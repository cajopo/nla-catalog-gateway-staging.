# WS-135 — six-game footer navigation

Issue: #135, follow-up to #124 and activation #131. Branch:
`agent/footer-six-games-135`, based on `f2c22ae28c10572ee8a7995463d485805f267624`.

The clone's header, catalog selector and wishlist already include Riftbound and
Disney Lorcana. Its footer renders `nla-main-menu`, whose seven top-level entries
still include only four games. This change adds the missing two game links after
the existing footer menu, using the current translated labels and locale-aware
search route with `view=nla-catalog`, the game slug and `family=all`.

The snippet omits a game already represented by a top-level menu title
(`Riftbound`, `Lorcana` or `Disney Lorcana`, ignoring case and outer whitespace)
or an exact `game` query parameter. It preserves each existing link and does not
interpret search text or a longer game slug as a match. Only the menu links
actually rendered by this footer participate in deduplication.

The additive patch inserts one render call in `sections/nla-footer.liquid`.
Install it together with `snippets/nla-new-game-footer-links.liquid`. The previous
patches remain unchanged; no footer styling, global menu, home content, product
or backend code changes are included.

## Evidence

The read-only audit at 2026-10-28 09:55 UTC found MAIN `210373968140` unchanged
(328 files) and clone `210427412748` still UNPUBLISHED and unchanged (329 files),
including the exact nine earlier patch payloads. The footer source SHA-256 was
`3384fbd9c2cc8be5802f9fc8cdee270d77a7d70ba0f65a82a0bcfc87c8c9d2a0`.
Full theme sources, menu responses, previews and screenshots remain private.

Reproduction, using a private exact clone source and the previously provisioned
LiquidJS 10.30.0 runtime:

```text
node tests/theme-footer-games.mjs <private-clone-source> <liquidjs-runtime>
node tests/theme-footer-browser.mjs <candidate-printed-by-first-command>
node --check tests/theme-footer-games.mjs
node --check tests/theme-footer-browser.mjs
python scripts/preflight_repo.py
git diff --check
```

The guarded patch and actual footer Liquid consumer tests passed **21/21**:
original bytes except the single insertion, patch applicability/reversibility,
Italian/English routes and labels, empty menu, existing games, exact parameter
matching, case/whitespace and escaped existing menu text. The local Chrome
rendering passed **4/4** at 375 and 1280 pixels in both languages: all nine menu
links visible, no horizontal overflow, correct destination and focusability.
These are local fixture checks, separate from live clone acceptance.

Both Node syntax checks, Ruff check/format and `git diff --check` passed.
Repository preflight passed with 289 files and zero failures. No Python source
changed; full repository test/build results remain the PR CI gate.

Shopify AI Toolkit Liquid validation passed **2/2 files**, artifact
`multigame-footer-135`, revision 1, with instrumentation disabled. The private
validator is the unchanged official helper with its declared dependencies:

```text
node <validator-runtime>/scripts/validate.mjs --api liquid --theme-path <candidate> --files snippets/nla-new-game-footer-links.liquid,sections/nla-footer.liquid --artifact-id multigame-footer-135 --revision 1
```

Independent review and green PR checks are required before installation. No live
installation or populated-catalog acceptance is claimed by these source tests.

## Installation and rollback

After merge, freshly verify the target remains UNPUBLISHED `210427412748`, MAIN
remains `210373968140`, and the clone inventory and footer hash match the reviewed
baseline. Stop on drift. Apply this patch to the verified original footer, pair
it with the merged snippet, and upsert only those two files. The expected clone
inventory becomes 330 files: 328 unchanged, one modified footer, one new snippet.
Read back both exact payloads, compare every other clone checksum and the full
MAIN inventory, then verify the real preview footer at desktop/mobile widths.
Never publish the theme or alter the shared menu resource.

Rollback restores only the original footer bytes and removes the new snippet,
after the same fresh role/hash checks. Catalog population and real sealed or
accessory availability remain separate #131 gates; this navigation does not
create stock or commercial products. MAIN publication remains the owner's gate.

