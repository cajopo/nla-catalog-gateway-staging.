# Preparazione del recupero applicativo — 18 ottobre 2026

La preparazione e i vincoli sotto sono storici. L'esecuzione successiva al
refresh, con restore, runtime current/previous e pulizia PASS, è registrata nella
[prova applicativa](RECOVERY-APPLICATION-2026-10-18.md); non reinstallare o
ripetere le fasi riuscite.

Il controllo in sola lettura delle **01:56:37 UTC** ha rilevato sulla VPS
3.359.264.768 byte di memoria disponibile e 13.762.465.792 byte liberi.
Market, refresh e backup erano inattivi con esito success; i timer erano
abilitati e in attesa, senza job accodati. Scadenze osservate: market alle
02:00 UTC, refresh alle 03:00 UTC, backup il 19 ottobre alle 01:00 UTC.

La capacità osservata è sufficiente per il drill previsto, ma **la finestra
di 85 minuti più 5 di margine non era disponibile**. Nessun restore, container,
caricamento immagine o modifica di unità è stato eseguito. Attendere il termine
del refresh e verificare di nuovo ammissione e pin prima di avviare il drill;
non riutilizzare i pin live delle 01:56 dopo market/refresh.

## Materiali e correzioni locali

Il manifest dello snapshot `9fc4fe1…` è stato acquisito per preparare il nuovo
drill e confrontato con il pin già verificato `aa3337…`. Comprende 755 file e
due immagini; restore previsto 2.127.307.366 byte, copia dei cataloghi
1.804.372.384 byte. Riserva totale minima calcolata, inclusi 6 GiB liberi e
128 MiB di margine: 10.508.348.422 byte. Il primo calcolo con 16 MiB è
conservato in `next-recovery-inputs.v1.json`; il piano corrente mantiene
il margine maggiore usato nella preparazione precedente.

La procedura esistente è stata adattata localmente per caricare l'ambiente
effettivo del container dallo snapshot, preservando segreti, dominio e percorsi
proxy. Cambiano solo il percorso dello store isolato e il puntatore della
generazione esercitata. I valori privati non sono inseriti nelle ricevute.
Il timer backup resta attivo: il nuovo controllo richiede stato noto, nessun
job accodato e scadenza oltre la finestra necessaria. Rimangono i limiti
2 GiB, 0,5 CPU, rete disabilitata e filesystem del container in sola lettura.

Revisione indipendente dell'agente principale e regressioni locali:
**56 test PASS, 39 subtest PASS, 2,74 secondi**. Corretti prima dell'approvazione:
import dei moduli con Python `-I`, lettura limitata della configurazione,
timestamp UTC con verifica del giorno della settimana. Nessun nuovo pacchetto
installato; usato l'interprete `.venv` esistente.

Questi test non provano ancora il recupero nativo. Il caricatore immagine è
stato successivamente adattato e revisionato con i pin del nuovo snapshot;
riceve esplicitamente il digest dei metadati verificati e i pin live freschi.
Il finalizzatore conserva inventario, quarantena e revisione prima della
rimozione. Non aggirare `check_image`, né fabbricare ricevute di caricamento.

## Aggiornamento delle 02:21 UTC: strumenti installati, prova non avviata

Il bundle è installato in `/opt/nla-staging/recovery-e22a7cdf9f93442eacac300cbed2e4b1`
con directory root `0700` e file `0600`. L'installazione è inerte: nessun restore,
container, caricamento immagine o avvio/modifica di servizi. Su Linux sono passati
i controlli `python3 -I ... --help` di restore, runtime, loader e launcher;
gli helper dipendenti sono risolti tramite percorsi assoluti, non tramite stdin.

