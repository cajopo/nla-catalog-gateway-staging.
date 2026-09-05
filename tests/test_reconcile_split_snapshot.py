from __future__ import annotations

import hashlib
import json
import os
import runpy
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from scripts import reconcile_split_snapshot as cli

from nla_catalog_gateway.reconciliation import SnapshotPartManifestV1
from nla_catalog_gateway.runtime_contract import (
    CapabilityState,
    CatalogProductRecordV1,
    DatasetManifestV1,
)

PROJECT_ROOT = Path(__file__).parents[1]
PRODUCT_QUERY = PROJECT_ROOT / "graphql" / "catalog_products_snapshot.graphql"
VARIANT_QUERY = PROJECT_ROOT / "graphql" / "catalog_variants_snapshot.graphql"
PUBLICATION = "gid://shopify/Publication/9007199254743001"
SNAPSHOT_SET = "sha256:" + "b" * 64
SOURCE_SHA = "a" * 40
NOW = "2026-09-05T10:00:00Z"
LATER = "2026-09-05T10:01:00Z"


@dataclass(frozen=True)
class InputSet:
    products_snapshot: Path
    variants_snapshot: Path
    products_query: Path
    variants_query: Path
    products_terminal: Path
    variants_terminal: Path
    expectation_path: Path

    def kwargs(self, output: Path) -> dict[str, Path]:
        return {
            "products_snapshot": self.products_snapshot,
            "variants_snapshot": self.variants_snapshot,
            "products_query": self.products_query,
            "variants_query": self.variants_query,
            "products_terminal": self.products_terminal,
            "variants_terminal": self.variants_terminal,
            "expectation_path": self.expectation_path,
            "output_directory": output,
        }

    def argv(self, output: Path) -> list[str]:
        return [
            "--products-jsonl",
            str(self.products_snapshot),
            "--variants-jsonl",
            str(self.variants_snapshot),
            "--products-query",
            str(self.products_query),
            "--variants-query",
            str(self.variants_query),
            "--products-terminal",
            str(self.products_terminal),
            "--variants-terminal",
            str(self.variants_terminal),
            "--expectation",
            str(self.expectation_path),
            "--output-directory",
            str(output),
        ]


def gid(kind: str, number: int) -> str:
    return f"gid://shopify/{kind}/{number}"


def product_rows() -> list[dict[str, object]]:
    product = 9_007_199_254_740_993
    return [
        {
            "__typename": "Product",
            "id": gid("Product", product),
            "handle": "synthetic-cli-product",
            "title": "Synthetic CLI display",
            "status": "ACTIVE",
            "vendor": "Synthetic vendor",
            "productType": "Magic Display",
            "tags": ["Magic", "Synthetic"],
            "createdAt": NOW,
            "updatedAt": LATER,
            "publishedAt": NOW,
            "onlineStoreUrl": None,
            "totalInventory": 0,
            "tracksInventory": True,
            "variantsCount": {"count": 1},
            "featuredMedia": None,
            "syncProductId": {"type": "number_integer", "value": "9007199254745001"},
            "powertoolsId": {
                "type": "single_line_text_field",
                "value": "9007199254745001",
            },
        },
        {
            "__typename": "ResourcePublicationV2",
            "__parentId": gid("Product", product),
            "isPublished": True,
            "publishDate": NOW,
            "publication": {"id": PUBLICATION, "autoPublish": False, "catalog": None},
        },
    ]


def variant_rows() -> list[dict[str, object]]:
    product = 9_007_199_254_740_993
    variant = 9_007_199_254_741_101
    item = 9_007_199_254_742_001
    return [
        {
            "__typename": "ProductVariant",
            "id": gid("ProductVariant", variant),
            "title": "Synthetic variant",
            "sku": "SYNTHETIC-CLI",
            "barcode": None,
            "selectedOptions": [{"name": "Language", "value": "Synthetic"}],
            "price": "0.00",
            "compareAtPrice": None,
            "inventoryQuantity": 0,
            "inventoryPolicy": "DENY",
            "updatedAt": LATER,
            "product": {"__typename": "Product", "id": gid("Product", product)},
            "inventoryItem": {
                "__typename": "InventoryItem",
                "id": gid("InventoryItem", item),
                "tracked": True,
            },
        },
        {
            "__typename": "InventoryLevel",
            "__parentId": gid("InventoryItem", item),
            "id": f"{gid('InventoryLevel', 9007199254746001)}?inventory_item_id={item}",
            "location": {
                "id": gid("Location", 9007199254746001),
                "name": "Synthetic location",
            },
            "quantities": [
                {"name": name, "quantity": 0}
                for name in ("incoming", "available", "reserved", "committed", "on_hand")
            ],
        },
    ]


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> bytes:
    raw = b"".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
        for row in rows
    )
    path.write_bytes(raw)
    return raw


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, separators=(",", ":")), encoding="utf-8", newline="\n")


def terminal_document(
    *,
    query: Path,
    raw: bytes,
    rows: list[dict[str, object]],
    operation: int,
    root_type: str,
) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "operationId": gid("BulkOperation", operation),
        "operationType": "QUERY",
        "status": "COMPLETED",
        "errorCode": None,
        "query": query.read_text(encoding="utf-8"),
        "createdAt": NOW,
        "completedAt": LATER,
        "fileSize": len(raw),
        "objectCount": len(rows),
        "rootObjectCount": sum(row["__typename"] == root_type for row in rows),
        "urlPresent": True,
        "partialDataUrlPresent": False,
    }


