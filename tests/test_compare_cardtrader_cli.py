import hashlib
import json
import sqlite3
import sys
from contextlib import closing
from types import SimpleNamespace

import pytest
from scripts import compare_cardtrader_catalog as cli

from nla_catalog_gateway import cardtrader_capture


@pytest.mark.parametrize(
    "case",
    [
        "success",
        "integrated",
        "bad_hash",
        "wal",
        "existing_output",
        "relative_output",
        "projection_race",
    ],
)
def test_projection_comparison_is_pinned_readonly_and_never_overwrites(
    tmp_path, monkeypatch, capsys, case
):
    projection = tmp_path / "projection.sqlite3"
    product = dict(
        productGid="gid://shopify/Product/1",
        game="magic",
        productFamily="single",
        syncSourceId="42",
        powerToolsSourceId="42",
    )
    with closing(sqlite3.connect(projection)) as database:
        database.execute("CREATE TABLE projection_metadata(dataset_manifest_json TEXT)")
        database.execute(
            "INSERT INTO projection_metadata VALUES (?)",
            (json.dumps({"generatedAt": "2026-09-26T00:00:00Z"}),),
        )
        database.execute("CREATE TABLE products(product_record_json TEXT)")
        database.execute("INSERT INTO products VALUES (?)", (json.dumps(product),))
        database.commit()
    original = projection.read_bytes()
    digest = hashlib.sha256(original).hexdigest()
    output = tmp_path / "comparison.json"
    capture = tmp_path / "capture"

    def compare(path, products, categories):
        assert path == capture and products == [product] and categories == cli.CATEGORIES
        if case == "projection_race":
            projection.write_bytes(original + b"changed")
        return {
            "status": "read_only_comparison_complete",
            "sourceRows": 1,
            "details": [],
            "creationApproved": False,
            "shopifyChanged": False,
        }

    if case == "integrated":
        games = (1, 4, 5, 15)
        categories = {1: 1, 4: 44, 5: 73, 15: 192}

        def collection(kind, **kwargs):
            if kind == "games":
                return [{"id": i} for i in games]
            if kind == "categories":
                return [dict(id=i, game_id=g, name=n) for i, (g, n, _) in cli.CATEGORIES.items()]
            if kind == "expansions":
                return [dict(id=i, game_id=i) for i in games]
            i = kwargs["expansion_id"]
            return [
                dict(
                    id=i * 10,
                    game_id=i,
                    expansion_id=i,
                    category_id=categories[i],
                    card_market_ids=[42 if i == 1 else i * 100],
                )
            ]

        monkeypatch.setattr(cardtrader_capture.time, "sleep", lambda _: None)
        monkeypatch.setattr(
            cardtrader_capture.shutil, "disk_usage", lambda _: SimpleNamespace(free=8 * 1024**3)
        )
        cardtrader_capture.capture_catalog(SimpleNamespace(collection=collection), capture)
    else:
        monkeypatch.setattr(cli, "compare_captured_catalog", compare)
    if case == "bad_hash":
        digest = "0" * 64
    if case == "wal":
        projection.with_name(projection.name + "-wal").write_bytes(b"unsafe")
    if case == "existing_output":
        output.write_text("keep me")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "compare",
            "--capture",
            str(capture),
            "--projection",
            str(projection),
            "--projection-sha256",
            digest,
            "--output",
            "relative" if case == "relative_output" else str(output),
        ],
    )
    assert cli.main() == (0 if case in ("success", "integrated") else 1)
    assert projection.read_bytes() == original + (b"changed" if case == "projection_race" else b"")
    result = json.loads(capsys.readouterr().out)
    assert result["creationApproved"] is False
    if case in ("success", "integrated"):
        assert json.loads(output.read_text())["projectionSha256"] == digest
        if case == "integrated":
            report = json.loads(output.read_text())
            assert report["sourceRows"] == 4 and len(report["details"]) == 4
            assert [r["decision"] for r in report["details"]] == ["existing_identity_match"] + [
                "absent_from_supplied_snapshot"
            ] * 3
    elif case == "existing_output":
        assert output.read_text() == "keep me"
    else:
        assert not output.exists()
