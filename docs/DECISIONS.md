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
- Limiti al momento della scelta: il solo indirizzo non dimostrava la consegna
  né autorizzava messaggi di prova. Per le successive autorizzazioni usare
  D-022 e D-023, senza riproporre una richiesta già superata; la prova di
  recapito resta necessaria.

## D-021 — Credenziali del backup sulla VPS

- Status: autorizzazione esplicita di Jacopo il 15 ottobre 2026: «Sì, autorizzo
  il trasferimento alla VPS NLA», in risposta alla richiesta relativa a chiave
  Backblaze dedicata e password del repository cifrato.
- Decisione: trasferire le due credenziali dal PC alla VPS NLA tramite SSH in
  file leggibili solo da root. Il proprietario è stato informato che chi avesse
  accesso root alla VPS potrebbe leggerle. Il precedente blocco della revisione
  automatica è risolto; non serve ripetere questa richiesta.
- Esito: directory `/etc/nla-backup` root 0700 e file 0600 creati; configurazione
  e unità verificate. Primo backup completo corrente terminato alle 13:30:23 UTC
  con controllo integrale `read-data` passato e staging proprio rimosso.
- Aggiornamento 16 ottobre: un tentativo di attivazione si è fermato in admission
  senza avviare il job; un successivo job avviato alle 11:38:34 UTC è terminato
  alle 11:39:01 UTC con `checkpoint_failed`, prima del trasferimento. Il timer
  resta disabilitato; la configurazione v2 `d5d65f` con sorgente `929c7b0` e servizio `804` è installata; lo staging di circa 2,14 GB resta conservato per diagnosi.
- Aggiornamento 17 ottobre: correzione `b56ca95` installata, nuovo backup completo
  e verificato `read-data`; timer abilitato alle 01:00 UTC, prima scadenza osservata
  18 ottobre. Il payload fallito è stato rimosso dopo quarantena, verifica funzionale
  e review indipendente; le prove sono conservate.
- Aggiornamento 18 ottobre: primo ciclo automatico terminato alle 01:01:33 UTC,
  `read-data` PASS; inclusione dell'observer verificata nel manifest remoto.
  Custodia della password confermata dal titolare (D-025); recapito TEST email
  verificato (D-022). [Prova del ciclo](evidence/BACKUP-SCHEDULED-2026-10-18.md).
- Limiti residui: recupero completo e crescita oltre i carichi usati per la
  riserva disco non provati. Le copie cloud sono conservate; la rotazione
  automatica resta una preparazione opzionale inattiva, senza cancellazioni.
  [Backup e limiti](evidence/BACKUP-AUTOMATION-2026-10-15.md) ·
  [Conservazione](evidence/CLOUD-RETENTION-2026-10-17.md).

## D-022 — Attivazione UptimeRobot e referente iniziale

- Status: Jacopo ha autorizzato nella chat il 15 ottobre 2026 l'invio del
  destinatario confermato e dell'URL a UptimeRobot, con la conseguente email
  di attivazione; ha confermato di essere il referente iniziale degli incidenti.
- Configurazione richiesta: piano Free, HTTPS ogni cinque minuti su
  `https://catalog-staging.nextlevelarena.it/readyz`, avvisi email down/up.
  Contratto e piano gratuiti verificati nuovamente il 15 ottobre.
- Esito: richiesta inviata alle 13:49:32 UTC; HTTP 200, `status=ok`.
  Jacopo ha poi confermato ricezione, attivazione e accesso alla dashboard.
  Non serve ripetere l'attivazione o richiedere il consenso all'accesso.
  La verifica diretta del monitor era rimasta incompleta: Computer Use ha interrotto
  l'accesso perché non poteva accertare l'URL del browser per applicare la
  propria policy. È un limite tecnico distinto dall'autorizzazione del titolare.
- Aggiornamento 18 ottobre: TEST DOWN/UP ricevuti e verificati nella casella
  autorizzata alle 00:52 UTC. Jacopo ha confermato il monitor su `/opsz` e UP;
  la sonda indipendente GET/HEAD delle 01:13 UTC è riuscita. `/opsz` estende
  il controllo a esito refresh, freschezza e backup. Configurazione dopo il
  cambio attestata dal titolare, non ispezionata direttamente nella dashboard.
  [Prova email e monitor](evidence/ALERT-DELIVERY-2026-10-18.md).
- Limiti della richiesta iniziale: riguardava l'email di attivazione e il monitor
  proposto. Per proseguire vale la successiva D-023; non simulare guasti sul
  servizio attivo. Il recapito TEST non equivale a un incidente reale simulato.
  [Procedura e fonte ufficiale](OPERATIONS-RUNBOOK.md).

## D-023 — Continuità operativa entro l'obiettivo autorizzato

- Status: istruzione esplicita di Jacopo, ribadita il 16 ottobre 2026:
  «basta chiedere consensi. approvo tutto» e richiesta di ridurre le conferme
  che rallentano l'operatività.
