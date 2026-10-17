# Alert operativi — preparazione del 15 e attivazione del 17 ottobre 2026

Workstream #13, candidato [PR #114](https://github.com/cajopo/nla-catalog-gateway-staging./pull/114)
al commit `59a74e60edd967dc27e65fd95ac2a390eb619961`. Questa evidenza distingue
la preparazione dalla messa in esercizio e dal recapito email.

## Copertura e recapito

Jacopo ha scelto l'email, autorizzato l'attivazione UptimeRobot e accettato il
ruolo di referente iniziale. La richiesta del 15 ottobre alle 13:49:32 UTC ha
ricevuto HTTP 200 e stato `ok`. Jacopo ha successivamente confermato in chat
di avere ricevuto e attivato l'email e di essere entrato nella dashboard.
L'ispezione della dashboard è stata fermata da Computer Use perché non poteva
verificare l'URL corrente su Windows. La conferma del proprietario è registrata;
stato, metodo HTTP, intervallo e contatto del monitor non sono ancora verificati
direttamente. Non reinviare l'attivazione senza una nuova necessità.
Il destinatario è modificabile; il recapito degli alert resta da collaudare.

Il controllo iniziale di `/readyz` copre la raggiungibilità. Il nuovo componente
espone `/opsz`, attivato il 17 ottobre: il collector legge lo stato dei processi, le ricevute, la
freschezza del catalogo e lo spazio disponibile; un processo separato espone
solo un esito generico. Una lettura scaduta oltre 90 secondi produce 503.
Un refresh in corso non è automaticamente un errore. Restano fuori da questa
copertura la frequenza dei 5xx, la latenza, CPU/memoria e l'abilitazione dei timer.
Il collector `59a74e6` controlla market e refresh, ma non fallimenti o anzianità
del backup. Il limite di 90 secondi riguarda l'osservazione del collector, non
l'età del backup: questa copertura resta un lavoro separato.
L'endpoint e il codice da soli non costituiscono una catena di alert verificata.

## Preparazione riproducibile

Alle 15:53:06 UTC il preflight read-only ha verificato Python 3.12.3 e systemd
255 sulla VPS. Uvicorn ed ensurepip erano assenti; la porta loopback 10002 era
libera. Il refresh delle 15 UTC era in corso, con processo presente: nessun suo
avvio, arresto o riavvio è stato eseguito per questa preparazione.

Il pacchetto locale contiene cinque file di codice esatti dal commit della PR,
93 file di dipendenze e tre unità renderizzate. Le dipendenze pure Python sono
Uvicorn 0.52.4, Click 8.5.0 e h11 0.16.0, con hash verificati sui metadata PyPI.
Non è richiesto un aggiornamento dei pacchetti Python di sistema.

Manifest del pacchetto:
`14a735974e240945a3401e03ed1cd332f3772f2c4e632384a56ca9fde5b603c3`.
La verifica indipendente locale ha confrontato tutti i 101 file, i sorgenti Git,
le unità renderizzate e gli archivi. La destinazione prevista è
`/opt/nla-operational-health-59a74e6`; le unità restano sotto `units/` durante
la preparazione, senza attivare servizi o timer.

Gli artefatti riproducibili sono conservati in
`output/nla-operational-health-deployment/20261015/health-package-5592db2c-9b89-4a4d-bbcc-45a21e47659a/`.
L'installer revisionato ha SHA-256
`378de95749dfe8d1b03f3f0d9fc2048a49045d7a5b32bafb3b5012d499393f2b`:
dieci test sintetici indipendenti passati. La preparazione nativa è riuscita
alle 16:20 UTC, tentativo `073918cf6462447bb7fe459c19bc9e10`, stato JSON
`prepared`. Un secondo probe separato alle 16:21 UTC ha restituito `probe_pass`
su tutti i 101 file. Entrambi hanno verificato le unità con systemd 255 e gli
import Python con UID/GID 65534, senza avviare il server. Le unità restano
inermi nel pacchetto, fuori da `/etc/systemd/system`; `/opsz` non è attivato.
Ricevute private: `health-prepare-20261015T162034Z-073918cf` e
`health-probe-20261015T162114Z-4ede36c9`, sotto `output/nla-recovery/20260930/`.

