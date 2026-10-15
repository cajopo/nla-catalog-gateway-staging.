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
Deployment, independent review and full validation are recorded below and in
the pull request delivery record.

## Official contracts consulted

- [CardTrader API](https://www.cardtrader.com/it-IT/docs/api/full/reference):
  HTTPS GET endpoints, Bearer authentication and rate limits. The bounded retry
  policy is local; the API does not guarantee recovery.
- Python 3.12 [urllib](https://docs.python.org/3.12/library/urllib.request.html),
  [fcntl](https://docs.python.org/3.12/library/fcntl.html) and
  [atomic replacement](https://docs.python.org/3.12/library/os.html#os.replace).
- [systemctl v255](https://github.com/systemd/systemd/blob/v255/man/systemctl.xml):
  state inspection and `reset-failed`, separate from service start/restart.


## Esito operativo verificato

Applicazione completata il 15 ottobre 2026 alle 10:17:47 UTC; verifica finale
10:18:11 UTC. Market sbloccato e inattivo in attesa del timer normale; nessun
nuovo ciclo avviato. Il catalogo risponde HTTPS 200/ready. Ledger, puntatore,
configurazione, ultima ricevuta e invocazione del refresh sono invariati.
Timer market alle 14:00 UTC (16:00 Europe/Rome), refresh alle 15:00 UTC.

Il fix del modulo di cattura è stato installato e verificato sul ciclo successivo.

[PR #112](https://github.com/cajopo/nla-catalog-gateway-staging./pull/112) aperta
in bozza, non fusa. [CI](https://github.com/cajopo/nla-catalog-gateway-staging./actions/runs/38718197954)
verde: 4.108 test passati su Python 3.12 e 3.13, coverage completo 100%;
Ruff, preflight (211 file), build, audit dipendenze e container passati.
[CodeQL](https://github.com/cajopo/nla-catalog-gateway-staging./actions/runs/38718198059)
verde. Python 3.13 segnala un ResourceWarning di connessione SQLite non chiusa
nel test preesistente dei facet; non e' un test fallito o saltato.
Due run Windows presentavano PermissionError intermittenti in fixture differenti:
non sono stati indeboliti test o controlli, il gate completo e' quello Linux.

Revisione indipendente di codice e helper approvata. Anche le prove sintetiche
native Python 3.12.3 sulla VPS sono passate, senza richieste di rete.
Il primo piano aveva rifiutato, prima di scrivere, l'UID 10001 del puntatore:
il piano v2 verifica quell'UID soltanto per quel percorso esatto, coerente con
il runtime, mantenendo UID 0 per gli altri file e tutti gli hash originali.

Ulteriori ricevute private:
repair-code-binding-v2.json, independent-recovery-review-v2.json,
native_capture_proof_remote.result.json, repair_market_remote_plan_v2.result.json,
repair_market_remote_apply_v2.result.json, post_repair_check_remote.result.json.
Il helper v2 ha SHA256
1c6824022a4a30df97e273294ec07f6264dc455ddb8b371b01827b53bb93c1b9;
e' una procedura vincolata a questo incidente e non va riutilizzata su nuovi blocchi.

## Primo ciclo completo dopo la correzione

Run `market-20261015t140020z-69980f6a`, avviato alle 14:00:20 e terminato alle
14:49:19 UTC del 15 ottobre con stato `draft_cycle_complete`. La cattura ha
completato 2.438 espansioni e 257.154 blueprint; zero elementi differiti e
zero tentativi selezionati, con `eligibleExhausted=true`. Il ciclo non ha
selezionato stampe da importare. L'indice non è stato aggiornato perché non
c'erano cambiamenti importer e l'indice esistente era fresco. Il successo non
prova che sia stata esercitata una retry transitoria: non attribuire l'esito a
quel percorso senza log che lo confermi.

La ricevuta corrisponde byte per byte al ciclo; SHA-256 della ricevuta
`3a723eab831cdba08e384660f820b16d1250924a6e35869eb1012d3477919a72`.
La versione corretta della cattura installata è stata verificata sul ciclo.
Alla verifica read-only delle 14:50:42 UTC entrambe le unità
erano inattive e il refresh delle 15 UTC risultava pronto; spazio libero
10.244.165.632 byte, generazioni corrente e precedente invariate. Il piano
retention era completato senza elementi residui.
