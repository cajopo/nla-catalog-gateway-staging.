# NLA catalog gateway — current status

Last verified: 2026-08-31T22:22:00+02:00
Repository: `cajopo/nla-catalog-gateway-staging.`

This document records observed state. Git, GitHub, reproducible tests, and fresh read-only
data checks take precedence over older reports.

## Repository truth

- Current branch: `agent/platform-ci`.
- Platform code baseline carried by this documentation revision:
  `bac82b122b96366799ee5da481490af38a25a2eb`.
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

The code baseline `bac82b1` is green. It is not yet eligible for merge because CI and CodeQL
must rerun on the documentation-inclusive head containing this file, and an independent
clean-checkout review must approve that same final revision.

| Check | Result | Evidence |
|---|---|---|
| Ruff check and format | PASS | Local frozen diff and CI Python 3.12/3.13 |
| Pytest | PASS | 243/243, zero skipped/xfailed, 554 statements and 278 branches at 100% |
| Repository preflight | PASS | Exact indexed candidate; 22 tracked files, zero findings |
| Package build | PASS | Isolated sdist and wheel on Python 3.12/3.13 CI |
| Dependency audit | PASS | Development/build environment; no known vulnerabilities |
| Container build and smoke | PASS | Non-root foundation image and expected read-only JSON |
| CodeQL/SARIF | PASS | Zero security findings under the configured gate |
| Independent final review | PENDING | Required after the final documentation commit |

Exact remote evidence:

- [CI run 33435265263](https://github.com/cajopo/nla-catalog-gateway-staging./actions/runs/33435265263), success;
- [CodeQL run 33435265071](https://github.com/cajopo/nla-catalog-gateway-staging./actions/runs/33435265071), success;
- Python 3.12 and 3.13 each completed lint, format, tests, preflight, and isolated build;
- dependency audit and container smoke completed without skipped steps.

The earlier independent review of `621460d` was `CHANGES REQUIRED`. Commit `bac82b1`
closes its High findings for shell wrappers, JSON/percent-escaped capability URLs,
placeholder suppression, small Shopify snapshots, strict checkout booleans, and multipart
RAR artifacts. Additional working-diff red-team probes found and then verified fixes for
`env`/`command` options, Bash substitutions, `cmd` caret/`call`, `eval`, PowerShell paths and
literal concatenation, Unicode-escaped tokens, bounded decoding, and numeric REST snapshots.

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

1. Require CI and CodeQL to pass on the documentation-inclusive final SHA.
2. Run an independent clean-checkout adversarial review on the same final SHA.
3. Resolve all applicable PR #20 threads, update its body, and mark it ready for review.
4. Merge Platform only if no Blocker, Critical, or High finding remains.
5. Start Taxonomy, Data/Bulk, and Runtime-contract workstreams from merged `main`; do not
   resurrect closed branches wholesale.

No Shopify, PowerTools, Render, theme, product, price, or inventory mutation is authorized
by this status document.
