# Pulizia VPS e verifica della retention — 30 settembre 2026

Workstream PM/documentale #34, riferimenti operativi #13, decisione D-016.
Ramo locale `agent/pm-state-20260930`; base `470ae7946838ed9decd9e99ee0144dda86154dd2`.
Jacopo ha autorizzato rimozione dei file non più necessari, preferendo prima
ricollocazione e verifica, e controlli almeno ogni 48 ore. Nessuna nuova release,
modifica Shopify, MAIN/password, PowerTools, push o CI.

## Stato aggiornato dopo il ciclo pomeridiano

Il refresh delle 15 UTC è terminato alle 16:40:13 UTC, `inactive/dead`,
`Result=success`, `ExecMainStatus=0`. Ricevuta
`/var/lib/nla-catalog-refresh/20260930t150012z-3e9f4ed1/completed.json`,
SHA256 `a7e516c0d80ba14d9e7d220ce454aee57f90e546d754ef219b55cc1fce5e576f`.
Sorgente iniziata alle 15:00:30 UTC, attivazione 16:40:10 UTC.
Mercato pomeridiano concluso alle 14:48:52 UTC, nessun nuovo candidato.
Nessun job riavviato per questa verifica.

| Identità protetta | Valore |
| --- | --- |
| Manifest corrente | `b0ca55e7597711490b18046bbce6a32a21aafa01f7b91e191f2a819a4521e690` |
| Manifest precedente | `a23f6ba25b7e5abe1ecd3c7c51adf14c14535d774f779b2652fefb35d7765399` |
| Pointer SHA256 | `18bc7dfe87c956c697c99bd4f1c1eb5ac6b657ad84bef8192c5880fca2be4785` |
| Configurazione operatore SHA256 | `2222f94698f3731d360f1adbc8e82a7eaa8cdb60bfc77d2a9a3bba74cfd945d7` |
| Immagine runtime invariata | `sha256:8a23ad0809ed155665decdea9dff875dd198f1fefe2e5764e20798a31a22ece8` |

Alle 17:29 UTC, dopo la fine del refresh, memoria disponibile circa 3,12 GiB,
runtime circa 225 MiB secondo Docker stats; limiti e capacità non ricertificati.
Il checkpoint sul PC conserva il precedente stato copiato alle 16:08 UTC,
descritto nella [prova di manutenzione](MAINTENANCE-2026-09-30.md). Non è stato
sovrascritto o presentato come copia della nuova generazione attiva.

## Artefatti rimossi

Inventario alle 17:46 UTC: percorsi, dimensioni e riferimenti; nessuna lettura
di credenziali o esportazione di prodotti. Sono stati scelti soltanto:

| Percorso originale | Motivo / dimensione logica |
| --- | --- |
| `/var/lib/nla-staging/generations/59e3fb1ad32e9993ea03d7af1ddc82d3b72164f962be1bebe043e41cd51f2ce6` | Generazione legacy non corrente/precedente, 889.988.203 byte |
| `/var/lib/nla-staging/generations/8ae43faa539325ad66380e990c3528b13c92d20dd9ef1da60749b91cf33932e8` | Stesso criterio, 889.988.203 byte |
| `/var/lib/nla-staging/generations/a8d03eb658068a63b5b3e4db355a29957af4818c359b22f0a4770b8fa475d4ea` | Stesso criterio, 889.988.203 byte |
| `/opt/nla-staging/incoming/package-current-v2` | Vecchio package del 15 settembre non referenziato, 889.988.203 byte |
| `/opt/nla-staging/incoming/catalog-package.tar.gz` | Archivio in ingresso del 17 settembre non referenziato, 94.968.541 byte |

Esclusi: corrente/precedente, ultime acquisizioni, ledger importer, reference
canonica in uso e relativa possibilità di rollback, configurazione, credenziali,
certificati e sorgenti installati. Escluso anche il vecchio restore drill del
21 settembre da circa 3,56 GB: due container arrestati montano ancora i dati
restaurati. È distinto dal drill del checkpoint PC chiuso più avanti in questa
cronologia.
Durante questa pulizia legacy non sono stati rimossi container, immagini o volumi Docker.

