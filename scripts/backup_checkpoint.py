"""Private Linux recovery checkpoint; no network backup or source mutation.

The caller supplies a reviewed, exact source inventory. A completion manifest is
written last and only after both pipeline locks have been released. Failed job
directories remain private for inspection; this module never removes a source.
"""

import hashlib
import json
import os
import re
import select
import shutil
import sqlite3
import stat
import subprocess
import sys
import time
from contextlib import ExitStack, closing, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

MIN_FREE_BYTES = 6 * 1024**3
CHUNK_BYTES = 1024 * 1024
FIELDS = {
    "store",
    "ledger",
    "refresh_config",
    "market_lock",
    "refresh_lock",
    "pending_markers",
    "services",
    "files",
    "trees",
    "images",
    "containers",
    "max_seconds",
    "schedule_guard_seconds",
}
OWNER_ROOTS = {Path("/var/lib/nla-staging"): 10001, Path("/var/lib/nla-staging-edge"): 10002}
GENERATION_FILES = {
    "staging-generation-manifest.v1.json",
    "catalog-core-evidence.v1.json",
    "catalog-projection.v1.sqlite3",
}


class CheckpointError(ValueError):
    """Value-free rejection; source content must never enter operator output."""


class CheckpointBusy(CheckpointError):
    """The checkpoint cannot safely start while a pipeline may be running."""


def _require(condition):
    if not condition:
        raise CheckpointError("checkpoint rejected")


def _sha(value):
    _require(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None)
    return value


def _path(value):
    _require(type(value) is str and not any(c in value for c in "\x00\r\n"))
    path = Path(value)
    _require(path.is_absolute() and str(path) == value and ".." not in path.parts)
    _require(path.resolve() == path)
    return path


def _owner(path):
    return next((uid for root, uid in OWNER_ROOTS.items() if path.is_relative_to(root)), 0)


def _directory(path, *, private=False, immutable=False):
    # Checking every ancestor prevents a writable or symlink parent from replacing
    # a validated source. UID 10001 is allowed only at generation directories.
    for parent in reversed((path, *path.parents)):
        facts = parent.lstat()
        _require(stat.S_ISDIR(facts.st_mode) and facts.st_uid == _owner(parent))
        _require(not facts.st_mode & 0o022)
    if private:
        _require(stat.S_IMODE(path.stat().st_mode) == 0o700)
    if immutable:
        _require(not path.stat().st_mode & 0o222)


def _regular(facts, *, private=False, uid=0, immutable=False):
    _require(stat.S_ISREG(facts.st_mode) and facts.st_nlink == 1 and facts.st_uid == uid)
    _require(not facts.st_mode & (0o222 if immutable else 0o022))
    if private:
        _require(stat.S_IMODE(facts.st_mode) == 0o600)


def _signature(facts):
    return (facts.st_dev, facts.st_ino, facts.st_size, facts.st_mtime_ns, facts.st_ctime_ns)


def _config(value):
    _require(type(value) is dict and set(value) == FIELDS)
    result = dict(value)
    for key in ("store", "ledger", "refresh_config", "market_lock", "refresh_lock"):
        result[key] = _path(value[key])
    _require(result["market_lock"] != result["refresh_lock"])
    for key in ("pending_markers", "services", "files", "trees", "images"):
        _require(type(value[key]) is list and len(value[key]) > 0)
    result["pending_markers"] = [_path(p) for p in value["pending_markers"]]
    _require(
        {
            result["market_lock"].parent / "pending-market-run.json",
            result["refresh_lock"].parent / "pending-run.json",
        }
        <= set(result["pending_markers"])
    )
    _require(
        set(value["services"]) == {"nla-market-catalog.service", "nla-catalog-refresh.service"}
    )
    for unit in value["services"]:
        _require(type(unit) is str and re.fullmatch(r"[a-zA-Z0-9_-]+\.service", unit))
    for image in value["images"]:
        _require(type(image) is str and image.startswith("sha256:"))
        _sha(image[7:])
    _require(len(set(value["images"])) == len(value["images"]))
    _require(type(value["containers"]) is dict and len(value["containers"]) > 0)
    for name, image in value["containers"].items():
        _require(type(name) is str and re.fullmatch(r"[a-zA-Z0-9_-]+", name))
        _require(image in value["images"])
    _require(set(value["containers"].values()) == set(value["images"]))
    for key, minimum in (("max_seconds", 1), ("schedule_guard_seconds", 60)):
        _require(type(value[key]) is int and minimum <= value[key] <= 3600)
    sources = set()
    for entry in value["files"]:
        _require(type(entry) is dict and set(entry) == {"path", "sha256", "private"})
        _require(type(entry["private"]) is bool)
        path = _path(entry["path"])
        if entry["sha256"] is not None:
            _sha(entry["sha256"])
        else:
            _require(entry["private"])
        _require(path not in sources)
        sources.add(path)
    for tree in value["trees"]:
        _require(type(tree) is dict and set(tree) == {"path", "files"})
        root = _path(tree["path"])
        _require(len(root.parts) >= 3)
        _require(type(tree["files"]) is dict and len(tree["files"]) > 0)
        for name, pin in tree["files"].items():
            _require(type(name) is str and name != ".")
            path = _path(str(root / name))
            _require(path.is_relative_to(root) and path != root and path not in sources)
            _sha(pin)
            sources.add(path)
    return result


