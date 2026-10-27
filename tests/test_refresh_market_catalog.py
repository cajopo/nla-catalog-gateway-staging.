import json
import sqlite3
from contextlib import closing, nullcontext
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

    def source(client, path, *, game_scope="legacy"):
        events.append("source")
        behavior["game_scope"] = game_scope
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


@pytest.mark.parametrize("apply", [False, True])
def test_deferred_source_does_not_block_available_imports_or_next_cycle(setup, monkeypatch, apply):
    args, events, _ = setup
    args["shopify"] = SimpleNamespace(graphql=lambda *args, **kwargs: None)
    original = market.capture_catalog
    deferred = [dict(expansionId=4, httpStatus=404, reason="export_http_404")]

    def source(client, path, **kwargs):
        return {**original(client, path, **kwargs), "deferredExpansions": deferred}

    def batch(*inputs, **kwargs):
        events.append("batch")
        return dict(
            status="batch_complete" if apply else "preview",
            candidates=1,
            skippedExisting=0,
            selected=1,
            exceptions=0,
            attempts=[dict(status="draft_verified")] if apply else [],
        )

    def publish(*inputs, **kwargs):
        events.append("publication")
        return dict(status="publication_complete", published=1, remaining=0, results=[])

    monkeypatch.setattr(market, "capture_catalog", source)
    monkeypatch.setattr(market.drafts, "run_locked", batch)
    monkeypatch.setattr(market, "publish_verified_drafts", publish)
    result = market.cycle(
        **args,
        apply_drafts=apply,
        publish_online_store="gid://shopify/Publication/1" if apply else None,
    )
    assert result["status"] == ("draft_cycle_partial" if apply else "preview_cycle_partial")
    assert result["sourceComplete"] is False and result["sourceDeferredExpansions"] == deferred
    assert result["indexRefreshed"] is apply
    assert events == ["source", "identity", "pause30", "identity", "batch"] + (
        ["publication", "refresh"] if apply else []
    )
    assert not (args["state"] / "pending-market-run.json").exists()
    market.cycle(**args, apply_drafts=apply)
    assert events.count("source") == 2


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


def test_batch_failure_reason_reaches_cycle_receipt(setup, monkeypatch):
    args, _, _ = setup
    original = market.drafts.run_locked

    def failed(*a, **kw):
        result = original(*a, **kw)
        result["status"] = "stopped_inspect_before_retry"
        result["failure"] = dict(reason="inconsistent_identity_page", cardmarketId=43)
        return result

    monkeypatch.setattr(market.drafts, "run_locked", failed)
    with pytest.raises(ValueError, match="draft_batch_requires_inspection"):
        market.cycle(**args, apply_drafts=True)
    marker = json.loads((args["state"] / "pending-market-run.json").read_bytes())
    receipt = json.loads((args["state"] / marker["run"] / "stopped.json").read_bytes())
    assert receipt["batchFailure"] == dict(reason="inconsistent_identity_page", cardmarketId=43)


