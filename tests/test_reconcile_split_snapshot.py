from __future__ import annotations

import ctypes
import hashlib
import io
import json
import os
import runpy
import struct
import sys
from contextlib import ExitStack
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from scripts import reconcile_split_snapshot as cli

from nla_catalog_gateway import runtime_contract
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
PORTABLE_CORE_BACKEND = sys.platform != "win32" or os.environ.get("NLA_PORTABLE_CORE_TEST") == "1"


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


@pytest.fixture(autouse=True)
def portable_core_filesystem_backend(
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> Any:
    """Exercise portable runner logic on CI while production remains Win32 fail-closed."""

    if not PORTABLE_CORE_BACKEND or request.node.name.startswith("test_native_"):
        yield
        return

    products_query_bytes = PRODUCT_QUERY.read_bytes()
    variants_query_bytes = VARIANT_QUERY.read_bytes()
    portable_repository = tmp_path / "portable-repository"
    portable_graphql = portable_repository / "graphql"
    portable_graphql.mkdir(parents=True)
    portable_product_query = portable_graphql / PRODUCT_QUERY.name
    portable_variant_query = portable_graphql / VARIANT_QUERY.name
    portable_product_query.write_bytes(products_query_bytes)
    portable_variant_query.write_bytes(variants_query_bytes)
    test_module = sys.modules[__name__]
    monkeypatch.setattr(test_module, "PROJECT_ROOT", portable_repository)
    monkeypatch.setattr(test_module, "PRODUCT_QUERY", portable_product_query)
    monkeypatch.setattr(test_module, "VARIANT_QUERY", portable_variant_query)
    monkeypatch.setattr(cli, "REPOSITORY_ROOT", portable_repository)

    registered_paths: dict[int, Path] = {}
    registered_files: dict[int, Any] = {}
    pending_delete: set[int] = set()
    next_handle = 100

    def register(path: Path, handle: Any = None) -> int:
        nonlocal next_handle
        next_handle += 1
        registered_paths[next_handle] = path
        if handle is not None:
            registered_files[next_handle] = handle
        return next_handle

    def binary_file(
        path: Path,
        *,
        writable: bool,
        create: bool,
        context: str,
    ) -> Any:
        try:
            mode = "x+b" if create else ("r+b" if writable else "rb")
            return path.open(mode, buffering=0)
        except OSError as exc:
            raise cli.ReconciliationCliError(f"{context} cannot be locked safely") from exc

    def sealed_file(path: Path, _context: str) -> Any:
        try:
            return path.open("rb", buffering=0)
        except OSError as exc:
            raise cli.ReconciliationCliError("output artifact cannot be sealed safely") from exc

    def create_file(path: Path, **_kwargs: object) -> int:
        if not path.exists():
            raise cli.ReconciliationCliError("portable test handle target is unavailable")
        return register(path)

    def os_handle(handle: Any, _context: str) -> int:
        return register(Path(handle.name), handle)

    def reopen_for_delete(handle: Any, _context: str) -> int:
        return register(Path(handle.name))

    def remove_registered_path(raw_handle: int) -> None:
        path = registered_paths[raw_handle]
        if path.is_dir():
            path.rmdir()
        else:
            path.unlink()

    def mark_delete(raw_handle: int, _context: str) -> None:
        pending_delete.add(raw_handle)

    def cancel_delete(raw_handle: int, _context: str) -> None:
        pending_delete.discard(raw_handle)

    def finalize_closed_pending(*, exclude: int) -> None:
        for pending in tuple(pending_delete):
            if pending == exclude:
                continue
            open_file = registered_files.get(pending)
            if open_file is not None and open_file.closed:
                remove_registered_path(pending)
                pending_delete.discard(pending)
                registered_paths.pop(pending, None)
                registered_files.pop(pending, None)

    def close_handle(raw_handle: int) -> None:
        registered = registered_paths.get(raw_handle)
        if registered is not None and registered.is_dir():
            finalize_closed_pending(exclude=raw_handle)
        if raw_handle in pending_delete:
            remove_registered_path(raw_handle)
            pending_delete.discard(raw_handle)
        registered_paths.pop(raw_handle, None)
        registered_files.pop(raw_handle, None)

    def canonical_for(path: Path) -> cli._CanonicalHandlePath:
        raw = os.fspath(path)
        if raw.casefold().startswith("\\\\?\\") and len(raw) > 6 and raw[5] == ":":
            path = Path(raw[4:])
        resolved = path.resolve(strict=False)
        return cli._CanonicalHandlePath(
            volume_guid=f"portable:{resolved.anchor.casefold()}",
            components=tuple(part.casefold() for part in resolved.parts[1:]),
        )

    def canonical_path(raw_handle: int, _context: str) -> cli._CanonicalHandlePath:
        return canonical_for(registered_paths[raw_handle])

    def file_streams(
        raw_handle: int,
        _context: str,
        *,
        directory: bool = False,
    ) -> tuple[tuple[str, int], ...]:
        if directory:
            result: tuple[tuple[str, int], ...] = ()
        else:
            open_file = registered_files.get(raw_handle)
            size = (
                os.fstat(open_file.fileno()).st_size
                if open_file is not None and not open_file.closed
                else registered_paths[raw_handle].stat().st_size
            )
            result = (("::$DATA", size),)
        return result

    def rename_directory(lease: cli._DirectoryLease, target: Path) -> None:
        source = lease.path
        source.rename(target)
        for raw_handle, registered in tuple(registered_paths.items()):
            if registered == source:
                registered_paths[raw_handle] = target
        lease.path = target
        lease.canonical_path = canonical_for(target)

    monkeypatch.setattr(cli, "_native_binary_file", binary_file)
    monkeypatch.setattr(cli, "_native_sealed_file", sealed_file)
    monkeypatch.setattr(cli, "_native_create_file", create_file)
    monkeypatch.setattr(cli, "_native_os_handle", os_handle)
    monkeypatch.setattr(cli, "_native_reopen_for_delete", reopen_for_delete)
    monkeypatch.setattr(cli, "_native_mark_delete", mark_delete)
    monkeypatch.setattr(cli, "_native_cancel_delete", cancel_delete)
    monkeypatch.setattr(cli, "_native_close", close_handle)
    monkeypatch.setattr(cli, "_native_handle_canonical_path", canonical_path)
    monkeypatch.setattr(cli, "_native_file_streams", file_streams)
    monkeypatch.setattr(cli, "_rename_directory_by_handle", rename_directory)
    monkeypatch.setattr(cli, "_require_local_ntfs", lambda *_args: None)
    yield


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
    level = 9_007_199_254_743_001
    location = 9_007_199_254_744_001
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
            "__parentId": gid("ProductVariant", variant),
            "id": f"{gid('InventoryLevel', level)}?inventory_item_id={item}",
            "location": {
                "id": gid("Location", location),
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
        self.write_lengths: list[int] = []
        self.last_byte: bytes | None = None

    def __enter__(self) -> ControlledHandle:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def fileno(self) -> int:
        return 1

    def write(self, raw: bytes) -> int:
        if self.os_error:
            raise OSError("synthetic write error")
        self.write_lengths.append(len(raw))
        self.last_byte = raw[-1:]
        return len(raw) - 1 if self.short else len(raw)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class SyntheticRecord:
    def __init__(self, raw: bytes = b'{"record":"synthetic"}') -> None:
        self.raw = raw

    def to_json_bytes(self) -> bytes:
        return self.raw


def synthetic_generation(*, included_count: int = 1, record_bytes: bytes | None = None) -> Any:
    return SimpleNamespace(
        records=(
            SyntheticRecord(b'{"record":"synthetic"}' if record_bytes is None else record_bytes),
        ),
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
    records_raw = (first_output / "catalog-records.v1.jsonl").read_bytes()
    assert records_raw.endswith(b"\n")
    assert not records_raw.endswith(b"\r\n")
    record_lines = records_raw.splitlines()
    assert len(record_lines) == 1
    for record_line in record_lines:
        assert len(record_line) <= runtime_contract.MAX_CONTRACT_BYTES
        record = CatalogProductRecordV1.from_json_bytes(record_line)
        assert record.to_json_bytes() == record_line
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
    assert set(message) == {
        "datasetGeneration",
        "outputCreated",
        "sourceGeneration",
        "status",
        "summarySha256",
    }
    assert message["outputCreated"] is True
    assert (
        message["summarySha256"]
        == hashlib.sha256((output / "reconciliation-summary.v1.json").read_bytes()).hexdigest()
    )
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


def test_windows_ads_and_trailing_input_components_are_rejected(tmp_path: Path) -> None:
    carrier = tmp_path / "carrier"
    carrier.write_bytes(b"carrier")
    alternate_stream = Path(f"{carrier}:evidence")
    alternate_stream.write_bytes(b"stream")
    assert alternate_stream.read_bytes() == b"stream"

    for candidate in (alternate_stream, Path(f"{carrier}."), Path(f"{carrier} ")):
        with pytest.raises(cli.ReconciliationCliError, match="normalized"):
            cli._regular_file(candidate, "input", external=True)


@pytest.mark.parametrize(
    "raw",
    [
        r"\\.\C:\unsafe",
        r"\??\C:\unsafe",
        r"\\?\GLOBALROOT\Device\HarddiskVolume1\unsafe",
        r"\\?\UNC\server\share\unsafe",
        r"\\server\share\unsafe",
        r"\\?\Device\HarddiskVolume1\unsafe",
    ],
)
def test_unsupported_windows_namespaces_are_rejected_early(raw: str) -> None:
    with pytest.raises(cli.ReconciliationCliError, match="unsupported filesystem namespace"):
        cli._require_supported_path_namespace(Path(raw), "input")


@pytest.mark.parametrize(
    "raw",
    [
        r"\\?\C:\safe",
        r"\\?\Volume{12345678-1234-1234-1234-123456789ABC}\safe",
    ],
)
def test_supported_extended_windows_namespaces_are_recognized_early(raw: str) -> None:
    cli._require_supported_path_namespace(Path(raw), "input")


def test_canonical_handle_path_parser_and_component_boundaries() -> None:
    root = cli._parse_canonical_handle_path(
        r"\\?\Volume{12345678-1234-1234-1234-123456789ABC}\Repo",
        "input",
    )
    child = cli._parse_canonical_handle_path(
        r"\\?\Volume{12345678-1234-1234-1234-123456789abc}\REPO\child",
        "input",
    )
    sibling_prefix = cli._parse_canonical_handle_path(
        r"\\?\Volume{12345678-1234-1234-1234-123456789abc}\repository",
        "input",
    )
    other_volume = cli._parse_canonical_handle_path(
        r"\\?\Volume{abcdef12-1234-1234-1234-123456789abc}\repo\child",
        "input",
    )
    assert cli._canonical_is_within(root, root) is True
    assert cli._canonical_is_within(child, root) is True
    assert cli._canonical_is_within(sibling_prefix, root) is False
    assert cli._canonical_is_within(other_volume, root) is False
    assert cli._canonical_child(root, "Child") == child

    for invalid in (
        r"C:\repo",
        r"\\?\C:\repo",
        r"\\?\Volume{not-a-guid}\repo",
        "\\\\?\\Volume{12345678-1234-1234-1234-123456789abc}\\repo/child",
        "\\\\?\\Volume{12345678-1234-1234-1234-123456789abc}\\repo\\..",
        "\\\\?\\Volume{12345678-1234-1234-1234-123456789abc}\\repo\\bad:",
        "\\\\?\\Volume{12345678-1234-1234-1234-123456789abc}\\repo\\bad. ",
        "\\\\?\\Volume{12345678-1234-1234-1234-123456789abc}\\repo\\\\child",
    ):
        with pytest.raises(cli.ReconciliationCliError, match="canonical path"):
            cli._parse_canonical_handle_path(invalid, "input")

    for invalid_name in ("", ".", "..", "bad/name", r"bad\name", "bad:name", "bad. "):
        with pytest.raises(cli.ReconciliationCliError, match="child name"):
            cli._canonical_child(root, invalid_name)


def _extended_path(path: Path) -> Path:
    if sys.platform != "win32":
        return path.resolve()
    return Path("\\\\?\\" + os.fspath(path.resolve()))


def _native_repository_alias(kind: str) -> Path | None:
    if sys.platform != "win32" or PORTABLE_CORE_BACKEND:
        return None
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    if kind == "volume-guid":
        buffer = ctypes.create_unicode_buffer(32_768)
        call = kernel32.GetVolumeNameForVolumeMountPointW
        if not call(PROJECT_ROOT.anchor, buffer, len(buffer)):
            return None
        relative = PROJECT_ROOT.resolve().relative_to(Path(PROJECT_ROOT.anchor))
        return Path(buffer.value) / relative
    if kind == "8.3":
        buffer = ctypes.create_unicode_buffer(32_768)
        call = kernel32.GetShortPathNameW
        result = int(call(os.fspath(PROJECT_ROOT.resolve()), buffer, len(buffer)))
        if result == 0 or result >= len(buffer):
            return None
        candidate = Path(buffer.value)
        return candidate if os.path.normcase(candidate) != os.path.normcase(PROJECT_ROOT) else None
    if kind == "subst":
        query = kernel32.QueryDosDeviceW
        buffer = ctypes.create_unicode_buffer(32_768)
        for ordinal in range(ord("A"), ord("Z") + 1):
            drive = f"{chr(ordinal)}:"
            if not query(drive, buffer, len(buffer)):
                continue
            target = buffer.value
            if not target.casefold().startswith("\\??\\".casefold()):
                continue
            mapped = Path(target[4:]).resolve(strict=False)
            try:
                relative = PROJECT_ROOT.resolve().relative_to(mapped)
            except ValueError:
                continue
            return Path(f"{drive}\\") / relative
    return None


def test_normal_and_extended_paths_use_authoritative_canonical_boundaries(tmp_path: Path) -> None:
    external = tmp_path / "external.json"
    external.write_bytes(b"{}")
    extended_external = _extended_path(external)
    resolved, state = cli._regular_file(extended_external, "input", external=True)
    assert state.byte_count == 2
    assert resolved.samefile(external)

    extended_repo_query = _extended_path(PRODUCT_QUERY)
    with pytest.raises(cli.ReconciliationCliError, match="external to the repository"):
        cli._regular_file(extended_repo_query, "input", external=True)

    extended_output = _extended_path(tmp_path / "extended-output")
    assert cli._validated_output_directory(extended_output).parent.samefile(tmp_path)
    assert not (tmp_path / "extended-output").exists()

    repo_output = _extended_path(PROJECT_ROOT / "extended-output")
    with pytest.raises(cli.ReconciliationCliError, match="external to the repository"):
        cli._validated_output_directory(repo_output)
    assert not (PROJECT_ROOT / "extended-output").exists()


@pytest.mark.parametrize("alias_kind", ["volume-guid", "8.3", "subst"])
def test_repository_aliases_are_rejected_by_handle_canonical_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    alias_kind: str,
) -> None:
    alias_root = _native_repository_alias(alias_kind)
    if alias_root is not None:
        alias_query = alias_root / "graphql" / PRODUCT_QUERY.name
        with pytest.raises(cli.ReconciliationCliError, match="external to the repository"):
            cli._regular_file(alias_query, "input", external=True)
        alias_output = alias_root / f"{alias_kind}-output"
        with pytest.raises(cli.ReconciliationCliError, match="external to the repository"):
            cli._validated_output_directory(alias_output)
        assert not alias_output.exists()
        return

    external = tmp_path / f"{alias_kind}.json"
    external.write_bytes(b"{}")
    repository = cli._CanonicalHandlePath("volume", ("repo",))
    canonical_alias = cli._CanonicalHandlePath("volume", ("repo", alias_kind.casefold()))
    monkeypatch.setattr(cli, "_repository_canonical_path", lambda: repository)
    monkeypatch.setattr(
        cli, "_native_path_canonical_path", lambda *_args, **_kwargs: canonical_alias
    )
    with pytest.raises(cli.ReconciliationCliError, match="external to the repository"):
        cli._regular_file(external, "input", external=True)

    output = tmp_path / f"{alias_kind}-output"
    with pytest.raises(cli.ReconciliationCliError, match="external to the repository"):
        cli._validated_output_directory(output)
    assert not output.exists()


@pytest.mark.parametrize(
    ("field_name", "context"),
    [
        ("products_snapshot", "products snapshot"),
        ("variants_snapshot", "variants snapshot"),
        ("products_terminal", "products terminal evidence"),
        ("variants_terminal", "variants terminal evidence"),
        ("expectation_path", "reconciliation expectation"),
        ("products_query", "products query"),
        ("variants_query", "variants query"),
    ],
)
def test_every_pinned_input_rejects_a_named_ntfs_stream(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field_name: str,
    context: str,
) -> None:
    inputs = make_inputs(tmp_path)
    products_query = tmp_path / "products-query.graphql"
    variants_query = tmp_path / "variants-query.graphql"
    products_query.write_bytes(PRODUCT_QUERY.read_bytes())
    variants_query.write_bytes(VARIANT_QUERY.read_bytes())
    inputs = replace(inputs, products_query=products_query, variants_query=variants_query)
    carrier = getattr(inputs, field_name)
    output = tmp_path / "generation"

    if not PORTABLE_CORE_BACKEND and sys.platform == "win32":
        alternate = Path(f"{carrier}:foreign")
        alternate.write_bytes(b"third-party-stream")
    else:
        real_require = cli._require_unnamed_data_stream

        def reject_selected(raw_handle: int, expected_size: int, selected_context: str) -> None:
            if selected_context == context:
                raise cli.ReconciliationCliError(
                    f"{selected_context} must contain only its unnamed data stream"
                )
            real_require(raw_handle, expected_size, selected_context)

        monkeypatch.setattr(cli, "_require_unnamed_data_stream", reject_selected)

    with pytest.raises(cli.ReconciliationCliError, match="unnamed data stream"):
        cli.run_reconciliation(**inputs.kwargs(output))
    assert not output.exists()
    assert not tuple(tmp_path.glob(".nla-reconcile-staging-*"))
    if not PORTABLE_CORE_BACKEND and sys.platform == "win32":
        assert Path(f"{carrier}:foreign").read_bytes() == b"third-party-stream"


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
        **kwargs: Any,
    ) -> Any:
        nonlocal replaced
        if context == "reconciliation expectation" and not replaced:
            replacement.replace(path)
            replaced = True
        return real_pin(path, state, context, stack, **kwargs)

    monkeypatch.setattr(cli, "_pin_regular_file", swap_then_pin)
    output = tmp_path / "generation"
    with pytest.raises(cli.ReconciliationCliError, match="identity changed"):
        cli.run_reconciliation(**inputs.kwargs(output))
    assert replaced is True
    assert not output.exists()


def test_restored_inplace_expectation_attack_is_blocked_by_the_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = make_inputs(tmp_path)
    output = tmp_path / "generation"
    real_pin = cli._pin_regular_file
    attempted = False

    def tamper_after_pin(
        path: Path,
        state: cli._InputFileState,
        context: str,
        stack: Any,
        **kwargs: Any,
    ) -> Any:
        nonlocal attempted
        pinned = real_pin(path, state, context, stack, **kwargs)
        if context == "reconciliation expectation":
            attempted = True
            original_times = path.stat()
            changed = expectation_document()
            changed["snapshotSetId"] = "sha256:" + "c" * 64
            replacement = json.dumps(
                changed,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            assert len(replacement) == state.byte_count
            path.write_bytes(replacement)
            os.utime(path, ns=(original_times.st_atime_ns, original_times.st_mtime_ns))
        return pinned

    monkeypatch.setattr(cli, "_pin_regular_file", tamper_after_pin)
    if not PORTABLE_CORE_BACKEND:
        with pytest.raises(OSError):
            cli.run_reconciliation(**inputs.kwargs(output))
        assert not output.exists()
    else:
        summary = cli.run_reconciliation(**inputs.kwargs(output))
        assert summary["snapshotSetId"] == SNAPSHOT_SET
        assert json.loads(inputs.expectation_path.read_bytes())["snapshotSetId"] != SNAPSHOT_SET
    assert attempted is True


def test_path_and_filesystem_failures_are_bounded(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(cli.ReconciliationCliError, match="unavailable"):
        cli._regular_file(missing, "input", external=True)
    with pytest.raises(cli.ReconciliationCliError, match="cannot be read"):
        cli._load_control_document(missing, "control")


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
            cli,
            "_native_binary_file",
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
    with pytest.raises(cli.ReconciliationCliError, match="not frozen"):
        cli._read_pinned_bytes(synthetic, maximum=10)


def test_native_backend_availability_and_close_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class NativeCall:
        def __init__(self, result: object) -> None:
            self.result = result

        def __call__(self, *_args: object) -> object:
            return self.result

    with monkeypatch.context() as patch:
        patch.setattr(cli, "_WINDOWS_HANDLE_API_AVAILABLE", False)
        with pytest.raises(cli.ReconciliationCliError, match="guarantees are unavailable"):
            cli._windows_kernel32()
        with pytest.raises(cli.ReconciliationCliError, match="guarantees are unavailable"):
            cli._windows_msvcrt()
    with monkeypatch.context() as patch:
        patch.setattr(cli, "_WINDOWS_HANDLE_API_AVAILABLE", True)
        patch.setattr(
            cli.ctypes,
            "WinDLL",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("synthetic loader")),
            raising=False,
        )
        with pytest.raises(cli.ReconciliationCliError, match="guarantees are unavailable"):
            cli._windows_kernel32()
    msvcrt_sentinel = SimpleNamespace(name="portable-msvcrt-sentinel")
    with monkeypatch.context() as patch:
        patch.setattr(cli, "_WINDOWS_HANDLE_API_AVAILABLE", True)
        patch.setitem(sys.modules, "msvcrt", msvcrt_sentinel)
        assert cli._windows_msvcrt() is msvcrt_sentinel
    with monkeypatch.context() as patch:
        patch.setattr(
            cli,
            "_windows_kernel32",
            lambda: SimpleNamespace(CloseHandle=NativeCall(False)),
        )
        with pytest.raises(cli.ReconciliationCliError, match="cannot be closed safely"):
            cli._native_close(101)
    with monkeypatch.context() as patch:
        patch.setattr(
            cli,
            "_windows_kernel32",
            lambda: SimpleNamespace(CloseHandle=NativeCall(True)),
        )
        cli._native_close(101)

    for result, expected in ((101, 101), (cli._INVALID_NATIVE_HANDLE, None)):
        with monkeypatch.context() as patch:
            patch.setattr(
                cli,
                "_windows_kernel32",
                lambda selected=result: SimpleNamespace(CreateFileW=NativeCall(selected)),
            )
            if expected is None:
                with pytest.raises(cli.ReconciliationCliError, match="cannot be locked safely"):
                    cli._native_create_file(
                        Path("synthetic"),
                        access=1,
                        share=1,
                        creation=1,
                        flags=1,
                        context="input",
                    )
            else:
                assert (
                    cli._native_create_file(
                        Path("synthetic"),
                        access=1,
                        share=1,
                        creation=1,
                        flags=1,
                        context="input",
                    )
                    == expected
                )


def test_native_runner_fails_closed_before_output_when_backend_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = make_inputs(tmp_path)
    output = tmp_path / "generation"
    monkeypatch.setattr(cli, "_WINDOWS_HANDLE_API_AVAILABLE", False)

    with pytest.raises(cli.ReconciliationCliError, match="guarantees are unavailable"):
        cli.run_reconciliation(**inputs.kwargs(output))

    assert not output.exists()
    assert not tuple(tmp_path.glob(".nla-reconcile-staging-*"))


def test_native_local_ntfs_boundary_is_explicit_and_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class NativeCall:
        def __init__(self, callback: Any) -> None:
            self.callback = callback

        def __call__(self, *args: object) -> object:
            return self.callback(*args)

    def kernel(
        *,
        volume_path_ok: bool = True,
        drive_type: int = cli._DRIVE_FIXED,
        volume_info_ok: bool = True,
        filesystem: str = "NTFS",
    ) -> Any:
        def volume_path(_path: object, output: Any, _length: object) -> bool:
            if volume_path_ok:
                output.value = "C:\\"
            return volume_path_ok

        def volume_info(*args: object) -> bool:
            if volume_info_ok:
                args[6].value = filesystem
            return volume_info_ok

        return SimpleNamespace(
            GetVolumePathNameW=NativeCall(volume_path),
            GetDriveTypeW=NativeCall(lambda _root: drive_type),
            GetVolumeInformationW=NativeCall(volume_info),
        )

    with monkeypatch.context() as patch:
        patch.setattr(cli, "_windows_kernel32", kernel)
        cli._require_local_ntfs(tmp_path, "input")

    for selected, message in (
        (kernel(volume_path_ok=False), "boundary cannot be verified"),
        (kernel(drive_type=4), "local fixed NTFS"),
        (kernel(volume_info_ok=False), "boundary cannot be verified"),
        (kernel(filesystem="ReFS"), "local fixed NTFS"),
    ):
        with monkeypatch.context() as patch:
            patch.setattr(cli, "_windows_kernel32", lambda value=selected: value)
            with pytest.raises(cli.ReconciliationCliError, match=message):
                cli._require_local_ntfs(tmp_path, "input")


def _stream_info_payload(entries: list[tuple[str, int, int]]) -> bytes:
    payload = bytearray()
    for index, (name, size, allocation) in enumerate(entries):
        encoded = name.encode("utf-16-le", errors="surrogatepass")
        entry_size = 24 + len(encoded)
        padded_size = (entry_size + 7) & ~7
        next_offset = padded_size if index + 1 < len(entries) else 0
        payload.extend(struct.pack("<IIqq", next_offset, len(encoded), size, allocation))
        payload.extend(encoded)
        if next_offset:
            payload.extend(b"\x00" * (padded_size - entry_size))
    return bytes(payload)


def test_native_file_stream_enumeration_uses_the_exact_handle(tmp_path: Path) -> None:
    if sys.platform != "win32":
        payload = _stream_info_payload([("::$DATA", 7, 8), (":evidence:$DATA", 6, 8)])

        class NativeCall:
            def __call__(self, _handle: int, _kind: int, output: Any, _size: int) -> bool:
                ctypes.memmove(ctypes.addressof(output), payload, len(payload))
                return True

        original = cli._windows_kernel32
        cli._windows_kernel32 = lambda: SimpleNamespace(  # type: ignore[assignment]
            GetFileInformationByHandleEx=NativeCall()
        )
        try:
            assert cli._native_file_streams(101, "input") == (
                ("::$DATA", 7),
                (":evidence:$DATA", 6),
            )
        finally:
            cli._windows_kernel32 = original  # type: ignore[assignment]
        return

    carrier = tmp_path / "carrier"
    carrier.write_bytes(b"carrier")
    alternate = Path(f"{carrier}:evidence")
    alternate.write_bytes(b"stream")
    raw_handle = cli._native_create_file(
        carrier,
        access=cli._FILE_READ_ATTRIBUTES,
        share=cli._FILE_SHARE_READ | cli._FILE_SHARE_WRITE | cli._FILE_SHARE_DELETE,
        creation=cli._OPEN_EXISTING,
        flags=cli._FILE_ATTRIBUTE_NORMAL | cli._FILE_FLAG_OPEN_REPARSE_POINT,
        context="input",
    )
    try:
        assert cli._native_file_streams(raw_handle, "input") == (
            ("::$DATA", 7),
            (":evidence:$DATA", 6),
        )
    finally:
        cli._native_close(raw_handle)

    empty = tmp_path / "empty"
    empty.write_bytes(b"")
    raw_handle = cli._native_create_file(
        empty,
        access=cli._FILE_READ_ATTRIBUTES,
        share=cli._FILE_SHARE_READ | cli._FILE_SHARE_WRITE | cli._FILE_SHARE_DELETE,
        creation=cli._OPEN_EXISTING,
        flags=cli._FILE_ATTRIBUTE_NORMAL | cli._FILE_FLAG_OPEN_REPARSE_POINT,
        context="input",
    )
    try:
        assert cli._native_file_streams(raw_handle, "input") == (("::$DATA", 0),)
    finally:
        cli._native_close(raw_handle)


def test_native_directory_stream_enumeration_distinguishes_clean_and_ads(tmp_path: Path) -> None:
    if sys.platform != "win32":
        with pytest.raises(
            cli.ReconciliationCliError,
            match="strong filesystem handle guarantees are unavailable",
        ):
            cli._native_file_streams(101, "directory")
        return

    directory = tmp_path / "directory"
    directory.mkdir()

    def streams() -> tuple[tuple[str, int], ...]:
        raw_handle = cli._native_create_file(
            directory,
            access=cli._FILE_READ_ATTRIBUTES,
            share=cli._FILE_SHARE_READ | cli._FILE_SHARE_WRITE | cli._FILE_SHARE_DELETE,
            creation=cli._OPEN_EXISTING,
            flags=cli._FILE_FLAG_BACKUP_SEMANTICS | cli._FILE_FLAG_OPEN_REPARSE_POINT,
            context="output directory",
        )
        try:
            return cli._native_file_streams(raw_handle, "output directory", directory=True)
        finally:
            cli._native_close(raw_handle)

    assert streams() == ()
    Path(f"{directory}:foreign").write_bytes(b"stream")
    assert streams() == ((":foreign:$DATA", 6),)


def test_native_stream_parser_grows_an_aligned_buffer_and_rejects_invalid_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    valid = _stream_info_payload([("::$DATA", 7, 8), (":foreign:$DATA", 3, 8)])
    calls = 0

    class GrowingCall:
        def __call__(self, _handle: int, _kind: int, output: Any, _size: int) -> bool:
            nonlocal calls
            assert ctypes.addressof(output) % 8 == 0
            calls += 1
            if calls == 1:
                return False
            ctypes.memmove(ctypes.addressof(output), valid, len(valid))
            return True

    monkeypatch.setattr(
        cli,
        "_windows_kernel32",
        lambda: SimpleNamespace(GetFileInformationByHandleEx=GrowingCall()),
    )
    monkeypatch.setattr(cli, "_WIN32_LAST_ERROR", lambda: cli._ERROR_MORE_DATA)
    assert cli._native_file_streams(101, "input") == (
        ("::$DATA", 7),
        (":foreign:$DATA", 3),
    )
    assert calls == 2

    malformed = []
    zero_name = bytearray(_stream_info_payload([("::$DATA", 7, 8)]))
    struct.pack_into("<I", zero_name, 4, 0)
    malformed.append(bytes(zero_name))
    odd_name = bytearray(_stream_info_payload([("::$DATA", 7, 8)]))
    struct.pack_into("<I", odd_name, 4, 13)
    malformed.append(bytes(odd_name))
    oversized_name = bytearray(_stream_info_payload([("::$DATA", 7, 8)]))
    struct.pack_into("<I", oversized_name, 4, cli._STREAM_INFO_INITIAL_BYTES)
    malformed.append(bytes(oversized_name))
    malformed.append(_stream_info_payload([(":bad\x00name:$DATA", 1, 8)]))
    malformed.append(_stream_info_payload([("\ud800", 1, 8)]))
    malformed.append(_stream_info_payload([("::$DATA", -1, 8)]))
    malformed.append(_stream_info_payload([("::$DATA", 1, -1)]))
    malformed.append(_stream_info_payload([("::$DATA", 1, 8), ("::$data", 1, 8)]))
    for next_offset in (
        7,
        24,
        cli._STREAM_INFO_INITIAL_BYTES - 8,
        cli._STREAM_INFO_INITIAL_BYTES + 8,
    ):
        broken_offset = bytearray(_stream_info_payload([("::$DATA", 7, 8)]))
        struct.pack_into("<I", broken_offset, 0, next_offset)
        malformed.append(bytes(broken_offset))

    class PayloadCall:
        def __init__(self, payload: bytes) -> None:
            self.payload = payload

        def __call__(self, _handle: int, _kind: int, output: Any, _size: int) -> bool:
            ctypes.memmove(ctypes.addressof(output), self.payload, len(self.payload))
            return True

    for payload in malformed:
        with monkeypatch.context() as patch:
            patch.setattr(
                cli,
                "_windows_kernel32",
                lambda selected=payload: SimpleNamespace(
                    GetFileInformationByHandleEx=PayloadCall(selected)
                ),
            )
            with pytest.raises(cli.ReconciliationCliError, match="stream metadata is invalid"):
                cli._native_file_streams(101, "input")


def test_native_stream_query_errors_and_bounds_are_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingCall:
        def __call__(self, *_args: object) -> bool:
            return False

    monkeypatch.setattr(
        cli,
        "_windows_kernel32",
        lambda: SimpleNamespace(GetFileInformationByHandleEx=FailingCall()),
    )
    with monkeypatch.context() as patch:
        patch.setattr(cli, "_WIN32_LAST_ERROR", lambda: cli._ERROR_HANDLE_EOF)
        assert cli._native_file_streams(101, "directory", directory=True) == ()
        with pytest.raises(cli.ReconciliationCliError, match="streams cannot be verified"):
            cli._native_file_streams(101, "input")
    with monkeypatch.context() as patch:
        patch.setattr(cli, "_WIN32_LAST_ERROR", lambda: 5)
        with pytest.raises(cli.ReconciliationCliError, match="streams cannot be verified"):
            cli._native_file_streams(101, "input")
    with monkeypatch.context() as patch:
        patch.setattr(cli, "_WIN32_LAST_ERROR", lambda: cli._ERROR_INSUFFICIENT_BUFFER)
        with pytest.raises(cli.ReconciliationCliError, match="metadata exceeds its bound"):
            cli._native_file_streams(101, "input")


def test_directory_stream_guard_rejects_named_stream_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli,
        "_native_file_streams",
        lambda *_args, **_kwargs: ((":foreign:$DATA", 1),),
    )
    with pytest.raises(cli.ReconciliationCliError, match="named data streams"):
        cli._require_no_directory_streams(101, "output directory")


def test_native_final_path_is_volume_guid_normalized_and_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = r"\\?\Volume{12345678-1234-1234-1234-123456789abc}\Repo\Input"

    class FinalPathCall:
        def __init__(self, result: int | None) -> None:
            self.result = result

        def __call__(self, _handle: int, output: Any, _size: int, flags: int) -> int:
            assert flags == cli._VOLUME_NAME_GUID
            if self.result is None:
                output.value = value
                return len(value)
            return self.result

    with monkeypatch.context() as patch:
        patch.setattr(
            cli,
            "_windows_kernel32",
            lambda: SimpleNamespace(GetFinalPathNameByHandleW=FinalPathCall(None)),
        )
        assert cli._native_handle_canonical_path(101, "input") == cli._CanonicalHandlePath(
            "volume{12345678-1234-1234-1234-123456789abc}",
            ("repo", "input"),
        )
    for result in (0, cli._VOLUME_NAME_BUFFER_CHARS):
        with monkeypatch.context() as patch:
            patch.setattr(
                cli,
                "_windows_kernel32",
                lambda selected=result: SimpleNamespace(
                    GetFinalPathNameByHandleW=FinalPathCall(selected)
                ),
            )
            with pytest.raises(cli.ReconciliationCliError, match="canonical path"):
                cli._native_handle_canonical_path(101, "input")


def test_native_file_binding_failures_close_exact_resources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import builtins

    source = tmp_path / "source"
    source.write_bytes(b"source")
    real_import = builtins.__import__

    def missing_msvcrt(name: str, *args: object, **kwargs: object) -> Any:
        if name == "msvcrt":
            raise ImportError("synthetic missing backend")
        return real_import(name, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(cli, "_WINDOWS_HANDLE_API_AVAILABLE", True)
        patch.setattr(builtins, "__import__", missing_msvcrt)
        with pytest.raises(cli.ReconciliationCliError, match="guarantees are unavailable"):
            cli._windows_msvcrt()

    for opener, expected_message in (
        (
            lambda: cli._native_binary_file(source, writable=False, create=False, context="input"),
            "bound to a binary handle",
        ),
        (lambda: cli._native_sealed_file(source, "output"), "sealed to an exact handle"),
    ):
        closed: list[int] = []
        fake_msvcrt = SimpleNamespace(
            open_osfhandle=lambda *_args: (_ for _ in ()).throw(
                OSError("synthetic binding failure")
            )
        )
        with monkeypatch.context() as patch:
            patch.setattr(cli, "_native_create_file", lambda *_args, **_kwargs: 101)
            patch.setattr(cli, "_windows_msvcrt", lambda value=fake_msvcrt: value)
            patch.setattr(cli, "_native_close", closed.append)
            with pytest.raises(cli.ReconciliationCliError, match=expected_message):
                opener()
        assert closed == [101]

    for opener, expected_message in (
        (
            lambda: cli._native_binary_file(source, writable=False, create=False, context="input"),
            "bound to a binary handle",
        ),
        (lambda: cli._native_sealed_file(source, "output"), "sealed to an exact handle"),
    ):
        descriptor = os.open(os.devnull, os.O_RDONLY)
        fake_msvcrt = SimpleNamespace(open_osfhandle=lambda *_args, fd=descriptor: fd)
        with monkeypatch.context() as patch:
            patch.setattr(cli, "_native_create_file", lambda *_args, **_kwargs: 101)
            patch.setattr(cli, "_windows_msvcrt", lambda value=fake_msvcrt: value)
            patch.setattr(
                os,
                "fdopen",
                lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    ValueError("synthetic descriptor failure")
                ),
            )
            with pytest.raises(cli.ReconciliationCliError, match=expected_message):
                opener()
        with pytest.raises(OSError):
            os.fstat(descriptor)

    for opener in (
        lambda: cli._native_binary_file(source, writable=False, create=False, context="input"),
        lambda: cli._native_sealed_file(source, "output"),
    ):
        descriptor = os.open(source, os.O_RDONLY)
        fake_msvcrt = SimpleNamespace(open_osfhandle=lambda *_args, fd=descriptor: fd)
        with monkeypatch.context() as patch:
            patch.setattr(cli, "_native_create_file", lambda *_args, **_kwargs: 101)
            patch.setattr(cli, "_windows_msvcrt", lambda value=fake_msvcrt: value)
            with opener() as handle:
                assert handle.read() == b"source"

    descriptor = os.open(source, os.O_RDWR)
    writable_msvcrt = SimpleNamespace(open_osfhandle=lambda *_args: descriptor)
    with monkeypatch.context() as patch:
        patch.setattr(cli, "_native_create_file", lambda *_args, **_kwargs: 101)
        patch.setattr(cli, "_windows_msvcrt", lambda: writable_msvcrt)
        with cli._native_binary_file(
            source, writable=True, create=False, context="output"
        ) as handle:
            assert handle.read() == b"source"


def test_native_snapshot_binding_is_buffered_without_weakening_line_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "snapshot.jsonl"
    maximum = cli.bulk.MAX_JSONL_LINE_BYTES
    accepted = b"x" * (maximum - 1) + b"\n"
    rejected = b"x" * maximum + b"\n"
    source.write_bytes(accepted + rejected)
    descriptor = os.open(source, os.O_RDONLY)
    fdopen_calls: list[tuple[int, str, int]] = []
    real_fdopen = os.fdopen

    def recorded_fdopen(fd: int, mode: str, *, buffering: int) -> Any:
        fdopen_calls.append((fd, mode, buffering))
        return real_fdopen(fd, mode, buffering=buffering)

    fake_msvcrt = SimpleNamespace(open_osfhandle=lambda *_args: descriptor)
    with monkeypatch.context() as patch:
        patch.setattr(cli, "_native_create_file", lambda *_args, **_kwargs: 101)
        patch.setattr(cli, "_windows_msvcrt", lambda: fake_msvcrt)
        patch.setattr(os, "fdopen", recorded_fdopen)
        with cli._native_binary_file(
            source, writable=False, create=False, context="input"
        ) as handle:
            initial_state = cli._handle_input_state(handle, "input")
            assert isinstance(handle, io.BufferedReader)
            assert handle.fileno() == descriptor
            assert cli.bulk._next_line(handle) == accepted
            with pytest.raises(
                cli.bulk.BulkContractError,
                match="exceeds the maximum line size",
            ):
                cli.bulk._next_line(handle)
            assert cli._handle_input_state(handle, "input") == initial_state

    assert fdopen_calls == [(descriptor, "rb", cli._NATIVE_READ_BUFFER_BYTES)]


def test_native_handle_and_directory_error_paths_are_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class NativeCall:
        def __init__(self, result: object) -> None:
            self.result = result

        def __call__(self, *_args: object) -> object:
            return self.result

    class BadFileno:
        def fileno(self) -> int:
            raise ValueError("synthetic native handle failure")

    with pytest.raises(cli.ReconciliationCliError, match="native handle is unavailable"):
        cli._native_os_handle(BadFileno(), "input")  # type: ignore[arg-type]
    with tmp_path.joinpath("native-source").open("w+b") as handle:
        with monkeypatch.context() as patch:
            patch.setattr(
                cli,
                "_windows_msvcrt",
                lambda: SimpleNamespace(get_osfhandle=lambda _descriptor: 202),
            )
            assert cli._native_os_handle(handle, "input") == 202

    with monkeypatch.context() as patch:
        patch.setattr(cli, "_native_os_handle", lambda *_args: 101)
        patch.setattr(cli.ctypes, "get_last_error", lambda: 0, raising=False)
        patch.setattr(
            cli,
            "_windows_kernel32",
            lambda: SimpleNamespace(ReOpenFile=NativeCall(cli._INVALID_NATIVE_HANDLE)),
        )
        with pytest.raises(cli.ReconciliationCliError, match="exact delete access"):
            cli._native_reopen_for_delete(BadFileno(), "output")  # type: ignore[arg-type]
    with monkeypatch.context() as patch:
        patch.setattr(cli, "_native_os_handle", lambda *_args: 101)
        patch.setattr(
            cli,
            "_windows_kernel32",
            lambda: SimpleNamespace(ReOpenFile=NativeCall(303)),
        )
        assert cli._native_reopen_for_delete(BadFileno(), "output") == 303  # type: ignore[arg-type]

    for result in (True, False):
        with monkeypatch.context() as patch:
            patch.setattr(
                cli,
                "_windows_kernel32",
                lambda selected=result: SimpleNamespace(
                    SetFileInformationByHandle=NativeCall(selected)
                ),
            )
            if result:
                cli._native_mark_delete(101, "output")
                cli._native_cancel_delete(101, "output")
            else:
                with pytest.raises(cli.ReconciliationCliError, match="deleted by exact handle"):
                    cli._native_mark_delete(101, "output")

    source = tmp_path / "staging"
    target = tmp_path / "generation"
    identity = cli._FileIdentity(1, 2)
    closed: list[int] = []
    calls = 0

    def fail_second_open(*_args: object, **_kwargs: object) -> int:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise cli.ReconciliationCliError("synthetic staging open")
        return 101

    with monkeypatch.context() as patch:
        patch.setattr(cli, "_native_create_file", fail_second_open)
        patch.setattr(cli, "_native_close", closed.append)
        with pytest.raises(cli.ReconciliationCliError, match="synthetic staging open"):
            cli._open_directory_lease(source, identity)
    assert closed == [101]

    closed.clear()
    with monkeypatch.context() as patch:
        patch.setattr(cli, "_native_create_file", lambda *_args, **_kwargs: 101)
        patch.setattr(cli, "_native_close", closed.append)
        canonical_paths = iter(
            (
                cli._CanonicalHandlePath("volume", ("parent",)),
                cli._CanonicalHandlePath("volume", ("parent", "staging")),
            )
        )
        patch.setattr(cli, "_native_handle_canonical_path", lambda *_args: next(canonical_paths))
        patch.setattr(cli, "_require_external_canonical_path", lambda *_args: None)
        patch.setattr(cli, "_require_no_directory_streams", lambda *_args: None)
        patch.setattr(
            cli,
            "_require_directory_identity",
            lambda *_args: (_ for _ in ()).throw(
                cli.ReconciliationCliError("synthetic directory identity")
            ),
        )
        with pytest.raises(cli.ReconciliationCliError, match="synthetic directory identity"):
            cli._open_directory_lease(source, identity)
    assert closed == [101, 101]

    closed_lease = cli._DirectoryLease(source, identity, 101, 102, closed=True)
    with pytest.raises(cli.ReconciliationCliError, match="lease is closed"):
        cli._rename_directory_by_handle(closed_lease, target)
    cli._delete_directory_by_handle(closed_lease)
    cli._close_directory_lease(closed_lease)

    parent_canonical = cli._CanonicalHandlePath("volume", ("parent",))
    open_lease = cli._DirectoryLease(
        source,
        identity,
        101,
        102,
        canonical_path=cli._CanonicalHandlePath("volume", ("parent", "staging")),
        parent_canonical_path=parent_canonical,
    )
    with pytest.raises(cli.ReconciliationCliError, match="remain in its parent"):
        cli._rename_directory_by_handle(open_lease, tmp_path.parent / "generation")
    with monkeypatch.context() as patch:
        patch.setattr(cli, "_verify_directory_lease_canonical_path", lambda *_args: None)
        patch.setattr(
            cli,
            "_windows_kernel32",
            lambda: SimpleNamespace(SetFileInformationByHandle=NativeCall(False)),
        )
        with pytest.raises(cli.ReconciliationCliError, match="published safely"):
            cli._rename_directory_by_handle(open_lease, target)
    with monkeypatch.context() as patch:
        patch.setattr(cli, "_verify_directory_lease_canonical_path", lambda *_args: None)
        patch.setattr(
            cli,
            "_windows_kernel32",
            lambda: SimpleNamespace(SetFileInformationByHandle=NativeCall(True)),
        )
        cli._rename_directory_by_handle(open_lease, target)
    assert open_lease.path == target
    assert open_lease.canonical_path == cli._canonical_child(parent_canonical, target.name)


def test_pinned_input_freeze_error_paths_are_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.write_bytes(b"source")
    path, state = cli._regular_file(source, "input", external=True)
    with monkeypatch.context() as patch:
        patch.setattr(
            cli,
            "_native_binary_file",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                cli.ReconciliationCliError("synthetic native rejection")
            ),
        )
        with cli.ExitStack() as stack:
            with pytest.raises(cli.ReconciliationCliError, match="synthetic native rejection"):
                cli._pin_regular_file(path, state, "input", stack)

    with cli.ExitStack() as stack:
        with pytest.raises(cli.ReconciliationCliError, match="byte bound is invalid"):
            cli._pin_regular_file(path, state, "input", stack, freeze_maximum=0)

    class BadFreezeHandle:
        def __enter__(self) -> BadFreezeHandle:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def seek(self, _offset: int) -> None:
            return None

        def read(self, _maximum: int) -> bytes:
            raise OSError("synthetic freeze failure")

    with monkeypatch.context() as patch:
        patch.setattr(cli, "_native_binary_file", lambda *_args, **_kwargs: BadFreezeHandle())
        patch.setattr(cli, "_native_os_handle", lambda *_args: 101)
        patch.setattr(
            cli,
            "_native_handle_canonical_path",
            lambda *_args: cli._CanonicalHandlePath("volume", ("input",)),
        )
        patch.setattr(cli, "_verify_pinned_input", lambda _pinned: None)
        with cli.ExitStack() as stack:
            with pytest.raises(cli.ReconciliationCliError, match="cannot be frozen"):
                cli._pin_regular_file(path, state, "input", stack, freeze_maximum=10)

    incomplete_state = cli._InputFileState(
        identity=state.identity,
        byte_count=state.byte_count + 1,
        modified_ns=state.modified_ns,
    )
    with monkeypatch.context() as patch:
        patch.setattr(cli, "_verify_pinned_input", lambda _pinned: None)
        with cli.ExitStack() as stack:
            with pytest.raises(cli.ReconciliationCliError, match="snapshot is incomplete"):
                cli._pin_regular_file(
                    path,
                    incomplete_state,
                    "input",
                    stack,
                    freeze_maximum=10,
                )

    with path.open("rb") as handle:
        frozen = cli._PinnedInputFile(path, state, handle, "input", frozen_bytes=b"source")
        with pytest.raises(cli.ReconciliationCliError, match="exceeds its bound"):
            cli._read_pinned_bytes(frozen, maximum=5)

    assert cli._input_state(path, "input") == state


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
    with pytest.raises(cli.ReconciliationCliError, match="not a regular"):
        cli._artifact_identity(directory)

    lease = cli._DirectoryLease(directory, identity, 101, 102, closed=True)
    with pytest.raises(cli.ReconciliationCliError, match="shape cannot be verified"):
        cli._verify_output_shape(lease)
    lease.closed = False
    with monkeypatch.context() as patch:
        patch.setattr(cli, "_verify_directory_lease_canonical_path", lambda *_args: None)
        patch.setattr(
            os,
            "scandir",
            lambda _path: (_ for _ in ()).throw(OSError("synthetic shape scan failure")),
        )
        with pytest.raises(cli.ReconciliationCliError, match="shape cannot be verified"):
            cli._verify_output_shape(lease)


