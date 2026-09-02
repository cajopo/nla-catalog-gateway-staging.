"""Synthetic acceptance oracle for deterministic single-card search.

This module deliberately does not implement a production index, SQL, HTTP, pagination,
or a public wire contract.  It consumes the frozen runtime v1 Product records so tests can
prove the search semantics before any provisional capability is promoted.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from enum import StrEnum

from nla_catalog_gateway.runtime_contract import CatalogProductRecordV1
from nla_catalog_gateway.taxonomy import Game, ProductFamily

MAX_ORACLE_RECORDS = 1_000_000
MAX_QUERY_CODEPOINTS = 256
MAX_CANONICAL_NAME_CODEPOINTS = 1_024


class CanonicalSearchError(ValueError):
    """A stable, value-free failure at the synthetic search-oracle boundary."""


class SearchMode(StrEnum):
    BROWSE = "browse"
    SEARCH = "search"


class MatchTier(StrEnum):
    EXACT = "exact"
    PREFIX = "prefix"
    CONTAINS = "contains"


_TIER_ORDER = {
    MatchTier.EXACT: 0,
    MatchTier.PREFIX: 1,
    MatchTier.CONTAINS: 2,
}


@dataclass(frozen=True, slots=True)
class SingleCardHit:
    """One duplicate-free Product-level oracle hit."""

    product_gid: str
    canonical_card_name: str
    normalized_card_name: str
    match_tier: MatchTier
    available: bool


@dataclass(frozen=True, slots=True)
class SingleCardSuggestion:
    """A normalized-name group built only from the selected result tier."""

    canonical_card_name: str
    normalized_card_name: str
    print_count: int
    available_print_count: int

    @property
    def available(self) -> bool:
        return self.available_print_count > 0


@dataclass(frozen=True, slots=True)
class SingleCardSearchResult:
    """Deterministic oracle output; not a public runtime DTO."""

    mode: SearchMode
    game: Game
    normalized_query: str
    match_tier: MatchTier | None
    hits: tuple[SingleCardHit, ...]
    suggestions: tuple[SingleCardSuggestion, ...]


@dataclass(frozen=True, slots=True)
class MissingCanonicalName:
    """A classified single that cannot participate in canonical-name search."""

    product_gid: str
    game: Game
    publishable: bool


@dataclass(frozen=True, slots=True)
class CanonicalNameReport:
    """Game-scoped accounting for canonical-name coverage."""

    game: Game
    single_record_count: int
    missing: tuple[MissingCanonicalName, ...]

    @property
    def missing_count(self) -> int:
        return len(self.missing)


def normalize_search_text(value: str) -> str:
    """Apply exactly NFKC, Unicode case-folding, and whitespace collapse.

    Punctuation is intentionally retained.  In particular, percent and underscore are
    ordinary literal characters; this oracle never applies SQL wildcard semantics.
    """

    if type(value) is not str:
        raise CanonicalSearchError("search text must be a plain string")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise CanonicalSearchError("search text must contain valid Unicode") from exc
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def search_single_cards(
    records: tuple[CatalogProductRecordV1, ...],
    *,
    game: Game,
    query: str,
) -> SingleCardSearchResult:
    """Search publishable singles in exactly one game using canonical names only.

    The strongest tier present wins globally: exact suppresses prefix and contains, while
    prefix suppresses contains.  Every Product in that tier is returned in normalized-name
    then unbounded-decimal Product-GID order.
    """

    checked_records = _validated_records(records)
    checked_game = _validated_game(game)
    normalized_query = _bounded_normalize(
        query,
        context="query",
        maximum=MAX_QUERY_CODEPOINTS,
    )
    if not normalized_query:
        return SingleCardSearchResult(
            mode=SearchMode.BROWSE,
            game=checked_game,
            normalized_query="",
            match_tier=None,
            hits=(),
            suggestions=(),
        )

    candidates: list[tuple[MatchTier, str, tuple[int, str], CatalogProductRecordV1]] = []
    for record in checked_records:
        if (
            record.game is not checked_game
            or record.product_family is not ProductFamily.SINGLE
            or not record.publishable
        ):
            continue
        canonical_name = record.canonical_card_name
        if canonical_name is None:
            raise CanonicalSearchError("publishable single is missing its canonical card name")
        normalized_name = _bounded_normalize(
            canonical_name,
            context="canonical card name",
            maximum=MAX_CANONICAL_NAME_CODEPOINTS,
        )
        tier = _match_tier(normalized_name, normalized_query)
        if tier is not None:
            candidates.append(
                (tier, normalized_name, _product_gid_sort_key(record.product_gid), record)
            )

    if not candidates:
        return SingleCardSearchResult(
            mode=SearchMode.SEARCH,
            game=checked_game,
            normalized_query=normalized_query,
            match_tier=None,
            hits=(),
            suggestions=(),
        )

    selected_tier = min(candidates, key=lambda candidate: _TIER_ORDER[candidate[0]])[0]
    selected = sorted(
        (candidate for candidate in candidates if candidate[0] is selected_tier),
        key=lambda candidate: (candidate[1], candidate[2]),
    )
    hits = tuple(
        SingleCardHit(
            product_gid=record.product_gid,
            canonical_card_name=record.canonical_card_name,
            normalized_card_name=normalized_name,
            match_tier=tier,
            available=record.total_inventory > 0,
        )
        for tier, normalized_name, _gid_key, record in selected
    )
    return SingleCardSearchResult(
        mode=SearchMode.SEARCH,
        game=checked_game,
        normalized_query=normalized_query,
        match_tier=selected_tier,
        hits=hits,
        suggestions=_group_suggestions(hits),
    )


def report_missing_canonical_names(
    records: tuple[CatalogProductRecordV1, ...],
    *,
    game: Game,
) -> CanonicalNameReport:
    """Account for classified singles with no canonical name in one mandatory game."""

    checked_records = _validated_records(records)
    checked_game = _validated_game(game)
    scoped = tuple(
        record
        for record in checked_records
        if record.game is checked_game and record.product_family is ProductFamily.SINGLE
    )
    missing = tuple(
        MissingCanonicalName(
            product_gid=record.product_gid,
            game=checked_game,
            publishable=record.publishable,
        )
        for record in sorted(scoped, key=lambda item: _product_gid_sort_key(item.product_gid))
        if record.canonical_card_name is None
    )
    return CanonicalNameReport(
        game=checked_game,
        single_record_count=len(scoped),
        missing=missing,
    )


def _validated_records(
    records: tuple[CatalogProductRecordV1, ...],
) -> tuple[CatalogProductRecordV1, ...]:
    if type(records) is not tuple:
        raise CanonicalSearchError("search records must be a tuple")
    if len(records) > MAX_ORACLE_RECORDS:
        raise CanonicalSearchError("search record limit exceeded")
    checked: list[CatalogProductRecordV1] = []
    seen: set[str] = set()
    for record in records:
        if type(record) is not CatalogProductRecordV1:
            raise CanonicalSearchError("search records must contain runtime v1 Product records")
        try:
            record.__post_init__()
            canonical = CatalogProductRecordV1.from_json_bytes(record.to_json_bytes())
        except Exception as exc:
            raise CanonicalSearchError("search record violates the runtime v1 contract") from exc
        if canonical.product_gid in seen:
            raise CanonicalSearchError("search records contain a duplicate Product GID")
        seen.add(canonical.product_gid)
        checked.append(canonical)
    return tuple(checked)


def _validated_game(game: Game) -> Game:
    if type(game) is not Game:
        raise CanonicalSearchError("game must be a canonical Game")
    return game


def _bounded_normalize(value: str, *, context: str, maximum: int) -> str:
    if type(value) is not str:
        raise CanonicalSearchError(f"{context} must be a plain string")
    if len(value) > maximum:
        raise CanonicalSearchError(f"{context} exceeds the oracle limit")
    normalized = normalize_search_text(value)
    if len(normalized) > maximum:
        raise CanonicalSearchError(f"normalized {context} exceeds the oracle limit")
    return normalized


def _match_tier(normalized_name: str, normalized_query: str) -> MatchTier | None:
    if normalized_name == normalized_query:
        return MatchTier.EXACT
    if normalized_name.startswith(normalized_query):
        return MatchTier.PREFIX
    if normalized_query in normalized_name:
        return MatchTier.CONTAINS
    return None


def _product_gid_sort_key(product_gid: str) -> tuple[int, str]:
    digits = product_gid.removeprefix("gid://shopify/Product/")
    return len(digits), digits


def _group_suggestions(
    hits: tuple[SingleCardHit, ...],
) -> tuple[SingleCardSuggestion, ...]:
    grouped: dict[str, list[SingleCardHit]] = {}
    for hit in hits:
        grouped.setdefault(hit.normalized_card_name, []).append(hit)
    suggestions: list[SingleCardSuggestion] = []
    for normalized_name in sorted(grouped):
        group = grouped[normalized_name]
        representative = min(group, key=lambda hit: _product_gid_sort_key(hit.product_gid))
        suggestions.append(
            SingleCardSuggestion(
                canonical_card_name=representative.canonical_card_name,
                normalized_card_name=normalized_name,
                print_count=len(group),
                available_print_count=sum(hit.available for hit in group),
            )
        )
    return tuple(suggestions)
