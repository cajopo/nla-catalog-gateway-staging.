from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from nla_catalog_gateway.bulk_snapshot import (
    MAX_RECORDED_ERRORS,
    SnapshotContractError,
    validate_bulk_snapshot,
)


def product(
    product_id: int,
    *,
    source_id: str | None = "100",
    powertools_id: str | None | object = Ellipsis,
    media: object = Ellipsis,
    status: object = "ACTIVE",
    product_type: object = "Magic Single",
    tags: object = None,
    include_parent: bool = False,
) -> dict[str, object]:
    if powertools_id is Ellipsis:
        powertools_id = source_id
    if media is Ellipsis:
        media = {
            "__typename": "MediaImage",
            "id": f"gid://shopify/MediaImage/{product_id}",
            "alt": "card",
            "image": {"url": "https://cdn.example/card.jpg"},
        }
    record: dict[str, object] = {
        "__typename": "Product",
        "id": f"gid://shopify/Product/{product_id}",
        "handle": f"product-{product_id}",
        "title": f"Product {product_id}",
        "status": status,
        "vendor": "NLA",
        "productType": product_type,
        "tags": ["Magic"] if tags is None else tags,
        "createdAt": "2026-08-31T00:00:00Z",
        "updatedAt": "2026-08-31T00:00:00Z",
        "publishedAt": "2026-08-31T00:00:00Z",
        "onlineStoreUrl": None,
        "totalInventory": 0,
        "tracksInventory": True,
        "featuredMedia": media,
        "syncProductId": (
            None if source_id is None else {"type": "number_integer", "value": source_id}
        ),
        "powertoolsId": None
        if powertools_id is None
        else {"type": "number_integer", "value": powertools_id},
    }
    if include_parent:
        record["__parentId"] = "gid://shopify/Product/999"
    return record


def variant(
    product_id: int,
    variant_id: int,
    *,
    inventory_item_id: int | None = None,
    tracked: object = True,
) -> dict[str, object]:
    inventory_id = inventory_item_id if inventory_item_id is not None else variant_id
    return {
        "__typename": "ProductVariant",
        "id": f"gid://shopify/ProductVariant/{variant_id}",
        "__parentId": f"gid://shopify/Product/{product_id}",
        "title": "Default Title",
        "sku": f"SKU-{variant_id}",
        "price": "1.00",
        "compareAtPrice": None,
        "inventoryQuantity": 0,
        "inventoryPolicy": "DENY",
        "updatedAt": "2026-08-31T00:00:00Z",
        "inventoryItem": {
            "__typename": "InventoryItem",
            "id": f"gid://shopify/InventoryItem/{inventory_id}",
            "tracked": tracked,
        },
    }


def publication(
    product_id: int,
    *,
    online: bool = True,
    published: object = True,
) -> dict[str, object]:
    return {
        "__typename": "ResourcePublicationV2",
        "__parentId": f"gid://shopify/Product/{product_id}",
        "isPublished": published,
        "publishDate": "2026-08-31T00:00:00Z",
        "publication": {
            "id": "gid://shopify/Publication/1",
            "autoPublish": True,
            "catalog": {
                "id": "gid://shopify/AppCatalog/1",
                "title": "Online Store" if online else "Other",
            },
        },
    }


def level(inventory_item_id: int, level_id: int = 1) -> dict[str, object]:
    return {
        "__typename": "InventoryLevel",
        "id": f"gid://shopify/InventoryLevel/{level_id}",
        "__parentId": f"gid://shopify/InventoryItem/{inventory_item_id}",
        "location": {"id": "gid://shopify/Location/1", "name": "Main"},
        "quantities": [{"name": "available", "quantity": 0}],
    }


def write_jsonl(path: Path, records: list[object]) -> None:
    path.write_bytes(b"".join(json.dumps(record).encode() + b"\n" for record in records))


def validate(tmp_path: Path, records: list[object], *, expected: int | None = None):
    snapshot = tmp_path / "snapshot.jsonl"
    query = tmp_path / "query.graphql"
    write_jsonl(snapshot, records)
    query.write_text("query { products { edges { node { id } } } }\n", encoding="utf-8")
    return validate_bulk_snapshot(
        snapshot,
        query_path=query,
        operation_id="gid://shopify/BulkOperation/1",
        expected_products=expected,
        generated_at=datetime(2026, 8, 31, tzinfo=UTC),
    )


