# PM handoff — Next Level Arena catalog gateway

## Latest acquisition handoff — 2026-09-18 (#89)

Pronto il comando minimo sulla VPS: due esportazioni Shopify di sola lettura,
download verificato e riuso della riconciliazione/packaging esistenti. Ogni ripresa
conserva gli identificativi; un avvio incerto richiede recupero esplicito, non un
duplicato. Nessun nuovo servizio, pianificazione o attivazione automatica.
180 test nativi Linux PASS in 6.25s, entrambi i componenti al 100% linee/rami;
review indipendente PASS dopo due correzioni Medium. CI dell'head ancora richiesta.
Dettagli: `workstreams/ws-07-vps-bulk-acquisition.md`. Installazione e credenziali
reali dell'app, sorgenti canoniche correnti e prova App Proxy restano da completare;
questo risultato non chiude #11, #89 reale o l'obiettivo complessivo.

## Latest pagination handoff — 2026-09-15 (#69)

Il candidato permette di continuare una navigazione sul catalogo originale dopo
l'attivazione di uno nuovo; le nuove ricerche usano il nuovo catalogo. Coperti ricerca
nome/codice, esauriti, richieste in corso, scadenza e cambio chiave. Nessun bypass dei
controlli. 257 regressioni PASS, compreso traversal HTTP di 30.001 prodotti, modulo
runtime al 100%, review del diff APPROVE, preflight su 112 file senza errori.
CI dell'head ancora necessaria. La conservazione è soltanto nel processo:
riavvio/repliche e dimensionamento reale restano aperti, quindi #7 e
l'obiettivo completo non sono chiusi. Nessuna modifica Shopify/PowerTools/tema/deploy.
Dettagli: `docs/workstreams/ws-03b-retained-cursors.md`.

## Latest packaging handoff — 2026-09-15 (#67)

Applicata una semplificazione concreta dell'audit: il packaging costruisce il DB una
sola volta e consegna proprio quello verificato, senza ripetere la costruzione.
Nessuna prova di completezza, ricerca o integrità rimossa. I 122 test mirati passano;
i due moduli modificati sono coperti al 100%. Review indipendente APPROVE; altre 233
regressioni passano, compreso il traversal HTTP su 30.001 prodotti. CI del nuovo SHA
ancora richiesta. La CI del parent #66 è stata cancellata al limite di 15 minuti
durante la suite grande: non è verde e non autorizza merge.
Nessun pacchetto reale nuovo, deploy o intervento Shopify. Gli export grezzi nelle
cartelle temporanee storiche risultano assenti: servirà recuperarli o riacquisirli
in sola lettura. Il vecchio pacchetto non equivale a dati attuali.
L'app Shopify collegata non restituisce precedenti Bulk riutilizzabili; altre app
possono avere una cronologia diversa. Nessun nuovo export è stato ancora avviato.

## Latest data handoff — 2026-09-15 (#65)

Recuperati i quattro CSV originali: non serve ricaricarli. Il nuovo candidato porta
numero carta, espansione e rarità fino all'API tramite ID verificati; numero carta
ricercabile con suggerimenti, esauriti inclusi. Nessun codice composto inventato.
Corretti tre problemi emersi su dati reali/review; 485 test passano e re-review APPROVE.
Tutti i 332.667 record dei quattro CSV vengono letti; CI del nuovo head ancora richiesta.
Passata anche la prova di 30.001 risultati cercati solo per numero carta, tutti esauriti.
Parent PR #64 ora CI/CodeQL verde. Il percorso reale clone/staging resta da completare.
Dettagli: `ws-01h-card-metadata.md`.

## Latest clone UI handoff — 2026-09-15 (#14)

