"""Streaming validation and manifest generation for Shopify Bulk JSONL snapshots."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO, Iterable

MANIFEST_SCHEMA_VERSION = 1
KNOWN_TYPES = {"Product", "ProductVariant", "ResourcePublicationV2", "InventoryLevel"}
MAX_RECORDED_ERRORS = 100


class SnapshotContractError(ValueError):
    """Raised when caller-provided validation options are invalid."""


@dataclass(frozen=True, slots=True)
class SnapshotProvenance:
    operation_id: str
    source_file: str
    snapshot_sha256: str
    snapshot_bytes: int
    query_sha256: str
    generated_at: str


@dataclass(frozen=True, slots=True)
class ContractViolation:
    line: int | None
    code: str
    detail: str


@dataclass(frozen=True, slots=True)
class SnapshotManifest:
    schema_version: int
    valid: bool
    provenance: SnapshotProvenance
    line_count: int
    object_counts: dict[str, int]
    product_status_counts: dict[str, int]
    product_type_counts: dict[str, int]
    source_identity_counts: dict[str, int]
    online_store_published_products: int
    products_without_variants: int
    duplicate_source_id_groups: int
    duplicate_source_id_products: int
    media_counts: dict[str, int]
    violation_count: int
    violations: tuple[ContractViolation, ...]

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["provenance"] = asdict(self.provenance)
        payload["violations"] = [asdict(item) for item in self.violations]
        return payload


class _Violations:
    def __init__(self) -> None:
        self.total = 0
        self.items: list[ContractViolation] = []

    def add(self, *, line: int | None, code: str, detail: str) -> None:
        self.total += 1
        if len(self.items) < MAX_RECORDED_ERRORS:
            self.items.append(ContractViolation(line=line, code=code, detail=detail))


class _DigestingLines:
    def __init__(self, handle: BinaryIO) -> None:
        self.handle = handle
        self.digest = hashlib.sha256()
        self.byte_count = 0

    def __iter__(self) -> Iterable[tuple[int, bytes]]:
        for line_number, raw_line in enumerate(self.handle, start=1):
            self.digest.update(raw_line)
            self.byte_count += len(raw_line)
            yield line_number, raw_line


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _required_keys(
    record: dict[str, Any],
    keys: set[str],
    *,
    line: int,
    type_name: str,
    violations: _Violations,
) -> bool:
    missing = sorted(keys - record.keys())
    if not missing:
        return True
    violations.add(
        line=line,
        code="missing_required_fields",
        detail=f"{type_name}: {', '.join(missing)}",
    )
    return False


def _gid(value: Any, expected_kind: str) -> str | None:
    if not isinstance(value, str) or not value.startswith(f"gid://shopify/{expected_kind}/"):
        return None
    return value


def _metafield_value(record: dict[str, Any], key: str) -> str | None:
    value = record.get(key)
    if value is None:
        return None
    if not isinstance(value, dict):
        return ""
    raw = value.get("value")
    return raw.strip() if isinstance(raw, str) else ""


def _product_identity_state(record: dict[str, Any]) -> tuple[str, str | None]:
    sync_id = _metafield_value(record, "syncProductId")
    powertools_id = _metafield_value(record, "powertoolsId")
    if sync_id is None and powertools_id is None:
        return "both_missing", None
    if not sync_id or not powertools_id:
        return "one_sided", sync_id or powertools_id
    if sync_id != powertools_id:
        return "mismatch", None
    if not sync_id.isdecimal():
        return "nonnumeric_match", sync_id
    return "matching_numeric", sync_id


def _decode_record(
    raw_line: bytes,
    line_number: int,
    violations: _Violations,
) -> dict[str, Any] | None:
    if not raw_line.strip():
        violations.add(line=line_number, code="blank_line", detail="JSONL line is empty")
        return None
    try:
        record = json.loads(raw_line)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        violations.add(line=line_number, code="invalid_json", detail=str(exc))
        return None
    if not isinstance(record, dict):
        violations.add(line=line_number, code="non_object_json", detail=type(record).__name__)
        return None
    return record


def _validate_product(
    record: dict[str, Any],
    *,
    line: int,
    product_ids: set[str],
    source_ids: dict[str, list[str]],
    statuses: Counter[str],
    product_types: Counter[str],
    source_states: Counter[str],
    media_counts: Counter[str],
    violations: _Violations,
) -> None:
    required = {
        "id",
        "handle",
        "title",
        "status",
        "vendor",
        "productType",
        "tags",
        "createdAt",
        "updatedAt",
        "publishedAt",
        "onlineStoreUrl",
        "totalInventory",
        "tracksInventory",
        "featuredMedia",
        "syncProductId",
        "powertoolsId",
    }
    _required_keys(record, required, line=line, type_name="Product", violations=violations)
    if "__parentId" in record:
        violations.add(line=line, code="root_has_parent", detail="Product has __parentId")

    product_id = _gid(record.get("id"), "Product")
    if product_id is None:
        violations.add(line=line, code="invalid_product_gid", detail=repr(record.get("id")))
    elif product_id in product_ids:
        violations.add(line=line, code="duplicate_product_gid", detail=product_id)
    else:
        product_ids.add(product_id)

    tags = record.get("tags")
    if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
        violations.add(line=line, code="invalid_tags", detail="tags must be a list of strings")

    status = record.get("status")
    statuses[str(status) if isinstance(status, str) else "<invalid>"] += 1
    product_type = record.get("productType")
    product_types[product_type.strip() if isinstance(product_type, str) else "<invalid>"] += 1

    media = record.get("featuredMedia")
    if media is None:
        media_counts["missing"] += 1
    elif isinstance(media, dict) and media.get("__typename") == "MediaImage":
        image = media.get("image")
        if isinstance(image, dict) and isinstance(image.get("url"), str) and image["url"]:
            media_counts["media_image_with_url"] += 1
        else:
            media_counts["media_image_without_url"] += 1
    else:
        media_counts["unsupported_or_invalid"] += 1

    identity_state, source_id = _product_identity_state(record)
    source_states[identity_state] += 1
    if identity_state in {"one_sided", "mismatch", "nonnumeric_match"}:
        violations.add(
            line=line,
            code=f"source_identity_{identity_state}",
            detail=product_id or "invalid product",
        )
    if source_id and product_id:
        source_ids[source_id].append(product_id)


def _validate_variant(
    record: dict[str, Any],
    *,
    line: int,
    variant_ids: set[str],
    variant_parents: Counter[str],
    inventory_item_ids: set[str],
    violations: _Violations,
) -> None:
    required = {
        "id",
        "__parentId",
        "title",
        "sku",
        "price",
        "compareAtPrice",
        "inventoryQuantity",
        "inventoryPolicy",
        "updatedAt",
        "inventoryItem",
    }
    _required_keys(record, required, line=line, type_name="ProductVariant", violations=violations)
    variant_id = _gid(record.get("id"), "ProductVariant")
    if variant_id is None:
        violations.add(line=line, code="invalid_variant_gid", detail=repr(record.get("id")))
    elif variant_id in variant_ids:
        violations.add(line=line, code="duplicate_variant_gid", detail=variant_id)
    else:
        variant_ids.add(variant_id)

    parent_id = _gid(record.get("__parentId"), "Product")
    if parent_id is None:
        violations.add(
            line=line,
            code="invalid_variant_parent",
            detail=repr(record.get("__parentId")),
        )
    else:
        variant_parents[parent_id] += 1

    inventory_item = record.get("inventoryItem")
    if not isinstance(inventory_item, dict):
        violations.add(
            line=line,
            code="missing_inventory_item",
            detail=variant_id or "invalid variant",
        )
        return
    inventory_item_id = _gid(inventory_item.get("id"), "InventoryItem")
    if inventory_item_id is None:
        violations.add(
            line=line,
            code="invalid_inventory_item_gid",
            detail=repr(inventory_item.get("id")),
        )
    elif inventory_item_id in inventory_item_ids:
        violations.add(line=line, code="duplicate_inventory_item_gid", detail=inventory_item_id)
    else:
        inventory_item_ids.add(inventory_item_id)
    if not isinstance(inventory_item.get("tracked"), bool):
        violations.add(
            line=line,
            code="invalid_inventory_tracked",
            detail=variant_id or "invalid variant",
        )


def _validate_publication(
    record: dict[str, Any],
    *,
    line: int,
    publication_parents: set[str],
    online_store_published: set[str],
    violations: _Violations,
) -> None:
    required = {"__parentId", "isPublished", "publishDate", "publication"}
    _required_keys(
        record,
        required,
        line=line,
        type_name="ResourcePublicationV2",
        violations=violations,
    )
    parent_id = _gid(record.get("__parentId"), "Product")
    if parent_id is None:
        violations.add(
            line=line,
            code="invalid_publication_parent",
            detail=repr(record.get("__parentId")),
        )
        return
    publication_parents.add(parent_id)
    publication = record.get("publication")
    if not isinstance(publication, dict):
        violations.add(line=line, code="invalid_publication", detail=parent_id)
        return
    publication_id = _gid(publication.get("id"), "Publication")
    catalog = publication.get("catalog")
    if publication_id is None or not isinstance(catalog, dict):
        violations.add(line=line, code="invalid_publication", detail=parent_id)
        return
    catalog_title = catalog.get("title")
    if record.get("isPublished") is True and catalog_title == "Online Store":
        online_store_published.add(parent_id)


def _validate_inventory_level(
    record: dict[str, Any],
    *,
    line: int,
    inventory_level_ids: set[str],
    inventory_level_parents: Counter[str],
    violations: _Violations,
) -> None:
    required = {"id", "__parentId", "location", "quantities"}
    _required_keys(record, required, line=line, type_name="InventoryLevel", violations=violations)
    level_id = _gid(record.get("id"), "InventoryLevel")
    if level_id is None:
        violations.add(line=line, code="invalid_inventory_level_gid", detail=repr(record.get("id")))
    elif level_id in inventory_level_ids:
        violations.add(line=line, code="duplicate_inventory_level_gid", detail=level_id)
    else:
        inventory_level_ids.add(level_id)
    parent_id = _gid(record.get("__parentId"), "InventoryItem")
    if parent_id is None:
        violations.add(
            line=line,
            code="invalid_inventory_level_parent",
            detail=repr(record.get("__parentId")),
        )
    else:
        inventory_level_parents[parent_id] += 1
    location = record.get("location")
    quantities = record.get("quantities")
    if not isinstance(location, dict) or _gid(location.get("id"), "Location") is None:
        violations.add(
            line=line,
            code="invalid_inventory_location",
            detail=level_id or "invalid level",
        )
    if not isinstance(quantities, list) or any(
        not isinstance(item, dict)
        or not isinstance(item.get("name"), str)
        or not isinstance(item.get("quantity"), int)
        for item in quantities
    ):
        violations.add(
            line=line,
            code="invalid_inventory_quantities",
            detail=level_id or "invalid level",
        )


def _dangling(
    *,
    child_name: str,
    parents: Iterable[str],
    valid_parents: set[str],
    violations: _Violations,
) -> None:
    for parent_id in sorted(set(parents) - valid_parents):
        violations.add(line=None, code=f"dangling_{child_name}_parent", detail=parent_id)


def validate_bulk_snapshot(
    snapshot_path: Path,
    *,
    query_path: Path,
    operation_id: str,
    expected_products: int | None = None,
    generated_at: datetime | None = None,
) -> SnapshotManifest:
    """Validate a Shopify Bulk JSONL file and return a bounded, reviewable manifest."""
    if expected_products is not None and expected_products < 1:
        raise SnapshotContractError("expected_products must be positive")
    if not operation_id.startswith("gid://shopify/BulkOperation/"):
        raise SnapshotContractError("operation_id must be a Shopify BulkOperation GID")
    if not snapshot_path.is_file():
        raise SnapshotContractError(f"snapshot file not found: {snapshot_path}")
    if not query_path.is_file():
        raise SnapshotContractError(f"query file not found: {query_path}")

    violations = _Violations()
    object_counts: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    product_types: Counter[str] = Counter()
    source_states: Counter[str] = Counter()
    media_counts: Counter[str] = Counter()
    product_ids: set[str] = set()
    variant_ids: set[str] = set()
    inventory_item_ids: set[str] = set()
    inventory_level_ids: set[str] = set()
    variant_parents: Counter[str] = Counter()
    publication_parents: set[str] = set()
    inventory_level_parents: Counter[str] = Counter()
    online_store_published: set[str] = set()
    source_ids: dict[str, list[str]] = defaultdict(list)

    with snapshot_path.open("rb") as handle:
        lines = _DigestingLines(handle)
        line_count = 0
        for line_number, raw_line in lines:
            line_count = line_number
            record = _decode_record(raw_line, line_number, violations)
            if record is None:
                continue
            type_name = record.get("__typename")
            if type_name not in KNOWN_TYPES:
                violations.add(line=line_number, code="unknown_typename", detail=repr(type_name))
                continue
            object_counts[type_name] += 1
            if type_name == "Product":
                _validate_product(
                    record,
                    line=line_number,
                    product_ids=product_ids,
                    source_ids=source_ids,
                    statuses=statuses,
                    product_types=product_types,
                    source_states=source_states,
                    media_counts=media_counts,
                    violations=violations,
                )
            elif type_name == "ProductVariant":
                _validate_variant(
                    record,
                    line=line_number,
                    variant_ids=variant_ids,
                    variant_parents=variant_parents,
                    inventory_item_ids=inventory_item_ids,
                    violations=violations,
                )
            elif type_name == "ResourcePublicationV2":
                _validate_publication(
                    record,
                    line=line_number,
                    publication_parents=publication_parents,
                    online_store_published=online_store_published,
                    violations=violations,
                )
            else:
                _validate_inventory_level(
                    record,
                    line=line_number,
                    inventory_level_ids=inventory_level_ids,
                    inventory_level_parents=inventory_level_parents,
                    violations=violations,
                )

    _dangling(
        child_name="variant",
        parents=variant_parents,
        valid_parents=product_ids,
        violations=violations,
    )
    _dangling(
        child_name="publication",
        parents=publication_parents,
        valid_parents=product_ids,
        violations=violations,
    )
    _dangling(
        child_name="inventory_level",
        parents=inventory_level_parents,
        valid_parents=inventory_item_ids,
        violations=violations,
    )

    products_without_variants = len(product_ids - set(variant_parents))
    if products_without_variants:
        violations.add(
            line=None,
            code="products_without_variants",
            detail=str(products_without_variants),
        )
    if expected_products is not None and len(product_ids) != expected_products:
        violations.add(
            line=None,
            code="unexpected_product_count",
            detail=f"expected {expected_products}, observed {len(product_ids)}",
        )

    duplicate_source_groups = {key: values for key, values in source_ids.items() if len(values) > 1}
    duplicate_source_products = sum(len(values) for values in duplicate_source_groups.values())
    generated = generated_at or datetime.now(UTC)
    provenance = SnapshotProvenance(
        operation_id=operation_id,
        source_file=snapshot_path.name,
        snapshot_sha256=lines.digest.hexdigest(),
        snapshot_bytes=lines.byte_count,
        query_sha256=_file_sha256(query_path),
        generated_at=generated.astimezone(UTC).isoformat().replace("+00:00", "Z"),
    )
    return SnapshotManifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        valid=violations.total == 0,
        provenance=provenance,
        line_count=line_count,
        object_counts=dict(sorted(object_counts.items())),
        product_status_counts=dict(sorted(statuses.items())),
        product_type_counts=dict(sorted(product_types.items())),
        source_identity_counts=dict(sorted(source_states.items())),
        online_store_published_products=len(online_store_published),
        products_without_variants=products_without_variants,
        duplicate_source_id_groups=len(duplicate_source_groups),
        duplicate_source_id_products=duplicate_source_products,
        media_counts=dict(sorted(media_counts.items())),
        violation_count=violations.total,
        violations=tuple(violations.items),
    )