La revisione ha corretto un difetto nella guardia del timer: il parser richiede
UTC, quindi `systemctl` deve forzare sia il formato UTC sia l'ambiente UTC.
Le regressioni aggiornate riportano **69 test e 75 subtest PASS**; altri **3 test
del launcher PASS** verificano rifiuto per RAM insufficiente, sola lettura e
avvio limitato non ripetibile. La guardia UTC è passata anche sul timer backup
reale, attivo e in attesa del 19 ottobre alle 01 UTC.

Alle **02:21:30 UTC** market era effettivamente in esecuzione (`activating/start`,
job `1160433`, invocation `b441b43c1cfb411da6141ae716a9fff2`); il timer refresh
era inattivo. Non dedurre un guasto da questa osservazione durante il job.
Attendere la conclusione della catena ordinaria e verificare che tutti e tre i
servizi siano terminati con successo e i timer siano attivi/in attesa.

Solo dopo il refresh e una nuova ammissione, il launcher installato può essere
invocato per percorso assoluto con `--start-restore`. Senza il flag è in sola
lettura. Richiede almeno 3 GiB disponibili, 10.508.348.422 byte liberi e tutti
i prossimi timer oltre 90 minuti; ricontrolla container e file live. Crea una
sola unità transitoria con CPU 50%, RAM 768 MiB e timeout 22 minuti. L'esito
`submitted_check_native_result` significa soltanto richiesta di avvio accettata:
leggere unità e ricevuta nativa prima di dichiarare il restore riuscito.

Il pin `lastSuccessSha256` nella ricevuta del launcher è un'osservazione di
ammissione; il restore verifica invece ricevuta del job, snapshot e manifest.
Il loader lo ricontrolla successivamente. L'ispettore degli archivi dovrà ancora
essere eseguito sui materiali realmente ripristinati prima del caricamento.

## Riferimenti privati per la ripresa

- Osservazione e manifest: `output/nla-recovery-admission-20261018-560b88584d2e/`.
  Ricevuta `observe_admission.result.json`, SHA-256
  `388afeff098289505416b697028c4fb8b7653f73166ac40cf58e752ff2999dd4`.
- Input del prossimo drill: `next-recovery-inputs.json` nella stessa directory,
  SHA-256 `6d6294318e9bdbae4e838068914816599b31232e13857ce2c8181a4178e53073`.
- Helper e test: `output/nla-recovery-runtime-20261018-e22a7cdf9f93442eacac300cbed2e4b1/`.
  `review.json` contiene tutti i pin, le verifiche e le attività ancora mancanti;
  SHA-256 `4abc1da813e7523bb2f6cfb906bb6fb1b06658dd724f8d93f96320d83ca2a3a5`.
  Questa è la revisione storica: i pin aggiornati sono in `bundle.json` e
  `review-delta-20261018.json` (SHA-256
  `a4055b88ed30fbc4b72b4fde139defef4f28b96cfb3c4dcd2fff834de6d618e3`).
- Ricevuta installazione `install_bundle.result.json`, nella directory helper:
  SHA-256 `6e3204e3e6032058cf8445373f306baae215508ff9e4b3259364d55ae15b625d`.
- Osservazione `observe_native_schedule.result.json`, nella stessa directory:
  SHA-256 `28fe44318f0b0e63456862b7c3fc6085684ed015126574be9ed9ce649bfe7c52`.

Non rifare la [prova dei materiali](RECOVERY-MATERIALS-2026-10-18.md) già riuscita.
La prossima prova utile è l'applicazione isolata con configurazione recuperata,
letture funzionali delle generazioni corrente/precedente e chiusura verificata.
Restano distinti recupero isolato, uso della copia password custodita e RTO completo.

Contratti consultati: [Docker, limiti delle risorse](https://docs.docker.com/engine/containers/resource_constraints/),
[systemctl](https://www.freedesktop.org/software/systemd/man/latest/systemctl.html),
[Restic restore](https://restic.readthedocs.io/en/stable/050_restore.html),
[systemd-run](https://www.freedesktop.org/software/systemd/man/latest/systemd-run.html),
[systemd.service](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html),
[systemd.exec](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html).