def expectation_document() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "snapshotSetId": SNAPSHOT_SET,
        "shopDomain": "synthetic.myshopify.com",
        "apiVersion": "2026-04",
        "onlineStorePublicationGid": PUBLICATION,
        "sourceCodeSha": SOURCE_SHA,
        "productCount": 1,
        "variantCount": 1,
        "expectedActiveOnlineStorePublishedProductCount": 1,
    }


def make_inputs(tmp_path: Path) -> InputSet:
    source = tmp_path / "source"
    source.mkdir(parents=True)
    products = product_rows()
    variants = variant_rows()
    products_snapshot = source / "products.jsonl"
    variants_snapshot = source / "variants.jsonl"
    products_raw = write_jsonl(products_snapshot, products)
    variants_raw = write_jsonl(variants_snapshot, variants)
    products_terminal = source / "products-terminal.json"
    variants_terminal = source / "variants-terminal.json"
    expectation = source / "expectation.json"
    write_json(
        products_terminal,
        terminal_document(
            query=PRODUCT_QUERY,
            raw=products_raw,
            rows=products,
            operation=1,
            root_type="Product",
        ),
    )
    write_json(
        variants_terminal,
        terminal_document(
            query=VARIANT_QUERY,
            raw=variants_raw,
            rows=variants,
            operation=2,
            root_type="ProductVariant",
        ),
    )
    write_json(expectation, expectation_document())
    return InputSet(
        products_snapshot,
        variants_snapshot,
        PRODUCT_QUERY,
        VARIANT_QUERY,
        products_terminal,
        variants_terminal,
        expectation,
    )


