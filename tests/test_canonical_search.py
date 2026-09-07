from __future__ import annotations

import json
import traceback
from dataclasses import replace
from pathlib import Path
from time import perf_counter
from typing import Any

import pytest

# The private helper is exercised only to freeze the trust-boundary copy invariant.
from nla_catalog_gateway.canonical_search import (
    MAX_CANONICAL_NAME_CODEPOINTS,
    MAX_ORACLE_RECORDS,
    MAX_QUERY_CODEPOINTS,
    CanonicalSearchError,
    MatchTier,
    SearchMode,
    SingleCardSearchIndex,
    SingleCardSuggestion,
    _validated_records,
    normalize_search_text,
    prepare_single_card_search,
    report_missing_canonical_names,
    search_single_cards,
)
from nla_catalog_gateway.runtime_contract import (
    CatalogProductRecordV1,
    CatalogVariantRecordV1,
    InventoryPolicy,
    ProductStatus,
    SelectedOptionV1,
)
from nla_catalog_gateway.taxonomy import Game, ProductFamily

FIXTURE_PATH = Path(__file__).with_name("fixtures") / "canonical_search_v1.json"


class StringSubclass(str):
    pass


class TupleSubclass(tuple):
    pass


class HostileNestedTuple(tuple):
    def __iter__(self) -> Any:
        raise ValueError("hostile nested iterable detail")


class DeliberateBaseException(BaseException):
    pass


class RequestCancelled(RuntimeError):
    """Test double for the runtime cancellation exception owned by the caller."""


def _fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _record(raw: dict[str, Any]) -> CatalogProductRecordV1:
    product_id = raw["productId"]
    product_gid = f"gid://shopify/Product/{product_id}"
    family = ProductFamily(raw["productFamily"])
    subtype = "booster-box" if family is ProductFamily.SEALED else None
    return CatalogProductRecordV1(
        product_gid=product_gid,
        handle=f"synthetic-{product_id}",
        commercial_title=raw["commercialTitle"],
        canonical_card_name=raw["canonicalCardName"],
        shopify_status=ProductStatus(raw["status"]),
        online_store_published=raw["published"],
        powertools_source_id=None,
        sync_source_id=None,
        total_inventory=raw["inventory"],
        tracks_inventory=True,
        updated_at="2026-09-02T00:00:00Z",
        game=Game(raw["game"]),
        product_family=family,
        product_subtype=subtype,
        classification_rule_version="synthetic-search-v1",
        classification_rule_id=f"synthetic:{family.value}",
        unclassified_reason=None,
        subtype_rule_id="synthetic:booster-box" if subtype else None,
        subtype_reason=None,
        variants=(
            CatalogVariantRecordV1(
                variant_gid=f"gid://shopify/ProductVariant/{product_id}",
                product_gid=product_gid,
                inventory_item_gid=f"gid://shopify/InventoryItem/{product_id}",
                title="Synthetic variant",
                sku=None,
                barcode=None,
                selected_options=(),
                price_text="1.00",
                compare_at_price_text=None,
                inventory_quantity=raw["inventory"],
                inventory_policy=InventoryPolicy.DENY,
                inventory_tracked=True,
                updated_at="2026-09-02T00:00:00Z",
            ),
        ),
    )


@pytest.fixture
def records() -> tuple[CatalogProductRecordV1, ...]:
    document = _fixture()
    assert document["schemaVersion"] == 1
    assert document["evidenceKind"] == "synthetic-only"
    assert document["liveCountClaims"] is False
    return tuple(_record(item) for item in document["products"])


def _ids(result: Any) -> tuple[str, ...]:
    return tuple(hit.product_gid.rsplit("/", 1)[1] for hit in result.hits)


