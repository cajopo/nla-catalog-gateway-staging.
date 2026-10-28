"""Coordinator transitions with real SQLite ledger and native identity receipt validation."""

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from scripts import refresh_market_catalog as market

from test_refresh_market_catalog import setup as cycle_setup  # noqa: F401 -- pytest fixture.

SHOP = "test.myshopify.com"
DEFERRED = dict(cardmarketId=43, blueprintId=10, reason="inconsistent_identity_page")


@pytest.fixture
def case(cycle_setup, monkeypatch):  # noqa: F811 -- imported pytest fixture.
    args, events, _ = cycle_setup
    args["shopify"] = SimpleNamespace(graphql=object())
    # Portable file reading only: the native identity receipt/hash/count/age
    # validator stays in use; root/0600 enforcement has separate operator tests.
    monkeypatch.setattr(market.refresh, "document", lambda path: json.loads(path.read_bytes()))
    with closing(sqlite3.connect(args["ledger"])) as db:
        db.execute(
            "CREATE TABLE draft_attempts(shop TEXT,cardmarket_id INTEGER,blueprint_id INTEGER,"
            "product_gid TEXT,state TEXT,PRIMARY KEY(shop,cardmarket_id),UNIQUE(shop,blueprint_id))"
        )
    value = SimpleNamespace(args=args, events=events, paths=[], sources=[], known=[], steps=[])

    def insert(identifier, blueprint, *, state="draft_verified", gid=None):
        with closing(sqlite3.connect(args["ledger"])) as db:
            db.execute(
                "INSERT INTO draft_attempts VALUES (?,?,?,?,?)",
                (SHOP, identifier, blueprint, gid or f"gid://shopify/Product/{identifier}", state),
            )
            db.commit()

    def identity(_client, shop, path):
        events.append("identity")
        assert shop == SHOP and path not in value.paths
        value.paths.append(path)
        path.mkdir()
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        operation = f"gid://shopify/BulkOperation/{len(value.paths)}"
        # A full synthetic baseline with native count/hash/receipt/freshness checks.
        rows = [dict(id="gid://shopify/Product/1", syncProductId=None, powertoolsId=None)]
        for identifier in value.known:
            rows.append(
                dict(
                    id=f"gid://shopify/Product/{identifier}",
                    syncProductId=dict(type="number_integer", value=str(identifier)),
                    powertoolsId=dict(type="single_line_text_field", value=str(identifier)),
                )
            )
        raw = b"".join(json.dumps(row).encode() + b"\n" for row in rows)
        (path / "identities.jsonl").write_bytes(raw)
        receipt = dict(
            status="complete",
            shop=SHOP,
            operationId=operation,
            products=len(rows),
            shopifyChanged=False,
            sha256=hashlib.sha256(raw).hexdigest(),
            startedAt=now,
            completedAt=now,
        )
        for name, document in (
            ("completed.json", receipt),
            ("operation.json", {"id": operation}),
            (
                "intent.json",
                dict(
                    shop=SHOP,
                    querySha256=market.identities.QUERY_SHA,
                    products=len(rows),
                    startedAt=now,
                ),
            ),
        ):
            (path / name).write_text(json.dumps(document))
        return receipt

    def batch(*inputs, **kwargs):
        events.append("batch")
        assert inputs[2] == value.paths[-1] and kwargs["apply"] is True
        value.sources.append(inputs[1])
        step = value.steps.pop(0)
        created = step.pop("created", [])
        for identifier, blueprint in created:
            insert(identifier, blueprint)
        if step.pop("uncertain", False):
            insert(99, 99, state="reserved")
        value.known = step.pop("next_known", [])
        result = dict(
            status="batch_complete",
            candidates=2,
            skippedExisting=len(value.paths) - 1,
            selected=1,
            exceptions=0,
            attempts=[dict(status="draft_verified", cardmarketId=i) for i, _ in created],
            deferred=[],
        )
        result.update(step)
        return result

    def publication(*_args, **_kwargs):
        events.append("publication")
        return dict(status="publication_complete", published=2, remaining=0, results=[])

    monkeypatch.setattr(market.identities, "capture_once", identity)
    monkeypatch.setattr(market.drafts, "run_locked", batch)
    monkeypatch.setattr(market, "publish_verified_drafts", publication)
    value.insert = insert
    return value


