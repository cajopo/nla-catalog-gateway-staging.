# WS97 — CardTrader missing-printing importer

Issue: https://github.com/cajopo/nla-catalog-gateway-staging./issues/97

Owner confirmation (2026-09-25): create verified missing card printings as new
Shopify DRAFT/unpublished/zero-stock products. Existing products, PowerTools,
MAIN theme and publication remain untouched. No invented selling prices or
language/condition/finish. Gateway/normal refresh stay read-only.

## Current increment

### Bounded source-to-draft runner — 2026-09-26

`python -m scripts.import_cardtrader_drafts` now connects the existing components:
complete fresh source -> current pinned projection -> canonical preparation ->
reference selection -> live identity guard -> durable create-only primitive.
No new Shopify operation or product writer is introduced. Default is preview;
`--apply` is explicit and `--max-attempts` defaults to1 (maximum100 per invocation,
not a promise of store-wide daily quota). Required arguments: `--refresh-config`,
`--capture`, `--identities`, `--run`, `--ledger`, `--generator-sha`.

Use the existing private persistent ledger, never a new empty replacement. The
run must be a new path under the ledger's parent; retain it because its reference
bundle may become an input for future refreshes. The CLI holds the existing
whole-pipeline lock, rejects pending/stale refresh or unresolved prior attempts,
and checks the fresh complete identity export before preparation. On apply it
backs up the current configuration and changes ONLY the reference path and its
two pins. New reference files/directories are durable before config selection;
the original reference is preserved. Do not roll back reference additions after
creating corresponding drafts: doing so would break later reconciliation.

Every attempted draft uses the existing no-resend ledger and current identity
callback; source age/config selection are checked again at that boundary. All
products remain DRAFT/unpublished. No existing product, selling price, quantity,
PowerTools configuration or theme change is added. Uncertain creation stops the
batch and blocks subsequent runs pending inspection. A ledger backup and private
result are retained; interruption cannot produce a false complete receipt.

80 focused runner/importer tests PASS. Runner fixtures exercise actual source
capture, SQLite comparison, reference generation, config selection and SQLite
ledger with simulated Shopify responses; current identity API guards were tested
live separately above. Preview, bounded selection, reference-before-write,
no-resend, missing prerequisites and interruptions covered. Ruff/help/independent
review PASS after false-success-on-interrupt correction. No new live product write
or daily timer by this increment. Full orchestration, real runner verification,
retention and scheduling remain pending; publication is still separately gated.

Native VPS runner preparation: codebe23a40503e93547af7ae0a031aecb573cd14169
installed separately at `/opt/nla-staging/importer-be23a40`; archive SHA256
65dcd4c23a6777ec158fbd264f953aec5c416b3b2765035bf2cd7b91b14ab566.
CLI help/import smoke passed on native Linux. Actual preview against the current
projection/ledger/reference rejected the still-running source with
`incomplete_capture`; hashes prove refresh configuration and ledger unchanged,
with zero Shopify API calls. Private receipt:
`/opt/nla-staging/importer-state/runner-negative-preflight-be23a40.json`.
The preview directory `preflight-incomplete-be23a40` is retained, not reused.
This is a negative prerequisite test, NOT successful live draft execution.

Documentation rechecked: https://shopify.dev/docs/api/admin-graphql/latest/mutations/productCreate
(currently2026-07), https://www.cardtrader.com/it/docs/api/full/reference.

### Repeatable current Shopify identity check — 2026-09-26

`python -m scripts.capture_import_identities` generalizes the successful pilot's
complete all-status, both-identity-field Bulk export. Required: `--shop`,
`--credential-file`, `--run-root` (the existing refresh pipeline lock directory),
`--output` (new private run directory). Run on Linux from the installed package root.
Each call starts or polls the same saved operation; unknown submission outcomes
retain intent and cannot resend. Failed/partial downloads require inspection, not
automatic resubmission. No signed URL is saved in receipts or printed.

Exact independent counts before/after, query/operation identity, all row types,
unique product GIDs and SHA256 are checked. `read_fresh_identities` rechecks the
receipt and complete file and rejects exports older than30minutes from capture
start. `verify_missing` is reusable as the existing draft primitive's callback:
checks both identifiers, actual shop and existing definitions, recent changes,
and the deterministic handle. Absence is not atomic against PowerTools; it does
not authorize publication or bypass source/reference gates. No metafield search
filter, definition mutation or modification of an existing product is introduced.

46 targeted export/preflight/recent-identity tests PASS; Ruff and CLI smoke PASS.
Both actual GraphQL queries passed official schema validation, revision1:
`nla-repeatable-identities-snapshot-20260926` and
`nla-repeatable-identities-definition-20260926`. Independent review required syncing
the new run's parent directory before API calls; fixed and regression-tested.
Live check recorded below when performed. Source-to-draft orchestration and
scheduling are still unfinished.

Official documentation consulted before implementation:
https://shopify.dev/docs/apps/build/apis/graphql-admin/bulk-operations/queries

Real read-only verification completed using code038f5292fc730882797d7a652d96140468ed5f64
in `/opt/nla-staging/importer-038f529` (separate package; normal refresh unchanged).
Archive SHA25677fe1efeea62fc883e86f8910ea4c5ddd2670016dcdbaea52ca1c7f1ce187e71.
Bulk12533904965900 completed2026-09-26T10:11:39Z, started10:11:08Z:
291796 unique products, both identity fields; full counts and file verification PASS.
File SHA2565c395698ad3ba36922df6a57b02bcf24cca7585612de79e1cc4593178321ca2e.
Private run `/var/tmp/nla-current-identities-038f529` retains intent, operation,
completed receipt, identities.jsonl and live-guards.json. Do NOT resubmit this run;
future use must respect its30minute freshness limit, not pretend it stays current.

Actual guard rejected pilot Cardmarket80236 as already present BEFORE further API
calls. A different real source candidate904085 passed full snapshot + live shop,
definition, delta and handle checks. No creation was attempted or approved by this
probe; old CardTrader source data was used only to select a real test identifier,
not as current import authorization. All calls/readbacks were read-only.

### Comparison-to-reference preparation — 2026-09-26

`python -m scripts.prepare_cardtrader_reference` connects the verified capture and
checksum-pinned projection comparison to the existing canonical-reference builder.
Run from the repository root. Required arguments: `--capture`, `--projection`,
`--projection-sha256`, `--parent`, `--parent-sha256`, `--output`, `--generator-sha`.
All paths must be absolute; output must be new and private, outside Git.

Each candidate retains its exact source file/row, blueprint and Cardmarket IDs.
Only observed fixed properties supply collector number/rarity; editable-property
defaults never become variant attributes. The public CardTrader reference documents
image URLs and Cardmarket IDs but not these fixed-property names; their presence
and string types are checked against the observed real export contract used by the
successful Sep25 reference build. Missing/invalid/conflicting details are reported,
not guessed. Existing canonical records remain unchanged; cross-game ID ambiguity
is quarantined. No invented selling price, condition, language or finish.

