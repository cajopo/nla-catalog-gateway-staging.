# Ripresa consegna GitHub — 3 ottobre 2026

Jacopo ha revocato il rinvio GitHub il 3 ottobre. La ripresa tecnica è riuscita:
il repository corretto termina con il punto in `nla-catalog-gateway-staging.`;
le verifiche remote e il retry CI/CodeQL sono stati eseguiti sugli SHA indicati.
Questo risultato non equivale al consolidamento globale: restano da integrare
workstream dipendenti e richiedere review indipendenti. PR #100 ha ora CI/CodeQL
verdi; l'integrazione globale e la consegna degli altri workstream non sono finite.
Non sono autorizzati acquisti di quota o merge di controlli rossi.

## Stato delle PR interessate

- **#94 filtri:** CI e CodeQL verdi. PR ancora aperta; il branch `agent/set-rarity-filters`
  è una base dipendente per il lavoro successivo sulla ricerca per famiglia.
- **#98 CodeQL:** CI e CodeQL verdi dopo aver allineato `init` e `analyze` alla
  versione 4.38.2. PR aperta.
- **#99 CodeQL:** superata dalla correzione combinata #98; resta aperta da
  riconciliare, senza duplicare o annullare #98.
- **#100 recupero interruzione refresh (#13):** pronta per review (draft=false), stacked su
  `agent/staging-warm-activation` a `83b14e45ba20180805b2414f0c7b838041cd8ad7`.
  Head corrente `7ab94d345511ddd53c362206f041bf4942f1a61a`; CI e CodeQL verdi
  (3.885 test passati e coverage 100% su Python 3.12 e 3.13; gate locali passati).
  Il recupero VPS è terminato il 3 ottobre alle 07:29:11 UTC, exit 0. Il singolo
  refresh ordinario read-only `20261003t073240z-3f7384f8` è terminato exit 0 alle
  09:12:19; freshness, pointer, smoke e retention periodica passati.

## Sorgenti locali da consegnare

| Workstream | Tip locale salvato | Stato remoto osservato | Delta e dipendenze |
| --- | --- | --- | --- |
| Importer #97 | `agent/cardtrader-missing-printings` — `adbfa59156ada22d960c807c10e765320d6aef35` | Branch/PR dedicata assente | Il delta di 6 file (+53/−5) è dal merge-base `317126b7823032b4531e876ff0a4875b33bb98eb` fino al tip `adbfa591`; non è un diff diretto contro `agent/staging-warm-activation` (`83b14e45`), la cui ascendenza contiene già l'implementazione importer precedente. Il diff diretto da #100 head `7ab94d3` ad `adbfa591` rimuove 2.682 righe non pertinenti: non retargettare il branch intero. La fixture portabile è equivalente ai fix di test in #100; riconciliare solo quel delta. |
| Ricerca per famiglia #9 | `agent/family-search-v1` — `8d24b38124eb2c95f4f4e6481426d0b349dd3aba` | Branch/PR dedicata assente; #53 e #61 sono PR distinte di ricerca, #94 è la dipendenza filtri | La base #94 a `8634ff1` è antenata, ma il tip aggiunge 13 commit e il diff risultante è 34 file, +3.065/−83, con modifiche estranee a #9. La feature `ed24a61` da sola modifica 6 file (+415/−13); isolare feature, test e documentazione su una base di dipendenze accettata. |
| Operatore refresh/deploy #13 | `agent/staging-warm-activation` — `83b14e45ba20180805b2414f0c7b838041cd8ad7` | Branch remoto presente; PR dedicata per questo tip non individuata. #100 dipende da questo ramo. | La commit terminale modifica 3 file (+249/−8). La base #56 a `65af889` è antenata, ma la differenza integrata verso di essa è 133 file (+26.342/−642): non presentare il tip come mega-PR. Decomporre i workstream intermedi prima della review della base necessaria a #100. |
| Tema #14 | `agent/theme-family-selector` — `09821ca37bbffbcc3beef02651f59f7f106084ec` | Branch assente; #64 e #91 sono entrambe aperte | L’head #91 `c5a5dff` è antenato: il delta locale aggiunge 10 commit, 17 file (+1.172/−28). Verificare le sovrapposizioni con #64 prima di estendere o consolidare una delle PR; il branch completo contro `main` è 97 file (+23.542/−259). |
| PM #34 | `agent/pm-state-20260930` — `9f4e3906f639ef52ce60b4372f0fb1069ec34f56` | Consegna documentale separata | Branch `agent/pm-incident-state-20261003` nel checkout pulito `C:\Users\umbri\.codex\worktrees\nla-pm-incident-docs\nla-catalog-gateway-staging`, base `7ab94d3` (PR #100); 23 file solo docs, incluso `docs/workstreams/ws-09g-refresh-interruption-recovery.md`; preflight 210 file e Markdown link check passati. Conservare il root `9f4e390` come fonte PM storica. |

## Sequenza di consegna

1. PR #100 ha superato CI/CodeQL; recovery e refresh ordinario sono terminali
   con freshness/retention passati. Proseguire decomposizione e review indipendenti
   dei workstream restanti.
2. Definire una base reviewable per `83b14e4` decomponendo le dipendenze aperte;
   mantenere #100 separata e stacked su quella base.
3. Riconciliare una sola volta la fixture importer condivisa, poi isolare le
   modifiche #97 e #9 rispetto alle rispettive dipendenze.
4. Riconciliare #64/#91 prima di aggiornare il lavoro #14; evitare una terza PR
   parallela per lo stesso tema.
5. Consegnare #34 da un branch documentale pulito, includendo soltanto i file
   documentali concordati e preservando cronologia e checkout locale.

La nota registra l’inventario e l'ordine proposto; non certifica merge o release.
Recovery, refresh ordinario, freshness e retention sono passati. I checkout con
modifiche locali e gli artefatti operativi privati restano fuori da questa consegna.
