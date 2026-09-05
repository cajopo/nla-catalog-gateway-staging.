#!/usr/bin/env python3
"""Reconcile two downloaded Shopify Bulk JSONL parts without network access."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

from nla_catalog_gateway import bulk
from nla_catalog_gateway import reconciliation as reconciliation_model
from nla_catalog_gateway.reconciliation import (
    BulkOperationTerminalEvidenceV1,
    ReconciledCatalogGenerationV1,
    ReconciliationExpectationV1,
    SnapshotPart,
    SnapshotPartInputV1,
    SnapshotPartManifestV1,
    create_snapshot_part_manifest,
    reconcile_snapshot_parts,
)
from nla_catalog_gateway.taxonomy import load_taxonomy

CONTROL_DOCUMENT_MAX_BYTES = 64 * 1024
SUMMARY_SCHEMA_VERSION = 1
TAXONOMY_REPORT_SCHEMA_VERSION = 1

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_CONCRETE_PATH_TYPE = type(Path())
_OUTPUT_FILENAMES = frozenset(
    {
        "catalog-records.v1.jsonl",
        "dataset-manifest.v1.json",
        "products-part-manifest.v1.json",
        "reconciliation-summary.v1.json",
        "source-manifest.v2.json",
        "taxonomy-report.v1.json",
        "variants-part-manifest.v1.json",
    }
)
_EXPECTATION_KEYS = {
    "apiVersion",
    "expectedActiveOnlineStorePublishedProductCount",
    "onlineStorePublicationGid",
    "productCount",
    "schemaVersion",
    "shopDomain",
    "snapshotSetId",
    "sourceCodeSha",
    "variantCount",
}
_TERMINAL_KEYS = {
    "completedAt",
    "createdAt",
    "errorCode",
    "fileSize",
    "objectCount",
    "operationId",
    "operationType",
    "partialDataUrlPresent",
    "query",
    "rootObjectCount",
    "schemaVersion",
    "status",
    "urlPresent",
}


class ReconciliationCliError(ValueError):
    """Raised when local CLI inputs or output boundaries are unsafe."""


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        del message
        raise ReconciliationCliError("command arguments are invalid")


@dataclass(frozen=True, slots=True)
class _FileIdentity:
    device: int
    inode: int


@dataclass(frozen=True, slots=True)
class _ArtifactEvidence:
    filename: str
    sha256: str
    byte_count: int
    record_count: int

    def as_dict(self) -> dict[str, object]:
        return {
            "bytes": self.byte_count,
            "filename": self.filename,
            "recordCount": self.record_count,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class _TerminalQueryAuditEvidence:
    part: SnapshotPart
    approved_query_sha256: str
    raw_terminal_query_sha256: str
    transport: str

    def as_dict(self) -> dict[str, str]:
        return {
            "approvedQuerySha256": self.approved_query_sha256,
            "part": self.part.value,
            "rawTerminalQuerySha256": self.raw_terminal_query_sha256,
            "transport": self.transport,
        }


def _canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (RecursionError, TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ReconciliationCliError("generated evidence is not canonical JSON") from exc


def _path_has_alias(path: Path) -> bool:
    current = path
    while True:
        try:
            if current.is_symlink() or current.is_junction():
                return True
        except OSError as exc:
            raise ReconciliationCliError("filesystem alias state cannot be verified") from exc
        if current.parent == current:
            return False
        current = current.parent


def _contains_parent_reference(path: Path) -> bool:
    return any(part == ".." for part in path.parts)


def _is_within(path: Path, parent: Path) -> bool:
    try:
        common = os.path.commonpath(
            (os.path.normcase(os.fspath(path)), os.path.normcase(os.fspath(parent)))
        )
    except ValueError:
        return False
    return common == os.path.normcase(os.fspath(parent))


def _regular_file(
    value: object,
    context: str,
    *,
    external: bool,
) -> tuple[Path, _FileIdentity]:
    if type(value) is not _CONCRETE_PATH_TYPE:
        raise ReconciliationCliError(f"{context} must be a concrete filesystem path")
    path = value
    if not path.is_absolute() or _contains_parent_reference(path):
        raise ReconciliationCliError(f"{context} must be an absolute normalized path")
    if _path_has_alias(path):
        raise ReconciliationCliError(f"{context} must not use filesystem aliases")
    try:
        resolved = path.resolve(strict=True)
        facts = resolved.stat()
    except (OSError, RuntimeError) as exc:
        raise ReconciliationCliError(f"{context} is unavailable") from exc
    if not stat.S_ISREG(facts.st_mode) or facts.st_nlink != 1:
        raise ReconciliationCliError(f"{context} must be one regular, unaliased file")
    if external and _is_within(resolved, REPOSITORY_ROOT):
        raise ReconciliationCliError(f"{context} must be external to the repository")
    return resolved, _FileIdentity(facts.st_dev, facts.st_ino)


def _load_control_document(path: Path, context: str) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            raw = handle.read(CONTROL_DOCUMENT_MAX_BYTES + 1)
    except OSError as exc:
        raise ReconciliationCliError(f"{context} cannot be read") from exc
    if not raw or len(raw) > CONTROL_DOCUMENT_MAX_BYTES:
        raise ReconciliationCliError(f"{context} violates the byte bound")
    try:
        value = bulk._strict_json(raw, context)
    except bulk.BulkContractError as exc:
        raise ReconciliationCliError(f"{context} is invalid") from exc
    if type(value) is not dict:
        raise ReconciliationCliError(f"{context} must be an object")
    return value


def _require_schema_version(payload: dict[str, Any], context: str) -> None:
    if type(payload["schemaVersion"]) is not int or payload["schemaVersion"] != 1:
        raise ReconciliationCliError(f"{context} schemaVersion must be integer 1")


def _load_expectation(path: Path) -> ReconciliationExpectationV1:
    payload = _load_control_document(path, "reconciliation expectation")
    try:
        bulk._exact_keys(payload, _EXPECTATION_KEYS, "reconciliation expectation")
    except bulk.BulkContractError as exc:
        raise ReconciliationCliError("reconciliation expectation has invalid fields") from exc
    _require_schema_version(payload, "reconciliation expectation")
    return ReconciliationExpectationV1(
        snapshot_set_id=payload["snapshotSetId"],
        shop_domain=payload["shopDomain"],
        api_version=payload["apiVersion"],
        online_store_publication_gid=payload["onlineStorePublicationGid"],
        source_code_sha=payload["sourceCodeSha"],
        product_count=payload["productCount"],
        variant_count=payload["variantCount"],
        expected_active_online_store_published_product_count=payload[
            "expectedActiveOnlineStorePublishedProductCount"
        ],
    )


def _load_terminal_evidence(path: Path, context: str) -> BulkOperationTerminalEvidenceV1:
    payload = _load_control_document(path, context)
    try:
        bulk._exact_keys(payload, _TERMINAL_KEYS, context)
    except bulk.BulkContractError as exc:
        raise ReconciliationCliError(f"{context} has invalid fields") from exc
    _require_schema_version(payload, context)
    return BulkOperationTerminalEvidenceV1(
        operation_id=payload["operationId"],
        operation_type=payload["operationType"],
        status=payload["status"],
        error_code=payload["errorCode"],
        query=payload["query"],
        created_at=payload["createdAt"],
        completed_at=payload["completedAt"],
        file_size=payload["fileSize"],
        object_count=payload["objectCount"],
        root_object_count=payload["rootObjectCount"],
        url_present=payload["urlPresent"],
        partial_data_url_present=payload["partialDataUrlPresent"],
    )


def _terminal_query_audit(
    *,
    part: SnapshotPart,
    terminal: BulkOperationTerminalEvidenceV1,
    query_path: Path,
) -> _TerminalQueryAuditEvidence:
    canonical_query = reconciliation_model._read_query_bytes(query_path)
    transport = reconciliation_model._terminal_query_transport_mode(terminal.query, canonical_query)
    return _TerminalQueryAuditEvidence(
        part=part,
        approved_query_sha256=hashlib.sha256(canonical_query).hexdigest(),
        raw_terminal_query_sha256=hashlib.sha256(terminal.query.encode("utf-8")).hexdigest(),
        transport=transport,
    )


def _validated_output_directory(value: object) -> Path:
    if type(value) is not _CONCRETE_PATH_TYPE:
        raise ReconciliationCliError("output directory must be a concrete filesystem path")
    path = value
    if not path.is_absolute() or _contains_parent_reference(path):
        raise ReconciliationCliError("output directory must be an absolute normalized path")
    for part in path.parts:
        if part == path.anchor:
            continue
        if ":" in part or (part and part.rstrip(" .") != part):
            raise ReconciliationCliError("output directory contains an unsafe path component")
    parent = path.parent
    if _path_has_alias(parent):
        raise ReconciliationCliError("output directory parent must not use filesystem aliases")
    try:
        resolved_parent = parent.resolve(strict=True)
        parent_facts = resolved_parent.stat()
    except (OSError, RuntimeError) as exc:
        raise ReconciliationCliError("output directory parent is unavailable") from exc
    if not stat.S_ISDIR(parent_facts.st_mode):
        raise ReconciliationCliError("output directory parent must be a directory")
    resolved = resolved_parent / path.name
    if _is_within(resolved, REPOSITORY_ROOT):
        raise ReconciliationCliError("output directory must be external to the repository")
    if os.path.lexists(resolved):
        raise ReconciliationCliError("output directory must not already exist")
    return resolved


def _directory_identity(path: Path) -> _FileIdentity:
    try:
        facts = path.stat()
    except OSError as exc:
        raise ReconciliationCliError("output directory identity cannot be verified") from exc
    if not stat.S_ISDIR(facts.st_mode) or _path_has_alias(path):
        raise ReconciliationCliError("output directory is not a safe directory")
    return _FileIdentity(facts.st_dev, facts.st_ino)


def _require_directory_identity(path: Path, expected: _FileIdentity) -> None:
    if _directory_identity(path) != expected:
        raise ReconciliationCliError("output directory identity changed")


def _open_output_file(
    directory: Path,
    identity: _FileIdentity,
    filename: str,
    created: list[Path],
) -> tuple[Path, Any]:
    if filename not in _OUTPUT_FILENAMES or Path(filename).name != filename:
        raise ReconciliationCliError("output filename is not approved")
    _require_directory_identity(directory, identity)
    path = directory / filename
    try:
        handle = path.open("xb")
    except OSError as exc:
        raise ReconciliationCliError("output artifact cannot be created exclusively") from exc
    created.append(path)
    try:
        facts = os.fstat(handle.fileno())
        if not stat.S_ISREG(facts.st_mode) or facts.st_nlink != 1:
            raise ReconciliationCliError("output artifact is not a regular unaliased file")
    except BaseException:
        handle.close()
        raise
    return path, handle


def _write_bytes(
    directory: Path,
    identity: _FileIdentity,
    filename: str,
    raw: bytes,
    created: list[Path],
    *,
    record_count: int = 1,
) -> _ArtifactEvidence:
    _path, handle = _open_output_file(directory, identity, filename, created)
    try:
        with handle:
            written = handle.write(raw)
            if written != len(raw):
                raise ReconciliationCliError("output artifact write was incomplete")
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise ReconciliationCliError("output artifact cannot be written safely") from exc
    return _ArtifactEvidence(filename, hashlib.sha256(raw).hexdigest(), len(raw), record_count)


def _write_records(
    directory: Path,
    identity: _FileIdentity,
    generation: ReconciledCatalogGenerationV1,
    created: list[Path],
) -> _ArtifactEvidence:
    filename = "catalog-records.v1.jsonl"
    _path, handle = _open_output_file(directory, identity, filename, created)
    digest = hashlib.sha256()
    byte_count = 0
    record_count = 0
    try:
        with handle:
            for record in generation.records:
                raw = record.to_json_bytes() + b"\n"
                written = handle.write(raw)
                if written != len(raw):
                    raise ReconciliationCliError("catalog record write was incomplete")
                digest.update(raw)
                byte_count += len(raw)
                record_count += 1
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise ReconciliationCliError("catalog records cannot be written safely") from exc
    if record_count != generation.dataset_manifest.included_product_count:
        raise ReconciliationCliError("catalog record output count is inconsistent")
    return _ArtifactEvidence(filename, digest.hexdigest(), byte_count, record_count)


def _cleanup_created_output(
    directory: Path,
    identity: _FileIdentity,
    created: list[Path],
) -> None:
    try:
        _require_directory_identity(directory, identity)
        for path in reversed(created):
            if path.parent != directory or not os.path.lexists(path):
                continue
            facts = path.lstat()
            if not stat.S_ISREG(facts.st_mode) or facts.st_nlink != 1:
                raise ReconciliationCliError("unsafe output artifact cannot be cleaned")
            path.unlink()
        directory.rmdir()
    except (OSError, ReconciliationCliError) as exc:
        raise ReconciliationCliError("incomplete output could not be cleaned safely") from exc


def _cleanup_empty_output_directory(directory: Path) -> None:
    try:
        facts = directory.lstat()
        if not stat.S_ISDIR(facts.st_mode) or directory.is_symlink() or directory.is_junction():
            raise ReconciliationCliError("created output path is no longer a safe directory")
        directory.rmdir()
    except (OSError, ReconciliationCliError) as exc:
        raise ReconciliationCliError("empty output directory could not be cleaned safely") from exc


def _write_generation_output(
    output_directory: Path,
    products_manifest: SnapshotPartManifestV1,
    variants_manifest: SnapshotPartManifestV1,
    generation: ReconciledCatalogGenerationV1,
    terminal_query_audits: tuple[_TerminalQueryAuditEvidence, _TerminalQueryAuditEvidence],
) -> dict[str, object]:
    taxonomy_bytes = _canonical_json_bytes(
        {
            "schemaVersion": TAXONOMY_REPORT_SCHEMA_VERSION,
            **generation.taxonomy_report.as_dict(),
        }
    )
    static_artifacts = (
        ("dataset-manifest.v1.json", generation.dataset_manifest.to_json_bytes()),
        ("products-part-manifest.v1.json", products_manifest.to_json_bytes()),
        ("source-manifest.v2.json", generation.source_manifest_bytes),
        ("taxonomy-report.v1.json", taxonomy_bytes),
        ("variants-part-manifest.v1.json", variants_manifest.to_json_bytes()),
    )
    directory = _validated_output_directory(output_directory)
    created: list[Path] = []
    try:
        directory.mkdir(mode=0o700, parents=False, exist_ok=False)
    except OSError as exc:
        raise ReconciliationCliError("output directory cannot be created safely") from exc
    try:
        identity = _directory_identity(directory)
    except ReconciliationCliError as exc:
        try:
            _cleanup_empty_output_directory(directory)
        except ReconciliationCliError as cleanup_error:
            raise cleanup_error from exc
        raise ReconciliationCliError("output directory cannot be created safely") from exc
    try:
        artifacts = [
            _write_bytes(directory, identity, filename, raw, created)
            for filename, raw in static_artifacts
        ]
        artifacts.append(_write_records(directory, identity, generation, created))
        artifacts.sort(key=lambda item: item.filename)
        summary = {
            "artifacts": [item.as_dict() for item in artifacts],
            "capabilityPromotion": "not-performed",
            "catalogRecordCount": len(generation.records),
            "classifiedProductCount": generation.taxonomy_report.classified,
            "datasetActivation": "not-performed",
            "datasetGeneration": generation.dataset_manifest.dataset_generation,
            "schemaVersion": SUMMARY_SCHEMA_VERSION,
            "snapshotSetId": generation.source_manifest.snapshot_set_id,
            "sourceGeneration": generation.source_manifest.source_generation,
            "status": "reconciled-provisional",
            "taxonomyRuleVersion": generation.taxonomy_report.rule_version,
            "terminalQueryAudits": [item.as_dict() for item in terminal_query_audits],
            "unclassifiedProductCount": generation.taxonomy_report.unclassified,
            "variantCount": generation.source_manifest.variant_count,
        }
        summary_bytes = _canonical_json_bytes(summary)
        _write_bytes(
            directory,
            identity,
            "reconciliation-summary.v1.json",
            summary_bytes,
            created,
        )
        _require_directory_identity(directory, identity)
        return summary
    except BaseException as exc:
        try:
            _cleanup_created_output(directory, identity, created)
        except ReconciliationCliError as cleanup_error:
            raise cleanup_error from exc
        raise


def run_reconciliation(
    *,
    products_snapshot: Path,
    variants_snapshot: Path,
    products_query: Path,
    variants_query: Path,
    products_terminal: Path,
    variants_terminal: Path,
    expectation_path: Path,
    output_directory: Path,
) -> dict[str, object]:
    """Validate external evidence, reconcile it, and publish one provisional output set."""

    external_values = (
        (products_snapshot, "products snapshot"),
        (variants_snapshot, "variants snapshot"),
        (products_terminal, "products terminal evidence"),
        (variants_terminal, "variants terminal evidence"),
        (expectation_path, "reconciliation expectation"),
    )
    resolved_external = [
        _regular_file(path, context, external=True) for path, context in external_values
    ]
    products_query_path, products_query_identity = _regular_file(
        products_query, "products query", external=False
    )
    variants_query_path, variants_query_identity = _regular_file(
        variants_query, "variants query", external=False
    )
    identities = [identity for _path, identity in resolved_external]
    identities.extend((products_query_identity, variants_query_identity))
    if len(set(identities)) != len(identities):
        raise ReconciliationCliError("input files must have distinct identities")
    (
        (products_snapshot_path, _products_snapshot_identity),
        (variants_snapshot_path, _variants_snapshot_identity),
        (products_terminal_path, _products_terminal_identity),
        (variants_terminal_path, _variants_terminal_identity),
        (resolved_expectation_path, _expectation_identity),
    ) = resolved_external
    expectation = _load_expectation(resolved_expectation_path)
    products_terminal_evidence = _load_terminal_evidence(
        products_terminal_path, "products terminal evidence"
    )
    variants_terminal_evidence = _load_terminal_evidence(
        variants_terminal_path, "variants terminal evidence"
    )
    terminal_query_audits = (
        _terminal_query_audit(
            part=SnapshotPart.PRODUCTS,
            terminal=products_terminal_evidence,
            query_path=products_query_path,
        ),
        _terminal_query_audit(
            part=SnapshotPart.VARIANTS,
            terminal=variants_terminal_evidence,
            query_path=variants_query_path,
        ),
    )
    products_manifest = create_snapshot_part_manifest(
        products_snapshot_path,
        query_path=products_query_path,
        part=SnapshotPart.PRODUCTS,
        expectation=expectation,
        terminal_evidence=products_terminal_evidence,
    )
    variants_manifest = create_snapshot_part_manifest(
        variants_snapshot_path,
        query_path=variants_query_path,
        part=SnapshotPart.VARIANTS,
        expectation=expectation,
        terminal_evidence=variants_terminal_evidence,
    )
    generation = reconcile_snapshot_parts(
        (
            SnapshotPartInputV1(
                manifest=products_manifest,
                snapshot_path=products_snapshot_path,
                query_path=products_query_path,
            ),
            SnapshotPartInputV1(
                manifest=variants_manifest,
                snapshot_path=variants_snapshot_path,
                query_path=variants_query_path,
            ),
        ),
        expectation=expectation,
        taxonomy_config=load_taxonomy(),
    )
    return _write_generation_output(
        output_directory,
        products_manifest,
        variants_manifest,
        generation,
        terminal_query_audits,
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = _SafeArgumentParser(description=__doc__)
    parser.add_argument("--products-jsonl", required=True, type=Path)
    parser.add_argument("--variants-jsonl", required=True, type=Path)
    parser.add_argument("--products-query", required=True, type=Path)
    parser.add_argument("--variants-query", required=True, type=Path)
    parser.add_argument("--products-terminal", required=True, type=Path)
    parser.add_argument("--variants-terminal", required=True, type=Path)
    parser.add_argument("--expectation", required=True, type=Path)
    parser.add_argument("--output-directory", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        summary = run_reconciliation(
            products_snapshot=args.products_jsonl,
            variants_snapshot=args.variants_jsonl,
            products_query=args.products_query,
            variants_query=args.variants_query,
            products_terminal=args.products_terminal,
            variants_terminal=args.variants_terminal,
            expectation_path=args.expectation,
            output_directory=args.output_directory,
        )
        print(
            _canonical_json_bytes(
                {
                    "datasetGeneration": summary["datasetGeneration"],
                    "outputCreated": True,
                    "sourceGeneration": summary["sourceGeneration"],
                    "status": "ok",
                }
            ).decode("utf-8")
        )
        return 0
    except Exception:
        print("split snapshot reconciliation failed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ReconciliationCliError",
    "main",
    "parse_args",
    "run_reconciliation",
]
