"""Adversarial local inputs for the importer scripts; no remote requests."""

import json
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts import capture_import_identities as identities
from scripts import import_cardtrader_drafts as importer
from scripts import publish_imported_drafts as publication
from scripts import refresh_market_catalog as market

import test_capture_import_identities as identity_tests
import test_import_cardtrader_drafts as import_tests
import test_market_input_retention as retention_tests
import test_refresh_market_catalog as market_tests
from test_capture_import_identities import SHOP, complete

identity_case = identity_tests.setup
import_case = import_tests.setup
history = retention_tests.history
identity_batches = retention_tests.identity_batches
market_case = market_tests.setup


def write_json(path, value):
    path.write_text(json.dumps(value))


@pytest.mark.parametrize("success_at", [1, 2, 3, None, "non_retryable"])
def test_identity_retry_always_returns_or_raises_within_three_reads(
    identity_case, monkeypatch, success_at
):
    client, work = identity_case
    complete(client, work)
    calls, pauses = [], []

    def read(*args):
        calls.append(1)
        if len(calls) == success_at:
            return True
        raise ValueError(
            "identity_definition_changed"
            if success_at == "non_retryable"
            else "inconsistent_identity_page"
        )

    monkeypatch.setattr(identities, "_live_missing", read)
    monkeypatch.setattr(identities.time, "sleep", pauses.append)
    if isinstance(success_at, int):
        assert identities.verify_missing(work, SHOP, 42, client.graphql) is True
        attempts = success_at
    else:
        reason = (
            "identity_definition_changed"
            if success_at == "non_retryable"
            else "inconsistent_identity_page"
        )
        with pytest.raises(ValueError, match=reason):
            identities.verify_missing(work, SHOP, 42, client.graphql)
        attempts = 1 if success_at == "non_retryable" else 3
    assert len(calls) == attempts and pauses == [2] * (attempts - 1)


@pytest.mark.parametrize("case", ["timezone", "count", "hash", "capture_times"])
def test_identity_inputs_reject_unverifiable_receipts(identity_case, case):
    client, work = identity_case
    if case == "timezone":
        with pytest.raises(ValueError, match="identity_timestamp_timezone_required"):
            identities.timestamp("2026-09-28T00:00:00")
        return
    receipt = complete(client, work)
    if case == "capture_times":
        receipt["completedAt"] = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        write_json(work / "completed.json", receipt)
        with pytest.raises(ValueError, match="invalid_identity_capture_times"):
            identities.read_fresh_identities(work, SHOP)
    else:
        with pytest.raises(
            ValueError,
            match="invalid_identity_file" if case == "count" else "identity_hash_or_count_mismatch",
        ):
            identities.scan_identities(
                work / "identities.jsonl", "0" * 64, 0 if case == "count" else 1
            )


@pytest.mark.parametrize("case", ["linked", "changed_during_scan"])
def test_identity_guard_does_not_accept_changed_baseline(identity_case, monkeypatch, case):
    client, work = identity_case
    complete(client, work)
    if case == "linked":
        original = Path.lstat

        def facts(path, *args, **kwargs):
            found = original(path, *args, **kwargs)
            if path == work / "completed.json":
                return SimpleNamespace(st_mode=found.st_mode, st_nlink=2)
            return found

        monkeypatch.setattr(Path, "lstat", facts)
    else:
        original = identities.read_fresh_identities

        def changed(*args):
            result = original(*args)
            path = work / "completed.json"
            path.write_bytes(path.read_bytes() + b" ")
            return result

        monkeypatch.setattr(identities, "read_fresh_identities", changed)
    before = len(client.calls)
    with pytest.raises(ValueError, match="identity_snapshot_changed"):
        identities.missing_guard(work, SHOP, client.graphql)
    assert len(client.calls) == before


@pytest.mark.parametrize("entry", ["standalone", "live"])
def test_invalid_identity_never_reaches_graphql(identity_case, entry):
    client, work = identity_case
    with pytest.raises(ValueError, match="invalid_cardmarket_id"):
        if entry == "standalone":
            identities.verify_missing(work, SHOP, True, client.graphql)
        else:
            identities._live_missing({}, set(), SHOP, 0, client.graphql)
    assert client.calls == []


def test_live_identity_check_rejects_baseline_expiring_during_request(identity_case, monkeypatch):
    client, work = identity_case
    complete(client, work)
    original = client.graphql

    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) + timedelta(seconds=1801)

    def graphql(query, variables):
        result = original(query, variables)
        if query == identities.FIND_ATTEMPT_HANDLE:
            monkeypatch.setattr(identities, "datetime", Later)
        return result

    with pytest.raises(ValueError, match="identity_export_stale"):
        identities.verify_missing(work, SHOP, 42, graphql)


