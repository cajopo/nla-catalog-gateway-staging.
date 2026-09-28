# WS-09F — Keep search serving during index replacement (#13)

## Change

The previous activation stopped the serving process before starting its replacement.
The observed cold start on 2026-09-28 took roughly nine minutes. Keep that old process
serving its already loaded generation while the replacement opens the verified index
on the other loopback port (10000/10001). This is not a new index, public endpoint,
Shopify writer, source acquisition, or application release.

`ops/caddy/Caddyfile.staging` preserves the existing public route/method, body-size,
TLS, log-redaction and transport policies. Its two static upstreams use first-healthy
selection, `/readyz` active checks and bounded connection retries. Admin stays off;
there is no per-refresh edge rewrite/reload. A newly healthy primary can receive
requests before the operator writes its acceptance receipt. Do not assume otherwise.
GET round-trip failures may retry; POST round-trip failures do not automatically
retry. This removes the cold-start gap, not a guarantee that every in-flight request
survives every failure.

The activation operator checks the exact candidate identity, private port and pointer
while waiting for sustained readiness. Only after readiness and accepted-env commit
does it retire the original and check edge readiness. Failure after commit retains
pending state for inspection. It cannot report success if retirement or edge readiness
fails. Image, mounts, environment allowlist and container restrictions are unchanged.

Before commit, rollback first checks the original's identity, port and actual readiness.
It stops only the candidate, rolls back the pointer, warms a replacement for the old
generation with the *new rollback pointer hash*, commits that environment and then
retires the original. If restoration fails, the original stays running. It must not be
restarted with its stale pre-promotion pointer pin. An unexpected survivor fails closed
without stopping a candidate that might already be serving.

## Rollout prerequisite and rollback

Do not enable this operator against the old single-upstream Caddy configuration.
Wait for the current refresh/importer operation to finish and retain the pipeline lock
through rollout. Back up the existing edge config and service/config pins. Validate the
new Caddyfile with the installed immutable image; install it and restart only the edge
once (its admin API is disabled). Check the mounted bytes and edge readiness before
switching future refresh/importer invocation paths to the new pinned operator package.
Do not modify a running refresh package or its configuration.

The current runtime remains on port 10000 for the initial rollout. If edge validation
fails, restore its saved config and restart it; do not enable the new operator. Once a
real activation has moved the current runtime to 10001, reverting to the old single-port
edge or operator is **not** a safe rollback. Keep the dual-port edge and inspect the
pending operation/receipts; use the recorded current runtime, port and accepted pin.
Never start the retained original container with its obsolete environment.

## Evidence

- Independent review: approved, no blocking findings; two-upstream edge is a required
  deployment prerequisite, not something to discover after retiring the old runtime.
- Focused offline activation + coordinator suite: **208 passed** (2026-09-28).
  `python -m pytest tests/test_activate_staging_refresh.py tests/test_refresh_staging_catalog.py -q --no-cov -o addopts= -p no:cacheprovider`
- Additional cases cover both port directions, sustained readiness reset, incorrect or
  public port bindings, unavailable survivor, failed restoration, post-commit retirement
  failure, and edge failure. No full catalog recapture was launched for this change.
- GitHub delivery remains on hold until the owner's Actions allowance resets.
- Native Caddy 2.11.4 isolated test: full deployment config validates; both port
  directions and all five warming/retirement phase checks passed. Each of two
  continuous-POST runs made 422 requests and observed one HTTP 502 during abrupt
  synthetic retirement. This is the documented transient POST limitation, not a
  prolonged outage or a zero-error cutover. Independent review accepted it as
  nonblocking for this scoped availability correction. No automatic POST replay
  or request-body buffering was added.
- Test container used the installed immutable Caddy image, loopback ports
  21000/21001/21002 and synthetic responses; it was stopped and removed afterward.
  The real edge, service and in-flight catalog refresh were unchanged.

Official documentation consulted before implementation:

- https://caddyserver.com/docs/caddyfile/directives/reverse_proxy
- https://caddyserver.com/docs/command-line#caddy-reload
- https://docs.docker.com/engine/containers/run/

## Native rollout — 2026-09-28 18:35 UTC

Code `61be1734e19da1305b57737deb857e1da7c25a36` is installed at
`/opt/nla-staging/refresh-61be173`. The same 208 tests passed on native Linux under
the service's UMask0077. The guarded installer waited for the existing recovery
to finish successfully, then applied the reviewed edge-first deployment under
both pipeline locks. It verified the pinned mounted Caddyfile, startup command
and HTTPS readiness before changing future refresh invocations. Backups and the
terminal receipt are in `/opt/nla-staging/warm-rollout-61be173/`.

Post-deployment: HTTPS `/readyz`200, no pending refresh/importer markers, only the
expected runtime and edge containers running. The serving runtime was not restarted
or replaced by this rollout. Importer code remains `d7e6fc9`; only its refresh-package
argument changed. No new capture, Shopify write, MAIN theme or PowerTools change.
Both timers restored: market02/14UTC, ordinary03/15UTC, Persistent=false; next starts
2026-09-29 02UTC and03UTC respectively. No timer cadence was changed.