def test_exact_match_returns_every_print_and_suppresses_broader_tiers(
    records: tuple[CatalogProductRecordV1, ...],
) -> None:
    result = search_single_cards(records, game=Game.MAGIC, query="  lightning\tBOLT  ")

    assert result.mode is SearchMode.SEARCH
    assert result.game is Game.MAGIC
    assert result.normalized_query == "lightning bolt"
    assert result.match_tier is MatchTier.EXACT
    assert _ids(result) == ("2", "10", "999999999999999999999999999999999999")
    assert {hit.match_tier for hit in result.hits} == {MatchTier.EXACT}
    assert tuple(hit.available for hit in result.hits) == (False, True, False)
    assert result.suggestions == (
        SingleCardSuggestion(
            canonical_card_name="Lightning Bolt",
            normalized_card_name="lightning bolt",
            print_count=3,
            available_print_count=1,
        ),
    )
    assert result.suggestions[0].available is True


def test_prefix_suppresses_contains_and_contains_is_used_only_when_needed(
    records: tuple[CatalogProductRecordV1, ...],
) -> None:
    prefix = search_single_cards(records, game=Game.MAGIC, query="colossus")
    contains = search_single_cards(records, game=Game.MAGIC, query="steel col")

    assert prefix.match_tier is MatchTier.PREFIX
    assert _ids(prefix) == ("26",)
    assert contains.match_tier is MatchTier.CONTAINS
    assert _ids(contains) == ("27",)


@pytest.mark.parametrize(
    ("game", "expected_id"),
    [
        (Game.MAGIC, "101"),
        (Game.POKEMON, "102"),
        (Game.YUGIOH, "103"),
        (Game.ONE_PIECE, "104"),
    ],
)
def test_mandatory_game_boundary_prevents_cross_game_leakage(
    records: tuple[CatalogProductRecordV1, ...], game: Game, expected_id: str
) -> None:
    result = search_single_cards(records, game=game, query="shared hero")
    assert _ids(result) == (expected_id,)
    assert all(hit.product_gid.endswith(f"/{expected_id}") for hit in result.hits)


def test_expected_four_game_card_names_are_isolated_without_live_count_claims(
    records: tuple[CatalogProductRecordV1, ...],
) -> None:
    cases = (
        (Game.MAGIC, "Lightning Bolt", ("2", "10", "999999999999999999999999999999999999")),
        (Game.POKEMON, "Pikachu", ("30",)),
        (Game.YUGIOH, "Blue-Eyes White Dragon", ("31",)),
        (Game.ONE_PIECE, "Monkey.D.Luffy", ("32",)),
    )
    for game, query, expected in cases:
        assert _ids(search_single_cards(records, game=game, query=query)) == expected


def test_only_canonical_name_is_a_match_source_and_only_singles_are_searchable(
    records: tuple[CatalogProductRecordV1, ...],
) -> None:
    result = search_single_cards(records, game=Game.MAGIC, query="fallback trap")
    assert result.match_tier is None
    assert result.hits == ()
    assert result.suggestions == ()

    lightning = search_single_cards(records, game=Game.MAGIC, query="lightning bolt")
    assert "13" not in _ids(lightning)
    assert "14" not in _ids(lightning)
    assert "15" not in _ids(lightning)
    assert search_single_cards(records, game=Game.POKEMON, query="pikchus").hits == ()
    assert search_single_cards(records, game=Game.POKEMON, query="pika chu").hits == ()


@pytest.mark.parametrize(
    ("query", "expected_id"),
    [("%", "20"), ("_", "22")],
)
def test_percent_and_underscore_are_literal_characters(
    records: tuple[CatalogProductRecordV1, ...], query: str, expected_id: str
) -> None:
    result = search_single_cards(records, game=Game.MAGIC, query=query)
    assert result.match_tier is MatchTier.CONTAINS
    assert _ids(result) == (expected_id,)


@pytest.mark.parametrize("punctuation", ["%", "_", "'", '"', "/", ",", "-", "."])
def test_normalization_preserves_punctuation_literally(punctuation: str) -> None:
    assert normalize_search_text(f" A{punctuation}B ") == f"a{punctuation}b"


