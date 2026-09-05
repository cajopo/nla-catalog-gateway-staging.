"""Deterministic reconciliation for split read-only Shopify Bulk snapshots.

The module consumes already-downloaded JSONL files.  It never calls Shopify and
never persists source data in the repository.  Both snapshot parts are fully
validated and joined in a private temporary SQLite database before taxonomy or
runtime DTO construction is allowed to begin.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import stat
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, BinaryIO, ClassVar, Final

from nla_catalog_gateway import bulk
from nla_catalog_gateway import runtime_contract as runtime
from nla_catalog_gateway.taxonomy import (
    Classification,
    ClassificationReport,
    ProductFacts,
    ProductFamily,
    TaxonomyConfig,
    classify_catalog,
)

PART_MANIFEST_SCHEMA_VERSION: Final = 1
RECONCILED_MANIFEST_SCHEMA_VERSION: Final = 2
MAX_PART_MANIFEST_BYTES: Final = 64 * 1024
MAX_RECONCILED_MANIFEST_BYTES: Final = 64 * 1024
SINGLE_LINE_TEXT_TYPE: Final = "single_line_text_field"
MAX_BULK_QUERY_BYTES: Final = 256 * 1024
CAPTURE_FENCE_MAX_SECONDS: Final = 24 * 60 * 60

NLA_GAME_KEY: Final = "game"
NLA_SOURCE_RECORD_TYPE_KEY: Final = "source_record_type"
NLA_CANONICAL_CARD_NAME_KEY: Final = "canonical_card_name"


class ReconciliationError(ValueError):
    """Base class for bounded split-snapshot failures."""


class ReconciliationContractError(ReconciliationError):
    """Trusted orchestration input does not satisfy the frozen contract."""


class ReconciliationDataError(ReconciliationError):
    """Downloaded source parts do not form one complete generation."""


class SnapshotPart(StrEnum):
    PRODUCTS = "products"
    VARIANTS = "variants"


_PART_TYPES: Final = {
    SnapshotPart.PRODUCTS: ("Metafield", "Product", "ResourcePublicationV2"),
    SnapshotPart.VARIANTS: ("InventoryLevel", "Metafield", "ProductVariant"),
}
_ROOT_TYPE: Final = {
    SnapshotPart.PRODUCTS: "Product",
    SnapshotPart.VARIANTS: "ProductVariant",
}
_GENERATION_PATTERN: Final = re.compile(r"sha256:[0-9a-f]{64}\Z")
_CONCRETE_PATH_TYPE: Final = type(Path())
_APPROVED_QUERY_SHA256: Final = {
    SnapshotPart.PRODUCTS: "950e1bb757c01d40591437a8b0e5ddbed4476ad8eea39520d0d824b4bfba903a",
    SnapshotPart.VARIANTS: "b90f9bf4a691df66a1df8ef0e59aa21f7c23664a09d85d474b30099451f3fda4",
}


def _canonical_json_bytes(value: Any, *, context: str, limit: int) -> bytes:
    try:
        rendered = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except Exception as exc:
        raise ReconciliationContractError(f"{context} is not canonically serializable") from exc
    if len(rendered) > limit:
        raise ReconciliationContractError(f"{context} exceeds the byte bound")
    return rendered


def _digest_object(value: Any, *, domain: str) -> str:
    raw = _canonical_json_bytes(
        {"domain": domain, "value": value},
        context="generation descriptor",
        limit=MAX_RECONCILED_MANIFEST_BYTES,
    )
    return hashlib.sha256(raw).hexdigest()


def _validated_count(value: object, context: str, *, positive: bool = False) -> int:
    minimum = 1 if positive else 0
    if type(value) is not int or not minimum <= value < 2**63:
        qualifier = "positive" if positive else "non-negative"
        raise ReconciliationContractError(f"{context} must be a {qualifier} signed 64-bit integer")
    return value


def _canonical_timestamp(value: object, context: str) -> tuple[str, datetime]:
    if type(value) is not str:
        raise ReconciliationContractError(f"{context} is not a canonical timestamp")
    try:
        validated = bulk._timestamp({"value": value}, "value", context)
    except bulk.BulkContractError as exc:
        raise ReconciliationContractError(f"{context} is not a canonical timestamp") from exc
    if validated.endswith("-00:00"):
        raise ReconciliationContractError(f"{context} has an unknown timezone offset")
    try:
        parsed = datetime.fromisoformat(validated.replace("Z", "+00:00")).astimezone(UTC)
    except (OverflowError, ValueError) as exc:
        raise ReconciliationContractError(f"{context} cannot be normalized to UTC") from exc
    canonical = parsed.isoformat(timespec="microseconds").replace(".000000+00:00", "Z")
    if canonical.endswith("+00:00"):
        canonical = canonical.removesuffix("+00:00") + "Z"
    return canonical, parsed


def _validated_timestamp(value: object, context: str) -> str:
    return _canonical_timestamp(value, context)[0]


def _validated_gid(value: object, kind: str, context: str) -> str:
    if type(value) is not str:
        raise ReconciliationContractError(f"{context} is not a canonical {kind} GID")
    try:
        return bulk._gid_value(value, kind, context)
    except bulk.BulkContractError as exc:
        raise ReconciliationContractError(f"{context} is not a canonical {kind} GID") from exc


@dataclass(frozen=True, slots=True)
class ReconciliationExpectationV1:
    """Trusted, independently supplied identity and count fence for one capture."""

    snapshot_set_id: str
    shop_domain: str
    api_version: str
    online_store_publication_gid: str
    source_code_sha: str
    product_count: int
    variant_count: int
    expected_active_online_store_published_product_count: int

    def __post_init__(self) -> None:
        if (
            type(self.snapshot_set_id) is not str
            or _GENERATION_PATTERN.fullmatch(self.snapshot_set_id) is None
        ):
            raise ReconciliationContractError("snapshotSetId is invalid")
        if (
            type(self.shop_domain) is not str
            or bulk.SHOP_DOMAIN_PATTERN.fullmatch(self.shop_domain) is None
        ):
            raise ReconciliationContractError("shopDomain is invalid")
        if (
            type(self.api_version) is not str
            or bulk.API_VERSION_PATTERN.fullmatch(self.api_version) is None
        ):
            raise ReconciliationContractError("apiVersion is invalid")
        _validated_gid(
            self.online_store_publication_gid,
            "Publication",
            "onlineStorePublicationGid",
        )
        if (
            type(self.source_code_sha) is not str
            or bulk.COMMIT_SHA_PATTERN.fullmatch(self.source_code_sha) is None
        ):
            raise ReconciliationContractError("sourceCodeSha is invalid")
        _validated_count(self.product_count, "productCount", positive=True)
        _validated_count(self.variant_count, "variantCount", positive=True)
        _validated_count(
            self.expected_active_online_store_published_product_count,
            "expectedActiveOnlineStorePublishedProductCount",
        )
        if self.variant_count < self.product_count:
            raise ReconciliationContractError("variantCount cannot be less than productCount")
        if self.expected_active_online_store_published_product_count > self.product_count:
            raise ReconciliationContractError(
                "expected active published Product count cannot exceed productCount"
            )


def _validated_expectation(value: object) -> ReconciliationExpectationV1:
    if type(value) is not ReconciliationExpectationV1:
        raise ReconciliationContractError("expectation must be ReconciliationExpectationV1")
    try:
        return ReconciliationExpectationV1(
            snapshot_set_id=value.snapshot_set_id,
            shop_domain=value.shop_domain,
            api_version=value.api_version,
            online_store_publication_gid=value.online_store_publication_gid,
            source_code_sha=value.source_code_sha,
            product_count=value.product_count,
            variant_count=value.variant_count,
            expected_active_online_store_published_product_count=(
                value.expected_active_online_store_published_product_count
            ),
        )
    except ReconciliationContractError:
        raise
    except Exception as exc:
        raise ReconciliationContractError("expectation is invalid") from exc


@dataclass(frozen=True, slots=True)
class BulkOperationTerminalEvidenceV1:
    """Canonical terminal fields returned by one Shopify BulkOperation query."""

    operation_id: str
    operation_type: str
    status: str
    error_code: None
    query: str
    created_at: str
    completed_at: str
    file_size: int
    object_count: int
    root_object_count: int
    url_present: bool
    partial_data_url_present: bool

    def __post_init__(self) -> None:
        _validated_gid(self.operation_id, "BulkOperation", "BulkOperation.id")
        if type(self.operation_type) is not str or self.operation_type != "QUERY":
            raise ReconciliationContractError("BulkOperation.type must be QUERY")
        if type(self.status) is not str or self.status != "COMPLETED":
            raise ReconciliationContractError("BulkOperation.status must be COMPLETED")
        if self.error_code is not None:
            raise ReconciliationContractError("BulkOperation.errorCode must be null")
        if type(self.query) is not str or not self.query:
            raise ReconciliationContractError("BulkOperation.query must be non-empty text")
        try:
            query_bytes = self.query.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ReconciliationContractError("BulkOperation.query is not UTF-8 encodable") from exc
        if len(query_bytes) > MAX_BULK_QUERY_BYTES:
            raise ReconciliationContractError("BulkOperation.query exceeds the byte bound")
        created_at, created = _canonical_timestamp(self.created_at, "BulkOperation.createdAt")
        completed_at, completed = _canonical_timestamp(
            self.completed_at, "BulkOperation.completedAt"
        )
        if completed < created:
            raise ReconciliationContractError("BulkOperation.completedAt precedes createdAt")
        if completed - created > timedelta(seconds=CAPTURE_FENCE_MAX_SECONDS):
            raise ReconciliationContractError("BulkOperation exceeds the capture window")
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "completed_at", completed_at)
        _validated_count(self.file_size, "BulkOperation.fileSize", positive=True)
        _validated_count(self.object_count, "BulkOperation.objectCount", positive=True)
        _validated_count(self.root_object_count, "BulkOperation.rootObjectCount", positive=True)
        if self.root_object_count > self.object_count:
            raise ReconciliationContractError(
                "BulkOperation.rootObjectCount cannot exceed objectCount"
            )
        if type(self.url_present) is not bool or not self.url_present:
            raise ReconciliationContractError("completed BulkOperation.url must be present")
        if type(self.partial_data_url_present) is not bool:
            raise ReconciliationContractError("BulkOperation.partialDataUrl flag must be boolean")
        if self.partial_data_url_present:
            raise ReconciliationContractError("partial BulkOperation data is not acceptable")


def _validated_terminal_evidence(value: object) -> BulkOperationTerminalEvidenceV1:
    if type(value) is not BulkOperationTerminalEvidenceV1:
        raise ReconciliationContractError(
            "terminal evidence must be BulkOperationTerminalEvidenceV1"
        )
    try:
        return BulkOperationTerminalEvidenceV1(
            operation_id=value.operation_id,
            operation_type=value.operation_type,
            status=value.status,
            error_code=value.error_code,
            query=value.query,
            created_at=value.created_at,
            completed_at=value.completed_at,
            file_size=value.file_size,
            object_count=value.object_count,
            root_object_count=value.root_object_count,
            url_present=value.url_present,
            partial_data_url_present=value.partial_data_url_present,
        )
    except ReconciliationContractError:
        raise
    except Exception as exc:
        raise ReconciliationContractError("BulkOperation terminal evidence is invalid") from exc


@dataclass(frozen=True, slots=True)
class SnapshotPartManifestV1:
    """Canonical immutable evidence for one downloaded Bulk JSONL part."""

    part: SnapshotPart
    snapshot_set_id: str
    shop_domain: str
    api_version: str
    operation_id: str
    operation_type: str
    status: str
    error_code: None
    url_present: bool
    partial_data_url_present: bool
    created_at: str
    completed_at: str
    online_store_publication_gid: str
    source_code_sha: str
    query_sha256: str
    content_sha256: str
    snapshot_bytes: int
    object_count: int
    root_object_count: int
    object_counts: tuple[tuple[str, int], ...]
    capture_fence_max_seconds: int
    part_generation: str
    schema_version: int = PART_MANIFEST_SCHEMA_VERSION

    FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "apiVersion",
            "completedAt",
            "contentSha256",
            "objectCount",
            "objectCounts",
            "onlineStorePublicationGid",
            "operationId",
            "operationType",
            "part",
            "partGeneration",
            "partialDataUrlPresent",
            "querySha256",
            "rootObjectCount",
            "schemaVersion",
            "shopDomain",
            "snapshotBytes",
            "snapshotSetId",
            "sourceCodeSha",
            "createdAt",
            "errorCode",
            "status",
            "urlPresent",
            "captureFenceMaxSeconds",
        }
    )

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != (
            PART_MANIFEST_SCHEMA_VERSION
        ):
            raise ReconciliationContractError("snapshot part schemaVersion must be 1")
        if type(self.part) is not SnapshotPart:
            raise ReconciliationContractError("snapshot part is invalid")
        if (
            type(self.snapshot_set_id) is not str
            or _GENERATION_PATTERN.fullmatch(self.snapshot_set_id) is None
        ):
            raise ReconciliationContractError("snapshot part snapshotSetId is invalid")
        if (
            type(self.shop_domain) is not str
            or bulk.SHOP_DOMAIN_PATTERN.fullmatch(self.shop_domain) is None
        ):
            raise ReconciliationContractError("snapshot part shopDomain is invalid")
        if (
            type(self.api_version) is not str
            or bulk.API_VERSION_PATTERN.fullmatch(self.api_version) is None
        ):
            raise ReconciliationContractError("snapshot part apiVersion is invalid")
        _validated_gid(self.operation_id, "BulkOperation", "snapshot part operationId")
        if type(self.operation_type) is not str or self.operation_type != "QUERY":
            raise ReconciliationContractError("snapshot part operationType must be QUERY")
        _validated_gid(
            self.online_store_publication_gid,
            "Publication",
            "snapshot part onlineStorePublicationGid",
        )
        if type(self.status) is not str or self.status != "COMPLETED":
            raise ReconciliationContractError("snapshot part status must be COMPLETED")
        if self.error_code is not None:
            raise ReconciliationContractError("snapshot part errorCode must be null")
        if type(self.url_present) is not bool or not self.url_present:
            raise ReconciliationContractError("snapshot part URL flag must be true")
        if type(self.partial_data_url_present) is not bool:
            raise ReconciliationContractError("snapshot part partial flag must be boolean")
        if self.partial_data_url_present:
            raise ReconciliationContractError("partial snapshot data is not acceptable")
        created_text, created = _canonical_timestamp(self.created_at, "snapshot part createdAt")
        completed_text, completed = _canonical_timestamp(
            self.completed_at, "snapshot part completedAt"
        )
        if self.created_at != created_text or self.completed_at != completed_text:
            raise ReconciliationContractError("snapshot part timestamps are not canonical UTC")
        if completed < created:
            raise ReconciliationContractError("snapshot part completedAt precedes createdAt")
        if (
            type(self.capture_fence_max_seconds) is not int
            or self.capture_fence_max_seconds != CAPTURE_FENCE_MAX_SECONDS
        ):
            raise ReconciliationContractError("snapshot part capture fence is invalid")
        if completed - created > timedelta(seconds=self.capture_fence_max_seconds):
            raise ReconciliationContractError("snapshot part exceeds the capture window")
        if (
            type(self.source_code_sha) is not str
            or bulk.COMMIT_SHA_PATTERN.fullmatch(self.source_code_sha) is None
        ):
            raise ReconciliationContractError("snapshot part sourceCodeSha is invalid")
        for context, value in (
            ("querySha256", self.query_sha256),
            ("contentSha256", self.content_sha256),
        ):
            if type(value) is not str or bulk.SHA256_PATTERN.fullmatch(value) is None:
                raise ReconciliationContractError(f"snapshot part {context} is invalid")
        _validated_count(self.snapshot_bytes, "snapshot part snapshotBytes", positive=True)
        _validated_count(self.object_count, "snapshot part objectCount", positive=True)
        _validated_count(self.root_object_count, "snapshot part rootObjectCount", positive=True)
        expected_types = _PART_TYPES[self.part]
        if (
            type(self.object_counts) is not tuple
            or any(
                type(entry) is not tuple or len(entry) != 2 or type(entry[0]) is not str
                for entry in self.object_counts
            )
            or tuple(
                entry[0] for entry in self.object_counts if type(entry) is tuple and len(entry) == 2
            )
            != expected_types
            or len(self.object_counts) != len(expected_types)
        ):
            raise ReconciliationContractError("snapshot part objectCounts has invalid keys")
        for entry in self.object_counts:
            _validated_count(entry[1], "snapshot part objectCounts value")
        counts = dict(self.object_counts)
        if sum(counts.values()) != self.object_count:
            raise ReconciliationContractError(
                "snapshot part objectCounts do not sum to objectCount"
            )
        if counts[_ROOT_TYPE[self.part]] != self.root_object_count:
            raise ReconciliationContractError("snapshot part rootObjectCount is inconsistent")
        if (
            type(self.part_generation) is not str
            or _GENERATION_PATTERN.fullmatch(self.part_generation) is None
        ):
            raise ReconciliationContractError("snapshot part generation is invalid")
        if self.part_generation != self.expected_part_generation():
            raise ReconciliationContractError("snapshot part generation does not match evidence")

    def generation_descriptor(self) -> dict[str, Any]:
        return {
            "apiVersion": self.api_version,
            "captureFenceMaxSeconds": self.capture_fence_max_seconds,
            "completedAt": self.completed_at,
            "contentSha256": self.content_sha256,
            "createdAt": self.created_at,
            "errorCode": self.error_code,
            "objectCount": self.object_count,
            "objectCounts": dict(self.object_counts),
            "onlineStorePublicationGid": self.online_store_publication_gid,
            "operationId": self.operation_id,
            "operationType": self.operation_type,
            "part": self.part.value,
            "partialDataUrlPresent": self.partial_data_url_present,
            "querySha256": self.query_sha256,
            "rootObjectCount": self.root_object_count,
            "schemaVersion": self.schema_version,
            "shopDomain": self.shop_domain,
            "snapshotBytes": self.snapshot_bytes,
            "snapshotSetId": self.snapshot_set_id,
            "sourceCodeSha": self.source_code_sha,
            "status": self.status,
            "urlPresent": self.url_present,
        }

    def expected_part_generation(self) -> str:
        return (
            f"sha256:{_digest_object(self.generation_descriptor(), domain='nla-snapshot-part-v1')}"
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.generation_descriptor(),
            "partGeneration": self.part_generation,
        }

    def to_json_bytes(self) -> bytes:
        return _canonical_json_bytes(
            self.as_dict(),
            context="snapshot part manifest",
            limit=MAX_PART_MANIFEST_BYTES,
        )

    @classmethod
    def from_json_bytes(cls, raw: bytes) -> SnapshotPartManifestV1:
        if type(raw) is not bytes or not raw or len(raw) > MAX_PART_MANIFEST_BYTES:
            raise ReconciliationContractError("snapshot part manifest bytes are invalid")
        try:
            value = bulk._strict_json(raw, "snapshot part manifest")
            if type(value) is not dict:
                raise ReconciliationContractError("snapshot part manifest must be an object")
            bulk._exact_keys(value, cls.FIELDS, "snapshot part manifest")
            raw_counts = value["objectCounts"]
            if type(raw_counts) is not dict:
                raise ReconciliationContractError("snapshot part objectCounts must be an object")
            part = SnapshotPart(value["part"])
            expected_types = _PART_TYPES[part]
            bulk._exact_keys(raw_counts, set(expected_types), "snapshot part objectCounts")
            return cls(
                schema_version=value["schemaVersion"],
                part=part,
                snapshot_set_id=value["snapshotSetId"],
                shop_domain=value["shopDomain"],
                api_version=value["apiVersion"],
                operation_id=value["operationId"],
                operation_type=value["operationType"],
                status=value["status"],
                error_code=value["errorCode"],
                url_present=value["urlPresent"],
                partial_data_url_present=value["partialDataUrlPresent"],
                created_at=value["createdAt"],
                completed_at=value["completedAt"],
                online_store_publication_gid=value["onlineStorePublicationGid"],
                source_code_sha=value["sourceCodeSha"],
                query_sha256=value["querySha256"],
                content_sha256=value["contentSha256"],
                snapshot_bytes=value["snapshotBytes"],
                object_count=value["objectCount"],
                root_object_count=value["rootObjectCount"],
                object_counts=tuple((name, raw_counts[name]) for name in expected_types),
                capture_fence_max_seconds=value["captureFenceMaxSeconds"],
                part_generation=value["partGeneration"],
            )
        except ReconciliationContractError:
            raise
        except (TypeError, ValueError, KeyError, bulk.BulkContractError) as exc:
            raise ReconciliationContractError("snapshot part manifest is invalid") from exc


def _validated_part_manifest(value: object) -> SnapshotPartManifestV1:
    if type(value) is not SnapshotPartManifestV1:
        raise ReconciliationContractError("part manifest must be SnapshotPartManifestV1")
    try:
        raw = value.to_json_bytes()
        canonical = SnapshotPartManifestV1.from_json_bytes(raw)
        if canonical.to_json_bytes() != raw:
            raise ReconciliationContractError("snapshot part manifest is non-canonical")
        return canonical
    except ReconciliationContractError:
        raise
    except Exception as exc:
        raise ReconciliationContractError("snapshot part manifest is invalid") from exc


@dataclass(frozen=True, slots=True)
class SnapshotPartInputV1:
    manifest: SnapshotPartManifestV1
    snapshot_path: Path
    query_path: Path
    snapshot_handle: BinaryIO | None = field(default=None, repr=False, compare=False)
    query_handle: BinaryIO | None = field(default=None, repr=False, compare=False)
    query_bytes: bytes | None = field(default=None, repr=False, compare=False)


def _validated_path(value: object, context: str) -> Path:
    if type(value) is not _CONCRETE_PATH_TYPE:
        raise ReconciliationContractError(f"{context} must be a concrete Path")
    return value


@dataclass(frozen=True, slots=True)
class _PartScan:
    content_sha256: str
    snapshot_bytes: int
    object_count: int
    object_counts: tuple[tuple[str, int], ...]


def _verify_pinned_handle(handle: BinaryIO, context: str) -> tuple[int, int, int, int]:
    try:
        handle_facts = os.fstat(handle.fileno())
    except (OSError, ValueError) as exc:
        raise ReconciliationDataError(f"{context} pinned identity cannot be verified") from exc
    if not stat.S_ISREG(handle_facts.st_mode) or handle_facts.st_nlink != 1:
        raise ReconciliationDataError(f"{context} pinned handle is not one regular file")
    return (
        handle_facts.st_dev,
        handle_facts.st_ino,
        handle_facts.st_size,
        handle_facts.st_mtime_ns,
    )


def _read_part(
    path: Path,
    part: SnapshotPart,
    consumer: Callable[[dict[str, Any], int, bytes], None] | None = None,
    *,
    handle: BinaryIO | None = None,
) -> _PartScan:
    counts = dict.fromkeys(_PART_TYPES[part], 0)
    digest = hashlib.sha256()
    byte_count = 0
    line_count = 0

    def scan(stream: BinaryIO) -> None:
        nonlocal byte_count, line_count
        while raw := bulk._next_line(stream):
            line_count += 1
            byte_count += len(raw)
            digest.update(raw)
            if not raw.strip():
                raise ReconciliationDataError("snapshot part contains a blank JSONL record")
            payload = bulk._strict_json(raw, "snapshot part record")
            if type(payload) is not dict:
                raise ReconciliationDataError("snapshot part record must be an object")
            typename = payload.get("__typename")
            if typename not in counts:
                raise ReconciliationDataError("snapshot part contains an unexpected object type")
            if consumer is not None:
                consumer(payload, line_count, raw)
            counts[typename] += 1

    try:
        if handle is None:
            try:
                opened = path.open("rb")
            except OSError as exc:
                raise ReconciliationDataError("cannot read snapshot part") from exc
            with opened:
                scan(opened)
        else:
            pinned_state = _verify_pinned_handle(handle, "snapshot part")
            handle.seek(0)
            scan(handle)
            if _verify_pinned_handle(handle, "snapshot part") != pinned_state:
                raise ReconciliationDataError("snapshot part pinned state changed while reading")
    except ReconciliationDataError:
        raise
    except (OSError, bulk.BulkContractError) as exc:
        raise ReconciliationDataError("snapshot part is invalid") from exc
    except Exception as exc:
        raise ReconciliationDataError("snapshot part processing failed") from exc
    return _PartScan(
        content_sha256=digest.hexdigest(),
        snapshot_bytes=byte_count,
        object_count=line_count,
        object_counts=tuple((name, counts[name]) for name in _PART_TYPES[part]),
    )


def _file_sha256(path: Path, context: str) -> str:
    try:
        return bulk._file_sha256(path)
    except (OSError, bulk.BulkContractError) as exc:
        raise ReconciliationDataError(f"cannot read {context}") from exc


def _read_query_bytes(
    path: Path,
    *,
    handle: BinaryIO | None = None,
    frozen: bytes | None = None,
) -> bytes:
    if handle is not None and frozen is not None:
        raise ReconciliationContractError("snapshot query must use one immutable source")
    try:
        if frozen is not None:
            if type(frozen) is not bytes:
                raise ReconciliationContractError("frozen snapshot query must be exact bytes")
            raw = frozen
        elif handle is None:
            with path.open("rb") as opened:
                raw = opened.read(MAX_BULK_QUERY_BYTES + 1)
        else:
            pinned_state = _verify_pinned_handle(handle, "snapshot query")
            handle.seek(0)
            raw = handle.read(MAX_BULK_QUERY_BYTES + 1)
            if _verify_pinned_handle(handle, "snapshot query") != pinned_state:
                raise ReconciliationDataError("snapshot query pinned state changed while reading")
    except (OSError, ValueError) as exc:
        raise ReconciliationDataError("cannot read snapshot query") from exc
    if not raw or len(raw) > MAX_BULK_QUERY_BYTES:
        raise ReconciliationDataError("snapshot query bytes are invalid")
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReconciliationDataError("snapshot query is not valid UTF-8") from exc
    return raw


def _shopify_terminal_query_transport(canonical_query: bytes) -> bytes:
    """Return the one observed Shopify terminal representation of an approved query."""

    return canonical_query.replace(b"\n", b"\r\n") + b"\r\n"


def _terminal_query_transport_mode(terminal_query: str, canonical_query: bytes) -> str:
    """Classify only canonical bytes or Shopify's exact CRLF-plus-newline transport."""

    raw = terminal_query.encode("utf-8")
    if raw == canonical_query:
        return "canonical-lf-v1"
    if raw == _shopify_terminal_query_transport(canonical_query):
        return "shopify-crlf-plus-one-terminal-newline-v1"
    raise ReconciliationDataError(
        "snapshot query does not match approved bytes or the exact Shopify transport"
    )


