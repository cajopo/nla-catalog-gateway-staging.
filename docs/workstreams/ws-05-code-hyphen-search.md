# Card-code spellings — 19 October 2026 (#115)

Branch: `agent/card-code-search-115`. Local search fix; not installed on the VPS.
GitHub delivery remains separate from operational state and is deferred to the
owner's authorized weekly handoff. No push, PR, workflow or deployment is claimed.

## Diagnosis against the operating service

The current context was reconciled with the owner's chat
`2. Fine Staging + Monitor + Backup + Chat Manutenzione.` and its local PM documents.
The shop already uses MAIN `175195881740`; no theme file was changed. The older
GitHub status is not a statement about the installed service.

Read-only SQLite and five authenticated HTTPS requests on 19 October established:

| Magic query | Stock filter | Current HTTP result |
| --- | --- | --- |
| `FIN88` | None | 200, one product, suggestion `Al Bhed Salvagers` |
| `FIN-88` | None | 200, zero products and suggestions |
| `Al Bhed Salvagers` | None | 200, one product |
| `FIN88` | Available only | 200, zero products: this printing is sold out |
| `FIN88` | None, contextual facets requested | 200, one product and two facets |

The verified source SKU values already contain the compact `FIN88` prefix. The
serving predicate compared source codes literally, so inserting a hyphen prevented
the match. A missing full code does not require a new product or title-derived ID.
The initial hypothesis that this example needed a composite expansion/number alias
was superseded by the live data. No composite identifier is added by this fix.

HTTP observation: 16:28:46 UTC; active manifest
`ac4987afb0784244c32476dacc4c702bd55bd69a79a6df8e4e76baa2f83c77cc`.
The activation pointer was unchanged across the probe. Credentials and signatures
stayed in VPS memory. No snapshot, database or secret is included in Git.

## Change and compatibility

The shared single-card predicate retains literal canonical-name and source-code
matching and adds a comparison with ASCII `-` removed from both code and query.
This covers SKU, barcode and retained collector numbers, in both `single` and the
single-card portion of `all`. Other punctuation, leading zeros, game/publication
scope, stock and metadata filters retain their meanings. A hyphen-only query keeps
its original literal meaning; it cannot turn into an empty substring matching all
codes. Sealed/accessory titles retain literal punctuation.

Results, suggestions and contextual facets use the same predicate before limiting
or counting. Products remain distinct Shopify GIDs. Persisted search facts,
SQLite schema v2 and generation content are unchanged; existing packages can be
opened. No catalog rewrite, refresh or data migration is necessary.

Search cursor HMAC domain and request fingerprint use semantics v3, rejecting v2
search cursors so an existing traversal cannot silently change its match set.
Plain-browse cursors are unchanged. The independent raw-source core verifier also
checks compact source-code queries without calling the serving predicate.

## Native real-data check of the candidate

Candidate SELECT predicates were executed against the active immutable database
with `mode=ro&immutable=1` and `query_only=ON`; this did not install the application.
Observation: 16:38:19 UTC, manifest
`53d179f8263715ab08002c74b34913239fbbfc426b86330b4ce55ad3d14e746c`.
The normal refresh had advanced the generation between the two observations;
the pointer stayed unchanged throughout each individual diagnostic.

| Query | Matching products | Available products | Page + suggestions + facets SELECT time |
| --- | ---: | ---: | ---: |
| `FIN88` | 1 | 0 | 0.779 s |
| `FIN-88` | 1 | 0 | 0.775 s |
| `Lightning Bolt` | 74 | 0 | 0.589 s |
| Deliberately missing multiword query | 0 | 0 | 0.760 s |
| Pokémon `Pikachu` | 911 | 4 | 0.323 s |

These are five bounded native SELECT measurements, not HTTP latency, a load test,
or a claim that the running service contains the fix. The candidate search module
SHA-256 was `68aecaa9f69b4bc4ac49a689ff0c47194e2799931b69dff1480b04306aa93c22`.
Private diagnostic scripts and reports are retained outside tracked sources.

## Verification and handoff

Executable regressions are in `tests/test_card_code_search.py`,
`tests/test_runtime_suggestions.py` and `tests/test_search_sql.py`. They cover both
spellings, partial codes, case/NFKC, source fields, sold-out cards, unknown metadata,
literal names/punctuation, game/publication/family scope, filters/facets, complete
keyset pages, database reopening, and rejection of older cursor signatures.

Executed with Python 3.13.7 and SQLite 3.50.4 on Windows:

- Editable installation with development dependencies: PASS.
- `python -m ruff check .`: PASS.
- `python -m ruff format --check .`: PASS.
- `python scripts/preflight_repo.py`: PASS, 212 staged/tracked files, no failures.
- `python -m build`: PASS, isolated sdist and wheel builds.
- `python -m pytest --cov=nla_catalog_gateway --cov-report=term-missing
  --basetemp <external-temp> -p no:cacheprovider --tb=short -q -x`:
  **4,121 passed**, zero skips, one ResourceWarning, in 1,340.14 seconds.
  The command **exited 1 on the unchanged 100% coverage gate**: 99.43% overall.
  The warning reports an unclosed SQLite connection during a metadata-facet test;
  no assertion failed. It is recorded here without attributing a new root cause.
- The supplemental core-proof regression added during that run:
  **1 passed** in 5.42 seconds with `--cov-append`; the same global coverage gate
  still exited 1. Across both runs all **4,122 test cases passed**, none skipped.
- All four changed production modules have **100% statement/branch coverage**.
  The only uncovered production module is `generation_bundle.py`: 57 lines and
  one partial branch in the native Linux filesystem backend (1842–1981), which
  Windows does not exercise. It is byte-equivalent to base `90f4f49` after LF
  normalization; SHA-256 `327edf4c5b3ce22ac2ddf6eab18c0bad62eb923bfb0e1d3b7d09cc2bc3f14eb9`.
  Local Docker's Linux engine pipe is unavailable, so no native Linux result is
  claimed. This search branch does not change platform tests or lower/exclude the
  gate; the global coverage check remains unresolved before merge/deployment.
- Independent final review by `/root/review_card_codes`: approved, no actionable
  findings. Its separate in-memory check covered 7,140 retained-code/query pairs,
  literal names in `single`/`all`, and old-signature rejection. This is separate
  from pytest counts and the native real-data observations above.

The Windows sandbox prevented SQLite's atomic hard-link installation and Git's
shared-directory lock; development checks were run with the authorized local
execution permission. Core-proof test temporaries must be outside this checkout:
the verifier deliberately rejects projections inside the repository. No test,
coverage threshold or application boundary was disabled to accommodate that rule.
The supplementary test and report were also checked by the independent reviewer,
with no actionable findings. Full coverage data and private diagnostics are under
ignored `output/card-code-search-20261019/`; no CI/CodeQL success is claimed.

Rollout must preserve the installed operator, timer, importer and monitoring pins
documented in the current local runbook. This branch is a search delta, not a full
replacement for the newer operational workstreams. The read-only diagnostics made
no service, timer, Shopify, PowerTools, MAIN, monitor or backup configuration changes.
Rollback pairs the previous application with its previous cursor semantics; no
database rollback is needed for these unchanged projection facts.