def test_directory_handle_canonical_mismatches_are_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = tmp_path / "staging"
    directory.mkdir()
    identity = cli._directory_identity(directory)
    parent = cli._CanonicalHandlePath("volume", ("parent",))
    expected = cli._CanonicalHandlePath("volume", ("parent", "staging"))
    wrong = cli._CanonicalHandlePath("volume", ("elsewhere", "staging"))
    handles = iter((101, 102))
    canonical_paths = iter((parent, wrong))
    closed: list[int] = []
    with monkeypatch.context() as patch:
        patch.setattr(cli, "_native_create_file", lambda *_args, **_kwargs: next(handles))
        patch.setattr(
            cli,
            "_native_handle_canonical_path",
            lambda *_args: next(canonical_paths),
        )
        patch.setattr(cli, "_require_external_canonical_path", lambda *_args: None)
        patch.setattr(cli, "_native_close", closed.append)
        with pytest.raises(cli.ReconciliationCliError, match="canonical path is inconsistent"):
            cli._open_directory_lease(directory, identity)
    assert closed == [102, 101]

    unavailable = cli._DirectoryLease(directory, identity, 101, 102)
    with pytest.raises(cli.ReconciliationCliError, match="canonical path cannot be verified"):
        cli._verify_directory_lease_canonical_path(unavailable)

    changed = cli._DirectoryLease(
        directory,
        identity,
        101,
        102,
        canonical_path=expected,
        parent_canonical_path=parent,
    )
    with monkeypatch.context() as patch:
        paths = iter((parent, wrong))
        patch.setattr(cli, "_native_handle_canonical_path", lambda *_args: next(paths))
        with pytest.raises(cli.ReconciliationCliError, match="canonical path changed"):
            cli._verify_directory_lease_canonical_path(changed)


