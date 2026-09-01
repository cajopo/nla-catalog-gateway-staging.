# SAL NLA — 2026-09-01T02:59:58+02:00

| WS | Issue | Branch | PR | Remote candidate | CI | Review | Stato | Blocco | Prossima azione |
|---|---:|---|---:|---|---|---|---|---|---|
| Platform/CI | #6 | `agent/platform-ci` | #20 | `73f3f78` | CI `33456765768` and CodeQL `33456765740` PASS | Local/static red team PASS; reviewer v4 pending | REVIEW | Final docs-inclusive gates incomplete | Commit evidence, final gates/review |
| Data/Bulk | #5 | — | — | — | — | Closed experiments only | BLOCKED | `NLA_DATA_ROOT` is `MISSING` | Real-baseline proof awaits external data |

## Cronologia immutabile

- Documentation head `f211b26` passed CI/CodeQL; reviewer v1 returned `CHANGES REQUIRED` for
  dynamic executable and Git-subcommand gaps.
- Documentation head `00f0703` passed CI/CodeQL; reviewer v2 returned `CHANGES REQUIRED` for
  four High capability classes.
- Code baseline `9d351e5` addressed review v2 and became documentation head
  `82ec0e472d4cfb4df131e95d87a445a7b56850b4`.
- Reviewer v3 on `82ec0e4` returned `CHANGES REQUIRED` with one High: shell and PowerShell
  `$()` subexpressions could conceal forbidden dispatch.
- Remote candidate `73f3f78819002ca21cea46be38b94d0eb874bb76` and local equivalent
  `db86bd356d4c356f6cc9674008dc9c5e5698ab79` share exact tree
  `a72a1c6016db2fcd8611ff5ae1ee770e5e394947` and contain the third remediation.
- PR #20 remains draft, unmerged, and not complete.

## Evidence sul candidato

- Local equivalent tree: Ruff check/format, package build, dependency audit, Docker
  build/smoke, 564 tests, zero skipped/xfailed, 877 statements and 472 branches at 100%, and
  repository preflight over 25 indexed files all pass.
- Static red-team replay passes with zero High on the candidate tree.
- [CI run 33456765768](https://github.com/cajopo/nla-catalog-gateway-staging./actions/runs/33456765768):
  `SUCCESS`. Python 3.12/3.13 jobs pass 564 tests, zero skipped/xfailed, 877 statements and 472
  branches at 100%, preflight over 25 files, isolated sdist/wheel builds, audit with zero known
  vulnerabilities, and container smoke with the expected JSON.
- [CodeQL run 33456765740](https://github.com/cajopo/nla-catalog-gateway-staging./actions/runs/33456765740):
  `SUCCESS`. Job `99698283209` produced one SARIF, zero security findings, and two diagnostics.
  Artifact `9781748648` is 36,987 bytes with digest
  `sha256:2957b71a838174e1586a001647eecbb29658a0b06a0db671ed3c360a0cea13bc`.
- Code-candidate remote PASS does not substitute for final documentation-inclusive gates.

## Policy bounded dopo reviewer v3

- D-007 capability controls remain in force.
- D-008 rejects the entire inline-command classes `$()`, `<()`, `>()`, and `@()`. Container
  smoke replaces command substitution with a directly auditable `docker run | python`
  pipeline. The scanner does not attempt to prove individual nested subexpressions safe.
- Workflow permissions remain read-only, workflow secret references are rejected, and checkout
  credentials require `persist-credentials: false`.
- Python, Docker, and arbitrary scripts invoked transitively remain outside semantic analysis.
  PASS is bounded defense in depth, not absolute proof over indirect execution.

## Stato del gate

- Exact remote CI and CodeQL for `73f3f78` pass.
- Committing this evidence creates another documentation-inclusive head. Fresh CI, CodeQL,
  and independent clean-checkout reviewer v4 must all pass on that same SHA before review
  threads are resolved or a technical merge is considered.
- `NLA_DATA_ROOT` remains `MISSING`; no real baseline validation or reuse is claimed.

## Decisioni richieste

Nessuna.

## Handoff

Commit this evidence without altering the verified code files, rerun CI and CodeQL on the
resulting documentation-inclusive SHA, and obtain reviewer v4 on that exact head. Keep PR #20
draft and unmerged until all gates are green and no
Blocker, Critical, or High finding remains. No Shopify, PowerTools, Render, theme, product,
price, inventory, or other live mutation occurred.
