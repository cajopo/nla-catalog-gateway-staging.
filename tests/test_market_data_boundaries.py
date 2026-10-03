"""Recovered source safety boundaries from the original importer review tests."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts import capture_import_identities as identities

import test_capture_import_identities as identity_tests
from test_capture_import_identities import SHOP, complete

identity_case = identity_tests.setup


def write_json(path, value):
    path.write_text(json.dumps(value))


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


def test_invalid_identity_never_reaches_graphql(identity_case):
    client, work = identity_case
    with pytest.raises(ValueError, match="invalid_cardmarket_id"):
        identities.verify_missing(work, SHOP, True, client.graphql)
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
