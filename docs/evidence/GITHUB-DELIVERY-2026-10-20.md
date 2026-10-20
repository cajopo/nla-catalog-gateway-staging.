# Consegna GitHub — 20 ottobre 2026

Jacopo ha reso pubblica la repository e autorizzato la ripresa immediata
([D-030](../DECISIONS.md#d-030--completare-la-consegna-github-nella-repository-pubblica)).
La visibilità `public` è stata letta dall'API; i nuovi workflow hanno eseguito
i test. Il primo rifiuto del tentativo mattutino resta una
[prova storica distinta](GITHUB-WEEKLY-2026-10-20.md).

## Integrazioni verificate

| PR | Contenuto | Commit di merge |
| --- | --- | --- |
| [#112](https://github.com/cajopo/nla-catalog-gateway-staging./pull/112) | fix(market): retry transient source reads and preserve failure context | `dfc183692b475bcf7d99205f6f60e896d479f2fe` |
| [#113](https://github.com/cajopo/nla-catalog-gateway-staging./pull/113) | Add guarded encrypted offsite recovery checkpoints (#13) | `169843b7a6f3b39e1dc7f6554a4aff89c45907b2` |
| [#114](https://github.com/cajopo/nla-catalog-gateway-staging./pull/114) | Add a read-only operational health signal | `8cb22a84ecb44bb5ed6668968b3c64723ad9ab60` |
| [#26](https://github.com/cajopo/nla-catalog-gateway-staging./pull/26) | Bump actions/setup-python from 6.2.0 to 7.0.0 | `b1be391f1de4ddb3c205cf46d492cdfcba7eaed6` |
| [#27](https://github.com/cajopo/nla-catalog-gateway-staging./pull/27) | Bump actions/checkout from 6.0.2 to 7.0.1 | `b95696f2c09f36361e319b93f7ec2521cfc80d5a` |
| [#109](https://github.com/cajopo/nla-catalog-gateway-staging./pull/109) | build(deps): update uvicorn requirement from <0.53,>=0.52.4 to >=0.52.4,<0.55 | `757925a33d1b71f3ab54b92f9f8497495635a8a7` |
| [#110](https://github.com/cajopo/nla-catalog-gateway-staging./pull/110) | build(deps): bump actions/upload-artifact from 7.0.1 to 7.0.2 | `1a100a9bbee943cbcef506b8832dc6bc995ae462` |
| [#100](https://github.com/cajopo/nla-catalog-gateway-staging./pull/100) | Recupero refresh, riconciliato con main | `69603bd1701dd4ab8c6bd530c6bee891ef037c79` |
| [#116](https://github.com/cajopo/nla-catalog-gateway-staging./pull/116) | Ricerca FIN88/FIN-88, issue #115 | `0f0aadb6a9ed683c91c79f98611ccb9263c8bf15` |
| [#111](https://github.com/cajopo/nla-catalog-gateway-staging./pull/111) | CodeQL init/analyze 4.38.3 | `bc6599b3b0ff9c91143c578c800f5e285e35ec85` |
| [#118](https://github.com/cajopo/nla-catalog-gateway-staging./pull/118) | Evidenza acquisizione dati, issue #71 | `b20ba1edf7a6ccd34af296749a3a285612afe352` |

Per questi head sono stati verificati CI, CodeQL e gli step dei job, tutti
riusciti. Le revisioni indipendenti sono state eseguite da
`/root/operational_review` (market/backup/health) e
`/root/dependency_reconcile` (dipendenze), senza auto-approvazioni GitHub.

## Riconciliazioni e prove

- #100 è stata riportata su `main`, conservando la cronologia e la distinzione
  tra SHA di acquisizione e SHA del producer verificato. Head `adc3e1a`:
  205 test mirati passati, Ruff/format PASS, revisione indipendente PASS.
  CI `39441099703` e CodeQL `39441099620` verdi. Il job Python 3.13
  registra 4.128 test passati e copertura 100% su istruzioni e rami.
  Le iniziali prove Windows non raggiungevano le fixture per una directory
  temporanea inaccessibile; una directory dedicata ha consentito tutti i test.
- #111 allinea `init` e `analyze` a CodeQL 4.38.3. Il precedente errore era
  la configurazione prodotta con 4.38.3 letta da 4.37.9. Il blob
  `8146cc811eeda4783675b347e04f72bd7b6b9da0` è identico nel commit locale
  revisionato `d626f5d` e nel head remoto `d4119b1`.
  Preflight, 584 test del preflight e revisione indipendente PASS.
  Il client Git non aveva scope workflow; la scrittura è riuscita tramite
  l'app GitHub collegata, con il normale controllo dei suoi permessi.
  CI `39441820707` e CodeQL `39441820689` verdi su `d4119b1`.
  #98 è stata chiusa senza merge perché superata da #111.
- #116 consegna separatamente la correzione ricerca #115, già installata
  il 19 ottobre: head `e4be48d`, codice `2c8c650`; nuova revisione indipendente
  PASS. Le prove native restano in
  [ws-05](../workstreams/ws-05-code-hyphen-search.md).
  CI `39441372344` e CodeQL `39441372358` verdi sul head consegnato.
- #118 consegna solo l'evidenza testuale dell'acquisizione accettata:
  head `0b12697`, preflight PASS, revisione indipendente PASS;
  CI `39443384683` e CodeQL `39443384676` verdi. Nessuna nuova acquisizione.
- #117 consegna la patch Arena già pubblicata dal titolare e il relativo
  [rapporto](../workstreams/ws-10-arena-neon-20261019.md). Il primo tentativo
  ha rifiutato il PNG binario: 4.448 test passati e uno fallito su entrambi
  i Python. Il file è stato escluso dall'albero tracciato; originale privato
  preservato, dimensione e SHA256 verificati da un reviewer indipendente.
  Nessuna modifica ai controlli. La patch richiede baseline e PNG esterni:
  non è un archivio completo del tema. La correzione è nel head `0486382`;
  risultato CI definitivo e integrazione sono registrati nei metadati di #117.
- #101 mantiene la cronologia documentale, aggiorna chiusura della Fase 2,
  backup/restore/QA e decisioni successive. I checkpoint storici conservano
  le date; il controllo del 20 ottobre con `backup_attention` rimane aperto
  nella manutenzione operativa.

Le ultime due consegne sono [#117](https://github.com/cajopo/nla-catalog-gateway-staging./pull/117)
e questa [PR documentale #101](https://github.com/cajopo/nla-catalog-gateway-staging./pull/101).
I loro metadati registrano il commit finale, i controlli e l'integrazione:
questo documento appartiene al commit sottoposto a quei controlli e non usa
i risultati di un head precedente per certificare quello finale.
La chiusura richiede entrambe le PR fuse con CI/CodeQL verdi e review indipendente.

## Issue e backlog

#33, #62 e #89 sono chiuse con riferimenti alle integrazioni e alle prove già
presenti; #115 e #71 sono risolte dalle consegne #116 e #118. #101 consegna
il workstream documentale #34. La roadmap #3 resta aperta per il lavoro futuro.
Le issue più ampie (fra cui #7, #10, #14, #65, #68 e #97) conservano criteri
di accettazione distinti: la consegna GitHub non certifica il completamento
di tutto il backlog né aggiunge nuove funzionalità.

## Confini e materiale preservato

Nessun deploy, refresh, export, richiesta Shopify, email o modifica alla
fatturazione. La visibilità privata sarà ripristinata da Jacopo.
Il checkout originario e i worktree preesistenti sono conservati.
I candidati opzionali di retention `aa2ffe5`/`1d4cf53` restano locali e
non installati; non sono requisiti per questa chiusura. Snapshot, ricevute
operative private, credenziali e artefatti generati restano esclusi da Git.

Ricevuta di consegna privata: `output/github-delivery-receipt-20261020.json`.
La consegna usa checkout isolati in `output/github-*-20261020`.
Eliminare solo l'automazione `completa-consegna-github-nla` dopo il successo
completo; mantenere chat e `manutenzione-spazio-vps-nla` invariate.
