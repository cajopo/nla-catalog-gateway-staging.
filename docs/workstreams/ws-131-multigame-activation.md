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
quella dei cataloghi reali allora non era ancora passata.
La ricevuta finale UI ha SHA-256
`8edfbe2c1c781924439c4624d2101b33ee82d123302eca3e0a5d8d1e9a67ebc7`;
la lettura di conferma dell'installazione ha SHA-256
`83cada9192a89c8cbd79340b0aaa12e1957c3b5be1551e0378e7abd5288e90b5`.
Anche lo scorrimento del menu mobile fino ad Accessori è stato verificato, senza
overflow orizzontale e con la voce raggiungibile sopra la barra di anteprima.

Revisione indipendente del documento: commit, unioni, archivio, diagnostiche e
ricevuta del clone verificati; nessun rilievo bloccante. La revisione del documento
non sostituisce quella degli helper eseguibili né le verifiche dopo il deploy.

## Compatibilità e recupero dell'installazione

Il controllo delle due generazioni conservate, eseguito in sequenza con la nuova
immagine e accesso ai dati in sola lettura, è concluso con
`retained_generations_compatible`: 296.712 prodotti nella generazione attuale e
296.583 nella precedente. Entrambi i vincoli con il runtime sono validi; i
container di verifica sono stati rimossi. La ricevuta del tentativo
`20261027t174741z-c464d3fd` ha SHA-256
`c90cc2d78c3e5adb7c77d59d937cbf35a504213c5081f508abc55b344915e785`.

Alle 18:06 UTC l'installazione si è fermata dopo la creazione del candidato,
prima del suo avvio. Il runtime precedente è rimasto sano, con risposta 200;
i tre timer operativi sono rimasti fermi secondo il percorso di errore previsto.
La ricevuta originale `stopped.json`, conservata senza riscritture, ha SHA-256
`24d8f2dcb8cced07473ae9ac9b1b13d2a80b43a186060fcd3734b86eeeb5730d`.
La diagnostica in sola lettura ha individuato un confronto troppo restrittivo
delle variabili predefinite delle immagini Python: la nuova aggiunge `LANG` e
cambia `PYTHON_VERSION` e `PYTHON_SHA256`. Entrambi i container contengono
esattamente le variabili della propria immagine e lo stesso ambiente operativo
accettato, senza modifiche a credenziali o configurazione applicativa.

Il recupero circoscritto riutilizza esclusivamente il candidato mai avviato;
verifica identità, immagini, configurazione, sicurezza, ricevute e stato originale
prima di acquisire i lock e avviarlo. Non ricrea container, non ricostruisce
immagini e non ripete l'installazione fallita. L'helper ha SHA-256
`581795c8f878e9d29d49f6da6fc52f4abb7aa54eb238593e114e723d035c03e4`;
63 test mirati, Ruff e formattazione sono passati, con revisione indipendente
senza rilievi. Anche il launcher a dispatch unica è revisionato: SHA-256
`eae1643cf7e1e0b9aff0cb35fe3ef14ba56442ad2ce67f12f131b4ab9590975b`,
16 test passati. Dopo il preflight remoto in sola lettura, alle 18:25:54 UTC
è stata effettuata una sola dispatch del recupero, invocazione systemd
`bfa60121ea2b448ab8cf0b72d49e29f2`. La dispatch non attesta il deploy:
l'applicazione e le verifiche successive richiedono le proprie ricevute.

Alle 18:35 UTC il recupero è concluso con
`recovered_installed_timers_restored`: nuovo runtime disponibile con HTTP 200,
vecchio runtime conservato e fermo, tre timer ripristinati, marker pendente
archiviato. Generazione, puntatore e ambiente accettato sono invariati. La ricevuta
di installazione ha SHA-256
`d2a33eb0aa3b962d9a3538cf76745411bce3c2a86cdd636d889263d790a65e03`,
quella finale del recupero
`dfe3988319ee01482feed382d988179d4d45cc9a8e077bd867cab075c265bb64`.
Il controllo successivo conferma immagine attesa, nessun riavvio o OOM e HTTP 200
anche sull'endpoint pubblico. La precedente ricevuta di errore resta conservata
come prova storica. Il dataset servito è ancora quello dei quattro giochi:
installazione del software e completamento del primo ciclo sono prove distinte.

