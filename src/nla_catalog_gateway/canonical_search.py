"""Deterministic single-card search semantics and prepared in-memory index.

This module deliberately does not implement SQL, HTTP, pagination, or a public wire
contract.  It consumes frozen runtime v1 Product records so callers can prepare one
generation-scoped index without promoting any provisional capability.
"""

from __future__ import annotations

import unicodedata
from bisect import bisect_left
from collections.abc import Callable
from dataclasses import dataclass, field
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
class _IndexedSingleCard:
    product_gid: str
    canonical_card_name: str
    normalized_card_name: str
    product_gid_sort_key: tuple[int, str]
    available: bool


@dataclass(frozen=True, slots=True)
class _GameSingleCardIndex:
    game: Game
    entries: tuple[_IndexedSingleCard, ...]
    normalized_names: tuple[str, ...]


_SEARCH_INDEX_SEAL = object()


@dataclass(frozen=True, slots=True, init=False, repr=False)
class SingleCardSearchIndex:
    """Opaque, immutable search index prepared once for one catalog generation."""

    _games: tuple[_GameSingleCardIndex, ...] = field(repr=False)
    _seal: object = field(repr=False)

    def __new__(cls, *_args: object, **_kwargs: object) -> SingleCardSearchIndex:
        raise CanonicalSearchError("search index must be created from runtime v1 records")

    def search(
        self,
        *,
        game: Game,
        query: str,
        checkpoint: Callable[[], None] | None = None,
    ) -> SingleCardSearchResult:
        """Search this generation snapshot without touching Product graphs."""

        return _search_prepared_index(
            self,
            game=game,
            query=query,
            checkpoint=checkpoint,
        )


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
    except UnicodeEncodeError:
        invalid_unicode = True
    else:
        invalid_unicode = False
    if invalid_unicode:
        # Raise outside the handler so the public error retains neither an attacker-
        # controlled cause nor an implicit exception context.
        raise CanonicalSearchError("search text must contain valid Unicode")
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def prepare_single_card_search(
    records: tuple[CatalogProductRecordV1, ...],
    *,
    checkpoint: Callable[[], None] | None = None,
) -> SingleCardSearchIndex:
    """Validate one generation and prepare immutable game-scoped search indexes."""

    if checkpoint is not None:
        checkpoint()
    checked_records = _validated_records(records, checkpoint=checkpoint)
    game_indexes: list[_GameSingleCardIndex] = []
    for game in Game:
        if checkpoint is not None:
            checkpoint()
        game_indexes.append(
            _build_game_index(
                checked_records,
                game=game,
                checkpoint=checkpoint,
            )
        )
    index = object.__new__(SingleCardSearchIndex)
    object.__setattr__(index, "_games", tuple(game_indexes))
    object.__setattr__(index, "_seal", _SEARCH_INDEX_SEAL)
    return index


def search_single_cards(
    records: tuple[CatalogProductRecordV1, ...] | SingleCardSearchIndex,
    *,
    game: Game,
    query: str,
    checkpoint: Callable[[], None] | None = None,
) -> SingleCardSearchResult:
    """Search publishable singles in exactly one game using canonical names only.

    The strongest tier present wins globally: exact suppresses prefix and contains, while
    prefix suppresses contains.  Every Product in that tier is returned in normalized-name
    then unbounded-decimal Product-GID order.  A checkpoint may cancel by raising; its return
    value is ignored and its exception propagates unchanged, without a partial result.

    Existing tuple callers remain supported.  Serving callers should instead pass the
    concrete index returned by :func:`prepare_single_card_search`, prepared once when the
    verified catalog generation is activated.
    """

    if type(records) is SingleCardSearchIndex:
        return _search_prepared_index(
            records,
            game=game,
            query=query,
            checkpoint=checkpoint,
        )
    if checkpoint is not None:
        checkpoint()
    checked_records = _validated_records(records, checkpoint=checkpoint)
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

    return _search_game_index(
        _build_game_index(
            checked_records,
            game=checked_game,
            checkpoint=checkpoint,
        ),
        normalized_query=normalized_query,
        checkpoint=checkpoint,
    )


