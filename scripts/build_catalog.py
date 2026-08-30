from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from app.sync.build_index import build_catalog


def main() -> None:
    parser = argparse.ArgumentParser(description="Build NLA catalog SQLite index")
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("database", type=Path)
    parser.add_argument("--expected-count", type=int)
    parser.add_argument("--dataset-version")
    args = parser.parse_args()
    result = build_catalog(
        args.snapshot,
        args.database,
        expected_count=args.expected_count,
        dataset_version=args.dataset_version,
    )
    print(json.dumps(asdict(result), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
