# OAuth read-scope compatibility (#97)

2026-09-26: NLA Catalog version `nla-catalog-4` was released and the merchant
approved the access update. The installed app now grants `write_products` and
`write_publications`; this is not authorization to publish products.

Official contract: https://shopify.dev/docs/apps/build/authentication-authorization/manage-access-scopes
states that a write scope includes its corresponding read permission. The actual
client-credentials token response omitted `read_products` in favor of
`write_products`. The previous literal read-scope check rejected this valid token.

The transport now accepts each exact required read scope OR the corresponding
exact write scope. It still rejects incomplete permissions and similar-looking
scope names. Token, expiry and transport validation remain unchanged. The gateway
remains read-only; accepting broader credentials does not add write operations.

Verification: 95 focused HTTP transport tests passed (including all eight read/write
combinations and unrelated/suffixed write scopes); Ruff check/format passed.
Independent diff review: no material findings. A memory-only copy of the corrected
client successfully queried currentAppInstallation on the VPS and confirmed the
actual shop and new grants. No Shopify product was created or published.

Deployment NOT performed. Installed refresh source remains pinned to `25644a1`.
A separate, earlier refresh interruption requires recovery before changing the
operator package: run `20260926t030020z-81018c7b`, pending marker retained,
preflight accepted, promote exited 0, candidate container only created, previous
runtime still running. Do not blindly rerun or remove the pending marker.
GitHub push/CI remains held for the owner's Actions quota reset.
