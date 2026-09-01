# SAL NLA — 2026-08-31T20:08:44+02:00

| WS | Issue | Branch | PR | SHA | CI | Review | Stato | Blocco | Prossima azione |
|---|---:|---|---:|---|---|---|---|---|---|
| Platform | #6 | `agent/platform-ci` | #20 | `e5c7e92` | FAIL | Findings open | IN_PROGRESS | Preflight and High findings | Author hardening |
| Sharding | #8 | closed branch | #21 | `b5b9fa3` | historical red | 4 threads open | BACKLOG | Not primary architecture | Salvage concepts only |
| Taxonomy | #19 | closed branch | #22 | `241e580` | historical red | 6 threads open | BACKLOG | Platform/data contract | Reimplement after Platform |
| Data/Bulk | #5 | closed branches | #23–#25 | `37c393d` / later experiments | historical red | Findings open | BLOCKED | Data root missing | Contract first; data later |

## Evidenze nuove

- Git fetch completed; local and remote Platform heads match.
- GitHub connector verified 17 issues, 8 real pull requests, current PR metadata, review
  threads, and Actions results.
- Main-thread local gate: Ruff check PASS, Ruff format PASS, 51 tests PASS, coverage 100%,
  repository preflight FAIL with two self-matches.
- CI run `33400328891`: dependency audit and container smoke PASS; Python 3.12/3.13 reach
  and fail preflight after successful lint, format, and tests; package build skipped.
- CodeQL run `33400328929`: PASS.
- Independent clean-archive audit reproduced Platform findings and built wheel/sdist.
- Read-only data inventory found no configured or fallback data root on disk.

## Finding aperti

- Blocker: scanner self-match keeps CI red.
- High: whole-line marker can conceal a real credential or capability URL.
- High: common quoted secret forms are not detected.
- Medium: shell token splitting, checkout persistence, artifact variants, audit scope, and
  preflight coverage need hardening.
- Data: no real baseline artifact exists on this host.

## Decisioni richieste

Nessuna. The current work is ordinary technical remediation within the approved architecture.

## Rischi

- Merging PR #20 now would preserve a red gate and known scanner bypasses.
- Copying closed data/taxonomy branches wholesale would reintroduce unresolved correctness
  defects.
- Claims about the historical catalog cannot be refreshed until external artifacts exist.

## Lavoro realmente eseguito

Four independent read-only audits; Git/GitHub reconciliation; local quality reproduction;
CI/review inspection; canonical status, roadmap, decisions, and PM handoff creation.

## Lavoro soltanto pianificato

Platform code fixes, candidate commit/push, green CI, independent final review, merge, and
post-merge Taxonomy/Data/Runtime workstreams.

## Handoff per PM esterno

Use the copyable block in `docs/PM-HANDOFF.md`.
