# WS-01B — independent audit of the uncommitted taxonomy-v2 artifact

## Disposition

**Rejected as a canonical dataset or implementation source.** Individual design ideas may be reimplemented under review, but the database and uncommitted worktree must not be merged or deployed.

## Artifact verified

| Property | Value |
|---|---|
| Database | `catalog_gateway-taxonomy-v2.sqlite3` |
| Bytes | 958,955,520 |
| SHA-256 | `7c20fe5c2662c5fbdf09a5170b9bff5a9d89f5ffb2f2bdf0ab50d612a945b181` |
| `PRAGMA quick_check` | `ok` |
| Products | 291,795 |
| Classified `single` | 291,791 |
| Classified `sealed` | 4 |
| `unclassified` | 0 |
| Searchable | 291,795 |

File integrity is not the problem. Classification provenance is.

## Blocking findings

1. `shopify_product_type` is empty on all 291,795 records.
2. `shopify_tags_json` is empty on all 291,795 records.
3. Every one of the 291,791 `single` assignments is supported only by membership in a legacy top-level Single collection.
4. The four sealed assignments are supported only by the old `magic-display` and `magic-sigillato` collections; their subtypes are then inferred from title text.
5. The artifact declares zero unclassified records and makes every record searchable even though the existing live-data audit already identifies at least 8,722 high-confidence components, digital codes, sets, accessories or sealed-like records in the extra import.

The old storefront collections are an output of the previous import flow, not an authoritative product-family source. Using them as ground truth reproduces the contamination we are trying to remove.

## Reproduced false classifications

| Source ID | Product | Artifact result | Evidence used |
|---:|---|---|---|
| 812410 | Rare Set - Wings of the Captain (OP06) | `single`, searchable | `singole-one-piece` collection |
| 294127 | 25x Online Code Card | `single`, searchable | `singole-pokemon` collection |
| 15522 | Goblin Token (Red 1/1) | `single`, searchable | `singole-magic` collection |

A diagnostic title scan within the artifact also finds 1,455 `code card`, 1,283 `online code`, 194 `rare set`, eight `sleeves`, three `playmat` and two `booster box` matches classified as searchable singles. These string counts are not the production classifier; they demonstrate the consequence of trusting collection membership.

## Worktree provenance problem

The implementation exists only as uncommitted modifications on top of a different local platform branch. It contains generated coverage files, caches and an external worktree link. Its reported local acceptance used a 65% coverage floor, while the canonical platform gate is 100% for the current foundation. This is not a reviewable chain of custody.

## Salvage policy

The following concepts may be reimplemented in their owner workstreams:

- side-by-side atomic database migration;
- explicit classification evidence and rule versioning;
- family-bound cursors and family-aware search/browse tests;
- price aggregation from variants;
- fail-closed reconciliation.

The following must not be reused as authoritative evidence:

- collection membership as a sufficient `single` classifier;
- unverified product-type mappings for products not observed live;
- broad title subtype patterns as family detection;
- the claim `unclassified = 0`;
- the migrated SQLite database itself.

## Required replacement

WS-01 must export the current structured Shopify fields, then run the reviewed classifier from PR #22. Until that occurs, the only accepted live family fixtures are the four exact `Magic Display` products verified through Admin `productType`, with all other unresolved commercial classes retained as `unclassified` rather than forced into `single`.
