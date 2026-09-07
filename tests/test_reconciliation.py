from __future__ import annotations

import hashlib
import json
import sqlite3
import stat
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

import pytest

from nla_catalog_gateway import reconciliation as reconciliation
from nla_catalog_gateway.canonical_names import (
    CANONICAL_GAME_ORDER,
    CanonicalNameRecordV1,
    CanonicalNameSidecarEvidenceV1,
    CanonicalNamesManifestV1,
    CanonicalNameSourceEvidenceV1,
)
from nla_catalog_gateway.reconciliation import (
    BulkOperationTerminalEvidenceV1,
    CanonicalNamesInputV1,
    ReconciliationContractError,
    ReconciliationDataError,
    ReconciliationExpectationV1,
    SnapshotPart,
    SnapshotPartInputV1,
    SnapshotPartManifestV1,
    create_snapshot_part_manifest,
    reconcile_snapshot_parts,
)
from nla_catalog_gateway.runtime_contract import CapabilityState, Game, ProductFamily
from nla_catalog_gateway.taxonomy import ProductFacts, classify_catalog, load_taxonomy

PRODUCT_ONE = 9_007_199_254_740_993
PRODUCT_TWO = 9_007_199_254_740_995
VARIANT_ONE = 9_007_199_254_741_101
VARIANT_TWO = 9_007_199_254_741_103
ITEM_ONE = 9_007_199_254_742_001
ITEM_TWO = 9_007_199_254_742_003
LEVEL_ONE = 9_007_199_254_743_001
LEVEL_TWO = 9_007_199_254_743_003
LOCATION_ONE = 9_007_199_254_744_001
LOCATION_TWO = 9_007_199_254_744_003
PUBLICATION = "gid://shopify/Publication/9007199254743001"
SOURCE_SHA = "a" * 40
SNAPSHOT_SET = "sha256:" + "b" * 64
NOW = "2026-09-02T10:00:00Z"
LATER = "2026-09-02T10:01:00Z"
PROJECT_ROOT = Path(__file__).parents[1]


def _gid(kind: str, number: int) -> str:
    return f"gid://shopify/{kind}/{number}"


def _product(
    number: int,
    *,
    handle: str,
    source_id: str | None,
    product_type: str = "Magic Display",
    variants: int = 1,
) -> dict[str, object]:
    sync_source = None if source_id is None else {"type": "number_integer", "value": source_id}
    powertools_source = (
        None if source_id is None else {"type": "single_line_text_field", "value": source_id}
    )
    return {
        "__typename": "Product",
        "id": _gid("Product", number),
        "handle": handle,
        "title": "Duplicate synthetic commercial title",
        "status": "ACTIVE",
        "vendor": "Synthetic vendor",
        "productType": product_type,
        "tags": ["Magic", "Synthetic"],
        "createdAt": NOW,
        "updatedAt": LATER,
        "publishedAt": NOW,
        "onlineStoreUrl": None,
        "totalInventory": 0,
        "tracksInventory": True,
        "variantsCount": {"count": variants},
        "featuredMedia": None,
        "syncProductId": sync_source,
        "powertoolsId": powertools_source,
    }


def _publication(product: int, publication: str = PUBLICATION) -> dict[str, object]:
    return {
        "__typename": "ResourcePublicationV2",
        "__parentId": _gid("Product", product),
        "isPublished": True,
        "publishDate": NOW,
        "publication": {"id": publication, "autoPublish": False, "catalog": None},
    }


def _variant(
    product: int,
    number: int,
    item: int,
    *,
    product_gid: str | None = None,
) -> dict[str, object]:
    return {
        "__typename": "ProductVariant",
        "id": _gid("ProductVariant", number),
        "title": "Duplicate synthetic variant title",
        "sku": "DUPLICATE-SYNTHETIC-SKU",
        "barcode": None,
        "selectedOptions": [{"name": "Language", "value": "Synthetic"}],
        "price": "0.00",
        "compareAtPrice": None,
        "inventoryQuantity": 0,
        "inventoryPolicy": "DENY",
        "updatedAt": LATER,
        "product": {
            "__typename": "Product",
            "id": product_gid or _gid("Product", product),
        },
        "inventoryItem": {
            "__typename": "InventoryItem",
            "id": _gid("InventoryItem", item),
            "tracked": True,
        },
    }


def _level(variant: int, item: int, level: int, location: int) -> dict[str, object]:
    return {
        "__typename": "InventoryLevel",
        "__parentId": _gid("ProductVariant", variant),
        "id": f"{_gid('InventoryLevel', level)}?inventory_item_id={item}",
        "location": {"id": _gid("Location", location), "name": "Synthetic location"},
        "quantities": [
            {"name": name, "quantity": 0}
            for name in ("incoming", "available", "reserved", "committed", "on_hand")
        ],
    }


def _metafield(owner: str, number: int, key: str, value: str) -> dict[str, object]:
    return {
        "__typename": "Metafield",
        "__parentId": owner,
        "id": _gid("Metafield", number),
        "namespace": "nla",
        "key": key,
        "type": "single_line_text_field",
        "value": value,
    }


def _rows() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    products = [
        _publication(PRODUCT_TWO),
        _product(
            PRODUCT_ONE,
            handle="synthetic-one",
            source_id="9007199254745001",
        ),
        _publication(PRODUCT_ONE),
        _product(
            PRODUCT_TWO,
            handle="synthetic-two",
            source_id="9007199254745001",
            product_type="Unknown Synthetic Type",
        ),
        _metafield(_gid("Product", PRODUCT_ONE), 9007199254747001, "game", "magic"),
    ]
    variants = [
        _variant(PRODUCT_ONE, VARIANT_ONE, ITEM_ONE),
        _level(VARIANT_ONE, ITEM_ONE, LEVEL_ONE, LOCATION_ONE),
        _metafield(
            _gid("ProductVariant", VARIANT_ONE),
            9007199254747002,
            "synthetic_note",
            "synthetic",
        ),
        _variant(PRODUCT_TWO, VARIANT_TWO, ITEM_TWO),
        _level(VARIANT_TWO, ITEM_TWO, LEVEL_TWO, LOCATION_TWO),
    ]
    return products, variants


def _write_jsonl(path: Path, rows: list[object]) -> bytes:
    raw = b"".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
        for row in rows
    )
    path.write_bytes(raw)
    return raw


def _expectation(**changes: object) -> ReconciliationExpectationV1:
    values: dict[str, object] = {
        "snapshot_set_id": SNAPSHOT_SET,
        "shop_domain": "synthetic.myshopify.com",
        "api_version": "2026-04",
        "online_store_publication_gid": PUBLICATION,
        "source_code_sha": SOURCE_SHA,
        "product_count": 2,
        "variant_count": 2,
        "expected_active_online_store_published_product_count": 2,
    }
    values.update(changes)
    return ReconciliationExpectationV1(**values)  # type: ignore[arg-type]


def _terminal_evidence(
    query_path: Path,
    raw: bytes,
    rows: list[dict[str, object]],
    operation: int,
    *,
    created_at: str = NOW,
    completed_at: str = LATER,
    **changes: object,
) -> BulkOperationTerminalEvidenceV1:
    part = SnapshotPart.PRODUCTS if "products" in query_path.name else SnapshotPart.VARIANTS
    root_type = "Product" if part is SnapshotPart.PRODUCTS else "ProductVariant"
    values: dict[str, object] = {
        "operation_id": _gid("BulkOperation", operation),
        "operation_type": "QUERY",
        "status": "COMPLETED",
        "error_code": None,
        "query": query_path.read_bytes().decode("utf-8"),
        "created_at": created_at,
        "completed_at": completed_at,
        "file_size": len(raw),
        "object_count": len(rows),
        "root_object_count": sum(row.get("__typename") == root_type for row in rows),
        "url_present": True,
        "partial_data_url_present": False,
    }
    values.update(changes)
    return BulkOperationTerminalEvidenceV1(**values)  # type: ignore[arg-type]


def _make_input(
    tmp_path: Path,
    *,
    part: SnapshotPart,
    rows: list[dict[str, object]],
    expectation: ReconciliationExpectationV1,
    operation: int,
    created_at: str = NOW,
    completed_at: str = LATER,
) -> SnapshotPartInputV1:
    tmp_path.mkdir(parents=True, exist_ok=True)
    name = part.value
    snapshot = tmp_path / f"{name}.jsonl"
    query = tmp_path / f"{name}.graphql"
    raw = _write_jsonl(snapshot, rows)
    approved_query = PROJECT_ROOT / "graphql" / f"catalog_{name}_snapshot.graphql"
    query.write_bytes(approved_query.read_bytes())
    manifest = create_snapshot_part_manifest(
        snapshot,
        query_path=query,
        part=part,
        expectation=expectation,
        terminal_evidence=_terminal_evidence(
            query,
            raw,
            rows,
            operation,
            created_at=created_at,
            completed_at=completed_at,
        ),
    )
    return SnapshotPartInputV1(manifest, snapshot, query)