Quarantena alle **17:58:32 UTC**, tramite rename sullo stesso filesystem in
`/var/lib/nla-maintenance/quarantine/20260930-first-retention/`, privata root.
Guardie: pipeline inattive, lock non bloccanti di pipeline/attivazione, pointer e
config invariati, manifest protetti validi, percorsi canonici e owner verificati,
nessun link/file speciale, ogni elemento vecchio almeno 48 ore. Il reviewer
indipendente `gpt-6-luna` ha richiesto il controllo di età anche sui file annidati;
correzione applicata prima dello spostamento. Readiness positiva prima/dopo.
Lo spostamento da solo non ha liberato spazio.
Il requisito di età è imposto dallo script conservato; la sola ricevuta di
quarantena non contiene le età individuali. Riscontro dal piano pre-cancellazione:
17 elementi, tutti almeno 48 ore al momento della quarantena; età minima
220,076 ore. Confronto SHA della ricevuta PASS, resoconto privato
`retention-age-evidence.json`. Il rename ha conservato gli mtime verificati.

Prova funzionale alle **18:12:34 UTC**: dieci POST autenticate al runtime
esistente, dall'interno del container, senza esportare i segreti. Due pagine
da cinque risultati senza sovrapposizione per Pokémon/Magic/Yu-Gi-Oh!/One Piece,
più ricerca e suggerimenti per Pikachu/Charizard. Tutti passati sulla stessa
generazione dati `sha256:839c8f07bf378351921f6d8adbb563058cf029b890079250b1d5cbedeeb8706a`.
Prima diagnostica: il controllo usava erroneamente `one_piece`; risposta 400
`invalid_request`. Il valore canonico verificato nei sorgenti è `one-piece`;
corretto il solo controllo, nessuna correzione del servizio. Esito sanitizzato
conservato, senza URL firmati. Non è una nuova prova browser end-to-end Shopify.

Cancellazione alle **18:16:33 UTC**, dopo review indipendente senza blocchi.
Target fissi confrontati con la ricevuta di quarantena; originali ancora assenti,
batch allowlist, controlli freschi di mount/container/processi, nessun hardlink,
`rmtree` con protezione dai symlink. Metadati e piccoli JSON salvati prima della
rimozione; lock, readiness e pin ricontrollati. Nessuna cancellazione generica.

| Misura effettiva | Byte | GB decimali |
| --- | --- | --- |
| Libero prima della cancellazione | 8.260.841.472 | 8,26 |
| Allocato dai target rimossi | 3.654.983.680 | 3,65 |
| Libero dopo cancellazione e sync | 11.915.825.152 | 11,92 |

Readiness e hash pointer/config invariati. Le dieci richieste funzionali sono
state ripetute dopo la cancellazione alle **18:17:09 UTC**, tutte passate.
Non dimostra una garanzia futura di spazio o la certificazione QA completa.
Il campo `sourceUnchanged` della ricevuta grezza è un'etichetta troppo ampia:
lo script verifica pointer/config, senza un nuovo hash dei sorgenti installati.
Il campo non viene usato come prova di immutabilità dei sorgenti; la ricevuta
originale è conservata e il limite è esplicitato qui.

## Chiusura successiva del drill di restore

Questa è una pulizia distinta dalla retention legacy sopra. Il drill del
checkpoint PC sulla stessa VPS, documentato nella [prova Linux](RECOVERY-LINUX-2026-09-30.md),
è stato chiuso alle **20:55:53 UTC**. Prima sono stati rimossi solo i due
container identificati; poi i quattro file grandi del drill sono stati spostati
in quarantena sullo stesso filesystem. I file sono stati eliminati dopo
verifica SHA/inode e smoke live di dieci POST firmate passato. Readiness HTTPS live
pronta prima/dopo; pointer e config conservano gli hash documentati. Il primo
container OOM e i due rifiuti iniziali del finalizer sono mantenuti nella
cronologia delle ricevute; non sono stati rimossi altri container, immagini,
volumi o directory.

