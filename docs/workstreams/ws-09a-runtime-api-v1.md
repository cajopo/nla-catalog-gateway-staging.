# WS-09A — Evidence-bound runtime API v1

## Search v2 follow-up (#60, 2026-09-15)

Search result pages now use SQLite, with optional first-page `suggestions` from the same
lease and predicate. See `ws-05-name-code-search-v2.md` for wire fields, compatibility,
tests and remaining source-code/UI work. Issue #62 replaces only the redundant static
output checks, as described below.

## Scope

Issue #33 integrates the accepted, framework-independent runtime components without adding an HTTP
server, Shopify client, deployment configuration, or theme code. It never mutates Shopify, TCG
PowerTools, a theme, or a production resource.

`AppProxyVerifierAuthorizer` directly adapts the accepted verifier and exposes only the verified
shop domain. `EvidenceBoundCatalogBackend` atomically selects one immutable generation assembled
from `VerifiedReconciledGenerationV1`, `CatalogProjection`, `CursorCodecV1`, and
`VerifiedCatalogCoreEvidenceV1`. `EvidenceBoundCapabilityGate` authorizes only an exact open lease
issued by that backend.

The safe defaults remain deliberately unusable for public catalog output:

- `DenyAllProxyAuthorizer` rejects every request;
- `UnavailableCatalogBackend` exposes no generation;
- `FailClosedCapabilityGate` authorizes neither catalog output nor readiness.

`DEFAULT_CAPABILITIES_V1` is unchanged.

## Generation-based authorization (#62)

The concrete runtime no longer calls three historical global denial checks:

1. `_contract_output_is_verified()` (removed from the runtime module).
2. `CatalogRequestV1.require_executable()`.
3. `CatalogPageV1.require_output_capability()`.

The existing `EvidenceBoundCapabilityGate` is the runtime authority. It checks the exact
backend-issued lease and the complete six-way binding: shop domain,
reconciliation-summary SHA-256, dataset generation, catalog-content SHA-256, SQLite projection
content fingerprint, and the explicitly configured catalog-core verifier code SHA. The two source
part `sourceCodeSha` values must remain equal to each other, but are intentionally not equated with
the verifier code SHA: they describe different provenance.

Before verification or readiness, the service also requires an exact concrete composition:
`AppProxyVerifierAuthorizer`, `EvidenceBoundCatalogBackend`, and
`EvidenceBoundCapabilityGate`, with the gate carrying the backend's private identity token.
Protocol-compatible or permissive substitutes are never production authorization. Boundary unit
tests replace only this private attestation helper; there is no public enable flag.

The unchanged user goal and approved #17 architecture require the verified runtime to be
servable. No provider, deployment or live authorization is inferred from this code change.
The standalone DTO guards and frozen default matrix remain unchanged for callers outside
this concrete service. Missing/unverified dependencies still deny output; no public enable
flag or alternate route exists. The replacement preserves these fail-closed invariants:

- omitted dependencies still select the deny/unavailable defaults;
- non-evidence or cross-backend component compositions fail before authorization or acquisition;
- a lease from another backend, a closed lease, a changed projection, or any evidence mismatch is
  denied;
- one request acquires exactly one generation and an activation cannot rewrite that pinned lease;
- malformed/expired/context-mismatched cursors map only to fixed public error codes;
- cancellation propagates unchanged and is never normalized into a response.

Core proof schema v2 now exercises the actual SQLite search/suggestion path against
independent record-derived expectations (name/code substrings, stock, game, pagination
and suggestion counts). The opaque evidence object retains verification version 2;
runtime admission and lease checks reject legacy/malformed versions. Portable readers
reject schema-v1 proof reports. Filenames and outer package format remain unchanged.
Rebuild a package with the current verifier; never relabel an old proof. Rollback keeps
the previous application, package and deployment pins together.

Unused prepared Python search, facet and public-item copies were removed from runtime
generation assembly. Canonical records remain for integrity binding. Public single-name
raw/normalized length limits now run in projection build/reopen, preserving admission
constraints without rebuilding an unused search index.

### #62 verification checkpoint — 2026-09-15

