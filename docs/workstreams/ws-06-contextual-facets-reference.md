# WS-06 — Canonical v1 filter state and contextual-facet oracle

This issue #10 slice is synthetic and code-only. It defines a framework-independent
acceptance oracle for the fields already frozen by issue #28; it does not implement SQL,
HTTP, HMAC, UI, Shopify access, live-data measurement, or capability promotion.

## Canonical URL state

The URL query is the canonical serialization of one `CatalogRequestV1`. Keys are emitted in
this fixed order:

1. `game`;
2. `productFamily`;
3. nullable `q` (present with an empty value when the request distinguishes `""` from null);
4. nullable `inStock` as lowercase `true|false`;
5. nullable `productSubtype`;
6. the only v1 sort, `product_gid_asc`;
7. `pageSize`.

UTF-8 values use uppercase percent escapes and spaces use `%20`, never `+`. The parser accepts
only this canonical representation. Missing/unknown/duplicate keys, repeated scalar values,
non-canonical escaping, invalid enums/types, oversized state, an unsupported sort, and a
`productSubtype` outside `sealed` fail closed with stable value-free errors. Parsing and
re-serializing therefore reproduces the same bytes, and the resulting `CatalogRequestV1`
produces the same issue #28 cursor request-context bytes and digest.

V1 has scalar selections only, so repeated values are represented as duplicate keys and are
rejected. Duplicate elimination for a future multi-value facet is not representable in this
wire contract and requires an explicit versioned extension rather than comma-delimited or
repeated-key interpretation.

A family change clears `productSubtype` and preserves the common compatible state: game,
query, `inStock`, sort, and page size. A game change also clears `productSubtype`, whose
cross-game meaning has not been evidenced, while preserving the other canonical request
fields. Cursor tokens and page numbers are not added here because they are not fields in the
issue #28 request contract; cursor encoding/HMAC remains owned by issue #7.

## Reference facet algebra

The oracle applies dimensions with AND semantics. The two v1 scalar filters have a single
value, so their within-dimension semantics are degenerate OR. A future multi-value extension
must explicitly use OR within that one facet without changing the AND-across-facets rule.

Each facet count applies game, query scope, family, and every other active filter while
excluding its own active selection:

- `productFamily` always returns `single`, `sealed`, and `accessory` in that order, including
  zero counts; `all` is a request mode and is never persisted as a Product family;
- `inStock` always returns complete `true`, then `false` counts;
- `productSubtype` is exposed only for `sealed`, returns every observed value in lexical
  order without a top-100 truncation, retains an active-but-absent value with count zero, and
  separately accounts for sealed Products whose nullable subtype is missing.

Result Products use full Shopify Product GID identity and deterministic numeric-GID order.
The input may contain multiple games, but only the mandatory request game can match. Search
ranking and text matching are intentionally not duplicated: when `q` is non-empty, the search
workstream must supply an exact, unique tuple of matching Product GIDs. Unknown, duplicated,
malformed, or cross-game query GIDs are rejected rather than ignored. An empty tuple is a
valid explicit empty search result.

## Prepared evaluation boundary

`PreparedFacetCatalog` decodes and validates the immutable Product graph once when a
generation is activated. It then retains canonical items in numeric Product-GID order and
the derived positive-inventory fact used by the accepted algebra. Each request still
round-trips its `CatalogRequestV1`, validates every supplied search GID, evaluates the same
contextual counts, and runs cooperative checkpoints throughout; it does not rebuild or
re-serialize the complete Variant graph.

The regression suite evaluates a high-cardinality filtered request over 30,001 prepared
Products inside the two-second runtime budget. Preparation remains an activation operation,
not request handling, and this boundary does not authorize public output or change any
capability state.

## Inventory and price facts

`inStock=true` means only that at least one v1 Variant has `inventoryQuantity > 0`;
`inStock=false` means no Variant has a positive quantity. The reference label is
`Disponibile` or `Esaurito` respectively. `inventoryTracked` and `inventoryPolicy` do not
change this fact and are not used to invent purchasability or oversell policy.

A positive canonical `priceText` is preserved exactly. Missing or exact-zero decimal text is
presented as `n/d`; this helper does not create a nullable price field in any issue #28 DTO.
Price filtering and price sorting remain unsupported because their aggregation semantics and
baseline evidence are not frozen.

## Explicitly unsupported/backlog

The following candidate dimensions are not accepted in URL state and are not added to the
issue #28 wire contract: language, expansion/set/set code, condition, finish, rarity,
collector number, price range, accessory brand/compatibility, and release date.
Selected-option display text is not promoted into a canonical condition/finish/language
vocabulary. Additional sorts likewise remain backlog until producer coverage and
normalization rules are independently evidenced.

`CapabilityMatrixV1.facets` and `catalogOutput` remain `unsupported`. These tests prove the
reference algebra and bounded prepared high-cardinality evaluation only; they do not prove
the real baseline, SQL equivalence, or a production serving path.
