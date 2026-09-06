from __future__ import annotations

from typing import Any

import pytest

import nla_catalog_gateway.facets as facets
from nla_catalog_gateway.facets import (
    ContextualFacet,
    FacetContractError,
    FacetDimension,
    FacetEvaluation,
    FacetValueCount,
    evaluate_facets,
    has_positive_inventory,
    inventory_fact_label,
    parse_url_state,
    price_fact_label,
    serialize_url_state,
    switch_family,
    switch_game,
)
from nla_catalog_gateway.runtime_contract import (
    CatalogFiltersV1,
    CatalogItemV1,
    CatalogRequestV1,
    CatalogVariantItemV1,
    CursorContextV1,
    InventoryPolicy,
    RequestFamily,
)
from nla_catalog_gateway.taxonomy import Game, ProductFamily

GENERATION = "sha256:" + "a" * 64


def _item(
    product_id: int,
    *,
    game: Game = Game.MAGIC,
    family: ProductFamily = ProductFamily.SINGLE,
    subtype: str | None = None,
    inventory: int = 1,
    tracked: bool = True,
    price: str = "10.00",
) -> CatalogItemV1:
    return CatalogItemV1(
        product_gid=f"gid://shopify/Product/{product_id}",
        handle=f"product-{product_id}",
        commercial_title=f"Product {product_id}",
        canonical_card_name=f"Card {product_id}" if family is ProductFamily.SINGLE else None,
        game=game,
        product_family=family,
        product_subtype=subtype,
        variants=(
            CatalogVariantItemV1(
                variant_gid=f"gid://shopify/ProductVariant/{product_id}0",
                title="Default Title",
                selected_options=(),
                price_text=price,
                compare_at_price_text=None,
                inventory_quantity=inventory,
                inventory_policy=InventoryPolicy.DENY,
                inventory_tracked=tracked,
            ),
        ),
    )


def _request(
    *,
    game: Game = Game.MAGIC,
    family: RequestFamily = RequestFamily.ALL,
    query: str | None = None,
    in_stock: bool | None = None,
    subtype: str | None = None,
    page_size: int = 24,
) -> CatalogRequestV1:
    return CatalogRequestV1(
        game=game,
        product_family=family,
        query=query,
        filters=CatalogFiltersV1(in_stock=in_stock, product_subtype=subtype),
        page_size=page_size,
    )


def _catalog() -> tuple[CatalogItemV1, ...]:
    return (
        _item(10, family=ProductFamily.ACCESSORY, inventory=3),
        _item(8, game=Game.POKEMON, family=ProductFamily.SEALED, subtype="booster-box"),
        _item(6, family=ProductFamily.SEALED, subtype=None, inventory=0),
        _item(5, family=ProductFamily.SEALED, subtype="bundle", inventory=0),
        _item(4, family=ProductFamily.SEALED, subtype="booster-box", inventory=5),
        _item(3, inventory=0, tracked=False, price="0.00"),
        _item(2, inventory=1),
    )


def _counts(facet: ContextualFacet) -> tuple[tuple[str, int], ...]:
    return tuple((value.value, value.count) for value in facet.values)


def test_url_state_is_literal_canonical_round_trip_and_cursor_bound() -> None:
    request = _request(
        family=RequestFamily.SEALED,
        query="Éclair + & /?",
        in_stock=False,
        subtype="booster-box",
        page_size=17,
    )
    encoded = serialize_url_state(request)
    assert encoded == (
        "game=magic&productFamily=sealed&q=%C3%89clair%20%2B%20%26%20%2F%3F"
        "&inStock=false&productSubtype=booster-box&sort=product_gid_asc&pageSize=17"
    )
    parsed = parse_url_state(encoded)
    assert parsed == request
    assert serialize_url_state(parsed) == encoded

    original_cursor = CursorContextV1.from_request(
        request,
        GENERATION,
        last_product_gid=None,
        expires_at="2026-09-02T12:00:00Z",
    )
    parsed_cursor = CursorContextV1.from_request(
        parsed,
        GENERATION,
        last_product_gid=None,
        expires_at="2026-09-02T12:00:00Z",
    )
    assert parsed_cursor.request_context_bytes() == original_cursor.request_context_bytes()
    assert parsed_cursor.request_context_sha256 == original_cursor.request_context_sha256
    assert parsed_cursor.request is parsed
    assert parsed_cursor.request == request

    empty_query = _request(query="")
    assert "q=" in serialize_url_state(empty_query)
    assert parse_url_state(serialize_url_state(empty_query)).query == ""
    no_query = _request()
    assert "q=" not in serialize_url_state(no_query)
    assert parse_url_state(serialize_url_state(no_query)).query is None
    assert parse_url_state(serialize_url_state(_request(in_stock=True))).filters.in_stock is True


