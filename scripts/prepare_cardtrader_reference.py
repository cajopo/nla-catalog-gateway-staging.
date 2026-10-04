"""Prepare missing-printing inputs and an unactivated reference; no Shopify writes."""

import argparse
import hashlib
import json
import os
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit

from nla_catalog_gateway.canonical_names import (
    MANIFEST_FILENAME,
    SIDECAR_FILENAME,
    CanonicalNameRecordV1,
    load_canonical_names,
    load_canonical_names_manifest,
)
from nla_catalog_gateway.canonical_reference_extension import build_extended_reference
from nla_catalog_gateway.card_metadata import CardMetadataV1
from nla_catalog_gateway.cardtrader_candidates import GAMES
from nla_catalog_gateway.taxonomy import Game
from scripts.compare_cardtrader_catalog import compare_projection

RARITY = {
    "magic": "mtg_rarity",
    "pokemon": "pokemon_rarity",
    "yugioh": "yugioh_rarity",
    "one-piece": "onepiece_rarity",
}


def prepare(capture, projection, projection_sha, parent, parent_sha, output, generator_sha):
    comparison = compare_projection(capture, projection, projection_sha)
    raw = (capture / "progress.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != comparison["captureSha256"]:
        raise ValueError("capture_changed")
    progress = json.loads(raw)

    def source(name):
        path = capture / name
        if path.is_symlink():
            raise ValueError("source_symlink")
        data = path.read_bytes()
        facts = progress["files"][name]
        if len(data) != facts["bytes"] or hashlib.sha256(data).hexdigest() != facts["sha256"]:
            raise ValueError("source_changed")
        return json.loads(data)

    expansions = {
        r["id"]: r
        for r in source("expansions.json")
        if type(r.get("game_id")) is int and r["game_id"] in GAMES
    }
    manifest = load_canonical_names_manifest(
        (parent / MANIFEST_FILENAME).read_bytes(), expected_sha256=parent_sha
    )
    with (parent / SIDECAR_FILENAME).open("rb") as stream:
        existing = load_canonical_names(stream, manifest=manifest)
    existing_ids = {}
    ambiguous_ids = set()
    for record in existing.values():
        if record.source_id in existing_ids:
            ambiguous_ids.add(record.source_id)
        existing_ids[record.source_id] = record
    grouped = defaultdict(list)
    for row in comparison["details"]:
        if row["decision"] == "absent_from_supplied_snapshot":
            grouped[row["sourceExpansionId"]].append(row)
    additions = []
    candidates = []
    exceptions = []

    def optional(value):
        if value is None or value == "":
            return None
        if type(value) is not str:
            raise ValueError("invalid_metadata")
        return value

    for expansion_id, decisions in sorted(grouped.items()):
        filename = f"blueprints-{expansion_id}.json"
        rows = source(filename)
        expansion = expansions[expansion_id]
        for decision in decisions:
            binding = dict(
                blueprintId=decision["blueprintId"],
                cardmarketIds=decision["cardmarketIds"],
                sourceFile=filename,
                sourceRowIndex=decision["sourceRowIndex"],
            )
            try:
                index = decision["sourceRowIndex"]
                if type(index) is not int or not 0 <= index < len(rows):
                    raise ValueError("invalid_source_row")
                row = rows[index]
                ids = decision["cardmarketIds"]
                game = Game(decision["game"])
                if (
                    row["id"] != decision["blueprintId"]
                    or row["card_market_ids"] != ids
                    or len(ids) != 1
                    or row["expansion_id"] != expansion_id
                    or row["game_id"] != expansion["game_id"]
                    or GAMES[row["game_id"]] != game.value
                    or decision["shopifyProductGids"]
                    or decision["creationApproved"] is not False
                ):
                    raise ValueError("identity_mismatch")
                properties = row[
                    "fixed_properties"
                ]  # Observed source contract, not editable defaults.
                if type(properties) is not dict:
                    raise ValueError("invalid_fixed_properties")
                record = CanonicalNameRecordV1(
                    game,
                    str(ids[0]),
                    row["name"],
                    CardMetadataV1(
                        optional(properties.get("collector_number")),
                        None,
                        optional(expansion["name"]),
                        optional(properties.get(RARITY[game.value])),
                    ),
                )
                image = urlsplit(row["image_url"])
                if (
                    image.scheme != "https"
                    or not image.hostname
                    or image.username
                    or image.password
                    or image.fragment
                ):
                    raise ValueError("invalid_source_image")
                if record.source_id in ambiguous_ids:
                    raise ValueError("ambiguous_canonical_identity")
                previous = existing_ids.get(record.source_id)
                if previous is not None and (
                    previous.game != game
                    or previous.canonical_card_name != record.canonical_card_name
                ):
                    raise ValueError("canonical_identity_conflict")
                chosen = previous or record
                metadata = chosen.card_metadata
                title = chosen.canonical_card_name
                if metadata and metadata.expansion_name:
                    title += " - " + metadata.expansion_name
                if metadata and metadata.collector_number:
                    title += " [" + metadata.collector_number + "]"
                if len(title) > 255:
                    raise ValueError("title_too_long")
                candidates.append(
                    {
                        **binding,
                        "game": game.value,
                        "cardmarketId": record.source_id,
                        "title": title,
                        "imageUrl": row["image_url"],
                        "canonicalMappingPreserved": previous is not None,
                        "creationApproved": False,
                    }
                )
                if previous is None:
                    additions.append(record)
            except (ValueError, KeyError, TypeError, IndexError):
                exceptions.append(
                    {**binding, "reason": "source_or_canonical_details_require_review"}
                )
    if (capture / "progress.json").read_bytes() != raw:
        raise ValueError("capture_changed")
    if additions:
        evidence = build_extended_reference(
            parent, parent_sha, additions, output_directory=output, generator_code_sha=generator_sha
        )
        reference = output / "bundle"
    else:
        output.mkdir(mode=0o700)
        evidence = dict(
            parentManifestSha256=parent_sha,
            manifestSha256=parent_sha,
            addedRecords=0,
            existingRecordsUnchanged=True,
            activated=False,
        )
        reference = parent
    result = dict(
        reference=str(reference),
        referenceEvidence=evidence,
        captureSha256=comparison["captureSha256"],
        projectionSha256=projection_sha,
        sourceStartedAt=comparison["sourceStartedAt"],
        candidates=candidates,
        exceptions=exceptions,
        creationApproved=False,
        shopifyChanged=False,
        requirement="Before creation: current Shopify identity check and reference activation",
    )
    with os.fdopen(
        os.open(output / "preparation.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w"
    ) as stream:
        json.dump(result, stream)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("capture", "projection", "parent", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("projection-sha256", "parent-sha256", "generator-sha"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    try:
        if not all(
            p.is_absolute() for p in (args.capture, args.projection, args.parent, args.output)
        ):
            raise ValueError("absolute_paths_required")
        result = prepare(
            args.capture,
            args.projection,
            args.projection_sha256,
            args.parent,
            args.parent_sha256,
            args.output,
            args.generator_sha,
        )
        print(
            json.dumps(
                dict(
                    status="reference_prepared",
                    candidates=len(result["candidates"]),
                    exceptions=len(result["exceptions"]),
                    addedRecords=result["referenceEvidence"]["addedRecords"],
                    activated=False,
                    shopifyChanged=False,
                )
            )
        )
        return 0
    except Exception:
        print(json.dumps(dict(status="preparation_failed", shopifyChanged=False)))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