@pytest.mark.parametrize(
    "case", ["relative", "file", "private", "not_empty", "count", "start", "intent", "operation"]
)
def test_capture_refuses_invalid_paths_or_operation_evidence(identity_case, monkeypatch, case):
    client, work = identity_case
    reason = {
        "relative": "canonical_absolute_directory_required",
        "file": "identity_directory_required",
        "private": "identity_directory_not_private",
        "not_empty": "identity_directory_not_empty",
        "count": "identity_count_unconfirmed",
        "start": "identity_start_unconfirmed",
        "intent": "identity_intent_mismatch",
        "operation": "identity_operation_mismatch",
    }[case]
    if case == "relative":
        work = Path("relative")
    elif case == "file":
        work.touch()
    elif case == "not_empty":
        work.mkdir(mode=0o700)
        (work / "unaccounted.json").write_text("{}")
    elif case == "private":
        work.mkdir()
        monkeypatch.setattr(identities, "os", SimpleNamespace(name="posix", geteuid=lambda: -1))
    elif case == "count":
        client.count = 0
    elif case in ("intent", "operation"):
        identities.capture_once(client, SHOP, work)
        if case == "intent":
            path = work / "intent.json"
            value = json.loads(path.read_bytes())
            value["shop"] = "other.myshopify.com"
            write_json(path, value)
        else:
            original = client.graphql

            def wrong_operation(query, variables):
                result = original(query, variables)
                if query == identities.CONTROLS["status"]:
                    result["bulkOperation"]["query"] = "different query"
                return result

            client.graphql = wrong_operation
    else:
        original = client.graphql

        def invalid_start(query, variables):
            result = original(query, variables)
            if query == identities.CONTROLS["start"]:
                result["bulkOperationRunQuery"]["bulkOperation"]["id"] = "bad"
            return result

        client.graphql = invalid_start
    with pytest.raises(ValueError, match=reason):
        identities.capture_once(client, SHOP, work)
    assert client.calls.count(identities.CONTROLS["start"]) <= 1


@pytest.mark.parametrize("case", ["fields", "relative"])
def test_import_configuration_is_exact_and_canonical(import_case, case):
    args, original, _, _ = import_case
    if case == "fields":
        original["unexpected"] = True
    else:
        original["run_root"] = "relative"
    write_json(args["config_path"], original)
    with pytest.raises(
        ValueError,
        match="unexpected_refresh_configuration"
        if case == "fields"
        else "noncanonical_refresh_path",
    ):
        importer.config_values(args["config_path"])


def test_durable_reference_refuses_symlink(import_case, monkeypatch):
    args, _, _, _ = import_case
    original = Path.is_symlink
    target = args["capture"] / "progress.json"
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == target or original(path))
    with pytest.raises(ValueError, match="reference_symlink"):
        importer.durable_tree(args["capture"])


@pytest.mark.parametrize(
    "case",
    [
        "sha",
        "path",
        "ledger_type",
        "ledger_private",
        "generation",
        "config_changed",
        "stale_source",
        "deferred_outcome",
    ],
)
def test_import_boundary_failures_never_allow_creation(import_case, monkeypatch, case):
    args, original_config, api, _ = import_case
    expected = {
        "sha": "invalid_generator_sha",
        "path": "canonical_absolute_paths_required",
        "ledger_type": "existing_regular_ledger_required",
        "ledger_private": "private_existing_ledger_required",
        "generation": "invalid_current_generation",
        "config_changed": "refresh_configuration_changed",
    }
    if case == "sha":
        args["generator_sha"] = "bad"
    elif case == "path":
        args["identity_run"] = Path("relative")
    elif case in ("ledger_type", "ledger_private"):
        original = Path.lstat

        def facts(path, *a, **kw):
            if path == args["ledger"]:
                return SimpleNamespace(
                    st_mode=(stat.S_IFDIR if case == "ledger_type" else stat.S_IFREG) | 0o600,
                    st_nlink=1,
                    st_uid=1,
                )
            return original(path, *a, **kw)

        monkeypatch.setattr(Path, "lstat", facts)
        if case == "ledger_private":
            monkeypatch.setattr(importer, "os", SimpleNamespace(name="posix"))
    elif case == "generation":
        write_json(
            Path(original_config["run_root"]) / "last-success.json", dict(manifestSha256="bad")
        )
    elif case == "config_changed":
        original = importer.refresh.document
        reads = []

        def changed(path):
            result = original(path)
            if path == args["config_path"]:
                reads.append(1)
                if len(reads) > 1:
                    result["unexpected"] = True
            return result

        monkeypatch.setattr(importer.refresh, "document", changed)
    elif case == "stale_source":
        monkeypatch.setattr(
            importer.identities, "timestamp", lambda _: datetime.now(UTC) - timedelta(hours=25)
        )
    else:

        def fail(*args):
            raise ValueError("inconsistent_identity_page")

        def inconsistent_outcome(*args, **kwargs):
            assert kwargs["verify_missing"]() is False
            return dict(status="draft_verified")

        monkeypatch.setattr(importer.identities, "verify_missing", fail)
        monkeypatch.setattr(importer, "create_draft_once", inconsistent_outcome)
    if case in expected:
        with pytest.raises(ValueError, match=expected[case]):
            importer.run_locked(**args, apply=True)
    else:
        result = importer.run_locked(**args, apply=True)
        assert result["status"] == "stopped_inspect_before_retry"
        assert result["failure"]["reason"] == (
            "source_stale_or_reference_not_selected"
            if case == "stale_source"
            else "unexpected_batch_error"
        )
    assert all(not query.lstrip().startswith("mutation") for query, _ in api.calls)


