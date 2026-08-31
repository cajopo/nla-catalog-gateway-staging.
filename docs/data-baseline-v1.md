# WS-01 — Shopify Admin Bulk baseline contract v1

## Scope

This slice defines the fail-closed boundary between a read-only Shopify Admin Bulk export and the NLA catalog index. It does not execute Shopify mutations, alter products, alter variants, alter inventory, or publish a theme.

The checked-in GraphQL projection is `docs/contracts/admin-bulk-catalog-v1.graphql`. It must be schema-validated against the selected stable Admin API version before a live Bulk operation is started. A successful schema validation is not evidence that a full export completed.

## Required run inputs

A baseline run is identified by immutable evidence:

- shop domain;
- Admin API version;
- Bulk operation GID;
- operation creation and completion timestamps;
- object count reported by Shopify;
- byte count and SHA-256 of the downloaded JSONL file;
- Online Store publication GID used for publication reconciliation;
- taxonomy contract version and repository commit SHA.

Temporary Shopify download URLs are secrets-by-capability and must not be committed, logged, or copied into the manifest.

## JSONL contract

Every non-empty line must be a JSON object with one of these explicit `__typename` values:

- `Product`;
- `ProductVariant`;
- `Metafield`;
- `ResourcePublicationV2`.

Unknown row types, malformed rows, duplicate product/variant IDs, duplicate handles, unsupported statuses, malformed money, invalid timestamps, invalid GIDs, and orphan children fail the run. There is no skip-and-continue mode.

The parser preserves commercial values as supplied by Shopify:

- product title, product type, vendor, tags and media URL;
- variant SKU, barcode, price, inventory quantity and selected options;
- controlled product metafields;
- Online Store publication state.

It performs no repricing and no inventory normalization. A negative inventory quantity, when supplied by Shopify, is preserved rather than silently clamped.

## Taxonomy boundary

Classification is delegated to the versioned taxonomy contract. The baseline parser supplies only structured facts:

- explicit `nla.game` metafield, when present;
- Shopify `productType`;
- Shopify tags;
- explicit `nla.record_type` metafield, when present;
- commercial title;
- `nla.canonical_card_name`, when present.

The result is exactly one of `single`, `sealed`, `accessory`, or `unclassified`. Unknown or conflicting evidence remains visible as `unclassified` with a reason. Product IDs are not classification rules.

The `sync.productid` metafield is retained as source identity evidence. It is not used to change price, stock, publication, or taxonomy.

## Publication state

Online Store publication is not inferred from `ACTIVE` status. A product is considered published only when its `ResourcePublicationV2` row matches the explicitly supplied Online Store publication GID and reports `isPublished=true`.

## Reconciliation gate

A candidate baseline is acceptable only when all of the following hold:

1. the Bulk operation status is `COMPLETED` and has no partial-data URL;
2. the downloaded bytes match the recorded SHA-256;
3. every JSONL row is parsed or the run fails;
4. every child row has a known parent;
5. `classified + unclassified = total products`;
6. every unclassified product has a machine-readable reason;
7. independent SQL/count checks agree with the manifest;
8. the full active-and-Online-Store-published count is reconciled against a second Shopify read-only query;
9. the four known `Magic Display` products classify as `magic/sealed` without rules tied to their GIDs;
10. no credentials, Bulk URL, customer data, order data, or write-capable token enters the repository or artifact bundle.

## Current state

This commit is the parser/query contract, not the canonical 2026-08-31 dataset. Issue #5 remains open until a fresh full Bulk export, manifest, independent count reconciliation, unclassified report, duplicate report, and reviewer sign-off exist.
