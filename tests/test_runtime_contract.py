from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

import nla_catalog_gateway.runtime_contract as runtime
from nla_catalog_gateway.bulk import (
    ALLOWED_TYPES,
    PRODUCT_STATUSES,
    SourceSnapshotEvidence,
    SourceSnapshotManifest,
)
from nla_catalog_gateway.runtime_contract import (
    COMPATIBILITY_MATRIX_V1,
    DEFAULT_CAPABILITIES_V1,
    FIELD_DISPOSITIONS_V1,
    PUBLIC_ERROR_MESSAGES_V1,
    SERIALIZABLE_DTOS_V1,
    CapabilityMatrixV1,
    CapabilityState,
    CatalogEndpoint,
    CatalogErrorCode,
    CatalogErrorV1,
    CatalogFiltersV1,
    CatalogItemV1,
    CatalogPageV1,
    CatalogProductRecordV1,
    CatalogRequestV1,
    CatalogVariantItemV1,
    CatalogVariantRecordV1,
    CursorContextV1,
    DatasetManifestV1,
    FieldDisposition,
    InventoryPolicy,
    ProductStatus,
    RequestFamily,
    RuntimeContractError,
    SelectedOptionV1,
    decode_contract,
)
from nla_catalog_gateway.taxonomy import Classification, Game, ProductFamily

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
GENERATION = f"sha256:{SHA_A}"
UPDATED = "2026-09-01T01:02:03.400Z"
EXPIRES = "2026-09-01T02:00:00+00:00"


def _variant(
    product: str = "2",
    variant: str = "20",
    inventory_item: str = "200",
    *,
    title: str = "Near Mint",
    sku: str | None = "",
    barcode: str | None = None,
    price: str = "10.00",
    compare_at: str | None = "12.50",
    inventory: int = -2,
) -> CatalogVariantRecordV1:
    return CatalogVariantRecordV1(
        variant_gid=f"gid://shopify/ProductVariant/{variant}",
        product_gid=f"gid://shopify/Product/{product}",
        inventory_item_gid=f"gid://shopify/InventoryItem/{inventory_item}",
        title=title,
        sku=sku,
        barcode=barcode,
        selected_options=(
            SelectedOptionV1("Language", "Italiano"),
            SelectedOptionV1("Finish", "Foil"),
        ),
        price_text=price,
        compare_at_price_text=compare_at,
        inventory_quantity=inventory,
        inventory_policy=InventoryPolicy.DENY,
        inventory_tracked=True,
        updated_at=UPDATED,
    )


def _product(
    product: str = "2",
    *,
    handle: str | None = None,
    title: str = "Mago Élite",
    canonical: str | None = "Éclair Mage",
    status: ProductStatus = ProductStatus.ACTIVE,
    published: bool = True,
    source_id: str | None = "9007199254740993",
    game: Game | None = Game.MAGIC,
    family: ProductFamily = ProductFamily.SINGLE,
    subtype: str | None = None,
    rule_id: str | None = "family:single",
    reason: str | None = None,
    subtype_rule_id: str | None = None,
    subtype_reason: str | None = None,
    variant: CatalogVariantRecordV1 | None = None,
) -> CatalogProductRecordV1:
    return CatalogProductRecordV1(
        product_gid=f"gid://shopify/Product/{product}",
        handle=handle or f"product-{product}",
        commercial_title=title,
        canonical_card_name=canonical,
        shopify_status=status,
        online_store_published=published,
        powertools_source_id=source_id,
        sync_source_id=source_id,
        total_inventory=-2,
        tracks_inventory=True,
        updated_at=UPDATED,
        game=game,
        product_family=family,
        product_subtype=subtype,
        classification_rule_version="2026-09-01.1",
        classification_rule_id=rule_id,
        unclassified_reason=reason,
        subtype_rule_id=subtype_rule_id,
        subtype_reason=subtype_reason,
        variants=(variant or _variant(product, f"{product}0", f"{product}00"),),
    )


def _records() -> tuple[CatalogProductRecordV1, ...]:
    return (
        _product(),
        _product(
            "10",
            title="Booster Box",
            canonical=None,
            status=ProductStatus.DRAFT,
            published=False,
            family=ProductFamily.SEALED,
            subtype="booster-box",
            rule_id="family:sealed",
            subtype_rule_id="sealed:booster-box",
            variant=_variant(
                "10",
                "100",
                "1000",
                title="Default Title",
                sku="DUPLICATE-SKU",
                barcode="",
                price="120.000",
                compare_at=None,
                inventory=5,
            ),
        ),
        _product(
            "9999999999999999999999999999999999999999",
            title="Unclassified Product",
            canonical=None,
            source_id=None,
            game=None,
            family=ProductFamily.UNCLASSIFIED,
            rule_id=None,
            reason="missing_game_signal",
            variant=_variant(
                "9999999999999999999999999999999999999999",
                "99999999999999999999999999999999999999990",
                "999999999999999999999999999999999999999900",
                title="Near Mint",
                sku="DUPLICATE-SKU",
                barcode=None,
                price="0",
                compare_at=None,
                inventory=0,
            ),
        ),
    )


def _source_manifest(
    *,
    product_status_counts: tuple[tuple[str, int], ...] | None = None,
    product_count: int = 3,
    variant_count: int = 3,
    active_published: int = 2,
    source_identities: int = 2,
) -> SourceSnapshotManifest:
    line_count = product_count + variant_count
    evidence = SourceSnapshotEvidence(
        shop_domain="synthetic.myshopify.com",
        api_version="2026-07",
        operation_id="gid://shopify/BulkOperation/1",
        status="COMPLETED",
        partial_data_url_present=False,
        file_size=1234,
        object_count=line_count,
        product_count=product_count,
        expected_active_online_store_published_product_count=active_published,
        query_sha256=SHA_A,
        online_store_publication_gid="gid://shopify/Publication/1",
        completed_at="2026-09-01T01:00:00Z",
        source_code_sha="d" * 40,
    )
    object_counts = dict.fromkeys(ALLOWED_TYPES, 0)
    object_counts["Product"] = product_count
    object_counts["ProductVariant"] = variant_count
    return SourceSnapshotManifest(
        schema_version=2,
        source=evidence,
        snapshot_sha256=SHA_B,
        database_sha256=SHA_C,
        snapshot_bytes=1234,
        line_count=line_count,
        object_counts=tuple((key, object_counts[key]) for key in ALLOWED_TYPES),
        product_status_counts=product_status_counts
        or (("ACTIVE", 2), ("ARCHIVED", 0), ("DRAFT", 1), ("UNLISTED", 0)),
        verified_active_online_store_published_product_count=active_published,
        source_identity_products=source_identities,
    )


