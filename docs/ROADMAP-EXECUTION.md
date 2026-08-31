# NLA catalog gateway — execution roadmap

Last reconciled: 2026-08-31T22:22:00+02:00

## Dependency order

Platform is the current merge gate. Taxonomy, Data/Bulk, and the runtime contract may be
designed in parallel after that gate, but their pull requests must use the merged Platform
foundation. Pagination, search, filters, sync, and security depend on the canonical data and
taxonomy contracts. Runtime/staging depends on those cores; theme clone and QA follow a
verified staging service. Live cutover remains a separate owner decision.

## Workstream status

| WS | Issue | Current state | Verified source | Next executable action |
|---|---:|---|---|---|
| Platform/CI | #6 | REVIEW | PR #20 carries code baseline `bac82b1`; its CI and CodeQL are green | Rerun gates on docs-inclusive head, independent final review |
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

Code SHA `bac82b1` passes Python 3.12/3.13 lint, format, 243 tests at 100% line/branch,
preflight, isolated build, development dependency audit, container smoke, and CodeQL/SARIF.
Exit still requires those checks on the final documentation-inclusive SHA, a clean-checkout
review of that exact SHA, and no unresolved Blocker/Critical/High finding.

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
