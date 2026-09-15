# WS-01H — Source card metadata (#65)

## Candidate — 2026-09-15

`agent/source-card-codes`, based on `94d95ad` / draft PR #64. That parent now has
successful CI `35014489057` and CodeQL `35014489039`. No Shopify, PowerTools, MAIN,
clone upload, provider or deployment mutation.

The existing CSV compiler retains collector number, expansion code/name and rarity.
Metadata follows the already-audited game/source-ID join through ProductFacts,
reconciliation, retained SQLite JSON and public catalog items. Shared SQL search and
suggestions additionally match collector numbers; expansion/rarity alone never match.
Existing name/SKU/barcode matching remains. No composite printed code is guessed.

## Compatibility and data policy

- Optional `cardMetadata` has exactly `collectorNumber`, `expansionCode`,
  `expansionName`, `rarity`. Absent metadata is omitted, retaining legacy bytes.
  Explicit null extension, unknown keys, wrong types, NUL and unsafe controls fail.
- Empty CSV cells become null. Nonempty source text is preserved, including benign
  whitespace; search applies existing normalization and omits blank normalized codes.
- Real sources contain nine Magic collector cells equal to a space and one Pokemon
  collector cell with a trailing TAB. Neither drops a record or fabricates a code.
- Each field is bounded to 1,024 codepoints; source record byte bound is 24 KiB to
  permit combined Unicode fields and name to round-trip.
- Metadata attaches only inside the audited product-type single join. Singles
  classified through other supported signals retain their existing behavior without
  an invented or unaudited lookup. Duplicate Shopify products remain distinct GIDs.
- Source/mapping hashes and product content hashes bind the attributes. Derived SQL
  columns are checked against retained records; core proof samples collector queries.
- Physical SQLite schema v2 is unchanged. Older readers reject enriched records;
  promote reviewed application, verifier SHA and regenerated package together.
  Keep their previous versions together for rollback. Never relabel an old proof.

## Recovered sources and historical coverage

The four original 2026-07-27 CSVs exist outside Git in the Desktop project archive's
`02_export_originali` folder. Prior "awaiting CSV input" statements are superseded.
No raw CSV, snapshot, database or generated artifact is committed.

Read-only join against the recovered September 7 schema-v1 database:

| Game | Public singles | Paired source IDs and name match | Nonempty number + expansion cells |
| --- | ---: | ---: | ---: |
| Magic | 122,530 | 122,530 | 99,894 |
| Pokemon | 71,604 | 71,604 | 67,675 |
| Yu-Gi-Oh | 85,991 | 85,991 | 84,998 |
| One Piece | 11,662 | 11,662 | 11,119 |
| Total | 291,787 | 291,787 | 263,686 |

These are historical raw-cell presence counts, including the nine whitespace-only
Magic cells, not proof of usable printed identifiers, current Shopify counts or current
package acceptance. Every product is retained even when metadata is missing.

## Verification and remaining scope

Initial original contract/source/search suite: 180 PASS including full 30,001-result
code-only keyset traversal and positions 24,999–25,001. Initial metadata/reconciliation/
signed-HTTP suite: 204 PASS; wider suite: 402 PASS and new metadata module 100% coverage.
Independent review found and prompted correction of the three cases above: real source
whitespace, out-of-scope join and combined Unicode byte bounds. Final focused rerun:
485 PASS, metadata module 100% line/branch coverage. Independent re-review APPROVE,
47 metadata tests independently passed. All four real CSVs parse successfully with
the current compiler: 136,697 / 84,277 / 94,614 / 17,079 rows (332,667 total).
The 30,001-result collector-only traversal passes (87.23s for the whole test), with
all records sold out, complete ordered ID equality, 24,999–25,001 boundaries and
SQL query-plan checks. This is synthetic correctness evidence, not real latency.
Staged preflight: 109 files, zero findings. Exact-SHA CI remains required.

Reproducible local commands (repository virtual environment):

```text
python -m pytest tests/test_card_metadata.py tests/test_canonical_names.py tests/test_runtime_contract.py tests/test_core_evidence.py tests/test_runtime_suggestions.py tests/test_reconciliation.py tests/test_taxonomy.py -q --cov=nla_catalog_gateway.card_metadata --cov-report=term-missing -p no:cacheprovider
python -m pytest tests/test_search_sql.py::test_literal_search_traverses_30001_with_indexed_keyset[collector] -q -p no:cacheprovider
python -m build --no-isolation
```

Build passes. Ruff check/format passes over all 57 tracked/candidate Python files.
The blanket format scan crashed on pre-existing inaccessible temporary directories;
explicit Git-file enumeration avoids those unrelated directories without excluding code.

The first reconciliation run failed on pre-existing local CRLF GraphQL copies.
Restoring the existing LF policy reproduced the two already-approved query SHA-256
values exactly, with no semantic Git diff or weakened validation.

Full goal remains open: compound printed identifiers absent from collector cells need
verified semantics; images, current real package, durable sync, retained cursor
generations, staging, clone installation and real E2E still remain.
