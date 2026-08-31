from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from nla_catalog_gateway import bulk_records as bulk
from nla_catalog_gateway.taxonomy import Classification, ProductFamily, load_taxonomy

ONLINE_STORE = "gid://shopify/Publication/1"
OTHER_PUBLICATION = "gid://shopify/Publication/2"


def _product(
    number: int,
    *,
    title: str = "Test product",
    handle: str | None = None,
    product_type: str = "",
    tags: list[str] | None = None,
    featured: bool = False,
) -> dict[str, object]:
    row: dict[str, object] = {
        "__typename": "Product",
        "id": f"gid://shopify/Product/{number}",
        "handle": handle or f"product-{number}",
        "title": title,
        "status": "ACTIVE",
        "productType": product_type,
        "vendor": "UMBRIA GIFT",
        "tags": tags or [],
        "updatedAt": "2026-08-31T12:00:00Z",
        "featuredMedia": None,
    }
    if featured:
        row["featuredMedia"] = {
            "preview": {"image": {"url": f"https://cdn.example/{number}.jpg"}}
        }
    return row


def _variant(
    product_number: int,
    variant_number: int,
    *,
    price: str = "10.00",
    inventory: int = 1,
) -> dict[str, object]:
    return {
        "__typename": "ProductVariant",
        "__parentId": f"gid://shopify/Product/{product_number}",
        "id": f"gid://shopify/ProductVariant/{variant_number}",
        "title": "English / Normal",
        "sku": "",
        "barcode": None,
        "price": price,
        "inventoryQuantity": inventory,
        "selectedOptions": [
            {"name": "Language", "value": "English"},
            {"name": "Finish", "value": "Normal"},
        ],
    }


def _metafield(
    owner_number: int,
    namespace: str,
    key: str,
    value: str,
    *,
    owner: str = "Product",
) -> dict[str, object]:
    return {
        "__typename": "Metafield",
        "__parentId": f"gid://shopify/{owner}/{owner_number}",
        "namespace": namespace,
        "key": key,
        "type": "single_line_text_field",
        "value": value,
    }


def _publication(
    product_number: int,
    publication_gid: str = ONLINE_STORE,
    *,
    published: bool = True,
) -> dict[str, object]:
    return {
        "__typename": "ResourcePublicationV2",
        "__parentId": f"gid://shopify/Product/{product_number}",
        "publication": {"id": publication_gid},
        "isPublished": published,
    }


def _write(path: Path, rows: list[object]) -> bytes:
    payload = ("\n".join(json.dumps(row) for row in rows) + "\n").encode()
    path.write_bytes(payload)
    return payload


def _minimal_rows() -> list[object]:
    return [
        _product(1, product_type="Magic Display", tags=["Magic"]),
        _variant(1, 11),
    ]


