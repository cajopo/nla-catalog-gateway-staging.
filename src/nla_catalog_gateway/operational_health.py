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
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

MAX_DOCUMENT_BYTES = 128 * 1024
# 50 batches x 100 scalar attempts fit below 1 MiB; reserve eight times that
# budget for batch/deferred metadata without allowing an unbounded JSON parse.
MAX_MARKET_RECEIPT_BYTES = 8 * 1024**2
MAX_SOURCE_AGE_SECONDS = 86400
MIN_FREE_BYTES = 6 * 1024**3
REASONS = frozenset(
    {
        "healthy",
        "job_attention",
        "market_incomplete",
        "low_disk",
        "runtime_unavailable",
        "source_stale_or_unverified",
        "observation_unknown",
    }
)
OBSERVATION_TTL_SECONDS = 90
UNITS = ("nla-catalog-refresh.service", "nla-market-catalog.service")
PROPERTIES = ("LoadState", "ActiveState", "SubState", "Result", "ExecMainStatus", "Job")


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


def systemd_unit(name: str) -> dict:
    result = subprocess.run(  # noqa: S603 -- fixed executable/properties/unit allowlist
        [
            "/usr/bin/systemctl",
            "show",
            name,
            "--no-pager",
            "--all",
            "--property=" + ",".join(PROPERTIES),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=3,
        env={"PATH": os.defpath, "LC_ALL": "C"},
    )
    # Only selected scalar properties; reject changed/oversized output contracts.
    if len(result.stdout) > 4096:
        raise ValueError("invalid service observation")
    return dict(line.split("=", 1) for line in result.stdout.splitlines())


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


def collect(
    paths: ObserverPaths,
    *,
    now: datetime,
    min_free_bytes: int = MIN_FREE_BYTES,
    max_source_age_seconds: int = MAX_SOURCE_AGE_SECONDS,
) -> str:
    """No credentials, exports, pipeline locks or writes. Errors fail closed at caller."""
    refresh_unit, market_unit = (systemd_unit(name) for name in UNITS)
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
