"""Cross-platform logic tests; Linux ownership/flock contracts are explicit seams."""

import copy
import hashlib
import json
import os
import sqlite3
import stat
import sys
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts import backup_checkpoint as checkpoint


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


class Budget:
    expires = datetime(2026, 10, 15, 12, tzinfo=UTC)

    def check(self, reserve=0):
        pass

    def remaining(self):
        return 20


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(checkpoint, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(checkpoint.os, "geteuid", lambda: 0, raising=False)
    for flag in ("O_NOFOLLOW", "O_NONBLOCK", "O_DIRECTORY"):
        monkeypatch.setattr(checkpoint.os, flag, 0, raising=False)
    monkeypatch.setattr(checkpoint, "_directory", lambda *a, **k: None)
    monkeypatch.setattr(checkpoint, "_regular", lambda *a, **k: None)
    monkeypatch.setattr(checkpoint, "_Budget", lambda *a, **k: Budget())
    monkeypatch.setattr(checkpoint.os, "fsync", lambda _: None)
    monkeypatch.setattr(checkpoint, "_signature", lambda facts: (facts.st_size,))
    original_open = checkpoint.os.open

    def compatible_open(path, flags, *args):
        if Path(path).is_dir():
            return original_open(os.devnull, os.O_RDONLY)
        return original_open(path, flags, *args)

    monkeypatch.setattr(checkpoint.os, "open", compatible_open)
    checkpoint_root = tmp_path / "jobs"
    checkpoint_root.mkdir()
    sources = tmp_path / "sources"
    sources.mkdir()

    def put(name, raw):
        path = sources / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return path

    pins = []
    for number in (1, 2):
        artifacts = []
        for name in sorted(checkpoint.GENERATION_FILES - {"staging-generation-manifest.v1.json"}):
            raw = (name + str(number)).encode()
            artifacts.append({"filename": name, "bytes": len(raw), "sha256": digest(raw)})
        manifest = json.dumps(
            {
                "schemaVersion": 1,
                "packageFormat": "nla-staging-generation-v1",
                "artifacts": artifacts,
            }
        ).encode()
        pin = digest(manifest)
        pins.append(pin)
        for item in artifacts:
            put(
                "store/generations/" + pin + "/" + item["filename"],
                (item["filename"] + str(number)).encode(),
            )
        put("store/generations/" + pin + "/staging-generation-manifest.v1.json", manifest)
    put(
        "store/activation.v1.json",
        json.dumps(
            {
                "schemaVersion": 1,
                "currentManifestSha256": pins[0],
                "previousManifestSha256": pins[1],
            }
        ).encode(),
    )
    reference = sources / "reference"
    put("reference/canonical-names-manifest.v1.json", b"reference-manifest")
    put("reference/canonical-names.v1.jsonl", b"reference-data")
    refresh = put(
        "refresh.json",
        json.dumps(
            {
                "reference": str(reference),
                "reference_manifest_sha256": digest(b"reference-manifest"),
                "reference_data_sha256": digest(b"reference-data"),
            }
        ).encode(),
    )
    private_file = put("private.env", b"private-fixture-content")
    put("tree/scripts/live.py", b"installed-hotfix")
    put("tree/config.json", b"source-config")
    ledger = sources / "ledger.sqlite3"
    with closing(sqlite3.connect(ledger)) as database:
        database.execute("CREATE TABLE ledger (id INTEGER)")
        database.execute("INSERT INTO ledger VALUES (42)")
        database.commit()
    market_lock = put("market/.pipeline.lock", b"")
    refresh_lock = put("refresh/.pipeline.lock", b"")
    image = "sha256:" + "a" * 64
    config = dict(
        store=str(sources / "store"),
        ledger=str(ledger),
        refresh_config=str(refresh),
        market_lock=str(market_lock),
        refresh_lock=str(refresh_lock),
        pending_markers=[
            str(market_lock.parent / "pending-market-run.json"),
            str(refresh_lock.parent / "pending-run.json"),
        ],
        services=["nla-market-catalog.service", "nla-catalog-refresh.service"],
        files=[dict(path=str(private_file), sha256=None, private=True)],
        trees=[
            dict(
                path=str(sources / "tree"),
                files={
                    "scripts/live.py": digest(b"installed-hotfix"),
                    "config.json": digest(b"source-config"),
                },
            )
        ],
        images=[image],
        containers={"nla-catalog-staging-private": image},
        max_seconds=600,
        schedule_guard_seconds=300,
    )
    monkeypatch.setattr(checkpoint, "OWNER_ROOTS", {sources / "store": 10001})
    events = []

    @contextmanager
    def lock(path):
        events.append("acquire:" + path.parent.name)
        try:
            yield
        finally:
            events.append("release:" + path.parent.name)

    monkeypatch.setattr(checkpoint, "_lock", lock)

    def command(arguments, budget):
        events.append(arguments[1])
        if arguments[0].endswith("systemctl"):
            return b"inactive\n"
        if arguments[1] == "container":
            return json.dumps(
                [
                    {
                        "State": {"Running": True},
                        "Image": image,
                        "Config": {"Env": ["fixture-secret=value"]},
                        "HostConfig": {"Memory": 1024},
                        "Mounts": [],
                    }
                ]
            ).encode()
        return json.dumps([{"Id": image, "Size": 100}]).encode()

    monkeypatch.setattr(checkpoint, "_run", command)

    def image_export(image, target, budget):
        target.write_bytes(b"saved-image")
        return dict(id=image, filename=target.name, sha256=digest(b"saved-image"), bytes=11)

    monkeypatch.setattr(checkpoint, "_image", image_export)
    return config, checkpoint_root / "one", sources, events


def test_complete_checkpoint_contains_every_recovery_input_and_releases_locks(setup):
    config, destination, sources, events = setup
    before = {path: path.read_bytes() for path in sources.rglob("*") if path.is_file()}
    manifest = checkpoint.capture(config, destination)
    assert manifest == json.loads((destination / "manifest.json").read_bytes())
    assert manifest["status"] == "checkpoint_complete"
    assert manifest["referencePath"] == str(sources / "reference")
    assert events[:2] == ["acquire:market", "acquire:refresh"]
    assert events[-2:] == ["release:refresh", "release:market"]
    assert len(manifest["files"]) == 15
    assert len(manifest["images"]) == 1
    for item in manifest["files"] + manifest["images"]:
        assert digest((destination / item["filename"]).read_bytes()) == item["sha256"]
    with closing(sqlite3.connect(destination / "ledger.sqlite3")) as database:
        assert database.execute("SELECT * FROM ledger").fetchall() == [(42,)]
    assert before == {path: path.read_bytes() for path in before}


@pytest.mark.parametrize(
    "failure", ["pending", "service", "container", "image", "pin", "tree", "reference"]
)
def test_fail_closed_never_completes_and_does_not_modify_sources(setup, monkeypatch, failure):
    config, destination, sources, _ = setup
    expected = checkpoint.CheckpointError
    if failure == "pending":
        Path(config["pending_markers"][0]).touch()
        expected = checkpoint.CheckpointBusy
    elif failure == "service":
        monkeypatch.setattr(checkpoint, "_run", lambda *_: b"active")
        expected = checkpoint.CheckpointBusy
    elif failure == "container":
        previous = checkpoint._run
        monkeypatch.setattr(
            checkpoint,
            "_run",
            lambda args, b: b"[]" if args[1] == "container" else previous(args, b),
        )
    elif failure == "image":
        previous = checkpoint._run
        monkeypatch.setattr(
            checkpoint,
            "_run",
            lambda args, b: (
                json.dumps([{"State": {"Running": False}, "Image": "wrong"}]).encode()
                if args[1] == "container"
                else previous(args, b)
            ),
        )
    elif failure == "pin":
        config["files"][0]["sha256"] = "0" * 64
    elif failure == "tree":
        (sources / "tree/unlisted.py").touch()
    else:
        (sources / "reference/canonical-names.v1.jsonl").write_bytes(b"changed")
    before = {path: path.read_bytes() for path in sources.rglob("*") if path.is_file()}
    with pytest.raises(expected, match=r"checkpoint (busy|rejected)"):
        checkpoint.capture(config, destination)
    assert not (destination / "manifest.json").exists()
    assert before == {path: path.read_bytes() for path in before}


def inspect_mounts(monkeypatch, before, after=None):
    previous = checkpoint._run
    inspections = []

    def run(arguments, budget):
        raw = previous(arguments, budget)
        if arguments[1] != "container":
            return raw
        value = json.loads(raw)
        value[0]["Mounts"] = before if not inspections or after is None else after
        inspections.append(True)
        return json.dumps(value).encode()

    monkeypatch.setattr(checkpoint, "_run", run)


def mounts_fixture():
    return [
        {
            "Type": "bind",
            "Name": "",
            "Source": "/var/lib/second",
            "Destination": "/z-last",
            "Driver": "",
            "Mode": "ro",
            "RW": False,
            "Propagation": "rprivate",
            "FutureMetadata": {"preserve": [1, 2]},
        },
        {"Type": "bind", "Source": "/var/lib/first", "Destination": "/a-first", "RW": True},
    ]


def test_reordered_mounts_complete_checkpoint_and_preserve_every_field(setup, monkeypatch):
    config, destination, _, _ = setup
    mounts = mounts_fixture()
    inspect_mounts(monkeypatch, mounts, list(reversed(mounts)))
    manifest = checkpoint.capture(config, destination)
    assert manifest["status"] == "checkpoint_complete"
    launch = json.loads((destination / "containers/nla-catalog-staging-private.json").read_bytes())
    assert launch["Mounts"] == sorted(mounts, key=lambda mount: mount["Destination"])
    assert launch["Mounts"][1] == mounts[0]
    assert launch["Config"] == {"Env": ["fixture-secret=value"]}
    assert launch["HostConfig"] == {"Memory": 1024}


@pytest.mark.parametrize(
    ("field", "changed"),
    [
        ("Type", "volume"),
        ("Name", "new-volume"),
        ("Source", "/changed"),
        ("Destination", "/changed"),
        ("Driver", "new-driver"),
        ("Mode", "rw"),
        ("RW", True),
        ("Propagation", "shared"),
        ("FutureMetadata", {"preserve": [1, 3]}),
    ],
)
def test_material_mount_change_still_rejects_checkpoint(setup, monkeypatch, field, changed):
    config, destination, _, _ = setup
    mounts = mounts_fixture()
    modified = copy.deepcopy(mounts)
    modified[0][field] = changed
    inspect_mounts(monkeypatch, mounts, modified)
    with pytest.raises(checkpoint.CheckpointError, match=r"^checkpoint rejected$"):
        checkpoint.capture(config, destination)
    assert destination.is_dir() and not (destination / "manifest.json").exists()


@pytest.mark.parametrize(
    "mounts",
    [
        None,
        {},
        [None],
        [{}],
        [{"Destination": 1}],
        [{"Destination": "/duplicate"}, {"Destination": "/duplicate"}],
    ],
)
def test_mounts_require_unique_string_destinations(setup, monkeypatch, mounts):
    config, _, _, _ = setup
    inspect_mounts(monkeypatch, mounts)
    with pytest.raises(checkpoint.CheckpointError, match=r"^checkpoint rejected$"):
        checkpoint._idle(config, Budget())


def test_source_changes_during_image_export_are_detected(setup, monkeypatch):
    config, destination, sources, _ = setup
    original = checkpoint._image

    def export(*args):
        (sources / "private.env").write_bytes(b"changed-private-content")
        return original(*args)

    monkeypatch.setattr(checkpoint, "_image", export)
    with pytest.raises(checkpoint.CheckpointError, match=r"^checkpoint rejected$"):
        checkpoint.capture(config, destination)
    assert not (destination / "manifest.json").exists()


def test_same_generation_is_copied_once(setup):
    config, destination, sources, _ = setup
    path = sources / "store/activation.v1.json"
    pointer = json.loads(path.read_bytes())
    pointer["previousManifestSha256"] = pointer["currentManifestSha256"]
    path.write_text(json.dumps(pointer))
    assert len(checkpoint.capture(config, destination)["files"]) == 12


def test_receipt_is_removed_on_durability_failure(setup, monkeypatch):
    config, destination, _, _ = setup
    previous = checkpoint.os.fsync

    def fsync(descriptor):
        if (destination / "manifest.json").exists():
            raise OSError("secret-child-output")
        previous(descriptor)

    monkeypatch.setattr(checkpoint.os, "fsync", fsync)
    with pytest.raises(checkpoint.CheckpointError, match=r"^checkpoint rejected$"):
        checkpoint.capture(config, destination)
    assert not (destination / "manifest.json").exists()


@pytest.mark.parametrize(
    "change",
    [
        "extra",
        "path",
        "same_locks",
        "pending",
        "services",
        "images",
        "duplicates",
        "container",
        "bounds",
        "dynamic",
        "file",
        "tree",
        "tree_path",
        "tree_pin",
        "tree_duplicate",
    ],
)
def test_configuration_rejects_unsafe_inventories(setup, change):
    config, destination, _, _ = setup
    config = copy.deepcopy(config)
    if change == "extra":
        config["extra"] = 1
    elif change == "path":
        config["store"] = "relative"
    elif change == "same_locks":
        config["market_lock"] = config["refresh_lock"]
    elif change == "pending":
        config["pending_markers"] = []
    elif change == "services":
        config["services"] = ["other.service"]
    elif change == "images":
        config["images"] = ["latest"]
    elif change == "duplicates":
        config["images"] *= 2
    elif change == "container":
        config["containers"] = {}
    elif change == "bounds":
        config["max_seconds"] = True
    elif change == "dynamic":
        config["files"][0]["private"] = False
    elif change == "file":
        config["files"] *= 2
    elif change == "tree":
        config["trees"][0]["files"] = {}
    elif change == "tree_path":
        config["trees"][0]["files"] = {str(destination): "0" * 64}
    elif change == "tree_pin":
        config["trees"][0]["files"]["scripts/live.py"] = "bad"
    else:
        config["trees"] *= 2
    with pytest.raises(checkpoint.CheckpointError):
        checkpoint.capture(config, destination)
    assert not destination.exists()


@pytest.mark.parametrize("case", ["platform", "existing", "inside_source", "interruption"])
def test_capture_boundary_and_interruptions(setup, monkeypatch, case):
    config, destination, sources, _ = setup
    expected = checkpoint.CheckpointError
    if case == "platform":
        monkeypatch.setattr(checkpoint, "sys", SimpleNamespace(platform="win32"))
    elif case == "existing":
        destination.mkdir()
    elif case == "inside_source":
        destination = sources / "tree/job"
    else:

        def interrupt(*args):
            raise KeyboardInterrupt

        monkeypatch.setattr(checkpoint, "_capture", interrupt)
        expected = KeyboardInterrupt
    with pytest.raises(expected):
        checkpoint.capture(config, destination)
    assert not (destination / "manifest.json").exists()


def test_sha_and_path_value_validation(tmp_path):
    assert checkpoint._sha("a" * 64) == "a" * 64
    assert checkpoint._path(str(tmp_path)) == tmp_path
    for value in (None, 12, "relative", "bad\npath"):
        with pytest.raises(checkpoint.CheckpointError):
            checkpoint._path(value)
    for value in (None, "0", "G" * 64):
        with pytest.raises(checkpoint.CheckpointError):
            checkpoint._sha(value)


@pytest.mark.parametrize("private,immutable", [(False, False), (True, False), (False, True)])
def test_regular_guards_reject_ownership_links_and_modes(private, immutable):
    values = dict(st_mode=stat.S_IFREG | (0o444 if immutable else 0o600), st_nlink=1, st_uid=0)
    checkpoint._regular(SimpleNamespace(**values), private=private, immutable=immutable)
    for key, value in (
        ("st_uid", 10001),
        ("st_nlink", 2),
        ("st_mode", stat.S_IFIFO | 0o600),
        ("st_mode", stat.S_IFREG | 0o666),
    ):
        with pytest.raises(checkpoint.CheckpointError):
            checkpoint._regular(
                SimpleNamespace(**{**values, key: value}), private=private, immutable=immutable
            )
    if private:
        with pytest.raises(checkpoint.CheckpointError):
            checkpoint._regular(
                SimpleNamespace(**{**values, "st_mode": stat.S_IFREG | 0o640}), private=True
            )


def test_directory_checks_every_ancestor_and_private_mode(monkeypatch):
    root = SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_uid=0)
    facts = SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_uid=10001)

    class Directory:
        parents = ()

        def lstat(self):
            return facts

        def stat(self):
            return facts

    path = Directory()
    ancestor = Directory()
    ancestor.lstat = lambda: root
    path.parents = (ancestor,)
    monkeypatch.setattr(checkpoint, "_owner", lambda p: 10001 if p is path else 0)
    checkpoint._directory(path, private=True)
    checkpoint._directory(path)
    facts.st_mode = stat.S_IFDIR | 0o555
    checkpoint._directory(path, immutable=True)
    facts.st_mode = stat.S_IFDIR | 0o700
    with pytest.raises(checkpoint.CheckpointError):
        checkpoint._directory(path, immutable=True)
    facts.st_mode = stat.S_IFDIR | 0o755
    with pytest.raises(checkpoint.CheckpointError):
        checkpoint._directory(path, private=True)
    root.st_mode = stat.S_IFDIR | 0o777
    with pytest.raises(checkpoint.CheckpointError):
        checkpoint._directory(path)


