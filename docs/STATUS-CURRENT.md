# Stato attuale del progetto NLA

Aggiornamento operativo del 15 ottobre 2026; fotografia generale del 3 ottobre.
PM della fase: Codex, incaricato da Jacopo.
Workstream documentale [#34](https://github.com/cajopo/nla-catalog-gateway-staging./issues/34), roadmap [#3](https://github.com/cajopo/nla-catalog-gateway-staging./issues/3).

L'obiettivo operativo della chat «Esegui bootstrap e audit NLA» è raggiunto.
Il catalogo usa il tema principale dal 29 settembre, ore 19:20 Europe/Rome.
Il negozio resta protetto da password. Il 3 ottobre Jacopo ha revocato il rinvio
della consegna GitHub e ha chiesto di capire e correggere l'errore, poi riprendere
la consegna. Il ramo main è ora `90f4f49` (integrazione PR #108); la correzione
market è nella [PR #112](https://github.com/cajopo/nla-catalog-gateway-staging./pull/112).
Recovery VPS del 3 ottobre conclusa alle 07:29:11
UTC; il refresh ordinario read-only successivo è terminato exit 0 alle 09:12:19.
Freschezza, pointer e readiness sono passati; runtime `af366c05…` è attivo senza
OOM. Vedi [incidente](evidence/INCIDENT-2026-10-03.md) e
[ripresa GitHub](evidence/GITHUB-RESUME-2026-10-03.md).

Il 15 ottobre alle 10:17:47 UTC è stato corretto e sbloccato il market:
interruzione della cattura CardTrader del 14 ottobre, prima di qualsiasi scrittura
Shopify; marker pendente archiviato dopo verifica indipendente e ledger immutato.
Il modulo ora ritenta gli errori transitori e conserva diagnostica sicura.
Readiness 200/ready, puntatore e ricevuta del refresh invariati; nessun avvio o
riavvio di processi. Il refresh ordinario era già terminato alle 04:38:51 UTC.
Prossimo market previsto alle 14:00 UTC, refresh alle 15:00 UTC; un nuovo ciclo
market completo non è ancora attestato. Vedi [incidente market](evidence/MARKET-SOURCE-2026-10-15.md).

Questa pagina riassume lo stato; la [fotografia del 30 settembre](evidence/STATE-2026-09-30.md)
contiene inventario, limiti delle prove, versioni e riconciliazione con GitHub.
Il 15 ottobre è riuscita anche la [prova di backup cifrato S3](evidence/BACKUP-ENCRYPTION-2026-10-15.md):
checkpoint del 3 ottobre trasferito, controllato integralmente e recuperato su PC
con hash identico. Era la prova sul checkpoint storico; il successivo primo
backup completo corrente è descritto sotto. Scheduler, conservazione e custodia
indipendente delle chiavi restano da completare.
Il codice del backup automatico è nella [PR #113](https://github.com/cajopo/nla-catalog-gateway-staging./pull/113),
con CI Linux verde (4.191 test per versione Python, copertura 100%) e review
indipendente. [Prove e limiti](evidence/BACKUP-AUTOMATION-2026-10-15.md):
trasferimento credenziali autorizzato (D-021), installazione verificata e primo
backup completo corrente terminato alle 13:30:23 UTC, con controllo `read-data`
passato e copie temporanee rimosse. Timer disabilitato; restano recupero
applicativo e margine disco per trasferimenti lunghi/falliti prima dell'attivazione.
La [verifica operativa del 30 settembre](evidence/MAINTENANCE-2026-09-30.md)
aggiunge stato VPS, cicli, prima copia fuori host e prove browser. Il successivo
[recupero Linux isolato](evidence/RECOVERY-LINUX-2026-09-30.md) verifica dati,
ammissione, paginazione/ricerca, errore di cursore e carico limitato; il drill
temporaneo è ora chiuso. La prova di generazione attiva del 29–30 settembre è
storica e superata dalla recovery e dal refresh del 3 ottobre. La password resta
attestata dalle prove precedenti.
La nuova [prova PC](evidence/RECOVERY-PC-2026-10-01.md) attesta immagine e
integrità dei dati restaurati nel volume Linux isolato; il controllo di memoria
ha bloccato la preparazione del runtime, che non è stato creato né avviato.
La [prova reference](evidence/REFERENCE-RECOVERY-2026-10-01.md) ha poi accettato
la configurazione restaurata e validato tutte le 336.752 identità con i sorgenti
installati, offline sul PC. Il ciclo Shopify effettivo resta da collaudare.

## Cosa abbiamo

| Area | Stato verificato | Evidenza |
| --- | --- | --- |
| Catalogo completo | Proiezione Shopify e navigazione oltre 25.000, con conte e identità verificate | Fotografia, dati e prove di traversal |
| Ricerca | Gioco obbligatorio; singole per nome/codici verificati; sigillato e accessori per titolo commerciale; vista Tutto | [Ricerca per famiglia](workstreams/ws-05-family-search-v1.md) |
| Suggerimenti | Nomi distinti e dinamici per le singole, confinati al gioco | Prove browser del 28 e 29 settembre |
| Filtri | Famiglia, disponibilità, espansione/rarità per le singole e stato URL | Fotografia e prove browser |
| Presentazione | Immagini, SOLD OUT rosso, prezzi assenti/zero omessi nell'interfaccia; acquisto nativo Shopify | [QA della home e del carrello](workstreams/ws-10-home-browser-20260928.md) |
| Aggiornamenti | Timer attivi; refresh delle 15 UTC completato alle 16:40 UTC del 30 settembre; otto nuove carte nel ciclo mattutino, zero in quello pomeridiano | Ricevuta terminale e pointer concordanti; nessun job riavviato |
| Refresh e market, 3 ottobre | Run `20261003t073240z-3f7384f8` exit 0; servizio terminato 09:12:19 UTC, monitorato 09:14:01. Attivazione 09:12:13; freshness PASS 09:15:01, source age 6.124 secondi (1 h 42 min 4 s), ricevuta/last-success/pointer coerenti, HTTPS 200; smoke 10/10 alle 09:14:42. Dataset SHA-256 `5152b3c3…`; runtime `af366c05…` senza OOM. Resolver/ack market hanno ripulito solo stato storico senza avviare job o chiamare Shopify. Timer prossimi: market 14 UTC, refresh 15 UTC | [Incidente](evidence/INCIDENT-2026-10-03.md); refresh Shopify read-only |
| Retention e spazio VPS | Retention finale 09:15:41: piano completato, sei container e quattro directory obsolete rimosse, due generazioni soltanto; corrente/precedente e ledger protetti/verificati. Spazio 11.782.266.880 byte. Letture precedenti: 5.446.959.104 byte alle 07:45 e 5,67 GB; non sommarle per dedurre il recupero del piano | [Retention](evidence/RETENTION-2026-09-30.md); [stato incidente](evidence/INCIDENT-2026-10-03.md). Riserva 6 GiB solo pre-cattura, senza garanzia sul picco |
| Backup e recupero | Servizio e credenziali installati sulla VPS; primo backup corrente completo su Backblaze e controllo integrale passati il 15 ottobre alle 13:30 UTC. Timer disabilitato: restano margine disco in caso di errore e recupero applicativo. Il precedente checkpoint PC del 3 ottobre era già stato riscaricato e restaurato offline, tre DB PASS | [Backup corrente](evidence/BACKUP-AUTOMATION-2026-10-15.md); prove storiche: [Backblaze 3 ottobre](evidence/BACKBLAZE-2026-10-03.md), [checkpoint PC](evidence/BACKUP-PC-2026-10-03.md), [PC](evidence/RECOVERY-PC-2026-10-01.md), [reference](evidence/REFERENCE-RECOVERY-2026-10-01.md), [Linux](evidence/RECOVERY-LINUX-2026-09-30.md) |
| QA componente | Matrice 21/21 in Chrome, Firefox e WebKit; smoke touch 390×844 e retry dopo 503 simulato sulla fixture; axe zero violazioni, un incomplete di contrasto valutato manualmente nello stato coperto | Solo fixture congelata; non certifica Shopify/mobile reale, Safari/iOS, screen reader, outage gateway o freschezza. Dettagli: [QA](evidence/MAINTENANCE-2026-09-30.md#qa-sul-sorgente-congelato); ricevuta privata in `../output/nla-recovery/20260930/evidence/qa-touch-down-final/index.json` |
| Sicurezza | Confine Shopify App Proxy autenticato; gateway e refresh in sola lettura | Architettura #17 e prove del servizio |
| Tema | 175195881740 principale; 175194898700 conservato per ripristino; password attiva | [Ricevute del passaggio](workstreams/ws-12-release-readiness-20260929.md) |

## Cosa resta aperto

- Completare la consegna delle correzioni successive e della documentazione:
  l'integrazione principale della PR #108 è fusa dal 4 ottobre in `90f4f49`;
  le PR #100 (recovery), #101 (PM), #112 (market) e #113 (backup) restano non fuse.
  Verifica metadati del 15 ottobre, senza nuova esecuzione CI. Restano review,
  controlli sui commit finali e riconciliazione delle issue per questi residui.
- Certificazione completa della release: matrice browser/accessibilità/carico
  e prove di recupero legate alla stessa versione.
- Completare backup automatico e recupero del servizio: destinazione Backblaze
  scelta, servizio installato e prima copia corrente verificata; timer da
  attivare dopo le prove di recupero e margine disco in caso di errore.
  La conservazione cloud resta da definire. Il checkpoint manuale del 3 ottobre
  non era atomico tra catalogo e ledger; la nuova cattura del 15 ottobre usa
  i lock delle pipeline. Il preflight memoria PC del
  3 ottobre ha misurato 2.378.674.176 byte disponibili, sotto il minimo richiesto
  di 2.415.919.104; impostazioni invariate, seed fermo, nessun runtime avviato.
  Restano decisione del proprietario sulle risorse per la prova isolata,
  ciclo reale runtime/refresh/importer e verifica di recupero di configurazione,
  credenziali e certificati inclusi nella nuova cattura.
- Alert effettivamente recapitati e obiettivi di recupero.
  Email, destinatario e Jacopo come referente iniziale confermati (15 ottobre).
  Richiesta di attivazione UptimeRobot autorizzata e inviata alle 13:49:32 UTC,
  HTTP 200; questa risposta non prova recapito o creazione del monitor.
  Serve la conferma di Jacopo nell'email; poi verifica della configurazione
  e prova concordata. Il monitor proposto copre la raggiungibilità;
  refresh fallito e dati vecchi richiedono copertura ulteriore.
  Le unità NLA non hanno `OnFailure`; entrambi i timer hanno `Persistent=no`.
- Funzioni ulteriori: ordinamenti diversi dal GID, filtri lingua/condizione/finish,
  migliore copertura dei dati non singole. Sono backlog, non difetti dimostrati.
- «Altre stampe di questa carta»: idea documentata, implementazione da autorizzare.
- Apertura pubblica senza password: decisione separata di Jacopo, ancora assente.

Il sistema non va considerato privo di sync solo perché le issue #11/#13 sono
aperte; allo stesso modo, il successo operativo non chiude automaticamente #15/#16
o rende verde la CI. Non è documentato un percorso webhook completo in esercizio:
l'automazione accettata è quella dei timer Bulk/importer.

## Da leggere per lavorare

1. [Fotografia e inventario](evidence/STATE-2026-09-30.md).
2. [Priorità e criteri di accettazione](ROADMAP-EXECUTION.md).
3. [Passaggio di consegne PM](PM-HANDOFF.md).
4. [Decisioni e autorizzazioni](DECISIONS.md).
5. [Runbook operativo e recupero](OPERATIONS-RUNBOOK.md).

La [cronologia completa fino al 29 settembre](STATUS-HISTORY-20260929.md)
è conservata senza riscritture. I suoi blocchi “current”, “blocked” e “next”
descrivono momenti storici; non autorizzano a riavviare attività concluse.
