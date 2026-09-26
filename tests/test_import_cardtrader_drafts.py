import hashlib
import json
import sqlite3
from contextlib import closing
from types import SimpleNamespace

import pytest
from scripts import import_cardtrader_drafts as runner
from scripts.compare_cardtrader_catalog import CATEGORIES

from nla_catalog_gateway import cardtrader_capture
from nla_catalog_gateway.canonical_names import SIDECAR_FILENAME
from nla_catalog_gateway.shopify_draft_import import (
    CREATE_DRAFT,
    INITIALIZE_VARIANT,
    create_draft_once,
)
from test_canonical_reference_extension import parent
from test_shopify_draft_import import SHOP, FakeShopify


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(runner.activation, "sync_directory", lambda _: None)
    monkeypatch.setattr(runner.refresh, "document", lambda p: json.loads(p.read_bytes()))
    monkeypatch.setattr(runner.refresh, "freshness", lambda _: {"status": "fresh"})
    monkeypatch.setattr(runner.identities, "read_fresh_identities", lambda *_: ({}, set()))
    monkeypatch.setattr(cardtrader_capture.time, "sleep", lambda _: None)
    monkeypatch.setattr(
        cardtrader_capture.shutil, "disk_usage", lambda _: SimpleNamespace(free=8 * 1024**3)
    )
    bundle, pin = parent(tmp_path)
    source = tmp_path / "capture"

    def collection(kind, **kwargs):
        if kind == "games":
            return [dict(id=i) for i in (1, 4, 5, 15)]
        if kind == "categories":
            return [dict(id=i, game_id=g, name=n) for i, (g, n, _) in CATEGORIES.items()]
        if kind == "expansions":
            return [dict(id=i, game_id=i, name="New Set") for i in (1, 4, 5, 15)]
        if kwargs["expansion_id"] != 1:
            return []
        return [
            dict(
                id=9 + i,
                game_id=1,
                expansion_id=1,
                category_id=1,
                card_market_ids=[42 + i],
                name="New Card" + str(i),
                image_url="https://cardtrader.com/image.jpg",
                fixed_properties={"collector_number": str(i), "mtg_rarity": "Common"},
            )
            for i in range(2)
        ]

    cardtrader_capture.capture_catalog(SimpleNamespace(collection=collection), source)
    # Real immutable SQLite input, not a mocked comparison/preparation result.
    dbpath = tmp_path / "source.sqlite3"
    with closing(sqlite3.connect(dbpath)) as db:
        db.execute("CREATE TABLE projection_metadata(dataset_manifest_json TEXT)")
        db.execute(
            "INSERT INTO projection_metadata VALUES (?)",
            (json.dumps({"generatedAt": "2026-09-26T00:00:00Z"}),),
        )
        db.execute("CREATE TABLE products(product_record_json TEXT)")
        db.commit()
    raw_manifest = json.dumps(
        {
            "artifacts": [
                {
                    "filename": "catalog-projection.v1.sqlite3",
                    "sha256": hashlib.sha256(dbpath.read_bytes()).hexdigest(),
                }
            ]
        }
    ).encode()
    manifest_pin = hashlib.sha256(raw_manifest).hexdigest()
    generation = tmp_path / "store" / "generations" / manifest_pin
    generation.mkdir(parents=True)
    (generation / "catalog-projection.v1.sqlite3").write_bytes(dbpath.read_bytes())
    (generation / "staging-generation-manifest.v1.json").write_bytes(raw_manifest)
    run_root = tmp_path / "refresh-runs"
    run_root.mkdir()
    (run_root / "last-success.json").write_text(json.dumps({"manifestSha256": manifest_pin}))
    config = {key: "unused" for key in runner.refresh.FIELDS}
    config.update({key: str(tmp_path / key) for key in runner.refresh.PATHS})
    config.update(
        shop=SHOP,
        run_root=str(run_root),
        reference=str(bundle),
        reference_manifest_sha256=pin,
        reference_data_sha256=hashlib.sha256((bundle / SIDECAR_FILENAME).read_bytes()).hexdigest(),
    )
    config_path = tmp_path / "refresh.json"
    config_path.write_text(json.dumps(config))
    api = FakeShopify()
    ledger = tmp_path / "ledger.sqlite3"
    create_draft_once(
        ledger,
        shop=SHOP,
        blueprint_id=9,
        cardmarket_id=42,
        game="magic",
        title="Initial",
        image_url="https://cardtrader.com/image.jpg",
        graphql=api,
        verify_missing=lambda: False,
        enabled=True,
    )
    api.calls.clear()
    events = []

    def verify(*args):
        current = json.loads(config_path.read_bytes())
        assert current["reference_manifest_sha256"] != pin
        events.append("live_guard_after_reference_selected")
        return True

    monkeypatch.setattr(runner.identities, "verify_missing", verify)
    values = dict(
        config_path=config_path,
        capture=source,
        identity_run=tmp_path / "identities",
        run=tmp_path / "run-1",
        ledger=ledger,
        generator_sha="b" * 40,
        client=SimpleNamespace(graphql=api),
    )
    return values, config, api, events


