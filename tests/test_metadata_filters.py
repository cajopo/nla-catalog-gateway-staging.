from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from nla_catalog_gateway.card_metadata import CardMetadataV1
from nla_catalog_gateway.pagination import CursorContextMismatchError
from nla_catalog_gateway.runtime_contract import (
    CatalogFiltersV1,
    CatalogRequestV1,
    CursorContextV1,
    RequestFamily,
    RuntimeContractError,
)
from nla_catalog_gateway.taxonomy import Game
from test_pagination import _paginator, _projection, _request
from test_search_sql import card, request


def selected(*, expansion=None, rarity=None, stock=None, query="Bolt", size=100):
    return replace(
        request(query, size=size),
        filters=CatalogFiltersV1(stock, None, expansion_code=expansion, rarity=rarity),
    )


def metadata_card(number, name="Bolt", *, expansion="SET", rarity="Rare", stock=0):
    return replace(
        card(number, name, stock=stock),
        sync_source_id=str(number),
        powertools_source_id=str(number),
        card_metadata=CardMetadataV1(None, expansion, "Source set name", rarity),
    )


@pytest.fixture
def metadata_projection(tmp_path):
    return _projection(
        tmp_path,
        (
            metadata_card(1),
            metadata_card(2, "Bolt Adept", stock=2),
            metadata_card(3, "Bolt Variant", expansion="OTHER"),
            metadata_card(4, "Bolt Common", rarity="Common"),
            replace(metadata_card(5), game=Game.POKEMON),
            replace(metadata_card(6), online_store_published=False),
            card(7, "Bolt Without Metadata"),
            metadata_card(8, "Bolt Lowercase", expansion="set", rarity="rare"),
            metadata_card(9, "Bolt Literal", expansion="é%_'[]/", rarity="超 Rare ' %"),
            metadata_card(10, "Bolt Missing Fields", expansion=None, rarity=None),
        ),
    )


def product_ids(projection, chosen):
    return [
        int(item.product_gid.rsplit("/", 1)[1])
        for item in _paginator(projection).fetch_page(chosen).page.items
    ]


def test_metadata_extensions_leave_legacy_request_and_cursor_vectors_unchanged():
    vectors = json.loads(
        Path(__file__)
        .with_name("fixtures")
        .joinpath("runtime_contract_v1_golden.json")
        .read_text(encoding="utf-8")
    )
    for name, kind in (
        ("CatalogRequestV1", CatalogRequestV1),
        ("CursorContextV1", CursorContextV1),
    ):
        raw = vectors[name]["canonicalJson"].encode("utf-8")
        parsed = kind.from_json_bytes(raw)
        assert parsed.to_json_bytes() == raw
        assert hashlib.sha256(parsed.to_json_bytes()).hexdigest() == vectors[name]["sha256"]
    cursor = CursorContextV1.from_json_bytes(vectors["CursorContextV1"]["canonicalJson"].encode())
    assert (
        cursor.request_context_sha256
        == "20bf2b54e5b054d75ac671d892ef2e5e11b3075420917449afdfe38252c35c2c"
    )
    assert CatalogFiltersV1(None, None).as_dict() == {"inStock": None, "productSubtype": None}
    assert not CatalogFiltersV1(None, None).nonempty


@pytest.mark.parametrize("field,wire", [("expansion_code", "expansionCode"), ("rarity", "rarity")])
def test_optional_metadata_fields_roundtrip_without_other_absent_key(field, wire):
    filters = CatalogFiltersV1(None, None, **{field: "Éxact %_'[]/"})
    assert filters.nonempty
    assert filters.as_dict() == {"inStock": None, "productSubtype": None, wire: "Éxact %_'[]/"}
    assert CatalogFiltersV1.from_dict(filters.as_dict()) == filters
    assert CatalogFiltersV1(None, None, **{field: "x" * 1024}).nonempty
    # Preserve raw values, including allowed whitespace, rather than silently normalizing.
    raw = " Source\t\r\n value "
    assert CatalogFiltersV1(None, None, **{field: raw}).as_dict()[wire] == raw