def test_nfkc_casefold_whitespace_and_punctuation_semantics_are_exact(
    records: tuple[CatalogProductRecordV1, ...],
) -> None:
    assert normalize_search_text(" \uff30\uff49\uff4b\uff41\uff43\uff48\uff55\n") == "pikachu"
    assert normalize_search_text("Stra\u00dfe") == "strasse"
    assert normalize_search_text(" Cafe\u0301\tMage ") == "caf\u00e9 mage"

    unicode_result = search_single_cards(records, game=Game.MAGIC, query="CAF\u00c9 MAGE")
    assert unicode_result.match_tier is MatchTier.EXACT
    assert _ids(unicode_result) == ("24", "25")
    assert unicode_result.suggestions[0].print_count == 2
    assert unicode_result.suggestions[0].available_print_count == 1

    punctuation = search_single_cards(records, game=Game.ONE_PIECE, query="monkey d luffy")
    assert punctuation.hits == ()
    assert (
        search_single_cards(records, game=Game.ONE_PIECE, query="monkey.d.luffy").match_tier
        is MatchTier.EXACT
    )


def test_empty_normalized_query_routes_to_browse_without_running_search(
    records: tuple[CatalogProductRecordV1, ...],
) -> None:
    result = search_single_cards(records, game=Game.MAGIC, query=" \t\n ")
    assert result.mode is SearchMode.BROWSE
    assert result.normalized_query == ""
    assert result.match_tier is None
    assert result.hits == ()
    assert result.suggestions == ()


