# Stato attuale del progetto NLA

Aggiornato il 3 ottobre 2026. PM della fase: Codex, incaricato da Jacopo.
Workstream documentale [#34](https://github.com/cajopo/nla-catalog-gateway-staging./issues/34), roadmap [#3](https://github.com/cajopo/nla-catalog-gateway-staging./issues/3).

L'obiettivo operativo della chat «Esegui bootstrap e audit NLA» è raggiunto.
Il catalogo usa il tema principale dal 29 settembre, ore 19:20 Europe/Rome.
Il negozio resta protetto da password. Il 3 ottobre Jacopo ha revocato il rinvio
della consegna GitHub e ha chiesto di capire e correggere l'errore, poi riprendere
la consegna. Nessuna PR è stata ancora fusa. Recovery VPS conclusa alle 07:29:11
UTC; il refresh ordinario read-only successivo è terminato exit 0 alle 09:12:19.
Freschezza, pointer e readiness sono passati; runtime `af366c05…` è attivo senza
OOM. Vedi [incidente](evidence/INCIDENT-2026-10-03.md) e
[ripresa GitHub](evidence/GITHUB-RESUME-2026-10-03.md).

Questa pagina riassume lo stato; la [fotografia del 30 settembre](evidence/STATE-2026-09-30.md)
contiene inventario, limiti delle prove, versioni e riconciliazione con GitHub.
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
| Backup e recupero | Nuovo checkpoint privato PC acquisito e restaurato offline con esito PASS; seed precedente preservato e fermo, runtime PC mai avviato, nessun RTO completo né backup automatico/durevole | [Checkpoint e restore PC 3 ottobre](evidence/BACKUP-PC-2026-10-03.md); prove storiche: [PC](evidence/RECOVERY-PC-2026-10-01.md), [reference](evidence/REFERENCE-RECOVERY-2026-10-01.md), [Linux](evidence/RECOVERY-LINUX-2026-09-30.md) |
| QA componente | Matrice 21/21 in Chrome, Firefox e WebKit; smoke touch 390×844 e retry dopo 503 simulato sulla fixture; axe zero violazioni, un incomplete di contrasto valutato manualmente nello stato coperto | Solo fixture congelata; non certifica Shopify/mobile reale, Safari/iOS, screen reader, outage gateway o freschezza. Dettagli: [QA](evidence/MAINTENANCE-2026-09-30.md#qa-sul-sorgente-congelato); ricevuta privata in `../output/nla-recovery/20260930/evidence/qa-touch-down-final/index.json` |
| Sicurezza | Confine Shopify App Proxy autenticato; gateway e refresh in sola lettura | Architettura #17 e prove del servizio |
| Tema | 175195881740 principale; 175194898700 conservato per ripristino; password attiva | [Ricevute del passaggio](workstreams/ws-12-release-readiness-20260929.md) |

## Cosa resta aperto

- Consolidamento dei rami e consegna GitHub con CI/CodeQL sul commit finale,
  review indipendente e aggiornamento delle issue: autorizzato a riprendere il 3 ottobre,
  ancora da completare.
- Certificazione completa della release: matrice browser/accessibilità/carico
  e prove di recupero legate alla stessa versione.
- Completare backup automatico/destinazione durevole e recupero del servizio:
  checkpoint PC e restore offline sono verificati, ma non sono una copia atomica
  catalogo+ledger né un backup automatico/durevole. Il preflight memoria PC del
  3 ottobre ha misurato 2.378.674.176 byte disponibili, sotto il minimo richiesto
  di 2.415.919.104; impostazioni invariate, seed fermo, nessun runtime avviato.
  Restano decisione del proprietario sulle risorse per la prova isolata,
  ciclo reale runtime/refresh/importer, destinazione durevole, credenziali e
  certificati, che richiedono procedure dedicate.
- Alert effettivamente recapitati, referente operativo e obiettivi di recupero.
  Email scelta dal proprietario; indirizzo e servizio di invio ancora da verificare.
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
