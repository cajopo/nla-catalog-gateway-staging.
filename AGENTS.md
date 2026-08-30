# AGENTS.md — Next Level Arena catalog gateway

## Mission
Build a read-only catalog projection for the Next Level Arena Shopify storefront. Shopify remains authoritative for products, variants, prices, inventory, product pages, cart, checkout and orders. TCG PowerTools continues to write to Shopify as it does today.

## Read before changing code
1. GitHub issue #3 — master roadmap.
2. GitHub issue #17 — approved gateway architecture.
3. GitHub issue #19 — `single`, `sealed`, `accessory`, `unclassified` taxonomy.
4. The issue assigned to the current workstream.

## Non-negotiable boundaries
- Never mutate Shopify products, variants, prices, inventory, tags, metafields or publication state.
- Never change or disconnect TCG PowerTools.
- Never modify the Shopify MAIN theme. Theme work is restricted to the unpublished clone and its own workstream.
- Never commit Shopify snapshots, SQLite databases, generated catalog artifacts, credentials or signed Bulk URLs.
- Never use a title alone as product identity; preserve Shopify GID and verified PowerTools/sync IDs.
- Never silently drop an unclassified product. Account for every included baseline record.
- Never claim completion without tests and reproducible evidence.

## Delivery model
- One issue, one `agent/*` branch, one reviewable pull request.
- Keep platform, data, pagination, search, filters, sync, security, deploy, theme and QA changes separated.
- Authors do not approve their own work. Request an independent review.
- Do not merge red CI, skipped tests or unresolved Blocker/Critical/High findings.
- Live publication is reserved to Jacopo under the cutover gate.

## Foundation commands
```bash
python -m pip install -e '.[dev]'
ruff check .
ruff format --check .
pytest --cov=nla_catalog_gateway --cov-report=term-missing
python scripts/preflight_repo.py
python -m build
```

## Evidence in pull requests
Record the issue, branch, commit SHA, commands executed, test results, dataset version when applicable, security/rollback implications and any unresolved decision. A written plan without executable evidence is not progress.