@pytest.mark.parametrize(
    ("query_string", "message"),
    [
        ("", "byte length"),
        ("game=magic", "missing required"),
        (
            "game=magic&productFamily=all&sort=product_gid_asc&pageSize=24&condition=nm",
            "unsupported key",
        ),
        (
            "game=magic&game=magic&productFamily=all&sort=product_gid_asc&pageSize=24",
            "duplicate key",
        ),
        (
            "game=magic&productFamily=all&q=a+b&sort=product_gid_asc&pageSize=24",
            "encoding is not canonical",
        ),
        (
            "game=magic&productFamily=all&q=%c3%89&sort=product_gid_asc&pageSize=24",
            "encoding is not canonical",
        ),
        (
            "game=magic&productFamily=all&q=%ZZ&sort=product_gid_asc&pageSize=24",
            "encoding is not canonical",
        ),
        (
            "game=magic&productFamily=all&inStock=1&sort=product_gid_asc&pageSize=24",
            "inStock value",
        ),
        (
            "game=magic&productFamily=all&sort=product_gid_asc&pageSize=024",
            "pageSize value",
        ),
        (
            "game=magic&productFamily=all&q=%41&sort=product_gid_asc&pageSize=24",
            "not canonical",
        ),
        (
            "game=digimon&productFamily=all&sort=product_gid_asc&pageSize=24",
            "runtime contract",
        ),
        (
            "game=magic&productFamily=single&productSubtype=booster-box"
            "&sort=product_gid_asc&pageSize=24",
            "runtime contract",
        ),
        (
            "game=magic&productFamily=all&sort=title_asc&pageSize=24",
            "runtime contract",
        ),
        (
            "game=magic&productFamily=all&sort=product_gid_asc&pageSize=101",
            "runtime contract",
        ),
        ("game&productFamily=all&sort=product_gid_asc&pageSize=24", "invalid"),
    ],
)
def test_url_state_rejects_noncanonical_duplicate_and_unsupported_input(
    query_string: str, message: str
) -> None:
    with pytest.raises(FacetContractError, match=message):
        parse_url_state(query_string)


def test_url_state_bounds_types_and_field_count() -> None:
    with pytest.raises(FacetContractError, match="plain text"):
        parse_url_state(b"game=magic")  # type: ignore[arg-type]
    with pytest.raises(FacetContractError, match="percent-encoded UTF-8"):
        parse_url_state("game=mágic")
    with pytest.raises(FacetContractError, match="byte length"):
        parse_url_state("x" * (facets.MAX_URL_STATE_BYTES + 1))
    with pytest.raises(FacetContractError, match="invalid"):
        parse_url_state("a=1&b=2&c=3&d=4&e=5&f=6&g=7&h=8")

    class RequestSubclass(CatalogRequestV1):
        pass

    base = _request()
    subclass = RequestSubclass(*(getattr(base, name) for name in CatalogRequestV1.__match_args__))
    with pytest.raises(FacetContractError, match="must be CatalogRequestV1"):
        serialize_url_state(subclass)

    forged = _request()
    object.__setattr__(forged, "sort", "title_asc")
    with pytest.raises(FacetContractError, match="violates the runtime contract"):
        serialize_url_state(forged)
    with pytest.raises(FacetContractError, match="exceeds the byte limit"):
        serialize_url_state(_request(query="x" * facets.MAX_URL_STATE_BYTES))


