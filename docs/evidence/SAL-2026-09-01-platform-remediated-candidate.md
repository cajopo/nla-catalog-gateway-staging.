# SAL NLA — 2026-09-01T02:07:51+02:00

| WS | Issue | Branch | PR | Code baseline | CI | Review | Stato | Blocco | Prossima azione |
|---|---:|---|---:|---|---|---|---|---|---|
| Platform/CI | #6 | `agent/platform-ci` | #20 | `9d351e5` | CI `33453261603` and CodeQL `33453261610` PASS | Stable-freeze QA PASS; final clean exact-SHA review pending | REVIEW | Documentation-inclusive SHA not yet green and independently approved | Commit evidence, rerun gates, independent review |
| Data/Bulk | #5 | — | — | — | — | Closed experiments only | BLOCKED | `NLA_DATA_ROOT` is `MISSING` | Freeze contract after Platform; real-baseline proof awaits external data |

## Cronologia immutabile

- Documentation-inclusive head `f211b261cbf4237149b0f45a2d3a79d3476cf4ba` passed CI
  `33436231899` and CodeQL `33436231910`; independent review v1 returned
  `CHANGES REQUIRED` for dynamic executable and Git-subcommand gaps.
- Code baseline `8047ba6ae314d39189f3d0ac72303cb532f05d48` addressed that review.
- Documentation-inclusive head `00f07033baaa465ac920e620265bff570a104d03` (tree
  `3e4d99dc188122f9dae4ca937d5363a3ac2fc2a7`) passed CI `33446860246` and CodeQL
  `33446860231`; independent review v2 still returned `CHANGES REQUIRED`.
- Review v2 identified four High classes: `env` split-string dispatch; `Start-Process` into a
  shell; PowerShell function/provider overrides; and Git-helper environment or `GITHUB_ENV`
  dispatch. Green automation did not override those findings.
- Remediated code baseline `9d351e5e78537afe3133bf20bb2b18d4b96abc9e` (tree
  `c59a59540c4301d05587fb83730e9c7ce1e30c38`) contains the second correction.
- PR #20 remains draft, unmerged, and not complete.

## Evidence sul code baseline

- Local and independent stable-freeze QA: Ruff check/format, package build, 537 tests passed,
  zero skipped/xfailed, 876 statements and 472 branches at 100%, repository preflight over 24
  indexed files, and `pip check` all pass. `pip-audit` reports no known vulnerabilities; the
  local package itself was skipped by audit.
- [CI run 33453261603](https://github.com/cajopo/nla-catalog-gateway-staging./actions/runs/33453261603):
  `success`; Python 3.12 and 3.13 each pass 537 tests, zero skipped/xfailed, 876 statements and
  472 branches at 100%, preflight over 24 files, and isolated sdist/wheel builds. Dependency
  audit and container build/smoke are green.
- [CodeQL run 33453261610](https://github.com/cajopo/nla-catalog-gateway-staging./actions/runs/33453261610):
  `success`; job `99687655049` completed. One SARIF contains zero security findings and two
  diagnostics. Artifact `9780557282` has digest
  `b4b6ff4a50dd8427a1b9a15427871b0a365d2f7454703cb9a705b70fd1899da5`.

## Policy bounded dopo remediation

- Inline commands retain a static positive allowlist. The following whole classes fail closed:
  `env` split-string dispatch; `Start-Process`; PowerShell provider, function, and variable
  mutators; risky Git-helper, PAGER, PATH, and PATHEXT environment controls;
  `GITHUB_ENV`/`GITHUB_PATH` command files; path-qualified direct executables; and Bash
  indirect expansion.
- Workflow permissions must remain read-only, workflow secret references are rejected, and
  checkout credentials must be disabled with `persist-credentials: false`.
- Python, Docker, and arbitrary scripts invoked transitively remain outside semantic analysis.
  Preflight PASS is bounded defense in depth, not absolute proof over indirect execution.
- Existing conservative Medium limitations remain: executable-looking `git push` text in a
  heredoc and deliberately literal token-like Unicode escapes in JSON can be rejected. Both
  fail closed.

## Stato del gate

- Stable-freeze QA and exact code-baseline automation are green, but they do not substitute
  for final independent approval of the future documentation-inclusive exact SHA.
- Committing this evidence creates a new PR head. CI, CodeQL, and a new clean-checkout
  independent review must all pass on that same SHA before review threads are resolved or a
  technical merge is considered.
- `NLA_DATA_ROOT` is absent. State: `MISSING`, not `CORRUPT`; no real baseline validation or
  reuse is claimed.

## Decisioni richieste

Nessuna.

## Handoff

Commit the evidence without altering code baseline `9d351e5`, rerun CI and CodeQL, then obtain
a new independent clean-checkout review of that exact head. Keep PR #20 draft and unmerged
until the same revision has green automated gates and no unresolved Blocker, Critical, or High
finding. No Shopify, PowerTools, Render, theme, product, price, inventory, or other live
mutation occurred.
