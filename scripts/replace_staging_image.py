"""Idle-only code replacement; no dataset promotion or config/unit installation.

Default: read-only preflight. Apply retains pending-run.json even on success:
an operator must install coherent refresh/market pins before closing this gate.
Interrupted attempts are never resumed automatically. No resource deletion.
"""

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

from scripts import activate_staging_refresh as a
from scripts import refresh_staging_catalog as r

UNITS = (
    "nla-catalog-refresh.service",
    "nla-market-catalog.service",
    "nla-catalog-refresh.timer",
    "nla-market-catalog.timer",
)
MARKET_PENDING = Path("/opt/nla-staging/importer-state/pending-market-run.json")
FIELDS = {
    "config",
    "run_id",
    "expected_id",
    "old_image",
    "new_image",
    "activation_sha256",
    "manifest_sha256",
    "accepted_env_sha256",
    "last_success_sha256",
}


def load_plan(value):
    if type(value) is not dict or set(value) != FIELDS:
        raise ValueError("invalid image replacement fields")
    for key in FIELDS - {"config", "run_id", "old_image", "new_image"}:
        if type(value[key]) is not str or re.fullmatch("[0-9a-f]{64}", value[key]) is None:
            raise ValueError("invalid image replacement pin")
    for key in ("old_image", "new_image"):
        if type(value[key]) is not str or re.fullmatch("sha256:[0-9a-f]{64}", value[key]) is None:
            raise ValueError("invalid image digest")
    if value["old_image"] == value["new_image"]:
        raise ValueError("image replacement requires distinct images")
    if type(value["run_id"]) is not str or re.fullmatch(r.RUN_NAME, value["run_id"]) is None:
        raise ValueError("invalid image replacement run")
    raw = value["config"]
    if (
        type(raw) is not str
        or not raw.startswith("/")
        or Path(raw).as_posix() != raw
        or ".." in Path(raw).parts
        or any(c in raw for c in "\x00\r\n")
    ):
        raise ValueError("invalid candidate configuration path")
    return SimpleNamespace(**value)