Alle 18:40 UTC il controllo HTTP dopo l'installazione è passato: 39 richieste,
stato invariato, regressione sui quattro giochi esistenti e risposte valide per
entrambi i nuovi giochi e tutte le famiglie. I due nuovi cataloghi sono ancora
vuoti, come nella proiezione indipendente; questa prova verifica i contratti,
non il popolamento. Ricevuta `http-code-only.json` SHA-256
`ea92064665154e76625d952da3e5cfb25a7556c9cd93b5263e6a515a0ff30c8f`.

Il preflight dei servizi è stato corretto per leggere l'identità systemd effettiva:
il refresh usa l'utente root predefinito, rappresentato da `User=` vuoto,
mentre gli altri servizi dichiarano root esplicitamente. Il gate verifica ora
utente, gruppo e `DynamicUser=no` esatti per ciascun servizio, con lettura
esplicita del gestore di sistema. Sono passati 90 controlli offline e il preflight
reale, con revisione indipendente. Non sono stati modificati i servizi per
adattarli al verificatore.

Alle 18:40:39 UTC è partito un solo backup, invocazione
`04ca66a70d104ada8aae13c25fe1c100`. Il suo osservatore si è fermato subito dopo
la dispatch perché usava un lettore riservato a directory root per il puntatore
del catalogo, la cui proprietà UID 10001 è corretta. Il backup stesso è poi
terminato alle 18:42:18 UTC con `complete`, integrità `read-data/passed` e nessun
job conservato. La ricevuta coincide con `last-success.json`, SHA-256
`f8e1f3d7af34360ebce576eb08454994d67f0745426b6d15655b6eb284536992`;
lo stato dell'installazione è ancora identico all'intento iniziale. Il backup
non viene rilanciato. Restava la verifica separata della copia remota, mantenendo
la ricevuta di arresto originale dell'osservatore.

La successiva diagnosi ha confermato i dodici controlli strutturali del manifesto
e gli hash delle prime tredici voci dell'inventario. Il verificatore si fermava
sulla voce successiva, gestita da Caddy con UID 10002, perché imponeva anche lì
la proprietà root. L'ispezione separata ha confermato percorso e proprietario
attesi: era un rifiuto del verificatore, senza uno scarto degli hash già
controllati, e non un errore dello snapshot. La correzione mantiene i vincoli
specifici di ciascun percorso; non cambia proprietari o contenuti del backup.

Alle 19:08:13 UTC la verifica finale è conclusa con
`postinstall_http_backup_verified`, sullo stesso backup e con una sola dispatch.
Il manifesto del checkpoint, le immagini e i riferimenti del catalogo risultano
legati allo snapshot
`028030d5659dea04c50936e5d7e4be77444edab55e30f303139ea5fc0eb3584c`.
La ricevuta finale ha SHA-256
`dc178195e06c23a8da46c7bbb136014526946a9c3ae9a542887c71a345e30adb`,
il legame verificato con il manifesto
`f4f1b2f83475eb734d220272300358d89dd8b915eb4149d6152189744b2562c7`.
La ricevuta originale di arresto resta conservata. Non è stato avviato un
secondo backup per superare il rifiuto del verificatore.

Alle 18:43:59 UTC è conclusa anche la verifica reale del clone dopo il deploy:
20 casi di base (due nuovi giochi, quattro famiglie, desktop/mobile, più i quattro
giochi esistenti) e sei prove aggiuntive di filtri, paginazione e cambio gioco.
Tutte le 26 richieste effettive al proxy Shopify hanno restituito HTTP 200:
19 con contratto 2 e sette con contratto 1, senza errori JavaScript o test saltati.
La generazione è rimasta
`sha256:dd6b999dfc75270917ef0cfebbad3cf3ae353a71ecaeaac50b6f28ec274e65d7`.
La ricevuta aggregata ha SHA-256
`f696fc19ffa4fa296931ce4e70ed147134d73982784e7bd0268fa0c195a8280e`;
collega tre ricevute, 38 screenshot e l'harness. Due arresti del solo harness
durante la navigazione sono stati riprodotti e corretti; le prove già complete
sono state riutilizzate soltanto dopo confronto degli hash e della generazione.
I nuovi giochi mostrano lo stato vuoto previsto, mentre i controlli dei giochi
esistenti restituiscono prodotti. MAIN e clone non sono stati modificati durante
questa verifica. Resta distinta la successiva accettazione dei cataloghi popolati.

