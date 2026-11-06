# Unified NLA TCG Catalog: isolated commercial pilot

Issue: [#119](https://github.com/cajopo/nla-catalog-gateway-staging./issues/119).
Source baseline: `90f4f49bf2094fa2af51dff3a998b82054d93c76`.
Copy branch: `agent/commercial-pilot`.

## Delivery boundary

One product combines catalog/search and missing-printing import. This delivery
adds a separate operator control-plane foundation: private shop workspaces,
read-only Shopify subscription verification, and an executable synthetic pilot.
Existing runtime, importer, theme, container command, schedules and deployment
defaults remain byte-for-byte unchanged.

This is not a public Shopify app installation, sale-ready release, operational
importer authorization or Shopify approval. The operational runtime never imports
or starts the new package.

## Offline pilot and preview

With development dependencies installed in this copy:

```powershell
./.venv/Scripts/python.exe -m nla_catalog_gateway.commercial demo
./.venv/Scripts/python.exe -m nla_catalog_gateway.commercial demo --html "$env:TEMP/nla-commercial-preview.html"
```

The demo uses two synthetic shops and an injected provider envelope with the
real subscription parser. Temporary private workspaces are removed afterwards.
Alpha has a simulated subscription; beta has none. Neither has verified
installation or operational activation. Zero live requests are performed.
The optional HTML preview is explicitly labelled synthetic; existing files are
never replaced. Keep generated previews outside Git.

## Operator workspace

Create a dedicated private root outside every source checkout and every existing
NLA runtime, catalog, importer or backup directory. On POSIX it must be owned by
the running user and have owner-only permissions. On Windows the operator must
first enforce a private ACL; chmod does not establish ACL security.

Example with synthetic identities (replace them with verified merchant values):

```powershell
./.venv/Scripts/python.exe -m nla_catalog_gateway.commercial provision --root C:/private/commercial-pilot --shop-domain pilot-example.myshopify.com --shop-gid gid://shopify/Shop/103
```

The manifest contains no token or secret. Repeating the same identity and
authorization is idempotent. Conflicting identity/authorization, unsafe paths and
interrupted initialization are rejected, never overwritten or silently repaired.
`--authorize-importer` records an operator setting only: it proves neither
merchant consent, OAuth installation, ledger ownership nor operational permission.

## Authoritative subscription check

After separate public app and Partner API setup, provide host-only environment:

- `NLA_COMMERCIAL_PARTNER_ORGANIZATION_ID`
- `NLA_COMMERCIAL_PARTNER_ACCESS_TOKEN`
- `NLA_COMMERCIAL_APP_GID`
- `NLA_COMMERCIAL_PLAN_HANDLES`

Run `python -m nla_catalog_gateway.commercial check --shop-domain <domain> --shop-gid <GID>`.
The token is never accepted on the command line, persisted or printed. No existing
runtime environment values are used as a fallback.

Only Shopify's documented Partner subscription read is performed. No charge,
Admin product mutation, publication, runtime activation or importer command is
performed. Eligibility alone does not prove merchant installation.

Unknown plans, unsupported pricing, trial-only subscriptions, expired cycles,
cross-shop/app/domain evidence and unavailable/ambiguous responses grant no
eligibility. Fixed recurring supported subscriptions only; other plan types
require explicit implementation and tests before use.

## Remaining sale and live gates

1. Separate public production app identity and appropriate authentication for
   unrelated merchant organizations; installation, uninstall and privacy lifecycle.
2. Reusable theme integration and per-shop runtime/capture provisioning with
   separate secrets, cursor material, datasets, inboxes and importer ledgers.
3. End-to-end subscription enforcement and safe cancellation/downgrade behavior.
4. Merchant approval for importer writes plus fresh identity, media, zero-stock
   and ledger checks under the existing create-only boundaries.
5. Live sandbox acceptance, restore/rollback evidence, support, commercial terms,
   catalog/image use terms, independent review and Shopify App Store approval.
6. Paid independent-store pilots measuring search success, release-work savings,
   support cost and willingness to renew.

## Official contracts checked 2026-10-20

- [Distribution](https://shopify.dev/docs/apps/launch/distribution):
  unrelated merchants require public distribution. Custom distribution serves
  one shop or the same Plus organization. Hosting isolation changes neither
  distribution nor approval requirements. Preserve the existing NLA app identity.
- [Visibility](https://shopify.dev/docs/apps/launch/distribution/visibility):
  limited visibility changes discovery, not public review requirements.
- [App Pricing](https://shopify.dev/docs/apps/launch/billing/shopify-app-pricing):
  new supported public recurring plans use Shopify App Pricing. One-time app
  purchases require the supported Manual Pricing path; no charges are created here.
- [Active Subscription](https://shopify.dev/docs/api/partner/2026-07/active-subscription):
  Partner API with App/Shop GIDs and a server-owned Partner token, distinct from
  Admin tokens and the old subscription webhooks.
- [Client credentials](https://shopify.dev/docs/apps/build/authentication-authorization/client-credentials-grant):
  existing capture auth is limited to the same organization. It remains unchanged;
  a subscription check is not a replacement for merchant OAuth.

No live API behavior was observed. Documentation and synthetic tests do not
prove approval, installed-merchant acceptance or product-market fit.