def _inputs(
    tmp_path: Path,
    *,
    products: list[dict[str, object]] | None = None,
    variants: list[dict[str, object]] | None = None,
    expectation: ReconciliationExpectationV1 | None = None,
) -> tuple[SnapshotPartInputV1, SnapshotPartInputV1]:
    default_products, default_variants = _rows()
    expected = expectation or _expectation()
    return (
        _make_input(
            tmp_path,
            part=SnapshotPart.PRODUCTS,
            rows=default_products if products is None else products,
            expectation=expected,
            operation=1,
        ),
        _make_input(
            tmp_path,
            part=SnapshotPart.VARIANTS,
            rows=default_variants if variants is None else variants,
            expectation=expected,
            operation=2,
        ),
    )


def _canonical_names_input(
    *,
    game: Game = Game.MAGIC,
    source_id: str = "9007199254745001",
    name: str = "Canonical synthetic card",
    expected_products: int = 2,
) -> CanonicalNamesInputV1:
    record = CanonicalNameRecordV1(game, source_id, name)
    sidecar_raw = record.to_json_bytes() + b"\n"
    sources = tuple(
        CanonicalNameSourceEvidenceV1(
            game=item,
            sha256=hashlib.sha256(item.value.encode()).hexdigest(),
            byte_count=1,
            record_count=int(item is game),
        )
        for item in CANONICAL_GAME_ORDER
    )
    manifest = CanonicalNamesManifestV1(
        generator_code_sha="c" * 40,
        sources=sources,
        sidecar=CanonicalNameSidecarEvidenceV1(
            sha256=hashlib.sha256(sidecar_raw).hexdigest(),
            byte_count=len(sidecar_raw),
            record_count=1,
        ),
    )
    return CanonicalNamesInputV1(
        manifest=manifest,
        manifest_sha256=manifest.manifest_sha256,
        records=MappingProxyType({(game, source_id): record}),
        expected_product_count=expected_products,
    )


def test_canonical_name_input_contract_rejects_forged_values() -> None:
    valid = _canonical_names_input()
    with pytest.raises(ReconciliationContractError, match="manifest is invalid"):
        replace(valid, manifest=object())  # type: ignore[arg-type]
    with pytest.raises(ReconciliationContractError, match="trust root"):
        replace(valid, manifest_sha256="0" * 64)
    with pytest.raises(ReconciliationContractError, match="mapping count"):
        replace(valid, records=MappingProxyType({}))
    with pytest.raises(ReconciliationContractError, match="mapping count"):
        replace(valid, records=object())  # type: ignore[arg-type]
    broken_mapping = dict(valid.records)

    class BrokenItems(dict[object, object]):
        def items(self) -> object:
            raise RuntimeError("synthetic iteration failure")

    with pytest.raises(ReconciliationContractError, match="mapping is invalid"):
        replace(valid, records=BrokenItems(broken_mapping))  # type: ignore[arg-type]
    bad_record = next(iter(valid.records.values()))
    with pytest.raises(ReconciliationContractError, match="mapping is invalid"):
        replace(valid, records=MappingProxyType({(Game.POKEMON, bad_record.source_id): bad_record}))
    forged_name = CanonicalNameRecordV1(
        bad_record.game,
        bad_record.source_id,
        "Different untrusted name",
    )
    with pytest.raises(ReconciliationContractError, match="evidence does not match"):
        replace(
            valid,
            records=MappingProxyType({(forged_name.game, forged_name.source_id): forged_name}),
        )
    with pytest.raises(ReconciliationContractError, match="Product count"):
        replace(valid, expected_product_count=-1)
    mutable = dict(valid.records)
    copied = replace(valid, records=mutable)
    mutable.clear()
    assert len(copied.records) == 1


def test_reconciliation_rejects_a_mistyped_canonical_name_input(tmp_path: Path) -> None:
    with pytest.raises(ReconciliationContractError, match="CanonicalNamesInputV1"):
        reconcile_snapshot_parts(
            _inputs(tmp_path),
            expectation=_expectation(),
            taxonomy_config=load_taxonomy(),
            canonical_names=object(),  # type: ignore[arg-type]
        )


class _CanonicalRowsCursor:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = iter(rows)
        self.closed = False

    def __iter__(self) -> _CanonicalRowsCursor:
        return self

    def __next__(self) -> dict[str, object]:
        return next(self._rows)

    def close(self) -> None:
        self.closed = True


class _CanonicalRowsConnection:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.cursor = _CanonicalRowsCursor(rows)

    def execute(self, _query: str) -> _CanonicalRowsCursor:
        return self.cursor


@pytest.mark.parametrize(
    ("facts", "rows", "message"),
    [
        (
            (ProductFacts(_gid("Product", PRODUCT_ONE)),),
            [
                {
                    "gid": _gid("Product", PRODUCT_TWO),
                    "product_type": "Magic Single",
                    "sync_source_id": "9007199254745001",
                }
            ],
            "order does not reconcile",
        ),
        (
            (ProductFacts(_gid("Product", PRODUCT_ONE)),),
            [
                {
                    "gid": _gid("Product", PRODUCT_ONE),
                    "product_type": "Magic Single",
                    "sync_source_id": None,
                }
            ],
            "lacks its source identity",
        ),
        (
            (),
            [
                {
                    "gid": _gid("Product", PRODUCT_ONE),
                    "product_type": "Magic Display",
                    "sync_source_id": "9007199254745001",
                }
            ],
            "order does not reconcile",
        ),
    ],
)
def test_canonical_name_join_internal_accounting_is_fail_closed(
    facts: tuple[ProductFacts, ...],
    rows: list[dict[str, object]],
    message: str,
) -> None:
    connection = _CanonicalRowsConnection(rows)
    with pytest.raises(ReconciliationDataError, match=message):
        reconciliation._apply_canonical_names(
            connection,  # type: ignore[arg-type]
            facts,
            load_taxonomy(),
            _canonical_names_input(),
        )
    assert connection.cursor.closed is True


def test_canonical_name_join_leaves_non_single_products_unchanged() -> None:
    facts = (ProductFacts(_gid("Product", PRODUCT_ONE), product_type="Magic Display"),)
    connection = _CanonicalRowsConnection(
        [
            {
                "gid": _gid("Product", PRODUCT_ONE),
                "product_type": "Magic Display",
                "sync_source_id": "9007199254745001",
            }
        ]
    )
    enriched, audit = reconciliation._apply_canonical_names(
        connection,  # type: ignore[arg-type]
        facts,
        load_taxonomy(),
        _canonical_names_input(expected_products=0),
    )
    assert enriched == facts
    assert audit is not None
    assert audit.unused_mapping_count == 1


def test_reconciliation_is_order_independent_and_projects_exact_large_gids(
    tmp_path: Path,
) -> None:
    inputs = _inputs(tmp_path)
    first = reconcile_snapshot_parts(
        inputs, expectation=_expectation(), taxonomy_config=load_taxonomy()
    )
    second = reconcile_snapshot_parts(
        (inputs[1], inputs[0]),
        expectation=_expectation(),
        taxonomy_config=load_taxonomy(),
    )

    assert first.source_manifest_bytes == second.source_manifest_bytes
    assert first.dataset_manifest.to_json_bytes() == second.dataset_manifest.to_json_bytes()
    assert tuple(record.to_json_bytes() for record in first.records) == tuple(
        record.to_json_bytes() for record in second.records
    )
    assert [record.product_gid for record in first.records] == [
        _gid("Product", PRODUCT_ONE),
        _gid("Product", PRODUCT_TWO),
    ]
    assert first.records[0].variants[0].variant_gid == _gid("ProductVariant", VARIANT_ONE)
    assert first.records[0].product_family is ProductFamily.SEALED
    assert first.records[0].game is Game.MAGIC
    assert first.records[1].product_family is ProductFamily.UNCLASSIFIED
    assert first.records[1].unclassified_reason == "unknown_product_type"
    assert first.source_manifest.product_count == 2
    assert first.source_manifest.variant_count == 2
    assert first.source_manifest.inventory_item_count == 2
    assert first.source_manifest.inventory_level_count == 2
    assert first.source_manifest.source_identity_product_count == 2
    assert first.dataset_manifest.included_source_identity_product_count == 2
    assert first.dataset_manifest.source_product_count == (
        first.dataset_manifest.classified_product_count
        + first.dataset_manifest.unclassified_product_count
    )
    assert all(
        state is not CapabilityState.VERIFIED
        for _name, state in (
            *first.dataset_manifest.capability_matrix.features,
            *first.dataset_manifest.capability_matrix.requests,
        )
    )
    assert len({record.product_gid for record in first.records}) == 2
    assert len({record.sync_source_id for record in first.records}) == 1
    assert all(record.sync_source_id == record.powertools_source_id for record in first.records)
    for item in inputs:
        encoded = item.manifest.to_json_bytes()
        assert SnapshotPartManifestV1.from_json_bytes(encoded).to_json_bytes() == encoded
        assert (
            item.manifest.query_sha256 == hashlib.sha256(item.query_path.read_bytes()).hexdigest()
        )
        assert item.manifest.operation_type == "QUERY"
        assert item.manifest.error_code is None
        assert item.manifest.url_present is True
        assert item.manifest.capture_fence_max_seconds == reconciliation.CAPTURE_FENCE_MAX_SECONDS


