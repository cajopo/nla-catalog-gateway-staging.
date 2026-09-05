# WS-01d — split snapshot reconciliation candidate

## Status and boundary

This issue-#32 slice replaces the non-submittable six-connection query candidate with two
read-only Shopify Admin Bulk query documents and a local deterministic reconciliation reference
model. It does not call Shopify, start a Bulk operation, download a result, retain a signed URL,
write a repository snapshot/database, activate a dataset, promote a capability, mutate Shopify or
PowerTools, or change a theme.

Issue #43 is the separate real-baseline gate and runner-hardening follow-up. It preserves the
issue-#32 evidence model while adding pinned input handles, hostile NTFS path rejection and
identity-safe staged output publication required before a current capture can be accepted.

Repository fixtures and committed executable evidence remain conspicuously synthetic. The current
capture and all generated artifacts remain outside Git. The independently reviewed frozen run on
candidate `2543575fe00144627ae433a56e11e9e249cef8e7` completed with exit zero and status `ok`, and
its subsequent value-free audit was `APPROVED`. This establishes reviewable issue-#43 real-baseline
evidence only: the output remains provisional and no dataset activation or capability promotion
was performed.

## Query split and schema evidence

The packaged query documents are:

- `graphql/catalog_products_snapshot.graphql`: root `products`, nested
  `resourcePublicationsV2`, and Product `nlaMetafields` (three connections, maximum depth two);
- `graphql/catalog_variants_snapshot.graphql`: root `productVariants`, Variant `nlaMetafields`,
  and InventoryItem `inventoryLevels` (three connections, maximum depth two).

The ProductVariant root explicitly selects `product { __typename id }`; it cannot inherit Product
ownership from a different Bulk operation. For this root-ProductVariant query, Shopify Bulk emits
each nested InventoryLevel with its root ProductVariant as `__parentId`; reconciliation requires
that typed parent to have been inserted, resolves its exact InventoryItem GID, and requires the
InventoryLevel GID's `inventory_item_id` parameter to match. The InventoryLevel path component is
an opaque canonical positive-decimal identity, not a Location ID; the typed Location GID is
validated separately. Metafields in the first part must have Product owners and those in the
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
- InventoryLevels without an already observed typed ProductVariant parent, with a mismatched
  InventoryItem parameter, or with duplicate InventoryItem/Location ownership;
- one InventoryItem assigned to multiple ProductVariants;
- duplicate/conflicting Product handles;
- disagreement between verified sync and PowerTools source identities;
- missing exact Online Store publication evidence;
- root, typed-object, status or active-published accounting mismatches; and
- any SQLite integrity or `quick_check` failure.

Duplicate titles, SKUs, barcodes and secondary values across otherwise distinct records are not
used as joins. Secondary source identity is preserved per Product and is only an independently
accounted consistency signal: pairing, exact alias equality and field types remain mandatory, but
global uniqueness is not a reconciliation invariant. Input part order cannot affect the canonical
source manifest, taxonomy result, catalog record bytes or dataset-manifest bytes.

The two reviewed source-identity aliases have distinct exact Shopify types. `syncProductId` must
be `number_integer`; `powertoolsId` must be `single_line_text_field`. Both values must still be
canonical positive decimal digits. The runner does not accept either type interchangeably. Issue
#43's redacted full-Product diagnostic observed those two types, valid digits and equality between
the aliases for every Product in the current capture; this corrects the earlier synthetic-only
assumption without weakening the identity fence.

The successful frozen run and value-free audit account for all 291795 Products and 293866 Variants,
with paired, equal sync and PowerTools aliases on every Product. They found four duplicated
secondary-value groups covering eight Products, with maximum multiplicity two and exactly one
`ACTIVE` plus one `UNLISTED` Product in each group. Their distinct Shopify Product GIDs remain the
sole primary identities; reconciliation preserves every Product and does not merge, drop or
deduplicate on a secondary value. Any later global-uniqueness policy belongs to the sync
workstream and is not an activation claim in issue #43.

## Projection and accounting

Only a fully reconciled generation is converted into `ProductFacts`, classified by the existing
issue-#19 taxonomy, then reconstructed as exact `CatalogProductRecordV1` values. Every source
Product is included: classified plus reasoned unclassified equals source count, with zero silent
exclusions. Product/Variant/status/source-identity/active-published counts flow into
`DatasetManifestV1`, whose existing validation checks the exact record set.

