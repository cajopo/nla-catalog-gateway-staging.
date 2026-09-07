# WS-09B — Staging projection handoff and deployment

## Current status

This issue #13 candidate is local only. It has not created a Render service, attached a paid
disk, provisioned a secret, changed Shopify, changed either theme, or exposed a public URL.
Those facts must remain explicit: a green local package is not evidence of a deployed staging
environment.

Render remains only a conditional candidate for a single-instance staging service in the
Frankfurt region. Its current web-service contract supports Docker, a configurable HTTP health
path, TLS, and an absolute persistent-disk mount. An attached disk restricts the service to one
instance and only files below its mount survive restart or deploy. Those limitations are
acceptable for staging, not silently accepted for a future production topology.

Render Professional and higher workspaces are currently prohibited for this App Proxy endpoint.
Render documents automatic public HTTP request logs on those plans and describes a requested-URL
field, but does not document that signed query strings are omitted or that dashboard request logs
can be disabled. A deployment may proceed only after a synthetic (never Shopify) signed-query
canary proves that the provider stores no query string, or Render confirms that guarantee in
writing. Failure or absence of that evidence selects a different EU host and forbids a public
staging URL. Disabling Uvicorn access logs does not satisfy this provider-level gate.

Official references checked on 2026-09-06:

- <https://render.com/docs/web-services>
- <https://render.com/docs/health-checks>
- <https://render.com/docs/disks>
- <https://render.com/docs/blueprint-spec>
- <https://render.com/docs/logging>
- <https://render.com/docs/platform-features-by-plan>

## Release/data separation

Application releases never contain a Shopify snapshot or generated catalog database. The
Windows authorized runner remains the only producer allowed to open the reconciled #47 bundle.
`scripts/package_staging_generation.py` performs the real-core proof implemented by commit
`cd24939`. On 2026-09-07 its protected execution against the current canonical generation
completed with `VALUE_FREE_RESULT: ACCEPTED`: it proved 291,795 Products and 293,866 Variants,
rebuilt the same deterministic SQLite projection, matched the projection fingerprint, published
the immutable external package atomically, and reopened the installed package. No generation was
activated. The code PR/merge, transfer to the designated operator runner, and a reopen from that
separate runner remain pending.

The Linux service consumes only these three externally transferred files:

- `catalog-projection.v1.sqlite3`;
- `catalog-core-evidence.v1.json`;
- `staging-generation-manifest.v1.json`.

The manifest contains only fixed filenames, byte counts, and SHA-256 digests. Its SHA-256 is a
separate deployment trust root. The consumer rejects extra files, symlinks, hard-link aliases,
writable artifacts, noncanonical JSON, digest mismatches, changed file identity, an invalid
SQLite projection, or any mismatch in shop, reconciliation summary, dataset generation, catalog
content, projection fingerprint, or verifier code SHA.

No generated package, manifest digest, real report, path, credential, or signed URL belongs in
Git.

## HTTP boundary

The ASGI adapter exposes exactly:

- `GET /livez` for process liveness;
- `GET /readyz` for evidence-bound readiness;
- `POST` on the one configured App Proxy backend path.

It does not expose a direct catalog twin. Raw query, headers, and body chunks are forwarded
without reconstruction. Input is bounded before accumulation, disconnect cancels the shared
request control, and malformed service output becomes a fixed value-free error.

The container starts the reviewed ASGI factory with:

```text
python -m nla_catalog_gateway.runtime_bootstrap
```

That launcher fixes the bind host, uses Render's bounded `PORT`, runs one worker, disables proxy
header trust, suppresses Uvicorn's request-target access log, and removes its server header. The
access log must not be re-enabled: an App Proxy target contains the signed query string.

The host, never the image or Git, supplies these required values:

- `NLA_SHOP_DOMAIN`;
- `NLA_APP_PROXY_SIGNED_PATH_PREFIX`;
- `NLA_APP_PROXY_BACKEND_PATH`;
- `NLA_APP_PROXY_SHARED_SECRET_B64`;
- `NLA_CURSOR_HMAC_SECRET_B64`;
- `NLA_STAGING_STORE_ROOT`;
- `NLA_ACTIVATION_SHA256`;
- `NLA_EVIDENCE_CODE_SHA`.

`NLA_CURSOR_TTL_SECONDS` and `NLA_REQUEST_TIMEOUT_MS` are optional bounded overrides. Startup
loads only the package named by the externally pinned activation digest, composes the real App
Proxy verifier and evidence-bound backend, and otherwise exits with one fixed value-free error.

