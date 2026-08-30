#!/usr/bin/env python3
"""Simulate deterministic Shopify smart-collection shards without mutations."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class IdBucket:
    source_id: int
    product_ids: tuple[str, ...]

    @property
    def count(self) -> int:
        return len(self.product_ids)


@dataclass(frozen=True, slots=True)
class Shard:
    number: int
    minimum_source_id: int
    maximum_source_id: int
    product_count: int
    product_id_sha256: str


class SimulationError(RuntimeError):
    """Raised when the input cannot produce safe integer-range shards."""


def _catalog_columns(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(catalog_products)")
    }


def _load_buckets(
    connection: sqlite3.Connection,
    *,
    game: str,
    record_type: str | None,
) -> tuple[list[IdBucket], int]:
    columns = _catalog_columns(connection)
    required = {"game", "product_gid", "published_online_store", "source_id", "status"}
    missing = sorted(required - columns)
    if missing:
        raise SimulationError(f"catalog_products missing columns: {', '.join(missing)}")
    if record_type is not None and "record_type" not in columns:
        raise SimulationError("record_type filter requested but the column is absent")

    if record_type is None:
        query = """
            SELECT source_id, product_gid
            FROM catalog_products
            WHERE game = ? AND status = 'ACTIVE' AND published_online_store = 1
            ORDER BY CAST(source_id AS INTEGER), source_id, product_gid
        """
        params = (game,)
    else:
        query = """
            SELECT source_id, product_gid
            FROM catalog_products
            WHERE game = ? AND record_type = ?
              AND status = 'ACTIVE' AND published_online_store = 1
            ORDER BY CAST(source_id AS INTEGER), source_id, product_gid
        """
        params = (game, record_type)
    rows = connection.execute(query, params)

    grouped: dict[int, list[str]] = defaultdict(list)
    nonnumeric = 0
    for source_id_raw, product_gid in rows:
        source_id_text = str(source_id_raw or "").strip()
        if not source_id_text.isdecimal():
            nonnumeric += 1
            continue
        grouped[int(source_id_text)].append(str(product_gid))
    buckets = [
        IdBucket(source_id=source_id, product_ids=tuple(product_ids))
        for source_id, product_ids in sorted(grouped.items())
    ]
    return buckets, nonnumeric


def _digest_product_ids(product_ids: list[str]) -> str:
    digest = hashlib.sha256()
    for product_id in product_ids:
        digest.update(product_id.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def build_shards(buckets: list[IdBucket], cap: int) -> list[Shard]:
    """Pack complete source-ID buckets into stable ranges no larger than cap."""
    if cap < 1:
        raise SimulationError("cap must be positive")
    shards: list[Shard] = []
    current: list[IdBucket] = []
    current_count = 0

    def flush() -> None:
        nonlocal current, current_count
        if not current:
            return
        product_ids = [product_id for bucket in current for product_id in bucket.product_ids]
        shards.append(
            Shard(
                number=len(shards) + 1,
                minimum_source_id=current[0].source_id,
                maximum_source_id=current[-1].source_id,
                product_count=current_count,
                product_id_sha256=_digest_product_ids(product_ids),
            )
        )
        current = []
        current_count = 0

    for bucket in buckets:
        if bucket.count > cap:
            raise SimulationError(
                f"source_id {bucket.source_id} has {bucket.count} products, above cap {cap}"
            )
        if current and current_count + bucket.count > cap:
            flush()
        current.append(bucket)
        current_count += bucket.count
    flush()
    return shards


def simulate(
    database_path: Path,
    *,
    caps: list[int],
    record_type: str | None = None,
) -> dict[str, Any]:
    uri = f"file:{database_path.resolve()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        integrity = str(connection.execute("PRAGMA quick_check").fetchone()[0])
        if integrity != "ok":
            raise SimulationError(f"database quick_check failed: {integrity}")
        columns = _catalog_columns(connection)
        games = [
            str(row[0])
            for row in connection.execute(
                "SELECT DISTINCT game FROM catalog_products WHERE game IS NOT NULL ORDER BY game"
            )
        ]
        results: dict[str, Any] = {}
        for cap in caps:
            cap_result: dict[str, Any] = {"games": {}, "totalProducts": 0, "totalShards": 0}
            for game in games:
                buckets, nonnumeric = _load_buckets(
                    connection,
                    game=game,
                    record_type=record_type,
                )
                if nonnumeric:
                    raise SimulationError(f"{game}: {nonnumeric} nonnumeric source IDs")
                shards = build_shards(buckets, cap)
                duplicate_groups = sum(bucket.count > 1 for bucket in buckets)
                product_count = sum(shard.product_count for shard in shards)
                cap_result["games"][game] = {
                    "duplicateSourceIdGroups": duplicate_groups,
                    "productCount": product_count,
                    "shardCount": len(shards),
                    "shards": [asdict(shard) for shard in shards],
                }
                cap_result["totalProducts"] += product_count
                cap_result["totalShards"] += len(shards)
            results[str(cap)] = cap_result
        return {
            "database": str(database_path),
            "integrity": integrity,
            "recordTypeColumnPresent": "record_type" in columns,
            "recordTypeFilter": record_type,
            "sourceField": "catalog_products.source_id (simulation of sync.productid ranges)",
            "caps": results,
        }
    finally:
        connection.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("--caps", nargs="+", type=int, default=[24_999, 4_999])
    parser.add_argument("--record-type")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = simulate(args.database, caps=args.caps, record_type=args.record_type)
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
