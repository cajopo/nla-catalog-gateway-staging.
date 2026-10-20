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

## Aggiornamento del ripristino isolato — 16 ottobre 2026

Il restore nativo avviato il 15 ottobre alle 23:02:52.345978 UTC è terminato alle 23:03:27.972298 UTC (35.62632 s): dimensione logica ripristinata 2.126.224.845 byte (~2,13 GB); `resticVerify=true`. Snapshot `f11005053ed6d498a312c7be84181ee40f28f6947a82dc349ef91319267a70bb`, manifest `3ecbd4ed9cc078b7825c88c6ed074e195444d56b7401c36a5afe23bb5f203b8d`; ricevuta wrapper read-only in `recovery-draft/first-restore-observation-df1563b8f2c04b75b8d0c03eb967ab96` SHA-256 `2c1bd0c53efed694441924739305914e257a02db8923fa8e9085697919021876`.

La verifica guarded read-only del 16 ottobre alle 09:30 è PASS per tutti i file e i tre `quick_check` SQLite. Lo snapshot restaurato ha current `ed078…` e previous `fd665…`; ricevuta `reviewed-verify-metadata-20261016T093054Z-79fce481747c4b5ea89b70a327b112d0/verify.result.json` SHA-256 `4e8cf84a70bdb3432c152dfc6d33d51f0bdaeda978e9bae9fe0295ff72c9ae52`, metadata nella stessa directory SHA-256 `b3b3115c93f19790c05e7bb432bc8a6440a252bf8e3261e801758ba5b35a7ef3`. Alla verifica delle 09:30 erano presenti l’archivio Docker-save e il layout OCI senza riferimenti/tag; il caricamento dell'archivio non era ancora stato eseguito; la presenza dell'immagine sul nodo è distinta. Questo supera lo stato precedente “restore applicativo isolato resta aperto” per il ripristino e la verifica dello snapshot; il successivo drill applicativo è documentato sotto.

Il controllo live separato (`reviewed-inspect-20261016T092432Z-eae9c5db107146b2a321e91f42bb3c5b/retention.result.json`, SHA-256 `9ca1dd1686226043397e85df871a26d426304c5dafdb37e89879b6a735303895`) delle 09:24:36 UTC ha current `4cbb2053`, previous `49521`, refresh e market `inactive/success` e 11.665.154.048 byte liberi. Il pointer live `6e1b…` è distinto dallo snapshot restaurato: mantenere le due generazioni separate nelle prove. Il runtime live era operativo; il timer backup era disabilitato. Il drill di test successivo è riportato sotto.

Nel successivo drill applicativo del 16 ottobre (`reviewed-application-drill-20261016T094050Z-4765bf806fe6453e8c097ada67d852c5`), il load gateway è PASS (risultato SHA-256 `392746fd5dc67e62b1f595cae0a278616796e9b7c1925bb70f5ed2c7280456e7`; loader `2f480e…`). L’immagine `8a23…` era già residente prima dell’operazione: `emptyHostRecoveryProven=false`, quindi il drill non prova un recupero su host vuoto. Il ruolo `current` è PASS con `closed=true` (risultato `dd8775aea2182c72e8158eb159f40d4ae545574ebb38c6993cfdc089954008ca`); il ruolo `previous` è PASS con `closed=true` (risultato SHA-256 `c19a26df24d4f22b7b2033dbecbbe7b32cbf11c9a454e464ee5605c083c30b44`; sessione `66359`, exit 0). Entrambi i ruoli del runtime di test sono stati avviati, verificati e chiusi; il runtime live continua operativo. Il componente health è inerte e il timer backup disabilitato.

## Pulizia finale delle copie del restore — 16 ottobre 2026

La pulizia nativa ha eliminato esclusivamente i due alberi isolati `catalog/` e `restored/`, inclusi gli archivi e le sorgenti ripristinati: 643 file e 72 directory, per 3.930.589.037 byte. Lo snapshot cloud `f11005053ed6d498a312c7be84181ee40f28f6947a82dc349ef91319267a70bb` è stato conservato. Inventario approvato indipendentemente, SHA-256 `ce86434353fa31795ae39f766c8712ed175869d1d915d194430d5a2fe72b31d7`; ricevuta finale di eliminazione SHA-256 `e4a911c5ed064c10ee1f06e51132c0a78c8e8739e61951d771e2b831f16d7b1b`, evidenza `reviewed-final-cleanup-20261016T110110Z-3643e58bd28f422ebd78d4602d94364b`.

Il controllo post-retention delle 11:21:55 UTC ha rilevato 13.793.955.840 byte liberi; refresh e market `inactive/success`; pointer `6e1b…` e generazioni protette current `4cbb2053` / previous `49521` invariati; due directory di retention; i due container di test erano già chiusi e il finalizer non ha rimosso container. Ricevuta post-retention SHA-256 `1db7305c9cb886c1e6792255596a6b0e2a322ae9cef839094423be7993c4e152`. Il tentativo di attivazione del backup (`reviewed-backup-activate-20261016T112319Z-5665b431d434485a8d9db072726e2693/backup-activation.stdout`) si è fermato in admission: `startAttempted=false`, rollback verificato, timer disabilitato e nessun nuovo backup avviato; diagnosi in corso. La pulizia non modifica la conclusione `emptyHostRecoveryProven=false`.