def test_owner_exception_is_narrow():
    assert checkpoint._owner(Path("/var/lib/nla-staging/activation.v1.json")) == 10001
    assert checkpoint._owner(Path("/var/lib/nla-staging-edge/data/cert")) == 10002
    assert checkpoint._owner(Path("/var/lib/nla-staging-other/file")) == 0


def test_budget_deadline_space_and_next_schedule(tmp_path, monkeypatch):
    class Clock(datetime):
        moment = datetime(2026, 10, 15, 12, tzinfo=UTC)

        @classmethod
        def now(cls, timezone):
            return cls.moment

    monkeypatch.setattr(checkpoint, "datetime", Clock)
    monotonic = [100]
    monkeypatch.setattr(checkpoint.time, "monotonic", lambda: monotonic[0])
    free = [checkpoint.MIN_FREE_BYTES + 100]
    monkeypatch.setattr(checkpoint.shutil, "disk_usage", lambda _: SimpleNamespace(free=free[0]))
    config = dict(max_seconds=600, schedule_guard_seconds=300)
    budget = checkpoint._Budget(config, tmp_path / "job")
    assert budget.remaining() == 600
    inherited = checkpoint._Budget(config, tmp_path / "job", deadline=120)
    assert inherited.remaining() == 20
    assert inherited.expires == Clock.moment.replace(second=20)
    assert checkpoint._Budget(config, tmp_path / "job", deadline=900).remaining() == 600
    budget.check(100)
    with pytest.raises(checkpoint.CheckpointError):
        budget.check(101)
    monotonic[0] = 700
    with pytest.raises(checkpoint.CheckpointError):
        budget.check()
    Clock.moment = datetime(2026, 10, 15, 13, 55, tzinfo=UTC)
    with pytest.raises(checkpoint.CheckpointBusy):
        checkpoint._Budget(config, tmp_path / "job")


