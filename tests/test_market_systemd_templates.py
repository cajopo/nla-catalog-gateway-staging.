from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "ops/systemd"


def test_market_service_is_bounded_oneshot_and_restores_only_fallback_timer():
    text = (ROOT / "nla-market-catalog.service.in").read_text()
    lines = text.splitlines()
    assert "Type=oneshot" in lines and "TimeoutStartSec=23h" in lines
    assert not any(line.startswith(("RemainAfterExit=", "Restart=", "ExecStop=")) for line in lines)
    assert "ExecStartPre=/usr/bin/systemctl stop nla-catalog-refresh.timer" in lines
    assert "ExecStopPost=/usr/bin/systemctl start nla-catalog-refresh.timer" in lines
    assert "systemctl stop nla-catalog-refresh.service" not in text
    assert "--max-attempts 100 --max-batches 50 --apply-drafts" in text
    assert "WorkingDirectory=@IMPORTER_PACKAGE@" in lines
    assert "Environment=PYTHONPATH=@IMPORTER_PACKAGE@/src" in lines
    assert "--refresh-package @REFRESH_PACKAGE@" in text
    assert "--generator-sha @IMPORTER_CODE_SHA@" in text
    assert "--ledger /opt/nla-staging/importer-state/draft-attempts.sqlite3" in text
    assert (
        "--cardtrader-credentials /opt/nla-staging/config/cardtrader-api-credentials.json" in text
    )
    assert "ExecStart=/usr/bin/python3 -m scripts.refresh_market_catalog" in text


def test_timer_uses_explicit_utc_schedule_without_catchup():
    lines = (ROOT / "nla-market-catalog.timer.in").read_text().splitlines()
    assert "OnCalendar=*-*-* 02,14:00:00 UTC" in lines
    assert "Persistent=false" in lines
    assert "Unit=nla-market-catalog.service" in lines
    assert "WantedBy=timers.target" in lines
