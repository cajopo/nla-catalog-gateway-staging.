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

## Remediated candidate evidence — 2026-09-01

Code baseline: `9d351e5e78537afe3133bf20bb2b18d4b96abc9e` (tree
`c59a59540c4301d05587fb83730e9c7ce1e30c38`).

- CI run `33453261603`: success on Python 3.12 and 3.13; 537 tests, zero
  skipped/xfailed, 876 statements and 472 branches at 100%, preflight over 24 indexed files,
  isolated sdist/wheel build, development dependency audit, and container smoke.
- CodeQL run `33453261610`: success; job `99687655049` completed. One SARIF has zero security
  findings and two diagnostics; artifact `9780557282` has digest
  `b4b6ff4a50dd8427a1b9a15427871b0a365d2f7454703cb9a705b70fd1899da5`.
- Green documentation-inclusive predecessors `f211b26` and `00f0703` both received independent
  `CHANGES REQUIRED` verdicts. Review v2 found four High classes covering `env` split dispatch,
  `Start-Process`, PowerShell provider/function overrides, and Git-helper environment or
  `GITHUB_ENV` dispatch.
- Local and independent stable-freeze QA pass Ruff, format, build, 537 tests, zero
  skipped/xfailed, 876 statements/472 branches at 100%, preflight over 24 files, `pip check`,
  and `pip-audit` with no known vulnerabilities; the local package itself was skipped by audit.
- Inline commands retain a static positive allowlist plus conservative whole-class bans for
  the reviewed dispatch/mutator capabilities, risky Git-helper, PAGER, PATH, and PATHEXT
  environment, `GITHUB_ENV`/`GITHUB_PATH`, path-qualified direct executables, and Bash indirect
  expansion.
- The capability boundary enforces read-only permissions, rejects workflow secret references,
  and requires `persist-credentials: false`.
- Python, Docker, and arbitrary scripts invoked transitively are not semantically interpreted;
  preflight PASS is therefore defense in depth, not absolute proof over indirect execution.
- Final independent clean-checkout review remains required on the documentation-inclusive SHA
  before merge.
- Known fail-closed limitations: heredoc text containing an executable-looking `git push`
  line and deliberately literal token-like Unicode escapes in JSON may be rejected.

`NLA_DATA_ROOT` remains `MISSING`; no real catalog baseline is claimed. PR #20 remains draft.
No Shopify, PowerTools, theme, Render, or catalog data mutation occurred.
