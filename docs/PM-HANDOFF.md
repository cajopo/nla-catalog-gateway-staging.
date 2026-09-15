# PM handoff — Next Level Arena catalog gateway

## Current handoff — 2026-09-15

Issue #60 is implementing the actual name-or-code substring requirement on
`agent/search-name-code-v2`, based on unmerged #57. Runtime result pagination now uses
SQLite for search and stock filters as well as plain browse; literal matching does not
discard substring hits when an exact match exists. Sold-out products remain included.
Suggestions are now wired to the optional HTTP response field on the first search page,
using explicit `includeSuggestions: true` opt-in and the same leased database/filter
scope; 40 new tests pass. Existing clients retain their response shape. Clone UI and public
activation are still pending. No extra endpoint or service was introduced.
SKU/barcode data are available in the record contract; printed collector codes still
need a verified source join. No real dataset acceptance, deployment, clone integration
or full sync completion is claimed. Independent review approved after one P2 fix. Final
focused checks: 66 pagination/search cases at 100% module coverage, 149 runtime cases and
78 contract cases. The preceding `ab0c26e` now has fully green CI/CodeQL. The suggestion
follow-up has 198 passing regressions and 100% runtime API coverage; final new-head CI
remains required. The separate 30,001-product HTTP traversal passed, including search
plus suggestions under two seconds on synthetic data. No Shopify writes.

The historical staging SQLite package was recovered. Fresh read-only coverage shows
291,787 public singles all with SKU and none with barcode. SKU format is not equivalent
to the printed code; source CSVs were requested. Initial SQL suite: 20 passed, including
30,001 code-only sold-out results without gaps. Runtime-contract suite: 78 passed.

The older block below is historical and must not be copied as current status.

Updated 2026-09-01T02:59:58+02:00.

Copyable update:

> Platform PR #20 remains draft. Reviewer v3 returned `CHANGES REQUIRED` on `82ec0e4` for one
> High: shell/PowerShell `$()` subexpressions. Remote candidate `73f3f78` and local equivalent
> `db86bd3` share one tree; local Ruff/build/audit/Docker smoke and static replay, 564 tests at
> 100% line/branch,
> preflight over 25 files, and static red team all pass. Exact CI `33456765768` and CodeQL
> `33456765740` now pass, with zero CodeQL security findings. D-008 bans `$()`, `<()`, `>()`,
> and `@()` conservatively, and rewrites container smoke as direct `docker run | python`. Final
> docs-inclusive gates and reviewer
> v4 remain required before merge. `NLA_DATA_ROOT` is missing; no Shopify or live action occurred.
