# Recupero offline della reference — 1 ottobre 2026

Workstream documentale #34, ramo `agent/pm-state-20260930`. Base documentale
`99ba1fd4e7fee320b5933d55600a45dee1f78f0c`. Prova eseguita sul PC il 30 settembre
alle 23:15:01 UTC, ossia 1 ottobre 01:15:01 Europe/Rome. Integra il
[checkpoint PC](RECOVERY-PC-2026-10-01.md) senza ripetere il seed dei dati.

## Risultato e limite

PASS: la configurazione restaurata è stata accettata dal comando di refresh in
modalità predefinita `REFRESH_CONFIGURATION_ACCEPTED_NO_CHANGES`. La funzione
`capture_shopify_bulk._configuration` ha caricato e validato l'intera reference,
con hash, byte, conte, ordine e identità duplicate controllati dal loader effettivo.
Entrambi i moduli e il loader provenivano dai sorgenti salvati dell'operatore
installato `881b9ca08dd2bc3ba9875b10d59ccb1a825a9246`, non dal checkout corrente.

| Gioco | Identità validate |
| --- | ---: |
| Magic | 138.875 |
| Pokémon | 85.357 |
| Yu-Gi-Oh! | 95.092 |
| One Piece | 17.428 |
| Totale | 336.752 |

Tempo interno: **23,164 s**. Picco cgroup: **302.075.904 byte**, circa 288 MiB.
Il container è uscito con codice 0, senza OOM. Sono state verificate anche le
query snapshot/control e la tassonomia salvate, registrandone gli hash privati.
Questo prova il contratto dei file; non verifica lo schema API Shopify corrente.

Nessun client Shopify, richiesta di rete, acquisizione Bulk, refresh applicato o
importer eseguito. Nessuna credenziale usata. Nessuna configurazione operativa
modificata: le sole modifiche erano i cinque percorsi rimappati nello scratch.
Non prova freschezza dei dati, servizio applicativo PC, recupero degli accessi,
TLS/DNS/App Proxy, nuovo host o RTO completo. La soglia del runtime PC e la sua
decisione pendente rimangono quelle del checkpoint precedente.

## Versioni e isolamento

| Input | SHA-256 |
| --- | --- |
| `refresh-881b9ca.tar`, 187 file regolari / 3.368.664 byte estratti | `291d967a77ca1295a385ebc6a72be72d64c721a32f3aac82d95d4d1a3600dcbd` |
| `reference-config-checkpoint.tar.gz`, 6.474.146 byte | `4730b6a9049ba8470c97551e3cae9a3d7e933736381afb861d35d12341cd3e08` |
| Manifest, 743 byte | `592097c0d4f8ee4a29e0890557ea5874ffcd61931b5e8b71b75005f917b2c718` |
| Sidecar JSONL, 67.367.250 byte | `b726989cc231ba52fb30265ba3ddaf83dcef51b7bfea006982ef5fb32f75370f` |

Immagine runtime revision `ed24a61f061c9ea226f3c37f145eb5deb37d4eb8`; catena OCI
già verificata e ricontrollata prima della prova: config digest
`sha256:8a23ad0809ed155665decdea9dff875dd198f1fefe2e5764e20798a31a22ece8`,
manifest/ID locale
`sha256:ef26b1d554d3cdcddd2eaa2d918d07ddf4a880eb22afb4b355c6b0c1e6574a12`.
I sorgenti dell'operatore sono una versione separata da questa immagine.

Contesto Docker `desktop-linux`, Engine 29.7.2. Contenitore nuovo, etichettato e
limitato a 768 MiB senza swap aggiuntivo, 1 CPU e 32 PID; rete `none`, nessuna porta,
capability rimosse, `no-new-privileges`, filesystem in sola lettura. Due soli bind
read-only per gli archivi; scratch tmpfs privato di 128 MiB con noexec/nosuid/nodev.
Root Linux serve al validatore originale. Un audit hook rifiutava socket, DNS e
processi esterni prima degli import di produzione.

Preflight richiesto: memoria host disponibile almeno 1.536 MiB; misura interna
prima 2.341.916.672 byte, dopo 2.085.212.160 byte. Nessun limite del runtime completo
è stato abbassato. Gli archivi sono stati riverificati dopo la prova e la chiusura.

## Ricevute e chiusura

La review indipendente degli helper è passata prima dell'esecuzione; quella delle
ricevute è passata prima della rimozione. Gli helper privati e i pin sono:

| Helper | SHA-256 |
| --- | --- |
| `validate_reference_inner.py` | `7523abbfc5f0207fa0a33ca1fe0e716484e648f149f76072f8959ac57f5800fb` |
| `run_reference.py` | `216076dbbf421b8ae108b144291c6070035f85ac79c8b9d948b75cdd6c7e29ab` |
| `preserve_reference.py` | `875eebae24a42ca32b52ccf0518cf65ee0e4ce1865ba5a81d5cd4c9db83b63ac` |

Sequenza eseguita: sintassi Python → review → `run_reference.py --run` →
`preserve_reference.py ready` → review dell'indice/ricevute →
`run_reference.py --close` → `preserve_reference.py closed`. Tutti con exit 0.
Gli helper rifiutano pin cambiati, stato già esistente o risorse non conformi;
per una nuova prova occorrono identità, percorsi e review nuovi.

Cartella privata del checkpoint: `output/nla-recovery/20260930/evidence/`.
`reference-offline-ready/index.json`: 8 file metadata, 35.363 byte;
`reference-offline-closed/index.json`: 9 file metadata, 35.766 byte.
Ogni copia ha nome consentito, dimensione e SHA verificati. Nessun dato prodotto,
nome carta, credenziale o archivio è incluso nei documenti Git.

Ricevuta prova: `e927e9804a7aa22c2c224b2104c217d8e3fd2ccf3e3e1459c03c6a816db98b76`.
Ricevuta chiusura: `b14bfeb8d0f215d266705f939dacece9770d64ae52c34da7f3cd8fe747691546`.
Alle **23:18:02 UTC** è stato rimosso esclusivamente il container arrestato
`6ac51ad0e691cd3aa1cf2d7ca3fa46ded760635d9e196e394f21e5499fc3255a`;
assenza del suo ID e hash degli archivi verificati. Immagine conservata; nessuna
operazione sul volume/seed PC precedente, su altri container o sulla VPS.

## Documentazione e seguito

Contratti ufficiali consultati prima dell'uso:
[Python tarfile](https://docs.python.org/3.12/library/tarfile.html),
[Docker create](https://docs.docker.com/reference/cli/docker/container/create/),
[Docker start](https://docs.docker.com/reference/cli/docker/container/start/),
[Docker rm](https://docs.docker.com/reference/cli/docker/container/rm/),
[tmpfs](https://docs.docker.com/engine/storage/tmpfs/),
[cgroup v2](https://docs.kernel.org/admin-guide/cgroup-v2.html#memory).
Contratti effettivi verificati nei sorgenti archiviati `881b9ca`.

Riutilizzare questa evidenza: la lacuna reference/config offline è chiusa.
Restano un ciclo operativo con credenziali recuperate, runtime su host distinto,
backup automatico/destinazione durevole e le altre prove elencate nello
[stato corrente](../STATUS-CURRENT.md). GitHub resta differito; nessun push/merge/CI.
