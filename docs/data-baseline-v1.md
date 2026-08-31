# WS-01 — Shopify Admin Bulk baseline contract v1

## Scope

This slice defines the fail-closed boundary between a read-only Shopify Admin Bulk export and the NLA catalog index. It does not execute Shopify mutations, alter products, alter variants, alter inventory, or publish a theme.

The checked-in GraphQL projection is `docs/contracts/admin-bulk-catalog-v1.graphql`. It must be validated both against the selected stable Admin API schema and against Shopify Bulk-operation query restrictions before a live operation is started. Passing schema validation is not evidence that a full export completed.

## Required run evidence

A baseline run is identified by immutable evidence:

- shop domain;
- Admin API version;
- Bulk operation GID;
- operation creation and completion timestamps;
- object count reported by Shopify;
- byte count and SHA-256 of the downloaded JSONL file;
- Online Store publication GID used for reconciliation;
- taxonomy rule version and repository commit SHA.

Temporary Shopify download URLs are secrets-by-capability and must not be committed, logged, or copied into manifests.

## JSONL accounting

Every non-empty line must be a JSON object whose `__typename` is exactly one of:

- `Product`;
- `ProductVariant`;
- `Metafield`;
- `ResourcePublicationV2`.

The manifest records counts by row type. Unknown types, malformed rows, duplicate IDs, duplicate handles, duplicate owner/namespace/key metafields, duplicate product/publication pairs, malformed money, invalid timestamps, invalid GIDs, orphan children, products without variants, and exports without products fail the entire run. There is no skip-and-continue mode.

Product-owned and variant-owned metafields are retained separately. No accepted child row is discarded.

## Commercial-data boundary

The parser preserves Shopify values:

- product title, product type, vendor, tags and featured-media URL;
- variant title, SKU, barcode, price text, signed inventory quantity and selected options;
- controlled product and variant metafields;
- publication state.

It performs no repricing, no stock normalization and no availability override. A negative inventory quantity, when returned by Shopify, is retained rather than silently clamped.

## Taxonomy boundary

Classification is delegated to the versioned taxonomy contract and receives only structured facts: explicit `nla.game`, Shopify `productType`, tags, explicit `nla.record_type`, commercial title and `nla.canonical_card_name`.

Every product becomes exactly one of `single`, `sealed`, `accessory`, or `unclassified`. Unknown or conflicting evidence remains visible as `unclassified` with a reason. Product GIDs are never classification rules.

The `sync.productid` metafield is retained as source-identity evidence. It is not allowed to change price, inventory, publication or taxonomy.

## Publication state

`ACTIVE` does not imply Online Store publication. A product is considered published only when a `ResourcePublicationV2` row matches the explicitly supplied Online Store Publication GID and has `isPublished=true`.

## Acceptance gate

A candidate canonical baseline is acceptable only when:

1. the Bulk operation status is `COMPLETED` and no partial-data URL is present;
2. downloaded bytes match the recorded SHA-256;
3. every JSONL row is parsed and accounted for, or the run fails;
4. all children resolve to known parents;
5. every Product resolves to at least one ProductVariant;
6. `classified + unclassified = total products`;
7. every unclassified product has a machine-readable reason;
8. independent SQL/count checks agree with the manifest;
9. active-and-Online-Store-published count is reconciled against a second Shopify read-only query;
10. the four known `Magic Display` products classify as `magic/sealed` without GID-specific rules;
11. no credentials, Bulk URL, customer/order data or write-capable token enters the repository or evidence bundle.

## Current state

This is a parser/query contract, not the canonical 2026-08-31 dataset. Issue #5 remains open until a fresh full Bulk export, manifest, independent count reconciliation, unclassified report, duplicate report and reviewer sign-off exist.