- Tests exercise signed HTTP/ASGI catalog requests and readiness without monkeypatching
  composition, evidence or static activation checks. Unsigned requests, wrong routes and
  obsolete/malformed evidence remain denied. Host-configured bootstrap becomes ready only
  with a valid pinned package; an empty store stays not-ready.
- Core-verifier regressions deliberately inject missing, duplicate, cross-game, truncated,
  nonterminating and wrong-suggestion results; every corruption is rejected. The sampled
  `Duelist Ace`/`Ace` query and blank-SKU regression covers the P2 found in independent review.
- Focused run over `test_core_evidence`, `test_runtime_api`, `test_runtime_api_integration`,
  `test_runtime_suggestions`, `test_staging_generation`, `test_runtime_bootstrap`,
  `test_search_sql` and `test_sync_publication`, excluding `over_30000` and `traverses_30001`:
  367 passed. One additional ALL-family stock test passed and closed the last coverage branch.
  Combined, on unchanged production code: 1,647 statements / 504 branches, 100% across
  `core_evidence`, `runtime_api`, `search_sql` and `staging_generation`. No gate lowered.
- `pytest tests/test_runtime_api_integration.py -q -k over_30000 -x`: 1 passed in 249.89s.
  All 30,001 Products traversed through 301 signed page requests; search plus suggestions
  and stock filtering each under two seconds. Synthetic fixture, not real-data acceptance.
- `python scripts/preflight_repo.py`: 97 files, zero findings. Scoped Ruff check/format
  and `python -m build --no-isolation` pass. A final test-file formatting correction followed
  the first format check. Full isolated build/container/security gates require new-head CI.
- Independent read-only review: approve after the sampled-query normalization fix;
  separate probes verified both raw and normalization-expanded public name limits.

No full roadmap closure, real package acceptance, provider operation or Shopify mutation.

## Transport boundary

The intended catalog route is a strict `POST` to a configured App Proxy path. A thin adapter must
construct `RuntimeHttpRequest` without interpreting or rebuilding the raw query. The concrete
adapter passes those exact bytes to `AppProxyVerifier` and returns only a canonical, redacted
`shop_domain`. Verification failures become `ProxyRequestRejected`; verifier configuration or
internal failures become `ProxyVerifierUnavailable`. A checkpoint runs before and after
verification. The service separately binds that identity and every acquired dataset lease to one configured expected
`{shop}.myshopify.com` domain.

The request body is:

```json
{
  "contractVersion": 1,
  "cursor": "opaque-authenticated-token-or-null",
  "request": { "...": "CatalogRequestV1" }
}
```

The response body planned by #33 is:

```json
{
  "contractVersion": 1,
  "nextCursor": "opaque-authenticated-token-or-null",
  "page": { "...": "CatalogPageV1" }
}
```

The `page` sub-object contains the validated `CatalogPageV1` fields except
`nextCursorContext`. That unsigned internal material is always removed before serialization and is
rejected as an unknown field by the public decoder. `nextCursor` is the only cursor a client may
receive or send back. A private transport DTO reuses a terminal `CatalogPageV1` to validate the
remaining fields, then separately validates nonterminal item presence and opaque-cursor
coherence. Public response bytes must round-trip to the one canonical JSON representation.

The parser rejects duplicate or unknown keys, BOMs, malformed UTF-8/Unicode, floats, non-finite
numbers, oversized integers, unsupported versions, malformed opaque tokens, noncanonical request
DTOs, queries over 256 characters before or after NFKC normalization, and incompatible
query/family or subtype/family combinations.
It never falls back to browse when search or filters are unsupported.

## Bounds and cancellation

`RuntimeLimits` applies hard ceilings to body chunks, request and response bytes, cursor length,
raw query, path, header count, per-header name/value size, aggregate header bytes, and a monotonic
request deadline. The default request body limit is 64 KiB; the complete response envelope is
limited to the 2 MiB runtime-contract ceiling. Every emitted cursor for an accepted request must
fit the configured next-request body/cursor bounds.

