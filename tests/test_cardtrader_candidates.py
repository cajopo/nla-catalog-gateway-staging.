"""Synthetic identity cases; no real catalog payloads."""

import pytest

from nla_catalog_gateway.cardtrader_candidates import compare_catalog

CATEGORIES = {10: (1, "single"), 20: (1, "sealed"), 30: (1, "unclassified")}


def card(**changes):
    return {
        "id": 100,
        "game_id": 1,
        "category_id": 10,
        "expansion_id": 50,
        "card_market_ids": [900],
        **changes,
    }


def product(**changes):
    return {
        "productGid": "gid://shopify/Product/1000",
        "game": "magic",
        "productFamily": "single",
        "syncSourceId": "900",
        "powerToolsSourceId": "900",
        **changes,
    }


def test_existing_and_absent_are_read_only_and_do_not_use_title():
    rows = [card(name="Different name"), card(id=101, card_market_ids=[901])]
    result = compare_catalog(rows, [product(title="Unrelated")], CATEGORIES)
    assert [r["decision"] for r in result] == [
        "existing_identity_match",
        "absent_from_supplied_snapshot",
    ]
    assert all(r["creationApproved"] is False for r in result)
    assert [r["rowIndex"] for r in result] == [0, 1]
    assert rows[0]["name"] == "Different name"


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"id": True}, "invalid_blueprint_identity"),
        ({"game_id": []}, "invalid_blueprint_identity"),
        ({"expansion_id": None}, "invalid_blueprint_identity"),
        ({"game_id": 99}, "out_of_scope_game"),
        ({"category_id": 99}, "unclassified_category"),
        ({"category_id": 30}, "unclassified_category"),
        ({"game_id": 4}, "category_game_conflict"),
        ({"category_id": 20}, "non_card_category"),
        ({"card_market_ids": None}, "invalid_cardmarket_ids"),
        ({"card_market_ids": [True]}, "invalid_cardmarket_ids"),
        ({"card_market_ids": ["900"]}, "invalid_cardmarket_ids"),
        ({"card_market_ids": []}, "missing_cardmarket_id"),
        ({"card_market_ids": [900, 901]}, "multiple_cardmarket_ids"),
    ],
)
def test_every_row_gets_explicit_decision(changes, reason):
    assert compare_catalog([card(**changes)], [], CATEGORIES)[0]["decision"] == reason


def test_cross_expansion_collision_and_duplicate_blueprints():
    rows = [card(), card(id=101, expansion_id=51)]
    assert {r["decision"] for r in compare_catalog(rows, [], CATEGORIES)} == {
        "shared_cardmarket_id"
    }
    assert {r["decision"] for r in compare_catalog([card(), card()], [], CATEGORIES)} == {
        "duplicate_blueprint_id"
    }


def test_multi_id_row_blocks_other_candidate_sharing_an_id():
    rows = [card(), card(id=101, card_market_ids=[900, 901])]
    assert [r["decision"] for r in compare_catalog(rows, [], CATEGORIES)] == [
        "shared_cardmarket_id",
        "multiple_cardmarket_ids",
    ]


@pytest.mark.parametrize(
    "changes",
    [
        {"game": "pokemon"},
        {"productFamily": "sealed"},
        {"syncSourceId": "901"},
        {"powerToolsSourceId": None},
    ],
)
def test_existing_conflicts_never_become_missing_candidates(changes):
    assert compare_catalog([card()], [product(**changes)], CATEGORIES)[0]["decision"] == (
        "shopify_identity_conflict"
    )


def test_multiple_products_and_repeated_identical_product_rows():
    assert compare_catalog([card()], [product(), product()], CATEGORIES)[0]["decision"] == (
        "existing_identity_match"
    )
    result = compare_catalog(
        [card()], [product(), product(productGid="gid://shopify/Product/2")], CATEGORIES
    )
    assert result[0]["decision"] == "multiple_shopify_products"


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"productGid": None}, "invalid_product_identity"),
        ({"game": "unknown"}, "invalid_product_game"),
        ({"syncSourceId": 900}, "invalid_source_identity"),
    ],
)
def test_bad_existing_snapshot_fails_instead_of_allowing_creation(changes, reason):
    with pytest.raises(ValueError, match=reason):
        compare_catalog([card()], [product(**changes)], CATEGORIES)


def test_missing_identity_field_and_conflicting_duplicate_rows_fail():
    item = product()
    del item["syncSourceId"]
    with pytest.raises(ValueError, match="missing_identity_field"):
        compare_catalog([card()], [item], CATEGORIES)
    with pytest.raises(ValueError, match="conflicting_product_rows"):
        compare_catalog([card()], [product(), product(game="pokemon")], CATEGORIES)


@pytest.mark.parametrize(
    "mapping",
    [{True: (1, "single")}, {10: (True, "single")}, {10: (99, "single")}, {10: (1, "unknown")}],
)
def test_invalid_category_mapping(mapping):
    with pytest.raises(ValueError, match="invalid_category_mapping"):
        compare_catalog([card()], [], mapping)


def test_empty_source_and_unmapped_existing_product():
    assert compare_catalog([], [product(syncSourceId=None, powerToolsSourceId=None)], {}) == []


@pytest.mark.parametrize("source", ["901", None])
def test_conflicting_gid_with_disjoint_or_empty_ids_fails(source):
    with pytest.raises(ValueError, match="conflicting_product_rows"):
        compare_catalog(
            [card()],
            [product(), product(syncSourceId=source, powerToolsSourceId=source)],
            CATEGORIES,
        )