def test_existing_lock_only_nonblocking_and_closed(tmp_path, monkeypatch):
    lock = tmp_path / ".pipeline.lock"
    lock.touch()
    monkeypatch.setattr(checkpoint, "_directory", lambda *a, **k: None)
    monkeypatch.setattr(checkpoint, "_regular", lambda *a, **k: None)
    monkeypatch.setattr(checkpoint.os, "O_NOFOLLOW", 0, raising=False)
    calls = []
    fake = SimpleNamespace(LOCK_EX=2, LOCK_NB=4, flock=lambda fd, flags: calls.append(flags))
    monkeypatch.setitem(sys.modules, "fcntl", fake)
    with checkpoint._lock(lock):
        assert calls == [6]

    def busy(*args):
        raise BlockingIOError

    fake.flock = busy
    with pytest.raises(checkpoint.CheckpointBusy):
        with checkpoint._lock(lock):
            pytest.fail("busy lock acquired")
    with pytest.raises(FileNotFoundError):
        with checkpoint._lock(tmp_path / "missing"):
            pytest.fail("missing lock created")


def test_run_has_deadline_suppressed_stderr_and_no_inherited_credentials(monkeypatch):
    def run(args, **kwargs):
        assert args == ["/usr/bin/systemctl", "show"]
        assert kwargs["stderr"] == checkpoint.subprocess.DEVNULL
        assert kwargs["timeout"] == 20
        assert set(kwargs["env"]) == {"PATH", "LC_ALL"}
        return SimpleNamespace(stdout=b"inactive")

    monkeypatch.setattr(checkpoint.subprocess, "run", run)
    assert checkpoint._run(["/usr/bin/systemctl", "show"], Budget()) == b"inactive"