def test_default_preview_uses_real_preparation_but_never_writes_shopify_or_config(setup):
    args, original, api, events = setup
    result = runner.run_locked(**args)
    assert result["status"] == "preview" and result["candidates"] == 2
    assert result["selected"] == 1 and result["attempts"] == []
    assert json.loads(args["config_path"].read_bytes()) == original
    assert not api.calls and not events


def test_real_preparation_to_ledger_import_order_and_no_resend(setup, monkeypatch):
    args, original, api, events = setup
    result = runner.run_locked(**args, apply=True)
    assert result["status"] == "batch_complete" and result["selected"] == 1
    assert result["attempts"][0]["status"] == "draft_verified"
    assert events == ["live_guard_after_reference_selected"]
    updated = json.loads(args["config_path"].read_bytes())
    changed = {k for k in updated if updated[k] != original[k]}
    assert changed == {"reference", "reference_manifest_sha256", "reference_data_sha256"}
    assert (args["run"] / "ledger-after.sqlite3").is_file()
    assert json.loads((args["run"] / "refresh-config.before.json").read_bytes()) == original
    assert sum(query == CREATE_DRAFT for query, _ in api.calls) == 1
    with pytest.raises(FileExistsError):
        runner.run_locked(**args, apply=True)
    args["run"] = args["run"].with_name("run-2")
    calls = len(api.calls)
    selected = []

    def inspect_next(ledger, **kwargs):
        selected.append(kwargs["cardmarket_id"])
        return dict(status="not_verified_missing")

    monkeypatch.setattr(runner, "create_draft_once", inspect_next)
    repeated = runner.run_locked(**args, apply=True)
    assert repeated["skippedExisting"] == 1 and selected == [43]
    assert len(api.calls) == calls


def test_existing_shopify_drafts_are_skipped_before_batch_limit(setup, monkeypatch):
    args, _, api, _ = setup
    monkeypatch.setattr(runner.identities, "read_fresh_identities", lambda *_: ({}, {"42"}))
    selected = []

    def inspect_next(ledger, **kwargs):
        selected.append(kwargs["cardmarket_id"])
        return dict(status="not_verified_missing")

    monkeypatch.setattr(runner, "create_draft_once", inspect_next)
    result = runner.run_locked(**args, apply=True)
    assert result["skippedExisting"] == 1 and selected == [43]
    assert not api.calls


def test_uncertain_creation_stops_batch_and_blocks_next_run(setup):
    args, _, api, _ = setup
    api.fail_on = CREATE_DRAFT
    result = runner.run_locked(**args, apply=True, max_attempts=2)
    assert result["status"] == "needs_reconciliation" and len(result["attempts"]) == 1
    assert result["published"] is False
    args["run"] = args["run"].with_name("run-2")
    with pytest.raises(ValueError, match="previous_import_needs_reconciliation"):
        runner.run_locked(**args, apply=True)
    assert sum(query == CREATE_DRAFT for query, _ in api.calls) == 1


@pytest.mark.parametrize("interrupted_operation", [CREATE_DRAFT, INITIALIZE_VARIANT])
def test_interrupt_cannot_publish_false_success_or_allow_retry(setup, interrupted_operation):
    args, _, api, _ = setup

    def interrupted(query, variables):
        if query == interrupted_operation:
            raise KeyboardInterrupt
        return api(query, variables)

    args["client"] = SimpleNamespace(graphql=interrupted)
    with pytest.raises(KeyboardInterrupt):
        runner.run_locked(**args, apply=True)
    receipt = json.loads((args["run"] / "result.json").read_bytes())
    assert receipt["status"] == "stopped_inspect_before_retry"
    assert (args["run"] / "ledger-after.sqlite3").exists()
    args["run"] = args["run"].with_name("run-2")
    with pytest.raises(ValueError, match="previous_import_needs_reconciliation"):
        runner.run_locked(**args, apply=True)


@pytest.mark.parametrize(
    "case", ["pending", "stale_identities", "changed_manifest", "bad_limit", "wrong_run"]
)
def test_failed_prerequisites_never_change_reference_or_create(setup, monkeypatch, case):
    args, original, api, _ = setup
    if case == "pending":
        (args["run"].parent / "refresh-runs" / "pending-run.json").write_text("{}")
    elif case == "stale_identities":

        def fail(*_):
            raise ValueError("stale")

        monkeypatch.setattr(runner.identities, "read_fresh_identities", fail)
    elif case == "changed_manifest":
        next(
            (args["run"].parent / "store").rglob("staging-generation-manifest.v1.json")
        ).write_text("{}")
    elif case == "bad_limit":
        args["max_attempts"] = 101
    else:
        args["run"] = args["ledger"].parent.parent / "outside"
    with pytest.raises(ValueError):
        runner.run_locked(**args, apply=True)
    assert json.loads(args["config_path"].read_bytes()) == original
    assert not api.calls
