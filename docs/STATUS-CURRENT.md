# NLA catalog gateway — current status

Last verified: 2026-08-31T20:08:44+02:00
Repository: `cajopo/nla-catalog-gateway-staging.`

This document records observed state. Git, GitHub, reproducible tests, and fresh read-only
data checks take precedence over older reports.

## Repository truth

- Current branch: `agent/platform-ci`.
- Current and remote head: `e5c7e92201fb8c1204680733a53f2fcf8feda4af`.
- `main`: `4e1c2a3e8e75c1d6f264e63a9b9c29e4f4bb8310`.
- Pull request [#20](https://github.com/cajopo/nla-catalog-gateway-staging./pull/20) is
  open, draft, unmerged, and based on `main`.
- The only untracked path observed is the pre-existing local `.codex/` directory. It is
  not part of the reviewed revision and must not be committed.
- No tracked Shopify snapshot, SQLite database, compressed catalog artifact, build output,
  or credential was found in the current tree.

GitHub currently contains 17 issues and 8 pull requests. Pull requests #21 through #25
are real, closed without merge, and must be treated as review material rather than completed
work. Pull requests #26 through #28 do not exist.

## Platform gate

The current PR #20 CI run is red because repository preflight rejects two scanner-result
literals in its own tests. The remaining jobs reached these results on the same head:

| Check | Result | Evidence |
|---|---|---|
| Ruff check | PASS | Python 3.12 and 3.13 CI; repeated locally on 3.13 |
| Ruff format check | PASS | Python 3.12 and 3.13 CI; repeated locally on 3.13 |
| Pytest | PASS | 51/51 on Python 3.12 and 3.13; package coverage 100% |
| Repository preflight | FAIL | Two self-matches in `tests/test_preflight_repo.py` |
| Package build | SKIPPED in CI | Blocked by the earlier preflight step |
| Dependency audit | PASS in CI | Current runtime-only audit scope |
| Container build and smoke | PASS in CI | Foundation image output validated |
| CodeQL/SARIF | PASS in CI | Zero security findings under the configured gate |
| Independent final review | MISSING | Existing review targets the red head |

PR #20 is recoverable, but it is not eligible for merge. Fresh review found the following
unresolved acceptance gaps:

- scanner self-match blocks both Python jobs;
- a whole-line test marker can hide a real credential or signed capability URL;
- generic secret parsing misses quoted punctuation and other supported forms;
- split or quoted shell tokens can evade the `git push` check;
- preflight does not enforce `persist-credentials: false` on every checkout;
- artifact checks have case and archive/multipart gaps;
- dependency audit does not cover the development/build environment;
- the 100% coverage report does not include the security-critical preflight module.

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

1. Harden PR #20 and make all local Platform tests and preflight pass.
2. Push one candidate SHA and require all CI/CodeQL jobs to pass on that exact SHA.
3. Run an independent clean-checkout adversarial review and resolve applicable threads.
4. Merge Platform only if there are no Blocker, Critical, or High findings.
5. Rebase new Taxonomy, Data/Bulk, and Runtime-contract workstreams on the merged Platform
   foundation. Do not resurrect closed branches wholesale.

No Shopify, PowerTools, Render, theme, product, price, or inventory mutation is authorized
by this status document.