def _source_bytes(manifest: SourceSnapshotManifest) -> bytes:
    return (
        json.dumps(manifest.as_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode()


def _manifest(
    records: tuple[CatalogProductRecordV1, ...] | None = None,
) -> DatasetManifestV1:
    actual_records = records or _records()
    source = _source_manifest()
    return DatasetManifestV1.build(
        actual_records,
        source_manifest=source,
        source_manifest_bytes=_source_bytes(source),
        excluded_product_status_counts=tuple((status, 0) for status in PRODUCT_STATUSES),
        excluded_variant_count=0,
        excluded_source_identity_product_count=0,
        excluded_active_online_store_published_product_count=0,
    )


def _request(
    *,
    family: RequestFamily = RequestFamily.ALL,
    query: str | None = None,
    in_stock: bool | None = None,
    subtype: str | None = None,
    page_size: int = 2,
) -> CatalogRequestV1:
    return CatalogRequestV1(
        game=Game.MAGIC,
        product_family=family,
        query=query,
        filters=CatalogFiltersV1(in_stock=in_stock, product_subtype=subtype),
        page_size=page_size,
    )


def _cursor(
    *,
    request: CatalogRequestV1 | None = None,
    generation: str = GENERATION,
    last_product_gid: str | None = None,
    expires_at: str = EXPIRES,
) -> CursorContextV1:
    return CursorContextV1.from_request(
        request or _request(),
        generation,
        last_product_gid=last_product_gid,
        expires_at=expires_at,
    )


def _page() -> tuple[CatalogPageV1, CursorContextV1]:
    item = CatalogItemV1.from_product_record(_records()[0])
    current = _cursor()
    next_cursor = _cursor(last_product_gid=item.product_gid)
    page = CatalogPageV1(
        dataset_generation=GENERATION,
        request=current.request,
        request_context_sha256=current.request_context_sha256,
        items=(item,),
        returned_product_count=1,
        returned_variant_count=1,
        has_next_page=True,
        next_cursor_context=next_cursor,
    )
    return page, current


def _golden_objects() -> dict[str, Any]:
    records = _records()
    manifest = _manifest(records)
    request = _request()
    cursor = CursorContextV1.from_request(
        request,
        manifest.dataset_generation,
        last_product_gid=None,
        expires_at=EXPIRES,
    )
    item = CatalogItemV1.from_product_record(records[0])
    next_cursor = CursorContextV1.from_request(
        request,
        manifest.dataset_generation,
        last_product_gid=item.product_gid,
        expires_at=EXPIRES,
    )
    page = CatalogPageV1(
        dataset_generation=manifest.dataset_generation,
        request=request,
        request_context_sha256=cursor.request_context_sha256,
        items=(item,),
        returned_product_count=1,
        returned_variant_count=1,
        has_next_page=True,
        next_cursor_context=next_cursor,
    )
    error = CatalogErrorV1.for_code(
        CatalogErrorCode.INVALID_CURSOR,
        field="cursor",
        request_context_sha256=cursor.request_context_sha256,
    )
    return {
        "CatalogErrorV1": error,
        "CatalogItemV1": item,
        "CatalogPageV1": page,
        "CatalogProductRecordV1": records[0],
        "CatalogRequestV1": request,
        "CursorContextV1": cursor,
        "DatasetManifestV1": manifest,
    }


def test_happy_contract_round_trips_preserve_non_lossy_values_and_public_minimum() -> None:
    records = _records()
    manifest = _manifest(records)
    manifest.validate_records(records)
    assert manifest.source_product_count == 3
    assert manifest.included_product_count == 3
    assert manifest.classified_product_count == 2
    assert manifest.unclassified_product_count == 1
    assert manifest.source_active_online_store_published_product_count == 2
    assert manifest.included_active_online_store_published_product_count == 2
    assert manifest.public_item_count == 1
    assert manifest.included_source_identity_product_count == 2
    assert records[0].powertools_source_id == records[1].powertools_source_id
    assert records[0].variants[0].price_text == "10.00"
    assert records[0].variants[0].inventory_quantity == -2
    assert records[0].variants[0].sku == ""
    assert records[0].variants[0].barcode is None

    item = CatalogItemV1.from_product_record(records[0])
    public_variant = item.variants[0].as_dict()
    assert item.product_gid == records[0].product_gid
    assert set(public_variant) == CatalogVariantItemV1.FIELDS
    assert "inventoryItemGid" not in public_variant
    assert "sku" not in public_variant
    assert "barcode" not in public_variant
    assert "updatedAt" not in public_variant

    for dto in _golden_objects().values():
        encoded = dto.to_json_bytes()
        decoded = type(dto).from_json_bytes(encoded)
        assert decoded == dto
        assert decoded.to_json_bytes() == encoded == dto.to_json_bytes()
        assert not encoded.endswith(b"\n")


def test_taxonomy_classification_is_consumed_without_reclassification() -> None:
    variant = _variant()
    classification = Classification(
        product_gid="gid://shopify/Product/2",
        game=Game.MAGIC,
        family=ProductFamily.SINGLE,
        subtype=None,
        rule_version="2026-09-01.1",
        rule_id="family:single",
        reason=None,
    )
    record = CatalogProductRecordV1.from_classification(
        classification=classification,
        handle="exact-handle",
        commercial_title="Commercial title",
        canonical_card_name="Canonical name",
        shopify_status=ProductStatus.ACTIVE,
        online_store_published=True,
        powertools_source_id=None,
        sync_source_id=None,
        total_inventory=-1,
        tracks_inventory=True,
        updated_at=UPDATED,
        variants=(variant,),
    )
    assert record.product_family is ProductFamily.SINGLE
    assert record.classification_rule_id == "family:single"
    with pytest.raises(RuntimeContractError, match="taxonomy Classification"):
        CatalogProductRecordV1.from_classification(
            classification=object(),  # type: ignore[arg-type]
            handle="x",
            commercial_title="x",
            canonical_card_name=None,
            shopify_status=ProductStatus.DRAFT,
            online_store_published=False,
            powertools_source_id=None,
            sync_source_id=None,
            total_inventory=0,
            tracks_inventory=False,
            updated_at=UPDATED,
            variants=(variant,),
        )


def test_generation_and_manifest_bytes_are_deterministic_and_timestamp_free() -> None:
    records = _records()
    first = _manifest(records)
    second = _manifest(tuple(reversed(records)))
    assert first == second
    assert first.to_json_bytes() == second.to_json_bytes()
    assert first.dataset_generation == second.dataset_generation
    descriptor = first.generation_descriptor()
    assert descriptor["domain"] == "nla-catalog-dataset-generation-v1"
    assert "generatedAt" not in descriptor
    assert first.generated_at == "2026-09-01T01:00:00Z"

    changed = replace(records[0], commercial_title="Changed title")
    changed_manifest = _manifest((changed, *records[1:]))
    assert changed_manifest.dataset_generation != first.dataset_generation
    assert changed_manifest.catalog_content_sha256 != first.catalog_content_sha256


def test_manifest_reconciles_nonzero_excluded_accounting() -> None:
    records = _records()
    source = _source_manifest(
        product_status_counts=(
            ("ACTIVE", 2),
            ("ARCHIVED", 1),
            ("DRAFT", 1),
            ("UNLISTED", 0),
        ),
        product_count=4,
        variant_count=5,
        active_published=2,
        source_identities=3,
    )
    manifest = DatasetManifestV1.build(
        records,
        source_manifest=source,
        source_manifest_bytes=_source_bytes(source),
        excluded_product_status_counts=(
            ("ACTIVE", 0),
            ("ARCHIVED", 1),
            ("DRAFT", 0),
            ("UNLISTED", 0),
        ),
        excluded_variant_count=2,
        excluded_source_identity_product_count=1,
        excluded_active_online_store_published_product_count=0,
    )
    assert manifest.source_product_count == 4
    assert manifest.excluded_product_count == 1
    assert manifest.source_variant_count == 5
    assert manifest.excluded_variant_count == 2
    assert manifest.source_identity_product_count == 3
    _manifest_replacement_error(
        manifest,
        "included identity count cannot exceed",
        source_identity_product_count=4,
        included_source_identity_product_count=4,
        excluded_source_identity_product_count=0,
    )
    _manifest_replacement_error(
        manifest,
        "excluded identity count cannot exceed",
        source_identity_product_count=4,
        included_source_identity_product_count=2,
        excluded_source_identity_product_count=2,
    )
    _manifest_replacement_error(
        manifest,
        "excluded Variant count cannot be less",
        source_variant_count=4,
        included_variant_count=4,
        excluded_variant_count=0,
    )


def test_unlisted_and_unclassified_active_published_are_accounted_not_public() -> None:
    unlisted = _product(status=ProductStatus.UNLISTED, published=True)
    assert not unlisted.publishable
    unclassified = _records()[2]
    assert unclassified.publishable
    with pytest.raises(RuntimeContractError, match="active, published, and classified"):
        CatalogItemV1.from_product_record(unclassified)
    with pytest.raises(RuntimeContractError, match="active, published, and classified"):
        CatalogItemV1.from_product_record(unlisted)


def test_request_cursor_and_page_bind_complete_product_level_context() -> None:
    page, current = _page()
    page.validate_for_context(current)
    assert page.returned_product_count == len(page.items) == 1
    assert page.next_cursor_context is not None
    assert page.next_cursor_context.last_sort_values == (page.items[-1].product_gid,)
    assert page.next_cursor_context.last_product_gid == page.items[-1].product_gid
    assert b'"q":null' in current.to_json_bytes()
    assert b'"endpoint":"catalog"' in current.to_json_bytes()
    current.assert_matches(_request(), GENERATION)
    current.assert_not_expired("2026-09-01T01:59:59Z")
    with pytest.raises(RuntimeContractError, match="expired"):
        current.assert_not_expired(EXPIRES)

    request_fingerprints = {
        current.request_context_sha256,
        _cursor(request=_request(page_size=3)).request_context_sha256,
        _cursor(request=_request(query="x")).request_context_sha256,
        _cursor(request=_request(in_stock=True)).request_context_sha256,
        _cursor(request=_request(family=RequestFamily.SINGLE)).request_context_sha256,
        _cursor(generation=f"sha256:{SHA_B}").request_context_sha256,
    }
    assert len(request_fingerprints) == 6
    changed_expiry = _cursor(expires_at="2026-09-01T03:00:00Z")
    changed_position = _cursor(last_product_gid="gid://shopify/Product/2")
    assert changed_expiry.request_context_sha256 == current.request_context_sha256
    assert changed_position.request_context_sha256 == current.request_context_sha256
    assert changed_expiry.context_sha256 != current.context_sha256
    assert changed_position.context_sha256 != current.context_sha256


def test_provisional_capabilities_never_authorize_output_filters_search_or_codec() -> None:
    serialized = DEFAULT_CAPABILITIES_V1.as_dict()
    states = [*serialized["features"].values(), *serialized["requests"].values()]
    assert "verified" not in states
    assert set(states) == {"provisional", "unsupported"}
    assert DEFAULT_CAPABILITIES_V1.feature_state("cursorCodec") is CapabilityState.UNSUPPORTED
    assert (
        DEFAULT_CAPABILITIES_V1.request_state(Game.ONE_PIECE, RequestFamily.ACCESSORY)
        is CapabilityState.PROVISIONAL
    )
    with pytest.raises(RuntimeContractError, match="not verified"):
        _request().require_executable()
    with pytest.raises(RuntimeContractError, match="search is unsupported"):
        _request(query="Black Lotus").require_executable()
    with pytest.raises(RuntimeContractError, match="filters are not verified"):
        _request(in_stock=False).require_executable()
    with pytest.raises(RuntimeContractError, match="output capability"):
        _page()[0].require_output_capability()


def test_request_family_all_is_request_only_and_filters_are_compatible() -> None:
    assert _request().product_family is RequestFamily.ALL
    with pytest.raises(RuntimeContractError, match="supported enum"):
        CatalogRequestV1.from_dict({**_request().as_dict(), "productFamily": "unclassified"})
    with pytest.raises(RuntimeContractError, match="only compatible with sealed"):
        _request(family=RequestFamily.ALL, subtype="booster-box")
    sealed = _request(family=RequestFamily.SEALED, subtype="booster-box")
    assert sealed.filters.product_subtype == "booster-box"


def test_field_disposition_and_compatibility_matrices_are_complete_and_frozen() -> None:
    assert set(FIELD_DISPOSITIONS_V1) == {dto.__name__ for dto in SERIALIZABLE_DTOS_V1}
    for dto in SERIALIZABLE_DTOS_V1:
        assert set(FIELD_DISPOSITIONS_V1[dto.__name__]) == set(dto.FIELDS)
        assert all(
            isinstance(disposition, FieldDisposition)
            for disposition in FIELD_DISPOSITIONS_V1[dto.__name__].values()
        )
    assert COMPATIBILITY_MATRIX_V1 == {
        "additiveNullableField": "minor",
        "enumChange": "major",
        "fieldRemoval": "major",
        "fieldRename": "major",
        "nullabilityChange": "major",
        "semanticChange": "major",
        "typeChange": "major",
    }
    with pytest.raises(TypeError):
        COMPATIBILITY_MATRIX_V1["fieldRename"] = "minor"  # type: ignore[index]
    with pytest.raises(TypeError):
        FIELD_DISPOSITIONS_V1["CatalogItemV1"]["productGid"] = (  # type: ignore[index]
            FieldDisposition.NULLABLE
        )
    with pytest.raises(TypeError):
        PUBLIC_ERROR_MESSAGES_V1[CatalogErrorCode.INVALID_REQUEST] = "changed"  # type: ignore[index]


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        pytest.param(b"", "empty", id="empty"),
        pytest.param(b"\xef\xbb\xbf{}", "BOM", id="utf8-bom"),
        pytest.param(b"\xff\xfe{}", "BOM", id="utf16-bom"),
        pytest.param(b"\xfe\xff{}", "BOM", id="utf16be-bom"),
        pytest.param(b"\xff\xfe\x00\x00{}", "BOM", id="utf32le-bom"),
        pytest.param(b"\x00\x00\xfe\xff{}", "BOM", id="utf32be-bom"),
        pytest.param(b"\xff", "invalid", id="invalid-utf8"),
        pytest.param(b"[]", "root", id="nonobject-root"),
        pytest.param(b'{"game":"magic","game":"magic"}', "duplicate", id="duplicate"),
        pytest.param(b'{"pageSize":1.0}', "signed integers", id="float"),
        pytest.param(b'{"pageSize":NaN}', "non-finite", id="nan"),
        pytest.param(b'{"q":"\\ud800"}', "invalid Unicode", id="surrogate-value"),
        pytest.param(b'{"\\ud800":null}', "invalid Unicode", id="surrogate-key"),
        pytest.param(b'{"pageSize":99999999999999999999}', "signed 64-bit", id="huge-int"),
    ],
)
def test_strict_json_decoder_fails_closed(raw: bytes, message: str) -> None:
    with pytest.raises(RuntimeContractError, match=message):
        CatalogRequestV1.from_json_bytes(raw)


