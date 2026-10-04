# WS-05 — Name/code search v2 (#60)

## Requirement and scope

The 2026-09-15 active user goal supersedes the old strongest-tier-only, name-only
search semantics. New serving search matches the normalized literal substring in
the canonical card name OR a verified code, within the selected game. Exact and
prefix matches must not suppress other matching cards. Sold-out cards remain
included unless the caller explicitly selects an inventory filter. Draft,
unpublished and unclassified products stay out of public results, but remain in
baseline accounting. Shopify and PowerTools remain authoritative and unchanged.

## Implementation

- Extend the existing SQLite projection, rather than introduce another serving store.
- Projection schema v2 stores normalized name, a deduplicated JSON array of normalized
  SKU/barcode values and a positive-inventory fact. Reopen independently derives every
  indexed value from the retained canonical Product/Variant graph and rejects mismatch.
- Queries use parameter binding and `instr`, not LIKE/regex/full-text syntax. Unicode
  normalization stays NFKC + case-fold + whitespace collapse; punctuation remains literal.
  Source codes containing NUL explicitly reject the candidate, because SQLite JSON1 can
  otherwise truncate them silently. The previous valid generation is not replaced.
- Apply game/family, search, stock and subtype predicates before the limit. Continue
  with `(product_gid_length, product_gid_digits) > last_key`, retaining the existing
  HMAC-bound request/game/generation/page-size/expiry semantics. Never use OFFSET.
- Search cursor signatures have a v2 domain separator and search request fingerprints
  include `searchSemanticsVersion=2`; old name-only search cursors cannot resume under
  the new match rule. Plain-browse cursor format is unchanged.
- `CatalogProjection.suggest()` uses the same query/filter scope, groups matching prints
  by normalized name, counts matching products rather than variants, and returns at most
  20 suggestions. Exact/prefix ranking applies to suggestions only; result pages retain
  the existing Product-GID order. Empty input returns no suggestions.
- Runtime result fetching uses the shared SQLite paginator. The old in-memory search
  remains a historical v1 oracle for now; it is no longer the serving result path.
  Its prepared data and facet structures are still built by the old capability/evidence
  composition. Removing that bootstrap duplication is pending, not claimed here.

No speculative search technology is added. The game/family/GID index supports ordered
keyset traversal; substring predicates still examine candidate rows. This is not a claim
of an indexed substring lookup. Introduce a trigram index only if representative latency
measurements require it. Suggestions scan the selected result scope to count groups.

## Data and migration caveats

SKU and barcode are verified source values, but they are NOT necessarily printed card
numbers. The canonical CSV shape includes `collectorNumber` and `expansionCode`; the old
name-only join drops them. Recover the real CSVs and measure identity/field coverage before
adding that mapping. No title-derived or invented code is accepted. This issue and the
full goal are NOT complete while printed-code coverage remains unverified.

Schema-v1 SQLite packages must be rebuilt, not edited in place. The new reader rejects
them; retain the previous application AND its matching package for rollback. No existing
external package has been overwritten. Static output gates, App Proxy verification and
the six-evidence binding are unchanged; the branch does not enable public output.

## Verification / remaining deliveries

Focused synthetic tests cover name/code OR, partial codes, literal punctuation, game and
publication isolation, zero/negative stock, multiple matching variants without duplicate
products, bounded suggestions, cursor isolation and old-semantic rejection, and tampered
derived columns. A 30,001-result traversal exercises code-only matching on sold-out records,
the 24,999/25,000/25,001 boundary, complete ID equality and the SQL keyset query plan.
Execution results and independent review will be appended after completion.

Initial execution: `pytest tests/test_search_sql.py -q -x`: 20 passed in 143.96s,
including full 30,001 traversal. `pytest tests/test_runtime_contract.py -q -x`: 78 passed.
Independent review found one P2: SQLite JSON1 truncation at embedded NUL in source codes.
Explicit candidate rejection and regression tests for SKU and barcode were added.
Independent re-review: APPROVE; P2 resolved, no further actionable finding in that delta.

Fresh read-only inventory of the recovered staging projection found 291,787 public singles,
all with SKU and none with barcode (Magic 122,530; Pokemon 71,604; Yu-Gi-Oh 85,991;
One Piece 11,662). Sample SKUs concatenate set/collector and internal suffixes; literal SKU
lookup does not establish printed-code lookup. This inventory is not package
reauthentication or acceptance of a schema-v2 real build.

