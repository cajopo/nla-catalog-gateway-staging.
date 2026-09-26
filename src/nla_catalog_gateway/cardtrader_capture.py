"""Repeatable GET-only catalog capture; partial runs never become usable snapshots."""

import hashlib
import json
import os
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path

from nla_catalog_gateway.cardtrader_catalog import CardTraderCatalogClient

GAME_IDS = frozenset((1, 4, 5, 15))
MAX_BYTES = 2 * 1024**3
MIN_FREE_BYTES = 4 * 1024**3
MAX_SECONDS = 10800


def capture_catalog(client: CardTraderCatalogClient, destination: Path) -> dict:
    """Use a NEW private directory each run; no retries, deletion or Shopify calls.

    Query every expansion of the four approved games, including old expansions:
    source IDs are not release dates, and old sets can receive new blueprints.
    Preserve all source rows and explicit per-export anomaly indices. Consumers
    must require a complete status, all files/hashes/counts and current identities
    before considering import candidates. Completion does not authorize writes.
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
        if time.monotonic() - started >= MAX_SECONDS:
            raise ValueError("capture_deadline")
        time.sleep(1)  # Conservative shared-account rate, well below documented limit.
        rows = client.collection(kind, **kwargs)
        if time.monotonic() - started >= MAX_SECONDS:
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
            rows = get("blueprints", expansion_id=expansion["id"])
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
        status["status"] = (
            "complete_with_source_anomalies" if status["sourceAnomalyCount"] else "complete"
        )
        status["finishedAt"] = datetime.now(UTC).isoformat()
        checkpoint()
        return status
    except Exception as error:
        status["status"] = "failed"
        status["errorType"] = type(error).__name__
        status["httpStatus"] = getattr(error, "http_status", None)
        checkpoint()
        raise RuntimeError("catalog_capture_failed") from None
