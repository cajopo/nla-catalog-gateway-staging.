"""Fail-closed ingestion for a Shopify Admin Bulk source snapshot.

This module does not call Shopify.  It validates an already-downloaded JSONL
file, stages every accepted row in SQLite, reconciles the complete source, and
publishes an immutable candidate directory only after all checks pass.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO

MANIFEST_SCHEMA_VERSION = 2
MAX_JSONL_LINE_BYTES = 2 * 1024 * 1024
MAX_EVIDENCE_BYTES = 64 * 1024
MONEY_PATTERN = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
COMMIT_SHA_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
API_VERSION_PATTERN = re.compile(r"[0-9]{4}-(?:01|04|07|10)\Z")
RFC3339_PATTERN = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})\Z"
)
POSITIVE_DECIMAL_PATTERN = re.compile(r"[1-9][0-9]*\Z")
SHOP_DOMAIN_PATTERN = re.compile(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+myshopify\.com\Z")
ALLOWED_TYPES = (
    "InventoryLevel",
    "Metafield",
    "Product",
    "ProductVariant",
    "ResourcePublicationV2",
)
CATALOG_TYPES = ("AppCatalog", "CompanyLocationCatalog", "MarketCatalog")
MEDIA_CONTENT_TYPES = {
    "ExternalVideo": "EXTERNAL_VIDEO",
    "MediaImage": "IMAGE",
    "Model3d": "MODEL_3D",
    "Video": "VIDEO",
}
MEDIA_STATUSES = ("FAILED", "PROCESSING", "READY", "UPLOADED")
PRODUCT_STATUSES = ("ACTIVE", "ARCHIVED", "DRAFT", "UNLISTED")
QUANTITY_NAMES = ("available", "committed", "incoming", "on_hand", "reserved")
UTF_BOMS = (
    bytes.fromhex("efbbbf"),
    bytes.fromhex("fffe"),
    bytes.fromhex("feff"),
    bytes.fromhex("0000feff"),
    bytes.fromhex("fffe0000"),
)


class BulkContractError(ValueError):
    """Raised when source evidence or JSONL violates the ingestion contract."""


class _StrictJsonError(ValueError):
    """Internal error used to reject ambiguous JSON constructs."""


@dataclass(frozen=True, slots=True)
class SourceSnapshotEvidence:
    """Sanitized terminal metadata bound to one downloaded source snapshot."""

    shop_domain: str
    api_version: str
    operation_id: str
    status: str
    partial_data_url_present: bool
    file_size: int
    object_count: int
    product_count: int
    expected_active_online_store_published_product_count: int
    query_sha256: str
    online_store_publication_gid: str
    completed_at: str
    source_code_sha: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> SourceSnapshotEvidence:
        keys = {
            "apiVersion",
            "completedAt",
            "expectedActiveOnlineStorePublishedProductCount",
            "fileSize",
            "objectCount",
            "onlineStorePublicationGid",
            "operationId",
            "partialDataUrlPresent",
            "productCount",
            "querySha256",
            "shopDomain",
            "sourceCodeSha",
            "status",
        }
        _exact_keys(payload, keys, "source evidence")
        evidence = cls(
            shop_domain=_text(payload, "shopDomain", "source evidence"),
            api_version=_text(payload, "apiVersion", "source evidence"),
            operation_id=_gid_value(
                payload.get("operationId"), "BulkOperation", "source evidence.operationId"
            ),
            status=_text(payload, "status", "source evidence"),
            partial_data_url_present=_boolean(payload, "partialDataUrlPresent", "source evidence"),
            file_size=_positive_integer(payload, "fileSize", "source evidence"),
            object_count=_positive_integer(payload, "objectCount", "source evidence"),
            product_count=_positive_integer(payload, "productCount", "source evidence"),
            expected_active_online_store_published_product_count=_nonnegative_integer(
                payload,
                "expectedActiveOnlineStorePublishedProductCount",
                "source evidence",
            ),
            query_sha256=_text(payload, "querySha256", "source evidence"),
            online_store_publication_gid=_gid_value(
                payload.get("onlineStorePublicationGid"),
                "Publication",
                "source evidence.onlineStorePublicationGid",
            ),
            completed_at=_timestamp(payload, "completedAt", "source evidence"),
            source_code_sha=_text(payload, "sourceCodeSha", "source evidence"),
        )
        evidence.validate()
        return evidence

    def validate(self) -> None:
        """Validate terminal state and reproducibility identifiers."""
        if not isinstance(self.shop_domain, str) or not SHOP_DOMAIN_PATTERN.fullmatch(
            self.shop_domain
        ):
            raise BulkContractError("source evidence: invalid shopDomain")
        if not isinstance(self.api_version, str) or not API_VERSION_PATTERN.fullmatch(
            self.api_version
        ):
            raise BulkContractError("source evidence: invalid stable apiVersion")
        _gid_value(self.operation_id, "BulkOperation", "source evidence.operationId")
        _gid_value(
            self.online_store_publication_gid,
            "Publication",
            "source evidence.onlineStorePublicationGid",
        )
        if self.status != "COMPLETED":
            raise BulkContractError("source evidence: status must be COMPLETED")
        if type(self.partial_data_url_present) is not bool:
            raise BulkContractError("source evidence: partialDataUrlPresent must be boolean")
        if self.partial_data_url_present:
            raise BulkContractError("source evidence: partial data is not acceptable")
        for name, value in (
            ("fileSize", self.file_size),
            ("objectCount", self.object_count),
            ("productCount", self.product_count),
        ):
            if type(value) is not int or not 1 <= value < 2**63:
                raise BulkContractError(f"source evidence: {name} must be positive")
        if (
            type(self.expected_active_online_store_published_product_count) is not int
            or not 0 <= self.expected_active_online_store_published_product_count < 2**63
        ):
            raise BulkContractError(
                "source evidence: expected active Online Store published Product count "
                "must be a non-negative signed 64-bit integer"
            )
        if self.expected_active_online_store_published_product_count > self.product_count:
            raise BulkContractError(
                "source evidence: expected active Online Store published Product count "
                "cannot exceed productCount"
            )
        if not isinstance(self.query_sha256, str) or not SHA256_PATTERN.fullmatch(
            self.query_sha256
        ):
            raise BulkContractError("source evidence: invalid querySha256")
        _timestamp({"completedAt": self.completed_at}, "completedAt", "source evidence")
        if not isinstance(self.source_code_sha, str) or not COMMIT_SHA_PATTERN.fullmatch(
            self.source_code_sha
        ):
            raise BulkContractError("source evidence: invalid sourceCodeSha")

    def as_dict(self) -> dict[str, Any]:
        return {
            "apiVersion": self.api_version,
            "completedAt": self.completed_at,
            "expectedActiveOnlineStorePublishedProductCount": (
                self.expected_active_online_store_published_product_count
            ),
            "fileSize": self.file_size,
            "objectCount": self.object_count,
            "onlineStorePublicationGid": self.online_store_publication_gid,
            "operationId": self.operation_id,
            "partialDataUrlPresent": self.partial_data_url_present,
            "productCount": self.product_count,
            "querySha256": self.query_sha256,
            "shopDomain": self.shop_domain,
            "sourceCodeSha": self.source_code_sha,
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class SourceSnapshotManifest:
    """Deterministic evidence for one fully reconciled source candidate."""

    schema_version: int
    source: SourceSnapshotEvidence
    snapshot_sha256: str
    database_sha256: str
    snapshot_bytes: int
    line_count: int
    object_counts: tuple[tuple[str, int], ...]
    product_status_counts: tuple[tuple[str, int], ...]
    verified_active_online_store_published_product_count: int
    source_identity_products: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "databaseSha256": self.database_sha256,
            "lineCount": self.line_count,
            "objectCounts": dict(self.object_counts),
            "productStatusCounts": dict(self.product_status_counts),
            "schemaVersion": self.schema_version,
            "snapshotBytes": self.snapshot_bytes,
            "snapshotSha256": self.snapshot_sha256,
            "source": self.source.as_dict(),
            "sourceIdentityProducts": self.source_identity_products,
            "verifiedActiveOnlineStorePublishedProductCount": (
                self.verified_active_online_store_published_product_count
            ),
        }


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _StrictJsonError("duplicate JSON key")
        result[key] = value
    return result


def _reject_float(value: str) -> None:
    del value
    raise _StrictJsonError("JSON floating-point number is forbidden")


def _reject_constant(value: str) -> None:
    del value
    raise _StrictJsonError("non-finite JSON number is forbidden")


def _strict_json(raw: bytes, context: str) -> Any:
    if any(raw.startswith(marker) for marker in UTF_BOMS):
        raise BulkContractError(f"{context}: Unicode BOM is forbidden")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise BulkContractError(f"{context}: invalid UTF-8") from exc
    try:
        payload = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_float=_reject_float,
            parse_constant=_reject_constant,
        )
    except _StrictJsonError as exc:
        raise BulkContractError(f"{context}: invalid JSON: {exc}") from exc
    except (json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise BulkContractError(f"{context}: invalid JSON") from exc
    pending = [payload]
    while pending:
        value = pending.pop()
        if isinstance(value, str):
            if _contains_surrogate(value):
                raise BulkContractError(f"{context}: Unicode surrogate is forbidden")
        elif isinstance(value, dict):
            pending.extend(value.keys())
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
    return payload


def load_source_evidence(path: Path) -> SourceSnapshotEvidence:
    """Load a small sanitized evidence document with strict JSON semantics."""
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_EVIDENCE_BYTES + 1)
    except OSError as exc:
        raise BulkContractError("cannot read source evidence") from exc
    if not raw or len(raw) > MAX_EVIDENCE_BYTES:
        raise BulkContractError("source evidence must be between 1 byte and 64 KiB")
    payload = _strict_json(raw, "source evidence")
    if not isinstance(payload, dict):
        raise BulkContractError("source evidence: root must be an object")
    return SourceSnapshotEvidence.from_dict(payload)


def _exact_keys(
    payload: dict[str, Any],
    required: set[str],
    context: str,
    optional: set[str] | None = None,
) -> None:
    optional = optional or set()
    missing = required - payload.keys()
    unexpected = payload.keys() - required - optional
    if missing:
        raise BulkContractError(f"{context}: missing required fields")
    if unexpected:
        raise BulkContractError(f"{context}: unexpected fields")


def _contains_surrogate(value: str) -> bool:
    return any(0xD800 <= ord(character) <= 0xDFFF for character in value)


def _text(payload: dict[str, Any], key: str, context: str, *, empty: bool = False) -> str:
    value = payload.get(key)
    if (
        not isinstance(value, str)
        or _contains_surrogate(value)
        or (not empty and not value.strip())
    ):
        qualifier = "text" if empty else "non-empty text"
        raise BulkContractError(f"{context}: {key} must be {qualifier}")
    return value


def _optional_text(payload: dict[str, Any], key: str, context: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or _contains_surrogate(value):
        raise BulkContractError(f"{context}: {key} must be text or null")
    return value


def _integer(payload: dict[str, Any], key: str, context: str) -> int:
    value = payload.get(key)
    if type(value) is not int or not -(2**63) <= value < 2**63:
        raise BulkContractError(f"{context}: {key} must be a signed 64-bit integer")
    return value


def _positive_integer(payload: dict[str, Any], key: str, context: str) -> int:
    value = _integer(payload, key, context)
    if value < 1:
        raise BulkContractError(f"{context}: {key} must be positive")
    return value


def _optional_positive_integer(payload: dict[str, Any], key: str, context: str) -> int | None:
    if payload.get(key) is None:
        return None
    return _positive_integer(payload, key, context)


def _nonnegative_integer(payload: dict[str, Any], key: str, context: str) -> int:
    value = _integer(payload, key, context)
    if value < 0:
        raise BulkContractError(f"{context}: {key} must be non-negative")
    return value


def _boolean(payload: dict[str, Any], key: str, context: str) -> bool:
    value = payload.get(key)
    if type(value) is not bool:
        raise BulkContractError(f"{context}: {key} must be boolean")
    return value


def _timestamp(payload: dict[str, Any], key: str, context: str) -> str:
    value = _text(payload, key, context)
    if not RFC3339_PATTERN.fullmatch(value):
        raise BulkContractError(f"{context}: {key} must be a timezone-aware RFC3339 timestamp")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BulkContractError(
            f"{context}: {key} must be a valid RFC3339 calendar timestamp"
        ) from exc
    return value


def _optional_timestamp(payload: dict[str, Any], key: str, context: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    return _timestamp(payload, key, context)


def _gid_parts(value: Any, expected_kind: str, context: str) -> tuple[str, str]:
    if not isinstance(value, str) or value != value.strip():
        raise BulkContractError(f"{context}: invalid {expected_kind} GID; canonical form required")
    prefix = f"gid://shopify/{expected_kind}/"
    if not value.startswith(prefix):
        raise BulkContractError(f"{context}: invalid {expected_kind} GID; canonical form required")
    component = value[len(prefix) :]
    if not POSITIVE_DECIMAL_PATTERN.fullmatch(component):
        raise BulkContractError(f"{context}: invalid {expected_kind} GID; canonical form required")
    return value, component


def _gid_value(value: Any, expected_kind: str, context: str) -> str:
    return _gid_parts(value, expected_kind, context)[0]


def _catalog_gid(value: Any, catalog_type: str, context: str) -> str:
    if catalog_type not in CATALOG_TYPES:
        raise BulkContractError(f"{context}: unsupported catalog type")
    return _gid_value(value, catalog_type, context)


def _inventory_level_gid(
    value: Any,
    *,
    inventory_item_gid: str,
    context: str,
) -> str:
    if not isinstance(value, str) or value != value.strip():
        raise BulkContractError(f"{context}: invalid InventoryLevel GID; canonical form required")
    _item, item_id = _gid_parts(inventory_item_gid, "InventoryItem", context)
    prefix = "gid://shopify/InventoryLevel/"
    if not value.startswith(prefix):
        raise BulkContractError(f"{context}: invalid InventoryLevel GID; canonical form required")
    component, separator, supplied_item_id = value[len(prefix) :].partition("?inventory_item_id=")
    if (
        separator != "?inventory_item_id="
        or not POSITIVE_DECIMAL_PATTERN.fullmatch(component)
        or not POSITIVE_DECIMAL_PATTERN.fullmatch(supplied_item_id)
        or value != f"{prefix}{component}?inventory_item_id={supplied_item_id}"
    ):
        raise BulkContractError(f"{context}: invalid InventoryLevel GID; canonical form required")
    if supplied_item_id != item_id:
        raise BulkContractError(
            f"{context}: invalid InventoryLevel GID; does not match inventory item"
        )
    return value


def _gid(payload: dict[str, Any], key: str, expected_kind: str, context: str) -> str:
    return _gid_value(payload.get(key), expected_kind, f"{context}.{key}")


def _owner_gid(payload: dict[str, Any], key: str, context: str) -> str:
    value = payload.get(key)
    for kind in ("Product", "ProductVariant"):
        try:
            return _gid_value(value, kind, f"{context}.{key}")
        except BulkContractError:
            continue
    raise BulkContractError(f"{context}.{key}: unsupported owner GID")


def _money(
    payload: dict[str, Any], key: str, context: str, *, optional: bool = False
) -> str | None:
    value = payload.get(key)
    if optional and value is None:
        return None
    if not isinstance(value, str) or not MONEY_PATTERN.fullmatch(value):
        raise BulkContractError(f"{context}: {key} must be decimal price text")
    return value


def _source_metafield(value: Any, context: str, *, expected_type: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise BulkContractError(f"{context}: source metafield must be an object or null")
    _exact_keys(value, {"type", "value"}, context)
    if _text(value, "type", context) != expected_type:
        raise BulkContractError(f"{context}: source metafield type does not match its contract")
    source_id = _text(value, "value", context)
    if not POSITIVE_DECIMAL_PATTERN.fullmatch(source_id):
        raise BulkContractError(
            f"{context}: source metafield value must be canonical positive decimal digits"
        )
    return source_id


def _tags(payload: dict[str, Any], context: str) -> str:
    tags = payload.get("tags")
    if not isinstance(tags, list) or any(
        not isinstance(tag, str) or _contains_surrogate(tag) or not tag.strip() for tag in tags
    ):
        raise BulkContractError(f"{context}: tags must be a list of non-empty text")
    return json.dumps(tags, ensure_ascii=False, separators=(",", ":"))


def _selected_options(payload: dict[str, Any], context: str) -> str:
    options = payload.get("selectedOptions")
    if not isinstance(options, list):
        raise BulkContractError(f"{context}: selectedOptions must be a list")
    for index, option in enumerate(options):
        option_context = f"{context}.selectedOptions[{index}]"
        if not isinstance(option, dict):
            raise BulkContractError(f"{option_context}: selected option must be an object")
        _exact_keys(option, {"name", "value"}, option_context)
        _text(option, "name", option_context)
        _text(option, "value", option_context)
    return json.dumps(options, ensure_ascii=False, separators=(",", ":"))


def _image_fields(
    value: Any, context: str
) -> tuple[str | None, str | None, int | None, int | None]:
    if value is None:
        return (None, None, None, None)
    if not isinstance(value, dict):
        raise BulkContractError(f"{context}: image must be an object or null")
    _exact_keys(value, {"altText", "height", "url", "width"}, context)
    return (
        _text(value, "url", context),
        _optional_text(value, "altText", context),
        _optional_positive_integer(value, "width", context),
        _optional_positive_integer(value, "height", context),
    )


def _media(payload: dict[str, Any], context: str) -> tuple[Any, ...]:
    media = payload.get("featuredMedia")
    if media is None:
        return (None,) * 15
    if not isinstance(media, dict):
        raise BulkContractError(f"{context}: featuredMedia must be an object or null")
    media_context = f"{context}.featuredMedia"
    media_type = _text(media, "__typename", media_context)
    if media_type not in MEDIA_CONTENT_TYPES:
        raise BulkContractError(f"{context}: unsupported featured media type")
    common_keys = {"__typename", "alt", "id", "mediaContentType", "preview", "status"}
    _exact_keys(
        media,
        common_keys | ({"image"} if media_type == "MediaImage" else set()),
        media_context,
    )
    media_id = _gid(media, "id", media_type, media_context)
    alt = _optional_text(media, "alt", media_context)
    content_type = _text(media, "mediaContentType", media_context)
    if content_type != MEDIA_CONTENT_TYPES[media_type]:
        raise BulkContractError(f"{context}: featured media content type mismatch")
    status = _text(media, "status", media_context)
    if status not in MEDIA_STATUSES:
        raise BulkContractError(f"{context}: unsupported featured media status")
    image_fields: tuple[str | None, str | None, int | None, int | None] = (
        None,
        None,
        None,
        None,
    )
    if media_type == "MediaImage":
        image_fields = _image_fields(media.get("image"), f"{context}.featuredMedia.image")
    preview = media.get("preview")
    preview_status: str | None = None
    preview_image_fields: tuple[str | None, str | None, int | None, int | None] = (
        None,
        None,
        None,
        None,
    )
    if preview is not None:
        preview_context = f"{context}.featuredMedia.preview"
        if not isinstance(preview, dict):
            raise BulkContractError(f"{preview_context}: preview must be an object or null")
        _exact_keys(preview, {"image", "status"}, preview_context)
        preview_status = _text(preview, "status", preview_context)
        if preview_status not in MEDIA_STATUSES:
            raise BulkContractError(f"{context}: unsupported featured media preview status")
        preview_image_fields = _image_fields(
            preview.get("image"), f"{context}.featuredMedia.preview.image"
        )
    raw = json.dumps(media, ensure_ascii=False, separators=(",", ":"))
    return (
        media_type,
        media_id,
        alt,
        content_type,
        status,
        *image_fields,
        preview_status,
        *preview_image_fields,
        raw,
    )


SCHEMA = """
PRAGMA foreign_keys = OFF;
PRAGMA temp_store = FILE;
PRAGMA cache_size = -8192;
PRAGMA journal_mode = DELETE;
PRAGMA synchronous = FULL;

