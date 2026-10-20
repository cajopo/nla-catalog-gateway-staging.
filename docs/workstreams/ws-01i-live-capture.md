# WS-01I — Fresh real acquisition (#71)

## Delivery reconciliation — 2026-10-20

This document delivers the historical 15–16 September evidence for issue #71.
The recorded work completed the original-byte Product/ProductVariant acquisition,
verified source-ID reconciliation, schema-v2 packaging and real traversal,
search and suggestion proofs. The final signed-service result on 16 September at
03:53 UTC accepted all 20 cases with exit 0, using runtime
`d2ae142334069abc2a0b305a014ca0682651ff3a`. Its collector-field and service-boundary
limitations remain explicit below.

This delivery contains documentation only. It performs no new capture, package
build, deployment or service operation and does not revalidate the private
historical artifacts. Current operational state and remaining project gates are
maintained in [STATUS-CURRENT.md](../STATUS-CURRENT.md).

The earlier running, failed and pending checkpoints below are preserved as
historical investigation evidence. The final accepted result supersedes those
checkpoints within the bounded acquisition/package-proof scope of #71; it does
not establish deployed storefront, durable synchronization or live-cutover
acceptance. Raw captures, authenticated metadata, manifests and private reports
remain outside Git.

## Historical acquisition checkpoints — September 2026

Branch `agent/live-bulk-capture` starts from reviewed runtime/source candidate
`3008e05938219bcdd1cf9e3d3f65b7134ae22ca3`. The architecture audit is complete;
this work uses the existing acquisition, reconciliation and single-build package
path rather than introducing a new architecture.

The existing local CLI session can read the shop. API version 2026-07 permits
concurrent Bulk queries; the approved products operation was checked RUNNING
before the approved variants query was dispatched. No operation was restarted
because a local observation failed. Operation IDs, authenticated store metadata,
raw artifacts and trust roots remain in the external private capture checkpoint.
No authenticated metadata is being published to GitHub without separate approval.

The variants query passed the official schema validator unchanged. The downloader
has independent static approval for original-byte streaming, exact approved-query
matching, bounded size and duration, HTTPS origin restriction without redirects,
exclusive output creation, integer terminal evidence and signed-URL suppression.
Both operations have now completed and their original JSONLs have been downloaded;
byte lengths match terminal metadata and independent rehashes match the transfer
checksums. Terminal capture windows overlap. The monitor exited successfully without
restarting a remote operation. Reconciliation completed through the existing script
with the current sidecar and independent expectation; every record was accounted for,
with no excluded or unclassified records. The seven-file bundle and independently
retained summary trust root remain outside Git. Runtime acceptance is not yet claimed.

The additional independent read-only count query completed with exact precision for
all products, structured singles, published active products and variants. Existing
preflight counts are unchanged. A private schema-v2 expectation binds those counts
to both capture identities and the separately hashed source-name manifest.

Independent control review APPROVE: the singles-count query covers all five
structured product types, counts have exact precision and match the control files,
Bulk queries match their approved shapes, terminal windows overlap within 24 hours,
and the separately checked canonical manifest matches its expectation trust root.
The reviewer also rechecked the downloader's stderr handling. This limited review
does not attest large JSONL contents, source join coverage or current runtime acceptance.

PowerShell native diagnostics initially interrupted observation under
`ErrorActionPreference=Stop`, although the CLI itself exited successfully.
The helper now captures only JSON stdout, discards native diagnostics, checks the
process exit code, and restores strict PowerShell handling after the invocation.
Only fixed stage names are emitted on failure; no raw network/API error is echoed.

The four original CSVs have been compiled successfully with the current compiler,
including collector metadata. The sidecar remains outside Git and does not by
itself establish current source-ID join coverage or compound printed-code semantics.
Explicit `PYTHONPATH` selects this worktree's `src` when running operational scripts;
the existing environment otherwise resolved an older installed package. No global
installation or environment configuration was changed to work around that mismatch.

