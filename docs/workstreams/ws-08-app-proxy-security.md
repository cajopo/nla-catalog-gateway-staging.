# WS-08 — Shopify App Proxy verification v1

## Status and boundary

This branch is a local, framework-independent security candidate for GitHub issue
[#12](https://github.com/cajopo/nla-catalog-gateway-staging./issues/12). It verifies the
Shopify App Proxy request contract and defines a fail-closed route-exposure policy. It does
not install an app, access Shopify, load an Admin token, mutate Shopify or PowerTools, deploy
a service, change a theme, or enable a public route.

The implementation is `src/nla_catalog_gateway/app_proxy_security.py`. It has no network,
database, file-system, logging, or Shopify SDK dependency.

## Protocol source

The sole protocol source is Shopify's current official documentation,
[Authenticate app proxies](https://shopify.dev/docs/apps/build/online-store/app-proxies/authenticate-app-proxies),
checked on 2026-09-02 through the Shopify developer-documentation search supplied by the
installed Shopify plugin and directly against the current page.

The documented algorithm parses and percent-decodes the raw query, groups repeated values in
arrival order, renders each parameter as `key=value1,value2`, sorts those complete rendered
parameters, concatenates them without separators, removes `signature`, and computes a
lowercase hexadecimal HMAC-SHA256 with the app's shared secret. The verifier follows that
algorithm exactly before applying NLA's additional fail-closed constraints.

Shopify's two displayed examples are retained as protocol anchors for logged-in and anonymous
requests. Their displayed shop is the redacted placeholder `{shop}.myshopify.com`; therefore
the published digest cannot be recomputed from the displayed text. Tests assert the published
canonical text and signature independently, then run an adapted valid-domain vector through
the complete verifier with an independently calculated digest.

Shopify also states that:

- `logged_in_customer_id` can be empty and signature validation alone does not authorize
  customer-owned data;
- merchants can customize the storefront proxy prefix/subpath, so the signed `path_prefix`
  might differ from a later app configuration;
- new query parameters can be introduced, so unknown safe parameters must remain in the
  signed canonical message;
- request methods and bodies can be forwarded, while the App Proxy signature parameters stay
  in the URL; and
- App Proxies strip cookies and several response headers.

## Verification contract

Callers provide the exact raw query bytes without a leading `?` and the decoded backend
request path. They must never reconstruct the query from a framework dictionary: doing so can
discard duplicates or change decoding before verification.

Verification proceeds in this order:

1. Enforce byte, parameter-count and component limits before expensive or application work.
2. Parse exactly one `=` per segment boundary, percent-decode once, treat `+` as space, and
   require strict UTF-8 and NFC text.
3. Reject empty/missing segments, control characters, malformed escapes, encoded security
   parameter names, second-stage `%HH` encodings and decoded `=` values. The last rule keeps
   the separator-free signed representation from acquiring an alternate parameter boundary.
4. Reject duplicate `signature`, `shop`, `timestamp`, `path_prefix`, and
   `logged_in_customer_id`. Repeated non-security parameters are collapsed to the exact
   comma-joined value signed by Shopify, so downstream code cannot reinterpret a signature
   collision as a different list shape.
5. Require one unencoded, exactly 64-character lowercase hexadecimal `signature`; remove it,
   reject non-ASCII text as the same bounded signature error, calculate HMAC-SHA256 and compare
   with `hmac.compare_digest`.
6. Only after the signature passes, validate the exact lowercase `*.myshopify.com` shop
   allowlist, signed storefront prefix allowlist, canonical backend route prefix and timestamp.
7. Return tuple-backed immutable normalized metadata without the supplied signature. Its
   representation redacts the shop, customer claim, path and parameters.

`hmac` is not accepted as an alias for App Proxy `signature`; it remains in neither an OAuth
nor webhook verification path by accident.

### Default limits

| Control | Default | Hard configuration ceiling |
|---|---:|---:|
| Raw query | 8 KiB | 64 KiB |
| Query parameters | 64 | 256 |
| Decoded key/value component | 4 KiB | raw-query limit |
| Backend request path | 2 KiB | 8 KiB |
| Accepted request age | 300 seconds | 3,600 seconds |
| Accepted future clock skew | 30 seconds | 300 seconds |

At verifier construction the public configuration is copied field by field and reconstructed
through the complete validator. The resulting immutable snapshot and clock are registered in a
private closure-owned, lock-protected weak identity map. The verifier instance has no config,
clock, snapshot or generic state slot that reflection can replace. Registration is one-write,
and only an exactly constructed consumer instance is accepted. Later mutation of the original
frozen dataclass, an exact private snapshot assigned through `object.__setattr__`, explicit
re-initialization, state copied from another verifier, a subclass, or an `object.__new__`
instance cannot change or acquire verification authority. Corrupted or incompletely forged
configuration instances fail at the boundary. Invalid types, empty allowlists, non-canonical
paths/domains and out-of-range limits fail at construction time.

## Replay policy

The default accepts a timestamp exactly 300 seconds old and exactly 30 seconds in the future;
older or further-future requests fail. The clock is injected, and ordinary callback failures
become a bounded configuration error. Process-control `BaseException` values are not swallowed.

The official App Proxy contract supplies no nonce. Consequently, a correctly signed URL can
be replayed inside the accepted window. This v1 boundary is suitable only for NLA's read-only,
non-customer-privileged catalog operations. Any future privileged or mutating operation needs
separate customer authorization and a distributed one-time replay store; neither is authorized
by this workstream.

## Shop, path and direct-origin policy

Allowed shops and merchant-visible `path_prefix` values are explicit immutable sets. A prefix
change in Shopify must be deliberately added and reviewed; accepting arbitrary `/apps/*`
values would weaken tenant and route isolation. The backend path must match the configured
prefix on a segment boundary, so `/proxy` and `/proxy/catalog` match while `/proxyevil`, dot
segments, double slashes and encoded path variants do not.

`GatewayExposurePolicy` makes the routing invariant explicit. Its validated immutable state is
also held only in a closure-owned weak identity registry. Public configuration values are
read-only properties; the instance has no policy/snapshot slot. Routing decisions read only the
registered state for that exact identity. An unregistered `object.__new__` instance or subclass
denies every route, and assigning an exact private development snapshot, re-initializing the
production object, or transplanting values from another policy cannot enable development
access.

- App Proxy routes require verification;
- direct `/api` routes are denied in staging and production;
- a direct route is possible only when both the environment is exactly `development` and the
  dedicated bypass flag is explicitly true; and
- enabling that flag for staging or production fails startup configuration.

This is a library contract, not a claim that a deployed edge already enforces it. WS-09 must
wire the policy before exposing a service and independently prove there is no direct-origin
bypass.

The in-process trust boundary assumes application code cannot monkeypatch module globals or
reach into and mutate closure cells. Code with that level of arbitrary interpreter privilege
can also replace the verifier itself and is outside this library's threat model. Ordinary
reflection on configuration DTOs or consumer instances, including `object.__setattr__`, is in
scope and cannot read or replace the registered trust state. The application process and its
dependency-injection wiring therefore remain trusted deployment inputs.

## Response and logging contract

The module defines an immutable JSON response-header baseline: private/no-store caching,
`nosniff`, same-site resource policy, no-referrer, a deny-all content policy with no framing,
and disabled camera/geolocation/microphone. It intentionally provides no permissive CORS
header. Because Shopify documents that App Proxies strip cookies and other headers, WS-09 must
verify the effective headers both at the backend origin and through the installed proxy rather
than assume pass-through.

The verifier performs no logging. Public failures contain only one fixed message selected from
a stable code; they never contain the shared secret, calculated digest, supplied signature,
full query, shop, customer ID or attacker-controlled value. The verified result also excludes
the signature and redacts all request fields from `repr`.

## Threat and evidence matrix

| Threat / failure | Local control and automated evidence | Remaining operational gate |
|---|---|---|
| Query tampering | HMAC-SHA256 and constant-time comparison; altered field test | Real installed App Proxy vector |
| Duplicate security keys | Decoded-name duplicate rejection, including encoded aliases | Framework must pass raw bytes |
| Encoding ambiguity/injection | Strict escapes/UTF-8/NFC, one decode, bounded keys, no decoded `=` | Runtime must not decode returned values again |
| Cross-shop request | Canonical `myshopify.com` validation plus exact allowlist | Production shop value/rotation procedure |
| Wrong proxy route | Signed storefront allowlist plus backend segment-boundary check | Edge route configuration |
| Replay / clock skew | Injectable clock; inclusive 300-second/30-second boundary tests | Clock monitoring; one-time store if scope changes |
| Customer-ID privilege confusion | Field named `claimed_*`, empty/malformed tests, no authorization API | Separate authorization for any customer data |
| Direct `/api` bypass | Production/staging deny and startup failure for bypass flag | Deployed route and origin-access test |
| Query/CPU exhaustion | Raw size, parameter and component ceilings | Distributed/edge rate limiting in real hosting |
| Forwarded-IP spoofing | Verifier never trusts or consumes forwarding headers | Trusted-proxy and rate-limit design in WS-09 |
| Secret/query leakage | No logging; bounded fixed errors and redacted representations | Redaction verification in deployed logs/APM |
| Header/CORS drift | Immutable restrictive baseline and tests | Confirm Shopify/edge pass-through behavior |
| Post-validation state forgery | Revalidated snapshots in one-write identity registries; exact-snapshot, alias, re-init, transplant, subclass and `object.__new__` regressions | Restrict privileged monkeypatch/closure access |

Adversarial tests cover both official examples; valid anonymous/customer-claim flows; repeated
parameters and sort order; percent-case, spaces and Unicode; tampering; signature case, size and
alphabet; encoded/duplicate security keys; missing fields; malformed UTF-8 and escapes;
second decoding, normalization and delimiter ambiguity; all configured limits; path traversal
and prefix confusion; shop-domain confusion; timestamp boundaries; clock failure and
`BaseException`; customer claim formats; non-ASCII signatures; post-construction mutation and
forged configuration/policy instances; exact private snapshot replacement; cross-instance
state transplant; explicit re-initialization; subclass and `object.__new__` consumers;
route-policy startup invariants; immutable error and header contracts; and secret/request
redaction.

## Explicitly deferred from #12

The issue remains open after this local v1 candidate. The following require later work and real
environment evidence:

- app creation/installation, minimum scopes, offline token handling and proxy configuration;
- deployment and edge/origin access controls;
- trusted-proxy selection and distributed per-endpoint rate limits;
- secret storage, dual-key rotation and operational alerting;
- dependency/runtime policy for the eventual HTTP service;
- verification that no endpoint exposes the database/file system or introduces a Shopify
  mutation; and
- independent security review with no unresolved Critical or High finding.

No customer authorization, Admin mutation, Shopify write, PowerTools change, theme edit or live
publication is part of this candidate.
