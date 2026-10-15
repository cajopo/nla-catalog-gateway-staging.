# NLA catalog gateway — decisions

Reconciled on 30 September 2026. D-009 through D-016 record the subsequent owner
instructions and operational outcome. They qualify older blanket restrictions and
pending-state wording; they do not broaden the gateway's read-only boundary.

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
- Consequence: the gateway and Shopify-to-index refresh never mutate those commercial
  records or disconnect, replace, or reconfigure PowerTools. The separate importer has
  only the narrow exceptions in D-009/D-010; existing commercial records remain protected.

## D-003 — Four-family taxonomy

- Status: accepted product contract, implemented and evidenced in the subsequent catalog
  workstreams; see the 30 September snapshot for operational coverage and remaining gaps.
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
- Consequence at the time: the PR was unmergeable until one new SHA had green CI and an
  independent review with no unresolved Blocker/Critical/High findings. PR #20 was later
  merged as `e8a0a354b6b584684676743cc288d4cb6b738a7f`; issue #6 is closed. This record
  preserves the recovery decision rather than reopening the completed Platform gate.

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

- Status: accepted technical execution decision on 2026-09-01; broadened by D-007 after the
  second independent review.
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

## D-007 — Ban reviewed workflow capability classes fail-closed

- Status: accepted technical execution decision on 2026-09-01; broadened by D-008 after
  reviewer v3.
- Evidence: documentation-inclusive head `00f07033baaa465ac920e620265bff570a104d03`
  (tree `3e4d99dc188122f9dae4ca937d5363a3ac2fc2a7`) passed CI `33446860246` and
  CodeQL `33446860231`, but independent review v2 returned `CHANGES REQUIRED` with four High
  capability classes. Remediated code baseline `9d351e5e78537afe3133bf20bb2b18d4b96abc9e`
  (tree `c59a59540c4301d05587fb83730e9c7ce1e30c38`) passes local and independent
  stable-freeze QA, CI `33453261603`, and CodeQL `33453261610`.
- Decision: keep the static positive allowlist and reject entire ambiguous capability classes:
  `env` split-string dispatch; `Start-Process`; PowerShell provider, function, and variable
  mutators; risky Git-helper, PAGER, PATH, and PATHEXT environment controls;
  `GITHUB_ENV`/`GITHUB_PATH` command files; path-qualified direct executables; and Bash
  indirect expansion.
- Capability boundary: read-only workflow permissions, no workflow secret references, and
  `persist-credentials: false` remain mandatory. Python, Docker, and arbitrary scripts invoked
  transitively remain outside semantic analysis; PASS is not absolute proof over them.
- Consequence: a workflow using a banned class must be rewritten into a statically auditable
  form or proposed as a separately reviewed policy change. Final merge eligibility still
  requires green gates and independent approval on one documentation-inclusive exact SHA.

## D-008 — Reject inline subexpressions and stream Docker output directly

- Status: accepted technical execution decision on 2026-09-01. The hashes below describe
  the intermediate candidate; subsequent Platform delivery is recorded under D-004.
- Evidence: reviewer v3 returned `CHANGES REQUIRED` on documentation head
  `82ec0e472d4cfb4df131e95d87a445a7b56850b4` with one High for shell and PowerShell `$()`
  subexpressions. Remote candidate `73f3f78819002ca21cea46be38b94d0eb874bb76` and local
  equivalent `db86bd356d4c356f6cc9674008dc9c5e5698ab79` share exact tree
  `a72a1c6016db2fcd8611ff5ae1ee770e5e394947`. Local gates and static red team pass; CI
  `33456765768` and CodeQL `33456765740` pass, with zero CodeQL security findings.
- Decision: fail closed on the entire inline-command classes `$()`, `<()`, `>()`, and `@()`.
  Replace the container smoke's banned command-substitution assignment with a directly
  auditable `docker run | python` pipeline. The conservative subexpression ban replaces
  attempts to infer whether an individual nested expression is safe; it does not ban that
  direct pipeline.
