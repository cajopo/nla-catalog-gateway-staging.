from __future__ import annotations

import builtins
import ctypes
import hashlib
import inspect
import json
import os
import stat
import struct
import sys
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field, fields, replace
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import Any, BinaryIO

import pytest

import nla_catalog_gateway.generation_bundle as generation_bundle
from nla_catalog_gateway import bulk, reconciliation
from nla_catalog_gateway import runtime_contract as runtime
from nla_catalog_gateway.taxonomy import ClassificationReport, Game, ProductFamily

NOW = "2026-09-05T10:00:00Z"
SHOP = "synthetic.myshopify.com"
RULE_VERSION = "2026-09-01.1"
SUMMARY_NAME = "reconciliation-summary.v1.json"
CATALOG_NAME = "catalog-records.v1.jsonl"
EXPECTED_NAMES = frozenset((*generation_bundle._ARTIFACT_FILENAMES, SUMMARY_NAME))

TRUST_ERROR = "generation bundle trust root is invalid"
FILESYSTEM_ERROR = "generation bundle filesystem boundary is invalid"
SHAPE_ERROR = "generation bundle shape is invalid"
CONTENT_ERROR = "generation bundle contents are invalid"
CHANGED_ERROR = "generation bundle changed during verification"


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _variant(product_id: str) -> runtime.CatalogVariantRecordV1:
    return runtime.CatalogVariantRecordV1(
        variant_gid=f"gid://shopify/ProductVariant/{product_id}0",
        product_gid=f"gid://shopify/Product/{product_id}",
        inventory_item_gid=f"gid://shopify/InventoryItem/{product_id}00",
        title="Default Title",
        sku=f"SKU-{product_id}",
        barcode=None,
        selected_options=(runtime.SelectedOptionV1("Title", "Default Title"),),
        price_text="1.2300",
        compare_at_price_text=None,
        inventory_quantity=2,
        inventory_policy=runtime.InventoryPolicy.DENY,
        inventory_tracked=True,
        updated_at=NOW,
    )


def _product(
    product_id: str,
    *,
    family: ProductFamily = ProductFamily.SINGLE,
    status: runtime.ProductStatus = runtime.ProductStatus.ACTIVE,
    published: bool = True,
    source_id: str | None = None,
    handle: str | None = None,
) -> runtime.CatalogProductRecordV1:
    sealed = family is ProductFamily.SEALED
    unclassified = family is ProductFamily.UNCLASSIFIED
    identity = product_id if source_id is None else source_id
    return runtime.CatalogProductRecordV1(
        product_gid=f"gid://shopify/Product/{product_id}",
        handle=handle or f"synthetic-{product_id}",
        commercial_title=f"Synthetic Product {product_id}",
        canonical_card_name=None if sealed or unclassified else f"Synthetic Card {product_id}",
        shopify_status=status,
        online_store_published=published,
        powertools_source_id=identity,
        sync_source_id=identity,
        total_inventory=2,
        tracks_inventory=True,
        updated_at=NOW,
        game=None if unclassified else Game.MAGIC,
        product_family=family,
        product_subtype="booster-box" if sealed else None,
        classification_rule_version=RULE_VERSION,
        classification_rule_id=None if unclassified else f"family:{family.value}",
        unclassified_reason="unknown_product_type" if unclassified else None,
        subtype_rule_id="sealed:booster-box" if sealed else None,
        subtype_reason=None,
        variants=(_variant(product_id),),
    )


def _base_records() -> tuple[runtime.CatalogProductRecordV1, ...]:
    return (
        _product("1"),
        _product(
            "2",
            family=ProductFamily.SEALED,
            status=runtime.ProductStatus.DRAFT,
            published=False,
        ),
        _product(
            "3",
            family=ProductFamily.UNCLASSIFIED,
            status=runtime.ProductStatus.ARCHIVED,
            published=False,
        ),
    )


def _part_manifest(
    records: tuple[runtime.CatalogProductRecordV1, ...],
    part: reconciliation.SnapshotPart,
) -> reconciliation.SnapshotPartManifestV1:
    product_count = len(records)
    variant_count = sum(len(record.variants) for record in records)
    if part is reconciliation.SnapshotPart.PRODUCTS:
        object_counts = (
            ("Metafield", 0),
            ("Product", product_count),
            ("ResourcePublicationV2", product_count),
        )
        root_count = product_count
        operation_id = "gid://shopify/BulkOperation/11"
        content_sha256 = "e" * 64
    else:
        object_counts = (
            ("InventoryLevel", variant_count),
            ("Metafield", 0),
            ("ProductVariant", variant_count),
        )
        root_count = variant_count
        operation_id = "gid://shopify/BulkOperation/12"
        content_sha256 = "f" * 64
    values: dict[str, Any] = {
        "schema_version": 1,
        "part": part,
        "snapshot_set_id": "sha256:" + "1" * 64,
        "shop_domain": SHOP,
        "api_version": "2026-07",
        "operation_id": operation_id,
        "operation_type": "QUERY",
        "status": "COMPLETED",
        "error_code": None,
        "url_present": True,
        "partial_data_url_present": False,
        "created_at": NOW,
        "completed_at": NOW,
        "online_store_publication_gid": "gid://shopify/Publication/1",
        "source_code_sha": "b" * 40,
        "query_sha256": generation_bundle._APPROVED_QUERY_SHA256[part],
        "content_sha256": content_sha256,
        "snapshot_bytes": 1234,
        "object_count": sum(count for _, count in object_counts),
        "root_object_count": root_count,
        "object_counts": object_counts,
        "capture_fence_max_seconds": reconciliation.CAPTURE_FENCE_MAX_SECONDS,
    }
    draft = object.__new__(reconciliation.SnapshotPartManifestV1)
    for name, value in values.items():
        object.__setattr__(draft, name, value)
    object.__setattr__(draft, "part_generation", "sha256:" + "0" * 64)
    values["part_generation"] = draft.expected_part_generation()
    return reconciliation.SnapshotPartManifestV1(**values)


def _replace_part_manifest(
    manifest: reconciliation.SnapshotPartManifestV1,
    **changes: Any,
) -> reconciliation.SnapshotPartManifestV1:
    values = {item.name: getattr(manifest, item.name) for item in fields(manifest)}
    values.update(changes)
    draft = object.__new__(reconciliation.SnapshotPartManifestV1)
    for name, value in values.items():
        object.__setattr__(draft, name, value)
    object.__setattr__(draft, "part_generation", "sha256:" + "0" * 64)
    values["part_generation"] = draft.expected_part_generation()
    return reconciliation.SnapshotPartManifestV1(**values)


def _classification_report(
    records: tuple[runtime.CatalogProductRecordV1, ...],
) -> ClassificationReport:
    classified = sum(record.product_family is not ProductFamily.UNCLASSIFIED for record in records)
    return ClassificationReport(
        rule_version=RULE_VERSION,
        total=len(records),
        classified=classified,
        unclassified=len(records) - classified,
        counts=MappingProxyType(
            dict(
                Counter(
                    f"{record.game.value if record.game else 'unknown'}/"
                    f"{record.product_family.value}"
                    for record in records
                )
            )
        ),
        rule_counts=MappingProxyType(
            dict(
                Counter(
                    record.classification_rule_id
                    for record in records
                    if record.classification_rule_id is not None
                )
            )
        ),
        unclassified_reasons=MappingProxyType(
            dict(
                Counter(
                    record.unclassified_reason
                    for record in records
                    if record.unclassified_reason is not None
                )
            )
        ),
        subtype_reasons=MappingProxyType(
            dict(
                Counter(
                    record.subtype_reason for record in records if record.subtype_reason is not None
                )
            )
        ),
    )


def _generation(
    records: tuple[runtime.CatalogProductRecordV1, ...],
) -> tuple[
    reconciliation.SnapshotPartManifestV1,
    reconciliation.SnapshotPartManifestV1,
    reconciliation.ReconciledCatalogGenerationV1,
]:
    products = _part_manifest(records, reconciliation.SnapshotPart.PRODUCTS)
    variants = _part_manifest(records, reconciliation.SnapshotPart.VARIANTS)
    variant_count = sum(len(record.variants) for record in records)
    counts = reconciliation._SourceCounts(
        product_count=len(records),
        variant_count=variant_count,
        inventory_item_count=variant_count,
        inventory_level_count=variant_count,
        publication_count=len(records),
        metafield_count=0,
        product_status_counts=tuple(
            (
                status,
                sum(record.shopify_status.value == status for record in records),
            )
            for status in bulk.PRODUCT_STATUSES
        ),
        active_published_product_count=sum(record.publishable for record in records),
        source_identity_product_count=sum(
            record.powertools_source_id is not None for record in records
        ),
    )
    source = reconciliation._build_source_manifest(
        (
            SimpleNamespace(manifest=products),
            SimpleNamespace(manifest=variants),
        ),
        counts,
    )
    report = _classification_report(records)
    dataset = reconciliation._runtime_manifest(source, records, report)
    return (
        products,
        variants,
        reconciliation.ReconciledCatalogGenerationV1(
            source_manifest=source,
            source_manifest_bytes=source.to_json_bytes(),
            taxonomy_report=report,
            records=records,
            dataset_manifest=dataset,
        ),
    )


@dataclass(frozen=True, slots=True)
class BundleCase:
    directory: Path
    summary_sha256: str
    records: tuple[runtime.CatalogProductRecordV1, ...]
    generation: reconciliation.ReconciledCatalogGenerationV1


def _write_bundle(
    directory: Path,
    records: tuple[runtime.CatalogProductRecordV1, ...],
) -> BundleCase:
    products, variants, value = _generation(records)
    catalog_raw = b"".join(record.to_json_bytes() + b"\n" for record in records)
    taxonomy_raw = _canonical_json_bytes(
        {
            "schemaVersion": generation_bundle.TAXONOMY_REPORT_SCHEMA_VERSION,
            **value.taxonomy_report.as_dict(),
        }
    )
    artifacts = {
        CATALOG_NAME: catalog_raw,
        "dataset-manifest.v1.json": value.dataset_manifest.to_json_bytes(),
        "products-part-manifest.v1.json": products.to_json_bytes(),
        "source-manifest.v2.json": value.source_manifest_bytes,
        "taxonomy-report.v1.json": taxonomy_raw,
        "variants-part-manifest.v1.json": variants.to_json_bytes(),
    }
    directory.mkdir(parents=True)
    for filename, raw in artifacts.items():
        (directory / filename).write_bytes(raw)
    summary = {
        "artifacts": [
            {
                "bytes": len(artifacts[filename]),
                "filename": filename,
                "recordCount": len(records) if filename == CATALOG_NAME else 1,
                "sha256": hashlib.sha256(artifacts[filename]).hexdigest(),
            }
            for filename in generation_bundle._ARTIFACT_FILENAMES
        ],
        "capabilityPromotion": "not-performed",
        "catalogRecordCount": len(records),
        "classifiedProductCount": value.taxonomy_report.classified,
        "datasetActivation": "not-performed",
        "datasetGeneration": value.dataset_manifest.dataset_generation,
        "schemaVersion": generation_bundle.SUMMARY_SCHEMA_VERSION,
        "snapshotSetId": value.source_manifest.snapshot_set_id,
        "sourceGeneration": value.source_manifest.source_generation,
        "status": "reconciled-provisional",
        "taxonomyRuleVersion": value.taxonomy_report.rule_version,
        "terminalQueryAudits": [
            {
                "approvedQuerySha256": part.query_sha256,
                "part": part.part.value,
                "rawTerminalQuerySha256": hashlib.sha256(
                    f"terminal-{part.part.value}".encode()
                ).hexdigest(),
                "transport": "canonical-lf-v1",
            }
            for part in (products, variants)
        ],
        "unclassifiedProductCount": value.taxonomy_report.unclassified,
        "variantCount": value.source_manifest.variant_count,
    }
    summary_raw = _canonical_json_bytes(summary)
    (directory / SUMMARY_NAME).write_bytes(summary_raw)
    return BundleCase(directory, hashlib.sha256(summary_raw).hexdigest(), records, value)


class _FaultingHandle:
    def __init__(self, raw: BinaryIO, method: str, exception: BaseException | None) -> None:
        self._raw = raw
        self._method = method
        self._exception = exception
        self._fired = False

    @property
    def closed(self) -> bool:
        return self._raw.closed

    def fileno(self) -> int:
        return self._raw.fileno()

    def seek(self, offset: int, whence: int = os.SEEK_SET) -> int:
        return self._raw.seek(offset, whence)

    def read(self, size: int = -1) -> Any:
        if self._method == "read" and not self._fired:
            self._fired = True
            if self._exception is not None:
                raise self._exception
            return "not-binary"
        return self._raw.read(size)

    def readline(self, size: int = -1) -> Any:
        if self._method == "readline" and not self._fired:
            self._fired = True
            if self._exception is not None:
                raise self._exception
            return "not-binary"
        return self._raw.readline(size)


