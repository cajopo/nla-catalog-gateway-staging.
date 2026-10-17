# Roadmap della manutenzione NLA

Aggiornata il 17 ottobre 2026, sotto la roadmap #3 e il workstream PM #34.
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

## Delta operativo — 15–17 ottobre

La correzione market è stata applicata il 15 ottobre alle 10:17:47 UTC e verificata
alle 10:18:11 UTC. Dopo la correzione, i cicli market del 15 ottobre alle 14:00 UTC
e del 16 ottobre alle 02:00 UTC sono terminati con successo; l'ultima sorgente è
stata acquisita alle 03:00 UTC. Alle 11:45 UTC refresh e market risultavano
`inactive/success`, con pointer/generazioni protette invariati. La PR #112 resta
draft con CI verde. [Evidenza](evidence/MARKET-SOURCE-2026-10-15.md).

I risultati CI/CodeQL e lo stato runtime del 3 ottobre sono storici. Il ciclo market e i controlli live del 15–16 ottobre sono riportati sopra; restano aperte le lacune backup/recupero, QA completa e verifica del monitor UptimeRobot.

La [prova cifrata S3 del 15 ottobre](evidence/BACKUP-ENCRYPTION-2026-10-15.md)
ha verificato il checkpoint storico del 3 ottobre. Il backup completo più recente
è il job `backup-c121a380661d4bbfa6b6c0c5de1a09b4` del 17 ottobre alle 07:16 UTC,
con `read-data` e gate PASS, snapshot
`bd249a0d8064bd950a2ef6ddb37eb9329c36eec2101491884d0c8cd794e42963`. Il timer è
enabled/waiting per il 18 ottobre alle 01:00 UTC (`Persistent=no`); la prima
esecuzione automatica non è ancora osservata. Restore isolati `current` e
`previous` PASS; host vuoto non provato (`emptyHostRecoveryProven=false`, immagine
già residente). Runtime live operativo e health inerte. Lo staging del job fallito
del 16 ottobre è stato rimosso esattamente dopo quarantine e review indipendente.
[Evidenza](evidence/BACKUP-AUTOMATION-2026-10-15.md).


## Stato GitHub verificato — 16 ottobre

La lettura metadata-only registra PR #108 chiusa e fusa il 4 ottobre 2026 alle
12:16:49 UTC, merge commit `90f4f49bf2094fa2af51dff3a998b82054d93c76`:
[PR #108](https://github.com/cajopo/nla-catalog-gateway-staging./pull/108).
La consegna principale è completata. PR #100 è aperta, non draft e non fusa,
head `7ab94d345511ddd53c362206f041bf4942f1a61a`, base
`agent/staging-warm-activation` (`83b14e45ba20180805b2414f0c7b838041cd8ad7`).
Prima di questa revisione documentale, PR #101 era aperta, non draft e non fusa, head
`55aa1bedcc99d39e7d60ae1f388fa6c5541ebdf4`, base
`agent/refresh-interruption-recovery` (`7ab94d345511ddd53c362206f041bf4942f1a61a`).
Il precedente head #101 `6913748dc1513b29c084db522865386067db241a` è storico.
Il nuovo commit documentale e i suoi controlli sono identificati nella PR #101;
non usare i risultati del precedente head per attestare questa revisione.
PR #112 e #113 sono draft e non fuse secondo le rispettive evidenze market e
backup. I residui #100, #101, #112 e #113 non sono fusi. La lettura dei metadati
non attesta CI nuova; i risultati CI delle nuove PR sono nelle evidenze dedicate. Il checkpoint documentale pubblicato precedente della PR #101 era `b6ab98e618b0867f875b97ccf6d6854359a826d0`, con CI `38819024906` e CodeQL `38819025033` completati con esito positivo alle 22:56 UTC. Il head finale e i controlli del delta attuale sono da seguire nei metadati della PR #101.

## Ordine di lavoro proposto

| Priorità | Attività | Responsabile della fase | Criterio di accettazione | Vincolo |
| --- | --- | --- | --- | --- |
| P1 | Consolidare la documentazione e registrare i limiti delle prove | PM Codex | Stato, roadmap, decisioni e fonti coerenti; cronologia preservata; controlli documentali ripetibili | Questo intervento; #34 resta aperta fino alla consegna prevista |
| P1 | Completare le garanzie operative e chi interviene in caso di errore | PM; Jacopo referente iniziale degli alert | Jacopo ha confermato email ricevuta/attivata e login; pacchetto health preparato e verificato ma inerte. [Stato e prove](evidence/OPERATIONAL-HEALTH-2026-10-15.md) | Monitor UptimeRobot non verificato per blocco della verifica URL in Computer Use; proxy e inventario backup non aggiornati, recapito non collaudato |
| P1 | Mantenere lo spazio VPS | PM per verifica; retention ordinaria sulla VPS | Pulizia legacy 3,65 GB verificata; retention refresh 3 ottobre completata, corrente/precedente e reference protetti; controllo Codex ogni 48 ore attivo | Riserva 6 GiB solo pre-cattura; nessuna garanzia sul picco. [Prove](evidence/RETENTION-2026-09-30.md), [incidente](evidence/INCIDENT-2026-10-03.md) |
| P1 | Chiudere i residui GitHub con review e controlli sul head finale | Autori dei workstream e reviewer indipendenti | Consegna principale #108 fusa il 4 ottobre; #100 e #101 aperte; #112, #113 e #114 draft. CI e CodeQL verdi sui head pubblicati #101, #113 e #114 registrati nell'[handoff](PM-HANDOFF.md) | Nessun merge dei residui attestato; aggiornamenti locali sugli alert ancora da consegnare. Code review e CI non sostituiscono i gate operativi |
| P2 | Completare la certificazione QA della release | QA indipendente da assegnare | Fixture Chrome/Firefox/WebKit 21/21 per motore; axe qualificato; errore HTTP del cursore provato e 40 richieste di carico passate sulla copia restaurata; restano Shopify E2E/mobile/a11y/guasto-freschezza/carico produzione | [Prova e limiti](evidence/RECOVERY-LINUX-2026-09-30.md); riutilizzare prove valide, sessione negozio da sbloccare |
| P1 | Completare recupero fuori VPS | PM, operatore continuativo da assegnare | Backup completo del 17 ottobre, gate `read-data` PASS; restore isolati `current`/`previous` PASS; runtime di test chiuso e live operativo; staging fallito del 16 ottobre rimosso dopo review; [prove](evidence/BACKUP-AUTOMATION-2026-10-15.md) | Host vuoto non provato perché immagine preesistente. Timer abilitato, prima esecuzione automatica da osservare; componente health inerte. Restano margine disco, conservazione e custodia indipendente della password; pacchetto health inerte incluso nella cattura; una futura attivazione richiede aggiornare inventario e backup |
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
