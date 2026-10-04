"""Portable, fail-closed consumer for one packaged staging generation.

The Windows-only reconciled-bundle verifier remains the producer trust boundary.
This module consumes only its immutable SQLite projection and canonical evidence
report, pinned by a separately supplied package-manifest SHA-256.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
from contextlib import ExitStack
from dataclasses import dataclass, field
from itertools import islice
from pathlib import Path
from typing import BinaryIO

from nla_catalog_gateway import core_evidence, pagination, runtime_contract
from nla_catalog_gateway.core_evidence import VerifiedCatalogCoreEvidenceV1
from nla_catalog_gateway.pagination import (
    MAX_PROJECTION_FILE_BYTES,
    CatalogProjection,
)
from nla_catalog_gateway.runtime_contract import CatalogProductRecordV1

STAGING_PACKAGE_SCHEMA_VERSION = 1
STAGING_PACKAGE_FORMAT = "nla-staging-generation-v1"
EVIDENCE_FILENAME = "catalog-core-evidence.v1.json"
PROJECTION_FILENAME = "catalog-projection.v1.sqlite3"
MANIFEST_FILENAME = "staging-generation-manifest.v1.json"
ARTIFACT_FILENAMES = (EVIDENCE_FILENAME, PROJECTION_FILENAME)
PACKAGE_FILENAMES = frozenset((*ARTIFACT_FILENAMES, MANIFEST_FILENAME))
MAX_STAGING_MANIFEST_BYTES = 64 * 1024
MAX_CORE_EVIDENCE_REPORT_BYTES = 64 * 1024

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_CONCRETE_PATH_TYPE = type(Path())
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_CODE_SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
_GENERATION_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_SHOP_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.myshopify\.com\Z")
_READ_CHUNK_BYTES = 1024 * 1024
_WRITE_BITS = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH
_ERROR = "staging generation verification failed"

_MANIFEST_FIELDS = frozenset({"artifacts", "packageFormat", "schemaVersion"})
_ARTIFACT_FIELDS = frozenset({"bytes", "filename", "sha256"})
_REPORT_FIELDS = frozenset(
    {"bindings", "durationNanoseconds", "operationCounts", "result", "schemaVersion"}
)
_BINDING_FIELDS = frozenset(
    {
        "catalogContentSha256",
        "codeSha",
        "datasetGeneration",
        "projectionFingerprint",
        "shopDomain",
        "summarySha256",
    }
)
_DURATION_FIELDS = frozenset(
    {
        "facetEvaluation",
        "paginationTraversal",
        "projectionBuild",
        "searchQuery",
        "syncBootstrap",
    }
)
_COUNT_FIELDS = frozenset(
    {"facetEvaluations", "paginationPages", "searchQueries", "syncBootstraps"}
)


class StagingGenerationError(ValueError):
    """A fixed, value-free rejection of an untrusted staging package."""


@dataclass(frozen=True, slots=True, init=False, repr=False)
class VerifiedStagingGenerationV1:
    """Opaque, portable runtime inputs bound to one pinned staging package."""

    projection: CatalogProjection = field(repr=False)
    records: tuple[CatalogProductRecordV1, ...] = field(repr=False)
    evidence: VerifiedCatalogCoreEvidenceV1 = field(repr=False)
    manifest_sha256: str = field(repr=False)

    def __new__(cls, *_args: object, **_kwargs: object) -> VerifiedStagingGenerationV1:
        raise StagingGenerationError(_ERROR)

    def __reduce__(self) -> object:
        raise StagingGenerationError(_ERROR)

    def __reduce_ex__(self, _protocol: int) -> object:
        raise StagingGenerationError(_ERROR)


@dataclass(frozen=True, slots=True)
class _ArtifactContract:
    filename: str
    byte_count: int
    sha256: str


@dataclass(frozen=True, slots=True)
class _EvidenceBindings:
    shop_domain: str
    summary_sha256: str
    dataset_generation: str
    catalog_content_sha256: str
    projection_fingerprint: str
    code_sha: str


@dataclass(frozen=True, slots=True)
class _FileState:
    device: int
    inode: int
    byte_count: int
    modified_ns: int
    changed_ns: int
    mode: int
    link_count: int


@dataclass(frozen=True, slots=True)
class _PinnedFile:
    path: Path
    handle: BinaryIO = field(repr=False)
    state: _FileState


def _fail() -> StagingGenerationError:
    return StagingGenerationError(_ERROR)


def _exact_keys(value: object, expected: frozenset[str]) -> dict[str, object]:
    if type(value) is not dict or frozenset(value) != expected:
        raise _fail()
    return value


def _canonical_object(raw: bytes, *, maximum: int) -> dict[str, object]:
    value = runtime_contract._load_json_object(raw, byte_limit=maximum)
    if runtime_contract._canonical_json_bytes(value) != raw:
        raise _fail()
    return value


def _nonnegative(value: object) -> int:
    if type(value) is not int or not 0 <= value < 2**63:
        raise _fail()
    return value


def _positive(value: object) -> int:
    result = _nonnegative(value)
    if result == 0:
        raise _fail()
    return result


def _text(value: object, pattern: re.Pattern[str]) -> str:
    if type(value) is not str or pattern.fullmatch(value) is None:
        raise _fail()
    return value


def _parse_manifest(raw: bytes) -> tuple[_ArtifactContract, _ArtifactContract]:
    value = _exact_keys(
        _canonical_object(raw, maximum=MAX_STAGING_MANIFEST_BYTES), _MANIFEST_FIELDS
    )
    if (
        type(value["schemaVersion"]) is not int
        or value["schemaVersion"] != STAGING_PACKAGE_SCHEMA_VERSION
        or value["packageFormat"] != STAGING_PACKAGE_FORMAT
    ):
        raise _fail()
    supplied = value["artifacts"]
    if type(supplied) is not list or len(supplied) != len(ARTIFACT_FILENAMES):
        raise _fail()
    artifacts: list[_ArtifactContract] = []
    limits = (MAX_CORE_EVIDENCE_REPORT_BYTES, MAX_PROJECTION_FILE_BYTES)
    for raw_artifact, expected_name, maximum in zip(
        supplied, ARTIFACT_FILENAMES, limits, strict=True
    ):
        artifact = _exact_keys(raw_artifact, _ARTIFACT_FIELDS)
        if artifact["filename"] != expected_name:
            raise _fail()
        byte_count = _positive(artifact["bytes"])
        if byte_count > maximum:
            raise _fail()
        artifacts.append(
            _ArtifactContract(
                filename=expected_name,
                byte_count=byte_count,
                sha256=_text(artifact["sha256"], _SHA256_RE),
            )
        )
    return artifacts[0], artifacts[1]


def _parse_evidence_report(raw: bytes) -> _EvidenceBindings:
    value = _exact_keys(
        _canonical_object(raw, maximum=MAX_CORE_EVIDENCE_REPORT_BYTES), _REPORT_FIELDS
    )
    if (
        type(value["schemaVersion"]) is not int
        or value["schemaVersion"] != 1
        or value["result"] != "ACCEPTED"
    ):
        raise _fail()
    durations = _exact_keys(value["durationNanoseconds"], _DURATION_FIELDS)
    counts = _exact_keys(value["operationCounts"], _COUNT_FIELDS)
    for item in durations.values():
        _nonnegative(item)
    for item in counts.values():
        _nonnegative(item)
    if counts["syncBootstraps"] != 1:
        raise _fail()
    bindings = _exact_keys(value["bindings"], _BINDING_FIELDS)
    return _EvidenceBindings(
        shop_domain=_text(bindings["shopDomain"], _SHOP_RE),
        summary_sha256=_text(bindings["summarySha256"], _SHA256_RE),
        dataset_generation=_text(bindings["datasetGeneration"], _GENERATION_RE),
        catalog_content_sha256=_text(bindings["catalogContentSha256"], _SHA256_RE),
        projection_fingerprint=_text(bindings["projectionFingerprint"], _SHA256_RE),
        code_sha=_text(bindings["codeSha"], _CODE_SHA_RE),
    )


def _file_state(value: os.stat_result) -> _FileState:
    return _FileState(
        device=value.st_dev,
        inode=value.st_ino,
        byte_count=value.st_size,
        modified_ns=value.st_mtime_ns,
        changed_ns=value.st_ctime_ns,
        mode=value.st_mode,
        link_count=value.st_nlink,
    )


def _handle_matches_path(handle_state: _FileState, path_state: _FileState) -> bool:
    return (
        handle_state.device,
        handle_state.inode,
        handle_state.byte_count,
        handle_state.modified_ns,
        handle_state.mode,
        handle_state.link_count,
    ) == (
        path_state.device,
        path_state.inode,
        path_state.byte_count,
        path_state.modified_ns,
        path_state.mode,
        path_state.link_count,
    )


def _validated_existing_directory(value: object) -> Path:
    if type(value) is not _CONCRETE_PATH_TYPE or not value.is_absolute():
        raise _fail()
    resolved = value.resolve(strict=True)
    if (
        resolved != value
        or value.is_symlink()
        or not value.is_dir()
        or value.stat(follow_symlinks=False).st_mode & _WRITE_BITS
        or resolved == REPOSITORY_ROOT
        or resolved.is_relative_to(REPOSITORY_ROOT)
    ):
        raise _fail()
    return resolved


def _directory_names(directory: Path) -> tuple[str, ...]:
    with os.scandir(directory) as entries:
        names = tuple(entry.name for entry in islice(entries, len(PACKAGE_FILENAMES) + 1))
    if len(names) != len(PACKAGE_FILENAMES) or frozenset(names) != PACKAGE_FILENAMES:
        raise _fail()
    return names


def _open_pinned_file(stack: ExitStack, path: Path) -> _PinnedFile:
    before = _file_state(path.stat(follow_symlinks=False))
    if path.is_symlink() or not stat.S_ISREG(before.mode) or before.link_count != 1:
        raise _fail()
    handle = stack.enter_context(path.open("rb"))
    opened = _file_state(os.fstat(handle.fileno()))
    after = _file_state(path.stat(follow_symlinks=False))
    if not _handle_matches_path(opened, before) or after != before or before.mode & _WRITE_BITS:
        raise _fail()
    return _PinnedFile(path=path, handle=handle, state=before)


def _scan_file(pinned: _PinnedFile, *, maximum: int, retain: bool) -> tuple[str, bytes]:
    pinned.handle.seek(0)
    digest = hashlib.sha256()
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = pinned.handle.read(_READ_CHUNK_BYTES)
        if type(chunk) is not bytes:
            raise _fail()
        if not chunk:
            break
        total += len(chunk)
        if total > maximum:
            raise _fail()
        digest.update(chunk)
        if retain:
            chunks.append(chunk)
    if total != pinned.state.byte_count or not _handle_matches_path(
        _file_state(os.fstat(pinned.handle.fileno())), pinned.state
    ):
        raise _fail()
    return digest.hexdigest(), b"".join(chunks)


def _require_unchanged(
    directory: Path,
    directory_state: _FileState,
    files: tuple[_PinnedFile, ...],
) -> None:
    _directory_names(directory)
    if _file_state(directory.stat(follow_symlinks=False)) != directory_state:
        raise _fail()
    for pinned in files:
        if (
            not _handle_matches_path(_file_state(os.fstat(pinned.handle.fileno())), pinned.state)
            or _file_state(pinned.path.stat(follow_symlinks=False)) != pinned.state
        ):
            raise _fail()


def _records_from_projection(
    projection: CatalogProjection,
) -> tuple[CatalogProductRecordV1, ...]:
    with pagination._readonly_connection(projection.path) as connection:
        records = pagination._verify_projection_semantics(connection, projection.stats)
    projection.manifest.validate_records(records)
    return records


def _new_verified(
    projection: CatalogProjection,
    records: tuple[CatalogProductRecordV1, ...],
    bindings: _EvidenceBindings,
    manifest_sha256: str,
) -> VerifiedStagingGenerationV1:
    evidence = core_evidence._new_evidence(
        shop_domain=bindings.shop_domain,
        summary_sha256=bindings.summary_sha256,
        dataset_generation=bindings.dataset_generation,
        catalog_content_sha256=bindings.catalog_content_sha256,
        projection_fingerprint=bindings.projection_fingerprint,
        code_sha=bindings.code_sha,
    )
    result = object.__new__(VerifiedStagingGenerationV1)
    object.__setattr__(result, "projection", projection)
    object.__setattr__(result, "records", records)
    object.__setattr__(result, "evidence", evidence)
    object.__setattr__(result, "manifest_sha256", manifest_sha256)
    return result


def _open_staging_generation(
    directory: Path,
    expected_manifest_sha256: str,
) -> VerifiedStagingGenerationV1:
    package = _validated_existing_directory(directory)
    manifest_digest = _text(expected_manifest_sha256, _SHA256_RE)
    directory_state = _file_state(package.stat(follow_symlinks=False))
    _directory_names(package)
    with ExitStack() as stack:
        pinned_by_name = {
            filename: _open_pinned_file(stack, package / filename)
            for filename in (MANIFEST_FILENAME, *ARTIFACT_FILENAMES)
        }
        pinned = tuple(pinned_by_name.values())
        identities = {(item.state.device, item.state.inode) for item in pinned}
        if len(identities) != len(pinned):
            raise _fail()
        manifest_sha, manifest_raw = _scan_file(
            pinned_by_name[MANIFEST_FILENAME],
            maximum=MAX_STAGING_MANIFEST_BYTES,
            retain=True,
        )
        if manifest_sha != manifest_digest:
            raise _fail()
        evidence_contract, projection_contract = _parse_manifest(manifest_raw)
        evidence_sha, evidence_raw = _scan_file(
            pinned_by_name[EVIDENCE_FILENAME],
            maximum=MAX_CORE_EVIDENCE_REPORT_BYTES,
            retain=True,
        )
        projection_sha, _ = _scan_file(
            pinned_by_name[PROJECTION_FILENAME],
            maximum=MAX_PROJECTION_FILE_BYTES,
            retain=False,
        )
        if (
            evidence_contract.byte_count != pinned_by_name[EVIDENCE_FILENAME].state.byte_count
            or evidence_contract.sha256 != evidence_sha
            or projection_contract.byte_count
            != pinned_by_name[PROJECTION_FILENAME].state.byte_count
            or projection_contract.sha256 != projection_sha
        ):
            raise _fail()
        bindings = _parse_evidence_report(evidence_raw)
        _require_unchanged(package, directory_state, pinned)
        projection = CatalogProjection.open(
            pinned_by_name[PROJECTION_FILENAME].path,
            expected_generation=bindings.dataset_generation,
        )
        records = _records_from_projection(projection)
        if (
            projection.path != pinned_by_name[PROJECTION_FILENAME].path
            or projection._file_fingerprint.content_sha256 != projection_sha
            or projection_sha != bindings.projection_fingerprint
            or projection.manifest.dataset_generation != bindings.dataset_generation
            or projection.manifest.catalog_content_sha256 != bindings.catalog_content_sha256
        ):
            raise _fail()
        projection._assert_file_unchanged()
        _require_unchanged(package, directory_state, pinned)
        return _new_verified(projection, records, bindings, manifest_digest)


def open_staging_generation(
    directory: Path,
    expected_manifest_sha256: str,
) -> VerifiedStagingGenerationV1:
    """Open one exact package selected by an external manifest digest."""

    try:
        return _open_staging_generation(directory, expected_manifest_sha256)
    except Exception:
        rejection_message = _ERROR
    raise StagingGenerationError(rejection_message) from None


__all__ = (
    "ARTIFACT_FILENAMES",
    "EVIDENCE_FILENAME",
    "MANIFEST_FILENAME",
    "PROJECTION_FILENAME",
    "STAGING_PACKAGE_FORMAT",
    "STAGING_PACKAGE_SCHEMA_VERSION",
    "StagingGenerationError",
    "VerifiedStagingGenerationV1",
    "open_staging_generation",
)