def test_canonical_name_join_preserves_duplicate_shopify_products(tmp_path: Path) -> None:
    products, variants = _rows()
    for row in products:
        if row["__typename"] == "Product":
            row["productType"] = "Magic Single"
    result = reconcile_snapshot_parts(
        _inputs(tmp_path, products=products, variants=variants),
        expectation=_expectation(),
        taxonomy_config=load_taxonomy(),
        canonical_names=_canonical_names_input(),
    )

    assert [record.canonical_card_name for record in result.records] == [
        "Canonical synthetic card",
        "Canonical synthetic card",
    ]
    assert all(record.product_family is ProductFamily.SINGLE for record in result.records)
    assert result.canonical_name_audit is not None
    assert result.canonical_name_audit.as_dict() == {
        "duplicateProductExcess": 1,
        "manifestSha256": result.canonical_name_audit.manifest_sha256,
        "mappingBytes": result.canonical_name_audit.mapping_bytes,
        "mappingRecordCount": 1,
        "mappingSha256": result.canonical_name_audit.mapping_sha256,
        "matchedProductCount": 2,
        "matchedUniqueKeyCount": 1,
        "unusedMappingCount": 0,
    }


@pytest.mark.parametrize(
    ("canonical_names", "message"),
    [
        (_canonical_names_input(game=Game.POKEMON), "lacks its canonical-name mapping"),
        (_canonical_names_input(expected_products=1), "Product count does not match"),
    ],
)
def test_canonical_name_join_fails_closed(
    tmp_path: Path,
    canonical_names: CanonicalNamesInputV1,
    message: str,
) -> None:
    products, variants = _rows()
    for row in products:
        if row["__typename"] == "Product":
            row["productType"] = "Magic Single"
    with pytest.raises(ReconciliationDataError, match=message):
        reconcile_snapshot_parts(
            _inputs(tmp_path, products=products, variants=variants),
            expectation=_expectation(),
            taxonomy_config=load_taxonomy(),
            canonical_names=canonical_names,
        )


def test_canonical_name_join_rejects_a_disagreeing_shopify_metafield(tmp_path: Path) -> None:
    products, variants = _rows()
    for row in products:
        if row["__typename"] == "Product":
            row["productType"] = "Magic Single"
    products.append(
        _metafield(
            _gid("Product", PRODUCT_ONE),
            9007199254747999,
            "canonical_card_name",
            "Different Shopify name",
        )
    )
    with pytest.raises(ReconciliationDataError, match="sources disagree"):
        reconcile_snapshot_parts(
            _inputs(tmp_path, products=products, variants=variants),
            expectation=_expectation(),
            taxonomy_config=load_taxonomy(),
            canonical_names=_canonical_names_input(),
        )


def test_capture_fence_rejects_nonoverlap_and_oversized_union(tmp_path: Path) -> None:
    products, variants = _rows()
    expected = _expectation()
    january = _make_input(
        tmp_path / "nonoverlap",
        part=SnapshotPart.PRODUCTS,
        rows=products,
        expectation=expected,
        operation=1,
        created_at="2026-01-01T00:00:00Z",
        completed_at="2026-01-01T00:01:00Z",
    )
    september = _make_input(
        tmp_path / "nonoverlap",
        part=SnapshotPart.VARIANTS,
        rows=variants,
        expectation=expected,
        operation=2,
        created_at="2026-09-01T00:00:00Z",
        completed_at="2026-09-01T00:01:00Z",
    )
    with pytest.raises(ReconciliationDataError, match="do not overlap"):
        reconcile_snapshot_parts(
            (january, september), expectation=expected, taxonomy_config=load_taxonomy()
        )

    first = _make_input(
        tmp_path / "wide-union",
        part=SnapshotPart.PRODUCTS,
        rows=products,
        expectation=expected,
        operation=3,
        created_at="2026-09-01T00:00:00Z",
        completed_at="2026-09-02T00:00:00Z",
    )
    second = _make_input(
        tmp_path / "wide-union",
        part=SnapshotPart.VARIANTS,
        rows=variants,
        expectation=expected,
        operation=4,
        created_at="2026-09-02T00:00:00Z",
        completed_at="2026-09-03T00:00:00Z",
    )
    with pytest.raises(ReconciliationDataError, match="maximum window"):
        reconcile_snapshot_parts(
            (first, second), expectation=expected, taxonomy_config=load_taxonomy()
        )


def test_timestamps_normalize_to_utc_and_generated_at_is_chronological(
    tmp_path: Path,
) -> None:
    products, variants = _rows()
    expected = _expectation()
    product_input = _make_input(
        tmp_path,
        part=SnapshotPart.PRODUCTS,
        rows=products,
        expectation=expected,
        operation=1,
        created_at="2026-09-02T12:00:00+02:00",
        completed_at="2026-09-02T12:30:00+02:00",
    )
    variant_input = _make_input(
        tmp_path,
        part=SnapshotPart.VARIANTS,
        rows=variants,
        expectation=expected,
        operation=2,
        created_at="2026-09-02T10:10:00Z",
        completed_at="2026-09-02T10:40:00Z",
    )
    result = reconcile_snapshot_parts(
        (product_input, variant_input),
        expectation=expected,
        taxonomy_config=load_taxonomy(),
    )
    assert product_input.manifest.created_at == "2026-09-02T10:00:00Z"
    assert product_input.manifest.completed_at == "2026-09-02T10:30:00Z"
    assert result.source_manifest.capture_started_at == "2026-09-02T10:00:00Z"
    assert result.source_manifest.capture_completed_at == "2026-09-02T10:40:00Z"
    assert result.source_manifest.capture_window_seconds == 2_400
    assert result.dataset_manifest.generated_at == "2026-09-02T10:40:00Z"

    changed = _make_input(
        tmp_path / "changed",
        part=SnapshotPart.VARIANTS,
        rows=variants,
        expectation=expected,
        operation=2,
        created_at="2026-09-02T10:11:00Z",
        completed_at="2026-09-02T10:40:00Z",
    )
    changed_result = reconcile_snapshot_parts(
        (product_input, changed), expectation=expected, taxonomy_config=load_taxonomy()
    )
    assert (
        changed_result.source_manifest.source_generation != result.source_manifest.source_generation
    )


