# NLA Catalog Gateway bootstrap

Questo bootstrap temporaneo serve a trasferire nel repository il sorgente del gateway già revisionato e a costruire il database esclusivamente dallo snapshot Shopify reale.

L’archivio sorgente è deterministico e viene verificato tramite SHA-256 prima dell’estrazione. Il workflow scarica poi il JSONL Bulk dalla secret privata `SHOPIFY_BULK_URL`, costruisce SQLite, esegue tutti i test sul database reale, ricostruisce l’artefatto compresso e prova il container con limite di 512 MB.

Non sono presenti mutation su prodotti, inventario, TCG PowerTools, temi, carrello, checkout o ordini.

## Gate manuale

1. Rinominare il repository in `nla-catalog-gateway-staging`, eliminando il punto finale.
2. Caricare l’archivio fornito come `bootstrap/source.tar.gz` sul ramo `main`.
3. Creare la repository secret Actions `SHOPIFY_BULK_URL` con l’URL temporaneo del Bulk Shopify.
4. Eseguire una volta **Bootstrap source and build verified catalog**.

SHA-256 atteso dell’archivio:

`528289d87b913e6fe9a0092eec8f427b8b2eba3a239cc3f3c7641bc4b1035c84`

Dopo un’esecuzione riuscita, il workflow rimuove automaticamente la directory `bootstrap/`. Il workflow temporaneo verrà eliminato dopo la verifica del risultato.