def create_snapshot_part_manifest(
    snapshot_path: Path,
    *,
    query_path: Path,
    part: SnapshotPart,
    expectation: ReconciliationExpectationV1,
    terminal_evidence: BulkOperationTerminalEvidenceV1,
    snapshot_handle: BinaryIO | None = None,
    query_handle: BinaryIO | None = None,
    query_bytes: bytes | None = None,
) -> SnapshotPartManifestV1:
    """Create canonical evidence after checking exact terminal BulkOperation metadata."""

    expected = _validated_expectation(expectation)
    terminal = _validated_terminal_evidence(terminal_evidence)
    if type(part) is not SnapshotPart:
        raise ReconciliationContractError("part must be SnapshotPart")
    snapshot_path = _validated_path(snapshot_path, "snapshot path")
    query_path = _validated_path(query_path, "query path")
    approved_query_bytes = _read_query_bytes(
        query_path,
        handle=query_handle,
        frozen=query_bytes,
    )
    query_sha256 = hashlib.sha256(approved_query_bytes).hexdigest()
    if query_sha256 != _APPROVED_QUERY_SHA256[part]:
        raise ReconciliationDataError("snapshot query is not the approved query for its part")
    _terminal_query_transport_mode(terminal.query, approved_query_bytes)
    scan = _read_part(snapshot_path, part, handle=snapshot_handle)
    if scan.snapshot_bytes != terminal.file_size:
        raise ReconciliationDataError("snapshot byte count does not match terminal evidence")
    if scan.object_count != terminal.object_count:
        raise ReconciliationDataError("snapshot object count does not match terminal evidence")
    root_count = dict(scan.object_counts)[_ROOT_TYPE[part]]
    if root_count != terminal.root_object_count:
        raise ReconciliationDataError("snapshot root count does not match terminal evidence")
    expected_root_count = (
        expected.product_count if part is SnapshotPart.PRODUCTS else expected.variant_count
    )
    if root_count != expected_root_count:
        raise ReconciliationDataError("snapshot root count does not match trusted expectation")
    values: dict[str, Any] = {
        "part": part,
        "snapshot_set_id": expected.snapshot_set_id,
        "shop_domain": expected.shop_domain,
        "api_version": expected.api_version,
        "operation_id": terminal.operation_id,
        "operation_type": terminal.operation_type,
        "status": terminal.status,
        "error_code": terminal.error_code,
        "url_present": terminal.url_present,
        "partial_data_url_present": terminal.partial_data_url_present,
        "created_at": terminal.created_at,
        "completed_at": terminal.completed_at,
        "online_store_publication_gid": expected.online_store_publication_gid,
        "source_code_sha": expected.source_code_sha,
        "query_sha256": query_sha256,
        "content_sha256": scan.content_sha256,
        "snapshot_bytes": scan.snapshot_bytes,
        "object_count": scan.object_count,
        "root_object_count": root_count,
        "object_counts": scan.object_counts,
        "capture_fence_max_seconds": CAPTURE_FENCE_MAX_SECONDS,
    }
    provisional = object.__new__(SnapshotPartManifestV1)
    for name, value in values.items():
        object.__setattr__(provisional, name, value)
    object.__setattr__(provisional, "schema_version", PART_MANIFEST_SCHEMA_VERSION)
    part_digest = _digest_object(provisional.generation_descriptor(), domain="nla-snapshot-part-v1")
    generation = f"sha256:{part_digest}"
    return SnapshotPartManifestV1(**values, part_generation=generation)