def test_load_snapshot_preserves_all_rows_and_commerce_values(tmp_path: Path) -> None:
    path = tmp_path / "bulk.jsonl"
    rows: list[object] = [
        _product(
            30,
            title="Outlaws Collector Booster Box",
            product_type="Magic Display",
            tags=["Magic", "English"],
            featured=True,
        ),
        _variant(30, 302, price="300.00", inventory=-1),
        _variant(30, 301, price="299.99", inventory=2),
        _metafield(30, "sync", "productid", "758326"),
        _publication(30),
        _publication(30, OTHER_PUBLICATION),
        _product(10, title="Pikachu", tags=["Pokémon"]),
        _variant(10, 101),
        _metafield(10, "nla", "record_type", "single"),
        _metafield(10, "nla", "canonical_card_name", "Pikachu"),
        _publication(10, published=False),
        _product(20, title="One Piece sleeves", tags=["One Piece"]),
        _variant(20, 201),
        _metafield(20, "nla", "record_type", "accessory"),
        _product(40, title="Needs review"),
        _variant(40, 401),
        _metafield(
            401,
            "vendor",
            "opaque",
            "preserved upstream",
            owner="ProductVariant",
        ),
    ]
    payload = _write(path, rows)

    snapshot = bulk.load_bulk_snapshot(path, online_store_publication_gid=ONLINE_STORE)

    assert snapshot.source_sha256 == hashlib.sha256(payload).hexdigest()
    assert snapshot.source_row_counts == (
        ("Metafield", 5),
        ("Product", 4),
        ("ProductVariant", 5),
        ("ResourcePublicationV2", 3),
    )
    assert [item.product_gid for item in snapshot.products] == [
        "gid://shopify/Product/10",
        "gid://shopify/Product/20",
        "gid://shopify/Product/30",
        "gid://shopify/Product/40",
    ]
    sealed = snapshot.products[2]
    assert sealed.featured_image_url == "https://cdn.example/30.jpg"
    assert sealed.source_id == "758326"
    assert sealed.published_online_store is True
    assert sealed.classification.family is ProductFamily.SEALED
    assert [variant.variant_gid for variant in sealed.variants] == [
        "gid://shopify/ProductVariant/301",
        "gid://shopify/ProductVariant/302",
    ]
    assert sealed.variants[0].price == "299.99"
    assert sealed.variants[0].sku is None
    assert sealed.variants[0].barcode is None
    assert sealed.variants[1].inventory_quantity == -1
    assert sealed.variants[0].selected_options == (
        ("Language", "English"),
        ("Finish", "Normal"),
    )
    assert snapshot.products[0].canonical_card_name == "Pikachu"
    assert snapshot.products[0].classification.family is ProductFamily.SINGLE
    assert snapshot.products[1].classification.family is ProductFamily.ACCESSORY
    unclassified = snapshot.products[3]
    assert unclassified.classification.family is ProductFamily.UNCLASSIFIED
    assert unclassified.classification.game is None
    assert unclassified.published_online_store is False
    assert unclassified.variants[0].metafields[0].value == "preserved upstream"
    assert len(snapshot.variants) == 5
    assert len(snapshot.metafields) == 5

    manifest = snapshot.manifest()
    one_piece_key = (
        f"{snapshot.products[1].classification.game.value}/accessory"
    )
    taxonomy_version = snapshot.products[0].classification.rule_version
    assert manifest == {
        "sourceSha256": hashlib.sha256(payload).hexdigest(),
        "onlineStorePublicationGid": ONLINE_STORE,
        "sourceRowCounts": {
            "Metafield": 5,
            "Product": 4,
            "ProductVariant": 5,
            "ResourcePublicationV2": 3,
        },
        "productCount": 4,
        "variantCount": 5,
        "metafieldCount": 5,
        "activePublishedCount": 1,
        "classifiedCount": 3,
        "unclassifiedCount": 1,
        "taxonomyRuleVersions": [taxonomy_version],
        "familyCounts": {
            "magic/sealed": 1,
            one_piece_key: 1,
            "pokemon/single": 1,
            "unknown/unclassified": 1,
        },
        "unclassifiedReasons": {"missing_game_signal": 1},
    }


