from __future__ import annotations

import hashlib
import json
import sqlite3
import tracemalloc
from dataclasses import replace
from pathlib import Path

import pytest

from nla_catalog_gateway import bulk as bulk_module
from nla_catalog_gateway.bulk import (
    ALLOWED_TYPES,
    BulkContractError,
    SourceSnapshotEvidence,
    build_source_candidate,
    load_source_evidence,
)

ONLINE_STORE = "gid://shopify/Publication/1"
QUERY = b"query Synthetic { products { edges { node { id } } } }\n"
SOURCE_CODE_SHA = "a" * 40


def _product(
    number: int,
    *,
    variants: int = 1,
    source_id: str | None = "100",
    powertools_id: str | object | None = Ellipsis,
    title: str = "  Exact commercial title  ",
    media: object = Ellipsis,
) -> dict[str, object]:
    if powertools_id is Ellipsis:
        powertools_id = source_id
    if media is Ellipsis:
        media = {
            "__typename": "MediaImage",
            "id": f"gid://shopify/MediaImage/{number}",
            "alt": " exact alt ",
            "mediaContentType": "IMAGE",
            "status": "READY",
            "preview": None,
            "image": {
                "url": f"https://cdn.example/{number}.jpg",
                "altText": None,
                "width": 640,
                "height": 900,
            },
        }
    return {
        "__typename": "Product",
        "id": f"gid://shopify/Product/{number}",
        "handle": f"product-{number}",
        "title": title,
        "status": "ACTIVE",
        "vendor": "",
        "productType": "Magic Display",
        "tags": ["Magic", " Sealed "],
        "createdAt": "2026-09-01T00:00:00Z",
        "updatedAt": "2026-09-01T01:00:00+00:00",
        "publishedAt": None,
        "onlineStoreUrl": None,
        "totalInventory": -3,
        "tracksInventory": True,
        "variantsCount": {"count": variants},
        "featuredMedia": media,
        "syncProductId": (
            None if source_id is None else {"type": "number_integer", "value": source_id}
        ),
        "powertoolsId": (
            None if powertools_id is None else {"type": "number_integer", "value": powertools_id}
        ),
    }


def _variant(
    product: int,
    number: int,
    *,
    item: int | None = None,
    price: object = "10.00",
    inventory: object = -2,
) -> dict[str, object]:
    item_number = number if item is None else item
    return {
        "__typename": "ProductVariant",
        "id": f"gid://shopify/ProductVariant/{number}",
        "__parentId": f"gid://shopify/Product/{product}",
        "title": "Exact variant",
        "sku": "",
        "barcode": None,
        "selectedOptions": [
            {"name": "Language", "value": "English"},
            {"name": "Finish", "value": "Foil"},
        ],
        "price": price,
        "compareAtPrice": "12.50",
        "inventoryQuantity": inventory,
        "inventoryPolicy": "DENY",
        "updatedAt": "2026-09-01T01:00:00Z",
        "inventoryItem": {
            "__typename": "InventoryItem",
            "id": f"gid://shopify/InventoryItem/{item_number}",
            "tracked": True,
        },
    }


def _publication(
    product: int,
    publication_gid: str = ONLINE_STORE,
    *,
    published: object = True,
) -> dict[str, object]:
    return {
        "__typename": "ResourcePublicationV2",
        "__parentId": f"gid://shopify/Product/{product}",
        "isPublished": published,
        "publishDate": None,
        "publication": {
            "id": publication_gid,
            "autoPublish": False,
            "catalog": {
                "__typename": "AppCatalog",
                "id": "gid://shopify/AppCatalog/1",
                "title": "Exact channel title",
            },
        },
    }


def _level(item: int, number: int, *, quantity: int = -1) -> dict[str, object]:
    return {
        "__typename": "InventoryLevel",
        "id": f"gid://shopify/InventoryLevel/{number}?inventory_item_id={item}",
        "__parentId": f"gid://shopify/InventoryItem/{item}",
        "location": {
            "id": f"gid://shopify/Location/{number}",
            "name": f"Location {number}",
        },
        "quantities": [
            {"name": "incoming", "quantity": quantity},
            {"name": "available", "quantity": quantity},
            {"name": "reserved", "quantity": quantity},
            {"name": "committed", "quantity": quantity},
            {"name": "on_hand", "quantity": quantity},
        ],
    }


def _metafield(owner: str, number: int, *, value: str = "") -> dict[str, object]:
    return {
        "__typename": "Metafield",
        "id": f"gid://shopify/Metafield/{number}",
        "__parentId": owner,
        "namespace": "nla",
        "key": f"field_{number}",
        "type": "single_line_text_field",
        "value": value,
    }


def _minimal_rows(product_number: int = 1) -> list[dict[str, object]]:
    return [
        _product(product_number, source_id=str(99 + product_number)),
        _variant(product_number, product_number * 10 + 1),
        _publication(product_number),
    ]


def _write_jsonl(path: Path, rows: list[object]) -> bytes:
    raw = b"".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
        for row in rows
    )
    path.write_bytes(raw)
    return raw


def _evidence(
    raw: bytes,
    query_path: Path,
    *,
    products: int,
    objects: int,
    active_published: int = 1,
):
    return SourceSnapshotEvidence(
        shop_domain="synthetic.myshopify.com",
        api_version="2026-07",
        operation_id="gid://shopify/BulkOperation/1",
        status="COMPLETED",
        partial_data_url_present=False,
        file_size=len(raw),
        object_count=objects,
        product_count=products,
        expected_active_online_store_published_product_count=active_published,
        query_sha256=hashlib.sha256(query_path.read_bytes()).hexdigest(),
        online_store_publication_gid=ONLINE_STORE,
        completed_at="2026-09-01T02:00:00Z",
        source_code_sha=SOURCE_CODE_SHA,
    )


def _paths(tmp_path: Path, rows: list[object]):
    tmp_path.mkdir(parents=True, exist_ok=True)
    snapshot = tmp_path / "source.jsonl"
    query = tmp_path / "query.graphql"
    query.write_bytes(QUERY)
    raw = _write_jsonl(snapshot, rows)
    published_product_gids = {
        row.get("__parentId")
        for row in rows
        if isinstance(row, dict)
        and row.get("__typename") == "ResourcePublicationV2"
        and row.get("isPublished") is True
        and isinstance(row.get("publication"), dict)
        and row["publication"].get("id") == ONLINE_STORE
    }
    evidence = _evidence(
        raw,
        query,
        products=sum(row.get("__typename") == "Product" for row in rows if isinstance(row, dict)),
        objects=len(rows),
        active_published=sum(
            row.get("__typename") == "Product"
            and row.get("status") == "ACTIVE"
            and row.get("id") in published_product_gids
            for row in rows
            if isinstance(row, dict)
        ),
    )
    return snapshot, query, evidence


