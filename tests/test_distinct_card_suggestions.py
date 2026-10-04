"""Print labels must not crowd distinct card names out of suggestions."""

from dataclasses import replace

import pytest

from nla_catalog_gateway import search_sql
from nla_catalog_gateway.core_evidence import (
    CatalogCoreEvidenceError,
    _expected_suggestion_label,
    verify_catalog_core_evidence,
)
from nla_catalog_gateway.pagination import UnsupportedPaginationRequestError
from nla_catalog_gateway.runtime_contract import ProductStatus, RequestFamily
from nla_catalog_gateway.search_sql import _suggestion_name, select_suggestions
from nla_catalog_gateway.taxonomy import Game, ProductFamily
from test_core_evidence import CODE_SHA, _records, _verified
from test_pagination import _paginator, _projection, _record, _request
from test_search_sql import card


def one_piece_card(number, name, stock=0, code=None):
    return replace(card(number, name, stock=stock, code=code), game=Game.ONE_PIECE)


def chosen(query="Ma", *, stock=None, size=100):
    return _request(
        family=RequestFamily.SINGLE,
        game=Game.ONE_PIECE,
        query=query,
        in_stock=stock,
        page_size=size,
    )


@pytest.fixture
def crowded(tmp_path):
    prints = tuple(
        one_piece_card(
            i, f"Magellan (OP02-085) (V.{i} - Rare)", stock=int(i % 3 == 0), code="OP02-085"
        )
        for i in range(1, 32)
    )
    other_names = tuple(
        one_piece_card(40 + index, f"{name} (ST01-001) (V.1)", stock=1)
        for index, name in enumerate(("Machvise", "Manta", "Marco", "Marshall", "Maynard"))
    )
    excluded = (
        replace(one_piece_card(60, "Magellan (OP02-085) (V.99)"), game=Game.MAGIC),
        replace(one_piece_card(61, "Magellan (OP02-085) (V.98)"), online_store_published=False),
        replace(
            one_piece_card(62, "Magellan (OP02-085) (V.97)"), shopify_status=ProductStatus.DRAFT
        ),
        _record("63", game=Game.ONE_PIECE, family=ProductFamily.SEALED),
    )
    return _projection(tmp_path, prints + other_names + excluded)


def test_limit_applies_after_all_prints_are_merged(crowded):
    suggestions = crowded.suggest(chosen(), limit=5)
    assert [value.normalized_card_name for value in suggestions] == [
        "machvise",
        "magellan",
        "manta",
        "marco",
        "marshall",
    ]
    assert len({value.normalized_card_name for value in suggestions}) == 5
    magellan = suggestions[1]
    assert magellan.print_count == 31
    assert magellan.available_print_count == 10
    assert len(crowded.suggest(chosen(), limit=10)) == 6


def test_merged_counts_keep_stock_game_visibility_and_family_scope(crowded):
    stocked = crowded.suggest(chosen("Magellan", stock=True))
    sold = crowded.suggest(chosen("Magellan", stock=False))
    assert [(value.print_count, value.available_print_count) for value in stocked] == [(10, 10)]
    assert [(value.print_count, value.available_print_count) for value in sold] == [(21, 0)]
    assert crowded.suggest(replace(chosen(), game=Game.POKEMON)) == ()
    magic = crowded.suggest(replace(chosen("Magellan"), game=Game.MAGIC))
    assert [(value.canonical_card_name, value.print_count) for value in magic] == [
        ("Magellan (OP02-085)", 1)
    ]
    with pytest.raises(UnsupportedPaginationRequestError):
        crowded.suggest(replace(chosen(None), product_family=RequestFamily.SEALED))


