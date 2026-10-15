# Roadmap della manutenzione NLA

Aggiornata il 15 ottobre 2026, sotto la roadmap #3 e il workstream PM #34.
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

## Delta operativo — 15 ottobre

La correzione market è stata applicata alle 10:17:47 UTC e verificata alle
10:18:11 UTC. Market è sbloccato e attende il timer; nessun nuovo ciclo è stato
avviato. Il refresh ordinario era già concluso alle 04:38:51 UTC e non è stato
toccato. Non è attestato un nuovo ciclo market completo. La PR #112 è draft,
non merged, con CI verde e 4.108 test per ciascuna versione Python riportata
nell'[evidenza](evidence/MARKET-SOURCE-2026-10-15.md).

I run CI/CodeQL e lo stato runtime del 3 ottobre restano storici; gli head PR
correnti verificati in modalità metadata-only sono registrati sotto. Questa
lettura non prova un ciclo market successivo. Restano aperte le lacune
backup/recupero, QA completa e alert/referente descritte sotto.

La [prova cifrata S3 del 15 ottobre](evidence/BACKUP-ENCRYPTION-2026-10-15.md)
ha verificato il trasferimento e il recupero del checkpoint del 3 ottobre con
restic. Il pilota manuale già riuscito non va ripetuto: il primo backup completo
dei dati correnti è ora passato, come descritto sotto. Attivazione periodica,
recupero del runtime e custodia indipendente della password restano aperti.
Il codice del nuovo job è nella PR #113 in bozza, con CI Linux verde e review
indipendente; [evidenza del backup automatico](evidence/BACKUP-AUTOMATION-2026-10-15.md).
Il trasferimento delle credenziali è stato autorizzato (D-021) e l'installazione
verificata. Primo backup corrente completato alle 13:30:23 UTC, controllo
integrale passato e staging rimosso. Restano recupero applicativo e verifica
del margine disco per trasferimenti lunghi/falliti; timer ancora disabilitato.

## Stato GitHub verificato — 15 ottobre

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
non attesta CI nuova; i risultati CI delle nuove PR sono nelle evidenze dedicate.

## Ordine di lavoro proposto

| Priorità | Attività | Responsabile della fase | Criterio di accettazione | Vincolo |
| --- | --- | --- | --- | --- |
| P1 | Consolidare la documentazione e registrare i limiti delle prove | PM Codex | Stato, roadmap, decisioni e fonti coerenti; cronologia preservata; controlli documentali ripetibili | Questo intervento; #34 resta aperta fino alla consegna prevista |
| P1 | Completare le garanzie operative e chi interviene in caso di errore | PM; Jacopo referente iniziale degli alert | Jacopo ha confermato email ricevuta/attivata e login; pacchetto health preparato e verificato ma inerte. [Stato e prove](evidence/OPERATIONAL-HEALTH-2026-10-15.md) | Monitor UptimeRobot non verificato per blocco della verifica URL in Computer Use; proxy e inventario backup non aggiornati, recapito non collaudato |
| P1 | Mantenere lo spazio VPS | PM per verifica; retention ordinaria sulla VPS | Pulizia legacy 3,65 GB verificata; retention refresh 3 ottobre completata, corrente/precedente e reference protetti; controllo Codex ogni 48 ore attivo | Riserva 6 GiB solo pre-cattura; nessuna garanzia sul picco. [Prove](evidence/RETENTION-2026-09-30.md), [incidente](evidence/INCIDENT-2026-10-03.md) |
| P1 | Chiudere i residui GitHub con review e controlli sul head finale | Autori dei workstream e reviewer indipendenti | Consegna principale #108 fusa il 4 ottobre; #100 e #101 aperte; #112, #113 e #114 draft. CI e CodeQL verdi sui head pubblicati #101, #113 e #114 registrati nell'[handoff](PM-HANDOFF.md) | Nessun merge dei residui attestato; aggiornamenti locali sugli alert ancora da consegnare. Code review e CI non sostituiscono i gate operativi |
| P2 | Completare la certificazione QA della release | QA indipendente da assegnare | Fixture Chrome/Firefox/WebKit 21/21 per motore; axe qualificato; errore HTTP del cursore provato e 40 richieste di carico passate sulla copia restaurata; restano Shopify E2E/mobile/a11y/guasto-freschezza/carico produzione | [Prova e limiti](evidence/RECOVERY-LINUX-2026-09-30.md); riutilizzare prove valide, sessione negozio da sbloccare |
| P1 | Completare recupero fuori VPS | PM, operatore continuativo da assegnare | Primo backup completo corrente su Backblaze concluso il 15 ottobre alle 13:30 UTC con controllo integrale passato; [prova](evidence/BACKUP-AUTOMATION-2026-10-15.md). Timer ancora disabilitato | Restano recupero applicativo isolato, capacità, runner aggiornato, conservazione e custodia indipendente della password. Il nuovo componente health richiede l'aggiornamento dell'inventario; non è coperto dallo snapshot precedente |
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