def test_valid_manifest_reconciles_products_children_and_source_duplicates(tmp_path: Path) -> None:
    records = [
        product(1, source_id="100"),
        publication(1),
        variant(1, 11),
        level(11, 101),
        product(2, source_id=None, media=None, status="DRAFT", product_type=""),
        publication(2, online=False),
        variant(2, 12),
        product(
            3,
            source_id="100",
            media={"__typename": "MediaImage", "image": {"url": ""}},
        ),
        publication(3, published=False),
        variant(3, 13),
        product(4, source_id="104", media={"__typename": "Video"}),
        variant(4, 14),
    ]
    manifest = validate(tmp_path, records, expected=4)
    payload = manifest.as_dict()
    assert manifest.valid is True
    assert payload["schema_version"] == 1
    assert payload["line_count"] == 12
    assert payload["object_counts"] == {
        "InventoryLevel": 1,
        "Product": 4,
        "ProductVariant": 4,
        "ResourcePublicationV2": 3,
    }
    assert payload["product_status_counts"] == {"ACTIVE": 3, "DRAFT": 1}
    assert payload["source_identity_counts"] == {"both_missing": 1, "matching_numeric": 3}
    assert payload["online_store_published_products"] == 1
    assert payload["duplicate_source_id_groups"] == 1
    assert payload["duplicate_source_id_products"] == 2
    assert payload["media_counts"] == {
        "media_image_with_url": 1,
        "media_image_without_url": 1,
        "missing": 1,
        "unsupported_or_invalid": 1,
    }
    assert payload["provenance"]["generated_at"] == "2026-08-31T00:00:00Z"
    assert len(payload["provenance"]["snapshot_sha256"]) == 64
    assert len(payload["provenance"]["query_sha256"]) == 64
    assert payload["violation_count"] == 0