@pytest.mark.parametrize("verified", [0, 1])
@pytest.mark.parametrize("failure", [None, "ledger", "publication", "refresh"])
def test_readonly_deferral_finalizes_partial_only_with_a_verified_ledger(
    setup, monkeypatch, verified, failure
):
    args, events, behavior = setup
    args["shopify"] = SimpleNamespace(graphql=object())
    with closing(sqlite3.connect(args["ledger"])) as db:
        db.execute("CREATE TABLE draft_attempts(state TEXT NOT NULL)")
        db.execute("INSERT INTO draft_attempts VALUES ('draft_verified')")
        db.commit()
    deferred = [dict(cardmarketId=43, blueprintId=10, reason="inconsistent_identity_page")]

    def batch(*inputs, **kwargs):
        events.append("batch")
        assert kwargs == dict(apply=True, max_attempts=3)
        with closing(sqlite3.connect(args["ledger"])) as db:
            if failure == "ledger":
                db.execute("UPDATE draft_attempts SET state='needs_reconciliation'")
            elif verified:
                db.execute("INSERT INTO draft_attempts VALUES ('draft_verified')")
            db.commit()
        return dict(
            status="batch_deferred",
            candidates=5,
            skippedExisting=1,
            selected=3,
            exceptions=2,
            attempts=[dict(status="draft_verified", cardmarketId=42)] * verified
            + [dict(status="not_verified_missing", cardmarketId=43)],
            deferred=deferred,
        )

    def publish(ledger, **kwargs):
        events.append("publication")
        assert ledger == args["ledger"] and kwargs["enabled"] is True
        return dict(
            status="publication_stopped_inspect"
            if failure == "publication"
            else "publication_complete",
            published=1,
            remaining=1 if failure == "publication" else 0,
            results=[],
        )

    monkeypatch.setattr(market.drafts, "run_locked", batch)
    monkeypatch.setattr(market, "publish_verified_drafts", publish)
    if failure == "refresh":
        behavior["fail"] = "refresh"
    options = dict(
        apply_drafts=True,
        max_attempts=3,
        max_batches=10,
        publish_online_store="gid://shopify/Publication/12",
    )
    if failure is None:
        result = market.cycle(**args, **options)
        run = args["state"] / result["run"]
        assert result["status"] == "draft_cycle_partial"
        assert result["indexRefreshed"] is True and result["published"] is True
        assert result["eligibleExhausted"] is False
        assert events[-2:] == ["publication", "refresh"]
        assert not (args["state"] / "pending-market-run.json").exists()
        assert json.loads((run / "completed.json").read_bytes()) == result
    else:
        reason = {
            "ledger": "previous_import_needs_reconciliation",
            "publication": "publication_requires_inspection",
            "refresh": "refresh failed",
        }[failure]
        with pytest.raises(ValueError, match=reason):
            market.cycle(**args, **options)
        marker = json.loads((args["state"] / "pending-market-run.json").read_bytes())
        run = args["state"] / marker["run"]
        result = json.loads((run / "stopped.json").read_bytes())
        assert not (run / "completed.json").exists()
        assert not (args["state"] / "last-market-success.json").exists()
        assert ("publication" in events) is (failure != "ledger")
        assert ("refresh" in events) is (failure == "refresh")
    assert events.count("source") == events.count("batch") == 1
    assert result["remaining"] == 4 - verified
    assert result["deferred"] == deferred
    assert result["completionReason"] == "precreate_identity_deferred"
    assert len(result["batches"]) == 1 and result["exceptions"] == 2


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
    assert events.count("batch") == events.count("refresh") == 1


def test_preview_does_not_repeat_same_selection(setup):
    args, events, _ = setup
    result = market.cycle(**args, max_batches=10)
    assert result["completionReason"] == "preview" and events.count("batch") == 1
    assert "refresh" not in events


@pytest.mark.parametrize("apply", [False, True])
@pytest.mark.parametrize("source_complete", [False, True])
def test_empty_batch_reuses_fresh_index_without_claiming_refresh(
    setup, monkeypatch, apply, source_complete
):
    args, events, _ = setup
    original_source = market.capture_catalog

    def source(*inputs, **kwargs):
        result = original_source(*inputs, **kwargs)
        result["deferredExpansions"] = (
            [] if source_complete else [dict(expansionId=4, httpStatus=404)]
        )
        return result

    def empty_batch(*inputs, **kwargs):
        events.append("batch")
        # This is run_locked's actual no-selection contract, even with apply=True.
        return dict(
            status="preview", candidates=2, skippedExisting=2, selected=0, exceptions=0, attempts=[]
        )

    monkeypatch.setattr(market.drafts, "run_locked", empty_batch)
    monkeypatch.setattr(market, "capture_catalog", source)
    result = market.cycle(**args, apply_drafts=apply, max_batches=50)
    assert events.count("batch") == 1
    assert "refresh" not in events
    assert result["indexRefreshed"] is False
    if apply:
        assert result["indexRefreshSkippedReason"] == "no_importer_changes_index_fresh"
        assert result["indexFreshness"] == {"status": "fresh"}
    else:
        assert "indexRefreshSkippedReason" not in result
    assert result["remaining"] == 0 and result["attempts"] == []
    prefix = "draft" if apply else "preview"
    assert result["status"] == prefix + ("_cycle_complete" if source_complete else "_cycle_partial")
    assert result["sourceComplete"] is source_complete
    assert not (args["state"] / "pending-market-run.json").exists()


