import hashlib
import json
import runpy
import sqlite3
from contextlib import closing, nullcontext
from copy import deepcopy
from types import SimpleNamespace

import pytest
from scripts import backfill_expansion_tags as backfill


@pytest.fixture
def case(tmp_path, monkeypatch):
    rows = [
        dict(
            productGid=f"gid://shopify/Product/{i}",
            handle=f"item-{i}",
            cardmarketId=str(i),
            family=family,
            game="lorcana",
            tagsToAdd=["Lorcana", "Synthetic Set"],
        )
        for i, family in ((1, "single"), (2, "sealed"))
    ]
    path = tmp_path / "plan.json"
    path.write_text(json.dumps({"products": rows}))
    monkeypatch.setattr(backfill, "APPROVED_SHA", hashlib.sha256(path.read_bytes()).hexdigest())
    monkeypatch.setattr(backfill, "APPROVED_COUNT", len(rows))
    api = Fake(rows)
    return path, tmp_path / "state" / "checkpoint.sqlite", api


class Fake:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []
        self.products = {}
        self.access = {
            "shop": {"myshopifyDomain": backfill.SHOP},
            "currentAppInstallation": {"accessScopes": [{"handle": "write_products"}]},
        }
        for row in rows:
            self.products[row["productGid"]] = dict(
                id=row["productGid"],
                handle=row["handle"],
                productType="Lorcana Single" if row["family"] == "single" else "",
                tags=["Merchant Tag"],
                syncProductId={"type": "number_integer", "value": row["cardmarketId"]},
                powertoolsId={"type": "single_line_text_field", "value": row["cardmarketId"]},
                nlaGame={"type": "single_line_text_field", "value": "lorcana"},
                sourceRecordType={"type": "single_line_text_field", "value": "sealed"},
                commercial={"price": "12.50", "stock": 7, "variant": "merchant-owned"},
            )

    def __call__(self, query, variables):
        self.calls.append((query, deepcopy(variables)))
        if query == backfill.ACCESS_QUERY:
            return deepcopy(self.access)
        if query == backfill.READ:
            return {"nodes": [deepcopy(self.products.get(i)) for i in variables["ids"]]}
        assert query.startswith("mutation NlaAddExpansionTags")
        result = {}
        for i in range(len(variables) // 2):
            product = self.products[variables[f"id{i}"]]
            product["tags"] = sorted(set(product["tags"]) | set(variables[f"tags{i}"]))
            result[f"p{i}"] = {"node": {"id": product["id"]}, "userErrors": []}
        return result

    def mutations(self):
        return [query for query, _ in self.calls if query.startswith("mutation")]


def test_preview_checks_every_identity_without_writes(case):
    plan, state, api = case
    result = backfill.run(plan, state, api, batch_size=1)
    assert result["status"] == "preview" and result["productsNeedingTags"] == 2
    assert result["shopifyChanged"] is False and not api.mutations()
    assert len([q for q, _ in api.calls if q == backfill.READ]) == 2


def test_additive_apply_preserves_tags_and_commercial_data_and_resume(case):
    plan, state, api = case
    before = deepcopy(api.products)
    result = backfill.run(plan, state, api, apply=True)
    assert result["status"] == "complete" and result["productsChecked"] == 2
    assert result["shopifyChanged"] is True and len(api.mutations()) == 1
    for gid, product in api.products.items():
        assert product["tags"] == ["Lorcana", "Merchant Tag", "Synthetic Set"]
        assert product["commercial"] == before[gid]["commercial"]
    result = backfill.run(plan, state, api, apply=True)
    assert result["shopifyChanged"] is False and len(api.mutations()) == 1


def test_response_lost_resume_reads_and_does_not_resend_completed_add(case):
    plan, state, api = case

    def lost(query, variables):
        result = api(query, variables)
        if query.startswith("mutation"):
            with closing(sqlite3.connect(state)) as db:
                assert (
                    db.execute("SELECT COUNT(*) FROM products WHERE state='pending'").fetchone()[0]
                    == 2
                )
            raise TimeoutError("lost")
        return result

    with pytest.raises(TimeoutError):
        backfill.run(plan, state, lost, apply=True)
    assert backfill.run(plan, state, api, apply=True)["status"] == "complete"
    assert len(api.mutations()) == 1


def test_resume_pending_not_applied_rechecks_before_add(case):
    plan, state, api = case

    def failed(query, variables):
        if query.startswith("mutation"):
            raise TimeoutError("before send")
        return api(query, variables)

    with pytest.raises(TimeoutError):
        backfill.run(plan, state, failed, apply=True)
    api.products[api.rows[0]["productGid"]]["tags"].append("PowerTools New Tag")
    assert backfill.run(plan, state, api, apply=True)["status"] == "complete"
    assert "PowerTools New Tag" in api.products[api.rows[0]["productGid"]]["tags"]


@pytest.mark.parametrize(
    "kwargs", [{"apply": 1}, {"batch_size": True}, {"batch_size": 0}, {"batch_size": 51}]
)
def test_invalid_controls(case, kwargs):
    plan, state, api = case
    with pytest.raises(ValueError, match="invalid_backfill_controls"):
        backfill.run(plan, state, api, **kwargs)
    assert not api.calls


def test_manifest_hash_and_count_pin(case, monkeypatch):
    plan, state, api = case
    monkeypatch.setattr(backfill, "APPROVED_SHA", "0" * 64)
    with pytest.raises(ValueError, match="unapproved_manifest"):
        backfill.run(plan, state, api)
    monkeypatch.setattr(backfill, "APPROVED_SHA", hashlib.sha256(plan.read_bytes()).hexdigest())
    monkeypatch.setattr(backfill, "APPROVED_COUNT", 3)
    with pytest.raises(ValueError, match="unapproved_product_count"):
        backfill.run(plan, state, api)


def test_manifest_duplicate_gid(case, monkeypatch):
    plan, state, api = case
    plan.write_text(json.dumps({"products": [api.rows[0], api.rows[0]]}))
    monkeypatch.setattr(backfill, "APPROVED_SHA", hashlib.sha256(plan.read_bytes()).hexdigest())
    with pytest.raises(ValueError, match="unapproved_product_count"):
        backfill.run(plan, state, api)


@pytest.mark.parametrize("kind", ["shop", "scope"])
def test_wrong_shop_or_scope(case, kind):
    plan, state, api = case
    if kind == "shop":
        api.access["shop"]["myshopifyDomain"] = "another.myshopify.com"
    else:
        api.access["currentAppInstallation"]["accessScopes"] = []
    with pytest.raises(ValueError, match="backfill_access_mismatch"):
        backfill.run(plan, state, api, apply=True)
    assert not api.mutations()


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", "wrong"),
        ("handle", "changed"),
        ("syncProductId", None),
        ("powertoolsId", None),
        ("tags", None),
        ("tags", [1]),
    ],
)
def test_identity_or_tags_drift_fails_whole_batch_before_mutation(case, field, value):
    plan, state, api = case
    api.products[api.rows[1]["productGid"]][field] = value
    with pytest.raises(ValueError, match="fresh_product_identity_mismatch"):
        backfill.run(plan, state, api, apply=True)
    assert not api.mutations()


