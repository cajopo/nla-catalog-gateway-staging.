# WS-07F — Incremental SQL generation and runtime publication (#83 / #11)

## Real gap closed by this change

The existing sync core produced event-derived GenerationViews, but the SQL
manifest only described full reconciliations. Casting a changed view back to its
base snapshot would invent source evidence. This change explicitly represents
incremental lineage and connects it through the existing proof, packaging and
evidence-bound serving code. No new service, queue, search engine or dependency.

`DatasetManifestV1` adds an optional `incrementalLineage` object. Baseline bytes
and identities are unchanged when it is absent. When present, it contains the
base and parent generation, configured shop, source cut, event count and lineage
hash. The generation descriptor is exactly the existing SyncCore incremental
descriptor, not a second identity system. Removing/changing lineage without the
corresponding identity is rejected. Future source cuts are rejected.

The snapshot/query digests continue to identify the **base export**, not a new
Bulk operation. Counts and record hash describe the derived catalog, carrying
forward the base's unchanged excluded population. These counts are not claimed
to be a fresh independent Shopify-wide count. Full reconciliation still repairs
lost events, unknown products and drift.

`SyncCore.publication_snapshot(expected_base)` compares the exact validated base,
validates the committed internal generation, freezes one view and constructs a
manifest whose counts, content hash and identity match its records. An initial
unadvanced view or wrong base is rejected. It does not acknowledge an inbox row.

## Executable path

The existing `run_packaging(..., incremental_core=core)` accepts the normal pinned
reconciled bundle plus its current SyncCore. It uses the existing independent
pagination/search/suggestion/facet checks against the changed records, verifies
that the core has not advanced during the proof, and produces the same immutable
package format. Proof provenance hashes the verified base summary and full derived
manifest. Existing fingerprint, package reopen, output ownership and cleanup
checks remain in effect. Its CLI remains baseline-only; no worker is enabled.

`publish_incremental_generation(core, reopened_package, backend=..., cursor_codec=...)`
requires that exact committed view to still be current and checks its lineage and
records. A new conditional staging activation protects against intervening backend
activations (including A→B→A). The existing backend retains issued old cursors and
atomically changes the in-process serving generation only after full verification.

The package exists durably, but this runtime switch is **in-process**. This change
does not coordinate the durable active pointer with runtime activation, recover a
SyncCore/event-order state after restart, acknowledge the durable inbox, re-fetch
Shopify records, schedule reconciliation or register a subscription. Those links
remain required before automatic sync/#11 can be accepted. Do not complete inbox
events merely because this API returned a generation. No live Shopify, PowerTools,
MAIN/clone, provider or main-branch change is made here.

## Verification and rollback

The new synthetic integration tests use real baseline bundles, core validation,
SQLite packaging/reopen, evidence-bound backend leases and capability checks.
They test an update reaching public price/stock output, sold-out visibility,
printed-code/name search, cross-game isolation and an old cursor surviving
activation; create/delete/unpublish/inventory changes are also exercised.
Negative tests cover malformed lineage, tampering, stale core/package/base,
concurrent activation, cross-shop activation and proof-time advancement.

The unchanged baseline regression suite first passed296 tests /34.66s.
Initial new-fixture failures were test setup mistakes (missing four-game proof
coverage, too-short synthetic cursor material, missing request DTO arguments and
using the raw-product stock field on a public item). They were corrected without
weakening production gates. A broader diagnostic run then passed383 tests /341.28s,
but its selected-module coverage gate failed99.45%: two new negative paths were
missing, existing metadata tests were outside the selection, and one source file
had changed after test-process import. It is not final-SHA coverage evidence.
Both new negative cases are added, and creation now proves a new single card is
searchable by printed code. A frozen focused run covers the publication module;
full application/scripts coverage is required in exact-head CI. Ruff/format,
preflight121 before staging and sdist/wheel build PASS. Final focused results,
independent review and exact-head full CI must be recorded before merge. No accepted heavy
real-catalog proof is rerun for these synthetic integration checks.

Rollback uses the retained baseline package with baseline-compatible code. Older
code rejects the new optional lineage field, so do not start old code on a derived
package: restore the prior package/pointer as well. No packages or receipts are
deleted by this API. Production sizing/freshness is not established by tiny fixtures;
the proof still rebuilds a whole projection and requires coalesced publication.
