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
| `.github/workflows/codeql.yml` | Rewritten now | CodeQL runs queries, distinguishes security results from extractor diagnostics, gates on zero security findings and stores the SARIF as an artifact. |
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

The current repository is private and user-owned; GitHub accepts CodeQL extraction and query execution but rejects Code Scanning upload because that repository feature is not enabled. The workflow therefore uses the action's documented `upload: never` mode, parses the generated SARIF and uploads it as a normal short-lived Actions artifact.

SARIF also contains extractor diagnostics and metric results. Those are reported separately; only rules explicitly tagged as security findings fail the security gate. This avoids both false green builds and the earlier false failure caused by counting a Python extractor diagnostic as a vulnerability. Enabling GitHub Code Scanning later changes only the presentation/upload path, not the query execution or gate.

## Acceptance evidence

Required on the pull request:

1. legacy bootstrap files absent;
2. no workflow has `contents: write` or performs `git push`;
3. Python 3.12 and 3.13 jobs execute lint, format, tests, preflight and package build;
4. dependency audit succeeds;
5. CodeQL query execution succeeds, SARIF contains zero security findings and the artifact is retained;
6. container build and smoke succeeds;
7. independent review before merge.

## Corrected candidate evidence — 2026-09-01

Code baseline: `8047ba6ae314d39189f3d0ac72303cb532f05d48`.

- CI run `33445224607`: success on Python 3.12 and 3.13; 409 tests, zero
  skipped/xfailed, 790 statements and 416 branches at 100%, preflight over 23 indexed files,
  isolated sdist/wheel build, development dependency audit, and container smoke.
- CodeQL run `33445224609`: success; job `99662692010`, the zero-security-finding gate, and
  SARIF artifact step all completed. The SARIF contains zero security findings and two
  diagnostic results.
- Documentation-inclusive predecessor `f211b26` had green CI/CodeQL but final independent
  review returned `CHANGES REQUIRED` for dynamic executable and Git-subcommand expansions.
  The corrected working diff passes 77/77 dangerous probes and 33/33 safe controls.
- Local lint, format, full test, coverage, and preflight gates pass. Isolated builds are
  evidenced by the exact remote CI run.
- Inline commands now follow a bounded static positive allowlist; dynamic or unknown
  executable, dispatcher, and Git-subcommand positions fail closed. The capability boundary
  also enforces read-only permissions, rejects workflow secret references, and requires
  `persist-credentials: false`.
- Python, Docker, and arbitrary scripts invoked transitively are not semantically interpreted;
  preflight PASS is therefore defense in depth, not absolute proof over indirect execution.
- Final independent clean-checkout review remains required on the documentation-inclusive SHA
  before merge.
- Known fail-closed limitations: heredoc text containing an executable-looking `git push`
  line and deliberately literal token-like Unicode escapes in JSON may be rejected.

`NLA_DATA_ROOT` remains `MISSING`; no real catalog baseline is claimed. PR #20 remains draft.
No Shopify, PowerTools, theme, Render, or catalog data mutation occurred.
