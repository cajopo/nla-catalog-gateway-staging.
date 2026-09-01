# SAL NLA — 2026-09-01T00:18:16+02:00

> **SUPERSEDED / CORRECTION — 2026-09-01:** this historical candidate became
> documentation-inclusive head `00f0703`. Its CI and CodeQL passed, but independent review v2
> returned `CHANGES REQUIRED` with four High workflow-capability classes. Use
> `SAL-2026-09-01-platform-remediated-candidate.md` for current evidence.

| WS | Issue | Branch | PR | Code baseline | CI | Review | Stato | Blocco | Prossima azione |
|---|---:|---|---:|---|---|---|---|---|---|
| Platform/CI | #6 | `agent/platform-ci` | #20 | `8047ba6` | CI `33445224607` and CodeQL `33445224609` PASS | Working-diff red team PASS; final clean-checkout exact-SHA review pending | REVIEW | Documentation-inclusive SHA not yet green and independently approved | Commit evidence, rerun gates, independent review |
| Data/Bulk | #5 | — | — | — | — | Closed experiments only | BLOCKED | `NLA_DATA_ROOT` is `MISSING` | Freeze contract after Platform; real-baseline proof awaits external data |

## Cronologia verificata

- Documentation-inclusive head `f211b261cbf4237149b0f45a2d3a79d3476cf4ba` passed CI
  `33436231899` and CodeQL `33436231910`.
- Its final independent review nevertheless returned `CHANGES REQUIRED`: dynamic executable
  and Git-subcommand expansions were not rejected reliably. Green automation did not override
  that High finding.
- Code baseline `8047ba6ae314d39189f3d0ac72303cb532f05d48` contains the bounded fix.
- PR #20 remains draft, unmerged, and not complete. The required independent review must be
  performed again on the future documentation-inclusive final SHA.

## Evidence sul code baseline

- Local verification: Ruff check/format, 409 tests with zero skipped/xfailed, 790 statements
  and 416 branches at 100%, and repository preflight over 23 indexed files all pass. The
  isolated-build proof comes from the exact remote CI run below.
- [CI run 33445224607](https://github.com/cajopo/nla-catalog-gateway-staging./actions/runs/33445224607):
  success on Python 3.12 and 3.13; Ruff check/format; 409 tests passed; zero skipped/xfailed;
  790 statements and 416 branches at 100%; preflight over 23 indexed files; isolated
  sdist/wheel builds; development/build dependency audit; Docker build and smoke.
- [CodeQL run 33445224609](https://github.com/cajopo/nla-catalog-gateway-staging./actions/runs/33445224609):
  completed with conclusion `success`. Job `99662692010` and every step succeeded, including
  the zero-security-finding gate. One SARIF contains zero security findings and two diagnostic
  results. Artifact `codeql-sarif` has ID `9777814278` and SHA-256
  `d45a4a2802546e47ab19b923b75487d2a46f9eea0e9a4c5ea5bb1ae808ff1c9b`.
- Working-diff adversarial matrix: 77/77 dangerous probes rejected and 33/33 safe controls
  accepted.

## Contratto bounded e capability boundary

- Inline workflow commands are accepted through a static positive allowlist. A dynamic or
  unknown executable, dispatcher target, or Git subcommand fails closed.
- Workflow permissions must remain read-only, workflow secret references are rejected, and
  checkout credentials must be disabled with `persist-credentials: false`.
- The preflight does not semantically interpret Python, Docker, or arbitrary scripts invoked
  transitively. Its PASS is defense in depth over the declared static boundary, not absolute
  proof that no indirect program could mutate repository state.
- Two existing conservative Medium limitations remain: executable-looking `git push` text in
  a heredoc can be rejected, and a deliberately literal token-like Unicode escape in JSON can
  be decoded conservatively and rejected. Both fail closed.

## Stato del gate

- No post-fix High was observed by the working-diff author/red-team evidence. This does not
  substitute for independent approval of the final exact SHA.
- Documentation changes will create a new PR head. CI, CodeQL, and a clean-checkout
  independent review must all pass on that same SHA before review threads are resolved or a
  technical merge is considered.
- `NLA_DATA_ROOT` is absent and the expected external directory is unavailable. State:
  `MISSING`, not `CORRUPT`; no real baseline validation or reuse is claimed.

## Decisioni richieste

Nessuna.

## Handoff

Commit the evidence without altering the code baseline, rerun CI and CodeQL, then obtain an
independent clean-checkout review of that exact head. Keep PR #20 draft and unmerged until the
same revision has green automated gates and no unresolved Blocker, Critical, or High finding.
No Shopify, PowerTools, Render, theme, product, price, inventory, or other live mutation
occurred.
