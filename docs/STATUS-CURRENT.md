# Stato attuale del progetto NLA

Aggiornamento operativo del 17 ottobre 2026; fotografia generale del 3 ottobre.
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
Il primo ciclo market post-fix, run `market-20261015t140020z-69980f6a`, è
terminato alle 14:49:19 UTC con `draft_cycle_complete`: 2.438 espansioni
completate, 257.154 blueprint, zero differiti e zero tentativi di creazione;
nessuna nuova stampa idonea selezionata. L'indice non è stato aggiornato perché
non c'erano cambiamenti importer e quello esistente era fresco. Alle 14:50:42 UTC
entrambi i servizi erano inattivi e il refresh delle
15 UTC pronto; spazio libero 10.244.165.632 byte, generazioni corrente e
precedente invariate. Esito documentato in
[incidente market](evidence/MARKET-SOURCE-2026-10-15.md).

Il successivo refresh ordinario `20261015t150018z-a6b95321` è terminato con
successo alle 16:36:34 UTC. Il controllo delle 16:40:10 conferma ricevuta,
last-success e manifest attivo coerenti; retention eseguita, nessuna directory
prevista ancora da rimuovere e soltanto corrente/precedente conservate.
Spazio libero 10.245.189.632 byte; entrambi i servizi inattivi con esito positivo.
Il parser `nsfs` corretto ha superato il controllo nativo completo in sola
lettura. Due container smoke del 17 settembre erano già stati rimossi
separatamente; poi il vecchio drill è stato messo in quarantena, con tre
container rimossi e due payload cancellati dopo lo smoke PASS (10 richieste,
6 controlli) sulla generazione live `ae3be49c…` alle 21:57:13 UTC. La ricevuta terminale del
15 ottobre alle 21:58 UTC verifica la cancellazione; la retention successiva è
coerente, con 13.795.237.888 byte liberi e le generazioni corrente/precedente
protette. [Dettagli e ricevute](evidence/BACKUP-AUTOMATION-2026-10-15.md).


