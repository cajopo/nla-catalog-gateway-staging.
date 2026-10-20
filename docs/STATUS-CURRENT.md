# Stato attuale del progetto NLA

Fotografia operativa aggiornata al 20 ottobre 2026. PM della fase: Codex,
incaricato da Jacopo. Riferimenti: roadmap [#3](https://github.com/cajopo/nla-catalog-gateway-staging./issues/3),
architettura #17, tassonomia #19 e manutenzione documentale #34.

**Fase di manutenzione completata il 18 ottobre 2026 (100% dell'obiettivo
autorizzato).** Garanzie operative e recupero verificati; ricevute anche le
immagini della scheda prodotto mobile, che completano lo spot-check manuale
PDP/carrello. La consegna GitHub è stata riattivata il 20 ottobre, separatamente
dalla chiusura operativa ([D-030](DECISIONS.md#d-030--completare-la-consegna-github-nella-repository-pubblica)).
[Verifica dei cinque requisiti e limiti](evidence/MAINTENANCE-CLOSURE-2026-10-18.md).

## Sito e priorità prima del lancio — 20 ottobre 2026

Arena è pubblicato dal 19 ottobre: MAIN `210350735628`, precedente
`175195881740` non pubblicato e conservato per rollback. Logo attuale mantenuto,
stile Arena e accenti neon applicati; Jacopo ha confermato la visualizzazione
corretta in incognito. La tipografia provvisoria del 18 ottobre è uno stato
storico. Il negozio resta protetto da password.
[Pubblicazione e prove](DECISIONS.md#d-028--stile-arena-pubblicato).

Jacopo ha chiarito il 20 ottobre che prima del lancio pubblico vuole modifiche
alla home, nuove funzionalità e nuove sezioni del sito non dedicate alla vendita.
Sono tre workstream ancora da dettagliare, senza funzionalità, sezioni o scadenze
già decise. Il lancio viene dopo il loro completamento e una decisione separata
sulla password; Fase 2 chiusa e manutenzione ordinaria restano distinte.
[Ordine di lavoro](ROADMAP-EXECUTION.md#ordine-di-lavoro-proposto) ·
[Decisione](DECISIONS.md#d-029--home-funzionalità-e-sezioni-prima-del-lancio).

## Ricerca codici installata — 19 ottobre 2026

**Aggiornamento del 20 ottobre, 08:28 UTC:** il primo ciclo market successivo
è completo e il refresh ordinario è terminato alle 06:07 UTC. Il manifest
attivo corrisponde alla ricevuta; sorgente di circa quattro ore. La precedente
segnalazione `market_incomplete` è superata: l'espansione rinviata il 19 ottobre
aveva restituito HTTP 404 dalla fonte. `/readyz` è 200; `/opsz` resta 503, ora
per `backup_attention`. Non dichiarare tutto UP. La diagnosi del 19 ottobre
riportata sotto resta una prova storica.
Alle 08:30 UTC è confermato il backup automatico odierno fallito
(`checkpoint_failed`); ultimo backup completo il 19 ottobre alle 01:01 UTC.
La causa interna del checkpoint resta da diagnosticare e correggere.
[Verifica corrente](evidence/OPERATIONAL-CHECK-2026-10-20.md).

Su richiesta esplicita di Jacopo, installata la correzione locale `2c8c650`
(`agent/card-code-search-115`): `FIN88` e `FIN-88` restituiscono la stessa carta,
con suggerimenti e faccette coerenti. La stampa è esaurita e rimane esclusa
con il filtro disponibili. Copertura aggregata Windows/Linux 100% su istruzioni
e rami; 4.122 test Windows e 35 test nativi Linux passati, review indipendente.

Immagine effettiva `sha256:2231c268945bf3681c83b2f0fafa9ae71a0751e46972c963c205463fc2b24a22`,
costruita sull'immagine `8a23ad08`/runtime `ed24a61` con soli quattro moduli aggiornati.
Container `b89865e8...`, installazione registrata alle 21:05:56 UTC,
prova finale alle 21:10:40 UTC. Fonte dati, pointer e ambiente accettato invariati;
operatore/archive `881b9ca`, patch importer `8657aaa`, unità, Caddy, backup e monitor
preservati. Modificato soltanto `image` nella configurazione del refresh futuro.
Timer market 02/14 UTC e refresh 03/15 UTC attivi; nessun marker pendente.
Al checkpoint del 19 ottobre il primo ciclo pianificato successivo non era
ancora osservato; l'aggiornamento sopra registra la verifica del 20 ottobre.

**Attenzione operativa preesistente:** `/readyz` 200, `/opsz` GET/HEAD 503.
Il collector segnalava `market_incomplete` già prima del deploy (20:00 e
20:52:13 UTC). Ricevuta immutabile `draft_cycle_partial` del ciclo
`market-20261019t140017z-be2a057f`, SHA256 `5fb4de9672fcc50d5194db59214ff5458985479d6764bc6631d8aae0ebc72096`.
Non è un guasto introdotto dalla ricerca; non dichiarare il monitor UP.
Esito market e monitor non sono stati modificati né è stato forzato un ciclo.
Al checkpoint del 19 ottobre il problema market restava manutenzione separata.

Ricevute VPS: `/opt/nla-staging/search-code-2c8c650/rollout/` e
`/var/lib/nla-catalog-refresh/20261019t205146z-48551a72/`.
[Metodo, prove, limiti e rollback](workstreams/ws-05-code-hyphen-search.md).
Prove private PC nel worktree `C:\Users\umbri\.codex\worktrees\0072\nla-catalog-gateway-staging\output\card-code-search-20261019`.
Al checkpoint del 19 ottobre non erano stati eseguiti push, PR o workflow GitHub.
La consegna successiva è integrata tramite #116 il 20 ottobre, secondo D-030.
Non rieseguire i due helper di installazione/finalizzazione una tantum.

## Stato operativo

- Il catalogo live resta operativo e in sola lettura verso Shopify. Shopify è
  autoritativo per prodotti, varianti, prezzi, inventario, pagine, carrello e ordini.
- L'ultimo controllo completo della retention del 17 ottobre alle 11:42:43 UTC conferma
  market e refresh inattivi con esito success, timer attivi, ricevuta
  e stato corrente coerenti, zero directory residue previste dalla retention e
  solo due generazioni protette. Spazio libero VPS: 13.246.488.576 byte.
  [Ricevuta retention](../output/nla-recovery/20260930/evidence/retention-periodic-20261017T114241Z-1b73631c/retention_periodic_check_remote.result.json)
- Il primo backup automatico è riuscito il 18 ottobre, dalle 01:00:12 alle
  01:01:33 UTC: circa 81 secondi, integrità `read-data` PASS. Il manifest remoto
  dello snapshot `9fc4fe1…` include l'observer `319ca0b` con i pin attesi. Le copie
  cloud sono protette; la rotazione automatica resta opzionale e inattiva.
  [Primo backup automatico](evidence/BACKUP-SCHEDULED-2026-10-18.md)
- Drill applicativo isolato chiuso: `current` PASS (04:42:55.573467–05:02:30.871598 UTC,
  1.175,298131 s, 10 richieste) e `previous` PASS (05:03:13.812059–05:22:46.065102 UTC,
  1.172,253043 s, 10 richieste). Entrambi chiusi 45m29s dopo il download; la pulizia
  è esclusa da tale durata. Alle 05:26:27.145572 UTC sono stati rimossi 765 file e
  104 directory (3.931.679.750 byte, solo percorsi restored/catalog); ricevuta
  `deletion_complete` e journal `Deactivated successfully`. Spazio libero:
  13.750.943.744 byte. Evidenze conservate. Proposta
  RPO 36 h in esercizio regolare; RTO 2 h su Linux pronto con accessi disponibili.
  [Checkpoint e limiti](evidence/RECOVERY-APPLICATION-2026-10-18.md)
- La prova di carico controllato del 17 ottobre è completata: 54 richieste HTTPS
  riuscite, massimo due concorrenti; è la prova limitata prevista e non misura la
  capacità massima. Dopo cleanup, GET pubblico `/opsz` alle 05:29:06.024486 UTC
  ha restituito HTTP 200, body `healthy`, in 0,604 s. I due runtime del drill
  sono PASS e chiusi come sopra.
  [Prova HTTPS](evidence/PUBLIC-GATEWAY-2026-10-17.md) ·
  [Backup e restore](evidence/BACKUP-AUTOMATION-2026-10-15.md)
- I materiali runtime e TLS recuperati dal backup hanno hash verificati,
  handshake TLS e controlli negativi PASS in 18,806 secondi; il drill applicativo
  successivo è documentato sopra. [Materiali](evidence/RECOVERY-MATERIALS-2026-10-18.md) ·
  [Preparazione](evidence/RECOVERY-RESUME-2026-10-18.md)
- Monitor UptimeRobot esistente configurato su `/opsz` e UP secondo conferma
  di Jacopo; intervallo 5 minuti visibile nello screenshot prima del cambio URL.
  Recapito TEST DOWN/UP verificato in Gmail alle 00:52 UTC; sonda indipendente
  GET/HEAD `/opsz` 200 alle 01:13 UTC. Non ripetere attivazione, test email o
  cambio URL. L'accesso tecnico a Chrome resta indisponibile per la QA Shopify;
  l'ispezione diretta della configurazione dopo la modifica è distinta dalla
  conferma del titolare. [Prova email e monitor](evidence/ALERT-DELIVERY-2026-10-18.md)
- Il negozio resta protetto da password. Il tema Arena MAIN è `210350735628`;
  il precedente `175195881740` è conservato per rollback.
- Il 18 ottobre la lettura API del componente MAIN e dei testi italiani ha
  confermato l'equivalenza con la fixture storica dopo normalizzazione delle
  righe. Le prove del componente restano riutilizzabili; nessuna nuova prova
  browser né equivalenza dell'intero tema è dichiarata.
  PDP e carrello stretti sono documentati da immagini del proprietario, con
  coerenza verificata indipendentemente. In quella prova font e dimensioni erano
  provvisori; lo stile Arena pubblicato il 19 ottobre supera tale stato. Accessibilità completa e
  down/stale live sono limiti di contesto, non gate originali dimostrati.
  [Binding](evidence/QA-COMPONENT-BINDING-2026-10-18.md) ·
  [Copertura e limiti QA](evidence/QA-REMAINING-2026-10-18.md)
- Il drill, la pulizia isolata e le lacune QA applicabili della fase sono chiusi.

## Cosa abbiamo

| Area | Stato verificato | Evidenza |
| --- | --- | --- |
| Catalogo | Proiezione completa e navigazione oltre 25.000 prodotti, con conte e identità verificate | [Fotografia e inventario](evidence/STATE-2026-09-30.md) |
| Ricerca | Gioco obbligatorio; singole per nome/codici verificati; sigillati e accessori per titolo commerciale; vista Tutto | [Ricerca per famiglia](workstreams/ws-05-family-search-v1.md) |
| Suggerimenti | Nomi distinti e dinamici per singole, confinati al gioco | [QA/manutenzione](evidence/MAINTENANCE-2026-09-30.md) |
| Filtri | Famiglia, disponibilità, espansione/rarità per singole e stato URL | [Fotografia e inventario](evidence/STATE-2026-09-30.md) |
| Presentazione e carrello | Immagini, SOLD OUT rosso, prezzi assenti/zero omessi; carrello nativo Shopify | [QA home e carrello](workstreams/ws-10-home-browser-20260928.md) |
| Tema | Arena MAIN `210350735628` dal 19 ottobre; precedente `175195881740` conservato per rollback; password attiva | [Pubblicazione Arena](DECISIONS.md#d-028--stile-arena-pubblicato) |

## Codice e consegna: stati distinti

**Installato.** Il gateway live e le pipeline ordinarie restano operative. Il
collector health `319ca0b` è installato e incluso nella prima cattura automatica
del 18 ottobre, verificata tramite manifest remoto. GET/HEAD pubblici su `/opsz`
erano 200 dopo quel backup; la verifica del 20 ottobre sopra riporta 503.
Il backup installato resta al pin `b56ca95`.

**Locale.** Le preparazioni retention sono conservate solo nei worktree locali:
planner `agent/offsite-backup-13` con commit precedente `aa2ffe5` e commit locale
più recente `1d4cf53` (esecutore). Sono preparazioni opzionali: non occorre
distribuire questi componenti per forza; la policy cloud resta inattiva.
La suite generale sul ramo locale resta incompleta: 1.712 PASS, un errore
intermittente Windows `WinError 5` al rename, zero skip. I test mirati successivi
non hanno riprodotto né spiegato la causa. [Planner](evidence/RETENTION-PLANNER-2026-10-17.md) ·
[Esecutore](evidence/RETENTION-EXECUTOR-2026-10-17.md)

**GitHub/remoto — ripresa del 20 ottobre.** Jacopo ha reso pubblica la repository
e autorizzato il completamento immediato, superando il rinvio D-024 e la sola
cadenza D-027. I nuovi workflow eseguono regolarmente test e analisi.
Le PR #100/#112/#113/#114, #26/#27/#109/#110, ricerca #116, CodeQL #111
ed evidenza dati #118 sono integrate, dopo controlli verdi e revisione
indipendente. #98 è chiusa perché superata da #111. La consegna finale comprende
patch Arena #117 e documentazione #101; i metadati delle due PR riportano
controlli finali e integrazione. La [ricevuta GitHub](evidence/GITHUB-DELIVERY-2026-10-20.md)
collega SHA, verifiche e issue riconciliate.
Il vecchio tentativo mattutino respinto è conservato come
[checkpoint storico](evidence/GITHUB-WEEKLY-2026-10-20.md).
Il completamento remoto non equivale a una nuova installazione sulla VPS.

## Vincoli e lacune

- Gateway e refresh restano read-only rispetto a Shopify. Non cambiare o
  disconnettere TCG PowerTools. L'eccezione autorizzata è un importer separato
  che crea solo stampe mancanti verificate, inizialmente draft, zero stock e
  senza sovrascrivere prodotti esistenti; la pubblicazione automatica autorizzata
  riguarda solo le sue carte verificate SOLD OUT. [Decisioni](DECISIONS.md)
- Conservare gli identificatori Shopify GID e le identità PowerTools/Cardmarket/
  CardTrader verificate. Mai identificare per solo titolo, inventare prezzi o
  dettagli lingua/condizione/finish, né eliminare silenziosamente record
  non classificati.
- Drill recovery applicativo: `current` e `previous` PASS; pulizia isolata conclusa
  con ricevuta `deletion_complete`. RPO proposto 36 h in esercizio regolare e RTO
  proposto 2 h su Linux pronto con accessi disponibili; non sono SLA. Host vuoto,
  provisioning e percorso pubblico restano fuori prova, non gate aggiunti.
  [Checkpoint recovery](evidence/RECOVERY-APPLICATION-2026-10-18.md)
- QA: le prove browser Shopify storiche, il componente legato alla fixture e il
  carico controllato sono riutilizzati. Lo spot-check manuale mobile PDP/carrello
  è documentato; immagini statiche, non una registrazione delle interazioni;
  full a11y e down/stale live restano limiti senza criterio originale locale
  dimostrato. Nessun outage live, benchmark massimo o regressione completa.
  [Matrice e limiti](evidence/QA-REMAINING-2026-10-18.md)
- Funzioni come ordinamenti diversi dal GID, filtri lingua/condizione/finish e
  “altre stampe” restano backlog, senza essere requisiti di completamento di
  questa fase; apertura pubblica senza password richiede una decisione separata
  del titolare.
- Non è documentato un percorso webhook completo in esercizio. I timer Bulk e
  importer costituiscono l'automazione accettata.

## Riferimenti

- [Handoff PM e checkpoint](PM-HANDOFF.md)
- [Fotografia e inventario del 30 settembre](evidence/STATE-2026-09-30.md)
- [Roadmap di esecuzione](ROADMAP-EXECUTION.md) · [Runbook operativo](OPERATIONS-RUNBOOK.md)
- [Decisioni e autorizzazioni](DECISIONS.md)
- [Cronologia precedente](STATUS-HISTORY-20260929.md)

## Prossimi passi

1. Definire e completare i tre workstream richiesti: modifiche alla home,
   nuove funzionalità e sezioni non dedicate alla vendita, nella direzione Arena.
   I dettagli sono ancora da definire; il backlog esistente non è automaticamente
   incluso. [Roadmap](ROADMAP-EXECUTION.md#ordine-di-lavoro-proposto)
2. Valutare il lancio pubblico soltanto dopo questi lavori; la rimozione della
   password resta una decisione separata di Jacopo.
3. Conservare le evidenze del drill chiuso e il backup verificato; le copie cloud sono protette e la rotazione
   automatica è opzionale, non un prerequisito.
4. Mantenere la manutenzione ordinaria separata e riutilizzare le prove QA valide.
   Ricevuti screenshot desktop (rimozione owner-attestata) e PDP/carrello
   stretti per la chiusura del 18 ottobre. La tipografia allora provvisoria è
   superata da Arena; il limite tecnico Computer Use di quella prova resta
   documentato. Lo spot-check manuale ha coperto la lacuna; alert e carico della
   fase sono conclusi.
   [QA](evidence/QA-REMAINING-2026-10-18.md)
5. La consegna GitHub D-030 si chiude con #117 e #101 fuse e controlli verdi;
   a quel punto eliminare solo `completa-consegna-github-nla`. Conservare
   la chat e l'automazione VPS, lasciata invariata (calendario salvato: domenica
   alle 09:00; il riferimento alle 48 ore nel prompt è storico).

La cronologia e le ricevute collegate conservano i dettagli dei singoli run.
Questa pagina fotografa lo stato e non sostituisce i limiti descritti nelle prove.