One `RequestControl` is passed to authorization, generation acquisition, capability evaluation,
and page execution. Cooperative cancellation has precedence over normalized dependency errors and
is propagated as `RequestCancelled`; it is never converted into an HTTP response. Lease close is
idempotent and a closed lease fails closed. Pagination passes the same checkpoint into the SQLite
progress handler and removes that handler in `finally`; search, facet evaluation, tuple filtering,
keyset traversal, and variant accounting checkpoint their non-SQL loops.

## Pinned generation and fixed failures

`CatalogBackend.acquire(control=...)` returns one immutable `CatalogGenerationLease`. The concrete
backend validates the generation, manifest and projection before swapping the complete candidate
under one lock. The service
reads its generation once, executes through that same lease, defensively round-trips the returned
page, removes its internal unsigned cursor context, and requires request, shop, page generation,
terminal state, and opaque-cursor presence to remain consistent. A concurrent backend activation
cannot cause a second selection within the request.

Browse requests without `q` or filters, including a concrete family, use
`CatalogPaginator` and its SQLite Product-GID keyset. A generation prepares both the accepted #9
search index and #10 facet catalog once during activation. Request-time search and filtering reuse
those immutable facts without rebuilding or serializing the complete Product/Variant graph.
Search results and prepared facet results are paged as an immutable tuple by the same numeric
Product-GID keyset. `CursorCodecV1` binds the full request, generation, final Product GID, expiry,
endpoint, and contract version under HMAC. Query/filter cursors are authenticated before running
either accepted engine, so invalid input cannot force a catalog scan. No path uses `OFFSET`.
Facet counts and search suggestions remain internal in this slice; the wire response is only the
canonical page plus opaque cursor.

The synthetic service integration traverses 30,001 Products through 301 HTTP-boundary requests
with no duplicate or missing Product GID, including the 25,000 boundary. On the same prepared
generation, an exact search and a full-catalog inventory filter each complete within the default
two-second request deadline. This timing/traversal test uses pytest-cov's `no_cover` marker so
instrumentation does not distort the production request budget; the ordinary runtime suite covers
the same implementation at 100% statement and branch coverage. Test-only monkeypatches open only
the three documented static gates; the real App Proxy verifier, evidence-bound backend, concrete
capability gate, cursor codec, search index, facet catalog, and service boundary remain in the
exercised path.

Errors are serialized only through the frozen `CatalogErrorV1` messages. Request values,
exception text, SQL, paths, secrets, and signed query material are never copied into the response.
Malformed requests map to `invalid_request`; incompatible context to `incompatible_filter`;
cursor failures to the cursor codes; stale generations to restart/mismatch; unavailable or timed
out dependencies to the fixed 503 errors; and malformed dependency output to
`contract_violation`.

Liveness is process-only and does not inspect a dataset or call Shopify. Readiness selects at most
one lease, requires the exact expected shop and accepted capability evidence, and otherwise returns
a fixed non-sensitive `not_ready` response.

## Gates before a real adapter or public route

1. Produce and accept a real schema-v2 proof/package, with representative latency evidence;
   the synthetic runtime tests alone do not certify the historical 291k-product package.
2. Keep the resolved public page/cursor boundary intact: only the opaque signed cursor may cross
   the wire; unsigned cursor context remains internal.
3. Supply real baseline evidence and the reviewed verifier code SHA at composition time. Do not
   change the frozen v1 capability matrix.
4. The #60 suggestion extension requires explicit first-page opt-in. Public facet counts
   and richer card presentation fields are separate outstanding work.
5. The #57 full-reconciliation publication coordinator exists; durable event ingestion and
   incremental live publication remain outstanding. A `GenerationView` is not by itself a
   `DatasetManifestV1`/SQLite activation.
6. Through #13, select the server/provider and prove ingress isolation, App Proxy secret lifecycle,
   TLS/DNS, rate limiting, effective security headers, internal health routing, logging redaction,
   shutdown, timeouts, observability, and rollback.
7. Through #14, integrate only the unpublished theme clone and submit only the opaque
   `nextCursor`. Live publication remains reserved to the cutover gate.

Until every applicable gate is accepted, direct production routes remain denied and the service
must return an explicit unavailable/unsupported response rather than silently falling back to an
incomplete native catalog.
