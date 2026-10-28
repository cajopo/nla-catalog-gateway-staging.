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