def test_prepared_index_matches_the_frozen_oracle_and_serializes_only_at_activation(
    records: tuple[CatalogProductRecordV1, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cases = (
        (Game.MAGIC, "lightning bolt"),
        (Game.MAGIC, "colossus"),
        (Game.MAGIC, "steel col"),
        (Game.MAGIC, "fallback trap"),
        (Game.MAGIC, "%"),
        (Game.POKEMON, "shared hero"),
        (Game.YUGIOH, "shared hero"),
        (Game.ONE_PIECE, "monkey.d.luffy"),
        (Game.MAGIC, " \t\n "),
    )
    expected = tuple(search_single_cards(records, game=game, query=query) for game, query in cases)

    serialization_calls = 0
    original_to_json_bytes = CatalogProductRecordV1.to_json_bytes

    def counted_to_json_bytes(record: CatalogProductRecordV1) -> bytes:
        nonlocal serialization_calls
        serialization_calls += 1
        return original_to_json_bytes(record)

    monkeypatch.setattr(CatalogProductRecordV1, "to_json_bytes", counted_to_json_bytes)
    prepared = prepare_single_card_search(records)

    assert type(prepared) is SingleCardSearchIndex
    assert serialization_calls == len(records)
    actual = tuple(search_single_cards(prepared, game=game, query=query) for game, query in cases)
    assert actual == expected
    assert prepared.search(game=Game.MAGIC, query="lightning bolt") == expected[0]
    assert serialization_calls == len(records)


def test_prepared_index_construction_and_requests_remain_fail_closed_and_cancellable(
    records: tuple[CatalogProductRecordV1, ...],
) -> None:
    with pytest.raises(CanonicalSearchError, match="created from runtime v1 records"):
        SingleCardSearchIndex()  # type: ignore[call-arg]

    unbound = object.__new__(SingleCardSearchIndex)
    with pytest.raises(CanonicalSearchError, match="prepared search index is invalid"):
        search_single_cards(unbound, game=Game.MAGIC, query="bolt")

    build_cancelled = RequestCancelled("build cancelled")
    build_calls = 0

    def build_checkpoint() -> object:
        nonlocal build_calls
        build_calls += 1
        if build_calls == 3:
            raise build_cancelled
        return object()

    with pytest.raises(RequestCancelled) as build_error:
        prepare_single_card_search(
            records,
            checkpoint=build_checkpoint,  # type: ignore[arg-type]
        )
    assert build_error.value is build_cancelled
    assert build_calls == 3

    successful_checkpoint_calls = 0

    def successful_checkpoint() -> object:
        nonlocal successful_checkpoint_calls
        successful_checkpoint_calls += 1
        return object()

    prepared = prepare_single_card_search(
        records,
        checkpoint=successful_checkpoint,  # type: ignore[arg-type]
    )
    assert successful_checkpoint_calls > len(records)

    wrong_entry_type = object.__new__(SingleCardSearchIndex)
    object.__setattr__(wrong_entry_type, "_games", (object(),) * len(Game))
    object.__setattr__(wrong_entry_type, "_seal", prepared._seal)
    with pytest.raises(CanonicalSearchError, match="prepared search index is invalid"):
        wrong_entry_type.search(game=Game.MAGIC, query="bolt")
    with pytest.raises(CanonicalSearchError, match="prepared search index is invalid"):
        wrong_entry_type.search(game=Game.MAGIC, query=" \t\n ")

    wrong_game_order = object.__new__(SingleCardSearchIndex)
    object.__setattr__(wrong_game_order, "_games", tuple(reversed(prepared._games)))
    object.__setattr__(wrong_game_order, "_seal", prepared._seal)
    with pytest.raises(CanonicalSearchError, match="prepared search index is invalid"):
        wrong_game_order.search(game=Game.MAGIC, query="bolt")
    with pytest.raises(CanonicalSearchError, match="prepared search index is invalid"):
        wrong_game_order.search(game=Game.MAGIC, query=" \t\n ")

    with pytest.raises(CanonicalSearchError, match="canonical Game"):
        prepared.search(game="magic", query="bolt")  # type: ignore[arg-type]
    with pytest.raises(CanonicalSearchError, match="query exceeds"):
        prepared.search(game=Game.MAGIC, query="x" * (MAX_QUERY_CODEPOINTS + 1))

    request_cancelled = RequestCancelled("request cancelled")
    request_calls = 0

    def request_checkpoint() -> object:
        nonlocal request_calls
        request_calls += 1
        if request_calls == 7:
            raise request_cancelled
        return object()

    with pytest.raises(RequestCancelled) as request_error:
        prepared.search(
            game=Game.MAGIC,
            query="not present",
            checkpoint=request_checkpoint,  # type: ignore[arg-type]
        )
    assert request_error.value is request_cancelled
    assert request_calls == 7


def test_prepared_contains_search_over_30000_records_finishes_within_two_seconds(
    records: tuple[CatalogProductRecordV1, ...],
) -> None:
    template = next(record for record in records if record.product_gid.endswith("/10"))
    template_variant = template.variants[0]
    record_count = 30_001
    large_records: list[CatalogProductRecordV1] = []
    for offset in range(record_count):
        product_id = 1_000_000 + offset
        product_gid = f"gid://shopify/Product/{product_id}"
        canonical_name = (
            "Rare Target Fragment Card"
            if offset == record_count - 1
            else f"Synthetic Indexed Card {offset:05d}"
        )
        large_records.append(
            replace(
                template,
                product_gid=product_gid,
                handle=f"synthetic-indexed-{product_id}",
                canonical_card_name=canonical_name,
                variants=(
                    replace(
                        template_variant,
                        product_gid=product_gid,
                        variant_gid=f"gid://shopify/ProductVariant/{product_id}",
                        inventory_item_gid=f"gid://shopify/InventoryItem/{product_id}",
                    ),
                ),
            )
        )

    prepared = prepare_single_card_search(tuple(large_records))
    started = perf_counter()
    result = prepared.search(game=Game.MAGIC, query="target fragment")
    elapsed = perf_counter() - started

    assert len(large_records) > 30_000
    assert result.match_tier is MatchTier.CONTAINS
    assert tuple(hit.product_gid for hit in result.hits) == ("gid://shopify/Product/1030000",)
    assert elapsed < 2.0


def test_checkpoint_return_value_is_ignored_without_changing_results(
    records: tuple[CatalogProductRecordV1, ...],
) -> None:
    calls = 0

    def checkpoint() -> object:
        nonlocal calls
        calls += 1
        return object()

    search = search_single_cards(
        records,
        game=Game.MAGIC,
        query="lightning bolt",
        checkpoint=checkpoint,  # type: ignore[arg-type]
    )
    report = report_missing_canonical_names(
        records,
        game=Game.MAGIC,
        checkpoint=checkpoint,  # type: ignore[arg-type]
    )

    assert search == search_single_cards(records, game=Game.MAGIC, query="lightning bolt")
    assert report == report_missing_canonical_names(records, game=Game.MAGIC)
    assert calls > len(records) * 2


@pytest.mark.parametrize("entry_point", ["search", "report"])
def test_checkpoint_cancellation_precedes_validation_and_propagates_unchanged(
    entry_point: str,
) -> None:
    cancelled = RequestCancelled("request cancelled")

    def checkpoint() -> None:
        raise cancelled

    with pytest.raises(RequestCancelled) as error:
        if entry_point == "search":
            search_single_cards(
                [],  # type: ignore[arg-type]
                game="magic",  # type: ignore[arg-type]
                query=1,  # type: ignore[arg-type]
                checkpoint=checkpoint,
            )
        else:
            report_missing_canonical_names(
                [],  # type: ignore[arg-type]
                game="magic",  # type: ignore[arg-type]
                checkpoint=checkpoint,
            )

    assert error.value is cancelled
    assert error.value.__cause__ is None
    assert error.value.__context__ is None


@pytest.mark.parametrize("entry_point", ["search", "report"])
def test_checkpoint_can_cancel_inside_the_post_validation_record_loop(
    records: tuple[CatalogProductRecordV1, ...],
    entry_point: str,
) -> None:
    calls = 0
    cancellation_call = len(records) + 3
    cancelled = RequestCancelled("request cancelled")

    def checkpoint() -> None:
        nonlocal calls
        calls += 1
        if calls == cancellation_call:
            raise cancelled

    with pytest.raises(RequestCancelled) as error:
        if entry_point == "search":
            search_single_cards(
                records,
                game=Game.MAGIC,
                query="lightning bolt",
                checkpoint=checkpoint,
            )
        else:
            report_missing_canonical_names(
                records,
                game=Game.MAGIC,
                checkpoint=checkpoint,
            )

    assert calls == cancellation_call
    assert error.value is cancelled


def test_missing_name_report_is_game_scoped_complete_and_gid_ordered(
    records: tuple[CatalogProductRecordV1, ...],
) -> None:
    second_missing = replace(
        next(record for record in records if record.product_gid.endswith("/15")),
        product_gid="gid://shopify/Product/5",
        handle="synthetic-5-missing",
        variants=(
            replace(
                next(record for record in records if record.product_gid.endswith("/15")).variants[
                    0
                ],
                product_gid="gid://shopify/Product/5",
                variant_gid="gid://shopify/ProductVariant/5",
                inventory_item_gid="gid://shopify/InventoryItem/5",
            ),
        ),
    )
    expanded_records = (*records, second_missing)
    report = report_missing_canonical_names(expanded_records, game=Game.MAGIC)

    assert report.game is Game.MAGIC
    assert report.single_record_count == sum(
        record.game is Game.MAGIC and record.product_family is ProductFamily.SINGLE
        for record in expanded_records
    )
    assert tuple(item.product_gid.rsplit("/", 1)[1] for item in report.missing) == ("5", "15")
    assert all(item.game is Game.MAGIC for item in report.missing)
    assert all(item.publishable is False for item in report.missing)
    assert report.missing_count == 2
    assert report_missing_canonical_names(records, game=Game.POKEMON).missing_count == 0


def test_results_and_group_display_are_repeatable_independent_of_input_order(
    records: tuple[CatalogProductRecordV1, ...],
) -> None:
    forward = search_single_cards(records, game=Game.MAGIC, query="lightning bolt")
    reverse = search_single_cards(tuple(reversed(records)), game=Game.MAGIC, query="lightning bolt")
    assert reverse == forward
    assert forward.suggestions[0].canonical_card_name == "Lightning Bolt"


def test_normalization_and_result_invariants_hold_for_bounded_property_matrix(
    records: tuple[CatalogProductRecordV1, ...],
) -> None:
    samples = (
        "Lightning Bolt",
        "  LIGHTNING\tBOLT ",
        "Cafe\u0301 Mage",
        "Monkey.D.Luffy",
        "100% Energy",
        "Code_Name",
        "Blue-Eyes White Dragon",
    )
    for sample in samples:
        normalized = normalize_search_text(sample)
        assert normalize_search_text(normalized) == normalized

    for query in ("lightning bolt", "colossus", "energy", "%", "_", "not present"):
        result = search_single_cards(records, game=Game.MAGIC, query=query)
        gids = tuple(hit.product_gid for hit in result.hits)
        assert len(gids) == len(set(gids))
        assert all(hit.match_tier is result.match_tier for hit in result.hits)
        assert tuple(
            (hit.normalized_card_name, len(gid.rsplit("/", 1)[1]), gid.rsplit("/", 1)[1])
            for hit, gid in zip(result.hits, gids, strict=True)
        ) == tuple(
            sorted(
                (
                    hit.normalized_card_name,
                    len(gid.rsplit("/", 1)[1]),
                    gid.rsplit("/", 1)[1],
                )
                for hit, gid in zip(result.hits, gids, strict=True)
            )
        )

    energy = search_single_cards(records, game=Game.MAGIC, query="energy")
    assert _ids(energy) == ("20", "21")
    assert tuple(item.normalized_card_name for item in energy.suggestions) == (
        "100% energy",
        "100x energy",
    )


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (1, "plain string"),
        ("\ud800", "valid Unicode"),
    ],
)
def test_normalization_rejects_non_plain_or_invalid_unicode(value: Any, message: str) -> None:
    with pytest.raises(CanonicalSearchError, match=message) as error:
        normalize_search_text(value)  # type: ignore[arg-type]
    assert error.value.__cause__ is None
    assert error.value.__context__ is None