def test_code_search_groups_names_but_selecting_name_keeps_all_product_ids(crowded):
    coded = crowded.suggest(chosen("OP02-085"))
    assert [(value.canonical_card_name, value.print_count) for value in coded] == [("Magellan", 31)]
    request = chosen(coded[0].canonical_card_name, size=7)
    paginator = _paginator(crowded)
    cursor = None
    ids = []
    while True:
        result = paginator.fetch_page(request, cursor=cursor)
        ids.extend(item.product_gid for item in result.page.items)
        assert all("(OP02-085) (V." in item.canonical_card_name for item in result.page.items)
        cursor = result.next_cursor
        if cursor is None:
            break
    assert ids == [f"gid://shopify/Product/{i}" for i in range(1, 32)]
    assert len(set(ids)) == 31


@pytest.mark.parametrize("code", ["OP02-085", "ST01-001", "EB01-001", "PRB01-001", "P-001"])
def test_only_known_one_piece_number_suffixes_are_grouped(code):
    assert _suggestion_name(f"Name ({code}) (V.2 - Rare)", "one-piece") == "Name"
    assert _suggestion_name(f"Name ({code})", "one-piece") == "Name"
    assert _expected_suggestion_label(f"Name ({code}) (V.2 - Rare)", Game.ONE_PIECE) == "Name"


@pytest.mark.parametrize(
    "name,game,expected",
    [
        ("Name (Young)", "one-piece", "Name (Young)"),
        ("Name (OP2-085)", "one-piece", "Name (OP2-085)"),
        ("Name (ABC01-001)", "one-piece", "Name (ABC01-001)"),
        ("Name (OP02-085) Extra", "one-piece", "Name (OP02-085) Extra"),
        ("Name (op02-085)", "one-piece", "Name (op02-085)"),
        ("Name (V.x)", "one-piece", "Name (V.x)"),
        ("Name (V.)", "one-piece", "Name (V.)"),
        ("Name (V.\uff11)", "one-piece", "Name (V.\uff11)"),
        ("Name (V.1 - )", "one-piece", "Name (V.1 - )"),
        ("Name (V.1 - (Rare))", "one-piece", "Name (V.1 - (Rare))"),
        ("Name (OP\uff10\uff11-001)", "one-piece", "Name (OP\uff10\uff11-001)"),
        ("Name (OP01-\uff1001)", "one-piece", "Name (OP01-\uff1001)"),
        ("Name (V.1)\n", "one-piece", "Name (V.1)\n"),
        ("Name (OP02-085)\n", "one-piece", "Name (OP02-085)\n"),
        ("Name (Young) (OP02-085) (V.2)", "one-piece", "Name (Young)"),
        ("Name (OP02-085) (V.2)", "magic", "Name (OP02-085)"),
        ("Name (OP02-085) (V.2)", "pokemon", "Name (OP02-085)"),
        ("Name (ABC01-001) (V.2)", "one-piece", "Name (ABC01-001)"),
        (" (V.1)", "one-piece", " (V.1)"),
        (" (P-001)", "one-piece", " (P-001)"),
    ],
)
def test_parenthetical_card_text_and_other_game_codes_are_not_lost(name, game, expected):
    assert _suggestion_name(name, game) == expected
    assert _expected_suggestion_label(name, Game(game)) == expected


def test_unicode_casefold_merges_labels_and_ranking_remains_exact_prefix_contains(tmp_path):
    records = (
        one_piece_card(1, "Éclair (OP01-001) (V.1)", stock=1),
        one_piece_card(2, "E\u0301CLAIR (ST01-001) (V.2)"),
        one_piece_card(3, "Éclair Mage (V.1)"),
        one_piece_card(4, "An Éclair (V.1)"),
        one_piece_card(5, "Éclair (Young) (V.1)"),
    )
    projection = _projection(tmp_path, records)
    values = projection.suggest(chosen("ÉCLAIR"))
    assert [value.normalized_card_name for value in values] == [
        "éclair",
        "éclair (young)",
        "éclair mage",
        "an éclair",
    ]
    assert values[0].print_count == 2
    assert values[0].available_print_count == 1


def test_casefold_equivalent_raw_version_markers_are_not_stripped_as_a_group(tmp_path):
    projection = _projection(
        tmp_path,
        (
            one_piece_card(1, "Name (V.1)"),
            one_piece_card(2, "name (v.1)"),
        ),
    )
    assert [
        (value.normalized_card_name, value.print_count)
        for value in projection.suggest(chosen("name"))
    ] == [("name", 1), ("name (v.1)", 1)]