def deferred_step(**changes):
    return dict(
        status="batch_deferred",
        created=[(42, 9)],
        deferred=[dict(DEFERRED)],
        **changes,
    )


def run(case, max_batches=5):
    return market.cycle(
        **case.args,
        apply_drafts=True,
        max_attempts=100,
        max_batches=max_batches,
        publish_online_store="gid://shopify/Publication/12",
    )


def test_progress_deferral_uses_new_baseline_then_same_identity_can_complete(case):
    case.steps = [deferred_step(), dict(created=[(43, 10)])]
    result = run(case)
    assert result["status"] == "draft_cycle_complete"
    assert result["remaining"] == 0 and result["eligibleExhausted"] is True
    assert result["deferred"] == []
    assert result["deferralHistory"] == [
        {**DEFERRED, "batch": 1, "identityOperation": "gid://shopify/BulkOperation/1"}
    ]
    assert result["resolvedDeferrals"] == [
        {
            **DEFERRED,
            "lastDeferredBatch": 1,
            "resolution": "verified_ledger",
            "productGid": "gid://shopify/Product/43",
        }
    ]
    proof = result["deferralResolutionEvidence"]
    assert proof["batch"] == 2 and proof["identityOperation"] == "gid://shopify/BulkOperation/2"
    assert proof["identityReceiptSha256"] == market.activation.digest(
        case.paths[-1] / "completed.json"
    )
    assert proof["identityPayloadSha256"] == market.activation.digest(
        case.paths[-1] / "identities.jsonl"
    )
    assert (
        proof["verifiedLedgerSha256"]
        == hashlib.sha256(
            json.dumps(
                market.verified_ledger_rows(case.args["ledger"], SHOP), separators=(",", ":")
            ).encode()
        ).hexdigest()
    )
    assert case.paths[0] != case.paths[1] and case.sources[0] == case.sources[1]
    assert case.events == [
        "source",
        "identity",
        "batch",
        "identity",
        "batch",
        "publication",
        "refresh",
    ]
    terminal = case.args["state"] / result["run"] / "completed.json"
    assert json.loads(terminal.read_bytes()) == result


def test_later_baseline_presence_resolves_without_claiming_importer_ownership(case):
    case.steps = [
        deferred_step(next_known=[43]),
        dict(status="preview", skippedExisting=2, selected=0),
    ]
    result = run(case)
    assert result["status"] == "draft_cycle_complete" and not result["deferred"]
    assert result["resolvedDeferrals"] == [
        {**DEFERRED, "lastDeferredBatch": 1, "resolution": "observed_in_fresh_identity_baseline"}
    ]
    assert [row[0] for row in market.verified_ledger_rows(case.args["ledger"], SHOP)] == [42]


def test_repeated_read_deferral_without_progress_stops_and_remains_unresolved(case):
    case.steps = [
        deferred_step(),
        dict(status="batch_deferred", deferred=[dict(DEFERRED)]),
    ]
    result = run(case)
    assert result["status"] == "draft_cycle_partial"
    assert result["completionReason"] == "precreate_identity_deferred"
    assert result["remaining"] == 1 and result["deferred"] == [DEFERRED]
    assert len(result["deferralHistory"]) == 2 and result["resolvedDeferrals"] == []
    assert len(case.paths) == 2 and result["deferralResolutionEvidence"] is None


def test_batch_budget_still_closes_partial_and_retains_deferral(case):
    case.steps = [deferred_step()]
    result = run(case, 1)
    assert result["completionReason"] == "batch_budget_exhausted"
    assert result["status"] == "draft_cycle_partial" and result["deferred"] == [DEFERRED]
    assert len(case.paths) == 1


def test_budget_end_resolves_old_deferral_but_keeps_new_one(case):
    next_deferred = dict(cardmarketId=44, blueprintId=11, reason="inconsistent_identity_page")
    case.steps = [
        deferred_step(candidates=3),
        dict(status="batch_deferred", candidates=3, created=[(43, 10)], deferred=[next_deferred]),
    ]
    result = run(case, 2)
    assert result["completionReason"] == "batch_budget_exhausted"
    assert result["deferred"] == [next_deferred] and result["remaining"] == 1
    assert [event["cardmarketId"] for event in result["deferralHistory"]] == [43, 44]
    assert [entry["cardmarketId"] for entry in result["resolvedDeferrals"]] == [43]
    assert result["status"] == "draft_cycle_partial" and result["eligibleExhausted"] is False