def test_plain_string_and_tuple_subclasses_are_rejected(
    records: tuple[CatalogProductRecordV1, ...],
) -> None:
    with pytest.raises(CanonicalSearchError, match="plain string"):
        normalize_search_text(StringSubclass("bolt"))
    with pytest.raises(CanonicalSearchError, match="query must be a plain string"):
        search_single_cards(records, game=Game.MAGIC, query=StringSubclass("bolt"))
    with pytest.raises(CanonicalSearchError, match="records must be a tuple"):
        search_single_cards(TupleSubclass(records), game=Game.MAGIC, query="bolt")


def test_oracle_boundaries_are_fail_closed(
    records: tuple[CatalogProductRecordV1, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    assert MAX_ORACLE_RECORDS == 1_000_000
    with pytest.raises(CanonicalSearchError, match="records must be a tuple"):
        search_single_cards(list(records), game=Game.MAGIC, query="bolt")  # type: ignore[arg-type]
    monkeypatch.setattr("nla_catalog_gateway.canonical_search.MAX_ORACLE_RECORDS", 1)
    with pytest.raises(CanonicalSearchError, match="record limit"):
        search_single_cards(records, game=Game.MAGIC, query="bolt")
    monkeypatch.setattr(
        "nla_catalog_gateway.canonical_search.MAX_ORACLE_RECORDS", MAX_ORACLE_RECORDS
    )

    with pytest.raises(CanonicalSearchError, match="canonical Game"):
        search_single_cards(records, game="magic", query="bolt")  # type: ignore[arg-type]
    with pytest.raises(CanonicalSearchError, match="query must be a plain string"):
        search_single_cards(records, game=Game.MAGIC, query=1)  # type: ignore[arg-type]
    with pytest.raises(CanonicalSearchError, match="query exceeds"):
        search_single_cards(records, game=Game.MAGIC, query="x" * (MAX_QUERY_CODEPOINTS + 1))
    with pytest.raises(CanonicalSearchError, match="normalized query exceeds"):
        search_single_cards(records, game=Game.MAGIC, query="\ufb03" * MAX_QUERY_CODEPOINTS)


def test_record_type_duplicates_and_revalidation_fail_closed(
    records: tuple[CatalogProductRecordV1, ...],
) -> None:
    with pytest.raises(CanonicalSearchError, match="runtime v1 Product records"):
        search_single_cards((*records, object()), game=Game.MAGIC, query="bolt")  # type: ignore[arg-type]
    with pytest.raises(CanonicalSearchError, match="duplicate Product GID"):
        search_single_cards((*records, records[0]), game=Game.MAGIC, query="bolt")

    forged = replace(records[0])
    object.__setattr__(forged, "game", "magic")
    with pytest.raises(CanonicalSearchError, match="violates the runtime v1 contract"):
        search_single_cards((forged,), game=Game.MAGIC, query="bolt")


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("product_gid", StringSubclass("gid://shopify/Product/2")),
        ("game", "magic"),
        ("product_family", "single"),
        ("shopify_status", "ACTIVE"),
        ("online_store_published", 1),
        ("canonical_card_name", StringSubclass("Lightning Bolt")),
        ("total_inventory", True),
    ],
)
def test_each_consumed_runtime_field_is_revalidated_and_errors_are_normalized(
    records: tuple[CatalogProductRecordV1, ...], field: str, invalid_value: Any
) -> None:
    forged = replace(records[0])
    object.__setattr__(forged, field, invalid_value)
    with pytest.raises(CanonicalSearchError, match="violates the runtime v1 contract") as error:
        search_single_cards((forged,), game=Game.MAGIC, query="bolt")
    assert error.value.__cause__ is None
    assert error.value.__context__ is None


