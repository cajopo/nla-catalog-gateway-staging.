# #143 — Shopify stock replaces the legacy catalog-only presentation gate

Branch `agent/catalog-handoff-theme-143`, base `12874fee8918d54de723004347f912070e105680`.
This is a prepared theme correction. No Shopify writes, installation or publication
have been performed. PowerTools synchronization remains a separate investigation.

## Observed problem and active consumers

Read-only MAIN capture on 31 October 2026: theme `210427412748`. The stale
`nla_catalog_only` tag independently blocks three active consumers:

- `main-product.liquid` replaces the price with SOLD OUT and omits both variant
  picker and buy-buttons; the default product template includes those blocks.
- `card-product.liquid` hides the price and quick-add. The default collection grid
  and native search render this snippet. Current collections configure quick-add
  as `none`; its other modes still need to remain safe.
- The homepage wishlist's data adapter discards the product before examining
  its fresh Shopify variants. A synthetic replay of the captured asset returned
  one offer with quantity 1, then zero when only `catalogOnly` became true.

The old `nla-product-card` also contains a tag gate, but the wishlist home patch
removed its only observed render. It is not included in this correction or claimed
as an active storefront failure. Gateway quantities are preserved independently.

The tracked wishlist source is `agent/wishlist-20261022`, commit `cfac2fc`, with
`theme/patches/multigame-20261027.patch` supplying the six-game changes. The main
branch keeps patches rather than complete third-party theme snapshots. This slice
follows that model: four guarded file deltas and one new shared Liquid snippet.

## Resulting behavior and boundaries

For tagged products, the shared snippet requires the existing two product source
IDs to have their observed types, a positive matching value, real Shopify product
and variant IDs, a tracked and available variant, positive physical stock and a
positive Shopify price. Both known inventory policies are accepted when physical
stock is positive; `continue` at zero does not bypass the catalog placeholder gate.
It does not invent a PowerTools article/variant matching contract or option data.

PDP readiness follows the selected variant. The picker and form remain present,
so the existing Dawn section fetch can enable or disable the submit button when
selection changes. Native minimum-quantity checks remain intact. Tagged cards
show the minimum price of only their ready variants. Wishlist retains all existing
identity, game/printing, language/condition/finish, price and fresh-stock checks;
the tag no longer vetoes an otherwise valid offer.

Partial arrival is intentionally closed: stock arriving before price, or price
before stock, cannot enable purchase. A placeholder with zero stock/zero price
remains blocked. Until a usable price and stock coexist, the legacy unavailable
presentation remains; this does not assert that the provider has completed handoff.

Tagged products use standard add-to-cart only: accelerated checkout and bulk
quick-add are withheld while the tag remains. Those paths do not consume the
selected variant's custom readiness response, so leaving them enabled could bypass
the partial-arrival guard. Standard quick-add still works; multiple variants use
the native picker/modal. Untagged products keep their original purchase behavior.
No tags, variants, identities, prices, inventory or provider settings are written.

## Reproducible checks and candidate

```text
node tests/theme-catalog-handoff.mjs <private-baseline> <liquidjs-runtime>
node --check tests/theme-catalog-handoff.mjs
git diff --check
```

The first command checks every baseline SHA-256, applies the exact patch, verifies
candidate hashes, reverses it and verifies exact restoration, then reapplies it.
It parses all four Liquid files with Shopify's parser and renders synthetic stock,
identity, price, mixed-variant, quantity-rule and selection cases with LiquidJS
10.30.0. It executes the actual candidate wishlist adapter across all six games,
including zero/negative stock, untracked/unavailable variants, unusable price,
wrong identity/game/printing and unmet option constraints. All checks passed.
Rendering stubs live in a separate temporary fixture, never in the upload candidate.

Official Shopify validator: new snippet and wishlist JavaScript PASS. The three
existing Liquid files are a partial export with missing dependencies/locales;
baseline and candidate each report 492 identical diagnostics after removing line
offsets, with zero new diagnostics. This is not full-theme validation or browser QA.
Private source, validation comparison and candidate receipts are under
`output/repair-audit-20261031/`. Fresh clone role/checksum verification and browser
acceptance remain installation gates; publication belongs to the owner.

## Install/rollback contract

`theme/patches/catalog-handoff-143.json` lists the four target files and normalized
before/after SHA-256 values plus the new snippet hash. Re-read the target as
UNPUBLISHED immediately before installation and compare all four baseline hashes.
Reject any drift. Upload only those four candidates and the named new snippet.
Do not upload fixture dependencies, receipts or other files in the temporary tree.
Read back exact normalized hashes after upload. Preserve the target's exact original
bodies for rollback; restore only these four after checking the installed hashes,
then remove only the newly added snippet if its hash still matches. The reverse
patch was exercised offline. MAIN is excluded from this procedure.

Official references consulted: [variant handling](https://shopify.dev/docs/storefronts/themes/product-merchandising/variants),
[Liquid variant facts](https://shopify.dev/docs/api/liquid/objects/variant),
[theme reads](https://shopify.dev/docs/api/admin-graphql/2026-10/queries/theme),
[theme performance](https://shopify.dev/docs/storefronts/themes/best-practices/performance).
