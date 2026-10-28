# Continuazione dopo rinvii delle letture identità — issue #133

I primi cicli a sei giochi del 27–28 ottobre 2026 si sono chiusi parziali dopo
148 e 158 creazioni verificate e pubblicate. Entrambi hanno incontrato
`inconsistent_identity_page` durante la scansione Shopify prima di una creazione.
Il primo identificativo rinviato è stato poi creato e pubblicato dal ciclo
successivo, con una nuova baseline completa. Non c'era una scrittura incerta da
ripetere né una prova che l'identità sorgente fosse ambigua.

La modifica riguarda soltanto il coordinatore dell'importatore. Dopo un batch
rinviato con progressi verificati, il coordinatore controlla in sola lettura che
tutto il ledger sia verificato e passa a un nuovo batch con un nuovo export
completo delle identità Shopify. Non esclude l'identificativo rinviato dalla
selezione. Restano invariati il ledger prima delle scritture, i controlli per
prodotto, le tre riletture limitate, il limite di batch, la validità della sorgente
di 24 ore e quella della baseline di 30 minuti. Un rinvio senza progressi chiude
ancora il ciclo parzialmente; una scrittura incerta blocca continuazione e
pubblicazione.

## Contratto delle ricevute

- `deferralHistory` conserva ogni evento, con Cardmarket ID, blueprint ID,
  motivo, numero di batch e operazione di acquisizione identità.
- `deferred` contiene soltanto gli identificativi ancora irrisolti alla chiusura.
- `resolvedDeferrals` indica l'ultimo batch rinviato e la prova successiva:
  `verified_ledger` richiede l'esatta coppia Cardmarket/blueprint e il GID del
  prodotto verificato; `observed_in_fresh_identity_baseline` attesta solo la
  presenza dell'identità in una baseline successiva, non una creazione o
  pubblicazione effettuata dall'importatore.
- `deferralResolutionEvidence` lega la risoluzione al batch finale, alla sua
  operazione, agli hash della ricevuta e del payload delle identità e all'hash
  delle righe verificate del ledger per quel negozio. Quest'ultimo è SHA-256 del
  JSON delle triple `[cardmarket_id, blueprint_id, product_gid]`, ordinate per
  Cardmarket/blueprint, serializzate con separatori `,` e `:` senza spazi.

La risoluzione legge nuovamente la baseline completa con il validatore esistente.
Una coppia discordante nel ledger blocca il ciclo. Il conteggio `remaining` resta
quello conservativo dell'ultimo batch: candidati meno identità già presenti e
tentativi verificati. Non si sottraggono i tentativi cumulativi né i rinvii.
`eligibleExhausted` non può essere vero con rinvii irrisolti, anche se il conteggio
aggregato fosse zero. I batch e le ricevute storiche non vengono riscritti.

Gli errori della sorgente, gli identificativi mancanti o multipli e i prodotti
fuori ambito restano nella contabilità separata del confronto CardTrader. Non
sono rinvii temporanei della lettura Shopify e non diventano candidati approvati.
Il completamento dell'importatore riguarda i candidati verificabili; l'accettazione
di #131 richiede comunque il confronto completo delle righe e le prove del catalogo
popolato.

## Conservazione e limiti

Durante il ciclo la retention conserva il payload completo di ogni batch
`batch_deferred`, insieme alle ricevute. Continua a eliminare soltanto i payload
dei batch completi oltre gli ultimi due, secondo i controlli esistenti. La normale
retention dei vecchi cicli conclusi resta invariata. Prima di ciascun nuovo export
viene ricontrollato il margine esistente di 6 GiB: uno spazio insufficiente ferma
il ciclo con evidenza pendente, senza iniziare un'altra acquisizione.

Ogni nuovo batch consuma il budget configurato, anche quando segue un rinvio.
Non si promette il completamento di un arretrato iniziale in un solo ciclo:
budget, durata e freschezza restano limiti effettivi. Non sono aggiunti timer,
retry di scritture, nuove query o limiti temporali arbitrari nella query Shopify.

## Documentazione consultata e prove

Il client operativo usa Admin GraphQL `2026-07`. Sono state consultate le pagine
ufficiali [products](https://shopify.dev/docs/api/admin-graphql/2026-07/queries/products),
[ProductSortKeys](https://shopify.dev/docs/api/admin-graphql/2026-07/enums/ProductSortKeys)
e [paginazione](https://shopify.dev/docs/api/usage/pagination-graphql), oltre al
[riferimento CardTrader API v2](https://www.cardtrader.com/docs/api/full/reference).
La paginazione con cursori e l'ordinamento `UPDATED_AT` non documentano una
snapshot atomica durante modifiche concorrenti. I controlli conservativi della
scansione rimangono quindi obbligatori.

Le prove mirate coprono una nuova baseline dopo progressi, risoluzione con coppia
esatta o presenza successiva, conservazione dello storico, arresto senza
progressi, budget esaurito, ledger incerto, prove alterate o scadute, zero
aggregato con rinvio irrisolto e conservazione dei payload rinviati. Usano SQLite
reale e il validatore nativo delle ricevute identità; solo la lettura dei permessi
root è sostituita nelle fixture portabili. Le API restano simulate nei test.

Comandi riproducibili: `ruff check .`, `ruff format --check .`,
`pytest --cov=nla_catalog_gateway --cov=scripts --cov-report=term-missing`,
`python scripts/preflight_repo.py` e `python -m build`. Conteggi e risultati finali
sono registrati nella PR di #133; nessuna prova locale equivale a un'applicazione
operativa.

Il rollout usa un nuovo pacchetto importatore immutabile e il relativo SHA
generatore. Pacchetto, archivio, immagine e configurazione del refresh/runtime
rimangono quelli già distribuiti. Il rollback ripristina il precedente operatore
market a servizi inattivi, conservando ledger, prodotti creati, sorgenti e
ricevute; non cancella prodotti né riavvia tentativi incerti. Nessuna modifica a
MAIN, PowerTools, prezzi, stock o prodotti preesistenti.
