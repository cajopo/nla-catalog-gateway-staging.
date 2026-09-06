"""Synthetic acceptance oracle for canonical v1 filter state and contextual facets.

This module deliberately contains no SQL, HTTP, cursor codec, Shopify access, or UI.
It evaluates only facts already exposed by the runtime v1 contract.  Search remains a
separate workstream: when ``q`` is active, callers must provide the exact Product GIDs
selected by that workstream rather than relying on an invented matcher here.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import StrEnum
from types import MappingProxyType
from urllib.parse import parse_qsl, quote, urlencode

from nla_catalog_gateway.runtime_contract import (
    CatalogFiltersV1,
    CatalogItemV1,
    CatalogRequestV1,
    RequestFamily,
    RuntimeContractError,
)
from nla_catalog_gateway.taxonomy import Game, ProductFamily

MAX_URL_STATE_BYTES = 4 * 1024
MAX_FACET_ITEMS = 1_000_000
MAX_QUERY_PRODUCT_GIDS = 1_000_000

_PRODUCT_GID_RE = re.compile(r"gid://shopify/Product/([1-9][0-9]*)\Z")
_PRICE_RE = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z")
_PERCENT_ESCAPE_RE = re.compile(r"%[0-9A-F]{2}")
_PAGE_SIZE_RE = re.compile(r"[1-9][0-9]*\Z")

_URL_KEY_ORDER = (
    "game",
    "productFamily",
    "q",
    "inStock",
    "productSubtype",
    "sort",
    "pageSize",
)
_REQUIRED_URL_KEYS = frozenset({"game", "productFamily", "sort", "pageSize"})
_SUPPORTED_URL_KEYS = frozenset(_URL_KEY_ORDER)
_PUBLIC_FAMILIES = (
    ProductFamily.SINGLE,
    ProductFamily.SEALED,
    ProductFamily.ACCESSORY,
)


class FacetContractError(ValueError):
    """A stable, value-free rejection from the synthetic facet oracle."""


class FacetDimension(StrEnum):
    PRODUCT_FAMILY = "productFamily"
    IN_STOCK = "inStock"
    PRODUCT_SUBTYPE = "productSubtype"


@dataclass(frozen=True, slots=True)
class FacetValueCount:
    """One deterministic facet value and its complete contextual Product count."""

    value: str
    count: int

    def __post_init__(self) -> None:
        if type(self.value) is not str or not self.value:
            raise FacetContractError("facet value must be non-empty plain text")
        if type(self.count) is not int or self.count < 0:
            raise FacetContractError("facet count must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class ContextualFacet:
    """Counts for one dimension after applying every other active dimension."""

    dimension: FacetDimension
    values: tuple[FacetValueCount, ...]
    missing_value_count: int = 0

    def __post_init__(self) -> None:
        if type(self.dimension) is not FacetDimension:
            raise FacetContractError("facet dimension must be canonical")
        if type(self.values) is not tuple or any(
            type(value) is not FacetValueCount for value in self.values
        ):
            raise FacetContractError("facet values must be an immutable count tuple")
        names = tuple(value.value for value in self.values)
        if len(set(names)) != len(names):
            raise FacetContractError("facet values must be unique")
        if type(self.missing_value_count) is not int or self.missing_value_count < 0:
            raise FacetContractError("missing facet count must be a non-negative integer")
        if self.dimension is not FacetDimension.PRODUCT_SUBTYPE and self.missing_value_count:
            raise FacetContractError("only productSubtype may account for missing values")


@dataclass(frozen=True, slots=True)
class FacetEvaluation:
    """Filtered Products and contextual facet counts for one canonical request."""

    items: tuple[CatalogItemV1, ...]
    facets: tuple[ContextualFacet, ...]

    def __post_init__(self) -> None:
        if type(self.items) is not tuple or any(
            type(item) is not CatalogItemV1 for item in self.items
        ):
            raise FacetContractError("evaluation items must be an immutable CatalogItemV1 tuple")
        if type(self.facets) is not tuple or any(
            type(facet) is not ContextualFacet for facet in self.facets
        ):
            raise FacetContractError("evaluation facets must be an immutable contextual tuple")
        dimensions = tuple(facet.dimension for facet in self.facets)
        if len(set(dimensions)) != len(dimensions):
            raise FacetContractError("evaluation facet dimensions must be unique")

    @property
    def result_count(self) -> int:
        return len(self.items)

    def facet(self, dimension: FacetDimension) -> ContextualFacet:
        if type(dimension) is not FacetDimension:
            raise FacetContractError("facet lookup dimension must be canonical")
        for facet in self.facets:
            if facet.dimension is dimension:
                return facet
        raise FacetContractError("facet is not exposed for this request family")


UNSUPPORTED_FILTER_FIELDS = MappingProxyType(
    {
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
)


def serialize_url_state(request: CatalogRequestV1) -> str:
    """Render the exact v1 request as a canonical query string."""

    request = _validated_request(request)
    values: dict[str, str] = {
        "game": request.game.value,
        "productFamily": request.product_family.value,
        "sort": request.sort,
        "pageSize": str(request.page_size),
    }
    if request.query is not None:
        values["q"] = request.query
    if request.filters.in_stock is not None:
        values["inStock"] = "true" if request.filters.in_stock else "false"
    if request.filters.product_subtype is not None:
        values["productSubtype"] = request.filters.product_subtype
    pairs = [(key, values[key]) for key in _URL_KEY_ORDER if key in values]
    rendered = urlencode(pairs, doseq=False, safe="", quote_via=quote)
    if len(rendered.encode("ascii")) > MAX_URL_STATE_BYTES:
        raise FacetContractError("catalog URL state exceeds the byte limit")
    return rendered


def parse_url_state(query_string: str) -> CatalogRequestV1:
    """Parse only the one canonical, duplicate-free v1 URL representation."""

    if type(query_string) is not str:
        raise FacetContractError("catalog URL state must be plain text")
    try:
        raw = query_string.encode("ascii")
    except UnicodeEncodeError as exc:
        raise FacetContractError("catalog URL state must use percent-encoded UTF-8") from exc
    if not raw or len(raw) > MAX_URL_STATE_BYTES:
        raise FacetContractError("catalog URL state has an invalid byte length")
    if "+" in query_string or not _has_canonical_percent_escapes(query_string):
        raise FacetContractError("catalog URL state encoding is not canonical")
    try:
        pairs = parse_qsl(
            query_string,
            keep_blank_values=True,
            strict_parsing=True,
            encoding="utf-8",
            errors="strict",
            max_num_fields=len(_SUPPORTED_URL_KEYS),
            separator="&",
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise FacetContractError("catalog URL state is invalid") from exc
    values: dict[str, str] = {}
    for key, value in pairs:
        if key in values:
            raise FacetContractError("catalog URL state contains a duplicate key")
        values[key] = value
    if not _REQUIRED_URL_KEYS.issubset(values):
        raise FacetContractError("catalog URL state is missing required keys")
    if not values.keys() <= _SUPPORTED_URL_KEYS:
        raise FacetContractError("catalog URL state contains an unsupported key")

    raw_in_stock = values.get("inStock")
    if raw_in_stock is None:
        in_stock = None
    elif raw_in_stock == "true":
        in_stock = True
    elif raw_in_stock == "false":
        in_stock = False
    else:
        raise FacetContractError("catalog URL inStock value is invalid")
    raw_page_size = values["pageSize"]
    if _PAGE_SIZE_RE.fullmatch(raw_page_size) is None:
        raise FacetContractError("catalog URL pageSize value is invalid")
    try:
        request = CatalogRequestV1(
            game=Game(values["game"]),
            product_family=RequestFamily(values["productFamily"]),
            query=values.get("q"),
            filters=CatalogFiltersV1(
                in_stock=in_stock,
                product_subtype=values.get("productSubtype"),
            ),
            page_size=int(raw_page_size),
            sort=values["sort"],
        )
    except (RuntimeContractError, ValueError) as exc:
        raise FacetContractError("catalog URL state violates the runtime contract") from exc
    if serialize_url_state(request) != query_string:
        raise FacetContractError("catalog URL state is not canonical")
    return request


def switch_family(request: CatalogRequestV1, family: RequestFamily) -> CatalogRequestV1:
    """Switch family while dropping the incompatible sealed-only subtype selection."""

    request = _validated_request(request)
    if type(family) is not RequestFamily:
        raise FacetContractError("target request family must be canonical")
    if family is request.product_family:
        return request
    return replace(
        request,
        product_family=family,
        filters=replace(request.filters, product_subtype=None),
    )


def switch_game(request: CatalogRequestV1, game: Game) -> CatalogRequestV1:
    """Switch game and clear subtype state whose cross-game meaning is unverified."""

    request = _validated_request(request)
    if type(game) is not Game:
        raise FacetContractError("target game must be canonical")
    if game is request.game:
        return request
    return replace(
        request,
        game=game,
        filters=replace(request.filters, product_subtype=None),
    )


def evaluate_facets(
    items: tuple[CatalogItemV1, ...],
    request: CatalogRequestV1,
    *,
    query_product_gids: tuple[str, ...] | None = None,
    checkpoint: Callable[[], None] | None = None,
) -> FacetEvaluation:
    """Evaluate AND-across-facets counts, excluding each facet's own selection.

    Multiple values within a future facet would be ORed, but v1 exposes only scalar
    ``inStock`` and ``productSubtype`` selections.  ``query_product_gids`` is required
    exactly when ``q`` is non-empty and is deliberately supplied by the search oracle.
    """

    if checkpoint is not None and not callable(checkpoint):
        raise FacetContractError("facet checkpoint must be callable")
    _run_checkpoint(checkpoint)
    request = _validated_request(request)
    items, item_by_gid = _validated_item_index(items, checkpoint=checkpoint)
    query_scope = _validated_query_scope(
        item_by_gid,
        request,
        query_product_gids,
        checkpoint=checkpoint,
    )
    filtered = _matching_items(
        items,
        request,
        query_scope,
        excluded=None,
        checkpoint=checkpoint,
    )

    family_base = _matching_items(
        items,
        request,
        query_scope,
        excluded=FacetDimension.PRODUCT_FAMILY,
        checkpoint=checkpoint,
    )
    family_totals = dict.fromkeys(_PUBLIC_FAMILIES, 0)
    for item in family_base:
        _run_checkpoint(checkpoint)
        family_totals[item.product_family] += 1
    family_counts = tuple(
        FacetValueCount(family.value, family_totals[family]) for family in _PUBLIC_FAMILIES
    )

    stock_base = _matching_items(
        items,
        request,
        query_scope,
        excluded=FacetDimension.IN_STOCK,
        checkpoint=checkpoint,
    )
    positive_inventory_count = 0
    for item in stock_base:
        _run_checkpoint(checkpoint)
        positive_inventory_count += _has_positive_inventory_fact(item)
    stock_counts = (
        FacetValueCount("true", positive_inventory_count),
        FacetValueCount("false", len(stock_base) - positive_inventory_count),
    )
    facets = [
        ContextualFacet(FacetDimension.PRODUCT_FAMILY, family_counts),
        ContextualFacet(FacetDimension.IN_STOCK, stock_counts),
    ]

    if request.product_family is RequestFamily.SEALED:
        subtype_base = _matching_items(
            items,
            request,
            query_scope,
            excluded=FacetDimension.PRODUCT_SUBTYPE,
            checkpoint=checkpoint,
        )
        subtype_totals: dict[str, int] = {}
        missing_subtype_count = 0
        for item in subtype_base:
            _run_checkpoint(checkpoint)
            if item.product_subtype is None:
                missing_subtype_count += 1
            else:
                subtype_totals[item.product_subtype] = (
                    subtype_totals.get(item.product_subtype, 0) + 1
                )
        if request.filters.product_subtype is not None:
            subtype_totals.setdefault(request.filters.product_subtype, 0)
        subtype_counts = tuple(
            FacetValueCount(subtype, subtype_totals[subtype]) for subtype in sorted(subtype_totals)
        )
        facets.append(
            ContextualFacet(
                FacetDimension.PRODUCT_SUBTYPE,
                subtype_counts,
                missing_value_count=missing_subtype_count,
            )
        )
    _run_checkpoint(checkpoint)
    return FacetEvaluation(filtered, tuple(facets))


def has_positive_inventory(item: CatalogItemV1) -> bool:
    """Return only whether any v1 Variant carries a strictly positive quantity fact."""

    item = _validated_item(item)
    return _has_positive_inventory_fact(item)


def inventory_fact_label(item: CatalogItemV1) -> str:
    """Label the quantity fact without inferring policy from inventory tracking."""

    return "Disponibile" if has_positive_inventory(item) else "Esaurito"


def price_fact_label(price_text: str | None) -> str:
    """Preserve a positive v1 price fact; render missing or exact zero as ``n/d``."""

    if price_text is None:
        return "n/d"
    if type(price_text) is not str or _PRICE_RE.fullmatch(price_text) is None:
        raise FacetContractError("price fact must be canonical decimal text or null")
    integer_and_fraction = price_text.replace(".", "")
    return "n/d" if set(integer_and_fraction) <= {"0"} else price_text


def _validated_request(request: CatalogRequestV1) -> CatalogRequestV1:
    if type(request) is not CatalogRequestV1:
        raise FacetContractError("facet request must be CatalogRequestV1")
    try:
        return CatalogRequestV1.from_json_bytes(request.to_json_bytes())
    except (AttributeError, RecursionError, RuntimeContractError, TypeError, ValueError) as exc:
        raise FacetContractError("facet request violates the runtime contract") from exc


def _validated_item(item: CatalogItemV1) -> CatalogItemV1:
    if type(item) is not CatalogItemV1:
        raise FacetContractError("facet item must be CatalogItemV1")
    try:
        return CatalogItemV1.from_json_bytes(item.to_json_bytes())
    except (AttributeError, RecursionError, RuntimeContractError, TypeError, ValueError) as exc:
        raise FacetContractError("facet item violates the runtime contract") from exc


def _has_positive_inventory_fact(item: CatalogItemV1) -> bool:
    return any(variant.inventory_quantity > 0 for variant in item.variants)


def _has_canonical_percent_escapes(query_string: str) -> bool:
    position = 0
    while True:
        position = query_string.find("%", position)
        if position < 0:
            return True
        if _PERCENT_ESCAPE_RE.match(query_string, position) is None:
            return False
        position += 3


def _validated_item_index(
    items: tuple[CatalogItemV1, ...],
    *,
    checkpoint: Callable[[], None] | None = None,
) -> tuple[tuple[CatalogItemV1, ...], dict[str, CatalogItemV1]]:
    if type(items) is not tuple:
        raise FacetContractError("facet input must be an immutable Product tuple")
    if len(items) > MAX_FACET_ITEMS:
        raise FacetContractError("facet input exceeds the Product limit")
    canonical_items = []
    result: dict[str, CatalogItemV1] = {}
    for item in items:
        _run_checkpoint(checkpoint)
        item = _validated_item(item)
        if item.product_gid in result:
            raise FacetContractError("facet input Product GIDs must be unique")
        canonical_items.append(item)
        result[item.product_gid] = item
    return tuple(canonical_items), result


def _validated_query_scope(
    item_by_gid: dict[str, CatalogItemV1],
    request: CatalogRequestV1,
    query_product_gids: tuple[str, ...] | None,
    *,
    checkpoint: Callable[[], None] | None = None,
) -> frozenset[str] | None:
    query_active = request.query not in (None, "")
    if not query_active:
        if query_product_gids is not None:
            raise FacetContractError("query Product GIDs require a non-empty query")
        return None
    if type(query_product_gids) is not tuple:
        raise FacetContractError("active query requires canonical Product GID tuple")
    if len(query_product_gids) > MAX_QUERY_PRODUCT_GIDS:
        raise FacetContractError("query Product GIDs exceed the context limit")
    result: set[str] = set()
    for gid in query_product_gids:
        _run_checkpoint(checkpoint)
        if type(gid) is not str or _PRODUCT_GID_RE.fullmatch(gid) is None:
            raise FacetContractError("active query requires canonical Product GID tuple")
        if gid in result:
            raise FacetContractError("query Product GIDs must be unique")
        if gid not in item_by_gid:
            raise FacetContractError("query Product GIDs must belong to the facet input")
        if item_by_gid[gid].game is not request.game:
            raise FacetContractError("query context must not contain cross-game Products")
        result.add(gid)
    return frozenset(result)


def _matching_items(
    items: tuple[CatalogItemV1, ...],
    request: CatalogRequestV1,
    query_scope: frozenset[str] | None,
    *,
    excluded: FacetDimension | None,
    checkpoint: Callable[[], None] | None = None,
) -> tuple[CatalogItemV1, ...]:
    matches = []
    for item in items:
        _run_checkpoint(checkpoint)
        if item.game is not request.game:
            continue
        if query_scope is not None and item.product_gid not in query_scope:
            continue
        if (
            excluded is not FacetDimension.PRODUCT_FAMILY
            and request.product_family is not RequestFamily.ALL
            and item.product_family.value != request.product_family.value
        ):
            continue
        if (
            excluded is not FacetDimension.IN_STOCK
            and request.filters.in_stock is not None
            and _has_positive_inventory_fact(item) is not request.filters.in_stock
        ):
            continue
        if (
            excluded is not FacetDimension.PRODUCT_SUBTYPE
            and request.filters.product_subtype is not None
            and item.product_subtype != request.filters.product_subtype
        ):
            continue
        matches.append(item)
    result = tuple(sorted(matches, key=lambda item: _product_gid_sort_key(item.product_gid)))
    _run_checkpoint(checkpoint)
    return result


def _run_checkpoint(checkpoint: Callable[[], None] | None) -> None:
    if checkpoint is not None:
        checkpoint()


def _product_gid_sort_key(product_gid: str) -> tuple[int, str]:
    match = _PRODUCT_GID_RE.fullmatch(product_gid)
    if match is None:
        raise FacetContractError("facet Product GID must be canonical")
    digits = match.group(1)
    return (len(digits), digits)
