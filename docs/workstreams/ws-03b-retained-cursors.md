# WS-03B — retained runtime cursors (#69)

## Scope

Branch: `agent/retained-cursor-generations`, based on the single-build packaging
candidate `0621aedac0c64740f5c2fd87fcecc165e2c32e22` (#67).
Refs #3, #7, #17, #69. The user goal and master contract require complete navigation
while the catalog changes. This supersedes the original runtime behavior that
rejected every previous-generation cursor. It does not change search semantics,
Shopify data, PowerTools, the theme, hosting or production.

## Behavior

- The HTTP boundary forwards the parsed request and opaque cursor to the backend
  before acquiring its immutable generation lease. A request without a cursor
  selects the active generation; a cursor is HMAC/context/expiry-verified before
  selecting its original retained generation or reading product rows.
- A retained entry binds the verified generation, evidence and original cursor
  codec. Rotating the key or TTL with unchanged dataset content does not replace
  the old entry. Keys are not exposed in public responses or diagnostics.
- Open leases reserve their entry. The backend records the latest expiry actually
  issued by a lease, including a first-page request already in flight during
  activation. Subsequent pages preserve the original expiry; browsing does not
  renew the cursor indefinitely. Closing a lease is idempotent.
- Up to eight generation/codec bindings can be retained. When all slots are needed
  by open leases or valid cursors, activation fails without replacing the active
  generation or silently evicting a valid cursor. The caller must retry later.
- Expired, unleased entries are pruned on acquisition/activation. Only memory and
  key references are released: this code never removes package/database files.
- App Proxy authentication, shop isolation, evidence checks, immutable-file checks,
  deadlines, cancellation and public response validation remain in force.

## Operational limitations — not full #7 completion

Retention is **in-process only**. A newly started backend knows only its configured
active package. A cursor for another generation then fails explicitly, rather than
silently mixing results. Durable retained-generation discovery, retained-key loading
and restart/deployment continuity remain open; they are required before claiming
the full no-pagination-problems goal. Changing a replica/process without that state
can invalidate an existing traversal.

The current runtime holds full source-record tuples with each bound generation.
Eight slots bound the count, not production memory usage in bytes. Real-catalog
memory and update-frequency measurements are required before deployment. Retired
package disk cleanup is outside this patch and must respect cursor/rollback needs.
This is not a new synchronization transport or automated source acquisition path.

## Verification

The new `tests/test_cursor_retention.py` uses real signed HTTP requests and real
evidence/capability gates. Cases cover browse, name and SKU/collector-code searches,
sold-out inclusion, multiple activations with exact expected IDs, fresh requests,
in-flight cursor issuance, same-dataset key rotation, expiry, wrong context,
tampering, unknown generations, unavailable files, obsolete evidence, capacity,
idempotent close, acquisition timeout cleanup and the explicit restart limitation.

Local Python 3.13 verification:

- `pytest tests/test_cursor_retention.py tests/test_runtime_api.py
  tests/test_runtime_api_integration.py tests/test_runtime_suggestions.py
  --cov=nla_catalog_gateway.runtime_api --cov-report=term-missing
  -q -k 'not over_30000'`: 217 PASS, the large traversal selected separately.
  This first coverage run correctly failed its 100% gate because conditional
  activation is exercised in the sync-publication suite, not these four files.
- `pytest tests/test_sync_publication.py tests/test_staging_activation.py
  --cov=nla_catalog_gateway.runtime_api --cov-append --cov-report=term-missing -q`:
  39 PASS; combined changed-module coverage 100% (1,145 statements, 358 branches).
- `pytest tests/test_sync_publication.py tests/test_staging_activation.py
  tests/test_runtime_api_integration.py -q
  -k 'over_30000 or not test_runtime_api_integration'`: 40 PASS, including the
  complete signed HTTP traversal of 30,001 products. The other 39 repeat the above
  suite; there are 257 distinct passing cases across these commands.
- Ruff check and format check over all 58 Python files: PASS.
- `python -m build --no-isolation`: sdist and wheel PASS.
- `python scripts/preflight_repo.py`: 112 tracked files, zero failures.
- Independent reviewer `/root/search_v2_review`: APPROVE on the implementation/test
  diff, with no findings; final SHA binding is recorded in the delivery/PR receipt.

No real current-generation package, deployment or live E2E is claimed. These focused
results do not substitute for full exact-head CI.

## Security and rollback

This extends how long a valid old cursor key remains useful: until its last issued
cursor expires and its leases close. Emergency key revocation is not implemented
by ordinary rotation. Restarting without old history revokes that in-memory history
but interrupts those traversals; it is not a seamless rollback procedure.

Code rollback restores active-only selection and can cause `restart_required` for
old cursors. No Shopify state or catalog artifact must be reverted/deleted. Exact
head CI, independent review and the existing release gates still apply. Parent #66
CI cancellation and the separate #68 workflow-permission gate are not bypassed.