## Final historical runtime result — 2026-09-16

Current result (2026-09-16 03:53 UTC): runtime `d2ae142` / draft PR #75 completed the
private signed-service proof, exit 0 and all 20 cases accepted. Complete ordered IDs
and expected suggestion groups/counts agree across all four games, including sold-out
records; unsigned requests reject. Maximum observed request duration is 0.971238 s
with the original 2 s deadline. Independent receipt review approves the bounded
result and verifies source/provenance/harness/report pins. This is not a concurrent
load test, ASGI/socket test, deployed proxy, clone, durable sync or restart proof.
All four collector cases have zero collector-exclusive matches: do not claim that
the real run independently isolates that field or establishes full printed-code coverage.
Missing source collector values do not remove products. The complete private report is
kept outside Git, alongside its independently checked manifest and source evidence.
Full local #75 application/scripts suite starts only after this real process exits.
Earlier running/no-fourth-run descriptions below are historical checkpoints.

### Earlier runtime checkpoints, superseded by the accepted result above

Latest run: reviewed commit `d2ae142334069abc2a0b305a014ca0682651ff3a` (#74, draft
PR #75) is now executing the private real-service proof. Launch checks passed for
clean HEAD, unchanged producer verifier/projection/search code and the separately
trusted package manifest. Package opening passed in 534.772 s and oracle preparation
passed in 7.009 s; runtime binding passed in 294.247 s. Signed request cases are
running. The binding phase is roughly half the last old-runtime observation, but
this is a local indicative comparison, not controlled host performance or HTTP
acceptance. Earlier no-fourth-run statements are historical.

Current harness preparation (2026-09-16): expected IDs, suggestion groups and coverage
for the same 20 cases are computed before serving and retained as builtin values only.
The caller's verified source graph is released before signed/unsigned requests. The
historical fixture count is labeled separately from current exact-name counts. No
query, scope, deadline or GC policy changed. Independent review approves; the helper
smoke passes against the #74 candidate, including rejection of an incorrect module root.
The next real launch must use a reviewed clean commit, check that verifier/projection
code is unchanged from the package producer, and independently recheck the manifest
trust root. Report actual runtime SHA/module origins separately from producer SHA.
The full #73 suite completed: 2,393 tests, 100% application/scripts coverage, exit 0.
The broader #74 suite ran only afterwards and passed: 262 tests, 100% runtime module
coverage, including signed HTTP traversal through 30,001 products. No fourth real-service
run has started; final reviewed source/provenance checks precede that launch.

The private framework-neutral HTTP-service acceptance harness has independent
APPROVE after fixing its filter DTO construction and public/unclassified oracle
scope. Collector-only contributions are reported separately from matches already
covered by name/SKU/barcode; zero exclusive matches cannot certify that contribution.
A lightweight local smoke passes twelve request-envelope round trips and the
collector-isolation helper. Ruff check/format pass. Packaging completed with exit 0
and ACCEPTED; after independently checking the installed manifest trust root and
unchanged runtime source, the harness was started. It is not a socket/ASGI, clone or
live E2E proof. Heavy stages remain sequential, not parallel.
The private harness also records package-open and runtime-bind durations separately;
this instrumentation changes no acceptance assertion. Ruff check/format pass after
the addition. The real package-open stage completed in 527.755 seconds locally;
runtime binding completed in 549.793 seconds. Together they expose a material startup
cost, not a request-latency result or a deployed-host measurement. No completed HTTP
report or storefront acceptance is claimed.
First attempt: all five Magic cases passed, followed by Pokemon browse/name/prefix.
It then exited 1 with AssertionError at Pokemon collector; no accepted HTTP report
was produced. The original harness omitted the specific assertion/status. A bounded
private diagnostic now retains fixed assertion reason, public error code, status,
request timing and partial results on failure; no raw response body or secret is logged.
Direct read-only SQL/oracle, suggestions and five-page DTO round trips agree for the
failed collector query, but do not establish HTTP acceptance or explain the failure.
The full unchanged case matrix was repeated with those diagnostics and the same
runtime source, package and default timeout. No production fix or relaxed gate is claimed.
The second attempt passed package opening in 529.851 seconds and runtime binding in
561.771 seconds (1091.622 seconds total). All five Magic cases and Pokemon browse,
name and prefix passed again. It exited 1 on the first Pokemon collector request:
HTTP 503, public error `temporarily_unavailable`, elapsed 2.011 s with the unchanged
2 s deadline. This is consistent with a deadline failure but does not identify the
responsible operation. A private failure report retains exact timing and partial results.
The isolated component probe now includes fresh production SQLite connections,
progress-handler deadlines, context validation and response validation/serialization;
it passes, including the first-page work in approximately 0.501 s. That excludes
authorization, generation binding and the large resident catalog: it is not HTTP proof.
The resident-catalog diagnostic completed: all three repetitions passed while keeping
the full DTO catalog in memory. First-page component work was approximately 0.506,
0.546 and 0.587 s. Long observed GC pauses were confined to loading; no pause over
50 ms occurred during these component requests. This does not reproduce the service's
complete request history and does not establish or rule out its root cause.
The third full service attempt recorded one bounded function/line stack near the
deadline and passive per-request GC durations. It retains real monotonic time, the
same timeout, case order, assertions and gates. Independent static review APPROVE
and clock/deadline smoke pass; timings include observation overhead and are diagnostic,
not host benchmarks. No production code changed and no accepted service report exists.
This third attempt passed package opening in 546.767 s and runtime binding in
584.006 s, then exited 1 during Magic browse with HTTP 503/temporarily_unavailable.
The failed request took 2.076 s; a generation-2 GC pause inside it took 1.858 s.
The near-deadline stack reaches the checkpoint after response serialization, so the
pause is a dominant contributor to this request's rejection. This does not identify
which retained objects caused GC cost or establish the cause of the prior failures.
The backend retains full source-record tuples for evidence identity checks, while
serving pages from SQLite. The oracle also shares this process. Local development/QA
ran during startup and preflight/build overlapped requests; these timings are not a
clean benchmark. No fourth full retry, GC configuration change or relaxed gate.

Historical fixture interpretation: a bounded private identity comparison of the old
and current SQLite packages found the same complete Lightning Bolt name-match GID set.
The fixture in issue #9 includes version-labelled canonical names; it is not the plain
exact-name subset. The private harness's `historicalExactNameCount` label therefore
misdescribes that reference and remains a pending label correction before any next run.
This is a reporting distinction, not permission to filter extra literal-name matches,
rewrite canonical names or substitute a smaller expected result set. The private v2
comparison records separate exact, fixture-family and substring counts plus name groups;
no commercial record was modified and no identities disappeared between these packages.
The similar durations make the local startup cost reproducible, not a proof of its
cause or a request-latency result. The provider startup-window risk is recorded in
`ws-09b-staging-deploy.md`; no deployed-host timing is claimed.

### Earlier completion checklist, superseded by the accepted result above

1. DONE: both existing operations reached terminal success; original bytes downloaded.
2. PASS: terminal metadata, query identity, independent counts, checksums and overlap.
3. PASS: reconcile every current record using the source-ID join, with complete accounting.
4. PASS: current schema-v2 core report and final candidate/installed package checks;
   process exit 0, ACCEPTED. Sync evidence covers initialization, not incremental events.
5. FAILED: the first two signed service attempts stop at Pokemon collector; the third
   stops during Magic browse and observes a dominant GC pause. Investigate retained
   runtime/oracle memory before another long retry. No HTTP acceptance yet.

No raw artifact, control file, signed URL or generated database may enter Git.
No activation, deployment, clone installation or end-to-end storefront acceptance
is claimed. CI/workflow authorization and the live cutover gate remain separate.

Official reference checked 2026-09-16:
https://shopify.dev/docs/api/usage/bulk-operations/queries