def test_family_and_game_transitions_preserve_only_compatible_v1_state() -> None:
    sealed = _request(
        family=RequestFamily.SEALED,
        query="shared query",
        in_stock=True,
        subtype="booster-box",
        page_size=33,
    )
    assert switch_family(sealed, RequestFamily.SEALED) == sealed
    single = switch_family(sealed, RequestFamily.SINGLE)
    assert single.product_family is RequestFamily.SINGLE
    assert single.filters == CatalogFiltersV1(in_stock=True, product_subtype=None)
    assert single.query == sealed.query
    assert single.page_size == sealed.page_size

    assert switch_game(sealed, Game.MAGIC) == sealed
    pokemon = switch_game(sealed, Game.POKEMON)
    assert pokemon.game is Game.POKEMON
    assert pokemon.product_family is RequestFamily.SEALED
    assert pokemon.filters == CatalogFiltersV1(in_stock=True, product_subtype=None)
    assert pokemon.query == sealed.query

    for function, value, message in (
        (switch_family, "sealed", "target request family"),
        (switch_game, "pokemon", "target game"),
    ):
        with pytest.raises(FacetContractError, match=message):
            function(sealed, value)  # type: ignore[arg-type]
    with pytest.raises(FacetContractError, match="facet request"):
        switch_family(object(), RequestFamily.ALL)  # type: ignore[arg-type]


def test_contextual_facets_apply_other_dimensions_and_exclude_their_own() -> None:
    request = _request(
        family=RequestFamily.SEALED,
        in_stock=False,
        subtype="booster-box",
    )
    result = evaluate_facets(_catalog(), request)
    assert result.result_count == 0
    assert result.items == ()
    assert tuple(facet.dimension for facet in result.facets) == (
        FacetDimension.PRODUCT_FAMILY,
        FacetDimension.IN_STOCK,
        FacetDimension.PRODUCT_SUBTYPE,
    )
    assert _counts(result.facet(FacetDimension.PRODUCT_FAMILY)) == (
        ("single", 0),
        ("sealed", 0),
        ("accessory", 0),
    )
    assert _counts(result.facet(FacetDimension.IN_STOCK)) == (("true", 1), ("false", 0))
    subtype = result.facet(FacetDimension.PRODUCT_SUBTYPE)
    assert _counts(subtype) == (("booster-box", 0), ("bundle", 1))
    assert subtype.missing_value_count == 1


def test_all_family_is_game_scoped_complete_and_gid_sorted() -> None:
    result = evaluate_facets(_catalog(), _request())
    assert evaluate_facets(tuple(reversed(_catalog())), _request()) == result
    assert tuple(item.product_gid for item in result.items) == tuple(
        f"gid://shopify/Product/{value}" for value in (2, 3, 4, 5, 6, 10)
    )
    assert _counts(result.facet(FacetDimension.PRODUCT_FAMILY)) == (
        ("single", 2),
        ("sealed", 3),
        ("accessory", 1),
    )
    assert _counts(result.facet(FacetDimension.IN_STOCK)) == (("true", 3), ("false", 3))
    with pytest.raises(FacetContractError, match="not exposed"):
        result.facet(FacetDimension.PRODUCT_SUBTYPE)

    sealed = evaluate_facets(_catalog(), _request(family=RequestFamily.SEALED))
    assert _counts(sealed.facet(FacetDimension.PRODUCT_SUBTYPE)) == (
        ("booster-box", 1),
        ("bundle", 1),
    )


def test_subtype_facet_returns_every_value_including_rare_beyond_top_100() -> None:
    high_cardinality = tuple(
        _item(
            1_000 + index,
            family=ProductFamily.SEALED,
            subtype=f"type-{index:03d}",
        )
        for index in reversed(range(105))
    )
    request = _request(family=RequestFamily.SEALED, subtype="type-104")
    result = evaluate_facets(high_cardinality, request)
    subtype = result.facet(FacetDimension.PRODUCT_SUBTYPE)
    assert len(subtype.values) == 105
    assert subtype.values[0] == FacetValueCount("type-000", 1)
    assert subtype.values[100] == FacetValueCount("type-100", 1)
    assert subtype.values[-1] == FacetValueCount("type-104", 1)
    assert result.result_count == 1