def all_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(all_keys(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(all_keys(item) for item in value))
    return set()


class ControlledHandle:
    def __init__(self, *, short: bool = False, os_error: bool = False) -> None:
        self.short = short
        self.os_error = os_error
        self.closed = False

    def __enter__(self) -> ControlledHandle:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def fileno(self) -> int:
        return 1

    def write(self, raw: bytes) -> int:
        if self.os_error:
            raise OSError("synthetic write error")
        return len(raw) - 1 if self.short else len(raw)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class SyntheticRecord:
    def to_json_bytes(self) -> bytes:
        return b'{"record":"synthetic"}'


def synthetic_generation(*, included_count: int = 1) -> Any:
    return SimpleNamespace(
        records=(SyntheticRecord(),),
        dataset_manifest=SimpleNamespace(
            included_product_count=included_count,
            dataset_generation="sha256:" + "d" * 64,
            to_json_bytes=lambda: b'{"dataset":"synthetic"}',
        ),
        source_manifest_bytes=b'{"source":"synthetic"}',
        source_manifest=SimpleNamespace(
            snapshot_set_id=SNAPSHOT_SET,
            source_generation="sha256:" + "e" * 64,
            variant_count=1,
        ),
        taxonomy_report=SimpleNamespace(
            classified=1,
            unclassified=0,
            rule_version="2026-09-01.1",
            as_dict=lambda: {
                "classificationRuleVersion": "2026-09-01.1",
                "classified": 1,
                "counts": {"sealed": 1},
                "ruleCounts": {"product_type_magic_display": 1},
                "subtypeReasons": {},
                "total": 1,
                "unclassified": 0,
                "unclassifiedReasons": {},
            },
        ),
    )


def synthetic_manifest() -> Any:
    return SimpleNamespace(to_json_bytes=lambda: b'{"part":"synthetic"}')


def synthetic_audits() -> tuple[Any, Any]:
    return (
        cli._TerminalQueryAuditEvidence(
            part=cli.SnapshotPart.PRODUCTS,
            approved_query_sha256="1" * 64,
            raw_terminal_query_sha256="2" * 64,
            transport="canonical-lf-v1",
        ),
        cli._TerminalQueryAuditEvidence(
            part=cli.SnapshotPart.VARIANTS,
            approved_query_sha256="3" * 64,
            raw_terminal_query_sha256="4" * 64,
            transport="canonical-lf-v1",
        ),
    )


def test_complete_generation_is_external_deterministic_and_self_accounting(tmp_path: Path) -> None:
    inputs = make_inputs(tmp_path)
    first_output = tmp_path / "generation-one"
    second_output = tmp_path / "generation-two"

    first_summary = cli.run_reconciliation(**inputs.kwargs(first_output))
    second_summary = cli.run_reconciliation(**inputs.kwargs(second_output))

    expected_files = {
        "catalog-records.v1.jsonl",
        "dataset-manifest.v1.json",
        "products-part-manifest.v1.json",
        "reconciliation-summary.v1.json",
        "source-manifest.v2.json",
        "taxonomy-report.v1.json",
        "variants-part-manifest.v1.json",
    }
    assert {path.name for path in first_output.iterdir()} == expected_files
    assert {path.name for path in second_output.iterdir()} == expected_files
    assert first_summary == second_summary
    for filename in expected_files:
        assert (first_output / filename).read_bytes() == (second_output / filename).read_bytes()

    summary_raw = (first_output / "reconciliation-summary.v1.json").read_bytes()
    summary = json.loads(summary_raw)
    assert summary == first_summary
    assert summary["status"] == "reconciled-provisional"
    assert summary["datasetActivation"] == "not-performed"
    assert summary["capabilityPromotion"] == "not-performed"
    assert summary["catalogRecordCount"] == 1
    assert [audit["part"] for audit in summary["terminalQueryAudits"]] == [
        "products",
        "variants",
    ]
    assert all(audit["transport"] == "canonical-lf-v1" for audit in summary["terminalQueryAudits"])
    assert summary_raw == cli._canonical_json_bytes(summary)
    for artifact in summary["artifacts"]:
        raw = (first_output / artifact["filename"]).read_bytes()
        assert artifact["bytes"] == len(raw)
        assert artifact["sha256"] == hashlib.sha256(raw).hexdigest()

    products_manifest = SnapshotPartManifestV1.from_json_bytes(
        (first_output / "products-part-manifest.v1.json").read_bytes()
    )
    variants_manifest = SnapshotPartManifestV1.from_json_bytes(
        (first_output / "variants-part-manifest.v1.json").read_bytes()
    )
    assert products_manifest.snapshot_set_id == variants_manifest.snapshot_set_id == SNAPSHOT_SET
    dataset = DatasetManifestV1.from_json_bytes(
        (first_output / "dataset-manifest.v1.json").read_bytes()
    )
    assert dataset.dataset_generation == summary["datasetGeneration"]
    assert all(
        state is not CapabilityState.VERIFIED
        for _name, state in (
            *dataset.capability_matrix.features,
            *dataset.capability_matrix.requests,
        )
    )
    record_lines = (first_output / "catalog-records.v1.jsonl").read_bytes().splitlines()
    assert len(record_lines) == 1
    record = CatalogProductRecordV1.from_json_bytes(record_lines[0])
    assert record.product_gid == gid("Product", 9_007_199_254_740_993)
    taxonomy = json.loads((first_output / "taxonomy-report.v1.json").read_bytes())
    assert taxonomy["schemaVersion"] == 1
    assert taxonomy["total"] == 1
    for filename in expected_files:
        value = json.loads((first_output / filename).read_bytes().splitlines()[0])
        assert "url" not in all_keys(value)
        assert "partialDataUrl" not in all_keys(value)


def test_main_emits_only_safe_success_metadata(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inputs = make_inputs(tmp_path)
    output = tmp_path / "generation"

    assert cli.main(inputs.argv(output)) == 0

    captured = capsys.readouterr()
    assert captured.err == ""
    message = json.loads(captured.out)
    assert set(message) == {"datasetGeneration", "outputCreated", "sourceGeneration", "status"}
    assert message["outputCreated"] is True
    assert message["status"] == "ok"
    assert str(output) not in captured.out


def test_signed_url_field_is_rejected_and_failure_is_redacted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inputs = make_inputs(tmp_path)
    document = json.loads(inputs.products_terminal.read_text(encoding="utf-8"))
    signed_value = "sensitive-value-that-must-not-be-echoed"
    document["url"] = signed_value
    write_json(inputs.products_terminal, document)
    output = tmp_path / "generation"

    assert cli.main(inputs.argv(output)) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "split snapshot reconciliation failed"
    assert signed_value not in captured.err
    assert str(inputs.products_terminal) not in captured.err
    assert not output.exists()


@pytest.mark.parametrize(
    "raw",
    [
        b'{"schemaVersion":1,"schemaVersion":1}',
        b'{"schemaVersion":1.0}',
        b"\xef\xbb\xbf{}",
        b"[]",
        b"{}",
    ],
)
def test_control_documents_reject_ambiguous_or_incomplete_json(tmp_path: Path, raw: bytes) -> None:
    path = tmp_path / "control.json"
    path.write_bytes(raw)
    with pytest.raises(cli.ReconciliationCliError):
        cli._load_expectation(path)


def test_control_document_bounds_and_generated_json_fail_closed(tmp_path: Path) -> None:
    empty = tmp_path / "empty.json"
    empty.write_bytes(b"")
    oversized = tmp_path / "oversized.json"
    oversized.write_bytes(b"{" + b" " * cli.CONTROL_DOCUMENT_MAX_BYTES + b"}")
    for path in (empty, oversized):
        with pytest.raises(cli.ReconciliationCliError, match="byte bound"):
            cli._load_control_document(path, "control")
    with pytest.raises(cli.ReconciliationCliError, match="canonical JSON"):
        cli._canonical_json_bytes({"bad": object()})


@pytest.mark.parametrize("version", [True, 0, 2])
def test_control_schema_version_is_exact_integer_one(tmp_path: Path, version: object) -> None:
    path = tmp_path / "expectation.json"
    document = expectation_document()
    document["schemaVersion"] = version
    write_json(path, document)
    with pytest.raises(cli.ReconciliationCliError, match="schemaVersion"):
        cli._load_expectation(path)


def test_terminal_document_has_exact_sanitized_shape(tmp_path: Path) -> None:
    inputs = make_inputs(tmp_path)
    valid = cli._load_terminal_evidence(inputs.products_terminal, "terminal")
    assert valid.url_present is True
    document = json.loads(inputs.products_terminal.read_text(encoding="utf-8"))
    document.pop("urlPresent")
    write_json(inputs.products_terminal, document)
    with pytest.raises(cli.ReconciliationCliError, match="invalid fields"):
        cli._load_terminal_evidence(inputs.products_terminal, "terminal")


def test_query_mismatch_and_independent_counts_fail_before_output(tmp_path: Path) -> None:
    inputs = make_inputs(tmp_path)
    terminal = json.loads(inputs.products_terminal.read_text(encoding="utf-8"))
    terminal["query"] = "query { shop { id } }"
    write_json(inputs.products_terminal, terminal)
    with pytest.raises(Exception, match="query does not match"):
        cli.run_reconciliation(**inputs.kwargs(tmp_path / "query-mismatch"))
    assert not (tmp_path / "query-mismatch").exists()

    inputs = make_inputs(tmp_path / "second")
    expectation = json.loads(inputs.expectation_path.read_text(encoding="utf-8"))
    expectation["productCount"] = 2
    expectation["variantCount"] = 2
    write_json(inputs.expectation_path, expectation)
    with pytest.raises(Exception, match="trusted expectation"):
        cli.run_reconciliation(**inputs.kwargs(tmp_path / "count-mismatch"))
    assert not (tmp_path / "count-mismatch").exists()


def test_exact_shopify_terminal_transport_is_accepted_and_raw_hash_is_audited(
    tmp_path: Path,
) -> None:
    inputs = make_inputs(tmp_path)
    expected_raw_hashes: dict[str, str] = {}
    for part, terminal_path, query_path in (
        ("products", inputs.products_terminal, PRODUCT_QUERY),
        ("variants", inputs.variants_terminal, VARIANT_QUERY),
    ):
        document = json.loads(terminal_path.read_text(encoding="utf-8"))
        transport = query_path.read_bytes().replace(b"\n", b"\r\n") + b"\r\n"
        document["query"] = transport.decode("utf-8")
        write_json(terminal_path, document)
        expected_raw_hashes[part] = hashlib.sha256(transport).hexdigest()

    summary = cli.run_reconciliation(**inputs.kwargs(tmp_path / "generation"))

    assert {
        audit["part"]: audit["rawTerminalQuerySha256"] for audit in summary["terminalQueryAudits"]
    } == expected_raw_hashes
    assert all(
        audit["transport"] == "shopify-crlf-plus-one-terminal-newline-v1"
        for audit in summary["terminalQueryAudits"]
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda canonical: canonical.replace(b"\n", b"\r\n"),
        lambda canonical: canonical + b"\n",
        lambda canonical: canonical.replace(b"\n", b"\r\n") + b"\r\n\r\n",
        lambda canonical: canonical.replace(b"query", b"query Changed", 1),
        lambda canonical: canonical.replace(b"\n", b"\r\n", 1),
        lambda canonical: canonical + b" ",
    ],
)
def test_every_other_terminal_query_difference_is_rejected(tmp_path: Path, mutation: Any) -> None:
    inputs = make_inputs(tmp_path)
    document = json.loads(inputs.products_terminal.read_text(encoding="utf-8"))
    document["query"] = mutation(PRODUCT_QUERY.read_bytes()).decode("utf-8")
    write_json(inputs.products_terminal, document)
    output = tmp_path / "generation"

    with pytest.raises(Exception, match="query does not match"):
        cli.run_reconciliation(**inputs.kwargs(output))
    assert not output.exists()


def test_output_must_be_new_normalized_external_directory(tmp_path: Path) -> None:
    existing = tmp_path / "existing"
    existing.mkdir()
    for value, message in (
        ("not-a-path", "concrete"),
        (Path("relative"), "absolute"),
        (tmp_path / ".." / "escape", "normalized"),
        (tmp_path / "unsafe." / "output", "unsafe"),
        (tmp_path / "unsafe:name", "unsafe"),
        (existing, "already exist"),
        (PROJECT_ROOT / "unsafe-output", "external"),
    ):
        with pytest.raises(cli.ReconciliationCliError, match=message):
            cli._validated_output_directory(value)


def test_input_files_are_absolute_regular_external_and_distinct(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = make_inputs(tmp_path)
    with pytest.raises(cli.ReconciliationCliError, match="concrete"):
        cli._regular_file("bad", "input", external=True)
    with pytest.raises(cli.ReconciliationCliError, match="absolute"):
        cli._regular_file(Path("relative"), "input", external=True)
    with pytest.raises(cli.ReconciliationCliError, match="external"):
        cli._regular_file(PRODUCT_QUERY, "input", external=True)
    with pytest.raises(cli.ReconciliationCliError, match="regular"):
        cli._regular_file(tmp_path, "input", external=True)
    with pytest.raises(cli.ReconciliationCliError, match="distinct"):
        cli.run_reconciliation(
            **{
                **inputs.kwargs(tmp_path / "generation"),
                "variants_terminal": inputs.products_terminal,
            }
        )
    real_alias = cli._path_has_alias
    monkeypatch.setattr(cli, "_path_has_alias", lambda _path: True)
    with pytest.raises(cli.ReconciliationCliError, match="aliases"):
        cli._regular_file(inputs.products_snapshot, "input", external=True)
    monkeypatch.setattr(cli, "_path_has_alias", real_alias)


@pytest.mark.skipif(sys.platform != "win32", reason="NTFS path syntax is Windows-specific")
def test_windows_ads_and_trailing_input_components_are_rejected(tmp_path: Path) -> None:
    carrier = tmp_path / "carrier"
    carrier.write_bytes(b"carrier")
    alternate_stream = Path(f"{carrier}:evidence")
    alternate_stream.write_bytes(b"stream")
    assert alternate_stream.read_bytes() == b"stream"

    for candidate in (alternate_stream, Path(f"{carrier}."), Path(f"{carrier} ")):
        with pytest.raises(cli.ReconciliationCliError, match="normalized"):
            cli._regular_file(candidate, "input", external=True)


def test_every_reparse_attribute_is_treated_as_an_alias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    facts = SimpleNamespace(st_file_attributes=cli._REPARSE_POINT_ATTRIBUTE)
    monkeypatch.setattr(Path, "lstat", lambda _path: facts)
    monkeypatch.setattr(Path, "is_symlink", lambda _path: False)
    monkeypatch.setattr(Path, "is_junction", lambda _path: False)
    assert cli._path_has_alias(tmp_path) is True


def test_atomic_expectation_replacement_is_rejected_before_consumption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = make_inputs(tmp_path)
    replacement = tmp_path / "replacement-expectation.json"
    changed = expectation_document()
    changed["snapshotSetId"] = "sha256:" + "c" * 64
    write_json(replacement, changed)
    real_pin = cli._pin_regular_file
    replaced = False

    def swap_then_pin(
        path: Path,
        state: cli._InputFileState,
        context: str,
        stack: Any,
    ) -> Any:
        nonlocal replaced
        if context == "reconciliation expectation" and not replaced:
            replacement.replace(path)
            replaced = True
        return real_pin(path, state, context, stack)

    monkeypatch.setattr(cli, "_pin_regular_file", swap_then_pin)
    output = tmp_path / "generation"
    with pytest.raises(cli.ReconciliationCliError, match="identity changed"):
        cli.run_reconciliation(**inputs.kwargs(output))
    assert replaced is True
    assert not output.exists()


def test_path_and_filesystem_failures_are_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(cli.ReconciliationCliError, match="unavailable"):
        cli._regular_file(missing, "input", external=True)
    with pytest.raises(cli.ReconciliationCliError, match="cannot be read"):
        cli._load_control_document(missing, "control")

    monkeypatch.setattr(os.path, "commonpath", lambda _paths: (_ for _ in ()).throw(ValueError()))
    assert cli._is_within(tmp_path, PROJECT_ROOT) is False


def test_pinned_input_failures_are_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source.json"
    source.write_bytes(b"{}")
    path, state = cli._regular_file(source, "input", external=True)

    with monkeypatch.context() as patch:
        patch.setattr(cli, "_path_has_alias", lambda _path: True)
        with pytest.raises(cli.ReconciliationCliError, match="aliases"):
            cli._input_state(path, "input")
    with monkeypatch.context() as patch:
        patch.setattr(cli, "_path_has_alias", lambda _path: False)
        patch.setattr(
            Path,
            "lstat",
            lambda _path: (_ for _ in ()).throw(OSError("synthetic state failure")),
        )
        with pytest.raises(cli.ReconciliationCliError, match="cannot be verified"):
            cli._input_state(path, "input")
    with pytest.raises(cli.ReconciliationCliError, match="regular"):
        cli._input_state(tmp_path, "input")

    class BadFileno:
        def fileno(self) -> int:
            raise ValueError("synthetic handle failure")

    with pytest.raises(cli.ReconciliationCliError, match="handle identity"):
        cli._handle_input_state(BadFileno(), "input")  # type: ignore[arg-type]
    with monkeypatch.context() as patch:
        patch.setattr(os, "fstat", lambda _fd: SimpleNamespace(st_mode=0, st_nlink=1))
        with source.open("rb") as handle:
            with pytest.raises(cli.ReconciliationCliError, match="single regular"):
                cli._handle_input_state(handle, "input")
    with monkeypatch.context() as patch:
        patch.setattr(
            Path,
            "open",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("synthetic open failure")),
        )
        with cli.ExitStack() as stack:
            with pytest.raises(cli.ReconciliationCliError, match="opened safely"):
                cli._pin_regular_file(path, state, "input", stack)

    class BadReader:
        def seek(self, _offset: int) -> None:
            raise OSError("synthetic read failure")

    bad_reader = BadReader()
    synthetic = cli._PinnedInputFile(path, state, bad_reader, "input")  # type: ignore[arg-type]
    monkeypatch.setattr(cli, "_verify_pinned_input", lambda _pinned: None)
    with pytest.raises(cli.ReconciliationCliError, match="cannot be read"):
        cli._read_pinned_bytes(synthetic, maximum=10)


def test_alias_probe_detects_links_junctions_and_probe_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with monkeypatch.context() as patch:
        patch.setattr(Path, "is_symlink", lambda _path: True)
        assert cli._path_has_alias(tmp_path) is True
    with monkeypatch.context() as patch:
        patch.setattr(Path, "is_symlink", lambda _path: False)
        patch.setattr(Path, "is_junction", lambda _path: True)
        assert cli._path_has_alias(tmp_path) is True
    with monkeypatch.context() as patch:
        patch.setattr(
            Path,
            "is_symlink",
            lambda _path: (_ for _ in ()).throw(OSError("synthetic probe failure")),
        )
        with pytest.raises(cli.ReconciliationCliError, match="cannot be verified"):
            cli._path_has_alias(tmp_path)


def test_output_alias_and_parent_failures_are_rejected_before_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "generation"
    monkeypatch.setattr(cli, "_path_has_alias", lambda _path: True)
    with pytest.raises(cli.ReconciliationCliError, match="aliases"):
        cli._validated_output_directory(output)

    monkeypatch.setattr(cli, "_path_has_alias", lambda _path: False)
    with pytest.raises(cli.ReconciliationCliError, match="unavailable"):
        cli._validated_output_directory(tmp_path / "missing-parent" / "generation")

    file_parent = tmp_path / "file-parent"
    file_parent.write_bytes(b"x")
    with pytest.raises(cli.ReconciliationCliError, match="must be a directory"):
        cli._validated_output_directory(file_parent / "generation")


def test_directory_identity_is_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    missing = tmp_path / "missing"
    with pytest.raises(cli.ReconciliationCliError, match="cannot be verified"):
        cli._directory_identity(missing)
    regular = tmp_path / "regular"
    regular.write_bytes(b"x")
    with pytest.raises(cli.ReconciliationCliError, match="safe directory"):
        cli._directory_identity(regular)
    directory = tmp_path / "directory"
    directory.mkdir()
    identity = cli._directory_identity(directory)
    with pytest.raises(cli.ReconciliationCliError, match="identity changed"):
        cli._require_directory_identity(
            directory, cli._FileIdentity(identity.device + 1, identity.inode)
        )
    with monkeypatch.context() as patch:
        patch.setattr(cli, "_path_has_alias", lambda _path: True)
        with pytest.raises(cli.ReconciliationCliError, match="safe directory"):
            cli._directory_identity(directory)

    artifact = tmp_path / "artifact"
    artifact.write_bytes(b"artifact")
    artifact_identity = cli._artifact_identity(artifact)
    with pytest.raises(cli.ReconciliationCliError, match="identity changed"):
        cli._require_artifact_identity(
            cli._CreatedArtifact(
                artifact,
                cli._FileIdentity(artifact_identity.device + 1, artifact_identity.inode),
            )
        )
    with monkeypatch.context() as patch:
        patch.setattr(cli, "_path_has_alias", lambda _path: True)
        with pytest.raises(cli.ReconciliationCliError, match="filesystem alias"):
            cli._artifact_identity(artifact)
    with pytest.raises(cli.ReconciliationCliError, match="cannot be verified"):
        cli._artifact_identity(tmp_path / "missing-artifact")


def test_partial_output_is_cleaned_without_recursive_deletion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = make_inputs(tmp_path)
    output = tmp_path / "generation"

    def fail_records(*_args: object, **_kwargs: object) -> Any:
        raise cli.ReconciliationCliError("synthetic write failure")

    monkeypatch.setattr(cli, "_write_records", fail_records)
    with pytest.raises(cli.ReconciliationCliError, match="synthetic"):
        cli.run_reconciliation(**inputs.kwargs(output))
    assert not output.exists()


def test_cleanup_refuses_unknown_or_aliased_artifacts(tmp_path: Path) -> None:
    output = tmp_path / "generation"
    output.mkdir()
    identity = cli._directory_identity(output)
    unsafe = output / "unsafe"
    unsafe.mkdir()
    with pytest.raises(cli.ReconciliationCliError, match="cleaned safely"):
        cli._cleanup_created_output(
            output,
            identity,
            [cli._CreatedArtifact(unsafe, cli._FileIdentity(1, 1))],
        )


def test_cleanup_never_unlinks_a_replacement_artifact(tmp_path: Path) -> None:
    output = tmp_path / "generation"
    output.mkdir()
    directory_identity = cli._directory_identity(output)
    created: list[cli._CreatedArtifact] = []
    path, handle, _artifact = cli._open_output_file(
        output,
        directory_identity,
        "dataset-manifest.v1.json",
        created,
    )
    handle.close()
    replacement = tmp_path / "replacement"
    replacement.write_bytes(b"replacement")
    replacement.replace(path)

    with pytest.raises(cli.ReconciliationCliError, match="cleaned safely"):
        cli._cleanup_created_output(output, directory_identity, created)
    assert path.read_bytes() == b"replacement"


def test_directory_swap_does_not_leave_or_delete_an_unowned_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "generation"
    output.mkdir()
    moved_original = tmp_path / "moved-original"
    replacement_directory = tmp_path / "replacement-directory"
    replacement_directory.mkdir()
    unowned = replacement_directory / "unowned"
    unowned.write_bytes(b"unowned")
    directory_identity = cli._directory_identity(output)
    real_require = cli._require_directory_identity
    calls = 0

    def swap_after_first_check(path: Path, expected: cli._FileIdentity) -> None:
        nonlocal calls
        real_require(path, expected)
        calls += 1
        if calls == 1:
            path.rename(moved_original)
            replacement_directory.rename(path)

    monkeypatch.setattr(cli, "_require_directory_identity", swap_after_first_check)
    created: list[cli._CreatedArtifact] = []
    with pytest.raises(cli.ReconciliationCliError, match="identity changed"):
        cli._open_output_file(
            output,
            directory_identity,
            "dataset-manifest.v1.json",
            created,
        )
    with pytest.raises(cli.ReconciliationCliError, match="cleaned safely"):
        cli._cleanup_created_output(output, directory_identity, created)
    assert not (output / "dataset-manifest.v1.json").exists()
    assert (output / "unowned").read_bytes() == b"unowned"


@pytest.mark.parametrize("created_kind", ["missing", "outside"])
def test_cleanup_ignores_only_paths_it_did_not_create(tmp_path: Path, created_kind: str) -> None:
    output = tmp_path / "generation"
    output.mkdir()
    identity = cli._directory_identity(output)
    created = output / "missing" if created_kind == "missing" else tmp_path / "outside"
    cli._cleanup_created_output(
        output,
        identity,
        [cli._CreatedArtifact(created, cli._FileIdentity(1, 1))],
    )
    assert not output.exists()

    cli._cleanup_created_output(output, identity, [])


def test_empty_output_cleanup_is_nonrecursive_and_alias_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "generation"
    output.mkdir()
    cli._cleanup_empty_output_directory(output)
    assert not output.exists()

    unsafe = tmp_path / "unsafe"
    unsafe.write_bytes(b"x")
    with pytest.raises(cli.ReconciliationCliError, match="cleaned safely"):
        cli._cleanup_empty_output_directory(unsafe)
    alias = tmp_path / "alias"
    alias.mkdir()
    monkeypatch.setattr(Path, "is_symlink", lambda _path: True)
    with pytest.raises(cli.ReconciliationCliError, match="cleaned safely"):
        cli._cleanup_empty_output_directory(alias)


def test_output_writer_rejects_unapproved_names_and_nonregular_handles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "generation"
    output.mkdir()
    identity = cli._directory_identity(output)
    with pytest.raises(cli.ReconciliationCliError, match="filename"):
        cli._open_output_file(output, identity, "../unsafe", [])

    class FakeHandle:
        closed = False

        def fileno(self) -> int:
            return 1

        def close(self) -> None:
            self.closed = True

    fake = FakeHandle()
    monkeypatch.setattr(Path, "open", lambda *_args, **_kwargs: fake)
    monkeypatch.setattr(os, "fstat", lambda _fd: SimpleNamespace(st_mode=0, st_nlink=1))
    with pytest.raises(cli.ReconciliationCliError, match="regular"):
        cli._open_output_file(output, identity, "dataset-manifest.v1.json", [])
    assert fake.closed is True


def test_output_open_and_write_failures_are_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "generation"
    output.mkdir()
    identity = cli._directory_identity(output)
    existing = output / "dataset-manifest.v1.json"
    existing.write_bytes(b"existing")
    with pytest.raises(cli.ReconciliationCliError, match="exclusively"):
        cli._open_output_file(output, identity, existing.name, [])

    for handle, message in (
        (ControlledHandle(short=True), "incomplete"),
        (ControlledHandle(os_error=True), "written safely"),
    ):
        monkeypatch.setattr(
            cli,
            "_open_output_file",
            lambda *_args, selected=handle, **_kwargs: (
                output / "artifact",
                selected,
                cli._CreatedArtifact(output / "artifact", cli._FileIdentity(1, 1)),
            ),
        )
        with pytest.raises(cli.ReconciliationCliError, match=message):
            cli._write_bytes(output, identity, existing.name, b"payload", [])


def test_catalog_record_write_failures_and_count_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "generation"
    output.mkdir()
    identity = cli._directory_identity(output)
    monkeypatch.setattr(os, "fsync", lambda _fd: None)
    monkeypatch.setattr(cli, "_require_artifact_identity", lambda _artifact: None)
    for handle, message in (
        (ControlledHandle(short=True), "incomplete"),
        (ControlledHandle(os_error=True), "written safely"),
    ):
        monkeypatch.setattr(
            cli,
            "_open_output_file",
            lambda *_args, selected=handle, **_kwargs: (
                output / "records",
                selected,
                cli._CreatedArtifact(output / "records", cli._FileIdentity(1, 1)),
            ),
        )
        with pytest.raises(cli.ReconciliationCliError, match=message):
            cli._write_records(output, identity, synthetic_generation(), [])

    valid = ControlledHandle()
    monkeypatch.setattr(
        cli,
        "_open_output_file",
        lambda *_args, **_kwargs: (
            output / "records",
            valid,
            cli._CreatedArtifact(output / "records", cli._FileIdentity(1, 1)),
        ),
    )
    with pytest.raises(cli.ReconciliationCliError, match="count is inconsistent"):
        cli._write_records(output, identity, synthetic_generation(included_count=2), [])


def test_generation_output_creation_and_cleanup_failures_are_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    generation = synthetic_generation()
    manifest = synthetic_manifest()
    output = tmp_path / "generation"
    with monkeypatch.context() as patch:
        patch.setattr(
            cli.tempfile,
            "mkdtemp",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("synthetic mkdir")),
        )
        with pytest.raises(cli.ReconciliationCliError, match="cannot be created safely"):
            cli._write_generation_output(output, manifest, manifest, generation, synthetic_audits())

    with monkeypatch.context() as patch:
        real_identity = cli._directory_identity
        calls = 0

        def fail_first_identity(path: Path) -> Any:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise cli.ReconciliationCliError("synthetic identity failure")
            return real_identity(path)

        patch.setattr(cli, "_directory_identity", fail_first_identity)
        with pytest.raises(cli.ReconciliationCliError, match="identity failure"):
            cli._write_generation_output(output, manifest, manifest, generation, synthetic_audits())
        assert not output.exists()

    unsafe_identity_output = tmp_path / "unsafe-identity-generation"
    with monkeypatch.context() as patch:
        real_identity = cli._directory_identity
        calls = 0

        def fail_staging_identity(path: Path) -> Any:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise cli.ReconciliationCliError("synthetic identity failure")
            return real_identity(path)

        patch.setattr(
            cli,
            "_directory_identity",
            fail_staging_identity,
        )
        patch.setattr(
            cli,
            "_cleanup_empty_output_directory",
            lambda _path: (_ for _ in ()).throw(
                cli.ReconciliationCliError("synthetic empty cleanup failure")
            ),
        )
        with pytest.raises(cli.ReconciliationCliError, match="empty cleanup failure"):
            cli._write_generation_output(
                unsafe_identity_output,
                manifest,
                manifest,
                generation,
                synthetic_audits(),
            )

    with monkeypatch.context() as patch:
        patch.setattr(
            cli,
            "_write_records",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                cli.ReconciliationCliError("synthetic output failure")
            ),
        )
        patch.setattr(
            cli,
            "_cleanup_created_output",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                cli.ReconciliationCliError("synthetic cleanup failure")
            ),
        )
        with pytest.raises(cli.ReconciliationCliError, match="cleanup failure"):
            cli._write_generation_output(output, manifest, manifest, generation, synthetic_audits())