## Esito operativo aggiornato — 16 ottobre 2026

Il backup valido resta il job `backup-4adf397a664545e6855c5ceb889cfaf6` del 15 ottobre alle 13:30:23 UTC (`read-data` PASS), snapshot `f11005053ed6d498a312c7be84181ee40f28f6947a82dc349ef91319267a70bb`, manifest `3ecbd4ed9cc078b7825c88c6ed074e195444d56b7401c36a5afe23bb5f203b8d`. La pulizia finale, i 643 file/72 directory rimossi e il controllo retention sono descritti nella sezione precedente.

Il primo tentativo di attivazione si è fermato in admission con `startAttempted=false` e rollback verificato. Il controllo dei permessi richiedeva erroneamente file privati anche per le unità systemd 0644; la correzione conserva i vincoli sulle credenziali. È stata corretta anche la lettura UTC dell'orario del timer. Il secondo tentativo ha installato la configurazione `d5d65f…` e le unità del pacchetto `929c7b0`, poi avviato il job `backup-971c466e4e45412cbce8b6de31594a2e` il 16 ottobre alle 11:38:34.037255 UTC. Il job è terminato alle 11:39:01.617282 UTC (27,580 s) con `checkpoint_failed`, prima del trasferimento. Risultato SHA-256 `2ddc94cad7d1e505ab0d4ad8f23fa7ec42d4a0ac5d72accbcdef497879984b62`, evidenza `reviewed-backup-result-diagnose-20261016T114550Z-4598a296fbc6447abf3340fada45faa5`; ricevuta del job SHA-256 `e3e411d2414d3d8f3dee0860d515e1d2962cbf3759ab671d36faae67b4e58375`.

Lo staging di circa 2,14 GB resta conservato per diagnosi. Alle 11:45 erano liberi 11.655.643.136 byte. Il timer è disabilitato e la causa non è ancora stabilita. Il diagnostico v2 delle 12:22:50 UTC ha inventariato 743/744 file attesi: manca solo `manifest.json`. Sono presenti 700 file degli alberi sorgente, 28 file di configurazione, il ledger da 12.808.192 byte e i due archivi immagine. I 712 confronti dei piccoli file selezionati sono passati; gli inventari degli alberi sono esatti e il pointer coincide. I tar hanno dimensioni attese e terminatore zero, ma questa sonda non ne ha verificato l'integrità completa. Risultato SHA-256 `7ba014c1f7bf546928d27bbf2aa5ecfa5abf8fa7a672527e04529938e362a572`, evidenza `reviewed-backup-checkpoint-diagnose-20261016T122250Z-cdcc4f97ac5b41e68ee60e0da5fc5b1a`.

La successiva sonda della verifica finale è stata eseguita alle 14:47 UTC e ha restituito `CheckpointBusy` prima di qualsiasi confronto, perché mancava il margine previsto rispetto al refresh delle 15 UTC. Risultato SHA-256 `6eec6c2e2faa639d96e03db8c607e0c67469c5018a0fe5cf41f492a4fdf75990`, evidenza `reviewed-backup-tail-diagnose-20261016T144714Z-33907d1a8a3844bdab04e34d271f9f80`. Non è un nuovo fallimento del backup. La revisione del codice ha individuato un confronto dipendente dall'ordine di `Mounts`: il [sorgente ufficiale Docker](https://github.com/moby/moby/blob/v28.5.1/container/container_unix.go#L396-L412) costruisce la lista iterando una mappa. Questo difetto è da correggere conservando il confronto di tutti i campi; il legame con il job fallito resta da dimostrare. Non ripetere il backup prima della diagnosi e di una nuova verifica della finestra libera.

La correzione candidata nella PR #113 ordina i montaggi per destinazione unica,
conservando tutti i campi del confronto. La validazione locale comprende 141 test
passati, copertura statement/branch 100% dei due moduli backup, Ruff, preflight e
build passati. La review indipendente e le 16 nuove regressioni sono passate:
riordinare i montaggi è accettato; cambiamenti reali e destinazioni duplicate sono
rifiutati. Sorgente candidato SHA-256
`048582e7fa20b4f991554d9f5ca3c878e09013a9d14626264a0f9a12ce981be8`.
La correzione non è ancora installata sulla VPS; il job fallito resta da diagnosticare.
Commit finale e CI della correzione sono da verificare nella PR #113.

## Esito operativo aggiornato — 17 ottobre 2026, 07:16 UTC

