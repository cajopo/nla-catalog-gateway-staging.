"""Offline integration of the single staging refresh coordinator."""

import json
import os
import runpy
import stat
import subprocess
import sys
import tarfile
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts import refresh_staging_catalog as refresh


@pytest.fixture
def pipeline(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    config = {
        "run_root": root / "runs",
        "config": root / "config",
        "store": root / "store",
        "current": "nla-catalog-staging-private",
        "image": "sha256:" + "1" * 64,
        "code_sha": "2" * 40,
        "shop": "synthetic.myshopify.com",
        "publication": "gid://shopify/Publication/123",
        "reference_manifest_sha256": "a" * 64,
        "reference_data_sha256": "b" * 64,
    }
    config["run_root"].mkdir()
    config["config"].mkdir()
    old_env = refresh.activation.env_bytes(
        {
            "NLA_ACTIVATION_SHA256": "3" * 64,
            "NLA_EVIDENCE_CODE_SHA": "4" * 40,
        }
    )
    (config["config"] / "accepted-runtime.env").write_bytes(old_env)
    events = []
    case = SimpleNamespace(config=config, events=events, failure=None, held=False)

    @contextmanager
    def lock(path):
        assert path == config["run_root"] and not case.held
        case.held = True
        events.append("lock")
        try:
            yield
        finally:
            case.held = False
            events.append("unlock")

    monkeypatch.setattr(refresh, "pipeline_lock", lock)
    monkeypatch.setattr(refresh.shutil, "disk_usage", lambda _: SimpleNamespace(free=10 * 1024**3))
    monkeypatch.setattr(refresh.activation, "private_read", lambda path: path.read_bytes())
    monkeypatch.setattr(refresh.activation, "sync_directory", lambda _: None)
    monkeypatch.setattr(
        refresh.activation,
        "inspect",
        lambda _: {"Id": "5" * 64, "Image": config["image"], "State": {"Running": True}},
    )
    monkeypatch.setattr(refresh.activation, "pointer", lambda _: ({}, "6" * 64))

    def child(args, **kwargs):
        assert case.held
        pending = json.loads((config["run_root"] / "pending-run.json").read_bytes())
        run = Path(args[-1])
        assert pending["run"] == run.name and run.is_dir()
        assert kwargs["timeout"] == 10800 and kwargs["check"] is True
        assert kwargs["env"] == {
            "PATH": os.defpath,
            "PYTHONPATH": str(refresh.ROOT / "src"),
            "PYTHONNOUSERSITE": "1",
        }
        assert args[1:3] == ["-m", "scripts.refresh_staging_catalog"]
        events.append("capture")
        if case.failure == "capture-exit":
            raise subprocess.CalledProcessError(1, args)
        if case.failure == "capture-timeout":
            raise subprocess.TimeoutExpired(args, 10800)
        if case.failure == "capture-json":
            return SimpleNamespace(stdout="not-json")
        capture = run / "capture"
        capture.mkdir()
        checkpoint = {
            "identity": {
                "sourceCodeSha": "wrong" if case.failure == "producer" else config["code_sha"],
                "shopDomain": "other.myshopify.com"
                if case.failure == "identity"
                else config["shop"],
                "onlineStorePublicationGid": config["publication"],
                "canonicalNameManifestSha256": config["reference_manifest_sha256"],
                "canonicalNameSidecarSha256": config["reference_data_sha256"],
            },
            "beforeObservedAt": "2026-09-21T12:00:00Z",
            "beforeCounts": {"products": 9, "published": 8, "singles": 8, "variants": 10},
            "summarySha256": "7" * 64,
            "packageManifestSha256": "8" * 64,
        }
        (capture / "capture-checkpoint.v1.json").write_text(json.dumps(checkpoint))
        return SimpleNamespace(
            stdout=json.dumps(
                {
                    "status": "pending" if case.failure == "pending" else "candidate-ready",
                    "manifestSha256": "wrong" if case.failure == "manifest" else "8" * 64,
                }
            )
        )

    monkeypatch.setattr(refresh.subprocess, "run", child)

    def load_plan(value):
        assert value["expected_id"] == "5" * 64 and value["old_pin"] == "3" * 64
        assert value["new_code"] == config["code_sha"]
        assert value["counts"] == {"products": 9, "published": 8, "singles": 8, "variants": 10}
        value.update({key: Path(value[key]) for key in ("capture", "store", "config", "work")})
        return SimpleNamespace(**value)

    monkeypatch.setattr(refresh.activation, "load_plan", load_plan)

    def verify(plan):
        assert case.held
        assert (
            json.loads((plan.capture / "operator-receipt.json").read_bytes())["status"]
            == "candidate-ready"
        )
        events.append("verify")
        if case.failure == "verify":
            raise RuntimeError("verification failed")

    def preflight(plan):
        assert case.held
        events.append("preflight")
        if case.failure == "preflight":
            raise RuntimeError("activation evidence rejected")
        return plan

    def apply(plan, checked):
        assert case.held and checked is plan
        events.append("apply")
        if case.failure == "apply":
            raise RuntimeError("activation outcome requires inspection")

    monkeypatch.setattr(refresh, "verify", verify)
    monkeypatch.setattr(refresh.activation, "preflight", preflight)
    monkeypatch.setattr(refresh.activation, "apply", apply)
    return case


def test_pipeline_holds_one_lock_until_success_and_records_source_age(pipeline):
    case = pipeline
    completed = refresh.run_once(Path("private-config.json"), case.config)
    root = case.config["run_root"]
    assert case.events == ["lock", "capture", "verify", "preflight", "apply", "unlock"]
    assert not case.held and not (root / "pending-run.json").exists()
    assert completed["sourceStartedAt"] == "2026-09-21T12:00:00Z"
    assert completed["activatedAt"] != completed["sourceStartedAt"]
    assert completed["activationSha256"] == "6" * 64
    assert json.loads((root / "last-success.json").read_bytes()) == completed
    assert json.loads((root / completed["run"] / "completed.json").read_bytes()) == completed


@pytest.mark.parametrize(
    "failure",
    [
        "capture-exit",
        "capture-timeout",
        "capture-json",
        "pending",
        "manifest",
        "producer",
        "identity",
        "verify",
        "preflight",
        "apply",
    ],
)
def test_failed_pipeline_retains_intent_and_blocks_next_export(pipeline, failure):
    case = pipeline
    case.failure = failure
    expected = {
        "capture-exit": subprocess.CalledProcessError,
        "capture-timeout": subprocess.TimeoutExpired,
        "capture-json": json.JSONDecodeError,
        "pending": ValueError,
        "manifest": ValueError,
        "producer": ValueError,
        "identity": ValueError,
        "verify": RuntimeError,
        "preflight": RuntimeError,
        "apply": RuntimeError,
    }[failure]
    with pytest.raises(expected):
        refresh.run_once(Path("private-config.json"), case.config)
    root = case.config["run_root"]
    retained = (root / "pending-run.json").read_bytes()
    assert not case.held and not (root / "last-success.json").exists()
    captures = case.events.count("capture")
    with pytest.raises(ValueError, match="prior run"):
        refresh.run_once(Path("private-config.json"), case.config)
    assert (root / "pending-run.json").read_bytes() == retained
    assert case.events.count("capture") == captures
    if failure not in ("apply",):
        assert "apply" not in case.events


@pytest.mark.parametrize("failure", ["space", "image", "stopped"])
def test_prelaunch_rejection_creates_no_run_or_pending(pipeline, monkeypatch, failure):
    case = pipeline
    if failure == "space":
        monkeypatch.setattr(refresh.shutil, "disk_usage", lambda _: SimpleNamespace(free=0))
    else:
        monkeypatch.setattr(
            refresh.activation,
            "inspect",
            lambda _: {
                "Image": "other" if failure == "image" else case.config["image"],
                "State": {"Running": failure != "stopped"},
            },
        )
    with pytest.raises(ValueError):
        refresh.run_once(Path("private-config.json"), case.config)
    assert list(case.config["run_root"].iterdir()) == []
    assert case.events == ["lock", "unlock"]


def test_terminal_publication_is_exclusive_and_replace_is_explicit(tmp_path, monkeypatch):
    synced = []
    monkeypatch.setattr(refresh.activation, "sync_directory", lambda path: synced.append(path))
    path = tmp_path / "receipt.json"
    refresh.publish(path, {"value": 1})
    assert path.stat().st_nlink == 1
    with pytest.raises(FileExistsError):
        refresh.publish(path, {"value": 2})
    assert json.loads(path.read_bytes()) == {"value": 1}
    refresh.publish(path, {"value": 3}, replace=True)
    assert json.loads(path.read_bytes()) == {"value": 3}
    assert synced == [tmp_path, tmp_path]


@pytest.mark.parametrize("mode", [[], ["--apply"], ["--capture-run", "run"]])
def test_cli_modes_are_explicit(monkeypatch, capsys, mode):
    calls = []
    monkeypatch.setattr(refresh, "configuration", lambda _: {})
    monkeypatch.setattr(refresh, "run_once", lambda *args: calls.append("apply") or {})
    monkeypatch.setattr(refresh, "capture", lambda *args: calls.append("capture") or {})
    assert refresh.main(["--config", "config.json", *mode]) == 0
    assert calls == ([] if not mode else ["apply" if mode[0] == "--apply" else "capture"])
    assert not capsys.readouterr().err


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        ["--config", "x", "--unknown=private"],
        ["--config", "x", "--apply", "--capture-run", "x"],
    ],
)
def test_cli_rejects_invalid_arguments_without_disclosure(capsys, arguments):
    assert refresh.main(arguments) == 1
    output = capsys.readouterr()
    assert (
        output.out == ""
        and output.err == "REFRESH_STOPPED_INSPECT_PENDING_RUN_NO_AUTOMATIC_RETRY\n"
    )


