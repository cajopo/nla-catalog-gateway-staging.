"""Fail-closed reader for one externally reconciled catalog generation.

The public boundary in this module is deliberately local and read-only.  It does
not discover a generation, read its trust root from the generation itself, call
Shopify, activate a dataset, or promote a runtime capability.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import stat
import sys
from collections import Counter
from collections.abc import Iterator, Mapping
from contextlib import AbstractContextManager, ExitStack, contextmanager
from ctypes import wintypes
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Any, BinaryIO, Protocol, cast

from nla_catalog_gateway import bulk
from nla_catalog_gateway import runtime_contract as runtime
from nla_catalog_gateway.reconciliation import (
    CAPTURE_FENCE_MAX_SECONDS,
    MAX_PART_MANIFEST_BYTES,
    MAX_RECONCILED_MANIFEST_BYTES,
    RECONCILED_MANIFEST_SCHEMA_VERSION,
    CanonicalNameAuditV1,
    ReconciledCatalogGenerationV1,
    ReconciledSourceManifestV2,
    SnapshotPart,
    SnapshotPartManifestV1,
)
from nla_catalog_gateway.taxonomy import ClassificationReport, ProductFamily

SUMMARY_SCHEMA_VERSION = 2
TAXONOMY_REPORT_SCHEMA_VERSION = 1
MAX_SUMMARY_BYTES = 64 * 1024
MAX_TAXONOMY_REPORT_BYTES = 2 * 1024 * 1024
MAX_DATASET_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_CATALOG_BYTES = 2 * 1024 * 1024 * 1024
MAX_CATALOG_RECORDS = 1_000_000
MAX_CATALOG_VARIANTS = 10_000_000
MAX_VARIANTS_PER_PRODUCT = 10_000

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_CONCRETE_PATH_TYPE = type(Path())
_SUMMARY_FILENAME = "reconciliation-summary.v2.json"
_ARTIFACT_FILENAMES = (
    "catalog-records.v1.jsonl",
    "dataset-manifest.v1.json",
    "products-part-manifest.v1.json",
    "source-manifest.v2.json",
    "taxonomy-report.v1.json",
    "variants-part-manifest.v1.json",
)
_OUTPUT_FILENAMES = frozenset((*_ARTIFACT_FILENAMES, _SUMMARY_FILENAME))
_STATIC_RECORD_COUNTS = MappingProxyType(
    {name: 1 for name in _ARTIFACT_FILENAMES if name != "catalog-records.v1.jsonl"}
)
_STATIC_BYTE_LIMITS = MappingProxyType(
    {
        "dataset-manifest.v1.json": MAX_DATASET_MANIFEST_BYTES,
        "products-part-manifest.v1.json": MAX_PART_MANIFEST_BYTES,
        "source-manifest.v2.json": MAX_RECONCILED_MANIFEST_BYTES,
        "taxonomy-report.v1.json": MAX_TAXONOMY_REPORT_BYTES,
        "variants-part-manifest.v1.json": MAX_PART_MANIFEST_BYTES,
    }
)
_APPROVED_QUERY_SHA256 = MappingProxyType(
    {
        SnapshotPart.PRODUCTS: ("950e1bb757c01d40591437a8b0e5ddbed4476ad8eea39520d0d824b4bfba903a"),
        SnapshotPart.VARIANTS: ("b90f9bf4a691df66a1df8ef0e59aa21f7c23664a09d85d474b30099451f3fda4"),
    }
)

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_GENERATION_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")
_RULE_VERSION_PATTERN = re.compile(r"[0-9A-Za-z][0-9A-Za-z._-]*\Z")
_BOMS = (
    b"\xef\xbb\xbf",
    b"\xff\xfe",
    b"\xfe\xff",
    b"\xff\xfe\x00\x00",
    b"\x00\x00\xfe\xff",
)

_TRUST_ERROR = "generation bundle trust root is invalid"
_FILESYSTEM_ERROR = "generation bundle filesystem boundary is invalid"
_SHAPE_ERROR = "generation bundle shape is invalid"
_CONTENT_ERROR = "generation bundle contents are invalid"
_CHANGED_ERROR = "generation bundle changed during verification"
_PUBLIC_ERRORS = frozenset(
    {_TRUST_ERROR, _FILESYSTEM_ERROR, _SHAPE_ERROR, _CONTENT_ERROR, _CHANGED_ERROR}
)

_SUMMARY_FIELDS = frozenset(
    {
        "artifacts",
        "capabilityPromotion",
        "canonicalNameAudit",
        "catalogRecordCount",
        "classifiedProductCount",
        "datasetActivation",
        "datasetGeneration",
        "schemaVersion",
        "snapshotSetId",
        "sourceGeneration",
        "status",
        "taxonomyRuleVersion",
        "terminalQueryAudits",
        "unclassifiedProductCount",
        "variantCount",
    }
)
_ARTIFACT_FIELDS = frozenset({"bytes", "filename", "recordCount", "sha256"})
_AUDIT_FIELDS = frozenset({"approvedQuerySha256", "part", "rawTerminalQuerySha256", "transport"})
_CANONICAL_NAME_AUDIT_FIELDS = frozenset(
    {
        "duplicateProductExcess",
        "manifestSha256",
        "mappingBytes",
        "mappingRecordCount",
        "mappingSha256",
        "matchedProductCount",
        "matchedUniqueKeyCount",
        "unusedMappingCount",
    }
)
_SOURCE_FIELDS = frozenset(
    {
        "activeOnlineStorePublishedProductCount",
        "captureCompletedAt",
        "captureFenceMaxSeconds",
        "captureStartedAt",
        "captureWindowSeconds",
        "inventoryItemCount",
        "inventoryLevelCount",
        "metafieldCount",
        "parts",
        "productCount",
        "productStatusCounts",
        "publicationCount",
        "schemaVersion",
        "snapshotSetId",
        "sourceGeneration",
        "sourceIdentityProductCount",
        "sourceQuerySha256",
        "sourceSnapshotSha256",
        "variantCount",
    }
)
_TAXONOMY_FIELDS = frozenset(
    {
        "classificationRuleVersion",
        "classified",
        "counts",
        "ruleCounts",
        "schemaVersion",
        "subtypeReasons",
        "total",
        "unclassified",
        "unclassifiedReasons",
    }
)


class GenerationBundleError(ValueError):
    """A fixed, value-free rejection of an untrusted generation bundle."""


@dataclass(frozen=True, slots=True, repr=False)
class VerifiedReconciledGenerationV1:
    """One fully verified, still-provisional generation held in memory."""

    generation: ReconciledCatalogGenerationV1 = field(repr=False)
    summary_sha256: str

    def __post_init__(self) -> None:
        if type(self.generation) is not ReconciledCatalogGenerationV1:
            raise GenerationBundleError(_CONTENT_ERROR)
        if (
            type(self.summary_sha256) is not str
            or _SHA256_PATTERN.fullmatch(self.summary_sha256) is None
        ):
            raise GenerationBundleError(_TRUST_ERROR)


@dataclass(frozen=True, slots=True)
class _ArtifactContract:
    filename: str
    sha256: str
    byte_count: int
    record_count: int


@dataclass(frozen=True, slots=True)
class _TerminalQueryAudit:
    part: SnapshotPart
    approved_query_sha256: str
    raw_terminal_query_sha256: str
    transport: str


@dataclass(frozen=True, slots=True)
class _SummaryContract:
    artifacts: tuple[_ArtifactContract, ...]
    canonical_name_audit: CanonicalNameAuditV1 | None
    catalog_record_count: int
    classified_product_count: int
    dataset_generation: str
    snapshot_set_id: str
    source_generation: str
    taxonomy_rule_version: str
    terminal_query_audits: tuple[_TerminalQueryAudit, _TerminalQueryAudit]
    unclassified_product_count: int
    variant_count: int

    @property
    def artifacts_by_name(self) -> Mapping[str, _ArtifactContract]:
        return MappingProxyType({artifact.filename: artifact for artifact in self.artifacts})


@dataclass(frozen=True, slots=True)
class _FileIdentity:
    device: int
    inode: int


@dataclass(frozen=True, slots=True)
class _NativeFileIdentity:
    volume_serial_number: int
    file_id: bytes


@dataclass(frozen=True, slots=True)
class _FileState:
    identity: _FileIdentity
    byte_count: int
    modified_ns: int


@dataclass(frozen=True, slots=True)
class _CanonicalHandlePath:
    volume_guid: str
    components: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _PinnedArtifact:
    filename: str
    path: Path
    handle: BinaryIO
    state: _FileState
    canonical_path: _CanonicalHandlePath | Path
    linux_state: tuple[int, ...] | None = None


@dataclass(frozen=True, slots=True)
class _PinnedBundle:
    directory: Path
    directory_identity: _FileIdentity
    directory_handle: int
    canonical_path: _CanonicalHandlePath | Path
    files: Mapping[str, _PinnedArtifact]
    directory_native_identity: _NativeFileIdentity | None = None
    linux_state: tuple[int, ...] | None = None


class _BundleFilesystemBackend(Protocol):
    def open(self, directory: Path) -> AbstractContextManager[_PinnedBundle]: ...

    def verify(self, bundle: _PinnedBundle) -> None: ...


@dataclass(frozen=True, slots=True)
class _FileScan:
    sha256: str
    byte_count: int


@dataclass(slots=True)
class _OwnedNativeHandle:
    raw_handle: int | None = None

    @property
    def handle(self) -> int:
        if self.raw_handle is None:
            raise GenerationBundleError(_FILESYSTEM_ERROR)
        return self.raw_handle

    def release(self) -> int:
        # Keep the ownership hand-off on one trace line. A line-level
        # interruption must observe either this owner or its recipient.
        return (self.handle, setattr(self, "raw_handle", None))[0]

    def close(self) -> None:
        try:
            if self.raw_handle is not None:
                self.raw_handle = _native_close(self.handle)
        except BaseException as failure:
            failure_traceback = failure.__traceback__
            if self.raw_handle is not None:
                try:
                    self.raw_handle = _native_close(self.handle)
                except BaseException as retry_failure:
                    raise retry_failure
            raise failure.with_traceback(failure_traceback) from None


@dataclass(slots=True)
class _OwnedNativeBinary:
    descriptor: int | None = None
    handle: BinaryIO | None = None

    def release(self) -> BinaryIO:
        if self.handle is None:
            raise GenerationBundleError(_FILESYSTEM_ERROR)
        # See _OwnedNativeHandle.release: transfer and return share a trace line.
        return (self.handle, setattr(self, "handle", None))[0]

    def close(self) -> None:
        try:
            if self.handle is not None:
                self.handle = self.handle.close()
            elif self.descriptor is not None:
                self.descriptor = os.close(self.descriptor)
        except BaseException as failure:
            failure_traceback = failure.__traceback__
            try:
                if self.handle is not None:
                    self.handle = self.handle.close()
                elif self.descriptor is not None:
                    self.descriptor = os.close(self.descriptor)
            except BaseException as retry_failure:
                raise retry_failure
            raise failure.with_traceback(failure_traceback) from None


@dataclass(slots=True)
class _PinnedContextLifecycle:
    enter_failure: BaseException | None = None
    body_failure: BaseException | None = None
    exit_failure: BaseException | None = None


class _StrictJsonError(ValueError):
    pass


def _canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (RecursionError, TypeError, UnicodeEncodeError, ValueError) as exc:
        raise GenerationBundleError(_CONTENT_ERROR) from exc


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _StrictJsonError
        result[key] = value
    return result


def _parse_integer(value: str) -> int:
    if len(value.lstrip("-")) > 19:
        raise _StrictJsonError
    parsed = int(value)
    if not -(2**63) <= parsed < 2**63:
        raise _StrictJsonError
    return parsed


def _reject_number(_value: str) -> None:
    raise _StrictJsonError


def _contains_surrogate(value: str) -> bool:
    return any(0xD800 <= ord(character) <= 0xDFFF for character in value)


def _validate_unicode_tree(root: Any) -> None:
    pending = [root]
    while pending:
        value = pending.pop()
        if type(value) is str:
            if _contains_surrogate(value):
                raise _StrictJsonError
        elif type(value) is dict:
            pending.extend(value.keys())
            pending.extend(value.values())
        elif type(value) is list:
            pending.extend(value)


def _strict_json_object(raw: bytes, *, maximum: int) -> dict[str, Any]:
    if type(raw) is not bytes or not raw or len(raw) > maximum or raw.startswith(_BOMS):
        raise GenerationBundleError(_CONTENT_ERROR)
    try:
        text = raw.decode("utf-8", errors="strict")
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_number,
            parse_float=_reject_number,
            parse_int=_parse_integer,
        )
        _validate_unicode_tree(value)
    except (RecursionError, UnicodeDecodeError, ValueError) as exc:
        raise GenerationBundleError(_CONTENT_ERROR) from exc
    if type(value) is not dict or _canonical_json_bytes(value) != raw:
        raise GenerationBundleError(_CONTENT_ERROR)
    return value


def _exact_keys(value: dict[str, Any], expected: frozenset[str]) -> None:
    if any(type(key) is not str for key in value) or frozenset(value) != expected:
        raise GenerationBundleError(_CONTENT_ERROR)


def _count(value: Any, *, positive: bool = False) -> int:
    minimum = 1 if positive else 0
    if type(value) is not int or not minimum <= value < 2**63:
        raise GenerationBundleError(_CONTENT_ERROR)
    return value


def _text(value: Any, *, pattern: re.Pattern[str] | None = None) -> str:
    if type(value) is not str or not value or _contains_surrogate(value):
        raise GenerationBundleError(_CONTENT_ERROR)
    if pattern is not None and pattern.fullmatch(value) is None:
        raise GenerationBundleError(_CONTENT_ERROR)
    return value


def _sha256(value: Any) -> str:
    return _text(value, pattern=_SHA256_PATTERN)


def _generation(value: Any) -> str:
    return _text(value, pattern=_GENERATION_PATTERN)


def _parse_summary(raw: bytes) -> _SummaryContract:
    value = _strict_json_object(raw, maximum=MAX_SUMMARY_BYTES)
    _exact_keys(value, _SUMMARY_FIELDS)
    if (
        type(value["schemaVersion"]) is not int
        or value["schemaVersion"] != SUMMARY_SCHEMA_VERSION
        or value["status"] != "reconciled-provisional"
        or value["datasetActivation"] != "not-performed"
        or value["capabilityPromotion"] != "not-performed"
    ):
        raise GenerationBundleError(_CONTENT_ERROR)

    catalog_count = _count(value["catalogRecordCount"], positive=True)
    classified = _count(value["classifiedProductCount"])
    unclassified = _count(value["unclassifiedProductCount"])
    variant_count = _count(value["variantCount"], positive=True)
    if (
        catalog_count > MAX_CATALOG_RECORDS
        or classified + unclassified != catalog_count
        or variant_count < catalog_count
        or variant_count > MAX_CATALOG_VARIANTS
    ):
        raise GenerationBundleError(_CONTENT_ERROR)

    raw_artifacts = value["artifacts"]
    if type(raw_artifacts) is not list or len(raw_artifacts) != len(_ARTIFACT_FILENAMES):
        raise GenerationBundleError(_CONTENT_ERROR)
    artifacts: list[_ArtifactContract] = []
    for index, raw_artifact in enumerate(raw_artifacts):
        if type(raw_artifact) is not dict:
            raise GenerationBundleError(_CONTENT_ERROR)
        _exact_keys(raw_artifact, _ARTIFACT_FIELDS)
        filename = _text(raw_artifact["filename"])
        if filename != _ARTIFACT_FILENAMES[index]:
            raise GenerationBundleError(_CONTENT_ERROR)
        byte_count = _count(raw_artifact["bytes"], positive=True)
        record_count = _count(raw_artifact["recordCount"], positive=True)
        expected_records = (
            catalog_count
            if filename == "catalog-records.v1.jsonl"
            else _STATIC_RECORD_COUNTS[filename]
        )
        if record_count != expected_records:
            raise GenerationBundleError(_CONTENT_ERROR)
        if filename == "catalog-records.v1.jsonl":
            if byte_count > MAX_CATALOG_BYTES:
                raise GenerationBundleError(_CONTENT_ERROR)
        elif byte_count > _STATIC_BYTE_LIMITS[filename]:
            raise GenerationBundleError(_CONTENT_ERROR)
        artifacts.append(
            _ArtifactContract(filename, _sha256(raw_artifact["sha256"]), byte_count, record_count)
        )

    raw_audits = value["terminalQueryAudits"]
    if type(raw_audits) is not list or len(raw_audits) != 2:
        raise GenerationBundleError(_CONTENT_ERROR)
    audits: list[_TerminalQueryAudit] = []
    for expected_part, raw_audit in zip(
        (SnapshotPart.PRODUCTS, SnapshotPart.VARIANTS), raw_audits, strict=True
    ):
        if type(raw_audit) is not dict:
            raise GenerationBundleError(_CONTENT_ERROR)
        _exact_keys(raw_audit, _AUDIT_FIELDS)
        if raw_audit["part"] != expected_part.value or raw_audit["transport"] not in {
            "canonical-lf-v1",
            "shopify-crlf-plus-one-terminal-newline-v1",
        }:
            raise GenerationBundleError(_CONTENT_ERROR)
        audits.append(
            _TerminalQueryAudit(
                part=expected_part,
                approved_query_sha256=_sha256(raw_audit["approvedQuerySha256"]),
                raw_terminal_query_sha256=_sha256(raw_audit["rawTerminalQuerySha256"]),
                transport=raw_audit["transport"],
            )
        )

    raw_canonical_audit = value["canonicalNameAudit"]
    canonical_audit = None
    if raw_canonical_audit is not None:
        if type(raw_canonical_audit) is not dict:
            raise GenerationBundleError(_CONTENT_ERROR)
        _exact_keys(raw_canonical_audit, _CANONICAL_NAME_AUDIT_FIELDS)
        mapping_count = _count(raw_canonical_audit["mappingRecordCount"])
        mapping_bytes = _count(raw_canonical_audit["mappingBytes"])
        matched_unique = _count(raw_canonical_audit["matchedUniqueKeyCount"])
        matched_products = _count(raw_canonical_audit["matchedProductCount"])
        duplicate_excess = _count(raw_canonical_audit["duplicateProductExcess"])
        unused = _count(raw_canonical_audit["unusedMappingCount"])
        if (
            (mapping_bytes == 0) != (mapping_count == 0)
            or matched_unique > mapping_count
            or matched_products < matched_unique
            or matched_products > catalog_count
            or duplicate_excess != matched_products - matched_unique
            or unused != mapping_count - matched_unique
        ):
            raise GenerationBundleError(_CONTENT_ERROR)
        canonical_audit = CanonicalNameAuditV1(
            manifest_sha256=_sha256(raw_canonical_audit["manifestSha256"]),
            mapping_sha256=_sha256(raw_canonical_audit["mappingSha256"]),
            mapping_bytes=mapping_bytes,
            mapping_record_count=mapping_count,
            matched_unique_key_count=matched_unique,
            matched_product_count=matched_products,
            duplicate_product_excess=duplicate_excess,
            unused_mapping_count=unused,
        )

    return _SummaryContract(
        artifacts=tuple(artifacts),
        canonical_name_audit=canonical_audit,
        catalog_record_count=catalog_count,
        classified_product_count=classified,
        dataset_generation=_generation(value["datasetGeneration"]),
        snapshot_set_id=_generation(value["snapshotSetId"]),
        source_generation=_generation(value["sourceGeneration"]),
        taxonomy_rule_version=_text(value["taxonomyRuleVersion"], pattern=_RULE_VERSION_PATTERN),
        terminal_query_audits=(audits[0], audits[1]),
        unclassified_product_count=unclassified,
        variant_count=variant_count,
    )


def _digest_object(value: Any, *, domain: str) -> str:
    return hashlib.sha256(_canonical_json_bytes({"domain": domain, "value": value})).hexdigest()


def _canonical_utc(value: datetime) -> str:
    canonical = value.astimezone(UTC).isoformat(timespec="microseconds")
    canonical = canonical.replace(".000000+00:00", "Z")
    if canonical.endswith("+00:00"):
        canonical = canonical.removesuffix("+00:00") + "Z"
    return canonical


def _timestamp(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except (OverflowError, ValueError) as exc:
        raise GenerationBundleError(_CONTENT_ERROR) from exc


def _parse_part_manifest(raw: bytes, expected_part: SnapshotPart) -> SnapshotPartManifestV1:
    _strict_json_object(raw, maximum=MAX_PART_MANIFEST_BYTES)
    try:
        manifest = SnapshotPartManifestV1.from_json_bytes(raw)
        if manifest.to_json_bytes() != raw or manifest.part is not expected_part:
            raise GenerationBundleError(_CONTENT_ERROR)
    except GenerationBundleError:
        raise
    except Exception as exc:
        raise GenerationBundleError(_CONTENT_ERROR) from exc
    if manifest.query_sha256 != _APPROVED_QUERY_SHA256[expected_part]:
        raise GenerationBundleError(_CONTENT_ERROR)
    return manifest


def _source_count_map(value: Any) -> tuple[tuple[str, int], ...]:
    if type(value) is not dict or frozenset(value) != frozenset(bulk.PRODUCT_STATUSES):
        raise GenerationBundleError(_CONTENT_ERROR)
    result = tuple((status, _count(value[status])) for status in bulk.PRODUCT_STATUSES)
    return result


def _parse_source_manifest(
    raw: bytes,
    products: SnapshotPartManifestV1,
    variants: SnapshotPartManifestV1,
) -> ReconciledSourceManifestV2:
    value = _strict_json_object(raw, maximum=MAX_RECONCILED_MANIFEST_BYTES)
    _exact_keys(value, _SOURCE_FIELDS)
    if (
        type(value["schemaVersion"]) is not int
        or value["schemaVersion"] != RECONCILED_MANIFEST_SCHEMA_VERSION
        or value["parts"] != [products.as_dict(), variants.as_dict()]
    ):
        raise GenerationBundleError(_CONTENT_ERROR)

    common_fields = (
        "snapshot_set_id",
        "shop_domain",
        "api_version",
        "online_store_publication_gid",
        "source_code_sha",
    )
    if any(getattr(products, field) != getattr(variants, field) for field in common_fields):
        raise GenerationBundleError(_CONTENT_ERROR)
    if products.operation_id == variants.operation_id:
        raise GenerationBundleError(_CONTENT_ERROR)

    created = (_timestamp(products.created_at), _timestamp(variants.created_at))
    completed = (_timestamp(products.completed_at), _timestamp(variants.completed_at))
    if max(created) > min(completed):
        raise GenerationBundleError(_CONTENT_ERROR)
    capture_started = min(created)
    capture_completed = max(completed)
    capture_duration = capture_completed - capture_started
    if capture_duration > timedelta(seconds=CAPTURE_FENCE_MAX_SECONDS):
        raise GenerationBundleError(_CONTENT_ERROR)

    source_query_sha256 = _digest_object(
        [
            {"part": part.part.value, "querySha256": part.query_sha256}
            for part in (products, variants)
        ],
        domain="nla-split-query-set-v1",
    )
    source_snapshot_sha256 = _digest_object(
        [
            {
                "contentSha256": part.content_sha256,
                "objectCounts": dict(part.object_counts),
                "part": part.part.value,
                "snapshotBytes": part.snapshot_bytes,
            }
            for part in (products, variants)
        ],
        domain="nla-split-snapshot-set-v1",
    )
    generation_descriptor = {
        "apiVersion": products.api_version,
        "captureCompletedAt": _canonical_utc(capture_completed),
        "captureFenceMaxSeconds": CAPTURE_FENCE_MAX_SECONDS,
        "captureStartedAt": _canonical_utc(capture_started),
        "captureWindowSeconds": int(capture_duration.total_seconds()),
        "partGenerations": [products.part_generation, variants.part_generation],
        "shopDomain": products.shop_domain,
        "snapshotSetId": products.snapshot_set_id,
        "sourceCodeSha": products.source_code_sha,
        "sourceQuerySha256": source_query_sha256,
        "sourceSnapshotSha256": source_snapshot_sha256,
    }
    source_generation = (
        f"sha256:{_digest_object(generation_descriptor, domain='nla-reconciled-source-v2')}"
    )

    product_counts = dict(products.object_counts)
    variant_counts = dict(variants.object_counts)
    product_count = _count(value["productCount"], positive=True)
    variant_count = _count(value["variantCount"], positive=True)
    inventory_item_count = _count(value["inventoryItemCount"], positive=True)
    inventory_level_count = _count(value["inventoryLevelCount"])
    publication_count = _count(value["publicationCount"], positive=True)
    metafield_count = _count(value["metafieldCount"])
    active_published = _count(value["activeOnlineStorePublishedProductCount"])
    source_identity_count = _count(value["sourceIdentityProductCount"])
    status_counts = _source_count_map(value["productStatusCounts"])

    if (
        value["snapshotSetId"] != products.snapshot_set_id
        or value["captureStartedAt"] != generation_descriptor["captureStartedAt"]
        or value["captureCompletedAt"] != generation_descriptor["captureCompletedAt"]
        or value["captureWindowSeconds"] != generation_descriptor["captureWindowSeconds"]
        or value["captureFenceMaxSeconds"] != CAPTURE_FENCE_MAX_SECONDS
        or value["sourceQuerySha256"] != source_query_sha256
        or value["sourceSnapshotSha256"] != source_snapshot_sha256
        or value["sourceGeneration"] != source_generation
        or product_count != product_counts["Product"]
        or variant_count != variant_counts["ProductVariant"]
        or inventory_item_count != variant_count
        or inventory_level_count != variant_counts["InventoryLevel"]
        or publication_count != product_counts["ResourcePublicationV2"]
        or metafield_count != product_counts["Metafield"] + variant_counts["Metafield"]
        or sum(dict(status_counts).values()) != product_count
        or active_published > dict(status_counts)["ACTIVE"]
        or source_identity_count > product_count
    ):
        raise GenerationBundleError(_CONTENT_ERROR)

    manifest = ReconciledSourceManifestV2(
        snapshot_set_id=products.snapshot_set_id,
        parts=(products, variants),
        capture_started_at=generation_descriptor["captureStartedAt"],
        capture_completed_at=generation_descriptor["captureCompletedAt"],
        capture_window_seconds=generation_descriptor["captureWindowSeconds"],
        capture_fence_max_seconds=CAPTURE_FENCE_MAX_SECONDS,
        source_query_sha256=source_query_sha256,
        source_snapshot_sha256=source_snapshot_sha256,
        source_generation=source_generation,
        product_count=product_count,
        variant_count=variant_count,
        inventory_item_count=inventory_item_count,
        inventory_level_count=inventory_level_count,
        publication_count=publication_count,
        metafield_count=metafield_count,
        product_status_counts=status_counts,
        active_published_product_count=active_published,
        source_identity_product_count=source_identity_count,
    )
    if manifest.to_json_bytes() != raw:
        raise GenerationBundleError(_CONTENT_ERROR)
    return manifest


def _parse_dataset_manifest(raw: bytes) -> runtime.DatasetManifestV1:
    _strict_json_object(raw, maximum=MAX_DATASET_MANIFEST_BYTES)
    try:
        manifest = runtime.DatasetManifestV1.from_json_bytes(raw)
        if manifest.to_json_bytes() != raw:
            raise GenerationBundleError(_CONTENT_ERROR)
    except GenerationBundleError:
        raise
    except Exception as exc:
        raise GenerationBundleError(_CONTENT_ERROR) from exc
    capabilities = (*manifest.capability_matrix.features, *manifest.capability_matrix.requests)
    if any(state is runtime.CapabilityState.VERIFIED for _name, state in capabilities):
        raise GenerationBundleError(_CONTENT_ERROR)
    return manifest


def _product_gid_key(value: str) -> tuple[int, str]:
    prefix = "gid://shopify/Product/"
    digits = value.removeprefix(prefix)
    if not value.startswith(prefix) or not digits.isascii() or not digits.isdigit():
        raise GenerationBundleError(_CONTENT_ERROR)
    return (len(digits), digits)


def _classification_report_for_records(
    records: tuple[runtime.CatalogProductRecordV1, ...],
) -> ClassificationReport:
    counts = Counter(
        f"{record.game.value if record.game else 'unknown'}/{record.product_family.value}"
        for record in records
    )
    rule_counts = Counter(
        record.classification_rule_id
        for record in records
        if record.classification_rule_id is not None
    )
    unclassified_reasons = Counter(
        record.unclassified_reason for record in records if record.unclassified_reason is not None
    )
    subtype_reasons = Counter(
        record.subtype_reason for record in records if record.subtype_reason is not None
    )
    classified = sum(record.product_family is not ProductFamily.UNCLASSIFIED for record in records)
    return ClassificationReport(
        rule_version=records[0].classification_rule_version,
        total=len(records),
        classified=classified,
        unclassified=len(records) - classified,
        counts=MappingProxyType(dict(counts)),
        rule_counts=MappingProxyType(dict(rule_counts)),
        unclassified_reasons=MappingProxyType(dict(unclassified_reasons)),
        subtype_reasons=MappingProxyType(dict(subtype_reasons)),
    )


def _parse_taxonomy_report(
    raw: bytes,
    records: tuple[runtime.CatalogProductRecordV1, ...],
) -> ClassificationReport:
    value = _strict_json_object(raw, maximum=MAX_TAXONOMY_REPORT_BYTES)
    _exact_keys(value, _TAXONOMY_FIELDS)
    report = _classification_report_for_records(records)
    expected = {"schemaVersion": TAXONOMY_REPORT_SCHEMA_VERSION, **report.as_dict()}
    if value != expected or _canonical_json_bytes(expected) != raw:
        raise GenerationBundleError(_CONTENT_ERROR)
    return report


def _cross_check_generation(
    *,
    summary: _SummaryContract,
    source: ReconciledSourceManifestV2,
    source_raw: bytes,
    dataset: runtime.DatasetManifestV1,
    report: ClassificationReport,
    records: tuple[runtime.CatalogProductRecordV1, ...],
) -> None:
    try:
        dataset.validate_records(records)
    except Exception as exc:
        raise GenerationBundleError(_CONTENT_ERROR) from exc
    expected_generated_at = max(
        source.parts,
        key=lambda part: _timestamp(part.completed_at),
    ).completed_at
    if (
        summary.catalog_record_count != len(records)
        or summary.classified_product_count != report.classified
        or summary.unclassified_product_count != report.unclassified
        or summary.variant_count != source.variant_count
        or summary.dataset_generation != dataset.dataset_generation
        or summary.snapshot_set_id != source.snapshot_set_id
        or summary.source_generation != source.source_generation
        or summary.taxonomy_rule_version != report.rule_version
        or dataset.source_snapshot_manifest_sha256 != hashlib.sha256(source_raw).hexdigest()
        or dataset.source_snapshot_manifest_schema_version != source.schema_version
        or dataset.source_snapshot_sha256 != source.source_snapshot_sha256
        or dataset.source_query_sha256 != source.source_query_sha256
        or dataset.taxonomy_rule_version != report.rule_version
        or dataset.generated_at != expected_generated_at
        or dataset.source_product_count != source.product_count
        or dataset.included_product_count != source.product_count
        or dataset.excluded_product_count != 0
        or dataset.source_product_status_counts != source.product_status_counts
        or dataset.included_product_status_counts != source.product_status_counts
        or any(count for _status, count in dataset.excluded_product_status_counts)
        or dataset.source_variant_count != source.variant_count
        or dataset.included_variant_count != source.variant_count
        or dataset.excluded_variant_count != 0
        or dataset.source_identity_product_count != source.source_identity_product_count
        or dataset.included_source_identity_product_count != source.source_identity_product_count
        or dataset.excluded_source_identity_product_count != 0
        or dataset.source_active_online_store_published_product_count
        != source.active_published_product_count
        or dataset.included_active_online_store_published_product_count
        != source.active_published_product_count
        or dataset.excluded_active_online_store_published_product_count != 0
        or sum(record.powertools_source_id is not None for record in records)
        != source.source_identity_product_count
        or sum(record.publishable for record in records) != source.active_published_product_count
        or sum(len(record.variants) for record in records) != source.variant_count
        or len({variant.inventory_item_gid for record in records for variant in record.variants})
        != source.inventory_item_count
    ):
        raise GenerationBundleError(_CONTENT_ERROR)

    for audit, part in zip(summary.terminal_query_audits, source.parts, strict=True):
        if audit.part is not part.part or audit.approved_query_sha256 != part.query_sha256:
            raise GenerationBundleError(_CONTENT_ERROR)


def _handle_state(handle: BinaryIO) -> _FileState:
    try:
        facts = os.fstat(handle.fileno())
    except (OSError, ValueError) as exc:
        raise GenerationBundleError(_FILESYSTEM_ERROR) from exc
    if not stat.S_ISREG(facts.st_mode) or facts.st_nlink != 1:
        raise GenerationBundleError(_FILESYSTEM_ERROR)
    return _FileState(
        identity=_FileIdentity(facts.st_dev, facts.st_ino),
        byte_count=facts.st_size,
        modified_ns=facts.st_mtime_ns,
    )


def _require_pinned_state(artifact: _PinnedArtifact) -> None:
    if _handle_state(artifact.handle) != artifact.state:
        raise GenerationBundleError(_CHANGED_ERROR)


def _scan_pinned_file(artifact: _PinnedArtifact) -> _FileScan:
    _require_pinned_state(artifact)
    digest = hashlib.sha256()
    byte_count = 0
    try:
        artifact.handle.seek(0)
        while True:
            chunk = artifact.handle.read(1024 * 1024)
            if not chunk:
                break
            if type(chunk) is not bytes:
                raise GenerationBundleError(_CONTENT_ERROR)
            digest.update(chunk)
            byte_count += len(chunk)
    except GenerationBundleError:
        raise
    except (OSError, ValueError) as exc:
        raise GenerationBundleError(_FILESYSTEM_ERROR) from exc
    _require_pinned_state(artifact)
    if byte_count != artifact.state.byte_count:
        raise GenerationBundleError(_CHANGED_ERROR)
    return _FileScan(digest.hexdigest(), byte_count)


def _read_bounded_file(artifact: _PinnedArtifact, *, maximum: int) -> tuple[bytes, _FileScan]:
    if artifact.state.byte_count < 1 or artifact.state.byte_count > maximum:
        raise GenerationBundleError(_CONTENT_ERROR)
    _require_pinned_state(artifact)
    pending = artifact.state.byte_count
    chunks: list[bytes] = []
    digest = hashlib.sha256()
    try:
        artifact.handle.seek(0)
        while pending:
            chunk = artifact.handle.read(min(pending, 1024 * 1024))
            if not chunk or type(chunk) is not bytes:
                raise GenerationBundleError(_CHANGED_ERROR)
            chunks.append(chunk)
            digest.update(chunk)
            pending -= len(chunk)
        if artifact.handle.read(1):
            raise GenerationBundleError(_CHANGED_ERROR)
    except GenerationBundleError:
        raise
    except (OSError, ValueError) as exc:
        raise GenerationBundleError(_FILESYSTEM_ERROR) from exc
    _require_pinned_state(artifact)
    raw = b"".join(chunks)
    return raw, _FileScan(digest.hexdigest(), len(raw))


def _read_catalog_records(
    artifact: _PinnedArtifact,
    contract: _ArtifactContract,
    *,
    expected_variant_count: int,
) -> tuple[tuple[runtime.CatalogProductRecordV1, ...], _FileScan]:
    if (
        artifact.state.byte_count != contract.byte_count
        or artifact.state.byte_count < 1
        or artifact.state.byte_count > MAX_CATALOG_BYTES
        or contract.record_count > MAX_CATALOG_RECORDS
    ):
        raise GenerationBundleError(_CONTENT_ERROR)
    _require_pinned_state(artifact)
    digest = hashlib.sha256()
    byte_count = 0
    records: list[runtime.CatalogProductRecordV1] = []
    previous_key: tuple[int, str] | None = None
    variant_count = 0
    try:
        artifact.handle.seek(0)
        while True:
            line = artifact.handle.readline(runtime.MAX_CONTRACT_BYTES + 2)
            if line == b"":
                break
            if type(line) is not bytes:
                raise GenerationBundleError(_CONTENT_ERROR)
            byte_count += len(line)
            digest.update(line)
            if (
                len(line) > runtime.MAX_CONTRACT_BYTES + 1
                or not line.endswith(b"\n")
                or b"\r" in line
                or byte_count > contract.byte_count
                or len(records) >= contract.record_count
            ):
                raise GenerationBundleError(_CONTENT_ERROR)
            raw_record = line[:-1]
            if not raw_record or len(raw_record) > runtime.MAX_CONTRACT_BYTES:
                raise GenerationBundleError(_CONTENT_ERROR)
            try:
                raw_value = _strict_json_object(raw_record, maximum=runtime.MAX_CONTRACT_BYTES)
                raw_variants = raw_value.get("variants")
                if (
                    type(raw_variants) is not list
                    or len(raw_variants) > MAX_VARIANTS_PER_PRODUCT
                    or variant_count + len(raw_variants) > expected_variant_count
                ):
                    raise GenerationBundleError(_CONTENT_ERROR)
                record = runtime.CatalogProductRecordV1.from_dict(raw_value)
                if record.to_json_bytes() != raw_record:
                    raise GenerationBundleError(_CONTENT_ERROR)
            except GenerationBundleError:
                raise
            except Exception as exc:
                raise GenerationBundleError(_CONTENT_ERROR) from exc
            key = _product_gid_key(record.product_gid)
            if previous_key is not None and key <= previous_key:
                raise GenerationBundleError(_CONTENT_ERROR)
            previous_key = key
            variant_count += len(record.variants)
            if variant_count > MAX_CATALOG_VARIANTS:
                raise GenerationBundleError(_CONTENT_ERROR)
            records.append(record)
            if len(records) > contract.record_count or len(records) > MAX_CATALOG_RECORDS:
                raise GenerationBundleError(_CONTENT_ERROR)
    except GenerationBundleError:
        raise
    except (OSError, ValueError) as exc:
        raise GenerationBundleError(_FILESYSTEM_ERROR) from exc
    _require_pinned_state(artifact)
    scan = _FileScan(digest.hexdigest(), byte_count)
    if (
        scan.sha256 != contract.sha256
        or scan.byte_count != contract.byte_count
        or len(records) != contract.record_count
        or variant_count != expected_variant_count
    ):
        raise GenerationBundleError(_CONTENT_ERROR)
    return tuple(records), scan


def _require_scan(scan: _FileScan, contract: _ArtifactContract) -> None:
    if scan.sha256 != contract.sha256 or scan.byte_count != contract.byte_count:
        raise GenerationBundleError(_CONTENT_ERROR)


def _artifact(bundle: _PinnedBundle, filename: str) -> _PinnedArtifact:
    try:
        artifact = bundle.files[filename]
    except (KeyError, TypeError) as exc:
        raise GenerationBundleError(_SHAPE_ERROR) from exc
    if type(artifact) is not _PinnedArtifact or artifact.filename != filename:
        raise GenerationBundleError(_SHAPE_ERROR)
    return artifact


def _prepare_verified_generation(
    bundle: _PinnedBundle,
    expected_summary_sha256: str,
    backend: _BundleFilesystemBackend,
) -> VerifiedReconciledGenerationV1:
    backend.verify(bundle)
    if frozenset(bundle.files) != _OUTPUT_FILENAMES or len(bundle.files) != len(_OUTPUT_FILENAMES):
        raise GenerationBundleError(_SHAPE_ERROR)

    summary_file = _artifact(bundle, _SUMMARY_FILENAME)
    first_summary_raw, first_summary_scan = _read_bounded_file(
        summary_file, maximum=MAX_SUMMARY_BYTES
    )
    if first_summary_scan.sha256 != expected_summary_sha256:
        raise GenerationBundleError(_TRUST_ERROR)
    summary = _parse_summary(first_summary_raw)
    contracts = summary.artifacts_by_name

    first_scans: dict[str, _FileScan] = {}
    for filename in _ARTIFACT_FILENAMES:
        artifact = _artifact(bundle, filename)
        contract = contracts[filename]
        if artifact.state.byte_count != contract.byte_count:
            raise GenerationBundleError(_CONTENT_ERROR)
        scan = _scan_pinned_file(artifact)
        _require_scan(scan, contract)
        first_scans[filename] = scan

    second_summary_raw, second_summary_scan = _read_bounded_file(
        summary_file, maximum=MAX_SUMMARY_BYTES
    )
    if (
        second_summary_raw != first_summary_raw
        or second_summary_scan != first_summary_scan
        or second_summary_scan.sha256 != expected_summary_sha256
        or _parse_summary(second_summary_raw) != summary
    ):
        raise GenerationBundleError(_CHANGED_ERROR)

    static_raw: dict[str, bytes] = {}
    for filename, maximum in _STATIC_BYTE_LIMITS.items():
        raw, scan = _read_bounded_file(_artifact(bundle, filename), maximum=maximum)
        _require_scan(scan, contracts[filename])
        if scan != first_scans[filename]:
            raise GenerationBundleError(_CHANGED_ERROR)
        static_raw[filename] = raw

    records, catalog_scan = _read_catalog_records(
        _artifact(bundle, "catalog-records.v1.jsonl"),
        contracts["catalog-records.v1.jsonl"],
        expected_variant_count=summary.variant_count,
    )
    if catalog_scan != first_scans["catalog-records.v1.jsonl"]:
        raise GenerationBundleError(_CHANGED_ERROR)

    products = _parse_part_manifest(
        static_raw["products-part-manifest.v1.json"], SnapshotPart.PRODUCTS
    )
    variants = _parse_part_manifest(
        static_raw["variants-part-manifest.v1.json"], SnapshotPart.VARIANTS
    )
    source_raw = static_raw["source-manifest.v2.json"]
    source = _parse_source_manifest(source_raw, products, variants)
    dataset = _parse_dataset_manifest(static_raw["dataset-manifest.v1.json"])
    report = _parse_taxonomy_report(static_raw["taxonomy-report.v1.json"], records)
    _cross_check_generation(
        summary=summary,
        source=source,
        source_raw=source_raw,
        dataset=dataset,
        report=report,
        records=records,
    )
    generation = ReconciledCatalogGenerationV1(
        source_manifest=source,
        source_manifest_bytes=source_raw,
        taxonomy_report=report,
        records=records,
        dataset_manifest=dataset,
        canonical_name_audit=summary.canonical_name_audit,
    )
    backend.verify(bundle)
    return VerifiedReconciledGenerationV1(
        generation=generation,
        summary_sha256=expected_summary_sha256,
    )


_WINDOWS_HANDLE_API_AVAILABLE = sys.platform == "win32"
_GENERIC_READ = 0x80000000
_FILE_LIST_DIRECTORY = 0x00000001
_FILE_READ_ATTRIBUTES = 0x00000080
_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_FILE_SHARE_DELETE = 0x00000004
_OPEN_EXISTING = 3
_FILE_ATTRIBUTE_NORMAL = 0x00000080
_FILE_FLAG_SEQUENTIAL_SCAN = 0x08000000
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_FILE_STREAM_INFO_CLASS = 7
_FILE_ID_INFO_CLASS = 18
_DRIVE_FIXED = 3
_VOLUME_NAME_GUID = 0x1
_VOLUME_NAME_BUFFER_CHARS = 32_768
_STREAM_INFO_INITIAL_BYTES = 4_096
_STREAM_INFO_MAX_BYTES = 1024 * 1024
_ERROR_INSUFFICIENT_BUFFER = 122
_ERROR_MORE_DATA = 234
_ERROR_HANDLE_EOF = 38
_O_BINARY = getattr(os, "O_BINARY", 0)
_WIN32_LAST_ERROR = getattr(ctypes, "get_last_error", lambda: 0)
_INVALID_NATIVE_HANDLE = ctypes.c_void_p(-1).value
_REPARSE_POINT_ATTRIBUTE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_FINAL_VOLUME_GUID_PATTERN = re.compile(
    r"^\\\\\?\\(Volume\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
    r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\})\\(.*)$"
)


def _windows_kernel32() -> Any:
    if not _WINDOWS_HANDLE_API_AVAILABLE:
        raise GenerationBundleError(_FILESYSTEM_ERROR)
    try:
        return ctypes.WinDLL("kernel32", use_last_error=True)
    except (AttributeError, OSError) as exc:
        raise GenerationBundleError(_FILESYSTEM_ERROR) from exc


def _windows_msvcrt() -> Any:
    if not _WINDOWS_HANDLE_API_AVAILABLE:
        raise GenerationBundleError(_FILESYSTEM_ERROR)
    try:
        import msvcrt
    except ImportError as exc:
        raise GenerationBundleError(_FILESYSTEM_ERROR) from exc
    return msvcrt


def _native_create_file(
    path: Path,
    *,
    access: int,
    share: int,
    flags: int,
) -> int:
    kernel32 = _windows_kernel32()
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    create_file.restype = wintypes.HANDLE
    owner = _OwnedNativeHandle()
    try:
        owner.raw_handle = int(create_file(os.fspath(path), access, share, None, _OPEN_EXISTING, flags, None))  # noqa: E501  # fmt: skip
        if owner.raw_handle == _INVALID_NATIVE_HANDLE:
            raise GenerationBundleError(_FILESYSTEM_ERROR)
        return owner.release()
    finally:
        if owner.raw_handle == _INVALID_NATIVE_HANDLE:
            owner.raw_handle = None
        owner.close()


def _native_close(raw_handle: int) -> None:
    kernel32 = _windows_kernel32()
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL
    if not close_handle(raw_handle):
        raise GenerationBundleError(_FILESYSTEM_ERROR)


@contextmanager
def _owned_native_handle(
    path: Path,
    *,
    access: int,
    share: int,
    flags: int,
) -> Iterator[_OwnedNativeHandle]:
    owner = _OwnedNativeHandle()
    try:
        owner.raw_handle = _native_create_file(path, access=access, share=share, flags=flags)
        yield owner
    finally:
        owner.close()


def _native_binary_file(path: Path) -> BinaryIO:
    resources = _OwnedNativeBinary()
    try:
        with _owned_native_handle(
            path,
            access=_GENERIC_READ,
            share=_FILE_SHARE_READ,
            flags=_FILE_ATTRIBUTE_NORMAL
            | _FILE_FLAG_OPEN_REPARSE_POINT
            | _FILE_FLAG_SEQUENTIAL_SCAN,
        ) as owner:
            try:
                resources.descriptor, owner.raw_handle = (_windows_msvcrt().open_osfhandle(owner.handle, _O_BINARY | os.O_RDONLY), None)  # noqa: E501  # fmt: skip
                resources.handle, resources.descriptor = ((opened_handle := os.fdopen(resources.descriptor, "rb", buffering=1024 * 1024)), None if opened_handle is not None else resources.descriptor)  # noqa: E501  # fmt: skip
            except Exception as exc:
                raise GenerationBundleError(_FILESYSTEM_ERROR) from exc
        return resources.release()
    finally:
        resources.close()


def _native_os_handle(handle: BinaryIO) -> int:
    try:
        return int(_windows_msvcrt().get_osfhandle(handle.fileno()))
    except (AttributeError, OSError, ValueError) as exc:
        raise GenerationBundleError(_FILESYSTEM_ERROR) from exc


def _parse_canonical_handle_path(value: str) -> _CanonicalHandlePath:
    match = _FINAL_VOLUME_GUID_PATTERN.fullmatch(value)
    if match is None or "/" in value or "\x00" in value:
        raise GenerationBundleError(_FILESYSTEM_ERROR)
    volume_guid, remainder = match.groups()
    components = () if not remainder else tuple(remainder.split("\\"))
    if any(
        not component
        or component in {".", ".."}
        or ":" in component
        or component.rstrip(" .") != component
        for component in components
    ):
        raise GenerationBundleError(_FILESYSTEM_ERROR)
    return _CanonicalHandlePath(
        volume_guid=volume_guid.lower(),
        components=components,
    )


def _native_handle_canonical_path(raw_handle: int) -> _CanonicalHandlePath:
    kernel32 = _windows_kernel32()
    get_final_path = kernel32.GetFinalPathNameByHandleW
    get_final_path.argtypes = (
        wintypes.HANDLE,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    )
    get_final_path.restype = wintypes.DWORD
    buffer = ctypes.create_unicode_buffer(_VOLUME_NAME_BUFFER_CHARS)
    result = int(get_final_path(raw_handle, buffer, len(buffer), _VOLUME_NAME_GUID))
    if result == 0 or result >= len(buffer):
        raise GenerationBundleError(_FILESYSTEM_ERROR)
    return _parse_canonical_handle_path(buffer.value)


def _native_handle_identity(raw_handle: int) -> _NativeFileIdentity:
    class _FileId128(ctypes.Structure):
        _fields_ = (("identifier", ctypes.c_ubyte * 16),)

    class _FileIdInfo(ctypes.Structure):
        _fields_ = (
            ("volume_serial_number", ctypes.c_uint64),
            ("file_id", _FileId128),
        )

    kernel32 = _windows_kernel32()
    get_information = kernel32.GetFileInformationByHandleEx
    get_information.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    )
    get_information.restype = wintypes.BOOL
    information = _FileIdInfo()
    if not get_information(
        raw_handle,
        _FILE_ID_INFO_CLASS,
        ctypes.byref(information),
        ctypes.sizeof(information),
    ):
        raise GenerationBundleError(_FILESYSTEM_ERROR)
    return _NativeFileIdentity(
        volume_serial_number=int(information.volume_serial_number),
        file_id=bytes(information.file_id.identifier),
    )


def _native_file_streams(
    raw_handle: int, *, directory: bool = False
) -> tuple[tuple[str, int], ...]:
    class _FileStreamInfo(ctypes.Structure):
        _fields_ = (
            ("next_entry_offset", ctypes.c_uint32),
            ("stream_name_length", ctypes.c_uint32),
            ("stream_size", ctypes.c_int64),
            ("stream_allocation_size", ctypes.c_int64),
        )

    kernel32 = _windows_kernel32()
    get_information = kernel32.GetFileInformationByHandleEx
    get_information.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    )
    get_information.restype = wintypes.BOOL
    size = _STREAM_INFO_INITIAL_BYTES
    while True:
        storage = ctypes.create_string_buffer(size + 7)
        aligned_address = (ctypes.addressof(storage) + 7) & ~7
        buffer = (ctypes.c_ubyte * size).from_address(aligned_address)
        if get_information(raw_handle, _FILE_STREAM_INFO_CLASS, buffer, size):
            break
        error_code = _WIN32_LAST_ERROR()
        if directory and error_code == _ERROR_HANDLE_EOF:
            return ()
        if error_code not in {_ERROR_INSUFFICIENT_BUFFER, _ERROR_MORE_DATA}:
            raise GenerationBundleError(_FILESYSTEM_ERROR)
        size *= 2
        if size > _STREAM_INFO_MAX_BYTES:
            raise GenerationBundleError(_FILESYSTEM_ERROR)

    header_size = ctypes.sizeof(_FileStreamInfo)
    offset = 0
    streams: list[tuple[str, int]] = []
    seen_names: set[str] = set()
    while True:
        if offset > size - header_size:
            raise GenerationBundleError(_FILESYSTEM_ERROR)
        header = _FileStreamInfo.from_buffer_copy(buffer, offset)
        name_length = int(header.stream_name_length)
        name_start = offset + header_size
        name_end = name_start + name_length
        if name_length == 0 or name_length % 2 or name_end > size:
            raise GenerationBundleError(_FILESYSTEM_ERROR)
        try:
            name = bytes(buffer[name_start:name_end]).decode("utf-16-le", errors="strict")
        except UnicodeDecodeError as exc:
            raise GenerationBundleError(_FILESYSTEM_ERROR) from exc
        folded_name = name.casefold()
        if (
            "\x00" in name
            or folded_name in seen_names
            or int(header.stream_size) < 0
            or int(header.stream_allocation_size) < 0
        ):
            raise GenerationBundleError(_FILESYSTEM_ERROR)
        seen_names.add(folded_name)
        streams.append((name, int(header.stream_size)))
        next_offset = int(header.next_entry_offset)
        if next_offset == 0:
            return tuple(streams)
        if (
            next_offset % 8
            or next_offset < header_size + name_length
            or next_offset > size - offset
        ):
            raise GenerationBundleError(_FILESYSTEM_ERROR)
        offset += next_offset


def _require_unnamed_stream(raw_handle: int, expected_size: int) -> None:
    if _native_file_streams(raw_handle) != (("::$DATA", expected_size),):
        raise GenerationBundleError(_FILESYSTEM_ERROR)


def _require_no_directory_streams(raw_handle: int) -> None:
    if _native_file_streams(raw_handle, directory=True):
        raise GenerationBundleError(_FILESYSTEM_ERROR)


def _require_local_ntfs(path: Path) -> None:
    kernel32 = _windows_kernel32()
    volume_path = ctypes.create_unicode_buffer(_VOLUME_NAME_BUFFER_CHARS)
    get_volume_path = kernel32.GetVolumePathNameW
    get_volume_path.argtypes = (wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD)
    get_volume_path.restype = wintypes.BOOL
    if not get_volume_path(os.fspath(path), volume_path, len(volume_path)):
        raise GenerationBundleError(_FILESYSTEM_ERROR)

    get_drive_type = kernel32.GetDriveTypeW
    get_drive_type.argtypes = (wintypes.LPCWSTR,)
    get_drive_type.restype = wintypes.UINT
    if get_drive_type(volume_path.value) != _DRIVE_FIXED:
        raise GenerationBundleError(_FILESYSTEM_ERROR)

    filesystem_name = ctypes.create_unicode_buffer(_VOLUME_NAME_BUFFER_CHARS)
    get_volume_information = kernel32.GetVolumeInformationW
    get_volume_information.argtypes = (
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.LPDWORD,
        wintypes.LPDWORD,
        wintypes.LPDWORD,
        wintypes.LPWSTR,
        wintypes.DWORD,
    )
    get_volume_information.restype = wintypes.BOOL
    if (
        not get_volume_information(
            volume_path.value,
            None,
            0,
            None,
            None,
            None,
            filesystem_name,
            len(filesystem_name),
        )
        or filesystem_name.value.upper() != "NTFS"
    ):
        raise GenerationBundleError(_FILESYSTEM_ERROR)


def _require_local_ntfs_volume(canonical_path: _CanonicalHandlePath) -> None:
    if (
        re.fullmatch(
            r"volume\{[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
            r"[0-9a-f]{4}-[0-9a-f]{12}\}",
            canonical_path.volume_guid,
        )
        is None
    ):
        raise GenerationBundleError(_FILESYSTEM_ERROR)
    volume_root = f"\\\\?\\{canonical_path.volume_guid}\\"
    kernel32 = _windows_kernel32()
    get_drive_type = kernel32.GetDriveTypeW
    get_drive_type.argtypes = (wintypes.LPCWSTR,)
    get_drive_type.restype = wintypes.UINT
    if get_drive_type(volume_root) != _DRIVE_FIXED:
        raise GenerationBundleError(_FILESYSTEM_ERROR)

    filesystem_name = ctypes.create_unicode_buffer(_VOLUME_NAME_BUFFER_CHARS)
    get_volume_information = kernel32.GetVolumeInformationW
    get_volume_information.argtypes = (
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.LPDWORD,
        wintypes.LPDWORD,
        wintypes.LPDWORD,
        wintypes.LPWSTR,
        wintypes.DWORD,
    )
    get_volume_information.restype = wintypes.BOOL
    if (
        not get_volume_information(
            volume_root,
            None,
            0,
            None,
            None,
            None,
            filesystem_name,
            len(filesystem_name),
        )
        or filesystem_name.value.upper() != "NTFS"
    ):
        raise GenerationBundleError(_FILESYSTEM_ERROR)


def _require_fixed_drive_anchor(path: Path) -> None:
    anchor = path.anchor
    if re.fullmatch(r"[a-z]:\\", anchor, re.IGNORECASE) is None:
        raise GenerationBundleError(_FILESYSTEM_ERROR)
    kernel32 = _windows_kernel32()
    get_drive_type = kernel32.GetDriveTypeW
    get_drive_type.argtypes = (wintypes.LPCWSTR,)
    get_drive_type.restype = wintypes.UINT
    if get_drive_type(anchor) != _DRIVE_FIXED:
        raise GenerationBundleError(_FILESYSTEM_ERROR)


def _canonical_child(parent: _CanonicalHandlePath, name: str) -> _CanonicalHandlePath:
    if (
        not name
        or name in {".", ".."}
        or "\\" in name
        or "/" in name
        or ":" in name
        or name.rstrip(" .") != name
    ):
        raise GenerationBundleError(_FILESYSTEM_ERROR)
    return _CanonicalHandlePath(parent.volume_guid, (*parent.components, name))


def _canonical_paths_equal(left: _CanonicalHandlePath, right: _CanonicalHandlePath) -> bool:
    return left == right


def _canonical_is_within(candidate: _CanonicalHandlePath, parent: _CanonicalHandlePath) -> bool:
    return (
        candidate.volume_guid == parent.volume_guid
        and len(candidate.components) >= len(parent.components)
        and candidate.components[: len(parent.components)] == parent.components
    )


def _native_path_canonical_path(path: Path, *, directory: bool) -> _CanonicalHandlePath:
    with _owned_native_handle(
        path,
        access=_FILE_READ_ATTRIBUTES,
        share=_FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE,
        flags=_FILE_FLAG_OPEN_REPARSE_POINT
        | (_FILE_FLAG_BACKUP_SEMANTICS if directory else _FILE_ATTRIBUTE_NORMAL),
    ) as owner:
        return _native_handle_canonical_path(owner.handle)


def _native_path_attestation(
    path: Path, *, directory: bool
) -> tuple[_NativeFileIdentity, _CanonicalHandlePath]:
    with _owned_native_handle(
        path,
        access=_FILE_READ_ATTRIBUTES,
        share=_FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE,
        flags=_FILE_FLAG_OPEN_REPARSE_POINT
        | (_FILE_FLAG_BACKUP_SEMANTICS if directory else _FILE_ATTRIBUTE_NORMAL),
    ) as owner:
        return (
            _native_handle_identity(owner.handle),
            _native_handle_canonical_path(owner.handle),
        )


def _expected_canonical_drive_path(path: Path) -> _CanonicalHandlePath:
    root = _native_path_canonical_path(Path(path.anchor), directory=True)
    if root.components:
        raise GenerationBundleError(_FILESYSTEM_ERROR)
    expected = root
    for component in path.parts[1:]:
        expected = _canonical_child(expected, component)
    return expected


def _repository_canonical_path() -> _CanonicalHandlePath:
    return _native_path_canonical_path(REPOSITORY_ROOT, directory=True)


def _path_has_alias(path: Path) -> bool:
    parts = path.parts
    if not parts or not path.anchor or parts[0] != path.anchor:
        raise GenerationBundleError(_FILESYSTEM_ERROR)
    current = Path(path.anchor)
    for index, part in enumerate(parts):
        if index:
            current /= part
        try:
            facts = current.lstat()
            attributes = getattr(facts, "st_file_attributes", 0)
            if attributes & _REPARSE_POINT_ATTRIBUTE or stat.S_ISLNK(facts.st_mode):
                return True
        except OSError as exc:
            raise GenerationBundleError(_FILESYSTEM_ERROR) from exc
    return False


def _require_supported_namespace(path: Path) -> None:
    raw = os.fspath(path)
    folded = raw.casefold()
    if (
        folded.startswith("\\\\?\\")
        or folded.startswith("\\\\.\\")
        or folded.startswith("\\??\\")
        or folded.startswith("\\\\")
    ):
        raise GenerationBundleError(_FILESYSTEM_ERROR)
    if _WINDOWS_HANDLE_API_AVAILABLE and re.match(r"^[a-z]:\\", raw, re.IGNORECASE) is None:
        raise GenerationBundleError(_FILESYSTEM_ERROR)


def _has_unsafe_path_component(path: Path) -> bool:
    return any(
        part != path.anchor and (":" in part or (part and part.rstrip(" .") != part))
        for part in path.parts
    )


def _normalized_path_spelling(path: Path) -> str:
    return os.path.normpath(os.fspath(path)).replace("/", "\\")


def _validated_directory_argument(value: object) -> Path:
    if type(value) is not _CONCRETE_PATH_TYPE:
        raise GenerationBundleError(_FILESYSTEM_ERROR)
    path = value
    _require_supported_namespace(path)
    if (
        not path.is_absolute()
        or any(part == ".." for part in path.parts)
        or _has_unsafe_path_component(path)
    ):
        raise GenerationBundleError(_FILESYSTEM_ERROR)
    return path


def _path_file_state(path: Path) -> _FileState:
    try:
        facts = path.lstat()
    except OSError as exc:
        raise GenerationBundleError(_FILESYSTEM_ERROR) from exc
    if not stat.S_ISREG(facts.st_mode) or facts.st_nlink != 1:
        raise GenerationBundleError(_FILESYSTEM_ERROR)
    return _FileState(
        identity=_FileIdentity(facts.st_dev, facts.st_ino),
        byte_count=facts.st_size,
        modified_ns=facts.st_mtime_ns,
    )


def _directory_identity(path: Path) -> _FileIdentity:
    try:
        facts = path.lstat()
    except OSError as exc:
        raise GenerationBundleError(_FILESYSTEM_ERROR) from exc
    if not stat.S_ISDIR(facts.st_mode):
        raise GenerationBundleError(_FILESYSTEM_ERROR)
    return _FileIdentity(facts.st_dev, facts.st_ino)


def _directory_names(path: Path) -> tuple[str, ...]:
    names: list[str] = []
    try:
        with os.scandir(path) as entries:
            for entry in entries:
                names.append(entry.name)
                if len(names) > len(_OUTPUT_FILENAMES):
                    raise GenerationBundleError(_SHAPE_ERROR)
    except GenerationBundleError:
        raise
    except OSError as exc:
        raise GenerationBundleError(_FILESYSTEM_ERROR) from exc
    return tuple(names)


class _Win32FilesystemBackend:
    @contextmanager
    def open(self, directory: Path) -> Iterator[_PinnedBundle]:
        if not _WINDOWS_HANDLE_API_AVAILABLE:
            raise GenerationBundleError(_FILESYSTEM_ERROR)
        _require_fixed_drive_anchor(directory)
        if _path_has_alias(directory):
            raise GenerationBundleError(_FILESYSTEM_ERROR)
        try:
            resolved = directory.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise GenerationBundleError(_FILESYSTEM_ERROR) from exc
        if _normalized_path_spelling(directory) != _normalized_path_spelling(
            resolved
        ) or _path_has_alias(resolved):
            raise GenerationBundleError(_FILESYSTEM_ERROR)
        directory_identity = _directory_identity(resolved)
        expected_canonical_path = _expected_canonical_drive_path(resolved)

        with (
            _owned_native_handle(
                resolved,
                access=_FILE_LIST_DIRECTORY | _FILE_READ_ATTRIBUTES,
                share=_FILE_SHARE_READ,
                flags=_FILE_FLAG_BACKUP_SEMANTICS | _FILE_FLAG_OPEN_REPARSE_POINT,
            ) as directory_owner,
            ExitStack() as stack,
        ):
            directory_handle = directory_owner.handle
            canonical_path = _native_handle_canonical_path(directory_handle)
            directory_native_identity = _native_handle_identity(directory_handle)
            path_native_identity, path_canonical = _native_path_attestation(
                resolved, directory=True
            )
            if (
                path_native_identity != directory_native_identity
                or not _canonical_paths_equal(path_canonical, canonical_path)
                or not _canonical_paths_equal(canonical_path, expected_canonical_path)
                or _directory_identity(resolved) != directory_identity
                or _canonical_is_within(canonical_path, _repository_canonical_path())
            ):
                raise GenerationBundleError(_FILESYSTEM_ERROR)
            _require_local_ntfs_volume(canonical_path)
            _require_no_directory_streams(directory_handle)
            names = _directory_names(resolved)
            if len(names) != len(_OUTPUT_FILENAMES) or frozenset(names) != _OUTPUT_FILENAMES:
                raise GenerationBundleError(_SHAPE_ERROR)

            pinned: dict[str, _PinnedArtifact] = {}
            identities: set[_FileIdentity] = set()
            for filename in (_SUMMARY_FILENAME, *_ARTIFACT_FILENAMES):
                path = resolved / filename
                if _path_has_alias(path):
                    raise GenerationBundleError(_FILESYSTEM_ERROR)
                before = _path_file_state(path)
                handle = stack.enter_context(_native_binary_file(path))
                state = _handle_state(handle)
                raw_handle = _native_os_handle(handle)
                file_canonical_path = _native_handle_canonical_path(raw_handle)
                if (
                    state != before
                    or not _canonical_paths_equal(
                        file_canonical_path, _canonical_child(canonical_path, filename)
                    )
                    or state.identity in identities
                ):
                    raise GenerationBundleError(_FILESYSTEM_ERROR)
                _require_unnamed_stream(raw_handle, state.byte_count)
                identities.add(state.identity)
                pinned[filename] = _PinnedArtifact(
                    filename=filename,
                    path=path,
                    handle=handle,
                    state=state,
                    canonical_path=file_canonical_path,
                )

            bundle = _PinnedBundle(
                directory=resolved,
                directory_identity=directory_identity,
                directory_handle=directory_handle,
                canonical_path=canonical_path,
                files=MappingProxyType(pinned),
                directory_native_identity=directory_native_identity,
            )
            self.verify(bundle)
            yield bundle

    def verify(self, bundle: _PinnedBundle) -> None:
        if type(bundle) is not _PinnedBundle:
            raise GenerationBundleError(_FILESYSTEM_ERROR)
        _require_fixed_drive_anchor(bundle.directory)
        current_canonical = _native_handle_canonical_path(bundle.directory_handle)
        current_native_identity = _native_handle_identity(bundle.directory_handle)
        path_native_identity, path_canonical = _native_path_attestation(
            bundle.directory, directory=True
        )
        expected_canonical_path = _expected_canonical_drive_path(bundle.directory)
        if (
            type(bundle.directory_native_identity) is not _NativeFileIdentity
            or not _canonical_paths_equal(current_canonical, expected_canonical_path)
            or _path_has_alias(bundle.directory)
            or _directory_identity(bundle.directory) != bundle.directory_identity
            or current_native_identity != bundle.directory_native_identity
            or path_native_identity != bundle.directory_native_identity
            or not _canonical_paths_equal(current_canonical, bundle.canonical_path)
            or not _canonical_paths_equal(path_canonical, bundle.canonical_path)
            or _canonical_is_within(bundle.canonical_path, _repository_canonical_path())
        ):
            raise GenerationBundleError(_CHANGED_ERROR)
        _require_local_ntfs_volume(current_canonical)
        _require_no_directory_streams(bundle.directory_handle)
        names = _directory_names(bundle.directory)
        if len(names) != len(_OUTPUT_FILENAMES) or frozenset(names) != _OUTPUT_FILENAMES:
            raise GenerationBundleError(_SHAPE_ERROR)
        if frozenset(bundle.files) != _OUTPUT_FILENAMES or len(bundle.files) != len(
            _OUTPUT_FILENAMES
        ):
            raise GenerationBundleError(_SHAPE_ERROR)

        identities: set[_FileIdentity] = set()
        for filename in (_SUMMARY_FILENAME, *_ARTIFACT_FILENAMES):
            artifact = _artifact(bundle, filename)
            if _path_has_alias(artifact.path):
                raise GenerationBundleError(_CHANGED_ERROR)
            _require_pinned_state(artifact)
            raw_handle = _native_os_handle(artifact.handle)
            if (
                _path_file_state(artifact.path) != artifact.state
                or not _canonical_paths_equal(
                    _native_handle_canonical_path(raw_handle), artifact.canonical_path
                )
                or not _canonical_paths_equal(
                    artifact.canonical_path,
                    _canonical_child(bundle.canonical_path, filename),
                )
                or artifact.state.identity in identities
            ):
                raise GenerationBundleError(_CHANGED_ERROR)
            _require_unnamed_stream(raw_handle, artifact.state.byte_count)
            identities.add(artifact.state.identity)


_LINUX_HANDLE_API_AVAILABLE = sys.platform == "linux"


def _linux_state(facts: os.stat_result) -> tuple[int, ...]:
    # Exclude access time: verification itself reads every artifact twice.
    return (
        facts.st_dev,
        facts.st_ino,
        facts.st_mode,
        facts.st_nlink,
        facts.st_uid,
        facts.st_gid,
        facts.st_size,
        facts.st_mtime_ns,
        facts.st_ctime_ns,
    )


@contextmanager
def _linux_descriptor(name: str, flags: int, parent: int | None = None) -> Iterator[int]:
    descriptor: int | None = None
    try:
        descriptor = os.open(name, flags, dir_fd=parent)
        yield descriptor
    finally:
        if descriptor is not None:
            os.close(descriptor)


@contextmanager
def _linux_directory(directory: Path) -> Iterator[int]:
    """Walk from / using pinned descriptors; never follow an ancestor symlink."""
    if (
        not _LINUX_HANDLE_API_AVAILABLE
        or directory.anchor != "/"
        or ".." in directory.parts
        or directory == REPOSITORY_ROOT
        or directory.is_relative_to(REPOSITORY_ROOT)
    ):
        raise GenerationBundleError(_FILESYSTEM_ERROR)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    with ExitStack() as stack:
        descriptor = stack.enter_context(_linux_descriptor("/", flags))
        for component in directory.parts[1:]:
            descriptor = stack.enter_context(_linux_descriptor(component, flags, descriptor))
        yield descriptor


def _linux_names(descriptor: int) -> None:
    names: list[str] = []
    with os.scandir(descriptor) as entries:
        for entry in entries:
            names.append(entry.name)
            if len(names) > len(_OUTPUT_FILENAMES):
                raise GenerationBundleError(_SHAPE_ERROR)
    if frozenset(names) != _OUTPUT_FILENAMES:
        raise GenerationBundleError(_SHAPE_ERROR)


class _LinuxFilesystemBackend:
    """Read operator-sealed bundles using Linux descriptors and existing hashes.

    Files and their directory must have no write bits. This is not a lock against
    their owner or root: metadata (including ctime) and the external digest are
    checked before returning detached records. No Windows attestation is faked.
    """

    @contextmanager
    def open(self, directory: Path) -> Iterator[_PinnedBundle]:
        with _linux_directory(directory) as descriptor, ExitStack() as stack:
            facts = os.fstat(descriptor)
            if facts.st_mode & 0o222:
                raise GenerationBundleError(_FILESYSTEM_ERROR)
            _linux_names(descriptor)
            pinned: dict[str, _PinnedArtifact] = {}
            identities: set[_FileIdentity] = set()
            for filename in (_SUMMARY_FILENAME, *_ARTIFACT_FILENAMES):
                before = os.stat(filename, dir_fd=descriptor, follow_symlinks=False)
                if (
                    not stat.S_ISREG(before.st_mode)
                    or before.st_nlink != 1
                    or before.st_mode & 0o222
                ):
                    raise GenerationBundleError(_FILESYSTEM_ERROR)
                raw = stack.enter_context(
                    _linux_descriptor(
                        filename,
                        os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                        descriptor,
                    )
                )
                handle = stack.enter_context(os.fdopen(raw, "rb", closefd=False))
                opened = os.fstat(raw)
                state = _handle_state(handle)
                if _linux_state(opened) != _linux_state(before) or state.identity in identities:
                    raise GenerationBundleError(_CHANGED_ERROR)
                identities.add(state.identity)
                pinned[filename] = _PinnedArtifact(
                    filename=filename,
                    path=directory / filename,
                    handle=handle,
                    state=state,
                    canonical_path=directory / filename,
                    linux_state=_linux_state(opened),
                )
            bundle = _PinnedBundle(
                directory=directory,
                directory_identity=_FileIdentity(facts.st_dev, facts.st_ino),
                directory_handle=descriptor,
                canonical_path=directory,
                files=MappingProxyType(pinned),
                linux_state=_linux_state(facts),
            )
            self.verify(bundle)
            yield bundle

    def verify(self, bundle: _PinnedBundle) -> None:
        with _linux_directory(bundle.directory) as current:
            if (
                bundle.linux_state is None
                or _linux_state(os.fstat(current)) != bundle.linux_state
                or _linux_state(os.fstat(bundle.directory_handle)) != bundle.linux_state
            ):
                raise GenerationBundleError(_CHANGED_ERROR)
        _linux_names(bundle.directory_handle)
        if frozenset(bundle.files) != _OUTPUT_FILENAMES:
            raise GenerationBundleError(_SHAPE_ERROR)
        for filename in (_SUMMARY_FILENAME, *_ARTIFACT_FILENAMES):
            artifact = _artifact(bundle, filename)
            facts = os.stat(filename, dir_fd=bundle.directory_handle, follow_symlinks=False)
            if (
                artifact.linux_state is None
                or _linux_state(facts) != artifact.linux_state
                or _linux_state(os.fstat(artifact.handle.fileno())) != artifact.linux_state
            ):
                raise GenerationBundleError(_CHANGED_ERROR)


def _filesystem_backend() -> _BundleFilesystemBackend:
    """Return the production backend; tests may monkeypatch this private seam."""

    if _WINDOWS_HANDLE_API_AVAILABLE:
        return _Win32FilesystemBackend()
    if _LINUX_HANDLE_API_AVAILABLE:
        return _LinuxFilesystemBackend()
    raise GenerationBundleError(_FILESYSTEM_ERROR)


def _public_error_message(value: GenerationBundleError, *, default: str) -> str:
    if (
        type(value) is GenerationBundleError
        and len(value.args) == 1
        and type(value.args[0]) is str
        and value.args[0] in _PUBLIC_ERRORS
    ):
        return value.args[0]
    return default


def _raise_boundary_failure(value: BaseException, *, default: str) -> None:
    if isinstance(value, GenerationBundleError):
        raise GenerationBundleError(_public_error_message(value, default=default))
    if isinstance(value, Exception):
        raise GenerationBundleError(default)
    raise value.with_traceback(value.__traceback__)


@contextmanager
def _tracked_pinned_context(
    inner: AbstractContextManager[_PinnedBundle],
    lifecycle: _PinnedContextLifecycle,
) -> Iterator[_PinnedBundle]:
    entered = False
    body_failure: BaseException | None = None
    try:
        with inner as bundle:
            entered = True
            try:
                yield bundle
            except BaseException as exc:
                body_failure = exc
                lifecycle.body_failure = exc
                raise
    except BaseException as exc:
        if not entered:
            lifecycle.enter_failure = exc
        elif body_failure is None or exc is not body_failure:
            lifecycle.exit_failure = exc
        raise


@contextmanager
def open_reconciled_generation(
    directory: Path,
    expected_summary_sha256: str,
) -> Iterator[VerifiedReconciledGenerationV1]:
    """Open and independently verify one exact external provisional generation.

    The separately supplied summary digest is the sole trust root.  All carrier
    handles remain pinned for the lifetime of the context manager.
    """

    path_failure: BaseException | None = None
    try:
        path = _validated_directory_argument(directory)
    except BaseException as exc:
        path_failure = exc
    if path_failure is not None:
        _raise_boundary_failure(path_failure, default=_FILESYSTEM_ERROR)
    if (
        type(expected_summary_sha256) is not str
        or _SHA256_PATTERN.fullmatch(expected_summary_sha256) is None
    ):
        raise GenerationBundleError(_TRUST_ERROR)
    trust_root = expected_summary_sha256

    factory_failure: BaseException | None = None
    try:
        backend = _filesystem_backend()
    except BaseException as exc:
        factory_failure = exc
    if factory_failure is not None:
        _raise_boundary_failure(factory_failure, default=_FILESYSTEM_ERROR)

    open_failure: BaseException | None = None
    try:
        pinned_context = backend.open(path)
    except BaseException as exc:
        open_failure = exc
    if open_failure is not None:
        _raise_boundary_failure(open_failure, default=_FILESYSTEM_ERROR)

    lifecycle = _PinnedContextLifecycle()
    escaped_failure: BaseException | None = None
    escaped_traceback = None
    prepare_failure: BaseException | None = None
    verified: VerifiedReconciledGenerationV1 | None = None
    try:
        with _tracked_pinned_context(pinned_context, lifecycle) as bundle:
            try:
                verified = _prepare_verified_generation(bundle, trust_root, backend)
            except BaseException as exc:
                prepare_failure = exc
            if prepare_failure is None:
                yield cast(VerifiedReconciledGenerationV1, verified)
    except BaseException as exc:
        escaped_failure = exc
        escaped_traceback = exc.__traceback__

    if lifecycle.exit_failure is not None:
        _raise_boundary_failure(lifecycle.exit_failure, default=_FILESYSTEM_ERROR)
    if lifecycle.enter_failure is not None:
        _raise_boundary_failure(lifecycle.enter_failure, default=_FILESYSTEM_ERROR)
    if escaped_failure is not None:
        raise escaped_failure.with_traceback(escaped_traceback)
    if prepare_failure is not None:
        _raise_boundary_failure(prepare_failure, default=_CONTENT_ERROR)


__all__ = (
    "GenerationBundleError",
    "VerifiedReconciledGenerationV1",
    "open_reconciled_generation",
)
