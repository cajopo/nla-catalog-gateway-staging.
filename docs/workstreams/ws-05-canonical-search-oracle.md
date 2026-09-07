# WS-05 - synthetic canonical single-card search oracle

## Scope and result

This issue #9 slice is a framework-independent acceptance oracle over exact
`CatalogProductRecordV1` inputs plus a generation-scoped, prepared in-memory search index.
It implements no SQL, HTTP/API endpoint, UI, facets, cursor, sync, deployment, Shopify call,
or public wire-contract change. The runtime v1 capability matrix remains unchanged: search
and catalog output are not promoted by this synthetic work.

The oracle requires one canonical `Game`, considers only `single` Products in that game, and
emits only `ACTIVE` plus Online-Store-published records. `canonical_card_name` is its sole
match source. It never falls back to commercial title, handle, variant title, SKU, tags,
vendor, description, set data, or other metadata. Missing canonical names are reported by a
separate game-scoped accounting function and are never silently derived.

## Frozen oracle semantics

Normalization is exactly:

1. Unicode NFKC;
2. Unicode case-folding;
3. whitespace split and single-space join.

No punctuation is removed. Percent, underscore, apostrophes, periods, hyphens, commas,
slashes, and quotes remain literal characters. This also prevents an acceptance oracle from
accidentally acquiring SQL `LIKE` wildcard behavior.

Matching uses a global tier gate. If any exact normalized canonical name exists, every print
of that exact name and no broader name is returned. Otherwise all prefix matches are
returned; contains matches are used only when neither exact nor prefix matches exist. The
selected tier is ordered by normalized canonical name and then by the unbounded decimal
component of the full Product GID, represented as `(digit length, digit text)` without
integer coercion.

Suggestions group the selected hits by normalized canonical name. `print_count` is the exact
number of eligible Product records in the group. `available_print_count` counts only records
whose frozen v1 `total_inventory` is positive; `available` means that count is nonzero. The
label is only a synthetic positive-inventory fact, not verified Shopify sellability. The
oracle does not infer any additional availability semantics from commercial text, inventory
policy, tracking state, or unverified fields.

An empty normalized query returns an explicit `browse` routing result with no search hits;
it does not implement browse. Inputs are bounded to 1,000,000 records, a 256-codepoint query,
and a 1,024-codepoint canonical name. The Product bound matches the shared #7/#10 internal
safety envelope and leaves room for a future whole-baseline oracle run; it is not a production
capacity, latency, or scalability claim. The complete supplied tuple is validated before
game filtering, so a future baseline proof need not partition away cross-game leakage checks.
Duplicate Product GIDs, non-v1 records, forged runtime records, invalid Unicode, or
non-canonical game values fail closed.

Both oracle entry points accept an optional keyword-only `checkpoint`. It is invoked before
input validation, before each record handled by validation and selection, and throughout
result ordering and materialization loops. A checkpoint return value has no meaning:
cancellation is signalled only by raising the caller's runtime cancellation exception. The
oracle neither catches nor translates that exception, so it propagates unchanged and no
partial search result or coverage report is returned. With no checkpoint, call signatures
and domain-error behavior remain backward compatible.

## Prepared activation index

`prepare_single_card_search(records)` validates and canonically copies the complete bounded
Product tuple once, then retains only immutable storefront search fields in four isolated,
sorted game indexes. A serving composition must build this concrete `SingleCardSearchIndex`
once when a verified generation is activated, bind that exact index to the generation, and
pass it to `search_single_cards` (or call its `search` method). Exact and prefix lookups start
with a binary search; contains matching scans only the pre-normalized game index. Requests do
not render or decode Product/Variant graphs, normalize catalog names, or sort the full game
again. The original tuple call remains compatible as the reference/oracle path.

Preparation and every potentially long request loop retain cooperative checkpoints. Invalid
records, duplicate Product GIDs, unsupported names, a forged/uninitialized prepared index,
an invalid game, or an over-bound query fail closed with value-free domain errors. The index
is a detached snapshot: replacement of the source tuple after activation cannot alter its
stored search fields.

Every supplied Product is outer-validated, rendered to canonical v1 JSON, and decoded back
through the complete runtime schema before it is searched or reported. Only the reconstructed
Product graph is consumed. This makes nested Variant and selected-option validation part of
the oracle boundary and normalizes validation or serialization failures to
`CanonicalSearchError`. Public failures retain neither the nested exception cause/context nor
its traceback values, because malformed source fields may be attacker controlled.

## Evidence boundary and real-data gaps

`tests/fixtures/canonical_search_v1.json` is explicitly marked `synthetic-only` and contains
no live count claims. It covers four-game collisions, duplicate prints, Unicode equivalence,
punctuation, literal percent/underscore, match-tier ambiguity, non-card commercial-title
traps, availability counts, and missing-name reporting.

`NLA_DATA_ROOT` is missing. This slice therefore does not establish:

- current canonical-name coverage or extraction provenance;
- the historical Lightning Bolt, Pikachu, Blue-Eyes White Dragon, or Monkey.D.Luffy live
  counts;
- recall, result distributions, latency, or ordering on the current Shopify baseline;
- availability correctness beyond the explicit positive-`total_inventory` oracle rule;
- a production search/index capability. The synthetic regression proves only that one
  worst-case contains request over 30,001 prepared records stays below the two-second request
  budget on CI; index preparation is deliberately outside that request measurement.

Those claims require the independently reviewed real-baseline reconciliation gate and a
separate production implementation. Until then every relevant runtime capability remains
provisional or unsupported and no catalog output is authorized.
