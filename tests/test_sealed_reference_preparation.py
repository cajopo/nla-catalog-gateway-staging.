"""Reduced offline regressions for historical sealed canonical-name records."""

import csv
import hashlib
import json
import sqlite3
from contextlib import closing
from types import SimpleNamespace

import pytest
from scripts.compare_cardtrader_catalog import CATEGORIES, compare_projection
from scripts.prepare_cardtrader_reference import prepare

from nla_catalog_gateway.canonical_names import (
    CANONICAL_GAME_ORDER,
    CSV_HEADER,
    MANIFEST_FILENAME,
    SIDECAR_FILENAME,
    build_canonical_name_sidecar,
)
from nla_catalog_gateway.cardtrader_capture import capture_catalog
from test_shopify_draft_import import FakeShopify
from test_shopify_draft_import import run as create

SAMPLES = (
    (102393, 254468, 1030, "Legend of Blue Eyes White Dragon Booster Box"),
    (102398, 254470, 1035, "Spell Ruler Booster Box"),
)


@pytest.fixture
def sealed_reference_case(tmp_path):
    def run(reference_case="same_game", shopify_case=None):
        sources = {}
        for index, game in enumerate(CANONICAL_GAME_ORDER):
            path = tmp_path / f"{game.value}.csv"
            with path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.writer(stream)
                writer.writerow(CSV_HEADER)
                writer.writerow([index + 1, "Unrelated mapping", "", "", "", "", "", ""])
                include = game.value == "yugioh" and reference_case != "cross_game"
                include |= game.value == "magic" and reference_case in ("cross_game", "ambiguous")
                if include:
                    for _, cardmarket, _, title in SAMPLES:
                        name = (
                            "Historical source spelling" if reference_case == "old_name" else title
                        )
                        writer.writerow([cardmarket, name, "", "", "Old Set", "OLD", "", ""])
            sources[game] = path
        parent = tmp_path / "reference"
        manifest = build_canonical_name_sidecar(
            sources, output_directory=parent, generator_code_sha="a" * 40
        )
        before = {
            name: (parent / name).read_bytes() for name in (MANIFEST_FILENAME, SIDECAR_FILENAME)
        }
        rows = {
            expansion: [
                dict(
                    id=blueprint,
                    game_id=4,
                    expansion_id=expansion,
                    category_id=54,
                    card_market_ids=[cardmarket],
                    name=title,
                    fixed_properties={},
                    image_url=f"https://example.com/synthetic-sealed-{blueprint}.jpg",
                )
            ]
            for blueprint, cardmarket, expansion, title in SAMPLES
        }

        def collection(kind, **kwargs):
            if kind == "games":
                return [dict(id=i) for i in (1, 4, 5, 15)]
            if kind == "categories":
                return [dict(id=i, game_id=g, name=n) for i, (g, n, _) in CATEGORIES.items()]
            if kind == "expansions":
                return [
                    dict(id=expansion, game_id=4, name="Synthetic Set")
                    for _, _, expansion, _ in SAMPLES
                ] + [dict(id=100 + g, game_id=g, name="Empty Set") for g in (1, 5, 15)]
            return rows.get(kwargs["expansion_id"], [])

        capture = tmp_path / "capture"
        capture_catalog(SimpleNamespace(collection=collection), capture)
        projection = tmp_path / "projection.sqlite3"
        with closing(sqlite3.connect(projection)) as db, db:
            db.execute("CREATE TABLE projection_metadata(dataset_manifest_json TEXT)")
            db.execute(
                "INSERT INTO projection_metadata VALUES (?)",
                (json.dumps({"generatedAt": "2026-10-31T04:41:05Z"}),),
            )
            db.execute("CREATE TABLE products(product_record_json TEXT)")
            if shopify_case:
                for _, cardmarket, _, _ in SAMPLES:
                    db.execute(
                        "INSERT INTO products VALUES (?)",
                        (
                            json.dumps(
                                dict(
                                    productGid=f"gid://shopify/Product/{cardmarket}",
                                    game="magic" if shopify_case == "wrong_game" else "yugioh",
                                    productFamily="single"
                                    if shopify_case == "wrong_family"
                                    else "sealed",
                                    syncSourceId=str(cardmarket),
                                    powerToolsSourceId=str(cardmarket),
                                )
                            ),
                        ),
                    )
        pin = hashlib.sha256(projection.read_bytes()).hexdigest()
        compared = compare_projection(capture, projection, pin)
        result = prepare(
            capture,
            projection,
            pin,
            parent,
            manifest.manifest_sha256,
            tmp_path / "prepared",
            "b" * 40,
        )
        assert result["reference"] == str(parent)
        assert result["referenceEvidence"]["addedRecords"] == 0
        assert result["shopifyChanged"] is False
        assert all((parent / name).read_bytes() == raw for name, raw in before.items())
        assert hashlib.sha256(projection.read_bytes()).hexdigest() == pin
        return result, compared

    return run


@pytest.mark.parametrize("reference_case", ["same_game", "old_name"])
def test_same_game_reference_does_not_classify_sealed_source(sealed_reference_case, reference_case):
    result, compared = sealed_reference_case(reference_case)
    assert result["exceptions"] == []
    assert [row["decision"] for row in compared["details"]] == ["absent_from_supplied_snapshot"] * 2
    assert [
        (row["blueprintId"], row["cardmarketId"], row["title"]) for row in result["candidates"]
    ] == [(blueprint, str(cardmarket), title) for blueprint, cardmarket, _, title in SAMPLES]
    for row in result["candidates"]:
        assert row["game"] == "yugioh" and row["productFamily"] == "sealed"
        assert row["creationApproved"] is False
        assert row["canonicalMappingPreserved"] is False  # Sealed title comes from source.


@pytest.mark.parametrize("reference_case", ["cross_game", "ambiguous"])
def test_sealed_canonical_ambiguity_and_cross_game_stay_quarantined(
    sealed_reference_case, reference_case
):
    result, _ = sealed_reference_case(reference_case)
    assert result["candidates"] == []
    assert len(result["exceptions"]) == 2
    assert all(
        row["reason"] == "source_or_canonical_details_require_review"
        for row in result["exceptions"]
    )


@pytest.mark.parametrize("shopify_case", ["matching", "wrong_family", "wrong_game"])
def test_existing_shopify_identity_still_excludes_same_game_reference_candidates(
    sealed_reference_case, shopify_case
):
    result, compared = sealed_reference_case(shopify_case=shopify_case)
    expected = (
        "existing_identity_match" if shopify_case == "matching" else "shopify_identity_conflict"
    )
    assert [row["decision"] for row in compared["details"]] == [expected] * 2
    assert result["candidates"] == [] and result["exceptions"] == []


def test_prepared_sealed_reference_candidate_still_needs_current_absence(
    sealed_reference_case, tmp_path
):
    prepared, _ = sealed_reference_case()
    row = prepared["candidates"][0]
    api = FakeShopify()
    result = create(
        tmp_path,
        api,
        blueprint_id=row["blueprintId"],
        cardmarket_id=int(row["cardmarketId"]),
        game=row["game"],
        product_family=row["productFamily"],
        title=row["title"],
        image_url=row["imageUrl"],
        verify_missing=lambda: False,
    )
    assert result["status"] == "not_verified_missing"
    assert api.calls and all(not query.lstrip().startswith("mutation") for query, _ in api.calls)
    with closing(sqlite3.connect(tmp_path / "ledger.sqlite")) as db:
        assert db.execute("SELECT count(*) FROM draft_attempts").fetchone()[0] == 0
