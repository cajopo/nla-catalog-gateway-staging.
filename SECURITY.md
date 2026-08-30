# Security policy

## Trust boundaries

- Shopify and TCG PowerTools are the commercial source of truth.
- The catalog database is a read-only projection.
- The browser is untrusted.
- App Proxy signatures authenticate Shopify-originated storefront requests; an `Origin` header does not.

## Required production controls

- App Proxy HMAC-SHA256 verification using the app client secret.
- Exact shop allowlist and bounded timestamp age.
- Constant-time signature and cursor comparisons.
- Signed, expiring, query-bound cursors.
- Read-only SQLite connections for public requests.
- Rate limiting at the edge and application level.
- Strict query and page-size limits.
- No Admin token in public payloads or logs.
- Atomic dataset replacement and rollback.
- HMAC and delivery-ID verification for future webhook ingestion.

## Secret handling

Secrets are provided through the deployment platform. Rotate a secret immediately if it appears in Git history, logs, screenshots, issue comments, or theme code.
