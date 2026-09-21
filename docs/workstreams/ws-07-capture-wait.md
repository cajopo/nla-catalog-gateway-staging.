# WS-07 / issue #11: bounded capture polling

The existing `scripts.capture_shopify_bulk` command now accepts optional
`--wait-seconds 7200 --poll-seconds 60`. Without those options its existing
single-step behavior is preserved.

This replaces ad-hoc polling wrappers, not the reconciler or package validator.
All steps retain the same capture directory, client, pinned reference and source
configuration. Only a successful `pending` result is retried. Errors, uncertain
export launches and invalid reference coverage stop immediately. Recovery IDs are
used only on the first step; subsequent steps use the durable checkpoint.

Exit codes remain 0 for a verified candidate, 3 for pending (including an expired
polling budget), and 1 for failure. Resuming a pending run requires the same private
capture directory. Never respond to exit 1 by blindly creating another directory.
The polling budget does not interrupt a running download/reconciliation/package;
an external service must impose the overall timeout and memory limit.

This is NOT an installed periodic refresh or automatic publication. An actual
scheduled workflow still needs activation/rollback integration, bounded disk
retention and freshness reporting. A 24-hour interval alone would not satisfy a
24-hour visibility limit because export, validation and activation take time.
New source IDs still require verified canonical-name reference coverage; no title
guessing or silent omission is introduced. No Shopify product, PowerTools or theme
writes are added, and no active dataset changes are performed by this command.

## Reusable runtime compatibility check

`scripts/verify_staging_runtime.py` replaces the dated, embedded verification
snippet used during supervised refreshes. It is included in the runtime image so
the check uses the same installed reader and runtime backend as deployment:

```text
python /app/scripts/verify_staging_runtime.py \
  --candidate-directory /candidate \
  --manifest-sha256 <accepted-capture-manifest-sha256> \
  --summary-sha256 <capture-checkpoint-summary-sha256> \
  --code-sha <capture-producer-code-sha> \
  --record-count <independently-reconciled-product-count>
```

Run it in the pinned deployment image, network disabled, candidate mounted read
only, non-root, with the existing memory/CPU and supervisor time limits. The
caller supplies pins and count from the accepted capture checkpoint/receipt;
reading expected values out of the candidate itself would not establish this
capture-to-candidate binding. The caller must still verify capture completion.

Exit0 emits one JSON receipt only after the package reader and runtime backend
both accept the artifact. Exit1 emits a fixed error without paths, arguments or
exception contents. Counts and per-game totals come from verified records, with
unclassified records counted explicitly; no date, store or catalog size is baked
into the command. It does not re-run the full catalog proof, activate anything,
validate App Proxy credentials, or certify HTTP readiness/freshness. Interrupted
container checks require inspection before retry. The deployed image is unchanged
until a separately tested deployment; this change alone installs no scheduler.

Focused verification: `pytest tests/test_verify_staging_runtime.py
--cov=scripts.verify_staging_runtime --cov-report=term-missing` covers a real
package/runtime binding, read-only file hashes, wrong pins/counts, CLI errors and
interruption without a success receipt.