Ripresa sul percorso cliente, senza riscrittura generale. Il candidato locale contiene un
solo componente Liquid riutilizzabile: selettore gioco, suggerimenti, esauriti e paginazione
con URL. Clone identificato in sola lettura e ancora UNPUBLISHED; nessun upload/MAIN.
Runtime #63 verde in CI e CodeQL. Validazione Shopify: 7 file validi; test browser: 18 PASS.
Corretti tre P2 di stato/focus e un P3 di tastiera; re-review indipendente APPROVE.
Push eseguito e PR #64 aperta draft su #63, implementazione `0d0345c`; CI del nuovo head
ancora da verificare. Nessuna installazione clone o verifica E2E reale ancora dichiarata.
Non è ancora il sito funzionante: mancano endpoint reale, installazione clone, dati/codici
e immagini completi, aggiornamenti persistenti ed E2E. Dettagli in `ws-10-theme-clone.md`.

## Latest runtime handoff — 2026-09-15 (#62)

`agent/runtime-verified-output` is based on `162edb4` (#61, now fully CI green).
Concrete service output/readiness uses existing evidence-bound authorization; no static
global enable switch. Default/unsigned/obsolete-proof paths still deny. Proof schema v2
checks real SQL semantics against source records; package filenames remain v1, but old
proof contents are rejected. Removed unused prepared search/facet/item copies; retained
single-name bounds in projection validation. See the current runtime workstream document.
Review approved after a query-normalization P2 fix; 368 focused tests pass, changed
modules at 100% coverage, plus the separate 30,001-product signed service traversal.
Build, preflight and scoped Ruff pass; exact-head remote CI still required.
No real package acceptance, provider deployment or clone integration. The full goal stays open.

## Previous search handoff — 2026-09-15

Issue #60 is implementing the actual name-or-code substring requirement on
`agent/search-name-code-v2`, based on unmerged #57. Runtime result pagination now uses
SQLite for search and stock filters as well as plain browse; literal matching does not
discard substring hits when an exact match exists. Sold-out products remain included.
Suggestions are now wired to the optional HTTP response field on the first search page,
using explicit `includeSuggestions: true` opt-in and the same leased database/filter
scope; 40 new tests pass. Existing clients retain their response shape. Clone UI and public
activation are still pending. No extra endpoint or service was introduced.
SKU/barcode data are available in the record contract; printed collector codes still
need a verified source join. No real dataset acceptance, deployment, clone integration
or full sync completion is claimed. Independent review approved after one P2 fix. Final
focused checks: 66 pagination/search cases at 100% module coverage, 149 runtime cases and
78 contract cases. The preceding `ab0c26e` now has fully green CI/CodeQL. The suggestion
follow-up has 198 passing regressions and 100% runtime API coverage; final new-head CI
remains required. The separate 30,001-product HTTP traversal passed, including search
plus suggestions under two seconds on synthetic data. No Shopify writes.

The historical staging SQLite package was recovered. Fresh read-only coverage shows
291,787 public singles all with SKU and none with barcode. SKU format is not equivalent
to the printed code; source CSVs were requested. Initial SQL suite: 20 passed, including
30,001 code-only sold-out results without gaps. Runtime-contract suite: 78 passed.

The older block below is historical and must not be copied as current status.

Updated 2026-09-01T02:59:58+02:00.

Copyable update:

> Platform PR #20 remains draft. Reviewer v3 returned `CHANGES REQUIRED` on `82ec0e4` for one
> High: shell/PowerShell `$()` subexpressions. Remote candidate `73f3f78` and local equivalent
> `db86bd3` share one tree; local Ruff/build/audit/Docker smoke and static replay, 564 tests at
> 100% line/branch,
> preflight over 25 files, and static red team all pass. Exact CI `33456765768` and CodeQL
> `33456765740` now pass, with zero CodeQL security findings. D-008 bans `$()`, `<()`, `>()`,
> and `@()` conservatively, and rewrites container smoke as direct `docker run | python`. Final
> docs-inclusive gates and reviewer
> v4 remain required before merge. `NLA_DATA_ROOT` is missing; no Shopify or live action occurred.
