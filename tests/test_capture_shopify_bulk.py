"""Native Linux capture orchestration with real transport and synthetic HTTP.

Only the network response boundary and observation clock are controlled. The
reconciler, bundle reader, package proof, SQLite projection and runtime are real.
Non-Linux hosts return without claiming native capture coverage.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts import capture_shopify_bulk as capture

import test_reconcile_split_snapshot as raw_fixtures
import test_reconcile_split_snapshot_linux as native
import test_shopify_capture_http as http_fixtures
from nla_catalog_gateway.pagination import CursorCodecV1
from nla_catalog_gateway.runtime_api import EvidenceBoundCatalogBackend
from nla_catalog_gateway.shopify_capture_http import CaptureHttpError, ShopifyCaptureHttp
from nla_catalog_gateway.staging_generation import open_staging_generation
from nla_catalog_gateway.taxonomy import Game

CODE = "c" * 40
SHOP = http_fixtures.SHOP
BEFORE = datetime(2026, 9, 5, 9, 59, tzinfo=UTC)
AFTER = datetime(2026, 9, 5, 10, 1, 1, tzinfo=UTC)


class CaptureBoundary:
    def __init__(self, inputs, directory):
        self.directory = directory
        self.clock = BEFORE
        self.calls = []
        self.starts = []
        self.downloads = []
        self.count_calls = 0
        self.count_overrides = {}
        self.status_overrides = {}
        self.launch_errors = {}
        self.pending = False
        self.uncertain_part = None
        self.short_part = None
        self.raw = {
            "products": inputs.products_snapshot.read_bytes(),
            "variants": inputs.variants_snapshot.read_bytes(),
        }
        self.queries = {
            part: (capture.ROOT / "graphql" / f"catalog_{part}_snapshot.graphql")
            .read_bytes()
            .decode("utf-8")
            for part in capture.PARTS
        }
        self.controls = {
            name: (capture.ROOT / "graphql" / f"capture_{name}.graphql")
            .read_bytes()
            .decode("utf-8")
            for name in ("counts", "start", "status")
        }
        self.identifiers = {
            part: raw_fixtures.gid("BulkOperation", index)
            for index, part in enumerate(capture.PARTS, start=1)
        }
        self.urls = {
            part: (
                f"https://storage.googleapis.com/synthetic-bulk/{part}.jsonl"
                f"?signature=private-{part}"
            )
            for part in capture.PARTS
        }

    def build(self, *_handlers):
        return self

    def open(self, request, *, timeout):
        assert 0 < timeout <= 30
        self.calls.append(request)
        if request.full_url == f"https://{SHOP}/admin/oauth/access_token":
            response = http_fixtures._token()
        elif request.full_url == f"https://{SHOP}/admin/api/{capture.API_VERSION}/graphql.json":
            body = json.loads(request.data)
            assert http_fixtures._headers(request)["x-shopify-access-token"] == http_fixtures.ACCESS
            response = http_fixtures._json({"data": self._graphql(body)})
        else:
            part = next(part for part, url in self.urls.items() if url == request.full_url)
            assert request.get_method() == "GET"
            assert "x-shopify-access-token" not in http_fixtures._headers(request)
            self.downloads.append(part)
            raw = self.raw[part]
            body = raw[:-1] if self.short_part == part else raw
            response = http_fixtures.Response(body, headers={"Content-Length": len(raw)})
        response.url = request.full_url
        return response

    def _graphql(self, body):
        query, variables = body["query"], body["variables"]
        if query == self.controls["counts"]:
            self.count_calls += 1
            assert set(variables) == {"singleQuery"}
            taxonomy = json.loads(
                (capture.ROOT / "src/nla_catalog_gateway/catalog_taxonomy.v1.json").read_bytes()
            )
            expected = sorted(
                name
                for name, rule in taxonomy["productTypes"].items()
                if rule["productFamily"] == "single"
            )
            assert variables["singleQuery"] == (
                "("
                + " OR ".join(
                    "product_type:" + json.dumps(name, ensure_ascii=False) for name in expected
                )
                + ")"
            )
            assert "status:" not in variables["singleQuery"]
            assert "published_status:" not in variables["singleQuery"]
            result = {
                name: {"count": 4, "precision": "EXACT"}
                for name in (*capture.PARTS, "published", "singles")
            }
            result["shop"] = {"myshopifyDomain": SHOP}
            result.update(self.count_overrides.get(self.count_calls, {}))
            return result
        if query == self.controls["start"]:
            assert set(variables) == {"query"}
            part = next(
                part for part, approved in self.queries.items() if approved == variables["query"]
            )
            state = json.loads((self.directory / capture.CHECKPOINT).read_bytes())
            assert state["parts"][part] == {"launchIntent": True, "operationId": None}
            self.starts.append(part)
            if self.uncertain_part == part:
                raise urllib.error.URLError("synthetic ambiguous launch")
            return {
                "bulkOperationRunQuery": {
                    "bulkOperation": {"id": self.identifiers[part]},
                    "userErrors": self.launch_errors.get(part, []),
                }
            }
        assert query == self.controls["status"]
        assert set(variables) == {"id"}
        part = next(
            part for part, identifier in self.identifiers.items() if identifier == variables["id"]
        )
        self.clock = AFTER
        result = {
            "id": self.identifiers[part],
            "type": "QUERY",
            "status": "RUNNING" if self.pending else "COMPLETED",
            "errorCode": None,
            "query": self.queries[part],
            "createdAt": raw_fixtures.NOW,
            "completedAt": None if self.pending else raw_fixtures.LATER,
            "fileSize": str(len(self.raw[part])),
            "objectCount": str(len(self.raw[part].splitlines())),
            "rootObjectCount": "4",
            "url": None if self.pending else self.urls[part],
            "partialDataUrl": None,
        }
        result.update(self.status_overrides.get(part, {}))
        return {"bulkOperation": result}


def _new_client():
    return ShopifyCaptureHttp(SHOP, capture.API_VERSION, http_fixtures.CLIENT, http_fixtures.SHARED)


@pytest.fixture
def capture_case(tmp_path, monkeypatch):
    if sys.platform != "linux":
        yield None
        return
    before = len(os.listdir("/proc/self/fd"))
    inputs = raw_fixtures.make_inputs(tmp_path)
    names = native._single_card_inputs(inputs, tmp_path)
    directory = tmp_path / "capture"
    directory.mkdir(mode=0o700)
    active = tmp_path / "operator-active-generation.txt"
    active.write_bytes(b"unchanged-active-generation")
    boundary = CaptureBoundary(inputs, directory)

    def forbid_network(*_args, **_kwargs):
        pytest.fail("capture integration test attempted real network access")

    monkeypatch.setattr(socket, "create_connection", forbid_network)
    monkeypatch.setattr(urllib.request, "build_opener", boundary.build)
    monkeypatch.setattr(capture, "_utcnow", lambda: boundary.clock)
    args = {
        "client": _new_client(),
        "capture_directory": directory,
        "shop_domain": SHOP,
        "online_store_publication_gid": raw_fixtures.PUBLICATION,
        "code_sha": CODE,
        **names,
        "canonical_manifest_sha256": hashlib.sha256(
            names["canonical_names_manifest"].read_bytes()
        ).hexdigest(),
    }
    try:
        yield SimpleNamespace(args=args, boundary=boundary, directory=directory, active=active)
    finally:
        assert active.read_bytes() == b"unchanged-active-generation"
        assert len(os.listdir("/proc/self/fd")) == before
        for root, _directories, files in os.walk(tmp_path, followlinks=False):
            Path(root).chmod(0o755)
            for name in files:
                path = Path(root) / name
                if not path.is_symlink():
                    path.chmod(0o644)


def _state(case):
    return json.loads((case.directory / capture.CHECKPOINT).read_bytes())


def _assert_no_candidate(case):
    assert not (case.directory / "candidate").exists()
    assert case.active.read_bytes() == b"unchanged-active-generation"


def _assert_ready(case, receipt):
    assert receipt["status"] == "candidate-ready"
    state = _state(case)
    assert state["packageManifestSha256"] == receipt["manifestSha256"]
    assert case.boundary.starts == ["products", "variants"]
    for part in capture.PARTS:
        raw = (case.directory / f"{part}.jsonl").read_bytes()
        assert raw == case.boundary.raw[part]
        assert state["parts"][part]["downloadSha256"] == hashlib.sha256(raw).hexdigest()
    for name in (
        capture.CHECKPOINT,
        "expectation.json",
        "products-terminal.json",
        "variants-terminal.json",
    ):
        raw = (case.directory / name).read_bytes()
        for private in (http_fixtures.SHARED, http_fixtures.ACCESS, *case.boundary.urls.values()):
            assert private.encode() not in raw
    return open_staging_generation(case.directory / "candidate", receipt["manifestSha256"])


def test_native_capture_real_pipeline_reopens_and_serves_four_games(capture_case):
    if capture_case is None:
        return
    case = capture_case
    receipt = capture.run_capture(**case.args)
    package = _assert_ready(case, receipt)
    backend = EvidenceBoundCatalogBackend.from_staging_generation(
        package,
        CursorCodecV1(b"synthetic-cursor-key" * 2, 1800),
        expected_code_sha=CODE,
        clock=lambda: datetime(2026, 9, 5, 12, tzinfo=UTC),
    )
    ids = set()
    for game in Game:
        if game not in (Game.MAGIC, Game.POKEMON, Game.YUGIOH, Game.ONE_PIECE):
            continue
        result = native._search(backend, game, "123")
        assert len(result.page.items) == 1
        product = result.page.items[0]
        ids.add(product.product_gid)
        assert product.variants[0].inventory_quantity == 0
        assert product.variants[0].inventory_tracked is True
        assert product.variants[0].inventory_policy.value == "DENY"
        assert product.variants[0].price_text == "0.00"
        assert result.next_cursor is None
        assert len(result.suggestions) == 1
        expected = "Lightning Bolt" if game is Game.MAGIC else f"Unmatched {game.value}"
        assert result.suggestions[0].canonical_card_name == expected
    assert len(ids) == 4
    for query in ("Lightning Bolt", "Bolt", "Ligh", "123"):
        result = native._search(backend, Game.MAGIC, query)
        assert len(result.page.items) == 1
        assert result.suggestions[0].canonical_card_name == "Lightning Bolt"
    for game in (Game.POKEMON, Game.YUGIOH, Game.ONE_PIECE):
        result = native._search(backend, game, "Bolt")
        assert not result.page.items and not result.suggestions
    calls = len(case.boundary.calls)
    assert capture.run_capture(**{**case.args, "client": _new_client()}) == receipt
    assert len(case.boundary.calls) == calls


def test_native_capture_pending_resumes_with_new_client_without_duplicate_launch(capture_case):
    if capture_case is None:
        return
    case = capture_case
    case.boundary.pending = True
    receipt = capture.run_capture(**case.args)
    assert receipt == {
        "status": "pending",
        "operationIds": list(case.boundary.identifiers.values()),
    }
    initial = _state(case)
    _assert_no_candidate(case)
    assert not case.boundary.downloads
    case.boundary.pending = False
    ready = capture.run_capture(**{**case.args, "client": _new_client()})
    _assert_ready(case, ready)
    resumed = _state(case)
    assert resumed["snapshotSetId"] == initial["snapshotSetId"]
    assert resumed["beforeObservedAt"] == initial["beforeObservedAt"]
    assert resumed["beforeCounts"] == initial["beforeCounts"]


@pytest.mark.parametrize("part", capture.PARTS)
def test_native_capture_ambiguous_launch_requires_explicit_id_recovery(capture_case, part):
    if capture_case is None:
        return
    case = capture_case
    case.boundary.uncertain_part = part
    with pytest.raises(CaptureHttpError):
        capture.run_capture(**case.args)
    assert _state(case)["parts"][part] == {"launchIntent": True, "operationId": None}
    attempted = case.boundary.starts.copy()
    case.boundary.uncertain_part = None
    with pytest.raises(capture.CaptureError, match="launch outcome is uncertain"):
        capture.run_capture(**{**case.args, "client": _new_client()})
    assert case.boundary.starts == attempted
    _assert_no_candidate(case)
    ready = capture.run_capture(
        **{
            **case.args,
            "client": _new_client(),
            f"recover_{part}_operation_id": case.boundary.identifiers[part],
        }
    )
    _assert_ready(case, ready)


@pytest.mark.parametrize(
    "changes",
    [
        {"code_sha": "f" * 40},
        {"canonical_manifest_sha256": "0" * 64},
        {"shop_domain": "other-synthetic.myshopify.com"},
        {"online_store_publication_gid": "gid://shopify/Publication/7"},
    ],
    ids=["code", "canonical-pin", "shop", "publication"],
)
def test_native_capture_resume_rejects_changed_pins_without_network(capture_case, changes):
    if capture_case is None:
        return
    case = capture_case
    case.boundary.pending = True
    assert capture.run_capture(**case.args)["status"] == "pending"
    checkpoint = (case.directory / capture.CHECKPOINT).read_bytes()
    calls = len(case.boundary.calls)
    with pytest.raises(ValueError):
        capture.run_capture(**{**case.args, **changes})
    assert len(case.boundary.calls) == calls
    assert (case.directory / capture.CHECKPOINT).read_bytes() == checkpoint
    _assert_no_candidate(case)


@pytest.mark.parametrize("count_call", [2, 3], ids=["before-launch", "after-export"])
def test_native_capture_count_drift_never_produces_candidate(capture_case, count_call):
    if capture_case is None:
        return
    case = capture_case
    case.boundary.count_overrides[count_call] = {"variants": {"count": 5, "precision": "EXACT"}}
    with pytest.raises(capture.CaptureError, match="catalog counts changed"):
        capture.run_capture(**case.args)
    assert case.boundary.starts == ([] if count_call == 2 else ["products", "variants"])
    assert not case.boundary.downloads
    assert _state(case)["beforeCounts"]["variants"] == 4
    _assert_no_candidate(case)


@pytest.mark.parametrize(
    "changes",
    [
        {"partialDataUrl": "https://storage.googleapis.com/synthetic-partial" + "?signature=fake"},
        {"status": "FAILED"},
        {"rootObjectCount": "5"},
    ],
    ids=["partial", "failed", "root-count"],
)
def test_native_capture_rejects_failed_or_mismatched_exports(capture_case, changes):
    if capture_case is None:
        return
    case = capture_case
    case.boundary.status_overrides["products"] = changes
    with pytest.raises(capture.CaptureError):
        capture.run_capture(**case.args)
    assert not case.boundary.downloads
    _assert_no_candidate(case)


@pytest.mark.parametrize("tamper", [False, True], ids=["resume", "reject-tamper"])
def test_native_capture_partial_download_retains_prior_checkpoint_without_false_success(
    capture_case, tamper
):
    if capture_case is None:
        return
    case = capture_case
    case.boundary.short_part = "variants"
    with pytest.raises(CaptureHttpError):
        capture.run_capture(**case.args)
    checkpoint = _state(case)
    assert "downloadSha256" in checkpoint["parts"]["products"]
    assert "downloadSha256" not in checkpoint["parts"]["variants"]
    assert not (case.directory / "variants.jsonl").exists()
    assert len(tuple(case.directory.glob(".variants-*.partial"))) == 1
    assert not (case.directory / "bundle").exists()
    _assert_no_candidate(case)
    case.boundary.short_part = None
    if tamper:
        products = case.directory / "products.jsonl"
        products.chmod(0o600)
        products.write_bytes(b"changed after checkpoint")
        with pytest.raises(capture.CaptureError, match="download differs from checkpoint"):
            capture.run_capture(**{**case.args, "client": _new_client()})
        assert case.boundary.downloads == ["products", "variants"]
        _assert_no_candidate(case)
    else:
        ready = capture.run_capture(**{**case.args, "client": _new_client()})
        _assert_ready(case, ready)
        assert case.boundary.downloads == ["products", "variants", "variants"]


@pytest.mark.parametrize("kind", ["known-id", "no-intent"])
def test_native_capture_recovery_requires_exact_unresolved_launch_state(capture_case, kind):
    if capture_case is None:
        return
    case = capture_case
    if kind == "known-id":
        case.boundary.pending = True
        assert capture.run_capture(**case.args)["status"] == "pending"
    else:
        case.boundary.count_overrides[2] = {"variants": {"count": 5, "precision": "EXACT"}}
        with pytest.raises(capture.CaptureError, match="catalog counts changed"):
            capture.run_capture(**case.args)
        case.boundary.count_overrides.clear()
    original = (case.directory / capture.CHECKPOINT).read_bytes()
    starts = case.boundary.starts.copy()
    with pytest.raises(capture.CaptureError, match="recovery requires an unresolved launch intent"):
        capture.run_capture(
            **{**case.args, "recover_products_operation_id": case.boundary.identifiers["products"]}
        )
    assert (case.directory / capture.CHECKPOINT).read_bytes() == original
    assert case.boundary.starts == starts
    assert not case.boundary.downloads
    _assert_no_candidate(case)


@pytest.mark.parametrize("part", capture.PARTS)
def test_native_capture_launch_user_errors_leave_intent_and_never_retry(capture_case, part):
    if capture_case is None:
        return
    case = capture_case
    remote_message = http_fixtures.SHARED + case.boundary.urls[part]
    case.boundary.launch_errors[part] = [{"message": remote_message}]
    with pytest.raises(capture.CaptureError, match="export launch failed") as error:
        capture.run_capture(**case.args)
    assert remote_message not in str(error.value)
    assert _state(case)["parts"][part] == {"launchIntent": True, "operationId": None}
    starts = case.boundary.starts.copy()
    case.boundary.launch_errors.clear()
    with pytest.raises(capture.CaptureError, match="launch outcome is uncertain"):
        capture.run_capture(**{**case.args, "client": _new_client()})
    assert case.boundary.starts == starts
    assert not case.boundary.downloads
    _assert_no_candidate(case)


def test_native_capture_rejects_duplicate_split_operation_ids(capture_case):
    if capture_case is None:
        return
    case = capture_case
    case.boundary.identifiers["variants"] = case.boundary.identifiers["products"]
    with pytest.raises(
        capture.CaptureError, match="split exports must have distinct operation IDs"
    ):
        capture.run_capture(**case.args)
    assert case.boundary.starts == ["products", "variants"]
    assert not case.boundary.downloads
    assert case.boundary.clock == BEFORE  # No terminal query was trusted or even requested.
    _assert_no_candidate(case)


def test_native_capture_resumes_real_packaging_after_interruption_without_reconciliation(
    capture_case, monkeypatch
):
    if capture_case is None:
        return
    case = capture_case
    real_packaging = capture.run_packaging
    real_reconciliation = capture.reconcile.run_reconciliation
    attempts, reconciliations = [], []

    def interrupt_once(*args, **kwargs):
        attempts.append(args)
        if len(attempts) == 1:
            raise OSError("synthetic packaging interruption")
        return real_packaging(*args, **kwargs)

    def reconcile_once(**kwargs):
        reconciliations.append(kwargs)
        return real_reconciliation(**kwargs)

    monkeypatch.setattr(capture, "run_packaging", interrupt_once)
    monkeypatch.setattr(capture.reconcile, "run_reconciliation", reconcile_once)
    with pytest.raises(OSError, match="synthetic packaging interruption"):
        capture.run_capture(**case.args)
    state = _state(case)
    assert state["summarySha256"]
    assert state["packageManifestSha256"] is None
    _assert_no_candidate(case)
    original_bundle = {
        path.name: path.read_bytes() for path in (case.directory / "bundle").iterdir()
    }
    assert len(original_bundle) == 7
    ready = capture.run_capture(**{**case.args, "client": _new_client()})
    _assert_ready(case, ready)
    assert len(reconciliations) == 1
    assert len(attempts) == 2 and attempts[0] == attempts[1]
    assert case.boundary.downloads == ["products", "variants"]
    assert {
        path.name: path.read_bytes() for path in (case.directory / "bundle").iterdir()
    } == original_bundle
