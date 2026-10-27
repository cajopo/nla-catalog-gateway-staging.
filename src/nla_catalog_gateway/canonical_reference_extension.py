"""Append verified names using the existing CSV builder; never activate a reference."""

import csv
import hashlib
import json
from collections.abc import Iterable
from pathlib import Path

from nla_catalog_gateway.canonical_names import (
    CSV_HEADER,
    MANIFEST_FILENAME,
    SIDECAR_FILENAME,
    SUPPORTED_GAME_ORDER,
    CanonicalNameRecordV1,
    build_canonical_name_sidecar,
    load_canonical_names,
    load_canonical_names_manifest,
)


def build_extended_reference(
    parent: Path,
    parent_manifest_sha256: str,
    additions: Iterable[CanonicalNameRecordV1],
    *,
    output_directory: Path,
    generator_code_sha: str,
) -> dict:
    """Build a new, unactivated reference, preserving every original record exactly.

    Caller supplies only verified missing mappings; existing keys, cross-game
    source-ID reuse and duplicate additions are errors, never replacements. Keep
    source/provenance evidence alongside the output. Derived CSVs for the source roster are retained
    as the actual builder inputs, not misrepresented as original PowerTools exports.
    Output must not exist. Failed output is retained for inspection, not activated.
    """
    parent_manifest = load_canonical_names_manifest(
        (parent / MANIFEST_FILENAME).read_bytes(), expected_sha256=parent_manifest_sha256
    )
    with (parent / SIDECAR_FILENAME).open("rb") as source:
        existing = load_canonical_names(source, manifest=parent_manifest)
    combined = dict(existing)
    source_ids = {record.source_id for record in existing.values()}
    added = []
    for record in additions:
        if type(record) is not CanonicalNameRecordV1:
            raise ValueError("invalid_canonical_addition")
        if record.source_id in source_ids:
            raise ValueError("canonical_addition_identity_already_present")
        source_ids.add(record.source_id)
        combined[(record.game, record.source_id)] = record
        added.append(record)
    if not added:
        raise ValueError("no_canonical_additions")
    output_directory.mkdir(mode=0o700)
    sources = {}
    source_games = {source.game for source in parent_manifest.sources} | {r.game for r in added}
    for game in SUPPORTED_GAME_ORDER:
        if game not in source_games:
            continue
        path = output_directory / f"derived-{game.value}.csv"
        sources[game] = path
        with path.open("x", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(CSV_HEADER)
            for key in sorted(combined, key=lambda k: (k[0].value, len(k[1]), k[1])):
                record = combined[key]
                if record.game is not game:
                    continue
                metadata = record.card_metadata
                writer.writerow(
                    [
                        record.source_id,
                        record.canonical_card_name,
                        metadata.collector_number if metadata else None,
                        metadata.rarity if metadata else None,
                        metadata.expansion_name if metadata else None,
                        metadata.expansion_code if metadata else None,
                        None,
                        None,
                    ]
                )
    bundle = output_directory / "bundle"
    manifest = build_canonical_name_sidecar(
        sources, output_directory=bundle, generator_code_sha=generator_code_sha
    )
    with (bundle / SIDECAR_FILENAME).open("rb") as source:
        verified = load_canonical_names(source, manifest=manifest)
    if verified != combined or any(verified[key] != value for key, value in existing.items()):
        raise ValueError("canonical_extension_roundtrip_changed_records")
    added.sort(key=lambda r: (SUPPORTED_GAME_ORDER.index(r.game), len(r.source_id), r.source_id))
    addition_bytes = b"".join(record.to_json_bytes() + b"\n" for record in added)
    with (output_directory / "additions.v1.jsonl").open("xb") as stream:
        stream.write(addition_bytes)
    evidence = {
        "parentManifestSha256": parent_manifest_sha256,
        "manifestSha256": manifest.manifest_sha256,
        "parentRecords": len(existing),
        "addedRecords": len(added),
        "records": len(verified),
        "additionsSha256": hashlib.sha256(addition_bytes).hexdigest(),
        "existingRecordsUnchanged": True,
        "activated": False,
    }
    with (output_directory / "extension-evidence.v1.json").open("x", encoding="utf-8") as stream:
        json.dump(evidence, stream, sort_keys=True)
    return evidence
