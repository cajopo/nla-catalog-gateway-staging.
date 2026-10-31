"""Verified source expansions tag only new, eligible products; legacy requests stay stable."""

import json
import sqlite3
from contextlib import closing
from types import SimpleNamespace

import pytest
from scripts import import_cardtrader_drafts as importer

import test_import_cardtrader_drafts as import_tests
from nla_catalog_gateway import cardtrader_capture as capture
from nla_catalog_gateway import shopify_draft_import as draft
from test_multigame_import import SixGameSource
from test_shopify_draft_import import SHOP, FakeShopify, run

import_case = import_tests.setup


@pytest.mark.parametrize(
    "game_id,category,eligible",
    [
        (18, 214, True),
        (22, 258, True),
        (18, 215, True),
        (22, 259, True),
        (18, 230, False),
        (18, 270, False),
        (22, 284, False),
        (1, 1, False),
    ],
)
def test_verified_source_binds_expansion_only_for_eligible_products(
    import_case, game_id, category, eligible
):
    args, _, api, _ = import_case
    source = SixGameSource()
    source.rows = {key: rows if key == 100 + game_id else [] for key, rows in source.rows.items()}
    source.rows[100 + game_id][0]["category_id"] = category
    args["capture"] = args["capture"].with_name("six-capture")
    capture.capture_catalog(source, args["capture"], game_scope="six-games")
    assert importer.run_locked(**args)["candidates"] == 1
    candidate = json.loads((args["run"] / "reference/preparation.json").read_bytes())["candidates"][
        0
    ]
    if eligible:
        assert candidate["sourceExpansionId"] == 100 + game_id
        assert candidate["sourceExpansionName"] == "Synthetic Set"
        assert candidate["collectionTags"] == [
            "Lorcana" if game_id == 18 else "Riftbound",
            "Synthetic Set",
        ]
    else:
        assert not {"sourceExpansionId", "sourceExpansionName", "collectionTags"} & candidate.keys()
    assert not api.calls


@pytest.mark.parametrize("name", ["Bad, expansion", " Untrimmed", "Riftbound", "x" * 256])
def test_invalid_expansion_tag_is_quarantined_before_creation(import_case, name):
    args, _, api, _ = import_case
    source = SixGameSource()
    source.rows = {key: rows if key == 122 else [] for key, rows in source.rows.items()}
    next(e for e in source.expansions if e["id"] == 122)["name"] = name
    args["capture"] = args["capture"].with_name("six-capture")
    capture.capture_catalog(source, args["capture"], game_scope="six-games")
    result = importer.run_locked(**args, apply=True)
    assert result["selected"] == 0 and result["exceptions"] == 1
    assert not api.calls


@pytest.mark.parametrize("game,label", [("lorcana", "Lorcana"), ("riftbound", "Riftbound")])
def test_initial_tags_and_source_provenance_are_durable_without_resend(tmp_path, game, label):
    api = FakeShopify()
    kwargs = dict(
        game=game,
        source_expansion_id=123,
        source_expansion_name="New Set",
        collection_tags=[label, "New Set"],
    )
    assert run(tmp_path, api, **kwargs)["status"] == "draft_verified"
    ledger = tmp_path / "ledger.sqlite"
    with closing(sqlite3.connect(ledger)) as db:
        request = json.loads(db.execute("SELECT request_json FROM draft_attempts").fetchone()[0])
    assert request["sourceExpansionId"] == 123 and request["sourceExpansionName"] == "New Set"
    assert request["variables"]["product"]["tags"] == [label, "New Set"]
    assert draft.inspect_draft_attempt(ledger, shop=SHOP, cardmarket_id=42, graphql=api)[
        "status"
    ] == ("recorded_draft_matches")
    before = ledger.read_bytes()
    api.calls.clear()
    assert run(tmp_path, api, **kwargs)["status"] == "already_reserved"
    assert not api.calls and ledger.read_bytes() == before
    api.product["tags"] = [label]
    assert draft.inspect_draft_attempt(ledger, shop=SHOP, cardmarket_id=42, graphql=api)[
        "status"
    ] == ("inspection_unconfirmed")


