# Backup automatico — validazione del 15 ottobre 2026

Stato alle 13:55 UTC (15:55 Europe/Rome): installazione completata, primo backup
corrente cifrato e controllo integrale dei dati passati. Il timer è disabilitato;
questa evidenza non attesta ancora il recupero completo dell'applicazione.

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

La revisione automatica aveva bloccato il trasferimento delle credenziali per
mancanza di consenso esplicito alla destinazione. Jacopo lo ha poi autorizzato
nella chat (D-021); sono stati eseguiti gli stessi helper revisionati, senza
aggirare il blocco. Directory root 0700 e credenziali root 0600 verificate.
Configurazione, pin, versione restic e limiti systemd sono stati verificati
alle 13:28:40 UTC. Il solo `daemon-reload` ha caricato le nuove unità; i servizi
market/refresh e i loro InvocationID sono rimasti invariati.

Il primo job è iniziato alle 13:28:57 UTC ed è terminato alle 13:30:23 UTC:
86,632 secondi per cattura, trasferimento, controllo completo `read-data` e
pulizia delle copie proprie. Ricevuta `backup-4adf397a664545e6855c5ceb889cfaf6`,
snapshot `f11005053ed6d498a312c7be84181ee40f28f6947a82dc349ef91319267a70bb`,
manifest `3ecbd4ed9cc078b7825c88c6ed074e195444d56b7401c36a5afe23bb5f203b8d`.
Il controllo delle 13:33:05 UTC conferma `complete`, integrità passata, servizio
terminato con successo, timer inattivo e spazio libero 10.672.623.616 byte.
Nessun ciclo market/refresh è stato avviato, fermato o riavviato dal backup.

Alle 13:55 UTC il manifest è stato riscaricato con `restic dump` in sola lettura,
senza cache o lock del repository: hash identico, 167.547 byte, 633 file e due
immagini Docker, per 2.126.057.298 byte descritti. Ricevuta terminale e
`last-success.json` coincidono, SHA-256
`fbd1869b5beb9da4b6e0d0cb821a079fe37d0b24c0e62203bd2e7fa7ba08af1b`.
Helper SHA-256 `37f290f15e90c954acfde5dd25f8da0dbd441929de790d12ece520b03250d509`,
35 test sintetici, Ruff e review indipendente passati; esecuzione nativa
3,409 secondi, nessun file remoto scritto. Il primo tentativo aveva rifiutato
il timestamp restic con offset `+02:00`: il verificatore ora normalizza gli
orari con fuso a UTC, mantenendo il rifiuto degli orari senza fuso. Non è un
errore del backup o una prova di recupero applicativo.
Ricevuta privata `recovery-draft/manifest-20261015T135522Z-be7e6f30/fetch_first_manifest_remote.result.json`.

Prima di abilitare il timer occorre chiudere il caso di trasferimento lungo o
fallito: la cattura rilascia i lock prima dell'upload e una copia fallita resta
in staging. I limiti CPU/memoria non riservano spazio disco per i cicli delle
02/03 UTC; la durata riuscita di questa prova non è una garanzia per i job futuri.
Non abilitare il timer sulla sola base di questo esito. Il probe in sola lettura
delle 13:42:17 UTC misura 10.672.390.144 byte liberi e zero byte ancora
recuperabili dalla pulizia ordinaria pre-market: i file eleggibili sono già
rimossi. Gli ultimi run hanno allocato 530.079.744 byte per market e
3.059.703.808 byte per cattura refresh più nuova generazione. Con lo staging
backup osservato di 2.141.757.440 byte, servirebbero almeno 12.173.991.936 byte
iniziali per conservare anche la riserva di 6 GiB: deficit 1.501.601.792 byte.
È una stima su run osservati, non un limite massimo dei run futuri.
Probe SHA-256 `e0e8755f2c1985923c95cf65022a2b079ffc284a0ae5724255b0d2c6c7e273f4`,
review indipendente passata, nessuna modifica VPS.
Risultato privato `inventory/capacity-20261015T134214Z-574f5d5d/capacity_before_market.result.json`,
SHA-256 `482f0f950273791f4302bfdc3e05bff306bb6b82fb242c8b890d05f7a07b202d`.

