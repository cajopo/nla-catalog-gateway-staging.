"""Parse a controlled Shopify Admin Bulk JSONL baseline without silent drops."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from nla_catalog_gateway.taxonomy import (
    Classification,
    ProductFacts,
    ProductFamily,
    TaxonomyConfig,
    classify_product,
    load_taxonomy,
)

_ALLOWED_TYPES = {"Metafield", "Product", "ProductVariant", "ResourcePublicationV2"}
_ALLOWED_STATUSES = {"ACTIVE", "ARCHIVED", "DRAFT"}


class BulkContractError(ValueError):
    """Raised when a Bulk export violates the frozen baseline contract."""


@dataclass(frozen=True, slots=True)
class VariantRecord:
    variant_gid: str
    product_gid: str
    title: str
    sku: str | None
    barcode: str | None
    price: str
    inventory_quantity: int
    selected_options: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class MetafieldRecord:
    owner_gid: str
    namespace: str
    key: str
    value_type: str
    value: str


@dataclass(frozen=True, slots=True)
class ProductRecord:
    product_gid: str
    handle: str
    commercial_title: str
    status: str
    product_type: str
    vendor: str
    tags: tuple[str, ...]
    updated_at: str
    published_online_store: bool
    featured_image_url: str | None
    source_id: str | None
    canonical_card_name: str | None
    variants: tuple[VariantRecord, ...]
    metafields: tuple[MetafieldRecord, ...]
    classification: Classification


@dataclass(frozen=True, slots=True)
class BaselineSnapshot:
    source_sha256: str
    online_store_publication_gid: str
    products: tuple[ProductRecord, ...]

    @property
    def variants(self) -> tuple[VariantRecord, ...]:
        return tuple(variant for product in self.products for variant in product.variants)

    def manifest(self) -> dict[str, Any]:
        family_counts = Counter(
            (
                product.classification.game.value
                if product.classification.game is not None
                else "unknown",
                product.classification.family.value,
            )
            for product in self.products
        )
        reason_counts = Counter(
            product.classification.reason or "unspecified"
            for product in self.products
            if not product.classification.classified
        )
        classified = sum(product.classification.classified for product in self.products)
        return {
            "sourceSha256": self.source_sha256,
            "onlineStorePublicationGid": self.online_store_publication_gid,
            "productCount": len(self.products),
            "variantCount": len(self.variants),
            "activePublishedCount": sum(
                product.status == "ACTIVE" and product.published_online_store
                for product in self.products
            ),
            "classifiedCount": classified,
            "unclassifiedCount": len(self.products) - classified,
            "familyCounts": {
                f"{game}/{family}": count
                for (game, family), count in sorted(family_counts.items())
            },
            "unclassifiedReasons": dict(sorted(reason_counts.items())),
        }


def _required_text(row: dict[str, Any], key: str, context: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise BulkContractError(f"{context}: {key} must be non-empty text")
    return value.strip()


def _optional_text(row: dict[str, Any], key: str, context: str) -> str | None:
    value = row.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise BulkContractError(f"{context}: {key} must be text or null")
    normalized = value.strip()
    return normalized or None


def _gid(row: dict[str, Any], key: str, resource: str, context: str) -> str:
    value = _required_text(row, key, context)
    prefix = f"gid://shopify/{resource}/"
    if not value.startswith(prefix):
        raise BulkContractError(f"{context}: {key} must start with {prefix}")
    return value


def _validate_timestamp(value: str, context: str) -> str:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BulkContractError(f"{context}: invalid updatedAt") from exc
    return value


def _tags(row: dict[str, Any], context: str) -> tuple[str, ...]:
    value = row.get("tags")
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise BulkContractError(f"{context}: tags must be a string list")
    return tuple(item.strip() for item in value if item.strip())


def _image_url(row: dict[str, Any], context: str) -> str | None:
    media = row.get("featuredMedia")
    if media is None:
        return None
    try:
        value = media["preview"]["image"]["url"]
    except (KeyError, TypeError) as exc:
        raise BulkContractError(f"{context}: invalid featuredMedia shape") from exc
    if not isinstance(value, str) or not value.strip():
        raise BulkContractError(f"{context}: featured image URL must be non-empty text")
    return value.strip()


def _price(row: dict[str, Any], context: str) -> str:
    value = _required_text(row, "price", context)
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise BulkContractError(f"{context}: invalid price") from exc
    if not amount.is_finite() or amount < 0:
        raise BulkContractError(f"{context}: price must be a finite non-negative amount")
    return format(amount, "f")


def _selected_options(row: dict[str, Any], context: str) -> tuple[tuple[str, str], ...]:
    value = row.get("selectedOptions")
    if not isinstance(value, list):
        raise BulkContractError(f"{context}: selectedOptions must be a list")
    options: list[tuple[str, str]] = []
    for index, option in enumerate(value):
        option_context = f"{context}.selectedOptions[{index}]"
        if not isinstance(option, dict):
            raise BulkContractError(f"{option_context}: option must be an object")
        options.append(
            (
                _required_text(option, "name", option_context),
                _required_text(option, "value", option_context),
            )
        )
    return tuple(options)


def _variant(row: dict[str, Any], line_number: int) -> VariantRecord:
    context = f"line {line_number} ProductVariant"
    inventory = row.get("inventoryQuantity")
    if isinstance(inventory, bool) or not isinstance(inventory, int):
        raise BulkContractError(f"{context}: inventoryQuantity must be an integer")
    return VariantRecord(
        variant_gid=_gid(row, "id", "ProductVariant", context),
        product_gid=_gid(row, "__parentId", "Product", context),
        title=_required_text(row, "title", context),
        sku=_optional_text(row, "sku", context),
        barcode=_optional_text(row, "barcode", context),
        price=_price(row, context),
        inventory_quantity=inventory,
        selected_options=_selected_options(row, context),
    )


def _metafield(row: dict[str, Any], line_number: int) -> MetafieldRecord:
    context = f"line {line_number} Metafield"
    owner_gid = _required_text(row, "__parentId", context)
    if not owner_gid.startswith(("gid://shopify/Product/", "gid://shopify/ProductVariant/")):
        raise BulkContractError(f"{context}: unsupported metafield owner")
    return MetafieldRecord(
        owner_gid=owner_gid,
        namespace=_required_text(row, "namespace", context),
        key=_required_text(row, "key", context),
        value_type=_required_text(row, "type", context),
        value=_required_text(row, "value", context),
    )


def _publication(row: dict[str, Any], line_number: int) -> tuple[str, str, bool]:
    context = f"line {line_number} ResourcePublicationV2"
    parent_gid = _gid(row, "__parentId", "Product", context)
    publication = row.get("publication")
    if not isinstance(publication, dict):
        raise BulkContractError(f"{context}: publication must be an object")
    publication_gid = _gid(publication, "id", "Publication", context)
    is_published = row.get("isPublished")
    if not isinstance(is_published, bool):
        raise BulkContractError(f"{context}: isPublished must be boolean")
    return parent_gid, publication_gid, is_published


def _metadata_value(
    records: tuple[MetafieldRecord, ...], namespace: str, key: str
) -> str | None:
    values = [item.value for item in records if item.namespace == namespace and item.key == key]
    if len(values) > 1:
        raise BulkContractError(f"duplicate metafield {namespace}.{key}")
    return values[0] if values else None


def load_bulk_snapshot(
    path: Path,
    *,
    online_store_publication_gid: str,
    taxonomy: TaxonomyConfig | None = None,
) -> BaselineSnapshot:
    """Load and reconcile one controlled Bulk JSONL export."""
    if not online_store_publication_gid.startswith("gid://shopify/Publication/"):
        raise BulkContractError("invalid online store publication GID")
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise BulkContractError(f"cannot read Bulk export: {exc}") from exc
    source_sha256 = hashlib.sha256(payload).hexdigest()
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BulkContractError("Bulk export must be UTF-8") from exc
    if not text:
        raise BulkContractError("Bulk export is empty")

    product_rows: dict[str, tuple[int, dict[str, Any]]] = {}
    variant_rows: dict[str, tuple[int, dict[str, Any]]] = {}
    metafields: list[MetafieldRecord] = []
    publications: list[tuple[str, str, bool]] = []

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        if not raw_line.strip():
            raise BulkContractError(f"line {line_number}: blank JSONL record")
        try:
            row = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise BulkContractError(f"line {line_number}: invalid JSON") from exc
        if not isinstance(row, dict):
            raise BulkContractError(f"line {line_number}: record must be an object")
        node_type = row.get("__typename")
        if node_type not in _ALLOWED_TYPES:
            raise BulkContractError(f"line {line_number}: unsupported __typename {node_type!r}")
        if node_type == "Product":
            context = f"line {line_number} Product"
            gid = _gid(row, "id", "Product", context)
            if gid in product_rows:
                raise BulkContractError(f"duplicate product {gid}")
            product_rows[gid] = (line_number, row)
        elif node_type == "ProductVariant":
            variant = _variant(row, line_number)
            if variant.variant_gid in variant_rows:
                raise BulkContractError(f"duplicate variant {variant.variant_gid}")
            variant_rows[variant.variant_gid] = (line_number, row)
        elif node_type == "Metafield":
            metafields.append(_metafield(row, line_number))
        else:
            publications.append(_publication(row, line_number))

    config = taxonomy or load_taxonomy()
    variants_by_product: dict[str, list[VariantRecord]] = defaultdict(list)
    for line_number, row in variant_rows.values():
        variant = _variant(row, line_number)
        if variant.product_gid not in product_rows:
            raise BulkContractError(f"orphan variant {variant.variant_gid}")
        variants_by_product[variant.product_gid].append(variant)

    product_metafields: dict[str, list[MetafieldRecord]] = defaultdict(list)
    variant_ids = set(variant_rows)
    for metafield in metafields:
        if metafield.owner_gid in product_rows:
            product_metafields[metafield.owner_gid].append(metafield)
        elif metafield.owner_gid not in variant_ids:
            raise BulkContractError(f"orphan metafield owner {metafield.owner_gid}")

    published_products: set[str] = set()
    for parent_gid, publication_gid, is_published in publications:
        if parent_gid not in product_rows:
            raise BulkContractError(f"orphan publication {parent_gid}")
        if publication_gid == online_store_publication_gid and is_published:
            published_products.add(parent_gid)

    products: list[ProductRecord] = []
    handles: set[str] = set()
    for product_gid, (line_number, row) in sorted(product_rows.items()):
        context = f"line {line_number} Product"
        handle = _required_text(row, "handle", context)
        if handle in handles:
            raise BulkContractError(f"duplicate handle {handle}")
        handles.add(handle)
        status = _required_text(row, "status", context)
        if status not in _ALLOWED_STATUSES:
            raise BulkContractError(f"{context}: unsupported status {status}")
        commercial_title = _required_text(row, "title", context)
        product_type = _optional_text(row, "productType", context) or ""
        vendor = _optional_text(row, "vendor", context) or ""
        records = tuple(
            sorted(
                product_metafields[product_gid],
                key=lambda item: (item.namespace, item.key, item.value_type, item.value),
            )
        )
        source_id = _metadata_value(records, "sync", "productid")
        explicit_game = _metadata_value(records, "nla", "game")
        source_record_type = _metadata_value(records, "nla", "record_type")
        canonical_card_name = _metadata_value(records, "nla", "canonical_card_name")
        classification = classify_product(
            ProductFacts(
                product_gid=product_gid,
                explicit_game=explicit_game,
                product_type=product_type,
                tags=_tags(row, context),
                source_record_type=source_record_type,
                commercial_title=commercial_title,
                canonical_card_name=canonical_card_name,
            ),
            config,
        )
        products.append(
            ProductRecord(
                product_gid=product_gid,
                handle=handle,
                commercial_title=commercial_title,
                status=status,
                product_type=product_type,
                vendor=vendor,
                tags=_tags(row, context),
                updated_at=_validate_timestamp(
                    _required_text(row, "updatedAt", context), context
                ),
                published_online_store=product_gid in published_products,
                featured_image_url=_image_url(row, context),
                source_id=source_id,
                canonical_card_name=canonical_card_name,
                variants=tuple(
                    sorted(
                        variants_by_product[product_gid],
                        key=lambda item: item.variant_gid,
                    )
                ),
                metafields=records,
                classification=classification,
            )
        )

    snapshot = BaselineSnapshot(
        source_sha256=source_sha256,
        online_store_publication_gid=online_store_publication_gid,
        products=tuple(products),
    )
    manifest = snapshot.manifest()
    if manifest["classifiedCount"] + manifest["unclassifiedCount"] != len(products):
        raise BulkContractError("classification reconciliation failed")
    if any(
        product.classification.family is ProductFamily.UNCLASSIFIED
        and not product.classification.reason
        for product in products
    ):
        raise BulkContractError("unclassified product without reason")
    return snapshot