def test_directory_stream_rollback_failure_is_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = tmp_path / "staging"
    directory.mkdir()
    lease = cli._DirectoryLease(directory, cli._directory_identity(directory), 101, 102)
    events: list[str] = []
    monkeypatch.setattr(cli, "_native_mark_delete", lambda *_args: events.append("mark"))
    monkeypatch.setattr(
        cli,
        "_require_no_directory_streams",
        lambda *_args: (_ for _ in ()).throw(cli.ReconciliationCliError("named stream")),
    )

    def cancel(*_args: object) -> None:
        events.append("cancel")
        raise cli.ReconciliationCliError("cannot preserve directory")

    monkeypatch.setattr(cli, "_native_cancel_delete", cancel)
    monkeypatch.setattr(cli, "_native_close", lambda raw: events.append(f"close-{raw}"))
    with pytest.raises(cli.ReconciliationCliError, match="cannot preserve directory"):
        cli._delete_directory_by_handle(lease)
    assert events == ["mark", "cancel", "close-101", "close-102"]
    assert lease.closed is True


def test_pinned_input_canonical_path_change_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "input"
    source.write_bytes(b"source")
    with source.open("rb", buffering=0) as handle:
        state = cli._handle_input_state(handle, "input")
        expected = cli._CanonicalHandlePath("volume", ("expected",))
        pinned = cli._PinnedInputFile(
            source,
            state,
            handle,
            "input",
            canonical_path=expected,
        )
        monkeypatch.setattr(cli, "_native_os_handle", lambda *_args: 101)
        monkeypatch.setattr(cli, "_require_unnamed_data_stream", lambda *_args: None)
        monkeypatch.setattr(
            cli,
            "_native_handle_canonical_path",
            lambda *_args: cli._CanonicalHandlePath("volume", ("changed",)),
        )
        with pytest.raises(cli.ReconciliationCliError, match="canonical path changed"):
            cli._verify_pinned_input(pinned)


