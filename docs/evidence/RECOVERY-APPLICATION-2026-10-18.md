# Ripristino applicativo isolato — 18 ottobre 2026

Download, integrità, caricamento immagine e runtime `current`/`previous`
**PASS**; entrambi chiusi e rimossi, previous alle 05:22:46 UTC.
Pulizia delle sole copie isolate conclusa alle 05:26:27 UTC dopo inventario e
revisione indipendente; `/opsz` pubblico HTTP 200 alle 05:29:06 UTC. Questa nota aggiorna
la [preparazione](RECOVERY-RESUME-2026-10-18.md), senza sostituirne la cronologia.

## Esecuzione e risultati

Il refresh ordinario delle 03 UTC è terminato con successo alle 04:37 UTC.
Solo dopo la conclusione della catena market/refresh il controllo di ammissione
ha rilevato 3.346.931.712 byte di RAM disponibile, 13.753.745.408 byte liberi,
timer in attesa e spazio temporale sufficiente. Nessun job ordinario è stato
avviato, interrotto o modificato per il drill.

| Fase | Risultato misurato |
| --- | --- |
| Restore Backblaze | PASS, 04:37:17–04:38:20 UTC, **62,909634 s**, 2.127.307.366 byte; `restic restore --verify` e manifest verificati |
| Preparazione | PASS, 755 file del manifest, hash, tre SQLite, reference e due generazioni; copia indipendente cataloghi 1.804.372.384 byte; completata alle 04:41:41 UTC |
| Immagini | Metadati dei due archivi verificati e revisionati indipendentemente; immagine gateway caricata dall'archivio ripristinato, senza tag o riferimenti OCI; pin live invariati |
| Runtime current | PASS, 04:42:55–05:02:30 UTC, **1.175,298131 s**; 10 richieste funzionali, generazione attesa; container chiuso e rimosso, unità terminata con successo |
| Runtime previous | PASS, 05:03:13–05:22:46 UTC, **1.172,253043 s**; 10 richieste funzionali, generazione attesa; container chiuso e rimosso, unità terminata con successo |
| Pulizia | PASS alle 05:26:27 UTC: eliminati 765 file e 104 directory dalle sole copie isolate `restored/` e `catalog/`, 3.931.679.750 byte; liberi 13.750.943.744 byte. Prove e ricevute conservate, unità conclusa con successo e pin live invariati |
| Verifica finale | GET pubblico `/opsz` HTTP 200, risposta `healthy`, alle 05:29:06 UTC dopo la pulizia |

Il runtime usa l'ambiente effettivo recuperato dal backup: cambia soltanto
`NLA_STAGING_STORE_ROOT` e `NLA_ACTIVATION_SHA256` per la copia isolata.
Nessun valore segreto è incluso nelle ricevute pubbliche. I container hanno
rete disabilitata, filesystem e mount catalogo in sola lettura, utente 10001,
limite 2 GiB senza swap e 0,5 CPU; nessuna porta è esposta. I due ruoli sono
sequenziali e ciascuno richiede chiusura verificata. La durata include l'avvio del catalogo
con questo limite di CPU, non soltanto il download.

## Identità e prove riproducibili