def test_strict_json_decoder_bounds_size_recursion_type_and_dto() -> None:
    request = _request()
    assert decode_contract(request.to_json_bytes(), CatalogRequestV1) == request
    with pytest.raises(RuntimeContractError, match="bytes"):
        CatalogRequestV1.from_json_bytes("{}")  # type: ignore[arg-type]
    with pytest.raises(RuntimeContractError, match="byte limit"):
        CatalogRequestV1.from_json_bytes(b"{" + b" " * (2 * 1024 * 1024) + b"}")
    deep = (b'{"x":' * 5000) + b"null" + (b"}" * 5000)
    with pytest.raises(RuntimeContractError):
        CatalogRequestV1.from_json_bytes(deep)
    with pytest.raises(RuntimeContractError, match="unsupported runtime contract DTO"):
        decode_contract(b"{}", dict)  # type: ignore[arg-type]

    class DictSubclass(dict):
        pass

    with pytest.raises(RuntimeContractError, match="request must be an object"):
        CatalogRequestV1.from_dict(DictSubclass(request.as_dict()))

    class ForgedKey(str):
        __hash__ = str.__hash__

        def __eq__(self, _other: object) -> bool:
            return True

        def __ne__(self, _other: object) -> bool:
            return False

    forged_key_payload = {ForgedKey(key): value for key, value in request.as_dict().items()}
    with pytest.raises(RuntimeContractError, match="missing or unknown"):
        CatalogRequestV1.from_dict(forged_key_payload)

    class ListSubclass(list):
        pass

    variant_payload = _variant().as_dict()
    variant_payload["selectedOptions"] = ListSubclass(variant_payload["selectedOptions"])
    with pytest.raises(RuntimeContractError, match="selectedOptions must be an array"):
        CatalogVariantRecordV1.from_dict(variant_payload)


def test_unknown_and_missing_fields_fail_for_every_golden_dto() -> None:
    for dto in _golden_objects().values():
        payload = dto.as_dict()
        with pytest.raises(RuntimeContractError, match="missing or unknown"):
            type(dto).from_dict({**payload, "unknownSecretField": "never echoed"})
        missing = dict(payload)
        missing.pop(next(iter(payload)))
        with pytest.raises(RuntimeContractError, match="missing or unknown"):
            type(dto).from_dict(missing)


@pytest.mark.parametrize("code", list(CatalogErrorCode))
def test_error_codes_have_fixed_secret_free_public_messages(code: CatalogErrorCode) -> None:
    error = CatalogErrorV1.for_code(code)
    assert error.message == PUBLIC_ERROR_MESSAGES_V1[code]
    assert CatalogErrorV1.from_json_bytes(error.to_json_bytes()) == error
    with pytest.raises(RuntimeContractError, match="frozen public message"):
        replace(error, message="token=attacker-controlled")


def test_golden_vectors_are_literal_bytes_and_hashes() -> None:
    fixture = json.loads(
        Path(__file__)
        .with_name("fixtures")
        .joinpath("runtime_contract_v1_golden.json")
        .read_text(encoding="utf-8")
    )
    for name, dto in _golden_objects().items():
        expected_bytes = fixture[name]["canonicalJson"].encode()
        assert dto.to_json_bytes() == expected_bytes
        assert hashlib.sha256(expected_bytes).hexdigest() == fixture[name]["sha256"]
        assert decode_contract(expected_bytes, type(dto)) == dto


def test_primitive_contract_validators_reject_lossy_or_noncanonical_values() -> None:
    with pytest.raises(RuntimeContractError, match="serializable"):
        runtime._canonical_json_bytes({"bad": {1, 2}})
    with pytest.raises(RuntimeContractError, match="serializable"):
        runtime._canonical_json_bytes({"bad": "\ud800"})
    with pytest.raises(RuntimeContractError, match="must be a string"):
        SelectedOptionV1(1, "x")  # type: ignore[arg-type]
    with pytest.raises(RuntimeContractError, match="invalid Unicode"):
        SelectedOptionV1("x", "\ud800")
    for name, value in (("", "x"), (" \t", "x"), ("x", ""), ("x", " \t")):
        with pytest.raises(RuntimeContractError, match="must be a string"):
            SelectedOptionV1(name, value)
    with pytest.raises(RuntimeContractError, match="boolean"):
        CatalogFiltersV1(in_stock=1, product_subtype=None)  # type: ignore[arg-type]
    with pytest.raises(RuntimeContractError, match="canonical subtype"):
        CatalogFiltersV1(in_stock=None, product_subtype="Booster Box")
    with pytest.raises(RuntimeContractError, match="signed 64-bit"):
        replace(_variant(), inventory_quantity=True)
    with pytest.raises(RuntimeContractError, match="signed 64-bit"):
        replace(_variant(), inventory_quantity=2**63)
    with pytest.raises(RuntimeContractError, match="decimal text"):
        replace(_variant(), price_text="10.0e0")
    with pytest.raises(RuntimeContractError, match="decimal text"):
        replace(_variant(), compare_at_price_text="-1")
    with pytest.raises(RuntimeContractError, match="canonical positive decimal"):
        replace(
            _product(status=ProductStatus.DRAFT),
            powertools_source_id="001",
            sync_source_id="001",
        )
    with pytest.raises(RuntimeContractError, match="canonical rule version"):
        replace(_product(), classification_rule_version="bad version")
    with pytest.raises(RuntimeContractError, match="canonical rule identifier"):
        replace(_product(), classification_rule_id="BAD_RULE")
    with pytest.raises(RuntimeContractError, match="machine-readable reason"):
        replace(_records()[2], unclassified_reason="Human readable")


@pytest.mark.parametrize(
    "timestamp",
    [
        "2026-09-01 01:02:03Z",
        "20260901T010203Z",
        "2026-W36-2T01:02:03Z",
        "2026-09-01t01:02:03z",
        "2026-09-01T01:02:03+01:00:30",
    ],
)
def test_timestamp_syntax_is_canonical_before_calendar_validation(timestamp: str) -> None:
    with pytest.raises(RuntimeContractError, match="canonical timezone-aware"):
        replace(_variant(), updated_at=timestamp)


def test_timestamp_calendar_validation_rejects_impossible_dates() -> None:
    with pytest.raises(RuntimeContractError, match="calendar-valid"):
        replace(_variant(), updated_at="2026-02-30T01:02:03Z")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        pytest.param("variant_gid", "gid://shopify/ProductVariant/0", "canonical", id="zero"),
        pytest.param(
            "variant_gid",
            "gid://shopify/ProductVariant/01",
            "canonical",
            id="leading-zero",
        ),
        pytest.param(
            "variant_gid",
            "gid://shopify/ProductVariant/1?x=2",
            "canonical",
            id="query",
        ),
        pytest.param("variant_gid", "gid://shopify/Product/1", "ProductVariant", id="kind"),
        pytest.param("product_gid", "gid://shopify/ProductVariant/2", "Product", id="parent-kind"),
        pytest.param(
            "inventory_item_gid", "gid://shopify/InventoryLevel/2", "InventoryItem", id="item-kind"
        ),
        pytest.param("title", "", "string", id="empty-title"),
        pytest.param("title", " \t", "string", id="whitespace-title"),
        pytest.param("sku", 1, "string", id="sku-type"),
        pytest.param("barcode", 1, "string", id="barcode-type"),
        pytest.param("selected_options", [], "tuple", id="options-list"),
        pytest.param("selected_options", (object(),), "selected option records", id="option-type"),
        pytest.param("inventory_policy", "DENY", "canonical", id="policy-type"),
        pytest.param("inventory_tracked", 1, "boolean", id="tracked-type"),
    ],
)
def test_variant_record_direct_construction_is_strict(field: str, value: Any, message: str) -> None:
    with pytest.raises(RuntimeContractError, match=message):
        replace(_variant(), **{field: value})


