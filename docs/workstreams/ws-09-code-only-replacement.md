# Code-only staging replacement (#13)

Delivery reconciliation 2026-10-03: recovered from `571794d`, with the handoff
description aligned to the warm helper in `7f421cf`/`83b14e45`. No production code,
installed operator, service or timer is changed by this documentation recovery.

`scripts/replace_staging_image.py` separates application replacement from dataset
promotion. It does not capture Shopify, repack data, change the pointer or accepted
environment, install config/units, restart timers, or delete resources. Source age
and the dataset producer SHA are not the application image revision.

Run from a reviewed, installed operator archive. The private plan has exactly:
`config` (absolute candidate refresh config path), `run_id` (normal refresh run
format), `expected_id` (current container ID), `old_image`, `new_image` (immutable
`sha256:` IDs), `activation_sha256`, `manifest_sha256`, `accepted_env_sha256`, and
`last_success_sha256`. The candidate config must pass the existing complete
installed-source/archive/reference validator and name the new image. Obtain all
pins from verified private evidence; never guess them.

Before preflight/apply, both `nla-catalog-refresh.service` and
`nla-market-catalog.service` must be idle, both corresponding timers stopped, and
both pipeline pending markers absent. The helper only checks these conditions;
it never stops a live job. It checks idle before acquiring the nonblocking lock
and again inside it. Do not run warmup holding this lock during a market cycle.
The dual-upstream edge prerequisite in [warm activation](ws-09f-warm-activation.md)
must already hold; this helper does not install or rewrite the edge configuration.

Use `python -m scripts.replace_staging_image --plan /absolute/private-plan.json`
for preflight; add `--apply` only after independent review and deployment authority.
Apply records durable intent before creating a candidate. The shared runtime
builder verifies pinned image, unchanged environment, mounts and host settings.
The candidate starts on the alternate validated loopback port (10000/10001), while
the original remains serving through candidate readiness and durable receipts.
Readiness uses the same dataset evidence binding. No dataset selector or fictional
promote is involved. After both receipts are published, retirement stops the old
runtime and checks edge readiness. A retirement failure requires inspection.

Success writes a new immutable `kind: image-upgrade` completion with resource
roles `runtime` and `replaced`, both owned by the same current manifest, then
atomically updates `last-success.json`. The original completion remains intact.
`sourceStartedAt` is preserved. **Success is not completed rollout:**
`installationComplete` is false and `pending-run.json` stays present. Keep timers
stopped. A separate reviewed installation must set coherent normal-refresh
operator/archive/config image and market refresh-package pins, verify current
runtime/readiness/freshness, and archive the pending marker under the same lock
before restarting timers. Do not rewrite the terminal image receipt to record
installation; retain a separate installation receipt. This helper supplies no
installer and must not be advertised as unattended deployment.

On ordinary pre-commit handoff/readiness failure, rollback first verifies the old
survivor's identity, image, private port and health before stopping the candidate.
It restores the original container name/policy with the same image/environment/ID;
original last-success still describes it. Failed candidate and rollback evidence
remain. Crash, uncertain Docker outcome, receipt publication failure, changed
pointer/environment, or interrupted rollback leave pending and require inspection,
not another `--apply`. Once receipt publication begins there is no automatic
rollback of a possibly committed runtime; both may still be serving on an ambiguous
publication failure. No retention runs here. Future retention understands both
legacy dataset receipts and strict image receipts; unknown resources/kinds or
conflicting ownership fail closed. Any separate verifier container mounting managed
data still requires valid recorded ownership or explicit reviewed disposal before
future retention.

Official contracts: [Docker create](https://docs.docker.com/reference/cli/docker/container/create/),
[inspect](https://docs.docker.com/reference/cli/docker/container/inspect/),
[start](https://docs.docker.com/reference/cli/docker/container/start/),
[stop](https://docs.docker.com/reference/cli/docker/container/stop/),
[rename](https://docs.docker.com/reference/cli/docker/container/rename/), and
[systemctl upstream manual](https://github.com/systemd/systemd/blob/main/man/systemctl.xml)
(`show` machine-readable unit properties; rendered upstream manual was unavailable).
