"""Six-game source fixtures are synthetic; no credentials or remote calls."""

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts import import_cardtrader_drafts as importer
from scripts import prepare_cardtrader_reference as preparation
from scripts.compare_cardtrader_catalog import CATEGORIES

import test_import_cardtrader_drafts as import_tests
import test_pagination as page_tests
import test_refresh_market_catalog as market_tests
from nla_catalog_gateway import cardtrader_capture as capture
from nla_catalog_gateway.canonical_names import (
    MANIFEST_FILENAME,
    SIDECAR_FILENAME,
    load_canonical_names,
    load_canonical_names_manifest,
)
from nla_catalog_gateway.cardtrader_candidates import compare_catalog
from nla_catalog_gateway.cardtrader_catalog import CardTraderCatalogError
from nla_catalog_gateway.cardtrader_scope import GAMES, LEGACY_GAME_IDS, game_ids_for_scope
from nla_catalog_gateway.runtime_contract import CatalogFiltersV1, RequestFamily
from nla_catalog_gateway.shopify_draft_import import CREATE_DRAFT, PRODUCT_TYPES
from nla_catalog_gateway.taxonomy import Game
from test_shopify_draft_import import FakeShopify
from test_shopify_draft_import import run as create_draft

import_case = import_tests.setup
market_case = market_tests.setup
SINGLE_CATEGORIES = {1: 1, 4: 44, 5: 73, 15: 192, 18: 214, 22: 258}
NEW_EXPANSION_CODES = {18: "ch1", 22: "ogn"}


class SixGameSource:
    def __init__(self):
        self.calls = []
        self.unavailable = set()
        self.games = [{"id": game_id} for game_id in GAMES]
        self.expansions = [
            {
                "id": 100 + game_id,
                "game_id": game_id,
                "name": "Synthetic Set",
                "code": NEW_EXPANSION_CODES.get(game_id, "legacy-source-code"),
            }
            for game_id in GAMES
        ]
        self.rows = {
            100 + game_id: [
                {
                    "id": 1000 + game_id,
                    "game_id": game_id,
                    "expansion_id": 100 + game_id,
                    "category_id": SINGLE_CATEGORIES[game_id],
                    "card_market_ids": [2000 + game_id],
                    "name": "Shared Card",
                    "image_url": "https://cardtrader.com/synthetic.jpg",
                    "fixed_properties": {
                        "collector_number": "012",
                        preparation.RARITY[game]: "Rare",
                    },
                    "editable_properties": [
                        {"name": "condition", "default_value": "Near Mint"},
                        {"name": "language", "default_value": "en"},
                    ],
                }
            ]
            for game_id, game in GAMES.items()
        }

    def collection(self, kind, **kwargs):
        self.calls.append((kind, kwargs))
        if kind == "games":
            return deepcopy(self.games)
        if kind == "categories":
            return [dict(id=i, game_id=g, name=n) for i, (g, n, _) in CATEGORIES.items()]
        if kind == "expansions":
            return deepcopy(self.expansions)
        identifier = kwargs["expansion_id"]
        if identifier in self.unavailable:
            raise CardTraderCatalogError("request_failed", 404)
        return deepcopy(self.rows[identifier])


@pytest.fixture
def source(monkeypatch):
    monkeypatch.setattr(capture.time, "sleep", lambda _: None)
    monkeypatch.setattr(capture.shutil, "disk_usage", lambda _: SimpleNamespace(free=8 * 1024**3))
    return SixGameSource()


@pytest.mark.parametrize("scope,expected", [("legacy", LEGACY_GAME_IDS), ("six-games", set(GAMES))])
def test_capture_scope_is_explicit_and_preserved_in_comparison(tmp_path, source, scope, expected):
    root = tmp_path / "capture"
    receipt = capture.capture_catalog(source, root, game_scope=scope)
    assert receipt["gameScope"] == scope
    assert receipt["completedExpansions"] == len(expected)
    assert {kw["expansion_id"] for kind, kw in source.calls if kind == "blueprints"} == {
        100 + game_id for game_id in expected
    }
    report = capture.compare_captured_catalog(root, [], CATEGORIES)
    assert report["gameScope"] == scope
    assert {row["game"] for row in report["details"]} == {GAMES[i] for i in expected}
    assert all(row["decision"] == "absent_from_supplied_snapshot" for row in report["details"])
    assert report["creationApproved"] is False and report["shopifyChanged"] is False


def test_old_capture_receipt_stays_four_game_when_source_lists_six(tmp_path, source):
    root = tmp_path / "capture"
    receipt = capture.capture_catalog(source, root)
    del receipt["gameScope"]
    (root / "progress.json").write_text(json.dumps(receipt))
    report = capture.compare_captured_catalog(root, [], CATEGORIES)
    assert report["gameScope"] == "legacy" and report["sourceRows"] == 4
    assert not (root / "blueprints-118.json").exists()
    assert not (root / "blueprints-122.json").exists()


