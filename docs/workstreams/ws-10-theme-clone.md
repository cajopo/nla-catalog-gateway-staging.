# WS-10 — Game-scoped clone UI

Issue #14. Branch `agent/theme-clone-integration`, based on runtime `69f56a3`
(PR #63; CI `35009265538` and CodeQL `35009265549` both succeeded).

Delivery: [draft PR #64](https://github.com/cajopo/nla-catalog-gateway-staging./pull/64),
implementation commit `0d0345c54201c1f8fd611d83a87017dde8cc4141`, pushed and independently
approved on that SHA. Documentation-only follow-up records the actual PR. No merge or
deployment; exact-head CI and release gates remain required.

## Scope and state

This is a local integration component, NOT an installed/connected storefront.
One reusable Liquid snippet supports header suggestions and a catalog results page.
Game is explicit; public singles include sold-out records unless the stock box is checked.
The existing POST gateway contract supplies both results and opt-in suggestions.
No native predictive-search results are filtered or used as a fallback.

The page keeps a bounded 24-product DOM and advances through opaque keyset cursors.
Next/first buttons and URL state support browser back, forward and reload. This slice uses
separate pages rather than an unbounded append-only grid; there is no 25k client-side cap.
A dataset change shows an explicit restart action, reflecting the current runtime contract.
This does not solve server-side retention of navigable previous generations.

Debounced suggestions support arrows, Enter, Escape, IME composition, cancellation and
late-response rejection. Rendering uses DOM text nodes; product links stay on Shopify.
Zero/absent usable price displays n/d; zero stock displays Esaurito; no cart writes exist.
English/Italian translations are supplied. Currency is the shop currency, not a claim of
Shopify Markets conversion. Product pages remain the final price/availability authority.

## Real clone inspection (2026-09-15)

Admin GraphQL confirmed theme `175195881740`, `NLA — catalogo completo test`,
role `UNPUBLISHED`. No Shopify mutations were performed.

Read-only MD5 observations, to recheck before a future installation:

| File | MD5 |
|---|---|
| sections/nla-header.liquid | 0655b8bae75d8ee95e27ca4cffbe231d |
| sections/header-group.json | 8fdba033d702631e55db9857d26b198c |
| templates/search.json | 53adfdd77adeb6fd0bdc76e968dda4c7 |
| locales/en.default.json | 1d532d7055a6b9a28975bddda8713a9f |
| locales/it.json | 2adee8e271be50e157d30dfd09149601 |
| locales/en.default.schema.json | 275c16ce1b9cd3c0fc457d51b24a2043 |
| locales/it.schema.json | a25c4e82edece514febeb391557d8769 |

The actual header group renders `nla-header`; its current search is native Shopify.
This fresh file inspection supersedes assumptions about older custom search markup.
The existing header/logo/menu and default search template have not been replaced.

## Installation boundary (not executed)

1. Confirm the same theme ID is still UNPUBLISHED. Export full target-file backups outside
   Git, with hashes; reject changed targets rather than overwrite someone else's work.
2. Upload the new snippet, section and `search.nla-catalog.json` create-only.
3. **Merge only the `nla_catalog` object** from each locale fragment into the matching
   existing locale. The files in `theme/locales` are NOT replacements for the store locales.
4. Replace only the native search wrapper in `sections/nla-header.liquid` with a render of
   `nla-catalog-search`, unique `instance_id: section.id`, `mode: 'header'`, and the verified
   App Proxy endpoint. Preserve the existing logo, account/cart links, menu and styling.
   The wrapper should retain the existing `nla-search-wrap` layout class.
5. Configure the same verified App Proxy path in the catalog section. Leave the endpoint
   empty until the authenticated staging service is actually available. No client secret
   or Admin token belongs in Liquid or browser configuration.
6. Verify `/search?view=nla-catalog&game=magic`, header navigation and all regression cases
   on the clone. Roll back by restoring backed-up header/locales and removing only newly
   created files. No default-template or MAIN publication change is part of this slice.

## Reproducible verification

`node tests/theme-browser.mjs` requires Node >=22 and Chrome, uses a fresh headless profile
and a localhost-only fixture server; `NLA_CHROME` can specify the executable.
It imports the actual snippet JS/CSS, substitutes only the fixture Liquid variables and
translations, and checks real DOM/events/navigation. It does not simulate Shopify Liquid
rendering, App Proxy signing, current catalog data or the complete existing header CSS.
Temporary profile/screenshot paths are printed and remain outside Git.

Coverage includes scoped requests, sold-out pages, opaque cursor URL restoration,
game/stock changes, keyboard/late suggestions, malformed/cross-game/duplicate output,
restart and looping cursors, XSS text rendering, empty/unconfigured states and horizontal
overflow at 320/375/430/1280 pixels. Product IDs in the small fixture are NOT evidence of
traversal through 25k records; that remains the separate backend traversal proof and real E2E.

The Shopify Liquid skill validator checks all seven theme files. Its three dependencies
were missing locally and were installed from its declared package versions (3.24.0), with
install scripts disabled. Instrumentation is opted out. Validation revisions 3 and 4 passed
all seven files after the four UI corrections.

Final browser run: `node tests/theme-browser.mjs`, 18 checks passed in 6.27 seconds
on Node 22 / headless Chrome. The prior expanded run failed because the test typed
programmatically without refocusing the input after submission; it now models actual
typing focus. This does not weaken the focus-leave regression. Screenshot inspected at
`C:\Users\umbri\AppData\Local\Temp\nla-theme-browser-MzFUCL\catalog-fixture.png`.

Independent reviewer `/root/search_v2_review`: APPROVE after three P2 fixes (unscoped
history restoration, delayed suggestions after focus leaves, stale options on header
stock changes) and one P3 fix (first ArrowUp chooses the last option). Each has a browser
regression. Review covers the local component, not clone installation or Shopify E2E.
The source/test delta changes no Python runtime; its parent #63 has green CI/CodeQL.
The new documentation-inclusive commit still requires its own remote CI.

Local foundation checks: Ruff check and format on `src tests scripts` PASS (55 Python
files formatted), `node --check tests/theme-browser.mjs` PASS, sdist/wheel build with
`python -m build --no-isolation` PASS, and staged `python scripts/preflight_repo.py`
PASS over 106 files with zero findings. `git diff --cached --check` PASS. Python production
code is unchanged; the full Python suite/container remain the exact-head remote CI gate.

## Remaining, not hidden by this delivery

- Real staging endpoint/App Proxy installation and clone upload/header integration.
- Verified printed-code source join and real schema-v2 package acceptance.
- Images, structured card/set numbers and richer variant presentation in the API/UI.
- Sealed/accessory/all-family search, richer facets/sorting, other locales/Markets.
- Durable updates, cursor retention across refresh, real catalog/browser E2E, MAIN cutover.
- Browser checks currently run explicitly, not as a claim of Python coverage or CI browser QA.

References: [theme component settings](https://shopify.dev/docs/storefronts/themes/architecture/settings),
[Admin theme-file text](https://shopify.dev/docs/api/admin-graphql/2026-07/objects/OnlineStoreThemeFileBodyText).

## Metadata controls candidate, 2026-09-21

Issue #14 continuation, based on PR #91 (`c5a5dff`), dependent on the runtime
metadata-facet contract in PR #94, including its cursor-page follow-up. Not uploaded.

The catalog page adds native, labelled expansion-code and rarity selects with contextual
product counts. All values come from the gateway; there is no top-100 truncation or
invented expansion-name mapping. Counts span the matching catalog, not the visible page.
Each dimension excludes its own selection, retains the other selection and stock/search
scope, and preserves a selected zero-count value so it can be cleared. Missing metadata
is not presented as an invented selectable value; it remains included with no selection.

Selections use raw exact values in the request and URL. Game changes clear both; changing
either filter starts a new first page. Back/forward and direct cursor URLs restore the
selected values and receive counts from the same pinned generation as the products.
Header search remains a game-scoped fresh search, without invisible page filters.
Suggestion requests keep page filter scope but do not request counts. Incoming values
are rendered with `textContent`; malformed counts, duplicate values, missing selections,
request-echo mismatches and cross-filter product metadata fail closed.

Only the snippet and five `nla_catalog` translation keys in the English/Italian fragments
change the UI. Merge those keys into the clone's existing locale files; never replace a
complete merchant locale with a fragment. No header layout, settings, native product
page, commercial data, MAIN theme or publication change is included.

Local Shopify Liquid validation revision 1 passed the snippet and both locale fragments
with instrumentation disabled. The initial automatic permission rejection was resolved
by inspecting the validator: full-app checks run locally and telemetry returns before
network access when opted out; the unchanged command then passed. The URL-state VM
regression passes. The browser fixture is updated for optional counts and passes syntax
checking, but has NOT been executed for this candidate. VM tests are not browser,
Shopify App Proxy, mobile layout or real-catalog E2E evidence.

Do not upload this candidate against the currently serving runtime, which lacks this
response extension. Require matching backend CI, staging validation, clone backup and
browser acceptance first. Rollback restores the backed-up clone snippet and only the
added locale keys; no data migration is needed. New-market ingestion remains blocked
on CardTrader access and is not enabled by these controls.

`node tests/theme-url-state.mjs` and `node tests/theme-metadata-filters.mjs` PASS.
The latter exercises the actual snippet script in a VM: complete 131-value options,
literal Unicode/HTML-looking values, zero-count selections, URL/cursor restoration,
malformed URL rejection before fetch, game/header isolation, strict response checks,
first-page filter changes retaining stock and the other filter, stale responses and
cancelled-request control recovery. Product/image rendering is deliberately stubbed.
Independent reviewer `/root/theme_title_review` approved the candidate and reran
both VM suites, with no blocker. Real-browser focus/keyboard/mobile and clone
back/forward remain release gates, not results inferred from the VM tests.
Staged repository preflight PASS over 125 files, zero findings; diff whitespace and
browser-fixture syntax checks PASS. No Python production code changed in this slice.
