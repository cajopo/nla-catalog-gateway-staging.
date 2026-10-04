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

## Distinct-name correction (2026-09-21, issue #9 follow-up)

Real clone QA found that One Piece `Ma` showed ten suggestion labels but only three
base names: Machvise, Mad Treasure and Magellan. A read-only query on restored real
manifest `3edfbc59f731613b4684305efc676e9ff8739076024928ff3f9b21e432dd8864`
confirmed later matching names (Magura, Maha, Mahoroba, Makino, and others). The source
name field includes print suffixes; limiting raw source-name groups hid those names.
Pokemon `p` exposed the same problem with Pachirisu numeric-level suffixes.

The correction changes suggestions only. It groups scoped raw-name SQL totals into
base-name suggestions before applying the existing ten-result limit. Known suffixes:

- trailing ` (V.n)` or ` (V.n - description)` source print versions;
- only for One Piece, trailing `(OPnn-nnn)`, `(STnn-nnn)`, `(EBnn-nnn)`,
  `(PRBnn-nnn)` or `(P-nnn)`, after version removal;
- only for Pokemon, trailing ` Lv.n` (case insensitive), after version removal.

Other parenthesized text, token characteristics, `Lv.X`, `ex`, `VMAX`, unknown code
formats and numeric levels in other games are retained. This is not general removal
of parentheses, product identity inference, a new canonical-source rewrite, or a claim
that all future source annotation formats are recognized. Empty labels are forbidden.
Original canonical names, Shopify GIDs, source IDs, search columns, product results and
cursor semantics are unchanged. Selecting the suggested base name searches its prints;
counts still cover only the current matching game/query/stock scope. No product is
dropped, deduplicated out of search results or written to Shopify.

The aggregation checks the existing operation checkpoint during the Python merge and
after final ranking. The independent core verifier uses separate string parsing of
the declared suffix rules, while its product-search oracle still uses original names.
This was required by review: the old raw-name suggestion oracle would otherwise reject
the corrected generation. No schema migration, new index, service or cache is needed.

The first candidate-wheel diagnostic on the restored read-only database completed
eight representative four-game queries in 0.021–0.504 seconds. One Piece `Ma` produced
Machvise, Mad Treasure, Magellan, Magura, Maha, Mahoroba, Makino, Mamaragan, Mamboshi and
Mansherry, with counts6/2/15/3/3/3/23/4/3/8. That diagnostic preceded the Pokemon-level
and raw-name grouping refinements; final validation is recorded separately. These are
suggestion-component timings, not complete HTTP or concurrent-load acceptance.

Not deployed. Exact-head native CI and staging/clone checks remain required; GitHub
Actions currently has an unresolved pre-step failure on the preceding PR94 run. Do
not rerun failed infrastructure jobs blindly or relax coverage to ship this correction.
New-market ingestion is still NOT ACTIVE and awaits CardTrader access.

Final component run after both refinements: eight queries, 0.020–0.510 seconds,
all assertions PASS; Pokemon `p` now yields ten names (Pachirisu, Paint Roller,
Pal Pad, Palace Belt, Palace Book, Palafin, Palafin ex, Paldean Clodsire,
Paldean Clodsire ex, Paldean Student). Pachirisu aggregates60 matching products.
Database size/mtime unchanged, SQLite opened read-only. Wheel and probe reside only
in `/tmp/nla-distinct-suggestions-aByRe0`; no install, activation or serving change.
The later independent-oracle Unicode-offset correction does not change the benchmarked
search implementation. Reviewer confirmed the core-verification blocker resolved,
ran39 focused tests, and approved that final oracle correction without rerunning tests.

Focused search tests initially54 PASS (including two 30,001-product traversal cases).
Expanded search/core/HTTP-suggestion run170 PASS, with those two slow cases deselected
rather than rerun. Final additional negative-suffix/Unicode coverage run:

```powershell
python -m pytest tests/test_distinct_card_suggestions.py tests/test_core_evidence.py tests/test_search_sql.py -k 'not literal_search_traverses_30001' --basetemp <new-isolated-temp>/cases -o cache_dir=<new-isolated-temp>/cache --cov=nla_catalog_gateway.search_sql --cov=nla_catalog_gateway.core_evidence --cov-report=term-missing -q -x
```

134 passed,2 deselected in28.90seconds. The partial-file coverage gate exits1 at96.95%:
uncovered lines are existing collector-code facts in search_sql.py59–61 and existing
core-evidence command/report paths634–637/655/685, not the new grouping/oracle code.
No coverage threshold was reduced; this targeted run is NOT a full repository gate.
An earlier attempt had73 fixture setup errors because Windows denied access to the
shared pytest temporary directory; a new isolated basetemp/cache resolved that issue.
These results do not replace exact-head native CI or real storefront activation.
Final Ruff check/format PASS; staged preflight PASS147files/zero findings and diff
check PASS. Unicode confusables in negative fixtures use explicit escapes (same runtime
strings); targeted recheck34 PASS. Independent approval covers all three production
files, including the Unicode-safe independent oracle. No full-suite pass is claimed.