def test_nested_variant_and_selected_option_forgery_fails_closed(
    records: tuple[CatalogProductRecordV1, ...],
) -> None:
    product = records[0]
    variant = product.variants[0]

    bad_inventory = replace(variant)
    object.__setattr__(bad_inventory, "inventory_quantity", True)

    bad_price = replace(variant)
    object.__setattr__(bad_price, "price_text", "not-a-price")

    bad_options = replace(variant)
    object.__setattr__(bad_options, "selected_options", (object(),))

    noniterable_options = replace(variant)
    object.__setattr__(noniterable_options, "selected_options", 1)

    option = SelectedOptionV1(name="Finish", value="Regular")
    bad_option = replace(option)
    object.__setattr__(bad_option, "name", 1)
    variant_with_bad_option = replace(variant)
    object.__setattr__(variant_with_bad_option, "selected_options", (bad_option,))

    forged_variants = (
        bad_inventory,
        bad_price,
        bad_options,
        noniterable_options,
        variant_with_bad_option,
    )
    for forged_variant in forged_variants:
        forged_product = replace(product, variants=(forged_variant,))
        with pytest.raises(
            CanonicalSearchError, match="violates the runtime v1 contract"
        ) as search_error:
            search_single_cards((forged_product,), game=Game.MAGIC, query="lightning bolt")
        assert search_error.value.__cause__ is None
        assert search_error.value.__context__ is None

    forged_product = replace(product, variants=(bad_inventory,))
    with pytest.raises(CanonicalSearchError, match="violates the runtime v1 contract"):
        report_missing_canonical_names((forged_product,), game=Game.MAGIC)