def _build(tmp_path: Path, rows: list[object], name: str = "candidate"):
    snapshot, query, evidence = _paths(tmp_path, rows)
    output = tmp_path / name
    manifest = build_source_candidate(
        snapshot,
        query_path=query,
        evidence=evidence,
        expected_source_code_sha=SOURCE_CODE_SHA,
        final_directory=output,
    )
    return output, manifest


def test_valid_candidate_preserves_exact_values_and_more_than_fifty_locations(
    tmp_path: Path,
) -> None:
    rows: list[object] = [
        _product(1, variants=2),
        _variant(1, 11, item=111),
        _variant(1, 12, item=112, price="0.0100", inventory=-9),
        _publication(1),
        _metafield("gid://shopify/Product/1", 1, value=" exact metafield "),
        _metafield("gid://shopify/ProductVariant/11", 2),
    ]
    rows.extend(_level(111, number) for number in range(1, 52))

    output, manifest = _build(tmp_path, rows)

    assert sorted(path.name for path in output.iterdir()) == ["catalog.sqlite3", "manifest.json"]
    assert manifest.object_counts == (
        ("InventoryLevel", 51),
        ("Metafield", 2),
        ("Product", 1),
        ("ProductVariant", 2),
        ("ResourcePublicationV2", 1),
    )
    assert manifest.verified_active_online_store_published_product_count == 1
    assert manifest.product_status_counts == (
        ("ACTIVE", 1),
        ("ARCHIVED", 0),
        ("DRAFT", 0),
        ("UNLISTED", 0),
    )
    assert manifest.source_identity_products == 1
    assert manifest.schema_version == 2
    assert len(manifest.snapshot_sha256) == 64
    assert len(manifest.database_sha256) == 64

    connection = sqlite3.connect(output / "catalog.sqlite3")
    try:
        assert connection.execute(
            "SELECT commercial_title, total_inventory, media_alt FROM products"
        ).fetchone() == ("  Exact commercial title  ", -3, " exact alt ")
        assert connection.execute(
            "SELECT barcode, selected_options_json, price_text, inventory_quantity "
            "FROM variants WHERE gid LIKE '%/12'"
        ).fetchone() == (
            None,
            '[{"name":"Language","value":"English"},{"name":"Finish","value":"Foil"}]',
            "0.0100",
            -9,
        )
        assert connection.execute("SELECT COUNT(*) FROM inventory_levels").fetchone() == (51,)
        assert connection.execute("SELECT MIN(quantity) FROM inventory_quantities").fetchone() == (
            -1,
        )
        assert connection.execute("SELECT catalog_title FROM publications").fetchone() == (
            "Exact channel title",
        )
        assert connection.execute(
            "SELECT media_type, media_content_type, media_status FROM products"
        ).fetchone() == ("MediaImage", "IMAGE", "READY")
        assert connection.execute(
            "SELECT value FROM metafields WHERE gid='gid://shopify/Metafield/1'"
        ).fetchone() == (" exact metafield ",)
    finally:
        connection.close()
    persisted = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert persisted == manifest.as_dict()
    assert persisted["source"]["partialDataUrlPresent"] is False


def test_manifest_and_database_are_deterministic_for_identical_inputs(tmp_path: Path) -> None:
    rows = _minimal_rows()
    first, first_manifest = _build(tmp_path / "first", rows)
    second, second_manifest = _build(tmp_path / "second", rows)
    assert first_manifest.as_dict() == second_manifest.as_dict()
    assert (first / "manifest.json").read_bytes() == (second / "manifest.json").read_bytes()
    assert (first / "catalog.sqlite3").read_bytes() == (second / "catalog.sqlite3").read_bytes()


def test_unlisted_and_active_online_store_count_are_preserved_and_reconciled(
    tmp_path: Path,
) -> None:
    products = []
    variants = []
    publications = []
    for number, status, published in (
        (1, "ACTIVE", True),
        (2, "DRAFT", True),
        (3, "UNLISTED", True),
        (4, "ACTIVE", False),
    ):
        product = _product(number, source_id=str(100 + number))
        product["status"] = status
        products.append(product)
        variants.append(_variant(number, number * 10 + 1))
        publications.append(_publication(number, published=published))
    rows = [*products, *variants, *publications, _publication(4, "gid://shopify/Publication/2")]

    output, manifest = _build(tmp_path / "mixed", rows)

    assert manifest.verified_active_online_store_published_product_count == 1
    assert manifest.product_status_counts == (
        ("ACTIVE", 2),
        ("ARCHIVED", 0),
        ("DRAFT", 1),
        ("UNLISTED", 1),
    )
    connection = sqlite3.connect(output / "catalog.sqlite3")
    try:
        assert connection.execute(
            "SELECT status FROM products WHERE gid='gid://shopify/Product/3'"
        ).fetchone() == ("UNLISTED",)
    finally:
        connection.close()

    snapshot, query, evidence = _paths(tmp_path / "mismatch", rows)
    with pytest.raises(BulkContractError, match="active Online Store published Product count"):
        build_source_candidate(
            snapshot,
            query_path=query,
            evidence=replace(
                evidence,
                expected_active_online_store_published_product_count=2,
            ),
            expected_source_code_sha=SOURCE_CODE_SHA,
            final_directory=tmp_path / "mismatch-candidate",
        )
    assert not (tmp_path / "mismatch-candidate").exists()

    zero_rows = [_product(9, source_id="109"), _variant(9, 91), _publication(9, published=False)]
    _zero_output, zero_manifest = _build(tmp_path / "zero", zero_rows)
    assert zero_manifest.verified_active_online_store_published_product_count == 0


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (b"", "contains no Product"),
        (bytes.fromhex("efbbbf7b7d0a"), "BOM"),
        (b"\xff\n", "UTF-8"),
        (b"\n", "blank"),
        (b"[]\n", "must be an object"),
        (b'{"__typename":"Mystery"}\n', "unsupported __typename"),
        (b'{"__typename":"Product","id":1,"id":2}\n', "duplicate JSON key"),
        (b'{"__typename":"Product","x":{"a":1,"a":2}}\n', "duplicate JSON key"),
        (b'{"__typename":"Product","x":1.5}\n', "floating-point"),
        (b'{"__typename":"Product","x":NaN}\n', "non-finite"),
        (b'{"__typename":"Product","title":"\\ud800"}\n', "Unicode surrogate"),
        (b'{"__typename":"Product","\\ud800":1}\n', "Unicode surrogate"),
    ],
)
def test_invalid_jsonl_envelope_is_rejected_without_final_artifacts(
    tmp_path: Path, payload: bytes, message: str
) -> None:
    snapshot = tmp_path / "source.jsonl"
    query = tmp_path / "query.graphql"
    snapshot.write_bytes(payload)
    query.write_bytes(QUERY)
    evidence = _evidence(payload or b"x", query, products=1, objects=1)
    if not payload:
        evidence = replace(evidence, file_size=1)
    output = tmp_path / "candidate"
    with pytest.raises(BulkContractError, match=message):
        build_source_candidate(
            snapshot,
            query_path=query,
            evidence=evidence,
            expected_source_code_sha=SOURCE_CODE_SHA,
            final_directory=output,
        )
    assert not output.exists()
    assert not list(tmp_path.glob(".candidate.candidate-*"))


