# Esecutore retention preparato localmente — 17 ottobre 2026

Workstream #13, ramo `agent/offsite-backup-13`, sopra il planner locale `aa2ffe5`.
Il backup installato e l'ultimo head remoto noto restano `b56ca95`. Nessuna
installazione, configurazione approvata, schedulazione o cancellazione cloud
deriva da questo lavoro. GitHub resta differito per D-024.

## Comportamento e review

Il nuovo `scripts/backup_retention.py` prepara un piano in lettura per default.
L'applicazione richiede sia il flag esplicito sia una policy privata approvata;
la proposta 7/4/6 non è attivata. Riusa il lock del backup e le primitive già
revisionate per credenziali, binario restic, scadenze e pubblicazione delle prove.
Protegge i quattro snapshot di prova obbligatori, tutte le protezioni aggiunte
e l'ultima copia riuscita, verificata contro l'inventario corrente.

Prima della rimozione per ID completi conserva un piano immutabile, rilegge gli
input e pubblica un intento persistente. Verifica poi esattamente l'inventario
residuo. Un'operazione incerta rimane da ispezionare e non viene ritentata
automaticamente. La riserva è di 6 GiB più 64 MiB per le prove del nuovo ciclo.
Configurazione, orari, limiti e riconciliazione sono descritti nel
[workstream](../workstreams/ws-09g-offsite-backup.md).

Autore `/root/retention_executor_author`; review indipendente `/root`. La review
ha fatto correggere cinque punti: timestamp reali `+02:00` e nanosecondi;
validazione dell'inventario prima della lettura; scadenza durante la scansione
dei cicli e riserva disco; distinzione tra lock occupato e errore dopo ammissione;
nuovo controllo dell'età del piano dopo la pubblicazione dell'intento.
Quest'ultimo rifiuta un piano diventato vecchio prima del comando effettivo.

## Prove e limiti

Suite mirata dell'autore: 102 PASS, copertura statement/branch 100% del solo
esecutore (224 statement, 30 branch). Ruff check/format e diff check PASS.
I test usano metadati sintetici e sostituti portabili per permessi, lock e
pubblicazione Linux: non costituiscono una prova nativa dell'esecutore.
La suite generale Windows rimane non verde per il problema di rinomina già
registrato; il test mirato successivo non lo riproduce e non lo risolve.
[Diagnosi e prove precedenti](RETENTION-PLANNER-2026-10-17.md).

Verifica congiunta indipendente del planner e dell'esecutore: **256 PASS in
10,00 s**, zero skip, copertura statement/branch 100% di questi due moduli
(397 statement, 56 branch). Non è la suite completa del repository.
Ricevute private sotto
`output/retention-executor-validation-7eda615568884440ac2e826a5c2b0048/`:
`result.json` SHA `f5d7ac9a87c08a5a4ea8fa2e5a3a70f3dd7a4391d167d159ba0773196c774348`,
`coverage.json` SHA `0604e464a4186b822524a529c27bd31f10e38d6f0385187e7c867dfcf74ac4ee`,
`junit.xml` SHA `e33934cef7ada9b69727b7858ed2b45fed343f4699decc1eb09665a21206b9fd`,
`pytest.log` SHA `1042ebdfd21c0e748f41b8a12b7170b93eefd71157faf1ec84791de1d1b29e14`.

Controlli finali locali: Ruff su tutto il worktree, format check, preflight su
223 file tracciati e build isolato sdist/wheel PASS. Ricevuta `checks.json` e
log separati nella stessa directory. Review indipendente delle evidenze PASS;
questi controlli non sostituiscono la suite generale o l'esecuzione Linux.

| Artefatto | SHA-256 |
| --- | --- |
| `scripts/backup_retention.py` | `b294f32d682ce07b9da8bd4b135d6d046813afe03024636a3612c07f288c6266` |
| `tests/test_backup_retention.py` | `f3bb94558ee62c5460492c34796eb04d7c37882477332c13f0d439b0d0bcdae5` |
| Coverage privata `output/retention-executor-coverage-20261017-a5.json` | `2dc28ac2fbde743ab11599656f52fad39302627a8239b643c0f9196968ac6532` |

Preflight VPS in sola lettura alle 11:23:52 UTC: refresh, market e backup
inattivi, ultimo esito success; 13.246.971.904 byte disco liberi e
3.393.536.000 byte di RAM disponibile. Python 3.12.3, systemd 255, modulo venv
presente ma pytest assente. Nessuna unità, dipendenza o risorsa è stata creata
sulla VPS. Questi sono prerequisiti osservati per valutare una futura prova
isolata, non un'ammissione permanente né un test Linux eseguito.
Ricevuta privata `output/nla-validation-preflight-20261017/probe.result.json`,
SHA `fff0c69f72ea8551186046e538bdfb42f921206cc3941d4534682c3376123a6d`.

Restano prova nativa, validazione completa, policy effettivamente approvata e
collaudo di installazione/schedulazione. L'esecutore rimuove solo metadati:
la compattazione `prune`, con finestra, limiti e controllo d'integrità propri,
resta necessaria per liberare spazio cloud. Le evidenze locali accumulate
richiedono inoltre un'archiviazione separata e revisionata. La retention
operativa complessiva e l'obiettivo della chat restano incompleti.
