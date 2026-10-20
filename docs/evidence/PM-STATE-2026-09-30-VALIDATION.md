# Verifica della manutenzione documentale NLA

Intervento del 30 settembre 2026, issue #34 / master #3, ramo locale
agent/pm-state-20260930, base 3008e05938219bcdd1cf9e3d3f65b7134ae22ca3.
La modifica riguarda documenti e conservazione delle evidenze. Nessuna nuova
release, verifica live Shopify/VPS, modifica del MAIN o consegna GitHub.

## Controlli eseguiti

Ambiente esistente: Python 3.13.0, pytest 9.1.1, Ruff 0.16.5, Node 22.20.0,
Git 2.52.0.windows.1. Dipendenze già disponibili; nessuna nuova installazione.

| Controllo | Esito e limite |
| --- | --- |
| Git/GitHub e chat di riferimento | Issue #3/#17/#19/#34 e workstream letti; 20 issue e 21 PR aperte; stati e CI citati verificati in sola lettura |
| Conservazione delle tre cronologie | Copie byte-identiche ai documenti iniziali prima della riscrittura; hash sotto |
| Sorgenti e configurazione | 77 file protetti confrontati con gli hash iniziali, senza cambiamenti; incluse le modifiche pre-esistenti ai due file GraphQL e AGENTS.md |
| Ruff check src scripts tests | PASS |
| Ruff format --check src scripts tests | PASS, 58 file già formattati |
| pytest tests/test_preflight_repo.py tests/test_package.py | 587 passed, 116,43 secondi, exit 0; nessuna nuova dichiarazione di copertura completa |
| Build senza isolamento | PASS, sdist e wheel del checkout; output privato in Temp/nla-pm-state-20260930/dist |
| Collegamenti attivi e checksum delle cronologie | PASS: 13 documenti, 39 collegamenti locali, tre cronologie preservate |
| Preflight dell'indice documentale e git diff --cached --check | PASS: 123 file nell'indice, zero findings; diff senza errori di whitespace |

Comandi effettivi, eseguiti dalla radice del repository con gli eseguibili già presenti:

```powershell
& .\.venv\Scripts\ruff.exe check src scripts tests
& .\.venv\Scripts\ruff.exe format --check src scripts tests
$env:PYTHONDONTWRITEBYTECODE = '1'
& .\.venv\Scripts\python.exe -m pytest tests/test_preflight_repo.py tests/test_package.py -q -p no:cacheprovider --basetemp C:/Users/umbri/AppData/Local/Temp/nla-pm-state-20260930/pytest
& .\.venv\Scripts\python.exe -m build --no-isolation --outdir C:/Users/umbri/AppData/Local/Temp/nla-pm-state-20260930/dist
& .\.venv\Scripts\python.exe scripts/preflight_repo.py
git diff --cached --check
```

Il primo tentativo dalla radice, Ruff check . seguito da format --check .,
ha incontrato due directory storiche di test non accessibili; il linter ha
stampato “All checks passed”, poi il formatter è terminato con panic
“Expected a ruff source file”. Non è un controllo globale verde. I due comandi
ristretti alle directory dei sorgenti sono successivamente passati; nessuna
directory pre-esistente è stata eliminata o modificata per aggirare il problema.

## Cronologia preservata

| Documento | SHA256 dei byte originali conservati |
| --- | --- |
| STATUS-HISTORY-20260929.md | 2130c2d699d07c19db5020e9ca0de29c00d3cc79f947ab6830c5882cffd7b5b7 |
| PM-HANDOFF-HISTORY-20260929.md | e0411687eacfa9d21f6e99ce698cb8fbc599ed25975e39f2b8d5e3f2dccf15fd |
| ROADMAP-HISTORY-20260929.md | f7a3254404d4f3c81e35330ecdd7e4a55671797e1a964272d71c226b34f3d366 |

