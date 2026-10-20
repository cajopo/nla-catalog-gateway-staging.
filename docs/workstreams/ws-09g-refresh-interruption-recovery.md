ï»¿# WS-09: recover an interrupted catalog promotion (#13)

The 1 October 2026 OpenSSL unattended upgrade invoked `needrestart`, which
restarted `nla-market-catalog.service` while its nested catalog activation was
waiting for Docker. systemd killed the coordinator at 04:29 UTC. Docker finished
promotion at 04:30:30 UTC, leaving the new pointer installed, the candidate
container created but never started, and the previous runtime serving.

## Prevention

Install `ops/needrestart/90-nla-batch-jobs.conf` as
`/etc/needrestart/conf.d/90-nla-batch-jobs.conf`. It excludes only the finite NLA
market and refresh jobs from automatic service restarts. Security package updates
and restart defaults for other services remain enabled. The next scheduled job
starts a new process using updated libraries. Do not restart a running job to
apply this snippet. [Ubuntu's documented service restart configuration](https://ubuntu.com/server/docs/how-to/software/automatic-updates/#service-restarts)
supports these exact `override_rc` entries.

The private installer passed an independent review and a Perl evaluation proving
that both exclusions preserve the SSH restart default. It installed the snippet
on 3 October; installed SHA256:
`6c59200c44293b3f4438910d62300eb17afd92ad460f5c97653c7376648f07fc`.

## Recovery deployment boundary

Install the reviewed recovery package in the separate directory
`/opt/nla-staging/recovery-20261003`, containing only:

- `scripts/recover_staging_refresh.py`
- `scripts/activate_staging_refresh.py`
- `scripts/refresh_staging_catalog.py`
- the private, independently inspected plan and execution wrapper.

Record SHA256 for each of the three Python files in the private plan and compare
it with the local reviewed source before execution. Run from this new directory.
Do not overwrite `/opt/nla-staging/refresh-881b9ca`, its source archive or the
original refresh configuration. Do not retarget the normal services or timers.
The original producer remains `881b9ca08dd2bc3ba9875b10d59ccb1a825a9246`;
recovery-source hashes attest a separate operation, not a new capture producer.

`recover_staging_refresh` never calls ordinary `configuration()`, which validates
an installed producer tree against its matching archive. Running a modified tree
against the old archive would fail that guard on the next ordinary refresh.

## Narrow recovery contract

Default execution is a read-only preflight. An explicit private plan binds the
original run, capture/checkpoint/verifier receipts, environment-file hashes,
original config/archive, pointer and predecessor manifests, operator hashes, and
four exact container IDs with their private configuration fingerprints.
Environment values and credentials stay on the VPS.

Only a successful selector and a never-started candidate are accepted. The old
runtime must still be ready. Recovery reuses that candidate, warms it on the
alternate port, performs the existing handoff, and retires the old runtime after
readiness checks. A failure requires inspection and retains named resources;
there is no automatic rollback, new container, export or Shopify operation in
this narrow command. Ordinary activation retains its existing rollback behavior.

Run the command under the importer lock as well as its own catalog pipeline lock,
with both normal service cgroups empty. Write completed/last-success receipts only
after handoff; clear the original pending marker last. The receipt retains the
original source timestamp. Successful recovery can still be stale: a new ordinary
read-only refresh must subsequently validate current freshness.

Retention is explicitly deferred during recovery. Preserve the current/previous
generations, capture, importer ledger, reference and incident evidence. Resolve
the stopped market marker only after independently reconciling batch/publication
receipts with the unchanged ledger and recovered catalog receipt. Record
`stopped_inspected`, not a fabricated successful market cycle.

## Validation and execution evidence

The targeted suite reproduces interruption after the selector changes the pointer
and before the coordinator records promotion. It verifies continuation using the
same candidate and fail-closed behavior for changed receipts, resources, pointer,
configuration and later-stage ambiguity. On head `7ab94d3`, GitHub CI passed on
Python 3.12 and 3.13 (3,885 tests and 100% coverage each), together with CodeQL.
The independently reviewed recovery completed at 07:29:11 UTC on 3 October.
Its original source timestamp remains 1 October; recovery alone does not establish
current freshness. See the maintained [incident record](../evidence/INCIDENT-2026-10-03.md)
for the separate ordinary refresh, functional checks and retention outcome.
Private artifacts belong in the ignored recovery evidence folder, never in Git.

The transient recovery unit also received an exact-name needrestart exclusion in
`91-nla-incident-20261003.conf` before execution, independently reviewed and checked
with Perl. This one-off guard did not replace or broaden the two normal-job
exclusions; its hash and execution evidence are recorded in the incident.