The synthetic fixture exercises Product and ProductVariant metafield owners, root-ProductVariant
InventoryLevel parent links, distinct InventoryLevel/InventoryItem/Location identities, typed GIDs
above `2^53`, duplicate titles/SKUs, zero inventory, zero price text, order independence,
mixed/partial captures, missing and orphan children, duplicate/conflicting rows, secondary
identity conflicts, hostile values and every defensive branch. It contains no real Shopify row or
commercial value.

All runtime capabilities remain at their existing provisional/unsupported states. This is
reviewed issue-#43 real-baseline evidence, not evidence that global browse, search, filters,
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
remain enforced by the reconciliation model. Every input rejects alternate-data-stream syntax,
unsafe trailing-dot/space components and every filesystem reparse-point ancestor, not only
symlinks and junctions. This real-baseline runner has an explicit local Windows/NTFS filesystem
backend: it uses Win32 handles opened without write/delete sharing and fails closed when those
primitives, their sharing guarantees or native rename are unavailable. It has no weaker
cross-platform or path-based fallback. `GetVolumePathNameW`, `GetDriveTypeW` and
`GetVolumeInformationW` must identify every input and the output parent as the local fixed NTFS
volume boundary; UNC/network paths and FAT, exFAT, ReFS or unknown filesystems are rejected.
Unsupported device namespaces are rejected before any open. For supported normal, extended-length
drive, volume-GUID, 8.3 and SUBST spellings, repository containment is decided from
`GetFinalPathNameByHandleW(..., VOLUME_NAME_GUID)` on the exact opened object, using
case-insensitive canonical component boundaries. It is never decided from a lexical prefix.

After preliminary path and filesystem validation, the runner pins each input to one persistent
handle and holds all seven pinned handles through reconciliation and output publication. The two
large JSONL streams are consumed only through those pinned,
write/delete-denying handles, with handle state checked around every scan. The two reviewed query
documents and three bounded control documents are copied to immutable byte values while the same
locks are held, and all later parsing and query checks consume only those frozen bytes. No code
path reopens consumed bytes by path after pinning. Atomic replacement and same-inode, same-size
changes with restored timestamps are therefore denied or cannot alter the consumed evidence. The
output parent must already exist
without any reparse-point alias. The requested output directory must be new and outside this
repository: its parent and later staging/published target remain bound to canonical directory
handles; existing targets, traversal, aliases and every unsafe path component fail closed. Every
one of the seven input file handles is also enumerated with `FileStreamInfo`: exactly one unnamed
`::$DATA` stream with the handle-reported byte size is required, so a named NTFS stream on the
carrier fails closed without relying on path spelling.

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
path or raw JSONL row. Each canonical Product record is limited to 2 MiB before its single JSONL
LF delimiter is added; an oversized record fails before any of its bytes are written. The dataset
content SHA-256 is streamed over the same canonical envelope and ordered per-record bytes as the
legacy renderer, without materializing a second all-record JSON tree or byte string. Consumers can
parse every line and require byte-identical canonical re-encoding. Files are created exclusively,
flushed and fsynced in an unpredictable
sibling staging directory. Each live file handle is bound to its expected device/inode, byte count
and SHA-256 and is checked before publication. Because Windows does not provide a portable
contract for renaming a directory while child handles remain open under their required access and
share modes, they are closed only after this pre-publish seal; the directory itself remains bound
to its native handle and is renamed with `SetFileInformationByHandle`. A sharing violation or
unsupported native rename fails closed with no path-based fallback. Immediately after the rename,
all seven files are reopened with exact read/delete handles that deny write and replacement, and
every identity, byte count and SHA-256 is checked again while all seven handles remain held. Each
check also requires the exact
unnamed-stream-only shape. For the single publish-attestation linearization point, all seven exact
carrier handles are marked delete-pending together. While every guard remains active, the runner
rechecks every handle-bound identity, size, SHA-256 and stream list, then the exact seven-name
directory shape, canonical handle path and absence of directory ADS. ADS creation on any guarded
carrier is blocked by NTFS. Only after this simultaneous observation does the runner roll back all
seven delete flags and close their handles. The reconciliation summary is created last. Directory
shape, canonical path and directory ADS are checked before and after native rename and once more
immediately before the directory lease closes. A persistent eighth file makes publication fail,
and cleanup removes only the seven owned artifacts while preserving the foreign file.

