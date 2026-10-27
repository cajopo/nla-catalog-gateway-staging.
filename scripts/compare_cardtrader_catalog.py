"""Compare a complete capture with a checksum-pinned SQLite projection, read-only."""

import argparse
import hashlib
import json
import os
import re
import sqlite3
from contextlib import closing
from pathlib import Path

from nla_catalog_gateway.cardtrader_capture import compare_captured_catalog

# Observed category contracts; unknown categories are reported, not guessed.
CATEGORIES = {
    1: (1, "Magic Single Card", "single"),
    2: (1, "Magic Token/Emblem", "single"),
    3: (1, "Magic Oversized", "single"),
    44: (4, "Yu-Gi-Oh! Singles", "single"),
    76: (4, "Yu-Gi-Oh! Oversized", "single"),
    73: (5, "Pokémon Singles", "single"),
    78: (5, "Pokémon Oversized", "single"),
    192: (15, "One Piece Single Card", "single"),
    255: (15, "One Piece DON Token", "single"),
    299: (15, "One Piece Oversized", "single"),
    54: (4, "Yu-Gi-Oh! Boosters Box", "sealed"),
    214: (18, "Lorcana Singles", "single"),
    230: (18, "Lorcana Oversized", "single"),
    270: (18, "Lorcana Token", "single"),
    258: (22, "Riftbound Singles", "single"),
    284: (22, "Riftbound Oversized", "single"),
    215: (18, "Lorcana Booster Boxes", "sealed"),
    216: (18, "Lorcana Boosters", "sealed"),
    217: (18, "Lorcana Bundles & Prerelease Kits", "sealed"),
    218: (18, "Lorcana Box Sets", "sealed"),
    219: (18, "Lorcana Starter Decks", "sealed"),
    320: (18, "Lorcana Cases & Displays", "sealed"),
    259: (22, "Riftbound Booster Boxes", "sealed"),
    260: (22, "Riftbound Boosters", "sealed"),
    261: (22, "Riftbound Bundles", "sealed"),
    262: (22, "Riftbound Starter Decks", "sealed"),
    263: (22, "Riftbound Box Sets", "sealed"),
    325: (22, "Riftbound Cases & Displays", "sealed"),
    # A complete set is not a single printing; do not infer its product family.
    231: (18, "Lorcana Complete Sets", "unclassified"),
    283: (22, "Riftbound Complete Sets", "unclassified"),
}


def compare_projection(capture: Path, projection: Path, expected_sha: str) -> dict:
    if (
        not projection.is_absolute()
        or projection.is_symlink()
        or re.fullmatch(r"[0-9a-f]{64}", expected_sha) is None
        or any(Path(str(projection) + suffix).exists() for suffix in ("-wal", "-shm", "-journal"))
    ):
        raise ValueError("immutable_pinned_projection_required")

    def digest():
        with projection.open("rb") as source:
            return hashlib.file_digest(source, "sha256").hexdigest()

    if digest() != expected_sha:
        raise ValueError("projection_digest_mismatch")
    fields = ("productGid", "game", "productFamily", "syncSourceId", "powerToolsSourceId")
    with closing(sqlite3.connect(projection.as_uri() + "?mode=ro", uri=True)) as database:
        database.execute("PRAGMA query_only=ON")
        metadata = json.loads(
            database.execute("SELECT dataset_manifest_json FROM projection_metadata").fetchone()[0]
        )
        query = """SELECT json_extract(product_record_json,'$.productGid'),
            json_extract(product_record_json,'$.game'),
            json_extract(product_record_json,'$.productFamily'),
            json_extract(product_record_json,'$.syncSourceId'),
            json_extract(product_record_json,'$.powerToolsSourceId') FROM products"""
        products = [dict(zip(fields, row, strict=True)) for row in database.execute(query)]
    result = compare_captured_catalog(capture, products, CATEGORIES)
    if digest() != expected_sha:
        raise ValueError("projection_changed")
    return {
        **result,
        "projectionSha256": expected_sha,
        "projectionProducts": len(products),
        "snapshotGeneratedAt": metadata["generatedAt"],
        "scope": "supplied projection only; not proof of current Shopify absence",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--projection", type=Path, required=True)
    parser.add_argument("--projection-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if not args.output.is_absolute():
            raise ValueError("absolute_output_required")
        result = compare_projection(args.capture, args.projection, args.projection_sha256)
        with os.fdopen(
            os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w"
        ) as output:
            json.dump(result, output)
            output.flush()
            os.fsync(output.fileno())
        print(json.dumps({k: v for k, v in result.items() if k != "details"}))
        return 0
    except Exception:
        print(json.dumps({"status": "comparison_failed", "creationApproved": False}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