## Avvio del primo ciclo a sei giochi

La catena di verifica del backup, avvio unico e supervisione è stata sottoposta
a 135 test mirati e 40 sottocasi, con Ruff, formattazione e revisione indipendente
passati. Il launcher eseguito ha SHA-256
`a634bf574dd6085a85d9fb37f05d19e2b7d6219979b07d3f15948275a85dea07`;
il supervisore
`a34a7f211db74ccfe5dd6712d7e5a281eb4c69c07263193a94487408239ceb26`.
Il preflight reale ha verificato il backup finale e il ledger con 4.917 creazioni
e altrettante pubblicazioni verificate prima di avviare nuovi lavori.

Alle 19:08:35 UTC è partito il ciclo
`market-20261027t190835z-3e6d72d1`, invocazione
`5e5bb9ec057d48b7b1c45cabb85d4fc2`, con una sola dispatch del servizio market
e una del supervisore. Il piano del ciclo ha SHA-256
`5641cc758ccd4110cd0b48fd612f42f63c8e27d92cc699d56979864d707148d3`.
La dispatch attesta l'avvio, non il completamento dell'acquisizione,
dell'importazione o dell'accettazione.

La lettura delle 19:09:37 UTC conferma lo stesso run e invocazione, marker
pendente coerente e stabile durante l'osservazione, servizio market in esecuzione
(`activating/start`) e supervisore `active/running`. L'acquisizione dichiara
esplicitamente `six-games`: 48 espansioni completate su 2.493, 6.832 blueprint,
zero retry e nessuna espansione rinviata a quel momento. Non sono ancora presenti
ricevute terminali, di pubblicazione o di catalogo popolato; nessuna ricevuta di
arresto è presente per questo run. È un checkpoint della fase iniziale, non una
stima dei tempi residui. L'osservazione conservata ha SHA-256
`5a6dcd66d9a8db1c3f42b7abf7656f2e4450b0f30df095a92cb8da61f1a60d63`.
Il lettore restituisce soltanto stati e aggregati, con otto test locali e revisione
indipendente passati. Le prove UI restano quelle dello stato vuoto delle 18:43 UTC:
HTTP e interfaccia con dati popolati richiedono l'esito del primo ciclo.

## Esito dei cicli e diagnosi del 28 ottobre

Il primo ciclo è terminato alle 22:04:14 UTC del 27 ottobre con
`draft_cycle_partial`: 148 carte create, verificate e pubblicate, 5.293 candidate
rimanenti. Il secondo batch si è fermato prima della creazione di CM729357,
blueprint259051, perché tre scansioni di identità Shopify non hanno superato il
controllo `inconsistent_identity_page`. La ricevuta terminale ha SHA-256
`5a9744be3079958d8f11817905331536d372e6d9be2a0ff5f5d25a6001ab532a`.
Il supervisore ha correttamente rifiutato l'accettazione; la sua ricevuta di arresto
resta conservata e non è stato avviato un backup di accettazione.

Il ciclo `market-20261028t020006z-784ef4ce` è partito alle 02:00:06 UTC.
Questo ciclo è terminato alle 04:47:31 con lo stesso motivo, dopo altre 158
creazioni e pubblicazioni verificate e con 5.481 candidate rimanenti. La ricevuta
ha SHA-256 `50400a8359a3dc5ae766e3406a384407ad5d25e847bdc6a1c81e9fb04815fd8a`.
Il nuovo rinvio riguarda CM745061, blueprint268282, senza alcuna prenotazione
nel ledger. CM729357 è invece stata creata e pubblicata dopo una baseline nuova:
il rinvio precedente non dimostrava un'identità ambigua della carta.

