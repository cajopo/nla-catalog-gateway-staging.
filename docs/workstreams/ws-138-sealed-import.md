# Issue 138 — Importazione dei sigillati

Il proprietario ha autorizzato i sigillati come SKU ordinari, con gli stessi
controlli delle singole. Le categorie sealed esplicitamente mappate entrano nel
ciclo automatico; categorie ignote e identità assenti o ambigue restano
rendicontate e non vengono indovinate. Il confronto fresco con Shopify e il
ledger evitano la creazione duplicata e non modificano prodotti preesistenti.

I nuovi prodotti nascono in bozza con stock zero. Per la tassonomia già
distribuita usano un product type vuoto e i metafield strutturati `nla.game` e
`nla.source_record_type=sealed`; i loro valori sono verificati prima di
certificare la bozza e nella pubblicazione separata. Il riferimento dei nomi
delle carte non viene esteso con prodotti sigillati. Le pubblicazioni pendenti
precedenti mantengono compatibilità con i due nuovi campi nulli; valori diversi
restano soggetti al controllo di integrità.

Verifiche locali: 276 test mirati passati su importazione, candidati,
pubblicazione e regressioni; un ulteriore test di risposta persa durante la
pubblicazione è passato. La revisione indipendente ha verificato le identità,
la classificazione e i casi di ripresa, senza finding gravi residui. Prima della
consegna servono installazione, ciclo reale e verifica dei prodotti pubblicati:
questi test locali non attestano che i sigillati siano già disponibili.

Shopify Admin GraphQL 2026-07: il contratto ufficiale di
[`ProductCreateInput`](https://shopify.dev/docs/api/admin-graphql/2026-07/input-objects/ProductCreateInput)
ammette `productType` e `metafields`; il valore effettivo deve essere verificato
in lettura su Shopify. Il gateway e il tema MAIN non vengono modificati.