@pytest.mark.parametrize("tags", [None, [], ["Lorcana"], ["Lorcana", "Wrong Set"]])
def test_initial_tag_readback_failure_is_not_verified_or_retried(tmp_path, tags):
    api = FakeShopify()

    def changed(query, variables):
        response = api(query, variables)
        if query == draft.VERIFY_DRAFT:
            response["product"]["tags"] = tags
        return response

    kwargs = dict(
        game="lorcana",
        source_expansion_id=123,
        source_expansion_name="New Set",
        collection_tags=["Lorcana", "New Set"],
    )
    assert run(tmp_path, changed, **kwargs)["status"] == "needs_reconciliation"
    assert not any(q == draft.INITIALIZE_VARIANT for q, _ in api.calls)
    api.calls.clear()
    assert run(tmp_path, api, **kwargs)["status"] == "already_reserved"
    assert not api.calls


@pytest.mark.parametrize(
    "changes",
    [
        dict(game="magic"),
        dict(source_expansion_id=True),
        dict(source_expansion_name=None),
        dict(source_expansion_name="New, Set"),
        dict(collection_tags=["Riftbound", "New Set"]),
    ],
)
def test_partial_or_conflicting_expansion_metadata_has_no_side_effects(tmp_path, changes):
    api = FakeShopify()
    kwargs = dict(
        game="lorcana",
        source_expansion_id=123,
        source_expansion_name="New Set",
        collection_tags=["Lorcana", "New Set"],
    )
    kwargs.update(changes)
    with pytest.raises(ValueError, match="invalid_expansion_collection"):
        run(tmp_path, api, **kwargs)
    assert not api.calls and not (tmp_path / "ledger.sqlite").exists()


@pytest.mark.parametrize("mode", ["enabled", "disabled", "preview", "failure", "bad_approval"])
def test_collection_reconciliation_precedes_creation_and_is_explicit(
    import_case, monkeypatch, mode
):
    args, _, _, _ = import_case
    source = SixGameSource()
    source.rows = {key: rows if key == 118 else [] for key, rows in source.rows.items()}
    args["capture"] = args["capture"].with_name("six-capture")
    capture.capture_catalog(source, args["capture"], game_scope="six-games")
    events = []
    api = FakeShopify()

    def graphql(query, variables):
        if query == draft.CREATE_DRAFT:
            events.append("product")
            api.product["handle"] = variables["product"]["handle"]
        response = api(query, variables)
        if query == draft.SET_IDENTITIES:
            for alias, field in zip(
                ("syncProductId", "powertoolsId"), variables["metafields"], strict=True
            ):
                api.product[alias] = {"type": field["type"], "value": field["value"]}
        return response

    args["client"] = SimpleNamespace(graphql=graphql)
    monkeypatch.setattr(importer.identities, "missing_guard", lambda *_: lambda _: True)

    def collections(**kwargs):
        events.append("collections")
        assert kwargs["enabled"] is True
        assert kwargs["state_dir"] == args["ledger"].parent / "expansion-collections"
        assert kwargs["specs"][0]["sourceExpansionId"] == 118
        if mode == "failure":
            raise ValueError("expansion_collection_missing_inspect")
        return dict(status="complete", planned=1, created=1, existing=0)

    monkeypatch.setattr(importer, "reconcile_expansion_collections", collections)
    if mode == "bad_approval":
        original_prepare = importer.prepare

        def bad_prepare(*args):
            result = original_prepare(*args)
            result["candidates"][0]["creationApproved"] = True
            return result

        monkeypatch.setattr(importer, "prepare", bad_prepare)
    result = importer.run_locked(
        **args, apply=mode != "preview", expansion_collections=mode != "disabled"
    )
    if mode in ("failure", "bad_approval"):
        assert result["status"] == "stopped_inspect_before_retry" and not result["attempts"]
        assert events == (["collections"] if mode == "failure" else [])
        if mode == "failure":
            assert result["failure"]["reason"] == "expansion_collection_missing_inspect"
            assert result["expansionCollections"]["status"] == "started_inspect_journal"
    elif mode == "preview":
        assert result["status"] == "preview" and not events and not api.calls
    else:
        assert result["status"] == "batch_complete"
        assert events == (["collections", "product"] if mode == "enabled" else ["product"])
        assert api.product["tags"] == ["Lorcana", "Synthetic Set"]


def test_collection_flag_rejects_non_boolean_before_side_effects(import_case):
    args, _, api, _ = import_case
    with pytest.raises(ValueError, match="invalid_batch_controls"):
        importer.run_locked(**args, apply=True, expansion_collections="yes")
    assert not api.calls and not args["run"].exists()
