import hashlib
import json
import os
from pathlib import Path

import pytest
from scripts import refresh_market_catalog as market


@pytest.fixture
def history(tmp_path, monkeypatch):
    state = tmp_path / "importer"
    state.mkdir()
    refresh_root = tmp_path / "refresh"
    refresh_root.mkdir()
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"reference": str(tmp_path / "external-reference")}))
    monkeypatch.setattr(market.activation, "sync_directory", lambda _: None)
    # File selection/deletion is portable; root/0600 reading is covered by the
    # existing Linux operator tests, not Windows permission emulation.
    monkeypatch.setattr(market.refresh, "document", lambda path: json.loads(path.read_bytes()))

    def config(path):
        raw = json.loads(path.read_text())
        return raw, dict(reference=type(path)(raw["reference"]), run_root=refresh_root)

    monkeypatch.setattr(market.drafts, "config_values", config)
    runs = []
    for i in range(6):
        run = state / f"market-2026092{i}t000000z-12345678"
        run.mkdir()
        (run / "completed.json").write_text(
            json.dumps(dict(run=run.name, status="draft_cycle_complete"))
        )
        for name in (
            "source/blueprints-12.json",
            "source/progress.json",
            "source/anomalies-12.json",
            "identities/identities.jsonl",
            "identities/completed.json",
            "batch/ledger-after.sqlite3",
            "batch/reference/bundle/canonical-names.v1.jsonl",
            "batch/reference/bundle/canonical-names-manifest.v1.json",
            "batch/reference/preparation.json",
            "batch/result.json",
        ):
            path = run / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("retained fixture")
        runs.append(run)
    (state / "draft-attempts.sqlite3").write_text("persistent ledger")
    manual = state / "manual-pilot"
    manual.mkdir()
    (manual / "identities.jsonl").write_text("manual evidence")
    return state, config_path, refresh_root, runs


def test_only_old_raw_inputs_removed_receipts_and_ledger_survive(history):
    state, config, _, runs = history
    assert market.prune_completed_inputs(state, config) == 16
    for run in runs[:4]:
        assert not (run / "source/blueprints-12.json").exists()
        assert not (run / "identities/identities.jsonl").exists()
        assert not (run / "batch/ledger-after.sqlite3").exists()
        assert not (run / "batch/reference/bundle/canonical-names.v1.jsonl").exists()
        assert (run / "source/progress.json").exists()
        assert (run / "source/anomalies-12.json").exists()
        assert (run / "batch/reference/preparation.json").exists()
        assert (run / "batch/reference/bundle/canonical-names-manifest.v1.json").exists()
        assert json.loads((run / "pruned-inputs.json").read_bytes())["files"] == 4
    for run in runs[-2:]:
        assert (run / "source/blueprints-12.json").exists()
    assert (state / "draft-attempts.sqlite3").read_text() == "persistent ledger"
    assert (state / "manual-pilot/identities.jsonl").exists()
    assert market.prune_completed_inputs(state, config) == 0


def test_active_reference_and_before_reference_preserved(history):
    state, config, _, runs = history
    config.write_text(json.dumps({"reference": str(runs[1] / "batch/reference/bundle")}))
    (runs[1] / "batch/refresh-config.before.json").write_text(
        json.dumps({"reference": str(runs[0] / "batch/reference/bundle")})
    )
    assert market.prune_completed_inputs(state, config) == 8
    for i in (0, 1, 4, 5):
        assert (runs[i] / "batch/reference/bundle/canonical-names.v1.jsonl").exists()
    for i in (2, 3):
        assert not (runs[i] / "source/blueprints-12.json").exists()


@pytest.mark.parametrize("blocked", ["market", "refresh", "incomplete", "bad_receipt"])
def test_unfinished_or_invalid_state_prevents_deletion(history, blocked):
    state, config, refresh_root, runs = history
    if blocked == "market":
        (state / "pending-market-run.json").write_text("{}")
    elif blocked == "refresh":
        (refresh_root / "pending-run.json").write_text("{}")
    elif blocked == "incomplete":
        (runs[0] / "completed.json").unlink()
    else:
        (runs[0] / "completed.json").write_text('{"run":"wrong","status":"ready"}')
    with pytest.raises(ValueError):
        market.prune_completed_inputs(state, config)
    assert all((r / "source/blueprints-12.json").exists() for r in runs)


def test_linked_input_is_not_deleted(history):
    state, config, _, runs = history
    target = runs[0] / "identities/identities.jsonl"
    os.link(target, state / "other-owner-copy")
    with pytest.raises(ValueError, match="unsafe_expired_market_input"):
        market.prune_completed_inputs(state, config)
    assert (runs[0] / "source/blueprints-12.json").exists()
    assert target.exists()


