# WS-07D — Durable webhook receipt and replay (#79 / #11)

## Scope

`agent/durable-webhook-inbox` starts from `9594d79`, the reviewed #78 integration.
One SQLite adapter reuses `RawWebhookEnvelope`; no additional service, dependency,
catalog representation or replacement search engine is introduced.

`receive()` commits the first envelope before returning a receipt. A store belongs
to one configured shop; its unique webhook ID is therefore the `(shop, webhook ID)`
delivery identity. Exact retries keep the original bytes/time/revision. A different
payload hash, topic or API version increments the revision and durably requires
reconciliation. A conflict after completion reopens the delivery. Unknown topics
also require reconciliation. Conflicting payloads never overwrite the original.

`pending(limit=...)` returns at most100 ordered envelopes without claiming/deleting
them. `complete()` records a caller-supplied published generation and checks the
delivery revision, immutable identity and persisted reconciliation requirement.
An old worker cannot acknowledge a newer conflict, even if its cached flag is false.

Each operation opens/closes its own SQLite connection. Transactions use
`BEGIN IMMEDIATE`, synchronous FULL and SQLite rollback journaling. Concurrent
receipts are serialized; interruption before commit cannot acknowledge delivery.
Receipts not completed after durable publication replay after a process restart.
This is at-least-once replay: publication must be idempotent, including a crash
between publication and completion. No exactly-once cross-store transaction exists.

## Operational and security boundaries

- This adapter is NOT an authorizer. Authenticate Shopify HMAC over the original
  body before calling it; no HTTP route or webhook registration is added here.
- The caller must verify durable publication/reconciliation before `complete()`;
  the method records that decision, it cannot prove the catalog is active.
- Use a private, operator-owned directory outside Git for the database/journal.
  It contains raw catalog events. Do not log them, ship them with code, or expose
  arbitrary file paths to clients. No defense against an attacker controlling the
  host directory is claimed; incorrect shop/format and invalid replay data fail closed.
- Queue limits bound retained envelope bytes/count, not physical filesystem usage.
  Completed dedupe history is retained and counts toward capacity. At capacity new
  receipts fail, never evict silently; existing retries/conflicts remain recordable.
  History retention/compaction, disk/lag monitoring and production sizing remain open.
- Busy storage has a one-second SQLite wait, not an end-to-end HTTP deadline claim.
- No Shopify/PowerTools/theme/provider changes, live ingress or catalog activation.

## Evidence

Focused tests cover reopen/replay, duplicate/conflict, unknown topics, concurrent
delivery, completion revision checks, row/byte capacity, foreign/corrupt storage,
commit failure with rollback, and a real child-process abrupt exit with a committed
receipt and uncommitted completion. Commands (project virtual environment):

```text
python -m ruff check src/nla_catalog_gateway/durable_inbox.py tests/test_durable_inbox.py
python -m ruff format --check src/nla_catalog_gateway/durable_inbox.py tests/test_durable_inbox.py
python -m pytest tests/test_durable_inbox.py -q --cov=nla_catalog_gateway.durable_inbox --cov-report=term-missing -p no:cacheprovider
```

Local focused result2026-09-16: 50 tests PASS in2.13s, 100% new-module line/branch
coverage (110 statements/32 branches), no skips or warnings. Ruff check/format PASS.
All152 existing sync-core tests also PASS in3.03s; repository-wide Ruff check and
format PASS (95 Python files). No existing production module or workflow changed.
The initial 47-test run passed functional assertions but failed the100% coverage
gate at98.59%; three corrupt-state cases closed that gap. Test-only SQLite connection
lifetime warnings and a lint finding were fixed before the accepted run.
Independent review and exact-head CI must accompany the PR before merge.
This slice does not close #11: authenticated ingress, publication worker,
continuous source metadata, restart-safe catalog generations, freshness/monitoring
and actual Shopify delivery/clone E2E are still required.

Official source checked2026-09-16:
[Shopify delivery verification and retries](https://shopify.dev/docs/apps/build/webhooks/verify-deliveries).
The Shopify skill documentation search failed (`fetch failed`); the official page
was read through the web fallback. It confirms persistent delivery-ID dedupe and
quick receipt with queued processing; no live webhook request was sent.