Il nuovo backup del servizio è completo; il timer è stato abilitato dopo la verifica. Il codice installato è `b56ca95fad2824b9faafc84c9f97ce66942fe75d`, la configurazione `f17ba5317d6e739d32a31f731a301db0209022ad0c725f3401e9156a6a548490` e l'unità service `bbc6e4b3b9e0550dfab8cb2eb70d23b3b6e00bf4d03a963c678bb5de80c62097`. Il job `backup-c121a380661d4bbfa6b6c0c5de1a09b4` ha ricevuta SHA-256 `8bd4cfe334ee34e91358e5416940e3cecc8d3018a3968561e0936b4775f2d64d`, snapshot `bd249a0d8064bd950a2ef6ddb37eb9329c36eec2101491884d0c8cd794e42963`; `complete`, `read-data`, gate con ricevuta per-job uguale a last-success e stato service success sono passati. La directory dei job è vuota. Il timer è `active/waiting`, abilitato per le 01:00 UTC; prossimo trigger 18 ottobre alle 01:00, `Persistent=no`. L'abilitazione è verificata; la prima esecuzione automatica non è ancora stata osservata.

La recovery locale è in `recovery-draft/reviewed-backup-recover-20261017T071214Z-cc6893804d814ac895420d8e6cd226d7`; hash SHA-256 dell'attivazione `fc43b56bd551922cb33c1ec5e5f1ebc3c01aa0193db08543b98740687e9c8ba3` e della retention finale `7e1a1f38d5b67608fd62b7bd9ef82601fd47fc53de34e1093b60dd45d33ec8f6`. La quarantena, il controllo indipendente dell'inventario e la rimozione esatta del solo vecchio payload del job fallito `971c` sono riusciti: 743 file, 2.126.986.835 byte; prove conservate e vecchio job non ripetuto. L'inventario revisionato ha SHA-256 `78b68c78d4d32639ee78db536494cc3a6f6bc801639540301d306d0ff68e0784`. Il difetto di confronto dell'ordine dei mount è stato riprodotto e corretto; il suo legame con l'errore storico di `971c` non è dimostrato.

Al controllo finale erano liberi 13.249.085.440 byte; market e refresh erano `success`, il pointer `43476…` e le generazioni `3fbd719c` / `5b22aed7` erano invariati. Gli esiti falliti del 16 ottobre e il vecchio stato con timer disabilitato restano nella cronologia, non descrivono lo stato corrente. Il componente health è ancora inerte; il restore su host vuoto, la conservazione cloud e la QA completa restano aperti.

Il checkpoint documentale pubblicato precedente della PR #101 era `b6ab98e618b0867f875b97ccf6d6854359a826d0`, con CI `38819024906` e CodeQL `38819025033` completed/success alle 22:56 UTC. Il head finale e i controlli del delta attuale sono da seguire nei metadati della PR #101.

## Backup dopo attivazione health — 17 ottobre, 08:18 UTC

L'ultimo backup verificato è ora `backup-919aeddea561432c9da028bd7e3ff6e8`,
creato dopo l'[attivazione della sonda](OPERATIONAL-HEALTH-2026-10-15.md).
Il codice resta `b56ca95`; la configurazione attiva è
`54a376a48a83e4dced5d81251b7e68ca99c6bc0804a3b44992361488ed2b6190`.
Il delta da `f17ba531…` aggiunge solo le tre unità health installate e aggiorna
il pin Caddy a `ef4c3fa2…`; nessun altro contenuto viene rimosso dalla copertura.

- Ricevuta SHA-256: `ce6018583f3d7369d36f97d9a09bf453748a60f8575f4ed8fad49ebad148b4e6`.
- Snapshot: `ffa29faf98aecfc61a39c2ad52f9bc69803a3b479e2cc877fa7a87297ef43cf8`.
- Manifest checkpoint: `8baedc6e59f7f1959d79bbe4925c3a9bb3e54be27c234b00c55aec5c6045adb0`.
- Risultato attivazione: `fc16f0a161eecafa570b057e5f27b8ee204680e6516648838cadc4ac8852ffb4`.
- Retention finale: `7540b405998f541770ce453071d001da5f9c655b75aabc9e999d9987a571a3f1`.

Gate completi: nuova ricevuta `complete`, `read-data` PASS, uguaglianza esatta
per-job/last-success, directory job vuota e servizio riuscito. Il timer è stato
riabilitato soltanto dopo il backup; attende il 18 ottobre alle 01:00 UTC.
La review indipendente ha verificato localmente il wrapper effettivamente
trasmesso, helper/config esatti, stdout, result e codici d'uscita: si basa sulle
attestazioni del codice revisionato, senza una seconda acquisizione dei file
remoti. Evidenza privata `reviewed-health-activate-20261017T081704Z-a8739425feb740ab85edcf2300302123`.

Alle 08:18:54.384365 UTC restavano 13.247.131.648 byte liberi, market e refresh
inattivi con `success`, pointer `43476…` e generazioni `3fbd719c`/`5b22aed7`
invariati; nessun residuo della retention pianificata. La health è ora operativa.
Restano da provare primo ciclo automatico, host vuoto, custodia indipendente,
conservazione cloud e recapito degli alert; la sonda non verifica ancora
fallimento o anzianità del backup. I precedenti snapshot restano conservati.