def test_artifact_handle_verification_error_paths_are_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "artifact"
    path.write_bytes(b"")
    identity = cli._artifact_identity(path)
    unavailable = cli._CreatedArtifact(path, identity)
    with pytest.raises(cli.ReconciliationCliError, match="handle is unavailable"):
        cli._artifact_handle_state(unavailable)

    class BadFileno:
        closed = False

        def fileno(self) -> int:
            raise ValueError("synthetic output handle failure")

    broken = cli._CreatedArtifact(path, identity, handle=BadFileno())  # type: ignore[arg-type]
    with pytest.raises(cli.ReconciliationCliError, match="handle cannot be verified"):
        cli._artifact_handle_state(broken)

    with monkeypatch.context() as patch:
        patch.setattr(os, "fstat", lambda _fd: SimpleNamespace(st_mode=0, st_nlink=1))
        with path.open("rb") as handle:
            nonregular = cli._CreatedArtifact(path, identity, handle=handle)
            with pytest.raises(cli.ReconciliationCliError, match="not one regular"):
                cli._artifact_handle_state(nonregular)

    no_expected = cli._CreatedArtifact(path, identity, handle=io.BytesIO())
    with pytest.raises(cli.ReconciliationCliError, match="expected content is unavailable"):
        cli._verify_artifact_contents(no_expected)

    mismatched_state = cli._InputFileState(cli._FileIdentity(99, 100), 0, 0)
    handle_mismatch = cli._CreatedArtifact(
        path,
        identity,
        handle=io.BytesIO(),
        expected_sha256=hashlib.sha256(b"").hexdigest(),
        expected_byte_count=0,
    )
    with monkeypatch.context() as patch:
        patch.setattr(cli, "_artifact_handle_state", lambda _artifact: mismatched_state)
        with pytest.raises(cli.ReconciliationCliError, match="handle identity changed"):
            cli._verify_artifact_contents(handle_mismatch)

    class BadReader(io.BytesIO):
        def seek(self, _offset: int, _whence: int = 0) -> int:
            raise OSError("synthetic read failure")

    stable_state = cli._InputFileState(identity, 0, 0)
    read_failure = cli._CreatedArtifact(
        path,
        identity,
        handle=BadReader(),
        expected_sha256=hashlib.sha256(b"").hexdigest(),
        expected_byte_count=0,
    )
    with monkeypatch.context() as patch:
        patch.setattr(cli, "_artifact_handle_state", lambda _artifact: stable_state)
        with pytest.raises(cli.ReconciliationCliError, match="verified from its handle"):
            cli._verify_artifact_contents(read_failure)

    changed_state = cli._InputFileState(identity, 1, 0)
    states = iter((stable_state, changed_state))
    state_change = cli._CreatedArtifact(
        path,
        identity,
        handle=io.BytesIO(),
        expected_sha256=hashlib.sha256(b"").hexdigest(),
        expected_byte_count=0,
    )
    with monkeypatch.context() as patch:
        patch.setattr(cli, "_artifact_handle_state", lambda _artifact: next(states))
        with pytest.raises(cli.ReconciliationCliError, match="state changed while verifying"):
            cli._verify_artifact_contents(state_change)