Il controllo delle 16:21:16 UTC conferma refresh in corso, market inattivo con
esito positivo, pointer e ultima ricevuta invariati. Spazio libero
7.185.530.880 byte. La terza directory di generazione, comparsa durante il
refresh, era lavoro in corso da preservare. Il job è poi terminato con successo
alle 16:36:34 UTC; la verifica delle 16:40 conferma la nuova generazione attiva,
la precedente preservata, retention conclusa e 10.245.189.632 byte liberi.
La verifica nativa read-only e la quarantena v3 del vecchio drill sono passate:
due payload spostati e tre container rimossi, oltre ai due container smoke già
rimossi separatamente. Lo smoke di 10 richieste e 6 controlli è PASS sulla
generazione live `ae3be49c…` alle 21:57:13 UTC. La cancellazione esatta dei
payload è stata verificata il 15 ottobre alle 21:58 UTC; il restore applicativo
isolato resta da eseguire. [Dettagli e ricevute](BACKUP-AUTOMATION-2026-10-15.md).


## Proxy e backup: aggiornamento coordinato

La configurazione Caddy candidata aggiunge soltanto GET/HEAD `/opsz` verso il
nuovo processo loopback. Le rotte del catalogo e i suoi controlli upstream
restano quelli verificati. Hash del file esistente:
`3f761c8dabd2e79f7f4454221d249ce7c72e5867d7129b6eb237270dba5220ab`;
hash del candidato:
`ef4c3fa2e611798e6d42f50962b1b9ddfb9ef27ea5d7494ea406b3a499dd73b9`.
Caddy ha l'API admin disabilitata: non presumere disponibile il reload.
Alle 16:29:42 UTC il Caddy installato ha convertito il candidato con `adapt`,
come UID/GID 65534: sintassi accettata, GET/HEAD `/opsz` e upstream previsti
verificati. Configurazione esistente e identità del container invariate prima
e dopo. Il risultato JSON adattato ha SHA-256
`80378fd09abfd526adf91d6c09410fe0a922ae764e4e08d89176e29efa361fb8`.
Ricevuta privata `health-edge-adapt-20261015T162939Z-db049664`.
Non è stata richiesta la validazione con provisioning e non è stata applicata
alcuna configurazione. Questa validazione ulteriore, finestra idle, rollback
e verifica delle rotte restano necessari prima di cambiare il proxy in esercizio.

Al 15 ottobre l'inventario installato fissava l'hash del Caddyfile precedente e
non includeva il nuovo componente. La proposta allora preparata coordinava
l'aggiunta dei 101 file e delle tre unità con il nuovo hash Caddy. Il delta storico
`health-backup-delta.json` ha SHA-256
`ae6319b00475d129815f936f015bf272d55e11bc27cb7e941d6346eb9f3790b3`;
non è stato applicato. Lo stato temporaneo sotto `/run` viene rigenerato e non
è un dato di recupero. Il primo snapshot corrente già verificato su Backblaze
precedeva il nuovo componente; non attribuirgli questa copertura.

## Contratto nativo verificato — 17 ottobre 2026

La sonda in lettura delle 07:46:59 UTC è PASS: Caddy `v2.11.4`, container edge
`5d6fcb2d76c545df10c099dea208016aa9beb084022be0282d03d614973df87b`, immagine
`af555904a0961945f16bb323a501457b13a4f7e9bde969b145b97da80b38ecbe`.
Il processo usa UID/GID `10002:10002`, rete host e filesystem radice in sola
lettura. Il Caddyfile è un bind del singolo file, in sola lettura; `/config` e
`/data` sono bind scrivibili dei due alberi dedicati sotto
`/var/lib/nla-staging-edge/`. `StopSignal` e `StopTimeout` non sono impostati:
la sonda riporta `null`, senza inventare valori.

Risultato SHA-256 `ac2153f863def7436b76f0f542959872e34f495e2f0d71d024bda9acf0fb62e1`,
prova privata `recovery-draft/reviewed-health-inspect-20261017T074657Z-a1ba9d67de874d1f945778df15d520de`.
La prima sonda si era fermata nel comando inspect; la revisione successiva
gestisce i campi Docker opzionali. Il primo errore non è attribuito a un campo
specifico, poiché quella ricevuta non conservava tale informazione.

Market, refresh e backup risultano inattivi con esito positivo. Il timer backup
è abilitato e attende il 18 ottobre alle 01:00 UTC. Le tre unità health risultano
ancora `not-found`: non sono state attivate né è stato cambiato il proxy.
La configurazione backup corrente `f17ba531…` e lo snapshot verificato del
17 ottobre includono già i 101 file del pacchetto inerte e il codice `b56ca95`.
La futura attivazione richiede soltanto aggiungere le tre unità installate e
aggiornare il pin Caddy, quindi eseguire un nuovo backup verificato. Il delta
storico `ae6319…` non va applicato alla nuova base senza riconciliazione.

## Avvio HTTP: tentativo del 17 ottobre

