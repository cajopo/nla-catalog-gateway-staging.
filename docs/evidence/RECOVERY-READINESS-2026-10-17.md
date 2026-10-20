# Preparazione del recupero e obiettivi — 17 ottobre 2026

Aggiornamento locale, workstream operativo #13 e PM #34. GitHub sospeso per
D-024: questa nota non è una nuova consegna remota. Le precedenti prove di
recupero e QA restano valide nel proprio ambito e non sono state ripetute.

## Risorsa disponibile per il recupero da ambiente vuoto

Aggiornamento 18 ottobre: Jacopo ha confermato di non riuscire a liberare RAM;
il tentativo sul PC è rinviato. Non ripetere misure o avvii senza un cambiamento
delle risorse. La revisione degli helper conferma inoltre che
`restic-pilot.ps1 -Mode VerifyRestore` è fissato al checkpoint del 3 ottobre;
gli helper `recovery-draft` successivi richiedono Linux e percorsi VPS.
Non esiste ancora un comando PC pronto per il checkpoint del 18 ottobre:
la futura ripresa richiede adattamento e verifica dei pin, oltre alle risorse.
Nessun nuovo recupero completo o container è stato avviato. Alle 01:51 UTC
del 18 ottobre una sonda leggera ha recuperato quattro file dal backup, verificato
hash e configurazione, e provato la coppia TLS in memoria. La prova è conclusa;
non sostituisce l'avvio completo dell'applicazione con i materiali recuperati.
[Evidenza e limiti](RECOVERY-MATERIALS-2026-10-18.md).

I paragrafi seguenti conservano le misure del 17 ottobre. Primo backup automatico,
custodia della password e recapito TEST sono nel frattempo completati, come
registrato nello [stato corrente](../STATUS-CURRENT.md); resta aperto il recupero
completo. Il ripristino isolato già riuscito sulla VPS non viene ripetuto.

La verifica locale read-only delle 09:41:11 UTC registra 529.022.976 byte di RAM
libera su 6.347.137.024 visibili e 230.419.566.592 byte liberi su C:.
`wsl --list --verbose` restituisce soltanto `docker-desktop`, WSL 2, arrestata;
la pipe `dockerDesktopLinuxEngine` è assente. Nessuna distribuzione, processo,
container o configurazione di memoria è stata avviata o modificata.

Il precedente avvio del catalogo restaurato con 1 GiB era terminato OOM;
quello con limite 2 GiB richiedeva almeno 3 GiB di RAM host disponibile.
I circa 505 MiB ora liberi non ammettono quel drill. Lo spazio disco sufficiente
non risolve il limite di memoria. Nessuna nuova prova pesante è stata avviata;
non si richiede un nuovo consenso per ripetere attività già autorizzate, ma
serve una risorsa compatibile prima dell'esecuzione.