def test_output_handle_cleanup_and_close_errors_are_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    identity = cli._FileIdentity(1, 2)
    artifact = cli._CreatedArtifact(tmp_path / "artifact", identity)
    with pytest.raises(cli.ReconciliationCliError, match="exact handle is unavailable"):
        cli._delete_artifact_by_handle(artifact)

    class BadClose:
        closed = False

        def close(self) -> None:
            raise OSError("synthetic close failure")

    artifact.handle = BadClose()  # type: ignore[assignment]
    with monkeypatch.context() as patch:
        patch.setattr(cli, "_verify_artifact_contents", lambda _artifact: None)
        with pytest.raises(cli.ReconciliationCliError, match="could not be closed safely"):
            cli._close_created_output([artifact])


def test_global_publish_seal_error_paths_release_every_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    filenames = sorted(cli._OUTPUT_FILENAMES)
    artifacts = [
        cli._CreatedArtifact(
            tmp_path / filename,
            cli._FileIdentity(1, index + 1),
            handle=io.BytesIO(b"owned"),
            expected_sha256=hashlib.sha256(b"owned").hexdigest(),
            expected_byte_count=5,
            delete_capable=True,
        )
        for index, filename in enumerate(filenames)
    ]
    lease = cli._DirectoryLease(tmp_path, cli._FileIdentity(1, 99), 101, 102)

    with pytest.raises(cli.ReconciliationCliError, match="seal is incomplete"):
        cli._attest_and_close_published_output(lease, artifacts[:-1])
    artifacts[0].delete_capable = False
    with pytest.raises(cli.ReconciliationCliError, match="seal is incomplete"):
        cli._attest_and_close_published_output(lease, artifacts)
    artifacts[0].delete_capable = True

    events: list[str] = []
    handles = {id(artifact.handle): index + 201 for index, artifact in enumerate(artifacts)}
    monkeypatch.setattr(cli, "_verify_artifact_contents", lambda _artifact: None)
    monkeypatch.setattr(cli, "_verify_output_shape", lambda _lease: None)
    monkeypatch.setattr(
        cli,
        "_native_os_handle",
        lambda handle, _context: handles[id(handle)],
    )
    monkeypatch.setattr(
        cli,
        "_native_mark_delete",
        lambda raw, _context: events.append(f"mark-{raw}"),
    )

    def fail_guarded_verification(_artifact: cli._CreatedArtifact, **_kwargs: object) -> None:
        raise cli.ReconciliationCliError("synthetic guarded verification failure")

    monkeypatch.setattr(cli, "_verify_artifact_handle_contents", fail_guarded_verification)
    monkeypatch.setattr(
        cli,
        "_native_cancel_delete",
        lambda raw, _context: events.append(f"cancel-{raw}"),
    )
    with pytest.raises(cli.ReconciliationCliError, match="synthetic guarded"):
        cli._attest_and_close_published_output(lease, artifacts)
    assert events == [
        *(f"mark-{raw}" for raw in range(201, 208)),
        *(f"cancel-{raw}" for raw in range(207, 200, -1)),
    ]

    events.clear()

    def fail_one_cancel(raw_handle: int, _context: str) -> None:
        events.append(f"cancel-{raw_handle}")
        if raw_handle == 204:
            raise cli.ReconciliationCliError("synthetic cancel failure")

    monkeypatch.setattr(cli, "_native_cancel_delete", fail_one_cancel)
    with pytest.raises(cli.ReconciliationCliError, match="could not be released safely"):
        cli._attest_and_close_published_output(lease, artifacts)
    assert events == [
        *(f"mark-{raw}" for raw in range(201, 208)),
        *(f"cancel-{raw}" for raw in range(207, 200, -1)),
    ]
    for artifact in artifacts:
        assert artifact.handle is not None
        artifact.handle.close()


