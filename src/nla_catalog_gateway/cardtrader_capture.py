"""GET-only capture with explicit unavailable exports; interrupted runs are unusable."""

import hashlib
import json
import os
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path

from nla_catalog_gateway.cardtrader_candidates import compare_catalog
from nla_catalog_gateway.cardtrader_catalog import (
    MAX_RESPONSE_BYTES,
    CardTraderCatalogClient,
    CardTraderCatalogError,
    catalog_rows,
)

GAME_IDS = frozenset((1, 4, 5, 15))
MAX_BYTES = 2 * 1024**3
MIN_FREE_BYTES = 4 * 1024**3
MAX_SECONDS = 10800
MAX_GET_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = (2, 5)
RETRYABLE_HTTP_STATUSES = frozenset((408, 429, 500, 502, 503, 504))
SAFE_CATALOG_FAILURE_REASONS = frozenset(
    (
        "request_failed",
        "unexpected_status",
        "invalid_collection",
        "response_too_large",
        "invalid_json",
    )
)


def _capture_status(anomalies, deferred):
    if deferred:
        return "partial_with_deferred_expansions"
    return "complete_with_source_anomalies" if anomalies else "complete"


def compare_captured_catalog(destination: Path, products, categories: dict, *, now=None) -> dict:
    """Join verified available exports to a supplied Shopify snapshot, read-only.

    categories maps IDs to (game ID, verified source category name, family).
    The existing comparison accounts for every row and all cross-expansion ID
    clashes. Absence is only relative to the supplied snapshot, never write approval.
    """
    if not destination.is_absolute() or destination.is_symlink():
        raise ValueError("invalid_capture_directory")
    progress = destination / "progress.json"
    if progress.is_symlink() or progress.stat().st_size > MAX_RESPONSE_BYTES:
        raise ValueError("invalid_capture_progress")
    encoded = progress.read_bytes()
    status = json.loads(encoded)
    count_keys = (
        "totalExpansions",
        "completedExpansions",
        "blueprints",
        "sourceAnomalyCount",
        "bytes",
    )
    if (
        status["status"]
        not in ("complete", "complete_with_source_anomalies", "partial_with_deferred_expansions")
        or any(type(status[k]) is not int or status[k] < 0 for k in count_keys)
        or status["automaticImportEnabled"] is not False
        or status["shopifyChanged"] is not False
    ):
        raise ValueError("incomplete_capture")
    started = datetime.fromisoformat(status["startedAt"])
    finished = datetime.fromisoformat(status["finishedAt"])
    current = now or datetime.now(UTC)
    if not started <= finished <= current or not 0 <= (current - started).total_seconds() <= 86400:
        raise ValueError("stale_capture")
    used = set()
    total_bytes = 0

    def read(name):
        nonlocal total_bytes
        path = destination / name
        facts = status["files"][name]
        size = path.stat().st_size
        if (
            path.is_symlink()
            or not path.is_file()
            or size > MAX_RESPONSE_BYTES
            or type(facts["bytes"]) is not int
            or size != facts["bytes"]
        ):
            raise ValueError("invalid_capture_file")
        data = path.read_bytes()
        total_bytes += len(data)
        if total_bytes > MAX_BYTES or hashlib.sha256(data).hexdigest() != facts["sha256"]:
            raise ValueError("capture_digest_mismatch")
        used.add(name)
        return catalog_rows(json.loads(data))

    games = read("games.json")
    if not GAME_IDS <= {r.get("id") for r in games if type(r.get("id")) is int}:
        raise ValueError("missing_games")
    category_rows = read("categories.json")
    for identifier, (game, name, _) in categories.items():
        found = [r for r in category_rows if r.get("id") == identifier]
        if len(found) != 1 or found[0].get("game_id") != game or found[0].get("name") != name:
            raise ValueError("category_mapping_changed")
    selected = [
        r
        for r in read("expansions.json")
        if type(r.get("game_id")) is int and r["game_id"] in GAME_IDS
    ]
    if (
        not selected
        or len(selected) > 10000
        or any(type(r.get("id")) is not int or not 0 < r["id"] < 2**63 for r in selected)
        or len({r["id"] for r in selected}) != len(selected)
        or {r["game_id"] for r in selected} != GAME_IDS
        or len(selected) != status["totalExpansions"]
    ):
        raise ValueError("invalid_capture_expansions")
    deferred = status.get("deferredExpansions", [])
    selected_ids = {r["id"] for r in selected}
    if not isinstance(deferred, list) or any(
        not isinstance(row, dict)
        or set(row) != {"expansionId", "httpStatus", "reason"}
        or type(row["expansionId"]) is not int
        or row["expansionId"] not in selected_ids
        or type(row["httpStatus"]) is not int
        or row["httpStatus"] != 404
        or row["reason"] != "export_http_404"
        for row in deferred
    ):
        raise ValueError("invalid_deferred_expansions")
    deferred_ids = {row["expansionId"] for row in deferred}
    if (
        len(deferred_ids) != len(deferred)
        or status["completedExpansions"] + len(deferred) != len(selected)
        or any((destination / f"blueprints-{i}.json").exists() for i in deferred_ids)
    ):
        raise ValueError("invalid_capture_expansions")
    rows, provenance, quarantined = [], [], set()
    for expansion in sorted(selected, key=lambda r: r["id"]):
        if expansion["id"] in deferred_ids:
            continue
        batch = read(f"blueprints-{expansion['id']}.json")
        anomalies = []
        for index, row in enumerate(batch):
            if (
                type(row.get("game_id")) is not int
                or row["game_id"] != expansion["game_id"]
                or type(row.get("expansion_id")) is not int
                or row["expansion_id"] != expansion["id"]
            ):
                quarantined.add(len(rows))
                anomalies.append(
                    dict(
                        rowIndex=index,
                        blueprintId=row.get("id") if type(row.get("id")) is int else None,
                        reason="export_game_or_expansion_conflict",
                    )
                )
            rows.append(
                {
                    key: row.get(key)
                    for key in ("id", "game_id", "category_id", "expansion_id", "card_market_ids")
                }
            )
            provenance.append((expansion["id"], index))
        if anomalies and read(f"anomalies-{expansion['id']}.json") != anomalies:
            raise ValueError("capture_anomaly_mismatch")
    if (
        used != set(status["files"])
        or total_bytes != status["bytes"]
        or len(rows) != status["blueprints"]
        or len(quarantined) != status["sourceAnomalyCount"]
        or status["status"] != _capture_status(quarantined, deferred)
        or progress.read_bytes() != encoded
    ):
        raise ValueError("capture_counts_mismatch")
    report = compare_catalog(
        rows,
        products,
        {identifier: (game, family) for identifier, (game, _, family) in categories.items()},
        {r["id"]: r["game_id"] for r in selected},
    )
    for index, item in enumerate(report):
        item["sourceExpansionId"], item["sourceRowIndex"] = provenance[index]
        if index in quarantined:
            item["decision"] = "source_export_conflict"
    return dict(
        status="read_only_comparison_complete",
        sourceRows=len(rows),
        sourceAnomalyCount=len(quarantined),
        sourceComplete=not deferred,
        deferredExpansions=deferred,
        sourceStartedAt=status["startedAt"],
        captureSha256=hashlib.sha256(encoded).hexdigest(),
        details=report,
        creationApproved=False,
        shopifyChanged=False,
    )


