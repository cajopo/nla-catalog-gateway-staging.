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

Sul commit integrato, CI `40518014047` e CodeQL `40518013982` sono conclusi
con successo. La prova Python 3.13 registra 4.547 test passati, zero test saltati,
copertura del 100% di 17.053 istruzioni e 5.932 rami; preflight su 282 file senza
rilievi e build del pacchetto riuscita. Anche il job Python 3.12, il controllo
delle dipendenze e quello del container sono verdi.

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
6. Installare la patch soltanto sul clone non pubblicato, controllando file e
   lettura di conferma. Il titolare ha chiesto di poter vedere i nuovi giochi
   nell'anteprima: il caricamento del menu può quindi precedere il deploy del
   gateway. La verifica del menu non attesta il funzionamento dei nuovi cataloghi:
   pagine vuote e contratti richiedono il controllo HTTP della nuova versione;
   catalogo e interfaccia con dati reali richiedono una verifica separata al termine
   del primo ciclo. Pubblicazione MAIN e rimozione password restano escluse.

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

Alle 14:44:46 UTC è partita la sola preparazione dell'immagine, nel servizio
transitorio `nla-multigame-prepare-8b23217.service`. Il preflight remoto è passato.
Il builder dedicato ha limiti di 1.536 MiB e 0,5 CPU; non monta dati gestiti.
L'helper revisionato ha SHA-256
`027d6d4d442565f6a72ca8331545f03f4d4e848467d7976a13a9222cf046a8e7`;
21 test mirati e Ruff sono passati, con revisione indipendente. Pacchetto,
immagine e ricevute di preparazione sono distinti dall'installazione del runtime.
Alle 14:45:46 UTC la ricevuta `prepared_not_activated` e il servizio terminato
con codice zero attestano la build e lo smoke test con UID 10001. L'immagine è
`sha256:bc6bb454242a3c8c3cf8fff3eae91bb66a8417045a2d72877b0949c151d744f0`;
il builder è fermo e lo smoke container rimosso. Nessun servizio esistente o
dato gestito è stato modificato. Restano separate le verifiche sulle generazioni
conservate e l'installazione.
Il servizio transitorio terminato è stato poi chiuso, conservando la ricevuta di
preparazione con SHA-256
`41c445b66e919113a7d86536720b28e386c74ba9b38f425abb22830d2fb1b638`.

La manutenzione separata ha concluso market e refresh alle 15:21 UTC. Il refresh
ordinario successivo, `20261027t152125z-0a8afd71`, si è invece fermato prima del
download; alle 15:29 il servizio era `failed`, con marker pendente e catalogo
precedente sano. L'installazione è rimasta ferma al proprio controllo preliminare.
L'ispezione dei due export tramite la stessa applicazione ha confermato stato
`COMPLETED`, nessun errore o risultato parziale, identità/query valide e conteggi
invariati (296.712 prodotti, 298.783 varianti). La directory contiene soltanto
checkpoint e lock: nessun download o attivazione. Il log generico non permette
di attribuire una causa precisa. Le prove di quel tentativo restano conservate;
non va dichiarato un refresh riuscito né rilanciato senza ispezione.

Alla ripresa delle 17:24 UTC questi pin erano ancora invariati. La chiusura
circoscritta del tentativo, revisionata indipendentemente e verificata con 14 test
mirati, è poi riuscita con stato `stopped_inspected_before_download`. Il marker è
archiviato insieme alla ricevuta, mentre checkpoint e directory del tentativo
rimangono intatti. Nessun nuovo export, refresh, modifica Shopify o cambio timer.
La ricevuta `closure.json` ha SHA-256
`420127d220d1bdbd2056e0ab7ff1ab53ecd53ea5dd8ac12390183458abbedce4`;
l'helper eseguito ha SHA-256
`46244c6caa9436edec832f38e6e3d03ca308fa242cffb81d49c626db84d0d467`.
Il servizio è ora inattivo, ma systemd conserva `ExecMainStatus=1` dell'invocazione
ispezionata: questo valore storico non viene falsificato come successo del refresh.

Alle 14:13 UTC è stata verificata la duplicazione del tema: clone
`210427412748`, nome `NLA Arena — Riftbound e Lorcana`, ruolo `UNPUBLISHED`,
elaborazione conclusa senza errori. Tutti i 328 file hanno checksum e dimensione
identici alla sorgente MAIN `210373968140`, rimasta invariata. Dopo un nuovo
controllo di ruolo e inventario, i nove file revisionati sono stati caricati sul
solo clone: nove accettati, nessun errore, lettura di conferma su 329 file, 320
originali invariati e nove corpi corrispondenti ai payload. Per i due JSON di
traduzione Shopify ha aggiunto il consueto commento iniziale. MAIN conserva tutti
i 328 file e lo stesso `updatedAt` delle 12:15:10 UTC. Le cinque operazioni GraphQL
sono state validate sulla versione 2026-07; il connettore non espone la propria
versione API effettiva.

Il link di anteprima condiviso dal titolare ha consentito una verifica reale in
Chrome, senza risposte simulate: HTTP 200 e tema `210427412748`, ruolo unpublished.
Desktop 1280 px e mobile 375 px mostrano i sei giochi, i selettori ricerca/wishlist
e le quattro voci di ciascun nuovo menu. Alle 17:26:54 UTC i link Singole
conservavano gioco e famiglia e generavano POST reali a `/apps/nla-catalog` con
contratto versione 2. Il backend ancora precedente rispondeva HTTP 400 e la UI
mostrava catalogo temporaneamente indisponibile: la prova del menu è passata,
quella dei cataloghi reali non è ancora passata.
La ricevuta finale UI ha SHA-256
`8edfbe2c1c781924439c4624d2101b33ee82d123302eca3e0a5d8d1e9a67ebc7`;
la lettura di conferma dell'installazione ha SHA-256
`83cada9192a89c8cbd79340b0aaa12e1957c3b5be1551e0378e7abd5288e90b5`.
Anche lo scorrimento del menu mobile fino ad Accessori è stato verificato, senza
overflow orizzontale e con la voce raggiungibile sopra la barra di anteprima.

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
