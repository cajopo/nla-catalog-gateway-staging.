from __future__ import annotations

import hashlib
import importlib.util
import json
import runpy
import sys
from pathlib import Path

import pytest

CLI_PATH = Path(__file__).resolve().parents[1] / "scripts" / "validate_bulk_snapshot.py"
CLI_SPEC = importlib.util.spec_from_file_location("scripts.validate_bulk_snapshot", CLI_PATH)
if CLI_SPEC is None or CLI_SPEC.loader is None:
    raise ImportError("cannot load validate_bulk_snapshot.py for tests")
cli = importlib.util.module_from_spec(CLI_SPEC)
CLI_SPEC.loader.exec_module(cli)


def _cli_files(tmp_path: Path) -> tuple[Path, Path, Path]:
    query = tmp_path / "query.graphql"
    query.write_text("query Synthetic { products { edges { node { id } } } }\n", encoding="utf-8")
    rows = [
        {
            "__typename": "Product",
            "id": "gid://shopify/Product/1",
            "handle": "one",
            "title": "One",
            "status": "ACTIVE",
            "vendor": "NLA",
            "productType": "Magic Single",
            "tags": ["Magic"],
            "createdAt": "2026-09-01T00:00:00Z",
            "updatedAt": "2026-09-01T00:00:00Z",
            "publishedAt": None,
            "onlineStoreUrl": None,
            "totalInventory": 1,
            "tracksInventory": True,
            "variantsCount": {"count": 1},
            "featuredMedia": None,
            "syncProductId": None,
            "powertoolsId": None,
        },
        {
            "__typename": "ProductVariant",
            "id": "gid://shopify/ProductVariant/11",
            "__parentId": "gid://shopify/Product/1",
            "title": "Default Title",
            "sku": None,
            "barcode": None,
            "selectedOptions": [{"name": "Title", "value": "Default Title"}],
            "price": "1.00",
            "compareAtPrice": None,
            "inventoryQuantity": 1,
            "inventoryPolicy": "DENY",
            "updatedAt": "2026-09-01T00:00:00Z",
            "inventoryItem": {
                "__typename": "InventoryItem",
                "id": "gid://shopify/InventoryItem/11",
                "tracked": True,
            },
        },
        {
            "__typename": "ResourcePublicationV2",
            "__parentId": "gid://shopify/Product/1",
            "isPublished": False,
            "publishDate": None,
            "publication": {
                "id": "gid://shopify/Publication/1",
                "autoPublish": False,
                "catalog": {
                    "__typename": "AppCatalog",
                    "id": "gid://shopify/AppCatalog/1",
                    "title": "Online Store",
                },
            },
        },
    ]
    snapshot = tmp_path / "source.jsonl"
    raw = b"".join(json.dumps(row, separators=(",", ":")).encode() + b"\n" for row in rows)
    snapshot.write_bytes(raw)
    evidence = {
        "shopDomain": "synthetic.myshopify.com",
        "apiVersion": "2026-07",
        "operationId": "gid://shopify/BulkOperation/1",
        "status": "COMPLETED",
        "partialDataUrlPresent": False,
        "fileSize": len(raw),
        "objectCount": len(rows),
        "productCount": 1,
        "expectedActiveOnlineStorePublishedProductCount": 0,
        "querySha256": hashlib.sha256(query.read_bytes()).hexdigest(),
        "onlineStorePublicationGid": "gid://shopify/Publication/1",
        "completedAt": "2026-09-01T00:00:00Z",
        "sourceCodeSha": "a" * 40,
    }
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    return snapshot, query, evidence_path


def test_cli_success_and_failure(tmp_path: Path, capsys) -> None:
    snapshot, query, evidence = _cli_files(tmp_path)
    output = tmp_path / "candidate"
    args = [
        str(snapshot),
        "--query",
        str(query),
        "--evidence",
        str(evidence),
        "--output",
        str(output),
        "--expected-source-code-sha",
        "a" * 40,
    ]
    assert cli.main(args) == 0
    assert json.loads(capsys.readouterr().out)["objectCounts"]["Product"] == 1

    assert cli.main(args) == 2
    captured = capsys.readouterr()
    assert captured.err == "source candidate rejected\n"
    assert captured.out == ""


def test_script_main_guard(tmp_path: Path, monkeypatch) -> None:
    snapshot, query, evidence = _cli_files(tmp_path)
    output = tmp_path / "candidate"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "validate_bulk_snapshot.py",
            str(snapshot),
            "--query",
            str(query),
            "--evidence",
            str(evidence),
            "--output",
            str(output),
            "--expected-source-code-sha",
            "a" * 40,
        ],
    )
    with pytest.raises(SystemExit, match="0"):
        runpy.run_path(cli.__file__, run_name="__main__")


def test_cli_binds_source_sha_and_never_echoes_attacker_source(tmp_path: Path, capsys) -> None:
    snapshot, query, evidence = _cli_files(tmp_path)
    output = tmp_path / "mismatch"
    base_args = [
        str(snapshot),
        "--query",
        str(query),
        "--evidence",
        str(evidence),
        "--output",
        str(output),
        "--expected-source-code-sha",
        "b" * 40,
    ]
    assert cli.main(base_args) == 2
    assert capsys.readouterr().err == "source candidate rejected\n"
    assert not output.exists()

    sentinel = "https://signed.example/object?token=TOPSECRET-" + "x" * 100_000
    raw = json.dumps({"__typename": sentinel}, separators=(",", ":")).encode() + b"\n"
    snapshot.write_bytes(raw)
    evidence_payload = json.loads(evidence.read_text(encoding="utf-8"))
    evidence_payload.update(fileSize=len(raw), objectCount=1, productCount=1)
    evidence.write_text(json.dumps(evidence_payload), encoding="utf-8")
    attack_output = tmp_path / "attack"
    attack_args = [
        *base_args[:-3],
        str(attack_output),
        "--expected-source-code-sha",
        "a" * 40,
    ]
    assert cli.main(attack_args) == 2
    captured = capsys.readouterr()
    assert captured.err == "source candidate rejected\n"
    assert "TOPSECRET" not in captured.err
    assert len(captured.err) < 256
    assert not attack_output.exists()

    surrogate = b'{"__typename":"Product","title":"\\ud800"}\n'
    snapshot.write_bytes(surrogate)
    evidence_payload["fileSize"] = len(surrogate)
    evidence.write_text(json.dumps(evidence_payload), encoding="utf-8")
    surrogate_output = tmp_path / "surrogate"
    surrogate_args = [
        *base_args[:-3],
        str(surrogate_output),
        "--expected-source-code-sha",
        "a" * 40,
    ]
    assert cli.main(surrogate_args) == 2
    assert capsys.readouterr().err == "source candidate rejected\n"
    assert not surrogate_output.exists()

    with pytest.raises(SystemExit, match="2"):
        cli.parse_args(
            [
                str(snapshot),
                "--query",
                str(query),
                "--evidence",
                str(evidence),
                "--output",
                str(tmp_path / "missing-arg"),
            ]
        )