@pytest.mark.parametrize("conflict", [False, True])
def test_duplicate_and_conflicting_typed_gid_rows_fail(tmp_path: Path, conflict: bool) -> None:
    products, variants = _rows()
    duplicate = dict(products[1])
    if conflict:
        duplicate["title"] = "Conflicting title"
    products.append(duplicate)
    expectation = _expectation(product_count=3, variant_count=3)
    variants.append(_variant(PRODUCT_ONE, 9007199254741105, 9007199254742005))
    with pytest.raises(ReconciliationDataError, match=r"duplicate|conflicting"):
        reconcile_snapshot_parts(
            _inputs(tmp_path, products=products, variants=variants, expectation=expectation),
            expectation=expectation,
            taxonomy_config=load_taxonomy(),
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("conflicting_source", "conflicting secondary source identity"),
        ("missing_child", "missing or excess ProductVariant children"),
        ("orphan_variant", "dangling ProductVariant"),
        ("orphan_level", "InventoryLevel parent ProductVariant is unavailable"),
        ("missing_publication", "missing Online Store publication evidence"),
        ("duplicate_item", "conflicting InventoryItem ownership"),
        ("duplicate_handle", "conflicting Product handle"),
    ],
)
def test_reconciliation_rejects_identity_and_accounting_failures(
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    products, variants = _rows()
    if mutation == "conflicting_source":
        products[1]["powertoolsId"] = {
            "type": "single_line_text_field",
            "value": "999",
        }
    elif mutation == "missing_child":
        variants[3]["product"] = {"__typename": "Product", "id": _gid("Product", PRODUCT_ONE)}
    elif mutation == "orphan_variant":
        variants[3]["product"] = {
            "__typename": "Product",
            "id": _gid("Product", 9007199254740999),
        }
    elif mutation == "orphan_level":
        variants[4]["__parentId"] = _gid("ProductVariant", 9007199254742999)
    elif mutation == "missing_publication":
        products[0] = _publication(PRODUCT_TWO, _gid("Publication", 42))
    elif mutation == "duplicate_item":
        variants[3]["inventoryItem"] = variants[0]["inventoryItem"]
    else:
        products[3]["handle"] = products[1]["handle"]
    with pytest.raises(ReconciliationDataError, match=message):
        reconcile_snapshot_parts(
            _inputs(tmp_path, products=products, variants=variants),
            expectation=_expectation(),
            taxonomy_config=load_taxonomy(),
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("inventory_item_parent", "InventoryLevel split shape is invalid"),
        ("unknown_variant_parent", "InventoryLevel parent ProductVariant is unavailable"),
        ("different_variant_parent", "snapshot row contract is invalid"),
        ("different_inventory_item", "snapshot row contract is invalid"),
        ("extra_gid_parameter", "snapshot row contract is invalid"),
        ("invalid_location", "snapshot row contract is invalid"),
        ("child_before_parent", "InventoryLevel parent ProductVariant is unavailable"),
        ("duplicate_item_location", "conflicting source row"),
    ],
)
def test_split_inventory_level_ownership_fails_closed(
    tmp_path: Path, mutation: str, message: str
) -> None:
    products, variants = _rows()
    level = variants[1]
    if mutation == "inventory_item_parent":
        level["__parentId"] = _gid("InventoryItem", ITEM_ONE)
    elif mutation == "unknown_variant_parent":
        level["__parentId"] = _gid("ProductVariant", 9007199254741999)
    elif mutation == "different_variant_parent":
        level = variants[4]
        level["__parentId"] = _gid("ProductVariant", VARIANT_ONE)
    elif mutation == "different_inventory_item":
        level["id"] = f"{_gid('InventoryLevel', LEVEL_ONE)}?inventory_item_id={ITEM_TWO}"
    elif mutation == "extra_gid_parameter":
        level["id"] = f"{_gid('InventoryLevel', LEVEL_ONE)}?inventory_item_id={ITEM_ONE}&extra=1"
    elif mutation == "invalid_location":
        level["location"] = {
            "id": _gid("InventoryItem", LOCATION_ONE),
            "name": "Synthetic location",
        }
    elif mutation == "child_before_parent":
        variants.insert(0, variants.pop(1))
    else:
        variants.insert(
            2,
            _level(VARIANT_ONE, ITEM_ONE, 9007199254743999, LOCATION_ONE),
        )
    with pytest.raises(ReconciliationDataError, match=message):
        reconcile_snapshot_parts(
            _inputs(tmp_path, products=products, variants=variants),
            expectation=_expectation(),
            taxonomy_config=load_taxonomy(),
        )


def test_mixed_partial_and_duplicate_parts_fail_closed(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    with pytest.raises(ReconciliationContractError, match="exactly two"):
        reconcile_snapshot_parts(
            (inputs[0],), expectation=_expectation(), taxonomy_config=load_taxonomy()
        )  # type: ignore[arg-type]
    with pytest.raises(ReconciliationContractError, match="duplicate snapshot part"):
        reconcile_snapshot_parts(
            (inputs[0], inputs[0]), expectation=_expectation(), taxonomy_config=load_taxonomy()
        )
    with pytest.raises(ReconciliationDataError, match="mixed generation"):
        reconcile_snapshot_parts(
            inputs,
            expectation=_expectation(snapshot_set_id="sha256:" + "c" * 64),
            taxonomy_config=load_taxonomy(),
        )


def test_changed_query_and_snapshot_cannot_enter_reconciliation(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    inputs[0].query_path.write_text("changed\n", encoding="utf-8")
    with pytest.raises(ReconciliationDataError, match="query does not match"):
        reconcile_snapshot_parts(
            inputs, expectation=_expectation(), taxonomy_config=load_taxonomy()
        )

    inputs = _inputs(tmp_path / "snapshot")
    with inputs[1].snapshot_path.open("ab") as handle:
        handle.write(
            json.dumps(_level(VARIANT_ONE, ITEM_ONE, LEVEL_ONE, LOCATION_ONE)).encode() + b"\n"
        )
    with pytest.raises(
        ReconciliationDataError, match=r"duplicate InventoryLevel|immutable manifest"
    ):
        reconcile_snapshot_parts(
            inputs, expectation=_expectation(), taxonomy_config=load_taxonomy()
        )


def test_part_manifest_rejects_partial_nonterminal_and_tampered_generation(
    tmp_path: Path,
) -> None:
    item = _inputs(tmp_path)[0]
    with pytest.raises(ReconciliationContractError, match="status"):
        replace(item.manifest, status="RUNNING")
    with pytest.raises(ReconciliationContractError, match="partial"):
        replace(item.manifest, partial_data_url_present=True)
    with pytest.raises(ReconciliationContractError, match="generation"):
        replace(item.manifest, part_generation="sha256:" + "0" * 64)


class _HostileStr(str):
    def strip(self, *_args: object, **_kwargs: object) -> str:
        raise RuntimeError("hostile")


class _EqualStr(str):
    pass


def test_hostile_and_forged_boundary_values_are_normalized(tmp_path: Path) -> None:
    with pytest.raises(ReconciliationContractError):
        _expectation(shop_domain=_HostileStr("synthetic.myshopify.com"))
    with pytest.raises(ReconciliationContractError):
        _expectation(online_store_publication_gid=_HostileStr(PUBLICATION))
    with pytest.raises(ReconciliationContractError):
        _expectation(product_count=True)
    with pytest.raises(ReconciliationContractError, match="concrete Path"):
        create_snapshot_part_manifest(  # type: ignore[arg-type]
            "source.jsonl",
            query_path=Path("query.graphql"),
            part=SnapshotPart.PRODUCTS,
            expectation=_expectation(),
            terminal_evidence=BulkOperationTerminalEvidenceV1(
                operation_id=_gid("BulkOperation", 1),
                operation_type="QUERY",
                status="COMPLETED",
                error_code=None,
                query="query Synthetic { shop { id } }",
                created_at=NOW,
                completed_at=LATER,
                file_size=1,
                object_count=1,
                root_object_count=1,
                url_present=True,
                partial_data_url_present=False,
            ),
        )
    forged = object.__new__(ReconciliationExpectationV1)
    object.__setattr__(forged, "snapshot_set_id", SNAPSHOT_SET)
    with pytest.raises(ReconciliationContractError, match="expectation is invalid"):
        reconcile_snapshot_parts((), expectation=forged, taxonomy_config=load_taxonomy())  # type: ignore[arg-type]


def test_create_manifest_binds_terminal_counts_and_root_expectation(tmp_path: Path) -> None:
    products, _variants = _rows()
    snapshot = tmp_path / "products.jsonl"
    query = tmp_path / "products.graphql"
    raw = _write_jsonl(snapshot, products)
    query.write_bytes((PROJECT_ROOT / "graphql" / "catalog_products_snapshot.graphql").read_bytes())
    terminal = _terminal_evidence(query, raw, products, 1)
    common = dict(
        snapshot_path=snapshot,
        query_path=query,
        part=SnapshotPart.PRODUCTS,
        expectation=_expectation(),
    )
    with pytest.raises(ReconciliationDataError, match="byte count"):
        create_snapshot_part_manifest(
            **common, terminal_evidence=replace(terminal, file_size=len(raw) + 1)
        )
    with pytest.raises(ReconciliationDataError, match="object count"):
        create_snapshot_part_manifest(
            **common, terminal_evidence=replace(terminal, object_count=len(products) + 1)
        )
    with pytest.raises(ReconciliationDataError, match="terminal evidence"):
        create_snapshot_part_manifest(
            **common, terminal_evidence=replace(terminal, root_object_count=3)
        )
    with pytest.raises(ReconciliationDataError, match="trusted expectation"):
        create_snapshot_part_manifest(
            **{**common, "expectation": _expectation(product_count=3, variant_count=3)},
            terminal_evidence=terminal,
        )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"operation_id": _gid("Product", 1)}, "BulkOperation.id"),
        ({"operation_type": "MUTATION"}, "type must be QUERY"),
        ({"status": "RUNNING"}, "status must be COMPLETED"),
        ({"error_code": "ACCESS_DENIED"}, "errorCode must be null"),
        ({"query": ""}, "non-empty"),
        ({"query": _EqualStr("query Synthetic { shop { id } }")}, "non-empty"),
        ({"query": "\ud800"}, "UTF-8"),
        ({"query": "x" * (reconciliation.MAX_BULK_QUERY_BYTES + 1)}, "byte bound"),
        ({"created_at": "invalid"}, "createdAt"),
        ({"created_at": "2026-09-02T10:00:00-00:00"}, "unknown timezone"),
        ({"created_at": "0001-01-01T00:00:00+14:00"}, "normalized to UTC"),
        ({"created_at": LATER, "completed_at": NOW}, "precedes"),
        (
            {
                "created_at": "2026-09-01T00:00:00Z",
                "completed_at": "2026-09-03T00:00:00Z",
            },
            "capture window",
        ),
        ({"file_size": True}, "fileSize"),
        ({"object_count": 0}, "objectCount"),
        ({"root_object_count": 0}, "rootObjectCount"),
        ({"object_count": 1, "root_object_count": 2}, "cannot exceed"),
        ({"url_present": False}, "url must be present"),
        ({"url_present": 1}, "url must be present"),
        ({"partial_data_url_present": 0}, "flag must be boolean"),
        ({"partial_data_url_present": True}, "partial"),
    ],
)
def test_terminal_bulk_operation_evidence_is_exact_and_fail_closed(
    tmp_path: Path, changes: dict[str, object], message: str
) -> None:
    products, _variants = _rows()
    snapshot = tmp_path / "products.jsonl"
    query = tmp_path / "products.graphql"
    raw = _write_jsonl(snapshot, products)
    query.write_bytes((PROJECT_ROOT / "graphql" / "catalog_products_snapshot.graphql").read_bytes())
    with pytest.raises(ReconciliationContractError, match=message):
        _terminal_evidence(query, raw, products, 1, **changes)


