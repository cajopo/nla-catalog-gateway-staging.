# Product presentation — clone only, 2026-09-28

Issue #14; branch agent/theme-metadata-filters. Owner asked to correct known
defects and record the actual change, not keep logging unresolved findings.

Applied theme/patches/product-presentation.patch to UNPUBLISHED clone
175195881740. Four files, userErrors empty, exact post-write content verified.
No MAIN, Shopify commercial data, PowerTools, cart logic or publication changes.

- Hide the price container when the real target price is zero/absent; keep
  positive prices and editor placeholders. Keep the outer replacement wrapper
  and SOLD OUT badge so native variant switching still works.
- Use literal SOLD OUT for initial product labels and window.variantStrings.
  This is the owner's explicit language-independent label, not a missing translation.
- Product badge, catalog-only notice and disabled button use bright red #e00000;
  disabled buttons retain their original disabled condition, with full opacity.

Verification: tests/product-presentation.mjs passes four official Liquid/HTML
parser checks, six guard-expression cases, badge placement, initial/dynamic label
agreement and exact preservation of purchase-disable logic. Independent reviewer
/root/product_presentation_review approved the diff with no blocking findings.
The official skill validator was run: this partial export has existing missing
dependencies/locales and legacy diagnostics, so it is NOT full-theme green.
Comparative baseline check: 491 before, 486 after, ZERO newly introduced findings.
Live browser visual/interaction verification remains unavailable; do not claim it.
Existing volume-pricing paths outside the price snippet were not changed/tested.

Official reference consulted before edits:
https://shopify.dev/docs/storefronts/themes/product-merchandising/variants
The skill search script failed network access; the Shopify documentation connector
supplied the relevant official variant documentation instead.

Private exact backup, prepared files and readback receipt:
C:/Users/umbri/AppData/Local/Temp/nla-product-ui-20260928/
Rollback: after confirming the clone is still UNPUBLISHED and checking the receipt's
after hashes, restore only these four original bodies from backup-exact.json.
GitHub push/CI/merge remain on hold pending the owner's quota reset.
