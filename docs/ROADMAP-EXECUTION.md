# NLA catalog gateway — execution roadmap

## Current goal overlay — 2026-09-15

Current work is #62 (`agent/runtime-verified-output`) on #61: make the verified runtime
servable through the existing authenticated path, certify current SQL behavior and remove
unused bootstrap copies. Real package acceptance/deployment are not implied. See current
status and runtime workstream for proof-version migration and tests.

Work resumes with #60 on `agent/search-name-code-v2`: SQLite literal name/code search and
suggestions, sold-out cards and complete keyset traversal. Remaining: verified printed-code
data, clone UI, runtime activation, durable updates, staging and E2E. Suggestions are now
wired into the first-page HTTP search response; this does not enable public output.
Dependency PRs through #57 remain unmerged; live remains Jacopo's #18 gate. STATUS-CURRENT
and the #60 workstream distinguish executable evidence from pending work.

The roadmap below is historical.

Last reconciled (historical): 2026-09-01T02:59:58+02:00

## Dependency order

Platform is the current merge gate. Taxonomy, Data/Bulk, and the runtime contract may be
designed in parallel after that gate, but their pull requests must use the merged Platform
foundation. Pagination, search, filters, sync, and security depend on the canonical data and
taxonomy contracts. Runtime/staging depends on those cores; theme clone and QA follow a
verified staging service. Live cutover remains a separate owner decision.

## Workstream status

| WS | Issue | Current state | Verified source | Next executable action |
|---|---:|---|---|---|
| Platform/CI | #6 | REVIEW | Draft PR #20 carries remote candidate `73f3f78`; exact CI and CodeQL are green | Docs-inclusive gates and reviewer v4 |
| Sharding spike | #8 | BACKLOG | PR #21 closed/unmerged | Reproduce later only if limited fallback has value |
| Taxonomy | #19 | BACKLOG | PR #22 closed/unmerged | Reimplement contract after Platform |
| Data/Bulk | #5 | BLOCKED | PR #23–#25 closed/unmerged; real data root missing | Freeze code contract after Platform; real-baseline proof remains blocked |
| Pagination | #7 | BACKLOG | No accepted PR | Start after data schema/generation contract |
| Search | #9 | BACKLOG | No accepted PR | Build independent oracle before SQL |
| Filters | #10 | BACKLOG | No accepted PR | Freeze canonical parser/algebra before SQL |
| Sync | #11 | BACKLOG | No accepted PR | Define immutable inbox and reconciliation after data |
| Security | #12 | BACKLOG | No accepted PR | Implement App Proxy verifier with separate red team |
| Runtime/API | #3 | BACKLOG | Foundation only | Freeze shared response/error/dataset contract |
| Deploy | #13 | BACKLOG | Render is only a candidate | Prepare blueprint/cost/rollback before owner decision |
| Theme clone | #14 | BACKLOG | No accepted PR | Work only against unpublished clone after staging |
| QA | #15 | BACKLOG | No accepted PR | E2E on exact staging release SHA |
| Principal review | #16 | BACKLOG | No final release review | Review exact candidate SHAs independently |
| Cutover | #18 | BACKLOG | Explicit owner gate | No action before go/no-go decision |

## Wave gates

### Wave 0 — Platform

Documentation-inclusive SHAs `f211b26` and `00f0703` received `CHANGES REQUIRED` in successive
independent reviews despite green CI and CodeQL. Documentation head `82ec0e4` then received a
third `CHANGES REQUIRED`: one High remained because shell and PowerShell `$()` subexpressions
could conceal forbidden dispatch.

Remote code candidate `73f3f78` and local equivalent `db86bd3` share exact tree `a72a1c6`.
Local Ruff, format, build, audit, Docker build/smoke, static replay, 564 tests at 100%
line/branch, preflight
over 25 indexed files, and a static red team with zero High pass. Exact remote CI
`33456765768` and CodeQL `33456765740` also pass; CI covers both supported interpreters,
isolated builds, audit, and container smoke, while CodeQL reports zero security findings.

The bounded static gate retains the D-007 capability controls and adds conservative whole-class
bans for `$()`, `<()`, `>()`, and `@()`. Container smoke replaces command substitution with a
directly auditable `docker run | python` pipeline. Workflow permissions stay read-only,
workflow secrets are forbidden, and checkout credentials must not persist.
Python, Docker, and arbitrary transitively invoked scripts remain outside semantic analysis;
this is not absolute proof over indirect execution. Exit still requires completed green gates
and reviewer v4 on the same final documentation-inclusive SHA, with no unresolved
Blocker/Critical/High finding.

### Wave 1 — Canonical data contracts

Deliver separate reviewable pull requests for Taxonomy, Data/Bulk, and Runtime contract.
Every included record must be accounted for exactly once. Unknown or unsupported fields stay
nullable, provisional, or unsupported until measured on a verified baseline.

### Wave 2 — Catalog core

Implement signed context-bound keyset cursors, exact-first family search, canonical filter
state and facet algebra, immutable event inbox/reconciliation, and App Proxy verification.
Synthetic tests must cross 30,000 records before real-baseline traversal is claimed.

### Wave 3 — Runtime and staging

Add API, health/readiness, cache/version semantics, Docker runtime, observability,
backup/restore, and a validated Render candidate. A paid plan or recurring cost requires an
owner decision only after the technical package and current official pricing are ready.

### Wave 4 — Unpublished theme and QA

Integrate only with the Shopify clone. Verify URL state, scoped search/facets, accessibility,
mobile layouts, PDP/cart/checkout handoff, gateway failure modes, and browser coverage.

### Wave 5 — Live

Freeze code SHA, dataset checksum, and theme checksum; back up, dry-run, and present a
go/no-go package. Only Jacopo may authorize publication or other live cutover actions.

## Rules applied to every wave

- One issue, one `agent/*` branch, one reviewable pull request.
- No author self-approval and no review carried over from an older SHA.
- No skipped test is counted as PASS.
- No large data, generated index, credential, or signed download URL enters Git.
- Shopify remains the commercial authority and this project stays read-only.
- A written plan is not progress; status advances only with executable evidence.
