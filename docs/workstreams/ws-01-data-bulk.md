# WS-01 Data/Bulk - synthetic source contract

## Scope

This slice implements the fail-closed local boundary between completed Shopify Admin Bulk
downloads and an immutable SQLite source candidate. It does not call Shopify, classify products,
build the serving index, activate a dataset, or change Shopify or PowerTools.

The original six-connection schema candidate has been removed. Issue #32 now carries two
schema-validated, read-only query documents and a deterministic synthetic reconciliation model;
see `ws-01d-data-baseline-reconciliation.md`. This older slice remains the ingestion/storage
contract and does not claim that a real Bulk operation was run.

## Sanitized terminal evidence

The validator reads at most 64 KiB plus one byte for a strict JSON document containing shop
domain, stable API version, Bulk operation GID, `COMPLETED` status, a boolean recording whether
partial data was offered, file size, object count, independent total Product count, independent
expected count of Products that are both `ACTIVE` and published to the exact configured Online
Store Publication GID, exact query SHA-256, completion timestamp and source-code SHA.

The expected source-code SHA is supplied independently by trusted deployment configuration and
must match before staging begins; evidence cannot self-attest arbitrary executing provenance. The
document accepts no download URL field. Signed result URLs remain transient capability secrets
and never enter diagnostics, manifests, tests, Git, issues or pull requests.

## Fail-closed ingestion

The JSONL file is read one bounded line at a time. SHA-256 and byte/row counters are incremental.
UTF BOMs, invalid UTF-8, blank records, non-object JSON, floating JSON numbers, excessive nesting,
oversized integers, lone Unicode surrogates, duplicate keys at any nesting level, unexpected
fields, unknown `__typename` values, malformed typed GIDs, invalid commercial scalar types,
duplicates and orphans reject the entire candidate. Source-derived diagnostics are generic,
single-line and bounded; attacker-controlled values are never echoed by the CLI.

Every accepted source row is stored as raw bytes plus normalized typed columns in a temporary
SQLite database. Product, Variant, Publication, InventoryLevel and Metafield identities are
reconciled with SQL rather than retained in Python sets. Each Product must have exactly the
`variantsCount.count` exported by Shopify and explicit evidence for the supplied Online Store
Publication GID. The independently supplied active-and-published count must equal the SQL join
over `status=ACTIVE`, the exact Publication GID and `isPublished=true`; manifest keys distinguish
expected from verified counts and account for all four Product statuses, including `UNLISTED`.

Ordinary Shopify GIDs use unbounded canonical positive-decimal text. InventoryLevel parameterized
GIDs bind an opaque canonical level identity to their inventory-item component exactly; the typed
Location GID is validated separately and is not inferred from that opaque identity. Every
InventoryLevel contains the five requested signed quantities, with no location cap. Decimal price
text is retained without floats or clamps, booleans cannot masquerade as integers, and negative
inventory is preserved.
Timestamps preserve exact valid text but must use the canonical timezone-aware Shopify-emitted
RFC3339 subset.

Variant barcode and ordered structured selected options are preserved without normalization or
deduplication. Featured media preserves common ID, alt, content type, status, preview and raw JSON
for the frozen MediaImage/Video/ExternalVideo/Model3d set. Media and preview images are nullable;
their nullable dimensions remain null. Connection metafield rows must use the queried `nla`
namespace, while PowerTools/sync identities must be matching canonical positive-decimal text.

Only after terminal metadata, child accounting, source identities and SQLite `quick_check` pass
are `catalog.sqlite3` and deterministic `manifest.json` atomically renamed into the requested
immutable directory. Any failure removes the private temporary candidate and leaves no final DB
or manifest. Activation and active-generation pointers are intentionally out of scope.

Publication visibility is keyed only by the configured Publication GID. The schema evidence also
showed that `Publication.catalog` is nullable and polymorphic, so the source model preserves a
nullable catalog typename/GID/title for the frozen AppCatalog/MarketCatalog/CompanyLocationCatalog
set and never infers visibility from a catalog title. `resourcePublicationsV2` covers published
and staged resources but has not been proven live to emit an explicit negative row for every
Product; the parser deliberately blocks when that required evidence is absent.

## Current evidence and block

All executable evidence in this slice is synthetic. `NLA_DATA_ROOT` is missing on the current
host, so no real snapshot, historical database, manifest, byte count or checksum was reused.
Issue #5 remains blocked for real-baseline proof until the external data root exists and is
inventoried before any new Bulk operation is considered.