Cleanup uses `ReOpenFile` and `FileDispositionInfo` (or an already delete-capable sealed handle) to
delete only the exact file object owned by the run, then applies the same handle-bound disposition
to the staging/published directory. It never unlinks or removes a directory by path, never recurses
and preserves an identity-mismatched replacement. Because ordinary share modes do not protect
named NTFS streams, cleanup first marks the exact object delete-pending, then enumerates its streams
on that same handle. Delete-pending blocks a late ADS creation. Any pre-existing or concurrently
opened named stream causes an immediate `DeleteFile=FALSE` rollback before close; when that native
rollback succeeds, both carrier and foreign stream are preserved. A rollback failure is itself a
fail-closed filesystem error and cannot support a preservation claim. The same protocol protects
the directory. Deterministic adversarial
tests cover all seven input carriers, ADS before/after output writes and seals, staging and
post-rename directory ADS, restored same-inode input mutation, post-write/pre-seal artifact
tampering, replacement after exact cleanup handle acquisition and native rename failure.

These checks attest only the guarded point-in-time publish boundary; they do not claim OS-level
immutability after the delete guards are released, during handle close, or after the runner
returns. The success metadata includes the in-memory SHA-256 of the canonical reconciliation
summary. That expected digest must travel separately with the handoff. The downstream issue-#01F
consumer must independently require the exact seven-file shape, reject every named stream on the
directory and carriers, match that expected summary SHA-256 and revalidate all summary-bound sizes
and SHA-256 values before use. A post-release mutation is external state and must make that consumer
gate fail. Linux CI exercises all portable parsing,
reconciliation, publication and failure logic with a deterministic test-only filesystem backend,
while also proving that the production runner rejects an unavailable Win32 backend. The real
Win32 handle/share/rename/delete, `FileStreamInfo` and canonical volume-GUID integration tests run
separately on local fixed NTFS. Hosts without usable 8.3 or SUBST aliases exercise the identical
canonical-containment branch through deterministic native-path fixtures, without skips or xfails;
the test backend is never selected by production code.

The first issue-#43 invocation against the current Shopify-derived capture failed closed before
publishing an output directory. Redacted diagnostics proved both immutable part manifests valid,
then isolated the first failure to the initial Product insertion: the earlier runner required
`number_integer` for both source aliases even though the PowerTools alias is uniformly the exact
`single_line_text_field` described above.

A second frozen invocation on candidate
`b0033d2a6890ac555472495fba73aa5827495f65` after that correction again validated both immutable
part manifests, then failed closed at the first InventoryLevel in the variants semantic pass. The runner had
incorrectly required its flattened `__parentId` to be an InventoryItem rather than its root
ProductVariant and had incorrectly equated the opaque InventoryLevel identity with the Location
identity. The final target, private staging directory and temporary reconciliation database were
all absent afterward; no dataset was activated and neither Shopify nor PowerTools was mutated.
That InventoryLevel correction was independently re-reviewed before the subsequent frozen
invocation described below; the second-run evidence by itself did not change the real-baseline,
distribution, staging or capability status above.

A third frozen invocation on candidate `2684f02d348f14682161ff0fe6ab276efa09ccc4`
completed both Products and variants semantic passes and satisfied all earlier manifest, identity,
publication, variant and inventory fences. It then failed closed at the global uniqueness check for
secondary source identities. A subsequent value-free aggregate probe established the distribution
recorded above and showed that Shopify Product GID, not the repeated secondary value, remains the
correct identity boundary. The final target, private staging directory and temporary database were
again absent afterward; no dataset was activated and neither Shopify nor PowerTools was mutated.

A fourth frozen invocation on independently approved candidate
`2543575fe00144627ae433a56e11e9e249cef8e7` completed with exit zero and status `ok`. It accounted
for all 291795 Products and 293866 Variants and atomically created exactly seven external
provisional artifacts. The separately captured reconciliation-summary SHA-256 is
`9f17942d891fac4bb3bac7df0009d26182c16bee2408c1a57b14ec1395c4edb0`; the bound dataset generation
is `sha256:5ddd4d73bc875d4e6660e3d84582bf5b8539f771ce2770922697e53319667a6c` and the source generation is
`sha256:6041a94b6a2dfe60f774eee7c04e8a4058a8e7b85546b57c6070075d23d36116`.

The value-free post-run audit returned `APPROVED`: it checked the exact seven-file shape, separate
summary trust root, canonical and cross-linked manifests, two stable size/hash passes, every
catalog line's 2 MiB bound and byte-identical contract round-trip, global Product/handle/Variant/
InventoryItem identity and ordering, incremental catalog digest, aggregate counts, fixed-NTFS
file identity/stream boundaries and complete temporary cleanup. Both frozen snapshot hashes and
all five control/query hashes remained unchanged. The artifacts still state
`reconciled-provisional`, `datasetActivation: not-performed` and
`capabilityPromotion: not-performed`; no dataset was activated and neither Shopify nor PowerTools
was mutated.