def _build_game_index(
    records: tuple[CatalogProductRecordV1, ...],
    *,
    game: Game,
    checkpoint: Callable[[], None] | None,
) -> _GameSingleCardIndex:
    entries: list[_IndexedSingleCard] = []
    for record in records:
        if checkpoint is not None:
            checkpoint()
        if (
            record.game is not game
            or record.product_family is not ProductFamily.SINGLE
            or not record.publishable
        ):
            continue
        canonical_name = record.canonical_card_name
        if canonical_name is None:
            raise CanonicalSearchError("publishable single is missing its canonical card name")
        entries.append(
            _IndexedSingleCard(
                product_gid=record.product_gid,
                canonical_card_name=canonical_name,
                normalized_card_name=_bounded_normalize(
                    canonical_name,
                    context="canonical card name",
                    maximum=MAX_CANONICAL_NAME_CODEPOINTS,
                ),
                product_gid_sort_key=_product_gid_sort_key(record.product_gid),
                available=record.total_inventory > 0,
            )
        )

    if checkpoint is None:
        entries.sort(key=lambda entry: (entry.normalized_card_name, entry.product_gid_sort_key))
    else:

        def checkpointed_sort_key(
            entry: _IndexedSingleCard,
        ) -> tuple[str, tuple[int, str]]:
            checkpoint()
            return entry.normalized_card_name, entry.product_gid_sort_key

        entries.sort(key=checkpointed_sort_key)

    normalized_names: list[str] = []
    for entry in entries:
        if checkpoint is not None:
            checkpoint()
        normalized_names.append(entry.normalized_card_name)
    return _GameSingleCardIndex(
        game=game,
        entries=tuple(entries),
        normalized_names=tuple(normalized_names),
    )


def _search_prepared_index(
    index: SingleCardSearchIndex,
    *,
    game: Game,
    query: str,
    checkpoint: Callable[[], None] | None,
) -> SingleCardSearchResult:
    if checkpoint is not None:
        checkpoint()
    try:
        game_indexes = index._games
        seal = index._seal
    except (AttributeError, TypeError):
        invalid_index = True
    else:
        invalid_index = (
            type(index) is not SingleCardSearchIndex
            or seal is not _SEARCH_INDEX_SEAL
            or type(game_indexes) is not tuple
            or len(game_indexes) != len(Game)
        )
    if invalid_index:
        raise CanonicalSearchError("prepared search index is invalid")

    checked_game = _validated_game(game)
    normalized_query = _bounded_normalize(
        query,
        context="query",
        maximum=MAX_QUERY_CODEPOINTS,
    )
    for expected_game, game_index in zip(Game, game_indexes, strict=True):
        if checkpoint is not None:
            checkpoint()
        if type(game_index) is not _GameSingleCardIndex or game_index.game is not expected_game:
            raise CanonicalSearchError("prepared search index is invalid")
    if not normalized_query:
        return SingleCardSearchResult(
            mode=SearchMode.BROWSE,
            game=checked_game,
            normalized_query="",
            match_tier=None,
            hits=(),
            suggestions=(),
        )

    selected_game_index = game_indexes[tuple(Game).index(checked_game)]
    return _search_game_index(
        selected_game_index,
        normalized_query=normalized_query,
        checkpoint=checkpoint,
    )


def _search_game_index(
    index: _GameSingleCardIndex,
    *,
    normalized_query: str,
    checkpoint: Callable[[], None] | None,
) -> SingleCardSearchResult:
    start = bisect_left(index.normalized_names, normalized_query)
    selected: list[_IndexedSingleCard] = []
    selected_tier: MatchTier | None = None

    if start < len(index.normalized_names) and index.normalized_names[start] == normalized_query:
        selected_tier = MatchTier.EXACT
        for position in range(start, len(index.entries)):
            if checkpoint is not None:
                checkpoint()
            if index.normalized_names[position] != normalized_query:
                break
            selected.append(index.entries[position])
    else:
        for position in range(start, len(index.entries)):
            if checkpoint is not None:
                checkpoint()
            if not index.normalized_names[position].startswith(normalized_query):
                break
            selected.append(index.entries[position])
        if selected:
            selected_tier = MatchTier.PREFIX
        else:
            for entry in index.entries:
                if checkpoint is not None:
                    checkpoint()
                if normalized_query in entry.normalized_card_name:
                    selected.append(entry)
            if selected:
                selected_tier = MatchTier.CONTAINS

    if checkpoint is not None:
        checkpoint()
    if selected_tier is None:
        return SingleCardSearchResult(
            mode=SearchMode.SEARCH,
            game=index.game,
            normalized_query=normalized_query,
            match_tier=None,
            hits=(),
            suggestions=(),
        )

    hits_list: list[SingleCardHit] = []
    for entry in selected:
        if checkpoint is not None:
            checkpoint()
        hits_list.append(
            SingleCardHit(
                product_gid=entry.product_gid,
                canonical_card_name=entry.canonical_card_name,
                normalized_card_name=entry.normalized_card_name,
                match_tier=selected_tier,
                available=entry.available,
            )
        )
    hits = tuple(hits_list)
    return SingleCardSearchResult(
        mode=SearchMode.SEARCH,
        game=index.game,
        normalized_query=normalized_query,
        match_tier=selected_tier,
        hits=hits,
        suggestions=_group_suggestions(hits, checkpoint=checkpoint),
    )


