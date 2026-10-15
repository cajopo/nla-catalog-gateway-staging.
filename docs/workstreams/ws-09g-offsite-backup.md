# WS-09G — Encrypted offsite recovery checkpoints (#13)

The offsite job captures the installed NLA service into a private local checkpoint,
then uploads that checkpoint to the existing encrypted restic repository in the
owner-authorized Backblaze bucket. A successful transport receipt does not by
itself establish that the service can be restored or that an RPO/RTO is met.

## Delivery and rollout status

Implementation is being validated on `agent/offsite-backup-13`, based on
`90f4f49bf2094fa2af51dff3a998b82054d93c76`. This document is not a deployment receipt.
No backup service, timer or credential installation is implied by the presence of
the templates. Independent code review and a native Linux synthetic capture proof
have passed. Systemd execution, a fresh complete cloud snapshot and an isolated
application recovery exercise remain rollout gates.

The earlier October 15 encrypted pilot uploaded and recovered the October 3
catalog/ledger archive with an identical hash. It established the S3/restic
transport contract; its fixed input must not be scheduled as a current backup.

Validation on October 15: 46 checkpoint tests and 59 transport tests passed with
100% statement/branch coverage of their respective modules. Ruff check/format
passed. The package built with the bundled complete Python 3.12.14 runtime;
the older MySQL-derived Windows Python could not build an isolated environment
with SSL. This environment failure was retained, not bypassed by disabling TLS.

The native Python 3.12 proof used 67,195 bytes of synthetic fixtures in new private
directories. Both real nonblocking lock-contention cases, ownership/modes,
online WAL backup/reopen, source/hash invariance, symlink/FIFO rejection, deadline
and disk guards passed. It completed in 0.276 seconds and removed its own fixture
and upload directories. Docker/service responses and image export were synthetic;
the proof did not read or change production data, locks, services or credentials.
It does not establish systemd execution, a real image export or live recovery.

The independently reviewed checkpoint module SHA-256 was
`a8a07d57fd8f958dfb727c0b092f1e66d914e14a48970881bff1f1e4da4f92bc`.
Private evidence is retained under
`output/nla-recovery/20260930/backup-automation-20261015/native-proof/`;
the result is `native_proof_wrapper_v3.result.json`. The wrapper/helper and their
review pins are retained alongside it. Full repository CI is recorded in the PR;
the focused and synthetic checks alone do not replace that gate.

## Capture boundary

`scripts/backup_checkpoint.py` accepts a reviewed private inventory. It captures:

- The activation pointer and both immutable current/previous catalog generations,
  with their manifests, proofs and projection databases.
- A SQLite online backup of the importer ledger, with `quick_check`.
- The reference bundle selected by the current refresh configuration, including
  its expected hashes.
- Explicitly selected current configuration, credentials, TLS material, terminal
  receipts, service/timer definitions and operator launchers.
- Pinned installed source files, including any separately recorded hotfix, and
  Docker image exports selected by immutable image IDs.

The private deployment inventory is part of the recovery contract. It must be
updated when installed sources, images, unit schedules or required configuration
paths change. Dynamic configuration files are individually allowlisted and must
be stable across capture. Capturing an arbitrary directory such as all of
`/opt/nla-staging/operator` is not an acceptable substitute.

The destination is a new root-only directory. Source ownership, permissions,
file identity, hashes and symlink/hard-link boundaries are checked. Original
UID/mode metadata is recorded for recovery; private staging files are root-owned
and mode 0600. No checkpoint, credential, live configuration or generated catalog
belongs in Git.

## Coordination and resources

The capture acquires both existing pipeline locks without waiting, market first,
and checks service state and pending markers. A busy pipeline causes a skip. The
backup never starts, stops, restarts or refreshes either pipeline.

The installed pipeline locks are nonblocking: holding one when its timer fires
could make that pipeline fail. Capture therefore has a bounded deadline and a
guard interval before the known 02/03/14/15 UTC schedule. Changes to those unit
definitions require review of the backup configuration and schedule guard.
Locks are released before any cloud transfer or repository check.

