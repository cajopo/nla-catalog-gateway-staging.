# Family search completion — 2026-09-28

Workstream: #9 / approved taxonomy #19; architecture #17 and master #3.
Branch: `agent/family-search-v1`, based on runtime `9b56fdd`.

## Scope and behavior

The runtime now accepts a nonempty query for `all`, `sealed` and `accessory`,
not only `single`. The game remains mandatory. Public status, game, stock,
subtype filtering and authenticated keyset cursors retain their existing guards.

- `single`: unchanged canonical-card-name and verified source-code substring search.
- `sealed`: commercial-title substring search, plus the classified subtype when present.
- `accessory`: commercial-title substring search.
- `all`: the union of those family-specific matches, never single-card commercial
  titles, descriptions, generic tags or inferred identities.

Normalization is the existing Unicode NFKC + casefold + whitespace normalization.
Accents are retained: composed and decomposed `é` match, plain `e` is not substituted.
Punctuation, including `%` and `_`, is literal. SQL request values remain bound.
Results use the existing numeric `product_gid_asc` keyset ordering; this change
does not introduce relevance ranking or deep offsets. Suggestions and set/rarity
facets remain single-only and are explicitly rejected for the other families.

The current source contract restricts `cardMetadata` to source-identified singles.
There is no reliable structured sealed-expansion field to search independently;
an expansion is searchable when it is in the real commercial title. No field is
fabricated or borrowed from an unrelated single. Unclassified records remain
stored and counted in the manifest, not silently discarded or falsely published.

## Compatibility and boundaries

No projection schema, persisted search facts, source records or generation hashes
change. A connection-local, deterministic normalization function reads commercial
titles only on the new query branches. SQLite `CASE` evaluates only the relevant
family branch. Existing game/family/keyset indexes and deadline checkpoints remain
in use; result retrieval stays bounded to one page plus a continuation probe.

Existing schema-v2 packages can be read without recapture or regeneration. This is
a code-only runtime candidate. No deployment, Shopify write, theme MAIN change,
PowerTools change, external source acquisition or GitHub CI run is part of this work.

## Evidence

Focused family suite: **32 passed** locally, including signed HTTP requests through
the real evidence-bound backend without capability overrides. Coverage includes
family union, single-code regression, Unicode/case/whitespace, literal punctuation,
cross-game isolation, stock/subtype, numeric cursor traversal and context binding,
unclassified accounting, unchanged projection hash/schema/facts, index plans without
temporary sorting, deadline exception propagation and single-only extension guards.
Unsigned HTTP requests return 401; a missing game returns 400.

```text
python -m pytest tests/test_family_search.py -q --no-cov -o addopts= -p no:cacheprovider
ruff check --no-cache <three changed modules and two changed test files>
git diff --check
```

Ruff and diff checks passed. These focused checks are not full native CI, deployed
staging verification or a claim that the overall project is complete.

## Native candidate — built, not activated

Reviewed code `ed24a61f061c9ea226f3c37f145eb5deb37d4eb8` was archived and copied
to the VPS without stopping services or timers. Archive SHA256
`20fee824f9feb1414ae37aa7c459e4ba50ffa493d1dbb5eab5340cb7ebb932c0`.
At `/opt/nla-staging/family-search-ed24a61`, all32 family tests passed on native
Linux under UMask0077 in5.90s. The Docker build completed with image
`sha256:8a23ad0809ed155665decdea9dff875dd198f1fefe2e5764e20798a31a22ece8`.
Receipt: `native-candidate.json` in that private directory, explicitly
`candidate_built_not_activated`. No serving container, timer or source data changed.
Session50200 completed successfully; do not repeat the build or native test run.

Remaining: actual current-generation compatibility/readiness and guarded code-only
installation with coherent future refresh pins, followed by the theme candidate
and real-browser family round-trip. Preserve the existing warm operator rather
than accidentally replacing it with this branch's older deployment helpers.

Broader search/runtime regression: **311 passed in 404.35 seconds**, including
the existing synthetic 30,001-product pagination proofs. This run used the final
production delta; the final focused 32-test run additionally covered the explicit
lazy-single normalizer assertion and strengthened signed-HTTP checks.

```text
python -m pytest tests/test_family_search.py tests/test_search_sql.py tests/test_runtime_api.py tests/test_runtime_api_integration.py tests/test_runtime_suggestions.py tests/test_runtime_metadata_facets.py tests/test_metadata_filter_edges.py -q --no-cov -o addopts= -p no:cacheprovider
```

Independent reviewer `deferred_export_review` found no blocking issue and approved
the scoped commit, conditional on these regression and Ruff checks passing. The
review did not authorize deployment. No full-repository/native coverage gate or
deployed real-data query timing is claimed.

## Runtime deployment and browser evidence

Deployment update 2026-09-28: code `ed24a61` and the candidate image above were
activated using the existing generation, without source acquisition. Run
`20260928t193738z-06c1ef95`, completed19:46:58UTC; current container
`6a79982c43dc36e3057fdef3a7ac1160d191a1bdbbeca52e82694f84d6076c3f`.
Manifest, accepted environment and source time16:50:11UTC are unchanged.
HTTPS readiness200, freshness fresh, no pending markers, both source jobs idle.
Future operator `881b9ca` preserves warm activation and image-upgrade retention;
272 focused native tests passed. Both timers restored (market02/14UTC,
refresh03/15UTC), with no immediate extra capture.

Independent review found no installer signature/pin/recovery blocker; the known
one-time cold-start outage was explicitly reported, not represented as warm.
Native immutable receipts are in `/var/lib/nla-catalog-refresh/20260928t193738z-06c1ef95`
and `/opt/nla-staging/family-rollout-ed24a61/completed.json`. Do not rerun installer.
Clone browser confirms four real Magic booster boxes for sealed `booster`, mixed
ALL results, SINGLE separation, stock/query retention, Back/reload and no leakage
to Pokemon for Magic `Outlaws`. Detailed evidence is in the theme workstream's
`ws-10-family-selector.md`. No overall goal-completion or unattended-cycle claim.

## Official references consulted before implementation

- [SQLite application-defined functions and trusted schema](https://www.sqlite.org/appfunc.html)
- [Python 3.12 sqlite3 create_function](https://docs.python.org/3.12/library/sqlite3.html#sqlite3.Connection.create_function)
- [SQLite literal instr](https://www.sqlite.org/lang_corefunc.html#instr)
- [SQLite lazy CASE evaluation](https://www.sqlite.org/lang_expr.html#the_case_expression)
