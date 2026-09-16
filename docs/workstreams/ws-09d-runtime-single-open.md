# WS-09D — Single verified reopen during runtime binding (#72)

## Scope

Issue: <https://github.com/cajopo/nla-catalog-gateway-staging./issues/72>.
Branch `agent/runtime-single-open`, parent `3008e05938219bcdd1cf9e3d3f65b7134ae22ca3`.
This local candidate reduces duplicate startup work; it does not claim to fix a
request deadline failure, deploy staging, or complete the storefront objective.

`_assemble_evidence_bound_generation` creates an `AtomicCatalogActivation` and uses
its fully verified selected projection for the existing manifest, fingerprint and
six-way evidence bindings, then gives that same activation to the paginator.
The expected dataset generation is checked explicitly before the candidate is returned.
Public activation still fully verifies its input. Record validation, evidence/code
pins, query semantics, request limits, and failure-before-install behavior remain.
There is no new trusted shortcut, cache, service, or public configuration flag.

## Current executable evidence

- Before the implementation edit, the new portable/reconciled regression failed in
  both cases because binding reopened the projection twice, not once.
- After the edit, both count/identity tests pass for construction and activation.
  Four existing portable, tampering and malformed-binding checks also pass:
  `6 passed, 33 deselected` in the focused development run.
- Independent QA passes the six focused tests and rechecks both new parameters after
  the added wrong-generation rejection/unchanged-active-lease assertions. Independent
  static review APPROVE covers the implementation and final test delta.
- All-repository Ruff check and formatting pass (90 files). Repository preflight
  passes over 112 tracked files; sdist and wheel build with `--no-isolation` passes.
- Broader runtime, retained-cursor, publication and activation verification passes:
  259 tests in 306.24 s, including the signed 30,001-product traversal, no deselection
  or skips. Runtime module coverage is 100%: 1,146 statements and 358 branches.
  This is changed-module coverage, not a new full-repository coverage result.
- These are synthetic tests, not a measured real-catalog startup improvement.
  The original real service diagnostic finished on unchanged source with a 503 and
  a long observed GC pause. This candidate does not address request memory residency.
  No accepted real evidence report has been generated or relabeled for this candidate.

Focused reproduction (set this worktree's `src` on `PYTHONPATH`):

```text
python -B -m pytest tests/test_runtime_api_integration.py -k "binding_reuses_one or portable_activation_rejects or portable_staging_generation_reaches or evidence_generation_constructor_rejects or generation_construction_rejects" -q --basetemp=<fresh-external-test-directory>
```

Broader reproduction (also set `COVERAGE_FILE` to an external temporary path):

```text
python -B -m pytest tests/test_cursor_retention.py tests/test_runtime_api.py tests/test_runtime_api_integration.py tests/test_runtime_suggestions.py tests/test_sync_publication.py tests/test_staging_activation.py --cov=nla_catalog_gateway.runtime_api --cov-report=term-missing -q --basetemp=<fresh-external-test-directory>
```

Test fixtures must be outside every repository root: package verification deliberately
rejects catalog artifacts inside the source repository. The initial in-repository
test-directory setup was rejected, then corrected; that was not a runtime regression.

## Remaining gates and rollback

Complete foundation checks, final-SHA review binding, exact-head CI, and real startup
measurement remain required before delivery. Short development runs do not waive
the large traversal tests. No push, PR, merge, provider, Shopify, PowerTools or theme
write is claimed. Rollback is the prior reviewed application release with its existing
artifact/verifier pins; this change never modifies a catalog package in place.
