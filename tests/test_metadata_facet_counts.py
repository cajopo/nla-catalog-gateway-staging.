"""SQL facets against the independent in-memory oracle and complete vocabularies."""

import json
import sqlite3
from dataclasses import replace

import pytest

import test_metadata_filters as metadata
from nla_catalog_gateway import pagination, search_sql
from nla_catalog_gateway.facets import (
    FacetDimension,
    evaluate_facets,
    parse_url_state,
    serialize_url_state,
    switch_family,
    switch_game,
)
from nla_catalog_gateway.pagination import (
    DatasetUnavailableError,
    PaginationContractError,
    UnsupportedPaginationRequestError,
)
from nla_catalog_gateway.runtime_contract import RequestFamily
from nla_catalog_gateway.taxonomy import Game
from test_metadata_filters import metadata_card, selected
from test_pagination import _paginator, _projection

metadata_projection = metadata.metadata_projection


def test_facet_scan_does_not_sort_large_product_payloads():
    with sqlite3.connect(":memory:") as database:
        database.execute(
            "CREATE TABLE products (game TEXT, product_family TEXT, is_public INTEGER, "
            "product_record_json BLOB)"
        )
        payload = json.dumps(
            {
                "cardMetadata": {"expansionCode": "SET", "rarity": "Rare"},
                "unrelatedPayload": "x" * 65536,
            }
        ).encode()
        database.executemany(
            "INSERT INTO products VALUES (?, 'single', 1, ?)",
            [
                ("magic", payload),
                ("magic", payload),
                ("pokemon", payload),
            ],
        )
        calls = []

        class Scan:
            def execute(self, sql, parameters):
                calls.append((sql, parameters))
                return database.execute(sql, parameters)

        facets = search_sql.select_metadata_facets(Scan(), selected(query=None))
        assert len(calls) == 1
        assert [(value.value, value.count) for value in facets[0].values] == [("SET", 2)]
        assert [(value.value, value.count) for value in facets[1].values] == [("Rare", 2)]
        sql, parameters = calls[0]
        instructions = database.execute("EXPLAIN " + sql, parameters).fetchall()
        assert not {"SorterOpen", "OpenEphemeral"} & {row[1] for row in instructions}


@pytest.mark.parametrize("expansion", [None, "SET", "OTHER", "MISSING"])
@pytest.mark.parametrize("rarity", [None, "Rare", "Common", "MISSING"])
@pytest.mark.parametrize("stock", [None, True, False])
def test_complete_sql_counts_equal_independent_oracle(
    metadata_projection, expansion, rarity, stock
):
    chosen = selected(expansion=expansion, rarity=rarity, stock=stock, query=None, size=1)
    all_items = _paginator(metadata_projection).fetch_page(selected(query=None)).page.items
    expected = evaluate_facets(all_items, chosen)
    assert metadata_projection.metadata_facets(chosen) == tuple(
        expected.facet(dimension)
        for dimension in (FacetDimension.EXPANSION_CODE, FacetDimension.RARITY)
    )


def test_vocabulary_not_truncated_to_page_or_top_100(tmp_path):
    records = tuple(metadata_card(i, expansion=f"SET-{i:04}") for i in range(1, 131))
    projection = _projection(tmp_path, records)
    chosen = selected(query=None, size=1)
    sets, rarities = projection.metadata_facets(chosen)
    assert len(sets.values) == 130
    assert sets.values[-1].value == "SET-0130"
    assert sets.values[-1].count == 1
    assert sum(item.count for item in rarities.values) == 130
    assert projection.metadata_facets(selected(query="absent"))[0].values == ()


def test_metadata_facet_checkpoint_failure_is_preserved(metadata_projection):
    stopped = RuntimeError("stop")

    def checkpoint():
        raise stopped

    with pytest.raises(RuntimeError) as caught:
        metadata_projection.metadata_facets(selected(), checkpoint=checkpoint)
    assert caught.value is stopped
    with pytest.raises(UnsupportedPaginationRequestError):
        metadata_projection.metadata_facets(replace(selected(), product_family=RequestFamily.ALL))
    with pytest.raises(PaginationContractError):
        metadata_projection.metadata_facets(selected(), checkpoint=42)


def test_metadata_facet_sql_progress_preserves_cancellation(metadata_projection, monkeypatch):
    monkeypatch.setattr(pagination, "_SQLITE_PROGRESS_VM_STEPS", 1)
    count = 0
    stopped = RuntimeError("interrupted")

    def checkpoint():
        nonlocal count
        count += 1
        if count > 1:
            raise stopped

    with pytest.raises(RuntimeError) as caught:
        metadata_projection.metadata_facets(selected(), checkpoint=checkpoint)
    assert caught.value is stopped


def test_metadata_facet_sql_failure_never_becomes_empty_counts(metadata_projection, monkeypatch):
    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("unavailable")

    monkeypatch.setattr(pagination, "select_metadata_facets", fail)
    with pytest.raises(DatasetUnavailableError):
        metadata_projection.metadata_facets(selected())


def test_metadata_facet_deadline_checked_after_query(metadata_projection, monkeypatch):
    monkeypatch.setattr(pagination, "select_metadata_facets", lambda *args, **kwargs: ())
    count = 0
    stopped = RuntimeError("deadline")

    def checkpoint():
        nonlocal count
        count += 1
        if count == 2:
            raise stopped

    with pytest.raises(RuntimeError) as caught:
        metadata_projection.metadata_facets(selected(), checkpoint=checkpoint)
    assert caught.value is stopped


def test_metadata_url_roundtrip_and_game_family_reset():
    chosen = selected(expansion="Code %' /", rarity="Rare é", stock=False)
    encoded = serialize_url_state(chosen)
    assert parse_url_state(encoded) == chosen
    assert "expansionCode=Code%20%25%27%20%2F" in encoded
    assert switch_game(chosen, Game.MAGIC) == chosen
    assert switch_family(chosen, RequestFamily.SINGLE) == chosen
    for changed in (
        switch_game(chosen, Game.POKEMON),
        switch_family(chosen, RequestFamily.SEALED),
    ):
        assert changed.filters.expansion_code is None
        assert changed.filters.rarity is None
        assert changed.filters.in_stock is False
