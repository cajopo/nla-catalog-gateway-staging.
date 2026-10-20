# Chiusura della fase di manutenzione — 18 ottobre 2026

La fase PM è conclusa per l'obiettivo autorizzato: esercizio documentato,
verificato e recuperabile, con prove QA applicabili conservate. Non è una
chiusura delle issue/PR GitHub, che Jacopo ha esplicitamente differito, né
un'autorizzazione a pubblicare o modificare MAIN/password.

## Verifica rispetto all'obiettivo

| Requisito | Evidenza verificata e risultato |
| --- | --- |
| 1. Garanzie operative, ricevute, timer e freschezza | Retention periodica del 17 ottobre: unità success, timer attivi, due generazioni protette. Primo backup schedulato del 18 ottobre riuscito; `/opsz` 200 dopo backup e dopo cleanup. Runbook con soglie, ricevute e azioni. [Stato](../STATUS-CURRENT.md), [backup](BACKUP-SCHEDULED-2026-10-18.md), [runbook](../OPERATIONS-RUNBOOK.md). |
| 2. Copia fuori VPS e recupero isolato misurato | Backblaze cifrato, password custodita secondo conferma del proprietario; integrità `read-data`, restore verificato e runtime `current`/`previous` PASS (20 richieste). Entrambi chiusi entro 45m29s dal download, pulizia successiva verificata. Proposti RPO 36h e RTO 2h su Linux pronto, con limiti espliciti. [Recupero](RECOVERY-APPLICATION-2026-10-18.md), [custodia D-025](../DECISIONS.md#d-025--custodia-della-password-backup-in-1password). |
| 3. Alert, destinatario e gestione incidenti | Email TEST DOWN/UP ricevute; Jacopo referente iniziale, indirizzo scelto e modificabile; monitor `/opsz` UP confermato dal proprietario, GET/HEAD 200 verificati. Runbook con azioni per indisponibilità, refresh, dati vecchi, spazio e recupero. [Recapito e limiti](ALERT-DELIVERY-2026-10-18.md), [runbook](../OPERATIONS-RUNBOOK.md). |
| 4. QA applicabile e versioni | Fixture componente legata al sorgente installato: Chrome/Firefox/WebKit 21 controlli ciascuno, touch e retry dopo 503, stale/malformed, axe 39/38 controlli senza violazioni; incomplete contrasto risolto nel solo stato osservato. Carico limitato: 54 richieste HTTPS, massimo due concorrenti, invarianti preservati. Nuove immagini del proprietario completano lo spot-check manuale PDP/carrello stretto. [Matrice e limiti](QA-REMAINING-2026-10-18.md), [binding](QA-COMPONENT-BINDING-2026-10-18.md), [carico](PUBLIC-GATEWAY-2026-10-17.md). |
| 5. Documentazione e separazione delle consegne | Stato, roadmap, decisioni, handoff e runbook aggiornati; installato, candidati locali e GitHub differito distinti. Fotografia e prove storiche preservate. [Stato](../STATUS-CURRENT.md), [handoff](../PM-HANDOFF.md), [roadmap](../ROADMAP-EXECUTION.md), [decisioni](../DECISIONS.md). |

La verifica finale riusa le ricevute primarie, senza nuovi refresh, export,
backup, email di prova o simulazioni di guasto. Revisione indipendente di
`/root/closure_ops_review`: backup, recupero e alert coerenti con le rispettive
ricevute. Revisione indipendente di `/root/mobile_cart_review`: immagini PDP e
carrello coerenti per prodotto XFDN-316, opzioni, prezzo e quantità.

Per QA sono stati letti i risultati originali in
`output/nla-recovery/20260930/evidence/`: `qa-harness-escalated-result.json`,
`webkit-result.json`, `firefox-v2-run.log` e `firefox-v2-exit.txt`,
`qa-a11y-axe-result.json`, `qa-status-diagnostic-result.json` e
`qa-touch-down-final/path-fixed/qa-touch-down-result.json`. Confronto componente
in `output/nla-qa-component-fixture-20261018-01/independent-comparison.json`;
ricevuta carico e relativi pin in [PUBLIC-GATEWAY](PUBLIC-GATEWAY-2026-10-17.md).
Le immagini finali e i loro hash sono nella [matrice QA](QA-REMAINING-2026-10-18.md).

Verifica documentale finale PASS: 7 documenti, 197 destinazioni locali esistenti,
hash delle due nuove immagini verificati e tre cronologie invariate; anche
`git diff --check` sui documenti tracciati modificati è PASS. Ricevuta privata:
`output/nla-mobile-pdp-20261018-09db3e41/documentation-check.json`.
Revisione indipendente finale di `/root/closure_ops_review`: nessun blocker
o ampliamento indebito delle prove; GitHub e candidati locali restano distinti.

## Limiti e seguito

- Le immagini mobile sono stati statici, non click registrati o checkout;
  mostrano il nome del tema ma non una revisione immutabile, viewport o browser.
  Font e dimensioni sono provvisori: D-026; proposta CSS locale opzionale.
- Le prove axe/browser/stale riguardano il componente e gli scenari registrati,
  non certificano l'intero tema, Safari fisico o screen reader.
- RPO/RTO sono proposte operative, non SLA; host vuoto, provisioning e ripristino
  del percorso pubblico non sono stati provati. La rotazione cloud è opzionale
  e inattiva; nessuna prova di incidenti reali o deduplicazione degli alert.
- GitHub resta differito per D-024, inclusi i normali controlli e review della
  consegna futura. La suite incompleta del candidato locale retention non viene
  presentata come verde né come codice installato.
- Prosegue il controllo VPS ogni 48 ore già autorizzato. Nessun nuovo heartbeat
  o abbonamento. Lancio pubblico, grafica definitiva e nuove funzioni sono
  attività successive; nessun intervento su MAIN, password o PowerTools.
