# Prima copia Backblaze verificata — 3 ottobre 2026

Jacopo ha scelto il bucket privato `nla-catalog` come destinazione dei backup e
ha salvato la nuova chiave sul PC. Autorizzazione operativa: [D-018](../DECISIONS.md#d-018--backblaze-backup-destination).
Workstream backup/restore #13; aggiornamento documentale #34.

## Esito e perimetro

La copia del [checkpoint PC delle 10:11 UTC](BACKUP-PC-2026-10-03.md) è stata
caricata, riscaricata integralmente e ripristinata offline. Non è una nuova
acquisizione dalla VPS: il contenuto resta quello del checkpoint del mattino.

| Verifica | Risultato |
| --- | --- |
| Destinazione | `nla-catalog`, regione `eu-central-003`, endpoint `https://s3.eu-central-003.backblazeb2.com` |
| Accesso | Chiave limitata al solo bucket; lettura/scrittura consentite; elenco di tutti i bucket non consentito |
| Protezione | Bucket privato; cifratura SSE-B2/AES256 confermata anche sull'oggetto |
| Archivio | 222.535.954 byte, catalogo corrente/precedente e ledger |
| SHA-256 originale e download | `93a7d1c6601f0c62f2d94098f94e539babb16241adfc85c915312038c9026713` |
| SHA-1 originale, risposta upload e download | `49477d3d2b2d9da6723a8d066376fd3618ef2505` |
| Fine trasferimento e verifica download | 15:46:42 UTC, 17:46:42 Europe/Rome |
| Restore della copia Backblaze | PASS, 61,970 secondi dopo la verifica iniziale dell'hash; 12 file più `checkpoint.json` |
| Database | Tre `PRAGMA quick_check` passati; ciascun catalogo con 295.975 prodotti e 298.046 varianti; ledger con 4.180 tentativi e 4.180 pubblicazioni |

Oggetto:
`nla/checkpoints/20261003T100800Z/catalog-ledger-checkpoint-93a7d1c6601f0c62f2d94098f94e539babb16241adfc85c915312038c9026713.tar.gz`.

Nessuna cancellazione o modifica alla VPS, nessun nuovo refresh/export Shopify.
Le copie iniziali e il seed precedente sono preservati. Il trasferimento ha
usato le API native B2 v4: non è una prova del protocollo S3.

## Riproducibilità

Helper e ricevute nella cartella privata, esclusa da Git:
`output/nla-recovery/20260930/backblaze-setup/`.

| Helper | SHA-256 |
| --- | --- |
| `check-connection.ps1` | `4126d350671c58122d86bcea5f096352de15507c85522b459faa1fafce5a50b0` |
| `upload-checkpoint.ps1` | `353cc064ac56e63de16d85312c3591ee6264729fb3b98e238e9bc0f85a7a9629` |
| `restore_offline.py`, invariato | `626ba793d51616a9068688ab48710abe2135e91bc5b5e9f6e3104a0f3fa27be9` |

Ricevute: `connection-20261003T153657177Z-b2006994.json`,
`transfer-20261003T154642762Z-55725da6.json`,
`offline-restore-20261003T154700Z.json`.
Download: `download-20261003T154552507Z-9914e931.tar.gz`;
restore: `restored-backblaze-20261003T154700Z/`.

Review indipendente dell'uploader: `/root/b2_key_capture_review`, nessun
Blocker/High dopo confronto con il contratto B2 v4. Il programma vincola
bucket, archivio, dimensione e hash; verifica gli host HTTPS restituiti,
disabilita i redirect, non registra credenziali/token e riusa un eventuale
oggetto omonimo solo dopo verifica dei metadati. Il restore rifiuta una
destinazione esistente e usa il filtro tar `data`.

Riferimenti ufficiali consultati: [autorizzazione](https://www.backblaze.com/apidocs/b2-authorize-account),
[elenco file](https://www.backblaze.com/apidocs/b2-list-file-names),
[URL upload](https://www.backblaze.com/apidocs/b2-get-upload-url),
[upload](https://www.backblaze.com/apidocs/b2-upload-file),
[download](https://www.backblaze.com/apidocs/b2-download-file-by-id).

## Cosa resta aperto

- Automazione dalla VPS, RPO, gestione degli errori e conservazione delle copie:
  nessuno scheduler di backup configurato, nessuna regola lifecycle presente.
- Backup e recupero dedicati per credenziali, certificati, configurazione,
  sorgenti e immagine runtime: esclusi da questo archivio.
- Ripristino completo del servizio su host nuovo: il test copre i dati,
  non l'avvio del runtime, il ciclo refresh/importer o un RTO completo.

Catalogo e ledger sono consistenti separatamente, senza snapshot atomico comune.
La chiave B2 resta cifrata con DPAPI sul PC, legata all'utente Windows;
non è stata installata sulla VPS. Object Lock risultava disabilitato nello
screenshot del proprietario; la chiave non può leggerne lo stato via API,
quindi non è stata certificata alcuna protezione immutabile. L'obiettivo
generale di manutenzione resta aperto.