@pytest.fixture
def linux_configuration(tmp_path, monkeypatch):
    # Actual POSIX paths/archive semantics are verified by the Linux CI matrix.
    if sys.platform != "linux":
        return None
    root = tmp_path / "source"
    names = [
        "scripts/refresh_staging_catalog.py",
        "scripts/capture_shopify_bulk.py",
        "scripts/activate_staging_refresh.py",
        "scripts/verify_staging_runtime.py",
        "src/nla_catalog_gateway/runtime_api.py",
        "src/nla_catalog_gateway/taxonomy.json",
        "graphql/query.graphql",
    ]
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(name.encode())
    monkeypatch.setattr(refresh, "ROOT", root)
    monkeypatch.setattr(refresh.os, "geteuid", lambda: 0)
    monkeypatch.setattr(refresh.activation, "private_read", lambda path: path.read_bytes())
    overrides = {}
    native_stat = Path.stat

    def root_stat(path, *args, **kwargs):
        facts = list(native_stat(path, *args, **kwargs))
        facts[4] = 0
        if path in overrides:
            facts[0], facts[4] = overrides[path]
        return os.stat_result(facts)

    monkeypatch.setattr(Path, "stat", root_stat)
    values = {key: str(tmp_path / key) for key in refresh.PATHS}
    for key in refresh.PATHS - {"archive"}:
        Path(values[key]).mkdir(mode=0o700)
    values.update(
        {
            "code_sha": "2" * 40,
            "image": "sha256:" + "1" * 64,
            "shop": "synthetic.myshopify.com",
            "current": "nla-runtime",
            "publication": "gid://shopify/Publication/123",
        }
    )
    for name, key in (
        ("canonical-names-manifest.v1.json", "reference_manifest_sha256"),
        ("canonical-names.v1.jsonl", "reference_data_sha256"),
    ):
        path = Path(values["reference"]) / name
        path.write_bytes(b"synthetic bytes only")
        values[key] = refresh.activation.digest(path)
    case = SimpleNamespace(
        root=root,
        names=names,
        values=values,
        overrides=overrides,
        path=tmp_path / "configuration.json",
    )
    write_source_archive(case)
    return case


