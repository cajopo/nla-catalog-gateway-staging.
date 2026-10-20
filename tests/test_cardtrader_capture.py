import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from nla_catalog_gateway import cardtrader_capture as capture
from nla_catalog_gateway.cardtrader_catalog import CardTraderCatalogError


class Source:
    def __init__(self):
        self.calls = []
        self.games = [{"id": i} for i in (1, 4, 5, 15)]
        self.expansions = [{"id": i, "game_id": i} for i in (15, 5, 4, 1)]
        self.categories = [{"id": i, "game_id": i, "name": f"Game{i}"} for i in (1, 4, 5, 15)]
        self.rows = {
            i: [
                {
                    "id": i * 10,
                    "game_id": i,
                    "expansion_id": i,
                    "category_id": i,
                    "card_market_ids": [i * 100],
                }
            ]
            for i in (1, 4, 5, 15)
        }

    def collection(self, kind, **kwargs):
        self.calls.append((kind, kwargs))
        if kind == "games":
            return deepcopy(self.games)
        if kind == "categories":
            return deepcopy(self.categories)
        if kind == "expansions":
            return deepcopy(self.expansions)
        return deepcopy(self.rows[kwargs["expansion_id"]])


@pytest.fixture(autouse=True)
def no_wait(monkeypatch):
    monkeypatch.setattr(capture.time, "sleep", lambda _: None)
    monkeypatch.setattr(capture.shutil, "disk_usage", lambda _: SimpleNamespace(free=8 * 1024**3))


def test_complete_all_expansions_with_hashes_and_no_overwrite(tmp_path):
    api = Source()
    root = tmp_path / "run"
    result = capture.capture_catalog(api, root)
    assert result["status"] == "complete" and result["completedExpansions"] == 4
    assert result["blueprints"] == 4 and result["sourceAnomalyCount"] == 0
    assert result["automaticImportEnabled"] is False and result["shopifyChanged"] is False
    assert [kw["expansion_id"] for kind, kw in api.calls if kind == "blueprints"] == [1, 4, 5, 15]
    for name, facts in result["files"].items():
        data = (root / name).read_bytes()
        assert len(data) == facts["bytes"] and hashlib.sha256(data).hexdigest() == facts["sha256"]
    before = (root / "progress.json").read_bytes()
    assert json.loads(before) == result
    with pytest.raises(FileExistsError):
        capture.capture_catalog(api, root)
    assert (root / "progress.json").read_bytes() == before


def test_export_anomaly_preserved_not_repaired_or_discarded(tmp_path):
    api = Source()
    api.rows[1][0]["game_id"] = 5
    api.rows[4][0].update(id="unknown", expansion_id=True)
    root = tmp_path / "run"
    result = capture.capture_catalog(api, root)
    assert result["status"] == "complete_with_source_anomalies"
    assert result["sourceAnomalyCount"] == 2 and result["blueprints"] == 4
    assert json.loads((root / "blueprints-1.json").read_bytes()) == api.rows[1]
    assert json.loads((root / "anomalies-4.json").read_bytes())[0]["blueprintId"] is None


@pytest.mark.parametrize(
    "case", ["games", "duplicate", "invalid_id", "missing_game", "empty", "too_many"]
)
def test_invalid_catalog_cannot_complete(tmp_path, case):
    api = Source()
    root = tmp_path / "run"
    if case == "games":
        api.games = []
    if case == "duplicate":
        api.expansions.append(api.expansions[0])
    if case == "invalid_id":
        api.expansions[0]["id"] = True
    if case == "missing_game":
        api.expansions.pop()
    if case == "empty":
        api.expansions = []
    if case == "too_many":
        api.expansions = [api.expansions[0]] * 10001
    with pytest.raises(RuntimeError, match="catalog_capture_failed"):
        capture.capture_catalog(api, root)
    assert json.loads((root / "progress.json").read_bytes())["status"] == "failed"
    assert not any(kind == "blueprints" for kind, _ in api.calls)