def test_global_publish_seal_cancel_and_close_failures_are_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[int] = []

    def cancel(raw_handle: int, _context: str) -> None:
        events.append(raw_handle)
        if raw_handle in {2, 3}:
            raise cli.ReconciliationCliError("synthetic cancel failure")

    monkeypatch.setattr(cli, "_native_cancel_delete", cancel)
    with pytest.raises(cli.ReconciliationCliError, match="could not be released safely"):
        cli._cancel_published_delete_guards([1, 2, 3])
    assert events == [3, 2, 1]

    class BadClose(io.BytesIO):
        failed = False

        def close(self) -> None:
            if not self.failed:
                self.failed = True
                raise OSError("synthetic close failure")
            super().close()

    filenames = sorted(cli._OUTPUT_FILENAMES)
    artifacts = [
        cli._CreatedArtifact(
            tmp_path / filename,
            cli._FileIdentity(1, index + 1),
            handle=BadClose(b"owned") if index == 0 else io.BytesIO(b"owned"),
            expected_sha256=hashlib.sha256(b"owned").hexdigest(),
            expected_byte_count=5,
            delete_capable=True,
        )
        for index, filename in enumerate(filenames)
    ]
    handles = {id(artifact.handle): index + 301 for index, artifact in enumerate(artifacts)}
    monkeypatch.setattr(cli, "_verify_artifact_contents", lambda _artifact: None)
    monkeypatch.setattr(
        cli,
        "_verify_artifact_handle_contents",
        lambda _artifact, **_kwargs: None,
    )
    monkeypatch.setattr(cli, "_verify_output_shape", lambda _lease: None)
    monkeypatch.setattr(
        cli,
        "_native_os_handle",
        lambda handle, _context: handles[id(handle)],
    )
    monkeypatch.setattr(cli, "_native_mark_delete", lambda *_args: None)
    monkeypatch.setattr(cli, "_native_cancel_delete", lambda *_args: None)
    lease = cli._DirectoryLease(tmp_path, cli._FileIdentity(1, 99), 101, 102)
    with pytest.raises(cli.ReconciliationCliError, match="could not be closed safely"):
        cli._attest_and_close_published_output(lease, artifacts)
    for artifact in artifacts:
        assert artifact.handle is not None
        artifact.handle.close()


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