@pytest.mark.parametrize("entry_point", ["search", "report"])
@pytest.mark.parametrize("failure_kind", ["iterable", "as_dict"])
def test_hostile_nested_rendering_failures_are_normalized_at_both_entry_points(
    records: tuple[CatalogProductRecordV1, ...],
    monkeypatch: pytest.MonkeyPatch,
    entry_point: str,
    failure_kind: str,
) -> None:
    product = records[0]
    option = SelectedOptionV1(name="Finish", value="Regular")
    variant = replace(product.variants[0], selected_options=(option,))

    if failure_kind == "iterable":
        object.__setattr__(variant, "selected_options", HostileNestedTuple((option,)))
        hostile_detail = "hostile nested iterable detail"
    else:
        hostile_detail = "hostile nested as_dict detail"

        def hostile_as_dict(_option: SelectedOptionV1) -> dict[str, Any]:
            raise ValueError(hostile_detail)

        monkeypatch.setattr(SelectedOptionV1, "as_dict", hostile_as_dict)

    forged_product = replace(product, variants=(variant,))
    with pytest.raises(CanonicalSearchError) as error:
        if entry_point == "search":
            search_single_cards((forged_product,), game=Game.MAGIC, query="lightning bolt")
        else:
            report_missing_canonical_names((forged_product,), game=Game.MAGIC)

    assert str(error.value) == "search record violates the runtime v1 contract"
    assert error.value.__cause__ is None
    assert error.value.__context__ is None
    assert hostile_detail not in "".join(traceback.format_exception(error.value))