class _ScriptedHandle:
    def __init__(
        self,
        raw: BinaryIO,
        *,
        reads: list[Any] | None = None,
        lines: list[Any] | None = None,
    ) -> None:
        self._raw = raw
        self._reads = list(reads or [])
        self._lines = list(lines or [])

    @property
    def closed(self) -> bool:
        return self._raw.closed

    def fileno(self) -> int:
        return self._raw.fileno()

    def seek(self, offset: int, whence: int = os.SEEK_SET) -> int:
        return self._raw.seek(offset, whence)

    @staticmethod
    def _resolve(value: Any) -> Any:
        if isinstance(value, BaseException):
            raise value
        return value() if callable(value) else value

    def read(self, size: int = -1) -> Any:
        if self._reads:
            return self._resolve(self._reads.pop(0))
        return self._raw.read(size)

    def readline(self, size: int = -1) -> Any:
        if self._lines:
            return self._resolve(self._lines.pop(0))
        return self._raw.readline(size)


class _CountingHandle:
    def __init__(
        self,
        raw: BinaryIO,
        *,
        on_seek: Callable[[int], None] | None = None,
    ) -> None:
        self._raw = raw
        self._on_seek = on_seek
        self.seek_count = 0
        self.read_count = 0
        self.readline_count = 0

    @property
    def closed(self) -> bool:
        return self._raw.closed

    def fileno(self) -> int:
        return self._raw.fileno()

    def seek(self, offset: int, whence: int = os.SEEK_SET) -> int:
        self.seek_count += 1
        if self._on_seek is not None:
            self._on_seek(self.seek_count)
        return self._raw.seek(offset, whence)

    def read(self, size: int = -1) -> bytes:
        self.read_count += 1
        return self._raw.read(size)

    def readline(self, size: int = -1) -> bytes:
        self.readline_count += 1
        return self._raw.readline(size)


class _WinFunction:
    def __init__(self, callback: Callable[..., Any]) -> None:
        self.callback = callback
        self.argtypes: Any = None
        self.restype: Any = None

    def __call__(self, *args: Any) -> Any:
        return self.callback(*args)


def _statement_line(function: Callable[..., Any], statement: str, occurrence: int = 0) -> int:
    source, first_line = inspect.getsourcelines(function)
    matches = [
        first_line + offset for offset, line in enumerate(source) if line.strip() == statement
    ]
    assert len(matches) > occurrence
    return matches[occurrence]


def _statement_line_containing(
    function: Callable[..., Any], fragment: str, occurrence: int = 0
) -> int:
    source, first_line = inspect.getsourcelines(function)
    matches = [first_line + offset for offset, line in enumerate(source) if fragment in line]
    assert len(matches) > occurrence
    return matches[occurrence]


@contextmanager
def _interrupt_on_line(
    function: Callable[..., Any],
    fragment: str,
    interruption: BaseException,
    *,
    occurrence: int = 0,
) -> Iterator[None]:
    target_line = _statement_line_containing(function, fragment, occurrence)
    target_code = function.__code__
    monitoring = sys.monitoring
    tool_id = next(candidate for candidate in range(6) if monitoring.get_tool(candidate) is None)
    monitoring.use_tool_id(tool_id, "generation-bundle-test-interrupt")

    def interrupt_at_target(code: Any, line: int) -> None:
        if code is target_code and line == target_line:
            monitoring.set_local_events(tool_id, target_code, 0)
            raise interruption

    monitoring.register_callback(tool_id, monitoring.events.LINE, interrupt_at_target)
    monitoring.set_local_events(tool_id, target_code, monitoring.events.LINE)
    try:
        yield
    finally:
        monitoring.set_local_events(tool_id, target_code, 0)
        monitoring.register_callback(tool_id, monitoring.events.LINE, None)
        monitoring.free_tool_id(tool_id)


def _stream_payload(
    entries: list[tuple[str | bytes, int, int]],
    *,
    first_next_offset: int | None = None,
) -> bytes:
    payload = bytearray()
    for index, (name_value, stream_size, allocation_size) in enumerate(entries):
        name = name_value.encode("utf-16-le") if isinstance(name_value, str) else name_value
        last = index == len(entries) - 1
        natural_offset = (24 + len(name) + 7) & ~7
        next_offset = 0 if last else natural_offset
        if index == 0 and first_next_offset is not None:
            next_offset = first_next_offset
        entry = struct.pack("<IIqq", next_offset, len(name), stream_size, allocation_size) + name
        if next_offset:
            entry += b"\0" * max(0, next_offset - len(entry))
        payload.extend(entry)
    return bytes(payload)


def _stream_kernel(payload: bytes, *, results: list[bool] | None = None) -> Any:
    outcomes = list(results or [True])

    def get_information(_handle: int, _kind: int, buffer: Any, size: int) -> bool:
        result = outcomes.pop(0) if outcomes else True
        if result:
            ctypes.memmove(ctypes.addressof(buffer), payload, min(len(payload), size))
        return result

    return SimpleNamespace(GetFileInformationByHandleEx=_WinFunction(get_information))


@dataclass(slots=True)
class PortableBackend:
    verify_hook: Callable[[int, generation_bundle._PinnedBundle], None] | None = None
    open_exception: BaseException | None = None
    close_exception: BaseException | None = None
    fault_filename: str | None = None
    fault_method: str = "readline"
    fault_exception: BaseException | None = None
    handle_wrapper: Callable[[str, BinaryIO], Any] | None = None
    handles: list[Any] = field(default_factory=list)
    verify_calls: int = 0
    exit_calls: int = 0

    @contextmanager
    def open(self, directory: Path) -> Iterator[generation_bundle._PinnedBundle]:
        if self.open_exception is not None:
            raise self.open_exception
        names = tuple(path.name for path in directory.iterdir())
        if len(names) != len(EXPECTED_NAMES) or frozenset(names) != EXPECTED_NAMES:
            raise generation_bundle.GenerationBundleError(SHAPE_ERROR)
        facts = directory.stat()
        canonical = generation_bundle._CanonicalHandlePath(
            "portable-volume",
            ("external-generation",),
        )
        try:
            with ExitStack() as stack:
                pinned: dict[str, generation_bundle._PinnedArtifact] = {}
                identities: set[generation_bundle._FileIdentity] = set()
                for filename in (SUMMARY_NAME, *generation_bundle._ARTIFACT_FILENAMES):
                    raw_handle = stack.enter_context((directory / filename).open("r+b"))
                    handle: Any = raw_handle
                    if self.handle_wrapper is not None:
                        handle = self.handle_wrapper(filename, raw_handle)
                    elif filename == self.fault_filename:
                        handle = _FaultingHandle(
                            raw_handle,
                            self.fault_method,
                            self.fault_exception,
                        )
                    self.handles.append(handle)
                    state = generation_bundle._handle_state(handle)
                    if state.identity in identities:
                        raise generation_bundle.GenerationBundleError(FILESYSTEM_ERROR)
                    identities.add(state.identity)
                    pinned[filename] = generation_bundle._PinnedArtifact(
                        filename=filename,
                        path=directory / filename,
                        handle=handle,
                        state=state,
                        canonical_path=generation_bundle._CanonicalHandlePath(
                            canonical.volume_guid,
                            (*canonical.components, filename.casefold()),
                        ),
                    )
                yield generation_bundle._PinnedBundle(
                    directory=directory,
                    directory_identity=generation_bundle._FileIdentity(
                        facts.st_dev,
                        facts.st_ino,
                    ),
                    directory_handle=0,
                    canonical_path=canonical,
                    files=MappingProxyType(pinned),
                )
        finally:
            self.exit_calls += 1
            if self.close_exception is not None:
                raise self.close_exception

    def verify(self, bundle: generation_bundle._PinnedBundle) -> None:
        self.verify_calls += 1
        if self.verify_hook is not None:
            self.verify_hook(self.verify_calls, bundle)
        names = tuple(path.name for path in bundle.directory.iterdir())
        if len(names) != len(EXPECTED_NAMES) or frozenset(names) != EXPECTED_NAMES:
            raise generation_bundle.GenerationBundleError(SHAPE_ERROR)
        facts = bundle.directory.stat()
        if generation_bundle._FileIdentity(facts.st_dev, facts.st_ino) != (
            bundle.directory_identity
        ):
            raise generation_bundle.GenerationBundleError(CHANGED_ERROR)
        if frozenset(bundle.files) != EXPECTED_NAMES or len(bundle.files) != len(EXPECTED_NAMES):
            raise generation_bundle.GenerationBundleError(SHAPE_ERROR)
        identities: set[generation_bundle._FileIdentity] = set()
        for filename in (SUMMARY_NAME, *generation_bundle._ARTIFACT_FILENAMES):
            artifact = bundle.files[filename]
            state = generation_bundle._handle_state(artifact.handle)
            if (
                state != artifact.state
                or generation_bundle._path_file_state(artifact.path) != state
            ):
                raise generation_bundle.GenerationBundleError(CHANGED_ERROR)
            if state.identity in identities:
                raise generation_bundle.GenerationBundleError(CHANGED_ERROR)
            identities.add(state.identity)


@pytest.fixture
def bundle_case(tmp_path: Path) -> BundleCase:
    return _write_bundle(tmp_path / "generation", _base_records())


def _install_backend(
    monkeypatch: pytest.MonkeyPatch,
    backend: PortableBackend | None = None,
) -> PortableBackend:
    selected = backend or PortableBackend()
    monkeypatch.setattr(generation_bundle, "_filesystem_backend", lambda: selected)
    return selected


def _summary_document(case: BundleCase) -> dict[str, Any]:
    return json.loads((case.directory / SUMMARY_NAME).read_bytes())


def _write_summary(case: BundleCase, value: dict[str, Any]) -> str:
    raw = _canonical_json_bytes(value)
    (case.directory / SUMMARY_NAME).write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _rewrite_artifact(case: BundleCase, filename: str, raw: bytes) -> str:
    (case.directory / filename).write_bytes(raw)
    summary = _summary_document(case)
    artifact = next(item for item in summary["artifacts"] if item["filename"] == filename)
    artifact["bytes"] = len(raw)
    artifact["sha256"] = hashlib.sha256(raw).hexdigest()
    return _write_summary(case, summary)


def _catalog_values(case: BundleCase) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (case.directory / CATALOG_NAME).read_bytes().splitlines()]


def _rewrite_catalog(case: BundleCase, values: list[dict[str, Any]]) -> str:
    return _rewrite_artifact(
        case,
        CATALOG_NAME,
        b"".join(_canonical_json_bytes(value) + b"\n" for value in values),
    )


def _assert_error(
    case: BundleCase,
    monkeypatch: pytest.MonkeyPatch,
    expected: str,
    *,
    trust_root: str | None = None,
    backend: PortableBackend | None = None,
) -> PortableBackend:
    selected = _install_backend(monkeypatch, backend)
    with pytest.raises(generation_bundle.GenerationBundleError) as captured:
        with generation_bundle.open_reconciled_generation(
            case.directory,
            case.summary_sha256 if trust_root is None else trust_root,
        ):
            pass
    assert str(captured.value) == expected
    return selected