def _validate_scan(scan: _PartScan, manifest: SnapshotPartManifestV1) -> None:
    if (
        scan.content_sha256 != manifest.content_sha256
        or scan.snapshot_bytes != manifest.snapshot_bytes
        or scan.object_count != manifest.object_count
        or scan.object_counts != manifest.object_counts
    ):
        raise ReconciliationDataError("snapshot part does not match its immutable manifest")


def _manifest_matches_expectation(
    manifest: SnapshotPartManifestV1, expectation: ReconciliationExpectationV1
) -> bool:
    expected_root = (
        expectation.product_count
        if manifest.part is SnapshotPart.PRODUCTS
        else expectation.variant_count
    )
    return (
        manifest.snapshot_set_id == expectation.snapshot_set_id
        and manifest.shop_domain == expectation.shop_domain
        and manifest.api_version == expectation.api_version
        and manifest.online_store_publication_gid == expectation.online_store_publication_gid
        and manifest.source_code_sha == expectation.source_code_sha
        and manifest.root_object_count == expected_root
    )


def _ordered_inputs(
    inputs: object, expectation: ReconciliationExpectationV1
) -> tuple[SnapshotPartInputV1, SnapshotPartInputV1]:
    if type(inputs) is not tuple or len(inputs) != 2:
        raise ReconciliationContractError("exactly two snapshot parts are required")
    by_part: dict[SnapshotPart, SnapshotPartInputV1] = {}
    for value in inputs:
        if type(value) is not SnapshotPartInputV1:
            raise ReconciliationContractError("snapshot inputs must be SnapshotPartInputV1")
        snapshot_path = _validated_path(value.snapshot_path, "snapshot input path")
        query_path = _validated_path(value.query_path, "query input path")
        manifest = _validated_part_manifest(value.manifest)
        if manifest.part in by_part:
            raise ReconciliationContractError("duplicate snapshot part")
        if not _manifest_matches_expectation(manifest, expectation):
            raise ReconciliationDataError("snapshot parts belong to a mixed generation")
        by_part[manifest.part] = SnapshotPartInputV1(
            manifest=manifest,
            snapshot_path=snapshot_path,
            query_path=query_path,
            snapshot_handle=value.snapshot_handle,
            query_handle=value.query_handle,
            query_bytes=value.query_bytes,
        )
    ordered = (by_part[SnapshotPart.PRODUCTS], by_part[SnapshotPart.VARIANTS])
    snapshot_handles = tuple(
        item.snapshot_handle for item in ordered if item.snapshot_handle is not None
    )
    if snapshot_handles and len(snapshot_handles) != 2:
        raise ReconciliationContractError("pinned snapshot inputs must include both handles")
    query_handles = tuple(item.query_handle for item in ordered if item.query_handle is not None)
    frozen_queries = tuple(item.query_bytes for item in ordered if item.query_bytes is not None)
    if query_handles and frozen_queries:
        raise ReconciliationContractError("snapshot queries must use one immutable source mode")
    if query_handles and len(query_handles) != 2:
        raise ReconciliationContractError("pinned snapshot queries must include both handles")
    if frozen_queries and len(frozen_queries) != 2:
        raise ReconciliationContractError("frozen snapshot queries must include both byte strings")
    handles = snapshot_handles + query_handles
    if handles and len({id(handle) for handle in handles}) != len(handles):
        raise ReconciliationContractError("pinned snapshot input handles must be distinct")
    if ordered[0].manifest.operation_id == ordered[1].manifest.operation_id:
        raise ReconciliationDataError("snapshot parts must use distinct Bulk operations")
    try:
        same_snapshot = ordered[0].snapshot_path.resolve() == ordered[1].snapshot_path.resolve()
        same_query = ordered[0].query_path.resolve() == ordered[1].query_path.resolve()
    except OSError as exc:
        raise ReconciliationContractError("snapshot input path cannot be resolved") from exc
    if same_snapshot:
        raise ReconciliationContractError("snapshot parts must use distinct files")
    if same_query:
        raise ReconciliationContractError("snapshot parts must use distinct queries")
    if any(
        item.manifest.query_sha256 != _APPROVED_QUERY_SHA256[item.manifest.part] for item in ordered
    ):
        raise ReconciliationDataError("snapshot part does not use its approved query")
    _capture_fence(ordered[0].manifest, ordered[1].manifest)
    return ordered


