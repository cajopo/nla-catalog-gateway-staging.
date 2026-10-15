# Backup automatico — validazione del 15 ottobre 2026

Stato alle 12:42 UTC: codice verificato e pacchetto installato sulla VPS;
credenziali, configurazione e unità non ancora installate. Questa evidenza non
attesta un backup corrente né un recupero completo.

Workstream #13, branch `agent/offsite-backup-13`, commit
`079a242c2129b346d58e170e6f954995364a8716`, base
`90f4f49bf2094fa2af51dff3a998b82054d93c76`.
[PR #113](https://github.com/cajopo/nla-catalog-gateway-staging./pull/113)
in bozza e non fusa. La precedente [prova cifrata](BACKUP-ENCRYPTION-2026-10-15.md)
resta valida per il checkpoint storico del 3 ottobre.

## Controlli eseguiti

- [CI 38728961722](https://github.com/cajopo/nla-catalog-gateway-staging./actions/runs/38728961722):
  4.191 test passati su ciascuno di Python 3.12 e 3.13, copertura statement/branch
  100%; Ruff, preflight, build, audit dipendenze e smoke container passati.
- [CodeQL 38728962156](https://github.com/cajopo/nla-catalog-gateway-staging./actions/runs/38728962156):
  passato, incluso il controllo di assenza di segnalazioni di sicurezza.
- Review indipendente del codice passata. Test mirati: 46 per la cattura e 59
  per il trasporto, con copertura 100% dei rispettivi moduli.
- Prova nativa Linux con 67.195 byte sintetici: lock reali non bloccanti,
  proprietari/permessi, backup SQLite con WAL e riapertura, invarianza sorgenti,
  rifiuto symlink/FIFO, limiti di spazio e tempo passati. Durata 0,276 secondi;
  directory proprie rimosse. Docker e risposte dei servizi erano simulati;
  nessun accesso a dati, lock o credenziali di produzione.

La suite completa Windows locale non è verde: 3.977 passati, 165 fallimenti,
49 errori, copertura 91%. I test nuovi del backup non compaiono nei fallimenti;
la causa dei fallimenti più ampi non è stata stabilita. Non sostituire questo
risultato con quello Linux. Il vecchio Python derivato da MySQL non disponeva
di SSL per la build isolata; il runtime completo Python 3.12.14 ha costruito
il pacchetto senza disabilitare TLS.

## Pin e confini

Archivio Git LF del commit, 3.788.800 byte, SHA-256:
`713fe41d8bdb4c99c7b4297ea2183499d7943c0c72fefbe54d10c12b349a3d5f`.
Generato con `git -c core.autocrlf=false archive`; tutti i 217 file verificati
contro i blob Git. Il primo archivio di preparazione (`08d1a8a2…`, 3.870.720 byte)
aveva applicato la conversione Windows CRLF: è conservato come prova superata
e non deve essere installato. La discrepanza è stata rilevata prima del deploy.
Modulo checkpoint, byte Git/Linux:
`a8a07d57fd8f958dfb727c0b092f1e66d914e14a48970881bff1f1e4da4f92bc`.
Modulo trasporto, byte Git/Linux:
`751035b8cd237d37dfafd22d625edaaa315cd25b1afc3a71ebbe17be361bcc56`.
La copia Windows CRLF del trasporto ha hash
`18cbc74fcf942033e893c99bed0c0a7502d3cba30dee0bee7c7b023fcc0202f3`:
la sola normalizzazione CRLF→LF produce il pin Git. L'installazione deve usare
i byte dell'archivio Git, senza confondere le due rappresentazioni.

La cattura include corrente/precedente, ledger online, reference corrente,
inventario esplicito di configurazione/credenziali/TLS, sorgenti installati e
immagini Docker fissate per ID. Acquisisce i lock esistenti senza attendere,
controlla i timer e li rilascia prima del trasferimento. Riserva minima 6 GiB;
nessun avvio o arresto delle pipeline. La pulizia riguarda solo le copie proprie
di un job completato; gli errori conservano lo staging per l'ispezione.

Prove private e helper rivisti:
`output/nla-recovery/20260930/backup-automation-20261015/`.
Nessun dato, segreto, snapshot o configurazione effettiva è incluso nella PR.

## Gate ancora aperti

La prova aggiuntiva nel sandbox systemd reale è passata: 67.611 byte sintetici,
limiti effettivi verificati, accessi in scrittura ai sorgenti respinti, ledger
SQLite WAL copiato e riaperto, hash di DB/WAL/SHM invariati. Unità temporanea,
fixture e directory di caricamento rimosse. Modulo checkpoint invariato;
wrapper SHA-256 `71bcb5531cedee1a786c9c91ed566677a1b9c076a5e407712be1993d7793f111`,
helper `ecf13679a5b68cfe157741aef1ee448d8c3ca989be89894ed6e8c0a831ee3b91`.
Ricevuta privata `native-proof/systemd_sandbox_wrapper_v1.result.json`.
Questa prova non trasferisce dati reali e non attesta il servizio backup installato.

Il solo pacchetto è stato installato con esito `created_no_activation` in
`/opt/nla-staging/backup-079a242`; creata anche la directory privata di stato
`/var/lib/nla-backup`. Il controllo delle 12:42:49 UTC conferma entrambe root
0700, directory `/etc/nla-backup` e unità ancora assenti, servizi market/refresh
inattivi e InvocationID invariati, spazio libero 10.674.012.160 byte.

L'errore SSH dell'installer dipendeva dall'assenza di `ProgramData` nell'ambiente
Windows esplicito: OpenSSH usciva con codice 255 prima di produrre output.
L'aggiunta della sola variabile richiesta è stata verificata con una prova SSH
in sola lettura e review indipendente; il contratto è nel
[sorgente ufficiale Win32 OpenSSH, `init_prog_paths`](https://github.com/PowerShell/openssh-portable/blob/latestw_all/contrib/win32/win32compat/w32fd.c).
Pin wrapper pubblico:
`b121aaea6edcccbfd634b051bdad9e96b45d608084617338771c6205a50fd9f6`;
wrapper credenziali/guardie:
`011cca9c4f8767e1b4fab4b522c9157889da5ee048b26564577c59b1e9fba0f2`.

La revisione automatica ha bloccato il successivo trasferimento delle
credenziali: richiede autorizzazione esplicita del proprietario a copiare sulla
VPS la chiave Backblaze e la password del repository. Domanda inviata; nessun
trasferimento o avvio eseguito. Non aggirare il blocco con un altro trasporto.
Dopo autorizzazione: credenziali, configurazione/unità, verificatore già
revisionato, poi singolo avvio protetto e osservazione dell'esito. Conservare
le prove nuove senza sovrascrivere quelle iniziali.

Sono preparati anche helper privati di recupero e pulizia delle sole copie del
drill, con 30 test locali sintetici e Ruff passati. Il recupero verifica manifest,
hash e tre SQLite restaurati; la prova runtime richiede 90 minuti liberi dai
cicli programmati e conserva corrente/precedente separati. La pulizia richiede
un inventario esatto e una review indipendente per ogni esecuzione. Pin del
verificatore `9bdace89d57cc15751841efc26d353c3bf45c939765e6ef281c6daece3aeb66e`,
finalizzatore `b56df6d80967035aee102b231f79f637ac8d910d2d2aef88e4d3cb24d8e4aef8`.
Queste sono prove locali degli helper; review finale, restore reale, importazione
dell'immagine e runtime da quel restore restano da eseguire. Nessun drill VPS
è stato avviato da questi helper.

Restano installazione completa verificata, prima copia completa corrente e
recupero isolato dell'applicazione. Scheduler proposto alle
01 UTC; non è ancora attivo. Conservazione cloud, custodia indipendente della
password e obiettivi RPO/RTO richiedono ancora chiusura documentata. Nessuna
cancellazione cloud, modifica MAIN/PowerTools o scrittura Shopify autorizzata
da questo workstream.
