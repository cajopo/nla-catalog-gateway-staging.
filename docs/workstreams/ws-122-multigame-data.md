# WS-122 — Lorcana and Riftbound catalog data

Issue: [#122](https://github.com/cajopo/nla-catalog-gateway-staging./issues/122).
Branch: `agent/multigame-data-122`. Owner request: 27 October 2026, full integration
of Lorcana and Riftbound, including singles, sealed and automatic new releases.
Importer and theme changes remain separate workstreams. This change only builds
and serves a read-only projection; it does not deploy or write to Shopify.

## Contract evolution

The v1 enum contract remains frozen. The existing four games use wire
`contractVersion: 1`; `lorcana` and `riftbound` require `contractVersion: 2`.
Requests using a new game with v1 fail explicitly. Legacy games retain their exact
v1 serialization and request/cursor hashes. A v2 payload for a legacy game also
fails, so each game has one canonical wire representation during this migration.

The version applies consistently to Product records, public items, requests,
pages, cursor contexts, and request/response transport envelopes. The POST route,
field names, opaque cursor syntax, price/stock semantics, metadata, suggestions
and facets do not change. The shared strict Python DTO implementations retain
their historical `V1` class names; `contractVersion` is the wire discriminator.
Factories propagate that discriminator; decoding rejects mismatched nested
versions. Game changes in URL state select the appropriate version and reset
game-specific filters.

Errors and health responses retain v1 because their vocabulary does not include
games. Dataset/container formats also retain v1: they do not expose a game enum,
and their hashes bind each explicitly versioned Product record. The frozen v1
capability matrix is unchanged and reports new-game requests as unsupported.
Actual serving still requires the existing independent generation evidence gate;
adding a game never enables the default unverified service.

## Source and taxonomy boundaries

Canonical manifests with schema 1 still require the exact original four-source
roster, in the original order. Schema 2 requires those four plus either or both
new games, ordered `lorcana`, then `riftbound`. The same pinned loader validates
both. Duplicate, reversed, incomplete and mislabeled rosters fail. Existing file
names retain their historical `v1` suffix for operational compatibility; the
manifest's explicit `schemaVersion` determines its source vocabulary.

The CSV builder keeps all four old CLI flags required, adding optional
`--lorcana` and `--riftbound`. A four-source build remains schema 1. Reference
extension preserves every parent record and never overwrites or activates the
parent bundle. A new-game extension emits schema 2 with the added source's
actual derived-CSV hash, byte count and record count. Those derived inputs are
not described as original PowerTools exports.

Taxonomy rule version `2026-10-27.1` adds explicit game aliases and the
importer-controlled types `Lorcana Single` and `Riftbound Single`. These types are
a declared contract for future importer products, **not observed PowerTools
product types**. Bounded Shopify searches by title, type and tag returned zero
matching products; fresh verified-ID duplicate checks remain required before
import. Sealed/accessory classification uses the existing
explicit game plus structured `source_record_type` route with an empty product
type, unless a separate verified product-type mapping is supplied. Unknown
nonempty commercial product types remain unclassified and counted.

Recognizing a single never invents a canonical name: reconciliation requires a
verified `(game, source ID)` join and rejects missing/conflicting mappings. No
title is used as identity. Shopify GIDs, PowerTools/source IDs, commercial data
and unclassified accounting remain unchanged.

## Staged coverage versus complete rollout

Core evidence always requires a searchable public single for every legacy game.
It also traverses all families and evaluates facets for each additional game
present in a generation. New public singles receive the existing name/code,
stock and suggestion checks. New sealed/accessory families receive bounded
commercial-search checks against independent record-derived expectations.
Draft-only or sealed-only onboarding does not require a nonexistent public
single, and removing a legacy game's proof still fails.

A generation-valid result is not a claim that the full six-game rollout is
complete. The six-game acceptance explicitly includes public singles for both
new games, and proves same-name/code isolation, SOLD OUT inclusion, full cursor
traversal, suggestions, metadata counts, literal code search, sealed/accessory
search, URL state and signed App Proxy transport. Real source coverage and
publication/activation evidence belong to the separate integration rollout.

## Reproducible verification

Use the repository virtual environment. On this Windows host the inherited
pytest temporary root was inaccessible; supply a fresh unique `--basetemp`
outside the repository. No existing directory should be reused for that option.

```powershell
$testRoot = 'C:/Users/umbri/AppData/Local/Temp/nla-multigame-' + [guid]::NewGuid().ToString('N')
.venv/Scripts/python.exe -m pytest tests/test_multigame.py tests/test_taxonomy.py tests/test_canonical_names.py tests/test_canonical_reference_extension.py tests/test_build_canonical_name_sidecar.py tests/test_reconciliation.py tests/test_runtime_contract.py tests/test_core_evidence.py tests/test_runtime_api.py tests/test_runtime_api_integration.py tests/test_pagination.py --basetemp=$testRoot -q
```

Local verification on 27 October 2026: the expanded regression selection passed
628 tests; the final multigame selection contains 20 tests, included in the
265-test contract/search/transport regression run that passed after the coverage
follow-up. Ruff lint and format checks passed, repository preflight passed, and
`python -m build` produced both
distribution formats. The full foundation suite and its 100% coverage gate remain
required before merge; the subset's diagnostic coverage is not that gate.

Official references consulted before work:
[Python 3.13 enum](https://docs.python.org/3.13/library/enum.html),
[pytest invocation](https://docs.pytest.org/en/stable/how-to/usage.html), and
[GitHub issue reads](https://docs.github.com/en/rest/issues/issues#get-an-issue).
No external API authentication or endpoint contract changed in this workstream.

Rollback is a code/data-generation operation: existing pinned four-game bundles
remain readable by this code. An old binary must not load a six-game generation;
restore a reviewed four-game generation before rolling the binary back. No
Shopify corrective writes or MAIN theme changes are part of rollback.