def test_attacker_sized_source_values_never_enter_diagnostics(tmp_path: Path) -> None:
    sentinel = "https://signed.example/object?token=TOPSECRET-" + "x" * 100_000
    encoded_key = json.dumps(sentinel).encode()
    product = _product(1)
    product[sentinel] = "value"
    cases = (
        json.dumps({"__typename": sentinel}, separators=(",", ":")).encode() + b"\n",
        b"{" + encoded_key + b":1," + encoded_key + b":2}\n",
        json.dumps(product, separators=(",", ":")).encode() + b"\n",
    )
    for index, raw in enumerate(cases):
        case_root = tmp_path / str(index)
        case_root.mkdir()
        snapshot = case_root / "source.jsonl"
        query = case_root / "query.graphql"
        snapshot.write_bytes(raw)
        query.write_bytes(QUERY)
        evidence = _evidence(raw, query, products=1, objects=1)
        output = case_root / "candidate"
        with pytest.raises(BulkContractError) as caught:
            build_source_candidate(
                snapshot,
                query_path=query,
                evidence=evidence,
                expected_source_code_sha=SOURCE_CODE_SHA,
                final_directory=output,
            )
        diagnostic = str(caught.value)
        assert "TOPSECRET" not in diagnostic
        assert len(diagnostic) < 256
        assert "\n" not in diagnostic
        assert not output.exists()


@pytest.mark.parametrize(
    "raw",
    [
        b'{"__typename":"Product","nested":' + b"[" * 5_000 + b"0" + b"]" * 5_000 + b"}\n",
        b'{"__typename":"Product","number":' + b"9" * 5_000 + b"}\n",
    ],
    ids=("deep-nesting", "huge-integer"),
)
def test_bounded_pathological_json_is_a_contract_error_without_artifacts(
    tmp_path: Path, raw: bytes
) -> None:
    snapshot = tmp_path / "source.jsonl"
    query = tmp_path / "query.graphql"
    snapshot.write_bytes(raw)
    query.write_bytes(QUERY)
    evidence = _evidence(raw, query, products=1, objects=1)
    output = tmp_path / "candidate"
    with pytest.raises(BulkContractError) as caught:
        build_source_candidate(
            snapshot,
            query_path=query,
            evidence=evidence,
            expected_source_code_sha=SOURCE_CODE_SHA,
            final_directory=output,
        )
    diagnostic = str(caught.value)
    assert len(diagnostic) < 256
    assert "\n" not in diagnostic
    assert not output.exists()


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda row: row.pop("handle"), "missing required fields"),
        (lambda row: row.update(extra="value"), "unexpected fields"),
        (lambda row: row.update(id="gid://shopify/Product/"), "invalid Product GID"),
        (lambda row: row.update(handle=None), "handle must be non-empty text"),
        (lambda row: row.update(status="DELETED"), "unsupported status"),
        (lambda row: row.update(tags=["Magic", ""]), "tags must be a list"),
        (lambda row: row.update(createdAt="yesterday"), "RFC3339"),
        (lambda row: row.update(updatedAt="2026-09-01T00:00:00"), "timezone"),
        (lambda row: row.update(totalInventory=True), "signed 64-bit"),
        (lambda row: row.update(tracksInventory=1), "must be boolean"),
        (lambda row: row.update(variantsCount=None), "variantsCount must be an object"),
        (lambda row: row.update(variantsCount={"count": 0}), "must be positive"),
        (lambda row: row.update(featuredMedia="bad"), "featuredMedia must be"),
        (
            lambda row: row.update(featuredMedia={"__typename": "Video"}),
            "missing required fields",
        ),
        (
            lambda row: row["featuredMedia"].update(image="invalid"),
            "image must be an object or null",
        ),
        (
            lambda row: row["syncProductId"].update(type="text"),
            "type must be number_integer",
        ),
        (
            lambda row: row["syncProductId"].update(value="abc"),
            "canonical positive decimal digits",
        ),
        (
            lambda row: row["syncProductId"].update(value="0"),
            "canonical positive decimal digits",
        ),
        (
            lambda row: row["syncProductId"].update(value="001"),
            "canonical positive decimal digits",
        ),
    ],
)
def test_product_values_and_types_fail_closed(tmp_path: Path, mutate, message: str) -> None:
    product = _product(1)
    mutate(product)
    rows = [product, _variant(1, 11), _publication(1)]
    with pytest.raises(BulkContractError, match=message):
        _build(tmp_path, rows)


def test_additional_gid_media_source_and_timestamp_contracts(tmp_path: Path) -> None:
    product = _product(1)
    product["id"] = None
    with pytest.raises(BulkContractError, match="invalid Product GID"):
        _build(tmp_path / "null-gid", [product, _variant(1, 11), _publication(1)])

    product = _product(1)
    product["syncProductId"] = "invalid"
    with pytest.raises(BulkContractError, match="source metafield must be"):
        _build(tmp_path / "source-shape", [product, _variant(1, 11), _publication(1)])

    product = _product(1)
    product["featuredMedia"] = {
        "__typename": "SecretMedia",
        "id": "gid://shopify/SecretMedia/1",
        "alt": None,
        "mediaContentType": "VIDEO",
        "status": "READY",
        "preview": None,
    }
    with pytest.raises(BulkContractError, match="unsupported featured media"):
        _build(tmp_path / "media-kind", [product, _variant(1, 11), _publication(1)])

    product = _product(1)
    product["publishedAt"] = "2026-09-01T00:00:00Z"
    publication = _publication(1)
    publication["publishDate"] = "2026-09-01T00:00:01Z"
    output, _manifest = _build(tmp_path / "timestamps", [product, _variant(1, 11), publication])
    connection = sqlite3.connect(output / "catalog.sqlite3")
    try:
        assert connection.execute("SELECT published_at FROM products").fetchone() == (
            "2026-09-01T00:00:00Z",
        )
        assert connection.execute("SELECT publish_date FROM publications").fetchone() == (
            "2026-09-01T00:00:01Z",
        )
    finally:
        connection.close()