def _capture_fence(
    first: SnapshotPartManifestV1, second: SnapshotPartManifestV1
) -> tuple[str, str, int]:
    parts = (first, second)
    created = [
        _canonical_timestamp(part.created_at, "snapshot part createdAt")[1] for part in parts
    ]
    completed = [
        _canonical_timestamp(part.completed_at, "snapshot part completedAt")[1] for part in parts
    ]
    if max(created) > min(completed):
        raise ReconciliationDataError("snapshot Bulk operation windows do not overlap")
    capture_started = min(created)
    capture_completed = max(completed)
    duration = capture_completed - capture_started
    if duration > timedelta(seconds=CAPTURE_FENCE_MAX_SECONDS):
        raise ReconciliationDataError("snapshot capture exceeds the maximum window")
    return (
        _validated_timestamp(capture_started.isoformat(), "capture startedAt"),
        _validated_timestamp(capture_completed.isoformat(), "capture completedAt"),
        int(duration.total_seconds()),
    )


_RECONCILIATION_SCHEMA: Final = """
CREATE TABLE reconciliation_identities (
    typename TEXT NOT NULL,
    identity TEXT NOT NULL,
    canonical_json BLOB NOT NULL,
    PRIMARY KEY (typename, identity)
) STRICT;
"""


def _canonical_source_row(payload: dict[str, Any]) -> bytes:
    try:
        return json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except Exception as exc:
        raise ReconciliationDataError("snapshot row is not canonically serializable") from exc


