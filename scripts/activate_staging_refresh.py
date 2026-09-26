"""One application-specific staging replacement; default is read-only preflight.

A private activation plan supplies expected capture evidence and current runtime
identity. No Shopify calls, new export, image upgrade, timer or cleanup. A failed
or interrupted operation retains named resources and requires inspection before
retry. Run under an exclusive pipeline lock and a bounded service.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath

FILES = {
    "staging-generation-manifest.v1.json",
    "catalog-core-evidence.v1.json",
    "catalog-projection.v1.sqlite3",
}
ENV_KEYS = {"NLA_ACTIVATION_SHA256", "NLA_EVIDENCE_CODE_SHA"}


@dataclass(frozen=True)
class ActivationPlan:
    capture: Path
    store: Path
    config: Path
    work: Path
    run_id: str
    current: str
    expected_id: str
    image: str
    old_pin: str
    old_code: str
    new_code: str
    summary: str
    manifest: str
    started: str
    shop: str
    counts: dict

    @property
    def prefix(self):
        return "nla-refresh-" + self.run_id

    @property
    def verifier(self):
        return self.prefix + "-runtime-verify"

    @property
    def backup(self):
        return self.prefix + "-before"

    @property
    def candidate(self):
        return self.prefix + "-candidate"

    @property
    def failed(self):
        return self.prefix + "-failed"

    @property
    def restored(self):
        return self.prefix + "-restored"


def load_plan(value):
    """Expected evidence is supplied by the coordinator, not inferred from files."""
    if type(value) is not dict or set(value) != set(ActivationPlan.__annotations__):
        raise ValueError("invalid activation plan fields")
    for key in ("capture", "store", "config", "work"):
        path = value[key]
        if (
            type(path) is not str
            or not path.startswith("/")
            or str(PurePosixPath(path)) != path
            or ".." in PurePosixPath(path).parts
            or any(character in path for character in (",", "\x00", "\n", "\r"))
        ):
            raise ValueError("invalid activation plan path")
    for key in ("old_pin", "summary", "manifest", "expected_id"):
        if type(value[key]) is not str or re.fullmatch("[0-9a-f]{64}", value[key]) is None:
            raise ValueError("invalid activation plan pin")
    for key in ("old_code", "new_code"):
        if type(value[key]) is not str or re.fullmatch("[0-9a-f]{40}", value[key]) is None:
            raise ValueError("invalid activation producer pin")
    for key in ("run_id", "current"):
        if (
            type(value[key]) is not str
            or re.fullmatch("[a-z0-9][a-z0-9-]{0,60}", value[key]) is None
        ):
            raise ValueError("invalid activation resource name")
    if (
        type(value["image"]) is not str
        or re.fullmatch("sha256:[0-9a-f]{64}", value["image"]) is None
        or type(value["shop"]) is not str
        or re.fullmatch("[a-z0-9][a-z0-9-]*\\.myshopify\\.com", value["shop"]) is None
    ):
        raise ValueError("invalid activation runtime identity")
    datetime.strptime(value["started"], "%Y-%m-%dT%H:%M:%SZ")
    counts = value["counts"]
    if (
        type(counts) is not dict
        or set(counts) != {"products", "published", "singles", "variants"}
        or any(type(n) is not int or n < 0 for n in counts.values())
        or counts["products"] < 1
    ):
        raise ValueError("invalid activation capture counts")
    return ActivationPlan(
        **{
            **value,
            **{key: Path(value[key]) for key in ("capture", "store", "config", "work")},
            "counts": dict(counts),
        }
    )


class InspectBeforeRetry(RuntimeError):
    pass


def docker(*args):
    return subprocess.run(  # noqa: S603 -- fixed executable, argument array, no shell
        ["/usr/bin/docker", *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def inspect(name):
    return json.loads(docker("inspect", name))[0]


def private_read(path):
    facts = path.lstat()
    assert stat.S_ISREG(facts.st_mode) and facts.st_nlink == 1
    assert facts.st_uid == 0 and stat.S_IMODE(facts.st_mode) == 0o600
    return path.read_bytes()


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def pointer(plan):
    path = plan.store / "activation.v1.json"
    facts = path.lstat()
    assert stat.S_ISREG(facts.st_mode) and facts.st_nlink == 1
    raw = path.read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def pointer_pin(current, previous):
    raw = json.dumps(
        {"schemaVersion": 1, "currentManifestSha256": current, "previousManifestSha256": previous},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(raw).hexdigest()


def private_write(path, raw):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def env_bytes(values):
    return "".join(k + "=" + v + "\n" for k, v in values.items()).encode()


def note(plan, stage):
    private_write(plan.work / (stage + ".json"), json.dumps({"stage": stage}).encode())
    print(stage, flush=True)


def preflight(plan):
    if not __debug__:
        raise InspectBeforeRetry("assertions_required")
    assert os.geteuid() == 0 and not plan.work.exists() and not plan.work.is_symlink()
    parent = plan.work.parent
    assert parent.resolve() == parent and parent.is_dir()
    assert parent.stat().st_uid == 0 and stat.S_IMODE(parent.stat().st_mode) == 0o700
    assert (
        plan.config.resolve() == plan.config and stat.S_IMODE(plan.config.stat().st_mode) == 0o700
    )
    assert plan.config.stat().st_uid == 0
    for directory in (plan.store, plan.store / "generations"):
        assert directory.resolve() == directory and directory.is_dir()
        assert directory.stat().st_uid == 10001
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    # The locked coordinator publishes this terminal receipt only after its
    # capture subprocess exits successfully. A separate per-run systemd unit is
    # unnecessary; missing/ambiguous completion cannot produce this receipt.
    receipt = json.loads(private_read(plan.capture / "operator-receipt.json"))
    checkpoint = json.loads(private_read(plan.capture / "capture-checkpoint.v1.json"))
    verified = json.loads(private_read(plan.capture / "runtime-verification-receipt.json"))
    manifest = receipt["manifestSha256"]
    assert manifest == plan.manifest
    assert re.fullmatch("[0-9a-f]{64}", manifest)
    assert receipt["status"] == "candidate-ready" and receipt["activeCatalogChanged"] is False
    # Acquisition and packaging may use different revisions during recovery.
    # Preserve the original acquisition pin; the verifier binds the producer below.
    assert receipt["codeSha"] == checkpoint["identity"]["sourceCodeSha"]
    assert re.fullmatch("[0-9a-f]{40}", receipt["codeSha"])
    assert checkpoint["packageManifestSha256"] == manifest
    assert checkpoint["summarySha256"] == verified["summarySha256"] == plan.summary
    assert receipt["captureStartedAt"] == checkpoint["beforeObservedAt"] == plan.started
    assert receipt["counts"] == checkpoint["beforeCounts"] == plan.counts
    assert verified["status"] == "verified" and verified["runtimeBinding"] is True
    assert verified["manifestSha256"] == manifest and verified["producerCodeSha"] == plan.new_code
    assert (
        verified["records"] == plan.counts["products"] and verified["activeCatalogChanged"] is False
    )
    verifier = inspect(plan.verifier)
    assert verifier["Image"] == plan.image and verifier["State"]["Status"] == "exited"
    assert verifier["State"]["ExitCode"] == 0 and not verifier["State"]["OOMKilled"]
    old = inspect(plan.current)
    assert old["Id"] == plan.expected_id and old["Image"] == plan.image and old["State"]["Running"]
    names = docker("ps", "-a", "--format", "{{.Names}}").splitlines()
    for name in (
        plan.backup,
        plan.candidate,
        plan.failed,
        plan.restored,
        plan.prefix + "-promote",
        plan.prefix + "-rollback",
    ):
        assert name not in names
    old_bytes = private_read(plan.config / "accepted-runtime.env")
    values = dict(line.split("=", 1) for line in old_bytes.decode().splitlines())
    live = dict(item.split("=", 1) for item in old["Config"]["Env"])
    assert all(live.get(k) == v for k, v in values.items())
    assert values["NLA_ACTIVATION_SHA256"] == plan.old_pin
    assert values["NLA_EVIDENCE_CODE_SHA"] == plan.old_code
    assert values["NLA_STAGING_STORE_ROOT"] == "/var/lib/nla-catalog"
    assert values["NLA_SHOP_DOMAIN"] == plan.shop
    assert values["NLA_APP_PROXY_SIGNED_PATH_PREFIX"] == "/apps/nla-catalog"
    assert values["NLA_APP_PROXY_BACKEND_PATH"] == "/proxy/catalog"
    before, pin = pointer(plan)
    assert pin == plan.old_pin and before["currentManifestSha256"] != manifest
    source = plan.capture / "candidate"
    assert source.resolve() == source and source.is_dir()
    assert stat.S_IMODE(source.stat().st_mode) == 0o555
    assert {p.name for p in source.iterdir()} == FILES
    assert digest(source / "staging-generation-manifest.v1.json") == manifest
    contract = json.loads((source / "staging-generation-manifest.v1.json").read_bytes())
    artifacts = {item["filename"]: item for item in contract["artifacts"]}
    assert set(artifacts) == FILES - {"staging-generation-manifest.v1.json"}
    for name in FILES:
        path = source / name
        f = path.lstat()
        assert stat.S_ISREG(f.st_mode) and f.st_nlink == 1
        assert stat.S_IMODE(f.st_mode) == 0o444
        if name in artifacts:
            assert f.st_size == artifacts[name]["bytes"]
            assert digest(path) == artifacts[name]["sha256"]
    destination = plan.store / "generations" / manifest
    assert not destination.exists() and not destination.is_symlink()
    return old, old_bytes, values, before, manifest, source, destination


def install(source, destination):
    destination.mkdir(mode=0o700)
    for name in sorted(FILES):
        target = destination / name
        with (source / name).open("rb") as src, target.open("xb") as out:
            shutil.copyfileobj(src, out, 1024 * 1024)
            out.flush()
            os.fsync(out.fileno())
        assert digest(target) == digest(source / name)
        os.chown(target, 10001, 10001)
        target.chmod(0o444)
    os.chown(destination, 10001, 10001)
    destination.chmod(0o555)
    sync_directory(destination)
    sync_directory(destination.parent)


def create_runtime(plan, name, env_path, reference, expected_values):
    docker(
        "create",
        "--name",
        name,
        "--restart",
        "unless-stopped",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        "128",
        "--memory",
        "3g",
        "--cpus",
        "2",
        "--log-opt",
        "max-size=5m",
        "--log-opt",
        "max-file=2",
        "--env-file",
        str(env_path),
        "--mount",
        f"type=bind,src={plan.store},dst=/var/lib/nla-catalog,readonly",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=64m",  # noqa: S108 -- isolated container tmpfs, not host /tmp
        "-p",
        "127.0.0.1:10000:10000",
        plan.image,
    )
    new = inspect(name)
    assert new["Image"] == plan.image
    for key in ("User", "Entrypoint", "Cmd", "WorkingDir", "ExposedPorts"):
        assert new["Config"][key] == reference["Config"][key]
    for key in (
        "ReadonlyRootfs",
        "CapDrop",
        "CapAdd",
        "SecurityOpt",
        "Memory",
        "NanoCpus",
        "PidsLimit",
        "Tmpfs",
        "PortBindings",
        "Mounts",
        "LogConfig",
        "NetworkMode",
        "RestartPolicy",
    ):
        assert new["HostConfig"][key] == reference["HostConfig"][key]
    old_env = dict(item.split("=", 1) for item in reference["Config"]["Env"])
    new_env = dict(item.split("=", 1) for item in new["Config"]["Env"])
    assert set(old_env) == set(new_env)
    assert {k for k in old_env if old_env[k] != new_env[k]} <= ENV_KEYS
    assert all(new_env[k] == v for k, v in expected_values.items())
    return new["Id"]


def select(plan, action, expected, target=None):
    name = plan.prefix + "-" + action
    args = [
        "/usr/bin/docker",
        "run",
        "--name",
        name,
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--memory=2g",
        "--cpus=1",
        "--pids-limit=64",
        "--user=10001:10001",
        "--mount",
        f"type=bind,src={plan.store},dst=/var/lib/nla-catalog",
        "-e",
        "NLA_STAGING_STORE_ROOT=/var/lib/nla-catalog",
        "-e",
        "NLA_STAGING_ACTIVATION_ACTION=" + action,
        "-e",
        "NLA_STAGING_ACTIVATION_SHA256=" + expected,
    ]
    if target is not None:
        args.extend(["-e", "NLA_STAGING_CANDIDATE_MANIFEST_SHA256=" + target])
    args.extend([plan.image, "python", "/app/scripts/manage_staging_activation.py"])
    result = subprocess.run(args, capture_output=True, text=True)  # noqa: S603 -- fixed command and validated plan, no shell
    if result.returncode != 0 or result.stdout.strip() != "VALUE_FREE_RESULT: ACCEPTED":
        raise InspectBeforeRetry("selection_outcome_requires_inspection")


def ready(plan, expected_id, expected_pin):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    started = time.monotonic()
    while time.monotonic() - started < 1200:
        state = inspect(plan.current)
        assert state["Id"] == expected_id and state["State"]["Running"]
        assert pointer(plan)[1] == expected_pin
        try:
            with opener.open("http://127.0.0.1:10000/readyz", timeout=3) as response:
                if response.status == 200:
                    return
        except OSError:
            pass
        time.sleep(5)
    raise RuntimeError("readiness_timeout")


def apply(plan, checked):
    old, old_bytes, values, before, manifest, source, destination = checked
    plan.work.mkdir(mode=0o700)
    private_write(plan.work / "before-runtime.env", old_bytes)
    note(plan, "PREFLIGHT_ACCEPTED")
    install(source, destination)
    new_pin = pointer_pin(manifest, before["currentManifestSha256"])
    updated = {**values, "NLA_ACTIVATION_SHA256": new_pin, "NLA_EVIDENCE_CODE_SHA": plan.new_code}
    new_env = plan.work / "candidate-runtime.env"
    private_write(new_env, env_bytes(updated))
    new_id = create_runtime(plan, plan.candidate, new_env, old, updated)
    assert inspect(plan.current)["Id"] == plan.expected_id and pointer(plan)[1] == plan.old_pin
    assert private_read(plan.config / "accepted-runtime.env") == old_bytes
    select(plan, "promote", plan.old_pin, manifest)
    if pointer(plan)[1] != new_pin:
        raise InspectBeforeRetry("promotion_pin_requires_inspection")
    committed = False
    try:
        note(plan, "DATASET_POINTER_PROMOTED")
        docker("stop", "-t", "30", plan.current)
        docker("rename", plan.current, plan.backup)
        docker("update", "--restart", "no", plan.backup)
        docker("rename", plan.candidate, plan.current)
        docker("start", plan.current)
        note(plan, "REPLACEMENT_STARTED")
        ready(plan, new_id, new_pin)
        assert private_read(plan.config / "accepted-runtime.env") == old_bytes
        os.replace(new_env, plan.config / "accepted-runtime.env")
        committed = True
        sync_directory(plan.config)
        note(plan, "ACTIVATED_READY_OLD_PACKAGE_AND_CONTAINER_RETAINED")
    except Exception:
        if committed:
            raise InspectBeforeRetry("committed_state_requires_inspection") from None
        if pointer(plan)[1] != new_pin:
            raise InspectBeforeRetry("external_pointer_change_no_automatic_rollback") from None
        names = docker("ps", "-a", "--format", "{{.Names}}").splitlines()
        if plan.current in names:
            current = inspect(plan.current)
            if current["Id"] == plan.expected_id:
                docker("stop", "-t", "30", plan.current)
                docker("rename", plan.current, plan.backup)
                docker("update", "--restart", "no", plan.backup)
            elif current["Id"] == new_id:
                docker("stop", "-t", "30", plan.current)
                docker("rename", plan.current, plan.failed)
                docker("update", "--restart", "no", plan.failed)
            else:
                raise InspectBeforeRetry("unexpected_runtime_no_automatic_rollback") from None
        assert inspect(plan.backup)["Id"] == plan.expected_id
        docker("update", "--restart", "no", plan.backup)
        select(plan, "rollback", new_pin)
        rollback_pin = pointer_pin(before["currentManifestSha256"], manifest)
        if pointer(plan)[1] != rollback_pin:
            raise InspectBeforeRetry("rollback_pin_requires_inspection") from None
        restored_values = {**values, "NLA_ACTIVATION_SHA256": rollback_pin}
        restored_env = plan.work / "rollback-runtime.env"
        private_write(restored_env, env_bytes(restored_values))
        restored_id = create_runtime(plan, plan.restored, restored_env, old, restored_values)
        docker("rename", plan.restored, plan.current)
        docker("start", plan.current)
        ready(plan, restored_id, rollback_pin)
        assert private_read(plan.config / "accepted-runtime.env") == old_bytes
        os.replace(restored_env, plan.config / "accepted-runtime.env")
        sync_directory(plan.config)
        note(plan, "ROLLBACK_READY_ACTUAL_POINTER_REPINNED")
        raise RuntimeError("candidate_not_accepted_rollback_completed") from None


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError("invalid activation arguments")


def main(argv=None):
    parser = _Parser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    try:
        args = parser.parse_args(argv)
        plan = load_plan(json.loads(private_read(args.plan)))
        checked = preflight(plan)
        if args.apply:
            apply(plan, checked)
        else:
            print("READ_ONLY_PREFLIGHT_ACCEPTED_NO_CHANGES")
        return 0
    except (Exception, KeyboardInterrupt):
        print(
            "OPERATOR_STOPPED_INSPECT_PRIVATE_RECEIPTS_AND_NAMED_CONTAINERS_BEFORE_RETRY",
            flush=True,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