def test_deleted_product(case):
    plan, state, api = case
    api.products.pop(api.rows[0]["productGid"])
    with pytest.raises(ValueError, match="fresh_product_identity_mismatch"):
        backfill.run(plan, state, api, apply=True)


@pytest.mark.parametrize(
    "index,field", [(0, "productType"), (1, "productType"), (1, "nlaGame"), (1, "sourceRecordType")]
)
def test_classification_drift(case, index, field):
    plan, state, api = case
    api.products[api.rows[index]["productGid"]][field] = None
    with pytest.raises(ValueError, match="fresh_product_classification_mismatch"):
        backfill.run(plan, state, api, apply=True)
    assert not api.mutations()


@pytest.mark.parametrize("nodes", [None, []])
def test_bad_read_shape(case, nodes):
    plan, state, api = case
    with pytest.raises(ValueError, match="invalid_product_readback"):
        backfill.run(
            plan, state, lambda q, v: {"nodes": nodes} if q == backfill.READ else api(q, v)
        )


def test_checkpoint_manifest_conflict(case):
    plan, state, api = case
    backfill.run(plan, state, api)
    with closing(sqlite3.connect(state)) as db:
        db.execute("UPDATE metadata SET manifest_sha='different'")
        db.commit()
    with pytest.raises(ValueError, match="checkpoint_manifest_mismatch"):
        backfill.run(plan, state, api, apply=True)


def test_symlink_checkpoint_rejected(case, monkeypatch):
    plan, state, api = case
    monkeypatch.setattr(type(state), "is_symlink", lambda self: self == state)
    with pytest.raises(ValueError, match="invalid_checkpoint_path"):
        backfill.run(plan, state, api, apply=True)


@pytest.mark.parametrize(
    "removed,error",
    [("Merchant Tag", "preexisting_tags_removed"), ("Lorcana", "completed_tags_changed")],
)
def test_verified_tag_removal_is_not_silently_repaired(case, removed, error):
    plan, state, api = case
    backfill.run(plan, state, api, apply=True)
    api.products[api.rows[0]["productGid"]]["tags"].remove(removed)
    with pytest.raises(ValueError, match=error):
        backfill.run(plan, state, api, apply=True)
    assert len(api.mutations()) == 1


