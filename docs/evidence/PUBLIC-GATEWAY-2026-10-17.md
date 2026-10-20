# Gateway pubblico HTTPS — prova limitata del 17 ottobre 2026

Esito PASS, osservazione iniziata alle **10:06:29 UTC**: 54 richieste HTTP 200,
50 risposte catalogo con contratto verificato e invarianti finali immutati.
Esecuzione dalla VPS verso `https://catalog-staging.nextlevelarena.it`, attraverso
DNS, TLS e Caddy pubblico. Nessun servizio avviato, riavviato o modificato;
nessun refresh, export Shopify, modifica al tema o operazione repository/CI.
La consegna GitHub resta differita secondo D-024; questa evidenza è locale.

## Copertura effettiva

| Prova | Esito |
| --- | --- |
| `/readyz` e `/opsz`, prima e dopo | 4 richieste GET, tutte 200 |
| Paginazione `single` su Pokémon, Magic, Yu-Gi-Oh! e One Piece | 8 richieste: prima/seconda pagina da 5, ID unici e disgiunti, ordinamento numerico, gioco/famiglia e richiesta restituita coerenti |
| Ricerca Pokémon Pikachu e Charizard con suggerimenti | 2 richieste, risultati e suggerimenti presenti |
| Letture ripetute | 40 prime pagine da 20 prodotti, 20 coppie, massimo 2 richieste contemporanee e inizi delle coppie distanti almeno un secondo |
| Generazione | Identica in tutte le 50 risposte catalogo |
| Controlli finali | Stessi container, immagine, avvio, restart/OOM, pointer, Caddyfile, ricevuta backup e marcatori di esecuzione delle pipeline |

Sulle sole 40 letture ripetute: minimo **70,045 ms**, massimo **133,966 ms**,
P95 **131,128 ms**, con nearest rank `ceil(0,95 × 40)`. I tempi includono
preparazione TLS, DNS, connessione e lettura HTTP dal nodo stesso. Non sono
una misura della latenza di un visitatore esterno, uno stress test o uno SLA.

La prova attraversa il gateway pubblico direttamente con richieste firmate
generate in memoria sulla VPS. Non attraversa l'inoltro Shopify né il tema:
restano da verificare i flussi reali browser/mobile/accessibilità, gli stati
down/stale e il recapito degli alert. La capacità massima non è stata misurata.
Le prove precedenti sulla fixture e sul restore isolato restano distinte.

## Versione e stato osservati

| Binding | Valore |
| --- | --- |
| Container | `c04241301513f0bcac5d154d04129769c1c61e3652bdb69727435c18ad2b6470` |
| Immagine | `sha256:8a23ad0809ed155665decdea9dff875dd198f1fefe2e5764e20798a31a22ece8` |
| Avvio container | `2026-10-17T05:57:52.080690628Z`, running, restart 0, OOM false |
| Dataset nelle risposte | `sha256:d9cf6e3cb3979eed1e12d6fc7d4cf4633ed2f7a03e9627f22e12c2670d730c30` |
| SHA256 pointer | `43476f7e8babe20362039ac21c56ebc6793c606eea9133326f1877fc7b30fd5a` |
| Manifest corrente / precedente | `3fbd719c115e3754c71ecb0e74e63054fb4ea92cdb5854750f6c6477569b95cd` / `5b22aed799704902be7d2bcb2ea2e82565621c7142e7a8d31448753a0e809add` |
| SHA256 Caddyfile | `ef4c3fa2e611798e6d42f50962b1b9ddfb9ef27ea5d7494ea406b3a499dd73b9` |
| SHA256 ultima ricevuta backup | `ce6018583f3d7369d36f97d9a09bf453748a60f8575f4ed8fad49ebad148b4e6` |

Gli hash dei manifest sono distinti dall'identità del dataset nelle risposte;
non è stata presunta la loro uguaglianza. Market, refresh e backup erano
`inactive/dead`, risultato `success`, senza PID/job pendenti. I timer erano
enabled/active/waiting: market alle 14 UTC, refresh alle 15 UTC del 17 ottobre,
backup alle 01 UTC del 18 ottobre. Questa verifica non prova ancora il primo
ciclo automatico del backup.

Spazio libero prima/dopo: 13.243.920.384 / **13.243.912.192 byte**.
Memoria disponibile prima/dopo: 3.370.479.616 / 3.368.923.136 byte.
La piccola variazione disco osservata non viene attribuita a questa sonda.

## Metodo, revisione e riproducibilità

Helper privato scritto da `/root/public_gateway_probe_author`, revisionato
indipendentemente da `/root`; controller revisionato dall'autore dell'helper.
17 test offline, Ruff check e format PASS. Nessuna modifica al sorgente del
gateway installato. Secret e firme restano in memoria VPS; ricevute senza
URL firmate, credenziali, cursori, prodotti o corpi HTTP.

Ammissione: pin fissi, pipeline inattive, timer distanti almeno 10 minuti,
memoria disponibile almeno 512 MiB e disco libero almeno 6 GiB. Nessun lock
che possa ritardare una pipeline. Ricontrollo ogni cinque coppie e a fine prova.
TLS con CA/hostname verificati; proxy ambientali e redirect disabilitati,
override ambientali delle CA rifiutati. Massimo 54 richieste, risposta 2 MiB,
timeout socket 5 secondi; al primo errore o risposta oltre 3 secondi si fermano
le nuove richieste. Il supervisore limita l'intera prova a 180 secondi e può
terminare soltanto il proprio gruppo di processi. Un timeout non attesta
gli invarianti finali.

Il primo tentativo delle 10:04 UTC si è fermato in ammissione, con **zero HTTP**:
il checker richiedeva timestamp non vuoti anche all'unità backup mai eseguita.
La diagnosi mirata ha confermato proprietà presenti ma vuote; i backup manuali
provati sono distinti dall'unità schedulata. Corretto solo quel caso, aggiunti
test di regressione e nuova revisione prima dell'esecuzione riuscita. Le prove
iniziali sono preservate; nessuna soglia operativa è stata abbassata.

Ricevute private, escluse da Git:

- Risultato PASS: `output/nla-public-gateway-20261017T100627Z-0c101feb3f5f4024af7e31f648725bc0/public-gateway.result.json`, SHA256 `7c601027c53cb6b1ea94937a959ec9b33ddab0d20c9bf917e0a1af36f3f9a1b9`.
- Helper finale: `output/nla-public-gateway-check-remote.py`, SHA256 `e8b84b0d057c30fcb45a601ef31cb587e58c3ba2341ca07c1db86c149e1eddc2`.
- Test: `output/test_nla_public_gateway_check_remote.py`, SHA256 `3a6d4494e7f866b290b6ee3a771d215f0435e7aac34a95a0311eaa8ee5961705`.
- Review finale: `output/nla-public-gateway-root-review-v2.json`; contratto privato: `output/nla-public-gateway-check-contract.md`.
- Prima ammissione respinta: `output/nla-public-gateway-20261017T100404Z-9ac7d54f3e8942f89925c58be95270d6/`.
- Diagnosi unità: `output/nla-public-unit-diagnostic-20261017T100442Z-e5224bc6c59b43a3af478719df3b4313/unit-shape.result.json`, SHA256 `42bca27c23ecbfed2d04db35369599a4cfcb87f4d7971eeb0daa5fcfc289fee7`.

Non ripetere la prova senza una modifica, un errore o una nuova lacuna che lo
giustifichi. I pin sono specifici dello stato osservato; non aggiornarli
automaticamente per superare un rifiuto. Un job in corso sospende l'ammissione
e non costituisce di per sé un guasto.