- Capability boundary: D-007 remains in force, including read-only permissions, no workflow
  secret references, and `persist-credentials: false`. Arbitrary transitively invoked Python,
  Docker, and other scripts remain outside semantic analysis.
- Consequence: workflows needing a banned construct must be rewritten into a statically
  auditable form or proposed as a separate reviewed policy change. Code-baseline PASS does not
  authorize merge; the final documentation-inclusive gates and reviewer v4 were required
  for that Platform delivery. These historical candidate pins are not the current release pins.

## D-009 — Separate create-only importer for missing card printings

- Status: owner-authorized on 2026-09-25.
- Source: issue [#97](https://github.com/cajopo/nla-catalog-gateway-staging./issues/97),
  owner instructions in the bootstrap chat and the existing AGENTS.md exception.
- Decision: a separate importer may create only verified missing card-printing products,
  initially DRAFT, unpublished and at zero stock, with necessary initial variants,
  metadata and traceable CardTrader/verified PowerTools or Cardmarket identities.
- Limits: fresh Shopify identity checks, safe retries and an importer ledger are required.
  Titles alone are not identity. Missing or ambiguous mappings are reported, not guessed.
  No fabricated prices, language, condition or finish. No update, merge, delete or overwrite
  of pre-existing products or their commercial data. Gateway and refresh stay read-only.

## D-010 — Guarded SOLD OUT publication of importer-owned products

- Status: owner-authorized after an explicit question on 2026-09-28.
- Source: owner instructions in the bootstrap chat and the AGENTS.md publication exception.
- Decision: a separate step may activate and publish to Online Store only products proven
  owned by the importer ledger, at zero stock and non-purchasable, after fresh identity,
  media and inventory checks.
- Limits: no commercial-data rewrite and no republication after handoff to PowerTools.
  This supersedes the initial no-automatic-publication scope of #97 only for these products.
  It does not authorize MAIN edits, PowerTools changes or corrections to existing products.

## D-011 — Defer GitHub delivery without stopping operational closure

- Status: explicit owner instruction on 2026-09-29.
- Source: «anche github sticazzi» in the bootstrap chat, followed by the documented
  release preparation and separate cutover consent.
- Decision: GitHub delivery and final exact-head checks are deferred; do not repeatedly
  wait for quota, buy minutes, push, merge or retry CI in this phase.
- Consequence: local tests and aggregate coverage are not called green GitHub CI.
  The working service can be accepted operationally while source delivery remains open.
  Normal independent review and green merge gates apply when that delivery resumes.
- Superseded in part: the owner revoked this deferral on 2026-10-03; see D-017.
  D-011 remains historical evidence for the earlier pause, not a current prohibition.

## D-012 — Authorized theme cutover completed with password retained

- Status: authorized by «consento» and executed on 2026-09-29 at 17:20 UTC
  (19:20 Europe/Rome).
- Source: [release receipts and bounded post-cutover acceptance](workstreams/ws-12-release-readiness-20260929.md),
  plus the final bootstrap-chat handoff. Local receipt `cutover-result.json` reread on 30 September.
- Decision executed: theme 175195881740 became MAIN; 175194898700 remains UNPUBLISHED
  and available for rollback. The complete 314/310 file inventories were unchanged;
  password protection stayed enabled. No PowerTools or commercial-data changes.
- Consequence: the operational bootstrap objective is complete. This is not public launch,
  password-removal consent or permission for further MAIN edits. The former test clone
  is now MAIN; future theme work needs an unpublished copy identified before editing.
- Limits: post-cutover smoke reused earlier scoped evidence; it was not a new full QA
  matrix or live rollback of the previous theme. Formal source delivery remains deferred.

## D-013 — Project management and documentation maintenance phase

- Status: owner instruction on 2026-09-30.
- Source: current chat: take a project snapshot, identify what exists and what is missing,
  maintain documentation and act as Project Manager for this phase.
- Decision: Codex maintains status, inventory, priorities, evidence limits and handoff under
  master #3 and documentation workstream #34. Preserve the previous evidence and local changes.
- Limits: PM priorities are proposals, not permission to implement new features, deploy,
  change MAIN/password, resume GitHub delivery (superseded by D-017 for its stated scope)
  or create recurring monitoring.
  The [current roadmap](ROADMAP-EXECUTION.md) identifies acceptance criteria and unassigned roles.

## D-014 — Operational maintenance objective and economical delegation

- Status: owner goal set on 2026-09-30, after the initial PM snapshot.
- Source: goal-objective.md attached to this chat; economical subagents and
  parallelism expressly authorized, starting with gpt-6-luna for bounded tasks.
- Decision: verify actual operation, complete off-VPS backup and isolated recovery
  with available authorized resources, close genuine QA gaps, maintain runbooks and
  current documents. Proceed with necessary reversible work within the existing scope.
- Executed: read-only VPS inventory, private manual PC checkpoint and offline data
  restore, installed image/source/reference preservation, focused
  Chrome/Firefox/WebKit fixture QA and automatic accessibility checks.
- Limits: no MAIN/password/PowerTools change, GitHub delivery was deferred under D-011
  (that deferral is revoked within D-017's scope), no recreation of the completed heartbeat,
  no unapproved paid resource or message to an invented recipient. Backup destination,
  alert recipient/operator and complete runtime recovery remain open. Partial data
  recovery and fixture tests do not make the goal complete.
- Evidence: [maintenance checkpoint](evidence/MAINTENANCE-2026-09-30.md) and
  [operator runbook](OPERATIONS-RUNBOOK.md). D-013's narrower initial PM-documentation
  scope is expanded by this objective; reserved decisions below still apply.

## D-015 — First off-VPS copy and initial alert channel

- Status: owner answers in this chat on 2026-09-30.
- Decision: use the owner's PC for the first private off-VPS copy; the owner will
  identify the permanent destination. Email is the initial alert channel.
- Limits: this does not choose a paid service, guarantee recurring backups or
  authorize an email test. Recipient address and incident referent remain to be
  confirmed; delivery and complete recovery still require executable evidence.
- Evidence: [operator runbook](OPERATIONS-RUNBOOK.md) and
  [maintenance checkpoint](evidence/MAINTENANCE-2026-09-30.md).

## D-016 — Obsolete VPS files: quarantine, verification, deletion and 48-hour checks

- Status: explicit owner instruction in this chat on 2026-09-30.
- Decision: remove VPS files that are no longer needed; first relocate them,
  verify operation, then delete. Check at least every 48 hours for space maintenance.
- Executed: three unreferenced legacy generations and two old incoming artifacts
  quarantined at 17:58 UTC; pagination on four games and search/suggestions passed;
  independent deletion review passed; deletion at 18:16 UTC recovered 3,654,983,680
  allocated bytes. HTTPS readiness, pointer and operator-config hashes unchanged.
- Recurrence: ordinary retention already runs on the VPS after successful refreshes
  scheduled at 03/15 UTC. New thread heartbeat `manutenzione-spazio-vps-nla`, ACTIVE,
  checks every 48 hours for space, retention outcomes and exceptional leftovers.
  It requires the PC and Codex app running; normal VPS retention does not.
- Limits: no guaranteed free-space floor or email delivery; failed/incomplete cycles,
  current/previous catalog, importer ledger, active references, credentials, installed
  sources and necessary evidence stay protected. Old restore-drill files with stopped
  container mounts were excluded. No generic prune or duplication of the former heartbeat.
- Evidence: [retention receipt](evidence/RETENTION-2026-09-30.md) and
  [operator procedure](OPERATIONS-RUNBOOK.md). This authorization qualifies D-013/D-014
  and the reserved irreversible-action rule only for verified obsolete VPS artifacts.

## D-017 — Resume GitHub delivery and fix the refresh interruption

- Status: direct owner instruction on 2026-10-03: «comprendi le motivazioni dell'errore e fixalo… riproviamo anche la parte di github…».
- Decision: investigate and correct the documented refresh interruption, then resume
  GitHub delivery. This revokes the GitHub deferral in D-011 and D-014 for incident
  correction and the scoped delivery work needed to complete it.
- Limits: keep work in reviewable issue/PR units; require independent review and green
  CI/CodeQL on final heads before merge. This does not authorize merge of red checks,
  quota purchases, paid services, email, MAIN/theme/password changes, PowerTools changes,
  or Shopify commercial-data mutations.
- Current evidence: [refresh incident](evidence/INCIDENT-2026-10-03.md),
  [GitHub recovery/delivery inventory](evidence/GITHUB-RESUME-2026-10-03.md). PR #100's
  checks passed. Recovery and the ordinary read-only refresh completed successfully;
  freshness and retention passed at 09:15 UTC. The old market failure state was
  reset without starting a process or making Shopify calls; its historical
  `ExecMainStatus=1` remains visible and is not a new market success.

## D-018 — Backblaze backup destination

- Status: owner choice on 2026-10-03. Jacopo created the private `nla-catalog`
  bucket in `eu-central-003`, supplied a bucket-scoped application key through
  the local encrypted collector, then explicitly instructed us to proceed.
- Decision: use this bucket for NLA backups. The first transfer is the existing
  verified catalog/ledger checkpoint; read, upload, download and offline restore
  have succeeded. The key is stored only on the PC under its protected ACL.
- Evidence: [Backblaze transfer and restore](evidence/BACKBLAZE-2026-10-03.md).
  This supersedes the earlier pending choice of durable destination; it does
  not establish scheduled backups, an RPO/RTO guarantee or full-system recovery.
- Limits: preserve original checkpoints and receipts. No bucket lifecycle or
  Object Lock changes, deletion, VPS changes, email or Shopify/PowerTools changes
  were performed in this first-copy operation. Scheduling, retention and the
  treatment of credentials/configuration/runtime images remain separate work.

## D-019 — Preparazione del backup cifrato

- Status: technical preparation on 2026-10-15, within the authorized backup
  destination D-018. No new hosting or subscription is selected.
- Decision: evaluate and verify restic 0.19.1 through the Backblaze S3 endpoint,
  in the separate `nla/restic-v1` prefix. Preserve the original manual object.
  Official binaries were authenticated; the private pilot was independently
  reviewed. Encrypted transfer, full cloud-data check and PC archive recovery
  passed with identical SHA-256 before any connection to unattended VPS backups.
- Evidence: [encryption pilot and inventory](evidence/BACKUP-ENCRYPTION-2026-10-15.md).
  The pilot is fixed to the October 3 checkpoint; a new transfer does not make
  its source data current. It is not the recurring backup implementation.
- Limits: no cloud retention/deletion policy, lifecycle/Object Lock changes or
  VPS scheduler is activated by this decision. Complete encrypted coverage,
  independent key recovery and a fresh full-service restore remain required.

## D-020 — Destinatario email iniziale degli alert

- Status: confermato da Jacopo nella chat il 15 ottobre 2026.
- Decisione: usare l'indirizzo fornito come destinatario iniziale; mantenerlo
  modificabile nella configurazione, senza inserirlo nel codice o nei documenti
  pubblicati. La scelta e' registrata in privato in
  `output/nla-recovery/20260930/alert-recipient-20261015.json`.
- Limiti: confermare un indirizzo non dimostra la consegna e non autorizza un
  messaggio di prova. Servizio, referente operativo e collaudo restano distinti.
  Preparare il recapito concreto prima della richiesta finale di autorizzazione.

## Reserved decisions

Future actions in the following areas are not delegated technical details and require Jacopo: paid hosting or
subscription activation, persistent Shopify app installation, credentials/login/2FA,
commercial or UX requirement changes, irreversible actions, and any live theme/cutover
publication or store-password removal. Already completed authorizations above are not
requests to obtain the same consent again.
