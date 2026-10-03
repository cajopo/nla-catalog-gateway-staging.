# Release-readiness checkpoint — 29 September 2026

Workstream: #16 final review, roadmap #3; eventual owner cutover #18.
Owner cutover approved and executed below; GitHub source delivery remains deferred.

## Cutover executed — 29 September 2026,17:20UTC

Owner's latest «consento» answers the exact candidate/password/rollback proposal.
Official publishing documentation consulted before acting:
https://help.shopify.com/en/manual/online-store/themes/managing-themes/publishing-themes.
The Shopify skill documentation-search script returned fetch failed; official
public docs and live schema discovery were used instead, with successful CLI and
connector GraphQL validation. No theme-publishing connector mutation was attempted;
the authorized action used Shopify Admin's documented Publish confirmation.

Preflight17:19:09Z: MAIN175194898700/candidate175195881740 and all310/314 checksum
entries match backups, no pagination remainder, password enabled. HTTPS gateway
/readyz200 at17:19:16Z. Admin dialog explicitly named both themes and confirmed
the store would remain password protected. One final Publish action completed.

Postflight17:20:17Z: candidate175195881740 MAIN; previous175194898700 UNPUBLISHED;
all complete file checksums unchanged, passwordProtection.enabled=true. No files
rewritten, products changed, PowerTools touched, source captured or VPS redeployed.
Private receipts: cutover-preflight-result.json and cutover-result.json alongside
the backups below. Admin UI independently shows the new Active theme and old draft.

Targeted ordinary storefront evidence, after Exit preview removed the preview bar:

- Magic/sealed/booster:4 products, unchanged actual commercial prices.
- Header light then lightning:10 distinct canonical-name suggestions, dynamically
  changed; Lightning Bolt group69, not confused with the74 broad search matches.
- Magic/Lightning Bolt:24 first-page results, images/SOLD OUT and next-page button.
  Prior74-result exhaustive pagination proof reused, not repeated here.
- Same query with Pokémon selected: no matching products, no Magic leakage.
- Enter on the exact SLDXL-1822 product link opens its Shopify product page:
  image present, red SOLD OUT (computed rgb224,0,0), no zero/N-D invented price;
  purchase/accelerated-payment controls absent, not an observed disabled button.
- AX-index click aimed at Bolt reached adjacent Blow; not counted as successful
  pointer evidence. Semantic input/Enter and product-link Enter passed. No claim
  of a new complete mouse/cart/mobile matrix; earlier unchanged-code proofs reused.

No functional regression found requiring rollback. Prior theme and verified export
remain available; do not claim a live rollback rehearsal. Operational acceptance
and authorized cutover are COMPLETE. Exact-head GitHub CI/source reconciliation
remain explicitly DEFERRED BY OWNER. Public opening/password removal not included.

## Pre-cutover preparation (historical)

## Owner-directed operational release — current 29 September

The owner explicitly deferred GitHub delivery («anche github sticazzi») after
authenticated billing confirmed2000/2000 Actions minutes used, reset in2days.
No spending limit, subscription, remote branch, CI run or publication changed.
GitHub remains non-green/deferred; it is no longer the operational waiting gate.
This release target is the already deployed/tested component combination, not an
installation of the unmerged integration preview. Final owner cutover consent is
still REQUIRED; preserve storefront password protection and PowerTools unchanged.

Fresh read-only Shopify evidence, using schema discovery and validated queries:

- Current MAIN:175194898700, `NLA — sviluppo 2026`,310files.
- Candidate:175195881740, `NLA — catalogo completo test`,UNPUBLISHED,314files.
- Complete checksum inventories,19 differing/new files, no MAIN-only file.
- Search, en/it locale, home and product-card checksums match installed receipts.
- `onlineStore.passwordProtection.enabled=true` confirmed directly by Shopify.
- Gateway HTTPS `/readyz`200. Anonymous storefront HTTP403 was inconclusive, not
  treated as evidence of password protection; the authoritative API read resolves it.

Full theme body exports completed,7pages per theme, no URL-only bodies. Private
directory: `C:/Users/umbri/AppData/Local/Temp/nla-cutover-readiness-20260929`.
No theme bodies or generated backup artifacts are committed to Git.

| Artifact | SHA256 |
| --- | --- |
| theme-inventory.json | f3eaeffe5b4792e3970c9a031587f64af9d293b2386d44c08a8b80a205a15012 |
| theme-175194898700-backup.json | 4c701fa92c3187b6a791cc339db3b675575531bf23d32cab1580b5083302a3cd |
| theme-175195881740-backup.json | ddb0f7315f3715c80dcebc08360c87697d85a25d1a73cc174979d6c4bcb5d591 |

