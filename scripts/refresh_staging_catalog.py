"""One staging refresh under a whole-pipeline lock; default is read-only.

No Shopify writes, automatic retry, source discovery or image upgrade. An
interrupted run leaves pending-run.json and requires inspection before another
run. Deploy under one bounded systemd oneshot, never as an unbounded shell job.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from scripts import activate_staging_refresh as activation

ROOT = Path(__file__).resolve().parents[1]
PATHS = {"run_root", "config", "store", "reference", "archive"}
PINS = {"archive_sha256", "reference_manifest_sha256", "reference_data_sha256"}
FIELDS = PATHS | PINS | {"code_sha", "image", "shop", "publication", "current"}
MIN_FREE_BYTES = 6 * 1024**3
RUN_NAME = r"[0-9]{8}t[0-9]{6}z-[0-9a-f]{8}"


def timestamp():
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def document(path):
    return json.loads(activation.private_read(path))


def publish(path, value, *, replace=False):
    """Private, durable publication; terminal receipts must never be overwritten."""
    temporary = path.parent / (".receipt-" + uuid.uuid4().hex)
    activation.private_write(temporary, json.dumps(value, sort_keys=True).encode())
    if replace:
        os.replace(temporary, path)
    else:
        os.link(temporary, path)
        temporary.unlink()
    activation.sync_directory(path.parent)


def configuration(path):
    if not __debug__ or sys.platform != "linux" or os.geteuid() != 0:
        raise ValueError("requires non-optimized root Linux process")
    value = document(path)
    if type(value) is not dict or set(value) != FIELDS:
        raise ValueError("invalid refresh configuration")
    for key in PATHS:
        raw = value[key]
        if type(raw) is not str or not raw.startswith("/") or any(c in raw for c in ",\x00\r\n"):
            raise ValueError("invalid refresh path")
        value[key] = Path(raw)
        if str(value[key]) != raw or value[key].resolve() != value[key]:
            raise ValueError("noncanonical refresh path")
    for key in PINS | {"code_sha"}:
        length = 40 if key == "code_sha" else 64
        if type(value[key]) is not str or re.fullmatch(f"[0-9a-f]{{{length}}}", value[key]) is None:
            raise ValueError("invalid refresh pin")
    for key, pattern in {
        "image": r"sha256:[0-9a-f]{64}",
        "shop": r"[a-z0-9][a-z0-9-]*\.myshopify\.com",
        "publication": r"gid://shopify/Publication/[1-9][0-9]*",
        "current": r"[a-z0-9][a-z0-9-]{0,60}",
    }.items():
        if type(value[key]) is not str or re.fullmatch(pattern, value[key]) is None:
            raise ValueError("invalid refresh identity")
    for directory in (value["run_root"], value["config"]):
        facts = directory.stat()
        if (
            not stat.S_ISDIR(facts.st_mode)
            or facts.st_uid != 0
            or stat.S_IMODE(facts.st_mode) != 0o700
        ):
            raise ValueError("refresh directory must be private")
    if activation.digest(value["archive"]) != value["archive_sha256"]:
        raise ValueError("source archive changed")
    required = {
        path.relative_to(ROOT).as_posix()
        for folder in ("scripts", "src", "graphql")
        for path in (ROOT / folder).rglob("*")
        if path.suffix in (".py", ".json", ".graphql")
    }
    required |= {
        "scripts/refresh_staging_catalog.py",
        "scripts/capture_shopify_bulk.py",
        "scripts/activate_staging_refresh.py",
        "scripts/verify_staging_runtime.py",
    }
    present = set()
    with tarfile.open(value["archive"]) as archive:
        if archive.pax_headers.get("comment") != value["code_sha"]:
            raise ValueError("source archive commit differs")
        for entry in archive:
            target = ROOT / entry.name
            if (
                entry.name.startswith("/")
                or ".." in Path(entry.name).parts
                or target.resolve() != target
            ):
                raise ValueError("unsafe source archive path")
            if entry.isdir():
                continue
            if not entry.isfile():
                raise ValueError("nonregular source archive entry")
            if entry.name in present:
                raise ValueError("duplicate source archive entry")
            present.add(entry.name)
            with archive.extractfile(entry) as source:
                if hashlib.file_digest(source, "sha256").hexdigest() != activation.digest(target):
                    raise ValueError("installed source changed")
    if not required <= present:
        raise ValueError("incomplete source archive")
    for name, pin in (
        ("canonical-names-manifest.v1.json", "reference_manifest_sha256"),
        ("canonical-names.v1.jsonl", "reference_data_sha256"),
    ):
        if activation.digest(value["reference"] / name) != value[pin]:
            raise ValueError("canonical reference changed")
    return value


@contextmanager
def pipeline_lock(directory):
    import fcntl

    descriptor = os.open(
        directory / ".pipeline.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600
    )
    try:
        facts = os.fstat(descriptor)
        if (
            not stat.S_ISREG(facts.st_mode)
            or facts.st_uid != 0
            or facts.st_nlink != 1
            or stat.S_IMODE(facts.st_mode) != 0o600
        ):
            raise ValueError("invalid pipeline lock")
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(descriptor)


def capture(config, run):
    """Child process: credentials remain in memory; parent attests successful exit."""
    from nla_catalog_gateway.shopify_capture_http import ShopifyCaptureHttp
    from scripts.capture_shopify_bulk import API_VERSION, wait_for_capture

    if run.parent != config["run_root"] or run.resolve() != run or not run.is_dir():
        raise ValueError("capture run outside configured root")
    facts = run.stat()
    if facts.st_uid != 0 or stat.S_IMODE(facts.st_mode) != 0o700:
        raise ValueError("capture run must be private")
    if document(config["run_root"] / "pending-run.json")["run"] != run.name:
        raise ValueError("capture run differs from durable intent")
    credentials = document(config["config"] / "shopify-app-credentials.json")
    client = ShopifyCaptureHttp(
        config["shop"], API_VERSION, credentials["client_id"], credentials["client_secret"]
    )
    credentials.clear()
    directory = run / "capture"
    directory.mkdir(mode=0o700)
    result = wait_for_capture(
        client=client,
        wait_seconds=7200,
        poll_seconds=60,
        capture_directory=directory,
        shop_domain=config["shop"],
        online_store_publication_gid=config["publication"],
        code_sha=config["code_sha"],
        canonical_names_jsonl=config["reference"] / "canonical-names.v1.jsonl",
        canonical_names_manifest=config["reference"] / "canonical-names-manifest.v1.json",
        canonical_manifest_sha256=config["reference_manifest_sha256"],
    )
    if result["status"] != "candidate-ready":
        raise ValueError("capture incomplete; inspect retained checkpoint")
    return result


def capture_receipt(config, run, result):
    state = document(run / "capture" / "capture-checkpoint.v1.json")
    if (
        result["status"] != "candidate-ready"
        or result["manifestSha256"] != state["packageManifestSha256"]
    ):
        raise ValueError("capture result differs from checkpoint")
    expected_identity = {
        "sourceCodeSha": config["code_sha"],
        "shopDomain": config["shop"],
        "onlineStorePublicationGid": config["publication"],
        "canonicalNameManifestSha256": config["reference_manifest_sha256"],
        "canonicalNameSidecarSha256": config["reference_data_sha256"],
    }
    if any(state["identity"].get(key) != value for key, value in expected_identity.items()):
        raise ValueError("capture identity differs")
    receipt = {
        "status": "candidate-ready",
        "codeSha": config["code_sha"],
        "manifestSha256": result["manifestSha256"],
        "captureStartedAt": state["beforeObservedAt"],
        "counts": state["beforeCounts"],
        "activeCatalogChanged": False,
    }
    publish(run / "capture" / "operator-receipt.json", receipt)
    return state, receipt


def verify(plan):
    args = [
        "/usr/bin/docker",
        "run",
        "--name",
        plan.verifier,
        "--pull=never",
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--memory=2g",
        "--cpus=1",
        "--pids-limit=64",
        "--user=10001:10001",
        "--entrypoint=python",
        "--mount",
        f"type=bind,src={plan.capture / 'candidate'},dst=/candidate,readonly",
        "--mount",
        f"type=bind,src={ROOT / 'scripts/verify_staging_runtime.py'},dst=/verify.py,readonly",
        plan.image,
        "-E",
        "/verify.py",
        "--candidate-directory",
        "/candidate",
        "--manifest-sha256",
        plan.manifest,
        "--summary-sha256",
        plan.summary,
        "--code-sha",
        plan.new_code,
        "--record-count",
        str(plan.counts["products"]),
    ]
    result = subprocess.run(args, check=True, capture_output=True, text=True, timeout=1200)  # noqa: S603 -- fixed Docker invocation, validated arguments
    publish(plan.capture / "runtime-verification-receipt.json", json.loads(result.stdout))


def retention(config, run, completed):
    """Delete only recorded obsolete runs/resources; caller holds pipeline lock."""
    root, store = config["run_root"], config["store"]
    pointer_plan = argparse.Namespace(store=store)

    def unchanged():
        pointer, pin = activation.pointer(pointer_plan)
        if (
            pin != completed["activationSha256"]
            or pointer["currentManifestSha256"] != completed["manifestSha256"]
            or pointer["previousManifestSha256"] != completed["previousManifestSha256"]
            or activation.inspect(config["current"])["Id"] != completed["resources"]["runtime"]
        ):
            raise ValueError("runtime changed during retention")
        return pointer

    pointer = unchanged()
    protected = {pointer["currentManifestSha256"], pointer["previousManifestSha256"]}
    keep_ids = set(completed["resources"].values())
    receipts, owners = {}, {}
    for directory in sorted(root.iterdir()):
        if (
            re.fullmatch(RUN_NAME, directory.name) is None
            or not (directory / "completed.json").exists()
        ):
            continue
        if directory.resolve() != directory:
            raise ValueError("noncanonical completed run")
        receipt = document(directory / "completed.json")
        if receipt["run"] != directory.name or receipt["status"] != "ready":
            raise ValueError("invalid completed run")
        resources = receipt["resources"]
        kind = receipt.get("kind", "dataset-refresh")
        expected_roles = (
            {"runtime", "replaced"}
            if kind == "image-upgrade"
            else {"runtime", "before", "verifier", "promote"}
        )
        if kind not in {"dataset-refresh", "image-upgrade"} or set(resources) != expected_roles:
            raise ValueError("invalid completed resources")
        if kind == "image-upgrade" and (
            resources["runtime"] == resources["replaced"]
            or receipt.get("oldImage") == receipt.get("newImage")
            or any(
                not isinstance(receipt.get(key), str)
                or re.fullmatch("sha256:[0-9a-f]{64}", receipt[key]) is None
                for key in ("oldImage", "newImage")
            )
        ):
            raise ValueError("invalid image replacement receipt")
        for value in [
            receipt["manifestSha256"],
            receipt["previousManifestSha256"],
            *resources.values(),
        ]:
            if not isinstance(value, str) or re.fullmatch("[0-9a-f]{64}", value) is None:
                raise ValueError("invalid retention identity")
        receipts[directory] = receipt
        for role, resource in resources.items():
            manifest = (
                receipt["previousManifestSha256"] if role == "before" else receipt["manifestSha256"]
            )
            if resource in owners and owners[resource] != manifest:
                raise ValueError("conflicting container ownership")
            owners[resource] = manifest
    if receipts.get(run) != completed:
        raise ValueError("current completion missing")

    def references_managed_data(container):
        return any(
            mount["Type"] == "bind"
            and any(
                Path(mount["Source"]).is_relative_to(parent)
                or parent.is_relative_to(Path(mount["Source"]))
                for parent in (root, store)
            )
            for mount in container["Mounts"]
        )

    remove_ids = []
    for identifier in activation.docker("ps", "-a", "-q", "--no-trunc").splitlines():
        container = activation.inspect(identifier)
        if container["Id"] != identifier:
            raise ValueError("container inventory changed")
        if references_managed_data(container) and identifier not in owners:
            raise ValueError("unrecorded container references managed data")
        if identifier not in owners:
            continue
        if identifier in keep_ids:
            protected.add(owners[identifier])
            continue
        if (
            container["State"]["Status"] not in ("exited", "created")
            or container["State"]["Running"]
            or container["HostConfig"]["RestartPolicy"]["Name"] not in ("", "no")
        ):
            raise ValueError("obsolete container is not stopped without restart")
        remove_ids.append(identifier)

    def check_tree(path, parent, uid):
        # Re-read: even a same-filesystem bind mount can appear after planning.
        mounts = [
            Path(re.sub(r"\\([0-7]{3})", lambda match: chr(int(match[1], 8)), line.split()[4]))
            for line in Path("/proc/self/mountinfo").read_text().splitlines()
        ]
        facts = path.lstat()
        if (
            path.parent != parent
            or path.resolve() != path
            or not stat.S_ISDIR(facts.st_mode)
            or facts.st_uid != uid
            or any(mount.is_relative_to(path) for mount in mounts)
            or not shutil.rmtree.avoids_symlink_attacks
        ):
            raise ValueError("unsafe retention root")
        for entry in [path, *path.rglob("*")]:
            item = entry.lstat()
            if (
                entry.resolve() != entry
                or item.st_dev != facts.st_dev
                or item.st_uid not in (0, 10001)
                or not (stat.S_ISDIR(item.st_mode) or stat.S_ISREG(item.st_mode))
                or (stat.S_ISREG(item.st_mode) and item.st_nlink != 1)
            ):
                raise ValueError("unsafe retention entry")
        return facts.st_dev, facts.st_ino

    targets = {}
    for directory, receipt in receipts.items():
        manifest = receipt["manifestSha256"]
        if manifest in protected:
            continue
        generation = store / "generations" / manifest
        if os.path.lexists(generation):
            if activation.digest(generation / "staging-generation-manifest.v1.json") != manifest:
                raise ValueError("obsolete generation does not match receipt")
            targets[generation] = (generation.parent, 10001)
        targets[directory] = (root, 0)
    checked = {path: check_tree(path, *args) for path, args in targets.items()}
    publish(
        run / "retention-plan.json",
        {"containers": remove_ids, "directories": [str(p) for p in targets]},
    )
    for identifier in remove_ids:
        unchanged()
        container = activation.inspect(identifier)
        if container["State"]["Running"] or container["HostConfig"]["RestartPolicy"][
            "Name"
        ] not in ("", "no"):
            raise ValueError("container changed before removal")
        activation.docker("rm", identifier)  # No force, no volumes, exact recorded ID.
    for path, args in targets.items():
        unchanged()
        for identifier in activation.docker("ps", "-a", "-q", "--no-trunc").splitlines():
            container = activation.inspect(identifier)
            if references_managed_data(container) and owners.get(identifier) not in protected:
                raise ValueError("container references changed before tree removal")
        if check_tree(path, *args) != checked[path]:
            raise ValueError("retention directory changed")
        shutil.rmtree(path)
        activation.sync_directory(path.parent)


def run_once(config_path, config):
    root = config["run_root"]
    with pipeline_lock(root):
        pending = root / "pending-run.json"
        if os.path.lexists(pending):
            raise ValueError("prior run requires inspection")
        if shutil.disk_usage(root).free < MIN_FREE_BYTES:
            raise ValueError("insufficient disk reserve")
        current = activation.inspect(config["current"])
        values = dict(
            line.split("=", 1)
            for line in activation.private_read(config["config"] / "accepted-runtime.env")
            .decode()
            .splitlines()
        )
        if current["Image"] != config["image"] or not current["State"]["Running"]:
            raise ValueError("unexpected current runtime")
        run_id = datetime.now(UTC).strftime("%Y%m%dt%H%M%Sz") + "-" + uuid.uuid4().hex[:8]
        run = root / run_id
        # Durable intent precedes both the run directory and the remote export.
        publish(pending, {"run": run_id, "startedAt": timestamp()})
        run.mkdir(mode=0o700)
        activation.sync_directory(root)
        result = subprocess.run(  # noqa: S603 -- same pinned module; no secrets in arguments/environment
            [
                sys.executable,
                "-m",
                "scripts.refresh_staging_catalog",
                "--config",
                str(config_path),
                "--capture-run",
                str(run),
            ],
            cwd=ROOT,
            env={"PATH": os.defpath, "PYTHONPATH": str(ROOT / "src"), "PYTHONNOUSERSITE": "1"},
            check=True,
            capture_output=True,
            text=True,
            timeout=10800,
        )
        state, receipt = capture_receipt(config, run, json.loads(result.stdout))
        plan = activation.load_plan(
            {
                "capture": str(run / "capture"),
                "store": str(config["store"]),
                "config": str(config["config"]),
                "work": str(run / "activation"),
                "run_id": run_id,
                "current": config["current"],
                "expected_id": current["Id"],
                "image": config["image"],
                "old_pin": values["NLA_ACTIVATION_SHA256"],
                "old_code": values["NLA_EVIDENCE_CODE_SHA"],
                "new_code": config["code_sha"],
                "summary": state["summarySha256"],
                "manifest": receipt["manifestSha256"],
                "started": receipt["captureStartedAt"],
                "shop": config["shop"],
                "counts": receipt["counts"],
            }
        )
        verify(plan)
        checked = activation.preflight(plan)
        previous_manifest = checked[3]["currentManifestSha256"]
        activation.apply(plan, checked)
        completed = {
            "run": run_id,
            "status": "ready",
            "sourceStartedAt": plan.started,
            "activatedAt": timestamp(),
            "manifestSha256": plan.manifest,
            "activationSha256": activation.pointer(plan)[1],
            "previousManifestSha256": previous_manifest,
            "resources": {
                "runtime": activation.inspect(plan.current)["Id"],
                "before": plan.expected_id,
                "verifier": activation.inspect(plan.verifier)["Id"],
                "promote": activation.inspect(plan.prefix + "-promote")["Id"],
            },
        }
        publish(run / "completed.json", completed)
        retention(config, run, completed)
        publish(root / "last-success.json", completed, replace=True)
        pending.unlink()
        activation.sync_directory(root)
        return completed


def freshness(config):
    """Private operator status; source age is not reset by activation time."""
    receipt = document(config["run_root"] / "last-success.json")
    pointer, pin = activation.pointer(argparse.Namespace(store=config["store"]))
    current = activation.inspect(config["current"])
    if (
        pointer["currentManifestSha256"] != receipt["manifestSha256"]
        or pin != receipt["activationSha256"]
        or current["Id"] != receipt["resources"]["runtime"]
        or not current["State"]["Running"]
    ):
        raise ValueError("freshness receipt does not describe current runtime")
    started = datetime.strptime(receipt["sourceStartedAt"], "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=UTC
    )
    age = (datetime.now(UTC) - started).total_seconds()
    if age < 0:
        raise ValueError("source timestamp is in the future")
    pending = os.path.lexists(config["run_root"] / "pending-run.json")
    return {
        "status": "stale" if age >= 86400 else "refresh_incomplete" if pending else "fresh",
        "sourceAgeSeconds": int(age),
        "sourceStartedAt": receipt["sourceStartedAt"],
        "activatedAt": receipt["activatedAt"],
        "pendingRun": pending,
        "marketNewUpdates": False,
    }


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError("invalid refresh arguments")


def main(argv=None):
    parser = _Parser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--capture-run", type=Path)
    mode.add_argument("--status", action="store_true")
    try:
        args = parser.parse_args(argv)
        config = configuration(args.config)
        if args.status:
            result = freshness(config)
            print(json.dumps(result))
            return 0 if result["status"] == "fresh" else 2
        if args.capture_run is not None:
            print(json.dumps(capture(config, args.capture_run)))
        elif args.apply:
            print(json.dumps(run_once(args.config.resolve(), config)))
        else:
            print("REFRESH_CONFIGURATION_ACCEPTED_NO_CHANGES")
        return 0
    except (Exception, KeyboardInterrupt):
        print("REFRESH_STOPPED_INSPECT_PENDING_RUN_NO_AUTOMATIC_RETRY", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
