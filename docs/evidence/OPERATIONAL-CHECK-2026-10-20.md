# Verifica operativa — 20 ottobre 2026

Controllo richiesto da Jacopo dopo la revisione della roadmap. Osservazione in
sola lettura dalle 08:28:10 UTC (10:28 italiane), via SSH con chiave e host key
già configurate. Nessun job forzato, restart, modifica a Shopify, ricevute,
ledger, configurazioni o alert. La Fase 2 chiusa non viene riaperta.

## Nuove uscite: recupero confermato

Il ciclo `market-20261020t020001z-d5bf0c5e`, iniziato alle 02:00:01 UTC,
è terminato alle 04:31:17 UTC con `draft_cycle_complete`, `sourceComplete=true`
e `eligibleExhausted=true`: 2.439 espansioni, 257.167 blueprint, un candidato
selezionato, zero rimanenti, zero eccezioni e zero espansioni rinviate.
La ricevuta registra `indexRefreshed=true` e `published=true`; questa verifica
legge gli esiti del processo ordinario e non effettua una nuova pubblicazione.

`last-market-success.json` coincide byte per byte con la ricevuta immutabile
`/opt/nla-staging/importer-state/market-20261020t020001z-d5bf0c5e/completed.json`.
SHA256: `456b8fc3825a0a508af29d80a088b4a6b7458973f7f80462c0f3e123eb011cf2`.
Servizio `inactive/dead`, `Result=success`, `ExecMainStatus=0`; nessun marker
market pendente. Il timer è attivo, prossimo avvio alle 14:00 UTC.

La ricevuta precedente del 19 ottobre alle 14:00 identifica la causa del
`draft_cycle_partial`: una sola espansione rinviata, ID `4912`, motivo
`export_http_404`, HTTP 404. Non era un errore della ricerca codici.
La ricevuta storica conserva SHA256
`5fb4de9672fcc50d5194db59214ff5458985479d6764bc6631d8aae0ebc72096`.
Il ciclo successivo completo supera la condizione `market_incomplete`;
la ricevuta storica non è stata riscritta.

## Catalogo e monitor

Refresh `20261020t043121z-e588e0a1`, sorgente iniziata alle 04:31:37 UTC,
attivazione alle 06:07:49 UTC, stato `ready`; servizio terminato alle
06:07:52 UTC, `inactive/dead`, `Result=success`, `ExecMainStatus=0`.
Il manifest `4d3feb9ada55f4367ab88634743e061c74e3fb09a51ee769547cf95b282f7f06`
corrisponde al `currentManifestSha256` del pointer attivo. Alla lettura la
sorgente ha circa 3 ore e 57 minuti, entro la tolleranza di 24 ore.
Il timer refresh è attivo, prossimo avvio alle 15:00 UTC.

- Ricevuta refresh SHA256:
  `75161a25485d16fe2dd0f11c67dd9cea178a6ed3c736cf3933502084457ce06d`.
- Pointer SHA256:
  `18c8b12aa859969c2eef15cc3527595d070c14b585d1d18275a53d14cfa90bf4`.
- GET HTTPS `/readyz`: **200**.
- GET HTTPS `/opsz`: **503**. Le tre ultime osservazioni del collector,
  dalle 08:26:48 alle 08:27:50 UTC, riportano **`backup_attention`**.
- Spazio libero osservato: 13.162.090.496 byte; non è una prova di capacità
  massima o di retention completa.

Il catalogo è aggiornato e raggiungibile, ma il monitor operativo non è UP.
La segnalazione backup è distinta dal problema market recuperato. Nessun
reset, soppressione dell'alert o nuova simulazione di guasto.

## Backup: attenzione confermata

Diagnosi indipendente in sola lettura alle 08:30:44 UTC. Il backup automatico
del 20 ottobre, iniziato alle 01:00:20 UTC, è fallito dopo circa 0,187 secondi
con `checkpoint_failed`. Servizio `failed`, `Result=exit-code`,
`ExecMainStatus=1`; la prima condizione che fa scattare l'alert è questo
fallimento del servizio.

- Job: `backup-0c597e6bcf664347a4dcf520649335ce`.
- Ricevuta del fallimento SHA256:
  `51416a532ebbaed7ea0580e4b58c05b412a6cf0304dd715a6c8f1d3c779dd3a2`.
- Ultimo backup completo: 19 ottobre, 01:01:25 UTC, checkpoint 01:00:29 UTC;
  controllo `read-data` passato. `last-success` coincide con la ricevuta
  immutabile, SHA256
  `cdef476b5b4773d118e8ca0231d2ffc982b04f9c721e15633bf945b70aff05a4`.
- Età del checkpoint: 31 ore e 30 minuti, oltre il trigger di alert di 26 ore.
  Quest'ultimo non è la proposta RPO di 36 ore.
- Directory di staging del job fallito ancora presente. Timer enabled e
  waiting, prossimo avvio 21 ottobre alle 01:00 UTC.

La ricevuta sanificata non espone la causa interna del checkpoint fallito.
La diagnosi conferma l'incidente, non una correzione: nessun backup avviato,
servizio ripristinato, staging eliminato o verifica cloud completa ripetuta.
La manutenzione deve diagnosticare e correggere il checkpoint, poi verificare
un nuovo backup completo e il rientro del monitor, prima dell'apertura pubblica.

## Metodo e prove locali

Consultati [systemctl v255](https://raw.githubusercontent.com/systemd/systemd/v255/man/systemctl.xml)
e [manuale OpenSSH](https://man.openbsd.org/ssh.1). Versione rilevata:
`systemd 255 (255.4-1ubuntu8.18)`. Letture limitate a proprietà delle unità,
ricevute JSON, pointer, due endpoint HTTPS e sole ragioni sanificate del
collector. Non esportati ambiente completo, log integrali o URL firmati.

Prove private, escluse da Git, nella cartella
`C:/Users/umbri/Projects/nla-catalog-gateway-staging/output/market-check-20261020/`:

- `inspect_remote.py`, SHA256
  `de9fc2219842a7d21f39fe79723c9a3a3f5d4ea6087c23574146fd4d6a4feed2`.
- `inspect_remote.result.json`, SHA256
  `69552af56bce169ddf0c7037ff886ee438931af9b742507bec7eb580197200f2`.
- `backup_readonly.py` e `backup_readonly.result.json`; quest'ultima SHA256
  `24a072a13cf410418a04d9430aea5c3142393ca0a77611e04af7b10a9fe8c9e5`.

Esecuzione tramite il runner SSH esistente `run_remote_script.py` del worktree
`0072`, timeout 55 secondi, verifica host key obbligatoria, exit 0. Il primo
tentativo limitato dalla sandbox non ha raggiunto il server; il successivo
accesso di sola lettura è stato approvato ed è riuscito.

Nessuna suite applicativa rieseguita: non sono cambiati codice o servizi.
Controlli documentali PASS: link locali nuovi risolti, whitespace del nuovo
documento verificato e `git diff --check` sui cinque documenti esistenti exit 0.
Revisione indipendente finale PASS, senza finding introdotti: controllati
date, conteggi, hash e corrispondenza con le due ricevute private, separazione
fra recupero market e incidente backup, e natura di sola lettura degli script.