Nel primo tentativo è mancata l'attesa tra avvio del processo e disponibilità
HTTP: l'operazione del 17 ottobre, iniziata alle 08:05:58 UTC,
si è fermato in `loopback-health` con `ConnectionRefusedError`. Nessuna validazione
o modifica Caddy e nessun backup erano ancora iniziati; rollback verificato.
Prova privata `reviewed-health-activate-20261017T080558Z-d49c8271925a499d8e697b0e7512c691`.

La diagnostica successiva, in sola lettura, ha SHA-256
`ea7dee46c5d72dc4bba3590cf88efc3f7aabc6f8629d89282d6d95f2ca4b455e`:
i tre avvii systemd sono riusciti; il server è stato avviato alle 08:06:05.446783
UTC; il rollback ne ha richiesto lo stop alle 08:06:06.249972 UTC, senza un evento di uscita,
errore o riavvio precedente. Il segnale 15 sull'observer appartiene al rollback.
La unità `Type=exec` conferma l'esecuzione del processo, non l'apertura del
listener; la procedura controllava HTTP immediatamente senza attenderlo.
I log applicativi sono disabilitati: non si attribuisce un traceback inesistente
al processo. Queste prove motivano una correzione circoscritta della readiness,
con attesa limitata e controlli invariati, prima di un nuovo tentativo.

## Attivazione e backup verificati — 17 ottobre, 08:18 UTC

Il secondo tentativo, con helper `8c018b175a49e649209aa9ac322b37533aa742955e210194019ddb521357c95b`,
è riuscito. Il delta aggiunge solo l'attesa HTTP limitata con controllo di PID,
invocazione e assenza di riavvii; risposte errate, osservazioni non sane e arresti
restano bloccanti. Tredici test sintetici e la review indipendente sono passati.

Sono attive le tre unità del pacchetto `59a74e6`: server loopback, observer e
timer. Il server e il timer sono abilitati. Il batch ha verificato due osservazioni
sane distinte, GET/HEAD `/opsz` 200 con `no-store`, la validazione Caddy con
provisioning, il nuovo hash e inode effettivamente montati dopo il riavvio del
solo edge e dieci richieste autenticate al catalogo. `/readyz` conserva GET 200
e HEAD 404. Pointer, generazioni corrente/precedente e pipeline sono preservati.

Il Caddyfile attivo è `ef4c3fa2e611798e6d42f50962b1b9ddfb9ef27ea5d7494ea406b3a499dd73b9`.
La configurazione backup attiva è `54a376a48a83e4dced5d81251b7e68ca99c6bc0804a3b44992361488ed2b6190`:
rispetto a `f17ba531…` aggiunge solo le tre unità installate e aggiorna il pin Caddy.
Il nuovo job `backup-919aeddea561432c9da028bd7e3ff6e8` è completo, con `read-data`
PASS e ricevuta per-job identica a `last-success`; staging vuoto e servizio
riuscito. Solo dopo questi controlli il timer backup è tornato enabled/waiting
per il 18 ottobre alle 01:00 UTC. Non è ancora una prova del ciclo automatico.

Risultato attivazione SHA-256 `fc16f0a161eecafa570b057e5f27b8ee204680e6516648838cadc4ac8852ffb4`;
prova privata `reviewed-health-activate-20261017T081704Z-a8739425feb740ab85edcf2300302123`.
Controllo finale alle 08:18:54.384365 UTC: 13.247.131.648 byte liberi, market e
refresh `success`, retention completata senza residui pianificati; SHA-256
`7540b405998f541770ce453071d001da5f9c655b75aabc9e999d9987a571a3f1`.
Snapshot e ricevuta completa nell'[evidenza backup](BACKUP-AUTOMATION-2026-10-15.md).

Il monitor esterno può usare `/opsz` per includere refresh e freschezza, anche
con HEAD. Configurazione e recapito UptimeRobot restano non verificati; la sonda
non controlla ancora fallimenti o anzianità del backup, né l'abilitazione dei timer.

## Contratti consultati

- [systemd 255: esecuzione e isolamento](https://raw.githubusercontent.com/systemd/systemd/v255/man/systemd.exec.xml)
  e [verifica delle unità](https://raw.githubusercontent.com/systemd/systemd/v255/man/systemd-analyze.xml).
- [Distribuzione Uvicorn](https://uvicorn.dev/deployment/) e metadata PyPI delle
  tre versioni fissate nel manifest locale.
- [Comandi Caddy](https://caddyserver.com/docs/command-line).
- [Attivazione UptimeRobot](https://uptimerobot.com/quick-monitor-setup/).