def _normalize_root_variant(payload: dict[str, Any]) -> dict[str, Any]:
    required = {
        "__typename",
        "barcode",
        "compareAtPrice",
        "id",
        "inventoryItem",
        "inventoryPolicy",
        "inventoryQuantity",
        "price",
        "product",
        "selectedOptions",
        "sku",
        "title",
        "updatedAt",
    }
    try:
        bulk._exact_keys(payload, required, "ProductVariant root")
        product = payload.get("product")
        if type(product) is not dict:
            raise ReconciliationDataError("ProductVariant root lacks Product ownership")
        bulk._exact_keys(product, {"__typename", "id"}, "ProductVariant root product")
        if product.get("__typename") != "Product":
            raise ReconciliationDataError("ProductVariant root has invalid Product ownership")
        product_gid = bulk._gid_value(product.get("id"), "Product", "ProductVariant root product")
    except bulk.BulkContractError as exc:
        raise ReconciliationDataError("ProductVariant root shape is invalid") from exc
    normalized = {key: value for key, value in payload.items() if key != "product"}
    normalized["__parentId"] = product_gid
    return normalized


def _normalize_split_inventory_level(
    connection: sqlite3.Connection, payload: dict[str, Any]
) -> dict[str, Any]:
    try:
        variant_gid = bulk._gid_value(
            payload.get("__parentId"),
            "ProductVariant",
            "InventoryLevel split parent",
        )
    except bulk.BulkContractError as exc:
        raise ReconciliationDataError("InventoryLevel split shape is invalid") from exc
    owner = connection.execute(
        "SELECT inventory_item_gid FROM variants WHERE gid=?", (variant_gid,)
    ).fetchone()
    if owner is None or type(owner[0]) is not str:
        raise ReconciliationDataError("InventoryLevel parent ProductVariant is unavailable")
    normalized = dict(payload)
    normalized["__parentId"] = owner[0]
    return normalized


def _row_identity(payload: dict[str, Any]) -> tuple[str, str]:
    typename = payload.get("__typename")
    try:
        if typename in {"Product", "ProductVariant", "Metafield"}:
            return typename, bulk._gid_value(payload.get("id"), typename, "snapshot row id")
        if typename == "InventoryLevel":
            value = bulk._text(payload, "id", "InventoryLevel")
            return typename, value
        if typename == "ResourcePublicationV2":
            product_gid = bulk._gid_value(
                payload.get("__parentId"), "Product", "publication Product"
            )
            publication = payload.get("publication")
            if type(publication) is not dict:
                raise ReconciliationDataError("publication row is invalid")
            publication_gid = bulk._gid_value(
                publication.get("id"), "Publication", "publication id"
            )
            return typename, f"{product_gid}|{publication_gid}"
    except bulk.BulkContractError as exc:
        raise ReconciliationDataError("snapshot row identity is invalid") from exc
    raise ReconciliationDataError("snapshot row type is invalid")


def _remember_identity(connection: sqlite3.Connection, payload: dict[str, Any]) -> None:
    typename, identity = _row_identity(payload)
    canonical = _canonical_source_row(payload)
    existing = connection.execute(
        "SELECT canonical_json FROM reconciliation_identities WHERE typename=? AND identity=?",
        (typename, identity),
    ).fetchone()
    if existing is not None:
        qualifier = "duplicate" if existing[0] == canonical else "conflicting"
        raise ReconciliationDataError(f"{qualifier} {typename} identity")
    connection.execute(
        "INSERT INTO reconciliation_identities VALUES (?, ?, ?)",
        (typename, identity, canonical),
    )