@pytest.mark.parametrize(
    "case", ["network", "byte_limit", "disk_limit", "deadline_before", "deadline_after"]
)
def test_failed_capture_retains_evidence_without_secret_in_progress(tmp_path, monkeypatch, case):
    api = Source()
    root = tmp_path / "run"
    if case == "network":
        original = api.collection

        def get(kind, **kwargs):
            if kind == "blueprints" and kwargs["expansion_id"] == 4:
                raise CardTraderCatalogError("request_failed", 429)
            return original(kind, **kwargs)

        api.collection = get
    if case == "byte_limit":
        monkeypatch.setattr(capture, "MAX_BYTES", 1)
    if case == "disk_limit":
        monkeypatch.setattr(capture.shutil, "disk_usage", lambda _: SimpleNamespace(free=1))
    if case.startswith("deadline"):
        ticks = iter(
            [0, capture.MAX_SECONDS] if case.endswith("before") else [0, 0, capture.MAX_SECONDS]
        )
        monkeypatch.setattr(capture.time, "monotonic", lambda: next(ticks))
    with pytest.raises(RuntimeError, match="catalog_capture_failed"):
        capture.capture_catalog(api, root)
    encoded = (root / "progress.json").read_text()
    result = json.loads(encoded)
    assert result["status"] == "failed" and "secret-token-test" not in encoded
    if case == "network":
        assert result["completedExpansions"] == 1 and result["httpStatus"] == 429
        assert result["failure"] == dict(
            reason="request_failed",
            catalogKind="blueprints",
            expansionId=4,
            attempts=3,
            retries=2,
            httpStatus=429,
        )
        assert result["requestRetries"] == 2
        assert (root / "blueprints-1.json").exists()


@pytest.mark.parametrize(
    ("reason", "http_status"),
    [("request_failed", status) for status in (None, 408, 429, 500, 502, 503, 504)]
    + [("unexpected_status", 503)],
)
def test_transient_source_failures_retry_then_complete_with_bounded_backoff(
    tmp_path, monkeypatch, reason, http_status
):
    api = Source()
    original = api.collection
    failures = 0
    sleeps = []

    def collection(kind, **kwargs):
        nonlocal failures
        if kind == "blueprints" and kwargs["expansion_id"] == 1 and failures < 2:
            failures += 1
            raise CardTraderCatalogError(reason, http_status)
        return original(kind, **kwargs)

    api.collection = collection
    monkeypatch.setattr(capture.time, "sleep", sleeps.append)
    result = capture.capture_catalog(api, tmp_path / "run")
    encoded = (tmp_path / "run" / "progress.json").read_text()
    assert result["status"] == "complete"
    assert result["requestRetries"] == 2
    assert result["requestAttempts"] == 9
    assert sleeps.count(2) == 1 and sleeps.count(5) == 1
    assert "failure" not in result
    assert "secret URL and token" not in encoded


@pytest.mark.parametrize(
    ("reason", "http_status", "safe_reason"),
    [
        ("secret response body", 401, "catalog_request_failed"),
        ("request_failed", 401, "request_failed"),
        ("request_failed", 403, "request_failed"),
        ("invalid_json", None, "invalid_json"),
        ("invalid_collection", None, "invalid_collection"),
        ("response_too_large", None, "response_too_large"),
        ([], "secret response body", "catalog_request_failed"),
        ("request_failed", True, "request_failed"),
    ],
)
def test_permanent_request_failure_is_not_retried_and_has_sanitized_receipt(
    tmp_path, reason, http_status, safe_reason
):
    api = Source()
    original = api.collection
    calls = 0

    def collection(kind, **kwargs):
        nonlocal calls
        if kind == "blueprints" and kwargs["expansion_id"] == 1:
            calls += 1
            raise CardTraderCatalogError(reason, http_status)
        return original(kind, **kwargs)

    api.collection = collection
    with pytest.raises(RuntimeError, match="catalog_capture_failed"):
        capture.capture_catalog(api, tmp_path / "run")
    encoded = (tmp_path / "run" / "progress.json").read_text()
    result = json.loads(encoded)
    assert calls == 1
    assert result["failure"] == dict(
        reason=safe_reason,
        catalogKind="blueprints",
        expansionId=1,
        attempts=1,
        retries=0,
        httpStatus=http_status if type(http_status) is int else None,
    )
    assert "secret response body" not in encoded