def test_query_scope_is_explicit_empty_safe_and_cross_game_fail_closed() -> None:
    catalog = _catalog()
    request = _request(query="resolved elsewhere", in_stock=True)
    scoped = evaluate_facets(
        catalog,
        request,
        query_product_gids=(
            "gid://shopify/Product/10",
            "gid://shopify/Product/2",
            "gid://shopify/Product/3",
        ),
    )
    assert tuple(item.product_gid for item in scoped.items) == (
        "gid://shopify/Product/2",
        "gid://shopify/Product/10",
    )
    assert _counts(scoped.facet(FacetDimension.IN_STOCK)) == (("true", 2), ("false", 1))

    empty = evaluate_facets(catalog, request, query_product_gids=())
    assert empty.result_count == 0
    assert _counts(empty.facet(FacetDimension.PRODUCT_FAMILY)) == (
        ("single", 0),
        ("sealed", 0),
        ("accessory", 0),
    )
    with pytest.raises(FacetContractError, match="cross-game"):
        evaluate_facets(
            catalog,
            request,
            query_product_gids=("gid://shopify/Product/8",),
        )


@pytest.mark.parametrize(
    ("catalog_request", "query_gids", "message"),
    [
        (_request(), (), "require a non-empty query"),
        (_request(query="x"), None, "canonical Product GID tuple"),
        (_request(query="x"), [], "canonical Product GID tuple"),
        (_request(query="x"), ("not-a-gid",), "canonical Product GID tuple"),
        (
            _request(query="x"),
            ("gid://shopify/Product/2", "gid://shopify/Product/2"),
            "must be unique",
        ),
        (_request(query="x"), ("gid://shopify/Product/999",), "belong to the facet input"),
    ],
)
def test_query_scope_rejects_ambiguous_or_invalid_context(
    catalog_request: CatalogRequestV1,
    query_gids: Any,
    message: str,
) -> None:
    with pytest.raises(FacetContractError, match=message):
        evaluate_facets(_catalog(), catalog_request, query_product_gids=query_gids)


def test_facet_input_and_result_types_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    catalog = _catalog()
    with pytest.raises(FacetContractError, match="immutable Product tuple"):
        evaluate_facets(list(catalog), _request())  # type: ignore[arg-type]
    with pytest.raises(FacetContractError, match="facet item"):
        evaluate_facets((object(),), _request())  # type: ignore[arg-type]
    with pytest.raises(FacetContractError, match="must be unique"):
        evaluate_facets((catalog[0], catalog[0]), _request())
    with pytest.raises(FacetContractError, match="facet request"):
        evaluate_facets(catalog, object())  # type: ignore[arg-type]

    forged_request = _request()
    object.__setattr__(forged_request.filters, "in_stock", 1)
    with pytest.raises(FacetContractError, match="request violates the runtime contract"):
        evaluate_facets(catalog, forged_request)

    forged_item = _item(99)
    object.__setattr__(forged_item.variants[0], "inventory_quantity", True)
    with pytest.raises(FacetContractError, match="item violates the runtime contract"):
        evaluate_facets((forged_item,), _request())

    with monkeypatch.context() as item_limit:
        item_limit.setattr(facets, "MAX_FACET_ITEMS", 1)
        with pytest.raises(FacetContractError, match="Product limit"):
            evaluate_facets(catalog[:2], _request())
    with monkeypatch.context() as query_limit:
        query_limit.setattr(facets, "MAX_QUERY_PRODUCT_GIDS", 1)
        with pytest.raises(FacetContractError, match="context limit"):
            evaluate_facets(
                catalog,
                _request(query="x"),
                query_product_gids=(
                    "gid://shopify/Product/2",
                    "gid://shopify/Product/3",
                ),
            )

    with pytest.raises(FacetContractError, match="Product GID must be canonical"):
        facets._product_gid_sort_key("gid://shopify/Product/0")


