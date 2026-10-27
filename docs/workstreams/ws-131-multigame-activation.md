# Attivazione Riftbound e Disney Lorcana — issue #131

Il titolare ha richiesto l'integrazione completa dei due giochi e ha confermato
il 27 ottobre 2026 che entrambi sono abilitati in TCG PowerTools. Non occorre
modificarne la configurazione. La pubblicazione del tema MAIN resta riservata
al titolare, come stabilito da `AGENTS.md`.

## Sorgente consegnata

Le tre PR, sottoposte a revisione indipendente e controlli verdi sui rispettivi
commit, sono state unite senza riscrivere la loro storia:

| Ambito | PR | Commit revisionato |
| --- | --- | --- |
| Contratti e catalogo | #128 | `e997a70a4da3ed4eb8dd0f3eef64d399e81c7118` |
| Acquisizione e importazione | #130 | `68c31c6fd7f8ebb4f99c475c182bc9d97f7182fd` |
| Navigazione e wishlist | #129 | `cd5f4a07e5d4f5054c921c40de1cedbf724c85fc` |

Main risultante: `8b23217f23d7c4f15cf032c6d4f8f3826b56fc5e`, tree
`45d8970f7936bdf60eb3c9ef2d4835f3587e1d71`, uguale alla precedente simulazione
dell'unione. L'archivio prodotto con `git archive --format=tar` ha SHA-256
`c793c6bff5033f0b166108981bb0f347e485472951572cc5f9b881baf06194be`.
Archivio, fonti commerciali, diagnostica e configurazioni private restano fuori Git.

## Controllo iniziale del 27 ottobre

Alle 14:07 UTC il runtime rispondeva 200 a `/readyz`, con immagine
`sha256:2231c268945bf3681c83b2f0fafa9ae71a0751e46972c963c205463fc2b24a22`.
Puntatore, ambiente accettato e ricevuta del runtime erano coerenti. La
generazione e il riferimento canonico erano ancora a quattro giochi.

Il ciclo market `market-20261027t123631z-2f60a224`, avviato dalla manutenzione
separata, era attivo e stava eseguendo il refresh
`20261027t134217z-72d4146f`. Entrambi i marker pendenti erano attesi per un
processo in corso: non sono un'autorizzazione a rimuoverli o riavviare il lavoro.
Il timer refresh era fermo per l'esclusione già prevista dal servizio market.
Nessun ciclo è stato interrotto per questa integrazione.

Il ledger letto in sola lettura conteneva 4.917 creazioni verificate e altrettante
pubblicazioni, nessuna operazione incerta; `quick_check` era `ok`. Lo spazio
libero era circa 10,8 GB. Sono osservazioni iniziali, da ricontrollare al momento
dell'installazione, non pin riutilizzabili dopo la conclusione del ciclo.

## Sequenza operativa e confini

1. Preparare un nuovo pacchetto immutabile dall'archivio revisionato e una sua
   immagine compatibile. Il validatore dell'operatore verifica anche l'archivio
   originale e il suo commit: non applicare patch arbitrarie al vecchio pacchetto.
2. Attendere che manutenzione, market, refresh e backup siano terminati.
   Controllare servizi, processi figli, ricevute, marker e lock; fermare soltanto
   i timer necessari all'installazione, conservandone lo stato iniziale.
3. Usare la sostituzione del runtime già revisionata, mantenendo la generazione,
   l'ambiente e il runtime precedente durante la verifica della nuova immagine.
   La ricevuta di sostituzione non equivale al completamento dell'installazione.
4. Allineare i riferimenti di operatore, archivio, immagine e servizi. Verificare
   anche i pin del checkpoint di backup, così che il nuovo runtime e il nuovo
   pacchetto restino recuperabili. Conservare una ricevuta separata e i file
   precedenti. Archiviare il marker pendente sotto lo stesso lock, dopo la
   ricevuta di installazione; ripristinare i timer solo a installazione attestata.
5. Abilitare esplicitamente `--game-scope six-games` e usare il ciclo esistente:
   acquisizione completa, identità Shopify fresche, creazioni limitate dal ledger,
   pubblicazione dei soli prodotti del ledger ancora idonei e refresh del catalogo.
   Non rilabelare come sei giochi una vecchia acquisizione a quattro giochi.
6. Verificare catalogo e interfaccia con i dati reali di entrambi i giochi.
   Installare il tema soltanto sul clone non pubblicato, dopo controllo dei file
   e lettura di conferma. Pubblicazione MAIN e rimozione password restano escluse.

Le fonti osservate comprendono 3.831 righe di categorie singole Lorcana e 1.896
Riftbound. Questi numeri non sono conteggi di prodotti approvati: 286 righe non
hanno Cardmarket ID e tre righe appartengono a giochi estranei. Le eccezioni
devono restare rendicontate. I sigillati provengono dai prodotti Shopify;
l'importatore autorizzato crea solo stampe di carte verificate.

Il ripristino di un vecchio binario richiede prima una generazione e un
riferimento canonico compatibili a quattro giochi. Non cancellare prodotti
creati, modificare dati commerciali esistenti o ripubblicare prodotti passati a
PowerTools per ottenere un rollback.

## Stato delle prove

Alle 14:13 UTC è stata verificata la duplicazione del tema: clone
`210427412748`, nome `NLA Arena — Riftbound e Lorcana`, ruolo `UNPUBLISHED`,
elaborazione conclusa senza errori. Tutti i 328 file hanno checksum e dimensione
identici alla sorgente MAIN `210373968140`, rimasta invariata. La patch non è
ancora caricata; i nove file revisionati sono preparati privatamente. Le cinque
operazioni GraphQL previste sono state validate sulla versione 2026-07; il
connettore non espone la propria versione API effettiva.

Revisione indipendente del documento: commit, unioni, archivio, diagnostiche e
ricevuta del clone verificati; nessun rilievo bloccante. La revisione del documento
non sostituisce quella degli helper eseguibili né le verifiche dopo il deploy.

Questo documento registra preparazione e controlli iniziali. Non attesta ancora
un deploy del gateway, un ciclo a sei giochi completato o la pubblicazione del tema.

Riferimenti operativi: [sostituzione immagine](ws-09-code-only-replacement.md),
[importatore](ws-multigame-import.md), [tema](ws-10-multigame-20261027.md).
Contratti ufficiali consultati: [merge GitHub](https://docs.github.com/en/rest/pulls/pulls#merge-a-pull-request),
[duplicazione tema Shopify 2026-07](https://shopify.dev/docs/api/admin-graphql/2026-07/mutations/themeDuplicate),
[scrittura file tema Shopify 2026-07](https://shopify.dev/docs/api/admin-graphql/2026-07/mutations/themeFilesUpsert).
