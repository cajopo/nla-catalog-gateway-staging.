# Market source interruption — 2026-10-15 (#97)

The October 14 14:00 UTC market cycle stopped during the read-only CardTrader
capture: 2,323 of 2,438 expansion exports completed; the next export was expansion
4688 (game 5). The saved error was `CardTraderCatalogError` with no HTTP status.
The old receipt discarded the fixed exception reason, so a timeout, connection
failure or invalid response cannot be distinguished retrospectively. One GET of
that expansion on October 15 succeeded.

The retained pending marker correctly blocked the October 15 02:00 UTC market
invocation. The failed run contained only `source/` and `stopped.json`, with no
attempts or batches. A read-only ledger check found 4,458 verified drafts and
4,458 published products, no uncertain states, no operations since the failed
cycle started, and SQLite `quick_check` returned `ok`.

The independent catalog refresh succeeded, activating at October 15 04:38:51 UTC.
At inspection both timers were waiting and the VPS had 10,713,243,648 bytes free.
An active refresh must never be stopped to repair the market service.

## Correction and safe recovery

Capture now retries GET requests at most three times for transport failures or
HTTP 408, 429, 500, 502, 503 and 504. Bounded backoff and existing pacing remain
inside the three-hour capture deadline. Authentication, malformed data and size
errors remain fatal; explicit handling of unavailable HTTP 404 exports is
unchanged. A failed capture remains unusable. Progress records allowlisted error
codes, endpoint identifiers and attempt counts, without credentials, response
bodies, URLs or arbitrary exception messages. Shopify behavior is unchanged.

Recovery is a separately reviewed operator action, never blind automatic removal
of the pending marker. The private incident helper requires both pipeline locks
without waiting, idle services, no pending refresh, exact original receipt/code/
unit/configuration hashes, no later-stage directories and an unchanged terminal
ledger. A mismatch requires renewed inspection.

The helper backs up and atomically replaces only the importer capture module,
records its Git source commit and before/after hashes, then archives the pending
marker inside the failed run. An `inspection-resolved.json` receipt binds
`stopped_inspected`, zero uncertain attempts and the stopped receipt hash. Existing
retention preserves that inspected run. The failed capture is never promoted to
success. Resetting the market failed indicator does not start a cycle, refresh or
export, or change either timer.

The capture-only hotfix has its own maintenance receipt; the existing generator
SHA identifies unchanged reference-generation code, not the patched capture file.
Rollback restores the saved module atomically under the same locks/idle checks.
An interrupted apply refuses automatic retry: inspect the saved plan, installed
module hash, inspection receipt and marker location to establish the last durable
step; then complete or roll back under a fresh review and the same idle guards.
Never restore an old pending marker after another market cycle has begun without
first inspecting the new state. A successful recovery/readiness check does not
establish successful completion of a subsequent full market cycle.

Private evidence stays outside Git under
`output/nla-recovery/20260930/evidence/market-failure-20261015/`:
`diagnose_receipts_remote.result.json`, `source_failure_remote.result.json`,
`probe_source_remote.result.json`, and `ledger_probe_remote.result.json`.
The deployment receipt, independent review and full validation results belong in
the pull request delivery record when available; no deployment is claimed here.

## Official contracts consulted

- [CardTrader API](https://www.cardtrader.com/it-IT/docs/api/full/reference):
  HTTPS GET endpoints, Bearer authentication and rate limits. The bounded retry
  policy is local; the API does not guarantee recovery.
- Python 3.12 [urllib](https://docs.python.org/3.12/library/urllib.request.html),
  [fcntl](https://docs.python.org/3.12/library/fcntl.html) and
  [atomic replacement](https://docs.python.org/3.12/library/os.html#os.replace).
- [systemctl v255](https://github.com/systemd/systemd/blob/v255/man/systemctl.xml):
  state inspection and `reset-failed`, separate from service start/restart.
