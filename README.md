# NLA Catalog Gateway

Read-only catalog and search layer for the Next Level Arena Shopify storefront.
It provides deterministic, game-scoped search and keyset pagination for a catalog larger than the storefront deep-pagination window, while Shopify and TCG PowerTools remain authoritative for products, variants, inventory, cart, checkout, and orders.

## Baseline 2026-08-30

| Game | Active published products |
|---|---:|
| Magic: The Gathering | 122,531 |
| Pokémon | 71,605 |
| Yu-Gi-Oh! | 85,992 |
| One Piece | 11,663 |
| **Total** | **291,791** |

The gateway never writes to Shopify.

## API

- `GET /readyz`
- `GET /api/catalog/games`
- `GET /api/catalog/search?game=magic&q=Lightning%20Bolt`
- `GET /api/catalog/browse?game=magic`
- `GET /api/catalog/suggest?game=magic&q=lightning`
- `GET /api/catalog/facets?game=magic&q=bolt`

Production aliases are available under `/apps/nla-catalog/*` for Shopify App Proxy routing.

## Local development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
ruff check .
pytest
```

Build an index from a Shopify Bulk JSONL export:

```bash
python scripts/build_catalog.py snapshot.jsonl data/catalog.sqlite3 \
  --expected-count 291791 \
  --dataset-version 2026-08-30-shopify-bulk-9764612112652
```

Run:

```bash
CURSOR_SECRET='replace-me' DATABASE_PATH='data/catalog.sqlite3' \
uvicorn app.main:app --reload
```

## Staging bootstrap

Set `AUTO_BOOTSTRAP=true` and provide one of:

1. `SHOPIFY_BULK_URL`, a temporary signed Bulk result URL;
2. `SHOPIFY_SHOP` and `SHOPIFY_ADMIN_TOKEN`, to start a fresh read-only Bulk export;
3. a JSONL file already available at `SNAPSHOT_PATH`.

The API returns `503` from `/readyz` until the index passes count and SQLite integrity checks.

## Production security

Required:

```text
ENVIRONMENT=production
REQUIRE_APP_PROXY=true
SHOPIFY_APP_SECRET=...
ALLOWED_SHOP=the-shop.myshopify.com
CURSOR_SECRET=...
```

Do not place secrets in Liquid, JavaScript, Git, build logs, or SQLite.

## Theme

The additive unpublished-theme package is in `theme/`. Its API base defaults to `/apps/nla-catalog`; a direct staging endpoint is allowed only in the unpublished clone.
