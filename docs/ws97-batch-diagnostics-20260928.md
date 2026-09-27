# Import-batch diagnostics and bounded recovery — issue #97

## Verified cause and fix

LIVE VALIDATION PASSED: session7672 exited0, batch_complete,100/100 new
draft_verified results, no additional publications. Reused the same source and
identity export; no new acquisition. This proves the bounded batch fix, not yet
a complete automatic market cycle. All prior failure receipts remain retained.
Post-run permanent ledger306 rows, all draft_verified, zero uncertain outcomes.

Additional recovery fix: retention accepts only explicitly inspected stopped
cycles (matching run/state, integer uncertainAttempts=0 and pinned stopped SHA256).
It retains their entire contents and rollback references; it still protects the
latest two COMPLETED cycles independently. An unresolved stop still blocks.
The inspection receipt is operator-written, never automatic; it does not claim
the stopped cycle completed. Targeted tests and independent review cover this.
Retention+coordinator42 tests passed; final retention-only26 passed after adding
latest-inspected-run cases. Ruff/check-format and diff checks passed. Independent
reviewer approved after preserving the last two completed runs separately.

The bounded recovery reproduced the stop after 51 verified creations:
inconsistent_identity_page, next Cardmarket ID901089. Ledger total206, all verified.
SSH session7837 TERMINAL exit1; no uncertain create outcome. Receipt retained at
recovery-20260928-2246/batch/result.json. No source or identity reacquisition followed.

Fix in capture_import_identities.missing_guard: at most three complete READ
attempts for that exact pagination-inconsistency error, starting from page one,
with2second pauses. Immutable-file and freshness checks run before every attempt
and after success. No partial pages accepted; all other errors fail immediately;
no Shopify mutation is retried.57 capture/identity tests PASS, Ruff PASS; independent
reviewer product_presentation_review approved this additional delta.
Installed package importer-b9733cd-retry-20260928; capture script SHA256
edcaf82eb9e19ce97cda305bc6b1e131fa0a88bade01c407dbd3eb08e266c098 verified.
Live validation uses SAME <30min identity snapshot and <24h source, permanent
ledger, max100, new batch-retry-fix directory. SSH session7672 active at launch;
poll it, do not duplicate. Service unit still unchanged pending actual result.

## Diagnostic change

The Sep27 market cycle stopped after 53 verified creations, before the next
reservation. All 155 existing ledger entries were draft_verified. Its error
handler discarded the exception, making the actual cause unrecoverable.

Evidence ruled out the 30-minute identity expiry (only 276 seconds elapsed),
source expiry and malformed inputs for the next three candidates. A read-only
reproduction of the unchanged recent-identity query traversed 58 products in two
pages successfully; current throttling had 1977/1994 of 2000 points available.
This does NOT prove the original failure was a timeout, pagination drift or throttle.

Change: retain only explicitly allowlisted local reason codes and the current
Cardmarket ID in the failed batch receipt; copy that diagnostic into the stopped
cycle receipt. Unknown text is discarded. No retries, mutations, freshness limits,
ledger checks or publication permissions are changed. Reset the candidate ID each
iteration, including malformed preparation paths, to avoid blaming the prior item.

Verification: 67 targeted importer/coordinator/identity tests passed; after the
reviewer's attribution fix, all 21 importer tests passed (including two new cases).
Ruff and diff checks passed. Independent review /root/product_presentation_review
approved after the attribution correction. No full suite or GitHub CI was rerun.

Installed isolated diagnostic copy: /opt/nla-staging/importer-b9733cd-diag-20260928.
Original service package and units are unchanged. Installed hashes match local:
- import_cardtrader_drafts.py: 69765e4083da8c27c0d4d26eeda707b4dc504ff682d90a8a37f0a45c70fe10f1
- refresh_market_catalog.py: ac59431d754d12143709b62b107aa784ec53208c6f88c77525fd5fbaf1195752

Recovery uses the existing CardTrader source from market-20260927t020013z-a3556800
while still younger than 24h, the SAME permanent draft-attempts.sqlite3 ledger,
and a fresh identity-only check under recovery-20260928-2246. Its saved Bulk
operation is 12541737009420; poll that operation, never create a replacement on timeout.
The old pending-market marker is preserved until the failure is reconciled.
No CardTrader reacquisition or extra Online Store publication is authorized by this.

Official reference consulted:
https://shopify.dev/docs/api/admin-graphql/2026-07/queries/products