class _Budget:
    def __init__(self, config, destination):
        now = datetime.now(UTC)
        future = [
            now.replace(hour=hour, minute=0, second=0, microsecond=0) + timedelta(days=day)
            for day in (0, 1)
            for hour in (2, 3, 14, 15)
        ]
        following = min(moment for moment in future if moment >= now)
        available = (following - now).total_seconds() - config["schedule_guard_seconds"]
        if available < config["max_seconds"]:
            raise CheckpointBusy("checkpoint busy")
        self.deadline = time.monotonic() + config["max_seconds"]
        self.expires = now + timedelta(seconds=config["max_seconds"])
        self.destination = destination

    def check(self, reserve=0):
        _require(time.monotonic() < self.deadline)
        _require(shutil.disk_usage(self.destination.parent).free >= MIN_FREE_BYTES + reserve)

    def remaining(self):
        self.check()
        return max(0.001, self.deadline - time.monotonic())


@contextmanager
def _lock(path):
    import fcntl

    _directory(path.parent, private=True)
    # Locks must already exist: never create an alternate coordination inode.
    descriptor = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
    try:
        _regular(os.fstat(descriptor), private=True)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise CheckpointBusy("checkpoint busy") from None
        _require(_signature(path.lstat()) == _signature(os.fstat(descriptor)))
        yield
    finally:
        os.close(descriptor)


def _run(arguments, budget):
    budget.check()
    return subprocess.run(  # noqa: S603 -- fixed executable, validated arguments, no shell
        arguments,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=budget.remaining(),
        env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"},
    ).stdout


def _idle(config, budget):
    if any(os.path.lexists(path) for path in config["pending_markers"]):
        raise CheckpointBusy("checkpoint busy")
    for unit in config["services"]:
        state = _run(
            [
                "/usr/bin/systemctl",
                "show",
                "--property=ActiveState",
                "--value",
                unit,
            ],
            budget,
        ).strip()
        if state != b"inactive":
            raise CheckpointBusy("checkpoint busy")
    launches = []
    for name, image in config["containers"].items():
        containers = json.loads(_run(["/usr/bin/docker", "container", "inspect", name], budget))
        _require(len(containers) == 1)
        _require(containers[0]["State"]["Running"] is True and containers[0]["Image"] == image)
        launches.append(
            {
                "name": name,
                **{key: containers[0][key] for key in ("Image", "Config", "HostConfig", "Mounts")},
            }
        )
    return launches


def _new_file(path):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    return os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb")


def _read(path, budget, *, private=False, uid=0, immutable=False, target=None, collect=False):
    _directory(path.parent)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as source, ExitStack() as stack:
        facts = os.fstat(source.fileno())
        _regular(facts, private=private, uid=uid, immutable=immutable)
        budget.check(facts.st_size)
        output = stack.enter_context(_new_file(target)) if target is not None else None
        digest, content = hashlib.sha256(), bytearray()
        while chunk := source.read(CHUNK_BYTES):
            budget.check(len(chunk))
            digest.update(chunk)
            if output is None:
                if collect:
                    _require(len(content) + len(chunk) <= CHUNK_BYTES)
                    content.extend(chunk)
            else:
                output.write(chunk)
        if output is not None:
            output.flush()
            os.fsync(output.fileno())
        _require(_signature(facts) == _signature(os.fstat(source.fileno())))
        _require(_signature(facts) == _signature(path.lstat()))
    return digest.hexdigest(), bytes(content), facts


def _record(path, target, destination, budget, *, pin=None, **checks):
    digest, _, facts = _read(path, budget, target=target, **checks)
    _require(pin is None or digest == pin)
    return {
        "source": str(path),
        "filename": target.relative_to(destination).as_posix(),
        "sha256": digest,
        "bytes": facts.st_size,
        "uid": facts.st_uid,
        "mode": stat.S_IMODE(facts.st_mode),
    }