def test_input_contract_errors(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot.jsonl"
    query = tmp_path / "query.graphql"
    snapshot.write_text("", encoding="utf-8")
    query.write_text("query Q { shop { id } }", encoding="utf-8")
    kwargs = {"query_path": query, "operation_id": "gid://shopify/BulkOperation/1"}
    with pytest.raises(SnapshotContractError, match="positive"):
        validate_bulk_snapshot(snapshot, expected_products=0, **kwargs)
    with pytest.raises(SnapshotContractError, match="operation_id"):
        validate_bulk_snapshot(snapshot, query_path=query, operation_id="wrong")
    with pytest.raises(SnapshotContractError, match="snapshot file"):
        validate_bulk_snapshot(tmp_path / "missing", **kwargs)
    with pytest.raises(SnapshotContractError, match="query file"):
        validate_bulk_snapshot(
            snapshot,
            query_path=tmp_path / "missing",
            operation_id="gid://shopify/BulkOperation/1",
        )


def test_malformed_lines_and_unknown_types_are_bounded(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot.jsonl"
    query = tmp_path / "query.graphql"
    raw = b"\n" + b"{\xff}\n" + b"[]\n" + b'{"__typename":"Mystery"}\n'
    raw += b"\n" * (MAX_RECORDED_ERRORS + 1)
    snapshot.write_bytes(raw)
    query.write_text("query", encoding="utf-8")
    manifest = validate_bulk_snapshot(
        snapshot,
        query_path=query,
        operation_id="gid://shopify/BulkOperation/1",
    )
    assert manifest.valid is False
    assert manifest.violation_count == MAX_RECORDED_ERRORS + 5
    assert len(manifest.violations) == MAX_RECORDED_ERRORS
    assert {item.code for item in manifest.violations[:4]} == {
        "blank_line",
        "invalid_json",
        "non_object_json",
        "unknown_typename",
    }


def test_product_violations_cover_identity_media_and_shape(tmp_path: Path) -> None:
    bad = product(
        1,
        source_id="abc",
        media={"__typename": "MediaImage", "image": None},
        status=3,
        product_type=4,
        tags=["Magic", 1],
        include_parent=True,
    )
    bad.pop("handle")
    duplicate = product(1, source_id="1", powertools_id="2")
    one_sided = product(3, source_id="3", powertools_id=None)
    invalid_gid = product(4)
    invalid_gid["id"] = "bad"
    invalid_metafield = product(5)
    invalid_metafield["syncProductId"] = "not-an-object"
    no_variant = product(6, source_id="6")
    records = [
        bad,
        variant(1, 11),
        duplicate,
        variant(1, 12),
        one_sided,
        variant(3, 13),
        invalid_gid,
        invalid_metafield,
        variant(5, 15),
        no_variant,
    ]
    manifest = validate(tmp_path, records, expected=99)
    codes = {item.code for item in manifest.violations}
    assert {
        "missing_required_fields",
        "root_has_parent",
        "invalid_tags",
        "source_identity_nonnumeric_match",
        "duplicate_product_gid",
        "source_identity_mismatch",
        "source_identity_one_sided",
        "invalid_product_gid",
        "products_without_variants",
        "unexpected_product_count",
    } <= codes
    assert manifest.product_status_counts["<invalid>"] == 1
    assert manifest.product_type_counts["<invalid>"] == 1


def test_variant_violations_and_dangling_parent(tmp_path: Path) -> None:
    valid_product = product(1)
    bad = variant(999, 1, tracked="yes")
    bad.pop("sku")
    duplicate = variant(1, 1, inventory_item_id=1)
    missing_item = variant(1, 3)
    missing_item["inventoryItem"] = None
    invalid_item = variant(1, 4)
    invalid_item["inventoryItem"] = {"id": "bad", "tracked": True}
    invalid_variant = variant(1, 5)
    invalid_variant["id"] = "bad"
    invalid_parent = variant(1, 6)
    invalid_parent["__parentId"] = "bad"
    manifest = validate(
        tmp_path,
        [
            valid_product,
            bad,
            duplicate,
            missing_item,
            invalid_item,
            invalid_variant,
            invalid_parent,
        ],
    )
    codes = {item.code for item in manifest.violations}
    assert {
        "missing_required_fields",
        "invalid_inventory_tracked",
        "duplicate_variant_gid",
        "duplicate_inventory_item_gid",
        "missing_inventory_item",
        "invalid_inventory_item_gid",
        "invalid_variant_gid",
        "invalid_variant_parent",
        "dangling_variant_parent",
    } <= codes


def test_publication_violations_and_dangling_parent(tmp_path: Path) -> None:
    records: list[object] = [product(1), variant(1, 1)]
    missing = publication(1)
    missing.pop("publishDate")
    invalid_parent = publication(1)
    invalid_parent["__parentId"] = "bad"
    invalid_object = publication(1)
    invalid_object["publication"] = None
    invalid_details = publication(999)
    invalid_details["publication"] = {"id": "bad", "catalog": None}
    records.extend([missing, invalid_parent, invalid_object, invalid_details])
    manifest = validate(tmp_path, records)
    codes = {item.code for item in manifest.violations}
    assert "missing_required_fields" in codes
    assert "invalid_publication_parent" in codes
    assert "invalid_publication" in codes
    assert "dangling_publication_parent" in codes


def test_inventory_level_violations_and_dangling_parent(tmp_path: Path) -> None:
    records: list[object] = [product(1), variant(1, 1)]
    missing = level(1, 1)
    missing.pop("quantities")
    duplicate = level(1, 1)
    invalid_gid = level(1, 3)
    invalid_gid["id"] = "bad"
    invalid_parent = level(1, 4)
    invalid_parent["__parentId"] = "bad"
    invalid_parent["location"] = None
    invalid_parent["quantities"] = [{"name": 1, "quantity": "zero"}]
    dangling = level(999, 5)
    records.extend([missing, duplicate, invalid_gid, invalid_parent, dangling])
    manifest = validate(tmp_path, records)
    codes = {item.code for item in manifest.violations}
    assert {
        "missing_required_fields",
        "duplicate_inventory_level_gid",
        "invalid_inventory_level_gid",
        "invalid_inventory_level_parent",
        "invalid_inventory_location",
        "invalid_inventory_quantities",
        "dangling_inventory_level_parent",
    } <= codes