def test_read_detects_source_replacement_and_streams_without_buffering(setup, monkeypatch):
    _, destination, sources, _ = setup
    path = sources / "private.env"
    actual_digest, raw, _ = checkpoint._read(path, Budget())
    assert actual_digest == digest(path.read_bytes()) and raw == b""
    assert checkpoint._read(path, Budget(), collect=True)[1] == path.read_bytes()
    monkeypatch.setattr(checkpoint, "_signature", lambda facts: object())
    with pytest.raises(checkpoint.CheckpointError):
        checkpoint._read(path, Budget(), target=destination / "copy")


def test_image_export_stream_success_timeout_and_failure(tmp_path, monkeypatch):
    image = "sha256:" + "a" * 64
    monkeypatch.setattr(checkpoint, "_run", lambda *a: json.dumps([dict(Id=image, Size=20)]))
    monkeypatch.setattr(checkpoint.os, "fsync", lambda _: None)
    process = None
    state = dict(status=0, fail=False, polls=0, waits=[])

    class Process:
        def __init__(self, args, **kwargs):
            nonlocal process
            assert args == ["/usr/bin/docker", "image", "save", image]
            read, write = os.pipe()
            os.write(write, b"docker-archive")
            os.close(write)
            self.stdout = os.fdopen(read, "rb")
            self.killed = False
            process = self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stdout.close()

        def wait(self, **kwargs):
            state["waits"].append(kwargs["timeout"])
            return state["status"]

        def kill(self):
            self.killed = True

    def select(*args):
        state["polls"] += 1
        if state["fail"]:
            raise TimeoutError("child-secret-output")
        return ([], [], []) if state["polls"] == 1 else ([process.stdout], [], [])

    monkeypatch.setattr(checkpoint.subprocess, "Popen", Process)
    monkeypatch.setattr(checkpoint.select, "select", select)
    result = checkpoint._image(image, tmp_path / "one.tar", Budget())
    assert result["sha256"] == digest(b"docker-archive")
    assert not process.killed
    assert process.stdout.closed and state["waits"] == [20]
    state["status"] = 1
    with pytest.raises(checkpoint.CheckpointError):
        checkpoint._image(image, tmp_path / "two.tar", Budget())
    assert process.killed
    assert process.stdout.closed and state["waits"][-1] == 10
    state["fail"] = True
    with pytest.raises(TimeoutError):
        checkpoint._image(image, tmp_path / "three.tar", Budget())
    assert process.killed
    assert process.stdout.closed and state["waits"][-1] == 10


