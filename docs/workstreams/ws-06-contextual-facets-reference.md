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
6. optional `expansionCode`;
7. optional `rarity`;
8. the only v1 sort, `product_gid_asc`;
9. `pageSize`.

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

A family change clears `productSubtype`, `expansionCode`, and `rarity`, preserving game,
query, `inStock`, sort, and page size. A game change also clears those three selections, whose
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
issue #28 wire contract: language, expansion/set/setCode aliases, condition, finish,
collector number, price range, accessory brand/compatibility, and release date.
Selected-option display text is not promoted into a canonical condition/finish/language
vocabulary. Additional sorts likewise remain backlog until producer coverage and
normalization rules are independently evidenced.

`CapabilityMatrixV1.facets` and `catalogOutput` remain `unsupported`. These tests prove the
reference algebra and bounded prepared high-cardinality evaluation only; they do not prove
the real baseline, SQL equivalence, or a production serving path.

## September 21 extension: exact set/rarity filtering and optional SQL counts

This issue #10 backend slice extends the historical reference-only work above. It does
not change the immutable database schema or Shopify, and it does not yet add theme controls.

- `CatalogFiltersV1` accepts omitted-or-nonempty `expansionCode` and `rarity`, for `single`
  only. Values match the source-ID-joined `cardMetadata` literally, including case and
  Unicode; no rarity vocabulary or title-derived identity is invented. Explicit null
  extension values are rejected. Missing keys preserve legacy request/cursor bytes.
- Pagination and adaptive suggestions use the same bound SQL predicates. Game, public
  visibility, query, and stock constraints remain in force; SOLD OUT remains included
  when no stock selection is made. Missing metadata is not dropped from unfiltered results.
- Any `single` envelope, including a cursor page, may opt into `includeFacets: true`.
  Cursor validation precedes the count read; both use the same pinned generation, so
  direct page URLs and back/forward need no separate latest-generation facet query.
  Without this flag,
  the response keeps its existing shape. With it, `facets` contains exactly `expansionCode`
  then `rarity`, each with lexically ordered `{value,count}` entries and `missingValueCount`.
- Each count covers all matching products, not the result page. One streaming scan reads
  only the two raw fields, then applies the other dimension's selection. Selected absent values
  remain visible with zero counts; neither a top-100 limit nor a frequency cutoff is used.
- Page, suggestions and counts share the same acquired generation and operation deadline.
  A failed/timed-out facet read fails the response, rather than returning partial counts.
  Existing request/response size limits and safe capability defaults are not increased.

Real restored-baseline diagnostics found metadata on all 291,787 public singles, with
753/128/766/1,170 distinct set codes for Magic/One Piece/Pokemon/Yu-Gi-Oh respectively.
The diagnostic combined SQL aggregate took about 1.08/0.09/0.62/0.77 seconds on the VPS;
these are isolated query timings, **not** full HTTP or concurrent-load acceptance.
The four public sealed products remain outside these single-only metadata controls.

Tests: `test_metadata_filters.py`, `test_metadata_facet_counts.py`, and
`test_runtime_metadata_facets.py` cover legacy vectors, exact scopes, cursor binding,
48 SQL/oracle combinations, complete vocabularies, URL restoration/reset, signed HTTP,
generation activation during a request, cancellation, and fail-closed wire output.
Independent review passed with 133 tests. Full-suite results are recorded separately.

Local final regression: 3,250 tests passed in 1,667.14 seconds. A subsequent 64-test
coverage append included the 13 newly added edge cases (3,263 unique tests in the final
tree). All five modified modules have 100% statement/branch coverage. The Windows run
still exits nonzero at the repository-wide coverage gate: 99.39%, solely 57 statements
and one partial branch in the unchanged native Linux bundle backend. Its native tests
return on non-Linux hosts, so Windows PASS is not evidence for those operations. Keep
the 100% threshold unchanged and require the normal Ubuntu Python 3.12/3.13 CI gates
before promotion. No skipped/non-native case is claimed as native Linux acceptance.

An additional read-only VPS component run used the built candidate wheel (no installation)
against restored manifest `3edfbc59f731613b4684305efc676e9ff8739076024928ff3f9b21e432dd8864`.
It exercised first-page SQL, variant/item decoding, contextual counts, optional suggestions,
and public count validation/serialization: 24 cases (four games, browse/search/rare-set,
two passes) all completed in 0.058–1.460 seconds. The rare sets PTMT/J-P/20TH-S/PB-JP
returned 1/2/1/3 products, with the full contextual set lists retained. Output remained
below 60 KB. Copy size/mtime were unchanged. This supports using the existing SQLite
schema without another search service; it does **not** replace full signed HTTP, concurrent
load or clone acceptance. The disposable wheel/script live only in
`/tmp/nla-metadata-facets-cpiMam`, with no serving configuration or activation change.

Still required before storefront acceptance: runtime candidate validation on the real
catalog within its deadline; clone-only controls/URL/back navigation; E2E verification.
No deploy or MAIN-theme change is implied by this backend slice. New-market updates remain
blocked on CardTrader API access and are not supplied by these filters.

Cursor-facet follow-up: 197 focused runtime, metadata and suggestion tests PASS after
allowing `includeFacets` on subsequent single-family pages. The added cases verify
complete counts on page 2, a retained generation after activation, and invalid,
incompatible or unretained cursors rejected before count reads. Ruff and diff checks
PASS. Independent reviewer `/root/theme_title_review` approved the three-file delta
without High/Blocker findings; no lease, authorization or deadline path changed.
This follow-up has not been deployed and does not supersede the full CI gate.

2026-09-26 runtime-storage correction (#10): integrated image `5daca757` failed the
real-data component smoke with `database or disk is full` under the runtime's 64 MB
temporary filesystem. SQLite 3.46.1 EXPLAIN showed the metadata GROUP BY sorter
retaining full source JSON payloads. Stream the two extracted values and aggregate
their counts in Python instead; no new index, schema, service or storage allowance.
139 focused metadata tests PASS, Ruff/diff checks PASS; independent reviewer
`/root/refresh_recovery_review` approved the delta. Regression checks counts and
absence of temporary sorter instructions. Real 64 MB smoke remains the release gate.
See [SQLite temporary files](https://www.sqlite.org/tempfiles.html).