For the first start on an exactly empty disk only,
`NLA_ALLOW_EMPTY_STAGING_STORE=true` permits the process and `/livez` to start while `/readyz`
and catalog output remain 503. With the exact absent-pointer sentinel, the launcher safely creates
the sole `generations/` directory on a virgin mounted root, or verifies that it is already the only
empty child. That public sentinel is SHA-256 of the empty byte string:
`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`. Use it for both
`NLA_ACTIVATION_SHA256` on the one-time empty bootstrap and
`NLA_STAGING_ACTIVATION_SHA256` on the first promotion; it is not a real activation pin.
The operator then installs and promotes a verified immutable package through the
provider SSH channel. The non-root container user has an explicit shell and a mode-0700 SSH home;
the catalog disk remains outside that home. The image includes only the versioned activation
operator, invoked as `python scripts/manage_staging_activation.py`; producer and raw-capture tools
remain outside the runtime image. From SSH, invoke it by its absolute path as
`python /app/scripts/manage_staging_activation.py`; do not assume the login working directory.
The operator uses the same `NLA_STAGING_STORE_ROOT` as the runtime, plus
`NLA_STAGING_ACTIVATION_ACTION` (`load`, `promote`, or `rollback`) and
`NLA_STAGING_ACTIVATION_SHA256` (the exact current pointer pin, or the documented absent-pointer
sentinel on first promotion). `NLA_STAGING_CANDIDATE_MANIFEST_SHA256` is present only for
`promote`. Before promotion, transfer exactly the three package files into a new
`generations/<manifest-sha256>/` directory on the mounted disk, owned by `appuser`; directories
for the store root and `generations/` are mode 0700, while the immutable package directory and
files preserve the producer's mode 0555 and 0444 respectively. Any write bit on the package
directory or files makes verification fail closed. Do not transfer producer scripts, raw captures,
control documents, or an existing activation pointer.

Exit 0 with `VALUE_FREE_RESULT: ACCEPTED` is the only ordinary success. Exit 1 with `REJECTED`
means no success claim. Exit 2 with `AMBIGUOUS` means the atomic pointer replacement might have
occurred but could not be re-attested: do not retry or redeploy until the exact pointer file and
generation have been inspected through the private operator channel.

After an accepted promotion, hash the exact mounted `activation.v1.json` in that same private SSH
session and copy the digest directly into host secret configuration. The value-free operator does
not print that pin, and the pin must not enter Git or application logs. Then remove the empty-store
flag and redeploy. Extra files, a partial package, a pointer
failure, an arbitrary pin, or an invalid generation never enter this bootstrap mode.

Render's eventual HTTP health check must use `/readyz` after the first verified package has been
installed. `/livez` may be used only during the one-time empty-disk bootstrap; while readiness is
false, the catalog route remains fail-closed. The service must be returned to `/readyz` before any
theme-clone integration or staging acceptance claim.

## Storage sizing evidence

The protected source capture retained outside Git currently measures:

- products JSONL: 526,794,198 bytes;
- variants JSONL: 317,704,228 bytes;
- total source capture: 844,498,426 bytes.

This is not yet a disk-size decision. The exact portable projection/package size, temporary build
peak, two retained generations, rollback copy, logs, and safety margin still need measurement on
the real package. A Blueprint must not select or create a paid disk until that measurement and
the recurring cost are presented to Jacopo.

The protected 2026-09-07 run measured the deterministic SQLite projection at exactly
851,685,376 bytes. Periodic process sampling observed at least 1,312.6 MiB working set; this is a
lower bound, not an instrumented peak. Two projection copies alone therefore require
1,703,370,752 bytes before manifests, evidence, filesystem overhead, logs, and safety margin.
The final package stayed outside Git as required, but the successor sandbox could not traverse
the protected temporary directory created by the originating job. Consequently its exact total
size and cross-runner transfer/reopen are not claimed here and must be repeated on the designated
operator runner before any paid-disk decision.

## Required remaining evidence

Issue #13 is not complete until all of the following exist on one immutable release candidate:

1. a reviewed runtime bootstrap with secrets supplied only by the host and no values in logs;
2. versioned `candidate`, `current`, and `previous` package selection with an atomic promotion;
3. a restart and redeploy proof showing the last valid package is retained;
4. an application rollback and a dataset rollback, each executed and recorded;
5. generation age, request latency/status, refresh outcome, storage, memory, and CPU visibility;
6. alerts for not-ready, stale/failed refresh, low storage, and elevated 5xx;
7. real browse/search/facet smoke tests, including traversal beyond product 25,000;
8. a public staging URL reachable only through the WS-08 policy;
9. deploy, refresh, incident, rollback, restore, and secret-rotation runbooks.

The maximum tolerated price/inventory lag remains an owner decision from issue #11. Freshness
must be configurable and measurable; it must not be invented in code as an undocumented default.

## Rollback boundary

Promotion must first verify a complete candidate, retain the exact previous manifest pin, and
then change one small atomic pointer. A failed candidate never overwrites `current`. Dataset
rollback selects the retained previous pin and restarts or atomically activates it. Application
rollback selects the previous reviewed image/commit while retaining both data packages. Neither
procedure mutates Shopify, TCG PowerTools, the MAIN theme, or a package in place.

Live publication remains exclusively within issue #18 and requires a new explicit decision from
Jacopo.