def test_oracle_uses_decoded_copies_not_forged_nested_runtime_objects() -> None:
    benign_filter_payload = CatalogFiltersV1(False, None).as_dict()

    class ForgedFilters(CatalogFiltersV1):
        def as_dict(self) -> dict[str, Any]:
            return dict(benign_filter_payload)

    request = _request(family=RequestFamily.SEALED, in_stock=False)
    forged_filters = ForgedFilters(True, None)
    object.__setattr__(request, "filters", forged_filters)
    result = evaluate_facets(_catalog(), request)
    assert tuple(item.product_gid for item in result.items) == (
        "gid://shopify/Product/5",
        "gid://shopify/Product/6",
    )
    assert "inStock=false" in serialize_url_state(request)

    benign_item = _item(30, inventory=0)
    benign_variant_payload = benign_item.variants[0].as_dict()

    class ForgedVariant(CatalogVariantItemV1):
        def as_dict(self) -> dict[str, Any]:
            return dict(benign_variant_payload)

    forged_variant = ForgedVariant(
        *(getattr(benign_item.variants[0], name) for name in CatalogVariantItemV1.__match_args__)
    )
    object.__setattr__(forged_variant, "inventory_quantity", 7)
    object.__setattr__(benign_item, "variants", (forged_variant,))
    assert not has_positive_inventory(benign_item)
    normalized = evaluate_facets((benign_item,), _request())
    assert not has_positive_inventory(normalized.items[0])
    assert type(normalized.items[0].variants[0]) is CatalogVariantItemV1


def test_optional_checkpoint_preserves_results_and_has_deterministic_calls() -> None:
    catalog = _catalog()
    request = _request(family=RequestFamily.SEALED, in_stock=False, subtype="booster-box")
    expected = evaluate_facets(catalog, request)
    call_counts = []

    for _ in range(2):
        calls = 0

        def checkpoint() -> None:
            nonlocal calls
            calls += 1

        assert evaluate_facets(catalog, request, checkpoint=checkpoint) == expected
        call_counts.append(calls)

    assert call_counts[0] == call_counts[1]
    assert call_counts[0] > len(catalog)


def test_checkpoint_cancellation_propagates_unchanged_without_partial_result() -> None:
    class RequestCancelled(Exception):
        pass

    cancellation = RequestCancelled()
    calls = 0

    def checkpoint() -> None:
        nonlocal calls
        calls += 1
        if calls == 10:
            raise cancellation

    with pytest.raises(RequestCancelled) as captured:
        evaluate_facets(_catalog(), _request(), checkpoint=checkpoint)

    assert captured.value is cancellation
    assert calls == 10


def test_query_scope_loop_is_cancellable_and_checkpoint_must_be_callable() -> None:
    catalog = _catalog()
    query_gids = tuple(item.product_gid for item in catalog if item.game is Game.MAGIC)

    class RequestCancelled(Exception):
        pass

    calls = 0

    def checkpoint() -> None:
        nonlocal calls
        calls += 1
        if calls == len(catalog) + 3:
            raise RequestCancelled

    with pytest.raises(RequestCancelled):
        evaluate_facets(
            catalog,
            _request(query="card"),
            query_product_gids=query_gids,
            checkpoint=checkpoint,
        )
    assert calls == len(catalog) + 3

    with pytest.raises(FacetContractError, match="checkpoint must be callable"):
        evaluate_facets(catalog, _request(), checkpoint=object())  # type: ignore[arg-type]