def test_create_manifest_requires_exact_approved_query_and_deep_terminal_copy(
    tmp_path: Path,
) -> None:
    products, _variants = _rows()
    snapshot = tmp_path / "products.jsonl"
    query = tmp_path / "products.graphql"
    raw = _write_jsonl(snapshot, products)
    fake_query = "query Synthetic { shop { id } }\n"
    query.write_text(fake_query, encoding="utf-8", newline="")
    fake_terminal = _terminal_evidence(query, raw, products, 1)
    with pytest.raises(ReconciliationDataError, match="approved query"):
        create_snapshot_part_manifest(
            snapshot,
            query_path=query,
            part=SnapshotPart.PRODUCTS,
            expectation=_expectation(),
            terminal_evidence=fake_terminal,
        )

    query.write_bytes((PROJECT_ROOT / "graphql" / "catalog_products_snapshot.graphql").read_bytes())
    terminal = _terminal_evidence(query, raw, products, 1)
    with pytest.raises(ReconciliationDataError, match="exact Shopify transport"):
        create_snapshot_part_manifest(
            snapshot,
            query_path=query,
            part=SnapshotPart.PRODUCTS,
            expectation=_expectation(),
            terminal_evidence=replace(terminal, query=terminal.query + "\n"),
        )

    corrupted = replace(terminal)
    object.__setattr__(corrupted, "status", "RUNNING")
    with pytest.raises(ReconciliationContractError, match="status must be COMPLETED"):
        create_snapshot_part_manifest(
            snapshot,
            query_path=query,
            part=SnapshotPart.PRODUCTS,
            expectation=_expectation(),
            terminal_evidence=corrupted,
        )

    forged = object.__new__(BulkOperationTerminalEvidenceV1)
    object.__setattr__(forged, "operation_id", terminal.operation_id)
    with pytest.raises(ReconciliationContractError, match="terminal evidence is invalid"):
        create_snapshot_part_manifest(
            snapshot,
            query_path=query,
            part=SnapshotPart.PRODUCTS,
            expectation=_expectation(),
            terminal_evidence=forged,
        )

    with pytest.raises(ReconciliationContractError, match="must be BulkOperationTerminalEvidence"):
        create_snapshot_part_manifest(
            snapshot,
            query_path=query,
            part=SnapshotPart.PRODUCTS,
            expectation=_expectation(),
            terminal_evidence=object(),  # type: ignore[arg-type]
        )


def test_query_reader_is_bounded_and_utf8(tmp_path: Path) -> None:
    query = tmp_path / "query.graphql"
    for raw, message in (
        (b"", "bytes are invalid"),
        (b"x" * (reconciliation.MAX_BULK_QUERY_BYTES + 1), "bytes are invalid"),
        (b"\xff", "valid UTF-8"),
    ):
        query.write_bytes(raw)
        with pytest.raises(ReconciliationDataError, match=message):
            reconciliation._read_query_bytes(query)
    with pytest.raises(ReconciliationDataError, match="cannot read"):
        reconciliation._read_query_bytes(tmp_path / "missing.graphql")


def test_query_reader_enforces_one_immutable_source_and_exact_frozen_bytes(
    tmp_path: Path,
) -> None:
    query = tmp_path / "query.graphql"
    query.write_bytes(b"query Synthetic { shop { id } }")
    with query.open("rb") as handle:
        with pytest.raises(ReconciliationContractError, match="one immutable source"):
            reconciliation._read_query_bytes(query, handle=handle, frozen=b"query")
    with pytest.raises(ReconciliationDataError, match="cannot read snapshot query"):
        reconciliation._read_query_bytes(  # type: ignore[arg-type]
            query, frozen=bytearray(b"query")
        )


def test_query_reader_uses_and_revalidates_the_pinned_handle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    query = tmp_path / "query.graphql"
    raw = b"query Synthetic { shop { id } }"
    query.write_bytes(raw)
    with query.open("rb") as handle:
        assert reconciliation._read_query_bytes(query, handle=handle) == raw

    states = iter(((1, 2, len(raw), 3), (1, 2, len(raw), 4)))
    monkeypatch.setattr(
        reconciliation,
        "_verify_pinned_handle",
        lambda _handle, _context: next(states),
    )
    with query.open("rb") as handle:
        with pytest.raises(ReconciliationDataError, match="cannot read snapshot query"):
            reconciliation._read_query_bytes(query, handle=handle)


def test_terminal_query_reader_accepts_the_exact_shopify_transport() -> None:
    canonical = b"query Synthetic {\n  shop { id }\n}"
    transported = reconciliation._shopify_terminal_query_transport(canonical)
    assert (
        reconciliation._terminal_query_transport_mode(transported.decode("utf-8"), canonical)
        == "shopify-crlf-plus-one-terminal-newline-v1"
    )


def test_fractional_timestamp_is_normalized_to_canonical_utc() -> None:
    assert (
        reconciliation._validated_timestamp("2026-09-02T12:00:00.5+02:00", "test")
        == "2026-09-02T10:00:00.500000Z"
    )


def test_canonical_json_and_scalar_contract_helpers_fail_closed() -> None:
    with pytest.raises(ReconciliationContractError, match="serializable"):
        reconciliation._canonical_json_bytes(object(), context="test", limit=10)
    with pytest.raises(ReconciliationContractError, match="byte bound"):
        reconciliation._canonical_json_bytes({"long": "value"}, context="test", limit=1)
    with pytest.raises(ReconciliationContractError, match="timestamp"):
        reconciliation._validated_timestamp(7, "test")
    with pytest.raises(ReconciliationContractError, match="timestamp"):
        reconciliation._validated_timestamp("not-a-time", "test")
    with pytest.raises(ReconciliationContractError, match="Product GID"):
        reconciliation._validated_gid("gid://shopify/Variant/1", "Product", "test")
    with pytest.raises(ReconciliationContractError, match="expectation"):
        reconciliation._validated_expectation(object())


@pytest.mark.parametrize(
    "changes",
    [
        {"snapshot_set_id": "invalid"},
        {"api_version": "unstable"},
        {"source_code_sha": "a" * 39},
        {"product_count": 0},
        {"variant_count": 1},
        {"expected_active_online_store_published_product_count": 3},
    ],
)
def test_expectation_rejects_invalid_identity_and_count_fences(changes: dict[str, object]) -> None:
    with pytest.raises(ReconciliationContractError):
        _expectation(**changes)


def test_corrupted_exact_expectation_is_revalidated() -> None:
    value = _expectation()
    object.__setattr__(value, "product_count", 0)
    with pytest.raises(ReconciliationContractError, match="productCount"):
        reconciliation._validated_expectation(value)


def test_part_manifest_rejects_every_noncanonical_field_shape(tmp_path: Path) -> None:
    manifest = _inputs(tmp_path)[0].manifest
    invalid_values = [
        {"schema_version": 2},
        {"part": "products"},
        {"snapshot_set_id": "invalid"},
        {"shop_domain": "bad.example"},
        {"api_version": "unstable"},
        {"operation_id": "gid://shopify/Product/1"},
        {"operation_type": "MUTATION"},
        {"error_code": "ACCESS_DENIED"},
        {"url_present": False},
        {"partial_data_url_present": 1},
        {"created_at": LATER, "completed_at": NOW},
        {"created_at": "2026-09-02T12:00:00+02:00"},
        {"created_at": "2026-09-01T00:00:00Z"},
        {"capture_fence_max_seconds": True},
        {"source_code_sha": "a" * 39},
        {"query_sha256": "0" * 63},
        {"content_sha256": "0" * 63},
        {"snapshot_bytes": 0},
        {"object_count": 0},
        {"root_object_count": 0},
        {"object_counts": (("Product", 2),)},
        {"object_counts": (("Metafield", 1), ("Product",), ("ResourcePublicationV2", 2))},
        {
            "object_counts": (
                (_EqualStr("Metafield"), 1),
                ("Product", 2),
                ("ResourcePublicationV2", 2),
            )
        },
        {"object_counts": (("Metafield", 0), ("Product", 2), ("ResourcePublicationV2", 1))},
        {"object_counts": (("Metafield", 1), ("Product", 1), ("ResourcePublicationV2", 3))},
        {"part_generation": "invalid"},
    ]
    for changes in invalid_values:
        with pytest.raises(ReconciliationContractError):
            replace(manifest, **changes)


