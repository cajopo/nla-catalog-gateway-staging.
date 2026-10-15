# Preparazione degli alert operativi — 15 ottobre 2026

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
propone `/opsz`: il collector legge lo stato dei processi, le ricevute, la
freschezza del catalogo e lo spazio disponibile; un processo separato espone
solo un esito generico. Una lettura scaduta oltre 90 secondi produce 503.
Un refresh in corso non è automaticamente un errore. Restano fuori da questa
copertura la frequenza dei 5xx, la latenza, CPU/memoria e l'abilitazione dei timer.
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

L'inventario del backup installato fissa l'hash del Caddyfile precedente e non
include il nuovo componente. Prima di attivarlo occorre coordinare l'aggiunta
dei 101 file e delle tre unità con il nuovo hash Caddy. Il delta proposto
`health-backup-delta.json` ha SHA-256
`ae6319b00475d129815f936f015bf272d55e11bc27cb7e941d6346eb9f3790b3`;
non è stato applicato. Lo stato temporaneo sotto `/run` viene rigenerato e non
è un dato di recupero. Il primo snapshot corrente già verificato su Backblaze
precede il nuovo componente; non attribuirgli questa copertura.

## Contratti consultati

- [systemd 255: esecuzione e isolamento](https://raw.githubusercontent.com/systemd/systemd/v255/man/systemd.exec.xml)
  e [verifica delle unità](https://raw.githubusercontent.com/systemd/systemd/v255/man/systemd-analyze.xml).
- [Distribuzione Uvicorn](https://uvicorn.dev/deployment/) e metadata PyPI delle
  tre versioni fissate nel manifest locale.
- [Comandi Caddy](https://caddyserver.com/docs/command-line).
- [Attivazione UptimeRobot](https://uptimerobot.com/quick-monitor-setup/).
