# Passaggio di consegne PM NLA

Aggiornato il 15 ottobre 2026. Jacopo ha affidato a Codex il ruolo PM di questa
fase. Riferimenti: master #3, manutenzione documentale #34, architettura #17 e
tassonomia #19, consultati prima dell'intervento.

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

## Stato GitHub verificato — 15 ottobre

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
La PR #101 documentale è aperta e non fusa. Il commit verificato
`f116c1f49e320166297257a1c400f6e7248763a4` ha CI `38748061728` e CodeQL
`38748061458` passati: 3.885 test per Python 3.12 e 3.13, coverage 100%;
container smoke, dependency audit, Ruff, preflight e build passati. La presente
revisione deve ricevere i controlli esatti sul nuovo head dopo il push.
PR #113 è aperta in bozza al head `929c7b0849bc66258effa89e6aac5d78d1444c84`;
CI `38754689301` e CodeQL `38754689777` sono passati. CI: 4.211 test per
Python 3.12 e 3.13, copertura 100% (16.476 statement, 5.752 branch); container,
dependency audit, Ruff, preflight e build passati. Python 3.13 riporta un
`ResourceWarning` nel test esistente dei facet; nessun test fallito o saltato.
Validazione dell'autore: 125 test mirati, copertura statement/branch 100% e
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

Jacopo ha autorizzato il trasferimento delle
credenziali (D-021), ora installate con configurazione e unità verificate.
Il servizio installato resta alla versione precedente, il timer è disabilitato
e la prima copia è verificata. Il primo backup completo corrente era concluso alle
13:30:23 UTC con `read-data` passato e staging rimosso. Prima dell'attivazione
restano recupero applicativo, prova di capacità e verifica della pulizia dopo
errore; usare [evidenza e pin](evidence/BACKUP-AUTOMATION-2026-10-15.md), senza
ripetere il pilota sul checkpoint storico del 3 ottobre.
La prova mirata della PR #113 ha coperto l'I/O pipe Linux e i limiti di
ammissione del comando; non sostituisce una nuova cattura o la prova completa
di timeout, unità e backup, né autorizza ad attivare il timer.

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
Il recapito non è ancora collaudato e il monitor richiede la conferma di Jacopo
nell'email. Il runbook descrive eventi, copertura e limiti del monitor esterno.
Quando Jacopo conferma l'email e il monitor viene configurato, scegliere
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
È pendente la scelta asincrona di Jacopo fra preparare un riavvio concordato
con Docker Desktop a 4 GB o rinviare; nessuna impostazione è stata cambiata.
Non ripetere le prove precedenti senza una nuova decisione e un preflight valido.
Preservare anche i fallimenti Firefox e la correzione del PNG nella sola fixture
privata; le assertion sono invariate. Restano QA dei flussi Shopify/mobile,
accessibilità completa, guasto/freschezza E2E e capacità in produzione. Il successivo diagnostico
del contrasto ha mostrato lo status interamente coperto dal listbox opaco:
incomplete classificato non applicabile per quel solo stato della fixture,
con review indipendente; ricevuta axe originale invariata. Screen reader,
altri stati/viewport e contesto Shopify rimangono da verificare. Il browser
di Codex raggiunge la pagina password: nessuna sessione negozio sbloccata nella
prova del 30 settembre; richiesto al proprietario l'accesso nell'app, senza
password in chat. La review automatica dell'accesso è stata negata; la richiesta
asincrona di autorizzazione del proprietario è ancora pendente. Non è stata
eseguita una prova sul negozio protetto. Il tab è conservato per questo passaggio.

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