@pytest.mark.parametrize(
    "timestamp",
    [
        "2026-09-01 02:00:00+00:00",
        "2026-W36-2T02:00:00+00:00",
        "20260901T020000+0000",
        "2026-09-01T02:00:00+00:00:30",
        "2026-09-01T02:00:00z",
        "2026-02-30T02:00:00Z",
        "2026-09-01T02:00:00+24:00",
    ],
)
def test_noncanonical_or_invalid_rfc3339_timestamps_are_rejected(
    tmp_path: Path, timestamp: str
) -> None:
    product = _product(1)
    product["createdAt"] = timestamp
    with pytest.raises(BulkContractError, match="RFC3339"):
        _build(tmp_path, [product, _variant(1, 11), _publication(1)])


def test_exact_rfc3339_fraction_and_offset_are_preserved(tmp_path: Path) -> None:
    exact = "2026-09-01T01:02:03.1200+05:30"
    product = _product(1)
    product["createdAt"] = exact
    output, _manifest = _build(tmp_path, [product, _variant(1, 11), _publication(1)])
    connection = sqlite3.connect(output / "catalog.sqlite3")
    try:
        assert connection.execute("SELECT created_at FROM products").fetchone() == (exact,)
    finally:
        connection.close()


def test_known_featured_media_shapes_and_nullable_image_fields(tmp_path: Path) -> None:
    content_types = {
        "ExternalVideo": "EXTERNAL_VIDEO",
        "Model3d": "MODEL_3D",
        "Video": "VIDEO",
    }
    for index, (media_type, content_type) in enumerate(content_types.items(), start=1):
        media = {
            "__typename": media_type,
            "id": f"gid://shopify/{media_type}/{index}",
            "alt": " exact non-image alt ",
            "mediaContentType": content_type,
            "status": "PROCESSING",
            "preview": {
                "status": "READY",
                "image": {
                    "url": f"https://cdn.example/preview-{index}.jpg",
                    "altText": None,
                    "width": None,
                    "height": 100,
                },
            },
        }
        output, _manifest = _build(
            tmp_path / media_type,
            [
                _product(index, source_id=str(200 + index), media=media),
                _variant(index, 100 + index),
                _publication(index),
            ],
        )
        connection = sqlite3.connect(output / "catalog.sqlite3")
        try:
            stored = connection.execute(
                "SELECT media_type, media_gid, media_alt, media_content_type, media_status, "
                "media_url, media_width, media_preview_status, media_preview_url, "
                "media_preview_alt_text, media_preview_width, media_preview_height, media_json "
                "FROM products"
            ).fetchone()
            assert stored == (
                media_type,
                f"gid://shopify/{media_type}/{index}",
                " exact non-image alt ",
                content_type,
                "PROCESSING",
                None,
                None,
                "READY",
                f"https://cdn.example/preview-{index}.jpg",
                None,
                None,
                100,
                json.dumps(media, separators=(",", ":")),
            )
        finally:
            connection.close()

    null_image = _product(20, source_id="220")
    null_image["featuredMedia"]["status"] = "UPLOADED"
    null_image["featuredMedia"]["image"] = None
    output, _manifest = _build(
        tmp_path / "null-image",
        [null_image, _variant(20, 201), _publication(20)],
    )
    connection = sqlite3.connect(output / "catalog.sqlite3")
    try:
        assert connection.execute(
            "SELECT media_url, media_alt_text, media_width, media_height FROM products"
        ).fetchone() == (None, None, None, None)
        assert '"image":null' in connection.execute("SELECT media_json FROM products").fetchone()[0]
    finally:
        connection.close()

    null_dimensions = _product(21, source_id="221")
    null_dimensions["featuredMedia"]["image"]["width"] = None
    null_dimensions["featuredMedia"]["image"]["height"] = None
    output, _manifest = _build(
        tmp_path / "null-dimensions",
        [null_dimensions, _variant(21, 211), _publication(21)],
    )
    connection = sqlite3.connect(output / "catalog.sqlite3")
    try:
        assert connection.execute("SELECT media_width, media_height FROM products").fetchone() == (
            None,
            None,
        )
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda media: media.update(__typename="SecretMedia"), "unsupported featured media"),
        (lambda media: media.update(mediaContentType="VIDEO"), "content type mismatch"),
        (lambda media: media.update(status="UNKNOWN"), "unsupported featured media status"),
        (lambda media: media.update(id="gid://shopify/Video/1"), "invalid MediaImage GID"),
        (lambda media: media["image"].update(width=True), "signed 64-bit"),
        (lambda media: media.update(preview="invalid"), "preview must be an object or null"),
        (
            lambda media: media.update(preview={"status": "UNKNOWN", "image": None}),
            "unsupported featured media preview status",
        ),
        (
            lambda media: media.update(preview={"status": "READY", "image": "invalid"}),
            "image must be an object or null",
        ),
    ],
)
def test_featured_media_contract_fails_closed(tmp_path: Path, mutate, message: str) -> None:
    product = _product(1)
    mutate(product["featuredMedia"])
    with pytest.raises(BulkContractError, match=message):
        _build(tmp_path, [product, _variant(1, 11), _publication(1)])

    video = {
        "__typename": "Video",
        "id": "gid://shopify/Video/1",
        "alt": None,
        "mediaContentType": "VIDEO",
        "status": "READY",
        "preview": None,
        "image": None,
    }
    with pytest.raises(BulkContractError, match="unexpected fields"):
        _build(
            tmp_path / "non-image-extra",
            [_product(2, source_id="202", media=video), _variant(2, 21), _publication(2)],
        )


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda row: row.pop("sku"), "missing required fields"),
        (lambda row: row.update(sku=4), "text or null"),
        (lambda row: row.update(barcode=4), "text or null"),
        (lambda row: row.update(selectedOptions=None), "selectedOptions must be a list"),
        (lambda row: row.update(selectedOptions=["bad"]), "selected option must be an object"),
        (
            lambda row: row.update(selectedOptions=[{"name": "Language"}]),
            "missing required fields",
        ),
        (
            lambda row: row.update(
                selectedOptions=[{"name": "Language", "value": "English", "extra": "x"}]
            ),
            "unexpected fields",
        ),
        (
            lambda row: row.update(selectedOptions=[{"name": 1, "value": "English"}]),
            "name must be non-empty text",
        ),
        (lambda row: row.update(price=10.0), "floating-point"),
        (lambda row: row.update(price="NaN"), "decimal price text"),
        (lambda row: row.update(price="-1.00"), "decimal price text"),
        (lambda row: row.update(compareAtPrice=[]), "decimal price text"),
        (lambda row: row.update(inventoryQuantity=True), "signed 64-bit"),
        (lambda row: row.update(inventoryPolicy="UNKNOWN"), "unsupported inventoryPolicy"),
        (lambda row: row.update(inventoryItem=None), "inventoryItem must be"),
        (
            lambda row: row["inventoryItem"].update(__typename="Wrong"),
            "invalid inventoryItem type",
        ),
        (
            lambda row: row["inventoryItem"].update(tracked=1),
            "tracked must be boolean",
        ),
    ],
)
def test_variant_values_and_types_fail_closed(tmp_path: Path, mutate, message: str) -> None:
    variant = _variant(1, 11)
    mutate(variant)
    rows = [_product(1), variant, _publication(1)]
    with pytest.raises(BulkContractError, match=message):
        _build(tmp_path, rows)


