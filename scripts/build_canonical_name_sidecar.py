#!/usr/bin/env python3
"""Build the pinned canonical-name sidecar from four authoritative CSV exports."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from nla_catalog_gateway.canonical_names import CanonicalNamesError, build_canonical_name_sidecar
from nla_catalog_gateway.taxonomy import Game

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--magic", required=True, type=Path, help="Authoritative Magic CSV")
    parser.add_argument("--pokemon", required=True, type=Path, help="Authoritative Pokemon CSV")
    parser.add_argument("--yugioh", required=True, type=Path, help="Authoritative Yu-Gi-Oh CSV")
    parser.add_argument("--one-piece", required=True, type=Path, help="Authoritative One Piece CSV")
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="New output directory outside the repository",
    )
    parser.add_argument(
        "--generator-code-sha",
        required=True,
        help="Reviewed 40- or 64-character compiler code SHA",
    )
    return parser.parse_args(argv)


def _output_is_outside_repository(output: Path) -> bool:
    try:
        resolved_output = output.resolve(strict=False)
        repository = REPOSITORY_ROOT.resolve(strict=True)
    except (OSError, RuntimeError):
        return False
    return not resolved_output.is_relative_to(repository)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if not _output_is_outside_repository(args.output):
            raise CanonicalNamesError("canonical-name output must be outside the repository")
        manifest = build_canonical_name_sidecar(
            {
                Game.MAGIC: args.magic,
                Game.POKEMON: args.pokemon,
                Game.YUGIOH: args.yugioh,
                Game.ONE_PIECE: args.one_piece,
            },
            output_directory=args.output,
            generator_code_sha=args.generator_code_sha,
        )
    except CanonicalNamesError:
        print("canonical-name sidecar rejected", file=sys.stderr)
        return 2
    print(manifest.to_json_bytes().decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
