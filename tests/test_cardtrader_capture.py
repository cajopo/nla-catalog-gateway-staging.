import hashlib
import json
from copy import deepcopy
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
        self.rows = {i: [{"id": i * 10, "game_id": i, "expansion_id": i}] for i in (1, 4, 5, 15)}

    def collection(self, kind, **kwargs):
        self.calls.append((kind, kwargs))
        if kind == "games":
            return deepcopy(self.games)
        if kind == "categories":
            return []
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
                raise CardTraderCatalogError("secret-token-test", 429)
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
        assert (root / "blueprints-1.json").exists()


def test_absolute_new_directory_required():
    with pytest.raises(ValueError, match="absolute_capture_directory_required"):
        capture.capture_catalog(Source(), Path("relative"))
