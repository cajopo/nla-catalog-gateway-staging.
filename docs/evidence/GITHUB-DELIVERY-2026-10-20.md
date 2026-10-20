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

Per questi head sono stati verificati CI, CodeQL e gli step dei job, tutti
riusciti. Le revisioni indipendenti sono state eseguite da
`/root/operational_review` (market/backup/health) e
`/root/dependency_reconcile` (dipendenze), senza auto-approvazioni GitHub.

## Riconciliazioni e verifiche in corso

- #100 è stata riportata su `main`, conservando la cronologia e la distinzione
  tra SHA di acquisizione e SHA del producer verificato. Head `adc3e1a`:
  205 test mirati passati, Ruff/format PASS, revisione indipendente PASS.
  Le iniziali prove Windows non raggiungevano le fixture per una directory
  temporanea inaccessibile; una directory dedicata ha consentito tutti i test.
- #111 allinea `init` e `analyze` a CodeQL 4.38.3. Il precedente errore era
  la configurazione prodotta con 4.38.3 letta da 4.37.9. Il blob
  `8146cc811eeda4783675b347e04f72bd7b6b9da0` è identico nel commit locale
  revisionato `d626f5d` e nel head remoto `d4119b1`.
  Preflight, 584 test del preflight e revisione indipendente PASS.
  Il client Git non aveva scope workflow; la scrittura è riuscita tramite
  l'app GitHub collegata, con il normale controllo dei suoi permessi.
  #98 sarà superata solo dopo l'integrazione di #111.
- #116 consegna separatamente la correzione ricerca #115, già installata
  il 19 ottobre: head `e4be48d`, codice `2c8c650`; nuova revisione indipendente
  PASS. Le prove native restano in
  [ws-05](../workstreams/ws-05-code-hyphen-search.md).
- #101 mantiene la cronologia documentale, aggiorna chiusura della Fase 2,
  backup/restore/QA e decisioni successive. I checkpoint storici conservano
  le date; il controllo del 20 ottobre con `backup_attention` rimane aperto
  nella manutenzione operativa.

Questo checkpoint non certifica ancora la chiusura delle PR in verifica.
Il completamento richiede i loro controlli sul commit finale e il merge
documentale. I metadati GitHub delle PR registrano SHA e risultati definitivi.

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
