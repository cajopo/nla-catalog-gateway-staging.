# NLA catalog gateway — execution roadmap

## Active finishing roadmap — 2026-09-29

This section supersedes the historical overlays below. Preserve the objective;
no new architecture, catalog capture, repeated broad audit or MAIN file changes.

Owner29September update: GitHub delivery is now deferred at the owner's explicit
instruction («anche github sticazzi»). Do not wait for Actions reset to prepare
operational closure; no paid upgrade or repeated quota checks. Existing evidence
must remain truthful: local validation does not become green GitHub CI. No merges
of red checks. The owner publication decision/password boundary still applies.

1. **DONE — working staging acceptance.** Catalog beyond25k, four-game isolation,
   distinct-name suggestions, family search, filters/history, images/SOLD OUT and
   real available-variant cart path already passed. First unattended market cycle
   added/published12 verified cards, all12 in the active index; scheduled warm
   refresh and service readiness passed. Completed heartbeat removed; VPS timers
   continue without Codex.
2. **DONE — local integrated validation; final commit still to deliver.** Source preview
   prepared from runtime8da5d4c + operator7f421cf (includes importer317126b) +
   theme09821ca. Reviewed prior conflict resolution reused, duplicate test names
   corrected; focused tests/lint/theme validation/build pass. Native full suite
   exposed105 test-harness/obsolete-test failures. Test-only fixes independently
   approved;280 local/281 native focused tests now PASS, zero skipped. Preserve
   full corrected run:4040PASS/0skips, coverage99.752%, command exit1. Two reviewed
   test-only additions then passed265 native tests; aggregate coverage100% with
   all209 non-delta files byte-identical and all52 report files accounted for.
   Final previewtree2d66cbd6; all validation jobs terminal, do not relaunch.
   Test fixes saved locally as importeradbfa59, runtime8d24b38 and operator83b14e4
   (254 focused branch tests PASS). No push. This is not a branch merge,
   a green full exact-head CI run or a new deployment.
