# Recapito degli alert — 18 ottobre 2026

Jacopo ha eseguito **Test Notification** nel monitor NLA e confermato il buon
esito. La lettura indipendente di Gmail ha verificato entrambe le email di
`alert@uptimerobot.com`, presenti in INBOX: DOWN alle 00:52:29 UTC e UP alle
00:52:32 UTC. Sono notifiche TEST, non incidenti reali. Nessun guasto è stato
provocato e l'agente non ha inviato email.

La [procedura ufficiale UptimeRobot](https://help.uptimerobot.com/en/articles/11602913-how-to-test-notifications-in-uptimerobot-quick-guide)
usa il percorso di consegna degli alert. Il recapito al destinatario autorizzato
è quindi verificato per la prova. Ricevuta privata, senza corpo email o link di
accesso: `output/nla-alert-delivery-20261018.json`, SHA-256
`3cd2a67d2747c9bbc62555807bee296e47d03622b2b55aee8ff930307189ebc3`.

Le email di prova identificavano `/readyz`. Lo screenshot successivo fornito
da Jacopo mostra il monitor esistente `804287721`, stato UP, controllo ogni
5 minuti e il pulsante Edit. Dopo la guida al solo cambio URL, Jacopo ha
confermato: «Fatto, ho cambiato l'URL in /opsz e risulta UP».

Il controllo indipendente delle 01:13:42 UTC su
`https://catalog-staging.nextlevelarena.it/opsz` conferma GET e HEAD 200,
entrambi `Cache-Control: no-store`. Il metodo HTTP può restare invariato.
Il monitor ora punta a `/opsz` secondo conferma del titolare; la configurazione
successiva alla modifica non è stata ispezionata direttamente dall'agente.
Non ripetere attivazione, invio delle email di prova o richiesta di cambio URL.

Ricevuta e screenshot precedente al cambio URL sono conservati in
`output/nla-monitor-confirmation-20261018-7de99b6fef7b42fd84aad2659585ccf2/`.
SHA-256 screenshot:
`9033f4f082e809082947a8aae1994803bd409c51edee884622beedbdb1fa7d38`.
`confirmation.json` distingue i dati visibili nello screenshot, la conferma
del titolare e i risultati della sonda HTTP indipendente.

La prova non dimostra rilevazione o deduplicazione di un incidente reale.
Non simulare un guasto live per colmare queste lacune. La configurazione del
canale e il recapito TEST sono completati con i livelli di evidenza sopra;
i riferimenti storici a queste attività ancora pendenti sono superati.