Reproducible local check: `node <private-directory>/verify-backup.cjs`, exit0.
All624 files accounted for and match Shopify MD5: MAIN235 raw text/2binary,
54 generated-header normalization,17 compact JSON,2 compact JSON with escaped
slashes; clone244 raw/2binary,50 header-normalized,16compact,2escaped-slash JSON.
Original returned bodies remain preserved unchanged in the exports. The first
naive raw-body check exposed JSON presentation differences; no remote content was
changed to force a match. Shopify documents generated JSON comment headers at
https://shopify.dev/docs/storefronts/themes/architecture#json-with-comments.

Independent deferred_export_review found no new functional blocker in the narrow
release inventory/evidence review and approved asking for consent, not publishing.
The requested prerequisites (verified exports, rollback target, password state)
are now documented. Prior implementation reviews remain distinct from this check.

### Minimal execution and rollback, only after owner approval

1. Freshly recheck candidate/current theme identities and gateway readiness; abort
   on unexpected changes. No new source capture or service rollout is needed.
2. Publish ONLY candidate175195881740. Keep175194898700 in the theme library;
   do not delete it, rewrite its files, remove the store password or edit PowerTools.
3. Confirm the new MAIN identity and unchanged password setting; verify the ordinary
   non-preview route, game separation, suggestions, SOLD OUT and a product link.
   This targeted post-publication check is not another full catalog acquisition.
4. If publication breaks search, game isolation, purchase behavior or availability,
   republish175194898700 and verify recovery. No product/commercial-data rollback.
   Preparation verified the complete old theme and its export without mutating it;
   a live republish/restore has NOT been executed or falsely claimed as tested.
5. Record actual times/outcomes. Do not mark operational completion before these
   results; GitHub reconciliation remains a separately deferred delivery item.

Decision requested: authorize this exact theme publication while keeping password
protection and the previous theme for rollback. Consent has not yet been received.

## Operational gates closed

One compact read-only native observation at08:28UTC established success of
market `market-20260929t020020z-20b6fdab` and ordinary refresh
`20260929t043209z-c77e0ce5`. The market source is complete:2433 expansions,
256432 blueprints, no deferred exports.12 selected/draft_verified/published,
no remaining or uncertain attempts; live ledger4082 draft_verified/publications.
No pending markers; both services terminal success, timers active/waiting.

Both market-triggered and ordinary refresh receipts prove real warm activation
using operator881b9ca, not merely an old successful job. Latest dataset manifest:
`4cb95d1225d04e497fdf352ca864449a88930bfc34f35a92d83d205ffe10f08f`.
295877 products,295873 published,297948 variants. Runtime/pointer/receipt identity
matches; public HTTPS `/readyz`200. No manual acquisition or recovery was started.

Exact-ID read-only SQLite check: all12 new product GIDs from the publication
receipt exist in this active generation; public=1, family=single, no positive
inventory. Real clone browser sample `/products/nla-cm-913645` is reachable from
Magic/Crystal Ball search and shows the correct image, red SOLD OUT, no zero/N-D
price and a disabled purchase button. Only this new sample was rendered; do not
claim12 visual checks. Existing cross-game/cart/mobile evidence was not repeated.

Private receipts: `/opt/nla-staging/importer-state/market-20260929t020020z-20b6fdab/`
and `/var/lib/nla-catalog-refresh/20260929t043209z-c77e0ce5/completed.json`.
Heartbeat `verifica-ciclo-nuove-uscite-nla` deleted after terminal verification;
the native market02/14UTC and refresh03/15UTC timers remain unchanged.

## Reproducible local integration preview

Inputs retained as separate branches, no branch/ref merge or push:

| Component | Exact input commit |
| --- | --- |
| Runtime/family search | `8da5d4c7b58afc1f9bea91e6fc81b70e1aa71b9a` |
| Warm operator | `7f421cf3da60fc9a1fa5c145f506e615a5d14f05` |
| Importer, already ancestor of operator | `317126b7823032b4531e876ff0a4875b33bb98eb` |
| Unpublished clone theme | `09821ca37bbffbcc3beef02651f59f7f106084ec` |

Private export: `C:/Users/umbri/AppData/Local/Temp/nla-release-preview-20260929`.
Source in `source/`; isolated Git index `preview.index`; `release-preview.zip`
contains source only, not the built wheel, cache or data. Resolved Git tree:
`cb27a5de39073e9b6471920bb00f15abea60f576`.
Archive SHA256:
`5c5299fa1ac4cf5782060582ebc4c424ef876c09ce2ffcb4287a90283fc2162f`.