L'ispezione delle 08:57 UTC conferma 5.223 creazioni verificate e altrettante
pubblicazioni, senza scritture incerte e senza ciclo market pendente. La proiezione delle
09:05 UTC contiene 306 singole Lorcana pubbliche, tutte esaurite; Riftbound è ancora
assente. Generazione `sha256:fd3d512650ee0da28e012dcbe73493726c6c0388696fb5b9125eae1adf4fdda3`,
manifesto `a048452f3c1ff006c24ed7cf8103e14fee68f7e772e782366f318e7984548228`.
La riconciliazione in sola lettura contabilizza tutte le 264.238 righe sorgente,
incluse 38 anomalie: le identità assenti dalla proiezione sono 3.356 Lorcana,
1.780 Riftbound e 345 Yu-Gi-Oh!. I record senza ID verificabile, le categorie
non carta e quelle non classificate restano esplicitamente distinti.

La correzione [#133](https://github.com/cajopo/nla-catalog-gateway-staging./issues/133),
[PR #134](https://github.com/cajopo/nla-catalog-gateway-staging./pull/134), è stata
unita nel commit `f2c22ae28c10572ee8a7995463d485805f267624`. Prosegue con una
baseline completa nuova dopo progressi verificati, conserva i rinvii e le loro
risoluzioni e si ferma senza progressi o con scritture incerte. I controlli di
identità restano invariati. La revisione indipendente è positiva; CI sullo head
`2b2214c6787067ce116f20f25f9adfd253519cf0`: 4.569 test passati, zero saltati e
copertura statement/branch 100% sia su Python 3.12 sia su 3.13. Ruff, preflight,
build, container, dipendenze e CodeQL sono verdi. Su 3.13 resta un ResourceWarning
del test preesistente `test_metadata_facet_counts`, senza test falliti.

L'archivio dell'importatore ha SHA-256
`eaacbb01364f7f42c7a421512fcc71d74aac1c74a1979804718dbcad7424041a` e contiene
284 file. Il coordinatore archiviato ha SHA-256
`72d3d39db900e6abe1799ca8c84d234de2f558beefe40d9bc9ce28f98b458394`:
28.070 byte con 623 terminatori CRLF. Il blob Git, normalizzato a LF, ha invece
SHA-256 `7dd2b0d9c24c5f718ee9ad03109226ef4bacb4bb054713c2ef1b0db08f20a34f`.
Il controllo finale deve usare i byte effettivi dell'archivio verificato.
Il pacchetto runtime/refresh resta sul commit `8b23217f23d7c4f15cf032c6d4f8f3826b56fc5e`.
Il budget dell'importatore passa da 60 a 100 batch, entro il massimo già
validato, mantenendo 100 tentativi per batch: le 5.481 candidate osservate e i
batch rinviati devono poter essere trattati nello stesso ciclo.

Il primo tentativo di installazione ha scritto esclusivamente la nuova unità
market e il relativo inventario del backup, poi si è fermato su
`unrelated_unit_changed`. La diagnosi in sola lettura conferma che
`daemon-reload` ha azzerato soltanto i campi storici di esecuzione di `ExecStart`
nei servizi refresh/backup. I loro file, comandi, invocazioni e gli altri campi
sono invariati; dataset, runtime, riferimento e ledger sono identici al preflight.
L'unità market ha l'hash previsto
`5e29b271aa506377b8bf2d1b72c10b5e671e750b99ab68baab69666698171c47`,
la configurazione backup
`a7aa6c0e3cdf09cb73caadc0b4a57393b16adca4fc2c95eff3721738a4603a22`.
Nessun servizio è stato avviato. L'intento e la ricevuta di arresto restano
conservati; l'installazione non è stata ripetuta. La finalizzazione separata,
helper SHA-256 `bc40aa695b310fb7fbd5213b9d89b331204c39401c441f4aa5ff5c25ac322e0d`,
ha superato 21 test e due revisioni indipendenti. Ha accettato soltanto
l'azzeramento dei campi storici osservato, mantenendo comandi, argomenti,
invocazioni, altri campi e hash esatti, con un nuovo controllo sotto i tre lock.
Il preflight reale e l'unica applicazione sono riusciti: tutte e tre le
pianificazioni sono di nuovo attive, nessun servizio è stato avviato dalla
finalizzazione e nessun file di configurazione è stato riscritto.
La ricevuta di installazione completata ha SHA-256
`65dba7b99fcace3555cf26d5e7a21c57d688adede9afb82abcf2ffa928f38f4c`;
le ricevute originali di intento e arresto sono rimaste identiche.

Il backup precedente alla ripresa è stato avviato una sola volta alle 09:59:30
UTC, invocazione `b09dac6dcc8b498a89c1572968735254`. La verifica separata della
copia remota conferma `read-data/passed`, inventario, immagini, generazione e
riferimento esatti. Ricevuta backup SHA-256
`352b8892cc21065c184f14181da36449df3011d796e966b7359789367fc676b3`, snapshot
`9143ed90dff4cf8882241b155b4f1b639e34fbeea4044af8e89e75e69e52d246`, manifesto
`75c1f51aec92ca8987298b6ce91583d28ef64e9a156c8261613908931ca0fc64`.
La ricevuta della verifica separata ha SHA-256
`08d44a746da7b0dc189fe20fc636824ac25b6b0cc313e78625cad3c31eff9a4f`.

Alle 10:02:51 UTC è stato avviato una sola volta il ciclo
`market-20261028t100251z-527602c9`, invocazione
`286804351c5a47939d2641d62e09c88e`, con il nuovo importatore. La ricevuta di avvio
ha SHA-256 `6d9849cf2766afdbc088abc3134b2b30a10d556726a573b8a9765f938360bb1f`.
L'operatore prosegue fino all'esito del ciclo, alla riconciliazione e alle prove
HTTP/UI con dati popolati; questa ricevuta attesta soltanto la dispatch.

L'audit indipendente delle categorie nei 46 export conservati del ciclo delle
02:00 non ha trovato categorie di singole escluse per errore. Le 229 righe Lorcana
con categoria non mappata dall'importatore sono 211 accessori e 18 Complete Sets;
le 127 Riftbound sono 125 accessori e due Complete Sets. Singles, Oversized e
Token sono tutte mappate. I 169 record Lorcana e 116 Riftbound senza Cardmarket ID
restano distinti; non si tenta di ricavarne l'identità dal titolo. Nessuna API o
mutazione è stata necessaria per questo audit. Sigillati e accessori restano
navigabili quando presenti in Shopify, secondo l'ambito approvato in #123.

L'audit dei consumer ha trovato un'omissione nel footer del clone, che leggeva
direttamente il menu globale a quattro giochi. La correzione separata #135,
PR #136, commit di merge `8a9ed264100c7e53048a0cc15848fd061809b8c2`, aggiunge
soltanto i due link mancanti, localizzati e senza duplicati, preservando menu
globale, stile e contenuto promozionale. Revisione indipendente, 21 prove Liquid,
quattro prove Chrome desktop/mobile e tutti i cinque controlli CI sono passati
sullo head `5cb22c72f2e73d8317e20773251e8b6eac6af93d`. Entrambe le versioni
Python hanno completato 4.569 test senza skip e con copertura 100%.

Alle 10:28 UTC sono stati installati nel solo clone i due payload del footer.
Il controllo precedente alla scrittura, la rilettura dei payload e il confronto
completo degli inventari sono riusciti: clone UNPUBLISHED con 330 file, di cui
328 invariati; MAIN ancora identico con 328 file e lo stesso `updatedAt`.
L'anteprima reale ha restituito HTTP 200 e ha superato entrambe le prove a 375 e
1280 pixel: nove link visibili, destinazioni e focus corretti, nessun overflow o
errore JavaScript. Nessuna richiesta catalogo o mutazione carrello in questa prova.
Ricevuta aggregata SHA-256
`67a8aacefd86620958e04558ee539e7038a405a794163e8e88b8f4f852b09878`, ricevuta UI
`392b8b4fcc53ef64e2984a6b69b4db3f313baea34b33cb6e9d3ef0c5fd8ef5c8`.
Queste prove del footer non sostituiscono l'accettazione del catalogo popolato.

## Spazio disponibile per completare il ciclo

Il 28 ottobre alle 13:12 UTC è stata completata una sola archiviazione reversibile
di 11 payload storici, dopo inventario, hash integrali e controllo dei riferimenti
attivi. Sono stati liberati 6.181.117.952 byte netti; la lettura indipendente delle
13:13 UTC rileva 17.501.163.520 byte disponibili. Le sei prove native conservano
gli hash originali. Tre database temporanei incompleti sono preservati come
evidenza incompleta, senza attribuire loro validità o correggerne i contenuti.

Ogni gzip è stato verificato mediante decompressione integrale, dimensione e
SHA-256 prima di rimuovere il relativo originale; intenzioni e ricevute sono
persistite prima della rimozione. Il controllo successivo ha verificato tutti gli
11 hash dei gzip e l'assenza di riferimenti attivi, senza una nuova decompressione.
Nessuna modifica a servizi, timer, catalogo attuale, Shopify o PowerTools. Gli
archivi sono locali: non è attestata una loro copia offsite. Prima di riusare i
vecchi consumer occorre il ripristino esplicito del singolo payload, verificato
e senza sovrascrivere destinazioni esistenti; inode e ctime saranno nuovi.

| Prova privata conservata | SHA-256 |
| --- | --- |
| Piano dei soli payload storici | `adcf873edbf1b9b7db00435e3192d2dc05d2cc33f99d1c4c8f217b84be71e529` |
| Ricevuta dell'unica archiviazione | `eeb01c8a8c148ef701cfd9466397663427655dfbd4917be1383c87c27fc76c98` |
| Controllo successivo in sola lettura | `d2e161167fa81d8dd2cf108abcb03ebc7f1090df127d54f929b2e896cf662aa4` |
| Chiusura e calcolo della capacità | `32579bbca9efcf4ee0a6747093ae8e9a0ec81ad87d619214c371d515f5c49387` |

Le revisioni indipendenti sono positive: 39 test di inventario/archiviazione,
23 di trasporto e nove del controllo successivo passati, con Ruff verde. Lo
scenario conservativo fino a 100 batch conserva spazio per il picco di refresh
osservato; eventuali backup successivi richiedono spazio e retention effettivi.
Questa operazione non costituisce accettazione del catalogo.

## Progresso del ciclo e verifiche

Il 28 ottobre alle 19:44 UTC il ledger contiene 10.704 prodotti verificati,
di cui 5.481 creati nel ciclo corrente. La pubblicazione è in corso; la ricevuta
privata dell'osservazione ha SHA-256
`110ed154427b03e636ec66df1761bd24953c07ceabd607d64ff540422a843a3c`.
La creazione completata non attesta ancora il catalogo pubblicato o il refresh.

Alle 22:20 UTC la pubblicazione risulta completata: 5.481 pubblicati e zero
rimanenti. Il refresh del catalogo è in corso. La ricevuta privata
dell'osservazione ha SHA-256
`4d139211653cdb93d63404391e0d65cde2bda4d8e31b03e5a46954c6addaddc2`.

Per anticipare il collaudo senza attendere un eventuale refresh successivo,
i verificatori possono operare sulla generazione già attiva durante quel refresh,
controllando identità del ciclo, ledger e invariabilità della generazione. La
modalità ordinaria resta invariata; 178 test mirati sono passati anche nella
revisione indipendente. La ricevuta privata di preparazione ha SHA-256
`b0f9357aa1962e4c584894c8fd8ae0aa86d045d7494b95614aa9cfac1635c9c0`.
## Esito del ciclo e collaudo del catalogo

Il ciclo `market-20261028t100251z-527602c9` è terminato: 5.481 prodotti
creati e pubblicati, 10.704 verificati nel ledger, nessun prodotto idoneo
rimanente e refresh dell'indice completato. I rinvii del ciclo sono stati
risolti. Il controllo indipendente dei dati e quello HTTP sono passati sulla
stessa generazione `sha256:a43adeed9fdc827cd72eda34850f26b9d30714511093a57d2141844f237ebb08`.
Il secondo comprende 151 richieste, paginazione completa dei nuovi giochi,
ricerca, filtri e verifiche campionate dei giochi precedenti. Anche il collaudo
del clone con catalogo popolato è passato: 26 casi desktop e mobile.

Nel catalogo pubblico risultano 3.662 singole Lorcana e 1.780 Riftbound,
tutte esaurite; per entrambi i giochi non risultano sigillati o accessori
pubblici. Le rispettive categorie sono supportate, ma questo non attesta la
disponibilità di prodotti. Alcuni record della fonte non hanno un identificativo
Cardmarket verificabile e rimangono esclusi, senza identità o prezzi inventati.
La fonte contiene inoltre 159 sigillati Lorcana e 84 Riftbound: l'importer
installato era limitato alle carte singole e non li ha creati. Il 29 ottobre il
proprietario ha autorizzato l'estensione ai sigillati, con le stesse verifiche
e pubblicazione a stock zero. I record senza ID
Cardmarket sono 169 Lorcana e 116 Riftbound, comprese categorie diverse dalle
stampe ordinarie, come Oversized e Token; richiedono associazioni verificabili
prima di un eventuale import.

Un inventario in sola lettura dei 243 sigillati rileva 185 record con un solo
ID Cardmarket, 45 senza ID e 13 con più ID; la presenza non ne verifica
l'identità commerciale. La verifica usa un export Shopify
del 28 ottobre e non sostituisce il confronto aggiornato necessario prima di
qualsiasi creazione; non attesta prezzi o disponibilità commerciale.

Il 29 ottobre alle 00:32 UTC una lettura in sola lettura ha confermato attivi
i timer: import alle 02:00 e 14:00 UTC, refresh alle 03:00 e 15:00 UTC.
L'import successivo resta soggetto agli stessi controlli di identità e ambito.

| Prova privata | SHA-256 |
| --- | --- |
| Accettazione dati | `f2f3ef7b3359283601bab29ff69ad90e6f3f840351bd9f546eb0d53fe36ceda0` |
| Accettazione HTTP | `84dd02eb5f665c994e76ca78fa09dbbb1b81bccd4561b4a9eda7c204e615026b` |
| Collaudo clone popolato | `4f1c3012cd2c62467966d2e281f7932f41773838b7b6bcdcbcc8f49dd214bc1a` |
| Wishlist e pagine prodotto dopo correzione | `cf4a2c990333dd05c28a3568bc217ea4de3e8124d4d1e4de4f28ac1d54174cdd` |
| Stato timer in sola lettura | `90d4e05a8936273b8365291d574def36ec34691ce22da80267bd082cc9d08163` |
| Inventario sigillati in sola lettura | `426893ad75472c64bf8a1b0fc9c7e52eb6092de33fb2e4fae97923486f440727` |

Il tema resta sul clone non pubblicato; il passaggio del negozio al tema è
riservato al proprietario secondo il gate di cutover. La pagina prodotto del
clone è stata corretta caricando un asset già presente, dopo che il collaudo
aveva rilevato `DetailsDisclosure is not defined`. Il nuovo collaudo wishlist e
pagine prodotto è passato su quattro casi e la stessa generazione, senza errori
runtime o mutazioni. Il layout corretto ha superato la validazione Liquid
stateless, con un warning preesistente; asset e ordine sono stati verificati
separatamente. Sono passati anche test mirati e verifica browser reale.

Riferimenti operativi: [sostituzione immagine](ws-09-code-only-replacement.md),
[importatore](ws-multigame-import.md), [tema](ws-10-multigame-20261027.md).
Contratti ufficiali consultati: [merge GitHub](https://docs.github.com/en/rest/pulls/pulls#merge-a-pull-request),
[duplicazione tema Shopify 2026-07](https://shopify.dev/docs/api/admin-graphql/2026-07/mutations/themeDuplicate),
[scrittura file tema Shopify 2026-07](https://shopify.dev/docs/api/admin-graphql/2026-07/mutations/themeFilesUpsert),
[variabili delle immagini Docker](https://docs.docker.com/reference/dockerfile/#env),
[ambiente del container Docker](https://docs.docker.com/reference/cli/docker/container/run/#env).
