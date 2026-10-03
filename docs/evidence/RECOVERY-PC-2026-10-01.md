# Recupero dei dati sul PC — 1 ottobre 2026

Esito corrente: la catena immagine e il seed offline dei dati sono verificati;
il runtime non è stato creato né avviato. Questa è una prova di integrità e
predisposizione dati nel Linux locale di Docker Desktop, non di ripristino del
servizio completo.

## Evidenza osservata

Docker Desktop Engine 29.7.2 era attivo sul contesto Linux/amd64, con 4 CPU e
3.001.667.584 byte di RAM. Il load predefinito dell'archivio immagine ha
terminato con codice 0 e ha restituito l'ID `sha256:ef26b1d554d3cdcddd2eaa2d918d07ddf4a880eb22afb4b355c6b0c1e6574a12`, diverso dal digest di configurazione atteso
`sha256:8a23ad0809ed155665decdea9dff875dd198f1fefe2e5764e20798a31a22ece8`.
Non si è interpretata la differenza come equivalenza: il bridge ha verificato
il manifest OCI locale (`ef26…`, 1.915 byte), collegato dall'unico descriptor
dell'indice dell'archivio, il config (`8a23…`, 8.029 byte), tutti gli 11 layer,
OS/architettura, runtime config e rootfs diff IDs. L'ispezione locale riportava
lo stesso digest descriptor/image ID, `linux/amd64` e revisione
`ed24a61f061c9ea226f3c37f145eb5deb37d4eb8`. Il motivo del precedente errore
al socket non è stato stabilito; il pin di configurazione è rimasto invariato.

Nel volume nuovo e isolato `nla-pc-recovery-20260930-00811b11cc38`, il seed
terminò con exit code 0, senza OOM. In 148,264 secondi, il verificatore ha
confrontato 12 file e fatto `SQLite quick_check` su tre database:

| Database | Esito | Conteggi riportati |
| --- | --- | --- |
| Catalogo corrente | `ok` | 295.885 prodotti; 297.956 varianti |
| Catalogo precedente | `ok` | 295.885 prodotti; 297.956 varianti |
| Ledger importer | `ok` | 4.090 tentativi; 4.090 pubblicazioni |

Permessi e ownership richiesti sono stati verificati. Il seed container
`9109931ded1b19d33ed8705546e5b3199395de4fa24fb11c9d9b99f0fcec6d52` è
arrestato; il volume resta conservato. Avvio: 30 settembre 2026 22:16:32 UTC;
termine: 22:19:01 UTC (1 ottobre, ora locale). Il JSON finale osservato è
`seed-verification-result.json`, timestamp 30 settembre 22:24:41.751326 UTC.

Il wrapper ha fermato la preparazione prima della fase `data_prepared` perché
la memoria disponibile misurata al termine era 2.090.254.336 byte, sotto il
minimo di 2.415.919.104 byte. Una misura successiva era 2.355.425.280 byte,
ancora sotto soglia. Nessun runtime applicativo è stato creato o avviato; non
sono quindi provati readiness, richieste, refresh, importer o funzionamento
del servizio. Dopo review indipendente, un unico tentativo di ammissione del
seed già verificato ha misurato 2.355.142.656 byte disponibili alle 22:28:48 UTC:
ancora sotto soglia, esito `waiting_memory`, stato invariato. Non sono stati
ripetuti restore o avvio. Ricevuta `resume-seed-preflight.json`; helper
`resume_verified_seed.py` SHA256
`c93dc174a9541cced9e76de75e4fec924e1da85dc07a65f673a911dd14e87e3d`.

È pendente la risposta asincrona di Jacopo: preparare un riavvio concordato di
Docker Desktop impostando 4 GB, oppure rinviare. Non è stata cambiata alcuna
impostazione. La successiva lettura Win32/WSL rileva 6.347.137.024 byte di RAM
fisica visibile e 4 processori logici, WSL 2.7.12; `.wslconfig` non esiste.
Il limite proposto di 4 GiB lascerebbe 2.052.169.728 byte di budget fisico
teorico a Windows, non memoria libera misurata. Non è quindi un aumento già
raccomandato o autorizzato: serve valutare l'uso del PC e concordare il riavvio,
oppure scegliere un ambiente Linux alternativo. Le impostazioni globali WSL
si applicano alle distribuzioni WSL 2 e richiedono il riavvio del sottosistema;
nessuna distribuzione o attività buildx è stata interrotta.
[Contratto ufficiale WSL](https://learn.microsoft.com/en-us/windows/wsl/wsl-config).
Ricevuta privata `pc-linux-recovery-resource-review/pc-resource-review.json`
e helper/indice conservati sotto la cartella evidence del checkpoint.
Nessun accesso VPS o modifica alle sue configurazioni è avvenuto;
il container buildx preesistente è rimasto intatto. La prova non dimostra il
recupero operativo completo su host nuovo, credenziali o certificati, reference/refresh/importer, TLS/DNS/App Proxy,
email, RTO, SLA o approvazione alla pubblicazione.

## Pin e conservazione

- Backup dati `catalog-ledger-checkpoint.tar.gz`: SHA-256
  `620c88e326bf949e345cc7afc49fc922b407ca56d2b10c4cd8ff7f23401ef79d`.
- Archivio immagine `runtime-ed24a61-image.tar.gz`: SHA-256
  `a037376414d31efa4a1bf1ef4c5a8ba9199567990d703fc258d9ba3ae0389265`.
- Verificatore offline incorporato: SHA-256
  `626ba793d51616a9068688ab48710abe2135e91bc5b5e9f6e3104a0f3fa27be9`.
- Bridge locale: SHA-256
  `981b56c3fdb6da85f06dc78b1226cfc1221c2e9bff7248798477fe89f5196bf4`.

La ricevuta riporta `backupUnchanged: true` e il digest atteso del checkpoint.
Gli archivi sorgente restano fuori Git nella cartella privata; questo non
costituisce garanzia di conservazione durevole.
Ricevuta e prove private sono conservate in
`output/nla-recovery/20260930/evidence/pc-linux-recovery-seed-hold/`:
16 file, 67.162 byte più indice. Le copie degli archivi sorgente restano nella
cartella privata del checkpoint.
Il follow-up di memoria è conservato separatamente in
`output/nla-recovery/20260930/evidence/pc-linux-recovery-memory-followup/`:
3 file, 6.013 byte più indice. Gli arresti iniziali e il load riuscito sono
conservati in `pc-linux-recovery-failure/`: 11 file, 46.478 byte più indice.
Nessuna ricevuta precedente è stata sovrascritta. La review indipendente ha
verificato i 16 file del checkpoint e i relativi hash; il controllo successivo
non cambia l'esito della mancata prova runtime.

## Riferimenti tecnici

La specifica OCI definisce l'ImageID come digest del JSON di configurazione;
Docker può esporre un descriptor target con il containerd image store. La
conclusione qui si basa sui digest e sull'ispezione locale effettivi, non sulla
sola stringa stampata dal load. [OCI config](https://github.com/opencontainers/image-spec/blob/main/config.md),
[Moby image inspect](https://github.com/moby/moby/blob/master/daemon/containerd/image_inspect.go),
[Docker image load](https://docs.docker.com/reference/cli/docker/image/load/).
