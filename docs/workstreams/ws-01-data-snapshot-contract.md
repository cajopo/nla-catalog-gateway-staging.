# WS-01/1 — canonical Shopify snapshot contract

## Scope

This slice defines and validates the read-only Shopify Admin Bulk snapshot that will replace the incomplete single-oriented projection. It does not build the production catalog index, classify the full dataset, deploy a service or change Shopify.

## Query contract

`graphql/catalog_snapshot.graphql` was validated against the live Admin schema and probed successfully against a real `Magic Display` product before the full Bulk query was started.

The snapshot contains, for every product:

- immutable product identity, handle, commercial title, status and timestamps;
- `productType` and exact tags for family/game/language evidence;
- featured media metadata and CDN URL;
- both `sync.productid` and `powertools.id`;
- publication state and catalog title;
- every variant with SKU, price, compare-at price, quantity and inventory policy;
- inventory item tracking and per-location quantities.

It deliberately excludes descriptions and SEO text from the search-data contract. Those fields are not needed to classify identity and must not become accidental search-match sources.

Query SHA-256: `7c23beb66608c085fc92d0b87399781b9f1693be9335ee98d72fa5335d70a704`.

## Running operation

A read-only Bulk query was started on 31 August 2026:

- operation: `gid://shopify/BulkOperation/9766734758156`;
- initial state: `CREATED`;
- first observed running count: 323,897 objects;
- mutation user errors: zero.

The temporary signed result URL must never be committed or copied into reports. Only operation ID, terminal status, timestamps, byte count, line count and SHA-256 are retained.

## Validator

`scripts/validate_bulk_snapshot.py` opens the JSONL locally and produces a bounded manifest. The raw snapshot remains outside Git.

Blocking checks include:

- every line is valid JSON and has a known `__typename`;
- Product, ProductVariant, ResourcePublicationV2 and InventoryLevel records contain the required fields;
- Shopify GIDs are type-correct and unique;
- child records reference existing products or inventory items;
- every product has at least one variant;
- one-sided, mismatched or nonnumeric PowerTools/sync identities fail closed;
- expected product count, when supplied, must match exactly;
- all violations are counted, with at most 100 details retained in the manifest.

Nonblocking but reported evidence includes:

- product status and product-type distribution;
- products published to Online Store;
- media coverage;
- products with both source IDs absent;
- duplicate source-ID groups, because the four known pilot/commercial pairs require explicit downstream handling rather than silent rejection.

The validator computes the snapshot digest while reading the file and the independent query digest from the committed GraphQL file.

## Acceptance status

- live schema validation: PASS;
- live one-product permission/shape probe: PASS;
- read-only Bulk operation launch: PASS, terminal result pending;
- synthetic contract tests: 8 PASS;
- line and branch coverage of package under test: 100%;
- full snapshot download/hash/JSONL validation: pending terminal Bulk status;
- full taxonomy classification: pending merge with WS-01B and source adapters.

## Next gate

The operation result is accepted only if:

1. status is `COMPLETED` with no error or partial-data fallback;
2. the downloaded byte count equals Shopify `fileSize`;
3. manifest structural validity is true;
4. Product count reconciles with the current Admin baseline;
5. source identity anomalies and duplicate groups are enumerated;
6. the snapshot and query SHA-256 values are frozen;
7. the complete artifact remains outside source control.