def report_missing_canonical_names(
    records: tuple[CatalogProductRecordV1, ...],
    *,
    game: Game,
    checkpoint: Callable[[], None] | None = None,
) -> CanonicalNameReport:
    """Account for classified singles with no canonical name in one mandatory game.

    A checkpoint may cancel by raising; its return value is ignored and its exception
    propagates unchanged, without a partial report.
    """

    if checkpoint is not None:
        checkpoint()
    checked_records = _validated_records(records, checkpoint=checkpoint)
    checked_game = _validated_game(game)
    scoped: list[CatalogProductRecordV1] = []
    for record in checked_records:
        if checkpoint is not None:
            checkpoint()
        if record.game is checked_game and record.product_family is ProductFamily.SINGLE:
            scoped.append(record)

    if checkpoint is None:
        scoped.sort(key=lambda item: _product_gid_sort_key(item.product_gid))
    else:

        def checkpointed_sort_key(item: CatalogProductRecordV1) -> tuple[int, str]:
            checkpoint()
            return _product_gid_sort_key(item.product_gid)

        scoped.sort(key=checkpointed_sort_key)

    missing_items: list[MissingCanonicalName] = []
    for record in scoped:
        if checkpoint is not None:
            checkpoint()
        if record.canonical_card_name is None:
            missing_items.append(
                MissingCanonicalName(
                    product_gid=record.product_gid,
                    game=checked_game,
                    publishable=record.publishable,
                )
            )
    return CanonicalNameReport(
        game=checked_game,
        single_record_count=len(scoped),
        missing=tuple(missing_items),
    )


def _validated_records(
    records: tuple[CatalogProductRecordV1, ...],
    *,
    checkpoint: Callable[[], None] | None = None,
) -> tuple[CatalogProductRecordV1, ...]:
    if type(records) is not tuple:
        raise CanonicalSearchError("search records must be a tuple")
    if len(records) > MAX_ORACLE_RECORDS:
        raise CanonicalSearchError("search record limit exceeded")
    checked: list[CatalogProductRecordV1] = []
    seen: set[str] = set()
    for record in records:
        if checkpoint is not None:
            checkpoint()
        if type(record) is not CatalogProductRecordV1:
            raise CanonicalSearchError("search records must contain runtime v1 Product records")
        try:
            record.__post_init__()
            canonical = CatalogProductRecordV1.from_json_bytes(record.to_json_bytes())
        except Exception:
            record_invalid = True
        else:
            record_invalid = False
        if record_invalid:
            # Do not chain or retain nested runtime/serialization failures: their
            # messages may contain values controlled by the source record.
            raise CanonicalSearchError("search record violates the runtime v1 contract")
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


def _product_gid_sort_key(product_gid: str) -> tuple[int, str]:
    digits = product_gid.removeprefix("gid://shopify/Product/")
    return len(digits), digits


def _group_suggestions(
    hits: tuple[SingleCardHit, ...],
    *,
    checkpoint: Callable[[], None] | None = None,
) -> tuple[SingleCardSuggestion, ...]:
    grouped: dict[str, list[SingleCardHit]] = {}
    for hit in hits:
        if checkpoint is not None:
            checkpoint()
        grouped.setdefault(hit.normalized_card_name, []).append(hit)
    if checkpoint is None:
        normalized_names = sorted(grouped)
    else:

        def checkpointed_name_sort_key(normalized_name: str) -> str:
            checkpoint()
            return normalized_name

        normalized_names = sorted(grouped, key=checkpointed_name_sort_key)
    suggestions: list[SingleCardSuggestion] = []
    for normalized_name in normalized_names:
        if checkpoint is not None:
            checkpoint()
        group = grouped[normalized_name]
        representative = group[0]
        available_print_count = 0
        for hit in group:
            if checkpoint is not None:
                checkpoint()
            available_print_count += hit.available
        suggestions.append(
            SingleCardSuggestion(
                canonical_card_name=representative.canonical_card_name,
                normalized_card_name=normalized_name,
                print_count=len(group),
                available_print_count=available_print_count,
            )
        )
    return tuple(suggestions)