def test_retry_backoff_cannot_cross_capture_deadline(tmp_path, monkeypatch):
    api = Source()
    original = api.collection
    calls = 0
    elapsed = 0

    def collection(kind, **kwargs):
        nonlocal calls
        if kind == "blueprints" and kwargs["expansion_id"] == 1:
            calls += 1
            raise CardTraderCatalogError("request_failed", None)
        return original(kind, **kwargs)

    def sleep(seconds):
        nonlocal elapsed
        elapsed += seconds

    api.collection = collection
    monkeypatch.setattr(capture, "MAX_SECONDS", 5)
    monkeypatch.setattr(capture.time, "monotonic", lambda: elapsed)
    monkeypatch.setattr(capture.time, "sleep", sleep)
    with pytest.raises(RuntimeError, match="catalog_capture_failed"):
        capture.capture_catalog(api, tmp_path / "run")
    result = json.loads((tmp_path / "run" / "progress.json").read_text())
    assert calls == 1
    assert result["failure"] == dict(
        reason="capture_deadline",
        catalogKind="blueprints",
        expansionId=1,
        attempts=1,
        retries=0,
        httpStatus=None,
    )


@pytest.mark.parametrize("stage", ["failed_request", "retry_pacing", "successful_retry"])
def test_deadline_receipt_identifies_current_request_and_attempt(tmp_path, monkeypatch, stage):
    api = Source()
    original = api.collection
    elapsed = 0
    calls = 0

    def sleep(seconds):
        nonlocal elapsed
        elapsed += seconds

    def collection(kind, **kwargs):
        nonlocal calls, elapsed
        if kind == "blueprints" and kwargs["expansion_id"] == 1:
            calls += 1
            if calls == 1:
                if stage == "failed_request":
                    elapsed = 9
                raise CardTraderCatalogError("request_failed", 503)
            elapsed = 9
        return original(kind, **kwargs)

    api.collection = collection
    monkeypatch.setattr(capture, "time", SimpleNamespace(monotonic=lambda: elapsed, sleep=sleep))
    monkeypatch.setattr(capture, "MAX_SECONDS", 7 if stage == "retry_pacing" else 9)
    with pytest.raises(RuntimeError, match="catalog_capture_failed"):
        capture.capture_catalog(api, tmp_path / "run")
    result = json.loads((tmp_path / "run" / "progress.json").read_bytes())
    attempts = 2 if stage == "successful_retry" else 1
    assert calls == attempts
    assert result["failure"] == dict(
        reason="capture_deadline",
        catalogKind="blueprints",
        expansionId=1,
        attempts=attempts,
        retries=attempts - 1,
        httpStatus=None if stage == "successful_retry" else 503,
    )
    assert result["status"] == "failed"
    assert not (tmp_path / "run" / "blueprints-1.json").exists()


def test_successful_first_request_crossing_deadline_keeps_request_context(tmp_path, monkeypatch):
    elapsed = 0

    class SlowSource:
        def collection(self, kind, **kwargs):
            nonlocal elapsed
            elapsed = capture.MAX_SECONDS
            return []

    monkeypatch.setattr(
        capture, "time", SimpleNamespace(monotonic=lambda: elapsed, sleep=lambda _: None)
    )
    with pytest.raises(RuntimeError, match="catalog_capture_failed"):
        capture.capture_catalog(SlowSource(), tmp_path / "run")
    result = json.loads((tmp_path / "run" / "progress.json").read_bytes())
    assert result["failure"] == dict(
        reason="capture_deadline",
        catalogKind="games",
        expansionId=None,
        attempts=1,
        retries=0,
        httpStatus=None,
    )


def test_absolute_new_directory_required():
    with pytest.raises(ValueError, match="absolute_capture_directory_required"):
        capture.capture_catalog(Source(), Path("relative"))


class DeferredSource(Source):
    def __init__(self, unavailable):
        super().__init__()
        self.unavailable = unavailable

    def collection(self, kind, **kwargs):
        rows = super().collection(kind, **kwargs)
        if kind == "blueprints" and kwargs["expansion_id"] in self.unavailable:
            raise CardTraderCatalogError("private upstream message", 404)
        return rows


@pytest.mark.parametrize("expires_at", ["request", "deferral"])
def test_final_export_404_cannot_bypass_capture_deadline(tmp_path, monkeypatch, expires_at):
    api = DeferredSource({15})
    final_checks = 0

    def clock():
        nonlocal final_checks
        if len(api.calls) == 7:
            final_checks += 1
            if expires_at == "request" or final_checks > 1:
                return capture.MAX_SECONDS
        return 0

    monkeypatch.setattr(capture, "time", SimpleNamespace(monotonic=clock, sleep=lambda _: None))
    with pytest.raises(RuntimeError, match="catalog_capture_failed"):
        capture.capture_catalog(api, tmp_path / "run")
    result = json.loads((tmp_path / "run/progress.json").read_bytes())
    assert result["status"] == "failed" and result["errorType"] == "ValueError"
    assert result["completedExpansions"] == 3 and result["deferredExpansions"] == []


