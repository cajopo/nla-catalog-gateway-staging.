# WS-09E — Detached serving records (#74)

Issue: <https://github.com/cajopo/nla-catalog-gateway-staging./issues/74>.
Branch `agent/runtime-detached-records`, parent #73
`e86f8a5e0ff92fdef462ca63b7ce2be30446052a`.

## Scope and trust boundary

The serving generation no longer retains the verified import object or complete
source-record tuple. It keeps the verified projection, a small owned manifest,
accepted evidence, six-way binding, cursor codec/paginator and clock. Import,
reconciliation, package loading, core proof and sync DTOs are unchanged.

The owned manifest is canonically copied before validation. All existing source,
record accounting, manifest, file fingerprint, expected-generation and evidence/code
checks still precede candidate installation. Requests continue to verify actual file
identity, projection/manifest/evidence bindings and cursor generation. This is not a
trusted unchecked constructor or a new cache.

Validation now establishes a detached serving snapshot. Changing discarded caller
inputs afterwards cannot invalidate or alter that snapshot; trying to activate those
now-malformed inputs still fails before replacing the active generation. Runtime-owned
manifest/evidence/projection tampering still fails closed. Retained cursor generations
keep their files and small serving state, not their original import graph.

## Evidence and limitations

- The new portable/reconciled residency regressions fail before the code change with
  `serving state retains source records` in both cases.
- The regression inspects owned object references, including function closures and
  positional/keyword defaults but excluding module globals/classes. Negative controls
  detect all three function-capture forms. It covers active and retained generations and
  leases, key rotation, continuation of an old cursor, caller-input mutation, rejected
  reactivation and an unchanged active lease.
- Existing tests tied to the removed import-object fields now check the serving
  manifest, all six binding values and projection fingerprint. Constructor-side
  malformed-source and tampering tests remain.
- Eight development regressions pass (5.69 s). Independent review identified missing
  default-argument captures in the memory probe; these and negative controls are fixed.
  Independent re-review APPROVE has no residual finding.
- Independent QA passes all nine selected tests in 6.97 s (33 deselected), including
  the probe negative controls. All-repository Ruff/check-format passes (91 files).
- Preflight passes over 114 tracked files with zero failures; the source distribution
  and wheel build successfully. These checks do not substitute for the pending suite.
- The private real-service harness now precomputes the same 20 acceptance cases into
  builtin-only values and releases the caller's source graph before requests. Independent
  review approves the oracle/provenance changes; a fresh synthetic helper smoke passes
  on this candidate. Runtime SHA/module origin and evidence-producer SHA are distinct
  pins; reusing the existing package requires unchanged verifier/projection code.
- The broader six-file runtime/retention/publication/activation suite passes all
  262 tests in 311.23 s, including signed HTTP traversal through 30,001 products.
  Runtime module line/branch coverage is 100% (1,131 statements, 352 branches),
  with no skips or deselection. Full candidate foundation coverage, final-SHA review
  and exact-head CI remain required. No measured real memory reduction or resolved
  HTTP timeout is claimed from these synthetic tests.
- Parent `e86f8a5` full local suite completed: 2,393 tests in 2,734.10 s, 100%
  application/scripts line/branch coverage (12,040 statements, 4,048 branches), no
  skips or deselection. This is parent evidence, not the candidate's full-suite result.
  The six-file broader candidate suite ran only after that process exited.

Focused reproduction, with this worktree's `src` and root on `PYTHONPATH`:

```text
python -B -m pytest tests/test_runtime_api_integration.py -k "serving_and_retained or residency_probe or current_evidence_binding or portable_staging_generation_reaches or portable_activation_rejects or generation_construction_rejects or evidence_generation_constructor_rejects" -q -p no:cacheprovider --basetemp=<fresh-external-test-directory>
```

Broader reproduction (also set `COVERAGE_FILE` outside the repository):

```text
python -B -m pytest tests/test_cursor_retention.py tests/test_runtime_api.py tests/test_runtime_api_integration.py tests/test_runtime_suggestions.py tests/test_sync_publication.py tests/test_staging_activation.py --cov=nla_catalog_gateway.runtime_api --cov-report=term-missing -q --basetemp=<fresh-external-test-directory>
```

Real-service verification must first stop retaining the oracle's complete source DTO
graph in the same serving lifetime/process. No GC settings, request deadlines, query
semantics, source data or acceptance gates are changed. No Shopify, PowerTools, theme,
provider, deployment, package relabeling, push, PR or merge for this candidate.

Rollback: use the prior reviewed application with its corresponding artifact/verifier
pins. No catalog package is modified or deleted by this change.
