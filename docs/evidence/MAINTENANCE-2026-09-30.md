# Prove della manutenzione operativa NLA — 30 settembre 2026

Workstream documentale #34, roadmap #3; riferimenti operativi #13 e QA #15/#16.
Ramo locale `agent/pm-state-20260930`, base documentale `8301720`.
Queste sono nuove verifiche successive alla fotografia iniziale, non una nuova
release o una modifica di Shopify. GitHub rimane differito.

Aggiornamento successivo: il refresh delle 15 UTC è terminato alle 16:40 UTC.
La [ricevuta di pulizia e retention](RETENTION-2026-09-30.md) registra stato alle
18:22 UTC, cinque artefatti eliminati dopo quarantena/verifiche, 3,65 GB recuperati
e il controllo aggiuntivo ogni 48 ore. Le osservazioni seguenti delle 15–16 UTC
restano evidenza storica del checkpoint copiato sul PC; non sono il pointer live
più recente. Il backup manuale non è stato sovrascritto. Il successivo
[drill Linux](RECOVERY-LINUX-2026-09-30.md) ha restaurato i dati dal PC,
ammesso il gateway isolato e superato le prove HTTP e di carico limitato;
restano i limiti esplicitati per recupero su host nuovo e integrazione Shopify.
La chiusura è stata completata alle 20:55:53 UTC. I due container erano stati
rimossi prima della quarantena dei quattro file grandi temporanei; questi file
sono stati eliminati dopo verifica e dieci POST funzionali live passate.
Readiness e pin sono rimasti invariati. I 2.036.482.048 byte
liberati dal drill non sono un incremento da sommare ai 3,65 GB della pulizia
legacy. Lo spazio libero finale osservato è 11.911.491.584 byte; i database
restaurati non sono più presenti sulla VPS.

## Osservazione del servizio

Accesso SSH esistente con chiave e host key verificata, senza leggere o stampare
segreti. Osservazioni del 30 settembre alle 15:54–15:57 UTC; verifica dei pin
alle 16:15 circa. Versioni: Ubuntu systemd 255.4, Docker Engine 28.1.1,
Python 3.12.3. Il PC usa Python 3.13.0 e Node 22.20.0.

| Controllo | Risultato osservato |
| --- | --- |
| HTTPS `/readyz` | 200, `status=ready` alle 15:56 UTC |
| Runtime | `nla-catalog-staging-private` running, restart `unless-stopped`, store montato read-only |
| Immagine | `sha256:8a23ad0809ed155665decdea9dff875dd198f1fefe2e5764e20798a31a22ece8`, invariata |
| Pin operatore | `881b9ca08dd2bc3ba9875b10d59ccb1a825a9246`, invariato |
| Ultimo refresh completato | `20260930t043743z-3f3fd4f2`, attivato 06:21:57 UTC; sorgente iniziata 04:38:01 UTC; ricevuta `status=ready` |
| Manifest corrente | `a23f6ba25b7e5abe1ecd3c7c51adf14c14535d774f779b2652fefb35d7765399` |
| Manifest precedente | `6b0e3ff3eb99fc58a1bb4a73026eed58fec25daf2a8fafa9d9a32675a6fe2b17` |
| Conte dalla copia verificata | 295.885 prodotti e 297.956 varianti, sia corrente sia precedente; non è un nuovo audit di ogni prodotto |
| Mercato mattutino | 8 candidati selezionati, 8 pubblicazioni, refresh eseguito; `sourceComplete=true`, `remaining=0`, deferred vuoto |
| Mercato pomeridiano | `market-20260930t140006z-1fc43e06`, concluso 14:48:52 UTC; zero candidati, sorgente completa, refresh saltato perché indice fresco e nessuna modifica importer |
| Ledger restaurato | 4.090 righe `draft_attempts` e 4.090 `draft_publications`; conte e integrità, non ricertificazione di ogni identità |
| Timer | Mercato 02/14 UTC, ordinario 03/15 UTC; entrambi attivi; il refresh delle 15 UTC era ancora in corso nell'osservazione |
| Esecuzioni perse durante spegnimento | Entrambi `Persistent=no`: non è configurato il recupero dei trigger persi |
| Alert di errore delle unità NLA | `OnFailure` vuoto su entrambe; nessuna unità NLA di backup/alert tra quelle censite. Non esclude un monitor esterno non documentato |
| Risorse VPS | Circa 6,10 GB decimali liberi e 1.366 MiB di memoria disponibile alle 15:56 UTC, durante refresh; non un nuovo limite di capacità certificato |

