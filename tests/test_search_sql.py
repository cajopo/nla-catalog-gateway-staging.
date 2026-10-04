from __future__ import annotations

import base64
import hashlib
import hmac
import sqlite3
import stat
from contextlib import closing
from dataclasses import replace
from pathlib import Path

import pytest

import nla_catalog_gateway.pagination as pagination
from nla_catalog_gateway.canonical_search import CanonicalSearchError
from nla_catalog_gateway.pagination import (
    CatalogProjection,
    CursorCodecV1,
    CursorContextMismatchError,
    DatasetUnavailableError,
    InvalidCursorError,
    PaginationContractError,
    StaleGenerationError,
    UnsupportedPaginationRequestError,
)
from nla_catalog_gateway.runtime_contract import CatalogFiltersV1, ProductStatus, RequestFamily
from nla_catalog_gateway.search_sql import search_facts, search_scope
from nla_catalog_gateway.taxonomy import Game, ProductFamily
from test_pagination import HMAC_KEY, NOW, _paginator, _projection, _record, _request


def card(number: int, name: str, *, code: str | None = None, stock: int = 0):
    record = _record(str(number))
    variant = replace(record.variants[0], sku=code, inventory_quantity=stock)
    return replace(record, canonical_card_name=name, variants=(variant,), total_inventory=stock)


@pytest.fixture
def projection(tmp_path: Path) -> CatalogProjection:
    codes = card(4, "Different name", code="OP05-119")
    codes = replace(codes, variants=(replace(codes.variants[0], barcode="001234"),))
    duplicate = card(10, "BOLT", stock=3)
    duplicate = replace(
        duplicate,
        variants=(
            replace(duplicate.variants[0], sku="OP05-119"),
            replace(
                duplicate.variants[0],
                variant_gid="gid://shopify/ProductVariant/100",
                inventory_item_gid="gid://shopify/InventoryItem/100",
                sku="OP05-119",
            ),
        ),
    )
    return _projection(
        tmp_path,
        (
            card(1, "Bolt"),
            card(2, "Bolt Adept", stock=1),
            card(3, "Thunder Bolt", stock=-1),
            codes,
            replace(card(5, "Bolt", code="OP05-119"), game=Game.POKEMON),
            replace(card(6, "Bolt"), online_store_published=False),
            replace(card(7, "Bolt"), shopify_status=ProductStatus.DRAFT),
            replace(card(8, "Unrelated"), commercial_title="Bolt OP05-119"),
            card(9, "Literal", code="%_'/[]"),
            duplicate,
        ),
    )


def request(query: str | None, *, size: int = 100):
    return _request(family=RequestFamily.SINGLE, query=query, page_size=size)


def ids(projection: CatalogProjection, query: str) -> list[int]:
    page = _paginator(projection).fetch_page(request(query)).page
    return [int(item.product_gid.rsplit("/", 1)[1]) for item in page.items]


def test_name_contains_keeps_exact_prefix_other_substrings_and_sold_out(projection):
    assert ids(projection, " BOLT ") == [1, 2, 3, 10]
    assert ids(projection, "olt") == [1, 2, 3, 10]
    assert ids(projection, " OP05-119 ") == [4, 10]
    assert ids(projection, "05-1") == [4, 10]
    assert ids(projection, "123") == [4]
    assert ids(projection, "nonexistent") == []


@pytest.mark.parametrize("field", ["sku", "barcode"])
def test_nul_source_code_rejects_candidate_instead_of_silently_truncating(tmp_path, field):
    record = card(1, "Card")
    record = replace(record, variants=(replace(record.variants[0], **{field: "ABC\x00OP05-119"}),))
    with pytest.raises(CanonicalSearchError, match="unsupported NUL"):
        _projection(tmp_path, (record,))
    assert not list(tmp_path.glob("*.sqlite3"))


@pytest.mark.parametrize("name", ["x" * 1025, "\ufb03" * 342])
def test_public_single_name_bounds_survive_removal_of_legacy_runtime_index(tmp_path, name):
    with pytest.raises(CanonicalSearchError, match="canonical name"):
        _projection(tmp_path, (card(1, name),))