def test_inventory_and_price_labels_use_only_v1_facts() -> None:
    positive_untracked = _item(20, inventory=1, tracked=False)
    zero_tracked = _item(21, inventory=0, tracked=True, price="0")
    negative_untracked = _item(22, inventory=-2, tracked=False, price="0.000")
    assert has_positive_inventory(positive_untracked)
    assert inventory_fact_label(positive_untracked) == "Disponibile"
    assert not has_positive_inventory(zero_tracked)
    assert inventory_fact_label(zero_tracked) == "Esaurito"
    assert inventory_fact_label(negative_untracked) == "Esaurito"
    assert price_fact_label(None) == "n/d"
    assert price_fact_label("0") == "n/d"
    assert price_fact_label("0.000") == "n/d"
    assert price_fact_label("10.00") == "10.00"
    for invalid in (True, "-1", "1e2", "01.00", ""):
        with pytest.raises(FacetContractError, match="canonical decimal"):
            price_fact_label(invalid)  # type: ignore[arg-type]
    with pytest.raises(FacetContractError, match="facet item"):
        has_positive_inventory(object())  # type: ignore[arg-type]


def test_reference_result_value_objects_enforce_exact_immutable_shapes() -> None:
    count = FacetValueCount("true", 1)
    for value in ("", 1):
        with pytest.raises(FacetContractError, match="facet value"):
            FacetValueCount(value, 1)  # type: ignore[arg-type]
    for value in (True, -1):
        with pytest.raises(FacetContractError, match="facet count"):
            FacetValueCount("true", value)  # type: ignore[arg-type]

    facet = ContextualFacet(FacetDimension.IN_STOCK, (count,))
    with pytest.raises(FacetContractError, match="dimension must be canonical"):
        ContextualFacet("inStock", (count,))  # type: ignore[arg-type]
    with pytest.raises(FacetContractError, match="immutable count tuple"):
        ContextualFacet(FacetDimension.IN_STOCK, [count])  # type: ignore[arg-type]
    with pytest.raises(FacetContractError, match="immutable count tuple"):
        ContextualFacet(FacetDimension.IN_STOCK, (object(),))  # type: ignore[arg-type]
    with pytest.raises(FacetContractError, match="must be unique"):
        ContextualFacet(FacetDimension.IN_STOCK, (count, count))
    for missing in (True, -1):
        with pytest.raises(FacetContractError, match="missing facet count"):
            ContextualFacet(
                FacetDimension.PRODUCT_SUBTYPE,
                (),
                missing_value_count=missing,  # type: ignore[arg-type]
            )
    with pytest.raises(FacetContractError, match="only productSubtype"):
        ContextualFacet(FacetDimension.IN_STOCK, (), missing_value_count=1)

    evaluation = FacetEvaluation((), (facet,))
    with pytest.raises(FacetContractError, match="lookup dimension"):
        evaluation.facet("inStock")  # type: ignore[arg-type]
    with pytest.raises(FacetContractError, match="immutable CatalogItemV1 tuple"):
        FacetEvaluation([], ())  # type: ignore[arg-type]
    with pytest.raises(FacetContractError, match="immutable CatalogItemV1 tuple"):
        FacetEvaluation((object(),), ())  # type: ignore[arg-type]
    with pytest.raises(FacetContractError, match="immutable contextual tuple"):
        FacetEvaluation((), [])  # type: ignore[arg-type]
    with pytest.raises(FacetContractError, match="immutable contextual tuple"):
        FacetEvaluation((), (object(),))  # type: ignore[arg-type]
    with pytest.raises(FacetContractError, match="dimensions must be unique"):
        FacetEvaluation((), (facet, facet))


def test_backlog_inventory_names_every_requested_but_unrepresented_dimension() -> None:
    assert facets.UNSUPPORTED_FILTER_FIELDS == {
        "accessoryBrand": "backlog",
        "accessoryCompatibility": "backlog",
        "collectorNumber": "backlog",
        "condition": "backlog",
        "expansion": "backlog",
        "finish": "backlog",
        "language": "backlog",
        "priceRange": "backlog",
        "rarity": "backlog",
        "releaseDate": "backlog",
        "set": "backlog",
        "setCode": "backlog",
    }
    with pytest.raises(TypeError):
        facets.UNSUPPORTED_FILTER_FIELDS["condition"] = "verified"  # type: ignore[index]
