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
  FIFO/symlink reads. systemctl uses fixed properties,
  a three second subprocess timeout and no shell; readiness uses one second per
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
| `observation_unknown` | Read, parse, subprocess or other observation error. |

Codes contain no paths, identifiers, receipt values or exception text. Inspect
existing private operator receipts under the established incident runbook to
identify a failing step. The generic HTTP endpoint deliberately carries no such
diagnostics. HEAD uses the same status and headers as GET with an empty body.
UptimeRobot defaults to HEAD and can retry GET, so both are supported explicitly.

## Review and future deployment gate

Render `.in` placeholders with reviewed canonical absolute paths to the pinned
observer package, its Python interpreter, refresh root, importer root and catalog
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
CPU/memory metrics, or prove that a scheduled timer is enabled. It cannot establish
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
  freedesktop HTML was unavailable; versioned upstream XML supplies the contract.
- Python 3.12 official documentation:
  [subprocess](https://docs.python.org/3.12/library/subprocess.html),
  [HTTPConnection](https://docs.python.org/3.12/library/http.client.html),
  [disk_usage](https://docs.python.org/3.12/library/shutil.html#shutil.disk_usage),
  [os](https://docs.python.org/3.12/library/os.html).

- [UptimeRobot HTTP method behavior](https://help.uptimerobot.com/en/articles/11358466-how-to-debug-a-monitor-showing-as-down-in-uptimerobot):
  HEAD first and optional GET retry; supported only on the separate `/opsz` route.