def _manifest_document(manifest: SnapshotPartManifestV1) -> dict[str, object]:
    return json.loads(manifest.to_json_bytes())


def test_part_manifest_json_parser_is_strict_and_bounded(tmp_path: Path) -> None:
    manifest = _inputs(tmp_path)[0].manifest
    with pytest.raises(ReconciliationContractError, match="bytes"):
        SnapshotPartManifestV1.from_json_bytes(b"")
    with pytest.raises(ReconciliationContractError, match="bytes"):
        SnapshotPartManifestV1.from_json_bytes(bytearray(b"{}"))  # type: ignore[arg-type]
    with pytest.raises(ReconciliationContractError, match="bytes"):
        SnapshotPartManifestV1.from_json_bytes(b" " * (reconciliation.MAX_PART_MANIFEST_BYTES + 1))
    with pytest.raises(ReconciliationContractError, match="object"):
        SnapshotPartManifestV1.from_json_bytes(b"[]")

    document = _manifest_document(manifest)
    document["objectCounts"] = []
    with pytest.raises(ReconciliationContractError, match="objectCounts"):
        SnapshotPartManifestV1.from_json_bytes(json.dumps(document).encode())

    document = _manifest_document(manifest)
    document["part"] = "unknown"
    with pytest.raises(ReconciliationContractError, match="manifest is invalid"):
        SnapshotPartManifestV1.from_json_bytes(json.dumps(document).encode())

    document["part"] = []
    with pytest.raises(ReconciliationContractError, match="manifest is invalid"):
        SnapshotPartManifestV1.from_json_bytes(json.dumps(document).encode())

    encoded = manifest.to_json_bytes()
    duplicate = encoded.replace(b'"apiVersion":', b'"apiVersion":"2026-04","apiVersion":', 1)
    with pytest.raises(ReconciliationContractError, match="manifest is invalid"):
        SnapshotPartManifestV1.from_json_bytes(duplicate)


def test_validated_manifest_rejects_wrong_and_corrupted_objects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _inputs(tmp_path)[0].manifest
    with pytest.raises(ReconciliationContractError, match="part manifest"):
        reconciliation._validated_part_manifest(object())
    corrupted = replace(manifest)
    object.__setattr__(corrupted, "schema_version", 2)
    with pytest.raises(ReconciliationContractError, match="schemaVersion"):
        reconciliation._validated_part_manifest(corrupted)

    original = SnapshotPartManifestV1.from_json_bytes

    def changed(raw: bytes) -> SnapshotPartManifestV1:
        decoded = original(raw)
        object.__setattr__(decoded, "part_generation", "sha256:" + "0" * 64)
        return decoded

    monkeypatch.setattr(SnapshotPartManifestV1, "from_json_bytes", changed)
    with pytest.raises(ReconciliationContractError, match="non-canonical"):
        reconciliation._validated_part_manifest(manifest)


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (b"\n", "blank"),
        (b"[]\n", "must be an object"),
        (b'{"__typename":"Unknown"}\n', "unexpected object type"),
        (b"not-json\n", "snapshot part is invalid"),
    ],
)
def test_part_reader_rejects_malformed_jsonl(tmp_path: Path, raw: bytes, message: str) -> None:
    path = tmp_path / "part.jsonl"
    path.write_bytes(raw)
    with pytest.raises(ReconciliationDataError, match=message):
        reconciliation._read_part(path, SnapshotPart.PRODUCTS)


