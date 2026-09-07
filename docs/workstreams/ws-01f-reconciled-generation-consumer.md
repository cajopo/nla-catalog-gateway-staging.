# WS-01F reconciled generation consumer

Issue: #46
Producer dependency: #43
Scope: local, read-only verification of one external reconciled generation

## Purpose

WS-01F is the trust boundary between the external provisional bundle produced by
WS-01D and the in-memory catalog cores. It reopens the bundle from an independently
supplied directory, authenticates the reconciliation summary against an independently
supplied SHA-256 trust root, verifies every carrier and relationship, and only then
returns a canonical generation in memory.

This workstream does not discover a bundle, fetch a trust root, activate or promote a
dataset, publish a capability, create a serving index, or call Shopify. The word
`Verified` in the return type describes the result of this local bundle check only. It
does not change the provisional capability matrix embedded in the dataset manifest.

## Public contract

```python
open_reconciled_generation(
    directory: Path,
    expected_summary_sha256: str,
) -> ContextManager[VerifiedReconciledGenerationV1]
```

The yielded value exposes only:

- the canonical `ReconciledCatalogGenerationV1` held in memory; and
- the lowercase summary SHA-256 supplied through the separate trust channel.

It does not expose the source directory, native handles, raw summary object, filesystem
backend, verification stages, or operational diagnostics. Its representation is
value-free so an accidental `repr` cannot emit catalog data.

`directory` must be an exact concrete `Path`, absolute and normalized. The trust root
must be an exact `str` containing 64 lowercase hexadecimal characters, with no
`sha256:` prefix. Subclasses and coercions are not accepted.

All public failures use fixed, value-free `GenerationBundleError` messages. Paths,
digests, filenames derived from an input, JSON values, commercial fields, operating
system messages and native error codes are not included in a public error. Internal
exception chaining is suppressed at the public boundary. All acquired handles are
closed on success, rejection and caller exceptions.

## External trust root

The expected summary digest is mandatory and must travel separately from the bundle.
It is never read from a file in the generation directory, inferred from another
manifest, discovered from Git, accepted from a sibling sidecar, or replaced by a
dataset/source generation identifier.

The consumer opens and pins all seven carriers before reading their contents, but the
summary is the first carrier whose bytes are consumed. Its size is bounded and its
SHA-256 is compared with `expected_summary_sha256` before any other artifact content is
read. A mismatch rejects the bundle without parsing or trusting the other carriers.

The authenticated summary binds the fixed artifact names, byte counts, record counts
and SHA-256 values. Authentication does not replace semantic verification: every
manifest, record and cross-link is independently reconstructed and checked.

## Exact bundle shape

The directory contains exactly these seven names and no other entry:

1. `catalog-records.v1.jsonl`
2. `dataset-manifest.v1.json`
3. `products-part-manifest.v1.json`
4. `reconciliation-summary.v2.json`
5. `source-manifest.v2.json`
6. `taxonomy-report.v1.json`
7. `variants-part-manifest.v1.json`

The summary's `artifacts` array deliberately excludes the summary itself. Its six
entries are ordered exactly as catalog records, dataset manifest, Products part
manifest, source manifest, taxonomy report and Variants part manifest. Each entry has
exactly `bytes`, `filename`, `recordCount` and `sha256`. Static JSON artifacts have a
record count of one; the JSONL count equals `catalogRecordCount`.

The summary must have schema version 2 and retain all three provisional fences:

- `status` is `reconciled-provisional`;
- `datasetActivation` is `not-performed`; and
- `capabilityPromotion` is `not-performed`.

Its terminal-query audits are exactly Products followed by Variants. Each audit binds
the approved query hash to its part manifest, contains a syntactically valid raw
terminal-query hash and uses one of the two frozen transport labels. The original raw
terminal query is not part of this bundle, so its hash is authenticated by the
separate summary trust root rather than recomputed by this consumer.

`canonicalNameAudit` is either null when no external canonical-name sidecar
participated (the legacy Shopify-only path), or an exact audit object for an external
canonical-name sidecar.
The object binds the independently pinned manifest and mapping hashes plus byte,
record, matched-key, matched-Product, duplicate-Product and unused-mapping counts.
Its accounting must reconcile exactly; it never embeds a name, source ID or path.

## Canonical content contract

