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
    monkeypatch.setattr(market, "prune_batch_identities", lambda *_: None)
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
            skippedExisting=0,
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
    assert result["status"] == ("draft_cycle_partial" if apply else "preview_cycle_complete")
    assert result["remaining"] == (1 if apply else 2)
    assert result["eligibleExhausted"] is False
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


@pytest.mark.parametrize("invalid", ["space", "budget", "batch_budget", "ledger", "sha"])
def test_bad_local_prerequisite_does_not_start_network_work(setup, monkeypatch, invalid):
    args, events, _ = setup
    if invalid == "space":
        monkeypatch.setattr(market.shutil, "disk_usage", lambda _: SimpleNamespace(free=1))
    elif invalid == "budget":
        args["max_attempts"] = 101
    elif invalid == "batch_budget":
        args["max_batches"] = 101
    elif invalid == "ledger":
        args["ledger"] = args["state"] / "missing.sqlite3"
    else:
        args["generator_sha"] = "bad"
    with pytest.raises(ValueError):
        market.cycle(**args)
    assert not events and not (args["state"] / "pending-market-run.json").exists()


def test_one_source_multiple_fresh_batches_one_final_refresh(setup, monkeypatch):
    args, events, _ = setup
    paths = []

    def batch(*inputs, **kwargs):
        events.append("batch")
        paths.append((inputs[2].name, inputs[3].name))
        return dict(
            status="batch_complete",
            candidates=3,
            skippedExisting=len(paths) - 1,
            selected=1,
            exceptions=5,
            attempts=[dict(status="draft_verified")],
        )

    monkeypatch.setattr(market.drafts, "run_locked", batch)
    result = market.cycle(**args, apply_drafts=True, max_batches=10)
    assert events.count("source") == events.count("refresh") == 1
    assert events.count("batch") == 3 and events.count("identity") == 4
    assert events[-1] == "refresh"
    assert paths == [
        ("identities", "batch"),
        ("identities-0002", "batch-0002"),
        ("identities-0003", "batch-0003"),
    ]
    assert result["status"] == "draft_cycle_complete"
    assert result["remaining"] == 0 and result["eligibleExhausted"] is True
    assert result["completionReason"] == "eligible_exhausted"
    assert result["selected"] == len(result["attempts"]) == len(result["batches"]) == 3
    assert result["exceptions"] == 5  # Exceptions are not silently counted as imported.


def test_budget_exhaustion_is_closed_but_explicitly_partial(setup):
    args, events, _ = setup
    result = market.cycle(**args, apply_drafts=True, max_batches=2)
    assert result["status"] == "draft_cycle_partial" and result["remaining"] == 1
    assert result["completionReason"] == "batch_budget_exhausted"
    assert result["eligibleExhausted"] is False
    assert events.count("refresh") == 1 and len(result["batches"]) == 2
    assert not (args["state"] / "pending-market-run.json").exists()


def test_uncertain_later_batch_retains_pending_without_refresh_or_next_batch(setup, monkeypatch):
    args, events, _ = setup
    original = market.drafts.run_locked
    calls = []

    def uncertain(*inputs, **kwargs):
        calls.append(inputs[3].name)
        result = original(*inputs, **kwargs)
        if len(calls) == 2:
            result.update(
                status="needs_reconciliation", attempts=[dict(status="needs_reconciliation")]
            )
        return result

    monkeypatch.setattr(market.drafts, "run_locked", uncertain)
    with pytest.raises(ValueError, match="draft_batch_requires_inspection"):
        market.cycle(**args, apply_drafts=True, max_batches=10)
    assert calls == ["batch", "batch-0002"] and "refresh" not in events
    assert (args["state"] / "pending-market-run.json").exists()
    assert not (args["state"] / "last-market-success.json").exists()


def test_live_guard_rejections_do_not_claim_imported_or_loop(setup, monkeypatch):
    args, events, _ = setup
    original = market.drafts.run_locked

    def rejected(*inputs, **kwargs):
        result = original(*inputs, **kwargs)
        result["attempts"] = [dict(status="not_verified_missing")]
        return result

    monkeypatch.setattr(market.drafts, "run_locked", rejected)
    result = market.cycle(**args, apply_drafts=True, max_batches=10)
    assert result["status"] == "draft_cycle_partial" and result["remaining"] == 2
    assert result["completionReason"] == "no_verified_progress"
    assert events.count("batch") == 1 and "refresh" not in events


def test_preview_does_not_repeat_same_selection(setup):
    args, events, _ = setup
    result = market.cycle(**args, max_batches=10)
    assert result["completionReason"] == "preview" and events.count("batch") == 1
    assert "refresh" not in events


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
