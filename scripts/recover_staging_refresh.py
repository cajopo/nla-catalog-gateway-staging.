"""Recover only the inspected, promoted-but-never-started staging refresh window.

An independently reviewed private plan pins original evidence, exact containers,
installed recovery operators and the existing pointer. Default is read-only.
No capture, import, install, promotion, retention or automatic retry is performed.
An interruption after handoff starts requires fresh inspection, not this recovery.
"""

import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path

from scripts import activate_staging_refresh as activation
from scripts import refresh_staging_catalog as refresh

ARTIFACTS = {
    "operatorReceipt": "capture/operator-receipt.json",
    "checkpoint": "capture/capture-checkpoint.v1.json",
    "verification": "capture/runtime-verification-receipt.json",
    "beforeEnv": "activation/before-runtime.env",
    "candidateEnv": "activation/candidate-runtime.env",
    "stage": "activation/PREFLIGHT_ACCEPTED.json",
}
OPERATORS = {
    "recovery": Path(__file__),
    "activation": Path(activation.__file__),
    "refresh": Path(refresh.__file__),
}
FIELDS = {
    "activation",
    "refreshConfig",
    "previousManifestSha256",
    "previousPreviousManifestSha256",
    "promotedActivationSha256",
    "containers",
    "artifacts",
    "operators",
}
ROLES = {"old", "candidate", "verifier", "promote"}


def pin(value):
    assert type(value) is str and re.fullmatch("[0-9a-f]{64}", value)
    return value


def load_plan(value):
    assert type(value) is dict and set(value) == FIELDS
    plan = activation.load_plan(value["activation"])
    assert re.fullmatch(refresh.RUN_NAME, plan.run_id)
    raw = value["refreshConfig"]
    assert type(raw) is str and raw.startswith("/")
    config = Path(raw)
    assert str(config) == raw and config.resolve() == config
    assert not any(c in raw for c in ",\x00\r\n")
    pin(value["previousManifestSha256"])
    if value["previousPreviousManifestSha256"] is not None:
        pin(value["previousPreviousManifestSha256"])
    pin(value["promotedActivationSha256"])
    assert set(value["containers"]) == ROLES
    for facts in value["containers"].values():
        assert set(facts) == {"id", "contractSha256"}
        pin(facts["id"])
        pin(facts["contractSha256"])
    assert len({facts["id"] for facts in value["containers"].values()}) == 4
    assert value["containers"]["old"]["id"] == plan.expected_id
    for key, expected in (
        ("artifacts", set(ARTIFACTS) | {"refreshConfig", "pending"}),
        ("operators", set(OPERATORS)),
    ):
        assert set(value[key]) == expected
        for digest in value[key].values():
            pin(digest)
    return plan, config, value