def test_search_facts_reject_missing_public_name():
    record = card(1, "Name")
    object.__setattr__(record, "canonical_card_name", None)
    with pytest.raises(CanonicalSearchError, match="canonical name"):
        search_facts(record)


def test_all_family_stock_filter_keeps_singles_and_sealed_without_game_leakage(tmp_path):
    projection = _projection(
        tmp_path,
        (
            _record("1"),
            _record("2", family=ProductFamily.SEALED),
            _record("3", family=ProductFamily.SEALED, game=Game.POKEMON),
        ),
    )
    page = _paginator(projection).fetch_page(_request(family=RequestFamily.ALL, in_stock=True))
    assert [item.product_gid for item in page.page.items] == [
        "gid://shopify/Product/1",
        "gid://shopify/Product/2",
    ]


@pytest.mark.parametrize("query", ["%", "_", "'", "/", "[", "]", "%_'/[]"])
def test_punctuation_is_literal_not_sql_or_pattern_syntax(projection, query):
    assert ids(projection, query) == [9]


def test_suggestions_are_bounded_grouped_scoped_and_include_sold_out(projection):
    suggestions = projection.suggest(request("bolt"), limit=2)
    assert [item.normalized_card_name for item in suggestions] == ["bolt", "bolt adept"]
    assert suggestions[0].print_count == 2
    assert suggestions[0].available_print_count == 1
    codes = projection.suggest(request("05-1"))
    assert sum(item.print_count for item in codes) == 2  # Not three matching Variants.
    assert any(not item.available for item in codes)
    assert projection.suggest(request("   ")) == ()
    assert projection.suggest(request("missing")) == ()


def test_search_and_suggestions_apply_same_stock_filter(projection):
    selected = replace(request("bolt"), filters=_request(in_stock=True).filters)
    page = _paginator(projection).fetch_page(selected).page
    assert [item.product_gid for item in page.items] == [
        "gid://shopify/Product/2",
        "gid://shopify/Product/10",
    ]
    assert sum(item.print_count for item in projection.suggest(selected)) == 2
    sold_out = replace(selected, filters=_request(in_stock=False).filters)
    assert sum(item.print_count for item in projection.suggest(sold_out)) == 2


def test_sealed_subtype_filter_uses_the_shared_sql_path(tmp_path):
    projection = _projection(tmp_path, (_record("1", family=ProductFamily.SEALED),))
    selected = replace(
        _request(family=RequestFamily.SEALED),
        filters=CatalogFiltersV1(None, "booster-box"),
    )
    assert _paginator(projection).fetch_page(selected).page.returned_product_count == 1
    absent = replace(selected, filters=CatalogFiltersV1(None, "not-present"))
    assert _paginator(projection).fetch_page(absent).page.items == ()


def test_search_cursors_bind_query_game_generation_and_new_semantics(projection):
    paginator = _paginator(projection)
    selected = request("bolt", size=1)
    first = paginator.fetch_page(selected)
    cursor = first.next_cursor
    assert cursor is not None
    second = paginator.fetch_page(selected, cursor=cursor)
    assert second.page.items[0].product_gid == "gid://shopify/Product/2"
    for changed in (request("05-1", size=1), replace(selected, game=Game.POKEMON)):
        with pytest.raises(CursorContextMismatchError):
            paginator.fetch_page(changed, cursor=cursor)
    codec = CursorCodecV1(HMAC_KEY)
    with pytest.raises(StaleGenerationError):
        codec.decode(
            cursor, expected_request=selected, now=NOW, expected_generation="sha256:" + "f" * 64
        )
    context = first.page.next_cursor_context
    assert context is not None
    assert context.request_context_dict()["searchSemanticsVersion"] == 2
    raw = context.to_json_bytes()
    old_signature = hmac.new(HMAC_KEY, raw, hashlib.sha256).digest()
    old_token = ".".join(
        base64.urlsafe_b64encode(part).decode().rstrip("=") for part in (raw, old_signature)
    )
    with pytest.raises(InvalidCursorError):
        paginator.fetch_page(selected, cursor=old_token)