- Decisione: proseguire autonomamente il lavoro già compreso nell'obiettivo
  operativo NLA e nelle autorizzazioni precedenti. Non riproporre al titolare
  le stesse decisioni, né trattare ogni comando o verifica come un nuovo consenso.
  Il collaudo previsto degli alert al recapito già scelto rientra nell'obiettivo;
  non estendere destinatari o servizi e non provocare guasti sul servizio attivo.
  Raggruppare le operazioni revisionate in procedure concrete; quando disponibile,
  usare un'autorizzazione tecnica persistente limitata alla procedura del progetto.
- Esecuzione: restano richiesti controlli tecnici, prove riproducibili e review
  indipendente nei punti previsti. Le restrizioni dell'ambiente non vanno aggirate
  né rimosse modificando ACL, credenziali o impostazioni globali. Un eventuale
  blocco deve indicare il vincolo effettivo, senza attribuirlo a un consenso utente
  già ottenuto. Restano validi i confini su Shopify MAIN, PowerTools e dati esistenti.

## D-024 — Rinvio GitHub fino all'intervento sul budget

Aggiornamento del 19 ottobre: il rinvio è superato per i tentativi settimanali
espressamente autorizzati in D-027. Il testo sotto conserva la decisione storica;
non impedisce l'esecuzione dell'automazione GitHub autorizzata.

- Status: istruzione esplicita di Jacopo il 17 ottobre 2026: ha esaurito le
  azioni GitHub disponibili e chiede di posticipare le operazioni finché non
  avrà agito sul budget.
- Decisione: sospendere le operazioni GitHub, inclusi push, aggiornamenti di
  issue/PR, merge, avvio o retry dei workflow e polling dei controlli. Riprendere
  quando Jacopo comunicherà di aver sistemato il budget; non chiedere conferme
  ripetute e non acquistare minuti né modificare la fatturazione.
- Ambito: questo rinvio prevale temporaneamente sulla ripresa autorizzata in
  D-017. L'obiettivo operativo e D-023 restano validi per le attività indipendenti
  da GitHub. Conservare localmente modifiche, prove e documentazione per la
  successiva consegna; questa decisione non è ancora pubblicata su GitHub.
- Stato conservato: PR #101 head `18ed78320f485d9ff03c05fa0514000e8afc156b`;
  CI `39021491093` e CodeQL `39021491094` non avviati per la condizione di
  pagamento o limite di spesa segnalata da GitHub. I controlli del codice
  installato PR #114, head `319ca0b`, sono già verdi. Nessun nuovo controllo
  remoto è necessario per registrare il rinvio.

## D-025 — Custodia della password backup in 1Password

- Status: Jacopo ha scelto 1Password il 17 ottobre 2026 e ha poi confermato
  «salvata» per la password di cifratura Restic, dopo la procedura manuale.
  Custodia registrata sulla base della conferma del titolare, senza accesso
  dell'agente al gestore o lettura della password.
- Voce indicata nella procedura: `NLA — Recupero backup Backblaze`.
  Il salvataggio è confermato; resta distinta la prova completa di recupero
  usando la copia custodita in 1Password.
- Per la fase corrente la conferma di Jacopo chiude la custodia indipendente.
  Il drill applicativo del 18 ottobre usa la copia operativa autorizzata della
  password: non prova una lettura dal gestore e non richiede di ripetere il
  salvataggio. [Prova e limiti](evidence/RECOVERY-APPLICATION-2026-10-18.md).
- Le credenziali Backblaze erano già custodite. La conferma successiva riguarda
  specificamente la password Restic prima mancante; non ripetere il trasferimento.
- Usare la password esistente, senza rigenerarla o inserirla in chat, Git o
  documentazione. Il passaggio finale nel gestore è manuale: Computer Use vieta
  l'automazione delle app e dei siti dei password manager.

## D-026 — Tipografia provvisoria e chiusura QA

Stato storico del 18 ottobre: la successiva D-028 registra lo stile Arena
approvato e pubblicato. La chiusura QA della Fase 2 resta valida nel suo ambito.

- Il 18 ottobre Jacopo ha chiarito che font e dimensione del testo non sono
  definitivi. La loro finalizzazione non è un requisito di questa fase.
- Le immagini iniziali del carrello sono state completate dalle immagini della
  PDP: spot-check manuale dei due stati coerente e revisionato. Non si dichiara
  una registrazione delle interazioni o un checkout. La proposta CSS locale è
  opzionale e non autorizza modifiche a MAIN o pubblicazioni.
  [Evidenze e limiti](evidence/QA-REMAINING-2026-10-18.md).

## D-027 — Fase 2 chiusa e ripresa GitHub settimanale

