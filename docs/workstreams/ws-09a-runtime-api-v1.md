# WS-09A — Runtime API v1 fail-closed skeleton

## Scope

Issue #33 introduces only a framework-independent HTTP boundary around the accepted runtime
contracts. This branch contains no HTTP server, App Proxy secret or cryptography, Shopify client,
SQLite projection adapter, search engine, facet engine, deployment configuration, or theme code.
It never mutates Shopify, TCG PowerTools, a theme, or a production resource.

The shipped concrete components are deliberately unusable for public catalog output:

- `DenyAllProxyAuthorizer` rejects every request;
- `UnavailableCatalogBackend` exposes no generation;
- `FailClosedCapabilityGate` authorizes neither catalog output nor readiness;
- every catalog request must also pass `CatalogRequestV1.require_executable()`;
- every candidate response must pass `CatalogPageV1.require_output_capability()`;
- readiness additionally requires the frozen contract features `activeIndex`, `catalogOutput`, and
  `cursorCodec` to be `verified`.

The current v1 capability matrix cannot claim those states. Dependency injection is present for
deterministic fake-backed tests and future reviewed adapters, but an injected gate alone cannot
bypass the frozen request/page gates.

## Transport boundary

The intended catalog route is a strict `POST` to a configured App Proxy path. A thin adapter must
construct `RuntimeHttpRequest` without interpreting or rebuilding the raw query. The future #12
adapter receives those exact bytes and returns only a canonical, redacted `shop_domain`. The
service separately binds that identity and every acquired dataset lease to one configured expected
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
DTOs, queries over 256 characters, and incompatible query/family or subtype/family combinations.
It never falls back to browse when search or filters are unsupported.

## Bounds and cancellation

`RuntimeLimits` applies hard ceilings to body chunks, request and response bytes, cursor length,
raw query, path, header count, per-header name/value size, aggregate header bytes, and a monotonic
request deadline. The default request body limit is 64 KiB; the complete response envelope is
limited to the 2 MiB runtime-contract ceiling. Every emitted cursor for an accepted request must
fit the configured next-request body/cursor bounds.

One `RequestControl` is passed to authorization, generation acquisition, capability evaluation,
and page execution. Cooperative cancellation has precedence over normalized dependency errors and
is propagated as `RequestCancelled`; it is never converted into an HTTP response. A lease is
closed exactly once after success, ordinary failure, timeout, or cancellation, including a race in
which cancellation occurs immediately after acquisition. The future #7 SQLite adapter still needs
a deadline/cancellation hook such as a bounded busy timeout and progress handler; wrapping a query
in a worker thread is not sufficient cancellation.

## Pinned generation and fixed failures

`CatalogBackend.acquire(control=...)` returns one immutable `CatalogGenerationLease`. The service
reads its generation once, executes through that same lease, defensively round-trips the returned
page, removes its internal unsigned cursor context, and requires request, shop, page generation,
terminal state, and opaque-cursor presence to remain consistent. A concurrent backend activation
cannot cause a second selection within the request.

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

1. Merge and independently accept #7 and #12. Add a #12 verifier/exposure-policy adapter and a #7
   lease API that selects exactly once and signs/validates opaque cursors.
2. Keep the resolved public page/cursor boundary intact: only the opaque signed cursor may cross
   the wire; unsigned cursor context remains internal.
3. Produce baseline evidence and a reviewed capability promotion. The current frozen v1 matrix
   intentionally forbids public output and readiness.
4. Build one generation-bound query engine instead of copying the in-memory acceptance oracles:
   #9 search scope, #10 filters/facet counts, and #7 keyset traversal must share the same lease.
   Search capability and a public facet response schema do not yet exist.
5. Add a publication coordinator between #11 sync generations and #7 immutable projections. A
   `GenerationView` is not by itself a `DatasetManifestV1`/SQLite activation.
6. Through #13, select the server/provider and prove ingress isolation, App Proxy secret lifecycle,
   TLS/DNS, rate limiting, effective security headers, internal health routing, logging redaction,
   shutdown, timeouts, observability, and rollback.
7. Through #14, integrate only the unpublished theme clone and submit only the opaque
   `nextCursor`. Live publication remains reserved to the cutover gate.

Until every applicable gate is accepted, direct production routes remain denied and the service
must return an explicit unavailable/unsupported response rather than silently falling back to an
incomplete native catalog.
