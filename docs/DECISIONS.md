# NLA catalog gateway — decisions

## D-001 — External read-only gateway is the primary catalog architecture

- Status: accepted by Jacopo on 2026-08-31.
- Source: GitHub issue [#17](https://github.com/cajopo/nla-catalog-gateway-staging./issues/17).
- Decision: Admin Bulk plus an immutable versioned index and keyset API form the primary
  catalog path. Shopify App Proxy is the production storefront boundary.
- Consequence: native Shopify sharding cannot replace the gateway. It may be reconsidered
  only for a measured SEO or fallback benefit.

## D-002 — Shopify and TCG PowerTools authority boundaries

- Status: accepted and non-negotiable.
- Source: issues [#3](https://github.com/cajopo/nla-catalog-gateway-staging./issues/3)
  and [#17](https://github.com/cajopo/nla-catalog-gateway-staging./issues/17).
- Decision: Shopify remains authoritative for products, variants, prices, final inventory,
  product pages, cart, checkout, and orders. TCG PowerTools continues writing to Shopify.
  The gateway is a read-only projection.
- Consequence: this repository must never mutate those commercial records or disconnect,
  replace, or reconfigure PowerTools.

## D-003 — Four-family taxonomy

- Status: accepted product contract; implementation pending.
- Source: GitHub issue [#19](https://github.com/cajopo/nla-catalog-gateway-staging./issues/19).
- Decision: every included product belongs to exactly one of `single`, `sealed`,
  `accessory`, or `unclassified`; the last requires an actionable reason.
- Consequence: no record may be silently dropped, and rules cannot be keyed to individual
  GIDs, SKUs, or handles.

## D-004 — Recover PR #20 instead of replacing it

- Status: accepted technical execution decision on 2026-08-31.
- Evidence: repository-truth audit, CI run `33400328891`, CodeQL run `33400328929`, and
  independent adversarial audit of head `e5c7e92201fb8c1204680733a53f2fcf8feda4af`.
- Decision: preserve the current Git-index scanning, parsed YAML permission checks,
  least-privilege workflows, container smoke, and CodeQL foundation; repair scanner and gate
  gaps on the existing Platform branch.
- Consequence: the PR remains unmergeable until one new SHA has green CI and an independent
  review with no unresolved Blocker/Critical/High findings.

## D-005 — Keep repository preflight conservative at ambiguous shell and escape boundaries

- Status: accepted technical execution decision on 2026-08-31; workflow-command scope is
  clarified and partially superseded by D-006.
- Evidence: code candidate `bac82b122b96366799ee5da481490af38a25a2eb`, CI run
  `33435265263`, CodeQL run `33435265071`, and working-diff adversarial probes.
- Decision: the Platform gate fails closed when a workflow command or encoded secret-like
  value cannot be interpreted safely within bounded parsing. Two known conservative false
  positives are retained: executable-looking `git push` text inside a heredoc and a JSON value
  intentionally preserving a token-like Unicode escape literally.
- Consequence: these cases require rewriting the workflow/fixture into an unambiguous form.
  They do not permit a push, credential, signed URL, snapshot, or generated artifact to pass.
  A future structured parser may narrow them in a separate reviewed workstream; the current
  PR will not grow an unbounded shell or serialization interpreter.

## D-006 — Bound workflow execution checks to static capability controls

- Status: accepted technical execution decision on 2026-09-01; final exact-SHA review pending.
- Evidence: final review of green documentation head `f211b261cbf4237149b0f45a2d3a79d3476cf4ba`
  returned `CHANGES REQUIRED` for dynamic executable and Git-subcommand bypasses; corrected
  code baseline `8047ba6ae314d39189f3d0ac72303cb532f05d48`, CI run `33445224607`,
  CodeQL run `33445224609`, and a 77-danger/33-safe working-diff red-team matrix.
- Decision: inline workflow commands use a static positive allowlist. Dynamic or unknown
  executable, dispatcher target, or Git-subcommand positions fail closed. Workflow
  permissions must remain read-only, workflow secret references are rejected, and checkout
  credentials must be disabled with `persist-credentials: false`.
- Capability boundary: the repository preflight does not semantically interpret Python,
  Docker, or arbitrary scripts invoked transitively. Its PASS is a bounded defense-in-depth
  claim, not absolute proof that no indirect program could ever mutate repository state.
- Consequence: ambiguous inline execution must be rewritten into a statically auditable form.
  Changes to transitive-script analysis require a separate, testable decision rather than an
  implicit claim of complete shell or program interpretation.

## Reserved decisions

The following are not delegated technical details and require Jacopo: paid hosting or
subscription activation, persistent Shopify app installation, credentials/login/2FA,
commercial or UX requirement changes, irreversible actions, and any live theme/cutover
publication.
