# NLA catalog gateway — current status

## Current runtime candidate — 2026-09-15 (#62)

- Branch `agent/runtime-verified-output`, based on `162edb4` (#61). No merge/deployment.
- The concrete authenticated service now relies on its verified generation gate, instead
  of three unconditional static denials. Default/missing dependencies still fail closed.
- Core proof schema v2 checks current SQL search/suggestions; obsolete proof reports are
  rejected. Runtime assembly no longer builds unused search/facet/public-item copies.
- Signed HTTP/ASGI and readiness tests exercise actual gates without activation overrides.
  Independent review found and resolved one sampled-query-normalization P2. 368 focused
  regressions pass; four changed modules have 100% coverage. The 30,001-product signed
  service traversal passes without activation overrides. No real-package activation claimed.
- The preceding `162edb4` is now fully CI/CodeQL green (runs `35006893228`/`35006893235`).
- Printed codes, real package rebuild/acceptance, clone, durable sync, deployment and E2E
  still remain. Source CSV location is still awaiting input. Shopify/PowerTools/MAIN untouched.

## Previous search checkpoint — 2026-09-15 (#60)

- Main is `22787055bbfa676b6700af0611fe5530186d3d5e`; dependency PRs through #57
  remain open. The search branch is `agent/search-name-code-v2`, based on #57
  (`3c24e1db93be18c1df90ea5635bc7f93ae120c48`). No merge or deployment is claimed.
- The current user goal requires literal substring matches in card name OR code,
  scoped by game, including sold-out cards, complete pagination and adaptive suggestions.
- In-progress code routes runtime search/stock-filter pagination through SQLite keyset,
  replacing per-request Python search/facet/result scans. Schema v2 derives and verifies
  normalized names, variant SKU/barcode codes and inventory facts from retained source records.
- Printed collector codes are NOT yet covered by this adapter. They require the verified
  CSV source join; do not equate SKU/barcode support with completion of the card-code goal.
- Database suggestions share the search predicate. The optional HTTP suggestion envelope
  is now implemented with explicit first-page opt-in (maximum ten groups), with signed-request
  integration tests. The theme-clone UI is still missing; static output gates remain closed.
- The configured `C:\\NLA_DATA` directory is currently absent. Inspected raw/canonical
  source directories contained no files, but the September 7 staging package was recovered.
  Fresh read-only SQL inventory found 291,787 public singles: Magic 122,530; Pokemon 71,604;
  Yu-Gi-Oh 85,991; One Piece 11,662. All have SKU, none barcode. Sample SKUs concatenate
  set/collector and internal suffixes, not necessarily printed-code punctuation. These are
  coverage observations, not package reauthentication or real schema-v2 acceptance.
- Focused verification: 66 pagination/search cases with 100% coverage of both modules,
  149 runtime cases, 78 contract cases; large traversals executed separately. Independent
  review approved after resolving one P2. Build, scoped Ruff and preflight pass. Full CI
  remains pending; see `docs/workstreams/ws-05-name-code-search-v2.md` for exact limitations.
  No Shopify, PowerTools, MAIN theme, provider or live mutation has occurred.
- Follow-up: 198 runtime/suggestion/sync-publication regressions passed, runtime API at
  100% coverage; opt-in compatibility fix approved independently. The preceding `ab0c26e`
  has fully green CI/CodeQL (2,249 tests on Python 3.12). New-head CI remains required.
  The 30,001-product HTTP traversal also passed, including sub-two-second search plus
  suggestions together on the synthetic fixture. No real-catalog latency claim.

The following September 1 snapshot is retained as history, NOT current repository state.

## Historical snapshot

Last verified: 2026-09-01T02:59:58+02:00
Repository: `cajopo/nla-catalog-gateway-staging.`

This document records observed state. Git, GitHub, reproducible tests, and fresh read-only
data checks take precedence over older reports.

## Repository truth

- Current branch: `agent/platform-ci`.
- Remote Platform code candidate carried by this documentation revision:
  `73f3f78819002ca21cea46be38b94d0eb874bb76`, tree
  `a72a1c6016db2fcd8611ff5ae1ee770e5e394947`.
- Local commit `db86bd356d4c356f6cc9674008dc9c5e5698ab79` has the same exact tree and is
  the verified local equivalent, not a second code state.
- `main`: `4e1c2a3e8e75c1d6f264e63a9b9c29e4f4bb8310`.
- Pull request [#20](https://github.com/cajopo/nla-catalog-gateway-staging./pull/20) is
  open, draft, unmerged, and based on `main`.
- The only untracked path observed is the pre-existing local `.codex/` directory. It is
  not part of the candidate revision and must not be committed.
- No tracked Shopify snapshot, SQLite database, compressed catalog artifact, build output,
  credential, or signed capability URL was found in the candidate tree.

GitHub contains 17 issues and 8 pull requests. Pull requests #21 through #25 are real,
closed without merge, and remain review material rather than completed work. Pull requests
#26 through #28 do not exist.

## Platform gate

The remote code candidate `73f3f78` passes exact CI and CodeQL. It is still not eligible for
merge: CI and CodeQL must run again on the documentation-inclusive head containing this file,
and independent reviewer v4 must approve that same final revision. PR #20 remains draft.

| Check | Result | Evidence |
|---|---|---|
| Ruff check and format | PASS | Local equivalent tree |
| Pytest | PASS | 564/564, zero skipped/xfailed, 877 statements and 472 branches at 100% |
| Repository preflight | PASS | Local exact indexed candidate; 25 tracked files, zero findings |
| Package build | PASS | Local build and remote isolated sdist/wheel builds |
| Dependency audit | PASS | Local equivalent tree |
| Container build and smoke | PASS | Local equivalent tree |
| Exact remote CI | PASS | Run `33456765768` |
| Exact remote CodeQL/SARIF | PASS | Run `33456765740`; zero security findings |
| Static red team | PASS | Zero High on the remediated tree |
| Independent final review | PENDING | Reviewer v4 on final documentation-inclusive SHA |

Exact remote evidence:

- [CI run 33456765768](https://github.com/cajopo/nla-catalog-gateway-staging./actions/runs/33456765768):
  `SUCCESS`. Python 3.12/3.13 jobs `99698284002`/`99698283943` pass 564 tests,
  877 statements and 472 branches at 100%, preflight over 25 files, and isolated sdist/wheel
  builds. Audit job `99698283934` reports zero known vulnerabilities. Container job
  `99698283800` returns the expected JSON;
- [CodeQL run 33456765740](https://github.com/cajopo/nla-catalog-gateway-staging./actions/runs/33456765740):
  `SUCCESS`. Job `99698283209` produced one SARIF with zero security findings and two
  diagnostics. Artifact `9781748648` is 36,987 bytes with digest
  `sha256:2957b71a838174e1586a001647eecbb29658a0b06a0db671ed3c360a0cea13bc`.

Local evidence on the tree shared by `db86bd3` and `73f3f78`: Ruff, format, build, audit,
Docker build/smoke, 564 tests, 100% line and branch coverage, and preflight all pass. A static
red-team rerun reports zero High. These code-baseline results do not replace final gates on
the documentation-inclusive SHA.

Immutable review chronology:

- documentation-inclusive head `f211b26` passed CI `33436231899` and CodeQL `33436231910`,
  but review v1 returned `CHANGES REQUIRED` for dynamic executable and Git-subcommand gaps;
- code baseline `8047ba6` addressed those findings, and documentation-inclusive head
  `00f07033baaa465ac920e620265bff570a104d03` (tree
  `3e4d99dc188122f9dae4ca937d5363a3ac2fc2a7`) passed CI `33446860246` and CodeQL
  `33446860231`;
- review v2 of `00f0703` still returned `CHANGES REQUIRED` with four High classes: `env`
  split-string dispatch, `Start-Process` into a shell, PowerShell function/provider overrides,
  and Git-helper environment or `GITHUB_ENV` dispatch;
- code baseline `9d351e5` applied the second remediation and became documentation-inclusive
  head `82ec0e472d4cfb4df131e95d87a445a7b56850b4`;
- reviewer v3 returned `CHANGES REQUIRED` on `82ec0e4` with one High: shell and PowerShell
  `$()` subexpressions could conceal forbidden dispatch;
- remote candidate `73f3f78` and local equivalent `db86bd3` apply the third remediation on
  exact tree `a72a1c6016db2fcd8611ff5ae1ee770e5e394947`.

The remediated contract remains bounded and conservative. D-007 controls still apply; D-008
additionally bans the whole inline-command classes `$()`, `<()`, `>()`, and `@()`. Container
smoke replaces command substitution with a direct `docker run | python` pipeline. The
capability boundary still requires read-only permissions,
rejects workflow secret references, and requires `persist-credentials: false`. Python,
Docker, and arbitrary scripts invoked transitively remain outside semantic analysis, so local
PASS is defense in depth rather than absolute proof about every indirect execution path.

Two fail-closed limitations remain documented as Medium, not bypasses:

- a heredoc containing a literal executable-looking `git push` line is rejected;
- JSON that intentionally preserves a token-like Unicode escape literally may be rejected.

The local MySQL Shell Python 3.13 runtime cannot create an isolated build environment because
its copied runtime lacks SSL. Local `--no-isolation` build passes, and the exact candidate's
isolated build passes on both supported CI interpreters; this is a host limitation, not a
release bypass.

## Data and artifact availability

`NLA_DATA_ROOT` is absent from the Process, User, and Machine environments. The local Codex
setup points to `C:\NLA_DATA`, but that directory and its expected `input`, `snapshots`,
`artifacts`, `reports`, and `tmp` children do not exist.

No baseline, JSONL, SQLite database, archive, or report can therefore be verified or reused
on this host. The correct state is `MISSING`, not `CORRUPT`. This does not block Platform/CI;
it does block future claims based on a real baseline until the external data root is
provisioned and independently verified.

## Closed-branch salvage status

- PR #21 sharding: retain deterministic packing ideas only. Confirmed verdict is `NO-GO`
  as the primary architecture; any limited SEO/fallback use remains unapproved.
- PR #22 taxonomy: retain the enum/model/report concepts, but reimplement validation for
  normalized-key collisions, `unclassified` reasons, subtype fragments, rule conflicts,
  duplicate JSON keys, and schema versioning.
- PR #23 data/Bulk: retain streaming hash and reconciliation patterns only. Empty exports,
  invalid types, duplicate JSON keys, BOMs, truncated connections, unbounded memory,
  non-atomic staging, and incomplete commercial-field preservation remain blockers.
- PR #24 and #25 are additional closed, unmerged data experiments. Neither supersedes a
  fresh implementation on a post-Platform base.

## Immediate execution order

1. Commit this evidence and require fresh CI and CodeQL on the documentation-inclusive SHA.
2. Run independent clean-checkout reviewer v4 on that same final SHA.
3. Resolve all applicable PR #20 threads, update its body, and mark it ready for review.
4. Merge Platform only if no Blocker, Critical, or High finding remains.
5. Start Taxonomy, Data/Bulk, and Runtime-contract workstreams from merged `main`; do not
   resurrect closed branches wholesale.

No Shopify, PowerTools, Render, theme, product, price, or inventory mutation is authorized
by this status document.
