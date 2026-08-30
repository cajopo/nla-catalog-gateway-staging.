from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.normalization import infer_game, normalize_text, parse_product_title

LANGUAGE_KEYS = {
    "english": "English", "italian": "Italian", "french": "French", "german": "German",
    "spanish": "Spanish", "portuguese": "Portuguese", "japanese": "Japanese",
    "korean": "Korean", "chinese": "Chinese", "russian": "Russian",
}
CONDITION_KEYS = {
    "mint": "Mint", "near mint": "Near Mint", "lightly played": "Lightly Played",
    "moderately played": "Moderately Played", "heavily played": "Heavily Played",
    "poor": "Poor", "damaged": "Damaged",
}
FINISH_KEYS = {
    "normal": "Normal", "non-foil": "Normal", "foil": "Foil", "etched": "Etched",
    "reverse": "Reverse", "reverse holo": "Reverse Holo", "holo": "Holo",
}


@dataclass(frozen=True, slots=True)
class BuildResult:
    database_path: str
    product_count: int
    source_sha256: str
    database_sha256: str
    database_bytes: int
    dataset_version: str
    elapsed_seconds: float


def _value(obj: Any) -> str | None:
    if isinstance(obj, dict):
        value = obj.get("value")
        return str(value) if value is not None else None
    return str(obj) if obj is not None else None


def _first_tag(tags: list[str], mapping: dict[str, str]) -> str | None:
    for tag in tags:
        key = normalize_text(tag)
        if key in mapping:
            return mapping[key]
    return None


def _image_url(featured_media: Any) -> str | None:
    if not isinstance(featured_media, dict):
        return None
    image = (featured_media.get("preview") or {}).get("image") or {}
    return str(image["url"]) if image.get("url") else None


def _numeric_gid(gid: str) -> str:
    return gid.rsplit("/", 1)[-1]


def _price_to_cents(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        cents = int(round(float(str(value)) * 100))
    except (TypeError, ValueError):
        return None
    return cents if cents > 0 else None


def _variant_options(selected_options: Any) -> tuple[str | None, str | None, str | None]:
    language = condition = finish = None
    if not isinstance(selected_options, list):
        return language, condition, finish
    for option in selected_options:
        if not isinstance(option, dict):
            continue
        name = normalize_text(str(option.get("name", "")))
        value = str(option.get("value", "")).strip() or None
        if not value:
            continue
        if name == "language":
            language = value
        elif name == "condition":
            condition = value
        elif name in {"edition", "finish", "printing"}:
            finish = value
    return language, condition, finish


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        PRAGMA journal_mode=OFF;
        PRAGMA synchronous=OFF;
        PRAGMA temp_store=MEMORY;
        PRAGMA foreign_keys=ON;
        DROP TABLE IF EXISTS metadata;
        DROP TABLE IF EXISTS products;
        CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID;
        CREATE TABLE products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shopify_product_gid TEXT NOT NULL UNIQUE,
            shopify_product_id TEXT NOT NULL,
            powertools_product_id TEXT,
            handle TEXT NOT NULL UNIQUE,
            game TEXT NOT NULL,
            canonical_name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            set_name TEXT,
            set_code TEXT,
            collector_number TEXT,
            rarity TEXT,
            language TEXT,
            condition TEXT,
            finish TEXT,
            image_url TEXT,
            available INTEGER NOT NULL DEFAULT 0 CHECK (available IN (0, 1)),
            inventory INTEGER NOT NULL DEFAULT 0,
            price_cents INTEGER,
            currency TEXT NOT NULL DEFAULT 'EUR',
            updated_at TEXT,
            catalog_only INTEGER NOT NULL DEFAULT 0 CHECK (catalog_only IN (0, 1)),
            source_title TEXT NOT NULL,
            product_type TEXT NOT NULL
        );
        """
    )


def _finalize_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE INDEX idx_products_game_name_id ON products(game, normalized_name, id);
        CREATE INDEX idx_products_game_available_name ON products(game, available, normalized_name, id);
        CREATE INDEX idx_products_game_set ON products(game, set_name COLLATE NOCASE);
        CREATE INDEX idx_products_game_language ON products(game, language COLLATE NOCASE);
        CREATE INDEX idx_products_powertools ON products(powertools_product_id);
        ANALYZE;
        PRAGMA optimize;
        """
    )


