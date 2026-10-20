# Roadmap di esecuzione NLA

Aggiornata il 20 ottobre 2026, sotto la roadmap #3 e il workstream PM #34.
La fase di bootstrap è chiusa operativamente. Questa roadmap ordina manutenzione,
consolidamento e possibili sviluppi. L'obiettivo di manutenzione autorizza
verifiche e preparazione reversibile; MAIN/password, GitHub e decisioni riservate
mantengono i vincoli registrati in [DECISIONS](DECISIONS.md).

**Fase di manutenzione conclusa il 18 ottobre 2026.** Verificati i cinque
requisiti dell'obiettivo, con riuso delle prove e spot-check manuale finale
PDP/carrello stretto. Restano esercizio ordinario, consegna GitHub riattivata
e backlog separato. [Chiusura e limiti](evidence/MAINTENANCE-CLOSURE-2026-10-18.md).

**Priorità del sito prima del lancio pubblico, confermata il 20 ottobre:** prima
dell'apertura vanno completati tre workstream: modifiche alla home, aggiunta di
funzionalità e aggiunta di sezioni del sito non dedicate alla vendita. Contenuti,
funzionalità specifiche e criteri di completamento sono ancora da definire con
Jacopo; non sono fissate scadenze né una nuova fase numerata. L'apertura pubblica
viene dopo questi lavori; la password resta attiva. La Fase 2 resta chiusa e la
manutenzione ordinaria procede separatamente.
[Decisione e perimetro](DECISIONS.md#d-029--home-funzionalità-e-sezioni-prima-del-lancio).

Lo stile Arena con logo esistente e accenti neon è stato pubblicato da Jacopo
il 19 ottobre: tema MAIN `210350735628`, precedente `175195881740` non pubblicato
e conservato per rollback. La tipografia provvisoria del 18 ottobre è uno stato
storico, superato dalla direzione Arena approvata e applicata.
[Pubblicazione verificata](DECISIONS.md#d-028--stile-arena-pubblicato).

**Verifica operativa del 20 ottobre, 08:28 UTC:** il ciclo nuove uscite è
completo e il catalogo aggiornato. `/readyz` 200; `/opsz` resta 503 per
`backup_attention`, mentre la precedente segnalazione `market_incomplete`
è superata. Il backup automatico odierno è fallito (`checkpoint_failed`);
ultimo completo il 19 ottobre. Diagnosi della causa interna e correzione
restano manutenzione prioritaria prima dell'apertura.
[Esito e prove](evidence/OPERATIONAL-CHECK-2026-10-20.md).

Dal 17 ottobre le azioni GitHub erano sospese su richiesta del titolare fino
alla sua comunicazione dopo l'intervento sul budget ([D-024](DECISIONS.md#d-024--rinvio-github-fino-allintervento-sul-budget)).
Dal 19 ottobre D-027 supera il rinvio per i tentativi settimanali autorizzati:
martedì alle 09:00 Europe/Rome, fino al primo completamento riuscito.
Il 20 ottobre D-030 autorizza la ripresa immediata dopo il passaggio della
repository a pubblica. Nessun acquisto di minuti o modifica alla fatturazione.
Le integrazioni e le issue riconciliate sono nella
[ricevuta finale](evidence/GITHUB-DELIVERY-2026-10-20.md); #117 e #101 chiudono
il pacchetto con controlli sul rispettivo head finale. Il backlog futuro resta
distinto dalla consegna del lavoro già completato.

Priorità ribadita da Jacopo: semplificare e ridurre i token. La
[pagina di stato](STATUS-CURRENT.md) riassume disponibile, mancante e prossimo
passo; le prove già valide non si ripetono. La preparazione retention descritta
sotto resta un'opzione locale, senza imporne lo sviluppo o il rilascio per
chiudere la fase: servono le garanzie operative, con il percorso più semplice.

## Risultato acquisito

**Nuovo checkpoint 18 ottobre:** primo backup schedulato dopo il rollout
observer riuscito dalle 01:00:12.349412 alle 01:01:33.023983 UTC
(80,674571 s), `read-data` PASS. Invocation
`451709267d414947a38d89b30f5af628`, job
`backup-7f89aeb859744c7e933aab3c724e7b16`, snapshot
`9fc4fe1143bd0e9048f91ff23ca6d4d517cad300238acc42a94f5f29b0c75d5e`.
Il manifest remoto da 198.901 byte, SHA-256
`aa3337d919cb10a4c5a278a4093ec9c10adbc4660a0637efcccfc7ecaf67faad`, è legato
alla ricevuta e verifica i pin del package observer `319ca0b` e della sua unità.
Il primo backup automatico e la verifica dei materiali runtime/TLS sono conclusi.
Il drill applicativo isolato è chiuso: `current` PASS (04:42:55.573467–05:02:30.871598
UTC, 1.175,298131 s, 10 richieste) e `previous` PASS (05:03:13.812059–05:22:46.065102
UTC, 1.172,253043 s, 10 richieste). Entrambi i runtime si sono chiusi 45m29s dopo
il download, esclusa la pulizia. Alle 05:26:27.145572 UTC sono stati rimossi 765
file e 104 directory (3.931.679.750 byte, solo percorsi restored/catalog); ricevuta
`deletion_complete`, journal `Deactivated successfully` e 13.750.943.744 byte liberi.
Le evidenze sono conservate. RPO proposto 36 h in
esercizio regolare; RTO proposto 2 h su Linux pronto con accessi disponibili.
Host vuoto, provisioning e percorso pubblico restano limiti, non nuovi gate.
[Recovery applicativo](evidence/RECOVERY-APPLICATION-2026-10-18.md) ·
[Backup](evidence/BACKUP-SCHEDULED-2026-10-18.md) ·
[QA e limiti](evidence/QA-REMAINING-2026-10-18.md) ·
[Alert](evidence/ALERT-DELIVERY-2026-10-18.md).

Il catalogo, la ricerca per gioco e famiglia, i suggerimenti delle singole,
i filtri presenti e gli aggiornamenti automatici sono operativi secondo le prove
del 28 e 29 settembre. Il passaggio al tema principale è stato autorizzato ed
eseguito il 29 settembre alle 19:20 Europe/Rome. Password attiva e PowerTools invariato.

La [fotografia](evidence/STATE-2026-09-30.md) definisce il punto di partenza.
Non occorre ripetere bootstrap, acquisizioni, cicli terminali o audit già accettati.

Delta locale successivo al rinvio GitHub: dry-run cloud 17 ottobre 09:47 UTC
completato; la regola 7/4/6 confligge con uno snapshot di prova, escluso per ID.
Zero candidati effettivi, nessuna retention automatica attivata.
[Piano e protezioni](evidence/CLOUD-RETENTION-2026-10-17.md).
Il precedente preflight PC non è un prerequisito del drill applicativo corrente;
RPO/RTO e limiti sono aggiornati nel [checkpoint recovery](evidence/RECOVERY-APPLICATION-2026-10-18.md).

Prova HTTPS delle 10:06 UTC PASS: 54 richieste, incluse 40 letture a massimo
due concorrenti; P95 131,128 ms dalla VPS verso il nome pubblico. Invarianti
live preservati. La prova soddisfa il carico controllato limitato previsto
dall'obiettivo; la capacità massima non è misurata e non è un requisito. Si
riutilizzano i flussi Shopify storici e le prove del componente. Lo spot-check
mobile è documentato dalle immagini del proprietario di PDP e carrello stretto.
[Risultato e limiti](evidence/PUBLIC-GATEWAY-2026-10-17.md).

Preparazione locale retention (commit locale `aa2ffe5`): validatore puro di piano e protezioni pronto,
154 test mirati PASS; prova restic sintetica delle 10:23 UTC con rimozione
esatta, compattazione, `read-data` e ripristino di tutte le copie protette PASS.
[Evidenze](evidence/RETENTION-PLANNER-2026-10-17.md). È ora preparato localmente
anche l'esecutore con lock del backup, ricevute e protezioni: 256 test congiunti
PASS, review indipendente. Restano prova nativa, compattazione, schedulazione
e policy da confermare; nessun componente è installato o attivato per cancellare
snapshot cloud. [Prove dell'esecutore](evidence/RETENTION-EXECUTOR-2026-10-17.md).
La suite generale locale non è verde: dopo 1.712 test riusciti si arresta su
un errore Windows al rename in un test preesistente. Prima di integrare o
distribuire il delta resta necessaria la validazione completa.

## Delta operativo — 15–17 ottobre

La correzione market è stata applicata il 15 ottobre alle 10:17:47 UTC e verificata
alle 10:18:11 UTC. Dopo la correzione, i cicli market del 15 ottobre alle 14:00 UTC
e del 16 ottobre alle 02:00 UTC sono terminati con successo; l'ultima sorgente è
stata acquisita alle 03:00 UTC. Alle 11:45 UTC refresh e market risultavano
`inactive/success`, con pointer/generazioni protette invariati. La PR #112 è ora
pronta per la revisione, con CI verde. [Evidenza](evidence/MARKET-SOURCE-2026-10-15.md).

I risultati CI/CodeQL e lo stato runtime del 3 ottobre sono storici. Il ciclo market e i controlli live del 15–16 ottobre sono riportati sopra. Backup e prove alert/carico sono conclusi; lo stato UptimeRobot `/opsz` è owner-attestato, senza nuova ispezione diretta richiesta. Entrambi i runtime e la pulizia isolata sono conclusi. Gli screenshot del proprietario documentano scheda e carrello desktop, con rimozione owner-attestata; le immagini successive documentano PDP e carrello stretti e ne confermano la coerenza. Alla chiusura del 18 ottobre font e dimensioni erano provvisori, senza nuovo gate grafico ([prova e limiti](evidence/QA-REMAINING-2026-10-18.md)); dal 19 ottobre è pubblicato lo stile Arena. Per la chiusura della manutenzione non erano richiesti un QA completo né un benchmark massimo.

La [prova cifrata S3 del 15 ottobre](evidence/BACKUP-ENCRYPTION-2026-10-15.md)
ha verificato il checkpoint storico del 3 ottobre. Al 18 ottobre il backup
completo più recente è il job `backup-7f89aeb859744c7e933aab3c724e7b16`,
con `read-data` PASS, snapshot
`9fc4fe1143bd0e9048f91ff23ca6d4d517cad300238acc42a94f5f29b0c75d5e`. Il primo
ciclo automatico, invocation `451709267d414947a38d89b30f5af628`, è terminato
alle 01:01:33 UTC; manifest remoto verificato con SHA-256
`aa3337d919cb10a4c5a278a4093ec9c10adbc4660a0637efcccfc7ecaf67faad`, inclusi i
pin del package observer e della sua unità. Prossimo timer 19 ottobre 01:00 UTC.
Il drill applicativo isolato del 18 ottobre ha entrambi i runtime PASS e la pulizia
conclusa ([evidenza](evidence/RECOVERY-APPLICATION-2026-10-18.md)).
Host vuoto non coperto; l'immagine era disponibile dall'archivio. Runtime live e health `/opsz` operativi; la configurazione di
cattura copre health, ma il nuovo observer non è nella copia delle 08:18.
Alla verifica delle 08:18 del 17 ottobre restavano da coprire errori/
anzianità backup; il rollout PR #114 ha aggiunto questa copertura. Recapito email
TEST DOWN/UP email verificato il 18 ottobre; monitor `/opsz` UP owner-attestato
e GET/HEAD indipendenti 200. Lo staging del job fallito
del 16 ottobre è stato rimosso esattamente dopo quarantine e review indipendente.
[Evidenza storica](evidence/BACKUP-AUTOMATION-2026-10-15.md). Il 17 ottobre
la PR #114 (head `319ca0ba046715b769eda97af3e18fad906d6bc2`, pubblicato 09:14 UTC)
aggiunge al codice l'osservabilità di failure backup, confronto fra `last-success`
e ricevuta immutabile per-job, validazione dei campi snapshot (senza interrogazione
remota), checkpoint <26 h, staging residuo e timer abilitati/attivi.
La soglia 26 h è un alert di freschezza, non un RPO. L'esecuzione in memoria,
read-only e senza scritture di stato native alle 09:17:08.775623 UTC è PASS;
rollout riuscito: package `/opt/nla-operational-observer-319ca0b` e nuova unità
installati; due osservazioni healthy e GET/HEAD loopback e pubblico PASS.
La verifica read-only delle 09:28:04.384413 UTC registra 13.244.923.904 byte
liberi e market/refresh/backup inattivi con esito success; i relativi timer,
come il nuovo observer timer, sono enabled/active/waiting. Nessun backup manuale:
il primo ciclo automatico del 18 ottobre ha incluso il nuovo observer, come
attestato dal manifest verificato sopra. Recapito email TEST DOWN/UP
verificato il 18 ottobre alle 00:52 UTC; monitor su `/opsz` e UP confermato da Jacopo.
[Prova email](evidence/ALERT-DELIVERY-2026-10-18.md) · [Evidenza health/backup](evidence/BACKUP-HEALTH-2026-10-17.md).


## Stato GitHub verificato — 16 ottobre

Checkpoint storico, superato per lo stato delle PR dalla
[consegna del 20 ottobre](evidence/GITHUB-DELIVERY-2026-10-20.md).

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
Al checkpoint del 16 ottobre PR #112 e #113 erano draft. Il 17 ottobre #112,
#113 e #114 sono state rese pronte per la revisione, con CI/CodeQL verdi e prove
operative documentate; restano non fuse, insieme a #100 e #101. La lettura dei metadati
non attesta CI nuova; i risultati CI delle nuove PR sono nelle evidenze dedicate. Il checkpoint documentale pubblicato precedente della PR #101 era `b6ab98e618b0867f875b97ccf6d6854359a826d0`, con CI `38819024906` e CodeQL `38819025033` completati con esito positivo alle 22:56 UTC. Il head finale e i controlli del delta attuale sono da seguire nei metadati della PR #101.

## Ordine di lavoro proposto

| Priorità | Attività | Responsabile della fase | Criterio di accettazione | Vincolo |
| --- | --- | --- | --- | --- |
| Consegna #101 | Consolidare la documentazione e registrare i limiti delle prove | PM Codex | Stato, roadmap, decisioni e fonti coerenti; cronologia preservata; [verifica finale](evidence/MAINTENANCE-CLOSURE-2026-10-18.md) | #34 chiusa dalla consegna documentale dopo controlli finali e revisione |
| P1 | Gestire la segnalazione corrente sui backup e mantenere le garanzie operative | PM; Jacopo referente iniziale degli alert | Market e refresh completi; `/readyz` 200 ma `/opsz` 503 per `backup_attention` il 20 ottobre. [Verifica](evidence/OPERATIONAL-CHECK-2026-10-20.md) | Recapito TEST già verificato; nessuna nuova simulazione di incidente o soppressione dell'alert |
| P1 | Mantenere lo spazio VPS | PM per verifica; retention ordinaria sulla VPS | Pulizia legacy 3,65 GB verificata; corrente/precedente e reference protetti; controllo Codex attivo, calendario salvato domenica 09:00 Europe/Rome (D-027) | Retention ordinaria dopo i refresh distinta dal controllo Codex; riserva 6 GiB solo pre-cattura, nessuna garanzia sul picco. [Prove](evidence/RETENTION-2026-09-30.md), [incidente](evidence/INCIDENT-2026-10-03.md) |
| Ripresa — D-030 | Chiudere i residui GitHub con review e controlli sul head finale | Autori e reviewer indipendenti | Nuovi workflow attivi; integrazioni e SHA nella [ricevuta](evidence/GITHUB-DELIVERY-2026-10-20.md) | Nessun deploy o modifica di visibilità; eliminare solo l'automazione GitHub al successo completo |
| Completato nell'ambito previsto | Chiudere le sole celle QA mancanti | PM coordina prove circoscritte | Fixture/browser, axe componente e carico controllato riutilizzati; flussi Shopify storici conservati; spot-check manuale PDP/carrello stretto documentato e revisionato. [Copertura e limiti](evidence/QA-REMAINING-2026-10-18.md) | La tipografia allora provvisoria non aggiungeva gate. Immagini statiche, nessun checkout o certificazione dell'intero tema. Accessibilità completa e down/stale live restano limiti, non nuovi gate |
| Completato | Drill applicativo isolato e cleanup delle sole copie temporanee | PM | `current` e `previous` PASS; 765 file/104 directory rimossi, ricevuta `deletion_complete`; evidenze conservate. [Checkpoint e limiti](evidence/RECOVERY-APPLICATION-2026-10-18.md) | RPO proposto 36 h in esercizio regolare; RTO proposto 2 h su Linux pronto con accessi. Host vuoto e percorso pubblico fuori prova. Copie cloud protette, rotazione opzionale |
| Prima del lancio | Modificare la home nello stile Arena | Jacopo definisce i contenuti; PM coordina | Modifiche e criteri di completamento da definire | Nessun contenuto o scadenza inventato |
| Prima del lancio | Aggiungere funzionalità al sito | Jacopo definisce le funzionalità; PM coordina | Elenco e criteri di completamento da definire | Il backlog P3 non viene automaticamente incluso |
| Prima del lancio | Aggiungere sezioni non dedicate alla vendita | Jacopo definisce le sezioni; PM coordina | Sezioni, contenuti e criteri di completamento da definire | Nessuna sezione specifica già decisa |
| Dopo i tre workstream | Valutare il lancio pubblico | Jacopo decide; PM prepara il pacchetto | Lavori su home, funzionalità e sezioni completati; decisione su rimozione password e rischi residui | Nessuna autorizzazione attuale alla rimozione password |
| P3 | Migliorare filtri e ordinamenti | Workstream #10, da pianificare | Contratto dati/UX approvato e prove su campioni verificati | Lingua, condizione, finish e altri sort non sono dichiarati disponibili |
| P3 | Progettare “Altre stampe di questa carta” | PM per fattibilità; autore da assegnare | Identità canonica affidabile, gruppo completo, link Shopify, preview tastiera/mobile | È autorizzata solo la documentazione |
| P3 | Migliorare copertura e gestione eccezioni importer/non singole | Workstream #97 e dati | Misurare mapping mancanti/ambigui, copertura per gioco/famiglia e report di quarantena | Mai identità per titolo o prezzi inventati |

P1 indica priorità di manutenzione; la segnalazione corrente sui backup è
registrata nella verifica del 20 ottobre. Non sono inventate
scadenze o assegnazioni ad altre persone. La cella mobile prevista è documentata
con le immagini del proprietario di PDP e carrello stretto, nei limiti dichiarati.
Il riferimento ai font provvisori appartiene alla chiusura del 18 ottobre:
lo stile Arena è stato approvato e pubblicato il 19 ottobre.
I limiti senza gate confermato non ampliano il perimetro.

## Consegna GitHub ripresa il 3 ottobre

Procedura storica riattivata da D-027 per i tentativi settimanali del 19 ottobre,
poi da D-030 per il completamento immediato nella repository pubblica.
Al completamento del pacchetto #117/#101 eliminare esclusivamente l'automazione
GitHub. La manutenzione VPS e questa chat rimangono attive.

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
Il restyling Arena successivamente autorizzato è stato preparato su una copia
non pubblicata e pubblicato da Jacopo il 19 ottobre. Il MAIN attuale è
`210350735628`; `175195881740` è il precedente tema conservato per rollback.
Per i nuovi lavori identificare la copia non pubblicata prima di modificarla,
rispettando i vincoli tecnici degli strumenti. La pubblicazione di Arena non
autorizza la rimozione della password.

La [roadmap storica](ROADMAP-HISTORY-20260929.md) è conservata integralmente.
Il suo precedente percorso di attese non è la roadmap attiva.