## Documentation consulted

- [Liquid routes](https://shopify.dev/docs/api/liquid/objects/routes): preserve locale-aware URLs.
- [Liquid link](https://shopify.dev/docs/api/liquid/objects/link): menu titles and URLs; active/current flags ignore query parameters and cannot identify the selected game.
- [Theme performance](https://shopify.dev/docs/storefronts/themes/best-practices/performance): no additional JavaScript, CSS or network requests.

## Product share dependency follow-up, 2026-10-29

The real populated clone smoke exposed a product-page `ReferenceError:
DetailsDisclosure is not defined`. The existing `share.js` extends that class;
the existing `assets/details-disclosure.js` defines it, but the Arena layout did
not load it. `product-share-dependency-20261029.patch` adds exactly one deferred
script after `global.js`, before the product section's deferred share consumer.
The assets themselves and all other layout bytes remain unchanged.

This follow-up stays in issue #135 and branch `agent/footer-six-games-135`, as
authorized during #131 acceptance. Root independently reviewed the one-line
patch and consumer test before the authorized clone-only installation.

```text
node tests/theme-product-share.mjs <private-disclosure-baseline>
node --check tests/theme-product-share.mjs
git diff --check
```

All four targeted checks passed: exact reversible patch, original exception
reproduced from the real share asset, and successful native/fallback consumers
with inherited close behavior and URL updates. Shopify Admin GraphQL queries
and mutation validated against pinned 2026-07. The plugin bundle lacked
`@shopify/theme-check-common`, so the existing private validator runtime from
#124 was reused with byte-identical official helper code; no dependencies were
installed. Stateless Liquid validation passed (artifact `product-share-135`,
revision 1), with one existing non-error warning about `scheme_classes`.
Repository preflight passed with 291 files and zero failures; syntax and
staged diff checks passed. Full CI remains the pull-request merge gate.

Fresh role/inventory gates confirmed UNPUBLISHED `210427412748` and MAIN
`210373968140`. Only `layout/theme.liquid` was upserted, with no user errors or
asynchronous job. Readback matched the candidate byte for byte: SHA-256
`d747e9dea9efb819655ada6b30c08ac122ae7b587682c301da77f320a582d080`,
20,863 bytes. All 329 other clone files and all 328 MAIN files were identical.
Rollback restores the verified original layout, SHA-256
`c1022da9f9a646708c9261b778e5233a1aae14d94e289bd88177208b00df0064`,
after fresh role/hash checks. No publication, shared-menu change, product write
or cart mutation occurred.

The real populated wishlist/product smoke completed at 00:38:26 UTC on October
29: four cases passed for Lorcana and Riftbound, with 12 screenshots across 375
and 1280 pixels. Both wishlist identities, catalog links, product JSON, selected
variants, loaded images and sold-out controls passed. Runtime exceptions: zero;
cart unchanged. Request counts were 7 catalog POST, 11 functional GET, 5 document
GET and 5 ancillary product GET. All 104 Shopify analytics POST attempts were
blocked before dispatch. Five known child pixel sandbox documents returned
404; those separately recorded nonfunctional iframe failures do not suppress
main-frame or API errors. The final private receipt SHA-256 is
`cf4a2c990333dd05c28a3568bc217ea4de3e8124d4d1e4de4f28ac1d54174cdd`;
harness SHA-256 `b9ef6b1817f0a94626ceb6a6de449d0d3e55a81ca756d70511776e488012f966`.
The independently supplied oracle and API responses bound generation
`sha256:a43adeed9fdc827cd72eda34850f26b9d30714511093a57d2141844f237ebb08`.
Full data acceptance and owner publication remain separate #131 gates.

Official references: [ordered deferred theme scripts](https://shopify.dev/docs/storefronts/themes/best-practices/performance/defer-scripts)
and [themeFilesUpsert 2026-07](https://shopify.dev/docs/api/admin-graphql/2026-07/mutations/themeFilesUpsert).
