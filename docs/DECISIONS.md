# NLA catalog gateway — decisions

## D-001 — External read-only gateway is the primary catalog architecture

- Status: accepted by Jacopo on 2026-08-31.
- Source: GitHub issue [#17](https://github.com/cajopo/nla-catalog-gateway-staging./issues/17).
- Decision: Admin Bulk plus an immutable versioned index and keyset API form the primary
  catalog path. Shopify App Proxy is the production storefront boundary.
- Consequence: native Shopify sharding cannot replace the gateway. It may be reconsidered
  only for a measured SEO or fallback benefit.

## D-002 — Shopify and TCG PowerTools authority boundaries

- Status: accepted and non-negotiable.
- Source: issues [#3](https://github.com/cajopo/nla-catalog-gateway-staging./issues/3)
  and [#17](https://github.com/cajopo/nla-catalog-gateway-staging./issues/17).
- Decision: Shopify remains authoritative for products, variants, prices, final inventory,
  product pages, cart, checkout, and orders. TCG PowerTools continues writing to Shopify.
  The gateway is a read-only projection.
- Consequence: this repository must never mutate those commercial records or disconnect,
  replace, or reconfigure PowerTools.

## D-003 — Four-family taxonomy

- Status: accepted product contract; implementation pending.
- Source: GitHub issue [#19](https://github.com/cajopo/nla-catalog-gateway-staging./issues/19).
- Decision: every included product belongs to exactly one of `single`, `sealed`,
  `accessory`, or `unclassified`; the last requires an actionable reason.
- Consequence: no record may be silently dropped, and rules cannot be keyed to individual
  GIDs, SKUs, or handles.

## D-004 — Recover PR #20 instead of replacing it

- Status: accepted technical execution decision on 2026-08-31.
- Evidence: repository-truth audit, CI run `33400328891`, CodeQL run `33400328929`, and
  independent adversarial audit of head `e5c7e92201fb8c1204680733a53f2fcf8feda4af`.
- Decision: preserve the current Git-index scanning, parsed YAML permission checks,
  least-privilege workflows, container smoke, and CodeQL foundation; repair scanner and gate
  gaps on the existing Platform branch.
- Consequence: the PR remains unmergeable until one new SHA has green CI and an independent
  review with no unresolved Blocker/Critical/High findings.

## Reserved decisions

The following are not delegated technical details and require Jacopo: paid hosting or
subscription activation, persistent Shopify app installation, credentials/login/2FA,
commercial or UX requirement changes, irreversible actions, and any live theme/cutover
publication.