L'inventario mirato delle 13:54 UTC conferma il vecchio drill del 21 settembre:
archivio 1.780.002.816 byte allocati e dati restaurati circa 1.780.006.912 byte.
Tre container di quel drill sono arrestati con restart policy `no` e conservano
montaggi dei dati restaurati; nessun riferimento aperto rilevato in quel momento.
Questo inventario non autorizza da solo la rimozione: preservare ricevute/prove,
chiudere i riferimenti esatti, quarantena e verifica funzionale, review
indipendente prima della cancellazione. Nessuna pulizia eseguita da questo probe.
Il totale del sottoalbero è indicativo, perché il probe non segnala errori di
attraversamento; prima della pulizia serve inventario completo che li rifiuti.
Il filesystem principale usa LVM sul disco da 40 GiB: non è attestato un volume
separato disponibile per il backup. Prova privata
`inventory/topology-20261015T135429Z-8a446f94/topology_old_drill.result.json`,
helper SHA-256 `d05dc5b80914066ecb4a66bdc9fcb95e5b64826387acf49654be7ed6f5cb5cd9`.

Sono preparati anche helper privati di recupero e pulizia delle sole copie del
drill. La review ha rilevato nella prima versione l'omissione del backup delle
01 UTC e un limite all'output applicato troppo tardi; entrambi sono stati
corretti prima dell'uso. Le versioni finali hanno review statica passata,
45 test sintetici per recupero/pulizia e 11 per il download restic, più Ruff.
Il recupero verifica manifest, hash e tre SQLite restaurati; la prova runtime
richiede 90 minuti liberi dai cicli programmati. Questi helper sono limitati
alla fase precedente all'attivazione: richiedono servizi inattivi senza job
pendenti e timer backup disabilitato, senza cambiare automaticamente le unità.
La pulizia richiede un inventario esatto e review indipendente per ogni esecuzione.
Pin del verificatore
`0c40d5daffaa9702f307bced8f035f2d955f59b33b9edbc249feb806dd2284d0`,
finalizzatore `e792465d79d569277125d26a8989038ebac50884ff55a652ec326e2af5a7e023`,
download restic `55d49f0a90ed0e866f531e7932d7180606aea799b4ddfd717099d924eb902571`.
Queste erano prove locali degli helper; un workflow v3 separato ha poi superato il controllo completo nativo read-only e completato quarantena e cancellazione esatta del vecchio drill. Il restore applicativo isolato, l'importazione dell'immagine e il runtime da quel restore restano da eseguire.

## Completamento del vecchio drill - verifica del 15 ottobre

Il primo tentativo di finalizzazione e' scaduto al builder con TTL 600 prima
di creare un receiver o trasferire dati, senza mutazioni. In un secondo
tentativo il trasferimento di prova e' passato; prima della SSH, `Get-Acl` non
ha potuto caricare il modulo PowerShell 5.1 perche l'ambiente ereditava
`PSModulePath` di PowerShell 7. Un fix limitato all'ambiente del child ha
impostato i moduli PowerShell 5.1; il preflight nativo e' quindi passato senza
cambiare ACL, pin o executor.

Dopo il fix del parser `nsfs`, la scansione VPS completa read-only dei riferimenti
e' passata: 122 processi, 205 task e 2.281 descrittori esaminati. Installer v3
`606a...` e probe separato PASS; helper di quarantena `3f2b...` e orchestratore
`306e...` PASS.