def idle():
    """Read systemd properties, never stop an active job or manipulate timers."""
    for unit in UNITS:
        result = subprocess.run(  # noqa: S603 -- fixed executable and unit allowlist
            [
                "/usr/bin/systemctl",
                "show",
                unit,
                "--all",
                "--property=LoadState,ActiveState,SubState,MainPID,Job",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        state = dict(line.split("=", 1) for line in result.stdout.splitlines())
        if (
            state.get("LoadState") != "loaded"
            or state.get("ActiveState") not in {"inactive", "failed"}
            or state.get("SubState") not in {"dead", "failed"}
            or (unit.endswith(".service") and state.get("MainPID") != "0")
            or state.get("Job") not in {"", "0"}
        ):
            raise ValueError("both refresh jobs must be idle and timers stopped")
    if os.path.lexists(MARKET_PENDING):
        raise ValueError("market cycle requires inspection")


def unchanged(plan, config, raw):
    pointer, pin = a.pointer(SimpleNamespace(store=config["store"]))
    if (
        pin != plan.activation_sha256
        or pointer["currentManifestSha256"] != plan.manifest_sha256
        or a.private_read(config["config"] / "accepted-runtime.env") != raw
        or a.digest(config["run_root"] / "last-success.json") != plan.last_success_sha256
    ):
        raise a.InspectBeforeRetry("dataset_or_accepted_environment_changed")
    return pointer


def preflight(plan, config):
    idle()
    if config["image"] != plan.new_image:
        raise ValueError("candidate configuration image differs")
    if json.loads(a.docker("image", "inspect", plan.new_image))[0]["Id"] != plan.new_image:
        raise ValueError("candidate image is not installed under its pinned identity")
    run = config["run_root"] / plan.run_id
    if os.path.lexists(run) or os.path.lexists(config["run_root"] / "pending-run.json"):
        raise a.InspectBeforeRetry("existing_attempt_requires_inspection")
    previous_raw = a.private_read(config["run_root"] / "last-success.json")
    if hashlib.sha256(previous_raw).hexdigest() != plan.last_success_sha256:
        raise ValueError("last success changed")
    previous = json.loads(previous_raw)
    if type(previous.get("run")) is not str or re.fullmatch(r.RUN_NAME, previous["run"]) is None:
        raise ValueError("invalid previous run")
    if previous != r.document(config["run_root"] / previous["run"] / "completed.json"):
        raise ValueError("last success missing immutable completion")
    if previous["status"] != "ready" or previous["resources"]["runtime"] != plan.expected_id:
        raise ValueError("last success runtime differs")
    raw = a.private_read(config["config"] / "accepted-runtime.env")
    if hashlib.sha256(raw).hexdigest() != plan.accepted_env_sha256:
        raise ValueError("accepted environment changed")
    values = dict(line.split("=", 1) for line in raw.decode().splitlines())
    pointer = unchanged(plan, config, raw)
    if (
        previous["manifestSha256"] != plan.manifest_sha256
        or previous["activationSha256"] != plan.activation_sha256
        or previous["previousManifestSha256"] != pointer["previousManifestSha256"]
        or values["NLA_ACTIVATION_SHA256"] != plan.activation_sha256
        or values["NLA_SHOP_DOMAIN"] != config["shop"]
        or values["NLA_STAGING_STORE_ROOT"] != "/var/lib/nla-catalog"
    ):
        raise ValueError("dataset provenance differs")
    r.freshness(config)  # Validate source time and live binding, never reset source age.
    old = a.inspect(config["current"])
    live = dict(item.split("=", 1) for item in old["Config"]["Env"])
    if (
        old["Id"] != plan.expected_id
        or old["Image"] != plan.old_image
        or not old["State"]["Running"]
        or any(live.get(k) != v for k, v in values.items())
        or old["HostConfig"]["RestartPolicy"] != {"Name": "unless-stopped", "MaximumRetryCount": 0}
        or [m for m in old["Mounts"] if m["Type"] == "bind"]
        != [
            m
            for m in old["Mounts"]
            if m["Type"] == "bind"
            and m["Source"] == str(config["store"])
            and m["Destination"] == "/var/lib/nla-catalog"
            and m["RW"] is False
        ]
        or not any(m["Type"] == "bind" for m in old["Mounts"])
    ):
        raise ValueError("previous runtime differs")
    runtime = SimpleNamespace(
        store=config["store"],
        image=plan.new_image,
        expected_id=plan.expected_id,
        old_port=a.runtime_port(old),
        current=config["current"],
        candidate="nla-image-" + plan.run_id + "-candidate",
        backup="nla-image-" + plan.run_id + "-before",
        failed="nla-image-" + plan.run_id + "-failed",
    )
    runtime.new_port = next(port for port in a.RUNTIME_PORTS if port != runtime.old_port)
    names = a.docker("ps", "-a", "--format", "{{.Names}}").splitlines()
    if any(name in names for name in (runtime.candidate, runtime.backup, runtime.failed)):
        raise a.InspectBeforeRetry("named_resources_exist")
    return run, previous, raw, values, old, runtime


def rollback(plan, config, raw, runtime, new_id):
    unchanged(plan, config, raw)
    names = a.docker("ps", "-a", "--format", "{{.Names}}").splitlines()
    old_name = runtime.backup if runtime.backup in names else runtime.current
    old = a.inspect(old_name)
    if old["Id"] != plan.expected_id or old["Image"] != plan.old_image:
        raise a.InspectBeforeRetry("unexpected_backup_no_rollback")
    a.serving(old_name, plan.expected_id, runtime.old_port)
    if runtime.candidate in names:
        candidate = a.inspect(runtime.candidate)
        if candidate["Id"] != new_id or candidate["Image"] != plan.new_image:
            raise a.InspectBeforeRetry("unexpected_candidate_no_rollback")
        a.docker("stop", "-t", "30", runtime.candidate)
        a.docker("rename", runtime.candidate, runtime.failed)
        a.docker("update", "--restart", "no", runtime.failed)
    if runtime.current in names:
        current = a.inspect(runtime.current)
        if current["Id"] == new_id:
            a.docker("stop", "-t", "30", runtime.current)
            a.docker("rename", runtime.current, runtime.failed)
            a.docker("update", "--restart", "no", runtime.failed)
        elif current["Id"] != plan.expected_id:
            raise a.InspectBeforeRetry("unexpected_runtime_no_rollback")
    if runtime.backup in names:
        old = a.inspect(runtime.backup)
        if old["Id"] != plan.expected_id or old["Image"] != plan.old_image:
            raise a.InspectBeforeRetry("unexpected_backup_no_rollback")
        a.docker("rename", runtime.backup, runtime.current)
    old = a.inspect(runtime.current)
    if old["Id"] != plan.expected_id or old["Image"] != plan.old_image:
        raise a.InspectBeforeRetry("unexpected_restored_runtime")
    a.docker("update", "--restart", "unless-stopped", runtime.current)
    a.docker("start", runtime.current)
    a.ready(runtime, runtime.current, plan.expected_id, plan.activation_sha256, runtime.old_port)
    unchanged(plan, config, raw)


def apply(plan, config, checked):
    run, previous, raw, values, old, runtime = checked
    idle()
    unchanged(plan, config, raw)
    run.mkdir(mode=0o700)
    a.sync_directory(run.parent)
    r.publish(run / "plan.json", vars(plan))
    a.private_write(run / "before-runtime.env", raw)
    r.publish(run / "before-success.json", previous)
    r.publish(
        config["run_root"] / "pending-run.json", {"run": plan.run_id, "kind": "image-upgrade"}
    )
    new_id = a.create_runtime(
        runtime, runtime.candidate, run / "before-runtime.env", old, values, runtime.new_port
    )
    committed = False
    try:
        unchanged(plan, config, raw)
        if a.inspect(runtime.current)["Id"] != plan.expected_id:
            raise a.InspectBeforeRetry("runtime_changed")
        a.docker("start", runtime.candidate)
        a.ready(runtime, runtime.candidate, new_id, plan.activation_sha256, runtime.new_port)
        unchanged(plan, config, raw)
        a.serving(runtime.current, plan.expected_id, runtime.old_port)
        a.docker("rename", runtime.current, runtime.backup)
        a.docker("update", "--restart", "no", runtime.backup)
        a.docker("rename", runtime.candidate, runtime.current)
        a.serving(runtime.current, new_id, runtime.new_port)
        unchanged(plan, config, raw)
        receipt = {
            "kind": "image-upgrade",
            "run": plan.run_id,
            "status": "ready",
            "sourceStartedAt": previous["sourceStartedAt"],
            "activatedAt": r.timestamp(),
            "manifestSha256": plan.manifest_sha256,
            "activationSha256": plan.activation_sha256,
            "previousManifestSha256": previous["previousManifestSha256"],
            "resources": {"runtime": new_id, "replaced": plan.expected_id},
            "oldImage": plan.old_image,
            "newImage": plan.new_image,
            "installationComplete": False,
        }
        # Once publication starts its outcome may be ambiguous: never undo a
        # runtime referenced by a possibly durable success receipt automatically.
        committed = True
        r.publish(run / "completed.json", receipt)
        r.publish(config["run_root"] / "last-success.json", receipt, replace=True)
        a.retire(runtime)
        return receipt
    except Exception:
        if committed:
            raise a.InspectBeforeRetry("receipt_publication_requires_inspection") from None
        rollback(plan, config, raw, runtime, new_id)
        r.publish(
            run / "rollback.json",
            {"runtime": plan.expected_id, "candidate": new_id, "status": "restored"},
        )
        raise a.InspectBeforeRetry("old_runtime_restored_inspect_before_retry") from None


def main(argv=None):
    parser = r._Parser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    try:
        args = parser.parse_args(argv)
        plan = load_plan(r.document(args.plan))
        config = r.configuration(Path(plan.config))
        idle()  # Do not acquire a pipeline lock while a market/refresh job is live.
        with r.pipeline_lock(config["run_root"]):
            checked = preflight(plan, config)
            if args.apply:
                apply(plan, config, checked)
                print("IMAGE_READY_INSTALLATION_PENDING_TIMERS_MUST_REMAIN_STOPPED")
            else:
                print("READ_ONLY_PREFLIGHT_ACCEPTED_NO_CHANGES")
        return 0
    except (Exception, KeyboardInterrupt):
        print("STOPPED_INSPECT_RETAINED_EVIDENCE_NO_AUTOMATIC_RETRY")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