def test_variant_and_option_dict_shapes_are_strict() -> None:
    with pytest.raises(RuntimeContractError, match="selected option must be an object"):
        SelectedOptionV1.from_dict([])  # type: ignore[arg-type]
    with pytest.raises(RuntimeContractError, match="variant record must be an object"):
        CatalogVariantRecordV1.from_dict([])  # type: ignore[arg-type]
    with pytest.raises(RuntimeContractError, match="selectedOptions must be an array"):
        CatalogVariantRecordV1.from_dict({**_variant().as_dict(), "selectedOptions": ()})
    public = CatalogVariantItemV1.from_variant_record(_variant())
    with pytest.raises(RuntimeContractError, match="source must be a variant record"):
        CatalogVariantItemV1.from_variant_record(object())  # type: ignore[arg-type]
    with pytest.raises(RuntimeContractError, match="public catalog variant must be an object"):
        CatalogVariantItemV1.from_dict([])  # type: ignore[arg-type]
    with pytest.raises(RuntimeContractError, match="public selectedOptions must be an array"):
        CatalogVariantItemV1.from_dict({**public.as_dict(), "selectedOptions": ()})
    with pytest.raises(RuntimeContractError, match="public selectedOptions must be a tuple"):
        replace(public, selected_options=[])
    with pytest.raises(RuntimeContractError, match="selected option records"):
        replace(public, selected_options=(object(),))
    with pytest.raises(RuntimeContractError, match="canonical"):
        replace(public, inventory_policy="DENY")
    with pytest.raises(RuntimeContractError, match="must be a string"):
        replace(public, title=" \t")
    public_without_compare_at = CatalogVariantItemV1.from_variant_record(
        replace(_variant(), compare_at_price_text=None)
    )
    assert public_without_compare_at.compare_at_price_text is None


def test_product_record_direct_identity_classification_and_children_are_strict() -> None:
    base = _product()
    invalid_replacements = [
        ({"contract_version": True}, "contractVersion"),
        ({"handle": ""}, "string"),
        ({"handle": " \t"}, "string"),
        ({"commercial_title": ""}, "string"),
        ({"commercial_title": " \t"}, "string"),
        ({"shopify_status": "ACTIVE"}, "shopifyStatus"),
        ({"online_store_published": 1}, "boolean"),
        ({"sync_source_id": None}, "source IDs"),
        ({"sync_source_id": "2"}, "source IDs"),
        ({"total_inventory": False}, "signed 64-bit"),
        ({"tracks_inventory": 1}, "boolean"),
        ({"game": "magic"}, "game"),
        ({"product_family": "single"}, "persisted taxonomy"),
        ({"variants": []}, "non-empty tuple"),
        ({"variants": (object(),)}, "variant records"),
        ({"variants": (_variant("3", "30", "300"),)}, "parent Product"),
        ({"variants": (base.variants[0], base.variants[0])}, "unique within"),
    ]
    for changes, message in invalid_replacements:
        with pytest.raises(RuntimeContractError, match=message):
            replace(base, **changes)

    with pytest.raises(RuntimeContractError, match="product record must be an object"):
        CatalogProductRecordV1.from_dict([])  # type: ignore[arg-type]
    with pytest.raises(RuntimeContractError, match="variants must be an array"):
        CatalogProductRecordV1.from_dict({**base.as_dict(), "variants": ()})


def test_product_and_public_variant_order_is_canonical_without_numeric_coercion() -> None:
    huge_digits = "8" * 5_000
    first = _variant("2", "9", "901")
    huge = _variant("2", huge_digits, "9" * 5_000)
    product = replace(_product(), variants=(first, huge))
    item = CatalogItemV1.from_product_record(product)
    assert tuple(variant.variant_gid for variant in item.variants) == (
        first.variant_gid,
        huge.variant_gid,
    )
    assert CatalogProductRecordV1.from_json_bytes(product.to_json_bytes()) == product

    with pytest.raises(RuntimeContractError, match="ascending ProductVariant GID order"):
        replace(product, variants=(huge, first))
    with pytest.raises(RuntimeContractError, match="ascending ProductVariant GID order"):
        replace(item, variants=tuple(reversed(item.variants)))


def test_product_classification_state_machine_is_fail_closed() -> None:
    active_single = _product()
    with pytest.raises(RuntimeContractError, match="requires canonicalCardName"):
        replace(active_single, canonical_card_name=None)
    draft_single = replace(
        active_single,
        shopify_status=ProductStatus.DRAFT,
        online_store_published=False,
        canonical_card_name=None,
    )
    assert draft_single.canonical_card_name is None
    with pytest.raises(RuntimeContractError, match="must be a string"):
        replace(draft_single, canonical_card_name="")

    unclassified = _records()[2]
    with pytest.raises(RuntimeContractError, match="require a reason"):
        replace(unclassified, unclassified_reason=None)
    with pytest.raises(RuntimeContractError, match="require a reason"):
        replace(unclassified, classification_rule_id="family:single")
    with pytest.raises(RuntimeContractError, match="cannot carry subtype"):
        replace(unclassified, product_subtype="booster-box")

    with pytest.raises(RuntimeContractError, match="require game"):
        replace(active_single, game=None)
    with pytest.raises(RuntimeContractError, match="require game"):
        replace(active_single, classification_rule_id=None)
    with pytest.raises(RuntimeContractError, match="unclassified reason"):
        replace(active_single, unclassified_reason="missing_game_signal")
    with pytest.raises(RuntimeContractError, match="only sealed"):
        replace(active_single, product_subtype="booster-box")

    sealed = _records()[1]
    failure_advisory = replace(
        sealed,
        product_subtype=None,
        subtype_rule_id=None,
        subtype_reason="no_matching_subtype_rule",
    )
    assert failure_advisory.subtype_reason == "no_matching_subtype_rule"
    with pytest.raises(RuntimeContractError, match="present together"):
        replace(sealed, subtype_rule_id=None)
    with pytest.raises(RuntimeContractError, match="cannot carry a subtype reason"):
        replace(sealed, subtype_reason="ambiguous_subtype_match")
    with pytest.raises(RuntimeContractError, match="requires a subtype reason"):
        replace(sealed, product_subtype=None, subtype_rule_id=None)


def test_catalog_item_direct_and_parsed_shapes_are_strict() -> None:
    item = CatalogItemV1.from_product_record(_product())
    invalid = [
        ({"contract_version": False}, "contractVersion"),
        ({"handle": " \t"}, "string"),
        ({"commercial_title": ""}, "string"),
        ({"game": "magic"}, "game"),
        ({"product_family": RequestFamily.SINGLE}, "canonical ProductFamily"),
        ({"product_family": "single"}, "canonical ProductFamily"),
        ({"product_family": ProductFamily.UNCLASSIFIED}, "classified productFamily"),
        ({"product_subtype": "booster-box"}, "only sealed"),
        ({"canonical_card_name": None}, "requires canonicalCardName"),
        ({"variants": []}, "non-empty tuple"),
        ({"variants": (object(),)}, "public variant records"),
        ({"variants": (item.variants[0], item.variants[0])}, "must be unique"),
    ]
    for changes, message in invalid:
        with pytest.raises(RuntimeContractError, match=message):
            replace(item, **changes)
    with pytest.raises(RuntimeContractError, match="source must be a product record"):
        CatalogItemV1.from_product_record(object())  # type: ignore[arg-type]
    with pytest.raises(RuntimeContractError, match="catalog item must be an object"):
        CatalogItemV1.from_dict([])  # type: ignore[arg-type]
    with pytest.raises(RuntimeContractError, match="variants must be an array"):
        CatalogItemV1.from_dict({**item.as_dict(), "variants": ()})
    encoded_item = item.to_json_bytes()
    assert CatalogItemV1.from_json_bytes(encoded_item).to_json_bytes() == encoded_item