def _tree(tree):
    root = Path(tree["path"])
    _directory(root)
    found = set()
    for directory, directories, filenames in os.walk(root, followlinks=False):
        for name in directories:
            _directory(Path(directory) / name)
        for name in filenames:
            path = Path(directory) / name
            _regular(path.lstat())
            if path.parent.name == "__pycache__":
                _require(path.suffix == ".pyc")
                continue
            found.add(path.relative_to(root).as_posix())
    _require(found == set(tree["files"]))


def _ledger(path, target, budget):
    _directory(path.parent, private=True)
    before = path.lstat()
    _regular(before, private=True)
    budget.check(before.st_size * 2)
    # Online backup includes committed WAL pages without copying live SQLite files.
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=0)) as source:
        with _new_file(target):
            pass
        with closing(sqlite3.connect(target)) as destination:
            source.backup(
                destination, pages=128, progress=lambda *_: budget.check(CHUNK_BYTES), sleep=0.01
            )
            _require(destination.execute("PRAGMA quick_check").fetchall() == [("ok",)])
    _require((before.st_dev, before.st_ino) == (path.stat().st_dev, path.stat().st_ino))
    with target.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
        os.fsync(stream.fileno())
    return {
        "source": str(path),
        "filename": "ledger.sqlite3",
        "sha256": digest,
        "bytes": target.stat().st_size,
        "uid": 0,
        "mode": 0o600,
    }


def _image(image, target, budget):
    inspected = json.loads(_run(["/usr/bin/docker", "image", "inspect", image], budget))
    _require(len(inspected) == 1 and inspected[0]["Id"] == image)
    _require(type(inspected[0]["Size"]) is int and inspected[0]["Size"] > 0)
    budget.check(inspected[0]["Size"] * 2)
    with (
        _new_file(target) as output,
        subprocess.Popen(  # noqa: S603
            ["/usr/bin/docker", "image", "save", image],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
        ) as process,
    ):
        digest, size = hashlib.sha256(), 0
        try:
            while True:
                budget.check(CHUNK_BYTES)
                ready, _, _ = select.select([process.stdout], [], [], min(1, budget.remaining()))
                if not ready:
                    continue
                chunk = os.read(process.stdout.fileno(), CHUNK_BYTES)
                if not chunk:
                    break
                output.write(chunk)
                digest.update(chunk)
                size += len(chunk)
            _require(process.wait(timeout=budget.remaining()) == 0 and size > 0)
            output.flush()
            os.fsync(output.fileno())
        except BaseException:
            process.kill()
            process.wait()
            raise
    return {"id": image, "filename": target.name, "sha256": digest.hexdigest(), "bytes": size}


