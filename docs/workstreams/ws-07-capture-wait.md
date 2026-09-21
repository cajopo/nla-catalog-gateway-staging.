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
