# WS-03 — bounded synthetic keyset pagination proof (issue #7)

## Scope and authority boundary

This workstream implements an internal, code-only proof of Product-level keyset pagination over
an immutable SQLite catalog projection. It consumes the merged runtime v1 DTO contract from issue
#28 and the producer/taxonomy boundaries from issues #5 and #19. It does not add an HTTP surface,
Shopify access, search semantics, non-empty filters, facets, sync, deployment, theme work, or any
write path to Shopify or TCG PowerTools.

The runtime v1 capability matrix is unchanged. In particular, `catalogOutput`, `activeIndex`, and
`cursorCodec` remain `unsupported`, and game/family request pairs remain `provisional`. The
pagination classes do not call the public-output capability gate and are not authorization to
serve a catalog. `NLA_DATA_ROOT` remains missing, so every result in this workstream is synthetic.

## Immutable Product projection

The builder accepts only an exact `DatasetManifestV1` and a non-empty, bounded tuple of exact
`CatalogProductRecordV1` objects. The manifest and every supplied record are serialized and decoded
again through the frozen v1 contract before their decoded values are used. The manifest must
validate the complete deep-canonical record tuple. Its content-derived `datasetGeneration` is the
only generation authority; callers cannot provide a free-form generation label. Canonical manifest
bytes are persisted in projection metadata and decoded again on open, when the complete decoded DB
record tuple is revalidated against them. A reused label therefore cannot authenticate different
catalog content.

All included Products and all nested Variants are persisted, including unpublished, non-active,
cross-game, and `unclassified` Products. A separate derived `is_public` flag is true only for
active, Online-Store-published, classified Products.

Product and Variant GID suffixes remain decimal text. Ordering and continuation compare the tuple
`(digit length, digit text)`; no GID suffix is converted to an integer. The serving query is a
parameterized composite keyset seek, requests `pageSize + 1` Product rows, returns at most
`pageSize`, and then loads every Variant for only those returned Products in the canonical Variant
GID order. No query contains `OFFSET`.

The database is created as a private same-directory candidate and installed with an atomic hard
link that fails if the destination already exists. The installed file is made read-only and is
never opened for writes by pagination code. Read connections use SQLite's `mode=ro`, `immutable=1`,
and `query_only`.

Opening or activating a generation verifies bounded counts, quick check, foreign keys, exact
canonical table and index DDL (including partial-index predicates), canonical manifest and Product
record bytes, denormalized Product fields, GID text against stored length/text keys, Variant parent
and inventory identities, canonical public Variant bytes, Variant order, public derivation, and
complete Product/Variant accounting. Invalid candidates fail with bounded errors and are not
activated.

Activation hashes the complete bounded file before and after semantic verification and pins that
digest together with the installed file identity, size, timestamps, mode, link count, and SQLite
header. Each page validates the cheap identity/header stamp immediately before and after its SQL
read; it does not hash the complete database per page. A later valid SQLite mutation or path
replacement therefore fails closed before a page is returned under the authenticated generation.
This mechanism assumes a trusted local catalog directory and filesystem: it protects against
accidental or out-of-band replacement and mutation, not a privileged malicious local process able
to race both checks while restoring file identity and SQLite header metadata.

## Authenticated cursor and generation semantics

The client token is two unpadded URL-safe Base64 segments: the exact canonical
`CursorContextV1.to_json_bytes()` followed by its HMAC-SHA256. Only the exact context bytes are the
signed message. Decoding is bounded and rejects malformed or non-canonical Base64, the raw unsigned
context, a bad signature or secret, non-canonical JSON, wrong contract/cursor version, request
context mismatch, stale generation, and expiry. Callers never treat `CursorContextV1` JSON alone
as an authenticated cursor.

Activation swaps one fully verified immutable `CatalogProjection` under a lock. Selection returns
one complete generation object, so a concurrent activation cannot mix rows or generation labels
within a page. Cursor requests select that object once, then authenticate against its expected
generation before checking expiry. A cursor that is both stale and expired therefore
deterministically raises the stale-generation error; a concurrent activation after selection leaves
that request pinned to the already-selected generation. A stale cursor is never replayed against a
new database, and a first request after activation starts from the new generation.

## Synthetic proof and unresolved real-data gates

Tests traverse 30,005 consecutive Product GIDs with page size 100 and assert exact equality to the
independent expected sequence, including Products 24,999, 25,000, and 25,001, with zero gaps or
duplicates. A separate bounded page-size-1 traversal covers every continuation edge without
making CI open tens of thousands of SQLite connections. Additional cases cover huge decimal GIDs,
Variant fanout, empty and terminal pages, every canonical game crossed with `single`, `sealed`,
`accessory`, and request-only `all`, manifest and row-content mismatch, hostile nested DTO values,
post-activation mutation and replacement, exact index predicates, tampering and context failures,
stale-plus-expired ordering, sealed-catalog growth, and concurrent activation.

This is not a real-baseline traversal, performance benchmark, active-index verification, or
production readiness claim. Those gates require the external data root, reproducible issue-#5
producer evidence, capability review, and independent review of the exact delivery SHA.
