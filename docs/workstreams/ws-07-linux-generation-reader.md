# WS-07 — Linux reconciled-generation reader (#85)

## Scope

Branch `agent/linux-generation-reader`, based on reviewed `5183191` (#84).
The existing generation reader used only Win32 handles. Linux could consume an
already-built staging package but could not prepare one from a reconciled bundle.
This change adds a Linux implementation of the same private filesystem boundary.
It does not change the format, trust root, record verification or Windows backend.

Linux input must be an absolute, external bundle directory with exactly the seven
expected files. The operator must seal files to mode `0444` and the directory to
`0555` before opening. Ancestor directories are walked using directory descriptors
without following symbolic links; regular files must have one link. File reads are
nonblocking to reject a raced FIFO safely. Identity, size, permissions, modification
and change times are checked against pinned descriptors and current paths. The
existing external summary digest, two-pass artifact hashing and semantic checks
remain mandatory. Read-only mode is not a lock against the owner/root; mutation
detected during verification fails closed. Records returned are detached in memory.

## Verification — 2026-09-18

Windows shared-reader regression: 223 passed in 19.33s. Independent targeted
Windows unsupported-platform/incremental regression: 2 passed in 5.85s.

First Linux run on the existing Aruba VPS: Python 3.13.15, non-root UID10001,
isolated container `nla-reader-v1`, no network, read-only code/root, synthetic data
in private temporary storage, 1 CPU/1 GiB limit. 268 passed in 39.36s. Source archive
SHA256 `debed7c9917c09d8a1093526c41cf01855dbafa453a46d55c17747892b992a0b`.
This run measured 99% statement coverage of the reader, not final branch coverage.
Pytest cache warning was caused by the read-only source mount, not a test failure.
The initial archive command also named a nonexistent `fixtures` directory; actual
fixtures are under `tests` and were included. Corrected archive scope is required
for the final run. No full-catalog proof or Shopify operation was repeated.

Independent static review identified an interruption gap before registering an
opened descriptor. An owned-descriptor context with `finally` cleanup fixes it;
the final focused run includes interruption regressions.

Final Linux container `nla-reader-v2`, same isolated limits, exited0:
282 passed in39.48s, reader1127 statements/356 branches,100% coverage, zero skips
or warnings. Corrected complete source archive SHA256
`2a4f195ce7dbffe0dc4a3ac0e7f27c3425d200e089fbd74e5129bfd7650904ff`.
Command: `python -m pytest -c /work/pyproject.toml
/work/tests/test_generation_bundle.py /work/tests/test_generation_bundle_linux.py
/work/tests/test_incremental_publication.py --basetemp=/tmp/nla-reader-pytest
-o cache_dir=/tmp/pytest-cache -q --cov=nla_catalog_gateway.generation_bundle
--cov-config=/work/pyproject.toml --cov-report=term-missing --cov-fail-under=100`.
Ruff check/format and preflight123 PASS. Independent static re-review PASS: the
descriptor ownership finding is resolved, no additional findings. Repository-wide
CI and exact-head final review remain required before merge; no runtime deployment.

## Remaining #11 boundaries

This does NOT implement Shopify transport, a refresh worker, Linux raw-snapshot
reconciliation, refreshed name/code enrichment, persisted runtime coordination or
restart recovery. It does not claim automatic import propagation. Credentials,
Shopify/PowerTools products and the running catalog container remain untouched.