I quattro file occupavano 2.036.482.048 byte allocati. Il libero finale è
11.911.491.584 byte (11,91 GB decimali). Questo riduce il consumo temporaneo
del drill e non si somma come nuovo recupero ai 3,65 GB della pulizia legacy.
Il restore e l'ammissione sullo stesso host hanno avuto esito positivo, ma i
database restaurati e il runtime di prova sono stati rimossi; non sono una
installazione recuperabile attualmente residente. Le ricevute di chiusura
sono archiviate privatamente; nessun dato è stato aggiunto al repository.

## Pulizia ordinaria già automatica e nuovo controllo

Alle **18:22:18 UTC**, i timer VPS risultano attivi: refresh alle 03/15 UTC,
mercato alle 02/14 UTC; `Persistent=no` invariato. Nell'operatore installato,
`scripts/refresh_staging_catalog.py:501` chiama retention prima di pubblicare
`last-success.json`. Quest'ultimo è identico alla ricevuta completata e concorda
con il pointer attivo. Piano retention SHA256
`9808b8516c843a931b59fbebb91ae7d985ab56c3ec947f38e423b2cf35d63735`:
due directory e tre container registrati; entrambe le directory pianificate
risultano assenti. Rimangono due run ordinari completati e due generazioni protette.

La retention dei normali artefatti è dunque eseguita sulla VPS dopo i refresh
riusciti, previsti due volte al giorno, senza consumo di token. Non viene
garantita dopo cicli falliti e non copre qualsiasi file legacy fuori pipeline.
L'operatore può eliminare le ricevute dei vecchi run ordinari insieme ai loro
dati; l'archivio storico completo richiede ancora una politica fuori host.

Nuovo heartbeat di questa chat **`manutenzione-spazio-vps-nla`**, creato tramite
lo strumento dell'app, ACTIVE, ogni 48 ore; configurazione riletta, unica automazione
NLA presente. Distinto dal precedente `verifica-ciclo-nuove-uscite-nla`, non ricreato.
Usa un checker di metadati in sola lettura e attiva approfondimenti/pulizia solo
quando giustificati. Notifiche solo per cambiamenti rilevanti, errori o interventi;
nessuna email. PC e app Codex devono essere in esecuzione: questa parte non è
un presidio continuo garantito né un nuovo timer sulla VPS. La procedura e i pin
degli helper sono nel [runbook](../OPERATIONS-RUNBOOK.md).

## Conservazione e fonti

Ricevute VPS e piccoli metadati rimossi conservati in
`/var/lib/nla-maintenance/evidence/20260930-first-retention/`.
Sul PC, sotto `output/nla-recovery/20260930/evidence/`, copiati 16 file per
66.910 byte, inclusi helper, esiti e archivio dei metadati. Indice privato
`retention-evidence-index.json`; cartella esclusa da Git, ACL privata invariata.
Nessun database o archivio di catalogo aggiunto al repository.

Documentazione ufficiale consultata prima dell'uso:
[Python 3.12 filesystem](https://docs.python.org/3.12/library/os.html),
[shutil](https://docs.python.org/3.12/library/shutil.html),
[flock](https://docs.python.org/3.12/library/fcntl.html),
[Docker inspect](https://docs.docker.com/reference/cli/docker/container/inspect/),
[Docker stats](https://docs.docker.com/reference/cli/docker/container/stats/),
[systemd timer 255](https://raw.githubusercontent.com/systemd/systemd/v255/man/systemd.timer.xml)
e [automazioni Codex](https://learn.chatgpt.com/docs/automations?surface=app).
Skill OpenAI Docs applicata per il comportamento del controllo programmato;
lettura del contratto runtime e degli helper dai sorgenti installati conservati.
La documentazione freedesktop v255 ha restituito 403: usata la fonte ufficiale
del tag v255 su GitHub, senza dedurre opzioni dal solo ricordo.

Consegna documentale locale: otto documenti, 57 link locali validi, tre cronologie
invariate nei checksum normalizzati. Preflight dell'indice PASS, 126 file e zero
findings; diff-check PASS. Review indipendente della cancellazione e dei claim
documentali completata, due limiti di evidenza qualificati come descritto sopra.
Modifiche pre-esistenti AGENTS/GraphQL preservate e non incluse; nessun nuovo
codice applicativo, backup o dato nell'indice. Suite applicativa non ripetuta
per questa sola documentazione; verifiche operative effettive riportate sopra.
