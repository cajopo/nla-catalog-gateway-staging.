#!/usr/bin/env python3
"""Run the local real catalog-core gate with value-free console output."""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
from pathlib import Path

from nla_catalog_gateway.core_evidence import (
    REPOSITORY_ROOT,
    _OperationalMeasurements,
    _VerificationResult,
    _verify_with_measurements,
)
from nla_catalog_gateway.generation_bundle import open_reconciled_generation

_CONCRETE_PATH_TYPE = type(Path())
_BUNDLE_ENV = "NLA_RECONCILED_BUNDLE_DIRECTORY"
_SUMMARY_ENV = "NLA_RECONCILIATION_SUMMARY_SHA256"
_PROJECTION_ENV = "NLA_CORE_EVIDENCE_PROJECTION_PATH"
_CODE_SHA_ENV = "NLA_CORE_EVIDENCE_CODE_SHA"
_REPORT_ENV = "NLA_CORE_EVIDENCE_REPORT_PATH"


def _validated_report_path(report_path: Path) -> Path:
    if type(report_path) is not _CONCRETE_PATH_TYPE or not report_path.is_absolute():
        raise ValueError
    resolved = report_path.resolve()
    if (
        resolved != report_path
        or resolved == REPOSITORY_ROOT
        or resolved.is_relative_to(REPOSITORY_ROOT)
        or not resolved.parent.is_dir()
        or resolved.exists()
    ):
        raise ValueError
    return resolved


def _report_bytes(result: _VerificationResult) -> bytes:
    if type(result) is not _VerificationResult:
        raise ValueError
    measurements = result.measurements
    if type(measurements) is not _OperationalMeasurements:
        raise ValueError
    durations = {
        "facetEvaluation": measurements.facet_evaluation_nanoseconds,
        "paginationTraversal": measurements.pagination_traversal_nanoseconds,
        "projectionBuild": measurements.projection_build_nanoseconds,
        "searchQuery": measurements.search_query_nanoseconds,
        "syncBootstrap": measurements.sync_bootstrap_nanoseconds,
    }
    counts = {
        "facetEvaluations": measurements.facet_evaluation_count,
        "paginationPages": measurements.pagination_page_count,
        "searchQueries": measurements.search_query_count,
        "syncBootstraps": 1,
    }
    if any(
        type(value) is not int or value < 0 for value in (*durations.values(), *counts.values())
    ):
        raise ValueError
    return json.dumps(
        {
            "bindings": {
                "catalogContentSha256": result.evidence.catalog_content_sha256,
                "codeSha": result.evidence.code_sha,
                "datasetGeneration": result.evidence.dataset_generation,
                "projectionFingerprint": result.evidence.projection_fingerprint,
                "shopDomain": result.evidence.shop_domain,
                "summarySha256": result.evidence.summary_sha256,
            },
            "durationNanoseconds": durations,
            "operationCounts": counts,
            "result": "ACCEPTED",
            "schemaVersion": 1,
        },
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _write_report(report_path: Path, result: _VerificationResult) -> None:
    destination = _validated_report_path(report_path)
    raw = _report_bytes(result)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".nla-core-evidence-",
        suffix=".tmp",
        dir=destination.parent,
    )
    temporary = Path(temporary_name)
    installed = False
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        os.link(temporary, destination)
        installed = True
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            if installed:
                destination.chmod(stat.S_IMODE(destination.stat().st_mode) | stat.S_IWUSR)
                destination.unlink()
            raise


def run_proof(
    bundle_directory: Path,
    expected_summary_sha256: str,
    projection_path: Path,
    code_sha: str,
    report_path: Path,
) -> None:
    """Verify one separately selected bundle without retaining an output file."""

    checked_report_path = _validated_report_path(report_path)
    resolved_bundle = bundle_directory.resolve()
    resolved_projection = projection_path.resolve()
    if (
        resolved_projection == resolved_bundle
        or resolved_projection.is_relative_to(resolved_bundle)
        or checked_report_path == resolved_bundle
        or checked_report_path.is_relative_to(resolved_bundle)
    ):
        raise ValueError
    with open_reconciled_generation(bundle_directory, expected_summary_sha256) as verified:
        result = _verify_with_measurements(
            verified,
            projection_path=projection_path,
            code_sha=code_sha,
        )
    _write_report(checked_report_path, result)


def main() -> int:
    arguments = tuple(sys.argv[1:])
    accepted = False
    try:
        if arguments:
            raise ValueError
        run_proof(
            Path(os.environ[_BUNDLE_ENV]),
            os.environ[_SUMMARY_ENV],
            Path(os.environ[_PROJECTION_ENV]),
            os.environ[_CODE_SHA_ENV],
            Path(os.environ[_REPORT_ENV]),
        )
        accepted = True
    except Exception:
        accepted = False
    print(f"VALUE_FREE_RESULT: {'ACCEPTED' if accepted else 'REJECTED'}")
    return 0 if accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main", "run_proof"]
