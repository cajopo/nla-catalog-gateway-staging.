# Security policy

## Trust boundaries

- Shopify and TCG PowerTools are outside this repository and remain authoritative.
- Catalog data is a read-only projection.
- Browser input, cursors, webhook payloads and proxy headers are untrusted.
- Admin credentials and Shopify app secrets are server-side only.

## Repository controls

- No credentials, signed Bulk URLs, snapshots or generated databases in Git.
- GitHub Actions use read-only repository permissions unless a narrowly reviewed workflow proves a write permission is necessary.
- Workflows must not commit generated artifacts back to `main`.
- Dependency audit, static analysis, tests, repository preflight and container smoke are required before merge.

## Reporting

Open a private security report with the repository owner. Do not place tokens, customer information, exploit payloads or production secrets in an issue or pull request.
