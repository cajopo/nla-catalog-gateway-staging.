# Health e osservabilità backup — 17 ottobre 2026

## Stato verificato

La PR #114 (health operativa #13), head
`319ca0ba046715b769eda97af3e18fad906d6bc2`, è stata pubblicata alle 09:14 UTC.
Il collector è stato eseguito in memoria sull'host alle 09:17:08.775623 UTC con
verifica read-only: PASS; ricevuta SHA-256
`902b0b26ce5753bc22f19cb8dd1008622bb5c776294d5182ec08d56498d9e4b5`.
Non sono stati installati file né scritti stati nativi. Questa prova non attesta
l'installazione del nuovo collector, la sua unità o una nuova cattura.

Il codice rileva failure del servizio backup, confronta `last-success` con la
ricevuta immutabile per-job e valida i campi d'identità dello snapshot senza
interrogare autonomamente il repository remoto; segnala checkpoint oltre
26 ore, controlla staging residuo entro limiti e verifica abilitazione/attività
dei timer market, refresh e backup. La soglia di 26 ore è un trigger di alert,
non un RPO. È ammessa la pausa refresh controllata dal market. La risposta HTTP
resta generica e invariata. L'elapsed monotonic evita un falso stato futuro
quando il backup termina durante la lettura. mtime è usato solo come evidenza
temporale e non come prova di ownership del processo.

## Verifiche del cambiamento

- 158 test mirati, 100% statement e branch complessivi sui tre moduli health.
- Review indipendente PASS.
- Ruff, format e preflight su 219 file PASS.
- Controllo documentale finale preflight 129 file PASS.
- Il build isolato locale non è riuscito perché Python 3.13 locale è distribuito
  con MySQL Shell e il virtualenv generato era privo di SSL. Wheel e sdist costruiti con
  `--no-isolation` PASS.
- CI `39020355673` e CodeQL `39020355686` SUCCESS; tutti e quattro i job e gli
  step PASS, nessuno saltato. Python 3.12: 4.244 test passati, copertura
  statement/branch 100%, 516,90 s; Python 3.13: 4.244 passati, copertura
  statement/branch 100%, 652,61 s, un warning. Preflight 219 e build isolato
  CI PASS su entrambe le versioni; il build isolato CI Python 3.12 è passato
  alle 09:23:21 UTC.

L'hash SHA-256 dell'entry `operational_health.py` nel wheel, dopo normalizzazione
LF, coincide con `a91d22…` del commit congelato; non è l'hash dell'intero wheel.
L'helper di rollout (non esegue catture backup) ha superato 26 test sintetici.
Helper SHA-256
`e3d0112cb4af7a806dfb4123cc30b4554c70fe23ef5513d53425065b0ecf0e8f`;
payload SHA-256 `5e74b0f8167173ddf48375e198a3df536beac02fde6ec20b6877a5e7e2e7294c`.
Pin candidato unità SHA-256
`1d82c090f2d1ca4b1f878e725e4684cb940839c4f89ce8c50d1784e16fc10622`;
config SHA-256 `5358c3483d128ecbb7ea484f73edd5b6c9c806012ffe13e61391587336d7c5d4`.
La configurazione precedente è `54a376…`; il backup più recente è lo snapshot
`ffa29faf98aecfc61a39c2ad52f9bc69803a3b479e2cc877fa7a87297ef43cf8` e non
include ancora il nuovo observer.

## Rollout nativo completato

Rollout riuscito del package `/opt/nla-operational-observer-319ca0b`, nuova unità
e quattro pin sorgente verificati. Endpoint HTTP, Caddy e pipeline non sono
stati modificati. Le sole azioni unità sono state stop `observer.timer`,
daemon-reload, start `observer.service` e start `observer.timer`; nessun rollback.
Pin unità `1d82c090f2d1ca4b1f878e725e4684cb940839c4f89ce8c50d1784e16fc10622`;
config `5358c3483d128ecbb7ea484f73edd5b6c9c806012ffe13e61391587336d7c5d4`.

Osservazioni healthy alle 09:26:51 e 09:27:21 UTC. GET e HEAD `/opsz` su
loopback e endpoint pubblico hanno restituito 200/no-store. Python 3.12
compile/import nativo e `systemd-analyze verify` PASS. L'HTTP server resta
`59a74e6`, PID `526219`, invocation `279cba19456d46f2a254b20377da8ef7`; pointer
`43476f7e8babe20362039ac21c56ebc6793c606eea9133326f1877fc7b30fd5a` invariato.
Verifica finale read-only alle 09:28:04.384413 UTC: 13.244.923.904 byte liberi;
market/refresh/backup `inactive/success`, i relativi timer enabled/active/waiting;
observer healthy con timer enabled. Ricevuta rollout privata
`/var/lib/nla-backup-health-rollout-4c256ef8a2d5437fae17cd03737df78b/result.json`,
SHA-256 `85c0f24cdcc88346af99e3351579b484ccd8fc73eb90aca245f85dc2351790bd`;
intent SHA-256 `571122266e0128090336183b4d9dcd9a57746abc64c5f41eccd02f85ef6e76a4`.
Ricevuta di verifica read-only privata locale
`output/nla-observer-upgrade-20261017T092648Z-42c8014843ab426c80d8fb23f315b9ae/verified-receipt-readonly.result.json`,
SHA-256 `f5e4b2ebe94be3a24092d21a73e082f9375b9a046e450bfd33cf581df6641828`.

Non è stato avviato un backup manuale. Ultima cattura completa verificata:
job `backup-919aeddea561432c9da028bd7e3ff6e8`, snapshot
`ffa29faf98aecfc61a39c2ad52f9bc69803a3b479e2cc877fa7a87297ef43cf8`, gate
`read-data` PASS, ricevuta `ce6018583f3d7369d36f97d9a09bf453748a60f8575f4ed8fad49ebad148b4e6`,
verificato entro le 08:18 UTC del 17 ottobre. La nuova
versione observer non è ancora inclusa in una cattura. Il timer backup è
enabled/waiting per il 18 ottobre alle 01:00 UTC; questa prima esecuzione
automatica non è ancora osservata. Il nuovo observer non è incluso nella cattura
(`backedUp=false`); la prima inclusione dipende dal prossimo backup, senza
esecuzione manuale. Conservazione cloud, host vuoto e custodia
indipendente della password restano limiti già registrati nei documenti
[backup/restore](BACKUP-AUTOMATION-2026-10-15.md) e
[retention cloud](CLOUD-RETENTION-2026-10-17.md).

Il blocco tecnico di Computer Use su Chrome lascia monitor UptimeRobot e
recapito email non verificati. Il consenso del proprietario è già registrato
in D-023; non è una richiesta di consenso pendente.

## Fonti di stato

- Codice e CI: [PR #114](https://github.com/cajopo/nla-catalog-gateway-staging./pull/114).
- Backup precedente, job fallito e prove storiche: [automazione backup](BACKUP-AUTOMATION-2026-10-15.md).
- Attivazione iniziale health: [operational health](OPERATIONAL-HEALTH-2026-10-15.md).

CI e rollout sono completati; la prima cattura automatica che includa il nuovo
observer e la verifica del recapito restano pendenti.
