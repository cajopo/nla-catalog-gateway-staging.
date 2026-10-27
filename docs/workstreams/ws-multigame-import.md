# Riftbound and Disney Lorcana source/importer integration

Issue: [#123](https://github.com/cajopo/nla-catalog-gateway-staging./issues/123).
Branch: `agent/multigame-import-123`. Depends on the compatible six-game data
and canonical-reference contracts in
[#122](https://github.com/cajopo/nla-catalog-gateway-staging./issues/122).

The owner requested singles, sealed browsing and automatic new releases on
2026-10-27. This work extends only source acquisition and the existing missing
printing importer. Shopify remains the source for sealed products; the importer
does not create sealed products, complete sets, prices or saleable variant options.

## Explicit scope and compatibility

Capture and market-cycle commands accept `--game-scope legacy|six-games`.
Omitting it continues to capture Magic, Pokemon, Yu-Gi-Oh and One Piece only.
The six-game scope additionally includes Lorcana and Riftbound. Installing this
code does not expand an existing scheduled command's scope.

Capture receipts record `gameScope`. A retained receipt without that field means
`legacy`. Comparison validates the selected scope's full expansion accounting,
category mappings, files and hashes. Preparation uses the same scope. Re-labelling
a four-game capture as six-game fails expansion accounting; it cannot prove the
missing exports were empty. Every source row receives an explicit decision.

The compatible data workstream reads existing four-game canonical bundles and
builds schema-2 bundles when verified new-game mappings are added. Preparation
retains source row, blueprint and Cardmarket identities; previous canonical
records remain unchanged. A preview prepares a new reference but does not select
it, mutate the importer ledger or contact Shopify for writes.

## Source evidence checked on 2026-10-27

Official [CardTrader v2 reference](https://www.cardtrader.com/docs/api/full/reference)
documents bearer authentication and GET games, categories, expansions and
blueprint exports by expansion ID. It documents Cardmarket IDs and image URLs,
but does not document `fixed_properties`. Those keys were checked through bounded
read-only exports after reviewing the public contract.

The retained 2026-10-23 source catalog and fresh sample exports establish:

| Game | CardTrader ID | Importable single categories | Fixed rarity key |
| --- | --- | --- | --- |
| Disney Lorcana | 18 | 214 Singles, 230 Oversized, 270 Token | `lorcana_rarity` |
| Riftbound | 22 | 258 Singles, 284 Oversized | `riftbound_rarity` |

The source category names are pinned exactly. Complete-set categories 231 and
283 are deliberately `unclassified`, requiring review rather than being mistaken
for individual printings. Verified sealed categories are explicitly non-card;
unmapped categories remain accounted for as unclassified.

Private diagnostic evidence is retained outside Git. Reproducible source pins:

- Games export SHA256: `d452e6052837aa188f9b5abbb7df1e8caf4aaf31aa420d24bfd190e5b087b25a`.
- Categories export SHA256: `09038622895167c17c39462d1b553d90c6bd77f8493b7554518a7324076385e5`.
- Expansions export SHA256: `12cbdd5ef3ab24d495c2fd5e1ea4b74475cb9540de192a84ef41477f99a69471`.
- Lorcana sample expansion 3469: 216 singles, all with one Cardmarket ID;
  export SHA256 `341d48311421ca8fa0b893ff15d3006e3cf5a55fdc75b8858ad1726f66b77539`.
- Riftbound sample expansion 4166: 353 singles, all with one Cardmarket ID;
  export SHA256 `15cfef568a2ab1a9514caf943efcab15834704fe4e6e5c7e124eb9d2d1f254a3`.

A subsequent read-only count completed all 46 listed exports: Lorcana had 29
exports, 4,219 rows and 3,831 single-category rows; Riftbound had 17 exports,
2,110 rows and 1,896 single-category rows. Missing Cardmarket IDs were reported
for 170 and 116 single-category rows respectively. Three wrong-game rows occurred
in Riftbound exports. These totals are not an import approval or an eligible
product count. Existing conflict quarantine applies, including to the valid row
elsewhere if an anomalous export duplicates its identity. Future runs recheck all
listed expansions, including earlier sets and explicitly deferred HTTP 404s.

## Shopify and PowerTools boundary

The new controlled importer product types are `Lorcana Single` and
`Riftbound Single`. They are declared types for importer-owned products, not
claimed observed PowerTools output. Bounded title, product-type and tag searches
returned zero matching products on 2026-10-27; fresh verified-ID duplicate checks
remain required before import.
PowerTools publicly [lists both games](https://tcgpowertools.com/) as supported;
that alone does not verify this store's takeover configuration.

The importer retains the existing verified Cardmarket-to-`sync.productid` and
`powertools.id` identity contract, fresh Shopify absence checks and durable
no-resend ledger. It creates only a missing printing's draft, image and initial
identities, with inventory tracking and DENY on the untouched zero-stock default
variant. The publisher continues to require ledger ownership, matching identity,
ready media and zero inventory. Its terminal receipt prevents any later merchant
or PowerTools change from being overwritten or republished.

The pinned [Shopify productCreate 2026-07 contract](https://shopify.dev/docs/api/admin-graphql/2026-07/mutations/productCreate)
and [current resource limits](https://shopify.dev/docs/api/usage/limits)
currently disagree on the creation throttle threshold. Initial fill scheduling
must use confirmed account limits, rather than treating either page's number as
an observed store quota. PowerTools takeover for these two games remains an
operational check before enabling the explicit six-game cycle.

## Validation and rollout

Synthetic tests cover default-four and explicit-six capture, old receipts,
rejected incomplete scopes, wrong-game quarantine, deferred export retry,
complete-set/sealed exclusions, cross-game identity collisions, actual
capture-to-reference-to-import preview, new-game creation idempotency and
zero-stock publication with terminal handoff. Test data contains no source dumps.

The local targeted integration run passed 561 tests, with no skips or
deselections, in 136.61 seconds. It exercised the multigame tests and the existing
capture, comparison, reference preparation, market-cycle, import, publication and
input-retention suites. The new scope module had 100% statement and branch
coverage; this is not a claim of full repository coverage. The run used the four
uncommitted canonical/taxonomy dependency files from #122, copied temporarily
into this isolated worktree. Those copies were restored before incorporating the
reviewed dependency commit `8a51da9f4b5287b52abcddec0605bd20bf828818` by fast-forward.
Repository preflight, `ruff check .` and `ruff format --check .` passed.
After the fast-forward, the targeted multigame import, reference preparation,
capture CLI and capture suites passed all 126 tests in 62.58 seconds.

An independent reviewer found no actionable defects and separately ran the
multigame import, Shopify draft publication and CardTrader candidate suites:
157 tests passed in 16.29 seconds. Final commit SHA and combined repository checks
are recorded in the pull request.

No live apply, scheduler change, gateway deployment, theme mutation or PowerTools
configuration change is part of this code workstream. Rollback of the new capture
scope is removal of the explicit flag before a new cycle; pending runs still need
their existing inspection procedure. A selected schema-2 reference requires the
compatible data release, and cannot be handed to a legacy four-game-only reader.
