# Preparazione retention e prova locale — 17 ottobre 2026

Workstream #13. Componente locale su `agent/offsite-backup-13`, nel worktree
`C:/Users/umbri/.codex/worktrees/nla-offsite-backup/nla-catalog-gateway-staging`.
Base, ultimo head remoto noto e backup installato: `b56ca95fad2824b9faafc84c9f97ce66942fe75d`.
Questo delta non è installato né pubblicato: D-024 rinvia ogni azione GitHub.
La regola 7 giornaliere / 4 settimanali / 6 mensili resta una proposta inattiva.

## Componente preparato e limiti

`scripts/backup_retention_plan.py` è un modulo puro: valida inventario e output
JSON di un dry-run restic 0.19.1, senza rete, file, processi o CLI. Verifica la
partizione completa keep/remove per il solo hostname ammesso e le motivazioni
di conservazione. Sottrae dai candidati tutti gli ID protetti forniti e l'ultimo
backup riuscito. Accetta gli offset RFC3339 realmente osservati e percorsi
assoluti Windows/POSIX; confronta tutti i metadati ignorando solo `short_id`.

La funzione `exact_forget_arguments` produce argomenti con soli ID completi,
oppure `None` se non ci sono candidati, dopo aver verificato piano, inventario
aggiornato, ultimo successo e anzianità massima di cinque minuti. Il legame
tramite hash rileva cambiamenti; non costituisce autorizzazione alla rimozione.
Sono imposti limiti JSON di 4 MiB e 1.000 snapshot, con rifiuto di duplicati,
numeri non finiti, metadati incoerenti e timestamp futuri oltre la tolleranza.

L'esecutore futuro deve caricare l'intero insieme di prove protette da una
policy attendibile, applicare una regola approvata, coordinarsi con il backup,
ripianificare, produrre ricevute immutabili e confrontare lo stato finale.
Il lock esterno del backup è `/var/lib/nla-backup/.pipeline.lock`: copre cattura,
trasferimento, verifica, pulizia e ricevuta. I lock market/refresh della cattura
vengono invece rilasciati prima del trasferimento. Il modulo non acquisisce lock
e non risolve da solo la concorrenza fra inventario e cancellazione.

