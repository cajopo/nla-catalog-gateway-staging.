# NLA catalog gateway — current status

Last verified: 2026-09-01T02:07:51+02:00
Repository: `cajopo/nla-catalog-gateway-staging.`

This document records observed state. Git, GitHub, reproducible tests, and fresh read-only
data checks take precedence over older reports.

## Repository truth

- Current branch: `agent/platform-ci`.
- Platform code baseline carried by this documentation revision:
  `9d351e5e78537afe3133bf20bb2b18d4b96abc9e` (tree
  `c59a59540c4301d05587fb83730e9c7ce1e30c38`).
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

The code baseline `9d351e5` is green. It is not yet eligible for merge because CI and CodeQL
must rerun on the documentation-inclusive head containing this file, and an independent
clean-checkout review must approve that same final revision. PR #20 remains draft.

| Check | Result | Evidence |
|---|---|---|
| Ruff check and format | PASS | Local frozen diff and CI Python 3.12/3.13 |
| Pytest | PASS | 537/537, zero skipped/xfailed, 876 statements and 472 branches at 100% |
| Repository preflight | PASS | Exact indexed candidate; 24 tracked files, zero findings |
| Package build | PASS | Isolated sdist and wheel on Python 3.12/3.13 CI |
| Dependency audit | PASS | No known vulnerabilities; local package itself skipped by audit |
| Container build and smoke | PASS | Non-root foundation image and expected read-only JSON |
| CodeQL/SARIF | PASS | Zero security findings under the configured gate |
| Independent final review | PENDING | Required after the final documentation commit |

Exact remote evidence:

- [CI run 33453261603](https://github.com/cajopo/nla-catalog-gateway-staging./actions/runs/33453261603), success;
- [CodeQL run 33453261610](https://github.com/cajopo/nla-catalog-gateway-staging./actions/runs/33453261610), success;
- Python 3.12 and 3.13 each completed lint, format, tests, preflight, and isolated build;
- dependency audit and container smoke completed without skipped steps;
- CodeQL job `99687655049` completed every step; one SARIF contains zero security findings
  and two diagnostics. Artifact `9780557282` has digest
  `b4b6ff4a50dd8427a1b9a15427871b0a365d2f7454703cb9a705b70fd1899da5`.

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
- code baseline `9d351e5` applies the second remediation. Local and independent stable-freeze
  QA pass Ruff, format, build, 537 tests, 100% coverage, preflight, `pip check`, and
  `pip-audit` with no known vulnerabilities; the local package itself was skipped by audit.
  This QA is not the still-required final exact-SHA clean-checkout approval.

The remediated contract is deliberately bounded and conservative. Inline workflow commands
still require a static positive allowlist; whole classes now fail closed for `env` split
dispatch, `Start-Process`, PowerShell provider/function/variable mutators, risky Git-helper,
PAGER, PATH, and PATHEXT environment controls, `GITHUB_ENV`/`GITHUB_PATH` command files,
path-qualified direct executables, and Bash indirect expansion. The capability boundary also
requires read-only permissions, rejects workflow secret references, and requires checkout
credentials to be disabled with `persist-credentials: false`. Python, Docker, and arbitrary
scripts invoked transitively remain outside semantic analysis, so PASS is defense in depth
rather than absolute proof about every indirect execution path. See D-007.

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

1. Commit the remediated evidence and require CI and CodeQL to pass on that
   documentation-inclusive final SHA.
2. Run an independent clean-checkout adversarial review on the same final SHA.
3. Resolve all applicable PR #20 threads, update its body, and mark it ready for review.
4. Merge Platform only if no Blocker, Critical, or High finding remains.
5. Start Taxonomy, Data/Bulk, and Runtime-contract workstreams from merged `main`; do not
   resurrect closed branches wholesale.

No Shopify, PowerTools, Render, theme, product, price, or inventory mutation is authorized
by this status document.
