# Legame delle prove QA con il componente installato — 18 ottobre 2026

Lettura Shopify Admin in sola lettura: negozio `NEXT LEVEL ARENA`, dominio
`bb5c19-c9.myshopify.com`, tema `175195881740` in ruolo MAIN. Nessuna modifica
di tema, password, prodotti o sessioni browser. Le query sono state precedute
da documentazione e schema; il validatore ha indicato validazione demandata
all'esecuzione, e le letture sono riuscite.

Il confronto iniziale dei checksum grezzi del componente non coincideva.
La lettura mirata di `snippets/nla-catalog-search.liquid` e `locales/it.json`
ha chiarito la differenza: **normalizzando esclusivamente i terminatori di
riga, il componente installato coincide con quello della fixture del
30 settembre**. Anche i valori di tutti i 41 testi italiani referenziati
coincidono. Confronto riprodotto indipendentemente dall'agente principale.

| Materiale | Hash |
| --- | --- |
| Snippet corrente, MD5 restituito da Shopify e riprodotto sui byte salvati | `aec87ea2e48828cc876e770954d9bb98` |
| Snippet corrente, SHA-256 grezzo | `76fcca53a2e7b481404281f803faa881158d2c2f7c93f708ff6a8a18efc3515d` |
| Storico e corrente, SHA-256 dopo normalizzazione delle righe | `5504c21db5816b9b048c04749d7385f259321c9bca72869dde3187c109094c9f` |
| File storico con CRLF, corrispondente alla ricevuta QA | `76dfaa5ac13ae492ef2024f2638d606dd107922656d467f28574693ff1d355de` |

Baseline recuperata dal tree Git locale
`2d66cbd609db158450824d2d71347d7e8bda9ddd`, senza accesso GitHub.
La lingua corrente contiene un commento iniziale generato da Shopify:
il confronto delle traduzioni legge il JSON dopo quel commento, conservando
integri i byte acquisiti. Il vecchio harness usa direttamente `JSON.parse`;
la copia di preparazione non è quindi pronta per un nuovo run senza gestire
esplicitamente quel commento. Nessun browser o test QA è stato riavviato.

Si riutilizzano le prove del **componente** già registrate in
[MAINTENANCE](MAINTENANCE-2026-09-30.md): matrice Chrome/Firefox/WebKit,
viewport, tastiera, risposte stale/malformate, 503 e Retry nella fixture,
e controlli axe con il limite già documentato. Non si trasformano queste
prove in una verifica dell'intero tema, della navigazione Shopify o di un
guasto reale. Browser/PDP/carrello e il contesto completo di accessibilità
restano distinti; non aggirare il diniego tecnico di accesso a Chrome.

## Evidenza privata

`output/nla-qa-component-fixture-20261018-01/` contiene le risposte, i file
grezzi e `independent-comparison.json`, SHA-256
`6fbd0bd94afedfc3cbc3a156e0c2dbbbfad01fa682fa8b972780b2ae4711ae11`.
La risposta della lettura mirata dei corpi ha SHA-256
`14436cead34f84345c058cccd3f7eb05b0fdd10eec2415f7b535f48e5706209f`.
La query iniziale di inventario aveva restituito solo 250 file con altre
pagine disponibili: non è usata come inventario completo. Il vecchio export
completo non è disponibile; nessuna equivalenza dell'intero tema è dichiarata.

Contratto: [Shopify Admin GraphQL, theme](https://shopify.dev/docs/api/admin-graphql/2026-10/queries/theme).