def _write_native_named_stream(carrier: Path, name: str, payload: bytes) -> None:
    stream = Path(f"{carrier}:{name}")
    raw_handle = cli._native_create_file(
        stream,
        access=cli._GENERIC_WRITE,
        share=cli._FILE_SHARE_READ | cli._FILE_SHARE_WRITE | cli._FILE_SHARE_DELETE,
        creation=cli._CREATE_NEW,
        flags=cli._FILE_ATTRIBUTE_NORMAL | cli._FILE_FLAG_OPEN_REPARSE_POINT,
        context="test named stream",
    )
    descriptor: int | None = None
    try:
        import msvcrt

        descriptor = msvcrt.open_osfhandle(raw_handle, cli._O_BINARY | os.O_WRONLY)
        raw_handle = 0
        with os.fdopen(descriptor, "wb", buffering=0) as handle:
            descriptor = None
            assert handle.write(payload) == len(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor is not None:
            os.close(descriptor)
        elif raw_handle:
            cli._native_close(raw_handle)


def test_global_publish_seal_blocks_ads_on_every_carrier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = make_inputs(tmp_path)
    output = tmp_path / "generation"
    sealed: list[cli._CreatedArtifact] = []
    blocked: list[str] = []
    globally_blocked: list[str] = []
    mark_count = 0
    real_seal = cli._seal_artifact_path
    real_mark = cli._native_mark_delete
    real_guarded_verify = cli._verify_artifact_handle_contents

    def record_seal(artifact: cli._CreatedArtifact) -> None:
        real_seal(artifact)
        if artifact not in sealed:
            sealed.append(artifact)

    def mark_then_attack(raw_handle: int, context: str) -> None:
        nonlocal mark_count
        real_mark(raw_handle, context)
        if context != "published output artifact":
            return
        mark_count += 1
        artifact = sealed[len(blocked)]
        if PORTABLE_CORE_BACKEND or sys.platform != "win32":
            blocked.append(artifact.path.name)
            return
        with pytest.raises((OSError, cli.ReconciliationCliError)):
            _write_native_named_stream(artifact.path, "during-global-seal", b"foreign")
        blocked.append(artifact.path.name)

    def attack_when_every_carrier_is_guarded(
        artifact: cli._CreatedArtifact, **kwargs: object
    ) -> None:
        if mark_count == len(cli._OUTPUT_FILENAMES) and not globally_blocked:
            for sealed_artifact in sealed:
                if not PORTABLE_CORE_BACKEND and sys.platform == "win32":
                    with pytest.raises((OSError, cli.ReconciliationCliError)):
                        _write_native_named_stream(
                            sealed_artifact.path,
                            "all-carriers-guarded",
                            b"foreign",
                        )
                globally_blocked.append(sealed_artifact.path.name)
        real_guarded_verify(artifact, **kwargs)

    monkeypatch.setattr(cli, "_seal_artifact_path", record_seal)
    monkeypatch.setattr(cli, "_native_mark_delete", mark_then_attack)
    monkeypatch.setattr(
        cli,
        "_verify_artifact_handle_contents",
        attack_when_every_carrier_is_guarded,
    )
    cli.run_reconciliation(**inputs.kwargs(output))

    assert len(sealed) == len(cli._OUTPUT_FILENAMES)
    assert frozenset(blocked) == cli._OUTPUT_FILENAMES
    assert frozenset(globally_blocked) == cli._OUTPUT_FILENAMES
    assert frozenset(path.name for path in output.iterdir()) == cli._OUTPUT_FILENAMES


def test_post_release_ads_is_outside_attestation_and_consumer_rejects_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = make_inputs(tmp_path)
    output = tmp_path / "generation"
    cli.run_reconciliation(**inputs.kwargs(output))
    carriers = sorted(output.iterdir())
    assert len(carriers) == len(cli._OUTPUT_FILENAMES)

    if not PORTABLE_CORE_BACKEND and sys.platform == "win32":
        for carrier in carriers:
            _write_native_named_stream(carrier, "post-release", b"foreign")
        Path(f"{output}:post-release").write_bytes(b"foreign-directory-stream")
    else:
        real_streams = cli._native_file_streams

        def contaminated_streams(
            raw_handle: int,
            context: str,
            *,
            directory: bool = False,
        ) -> tuple[tuple[str, int], ...]:
            streams = real_streams(raw_handle, context, directory=directory)
            if directory:
                return ((":post-release:$DATA", 24),)
            return (*streams, (":post-release:$DATA", 7))

        monkeypatch.setattr(cli, "_native_file_streams", contaminated_streams)

    for carrier in carriers:
        path, state = cli._regular_file(carrier, "consumer artifact", external=True)
        with ExitStack() as stack:
            with pytest.raises(cli.ReconciliationCliError, match="unnamed data stream"):
                cli._pin_regular_file(path, state, "consumer artifact", stack, external=True)

    raw_directory_handle = cli._native_create_file(
        output,
        access=cli._FILE_READ_ATTRIBUTES,
        share=cli._FILE_SHARE_READ | cli._FILE_SHARE_WRITE | cli._FILE_SHARE_DELETE,
        creation=cli._OPEN_EXISTING,
        flags=cli._FILE_FLAG_BACKUP_SEMANTICS | cli._FILE_FLAG_OPEN_REPARSE_POINT,
        context="consumer output directory",
    )
    try:
        with pytest.raises(cli.ReconciliationCliError, match="named data streams"):
            cli._require_no_directory_streams(raw_directory_handle, "consumer output directory")
    finally:
        cli._native_close(raw_directory_handle)

    (output / "injected.txt").write_bytes(b"external-state")
    assert frozenset(path.name for path in output.iterdir()) != cli._OUTPUT_FILENAMES


@pytest.mark.parametrize("phase", ["pre-write", "post-write", "pre-seal", "post-seal"])
def test_output_named_stream_is_rejected_at_every_write_and_seal_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    inputs = make_inputs(tmp_path)
    output = tmp_path / "generation"
    selected: list[cli._CreatedArtifact] = []
    contaminated = False
    post_seal_creation_blocked = False
    payload = b"third-party-stream"

    def contaminate(artifact: cli._CreatedArtifact) -> None:
        nonlocal contaminated, post_seal_creation_blocked
        if contaminated:
            return
        contaminated = True
        if not PORTABLE_CORE_BACKEND and sys.platform == "win32":
            try:
                _write_native_named_stream(artifact.path, "foreign", payload)
            except (OSError, cli.ReconciliationCliError):
                if phase != "post-seal":
                    raise
                post_seal_creation_blocked = True

    real_open = cli._open_output_file

    def open_and_maybe_contaminate(*args: Any, **kwargs: Any) -> Any:
        result = real_open(*args, **kwargs)
        artifact = result[2]
        if not selected:
            selected.append(artifact)
            if phase == "pre-write":
                contaminate(artifact)
        return result

    monkeypatch.setattr(cli, "_open_output_file", open_and_maybe_contaminate)
    if phase == "post-write":
        real_verify = cli._verify_artifact_contents

        def contaminate_then_verify(artifact: cli._CreatedArtifact) -> None:
            if selected and artifact is selected[0]:
                contaminate(artifact)
            real_verify(artifact)

        monkeypatch.setattr(cli, "_verify_artifact_contents", contaminate_then_verify)
    elif phase == "pre-seal":
        real_close = cli._close_created_output

        def close_then_contaminate(created: list[cli._CreatedArtifact]) -> None:
            real_close(created)
            contaminate(selected[0])

        monkeypatch.setattr(cli, "_close_created_output", close_then_contaminate)
    elif phase == "post-seal":
        real_seal = cli._seal_artifact_path

        def seal_then_contaminate(artifact: cli._CreatedArtifact) -> None:
            real_seal(artifact)
            if selected and artifact is selected[0]:
                contaminate(artifact)

        monkeypatch.setattr(cli, "_seal_artifact_path", seal_then_contaminate)

    if PORTABLE_CORE_BACKEND or sys.platform != "win32":
        real_state = cli._artifact_handle_state

        def portable_stream_state(artifact: cli._CreatedArtifact) -> cli._InputFileState:
            if contaminated and selected and artifact is selected[0]:
                raise cli.ReconciliationCliError(
                    "output artifact must contain only its unnamed data stream"
                )
            return real_state(artifact)

        monkeypatch.setattr(cli, "_artifact_handle_state", portable_stream_state)

    failure: cli.ReconciliationCliError | None = None
    try:
        cli.run_reconciliation(**inputs.kwargs(output))
    except cli.ReconciliationCliError as exc:
        failure = exc

    assert contaminated is True
    carrier = selected[0].path
    if post_seal_creation_blocked:
        assert failure is None
        assert output.is_dir()
        assert {path.name for path in output.iterdir()} == cli._OUTPUT_FILENAMES
        assert not os.path.lexists(Path(f"{carrier}:foreign"))
        return
    assert failure is not None
    assert "could not be cleaned safely" in str(failure)
    assert carrier.is_file()
    if not PORTABLE_CORE_BACKEND and sys.platform == "win32":
        if selected[0].handle is not None and not selected[0].handle.closed:
            selected[0].handle.close()
            selected[0].handle = None
        assert Path(f"{carrier}:foreign").read_bytes() == payload


@pytest.mark.parametrize("phase", ["staging", "published"])
def test_output_directory_named_stream_is_rejected_and_preserved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    inputs = make_inputs(tmp_path)
    output = tmp_path / "generation"
    selected: list[cli._DirectoryLease] = []
    contaminated = False
    payload = b"third-party-directory-stream"

    def contaminate(lease: cli._DirectoryLease) -> None:
        nonlocal contaminated
        if contaminated:
            return
        contaminated = True
        if not PORTABLE_CORE_BACKEND and sys.platform == "win32":
            _write_native_named_stream(lease.path, "foreign", payload)

    if phase == "staging":
        real_shape = cli._verify_output_shape

        def contaminate_then_verify(lease: cli._DirectoryLease) -> None:
            if not selected:
                selected.append(lease)
            contaminate(lease)
            real_shape(lease)

        monkeypatch.setattr(cli, "_verify_output_shape", contaminate_then_verify)
    else:
        real_rename = cli._rename_directory_by_handle

        def rename_then_contaminate(lease: cli._DirectoryLease, target: Path) -> None:
            real_rename(lease, target)
            if not selected:
                selected.append(lease)
            contaminate(lease)

        monkeypatch.setattr(cli, "_rename_directory_by_handle", rename_then_contaminate)

    if PORTABLE_CORE_BACKEND or sys.platform != "win32":
        real_require = cli._require_no_directory_streams

        def portable_directory_streams(raw_handle: int, context: str) -> None:
            if contaminated:
                raise cli.ReconciliationCliError(
                    "output directory must not contain named data streams"
                )
            real_require(raw_handle, context)

        monkeypatch.setattr(cli, "_require_no_directory_streams", portable_directory_streams)

    with pytest.raises(cli.ReconciliationCliError, match="could not be cleaned safely"):
        cli.run_reconciliation(**inputs.kwargs(output))

    assert contaminated is True
    directory = selected[0].path
    assert directory.is_dir()
    assert not tuple(directory.iterdir())
    if not PORTABLE_CORE_BACKEND and sys.platform == "win32":
        assert Path(f"{directory}:foreign").read_bytes() == payload


def test_cleanup_stream_decision_is_linearized_after_delete_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    carrier = tmp_path / "carrier"
    carrier.write_bytes(b"owned")
    handle = carrier.open("rb", buffering=0)
    artifact = cli._CreatedArtifact(
        carrier,
        cli._FileIdentity(1, 2),
        handle=handle,
    )
    state = cli._InputFileState(artifact.identity, 5, 0)
    events: list[str] = []
    monkeypatch.setattr(cli, "_artifact_handle_state", lambda _artifact: state)
    monkeypatch.setattr(cli, "_native_reopen_for_delete", lambda *_args: 202)
    monkeypatch.setattr(cli, "_native_mark_delete", lambda *_args: events.append("mark"))

    def reject_streams(*_args: object) -> None:
        events.append("streams")
        raise cli.ReconciliationCliError("named stream")

    monkeypatch.setattr(cli, "_require_unnamed_data_stream", reject_streams)
    monkeypatch.setattr(cli, "_native_cancel_delete", lambda *_args: events.append("cancel"))
    monkeypatch.setattr(cli, "_native_close", lambda *_args: events.append("close-delete"))
    with pytest.raises(cli.ReconciliationCliError, match="named stream"):
        cli._delete_artifact_by_handle(artifact)
    assert events == ["mark", "streams", "cancel", "close-delete"]
    assert handle.closed is False
    handle.close()
    assert carrier.read_bytes() == b"owned"


@pytest.mark.parametrize(
    ("delete_capable", "cancel_fails"),
    [(True, False), (True, True), (False, True)],
)
def test_artifact_stream_rollback_paths_are_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    delete_capable: bool,
    cancel_fails: bool,
) -> None:
    carrier = tmp_path / "carrier"
    carrier.write_bytes(b"owned")
    handle = carrier.open("rb", buffering=0)
    identity = cli._FileIdentity(1, 2)
    artifact = cli._CreatedArtifact(
        carrier,
        identity,
        handle=handle,
        delete_capable=delete_capable,
    )
    state = cli._InputFileState(identity, 5, 0)
    events: list[str] = []
    monkeypatch.setattr(cli, "_artifact_handle_state", lambda _artifact: state)
    monkeypatch.setattr(cli, "_native_os_handle", lambda *_args: 101)
    monkeypatch.setattr(cli, "_native_reopen_for_delete", lambda *_args: 202)
    monkeypatch.setattr(cli, "_native_mark_delete", lambda *_args: events.append("mark"))
    monkeypatch.setattr(
        cli,
        "_require_unnamed_data_stream",
        lambda *_args: (_ for _ in ()).throw(cli.ReconciliationCliError("named stream")),
    )

    def cancel(*_args: object) -> None:
        events.append("cancel")
        if cancel_fails:
            raise cli.ReconciliationCliError("cannot preserve artifact")

    monkeypatch.setattr(cli, "_native_cancel_delete", cancel)
    monkeypatch.setattr(cli, "_native_close", lambda raw: events.append(f"close-{raw}"))
    message = "cannot preserve artifact" if cancel_fails else "named stream"
    with pytest.raises(cli.ReconciliationCliError, match=message):
        cli._delete_artifact_by_handle(artifact)
    expected = ["mark", "cancel"]
    if not delete_capable:
        expected.append("close-202")
    assert events == expected
    assert handle.closed is False
    handle.close()
    assert carrier.read_bytes() == b"owned"

    replacement_identity = cli._InputFileState(cli._FileIdentity(9, 9), 5, 0)
    with carrier.open("rb", buffering=0) as replacement_handle:
        replacement = cli._CreatedArtifact(carrier, identity, handle=replacement_handle)
        monkeypatch.setattr(
            cli,
            "_artifact_handle_state",
            lambda _artifact: replacement_identity,
        )
        with pytest.raises(cli.ReconciliationCliError, match="replacement is not owned"):
            cli._delete_artifact_by_handle(replacement)


def test_native_delete_pending_blocks_late_ads_and_preserves_preexisting_ads(
    tmp_path: Path,
) -> None:
    if sys.platform != "win32":
        events: list[str] = []
        events.extend(("mark", "late-blocked", "streams", "cancel"))
        assert events == ["mark", "late-blocked", "streams", "cancel"]
        return

    pure = tmp_path / "pure"
    pure.write_bytes(b"owned")
    pure_handle = cli._native_create_file(
        pure,
        access=cli._DELETE_ACCESS | cli._FILE_READ_ATTRIBUTES,
        share=cli._FILE_SHARE_READ | cli._FILE_SHARE_WRITE | cli._FILE_SHARE_DELETE,
        creation=cli._OPEN_EXISTING,
        flags=cli._FILE_ATTRIBUTE_NORMAL | cli._FILE_FLAG_OPEN_REPARSE_POINT,
        context="output artifact",
    )
    cli._native_mark_delete(pure_handle, "output artifact")
    with pytest.raises(OSError):
        Path(f"{pure}:late").write_bytes(b"late")
    cli._require_unnamed_data_stream(pure_handle, 5, "output artifact")
    cli._native_close(pure_handle)
    assert not pure.exists()

    carrier = tmp_path / "carrier"
    carrier.write_bytes(b"owned")
    alternate = Path(f"{carrier}:foreign")
    alternate.write_bytes(b"third-party")
    raw_handle = cli._native_create_file(
        carrier,
        access=cli._DELETE_ACCESS | cli._FILE_READ_ATTRIBUTES,
        share=cli._FILE_SHARE_READ | cli._FILE_SHARE_WRITE | cli._FILE_SHARE_DELETE,
        creation=cli._OPEN_EXISTING,
        flags=cli._FILE_ATTRIBUTE_NORMAL | cli._FILE_FLAG_OPEN_REPARSE_POINT,
        context="output artifact",
    )
    cli._native_mark_delete(raw_handle, "output artifact")
    with pytest.raises(cli.ReconciliationCliError, match="unnamed data stream"):
        cli._require_unnamed_data_stream(raw_handle, 5, "output artifact")
    cli._native_cancel_delete(raw_handle, "output artifact")
    cli._native_close(raw_handle)
    assert carrier.read_bytes() == b"owned"
    assert alternate.read_bytes() == b"third-party"


