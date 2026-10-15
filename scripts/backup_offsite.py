"""Root-only, bounded checkpoint -> existing encrypted restic repository backup.

Never initialize, forget or prune. Failed local jobs require inspection before
another capture can consume disk; successful staging is verified before removal.
"""

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from scripts import backup_checkpoint as checkpoint
from scripts.refresh_staging_catalog import pipeline_lock

REPOSITORY = "s3:https://s3.eu-central-003.backblazeb2.com/nla-catalog/nla/restic-v1"
RESTIC_SHA256 = "20d4142678d0d95ec11a4759def1b73fd9190abc9ca19e4b62d067c0b387e639"
HOST = "nla-catalog"


class BackupError(Exception):
    """A deliberately value-free failure suitable for the journal."""


def timestamp():
    return datetime.now(UTC).isoformat()


def protected(path, *, directory=False, private=False):
    """Require canonical root-owned paths with no writable ancestor or symlink."""
    path = Path(path)
    if not path.is_absolute() or path.resolve() != path:
        raise BackupError("unsafe_path")
    facts = path.lstat()
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    if (
        not kind(facts.st_mode)
        or facts.st_uid != 0
        or facts.st_mode & (0o077 if private else 0o022)
        or (not directory and facts.st_nlink != 1)
    ):
        raise BackupError("unsafe_permissions")
    for parent in path.parents:
        facts = parent.lstat()
        if facts.st_uid != 0 or facts.st_mode & 0o022:
            raise BackupError("unsafe_parent")
    return path


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load_config(path):
    try:
        config = json.loads(protected(path, private=True).read_text())
        expected = {
            "state_root",
            "credential_file",
            "password_file",
            "restic_binary",
            "checkpoint",
            "integrity_mode",
            "command_timeout_seconds",
        }
        if set(config) != expected:
            raise BackupError("invalid_config")
        if config["integrity_mode"] not in {"metadata", "read-data"}:
            raise BackupError("invalid_integrity_mode")
        seconds = config["command_timeout_seconds"]
        if type(seconds) is not int or not 1 <= seconds <= 7200:
            raise BackupError("invalid_timeout")
        protected(config["state_root"], directory=True, private=True)
        binary = protected(config["restic_binary"])
        if not binary.stat().st_mode & 0o111 or digest(binary) != RESTIC_SHA256:
            raise BackupError("unverified_restic_binary")
        return config
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise BackupError("invalid_config") from error


def environment(config, job):
    """No inherited proxies, alternate repositories, AWS profiles or credentials."""
    try:
        passphrase_path = protected(config["password_file"], private=True)
        if not passphrase_path.read_bytes().strip():
            raise BackupError("empty_password")
        credentials = json.loads(protected(config["credential_file"], private=True).read_text())
        if set(credentials) != {"AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"}:
            raise BackupError("invalid_credentials")
        if any(
            not isinstance(value, str) or not value.strip() or "\n" in value or "\r" in value
            for value in credentials.values()
        ):
            raise BackupError("invalid_credentials")
        for name in ("home", "tmp"):
            (job / name).mkdir(mode=0o700)
        return {
            **credentials,
            "RESTIC_REPOSITORY": REPOSITORY,
            "RESTIC_PASSWORD_FILE": str(passphrase_path),
            "AWS_DEFAULT_REGION": "eu-central-003",
            "GOMAXPROCS": "2",
            "PATH": "/usr/bin:/bin",
            "HOME": str(job / "home"),
            "TMPDIR": str(job / "tmp"),
        }
    except (OSError, ValueError, TypeError) as error:
        raise BackupError("invalid_credentials") from error