def container_contract(container):
    """Fingerprint only private inspect contracts, never print environment values."""
    raw = json.dumps(
        {key: container[key] for key in ("Config", "HostConfig", "Mounts")},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(raw).hexdigest()


def directory(path, uid, mode):
    facts = path.lstat()
    assert path.resolve() == path and stat.S_ISDIR(facts.st_mode)
    assert facts.st_uid == uid and stat.S_IMODE(facts.st_mode) == mode


def pinned_private(path, expected):
    raw = activation.private_read(path)
    assert hashlib.sha256(raw).hexdigest() == expected
    return raw


def preflight(plan, config_path, expected):
    if not __debug__ or sys.platform != "linux" or os.geteuid() != 0:
        raise activation.InspectBeforeRetry("recovery_requires_root_linux_assertions")
    run = plan.work.parent
    root = run.parent
    assert run.name == plan.run_id and plan.capture == run / "capture"
    assert plan.work == run / "activation"
    for path in (root, run, plan.work, plan.capture, plan.config):
        directory(path, 0, 0o700)
    for path in (plan.store, plan.store / "generations"):
        directory(path, 10001, 0o700)
    assert {p.name for p in plan.work.iterdir()} == {
        "before-runtime.env",
        "candidate-runtime.env",
        "PREFLIGHT_ACCEPTED.json",
    }
    assert not os.path.lexists(run / "completed.json")
    assert not os.path.lexists(run / "retention-plan.json")
    for role, path in OPERATORS.items():
        assert activation.digest(path) == expected["operators"][role]
    artifacts = expected["artifacts"]
    raw = {
        key: pinned_private(run / relative, artifacts[key]) for key, relative in ARTIFACTS.items()
    }
    config = json.loads(pinned_private(config_path, artifacts["refreshConfig"]))
    pending_bytes = pinned_private(root / "pending-run.json", artifacts["pending"])
    pending = json.loads(pending_bytes)
    assert set(pending) == {"run", "startedAt"} and pending["run"] == plan.run_id
    assert json.loads(raw["stage"]) == {"stage": "PREFLIGHT_ACCEPTED"}
    for key, value in {
        "run_root": str(root),
        "config": str(plan.config),
        "store": str(plan.store),
        "current": plan.current,
        "image": plan.image,
        "shop": plan.shop,
        "code_sha": plan.new_code,
    }.items():
        assert config[key] == value
    # The original source archive and its producer pin remain unchanged. Recovery
    # operators are attested separately; they do not become capture producers.
    assert activation.digest(Path(config["archive"])) == config["archive_sha256"]
    checkpoint = json.loads(raw["checkpoint"])
    for key, value in {
        "sourceCodeSha": config["code_sha"],
        "shopDomain": config["shop"],
        "onlineStorePublicationGid": config["publication"],
        "canonicalNameManifestSha256": config["reference_manifest_sha256"],
        "canonicalNameSidecarSha256": config["reference_data_sha256"],
    }.items():
        assert checkpoint["identity"][key] == value
    manifest, source = activation.capture_evidence(plan)
    directory(source, 0, 0o555)
    for name in activation.FILES:
        assert (source / name).lstat().st_uid == 0
    pointer_facts = (plan.store / "activation.v1.json").lstat()
    assert pointer_facts.st_uid == 10001 and stat.S_IMODE(pointer_facts.st_mode) == 0o600
    destination = plan.store / "generations" / manifest
    directory(destination, 10001, 0o555)
    assert {p.name for p in destination.iterdir()} == activation.FILES
    for name in activation.FILES:
        target = destination / name
        facts = target.lstat()
        assert stat.S_ISREG(facts.st_mode) and facts.st_nlink == 1
        assert facts.st_uid == 10001 and stat.S_IMODE(facts.st_mode) == 0o444
        assert activation.digest(target) == activation.digest(source / name)
    previous = expected["previousManifestSha256"]
    before = {
        "schemaVersion": 1,
        "currentManifestSha256": previous,
        "previousManifestSha256": expected["previousPreviousManifestSha256"],
    }
    assert activation.pointer_pin(previous, before["previousManifestSha256"]) == plan.old_pin
    new_pin = activation.pointer_pin(manifest, previous)
    assert new_pin == expected["promotedActivationSha256"]
    current_pointer, current_pin = activation.pointer(plan)
    assert current_pointer == {
        "schemaVersion": 1,
        "currentManifestSha256": manifest,
        "previousManifestSha256": previous,
    }
    assert current_pin == new_pin
    old_bytes = raw["beforeEnv"]
    assert activation.private_read(plan.config / "accepted-runtime.env") == old_bytes
    values = dict(line.split("=", 1) for line in old_bytes.decode().splitlines())
    assert values["NLA_ACTIVATION_SHA256"] == plan.old_pin
    assert values["NLA_EVIDENCE_CODE_SHA"] == plan.old_code
    updated = {**values, "NLA_ACTIVATION_SHA256": new_pin, "NLA_EVIDENCE_CODE_SHA": plan.new_code}
    assert raw["candidateEnv"] == activation.env_bytes(updated)
    names = activation.docker("ps", "-a", "--format", "{{.Names}}").splitlines()
    for name in (plan.backup, plan.failed, plan.restored, plan.prefix + "-rollback"):
        assert name not in names
    containers = {}
    for role, name in {
        "old": plan.current,
        "candidate": plan.candidate,
        "verifier": plan.verifier,
        "promote": plan.prefix + "-promote",
    }.items():
        container = activation.inspect(name)
        assert container["Id"] == expected["containers"][role]["id"]
        assert container_contract(container) == expected["containers"][role]["contractSha256"]
        assert container["Image"] == (plan.old_image if role == "old" else plan.image)
        assert not container["State"]["OOMKilled"]
        containers[role] = container
    old, candidate = containers["old"], containers["candidate"]
    assert old["State"]["Running"] and old["State"]["Status"] == "running"
    live = dict(line.split("=", 1) for line in old["Config"]["Env"])
    assert all(live.get(key) == value for key, value in values.items())
    assert values["NLA_STAGING_STORE_ROOT"] == "/var/lib/nla-catalog"
    assert values["NLA_SHOP_DOMAIN"] == plan.shop
    assert values["NLA_APP_PROXY_SIGNED_PATH_PREFIX"] == "/apps/nla-catalog"
    assert values["NLA_APP_PROXY_BACKEND_PATH"] == "/proxy/catalog"
    assert candidate["State"]["Status"] == "created" and not candidate["State"]["Running"]
    assert candidate["State"]["StartedAt"] == "0001-01-01T00:00:00Z"
    assert candidate["State"]["ExitCode"] == 0
    new_port = next(
        port for port in activation.RUNTIME_PORTS if port != activation.runtime_port(old)
    )
    activation.runtime_matches(plan, candidate, old, updated, new_port)
    for role in ("verifier", "promote"):
        state = containers[role]["State"]
        assert state["Status"] == "exited" and not state["Running"] and state["ExitCode"] == 0
    selector_env = dict(line.split("=", 1) for line in containers["promote"]["Config"]["Env"])
    for key, value in {
        "NLA_STAGING_STORE_ROOT": "/var/lib/nla-catalog",
        "NLA_STAGING_ACTIVATION_ACTION": "promote",
        "NLA_STAGING_ACTIVATION_SHA256": plan.old_pin,
        "NLA_STAGING_CANDIDATE_MANIFEST_SHA256": manifest,
    }.items():
        assert selector_env[key] == value
    assert activation.docker("logs", containers["promote"]["Id"]) == "VALUE_FREE_RESULT: ACCEPTED"
    activation.serving(plan.current, plan.expected_id, activation.runtime_port(old))
    return (old, old_bytes, values, before, manifest, source, destination), pending_bytes


def recover(plan, config_path, expected, apply=False):
    root = plan.work.parent.parent
    # Default preflight uses an already existing lock, never creates a resource.
    directory(root, 0, 0o700)
    activation.private_read(root / ".pipeline.lock")
    with refresh.pipeline_lock(root):
        checked, pending_bytes = preflight(plan, config_path, expected)
        if not apply:
            print("RECOVERY_READ_ONLY_PREFLIGHT_ACCEPTED_NO_CHANGES")
            return
        activation.finish_promoted(
            plan,
            checked,
            expected["containers"]["candidate"]["id"],
            expected["promotedActivationSha256"],
            rollback=False,
        )
        completed = {
            "run": plan.run_id,
            "status": "ready",
            "sourceStartedAt": plan.started,
            "activatedAt": refresh.timestamp(),
            "manifestSha256": plan.manifest,
            "activationSha256": expected["promotedActivationSha256"],
            "previousManifestSha256": expected["previousManifestSha256"],
            "resources": {
                "runtime": expected["containers"]["candidate"]["id"],
                "before": plan.expected_id,
                "verifier": expected["containers"]["verifier"]["id"],
                "promote": expected["containers"]["promote"]["id"],
            },
            "recovery": "promoted-never-started",
            "retentionDeferred": True,
        }
        assert activation.pointer(plan)[1] == completed["activationSha256"]
        activation.serving(
            plan.current,
            completed["resources"]["runtime"],
            activation.runtime_port(activation.inspect(plan.current)),
        )
        refresh.publish(plan.work.parent / "completed.json", completed)
        refresh.publish(root / "last-success.json", completed, replace=True)
        assert activation.private_read(root / "pending-run.json") == pending_bytes
        (root / "pending-run.json").unlink()
        activation.sync_directory(root)
        print("RECOVERY_READY_TERMINAL_RECEIPTS_DURABLE_RETENTION_DEFERRED")


def main(argv=None):
    parser = activation._Parser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    try:
        args = parser.parse_args(argv)
        plan, config, expected = load_plan(json.loads(activation.private_read(args.plan)))
        recover(plan, config, expected, args.apply)
        return 0
    except (Exception, KeyboardInterrupt):
        print("RECOVERY_STOPPED_INSPECT_PENDING_RUN_AND_NAMED_CONTAINERS_NO_AUTOMATIC_RETRY")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
