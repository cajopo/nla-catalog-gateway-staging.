# Catalog family selector — issue14

Implemented on `agent/theme-family-selector`, based on61fe1fa. Deployed to the
unpublished clone only on 2026-09-28; deployment evidence follows below.
Completes the family choice required by approved issues17/19: All products,
Single cards, Sealed products, Accessories. Game remains mandatory. Existing
links without `family` retain SINGLE behavior; new links carry the family.

Changing family preserves query and stock, resets the cursor and incompatible
expansion/rarity filters, and cancels obsolete responses. Header/page history
synchronization includes family. Card metadata and distinct-name suggestions
remain SINGLE-only, matching the current API extensions; other categories show
an explicit submit-search hint, never fake suggestions or silently discarded text.
Results accept nullable canonical names on non-singles and render commercial titles.
Only the three public families are accepted, without cross-game leakage.

Executable evidence: `node tests/theme-metadata-filters.mjs` and
`node tests/theme-url-state.mjs` PASS. Coverage includes four-family URL/cursor
restore, stock/query retention, invalid family/filter combinations, mixed ALL
responses, nullable names, cross-family/game rejection and stale cancellation.
Official Shopify Liquid validation PASS for the snippet and en/it locales with
`OPT_OUT_INSTRUMENTATION=true`; cached official schemas used after public schema
refresh failed. No code telemetry sent by this opted-out run. Independent
`deferred_export_review` approved with no blocking finding.

Deployment prerequisite: compatible non-single query backend from
`agent/family-search-v1`; old9b56fdd explicitly rejects these queries. Do not upload
ahead of the backend. Then fresh clone-role/content backup guards, merge ONLY
the `nla_catalog` translations into full locale files, upload the snippet and
the two locales, and verify sealed → ALL → single plus Back/reload in the real
clone. VM tests do not certify rendering/layout. MAIN/PowerTools unchanged;
no source capture, Shopify product writes, push, merge or CI rerun.

Official documentation consulted before editing:
https://shopify.dev/docs/storefronts/themes/navigation-search/filtering/storefront-filtering/support-storefront-filtering

## Clone deployment and browser acceptance — 2026-09-28

Code `ed12e63fb974730a6212450189f060bfcc087e4a` is installed on clone
`175195881740`, NLA — catalogo completo test, role UNPUBLISHED. Three guarded
file writes: snippet plus en/it locales. Only 13 changed `nla_catalog` keys per
locale were merged; all unrelated keys were preserved. Fresh role and before-MD5
guards, private backups and byte-for-byte readback passed. Official Liquid
validation of the actual merged files passed (revision3, telemetry opted out).

Runtime prerequisite was installed in the same release: `ed24a61`, immutable image
`sha256:8a23ad0809ed155665decdea9dff875dd198f1fefe2e5764e20798a31a22ece8`.
Native activation completed at 19:46:58 UTC; browser tests ran after readiness.

Actual browser results, not only mocked tests:

- Magic / sealed / `booster`: four real booster boxes, images and real prices.
- ALL / same query: mixed sealed and single results (24 on the first page);
  all 24 images appeared after asynchronous hydration. SOLD OUT singles have
  no fabricated price. Switching to SINGLE removes the boxes and restores facets.
- Browser Back to ALL, reload ALL, then Back to sealed preserved family, query,
  header/page synchronization and expected results.
- ALL + stock-only returned four boxes; changing to sealed kept query and stock;
  unchecking stock restored the flag without discarding the search text.
- Magic / sealed / `Outlaws` returned exactly its booster box; changing only the
  game to Pokemon returned no products, not the Magic product.
- SINGLE `light` displayed ten distinct canonical names; suggestions remain
  SINGLE-only, with explicit submit-search wording for other categories.
- Magic / accessory / empty query returned a valid empty result. No positive
  real accessory sample exists in that tested slice; positive accessory search
  is covered by the native family tests, not claimed as a positive browser proof.

Private backups, merged payloads, readback MD5s and screenshots are in
`C:/Users/umbri/AppData/Local/Temp/nla-family-deploy-20260928` (not in Git).
No MAIN, products, commercial data, PowerTools, checkout, source acquisition,
GitHub push/merge or CI rerun changed. One-time code installation used the old
stop/start helper; do not describe it as a zero-downtime deployment. Future
scheduled refreshes use warm operator881b9ca; their first real unattended result
is still an independent acceptance gate.