Questa pagina riassume lo stato; la [fotografia del 30 settembre](evidence/STATE-2026-09-30.md)
contiene inventario, limiti delle prove, versioni e riconciliazione con GitHub.
Il 15 ottobre è riuscita anche la [prova di backup cifrato S3](evidence/BACKUP-ENCRYPTION-2026-10-15.md):
checkpoint del 3 ottobre trasferito, controllato integralmente e recuperato su PC
con hash identico. Era la prova sul checkpoint storico; il successivo primo
backup completo corrente è descritto sotto. Restano verifica del primo ciclo
automatico, conservazione e custodia indipendente delle chiavi.
Il codice del backup automatico è nella [PR #113](https://github.com/cajopo/nla-catalog-gateway-staging./pull/113).
Il backup completo più recente è del 17 ottobre alle 07:16 UTC: job
`backup-c121a380661d4bbfa6b6c0c5de1a09b4`, `read-data` e gate PASS, snapshot
`bd249a0d8064bd950a2ef6ddb37eb9329c36eec2101491884d0c8cd794e42963`. Timer
attivo, enabled per le 01 UTC con prossimo trigger il 18 ottobre alle 01 UTC;
la prima esecuzione automatica non è ancora stata osservata. Il restore da host
vuoto resta non provato perché l'immagine era già residente. Il runtime live è
operativo, il componente health resta inerte. [Prove e limiti](evidence/BACKUP-AUTOMATION-2026-10-15.md).
PR #113 e #114 hanno i controlli riportati nell'[handoff PM](PM-HANDOFF.md).
Il precedente checkpoint documentale pubblicato della PR #101 era `4cae6c7c6c84a00a64c3ca286eba1b4963bea643`, con CI `38920068601` e CodeQL `38920068523` riusciti il 16 ottobre. Il nuovo head e i controlli del delta attuale sono da seguire nei metadati della PR #101.
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
| Aggiornamenti — ultimo stato VPS, 17 ottobre | Alle 07:16 UTC refresh e market `inactive/success`; pointer `43476…`, generazioni `3fbd719c` / `5b22aed7` invariate; 13.249.085.440 byte liberi | [Evidenza backup](evidence/BACKUP-AUTOMATION-2026-10-15.md); storico: [incidente](evidence/INCIDENT-2026-10-03.md) |
| Refresh e market — storico 3 ottobre | Run `20261003t073240z-3f7384f8` exit 0; freshness e smoke PASS; dataset `5152b3c3…`. Questo è un esito storico, non lo stato corrente | [Incidente](evidence/INCIDENT-2026-10-03.md) |
| Retention e spazio VPS — 17 ottobre | Quarantena, controllo indipendente e rimozione esatta del vecchio staging `971c`: 743 file, 2.126.986.835 byte; 13.249.085.440 byte liberi al controllo finale | [Pulizia e retention](evidence/BACKUP-AUTOMATION-2026-10-15.md); storico 30 settembre: [retention](evidence/RETENTION-2026-09-30.md) |
| Backup e recupero | Backup completo del 17 ottobre, gate `read-data` PASS e timer abilitato; prima esecuzione automatica ancora da osservare. Restore isolati `current`/`previous` PASS; host vuoto non provato. Componente health inerte; runtime live operativo | [Backup e restore](evidence/BACKUP-AUTOMATION-2026-10-15.md); prove storiche: [Backblaze 3 ottobre](evidence/BACKBLAZE-2026-10-03.md), [checkpoint PC](evidence/BACKUP-PC-2026-10-03.md), [PC](evidence/RECOVERY-PC-2026-10-01.md), [reference](evidence/REFERENCE-RECOVERY-2026-10-01.md), [Linux](evidence/RECOVERY-LINUX-2026-09-30.md) |
| QA componente | Matrice 21/21 in Chrome, Firefox e WebKit; smoke touch 390×844 e retry dopo 503 simulato sulla fixture; axe zero violazioni, un incomplete di contrasto valutato manualmente nello stato coperto | Solo fixture congelata; non certifica Shopify/mobile reale, Safari/iOS, screen reader, outage gateway o freschezza. Dettagli: [QA](evidence/MAINTENANCE-2026-09-30.md#qa-sul-sorgente-congelato); ricevuta privata in `../output/nla-recovery/20260930/evidence/qa-touch-down-final/index.json` |
| Sicurezza | Confine Shopify App Proxy autenticato; gateway e refresh in sola lettura | Architettura #17 e prove del servizio |
| Tema | 175195881740 principale; 175194898700 conservato per ripristino; password attiva | [Ricevute del passaggio](workstreams/ws-12-release-readiness-20260929.md) |

## Cosa resta aperto

- Completare la consegna delle correzioni successive e della documentazione:
  l'integrazione principale della PR #108 è fusa dal 4 ottobre in `90f4f49`;
  le PR #100 (recovery), #101 (PM), #112 (market), #113 (backup) e #114
  (health operativa #13) restano non fuse. #101 aveva CI e CodeQL verdi sul checkpoint documentale precedente `b6ab98e618b0867f875b97ccf6d6854359a826d0` (CI `38819024906`, CodeQL `38819025033`); il head finale e i controlli del delta attuale sono da seguire nei metadati PR #101; #113 e #114 hanno review indipendenti e CI/CodeQL passati
  sui rispettivi head. Il delta documentale locale sugli alert richiederà
  consegna e controlli sul relativo commit; resta la riconciliazione delle issue.
- Certificazione completa della release: matrice browser/accessibilità/carico
  e prove di recupero legate alla stessa versione.
- Completare backup automatico e recupero del servizio: backup completo del 17 ottobre,
  gate `read-data` PASS e timer enabled/waiting; prima esecuzione automatica da osservare
  ([evidenza](evidence/BACKUP-AUTOMATION-2026-10-15.md)). Restore VPS `current`/`previous`
  PASS, host vuoto non provato perché l'immagine era preesistente; runtime di test chiuso,
  live operativo e componente health inerte. Restano margine disco, conservazione cloud,
  custodia chiave e prova della prima esecuzione automatica.
  Il preflight memoria PC del 3 ottobre (2.378.674.176 byte, sotto il minimo
  2.415.919.104) e il seed fermo descrivono quella prova storica PC, non il restore
  VPS. Restano inoltre il ciclo reale runtime/refresh/importer e la verifica di
  recupero di configurazione, credenziali e certificati inclusi nella cattura.
- Alert e obiettivi di recupero. Jacopo ha confermato ricezione dell'email,
  attivazione e accesso alla dashboard. Il monitor UptimeRobot resta da verificare:
  la lettura UI è stata fermata dal blocco tecnico URL di Computer Use, non per
  consenso mancante. Metodo, intervallo e contatto non sono verificati; la sonda
  `/readyz` ha mostrato GET 200 e HEAD 404. Non reinviare email/attivazione.
  [D-022 e procedura](DECISIONS.md#d-022--attivazione-uptimerobot-e-referente-iniziale).
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