CREATE TABLE source_records (
    line_number INTEGER PRIMARY KEY,
    typename TEXT NOT NULL,
    raw_json BLOB NOT NULL
);

CREATE TABLE products (
    gid TEXT PRIMARY KEY,
    handle TEXT NOT NULL UNIQUE,
    commercial_title TEXT NOT NULL,
    status TEXT NOT NULL,
    vendor TEXT NOT NULL,
    product_type TEXT NOT NULL,
    tags_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    published_at TEXT,
    online_store_url TEXT,
    total_inventory INTEGER NOT NULL,
    tracks_inventory INTEGER NOT NULL,
    expected_variant_count INTEGER NOT NULL,
    sync_source_id TEXT,
    powertools_source_id TEXT,
    media_type TEXT,
    media_gid TEXT,
    media_alt TEXT,
    media_content_type TEXT,
    media_status TEXT,
    media_url TEXT,
    media_alt_text TEXT,
    media_width INTEGER,
    media_height INTEGER,
    media_preview_status TEXT,
    media_preview_url TEXT,
    media_preview_alt_text TEXT,
    media_preview_width INTEGER,
    media_preview_height INTEGER,
    media_json TEXT
);

CREATE TABLE variants (
    gid TEXT PRIMARY KEY,
    product_gid TEXT NOT NULL,
    title TEXT NOT NULL,
    sku TEXT,
    barcode TEXT,
    selected_options_json TEXT NOT NULL,
    price_text TEXT NOT NULL,
    compare_at_price_text TEXT,
    inventory_quantity INTEGER NOT NULL,
    inventory_policy TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    inventory_item_gid TEXT NOT NULL UNIQUE,
    inventory_tracked INTEGER NOT NULL
);