def write_source_archive(case, *, omit=None, extra=None, comment=None):
    with tarfile.open(
        case.values["archive"], "w", pax_headers={"comment": comment or case.values["code_sha"]}
    ) as archive:
        archive.add(case.root / "scripts", arcname="scripts", recursive=False)
        for name in case.names:
            if name != omit:
                archive.add(case.root / name, arcname=name)
        if extra is not None:
            archive.addfile(extra)
    case.values["archive_sha256"] = refresh.activation.digest(Path(case.values["archive"]))
    case.path.write_text(json.dumps(case.values))


def test_configuration_accepts_complete_pinned_source_and_reference(linux_configuration):
    case = linux_configuration
    if case is None:
        return
    config = refresh.configuration(case.path)
    assert config["run_root"] == Path(case.values["run_root"])
    assert config["code_sha"] == case.values["code_sha"]


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("run_root", None),
        ("run_root", "relative"),
        ("run_root", "/unsafe,path"),
        ("run_root", "/unnormalized//path"),
        ("run_root", "/x/../y"),
        ("code_sha", "wrong"),
        ("archive_sha256", None),
        ("image", "latest"),
        ("shop", None),
        ("publication", "bad"),
        ("current", "--option"),
    ],
)
def test_configuration_rejects_invalid_fields(linux_configuration, key, value):
    case = linux_configuration
    if case is None:
        return
    case.values[key] = value
    case.path.write_text(json.dumps(case.values))
    with pytest.raises(ValueError):
        refresh.configuration(case.path)