Nessun esecutore cloud, timer o modifica al backup corrente è aggiunto.
Compattazione e schedulazione richiedono una finestra e prove proprie.
Il contratto distingue `forget` con ID espliciti, che produce stdout JSON vuoto,
dall'output di policy; exit 3 resta un errore parziale. Riferimenti ufficiali:
[conservazione restic](https://restic.readthedocs.io/en/stable/060_forget.html),
[contratto JSON](https://restic.readthedocs.io/en/stable/075_scripting.html).

## Prova con repository locale reale

Eseguita dalle 10:22:55 alle 10:23:19 UTC con restic Windows 0.19.1, repository
nuovo con soli piccoli fixture sintetici, password effimera e ambiente privato
senza credenziali cloud. Tutti i 27 comandi sono terminati exit 0.

- 14 snapshot creati; tre soli candidati effettivi rimossi con ID completi.
- Inventario finale di 11 snapshot esattamente uguale all'atteso.
- Una copia protetta selezionata dal piano grezzo è stata esclusa; anche
  l'ultimo successo e lo snapshot di un altro hostname sono conservati.
- Compattazione del repository sintetico e `check --read-data` riusciti.
- Tutti e quattro gli snapshot protetti sintetici ripristinati con `--verify`;
  contenuto confrontato tramite SHA-256 con i rispettivi fixture originali.
- Replay offline delle ricevute cloud delle 09:47 UTC: zero candidati effettivi,
  conflitto protetto `bd249a0d…` preservato, nessun comando di rimozione prodotto.

La prova non ha usato VPS o Backblaze, modificato snapshot reali o installato
una policy. Dimostra selezione e compatibilità con il binario su dati sintetici;
non è una prova del futuro esecutore Linux, della schedulazione o del recupero
completo da host vuoto. Le date dei fixture seguono il timezone del binario.

Un primo tentativo alle 10:21 UTC si era fermato al comando `init`, prima di
creare il repository: l'helper usava erroneamente `--repository`. Diagnostica
locale e help del binario hanno identificato l'opzione corretta `--repo`.
L'helper corretto è stato eseguito in una nuova directory; la prova fallita
resta conservata. Non è stato un guasto del servizio o del repository cloud.

## Verifiche e ricevute

Autore del modulo e reviewer separati; 154 test mirati PASS con copertura
statement/branch 100% del nuovo modulo (173 statement, 26 branch). Review
indipendente anche del confinamento dell'helper sintetico. Ruff check/format,
preflight su 220 file tracciati e build isolato Python 3.12.14 PASS. Il primo
tentativo della suite completa (4.381 test raccolti) è terminato alle 10:50:58
UTC per il timeout di 1.200 secondi dell'helper, prima del riepilogo e senza
JUnit/coverage finale: non è verde. Processi verificati terminati.

Diagnosi mirata su quattro casi, senza ripetere i tre file interi: tre PASS e
un errore Windows `PermissionError/WinError 5` alla rinomina della directory
temporanea del test Bulk sulle forme media. I sorgenti coinvolti sono invariati
rispetto a `b56ca95`. Lo stesso caso passa in 0,85 s con una nuova base temporanea
più corta e senza cambiamenti a codice, ACL o soglie; ciò circoscrive il problema
all'esecuzione locale ma non dimostra se la causa sia lunghezza o lock transitorio.
Non è stata aggiunta una correzione speculativa al servizio.

La nuova suite con base corta esclusiva e stop al primo errore è terminata
alle 11:01:19 UTC, exit 1: **1.712 passati, uno fallito, zero skip**; 389,67 s.
Il nuovo planner e tutto `test_bulk.py` passano. Il test importer
`test_guard_failure_records_safe_cause_without_retry_or_creation[error2-identity_export_stale]`
fallisce preparando un sidecar, su `canonical_names.py:578`: Windows nega un'altra
rinomina di directory con `WinError 5`, anche su percorso corto. Quindi ridurre
la base temporanea non ha risolto il problema generale. Review read-only:
entrambi i builder chiudono i loro file prima della rinomina; il planner non ha
effetti su file o processi. La causa del rifiuto del filesystem non è ancora
attribuita. Nessuna modifica a ACL, antivirus o gestione degli errori del servizio.

La suite completa e la sua copertura globale restano **non verificate**; non
sono eseguiti altri retry generali senza una nuova diagnosi. Questa è preparazione
locale, non una consegna pronta da integrare o distribuire. La validazione
completa resta un gate aperto; le operazioni CI su GitHub sono differite da
D-024. La CI di `b56ca95` non viene attribuita al nuovo delta.

| Artefatto | SHA-256 |
| --- | --- |
| `scripts/backup_retention_plan.py` | `e232d55b3db1485b159eded7c6481b5b38e53d81b45794a6fed0f6f757ae1dba` |
| `tests/test_backup_retention_plan.py` | `0a5116a307217ce2a5507b4b58cfd835559a44ddf39aa27ad213f35c13187d19` |
| Ricevuta sintetica riuscita `result.json` | `665038a5d82291e82e36a51a73d5b465b10868fe8db1b0592c66ad5d2b8505a4` |
| Binario restic Windows 0.19.1 | `b0dd1fd21eea5d8fe1325f55f7118213c21f36de8a261e04c0624a5ab9fd7830` |
| Helper sintetico `output/nla-retention-local-proof.py` | `87ca8b48484f59fa0d478fc409312427739eba469d486157ae2b36f7d4ead07b` |
| Review `output/nla-retention-plan-root-review.json` | `7eb0faf6e53dfb48d4d70ca61b75f1d6b9b7eda285f2c9bdb941c428e38ee060` |

Ricevute private nella directory principale del progetto, sotto
`output/nla-retention-local-proof-20261017T102255Z-2439dcb7cb9c43adab82d693f701715c/`.
Helper riproducibile `output/nla-retention-local-proof.py`: verificarne il pin
nel checkpoint prima dell'uso; crea ogni volta un repository locale esclusivo.
Review `output/nla-retention-plan-root-review.json`.
Primo tentativo conservato in
`output/nla-retention-local-proof-20261017T102112Z-61e1357e1bc64d9198ba53884f0b5a8f/`.
Le ricevute originarie cloud sono conservate separatamente e non sono state
riscritte. L'obiettivo operativo complessivo resta aperto.

Validazione iniziale sotto
`output/nla-retention-full-validation-20261017T103056Z-cfb276070f7143a189583f403f69107e/`:
`result.json` SHA `5b694667f2fefd9f328b57ad5b82325401fa9038cdec9a7421a68a090611cdbf`,
`pytest.log` SHA `95dfed882651836e2e7d856ae77ea896904438c3d42a3414fa594758ef2d186d`,
`independent-checks.json` SHA `42ef657ed96be63b0c62b9161e2f06948bdeb0f474100d107f3cc3decc11c0d9`.
Diagnosi in `diagnosis/pytest.log` e `diagnosis/short-path.result.json`.
Seconda esecuzione sotto `output/nla-retention-full-final-20261017-e2d861ca/`:
`result.json` SHA `4a0ae7f219159582d03645d3fb612375007f32c42c18da24111ccc34cf845b1c`,
`pytest.log` SHA `01cf0c960efcf575857b8501e65182e765c1fbcbb65ec9c42d3e123659338a6a`,
`junit.xml` SHA `a078dca995418db8dfb25723d2102e8398ef517545300b36ff5d9d737d44dff4`.
JUnit attesta 1.713 test eseguiti, uno fallito, zero errori di setup e zero skip;
tempo JUnit 388,855 s, distinto dal riepilogo pytest di 389,67 s. Il file di
copertura JSON globale non è stato prodotto. Nessuna suite resta in esecuzione.

## Diagnostica mirata successiva — 11:14 UTC

Una sola esecuzione degli otto parametri del test importer fallito è passata:
otto PASS in 19,10 s, 16 rinomine osservate, nessun errore. Sorgenti e permessi
invariati; nuova directory temporanea esclusiva. L'helper privato, revisionato
indipendentemente, invoca la rinomina originale una sola volta e ne propaga
l'eventuale errore. Soltanto al fallimento raccoglie attributi, ACL e processi
che usano i file tramite Restart Manager, senza chiudere handle o processi.
Il fallimento non si è riprodotto: nessuna ACL o lista di processi è stata
acquisita da questo helper e nessuna causa è stata dimostrata. Un risultato
vuoto sui file, inoltre, non escluderebbe un handle sulla directory.

La verifica precedente del sorgente colloca il rifiuto prima del controllo
`identity_export_stale` iniettato dal test; non sono raggiunte le sue assertion
né le chiamate Shopify previste. La diagnosi non dimostra una correzione e non
chiude la validazione generale. Evitare altri retry generali senza una nuova
ragione diagnostica o una modifica da validare.

Ricevute private sotto `output/nla-rename-diag-a1960fef/`:
`result.json` SHA `435ed4f354e7b6b89d3ad04893cf6191c031e752e30efbd7fefdc1d9c05c22fa`,
`junit.xml` SHA `dae6e24e92c8d0ff0e850c17797288268bcdc5fd2c99f61f1b80acc6db279371`.
Helper `output/nla-rename-diagnostic.py` SHA
`fc0d7f41a62056545f066d658efa09ef4995e7da140da3b212a99b05c9717a46`.
Contratti consultati: [Get-Acl](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.security/get-acl)
e [Restart Manager](https://learn.microsoft.com/en-us/windows/win32/api/restartmanager/nf-restartmanager-rmgetlist).