@pytest.mark.parametrize("unavailable", [{4}, {1, 4, 5, 15}])
def test_export_404_accounted_without_empty_files_and_retried_next_cycle(tmp_path, unavailable):
    api = DeferredSource(unavailable)
    root = tmp_path / "first"
    result = capture.capture_catalog(api, root)
    assert result["status"] == "partial_with_deferred_expansions"
    assert result["completedExpansions"] == 4 - len(unavailable)
    assert result["totalExpansions"] == 4
    assert result["blueprints"] == 4 - len(unavailable)
    expected = [
        dict(expansionId=i, httpStatus=404, reason="export_http_404") for i in sorted(unavailable)
    ]
    assert result["deferredExpansions"] == expected
    assert all(not (root / f"blueprints-{i}.json").exists() for i in unavailable)
    assert "private upstream message" not in (root / "progress.json").read_text()
    assert [kw["expansion_id"] for kind, kw in api.calls if kind == "blueprints"] == [1, 4, 5, 15]
    mapping = {i: (i, f"Game{i}", "single") for i in (1, 4, 5, 15)}
    report = capture.compare_captured_catalog(root, [], mapping)
    assert report["sourceComplete"] is False and report["deferredExpansions"] == expected
    assert report["sourceRows"] == 4 - len(unavailable)
    assert {r["sourceExpansionId"] for r in report["details"]} == {1, 4, 5, 15} - unavailable
    api.unavailable = set()
    api.calls.clear()
    again = capture.capture_catalog(api, tmp_path / "next")
    assert again["status"] == "complete" and again["completedExpansions"] == 4
    assert [kw["expansion_id"] for kind, kw in api.calls if kind == "blueprints"] == [1, 4, 5, 15]


def test_deferred_export_preserves_anomaly_quarantine(tmp_path):
    api = DeferredSource({4})
    api.rows[5][0]["game_id"] = 1
    root = tmp_path / "run"
    result = capture.capture_catalog(api, root)
    assert result["sourceAnomalyCount"] == 1
    report = capture.compare_captured_catalog(
        root, [], {i: (i, f"Game{i}", "single") for i in (1, 4, 5, 15)}
    )
    assert report["sourceAnomalyCount"] == 1 and report["sourceComplete"] is False
    assert report["details"][1]["decision"] == "source_export_conflict"


@pytest.mark.parametrize(
    "kind,status",
    [(k, 404) for k in ["games", "categories", "expansions"]]
    + [("blueprints", s) for s in [None, 401, 403, 429, 500]],
)
def test_only_listed_expansion_export_404_is_deferred(tmp_path, kind, status):
    api = Source()
    original = api.collection

    def get(request, **kwargs):
        if request == kind:
            raise CardTraderCatalogError("secret", status)
        return original(request, **kwargs)

    api.collection = get
    with pytest.raises(RuntimeError, match="catalog_capture_failed"):
        capture.capture_catalog(api, tmp_path / "run")
    result = json.loads((tmp_path / "run/progress.json").read_text())
    assert result["status"] == "failed" and result["deferredExpansions"] == []


@pytest.mark.parametrize(
    "case",
    [
        "not_list",
        "not_dict",
        "extra_key",
        "bool_id",
        "unknown_id",
        "wrong_status",
        "wrong_reason",
        "duplicate",
        "counts",
        "fake_complete",
        "fake_file",
    ],
)
def test_deferred_receipt_must_account_exactly_for_missing_export(tmp_path, case):
    root = tmp_path / "run"
    result = capture.capture_catalog(DeferredSource({4}), root)
    row = result["deferredExpansions"][0]
    if case == "not_list":
        result["deferredExpansions"] = {}
    elif case == "not_dict":
        result["deferredExpansions"] = [4]
    elif case == "extra_key":
        row["extra"] = True
    elif case == "bool_id":
        row["expansionId"] = True
    elif case == "unknown_id":
        row["expansionId"] = 100
    elif case == "wrong_status":
        row["httpStatus"] = 403
    elif case == "wrong_reason":
        row["reason"] = "guessed_not_released"
    elif case == "duplicate":
        result["deferredExpansions"].append(row)
    elif case == "counts":
        result["completedExpansions"] = 4
    elif case == "fake_complete":
        result["status"] = "complete"
    else:
        (root / "blueprints-4.json").write_text("[]")
    (root / "progress.json").write_text(json.dumps(result))
    with pytest.raises(ValueError):
        capture.compare_captured_catalog(
            root, [], {i: (i, f"Game{i}", "single") for i in (1, 4, 5, 15)}
        )


