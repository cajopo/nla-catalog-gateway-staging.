"""Literal name/code search over the existing immutable catalog database.

SKU and barcode come from the retained Shopify variant records, never from titles.
Collector numbers come from source-ID-joined CSV metadata. Expansion names and
rarity are never searched. No printed-code punctuation is inferred from SKUs.
"""

from __future__ import annotations

import json
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

    Group the two raw metadata fields together, then apply the other selection
    when counting each dimension. No new index, source or normalized vocabulary.
    """
    base = replace(request, filters=replace(request.filters, expansion_code=None, rarity=None))
    where, parameters = search_scope(base)
    sql = f"""SELECT json_extract(CAST(product_record_json AS TEXT),
                                 '$.cardMetadata.expansionCode'),
                     json_extract(CAST(product_record_json AS TEXT), '$.cardMetadata.rarity'),
                     COUNT(*)
              FROM products WHERE {where} GROUP BY 1, 2"""  # noqa: S608
    totals: tuple[dict[str, int], dict[str, int]] = ({}, {})
    missing = [0, 0]
    selected = (request.filters.expansion_code, request.filters.rarity)
    for expansion, rarity, count in connection.execute(sql, parameters):
        if checkpoint is not None:
            checkpoint()
        values = (expansion, rarity)
        for index in (0, 1):
            other = 1 - index
            if selected[other] is not None and values[other] != selected[other]:
                continue
            value = values[index]
            if value is None:
                missing[index] += count
            else:
                totals[index][value] = totals[index].get(value, 0) + count
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
    connection: sqlite3.Connection, request: CatalogRequestV1, *, limit: int
) -> tuple[SingleCardSuggestion, ...]:
    if type(limit) is not int or not 1 <= limit <= 20:
        raise CanonicalSearchError("suggestion limit must be between 1 and 20")
    query = normalized_query(request)
    if not query:
        return ()
    where, parameters = search_scope(request)
    # The interpolated predicate contains fixed fragments only, never request values.
    sql = f"""SELECT MIN(canonical_card_name), normalized_card_name,
                     COUNT(*), SUM(has_positive_inventory)
              FROM products WHERE {where}
              GROUP BY normalized_card_name
              ORDER BY CASE WHEN normalized_card_name = ? THEN 0
                            WHEN instr(normalized_card_name, ?) = 1 THEN 1 ELSE 2 END,
                       normalized_card_name
              LIMIT ?"""  # noqa: S608
    return tuple(
        SingleCardSuggestion(*row)
        for row in connection.execute(sql, (*parameters, query, query, limit))
    )
