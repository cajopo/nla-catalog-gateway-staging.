import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from scripts import publish_imported_drafts as cli


def test_default_disabled_without_credentials_or_ledger(tmp_path):
    assert cli.run(tmp_path / "missing", tmp_path / "missing-db", "bad")["status"] == "disabled"


@pytest.mark.parametrize("pending", [None, "market", "refresh"])
def test_lock_order_pending_guard_and_durable_receipt(tmp_path, monkeypatch, pending):
    state = tmp_path / "importer"
    state.mkdir()
    refresh_state = tmp_path / "refresh"
    refresh_state.mkdir()
    ledger = state / "ledger.sqlite3"
    ledger.touch(mode=0o600)
    config = dict(run_root=refresh_state, config=tmp_path / "config", shop="test.myshopify.com")
    monkeypatch.setattr(cli.drafts, "config_values", lambda _: ({}, config))
    events = []

    @contextmanager
    def lock(path):
        events.append(("lock", path))
        yield
        events.append(("unlock", path))

    def publish(db, **kwargs):
        assert events == [("lock", state), ("lock", refresh_state)]
        assert db == ledger and kwargs["publication_id"] == "gid://shopify/Publication/12"
        return dict(status="publication_complete", published=1, remaining=0, results=[])

    monkeypatch.setattr(cli.refresh, "pipeline_lock", lock)
    monkeypatch.setattr(
        cli.refresh,
        "document",
        lambda _: {"client_id": "fixture-id", "client_secret": "fixture-only"},
    )
    monkeypatch.setattr(cli, "ShopifyCaptureHttp", lambda **kw: SimpleNamespace(graphql=object()))
    monkeypatch.setattr(cli, "publish_verified_drafts", publish)
    monkeypatch.setattr(cli.refresh.activation, "sync_directory", lambda _: None)
    if pending:
        marker = (
            state / "pending-market-run.json"
            if pending == "market"
            else refresh_state / "pending-run.json"
        )
        marker.touch()
        with pytest.raises(ValueError, match="pending_cycle"):
            cli.run(tmp_path / "config.json", ledger, "gid://shopify/Publication/12", apply=True)
        assert not list(state.glob("publication-*.json"))
    else:
        result = cli.run(
            tmp_path / "config.json", ledger, "gid://shopify/Publication/12", apply=True
        )
        assert result["published"] == 1
        assert events[-2:] == [("unlock", refresh_state), ("unlock", state)]
        assert json.loads(next(state.glob("publication-*.json")).read_bytes())["published"] == 1