@pytest.mark.parametrize("field,wire", [("expansion_code", "expansionCode"), ("rarity", "rarity")])
@pytest.mark.parametrize("value", ["", "x" * 1025, "bad\x00", "bad\x1f", "\ud800", 7, True, [], {}])
def test_invalid_metadata_filters_fail_closed(field, wire, value):
    with pytest.raises(RuntimeContractError):
        CatalogFiltersV1(None, None, **{field: value})
    with pytest.raises(RuntimeContractError):
        CatalogFiltersV1.from_dict({"inStock": None, "productSubtype": None, wire: value})


@pytest.mark.parametrize("wire", ["expansionCode", "rarity"])
def test_explicit_null_metadata_extension_is_not_canonical(wire):
    with pytest.raises(RuntimeContractError):
        CatalogFiltersV1.from_dict({"inStock": None, "productSubtype": None, wire: None})


@pytest.mark.parametrize(
    "family", [RequestFamily.ALL, RequestFamily.SEALED, RequestFamily.ACCESSORY]
)
@pytest.mark.parametrize("extra", [{"expansion_code": "SET"}, {"rarity": "Rare"}])
def test_metadata_filters_only_apply_to_single_family(family, extra):
    with pytest.raises(RuntimeContractError):
        replace(_request(family=family), filters=CatalogFiltersV1(None, None, **extra))


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        ({"expansion": "SET"}, [1, 2, 4]),
        ({"rarity": "Rare"}, [1, 2, 3]),
        ({"expansion": "SET", "rarity": "Rare"}, [1, 2]),
        ({"expansion": "SET", "rarity": "Rare", "stock": True}, [2]),
        ({"expansion": "SET", "rarity": "Rare", "stock": False}, [1]),
        ({"expansion": "set", "rarity": "rare"}, [8]),
        ({"expansion": "Set"}, []),
        ({"expansion": "é%_'[]/", "rarity": "超 Rare ' %"}, [9]),
        ({"expansion": "e\u0301%_'[]/"}, []),
        ({"expansion": "%"}, []),
        ({"rarity": "Unknown"}, []),
        ({"expansion": "SET", "query": None}, [1, 2, 4]),
    ],
)
def test_metadata_filters_are_exact_scoped_and_composable(metadata_projection, kwargs, expected):
    assert product_ids(metadata_projection, selected(**kwargs)) == expected


def test_same_codes_in_other_game_never_leak(metadata_projection):
    chosen = selected(expansion="SET", rarity="Rare")
    assert product_ids(metadata_projection, replace(chosen, game=Game.POKEMON)) == [5]
    assert product_ids(metadata_projection, replace(chosen, game=Game.ONE_PIECE)) == []


def test_metadata_pagination_cursor_binds_both_filters(metadata_projection):
    paginator = _paginator(metadata_projection)
    chosen = selected(expansion="SET", rarity="Rare", size=1)
    first = paginator.fetch_page(chosen)
    assert first.page.items[0].product_gid == "gid://shopify/Product/1"
    assert first.next_cursor is not None
    last = paginator.fetch_page(chosen, cursor=first.next_cursor)
    assert last.page.items[0].product_gid == "gid://shopify/Product/2"
    assert last.next_cursor is None
    for changed in (
        selected(expansion="OTHER", rarity="Rare", size=1),
        selected(expansion="SET", rarity="Common", size=1),
        selected(expansion="SET", size=1),
        selected(rarity="Rare", size=1),
        replace(chosen, game=Game.POKEMON),
    ):
        with pytest.raises(CursorContextMismatchError):
            paginator.fetch_page(changed, cursor=first.next_cursor)


def test_suggestions_use_same_metadata_scope_and_keep_sold_out(metadata_projection):
    chosen = selected(expansion="SET", rarity="Rare")
    suggestions = metadata_projection.suggest(chosen)
    assert [item.normalized_card_name for item in suggestions] == ["bolt", "bolt adept"]
    assert sum(item.print_count for item in suggestions) == 2
    assert [item.available_print_count for item in suggestions] == [0, 1]
    stocked = metadata_projection.suggest(selected(expansion="SET", rarity="Rare", stock=True))
    assert [item.normalized_card_name for item in stocked] == ["bolt adept"]
    assert metadata_projection.suggest(selected(expansion="missing")) == ()
