# AGENTS.md — Next Level Arena catalog gateway

## Mission
Build a read-only catalog projection for the Next Level Arena Shopify storefront. Shopify remains authoritative for products, variants, prices, inventory, product pages, cart, checkout and orders. TCG PowerTools continues to write to Shopify as it does today.

The owner confirmed on 2026-09-25 that the operational system must also support new
market releases. A separate, narrowly scoped missing-product importer is authorized
as described below; this does not turn the gateway into a general Shopify writer.

## Read before changing code
1. GitHub issue #3 — master roadmap.
2. GitHub issue #17 — approved gateway architecture.
3. GitHub issue #19 — `single`, `sealed`, `accessory`, `unclassified` taxonomy.
4. The issue assigned to the current workstream.

## Non-negotiable boundaries
### Documentation first — standing owner instruction
- Before proposing or performing work involving an API, service, or tool, consult its relevant official public documentation when available. This applies to all agents, not only CardTrader work.
- Verify the applicable version, endpoints, authentication, request/response formats, and constraints before implementation or asking the owner to execute instructions. Do not substitute remembered behavior or guesses for available documentation.
- If documentation is unavailable or disagrees with observed behavior, explicitly report the gap and use a minimal read-only diagnostic to establish the actual contract before changing integration behavior.

### System boundaries
- The gateway and its Shopify-to-index refresh remain read-only: they never mutate Shopify products, variants, prices, inventory, tags, metafields or publication state.
- Owner-approved exception (2026-09-25; extended 2026-10-29): a separate importer may create verified missing card-printing and sealed products, initially DRAFT, unpublished and at zero stock, including only the new product's necessary initial variants, metadata and verified source identifiers. Sealed products are normal SKUs and follow the same identity and safety checks as cards. It must not update, merge, delete or overwrite pre-existing products or their variants, prices, inventory, tags, metafields or publication state.
- Import by verified identifiers, never by title alone. Check against current Shopify data before creation, prevent duplicate creation on retries, and report missing/ambiguous mappings rather than guessing. Do not fabricate selling prices or language/condition/finish data. Preserve traceable CardTrader and verified PowerTools/Cardmarket identities.
- Owner publication decision (2026-09-28; extended 2026-10-29): after an explicit question, the owner authorized automatic Online Store publication of verified importer-created cards and sealed products as SOLD OUT, zero stock and non-purchasable. A separate publication step may activate and publish only products proven owned by the importer ledger, after fresh identity, media and inventory checks. Never rewrite commercial data or republish products after handoff to PowerTools. This does not authorize MAIN theme changes, PowerTools configuration changes or bulk corrective edits to pre-existing products.
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
