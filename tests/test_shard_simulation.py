from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from scripts.simulate_shopify_shards import IdBucket, SimulationError, build_shards, simulate


def create_database(path: Path, rows: list[tuple[str, str, str]]) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE catalog_products (
          product_gid TEXT PRIMARY KEY,
          source_id TEXT,
          game TEXT,
          status TEXT,
          published_online_store INTEGER
        )
        """
    )
    connection.executemany(
        "INSERT INTO catalog_products VALUES (?, ?, ?, 'ACTIVE', 1)",
        rows,
    )
    connection.commit()
    connection.close()


def test_build_shards_preserves_duplicate_source_id_bucket() -> None:
    buckets = [
        IdBucket(10, ("a", "b")),
        IdBucket(11, ("c",)),
        IdBucket(12, ("d", "e")),
    ]
    shards = build_shards(buckets, cap=3)
    assert [(item.minimum_source_id, item.maximum_source_id) for item in shards] == [
        (10, 11),
        (12, 12),
    ]
    assert [item.product_count for item in shards] == [3, 2]


def test_simulation_accounts_for_every_active_published_product(tmp_path: Path) -> None:
    database = tmp_path / "catalog.sqlite3"
    create_database(
        database,
        [
            ("gid-1", "1", "Magic"),
            ("gid-2", "2", "Magic"),
            ("gid-3", "3", "Magic"),
            ("gid-4", "8", "Pokemon"),
        ],
    )
    report = simulate(database, caps=[2])
    assert report["recordTypeColumnPresent"] is False
    assert report["caps"]["2"]["totalProducts"] == 4
    assert report["caps"]["2"]["totalShards"] == 3
    assert report["caps"]["2"]["games"]["Magic"]["shardCount"] == 2


def test_nonnumeric_source_id_fails_closed(tmp_path: Path) -> None:
    database = tmp_path / "catalog.sqlite3"
    create_database(database, [("gid-1", "not-numeric", "Magic")])
    with pytest.raises(SimulationError, match="nonnumeric"):
        simulate(database, caps=[24_999])


def test_bucket_larger_than_cap_fails_closed() -> None:
    with pytest.raises(SimulationError, match="above cap"):
        build_shards([IdBucket(42, ("a", "b", "c"))], cap=2)
