"""Read-only operational observation, separate from catalog readiness/routing."""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import shutil
import stat
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

MAX_DOCUMENT_BYTES = 128 * 1024
# 50 batches x 100 scalar attempts fit below 1 MiB; reserve eight times that
# budget for batch/deferred metadata without allowing an unbounded JSON parse.
MAX_MARKET_RECEIPT_BYTES = 8 * 1024**2
MAX_SOURCE_AGE_SECONDS = 86400
MAX_BACKUP_AGE_SECONDS = 26 * 60 * 60
MIN_FREE_BYTES = 6 * 1024**3
REASONS = frozenset(
    {
        "healthy",
        "job_attention",
        "market_incomplete",
        "low_disk",
        "runtime_unavailable",
        "source_stale_or_unverified",
        "backup_attention",
        "scheduler_attention",
        "observation_unknown",
    }
)
OBSERVATION_TTL_SECONDS = 90
UNITS = (
    "nla-catalog-refresh.service",
    "nla-market-catalog.service",
    "nla-backup-offsite.service",
)
TIMERS = tuple(name.replace(".service", ".timer") for name in UNITS)
PROPERTIES = (
    "LoadState",
    "ActiveState",
    "SubState",
    "Result",
    "ExecMainStatus",
    "Job",
    "ExecMainStartTimestamp",
)
TIMER_PROPERTIES = ("LoadState", "ActiveState", "SubState", "Result", "UnitFileState")
BACKUP_JOB_PATTERN = r"backup-[0-9a-f]{32}"


def read_document(path: Path, *, max_bytes: int = MAX_DOCUMENT_BYTES) -> tuple[dict, bytes]:
    """Bounded regular-file read; no paths or contents enter exception messages."""
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(path, flags), "rb") as source:
        facts = os.fstat(source.fileno())
        if not stat.S_ISREG(facts.st_mode) or facts.st_size > max_bytes:
            raise ValueError("invalid observation input")
        raw = source.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError("invalid observation input")
    value = json.loads(raw)
    if type(value) is not dict:
        raise ValueError("invalid observation input")
    return value, raw