@pytest.mark.parametrize("limit", [0, 21, True, "10"])
def test_suggestion_limit_is_validated(projection, limit):
    with pytest.raises(CanonicalSearchError):
        projection.suggest(request("bolt"), limit=limit)


def test_query_limits_family_and_cancellation(projection):
    for query in ("a" * 257, "\ufdfa" * 256):
        with pytest.raises(PaginationContractError):
            _paginator(projection).fetch_page(request(query))
    with pytest.raises(UnsupportedPaginationRequestError):
        projection.suggest(_request())
    with pytest.raises(PaginationContractError):
        projection.suggest(request("bolt"), checkpoint=1)

    def cancel():
        raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError, match="cancelled"):
        projection.suggest(request("bolt"), checkpoint=cancel)


def test_suggestion_sql_cancellation_preserves_original_exception(projection, monkeypatch):
    cancelled = RuntimeError("cancelled during SQL")
    active = False

    def checkpoint():
        if active:
            raise cancelled

    def slow_query(connection, request, *, limit):
        nonlocal active
        active = True
        connection.execute(
            """WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL
               SELECT x+1 FROM n WHERE x<100000) SELECT sum(x) FROM n"""
        ).fetchone()

    monkeypatch.setattr(pagination, "select_suggestions", slow_query)
    with pytest.raises(RuntimeError) as caught:
        projection.suggest(request("bolt"), checkpoint=checkpoint)
    assert caught.value is cancelled


def test_suggestion_sql_failure_is_bounded(projection, monkeypatch):
    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("private detail")

    monkeypatch.setattr(pagination, "select_suggestions", fail)
    with pytest.raises(DatasetUnavailableError, match="catalog dataset is unavailable"):
        projection.suggest(request("bolt"))


def test_suggestion_cancellation_after_query(projection, monkeypatch):
    active = False

    def finish(*args, **kwargs):
        nonlocal active
        active = True
        return ()

    def checkpoint():
        if active:
            raise RuntimeError("cancelled after query")

    monkeypatch.setattr(pagination, "select_suggestions", finish)
    with pytest.raises(RuntimeError, match="cancelled after query"):
        projection.suggest(request("bolt"), checkpoint=checkpoint)


@pytest.mark.parametrize(
    "column,value",
    [
        ("normalized_card_name", "wrong"),
        ("search_codes_json", '["fabricated"]'),
        ("has_positive_inventory", 1),
    ],
)
def test_search_columns_are_verified_against_source_records(projection, column, value):
    projection.path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    with closing(sqlite3.connect(projection.path)) as connection:
        connection.execute(
            f"UPDATE products SET {column} = ? WHERE product_gid_digits = '1'",  # noqa: S608
            (value,),
        )
        connection.commit()
    projection.path.chmod(stat.S_IRUSR)
    with pytest.raises(DatasetUnavailableError):
        CatalogProjection.open(projection.path)


def test_literal_search_traverses_30001_with_indexed_keyset(tmp_path):
    projection = _projection(
        tmp_path, tuple(card(n, "Shared card", code="TEST-001") for n in range(1, 30002))
    )
    paginator = _paginator(projection)
    selected = request("st-00")  # Code-only match, every record sold out.
    cursor = None
    actual = []
    while True:
        result = paginator.fetch_page(selected, cursor=cursor)
        actual.extend(int(item.product_gid.rsplit("/", 1)[1]) for item in result.page.items)
        cursor = result.next_cursor
        if cursor is None:
            break
    assert actual == list(range(1, 30002))
    assert actual[24998:25001] == [24999, 25000, 25001]
    assert projection.suggest(selected)[0].print_count == 30001
    where, parameters = search_scope(selected)
    with closing(sqlite3.connect(projection.path)) as connection:
        plan = connection.execute(
            f"""EXPLAIN QUERY PLAN SELECT product_gid FROM products WHERE {where}
                AND (product_gid_length, product_gid_digits) > (?, ?)
                ORDER BY product_gid_length, product_gid_digits LIMIT ?""",  # noqa: S608
            (*parameters, 5, "25000", 101),
        ).fetchall()
    details = " ".join(str(row[-1]) for row in plan)
    assert "products_public_game_family_order" in details
    assert "TEMP B-TREE" not in details
