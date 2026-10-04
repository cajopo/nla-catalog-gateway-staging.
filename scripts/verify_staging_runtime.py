"""Read-only candidate verification in the deployment's pinned runtime image.

Reuses the package reader and runtime binding; neither publishes a generation nor
contacts Shopify. Expected pins/count come from the accepted capture checkpoint,
not from the candidate being checked. Run in a bounded, network-isolated process.
"""

from __future__ import annotations

import argparse
import json
import re
import secrets
import sys
from collections import Counter
from pathlib import Path

from nla_catalog_gateway.pagination import CursorCodecV1
from nla_catalog_gateway.runtime_api import EvidenceBoundCatalogBackend
from nla_catalog_gateway.staging_generation import open_staging_generation


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError("invalid verification arguments")


def verify_runtime(
    *,
    candidate_directory: Path,
    manifest_sha256: str,
    code_sha: str,
    summary_sha256: str,
    record_count: int,
) -> dict:
    """Verify artifact bytes and their compatibility with this runtime version."""
    if (
        type(record_count) is not int
        or record_count < 1
        or type(summary_sha256) is not str
        or re.fullmatch(r"[0-9a-f]{64}", summary_sha256) is None
    ):
        raise ValueError("invalid expected capture evidence")
    verified = open_staging_generation(candidate_directory, manifest_sha256)
    if verified.evidence.summary_sha256 != summary_sha256 or len(verified.records) != record_count:
        raise ValueError("candidate differs from capture evidence")
    backend = EvidenceBoundCatalogBackend.from_staging_generation(
        verified, CursorCodecV1(secrets.token_bytes(32)), expected_code_sha=code_sha
    )
    return {
        "status": "verified",
        "runtimeBinding": True,
        "records": len(verified.records),
        "games": dict(
            Counter(
                record.game.value if record.game is not None else "unclassified"
                for record in verified.records
            )
        ),
        "manifestSha256": verified.manifest_sha256,
        "producerCodeSha": verified.evidence.code_sha,
        "summarySha256": verified.evidence.summary_sha256,
        "datasetGeneration": backend.active_generation,
        "activeCatalogChanged": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = _Parser(description=__doc__)
    parser.add_argument("--candidate-directory", type=Path, required=True)
    for name in ("manifest-sha256", "code-sha", "summary-sha256"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--record-count", type=int, required=True)
    try:
        result = verify_runtime(**vars(parser.parse_args(argv)))
    except (Exception, KeyboardInterrupt):
        print("Runtime verification failed; no catalog was activated.", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
