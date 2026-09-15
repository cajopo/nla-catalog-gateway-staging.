from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest

import test_canonical_names as sources
import test_core_evidence as proof
import test_reconciliation as reconcile
from nla_catalog_gateway.canonical_names import CanonicalNameRecordV1, CanonicalNamesError
from nla_catalog_gateway.card_metadata import CardMetadataV1
from nla_catalog_gateway.core_evidence import verify_catalog_core_evidence
from nla_catalog_gateway.pagination import CatalogProjection
from nla_catalog_gateway.runtime_contract import (
    CatalogItemV1,
    CatalogProductRecordV1,
    RuntimeContractError,
)
from nla_catalog_gateway.taxonomy import Game, ProductFamily, load_taxonomy
from test_pagination import _paginator, _projection
from test_search_sql import card, ids, request

META = CardMetadataV1("019a/%_", "EXP", "Expansion not a card name", "Rare")


def enriched(number=1, *, metadata=META, **kwargs):
    return replace(
        card(number, "Different card", **kwargs),
        sync_source_id=str(number),
        powertools_source_id=str(number),
        card_metadata=metadata,
    )


@pytest.mark.parametrize("field", list(CardMetadataV1.FIELDS))
@pytest.mark.parametrize("value", [1, True, [], "", "a\x01b", "a\x00b", "\ud800", "x" * 1025])
def test_metadata_rejects_bad_values(field, value):
    raw = META.as_dict()
    raw[field] = value
    with pytest.raises(ValueError):
        CardMetadataV1.from_dict(raw)


@pytest.mark.parametrize("value", [None, [], {}, {**META.as_dict(), "extra": 1}])
def test_metadata_requires_exact_fields(value):
    with pytest.raises(ValueError):
        CardMetadataV1.from_dict(value)


def test_source_record_extension_preserves_legacy_bytes_and_raw_values():
    legacy = CanonicalNameRecordV1(Game.MAGIC, "1", "Card")
    assert "cardMetadata" not in legacy.as_dict()
    current = replace(legacy, card_metadata=META)
    assert CanonicalNameRecordV1.from_json_bytes(current.to_json_bytes()) == current
    assert CardMetadataV1(None, None, None, None).as_dict() == dict.fromkeys(META.FIELDS)
    with pytest.raises(CanonicalNamesError):
        replace(legacy, card_metadata={})
    raw = current.as_dict()
    raw["cardMetadata"] = None
    with pytest.raises(CanonicalNamesError):
        CanonicalNameRecordV1.from_json_bytes(sources._canonical_json(raw))


def test_maximum_unicode_source_record_round_trips():
    text = "\U0001f30d" * 1024
    metadata = CardMetadataV1(text, text, text, text)
    record = CanonicalNameRecordV1(Game.MAGIC, "1", text, metadata)
    raw = record.to_json_bytes()
    assert 8192 < len(raw) <= sources.names.MAX_RECORD_BYTES
    assert CanonicalNameRecordV1.from_json_bytes(raw) == record


@pytest.mark.parametrize("number", [" ", "MET\t"])
def test_real_source_whitespace_is_preserved_and_search_normalized(tmp_path, number):
    record = enriched(metadata=replace(META, collector_number=number))
    assert CatalogProductRecordV1.from_json_bytes(record.to_json_bytes()) == record
    projection = _projection(tmp_path, (record,))
    assert ids(projection, "MET") == ([1] if number.strip() else [])


def test_runtime_and_public_extensions_round_trip():
    record = enriched()
    assert CatalogProductRecordV1.from_json_bytes(record.to_json_bytes()) == record
    item = CatalogItemV1.from_product_record(record)
    assert item.card_metadata == META
    assert CatalogItemV1.from_json_bytes(item.to_json_bytes()) == item
    legacy = replace(record, card_metadata=None)
    assert "cardMetadata" not in legacy.as_dict()
    assert "cardMetadata" not in CatalogItemV1.from_product_record(legacy).as_dict()
    for dto in (record, item):
        raw = dto.as_dict()
        raw["cardMetadata"] = None
        with pytest.raises(RuntimeContractError):
            type(dto).from_dict(raw)
        raw["cardMetadata"] = {**META.as_dict(), "inventedCode": "X"}
        with pytest.raises(RuntimeContractError):
            type(dto).from_dict(raw)


def test_metadata_requires_single_and_source_identity():
    record = enriched()
    with pytest.raises(RuntimeContractError):
        replace(record, sync_source_id=None, powertools_source_id=None)
    for dto in (record, CatalogItemV1.from_product_record(record)):
        with pytest.raises(RuntimeContractError):
            replace(dto, card_metadata={})
        with pytest.raises(RuntimeContractError):
            replace(dto, product_family=ProductFamily.ACCESSORY)