def build_catalog(
    snapshot_path: Path,
    database_path: Path,
    expected_count: int | None = None,
    dataset_version: str | None = None,
) -> BuildResult:
    started = time.monotonic()
    snapshot_path = snapshot_path.resolve()
    database_path = database_path.resolve()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = database_path.with_suffix(database_path.suffix + ".building")
    temp_path.unlink(missing_ok=True)
    version = dataset_version or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    source_hash = hashlib.sha256()
    root_count = variant_count = ignored_count = 0

    connection = sqlite3.connect(temp_path, timeout=60.0)
    try:
        _create_schema(connection)
        insert_sql = """
            INSERT INTO products (
                shopify_product_gid, shopify_product_id, powertools_product_id,
                handle, game, canonical_name, normalized_name, set_name,
                set_code, collector_number, rarity, language, condition, finish,
                image_url, available, inventory, price_cents, updated_at,
                catalog_only, source_title, product_type
            ) VALUES (
                :shopify_product_gid, :shopify_product_id, :powertools_product_id,
                :handle, :game, :canonical_name, :normalized_name, :set_name,
                :set_code, :collector_number, :rarity, :language, :condition, :finish,
                :image_url, :available, :inventory, :price_cents, :updated_at,
                :catalog_only, :source_title, :product_type
            )
        """
        update_variant_sql = """
            UPDATE products SET
                available = MAX(available, :available),
                inventory = MAX(inventory, :inventory),
                price_cents = CASE
                    WHEN :price_cents IS NULL THEN price_cents
                    WHEN price_cents IS NULL THEN :price_cents
                    ELSE MIN(price_cents, :price_cents)
                END,
                language = COALESCE(language, :language),
                condition = COALESCE(condition, :condition),
                finish = COALESCE(finish, :finish)
            WHERE shopify_product_gid = :parent_gid
        """

        with snapshot_path.open("rb") as source:
            for raw_line in source:
                source_hash.update(raw_line)
                if not raw_line.strip():
                    continue
                record = json.loads(raw_line)
                gid = str(record.get("id", ""))
                if gid.startswith("gid://shopify/Product/") and "__parentId" not in record:
                    title = str(record.get("title", "")).strip()
                    product_type = str(record.get("productType", "")).strip()
                    tags = [str(tag) for tag in (record.get("tags") or [])]
                    game = infer_game(product_type, tags)
                    handle = str(record.get("handle", "")).strip()
                    if not game or not title or not handle:
                        ignored_count += 1
                        continue
                    parsed = parse_product_title(title, tags)
                    inventory = max(0, int(record.get("totalInventory") or 0))
                    connection.execute(
                        insert_sql,
                        {
                            "shopify_product_gid": gid,
                            "shopify_product_id": _numeric_gid(gid),
                            "powertools_product_id": _value(record.get("powertoolsId")) or _value(record.get("syncProductId")),
                            "handle": handle,
                            "game": game,
                            "canonical_name": parsed.canonical_name,
                            "normalized_name": normalize_text(parsed.canonical_name),
                            "set_name": parsed.set_name,
                            "set_code": parsed.set_code,
                            "collector_number": parsed.collector_number,
                            "rarity": parsed.rarity,
                            "language": _first_tag(tags, LANGUAGE_KEYS),
                            "condition": _first_tag(tags, CONDITION_KEYS),
                            "finish": _first_tag(tags, FINISH_KEYS),
                            "image_url": _image_url(record.get("featuredMedia")),
                            "available": 1 if inventory > 0 else 0,
                            "inventory": inventory,
                            "price_cents": None,
                            "updated_at": record.get("updatedAt"),
                            "catalog_only": 1 if "nla_catalog_only" in tags else 0,
                            "source_title": title,
                            "product_type": product_type,
                        },
                    )
                    root_count += 1
                elif gid.startswith("gid://shopify/ProductVariant/"):
                    parent_gid = str(record.get("__parentId", ""))
                    if not parent_gid:
                        continue
                    language, condition, finish = _variant_options(record.get("selectedOptions"))
                    inventory = max(0, int(record.get("inventoryQuantity") or 0))
                    available = bool(record.get("availableForSale")) or inventory > 0
                    connection.execute(
                        update_variant_sql,
                        {
                            "available": 1 if available else 0,
                            "inventory": inventory,
                            "price_cents": _price_to_cents(record.get("price")),
                            "language": language,
                            "condition": condition,
                            "finish": finish,
                            "parent_gid": parent_gid,
                        },
                    )
                    variant_count += 1
                if (root_count + variant_count) % 10000 == 0:
                    connection.commit()

        connection.commit()
        actual_count = connection.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        if expected_count is not None and actual_count != expected_count:
            raise RuntimeError(f"Product count mismatch: {actual_count} != {expected_count}")
        _finalize_schema(connection)
        metadata = {
            "dataset_version": version,
            "product_count": str(actual_count),
            "variant_count": str(variant_count),
            "ignored_count": str(ignored_count),
            "source_sha256": source_hash.hexdigest(),
            "source_file": snapshot_path.name,
            "built_at": datetime.now(UTC).isoformat(),
            "schema_version": "1",
        }
        connection.executemany("INSERT INTO metadata(key, value) VALUES (?, ?)", metadata.items())
        connection.commit()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"SQLite integrity check failed: {integrity}")
    finally:
        connection.close()

    os.replace(temp_path, database_path)
    database_hash = hashlib.sha256()
    with database_path.open("rb") as database_file:
        for chunk in iter(lambda: database_file.read(1024 * 1024), b""):
            database_hash.update(chunk)
    return BuildResult(
        database_path=str(database_path),
        product_count=actual_count,
        source_sha256=source_hash.hexdigest(),
        database_sha256=database_hash.hexdigest(),
        database_bytes=database_path.stat().st_size,
        dataset_version=version,
        elapsed_seconds=round(time.monotonic() - started, 3),
    )