La sorgente attiva aveva meno di 12 ore nell'osservazione, entro la tolleranza
di 24 ore del proprietario. Un servizio oneshot `activating/start` non è
automaticamente fallito: occorre attendere la ricevuta terminale del ciclo già
in corso. Non è stato riavviato alcun job, runtime, timer o componente VPS.
Nessun nuovo controllo Shopify, tema o password in questa verifica.

Jacopo ha confermato il PC per la prima copia fuori VPS e indicherà lo spazio
definitivo. Dopo il chiarimento sugli alert ha scelto l'email come canale iniziale.
Indirizzo, referente, servizio di invio e prova di ricezione restano da verificare;
nessun messaggio di prova è stato inviato.

Readiness verificata anche dal PC alle 17:06:23 UTC: HTTPS 200,
`contractVersion=1`, `status=ready`, TLS validato e redirect vietati, 0,187 s.
La prima richiesta nella sandbox ha dato `URLError`; con autorizzazione ai
processi locali e rete la stessa richiesta è riuscita. Entrambi gli esiti sono
conservati; il primo non viene trattato come indisponibilità del servizio.
Per il recapito esterno è preparata nel runbook una proposta UptimeRobot Free:
costi/limiti e flusso ufficiale consultati, nessuna attivazione/account o email
creata. Copre solo raggiungibilità; freschezza e job richiedono controlli propri.

