# Prova di recupero Linux NLA — 30 settembre 2026

Workstream documentale #34, ramo locale `agent/pm-state-20260930`.
Segue la [prima copia fuori VPS](MAINTENANCE-2026-09-30.md) e la
[pulizia verificata](RETENTION-2026-09-30.md). Nessuna modifica del servizio
live, del tema o di Shopify; GitHub resta differito.

## Perimetro e integrità dei dati

Il checkpoint privato sul PC delle 16:08 UTC è stato verificato prima della
trasmissione: `catalog-ledger-checkpoint.tar.gz`, 222.456.335 byte, SHA256
`620c88e326bf949e345cc7afc49fc922b407ca56d2b10c4cd8ff7f23401ef79d`.
È precedente al refresh live delle 16:40 UTC e non è stato sovrascritto.

La copia è stata trasferita alle 19:05–19:07 UTC in una nuova directory privata
`/var/lib/nla-maintenance/restore-20260930-pc-checkpoint/` sulla stessa VPS.
Non è una prova su host nuovo. Il trasferimento PC→VPS è durato circa 109 s;
estrazione, confronto di tutti i 12 file e verifica SQLite sono passati in
13,35 s. Non è l'RTO del servizio.

| Database restaurato | Verifica | Conte |
| --- | --- | --- |
| Catalogo corrente `a23f6ba2…` | Hash/dimensione e `quick_check=ok` | 295.885 prodotti, 297.956 varianti |
| Catalogo precedente `6b0e3ff3…` | Hash/dimensione e `quick_check=ok` | 295.885 prodotti, 297.956 varianti |
| Ledger importer | Hash/dimensione e `quick_check=ok` | 4.090 tentativi e 4.090 pubblicazioni |

Catalogo e ledger sono separatamente consistenti; non viene dichiarata una
transazione globale né una riconciliazione corrente di Shopify. Il ledger
restaurato non è stato usato per eseguire l'importer.
Store e directory intermedie hanno UID/GID 10001 e modo 0700; generazioni
sigillate 0500, file ordinari 0400, pointer 0600. L'helper di preparazione,
revisionato indipendentemente prima dell'esecuzione, ha SHA256
`1833d649f73217f5d16f1ce5985bdfe38c6f9c9e666517691d1d9b9381c1a8fe`.

## Runtime isolato e ammissione

È stata riusata l'immagine già residente
`sha256:8a23ad0809ed155665decdea9dff875dd198f1fefe2e5764e20798a31a22ece8`.
L'immagine salvata sul PC non è stata caricata: il recupero dell'immagine da
zero rimane da provare. Source consumer `ed24a61`, producer evidence `881b9ca`.

La nuova istanza `nla-restore-20260930-a522a0b4`, ID
`1c0180c73fa5913723037dc4c89696ddae13237cd02d79c487eec16ea562db04`,
è stata avviata alle 19:13:34 UTC, senza rete esterna né porte pubblicate.
Monta soltanto il catalogo restaurato, in sola lettura, e usa chiavi sintetiche.
Limiti: 0,25 CPU, 1 GiB RAM, nessuno swap aggiuntivo, 32 processi;
root filesystem read-only, capability rimosse, restart disabilitato.
Il servizio live non è stato riavviato.

La procedura salva intenzione e identità del container prima dei controlli
successivi, per consentire chiusura mirata anche in caso di errore. Reviewer
indipendente ha richiesto questa correzione prima dell'esecuzione.

Al controllo delle 19:42 UTC il processo era attivo, con 750,6 MiB
e CPU al limite; readiness non ancora positiva. Il codice congelato esegue
prima dell'avvio HTTP hash, controlli SQLite e semantici su tutti i record,
poi replay delle prove di ricerca/filtri. La durata sotto questo limite CPU
non viene interpretata come guasto del servizio live o capacità di produzione.
Un reviewer distinto dall'autore ha confermato i passaggi; limite del drill
esteso a 60 minuti mantenendo le risorse invariate.

Il primo tentativo si è arrestato alle 19:48:16 UTC per il limite di memoria:
`OOMKilled=true`, exit 137, dopo 34 minuti e 42 secondi. Non ha raggiunto la
readiness; non è una prova di recupero riuscito. Il container arrestato e le sue
ricevute sono stati conservati. Il limite di 1 GiB è risultato insufficiente
per questa fase di avvio, senza dimostrare un difetto nei dati restaurati.

