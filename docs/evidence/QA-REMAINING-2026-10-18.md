# QA riusabile e lacune circoscritte — 18 ottobre 2026

**Esito finale del 18 ottobre:** ricevuta anche la scheda prodotto in vista
stretta. Lo spot-check manuale PDP/carrello è documentato e coerente, con
revisione indipendente; le lacune applicabili della fase sono chiuse con i
limiti di ciascuna prova. Nessuna certificazione dell'intero tema o di un
checkout è dichiarata. Le sezioni cronologiche sotto conservano i passi precedenti.

Le fonti locali non contengono il testo originale dei criteri #15/#16 né una matrice QA autonoma. Il riepilogo chiede una matrice legata alla release, inventario delle celle e prove solo sulle lacune: non trasforma ogni limite documentato in un gate ([stato](STATE-2026-09-30.md#L101-L107), [issue status](STATE-2026-09-30.md#L143)). GitHub resta differito secondo lo stato corrente; questa nota non richiede nuovi consensi.

| Area | Evidenza riutilizzata | Confine della prova |
| --- | --- | --- |
| Browser Shopify | Controlli storici su clone: home, ricerca/suggerimenti, filtri, link PDP; add/remove articolo dal carrello nativo ([ws-10 browser](../workstreams/ws-10-home-browser-20260928.md#L57-L78), [cart](../workstreams/ws-10-home-browser-20260928.md#L97-L116)). | Questi scenari puntuali sono coperti. Non è documentata l’esigenza di rifare una regressione completa. |
| Browser componente | Matrice fixture Chrome/Firefox/WebKit, tastiera, URL, stale/malformed e race; componente MAIN legato alla fixture dopo normalizzazione righe ([manutenzione](MAINTENANCE-2026-09-30.md#L123-L142), [altri browser](MAINTENANCE-2026-09-30.md#L163-L175), [binding](QA-COMPONENT-BINDING-2026-10-18.md#L9-L21)). | Valida il componente sui casi registrati, non tutto il tema o una nuova navigazione Shopify. |
| Mobile | Screenshot homepage mobile e touch emulato della fixture ([ws-10](../workstreams/ws-10-home-browser-20260928.md#L77-L78), [touch fixture](MAINTENANCE-2026-09-30.md#L144-L153)); immagini del proprietario di PDP e carrello stretto descritte sotto. | Spot-check manuale documentato: immagine, prezzo/opzioni coerenti, quantità e controlli presenti; revisione indipendente. Le immagini non registrano click né identificano viewport, browser o revisione immutabile del tema. Nessuna fonte richiede un dispositivo fisico. |
| Accessibilità | Axe sul componente: 39/38 controlli passati, zero violazioni; follow-up documentato sul controllo incompleto ([manutenzione](MAINTENANCE-2026-09-30.md#L196-L224)); componente legato alla fixture ([binding](QA-COMPONENT-BINDING-2026-10-18.md#L9-L14)). | Prova componente riusabile. Accessibilità completa del tema, screen reader e contesto Shopify sono limiti espliciti; i criteri originali locali non dimostrano che siano gate di chiusura. |
| Errori e stale | Fixture copre risposte stale/malformed, 503 simulato e Retry ([manutenzione](MAINTENANCE-2026-09-30.md#L136-L161)); componente attuale legato ([binding](QA-COMPONENT-BINDING-2026-10-18.md#L31-L37)). | Copertura componente valida. La prova non è un guasto reale né un E2E browser→gateway. Le fonti locali non dimostrano un requisito di outage live; nessun guasto va provocato. |
| Carico controllato | 54 richieste HTTPS riuscite, massimo due concorrenti ([prova gateway](PUBLIC-GATEWAY-2026-10-17.md#L1-L6), [limiti](PUBLIC-GATEWAY-2026-10-17.md#L21-L35)). | Prova limitata completata. Nessuna capacità massima o soglia SLA è stabilita qui; nessun benchmark massimo aggiunto. |

## Cella mobile — esito finale

La homepage mobile è stata osservata e l’aggiunta/rimozione dal carrello è stata provata su Shopify in precedenti controlli. Le nuove immagini documentano ora entrambi gli stati PDP/carrello in vista stretta, con dati e quantità coerenti. Si chiude lo spot-check manuale mancante; non si convertono immagini statiche in una registrazione delle interazioni. Le prove storiche restano riutilizzabili per i rispettivi scenari.

Non si richiedono una nuova regressione completa Shopify, una certificazione completa di accessibilità, uno screen-reader audit o guasti live. L'accesso tecnico a Chrome resta indisponibile per QA Shopify: non aggirare il blocco ([stato](../STATUS-CURRENT.md)). Non sono stati eseguiti nuovi test Shopify in questa nota.

Primo tentativo del 18 ottobre (storico, superato dal successivo): Chrome è stato avviato, ma Computer Use ha interrotto l'accesso perché non riusciva a determinare l'URL corrente con sufficiente affidabilità per applicare la policy. Il controllo delle finestre restituiva `Nuova scheda - Google Chrome`. Non era un nuovo rifiuto del proprietario; fu richiesto di aprire manualmente il negozio. Non ripetere tale richiesta: l'esito successivo è descritto sotto.

Tentativo successivo (storico): Jacopo ha selezionato il profilo, aperto il negozio e comunicato «pronto». La finestra aveva titolo `Next Level Arena - Home – NEXT LEVEL ARENA - Google Chrome`, ma la cattura era fermata dallo stesso errore di riconoscimento URL. La selezione del profilo non ha risolto il blocco: non chiedere di ripetere login o apertura del negozio. La ricerca del collegamento Chrome tramite Plugin Management non ha restituito plugin disponibili (`plugins: []`); non equivale a dichiararne l'inesistenza nel catalogo generale. Nessun controllo del sito è stato aggirato. La successiva prova manuale tramite immagini, riportata sotto, ha permesso di chiudere lo spot-check senza ripristinare l'automazione browser.

## Immagini fornite dal proprietario — 18 ottobre

Ricevuti due screenshot: scheda di Abyssal Harvester (V.1), codice visibile
XFDN-316, e carrello con titolo/opzioni corrispondenti (English, Near Mint,
Normal), quantità 1, prezzo unitario e totale di 1.000,00 EUR. Provano la
coerenza visibile dei due stati; non espongono GID Shopify, URL o versione
immutabile del tema e non costituiscono una registrazione dell'interazione.

Le immagini misurano rispettivamente 1089×893 e 1545×821 pixel e mostrano un
layout da desktop; dimensioni del file e viewport CSS non sono equivalenti.
Jacopo ha confermato che la prova è stata eseguita su **PC normale**, senza
emulazione mobile, e che l'articolo di prova è stato rimosso. La rimozione è
attestata dal proprietario, non osservata dall'agente; il browser non è stato
specificato nella risposta. La prova documenta il percorso desktop e lascia
aperta la cella mobile. Nessuna modifica a prodotti, tema o checkout è stata
effettuata dall'agente.

Originali copiati senza alterazioni nell'area privata
`output/nla-owner-qa-20261018-979b5816/`, con provenienza e limiti in `receipt.json`:

- `product.png`, SHA-256 `ca4995c06575170de7135193add5f9f58045fc6de296dc67ec8db96873543f7f`;
- `cart.png`, SHA-256 `fc72c2a71643ca4a33bfb6ab31f79a57c858fdb2bc30961d9a634e08596cf622`.

## Carrello stretto e tipografia provvisoria — aggiornamento del proprietario

Ricevute altre due immagini del carrello dopo le istruzioni per l'emulazione
mobile. Mostrano quantità 1, opzioni e totale coerenti, ma il titolo occupa una
colonna molto stretta e si spezza dentro le parole. Non mostrano scheda prodotto,
barra dispositivo, viewport CSS esatto o interazioni. Non si dichiara quindi
completato il percorso mobile in quel momento. La rimozione era già attestata per la prova desktop;
queste immagini non attestano una nuova rimozione.

**Jacopo ha precisato che font e dimensione del testo non sono definitivi.**
La leggibilità osservata resta un appunto di presentazione: non introduce un
nuovo gate né richiede di finalizzare la grafica per chiudere questa fase.
La scheda prodotto, allora mancante, è stata documentata con le immagini finali sotto.

Prove private: `output/nla-mobile-cart-20261018-cec73467/`, con `receipt.json`:

- `cart-1.png`, SHA-256 `22b7e8f2fe62685472b3e9db45b4c62b92e395bf50fa1bf21b5d972f3dcdc631`;
- `cart-2.png`, SHA-256 `c39c31bd31b21e482f172d4d963fcfa2885b8a40e797ca93165c84e6fd72479f`.

Preparata **solo localmente e come opzione** `mobile-cart.patch`: sotto 750px,
nel solo `#main-cart-items`, dispone il totale sotto i dettagli e i controlli
sulla riga successiva. Nessuna modifica online o ai dati. Sorgente acquisito
in sola lettura da MAIN `175195881740`, negozio `bb5c19-c9.myshopify.com`:
`assets/component-cart-items.css` MD5 `f7e8b9fe8d0207bbc531a2a82671a74a`;
sezione cart MD5 `79764d0d1ee5ebabefc686f950df4d3c`.
Candidate SHA-256 `0c8fb65b5ebbe7ca4fecb58eacbedf467b378fad6a37946418a58a7553984bc9`.
Non applicare direttamente a MAIN: ogni eventuale seguito appartiene al workstream
del clone non pubblicato, con verifica fresca del sorgente e prova sul tema.

`node check-layout.cjs` PASS: 12 casi offline, larghezze 320/360/390/749/750/1280,
due scale font (1 e 1,2), zero richieste esterne. Titolo più largo, nessuna
sovrapposizione o overflow mobile, geometria desktop e controllo fuori scope
invariati. A 360px la colonna dettagli passa da circa 120 a 215px nella fixture.
`layout-check.json` e `fixture-before.png`/`fixture-after.png` conservano i risultati.
È markup rappresentativo con Arial, non il rendering reale del negozio, né un
test delle interazioni o del drawer completo. Revisione CSS indipendente PASS.
Il validator Shopify non è eseguibile: nel pacchetto manca
`@shopify/theme-check-common`; nessun PASS Theme Check dichiarato. La verifica
offline non sostituisce quella della futura grafica definitiva.

## Scheda prodotto stretta — chiusura della lacuna

Jacopo ha fornito le due immagini richieste: immagine e titolo del prodotto,
poi codice XFDN-316, prezzo 1.000,00 EUR, opzioni English / Near Mint / Normal,
quantità 1, dicitura «1 nel carrello» e pulsante «Aggiungi al carrello».
Questi dati coincidono con quelli del carrello stretto già acquisito. Il
controllo indipendente di `/root/mobile_cart_review` conferma la coerenza e la
presenza dei controlli di quantità, aggiunta nella PDP e rimozione nel carrello.
Font e dimensioni provvisori restano esclusi dai requisiti di chiusura (D-026).

Originali copiati byte per byte in `output/nla-mobile-pdp-20261018-09db3e41/`:

- `product-top.png`, 368×792 pixel, SHA-256 `c0d2563790606cbfc245bb0088b4f8835585593841dcc6abad5973bdf4930457`;
- `product-options.png`, 391×808 pixel, SHA-256 `b69c478f3659fac7acce59368fb3cf2232fd8e27c0b50dbecd4ac3a7fbde5a92`;
- `receipt.json`: provenienza, osservazioni, limiti e collegamento al carrello.

Identificazione della prova: immagini del proprietario del 18 ottobre, barra
preview «NLA — catalogo completo test». Questo nome coincide con il MAIN
175195881740 letto separatamente via API, ma le immagini non espongono l'ID o
una revisione immutabile: non attestano l'equivalenza integrale del tema.
Dimensioni PNG e viewport CSS sono distinti; dispositivo e versione browser
non sono identificabili. Non sono registrati click, checkout o una nuova
rimozione; si conservano le prove precedenti di add/remove per il loro ambito.
È una verifica puntuale manuale del layout e della coerenza PDP/carrello,
non una regressione completa del negozio. Nessun tema o prodotto modificato.
