#!/usr/bin/env python3
"""Validate a Shopify catalog Bulk JSONL snapshot without importing it."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from nla_catalog_gateway.bulk_snapshot import SnapshotContractError, validate_bulk_snapshot


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--query", type=Path, required=True)
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--expected-products", type=int)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        manifest = validate_bulk_snapshot(
            args.snapshot,
            query_path=args.query,
            operation_id=args.operation_id,
            expected_products=args.expected_products,
        )
    except SnapshotContractError as exc:
        print(json.dumps({"valid": False, "contractError": str(exc)}, indent=2))
        return 2
    payload = manifest.as_dict()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if manifest.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