La diagnosi successiva ha rilevato il live attivo a circa 208,5 MiB, con limite
3 GiB/2 CPU, e 3,36 GB di memoria host disponibile. Dopo review indipendente
è stata avviata alle 19:55:25 UTC una nuova istanza
`nla-restore-20260930-bdb91e42`, ID
`7860892831ad85196f5b0feb61accd8d2ed8b713e330bfd1ed5b57c1edf58fce`.
Stessi immagine/dati/confini, limite 2 GiB senza swap aggiuntivo e 0,5 CPU;
nessun riavvio dell'istanza live né del primo tentativo. La nuova preflight
richiede almeno 3 GiB di memoria disponibile e conferma i pin/readiness live.
Le nuove ricevute hanno nomi distinti; ogni ispezione conserva anche una copia
datata esclusiva. L'ispezione verifica capability, no-new-privileges, tmpfs,
utente non root e restart, oltre a mount, rete e limiti di risorse.

La seconda istanza è stata osservata pronta alle 20:15:44 UTC: readiness
HTTP 200 con contratto esatto, nessun OOM, circa 220,5 MiB. Il tempo fino alla
prima readiness positiva osservata è 20 minuti e 19 secondi; le ispezioni
sono distanziate, quindi non è l'istante esatto di fine bootstrap. Non è un RTO
su host nuovo né un limite garantito. Il primo tentativo fallito resta nella
sequenza e non viene escluso dal costo complessivo di questa prova.

Alle 20:16 UTC sono passate dieci POST firmate sul gateway restaurato:
prima/seconda pagina disgiunte da cinque record per Pokémon, Magic, Yu-Gi-Oh!
e One Piece, più ricerca e suggerimenti Pikachu/Charizard. Tutte riferiscono
`sha256:ac1760846953198405939862f0796363f3122de5b1ec0a1dc54b55fbacc0ca1e`,
la generazione del checkpoint PC, distinta da quella live più recente.
Nessuna scrittura Shopify; nessun segreto esportato dal container.

## Carico controllato sul catalogo restaurato

Quaranta richieste firmate, concorrenza due, famiglia `single`, query vuota,
pagina da 20 record, distribuite sui quattro giochi. Tutte HTTP 200, zero errori:

| Misura | Risultato |
| --- | --- |
| Durata batch | 3,5204 s |
| Latenza minima / mediana | 0,0996 / 0,1846 s |
| Percentile 95 / massimo | 0,2253 / 0,2664 s |

Il percentile usa il rango intero su 40 osservazioni. Prova esclusivamente
loopback, dati restaurati e limite 0,5 CPU: non certifica capacità, latenza o
SLA del sito in produzione, ricerche onerose, immagini o traffico Shopify.
Le assertion e i limiti del precedente helper revisionato sono stati preservati;
solo identità dell'istanza, nomi delle ricevute e descrizione CPU sono adattati.

Alle 20:21 UTC sono passate altre tre POST firmate alla stessa istanza:
prima pagina 200, cursore con firma valida ma generazione non disponibile →
409 `restart_required`, nuova richiesta senza cursore → 200 con cinque record.
Il codec è quello installato; solo il campo generazione del cursore è cambiato,
senza modificare store, clock o processo del gateway. Segreti e cursore restano
nel container. Contratto verificato nel tar consumer congelato, SHA256
`20fee824f9feb1414ae37aa7c459e4ba50ffa493d1dbb5eab5340cb7ebb932c0`;
review indipendente prima dell'esecuzione. Questa è una prova HTTP del backend,
non browser→Shopify E2E, indisponibilità del servizio o freschezza oltre 24 ore.

## Chiusura del drill isolato

Alle 20:55:53 UTC è stata completata la chiusura del drill. Entrambi i container
isolati identificati sopra, la prima istanza OOM a 1 GiB e il retry a 2 GiB/0,5 CPU,
erano stati rimossi prima della quarantena; le ricevute originali e datate, inclusi i controlli non pronti e i due
tentativi di chiusura falliti, restano conservati. L'archivio privato delle
ricevute ha SHA256
`61d6e12dad8519371d610af785682806aa7dca7220cd5876723a414d3f3edf94`.

I quattro file grandi del drill sono stati prima spostati in quarantena sullo
stesso filesystem, verificati per identità e SHA256, poi eliminati soltanto
dopo una nuova readiness HTTPS live e dieci POST funzionali firmate al container
live esistente. Le dieci richieste sono passate sulla generazione live
`sha256:839c8f07bf378351921f6d8adbb563058cf029b890079250b1d5cbedeeb8706a`;
nessuna scrittura Shopify. Readiness positiva prima e dopo, pointer e config
invariati ai rispettivi hash riportati nella tabella seguente. I controlli SQLite/hash sul checkpoint e
l'ammissione del gateway isolato hanno quindi avuto esito positivo; il runtime
temporaneo è stato poi chiuso e i suoi dati estratti rimossi.

