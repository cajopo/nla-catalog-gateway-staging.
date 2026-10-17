# Issue #13 operational health signal

Local implementation only. The existing catalog `/readyz`, Caddy backend health
checks, market 14:00 UTC job and refresh 15:00 UTC job are unchanged. Nothing in
this change installs a service, reloads Caddy, creates a monitor or sends email.

A root oneshot collector reads existing private receipts and selected systemd
properties. It checks root filesystem space and GET `/readyz` on the two fixed
loopback runtime ports, then atomically publishes only `checkedAt` and `healthy`
to `/run/nla-operational-health/status.json`. No pipeline locks, database opens,
Docker commands, source exports, credentials or Shopify requests are involved.
The HTTP service uses a dynamic unprivileged UID and Uvicorn (existing pinned
project dependency), listening only on `127.0.0.1:10002`. Only GET/HEAD `/opsz` without
a query returns `healthy` (200) or `attention` (503); other HTTP requests get a
fixed 404. Responses have `Cache-Control: no-store`. Access and exception logs
are disabled. It cannot select an input path from a request.

## Observation contract

- Collector every 30 seconds; missing, malformed, future or >=90 second old
  observation returns 503. Unknown reads or systemctl timeouts fail closed.
- Defaults are operational baselines, not an SLA: source age <24 hours and at
  least 6 GiB free on `/`. Both thresholds are explicit configurable collector
  arguments. Source age uses the verified receipt's `sourceStartedAt`, never
  activation time, job start or observation time.
- Backup coverage is mandatory: the collector requires an explicit backup root
  and checks `nla-backup-offsite.service`, its timer, `last-success.json` and the
  exact `receipts/<jobId>.json` selected by a strictly validated
  `backup-<32 lowercase hex>` identifier. Both bounded regular-file documents must
  agree. Schema 1, complete status, full snapshot/manifest SHA-256 identifiers,
  the expected checkpoint path, `integrityMode=read-data` and
  `integrityStatus=passed` are required. Native timezone-aware ISO/RFC3339
  timestamps must satisfy start <= checkpoint capture <= snapshot <= finish <=
  observation. Missing or malformed evidence fails closed.
- Backup freshness is measured from `checkpointCreatedAt`, never observation,
  finish or upload time. The configurable default is strictly less than 26 hours
  (daily 01:00 UTC schedule plus two hours for detection grace); this is an alert
  threshold, not an RPO guarantee. Running or queued jobs never extend this age.
  The latest successful receipt cannot hide a failed backup service.
  Evidence comparisons advance the supplied observation time by elapsed
  monotonic time after metadata/receipt/staging reads, so a normal start or
  completion during collection does not appear future-dated. The published
  `checkedAt` stays at collection start; this never extends its 90-second TTL.
- All three existing scheduler timers must be loaded, permanently enabled,
  successful and active (waiting/running). The sole pause exception is the
  enabled refresh timer being inactive/dead during an active/activating market
  service: the existing market template stops it in `ExecStartPre` and restarts
  it in `ExecStopPost`. An inactive or disabled timer otherwise needs attention.
- The backup `jobs` directory is inspected only until empty, one entry or two
  entries are established; receipt directories are never scanned. Idle/queued
  staging leftovers, unsafe entry names/types, multiple staging entries or a
  staged job with an existing terminal receipt need attention. A lone active job
  is allowed only with a directory modification time between the current
  service start and observation. This rejects older retained staging; filesystem
  timestamps are a limited temporal check, not proof of invocation identity.
  No staging is removed and no backup command or configuration file is opened.
- A healthy refresh receipt must match the active manifest and SHA-256 of the
  exact active pointer bytes. Three bounded coherent reads also consider a
  matching pending run's `completed.json` while `last-success.json` catches up.
  A pointer transition before the completed receipt exists is unknown/503, not
  proof that the job failed. External monitor debounce should tolerate this
  transition; no previous healthy observation is extended beyond its TTL.