def test_mutation_user_error_requires_inspection(case):
    plan, state, api = case

    def bad(query, variables):
        result = api(query, variables)
        if query.startswith("mutation"):
            result["p0"]["userErrors"] = [{"field": None, "message": "private remote error"}]
        return result

    with pytest.raises(ValueError, match="tag_mutation_unconfirmed"):
        backfill.run(plan, state, bad, apply=True)


def test_missing_readback_tag_fails(case):
    plan, state, api = case

    def remove(query, variables):
        result = api(query, variables)
        if query.startswith("mutation"):
            api.products[api.rows[0]["productGid"]]["tags"].remove("Synthetic Set")
        return result

    with pytest.raises(ValueError, match="tag_readback_mismatch"):
        backfill.run(plan, state, remove, apply=True)


@pytest.mark.parametrize(
    "throttle,sleeps",
    [
        ({}, []),
        ({"currentlyAvailable": 1000, "maximumAvailable": 1000, "restoreRate": 100}, []),
        ({"currentlyAvailable": 0, "maximumAvailable": 1000, "restoreRate": 100}, [7]),
        ({"currentlyAvailable": 0, "maximumAvailable": 50, "restoreRate": 0.1}, [30]),
        ({"currentlyAvailable": 0, "maximumAvailable": 50, "restoreRate": 0}, []),
    ],
)
def test_api_cost_pacing_without_logging_responses(monkeypatch, throttle, sleeps):
    result = {"extensions": {"cost": {"throttleStatus": throttle}}}
    monkeypatch.setattr(backfill.ShopifyCaptureHttp, "_request_json", lambda *_a, **_kw: result)
    observed = []
    monkeypatch.setattr(backfill.time, "sleep", observed.append)
    client = object.__new__(backfill.PacedShopify)
    assert client._request_json() is result and observed == sleeps


def test_cli_success_and_failure(case, monkeypatch, capsys):
    plan, state, api = case
    report = state.parent / "result.json"
    args = [
        "--refresh-config",
        "config",
        "--manifest",
        str(plan),
        "--checkpoint",
        str(state),
        "--result",
        str(report),
    ]
    monkeypatch.setattr(backfill.sys, "platform", "linux")
    monkeypatch.setattr(backfill.os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(backfill.os, "umask", lambda _: None)
    monkeypatch.setattr(
        backfill,
        "config_values",
        lambda _: ({}, {"run_root": state.parent, "config": state.parent, "shop": backfill.SHOP}),
    )
    monkeypatch.setattr(backfill.refresh, "pipeline_lock", lambda _: nullcontext())
    monkeypatch.setattr(
        backfill.refresh, "document", lambda _: {"client_id": "id", "client_secret": "secret"}
    )
    monkeypatch.setattr(backfill, "PacedShopify", lambda *_: SimpleNamespace(graphql=api))
    monkeypatch.setattr(
        backfill.refresh, "publish", lambda path, value, **_: path.write_text(json.dumps(value))
    )
    assert backfill.main(args) == 0
    output = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert output[0]["status"] == "progress"
    assert output[-1] == json.loads(report.read_text())
    assert output[-1]["status"] == "preview"
    monkeypatch.setattr(backfill.os, "geteuid", lambda: 1)
    assert backfill.main(args) == 1
    assert json.loads(capsys.readouterr().out) == {
        "status": "backfill_unconfirmed_inspect_checkpoint"
    }


def test_cli_module_entrypoint_exits_without_secrets(monkeypatch, capsys):
    monkeypatch.setattr(backfill.sys, "platform", "win32")
    monkeypatch.setattr(
        backfill.sys,
        "argv",
        [
            "backfill",
            "--refresh-config",
            "x",
            "--manifest",
            "x",
            "--checkpoint",
            "x",
            "--result",
            "x",
        ],
    )
    with pytest.raises(SystemExit) as result:
        runpy.run_module("scripts.backfill_expansion_tags", run_name="__main__")
    assert result.value.code == 1
    assert "backfill_unconfirmed" in capsys.readouterr().out


def test_progress_callback_reports_only_bounded_counts(case):
    plan, state, api = case
    events = []
    backfill.run(plan, state, api, batch_size=1, progress=events.append)
    assert events == [
        {
            "status": "progress",
            "productsChecked": 2,
            "productsTotal": 2,
            "productsNeedingTags": 2,
        }
    ]
