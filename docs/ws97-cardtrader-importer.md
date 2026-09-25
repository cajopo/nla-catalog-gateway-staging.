# WS97 — CardTrader missing-printing importer

Issue: https://github.com/cajopo/nla-catalog-gateway-staging./issues/97

Owner confirmation (2026-09-25): create verified missing card printings as new
Shopify DRAFT/unpublished/zero-stock products. Existing products, PowerTools,
MAIN theme and publication remain untouched. No invented selling prices or
language/condition/finish. Gateway/normal refresh stay read-only.

## Current increment

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
