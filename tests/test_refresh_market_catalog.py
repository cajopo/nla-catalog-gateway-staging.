import json
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts import refresh_market_catalog as market


@pytest.fixture
def setup(tmp_path, monkeypatch):
    events = []
    config = dict(shop="test.myshopify.com", run_root=tmp_path / "refresh-runs")
    config["run_root"].mkdir()
    ledger = tmp_path / "ledger.sqlite3"
    ledger.touch()
    monkeypatch.setattr(market.activation, "sync_directory", lambda _: None)
    monkeypatch.setattr(market.refresh, "pipeline_lock", lambda _: nullcontext())
    monkeypatch.setattr(market.drafts, "config_values", lambda _: ({}, config))
    monkeypatch.setattr(market, "prune_completed_inputs", lambda *_: 0)
    monkeypatch.setattr(market.shutil, "disk_usage", lambda _: SimpleNamespace(free=10 * 1024**3))
    monkeypatch.setattr(market.refresh, "freshness", lambda _: {"status": "fresh"})
    behavior = dict(fail=None, identity_calls=0, batch_status="batch_complete")

    def source(client, path):
        events.append("source")
        assert (tmp_path / "pending-market-run.json").exists()
        if behavior["fail"] == "source":
            raise ValueError("source failure")
        path.mkdir()
        return dict(completedExpansions=4, blueprints=50, files={})

    def identity(client, shop, path):
        events.append("identity")
        assert shop == config["shop"]
        if behavior["fail"] == "identity":
            raise ValueError("identity failure")
        behavior["identity_calls"] += 1
        return dict(
            status="running" if behavior["identity_calls"] == 1 else "complete",
            operationId="gid://shopify/BulkOperation/10",
        )

    def batch(*args, **kwargs):
        events.append("batch")
        assert args[3].parent == args[1].parent == args[2].parent
        assert args[4] == ledger and kwargs["max_attempts"] == 1
        if behavior["fail"] == "interrupt":
            raise KeyboardInterrupt
        applied = kwargs["apply"]
        return dict(
            status=behavior["batch_status"] if applied else "preview",
            candidates=2,
            selected=1,
            exceptions=0,
            attempts=[dict(status="draft_verified", productGid="gid://shopify/Product/9")]
            if applied
            else [],
        )

    def refresh(*args):
        events.append("refresh")
        if behavior["fail"] == "refresh":
            raise ValueError("refresh failed")

    monkeypatch.setattr(market, "capture_catalog", source)
    monkeypatch.setattr(market.identities, "capture_once", identity)
    monkeypatch.setattr(market.drafts, "run_locked", batch)
    monkeypatch.setattr(market, "refresh_index", refresh)
    values = dict(
        state=tmp_path,
        refresh_config=tmp_path / "config.json",
        refresh_package=tmp_path / "package",
        ledger=ledger,
        generator_sha="a" * 40,
        cardtrader=object(),
        shopify=object(),
        pause=lambda n: events.append(f"pause{n}"),
    )
    return values, events, behavior


@pytest.mark.parametrize("apply", [False, True])
def test_stage_order_and_explicit_draft_apply(setup, apply):
    args, events, _ = setup
    result = market.cycle(**args, apply_drafts=apply)
    assert events == ["source", "identity", "pause30", "identity", "batch"] + (
        ["refresh"] if apply else []
    )
    assert result["status"] == ("draft_cycle_complete" if apply else "preview_cycle_complete")
    assert result["published"] is False and result["indexRefreshed"] is apply
    assert not (args["state"] / "pending-market-run.json").exists()
    assert json.loads((args["state"] / "last-market-success.json").read_bytes()) == result
    run = args["state"] / result["run"]
    assert json.loads((run / "completed.json").read_bytes()) == result


@pytest.mark.parametrize("failure", ["source", "identity", "interrupt", "refresh", "batch"])
def test_uncertainty_retains_pending_and_prevents_next_execution(setup, failure):
    args, events, behavior = setup
    behavior["fail"] = failure
    if failure == "batch":
        behavior["batch_status"] = "needs_reconciliation"
    with pytest.raises((ValueError, KeyboardInterrupt)):
        market.cycle(**args, apply_drafts=True)
    marker = args["state"] / "pending-market-run.json"
    run = args["state"] / json.loads(marker.read_bytes())["run"]
    assert (
        json.loads((run / "stopped.json").read_bytes())["status"] == "stopped_inspect_pending_cycle"
    )
    assert not (run / "completed.json").exists()
    assert not (args["state"] / "last-market-success.json").exists()
    before = list(events)
    with pytest.raises(ValueError, match="previous_market_cycle_requires_inspection"):
        market.cycle(**args, apply_drafts=True)
    assert events == before


def test_expired_poll_waits_on_same_operation_not_a_replacement(setup, monkeypatch):
    args, events, _ = setup
    times = iter([0, 1201])
    monkeypatch.setattr(market.time, "monotonic", lambda: next(times))
    with pytest.raises(ValueError, match="identity_poll_limit"):
        market.cycle(**args)
    assert events == ["source", "identity"]
    assert (args["state"] / "pending-market-run.json").exists()


@pytest.mark.parametrize("invalid", ["space", "budget", "ledger", "sha"])
def test_bad_local_prerequisite_does_not_start_network_work(setup, monkeypatch, invalid):
    args, events, _ = setup
    if invalid == "space":
        monkeypatch.setattr(market.shutil, "disk_usage", lambda _: SimpleNamespace(free=1))
    elif invalid == "budget":
        args["max_attempts"] = 101
    elif invalid == "ledger":
        args["ledger"] = args["state"] / "missing.sqlite3"
    else:
        args["generator_sha"] = "bad"
    with pytest.raises(ValueError):
        market.cycle(**args)
    assert not events and not (args["state"] / "pending-market-run.json").exists()


def test_refresh_subprocess_uses_existing_operator_and_propagates_failure(tmp_path, monkeypatch):
    args = []

    def execute(command, **kwargs):
        args.append((command, kwargs))

    monkeypatch.setattr(market.subprocess, "run", execute)
    market.refresh_index(tmp_path, tmp_path / "config.json")
    command, options = args[0]
    assert command[1:4] == ["-m", "scripts.refresh_staging_catalog", "--config"]
    assert command[-1] == "--apply" and options["check"] is True
    assert options["cwd"] == tmp_path
    assert Path(options["env"]["PYTHONPATH"]) == tmp_path / "src"

    def fail(command, **kwargs):
        raise market.subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(market.subprocess, "run", fail)
    with pytest.raises(market.subprocess.CalledProcessError):
        market.refresh_index(tmp_path, tmp_path / "config.json")
