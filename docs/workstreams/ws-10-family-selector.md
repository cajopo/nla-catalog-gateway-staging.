# Catalog family selector — issue14

Local candidate on `agent/theme-family-selector`, based on61fe1fa. Not uploaded.
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
