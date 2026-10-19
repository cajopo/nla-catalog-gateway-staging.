"""Verified card codes share one predicate across pages, suggestions and facets."""

from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest

import test_core_evidence as evidence
from nla_catalog_gateway.card_metadata import CardMetadataV1
from nla_catalog_gateway.core_evidence import verify_catalog_core_evidence
from nla_catalog_gateway.pagination import CatalogProjection, CursorContextMismatchError
from nla_catalog_gateway.runtime_contract import CatalogFiltersV1, ProductStatus, RequestFamily
from nla_catalog_gateway.taxonomy import Game, ProductFamily
from test_pagination import _paginator, _projection, _record
from test_search_sql import card, ids, request

META = CardMetadataV1("88", "FIN", "Final Fantasy", "Rare")


def printing(number, *, metadata=META, **kwargs):
    return replace(
        card(number, "Verified card", **kwargs),
        sync_source_id=str(number),
        powertools_source_id=str(number),
        card_metadata=metadata,
    )


@pytest.fixture
def code_projection(tmp_path):
    return _projection(
        tmp_path,
        (
            printing(1, code="FIN88-111"),
            printing(2, code="FIN88-222", stock=2),
            printing(3, code="OTHER88-333", metadata=replace(META, expansion_code="OTHER")),
            printing(4, code="FIN89-444", metadata=replace(META, collector_number="89")),
            printing(5, metadata=None),
            printing(6, metadata=replace(META, collector_number=None)),
            printing(7, metadata=replace(META, expansion_code=None)),
            replace(printing(8, code="FIN88-888"), online_store_published=False),
            replace(printing(9, code="FIN88-999"), shopify_status=ProductStatus.DRAFT),
            replace(printing(10, code="FIN88-1010"), game=Game.POKEMON),
            replace(card(11, "Unrelated card"), commercial_title="FIN88"),
            replace(_record("12", family=ProductFamily.UNCLASSIFIED), commercial_title="FIN88"),
            replace(_record("13", family=ProductFamily.SEALED), commercial_title="Other display"),
            printing(
                14,
                code="FIN88-1414",
                metadata=replace(META, expansion_code=" \tFIN ", collector_number="88\t"),
            ),
        ),
    )


@pytest.mark.parametrize(
    "query", ["FIN88", "FIN-88", "fin88", "  fIn-88  ", "\uff26\uff29\uff2e\uff0d\uff18\uff18"]
)
def test_full_source_code_accepts_both_spellings(code_projection, query):
    assert ids(code_projection, query) == [1, 2, 14]
    suggestions = code_projection.suggest(request(query))
    assert [
        (s.canonical_card_name, s.print_count, s.available_print_count) for s in suggestions
    ] == [("Verified card", 3, 1)]
    all_request = replace(request(query), product_family=RequestFamily.ALL)
    assert [
        p.product_gid for p in _paginator(code_projection).fetch_page(all_request).page.items
    ] == [
        "gid://shopify/Product/1",
        "gid://shopify/Product/2",
        "gid://shopify/Product/14",
    ]


@pytest.mark.parametrize("query", ["FIN8", "FIN-8", "IN88", "IN-88", "N8"])
def test_partial_code_accepts_both_spellings(code_projection, query):
    expected = [1, 2, 4, 14] if query in ("FIN8", "FIN-8", "N8") else [1, 2, 14]
    assert ids(code_projection, query) == expected


@pytest.mark.parametrize("query", ["Final Fantasy", "Rare", "FIN%' OR 1=1 --"])
def test_display_metadata_and_sql_syntax_do_not_become_code_matches(code_projection, query):
    assert ids(code_projection, query) == []
    assert code_projection.suggest(request(query)) == ()


@pytest.mark.parametrize("field", ["collector_number", "expansion_code"])
@pytest.mark.parametrize("value", [None, " \t", "---"])
def test_missing_or_blank_code_components_never_create_a_combined_code(tmp_path, field, value):
    projection = _projection(tmp_path, (printing(1, metadata=replace(META, **{field: value})),))
    assert ids(projection, "FIN88") == []
    assert ids(projection, "FIN-88") == []


