#!/usr/bin/env python3
"""Build one portable, immutable staging generation with value-free output."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path

from nla_catalog_gateway.core_evidence import _report_bytes, _verify_with_measurements
from nla_catalog_gateway.generation_bundle import open_reconciled_generation
from nla_catalog_gateway.pagination import CatalogProjection
from nla_catalog_gateway.staging_generation import (
    ARTIFACT_FILENAMES,
    EVIDENCE_FILENAME,
    MANIFEST_FILENAME,
    PROJECTION_FILENAME,
    REPOSITORY_ROOT,
    STAGING_PACKAGE_FORMAT,
    STAGING_PACKAGE_SCHEMA_VERSION,
    open_staging_generation,
)
from nla_catalog_gateway.sync import SyncCore

_CONCRETE_PATH_TYPE = type(Path())
_CODE_SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
_READ_ONLY_FILE_MODE = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH
_READ_ONLY_DIRECTORY_MODE = _READ_ONLY_FILE_MODE | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
_REPARSE_POINT_ATTRIBUTE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_CLEANUP_BOUNDARY_ERROR = "staging package cleanup boundary is invalid"
_WORK_FILENAMES = frozenset(
    {EVIDENCE_FILENAME, MANIFEST_FILENAME, PROJECTION_FILENAME, ".core-proof.sqlite3"}
)

_BUNDLE_ENV = "NLA_RECONCILED_BUNDLE_DIRECTORY"
_SUMMARY_ENV = "NLA_RECONCILIATION_SUMMARY_SHA256"
_CODE_SHA_ENV = "NLA_CORE_EVIDENCE_CODE_SHA"
_PACKAGE_ENV = "NLA_STAGING_GENERATION_PACKAGE_DIRECTORY"


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _validated_destination(directory: Path, bundle_directory: Path) -> Path:
    if type(directory) is not _CONCRETE_PATH_TYPE or not directory.is_absolute():
        raise ValueError
    destination = directory.resolve()
    bundle = bundle_directory.resolve()
    if (
        destination != directory
        or destination.exists()
        or destination.is_symlink()
        or not destination.parent.is_dir()
        or destination == REPOSITORY_ROOT
        or destination.is_relative_to(REPOSITORY_ROOT)
        or destination == bundle
        or destination.is_relative_to(bundle)
        or bundle.is_relative_to(destination)
    ):
        raise ValueError
    return destination


def _write_bytes(path: Path, raw: bytes) -> None:
    with path.open("xb") as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
    path.chmod(_READ_ONLY_FILE_MODE)


def _artifact(path: Path) -> dict[str, object]:
    raw_digest = hashlib.sha256()
    byte_count = 0
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            byte_count += len(chunk)
            raw_digest.update(chunk)
    if byte_count < 1:
        raise ValueError
    return {
        "bytes": byte_count,
        "filename": path.name,
        "sha256": raw_digest.hexdigest(),
    }


def _manifest_bytes(directory: Path) -> bytes:
    return _canonical_json_bytes(
        {
            "artifacts": [_artifact(directory / filename) for filename in ARTIFACT_FILENAMES],
            "packageFormat": STAGING_PACKAGE_FORMAT,
            "schemaVersion": STAGING_PACKAGE_SCHEMA_VERSION,
        }
    )


def _is_reparse_point(facts: os.stat_result) -> bool:
    return bool(getattr(facts, "st_file_attributes", 0) & _REPARSE_POINT_ATTRIBUTE)


def _directory_identity(directory: Path) -> tuple[int, int]:
    facts = directory.lstat()
    if not stat.S_ISDIR(facts.st_mode) or _is_reparse_point(facts):
        raise OSError(_CLEANUP_BOUNDARY_ERROR)
    return facts.st_dev, facts.st_ino


def _require_directory_identity(directory: Path, expected_identity: tuple[int, int]) -> None:
    try:
        current_identity = _directory_identity(directory)
    except OSError as exc:
        raise OSError(_CLEANUP_BOUNDARY_ERROR) from exc
    if current_identity != expected_identity:
        raise OSError(_CLEANUP_BOUNDARY_ERROR)


def _artifact_identity(path: Path) -> tuple[int, int]:
    try:
        facts = path.lstat()
    except OSError as exc:
        raise OSError(_CLEANUP_BOUNDARY_ERROR) from exc
    if not stat.S_ISREG(facts.st_mode) or facts.st_nlink != 1 or _is_reparse_point(facts):
        raise OSError(_CLEANUP_BOUNDARY_ERROR)
    return facts.st_dev, facts.st_ino


def _require_artifact_identity(path: Path, expected_identity: tuple[int, int]) -> None:
    if _artifact_identity(path) != expected_identity:
        raise OSError(_CLEANUP_BOUNDARY_ERROR)


def _cleanup_entries(
    directory: Path, expected_identity: tuple[int, int]
) -> tuple[tuple[Path, tuple[int, int]], ...]:
    _require_directory_identity(directory, expected_identity)
    names: list[str] = []
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                names.append(entry.name)
                if len(names) > len(_WORK_FILENAMES):
                    raise OSError(_CLEANUP_BOUNDARY_ERROR)
    except OSError as exc:
        raise OSError(_CLEANUP_BOUNDARY_ERROR) from exc
    _require_directory_identity(directory, expected_identity)
    if any(name not in _WORK_FILENAMES for name in names):
        raise OSError(_CLEANUP_BOUNDARY_ERROR)
    artifacts = tuple((directory / name, _artifact_identity(directory / name)) for name in names)
    _require_directory_identity(directory, expected_identity)
    return artifacts


def _cleanup_directory(directory: Path, expected_identity: tuple[int, int]) -> None:
    try:
        current_identity = _directory_identity(directory)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise OSError(_CLEANUP_BOUNDARY_ERROR) from exc
    if current_identity != expected_identity:
        raise OSError(_CLEANUP_BOUNDARY_ERROR)

    artifacts = _cleanup_entries(directory, expected_identity)
    _require_directory_identity(directory, expected_identity)
    directory.chmod(stat.S_IRWXU)
    for path, artifact_identity in artifacts:
        _require_directory_identity(directory, expected_identity)
        _require_artifact_identity(path, artifact_identity)
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        _require_directory_identity(directory, expected_identity)
        _require_artifact_identity(path, artifact_identity)
        path.unlink()
    _require_directory_identity(directory, expected_identity)
    directory.rmdir()


def _same_evidence(left: object, right: object) -> bool:
    fields = (
        "shop_domain",
        "summary_sha256",
        "dataset_generation",
        "catalog_content_sha256",
        "projection_fingerprint",
        "code_sha",
    )
    return all(getattr(left, name, None) == getattr(right, name, None) for name in fields)


def run_packaging(
    bundle_directory: Path,
    expected_summary_sha256: str,
    code_sha: str,
    package_directory: Path,
    *,
    incremental_core: SyncCore | None = None,
) -> str:
    """Build once, prove, package those exact bytes, and locally reopen them."""

    destination = _validated_destination(package_directory, bundle_directory)
    if type(code_sha) is not str or _CODE_SHA_RE.fullmatch(code_sha) is None:
        raise ValueError
    work = Path(tempfile.mkdtemp(prefix=".nla-staging-generation-", dir=destination.parent))
    work_identity = _directory_identity(work)
    published = False
    completed = False
    try:
        projection_path = work / PROJECTION_FILENAME
        with open_reconciled_generation(
            bundle_directory, expected_summary_sha256
        ) as verified_generation:
            options = {} if incremental_core is None else {"incremental_core": incremental_core}
            result = _verify_with_measurements(
                verified_generation,
                projection_path=projection_path,
                code_sha=code_sha,
                retain_projection=True,
                **options,
            )
            projection = result.projection
            if (
                type(projection) is not CatalogProjection
                or projection.path != projection_path
                or projection._file_fingerprint.content_sha256
                != result.evidence.projection_fingerprint
            ):
                raise ValueError
            report_raw = _report_bytes(result)
        # The bundle context has finished its checks; subsequent package opens
        # reconstruct the full catalog, so release the earlier graph first.
        del verified_generation
        _write_bytes(work / EVIDENCE_FILENAME, report_raw)
        manifest_raw = _manifest_bytes(work)
        manifest_sha256 = hashlib.sha256(manifest_raw).hexdigest()
        _write_bytes(work / MANIFEST_FILENAME, manifest_raw)
        _require_directory_identity(work, work_identity)
        work.chmod(_READ_ONLY_DIRECTORY_MODE)
        candidate = open_staging_generation(work, manifest_sha256)
        if not _same_evidence(candidate.evidence, result.evidence):
            raise ValueError
        del candidate
        if os.path.lexists(destination):
            raise ValueError
        _require_directory_identity(work, work_identity)
        os.rename(work, destination)
        published = True
        _require_directory_identity(destination, work_identity)
        installed = open_staging_generation(destination, manifest_sha256)
        if not _same_evidence(installed.evidence, result.evidence):
            raise ValueError
        completed = True
        return manifest_sha256
    finally:
        if not completed:
            _cleanup_directory(destination if published else work, work_identity)


def main() -> int:
    accepted = False
    try:
        if sys.argv[1:]:
            raise ValueError
        run_packaging(
            Path(os.environ[_BUNDLE_ENV]),
            os.environ[_SUMMARY_ENV],
            os.environ[_CODE_SHA_ENV],
            Path(os.environ[_PACKAGE_ENV]),
        )
        accepted = True
    except Exception:
        accepted = False
    print(f"VALUE_FREE_RESULT: {'ACCEPTED' if accepted else 'REJECTED'}")
    return 0 if accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main", "run_packaging"]