def _insert_source_row(
    connection: sqlite3.Connection,
    part: SnapshotPart,
    payload: dict[str, Any],
    line: int,
) -> None:
    typename = payload["__typename"]
    try:
        _remember_identity(connection, payload)
        if part is SnapshotPart.PRODUCTS:
            if typename == "Product":
                handle = bulk._text(payload, "handle", "Product")
                if connection.execute(
                    "SELECT 1 FROM products WHERE handle=?", (handle,)
                ).fetchone():
                    raise ReconciliationDataError("conflicting Product handle")
                bulk._insert_product(connection, payload, line)
            elif typename == "ResourcePublicationV2":
                bulk._insert_publication(connection, payload, line)
            else:
                bulk._gid_value(payload.get("__parentId"), "Product", "Product Metafield owner")
                bulk._insert_metafield(connection, payload, line)
        elif typename == "ProductVariant":
            normalized = _normalize_root_variant(payload)
            item = normalized.get("inventoryItem")
            if type(item) is not dict:
                raise ReconciliationDataError("ProductVariant inventory item is invalid")
            inventory_gid = bulk._gid_value(
                item.get("id"), "InventoryItem", "ProductVariant inventory item"
            )
            if connection.execute(
                "SELECT 1 FROM variants WHERE inventory_item_gid=?", (inventory_gid,)
            ).fetchone():
                raise ReconciliationDataError("conflicting InventoryItem ownership")
            bulk._insert_variant(connection, normalized, line)
        elif typename == "InventoryLevel":
            bulk._insert_inventory_level(
                connection,
                _normalize_split_inventory_level(connection, payload),
                line,
            )
        else:
            bulk._gid_value(
                payload.get("__parentId"), "ProductVariant", "ProductVariant Metafield owner"
            )
            bulk._insert_metafield(connection, payload, line)
    except ReconciliationDataError:
        raise
    except bulk.BulkContractError as exc:
        raise ReconciliationDataError("snapshot row contract is invalid") from exc
    except sqlite3.IntegrityError as exc:
        raise ReconciliationDataError("conflicting source row") from exc
    except Exception as exc:
        raise ReconciliationDataError("snapshot row processing failed") from exc


@dataclass(frozen=True, slots=True)
class _SourceCounts:
    product_count: int
    variant_count: int
    inventory_item_count: int
    inventory_level_count: int
    publication_count: int
    metafield_count: int
    product_status_counts: tuple[tuple[str, int], ...]
    active_published_product_count: int
    source_identity_product_count: int


def _require_no_row(
    connection: sqlite3.Connection,
    query: str,
    message: str,
    parameters: tuple[object, ...] = (),
) -> None:
    if connection.execute(query, parameters).fetchone() is not None:
        raise ReconciliationDataError(message)


def _scalar(connection: sqlite3.Connection, query: str, parameters: tuple[object, ...] = ()) -> int:
    row = connection.execute(query, parameters).fetchone()
    if row is None or type(row[0]) is not int:
        raise ReconciliationDataError("reconciliation count is unavailable")
    return row[0]


def _reconcile_database(
    connection: sqlite3.Connection,
    expectation: ReconciliationExpectationV1,
    scans: dict[SnapshotPart, _PartScan],
) -> _SourceCounts:
    _require_no_row(
        connection,
        "SELECT 1 FROM variants v LEFT JOIN products p ON p.gid=v.product_gid "
        "WHERE p.gid IS NULL LIMIT 1",
        "dangling ProductVariant",
    )
    _require_no_row(
        connection,
        "SELECT 1 FROM publications r LEFT JOIN products p ON p.gid=r.product_gid "
        "WHERE p.gid IS NULL LIMIT 1",
        "dangling ResourcePublicationV2",
    )
    _require_no_row(
        connection,
        "SELECT 1 FROM inventory_levels l LEFT JOIN variants v "
        "ON v.inventory_item_gid=l.inventory_item_gid WHERE v.gid IS NULL LIMIT 1",
        "dangling InventoryLevel",
    )
    _require_no_row(
        connection,
        "SELECT 1 FROM metafields m LEFT JOIN products p ON p.gid=m.owner_gid "
        "LEFT JOIN variants v ON v.gid=m.owner_gid "
        "WHERE p.gid IS NULL AND v.gid IS NULL LIMIT 1",
        "dangling Metafield",
    )
    _require_no_row(
        connection,
        "SELECT 1 FROM products p LEFT JOIN variants v ON v.product_gid=p.gid "
        "GROUP BY p.gid, p.expected_variant_count "
        "HAVING COUNT(v.gid) <> p.expected_variant_count LIMIT 1",
        "missing or excess ProductVariant children",
    )
    _require_no_row(
        connection,
        "SELECT 1 FROM products p LEFT JOIN publications r "
        "ON r.product_gid=p.gid AND r.publication_gid=? "
        "WHERE r.product_gid IS NULL LIMIT 1",
        "missing Online Store publication evidence",
        (expectation.online_store_publication_gid,),
    )
    _require_no_row(
        connection,
        "SELECT 1 FROM products WHERE "
        "(sync_source_id IS NULL) <> (powertools_source_id IS NULL) "
        "OR sync_source_id <> powertools_source_id LIMIT 1",
        "conflicting secondary source identity",
    )
    product_count = _scalar(connection, "SELECT COUNT(*) FROM products")
    variant_count = _scalar(connection, "SELECT COUNT(*) FROM variants")
    if product_count != expectation.product_count or variant_count != expectation.variant_count:
        raise ReconciliationDataError("root identity counts do not match trusted expectation")
    if product_count != dict(scans[SnapshotPart.PRODUCTS].object_counts)["Product"]:
        raise ReconciliationDataError("Product accounting mismatch")
    if variant_count != dict(scans[SnapshotPart.VARIANTS].object_counts)["ProductVariant"]:
        raise ReconciliationDataError("ProductVariant accounting mismatch")
    inventory_item_count = _scalar(
        connection, "SELECT COUNT(DISTINCT inventory_item_gid) FROM variants"
    )
    if inventory_item_count != variant_count:
        raise ReconciliationDataError("InventoryItem identity accounting mismatch")
    active_published = _scalar(
        connection,
        "SELECT COUNT(*) FROM products p JOIN publications r ON r.product_gid=p.gid "
        "WHERE p.status='ACTIVE' AND r.publication_gid=? AND r.is_published=1",
        (expectation.online_store_publication_gid,),
    )
    if active_published != expectation.expected_active_online_store_published_product_count:
        raise ReconciliationDataError("active published Product count does not match expectation")
    quick_check = connection.execute("PRAGMA quick_check").fetchone()
    if quick_check is None or quick_check[0] != "ok":
        raise ReconciliationDataError("temporary reconciliation database failed quick_check")
    status_counts = tuple(
        (status, _scalar(connection, "SELECT COUNT(*) FROM products WHERE status=?", (status,)))
        for status in bulk.PRODUCT_STATUSES
    )
    return _SourceCounts(
        product_count=product_count,
        variant_count=variant_count,
        inventory_item_count=inventory_item_count,
        inventory_level_count=_scalar(connection, "SELECT COUNT(*) FROM inventory_levels"),
        publication_count=_scalar(connection, "SELECT COUNT(*) FROM publications"),
        metafield_count=_scalar(connection, "SELECT COUNT(*) FROM metafields"),
        product_status_counts=status_counts,
        active_published_product_count=active_published,
        source_identity_product_count=_scalar(
            connection, "SELECT COUNT(*) FROM products WHERE sync_source_id IS NOT NULL"
        ),
    )


_PRODUCT_FACTS_SQL: Final = """
SELECT p.gid, p.product_type, p.tags_json, p.commercial_title,
       game.value AS nla_game, source_type.value AS nla_source_type,
       canonical_name.value AS nla_canonical_name,
       game.value_type AS nla_game_type, source_type.value_type AS nla_source_type_type,
       canonical_name.value_type AS nla_canonical_name_type
FROM products AS p
LEFT JOIN metafields AS game
  ON game.owner_gid=p.gid AND game.namespace='nla' AND game.key=?
LEFT JOIN metafields AS source_type
  ON source_type.owner_gid=p.gid AND source_type.namespace='nla' AND source_type.key=?
LEFT JOIN metafields AS canonical_name
  ON canonical_name.owner_gid=p.gid AND canonical_name.namespace='nla' AND canonical_name.key=?
ORDER BY length(p.gid), p.gid
"""


def _structured_metafield(row: sqlite3.Row, value_name: str, type_name: str) -> str | None:
    value = row[value_name]
    value_type = row[type_name]
    if value is None and value_type is None:
        return None
    if type(value) is not str or value_type != SINGLE_LINE_TEXT_TYPE:
        raise ReconciliationDataError("taxonomy source metafield has an invalid type")
    return value