Final focused verification:

- Pagination/search coverage run excluding the two already executed large traversals:
  66 passed; `pagination.py` + `search_sql.py`: 730 statements, 236 branches, 100%.
  The initial broad run had 62 passing tests but failed coverage; extra cancellation,
  subtype and NUL regressions closed the uncovered branches. The gate was not lowered.
- Runtime API/integration excluding the separately exercised 30k timing case: 149 passed.
  That timing case passed in an earlier run before an obsolete test monkeypatch failed;
  its 30,001 HTTP traversal and sub-two-second search/filter assertions were executed.
  The old Python-hook cancellation tests now exercise the actual SQLite progress handler.
- Runtime contract: 78 passed. Ruff check and format pass on `src tests scripts`.
  The whole-directory formatter crashed on pre-existing inaccessible ignored test paths;
  no format rule was disabled. Preflight: 93 files, zero failures before final staging.
- `python -m build --no-isolation`: sdist and wheel built successfully. No isolated-build,
  full-suite, Docker or exact-head GitHub CI completion is claimed at this checkpoint.

No full issue closure or public readiness is claimed by these component checks.

Still required: real source recovery/collector-code join and coverage,
clone game selector/search UI, representative real-data latency, runtime activation,
durable live updates, deployment and E2E. Full roadmap/live gates remain in #3/#18.

## HTTP suggestion integration (2026-09-15 follow-up)

The existing authenticated catalog POST computes suggestions when the client explicitly
adds `includeSuggestions: true` for a nonblank `single` search with `cursor: null`, using
the same leased projection, game, query and filters as the result page. At most ten
normalized-name groups are returned, including sold-out
matches. Later cursor pages omit suggestions; they do not rerun the grouping scan.
No extra endpoint, provider or separate cache is introduced. Later pages must omit the
option or send false; asking for suggestions outside the first search page is rejected.

The v1 response gains an optional `suggestions` array. Each entry contains only
`canonicalCardName`, `matchingProductCount` and `availableProductCount`. Counts refer
to matching products in the selected scope, not variants or the total number of prints
of that name. A code-only match may therefore suggest a name that does not contain the
typed code. Opted-in searches without matches return `[]`. Requests without the option
(including existing search clients) retain exactly the legacy response fields. The
clone consumer will opt in and use the extended decoder. No default v1 wire change.

Input/output validation rejects malformed, duplicate or over-limit suggestion groups.
The shared deadline/cancellation and generation-file guards still apply; a failed
suggestion computation returns an error, never a partial HTTP 200. App Proxy checks,
readiness and static output gates are unchanged. This adds the wire implementation,
not deployment or public activation.

Initial follow-up verification: 40 new tests passed, including signed HTTP requests,
game/publication/stock isolation, code matches, pagination omission, empty queries,
malformed data, cancellation/failure and concurrent generation activation. The static
output gates are overridden only inside the HTTP tests; real proxy verification and
real evidence-bound leases are exercised. Review identified a compatibility P2 in the
initial unconditional extension; explicit opt-in and legacy-response tests resolve it.
Independent re-review approved the opt-in correction; no further actionable finding.
Final focused regression: 198 passed (runtime API, integration, suggestions and sync
publication), with 1,103 statements and 338 branches in `runtime_api.py` at 100%.
The separate HTTP test (`pytest tests/test_runtime_api_integration.py -q -k over_30000 -x`)
passed in 260.75s: 30,001 Products through 301 page requests without gaps/duplicates,
with search + opted-in suggestions together under two seconds and the stock filter
under two seconds. Synthetic fixture only, not a real-catalog latency acceptance.
Ruff/check/format and build `--no-isolation` pass; staged preflight: 97 files, zero findings.
Earlier exploratory runs failed
on test-fixture mistakes and stale coverage line maps while source changed; the final
coverage run above used frozen production code. No coverage threshold was relaxed.
CI for preceding commit `ab0c26e` is fully green: run `35004492258` (Python 3.12/3.13,
container, dependency audit) and CodeQL `35004492225`. Python 3.12 log: 2,249 tests passed,
11,863 statements and 3,968 branches at 100%, zero skipped. This does not certify the
newer suggestion delta, which needs its own exact-head CI.