def test_filters_capability_matrix_and_request_direct_types_are_strict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(RuntimeContractError, match="filters must be an object"):
        CatalogFiltersV1.from_dict([])  # type: ignore[arg-type]
    assert CatalogFiltersV1.from_dict({"inStock": True, "productSubtype": None}).in_stock is True

    with pytest.raises(RuntimeContractError, match="cannot claim verified"):
        CapabilityMatrixV1(
            features=(("catalogItem", CapabilityState.VERIFIED),),
            requests=DEFAULT_CAPABILITIES_V1.requests,
        )
    with pytest.raises(RuntimeContractError, match="frozen v1 matrix"):
        CapabilityMatrixV1(features=(), requests=DEFAULT_CAPABILITIES_V1.requests)
    malformed_capabilities = (
        {"features": []},
        {"features": (("catalogItem",),)},
        {"features": (("", CapabilityState.PROVISIONAL),)},
        {"features": (("catalogItem", "provisional"),)},
        {"requests": [("magic/all", CapabilityState.PROVISIONAL)]},
    )
    for changes in malformed_capabilities:
        with pytest.raises(RuntimeContractError, match="capability matrix"):
            replace(DEFAULT_CAPABILITIES_V1, **changes)

    class ForgedTuple(tuple):
        def __eq__(self, _other: object) -> bool:
            return True

        def __ne__(self, _other: object) -> bool:
            return False

    forged_features = ForgedTuple((("forgedFeature", CapabilityState.UNSUPPORTED),))
    forged_requests = ForgedTuple((("forged/request", CapabilityState.UNSUPPORTED),))
    with pytest.raises(RuntimeContractError, match="immutable tuple"):
        CapabilityMatrixV1(features=forged_features, requests=forged_requests)
    forged_pair = ForgedTuple(("catalogItem", CapabilityState.PROVISIONAL))
    with pytest.raises(RuntimeContractError, match="entries must be pairs"):
        CapabilityMatrixV1(
            features=(forged_pair,),
            requests=DEFAULT_CAPABILITIES_V1.requests,
        )
    with pytest.raises(RuntimeContractError, match="matrix must be an object"):
        CapabilityMatrixV1.from_dict([])  # type: ignore[arg-type]
    with pytest.raises(RuntimeContractError, match="frozen v1 matrix"):
        CapabilityMatrixV1.from_dict({**DEFAULT_CAPABILITIES_V1.as_dict(), "features": {}})
    with pytest.raises(RuntimeContractError, match="unknown capability feature"):
        DEFAULT_CAPABILITIES_V1.feature_state("unknown")
    with pytest.raises(RuntimeContractError, match="must be a string"):
        DEFAULT_CAPABILITIES_V1.feature_state(1)  # type: ignore[arg-type]
    with pytest.raises(RuntimeContractError, match="canonical enums"):
        DEFAULT_CAPABILITIES_V1.request_state("magic", RequestFamily.ALL)  # type: ignore[arg-type]
    with pytest.raises(RuntimeContractError, match="canonical enums"):
        DEFAULT_CAPABILITIES_V1.request_state(Game.MAGIC, "all")  # type: ignore[arg-type]

    base = _request()
    invalid = [
        ({"contract_version": True}, "contractVersion"),
        ({"game": "magic"}, "game"),
        ({"product_family": "all"}, "productFamily"),
        ({"filters": {}}, "CatalogFiltersV1"),
        ({"page_size": 0}, "positive"),
        ({"page_size": 101}, "between 1 and 100"),
        ({"sort": "title_asc"}, "product_gid_asc"),
    ]
    for changes, message in invalid:
        with pytest.raises(RuntimeContractError, match=message):
            replace(base, **changes)

    class ForgedSort(str):
        def __eq__(self, _other: object) -> bool:
            return True

        def __ne__(self, _other: object) -> bool:
            return False

    with pytest.raises(RuntimeContractError, match="sort must be a string"):
        replace(base, sort=ForgedSort("title_asc"))
    cursor = _cursor(request=base)
    assert CursorContextV1.from_json_bytes(cursor.to_json_bytes()).to_json_bytes() == (
        cursor.to_json_bytes()
    )
    with pytest.raises(RuntimeContractError, match="request must be an object"):
        CatalogRequestV1.from_dict([])  # type: ignore[arg-type]
    with pytest.raises(RuntimeContractError, match="canonical enum string"):
        CatalogRequestV1.from_dict({**base.as_dict(), "game": 1})

    class UnsupportedMatrix:
        @staticmethod
        def request_state(_game: Game, _family: RequestFamily) -> CapabilityState:
            return CapabilityState.UNSUPPORTED

    monkeypatch.setattr(runtime, "DEFAULT_CAPABILITIES_V1", UnsupportedMatrix())
    with pytest.raises(RuntimeContractError, match="combination is unsupported"):
        CatalogRequestV1(
            game=Game.MAGIC,
            product_family=RequestFamily.ALL,
            query=None,
            filters=CatalogFiltersV1(None, None),
            page_size=2,
        )


def test_verified_execution_path_still_requires_output_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request()

    class VerifiedRequestOnly:
        @staticmethod
        def request_state(_game: Game, _family: RequestFamily) -> CapabilityState:
            return CapabilityState.VERIFIED

        @staticmethod
        def feature_state(_feature: str) -> CapabilityState:
            return CapabilityState.UNSUPPORTED

    monkeypatch.setattr(runtime, "DEFAULT_CAPABILITIES_V1", VerifiedRequestOnly())
    with pytest.raises(RuntimeContractError, match="output capability"):
        request.require_executable()

    class FullyVerified(VerifiedRequestOnly):
        @staticmethod
        def feature_state(_feature: str) -> CapabilityState:
            return CapabilityState.VERIFIED

    monkeypatch.setattr(runtime, "DEFAULT_CAPABILITIES_V1", FullyVerified())
    request.require_executable()
    _page()[0].require_output_capability()


def test_cursor_direct_parse_match_and_expiry_contracts_are_strict() -> None:
    cursor = _cursor()
    invalid = [
        ({"contract_version": False}, "contractVersion"),
        ({"cursor_version": 2}, "cursorVersion"),
        ({"dataset_generation": SHA_A}, "content generation"),
        ({"endpoint": "catalog"}, "endpoint"),
        ({"request": object()}, "CatalogRequestV1"),
        ({"last_sort_values": []}, "tuple of strings"),
        ({"last_sort_values": (1,)}, "tuple of strings"),
        ({"last_sort_values": ("gid://shopify/Product/2",)}, "exactly bind"),
    ]
    for changes, message in invalid:
        with pytest.raises(RuntimeContractError, match=message):
            replace(cursor, **changes)
    positioned = _cursor(last_product_gid="gid://shopify/Product/2")
    with pytest.raises(RuntimeContractError, match="exactly bind"):
        replace(positioned, last_sort_values=())
    with pytest.raises(RuntimeContractError, match="canonical Shopify Product"):
        _cursor(last_product_gid="gid://shopify/ProductVariant/2")
    with pytest.raises(RuntimeContractError, match="cursor context must be an object"):
        CursorContextV1.from_dict([])  # type: ignore[arg-type]
    with pytest.raises(RuntimeContractError, match="lastSortValues must be an array"):
        CursorContextV1.from_dict({**cursor.as_dict(), "lastSortValues": ()})
    with pytest.raises(RuntimeContractError, match="must be a string"):
        CursorContextV1.from_dict({**cursor.as_dict(), "lastSortValues": [1]})
    with pytest.raises(RuntimeContractError, match="request context does not match"):
        cursor.assert_matches(_request(page_size=3), GENERATION)
    with pytest.raises(RuntimeContractError, match="generation does not match"):
        cursor.assert_matches(_request(), f"sha256:{SHA_B}")

    class ForgedRequest(CatalogRequestV1):
        def __eq__(self, _other: object) -> bool:
            return True

        def __ne__(self, _other: object) -> bool:
            return False

    forged_request = ForgedRequest(
        game=Game.POKEMON,
        product_family=RequestFamily.ACCESSORY,
        query="forged-query",
        filters=CatalogFiltersV1(in_stock=None, product_subtype=None),
        page_size=99,
    )
    assert forged_request.game is not cursor.request.game
    assert forged_request.page_size != cursor.request.page_size
    with pytest.raises(RuntimeContractError, match="must be CatalogRequestV1"):
        cursor.assert_matches(forged_request, GENERATION)
    with pytest.raises(RuntimeContractError, match="must be CatalogRequestV1"):
        runtime._request_context_dict(GENERATION, forged_request)
    with pytest.raises(RuntimeContractError, match="unsupported runtime contract DTO"):
        forged_request.to_json_bytes()
    request_bytes = cursor.request.to_json_bytes()
    with pytest.raises(RuntimeContractError, match="unsupported runtime contract DTO"):
        ForgedRequest.from_json_bytes(request_bytes)
    with pytest.raises(RuntimeContractError, match="unsupported runtime contract DTO"):
        decode_contract(request_bytes, ForgedRequest)

    class ForgedGeneration(str):
        def __eq__(self, _other: object) -> bool:
            return True

        def __ne__(self, _other: object) -> bool:
            return False

    forged_generation = ForgedGeneration(f"sha256:{SHA_B}")
    with pytest.raises(RuntimeContractError, match="must be a string"):
        cursor.assert_matches(_request(), forged_generation)


def test_cursor_expiry_comparison_is_lossless_and_requires_known_offsets() -> None:
    precise = _cursor(expires_at="2026-09-01T02:00:00.0000001Z")
    precise.assert_not_expired("2026-09-01T02:00:00.0000000Z")
    with pytest.raises(RuntimeContractError, match="expired"):
        precise.assert_not_expired("2026-09-01T02:00:00.00000010Z")
    with pytest.raises(RuntimeContractError, match="expired"):
        precise.assert_not_expired("2026-09-01T02:00:00.0000002Z")

    offset = _cursor(expires_at="2026-09-01T02:00:00+01:00")
    with pytest.raises(RuntimeContractError, match="expired"):
        offset.assert_not_expired("2026-09-01T01:00:00Z")
    with pytest.raises(RuntimeContractError, match="known timezone offset"):
        _cursor(expires_at="2026-09-01T02:00:00-00:00")
    with pytest.raises(RuntimeContractError, match="known timezone offset"):
        precise.assert_not_expired("2026-09-01T01:00:00-00:00")

    lower_boundary = _cursor(expires_at="0001-01-01T00:00:00+23:59")
    with pytest.raises(RuntimeContractError, match="expired"):
        lower_boundary.assert_not_expired("0001-01-01T00:00:00+23:59")
    upper_boundary = _cursor(expires_at="9999-12-31T23:59:59-23:59")
    upper_boundary.assert_not_expired("9999-12-31T23:59:58-23:59")

    producer_timestamp = replace(_variant(), updated_at="2026-09-01T01:02:03-00:00")
    assert producer_timestamp.updated_at.endswith("-00:00")