def test_variant_barcode_and_selected_options_preserve_exact_order_and_values(
    tmp_path: Path,
) -> None:
    variant = _variant(1, 11)
    variant["barcode"] = "000123456789"
    variant["selectedOptions"] = [
        {"name": "Finish", "value": " Foil "},
        {"name": "Finish", "value": "Etched ✨"},
    ]
    output, _manifest = _build(tmp_path, [_product(1), variant, _publication(1)])
    connection = sqlite3.connect(output / "catalog.sqlite3")
    try:
        assert connection.execute(
            "SELECT barcode, selected_options_json FROM variants"
        ).fetchone() == (
            "000123456789",
            '[{"name":"Finish","value":" Foil "},{"name":"Finish","value":"Etched ✨"}]',
        )
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda row: row.update(publication=None), "publication must be"),
        (lambda row: row.update(isPublished=1), "must be boolean"),
        (lambda row: row["publication"].update(catalog="invalid"), "catalog must be"),
        (
            lambda row: row["publication"]["catalog"].update(id="wrong"),
            "invalid AppCatalog GID",
        ),
    ],
)
def test_publication_values_and_types_fail_closed(tmp_path: Path, mutate, message: str) -> None:
    publication = _publication(1)
    mutate(publication)
    with pytest.raises(BulkContractError, match=message):
        _build(tmp_path, [_product(1), _variant(1, 11), publication])


def test_nullable_and_non_app_publication_catalogs_are_preserved(tmp_path: Path) -> None:
    null_catalog = _publication(1)
    null_catalog["publication"]["catalog"] = None
    output, _manifest = _build(tmp_path / "null", [_product(1), _variant(1, 11), null_catalog])
    connection = sqlite3.connect(output / "catalog.sqlite3")
    try:
        assert connection.execute(
            "SELECT catalog_type, catalog_gid, catalog_title FROM publications"
        ).fetchone() == (None, None, None)
    finally:
        connection.close()

    company = _publication(1)
    company["publication"]["catalog"] = {
        "__typename": "CompanyLocationCatalog",
        "id": "gid://shopify/CompanyLocationCatalog/10",
        "title": "Exact company location title",
    }
    output, _manifest = _build(tmp_path / "company", [_product(1), _variant(1, 11), company])
    connection = sqlite3.connect(output / "catalog.sqlite3")
    try:
        assert connection.execute(
            "SELECT catalog_type, catalog_gid, catalog_title FROM publications"
        ).fetchone() == (
            "CompanyLocationCatalog",
            "gid://shopify/CompanyLocationCatalog/10",
            "Exact company location title",
        )
    finally:
        connection.close()

    market = _publication(1)
    market["publication"]["catalog"] = {
        "__typename": "MarketCatalog",
        "id": "gid://shopify/MarketCatalog/9",
        "title": "Exact market title",
    }
    output, _manifest = _build(tmp_path / "market", [_product(1), _variant(1, 11), market])
    connection = sqlite3.connect(output / "catalog.sqlite3")
    try:
        assert connection.execute(
            "SELECT catalog_type, catalog_gid, catalog_title FROM publications"
        ).fetchone() == (
            "MarketCatalog",
            "gid://shopify/MarketCatalog/9",
            "Exact market title",
        )
    finally:
        connection.close()

    mismatch = _publication(1)
    mismatch["publication"]["catalog"] = {
        "__typename": "MarketCatalog",
        "id": "gid://shopify/AppCatalog/9",
        "title": "Mismatch",
    }
    with pytest.raises(BulkContractError, match="invalid MarketCatalog GID"):
        _build(tmp_path / "mismatch", [_product(1), _variant(1, 11), mismatch])

    invalid_gid = _publication(1)
    invalid_gid["publication"]["catalog"] = {
        "__typename": "MarketCatalog",
        "id": None,
        "title": "Invalid",
    }
    with pytest.raises(BulkContractError, match="invalid MarketCatalog GID"):
        _build(tmp_path / "catalog-gid", [_product(1), _variant(1, 11), invalid_gid])

    unknown = _publication(1)
    unknown["publication"]["catalog"] = {
        "__typename": "SecretCatalog",
        "id": "gid://shopify/SecretCatalog/9",
        "title": "Secret",
    }
    with pytest.raises(BulkContractError, match="unsupported catalog type"):
        _build(tmp_path / "catalog-unknown", [_product(1), _variant(1, 11), unknown])

    query_gid = _publication(1)
    query_gid["publication"]["catalog"] = {
        "__typename": "AppCatalog",
        "id": "gid://shopify/AppCatalog/1?x=1",
        "title": "Invalid query",
    }
    with pytest.raises(BulkContractError, match="canonical form required"):
        _build(tmp_path / "catalog-query", [_product(1), _variant(1, 11), query_gid])


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda row: row.update(id=None), "invalid InventoryLevel GID"),
        (lambda row: row.update(location=None), "location must be"),
        (lambda row: row.update(quantities=None), "quantities must be"),
        (lambda row: row.update(quantities=["bad"]), "quantity must be an object"),
        (lambda row: row["quantities"][0].update(quantity=True), "signed 64-bit"),
        (lambda row: row["quantities"].pop(), "names do not match"),
        (
            lambda row: row["quantities"].append({"name": "available", "quantity": 1}),
            "duplicate inventory quantity",
        ),
        (
            lambda row: row["quantities"][0].update(name="unknown"),
            "names do not match",
        ),
    ],
)
def test_inventory_level_values_and_types_fail_closed(tmp_path: Path, mutate, message: str) -> None:
    inventory_level = _level(11, 1)
    mutate(inventory_level)
    rows = [_product(1), _variant(1, 11), _publication(1), inventory_level]
    with pytest.raises(BulkContractError, match=message):
        _build(tmp_path, rows)