@pytest.mark.parametrize(
    "failure",
    [
        "fields",
        "directory-type",
        "directory-owner",
        "directory-mode",
        "archive-hash",
        "commit",
        "omitted",
        "modified",
        "reference",
        "traversal",
        "absolute",
        "symlink",
        "duplicate",
    ],
)
def test_configuration_rejects_unbound_or_unsafe_inputs(linux_configuration, failure):
    case = linux_configuration
    if case is None:
        return
    if failure == "fields":
        case.values["extra"] = True
    elif failure.startswith("directory-"):
        case.overrides[Path(case.values["run_root"])] = {
            "directory-type": (stat.S_IFREG | 0o700, 0),
            "directory-owner": (stat.S_IFDIR | 0o700, 1000),
            "directory-mode": (stat.S_IFDIR | 0o755, 0),
        }[failure]
    elif failure == "archive-hash":
        case.values["archive_sha256"] = "0" * 64
    elif failure == "commit":
        write_source_archive(case, comment="0" * 40)
    elif failure == "omitted":
        write_source_archive(case, omit=case.names[0])
    elif failure == "modified":
        (case.root / case.names[0]).write_bytes(b"changed")
    elif failure == "reference":
        case.values["reference_data_sha256"] = "0" * 64
    else:
        name = {
            "traversal": "../bad",
            "absolute": "/absolute",
            "symlink": "link",
            "duplicate": case.names[0],
        }[failure]
        entry = tarfile.TarInfo(name)
        if failure == "symlink":
            entry.type = tarfile.SYMTYPE
            entry.linkname = "target"
        write_source_archive(case, extra=entry)
    case.path.write_text(json.dumps(case.values))
    with pytest.raises(ValueError):
        refresh.configuration(case.path)


@pytest.mark.parametrize(("platform", "uid"), [("win32", 0), ("linux", 1000)])
def test_configuration_requires_root_linux_before_reading(monkeypatch, platform, uid):
    monkeypatch.setattr(refresh.sys, "platform", platform)
    monkeypatch.setattr(refresh.os, "geteuid", lambda: uid, raising=False)
    monkeypatch.setattr(refresh, "document", lambda _: pytest.fail("must refuse before reading"))
    with pytest.raises(ValueError, match="root Linux"):
        refresh.configuration(Path("unused"))


def test_entrypoint_missing_configuration_fails_without_disclosure(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["refresh_staging_catalog.py"])
    with pytest.raises(SystemExit, match="1"):
        runpy.run_path(refresh.__file__, run_name="__main__")
    assert "REFRESH_STOPPED" in capsys.readouterr().err


@pytest.mark.parametrize(
    "failure",
    [None, "outside", "missing", "noncanonical", "owner", "mode", "intent", "no-intent", "pending"],
)
def test_capture_requires_private_matching_intent_before_export(
    linux_configuration, monkeypatch, failure
):
    case = linux_configuration
    if case is None:
        return
    from scripts import capture_shopify_bulk

    from nla_catalog_gateway import shopify_capture_http

    config = refresh.configuration(case.path)
    run = config["run_root"] / "run-one"
    run.mkdir(mode=0o700)
    pending = config["run_root"] / "pending-run.json"
    pending.write_text(json.dumps({"run": run.name}))
    credentials = config["config"] / "shopify-app-credentials.json"
    credentials.write_text(json.dumps({"client_id": "example", "client_secret": "example-secret"}))
    calls = []
    client = object()
    monkeypatch.setattr(
        shopify_capture_http,
        "ShopifyCaptureHttp",
        lambda *args: calls.append(("client", args)) or client,
    )

    def wait(**kwargs):
        assert kwargs["client"] is client and kwargs["capture_directory"] == run / "capture"
        assert kwargs["code_sha"] == config["code_sha"] and kwargs["wait_seconds"] == 7200
        calls.append(("export", kwargs))
        return {"status": "pending" if failure == "pending" else "candidate-ready"}

    monkeypatch.setattr(capture_shopify_bulk, "wait_for_capture", wait)
    if failure == "outside":
        run = run.parent.parent
    elif failure == "missing":
        run = run.parent / "absent"
    elif failure == "noncanonical":
        run = run / ".." / run.name
    elif failure == "owner":
        case.overrides[run] = (stat.S_IFDIR | 0o700, 1000)
    elif failure == "mode":
        case.overrides[run] = (stat.S_IFDIR | 0o755, 0)
    elif failure == "intent":
        pending.write_text(json.dumps({"run": "other"}))
    elif failure == "no-intent":
        pending.unlink()
    if failure:
        with pytest.raises((ValueError, FileNotFoundError)):
            refresh.capture(config, run)
        if failure != "pending":
            assert calls == []
    else:
        assert refresh.capture(config, run) == {"status": "candidate-ready"}
        assert [call[0] for call in calls] == ["client", "export"]
        assert not (run / "capture" / "operator-receipt.json").exists()