def _taxonomy_inputs(connection: sqlite3.Connection) -> tuple[ProductFacts, ...]:
    facts: list[ProductFacts] = []
    for row in connection.execute(
        _PRODUCT_FACTS_SQL,
        (NLA_GAME_KEY, NLA_SOURCE_RECORD_TYPE_KEY, NLA_CANONICAL_CARD_NAME_KEY),
    ):
        try:
            tags = json.loads(row["tags_json"])
        except (json.JSONDecodeError, TypeError) as exc:
            raise ReconciliationDataError("stored Product tags are invalid") from exc
        if type(tags) is not list or any(type(tag) is not str for tag in tags):
            raise ReconciliationDataError("stored Product tags are invalid")
        facts.append(
            ProductFacts(
                product_gid=row["gid"],
                explicit_game=_structured_metafield(row, "nla_game", "nla_game_type"),
                product_type=row["product_type"],
                tags=tuple(tags),
                source_record_type=_structured_metafield(
                    row, "nla_source_type", "nla_source_type_type"
                ),
                commercial_title=row["commercial_title"],
                canonical_card_name=_structured_metafield(
                    row, "nla_canonical_name", "nla_canonical_name_type"
                ),
            )
        )
    return tuple(facts)


_PRODUCT_RUNTIME_SQL: Final = """
SELECT p.*, r.is_published
FROM products AS p
JOIN publications AS r ON r.product_gid=p.gid AND r.publication_gid=?
ORDER BY length(p.gid), p.gid
"""

_VARIANT_RUNTIME_SQL: Final = """
SELECT * FROM variants
ORDER BY length(product_gid), product_gid, length(gid), gid
"""


def _runtime_variant(row: sqlite3.Row) -> runtime.CatalogVariantRecordV1:
    try:
        options = json.loads(row["selected_options_json"])
    except (json.JSONDecodeError, TypeError) as exc:
        raise ReconciliationDataError("stored selected options are invalid") from exc
    if type(options) is not list:
        raise ReconciliationDataError("stored selected options are invalid")
    try:
        selected = tuple(runtime.SelectedOptionV1.from_dict(option) for option in options)
        return runtime.CatalogVariantRecordV1(
            variant_gid=row["gid"],
            product_gid=row["product_gid"],
            inventory_item_gid=row["inventory_item_gid"],
            title=row["title"],
            sku=row["sku"],
            barcode=row["barcode"],
            selected_options=selected,
            price_text=row["price_text"],
            compare_at_price_text=row["compare_at_price_text"],
            inventory_quantity=row["inventory_quantity"],
            inventory_policy=runtime.InventoryPolicy(row["inventory_policy"]),
            inventory_tracked=bool(row["inventory_tracked"]),
            updated_at=row["updated_at"],
        )
    except (TypeError, ValueError, runtime.RuntimeContractError) as exc:
        raise ReconciliationDataError(
            "stored ProductVariant cannot enter runtime contract"
        ) from exc


def _runtime_records(
    connection: sqlite3.Connection,
    publication_gid: str,
    facts: tuple[ProductFacts, ...],
    classifications: tuple[Classification, ...],
) -> tuple[runtime.CatalogProductRecordV1, ...]:
    variants = iter(connection.execute(_VARIANT_RUNTIME_SQL))
    next_variant = next(variants, None)
    records: list[runtime.CatalogProductRecordV1] = []
    fact_iter = iter(facts)
    classification_iter = iter(classifications)
    for product in connection.execute(_PRODUCT_RUNTIME_SQL, (publication_gid,)):
        fact = next(fact_iter, None)
        classification = next(classification_iter, None)
        if (
            fact is None
            or fact.product_gid != product["gid"]
            or classification is None
            or classification.product_gid != product["gid"]
        ):
            raise ReconciliationDataError("taxonomy and Product order do not reconcile")
        product_variants: list[runtime.CatalogVariantRecordV1] = []
        while next_variant is not None and next_variant["product_gid"] == product["gid"]:
            product_variants.append(_runtime_variant(next_variant))
            next_variant = next(variants, None)
        if not product_variants:
            raise ReconciliationDataError("Product has no reconciled ProductVariant")
        try:
            record = runtime.CatalogProductRecordV1.from_classification(
                classification=classification,
                handle=product["handle"],
                commercial_title=product["commercial_title"],
                canonical_card_name=fact.canonical_card_name,
                shopify_status=runtime.ProductStatus(product["status"]),
                online_store_published=bool(product["is_published"]),
                powertools_source_id=product["powertools_source_id"],
                sync_source_id=product["sync_source_id"],
                total_inventory=product["total_inventory"],
                tracks_inventory=bool(product["tracks_inventory"]),
                updated_at=product["updated_at"],
                variants=tuple(product_variants),
            )
        except (TypeError, ValueError, runtime.RuntimeContractError) as exc:
            raise ReconciliationDataError("Product cannot enter runtime contract") from exc
        records.append(record)
    if (
        next_variant is not None
        or next(fact_iter, None) is not None
        or next(classification_iter, None) is not None
    ):
        raise ReconciliationDataError("runtime Product/Variant accounting mismatch")
    return tuple(records)


@dataclass(frozen=True, slots=True)
class ReconciledSourceManifestV2:
    snapshot_set_id: str
    parts: tuple[SnapshotPartManifestV1, SnapshotPartManifestV1]
    capture_started_at: str
    capture_completed_at: str
    capture_window_seconds: int
    capture_fence_max_seconds: int
    source_query_sha256: str
    source_snapshot_sha256: str
    source_generation: str
    product_count: int
    variant_count: int
    inventory_item_count: int
    inventory_level_count: int
    publication_count: int
    metafield_count: int
    product_status_counts: tuple[tuple[str, int], ...]
    active_published_product_count: int
    source_identity_product_count: int
    schema_version: int = RECONCILED_MANIFEST_SCHEMA_VERSION

    def as_dict(self) -> dict[str, Any]:
        return {
            "activeOnlineStorePublishedProductCount": self.active_published_product_count,
            "captureCompletedAt": self.capture_completed_at,
            "captureFenceMaxSeconds": self.capture_fence_max_seconds,
            "captureStartedAt": self.capture_started_at,
            "captureWindowSeconds": self.capture_window_seconds,
            "inventoryItemCount": self.inventory_item_count,
            "inventoryLevelCount": self.inventory_level_count,
            "metafieldCount": self.metafield_count,
            "parts": [part.as_dict() for part in self.parts],
            "productCount": self.product_count,
            "productStatusCounts": dict(self.product_status_counts),
            "publicationCount": self.publication_count,
            "schemaVersion": self.schema_version,
            "snapshotSetId": self.snapshot_set_id,
            "sourceGeneration": self.source_generation,
            "sourceIdentityProductCount": self.source_identity_product_count,
            "sourceQuerySha256": self.source_query_sha256,
            "sourceSnapshotSha256": self.source_snapshot_sha256,
            "variantCount": self.variant_count,
        }

    def to_json_bytes(self) -> bytes:
        return _canonical_json_bytes(
            self.as_dict(),
            context="reconciled source manifest",
            limit=MAX_RECONCILED_MANIFEST_BYTES,
        )


def _build_source_manifest(
    parts: tuple[SnapshotPartInputV1, SnapshotPartInputV1], counts: _SourceCounts
) -> ReconciledSourceManifestV2:
    manifests = (parts[0].manifest, parts[1].manifest)
    capture_started, capture_completed, capture_seconds = _capture_fence(*manifests)
    query_sha = _digest_object(
        [{"part": item.part.value, "querySha256": item.query_sha256} for item in manifests],
        domain="nla-split-query-set-v1",
    )
    snapshot_sha = _digest_object(
        [
            {
                "contentSha256": item.content_sha256,
                "objectCounts": dict(item.object_counts),
                "part": item.part.value,
                "snapshotBytes": item.snapshot_bytes,
            }
            for item in manifests
        ],
        domain="nla-split-snapshot-set-v1",
    )
    generation_descriptor = {
        "apiVersion": manifests[0].api_version,
        "captureCompletedAt": capture_completed,
        "captureFenceMaxSeconds": CAPTURE_FENCE_MAX_SECONDS,
        "captureStartedAt": capture_started,
        "captureWindowSeconds": capture_seconds,
        "partGenerations": [item.part_generation for item in manifests],
        "shopDomain": manifests[0].shop_domain,
        "snapshotSetId": manifests[0].snapshot_set_id,
        "sourceCodeSha": manifests[0].source_code_sha,
        "sourceQuerySha256": query_sha,
        "sourceSnapshotSha256": snapshot_sha,
    }
    source_generation = (
        f"sha256:{_digest_object(generation_descriptor, domain='nla-reconciled-source-v2')}"
    )
    return ReconciledSourceManifestV2(
        snapshot_set_id=manifests[0].snapshot_set_id,
        parts=manifests,
        capture_started_at=capture_started,
        capture_completed_at=capture_completed,
        capture_window_seconds=capture_seconds,
        capture_fence_max_seconds=CAPTURE_FENCE_MAX_SECONDS,
        source_query_sha256=query_sha,
        source_snapshot_sha256=snapshot_sha,
        source_generation=source_generation,
        product_count=counts.product_count,
        variant_count=counts.variant_count,
        inventory_item_count=counts.inventory_item_count,
        inventory_level_count=counts.inventory_level_count,
        publication_count=counts.publication_count,
        metafield_count=counts.metafield_count,
        product_status_counts=counts.product_status_counts,
        active_published_product_count=counts.active_published_product_count,
        source_identity_product_count=counts.source_identity_product_count,
    )


