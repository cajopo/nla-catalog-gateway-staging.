# Clone homepage heading contrast, 2026-09-28

Issue #14; branch `agent/theme-metadata-filters`, starting HEAD `6c2ae02`.
Owner screenshot showed only the first hero-heading line readable on the dark home.
Inspected exact UNPUBLISHED clone `175195881740`, index template, `nla-home` section
and base CSS. Base headings set `color: rgb(var(--color-foreground))`; the section
overrode only `::first-line`. Added one explicit white color to `.nla-hero h1`.
No markup, settings, links, responsive rules, MAIN, products or PowerTools changed.

Applied `theme/patches/hero-contrast.patch` to `sections/nla-home.liquid` only.
Fresh prewrite content/role guard passed, mutation userErrors empty, exact content
readback matched. Before MD5 `8db7717049a30140c76c1be1eccdb96a`; after MD5
`6cc43b3e35627e1fcd69e94c9b458497`; prepared SHA256
`995b52c4e7252008925900dfd4351c880ac845af638526027979e48d01883440`.

Verification:
- `git apply --check` against the exact private baseline: PASS.
- `node tests/hero-contrast.mjs <artifact-root> <shopify-liquid-skill-root>`: PASS.
  Both Liquid/HTML parses, clone guard and exact single-property change verified.
- Official Shopify Liquid skill validator, revision 2: section PASS. Initial
  partial export lacked its referenced snippet; read that unchanged dependency
  and supplied the expected locales directory. Used cached official schemas after
  the documentation-cache network update failed. Not a full-theme validation.
- Mutation validated by both Shopify connector and official Admin skill script.
- Independent reviewer `/root/product_presentation_review`: APPROVE, no blockers.
- Actual storefront visual verification is still pending; Computer Use previously
  stopped on URL-policy enforcement. No alternative UI bypass attempted.

Private backup/prepared/readback evidence:
`C:/Users/umbri/AppData/Local/Temp/nla-hero-contrast-20260928/`.
Rollback: confirm the same clone remains UNPUBLISHED and current content matches
the after hash, then restore only this file from `backup-exact.json`.

Separate search finding from the same screenshot: immutable current catalog query
found zero `INN158`, but `ISD158` finds Rakish Heir (Innistrad), Product GID
16091484520716; `INR158` finds Hanweir Watchkeep / Bane of Hanweir (Innistrad
Remastered), Product GID 16089484198156. Verified structured metadata and indexed
SKUs; no invented alias, catalog refresh or search behavior change.

Official references consulted before implementation:
https://shopify.dev/docs/storefronts/themes/best-practices/javascript-and-stylesheet-tags
https://shopify.dev/docs/api/admin-graphql/2026-07/mutations/themeFilesUpsert

GitHub push/CI/merge remain on hold. Prior product-presentation files were preserved.

## Owner storefront screenshot accepted

Owner supplied `codex-clipboard-da46991e-c852-4840-a2ff-7cf73f4e8a65.png`
(private Temp attachment, not committed). Clone preview bar is visible; Magic is
selected, query LIGHT, available-only unchecked. The open autocomplete visibly
contains seven fully readable distinct names plus an eighth partially visible:
Light 'Em Up, Light from Within, Light of Day, Light of Hope, Light of Judgment,
Light of Promise, Light of Sanction, Light of the Legion. Visible entries include
red SOLD OUT labels; the multiline homepage hero is now white and legible.
This closes the requested Magic/light suggestion and hero-contrast visual check.
A still image alone does not prove keyboard/variant interactions, other games,
all-record traversal or product-page presentation; retain their separate evidence
and outstanding checks. Do not request this same screenshot again.
