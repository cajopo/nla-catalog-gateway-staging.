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

## Official references consulted before implementation

- [SQLite application-defined functions and trusted schema](https://www.sqlite.org/appfunc.html)
- [Python 3.12 sqlite3 create_function](https://docs.python.org/3.12/library/sqlite3.html#sqlite3.Connection.create_function)
- [SQLite literal instr](https://www.sqlite.org/lang_corefunc.html#instr)
- [SQLite lazy CASE evaluation](https://www.sqlite.org/lang_expr.html#the_case_expression)
