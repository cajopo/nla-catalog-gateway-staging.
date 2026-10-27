# Riftbound and Disney Lorcana theme support — issue #124

Branch `agent/multigame-theme-124`, base
`117b90c6320645db2ed0b6d27007b20dcfe3484d`. Depends on the versioned
gateway extension in [#122](https://github.com/cajopo/nla-catalog-gateway-staging./issues/122).
No theme installation, product write, menu-resource write, PowerTools change or
publication was performed. Independent review by the root agent approved the
source, patch, VM tests and desktop/mobile screenshots. This is not a GitHub
approval or authorization for live publication.

The shared header/catalog search now supports six games. Riftbound and Disney
Lorcana use `contractVersion: 2` for the POST envelope, request, response envelope,
page and product items. The four existing games retain version 1. The endpoint,
URL parameters, opaque cursor behavior, filters and variant format are unchanged.
The client rejects mismatched versions and game leakage before displaying results.

## Current-theme patch

The owner-approved scope includes the existing wishlist. The read-only acquisition
on 27 October identified MAIN `210373968140`, `NLA Arena — Wishlist multigioco`.
This ID identifies the inspected source only; it is not an installation target.
The former clone IDs and historical `arena-theme.patch` are not reused as a base.

`theme/patches/multigame-20261027.patch` is an additive patch against that source:

- Header renders `nla-new-game-navigation` after the fourth existing game in both
  desktop and mobile menus. Each new game links to the localized catalog route
  for All products, Singles, Sealed and Accessories.
- The shared store menu resource is unchanged. Its inspected top-level order is
  Magic, Pokémon, One Piece, Yu-Gi-Oh!, Eventi, Vendi carte, Il negozio. Recheck
  that menu order before using the prepared insertion.
- Wishlist parsing, search, edit/import game selectors and labels support both
  new games. Named game aliases are recognized; no numeric external IDs are
  invented. Mixed-game search issues separate versioned requests and cursors.
- The homepage currently has no game-card grid. Its entire source, hot-buylist,
  and existing wishlist purchasing/stock/identity behavior are preserved.

The repository stores only the narrow patch and new navigation snippet; complete
downloaded theme files and generated candidates remain private, outside Git.
`tests/theme-six-games.mjs` verifies SHA-256 guards for every patched source file,
applies the patch to a temporary copy, checks reverse applicability, copies the
new/revised catalog snippets and merges only the two new locale keys into the
complete existing locale files. It never writes to the supplied source directory.

## Reproducible checks

Read-only source acquisition is in the root worktree's ignored
`output/multigame-20261027/current-theme/`. For another environment, supply the
same verified source export; a changed source fails the checksum guards.

```text
node tests/theme-url-state.mjs
node tests/theme-metadata-filters.mjs
node tests/theme-six-games.mjs <private-current-theme-directory>
node tests/theme-browser.mjs <CANDIDATE-directory-printed-above> <liquidjs-runtime-directory>
```

The first two suites pass six-game URL/header synchronization, titles,
filter/cursor reset, version rejection, cross-game isolation and stale requests.
The patch suite passes named aliases, import/export, all-six-game search and
pagination, wrong-version/cross-game rejection and byte equality of unchanged
home/hot-buylist files.

Browser verification uses Node 22 and a fresh headless Chrome profile with a
localhost fixture. The 29 checks include both new games' page/back/reload,
suggestions and keyboard behavior; patched Arena menu order and all family links;
320/375/430/1024/1280px menu bounds and page overflow; and real patched wishlist
search handlers with version 2 fixture responses. A first wishlist keyboard check
correctly failed when the existing disclosure was closed; the harness now opens
it before interacting with its hidden controls. Production code was unchanged by
that correction. Desktop/mobile screenshots were inspected.

`theme-six-games-fixture.mjs` uses LiquidJS 10.30.0 to render the actual patched
header and wishlist, with explicit fixture Shopify objects and translations.
It omits Shopify-specific metadata/style/script Liquid blocks while including
the actual component CSS and JS separately. This verifies local component
behavior, not Shopify rendering, App Proxy authentication, live catalog data,
real purchases or the complete deployed storefront.

Official Shopify AI Toolkit validation uses its declared Theme Check 3.24.0
dependencies in a private temporary runtime, with install scripts and telemetry
disabled. The initial toolkit runtime lacked those dependencies. An intermediate
complete-file run identified only four pre-existing header assets missing from
the partial source export; their exact Shopify bytes were then acquired before
the final run. No source rule or check was weakened. Validation targets the two
catalog/navigation snippets, header, wishlist snippet, three wishlist JS assets
and both merged complete locales.

Final local receipt: both VM suites PASS, guarded patch suite PASS, **29/29
browser checks PASS**, and official validation **VALID, 9/9 files, revision 4**.
Repository preflight PASS over 277 staged files, zero findings, using the existing
root-worktree `.venv/Scripts/python.exe` (system Python lacks PyYAML). Staged
`git diff --check` and Node syntax checks for the changed browser/patch tests and
three prepared wishlist scripts also PASS. A whitespace-only context line in the
patch was trimmed by adjusting its hunk header; reapplication/reversal passed and
the prepared theme content is identical to the browser/validator candidate.
Private candidate: `C:/Users/umbri/AppData/Local/Temp/nla-six-games-124-lA5X2u`.
The final screenshots are `navigation-375.png`, `navigation-1280.png` and
`catalog-fixture.png` under
`C:/Users/umbri/AppData/Local/Temp/nla-theme-browser-Cy9TMK/`.
The private validation runtime is
`C:/Users/umbri/AppData/Local/Temp/nla-multigame-theme-validator-124/`.

The final validator command used `OPT_OUT_INSTRUMENTATION=true` and:

```text
node <private-runtime>/scripts/validate.mjs --api liquid --theme-path <candidate> --files snippets/nla-new-game-navigation.liquid,snippets/nla-catalog-search.liquid,snippets/nla-wishlist.liquid,sections/nla-header.liquid,assets/nla-wishlist-core.js,assets/nla-wishlist-data.js,assets/nla-wishlist.js,locales/en.default.json,locales/it.json --artifact-id multigame-theme-124 --revision 4
```

The copied validator matches the installed Shopify skill; only its declared
dependencies were installed. The browser renderer additionally uses LiquidJS
10.30.0. These private test dependencies are not shipped to the storefront.
No Python implementation changed, and this slice does not claim a new Python
coverage/build result or remote CI result.

## Installation and rollback boundary

Require the compatible backend, independently reviewed final SHA, and verified
catalog availability for both games first. Acquire a complete fresh target theme
and verify it is UNPUBLISHED. Recheck source hashes and menu order; reject drift.
Back up target files, add the navigation snippet create-only, and apply the
reviewed narrow changes with exact readback. Merge only `nla_catalog.riftbound`
and `nla_catalog.lorcana` into existing locales. Do not replace full merchant
locales with the repository fragments.

Rollback restores those backed-up target files and removes only the added
navigation snippet after a fresh role/content check. There is no catalog data
migration. MAIN, shared menus, existing products, publication, cart behavior and
PowerTools are outside the write scope. Live publication remains the owner's
separate decision.

Official references consulted before implementation:
[section schema](https://shopify.dev/docs/storefronts/themes/architecture/sections/section-schema),
[input settings](https://shopify.dev/docs/storefronts/themes/architecture/settings/input-settings),
[theme performance](https://shopify.dev/docs/storefronts/themes/best-practices/performance),
[LiquidJS setup](https://liquidjs.com/tutorials/setup.html) and
[custom filters/tags](https://liquidjs.com/tutorials/register-filters-tags.html).
