# WS-01d — split snapshot reconciliation candidate

## Status and boundary

This issue-#32 slice replaces the non-submittable six-connection query candidate with two
read-only Shopify Admin Bulk query documents and a local deterministic reconciliation reference
model. It does not call Shopify, start a Bulk operation, download a result, retain a signed URL,
write a repository snapshot/database, activate a dataset, promote a capability, mutate Shopify or
PowerTools, or change a theme.

`NLA_DATA_ROOT` is missing on this host. All executable evidence described here is conspicuously
synthetic. Real-baseline acceptance, distributions and capability promotion remain blocked on a
separate independently reviewed run with the external data root.

## Query split and schema evidence

The packaged query documents are:

- `graphql/catalog_products_snapshot.graphql`: root `products`, nested
  `resourcePublicationsV2`, and Product `nlaMetafields` (three connections, maximum depth two);
- `graphql/catalog_variants_snapshot.graphql`: root `productVariants`, Variant `nlaMetafields`,
  and InventoryItem `inventoryLevels` (three connections, maximum depth two).

The ProductVariant root explicitly selects `product { __typename id }`; it cannot inherit Product
ownership from a different Bulk operation. InventoryLevel JSONL parent IDs are accepted only as
typed InventoryItem GIDs. Metafields in the first part must have Product owners and those in the
second part ProductVariant owners. The model never joins by title, handle, SKU, barcode, source ID
or numeric conversion.

Both documents passed the bundled Shopify Admin `2026-04` schema validator locally on 2026-09-05
with instrumentation disabled. The successful evidence IDs were `nla32-products-7c4a1f` revision
6 and `nla32-variants-4d92be` revision 6. The validator reported these scope sets verbatim:

- products part: `read_products`, `read_files`, `read_themes`, `read_orders`,
  `read_draft_orders`, `read_images`, `read_quick_sale`, `read_publications`;
- variants part: `read_products`, `read_inventory`, `read_locations`, `read_markets_home`.

Those are validator output, not an installation request or a claim that all listed scopes should
be granted. Minimum app scopes and live executability require a separate authorized app/install
review. No metafield definition or value is created here: the documents only read existing
merchant/integration-owned namespaces required by the established source contract.

The GraphQL files are included in the source distribution through `MANIFEST.in`; they are review
inputs and runtime-external execution artifacts, not Python package data.

## Immutable part evidence

Each completed part is bound to a canonical manifest containing the part name, schema version,
snapshot-set ID, exact shop/API version/operation ID and type, terminal status/error/URL flags,
creation/completion times, Online Store Publication GID, independently supplied source-code SHA,
query SHA-256, raw JSONL SHA-256, byte/object/root counts and complete per-typename counts.

Manifest creation accepts one exact frozen `BulkOperationTerminalEvidenceV1`, reconstructs it at
the trust boundary, and accepts only a `QUERY` operation in exact `COMPLETED` state with null
`errorCode`, a result URL and no partial-data URL. The query text returned by Shopify must equal
the local LF bytes or the one measured Shopify transport representation defined below; the
canonical local bytes must also match the reviewed part-specific query hash.
The terminal `fileSize`, `objectCount` and `rootObjectCount` must independently match the rescanned
JSONL and the trusted expected root count. A fake `shop { id }` query therefore cannot attest a
Product or ProductVariant snapshot even when its own file and terminal query text agree.

Creation/completion timestamps are parsed as timezone-aware instants, reject RFC 3339 `-00:00`,
and are normalized to canonical UTC `Z`. Each operation and their combined capture are bounded to
24 hours. The Product and ProductVariant operation windows must overlap; two sequential captures
months apart are rejected even if a caller repeats the same snapshot-set ID. The fence limit,
canonical endpoints and elapsed seconds are included in the part/source manifests and generation
digests. `DatasetManifestV1.generatedAt` is selected by parsed UTC chronology, not lexical text.

A part generation is a SHA-256 over canonical JSON with the `nla-snapshot-part-v1` domain.
Reconciliation reconstructs exact manifests from canonical bytes, rehashes both files and rejects
duplicate parts, paths, operations, queries, changed contents or any mixed capture fence.

The two-part query and snapshot hashes are hashes of canonical part-labelled structures, with
separate `nla-split-query-set-v1` and `nla-split-snapshot-set-v1` domains. The reconciled source
generation uses a third `nla-reconciled-source-v2` domain. This is order-independent with respect
to part arrival and avoids ambiguous raw concatenation. Each part content hash still identifies
the exact downloaded byte stream, as required for independent verification.

## Deterministic fail-closed join

Both files are streamed into a private temporary strict SQLite database. A global canonical-row
identity table rejects duplicate and conflicting typed Product, ProductVariant, InventoryLevel,
Metafield and ResourcePublication identities even across part boundaries. Shopify GIDs remain
canonical unbounded decimal text, preserving values beyond JavaScript's `2^53` integer boundary.

Reconciliation rejects:

- missing/excess ProductVariant children against every Product `variantsCount.count`;
- orphan ProductVariants, InventoryLevels, Metafields or publication rows;
- ProductVariants without explicit typed Product and InventoryItem ownership;
- one InventoryItem assigned to multiple ProductVariants;
- duplicate/conflicting handles or matching secondary source IDs assigned to different Products;
- disagreement between verified sync and PowerTools source identities;
- missing exact Online Store publication evidence;
- root, typed-object, status or active-published accounting mismatches; and
- any SQLite integrity or `quick_check` failure.

