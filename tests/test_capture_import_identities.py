import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest
from scripts import capture_import_identities as capture

from nla_catalog_gateway.shopify_draft_import import ACCESS_QUERY, FIND_ATTEMPT_HANDLE
from nla_catalog_gateway.shopify_identity_changes import RECENT_IDENTITIES_QUERY

SHOP = "nla-test.myshopify.com"
OPERATION = "gid://shopify/BulkOperation/123"


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(capture.activation, "sync_directory", lambda _: None)
    monkeypatch.setattr(capture.refresh, "document", lambda p: json.loads(p.read_bytes()))
    row = dict(id="gid://shopify/Product/1", syncProductId=None, powertoolsId=None)

    class Client:
        def __init__(self):
            self.row = row
            self.calls = []
            self.downloads = 0
            self.count = 1
            self.status = "RUNNING"
            self.operation_patch = {}
            self.start_failure = False
            self.guard = "missing"

        def graphql(self, query, variables):
            self.calls.append(query)
            if query == capture.CONTROLS["counts"]:
                return dict(
                    shop=dict(myshopifyDomain=SHOP),
                    products=dict(count=self.count, precision="EXACT"),
                )
            if query == capture.CONTROLS["start"]:
                if self.start_failure:
                    raise TimeoutError("unknown remote result")
                self.started = capture.refresh.timestamp()
                return dict(
                    bulkOperationRunQuery=dict(bulkOperation=dict(id=OPERATION), userErrors=[])
                )
            if query == capture.CONTROLS["status"]:
                assert variables == {"id": OPERATION}
                return dict(
                    bulkOperation=dict(
                        id=OPERATION,
                        type="QUERY",
                        status=self.status,
                        query=capture.QUERY,
                        createdAt=self.started,
                        completedAt=capture.refresh.timestamp(),
                        rootObjectCount="1",
                        errorCode=None,
                        partialDataUrl=None,
                        url="https://signed.invalid/private",
                        fileSize=len(self.raw()),
                        **self.operation_patch,
                    )
                )
            if query == ACCESS_QUERY:
                return dict(
                    shop=dict(myshopifyDomain="wrong" if self.guard == "wrong_shop" else SHOP)
                )
            if query == capture.DEFINITION_QUERY:
                kind = (
                    "number_integer"
                    if variables["namespace"] == "sync"
                    else "single_line_text_field"
                )
                nodes = [dict(**variables, type=dict(name=kind))]
                return dict(
                    metafieldDefinitions=dict(
                        nodes=[] if self.guard == "bad_definition" else nodes,
                        pageInfo=dict(hasNextPage=False),
                    )
                )
            if query == RECENT_IDENTITIES_QUERY:
                node = dict(self.row, updatedAt=self.started)
                if self.guard == "delta_duplicate":
                    node["powertoolsId"] = dict(type="single_line_text_field", value=" 00042 ")
                return dict(
                    products=dict(nodes=[node], pageInfo=dict(hasNextPage=False, endCursor=None))
                )
            if query == FIND_ATTEMPT_HANDLE:
                return dict(product={} if self.guard == "handle_exists" else None)
            pytest.fail("unexpected GraphQL operation")

        def raw(self):
            return json.dumps(self.row).encode() + b"\n"

        def download(self, url, stream, size, *, maximum_bytes):
            assert maximum_bytes == 256 * 1024**2 and size == len(self.raw())
            self.downloads += 1
            stream.write(self.raw())
            return hashlib.sha256(self.raw()).hexdigest()

    return Client(), tmp_path / "identities"


def complete(client, work):
    result = capture.capture_once(client, SHOP, work)
    assert result["status"] == "running"
    client.status = "COMPLETED"
    return capture.capture_once(client, SHOP, work)


def test_same_operation_resumed_and_receipt_rechecked_without_resend(setup):
    client, work = setup
    receipt = complete(client, work)
    assert receipt["products"] == 1 and receipt["shopifyChanged"] is False
    assert "signed.invalid" not in (work / "completed.json").read_text()
    calls = len(client.calls)
    assert capture.capture_once(client, SHOP, work) == receipt
    assert len(client.calls) == calls
    assert client.downloads == 1 and client.calls.count(capture.CONTROLS["start"]) == 1
    assert capture.read_fresh_identities(work, SHOP) == (receipt, set())


def test_interrupted_submission_never_resends(setup):
    client, work = setup
    client.start_failure = True
    with pytest.raises(TimeoutError):
        capture.capture_once(client, SHOP, work)
    with pytest.raises(FileNotFoundError):
        capture.capture_once(client, SHOP, work)
    assert client.calls.count(capture.CONTROLS["start"]) == 1


def test_run_directory_is_durable_before_any_api_call(setup, monkeypatch):
    client, work = setup
    synced = []
    monkeypatch.setattr(capture.activation, "sync_directory", synced.append)
    original = client.graphql

    def checked_graphql(query, variables):
        assert synced and synced[0] == work.parent
        return original(query, variables)

    client.graphql = checked_graphql
    capture.capture_once(client, SHOP, work)