def test_configuration_change_stops_before_removal(history, monkeypatch):
    state, config, _, runs = history
    document = market.refresh.document
    monkeypatch.setattr(
        market.refresh,
        "document",
        lambda p: {"reference": "changed"} if p == config else document(p),
    )
    with pytest.raises(ValueError, match="configuration_changed"):
        market.prune_completed_inputs(state, config)
    assert all((r / "source/blueprints-12.json").exists() for r in runs)


def test_numbered_batches_and_partial_cycles_obey_reference_protection(history):
    state, config, _, runs = history
    for run in runs:
        batch, identity = market.batch_paths(run, 2)
        for path in (
            identity / "identities.jsonl",
            batch / "ledger-after.sqlite3",
            batch / "reference/bundle/canonical-names.v1.jsonl",
        ):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("numbered payload")
        (batch / "result.json").write_text('{"status":"batch_complete"}')
    config.write_text(json.dumps({"reference": str(runs[1] / "batch-0002/reference/bundle")}))
    (runs[1] / "batch-0002/refresh-config.before.json").write_text(
        json.dumps({"reference": str(runs[0] / "batch-0002/reference/bundle")})
    )
    (runs[2] / "completed.json").write_text(
        json.dumps(dict(run=runs[2].name, status="draft_cycle_partial"))
    )
    market.prune_completed_inputs(state, config)
    for index in (0, 1, 4, 5):
        assert (runs[index] / "identities-0002/identities.jsonl").exists()
        assert (runs[index] / "batch-0002/reference/bundle/canonical-names.v1.jsonl").exists()
    for index in (2, 3):
        assert not (runs[index] / "identities-0002/identities.jsonl").exists()
        assert not (runs[index] / "batch-0002/ledger-after.sqlite3").exists()
        assert not (runs[index] / "batch-0002/reference/bundle/canonical-names.v1.jsonl").exists()
        assert (runs[index] / "batch-0002/result.json").exists()
    assert market.prune_completed_inputs(state, config) == 0


@pytest.fixture
def identity_batches(tmp_path, monkeypatch):
    monkeypatch.setattr(market.activation, "sync_directory", lambda _: None)
    monkeypatch.setattr(market.refresh, "document", lambda path: json.loads(path.read_bytes()))
    payload = b'{"id":"gid://shopify/Product/1"}\n'
    for number in range(1, 5):
        batch, identity = market.batch_paths(tmp_path, number)
        batch.mkdir()
        identity.mkdir()
        (identity / "identities.jsonl").write_bytes(payload)
        (identity / "completed.json").write_text(
            json.dumps(
                dict(
                    status="complete",
                    shopifyChanged=False,
                    sha256=hashlib.sha256(payload).hexdigest(),
                )
            )
        )
        (batch / "result.json").write_text('{"status":"batch_complete"}')
        (batch / "ledger-after.sqlite3").write_text("retained backup")
    return tmp_path


def test_in_cycle_retention_keeps_latest_two_payloads_and_all_receipts(identity_batches):
    run = identity_batches
    market.prune_batch_identities(run, 2)
    assert (run / "identities/identities.jsonl").exists()
    market.prune_batch_identities(run, 3)
    assert not (run / "identities/identities.jsonl").exists()
    assert (run / "identities-0002/identities.jsonl").exists()
    market.prune_batch_identities(run, 4)
    market.prune_batch_identities(run, 4)  # Missing expired payloads are idempotent.
    for number in range(1, 5):
        batch, identity = market.batch_paths(run, number)
        assert (identity / "identities.jsonl").exists() is (number > 2)
        assert (identity / "completed.json").exists()
        assert (batch / "result.json").exists()
        assert (batch / "ledger-after.sqlite3").exists()
        assert (identity / "payload-expiry.json").exists() is (number <= 2)


@pytest.mark.parametrize("unsafe", ["hash", "uncertain", "hardlink"])
def test_in_cycle_retention_rejects_unsafe_or_uncertain_input(identity_batches, unsafe):
    run = identity_batches
    payload = run / "identities/identities.jsonl"
    if unsafe == "hash":
        payload.write_text("changed")
    elif unsafe == "uncertain":
        (run / "batch/result.json").write_text('{"status":"needs_reconciliation"}')
    else:
        os.link(payload, run / "other-copy")
    with pytest.raises(ValueError):
        market.prune_batch_identities(run, 3)
    assert payload.exists()


def test_in_cycle_retention_intent_precedes_interrupted_unlink(identity_batches, monkeypatch):
    run = identity_batches
    original = Path.unlink

    def interrupted(path, *args, **kwargs):
        if path.name == "identities.jsonl":
            assert (path.parent / "payload-expiry.json").exists()
            raise KeyboardInterrupt
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", interrupted)
    with pytest.raises(KeyboardInterrupt):
        market.prune_batch_identities(run, 3)
    assert (run / "identities/identities.jsonl").exists()
    monkeypatch.setattr(Path, "unlink", original)
    market.prune_batch_identities(run, 3)
    assert not (run / "identities/identities.jsonl").exists()