Ricevute e metadati privati sono conservati sotto
`C:\Users\umbri\Projects\nla-catalog-gateway-staging\output\nla-recovery\20260930\`.
Il percorso è escluso da Git e la cartella ha accesso limitato al proprietario
Windows, SYSTEM e Administrators. Non contiene credenziali copiate dalla VPS.

## Prima copia fuori VPS e recupero dei dati

È stata eseguita una copia manuale sul PC del proprietario, con circa 237 GB
liberi prima dell'operazione. Non è stato acquistato o configurato storage cloud.
Il trasferimento comprende pointer, due generazioni immutabili, snapshot SQLite
del ledger e quattro ricevute completate: 12 file più l'indice del checkpoint.

Gli artefatti sono stati aperti e mantenuti per file descriptor prima della
copia, confrontati con dimensioni/hash del manifest; il pointer è rimasto
invariato. Il ledger usa il backup online SQLite ed è internamente consistente;
non viene dichiarata una transazione unica fra ledger e catalogo.
Due subagent `gpt-6-luna` con contesto minimo hanno censito le lacune; il reviewer
operativo ha richiesto correzioni prima dell'esecuzione e non ha lasciato
Blocker/High nella seconda revisione dello stream di backup.

| Artefatto privato | Dimensioni / identità | Esito |
| --- | --- | --- |
| `catalog-ledger-checkpoint.tar.gz` | 222.456.335 byte; SHA256 `620c88e326bf949e345cc7afc49fc922b407ca56d2b10c4cd8ff7f23401ef79d` | Trasferimento 17,822 s; verifica locale di ogni membro prima dell'accettazione |
| `restored-offline/` | Tutti i 12 file confrontati; due DB catalogo da 901.120.000 byte ciascuno e ledger | PASS, estrazione/hash/SQLite `quick_check`/conte in 68,541 s |
| `runtime-ed24a61-image.tar.gz` | 50.355.135 byte; SHA256 `a037376414d31efa4a1bf1ef4c5a8ba9199567990d703fc258d9ba3ae0389265` | Copia 13,94 s; configurazione uguale all'image ID; linux/amd64, tutti gli 11 layer confrontati con i diff ID |
| `family-search-ed24a61.tar` | SHA256 `20fee824f9feb1414ae37aa7c459e4ba50ffa493d1dbb5eab5340cb7ebb932c0` | Copia dei sorgenti installati da Temp; header commit `ed24a61f061c9ea226f3c37f145eb5deb37d4eb8` |
| `refresh-881b9ca.tar` | SHA256 `291d967a77ca1295a385ebc6a72be72d64c721a32f3aac82d95d4d1a3600dcbd` | Uguale al pin configurato sulla VPS; header commit `881b9ca08dd2bc3ba9875b10d59ccb1a825a9246` |
| `reference-config-checkpoint.tar.gz` | 6.474.146 byte; SHA256 `4730b6a9049ba8470c97551e3cae9a3d7e933736381afb861d35d12341cd3e08` | Reference e manifest confrontati con hash/dimensioni configurati; soli percorsi dell'operatore, nessuna credenziale |

La prova dimostra disponibilità fuori host e recupero integro dei dati.
Questa sola verifica dei dati non dimostra riavvio del gateway, recupero delle credenziali,
TLS/DNS/App Proxy, refresh/importer restaurati o disponibilità di una VPS nuova.
Il backup non è automatico; conservazione, cifratura della destinazione definitiva
e controllo di copie successive sono da definire. Il supplemento della reference
contiene manifest di 743 byte con SHA256
`592097c0d4f8ee4a29e0890557ea5874ffcd61931b5e8b71b75005f917b2c718`
e sidecar di 67.367.250 byte con SHA256
`b726989cc231ba52fb30265ba3ddaf83dcef51b7bfea006982ef5fb32f75370f`.
La configurazione esportata ammette soltanto i 13 campi di percorsi/pin censiti;
i percorsi richiedono remapping sul nuovo host. La copia del supplemento è stata
revisionata indipendentemente prima dell'esecuzione. Non è un collaudo del refresh
restaurato. Credenziali e certificati TLS rimangono esclusi.

Docker Desktop 4.88.1 sul PC era spento. L'avvio locale è fallito per
`sailor-ingest.sock` non accessibile; il successivo arresto è riuscito,
il tentativo reversibile di rinominare il socket è fallito senza cambiarlo.
Nessun reset, pulizia dei dati Docker o reinstallazione. Unica distribuzione
WSL censita: `docker-desktop`. Il servizio restaurato richiede ora un ambiente
Linux funzionante separato dal servizio attivo; il successivo drill documentato
usa la stessa VPS con un container isolato e limiti di risorse. I 68,541 s
non sono l'RTO del servizio.

## QA sul sorgente congelato

Anteprima privata tree `2d66cbd609db158450824d2d71347d7e8bda9ddd`,
`tests/theme-browser.mjs` SHA256
`d7e256c470ff97080d7b514d56bf9a01cbeb21031396c0d80ba1c1b134e82aef`.
Comando: `NLA_CHROME="C:\Program Files\Google\Chrome\Application\chrome.exe" node tests/theme-browser.mjs`.
Chrome 154.0.8037.59, Node 22.20.0. Fixture locale, nessun traffico al negozio.

Prima esecuzione limitata dalla sandbox: timeout CDP `Runtime.enable`, prima
dei test. Diagnostica minima con permessi per i processi locali: stessa chiamata
riuscita. Unica successiva esecuzione completa: **21/21 PASS, exit 0**, sorgente
invariato. Entrambi gli esiti e la diagnostica sono conservati, senza nascondere
il primo fallimento.

Copertura: gioco esplicito/SOLD OUT/cursori; Back/Forward/reload e filtri URL;
suggerimenti da tastiera e selezione ARIA; risposte stale, malformate, leakage,
duplicati, restart e loop; XSS e link; vuoto/non configurato; overflow alle
larghezze 320/375/430/1280; identità immagini, concorrenza massima 4, cache,
fallback e race con immagini stale. È una prova del componente su fixture.
Restano flussi mobile Shopify/PDP/carrello, accessibilità completa,
guasto/freschezza E2E e soglie di carico. Non chiude #15/#16.

Prova mirata successiva, senza ripetere la matrice: il 30 settembre alle
21:53:03 UTC, Chrome 154.0.8037.59 e Node 22.20.0 hanno superato sei assertion
sulla stessa fixture congelata (tree `2d66cbd609db158450824d2d71347d7e8bda9ddd`,
componente SHA256 `76dfaa5ac13ae492ef2024f2638d606dd107922656d467f28574693ff1d355de`,
harness SHA256 `d7e256c470ff97080d7b514d56bf9a01cbeb21031396c0d80ba1c1b134e82aef`).
A viewport 390×844, device scale factor 3 e touch emulato: swipe per scorrere,
tap della seconda opzione suggerita, risposta pagina completata, HTTP 503
deliberato della fixture con messaggio indisponibile/Retry, quindi tap su Retry
e recupero fixture HTTP 200. È una prova locale del componente: il 503 è simulato,
non è guasto reale del gateway; non copre Shopify, Safari/iOS né screen reader.
Ricevuta SHA256 `2a2bb839020c43a2ca6fb5bbfeafde10767f201b5077a5a0e3c3f53d6dab03b1`,
runner SHA256 `7f1551839d960d0be5cb671f234095878ebde0df39a30fdbe14673a5542e4148`,
screenshot SHA256 `44c57c0c25753a30ad20113bec4b8d2641fefdf83a50640cfea72be4747be108`;
indice privato `output/nla-recovery/20260930/evidence/qa-touch-down-final/index.json`.
Due tentativi iniziali con `cleanup_incomplete` e le rispettive ricevute di cleanup
sono conservati nello stesso archivio; il run finale attesta processo Chrome
terminato, zero processi col profilo univoco e profilo rimosso. La prova non
certifica il flusso browser→gateway o un'indisponibilità reale.

La stessa matrice di assertion è stata adattata privatamente a Playwright 1.63.0,
con fixture locale e richieste esterne bloccate salvo immagini CDN sostituite
dalla fixture. WebKit 26.6: **21/21 PASS, exit 0**, adapter SHA256
`c8ced5bcc5e79071d21c21af19120d5f3bc1f6d6c277fbe6ce6c336155838d22`.
Firefox 155.0: **21/21 PASS, exit 0** dopo correzione del solo PNG della fixture,
adapter v2 SHA256 `33ee84b26d52bdbc3958b8647997924f9538d1f5da04f1bb3ddb439e76487a58`.
Comando dalla cartella privata: `NLA_ENGINE=webkit node theme-browser-playwright.mjs`
e `NLA_ENGINE=firefox node theme-browser-playwright-v2.mjs`.
Il componente e le assertion non sono stati corretti o indeboliti.
Review indipendente del PM: 49 linee di assertion, 19 chiamate `check` e
29 chiamate `waitFor` identiche fra harness congelato e i due adapter. Sono
conservati il confronto verificato e una nota di rettifica per due metadati
erronei del preflight/resoconto originario, senza alterare log o esiti dei test.

Esiti precedenti Firefox conservati: primo arresto durante navigazione attesa
(driver corretto per attendere solo nei poll read-only dopo distruzione del
contesto), poi 18 controlli passati e timeout sul conteggio delle immagini.
Diagnostica mirata: il PNG originale di 68 byte ha CRC IDAT errato,
SHA256 `d56519cbd3a1f830e3174bf4a0b5ce369f3ef5c389cd3e09b4b367ac5e3dd243`;
Firefox lo decodifica a 0×0. Il PNG conforme di 70 byte, SHA256
`4ff6ab670a58c14270e034e2090d9a432caa263a14e0a25785386b0c12f880b5`,
ha tutti i CRC corretti ed è decodificato a 1×1. Il solo payload è stato sostituito
nell'adapter v2 prima dell'unico run successivo; diff verificato dal PM.
Non è prova di un difetto delle immagini reali del negozio. Chrome e WebKit
restano attestati dalla variante PNG originale, Firefox dalla variante valida.

Limiti dell'adapter: `keyboard.press` include keyup, mentre il driver CDP
originario emette keydown; le prove responsive cambiano larghezza viewport,
senza emulare un dispositivo mobile completo. WebKit non equivale a una prova
del Safari installato su iPhone. Le ricevute browser, entrambi gli adapter,
diagnostici e lockfile sono conservati nella cartella privata `evidence/` del backup;
nessuna dipendenza di QA aggiunta al repository.

Alle 16:24 UTC sono stati aggiunti controlli automatici di accessibilità con
axe-core 4.13.0, installato soltanto in una cartella privata temporanea dopo
consultazione dei documenti Deque. Componente SHA256
`76dfaa5ac13ae492ef2024f2638d606dd107922656d467f28574693ff1d355de`;
`axe.min.js` SHA256 `c24f097bd2f451d4f933e8bc7d8d539f8672a2ebcb5cc9f9f3eec8ca9470a0c1`.
Tag WCAG 2.0/2.1/2.2 A/AA e best-practice, fixture con landmark main e titolo
aggiunti al contenitore: risultati visibili 39 controlli passati, zero violazioni,
zero incompleti; suggerimenti visibili 38 passati, zero violazioni, un controllo
contrasto incompleto su `.nla-catalog__status` per sovrapposizione dello sfondo.
Il controllo incompleto richiede verifica manuale, non equivale a passaggio
né a una violazione dimostrata. È prova automatica del componente su fixture,
non del contesto Shopify completo o di uso con screen reader.
Ricevuta iniziale in
`C:\Users\umbri\AppData\Local\Temp\nla-maintenance-20260930\a11y\qa-a11y-axe-result.json`,
conservata anche in `output/nla-recovery/20260930/evidence/qa-a11y-axe-result.json`.
Runner privato `run-axe-fixture.mjs` conservato nella stessa cartella del backup.

Diagnostico mirato successivo, senza ripetere axe o la matrice: Node 22.20,
`run-status-diagnostic.mjs` SHA256
`cb3e30fa316cb3bfa45c93f5631186bd14beefe41c45fa52a5bd05c26ddd6071`, exit 0.
Rettangoli, hit-test, CSS e screenshot mostrano `.nla-catalog__status` completamente
coperto dal listbox opaco nello stato “suggestions visible” osservato: identici
x/y/larghezza, status alto 24 px e listbox 59 px, sfondo `#15171d`, z-index 80.
Lo status mantiene `aria-live=polite`. Review indipendente: il contrasto di quel
testo non presentato visivamente è non applicabile per il solo stato osservato,
secondo [WCAG 2.2 SC 1.4.3](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html).
Non è un pass misurato del contrasto né una conclusione sul tema installato,
su altri stati/viewport o screen reader. Ricevuta axe originale invariata:
39/38 pass, zero violazioni, un incomplete originario; quello specifico controllo
è ora risolto con evidenza manuale. Nessuna modifica al componente o al MAIN.
Resoconto `qa-status-diagnostic-result.json` e screenshot `suggestions-status.png`
conservati privatamente; la scansione generale e i flussi Shopify restano aperti.

