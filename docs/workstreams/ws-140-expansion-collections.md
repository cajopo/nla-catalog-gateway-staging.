# WS-140: Riftbound and Lorcana expansion collections

Issue #140; branch `agent/expansion-collections-140`.

The owner authorized adding verified game/expansion tags to exactly 5,612
existing products on 2026-10-31. The private approved manifest has SHA-256
`a90776646654f074836be1086695bf04bc2d4d865d96e8e10e5039bfc0d8a2ed`.
It contains 5,423 ordinary singles and 189 sealed products, across 41 source
expansions (28 Lorcana, 13 Riftbound). Twenty oversized products are excluded.
Collection publication remains the owner's responsibility.

## Existing-store comparison and resulting behavior

The live baseline has 302 collections, including 297 expansion collections
selected by exact expansion tags. New expansion collections use the same native
automatic membership and standard template, with an additional game tag condition
to prevent cross-game collisions. Their sort order is BEST_SELLING. Four native
family collections cover singles and sealed products for the two games.

`scripts/backfill_expansion_tags.py` requires the exact manifest hash and count,
fresh Shopify GID, handle, both PowerTools/Cardmarket identities and classification.
It uses only `tagsAdd`, preserves every existing tag, records intent in a private
SQLite checkpoint and rereads every batch. A lost response is reconciled before
any additive retry. It never writes commercial fields or publication state.

For future releases, preparation derives the game and expansion tags from the
verified CardTrader blueprint/expansion relation. Only ordinary singles and sealed
products of the two new games receive these initial tags. Legacy product payloads
remain unchanged. The source expansion identity is retained in the importer ledger.

The market cycle's explicit `--expansion-collections` option ensures the verified
expansion collection exists **before** creating its first product. A durable journal
at `importer-state/expansion-collections/collections.sqlite3` records create intent.
The collection metafield `nla.expansion_identity` identifies the CardTrader game and
expansion ID; titles alone are never identities. New collections are unpublished.
Existing matching collections, including ones the owner later publishes, are read
only. Collisions, source drift and uncertain creations stop for inspection.

The sealed family collections use existing `nla.source_record_type = sealed`
metadata plus the game tag. Its PRODUCT definition enables smart collection
conditions; existing values are not rewritten. Single family collections use the
exact game product type and game tag. No MAIN theme or PowerTools settings change.

## Validation and operation

Official Shopify GraphQL validation and live 2026-07 schema introspection confirm
the `CollectionCreateInput`/`sources` contract used by the VPS. The runtime requires
ANY within an EQUALS product-type condition; a single exact value has the intended
semantics. Schema descriptions did not state this cross-field restriction; both
initial family requests were explicitly rejected before corrected creation.

Independent reciprocal review covered importer compatibility, source identity,
collection reconciliation, retry behavior and owner publication. No unresolved
findings. Targeted tests cover legacy payloads, token/oversize exclusions, exact
tag readback, published existing collections, collisions and lost responses.

Private manifests, source snapshots, credentials, checkpoints and API receipts
stay outside git. Final execution counts, package revision and complete test
results are recorded separately in the delivery evidence.

Rollback of future automation is restoring the previous pinned importer package
and unit, leaving current products/collections and the journal intact. Do not
delete tags, collections or pending journal rows as an automatic rollback. Inspect
uncertain writes against their remote markers and saved receipts first.