La documentazione Docker qualifica l'esecuzione di più daemon sullo stesso
host come sperimentale e richiede isolamento delle rispettive risorse.
Un secondo daemon sulla VPS esistente non proverebbe comunque provisioning,
accessi e recupero di un host sostitutivo: non è stato usato per chiudere quel
requisito. [Contratto Docker](https://docs.docker.com/reference/cli/dockerd/#run-multiple-daemons).

Ricevuta privata: `output/nla-recovery-capacity-20261017T094110Z/capacity.json`.
SHA-256: `226392f8eee9af394a86d0052367ecff2646203083c56e7f0b1092f6860c9985`.
Letture eseguite: `Win32_OperatingSystem`, `Win32_LogicalDisk` per C:, presenza
della pipe e lista WSL. Fonti ufficiali consultate:
[campi memoria Windows](https://learn.microsoft.com/en-us/windows/win32/cimwin32prov/win32-operatingsystem)
e [lista WSL](https://learn.microsoft.com/en-us/windows/wsl/basic-commands#list-installed-linux-distributions).
Ripetere il preflight quando una risorsa sarà disponibile o prima di un drill
concreto, senza polling della memoria a ogni continuazione.

Unica rivalutazione alle 11:40:09 UTC, dopo la conclusione dei processi di test
locali: RAM libera 643.268.608 byte, ancora sotto i 3 GiB richiesti dal drill
esistente. Nessun carico avviato. Ricevuta privata
`output/nla-recovery-capacity-recheck-20261017T114009Z.json`, SHA-256
`4d4886646d97320adf67b787aae2f29757a111583ea2e40e8683a4a483b553bb`.
Il recupero completo resta da eseguire quando sarà disponibile una risorsa
compatibile; ripetere questa lettura senza un cambiamento non lo sblocca.

## RPO: separare frequenza, età della copia e freschezza del catalogo

L'RPO descrive il punto dei dati al quale occorre poter tornare dopo un guasto;
il solo intervallo del timer non lo dimostra.
[Definizione NIST](https://csrc.nist.gov/glossary/term/recovery_point_objective).

Per ogni copia verificata conservare tre tempi: cattura del checkpoint,
completamento/verifica della copia fuori VPS e timestamp della sorgente del
catalogo incluso. In un incidente, usare l'ultima copia già completata:

- età del checkpoint recuperabile = istante dell'incidente meno cattura;
- età della sorgente recuperabile = istante dell'incidente meno sorgente;
- la seconda include il ritardo del catalogo già presente al momento della
  cattura. Un backup appena finito può contenere dati precedenti di diverse ore.

La proposta iniziale di RPO massimo 24 ore resta un obiettivo di recupero da
validare, non un RPO del titolare già confermato. Rimane invece concordata la
tolleranza di 24 ore per l'aggiornamento del catalogo nell'esercizio ordinario,
registrata nella [fotografia del progetto](STATE-2026-09-30.md): sono requisiti
distinti. Un timer backup ogni 24 ore, da solo, non garantisce l'RPO proposto:
prima che termini il nuovo trasferimento è utilizzabile la copia
precedente. Nel caso semplificato di catture puntuali ogni 24 ore e trasferimento
entro 2 ore, l'età massima del checkpoint si avvicina a 26 ore. Se il catalogo
era già vecchio di 10 ore alla cattura, l'età della sorgente si avvicina a 36 ore.
Sono scenari aritmetici, non misure o nuovi obiettivi approvati. Ritardi, cicli
saltati o copie fallite possono superare entrambi i valori; `Persistent=no`
non recupera automaticamente una scadenza persa durante lo spegnimento del timer.

La soglia di allarme del checkpoint a 26 ore resta distinta dall'RPO: non
garantisce recapito, presa in carico o recuperabilità. Per dichiarare raggiunte
24 ore occorrono un limite verificato alla cattura/trasferimento e alla
freschezza richiesta, oltre a una cadenza con margine sufficiente. Nessun timer
è stato cambiato. Il primo ciclo automatico è ancora previsto il 18 ottobre
alle 01 UTC e non è ancora osservato.

Shopify rimane autorevole per prodotti, prezzi, stock e ordini: questi obiettivi
riguardano le copie del sistema NLA. Per il ledger importer, una copia vecchia
richiede riconciliazione con Shopify prima di riabilitare scritture; non
riavviare automaticamente l'importer con un ledger restaurato.

## RTO: misurare l'intero intervento

Restano misurati il restore dati del 16 ottobre in 35,62632 secondi con verifica
restic, hash e tre SQLite, e i successivi smoke dei cataloghi corrente/precedente.
Il precedente avvio isolato del 30 settembre era stato osservato pronto dopo
20 minuti e 19 secondi al secondo tentativo; il primo tentativo OOM fa parte
della storia del drill. Nessuno dei due risultati misura da solo il recupero
completo del servizio.

Le 2 ore già proposte nel runbook sono un budget di esecuzione su host Linux
pronto, con accessi e chiavi disponibili. Non sono l'RTO complessivo del sito:
quest'ultimo include anche rilevamento, presa in carico, disponibilità dell'host,
recupero credenziali, trasferimento, avvio, verifiche e ripristino del percorso
pubblico. La proposta va collaudata su ambiente vuoto e resta non garantita.
[Definizione NIST](https://csrc.nist.gov/glossary/term/recovery_time_objective).

Prossimo drill: registrare inizio/fine di ciascuna fase e tutti i tentativi;
usare una copia verificata fuori VPS e un archivio immagine importato in un
ambiente inizialmente privo di quell'immagine. Verificare configurazione,
catalogo corrente/precedente e letture applicative senza attivare l'importer
o modificare il servizio live. La prova del percorso pubblico va pianificata
separatamente senza simulare guasti sul servizio operativo.

Le prove disponibili sono in [recupero Linux](RECOVERY-LINUX-2026-09-30.md),
[backup e restore](BACKUP-AUTOMATION-2026-10-15.md) e
[ultimo rollout health](BACKUP-HEALTH-2026-10-17.md). Restano aperti host vuoto,
custodia indipendente della password, primo ciclo automatico e recapito alert.
