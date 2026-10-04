# WS-09C — Package the exact verified projection

Issue #67, under #13. Branch `agent/staging-single-build`, parent `fbe3cfc` (#66).

## Change and boundaries

The audit found that staging packaging built a projection, proved it, deleted it,
then rebuilt an identical database. Packaging now asks the existing core verifier
to retain its successful projection and packages those exact bytes. It still
reopens both candidate and installed packages through the existing verifier.

The internal measurement result can carry the verified projection. This handle is
not serialized into the proof report. `retain_projection` is an explicit boolean,
false by default; the public standalone proof remains ephemeral. Failure in any
core check or final projection verification still removes the failed projection.
After successful handoff, the packager owns guarded cleanup if publication fails.

No source/query/record/proof schema is weakened or relabeled. All existing core
pagination, search, facet and sync checks execute unchanged. There is no new
activation, bypass, service, dependency, Shopify/PowerTools/theme write or deployment.
The separate sync-publication helper is unchanged; this PR is staging packaging only.

## Evidence

```text
python -m pytest tests/test_core_evidence.py tests/test_staging_generation.py -q -p no:cacheprovider --cov=nla_catalog_gateway.core_evidence --cov=scripts.package_staging_generation --cov-report=term-missing
```

122 PASS in 48.77s; 460 statements and 124 branches, both implementation modules
100% covered. Tests verify exactly one build, original file identity and proof
fingerprint after installation, failed-core cleanup with retention requested,
wrong/missing retained handles, post-proof byte changes, install failures and
existing path/identity/no-overwrite boundaries. No tests were skipped.

This proves one build instead of two, not a claimed percentage speedup of the
whole pipeline. No representative new real-package timing has been measured.
Independent reviewer `/root/source_codes_review`: APPROVE, with 22 focused tests
independently passed. An additional 233 tests passed in 201.14s:

```text
python -m pytest tests/test_sync_publication.py tests/test_staging_activation.py tests/test_runtime_bootstrap.py tests/test_runtime_server.py tests/test_runtime_api_integration.py tests/test_runtime_suggestions.py -q -p no:cacheprovider
```

This includes the 30,001-product signed HTTP traversal. Ruff check and format over
all 57 tracked Python files pass, and `python -m build --no-isolation` builds both
sdist and wheel. Staged repository preflight passes: 110 files, zero findings;
`git diff --cached --check` passes. Exact-head CI remains required before merge. Parent #66 CodeQL is
green; CI `35018638110` was cancelled at the 15-minute quality-job budget while
running the large search tests. This is not a green/skipped-test acceptance.

## Remaining objective

Known historical raw/reconciled/canonical temporary directories were rechecked
and contain no files. The recovered source CSVs and September 7 staging package
remain available, but are not a fresh schema-v2 accepted generation. Raw inputs
must be recovered or reacquired read-only before real packaging acceptance.
The current Shopify connection was verified and its validated, read-only
`bulkOperations` inventory returned no operations (complete page). That scope is
the connected app, not every app on the shop; no new Bulk has been started.
The `shopify-admin` skill required documentation search and query validation;
both script and connector validation passed before execution.
Printed-code completeness, images, durable updates, cursor retention, actual
staging, clone integration and real end-to-end verification remain open.

Rollback: revert this code change; existing package/proof formats are unchanged.