def test_parameterized_gid_and_metafield_owner_validation(tmp_path: Path) -> None:
    malformed_query = _level(11, 1)
    malformed_query["id"] = "gid://shopify/InventoryLevel/1?broken"
    with pytest.raises(BulkContractError, match="invalid InventoryLevel GID"):
        _build(tmp_path / "query-syntax", [*_minimal_rows(), malformed_query])

    duplicate_parameter = _level(11, 1)
    duplicate_parameter["id"] = "gid://shopify/InventoryLevel/1?x=1&x=2"
    with pytest.raises(BulkContractError, match="invalid InventoryLevel GID"):
        _build(tmp_path / "query-duplicate", [*_minimal_rows(), duplicate_parameter])

    empty_parameter = _level(11, 1)
    empty_parameter["id"] = "gid://shopify/InventoryLevel/1?x="
    with pytest.raises(BulkContractError, match="invalid InventoryLevel GID"):
        _build(tmp_path / "query-empty", [*_minimal_rows(), empty_parameter])

    metafield = _metafield("gid://shopify/Order/1", 1)
    with pytest.raises(BulkContractError, match="unsupported owner GID"):
        _build(tmp_path / "owner", [*_minimal_rows(), metafield])

    for index, namespace in enumerate(("NLA", " nla", "other")):
        metafield = _metafield("gid://shopify/Product/1", 1)
        metafield["namespace"] = namespace
        with pytest.raises(BulkContractError, match="metafield namespace must be nla"):
            _build(tmp_path / f"namespace-{index}", [*_minimal_rows(), metafield])


def test_canonical_gid_contract_and_unbounded_decimal_identity(tmp_path: Path) -> None:
    for index, invalid_component in enumerate(("0", "01", "abc", "%31", "1?x=1", "1#x")):
        product = _product(1)
        product["id"] = f"gid://shopify/Product/{invalid_component}"
        with pytest.raises(BulkContractError, match="canonical form required"):
            _build(
                tmp_path / f"product-{index}",
                [product, _variant(1, 11), _publication(1)],
            )

    variant = _variant(1, 11)
    variant["id"] = "gid://shopify/ProductVariant/abc?x=1"
    with pytest.raises(BulkContractError, match="invalid ProductVariant GID"):
        _build(tmp_path / "variant-query", [_product(1), variant, _publication(1)])

    for kind in (
        "BulkOperation",
        "InventoryItem",
        "Location",
        "MediaImage",
        "Metafield",
        "Publication",
    ):
        with pytest.raises(BulkContractError, match="canonical form required"):
            bulk_module._gid_value(f"gid://shopify/{kind}/1?x=1", kind, "test")

    mismatch_cases = (
        "gid://shopify/InventoryLevel/2?inventory_item_id=11",
        "gid://shopify/InventoryLevel/1?inventory_item_id=12",
        "gid://shopify/InventoryLevel/1?inventory_item_id=11&x=1",
        "gid://shopify/InventoryLevel/1?inventory_item_id=%31%31",
        "gid://shopify/InventoryLevel/1?x=1&inventory_item_id=11",
    )
    for index, invalid_gid in enumerate(mismatch_cases):
        level = _level(11, 1)
        level["id"] = invalid_gid
        with pytest.raises(BulkContractError, match="invalid InventoryLevel GID"):
            _build(tmp_path / f"level-{index}", [*_minimal_rows(), level])

    large = 9007199254740993
    output, _manifest = _build(
        tmp_path / "large-identities",
        [
            _product(large, source_id=str(large)),
            _variant(large, large, item=large),
            _publication(large),
            _level(large, large),
        ],
    )
    connection = sqlite3.connect(output / "catalog.sqlite3")
    try:
        assert connection.execute("SELECT gid, typeof(gid) FROM products").fetchone() == (
            f"gid://shopify/Product/{large}",
            "text",
        )
        assert connection.execute("SELECT gid, typeof(gid) FROM variants").fetchone() == (
            f"gid://shopify/ProductVariant/{large}",
            "text",
        )
        assert connection.execute("SELECT gid, typeof(gid) FROM inventory_levels").fetchone() == (
            f"gid://shopify/InventoryLevel/{large}?inventory_item_id={large}",
            "text",
        )
    finally:
        connection.close()


def test_duplicates_orphans_and_incomplete_children_fail_closed(tmp_path: Path) -> None:
    cases = [
        ([*_minimal_rows(), _product(1)], "duplicate or conflicting Product"),
        (
            [_product(1), _variant(2, 11), _publication(1)],
            "orphan ProductVariant",
        ),
        (
            [*_minimal_rows(), _publication(2)],
            "orphan ResourcePublicationV2",
        ),
        (
            [*_minimal_rows(), _level(999, 1)],
            "orphan InventoryLevel",
        ),
        (
            [*_minimal_rows(), _metafield("gid://shopify/Product/999", 1)],
            "orphan Metafield",
        ),
        (
            [_product(1, variants=2), _variant(1, 11), _publication(1)],
            "variant connection is incomplete",
        ),
        (
            [_product(1), _variant(1, 11)],
            "lacks explicit Online Store publication",
        ),
        (
            [_product(1, powertools_id=None), _variant(1, 11), _publication(1)],
            "one-sided or mismatched",
        ),
        (
            [
                *_minimal_rows(1),
                _product(2, source_id="100"),
                _variant(2, 21),
                _publication(2),
            ],
            "duplicate source identity",
        ),
    ]
    for index, (rows, message) in enumerate(cases):
        with pytest.raises(BulkContractError, match=message):
            _build(tmp_path / str(index), rows)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("status", "RUNNING", "status must be COMPLETED"),
        ("partial_data_url_present", True, "partial data"),
        ("file_size", 1, "fileSize"),
        ("object_count", 1, "objectCount"),
        ("product_count", 2, "productCount"),
        (
            "expected_active_online_store_published_product_count",
            0,
            "active Online Store published Product count",
        ),
        ("query_sha256", "0" * 64, "query SHA-256"),
    ],
)
def test_terminal_evidence_must_reconcile(
    tmp_path: Path, field: str, value: object, message: str
) -> None:
    snapshot, query, evidence = _paths(tmp_path, _minimal_rows())
    evidence = replace(evidence, **{field: value})
    with pytest.raises(BulkContractError, match=message):
        build_source_candidate(
            snapshot,
            query_path=query,
            evidence=evidence,
            expected_source_code_sha=SOURCE_CODE_SHA,
            final_directory=tmp_path / "candidate",
        )