def test_explicit_taxonomy_config_is_accepted(tmp_path: Path) -> None:
    path = tmp_path / "bulk.jsonl"
    _write(path, _minimal_rows())
    snapshot = bulk.load_bulk_snapshot(
        path,
        online_store_publication_gid=ONLINE_STORE,
        taxonomy=load_taxonomy(),
    )
    assert snapshot.products[0].classification.family is ProductFamily.SEALED


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda row: row.update(id="wrong"), "id must start"),
        (lambda row: row.update(handle=""), "handle must be non-empty"),
        (lambda row: row.update(title=None), "title must be non-empty"),
        (lambda row: row.update(status="DELETED"), "unsupported status"),
        (lambda row: row.update(productType=3), "productType must be text or null"),
        (lambda row: row.update(vendor=[]), "vendor must be text or null"),
        (lambda row: row.update(tags="Magic"), "tags must be a list"),
        (lambda row: row.update(tags=["Magic", 4]), "tags must be a list"),
        (lambda row: row.update(tags=["Magic", ""]), "tags must be a list"),
        (lambda row: row.update(updatedAt="yesterday"), "invalid updatedAt"),
        (
            lambda row: row.update(updatedAt="2026-08-31T12:00:00"),
            "must include a timezone",
        ),
        (lambda row: row.update(featuredMedia={}), "invalid featuredMedia shape"),
        (
            lambda row: row.update(featuredMedia={"preview": {"image": {"url": ""}}}),
            "featured image URL",
        ),
    ],
)
def test_invalid_product_fields_fail_closed(
    tmp_path: Path,
    mutate,
    message: str,
) -> None:
    row = _product(1)
    mutate(row)
    path = tmp_path / "bulk.jsonl"
    _write(path, [row, _variant(1, 11)])
    with pytest.raises(bulk.BulkContractError, match=message):
        bulk.load_bulk_snapshot(path, online_store_publication_gid=ONLINE_STORE)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda row: row.update(id="wrong"), "id must start"),
        (lambda row: row.update(__parentId="wrong"), "__parentId must start"),
        (lambda row: row.update(title=""), "title must be non-empty"),
        (lambda row: row.update(sku=1), "sku must be text or null"),
        (lambda row: row.update(barcode=[]), "barcode must be text or null"),
        (lambda row: row.update(price="nope"), "invalid price"),
        (lambda row: row.update(price="NaN"), "finite non-negative"),
        (lambda row: row.update(price="-0.01"), "finite non-negative"),
        (lambda row: row.update(inventoryQuantity=True), "must be an integer"),
        (lambda row: row.update(inventoryQuantity="1"), "must be an integer"),
        (lambda row: row.update(selectedOptions={}), "must be a list"),
        (lambda row: row.update(selectedOptions=["bad"]), "option must be an object"),
        (
            lambda row: row.update(selectedOptions=[{"name": "", "value": "x"}]),
            "name must be non-empty",
        ),
        (
            lambda row: row.update(selectedOptions=[{"name": "x", "value": ""}]),
            "value must be non-empty",
        ),
        (
            lambda row: row.update(
                selectedOptions=[
                    {"name": "Language", "value": "EN"},
                    {"name": "Language", "value": "IT"},
                ]
            ),
            "duplicate option name",
        ),
    ],
)
def test_invalid_variant_fields_fail_closed(
    tmp_path: Path,
    mutate,
    message: str,
) -> None:
    row = _variant(1, 11)
    mutate(row)
    path = tmp_path / "bulk.jsonl"
    _write(path, [_product(1), row])
    with pytest.raises(bulk.BulkContractError, match=message):
        bulk.load_bulk_snapshot(path, online_store_publication_gid=ONLINE_STORE)


@pytest.mark.parametrize(
    ("row", "message"),
    [
        (
            {
                "__typename": "Metafield",
                "__parentId": "gid://shopify/Order/1",
                "namespace": "nla",
                "key": "game",
                "type": "single_line_text_field",
                "value": "Magic",
            },
            "unsupported metafield owner",
        ),
        (
            {
                "__typename": "Metafield",
                "__parentId": "gid://shopify/Product/1",
                "namespace": "",
                "key": "game",
                "type": "single_line_text_field",
                "value": "Magic",
            },
            "namespace must be non-empty",
        ),
        (
            {
                "__typename": "ResourcePublicationV2",
                "__parentId": "gid://shopify/Product/1",
                "publication": None,
                "isPublished": True,
            },
            "publication must be an object",
        ),
        (
            {
                "__typename": "ResourcePublicationV2",
                "__parentId": "gid://shopify/Product/1",
                "publication": {"id": "wrong"},
                "isPublished": True,
            },
            "id must start",
        ),
        (
            {
                "__typename": "ResourcePublicationV2",
                "__parentId": "gid://shopify/Product/1",
                "publication": {"id": ONLINE_STORE},
                "isPublished": 1,
            },
            "isPublished must be boolean",
        ),
    ],
)
def test_invalid_child_records_fail_closed(
    tmp_path: Path,
    row: dict[str, object],
    message: str,
) -> None:
    path = tmp_path / "bulk.jsonl"
    _write(path, [_product(1), _variant(1, 11), row])
    with pytest.raises(bulk.BulkContractError, match=message):
        bulk.load_bulk_snapshot(path, online_store_publication_gid=ONLINE_STORE)


