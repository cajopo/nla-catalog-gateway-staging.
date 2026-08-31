#!/usr/bin/env python3
"""Validate a Shopify Bulk JSONL baseline and emit its reconciliation manifest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from nla_catalog_gateway.bulk_records import BulkContractError, load_bulk_snapshot


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("jsonl", type=Path, help="Downloaded Shopify Bulk JSONL file")
    parser.add_argument(
        "--online-store-publication-gid",
        required=True,
        help="Exact gid://shopify/Publication/... for the Online Store channel",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        help="Optional path for a deterministic JSON manifest",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        snapshot = load_bulk_snapshot(
            args.jsonl,
            online_store_publication_gid=args.online_store_publication_gid,
        )
    except BulkContractError as exc:
        print(f"baseline rejected: {exc}", file=sys.stderr)
        return 2

    rendered = json.dumps(snapshot.manifest(), indent=2, sort_keys=True) + "\n"
    if args.manifest is not None:
        args.manifest.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