def _runtime_manifest(
    source: ReconciledSourceManifestV2,
    records: tuple[runtime.CatalogProductRecordV1, ...],
    report: ClassificationReport,
) -> runtime.DatasetManifestV1:
    source_bytes = source.to_json_bytes()
    source_manifest_sha = hashlib.sha256(source_bytes).hexdigest()
    content_sha = runtime._catalog_content_sha256(records)
    descriptor = {
        "catalogContentSha256": content_sha,
        "contractVersion": runtime.CONTRACT_VERSION,
        "domain": "nla-catalog-dataset-generation-v1",
        "sourceQuerySha256": source.source_query_sha256,
        "sourceSnapshotManifestSchemaVersion": source.schema_version,
        "sourceSnapshotManifestSha256": source_manifest_sha,
        "sourceSnapshotSha256": source.source_snapshot_sha256,
        "taxonomyRuleVersion": report.rule_version,
    }
    generation = f"sha256:{hashlib.sha256(runtime._canonical_json_bytes(descriptor)).hexdigest()}"
    family_counts = tuple(
        (family.value, sum(record.product_family is family for record in records))
        for family in ProductFamily
    )
    classified = len(records) - dict(family_counts)[ProductFamily.UNCLASSIFIED.value]
    public_items = sum(
        record.publishable and record.product_family is not ProductFamily.UNCLASSIFIED
        for record in records
    )
    completed_at = max(
        source.parts,
        key=lambda part: _canonical_timestamp(part.completed_at, "snapshot part completedAt")[1],
    ).completed_at
    manifest = runtime.DatasetManifestV1(
        source_snapshot_manifest_schema_version=source.schema_version,
        source_snapshot_manifest_sha256=source_manifest_sha,
        source_snapshot_sha256=source.source_snapshot_sha256,
        source_query_sha256=source.source_query_sha256,
        taxonomy_rule_version=report.rule_version,
        catalog_content_sha256=content_sha,
        dataset_generation=generation,
        generated_at=completed_at,
        source_product_count=source.product_count,
        included_product_count=source.product_count,
        excluded_product_count=0,
        source_product_status_counts=source.product_status_counts,
        included_product_status_counts=source.product_status_counts,
        excluded_product_status_counts=tuple((status, 0) for status in bulk.PRODUCT_STATUSES),
        classified_product_count=classified,
        unclassified_product_count=len(records) - classified,
        product_family_counts=family_counts,
        source_variant_count=source.variant_count,
        included_variant_count=source.variant_count,
        excluded_variant_count=0,
        source_identity_product_count=source.source_identity_product_count,
        included_source_identity_product_count=source.source_identity_product_count,
        excluded_source_identity_product_count=0,
        source_active_online_store_published_product_count=(source.active_published_product_count),
        included_active_online_store_published_product_count=(
            source.active_published_product_count
        ),
        excluded_active_online_store_published_product_count=0,
        public_item_count=public_items,
    )
    manifest.validate_records(records)
    if report.total != len(records) or report.classified != classified:
        raise ReconciliationDataError("taxonomy report does not reconcile with runtime records")
    return manifest


@dataclass(frozen=True, slots=True)
class ReconciledCatalogGenerationV1:
    source_manifest: ReconciledSourceManifestV2
    source_manifest_bytes: bytes
    taxonomy_report: ClassificationReport
    records: tuple[runtime.CatalogProductRecordV1, ...]
    dataset_manifest: runtime.DatasetManifestV1


def reconcile_snapshot_parts(
    inputs: tuple[SnapshotPartInputV1, SnapshotPartInputV1],
    *,
    expectation: ReconciliationExpectationV1,
    taxonomy_config: TaxonomyConfig,
) -> ReconciledCatalogGenerationV1:
    """Reconcile exactly two immutable parts, then construct taxonomy/runtime evidence."""

    expected = _validated_expectation(expectation)
    ordered = _ordered_inputs(inputs, expected)
    scans: dict[SnapshotPart, _PartScan] = {}
    for item in ordered:
        if item.query_bytes is not None:
            query_sha256 = hashlib.sha256(
                _read_query_bytes(item.query_path, frozen=item.query_bytes)
            ).hexdigest()
        elif item.query_handle is None:
            query_sha256 = _file_sha256(item.query_path, "snapshot query")
        else:
            query_sha256 = hashlib.sha256(
                _read_query_bytes(item.query_path, handle=item.query_handle)
            ).hexdigest()
        if query_sha256 != item.manifest.query_sha256:
            raise ReconciliationDataError("snapshot query does not match its immutable manifest")
    try:
        with tempfile.TemporaryDirectory(prefix="nla-reconcile-") as directory:
            database = Path(directory) / "reconciliation.sqlite3"
            connection = sqlite3.connect(database)
            connection.row_factory = sqlite3.Row
            try:
                connection.executescript(bulk.SCHEMA)
                connection.executescript(_RECONCILIATION_SCHEMA)
                for item in ordered:
                    scan = _read_part(
                        item.snapshot_path,
                        item.manifest.part,
                        lambda payload, line, _raw, part=item.manifest.part: _insert_source_row(
                            connection, part, payload, line
                        ),
                        handle=item.snapshot_handle,
                    )
                    _validate_scan(scan, item.manifest)
                    scans[item.manifest.part] = scan
                counts = _reconcile_database(connection, expected, scans)
                facts = _taxonomy_inputs(connection)
                try:
                    classifications, report = classify_catalog(facts, taxonomy_config)
                except Exception as exc:
                    raise ReconciliationDataError(
                        "taxonomy rejected reconciled Product facts"
                    ) from exc
                records = _runtime_records(
                    connection,
                    expected.online_store_publication_gid,
                    facts,
                    classifications,
                )
                del facts, classifications
            finally:
                connection.close()
    except ReconciliationError:
        raise
    except (OSError, sqlite3.Error) as exc:
        raise ReconciliationDataError("split snapshot reconciliation failed") from exc
    source_manifest = _build_source_manifest(ordered, counts)
    dataset_manifest = _runtime_manifest(source_manifest, records, report)
    source_bytes = source_manifest.to_json_bytes()
    return ReconciledCatalogGenerationV1(
        source_manifest=source_manifest,
        source_manifest_bytes=source_bytes,
        taxonomy_report=report,
        records=records,
        dataset_manifest=dataset_manifest,
    )


__all__ = [
    "NLA_CANONICAL_CARD_NAME_KEY",
    "NLA_GAME_KEY",
    "NLA_SOURCE_RECORD_TYPE_KEY",
    "BulkOperationTerminalEvidenceV1",
    "ReconciledCatalogGenerationV1",
    "ReconciledSourceManifestV2",
    "ReconciliationContractError",
    "ReconciliationDataError",
    "ReconciliationError",
    "ReconciliationExpectationV1",
    "SnapshotPart",
    "SnapshotPartInputV1",
    "SnapshotPartManifestV1",
    "create_snapshot_part_manifest",
    "reconcile_snapshot_parts",
]