def test_staging_and_publish_failures_are_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "generation"
    with monkeypatch.context() as patch:
        patch.setattr(cli, "_has_unsafe_path_component", lambda _path: True)
        with pytest.raises(cli.ReconciliationCliError, match="staging directory is unsafe"):
            cli._create_staging_directory(target)

    staging, staging_identity, parent_identity = cli._create_staging_directory(target)
    target.mkdir()
    with pytest.raises(cli.ReconciliationCliError, match="already exist"):
        cli._publish_staging_directory(staging, target, staging_identity, parent_identity, [])
    target.rmdir()
    with monkeypatch.context() as patch:
        patch.setattr(
            Path,
            "rename",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("synthetic rename failure")),
        )
        with pytest.raises(cli.ReconciliationCliError, match="published safely"):
            cli._publish_staging_directory(staging, target, staging_identity, parent_identity, [])
    cli._cleanup_created_output(staging, staging_identity, [])

    staging, staging_identity, parent_identity = cli._create_staging_directory(target)
    real_require = cli._require_directory_identity
    with monkeypatch.context() as patch:
        patch.setattr(
            cli,
            "_require_directory_identity",
            lambda path, expected: (
                (_ for _ in ()).throw(cli.ReconciliationCliError("synthetic post-publish failure"))
                if path == target
                else real_require(path, expected)
            ),
        )
        with pytest.raises(cli.ReconciliationCliError, match="published output identity"):
            cli._publish_staging_directory(staging, target, staging_identity, parent_identity, [])
    assert not target.exists()

    staging, staging_identity, parent_identity = cli._create_staging_directory(target)
    with monkeypatch.context() as patch:
        patch.setattr(
            cli,
            "_require_directory_identity",
            lambda path, expected: (
                (_ for _ in ()).throw(cli.ReconciliationCliError("synthetic post-publish failure"))
                if path == target
                else real_require(path, expected)
            ),
        )
        patch.setattr(
            cli,
            "_cleanup_created_output",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                cli.ReconciliationCliError("synthetic publish cleanup failure")
            ),
        )
        with pytest.raises(cli.ReconciliationCliError, match="publish cleanup failure"):
            cli._publish_staging_directory(staging, target, staging_identity, parent_identity, [])
    target.rmdir()


