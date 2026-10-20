# WS-10 — Arena neon, 19 ottobre 2026

## Stato corrente — 20 ottobre 2026 (D-028)

Jacopo ha pubblicato il tema Arena il 19 ottobre: MAIN è `210350735628`;
il tema precedente `175195881740` è `UNPUBLISHED` ed è conservato per rollback.
Jacopo ha confermato la visualizzazione corretta in incognito. Questo checkpoint
aggiorna lo stato della pubblicazione; la sezione del 19 ottobre sotto conserva
le prove e i limiti registrati prima della pubblicazione. La presente consegna
GitHub riguarda solo patch sorgente e documentazione; il simbolo originale resta
conservato separatamente. Questa consegna non pubblica o
modifica temi Shopify. Stato registrato secondo la decisione del titolare D-028.

Issue [#14](https://github.com/cajopo/nla-catalog-gateway-staging./issues/14),
con riferimenti #3, #17 e #19 consultati. La preparazione del 19 ottobre era
sul branch `agent/arena-neon-20261019`, base
`9f4e3906f639ef52ce60b4372f0fb1069ec34f56`; a quel checkpoint non risultavano
commit o push dedicati.

## Evidenza pre-pubblicazione — 19 ottobre 2026

Jacopo ha approvato Arena e richiesto lo stile sull'intero sito live. Il
connettore impedisce scritture su MAIN e pubblicazione: è stato aggiornato
soltanto il clone **UNPUBLISHED `210350735628`**. La pubblicazione resta da
eseguire dal titolare in Shopify Admin; questa evidenza non dichiara un rollout live.
Il precedente ID di clone nell'issue #14 è ormai MAIN `175195881740`.

## Modifica e confini

Palette antracite, ciano/blu/viola del logo, neon limitato a bordi e azioni,
tipografia leggibile e adattamento mobile su home, catalogo, prodotto, carrello,
pagine, navigazione, footer, pagina password e template buono regalo. Il logo originale è conservato;
il simbolo fornito dal titolare è usato nell'header mobile e come favicon.

La home usa tre prodotti reali selezionabili nell'editor: Animation Module,
Black Mage's Rod e Diabolic Tutor. Le tre immagini sono decorative, con
dimensioni responsive e fallback ai prodotti delle collezioni configurate.
La PDP conserva `media_size: small` della baseline e sposta la media a sinistra.
Prezzi, disponibilità, identità e contenuti commerciali non sono riscritti.

Due nuovi CSS e un nuovo PNG; dieci file esistenti modificati. Verificati identici
byte per byte i 13 file protetti di catalogo, acquisto, variante, prezzo,
carrello e traduzioni elencati nel controllo privato `build_payload.py`.
Nessuna modifica a gateway, PowerTools, password del negozio o checkout.

## Verifica e revisione

- Validatore Shopify originale, dipendenze esatte `3.24.0`, telemetria disattivata:
  `validation-1.json` PASS per 10 file, con soli due warning preesistenti
  `scheme_classes` nei layout; `validation-2.json` PASS sui sei file rivisti,
  inclusi home e template index/product. `validation-giftcard.json`: controllo
  finale buono regalo e CSS nativo PASS 2/2, con schemi ufficiali inclusi nel
  package dopo fallback DNS; SHA-256 validati coerenti con i file finali.
  Nessuna regola disabilitata per questa modifica e nessun autofix.
- Revisione indipendente del delta Liquid/JSON/CSS: nessun Blocker/Critical/High
  individuato. Un solo spazio finale introdotto nella home è stato rimosso;
  la correzione è priva di effetto sul contenuto e comunicata all'autore per upload.
- `python build_payload.py`: 13 file, 196.078 byte, 13 file protetti invariati.
- `python review-final.py`: 13 hash e dimensioni coerenti; JSON modificati solo
  per presentazione e selezione immagini hero. I 13 file protetti sono invariati;
  script, riferimenti dati del buono regalo, codice e identificatore QR invariati.
- `git -c core.autocrlf=false apply --check --whitespace=error arena-theme.patch`
  PASS su copia privata dei file di baseline. La successiva applicazione ricrea
  esattamente i 12 file testuali preparati. `core.autocrlf=false` evita che la
  configurazione Windows aggiunga CRLF alle risorse durante questa verifica.
- `git diff --check`: PASS nel worktree. Anche `git -c core.autocrlf=false diff
  --no-index --check -- /dev/null <file>` PASS su patch ed evidenza, includendo
  così i nuovi file. I tre artefatti di consegna restano non tracciati.

Ricevuta API privata `final-readback.json`: MAIN invariato, 315 file; clone
318 file, soltanto i 13 cambiamenti previsti; nessun file imprevisto o problema
nel confronto finale, ultimo upload di CSS nativo e buono regalo con
`userErrors: []`. Shopify normalizza la serializzazione
di `settings_data.json`: verifica semantica PASS. La home finale dopo il solo
cleanup whitespace è `3bdb38816497f8165b60c501f7fed64d` (MD5), 22.706 byte,
con lettura del checksum e `userErrors: []` riferiti dall'agente autore.

QA reale riferita dall'agente autore, distinta dalla revisione sorgente:
PDP desktop/390/320 px senza overflow; variante italiana indisponibile con
pulsante disabilitato; variante inglese `54479351546124`, quantità uno a EUR0,99,
aggiunta al carrello nativo inizialmente vuoto e rimossa, con ritorno a vuoto.
Ricerca Magic Lightning Bolt, 24 risultati iniziali e seconda pagina;
filtro FCA1 con reset cursore e persistenza dopo reload; stock-only vuoto coerente;
cambio a Pokémon senza risultati Magic e con facet incompatibili rimossi.
Catalogo desktop 1440/mobile 390 senza overflow. La famiglia sigillato nasconde
i facet delle singole; collezione nativa mobile 390 senza overflow, drawer filtri
leggibile e pulsante Applica funzionante. Home finale desktop 1440/mobile 390:
tre immagini hero caricate, senza overflow. Il reviewer ha ispezionato le due
catture home salvate, senza rilevare clipping evidente; è una prova statica,
distinta dalle interazioni dell'autore. Nessun ordine o pagamento.
Nessun buono regalo emesso è stato aperto, creato o usato: il relativo template
ha verifica sorgente e Liquid, non una prova end-to-end. Non si dichiara
certificazione completa di accessibilità o di tutti i template.

## Consegna e rollback

Consegnati su GitHub soltanto [patch sorgente](../../theme/patches/arena-theme.patch)
e questa evidenza. La patch si applica alla radice del tema esportato.
Serve inoltre il simbolo PNG originale fornito dal titolare, da copiare in
`assets/nla-symbol.png`: il file binario non fa parte di questa repository.
Non è un tema completo: export, payload, manifest, ricevute e immagini QA restano
privati in `C:/Users/umbri/.codex/visualizations/2026/10/19/01a154c0-ddcf-70e1-b9f7-c8df57c74630/arena-rollout`.

SHA-256 patch: `8fe627603dd55e6e3c8491b26dbb2994c0ba72fb3367c22205b4b659dc173880`.
SHA-256 simbolo: `660ccf0022c70894e9a093a7f8fd15546b3c2f563f379c51477d8340497a0546`.

Per ripristinare il clone: rileggere ruolo e checksum, ripristinare i dieci file
esistenti dal backup e rimuovere i tre asset nuovi solo con gli stessi controlli.
Il MAIN non modificato rimane disponibile. Nessuna prova di pubblicazione o di
rollback live è stata eseguita; GitHub/CI e pubblicazione sono stati distinti.

## Correzione della consegna CI — 20 ottobre

Il preflight richiede file UTF-8 e vieta anche gli artefatti codificati.
La prima consegna del PNG binario ha fatto fallire un solo test su entrambe
le versioni Python (4.448 passati, uno fallito); non era un timeout.
Il PNG viene escluso dall'albero tracciato, senza modificare preflight o test.
La copia originale rimane nel PC del titolare:
`C:/Users/umbri/Projects/nla-catalog-gateway-staging/output/arena-neon-worktree/theme/assets/nla-symbol.png`.
Misura 54.114 byte e ha lo SHA-256 del simbolo riportato sopra, verificato
prima della consegna. Non contiene modifiche rispetto all'immagine approvata.

Questa consegna conserva patch e prove; non è un archivio autosufficiente del
tema. Per ricostruirlo occorrono l'export di baseline e il PNG conservati
separatamente. I controlli sul commit finale sono registrati nella PR #117.
