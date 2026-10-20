# Primo backup automatico verificato — 18 ottobre 2026

## Esito

Il timer ha avviato il servizio alle 01:00:12 UTC (03:00:12 italiane).
L'esecuzione, osservata prima attiva e poi conclusa nella stessa invocation
`451709267d414947a38d89b30f5af628`, ha prodotto una nuova ricevuta completa:

- Job: `backup-7f89aeb859744c7e933aab3c724e7b16`.
- Inizio: `2026-10-18T01:00:12.349412+00:00`.
- Fine: `2026-10-18T01:01:33.023983+00:00`; durata 80,674571 secondi.
- Snapshot: `9fc4fe1143bd0e9048f91ff23ca6d4d517cad300238acc42a94f5f29b0c75d5e`.
- Integrità: `read-data`, `passed`; servizio `inactive/dead`, `success`, exit 0.
- `last-success` e ricevuta per-job concordano. SHA-256 della ricevuta nativa:
  `4723ccf67123a974f363bf2e71842f70e686168e1fd769edbb1b9b7e6670bf12`.
- Timer `active/waiting`, prossimo avvio 19 ottobre alle 01:00 UTC.
- Alle 01:02:49 UTC: 13.763.911.680 byte liberi; market e refresh
  `inactive/success`, nessun pending osservato.

Nessun backup manuale, refresh o esportazione è stato avviato dall'agente.

## Inclusione dell'observer

Dopo la fine del job, un helper in sola lettura, revisionato indipendentemente,
ha recuperato dal repository il solo `manifest.json` del nuovo snapshot tramite
[`restic dump`](https://restic.readthedocs.io/en/stable/050_restore.html#printing-files-to-stdout),
senza cache o lock. Manifest di 198.901 byte, SHA-256
`aa3337d919cb10a4c5a278a4093ec9c10adbc4660a0637efcccfc7ecaf67faad`,
uguale al valore della ricevuta. Il manifest contiene i quattro sorgenti del
package `/opt/nla-operational-observer-319ca0b` e la relativa unità systemd,
con tutti e cinque gli hash uguali ai pin del rollout verificato.

Esito alle 01:03:41 UTC: `observer_in_snapshot_verified`. Il backup installato
resta `b56ca95`; non sono stati installati nuovi componenti. Alle 01:04:19 UTC
GET e HEAD pubblici su `/opsz` rispondono 200 con `Cache-Control: no-store`.

## Prove riproducibili

Directory privata: `output/nla-backup-scheduled-20261018-f9490a24d3fa465ea61564f278429cf9/`.
Le osservazioni iniziali sono conservate separatamente dalla finale.

| Artefatto | SHA-256 |
| --- | --- |
| `observe_backup_followup2.result.json` | `80dfd91d57f1cc96367fb6c968b5c7f338c97cddc2e306b8aeedfc086a018db0` |
| `verify_observer_in_snapshot.py` | `eb9953a5c73389d1110fecf5e8aea6e3e76c9261a4f131bbc8cf76c8de3edcf1` |
| `verify_observer_in_snapshot.result.json` | `a15967ff7c06212ad801c442aad67cabd900822a7892332600b5400aec30866d` |

L'helper è vincolato a questa invocation, job e snapshot: non riutilizzarlo
come checker generico dei cicli successivi. Verifica sintattica e review PASS;
il risultato remoto prova l'esecuzione della verifica. La sonda HTTP è conservata
in `public-opsz-after-backup.json` nella stessa directory.

## Limiti e prosecuzione

Questa prova chiude il primo ciclo automatico e l'inclusione dell'observer nel
manifest della copia. Non sostituisce il recupero completo su ambiente vuoto,
non misura un RTO completo e non certifica il futuro rispetto dell'RPO proposto.
Conservare questo snapshot come prova, oltre ai quattro già protetti; la
retention cloud resta inattiva e le preparazioni locali non sono state distribuite.

Il PC, ricontrollato alle 01:03:29 UTC, ha 816.218.112 byte liberi, sotto i
3 GiB richiesti dal drill esistente; il pipe Docker Desktop Linux è assente.
Nessun drill avviato. Ricevuta: `output/nla-recovery-capacity-20261018T010329Z.json`.
Gli alert TEST sono consegnati; resta configurare il monitor esistente su
`/opsz` ([prova email](ALERT-DELIVERY-2026-10-18.md)). GitHub rimane differito.