def test_page_direct_parse_context_and_leakage_contracts_are_strict() -> None:
    page, current = _page()
    assert current.endpoint is CatalogEndpoint.CATALOG
    item = page.items[0]
    terminal = replace(
        page,
        has_next_page=False,
        next_cursor_context=None,
    )
    terminal.validate_for_context(current)
    assert terminal.as_dict()["nextCursorContext"] is None

    class ForgedCatalogItem(CatalogItemV1):
        def as_dict(self) -> dict[str, Any]:
            return {"forged": True}

    forged_item = ForgedCatalogItem(*(getattr(item, name) for name in CatalogItemV1.__match_args__))
    with pytest.raises(RuntimeContractError, match="CatalogItemV1"):
        replace(terminal, items=(forged_item,))

    invalid = [
        ({"contract_version": False}, "contractVersion"),
        ({"request": object()}, "request must be"),
        ({"request_context_sha256": SHA_A}, "must bind its request"),
        ({"items": []}, "items must be a tuple"),
        ({"items": (object(),)}, "CatalogItemV1"),
        ({"items": (item, item)}, "Product GIDs must be unique"),
        ({"returned_product_count": 2}, "Product item count"),
        ({"returned_variant_count": 2}, "nested variant count"),
        ({"has_next_page": 1}, "boolean"),
        ({"has_next_page": False}, "match nextCursorContext"),
        ({"next_cursor_context": None}, "match nextCursorContext"),
    ]
    for changes, message in invalid:
        with pytest.raises(RuntimeContractError, match=message):
            replace(page, **changes)

    item10 = CatalogItemV1.from_product_record(
        _product("10", handle="p10", variant=_variant("10", "100", "1000"))
    )
    with pytest.raises(RuntimeContractError, match="handles must be unique"):
        replace(
            terminal,
            items=(item, replace(item10, handle=item.handle)),
            returned_product_count=2,
            returned_variant_count=2,
        )
    duplicate_page_variant = replace(
        item10,
        variants=(replace(item10.variants[0], variant_gid=item.variants[0].variant_gid),),
    )
    with pytest.raises(RuntimeContractError, match="Variant GIDs must be unique"):
        replace(
            terminal,
            items=(item, duplicate_page_variant),
            returned_product_count=2,
            returned_variant_count=2,
        )
    unordered = (item10, item)
    with pytest.raises(RuntimeContractError, match="ascending Product GID"):
        replace(
            terminal,
            items=unordered,
            returned_product_count=2,
            returned_variant_count=2,
        )
    with pytest.raises(RuntimeContractError, match="bound pageSize"):
        replace(
            terminal,
            request=_request(page_size=1),
            request_context_sha256=_cursor(request=_request(page_size=1)).request_context_sha256,
            items=(item, item10),
            returned_product_count=2,
            returned_variant_count=2,
        )
    pokemon_item = replace(item, game=Game.POKEMON)
    with pytest.raises(RuntimeContractError, match="requested game"):
        replace(terminal, items=(pokemon_item,))
    sealed_request = _request(family=RequestFamily.SEALED)
    with pytest.raises(RuntimeContractError, match="requested family"):
        replace(
            terminal,
            request=sealed_request,
            request_context_sha256=_cursor(request=sealed_request).request_context_sha256,
        )

    with pytest.raises(RuntimeContractError, match="non-terminal"):
        replace(page, items=(), returned_product_count=0, returned_variant_count=0)
    with pytest.raises(RuntimeContractError, match="nextCursorContext must be"):
        replace(page, next_cursor_context=object())
    with pytest.raises(RuntimeContractError, match="page dataset generation"):
        replace(
            page,
            dataset_generation=f"sha256:{SHA_B}",
            request_context_sha256=_cursor(generation=f"sha256:{SHA_B}").request_context_sha256,
        )
    different_request = _request(page_size=3)
    different_cursor = _cursor(request=different_request, last_product_gid=item.product_gid)
    with pytest.raises(RuntimeContractError, match=r"page request context|page request"):
        replace(page, next_cursor_context=different_cursor)
    wrong_last = _cursor(last_product_gid="gid://shopify/Product/3")
    with pytest.raises(RuntimeContractError, match="final Product GID"):
        replace(page, next_cursor_context=wrong_last)

    with pytest.raises(RuntimeContractError, match="page context must be"):
        page.validate_for_context(object())  # type: ignore[arg-type]
    with pytest.raises(RuntimeContractError, match="generations must match"):
        page.validate_for_context(_cursor(generation=f"sha256:{SHA_B}"))
    with pytest.raises(RuntimeContractError, match="request contexts must match"):
        page.validate_for_context(_cursor(request=_request(page_size=3)))
    after_same = _cursor(last_product_gid=item.product_gid)
    with pytest.raises(RuntimeContractError, match="begin after"):
        terminal.validate_for_context(after_same)
    after_one = _cursor(last_product_gid="gid://shopify/Product/1")
    terminal.validate_for_context(after_one)
    with pytest.raises(RuntimeContractError, match="complete request context"):
        page.validate_for_context(replace(current, expires_at="2026-09-01T03:00:00Z"))

    with pytest.raises(RuntimeContractError, match="catalog page must be an object"):
        CatalogPageV1.from_dict([])  # type: ignore[arg-type]
    with pytest.raises(RuntimeContractError, match="items must be an array"):
        CatalogPageV1.from_dict({**page.as_dict(), "items": ()})
    with pytest.raises(RuntimeContractError, match="object or null"):
        CatalogPageV1.from_dict({**page.as_dict(), "nextCursorContext": []})


def test_error_direct_and_parsed_shapes_are_strict() -> None:
    error = CatalogErrorV1.for_code(CatalogErrorCode.INVALID_REQUEST)
    with pytest.raises(RuntimeContractError, match="contractVersion"):
        replace(error, contract_version=True)
    with pytest.raises(RuntimeContractError, match="code must be canonical"):
        replace(error, code="invalid_request")
    with pytest.raises(RuntimeContractError, match="canonical path"):
        replace(error, field="bad-field")
    with pytest.raises(RuntimeContractError, match="canonical path"):
        replace(error, field="x" * 129)
    for field in ("a.", "a..b", "a.1"):
        with pytest.raises(RuntimeContractError, match="canonical path"):
            replace(error, field=field)
    with pytest.raises(RuntimeContractError, match="lowercase SHA"):
        replace(error, request_context_sha256="A" * 64)
    with pytest.raises(RuntimeContractError, match="code must be canonical"):
        CatalogErrorV1.for_code("invalid_request")  # type: ignore[arg-type]
    with pytest.raises(RuntimeContractError, match="catalog error must be an object"):
        CatalogErrorV1.from_dict([])  # type: ignore[arg-type]


def test_dataset_identity_rejects_only_true_identity_and_parent_collisions() -> None:
    records = _records()
    runtime._validate_records(records)
    invalid = [
        ([], "non-empty tuple"),
        ((object(),), "contain product records"),
        ((records[0], records[0]), "Product GIDs"),
        ((records[0], replace(records[1], handle=records[0].handle)), "handles"),
        (
            (
                records[0],
                replace(records[1], classification_rule_version="2026-09-01.2"),
            ),
            "one taxonomy rule version",
        ),
        (
            (
                records[0],
                replace(
                    records[1],
                    variants=(
                        replace(
                            records[1].variants[0],
                            variant_gid=records[0].variants[0].variant_gid,
                        ),
                    ),
                ),
            ),
            "ProductVariant GIDs",
        ),
        (
            (
                records[0],
                replace(
                    records[1],
                    variants=(
                        replace(
                            records[1].variants[0],
                            inventory_item_gid=records[0].variants[0].inventory_item_gid,
                        ),
                    ),
                ),
            ),
            "InventoryItem GIDs",
        ),
    ]
    for candidate, message in invalid:
        with pytest.raises(RuntimeContractError, match=message):
            runtime._validate_records(candidate)  # type: ignore[arg-type]

    duplicate_commercial_values = (
        records[0],
        replace(
            records[1],
            commercial_title=records[0].commercial_title,
            powertools_source_id=records[0].powertools_source_id,
            sync_source_id=records[0].sync_source_id,
            variants=(
                replace(
                    records[1].variants[0],
                    title=records[0].variants[0].title,
                    sku=records[0].variants[0].sku,
                    barcode=records[0].variants[0].barcode,
                ),
            ),
        ),
        records[2],
    )
    runtime._validate_records(duplicate_commercial_values)


def test_unbounded_gid_order_uses_decimal_text_without_integer_coercion() -> None:
    huge_digits = "9" * 5000
    huge = _product(
        huge_digits,
        handle="huge",
        variant=_variant(huge_digits, huge_digits + "1", huge_digits + "2"),
    )
    two = CatalogItemV1.from_product_record(_product())
    ten = CatalogItemV1.from_product_record(
        _product("10", handle="ten", variant=_variant("10", "100", "1000"))
    )
    huge_item = CatalogItemV1.from_product_record(huge)
    request = _request(page_size=3)
    context = _cursor(request=request)
    page = CatalogPageV1(
        dataset_generation=GENERATION,
        request=request,
        request_context_sha256=context.request_context_sha256,
        items=(two, ten, huge_item),
        returned_product_count=3,
        returned_variant_count=3,
        has_next_page=False,
        next_cursor_context=None,
    )
    page.validate_for_context(context)
    assert page.items[-1].product_gid.endswith(huge_digits)