La rimozione dei quattro file ha liberato 2.036.482.048 byte allocati e portato
lo spazio libero osservato a 11.911.491.584 byte (11,91 GB decimali). È una
riduzione del consumo temporaneo del drill, non un ulteriore guadagno da sommare
ai 3,65 GB della pulizia legacy precedente. Restano le directory piccole del
drill, il pointer restaurato verificato e le ricevute archiviate; non restano
i database restaurati né un gateway di prova in esecuzione.

Le due chiusure iniziali non sono state cancellate dalla cronologia: la prima
si è fermata sulla modalità 0644 dell'archivio, poi corretta a 0600; la seconda
ha rifiutato un controllo perché il confronto della generazione del catalogo ometteva il prefisso
`sha256:`, benché il servizio fosse valido. Il finalizer corretto ha verificato
entrambi gli ID esatti, il pin dell'immagine, le ricevute, i file in quarantena
e la protezione del live prima di completare.

## Protezione del live e prove private

Prima e dopo il restore, e dopo l'avvio isolato, i pin live sono invariati:

| Oggetto | SHA256 |
| --- | --- |
| `/var/lib/nla-staging/activation.v1.json` | `18bc7dfe87c956c697c99bd4f1c1eb5ac6b657ad84bef8192c5880fca2be4785` |
| `/opt/nla-staging/operator/catalog-refresh.json` | `2222f94698f3731d360f1adbc8e82a7eaa8cdb60bfc77d2a9a3bba74cfd945d7` |

Readiness HTTPS live positiva nei controlli di avvio e chiusura; timer e job
non modificati. Durante il drill il consumo temporaneo era circa 2,04 GB; dopo
la sua rimozione restavano 11,91 GB liberi, rispetto agli 11,92 GB dopo la
pulizia iniziale. La differenza di pochi MB è l'osservazione successiva, non una
contraddizione né spazio attribuito alla pulizia legacy.

Dodici helper/ricevute, inclusi i primi controlli non pronti, sono conservati
nella cartella privata del backup PC, `evidence/linux-drill-prepared/`, con
indice di hash. Altri otto file in `evidence/linux-drill-oom/` preservano
separatamente il fallimento e la diagnosi che giustifica il nuovo tentativo;
il primo errore di sintassi della sola diagnostica locale è conservato, poi
corretto prima della lettura VPS. Nessun dataset, ledger o segreto è stato
aggiunto a Git.

Gli ulteriori 30 helper/ricevute (169.419 byte) sono conservati in
`evidence/linux-drill-closed/`; cinque ricevute trasferite dalla VPS
(13.644 byte) in `evidence/linux-drill-vps-close/`. Gli indici riportano nomi,
dimensioni e SHA256; tutti i 12 membri dell'archivio delle ricevute sono stati
verificati contro i pin del finalizer. L'helper finale revisionato ha SHA256
`1157fa446520ec20e7a489a9f2484c3d6f5e2d276f902eefc128f65294e021d7`;
il wrapper locale ha SHA256
`50f1603000ae611320f309a37f4c8508e80d4e8955c7bac9318c8bca86acbc5d`.
La ricevuta VPS è
`/var/lib/nla-maintenance/evidence/restore-20260930-pc-checkpoint-close/closure-receipt.json`.
La copia PC originale resta intatta e le nuove prove mantengono i suoi permessi
privati e l'esclusione da Git.

## Distinguere errore di cursore e freschezza della sorgente

Le prove browser già accettate usano un server di fixture per il caso
`409 restart_required`. Un cursore che riferisce una generazione non più
disponibile è distinto da uno snapshot con sorgente oltre 24 ore. Il codice
installato non rifiuta automaticamente uno snapshot solo in base a quell'età;
il massimo TTL del cursore non è una soglia di freschezza del catalogo.
La freschezza va controllata dalla sorgente e dall'esito dei cicli. Nessuna
prova di guasto o di sorgente stale è stata eseguita sul servizio live.

Restano da provare host nuovo, caricamento dell'immagine dal backup,
configurazione/credenziali, reference nel refresh, TLS/DNS/App Proxy e importer
restaurati. Backup automatico, destinazione durevole e recapito email sono
ancora decisioni/prove aperte. Questa verifica non rende completo l'obiettivo PM.