def test_duplicate_and_orphan_records_fail_closed(tmp_path: Path) -> None:
    cases = [
        ([_product(1), _product(1)], "duplicate product"),
        ([_product(1), _product(2, handle="product-1")], "duplicate handle"),
        ([_product(1), _variant(1, 11), _variant(1, 11)], "duplicate variant"),
        ([_product(1), _variant(2, 11)], "orphan variant"),
        (
            [_product(1), _variant(1, 11), _metafield(2, "nla", "game", "Magic")],
            "orphan metafield",
        ),
        ([_product(1), _variant(1, 11), _publication(2)], "orphan publication"),
        (
            [
                _product(1),
                _variant(1, 11),
                _metafield(1, "vendor", "opaque", "a"),
                _metafield(1, "vendor", "opaque", "b"),
            ],
            "duplicate metafield",
        ),
        (
            [_product(1), _variant(1, 11), _publication(1), _publication(1)],
            "duplicate publication row",
        ),
    ]
    for index, (rows, message) in enumerate(cases):
        path = tmp_path / f"case-{index}.jsonl"
        _write(path, rows)
        with pytest.raises(bulk.BulkContractError, match=message):
            bulk.load_bulk_snapshot(path, online_store_publication_gid=ONLINE_STORE)


def test_product_without_variant_and_export_without_product_are_rejected(
    tmp_path: Path,
) -> None:
    product_only = tmp_path / "product-only.jsonl"
    _write(product_only, [_product(1)])
    with pytest.raises(bulk.BulkContractError, match="has no ProductVariant"):
        bulk.load_bulk_snapshot(product_only, online_store_publication_gid=ONLINE_STORE)

    variant_only = tmp_path / "variant-only.jsonl"
    _write(variant_only, [_variant(1, 11)])
    with pytest.raises(bulk.BulkContractError, match="contains no Product"):
        bulk.load_bulk_snapshot(variant_only, online_store_publication_gid=ONLINE_STORE)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (b"", "empty"),
        (b"\xff", "UTF-8"),
        (b"not-json\n", "invalid JSON"),
        (b"[]\n", "record must be an object"),
        (b"{}\n", "unsupported __typename"),
        (b"\n", "blank JSONL record"),
    ],
)
def test_invalid_jsonl_envelope_fails_closed(
    tmp_path: Path,
    payload: bytes,
    message: str,
) -> None:
    path = tmp_path / "bulk.jsonl"
    path.write_bytes(payload)
    with pytest.raises(bulk.BulkContractError, match=message):
        bulk.load_bulk_snapshot(path, online_store_publication_gid=ONLINE_STORE)


def test_invalid_publication_gid_and_missing_file_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "bulk.jsonl"
    _write(path, _minimal_rows())
    with pytest.raises(bulk.BulkContractError, match="invalid online store"):
        bulk.load_bulk_snapshot(path, online_store_publication_gid="wrong")
    with pytest.raises(bulk.BulkContractError, match="cannot read"):
        bulk.load_bulk_snapshot(
            tmp_path / "missing.jsonl",
            online_store_publication_gid=ONLINE_STORE,
        )


def test_source_row_guard_fails_closed(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "bulk.jsonl"
    _write(path, _minimal_rows())
    snapshot_type = bulk.BaselineSnapshot

    def invalid_snapshot(**kwargs):
        valid = snapshot_type(**kwargs)
        return replace(valid, source_row_counts=(("Product", 99),))

    monkeypatch.setattr(bulk, "BaselineSnapshot", invalid_snapshot)
    with pytest.raises(bulk.BulkContractError, match="source row reconciliation"):
        bulk.load_bulk_snapshot(path, online_store_publication_gid=ONLINE_STORE)


def test_classification_guard_fails_closed(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "bulk.jsonl"
    _write(path, _minimal_rows())
    original_manifest = bulk.BaselineSnapshot.manifest

    def invalid_manifest(self):
        report = original_manifest(self)
        report["classifiedCount"] = 99
        return report

    monkeypatch.setattr(bulk.BaselineSnapshot, "manifest", invalid_manifest)
    with pytest.raises(bulk.BulkContractError, match="classification reconciliation"):
        bulk.load_bulk_snapshot(path, online_store_publication_gid=ONLINE_STORE)


def test_reason_guard_fails_closed(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "bulk.jsonl"
    _write(path, _minimal_rows())

    def invalid_classification(*_args, **_kwargs):
        return Classification(
            product_gid="gid://shopify/Product/1",
            game=None,
            family=ProductFamily.UNCLASSIFIED,
            subtype=None,
            rule_version="test",
            rule_id=None,
            reason=None,
        )

    monkeypatch.setattr(bulk, "classify_product", invalid_classification)
    with pytest.raises(bulk.BulkContractError, match="without reason"):
        bulk.load_bulk_snapshot(path, online_store_publication_gid=ONLINE_STORE)