@pytest.mark.parametrize("scope", [None, "all", "", 6, [], {}])
def test_invalid_scope_fails_before_capture_or_cycle_side_effects(tmp_path, source, scope):
    with pytest.raises(ValueError, match="invalid_game_scope"):
        game_ids_for_scope(scope)
    with pytest.raises(ValueError, match="invalid_game_scope"):
        capture.capture_catalog(source, tmp_path / "new", game_scope=scope)
    assert not source.calls and not (tmp_path / "new").exists()


def test_capture_scope_cannot_claim_missing_new_games(tmp_path, source):
    source.games = [row for row in source.games if row["id"] != 22]
    with pytest.raises(RuntimeError, match="catalog_capture_failed"):
        capture.capture_catalog(source, tmp_path / "new", game_scope="six-games")
    assert [kind for kind, _ in source.calls] == ["games"]


def test_unknown_receipt_scope_and_missing_new_expansion_fail_closed(tmp_path, source):
    root = tmp_path / "capture"
    receipt = capture.capture_catalog(source, root)
    receipt["gameScope"] = "unknown"
    (root / "progress.json").write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="invalid_game_scope"):
        capture.compare_captured_catalog(root, [], CATEGORIES)
    receipt["gameScope"] = "six-games"
    (root / "progress.json").write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="invalid_capture_expansions"):
        capture.compare_captured_catalog(root, [], CATEGORIES)


def test_new_game_wrong_export_rows_remain_accounted_and_quarantined(tmp_path, source):
    source.rows[122].append(deepcopy(source.rows[118][0]))
    root = tmp_path / "capture"
    receipt = capture.capture_catalog(source, root, game_scope="six-games")
    report = capture.compare_captured_catalog(root, [], CATEGORIES)
    assert receipt["status"] == "complete_with_source_anomalies"
    assert report["sourceRows"] == 7 and report["sourceAnomalyCount"] == 1
    offending = report["details"][-1]
    assert offending["sourceExpansionId"] == 122
    assert offending["decision"] == "source_export_conflict"


def test_new_game_export_404_is_accounted_and_retried_next_cycle(tmp_path, source):
    source.unavailable = {122}
    root = tmp_path / "first"
    receipt = capture.capture_catalog(source, root, game_scope="six-games")
    report = capture.compare_captured_catalog(root, [], CATEGORIES)
    assert receipt["completedExpansions"] == 5 and not report["sourceComplete"]
    assert report["deferredExpansions"] == [
        {"expansionId": 122, "httpStatus": 404, "reason": "export_http_404"}
    ]
    source.unavailable.clear()
    assert (
        capture.capture_catalog(source, tmp_path / "second", game_scope="six-games")[
            "completedExpansions"
        ]
        == 6
    )


@pytest.mark.parametrize("game_id,category", [(18, 231), (22, 283), (18, 215), (22, 259)])
def test_complete_sets_and_sealed_never_become_printing_candidates(source, game_id, category):
    row = {**source.rows[100 + game_id][0], "category_id": category}
    result = compare_catalog(
        [row], [], {i: (g, f) for i, (g, _, f) in CATEGORIES.items()}, {100 + game_id: game_id}
    )
    assert result[0]["decision"] == (
        "unclassified_category" if category in (231, 283) else "non_card_category"
    )


@pytest.mark.parametrize("other_game", [1, 18])
def test_cross_game_cardmarket_collision_is_quarantined(source, other_game):
    rows = [source.rows[122][0], source.rows[100 + other_game][0]]
    rows[1]["card_market_ids"] = rows[0]["card_market_ids"]
    report = compare_catalog(
        rows,
        [],
        {i: (g, f) for i, (g, _, f) in CATEGORIES.items()},
        {row["expansion_id"]: row["game_id"] for row in rows},
    )
    assert [r["decision"] for r in report] == ["shared_cardmarket_id"] * 2


def _prepared_reference(args):
    prepared = json.loads((args["run"] / "reference" / "preparation.json").read_bytes())
    bundle = args["run"] / "reference" / "bundle"
    manifest = load_canonical_names_manifest(
        (bundle / MANIFEST_FILENAME).read_bytes(),
        expected_sha256=prepared["referenceEvidence"]["manifestSha256"],
    )
    assert manifest.schema_version == 2
    with (bundle / SIDECAR_FILENAME).open("rb") as stream:
        return prepared, load_canonical_names(stream, manifest=manifest)