@pytest.mark.parametrize("failure", ["failed", "count_changed", "bad_row", "download_interrupted"])
def test_incomplete_exports_never_produce_completion(setup, failure):
    client, work = setup
    capture.capture_once(client, SHOP, work)
    client.status = "FAILED" if failure == "failed" else "COMPLETED"
    if failure == "count_changed":
        client.count = 2
    if failure == "bad_row":
        client.row["id"] = "wrong"
    if failure == "download_interrupted":
        (work / "identities.jsonl").write_bytes(b"partial")
    with pytest.raises((ValueError, FileExistsError)):
        capture.capture_once(client, SHOP, work)
    assert not (work / "completed.json").exists()
    assert client.calls.count(capture.CONTROLS["start"]) == 1


@pytest.mark.parametrize("failure", ["bytes", "stale", "shop", "operation"])
def test_receipt_and_source_tamper_or_age_blocks_consumption(setup, failure):
    client, work = setup
    receipt = complete(client, work)
    if failure == "bytes":
        (work / "identities.jsonl").write_bytes(b"{}\n")
    elif failure == "stale":
        old = (datetime.now(UTC) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
        receipt["startedAt"] = receipt["completedAt"] = old
        intent = capture.refresh.document(work / "intent.json")
        intent["startedAt"] = old
        (work / "intent.json").write_text(json.dumps(intent))
    elif failure == "shop":
        receipt["shop"] = "wrong"
    else:
        receipt["operationId"] = "different"
    (work / "completed.json").write_text(json.dumps(receipt))
    with pytest.raises(ValueError):
        capture.read_fresh_identities(work, SHOP)


@pytest.mark.parametrize(
    "guard",
    [
        "missing",
        "snapshot_duplicate",
        "delta_duplicate",
        "handle_exists",
        "wrong_shop",
        "bad_definition",
    ],
)
def test_live_guards_of_fresh_snapshot(setup, guard):
    client, work = setup
    if guard == "snapshot_duplicate":
        client.row["syncProductId"] = dict(type="number_integer", value="00042")
    complete(client, work)
    client.guard = guard
    if guard in ("wrong_shop", "bad_definition"):
        with pytest.raises(ValueError):
            capture.verify_missing(work, SHOP, 42, client.graphql)
    else:
        assert capture.verify_missing(work, SHOP, 42, client.graphql) is (guard == "missing")
    assert not any("productCreate" in q or "metafieldsSet" in q for q in client.calls)


def test_batch_guard_scans_once_but_live_changes_are_not_cached(setup, monkeypatch):
    client, work = setup
    complete(client, work)
    original = capture.scan_identities
    scans = []

    def scan(*args):
        scans.append(1)
        return original(*args)

    monkeypatch.setattr(capture, "scan_identities", scan)
    guard = capture.missing_guard(work, SHOP, client.graphql)
    assert guard(42) is True
    client.guard = "delta_duplicate"
    assert guard(42) is False
    assert scans == [1]
    assert client.calls.count(RECENT_IDENTITIES_QUERY) == 2


@pytest.mark.parametrize(
    "filename", ["identities.jsonl", "completed.json", "intent.json", "operation.json"]
)
def test_batch_guard_rejects_changed_files_before_network(setup, filename):
    client, work = setup
    complete(client, work)
    guard = capture.missing_guard(work, SHOP, client.graphql)
    (work / filename).write_text("changed")
    before = len(client.calls)
    with pytest.raises(ValueError, match="identity_snapshot_changed"):
        guard(42)
    assert len(client.calls) == before


def test_batch_guard_rejects_expiry_without_network(setup, monkeypatch):
    client, work = setup
    complete(client, work)
    guard = capture.missing_guard(work, SHOP, client.graphql)

    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) + timedelta(seconds=1801)

    monkeypatch.setattr(capture, "datetime", Later)
    before = len(client.calls)
    with pytest.raises(ValueError, match="identity_export_stale"):
        guard(42)
    assert len(client.calls) == before


def test_batch_guard_checks_local_snapshot_again_after_network(setup):
    client, work = setup
    complete(client, work)

    def changed_during_query(query, variables):
        (work / "identities.jsonl").write_text("changed during network")
        return client.graphql(query, variables)

    guard = capture.missing_guard(work, SHOP, changed_during_query)
    with pytest.raises(ValueError, match="identity_snapshot_changed"):
        guard(42)


def test_scanner_rejects_duplicate_product_rows(setup):
    client, work = setup
    work.mkdir()
    raw = client.raw() * 2
    target = work / "bad.jsonl"
    target.write_bytes(raw)
    with pytest.raises(ValueError):
        capture.scan_identities(target, hashlib.sha256(raw).hexdigest(), 2)


@pytest.mark.parametrize("field", ["syncProductId", "powertoolsId"])
def test_scanner_checks_both_field_types(setup, field):
    client, work = setup
    work.mkdir()
    client.row[field] = dict(type="wrong", value="42")
    target = work / "bad.jsonl"
    target.write_bytes(client.raw())
    with pytest.raises(ValueError):
        capture.scan_identities(target, hashlib.sha256(client.raw()).hexdigest(), 1)