def test_uncertain_ledger_prevents_new_baseline_and_publication(case):
    case.steps = [deferred_step(uncertain=True)]
    with pytest.raises(ValueError, match="previous_import_needs_reconciliation"):
        run(case)
    assert case.events == ["source", "identity", "batch"]
    assert (case.args["state"] / "pending-market-run.json").exists()


def test_unresolved_deferral_cannot_be_hidden_by_zero_aggregate_remaining(case):
    case.steps = [deferred_step(), dict(candidates=0, skippedExisting=0, selected=0)]
    result = run(case)
    assert result["remaining"] == 0 and result["eligibleExhausted"] is False
    assert result["completionReason"] == "unresolved_identity_deferrals"
    assert result["status"] == "draft_cycle_partial" and result["deferred"] == [DEFERRED]


@pytest.mark.parametrize("identifier,blueprint", [(43, 999), (999, 10)])
def test_ledger_resolution_requires_both_identifiers(case, identifier, blueprint):
    case.steps = [deferred_step(), dict(created=[(identifier, blueprint)])]
    with pytest.raises(ValueError, match="deferred_ledger_identity_conflict"):
        run(case)
    assert "publication" not in case.events


def test_two_conflicting_ledger_rows_cannot_resolve_one_deferral(case):
    case.steps = [deferred_step(), dict(candidates=3, created=[(43, 999), (999, 10)])]
    with pytest.raises(ValueError, match="deferred_ledger_identity_conflict"):
        run(case)


@pytest.mark.parametrize("problem", ["stale", "payload", "operation"])
def test_bad_final_baseline_evidence_never_resolves_or_publishes(case, monkeypatch, problem):
    case.steps = [deferred_step(), dict(created=[(43, 10)])]
    original = market.drafts.run_locked

    def corrupt(*args, **kwargs):
        result = original(*args, **kwargs)
        if len(case.paths) == 2:
            path = case.paths[-1]
            if problem == "payload":
                (path / "identities.jsonl").write_bytes(b"changed")
            else:
                receipt = json.loads((path / "completed.json").read_bytes())
                if problem == "stale":
                    receipt["startedAt"] = "2000-01-01T00:00:00Z"
                    intent = json.loads((path / "intent.json").read_bytes())
                    intent["startedAt"] = receipt["startedAt"]
                    (path / "intent.json").write_text(json.dumps(intent))
                else:
                    receipt["operationId"] = "gid://shopify/BulkOperation/99"
                    (path / "operation.json").write_text(json.dumps({"id": receipt["operationId"]}))
                (path / "completed.json").write_text(json.dumps(receipt))
        return result

    monkeypatch.setattr(market.drafts, "run_locked", corrupt)
    with pytest.raises(ValueError):
        run(case)
    assert "publication" not in case.events


def test_capacity_is_rechecked_before_new_baseline(case, monkeypatch):
    case.steps = [deferred_step()]
    sizes = iter([10, 10, 5])
    monkeypatch.setattr(
        market.shutil, "disk_usage", lambda _: SimpleNamespace(free=next(sizes) * 1024**3)
    )
    with pytest.raises(ValueError, match="insufficient_market_cycle_space"):
        run(case)
    assert case.events == ["source", "identity", "batch"]


@pytest.mark.parametrize(
    "column,value",
    [
        ("state", None),
        ("cardmarket_id", "bad"),
        ("cardmarket_id", 0),
        ("blueprint_id", -1),
        ("product_gid", None),
        ("product_gid", "invalid"),
    ],
)
def test_malformed_ledger_is_not_resolution_evidence(case, column, value):
    case.insert(43, 10)
    with closing(sqlite3.connect(case.args["ledger"])) as db:
        db.execute(f"UPDATE draft_attempts SET {column}=?", (value,))  # noqa: S608 -- fixed parametrized column list.
        db.commit()
    with pytest.raises(ValueError):
        market.verified_ledger_rows(case.args["ledger"], SHOP)


def test_verified_ledger_read_is_nonmutating_and_shop_scoped(case):
    case.insert(43, 10)
    before = case.args["ledger"].read_bytes()
    assert market.verified_ledger_rows(case.args["ledger"], SHOP) == [
        (43, 10, "gid://shopify/Product/43")
    ]
    assert market.verified_ledger_rows(case.args["ledger"], "other.myshopify.com") == []
    assert case.args["ledger"].read_bytes() == before
