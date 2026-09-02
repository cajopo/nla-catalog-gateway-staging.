# WS-01C — Runtime contract v1 (issue #28)

## Outcome and boundary

This workstream defines pure, deterministic DTO and JSON contracts between the fused
Data/Bulk (#5), Taxonomy (#19), and future read-only runtime workstreams. It implements no
Shopify call, Bulk parser, SQL, HMAC or client cursor codec, HTTP/FastAPI surface, search,
facet/index engine, sync, deployment, theme change, or live-data operation.

`NLA_DATA_ROOT MISSING` was observed on 2026-09-01. No real baseline was read. The frozen v1
capability matrix consequently contains zero `verified` entries: contract shapes and every
canonical game/family request pair are `provisional`; catalog output, active index, facets,
and the client cursor codec are `unsupported`. Parsing or constructing a provisional DTO is
not authorization to serve it. Explicit execution/output gates accept only `verified` and
therefore fail closed in v1.

## Producer boundary and records

`CatalogProductRecordV1` is the internal Product-level projection. Shopify Product GID is
its primary identity. It preserves handle, commercial title, nullable canonical card name,
Shopify status (including `UNLISTED`), exact Online Store publication truth, paired source
IDs, signed inventory, inventory-tracking truth, exact timestamp text, the complete Taxonomy
classification/reason fields, and a non-empty tuple of `CatalogVariantRecordV1` children.
Variant records retain their typed Product foreign key, ProductVariant and InventoryItem
GIDs, SKU/barcode null-versus-empty values, ordered `selectedOptions`, exact price text,
signed inventory, policy/tracking, and exact timestamp text.

`CatalogItemV1` is a separate public Product-level view: one item equals one Shopify Product,
never one selected or representative Variant. It contains a tuple of minimum
`CatalogVariantItemV1` storefront values so no min/default Variant is invented. Public
Variants omit InventoryItem GID, SKU, barcode, and internal timestamp. `CatalogPageV1.items`
therefore preserves the public traversal equation `returned Product GIDs == returned item
GIDs`; pagination uses Product GID as its final tie-breaker.

Identity and classification invariants are fail closed:

- Product, ProductVariant, and InventoryItem GIDs are canonical typed Shopify GID strings
  with an unbounded positive-decimal component; no numeric coercion is performed.
- Product GIDs, Variant GIDs, InventoryItem GIDs, and handles are unique in a dataset. Handle
  is a producer-proven unique locator, not the primary identity and not an independent
  generation input.
- Each Product and public item stores Variants in ascending ProductVariant GID decimal order
  using `(digit length, digit text)` without integer coercion. Variant tuple order is not
  inferred from the #5 SQLite row order; ordered `selectedOptions` remain semantic.
- Commercial titles, Variant titles, SKUs, barcodes, and non-null source IDs may duplicate.
  A Product's PowerTools and sync source IDs must both be null or identical canonical
  positive-decimal strings.
- `productFamily` persisted values are `single`, `sealed`, `accessory`, or `unclassified`.
  `all` exists only in `CatalogRequestV1`; no public `unclassified` filter exists.
- Classified records require canonical game and classification rule ID. Unclassified
  records require a machine-readable reason and remain accounted. A publishable Product is
  exactly `ACTIVE && onlineStorePublished`; a publishable single also requires a non-empty
  canonical card name.
- Sealed subtype state is either `(subtype, subtypeRuleId, null reason)` or
  `(null subtype, null rule, machine-readable subtypeReason)`. Other families carry no
  subtype state.

## Dataset manifest and immutable generation

`DatasetManifestV1.build` accepts the #5 `SourceSnapshotManifest` object and the exact bytes
of its persisted `manifest.json`. It bounds the input at 64 KiB, strictly decodes it, requires
the exact #5 renderer (`ensure_ascii=False`, sorted keys, two-space indentation, LF newline),
hashes those exact bytes, and independently validates the otherwise directly constructible
#5 dataclass: schema v2, source evidence, snapshot/database hashes, byte/line/object/Product
counts, status counts, ProductVariant count, active+Online-Store-published proof, and source
identity count. Exact outer/nested concrete types, bounded raw JSON, and every semantic
invariant are checked before invoking the #5 renderer; subclasses cannot override renderer
dispatch, and renderer failures are normalized to a bounded contract error.

The runtime manifest records and enforces these equations:

```text
source Product = included Product + excluded Product
source status[S] = included status[S] + excluded status[S]       for every status
included Product = classified Product + unclassified Product
included Product = sum(single, sealed, accessory, unclassified)
source Variant = included Variant + excluded Variant
source/included/excluded Variant >= matching Product count
source identity Product = included identity Product + excluded identity Product
included/excluded identity Product <= matching Product count
source active+published = included active+published + excluded active+published
public item = intersection(included active+published, included classified)
public item <= min(included active+published, included classified)
public item >= included active+published + included classified - included Product
```

Source and included Product counts are positive in v1. This matches the #5 non-empty export
and the runtime builder's non-empty record tuple; an all-excluded generation would require an
explicit contract redesign. The Variant lower bounds are producer-backed: #5 requires every
Product's `variantsCount` to be positive and reconciles the exact child count, so they apply
to the source, included, and excluded partitions rather than being a live-data assumption.

The catalog content hash is over a domain-separated canonical object with records sorted by
the decimal Product GID key `(digit length, digit text)`. The immutable dataset generation is
`sha256:` plus the digest of a separate domain-separated descriptor binding runtime contract
version, exact source-manifest SHA, source snapshot/query hashes, taxonomy rule version, and
catalog content hash. It excludes wall-clock state. `generatedAt` is deterministically copied
from the #5 completion evidence, so repeated builds from identical inputs have identical
manifest bytes and generation.

## Request, cursor material, page, and errors

`CatalogRequestV1` binds canonical game, request-only family, nullable query, an exact filter
object, page size, and the frozen `product_gid_asc` plain-string sort. Public items require the
exact persisted `ProductFamily` enum type; equal-valued request enums or plain strings cannot
bypass the public classification rules. Non-empty search and filters are
preserved but cannot be silently ignored: the explicit execution gate rejects them, and
family-incompatible subtype filters fail during construction.

`CursorContextV1` is unsigned internal canonical material only. It binds contract/cursor
version, dataset generation, endpoint, the complete canonical request, expiry, last sort
tuple, and full final Product GID. It provides two distinct hashes:

- `request_context_sha256`: contract/cursor version + dataset + endpoint + request, excluding
  expiry and position so all pages in one traversal share it;
- `context_sha256`: the entire canonical CursorContext, including expiry and position, for a
  future authenticated codec.

No token, base64, signature, or HMAC implementation is present. Raw CursorContext JSON is not
a client-safe cursor. Pages carry the canonical request even when terminal, validate their
request-context hash, page size, Product-level counts, total Product GID order, game/family
isolation, page-wide Product GID/handle/nested Variant GID uniqueness, current-after position,
and exact next-context continuity. Expiry comparison converts only the whole-second/offset
portion and compares arbitrary-length fractional text exactly; `-00:00` is rejected for
expiry material because it denotes an unknown offset. Producer timestamps retain the #5
accepted timestamp subset unchanged. Cursor matching rejects non-concrete request objects and
non-plain generation strings before equality, so subclass-controlled comparison methods cannot
bypass the request or dataset binding.

`CatalogErrorV1` accepts only frozen code-to-public-message pairs. It includes the operational
codes `invalid_cursor`, `restart_required`, `dataset_unavailable`, and
`temporarily_unavailable`; free-form attacker-derived messages are impossible.

## Strict JSON and compatibility policy

Every DTO validates both direct construction and decoded input. JSON input is bounded,
non-empty UTF-8 without a BOM; duplicate keys at any depth, floats/non-finite numbers,
isolated surrogates, non-object roots, missing/unknown keys, wrong exact types, and enum
drift fail closed with bounded diagnostics. Nested DTO boundaries require the frozen concrete
v1 type, preventing subclass renderer overrides from forging page or content-hash material.
Bytes, strings, dictionaries, arrays, and structural tuples must likewise be their exact
built-in type; subclasses cannot override decoding, comparison, iteration, or equality at a
binding boundary. Canonical serialization uses UTF-8, sorted keys,
compact separators, unescaped valid Unicode, and no trailing newline. Price and GID values
remain strings; inventory/count integers are exact signed 64-bit values with booleans
excluded; accepted timestamps preserve their exact canonical timezone-aware RFC3339-subset
text. Required human-readable producer fields reject empty or whitespace-only strings without
normalizing accepted text; nullable SKU, barcode, and query text retain their distinct rules.
Golden fixture vectors freeze canonical bytes and independent SHA-256 values.

`FIELD_DISPOSITIONS_V1` independently covers every serialized key with
`required|nullable|provisional|unsupported`; tests compare it to every DTO's exact field set.
The v1 compatibility matrix is also frozen: adding a nullable field is minor; rename,
removal, type, nullability, enum, or semantic changes require a major contract version.

## Reproducible evidence and unresolved gate

Author evidence is local and synthetic only:

```text
pytest tests/test_runtime_contract.py --cov=nla_catalog_gateway.runtime_contract \
  --cov-branch --cov-report=term-missing
76 passed; 1136/1136 statements and 492/492 branches covered (100%)
```

Real-baseline capability verification remains blocked by `NLA_DATA_ROOT MISSING`. Future
work must supply reproducible producer evidence and independent review before changing any
matrix entry to `verified`; this contract alone does not enable output, index, facets, or a
cursor codec.