The new bundle is NOT activated. `preparation.json` explicitly retains
`creationApproved:false` and `shopifyChanged:false`. Current Shopify identity
verification and controlled reference activation must still precede any creation.
No source file, output artifact or credential is committed.

16 focused preparation/reference-builder tests PASS, including synthetic complete
capture -> SQLite comparison -> reference roundtrip, existing mapping preservation,
ambiguous parent IDs, malformed expansion duplicates, rejected metadata/images and
output no-overwrite. Ruff and CLI help smoke PASS. Independent review identified
an expansion-map filtering mismatch, corrected with its regression test. No live
run, deployment, timer, Shopify writes or GitHub push.
Official source reference: https://www.cardtrader.com/it/docs/api/full/reference

### Capture-to-comparison integration — 2026-09-26

`compare_captured_catalog` verifies completion,24h source age, every source file
hash/size, expansion/row/anomaly counts and exact anomaly sidecars before invoking
the existing global identity comparison. It retains source expansion/row provenance
and quarantines export conflicts. Unknown categories remain reportable. Only the
five identity fields are retained across expansions to avoid retaining all media
and property descriptions in memory.

`scripts/compare_cardtrader_catalog.py` reads a checksum-pinned SQLite projection
using mode=ro/query_only, rejects journal/WAL/SHM inputs, checks the checksum again,
and writes a new private report without overwriting prior evidence. It explicitly
reports the projection timestamp and scope; absence is NOT a current Shopify check
or creation approval. New and ambiguous rows do not cause any Shopify writes.

78 focused capture/comparison/CLI tests PASS, including capture -> real SQLite ->
comparison-report integration on synthetic fixtures; capture module100% statement
and branch coverage. Ruff and independent review PASS. Not deployed; no live
network run or source-to-store automation was enabled. Official SQLite URI
reference: https://docs.python.org/3/library/sqlite3.html#how-to-work-with-sqlite-uris

### Repeatable read-only source capture — 2026-09-26

`scripts/capture_cardtrader_catalog.py` invokes the GET-only transport through
`cardtrader_capture.py`, extracting the already exercised one-shot capture logic.
Read credentials from a private file, not a command-line token. Each execution
requires a new absolute output directory; no old run is overwritten or deleted.
It reads every expansion of the four approved games, not just larger IDs/new sets,
so additions to old sets can be discovered. Source anomalies remain in raw files
and per-expansion sidecars; file hashes, byte counts and progress are recorded.
Failures, disk/size/deadline limits yield failed status, never a complete snapshot.
Consumers must verify all files/hashes/counts before using a completed run.

18 focused capture/CLI tests PASS; capture module alone has100% statement/branch
coverage. Ruff and independent component/CLI review PASS (no Blocker/High).
CLI --help smoke PASS. The CLI has no Shopify client or mutation path. No live acquisition or
timer was started by this increment; it is the reusable acquisition entry point,
not a claim that scheduled source-to-store ingestion is active. Caller supplies
the existing private credential path and a fresh run directory outside Git.

Official source contract: https://www.cardtrader.com/it/docs/api/full/reference
The documented shared limit is200 requests/10seconds; this uses at most1 request
per second. Export is per expansion; no documented new-release cursor is assumed.

### Safe initial default variant — 2026-09-26

The real single-draft pilot exposed a Shopify default: quantity zero and DENY,
but inventory tracking disabled. Its initial tracking was completed under the
create-only exception; it remains DRAFT and unpublished. No price was supplied.

The execution primitive now performs that initialization for future newly created
drafts, within the existing durable attempt. It only accepts one complete default
variant with zero quantity, DENY, unchanged default options and Shopify's default
zero price. Unexpected state requires reconciliation, not correction. The only new
mutation sets `inventoryItem.tracked:true` and DENY on the variant read from the
product returned by this call's creation response. No quantity, price, option,
publication or pre-existing-product mutation is added. A complete readback must
equal the pre-initialization state except for tracking. Existing reservations still
block every retry, including an interruption after the initialization write.

Evidence:70 focused importer tests PASS (including response mismatch, interrupted
write/readback, changed variants, no-resend and recovery guards); 100% statement
and branch coverage of this module only. Ruff check/format and independent review
PASS, no Blocker/High findings. Actual source
operations schema validated: `nla-initial-variant-verify_draft` and
`nla-initial-variant-initialize_variant`, revision1, Shopify2026-07. This increment
is local, not deployed; automatic new-market ingestion remains OFF. Publication,
media readiness and PowerTools interoperability remain separate gates.

Official documentation used before implementation:
- https://shopify.dev/docs/api/admin-graphql/2026-07/mutations/productVariantsBulkUpdate
- https://shopify.dev/docs/api/admin-graphql/latest/input-objects/InventoryItemInput
- https://shopify.dev/docs/api/admin-graphql/2026-07/enums/ProductVariantInventoryPolicy

### Read-only interrupted-attempt inspection — 2026-09-25

`inspect_draft_attempt` opens the durable ledger mode=ro/query_only, verifies the
saved request digest and expected handle, then checks actual Shopify shop identity.
A recorded creation-response GID is read back; without a recorded GID, exact handle
lookup is only a manual-ownership lead. No result permits retry, adopts a product,
changes ledger state or mutates Shopify. Missing products and read errors remain
unconfirmed. Matching draft fields do not prove media readiness or purchase safety.

Official documentation consulted before coding:
https://shopify.dev/docs/api/admin-graphql/2026-07/queries/productByIdentifier
Exact query schema validation PASS `nla-inspect-draft-handle-20260925` rev1;
required scope read_products.44 focused importer/inspection tests PASS; Ruff PASS;
independent review no material findings. No live mutation/deployment performed.

Visibility remains a separate explicit owner gate: DRAFT products do not appear
in storefront search. Do not relax ACTIVE+OnlineStore publication filtering.
Publishing only verified importer-created records as non-purchasable SOLD OUT
products requires owner approval, inventory tracking/policy checks, and a pilot.

### Canonical reference prerequisite resolved — 2026-09-25

Helper commit `1643d6b12f434cf7562185d2baf8cb9e5587510d` extends through the existing
CSV builder/strict loader, rejecting collisions and requiring exact preservation.
Independent review found no blocker.85 extension/loader/builder tests PASS;
Ruff check and format check PASS. No full-suite claim.

Real captured candidate:332667 original mappings +4065 additions =336732;
5/4070 candidate IDs already mapped and retained unchanged. Additions by game:
Magic2163, Pokemon1080, Yugioh474, OnePiece348. Source file hashes and row/blueprint
bindings retained privately on VPS, not in Git. No new CardTrader calls needed.

