# Altre stampe di questa carta — nota di contesto

## Stato e perimetro

Idea discussa con Jacopo; è autorizzata questa documentazione, non l'implementazione.
La fattibilità è preliminare: identità delle carte, dati disponibili e soluzione UI
devono ancora essere verificati. Non modifica la priorità dell'importazione completa.

## Richiesta dell'utente

Nella scheda di un prodotto, per esempio Lightning Bolt, aggiungere un menu
«Altre stampe di questa carta» che permetta di aprire direttamente la distinta
scheda Shopify di un'altra stampa della stessa carta. Al passaggio del puntatore
su una voce deve essere disponibile un'anteprima dell'immagine.

## Proposta minima da confermare

- Menu personalizzato con espansione e numero carta, quando verificati nei dati.
- Anteprima al passaggio del mouse e comportamento equivalente al focus da tastiera.
- Su mobile: tocco per l'anteprima e comando esplicito per aprire la scheda.
  Questo dettaglio d'interazione è una proposta, non una scelta già approvata.
- Prezzo mostrato solo se disponibile; nessuna etichetta «Prezzo n/d».
- Carte senza disponibilità incluse, con **SOLD OUT** in rosso brillante,
  identico in tutte le lingue.
- Immagine assente o non caricabile: resta utilizzabile il collegamento testuale.

## Identità e confini

Il gruppo deve contenere soltanto stampe della stessa carta e dello stesso gioco.
Serve verificare una relazione canonica affidabile nei dati: la semplice somiglianza
o inclusione di una parola nel titolo non basta a stabilire l'identità.
Conservare i GID Shopify e gli identificativi PowerTools verificati.

Shopify resta autorevole per schede prodotto, prezzi, disponibilità e acquisto.
La funzione non modifica prodotti, varianti, prezzi, stock o sincronizzazione
PowerTools. Eventuale lavoro sul tema è limitato al clone non pubblicato;
nessuna modifica o pubblicazione del tema MAIN.

## Possibile riuso, senza presupporre funzionalità esistenti

Valutare il riuso del gateway read-only e del tema clone, senza una nuova app a
pagamento nell'approccio proposto. Non è ancora verificato che un endpoint attuale
fornisca il raggruppamento esatto: prima controllare identità, campi e copertura.
Non sono fissati tempi, costi o garanzie di fattibilità definitiva.

Il menu deve rendere raggiungibile l'intero gruppo, anche se numeroso: eventuale
paginazione o caricamento progressivo non deve troncare alle prime 24 stampe
né reintrodurre un limite di navigazione a 25.000 elementi.

## Verifiche minime prima dell'accettazione

- Gruppo esatto: stesso gioco e stessa carta; esclusione dei nomi solo simili.
- Navigazione verso il prodotto Shopify corretto tramite identità verificata.
- Inclusione delle stampe SOLD OUT e assenza di prezzi inventati o segnaposto.
- Gruppo completo su più pagine, senza buchi o duplicati.
- Menu e anteprima utilizzabili con tastiera e dispositivo mobile.
- Immagini mancanti, errori di rete e caricamenti tardivi gestiti senza
  mostrare l'anteprima di una voce diversa da quella selezionata.

Prossimo passo, solo dopo autorizzazione all'implementazione: verificare i dati
di identità e proporre il più piccolo intervento necessario nel clone.