def test_argument_errors_and_unexpected_failures_never_echo_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    sensitive_value = "another-value-that-must-not-be-echoed"
    assert cli.main(["--unknown", sensitive_value]) == 2
    first = capsys.readouterr()
    assert first.err.strip() == "split snapshot reconciliation failed"
    assert sensitive_value not in first.err

    def fail_run(**_kwargs: object) -> Any:
        raise RuntimeError(sensitive_value)

    monkeypatch.setattr(cli, "run_reconciliation", fail_run)
    inputs = make_inputs(tmp_path)
    assert cli.main(inputs.argv(tmp_path / "generation")) == 2
    second = capsys.readouterr()
    assert second.err.strip() == "split snapshot reconciliation failed"
    assert sensitive_value not in second.err


def test_module_entrypoint_is_covered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inputs = make_inputs(tmp_path)
    monkeypatch.setattr(sys, "argv", [str(cli.__file__), *inputs.argv(tmp_path / "generation")])
    with pytest.raises(SystemExit) as error:
        runpy.run_path(str(cli.__file__), run_name="__main__")
    assert error.value.code == 0
    assert json.loads(capsys.readouterr().out)["status"] == "ok"


def test_database_files_are_never_created_by_the_cli(tmp_path: Path) -> None:
    inputs = make_inputs(tmp_path)
    output = tmp_path / "generation"
    cli.run_reconciliation(**inputs.kwargs(output))
    forbidden_suffixes = {".sqlite", ".sqlite3", ".db", "-wal", "-shm", "-journal"}
    assert not any(
        path.name.endswith(tuple(forbidden_suffixes))
        for path in output.rglob("*")
        if path.is_file()
    )