The pre-existing recovery completed with zero selected products/attempts/publications.
Its source result remains explicitly partial: exports4887/4888/4890 returned404.
They are deferred, not invented or treated as complete. Its index refresh completed
at18:35:34UTC. That run used the old operator: the first scheduled real two-runtime
warm replacement has not yet been observed. Current evidence is the native proxy
exercise, offline fault tests and verified edge/operator deployment, not a claim
that the already-completed run used the new procedure.

## Local delivery compatibility follow-up — not deployed

Commit `f523d3978346e6a0de2ba25737f973e4e02046d7` preserves separate pinned
previous/candidate images during warm upgrades. Optional `old_image` defaults to
`image` for existing plans; fresh preflight binds both images, rollback uses the
candidate selector and restores the previous runtime image with the new pointer pin.
The warm readiness/commit/retirement order is unchanged. The activation and refresh
suites pass 219 tests locally; Ruff check/format and diff check pass. Independent
`deferred_export_review` approved. No native test or rollout is claimed for this SHA;
the installed operator remains61be173.

Read-only Git merge-tree preview against `agent/staging-ready-release` still has
one textual conflict in `scripts/activate_staging_refresh.py`: retain the warm
port guard and survivor/rollback ordering, not the old stop-before-warm variant.
Semantic image compatibility is now implemented, but the branches are NOT merged.
Runtime, importer/operator and theme remain separate delivery lines. GitHub hold
remains in force; no push, merge or CI rerun was performed.

## Compatibility fixes installed — 2026-09-28 19:46 UTC

Operator `881b9ca08dd2bc3ba9875b10d59ccb1a825a9246` now replaces61be173 in
the future refresh configuration and both relevant service paths. It includes
the separate previous-image rollback fix above and restores strict image-upgrade
receipt handling in retention, byte-equivalent to runtime9b56fdd's existing logic.
The missing retention case would otherwise fail cleanup after a code-only update.
272 activation/refresh/retention tests pass locally and on native Linux; independent
review approved. No warm ordering or security guard was relaxed.

Package `/opt/nla-staging/refresh-881b9ca`; archive SHA256
`291d967a77ca1295a385ebc6a72be72d64c721a32f3aac82d95d4d1a3600dcbd`.
Native command used the existing validation venv with UMask0077:
`python -m pytest tests/test_activate_staging_refresh.py tests/test_refresh_staging_catalog.py tests/test_refresh_retention.py --no-cov -o addopts= -p no:cacheprovider -q`.

Installed alongside family-runtimeed24a61, using the old code-only helper from
that package with its own module signatures. This one-time runtime replacement
was cold (~9m20s), NOT a demonstration of warm activation. Dataset, accepted
environment and source age were unchanged. Independent installer review confirmed
signature/pin coherence and fail-closed pending evidence on installation failure.
Actual attempt completed successfully:20260928t193738z-06c1ef95,
`/opt/nla-staging/family-rollout-ed24a61/completed.json`; do not rerun it.

HTTPSready200, fresh, no pending markers; both jobs idle and both timers restored.
Next market29Sep02UTC, ordinary29Sep03UTC. Importer d7e6fc9 and Caddy unchanged.
First real scheduled warm activation is STILL unobserved. Existing heartbeat was
updated to inspect that outcome, not to start work or repeat acquisition.
No MAIN, PowerTools, product writes, GitHub push/merge or CI rerun.

## Code-only helper integration fix — local, not deployed

A non-ref-updating merge-tree preview of runtime `8da5d4c` and operator `585c0ea`
produced tree `5099568b3555517681bd2f405e3c4d950f3f3466`. Its exported source
revealed five real test failures: the runtime's code-only helper still used the
old activation helper signatures. No branch was merged or live package changed.

Backport `scripts/replace_staging_image.py` and its tests here with the warm API:
use the alternate validated loopback port, keep the original serving through
candidate readiness and both durable receipts, then retire it. Before rollback,
verify the old survivor before stopping the candidate. Ambiguous receipt writes
retain both runtimes and pending evidence for inspection. Dataset, accepted
environment, original source time and installation-pending semantics are unchanged.
The existing dual-upstream edge prerequisite above also applies to this helper.

Evidence on 2026-09-28:

- Initial exported integration: **5 failed, 215 passed**, old helper signatures.
- Corrected exported integration: **252 passed** (replacement, activation, family).
- This operator branch: **275 passed** (replacement, activation, refresh), command:
  `python -B -m pytest tests/test_replace_staging_image.py tests/test_activate_staging_refresh.py tests/test_refresh_staging_catalog.py --no-cov -o addopts= -p no:cacheprovider -q`.
- Ruff check and format check pass for both new files. Tests cover both port
  directions, unsafe bindings, readiness rollback, interruption and failures at
  each durable receipt. Independent `deferred_export_review`: approved, no blocker.

The exported conflict resolution preserves the warm activation implementation
AND runtime's existing separation of acquisition/producer code pins. Keep that
separation when the real branch integration is authorized. Private export:
`Temp/nla-delivery-compatibility-20260928`; it is not a Git worktree or a release.
No native rollout claimed for this fix. Installed operator remains `881b9ca`;
its scheduled refresh path does not call this manual code-only replacement helper.
GitHub push/merge/CI hold and pending scheduled operational acceptance remain.