def test_part_reader_and_query_hash_normalize_file_failures(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    with pytest.raises(ReconciliationDataError, match="cannot read snapshot"):
        reconciliation._read_part(missing, SnapshotPart.PRODUCTS)
    with pytest.raises(ReconciliationDataError, match="cannot read query"):
        reconciliation._file_sha256(missing, "query")


def test_create_manifest_rejects_non_enum_part(tmp_path: Path) -> None:
    with pytest.raises(ReconciliationContractError, match="part must"):
        create_snapshot_part_manifest(  # type: ignore[arg-type]
            tmp_path / "snapshot",
            query_path=tmp_path / "query",
            part="products",
            expectation=_expectation(),
            terminal_evidence=BulkOperationTerminalEvidenceV1(
                operation_id=_gid("BulkOperation", 1),
                operation_type="QUERY",
                status="COMPLETED",
                error_code=None,
                query="query Synthetic { shop { id } }",
                created_at=NOW,
                completed_at=LATER,
                file_size=1,
                object_count=1,
                root_object_count=1,
                url_present=True,
                partial_data_url_present=False,
            ),
        )


def test_ordered_inputs_require_exact_values_and_distinct_evidence(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    with pytest.raises(ReconciliationContractError, match="SnapshotPartInputV1"):
        reconcile_snapshot_parts(
            (inputs[0], object()),  # type: ignore[arg-type]
            expectation=_expectation(),
            taxonomy_config=load_taxonomy(),
        )
    with pytest.raises(ReconciliationContractError, match="distinct files"):
        reconcile_snapshot_parts(
            (inputs[0], replace(inputs[1], snapshot_path=inputs[0].snapshot_path)),
            expectation=_expectation(),
            taxonomy_config=load_taxonomy(),
        )
    with pytest.raises(ReconciliationContractError, match="distinct queries"):
        reconcile_snapshot_parts(
            (inputs[0], replace(inputs[1], query_path=inputs[0].query_path)),
            expectation=_expectation(),
            taxonomy_config=load_taxonomy(),
        )

    products, variants = _rows()
    first = _make_input(
        tmp_path / "same-operation",
        part=SnapshotPart.PRODUCTS,
        rows=products,
        expectation=_expectation(),
        operation=1,
    )
    second = _make_input(
        tmp_path / "same-operation",
        part=SnapshotPart.VARIANTS,
        rows=variants,
        expectation=_expectation(),
        operation=1,
    )
    with pytest.raises(ReconciliationDataError, match="distinct Bulk operations"):
        reconcile_snapshot_parts(
            (first, second), expectation=_expectation(), taxonomy_config=load_taxonomy()
        )


def test_ordered_inputs_normalize_path_resolution_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _inputs(tmp_path)
    path_type = type(inputs[0].snapshot_path)
    monkeypatch.setattr(
        path_type,
        "resolve",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("hostile path")),
    )
    with pytest.raises(ReconciliationContractError, match="cannot be resolved"):
        reconcile_snapshot_parts(
            inputs, expectation=_expectation(), taxonomy_config=load_taxonomy()
        )


def test_pinned_input_handles_must_be_complete_and_distinct(tmp_path: Path) -> None:
    first, second = _inputs(tmp_path)
    with first.snapshot_path.open("rb") as handle:
        incomplete = replace(first, snapshot_handle=handle)
        with pytest.raises(ReconciliationContractError, match="both handles"):
            reconcile_snapshot_parts(
                (incomplete, second),
                expectation=_expectation(),
                taxonomy_config=load_taxonomy(),
            )

        duplicate_first = replace(first, snapshot_handle=handle, query_handle=handle)
        duplicate_second = replace(second, snapshot_handle=handle, query_handle=handle)
        with pytest.raises(ReconciliationContractError, match="must be distinct"):
            reconcile_snapshot_parts(
                (duplicate_first, duplicate_second),
                expectation=_expectation(),
                taxonomy_config=load_taxonomy(),
            )


def test_query_immutable_source_modes_must_be_complete_and_exclusive(tmp_path: Path) -> None:
    first, second = _inputs(tmp_path)
    first_query = first.query_path.read_bytes()
    second_query = second.query_path.read_bytes()
    with first.query_path.open("rb") as first_handle:
        with pytest.raises(ReconciliationContractError, match="one immutable source mode"):
            reconcile_snapshot_parts(
                (
                    replace(first, query_handle=first_handle),
                    replace(second, query_bytes=second_query),
                ),
                expectation=_expectation(),
                taxonomy_config=load_taxonomy(),
            )
        with pytest.raises(ReconciliationContractError, match="both handles"):
            reconcile_snapshot_parts(
                (replace(first, query_handle=first_handle), second),
                expectation=_expectation(),
                taxonomy_config=load_taxonomy(),
            )
    with pytest.raises(ReconciliationContractError, match="both byte strings"):
        reconcile_snapshot_parts(
            (replace(first, query_bytes=first_query), second),
            expectation=_expectation(),
            taxonomy_config=load_taxonomy(),
        )


def test_reconciliation_accepts_two_distinct_pinned_query_handles(tmp_path: Path) -> None:
    first, second = _inputs(tmp_path)
    with (
        first.query_path.open("rb") as first_handle,
        second.query_path.open("rb") as second_handle,
    ):
        generation = reconcile_snapshot_parts(
            (
                replace(first, query_handle=first_handle),
                replace(second, query_handle=second_handle),
            ),
            expectation=_expectation(),
            taxonomy_config=load_taxonomy(),
        )
    assert len(generation.records) == 2


def test_reconciliation_accepts_two_frozen_queries_and_pinned_snapshot_handles(
    tmp_path: Path,
) -> None:
    first, second = _inputs(tmp_path)
    with (
        first.snapshot_path.open("rb") as first_handle,
        second.snapshot_path.open("rb") as second_handle,
    ):
        generation = reconcile_snapshot_parts(
            (
                replace(
                    first,
                    snapshot_handle=first_handle,
                    query_bytes=first.query_path.read_bytes(),
                ),
                replace(
                    second,
                    snapshot_handle=second_handle,
                    query_bytes=second.query_path.read_bytes(),
                ),
            ),
            expectation=_expectation(),
            taxonomy_config=load_taxonomy(),
        )
    assert len(generation.records) == 2


def test_pinned_handle_state_is_bound_to_the_open_regular_object(tmp_path: Path) -> None:
    expected = tmp_path / "expected"
    other = tmp_path / "other"
    expected.write_bytes(b"expected")
    other.write_bytes(b"other")
    with expected.open("rb") as expected_handle, other.open("rb") as other_handle:
        expected_state = reconciliation._verify_pinned_handle(expected_handle, "input")
        other_state = reconciliation._verify_pinned_handle(other_handle, "input")
        assert expected_state != other_state
    with pytest.raises(ReconciliationDataError, match="cannot be verified"):
        reconciliation._verify_pinned_handle(expected_handle, "input")


@pytest.mark.parametrize(
    ("mode", "links"),
    [
        (stat.S_IFDIR, 1),
        (stat.S_IFREG, 2),
    ],
)
def test_pinned_handle_rejects_non_regular_or_multiply_linked_objects(
    monkeypatch: pytest.MonkeyPatch, mode: int, links: int
) -> None:
    facts = type("Facts", (), {"st_mode": mode, "st_nlink": links})()
    monkeypatch.setattr(reconciliation.os, "fstat", lambda _descriptor: facts)
    handle = type("Handle", (), {"fileno": lambda _self: 7})()
    with pytest.raises(ReconciliationDataError, match="not one regular file"):
        reconciliation._verify_pinned_handle(handle, "input")  # type: ignore[arg-type]


def test_part_reader_revalidates_pinned_state_after_consuming_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, _second = _inputs(tmp_path)
    size = first.snapshot_path.stat().st_size
    states = iter(((1, 2, size, 3), (1, 2, size, 4)))
    monkeypatch.setattr(
        reconciliation,
        "_verify_pinned_handle",
        lambda _handle, _context: next(states),
    )
    with first.snapshot_path.open("rb") as handle:
        with pytest.raises(ReconciliationDataError, match="pinned state changed"):
            reconciliation._read_part(
                first.snapshot_path,
                SnapshotPart.PRODUCTS,
                handle=handle,
            )


def test_identical_query_hashes_are_rejected(tmp_path: Path) -> None:
    products, variants = _rows()
    root = tmp_path / "same-query"
    first = _make_input(
        root,
        part=SnapshotPart.PRODUCTS,
        rows=products,
        expectation=_expectation(),
        operation=1,
    )
    second = _make_input(
        root,
        part=SnapshotPart.VARIANTS,
        rows=variants,
        expectation=_expectation(),
        operation=2,
    )
    forged = replace(second.manifest)
    object.__setattr__(forged, "query_sha256", first.manifest.query_sha256)
    object.__setattr__(forged, "part_generation", forged.expected_part_generation())
    second.query_path.write_bytes(first.query_path.read_bytes())
    second = SnapshotPartInputV1(forged, second.snapshot_path, second.query_path)
    with pytest.raises(ReconciliationDataError, match="approved query"):
        reconcile_snapshot_parts(
            (first, second), expectation=_expectation(), taxonomy_config=load_taxonomy()
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing_product", "lacks Product ownership"),
        ("wrong_product_type", "invalid Product ownership"),
        ("bad_product_gid", "root shape"),
        ("missing_inventory_item", "inventory item"),
        ("bad_contract", "row contract"),
        ("duplicate_metafield_key", "conflicting source row"),
    ],
)
def test_variant_and_metafield_row_contracts_fail_closed(
    tmp_path: Path, mutation: str, message: str
) -> None:
    products, variants = _rows()
    if mutation == "missing_product":
        variants[0]["product"] = None
    elif mutation == "wrong_product_type":
        variants[0]["product"] = {"__typename": "Variant", "id": _gid("Product", PRODUCT_ONE)}
    elif mutation == "bad_product_gid":
        variants[0]["product"] = {"__typename": "Product", "id": _gid("Variant", 1)}
    elif mutation == "missing_inventory_item":
        variants[0]["inventoryItem"] = None
    elif mutation == "bad_contract":
        variants[0]["price"] = True
    else:
        variants.extend(
            [
                _metafield(_gid("ProductVariant", VARIANT_ONE), 9007199254747998, "same", "one"),
                _metafield(_gid("ProductVariant", VARIANT_ONE), 9007199254747999, "same", "two"),
            ]
        )
    with pytest.raises(ReconciliationDataError, match=message):
        reconcile_snapshot_parts(
            _inputs(tmp_path, products=products, variants=variants),
            expectation=_expectation(),
            taxonomy_config=load_taxonomy(),
        )


def test_dangling_metafield_and_publication_fail(tmp_path: Path) -> None:
    products, variants = _rows()
    products.append(_metafield(_gid("Product", 999), 9007199254747990, "game", "magic"))
    with pytest.raises(ReconciliationDataError, match="dangling Metafield"):
        reconcile_snapshot_parts(
            _inputs(tmp_path / "metafield", products=products, variants=variants),
            expectation=_expectation(),
            taxonomy_config=load_taxonomy(),
        )

    products, variants = _rows()
    products[0]["__parentId"] = _gid("Product", 999)
    with pytest.raises(ReconciliationDataError, match="dangling ResourcePublication"):
        reconcile_snapshot_parts(
            _inputs(tmp_path / "publication", products=products, variants=variants),
            expectation=_expectation(),
            taxonomy_config=load_taxonomy(),
        )


def test_internal_manifest_scan_and_reader_failures_are_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _inputs(tmp_path / "manifest")[0].manifest
    forged = replace(manifest)
    object.__setattr__(forged, "part", object())
    with pytest.raises(ReconciliationContractError, match="manifest is invalid"):
        reconciliation._validated_part_manifest(forged)

    mismatched = replace(
        reconciliation._read_part(
            _inputs(tmp_path / "scan")[0].snapshot_path, SnapshotPart.PRODUCTS
        ),
        snapshot_bytes=1,
    )
    with pytest.raises(ReconciliationDataError, match="immutable manifest"):
        reconciliation._validate_scan(mismatched, manifest)

    source = tmp_path / "consumer.jsonl"
    _write_jsonl(source, [_product(PRODUCT_ONE, handle="one", source_id=None)])

    def hostile_consumer(*_args: object) -> None:
        raise RuntimeError("hostile consumer")

    with pytest.raises(ReconciliationDataError, match="processing failed"):
        reconciliation._read_part(source, SnapshotPart.PRODUCTS, hostile_consumer)

    with pytest.raises(ReconciliationDataError, match="canonically serializable"):
        reconciliation._canonical_source_row({"hostile": object()})

    monkeypatch.setattr(
        reconciliation,
        "_remember_identity",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("hostile row")),
    )
    with pytest.raises(ReconciliationDataError, match="processing failed"):
        reconciliation._insert_source_row(
            object(),
            SnapshotPart.PRODUCTS,
            {"__typename": "Product"},
            1,  # type: ignore[arg-type]
        )


def test_source_row_identity_errors_are_bounded() -> None:
    with pytest.raises(ReconciliationDataError, match="publication row"):
        reconciliation._row_identity(
            {
                "__typename": "ResourcePublicationV2",
                "__parentId": _gid("Product", PRODUCT_ONE),
                "publication": None,
            }
        )
    with pytest.raises(ReconciliationDataError, match="identity is invalid"):
        reconciliation._row_identity(
            {"__typename": "Product", "id": _gid("ProductVariant", VARIANT_ONE)}
        )
    with pytest.raises(ReconciliationDataError, match="type is invalid"):
        reconciliation._row_identity({"__typename": "Unknown"})


class _OneRow:
    def __init__(self, row: object) -> None:
        self.row = row

    def fetchone(self) -> object:
        return self.row