def test_only_regular_bytecode_cache_is_excluded(setup):
    config, _, sources, _ = setup
    cache = sources / "tree/__pycache__"
    cache.mkdir()
    (cache / "source.cpython-312.pyc").write_bytes(b"generated")
    checkpoint._tree(config["trees"][0])
    (cache / "unknown.json").write_bytes(b"unexpected")
    with pytest.raises(checkpoint.CheckpointError):
        checkpoint._tree(config["trees"][0])


@pytest.mark.parametrize("valid", [False, True])
def test_last_refresh_receipt_is_bound_to_captured_pointer(setup, valid):
    config, destination, sources, _ = setup
    pointer = sources / "store/activation.v1.json"
    activation = json.loads(pointer.read_bytes())
    receipt = sources / "last-success.json"
    receipt.write_text(
        json.dumps(
            dict(
                activationSha256=digest(pointer.read_bytes()) if valid else "0" * 64,
                manifestSha256=activation["currentManifestSha256"],
            )
        )
    )
    config["files"].append(dict(path=str(receipt), sha256=None, private=True))
    if valid:
        checkpoint.capture(config, destination)
    else:
        with pytest.raises(checkpoint.CheckpointError):
            checkpoint.capture(config, destination)


def test_pending_appearing_after_capture_retains_failed_job_and_is_not_busy(setup, monkeypatch):
    config, destination, _, _ = setup
    previous = checkpoint._capture

    def captured(*args):
        manifest = previous(*args)
        Path(config["pending_markers"][0]).touch()
        return manifest

    monkeypatch.setattr(checkpoint, "_capture", captured)
    with pytest.raises(checkpoint.CheckpointError) as error:
        checkpoint.capture(config, destination)
    assert type(error.value) is checkpoint.CheckpointError
    assert destination.is_dir() and not (destination / "manifest.json").exists()


def test_online_ledger_backup_includes_committed_wal_pages(setup):
    config, destination, _, _ = setup
    destination.mkdir()
    with closing(sqlite3.connect(config["ledger"])) as live:
        live.execute("PRAGMA journal_mode=WAL")
        live.execute("INSERT INTO ledger VALUES (99)")
        live.commit()
        assert Path(config["ledger"] + "-wal").is_file()
        result = checkpoint._ledger(
            Path(config["ledger"]), destination / "ledger.sqlite3", Budget()
        )
        assert result["sha256"] == digest((destination / "ledger.sqlite3").read_bytes())
        with closing(sqlite3.connect(destination / "ledger.sqlite3")) as restored:
            assert restored.execute("SELECT * FROM ledger ORDER BY id").fetchall() == [(42,), (99,)]