3. **DEFERRED BY OWNER — GitHub delivery (#16).** One authorized
   retry failed before test execution; precise quota status remains unavailable.
   Do not repeat retries or merge red checks. When Actions can execute, deliver
   separate reviewable workstream PRs, resolve integration exactly as previewed,
   obtain green required CI/CodeQL on the actual final commit, and pin the image,
   accepted dataset, clone checksums and rollback evidence for that release.
4. **DONE — owner cutover (#18),29September17:20UTC.** Explicit «consento» received.
   Published175195881740; API confirms MAIN, prior175194898700 UNPUBLISHED,
   both complete file inventories unchanged and password enabled. Non-preview
   search/suggestions/game-isolation/product smoke PASS. No product/PowerTools
   changes, new backend deployment or password removal. Rollback theme retained.

The operational objective is complete. Only the separately owner-deferred GitHub
delivery remains; do not restart completed acceptance work or infer public launch.

Evidence: `workstreams/ws-12-release-readiness-20260929.md` and the initial section
of `STATUS-CURRENT.md`. Do not restart completed historical work below.

## Current goal overlay — 2026-09-15

Latest2026-09-21: postactivationactualShopifyproxy smokePASS4games/8pages/192items,
correctgame/no crosspageduplicates,9–10canonicalnamesuggestions; MAINunchanged.
Automaticrefresh and ownerclarifications remainopen; no completion claim.

Latest2026-09-21: exact v3package deployed-imagereopen/runtimebindingPASS291795.
Stagingactivation preflightPASS and one guardedactivation launched; ready/result
still pending. Existing completeproof5848paginationpages/129queries reused, not rerun.

Latest2026-09-21: v3 full packaging SUCCEEDED (acceptedreceipt+terminaljournal).
Next necessary gate, deployed-image reopen, now running; activecatalog unchanged.
Updated acceptance includes5dynamic suggestions when available. Resolve individual
products versus canonical-name grouping with owner; do not redesign architecture.

Latest2026-09-18 resume: v2 failedSIGSEGV11 during optional timedtraceback dump;
cause unproven, activecatalogready. One reviewed v3 attempt started without that
diagnostic, same7d833b6 source/verifiedbundle/2GiB limit. CI+CodeQL nowgreen.
No new export, no acceptedcandidate or activation yet. Minimize polling/credit use.

Latest2026-09-18: reviewed streaming-hash fix7d833b6 pushed toPR92;312focusedtests
pass and sync/packagingcoverage100%. Separate recoveryv2 confirmedrunning under
same2GiB cap against preserved bundle. Wait exactunit; full proof/runtime reopen,
staged activation/rollback and ongoing sync still not complete. No live changes.

Latest2026-09-18: recovery v1 also terminated OOM at 2GiB after1948.69CPU seconds;
no accepted package or activation. Runtime readyz still passes. Next is a narrow
byte-preserving streaming sync-hash correction plus tests/review, then a new
bounded packaging attempt using the same verified bundle (no repeated export).
7397ffc CI/CodeQL are successful, but actual full-catalog recovery remains open.

Latest2026-09-18: complete downloads/reconciliation retained after v2 packagingOOM.
Reviewed minimal memory-lifetime fix7397ffc is running in a separate bounded
recovery unit, using the original pinned bundle; no new exports or activation.
166 focused testsPASS; full suite pending. Next: successful full proof, deployed
runtime reopen and staged refresh/rollback verification. Do not infer completion.

Latest2026-09-18: both v2 Shopify exports COMPLETE/exactcounts/noerrors. Local
download/candidate pipeline still running; not candidate acceptance/activation.
Next sequential deployed-image reopen checker prepared and independently reviewed.

Latest2026-09-18 11:37UTC: permission passed; independently reviewed fresh v2
capture launched and both operation IDs verified RUNNING/noerrors. New private
checkpoint; old pair untouched. Next verify complete outputs and candidate before
activation; current catalog unchanged. No continuous-refresh completion claim.

Latest2026-09-18: permission gate RESOLVED. Same-app probe confirms granted
read_publications and actual publication/media data without errors. New coordinated
acquisition remains next; no capture launched or catalog activated by this check.

2026-09-18 owner update verified: read_publications now requested, not yet granted
to installed NLA Catalog. Actual API still denies publication access. Next gate:
merchant approves installed-app access update. No new capture or activation yet.

Latest2026-09-18 correction: productsBulk FAILED ACCESS_DENIED; supervisor terminal,
variantsBulk now COMPLETED293866roots/noerror. Exactsame-appprobe still identifies only
read_publications missing at product.resourcePublicationsV2. Ownerappversion/scope
update required; preserveoperationIDs andinspectstatesbeforeanynewcapture. Current
catalogunchanged. Third consecutive permission-blocked goal turn; no live operation
or candidate. Recovery requires a new overlapping pair after permission verification,
not combining completed variants with a future products export. No relaunch yet.

Latest2026-09-18 10:51UTC: fresh candidate acquisition concretely RUNNING onVPS,
both known Shopify read-only Bulk operations live; independent counts captured.
Reviewed source64cfe4e and pinnedreference reused withfulljoinverification, current
catalog untouched. Next inspect sameunit/operationhandles, then verify candidate;
automatic scheduling/activation/incremental freshness remain open. Owner confirms
imagecorrectionvisually and n/d semantics. PR91 exact-headCI/CodeQLgreen, draftopen.

Latest2026-09-18: owner confirmed first/nextpage visually and requested images.
Theme-only visiblecardimage enhancement committed079f950 onagent/theme-card-images,
independently reviewed;21browserfixturechecks/2Liquidfiles/preflight123PASS.
Clone snippet+section installed guarded/readbackPASS;12realimageidentities+HEADPASS,
deliveredbundle+4gameproxyregressionPASS. MAIN untouched; ownerimagevisualcheck,
interactiveQA and continuousrefresh still open. No runtime/index expansion.

Latest2026-09-18: actual storefront access unblocked; normal login, no bypass.
Diagnosed real Shopify trailing-slash forwarding and normalized only two exact
paths at edge, preserving signature/query/method;11negative checksPASS. Actual
Shopify-forwarded4games/8pages/39suggestionsPASS. Guarded clone header+alternate
page endpoint installed/readbackPASS. Rendered previewHTTP200 two unique component
instances and bundledJS; MAIN unchanged. Interactive QA and continuous/current-source
refresh remain open; not roadmap completion. Previous access-blocked entries historical.

Latest2026-09-18 09:34UTC: owner installed appversion2 and privately entered credentials.
OAuth authenticated exact required4scopes. Real app-secret runtime activation SUCCESS;
independent deployment/readiness review accepted. Sameimage/data/cursorkey; previous
runtime retained stopped. Direct signed HTTPS4games/8pages192products/39suggestions
PASS, unsigned/oldkey401, ready200/TLS0. This is not Shopify-forwarded E2E: actual
proxy is storefront-password protected. Owner secure input helper prepared; no bypass.
Clone one-setting endpoint activation backedup/validated, NOT executed; header remains
unchanged. Fullrefresh/QA/live gates remain open. No host reboot or MAIN changes.

Latest2026-09-18: #13 same-release recovery independently verified on isolated VPS
replica: recreated/restarted8cases each PASS,8 actual old-process cursors each PASS,
same complete pages/suggestions/sold-out data; originalservice unchanged. Isolated
SIGKILL137/noOOM, finalstopped0. Startup~520s/~515s. Enabled only runtime restart
policy unless-stopped without restarting it; HTTPSready200. No new application code
or full traversal rerun. Actual Shopify auth/Proxy, refresh, different-version rollback,
backup restore and owner freshness tolerance remain open. Full objective unchanged.

Latest2026-09-18: #89 implementation in mergedPR90, head64cfe4e, independently APPROVED.
One-pass read-only Bulk acquisition/checkpoint feeds existing reconcile/package;
native180PASS100%newmodules, preflight137/build/RuffPASS. CI35297542683 and
CodeQL35297542658SUCCESS, bothPython2843PASS100%fullapp/scripts,zero skips.
Technicalmerge0a37736 treeequalshead. Real #89acceptance still open, as are #11 and
the full goal. No scheduler, activation, main/live/PowerTools mutation.

Latest2026-09-18: closedissue87 / mergedPR88 heada4fdb4f enables existing offline Bulk
reconciliation on real Linux. Native201tests PASS100%reconciler, Windows330tests
PASS; synthetic raw→bundle→package→search test covers all4games and sold-out cards.
Initial CI exposed trailing-dot checkout incompatibility; POSIX input fix and
reader-compatible output restriction reverified. Exact-head independent APPROVE;
CI35293756661/CodeQL35293756641 SUCCESS,2663tests eachPython100%,zero skips;
technicalmerge9fe7358 treeidentical to testedhead. Next minimal scope #89 (not implemented).
This advances preparation for #11 but is not automatic refresh or Shopify E2E.

Latest2026-09-18: mergedPR86 head9779401 adds the missing Linux source-bundle reader
within the existing boundary.282 nativeLinux tests PASS,100%reader line/branch,
independent exact-head APPROVE. Full CI35289718253/CodeQL35289718435 SUCCESS,
2569tests perPython3.12/3.13 at100%; mergedtechnicalbaf0316, treeverified,issue85closed.
Runtime/Shopify unchanged; #11 remains open for actual autonomous update plumbing.

Latest2026-09-18: reviewed7file theme component preinstallation now uploaded to
UNPUBLISHED175195881740 with explicit four-batch owner approval and7/7remote readback
PASS. Existing header/default search and MAIN untouched; endpoint unset. This moves
theme installation forward but not real proxy/theme E2E or automatic-sync acceptance.
Owner created NLA Catalog app; version/proxy configuration pending. DNSrecordconfirmed
and trusted public HTTPS operational:health200,unsigned401,unknown404,redirect308.
Fourgame private-HMAC HTTPS transport comparisonPASS,independentreviewPASS. Not
Shopify-signed auth,E2E,sync or restart/restore acceptance; full objective unchanged.

Current2026-09-18: owner-funded Aruba O2A4 host and staging hostname approved.
Reviewed5183191 built on chosen host; exact accepted package transferred and
Linux operator promotion PASS. Private host complete HTTP proof PASS20cases/3,008
pages,291,791 eligible products including290,795 sold-out; independent review PASS.
Max0.514949s loopback, not internet/concurrency or Shopify integration evidence.
SSH hardened to key-only. No public port, DNS, Shopify or theme changes. DNS and
app setup require owner panel input; connector cannot list apps and browser capture
stopped on unverifiable URL. Continue HTTPS/App Proxy/theme and real sync;
do not substitute private deployment for the full objective. Owner now explicitly
permits MAIN theme work (store not public), but no public-launch/password-removal
authorization; plugin's unpublished-theme-only write restriction remains binding.

Current (2026-09-16 16:15 UTC): explicit approval received; PR47 at739ac1e MERGED
into main as87b3713 after unchanged-head green CI/CodeQL and independent review
reconfirmation.1,705 tests per Python100%; merged/tested trees equal; issue46 closed.
Historical #47 authority block resolved. Owner has existing Aruba hosting; plan/access
identification requested before deciding compatibility. No new hosting purchase,
deployment, main-theme or Shopify mutation. Remaining sync/runtime/clone/QA gates stand.

Current (2026-09-16 14:44 UTC): issue#83 / draft#84 at790b5eb on5f2cd8c implements
explicit incremental lineage → existing verified package → conditional runtime
activation. New-card printed-code search, update/stock-zero, delete/unpublish and
retained cursors tested with real synthetic SQL/backend.33 final focused PASS100%
publication module;296 baseline and383 diagnostic functional tests PASS. Independent
review APPROVE at790b5eb; Linux CI failed13 fixture-platform cases before exercising
incremental code. Corrected test-only head5183191:33 PASS157.17s100%; follow-up
review APPROVE and CI35111905405/CodeQL35111905535 SUCCESS. All2,534 tests per
Python at100%, all foundation checks PASS. PR84 merged as e599c38 into the technical
source-card-codes branch; issue83 closed. Merged/tested trees equal. No production
boundary weakened, no Linux source-ingestion or autonomous Shopify updates claimed.
Next: durable active-pointer/runtime coordination, restart/replay and authoritative
re-fetch worker; existing source metadata/host/App Proxy/clone/full E2E gates remain.

Current (2026-09-16 07:55 UTC): #82 merged reviewed5d312fe as5f2cd8c into
agent/source-card-codes; issue#81 closed. Authenticated optional ingress into the
durable inbox, no new service.226 focused tests100%, independent security APPROVE,
exact CI35070071164/CodeQL35070071181 SUCCESS. All2,510 tests per Python100%,
foundation checks PASS, merged/tested trees equal. Durable receipt is not publication;
next critical integration remains authoritative refresh/incremental publication.
No live/provider/Shopify/main change or accepted real-proof rerun; goal still open.

Historical code inspection before#83: `sync_publication.publish_reconciled_generation`
deliberately rejects incremental GenerationView identities. `DatasetManifestV1`
and the evidence-bound serving path currently require reconciled baseline provenance;
bootstrap loads an externally pinned activation once. Completing the worker means
closing those real publication/serving links, not just marking inbox rows complete.
Preserve authoritative re-fetch, code/name metadata, atomic publication and old-cursor
retention. Do not fabricate Bulk provenance for event-derived records or add another
coordinator that cannot update the running catalog. No architecture change selected
or implementation claimed by this observation.

Previous (2026-09-16 07:22 UTC): #80 merged reviewed224dbfd as9a53937 into
agent/source-card-codes; #79 closed. New50 tests at100% plus152 sync regressions and local
foundation checks PASS. Independent exact-SHA review APPROVE/50 independent tests
at100%; exact CI35067211964/CodeQL35067211969 SUCCESS, all2,446 tests on both
Python versions at100%, preflight/build/container/dependency PASS. No main change.
Next integration still requires authenticated webhook ingress and durable publication
worker/reconciliation; storage acceptance alone does not complete live sync or the goal.

Latest (2026-09-16 06:57 UTC): #78 merged reviewed `6eba4de` as `9594d79` into
the #66 technical branch; #67 closed. Exact CI35064106542/CodeQL35064106648 PASS,
2,396 tests on each Python at100%, independent combined review APPROVE.
Real-data local UI accepted within scope: 33 checks / 36 pages, scoped suggestions,
sold-out labels, history/reload and four viewport widths. Prior header timeout remains
unexplained. Temporary preview process confirmed live, no accepted proof restarted.
Not actual Shopify Liquid/App Proxy/clone, durable sync, load or full E2E acceptance.
Keep the full goal open and continue concrete delivery; do not repeat the completed
architecture audit or expand the framework. Hosting and #47 owner gates unchanged.


Latest action (2026-09-16 06:12 UTC): #73 merged as `3d73c36`, #72 closed;
final CI35060908543/CodeQL35060908551 PASS, all 2,396 tests on both Python versions
at 100%. Parent #70 now has that same-content head, CI35062359454 and
CodeQL35062359451 PASS; combined review is running, merge remains separate.
Private existing-theme to real-runtime loopback UI harnesses are independently
reviewed; the server is opening the package, browser not yet run. Not accepted/deployed.
The audit is complete; no architecture restart or full accepted-proof rerun.

Current action (2026-09-16): parent PR #73 at new head
`bfb7dea906f6bd64eca6535a006b0b8181f41bff`, following merged PR #75 and #77.
Issues #74/#76 are closed completed. Final #75 CI35060201325/CodeQL35060201353 PASS;
both Python versions all 2,396 tests at 100%. Current #73 CI35060908543 running,
CodeQL35060908551 PASS, combined exact-SHA static review APPROVE. Technical
branch consolidation is not deployment or main/live publication.
The merged tree equals tested `a98bd93`: local and CI both execute all 2,396 tests
at 100% line/branch coverage; local suite reduced from 45m11s to 19m58s.
No assertions, datasets, application code, workflows or thresholds changed by #77.
No local heavy job remains. No main merge, deployment or goal completion.

Previous action: #74 / draft PR #75, `agent/runtime-detached-records`
at `d2ae142334069abc2a0b305a014ca0682651ff3a` on #73. Detach the serving source graph
after complete validation; 262 broader tests pass with 100% runtime module coverage,
including 30,001-product HTTP traversal and independent exact-SHA static approval.
The reviewed real-service proof passed all 20 cases on this frozen candidate, with
independent receipt review. This is local framework-neutral service evidence, not
deployed/ASGI/clone/sync/restart acceptance or complete printed-code coverage. Parent
#73 full suite passed 2,393 tests at 100%; #75 full local suite now also passes:
2,396 tests in 2,711.07 s, 100% application/scripts line/branch coverage, no skips.
The reviewed real-package loopback TCP/ASGI smoke also passed afterwards on the same
frozen candidate: first/second pages of 20 cases, 34 pages, oracle equality, sold-out,
health and unsigned rejection; max observed request 1.683 s. It is not a complete
network traversal or Shopify/clone/deployment result. Both local jobs are terminal.
Candidate remote CI is cancelled, not green. No overall completion implied.

Previous action: #67 / `agent/staging-single-build` on #66 (`fbe3cfc`). Package the exact
core-verified projection with one build, preserving every gate. This is a bounded
audit simplification, not a rewrite. See `ws-09c-single-build-package.md`.

Previous action: #65 / `agent/source-card-codes` on #64. Recovered source CSVs remove
the source-location blocker. Carry collector metadata through the existing verified
join and SQL/API path; see `ws-01h-card-metadata.md`. Full goal stays unchanged.

Previous slice is #14 / draft PR #64 (`agent/theme-clone-integration`) on green runtime #63: connect the
customer-facing path with a reusable game-scoped search/page component. Local UI/browser
fixtures are not a clone installation or real E2E. Read `ws-10-theme-clone.md` before any
upload; locale fragments must be merged, never replace the existing translations wholesale.
The audit's simplification findings are recorded as direction, not a new rewrite workstream.
Real data codes/images, package acceptance, durable sync, staging and E2E stay on the path.

Completed local runtime slice #62 removed unconditional output denials while retaining
authentication and verified-generation checks. #60 supplies literal name/SKU/barcode SQL
search and opt-in suggestions; printed-code semantics remain outstanding.
Dependency PRs through #57 remain unmerged; live remains Jacopo's #18 gate. STATUS-CURRENT
and the #60 workstream distinguish executable evidence from pending work.

The roadmap below is historical.

Last reconciled (historical): 2026-09-01T02:59:58+02:00

## Dependency order

Platform is the current merge gate. Taxonomy, Data/Bulk, and the runtime contract may be
designed in parallel after that gate, but their pull requests must use the merged Platform
foundation. Pagination, search, filters, sync, and security depend on the canonical data and
taxonomy contracts. Runtime/staging depends on those cores; theme clone and QA follow a
verified staging service. Live cutover remains a separate owner decision.

## Workstream status

| WS | Issue | Current state | Verified source | Next executable action |
|---|---:|---|---|---|
| Platform/CI | #6 | REVIEW | Draft PR #20 carries remote candidate `73f3f78`; exact CI and CodeQL are green | Docs-inclusive gates and reviewer v4 |
| Sharding spike | #8 | BACKLOG | PR #21 closed/unmerged | Reproduce later only if limited fallback has value |
| Taxonomy | #19 | BACKLOG | PR #22 closed/unmerged | Reimplement contract after Platform |
| Data/Bulk | #5 | BLOCKED | PR #23–#25 closed/unmerged; real data root missing | Freeze code contract after Platform; real-baseline proof remains blocked |
| Pagination | #7 | BACKLOG | No accepted PR | Start after data schema/generation contract |
| Search | #9 | BACKLOG | No accepted PR | Build independent oracle before SQL |
| Filters | #10 | BACKLOG | No accepted PR | Freeze canonical parser/algebra before SQL |
| Sync | #11 | BACKLOG | No accepted PR | Define immutable inbox and reconciliation after data |
| Security | #12 | BACKLOG | No accepted PR | Implement App Proxy verifier with separate red team |
| Runtime/API | #3 | BACKLOG | Foundation only | Freeze shared response/error/dataset contract |
| Deploy | #13 | BACKLOG | Render is only a candidate | Prepare blueprint/cost/rollback before owner decision |
| Theme clone | #14 | BACKLOG | No accepted PR | Work only against unpublished clone after staging |
| QA | #15 | BACKLOG | No accepted PR | E2E on exact staging release SHA |
| Principal review | #16 | BACKLOG | No final release review | Review exact candidate SHAs independently |
| Cutover | #18 | BACKLOG | Explicit owner gate | No action before go/no-go decision |

## Wave gates

### Wave 0 — Platform

Documentation-inclusive SHAs `f211b26` and `00f0703` received `CHANGES REQUIRED` in successive
independent reviews despite green CI and CodeQL. Documentation head `82ec0e4` then received a
third `CHANGES REQUIRED`: one High remained because shell and PowerShell `$()` subexpressions
could conceal forbidden dispatch.

Remote code candidate `73f3f78` and local equivalent `db86bd3` share exact tree `a72a1c6`.
Local Ruff, format, build, audit, Docker build/smoke, static replay, 564 tests at 100%
line/branch, preflight
over 25 indexed files, and a static red team with zero High pass. Exact remote CI
`33456765768` and CodeQL `33456765740` also pass; CI covers both supported interpreters,
isolated builds, audit, and container smoke, while CodeQL reports zero security findings.

The bounded static gate retains the D-007 capability controls and adds conservative whole-class
bans for `$()`, `<()`, `>()`, and `@()`. Container smoke replaces command substitution with a
directly auditable `docker run | python` pipeline. Workflow permissions stay read-only,
workflow secrets are forbidden, and checkout credentials must not persist.
Python, Docker, and arbitrary transitively invoked scripts remain outside semantic analysis;
this is not absolute proof over indirect execution. Exit still requires completed green gates
and reviewer v4 on the same final documentation-inclusive SHA, with no unresolved
Blocker/Critical/High finding.

### Wave 1 — Canonical data contracts

Deliver separate reviewable pull requests for Taxonomy, Data/Bulk, and Runtime contract.
Every included record must be accounted for exactly once. Unknown or unsupported fields stay
nullable, provisional, or unsupported until measured on a verified baseline.

### Wave 2 — Catalog core

Implement signed context-bound keyset cursors, exact-first family search, canonical filter
state and facet algebra, immutable event inbox/reconciliation, and App Proxy verification.
Synthetic tests must cross 30,000 records before real-baseline traversal is claimed.

### Wave 3 — Runtime and staging

Add API, health/readiness, cache/version semantics, Docker runtime, observability,
backup/restore, and a validated Render candidate. A paid plan or recurring cost requires an
owner decision only after the technical package and current official pricing are ready.

### Wave 4 — Unpublished theme and QA

Integrate only with the Shopify clone. Verify URL state, scoped search/facets, accessibility,
mobile layouts, PDP/cart/checkout handoff, gateway failure modes, and browser coverage.

### Wave 5 — Live

Freeze code SHA, dataset checksum, and theme checksum; back up, dry-run, and present a
go/no-go package. Only Jacopo may authorize publication or other live cutover actions.

## Rules applied to every wave

- One issue, one `agent/*` branch, one reviewable pull request.
- No author self-approval and no review carried over from an older SHA.
- No skipped test is counted as PASS.
- No large data, generated index, credential, or signed download URL enters Git.
- Shopify remains the commercial authority and this project stays read-only.
- A written plan is not progress; status advances only with executable evidence.
