# SAL NLA — 2026-08-31T22:22:00+02:00

| WS | Issue | Branch | PR | SHA | CI | Review | Stato | Blocco | Prossima azione |
|---|---:|---|---:|---|---|---|---|---|---|
| Platform/CI | #6 | `agent/platform-ci` | #20 | `bac82b1` code baseline | CI `33435265263` and CodeQL `33435265071` PASS | Predecessor CHANGES REQUIRED; candidate red-team PASS for High findings; final exact-SHA review pending | REVIEW | Documentation-inclusive head not yet green/reviewed | Rerun gates, independent review |
| Taxonomy | #19 | — | — | — | — | Closed PR #22 audited only | BACKLOG | Platform merge gate | Start clean implementation from merged `main` |
| Data/Bulk | #5 | — | — | — | — | Closed PRs #23–#25 audited only | BLOCKED | Real `NLA_DATA_ROOT` missing | Freeze code contract after Platform; await real data for baseline proof |
| Runtime contract | #3 | — | — | — | — | Not started | BACKLOG | Platform merge gate | Freeze shared schema with Data and Taxonomy |

## Evidenze nuove

- Candidate commit: `bac82b122b96366799ee5da481490af38a25a2eb`.
- CI: <https://github.com/cajopo/nla-catalog-gateway-staging./actions/runs/33435265263>.
- CodeQL: <https://github.com/cajopo/nla-catalog-gateway-staging./actions/runs/33435265071>.
- Python 3.12/3.13: Ruff check and format PASS; 243 tests PASS; zero skipped/xfailed;
  554 statements and 278 branches at 100%; preflight PASS over 22 indexed files; isolated
  sdist/wheel build PASS.
- Development/build dependency audit: PASS, no known vulnerabilities.
- Docker build and smoke: PASS with expected read-only foundation JSON.
- Local focused security suite: 241 tests PASS; 545 script statements and 278 branches at
  100%.
- Local isolated build is unavailable only in the bundled MySQL Shell Python runtime because
  its copied environment has no SSL; `--no-isolation` passes and exact isolated CI builds pass.

## Finding aperti

- Medium, fail-closed: heredoc text containing an executable-looking `git push` is rejected.
- Medium, fail-closed: deliberately literal token-like Unicode escapes in JSON may be
  decoded conservatively and rejected.
- No known open Blocker, Critical, or High finding on the code candidate. This is not a
  substitute for the required final independent review.

## Decisioni richieste

Nessuna.

## Rischi

- PR #20 is still draft and its body/review threads are stale until the final SHA is green.
- This documentation revision changes the PR head and therefore requires fresh CI/CodeQL and
  review; evidence from the embedded code baseline `bac82b1` alone cannot authorize merge.
- Real baseline validation remains impossible while `NLA_DATA_ROOT` is missing.

## Lavoro realmente eseguito

- Repository/GitHub/data audits and closed-PR salvage review.
- Canonical status, roadmap, decisions, and PM handoff established.
- Platform preflight, workflow permissions, audit, container, build, and CodeQL gates
  implemented and exercised.
- Original and additional adversarial bypasses reproduced, fixed, regression-tested, and
  rerun on the exact remote code SHA.

## Lavoro soltanto pianificato

- Final documentation-inclusive CI/CodeQL and independent review.
- PR thread resolution, ready-for-review transition, and technical merge.
- Taxonomy, Data/Bulk, Runtime-contract implementation and all later waves.

## Handoff per PM esterno

Platform code is green on exact SHA `bac82b1`, but it is not being called merged or complete.
The remaining gate is procedural and verifiable: commit current evidence, rerun CI/CodeQL,
obtain an independent review of that same SHA, resolve PR threads, then merge only if no High
finding exists. No live or commercial system was changed.