@pytest.mark.parametrize("failure", [False, True])
def test_verifier_is_bounded_isolated_and_receipt_requires_success(tmp_path, monkeypatch, failure):
    plan = SimpleNamespace(
        capture=tmp_path,
        verifier="nla-refresh-test-runtime-verify",
        image="sha256:" + "1" * 64,
        manifest="2" * 64,
        summary="3" * 64,
        new_code="4" * 40,
        counts={"products": 9},
    )
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        assert kwargs == {"check": True, "capture_output": True, "text": True, "timeout": 1200}
        if failure:
            raise subprocess.CalledProcessError(1, args)
        return SimpleNamespace(stdout=json.dumps({"status": "verified"}))

    monkeypatch.setattr(refresh.subprocess, "run", run)
    monkeypatch.setattr(refresh.activation, "sync_directory", lambda _: None)
    receipt = tmp_path / "runtime-verification-receipt.json"
    if failure:
        with pytest.raises(subprocess.CalledProcessError):
            refresh.verify(plan)
        assert not receipt.exists()
    else:
        refresh.verify(plan)
        assert json.loads(receipt.read_bytes()) == {"status": "verified"}
    args = calls[0]
    assert args[:4] == ["/usr/bin/docker", "run", "--name", plan.verifier]
    assert "--network=none" in args and "--pull=never" in args and "--read-only" in args
    assert plan.image in args and args[-2:] == ["--record-count", "9"]
    assert "--memory=2g" in args and "--cpus=1" in args
    assert any("dst=/verify.py,readonly" in arg for arg in args)


def test_real_pipeline_lock_refuses_overlap_and_releases(linux_configuration):
    case = linux_configuration
    if case is None:
        return
    root = Path(case.values["run_root"])
    # fstat, unlike the fixture's path stat, must model the root service UID.
    native_fstat = refresh.os.fstat
    from unittest.mock import patch

    def root_fstat(fd):
        facts = list(native_fstat(fd))
        facts[4] = 0
        return os.stat_result(facts)

    with patch.object(refresh.os, "fstat", root_fstat):
        with refresh.pipeline_lock(root):
            with pytest.raises(BlockingIOError):
                with refresh.pipeline_lock(root):
                    pytest.fail("overlapping run acquired lock")
        with refresh.pipeline_lock(root):
            assert (root / ".pipeline.lock").exists()


@pytest.mark.parametrize("bad", ["type", "owner", "links", "mode"])
def test_pipeline_lock_rejects_unsafe_file(linux_configuration, monkeypatch, bad):
    case = linux_configuration
    if case is None:
        return
    root = Path(case.values["run_root"])
    native_fstat = refresh.os.fstat

    def unsafe(fd):
        facts = list(native_fstat(fd))
        facts[4] = 1000 if bad == "owner" else 0
        if bad == "type":
            facts[0] = stat.S_IFDIR | 0o600
        elif bad == "links":
            facts[3] = 2
        elif bad == "mode":
            facts[0] = stat.S_IFREG | 0o644
        return os.stat_result(facts)

    monkeypatch.setattr(refresh.os, "fstat", unsafe)
    with pytest.raises(ValueError, match="lock"):
        with refresh.pipeline_lock(root):
            pytest.fail("unsafe lock accepted")