Duplicate titles, SKUs, barcodes and secondary values across otherwise distinct records are not
used as joins. Secondary source identity is only an independently accounted consistency signal.
Input part order cannot affect the canonical source manifest, taxonomy result, catalog record
bytes or dataset-manifest bytes.

## Projection and accounting

Only a fully reconciled generation is converted into `ProductFacts`, classified by the existing
issue-#19 taxonomy, then reconstructed as exact `CatalogProductRecordV1` values. Every source
Product is included: classified plus reasoned unclassified equals source count, with zero silent
exclusions. Product/Variant/status/source-identity/active-published counts flow into
`DatasetManifestV1`, whose existing validation checks the exact record set.

The synthetic fixture exercises Product and ProductVariant metafield owners, InventoryItem parent
links, typed GIDs above `2^53`, duplicate titles/SKUs, zero inventory, zero price text, order
independence, mixed/partial captures, missing and orphan children, duplicate/conflicting rows,
secondary identity conflicts, hostile values and every defensive branch. It does not contain or
claim real Shopify observations.

All runtime capabilities remain at their existing provisional/unsupported states. This candidate
is evidence for a later real-baseline gate, not evidence that global browse, search, filters,
incremental sync or live serving is production-ready.

## Offline reconciliation CLI

`scripts/reconcile_split_snapshot.py` is the operational, network-free entry point for a later
authorized capture. It only consumes files that already exist. It neither starts nor polls a Bulk
operation, downloads a result URL, calls Shopify, writes SQLite outside the reconciliation
module's private temporary directory, nor changes any product, publication, theme or PowerTools
state.

All paths must be absolute and normalized. The two JSONL parts and all three control documents
must be regular, single-link files outside this repository. The two query files may be the tracked
reviewed documents or byte-identical external copies; their approved part-specific SHA-256 values
remain enforced by the reconciliation model. The output parent must already exist without
symlinks or junctions. The requested output directory must be new and outside this repository:
existing targets, traversal, filesystem aliases, Windows alternate-data-stream syntax and unsafe
trailing-dot/space components fail closed.

The expectation document is strict JSON, at most 64 KiB, with exactly these fields:

- integer `schemaVersion` equal to `1`;
- `snapshotSetId`, `shopDomain`, `apiVersion`, `onlineStorePublicationGid` and
  independently supplied `sourceCodeSha`;
- independent integer `productCount`, `variantCount` and
  `expectedActiveOnlineStorePublishedProductCount` fences.

Each part has a separate strict terminal-evidence document, also at most 64 KiB, containing
exactly `schemaVersion`, `operationId`, `operationType`, `status`, `errorCode`, `query`,
`createdAt`, `completedAt`, `fileSize`, `objectCount`, `rootObjectCount`, `urlPresent` and
`partialDataUrlPresent`. It must be sanitized before use: the actual `url` and `partialDataUrl`
values, request headers, tokens and every other field are forbidden. The boolean flags attest only
the terminal presence/absence conditions. The terminal `query` text must equal the corresponding
approved local query bytes exactly, except for Shopify's measured terminal transport. That one
representation is accepted only when it is byte-for-byte equal to the approved LF artifact after
replacing every LF with CRLF and appending exactly one additional CRLF. Canonical LF text remains
valid for synthetic/offline evidence. Mixed line endings, CRLF without the extra terminal newline,
LF with an extra newline, multiple extra newlines, whitespace trimming and every content change
are rejected. The reconciliation summary records the raw terminal-query SHA-256, approved query
SHA-256 and selected transport label for each part; it never records the query text.

Duplicate or unknown JSON keys, BOMs, floats, non-finite numbers, surrogates, wrong exact types,
invalid GIDs/domains/versions/timestamps, counts outside signed 64-bit bounds, inconsistent
terminal sizes/counts and mixed captures all fail before the output directory is created. CLI
failure output is one fixed message; it does not echo a path, source value, URL or exception.

Example invocation after an independently authorized download and sanitization step:

```bash
python scripts/reconcile_split_snapshot.py \
  --products-jsonl /external/capture/products.jsonl \
  --variants-jsonl /external/capture/variants.jsonl \
  --products-query /reviewed/graphql/catalog_products_snapshot.graphql \
  --variants-query /reviewed/graphql/catalog_variants_snapshot.graphql \
  --products-terminal /external/control/products-terminal.json \
  --variants-terminal /external/control/variants-terminal.json \
  --expectation /external/control/reconciliation-expectation.json \
  --output-directory /external/generations/candidate-001
```

The new directory is published with a fixed seven-file shape:

- canonical Product and ProductVariant part manifests;
- canonical reconciled source and dataset manifests;
- canonical taxonomy report;
- `catalog-records.v1.jsonl`, one canonical `CatalogProductRecordV1` per line; and
- a canonical reconciliation summary binding fixed filenames to SHA-256, byte and record counts,
  plus the two terminal-query transport audits.

The derived record stream is necessary for downstream pagination, search, facet and runtime
workstreams to consume the exact same reconciled generation without reopening raw Shopify JSONL.
It is not a raw snapshot or a public-serving index, but it is still a generated catalog artifact:
the CLI therefore permits it only outside the repository. The summary explicitly records
`reconciled-provisional`, `datasetActivation: not-performed` and
`capabilityPromotion: not-performed`. No output file contains a signed Bulk URL, control-document
path or raw JSONL row. Files are created exclusively, flushed and fsynced; any ordinary failure
after directory creation removes only the fixed regular files created during that attempt and
then removes the empty directory, never using recursive deletion.

The CLI's executable evidence remains synthetic on this host. It has not been run against the
frozen historical database or a current Shopify-derived capture, so it does not change the
real-baseline, distribution, staging or capability status above.