Capture preserves a 6 GiB free-space reserve, including copy/export requirements.
The systemd template restricts CPU, memory, I/O priority and execution time.
It grants write access to the private backup state and existing lock files;
application sources and state remain read-only in the backup process namespace.
The proposed daily timer is 01:00 UTC with no persistent catch-up. A skipped day
is not a fresh backup and must not advance the last successful receipt.

## Transport and evidence

`scripts/backup_offsite.py` uses the already initialized repository:

```text
s3:https://s3.eu-central-003.backblazeb2.com/nla-catalog/nla/restic-v1
```

The verified Linux amd64 restic 0.19.1 binary has SHA-256:

```text
20d4142678d0d95ec11a4759def1b73fd9190abc9ca19e4b62d067c0b387e639
```

Credentials and the existing repository password come from root-only files.
The child environment is constructed explicitly. Raw provider errors, credentials
and arbitrary stderr are not copied to logs. Neither initialization nor cloud
deletion, `forget`, `prune`, unlock or bucket lifecycle changes are part of this job.

Every successful transfer is bound to a full snapshot ID, its path, host and job
tag. Exit code 3 (partial backup) is a failure. A receipt distinguishes metadata
integrity checks from `check --read-data`; only the latter reads all stored packs.
Neither check substitutes for application recovery.

Receipts have unique job identities and are durably published. Failure or a busy
skip never overwrites the previous successful receipt. Failed or interrupted
staging is retained for inspection; the next attempt refuses to pile up another
checkpoint. Completed staging is removed only after validating the exact expected
private files and their hashes. This removes the job's own copies, not catalog
generations, source data, evidence or cloud snapshots.

## Recovery and operator intervention

Preserve the snapshot ID, checkpoint manifest and transport receipt together.
Keep a separately recoverable repository password: Windows DPAPI tied to one PC
is not sufficient independent key custody. Do not reinitialize the repository or
replace its password when recovering access.

For an isolated drill, restore the exact snapshot subtree into a new private
directory with `--overwrite never --verify`. Check manifest hashes and SQLite
integrity before using restored files. Apply recorded ownership and immutable
modes only inside that new directory. Load the pinned image exports and start an
isolated runtime with no Shopify writer, no production mounts, no public ports
and no pipeline timers. Verify current and previous catalog readiness and record
elapsed time, source timestamp, image/code versions and any recovery gaps.

A retained failed job requires inspection of its receipt, completion manifest,
cloud snapshot state and exact local paths before retry or removal. A lost SSH
session or observation timeout does not establish that the service failed: check
the existing invocation and durable receipt instead of launching another job.
Do not remove pipeline pending markers to make a backup pass.

Cloud retention remains an owner policy decision. No automatic deletion is
enabled. The offsite job is also not an alert delivery channel; destination,
incident ownership and authorized delivery testing are separate operational work.

## Official contracts

Reviewed October 15, 2026:

- [Restic S3 repository configuration](https://restic.readthedocs.io/en/stable/030_preparing_a_new_repo.html),
  [backup](https://restic.readthedocs.io/en/stable/040_backup.html),
  [integrity checks](https://restic.readthedocs.io/en/stable/045_working_with_repos.html),
  [restore](https://restic.readthedocs.io/en/stable/050_restore.html) and
  [scripting](https://restic.readthedocs.io/en/stable/075_scripting.html).
- [Backblaze integration](https://www.backblaze.com/docs/cloud-storage-integrate-restic-with-backblaze-b2).
- Python 3.12 [SQLite backup](https://docs.python.org/3.12/library/sqlite3.html#sqlite3.Connection.backup),
  [flock](https://docs.python.org/3.12/library/fcntl.html#fcntl.flock) and
  [atomic file operations](https://docs.python.org/3.12/library/os.html).
- Docker [image save](https://docs.docker.com/reference/cli/docker/image/save/) and
  [inspect](https://docs.docker.com/reference/cli/docker/inspect/).
- systemd v255 [execution sandbox](https://github.com/systemd/systemd/blob/v255/man/systemd.exec.xml),
  [resource limits](https://github.com/systemd/systemd/blob/v255/man/systemd.resource-control.xml) and
  [timers](https://github.com/systemd/systemd/blob/v255/man/systemd.timer.xml).