def timestamp(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def job_running(unit: dict) -> bool:
    return unit["ActiveState"] in ("active", "activating") or unit["Job"] not in ("", "0")


def job_healthy(unit: dict, pending: dict | None, terminal: dict | None) -> bool:
    """A queued/running job is not failure; prior failure is never hidden."""
    if (
        set(unit) != set(PROPERTIES)
        or unit["LoadState"] != "loaded"
        or unit["Result"] != "success"
        or unit["ExecMainStatus"] != "0"
        or unit["ActiveState"] not in ("active", "activating", "inactive")
        or not unit["SubState"]
        or re.fullmatch(r"[0-9]*", unit["Job"]) is None
    ):
        return False
    if terminal is not None:
        return False
    return pending is None or job_running(unit)


def source_healthy(
    pointer: dict, pin: str, receipt: dict, now: datetime, max_age: int = MAX_SOURCE_AGE_SECONDS
) -> bool:
    if (
        receipt.get("status") != "ready"
        or re.fullmatch(r"[0-9a-f]{64}", str(receipt.get("manifestSha256"))) is None
        or pointer.get("currentManifestSha256") != receipt["manifestSha256"]
        or receipt.get("activationSha256") != pin
    ):
        return False
    age = (now - timestamp(receipt["sourceStartedAt"])).total_seconds()
    return 0 <= age < max_age


def systemd_units(names: tuple[str, ...], properties: tuple[str, ...]) -> dict[str, dict]:
    """Two fixed batches cover services/timers inside the collector deadline."""
    result = subprocess.run(  # noqa: S603 -- fixed executable/properties/unit allowlist
        [
            "/usr/bin/systemctl",
            "show",
            *names,
            "--no-pager",
            "--all",
            "--timestamp=unix",
            "--property=Id," + ",".join(properties),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=3,
        env={"PATH": os.defpath, "LC_ALL": "C"},
    )
    # Only selected scalar properties; reject changed/oversized output contracts.
    if len(result.stdout) > 4096 * len(names):
        raise ValueError("invalid service observation")
    units = {}
    for block in result.stdout.strip().split("\n\n"):
        lines = [line.split("=", 1) for line in block.splitlines()]
        unit = dict(lines)
        name = unit.pop("Id")
        if name not in names or name in units or len(lines) != len(unit) + 1:
            raise ValueError("invalid service observation")
        if set(unit) != set(properties):
            raise ValueError("invalid service observation")
        units[name] = unit
    if set(units) != set(names):
        raise ValueError("invalid service observation")
    return units


def timers_healthy(timers: dict[str, dict], market: dict) -> bool:
    for name, timer in timers.items():
        # The market service deliberately stops this timer during its child refresh.
        paused = name == TIMERS[0] and market["ActiveState"] in ("active", "activating")
        if (
            timer["LoadState"] != "loaded"
            or timer["UnitFileState"] != "enabled"
            or timer["Result"] != "success"
            or (
                (timer["ActiveState"], timer["SubState"])
                not in (("active", "waiting"), ("active", "running"))
                and not (
                    paused and (timer["ActiveState"], timer["SubState"]) == ("inactive", "dead")
                )
            )
        ):
            return False
    return True


def backup_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() is None:
        raise ValueError("invalid backup timestamp")
    return parsed.astimezone(UTC)


def backup_healthy(
    root: Path,
    unit: dict,
    now: datetime,
    max_age: int,
    *,
    observation_started: float | None = None,
) -> bool:
    """Observe existing local evidence only; never run backup/check or scan receipts."""
    if observation_started is None:
        observation_started = time.monotonic()
    receipt, _ = read_document(root / "last-success.json")
    job_id = receipt.get("jobId")
    if (
        type(receipt.get("schemaVersion")) is not int
        or receipt["schemaVersion"] != 1
        or not isinstance(job_id, str)
        or re.fullmatch(BACKUP_JOB_PATTERN, job_id) is None
        or receipt.get("status") != "complete"
        or receipt.get("integrityMode") != "read-data"
        or receipt.get("integrityStatus") != "passed"
        or not isinstance(receipt.get("snapshotId"), str)
        or re.fullmatch(r"[0-9a-f]{64}", str(receipt.get("snapshotId"))) is None
        or not isinstance(receipt.get("checkpointManifestSha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", str(receipt.get("checkpointManifestSha256"))) is None
    ):
        return False
    immutable, _ = read_document(root / "receipts" / (job_id + ".json"))
    if receipt != immutable:
        return False
    started, captured, snapshot, finished = (
        backup_timestamp(receipt[key])
        for key in ("startedAt", "checkpointCreatedAt", "snapshotTime", "finishedAt")
    )
    # Metadata/receipt reads can span a legitimate completion. Advance only by
    # elapsed monotonic time; keep the published observation timestamp unchanged.
    observed = now + timedelta(seconds=time.monotonic() - observation_started)
    if not started <= captured <= snapshot <= finished <= observed or not (
        0 <= (observed - captured).total_seconds() < max_age
    ):
        return False
    expected_path = str(root / "jobs" / job_id / "checkpoint")
    if receipt.get("snapshotPaths") != [expected_path]:
        return False
    jobs = root / "jobs"
    if not stat.S_ISDIR(jobs.lstat().st_mode):
        return False
    # At most one active job can exist; stop after two entries even after incidents.
    with os.scandir(jobs) as entries:
        entry = next(entries, None)
        if entry is None:
            return True
        if next(entries, None) is not None:
            return False
        facts = entry.stat(follow_symlinks=False)
        if (
            not stat.S_ISDIR(facts.st_mode)
            or re.fullmatch(BACKUP_JOB_PATTERN, entry.name) is None
            or unit["ActiveState"] not in ("active", "activating")
            or (root / "receipts" / (entry.name + ".json")).exists()
        ):
            return False
        # Reject staging older than this invocation; mtime is only temporal evidence.
        start = unit["ExecMainStartTimestamp"]
        if re.fullmatch(r"@[0-9]+", start) is None:
            return False
        observed = now + timedelta(seconds=time.monotonic() - observation_started)
        return int(start[1:]) <= facts.st_mtime <= observed.timestamp()


def runtime_ready(port: int) -> bool:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
    try:
        connection.request("GET", "/readyz")
        return connection.getresponse().status == 200
    except (OSError, http.client.HTTPException):
        return False
    finally:
        connection.close()


def pending_state(root: Path, filename: str, market: bool) -> tuple[dict | None, dict | None]:
    marker = root / filename
    if not marker.exists():
        return None, None
    pending, _ = read_document(marker)
    pattern = (
        r"market-[0-9]{8}t[0-9]{6}z-[0-9a-f]{8}" if market else r"[0-9]{8}t[0-9]{6}z-[0-9a-f]{8}"
    )
    if re.fullmatch(pattern, pending["run"]) is None:
        raise ValueError("invalid pending observation")
    stopped = root / pending["run"] / "stopped.json"
    return pending, {} if stopped.exists() else None


@dataclass(frozen=True)
class ObserverPaths:
    refresh: Path
    market: Path
    store: Path
    backup: Path


def collect(
    paths: ObserverPaths,
    *,
    now: datetime,
    min_free_bytes: int = MIN_FREE_BYTES,
    max_source_age_seconds: int = MAX_SOURCE_AGE_SECONDS,
    max_backup_age_seconds: int = MAX_BACKUP_AGE_SECONDS,
) -> str:
    """No credentials, exports, pipeline locks or writes. Errors fail closed at caller."""
    observation_started = time.monotonic()
    if min(min_free_bytes, max_source_age_seconds, max_backup_age_seconds) <= 0:
        raise ValueError("invalid observation threshold")
    units = systemd_units(UNITS, PROPERTIES)
    refresh_unit, market_unit, backup_unit = (units[name] for name in UNITS)
    refresh_pending, refresh_stopped = pending_state(paths.refresh, "pending-run.json", False)
    market_pending, market_stopped = pending_state(paths.market, "pending-market-run.json", True)
    if not job_healthy(market_unit, market_pending, market_stopped):
        return "job_attention"
    # The market oneshot starts refresh_index as a child process, so the separate
    # refresh unit remains inactive. Existing markers provide temporal ownership.
    market_child = (
        refresh_pending is not None
        and market_pending is not None
        and job_running(market_unit)
        and timestamp(market_pending["startedAt"]) <= timestamp(refresh_pending["startedAt"]) <= now
    )
    if not job_healthy(refresh_unit, None if market_child else refresh_pending, refresh_stopped):
        return "job_attention"
    if not job_healthy(backup_unit, None, None):
        return "backup_attention"
    if not timers_healthy(systemd_units(TIMERS, TIMER_PROPERTIES), market_unit):
        return "scheduler_attention"
    if not backup_healthy(
        paths.backup,
        backup_unit,
        now,
        max_backup_age_seconds,
        observation_started=observation_started,
    ):
        return "backup_attention"
    market_success, _ = read_document(
        paths.market / "last-market-success.json", max_bytes=MAX_MARKET_RECEIPT_BYTES
    )
    if market_success.get("status") != "draft_cycle_complete":
        return "market_incomplete"
    if shutil.disk_usage("/").free < min_free_bytes:
        return "low_disk"
    if not any(runtime_ready(port) for port in (10000, 10001)):
        return "runtime_unavailable"
    # Activation updates the pointer before the completed/last-success receipts.
    # Retry a bounded number of coherent snapshots, including the pending completed
    # receipt. Never reset source age to a job start or an observer timestamp.
    for _ in range(3):
        pointer, raw = read_document(paths.store / "activation.v1.json")
        pin = hashlib.sha256(raw).hexdigest()
        receipt, _ = read_document(paths.refresh / "last-success.json")
        receipts = [receipt]
        if refresh_pending is not None:
            completed = paths.refresh / refresh_pending["run"] / "completed.json"
            if completed.exists():
                candidate, _ = read_document(completed)
                if candidate.get("run") == refresh_pending["run"]:
                    receipts.append(candidate)
        pointer_after, raw_after = read_document(paths.store / "activation.v1.json")
        if pointer_after == pointer and raw_after == raw:
            if any(
                source_healthy(pointer, pin, item, now, max_source_age_seconds) for item in receipts
            ):
                return "healthy"
    return "source_stale_or_unverified"


def write_observation(path: Path, *, now: datetime, healthy: bool) -> None:
    """Publish only sanitized status into a dedicated systemd RuntimeDirectory."""
    raw = json.dumps({"checkedAt": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "healthy": healthy})
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as output:
        output.write(raw)
    temporary.chmod(0o644)
    os.replace(temporary, path)


class OperationalHealthApp:
    """A value-free endpoint; its UID needs access only to sanitized observation."""

    def __init__(self, observation: Path):
        self.observation = observation

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            raise ValueError("HTTP only")
        status, body = 404, b"Not found\n"
        if (
            scope.get("method") in ("GET", "HEAD")
            and scope.get("path") == "/opsz"
            and not scope.get("query_string")
        ):
            healthy = False
            try:
                value, _ = read_document(self.observation)
                age = (datetime.now(UTC) - timestamp(value["checkedAt"])).total_seconds()
                healthy = (
                    set(value) == {"checkedAt", "healthy"}
                    and value["healthy"] is True
                    and 0 <= age < OBSERVATION_TTL_SECONDS
                )
            except Exception:
                healthy = False
            status, body = (200, b"healthy\n") if healthy else (503, b"attention\n")
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"text/plain; charset=utf-8"),
                    (b"cache-control", b"no-store"),
                    (b"x-content-type-options", b"nosniff"),
                ],
            }
        )
        await send(
            {"type": "http.response.body", "body": b"" if scope.get("method") == "HEAD" else body}
        )