def test_csv_compiler_retains_card_fields(tmp_path):
    paths, _ = sources._write_sources(tmp_path, {Game.MAGIC: [("1", "Different card")]})
    paths[Game.MAGIC].write_text(
        ",".join(sources.CSV_HEADER) + "\n1,Different card,019a/%_,Rare,Expansion,EXP,,\n",
        encoding="utf-8",
    )
    records, _ = sources.names._load_csv_source(paths[Game.MAGIC], Game.MAGIC)
    assert records[0].card_metadata == replace(META, expansion_name="Expansion")
    paths[Game.MAGIC].write_text(
        ",".join(sources.CSV_HEADER) + '\n1,Different card,"a\x01b",Rare,Expansion,EXP,,\n',
        encoding="utf-8",
    )
    with pytest.raises(CanonicalNamesError):
        sources.names._load_csv_source(paths[Game.MAGIC], Game.MAGIC)


def test_source_metadata_reconciles_by_identity_and_preserves_all_products(tmp_path):
    original = reconcile._canonical_names_input()
    source = replace(next(iter(original.records.values())), card_metadata=META)
    raw = source.to_json_bytes() + b"\n"
    manifest = replace(
        original.manifest,
        sidecar=replace(
            original.manifest.sidecar, byte_count=len(raw), sha256=hashlib.sha256(raw).hexdigest()
        ),
    )
    names = replace(
        original,
        manifest=manifest,
        manifest_sha256=manifest.manifest_sha256,
        records={(source.game, source.source_id): source},
    )
    products, variants = reconcile._rows()
    for row in products:
        if row["__typename"] == "Product":
            row["productType"] = "Magic Single"
    result = reconcile.reconcile_snapshot_parts(
        reconcile._inputs(tmp_path, products=products, variants=variants),
        expectation=reconcile._expectation(),
        taxonomy_config=load_taxonomy(),
        canonical_names=names,
    )
    assert len(result.records) == 2
    assert all(r.card_metadata == META for r in result.records)
    assert all(
        r.sync_source_id == r.powertools_source_id == source.source_id for r in result.records
    )
    assert result.dataset_manifest.included_product_count == 2
    assert result.canonical_name_audit.matched_product_count == 2


def test_source_type_classified_single_outside_optional_join_is_not_dropped(tmp_path):
    products, variants = reconcile._rows()
    for index, row in enumerate(list(products)):
        if row["__typename"] == "Product":
            row["productType"] = ""
            row["syncProductId"]["value"] = "123"
            row["powertoolsId"]["value"] = "123"
            products.extend(
                [
                    reconcile._metafield(row["id"], 100 + index, "source_record_type", "single"),
                    reconcile._metafield(
                        row["id"], 200 + index, "canonical_card_name", "Already known"
                    ),
                ]
            )
    result = reconcile.reconcile_snapshot_parts(
        reconcile._inputs(tmp_path, products=products, variants=variants),
        expectation=reconcile._expectation(),
        taxonomy_config=load_taxonomy(),
        canonical_names=reconcile._canonical_names_input(expected_products=0),
    )
    assert len(result.records) == 2
    assert all(r.product_family is ProductFamily.SINGLE for r in result.records)
    assert all(r.card_metadata is None for r in result.records)
    assert result.canonical_name_audit.matched_product_count == 0


def test_sql_code_search_suggestions_and_pages_include_sold_out(tmp_path):
    records = (
        enriched(1),
        enriched(2, stock=2),
        replace(enriched(3), game=Game.POKEMON),
        replace(enriched(4), online_store_published=False),
        replace(card(5, "Other"), commercial_title="019a/%_"),
        enriched(6, metadata=replace(META, collector_number=None)),
    )
    projection = _projection(tmp_path, records)
    assert ids(projection, "19A/%_") == [1, 2]
    assert ids(projection, "EXP") == []
    assert ids(projection, "Rare") == []
    assert ids(projection, "Different") == [1, 2, 6]
    (suggestion,) = projection.suggest(request("19a/%_"), limit=10)
    assert (suggestion.print_count, suggestion.available_print_count) == (2, 1)
    paginator = _paginator(projection)
    first = paginator.fetch_page(request("19a/%_", size=1))
    second = paginator.fetch_page(request("19a/%_", size=1), cursor=first.next_cursor)
    assert [p.items[0].product_gid for p in (first.page, second.page)] == [
        records[0].product_gid,
        records[1].product_gid,
    ]
    assert second.next_cursor is None
    assert all(p.items[0].card_metadata == META for p in (first.page, second.page))
    reopened = CatalogProjection.open(projection.path)
    assert ids(reopened, "19a/%_") == [1, 2]


def test_core_proof_checks_source_collector_codes(tmp_path):
    records = tuple(
        replace(r, card_metadata=META) if r.product_family is ProductFamily.SINGLE else r
        for r in proof._records()
    )
    result = verify_catalog_core_evidence(
        proof._verified(records),
        projection_path=tmp_path / "proof.sqlite3",
        code_sha=proof.CODE_SHA,
    )
    assert (
        result.catalog_content_sha256
        == proof._verified(records).generation.dataset_manifest.catalog_content_sha256
    )