All JSON documents use canonical UTF-8 bytes: no BOM, duplicate or unknown keys,
floats, non-finite numbers, Unicode surrogates, CR characters, insignificant
whitespace or trailing newline. Integers are exact signed 64-bit values where the
contract permits them. A parsed document must re-encode byte-for-byte to its original
carrier.

The existing strict decoders are used for:

- `SnapshotPartManifestV1` for each part manifest;
- `DatasetManifestV1` for the dataset manifest; and
- `CatalogProductRecordV1` for every JSONL record.

`ReconciledSourceManifestV2` and `ClassificationReport` are not populated from
untrusted dictionaries. The consumer reconstructs them from the two typed part
manifests and the complete typed record tuple, then compares the resulting canonical
bytes with the supplied source and taxonomy carriers.

The two part manifests must be Products then Variants, use the reviewed part-specific
query hashes, share the snapshot set, shop, API version, Online Store publication and
source-code commit, use distinct Bulk operations, and satisfy the overlapping
24-hour capture fence. Their part generations are recomputed by the existing strict
decoder.

The source query-set, snapshot-set and source-generation hashes are recomputed with
their frozen domains. Product, Variant, InventoryItem, InventoryLevel, publication,
metafield, status, source-identity and active-published counts must reconcile across
the part manifests, source manifest and complete record set.

The dataset manifest must equal the generation rebuilt from the source manifest,
taxonomy report and records. This includes its source-manifest hash, source query and
snapshot hashes, taxonomy version, catalog-content hash, dataset generation, generated
time, all included/excluded splits, family/status counts and public-item count. Its
capability matrix remains the exact frozen provisional matrix and contains no
`verified` state.

The taxonomy report is rebuilt from the records, including family/game counts, rule
counts, unclassified reasons and subtype reasons. Its canonical bytes must equal the
taxonomy carrier.

## Catalog JSONL

The catalog is read with an explicitly bounded `readline` operation. Each non-empty
record is at most 2 MiB before its single LF delimiter. CRLF, blank records, an
unterminated final record and bytes following an oversized line are rejected.

Every record must round-trip through `CatalogProductRecordV1`. The full stream must
satisfy:

- strictly ascending numeric Shopify Product GID order;
- globally unique Product GIDs and handles;
- globally unique ProductVariant and InventoryItem GIDs;
- non-empty, ascending Variant tuples;
- every Variant's `productGid` equal to its parent Product GID;
- one taxonomy rule version across all Products; and
- exact record, Variant, status, family, identity and publication accounting.

The catalog-content digest is recomputed incrementally with the frozen
`nla-catalog-product-records-v1` envelope. The JSONL carrier SHA-256 separately covers
the exact canonical record bytes and LF delimiters.

`powerToolsSourceId` and `syncSourceId` remain paired and equal within a Product, but
they are not primary identities and may repeat across different Product GIDs. Such
Products remain distinct and are never deduplicated, merged or dropped.

## Resource bounds

Bounds are applied to handle state and authenticated summary declarations before an
artifact is materialized:

| Material | Maximum |
| --- | ---: |
| Reconciliation summary | 64 KiB |
| Each part manifest | 64 KiB |
| Reconciled source manifest | 64 KiB |
| Dataset manifest | 2 MiB |
| Taxonomy report | 2 MiB |
| One catalog record, excluding LF | 2 MiB |
| Complete catalog JSONL, including LF | 2 GiB |
| Products | 1,000,000 |
| Variants across the generation | 10,000,000 |
| Variants within one Product | 10,000 |

Counters are enforced again while streaming. No declared size is used to allocate an
equally sized buffer. Small JSON carriers may be frozen only after their handle size
passes its bound; the catalog is hashed and decoded incrementally. The 2 GiB catalog
limit is intentionally lower than the file-backed projection limit because this API
returns an eager in-memory generation.

## Win32 fixed-NTFS boundary

Production uses only the native Win32 backend and fails closed when its guarantees are
unavailable. The supplied directory must reside outside the repository on a local,
fixed NTFS volume. UNC paths, device namespaces, every extended namespace, relative
paths, parent traversal, trailing-dot/space components, junctions, symbolic links,
reparse points and unsafe aliases are rejected.

The supplied path must also use the exact long on-disk spelling and casing of every
component. Case-folded aliases are rejected, including on case-insensitive NTFS.

The consumer:

1. opens and retains an exact directory handle with `OPEN_REPARSE_POINT`;
2. verifies the fixed NTFS volume and canonical volume-GUID path;
3. verifies the external-to-repository containment boundary using canonical handle
   components rather than lexical prefixes;
