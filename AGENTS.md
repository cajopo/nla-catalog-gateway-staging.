# AGENTS.md — Next Level Arena catalog gateway

## Mission
Build a read-only catalog projection for the Next Level Arena Shopify storefront. Shopify remains authoritative for products, variants, prices, inventory, product pages, cart, checkout and orders. TCG PowerTools continues to write to Shopify as it does today.

A separate missing-printing importer supports new market releases under the
owner-approved create-only exception below; the gateway itself stays read-only.

## Read before changing code
1. GitHub issue #3 — master roadmap.
2. GitHub issue #17 — approved gateway architecture.
3. GitHub issue #19 — `single`, `sealed`, `accessory`, `unclassified` taxonomy.
4. The issue assigned to the current workstream.

## Non-negotiable boundaries
- Read relevant official public documentation before proposing or implementing integrations; explicitly reconcile discrepancies with observed API behavior.
- Gateway and Shopify-to-index refresh remain read-only. Owner exception confirmed 2026-09-25: a separate importer may create verified missing card-printing products, initially DRAFT/unpublished/zero-stock, including only necessary initial variants, metadata and verified identities. Never modify or delete pre-existing products or their data. Do not invent prices or language/condition/finish. Missing or ambiguous IDs require reporting, not guessing. Check current Shopify data before creation and prevent duplicate retries.
- Owner publication decision (2026-09-28): automatic Online Store publication of verified importer-created cards as SOLD OUT, zero stock and non-purchasable is authorized. A separate step may activate and publish only ledger-proven new products after fresh identity/media/inventory checks. Do not rewrite commercial data or republish after handoff to PowerTools. MAIN, PowerTools configuration and pre-existing-product corrective edits remain out of scope. See issue #97 and the current owner conversation.
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
