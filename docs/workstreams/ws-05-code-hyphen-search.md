# Card-code spellings — 19 October 2026 (#115)

Branch: `agent/card-code-search-115`. Search delta `2c8c650` installed on the VPS
on 19 October, with combined Windows/Linux coverage at 100%.
GitHub delivery remains separate from operational state and is deferred to the
owner's authorized weekly handoff. No push, PR or workflow was performed here.

## Diagnosis against the operating service

The current context was reconciled with the owner's chat
`2. Fine Staging + Monitor + Backup + Chat Manutenzione.` and its local PM documents.
The shop already uses MAIN `175195881740`; no theme file was changed. The older
GitHub status is not a statement about the installed service.

Read-only SQLite and five authenticated HTTPS requests on 19 October established:

| Magic query | Stock filter | Before-fix HTTP result |
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
  Local Docker's Linux engine pipe is unavailable. The native check below closes
  this platform gap without changing tests, exclusions or the coverage threshold.
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

Rollout preserves the installed operator, timer, importer and monitoring pins
documented in the current local runbook. This branch is a search delta, not a full
replacement for the newer operational workstreams. The initial read-only diagnostics made
no service, timer, Shopify, PowerTools, MAIN, monitor or backup configuration changes.
Rollback pairs the previous application with its previous cursor semantics; no
database rollback is needed for these unchanged projection facts.

## Coverage gate closed on native Linux

The owner explicitly authorized completing the gate and installing the fix on
19 October, while keeping GitHub delivery separate. Source archive for local
commit `2c8c650efb2790ebf6cd4ccb61b3fc64c7d7cfb1` has SHA-256
`0fb78f467a6f937d779fb31e94162c413d6285f58b8c7edf8b5b317d8d604c59`.

The existing native Linux filesystem suite ran against this archive in a bounded
container on the VPS, with read-only source/root, a private temporary filesystem,
dedicated evidence, no network, no production environment, no listeners and no
managed-data mount. Python 3.13.15, pytest 9.1.1 and coverage 7.16.1:
**35 passed in 1.27 seconds, exit 0, no OOM**. The command measured branches with
`coverage run --branch --source=nla_catalog_gateway -m pytest` and selected only
`tests/test_generation_bundle_linux.py`.

An earlier broader isolated attempt also included search tests and the two
30,001-record scale proofs under coverage tracing; it reached its explicit
600-second duration limit, exit 1, without a reported assertion failure. Its
evidence is retained and is not counted as a passing run. Both scale cases had
already passed in the full Windows suite. Native validation was then scoped to
the platform-specific code needed to close the measured gap.

The raw Windows and Linux data were preserved and combined using only a source
path mapping (`/work/src/nla_catalog_gateway` to the local checkout). The original
explicit `--cov=nla_catalog_gateway` scope is unchanged. Both reporting commands
passed the existing `fail_under = 100` gate:

```text
coverage combine --rcfile=<path-map-config> --data-file=<combined-data> --keep <windows-data> <linux-data>
coverage report --rcfile=<path-map-config> --data-file=<combined-data>
coverage json --rcfile=<path-map-config> --data-file=<combined-data>
TOTAL: 11,215 statements, 0 missing; 3,862 branches, 0 missing/partial; 100%
```

All 32 measured files, per-file statement/branch counts and existing exclusions
are identical to the initial report. The independent reviewer verified directly
from the three coverage databases that combined arcs are exactly the union of
the raw runs (24,544 unique arcs). No result was fabricated or excluded to pass.
Reproduction and private reports remain in `output/card-code-search-20261019/`.

The independent review also approved the concrete installer, SHA-256
`182c2a755f3abf7aaf7947a0d7ef88d4c7097095dfa28147599f1547ee5decc4`,
after correcting its finalization failure classification. Default preparation
passed with the installed operator archive and all operational pins preserved.