def test_evidence_loader_is_strict_and_sanitized(tmp_path: Path) -> None:
    query = tmp_path / "query.graphql"
    query.write_bytes(QUERY)
    valid = _evidence(b"x", query, products=1, objects=1).as_dict()
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(json.dumps(valid), encoding="utf-8")
    assert load_source_evidence(evidence_path).as_dict() == valid

    cases = [
        (b"", "between 1 byte"),
        (b"[]", "root must be an object"),
        (b'{"status":"COMPLETED","status":"RUNNING"}', "duplicate JSON key"),
        (json.dumps({**valid, "unexpected": "value"}).encode(), "unexpected fields"),
        (
            json.dumps(
                {key: value for key, value in valid.items() if key != "apiVersion"}
            ).encode(),
            "missing required fields",
        ),
        (
            json.dumps({**valid, "expectedActiveOnlineStorePublishedProductCount": -1}).encode(),
            "must be non-negative",
        ),
    ]
    for index, (raw, message) in enumerate(cases):
        path = tmp_path / f"invalid-{index}.json"
        path.write_bytes(raw)
        with pytest.raises(BulkContractError, match=message):
            load_source_evidence(path)

    capability = "https://signed.example/object?token=TOPSECRET"
    capability_path = tmp_path / "capability.json"
    capability_path.write_text(
        json.dumps({**valid, "partialDataUrl": capability}), encoding="utf-8"
    )
    with pytest.raises(BulkContractError, match="unexpected fields") as caught:
        load_source_evidence(capability_path)
    assert "TOPSECRET" not in str(caught.value)
    assert len(str(caught.value)) < 256

    with pytest.raises(BulkContractError, match="cannot read source evidence"):
        load_source_evidence(tmp_path / "missing.json")
    oversized = tmp_path / "oversized.json"
    oversized.write_bytes(b" " * (64 * 1024 + 1))
    with pytest.raises(BulkContractError, match="between 1 byte"):
        load_source_evidence(oversized)

    exact_limit = tmp_path / "exact-limit.json"
    rendered_valid = json.dumps(valid).encode()
    exact_limit.write_bytes(
        rendered_valid + b" " * (bulk_module.MAX_EVIDENCE_BYTES - len(rendered_valid))
    )
    assert exact_limit.stat().st_size == bulk_module.MAX_EVIDENCE_BYTES
    assert load_source_evidence(exact_limit).as_dict() == valid

    class SpyStream:
        def __init__(self) -> None:
            self.read_sizes: list[int] = []

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def read(self, size: int) -> bytes:
            self.read_sizes.append(size)
            return b" " * size

    class SpyPath:
        def __init__(self, stream: SpyStream) -> None:
            self.stream = stream

        def open(self, mode: str):
            assert mode == "rb"
            return self.stream

    stream = SpyStream()
    with pytest.raises(BulkContractError, match="between 1 byte"):
        load_source_evidence(SpyPath(stream))
    assert stream.read_sizes == [bulk_module.MAX_EVIDENCE_BYTES + 1]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("shop_domain", None, "invalid shopDomain"),
        ("api_version", "2026-02", "invalid stable apiVersion"),
        ("operation_id", "wrong", "invalid BulkOperation GID"),
        ("online_store_publication_gid", "wrong", "invalid Publication GID"),
        ("partial_data_url_present", 0, "must be boolean"),
        ("file_size", 0, "fileSize must be positive"),
        ("file_size", 2**63, "fileSize must be positive"),
        ("object_count", True, "objectCount must be positive"),
        ("product_count", 0, "productCount must be positive"),
        (
            "expected_active_online_store_published_product_count",
            -1,
            "non-negative",
        ),
        (
            "expected_active_online_store_published_product_count",
            True,
            "non-negative signed 64-bit",
        ),
        (
            "expected_active_online_store_published_product_count",
            2**63,
            "non-negative signed 64-bit",
        ),
        (
            "expected_active_online_store_published_product_count",
            2,
            "cannot exceed productCount",
        ),
        ("query_sha256", None, "invalid querySha256"),
        ("completed_at", "yesterday", "RFC3339"),
        ("source_code_sha", None, "invalid sourceCodeSha"),
    ],
)
def test_direct_evidence_objects_cannot_bypass_validation(
    tmp_path: Path, field: str, value: object, message: str
) -> None:
    _snapshot, _query, evidence = _paths(tmp_path, _minimal_rows())
    with pytest.raises(BulkContractError, match=message):
        replace(evidence, **{field: value}).validate()


def test_source_code_sha_is_bound_to_independent_trusted_input(tmp_path: Path) -> None:
    snapshot, query, evidence = _paths(tmp_path, _minimal_rows())
    for index, expected, message in (
        (0, "A" * 40, "trusted expected source-code SHA is invalid"),
        (1, "b" * 40, "does not match trusted expected"),
    ):
        output = tmp_path / f"candidate-{index}"
        with pytest.raises(BulkContractError, match=message):
            build_source_candidate(
                snapshot,
                query_path=query,
                evidence=evidence,
                expected_source_code_sha=expected,
                final_directory=output,
            )
        assert not output.exists()
        assert not list(tmp_path.glob(f".{output.name}.candidate-*"))