def test_public_api_round_trip_keeps_handles_pinned_and_returns_provisional_generation(
    bundle_case: BundleCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _install_backend(monkeypatch)

    with generation_bundle.open_reconciled_generation(
        bundle_case.directory,
        bundle_case.summary_sha256,
    ) as verified:
        assert type(verified) is generation_bundle.VerifiedReconciledGenerationV1
        assert verified.summary_sha256 == bundle_case.summary_sha256
        assert verified.generation == bundle_case.generation
        assert verified.generation.records == bundle_case.records
        assert backend.verify_calls == 2
        assert backend.handles and all(not handle.closed for handle in backend.handles)
        assert "Synthetic Product" not in repr(verified)

    assert backend.exit_calls == 1
    assert all(handle.closed for handle in backend.handles)
    assert generation_bundle.__all__ == (
        "GenerationBundleError",
        "VerifiedReconciledGenerationV1",
        "open_reconciled_generation",
    )


def test_status_accounting_and_capabilities_remain_provisional_or_unsupported(
    bundle_case: BundleCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_backend(monkeypatch)
    with generation_bundle.open_reconciled_generation(
        bundle_case.directory,
        bundle_case.summary_sha256,
    ) as verified:
        manifest = verified.generation.dataset_manifest
        assert dict(manifest.source_product_status_counts) == {
            "ACTIVE": 1,
            "ARCHIVED": 1,
            "DRAFT": 1,
            "UNLISTED": 0,
        }
        states = (
            *manifest.capability_matrix.features,
            *manifest.capability_matrix.requests,
        )
        assert states
        assert all(state is not runtime.CapabilityState.VERIFIED for _name, state in states)
        assert {state for _name, state in states} == {
            runtime.CapabilityState.PROVISIONAL,
            runtime.CapabilityState.UNSUPPORTED,
        }


def test_duplicate_secondary_id_is_legitimate_when_each_pair_is_present_and_equal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = (
        _product("1", source_id="7"),
        _product(
            "2",
            family=ProductFamily.SEALED,
            status=runtime.ProductStatus.DRAFT,
            published=False,
            source_id="7",
        ),
    )
    case = _write_bundle(tmp_path / "duplicate-secondary", records)
    _install_backend(monkeypatch)

    with generation_bundle.open_reconciled_generation(
        case.directory,
        case.summary_sha256,
    ) as verified:
        assert [record.powertools_source_id for record in verified.generation.records] == ["7", "7"]
        assert [record.sync_source_id for record in verified.generation.records] == ["7", "7"]
        assert verified.generation.source_manifest.source_identity_product_count == 2


def test_external_trust_root_is_required_and_mismatch_closes_every_handle(
    bundle_case: BundleCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _assert_error(
        bundle_case,
        monkeypatch,
        TRUST_ERROR,
        trust_root="0" * 64,
    )
    assert backend.handles and all(handle.closed for handle in backend.handles)

    backend = PortableBackend()
    _install_backend(monkeypatch, backend)
    with pytest.raises(generation_bundle.GenerationBundleError, match=f"^{TRUST_ERROR}$"):
        with generation_bundle.open_reconciled_generation(
            bundle_case.directory,
            bundle_case.summary_sha256.upper(),
        ):
            pass
    assert backend.handles == []


@pytest.mark.parametrize("change", ["missing", "extra"])
def test_directory_shape_must_be_exact(
    bundle_case: BundleCase,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    if change == "missing":
        (bundle_case.directory / "taxonomy-report.v1.json").unlink()
    else:
        (bundle_case.directory / "unexpected.json").write_bytes(b"{}")

    _assert_error(bundle_case, monkeypatch, SHAPE_ERROR)


@pytest.mark.parametrize("change", ["top-level-key", "artifact-key", "artifact-order"])
def test_summary_and_artifact_shape_are_exact(
    bundle_case: BundleCase,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    summary = _summary_document(bundle_case)
    if change == "top-level-key":
        summary["unexpected"] = False
    elif change == "artifact-key":
        summary["artifacts"][0]["unexpected"] = False
    else:
        summary["artifacts"].reverse()
    trust_root = _write_summary(bundle_case, summary)

    _assert_error(bundle_case, monkeypatch, CONTENT_ERROR, trust_root=trust_root)


@pytest.mark.parametrize("encoding", ["pretty", "duplicate-key", "bom", "float"])
def test_summary_requires_strict_canonical_json(
    bundle_case: BundleCase,
    monkeypatch: pytest.MonkeyPatch,
    encoding: str,
) -> None:
    path = bundle_case.directory / SUMMARY_NAME
    canonical = path.read_bytes()
    if encoding == "pretty":
        raw = json.dumps(json.loads(canonical), indent=2, sort_keys=True).encode()
    elif encoding == "duplicate-key":
        raw = b'{"status":"reconciled-provisional",' + canonical[1:]
    elif encoding == "bom":
        raw = b"\xef\xbb\xbf" + canonical
    else:
        raw = canonical.replace(b'"catalogRecordCount":3', b'"catalogRecordCount":3.0')
    path.write_bytes(raw)
    trust_root = hashlib.sha256(raw).hexdigest()

    _assert_error(bundle_case, monkeypatch, CONTENT_ERROR, trust_root=trust_root)


def test_summary_size_limit_is_enforced_before_parsing(
    bundle_case: BundleCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = b"{" + b" " * generation_bundle.MAX_SUMMARY_BYTES + b"}"
    (bundle_case.directory / SUMMARY_NAME).write_bytes(raw)

    _assert_error(
        bundle_case,
        monkeypatch,
        CONTENT_ERROR,
        trust_root=hashlib.sha256(raw).hexdigest(),
    )


def test_static_artifacts_must_be_canonical_json(
    bundle_case: BundleCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    filename = "dataset-manifest.v1.json"
    value = json.loads((bundle_case.directory / filename).read_bytes())
    raw = json.dumps(value, indent=2, sort_keys=True).encode()
    trust_root = _rewrite_artifact(bundle_case, filename, raw)

    _assert_error(bundle_case, monkeypatch, CONTENT_ERROR, trust_root=trust_root)


@pytest.mark.parametrize("framing", ["noncanonical", "crlf", "missing-final-lf"])
def test_catalog_jsonl_requires_canonical_records_and_exact_lf_framing(
    bundle_case: BundleCase,
    monkeypatch: pytest.MonkeyPatch,
    framing: str,
) -> None:
    path = bundle_case.directory / CATALOG_NAME
    raw = path.read_bytes()
    if framing == "noncanonical":
        first, remainder = raw.split(b"\n", 1)
        raw = json.dumps(json.loads(first), sort_keys=True).encode() + b"\n" + remainder
    elif framing == "crlf":
        raw = raw.replace(b"\n", b"\r\n")
    else:
        raw = raw[:-1]
    trust_root = _rewrite_artifact(bundle_case, CATALOG_NAME, raw)

    _assert_error(bundle_case, monkeypatch, CONTENT_ERROR, trust_root=trust_root)


def test_catalog_record_byte_limit_is_enforced_streamingly(
    bundle_case: BundleCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = b'{"padding":"' + b"a" * generation_bundle.runtime.MAX_CONTRACT_BYTES + b'"}\n'
    trust_root = _rewrite_artifact(bundle_case, CATALOG_NAME, raw)

    _assert_error(bundle_case, monkeypatch, CONTENT_ERROR, trust_root=trust_root)


@pytest.mark.parametrize("link", ["dataset", "terminal-audit", "source", "taxonomy"])
def test_all_derived_artifact_cross_links_are_rebuilt_and_checked(
    bundle_case: BundleCase,
    monkeypatch: pytest.MonkeyPatch,
    link: str,
) -> None:
    if link in {"dataset", "terminal-audit"}:
        summary = _summary_document(bundle_case)
        if link == "dataset":
            summary["datasetGeneration"] = "sha256:" + "0" * 64
        else:
            summary["terminalQueryAudits"][0]["approvedQuerySha256"] = "0" * 64
        trust_root = _write_summary(bundle_case, summary)
    elif link == "source":
        filename = "source-manifest.v2.json"
        value = json.loads((bundle_case.directory / filename).read_bytes())
        value["sourceIdentityProductCount"] -= 1
        trust_root = _rewrite_artifact(bundle_case, filename, _canonical_json_bytes(value))
    else:
        filename = "taxonomy-report.v1.json"
        value = json.loads((bundle_case.directory / filename).read_bytes())
        value["total"] -= 1
        trust_root = _rewrite_artifact(bundle_case, filename, _canonical_json_bytes(value))

    _assert_error(bundle_case, monkeypatch, CONTENT_ERROR, trust_root=trust_root)


@pytest.mark.parametrize(
    "collision",
    ["product-order", "product-gid", "handle", "variant-gid", "inventory-item-gid"],
)
def test_global_order_and_primary_identity_uniqueness_are_enforced(
    bundle_case: BundleCase,
    monkeypatch: pytest.MonkeyPatch,
    collision: str,
) -> None:
    values = _catalog_values(bundle_case)
    if collision == "product-order":
        values.reverse()
    elif collision == "product-gid":
        values[1]["productGid"] = values[0]["productGid"]
        values[1]["variants"][0]["productGid"] = values[0]["productGid"]
    elif collision == "handle":
        values[1]["handle"] = values[0]["handle"]
    elif collision == "variant-gid":
        values[1]["variants"][0]["variantGid"] = values[0]["variants"][0]["variantGid"]
    else:
        values[1]["variants"][0]["inventoryItemGid"] = values[0]["variants"][0]["inventoryItemGid"]
    trust_root = _rewrite_catalog(bundle_case, values)

    _assert_error(bundle_case, monkeypatch, CONTENT_ERROR, trust_root=trust_root)


def test_secondary_ids_must_remain_a_present_and_equal_pair(
    bundle_case: BundleCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = _catalog_values(bundle_case)
    values[1]["syncSourceId"] = "999"
    trust_root = _rewrite_catalog(bundle_case, values)

    _assert_error(bundle_case, monkeypatch, CONTENT_ERROR, trust_root=trust_root)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", "reconciled-complete"),
        ("datasetActivation", "performed"),
        ("capabilityPromotion", "performed"),
    ],
)
def test_summary_cannot_claim_activation_or_promotion(
    bundle_case: BundleCase,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: str,
) -> None:
    summary = _summary_document(bundle_case)
    summary[field] = value
    trust_root = _write_summary(bundle_case, summary)

    _assert_error(bundle_case, monkeypatch, CONTENT_ERROR, trust_root=trust_root)


def test_verified_capability_claim_is_rejected(
    bundle_case: BundleCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    filename = "dataset-manifest.v1.json"
    value = json.loads((bundle_case.directory / filename).read_bytes())
    value["capabilityMatrix"]["features"]["catalogItem"] = "verified"
    trust_root = _rewrite_artifact(bundle_case, filename, _canonical_json_bytes(value))

    _assert_error(bundle_case, monkeypatch, CONTENT_ERROR, trust_root=trust_root)


def test_final_revalidation_detects_mutation_after_both_content_passes(
    bundle_case: BundleCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def mutate_on_final(
        call: int,
        pinned: generation_bundle._PinnedBundle,
    ) -> None:
        if call == 2:
            handle = pinned.files[CATALOG_NAME].handle
            handle.seek(0, os.SEEK_END)
            handle.write(b"x")
            handle.flush()

    backend = PortableBackend(verify_hook=mutate_on_final)
    selected = _assert_error(bundle_case, monkeypatch, CHANGED_ERROR, backend=backend)
    assert selected.verify_calls == 2
    assert all(handle.closed for handle in selected.handles)


@pytest.mark.parametrize(
    ("boundary", "message"),
    [("identity", CHANGED_ERROR), ("alternate-stream", FILESYSTEM_ERROR)],
)
def test_backend_identity_and_stream_rejections_remain_fail_closed_and_value_free(
    bundle_case: BundleCase,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
    message: str,
) -> None:
    def reject(_call: int, _bundle: generation_bundle._PinnedBundle) -> None:
        raise generation_bundle.GenerationBundleError(message)

    backend = PortableBackend(verify_hook=reject)
    selected = _assert_error(bundle_case, monkeypatch, message, backend=backend)
    assert all(handle.closed for handle in selected.handles)


def test_stream_read_failure_is_bounded_and_closes_all_handles(
    bundle_case: BundleCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = PortableBackend(
        fault_filename=CATALOG_NAME,
        fault_method="readline",
        fault_exception=OSError("sensitive stream failure"),
    )
    selected = _assert_error(bundle_case, monkeypatch, FILESYSTEM_ERROR, backend=backend)
    assert all(handle.closed for handle in selected.handles)


def test_non_binary_stream_chunk_is_rejected_without_leaking_values(
    bundle_case: BundleCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = PortableBackend(
        fault_filename=CATALOG_NAME,
        fault_method="read",
    )
    selected = _assert_error(bundle_case, monkeypatch, CONTENT_ERROR, backend=backend)
    assert all(handle.closed for handle in selected.handles)


def test_handles_close_when_context_body_raises(
    bundle_case: BundleCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _install_backend(monkeypatch)

    with pytest.raises(LookupError, match="caller failure"):
        with generation_bundle.open_reconciled_generation(
            bundle_case.directory,
            bundle_case.summary_sha256,
        ):
            raise LookupError("caller failure")

    assert backend.exit_calls == 1
    assert all(handle.closed for handle in backend.handles)


def test_close_failure_is_mapped_after_handles_are_closed(
    bundle_case: BundleCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = PortableBackend(close_exception=RuntimeError("sensitive close failure"))
    selected = _assert_error(bundle_case, monkeypatch, FILESYSTEM_ERROR, backend=backend)
    assert all(handle.closed for handle in selected.handles)


@pytest.mark.skipif(os.name != "nt", reason="requires the real Win32 handle boundary")
def test_native_win32_fixed_ntfs_backend_round_trip_and_close(
    bundle_case: BundleCase,
) -> None:
    with generation_bundle.open_reconciled_generation(
        bundle_case.directory,
        bundle_case.summary_sha256,
    ) as verified:
        assert verified.generation.records == bundle_case.records
        carrier = bundle_case.directory / CATALOG_NAME
        with pytest.raises(OSError):
            carrier.open("r+b")
        with pytest.raises(OSError):
            carrier.unlink()

    for path in bundle_case.directory.iterdir():
        with path.open("r+b") as handle:
            assert handle.read(1)


def test_public_api_fails_closed_when_native_handle_api_is_unavailable(
    bundle_case: BundleCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(generation_bundle, "_WINDOWS_HANDLE_API_AVAILABLE", False)

    with pytest.raises(generation_bundle.GenerationBundleError) as captured:
        with generation_bundle.open_reconciled_generation(
            bundle_case.directory,
            bundle_case.summary_sha256,
        ):
            pass

    assert str(captured.value) == FILESYSTEM_ERROR


@pytest.mark.parametrize("phase", ["open", "verify"])
def test_unexpected_failures_are_fixed_and_value_free(
    bundle_case: BundleCase,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    sensitive_value = "sensitive-shop-and-record-value"
    if phase == "open":
        backend = PortableBackend(open_exception=RuntimeError(sensitive_value))
        expected = FILESYSTEM_ERROR
    else:

        def reject(_call: int, _bundle: generation_bundle._PinnedBundle) -> None:
            raise RuntimeError(sensitive_value)

        backend = PortableBackend(verify_hook=reject)
        expected = CONTENT_ERROR
    _install_backend(monkeypatch, backend)

    with pytest.raises(generation_bundle.GenerationBundleError) as captured:
        with generation_bundle.open_reconciled_generation(
            bundle_case.directory,
            bundle_case.summary_sha256,
        ):
            pass

    rendered = f"{captured.value!s} {captured.value!r}"
    assert str(captured.value) == expected
    assert sensitive_value not in rendered
    assert SHOP not in rendered
    assert os.fspath(bundle_case.directory) not in rendered
    assert captured.value.__cause__ is None
    assert all(handle.closed for handle in backend.handles)


def test_verified_wrapper_rejects_wrong_types_and_invalid_digest(bundle_case: BundleCase) -> None:
    with pytest.raises(generation_bundle.GenerationBundleError, match=f"^{CONTENT_ERROR}$"):
        generation_bundle.VerifiedReconciledGenerationV1(  # type: ignore[arg-type]
            generation=object(),
            summary_sha256=bundle_case.summary_sha256,
        )
    with pytest.raises(generation_bundle.GenerationBundleError, match=f"^{TRUST_ERROR}$"):
        generation_bundle.VerifiedReconciledGenerationV1(
            generation=bundle_case.generation,
            summary_sha256="invalid",
        )


@pytest.mark.parametrize(
    "value",
    [set(), {"surrogate": "\ud800"}],
    ids=["not-json-serializable", "non-utf8-surrogate"],
)
def test_canonical_renderer_maps_all_encoding_failures(value: Any) -> None:
    with pytest.raises(generation_bundle.GenerationBundleError, match=f"^{CONTENT_ERROR}$"):
        generation_bundle._canonical_json_bytes(value)


@pytest.mark.parametrize("value", ["1" * 20, str(2**63)])
def test_integer_parser_rejects_oversized_decimal_forms(value: str) -> None:
    with pytest.raises(generation_bundle._StrictJsonError):
        generation_bundle._parse_integer(value)


def test_unicode_tree_rejects_nested_surrogates() -> None:
    with pytest.raises(generation_bundle._StrictJsonError):
        generation_bundle._validate_unicode_tree([{"nested": "\udfff"}])


@pytest.mark.parametrize("value", [False, -1, 2**63])
def test_count_validator_rejects_noncanonical_or_out_of_range_values(value: Any) -> None:
    with pytest.raises(generation_bundle.GenerationBundleError, match=f"^{CONTENT_ERROR}$"):
        generation_bundle._count(value)


@pytest.mark.parametrize(
    ("value", "pattern"),
    [("", None), ("\ud800", None), ("UPPER", generation_bundle._SHA256_PATTERN)],
)
def test_text_validator_rejects_empty_surrogate_and_pattern_mismatch(
    value: Any,
    pattern: Any,
) -> None:
    with pytest.raises(generation_bundle.GenerationBundleError, match=f"^{CONTENT_ERROR}$"):
        generation_bundle._text(value, pattern=pattern)


@pytest.mark.parametrize(
    "invalidity",
    [
        "counts",
        "artifacts-container",
        "artifact-item",
        "record-count",
        "catalog-bytes",
        "static-bytes",
        "audits-container",
        "audit-item",
        "audit-transport",
    ],
)
def test_summary_rejects_every_bounded_shape_and_accounting_branch(
    bundle_case: BundleCase,
    invalidity: str,
) -> None:
    value = _summary_document(bundle_case)
    if invalidity == "counts":
        value["catalogRecordCount"] = generation_bundle.MAX_CATALOG_RECORDS + 1
    elif invalidity == "artifacts-container":
        value["artifacts"] = {}
    elif invalidity == "artifact-item":
        value["artifacts"][0] = "invalid"
    elif invalidity == "record-count":
        value["artifacts"][0]["recordCount"] += 1
    elif invalidity == "catalog-bytes":
        value["artifacts"][0]["bytes"] = generation_bundle.MAX_CATALOG_BYTES + 1
    elif invalidity == "static-bytes":
        value["artifacts"][1]["bytes"] = generation_bundle.MAX_DATASET_MANIFEST_BYTES + 1
    elif invalidity == "audits-container":
        value["terminalQueryAudits"] = {}
    elif invalidity == "audit-item":
        value["terminalQueryAudits"][0] = "invalid"
    else:
        value["terminalQueryAudits"][0]["transport"] = "invalid"

    with pytest.raises(generation_bundle.GenerationBundleError, match=f"^{CONTENT_ERROR}$"):
        generation_bundle._parse_summary(_canonical_json_bytes(value))


def test_canonical_utc_preserves_fractional_microseconds() -> None:
    value = datetime(2026, 9, 5, 10, 0, 0, 123456, tzinfo=UTC)
    assert generation_bundle._canonical_utc(value) == "2026-09-05T10:00:00.123456Z"


def test_timestamp_maps_invalid_values() -> None:
    with pytest.raises(generation_bundle.GenerationBundleError, match=f"^{CONTENT_ERROR}$"):
        generation_bundle._timestamp("not-a-timestamp")


def test_part_manifest_rejects_wrong_part_and_unapproved_query(
    bundle_case: BundleCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    products = bundle_case.generation.source_manifest.parts[0]
    with pytest.raises(generation_bundle.GenerationBundleError, match=f"^{CONTENT_ERROR}$"):
        generation_bundle._parse_part_manifest(
            products.to_json_bytes(),
            reconciliation.SnapshotPart.VARIANTS,
        )

    monkeypatch.setattr(
        generation_bundle,
        "_APPROVED_QUERY_SHA256",
        MappingProxyType(
            {
                reconciliation.SnapshotPart.PRODUCTS: "0" * 64,
                reconciliation.SnapshotPart.VARIANTS: "0" * 64,
            }
        ),
    )
    with pytest.raises(generation_bundle.GenerationBundleError, match=f"^{CONTENT_ERROR}$"):
        generation_bundle._parse_part_manifest(
            products.to_json_bytes(),
            reconciliation.SnapshotPart.PRODUCTS,
        )


@pytest.mark.parametrize(
    "failure",
    [generation_bundle.GenerationBundleError(CONTENT_ERROR), RuntimeError("private value")],
)
def test_part_manifest_maps_dto_failures(
    monkeypatch: pytest.MonkeyPatch,
    failure: BaseException,
) -> None:
    def reject(_cls: Any, _raw: bytes) -> Any:
        raise failure

    monkeypatch.setattr(
        generation_bundle.SnapshotPartManifestV1,
        "from_json_bytes",
        classmethod(reject),
    )
    with pytest.raises(generation_bundle.GenerationBundleError, match=f"^{CONTENT_ERROR}$"):
        generation_bundle._parse_part_manifest(
            b"{}",
            reconciliation.SnapshotPart.PRODUCTS,
        )


def test_part_manifest_rejects_non_round_tripping_dto(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = SimpleNamespace(
        part=reconciliation.SnapshotPart.PRODUCTS,
        query_sha256=generation_bundle._APPROVED_QUERY_SHA256[reconciliation.SnapshotPart.PRODUCTS],
        to_json_bytes=lambda: b"different",
    )
    monkeypatch.setattr(
        generation_bundle.SnapshotPartManifestV1,
        "from_json_bytes",
        classmethod(lambda _cls, _raw: fake),
    )
    with pytest.raises(generation_bundle.GenerationBundleError, match=f"^{CONTENT_ERROR}$"):
        generation_bundle._parse_part_manifest(
            b"{}",
            reconciliation.SnapshotPart.PRODUCTS,
        )


def test_source_status_map_requires_exact_canonical_keys() -> None:
    with pytest.raises(generation_bundle.GenerationBundleError, match=f"^{CONTENT_ERROR}$"):
        generation_bundle._source_count_map({"ACTIVE": 1})


@pytest.mark.parametrize(
    "invalidity",
    ["schema", "common", "operation", "overlap", "fence", "aggregate"],
)
def test_source_manifest_rejects_all_reconciliation_boundaries(
    bundle_case: BundleCase,
    invalidity: str,
) -> None:
    products, variants = bundle_case.generation.source_manifest.parts
    value = bundle_case.generation.source_manifest.as_dict()
    if invalidity == "schema":
        value["schemaVersion"] = 0
    elif invalidity == "common":
        variants = _replace_part_manifest(variants, shop_domain="other.myshopify.com")
        value["parts"] = [products.as_dict(), variants.as_dict()]
    elif invalidity == "operation":
        variants = _replace_part_manifest(variants, operation_id=products.operation_id)
        value["parts"] = [products.as_dict(), variants.as_dict()]
    elif invalidity == "overlap":
        products = _replace_part_manifest(
            products,
            created_at="2026-09-05T00:00:00Z",
            completed_at="2026-09-05T01:00:00Z",
        )
        variants = _replace_part_manifest(
            variants,
            created_at="2026-09-05T02:00:00Z",
            completed_at="2026-09-05T03:00:00Z",
        )
        value["parts"] = [products.as_dict(), variants.as_dict()]
    elif invalidity == "fence":
        products = _replace_part_manifest(
            products,
            created_at="2026-09-05T00:00:00Z",
            completed_at="2026-09-06T00:00:00Z",
        )
        variants = _replace_part_manifest(
            variants,
            created_at="2026-09-05T12:00:00Z",
            completed_at="2026-09-06T12:00:00Z",
        )
        value["parts"] = [products.as_dict(), variants.as_dict()]
    else:
        value["productCount"] += 1

    with pytest.raises(generation_bundle.GenerationBundleError, match=f"^{CONTENT_ERROR}$"):
        generation_bundle._parse_source_manifest(
            _canonical_json_bytes(value),
            products,
            variants,
        )


def test_source_manifest_requires_exact_round_trip(
    bundle_case: BundleCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = bundle_case.generation.source_manifest
    products, variants = source.parts
    raw = source.to_json_bytes()
    monkeypatch.setattr(
        generation_bundle.ReconciledSourceManifestV2,
        "to_json_bytes",
        lambda _self: b"different",
    )
    with pytest.raises(generation_bundle.GenerationBundleError, match=f"^{CONTENT_ERROR}$"):
        generation_bundle._parse_source_manifest(
            raw,
            products,
            variants,
        )


@pytest.mark.parametrize("mode", ["round-trip", "generation-error", "verified-capability"])
def test_dataset_manifest_maps_round_trip_capability_and_dto_failures(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    raw = b"{}"
    if mode == "round-trip":
        fake: Any = SimpleNamespace(
            to_json_bytes=lambda: b"different",
            capability_matrix=SimpleNamespace(features=(), requests=()),
        )
    elif mode == "verified-capability":
        fake = SimpleNamespace(
            to_json_bytes=lambda: raw,
            capability_matrix=SimpleNamespace(
                features=(("catalogItem", runtime.CapabilityState.VERIFIED),),
                requests=(),
            ),
        )
    else:
        fake = None

    def parse(_cls: Any, _raw: bytes) -> Any:
        if mode == "generation-error":
            raise generation_bundle.GenerationBundleError(CONTENT_ERROR)
        return fake

    monkeypatch.setattr(
        generation_bundle.runtime.DatasetManifestV1,
        "from_json_bytes",
        classmethod(parse),
    )
    with pytest.raises(generation_bundle.GenerationBundleError, match=f"^{CONTENT_ERROR}$"):
        generation_bundle._parse_dataset_manifest(raw)


@pytest.mark.parametrize("value", ["invalid", "gid://shopify/Product/12a"])
def test_product_gid_key_rejects_noncanonical_identity(value: str) -> None:
    with pytest.raises(generation_bundle.GenerationBundleError, match=f"^{CONTENT_ERROR}$"):
        generation_bundle._product_gid_key(value)


@pytest.mark.parametrize("failure", ["fstat", "not-regular"])
def test_handle_state_rejects_uninspectable_or_nonregular_handles(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    if failure == "fstat":
        handle = SimpleNamespace(fileno=lambda: (_ for _ in ()).throw(OSError("private")))
    else:
        handle = SimpleNamespace(fileno=lambda: 1)
        monkeypatch.setattr(
            generation_bundle.os,
            "fstat",
            lambda _fd: SimpleNamespace(st_mode=stat.S_IFDIR, st_nlink=1),
        )
    with pytest.raises(generation_bundle.GenerationBundleError, match=f"^{FILESYSTEM_ERROR}$"):
        generation_bundle._handle_state(handle)


def test_pinned_state_detects_changed_metadata(bundle_case: BundleCase) -> None:
    backend = PortableBackend()
    with backend.open(bundle_case.directory) as pinned:
        artifact = pinned.files[SUMMARY_NAME]
        changed = replace(
            artifact,
            state=replace(artifact.state, modified_ns=artifact.state.modified_ns + 1),
        )
        with pytest.raises(generation_bundle.GenerationBundleError, match=f"^{CHANGED_ERROR}$"):
            generation_bundle._require_pinned_state(changed)


@pytest.mark.parametrize("mode", ["io-error", "short-read"])
def test_full_file_scan_maps_io_and_short_read_failures(
    bundle_case: BundleCase,
    mode: str,
) -> None:
    backend = PortableBackend()
    with backend.open(bundle_case.directory) as pinned:
        artifact = pinned.files[SUMMARY_NAME]
        response: Any = OSError("private") if mode == "io-error" else b""
        scripted = _ScriptedHandle(artifact.handle, reads=[response])
        candidate = replace(artifact, handle=scripted)
        expected = FILESYSTEM_ERROR if mode == "io-error" else CHANGED_ERROR
        with pytest.raises(generation_bundle.GenerationBundleError, match=f"^{expected}$"):
            generation_bundle._scan_pinned_file(candidate)


@pytest.mark.parametrize("mode", ["short-read", "trailing-byte", "io-error"])
def test_bounded_reader_rejects_short_trailing_and_io_streams(
    bundle_case: BundleCase,
    mode: str,
) -> None:
    backend = PortableBackend()
    with backend.open(bundle_case.directory) as pinned:
        artifact = pinned.files[SUMMARY_NAME]
        if mode == "short-read":
            reads: list[Any] = [b""]
            expected = CHANGED_ERROR
        elif mode == "trailing-byte":
            reads = [(bundle_case.directory / SUMMARY_NAME).read_bytes(), b"x"]
            expected = CHANGED_ERROR
        else:
            reads = [OSError("private")]
            expected = FILESYSTEM_ERROR
        candidate = replace(artifact, handle=_ScriptedHandle(artifact.handle, reads=reads))
        with pytest.raises(generation_bundle.GenerationBundleError, match=f"^{expected}$"):
            generation_bundle._read_bounded_file(
                candidate,
                maximum=generation_bundle.MAX_SUMMARY_BYTES,
            )


@pytest.mark.parametrize(
    "mode",
    [
        "contract-size",
        "nonbinary-line",
        "empty-record",
        "variant-shape",
        "dto-round-trip",
        "global-variant-limit",
        "global-record-limit",
        "final-scan",
    ],
)
def test_streaming_catalog_reader_covers_every_fail_closed_gate(
    bundle_case: BundleCase,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    summary = generation_bundle._parse_summary((bundle_case.directory / SUMMARY_NAME).read_bytes())
    contract = summary.artifacts_by_name[CATALOG_NAME]
    backend = PortableBackend()
    with backend.open(bundle_case.directory) as pinned:
        artifact = pinned.files[CATALOG_NAME]
        candidate = artifact
        expected_variants = summary.variant_count
        if mode == "contract-size":
            contract = replace(contract, byte_count=contract.byte_count + 1)
        elif mode == "nonbinary-line":
            candidate = replace(
                artifact,
                handle=_ScriptedHandle(artifact.handle, lines=["not-binary"]),
            )
        elif mode == "empty-record":
            candidate = replace(
                artifact,
                handle=_ScriptedHandle(artifact.handle, lines=[b"\n"]),
            )
        elif mode == "variant-shape":
            candidate = replace(
                artifact,
                handle=_ScriptedHandle(artifact.handle, lines=[b'{"variants":null}\n']),
            )
        elif mode == "dto-round-trip":
            first_line = (
                (bundle_case.directory / CATALOG_NAME).read_bytes().splitlines(keepends=True)[0]
            )
            fake = SimpleNamespace(to_json_bytes=lambda: b"different")
            monkeypatch.setattr(
                generation_bundle.runtime.CatalogProductRecordV1,
                "from_dict",
                classmethod(lambda _cls, _value: fake),
            )
            candidate = replace(
                artifact,
                handle=_ScriptedHandle(artifact.handle, lines=[first_line]),
            )
        elif mode in {"global-variant-limit", "global-record-limit"}:
            first_line = (
                (bundle_case.directory / CATALOG_NAME).read_bytes().splitlines(keepends=True)[0]
            )

            def lower_limit() -> bytes:
                if mode == "global-variant-limit":
                    monkeypatch.setattr(generation_bundle, "MAX_CATALOG_VARIANTS", 0)
                else:
                    monkeypatch.setattr(generation_bundle, "MAX_CATALOG_RECORDS", 0)
                return first_line

            candidate = replace(
                artifact,
                handle=_ScriptedHandle(artifact.handle, lines=[lower_limit]),
            )
        else:
            contract = replace(contract, sha256="0" * 64)

        with pytest.raises(generation_bundle.GenerationBundleError, match=f"^{CONTENT_ERROR}$"):
            generation_bundle._read_catalog_records(
                candidate,
                contract,
                expected_variant_count=expected_variants,
            )


def test_scan_contract_and_artifact_lookup_reject_mismatches(bundle_case: BundleCase) -> None:
    summary = generation_bundle._parse_summary((bundle_case.directory / SUMMARY_NAME).read_bytes())
    contract = summary.artifacts_by_name[CATALOG_NAME]
    with pytest.raises(generation_bundle.GenerationBundleError, match=f"^{CONTENT_ERROR}$"):
        generation_bundle._require_scan(
            generation_bundle._FileScan("0" * 64, contract.byte_count),
            contract,
        )

    backend = PortableBackend()
    with backend.open(bundle_case.directory) as pinned:
        missing = replace(pinned, files=MappingProxyType({}))
        with pytest.raises(generation_bundle.GenerationBundleError, match=f"^{SHAPE_ERROR}$"):
            generation_bundle._artifact(missing, SUMMARY_NAME)
        wrong = replace(
            pinned,
            files=MappingProxyType({SUMMARY_NAME: object()}),
        )
        with pytest.raises(generation_bundle.GenerationBundleError, match=f"^{SHAPE_ERROR}$"):
            generation_bundle._artifact(wrong, SUMMARY_NAME)


@pytest.mark.parametrize(
    "mode",
    ["shape", "artifact-size", "summary-race", "static-race", "catalog-race"],
)
def test_prepare_detects_shape_size_and_each_two_pass_race(
    bundle_case: BundleCase,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    backend = PortableBackend()
    with backend.open(bundle_case.directory) as pinned:
        candidate = pinned
        verifier = SimpleNamespace(verify=lambda _bundle: None)
        if mode == "shape":
            candidate = replace(pinned, files=MappingProxyType({}))
            expected = SHAPE_ERROR
        elif mode == "artifact-size":
            files_by_name = dict(pinned.files)
            artifact = files_by_name[CATALOG_NAME]
            files_by_name[CATALOG_NAME] = replace(
                artifact,
                state=replace(artifact.state, byte_count=artifact.state.byte_count + 1),
            )
            candidate = replace(pinned, files=MappingProxyType(files_by_name))
            expected = CONTENT_ERROR
        elif mode == "summary-race":
            original = generation_bundle._read_bounded_file
            summary_reads = 0

            def changed_summary(
                artifact: generation_bundle._PinnedArtifact,
                *,
                maximum: int,
            ) -> tuple[bytes, generation_bundle._FileScan]:
                nonlocal summary_reads
                raw, scan = original(artifact, maximum=maximum)
                if artifact.filename == SUMMARY_NAME:
                    summary_reads += 1
                    if summary_reads == 2:
                        raw = b"x" + raw[1:]
                return raw, scan

            monkeypatch.setattr(generation_bundle, "_read_bounded_file", changed_summary)
            expected = CHANGED_ERROR
        elif mode == "static-race":
            original = generation_bundle._read_bounded_file

            def changed_static(
                artifact: generation_bundle._PinnedArtifact,
                *,
                maximum: int,
            ) -> tuple[bytes, generation_bundle._FileScan]:
                raw, scan = original(artifact, maximum=maximum)
                if artifact.filename == "dataset-manifest.v1.json":
                    scan = replace(scan, sha256="0" * 64)
                return raw, scan

            monkeypatch.setattr(generation_bundle, "_read_bounded_file", changed_static)
            monkeypatch.setattr(generation_bundle, "_require_scan", lambda *_args: None)
            expected = CHANGED_ERROR
        else:
            original_catalog = generation_bundle._read_catalog_records

            def changed_catalog(*args: Any, **kwargs: Any) -> Any:
                records, scan = original_catalog(*args, **kwargs)
                return records, replace(scan, sha256="0" * 64)

            monkeypatch.setattr(
                generation_bundle,
                "_read_catalog_records",
                changed_catalog,
            )
            expected = CHANGED_ERROR

        with pytest.raises(generation_bundle.GenerationBundleError, match=f"^{expected}$"):
            generation_bundle._prepare_verified_generation(
                candidate,
                bundle_case.summary_sha256,
                verifier,
            )


def test_owned_native_handle_guard_rejects_missing_ownership() -> None:
    owner = generation_bundle._OwnedNativeHandle()
    with pytest.raises(generation_bundle.GenerationBundleError, match=f"^{FILESYSTEM_ERROR}$"):
        _ = owner.handle


@pytest.mark.parametrize(
    "mode", ["kernel-disabled", "kernel-load", "msvcrt-disabled", "msvcrt-import"]
)
def test_windows_runtime_loaders_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    if mode.endswith("disabled"):
        monkeypatch.setattr(generation_bundle, "_WINDOWS_HANDLE_API_AVAILABLE", False)
    else:
        monkeypatch.setattr(generation_bundle, "_WINDOWS_HANDLE_API_AVAILABLE", True)
    if mode == "kernel-load":
        monkeypatch.setattr(
            generation_bundle.ctypes,
            "WinDLL",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("private")),
        )
    if mode == "msvcrt-import":
        original_import = builtins.__import__

        def blocked_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "msvcrt":
                raise ImportError("private")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", blocked_import)

    target = (
        generation_bundle._windows_kernel32
        if mode.startswith("kernel")
        else generation_bundle._windows_msvcrt
    )
    with pytest.raises(generation_bundle.GenerationBundleError, match=f"^{FILESYSTEM_ERROR}$"):
        target()


@pytest.mark.parametrize("operation", ["create", "close"])
def test_native_create_and_close_map_invalid_win32_results(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    operation: str,
) -> None:
    if operation == "create":
        kernel = SimpleNamespace(
            CreateFileW=_WinFunction(lambda *_args: generation_bundle._INVALID_NATIVE_HANDLE)
        )
        monkeypatch.setattr(generation_bundle, "_windows_kernel32", lambda: kernel)
    else:
        kernel = SimpleNamespace(CloseHandle=_WinFunction(lambda _handle: False))
        monkeypatch.setattr(generation_bundle, "_windows_kernel32", lambda: kernel)
    with pytest.raises(generation_bundle.GenerationBundleError, match=f"^{FILESYSTEM_ERROR}$"):
        if operation == "create":
            generation_bundle._native_create_file(
                tmp_path,
                access=1,
                share=2,
                flags=3,
            )
        else:
            generation_bundle._native_close(71)


def test_native_create_file_post_call_interrupt_closes_the_raw_handle_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    closed: list[int] = []
    kernel = SimpleNamespace(CreateFileW=_WinFunction(lambda *_args: 71))
    monkeypatch.setattr(generation_bundle, "_windows_kernel32", lambda: kernel)
    monkeypatch.setattr(generation_bundle, "_native_close", closed.append)

    with _interrupt_on_line(
        generation_bundle._native_create_file,
        "if owner.raw_handle == _INVALID_NATIVE_HANDLE:",
        KeyboardInterrupt("post-CreateFile line event"),
    ):
        with pytest.raises(KeyboardInterrupt, match="post-CreateFile line event"):
            generation_bundle._native_create_file(
                tmp_path / "carrier.bin",
                access=1,
                share=2,
                flags=3,
            )

    assert closed == [71]


@pytest.mark.parametrize("retry_fails", [False, True])
def test_owned_native_handle_close_retries_once_after_baseexception(
    monkeypatch: pytest.MonkeyPatch,
    retry_fails: bool,
) -> None:
    first = KeyboardInterrupt("first close")
    second = SystemExit("retry close")
    calls: list[int] = []

    def close(raw_handle: int) -> None:
        calls.append(raw_handle)
        if len(calls) == 1:
            raise first
        if retry_fails:
            raise second

    monkeypatch.setattr(generation_bundle, "_native_close", close)
    owner = generation_bundle._OwnedNativeHandle(71)
    with pytest.raises(BaseException) as captured:
        owner.close()

    assert captured.value is (second if retry_fails else first)
    assert calls == [71, 71]
    assert owner.raw_handle == (71 if retry_fails else None)


def test_owned_native_handle_preserves_failure_when_callee_consumes_ownership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = generation_bundle._OwnedNativeHandle(71)
    failure = KeyboardInterrupt("close consumed ownership")

    def close(_raw_handle: int) -> None:
        owner.raw_handle = None
        raise failure

    monkeypatch.setattr(generation_bundle, "_native_close", close)
    with pytest.raises(KeyboardInterrupt) as captured:
        owner.close()

    assert captured.value is failure
    assert owner.raw_handle is None


@pytest.mark.parametrize("kind", ["handle", "descriptor"])
@pytest.mark.parametrize("retry_fails", [False, True])
def test_owned_native_binary_close_retries_once_after_baseexception(
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    retry_fails: bool,
) -> None:
    first = KeyboardInterrupt("first close")
    second = SystemExit("retry close")
    calls = 0

    def close() -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise first
        if retry_fails:
            raise second

    if kind == "handle":
        resources = generation_bundle._OwnedNativeBinary(handle=SimpleNamespace(close=close))
    else:
        resources = generation_bundle._OwnedNativeBinary(descriptor=81)
        monkeypatch.setattr(generation_bundle.os, "close", lambda _descriptor: close())

    with pytest.raises(BaseException) as captured:
        resources.close()

    assert captured.value is (second if retry_fails else first)
    assert calls == 2
    expected_remaining = retry_fails
    assert (resources.handle is not None or resources.descriptor is not None) is expected_remaining


def test_owned_native_binary_preserves_failure_when_callee_consumes_ownership() -> None:
    resources = generation_bundle._OwnedNativeBinary()
    failure = KeyboardInterrupt("close consumed ownership")

    def close() -> None:
        resources.handle = None
        raise failure

    resources.handle = SimpleNamespace(close=close)
    with pytest.raises(KeyboardInterrupt) as captured:
        resources.close()

    assert captured.value is failure
    assert resources.handle is None
    assert resources.descriptor is None


@pytest.mark.parametrize(
    "mode",
    [
        "ordinary-before-descriptor",
        "base-before-descriptor",
        "ordinary-after-descriptor",
        "base-close-failure",
        "missing-result",
    ],
)
def test_native_binary_file_closes_owned_resources_for_every_exit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mode: str,
) -> None:
    closed_handles: list[int] = []
    real_close = os.close
    monkeypatch.setattr(generation_bundle, "_native_create_file", lambda *_args, **_kwargs: 71)
    monkeypatch.setattr(generation_bundle, "_native_close", closed_handles.append)
    descriptor = os.open(tmp_path / "descriptor.bin", os.O_CREAT | os.O_RDWR)

    if mode in {"ordinary-before-descriptor", "base-before-descriptor"}:
        failure: BaseException = (
            ValueError("private")
            if mode == "ordinary-before-descriptor"
            else KeyboardInterrupt("private")
        )
        msvcrt = SimpleNamespace(open_osfhandle=lambda *_args: (_ for _ in ()).throw(failure))
    else:
        msvcrt = SimpleNamespace(open_osfhandle=lambda *_args: descriptor)
    monkeypatch.setattr(generation_bundle, "_windows_msvcrt", lambda: msvcrt)

    if mode in {"ordinary-after-descriptor", "base-close-failure"}:
        monkeypatch.setattr(
            generation_bundle.os,
            "fdopen",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("private")),
        )
    elif mode == "missing-result":
        monkeypatch.setattr(generation_bundle.os, "fdopen", lambda *_args, **_kwargs: None)
    if mode == "base-close-failure":
        monkeypatch.setattr(
            generation_bundle.os,
            "close",
            lambda _fd: (_ for _ in ()).throw(KeyboardInterrupt("close")),
        )

    expected_exception: type[BaseException] = (
        KeyboardInterrupt
        if mode in {"base-before-descriptor", "base-close-failure"}
        else generation_bundle.GenerationBundleError
    )
    try:
        with pytest.raises(expected_exception):
            generation_bundle._native_binary_file(tmp_path / "carrier.bin")
    finally:
        if mode in {"ordinary-before-descriptor", "base-before-descriptor"}:
            real_close(descriptor)
        elif mode == "base-close-failure":
            real_close(descriptor)

    if mode in {"ordinary-before-descriptor", "base-before-descriptor"}:
        assert closed_handles == [71]
    else:
        assert closed_handles == []


@pytest.mark.parametrize(
    ("target_fragment", "expected_fd_closes", "expected_file_closes"),
    [
        ("resources.handle, resources.descriptor =", [81], 0),
        ("return resources.release()", [], 1),
    ],
)
def test_native_binary_file_line_interrupt_has_exactly_one_owner_close(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    target_fragment: str,
    expected_fd_closes: list[int],
    expected_file_closes: int,
) -> None:
    native_closes: list[int] = []
    descriptor_closes: list[int] = []
    file_closes = 0

    class FakeFile:
        def close(self) -> None:
            nonlocal file_closes
            file_closes += 1

    monkeypatch.setattr(generation_bundle, "_native_create_file", lambda *_args, **_kwargs: 71)
    monkeypatch.setattr(generation_bundle, "_native_close", native_closes.append)
    monkeypatch.setattr(
        generation_bundle,
        "_windows_msvcrt",
        lambda: SimpleNamespace(open_osfhandle=lambda *_args: 81),
    )
    monkeypatch.setattr(generation_bundle.os, "fdopen", lambda *_args, **_kwargs: FakeFile())
    monkeypatch.setattr(generation_bundle.os, "close", descriptor_closes.append)

    with _interrupt_on_line(
        generation_bundle._native_binary_file,
        target_fragment,
        KeyboardInterrupt("injected line event"),
    ):
        with pytest.raises(KeyboardInterrupt, match=r"^injected line event$"):
            generation_bundle._native_binary_file(tmp_path / "carrier.bin")

    assert native_closes == []
    assert descriptor_closes == expected_fd_closes
    assert file_closes == expected_file_closes
    assert len(native_closes) + len(descriptor_closes) + file_closes == 1


def test_native_os_handle_maps_runtime_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    msvcrt = SimpleNamespace(get_osfhandle=lambda _fd: (_ for _ in ()).throw(OSError("private")))
    monkeypatch.setattr(generation_bundle, "_windows_msvcrt", lambda: msvcrt)
    with (tmp_path / "carrier.bin").open("w+b") as handle:
        with pytest.raises(generation_bundle.GenerationBundleError, match=f"^{FILESYSTEM_ERROR}$"):
            generation_bundle._native_os_handle(handle)


@pytest.mark.parametrize(
    "value",
    [
        "invalid",
        r"\\?\Volume{00000000-0000-0000-0000-000000000000}\bad/name",
        "\\\\?\\Volume{00000000-0000-0000-0000-000000000000}\\bad\x00name",
        r"\\?\Volume{00000000-0000-0000-0000-000000000000}\..",
    ],
)
def test_canonical_handle_path_rejects_invalid_carriers(value: str) -> None:
    with pytest.raises(generation_bundle.GenerationBundleError, match=f"^{FILESYSTEM_ERROR}$"):
        generation_bundle._parse_canonical_handle_path(value)


@pytest.mark.parametrize("result", [0, generation_bundle._VOLUME_NAME_BUFFER_CHARS])
def test_native_handle_path_rejects_failed_or_truncated_result(
    monkeypatch: pytest.MonkeyPatch,
    result: int,
) -> None:
    kernel = SimpleNamespace(GetFinalPathNameByHandleW=_WinFunction(lambda *_args: result))
    monkeypatch.setattr(generation_bundle, "_windows_kernel32", lambda: kernel)
    with pytest.raises(generation_bundle.GenerationBundleError, match=f"^{FILESYSTEM_ERROR}$"):
        generation_bundle._native_handle_canonical_path(71)


@pytest.mark.parametrize(
    "mode",
    [
        "unexpected-error",
        "buffer-growth",
        "buffer-exhaustion",
        "offset-outside-buffer",
        "invalid-name-length",
        "invalid-utf16",
        "invalid-stream-facts",
        "invalid-next-offset",
        "two-entries",
    ],
)
def test_native_stream_parser_covers_all_bounded_layout_branches(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    default = _stream_payload([("::$DATA", 3, 8)])
    expected: tuple[tuple[str, int], ...] | None = None
    if mode == "unexpected-error":
        kernel = _stream_kernel(default, results=[False])
        last_error = 5
    elif mode == "buffer-growth":
        kernel = _stream_kernel(default, results=[False, True])
        last_error = generation_bundle._ERROR_INSUFFICIENT_BUFFER
        expected = (("::$DATA", 3),)
    elif mode == "buffer-exhaustion":
        kernel = _stream_kernel(default, results=[False] * 20)
        last_error = generation_bundle._ERROR_MORE_DATA
    elif mode == "offset-outside-buffer":
        kernel = _stream_kernel(_stream_payload([("a", 1, 1), ("b", 1, 1)], first_next_offset=4096))
        last_error = 0
    elif mode == "invalid-name-length":
        kernel = _stream_kernel(struct.pack("<IIqq", 0, 0, 0, 0))
        last_error = 0
    elif mode == "invalid-utf16":
        kernel = _stream_kernel(_stream_payload([(b"\x00\xd8", 1, 1)]))
        last_error = 0
    elif mode == "invalid-stream-facts":
        kernel = _stream_kernel(_stream_payload([("bad\x00name", 1, 1)]))
        last_error = 0
    elif mode == "invalid-next-offset":
        kernel = _stream_kernel(_stream_payload([("a", 1, 1), ("b", 1, 1)], first_next_offset=25))
        last_error = 0
    else:
        kernel = _stream_kernel(_stream_payload([("a", 1, 8), ("b", 2, 8)]))
        last_error = 0
        expected = (("a", 1), ("b", 2))
    monkeypatch.setattr(generation_bundle, "_windows_kernel32", lambda: kernel)
    monkeypatch.setattr(generation_bundle, "_WIN32_LAST_ERROR", lambda: last_error)

    if expected is None:
        with pytest.raises(
            generation_bundle.GenerationBundleError,
            match=f"^{FILESYSTEM_ERROR}$",
        ):
            generation_bundle._native_file_streams(71)
    else:
        assert generation_bundle._native_file_streams(71) == expected


@pytest.mark.parametrize("kind", ["file", "directory"])
def test_required_stream_shape_rejects_extra_streams(
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    monkeypatch.setattr(
        generation_bundle,
        "_native_file_streams",
        lambda *_args, **_kwargs: (("unexpected", 1),),
    )
    with pytest.raises(generation_bundle.GenerationBundleError, match=f"^{FILESYSTEM_ERROR}$"):
        if kind == "file":
            generation_bundle._require_unnamed_stream(71, 1)
        else:
            generation_bundle._require_no_directory_streams(71)


@pytest.mark.parametrize("mode", ["volume-path", "drive-type", "volume-info", "filesystem"])
def test_local_ntfs_gate_rejects_every_platform_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mode: str,
) -> None:
    def volume_path(_path: str, buffer: Any, _length: int) -> bool:
        buffer.value = "C:\\"
        return mode != "volume-path"

    def volume_info(*args: Any) -> bool:
        args[6].value = "FAT32" if mode == "filesystem" else "NTFS"
        return mode != "volume-info"

    kernel = SimpleNamespace(
        GetVolumePathNameW=_WinFunction(volume_path),
        GetDriveTypeW=_WinFunction(
            lambda _path: 2 if mode == "drive-type" else generation_bundle._DRIVE_FIXED
        ),
        GetVolumeInformationW=_WinFunction(volume_info),
    )
    monkeypatch.setattr(generation_bundle, "_windows_kernel32", lambda: kernel)
    with pytest.raises(generation_bundle.GenerationBundleError, match=f"^{FILESYSTEM_ERROR}$"):
        generation_bundle._require_local_ntfs(tmp_path)


def test_local_ntfs_gate_accepts_fixed_ntfs_volume(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def volume_path(_path: str, buffer: Any, _length: int) -> bool:
        buffer.value = "C:\\"
        return True

    def volume_info(*args: Any) -> bool:
        args[6].value = "NTFS"
        return True

    kernel = SimpleNamespace(
        GetVolumePathNameW=_WinFunction(volume_path),
        GetDriveTypeW=_WinFunction(lambda _path: generation_bundle._DRIVE_FIXED),
        GetVolumeInformationW=_WinFunction(volume_info),
    )
    monkeypatch.setattr(generation_bundle, "_windows_kernel32", lambda: kernel)

    generation_bundle._require_local_ntfs(tmp_path)


@pytest.mark.parametrize("name", ["", "..", "bad/name", "bad:name", "bad. "])
def test_canonical_child_rejects_unsafe_names(name: str) -> None:
    parent = generation_bundle._CanonicalHandlePath("volume", ("parent",))
    with pytest.raises(generation_bundle.GenerationBundleError, match=f"^{FILESYSTEM_ERROR}$"):
        generation_bundle._canonical_child(parent, name)


@pytest.mark.parametrize(
    ("left_component", "right_component"),
    [("Foo", "foo"), ("Straße", "strasse")],
)
def test_canonical_path_attestation_requires_exact_component_spelling(
    left_component: str,
    right_component: str,
) -> None:
    left = generation_bundle._CanonicalHandlePath("volume", (left_component,))
    right = generation_bundle._CanonicalHandlePath("volume", (right_component,))

    assert generation_bundle._canonical_paths_equal(left, right) is False


def test_expected_drive_path_rejects_nonroot_anchor_attestation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        generation_bundle,
        "_native_path_canonical_path",
        lambda *_args, **_kwargs: generation_bundle._CanonicalHandlePath("volume", ("unexpected",)),
    )

    with pytest.raises(generation_bundle.GenerationBundleError, match=f"^{FILESYSTEM_ERROR}$"):
        generation_bundle._expected_canonical_drive_path(Path(r"C:\bundle"))


def test_alias_walk_rejects_path_without_drive_anchor() -> None:
    with pytest.raises(generation_bundle.GenerationBundleError, match=f"^{FILESYSTEM_ERROR}$"):
        generation_bundle._path_has_alias(Path("relative"))


@pytest.mark.parametrize("mode", ["alias", "failure"])
def test_alias_walk_detects_reparse_and_maps_lstat_failure(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    path = Path(r"C:\top\child")

    def lstat(_self: Path) -> Any:
        if mode == "failure":
            raise OSError("private")
        return SimpleNamespace(
            st_file_attributes=generation_bundle._REPARSE_POINT_ATTRIBUTE,
            st_mode=stat.S_IFDIR,
        )

    monkeypatch.setattr(type(path), "lstat", lstat)
    if mode == "alias":
        assert generation_bundle._path_has_alias(path) is True
    else:
        with pytest.raises(generation_bundle.GenerationBundleError, match=f"^{FILESYSTEM_ERROR}$"):
            generation_bundle._path_has_alias(path)


@pytest.mark.parametrize(
    "raw",
    [
        r"\\server\share\bundle",
        r"\\?\C:\bundle",
        r"\\?\Volume{00000000-0000-0000-0000-000000000000}\bundle",
        r"\\?\UNC\server\share\bundle",
        r"\\.\C:\bundle",
        r"\??\C:\bundle",
        r"\rooted-without-drive",
    ],
)
def test_supported_namespace_rejects_unc_device_and_drive_ambiguous_paths(raw: str) -> None:
    with pytest.raises(generation_bundle.GenerationBundleError, match=f"^{FILESYSTEM_ERROR}$"):
        generation_bundle._require_supported_namespace(Path(raw))


@pytest.mark.parametrize("mode", ["wrong-type", "relative", "parent", "unsafe"])
def test_public_directory_argument_requires_concrete_absolute_normalized_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mode: str,
) -> None:
    monkeypatch.setattr(generation_bundle, "_WINDOWS_HANDLE_API_AVAILABLE", False)
    if mode == "wrong-type":
        value: Any = os.fspath(tmp_path)
    elif mode == "relative":
        value = Path("relative")
    elif mode == "parent":
        value = tmp_path / ".." / "escape"
    else:
        value = tmp_path / "unsafe. " / "bundle"
    with pytest.raises(generation_bundle.GenerationBundleError, match=f"^{FILESYSTEM_ERROR}$"):
        generation_bundle._validated_directory_argument(value)


@pytest.mark.parametrize(
    "kind", ["file-missing", "file-nonregular", "dir-missing", "dir-file", "scan"]
)
def test_portable_path_metadata_helpers_map_all_os_failures(
    tmp_path: Path,
    kind: str,
) -> None:
    missing = tmp_path / "missing"
    regular = tmp_path / "regular"
    regular.write_bytes(b"x")
    with pytest.raises(generation_bundle.GenerationBundleError, match=f"^{FILESYSTEM_ERROR}$"):
        if kind == "file-missing":
            generation_bundle._path_file_state(missing)
        elif kind == "file-nonregular":
            generation_bundle._path_file_state(tmp_path)
        elif kind == "dir-missing":
            generation_bundle._directory_identity(missing)
        elif kind == "dir-file":
            generation_bundle._directory_identity(regular)
        else:
            generation_bundle._directory_names(missing)


@pytest.mark.parametrize("mode", ["success", "failure"])
def test_native_handle_identity_reads_full_64_bit_volume_and_128_bit_file_id(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    volume = 2**64 - 1
    file_id = bytes(range(16))
    payload = struct.pack("<Q16s", volume, file_id)

    def get_information(
        _handle: int,
        _kind: int,
        information: Any,
        size: int,
    ) -> bool:
        if mode == "failure":
            return False
        ctypes.memmove(information, payload, min(len(payload), size))
        return True

    kernel = SimpleNamespace(GetFileInformationByHandleEx=_WinFunction(get_information))
    monkeypatch.setattr(generation_bundle, "_windows_kernel32", lambda: kernel)
    if mode == "failure":
        with pytest.raises(
            generation_bundle.GenerationBundleError,
            match=f"^{FILESYSTEM_ERROR}$",
        ):
            generation_bundle._native_handle_identity(71)
    else:
        assert generation_bundle._native_handle_identity(71) == (
            generation_bundle._NativeFileIdentity(volume, file_id)
        )


@pytest.mark.parametrize(
    "mode",
    ["invalid-guid", "remote-volume", "volume-info", "filesystem"],
)
def test_pinned_volume_ntfs_gate_rejects_invalid_or_nonlocal_volume(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    canonical = generation_bundle._CanonicalHandlePath(
        "invalid" if mode == "invalid-guid" else "volume{00000000-0000-0000-0000-000000000000}",
        ("bundle",),
    )

    def volume_info(*args: Any) -> bool:
        args[6].value = "FAT32" if mode == "filesystem" else "NTFS"
        return mode != "volume-info"

    kernel = SimpleNamespace(
        GetDriveTypeW=_WinFunction(
            lambda _path: 2 if mode == "remote-volume" else generation_bundle._DRIVE_FIXED
        ),
        GetVolumeInformationW=_WinFunction(volume_info),
    )
    monkeypatch.setattr(generation_bundle, "_windows_kernel32", lambda: kernel)
    with pytest.raises(generation_bundle.GenerationBundleError, match=f"^{FILESYSTEM_ERROR}$"):
        generation_bundle._require_local_ntfs_volume(canonical)


@pytest.mark.parametrize("mode", ["invalid-anchor", "remote-drive"])
def test_fixed_drive_preflight_rejects_before_any_path_traversal(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    path = Path("relative") if mode == "invalid-anchor" else Path(r"Z:\external\bundle")
    kernel = SimpleNamespace(GetDriveTypeW=_WinFunction(lambda _anchor: 2))
    monkeypatch.setattr(generation_bundle, "_windows_kernel32", lambda: kernel)
    with pytest.raises(generation_bundle.GenerationBundleError, match=f"^{FILESYSTEM_ERROR}$"):
        generation_bundle._require_fixed_drive_anchor(path)


class _EndlessDirectoryEntries:
    def __init__(self) -> None:
        self.index = 0
        self.closed = False

    def __enter__(self) -> _EndlessDirectoryEntries:
        return self

    def __exit__(self, *_args: Any) -> None:
        self.closed = True

    def __iter__(self) -> _EndlessDirectoryEntries:
        return self

    def __next__(self) -> Any:
        self.index += 1
        return SimpleNamespace(name=f"entry-{self.index}")


def test_directory_scan_stops_at_eighth_entry_and_closes_iterator(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    entries = _EndlessDirectoryEntries()
    monkeypatch.setattr(generation_bundle.os, "scandir", lambda _path: entries)
    with pytest.raises(generation_bundle.GenerationBundleError, match=f"^{SHAPE_ERROR}$"):
        generation_bundle._directory_names(tmp_path)
    assert entries.index == len(generation_bundle._OUTPUT_FILENAMES) + 1
    assert entries.closed is True


def test_alias_walk_is_top_down_and_stops_at_first_reparse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = Path(r"C:\ancestor\descendant")
    visited: list[Path] = []

    def lstat(current: Path) -> Any:
        visited.append(current)
        is_alias = current == Path(r"C:\ancestor")
        return SimpleNamespace(
            st_file_attributes=(generation_bundle._REPARSE_POINT_ATTRIBUTE if is_alias else 0),
            st_mode=stat.S_IFDIR,
        )

    monkeypatch.setattr(type(path), "lstat", lstat)
    assert generation_bundle._path_has_alias(path) is True
    assert visited == [Path("C:\\"), Path(r"C:\ancestor")]


def _install_native_backend_harness(
    monkeypatch: pytest.MonkeyPatch,
    bundle_case: BundleCase,
) -> SimpleNamespace:
    directory = bundle_case.directory.resolve(strict=True)
    canonical = generation_bundle._CanonicalHandlePath(
        "volume{00000000-0000-0000-0000-000000000001}",
        ("external", "bundle"),
    )
    repository = generation_bundle._CanonicalHandlePath(
        canonical.volume_guid,
        ("repository",),
    )
    directory_identity = generation_bundle._FileIdentity(10, 20)
    native_identity = generation_bundle._NativeFileIdentity(30, bytes(range(16)))
    filenames = (SUMMARY_NAME, *generation_bundle._ARTIFACT_FILENAMES)
    states = {
        filename: generation_bundle._FileState(
            identity=generation_bundle._FileIdentity(10, index + 100),
            byte_count=index + 1,
            modified_ns=index + 1000,
        )
        for index, filename in enumerate(filenames)
    }
    raw_handles = {filename: index + 100 for index, filename in enumerate(filenames)}
    handles = {filename: SimpleNamespace(filename=filename) for filename in filenames}
    canonicals = {
        raw_handles[filename]: generation_bundle._canonical_child(canonical, filename)
        for filename in filenames
    }

    @contextmanager
    def owned_handle(*_args: Any, **_kwargs: Any) -> Iterator[Any]:
        yield generation_bundle._OwnedNativeHandle(71)

    @contextmanager
    def binary_file(path: Path) -> Iterator[Any]:
        yield handles[path.name]

    def handle_canonical(raw_handle: int) -> Any:
        return canonical if raw_handle == 71 else canonicals[raw_handle]

    monkeypatch.setattr(generation_bundle, "_WINDOWS_HANDLE_API_AVAILABLE", True)
    monkeypatch.setattr(generation_bundle, "_require_fixed_drive_anchor", lambda _path: None)
    monkeypatch.setattr(generation_bundle, "_path_has_alias", lambda _path: False)
    monkeypatch.setattr(
        generation_bundle,
        "_directory_identity",
        lambda _path: directory_identity,
    )
    monkeypatch.setattr(
        generation_bundle,
        "_expected_canonical_drive_path",
        lambda _path: canonical,
    )
    monkeypatch.setattr(generation_bundle, "_owned_native_handle", owned_handle)
    monkeypatch.setattr(
        generation_bundle,
        "_native_handle_canonical_path",
        handle_canonical,
    )
    monkeypatch.setattr(
        generation_bundle,
        "_native_handle_identity",
        lambda _raw_handle: native_identity,
    )
    monkeypatch.setattr(
        generation_bundle,
        "_native_path_attestation",
        lambda *_args, **_kwargs: (native_identity, canonical),
    )
    monkeypatch.setattr(
        generation_bundle,
        "_repository_canonical_path",
        lambda: repository,
    )
    monkeypatch.setattr(generation_bundle, "_require_local_ntfs_volume", lambda _path: None)
    monkeypatch.setattr(generation_bundle, "_require_no_directory_streams", lambda _raw: None)
    monkeypatch.setattr(
        generation_bundle,
        "_directory_names",
        lambda _path: tuple(filenames),
    )
    monkeypatch.setattr(generation_bundle, "_native_binary_file", binary_file)
    monkeypatch.setattr(
        generation_bundle,
        "_path_file_state",
        lambda path: states[path.name],
    )
    monkeypatch.setattr(
        generation_bundle,
        "_handle_state",
        lambda handle: states[handle.filename],
    )
    monkeypatch.setattr(
        generation_bundle,
        "_native_os_handle",
        lambda handle: raw_handles[handle.filename],
    )
    monkeypatch.setattr(generation_bundle, "_require_unnamed_stream", lambda *_args: None)
    monkeypatch.setattr(generation_bundle, "_require_pinned_state", lambda _artifact: None)

    pinned = MappingProxyType(
        {
            filename: generation_bundle._PinnedArtifact(
                filename=filename,
                path=directory / filename,
                handle=handles[filename],
                state=states[filename],
                canonical_path=canonicals[raw_handles[filename]],
            )
            for filename in filenames
        }
    )
    return SimpleNamespace(
        backend=generation_bundle._Win32FilesystemBackend(),
        bundle=generation_bundle._PinnedBundle(
            directory=directory,
            directory_identity=directory_identity,
            directory_handle=71,
            canonical_path=canonical,
            files=pinned,
            directory_native_identity=native_identity,
        ),
        canonical=canonical,
        native_identity=native_identity,
        states=states,
    )


@pytest.mark.parametrize(
    "phase",
    [
        "directory-alias",
        "resolve-error",
        "resolved-spelling",
        "directory-binding",
        "shape",
        "child-alias",
        "file-binding",
    ],
)
def test_win32_backend_open_rejects_each_boundary_transition(
    bundle_case: BundleCase,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    harness = _install_native_backend_harness(monkeypatch, bundle_case)
    monkeypatch.setattr(harness.backend, "verify", lambda _bundle: None)
    directory = harness.bundle.directory

    if phase == "directory-alias":
        monkeypatch.setattr(generation_bundle, "_path_has_alias", lambda _path: True)
    elif phase == "resolve-error":
        directory = directory / "missing"
    elif phase == "resolved-spelling":
        spellings = iter(("supplied", "resolved"))
        monkeypatch.setattr(
            generation_bundle,
            "_normalized_path_spelling",
            lambda _path: next(spellings),
        )
    elif phase == "directory-binding":
        different = generation_bundle._NativeFileIdentity(31, bytes(range(16)))
        monkeypatch.setattr(
            generation_bundle,
            "_native_path_attestation",
            lambda *_args, **_kwargs: (different, harness.canonical),
        )
    elif phase == "shape":
        monkeypatch.setattr(generation_bundle, "_directory_names", lambda _path: ("wrong",))
    elif phase == "child-alias":
        monkeypatch.setattr(
            generation_bundle,
            "_path_has_alias",
            lambda path: path.name == SUMMARY_NAME,
        )
    else:
        monkeypatch.setattr(
            generation_bundle,
            "_handle_state",
            lambda handle: replace(
                harness.states[handle.filename],
                modified_ns=harness.states[handle.filename].modified_ns + 1,
            ),
        )

    expected = SHAPE_ERROR if phase == "shape" else FILESYSTEM_ERROR
    with pytest.raises(generation_bundle.GenerationBundleError, match=f"^{expected}$"):
        with harness.backend.open(directory):
            pytest.fail("rejected boundary must not yield")


@pytest.mark.parametrize(
    "phase",
    [
        "wrong-type",
        "directory-changed",
        "shape-names",
        "shape-files",
        "child-alias",
        "file-changed",
    ],
)
def test_win32_backend_verify_rejects_each_revalidation_boundary(
    bundle_case: BundleCase,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    harness = _install_native_backend_harness(monkeypatch, bundle_case)
    target: Any = harness.bundle

    if phase == "wrong-type":
        target = object()
    elif phase == "directory-changed":
        monkeypatch.setattr(
            generation_bundle,
            "_path_has_alias",
            lambda path: path == harness.bundle.directory,
        )
    elif phase == "shape-names":
        monkeypatch.setattr(generation_bundle, "_directory_names", lambda _path: ("wrong",))
    elif phase == "shape-files":
        target = replace(harness.bundle, files=MappingProxyType({}))
    elif phase == "child-alias":
        monkeypatch.setattr(
            generation_bundle,
            "_path_has_alias",
            lambda path: path != harness.bundle.directory,
        )
    else:
        monkeypatch.setattr(
            generation_bundle,
            "_path_file_state",
            lambda path: replace(
                harness.states[path.name],
                modified_ns=harness.states[path.name].modified_ns + 1,
            ),
        )

    if phase.startswith("shape"):
        expected = SHAPE_ERROR
    elif phase == "wrong-type":
        expected = FILESYSTEM_ERROR
    else:
        expected = CHANGED_ERROR
    with pytest.raises(generation_bundle.GenerationBundleError, match=f"^{expected}$"):
        harness.backend.verify(target)


class _ManualContext:
    def __init__(
        self,
        bundle: Any,
        *,
        enter_error: BaseException | None = None,
        exit_error: BaseException | None = None,
        suppress: bool = False,
    ) -> None:
        self.bundle = bundle
        self.enter_error = enter_error
        self.exit_error = exit_error
        self.suppress = suppress
        self.exit_args: list[tuple[Any, Any, Any]] = []

    def __enter__(self) -> Any:
        if self.enter_error is not None:
            raise self.enter_error
        return self.bundle

    def __exit__(self, *args: Any) -> bool:
        self.exit_args.append(args)
        if self.exit_error is not None:
            raise self.exit_error
        return self.suppress


class _ManualBackend:
    def __init__(
        self,
        context: _ManualContext,
        *,
        open_error: BaseException | None = None,
    ) -> None:
        self.context = context
        self.open_error = open_error

    def open(self, _directory: Path) -> _ManualContext:
        if self.open_error is not None:
            raise self.open_error
        return self.context

    def verify(self, _bundle: Any) -> None:
        return None


def _assert_exception_chain_is_empty(error: BaseException) -> None:
    pending = [error]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        assert id(current) not in seen
        seen.add(id(current))
        assert current.__cause__ is None
        assert current.__context__ is None


@pytest.mark.parametrize("phase", ["factory", "open", "prepare", "exit"])
def test_public_boundary_clears_exception_chains_recursively(
    bundle_case: BundleCase,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    context = _ManualContext(
        object(),
        exit_error=RuntimeError("private exit") if phase == "exit" else None,
    )
    backend = _ManualBackend(
        context,
        open_error=RuntimeError("private open") if phase == "open" else None,
    )
    if phase == "factory":
        monkeypatch.setattr(
            generation_bundle,
            "_filesystem_backend",
            lambda: (_ for _ in ()).throw(RuntimeError("private factory")),
        )
    else:
        monkeypatch.setattr(generation_bundle, "_filesystem_backend", lambda: backend)

    def prepare(*_args: Any) -> Any:
        if phase == "prepare":
            raise RuntimeError("private prepare")
        return object()

    monkeypatch.setattr(generation_bundle, "_prepare_verified_generation", prepare)
    with pytest.raises(generation_bundle.GenerationBundleError) as captured:
        with generation_bundle.open_reconciled_generation(
            bundle_case.directory,
            bundle_case.summary_sha256,
        ):
            pass
    expected = CONTENT_ERROR if phase == "prepare" else FILESYSTEM_ERROR
    assert str(captured.value) == expected
    _assert_exception_chain_is_empty(captured.value)


def test_hostile_error_subclass_maps_default_without_invoking_str(
    bundle_case: BundleCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class HostileError(generation_bundle.GenerationBundleError):
        def __str__(self) -> str:
            raise AssertionError("must not stringify hostile subclass")

    context = _ManualContext(object())
    backend = _ManualBackend(context, open_error=HostileError(FILESYSTEM_ERROR))
    monkeypatch.setattr(generation_bundle, "_filesystem_backend", lambda: backend)
    with pytest.raises(generation_bundle.GenerationBundleError) as captured:
        with generation_bundle.open_reconciled_generation(
            bundle_case.directory,
            bundle_case.summary_sha256,
        ):
            pass
    assert type(captured.value) is generation_bundle.GenerationBundleError
    assert str(captured.value) == FILESYSTEM_ERROR
    _assert_exception_chain_is_empty(captured.value)


@pytest.mark.parametrize("cleanup", ["clean", "fixed-error", "unexpected-error"])
def test_prepare_baseexception_and_cleanup_failure_ownership(
    bundle_case: BundleCase,
    monkeypatch: pytest.MonkeyPatch,
    cleanup: str,
) -> None:
    if cleanup == "fixed-error":
        exit_error: BaseException | None = generation_bundle.GenerationBundleError(SHAPE_ERROR)
    elif cleanup == "unexpected-error":
        exit_error = RuntimeError("private cleanup")
    else:
        exit_error = None
    context = _ManualContext(object(), exit_error=exit_error)
    backend = _ManualBackend(context)
    monkeypatch.setattr(generation_bundle, "_filesystem_backend", lambda: backend)
    interruption = KeyboardInterrupt("caller interrupt")

    def interrupt(*_args: Any) -> Any:
        raise interruption

    monkeypatch.setattr(generation_bundle, "_prepare_verified_generation", interrupt)
    if cleanup == "clean":
        with pytest.raises(KeyboardInterrupt) as captured:
            with generation_bundle.open_reconciled_generation(
                bundle_case.directory,
                bundle_case.summary_sha256,
            ):
                pass
        assert captured.value is interruption
        _assert_exception_chain_is_empty(captured.value)
    else:
        with pytest.raises(generation_bundle.GenerationBundleError) as captured:
            with generation_bundle.open_reconciled_generation(
                bundle_case.directory,
                bundle_case.summary_sha256,
            ):
                pass
        assert str(captured.value) == (
            SHAPE_ERROR if cleanup == "fixed-error" else FILESYSTEM_ERROR
        )
        _assert_exception_chain_is_empty(captured.value)
    assert len(context.exit_args) == 1


def test_caller_exception_can_be_suppressed_by_pinned_context(
    bundle_case: BundleCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _ManualContext(object(), suppress=True)
    backend = _ManualBackend(context)
    monkeypatch.setattr(generation_bundle, "_filesystem_backend", lambda: backend)
    monkeypatch.setattr(
        generation_bundle,
        "_prepare_verified_generation",
        lambda *_args: object(),
    )
    with generation_bundle.open_reconciled_generation(
        bundle_case.directory,
        bundle_case.summary_sha256,
    ):
        raise LookupError("suppressed caller")
    assert context.exit_args[0][0] is LookupError


def test_line_interrupt_immediately_after_pinned_enter_exits_exactly_once(
    bundle_case: BundleCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _ManualContext(object())
    backend = _ManualBackend(context)
    monkeypatch.setattr(generation_bundle, "_filesystem_backend", lambda: backend)
    monkeypatch.setattr(
        generation_bundle,
        "_prepare_verified_generation",
        lambda *_args: pytest.fail("prepare must not run after the injected interruption"),
    )

    tracked_body = generation_bundle._tracked_pinned_context.__wrapped__
    target_line = _statement_line(tracked_body, "entered = True")
    target_code = tracked_body.__code__
    interruption = KeyboardInterrupt("post-enter line event")
    previous_trace = sys.gettrace()

    def interrupt_after_enter(frame: Any, event: str, _arg: Any) -> Any:
        if frame.f_code is target_code and event == "line" and frame.f_lineno == target_line:
            sys.settrace(previous_trace)
            raise interruption
        return interrupt_after_enter

    sys.settrace(interrupt_after_enter)
    try:
        with pytest.raises(KeyboardInterrupt) as captured:
            with generation_bundle.open_reconciled_generation(
                bundle_case.directory,
                bundle_case.summary_sha256,
            ):
                pass
    finally:
        sys.settrace(previous_trace)

    assert captured.value is interruption
    assert len(context.exit_args) == 1
    exit_type, exit_value, _exit_traceback = context.exit_args[0]
    assert exit_type is KeyboardInterrupt
    assert exit_value is interruption


def test_public_path_rejection_has_no_exception_chain(
    bundle_case: BundleCase,
) -> None:
    with pytest.raises(generation_bundle.GenerationBundleError) as captured:
        with generation_bundle.open_reconciled_generation(  # type: ignore[arg-type]
            os.fspath(bundle_case.directory),
            bundle_case.summary_sha256,
        ):
            pass
    assert str(captured.value) == FILESYSTEM_ERROR
    _assert_exception_chain_is_empty(captured.value)


def test_uninitialized_exact_path_is_rejected_without_leaking_attribute_error(
    bundle_case: BundleCase,
) -> None:
    uninitialized = object.__new__(type(Path()))

    with pytest.raises(generation_bundle.GenerationBundleError) as captured:
        with generation_bundle.open_reconciled_generation(
            uninitialized,
            bundle_case.summary_sha256,
        ):
            pass

    assert str(captured.value) == FILESYSTEM_ERROR
    _assert_exception_chain_is_empty(captured.value)


def test_trust_root_is_checked_before_any_non_summary_carrier_is_read(
    bundle_case: BundleCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    counters: dict[str, _CountingHandle] = {}

    def wrap(filename: str, handle: BinaryIO) -> _CountingHandle:
        counters[filename] = _CountingHandle(handle)
        return counters[filename]

    backend = PortableBackend(handle_wrapper=wrap)
    _assert_error(
        bundle_case,
        monkeypatch,
        TRUST_ERROR,
        trust_root="0" * 64,
        backend=backend,
    )
    assert counters[SUMMARY_NAME].read_count > 0
    for filename in generation_bundle._ARTIFACT_FILENAMES:
        assert counters[filename].read_count == 0
        assert counters[filename].readline_count == 0
        assert counters[filename].seek_count == 0


def test_each_carrier_is_streamed_in_two_independent_passes(
    bundle_case: BundleCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    counters: dict[str, _CountingHandle] = {}

    def wrap(filename: str, handle: BinaryIO) -> _CountingHandle:
        counters[filename] = _CountingHandle(handle)
        return counters[filename]

    backend = _install_backend(monkeypatch, PortableBackend(handle_wrapper=wrap))
    with generation_bundle.open_reconciled_generation(
        bundle_case.directory,
        bundle_case.summary_sha256,
    ):
        pass

    assert backend.verify_calls == 2
    assert counters[SUMMARY_NAME].seek_count == 2
    assert counters[CATALOG_NAME].seek_count == 2
    assert counters[CATALOG_NAME].read_count >= 2
    assert counters[CATALOG_NAME].readline_count == len(bundle_case.records) + 1
    for filename in generation_bundle._STATIC_BYTE_LIMITS:
        assert counters[filename].seek_count == 2
        assert counters[filename].read_count >= 4
