# Passaggio di consegne PM NLA

Aggiornato il 17 ottobre 2026. Jacopo ha affidato a Codex il ruolo PM di questa
fase. Riferimenti: master #3, manutenzione documentale #34, architettura #17 e
tassonomia #19, consultati prima dell'intervento.

Jacopo ha ribadito di proseguire autonomamente entro l'obiettivo approvato e di
non ripetere richieste di consenso già risolte: [decisione D-023](DECISIONS.md#d-023--continuità-operativa-entro-lobiettivo-autorizzato).
Raggruppare i passaggi revisionati; distinguere un vincolo tecnico dell'ambiente
da un'autorizzazione del titolare già presente.

## Checkpoint di consegna — 17 ottobre

PR #101: checkpoint documentale `ef53db3`, CI `39017228273` e CodeQL
`39017228183` riusciti. PR #112 (`8657aaa`) e #113 (`b56ca95`) sono ora
pronte per la revisione e non fuse; i rispettivi controlli sono verdi.
La descrizione #112 include il primo ciclo market ordinario riuscito dopo il fix.
L'attivazione health del 17 ottobre è riuscita entro le 08:18 UTC: `/opsz`
verificato, catalogo preservato e nuovo backup `919aed…` completo con `read-data`.
Config backup `54a376a4…`, Caddy `ef4c3fa2…`, timer backup nuovamente abilitato.
Il controllo delle 08:18:54 UTC registra 13.247.131.648 byte liberi e pipeline
riuscite; il primo tentativo era stato annullato con rollback verificato prima
di cambiare Caddy. [Prove e limiti](evidence/OPERATIONAL-HEALTH-2026-10-15.md).
L'attivazione non prova il recapito UptimeRobot o la copertura di errori del backup.
La PR #114 (`59a74e6`) è ora pronta per la revisione, con CI/CodeQL verdi e
descrizione aggiornata all'attivazione. Nessuna PR residua è stata fusa.

Il controllo PC delle 07:51:06 UTC registra 506.658.816 byte di RAM libera
e pipe Docker Desktop assente al controllo: niente prova pesante locale,
niente variazioni a container o limiti. Il recupero su host vuoto resta aperto
per risorse insufficienti; non è in attesa di un nuovo consenso di Jacopo.
La documentazione e le prove dei checkpoint precedenti sotto restano storiche.
Il successivo tentativo Computer Use del 17 ottobre ha negato l'accesso tecnico
a Chrome prima di leggere la dashboard: monitor e recapito restano non verificati,
senza nuove richieste di consenso e senza aggirare il blocco.
Inventario Backblaze delle 08:50 UTC completato: quattro snapshot e copia
manuale presenti, 622.179.661 byte; nessuna cancellazione o lifecycle attivata.
Conservare tutte le copie attuali. [Prove e proposta retention](evidence/CLOUD-RETENTION-2026-10-17.md).

## Punto di partenza

L'obiettivo operativo della chat «Esegui bootstrap e audit NLA» è concluso.
Il 29 settembre alle 19:20 Europe/Rome, dopo «consento», il tema 175195881740
è diventato MAIN. Il precedente 175194898700 è UNPUBLISHED e conservato.
La password resta attiva. PowerTools e dati commerciali non sono stati cambiati
dal passaggio di tema.

Leggere la [fotografia del progetto](evidence/STATE-2026-09-30.md) per ciò che
abbiamo, ciò che manca e le prove disponibili. Lo [stato attuale](STATUS-CURRENT.md)
è il riepilogo; la [roadmap](ROADMAP-EXECUTION.md) contiene le priorità proposte.
La [ripresa GitHub del 3 ottobre](evidence/GITHUB-RESUME-2026-10-03.md) registra
stato delle PR, dipendenze e piano di consegna aggiornati.

## Stato operativo — fotografia storica del 3 ottobre

La recovery VPS è terminata alle 07:29:11 UTC. Il solo refresh ordinario
read-only `20261003t073240z-3f7384f8` è terminato exit 0 alle 09:12:19; freshness
PASS alle 09:15:01, source age 6.124 secondi (1 h 42 min 4 s), smoke 10/10, HTTPS 200 e retention
periodica completata alle 09:15:41. Il runtime `af366c05…` e la relativa readiness sono prove storiche del 3 ottobre;
due generazioni preservate e ledger invariato. Le misure di spazio precedenti
(5.446.959.104 byte alle 07:45 e 5,67 GB) restano alert storici, non valori da
sommare; finale 11.782.266.880 byte. Dati completi in [incidente](evidence/INCIDENT-2026-10-03.md). Questi numeri e
stati PR/runtime descrivono il 3 ottobre e non attestano lo stato corrente.

## Delta market — 15 ottobre

La correzione della cattura CardTrader è stata applicata il 15 ottobre alle
10:17:47 UTC e verificata alle 10:18:11 UTC. Il servizio market è sbloccato e
inattivo in attesa del timer; non è stato avviato un nuovo ciclo al momento del
fix. Il refresh read-only era già terminato alle 04:38:51 UTC e resta intatto.
Il primo ciclo market post-fix `market-20261015t140020z-69980f6a` è terminato
alle 14:49:19 UTC con `draft_cycle_complete`: 2.438 espansioni completate,
257.154 blueprint, zero differiti e zero tentativi di creazione; nessuna nuova
stampa idonea selezionata. Indice non aggiornato: nessuna modifica importer e indice
ancora fresco. Alle 14:50:42 entrambi i servizi erano inattivi, il refresh delle
15 UTC pronto, e lo spazio libero era 10.244.165.632 byte; generazioni corrente
e precedente invariate. Ricevuta e limiti in
[evidenza market](evidence/MARKET-SOURCE-2026-10-15.md).
Alle 15:17:12 UTC il refresh risultava attivo (`activating/start`, senza exit
timestamp); spazio libero 8.988.151.808 byte, pointer e ultima ricevuta del
refresh invariati. Quarantena e restore aspettano che entrambe le unità siano
idle; nessun job è stato riavviato.

Alle 16:21:16 UTC il refresh resta in corso, con 7.185.530.880 byte liberi e
pointer/ultima ricevuta invariati. Preservare anche la terza generazione in
costruzione. I due helper della quarantena sono installati e verificati ma
non eseguiti; nessun residuo è stato spostato o eliminato. Il pacchetto health
è stato preparato e verificato nativamente, con servizi ancora spenti:
[prove e passaggi mancanti](evidence/OPERATIONAL-HEALTH-2026-10-15.md).
La versione allora preparata usava il wrapper read-only da 70 secondi,
pin `789fe358023145d6edec8bd743ba4ad7d5526b780a3000642b6469e213e8090e`:
il file `.inventory.json` conserva gli esatti byte stdout, che diventano
l'autorità per review e SHA. Non usare il precedente flusso `.result.json`
formattato. Questa versione e' storica; la catena v2 qui sotto e' stata superata dal cleanup v3 completato. Non riusare i pin v2 per nuove esecuzioni.

Aggiornamento delle 16:40:10 UTC: il refresh `20261015t150018z-a6b95321` è
terminato alle 16:36:34, con attivazione alle 16:36:31 e sorgente delle 15:00:35.
Ricevuta SHA `9a86cb8027a877481b900382f47a90b3ea68806b2653bfba3a16b926aacd1bf9`,
pointer `ec0946126da6cffe424c1bd5fe38b0f0b8b8aa689dea0872da5427e73b4f4c93`;
corrente `49521a0f…`, precedente `ed078fcd…`. Retention coerente e conclusa,
10.245.189.632 byte liberi. Prova privata:
`retention-20261015T164009Z-4db6bd30/retention_periodic_check_remote.result.json`.

Il primo inventario completo aggiuntivo è stato rifiutato in 9,871 secondi,
senza piano accettato o mutazioni. La diagnosi delle 16:42–16:43 UTC ha isolato
la guardia `container_inventory:241`: il solo container storico `52abaae4…`
usa `0:0`, mentre gli altri due usano `10001:10001`. Tutti gli altri vincoli
osservati coincidono: fermi dal 21 settembre, immagine e nomi fissati, nessun
riavvio automatico, rete isolata, root filesystem read-only, nessuna porta e
solo il mount del vecchio restore. L'eccezione per quel solo ID è stata poi
preparata e revisionata in una versione separata, senza modificare il container
o disattivare gli altri controlli. Prove private:
`inventory-diagnostic-20261015T164224Z-4dc0cb55` e
`old-containers-20261015T164325Z-3ff82905`.

La catena v2 è installata sotto `/var/lib/nla-maintenance/helpers-v2` e ha
superato installazione/probe separati: inventario SHA
`acde202f68b2df31691868cb941dcb89a73b4b9628448e563b5c25354dc59e84`,
quarantena `e55bb3122333b5357648d2ed5bfc8f2b33379f3eefdb92a3687a9a9b0fdf0226`,
wrapper read-only `c5a3c0f9c29754ed134b167abd6aad85752634c63c5b3169886440398d5788bd`.
Il primo tentativo delle 17:00 UTC si è fermato prima di creare il batch:
due ulteriori container di smoke del 17 settembre montavano la cartella padre.
Inventariati e revisionati separatamente, sono stati rimossi per i soli due ID
completi; immagini, directory host e baseline live sono rimaste invariate.
Ricevuta privata `backup-automation-20261015/quarantine-v2-draft/`:
`smoke-container-removal-a2fcf86bb85b48de9d35eaa0a2d31410/remove_old_smoke_containers.result.json`.

Il nuovo inventario delle 17:15:08 UTC, SHA
`160c7c74959794fdf7fa562d57d8bf879120050d2a204109d1e464213fa31211`,
ha passato la review ma è scaduto durante l'attesa delle autorizzazioni tecniche;
il builder ha rifiutato il trasferimento senza creare un receiver. Non riusarlo
come inventario fresco. La successiva esecuzione deve riacquisire i dati e
confrontarli integralmente con il piano approvato, ammettendo solo un diverso
`observedAtUtc`; ogni altra differenza richiede nuova review. Il limite di
600 secondi e i controlli completi sui riferimenti restano invariati.
Il problema del parser v2 `nsfs` e risolto: il controllo nativo
completo read-only e l'orchestrazione v3 hanno completato la quarantena del
vecchio drill. Due container smoke del 17 settembre erano gia stati rimossi
separatamente; poi sono stati rimossi tre container del drill e spostati in
quarantena due payload. Lo smoke di 10 richieste/6 controlli e' PASS sulla
generazione live `ae3be49c...` alle 21:57:13 UTC. La cancellazione esatta dei
payload e' stata verificata il 15 ottobre alle 21:58 UTC; il restore applicativo
isolato resta aperto. La retention post-operazione ha confermato pointer e
manifest coerenti, servizi inattivi con esito positivo, generazioni
corrente/precedente protette e 13.795.237.888 byte liberi.
[Dettagli e ricevute](evidence/BACKUP-AUTOMATION-2026-10-15.md).

La PR #112 è in bozza e non fusa. CI è verde con 4.108 test passati per ciascuna
versione Python indicata nell'evidenza; ciò documenta il codice della PR e non
una nuova esecuzione completa operativa. Per il nuovo stato GitHub delle PR
#101, #113 e #114 vedere la sezione aggiornata sotto; le prove operative sulla
VPS restano distinte dai candidati di codice.

La consegna documentale del 3 ottobre usava un checkout pulito separato (stato storico):
`C:\Users\umbri\.codex\worktrees\nla-pm-incident-docs\nla-catalog-gateway-staging`,
branch `agent/pm-incident-state-20261003`, PR #101 ready for review. Alle 09:54
UTC era verificato il head PR #101 `6913748dc1513b29c084db522865386067db241a` (dato storico, non corrente), basato sul head PR #100
`7ab94d3`. CI #37113804901 e CodeQL #37113804893
passati; 3.885 test e coverage 100% con Python 3.12 e 3.13. Contiene 23 file solo
documentali, incluso `docs/workstreams/ws-09g-refresh-interruption-recovery.md`;
preflight su 210 file e Markdown link check passati. I controlli sono sul head
osservato; ogni commit documentale successivo richiede i propri controlli finali.
Il checkout root
`agent/pm-state-20260930` a `9f4e390` resta la fonte PM storica, non il branch pulito di consegna. Otto
ricevute recovery, 3.009 byte, sono sul PC in
`refresh-recovery-20261003/recovered-receipts`.

Il checkpoint PC privato del 3 ottobre è stato copiato alle 10:11:07 UTC e
restaurato offline con esito PASS; dettagli e limiti in
[BACKUP-PC-2026-10-03](evidence/BACKUP-PC-2026-10-03.md). Il preflight memoria
delle 09:58:17 ha misurato 2.378.674.176 byte disponibili, sotto la soglia
2.415.919.104; impostazioni invariate e seed fermo. Nessun nuovo container
avviato; le decisioni del proprietario restano pendenti.

## Stato GitHub verificato — 16 ottobre

La lettura metadata-only registra PR #108 chiusa e fusa il 4 ottobre 2026 alle
12:16:49 UTC, merge commit `90f4f49bf2094fa2af51dff3a998b82054d93c76`:
[PR #108](https://github.com/cajopo/nla-catalog-gateway-staging./pull/108).
La consegna principale è completata con #108. PR #100 resta aperta, non draft e
non fusa: head `7ab94d345511ddd53c362206f041bf4942f1a61a`, base
`agent/staging-warm-activation` (`83b14e45ba20180805b2414f0c7b838041cd8ad7`).
Prima di questa revisione documentale, PR #101 era aperta, non draft e non fusa: head
`55aa1bedcc99d39e7d60ae1f388fa6c5541ebdf4`, base
`agent/refresh-interruption-recovery` (`7ab94d345511ddd53c362206f041bf4942f1a61a`).
Il vecchio head #101 `6913748dc1513b29c084db522865386067db241a` e i relativi
controlli sono storici. PR #112 resta draft e non fusa secondo l'evidenza market.
La PR #101 documentale è aperta e non fusa. Il checkpoint pubblicato precedente
`551bfbc1a0fa473017b0c934d7e0cfd990e9daed` aveva CI `38760991582` e CodeQL
`38760991612` passati: 3.885 test per Python 3.12 e 3.13, coverage 100%; container
smoke, dependency audit, Ruff, preflight e build passati. Il checkpoint documentale
successivo prima della presente consegna era `b6ab98e618b0867f875b97ccf6d6854359a826d0`,
con CI `38819024906` e CodeQL `38819025033` completed/success alle 22:56 UTC.
Il head finale e i controlli del delta attuale vanno verificati nei metadati della
PR #101. Gli aggiornamenti locali su alert e roadmap sono in questa consegna.
Il checkpoint pubblicato precedente della PR #113, aperta in bozza, è
`929c7b0849bc66258effa89e6aac5d78d1444c84`;
CI `38754689301` e CodeQL `38754689777` sono passati. CI: 4.211 test per
Python 3.12 e 3.13, copertura 100% (16.476 statement, 5.752 branch); container,
dependency audit, Ruff, preflight e build passati. Python 3.13 riporta un
`ResourceWarning` nel test esistente dei facet; nessun test fallito o saltato.
Validazione di quel checkpoint: 125 test mirati, copertura statement/branch 100% e
Ruff/preflight/build passati; review indipendente: 18 verifiche. PR #114,
health operativa #13, è aperta
in bozza al head `59a74e60edd967dc27e65fd95ac2a390eb619961`; CI `38754640052`
e CodeQL `38754639981` sono passati. CI: 4.154 test per Python 3.12 e 3.13,
copertura 100% (15.994 statement, 5.614 branch); container, dependency audit,
Ruff, preflight e build passati. Un `ResourceWarning` appare in Python 3.13 nel
test dei facet, senza test falliti o saltati. Validazione dell'autore: 68 test
mirati, copertura statement/branch 100%, lint, format, preflight e build passati;
review indipendente: 10 casi. Nessuna delle due PR operative è stata installata o attivata. Un collector
read-only sul modulo #114 ha ottenuto `collect=healthy` senza scrivere file,
toccare unità o lock; il risultato convalida il contratto osservato sull'host,
non unità, sandbox, Caddy o deployment dell'endpoint pubblico. I residui #100,
#101, #112, #113 e #114 non sono fusi; non confonderli con la consegna
principale #108.

## Regole per il prossimo intervento

Il backup del 17 ottobre alle 07:16 UTC è completo: job
`backup-c121a380661d4bbfa6b6c0c5de1a09b4`, ricevuta
`8bd4cfe334ee34e91358e5416940e3cecc8d3018a3968561e0936b4775f2d64d`, snapshot
`bd249a0d8064bd950a2ef6ddb37eb9329c36eec2101491884d0c8cd794e42963`;
`read-data`, ricevuta per-job=last-success e servizio riuscito. Il timer è
enabled/waiting per il prossimo trigger del 18 ottobre alle 01:00 UTC
(`Persistent=no`); la prima esecuzione automatica non è ancora stata osservata.
La quarantine/review e la rimozione esatta dello staging fallito `971c` sono
concluse; il vecchio job non è stato ripetuto. Spazio libero finale 13.249.085.440 byte;
refresh/market e pointer/generazioni protette invariati. Il restore da host vuoto
non è provato; health resta inerte. [Dettagli e ricevute](evidence/BACKUP-AUTOMATION-2026-10-15.md).

La PR #114 resta un candidato di codice, non una modifica al monitor o un
deployment; lo stato dei gate e la prova read-only sono riportati sopra.

- Considerare concluse le prove e le unità terminali del 29 settembre; non
  riavviarle e non ripetere il conteggio delle nuove carte come aggiornamento.
- Jacopo ha revocato il rinvio GitHub il 3 ottobre e ha chiesto di capire/correggere
  l'errore e riprendere la consegna. Procedere con issue/PR separate, CI verde e
  review indipendente; la consegna complessiva non è ancora conclusa.
- Non ricreare il heartbeat `verifica-ciclo-nuove-uscite-nla`, eliminato a fine prova.
  I timer della VPS sono separati e nell'ultima osservazione risultavano attivi.
- Non togliere la password e non modificare il MAIN. Una nuova modifica al tema
  richiede una copia non pubblicata; il tema con nome “catalogo completo test”
  non è più una risorsa di test.
- Consultare documentazione ufficiale prima di usare API, servizi o strumenti.
- Preservare GID, identità verificate e ledger importer; non identificare per titolo,
  inventare prezzi o correggere in massa prodotti pre-esistenti.

## Cosa fare dopo questa fotografia

Il [checkpoint di manutenzione](evidence/MAINTENANCE-2026-09-30.md) registra
VPS osservata il 30 settembre, prima copia fuori host verificata e recupero dei
dati sul PC, più 21 prove per motore Chrome/Firefox/WebKit su fixture e controlli
axe nei due stati visibili. Il [runbook](OPERATIONS-RUNBOOK.md)
definisce controlli, incidenti e sequenza di recupero con i limiti effettivi.

Il successivo [drill Linux](evidence/RECOVERY-LINUX-2026-09-30.md) ha restaurato
il checkpoint dal PC sulla stessa VPS: primo tentativo OOM a 1 GiB conservato,
seconda istanza pronta con 2 GiB/0,5 CPU, dieci richieste funzionali e quaranta
di carico passate; errore HTTP del cursore verificato con 200→409→200. Non
ripetere questi test senza nuova modifica o fallimento. Il 30 settembre alle
20:55:53 UTC il finalizer ha completato la chiusura: entrambi i container erano
stati rimossi prima della quarantena dei quattro file grandi temporanei.
I file sono stati eliminati dopo verifica, dieci POST firmate passate al runtime
live e controllo readiness/pin. Restano le
ricevute archiviate e il pointer restaurato, non i database del drill né il
gateway di prova. Lo spazio libero era 11.911.491.584 byte; i 2,04 GB liberati
sono solo consumo temporaneo del drill, non un ulteriore incremento da sommare
ai 3,65 GB della pulizia legacy. Non è recupero su host nuovo né prova
browser→Shopify; non riusare nomi/ID/ricevute del drill per nuovi run.

Il checkpoint aggiornato [recupero PC](evidence/RECOVERY-PC-2026-10-01.md)
precisa che è passato il seed dei dati, non il runtime. Prossimi passi: decidere
se preparare il riavvio concordato di Docker Desktop a 4 GB o rinviare; solo con
preflight memoria valido proseguire il runtime isolato. Poi completare la prova
su host nuovo, completare backup automatico e conservazione, collaudare il
ciclo refresh/importer e definire conservazione/recupero credenziali, verificare il
recapito email degli alert; Jacopo è il referente iniziale confermato (D-022).
La destinazione è ora Backblaze: il 3 ottobre Jacopo ha scelto `nla-catalog`.
Prima copia manuale del checkpoint PC caricata, riscaricata con hash identici
e restaurata offline, tre database PASS. In quella prova la chiave era solo
sul PC; D-021 ne ha poi autorizzato l'installazione sulla VPS. Per il backup
corrente del 15 ottobre usare il delta sopra, senza confonderlo con il pilota.
Vedi [prova Backblaze](evidence/BACKBLAZE-2026-10-03.md).
Il 15 ottobre è passato il [pilota cifrato S3](evidence/BACKUP-ENCRYPTION-2026-10-15.md):
restic 0.19.1, checkpoint identico del 3 ottobre, controllo integrale e recupero
con SHA-256 invariato. Il repository `nla/restic-v1` è pronto per il lavoro
successivo; il suo helper è manuale e non va schedulato. La prima cattura
corrente completa è ora riuscita; restano recupero applicativo, custodia
indipendente della password e scheduler VPS con prove di rinvio/fallimento,
preservando i cicli in esercizio.
Le prove di cifratura già riuscite non vanno ripetute senza una nuova modifica.
La [prova reference del 1 ottobre](evidence/REFERENCE-RECOVERY-2026-10-01.md)
ha già validato offline tutte le 336.752 identità restaurate e accettato la
configurazione tramite i sorgenti installati del refresh. È un contenitore
separato con 768 MiB, senza rete né credenziali: non supera il preflight del
runtime PC e non prova un ciclo Shopify. Non ripeterla senza nuova lacuna.
Jacopo aveva confermato il PC per la prima copia e ha poi scelto Backblaze;
per gli alert ha scelto l'email dopo il chiarimento. Il 15 ottobre ha confermato
il destinatario, conservato nelle prove private e modificabile (D-020).
Ha poi confermato di essere il referente iniziale e autorizzato l'email di
attivazione UptimeRobot (D-022), richiesta alle 13:49:32 UTC con HTTP 200.
Jacopo ha poi confermato di avere ricevuto e attivato l'email e di essere entrato
nella dashboard. Il recapito degli alert non è ancora collaudato. L'ispezione
della dashboard è stata fermata da Computer Use perché non poteva verificare
l'URL corrente su Windows: stato e configurazione del monitor restano da
osservare, senza reinviare l'attivazione. Il runbook descrive copertura e limiti.
Quando si verifica la configurazione del monitor, scegliere
esplicitamente GET: [la guida ufficiale UptimeRobot](https://help.uptimerobot.com/en/articles/11358466-how-to-debug-a-monitor-showing-as-down-in-uptimerobot)
indica HEAD come default e GET al retry. La sonda pubblica read-only del 15
ottobre ha mostrato `/readyz` GET 200 e HEAD 404. Non reinviare l'email già
inviata; l'attivazione con metodo GET rientra nell'autorizzazione già data.
Nessun altro messaggio di prova inviato. Il primo tentativo Docker
locale fallì al socket e resta conservato come evento storico; non furono
resettati né cancellati dati. Nella prova del 1 ottobre Docker Desktop era attivo e l'immagine del
backup è stata collegata al manifest previsto tramite digest OCI, senza
indebolire il pin del config. La nuova [prova PC](evidence/RECOVERY-PC-2026-10-01.md)
ha verificato il seed di 12 file e tre database; la preparazione del runtime è
stata fermata perché la memoria libera risultava sotto soglia. Nessun runtime
PC è stato creato o avviato. Volume e seed arrestato restano preservati.
Questo paragrafo descrive la prova storica: non attesta la disponibilità attuale
del daemon Docker Desktop, da verificare prima di qualsiasi ripresa.
Al 30 settembre era pendente la scelta fra riavviare Docker Desktop con 4 GB
o rinviare; nessuna impostazione è stata cambiata. È uno stato storico, non una
nuova richiesta di consenso dopo D-023. La replica locale resta non provata;
il recupero isolato sulla VPS procede con i propri controlli di ammissione.
Preservare anche i fallimenti Firefox e la correzione del PNG nella sola fixture
privata; le assertion sono invariate. Restano QA dei flussi Shopify/mobile,
accessibilità completa, guasto/freschezza E2E e capacità in produzione. Il successivo diagnostico
del contrasto ha mostrato lo status interamente coperto dal listbox opaco:
incomplete classificato non applicabile per quel solo stato della fixture,
con review indipendente; ricevuta axe originale invariata. Screen reader,
altri stati/viewport e contesto Shopify rimangono da verificare. Il browser
di Codex raggiunge la pagina password: nessuna sessione negozio sbloccata nella
prova del 30 settembre; richiesto al proprietario l'accesso nell'app, senza
password in chat. In quella prova la review automatica dell'accesso era stata
negata. Dopo D-023 non considerare ancora pendente il consenso al lavoro NLA;
resta da verificare l'effettiva disponibilità della sessione e l'accesso tecnico.
Non è stata eseguita una prova sul negozio protetto.

La prova mirata del 30 settembre alle 21:53 UTC aggiunge sei assertion locali
con Chrome touch emulato a 390×844: scorrimento, tap/selezione suggerimento e
recupero UI dopo un HTTP 503 deliberato della fixture tramite Retry. Il recupero
è fixture HTTP 200; non è un outage del gateway né un flusso Shopify/mobile reale,
Safari/iOS o screen reader. Ricevuta e screenshot sono nell'archivio privato
`output/nla-recovery/20260930/evidence/qa-touch-down-final/`; indice
`index.json`. I due tentativi iniziali con cleanup incompleto e le ricevute dei
due cleanup restano conservati accanto all'esito finale, che attesta processo
terminato, zero processi Chrome del profilo di prova e profilo rimosso.

Il successivo refresh delle 15 UTC è concluso con successo alle 16:40:13 UTC;
pointer e ricevuta concordano sul manifest `b0ca55e7…`. Non occorre ripeterlo.
Per istruzione successiva di Jacopo, cinque artefatti VPS obsoleti sono stati
quarantenati, verificati e cancellati: 3,65 GB recuperati, 11,92 GB liberi alle
18:22 UTC. Restano solo le due generazioni protette. Il vecchio restore drill
del 21 settembre è escluso da quella pulizia perché due container arrestati ne
montano ancora i dati; è distinto dal nuovo drill del checkpoint PC, chiuso
alle 20:55 UTC come descritto sopra.
La retention ordinaria già esistente è provata dopo l'ultimo refresh riuscito;
i refresh sono previsti due volte al giorno. È attivo il nuovo controllo Codex
`manutenzione-spazio-vps-nla` ogni 48 ore, distinto dal heartbeat concluso.
Richiede PC e app accesi; la retention sulla VPS continua autonomamente.
Leggere [ricevute e limiti](evidence/RETENTION-2026-09-30.md) e la ricetta nel
runbook; non sovrascrivere le prove private né usare cancellazioni generiche.

Il checkout iniziale di questa chat era
`agent/live-bulk-capture` a `3008e05`, con modifiche locali pre-esistenti;
non rappresenta da solo il codice installato. Questa manutenzione usa il ramo
locale `agent/pm-state-20260930`, sotto #34. Non viene presentata come merge,
release certificata o chiusura delle issue.

## Sorgenti da preservare alla ripresa della consegna

| Workstream | Ramo locale | Commit salvato |
| --- | --- | --- |
| Importer #97 | agent/cardtrader-missing-printings | adbfa59156ada22d960c807c10e765320d6aef35 |
| Ricerca per famiglia #9 | agent/family-search-v1 | 8d24b38124eb2c95f4f4e6481426d0b349dd3aba |
| Operatore refresh/deploy #13 | agent/staging-warm-activation | 83b14e45ba20180805b2414f0c7b838041cd8ad7 |
| Tema #14 | agent/theme-family-selector | 09821ca37bbffbcc3beef02651f59f7f106084ec |

Questi commit non vanno confusi con runtime installato `ed24a61` e operatore
`881b9ca`. Anteprima integrata: tree `2d66cbd609db158450824d2d71347d7e8bda9ddd`,
archivio SHA256 `dcc17d67b466977ccb0e0fce6d98c24b5b6787c8e92500fc9ecfaf021c4f03ae`.
È un'anteprima privata, non un commit finale con CI verde.

Le ricevute, i cataloghi e gli archivi rimangono fuori Git. I percorsi temporanei
privati sono registrati nelle evidenze; la loro presenza oggi non garantisce
conservazione durevole. La fotografia distingue fatti, lacune e proposte.
La copia privata di manutenzione è in `output/nla-recovery/20260930/`, esclusa
da Git e protetta con ACL; contiene anche resoconti e script one-off.
Non è ancora un sistema di backup automatico.

Il [passaggio di consegne storico](PM-HANDOFF-HISTORY-20260929.md) è conservato
senza riscritture e non costituisce una nuova istruzione operativa.

## Aggiornamento restore — 16 ottobre 2026

Il restore isolato è terminato in 35.62632 s e la verifica guarded read-only è PASS su tutti i file e i tre database SQLite. Snapshot `f11005053ed6d498a312c7be84181ee40f28f6947a82dc349ef91319267a70bb` (dimensione logica ripristinata 2.126.224.845 byte; `resticVerify=true`); verifica del 16 ottobre 09:30 con snapshot current `ed078…` e previous `fd665…`. Questa evidenza supera lo stato precedente “restore non avviato” limitatamente al recupero e alla verifica dello snapshot: alla verifica delle 09:30 il caricamento dell'archivio non era ancora stato eseguito; la presenza dell'immagine sul nodo è distinta; il successivo runtime di test è stato avviato, verificato e chiuso, mentre il runtime live continua operativo. Il controllo live delle 09:24:36 è distinto: pointer `6e1b…`, current `4cbb2053`, previous `49521`, refresh e market `inactive/success`, 11.665.154.048 byte liberi. Non confondere il pointer live con quello dello snapshot restaurato. Dettagli e ricevute: [evidenza backup e restore](evidence/BACKUP-AUTOMATION-2026-10-15.md).

Il drill applicativo del 16 ottobre ha chiuso PASS i ruoli `current` e `previous`;
`emptyHostRecoveryProven=false` perché l'immagine era già residente. La pulizia
finale delle copie isolate del restore ha rimosso esattamente 643 file, 72 directory
e 3.930.589.037 byte, conservando lo snapshot; il runtime di test è chiuso e il live
resta operativo. Il successivo backup completo del 17 ottobre è PASS e il timer è
enabled/waiting per il 18 ottobre alle 01:00 UTC; la prima esecuzione automatica resta
da osservare. Il successivo backup dopo attivazione health è `919aed…`, verificato
entro le 08:18 UTC del 17 ottobre; il componente è ora attivo. Per job, ricevute e storico dei fallimenti,
vedere [dettagli backup](evidence/BACKUP-AUTOMATION-2026-10-15.md).
