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

## Parameterized staging replacement

`scripts/activate_staging_refresh.py` is the host-side version of the supervised
replacement already exercised on staging. It reuses the existing activation CLI
and pinned runtime image; it does not add an HTTP activation API or hot reload.

```text
python scripts/activate_staging_refresh.py --plan /private/activation-plan.json
python scripts/activate_staging_refresh.py --plan /private/activation-plan.json --apply
```

The default is read-only preflight. Run as root on the Linux staging host, without
Python optimization, inside a bounded service and the coordinator's exclusive
whole-pipeline lock. This component does not acquire that lock itself and must not
be scheduled directly. A private root-owned mode-0600 plan supplies exactly:

- `capture`, `store`, `config`, `work`: canonical absolute host directories; `work`
  must not exist and its parent must be root-owned mode 0700.
- `run_id`, `current`, `expected_id`, `image`: a unique run suffix, current runtime
  name, exact container ID, and exact image SHA256 (not a mutable tag).
- `old_pin`, `old_code`: accepted pointer-byte hash and current producer commit.
- `manifest`, `summary`, `new_code`, `started`, `counts`: accepted capture evidence;
  counts contain `products`, `published`, `singles`, `variants`, not a fixed total.
- `shop`: the expected Shopify shop domain. Credentials remain in the existing
  private accepted environment, never in the plan or repository.

The capture service is `nla-refresh-<run_id>.service`; its successful termination,
capture receipt/checkpoint and the exited successful verifier container
`nla-refresh-<run_id>-runtime-verify` must agree. Candidate artifact hashes, file
permissions, current container, accepted environment and pointer are checked
before any writes. Existing run resources or destination packages stop the run.

Apply installs the immutable package, prepares a same-image runtime changing only
the activation and producer pins, compare-and-swaps the pointer, replaces the
stopped runtime, and waits up to 20 minutes for pinned-container HTTP readiness.
Only then is `accepted-runtime.env` replaced. Package and prior container remain
available for recovery; this script deletes nothing.

Before environment commit, an ordinary failure with a known pointer/runtime can
roll back through the existing CAS command. Recovery creates a fresh runtime with
the **actual rollback pointer hash**; restarting the old container with its stale
pin is not valid. Ambiguous selection, an externally changed pointer/container,
interruption, or failure after environment commit requires operator inspection,
not a blind retry. Work receipts and named containers remain for that inspection.

Focused offline tests exercise the real preflight against synthetic files and
simulated POSIX ownership, command construction, install/sealing, readiness,
rollback and ambiguous failures. They do not claim a new VPS deployment. The
coordinator, retention, freshness reporting and timer are still absent; this
component alone provides neither a 24-hour refresh guarantee nor new market cards.
