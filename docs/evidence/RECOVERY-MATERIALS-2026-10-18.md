# Recupero di configurazione e certificati — 18 ottobre 2026

Esito nativo **PASS** alle 01:51:01.721461 UTC, durata **18,806 secondi**.
Dal backup automatico sono stati letti e verificati quattro file: configurazione
runtime di base, ambiente effettivo del container, certificato TLS e chiave privata.
Dimensioni e SHA-256 corrispondono al manifest remoto verificato. L'ambiente
effettivo corrisponde all'immagine attesa e all'attivazione del manifest.

Il certificato e la chiave recuperati hanno completato un handshake TLS 1.3
in memoria, verificando hostname e CA di sistema. Controlli negativi PASS:
hostname errato rifiutato e CA non attendibile rifiutata. Scadenza osservata:
16 dicembre 2026, 22:40:14 GMT. Nessun listener o container avviato.

## Riproducibilità

- Snapshot: `9fc4fe1143bd0e9048f91ff23ca6d4d517cad300238acc42a94f5f29b0c75d5e`.
- Manifest: `aa3337d919cb10a4c5a278a4093ec9c10adbc4660a0637efcccfc7ecaf67faad`.
- Directory privata: `output/nla-recovery-config-20261018T012857Z-b336b536/`.
- Helper `verify_restored_materials.py`:
  `17ad3ecac4e2a2ebec286d4dae16edd55454783c97a63f7caad96c1b911cbac4`.
- Runner `run_remote_script_with_diagnostic.py`:
  `6c3b74d02d8e07d4b49434ca80130664bfb6a2f60b470d2f4340febd201b33d7`.
- [Ricevuta privata](../../output/nla-recovery-config-20261018T012857Z-b336b536/verify_restored_materials.result.json):
  `bd3c388021285342d613f0e3f4cf4af3efd92fc634e0bc1abafc0d1e01d930ef`.

Comando eseguito dalla radice del progetto:

```powershell
python -X utf8 output/nla-recovery-config-20261018T012857Z-b336b536/run_remote_script_with_diagnostic.py output/nla-recovery-config-20261018T012857Z-b336b536/verify_restored_materials.py
```

Solo letture `restic --no-lock --no-cache dump` su snapshot e file fissati;
ricevuta backup invariata prima/dopo. Segreti mantenuti in memoria, non nei
risultati. Certificato e chiave caricati tramite memfd Linux; output limitato a
nomi delle impostazioni, esiti e metadati pubblici del certificato. Nessun refresh,
backup, esportazione Shopify o modifica del servizio avviato.

## Correzioni e verifiche

I tentativi precedenti sono conservati nella stessa directory. Il primo non
conservava il diagnostico stdout; il runner è stato corretto. Il secondo ha
identificato tre variabili storiche di attivazione che la sonda rifiutava: ora
sono riconosciute esplicitamente e ignorate, senza eseguire azioni di attivazione.
La configurazione effettiva del container resta verificata separatamente.

Due tentativi successivi hanno esaurito il budget condiviso di 32 secondi per
cinque letture Restic. Il limite diagnostico è stato portato a 120 secondi
dall'inizio delle letture, con arresto globale a 135 e timeout SSH a 150.
Nessun limite sui dati o controllo di integrità è stato rimosso. Un solo nuovo
tentativo è stato eseguito dopo questa modifica; è riuscito in meno di 19 secondi.
La causa della variabilità di latenza remota non è determinata: i timeout della
sonda non attestano un fallimento del backup o del servizio.

Test locali mirati: **17 PASS**, 0,87 secondi. Autore della sonda:
subagent `restored_material_probe`; revisione del codice e test indipendenti:
agente principale. Modifica finale dei timeout dell'agente principale revisionata
indipendentemente da `pc_recovery_resume`: PASS. Le simulazioni locali sono
distinte dal test TLS nativo riportato sopra.

## Limiti e uso operativo

Questa prova chiude la lettura verificata dei quattro materiali e l'utilizzabilità
della coppia TLS. Non avvia l'applicazione con le credenziali recuperate, non
verifica credenziali contro Shopify, DNS, proxy pubblico o recupero completo.
Usa l'accesso backup già presente sulla VPS, non la copia in 1Password.
Il recupero isolato dei cataloghi corrente/precedente già provato resta valido
nel proprio ambito. I tempi non sono un RTO completo.

Il requisito originario è un recupero isolato verificato usando risorse
autorizzate. Un host nuovo è un modo per provarne l'indipendenza, non un nuovo
requisito infrastrutturale: resta necessario collaudare l'intera procedura con
configurazione e accessi recuperati. Il tentativo PC è rinviato per RAM
insufficiente; non ripetere questa sonda riuscita senza una nuova necessità.

Contratti consultati: [Restic dump](https://restic.readthedocs.io/en/stable/050_restore.html#printing-files-to-stdout),
[Python SSL](https://docs.python.org/3.12/library/ssl.html) e
[Python memfd_create](https://docs.python.org/3.12/library/os.html#os.memfd_create).