def test_candidate_output_safety_and_failure_cleanup(tmp_path: Path) -> None:
    snapshot, query, evidence = _paths(tmp_path, _minimal_rows())
    repository = tmp_path / "repository"
    repository.mkdir()
    with pytest.raises(BulkContractError, match="outside the repository"):
        build_source_candidate(
            snapshot,
            query_path=query,
            evidence=evidence,
            expected_source_code_sha=SOURCE_CODE_SHA,
            final_directory=repository / "generated",
            repository_root=repository,
        )

    output = tmp_path / "existing"
    output.mkdir()
    marker = output / "owned"
    marker.write_text("keep", encoding="utf-8")
    with pytest.raises(BulkContractError, match="already exists"):
        build_source_candidate(
            snapshot,
            query_path=query,
            evidence=evidence,
            expected_source_code_sha=SOURCE_CODE_SHA,
            final_directory=output,
        )
    assert marker.read_text(encoding="utf-8") == "keep"

    malformed = tmp_path / "malformed.jsonl"
    valid_raw = snapshot.read_bytes()
    malformed.write_bytes(valid_raw + b"not-json\n")
    failed_evidence = replace(
        evidence,
        file_size=malformed.stat().st_size,
        object_count=evidence.object_count + 1,
    )
    failed_output = tmp_path / "failed"
    with pytest.raises(BulkContractError, match="invalid JSON"):
        build_source_candidate(
            malformed,
            query_path=query,
            evidence=failed_evidence,
            expected_source_code_sha=SOURCE_CODE_SHA,
            final_directory=failed_output,
        )
    assert not failed_output.exists()
    assert not list(tmp_path.glob(".failed.candidate-*"))

    with pytest.raises(BulkContractError, match="cannot read source snapshot"):
        build_source_candidate(
            tmp_path / "missing.jsonl",
            query_path=query,
            evidence=evidence,
            expected_source_code_sha=SOURCE_CODE_SHA,
            final_directory=tmp_path / "missing-source",
        )

    with pytest.raises(BulkContractError, match="query file not found"):
        build_source_candidate(
            snapshot,
            query_path=tmp_path / "missing.graphql",
            evidence=evidence,
            expected_source_code_sha=SOURCE_CODE_SHA,
            final_directory=tmp_path / "missing-query",
        )


def test_line_limit_and_internal_reconciliation_guards(tmp_path: Path, monkeypatch) -> None:
    query = tmp_path / "query.graphql"
    query.write_bytes(QUERY)
    oversized = tmp_path / "oversized.jsonl"
    oversized.write_bytes(b" " * (bulk_module.MAX_JSONL_LINE_BYTES + 1))
    evidence = _evidence(oversized.read_bytes(), query, products=1, objects=1)
    with pytest.raises(BulkContractError, match="maximum line size"):
        build_source_candidate(
            oversized,
            query_path=query,
            evidence=evidence,
            expected_source_code_sha=SOURCE_CODE_SHA,
            final_directory=tmp_path / "oversized-candidate",
        )

    connection = sqlite3.connect(":memory:")
    try:
        connection.executescript(bulk_module.SCHEMA)
        with pytest.raises(BulkContractError, match="source row accounting mismatch"):
            bulk_module._reconcile(
                connection,
                replace(evidence, file_size=1, object_count=2, product_count=1),
                1,
                2,
                {
                    "InventoryLevel": 0,
                    "Metafield": 0,
                    "Product": 1,
                    "ProductVariant": 0,
                    "ResourcePublicationV2": 0,
                },
            )
    finally:
        connection.close()

    output, manifest = _build(tmp_path / "quick", _minimal_rows())
    connection = sqlite3.connect(output / "catalog.sqlite3")
    try:
        monkeypatch.setattr(bulk_module, "_first_value", lambda *_args, **_kwargs: "bad")
        with pytest.raises(BulkContractError, match="quick_check"):
            bulk_module._reconcile(
                connection,
                manifest.source,
                manifest.snapshot_bytes,
                manifest.line_count,
                dict(manifest.object_counts),
            )
    finally:
        connection.close()

    with pytest.raises(BulkContractError, match="cannot read query or candidate database"):
        bulk_module._file_sha256(tmp_path / "absent")


def test_python_memory_remains_bounded_for_large_stream(tmp_path: Path) -> None:
    snapshot = tmp_path / "large.jsonl"
    query = tmp_path / "query.graphql"
    query.write_bytes(QUERY)
    product_count = 1500
    digest = hashlib.sha256()
    byte_count = 0
    object_count = 0
    with snapshot.open("wb") as handle:
        for number in range(1, product_count + 1):
            for row in _minimal_rows(number):
                raw = json.dumps(row, separators=(",", ":")).encode() + b"\n"
                handle.write(raw)
                digest.update(raw)
                byte_count += len(raw)
                object_count += 1
    evidence = SourceSnapshotEvidence(
        shop_domain="synthetic.myshopify.com",
        api_version="2026-07",
        operation_id="gid://shopify/BulkOperation/2",
        status="COMPLETED",
        partial_data_url_present=False,
        file_size=byte_count,
        object_count=object_count,
        product_count=product_count,
        expected_active_online_store_published_product_count=product_count,
        query_sha256=hashlib.sha256(QUERY).hexdigest(),
        online_store_publication_gid=ONLINE_STORE,
        completed_at="2026-09-01T02:00:00Z",
        source_code_sha=SOURCE_CODE_SHA,
    )
    tracemalloc.start()
    try:
        manifest = build_source_candidate(
            snapshot,
            query_path=query,
            evidence=evidence,
            expected_source_code_sha=SOURCE_CODE_SHA,
            final_directory=tmp_path / "large-candidate",
        )
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert manifest.line_count == object_count
    assert peak < 8 * 1024 * 1024


def test_allowed_type_order_is_frozen() -> None:
    assert ALLOWED_TYPES == tuple(sorted(ALLOWED_TYPES))


def test_split_queries_are_packaged_schema_validated_bulk_shapes() -> None:
    query_root = Path(__file__).resolve().parents[1] / "graphql"
    products = (query_root / "catalog_products_snapshot.graphql").read_text(encoding="utf-8")
    variants = (query_root / "catalog_variants_snapshot.graphql").read_text(encoding="utf-8")

    assert products.startswith("# Read-only Shopify Admin Bulk query, part 1 of 2.")
    assert variants.startswith("# Read-only Shopify Admin Bulk query, part 2 of 2.")
    assert "first:" not in products + variants
    assert products.count("query NlaCatalogProductsSnapshot") == 1
    assert variants.count("query NlaCatalogVariantsSnapshot") == 1
    assert products.count("edges {") == 3
    assert variants.count("edges {") == 3
    assert "products(sortKey: ID)" in products
    assert "productVariants(sortKey: ID)" in variants
    assert "resourcePublicationsV2" in products
    assert "catalog {\n                  __typename" in products
    assert "featuredMedia" in products
    assert "selectedOptions" in variants
    assert "inventoryLevels" in variants
    assert "product {\n          __typename\n          id" in variants