@pytest.mark.parametrize(
    "case",
    ["empty", "stale", "pending", "invalid_runtime", "published", "reconciled", "attempted"],
)
def test_empty_cycle_refresh_decision_preserves_freshness_and_write_guards(
    setup, monkeypatch, case
):
    args, events, _ = setup
    args["shopify"] = SimpleNamespace(graphql=object())

    def batch(*inputs, **kwargs):
        events.append("batch")
        return dict(
            status="preview",
            candidates=0,
            skippedExisting=0,
            selected=0,
            exceptions=0,
            attempts=[dict(status="not_verified_missing")] if case == "attempted" else [],
        )

    def publish(*inputs, **kwargs):
        events.append("publication")
        if case == "pending":
            (args["state"] / "refresh-runs" / "pending-run.json").touch()
        return dict(
            status="publication_complete",
            published=int(case == "published"),
            alreadyPublished=int(case == "reconciled"),
            remaining=0,
            results=[],
        )

    def freshness(config):
        events.append("freshness")
        if case == "invalid_runtime":
            raise ValueError("freshness receipt does not describe current runtime")
        return {"status": "stale" if case == "stale" and "refresh" not in events else "fresh"}

    monkeypatch.setattr(market.drafts, "run_locked", batch)
    monkeypatch.setattr(market, "publish_verified_drafts", publish)
    monkeypatch.setattr(market.refresh, "freshness", freshness)
    options = dict(apply_drafts=True, publish_online_store="gid://shopify/Publication/12")
    if case in ("pending", "invalid_runtime"):
        reason = "catalog_refresh_pending" if case == "pending" else "freshness receipt"
        with pytest.raises(ValueError, match=reason):
            market.cycle(**args, **options)
        assert "refresh" not in events
        assert (args["state"] / "pending-market-run.json").exists()
        assert not (args["state"] / "last-market-success.json").exists()
    else:
        result = market.cycle(**args, **options)
        assert result["indexRefreshed"] is (case != "empty")
        assert events.count("refresh") == int(case != "empty")
        assert ("indexRefreshSkippedReason" in result) is (case == "empty")
        assert result["status"] == "draft_cycle_complete"
        assert not (args["state"] / "pending-market-run.json").exists()
    assert events.count("source") == events.count("batch") == events.count("publication") == 1


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


@pytest.mark.parametrize(
    "apply,channel", [(False, "gid://shopify/Publication/12"), (True, "bad"), (True, True)]
)
def test_publication_gate_before_any_network_work(setup, apply, channel):
    args, events, _ = setup
    with pytest.raises(ValueError, match="publication_requires_apply"):
        market.cycle(**args, apply_drafts=apply, publish_online_store=channel)
    assert events == []
    assert not (args["state"] / "pending-market-run.json").exists()


@pytest.mark.parametrize("failed", [False, True])
def test_authorized_publication_precedes_only_refresh_and_records_partial_writes(
    setup, monkeypatch, failed
):
    args, events, _ = setup
    args["shopify"] = SimpleNamespace(graphql=object())

    def publish(ledger, **kwargs):
        events.append("publication")
        assert ledger == args["ledger"]
        assert kwargs == dict(
            shop="test.myshopify.com",
            publication_id="gid://shopify/Publication/12",
            graphql=args["shopify"].graphql,
            enabled=True,
            max_products=10000,
        )
        return dict(
            status="publication_stopped_inspect" if failed else "publication_complete",
            published=2,
            alreadyPublished=5,
            remaining=1 if failed else 0,
            results=[],
        )

    monkeypatch.setattr(market, "publish_verified_drafts", publish)
    if failed:
        with pytest.raises(ValueError, match="publication_requires_inspection"):
            market.cycle(
                **args, apply_drafts=True, publish_online_store="gid://shopify/Publication/12"
            )
        marker = json.loads((args["state"] / "pending-market-run.json").read_bytes())
        run = args["state"] / marker["run"]
        result = json.loads((run / "stopped.json").read_bytes())
        assert "refresh" not in events and not (run / "completed.json").exists()
    else:
        result = market.cycle(
            **args, apply_drafts=True, publish_online_store="gid://shopify/Publication/12"
        )
        run = args["state"] / result["run"]
        assert events[-2:] == ["publication", "refresh"]
        assert events.count("source") == events.count("refresh") == 1
    assert result["published"] is True and result["publication"]["published"] == 2
    receipt = json.loads((run / "publication.json").read_bytes())
    assert receipt["published"] == 2 and result["publicationState"] == receipt["status"]