## Documentazione ufficiale applicata

- [OpenSSH](https://man.openbsd.org/ssh): autenticazione esistente e verifica host key.
- [systemctl 255](https://raw.githubusercontent.com/systemd/systemd/v255/man/systemctl.xml) e [timer 255](https://raw.githubusercontent.com/systemd/systemd/v255/man/systemd.timer.xml): proprietà e limiti osservati; i timer non riavviano un servizio già attivo.
- [Docker inspect](https://docs.docker.com/reference/cli/docker/container/inspect/), [save](https://docs.docker.com/reference/cli/docker/image/save/) e [load](https://docs.docker.com/reference/cli/docker/image/load/): pin e archivio dell'immagine; load assente nella prima acquisizione, eseguito nella successiva [prova PC](RECOVERY-PC-2026-10-01.md).
- [Python 3.12 tarfile](https://docs.python.org/3.12/library/tarfile.html) e [SQLite backup](https://docs.python.org/3.12/library/sqlite3.html): streaming, hash e copia del ledger; estrazione filtrata su Python 3.13.
- [Windows icacls](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/icacls): protezione della destinazione locale.
- [Chrome Headless](https://developer.chrome.com/docs/automation-and-testing/headless), [CDP Runtime](https://chromedevtools.github.io/devtools-protocol/tot/Runtime/#method-enable) e [Node 22 WebSocket](https://nodejs.org/download/release/v22.18.0/docs/api/globals.html#websocket): prova browser e diagnostica.
- [CDP touch](https://chromedevtools.github.io/devtools-protocol/tot/Emulation/#method-setTouchEmulationEnabled), [input touch](https://chromedevtools.github.io/devtools-protocol/tot/Input/#method-dispatchTouchEvent) e [chiusura browser](https://chromedevtools.github.io/devtools-protocol/tot/Browser/#method-close): gesti reali nell'emulazione e chiusura della sola sessione locale di prova.
- [Get-CimInstance](https://learn.microsoft.com/en-us/powershell/module/cimcmdlets/get-ciminstance) e [Remove-Item](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.management/remove-item): query dei processi del profilo temporaneo e cancellazione delimitata dopo la loro uscita.
- [Deque axe-core](https://github.com/dequelabs/axe-core) e [API axe](https://github.com/dequelabs/axe-core/blob/develop/doc/API.md): controllo automatico solo degli stati resi visibili; limiti della copertura.
- [Playwright browser](https://playwright.dev/docs/browsers), [API Page](https://playwright.dev/docs/api/class-page) e [PNG W3C](https://www.w3.org/TR/png-3/): adapter isolato e diagnostica della fixture.
- [UptimeRobot Free](https://help.uptimerobot.com/en/articles/11604710-who-should-use-uptimerobot-s-free-plan), [email](https://help.uptimerobot.com/en/articles/11360953-uptimerobot-personal-notification-channels-setup-guide) e [skill ufficiale](https://github.com/uptimerobot/ai/blob/main/skills/quick-monitor-setup/SKILL.md): proposta di monitor esterno; nessuna attivazione.
- [Docker Desktop troubleshooting](https://docs.docker.com/desktop/troubleshoot-and-support/troubleshoot/) e [WSL](https://learn.microsoft.com/en-us/windows/wsl/basic-commands): solo diagnosi locale, senza reset o nuove installazioni.

## Controlli della consegna documentale

Sette documenti attivi, 46 link locali verificati; le tre cronologie rimangono
invariate nei checksum normalizzati per le sole terminazioni di riga. Confronto
con il censimento privato iniziale: 131 file invariati; unico delta in
`src/nla_catalog_gateway.egg-info/PKG-INFO`, metadato generato non tracciato.
Nessun delta nuovo nei sorgenti, AGENTS.md o GraphQL pre-esistenti.
Nessuna nuova modifica al codice applicativo; suite Python/build già eseguite
nella precedente consegna documentale non ripetute senza necessità.

Review indipendente: censimento e script operativi rivisti prima dell'uso;
documenti operativi confrontati con cinque ricevute private dal reviewer;
claims QA confrontati dal subagent QA con le prove effettive. Nessun Blocker/High
residuo nel perimetro rivisto. Questo non è review/approvazione GitHub.
Preflight dell'indice PASS: 125 file, zero findings; `git diff --cached --check`
PASS. Sono stati preparati solo i sette documenti elencati, nessun backup,
database, archivio o modifica pre-esistente nell'indice del commit.
