# WS-01B/1 — catalog taxonomy contract

## Scope

This slice freezes the fail-closed classification contract needed before the full Shopify baseline is rebuilt. It does not claim to classify all 291,795 products and does not mutate Shopify, PowerTools or a theme.

## Contract

Every included product receives exactly one `game`, one `product_family`, an optional `product_subtype`, a `classification_rule_version` and either a `rule_id` or an explicit unclassified reason.

Families are:

- `single`;
- `sealed`;
- `accessory`;
- `unclassified`.

Classification signals are evaluated from controlled structured fields:

1. exact `productType` mappings;
2. an explicit source record type from the canonical source adapter;
3. explicit game and controlled exact game tags;
4. commercial title only for subtype detection after the product is already known to be sealed.

Unknown product types, unknown source record types, conflicting games, conflicting families and missing required names fail closed to `unclassified`. Product IDs never appear in the mapping.

## Search and stock boundaries

- `single` requires a canonical card name; search behavior belongs to WS-05 and may use only that canonical name to create a match.
- `sealed` and `accessory` require a commercial title; sealed subtype detection cannot turn an unknown product into sealed.
- The taxonomy contains no stock transformation. Commercial sealed/accessory inventory and prices remain Shopify values.
- Unknown records remain countable and reportable; they are not silently discarded.
- Tags inherited from PowerTools, such as `Near Mint` and `Normal`, do not create single-card facets on a sealed record.

## Live sealed evidence

A schema-validated Admin query was executed read-only on 31 August 2026. The four ACTIVE products with exact `productType = Magic Display` are frozen as fixtures. The mapping classifies all four as `magic/sealed` without referencing their GIDs:

| Product | Language | Inventory | Price | Expected subtype |
|---|---|---:|---:|---|
| Edge of Eternities Collector Booster Box | English | 2 | EUR 399.99 | `collector-booster-box` |
| Ikoria: Lair of Behemoths Booster Box | Russian | 2 | EUR 249.99 | `booster-box` |
| Magic: The Gathering Foundations Collector Booster Box | English | 2 | EUR 600.00 | `collector-booster-box` |
| Outlaws of Thunder Junction Collector Booster Box | English | 1 | EUR 300.00 | `collector-booster-box` |

All four have matching `sync.productid` and `powertools.id`, tracked inventory, `DENY` policy and an Online Store publication. A fifth product with the same structured type would follow the same rule automatically. A new product type remains `unclassified` until the versioned mapping is extended and reviewed.

The Ikoria fixture is deliberately Russian. This prevents a future adapter from hard-coding English or deriving language from the product family.

## Legacy prototype finding

The frozen JAC-021 SQLite database is valid evidence for the earlier pagination/search experiment, but it has no `record_type`, `productType`, tags or media. It stores the four display titles in `canonical_name` and marks them searchable. That schema must not become the canonical production projection because it mixes commercial sealed titles with card-name search.

## Remaining acceptance gate

Issue #19 stays open until WS-01 produces a fresh Admin Bulk snapshot containing the structured fields, runs this classifier over the complete included baseline and emits counts by game/family/rule plus the complete unclassified queue. Required reconciliation remains:

```text
classified + unclassified with reasons = total included baseline
```

This contract unblocks schema, search and filter implementation against fixtures, but not a production dataset release.