class _QuickCheckConnection:
    def __init__(self, row: object = ("ok",)) -> None:
        self.row = row

    def execute(self, _query: str, _parameters: tuple[object, ...] = ()) -> _OneRow:
        return _OneRow(self.row)


def test_scalar_rejects_missing_and_non_integer_results() -> None:
    for row in (None, (True,)):
        with pytest.raises(ReconciliationDataError, match="count is unavailable"):
            reconciliation._scalar(_QuickCheckConnection(row), "SELECT 1")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"product": 1}, "root identity counts"),
        ({"product_scan": 1}, "Product accounting"),
        ({"variant_scan": 1}, "ProductVariant accounting"),
        ({"inventory": 1}, "InventoryItem identity"),
        ({"active": 1}, "active published Product count"),
        ({"quick": None}, "quick_check"),
        ({"quick": ("corrupt",)}, "quick_check"),
    ],
)
def test_reconciliation_defensive_accounting_checks(
    monkeypatch: pytest.MonkeyPatch,
    override: dict[str, object],
    message: str,
) -> None:
    values: dict[str, object] = {
        "product": 2,
        "variant": 2,
        "inventory": 2,
        "active": 2,
        "quick": ("ok",),
        "product_scan": 2,
        "variant_scan": 2,
    }
    values.update(override)
    scans = {
        SnapshotPart.PRODUCTS: reconciliation._PartScan(
            "0" * 64,
            1,
            1,
            (("Metafield", 0), ("Product", values["product_scan"]), ("ResourcePublicationV2", 0)),
        ),
        SnapshotPart.VARIANTS: reconciliation._PartScan(
            "1" * 64,
            1,
            1,
            (("InventoryLevel", 0), ("Metafield", 0), ("ProductVariant", values["variant_scan"])),
        ),
    }

    def scalar(_connection: object, query: str, parameters: tuple[object, ...] = ()) -> int:
        if query == "SELECT COUNT(*) FROM products":
            return values["product"]  # type: ignore[return-value]
        if query == "SELECT COUNT(*) FROM variants":
            return values["variant"]  # type: ignore[return-value]
        if "DISTINCT inventory_item_gid" in query:
            return values["inventory"]  # type: ignore[return-value]
        if "p.status='ACTIVE'" in query:
            return values["active"]  # type: ignore[return-value]
        if "WHERE status=?" in query:
            return 2 if parameters == ("ACTIVE",) else 0
        return 0

    monkeypatch.setattr(reconciliation, "_require_no_row", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(reconciliation, "_scalar", scalar)
    with pytest.raises(ReconciliationDataError, match=message):
        reconciliation._reconcile_database(
            _QuickCheckConnection(values["quick"]),  # type: ignore[arg-type]
            _expectation(),
            scans,
        )


class _RowsConnection:
    def __init__(
        self, products: list[dict[str, object]], variants: list[dict[str, object]]
    ) -> None:
        self.products = products
        self.variants = variants

    def execute(self, query: str, _parameters: tuple[object, ...] = ()) -> list[dict[str, object]]:
        return self.variants if query == reconciliation._VARIANT_RUNTIME_SQL else self.products


def _stored_product(product_gid: str = _gid("Product", PRODUCT_ONE)) -> dict[str, object]:
    return {
        "gid": product_gid,
        "handle": "synthetic-one",
        "commercial_title": "Synthetic Display",
        "status": "ACTIVE",
        "is_published": 1,
        "powertools_source_id": "9007199254745001",
        "sync_source_id": "9007199254745001",
        "total_inventory": 0,
        "tracks_inventory": 1,
        "updated_at": LATER,
    }


def _stored_variant(
    product_gid: str = _gid("Product", PRODUCT_ONE),
) -> dict[str, object]:
    return {
        "gid": _gid("ProductVariant", VARIANT_ONE),
        "product_gid": product_gid,
        "inventory_item_gid": _gid("InventoryItem", ITEM_ONE),
        "title": "Synthetic variant",
        "sku": None,
        "barcode": None,
        "selected_options_json": '[{"name":"Language","value":"Synthetic"}]',
        "price_text": "0.00",
        "compare_at_price_text": None,
        "inventory_quantity": 0,
        "inventory_policy": "DENY",
        "inventory_tracked": 1,
        "updated_at": LATER,
    }


def test_taxonomy_storage_boundaries_fail_closed() -> None:
    with pytest.raises(ReconciliationDataError, match="metafield has an invalid type"):
        reconciliation._structured_metafield(
            {"value": "magic", "value_type": "json"},
            "value",
            "value_type",  # type: ignore[arg-type]
        )

    base = {
        "gid": _gid("Product", PRODUCT_ONE),
        "product_type": "Magic Display",
        "commercial_title": "Synthetic Display",
        "nla_game": None,
        "nla_game_type": None,
        "nla_source_type": None,
        "nla_source_type_type": None,
        "nla_canonical_name": None,
        "nla_canonical_name_type": None,
    }
    for tags in ("{", "{}", '["Magic",7]'):
        with pytest.raises(ReconciliationDataError, match="stored Product tags"):
            reconciliation._taxonomy_inputs(
                _RowsConnection([{**base, "tags_json": tags}], [])  # type: ignore[arg-type]
            )


def test_runtime_variant_storage_boundaries_fail_closed() -> None:
    for value, message in (("{", "selected options"), ("{}", "selected options")):
        row = {**_stored_variant(), "selected_options_json": value}
        with pytest.raises(ReconciliationDataError, match=message):
            reconciliation._runtime_variant(row)  # type: ignore[arg-type]
    with pytest.raises(ReconciliationDataError, match="cannot enter runtime contract"):
        reconciliation._runtime_variant(  # type: ignore[arg-type]
            {**_stored_variant(), "inventory_policy": "HOSTILE"}
        )


def _one_product_taxonomy(
    product_gid: str = _gid("Product", PRODUCT_ONE),
) -> tuple[ProductFacts, object]:
    fact = ProductFacts(
        product_gid=product_gid,
        explicit_game="magic",
        product_type="Magic Display",
        commercial_title="Synthetic Display",
    )
    classifications, _report = classify_catalog((fact,), load_taxonomy())
    return fact, classifications[0]


def test_runtime_projection_rejects_order_missing_invalid_and_leftover_rows() -> None:
    fact, classification = _one_product_taxonomy()
    with pytest.raises(ReconciliationDataError, match="order do not reconcile"):
        other_fact, other_classification = _one_product_taxonomy(_gid("Product", PRODUCT_TWO))
        reconciliation._runtime_records(
            _RowsConnection([_stored_product()], [_stored_variant()]),  # type: ignore[arg-type]
            PUBLICATION,
            (other_fact,),
            (other_classification,),  # type: ignore[arg-type]
        )
    with pytest.raises(ReconciliationDataError, match="has no reconciled"):
        reconciliation._runtime_records(
            _RowsConnection([_stored_product()], []),  # type: ignore[arg-type]
            PUBLICATION,
            (fact,),
            (classification,),  # type: ignore[arg-type]
        )
    with pytest.raises(ReconciliationDataError, match="Product cannot enter"):
        reconciliation._runtime_records(
            _RowsConnection([{**_stored_product(), "status": "HOSTILE"}], [_stored_variant()]),  # type: ignore[arg-type]
            PUBLICATION,
            (fact,),
            (classification,),  # type: ignore[arg-type]
        )
    with pytest.raises(ReconciliationDataError, match="accounting mismatch"):
        reconciliation._runtime_records(
            _RowsConnection(
                [_stored_product()],
                [_stored_variant(), _stored_variant(_gid("Product", PRODUCT_TWO))],
            ),  # type: ignore[arg-type]
            PUBLICATION,
            (fact,),
            (classification,),  # type: ignore[arg-type]
        )


def test_runtime_manifest_and_top_level_failures_are_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _inputs(tmp_path / "valid")
    result = reconcile_snapshot_parts(
        inputs, expectation=_expectation(), taxonomy_config=load_taxonomy()
    )
    bad_report = replace(result.taxonomy_report, total=result.taxonomy_report.total + 1)
    with pytest.raises(ReconciliationDataError, match="taxonomy report"):
        reconciliation._runtime_manifest(result.source_manifest, result.records, bad_report)

    monkeypatch.setattr(
        reconciliation,
        "classify_catalog",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("hostile taxonomy")),
    )
    with pytest.raises(ReconciliationDataError, match="taxonomy rejected"):
        reconcile_snapshot_parts(
            inputs, expectation=_expectation(), taxonomy_config=load_taxonomy()
        )


def test_sqlite_failures_are_normalized(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sqlite3,
        "connect",
        lambda *_args: (_ for _ in ()).throw(sqlite3.OperationalError("hostile sqlite")),
    )
    with pytest.raises(ReconciliationDataError, match="reconciliation failed"):
        reconcile_snapshot_parts(
            _inputs(tmp_path), expectation=_expectation(), taxonomy_config=load_taxonomy()
        )