Preparation used documented Git merge-tree without updating refs or the real
index: runtime+operator produced conflicted tree89ba9115; add theme using verified
common base5183191 produced64d063d7. Resolve three conflict files by reusing the
independently reviewed28September integration: warm activation including the
separate acquisition/producer pin checks, warm code-only replacement and tests.
Remove only identical shadowing copies of two activation test functions created
by auto-merging; keep their parameter cases. Formatter normalizes four files.
No new operational behavior was invented during this assembly.

Evidence:

- 512 focused Python tests PASS20.81s: replacement, activation, catalog refresh,
  retention, market refresh, publication orchestration/client, family search.
- After duplicate-definition removal:164 activation tests PASS3.64s; no case lost.
- Ruff check PASS; formatter4 files normalized/167 unchanged.
- `node tests/theme-metadata-filters.mjs` and `node tests/theme-url-state.mjs` PASS.
- Official Shopify skill validator: snippet and section VALID, using cached
  official schemas because schema-network refresh was unavailable; telemetry OFF.
- Wheel and sdist built successfully with `python -B -m build --no-isolation`.
- `git diff --check` PASS. Repository preflight PASS210 files using the isolated
  preview index/worktree binding; the real repository index was not modified.
  No claim of full-suite coverage/exact-head CI/CodeQL.

The old private product/home presentation harness needs its original artifact
directory and is not an integrated source-only test. A no-argument invocation
failed its input assertion; those unchanged presentation proofs are reused from
their existing workstream evidence, not falsely reported as newly rerun.

## Review and remaining gates

Additional exact-tree native gate TERMINATED WITH FAILURES: unit
`nla-release-validation-cb27a5de.service`, invocation
`7b0a3b42eba6402fa365386a950f5bcb`, MainPID0/exit1. Verified input archive checksum
above; unprivileged dynamic user, no external network or access to live catalog,
credentials, Docker socket; protected read-only source/venv and dedicated scratch.
2GiB memory, one CPU,45-minute ceiling; no service deployment or timer changes.
Command: `python -B -m pytest tests --cov=nla_catalog_gateway --cov=scripts
--cov-report=term:skip-covered --cov-report=json:<output>/coverage.json
--junitxml=<output>/junit.xml --basetemp=<output>/pytest -p no:cacheprovider -q`.
Output root `/var/lib/nla-release-validation-cb27a5de` is retained. Terminal JUnit:
4040 tests,3935 passed,105 failed,0 errors/skips,814.273s. Coverage98.3208606%
(15585/15820 lines,5436/5560 branches), below the unchanged100% gate.
102 failures concern root-owned/private synthetic ledger fixtures, one capture
directory fixture missing0700, one obsolete rejection of ALL-family search, and
one repository preflight missing Git metadata in this source-only export.
Opt-in exact-ledger ownership fixtures, the directory mode and obsolete assertion
have been corrected; no production guard is weakened. Do not rerun the old unit.

### Test-portability correction completed

Six test files only (including new opt-in `tests/conftest.py`),45 additions and
9 deletions. Positive ledger fixtures set real0600 and simulate only root UID
on the exact registered ledger paths; all other lstat attributes remain real.
Negative UID/mode/link tests remain active. Nonempty capture directory uses0700.
The obsolete ALL-family search rejection now asserts matching/nonmatching results
while retaining forged request rejection. Independent reviewer APPROVED this delta.

Successor preview tree `c2a323ba7a0a06e069c4270c1b71783c774c4d31`;
`release-preview-v2.zip` SHA256
`24e5ced31dd66d3468ce4f2028925395922b5c84d7f84ca8e191122e814ac469`.
Ruff check/format PASS172 files;280 local focused tests PASS156.59s.
Native unprivileged/network-isolated unit `nla-release-recheck-c2a323ba`, invocation
`8370ae41f5c84554a8ec4f8725011dcf`, terminal MainPID0/exit0:
281 tests PASS73.341s, no failures/errors/skips. Includes the seven affected or
adjacent test modules and the real repository preflight entrypoint. Private JUnit:
`/var/lib/nla-release-recheck-c2a323ba/junit.xml`.

Preflight now has a separate synthetic Git index, no remote/credentials. First
preparation stopped before tests on an overly strict tree-equality assertion:
Git archive normalizes line endings (7 byte-identical files,204 newline-only,
zero substantive changes, all211 compared). Archive-native index tree24ef4944
records exact exported bytes; source archive SHA256 is verified. No production
service restarted. Both native validation units are terminal; do not relaunch.
These focused results resolve the observed failures but do not claim a new
4040-test full run,100% coverage or exact-head GitHub CI.

