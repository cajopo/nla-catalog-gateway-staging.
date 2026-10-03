# Clone homepage consistency and real browser checks — 2026-09-28

> Evidence retained from the private source preview on 30 September 2026. Statements
> below describe their original observation dates. The [current project snapshot](../evidence/STATE-2026-09-30.md)
> supersedes historical next-step and clone-role wording; no new execution is claimed.

Issue #14; branch `agent/theme-metadata-filters`, parent `6215b92`.
Only UNPUBLISHED clone `175195881740` (NLA — catalogo completo test) changed.
MAIN, PowerTools and Shopify commercial data were not touched. No push or CI rerun.

## Deployed change

`theme/patches/home-card-presentation.patch` records the exact small delta:

- Custom home cards show literal SOLD OUT for catalog-only or unavailable products.
- Zero/missing prices are hidden; real positive prices and the catalog-only guard
  remain unchanged. No availability or price is written back to Shopify.
- Both status labels are bright red `#ff4d4f`.
- Homepage h2/h3 explicitly use the existing white color: real mobile inspection
  revealed the old headings inherited black over dark backgrounds.
- Links, images, purchase controls and other pages are unchanged.

Fresh role/checksum guards preceded each write; all mutation userErrors were empty.
Exact readback matched prepared content. Final checksums:

| File | Before | After |
| --- | --- | --- |
| sections/nla-home.liquid | 6cc43b3e35627e1fcd69e94c9b458497 | 3d702b894ea1a327addfb2acc644bbcc |
| snippets/nla-product-card.liquid | 7bdb2049ae112fc3ae2d0468f1ee3419 | 35c2a95a6e6bfb32b6898375c9b8e385 |

Independent `deferred_export_review` approved the card change and separately the
five-line heading-color addition, with no blockers.

## Executable checks

- `node tests/home-card-presentation.mjs <private-artifact-root> <shopify-liquid-skill-root>`:
  PASS, two official Liquid/HTML parses and 12 price/availability/tag combinations,
  exact status/color/heading assertions, retained links/images/positive prices.
- Official Shopify Liquid validator: VALID for both changed files and again for
  the heading addition. Partial-theme missing-locales warnings remain; this is not
  a complete-theme validation claim. Latest run used cached official schemas after
  network access failed. No new translation keys were introduced.
- Official Admin GraphQL validation: VALID for the mutation. The PowerShell `--code`
  attempt lost embedded quotes; validation succeeded with the same operation via
  `--file`, not a changed GraphQL contract.
- `git apply --reverse --check <patch>` against final prepared theme: PASS.

Private backup, prepared files, mutation receipts and screenshot are under
`C:/Users/umbri/AppData/Local/Temp/nla-home-consistency-20260928/`.
They are deliberately not committed. Rollback requires a fresh clone/checksum
guard, then restores these two original files (or reverse-applies this patch).

Official documentation consulted before implementation:
[Liquid product](https://shopify.dev/docs/api/liquid/objects/product),
[themeFilesUpsert 2026-07](https://shopify.dev/docs/api/admin-graphql/2026-07/mutations/themeFilesUpsert).

## Browser evidence, not just backend tests

The supported in-app browser now works; the older native-browser access blocker
is superseded. Password protection and clone preview were retained.

- Magic `light` produced ten distinct names; extending to `lightning` updated the
  list and included Lightning Bolt. Pokémon + Lightning Bolt returned no match.
- Pokémon `char`, Yu-Gi-Oh! `bl`, One Piece `ma`: ten distinct suggestions each.
  Red SOLD OUT was visible; available Charizard suggestions were not mislabeled.
- Magic `spider // phyrexian beast` returned the newly imported card with image,
  SOLD OUT, no zero or unknown price. Actual search-result link activated with
  Enter opened `/products/nla-cm-910888`; image and disabled SOLD OUT purchase
  button verified. Prior signed backend evidence identifies this product as GID
  `16571747533068`, index position `295865` (not limited to the first 25,000).
- Pointer automation also failed on Shopify's preview-bar controls; keyboard
  interaction worked. Do not infer a storefront link defect or claim mouse-path
  acceptance from those failed tool clicks. Preview bar was hidden by its control.
- Reloaded homepage: eight card badges read SOLD OUT, computed red rgb(255,77,79);
  all 18 h2/h3 headings computed rgb(246,248,251). No ESAURITO or EUR0.00 output.
  Existing Brims Barone real EUR0.60 price remained visible.
- Mobile screenshot `home-cards-after.png` shows readable headings/cards and red
  SOLD OUT. No new cart, checkout, login configuration or product mutations.

Remaining delivery gates are separate: native deferred-source recovery completion,
GitHub quota/CI, remaining final QA and Jacopo's cutover. Not overall completion.

## Additional live pagination/filter acceptance

Next goal turn verified the unchanged deployed clone through its real controls:
Magic Lightning Bolt traversed four pages (24/24/24/2), 74 distinct product links,
zero duplicates, next hidden at the end. Applying M11 from the last page reset to
the first page with exactly Lightning Bolt M11-149. Combining Common retained that
one result and both filters in the address. Enabling stock-only produced the correct
empty result and retained removable M11 (0)/Common (0) selections; disabling it
restored the card. No catalog request was substituted by a native Shopify search.
At desktop 1280px: filters visible, product image loaded, document width1265px,
no horizontal overflow. Temporary viewport override reset to the original size.
Private screenshot `live-filter-qa.png` records the combined filters and SOLD OUT.
No source/deployment changes were needed for these checks.

## Final focused browser checks — 18:49 UTC

Same deployed clone, no source reacquisition or theme mutation:

- Reload preserved Magic / Lightning Bolt / M11 / Common and the single M11-149
  result. Clearing rarity, then browser Back and Forward, restored the exact
  respective URLs, selected filters and result. Loading states were awaited.
- Header `light`: ArrowDown selected the first of ten distinct names with
  `aria-selected=true` and a matching `aria-activedescendant`; Enter opened
  `Light 'Em Up`, two results, without leaking the previous page's filters.
- Pokemon / Charizard / stock-only: three available products with positive prices.
  Actual result-link Enter opened Dark Charizard TR-21. Its default Good/Normal
  variant was EUR129.99; Poor/Normal was unavailable; Poor/1st-Edition was EUR42.90,
  matching the catalog's minimum price. Existing product options/data were not edited.
- Starting from an empty session cart, the product's own Add to cart control added
  exactly one Italian / Poor / 1st-Edition, variant54812348973324, total EUR42.90.
  The cart's own Remove control removed that exact line. Final visible state:
  `Il tuo carrello e vuoto` (accented in the UI). No checkout/payment/order submitted.
- Private screenshots `cart-variant-qa.png` and `cart-restored-empty.png` in the
  same artifact directory prove addition and cleanup. Pointer tooling remains
  unreliable; successful paths here are keyboard-based, not mouse certification.

Independent `deferred_export_review` found no new functional blocker in existing
objective evidence. Minimum remaining operational acceptance: the next unattended
market cycle after d7e6fc9/404 fixes and the first real warm activation on61be173.
Observe existing timers/receipts; do not trigger another full acquisition. GitHub
quota/CI reconciliation and owner cutover remain separate release gates. This
does not claim a Firefox/WebKit matrix or complete issue15/16 release certification.
