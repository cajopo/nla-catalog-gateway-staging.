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
