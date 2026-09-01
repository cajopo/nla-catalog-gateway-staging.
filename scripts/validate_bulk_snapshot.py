#!/usr/bin/env python3
"""Validate a local Shopify Bulk JSONL source into an immutable candidate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from nla_catalog_gateway.bulk import (
    BulkContractError,
    build_source_candidate,
    load_source_evidence,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path, help="Downloaded JSONL file outside Git")
    parser.add_argument("--query", required=True, type=Path, help="Exact submitted query")
    parser.add_argument(
        "--evidence",
        required=True,
        type=Path,
        help="Sanitized terminal metadata JSON (never a download URL)",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="New immutable candidate directory outside Git",
    )
    parser.add_argument(
        "--expected-source-code-sha",
        required=True,
        help="Trusted reviewed 40-character Git SHA supplied independently of evidence",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        evidence = load_source_evidence(args.evidence)
        manifest = build_source_candidate(
            args.snapshot,
            query_path=args.query,
            evidence=evidence,
            expected_source_code_sha=args.expected_source_code_sha,
            final_directory=args.output,
            repository_root=REPOSITORY_ROOT,
        )
    except BulkContractError:
        print("source candidate rejected", file=sys.stderr)
        return 2
    print(json.dumps(manifest.as_dict(), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