Official contracts used: [coverage combine and path mapping](https://coverage.readthedocs.io/en/latest/commands/cmd_combine.html),
[Dockerfile FROM/COPY](https://docs.docker.com/reference/dockerfile/), and
[bounded transient services](https://www.freedesktop.org/software/systemd/man/latest/systemd-run.html).
Observed Docker behavior required the verified local base tag with pull disabled:
BuildKit interpreted a bare `sha256:<image-ID>` in `FROM` as a repository tag.
The final image's layer prefix was verified against the immutable installed ID.

## VPS installation and HTTPS acceptance

Installation run: `20261019t205146z-48551a72`. The new container started at
20:52:32 UTC on alternate loopback port 10001 while the previous runtime served
on 10000. Sampled public readiness stayed 200. After sustained candidate readiness,
the helper published its immutable image-upgrade receipt and retired the old
container at 21:01:26. Installation committed at **21:05:56 UTC**; final evidence
was recorded at **21:10:37 UTC**. No uninterrupted-availability measurement or
browser/theme interaction is claimed.

| Binding | Installed value |
| --- | --- |
| Image | `sha256:2231c268945bf3681c83b2f0fafa9ae71a0751e46972c963c205463fc2b24a22` |
| Image base | Unchanged installed `sha256:8a23ad0809ed155665decdea9dff875dd198f1fefe2e5764e20798a31a22ece8` / runtime `ed24a61` |
| Search source delta | `2c8c650efb2790ebf6cd4ccb61b3fc64c7d7cfb1` |
| Current container | `b89865e8b7eefc7871c9b0a1a80dd94bb25ff959db689075e85d4da8fa07695c`, restart 0, no OOM |
| Current manifest | `53d179f8263715ab08002c74b34913239fbbfc426b86330b4ce55ad3d14e746c` |
| Activation SHA-256 | `e57b63207eae26176949e3cc378c0fa7c883a56a9a1be80faf5a5eb292c1f7bf`, unchanged |
| HTTP dataset identity | `sha256:ff833e9f9b51ab552763f76122dd41c1b0a81ee8f609fb5099b0079c410cdb02` |
| Source age origin | `2026-10-19T15:00:27Z`, unchanged |
| Accepted environment SHA-256 | `f6cebc61dcfd4dd404aa6ef3c6bff7e1122c22c732becc34631cde22f4e4d187`, unchanged |
| Future-refresh config SHA-256 | `a8e711e331e88a5eaa182c4b3884b2c41c1a1d6becc4e727d2ef8b5505c56cb1` |

The image adds one layer containing exactly the four reviewed modules at their
effective `site-packages` import path. Its base layers, package file inventory and
runtime settings were verified unchanged. All other installed runtime modules
match the branch after LF normalization. Module bytes in the layer match the
source archive exactly; CRLF/LF normalization is used only for comparisons.

Only `image` changed in the existing operational refresh configuration.
Operator/archive `881b9ca` (`291d967a77ca1295a385ebc6a72be72d64c721a32f3aac82d95d4d1a3600dcbd`),
both service/package paths, timer definitions, importer retry patch `8657aaa`
(module `04a16414...`), Caddy, backup and monitor configuration were preserved.
The future config passed the installed operator's complete archive/reference
validator. Both pipeline timers are active again; pending image installation is
archived under the run, with a separate immutable installation receipt. No Bulk
capture, dataset promotion, Shopify/PowerTools/MAIN operation or forced pipeline
cycle was performed. The next scheduled cycle has not yet been observed.

Five authenticated HTTPS search checks against the running image passed:

| Query | Filter | Result |
| --- | --- | --- |
| `FIN88` | All stock, facets | 200; one product, `Al Bhed Salvagers`, FIN / Uncommon |
| `FIN-88` | All stock, facets | Same product, suggestion and facets |
| `Al Bhed Salvagers` | All stock | Same product and suggestion |
| `FIN-88` | Available only | 200; no products/suggestions, because the printing is sold out |
| Deliberately missing code | All stock | 200; no products/suggestions |

Five further HTTPS requests passed at 21:10:40 UTC: both code forms in `all`,
Pokémon isolation, and two distinct numerically ordered keyset pages of
`Lightning Bolt`. All responses bound to the same dataset, and the pointer,
runtime identity, restart/OOM state and restored timers were checked unchanged.
These are signed calls to the public gateway; they do not exercise Shopify's
proxy forwarding or a browser interaction. Credentials, signed URLs and cursors
were never included in receipts or Git.

## Operational-health exception, preserved accurately

The first installer checked `/opsz` while both timers were intentionally stopped
and its image-upgrade marker remained present. It stopped at `https_acceptance`
with HTTPError after the runtime handoff/config update. Its failure evidence is
preserved. A separate exact-state finalizer was reviewed before execution
(SHA-256 `3bc79775fb19b99e1cbd0c421a61bb141e60b111f09b552c3bce0f59ebdd1c97`):
it did not retry replacement, recreated no container and changed no dataset.
It verified search/readiness, committed installation, archived the exact pending
marker under importer→refresh locks, released both locks, then restored timers
and ran the unchanged ordinary observer. Installation and health acceptance
remain distinct records.

The fresh observer then reported **`market_incomplete`**, not a search failure.
This condition predates deployment: 102 collector records between 20:00 and
20:52:30 UTC show it, including 20:52:13; replacement began at 20:52:31.
The unchanged immutable market receipt is `draft_cycle_partial` for
`market-20261019t140017z-be2a057f`, SHA-256
`5fb4de9672fcc50d5194db59214ff5458985479d6764bc6631d8aae0ebc72096`.

Final readiness is **GET 200**. Operational health remains **GET/HEAD `/opsz` 503**,
with `operationalHealthPassed: false` and
`operationalHealthAcceptance: preexisting_market_incomplete` explicitly recorded.
No market receipt was rewritten and no monitor warning was suppressed. Resolving
that market condition is separate maintenance; it is not claimed complete here.

The exact-state evidence closure was independently approved (SHA-256
`188ea619265107f4793417f4ce41472e1adc29b4f9de2ca43e4b1d06f6fea774`).
Private VPS evidence is in `/opt/nla-staging/search-code-2c8c650/rollout/` and
`/var/lib/nla-catalog-refresh/20261019t205146z-48551a72/`; local signed-call summaries,
raw coverage and reviewed scripts are retained in the ignored output directory.
Previous image/container and immutable receipts remain available for inspected
rollback. Do not rerun either one-time installer or finalizer.
