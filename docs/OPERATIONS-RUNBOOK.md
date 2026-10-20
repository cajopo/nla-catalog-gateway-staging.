# Runbook operativo NLA

**Chiusura manutenzione del 18 ottobre:** backup automatico e recupero isolato
provati, alert TEST consegnati e Jacopo referente iniziale. Proposte operative:
RPO 36h in esercizio regolare, RTO 2h su Linux pronto; misure e limiti nella
[verifica finale](evidence/MAINTENANCE-CLOSURE-2026-10-18.md). Restano attive le
procedure ordinarie e il controllo periodico dello spazio descritti sotto
(calendario Codex salvato: domenica alle 09:00 Europe/Rome, D-027).

Aggiornamento market del 15 ottobre 2026; baseline del 3 ottobre. Stato e prove:
[manutenzione del 30 settembre](evidence/MAINTENANCE-2026-09-30.md) e
[recupero PC](evidence/RECOVERY-PC-2026-10-01.md),
[checkpoint PC del 3 ottobre](evidence/BACKUP-PC-2026-10-03.md),
[incidente refresh del 3 ottobre](evidence/INCIDENT-2026-10-03.md) e
[ripresa GitHub](evidence/GITHUB-RESUME-2026-10-03.md).
PM della fase: Codex. Destinatario email confermato da Jacopo il 15 ottobre
(D-020), conservato nelle prove private e modificabile. Operatore continuativo
ancora da assegnare; questo documento non crea un servizio di reperibilità.
Il 3 ottobre il refresh ordinario `20261003t073240z-3f7384f8` è terminato exit 0
alle 09:12:19 UTC; freshness, pointer, smoke e retention periodica sono passati.
Spazio finale 11.782.266.880 byte. Seguire la
[timeline dell'incidente](evidence/INCIDENT-2026-10-03.md) per ricevute, hash e
limite dei 6 GiB pre-cattura (non garantisce il picco di spazio).

## Ricerca codici installata — 19 ottobre 2026

**Verifica del 20 ottobre, 08:28 UTC:** market completo, refresh terminato e
manifest attivo coerente. Il precedente `market_incomplete` è superato;
`/readyz` 200 e `/opsz` 503 ora per `backup_attention`. Il blocco seguente
documenta il checkpoint storico del 19 ottobre.
Il controllo backup delle 08:30 UTC conferma il job odierno fallito con
`checkpoint_failed`; ultimo backup completo il 19 ottobre alle 01:01 UTC.
Diagnosticare la causa interna prima di una correzione; non rimuovere lo
staging del job fallito per far rientrare l'alert.
[Prove e limiti correnti](evidence/OPERATIONAL-CHECK-2026-10-20.md).

Su richiesta esplicita di Jacopo, installata la correzione locale `2c8c650`
(`agent/card-code-search-115`): `FIN88` e `FIN-88` restituiscono la stessa carta,
con suggerimenti e faccette coerenti. La stampa è esaurita e rimane esclusa
con il filtro disponibili. Copertura aggregata Windows/Linux 100% su istruzioni
e rami; 4.122 test Windows e 35 test nativi Linux passati, review indipendente.

Immagine effettiva `sha256:2231c268945bf3681c83b2f0fafa9ae71a0751e46972c963c205463fc2b24a22`,
costruita sull'immagine `8a23ad08`/runtime `ed24a61` con soli quattro moduli aggiornati.
Container `b89865e8...`, installazione registrata alle 21:05:56 UTC,
prova finale alle 21:10:40 UTC. Fonte dati, pointer e ambiente accettato invariati;
operatore/archive `881b9ca`, patch importer `8657aaa`, unità, Caddy, backup e monitor
preservati. Modificato soltanto `image` nella configurazione del refresh futuro.
Timer market 02/14 UTC e refresh 03/15 UTC attivi; nessun marker pendente.
Al checkpoint del 19 ottobre il primo ciclo pianificato successivo non era
ancora osservato; l'aggiornamento sopra registra la verifica del 20 ottobre.

**Attenzione operativa preesistente:** `/readyz` 200, `/opsz` GET/HEAD 503.
Il collector segnalava `market_incomplete` già prima del deploy (20:00 e
20:52:13 UTC). Ricevuta immutabile `draft_cycle_partial` del ciclo
`market-20261019t140017z-be2a057f`, SHA256 `5fb4de9672fcc50d5194db59214ff5458985479d6764bc6631d8aae0ebc72096`.
Non è un guasto introdotto dalla ricerca; non dichiarare il monitor UP.
Esito market e monitor non sono stati modificati né è stato forzato un ciclo.
Al checkpoint del 19 ottobre il problema market restava manutenzione separata.

Ricevute VPS: `/opt/nla-staging/search-code-2c8c650/rollout/` e
`/var/lib/nla-catalog-refresh/20261019t205146z-48551a72/`.
[Metodo, prove, limiti e rollback](workstreams/ws-05-code-hyphen-search.md).
Prove private PC nel worktree `C:\Users\umbri\.codex\worktrees\0072\nla-catalog-gateway-staging\output\card-code-search-20261019`.
Nessun push, PR o workflow GitHub: consegna locale separata secondo D-024/D-027.
Non rieseguire i due helper di installazione/finalizzazione una tantum.

## Correzione market del 15 ottobre

Alle 10:17:47 UTC è stato installato il fix della [PR #112](https://github.com/cajopo/nla-catalog-gateway-staging./pull/112),
commit `8657aaa495ae5e602d54365ffb691d06adc4f2c1`: massimo tre tentativi GET
CardTrader per errori transitori, con attese e scadenza globale; ricevute con
motivo, endpoint e tentativi, senza segreti. Il modulo di cattura installato ha
SHA256 `04a16414b0889751ad4d383a12070afe53bafaaf6459188fe0d0148fef329aa5`.
L'installazione importer mantiene il nome storico `importer-d7e6fc9`; identificare
questa patch tramite il suo hash e la ricevuta, non dal solo nome della directory.

Il ciclo fallito `market-20261014t140021z-b86bf562` si era fermato prima delle
scritture Shopify. Dopo lock non bloccanti, hash e ledger verificati, il marker
è stato archiviato nel ciclo insieme a `inspection-resolved.json`; la retention
preserva l'intera prova. Il file originale e le ricevute sono in
`/opt/nla-staging/importer-state/maintenance-20261015-market-source/`.
Non ripetere il helper specifico dell'incidente: un nuovo blocco richiede una
nuova ispezione, soprattutto se esistono batch, identità o pubblicazioni incerte.

Verifica finale alle 10:18:11 UTC: modulo importabile, HTTPS 200/ready, ledger,
puntatore, configurazione, ricevuta e invocazione del refresh invariati; timer
market 14:00 UTC e refresh 15:00 UTC attivi. Nessun processo avviato o riavviato.
Il reset dello stato fallito non attesta un nuovo ciclo completo. Dettagli e
limiti in [incidente market](evidence/MARKET-SOURCE-2026-10-15.md).

## Controllare prima di intervenire

1. Registrare ora UTC, problema osservato e ultimo ciclo completato. Verificare
   HTTPS `https://catalog-staging.nextlevelarena.it/readyz`, stato del runtime,
   proprietà delle unità e ricevuta completata. Non usare `Result=success` da
   solo per dichiarare concluso un processo ancora `activating`.
2. Il catalogo ha una tolleranza concordata di 24 ore per la freschezza durante
   l'esercizio ordinario; è distinta dall'RPO delle copie di recupero. Calcolare l'età dalla
   `sourceStartedAt` della ricevuta che corrisponde al manifest attivo, non
   dalla data del file, dall'ultimo trigger o dalla sola readiness.
3. Su VPS, leggere `systemctl show nla-catalog-refresh.service` e
   `systemctl show nla-market-catalog.service`, limitando l'output a
   `ActiveState`, `SubState`, `Result`, `ExecMainStatus`,
   `ExecMainExitTimestamp`. Per i timer leggere anche `TimersCalendar`,
   `Persistent`, `LastTriggerUSec`, `NextElapseUSecRealtime`.
4. Ricevute ordinarie: `/var/lib/nla-catalog-refresh/<run>/completed.json`.
   Ricevute mercato: `/opt/nla-staging/importer-state/<run>/completed.json`.
   Pointer: `/var/lib/nla-staging/activation.v1.json`. Conservare percorso e
   checksum; non esportare log integrali, segreti o URL Bulk firmati.

L'accesso SSH già configurato sul PC usa
`C:\Users\umbri\.ssh\nla_aruba_staging` e
`C:\Users\umbri\.ssh\nla_aruba_staging_known_hosts`, verifica host key obbligatoria.
Non chiedere o copiare chiavi/password in chat. Non disabilitare la verifica TLS/SSH.

## Incidenti e confini dell'intervento

| Evento | Prima azione | Prima di una correzione |
| --- | --- | --- |
| Readiness fallita o gateway non raggiungibile | Distinguere DNS/TLS/edge/runtime; verificare container e ultimi pin senza stampare l'ambiente completo | Preservare ultima generazione valida; niente restart in sequenza o simulazione di guasti sul live |
| Refresh fallito | Leggere la ricevuta terminale e verificare se il vecchio runtime serve ancora correttamente | Diagnosi sul ciclo esistente; niente nuova Bulk ripetuta solo per avere aggiornamenti |
| Market fallito con refresh recuperato | Eseguito helper revisionato `acknowledge_market_failure` default/apply sulla sola invocazione storica `ce52ee6b0aa84341bd83968f8d3b0dcc` (3 ottobre 02:00:18 UTC), dopo freshness e smoke PASS | PASS; nessun processo avviato e nessuna chiamata Shopify. `Result=success`/inactive con `ExecMainStatus=1` conserva il fallimento dell'invocazione storica, non prova un nuovo market riuscito. `systemctl reset-failed` rimuove stato failed e contatori start/restart ma non avvia il job; `ExecMainStartTimestampMonotonic` verificato prima/dopo. Timer invariati: market 14 UTC, refresh 15 UTC. [systemd v255 systemctl](https://raw.githubusercontent.com/systemd/systemd/v255/man/systemctl.xml) |
| Catalogo oltre 24 ore | Registrare manifest, età sorgente, ultimo esito e job eventualmente in corso; classificare come degrado | Readiness 200 non risolve la freschezza; occorre escalation al referente concordato |
| Importer con mapping mancanti/ambigui | Conservare eccezioni e ledger, distinguere quarantena da guasto generale | Mai creare per titolo, inventare prezzi/lingue/finish o correggere prodotti esistenti |
| Spazio VPS insufficiente | Inventariare dimensioni, piano di retention e generazioni protette | Applicare D-016: quarantena, verifica e cancellazione dei soli artefatti obsoleti provati; nessuna cancellazione generica |
| Spegnimento/perdita VPS | Non confidare nei trigger persi: timer osservati `Persistent=no` | Avviare il recupero su host isolato da un checkpoint verificato; segnalare i cicli mancati |
| Problema tema | Arena MAIN `210350735628` dal 19 ottobre; precedente `175195881740` UNPUBLISHED per rollback | Ripubblicazione, nuovo cutover o password richiedono Jacopo; lavorare sulla copia non pubblicata. [D-028](DECISIONS.md#d-028--stile-arena-pubblicato) |

Il recapito TEST DOWN/UP è verificato il 18 ottobre; vedere la
[prova di consegna](evidence/ALERT-DELIVERY-2026-10-18.md). `OnFailure` è vuoto nelle unità
NLA e non risultano unità o nomi di file cron NLA per monitor fra quelli censiti.
Il monitor esterno e la sua attivazione sono descritti sotto. Le email di prova
sono ricevute e registrate; Jacopo ha confermato il monitor su `/opsz` e UP.
La deduplicazione di incidenti reali non è provata. L'attivazione UptimeRobot è completata.
Per le autorizzazioni correnti vale D-023: non riaprire decisioni già prese.
Non simulare guasti sul servizio attivo per provocare una notifica.

Per la scelta del proprietario, il pacchetto minimo proposto segnala servizio
irraggiungibile, refresh fallito e sorgente oltre 24 ore. Un guasto va confermato
con controlli ripetuti prima di notificare; un job ancora in corso non deve
generare un falso alert di errore. Il messaggio deve dire cosa è accaduto,
da quando, ultimo aggiornamento valido e prima azione utile; inviare il rientro
alla normalità e contenere i duplicati. Nessun riepilogo periodico non richiesto.

Jacopo ha scelto l'email come canale iniziale il 30 settembre e ha confermato
il destinatario il 15 ottobre (D-020). L'indirizzo resta nelle prove private.
Il 15 ottobre ha autorizzato l'attivazione UptimeRobot e ha confermato di essere
il referente iniziale (D-022). Il referente prende in carico la segnalazione
e decide chi interviene; non implica che debba risolvere ogni problema da solo.

Il monitor di raggiungibilità deve essere fuori dalla VPS per segnalare anche
la sua perdita. Un monitor sullo stesso host può rilevare errori dei job mentre
l'host funziona, ma non inviare un alert dopo il proprio spegnimento. Il PC è
disponibile per la prima copia; non è ancora dichiarato un presidio sempre acceso.

Proposta pronta per il solo controllo esterno di raggiungibilità: UptimeRobot
Free, `https://catalog-staging.nextlevelarena.it/readyz`, HTTPS ogni cinque minuti,
email di down/up al recapito confermato. Il [piano gratuito](https://help.uptimerobot.com/en/articles/11604710-who-should-use-uptimerobot-s-free-plan)
è ammesso anche per uso commerciale, senza carta; il [recapito email personale](https://help.uptimerobot.com/en/articles/11360953-uptimerobot-personal-notification-channels-setup-guide)
è uno per utente. Costi/limiti verificati nuovamente il 15 ottobre: piano gratuito,
50 monitor, intervallo cinque minuti; non garantisce rilevazione entro cinque minuti.
Non copre da solo refresh falliti o dati vecchi con readiness ancora positiva.

La [skill ufficiale quick-monitor-setup](https://github.com/uptimerobot/ai/blob/main/skills/quick-monitor-setup/SKILL.md)
è stata letta per preparare il flusso senza installare plugin o chiedere API key.
Richiede URL e indirizzo identici nel challenge e nella richiesta; difficulty
letto dalla risposta, proof-of-work SHA256, poi invio della richiesta e conferma
dell'email da parte del proprietario. Dopo l'autorizzazione D-022, la richiesta
è stata inviata alle 13:49:32 UTC del 15 ottobre: HTTP 200, `status=ok`.
Al momento dell'invio, HTTP 200 del provider non provava creazione o recapito:
poteva indicare anche una richiesta ignorata. In seguito Jacopo ha confermato
ricezione dell'email, attivazione e accesso alla dashboard ([D-022](DECISIONS.md#d-022--attivazione-uptimerobot-e-referente-iniziale)).
L'apertura del link con scadenza a 24 ore e il clic su Activate sono quindi
passaggi storici completati. Non reinviare l'email né una richiesta di attivazione.
Ricevuta privata in `output/nla-recovery/20260930/alert-activation-20261015T134927Z-f53333c3/receipt.json`.
La discrepanza storica GET 200/HEAD 404 su `/readyz` del 15 ottobre è superata
per il monitor: il 18 ottobre Jacopo ha confermato il passaggio a `/opsz` e UP;
la sonda indipendente conferma GET e HEAD 200. Non occorre un ulteriore cambio
di metodo per risolvere quella discrepanza. [Evidenza](evidence/ALERT-DELIVERY-2026-10-18.md).
L'ispezione della dashboard è stata fermata inizialmente dalla verifica URL;
il 17 ottobre Computer Use ha negato l'accesso all'app Google Chrome prima
della lettura della pagina. L'autorizzazione del titolare non manca ([D-022](DECISIONS.md#d-022--attivazione-uptimerobot-e-referente-iniziale),
[D-023](DECISIONS.md#d-023--continuità-operativa-entro-lobiettivo-autorizzato)).

Per provare il recapito senza provocare un guasto, aprire il monitor NLA già
esistente e usare **Test Notification**, scegliendo il contatto email autorizzato
associato al monitor. La [procedura ufficiale](https://help.uptimerobot.com/en/articles/11602913-how-to-test-notifications-in-uptimerobot-quick-guide)
invia notifiche di prova DOWN e UP attraverso lo stesso percorso di consegna
degli alert. Conservare orario del test e metadati delle email effettivamente
ricevute; la conferma di invio del provider da sola non prova il recapito.
Finché Chrome resta inaccessibile a Computer Use, il clic è manuale del titolare;
non occorrono una nuova attivazione o un nuovo consenso. La prova è riuscita il
18 ottobre: non ripeterla. Le email identificavano `/readyz`; Jacopo ha poi
confermato il cambio in `/opsz` e stato UP. GET e HEAD sono entrambi supportati
da `/opsz`, verificati 200 anche alle 01:13 UTC. Intervallo 5 minuti visibile
nello screenshot precedente al cambio URL. Non ripetere la modifica.
Il collaudo del recapito non dimostra configurazione del monitor o deduplicazione.
Proseguire entro lo scope autorizzato senza ripetere richieste di consenso; non
reinviare l'email. Il monitor e la prova di alert non sono dichiarati verificati.
La lettura indipendente dei metadati Gmail del 17 ottobre, 10:56 UTC, conferma
la presenza in Inbox della sola email di conferma del 15 ottobre nella ricerca
delimitata. Nessun alert operativo trovato da quella query; questo non prova
né il monitor né la ricezione di avvisi down/up.
[Ricevuta e limiti della verifica](evidence/OPERATIONAL-HEALTH-2026-10-15.md).
L'indirizzo è modificabile dalle impostazioni dell'account; il
[cambio email](https://help.uptimerobot.com/en/articles/11582766-how-to-change-your-uptimerobot-account-email-or-username)
richiede conferma tramite il vecchio indirizzo. Non è una modifica del codice NLA.
La readiness dal PC, con TLS validato e senza redirect, è risultata 200/ready
alle 17:06 UTC. Questo è un controllo singolo, non un monitor configurato.

Il 15 ottobre alle 16:20–16:21 UTC il pacchetto health è stato preparato sulla
VPS: 101 file verificati, unità validate e import Python eseguiti senza privilegi.
La successiva attivazione del 17 ottobre è riuscita: servizi, `/opsz`, proxy
e inclusione nel backup sono verificati. Seguire lo stato finale e i pin in
[prove degli alert](evidence/OPERATIONAL-HEALTH-2026-10-15.md), senza ripetere
l'attivazione già conclusa. La prova di recapito resta distinta.

## Retention e controllo ogni 48 ore

Il titolo conserva il riferimento storico del prompt. Il calendario salvato,
verificato il 19 ottobre e lasciato invariato, è domenica alle 09:00 Europe/Rome
([D-027](DECISIONS.md#d-027--fase-2-chiusa-e-ripresa-github-settimanale)).
La retention ordinaria dopo i refresh resta distinta da questo controllo.

Jacopo ha autorizzato la pulizia degli artefatti VPS non più necessari il
30 settembre: prima spostamento, poi verifica funzionale, infine cancellazione.
La [prima esecuzione](evidence/RETENTION-2026-09-30.md) ha recuperato 3,65 GB.
Corrente/precedente, ledger, reference, credenziali, sorgenti installati e prove
necessarie rimangono protetti. Un file vecchio o un container arrestato non sono
da soli prova che i dati siano eliminabili.

La retention ordinaria è già inclusa nell'operatore installato `881b9ca`: dopo
ogni refresh riuscito elimina risorse e acquisizioni obsolete riconosciute dalle
ricevute, proteggendo corrente/precedente e risorse ancora referenziate. I timer
refresh sono previsti alle 03 e 15 UTC. Alle 18:22 UTC `last-success.json` era
identico alla ricevuta conclusa, pubblicata dopo la retention: i due percorsi
del piano risultavano rimossi. Non serve un'altra Bulk o un nuovo timer identico.
Questa pulizia è condizionata al successo dei cicli; non garantisce spazio dopo
errori ripetuti e non censisce automaticamente qualsiasi file fuori pipeline.
Le ricevute dei vecchi run ordinari possono essere eliminate insieme ai loro
run: la copia privata conserva un checkpoint, non tutta la cronologia futura.

Il controllo aggiuntivo Codex `manutenzione-spazio-vps-nla` è ACTIVE con la
cadenza settimanale salvata descritta sopra.
Serve per spazio, esito retention e residui eccezionali; non invia email e non
sostituisce il monitor esterno `/opsz`, attivato e con recapito verificato il
18 ottobre. Richiede PC e app Codex accesi,
come indicato nella [documentazione delle automazioni](https://learn.chatgpt.com/docs/automations?surface=app).
La pulizia ordinaria sulla VPS non dipende dal PC. Notifiche solo per errori,
spazio sotto 6 GB decimali, calo di almeno 3 GB, interventi o decisioni necessarie;
queste sono soglie iniziali di attenzione, non garanzie di capacità.

Helper privati verificati nella cartella del checkpoint, sottocartella `evidence`:

| File | SHA256 |
| --- | --- |
| `retention_periodic_check_remote.py` | `19d48f83b715ce577259f77da8afb38ce3389449207f056f69758ab447a69422` |
| `run_remote_script.py` | `6dbebea0cac79dc8cf9253fc4c440dd51a7e03fff29ac63b87d1d0e2a2368bbc` |

Il checker legge soltanto metadati, proprietà delle unità, pointer e ricevute;
non legge segreti, non avvia job e non cancella file. Per riusarlo, copiare i due
helper in una directory temporanea nuova dopo confronto degli hash, eseguirli
con Python del progetto e conservare il JSON datato fuori Git. Il runner scrive
il risultato accanto al checker: non eseguirlo direttamente nella cartella delle
prove iniziali. Mantiene autenticazione SSH esistente e host key obbligatoria.
In caso di errore limitare la diagnosi; non stampare ambienti o URL firmati.

Per nuove rimozioni: identificare percorso e ownership, escludere riferimenti
di pointer/configurazione/container/processi, acquisire lock delle pipeline e
attivazione, rifiutare link/special file/cross-device e modifiche recenti. Spostare
in quarantena sullo stesso filesystem, conservare un piano e i metadati, verificare
readiness e richieste funzionali autenticate senza esportare i segreti, poi far
revisionare indipendentemente la procedura prima di eliminare quei soli percorsi.
Su fallimento lasciare la quarantena e una ricevuta; non ampliare automaticamente
i target. Non usare `docker prune` o cancellazioni ricorsive generiche.

## Recupero: cosa si può eseguire oggi

Prima copia privata fuori VPS:
`C:\Users\umbri\Projects\nla-catalog-gateway-staging\output\nla-recovery\20260930\`.
Non è una destinazione cloud né un backup automatico. La cartella è esclusa
da Git e protetta per proprietario Windows/SYSTEM/Administrators.

Per verificare di nuovo i dati senza sovrascrivere la prova esistente, usare
Python 3.13 già disponibile e scegliere una directory isolata nuova:

```powershell
$nlaBackup = 'C:\Users\umbri\Projects\nla-catalog-gateway-staging\output\nla-recovery\20260930'
& 'C:\Users\umbri\Projects\nla-catalog-gateway-staging\.venv\Scripts\python.exe' `
  "$nlaBackup\evidence\restore_offline.py" `
  "$nlaBackup\catalog-ledger-checkpoint.tar.gz" `
  '620c88e326bf949e345cc7afc49fc922b407ca56d2b10c4cd8ff7f23401ef79d' `
  "$nlaBackup\restored-operator-check"
```

La procedura verifica l'hash prima di estrarre, rifiuta una destinazione già
esistente, confronta tutti i membri, esegue SQLite `quick_check` e registra conte.
La prova già eseguita ha impiegato 68,541 s. Non occorre ripeterla senza motivo.
Il ledger è uno snapshot SQLite separatamente consistente: prima di riattivare
l'importer occorre riconciliare lo stato Shopify corrente con le sue identità.

Per il recupero del servizio, l'immagine e i sorgenti installati sono salvati
nella cartella privata del checkpoint, con hash nell'evidenza. Il primo errore
locale al socket e il successivo load con output ID differente sono conservati
come tentativi storici. L'equivalenza è stata dimostrata verificando la catena
OCI del manifest, config e layer contro l'immagine locale ispezionata; il pin del
config non è stato sostituito. Il seed nel volume isolato è passato per 12 file,
tre SQLite `quick_check` e permessi/ownership, ma il wrapper si è fermato perché
la memoria disponibile dopo il seed era 2.090.254.336 byte, sotto la soglia di
2.415.919.104 byte. Docker Desktop è ora attivo (Engine 29.7.2, Linux/amd64,
4 CPU, 3.001.667.584 byte RAM); la misura successiva era ancora sotto soglia.
Il volume nominato e il container seed arrestato sono preservati per ripresa;
nessun runtime applicativo è stato creato o avviato. Questi sono dati storici:
il controllo del 17 ottobre registra 506.658.816 byte di RAM libera e pipe
Docker Desktop assente. Il blocco corrente è la disponibilità di risorse,
non un nuovo consenso dopo D-023. Nessuna impostazione è stata modificata;
preservare dati e applicazioni durante l'eventuale preparazione della prova.

Nuova prova PC del 3 ottobre: checkpoint copiato alle 10:11:07 UTC
(222.535.954 byte, SHA-256
`93a7d1c6601f0c62f2d94098f94e539babb16241adfc85c915312038c9026713`) e restore
offline PASS in 49,826 s: 12 file, tre database `quick_check`, 295.975 prodotti
e 298.046 varianti per ciascuna delle generazioni corrente e precedente;
ledger con 4.180 draft attempts e 4.180 draft publications. Checkpoint/seed del
30 settembre invariati. Questa acquisizione non è atomica tra catalogo e ledger,
non è backup automatico/durevole e non certifica RTO completo. Preflight memoria
alle 09:58:17: 2.378.674.176 byte disponibili, sotto il minimo 2.415.919.104;
limiti invariati, seed fermo, nessun nuovo container avviato. La misura di quella
prova e il blocco di risorse sono nell'[evidenza](evidence/BACKUP-PC-2026-10-03.md).

Il precedente [drill sulla VPS](evidence/RECOVERY-LINUX-2026-09-30.md) ha superato restore
dati, ammissione del gateway e prove HTTP/carico limitato sulla stessa VPS,
con job inattivi e risorse verificate. Il primo avvio con 1 GiB è terminato OOM;
il secondo con 2 GiB/0,5 CPU è stato osservato pronto dopo 20 minuti e 19 secondi.
Il tempo include validazione integrale; non usarlo come garanzia RTO né dedurre
capacità di produzione dal piccolo carico loopback. Usare nuovi percorsi,
identità e ricevute per nuove prove; verificare risorse prima dell'avvio e
conservare anche i fallimenti. Un nuovo tentativo richiede diagnosi, preflight
e review tecnica indipendente, senza una nuova richiesta di consenso al
titolare; evitare aumenti automatici dei limiti o riavvii in sequenza.

Il drill PC resta rinviato su indicazione di Jacopo: non ripetere misure RAM
o richieste di chiudere applicazioni senza una nuova disponibilità. Per la fase
corrente si usa il [drill applicativo isolato del 18 ottobre](evidence/RECOVERY-APPLICATION-2026-10-18.md)
sulla VPS ammessa, con configurazione recuperata e prova TLS separata. Restano
fuori dal collaudo provisioning di un host nuovo, percorso pubblico DNS/App
Proxy e riattivazione di refresh/importer: sono limiti della prova, non nuovi
requisiti da aggiungere a questa fase. Qualsiasi passaggio live resta soggetto
alle autorizzazioni applicabili.

La [prova reference sul PC](evidence/REFERENCE-RECOVERY-2026-10-01.md) ha superato
la validazione integrale delle 336.752 identità salvate e l'accettazione della
configurazione tramite i sorgenti installati `881b9ca`. Ha rimappato solo i cinque
percorsi in un'area temporanea privata, mantenendo identità e pin. La verifica
offline ha richiesto 23,164 s, con picco memoria 302.075.904 byte; il contenitore
aveva 768 MiB, filesystem in sola lettura e rete disabilitata. Nessun client
Shopify o ciclo di acquisizione è stato eseguito. Le ricevute e gli helper con
hash sono nella cartella privata `evidence/reference-offline-closed` del backup.
Riutilizzare questa prova; per un nuovo checkpoint scegliere nuove identità e
percorsi, verificare i pin e ottenere review prima di eseguire gli helper.

## Backblaze: prima copia e verifica del 3 ottobre

Destinazione scelta da Jacopo: bucket privato `nla-catalog`, regione
`eu-central-003`, cifratura SSE-B2/AES256. Il checkpoint PC del mattino è stato
caricato e riscaricato integralmente: SHA-256 e SHA-1 coincidono. Il restore
della copia cloud ha superato hash, dimensioni e tre SQLite `quick_check`
in 61,970 secondi dopo il controllo iniziale dell'archivio.
Vedi [ricevute, pin e limiti](evidence/BACKBLAZE-2026-10-03.md).

Gli helper sono in `output/nla-recovery/20260930/backblaze-setup/`, privata e
ignorata da Git. La chiave è in `credentials.clixml`, cifrata tramite DPAPI
per l'utente Windows; non copiarla in documenti, log o repository. Non è
installata sulla VPS in quella prova del 3 ottobre; il trasferimento successivo
è autorizzato da D-021 e registrato sotto. Il prompt console iniziale aveva registrato Ctrl+V:
`save-key.ps1` ora apre due campi mascherati e rifiuta caratteri di controllo.
Il file non valido è conservato separatamente; non va riutilizzato.

Per una diagnosi autorizzata, verificare prima lo SHA-256 documentato di
`check-connection.ps1`, poi eseguirlo come proprietario con Windows PowerShell
tramite il percorso completo dell'eseguibile e `-NoProfile -ExecutionPolicy
RemoteSigned -File`. Effettua solo tre richieste di lettura e salva una nuova
ricevuta priva di segreti. Non indebolire gli ACL della cartella per eseguirlo.

`upload-checkpoint.ps1` è una procedura per il checkpoint fissato del 3 ottobre:
controlla hash/dimensione dell'originale, verifica o crea l'oggetto con nome
derivato dall'hash e lo riscarica in un nuovo file. Non usarla come backup
periodico dei dati correnti. Il restore usa una copia invariata di
`restore_offline.py`, hash dell'archivio atteso e destinazione nuova.

Questa prova ha chiuso la scelta della destinazione e la prima copia cloud dei
dati. Il successivo servizio cifrato sulla VPS, descritto sotto, cattura anche
configurazione e immagini. Le copie sono protette; stato del recupero isolato e
limiti sono nella [prova del 18 ottobre](evidence/RECOVERY-APPLICATION-2026-10-18.md).
Il bucket non ha regole lifecycle; nessuna scadenza delle copie è stata impostata.

## Backup cifrato: pilota verificato il 15 ottobre

La [prova S3](evidence/BACKUP-ENCRYPTION-2026-10-15.md) ha verificato restic
0.19.1, cifratura prima del trasferimento, controllo integrale del repository e
recupero su PC con hash identico. Il repository separato è
`s3:https://s3.eu-central-003.backblazeb2.com/nla-catalog/nla/restic-v1`.
La copia è ancora il checkpoint del 3 ottobre; il pilota non va schedulato.

Helper privato: `output/nla-recovery/20260930/backup-automation-20261015/restic-pilot.ps1`,
SHA-256 `1ee73777e5af520597c2226e0094210e08ccbc1f02f9e60e0cf7e525fa1e0592`.
Verificare questo hash prima di eseguirlo. `Init` è già completato e rifiuta
una password esistente: non cancellare `password.clixml` per forzarlo.
Nella prova iniziale la password era protetta da DPAPI e dagli ACL del PC,
senza custodia indipendente. In quella prova non era sulla VPS; è stata
successivamente installata con autorizzazione D-021, descritta sotto.

Il 17 ottobre Jacopo ha scelto 1Password e confermato il salvataggio della
password Restic (D-025). La custodia è attestata dal titolare; il drill usa la
copia operativa autorizzata e non verifica la lettura manuale dal gestore.
Non ripetere la procedura di salvataggio. Voce indicata nella procedura:
`NLA — Recupero backup Backblaze`; conservare anche l'URL del repository sopra.
L'helper privato `copy-recovery-password.ps1`, accanto a `password.clixml`, è
destinato all'esecuzione manuale del titolare: copia la password esistente negli
appunti, esclude cronologia/sincronizzazione Windows per quel contenuto e,
dopo il salvataggio manuale in 1Password, pulisce gli appunti se ancora uguali.
Non automatizza 1Password e non cambia la password. La modalità `-ValidateOnly`
non legge il segreto e non scrive negli appunti.
Helper SHA-256 `14ef89f114ee11ea199e9c59998784dcb4a496ceb6893bebaf3d044faf038808`;
review indipendente senza rilievi bloccanti e validazione sintetica PASS con
Windows PowerShell 5.1.26100.9711, anche tramite avvio da PowerShell 7.
Nessuna password è stata letta o copiata durante la validazione dell'agente.
Jacopo ha successivamente confermato «salvata» per la password Restic, distinta
dalle credenziali Backblaze già custodite. Non ripetere il trasferimento.

Per un recupero successivo autorizzato, usare `VerifyRestore` con l'ID completo
dello snapshot riportato nella prova e una nuova directory diretta sotto
`backup-automation-20261015/restores/`. L'helper richiede la ricevuta di backup
riuscita, ripristina solo la sottocartella del checkpoint, rifiuta sovrascritture
e controlla l'hash. Non esegue un recupero del runtime o dei segreti applicativi.
Eseguire come proprietario con Windows PowerShell tramite percorso completo,
senza indebolire ACL. Le ricevute precedenti restano conservate.

La prova pilota non catturava i dati correnti della VPS. La successiva prima
cattura completa cifrata e lo scheduler attivo dal 17 ottobre sono descritti
sotto; la custodia in 1Password è confermata dal titolare. Il primo ciclo
automatico è verificato il 18 ottobre, come documentato nella sezione dedicata.
Nessuna rimozione cloud, policy di retention o modifica lifecycle è stata attivata.

L'[inventario cloud del 17 ottobre](evidence/CLOUD-RETENTION-2026-10-17.md)
conferma quattro snapshot e la copia manuale, 622.179.661 byte complessivi negli
upload completati. Conservare queste copie; zero candidati alla rimozione ora.
La proposta di rotazione e i vincoli di raggruppamento restic sono nell'evidenza;
non usare il default per percorso, perché ogni job ha un percorso diverso.

Il codice del nuovo servizio è nella PR #113, con CI Linux e review indipendente
passate. Anche la prova sintetica nel sandbox systemd reale è passata: lettura
del ledger WAL riuscita, scrittura ai sorgenti respinta, unità e fixture proprie
rimosse. [Versione, pin e limiti](evidence/BACKUP-AUTOMATION-2026-10-15.md).
Jacopo ha autorizzato il trasferimento delle credenziali (D-021). Il 17 ottobre
la versione `b56ca95` ha completato il nuovo job
`backup-c121a380661d4bbfa6b6c0c5de1a09b4`, con controllo `read-data` PASS,
ricevuta per-job coincidente con `last-success` e staging del job rimosso.
`nla-backup-offsite.timer` è abilitato e attivo: ogni giorno alle **01:00 UTC**,
`Persistent=no`; prima scadenza osservata 18 ottobre 01:00 UTC. L'attivazione
è distinta dalla successiva prova del ciclo automatico del 18 ottobre.

Il difetto corretto confrontava i montaggi Docker dipendendo dall'ordine della
lista, che può cambiare senza modifiche ai montaggi. Il comportamento è stato
riprodotto sulla VPS; l'istante preciso del precedente errore `971c` resta non
osservato. Il relativo payload fallito è stato prima messo in quarantena,
verificato con il catalogo operativo e revisionato indipendentemente, poi rimosso:
743 file, 2.126.986.835 byte. Ricevuta di errore e prove restano conservate.
Alle 07:16 UTC il controllo finale rilevava 13.249.085.440 byte liberi, market e
refresh riusciti, puntatore e generazioni protette invariati. Versioni, hash,
limiti di capacità e ricevute sono nell'[evidenza aggiornata](evidence/BACKUP-AUTOMATION-2026-10-15.md).

Alle 08:18 UTC la sonda operativa è stata attivata: GET/HEAD
`https://catalog-staging.nextlevelarena.it/opsz` restituiscono l'esito generico
della salute operativa. Il backup più recente è ora `backup-919aeddea561432c9da028bd7e3ff6e8`,
snapshot `ffa29faf98aecfc61a39c2ad52f9bc69803a3b479e2cc877fa7a87297ef43cf8`,
ricevuta `ce6018583f3d7369d36f97d9a09bf453748a60f8575f4ed8fad49ebad148b4e6`.
La configurazione attiva `54a376a4…` include le tre unità installate e il nuovo
Caddyfile `ef4c3fa2…`; il timer backup è enabled/waiting dopo `read-data` PASS.
Alla verifica delle 08:18 del 17 ottobre, questa versione non copriva ancora
errori/anzianità backup o abilitazione timer; la copertura è stata aggiunta e
installata nel rollout PR #114 riportato sotto. Per l'attivazione iniziale,
il rollback del primo tentativo e i limiti del recapito
vedere [attivazione health](evidence/OPERATIONAL-HEALTH-2026-10-15.md).

### Osservabilità backup aggiornata — PR #114, 17 ottobre

Il collector è installato nel package `/opt/nla-operational-observer-319ca0b`
con nuova unità e pin di cattura backup. Installazione, compile/import, unità,
due osservazioni healthy e GET/HEAD loopback/pubblico sono PASS. Il controllo
allerta su service
failure, confronto di `last-success` con ricevuta immutabile per-job e
validazione dei campi snapshot (senza interrogazione remota), checkpoint oltre
26 h, staging residuo limitato, e timer market,
refresh e backup abilitati/attivi. La soglia checkpoint è un trigger di allarme,
non un RPO. È consentita la pausa refresh controllata dal market; HTTP mantiene
risposta generica. La lettura usa elapsed monotonic per evitare allarmi se il
backup si completa durante il controllo; mtime è solo evidenza di tempo, non
ownership del processo. La cattura del 17 ottobre alle 08:18 resta l'ultima
verificata e non include il nuovo observer (`backedUp=false`). Timer successivo
previsto il 18 ottobre alle 01:00 UTC e non ancora osservato. Dopo la cattura,
verificare identità e pin senza avviare un backup manuale. Email/UptimeRobot
restano da verificare.
Pin, hash, controlli e limiti: [evidenza health/backup](evidence/BACKUP-HEALTH-2026-10-17.md).

### Primo backup automatico verificato — 18 ottobre

Il timer ha avviato il backup alle 01:00:12 UTC; conclusione alle 01:01:33 UTC
con `read-data` PASS. Nuovo snapshot `9fc4fe1…`: manifest remoto verificato,
include package observer `319ca0b` e unità con i pin attesi. La previsione di
prima cattura ancora pendente nella sezione storica precedente è superata.
Timer in attesa del 19 ottobre alle 01 UTC; nessun backup manuale avviato.
GET e HEAD pubblici su `/opsz` sono 200 dopo il backup. Conservare anche questo
snapshot come prova; la retention cloud resta inattiva. [Ricevute e limiti](evidence/BACKUP-SCHEDULED-2026-10-18.md).

### Prova limitata del percorso HTTPS — 17 ottobre

La [prova delle 10:06 UTC](evidence/PUBLIC-GATEWAY-2026-10-17.md) ha verificato
54 richieste sulla generazione live, incluse 40 letture con massimo due
concorrenti. Pipeline inattive, timer pronti e invarianti preservati; P95
131,128 ms dalla VPS al proprio nome pubblico. Non è un controllo periodico
né una certificazione della navigazione Shopify o della capacità massima.
Conservare questa ricevuta e ripetere solo per una modifica o lacuna concreta,
con nuovi pin revisionati e ammissione sicura. Un'unità backup mai eseguita può
avere timestamp vuoti: confrontare marcatori prima/dopo e ricevuta manuale
separatamente; non dichiarare il primo ciclo schedulato già provato.

## Decisioni e obiettivi da chiudere

| Voce | Situazione | Proposta verificabile |
| --- | --- | --- |
| Destinazione durevole | Backblaze scelto dal proprietario il 3 ottobre; bucket privato, backup automatico e recupero applicativo delle due generazioni verificati il 18 ottobre | Le prove coprono il recupero isolato con i limiti dichiarati. [Prima copia](evidence/BACKBLAZE-2026-10-03.md), [recupero applicativo](evidence/RECOVERY-APPLICATION-2026-10-18.md) |
| Backup automatico e retention | Primo ciclo automatico riuscito il 18 ottobre, `read-data` PASS, observer incluso nel manifest. Copie cloud conservate; preparazioni di rotazione soltanto locali | Preservare i quattro ID storici e lo snapshot `9fc4fe1…`. La rotazione cloud resta opzionale e inattiva; nessuna copia rimossa. [Primo ciclo](evidence/BACKUP-SCHEDULED-2026-10-18.md), [piano cloud](evidence/CLOUD-RETENTION-2026-10-17.md), [esecutore opzionale](evidence/RETENTION-EXECUTOR-2026-10-17.md) |
| Credenziali e reference | Reference, dati, configurazione e TLS recuperati e verificati. Il 18 ottobre runtime current e previous con ambiente effettivo del backup PASS e chiusi; copie isolate eliminate dopo revisione. Password Restic custodita in 1Password secondo Jacopo (D-025) | Il drill usa la copia operativa autorizzata della password; non prova la lettura manuale della voce nel gestore. Custodia attestata e recupero applicativo sono prove distinte, senza imporre una nuova richiesta al titolare. Nessun segreto in Git/documenti. [Materiali](evidence/RECOVERY-MATERIALS-2026-10-18.md), [applicazione](evidence/RECOVERY-APPLICATION-2026-10-18.md) |
| RPO | Scheduler giornaliero e primo ciclo automatico verificati; sorgente del checkpoint del 18 ottobre vecchia di 10 ore e 18,741959 secondi alla cattura. Recapito TEST provato; monitor `/opsz` UP confermato | Refresh alle 03/15 UTC e backup alle 01 UTC portano la sorgente recuperabile vicino a 34 ore prima della copia successiva, oltre ai tempi dei job. Obiettivo proposto: entro 36 ore in esercizio regolare, sostituendo la precedente proposta di 24 ore; non è una garanzia in caso di cicli saltati o falliti. Freschezza ordinaria 24 ore e soglia alert backup 26 ore restano distinte dall'RPO. [Misura e calcolo](evidence/RECOVERY-APPLICATION-2026-10-18.md) |
| RTO | Il 18 ottobre restore dati verificato in 62,909634 s; runtime current e previous PASS, 20 letture complessive e chiusura verificata. Dal download: circa 25m14s fino a current, 45m29s fino a entrambe le generazioni; pulizia esclusa | Budget proposto: 2 ore su Linux già pronto, con accessi disponibili. Rilevamento, presa in carico, provisioning e percorso pubblico aggiungono tempi non misurati. Il drill isolato sulla VPS non certifica un host vuoto o un RTO completo. [Misure e limiti](evidence/RECOVERY-APPLICATION-2026-10-18.md) |
| Alert e reperibilità | Jacopo è il referente iniziale; email TEST DOWN/UP verificate in Gmail; monitor `/opsz` UP confermato dal titolare, GET/HEAD 200 verificati dall'agente | Canale configurato e recapito collaudato. Non ripetere attivazione, test email o cambio URL. [Prova e limiti](evidence/ALERT-DELIVERY-2026-10-18.md) |
| Recupero trigger persi | `Persistent=no` osservato | Valutare `Persistent=yes` e prova isolata dopo verifica dei vincoli di locking/overlap; nessun timer cambiato ora |

Le proposte non sono SLA né assegnazioni implicite. PM e operatori conservano
versione, comandi, ricevute, tempi, limitazioni e decisioni nel resoconto.