Git può normalizzare CRLF/LF. Il controllo seguente usa anche hash normalizzati
a LF, ripetibili dopo un checkout su sistemi diversi. Le cronologie conservano
le vecchie affermazioni con i loro limiti; non sono istruzioni di lavoro attive.

## Verifica riproducibile dei documenti

Eseguire dalla radice con Python disponibile. Il controllo verifica i collegamenti
locali dei documenti attivi e delle quattro note recuperate, più la conservazione
delle cronologie. Non richiede rete e non contatta Shopify.

```python
from pathlib import Path
import hashlib
import re

active = [Path("README.md")] + [
    Path("docs") / name
    for name in (
        "STATUS-CURRENT.md",
        "ROADMAP-EXECUTION.md",
        "PM-HANDOFF.md",
        "DECISIONS.md",
        "evidence/STATE-2026-09-30.md",
        "evidence/PM-STATE-2026-09-30-VALIDATION.md",
        "workstreams/ws-05-family-search-v1.md",
        "workstreams/ws-10-family-selector.md",
        "workstreams/ws-09f-warm-activation.md",
        "workstreams/ws-10-home-browser-20260928.md",
        "workstreams/ws-12-release-readiness-20260929.md",
        "workstreams/other-printings-product-page.md",
    )
]
links = 0
for file in active:
    body = file.read_text(encoding="utf-8-sig")
    for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", body):
        if re.match(r"^[a-z][a-z0-9+.-]*:", target) or target.startswith("#"):
            continue
        target = target.split("#", 1)[0]
        assert (file.parent / target).is_file(), (file, target)
        links += 1
history = {
    "STATUS-HISTORY-20260929.md": "4c749bec8bb3728a24edaef78a5372cf3f8ea87d7b221390611445a0efbdbb57",
    "PM-HANDOFF-HISTORY-20260929.md": "0d2cd2cf0d15807789611ecfa275183c9a8c82019af82ae6240292959ea2eb18",
    "ROADMAP-HISTORY-20260929.md": "560a1898b4590abd6cabc07c9801d68c25d7e579354556e95a02e8df5347c153",
}
for name, expected in history.items():
    data = (Path("docs") / name).read_bytes().replace(b"\r\n", b"\n")
    assert hashlib.sha256(data).hexdigest() == expected, name
print(f"PASS: {len(active)} documents, {links} local links, 3 preserved histories")
```

I confronti con gli hash iniziali dei 77 file protetti sono conservati nel percorso
privato Temp/nla-pm-state-20260930/protected-hashes.json. Le quattro note di
workstream recuperate provengono dalla preview privata del 29 settembre: è stata
aggiunta solo un'avvertenza sulla loro data e sullo stato corrente.

## Limiti della consegna

Non è stata rieseguita tutta la suite applicativa, né modificata la soglia di
copertura. I 4.040 test e la successiva copertura aggregata del 29 settembre sono
prove precedenti, chiaramente distinte nella fotografia.

Nessun push, PR, merge, CI remota o aggiornamento delle issue. Review indipendente
di questa revisione documentale e criteri completi di consegna #34 restano aperti
per il rinvio GitHub deciso dal proprietario; nessuna auto-approvazione dichiarata.
La manutenzione dei file non viene presentata come chiusura formale di #34/#3.

La cronologia è preservata e i soli documenti scelti entrano nella consegna locale;
AGENTS.md, i due GraphQL, .codex e gli altri elementi pre-esistenti restano fuori.
La revisione non introduce un nuovo rischio di esercizio. Il ripristino dei testi
precedenti è disponibile nelle tre cronologie; non serve un rollback del servizio.

L'indice della consegna locale contiene 21 soli file Markdown, incluse le due
note pre-esistenti non ancora tracciate su cutover e altre stampe, necessarie
ai collegamenti della fotografia. Il commit risultante si identifica con
`git log -1 --format=fuller` sul ramo indicato; i risultati di questa pagina
non diventano una CI remota per effetto del commit locale.