@pytest.mark.parametrize("source", ["sku", "barcode", "collector"])
@pytest.mark.parametrize("code", ["OP05-119", "OP05119"])
def test_retained_source_codes_accept_both_spellings(tmp_path, source, code):
    record = card(1, "Other card")
    if source == "collector":
        record = replace(
            record,
            sync_source_id="1",
            powertools_source_id="1",
            card_metadata=CardMetadataV1(code, None, None, None),
        )
    else:
        record = replace(record, variants=(replace(record.variants[0], **{source: code}),))
    projection = _projection(tmp_path, (record,))
    for query in ("OP05-119", "OP05119", "op05119", "0511", "05-11"):
        assert ids(projection, query) == [1]
        assert sum(s.print_count for s in projection.suggest(request(query))) == 1


def test_names_and_non_hyphen_punctuation_remain_literal(tmp_path):
    projection = _projection(
        tmp_path,
        (
            card(1, "Re-animate"),
            card(2, "Unrelated", code="A/B-01"),
            card(3, "Another", code="---"),
            printing(4, code="FIN088", metadata=replace(META, collector_number="088")),
        ),
    )
    assert ids(projection, "reanimate") == []
    assert ids(projection, "re-animate") == [1]
    assert ids(projection, "A/B01") == [2]
    assert ids(projection, "AB01") == []
    assert ids(projection, "-") == [1, 2, 3]
    assert ids(projection, "---") == [3]
    assert ids(projection, "FIN88") == []  # Source leading zero is not invented away.
    assert ids(projection, "FIN088") == [4]


@pytest.mark.parametrize("query", ["FIN88", "FIN-88"])
def test_code_filters_facets_and_complete_keyset_traversal_agree(code_projection, query):
    selected = request(query, size=1)
    paginator = _paginator(code_projection)
    seen = []
    cursor = None
    while True:
        result = paginator.fetch_page(selected, cursor=cursor)
        seen.extend(item.product_gid for item in result.page.items)
        cursor = result.next_cursor
        if cursor is None:
            break
    assert seen == [
        "gid://shopify/Product/1",
        "gid://shopify/Product/2",
        "gid://shopify/Product/14",
    ]
    available = replace(selected, filters=CatalogFiltersV1(True, None, expansion_code="FIN"))
    assert [p.product_gid for p in paginator.fetch_page(available).page.items] == [
        "gid://shopify/Product/2"
    ]
    assert sum(s.print_count for s in code_projection.suggest(available)) == 1
    facets = code_projection.metadata_facets(selected)
    assert [{v.value: v.count for v in facet.values} for facet in facets] == [
        {" \tFIN ": 1, "FIN": 2},
        {"Rare": 3},
    ]
    other = "FIN-88" if query == "FIN88" else "FIN88"
    first = paginator.fetch_page(selected)
    with pytest.raises(CursorContextMismatchError):
        paginator.fetch_page(replace(selected, query=other), cursor=first.next_cursor)


def test_code_search_reuses_the_verified_database_without_rewriting_facts(code_projection):
    before = hashlib.sha256(code_projection.path.read_bytes()).hexdigest()
    reopened = CatalogProjection.open(code_projection.path)
    assert ids(reopened, "FIN88") == [1, 2, 14]
    assert ids(reopened, "FIN-88") == [1, 2, 14]
    assert hashlib.sha256(code_projection.path.read_bytes()).hexdigest() == before


def test_metadata_does_not_invent_a_full_code_when_the_source_has_none(tmp_path):
    projection = _projection(tmp_path, (printing(1),))
    assert ids(projection, "88") == [1]
    assert ids(projection, "FIN") == []
    assert ids(projection, "FIN88") == []
    assert ids(projection, "FIN-88") == []


def test_core_gate_checks_hyphen_only_codes_without_broadening_to_unrelated_records(tmp_path):
    records = tuple(
        replace(record, variants=(replace(record.variants[0], sku="---"),))
        if record.product_gid.rsplit("/", 1)[1] in {"1", "8", "15", "22"}
        else record
        for record in evidence._records()
    )
    verified = evidence._verified(records)
    result = verify_catalog_core_evidence(
        verified, projection_path=tmp_path / "core.sqlite3", code_sha=evidence.CODE_SHA
    )
    assert result.dataset_generation == verified.generation.dataset_manifest.dataset_generation
