# WS-07 — Idempotent synchronization core (issue #11)

## Outcome and boundary

This slice implements a framework-independent, in-memory reference core for a read-only
catalog projection. It accepts immutable raw-event envelopes, delegates payload validation
and projection to injected adapters, validates a complete synthetic candidate, and atomically
switches the active generation. It contains no Shopify API call, HMAC verification, webhook
registration, Bulk execution, queue, database, HTTP endpoint, deployment, PowerTools change,
theme change, or production mutation.

The implementation is rooted in the canonical Data/Bulk and runtime contracts merged through
PR #30 and PR #31. An older issue-#11 comment names PR #23 and PR #26: #23 was a historical
draft and the repository's PR #26 is unrelated to either contract, so neither is treated as
the current integration boundary.

All executable evidence is synthetic. `NLA_DATA_ROOT MISSING` was observed for the upstream
contract work and no real product, price, inventory, webhook payload, snapshot, or signed URL
was read or checked in.

## Inbox, identity, and retries

`RawWebhookEnvelope` retains the exact non-empty payload bytes, computes their SHA-256, and
binds them to a canonical shop domain, webhook ID, topic, stable API version, and receipt time.
The configured dataset shop is exactly one canonical `{shop}.myshopify.com` label. Cross-shop
deliveries and reconciliation candidates fail before projection. The inbox key is the private
built-in tuple `(shopDomain, webhookId)`; public `WebhookKey` values are separately constructed,
tuple-backed values which cannot mutate dictionary/set hashing. An identical delivery is
idempotent even when its receipt timestamp differs; a reused key with a different topic, API
version, or payload hash is a conflict and requires reconciliation. Raw payloads are excluded
from representations and safe operational reports, whose keys never alias internal keys.

Ordinary per-event inbox processing is monotonic:

```text
received -> validated -> projected
                   \-> failed -> projected (bounded retry)
any non-terminal state -> reconcile_required
projected -> reconcile_required (conflicting reuse of the same key)
```

A successful, fully attested reconciliation is the only administrative resolution outside
that per-event transition graph. Covered `received`, `validated`, or `failed` entries advance to
`projected`; an already `projected` entry keeps its event projection history; and a covered
`reconcile_required` entry remains at that highest-rank state for conflict audit. Every covered
entry receives a separate `reconciliationGeneration` resolution marker, becomes terminal to
`process`, and is removed from pending/dead-letter readiness accounting only in the same atomic
generation swap. A later conflicting reuse clears that marker and reopens the pending decision.

Ordinary adapter, clock, candidate, and activation exceptions become fixed failure codes and
never render attacker-controlled exception text. `BaseException` is deliberately not
normalized. Retry attempts are bounded; exhausted failures appear in a payload-free dead-letter
report. Once validation succeeds, the inbox freezes a detached canonical
`ValidatedWebhookEvent` and its event-identity digest. Every later processing attempt and
reconciliation catch-up reuses those exact values; a stateful validator cannot redirect a retry
to a different Product, category, or source timestamp. The reference inbox is bounded by both
unique event count and total retained envelope
bytes. The retained-byte measure includes the encoded shop, webhook ID, topic, API version,
receipt timestamp and payload hash as well as the raw payload. Topic, timestamp, Product GID and
taxonomy-version fields have independent limits; a bounded Product GID remains exact decimal
text and is never converted to an integer. Exact retries do not consume the byte budget twice.
Retention, eviction, and a durable dedupe store are deployment/persistence decisions outside
this slice.

## Event categories and ordering

The minimal semantic topic map covers Product create, update, unpublish and delete plus
inventory-level change. The injected validator must return a `ValidatedWebhookEvent` bound to
the same shop, webhook ID and raw-payload hash and to a category allowed for the delivered
topic. Unknown topics and ambiguous semantic changes are never dropped; they enter the
reconciliation report.

Ordering is tracked per `(shopDomain, Product GID)`. A new event must be strictly later than
the active generation's source cut and also strictly later than the latest active Product/Variant
timestamp or the last incrementally applied event for that identity. An event at or before the
source cut is already subsumed by that source snapshot and follows the conservative terminal
`reconcile_required` path; it can never replay over the reconciled record. Equal or older events
likewise require reconciliation. Receipt, source, Product, Variant, generation and clock
timestamps all use a bounded known-offset RFC3339 subset; `-00:00` cannot enter an active
generation. Ordering failures are normalized into reconciliation rather than escaping with an
event stranded in `validated`. The complete projection is built from a detached copy, then the
active generation identity and event state are checked again during commit. Tests inject
conflicts and generation replacement during validation and activation to prove that the losing
candidate cannot become active.

## Candidate integrity and commercial fields

Every projector result is a non-empty tuple of canonical `CatalogProductRecordV1` values.
Product GIDs, handles, Variant GIDs, InventoryItem GIDs, paired PowerTools/sync source IDs, and
the taxonomy version are checked across the whole generation. Non-null paired source IDs are
globally unique, matching the Bulk contract. Create adds exactly its target, delete removes
exactly its target, and update/unpublish/inventory events retain the Product identity set and the
target Product's byte-identical `powerToolsSourceId` and `syncSourceId`. Source-identity repair is
therefore possible only through a fully attested reconciliation generation. Every
non-target Product must be byte-for-byte unchanged; unpublish must explicitly remove Online Store
publication. An inventory event may change inventory/tracking and timestamps but cannot overwrite
price or any other non-inventory material.

No synchronization transform invents a placeholder value. Tests preserve exact decimal price
text and signed inventory for sealed and accessory Products, including negative inventory, while
allowing an explicitly supplied placeholder single to remain zero-priced and out of stock. The
core cannot prove the target adapter's values against Shopify; that adapter must project the
authoritative target record without lossy numeric conversion, and the real staging gate remains
required.