def test_publication_requires_distinct_locks(tmp_path, monkeypatch):
    monkeypatch.setattr(publication, "validate_ledger", lambda _: None)
    monkeypatch.setattr(
        publication.drafts, "config_values", lambda _: ({}, dict(run_root=tmp_path))
    )
    with pytest.raises(ValueError, match="importer_and_refresh_locks_must_be_separate"):
        publication.run(tmp_path / "config", tmp_path / "ledger", "unused", apply=True)


def test_retention_requires_existing_canonical_run(tmp_path):
    with pytest.raises(ValueError, match="noncanonical_retention_run"):
        market.prune_batch_identities(tmp_path / "missing", 3)


def test_identity_payload_changed_after_expiry_intent_is_retained(identity_batches, monkeypatch):
    payload = identity_batches / "identities/identities.jsonl"
    original = market.refresh.publish

    def changed(path, *args, **kwargs):
        original(path, *args, **kwargs)
        payload.write_bytes(payload.read_bytes() + b" ")

    monkeypatch.setattr(market.refresh, "publish", changed)
    with pytest.raises(ValueError, match="expired_market_input_changed"):
        market.prune_batch_identities(identity_batches, 3)
    assert payload.exists()


@pytest.mark.parametrize(
    "case", ["missing_state", "noncanonical_run", "changed_input", "short_history"]
)
def test_history_retention_boundaries_preserve_inputs(history, monkeypatch, case):
    state, config, _, runs = history
    if case == "missing_state":
        with pytest.raises(ValueError, match="noncanonical_retention_state"):
            market.prune_completed_inputs(state / "missing", config)
    elif case == "short_history":
        empty = state / "empty-history"
        empty.mkdir()
        assert market.prune_completed_inputs(empty, config) == 0
    elif case == "noncanonical_run":
        original = Path.resolve
        monkeypatch.setattr(
            Path,
            "resolve",
            lambda path, *a, **kw: state if path == runs[0] else original(path, *a, **kw),
        )
        with pytest.raises(ValueError, match="market_run_requires_inspection_before_retention"):
            market.prune_completed_inputs(state, config)
    else:
        original = market.input_facts

        def changed(path, root):
            facts = original(path, root)
            path.write_bytes(path.read_bytes() + b" ")
            return facts

        monkeypatch.setattr(market, "input_facts", changed)
        with pytest.raises(ValueError, match="expired_market_input_changed"):
            market.prune_completed_inputs(state, config)
    assert all((run / "source/blueprints-12.json").exists() for run in runs)


def test_refresh_requires_canonical_package(tmp_path):
    with pytest.raises(ValueError, match="canonical_refresh_package_required"):
        market.refresh_index(Path("relative"), tmp_path / "config")


@pytest.mark.parametrize(
    "case",
    ["relative", "pending_before_identity", "pending_before_publication", "stale_after_refresh"],
)
def test_cycle_boundaries_keep_pending_and_block_unsafe_next_stage(market_case, monkeypatch, case):
    args, events, _ = market_case
    pending = args["state"] / "refresh-runs/pending-run.json"
    if case == "relative":
        args["refresh_package"] = Path("relative")
        reason = "canonical_cycle_paths_required"
    elif case == "pending_before_identity":
        original = market.capture_catalog

        def source(*a, **kw):
            result = original(*a, **kw)
            pending.touch()
            return result

        monkeypatch.setattr(market, "capture_catalog", source)
        reason = "catalog_refresh_pending"
    elif case == "pending_before_publication":
        original = market.drafts.run_locked

        def batch(*a, **kw):
            result = original(*a, **kw)
            pending.touch()
            return result

        monkeypatch.setattr(market.drafts, "run_locked", batch)
        args["publish_online_store"] = "gid://shopify/Publication/12"
        reason = "catalog_refresh_pending"
    else:
        monkeypatch.setattr(market.refresh, "freshness", lambda _: dict(status="stale"))
        reason = "post_import_index_not_fresh"
    with pytest.raises(ValueError, match=reason):
        market.cycle(**args, apply_drafts=True)
    assert "publication" not in events
    assert ("refresh" in events) is (case == "stale_after_refresh")
    assert (args["state"] / "pending-market-run.json").exists() is (case != "relative")