def _manifest_replacement_error(manifest: DatasetManifestV1, message: str, **changes: Any) -> None:
    with pytest.raises(RuntimeContractError, match=message):
        replace(manifest, **changes)


def test_manifest_direct_accounting_equations_are_fail_closed() -> None:
    manifest = _manifest()
    _manifest_replacement_error(manifest, "contractVersion", contract_version=True)
    _manifest_replacement_error(
        manifest,
        "schema version",
        source_snapshot_manifest_schema_version=1,
    )
    _manifest_replacement_error(manifest, "lowercase SHA", source_snapshot_manifest_sha256="A" * 64)
    _manifest_replacement_error(
        manifest, "canonical rule version", taxonomy_rule_version="bad version"
    )
    _manifest_replacement_error(manifest, "content generation", dataset_generation=SHA_A)
    _manifest_replacement_error(
        manifest, "canonical timezone-aware", generated_at="2026-09-01 01:00:00Z"
    )
    _manifest_replacement_error(manifest, "non-negative", source_product_count=-1)
    _manifest_replacement_error(
        manifest,
        "source Product count must be positive",
        source_product_count=0,
    )
    _manifest_replacement_error(
        manifest,
        "included Product count must be positive",
        included_product_count=0,
    )
    _manifest_replacement_error(
        manifest,
        "immutable count tuple",
        source_product_status_counts=list(manifest.source_product_status_counts),
    )
    _manifest_replacement_error(
        manifest,
        "frozen keys",
        source_product_status_counts=tuple(reversed(manifest.source_product_status_counts)),
    )

    class ForgedCountKey(str):
        def __eq__(self, _other: object) -> bool:
            return True

        def __ne__(self, _other: object) -> bool:
            return False

    forged_status_keys = tuple(
        (ForgedCountKey(key), count) for key, count in manifest.source_product_status_counts
    )
    _manifest_replacement_error(
        manifest,
        "frozen keys",
        source_product_status_counts=forged_status_keys,
    )
    negative_statuses = list(manifest.source_product_status_counts)
    negative_statuses[0] = ("ACTIVE", -1)
    _manifest_replacement_error(
        manifest,
        "non-negative",
        source_product_status_counts=tuple(negative_statuses),
    )
    _manifest_replacement_error(manifest, "source products", source_product_count=4)
    _manifest_replacement_error(
        manifest,
        "source status counts",
        source_product_status_counts=(
            ("ACTIVE", 1),
            ("ARCHIVED", 0),
            ("DRAFT", 1),
            ("UNLISTED", 0),
        ),
    )
    _manifest_replacement_error(
        manifest,
        "included status counts",
        included_product_status_counts=(
            ("ACTIVE", 1),
            ("ARCHIVED", 0),
            ("DRAFT", 1),
            ("UNLISTED", 0),
        ),
    )
    _manifest_replacement_error(
        manifest,
        "excluded status counts",
        excluded_product_status_counts=(
            ("ACTIVE", 0),
            ("ARCHIVED", 1),
            ("DRAFT", 0),
            ("UNLISTED", 0),
        ),
    )
    _manifest_replacement_error(
        manifest,
        "included plus excluded counts",
        included_product_status_counts=(
            ("ACTIVE", 1),
            ("ARCHIVED", 1),
            ("DRAFT", 1),
            ("UNLISTED", 0),
        ),
    )
    _manifest_replacement_error(
        manifest,
        "classified plus unclassified",
        classified_product_count=1,
    )
    _manifest_replacement_error(
        manifest,
        "family counts must equal",
        product_family_counts=(
            ("single", 0),
            ("sealed", 1),
            ("accessory", 0),
            ("unclassified", 1),
        ),
    )
    _manifest_replacement_error(
        manifest,
        "unclassified family count",
        product_family_counts=(
            ("single", 1),
            ("sealed", 0),
            ("accessory", 1),
            ("unclassified", 1),
        ),
        unclassified_product_count=0,
        classified_product_count=3,
    )
    _manifest_replacement_error(
        manifest,
        "source Variant count",
        source_variant_count=4,
    )
    _manifest_replacement_error(
        manifest,
        "source Variant count cannot be less",
        source_variant_count=2,
        included_variant_count=2,
    )
    _manifest_replacement_error(
        manifest,
        "included Variant count cannot be less",
        included_variant_count=2,
        excluded_variant_count=1,
    )
    _manifest_replacement_error(
        manifest,
        "source source identity count",
        source_identity_product_count=3,
    )
    _manifest_replacement_error(
        manifest,
        "source active published Product count",
        source_active_online_store_published_product_count=3,
    )
    _manifest_replacement_error(
        manifest,
        "identity count cannot exceed",
        source_identity_product_count=4,
        included_source_identity_product_count=4,
    )
    _manifest_replacement_error(
        manifest,
        "source active published count cannot exceed",
        source_active_online_store_published_product_count=3,
        included_active_online_store_published_product_count=3,
    )
    _manifest_replacement_error(
        manifest,
        "public item count cannot exceed",
        public_item_count=3,
    )
    _manifest_replacement_error(
        manifest,
        "classified included products",
        classified_product_count=1,
        unclassified_product_count=2,
        product_family_counts=(
            ("single", 1),
            ("sealed", 0),
            ("accessory", 0),
            ("unclassified", 2),
        ),
        public_item_count=2,
    )
    _manifest_replacement_error(
        manifest,
        "active-published/classified intersection",
        public_item_count=0,
    )
    _manifest_replacement_error(
        manifest,
        "CapabilityMatrixV1",
        capability_matrix=object(),
    )
    _manifest_replacement_error(
        manifest,
        "content-derived identity",
        dataset_generation=f"sha256:{SHA_C}",
    )


def test_manifest_included_and_excluded_active_limits_are_independent() -> None:
    records = _records()
    source = _source_manifest(
        product_status_counts=(
            ("ACTIVE", 3),
            ("ARCHIVED", 0),
            ("DRAFT", 1),
            ("UNLISTED", 0),
        ),
        product_count=4,
        variant_count=4,
        active_published=3,
        source_identities=2,
    )
    base = DatasetManifestV1.build(
        records,
        source_manifest=source,
        source_manifest_bytes=_source_bytes(source),
        excluded_product_status_counts=(
            ("ACTIVE", 1),
            ("ARCHIVED", 0),
            ("DRAFT", 0),
            ("UNLISTED", 0),
        ),
        excluded_variant_count=1,
        excluded_source_identity_product_count=0,
        excluded_active_online_store_published_product_count=1,
    )
    _manifest_replacement_error(
        base,
        "included active published count cannot exceed",
        included_active_online_store_published_product_count=3,
        excluded_active_online_store_published_product_count=0,
    )

    included_active_three = (
        ("ACTIVE", 3),
        ("ARCHIVED", 0),
        ("DRAFT", 0),
        ("UNLISTED", 0),
    )
    excluded_draft = (
        ("ACTIVE", 0),
        ("ARCHIVED", 0),
        ("DRAFT", 1),
        ("UNLISTED", 0),
    )
    _manifest_replacement_error(
        base,
        "excluded active published count cannot exceed",
        included_product_status_counts=included_active_three,
        excluded_product_status_counts=excluded_draft,
        included_active_online_store_published_product_count=2,
        excluded_active_online_store_published_product_count=1,
    )


def test_manifest_dict_shapes_and_record_revalidation_are_strict() -> None:
    manifest = _manifest()
    with pytest.raises(RuntimeContractError, match="manifest must be an object"):
        DatasetManifestV1.from_dict([])  # type: ignore[arg-type]
    payload = manifest.as_dict()
    with pytest.raises(RuntimeContractError, match="must be an object"):
        DatasetManifestV1.from_dict({**payload, "productFamilyCounts": []})
    with pytest.raises(RuntimeContractError, match="missing or unknown"):
        DatasetManifestV1.from_dict({**payload, "productFamilyCounts": {"single": 1}})

    records = _records()
    with pytest.raises(RuntimeContractError, match="included Product count"):
        manifest.validate_records(records[:2])

    extra_variant = replace(
        records[0].variants[0],
        variant_gid="gid://shopify/ProductVariant/21",
        inventory_item_gid="gid://shopify/InventoryItem/201",
    )
    with pytest.raises(RuntimeContractError, match="included Variant count"):
        manifest.validate_records(
            (replace(records[0], variants=(*records[0].variants, extra_variant)), *records[1:])
        )
    with pytest.raises(RuntimeContractError, match="source identity count"):
        manifest.validate_records(
            (
                replace(records[0], powertools_source_id=None, sync_source_id=None),
                *records[1:],
            )
        )
    with pytest.raises(RuntimeContractError, match="family count"):
        manifest.validate_records(
            (
                records[0],
                replace(
                    records[1],
                    product_family=ProductFamily.ACCESSORY,
                    product_subtype=None,
                    subtype_rule_id=None,
                    subtype_reason=None,
                ),
                records[2],
            )
        )
    with pytest.raises(RuntimeContractError, match="status count"):
        manifest.validate_records(
            (replace(records[0], shopify_status=ProductStatus.ARCHIVED), *records[1:])
        )
    with pytest.raises(RuntimeContractError, match="active published count"):
        manifest.validate_records((replace(records[0], online_store_published=False), *records[1:]))
    with pytest.raises(RuntimeContractError, match="public item count"):
        shifted_publication = (
            records[0],
            replace(
                records[1],
                shopify_status=ProductStatus.ACTIVE,
                online_store_published=True,
            ),
            replace(
                records[2],
                shopify_status=ProductStatus.DRAFT,
                online_store_published=False,
            ),
        )
        manifest.validate_records(shifted_publication)
    with pytest.raises(RuntimeContractError, match="taxonomy rule version"):
        changed_rule_records = tuple(
            replace(record, classification_rule_version="2026-09-01.2") for record in records
        )
        manifest.validate_records(changed_rule_records)
    with pytest.raises(RuntimeContractError, match="content hash"):
        manifest.validate_records((replace(records[0], commercial_title="Changed"), *records[1:]))


