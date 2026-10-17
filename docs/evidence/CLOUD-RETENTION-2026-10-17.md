# Inventario e conservazione Backblaze — 17 ottobre 2026

Workstream operativo #13, manutenzione documentale #34. Inventario completato
alle 08:50:04 UTC, exit 0, in 8,975 secondi. Solo letture B2 e due letture
`restic snapshots --json --no-cache --no-lock`; nessuna operazione sulla VPS,
nessun nuovo backup, cancellazione o modifica lifecycle.

## Risultato osservato

| Ambito | Versioni | Byte degli upload completati |
| --- | ---: | ---: |
| Copia manuale storica | 1 | 222.535.954 |
| Repository cifrato restic | 75, inclusi 18 marker hide | 399.643.707 |
| Totale bucket | 76 | 622.179.661 |

Una pagina completa, nessun upload grande incompleto osservato; 40 oggetti
visibili per 622.176.662 byte. La differenza di 2.999 byte riguarda versioni
non correnti. Nessuna regola lifecycle configurata; bucket privato e cifratura
server SSE-B2/AES256 leggibile. La chiave non può leggere la configurazione
Object Lock: non si deduce il suo stato dal valore nullo.

Quattro snapshot presenti, identici nelle letture prima/dopo e corrispondenti
agli oggetti snapshot del bucket; nessun lock corrente osservato ai due estremi.

| Snapshot completo | Provenienza | Timestamp UTC |
| --- | --- | --- |
| `770df0e0490b46d1f9b93870852b8047acdff038077e4c693dc48b35c57903e8` | Pilota PC sul checkpoint storico del 3 ottobre | 15 ottobre 10:47:48 |
| `f11005053ed6d498a312c7be84181ee40f28f6947a82dc349ef91319267a70bb` | Backup VPS usato nel restore isolato | 15 ottobre 13:29:22 |
| `bd249a0d8064bd950a2ef6ddb37eb9329c36eec2101491884d0c8cd794e42963` | Backup VPS dopo correzione del confronto mount | 17 ottobre 07:15:09 |
| `ffa29faf98aecfc61a39c2ad52f9bc69803a3b479e2cc877fa7a87297ef43cf8` | Backup VPS comprendente health e proxy aggiornati | 17 ottobre 08:18:10 |

L'inventario è paginato e non atomico: le verifiche agli estremi rilevano alcune
concorrenze ma non provano l'assenza di ogni scrittura intermedia. I byte non
includono parti di upload incompleti e non sono il totale fatturabile dell'account.
Questa è una verifica di metadati, non un nuovo controllo integrale dei dati.
Le precedenti prove `read-data` e di restore restano nelle rispettive evidenze.

## Conservazione e costo

Conservare tutti e quattro gli snapshot e la copia manuale: zero candidati alla
rimozione in questa fase. Il risparmio sulle sole versioni non correnti sarebbe
trascurabile. Nessuna policy di cancellazione automatica è stata installata.

Per una futura policy, il default di restic raggruppa per hostname e percorsi.
I tre backup VPS hanno hostname `nla-catalog` ma percorsi diversi per ogni job:
il default formerebbe tre gruppi separati, rendendo inefficace la rotazione.
Una proposta concreta è limitare l'ambito a quel solo hostname, raggruppare per
hostname e conservare 7 giornaliere, 4 settimanali e 6 mensili, proteggendo anche
le copie delle prove sopra. Il pilota PC e l'oggetto manuale restano esclusi.
Prima dell'attivazione servono il piano `--dry-run` sui dati aggiornati, review
indipendente e una finestra compatibile con il backup. Non applicare scadenze
per età agli oggetti attivi del repository: dati vecchi possono servire a copie
recenti. [Contratto ufficiale restic 0.19.1](https://restic.readthedocs.io/en/stable/060_forget.html).

Il [listino Backblaze](https://www.backblaze.com/cloud-storage/pricing), consultato
il 17 ottobre, indica 6,95 USD/TB/30 giorni e i primi 10 GB gratuiti. A volume
costante, questi 622.179.661 byte equivalgono a circa 0,0043 USD per 30 giorni
prima della franchigia. Non è una fattura né una previsione di crescita: altri
bucket possono consumare la franchigia e il servizio fattura sui byte-ora.

## Procedura e prove riproducibili

Helper privato `output/nla-cloud-retention-inventory-v2.ps1`, SHA-256
`0d0dfc279d59f016fa6ab42899c7be29bea44030bd207a7468ffa95eb40f105c`.
Autore e reviewer separati; percorso e binario restic Windows 0.19.1 fissati,
credenziali DPAPI esistenti, controlli ACL e limiti di tempo/risposta/paginazione.
Nessuna credenziale o risposta di autenticazione conservata nei log.

Eseguire con Windows PowerShell 5.1 dopo verifica del pin, senza importare il
vecchio pilota. Ogni esecuzione crea nuove prove private sotto
`output/nla-recovery/20260930/backup-automation-20261015/receipts/`.
La riuscita richiede exit 0 e `cloud_inventory_complete_readonly`, `complete=true`.
Un risultato incompleto non autorizza pulizia. Ripetere solo per un cambiamento
o una verifica necessaria, non come nuovo audit a ogni turno.

Ricevuta di questa esecuzione:
`cloud-inventory-20261017T084956160Z-48b217e7aff54420adc574a5778b0486/`.

| File privato | SHA-256 |
| --- | --- |
| `terminal.json` | `b30f820bbe7f786c584bec3f5e581ffffc94d1b1e0737867b5454168ef5cd33c` |
| `versions.ndjson` | `39f573f7b7baf61e0540ce445c415e6b386ff68365ae7ea85a9c910decbb7f80` |
| `snapshots.json` | `11a0f519fc06d5e4b3d8f3e986b814849287c734d11521ed139da1eab1f97a56` |
| `bucket.json` | `af549e75bd47d1be1ecaf8fd431fd56fc8c4210cc822705f687ab568816feda4` |

Il primo tentativo delle 08:46:57 UTC, helper `0b3c2698…`, aveva completato
autenticazione, lettura bucket, lock e snapshot, ma ricevuto HTTP 400 sull'elenco
con parametro `prefix=` vuoto. Il contratto pubblico lo descrive come opzionale
con default vuoto: la versione corretta lo omette. Il successo successivo
conferma questa correzione di compatibilità; il codice errore del primo tentativo
non era acquisito e non viene inventato. È stato anche corretto l'export JSON
degli array in PowerShell 5.1. Prova incompleta conservata, senza sovrascrittura.
[Documentazione B2 v4](https://www.backblaze.com/apidocs/b2-list-file-versions).
