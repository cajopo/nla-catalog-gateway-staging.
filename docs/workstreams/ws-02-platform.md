# WS-02 — repository and CI consolidation

## Scope

This workstream replaces the self-modifying bootstrap on `main` with a small, auditable platform foundation. It does not claim to implement catalog behavior, build the production dataset, deploy Render or modify a Shopify theme.

## Legacy removal

The following are intentionally removed:

- base64 source fragments under `bootstrap/`;
- the workflow that reconstructs an archive and pushes generated files directly to `main`;
- the workflow that commits generated catalog artifacts back to `main`;
- `.github/BUILD_REQUEST` and the obsolete bootstrap instructions.

Dataset build and refresh will return in WS-01/WS-07 as explicit, reviewed jobs whose outputs are external/versioned artifacts rather than source-control commits.

## PR #4 disposition

Every component of the archived monolithic prototype is accounted for below. `Kept` means the concept is retained in the roadmap, not that its code is copied without review.

| PR #4 component | Decision | Destination / reason |
|---|---|---|
| `.env.example` | Rewritten later | Environment contract belongs with the runtime/security workstreams; no secret-shaped placeholders are needed in the foundation. |
| `.github/dependabot.yml` | Rewritten now | Kept as a small, canonical dependency update policy. |
| `.github/workflows/ci.yml` | Rewritten now | Tests, formatting, preflight, build and container smoke actually execute. |
| `.github/workflows/codeql.yml` | Rewritten now | CodeQL runs queries, gates on zero SARIF findings and stores the report as an artifact. Repository Code Scanning upload is unavailable on the current private user-owned repository. |
| `.ruff.toml` | Rewritten now | Configuration is consolidated into `pyproject.toml`. |
| `Dockerfile` | Rewritten now | Minimal non-root foundation image; runtime server arrives separately. |
| `README.md` | Rewritten now | Removes hard-coded catalog claims and documents only approved boundaries. |
| `SECURITY.md` | Rewritten now | Repository controls and trust boundaries only. |
| `app/__init__.py` | Rewritten now | Package moves to `src/nla_catalog_gateway`. |
| `app/app_proxy.py` | Deferred | WS-08 SECURITY. |
| `app/bootstrap.py` | Discarded | First-start download/build is operationally fragile; WS-07/WS-09 will separate dataset jobs from serving. |
| `app/catalog.py` | Deferred | WS-03/WS-05/WS-06 after the canonical data contract. |
| `app/config.py` | Deferred | Added with the runtime workstream, not the platform skeleton. |
| `app/cursor.py` | Deferred | WS-03 PAGINATION and WS-08 SECURITY. |
| `app/database.py` | Deferred | WS-01/WS-03 after schema and swap contract are frozen. |
| `app/main.py` | Deferred | Public API runtime enters after data/search contracts; no fake HTTP service in this PR. |
| `app/models.py` | Deferred | API models depend on taxonomy and filter contracts. |
| `app/normalization.py` | Deferred | WS-05 SEARCH, with corpus and property tests. |
| `app/rate_limit.py` | Discarded as implementation | In-memory host-based limiting is unsuitable behind production proxies; WS-08 will redesign it. |
| `app/sync/__init__.py` | Deferred | WS-07 SYNC. |
| `app/sync/build_index.py` | Deferred | WS-01 DATA and WS-01B TAXONOMY. |
| `app/sync/shopify_bulk.py` | Deferred | WS-01/WS-07, preserving read-only Admin Bulk behavior. |
| `pyproject.toml` | Rewritten now | Minimal package and quality-tool contract. |
| `render.yaml` | Deferred | WS-09 DEPLOY after service/storage requirements are validated. |
| `scripts/build_catalog.py` | Deferred | WS-01 DATA. |
| `scripts/preflight.py` | Rewritten now | Repository-boundary preflight only; dataset/runtime preflights remain separate. |
| `scripts/validate_dataset.py` | Deferred | WS-01/WS-03 and protected real-dataset validation. |
| `tests/test_gateway.py` | Discarded as monolith | Tests are split by workstream; foundation tests cover only foundation claims. |
| `theme/assets/nla-catalog.css` | Deferred | WS-10 THEME. |
| `theme/assets/nla-catalog.js` | Deferred | WS-10 THEME after API contracts are stable. |
| `theme/manifest.json` | Deferred | WS-10 THEME release packaging. |
| `theme/sections/nla-catalog-search.liquid` | Deferred | WS-10 THEME. |
| `theme/snippets/nla-game-selector.liquid` | Deferred | WS-10 THEME. |
| `theme/templates/page.nla-catalog.json` | Deferred | WS-10 THEME. |

## CodeQL operating mode

The current repository is private and user-owned; GitHub accepted the CodeQL extraction and query execution but rejected SARIF upload because Code Scanning is not enabled. The workflow therefore uses the action's documented `upload: never` mode, parses the generated SARIF, fails on any finding and uploads that SARIF as a normal short-lived Actions artifact for independent review. Enabling GitHub Code Scanning later changes only the presentation/upload path, not the security gate.

## Acceptance evidence

Required on the pull request:

1. legacy bootstrap files absent;
2. no workflow has `contents: write` or performs `git push`;
3. Python 3.12 and 3.13 jobs execute lint, format, tests, preflight and package build;
4. dependency audit succeeds;
5. CodeQL query execution succeeds, SARIF contains zero security findings and the artifact is retained;
6. container build and smoke succeeds;
7. independent review before merge.
