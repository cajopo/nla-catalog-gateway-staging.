# WS-07 — One-step VPS Bulk acquisition (#89)

## Scope

Branch `agent/vps-bulk-acquisition`, based on merged #88 (`9fe7358`).
`python -m scripts.capture_shopify_bulk` performs one acquisition step: launch the
two existing read-only exports, check them, download original JSONL, then reuse
`run_reconciliation` and `run_packaging`. The output is a verified **candidate**,
never the active catalog. No new service, queue, dependency or catalog schema.

If exports are still running, the command returns JSON `status: pending` and exit
code 3. Run the same command again later with the same directory and inputs.
Exit 0 means `candidate-ready`; exit 1 means failure, with only a fixed redacted
diagnostic. This is an operator command, not a scheduler or automatic retry loop.

Run the operator command from the reviewed source checkout (not the wheel alone).
Use a pre-created, empty `0700` directory outside the checkout, owned by the
operator UID. A nonblocking file lock prevents two cooperating writers. Paths are
checked without symlink traversal using the existing Linux reconciler helpers.
Root or a hostile process under the same UID is outside this isolation boundary.

Credentials are environment-only `SHOPIFY_CLIENT_ID` and `SHOPIFY_CLIENT_SECRET`.
They must belong to the installed, released app and store in the same Shopify
organization. The client-credentials exchange caches the token only in memory,
refreshes before expiry, and checks granted `read_products`, `read_inventory`,
`read_locations`. This is not evidence that the real app has been installed.

Required non-secret arguments:

```sh
python -m scripts.capture_shopify_bulk \
  --shop-domain SHOP.myshopify.com \
  --online-store-publication-gid gid://shopify/Publication/APPROVED_ID \
  --code-sha REVIEWED_40_HEX_SHA \
  --capture-directory /private/capture-unique \
  --canonical-names-jsonl /private/names/canonical-names.v1.jsonl \
  --canonical-names-manifest /private/names/canonical-names-manifest.v1.json \
  --canonical-manifest-sha256 INDEPENDENT_64_HEX_PIN
```

The example paths are placeholders: supply actual artifacts produced by the
existing canonical-name builder. Never put secrets on the command line or in Git.

## Evidence and recovery

- Independent exact Shopify counts (uncapped) precede both launches. The same
  counts and shop are checked on resume and after both successful terminal exports.
  Structured-single counts cover the entire baseline, including unpublished
  products, matching the existing canonical-name enrichment audit.
- The checkpoint binds original count observation, shop, API version, approved
  Online Store publication ID, query/control hashes, code SHA and independently
  supplied canonical manifest/sidecar pins. Inputs are revalidated on every run.
- A launch intent is persisted and fsynced **before** each start request. An
  uncertain response never triggers a blind replacement export. Supply
  `--recover-products-operation-id` or `--recover-variants-operation-id` only after
  operator inspection; adoption checks the authenticated shop, exact query, QUERY
  type and creation time within the original capture interval. IDs must differ.
- API version is pinned to `2026-07`; the response header must match. OAuth and
  GraphQL accept only the configured shop over verified HTTPS, no proxy/redirect.
  Downloads use only `storage.googleapis.com:443`, no Admin headers or redirects,
  original uncompressed bytes, exact terminal length, SHA256, 2 GiB / 20 minute
  limits and a per-read deadline. Partial/failed exports cannot produce a candidate.
- Neither credentials nor signed download URLs appear in persisted checkpoints,
  terminal evidence or normal CLI output. Partial files stay private for deliberate
  inspection. A crash between publication and checkpoint can require inspection;
  uncheckpointed artifacts are never silently adopted, overwritten or deleted.
- Completed downloads are rehashed on resume; terminal evidence must still agree.
  Packaging reopens the exact bundle selected by its hash. A completed candidate
  is reopened against its recorded manifest hash on a later invocation.

Equal counts prove cardinality, **not** a transactional Shopify snapshot, unchanged
prices/stock, or canonical-source freshness. The existing 24-hour capture fence
still applies. The manifest has no freshness timestamp: its external pin and current
source coverage remain operator responsibilities. Missing mappings fail closed.

## Verification status

Three new control operations were validated through both the installed Admin skill
validator (bundled `2026-04` schema) and the Shopify plugin validator. Exact fields
were checked via schema discovery and current `2026-07` primary documentation.
Neither validation executes an export. Runtime version-header validation is separate.

Native Linux container `nla-capture-v3`: **180 passed in 6.25s**, no skips/warnings;
**100% line and branch coverage** of both new modules (457 statements, 168 branches).
Python 3.13.15, UID10001, network disabled, read-only source/root, private tmpfs,
1 CPU / 1 GiB limit. Source archive SHA256:
`5bef4d8f8229459cc0297bada51c4156ebd33b4a7241ffc5cd163ac48ac91e47`.
Source is mounted at `/work/repository.` to match the real checkout suffix.

The tests drive the real OAuth/GraphQL/download transport with controlled HTTP
responses, then real reconciliation, bundle reader, packaging, SQLite and runtime
search. Coverage includes four-game name/code/suggestion isolation, sold-out cards,
pending resume, explicit recovery after ambiguous starts, independent-count drift,
failed/partial downloads, tampered pins and interrupted packaging without repeating
reconciliation or downloads. Existing active data is unchanged in every case.

```sh
python -m pytest -c /work/repository./pyproject.toml \
  /work/repository./tests/test_shopify_capture_http.py \
  /work/repository./tests/test_capture_shopify_bulk.py \
  /work/repository./tests/test_capture_shopify_bulk_boundaries.py \
  -q --tb=short -o cache_dir=/tmp/pytest-cache --basetemp=/tmp/nla-capture-pytest \
  --cov=scripts.capture_shopify_bulk --cov=nla_catalog_gateway.shopify_capture_http \
  --cov-config=/work/repository./pyproject.toml --cov-report=term-missing
```

Independent review found two Medium issues, both corrected and re-reviewed PASS:
descriptor cleanup around acquisition/interruption and verification of the actual
Shopify response API version. Native testing also exposed the inherited directory
descriptor offset after lock creation; enumeration now opens a fresh descriptor.
One test initially referenced a nonexistent DTO field; it now checks the actual
variant inventory/tracking contract. No production gate or coverage threshold was
relaxed. Local Ruff and non-isolated source/wheel build pass. Exact-head independent
review binding and repository-wide CI remain mandatory before technical merge.

No real acquisition, scheduler, automatic activation or Shopify theme change belongs
to this delivery. The #11 incremental/scheduled path, persistent activation/restart,
owner price/stock lag decision and actual App Proxy end-to-end proof remain open.

Primary references:

- [Client credentials grant](https://shopify.dev/docs/apps/build/authentication-authorization/client-credentials-grant)
- [Bulk query start](https://shopify.dev/docs/api/admin-graphql/2026-07/mutations/bulkOperationRunQuery)
- [Bulk operation status](https://shopify.dev/docs/api/admin-graphql/2026-07/queries/bulkOperation)
- [Product counts and filters](https://shopify.dev/docs/api/admin-graphql/2026-07/queries/productsCount)
- [API version response header](https://shopify.dev/docs/api/usage/versioning)
