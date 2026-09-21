"""Literal name/code search over the existing immutable catalog database.

SKU and barcode come from the retained Shopify variant records, never from titles.
Collector numbers come from source-ID-joined CSV metadata. Expansion names and
rarity are never searched. No printed-code punctuation is inferred from SKUs.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Callable
from dataclasses import replace

from nla_catalog_gateway.canonical_search import (
    MAX_CANONICAL_NAME_CODEPOINTS,
    MAX_QUERY_CODEPOINTS,
    CanonicalSearchError,
    SingleCardSuggestion,
    normalize_search_text,
)
from nla_catalog_gateway.facets import ContextualFacet, FacetDimension, FacetValueCount
from nla_catalog_gateway.runtime_contract import CatalogProductRecordV1, CatalogRequestV1

_PRINT_VERSION = re.compile(r" \(V\.[0-9]+(?: - [^()]+)?\)\Z")
_ONE_PIECE_NUMBER = re.compile(r" \((?:(?:OP|ST|EB|PRB)[0-9]{2}|P)-[0-9]{3}\)\Z")
_POKEMON_LEVEL = re.compile(r" Lv\.[0-9]+\Z", re.IGNORECASE)


def _suggestion_name(name: str, game: str) -> str:
    """Group observed source print suffixes, not arbitrary parenthesized card text.

    This is a suggestion label only: source names, IDs, search columns and product
    results remain unchanged. Selecting the base name searches all its prints.
    """
    label = _PRINT_VERSION.sub("", name)
    if game == "one-piece":
        label = _ONE_PIECE_NUMBER.sub("", label)
    if game == "pokemon":
        label = _POKEMON_LEVEL.sub("", label)
    return label if label.strip() else name


def search_facts(record: CatalogProductRecordV1) -> tuple[str, str, int]:
    """Derive reproducible search columns from an already validated Product."""
    name = record.canonical_card_name or ""
    normalized_name = normalize_search_text(name)
    if (
        record.publishable
        and record.product_family.value == "single"
        and (
            not normalized_name
            or len(name) > MAX_CANONICAL_NAME_CODEPOINTS
            or len(normalized_name) > MAX_CANONICAL_NAME_CODEPOINTS
        )
    ):
        raise CanonicalSearchError("public single canonical name is missing or exceeds its limit")
    codes = set()
    if record.card_metadata is not None and record.card_metadata.collector_number is not None:
        number = normalize_search_text(record.card_metadata.collector_number)
        if number:
            codes.add(number)
    for variant in record.variants:
        for code in (variant.sku, variant.barcode):
            if code is None:
                continue
            # JSON1 can truncate strings at NUL: reject instead of silently losing a code.
            if "\x00" in code:
                raise CanonicalSearchError("source code contains unsupported NUL")
            normalized = normalize_search_text(code)
            if normalized:
                codes.add(normalized)
    return (
        normalized_name,
        json.dumps(sorted(codes), ensure_ascii=False, separators=(",", ":")),
        int(any(variant.inventory_quantity > 0 for variant in record.variants)),
    )


def normalized_query(request: CatalogRequestV1) -> str:
    query = request.query or ""
    if len(query) > MAX_QUERY_CODEPOINTS:
        raise CanonicalSearchError("search query exceeds the character limit")
    normalized = normalize_search_text(query)
    if len(normalized) > MAX_QUERY_CODEPOINTS:
        raise CanonicalSearchError("normalized search query exceeds the character limit")
    return normalized


def search_scope(request: CatalogRequestV1) -> tuple[str, tuple[object, ...]]:
    """Only fixed SQL fragments are assembled; all request values are bound."""
    clauses = ["is_public = 1", "game = ?"]
    parameters: list[object] = [request.game.value]
    if request.product_family.value != "all":
        clauses.append("product_family = ?")
        parameters.append(request.product_family.value)
    query = normalized_query(request)
    if query:
        clauses.append(
            "(instr(normalized_card_name, ?) > 0 OR EXISTS "
            "(SELECT 1 FROM json_each(search_codes_json) AS code "
            "WHERE instr(code.value, ?) > 0))"
        )
        parameters.extend((query, query))
    if request.filters.in_stock is not None:
        clauses.append("has_positive_inventory = ?")
        parameters.append(int(request.filters.in_stock))
    if request.filters.product_subtype is not None:
        clauses.append("product_subtype = ?")
        parameters.append(request.filters.product_subtype)
    if request.filters.expansion_code is not None:
        clauses.append(
            "json_extract(CAST(product_record_json AS TEXT), '$.cardMetadata.expansionCode') = ?"
        )
        parameters.append(request.filters.expansion_code)
    if request.filters.rarity is not None:
        clauses.append(
            "json_extract(CAST(product_record_json AS TEXT), '$.cardMetadata.rarity') = ?"
        )
        parameters.append(request.filters.rarity)
    return " AND ".join(clauses), tuple(parameters)


def select_metadata_facets(
    connection: sqlite3.Connection,
    request: CatalogRequestV1,
    *,
    checkpoint: Callable[[], None] | None = None,
) -> tuple[ContextualFacet, ...]:
    """Complete contextual counts in one scan, never limited to the result page.

    Stream only the two metadata values and count each dimension in memory.
    SQLite GROUP BY on these expressions also sorts the full source JSON payload,
    overflowing the runtime's bounded temporary storage on the real catalog.
    """
    base = replace(request, filters=replace(request.filters, expansion_code=None, rarity=None))
    where, parameters = search_scope(base)
    sql = f"""SELECT json_extract(CAST(product_record_json AS TEXT),
                                 '$.cardMetadata.expansionCode'),
                     json_extract(CAST(product_record_json AS TEXT), '$.cardMetadata.rarity')
              FROM products WHERE {where}"""  # noqa: S608
    totals: tuple[dict[str, int], dict[str, int]] = ({}, {})
    missing = [0, 0]
    selected = (request.filters.expansion_code, request.filters.rarity)
    for expansion, rarity in connection.execute(sql, parameters):
        if checkpoint is not None:
            checkpoint()
        values = (expansion, rarity)
        for index in (0, 1):
            other = 1 - index
            if selected[other] is not None and values[other] != selected[other]:
                continue
            value = values[index]
            if value is None:
                missing[index] += 1
            else:
                totals[index][value] = totals[index].get(value, 0) + 1
    result = []
    for index, dimension in enumerate((FacetDimension.EXPANSION_CODE, FacetDimension.RARITY)):
        if selected[index] is not None:
            totals[index].setdefault(selected[index], 0)
        counts = []
        for value in sorted(totals[index]):
            if checkpoint is not None:
                checkpoint()
            counts.append(FacetValueCount(value, totals[index][value]))
        result.append(ContextualFacet(dimension, tuple(counts), missing[index]))
    return tuple(result)


def select_suggestions(
    connection: sqlite3.Connection,
    request: CatalogRequestV1,
    *,
    limit: int,
    checkpoint: Callable[[], None] | None = None,
) -> tuple[SingleCardSuggestion, ...]:
    if type(limit) is not int or not 1 <= limit <= 20:
        raise CanonicalSearchError("suggestion limit must be between 1 and 20")
    query = normalized_query(request)
    if not query:
        return ()
    where, parameters = search_scope(request)
    # The interpolated predicate contains fixed fragments only, never request values.
    sql = f"""SELECT canonical_card_name,
                     COUNT(*), SUM(has_positive_inventory)
              FROM products WHERE {where}
              GROUP BY canonical_card_name"""  # noqa: S608
    # Group before limiting: a run of print versions must not crowd out other names.
    groups: dict[str, SingleCardSuggestion] = {}
    for name, count, available in connection.execute(sql, parameters):
        if checkpoint is not None:
            checkpoint()
        label = _suggestion_name(name, request.game.value)
        normalized = normalize_search_text(label)
        previous = groups.get(normalized)
        groups[normalized] = SingleCardSuggestion(
            min(label, previous.canonical_card_name) if previous else label,
            normalized,
            count + (previous.print_count if previous else 0),
            available + (previous.available_print_count if previous else 0),
        )
    result = tuple(
        sorted(
            groups.values(),
            key=lambda item: (
                0
                if item.normalized_card_name == query
                else 1
                if item.normalized_card_name.startswith(query)
                else 2,
                item.normalized_card_name,
            ),
        )[:limit]
    )
    if checkpoint is not None:
        checkpoint()
    return result
