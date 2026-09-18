# WS-07 — Linux offline Bulk reconciliation (#87)

## Scope

Branch `agent/linux-bulk-reconciliation`, base `baf0316` (#86). The existing
`run_reconciliation` now accepts downloaded products/variants JSONL on Linux and
publishes the same seven-file reconciled bundle. Parsers, approved queries,
expectations, taxonomy, identity checks, canonical-name audit and output schema
are shared with Windows. No new service or data format is introduced.

Inputs are pinned through directory descriptors with no symbolic-link traversal.
Regular single-link files are checked against their path and descriptor, including
change time. Bounded control documents are frozen in memory. Data stays outside
the repository; approved query files may remain inside it. Input paths use native
POSIX semantics (NUL rejected; literal trailing dots/spaces/colons allowed), including
the GitHub checkout name ending with a dot. Output paths retain the existing bundle
reader's stricter component contract so success never creates an unreadable bundle.

The output parent must belong to the effective operator UID and must not be
group/other writable. A private staging directory holds exclusive-created files,
sealed to `0444`; its directory is sealed to `0555`. The complete shape, identity,
size and hashes are verified. Parent and staging identities are rechecked before
`renameat2(RENAME_NOREPLACE)`, followed by parent directory sync and verification
of the published directory. Existing destinations are never overwritten. Platforms
without the required atomic operation fail closed; there is no unsafe fallback.

Cleanup uses only recorded artifacts and observed identities. Unexpected files or
replacement directories are preserved. A failure before ownership is established
can leave a private incomplete staging directory; it is never reported as success
and requires deliberate operator inspection, not wildcard deletion. Mode bits are
not a lock against root or a hostile process with the same UID.

## Native verification — 2026-09-18

Windows shared-runner regression: 107 passed in 21.49 seconds. Final combined
Windows reconciler/reader regression: 330 passed in 27.19 seconds. Ruff check and
format check pass for all 105 Python files.
First isolated Linux run: 122 passed, 7 failed; no target was published by the
failed cases. Directory enumeration was changed to use an independent descriptor
relative to the pinned directory, avoiding inherited enumeration offsets. Repeated
verification is an explicit regression test. Intermediate runs then exposed two
test assumptions: Linux entrypoint success was not expected, and the integrated
catalog proof requires searchable cards in all four games. The test fixture now
contains four distinct products/source identities with the same publication ID;
no production gate was relaxed.

Initial successful native container `nla-reconcile-v5`: **195 passed in 4.22s**, no skips or
warnings. Reconciler coverage: **1261 statements / 334 branches, 100%**. Python
3.13.15, non-root UID10001, no network, read-only source/root, private temporary
test data, 1 CPU / 1 GiB limit. Archive SHA256:
`eebc2d40a49fe935afc09efd50475e0034d2d72b03041c405c8f5d23f4561e22`.

Full CI at initial head `09d84cc` caught a genuine Linux path compatibility bug:
query files inside the real GitHub checkout name ending in `.` were rejected by
an inherited Windows component restriction. No publication occurred. The targeted
fix uses native POSIX validation for inputs; an independent review also required
preserving reader-compatible restrictions on output paths. Both have dedicated
real-filesystem regressions. Native container `nla-reconcile-v7`, source mounted
at `/work/repository.` rather than `/work`, passed **201 tests in 4.40s** with
**100% of 1261 statements / 334 branches**, no skips/warnings. Same isolation and
resource limits. Archive SHA256:
`43b29ffe68a1b91d022da60d41f161dc1f06acd18bed98076892ff860efa4559`.
The command below applies with `/work` replaced by `/work/repository.` for v7.
POSIX reference: https://man7.org/linux/man-pages/man7/pathname.7.html.

Command:
```sh
python -m pytest -c /work/pyproject.toml \
  /work/tests/test_reconcile_split_snapshot.py \
  /work/tests/test_reconcile_split_snapshot_linux.py \
  /work/tests/test_reconcile_split_snapshot_linux_units.py \
  -q --tb=short -o cache_dir=/tmp/pytest-cache \
  --basetemp=/tmp/nla-reconcile-pytest \
  --cov=scripts.reconcile_split_snapshot --cov-config=/work/pyproject.toml \
  --cov-report=term-missing --cov-fail-under=100
```

Independent static review PASS, no outstanding Blocker/High/Medium findings.
Repository-wide CI and exact-head review binding remain mandatory before merge.

Native tests cover raw fixture → reconciliation → production bundle reader →
staging package → runtime search, including sold-out visibility, partial-name and
printed-code matching, suggestions and game isolation. Failure cases cover links,
special files, input mutation, invalid evidence, output collisions, interrupted
writes, swapped artifacts/directories and safe cleanup.

## Remaining work

This does not complete #11. Shopify acquisition, scheduled/incremental orchestration,
enrichment freshness, activation persistence and restart recovery remain separate.
No real full-catalog proof is repeated, no running service is redeployed, and no
Shopify/PowerTools/theme data is modified. Actual Shopify App Proxy configuration
and its signed end-to-end proof remain outside this offline slice.