@pytest.mark.parametrize("stop_at", [2, 4])
def test_cancellation_during_python_merge_and_after_sort_is_preserved(stop_at):
    class GroupedConnection:
        def execute(self, _sql, _parameters):
            return iter(
                (
                    ("Magellan (OP02-085) (V.1)", 1, 0),
                    ("Magellan (OP02-085) (V.2)", 1, 1),
                    ("Marco (OP02-001)", 1, 0),
                )
            )

    calls = 0
    stopped = RuntimeError("cancelled during aggregation")

    def checkpoint():
        nonlocal calls
        calls += 1
        if calls == stop_at:
            raise stopped

    with pytest.raises(RuntimeError) as caught:
        select_suggestions(GroupedConnection(), chosen(), limit=5, checkpoint=checkpoint)
    assert caught.value is stopped
    assert calls == stop_at


@pytest.mark.parametrize(
    "name,game,expected",
    [
        ("Pachirisu Lv.14", "pokemon", "Pachirisu"),
        ("İnternational Lv.14", "pokemon", "İnternational"),
        ("Pachirisu Lv.", "pokemon", "Pachirisu Lv."),
        ("Pachirisu Lv.\uff11\uff14", "pokemon", "Pachirisu Lv.\uff11\uff14"),
        ("Pachirisu LV.20 (V.2 - Rare)", "pokemon", "Pachirisu"),
        ("Pachirisu lv.100", "pokemon", "Pachirisu"),
        ("Pachirisu Lv.X", "pokemon", "Pachirisu Lv.X"),
        ("Pachirisu ex", "pokemon", "Pachirisu ex"),
        ("Pachirisu VMAX", "pokemon", "Pachirisu VMAX"),
        ("Pachirisu Lv.14 More", "pokemon", "Pachirisu Lv.14 More"),
        ("Pachirisu Lv.14\n", "pokemon", "Pachirisu Lv.14\n"),
        ("Pachirisu Lv.14", "magic", "Pachirisu Lv.14"),
        ("Pachirisu Lv.14", "one-piece", "Pachirisu Lv.14"),
        (" Lv.14", "pokemon", " Lv.14"),
    ],
)
def test_pokemon_numeric_level_suffix_is_not_other_card_identity(name, game, expected):
    assert _suggestion_name(name, game) == expected
    assert _expected_suggestion_label(name, Game(game)) == expected


def suffixed_records():
    records = []
    for record in _records():
        if record.product_family is ProductFamily.SINGLE and record.canonical_card_name:
            number = int(record.product_gid.rsplit("/", 1)[1])
            name = record.canonical_card_name
            if record.game is Game.ONE_PIECE:
                name += " (OP02-085)"
            if record.game is Game.POKEMON:
                name += f" Lv.{number}"
            record = replace(record, canonical_card_name=f"{name} (V.{number})")
        records.append(record)
    return tuple(records)


def test_real_core_evidence_accepts_distinct_suffixed_suggestions_for_four_games(tmp_path):
    verified = _verified(suffixed_records())
    evidence = verify_catalog_core_evidence(
        verified,
        projection_path=tmp_path / "suffix-proof.sqlite3",
        code_sha=CODE_SHA,
    )
    assert evidence.dataset_generation == verified.generation.dataset_manifest.dataset_generation


def test_real_core_evidence_rejects_old_raw_name_suggestion_grouping(tmp_path, monkeypatch):
    # Simulate the actual old behavior, without altering the independent proof oracle.
    monkeypatch.setattr(search_sql, "_suggestion_name", lambda name, _game: name)
    with pytest.raises(CatalogCoreEvidenceError):
        verify_catalog_core_evidence(
            _verified(suffixed_records()),
            projection_path=tmp_path / "wrong-proof.sqlite3",
            code_sha=CODE_SHA,
        )
