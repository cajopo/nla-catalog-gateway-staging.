"""Observe existing catalog jobs read-only; publish only a sanitized local status."""

import argparse
from datetime import UTC, datetime
from pathlib import Path

from nla_catalog_gateway.operational_health import (
    MAX_SOURCE_AGE_SECONDS,
    MIN_FREE_BYTES,
    REASONS,
    ObserverPaths,
    collect,
    write_observation,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("refresh-root", "market-root", "store", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--min-free-bytes", type=int, default=MIN_FREE_BYTES)
    parser.add_argument("--max-source-age-seconds", type=int, default=MAX_SOURCE_AGE_SECONDS)
    args = parser.parse_args(argv)
    now = datetime.now(UTC)
    reason = "observation_unknown"
    try:
        if args.min_free_bytes <= 0 or args.max_source_age_seconds <= 0:
            raise ValueError("invalid disk threshold")
        reason = collect(
            ObserverPaths(args.refresh_root, args.market_root, args.store),
            now=now,
            min_free_bytes=args.min_free_bytes,
            max_source_age_seconds=args.max_source_age_seconds,
        )
    except Exception:
        reason = "observation_unknown"
    if reason not in REASONS:
        reason = "observation_unknown"
    print("OPERATIONAL_HEALTH:" + reason)
    try:
        write_observation(args.output, now=now, healthy=reason == "healthy")
    except Exception:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