Corrections saved locally in their separate workstreams (no push):
`adbfa59156ada22d960c807c10e765320d6aef35` importer (#97),
`8d24b38124eb2c95f4f4e6481426d0b349dd3aba` family-search regression (#9).
Their six changed test files match the approved/tested preview after LF
normalization; only workstream evidence prose is additional. Unrelated untracked
coverage file in importer checkout was preserved, not committed.

### Full-suite result and focused coverage completion

Corrected-preview full run is TERMINAL: unit `nla-release-full-c2a323ba`,
invocation`254e7f97b7e245919c42e3a877ca6609`, MainPID0/exit1. JUnit:
**4040 passed,0 failures/errors/skips,813.120s**. Exit1 is the unchanged100%
coverage gate:99.75210477081384%,15820 statements/5560 branches total,28 lines
and25 branches missing in only the two staging operator scripts. No test failed.
Outputs `/var/lib/nla-release-full-c2a323ba/{junit.xml,coverage.json,.coverage}`.

Added cases in only `tests/test_activate_staging_refresh.py` and
`tests/test_replace_staging_image.py`: unknown runtime identity during rollback,
edge204 rejection, continuous healthy settle window, invalid plan/receipt/image
bindings, both rename interruption points, verified restoration, pending marker
and value-free CLI paths. No production or coverage configuration changes.
Replacement cases independently approved by deferred_export_review; activation
cases authored by that reviewer and reviewed by the parent. Local per-module
tests:166 activation/99 replacement PASS, each module100% coverage; Ruff PASS.

Successor tree `2d66cbd609db158450824d2d71347d7e8bda9ddd`;
`release-preview-v3.zip` SHA256
`dcc17d67b466977ccb0e0fce6d98c24b5b6787c8e92500fc9ecfaf021c4f03ae`.
Native comparison of all211 source files proves only those two test files differ;
all209 others are byte-identical. Reused full-run coverage via the documented
Coverage.combine API and paths mapping, retaining original binary data unchanged.
Ran the two changed modules with the same pytest command plus `--cov-append`,
same source selection and unchanged100% gate. No third full-suite rerun.

Native unit `nla-release-coverage-2d66cbd6`, invocation
`326b67cf794e40a8adf52d66571ede8f`: terminal MainPID0/exit0, active/exited because
RemainAfterExit=yes. **265 tests PASS,0 failures/errors/skips,8.570s. Aggregate
coverage100%:15820/15820 statements,5560/5560 branches,0 partial/missing**.
Output `/var/lib/nla-release-coverage-2d66cbd6/{junit.xml,coverage.json,.coverage}`;
`.coverage.full-original` preserves the imported data. Same isolated networkless
DynamicUser sandbox; source/venv read-only, no live data/config/Docker access,
2GiB/oneCPU/300s ceiling. No operational service/timer changed.

Coverage emitted old full-run source-path warnings. A separate read-only report
comparison confirms all52 filenames and per-file statement/branch totals match;
no module was dropped from the final denominator. Report this as aggregate
full-suite-plus-focused coverage, NOT a single new green full-suite command and
NOT exact-head GitHub CI. All jobs terminal; do not restart.

The exact reviewed test delta is saved on the operator branch as
`83b14e45ba20180805b2414f0c7b838041cd8ad7` (#13); no preview-only integration
changes were copied into that branch.254 operator-branch tests PASS4.65s,
Ruff check/format and diff checks PASS, checkout clean. Initial format check
flagged mixed line endings in one patched file; formatter normalized those only.
No push, deployment, source acquisition, VPS timer edit or GitHub CI start.

Independent `deferred_export_review`: APPROVE FOR STAGING for the documented
deployed combination, no unresolved blocking functional defect in reviewed scope.
This does not approve MAIN or an unmerged future release. The same independent
reviewer also APPROVED THE LOCAL PREVIEW: no High/Critical/Blocker in the examined
resolution/deduplication delta, reviewed implementations preserved and no test
cases lost. Review was read-only and did not independently rerun tests.

One owner-authorized retry of GitHub dependency-audit was accepted by the API;
latest job109328107709 on run35645001224 returned failure with no steps and logs404.
This proves no successful execution, not the precise current billing/quota cause.
Do not repeatedly retry or merge red checks. No new push or PR was made.

Remaining: deliver separate reviewed workstream PRs when Actions can execute;
freeze the actual integrated commit and obtain required green exact-head CI and
CodeQL. Bind release image/dataset/theme checksums and rollback evidence to that
candidate. Then request Jacopo's explicit #18 publication decision. Do not deploy
this source preview or change MAIN/PowerTools as a side effect of preparation.