- Il 19 ottobre Jacopo conferma «Fase 2 Chiusa» e autorizza un tentativo a
  settimana per sistemare la consegna GitHub, interrompendo l'attività dopo
  il primo completamento riuscito. Non occorre attendere un ulteriore consenso
  sul budget per questi tentativi; nessuna autorizzazione ad acquistare minuti.
- Creata in questa chat l'automazione `completa-consegna-github-nla`, ACTIVE,
  ogni martedì alle 09:00, Europe/Rome. Se il blocco rimane invariato, nessun
  retry insistente né notifica ripetitiva; riprovare alla scadenza successiva.
- Il successo richiede la sistemazione dei residui pertinenti, controlli sul
  commit finale e review soddisfatti, integrazioni autorizzate concluse e
  documentazione coerente. Un accesso riuscito o un solo workflow verde non
  bastano. Al primo successo completo eliminare soltanto questa automazione.
- La chat rimane aperta per la manutenzione VPS. L'automazione
  `manutenzione-spazio-vps-nla` resta ACTIVE e invariata: alla verifica del
  19 ottobre il calendario salvato è domenica alle 09:00, mentre il prompt
  conserva il riferimento storico alle 48 ore. Non è stato modificato qui.
- Restano esclusi deploy, modifiche MAIN/password/PowerTools, nuova funzionalità,
  indebolimento dei controlli, auto-approvazioni e cambi alla fatturazione.

## D-028 — Stile Arena pubblicato

- Jacopo ha approvato lo stile Arena, il mantenimento del logo attuale e accenti
  neon contenuti nei colori e nel gradiente del logo, estendendo la direzione
  all'intero sito. La tipografia provvisoria di D-026 non descrive più lo stato
  attuale del tema.
- Il 19 ottobre 2026 Jacopo ha pubblicato il tema `210350735628`: lettura
  successiva conferma `MAIN`, `processing=false`; il precedente `175195881740`
  è `UNPUBLISHED` e conservato per rollback. La preparazione era avvenuta sul
  clone non pubblicato; il connettore non consente scritture MAIN/pubblicazione.
- Prova privata: `C:/Users/umbri/.codex/visualizations/2026/10/19/01a154c0-ddcf-70e1-b9f7-c8df57c74630/arena-rollout/publication-verified.json`.
  La ricevuta conferma anche il caricamento Arena nel browser integrato; la
  successiva conferma di Jacopo in incognito è un'evidenza distinta della chat.
  Nessuno snapshot Shopify viene aggiunto a Git.
- La pubblicazione dello stile non equivale all'apertura pubblica: password
  conservata, PowerTools e dati commerciali invariati.

## D-029 — Home, funzionalità e sezioni prima del lancio

- Il 20 ottobre 2026 Jacopo ha precisato che prima del lancio pubblico vuole
  modifiche alla home, aggiunta di funzionalità e aggiunta di sezioni del sito
  non dedicate alla vendita.
- Questi tre workstream precedono il lancio. Dettagli di home, funzionalità,
  sezioni e relativi criteri di completamento sono ancora da definire: non
  assumere funzionalità specifiche, includere automaticamente il backlog,
  inventare scadenze o introdurre una nuova fase numerata.
- Arena resta la direzione visiva approvata. La Fase 2 è chiusa; manutenzione
  ordinaria e consegna GitHub differita restano percorsi separati, senza riaprire
  bootstrap o prove già accettate.
- La password non è stata rimossa. L'apertura pubblica viene dopo questi
  lavori e richiede la decisione del titolare sulla sua rimozione.
  [Ordine aggiornato](ROADMAP-EXECUTION.md#ordine-di-lavoro-proposto).

## D-030 — Completare la consegna GitHub nella repository pubblica

- Il 20 ottobre Jacopo ha comunicato di avere reso pubblica la repository
  per utilizzare Actions e ha chiesto di completare tutto il lavoro GitHub,
  prima di riportarla privata personalmente.
- Questa istruzione autorizza la ripresa immediata oltre la cadenza D-027 e
  supera il rinvio D-024. Sono inclusi riconciliazione delle PR, correzione dei
  conflitti e dei controlli, consegna dei sorgenti finalizzati e documentazione.
- Restano obbligatori controlli sul commit consegnato, revisione indipendente
  e conservazione del lavoro locale. Nessuna modifica a fatturazione, VPS,
  Shopify, MAIN o PowerTools è parte di questa consegna.
- Al completamento eliminare soltanto `completa-consegna-github-nla`;
  mantenere aperta la chat e invariata `manutenzione-spazio-vps-nla`.
  La successiva visibilità privata viene gestita da Jacopo.

## Reserved decisions

Future actions in the following areas are not delegated technical details and require Jacopo: paid hosting or
subscription activation, persistent Shopify app installation, credentials/login/2FA,
commercial or UX requirement changes, irreversible actions, and any live theme/cutover
publication or store-password removal. Already completed authorizations above are not
requests to obtain the same consent again.