VPS `/opt/nla-staging/reference-cardtrader-20260925-candidate-v1/bundle`:
manifest `fd1d542b44b98be9bb364f7365f83c58d22d00b10ba337c540aa668a63ad1c6d`,
sidecar `64742f7e6654eda4456d4e5ef2f0b488daaa97f97e8253dd50075230edab4c7b`.
Installed refresh configuration validator accepted the candidate. Selected these
reference pins under pipeline lock; timer briefly stopped then restored active,
refresh service inactive, runtime pointer unchanged. Prior configuration retained
in `refresh-config-before.json`; later `refresh-reference-selected.json` records
selection (the builder evidence's activated:false describes earlier build time).

No Shopify mutation or refresh started. This prepares future refreshes to accept
these new identities; it does not make missing products visible or enable imports.
Still require app scope, current duplicate checks, pilot integration and scheduling.

`cardtrader_catalog.py` is only a GET transport for games/categories/expansions
and blueprint export. Fixed HTTPS origin; no redirects/proxies; bounded bodies;
sanitized errors; no credential storage or Shopify writes.

`cardtrader_candidates.py` compares every source row against a supplied snapshot,
using explicit category mapping and verified IDs only. It reports unknown/non-card
categories, missing/multiple/shared IDs, duplicate blueprints and Shopify identity
conflicts. Even absence is only `absent_from_supplied_snapshot`, never write approval.

Official reference: https://www.cardtrader.com/it/docs/api/full/reference

Documented arrays and the observed exact `{"array": [...]}` wrapper are accepted.
Unknown shapes fail. IDs are not release dates; no incremental cursor is assumed.

Four real expansion samples: 226 items (including a booster box); 208 single
Cardmarket IDs, 17 missing IDs, one multi-ID. Use actual categories, not missing
metadata, to classify cards. Sep22 projection comparison: 110 existing same-game
identities, 98 absent single-ID items. Absence from that projection is NOT proof
of absence from current Shopify. Real samples remain outside Git.

## Evidence — 2026-09-25

- Focused pytest: 77 passed (45 transport, 32 comparison), 100% statement/branch
  coverage of these two new modules only.
- Ruff check and format check on module/tests: PASS.
- Independent review's HTTPException sanitization finding corrected and tested.
- Independent comparison review's contradictory Shopify GID finding corrected:
  all duplicate GID rows must agree, even with disjoint or empty source IDs.
- Full repository validation, deployment and automatic ingestion NOT claimed.
- `write_products` not granted. GitHub uploads held pending allowance reset.

## Real read-only check — 2026-09-25

Credential setup succeeded on VPS (root-only, outside Git). Actual API category
names/game IDs verified for single categories 1/44/73/192 and sealed category54.
The committed transport/comparison ran in memory against six authenticated GETs
and the existing SQLite projection in read-only mode: 226 accounted items =
110 existing, 98 absent from the Sep22 snapshot, 16 missing IDs, one multiple-ID,
one non-card. No Shopify mutations or gateway deployment.
This proves only the four-expansion sample, not whole-catalog coverage or current
Shopify absence. Owner has been asked to grant the missing `write_products` scope.

Next: whole-catalog discovery, fresh Shopify identity checks and duplicate-safe
creation under the approved exception. Automatic ingestion remains OFF;
publication remains a separate gate.

## Source inconsistency discovered during full acquisition

The first acquisition stopped after 63 expansions: expansion73 belongs to Magic,
but its export includes two rows with game5/category73 (Pokemon). A fresh GET
confirmed this discrepancy. Do not repair the upstream identities by guessing.
Comparison now requires the actual expansion-to-game mapping and reports
`expansion_game_conflict`, even when category and blueprint game agree. Focused
comparison suite: 38 passed, 100% module coverage, Ruff PASS; independent review PASS.

One-shot discovery V2 preserves every raw response plus indexed anomaly sidecars,
using a new run directory/unit; the failed run is retained. Its eventual complete
state means acquisition, not import eligibility. Consumers must respect sidecars
as well as record-level identity checks: sidecars retain requested-export context.

## Shopify identity definitions — read-only inspection

Official schema-validated query executed on 2026-09-25; both namespace pages
complete (`hasNextPage=false`):

| Existing field | Type | Admin filtering | Unique values |
| --- | --- | --- | --- |
| `sync.productid` | `number_integer` | disabled / NOT_FILTERABLE | disabled |
| `powertools.id` | `single_line_text_field` | disabled / NOT_FILTERABLE | disabled |

Preserve these types and merchant-owned definitions; do not create replacements
or enable capabilities without authority. A direct metafield-filter query cannot
currently serve as proof of product absence. Duplicate prevention must use an
authoritative inventory and account for concurrent PowerTools changes; a stale
projection, title match or unsupported search filter is insufficient.
The same probe confirms `write_products` remains ungranted. No mutation executed.

Reference: https://shopify.dev/docs/api/admin-graphql/latest/queries/metafieldDefinitions

## Completed full discovery and comparison — 2026-09-25

V2 acquisition finished at11:11:53Z: systemd EXIT0/MainPID0, all2430 expansions
and256176 source rows captured;37 source anomalies retained. No automatic importer
or Shopify writes enabled. Full comparison uses the Sep25 09:40:10Z projection,
manifest7a12429309ce2170ca609d2e399b5e7a0a3f3de9eefb9ab607c014a106d5cfc0,
containing291795 Shopify products. All source rows are accounted:

| Decision | Source rows |
| --- | ---: |
| Existing identity match | 221208 |
| Absent from supplied snapshot | 4070 |
| Unclassified category | 17421 |
| Missing Cardmarket ID | 9149 |
| Multiple Cardmarket IDs | 3986 |
| Multiple Shopify products | 3 |
| Non-card category | 301 |
| Invalid Cardmarket IDs | 1 |
| Source export conflict | 37 |

Absent candidates: Magic2168, Pokemon1080, Yu-Gi-Oh474, OnePiece348.
None is approved for creation by this comparison. Category exceptions retain
actual category names/counts; other exceptions retain source expansion/row
provenance. This is not proof of current Shopify absence or serving-runtime health.
Full private evidence remains on VPS at
`/var/tmp/nla-cardtrader-discovery-20260925-v2/full-comparison-7a12429309ce.json`;
do not commit the source or detailed report.

## Recent Shopify identity read — 2026-09-25

`shopify_identity_changes.py` reads products updated since the baseline capture
start, including active/draft/archived/unlisted products. It reuses the existing
read-only HTTP transport and reads both existing merchant identity fields. It
requires complete, consistent cursor pagination; errors or the5000-row cap fail
without returning partial success. It does not enable filtering on shared fields,
create products, or treat absence as permission to write. Concurrent writers,
search indexing lag and metadata timestamp semantics are not solved by this read.

Official reference: https://shopify.dev/docs/api/admin-graphql/latest/queries/products
The exact query passed schema validation (artifact nla-recent-identities-20260925,
revision2; revision1 failed because PowerShell stripped quoted string arguments).
26 focused tests, Ruff and independent review passed. One actual read from capture
start2026-09-25T09:32:46Z returned one complete empty page; none of the4070 candidate
IDs was found in that response. This is additional evidence, not fresh atomic
absence proof. Private report:
`/var/tmp/nla-cardtrader-discovery-20260925-v2/recent-shopify-identities-20260925.json`.

## Disabled draft execution primitive — 2026-09-25

`shopify_draft_import.py` implements one create-only attempt, not a rollout command.
Default disabled. Requires the matching shop and actual `write_products` scope,
vetted caller inputs and a reviewed current-identity check (NOT just an empty delta).
A persistent absolute SQLite ledger reserves both source IDs before any mutation.
Every prior reservation blocks resend, including failures and uncertain responses;
the ledger must be preserved/backed up. Valid returned GIDs are retained even when
other response fields are unexpected. No generic product-update operation exists.

The only writes are `productCreate` with DRAFT plus source image/title and known
product type, followed by initial `sync.productid`/`powertools.id` through
`metafieldsSet` with `compareDigest:null` (never overwrite existing values). The
definitions already exist and are not changed. No price, inventory, language,
condition, finish or publication writes. Readback checks the created GID, handle,
DRAFT state, zero aggregate inventory, unpublished Online Store state and identities.
It does not yet verify asynchronous image readiness or PowerTools interoperability.

Evidence:33 focused tests PASS,100% statement/branch coverage of this new module,
Ruff/formatPASS. Four operation schema validations PASS (nla-draft-{access,create,
identities,verify}-20260925 revision1). Independent review findings on persistent
ledger, early GID recording and final-readback tests corrected. No live mutation.
Fresh access query confirms the app still lacks `write_products`.

Still required: wire validated source/candidate data and the current duplicate
check into an operator entry point, reconcile uncertain outcomes without resend,
run a controlled real draft test, then daily scheduling and the separate publication
gate. This primitive neither resolves concurrent PowerTools creation nor proves
automatic new-market ingestion complete. Shopify documents a1000-new-variants/day
resource limit after50000 variants (subject to plan exceptions); respect the shared
store budget rather than assuming all4070 candidates can be imported immediately.

References:
- https://shopify.dev/docs/api/admin-graphql/latest/mutations/productCreate
- https://shopify.dev/docs/api/admin-graphql/latest/mutations/metafieldsSet

## Integration prerequisite found before any write — 2026-09-25

The current refresh pins an external canonical-name reference. In
`reconciliation._apply_canonical_names`, EVERY structured single requires a matching
(game,sync ID) entry, including drafts; absence raises `ReconciliationDataError`.
The capture counts all structured singles, not only published/active products.
Therefore creating missing products before extending the reference would break
the next full refresh, even though draft creation itself succeeded.

Actual read-only check of the currently configured reference:332667 rows.
Of4070 absent Shopify candidates, only5 already have a canonical mapping;
4065 need new entries (Magic2163/Pokemon1080/Yugioh474/OnePiece348).
No reference file or operator configuration was changed. This is a prerequisite
for the importer, not a reason to weaken reconciliation checks or fabricate names.
Next: build a new version of the reference using verified CardTrader names and
available metadata, preserve existing records exactly, validate with existing
loader, and activate the reference under the refresh lock BEFORE creating products.
Retain parent/source evidence outside Git. Publication remains separately gated.

Browser access attempted to avoid burdening the owner with app setup. The Codex
browser is at Shopify's saved-account selection screen; handoff requested. No app
settings or scopes changed. Required-scope updates need a new app version plus
merchant approval per official manage-access-scopes documentation.

## Repeatable cycle candidate — 2026-09-26

`scripts/refresh_market_catalog.py` coordinates existing source capture, a single
retained identity export, bounded draft importer and existing refresh operator.
Default preview; explicit `--apply-drafts`; no timer installed and no publication.
Errors retain a pending receipt and prevent blind restart. Retain run directories:
the selected canonical reference may be inside one. Retention/scheduling and live
positive-cycle evidence remain outstanding; new-market automation remains OFF.

The batch runner now excludes current Shopify IDs and same-shop verified ledger
CM/blueprint IDs BEFORE selecting the batch. This prevents repeated selection when
the projection predates a created draft. Live duplicate guards remain required.

Evidence: 24 targeted runner/coordinator tests PASS (14.78s), Ruff check and format
check PASS. Independent static review by refresh_recovery_review: no Blocker/High.
No deployment, Shopify mutation, timer or GitHub push for this delta. Existing
CardTrader capture remains the SAME service/PID184145, last observed1458/2430sets;
never restart it merely because observation ends. Use its completed output for the
next positive preview and authorized bounded DRAFT trial.

## Complete-source live trial — 2026-09-26

Installed `bdabf46dffb082a2f1070ca0f5315446d3c502e2` from archive SHA256
64bedf355e66d4a217a28f6c4bdcb3a0be91d97f752b23a95f1e0c5f013c21ca.
The retained CardTrader capture completed 2430 sets / 256177 blueprints, 37 source
anomalies; no second capture. Fresh Shopify identities Bulk12534107799820 completed
291796 products, started2026-09-26T11:05:10Z. Preview:4065candidates,1existing skipped,
5preparation exceptions,1selected, no mutations. Its directory is
/opt/nla-staging/importer-state/preview-complete-source-bdabf46.

One explicit `import_cardtrader_drafts --apply --max-attempts 1` then succeeded:
CM904085 / blueprint408222, Magic, Dáin Ironfoot - The Duelist Promos [001],
gid://shopify/Product/16570959921420. Result `batch_complete`, `draft_verified`,
publishedfalse. Retained run: importer-state/apply-complete-source-bdabf46-one;
ledger now prevents resend. No pre-existing product changes. Existing canonical
reference already contained this mapping; configured reference/pins stayed unchanged.
The normal read-only index refresh was started once afterwards, invocation
7a1ac08e8ac04759b7ea8bb2a8d62013; completion not yet observed. No recurring market
timer enabled. Publication remains an unanswered owner gate; full goal not complete.

## Bounded raw-input retention — 2026-09-26

Before a new market cycle's disk-reserve check, under both existing pipeline locks,
prune only large named inputs of completed `market-*` cycles. Keep the latest two
cycles, the configured canonical-reference owner, and the direct before-reference
owners of those retained cycles. Incomplete cycles or pending refreshes stop pruning.
Targets are blueprint payloads, the identity JSONL, the per-batch ledger backup and
unused canonical sidecars. Permanent ledger, completion/source manifests, source
anomalies, preparation/candidate/exception reports and manual pilot directories stay.
No directory is recursively removed. Canonical paths, file ownership/type, single
links and unchanged file identity/configuration are checked before unlinking.

Expired raw inputs are not recoverable from these receipts and are not reusable
captures. The source manifest retains their hashes; ordinary future cycles acquire
their own current source. An interrupted cleanup can leave only part of the old
inputs removed; repeat cleanup skips missing files and never recreates products.
The compact pruning receipt is written after removal, so a crash before that write
can omit that housekeeping receipt (source manifests and importer ledger remain).

Official Python filesystem documentation consulted before implementation:
https://docs.python.org/3.12/library/shutil.html#shutil.rmtree . Individual named-file
unlinking avoids recursive deletion of directories containing operational evidence.
21 targeted retention/coordinator tests PASS (2.25s), independent static review no
blocker. No production cleanup, timer activation, Shopify mutation or GitHub push.

Native Linux fixture proof also PASS for executable commit8777eb3: real root/0600
document reads, both locks, eight named fixture deletions, active/latest retention,
idempotent repeat and pending-cycle rejection. ProductionDataChanged=false.
Fixture evidence: /var/tmp/nla-retention-proof-8777eb3-0aoain7k and
/var/tmp/nla-retention-fixtures-8777eb3-h5g81r68. No dependency installation needed.

## Reuse validated identity baseline within a batch — 2026-09-26

The per-product guard previously rescanned the complete identity JSONL for every
candidate. `missing_guard` now fully validates it once when a batch guard is built;
the runner still separately reads it for initial candidate exclusion (two full
scans per batch, not per product). Before AND after each live check it rechecks
canonical regular single-link paths and inode/device/mode/owner/size/mtime/ctime of
all four snapshot files, and the unchanged 30-minute age limit. No global cache.
Shop, metadata definitions, recent Shopify identity changes and deterministic
handle remain queried separately for every candidate; remote results are not cached.
Standalone `verify_missing` remains compatible and builds a fresh one-call guard.
No API/query/scopes/publication behavior changed.

38 identity/runner tests PASS14.54s, Ruff/formatPASS, independent static review no
blocker. Regressions cover scan-once/live-delta-not-cached, all four local files,
expiry before network and mutation during network. Not deployed or run live yet.
This removes repeated work needed before multi-batch orchestration; the cycle's
one-batch maximum remains unchanged and does not yet clear the full backlog.

## Bounded multi-batch cycle — 2026-09-26

The market coordinator now accepts `--max-batches` (default1, range1..100) in
addition to the unchanged per-batch `--max-attempts` (range1..100). It acquires
CardTrader once, obtains a separate fresh Shopify identity export for each batch,
and refreshes the Shopify-derived index once at the end if any new draft was
verified. The existing 30-minute identity and24-hour source limits, live checks,
no-resend ledger and create-only DRAFT/unpublished/zero-stock rules are unchanged.
Preview runs only one batch. No API/query/schema, scheduling or publication change.

The first batch retains `batch/` and `identities/`; subsequent batches use
`batch-0002/`, `identities-0002/`, and so on. Completion receipts retain cumulative
attempts, per-batch summaries, `remaining`, `eligibleExhausted` and
`completionReason`. A successfully bounded but unfinished cycle is explicitly
`draft_cycle_partial`, not complete ingestion; it can close its pending marker
after the final refresh. The backlog is conservative: live-guard rejections are
not counted as imported. A batch with no verified progress stops rather than
repeating the same selection. Source/preparation exceptions remain reported even
when eligible candidates are exhausted. Uncertainty still leaves pending state
and requires inspection; no automatic retry or recovery is introduced.

After each successful batch, only the latest two identity JSONL payloads are
retained within that cycle. Expiry verifies the completed batch and identity
receipts, exact payload SHA256 and unchanged canonical regular single-link file;
a durable expiry intent precedes unlink. All directories, receipts, source
anomalies, preparation reports and the permanent ledger remain. Historical cycle
retention also understands numbered batch/identity paths and their before-reference
protection. These expired payloads are deliberately not recoverable from receipts.
Filesystem reference: https://docs.python.org/3.12/library/pathlib.html#pathlib.Path.unlink

Author validation:71 focused coordinator/retention/runner/identity tests PASS,
Ruff check and format PASS. Independent main-agent review found no blocking
findings: checked the full delta against the real runner's candidate/ledger,
reference selection, empty-batch and freshness contracts, plus identity receipts
and retention targets. No additional acquisition is needed for this review.
Not yet deployed or exercised as a live multi-batch cycle; real throughput and
timer coordination remain operational gates. Publication is not authorized.

## Draft-only recurring unit templates — 2026-09-26

`ops/systemd/nla-market-catalog.{service,timer}.in` are uninstalled templates,
not an enabled scheduler. Before installation, render `@IMPORTER_PACKAGE@` as the
absolute verified importer checkout, `@IMPORTER_CODE_SHA@` as its exact 40-hex
commit, and `@REFRESH_PACKAGE@` as the separately verified refresh checkout
(currently `/opt/nla-staging/refresh-5176337`). Do not pass an arbitrary branch or
mutable path as a pin. Verify the installed archives and configuration, render
the filenames without `.in`, then validate with the VPS's `systemd-analyze verify`
and `systemd-analyze calendar '*-*-* 02,14:00:00 UTC'` before enabling anything.
No template rendering or installation is performed by this change.

The fixed existing paths are `/usr/bin/python3`,
`/opt/nla-staging/operator/catalog-refresh.json`,
`/opt/nla-staging/importer-state/draft-attempts.sqlite3` and
`/opt/nla-staging/config/cardtrader-api-credentials.json`. State remains
`/opt/nla-staging/importer-state`; credentials are read from their private file,
never embedded in the unit. The explicit budget is 100 attempts per batch and 50 batches;
this is not a quota or throughput guarantee and does not authorize publication.

The oneshot has a 23h start timeout, no persistent active state and no automatic
restart. Its pre-start command stops ONLY `nla-catalog-refresh.timer`; its
post-stop command starts that timer again on success, startup failure or process
failure. It never stops an existing `nla-catalog-refresh.service`. Existing locks
and pending markers still reject conflicting/uncertain work; inspect pending
evidence instead of restarting blindly. The normal timer remains the fallback;
its already-running service is allowed to finish. The market timer requests
02:00 and 14:00 UTC, with `Persistent=false` (no missed-run catchup). A running
market instance is not duplicated by another timer tick. Recovery must be terminal
and current pending state resolved before initial installation/activation.

Every successful **apply** cycle now performs exactly one final read-only Shopify
index refresh, even when `run_locked` returns its no-selection `preview` receipt.
PowerTools price/stock changes must still reach the index without new draft
creation. An actual preview cycle never refreshes. Uncertain cycles still stop
before the final refresh and preserve pending evidence.

Official systemd manuals consulted (upstream sources, after rendered manuals
returned HTTP403):

- https://github.com/systemd/systemd/blob/main/man/systemd.service.xml
- https://github.com/systemd/systemd/blob/main/man/systemd.timer.xml
- https://github.com/systemd/systemd/blob/main/man/systemd.time.xml

23 targeted tests PASS; template assertions cover empty apply versus preview,
the timer-only stop/restore hooks, explicit UTC schedule, no catchup and no restart.
Independent main-agent review found no blocking findings against the real empty
batch contract and installed systemd service/timer manuals. Native systemd
validation remains required before installation; no live timer is enabled by this commit.

## Owner-approved publication stage — 2026-09-28

The owner's reply authorizes automatic Online Store publication of verified
importer-created SOLD OUT cards. This supersedes the historical draft-only
publication gate above, not the gateway's read-only boundary or PowerTools ownership.

`shopify_draft_publication` selects only `draft_verified` creation-ledger rows,
verifies saved request digest/identities against live Shopify, and requires the
unchanged zero-price/default variant, tracked zero stock at every location, DENY,
one ready image and no other app publication. It identifies the target as Shopify's
Online Store app, not by a display name. Only product status ACTIVE and that single
publication are written. Readback after each write verifies unchanged commercial
fields. A pending snapshot is committed first; lost responses stop and are resolved
by live reads on a later invocation, not blind mutation retries. Terminal published
receipts are excluded forever: subsequent merchant/PowerTools edits are not reset.
Already published importer pilots are recorded without mutations.

The cycle accepts an explicit `--publish-online-store gid://shopify/Publication/…`
only together with `--apply-drafts`, before its one final read-only index refresh.
The unmodified unit template is still draft-only; deployment must append this
owner-approved option to ExecStart. Standalone `scripts.publish_imported_drafts`
can publish existing verified rows without acquiring any catalog source, using
`--refresh-config`, `--ledger`, `--publication`, `--max-products` and explicit
`--apply`. Both paths use importer→refresh lock order and private durable receipts.
There is no write to price, inventory, variants, metadata, existing products,
themes or PowerTools configuration. Failure retains evidence for inspection.

Official 2026-07 contract consulted and four operations schema-validated:
https://shopify.dev/docs/apps/build/sales-channels/product-publishing
https://shopify.dev/docs/api/admin-graphql/2026-07/mutations/productUpdate
Independent product_presentation_review APPROVE: no blocking findings in module,
CLI or cycle ordering.150 focused publisher/CLI/coordinator/retention/unit-template
tests PASS8.57s; Ruff check/format PASS. All tests use synthetic data; deployment
and real publication evidence are separate operational steps.

### VPS evidence — 2026-09-28 CEST

Code bd693e68b71bf2f215d6fd0d8065afb73d2fd9bd installed at
`/opt/nla-staging/importer-bd693e6` from full git archive SHA256
`a089c5582191146ef8e2ed3f63993db85bd5cc81250ffef7dae277e18fe43035`.
Native disabled-default invocation PASS. Two applied batches completed:
5 newly published +5 already published without writes, then296 newly published,
zero remaining. Thus306 importer-owned products have terminal publication receipts
(301 new publications this turn). All new products were individually read back
ACTIVE, Online Store published, tracked0/DENY, ready image and unchanged commercial
data. Existing5 pilot publications were not mutated. No catalog reacquisition.
Private receipts retained in importer-state: publication-2867b18f667f46b284ab1732371e7ddb.json
and publication-9bfd78df5dfb4078a02322e16e3a9899.json. Sessions52752/6138 terminal exit0.

Service now pins bd693e6 and explicit Online Store162078753036 before its single
final index refresh. Native systemd validation/readback PASS, no early cycle
started; next market04:00CEST Sep28. Complete unattended cycle/index visibility
is still unproven. The existing first-cycle heartbeat remains; no duplicate monitor.
Rollback unit retained as `/opt/nla-staging/nla-market-catalog.before-bd693e6.service`:
restoring it removes future automatic publication, not already-published products.
No MAIN, PowerTools, commercial-data, pre-existing-product or GitHub changes.

### Preserve verified identities across provider naming differences — 2026-09-28

Read-only inspection of the existing Sep27 capture and checksum-pinned canonical
reference identified all five preparation exceptions: CardTrader names the five
sticker sheets identically, while the reference distinguishes Sheet1–5 (CM818500–4,
blueprints326966–70). IDs are one-to-one and game agrees; exact name equality was
an extra, incorrect identity gate. It is removed, not replaced by title matching.
The complete existing canonical record stays authoritative and unchanged;
`sourceNameDiffers` exposes the discrepancy in each candidate's existing provenance.
Cross-game, duplicate/shared/multiple IDs, invalid metadata/image and fresh Shopify
absence checks remain. No product is created merely by passing preparation.
Official blueprint ID contract rechecked:
https://www.cardtrader.com/it/docs/api/full/reference#blueprints
106 focused preparation/candidate/capture/reference/runner tests PASS48.82s;
Ruff PASS, independent product_presentation_review APPROVE. No new acquisition
or product mutation for this fix; next scheduled cycle will reevaluate current data.

Deployed code8adf76c8e12bd2de512d9bac73322f6e5cd42063 in isolated
`/opt/nla-staging/importer-8adf76c`; archive SHA256
09affaf240d19dabfff887d52282b1300850d2b28c927607acc5e1bc7dfaa8a9 verified.
Native import/help and systemd validation/readback PASS; service pin updated,
publication flag and04:00CEST schedule preserved. Previous unit backup:
`/opt/nla-staging/nla-market-catalog.before-8adf76c.service`.
Read-only ledger check:306 terminal published receipts, no pending publications.
No early run, source acquisition or additional Shopify mutation.

### Local delivery validation and preflight false positives — 2026-09-28

Baseline HEAD6f951f1200a547a1c1c593c19226c325d5e87065 received one full local
Windows validation. Ruff and formatting PASS (153 files), package build with
`python -m build --no-isolation` PASS. The single complete pytest run reported
3565 passed,1 failed,0 skipped in1522.62s. Its failing repository-entrypoint test
matched the standalone preflight failure: four runtime credential lookups were
misidentified as literal credential assignments, plus one synthetic test sentinel.

Normalize the four client constructors to the same positional signature already
used by capture_shopify_bulk and refresh_staging_catalog. Use the explicitly
synthetic `test-only-secret` sentinel and assert all four constructor arguments
in the publication CLI test. No secret-detector rules, exclusions, API behavior,
credentials, product data or runtime guards changed. Independent delivery_validation
review found no findings in the six-file staged diff.

Post-fix validation: preflight PASS over183 staged files; Ruff and format checks
PASS for the six changed files; `git diff --cached --check` PASS. Focused command:
`python -m pytest -p no:cacheprovider tests/test_capture_import_identities.py tests/test_import_cardtrader_drafts.py tests/test_publish_imported_drafts.py tests/test_refresh_market_catalog.py tests/test_capture_cardtrader_cli.py tests/test_preflight_repo.py::test_module_entrypoint_executes_repository_preflight`
reported88 passed,0 failed,0 skipped in70.58s, without rerunning the full suite.

Coverage remains explicitly NOT a full release pass: the earlier full run produced
99.41%, below the100% gate. generation_bundle's native Linux backend accounts for
57 uncovered statements and one partial branch; its Linux tests return early on
Windows, so0 skipped does not establish Linux coverage. Every other reported module,
including importer and publisher, reached100%. Linux/exact-head CI remains required;
no threshold waiver, GitHub push, remote CI claim or deployment is authorized by this
local diff review. The pre-existing coverage file was preserved; the new private
coverage output and build artifacts are not committed.

Separately, the already-running VPS package remains8adf76c, PID237423, same run
market-20260928t000647z-1b1a8344. At05:50:01UTC it had34 completed100-product batches,
3706 verified creations in the permanent ledger and306 prior publications.
This cycle's3400 creations still await terminal publication/index receipts; do not
restart or reacquire the source. Five former name-difference cases (CM818500–4)
are now ledger-verified creations, not merely prepared candidates. No MAIN or
PowerTools changes, and no assertion of final search visibility yet.

### Defer an inconsistent pre-create read without hiding uncertain writes — 2026-09-28

The same real run stopped at06:13:02UTC in batch0037, after36 complete batches
and66 more verified creations. CM910695 failed the existing three bounded identity
reads with inconsistent_identity_page. Readonly ledger inspection confirmed3972
draft_verified total, zero other creation states, no row forCM910695 and306 prior
publications. Thus3666 new verified creations awaited publication; the historical
stop receipt and pending marker remain intact. A later bounded diagnostic of the
same query returned2 pages/73 rows without duplicate IDs or timestamp regression.
This establishes no uncertain creation, not permission to bypass identity checks.

Official products documentation and schema were consulted before diagnosis:
https://shopify.dev/docs/api/admin-graphql/2026-07/queries/products
Existing NlaRecentProductIdentities query validated against Shopify schema, requiring
read_products. The first validator invocation lost quotes in PowerShell argument
passing; the unchanged query passed after transport quoting was corrected.

Only this exact ValueError inside the pre-create identity callback is now deferred:
the callback returns False, so create_draft_once neither reserves nor writes that
candidate. The durable batch receipt identifies CM, blueprint and reason, then stops
further candidates. cycle retains conservative backlog, rechecks that the entire
ledger has no unverified attempts and runs the existing publisher/final refresh.
It reports draft_cycle_partial, never complete. Deferred identities are not excluded
from future cycles. Other errors, altered/stale inputs, wrong shop, changed identity
definitions and uncertain writes retain their previous stop behavior. Query, retry
count, freshness thresholds and publication-readiness checks are unchanged.

Independent root review of delivery_validation's four-file implementation: no
findings.58 focused importer/coordinator tests PASS35.52s; after a purely nominal
lambda parameter shortening, the two affected deferral tests PASS22.06s. Ruff,
format and diff checks PASS. Full latest-head Linux/CI verification still pending;
no repeat full Windows suite, coverage waiver, push or MAIN/PowerTools modification.
Operational recovery is separate, limited to the existing source/run and fresh
Shopify identity data; no new CardTrader capture is needed or authorized by this fix.

### Close operator-script coverage on native Linux — 2026-09-28

One full native Linux run on dfb9b12:3576 tests passed,0 failures/skips,
1474.54s. Install/Ruff/format/preflight/build passed. Including scripts as CI does
exposed159 uncovered statements/89 branches in seven operator scripts; all gateway
modules were100%. This was not the earlier platform-specific generation gap.

Add88 offline boundary/entrypoint cases in two test files, reusing existing fixtures.
Independent root review found no findings. Targeted Windows proof:223+3 tests passed,
seven scripts100% (882 statements/372 branches). The only script edit is an inline
`no branch` annotation for the bounded retry loop's impossible natural exit; explicit
tests prove success on attempts1/2/3, failure on3 and nonretryable failure on1.
Executable AST and line positions are unchanged. This follows Coverage7.16's
documented structurally-partial-branch handling, not a threshold reduction:
https://coverage.readthedocs.io/en/7.16.0/branch.html#structurally-partial-branches

Native new-case run initially had65 passes, one incorrect test expectation and22
MemoryErrors caused by the test runner's virtual-address-space limit. The publisher
entrypoint test now explicitly selects --apply before testing missing inputs; no
runtime behavior changed. Repeat ONLY those23 cases using the established native
MemoryMax512M/CPUQuota50% isolation:23 passed in15.34s, exit0. All88 new cases now
pass natively. Append measurements to copies of the original data, never overwrite
the full-run evidence: aggregate15315/15315 statements and5316/5316 branches=100%.
The3576 baseline cases plus88 new cases establish3664 distinct passing cases without
another full run. Private reproducible receipts/JUnit/coverage remain under
`/opt/nla-staging/validation-dfb9b12` (full-*, tail-result.json, boundaries-native-*,
boundaries-native-r2-*); original .coverage-full hash verified unchanged.
No product mutation, source recapture, service restart, MAIN or PowerTools change
for this test-only correction. GitHub CI/CodeQL and final storefront QA remain
separate gates; local evidence does not authorize a merge or live cutover.

### Recovery complete; automatic next cycle confirmed — 2026-09-28

The same recovery run `market-20260928t000647z-1b1a8344` completed at11:50:17UTC:
3764 new products published/indexed, remaining0, eligibleExhausted=true,
published=true, indexRefreshed=true. All4070 importer-owned publications are terminal
and present/public/SOLD OUT in the active index; zero uncertain ledger entries.
37 source conflicts remain quarantined; they were not guessed or silently imported.
Completed receipt SHA256
`22dfeb4ab20063d26b08d8b225bbb241880325beb196e5b5ffa87e03772cb693`.

Final refresh `20260928t100300z-274ebd98` activated manifest
`fc3c75e0b1dbb4e70a5d2f5acda3d38feaf0d43d038ffc3f1ac348dd9394b9db`.
Its direct signed backend HTTP/immutable SQL check passed:295865 products,
295861 public items; one new verified GID per game found beyond catalog position25k;
eight prefix cases each returned10 distinct names without cross-game results.
Lightning Bolt returned74 unique products; Pokemon Lightning Bolt returned0.
Private proof: Temp/nla-aruba-staging-20260918/market-20260928-final-search.json.
This is backend proof, not final storefront browser QA. Previous observer is closed.

At14:46UTC, systemd confirmed the next scheduled unit `nla-market-catalog.service`
started autonomously at14:00:14UTC, MainPID257913, activating/start. `/proc/257913`
confirmed a live python3 process for run `market-20260928t140015z-217fbba9`, in
source acquisition. This new scheduled cycle is NOT yet claimed complete.
Market timer active/running; ordinary refresh timer temporarily inactive by the
documented coordination hooks. No manual acquisition, restart or duplicate worker.

### Scheduled cycle stopped on new source exports — 2026-09-28

Later inspection supersedes the running observation above: market service exited1,
MainPID0. Run `market-20260928t140015z-217fbba9/stopped.json` reports selected0,
attempts/batches empty, published=false, indexRefreshed=false. Source progress is
FAILED:2430/2433 expansions,256177 blueprints,37 source anomalies, HTTP404.
This new scheduled cycle did NOT complete; previous successful cycle remains valid.

Official CardTrader v2 reference was consulted again. It documents404 for an
absent/invalid expansion_id. Minimal authenticated GET diagnostics found the first
failing ID4887 still in /expansions; /blueprints/export returned404 again. Two more
bounded GETs confirmed404 for both other pending new expansion IDs:
- 4887: Championship Prize Cards2026 (Yu-Gi-Oh!).
- 4888: Secret Lair Commander Deck: Odds and Ends (Magic).
- 4890: Winner's Pack2026-2027 (Yu-Gi-Oh!).

This source-list/export discrepancy does not authorize treating404 as an empty
success or dropping the missing sets. Existing capture/stop receipts are preserved;
no repeated full capture, importer restart or Shopify write. Ordinary refresh
timer was restored and its17:00CEST service was independently live (PID258579).
Pending market marker blocks another blind run: source recovery/inspection is
still required once exports are available. Do not claim the next timer alone
will clear it, or that the full new-release automation is now finally verified.

### Explicit deferred exports — 2026-09-28

Issue97 correction: only HTTP404 from a listed expansion's blueprint export is
recorded as `deferredExpansions`, with no invented empty file. Other errors and
the capture deadline remain fatal. Comparison verifies every available file,
digest, row/count and anomaly, and reports `sourceComplete=false`. The coordinator
can import/publish verified available candidates, refresh and close an explicitly
partial cycle. The next scheduled cycle retries every expansion, including the
deferred ones. Existing Shopify/PowerTools products and MAIN are untouched.

Official source: https://www.cardtrader.com/it/docs/api/full/reference . The
observed list/export mismatch does NOT establish a release date or prerelease
status. Missing IDs remain explicit, never represented as full coverage.

Verification:91 capture/coordinator tests and100 comparison/reference/importer/
retention/CLI consumer tests passed locally; Ruff and diff checks passed. Legacy
captures are covered. Independent `deferred_export_review` found no remaining
findings after its deadline-boundary correction. No full suite or GitHub CI rerun.
Deployment and inspected recovery are separate subsequent steps; the failed
source receipt is not rewritten as a success.

Deployment: code66c82ee67737666114b2d66dd8fde349fdf857a5 installed at
`/opt/nla-staging/importer-66c82ee`; archive SHA256
900fdc672366e9230ebc17dac4d6c5bcf9f9a7b58c545e05d85c72b7e9fb0d91.
Native Linux100 focused tests passed. Existing recurring unit now points to this
package/SHA ONLY; schedule, limits and channel unchanged. Original unit backed up
at `/opt/nla-staging/nla-market-catalog-before-66c82ee.service`.

One-run source recovery independently reviewed and read-only inspection PASS:
all2430 cached exports hash-valid, zero prior attempts, three missing IDs. It
preserves original failed evidence/source age, retries only the three unavailable
exports and explicitly accounts for404s, then delegates to the existing guarded
import/publication/refresh coordinator. No complete source reacquisition. Helper
SHA256 c61b9c8ed825f8b78776d4e9f645558fd39e9511032878039d59e3c50fd6bbec.
Explicit non-optimized execution guard tested; systemd unit validation PASS.

Activation output confirms job440600 `nla-source-recovery-66c82ee.service` WAITING
after existing job435697 `nla-catalog-refresh.service` RUNNING. This is queued,
NOT proof of recovery completion. No restart/interruption of ordinary refresh.
Follow these existing jobs/receipts, do not launch another recovery or full capture.
GitHub remains owner-held; no push or CI rerun. Goal active, not complete.

### Avoid redundant index rebuilds in empty cycles — 2026-09-28

Recovery `market-20260928t164759z-16735a08` reused2430 exports/256177 blueprints,
deferred4887/4888/4890 explicitly, and found zero candidates/attempts/publications.
It nevertheless started refresh20260928t164953z-e53698bc immediately after the
successful15:00UTC refresh. That existing process is not interrupted or modified.

Future apply cycles now reuse the current index only with zero selections/attempts,
zero new or reconciled publications, and the ordinary freshness check verifying
the actual active manifest/container and source age under24h under the refresh lock.
Pending work or mismatched runtime stops; stale data or any possible changes still
require refresh. The independent ordinary timer continues handling PowerTools.
Receipts explicitly record `indexRefreshed=false`, the reuse reason and freshness;
unavailable source sets still yield partial completion, never false full coverage.

Verification:162 focused coordinator/retention/systemd/CLI/data-boundary tests pass;
Ruff and diff checks pass. Independent deferred_export_review APPROVED. No full
suite, source reacquisition, Shopify write or GitHub CI run for this correction.

Installed code d7e6fc991e36618da994bb511e8b0a37688a0255 for future starts at
`/opt/nla-staging/importer-d7e6fc9`; archive SHA256
5fa4212311ce18ca47057b1feeea4d5f0a1a5739d15f8a17ea897b331d588db6.
Native162 tests PASS with service UMask0077 (first runner omitted it:5 permission
fixture failures,157pass; corrected runner, no weakened tests/guards).
Unit SHA2569d0bbf64324cfbfc2b735a3a651573a19e866c525494d1005cd9869cbf04e9fb;
backup `/opt/nla-staging/nla-market-catalog-before-d7e6fc9.service`.
Only package/SHA changed; no starts/restarts/schedule changes. At17:04:32UTC,
separate recovery PID263793 still uses66c82ee, unit hash unchanged; its existing
refresh20260928t164953z-e53698bc continues. No final recovery receipt yet.

### CardTrader capture interruption — 2026-10-15

The October 14 market failure occurred before any Shopify stage; the pending
marker then blocked the next market invocation. The ordinary October 15 refresh
completed successfully. Bounded retries and sanitized failure context address the
source-capture failure path; inspected recovery remains explicit. See the
[incident evidence and recovery controls](evidence/MARKET-SOURCE-2026-10-15.md).
This correction is tracked on `agent/market-source-recovery-97` against current
main; the historical GitHub hold above no longer applies to this authorized fix.