- Active, activating and queued jobs are valid states, including a pending
  marker during an actual run. A refresh child launched by the market service
  also qualifies when both pending markers exist and their start times satisfy
  market <= refresh <= observation; failed/stopped states still take precedence.
  A retained marker with an inactive job, a failed unit, nonzero exit status,
  unknown unit state or stopped receipt needs attention.
  The systemd v255 `Job=` empty scalar means no queued job; `Job=123` means a
  queued job. Old success never hides the current systemd failure. Market partial
  outcomes need attention even though the existing file is named `last-market-success`.
- The reader accepts only bounded regular files: 128 KiB for small documents and
  8 MiB for the market success receipt. The market budget supports 50 batches x
  100 scalar attempt records (under 1 MiB), with eightfold headroom for batch and
  deferred metadata. Receipts exceeding the cap fail closed for operator
  inspection. Stopped receipt existence signals attention without parsing its
  potentially large payload. Linux nonblocking and no-follow open flags reject
  FIFO/symlink reads. systemctl uses two fixed metadata batches (three services,
  then three timers), fixed properties including `Id`, `UnitFileState` and
  `ExecMainStartTimestamp`, `--timestamp=unix`, a three second timeout per batch
  and no shell. Missing/duplicate/unexpected units or properties fail closed.
  Readiness uses one second per
  fixed loopback port. The collector has a 20 second systemd deadline.

Collector journal output contains only `OPERATIONAL_HEALTH:` plus one of:

| Code | Operator meaning |
| --- | --- |
| `healthy` | All checks passed in this observation. |
| `job_attention` | Failed, stopped, unknown or inactive pending refresh/market job. |
| `market_incomplete` | Latest market completion is partial or not a draft cycle completion. |
| `low_disk` | Root filesystem has less than the configured reserve. |
| `runtime_unavailable` | Neither loopback runtime returned readiness 200. |
| `source_stale_or_unverified` | Source old/future, receipt mismatch or pointer transition. |
| `backup_attention` | Failed backup service, unverified/stale checkpoint or retained/unsafe staging. |
| `scheduler_attention` | Required timer disabled, inactive, failed or unknown. |
| `observation_unknown` | Read, parse, subprocess or other observation error. |

Codes contain no paths, identifiers, receipt values or exception text. Inspect
existing private operator receipts under the established incident runbook to
identify a failing step. The generic HTTP endpoint deliberately carries no such
diagnostics. HEAD uses the same status and headers as GET with an empty body.
UptimeRobot defaults to HEAD and can retry GET, so both are supported explicitly.

## Review and future deployment gate

Render `.in` placeholders with reviewed canonical absolute paths to the pinned
observer package, its Python interpreter, refresh root, importer root, backup root and catalog
store. The HTTP package/interpreter must be installed outside the three blocked
private data directories and outside `/home`. Do not add Shopify, SMTP or other
credentials to either process. The observer package must not be the production
refresh package: refresh code remains pinned independently.

The collector owns its persistent runtime directory (0755) and status file (0644);
only root can replace them. The dynamic HTTP UID has no receipt privileges.
Verify the rendered units with systemd v255 on Linux before installation, including
DynamicUser, filesystem protections and loopback probes. Optional Caddy snippet
adds a separate exact GET/HEAD `/opsz` route and must never replace `/readyz` or be
imported into catalog upstream health checks. Review and validate the resulting
Caddyfile before any independently authorized reload. The current Caddyfile is
unchanged. A monitor must be explicitly pointed at `/opsz` to cover these checks;
existing `/readyz` monitoring still covers runtime availability only. The owner
coordinator verified on 2026-10-15 that the public staging `/readyz` returns
GET 200 and HEAD 404. Its existing UptimeRobot monitor must explicitly use GET
when activation/configuration is verified; provider HEAD defaults or GET retry
behavior are not evidence of a healthy monitor. This change leaves that route
untouched.