def command(binary, arguments, env, timeout):
    """Owned subprocess; discard all raw error output, including provider bodies."""
    try:
        result = subprocess.run(  # noqa: S603
            [str(binary), "--json", "--no-cache", *arguments],
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise BackupError("restic_timeout") from error
    except OSError as error:
        raise BackupError("restic_unavailable") from error
    if result.returncode != 0:
        # In particular exit 3 is a partial backup, never a successful receipt.
        raise BackupError("restic_failed")
    try:
        return result.stdout.decode("utf-8")
    except UnicodeError as error:
        raise BackupError("invalid_restic_output") from error


def summary(output):
    try:
        documents = [json.loads(line) for line in output.splitlines() if line.strip()]
        summaries = [item for item in documents if item.get("message_type") == "summary"]
        if len(summaries) != 1 or documents[-1] != summaries[0]:
            raise BackupError("missing_restic_summary")
        return summaries[0]
    except (ValueError, AttributeError, IndexError) as error:
        raise BackupError("invalid_restic_output") from error


def transfer(config, capture_path, manifest, env, job_id, run_command=command, record=None):
    manifest_sha256 = digest(capture_path / "manifest.json")

    def invoke(arguments):
        return run_command(
            config["restic_binary"], arguments, env, config["command_timeout_seconds"]
        )

    backup = summary(invoke(["backup", "--host", HOST, "--tag", job_id, str(capture_path)]))
    snapshot_id = backup.get("snapshot_id", "")
    if (
        not isinstance(snapshot_id, str)
        or re.fullmatch("[0-9a-f]{64}", snapshot_id) is None
        or backup.get("dry_run", False) is not False
    ):
        raise BackupError("invalid_snapshot_id")
    try:
        snapshots = json.loads(invoke(["snapshots", snapshot_id]))
        if len(snapshots) != 1:
            raise BackupError("snapshot_binding_failed")
        snapshot = snapshots[0]
        if (
            snapshot["id"] != snapshot_id
            or snapshot["paths"] != [str(capture_path)]
            or snapshot["tags"] != [job_id]
            or snapshot["hostname"] != HOST
        ):
            raise BackupError("snapshot_binding_failed")
        datetime.fromisoformat(snapshot["time"].replace("Z", "+00:00"))
    except (ValueError, TypeError, KeyError, IndexError, AttributeError) as error:
        raise BackupError("invalid_snapshot_output") from error
    facts = {
        "snapshotId": snapshot_id,
        "snapshotTime": snapshot["time"],
        "checkpointManifestSha256": manifest_sha256,
        "snapshotPaths": [str(capture_path)],
        "checkpointCreatedAt": manifest["createdAt"],
        "integrityMode": config["integrity_mode"],
    }
    if record is not None:
        record.update(facts)
    arguments = ["check"]
    if config["integrity_mode"] == "read-data":
        arguments.append("--read-data")
    check = summary(invoke(arguments))
    if check.get("num_errors") != 0 or check.get("broken_packs"):
        raise BackupError("integrity_check_failed")
    return {**facts, "integrityStatus": "passed"}


def publish(path, document, *, replace=False):
    """Publish complete private JSON without exposing a partially written receipt."""
    temporary = path.with_name("." + path.name + "." + uuid.uuid4().hex)
    with temporary.open("x", encoding="utf-8") as stream:
        os.chmod(temporary, 0o600)
        json.dump(document, stream, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    if replace:
        os.replace(temporary, path)
    else:
        os.link(temporary, path)
        temporary.unlink()
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def cleanup(job, captured, manifest, manifest_sha256):
    """Remove only this invocation's exact, hash-verified completed staging tree."""
    protected(job, directory=True, private=True)
    protected(captured, directory=True, private=True)
    expected = {captured / "manifest.json": manifest_sha256}
    for item in [*manifest["files"], *manifest["images"]]:
        name = Path(item["filename"])
        if name.anchor or ".." in name.parts or not name.parts:
            raise BackupError("unsafe_cleanup_manifest")
        path = captured / name
        if path in expected:
            raise BackupError("duplicate_cleanup_file")
        expected[path] = item["sha256"]
    directories = {captured, job / "home", job / "tmp"}
    for path in expected:
        directories.update(parent for parent in path.parents if parent.is_relative_to(captured))
    actual_files, actual_dirs = set(), set()
    # Walk never follows symlinks; protected() rejects links before any deletion.
    for parent, children, files in os.walk(job, followlinks=False):
        actual_dirs.update(Path(parent) / name for name in children)
        actual_files.update(Path(parent) / name for name in files)
    if actual_files != set(expected) or actual_dirs != directories:
        raise BackupError("unexpected_cleanup_entry")
    for path in directories:
        protected(path, directory=True, private=True)
    for path, sha256 in expected.items():
        protected(path, private=True)
        if digest(path) != sha256:
            raise BackupError("changed_cleanup_file")
    for path in expected:
        path.unlink()
    for path in sorted(directories, key=lambda item: len(item.parts), reverse=True):
        path.rmdir()
    job.rmdir()


def discard_busy_job(job):
    """CheckpointBusy is required to leave no capture artifact."""
    protected(job, directory=True, private=True)
    children = {job / "home", job / "tmp"}
    if set(job.iterdir()) != children:
        raise BackupError("busy_job_has_artifacts")
    for child in children:
        protected(child, directory=True, private=True)
        if any(child.iterdir()):
            raise BackupError("busy_job_has_artifacts")
    for child in children:
        child.rmdir()
    job.rmdir()


def run(config, *, capture=None, run_command=command, lock=pipeline_lock):
    root = Path(config["state_root"])
    job_id = "backup-" + uuid.uuid4().hex
    receipt = {"schemaVersion": 1, "jobId": job_id, "startedAt": timestamp()}
    capture = capture or checkpoint.capture
    try:
        with lock(root):
            jobs, receipts = root / "jobs", root / "receipts"
            jobs.mkdir(mode=0o700, exist_ok=True)
            receipts.mkdir(mode=0o700, exist_ok=True)
            protected(jobs, directory=True, private=True)
            protected(receipts, directory=True, private=True)
            if any(jobs.iterdir()):
                raise BackupError("retained_job_requires_inspection")
            job = jobs / job_id
            job.mkdir(mode=0o700)
            phase = "checkpoint"
            try:
                env = environment(config, job)
                captured = job / "checkpoint"
                manifest = capture(config["checkpoint"], captured)
                phase = "transfer"
                receipt.update(
                    transfer(config, captured, manifest, env, job_id, run_command, record=receipt)
                )
                phase = "cleanup"
                cleanup(job, captured, manifest, receipt["checkpointManifestSha256"])
                receipt["status"] = "complete"
            except checkpoint.CheckpointBusy:
                receipt["status"] = "skipped_busy"
                try:
                    discard_busy_job(job)
                except (BackupError, OSError):
                    receipt.update(status="failed", reason="busy_job_has_artifacts")
            except (BackupError, checkpoint.CheckpointError, OSError):
                receipt["status"] = "failed"
                receipt["reason"] = phase + "_failed"
            receipt["finishedAt"] = timestamp()
            publish(receipts / (job_id + ".json"), receipt)
            if receipt["status"] == "complete":
                publish(root / "last-success.json", receipt, replace=True)
            return receipt
    except BlockingIOError:
        return {**receipt, "status": "skipped_busy", "finishedAt": timestamp()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if sys.platform != "linux" or os.geteuid() != 0:
            raise BackupError("linux_root_required")
        os.umask(0o077)
        result = run(load_config(args.config))
        print(json.dumps({"status": result["status"], "jobId": result["jobId"]}))
        return 0 if result["status"] in {"complete", "skipped_busy"} else 1
    except (BackupError, OSError, ValueError):
        print('{"status":"failed","reason":"backup_rejected"}')
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