def _capture(config, destination, budget, launches):
    records, originals = [], []
    for launch in launches:
        relative = "containers/" + launch["name"] + ".json"
        raw = json.dumps(launch, sort_keys=True).encode()
        with _new_file(destination / relative) as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        records.append(
            {
                "source": "docker://" + launch["name"],
                "filename": relative,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw),
                "uid": 0,
                "mode": 0o600,
            }
        )

    def copy(path, relative, **checks):
        target = destination / relative
        record = _record(path, target, destination, budget, **checks)
        records.append(record)
        originals.append((path, checks, record["sha256"]))

    pointer = config["store"] / "activation.v1.json"
    # Exact pointer ownership exception, never an arbitrary allowlisted file.
    _require(_owner(pointer) == 10001)
    copy(pointer, "activation.v1.json", uid=10001, private=True)
    activation_sha = records[-1]["sha256"]
    activation = json.loads((destination / "activation.v1.json").read_bytes())
    _require(
        set(activation) == {"schemaVersion", "currentManifestSha256", "previousManifestSha256"}
    )
    _require(activation["schemaVersion"] == 1)
    generations = {}
    for role in ("current", "previous"):
        pin = _sha(activation[role + "ManifestSha256"])
        generations[role] = pin
        root = config["store"] / "generations" / pin
        _directory(root, immutable=True)
        _require({entry.name for entry in root.iterdir()} == GENERATION_FILES)
        manifest_path = root / "staging-generation-manifest.v1.json"
        digest, raw, _ = _read(manifest_path, budget, uid=10001, immutable=True, collect=True)
        _require(digest == pin)
        manifest = json.loads(raw)
        _require(
            manifest["schemaVersion"] == 1
            and manifest["packageFormat"] == "nla-staging-generation-v1"
        )
        artifacts = {item["filename"]: item for item in manifest["artifacts"]}
        _require(
            len(manifest["artifacts"]) == 2
            and set(artifacts) == GENERATION_FILES - {manifest_path.name}
        )
        if any(record["filename"].startswith("generations/" + pin + "/") for record in records):
            continue
        copy(
            manifest_path,
            "generations/" + pin + "/" + manifest_path.name,
            pin=pin,
            uid=10001,
            immutable=True,
        )
        for name, artifact in artifacts.items():
            _require((root / name).stat().st_size == artifact["bytes"])
            copy(
                root / name,
                "generations/" + pin + "/" + name,
                pin=_sha(artifact["sha256"]),
                uid=10001,
                immutable=True,
            )
    copy(config["refresh_config"], "refresh-config.json", private=True)
    refresh = json.loads((destination / "refresh-config.json").read_bytes())
    reference = _path(refresh["reference"])
    for name, key in (
        ("canonical-names-manifest.v1.json", "reference_manifest_sha256"),
        ("canonical-names.v1.jsonl", "reference_data_sha256"),
    ):
        copy(reference / name, "reference/" + name, pin=_sha(refresh[key]))
    for index, entry in enumerate(config["files"]):
        copy(
            Path(entry["path"]),
            f"files/{index:04d}",
            pin=entry["sha256"],
            private=entry["private"],
            uid=10002 if _owner(Path(entry["path"])) == 10002 else 0,
        )
        if Path(entry["path"]).name == "last-success.json":
            receipt = json.loads((destination / f"files/{index:04d}").read_bytes())
            _require(receipt["activationSha256"] == activation_sha)
            _require(receipt["manifestSha256"] == generations["current"])
    for index, tree in enumerate(config["trees"]):
        _tree(tree)
        for name, pin in tree["files"].items():
            copy(Path(tree["path"]) / name, f"trees/{index:04d}/" + name, pin=pin)
    records.append(_ledger(config["ledger"], destination / "ledger.sqlite3", budget))
    images = [
        _image(image, destination / (image[7:] + ".tar"), budget) for image in config["images"]
    ]
    for tree in config["trees"]:
        _tree(tree)
    for path, checks, pin in originals:
        digest, _, _ = _read(
            path, budget, **{key: value for key, value in checks.items() if key != "pin"}
        )
        _require(digest == pin)
    return {
        "schemaVersion": 1,
        "status": "checkpoint_complete",
        "files": records,
        "images": images,
        "generations": generations,
        "activationSha256": activation_sha,
        "referencePath": str(reference),
        "createdAt": datetime.now(UTC).isoformat(),
        "expiresAt": budget.expires.isoformat(),
    }


def capture(config, destination):
    """Capture into a new private directory; return its private completion manifest.

    ``CheckpointBusy`` means no safe idle window. All other failures raise
    ``CheckpointError``. Errors contain no paths, secrets or child-process output.
    No completion manifest exists after a failed capture. Caller owns retention.
    """
    receipt = None
    try:
        _require(__debug__ and sys.platform == "linux" and os.geteuid() == 0)
        config = _config(config)
        destination = _path(str(destination))
        _require(not os.path.lexists(destination))
        _directory(destination.parent, private=True)
        sources = [config[key] for key in ("store", "ledger", "refresh_config")]
        sources += [Path(item["path"]) for item in config["files"] + config["trees"]]
        _require(
            not any(
                destination.is_relative_to(path) or path.is_relative_to(destination)
                for path in sources
            )
        )
        budget = _Budget(config, destination)
        budget.check()
        with _lock(config["market_lock"]), _lock(config["refresh_lock"]):
            launches = _idle(config, budget)
            destination.mkdir(mode=0o700)
            manifest = _capture(config, destination, budget, launches)
            try:
                _require(_idle(config, budget) == launches)
            except CheckpointBusy:
                raise CheckpointError("checkpoint rejected") from None
            budget.check()
        # Receipt attests that locks were released before any network upload.
        receipt = destination / "manifest.json"
        budget.check()
        with _new_file(receipt) as output:
            output.write(json.dumps(manifest, sort_keys=True).encode())
            output.flush()
            os.fsync(output.fileno())
        descriptor = os.open(destination, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return manifest
    except CheckpointBusy:
        raise
    except Exception:
        if receipt is not None:
            receipt.unlink(missing_ok=True)
        raise CheckpointError("checkpoint rejected") from None
