# Draft publication evidence — issue #11

2026-09-26: refresh invocation 7a1ac08e8ac04759b7ea8bb2a8d62013
downloaded both Shopify exports, then failed with `missing Online Store publication
evidence`. Read-only local reproduction confirmed the exact error. Both newly
created DRAFT pilots had no ResourcePublicationV2 rows; publishedAt/onlineStoreUrl
were null. Source counts before/after matched: 291797 products, 293868 variants.
All downloaded evidence is retained outside Git; no repeat acquisition is needed.

Shopify 2026-07 documentation says DRAFT products are unavailable on sales channels;
ResourcePublicationV2 represents published or scheduled publication, not every
possible unpublished channel. The old requirement for an edge on every product
was invalid for never-published drafts.

The fix exempts only DRAFT from the missing-edge error and uses LEFT JOIN with
false for absent publication. It retains every draft and variant without exposing
them. Non-DRAFT missing evidence remains an error; actual publication rows/counts
are neither fabricated nor changed. No Shopify writes or query changes.

Evidence: 114 reconciliation tests PASS (4.40s), Ruff PASS. Two new cases exercise
absent publication and only another-channel publication. Existing ACTIVE rejection
remains covered. Independent static review: no blocker. Native retained-source
reconciliation and activation are still pending; no completion/CI/merge claim.

Official documentation consulted before implementation:
- https://shopify.dev/docs/api/admin-graphql/latest/enums/ProductStatus
- https://shopify.dev/docs/api/admin-graphql/latest/objects/ResourcePublicationV2