Rollback removes only the separately installed operational observer timer/service,
HTTP service and optional route; it does not change catalog pointers, jobs or data.
These templates have not been installed or validated against a live systemd host.

This signal does **not** measure customer-facing 5xx spikes, latency, rate limits,
CPU/memory metrics. It cannot establish
external DNS/TLS health without an external monitor. Those issue #13 requirements
and actual alert delivery/activation remain separate acceptance work. Do not close
issue #13 on the basis of this local change.

## Reproducible offline evidence

Run `pytest tests/test_operational_health.py` with coverage for
`nla_catalog_gateway.operational_health`, `scripts.observe_catalog_health` and
`scripts.serve_operational_health`. Tests use synthetic receipts and mocked
read-only systemd/HTTP observations, including future/stale source age, failed
units, pending/queued jobs, low disk, partial market completion, coherent pointer
reads, publication races, bounded inputs and HTTP/log leakage. They never contact
Shopify or a live runtime. Run the repository foundation commands before review.

## Official contracts consulted

- [Uvicorn deployment](https://uvicorn.dev/deployment/) and the existing
  `uvicorn>=0.52.4,<0.53` project constraint: programmatic ASGI instance, loopback
  host, single worker, systemd process supervision.
- [Caddy reverse_proxy](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy):
  literal loopback upstream, HTTP transport dial/response-header timeouts.
- systemd v255 official source:
  [service](https://raw.githubusercontent.com/systemd/systemd/v255/man/systemd.service.xml),
  [exec](https://raw.githubusercontent.com/systemd/systemd/v255/man/systemd.exec.xml),
  [systemctl](https://raw.githubusercontent.com/systemd/systemd/v255/man/systemctl.xml),
  [timer](https://raw.githubusercontent.com/systemd/systemd/v255/man/systemd.timer.xml),
  [resource controls](https://raw.githubusercontent.com/systemd/systemd/v255/man/systemd.resource-control.xml),
  [Job scalar printer](https://raw.githubusercontent.com/systemd/systemd/v255/src/systemctl/systemctl-show.c).
  The `show` command supports multiple units and selected scalar properties;
  `--timestamp=unix` is supported since v251. Timer enablement uses permanent
  `enabled` rather than transient `enabled-runtime`. The
  [systemd D-Bus contracts](https://raw.githubusercontent.com/systemd/systemd/v255/man/org.freedesktop.systemd1.xml)
  document timer results and unit/service properties.
  freedesktop HTML was unavailable; versioned upstream XML supplies the contract.
- Python 3.12 official documentation:
  [subprocess](https://docs.python.org/3.12/library/subprocess.html),
  [HTTPConnection](https://docs.python.org/3.12/library/http.client.html),
  [disk_usage](https://docs.python.org/3.12/library/shutil.html#shutil.disk_usage),
  [os](https://docs.python.org/3.12/library/os.html).
  [datetime](https://docs.python.org/3.12/library/datetime.html) supplies
  timezone-aware native backup/restic receipt parsing.
  [time.monotonic](https://docs.python.org/3.12/library/time.html#time.monotonic)
  supplies elapsed observation time independently of wall-clock adjustments.

The backup receipt format was inspected read-only in `scripts/backup_offsite.py`
at `b56ca95`: the immutable per-job receipt is published before `last-success`,
successful staging is removed before complete status, and failed staging is
retained. This observer does not import or execute that backup module. It relies
on the existing backup's recorded integrity result; it does not independently
verify remote availability or demonstrate a restore. The first scheduled run
and effective external alert delivery still require separate operational evidence.

- [UptimeRobot HTTP method behavior](https://help.uptimerobot.com/en/articles/11358466-how-to-debug-a-monitor-showing-as-down-in-uptimerobot):
  HEAD first and optional GET retry; supported only on the separate `/opsz` route.
