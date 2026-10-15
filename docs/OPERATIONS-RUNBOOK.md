# Runbook operativo NLA

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
2. Il catalogo ha una tolleranza concordata di 24 ore. Calcolare l'età dalla
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
| Problema tema | Conservare inventari e prove; precedente 175194898700 è UNPUBLISHED | Ripubblicazione, nuovo cutover o password richiedono Jacopo; non correggere il MAIN 175195881740 |

Non esiste una prova di recapito degli alert. `OnFailure` è vuoto nelle unità
NLA e non risultano unità o nomi di file cron NLA per monitor fra quelli censiti.
Il monitor esterno proposto e la sua attivazione sono descritti sotto. Una futura prova dovrà
inviare un messaggio identificabile al destinatario autorizzato, conservarne
esito e ricezione e verificare deduplicazione. È stata autorizzata e richiesta
la sola email di attivazione UptimeRobot; nessun messaggio di prova di guasto
è stato inviato.

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
Un HTTP 200 del provider non prova creazione o recapito: può indicare anche
una richiesta ignorata. Occorrono attivazione del proprietario, configurazione
effettiva e prova concordata senza guasti sul live. Il link scade dopo 24 ore:
Jacopo apre l'email e preme Activate nella pagina di conferma. Non reinviare
automaticamente una richiesta dall'esito non verificato.
Ricevuta privata in `output/nla-recovery/20260930/alert-activation-20261015T134927Z-f53333c3/receipt.json`.
Quando Jacopo conferma l'email, configurare e verificare il monitor con metodo
GET esplicito: [UptimeRobot usa HEAD di default e GET al retry](https://help.uptimerobot.com/en/articles/11358466-how-to-debug-a-monitor-showing-as-down-in-uptimerobot),
mentre `/readyz` ha risposto GET 200 e HEAD 404 alla sonda read-only del 15
ottobre. Non reinviare l'email.
L'indirizzo è modificabile dalle impostazioni dell'account; il
[cambio email](https://help.uptimerobot.com/en/articles/11582766-how-to-change-your-uptimerobot-account-email-or-username)
richiede conferma tramite il vecchio indirizzo. Non è una modifica del codice NLA.
La readiness dal PC, con TLS validato e senza redirect, è risultata 200/ready
alle 17:06 UTC. Questo è un controllo singolo, non un monitor configurato.

## Retention e controllo ogni 48 ore

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

Il controllo aggiuntivo Codex `manutenzione-spazio-vps-nla` è ACTIVE ogni 48 ore.
Serve per spazio, esito retention e residui eccezionali; non invia email e non
sostituisce il monitor esterno ancora da attivare. Richiede PC e app Codex accesi,
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
nessun runtime applicativo è stato creato o avviato. Non fare reset, cambiare
limiti o cancellare dati senza decisione e review. È pendente la scelta asincrona
di Jacopo fra preparare un riavvio concordato con 4 GB per Docker Desktop o
rinviare; nessuna impostazione è stata modificata.

Nuova prova PC del 3 ottobre: checkpoint copiato alle 10:11:07 UTC
(222.535.954 byte, SHA-256
`93a7d1c6601f0c62f2d94098f94e539babb16241adfc85c915312038c9026713`) e restore
offline PASS in 49,826 s: 12 file, tre database `quick_check`, 295.975 prodotti
e 298.046 varianti per ciascuna delle generazioni corrente e precedente;
ledger con 4.180 draft attempts e 4.180 draft publications. Checkpoint/seed del
30 settembre invariati. Questa acquisizione non è atomica tra catalogo e ledger,
non è backup automatico/durevole e non certifica RTO completo. Preflight memoria
alle 09:58:17: 2.378.674.176 byte disponibili, sotto il minimo 2.415.919.104;
limiti invariati, seed fermo, nessun nuovo container avviato. Decisioni del
proprietario ancora pendenti. Vedi [evidenza](evidence/BACKUP-PC-2026-10-03.md).

Il precedente [drill sulla VPS](evidence/RECOVERY-LINUX-2026-09-30.md) ha superato restore
dati, ammissione del gateway e prove HTTP/carico limitato sulla stessa VPS,
con job inattivi e risorse verificate. Il primo avvio con 1 GiB è terminato OOM;
il secondo con 2 GiB/0,5 CPU è stato osservato pronto dopo 20 minuti e 19 secondi.
Il tempo include validazione integrale; non usarlo come garanzia RTO né dedurre
capacità di produzione dal piccolo carico loopback. Usare nuovi percorsi,
identità e ricevute per nuove prove; verificare risorse prima dell'avvio e
conservare anche i fallimenti. Un nuovo tentativo richiede diagnosi, preflight
e review; evitare aumenti automatici dei limiti o riavvii in sequenza.

Per completare il drill PC, attendere la decisione pendente e ripetere il
preflight delle risorse prima di creare un runtime isolato; non riavviare
automaticamente il seed già concluso. Le prove positive richieste per un eventuale
runtime non sono ancora state eseguite. Restano da collaudare il recupero
operativo su host nuovo, credenziali, TLS/DNS/App
Proxy e refresh/importer. Solo dopo le prove si prepara un eventuale passaggio
live con autorizzazioni applicabili. Catalogo e ledger da soli non ricostruiscono
l'intero sistema.

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

Questa prova chiude la scelta della destinazione e la prima copia cloud dei
dati. Restano scheduler sulla VPS, gestione errori, conservazione, copertura
di configurazione/immagini/accessi e recupero completo del servizio.
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
La password è protetta da DPAPI e dagli ACL del PC; non è ancora custodita
indipendentemente dall'utente/PC. In quella prova non era sulla VPS; è stata
successivamente installata con autorizzazione D-021, descritta sotto.

Per un recupero successivo autorizzato, usare `VerifyRestore` con l'ID completo
dello snapshot riportato nella prova e una nuova directory diretta sotto
`backup-automation-20261015/restores/`. L'helper richiede la ricevuta di backup
riuscita, ripristina solo la sottocartella del checkpoint, rifiuta sovrascritture
e controlla l'hash. Non esegue un recupero del runtime o dei segreti applicativi.
Eseguire come proprietario con Windows PowerShell tramite percorso completo,
senza indebolire ACL. Le ricevute precedenti restano conservate.

La prova pilota non catturava i dati correnti della VPS. La successiva prima
cattura completa cifrata è descritta sotto; restano custodia della password,
scheduler e prove dei fallimenti prima di dichiarare il backup automatico.
Nessuna rimozione cloud, policy di retention o modifica lifecycle è stata attivata.

Il codice del nuovo servizio è nella PR #113, con CI Linux e review indipendente
passate. Anche la prova sintetica nel sandbox systemd reale è passata: lettura
del ledger WAL riuscita, scrittura ai sorgenti respinta, unità e fixture proprie
rimosse. [Versione, pin e limiti](evidence/BACKUP-AUTOMATION-2026-10-15.md).
Jacopo ha autorizzato il trasferimento delle credenziali (D-021). `/etc/nla-backup`
è root 0700, file credenziali 0600; configurazione e unità sono verificate.
Primo backup corrente terminato alle 13:30:23 UTC con `read-data` passato e
staging rimosso; spazio libero 10.672.623.616 byte alle 13:33 UTC.
Il timer resta disabilitato: chiudere recupero applicativo e margine disco per
upload lunghi/falliti prima di abilitarlo. Non usare il vecchio pilota come job
periodico e non ripetere i trasferimenti delle credenziali già riusciti.

## Decisioni e obiettivi da chiudere

| Voce | Situazione | Proposta verificabile |
| --- | --- | --- |
| Destinazione durevole | Backblaze scelto dal proprietario il 3 ottobre; prima copia nel bucket privato, download e restore dati verificati | Scelta e primo trasferimento conclusi; restano copertura completa e conservazione delle copie. [Prova Backblaze](evidence/BACKBLAZE-2026-10-03.md) |
| Backup automatico e retention | Servizio installato e prima copia corrente verificata; timer disabilitato, retention cloud non attiva | Chiudere recupero applicativo e margine disco in caso di errore prima dell'attivazione periodica; definire conservazione |
| Credenziali e reference | Reference completa e configurazione restaurata accettate offline; credenziali/certificati esclusi | Collaudare il ciclo refresh/importer con accessi recuperati; definire conservazione cifrata e recupero degli accessi, senza segreti in Git/documenti |
| RPO | Nessun RPO garantito dal backup manuale | Proposta iniziale: massimo 24 ore per copie fuori host, coerente con tolleranza del catalogo; richiede scheduler e prova dei fallimenti |
| RTO | Restore dati PC: 49,826 s; copia riscaricata da Backblaze: 61,970 s; reference storico: 23,164 s. Questi tempi escludono trasferimenti e avvio del runtime; nessun RTO completo certificato | Budget proposto: 2 ore su host Linux già pronto, escluso provisioning/DNS; serve prova completa con immagine/credenziali, oggi non garantito. [Prova Backblaze](evidence/BACKBLAZE-2026-10-03.md) |
| Alert e reperibilità | Jacopo referente; richiesta di attivazione UptimeRobot autorizzata e inviata, recapito e monitor ancora da verificare | Conferma del proprietario nell'email; poi verifica configurazione e prova di alert concordata; completare copertura refresh/freschezza |
| Recupero trigger persi | `Persistent=no` osservato | Valutare `Persistent=yes` e prova isolata dopo verifica dei vincoli di locking/overlap; nessun timer cambiato ora |

Le proposte non sono SLA né assegnazioni implicite. PM e operatori conservano
versione, comandi, ricevute, tempi, limitazioni e decisioni nel resoconto.