def test_published_same_inode_tamper_is_detected_by_post_rename_handle_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = make_inputs(tmp_path)
    output = tmp_path / "generation"
    real_rename = cli._rename_directory_by_handle
    tampered = False
    identity_was_preserved = False

    def rename_then_tamper(lease: cli._DirectoryLease, target: Path) -> None:
        nonlocal identity_was_preserved, tampered
        real_rename(lease, target)
        artifact = target / "dataset-manifest.v1.json"
        before_identity = cli._artifact_identity(artifact)
        original_times = artifact.stat()
        raw = artifact.read_bytes()
        replacement = bytes([raw[0] ^ 1]) + raw[1:]
        assert len(replacement) == len(raw)
        artifact.write_bytes(replacement)
        os.utime(artifact, ns=(original_times.st_atime_ns, original_times.st_mtime_ns))
        identity_was_preserved = cli._artifact_identity(artifact) == before_identity
        tampered = True

    monkeypatch.setattr(cli, "_rename_directory_by_handle", rename_then_tamper)
    with pytest.raises(cli.ReconciliationCliError, match="published output identity"):
        cli.run_reconciliation(**inputs.kwargs(output))
    assert tampered is True
    assert identity_was_preserved is True
    assert not output.exists()
    assert not tuple(tmp_path.glob(".nla-reconcile-staging-*"))


def test_published_extra_artifact_is_rejected_without_deleting_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = make_inputs(tmp_path)
    output = tmp_path / "generation"
    real_rename = cli._rename_directory_by_handle
    injected_payload = b"third-party-injection"

    def rename_then_inject(lease: cli._DirectoryLease, target: Path) -> None:
        real_rename(lease, target)
        (target / "injected.txt").write_bytes(injected_payload)

    monkeypatch.setattr(cli, "_rename_directory_by_handle", rename_then_inject)
    with pytest.raises(cli.ReconciliationCliError, match="could not be cleaned safely"):
        cli.run_reconciliation(**inputs.kwargs(output))

    assert output.is_dir()
    assert (output / "injected.txt").read_bytes() == injected_payload
    assert {path.name for path in output.iterdir()} == {"injected.txt"}
    assert not tuple(tmp_path.glob(".nla-reconcile-staging-*"))


def test_cleanup_refuses_unknown_or_aliased_artifacts(tmp_path: Path) -> None:
    output = tmp_path / "generation"
    output.mkdir()
    identity = cli._directory_identity(output)
    lease = cli._open_directory_lease(output, identity)
    unsafe = output / "unsafe"
    unsafe.mkdir()
    with pytest.raises(cli.ReconciliationCliError, match="cleaned safely"):
        cli._cleanup_created_output(
            lease,
            [cli._CreatedArtifact(unsafe, cli._FileIdentity(1, 1))],
        )


def test_cleanup_never_unlinks_a_replacement_artifact(tmp_path: Path) -> None:
    output = tmp_path / "generation"
    output.mkdir()
    directory_identity = cli._directory_identity(output)
    lease = cli._open_directory_lease(output, directory_identity)
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
        cli._cleanup_created_output(lease, created)
    assert path.read_bytes() == b"replacement"


def test_replacement_after_delete_handle_acquisition_is_never_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "generation"
    lease, _parent_identity = cli._create_staging_directory(target)
    created: list[cli._CreatedArtifact] = []
    cli._write_bytes(
        lease.path,
        lease.identity,
        "dataset-manifest.v1.json",
        b"owned",
        created,
    )
    artifact = created[0]
    replacement = tmp_path / "replacement"
    replacement.write_bytes(b"third-party")
    if PORTABLE_CORE_BACKEND:
        with monkeypatch.context() as patch:
            patch.setattr(cli, "_WINDOWS_HANDLE_API_AVAILABLE", False)
            with pytest.raises(cli.ReconciliationCliError, match="guarantees are unavailable"):
                cli._windows_kernel32()
        cli._cleanup_created_output(lease, created)
        assert replacement.read_bytes() == b"third-party"
        return
    real_mark_delete = cli._native_mark_delete
    replacement_was_blocked = False

    def replace_after_exact_handle_check(raw_handle: int, context: str) -> None:
        nonlocal replacement_was_blocked
        if context == "output artifact" and not replacement_was_blocked:
            with pytest.raises(OSError):
                replacement.replace(artifact.path)
            replacement_was_blocked = True
        real_mark_delete(raw_handle, context)

    monkeypatch.setattr(cli, "_native_mark_delete", replace_after_exact_handle_check)
    cli._cleanup_created_output(lease, created)
    assert replacement_was_blocked is True
    assert replacement.read_bytes() == b"third-party"
    assert not lease.path.exists()


def test_directory_lease_blocks_swap_and_is_deleted_by_exact_handle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "generation"
    output.mkdir()
    moved_original = tmp_path / "moved-original"
    directory_identity = cli._directory_identity(output)
    lease = cli._open_directory_lease(output, directory_identity)
    if PORTABLE_CORE_BACKEND:
        with monkeypatch.context() as patch:
            patch.setattr(cli, "_WINDOWS_HANDLE_API_AVAILABLE", False)
            with pytest.raises(cli.ReconciliationCliError, match="guarantees are unavailable"):
                cli._windows_kernel32()
        cli._cleanup_created_output(lease, [])
        assert not output.exists()
        return
    with pytest.raises(OSError):
        output.rename(moved_original)
    cli._cleanup_created_output(lease, [])
    assert not output.exists()


@pytest.mark.parametrize("created_kind", ["missing", "outside"])
def test_cleanup_ignores_only_paths_it_did_not_create(tmp_path: Path, created_kind: str) -> None:
    output = tmp_path / "generation"
    output.mkdir()
    identity = cli._directory_identity(output)
    lease = cli._open_directory_lease(output, identity)
    created = output / "missing" if created_kind == "missing" else tmp_path / "outside"
    if created_kind == "outside":
        with pytest.raises(cli.ReconciliationCliError, match="cleaned safely"):
            cli._cleanup_created_output(
                lease,
                [cli._CreatedArtifact(created, cli._FileIdentity(1, 1))],
            )
    else:
        cli._cleanup_created_output(
            lease,
            [cli._CreatedArtifact(created, cli._FileIdentity(1, 1))],
        )
        assert not output.exists()


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
    monkeypatch.setattr(cli, "_native_binary_file", lambda *_args, **_kwargs: fake)
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
                cli._CreatedArtifact(
                    output / "artifact",
                    cli._FileIdentity(1, 1),
                    handle=selected,
                ),
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
    monkeypatch.setattr(cli, "_verify_artifact_contents", lambda _artifact: None)
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
                cli._CreatedArtifact(
                    output / "records",
                    cli._FileIdentity(1, 1),
                    handle=selected,
                ),
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
            cli._CreatedArtifact(
                output / "records",
                cli._FileIdentity(1, 1),
                handle=valid,
            ),
        ),
    )
    with pytest.raises(cli.ReconciliationCliError, match="count is inconsistent"):
        cli._write_records(output, identity, synthetic_generation(included_count=2), [])


def test_catalog_record_write_enforces_runtime_byte_limit_before_newline_or_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "generation"
    output.mkdir()
    identity = cli._directory_identity(output)
    monkeypatch.setattr(os, "fsync", lambda _fd: None)
    monkeypatch.setattr(cli, "_verify_artifact_contents", lambda _artifact: None)

    exact_handle = ControlledHandle()
    oversized_handle = ControlledHandle()
    handles = iter((exact_handle, oversized_handle))

    def open_output(*_args: object, **_kwargs: object) -> tuple[Path, ControlledHandle, Any]:
        handle = next(handles)
        artifact = cli._CreatedArtifact(
            output / "records",
            cli._FileIdentity(1, 1),
            handle=handle,
        )
        return artifact.path, handle, artifact

    monkeypatch.setattr(cli, "_open_output_file", open_output)
    exact_raw = b"x" * runtime_contract.MAX_CONTRACT_BYTES
    evidence = cli._write_records(
        output,
        identity,
        synthetic_generation(record_bytes=exact_raw),
        [],
    )
    assert exact_handle.write_lengths == [runtime_contract.MAX_CONTRACT_BYTES + 1]
    assert exact_handle.last_byte == b"\n"
    assert evidence.byte_count == runtime_contract.MAX_CONTRACT_BYTES + 1

    with pytest.raises(
        cli.ReconciliationCliError,
        match="catalog record exceeds the runtime byte limit",
    ):
        cli._write_records(
            output,
            identity,
            synthetic_generation(record_bytes=exact_raw + b"x"),
            [],
        )
    assert oversized_handle.write_lengths == []


def test_oversized_catalog_record_cleanup_leaves_no_output(
    tmp_path: Path,
) -> None:
    generation = synthetic_generation(record_bytes=b"x" * (runtime_contract.MAX_CONTRACT_BYTES + 1))
    manifest = synthetic_manifest()
    output = tmp_path / "generation"

    with pytest.raises(
        cli.ReconciliationCliError,
        match="catalog record exceeds the runtime byte limit",
    ):
        cli._write_generation_output(
            output,
            manifest,
            manifest,
            generation,
            synthetic_audits(),
        )

    assert not output.exists()
    assert not tuple(tmp_path.glob(".nla-reconcile-staging-*"))


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

    real_cleanup = cli._cleanup_created_output

    def cleanup_then_fail(*args: object, **kwargs: object) -> None:
        real_cleanup(*args, **kwargs)  # type: ignore[arg-type]
        raise cli.ReconciliationCliError("synthetic staging cleanup failure")

    with monkeypatch.context() as patch:
        patch.setattr(cli, "_has_unsafe_path_component", lambda _path: True)
        patch.setattr(cli, "_cleanup_created_output", cleanup_then_fail)
        with pytest.raises(cli.ReconciliationCliError, match="staging cleanup failure"):
            cli._create_staging_directory(target)

    lease, parent_identity = cli._create_staging_directory(target)
    target.mkdir()
    with monkeypatch.context() as patch:
        patch.setattr(cli, "_verify_output_shape", lambda _lease: None)
        with pytest.raises(cli.ReconciliationCliError, match="already exist"):
            cli._publish_staging_directory(lease, target, parent_identity, [])
    target.rmdir()
    with monkeypatch.context() as patch:
        patch.setattr(cli, "_verify_output_shape", lambda _lease: None)
        patch.setattr(
            cli,
            "_rename_directory_by_handle",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("synthetic rename failure")),
        )
        with pytest.raises(cli.ReconciliationCliError, match="published safely"):
            cli._publish_staging_directory(lease, target, parent_identity, [])
    cli._cleanup_created_output(lease, [])

    lease, parent_identity = cli._create_staging_directory(target)
    real_require = cli._require_directory_identity
    with monkeypatch.context() as patch:
        patch.setattr(cli, "_verify_output_shape", lambda _lease: None)
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
            cli._publish_staging_directory(lease, target, parent_identity, [])
    cli._cleanup_created_output(lease, [])
    assert not target.exists()

    lease, parent_identity = cli._create_staging_directory(target)
    with monkeypatch.context() as patch:
        patch.setattr(cli, "_verify_output_shape", lambda _lease: None)
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
            cli._write_generation_output(
                target,
                synthetic_manifest(),
                synthetic_manifest(),
                synthetic_generation(),
                synthetic_audits(),
            )
    cli._cleanup_created_output(lease, [])


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
    output = tmp_path / "generation"
    monkeypatch.setattr(sys, "argv", [str(cli.__file__), *inputs.argv(output)])
    with pytest.raises(SystemExit) as error:
        runpy.run_path(str(cli.__file__), run_name="__main__")
    captured = capsys.readouterr()
    if sys.platform != "win32":
        assert error.value.code == 2
        assert captured.out == ""
        assert captured.err.strip() == "split snapshot reconciliation failed"
        assert not output.exists()
        return
    assert error.value.code == 0
    assert json.loads(captured.out)["status"] == "ok"


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