## Classification and generation lineage

Product-type or tag changes can reclassify the target idempotently within the active taxonomy
version. A known classification enters its canonical game/family. An ambiguous classification
remains present as `unclassified` with a machine-readable reason; it is never discarded.
Generation views and readiness metrics expose the taxonomy rule version and exact unclassified
Product count. A taxonomy rule-version change requires a full reconciliation rather than an
incremental mixed-version generation.

Fresh bootstrap and every later full install accept only the in-memory
`ReconciledCatalogGenerationV1` produced by the split-snapshot reconciler. There is no legacy
`SourceSnapshotManifest`, independent source/manifest/record, `Path`, or raw-artifact bootstrap
route. Both entry points reuse the same deep-copying boundary, which requires the exact nested
`ReconciledSourceManifestV2`, canonical bytes, taxonomy report, records, and runtime manifest. It
canonically rebuilds both part manifests, verifies their shared capture
identity, distinct operations, overlapping bounded windows and approved query hashes, then
rebuilds the source V2 evidence, taxonomy accounting, runtime manifest and generation digest.
Every comparison is byte-exact. The adapter accepts no `Path` and reads no raw artifact; raw
snapshot validation remains the responsibility of the reconciler that created this in-memory
object. Hostile or mismatched values produce fixed value-free contract/operational failures
without a partial initialization or swap. The reconciled `captureCompletedAt` is used only as the
candidate freshness/source cut, never as evidence that an inbox delivery was covered. Each
incremental generation binds its
shop, monotonic source
high-watermark, base and parent generations, canonical catalog-content hash, taxonomy version,
event identity, cumulative event-lineage hash, and event count. Record/status/family/Variant/
source-ID and public-item counts are recomputed. Build time cannot move backwards. This
incremental descriptor does not fabricate a new source snapshot manifest; the validated runtime
manifest remains the full-reconciliation base.

## Atomic activation, rollback, and readiness

Candidate validation and the injected activation probe finish before one locked pointer-pair
swap. A failed validation/probe or a concurrent generation change leaves the active generation
unchanged. The pair retains exactly the prior active generation. Rollback swaps the pair back,
pauses incremental projection, marks readiness stale, and requires a full reconciliation before
projection resumes. A separate maximum-observed source/build watermark survives pointer rollback;
recovery must advance both, so rolling back cannot authorize an older snapshot to displace newer
commercial data. Reconciliation orchestration must first ask the core for a
`ReconciliationFence`, before starting either Bulk capture. The opaque, core-bound fence records
the active generation, monotonic delivery sequence, and issuance time. While it is active,
ordinary processing may validate and freeze deliveries but cannot advance the active generation;
readiness remains paused/stale. Entropy-provider `Exception` failures become a fixed value-free
operational error without replacing any registered fence; `BaseException` deliberately propagates.

Installation proves that both capture windows began at or after the registered fence. Deliveries
at or before the fence sequence are covered by that later full capture without consulting their
receipt/source timestamps. Every delivery after the fence must already be a successfully frozen
event; failed, conflicting, unsupported, or unprocessed deliveries reject the install and remain
unresolved. The core replays post-fence events by each key's first delivery sequence after the
fence, so a later duplicate cannot reorder two distinct events against the candidate. An event
already reflected by the snapshot is accepted only when projection is a byte-identical no-op;
newer events create validated incremental descendants. A final compare-and-swap checks the active
pair, registered fence, every replay entry, and the global delivery sequence. Any reception during
candidate validation, catch-up, activation, or commit rejects the attempt with no partial swap.
The displaced active generation remains available as rollback state, and rollback itself is
blocked while a reconciliation fence is active.

Metrics expose bound shop, dataset version/build time, source cut, taxonomy version, unclassified
count, latest received and projected times, source-cut lag/staleness, pause state,
unresolved/dead-letter counts, retained inbox bytes, delivery/dedupe/conflict/failure/reconciliation
counters, activations, rollbacks, and full reconciliation installs. They contain no raw payload,
product data, credentials, or signed URLs.

## Reproducible evidence and remaining real gate

Focused author evidence:

```text
pytest -o pythonpath=src tests/test_sync.py --cov=nla_catalog_gateway.sync \
  --cov-branch --cov-report=term-missing
145 passed; 1064/1064 statements and 266/266 branches covered (100%)
focused sync/reconciliation/bulk/runtime/taxonomy suite: 501 passed
full suite (`nla_catalog_gateway` + `scripts`): 1352 passed;
  6150/6150 statements and 2296/2296 branches covered (100%)
ruff check: passed; ruff format check: 48 files already formatted
preflight: ok, 63 files scanned, 0 failures
build without isolation: sdist and wheel built successfully from this worktree
```

The exact isolated `python -m build` command could not bootstrap its temporary environment on
this Windows host: the only available Python is embedded in MySQL Shell, whose `venv` bootstrap
attempted to decode its DLLs as UTF-8 and produced a Python without SSL. The failure occurred
before reading/building project code. `python -m build --no-isolation` used the already installed,
locked development build requirements and successfully produced both artifacts; generated build
files were removed after verification.

The issue-#11 real acceptance gate is intentionally not claimed complete. A later, separately
authorized staging test must register/verify authenticated webhook transport, create a temporary
test Product, change product type/tags/price/inventory/publication, exercise delayed and duplicate
delivery, verify every active projection against a fresh read-only source, restore/delete the
temporary Product, and record PowerTools continuity. It must also choose durable queue/inbox
storage, retry/dead-letter operations, reconciliation scheduling, deployment readiness thresholds,
and the maximum accepted sync lag. Live publication remains reserved to Jacopo's cutover gate.
