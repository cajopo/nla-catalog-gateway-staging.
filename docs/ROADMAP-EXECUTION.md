# Roadmap della manutenzione NLA

Aggiornata il 3 ottobre 2026, sotto la roadmap #3 e il workstream PM #34.
La fase di bootstrap è chiusa operativamente. Questa roadmap ordina manutenzione,
consolidamento e possibili sviluppi. L'obiettivo di manutenzione autorizza
verifiche e preparazione reversibile; MAIN/password, GitHub e decisioni riservate
mantengono i vincoli registrati in [DECISIONS](DECISIONS.md).

## Risultato acquisito

Il catalogo, la ricerca per gioco e famiglia, i suggerimenti delle singole,
i filtri presenti e gli aggiornamenti automatici sono operativi secondo le prove
del 28 e 29 settembre. Il passaggio al tema principale è stato autorizzato ed
eseguito il 29 settembre alle 19:20 Europe/Rome. Password attiva e PowerTools invariato.

La [fotografia](evidence/STATE-2026-09-30.md) definisce il punto di partenza.
Non occorre ripetere bootstrap, acquisizioni, cicli terminali o audit già accettati.

## Ordine di lavoro proposto

| Priorità | Attività | Responsabile della fase | Criterio di accettazione | Vincolo |
| --- | --- | --- | --- | --- |
| P1 | Consolidare la documentazione e registrare i limiti delle prove | PM Codex | Stato, roadmap, decisioni e fonti coerenti; cronologia preservata; controlli documentali ripetibili | Questo intervento; #34 resta aperta fino alla consegna prevista |
| P1 | Completare le garanzie operative e chi interviene in caso di errore | PM con operatore da assegnare | Inventario svolto il 30 settembre; email scelta, restano recapito, destinatario/referente e backup automatico; [runbook](OPERATIONS-RUNBOOK.md) pronto | Nessun monitor email configurato o messaggio a terzi; controllo spazio Codex attivo, decisioni sul recapito pendenti |
| P1 | Mantenere lo spazio VPS | PM per verifica; retention ordinaria sulla VPS | Pulizia legacy 3,65 GB verificata; retention refresh 3 ottobre completata, corrente/precedente e reference protetti; controllo Codex ogni 48 ore attivo | Riserva 6 GiB solo pre-cattura; nessuna garanzia sul picco. [Prove](evidence/RETENTION-2026-09-30.md), [incidente](evidence/INCIDENT-2026-10-03.md) |
| P1 | Consolidare sorgenti, release e issue GitHub | Autori dei workstream e reviewer indipendente da assegnare | PR #100 e PR documentale #101 hanno head verificati con CI/CodeQL verdi; consolidamento altri workstream e merge ancora aperti | Ogni commit successivo richiede nuovi controlli sul suo head finale; vedere [inventario GitHub](evidence/GITHUB-RESUME-2026-10-03.md) |
| P2 | Completare la certificazione QA della release | QA indipendente da assegnare | Fixture Chrome/Firefox/WebKit 21/21 per motore; axe qualificato; errore HTTP del cursore provato e 40 richieste di carico passate sulla copia restaurata; restano Shopify E2E/mobile/a11y/guasto-freschezza/carico produzione | [Prova e limiti](evidence/RECOVERY-LINUX-2026-09-30.md); riutilizzare prove valide, sessione negozio da sbloccare |
| P1 | Completare recupero fuori VPS | PM, operatore continuativo da assegnare | Nuovo checkpoint PC 3 ottobre ripristinato offline (12 file, 3 DB quick_check); seed precedente preservato, runtime mai avviato; prova non atomica catalogo+ledger e non backup automatico/durevole | Preflight PC alle 09:58:17: 2.378.674.176 byte disponibili contro 2.415.919.104 richiesti; limiti invariati, seed fermo. Runtime/ciclo refresh-importer, credenziali, destinazione durevole e test RTO completo restano aperti. [Checkpoint](evidence/BACKUP-PC-2026-10-03.md) |
| P2 | Valutare il lancio pubblico | Jacopo decide; PM prepara il pacchetto | Decisione su rimozione password, rischi residui e gestione operativa | Nessuna autorizzazione attuale alla rimozione password |
| P3 | Migliorare filtri e ordinamenti | Workstream #10, da pianificare | Contratto dati/UX approvato e prove su campioni verificati | Lingua, condizione, finish e altri sort non sono dichiarati disponibili |
| P3 | Progettare “Altre stampe di questa carta” | PM per fattibilità; autore da assegnare | Identità canonica affidabile, gruppo completo, link Shopify, preview tastiera/mobile | È autorizzata solo la documentazione |
| P3 | Migliorare copertura e gestione eccezioni importer/non singole | Workstream #97 e dati | Misurare mapping mancanti/ambigui, copertura per gioco/famiglia e report di quarantena | Mai identità per titolo o prezzi inventati |

P1 indica priorità di manutenzione, non un incidente aperto. Non sono inventate
scadenze o assegnazioni ad altre persone. Il successivo intervento operativo
è completare le lacune nell'[evidenza del 30 settembre](evidence/MAINTENANCE-2026-09-30.md),
entro il perimetro concordato. L'obiettivo rimane aperto fino alle prove obbligatorie.

## Consegna GitHub ripresa il 3 ottobre

1. Congelare gli attuali sorgenti dei workstream e le ricevute del servizio;
   distinguere codice installato, rami locali e anteprima integrata.
2. Riprodurre l'integrazione già verificata senza perdere warm activation,
   separazione dei pin, test e modifiche del tema.
3. Consegnare una issue, un ramo `agent/*` e una PR per workstream.
4. Eseguire i controlli necessari sul commit finale e ottenere review indipendente.
   Test locali e copertura aggregata non sostituiscono CI/CodeQL sul commit finale.
5. Riconciliare le issue: chiusura operativa, consegna del codice e copertura QA
   hanno significati diversi. Non chiudere in blocco le issue solo perché il sito funziona.

Il dettaglio aggiornato delle PR e delle dipendenze è nella
[ripresa GitHub del 3 ottobre](evidence/GITHUB-RESUME-2026-10-03.md). La ripresa non
autorizza merge con controlli rossi né acquisto di minuti.
Lo stato aggiornato del refresh e la consegna documentale preparata sono
registrati nell'[incidente](evidence/INCIDENT-2026-10-03.md) e nel [passaggio PM](PM-HANDOFF.md).

## Limiti validi per tutta la fase

Gateway e refresh restano in sola lettura; Shopify è autorevole e PowerTools
non viene riconfigurato. L'importer ha solo le eccezioni registrate nelle decisioni.
Il consenso al passaggio del 29 settembre non autorizza ulteriori modifiche al MAIN.
Le nuove modifiche al tema devono partire da una copia non pubblicata, da identificare
prima di lavorare: il vecchio clone 175195881740 è ormai il tema principale.

La [roadmap storica](ROADMAP-HISTORY-20260929.md) è conservata integralmente.
Il suo precedente percorso di attese non è la roadmap attiva.
