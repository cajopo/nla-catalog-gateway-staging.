# NLA catalog gateway — current status

Last verified: 2026-09-01T00:18:16+02:00
Repository: `cajopo/nla-catalog-gateway-staging.`

This document records observed state. Git, GitHub, reproducible tests, and fresh read-only
data checks take precedence over older reports.

## Repository truth

- Current branch: `agent/platform-ci`.
- Platform code baseline carried by this documentation revision:
  `8047ba6ae314d39189f3d0ac72303cb532f05d48`.
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

The code baseline `8047ba6` is green. It is not yet eligible for merge because CI and CodeQL
must rerun on the documentation-inclusive head containing this file, and an independent
clean-checkout review must approve that same final revision. PR #20 remains draft.

| Check | Result | Evidence |
|---|---|---|
| Ruff check and format | PASS | Local frozen diff and CI Python 3.12/3.13 |
| Pytest | PASS | 409/409, zero skipped/xfailed, 790 statements and 416 branches at 100% |
| Repository preflight | PASS | Exact indexed candidate; 23 tracked files, zero findings |
| Package build | PASS | Isolated sdist and wheel on Python 3.12/3.13 CI |
| Dependency audit | PASS | Development/build environment; no known vulnerabilities |
| Container build and smoke | PASS | Non-root foundation image and expected read-only JSON |
| CodeQL/SARIF | PASS | Zero security findings under the configured gate |
| Independent final review | PENDING | Required after the final documentation commit |

Exact remote evidence:

- [CI run 33445224607](https://github.com/cajopo/nla-catalog-gateway-staging./actions/runs/33445224607), success;
- [CodeQL run 33445224609](https://github.com/cajopo/nla-catalog-gateway-staging./actions/runs/33445224609), success;
- Python 3.12 and 3.13 each completed lint, format, tests, preflight, and isolated build;
- dependency audit and container smoke completed without skipped steps;
- CodeQL job `99662692010` completed every step, including the zero-security-finding gate;
  the SARIF contains zero security findings and two diagnostics.

The documentation-inclusive head `f211b26` passed CI run `33436231899` and CodeQL run
`33436231910`, but its final independent review was `CHANGES REQUIRED`: dynamic executable
and Git-subcommand expansions could evade the static workflow check. Code baseline `8047ba6`
implements the bounded correction. Its working-diff red team passes 77/77 dangerous probes
and 33/33 safe controls. Local lint, format, test, coverage, and preflight gates also pass;
isolated builds are evidenced by the exact remote CI run.

The corrected contract is deliberately bounded. Inline workflow commands are accepted only
through a static positive allowlist; a dynamic or unknown executable, wrapper target, or Git
subcommand fails closed. The capability boundary also requires read-only permissions, rejects
workflow secret references, and requires checkout credentials to be disabled with
`persist-credentials: false`. Python, Docker and other scripts invoked transitively are not
semantically interpreted by this preflight, so a passing result is defense in depth rather
than absolute proof about every possible indirect execution path. See D-006.

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

1. Commit the corrected evidence and require CI and CodeQL to pass on that
   documentation-inclusive final SHA.
2. Run an independent clean-checkout adversarial review on the same final SHA.
3. Resolve all applicable PR #20 threads, update its body, and mark it ready for review.
4. Merge Platform only if no Blocker, Critical, or High finding remains.
5. Start Taxonomy, Data/Bulk, and Runtime-contract workstreams from merged `main`; do not
   resurrect closed branches wholesale.

No Shopify, PowerTools, Render, theme, product, price, or inventory mutation is authorized
by this status document.
