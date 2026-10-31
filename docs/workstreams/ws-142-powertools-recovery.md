# Ripristino PowerTools → Shopify → catalogo NLA

Issue [#142](https://github.com/cajopo/nla-catalog-gateway-staging./issues/142).
Checkpoint: 31 ottobre 2026. Il proprietario richiede diagnosi delle cause,
roadmap e ripristino verificato, proteggendo l'iniezione PowerTools attualmente
bloccata. Questa roadmap non attesta che il collegamento sia riparato.

## Stato e cause

| Problema | Prova attuale | Causa accertata o limite | Intervento e criterio di chiusura |
| --- | --- | --- | --- |
| Articoli PowerTools non aggiornano Shopify | Imperial Iron Wall MAZE e TAMA hanno invii Shopify `Pending` dal 29 ottobre. Due altri invii falliti mostrano soltanto `Errore interno`. | Il blocco è precedente alla proiezione NLA. Il motivo interno del fornitore non è esposto: non sono dimostrati né un conflitto di catalogo né una semplice attesa fisiologica. | Ottenere errore API e contratto di associazione dal fornitore; verificare una transazione conclusa sul GID/variante effettivo e poi il percorso completo. |
| Quantità attesa 1 su Imperial Iron Wall | MAZE è passata da 0 a 1 il 29 ottobre, poi da 1 a 0 il 30 ottobre per Orders Sync/CardTrader. TAMA EX/First Edition ha un invio +2 ancora Pending. | La copia MAZE non è più a 1 in PowerTools. Questo non dimostra che Shopify abbia ricevuto i movimenti: le varianti Shopify campionate risultano ferme a luglio. | Confrontare edizione, lingua, condizione e variante precise, senza usare il solo titolo o aggregare stampe diverse. |
| Presunta perdita del paginatore | Tutti gli 11 prodotti Imperial nella cattura Shopify e nella proiezione hanno le stesse quantità zero; quattro letture Shopify puntuali confermano zero. | Nessuna perdita di quantità dimostrata su questo campione. Non è un collaudo universale di ogni prodotto. | Dopo lo sblocco confrontare una variante realmente positiva alla sorgente, nel dataset e nella UI; includere ritorno a zero e paginazione. |
| Adozione dei prodotti creati da NLA | Campioni Lorcana/Riftbound: identità Cardmarket a livello prodotto, variante Default Title, SKU nullo, zero stock e nessun identificativo PowerTools visibile a livello variante. Il controllo con stock positivo ha identificativi di variante distinti. | L'adozione non è provata. Default Title e SKU nullo sono stati Shopify validi; la loro presenza non prova un errore. Un mapping privato del fornitore non è visibile dalle sole metafield. | Stabilire chi crea/associa le varianti e quali chiavi usa PowerTools; eseguire una verifica controllata attraverso il percorso supportato dal fornitore. Mai sostituire un ID articolo con il Cardmarket ID del prodotto. |
| Vecchio tag blocca prodotti che ricevono stock | Il MAIN acquisito in sola lettura nasconde variant picker e buy buttons sui prodotti `nla_catalog_only`; le card attive e la wishlist li trattano come esauriti. Riproduzione wishlist: stessa variante disponibile a quantità 1 produce un'offerta senza flag e zero offerte con flag. | Causa nel tema accertata. Il tag prevale sullo stato commerciale corrente. I nuovi campioni Lorcana/Riftbound non portano questo tag. | [#143](https://github.com/cajopo/nla-catalog-gateway-staging./issues/143): correzione su clone non pubblicato; test di ricezione parziale stock/prezzo, cambio variante, identità, quantità zero e acquisto rapido. Pubblicazione riservata al proprietario. |
| Indice non immediatamente aggiornato | Runtime privo di configurazione webhook/inbox; nessun worker; API della nostra app non mostra subscription shop-scoped. Il refresh usa timer Bulk. | I componenti receiver/core esistono, ma manca il collegamento operativo completo. Attivare il solo endpoint non applicherebbe gli eventi. | Conservare il refresh read-only e misurare sorgente→attivazione. Dopo un invio PowerTools riuscito, verificare il successivo refresh. Non descrivere il funzionamento programmato come tempo reale. |
| Filtri mancanti per nuovi giochi | Search & Discovery autorizzato e verificato: Edition, Condition e Language; valori vuoti e prodotti esauriti in fondo, non nascosti. | Nessuna esclusione per gioco trovata. I valori dei filtri derivano dalle opzioni realmente presenti nelle varianti, che nei nuovi placeholder non sono ancora popolate. | Non inventare opzioni commerciali. Ricontrollare i filtri sui prodotti dopo l'associazione PowerTools delle varianti. |
| Collezioni ed espansioni | #140 ha verificato tag additivi su 5.612 prodotti, 41 collezioni espansione e 4 famiglie; nuova automazione create-only. Le nuove collezioni restano non pubblicate per decisione del proprietario. | La pubblicazione non è una correzione di sincronizzazione ed è un gate distinto. Into the Inklands ha mostrato un contatore Shopify 238 contro 236 GID effettivi corretti; la causa del contatore non è stabilita. | Conservare regole e membership verificate, non correggere prodotti per far coincidere un contatore. Rieseguire verifica dopo ripresa e lasciare la pubblicazione al proprietario. |
| Identificativi non verificabili R/L | Ricevute del 28–29 ottobre: singole senza ID 17 Lorcana e 108 Riftbound; sigillati senza ID 14 e 31, multi-ID 1 e 12 blueprint (28 ID associati). | Sono conteggi storici, non una nuova scansione live. Mancanza di un ID sorgente o associazioni multiple non autorizza a sceglierne uno per titolo; per i multi-ID resta da provare l'identità della specifica edizione/immagine. Il ledger vigente ha inoltre `UNIQUE(shop, blueprint_id)`. | Conservare quarantena e provenienza, separare token/oversize fuori interesse del proprietario. Dopo prova autorevole di più prodotti per blueprint, serve un adeguamento compatibile dell'identità/idempotenza del ledger in un workstream distinto, senza bypass dei guard. Rieseguire controlli live di assenza prima di creare. |
| Eccezioni sealed nel ciclo del 31 ottobre | Le 258 eccezioni sono tutte booster box Yu-Gi-Oh, con ID già nella reference canonica: `canonical_identity_conflict`. Non sono i mancanti ID R/L. Due campioni sono nella reference ma assenti nella cattura Shopify iniziata alle 04:41 UTC e nell'indice derivato, attivato alle 06:28 UTC. | Il conflitto del riferimento blocca il candidato; non dimostra prodotto già esistente nello store. L'assenza nella cattura non sostituisce una lettura live prima dell'import. | Separato fix dati/importer: distinguere la collisione reale di identità/famiglia dalla presenza nel riferimento storico, con prove autorevoli e test; nessuna creazione durante il blocco PowerTools. |
| Anomalie negli export sorgente | L'ultima cattura conserva 38 `export_game_or_expansion_conflict` in quarantena. | Sono anomalie dei dati sorgente, distinte da ID mancanti/multipli e dalle 258 eccezioni sealed. Non dimostrano 38 SKU mancanti. | Mantenere la quarantena e correggere solo con prova di gioco/espansione e provenienza coerenti; non propagare una classificazione contraddittoria. |

## Protezione di PowerTools già applicata

Alle 12:45:58 UTC il servizio importer era inattivo, MainPID 0 e nessun job.
È stato fermato **solo** `nla-market-catalog.timer`; resta enabled ma inactive.
Non sono stati fermati processi in esecuzione, modificati calendari o disabilitata
PowerTools. Il refresh NLA è rimasto programmato alle 15:00 UTC (16:00 CET),
e `/readyz` ha restituito HTTP 200 prima e dopo.

Questo sospende temporaneamente le nostre nuove creazioni e pubblicazioni,
compresa l'automazione future uscite, per evitare sovrapposizioni durante la
diagnosi. Non basta da solo a sbloccare la coda del fornitore. Dopo un riavvio
host un timer ancora enabled può tornare attivo: verificarlo prima di riprendere
l'indagine; non considerare la sospensione persistente attraverso un reboot.

Ripristino, soltanto dopo verifica di coesistenza:

```sh
systemctl start nla-market-catalog.timer
systemctl show nla-market-catalog.timer -p ActiveState -p NextElapseUSecRealtime
```

La configurazione verificata ha `Persistent=false`, senza recupero automatico
delle scadenze perse. Prima di `start` ricontrollare che non sia cambiata.
Non avviare manualmente un
ciclo, ritentare transazioni PowerTools, cambiare token/scopes, rifare il catalogo
o modificare stock/prezzi/tag/varianti per forzare un esito positivo.

## Ipotesi di interferenza

- **Concorrenza fra creazioni:** possibile per natura del sistema; il nostro
  controllo di assenza e la creazione Shopify non sono una transazione condivisa
  con il fornitore. La sospensione del nostro timer elimina nuove creazioni NLA
  durante questa diagnosi. Zero duplicati nel nostro ledger non prova zero
  duplicati esterni nello store.
- **Budget API ordinario:** Shopify lo separa per coppia app/negozio. Le letture
  della nostra app non consumano direttamente quello dell'app PowerTools.
- **Quota di creazione varianti dello store:** è distinta e può essere condivisa.
  Lettura live: Basic, non Plus, 304.862 varianti (EXACT). Le pagine correnti dei
  limiti indicano soglia 500.000/10.000 al giorno, mentre productCreate 2026-07
  riporta ancora 50.000/1.000. Non attribuire il problema alla quota senza
  l'errore effettivo. Il nostro ledger registra tre creazioni il 31 ottobre;
  questo non misura tutte le creazioni dello store. Il conteggio di varianti
  non documenta filtri: non inventare un conteggio `created_at`.
- **Ownership delle metafield:** `sync` e `powertools` non sono namespace
  app-reserved. La loro creazione da NLA non prova un blocco di ownership.
  Tipo/definizione/scopes effettivamente rifiutati richiedono un errore concreto.
- **Adozione e opzioni:** l'identità prodotto non certifica la variante commerciale.
  La documentazione PowerTools pubblica consultabile non definisce questo
  contratto Shopify; la ricerca `Shopify` nel KB ufficiale restituisce zero
  risultati. Non equivale a dire che la funzione non esista.

## Sequenza operativa e gate

1. **Isolamento e fotografia — NLA, eseguito.** Conservare ricevute timer,
   sorgente/indice, stato transazioni e differenze di variante. Nessun nuovo Bulk
   diagnostico o aumento di polling. Mantenere i normali refresh read-only.
2. **Causa del blocco — PowerTools, aperto.** Richiedere identificativo job,
   operazione/API version, HTTP code, `errors`/`userErrors`, request ID e timestamp;
   motivo della coda Pending; contratto di adozione prodotto/variante e gestione
   del catalogo preesistente. La richiesta è preparata, non inviata. Verificare
   se il fornitore sta elaborando un catalogo iniziale e con quale progresso
   misurabile; non promettere un orario sulla base dello stato Pending.
3. **Correzione tema — NLA, in corso #143.** Usare stock/prezzo/identità effettivi,
   non eliminare tag globalmente. Review indipendente e test sui consumer attivi;
   installazione su clone solo dopo verifica ruolo e diff; rollback dei soli file
   modificati. Non fare ordini reali di prova o pubblicare MAIN.
4. **Verifica di associazione — PowerTools + NLA, dipende da 2.** Scegliere un
   articolo reale già noto al proprietario, fissare ID prodotto/variante,
   lingua/condizione/edizione e sede. Far passare il suo aggiornamento nel percorso
   supportato PowerTools, senza scritture di stock NLA. Provare sia nuovo prodotto
   sia prodotto preesistente, inclusi singole e sigillati dei due nuovi giochi.
   Mantenere campioni di controllo dei quattro giochi esistenti. Confrontare
   transazione conclusa, lettura Shopify fresca e successivo dataset/UI.
5. **Freschezza — NLA, dopo 4.** Il Bulk programmato è l'automazione accettata
   documentata al checkpoint precedente. Misurare il ritardo reale e mostrare
   correttamente l'età del dataset; non chiamare `fresh` una promessa realtime.
   Se il ripristino richiede una latenza minore, il percorso incrementale deve
   includere re-fetch autorevole, inbox durevole, replay/deduplica, attivazione
   atomica persistente e recupero dopo restart: separato workstream sync, testato
   prima di registrare subscription. Accendere solo il receiver non è una fix.
6. **Ripresa nuove uscite — NLA, dipende da 4 e 5.** Verificare assenza di job in
   corso, stato ledger/ricevute e contratto di coesistenza; ripristinare il timer
   senza cambiare la cadenza. Validare un ciclo completo, inclusa riconciliazione
   collezioni per nuova espansione e assenza di duplicati/overwrite. Eventuali
   correzioni massive a prodotti esistenti richiedono un piano distinto e dati
   commerciali autorevoli: non sono autorizzate dal vecchio backfill dei tag.
7. **Accettazione — proprietario.** Pubblicare il tema e le collezioni soltanto
   quando decide il proprietario; verificare dopo pubblicazione il percorso
   effettivamente attivo. Nessuna chiusura dell'integrazione stock sulla base dei
   soli test locali o della presenza di giochi/collezioni.

## Prove e limiti di questa consegna

Le ricevute private sono conservate fuori Git nel worktree operativo, cartelle
`output/components-audit-20261031`, `output/collections-20261031` e
`output/repair-audit-20261031`. Comprendono query validate, dati puntuali, cattura
del tema, screenshot delle transazioni, riproduzione del bug e ricevuta isolamento.
Nessuno snapshot Shopify, database o payload commerciale viene versionato.

Il collegamento PowerTools resta non riparato finché il gate 4 non passa. La
causa degli errori interni resta sconosciuta; non viene attribuita né assolta
l'integrazione NLA per supposizione. Il tema e il ritardo del refresh sono
problemi distinti e non possono spiegare da soli uno stock già zero in Shopify.

Fonti ufficiali consultate:
[PowerTools FAQ](https://tcgpowertools.com/faq),
[PowerTools KB](https://support.tcgpowertools.com/support/kb/categories),
[budget GraphQL](https://shopify.dev/docs/apps/build/apis/graphql-admin/rate-limits),
[limiti risorse](https://shopify.dev/docs/api/usage/limits),
[productCreate 2026-07](https://shopify.dev/docs/api/admin-graphql/2026-07/mutations/productCreate),
[productVariantsCount 2026-07](https://shopify.dev/docs/api/admin-graphql/2026-07/queries/productVariantsCount),
[ownership metafield](https://shopify.dev/docs/apps/build/metafields),
[systemctl](https://www.freedesktop.org/software/systemd/man/latest/systemctl.html).
