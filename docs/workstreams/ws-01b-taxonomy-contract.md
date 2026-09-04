# WS-01B/1 — fail-closed catalog taxonomy contract

## Scope

This slice implements the deterministic code contract required by issue #19. It classifies
only synthetic records, including four explicitly synthetic `Magic Display` examples. It
does not claim to classify the current complete Shopify baseline, rebuild an index, or prove
DB/API integration.

Shopify remains authoritative for commercial fields. The classifier neither accepts nor
returns transformed price or inventory values, performs no Shopify mutation, and does not
interact with TCG PowerTools or a theme.

## Result contract

Every input has a canonical Shopify Product GID and produces exactly one result containing:

- `game`: `magic`, `pokemon`, `yugioh`, `one-piece`, or null when the game itself cannot be
  established;
- `productFamily`: `single`, `sealed`, `accessory`, or `unclassified`;
- optional `productSubtype`;
- `classificationRuleVersion` on every path;
- either `classificationRuleId` or a machine-readable `unclassifiedReason`;
- subtype rule or subtype reason when a sealed title fallback is evaluated.

The catalog report accounts for every input and records counts by game/family, rule,
unclassified reason, and subtype advisory. Duplicate or malformed product identity aborts
classification instead of overwriting a record.

## Signal and conflict policy

Rules use exact normalized structured signals. Known `productType` rules provide game and
family; a reviewed source-record type provides family; explicit game and exact controlled
tags provide game evidence. An unknown non-empty product or source type is reported before
game reconciliation so a missing game cannot hide a new commercial type. Recognized signals
that disagree produce `unclassified`, even when one would otherwise have higher precedence.

Commercial title is never a family or identity signal. It is consulted only after a product
is already known to be sealed. Matching subtype rules are ordered by objective specificity,
not JSON order. A top-score tie across different subtypes leaves subtype unset and emits
`ambiguous_subtype_match`. A sealed record with no subtype match remains sealed and reports
`no_matching_subtype_rule`.

## Configuration boundary

The packaged JSON mapping has a strict schema version and an independently changing
classification-rule version. Loading rejects duplicate JSON keys, wrong types, unexpected
fields, unsupported enums, blank or colliding normalized keys, `unclassified` rule targets,
empty or duplicate subtype fragments, duplicate rule IDs/matchers, and any Shopify Product
GID or product-shaped bare numeric ID embedded in the mapping. Classification rule IDs are
explicit, normalized, and globally unique; they are never derived from punctuation in a
match key. Every serialized game value is also a required canonical self-alias, so a game
value can round-trip through `explicit_game` without depending on a display alias.

Only the reviewed product type `Magic Display` is mapped today. No product ID, SKU, title,
collection membership, price, or inventory value selects that family.

## Synthetic sealed fixture

The fixture contains four invented `Magic Display` examples with conspicuous test-only GIDs
and titles. It contains no captured Shopify Product GID, title, tag, language, price, or
inventory value. Tests prove that the shared product-type rule classifies all four as
`magic/sealed`, covering both supported sealed subtypes, and that a fifth synthetic GID
follows the same rule.

The repository preflight rejects the removed source Product IDs, commercial titles, and
former fixture path by non-reversible digest without retaining those values in Git. It scans
every regular UTF-8 blob in the staged Git index, independent of filename extension, and
fails closed above explicit index-entry, per-file, and aggregate-byte limits. The synthetic
fixture deliberately omits publication identity, inventory policy, and separate
PowerTools/sync identifiers.

## Blocked real-data gate

`NLA_DATA_ROOT` is missing on this host. The accepted issue #19 contract therefore remains a
synthetic foundation. Issue #32 must later run a fresh, independently verified Admin Bulk
snapshot outside Git and prove:

```text
classified + unclassified with non-empty reasons = total included baseline
```

That proof must also establish observed mappings beyond `Magic Display`, preserve external
read-only evidence for other games where available, verify price/inventory through the data
projection, and prove equality of taxonomy version and counts across manifest, DB, and API.
Only synthetic fixtures may be checked into this repository. None of those production-data
claims are made by this contract slice.
