# Runbook operativo NLA

Aggiornato il 3 ottobre 2026. Stato e prove:
[manutenzione del 30 settembre](evidence/MAINTENANCE-2026-09-30.md) e
[recupero PC](evidence/RECOVERY-PC-2026-10-01.md),
[checkpoint PC del 3 ottobre](evidence/BACKUP-PC-2026-10-03.md),
[incidente refresh del 3 ottobre](evidence/INCIDENT-2026-10-03.md) e
[ripresa GitHub](evidence/GITHUB-RESUME-2026-10-03.md).
PM della fase: Codex. Operatore continuativo e destinatari degli alert da
assegnare da Jacopo; questo documento non crea un servizio di reperibilità.
Il 3 ottobre il refresh ordinario `20261003t073240z-3f7384f8` è terminato exit 0
alle 09:12:19 UTC; freshness, pointer, smoke e retention periodica sono passati.
Spazio finale 11.782.266.880 byte. Seguire la
[timeline dell'incidente](evidence/INCIDENT-2026-10-03.md) per ricevute, hash e
limite dei 6 GiB pre-cattura (non garantisce il picco di spazio).

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
Rimane possibile un monitor esterno da identificare. Una futura prova dovrà
inviare un messaggio identificabile al destinatario autorizzato, conservarne
esito e ricezione, verificare deduplicazione e chi interviene. Nessun messaggio
a terzi è stato inviato in questa fase.

Per la scelta del proprietario, il pacchetto minimo proposto segnala servizio
irraggiungibile, refresh fallito e sorgente oltre 24 ore. Un guasto va confermato
con controlli ripetuti prima di notificare; un job ancora in corso non deve
generare un falso alert di errore. Il messaggio deve dire cosa è accaduto,
da quando, ultimo aggiornamento valido e prima azione utile; inviare il rientro
alla normalità e contenere i duplicati. Nessun riepilogo periodico non richiesto.

Jacopo ha scelto l'email come canale iniziale il 30 settembre. Indirizzo,
servizio di invio, autenticazione e costi non sono ancora verificati;
la scelta del canale non dimostra il recapito. Il destinatario e il referente possono coincidere
con Jacopo, solo se lo conferma. Il referente prende in carico la segnalazione
e decide chi interviene; non implica che debba risolvere ogni problema da solo.

Il monitor di raggiungibilità deve essere fuori dalla VPS per segnalare anche
la sua perdita. Un monitor sullo stesso host può rilevare errori dei job mentre
l'host funziona, ma non inviare un alert dopo il proprio spegnimento. Il PC è
disponibile per la prima copia; non è ancora dichiarato un presidio sempre acceso.

Proposta pronta per il solo controllo esterno di raggiungibilità: UptimeRobot
Free, `https://catalog-staging.nextlevelarena.it/readyz`, HTTPS ogni cinque minuti,
email di down/up al recapito confermato. Il [piano gratuito](https://help.uptimerobot.com/en/articles/11604710-who-should-use-uptimerobot-s-free-plan)
è ammesso anche per uso commerciale, senza carta; il [recapito email personale](https://help.uptimerobot.com/en/articles/11360953-uptimerobot-personal-notification-channels-setup-guide)
è uno per utente. Costi/limiti verificati il 30 settembre: zero euro/mese,
50 monitor, intervallo cinque minuti; non garantisce rilevazione entro cinque minuti.
Non copre da solo refresh falliti o dati vecchi con readiness ancora positiva.

La [skill ufficiale quick-monitor-setup](https://github.com/uptimerobot/ai/blob/main/skills/quick-monitor-setup/SKILL.md)
è stata letta per preparare il flusso senza installare plugin o chiedere API key.
Richiede URL e indirizzo identici nel challenge e nella richiesta; difficulty
letto dalla risposta, proof-of-work SHA256, poi invio della richiesta e conferma
dell'email da parte del proprietario. Non è stata fatta alcuna richiesta di
attivazione: mancano indirizzo e autorizzazione a inviare quell'email. Un HTTP 200
del provider non proverebbe creazione o recapito: occorrono attivazione del
proprietario, configurazione effettiva e prova concordata senza guasti sul live.
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

## Decisioni e obiettivi da chiudere

| Voce | Situazione | Proposta verificabile |
| --- | --- | --- |
| Destinazione durevole | Prima copia su PC pronta e scelta confermata da Jacopo il 30 settembre; spazio definitivo sarà indicato dal proprietario | Il PC non aggiunge una sottoscrizione; costi di un eventuale provider vanno verificati prima della scelta |
| Backup automatico e retention | Non configurati | Copia dopo ciclo riuscito, verifica hash/restore, retention da approvare; misurare quanto rimane recuperabile se un ciclo fallisce |
| Credenziali e reference | Reference completa e configurazione restaurata accettate offline; credenziali/certificati esclusi | Collaudare il ciclo refresh/importer con accessi recuperati; definire conservazione cifrata e recupero degli accessi, senza segreti in Git/documenti |
| RPO | Nessun RPO garantito dal backup manuale | Proposta iniziale: massimo 24 ore per copie fuori host, coerente con tolleranza del catalogo; richiede scheduler e prova dei fallimenti |
| RTO | Restore dati PC 3 ottobre: 49,826 s; restore reference storico: 23,164 s. Non è stato avviato runtime PC, quindi nessun RTO completo certificato. Restano distinti gli esiti del drill Linux VPS | Budget proposto: 2 ore su host Linux già pronto, escluso provisioning/DNS; serve prova completa con immagine/credenziali, oggi non garantito. [Nuova prova PC](evidence/BACKUP-PC-2026-10-03.md) |
| Alert e reperibilità | Email scelta; indirizzo, recapito e referente ancora da confermare | PM verifica servizio/costi e prepara configurazione; prova identificabile al destinatario dopo autorizzazione |
| Recupero trigger persi | `Persistent=no` osservato | Valutare `Persistent=yes` e prova isolata dopo verifica dei vincoli di locking/overlap; nessun timer cambiato ora |

Le proposte non sono SLA né assegnazioni implicite. PM e operatori conservano
versione, comandi, ricevute, tempi, limitazioni e decisioni nel resoconto.
