# WS-11A — Complete scale proofs without coverage tracing (#76)

## Scope

Base: `d2ae142334069abc2a0b305a014ca0682651ff3a` (draft PR #75).
Branch: `agent/qa-traversal-coverage`. This delivery only changes instrumentation
for two existing test functions, representing three complete synthetic traversals.

The plain traversal retains all 30,005 products. The SKU and collector-code cases
retain 30,001 products each. Every assertion, including full ordered-ID equality,
boundary positions, duplicate/gap checks and query-plan checks, is unchanged.
`pytest.mark.no_cover` pauses pytest-cov tracing; it does not skip the test.
The existing large signed-HTTP traversal already follows this pattern.

No application code, workflow, timeout, permission, coverage exclusion, dataset
or assertion is changed. The 100% application/scripts line and branch gate stays
mandatory. This is separate from the workflow-budget proposal in #68.

## Measured baseline

On the unchanged base, the full 2,396-test suite passed in 2,711.07 seconds with
100% line/branch coverage. These three tests contributed 1,754.32 seconds:
569.23 seconds plain, 572.62 seconds SKU, 612.47 seconds collector.
An unchanged-code diagnostic without coverage passed all three in 241.87 seconds
(77.80 / 78.13 / 85.56 seconds). This indicates instrumentation cost, not an
application-load benchmark or a guarantee about hosted CI duration.

## Acceptance and reproduction

Run from the isolated candidate, using the project's declared dependencies:

```text
python -m ruff check .
python -m ruff format --check .
python -B -m pytest --cov=nla_catalog_gateway --cov=scripts --cov-report=term-missing --durations=12 -q
python scripts/preflight_repo.py
python -m build
```

The complete suite must still execute all existing 2,396 cases, with no skipped
or deselected tests, and retain 100% line/branch coverage. Any uncovered path must
receive a focused test, not an exclusion or a lower threshold. Keep coverage files
and pytest temporary artifacts outside Git. Exact-head Python 3.12/3.13 CI and
independent review remain required before merge; baseline results do not certify
this candidate. Record candidate execution results in the PR and current status.

## Risk and rollback

The risk is losing coverage contributed uniquely by a scale proof; the unchanged
full coverage gate detects it. Reverting the two annotations restores tracing.
This change neither deploys nor activates a catalog and cannot close clone E2E,
durable synchronization, restart continuity or the overall catalog objective.