4. checks the exact seven-name directory shape and absence of directory streams;
5. opens all seven carriers with exact read handles whose sharing denies writes,
   replacement and deletion;
6. binds every handle to its device/inode identity, size, modification time and
   canonical child path;
7. requires a regular file with link count one, no reparse attribute, a distinct
   identity, and exactly one unnamed `::$DATA` stream; and
8. retains the directory and all carrier handles until the context exits.

No verified content is reopened by pathname. The consumer first scans every carrier
for its complete size and hash, then rereads the same handles while repeating size/hash
checks and performing semantic parsing, and finally revalidates identities, sizes,
modification times, canonical paths, streams and directory shape immediately before
delivery. Any change rejects the entire bundle.

Ordinary read sharing does not establish permanent immutability for named NTFS streams.
The final stream revalidation is therefore the point-in-time attestation boundary. The
consumer does not use reversible delete-pending flags because doing so would introduce
a destructive side effect into a read-only API. A later external filesystem mutation
does not retroactively alter the already copied in-memory values and must be detected
by the next open operation.

## Portable test-only seam

The public function has no backend parameter, environment switch, command-line switch
or portable fallback. It always selects the native Win32 boundary. On a host without
that boundary it returns a fixed fail-closed error before consuming bundle content.

Portable CI calls a private verification engine with a deterministic backend defined
only under `tests/`. That backend can model identity changes, replacement, reparse
points, hardlinks, ADS, short-name aliases, partial reads and close failures. It is not
packaged under `src`, cannot be selected through public input and is never auto-selected
by production code. Tests do not monkeypatch global platform or `os.name` state.

Linux tests cover all parsing, limits, cross-links and adversarial phase transitions.
Separate local integration exercises real Win32 handles, sharing, canonical
volume-GUID paths and `FileStreamInfo` on fixed NTFS. The production API's rejection of
an unavailable native backend is itself a mandatory test.

## Read-only operational proof

The operational proof uses the separately controlled bundle location and summary
digest without writing either value to source files, command output, shell history, CI
logs, issue comments or the pull request.

1. Confirm that the code revision under review and the external bundle handoff are the
   intended candidates.
2. Obtain the bundle location and expected summary digest through separate approved
   local channels.
3. Pass both values directly to `open_reconciled_generation` without printing them.
4. Enter the context, confirm that a value was yielded, and exercise the in-memory
   consumer integration without activating or persisting it.
5. Exit the context and confirm that all native handles were closed.
6. Record only a value-free accepted/rejected outcome, the reviewed code revision and
   the test commands executed.

The proof must also assert that no network client, Shopify mutation, PowerTools path,
theme operation, persistent SQLite database, serving index or activation callback was
invoked. Failure at any stage yields no partially verified value.

## SyncCore compatibility

The in-memory generation may be passed explicitly to the existing SyncCore bootstrap
boundary, which independently copies and reconstructs its evidence. That path must use
Shopify Product GID as its primary identity. Global repetition of paired secondary
source IDs is valid and cannot cause rejection or deduplication. The existing rule that
a non-create/delete event cannot rewrite a Product's source-ID pair remains in force.

Opening a bundle never calls SyncCore and never switches an active generation. Any
bootstrap or later reconciliation install remains a separate, explicit caller action.

## Failure and rollback

Verification is transactional in memory. Until all checks and final revalidation pass,
no `VerifiedReconciledGenerationV1` is delivered. On rejection the consumer closes all
handles, discards partial objects and leaves the external directory untouched. It does
not recursively delete, rename, quarantine, repair or rewrite any artifact.

Because WS-01F performs no activation, the operational rollback is to keep the current
consumer generation unchanged and stop using the rejected candidate. A code rollback
is the normal revert of the WS-01F change; the external producer evidence remains under
its existing retention controls. No filesystem cleanup is part of this API.

## Non-live boundaries

WS-01F does not:

- call Shopify or mutate products, variants, prices, inventory, tags, metafields or
  publication state;
- change or disconnect TCG PowerTools;
- read, modify or publish any Shopify theme;
- activate a dataset or promote a runtime capability;
- create a persistent database or generated artifact in the repository;
- expose catalog values in logs, errors, documentation or pull-request evidence; or
- authorize staging, production, DNS, traffic, checkout or cutover work.

Any live publication remains gated by the separate go/no-go and explicit cutover
authorization.