def _build_with_source(
    source: SourceSnapshotManifest | object,
    *,
    raw: bytes | None = None,
    excluded_statuses: tuple[tuple[str, int], ...] | None = None,
    excluded_variants: int = 0,
    excluded_identities: int = 0,
    excluded_active_published: int = 0,
) -> DatasetManifestV1:
    assert isinstance(source, SourceSnapshotManifest) or raw is not None
    source_bytes = _source_bytes(source) if raw is None else raw  # type: ignore[arg-type]
    return DatasetManifestV1.build(
        _records(),
        source_manifest=source,  # type: ignore[arg-type]
        source_manifest_bytes=source_bytes,
        excluded_product_status_counts=excluded_statuses
        or tuple((status, 0) for status in PRODUCT_STATUSES),
        excluded_variant_count=excluded_variants,
        excluded_source_identity_product_count=excluded_identities,
        excluded_active_online_store_published_product_count=excluded_active_published,
    )


def test_source_manifest_reference_requires_exact_persisted_bytes_and_valid_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _source_manifest()
    with pytest.raises(RuntimeContractError, match="must be SourceSnapshotManifest"):
        _build_with_source(object(), raw=b"{}")

    class ForgedManifest(SourceSnapshotManifest):
        def as_dict(self) -> dict[str, Any]:
            payload = super().as_dict()
            payload["snapshotSha256"] = "e" * 64
            return payload

    forged_manifest = ForgedManifest(
        *(getattr(source, name) for name in SourceSnapshotManifest.__match_args__)
    )
    forged_bytes = (
        json.dumps(forged_manifest.as_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode()
    with pytest.raises(RuntimeContractError, match="must be SourceSnapshotManifest"):
        _build_with_source(forged_manifest, raw=forged_bytes)

    with pytest.raises(RuntimeContractError, match="must be SourceSnapshotEvidence"):
        _build_with_source(
            replace(source, source=object()),
            raw=_source_bytes(source),
        )

    class EvidenceSubclass(SourceSnapshotEvidence):
        pass

    subclass_evidence = EvidenceSubclass(
        *(getattr(source.source, name) for name in SourceSnapshotEvidence.__match_args__)
    )
    with pytest.raises(RuntimeContractError, match="must be SourceSnapshotEvidence"):
        _build_with_source(
            replace(source, source=subclass_evidence),
            raw=_source_bytes(source),
        )

    canonical_source_bytes = _source_bytes(source)

    class ForgedBytes(bytes):
        def decode(self, encoding: str = "utf-8", errors: str = "strict") -> str:
            return canonical_source_bytes.decode(encoding, errors)

        def __ne__(self, _other: object) -> bool:
            return False

    forged_bytes_input = ForgedBytes(b"evil")
    assert bytes(forged_bytes_input) == b"evil"
    assert forged_bytes_input.decode() == canonical_source_bytes.decode()
    with pytest.raises(RuntimeContractError, match="input must be bytes"):
        _build_with_source(source, raw=forged_bytes_input)

    class ForgedStatus(str):
        def __eq__(self, _other: object) -> bool:
            return True

        def __ne__(self, _other: object) -> bool:
            return False

    forged_status_source = replace(
        source,
        source=replace(source.source, status=ForgedStatus("RUNNING")),
    )
    with pytest.raises(RuntimeContractError, match="must be a string"):
        _build_with_source(
            forged_status_source,
            raw=_source_bytes(forged_status_source),
        )

    with pytest.raises(RuntimeContractError, match="byte limit"):
        _build_with_source(source, raw=b"{" + b" " * (64 * 1024) + b"}")
    compact = json.dumps(source.as_dict(), sort_keys=True).encode()
    with pytest.raises(RuntimeContractError, match="canonical #5 renderer"):
        _build_with_source(source, raw=compact)
    duplicate = b'{"schemaVersion":2,"schemaVersion":2}'
    with pytest.raises(RuntimeContractError, match="duplicate key"):
        _build_with_source(source, raw=duplicate)
    with pytest.raises(RuntimeContractError, match="duplicate key"):
        _build_with_source(replace(source, snapshot_sha256="\ud800"), raw=duplicate)
    with pytest.raises(RuntimeContractError, match="invalid Unicode"):
        _build_with_source(
            replace(source, snapshot_sha256="\ud800"),
            raw=_source_bytes(source),
        )

    valid_source_bytes = _source_bytes(source)
    with monkeypatch.context() as renderer_patch:
        renderer_patch.setattr(
            SourceSnapshotManifest,
            "as_dict",
            lambda _manifest: {"invalid": "\ud800"},
        )
        with pytest.raises(RuntimeContractError, match="cannot be rendered canonically"):
            _build_with_source(source, raw=valid_source_bytes)

    invalid_evidence = replace(source.source, status="RUNNING")
    invalid_source = replace(source, source=invalid_evidence)
    with pytest.raises(RuntimeContractError, match="evidence is invalid"):
        _build_with_source(invalid_source)
    with pytest.raises(RuntimeContractError, match="schema version"):
        _build_with_source(replace(source, schema_version=1))
    with pytest.raises(RuntimeContractError, match="schema version"):
        _build_with_source(replace(source, schema_version=True))
    with pytest.raises(RuntimeContractError, match="lowercase SHA"):
        _build_with_source(replace(source, snapshot_sha256="A" * 64))
    with pytest.raises(RuntimeContractError, match="lowercase SHA"):
        _build_with_source(replace(source, database_sha256="A" * 64))
    with pytest.raises(RuntimeContractError, match="must be positive"):
        _build_with_source(replace(source, snapshot_bytes=0))
    with pytest.raises(RuntimeContractError, match="evidence fileSize"):
        _build_with_source(replace(source, snapshot_bytes=1235))
    with pytest.raises(RuntimeContractError, match="must be positive"):
        _build_with_source(replace(source, line_count=0))
    with pytest.raises(RuntimeContractError, match="evidence objectCount"):
        _build_with_source(replace(source, line_count=7))


def test_source_manifest_internal_counts_are_independently_validated() -> None:
    source = _source_manifest()
    counts = dict(source.object_counts)
    counts["Metafield"] = 1
    with pytest.raises(RuntimeContractError, match="object counts must equal"):
        _build_with_source(
            replace(
                source,
                object_counts=tuple((key, counts[key]) for key in ALLOWED_TYPES),
            )
        )
    counts = dict(source.object_counts)
    counts["Product"] = 2
    counts["Metafield"] = 1
    with pytest.raises(RuntimeContractError, match="Product object count"):
        _build_with_source(
            replace(
                source,
                object_counts=tuple((key, counts[key]) for key in ALLOWED_TYPES),
            )
        )
    with pytest.raises(RuntimeContractError, match="status counts must equal"):
        _build_with_source(
            replace(
                source,
                product_status_counts=(
                    ("ACTIVE", 1),
                    ("ARCHIVED", 0),
                    ("DRAFT", 1),
                    ("UNLISTED", 0),
                ),
            )
        )
    with pytest.raises(RuntimeContractError, match="independent evidence"):
        _build_with_source(replace(source, verified_active_online_store_published_product_count=1))
    with pytest.raises(RuntimeContractError, match="cannot exceed ACTIVE"):
        active_one = replace(
            source,
            product_status_counts=(
                ("ACTIVE", 1),
                ("ARCHIVED", 1),
                ("DRAFT", 1),
                ("UNLISTED", 0),
            ),
        )
        _build_with_source(active_one)
    with pytest.raises(RuntimeContractError, match="identity count cannot exceed"):
        _build_with_source(replace(source, source_identity_products=4))
    too_few_variants = _source_manifest(variant_count=2)
    with pytest.raises(RuntimeContractError, match="ProductVariant count cannot be less"):
        _build_with_source(too_few_variants)


def test_manifest_builder_rejects_every_reconciliation_mismatch() -> None:
    source = _source_manifest()
    with pytest.raises(RuntimeContractError, match="status counts do not reconcile"):
        _build_with_source(
            replace(
                source,
                product_status_counts=(
                    ("ACTIVE", 1),
                    ("ARCHIVED", 1),
                    ("DRAFT", 1),
                    ("UNLISTED", 0),
                ),
                verified_active_online_store_published_product_count=1,
                source=replace(
                    source.source,
                    expected_active_online_store_published_product_count=1,
                ),
            )
        )
    source_four = _source_manifest(
        product_status_counts=(
            ("ACTIVE", 2),
            ("ARCHIVED", 1),
            ("DRAFT", 1),
            ("UNLISTED", 0),
        ),
        product_count=4,
        variant_count=4,
        active_published=2,
        source_identities=2,
    )
    with pytest.raises(RuntimeContractError, match="Product count does not reconcile"):
        _build_with_source(source_four)
    with pytest.raises(RuntimeContractError, match="ProductVariant count"):
        _build_with_source(source, excluded_variants=1)
    with pytest.raises(RuntimeContractError, match="identity count"):
        _build_with_source(source, excluded_identities=1)
    with pytest.raises(RuntimeContractError, match="active published count"):
        _build_with_source(source, excluded_active_published=1)
