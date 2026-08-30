from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from app.normalization import normalize_text

EXPECTED_COUNTS = {
    "magic": 122531,
    "pokemon": 71605,
    "yugioh": 85992,
    "one-piece": 11663,
}
EXPECTED_EXACT = {
    ("magic", "Lightning Bolt"): 64,
    ("pokemon", "Pikachu"): 392,
    ("yugioh", "Blue-Eyes White Dragon"): 177,
    ("one-piece", "Monkey.D.Luffy"): 496,
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    parser.add_argument("--deep-count", type=int, default=25500)
    parser.add_argument("--relaxed-fixtures", action="store_true")
    args = parser.parse_args()
    connection = sqlite3.connect(args.database)
    connection.row_factory = sqlite3.Row
    failures = []
    report = {}
    try:
        report["integrity"] = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if report["integrity"] != "ok":
            failures.append(f"integrity={report['integrity']}")
        counts = {row["game"]: row["count"] for row in connection.execute("SELECT game, COUNT(*) AS count FROM products GROUP BY game")}
        report["counts"] = counts
        if counts != EXPECTED_COUNTS:
            failures.append(f"game counts mismatch: {counts}")
        exact = {}
        for (game, name), expected in EXPECTED_EXACT.items():
            actual = connection.execute(
                "SELECT COUNT(*) FROM products WHERE game=? AND normalized_name=?",
                (game, normalize_text(name)),
            ).fetchone()[0]
            exact[f"{game}:{name}"] = actual
            if not args.relaxed_fixtures and actual != expected:
                failures.append(f"exact fixture {game}/{name}: {actual} != {expected}")
            elif args.relaxed_fixtures and actual <= 0:
                failures.append(f"exact fixture missing {game}/{name}")
        report["exact"] = exact
        cross_game = {}
        for (source_game, name), _ in EXPECTED_EXACT.items():
            for game in EXPECTED_COUNTS:
                if game == source_game:
                    continue
                count = connection.execute(
                    "SELECT COUNT(*) FROM products WHERE game=? AND normalized_name=?",
                    (game, normalize_text(name)),
                ).fetchone()[0]
                cross_game[f"{name}->{game}"] = count
                if count:
                    failures.append(f"cross-game fixture {name} leaked into {game}: {count}")
        report["crossGame"] = cross_game
        last_name = ""
        last_id = 0
        seen = set()
        while len(seen) < args.deep_count:
            rows = connection.execute(
                """SELECT id, normalized_name FROM products
                WHERE game='magic' AND (normalized_name > ? OR (normalized_name = ? AND id > ?))
                ORDER BY normalized_name, id LIMIT 500""",
                (last_name, last_name, last_id),
            ).fetchall()
            if not rows:
                break
            for row in rows:
                if row["id"] in seen:
                    failures.append(f"duplicate during deep browse: {row['id']}")
                    break
                seen.add(row["id"])
            last_name = rows[-1]["normalized_name"]
            last_id = rows[-1]["id"]
        report["deepBrowseMagic"] = len(seen)
        if len(seen) < args.deep_count:
            failures.append(f"deep browse stopped at {len(seen)}")
        report["metadata"] = {row["key"]: row["value"] for row in connection.execute("SELECT key, value FROM metadata")}
    finally:
        connection.close()
    report["ok"] = not failures
    report["failures"] = failures
    print(json.dumps(report, indent=2, sort_keys=True))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