- Snapshot: `9fc4fe1143bd0e9048f91ff23ca6d4d517cad300238acc42a94f5f29b0c75d5e`.
- Manifest: `aa3337d919cb10a4c5a278a4093ec9c10adbc4660a0637efcccfc7ecaf67faad`.
- Immagine gateway: `sha256:8a23ad0809ed155665decdea9dff875dd198f1fefe2e5764e20798a31a22ece8`.
- Metadati archivi revisionati: `15baca46a54f75d8314ec93899a13aa5ed929fe570aac2eacbe1d7d9ed153275`.
- Manifest current: `04b8cf157498609d04755f3e941d84e8474aad54739b1ff037f7acfd15b1824d`.
- Manifest previous: `3fbd719c115e3754c71ecb0e74e63054fb4ea92cdb5854750f6c6477569b95cd`.
- Ricevuta current, SHA-256: `1a2bac2ad9175f77cc020a820ae18b371105e465909064b7bb1469b1939568ed`.
- Ricevuta previous, SHA-256: `4578b0028e692b95c285cffb076972522f3bf90a786512f4fd3851f5e235bcb1`.
- Raccolta finale runtime, SHA-256: `8aae96302766e4fa1b84a9a79c34cbeb0d64da53fa936adb1e8a5eac1c86775f`.
- Inventario cancellazione revisionato, SHA-256: `1d77ec96c95c8f85ed34560ec0af6f98fb230d9149575fec0cec8328bda22b25`.
- Ricevuta cancellazione conclusa, SHA-256: `b6913bf718323d2a73a444127275b49fcf45f0b6dbd772f301e46f1a6804e808`.

Le ricevute private sono conservate in
`output/nla-recovery-runtime-20261018-e22a7cdf9f93442eacac300cbed2e4b1/`:
`observe_restore_final.result.json`, `observe_prepare_final.result.json`,
`inspect_restored_archives.result.json`, `load_reviewed_image.result.json`,
`observe_current_final.result.json`, `observe_previous_final.result.json`,
`collect_runtime_evidence.result.json`, `runtime-metrics.json`,
`deletion-independent-review.json`, `observe_delete_1.result.json`,
`cleanup-summary.json` e `public-opsz-after-cleanup.json`.
Bundle e pin installati sono in `bundle.json`; revisione e regressioni sono
già documentate nella preparazione. Non ripetere restore o smoke riusciti.
La diagnostica `diagnose_current_ready.failed.json` è stata rifiutata dalla
guardia perché current era già chiuso con PASS: non è un fallimento del runtime
e non richiede retry o correzioni.

## RPO, RTO e confini della prova

Il checkpoint è stato catturato alle **01:00:39,741959 UTC**; la ricevuta refresh
recuperata registra `sourceStartedAt=2026-10-17T15:00:21Z`. L'anzianità della
sorgente alla cattura è quindi **10 ore e 18,741959 secondi**. Con refresh alle
03/15 UTC e backup alle 01 UTC, prima della copia successiva la sorgente
recuperabile si avvicina a 34 ore, più la durata effettiva del trasferimento.
La proposta di RPO dei dati entro **36 ore in esercizio regolare** sostituisce
la precedente proposta di 24 ore; è un obiettivo proposto, non una garanzia
contro cicli saltati o falliti. La tolleranza ordinaria di freschezza a 24 ore
e la soglia alert backup a 26 ore sono misure distinte.

Dal primo download alla chiusura positiva di current sono trascorsi circa
**25 minuti e 14 secondi**; fino alla chiusura di entrambe le generazioni,
**45 minuti e 29 secondi** (pulizia esclusa). Il budget proposto di recupero è **2 ore su Linux
già pronto con accessi disponibili**; rilevamento, presa in carico, provisioning
e riattivazione del percorso pubblico restano fuori dalla misura.

La prova usa copie isolate sulla VPS disponibile e l'immagine era già residente:
non certifica un host vuoto, un nuovo host o il percorso pubblico ripristinato.
La password Restic usata è la copia operativa autorizzata; la custodia indipendente
in 1Password è confermata da Jacopo, senza accesso al gestore. Questi sono limiti
dichiarati, non nuovi prerequisiti infrastrutturali aggiunti all'obiettivo di
recupero isolato. Configurazione e TLS hanno una [prova separata già conclusa](RECOVERY-MATERIALS-2026-10-18.md).

Contratti consultati: [Docker image load](https://docs.docker.com/reference/cli/docker/image/load/),
[Docker container create](https://docs.docker.com/reference/cli/docker/container/create/),
[Docker container exec](https://docs.docker.com/reference/cli/docker/container/exec/)
e i contratti Restic/systemd riportati nella preparazione.
