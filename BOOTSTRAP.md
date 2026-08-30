# NLA Catalog Gateway bootstrap

Questo bootstrap temporaneo trasferisce nel repository il gateway già revisionato e costruisce il database esclusivamente dallo snapshot Shopify reale.

Il sorgente è già presente in cinque frammenti testuali sotto `bootstrap/`. Il workflow li ricompone, verifica SHA-256, estrae soltanto percorsi sicuri, scarica il JSONL Bulk dalla repository secret `SHOPIFY_BULK_URL`, costruisce SQLite, esegue i test sul database reale, ricostruisce l’artefatto compresso e prova il container con limite di 512 MB.

Non sono presenti mutation su prodotti, inventario, TCG PowerTools, temi, carrello, checkout o ordini.

## Gate manuale

1. Rinominare il repository in `nla-catalog-gateway-staging`, eliminando il punto finale.
2. Creare la repository secret Actions `SHOPIFY_BULK_URL` con l’URL temporaneo del Bulk Shopify.
3. Eseguire una volta **Bootstrap source and build verified catalog**.

SHA-256 atteso del sorgente ricomposto:

`8bd0ef386f4187f8b7c7440af1b082a8256c0be5f5172fd3aa1bea60ae4d2541`

Dopo un’esecuzione riuscita, il workflow rimuove automaticamente la directory `bootstrap/` e il workflow temporaneo. Rimane il workflow ricorrente `Build verified catalog artifact`.
