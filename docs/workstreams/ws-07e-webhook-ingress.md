# WS-07E — Authenticated durable webhook ingress (#81 / #11 / #12)

## Scope and integration

`agent/webhook-ingress` starts from `9a53937`, the reviewed #80 durable inbox.
The existing ASGI server gets one opt-in POST route. No service, dependency,
catalog representation or queue infrastructure is added. With neither new setting
present the route is disabled and no inbox is opened.

Host configuration (never put secret values in Git):

- `NLA_WEBHOOK_PATH`: an explicit absolute URL path, distinct from the health
  probes and the configured App Proxy backend route. Queries are rejected.
- `NLA_WEBHOOK_INBOX_PATH`: absolute SQLite path in a private operator-owned
  directory outside the source repository and immutable catalog store. Both
  settings are required together. The directory must already exist.
- Existing `NLA_SHOP_DOMAIN` selects the one accepted shop. Existing
  `NLA_APP_PROXY_SHARED_SECRET_B64` supplies the same Shopify app client secret;
  webhook signing does not use the App Proxy query-signature algorithm.

Authentication verifies canonical base64 HMAC-SHA256 against the exact received
body bytes using constant-time comparison. Required signature/shop/delivery-ID/
topic/API-version/content-type headers and optional content-length must be unique.
Encoded bodies, mismatched lengths and unexpected shops fail closed. Metadata has
existing ASGI header bounds; webhook bodies have the existing envelope limit of
16 MiB and at most1,024 chunks. Catalog requests retain their64 KiB limit and
independent App Proxy authentication.

The receiver authenticates before passing a raw envelope to `DurableWebhookInbox`.
HTTP200 follows a committed new receipt, duplicate or retained conflict. It means
**received**, never applied/published. Conflicts remain queued for reconciliation.
Invalid authentication writes nothing; storage/capacity failures return503.
Public errors contain no request, path, database or secret details.

## Deadlines, trust and operational boundaries

The ASGI path budgets four seconds from entry through body receipt and synchronous
storage work. The existing configured body timeout can be shorter. A timeout gives
503; disconnect gives no response. An already running worker thread can still
commit after timeout/disconnect, so a retry must deduplicate. Thread cancellation
is not transaction rollback. No200 is sent for an uncommitted receipt.
This bound does not establish external connection/TLS/proxy latency or slow response
transport; actual hosted Shopify delivery must meet Shopify's five-second window.

Shopify signs the body, not each metadata header independently. The future worker
must re-fetch authoritative records under the configured shop and reconcile gaps;
metadata/payload is not authority to mutate Shopify commercial data. JSON parsing
and application semantics remain in that worker, not in the receipt route.

The private SQLite file/journal contains event data and must not be committed,
served or included in immutable catalog packages. Host-directory ownership and
permissions are deployment prerequisites. Capacity includes retained dedupe
history; no silent eviction is introduced. Disk/queue/freshness monitoring,
retention, rate/load sizing and secret rotation remain operational work.

No subscription registration, Shopify/PowerTools/MAIN/clone/provider mutation,
paid service, deployment or catalog activation occurs in this workstream.
The publication worker, source metadata refresh, restart-safe catalog retention,
actual App Proxy/clone integration and E2E remain open; #11 is not complete.

## Reproducible evidence

Commands use the project virtual environment from this branch/worktree:

```text
python -m pytest tests/test_webhook_ingress.py tests/test_runtime_server.py tests/test_runtime_bootstrap.py tests/test_durable_inbox.py -q --cov=nla_catalog_gateway.webhook_ingress --cov=nla_catalog_gateway.runtime_server --cov=nla_catalog_gateway.runtime_bootstrap --cov=nla_catalog_gateway.durable_inbox --cov-report=term-missing -p no:cacheprovider
python -m ruff check .
python -m ruff format --check .
python scripts/preflight_repo.py
python -m build --no-isolation
git diff --check
```

The final focused run:226 PASS /21.56s,100% changed-module line/branch coverage
(670 statements/204 branches), including both interrupted-body cases. Repository
Ruff check/format and preflight118 PASS. Tests cover signed ASGI-to-SQLite/reopen,
duplicates/conflicts, invalid signatures/metadata, unknown topics, capacity and
storage errors, cancellation/deadline and eventual commit, bootstrap fail-closed
configuration and unchanged catalog authorization/limits. Fixtures are synthetic.

Initial test failures were corrected without weakening application gates: an
existing asyncio.wait mock needed the new optional timeout argument; a test using
an unbound catalog service incorrectly expected401 instead of fail-closed503.
The actual evidence-bound bootstrap separately proves unsigned catalog401 even
with a valid webhook signature. An unused test import and line endings were fixed.
Independent review and exact-head full CI must accompany the PR before merge.
No accepted heavy real-catalog proof was repeated.

Official delivery contract checked2026-09-16:
[Shopify HTTPS delivery verification](https://shopify.dev/docs/apps/build/webhooks/verify-deliveries).
The Shopify skill search failed (`fetch failed`); the official page was read via
web fallback. Delivery dedupe uses `X-Shopify-Webhook-Id`, not event correlation ID.
