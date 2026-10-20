# Backup cifrato: prova S3 e recupero — 15 ottobre 2026

Workstream operativo #13; manutenzione documentale #34. Il bucket Backblaze
`nla-catalog`, regione `eu-central-003`, è la destinazione già autorizzata in
D-018. Il checkpoint originale e la prima copia cloud del 3 ottobre sono
preservati. Questa attività non avvia refresh o acquisizioni Shopify.

## Risultato cloud

PASS il 15 ottobre alle 11:00:51 UTC: inizializzazione del repository,
trasferimento cifrato, controllo integrale `check --read-data` e recupero sul
PC riusciti, tutti con exit 0. Il checkpoint è quello del **3 ottobre**, non
una nuova acquisizione dei dati correnti. La prova verifica il nuovo trasporto
S3 e la cifratura; non certifica automazione, freschezza o recupero del servizio.

| Misura | Risultato |
| --- | --- |
| Archivio sorgente e recuperato | 222.535.954 byte |
| SHA-256 prima/dopo il backup e dopo il recupero | `93a7d1c6601f0c62f2d94098f94e539babb16241adfc85c915312038c9026713` |
| Snapshot completo | `770df0e0490b46d1f9b93870852b8047acdff038077e4c693dc48b35c57903e8` |
| Trasferimento cifrato | 617,046 s |
| Controllo integrale dei blocchi cloud | 119,841 s |
| Recupero e verifica restic | 16,565 s; 17,543 s incluso controllo esterno dell'hash |

Sono riutilizzate le prove SQLite del checkpoint identico del 3 ottobre:
questa prova non ripete l'estrazione dei database né avvia un runtime. I tempi
misurati non sono un RTO del servizio. Le ricevute sono
`init-20261015T104730638Z-0a942f9f.json`,
`backup-20261015T110010611Z-1908ea25.json` e
`verifyrestore-20261015T110051883Z-287e3a2c.json`.
Il file recuperato è in `restores/cloud-20261015T110100Z/` nella directory privata.

## Metodo e verifica preliminare

È stato preparato restic 0.19.1 per cifrare i dati prima del trasferimento e
gestire copie incrementali. La documentazione restic raccomanda l'interfaccia
S3 per Backblaze; il trasferimento del 3 ottobre aveva provato l'API nativa B2.
Per questo servono una nuova prova di connessione, integrità e recupero.
Il repository dedicato è
`s3:https://s3.eu-central-003.backblazeb2.com/nla-catalog/nla/restic-v1`.

I binari Windows e Linux provengono dalla release ufficiale. Sono stati
verificati gli SHA-256 pubblicati e la firma GPG del file SHA256SUMS, con
fingerprint `CF8F18F2844575973F79D4E191A6868BD3F7A907`.

| Artefatto | SHA-256 |
| --- | --- |
| Binario Windows | `b0dd1fd21eea5d8fe1325f55f7118213c21f36de8a261e04c0624a5ab9fd7830` |
| Binario Linux, solo preparato sul PC | `20d4142678d0d95ec11a4759def1b73fd9190abc9ca19e4b62d067c0b387e639` |
| Helper privato `restic-pilot.ps1` | `1ee73777e5af520597c2226e0094210e08ccbc1f02f9e60e0cf7e525fa1e0592` |

La prova sintetica locale ha superato init, backup, elenco snapshot, controllo
integrale dei dati e restore con hash identico. Il primo restore dell'albero
Windows completo aveva fallito sui metadati di `C/Users`; il selettore della sola
sottocartella sorgente ha risolto il problema senza cambiare ACL. Il restore usa
una destinazione nuova, `--overwrite never` e `--verify`.

L'helper è stato revisionato da `/root/restic_pilot_review`, distinto
dall'autore. Le ricevute sono create esclusivamente, sincronizzate su disco e
promosse senza sovrascrittura; directory, ACL e reparse point sono verificati
prima dell'accesso alle credenziali. Le chiavi passano soltanto nell'ambiente
del processo figlio; stderr e segreti non sono riportati nelle ricevute.

La nuova password del repository è salvata tramite DPAPI sul PC, nella cartella
privata. Serve insieme alla chiave Backblaze per il recupero: non cancellarla,
non rigenerarla dopo un errore e non presumere che il file DPAPI sia utilizzabile
su un altro PC. L'installazione protetta sulla VPS e una procedura indipendente
di custodia/recupero della password restano da completare.

## Inventario per l'automazione

Letture VPS del 15 ottobre, 10:38–10:44 UTC: Ubuntu 24.04.2, Python 3.12.3,
x86_64, restic assente; entrambi i servizi inattivi e i timer in attesa. Spazio
libero 10.711.048.192 byte, memoria disponibile 3.292.876.800 byte.

Catalogo, ledger, reference configurata, sorgenti attivi, configurazione, edge
e dimensioni delle immagini totalizzano circa 2.080.741.861 byte prima di
compressione e deduplicazione. È una stima di preparazione: non include ancora
tutti i file operatore e le ricevute, e la dimensione Docker non misura un
archivio esportato. La directory operatore completa occupa 3.620.332.305 byte:
serve una lista esplicita dei file attivi, senza includere alla cieca gli
artefatti storici. Nessuno di questi file è stato eliminato.

La procedura da implementare deve acquisire corrente/precedente, ledger tramite
SQLite backup, reference e pin, sorgenti installati inclusa la correzione market,
immagini, configurazione/accessi cifrati, unità e ricevute necessarie. La cattura
deve rispettare i lock delle pipeline e rinviare se occupati, con riserva di
spazio e limiti di risorse. Il trasferimento non deve trattenere quei lock.
Non basta schedulare l'helper del pilota, fissato al checkpoint del 3 ottobre.

Scheduler, snapshot completo aggiornato, recupero del runtime e RPO/RTO
restano aperti. La conservazione cloud richiede ancora una scelta; nessun
`forget`, `prune`, cambio lifecycle o Object Lock fa parte del pilota.
La tariffa pubblicata è 6,95 USD/TB/30 giorni, con i primi 10 GB gratuiti;
egress gratuito entro tre volte lo spazio medio mensile, poi 0,01 USD/GB.
Il costo reale dipenderà da retention, modifiche e recuperi misurati.

## Prove private e fonti

Directory privata, esclusa da Git:
`output/nla-recovery/20260930/backup-automation-20261015/`.
Contiene `tools/binary-verification.json`, `independent-pilot-review.json`,
`local-contract-20261015T104136Z/result.json` (fallimento conservato),
`local-contract-20261015T104228Z/result.json` (PASS), le ricevute del pilota in
`receipts/`, i due probe in `inventory/` e `automation-design.json`.
Il progetto di automazione è esplicitamente marcato come non eseguito.

Fonti ufficiali consultate:

- [Release restic 0.19.1](https://github.com/restic/restic/releases/tag/v0.19.1)
  e [verifica dei binari](https://restic.readthedocs.io/en/stable/020_installation.html).
- [Repository e backend S3/B2](https://restic.readthedocs.io/en/stable/030_preparing_a_new_repo.html),
  [backup](https://restic.readthedocs.io/en/stable/040_backup.html),
  [controllo integrale](https://restic.readthedocs.io/en/stable/045_working_with_repos.html)
  e [restore](https://restic.readthedocs.io/en/stable/050_restore.html).
- [Integrazione Backblaze](https://www.backblaze.com/docs/cloud-storage-integrate-restic-with-backblaze-b2)
  e [tariffe](https://www.backblaze.com/cloud-storage/pricing), verificate il 15 ottobre.
