# Tentativo GitHub settimanale — 20 ottobre 2026

> Checkpoint storico del primo tentativo mattutino. Successivamente Jacopo
> ha reso pubblica la repository e autorizzato esplicitamente il completamento
> della consegna. Il blocco qui descritto è superato dalla
> [ripresa e consegna del 20 ottobre](GITHUB-DELIVERY-2026-10-20.md).

Lettura remota riuscita tramite il collegamento GitHub. Le cinque PR storiche
risultano ancora aperte e non fuse:

| PR | Head verificato |
| --- | --- |
| #100 | `7ab94d345511ddd53c362206f041bf4942f1a61a` |
| #101 | `18ed78320f485d9ff03c05fa0514000e8afc156b` |
| #112 | `8657aaa495ae5e602d54365ffb691d06adc4f2c1` |
| #113 | `b56ca95fad2824b9faafc84c9f97ce66942fe75d` |
| #114 | `319ca0ba046715b769eda97af3e18fad906d6bc2` |

Per #101, CI `39021491093` e CodeQL `39021491094` risultano falliti.
La CI è ancora al tentativo 1 del **17 ottobre**, aggiornata alle 09:32:02 UTC:
questo è un fallimento storico, non dimostra che il budget sia tuttora bloccato.

È stato richiesto un solo riavvio dei job falliti della CI, come prova della
ripresa settimanale D-027. **La revisione automatica di approvazione lo ha
respinto prima dell'esecuzione GitHub**, interpretando il blocco storico come
divieto al retry e segnalando il possibile consumo di risorse Actions a pagamento.
Nessun aggiramento o secondo tentativo effettuato. La successiva lettura remota
conferma `run_attempt=1`; disponibilità attuale del budget non determinata.
Serve chiarire l'autorizzazione a questo singolo retry; non acquistare minuti
né modificare limiti di spesa. Non presentare il rifiuto come un nuovo errore
del codice o una risposta di fatturazione corrente di GitHub.

Ricevuta privata:
`output/nla-github-weekly-20261020-mvgc2lsa/receipt.json`, con stati/commit,
metadati del run e risposta integrale della revisione automatica.
Il CLI `gh` non era nel PATH o nel percorso standard; nessuna installazione,
il collegamento GitHub ha consentito le letture. Nessun push, merge, modifica
al codice, accesso VPS/Shopify o invio email. Il delta locale ricerca codici
del 19 ottobre resta distinto, come già descritto nell'handoff.

Consegna non conclusa: `completa-consegna-github-nla` resta attiva per la
prossima scadenza settimanale. Chat e automazione VPS restano invariate.
Metodo: [lettura PR](https://docs.github.com/en/rest/pulls/pulls#get-a-pull-request),
[riavvio dei job falliti](https://docs.github.com/en/rest/actions/workflow-runs#re-run-failed-jobs-from-a-workflow-run).