def capture_catalog(client: CardTraderCatalogClient, destination: Path) -> dict:
    """Use a NEW private directory each run; bounded GET retries, no deletion or Shopify calls.

    Query every expansion of the four approved games, including old expansions:
    source IDs are not release dates, and old sets can receive new blueprints.
    Preserve all source rows and explicit per-export anomaly indices. Consumers
    require accounted-for coverage, all files/hashes/counts and current identities.
    A listed expansion's HTTP404 is deferred, never represented as an empty export.
    Each new cycle tries it again. Other errors still stop the capture.
    """
    if not isinstance(destination, Path) or not destination.is_absolute():
        raise ValueError("absolute_capture_directory_required")
    destination.mkdir(mode=0o700, exist_ok=False)
    started = time.monotonic()
    status = {
        "status": "running",
        "startedAt": datetime.now(UTC).isoformat(),
        "completedExpansions": 0,
        "blueprints": 0,
        "bytes": 0,
        "sourceAnomalyCount": 0,
        "deferredExpansions": [],
        "requestAttempts": 0,
        "requestRetries": 0,
        "automaticImportEnabled": False,
        "shopifyChanged": False,
        "files": {},
    }

    def save(name, data):
        encoded = json.dumps(data, ensure_ascii=True).encode()
        if (
            status["bytes"] + len(encoded) > MAX_BYTES
            or shutil.disk_usage(destination).free - len(encoded) < MIN_FREE_BYTES
        ):
            raise ValueError("capture_storage_limit")
        path = destination / name
        with path.open("xb") as out:
            out.write(encoded)
        os.chmod(path, 0o600)
        status["bytes"] += len(encoded)
        status["files"][name] = {
            "sha256": hashlib.sha256(encoded).hexdigest(),
            "bytes": len(encoded),
        }

    def checkpoint():
        temporary = destination / "progress.tmp"
        with temporary.open("wb") as out:
            out.write(json.dumps(status).encode())
            out.flush()
            os.fsync(out.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination / "progress.json")

    def get(kind, **kwargs):
        expansion_id = kwargs.get("expansion_id")
        attempts = 0
        retries = 0
        last_http_status = None

        def safe_status(value):
            return value if type(value) is int and 100 <= value <= 599 else None

        def record_failure(reason, http_status):
            nonlocal last_http_status
            safe_reason = (
                reason
                if type(reason) is str and reason in SAFE_CATALOG_FAILURE_REASONS
                else "catalog_request_failed"
            )
            safe_http_status = safe_status(http_status)
            failure = dict(
                reason=safe_reason,
                catalogKind=kind,
                expansionId=expansion_id,
                attempts=attempts,
                retries=retries,
                httpStatus=safe_http_status,
            )
            last_http_status = safe_http_status
            if not (kind == "blueprints" and http_status == 404):
                status["failure"] = failure

        def deadline_failure():
            status["failure"] = dict(
                reason="capture_deadline",
                catalogKind=kind,
                expansionId=expansion_id,
                attempts=attempts,
                retries=retries,
                httpStatus=safe_status(last_http_status),
            )

        while True:
            if time.monotonic() - started >= MAX_SECONDS:
                deadline_failure()
                raise ValueError("capture_deadline")
            # Preserve the existing one-second shared-account pacing on every try.
            time.sleep(1)
            if time.monotonic() - started >= MAX_SECONDS:
                deadline_failure()
                raise ValueError("capture_deadline")
            attempts += 1
            status["requestAttempts"] += 1
            if attempts > 1:
                retries += 1
                status["requestRetries"] += 1
            try:
                rows = client.collection(kind, **kwargs)
            except CardTraderCatalogError as error:
                reason = error.args[0] if error.args else ""
                record_failure(reason, error.http_status)
                if time.monotonic() - started >= MAX_SECONDS:
                    deadline_failure()
                    raise ValueError("capture_deadline") from None
                retryable = (reason == "request_failed" and error.http_status is None) or (
                    reason in ("request_failed", "unexpected_status")
                    and safe_status(error.http_status) in RETRYABLE_HTTP_STATUSES
                )
                if retryable and attempts < MAX_GET_ATTEMPTS:
                    time.sleep(RETRY_BACKOFF_SECONDS[attempts - 1])
                    if time.monotonic() - started >= MAX_SECONDS:
                        deadline_failure()
                        raise ValueError("capture_deadline") from None
                    status.pop("failure", None)
                    continue
                raise
            last_http_status = None
            if time.monotonic() - started >= MAX_SECONDS:
                deadline_failure()
                raise ValueError("capture_deadline")
            return rows

    try:
        games = get("games")
        if not GAME_IDS <= {r.get("id") for r in games if type(r.get("id")) is int}:
            raise ValueError("missing_games")
        save("games.json", games)
        save("categories.json", get("categories"))
        expansions = get("expansions")
        save("expansions.json", expansions)
        selected = [
            r for r in expansions if type(r.get("game_id")) is int and r["game_id"] in GAME_IDS
        ]
        if (
            not selected
            or len(selected) > 10000
            or any(type(r.get("id")) is not int or not 0 < r["id"] < 2**63 for r in selected)
            or len({r["id"] for r in selected}) != len(selected)
            or {r["game_id"] for r in selected} != GAME_IDS
        ):
            raise ValueError("invalid_expansions")
        status["totalExpansions"] = len(selected)
        checkpoint()
        for expansion in sorted(selected, key=lambda r: r["id"]):
            try:
                rows = get("blueprints", expansion_id=expansion["id"])
            except CardTraderCatalogError as error:
                if error.http_status != 404:
                    raise
                if time.monotonic() - started >= MAX_SECONDS:
                    raise ValueError("capture_deadline") from None
                status["deferredExpansions"].append(
                    dict(expansionId=expansion["id"], httpStatus=404, reason="export_http_404")
                )
                checkpoint()
                continue
            anomalies = [
                {
                    "rowIndex": index,
                    "blueprintId": row.get("id") if type(row.get("id")) is int else None,
                    "reason": "export_game_or_expansion_conflict",
                }
                for index, row in enumerate(rows)
                if type(row.get("game_id")) is not int
                or row["game_id"] != expansion["game_id"]
                or type(row.get("expansion_id")) is not int
                or row["expansion_id"] != expansion["id"]
            ]
            if anomalies:
                save(f"anomalies-{expansion['id']}.json", anomalies)
                status["sourceAnomalyCount"] += len(anomalies)
            save(f"blueprints-{expansion['id']}.json", rows)
            status["blueprints"] += len(rows)
            status["completedExpansions"] += 1
            checkpoint()
        status["status"] = _capture_status(
            status["sourceAnomalyCount"], status["deferredExpansions"]
        )
        status["finishedAt"] = datetime.now(UTC).isoformat()
        checkpoint()
        return status
    except Exception as error:
        status["status"] = "failed"
        status["errorType"] = type(error).__name__
        status_code = getattr(error, "http_status", None)
        status["httpStatus"] = (
            status_code if type(status_code) is int and 100 <= status_code <= 599 else None
        )
        status.setdefault(
            "failure",
            dict(
                reason="capture_deadline"
                if type(error) is ValueError and error.args == ("capture_deadline",)
                else "capture_failed",
                catalogKind=None,
                expansionId=None,
                attempts=0,
                retries=0,
                httpStatus=None,
            ),
        )
        checkpoint()
        raise RuntimeError("catalog_capture_failed") from None