def test_validation_does_not_catch_base_exception(
    records: tuple[CatalogProductRecordV1, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    product = records[0]
    option = SelectedOptionV1(name="Finish", value="Regular")
    variant = replace(product.variants[0], selected_options=(option,))
    forged_product = replace(product, variants=(variant,))

    def interrupt_as_dict(_option: SelectedOptionV1) -> dict[str, Any]:
        raise DeliberateBaseException("deliberate interrupt")

    monkeypatch.setattr(SelectedOptionV1, "as_dict", interrupt_as_dict)
    with pytest.raises(DeliberateBaseException, match="deliberate interrupt"):
        search_single_cards((forged_product,), game=Game.MAGIC, query="lightning bolt")


def test_validation_returns_deep_canonical_copies_not_original_records(
    records: tuple[CatalogProductRecordV1, ...],
) -> None:
    product = records[0]
    variant = replace(
        product.variants[0],
        selected_options=(SelectedOptionV1(name="Finish", value="Regular"),),
    )
    product_with_option = replace(product, variants=(variant,))

    checked = _validated_records((product_with_option,))

    assert checked == (product_with_option,)
    assert checked[0] is not product_with_option
    assert checked[0].variants is not product_with_option.variants
    assert checked[0].variants[0] is not product_with_option.variants[0]
    assert (
        checked[0].variants[0].selected_options[0]
        is not product_with_option.variants[0].selected_options[0]
    )


def test_publishable_missing_name_guard_remains_fail_closed(
    records: tuple[CatalogProductRecordV1, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    forged = replace(records[0])
    object.__setattr__(forged, "canonical_card_name", None)
    monkeypatch.setattr(CatalogProductRecordV1, "__post_init__", lambda self: None)
    with pytest.raises(CanonicalSearchError, match="missing its canonical card name"):
        search_single_cards((forged,), game=Game.MAGIC, query="bolt")


def test_canonical_name_bound_is_fail_closed(
    records: tuple[CatalogProductRecordV1, ...],
) -> None:
    long_name = replace(
        records[0],
        canonical_card_name="x" * (MAX_CANONICAL_NAME_CODEPOINTS + 1),
    )
    with pytest.raises(CanonicalSearchError, match="canonical card name exceeds"):
        search_single_cards((long_name,), game=Game.MAGIC, query="x")


def test_no_match_and_unavailable_suggestion_paths_are_explicit(
    records: tuple[CatalogProductRecordV1, ...],
) -> None:
    no_match = search_single_cards(records, game=Game.MAGIC, query="not present")
    assert no_match.mode is SearchMode.SEARCH
    assert no_match.match_tier is None
    assert no_match.hits == ()

    unavailable = search_single_cards(records, game=Game.MAGIC, query="100% energy")
    unavailable_record = replace(
        next(record for record in records if record.product_gid.endswith("/20")),
        total_inventory=0,
        variants=(
            replace(
                next(record for record in records if record.product_gid.endswith("/20")).variants[
                    0
                ],
                inventory_quantity=0,
            ),
        ),
    )
    unavailable = search_single_cards((unavailable_record,), game=Game.MAGIC, query="100% energy")
    assert unavailable.suggestions[0].available_print_count == 0
    assert unavailable.suggestions[0].available is False