@pytest.mark.parametrize("legacy", [False, True])
def test_capture_to_comparison_accounts_all_rows_and_preserves_provenance(tmp_path, legacy):
    api = Source()
    root = tmp_path / "run"
    api.rows[4][0]["game_id"] = 5
    capture.capture_catalog(api, root)
    if legacy:
        progress = json.loads((root / "progress.json").read_bytes())
        del progress["deferredExpansions"]
        (root / "progress.json").write_text(json.dumps(progress))
    mapping = {i: (i, f"Game{i}", "single") for i in (1, 4, 5, 15)}
    products = [
        dict(
            productGid="gid://shopify/Product/1",
            game="magic",
            productFamily="single",
            syncSourceId="100",
            powerToolsSourceId="100",
        )
    ]
    result = capture.compare_captured_catalog(root, products, mapping)
    assert result["sourceRows"] == 4 and result["sourceAnomalyCount"] == 1
    assert result["creationApproved"] is False and result["shopifyChanged"] is False
    assert [r["decision"] for r in result["details"]] == [
        "existing_identity_match",
        "source_export_conflict",
        "absent_from_supplied_snapshot",
        "absent_from_supplied_snapshot",
    ]
    assert [(r["sourceExpansionId"], r["sourceRowIndex"]) for r in result["details"]] == [
        (1, 0),
        (4, 0),
        (5, 0),
        (15, 0),
    ]
    assert all(r["creationApproved"] is False for r in result["details"])


@pytest.mark.parametrize(
    "case",
    [
        "partial",
        "stale",
        "counts",
        "hash",
        "bytes",
        "extra_file",
        "missing_file",
        "mapping",
        "invalid_expansion",
        "anomaly",
        "progress_changed",
        "missing_games",
        "too_big",
        "storage_limit",
        "relative",
    ],
)
def test_comparison_rejects_untrusted_or_incomplete_capture(tmp_path, monkeypatch, case):
    api = Source()
    root = tmp_path / "run"
    if case == "anomaly":
        api.rows[4][0]["game_id"] = 5
    capture.capture_catalog(api, root)
    path = root / "progress.json"
    progress = json.loads(path.read_bytes())
    mapping = {i: (i, f"Game{i}", "single") for i in (1, 4, 5, 15)}
    kwargs = {}

    def replace_source(name, value):
        encoded = json.dumps(value).encode()
        (root / name).write_bytes(encoded)
        old = progress["files"][name]["bytes"]
        progress["files"][name] = {
            "sha256": hashlib.sha256(encoded).hexdigest(),
            "bytes": len(encoded),
        }
        progress["bytes"] += len(encoded) - old

    if case == "partial":
        progress["status"] = "running"
    if case == "stale":
        kwargs["now"] = datetime.now(UTC) + timedelta(days=2)
    if case == "counts":
        progress["blueprints"] += 1
    if case == "hash":
        progress["files"]["games.json"]["sha256"] = "0" * 64
    if case == "bytes":
        progress["files"]["games.json"]["bytes"] += 1
    if case == "extra_file":
        progress["files"]["unexpected.json"] = {"sha256": "0" * 64, "bytes": 0}
    if case == "missing_file":
        (root / "blueprints-1.json").unlink()
    if case == "mapping":
        mapping[1] = (1, "Changed", "single")
    if case == "invalid_expansion":
        replace_source("expansions.json", [api.expansions[0]])
    if case == "anomaly":
        replace_source("anomalies-4.json", [])
    if case == "missing_games":
        replace_source("games.json", [])
    if case == "too_big":
        monkeypatch.setattr(capture, "MAX_RESPONSE_BYTES", 1)
    if case == "storage_limit":
        monkeypatch.setattr(capture, "MAX_BYTES", 1)
    path.write_text(json.dumps(progress))
    if case == "progress_changed":
        original = Path.read_bytes
        calls = 0

        def read(p):
            nonlocal calls
            if p == path:
                calls += 1
                if calls == 2:
                    return b"{}"
            return original(p)

        monkeypatch.setattr(Path, "read_bytes", read)
    with pytest.raises((ValueError, KeyError, FileNotFoundError)):
        capture.compare_captured_catalog(
            Path("relative") if case == "relative" else root, [], mapping, **kwargs
        )
