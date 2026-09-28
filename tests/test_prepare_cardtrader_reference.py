import csv
import hashlib
import json
import sqlite3
from contextlib import closing
from types import SimpleNamespace

import pytest
from scripts import prepare_cardtrader_reference as prepare
from scripts.compare_cardtrader_catalog import CATEGORIES

from nla_catalog_gateway import cardtrader_capture
from nla_catalog_gateway.canonical_names import (
    CANONICAL_GAME_ORDER,
    CSV_HEADER,
    SIDECAR_FILENAME,
    build_canonical_name_sidecar,
)


@pytest.mark.parametrize(
    "case",
    [
        "extend",
        "preserve",
        "bad_image",
        "bad_metadata",
        "name_conflict",
        "cross_game",
        "no_candidates",
        "ambiguous_parent",
        "malformed_expansion",
    ],
)
def test_capture_projection_to_reference_preparation(tmp_path, monkeypatch, case):
    sources = {}
    for index, game in enumerate(CANONICAL_GAME_ORDER):
        path = tmp_path / f"{game.value}.csv"
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(CSV_HEADER)
            source_id = 1 if case == "ambiguous_parent" else index + 1
            writer.writerow([str(source_id), "Original", "007", "Common", "Old Set", "", "", ""])
        sources[game] = path
    parent = tmp_path / "parent"
    manifest = build_canonical_name_sidecar(
        sources, output_directory=parent, generator_code_sha="a" * 40
    )
    before = (parent / SIDECAR_FILENAME).read_bytes()
    gids = (1, 4, 5, 15)
    cats = {1: 1, 4: 44, 5: 73, 15: 192}
    source_id = 1 if case in ("preserve", "name_conflict", "ambiguous_parent") else 100
    if case == "cross_game":
        source_id = 2  # A unique identity belonging to another baseline game.

    def collection(kind, **kwargs):
        if kind == "games":
            return [dict(id=i) for i in gids]
        if kind == "categories":
            return [dict(id=i, game_id=g, name=n) for i, (g, n, _) in CATEGORIES.items()]
        if kind == "expansions":
            rows = [dict(id=i, game_id=i, name="New Set") for i in gids]
            if case == "malformed_expansion":
                rows.append(dict(id=1, game_id=True, name="Wrong Set"))
            return rows
        i = kwargs["expansion_id"]
        if i != 1 or case == "no_candidates":
            return []
        return [
            dict(
                id=10,
                game_id=1,
                expansion_id=1,
                category_id=cats[1],
                card_market_ids=[source_id],
                name="Original" if case in ("preserve", "ambiguous_parent") else "New Card",
                image_url="http://invalid/image"
                if case == "bad_image"
                else "https://cardtrader.com/image.jpg",
                fixed_properties={
                    "collector_number": 12 if case == "bad_metadata" else "012",
                    "mtg_rarity": "Common",
                },
                editable_properties=[{"name": "condition", "default_value": "Near Mint"}],
            )
        ]

    monkeypatch.setattr(cardtrader_capture.time, "sleep", lambda _: None)
    monkeypatch.setattr(
        cardtrader_capture.shutil, "disk_usage", lambda _: SimpleNamespace(free=8 * 1024**3)
    )
    capture = tmp_path / "capture"
    cardtrader_capture.capture_catalog(SimpleNamespace(collection=collection), capture)
    projection = tmp_path / "projection.sqlite3"
    with closing(sqlite3.connect(projection)) as db:
        db.execute("CREATE TABLE projection_metadata(dataset_manifest_json TEXT)")
        db.execute(
            "INSERT INTO projection_metadata VALUES (?)",
            (json.dumps({"generatedAt": "2026-09-26T00:00:00Z"}),),
        )
        db.execute("CREATE TABLE products(product_record_json TEXT)")
        db.commit()
    pin = hashlib.sha256(projection.read_bytes()).hexdigest()
    output = tmp_path / "prepared"
    result = prepare.prepare(
        capture, projection, pin, parent, manifest.manifest_sha256, output, "b" * 40
    )
    assert (parent / SIDECAR_FILENAME).read_bytes() == before
    assert result["creationApproved"] is False and result["shopifyChanged"] is False
    assert result["referenceEvidence"]["activated"] is False
    assert result["referenceEvidence"]["addedRecords"] == (
        1 if case in ("extend", "malformed_expansion") else 0
    )
    assert len(result["exceptions"]) == (
        1 if case in ("bad_image", "bad_metadata", "cross_game", "ambiguous_parent") else 0
    )
    assert len(result["candidates"]) == (
        1 if case in ("extend", "preserve", "name_conflict", "malformed_expansion") else 0
    )
    if result["candidates"]:
        item = result["candidates"][0]
        assert item["creationApproved"] is False and item["canonicalMappingPreserved"] == (
            case in ("preserve", "name_conflict")
        )
        assert item["sourceRowIndex"] == 0 and item["sourceFile"] == "blueprints-1.json"
        assert item["title"] == (
            "Original - Old Set [007]"
            if case in ("preserve", "name_conflict")
            else "New Card - New Set [012]"
        )
        assert item["sourceNameDiffers"] is (case == "name_conflict")
        if case in ("preserve", "name_conflict"):
            assert result["reference"] == str(parent)
        assert not {"price", "quantity", "language", "condition", "finish"} & set(item)
    with pytest.raises(FileExistsError):
        prepare.prepare(
            capture, projection, pin, parent, manifest.manifest_sha256, output, "b" * 40
        )