CREATE TABLE publications (
    product_gid TEXT NOT NULL,
    publication_gid TEXT NOT NULL,
    is_published INTEGER NOT NULL,
    publish_date TEXT,
    auto_publish INTEGER NOT NULL,
    catalog_type TEXT,
    catalog_gid TEXT,
    catalog_title TEXT,
    PRIMARY KEY (product_gid, publication_gid)
);

CREATE TABLE inventory_levels (
    gid TEXT PRIMARY KEY,
    inventory_item_gid TEXT NOT NULL,
    location_gid TEXT NOT NULL,
    location_name TEXT NOT NULL,
    quantities_json TEXT NOT NULL,
    UNIQUE (inventory_item_gid, location_gid)
);

CREATE TABLE inventory_quantities (
    inventory_level_gid TEXT NOT NULL,
    name TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    PRIMARY KEY (inventory_level_gid, name)
);

CREATE TABLE metafields (
    gid TEXT PRIMARY KEY,
    owner_gid TEXT NOT NULL,
    namespace TEXT NOT NULL,
    key TEXT NOT NULL,
    value_type TEXT NOT NULL,
    value TEXT NOT NULL,
    UNIQUE (owner_gid, namespace, key)
);
"""


def _insert_product(connection: sqlite3.Connection, row: dict[str, Any], line: int) -> None:
    context = f"line {line} Product"
    required = {
        "__typename",
        "createdAt",
        "featuredMedia",
        "handle",
        "id",
        "onlineStoreUrl",
        "powertoolsId",
        "productType",
        "publishedAt",
        "status",
        "syncProductId",
        "tags",
        "title",
        "totalInventory",
        "tracksInventory",
        "updatedAt",
        "variantsCount",
        "vendor",
    }
    _exact_keys(row, required, context)
    status = _text(row, "status", context)
    if status not in PRODUCT_STATUSES:
        raise BulkContractError(f"{context}: unsupported status")
    variants_count = row.get("variantsCount")
    if not isinstance(variants_count, dict):
        raise BulkContractError(f"{context}: variantsCount must be an object")
    _exact_keys(variants_count, {"count"}, f"{context}.variantsCount")
    expected_variants = _positive_integer(variants_count, "count", f"{context}.variantsCount")
    media = _media(row, context)
    connection.execute(
        """INSERT INTO products VALUES (
        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
        ?, ?, ?, ?, ?
        )""",
        (
            _gid(row, "id", "Product", context),
            _text(row, "handle", context),
            _text(row, "title", context),
            status,
            _text(row, "vendor", context, empty=True),
            _text(row, "productType", context, empty=True),
            _tags(row, context),
            _timestamp(row, "createdAt", context),
            _timestamp(row, "updatedAt", context),
            _optional_timestamp(row, "publishedAt", context),
            _optional_text(row, "onlineStoreUrl", context),
            _integer(row, "totalInventory", context),
            int(_boolean(row, "tracksInventory", context)),
            expected_variants,
            _source_metafield(
                row.get("syncProductId"),
                f"{context}.syncProductId",
                expected_type="number_integer",
            ),
            _source_metafield(
                row.get("powertoolsId"),
                f"{context}.powertoolsId",
                expected_type="single_line_text_field",
            ),
            *media,
        ),
    )


def _insert_variant(connection: sqlite3.Connection, row: dict[str, Any], line: int) -> None:
    context = f"line {line} ProductVariant"
    required = {
        "__parentId",
        "__typename",
        "barcode",
        "compareAtPrice",
        "id",
        "inventoryItem",
        "inventoryPolicy",
        "inventoryQuantity",
        "price",
        "selectedOptions",
        "sku",
        "title",
        "updatedAt",
    }
    _exact_keys(row, required, context)
    policy = _text(row, "inventoryPolicy", context)
    if policy not in {"CONTINUE", "DENY"}:
        raise BulkContractError(f"{context}: unsupported inventoryPolicy")
    item = row.get("inventoryItem")
    if not isinstance(item, dict):
        raise BulkContractError(f"{context}: inventoryItem must be an object")
    _exact_keys(item, {"__typename", "id", "tracked"}, f"{context}.inventoryItem")
    if _text(item, "__typename", f"{context}.inventoryItem") != "InventoryItem":
        raise BulkContractError(f"{context}: invalid inventoryItem type")
    connection.execute(
        "INSERT INTO variants VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            _gid(row, "id", "ProductVariant", context),
            _gid(row, "__parentId", "Product", context),
            _text(row, "title", context),
            _optional_text(row, "sku", context),
            _optional_text(row, "barcode", context),
            _selected_options(row, context),
            _money(row, "price", context),
            _money(row, "compareAtPrice", context, optional=True),
            _integer(row, "inventoryQuantity", context),
            policy,
            _timestamp(row, "updatedAt", context),
            _gid(item, "id", "InventoryItem", f"{context}.inventoryItem"),
            int(_boolean(item, "tracked", f"{context}.inventoryItem")),
        ),
    )


def _insert_publication(connection: sqlite3.Connection, row: dict[str, Any], line: int) -> None:
    context = f"line {line} ResourcePublicationV2"
    _exact_keys(
        row,
        {"__parentId", "__typename", "isPublished", "publication", "publishDate"},
        context,
    )
    publication = row.get("publication")
    if not isinstance(publication, dict):
        raise BulkContractError(f"{context}: publication must be an object")
    _exact_keys(publication, {"autoPublish", "catalog", "id"}, f"{context}.publication")
    catalog = publication.get("catalog")
    catalog_type: str | None = None
    catalog_gid: str | None = None
    catalog_title: str | None = None
    if catalog is not None:
        if not isinstance(catalog, dict):
            raise BulkContractError(f"{context}: catalog must be an object or null")
        _exact_keys(catalog, {"__typename", "id", "title"}, f"{context}.catalog")
        catalog_type = _text(catalog, "__typename", f"{context}.catalog")
        catalog_gid = _catalog_gid(catalog.get("id"), catalog_type, f"{context}.catalog.id")
        catalog_title = _text(catalog, "title", f"{context}.catalog")
    connection.execute(
        "INSERT INTO publications VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            _gid(row, "__parentId", "Product", context),
            _gid(publication, "id", "Publication", f"{context}.publication"),
            int(_boolean(row, "isPublished", context)),
            _optional_timestamp(row, "publishDate", context),
            int(_boolean(publication, "autoPublish", f"{context}.publication")),
            catalog_type,
            catalog_gid,
            catalog_title,
        ),
    )


def _insert_inventory_level(connection: sqlite3.Connection, row: dict[str, Any], line: int) -> None:
    context = f"line {line} InventoryLevel"
    _exact_keys(row, {"__parentId", "__typename", "id", "location", "quantities"}, context)
    location = row.get("location")
    if not isinstance(location, dict):
        raise BulkContractError(f"{context}: location must be an object")
    _exact_keys(location, {"id", "name"}, f"{context}.location")
    quantities = row.get("quantities")
    if not isinstance(quantities, list):
        raise BulkContractError(f"{context}: quantities must be a list")
    normalized: dict[str, int] = {}
    for index, item in enumerate(quantities):
        item_context = f"{context}.quantities[{index}]"
        if not isinstance(item, dict):
            raise BulkContractError(f"{item_context}: quantity must be an object")
        _exact_keys(item, {"name", "quantity"}, item_context)
        name = _text(item, "name", item_context)
        if name in normalized:
            raise BulkContractError(f"{context}: duplicate inventory quantity name")
        normalized[name] = _integer(item, "quantity", item_context)
    if set(normalized) != set(QUANTITY_NAMES):
        raise BulkContractError(f"{context}: inventory quantity names do not match contract")
    inventory_item_gid = _gid(row, "__parentId", "InventoryItem", context)
    location_gid = _gid(location, "id", "Location", f"{context}.location")
    level_gid = _inventory_level_gid(
        row.get("id"),
        inventory_item_gid=inventory_item_gid,
        context=f"{context}.id",
    )
    connection.execute(
        "INSERT INTO inventory_levels VALUES (?, ?, ?, ?, ?)",
        (
            level_gid,
            inventory_item_gid,
            location_gid,
            _text(location, "name", f"{context}.location"),
            json.dumps(quantities, ensure_ascii=False, separators=(",", ":")),
        ),
    )
    connection.executemany(
        "INSERT INTO inventory_quantities VALUES (?, ?, ?)",
        ((level_gid, name, normalized[name]) for name in QUANTITY_NAMES),
    )


def _insert_metafield(connection: sqlite3.Connection, row: dict[str, Any], line: int) -> None:
    context = f"line {line} Metafield"
    _exact_keys(
        row,
        {"__parentId", "__typename", "id", "key", "namespace", "type", "value"},
        context,
    )
    namespace = _text(row, "namespace", context)
    if namespace != "nla":
        raise BulkContractError(f"{context}: metafield namespace must be nla")
    connection.execute(
        "INSERT INTO metafields VALUES (?, ?, ?, ?, ?, ?)",
        (
            _gid(row, "id", "Metafield", context),
            _owner_gid(row, "__parentId", context),
            namespace,
            _text(row, "key", context),
            _text(row, "type", context),
            _text(row, "value", context, empty=True),
        ),
    )


def _insert_record(
    connection: sqlite3.Connection,
    row: dict[str, Any],
    line: int,
    raw: bytes,
) -> str:
    type_name = row.get("__typename")
    if type_name not in ALLOWED_TYPES:
        raise BulkContractError(f"line {line}: unsupported __typename")
    connection.execute("INSERT INTO source_records VALUES (?, ?, ?)", (line, type_name, raw))
    try:
        if type_name == "Product":
            _insert_product(connection, row, line)
        elif type_name == "ProductVariant":
            _insert_variant(connection, row, line)
        elif type_name == "ResourcePublicationV2":
            _insert_publication(connection, row, line)
        elif type_name == "InventoryLevel":
            _insert_inventory_level(connection, row, line)
        else:
            _insert_metafield(connection, row, line)
    except sqlite3.IntegrityError as exc:
        raise BulkContractError(f"line {line}: duplicate or conflicting {type_name}") from exc
    return type_name


def _next_line(handle: BinaryIO) -> bytes:
    raw = handle.readline(MAX_JSONL_LINE_BYTES + 1)
    if len(raw) > MAX_JSONL_LINE_BYTES:
        raise BulkContractError("JSONL record exceeds the maximum line size")
    return raw


def _ingest(
    connection: sqlite3.Connection,
    snapshot_path: Path,
) -> tuple[str, int, int, dict[str, int]]:
    digest = hashlib.sha256()
    byte_count = 0
    line_count = 0
    counts = dict.fromkeys(ALLOWED_TYPES, 0)
    try:
        handle = snapshot_path.open("rb")
    except OSError as exc:
        raise BulkContractError("cannot read source snapshot") from exc
    with handle:
        while raw := _next_line(handle):
            line_count += 1
            byte_count += len(raw)
            digest.update(raw)
            if not raw.strip():
                raise BulkContractError(f"line {line_count}: blank JSONL record")
            payload = _strict_json(raw, f"line {line_count}")
            if not isinstance(payload, dict):
                raise BulkContractError(f"line {line_count}: record must be an object")
            type_name = _insert_record(connection, payload, line_count, raw)
            counts[type_name] += 1
    return digest.hexdigest(), byte_count, line_count, counts


def _first_value(connection: sqlite3.Connection, query: str, parameters: tuple[Any, ...] = ()):
    row = connection.execute(query, parameters).fetchone()
    return None if row is None else row[0]


def _require_no_row(
    connection: sqlite3.Connection,
    query: str,
    message: str,
    parameters: tuple[Any, ...] = (),
) -> None:
    if connection.execute(query, parameters).fetchone() is not None:
        raise BulkContractError(message)


def _reconcile(
    connection: sqlite3.Connection,
    evidence: SourceSnapshotEvidence,
    byte_count: int,
    line_count: int,
    counts: dict[str, int],
) -> tuple[int, tuple[tuple[str, int], ...], int]:
    if counts["Product"] == 0:
        raise BulkContractError("source snapshot contains no Product")
    if byte_count != evidence.file_size:
        raise BulkContractError("source snapshot fileSize does not match terminal evidence")
    if line_count != evidence.object_count:
        raise BulkContractError("source snapshot objectCount does not match terminal evidence")
    if counts["Product"] != evidence.product_count:
        raise BulkContractError("source snapshot productCount does not match independent evidence")
    if line_count != sum(counts.values()):
        raise BulkContractError("source row accounting mismatch")

    _require_no_row(
        connection,
        "SELECT 1 FROM variants v LEFT JOIN products p ON p.gid=v.product_gid "
        "WHERE p.gid IS NULL LIMIT 1",
        "orphan ProductVariant",
    )
    _require_no_row(
        connection,
        "SELECT 1 FROM publications r LEFT JOIN products p ON p.gid=r.product_gid "
        "WHERE p.gid IS NULL LIMIT 1",
        "orphan ResourcePublicationV2",
    )
    _require_no_row(
        connection,
        "SELECT 1 FROM inventory_levels l LEFT JOIN variants v "
        "ON v.inventory_item_gid=l.inventory_item_gid WHERE v.gid IS NULL LIMIT 1",
        "orphan InventoryLevel",
    )
    _require_no_row(
        connection,
        "SELECT 1 FROM metafields m LEFT JOIN products p ON p.gid=m.owner_gid "
        "LEFT JOIN variants v ON v.gid=m.owner_gid "
        "WHERE p.gid IS NULL AND v.gid IS NULL LIMIT 1",
        "orphan Metafield",
    )
    _require_no_row(
        connection,
        "SELECT 1 FROM products p LEFT JOIN variants v ON v.product_gid=p.gid "
        "GROUP BY p.gid, p.expected_variant_count "
        "HAVING COUNT(v.gid) <> p.expected_variant_count LIMIT 1",
        "Product variant connection is incomplete",
    )
    _require_no_row(
        connection,
        "SELECT 1 FROM products p LEFT JOIN publications r "
        "ON r.product_gid=p.gid AND r.publication_gid=? "
        "WHERE r.product_gid IS NULL LIMIT 1",
        "Product lacks explicit Online Store publication evidence",
        (evidence.online_store_publication_gid,),
    )
    _require_no_row(
        connection,
        "SELECT 1 FROM products WHERE "
        "(sync_source_id IS NULL) <> (powertools_source_id IS NULL) "
        "OR sync_source_id <> powertools_source_id LIMIT 1",
        "source identity is one-sided or mismatched",
    )
    _require_no_row(
        connection,
        "SELECT 1 FROM products WHERE sync_source_id IS NOT NULL "
        "GROUP BY sync_source_id HAVING COUNT(*) > 1 LIMIT 1",
        "duplicate source identity requires reconciliation",
    )
    quick_check = _first_value(connection, "PRAGMA quick_check")
    if quick_check != "ok":
        raise BulkContractError("SQLite quick_check failed")
    active_online_store_published = int(
        _first_value(
            connection,
            "SELECT COUNT(*) FROM products p JOIN publications r ON r.product_gid=p.gid "
            "WHERE p.status='ACTIVE' AND r.publication_gid=? AND r.is_published=1",
            (evidence.online_store_publication_gid,),
        )
    )
    if (
        active_online_store_published
        != evidence.expected_active_online_store_published_product_count
    ):
        raise BulkContractError(
            "active Online Store published Product count does not match independent evidence"
        )
    status_counts = tuple(
        (
            status,
            int(
                _first_value(
                    connection,
                    "SELECT COUNT(*) FROM products WHERE status=?",
                    (status,),
                )
            ),
        )
        for status in PRODUCT_STATUSES
    )
    source_identities = int(
        _first_value(connection, "SELECT COUNT(*) FROM products WHERE sync_source_id IS NOT NULL")
    )
    return active_online_store_published, status_counts, source_identities


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        handle = path.open("rb")
    except OSError as exc:
        raise BulkContractError("cannot read query or candidate database") from exc
    with handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_manifest(path: Path, manifest: SourceSnapshotManifest) -> None:
    rendered = json.dumps(manifest.as_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(rendered)
        handle.flush()
        os.fsync(handle.fileno())


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def build_source_candidate(
    snapshot_path: Path,
    *,
    query_path: Path,
    evidence: SourceSnapshotEvidence,
    expected_source_code_sha: str,
    final_directory: Path,
    repository_root: Path | None = None,
) -> SourceSnapshotManifest:
    """Build and atomically publish one validated immutable source candidate."""
    evidence.validate()
    if not isinstance(expected_source_code_sha, str) or not COMMIT_SHA_PATTERN.fullmatch(
        expected_source_code_sha
    ):
        raise BulkContractError("trusted expected source-code SHA is invalid")
    if evidence.source_code_sha != expected_source_code_sha:
        raise BulkContractError("sourceCodeSha does not match trusted expected source-code SHA")
    if repository_root is not None and _inside(final_directory, repository_root):
        raise BulkContractError("candidate output must remain outside the repository")
    if final_directory.exists():
        raise BulkContractError("final candidate directory already exists")
    if not query_path.is_file():
        raise BulkContractError("query file not found")
    query_sha256 = _file_sha256(query_path)
    if query_sha256 != evidence.query_sha256:
        raise BulkContractError("query SHA-256 does not match terminal evidence")

    final_directory.parent.mkdir(parents=True, exist_ok=True)
    candidate = Path(
        tempfile.mkdtemp(
            prefix=f".{final_directory.name}.candidate-",
            dir=final_directory.parent,
        )
    )
    published = False
    try:
        database_path = candidate / "catalog.sqlite3"
        connection = sqlite3.connect(database_path)
        try:
            connection.executescript(SCHEMA)
            snapshot_sha256, byte_count, line_count, counts = _ingest(connection, snapshot_path)
            published_products, status_counts, source_identities = _reconcile(
                connection, evidence, byte_count, line_count, counts
            )
            connection.commit()
        finally:
            connection.close()

        database_sha256 = _file_sha256(database_path)
        manifest = SourceSnapshotManifest(
            schema_version=MANIFEST_SCHEMA_VERSION,
            source=evidence,
            snapshot_sha256=snapshot_sha256,
            database_sha256=database_sha256,
            snapshot_bytes=byte_count,
            line_count=line_count,
            object_counts=tuple((name, counts[name]) for name in ALLOWED_TYPES),
            product_status_counts=status_counts,
            verified_active_online_store_published_product_count=published_products,
            source_identity_products=source_identities,
        )
        _write_manifest(candidate / "manifest.json", manifest)
        os.rename(candidate, final_directory)
        published = True
        return manifest
    finally:
        if not published and candidate.exists():
            shutil.rmtree(candidate)


__all__ = [
    "ALLOWED_TYPES",
    "BulkContractError",
    "SourceSnapshotEvidence",
    "SourceSnapshotManifest",
    "build_source_candidate",
    "load_source_evidence",
]