Il batch `old-drill-20260921-20bbfa9f0ec94690b8065e0004a65b58` ha usato inventory
SHA-256 `93e2eae74e847027f81f63f2330f672685ac0e7d639fd6911d868d29abc40fd8` e
ricevuta di quarantena `bf576880761177f744e1149700aaea4a29b5220b2ad497b4db4dc87a2e303894`.
Due payload sono stati spostati in quarantena. I due container smoke del 17
settembre erano gia stati rimossi separatamente; durante la quarantena sono
stati rimossi i tre container del drill. Approval `fc479d...` e smoke
`f765ec...` (10 richieste, 6 controlli) PASS sulla generazione live
`ae3be49c...` alle 21:57:13 UTC. La sessione workflow `69277` e' terminata con
exit 0 e outcome `deleted_payloads_verified`: il finalizzatore ha eliminato e
verificato i due payload esatti (nove file payload e le directory vuote
associate). Ricevuta terminale SHA-256
`ebf076b7f215466f3e2fb47d085e966b40bda08daa394cd9cd0896dedc3cea80`.

Il controllo post-delete delle 21:58:47 UTC ha registrato 13.795.237.888 byte
liberi; servizi refresh e market `inactive/dead`, entrambi `Result=success` e
`ExecMainStatus=0`. Retention coerente: run `20261015t150018z-a6b95321`, ultimo
successo e manifest attivo corrispondenti, due directory e tre container
pianificati, zero directory residue; pointer e generazioni corrente/precedente
invariati. SHA-256 della ricevuta post-delete
`7a934c10747b029c94ee18de779750918d20b7027980a47d8e393acb489bd062`. Il restore
applicativo isolato resta aperto. I pacchetti backup `929c7b0` e health `59a74e6`
sono preparati/provati ma inerti; UptimeRobot resta non verificato dopo il blocco
della policy URL di Computer Use, pur con email attivata e login alla dashboard
confermati dal proprietario.

Il piu' recente tentativo di ammissione read-only per il restore e' stato rifiutato; la diagnosi e' in corso. Il restore non e' stato avviato.


Restano recupero isolato dell'applicazione e verifica del margine disco per lo
scheduler anche in caso di errore. Scheduler proposto alle
01 UTC; non è ancora attivo. Conservazione cloud, custodia indipendente della
password e obiettivi RPO/RTO richiedono ancora chiusura documentata. Nessuna
cancellazione cloud, modifica MAIN/PowerTools o scrittura Shopify autorizzata
da questo workstream.

## Preparazione inerte del pacchetto hardening

Il bundle pubblico dal commit `929c7b0849bc66258effa89e6aac5d78d1444c84` è stato
revisionato indipendentemente: installer `13f2425cc6da200db84680ee2a0f216dc4513eb4644fca656a557529acf29e5b`,
esito PASS nella review salvata
`output/nla-backup-hardening-deployment/20261015/1ab5bdbb-f368-4e0c-92e8-c82add799c7c/review-installer-root.json`. La preparazione
nativa ha restituito `prepared` per 7 file al target
`/opt/nla-staging/backup-929c7b0`; il probe separato ha restituito
`probe_pass` sugli stessi 7 file. Entrambi sono vincolati al manifest SHA-256
`922c569474226c606f11c52e2bfab3cad299e689a39f7162985290136bcb373f`. Ricevute
private: `backup-package-prepare-528c049d15434db58b61fde64e489695/install_backup_package.result.json`
e `backup-package-probe-e3ed28b4b3d846d7b494b59dd165f149/install_backup_package.result.json`.

Questa preparazione del pacchetto sorgente è separata dall'attivazione: le unità
candidate restano sotto `units/` nel pacchetto e non sono state installate in
`/etc/systemd`; le unità e la configurazione installate in precedenza restano
in uso, senza modifiche. Nessun job restic, timer o scheduler è stato avviato o
sostituito. Il timer resta disabilitato e il primo backup corrente delle 13:30
resta integro. Le candidate di configurazione solo hardening `d5d65f` e
`health-active 8a7bf` hanno review PASS ma non sono state applicate.