def test_six_game_capture_to_reference_to_import_preview(import_case, source, tmp_path):
    args, original, api, events = import_case
    parent = Path(original["reference"])
    old_manifest = (parent / MANIFEST_FILENAME).read_bytes()
    old_sidecar = (parent / SIDECAR_FILENAME).read_bytes()
    root = args["capture"].with_name("six-capture")
    capture.capture_catalog(source, root, game_scope="six-games")
    args["capture"] = root
    result = importer.run_locked(**args, max_attempts=100)
    assert result["status"] == "preview" and result["candidates"] == result["selected"] == 6
    assert result["exceptions"] == 0 and result["attempts"] == []
    prepared, records = _prepared_reference(args)
    assert prepared["gameScope"] == "six-games"
    assert {c["game"] for c in prepared["candidates"]} == set(GAMES.values())
    added = [record for record in records.values() if int(record.source_id) >= 2000]
    assert len(added) == 6
    assert all(record.card_metadata.rarity == "Rare" for record in added)
    assert all(record.card_metadata.collector_number == "012" for record in added)
    assert all(record.canonical_card_name == "Shared Card" for record in added)
    assert all(
        record.card_metadata.expansion_code is None
        for record in added
        if record.game not in (Game.LORCANA, Game.RIFTBOUND)
    )
    assert (parent / MANIFEST_FILENAME).read_bytes() == old_manifest
    assert (parent / SIDECAR_FILENAME).read_bytes() == old_sidecar
    merged_lines = (args["run"] / "reference" / "bundle" / SIDECAR_FILENAME).read_bytes()
    assert (
        b"".join(
            line
            for line in merged_lines.splitlines(keepends=True)
            if int(json.loads(line)["sourceId"]) < 2000
        )
        == old_sidecar
    )
    projected = []
    for record in added:
        product = page_tests._record(record.source_id, game=record.game)
        projected.append(
            replace(
                product,
                canonical_card_name=record.canonical_card_name,
                card_metadata=record.card_metadata,
                powertools_source_id=record.source_id,
                sync_source_id=record.source_id,
                total_inventory=0,
                variants=(replace(product.variants[0], inventory_quantity=0),),
            )
        )
    projection = page_tests._projection(tmp_path, tuple(projected))
    for game_id, expansion_code in NEW_EXPANSION_CODES.items():
        request = page_tests._request(
            game=Game(GAMES[game_id]), family=RequestFamily.SINGLE, query="Shared Card"
        )
        sets, rarities = projection.metadata_facets(request)
        assert [(value.value, value.count) for value in sets.values] == [(expansion_code, 1)]
        assert [(value.value, value.count) for value in rarities.values] == [("Rare", 1)]
        selected = replace(
            request,
            filters=CatalogFiltersV1(False, None, expansion_code=expansion_code, rarity="Rare"),
        )
        page = page_tests._paginator(projection).fetch_page(selected).page
        assert [item.product_gid for item in page.items] == [
            f"gid://shopify/Product/{2000 + game_id}"
        ]
        wrong = replace(selected, filters=replace(selected.filters, expansion_code="missing"))
        assert page_tests._paginator(projection).fetch_page(wrong).page.items == ()
    assert json.loads(args["config_path"].read_bytes()) == original
    assert not api.calls and not events


@pytest.mark.parametrize("code", ["absent", None, "", 123, True, [], {}])
def test_preparation_new_expansion_codes_preserve_missing_and_quarantine_invalid(
    import_case, source, code
):
    args, original, api, events = import_case
    for expansion in source.expansions:
        if expansion["game_id"] in NEW_EXPANSION_CODES:
            if code == "absent":
                del expansion["code"]
            else:
                expansion["code"] = code
    root = args["capture"].with_name("six-capture")
    capture.capture_catalog(source, root, game_scope="six-games")
    args["capture"] = root
    result = importer.run_locked(**args, max_attempts=100)
    invalid = code not in ("absent", None, "")
    assert result["status"] == "preview"
    assert result["exceptions"] == (2 if invalid else 0)
    assert result["candidates"] == (4 if invalid else 6)
    prepared = json.loads((args["run"] / "reference" / "preparation.json").read_bytes())
    if invalid:
        assert {row["blueprintId"] for row in prepared["exceptions"]} == {1018, 1022}
    else:
        _, records = _prepared_reference(args)
        assert all(
            record.card_metadata.expansion_code is None
            for record in records.values()
            if int(record.source_id) >= 2000
        )
    assert json.loads(args["config_path"].read_bytes()) == original
    assert not api.calls and not events


@pytest.mark.parametrize("game", ["lorcana", "riftbound"])
def test_new_game_draft_keeps_identity_guard_and_does_not_resend(tmp_path, game):
    api = FakeShopify()
    result = create_draft(tmp_path, api, game=game)
    assert result["status"] == "draft_verified"
    created = [variables for query, variables in api.calls if query == CREATE_DRAFT]
    assert len(created) == 1 and created[0]["product"]["productType"] == PRODUCT_TYPES[game]
    calls = len(api.calls)
    assert create_draft(tmp_path, api, game=game)["status"] == "already_reserved"
    assert len(api.calls) == calls
    other = "riftbound" if game == "lorcana" else "lorcana"
    assert create_draft(tmp_path, api, game=other)["status"] == "already_reserved"
    assert len(api.calls) == calls


def test_market_cycle_forwards_explicit_scope_and_keeps_default(market_case):
    args, _, behavior = market_case
    first = market_tests.market.cycle(**args)
    assert first["gameScope"] == behavior["game_scope"] == "legacy"
    second = market_tests.market.cycle(**args, game_scope="six-games")
    assert second["gameScope"] == behavior["game_scope"] == "six-games"
    assert second["published"] is False
    with pytest.raises(ValueError, match="invalid_game_scope"):
        market_tests.market.cycle(**args, game_scope="unknown")
