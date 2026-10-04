import csv

import pytest

from nla_catalog_gateway.canonical_names import (
    CANONICAL_GAME_ORDER,
    CSV_HEADER,
    MANIFEST_FILENAME,
    SIDECAR_FILENAME,
    CanonicalNameRecordV1,
    build_canonical_name_sidecar,
    load_canonical_names,
    load_canonical_names_manifest,
)
from nla_catalog_gateway.canonical_reference_extension import build_extended_reference
from nla_catalog_gateway.card_metadata import CardMetadataV1
from nla_catalog_gateway.taxonomy import Game


def parent(tmp_path):
    sources = {}
    for index, game in enumerate(CANONICAL_GAME_ORDER):
        path = tmp_path / f"{game.value}.csv"
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(CSV_HEADER)
            writer.writerow(
                [str(index + 1), 'Original, "name"', "007", "Rare", "Set", "SET", "", ""]
            )
        sources[game] = path
    bundle = tmp_path / "parent"
    manifest = build_canonical_name_sidecar(
        sources, output_directory=bundle, generator_code_sha="a" * 40
    )
    return bundle, manifest.manifest_sha256


def test_extends_without_changing_parent_records_or_activating(tmp_path):
    bundle, pin = parent(tmp_path)
    before = (bundle / SIDECAR_FILENAME).read_bytes()
    addition = CanonicalNameRecordV1(
        Game.MAGIC, "99", "New card", CardMetadataV1("011", None, "New Set", "Common")
    )
    result = build_extended_reference(
        bundle,
        pin,
        [addition],
        output_directory=tmp_path / "extension",
        generator_code_sha="b" * 40,
    )
    assert result["parentRecords"] == 4 and result["addedRecords"] == 1 and result["records"] == 5
    assert result["existingRecordsUnchanged"] is True and result["activated"] is False
    assert (bundle / SIDECAR_FILENAME).read_bytes() == before
    new = tmp_path / "extension" / "bundle"
    manifest = load_canonical_names_manifest(
        (new / MANIFEST_FILENAME).read_bytes(), expected_sha256=result["manifestSha256"]
    )
    with (new / SIDECAR_FILENAME).open("rb") as stream:
        records = load_canonical_names(stream, manifest=manifest)
    assert records[(Game.MAGIC, "99")] == addition


@pytest.mark.parametrize(
    "additions",
    [
        [],
        [None],
        [CanonicalNameRecordV1(Game.MAGIC, "1", "Replacement")],
        [CanonicalNameRecordV1(Game.POKEMON, "1", "Cross-game collision")],
        [
            CanonicalNameRecordV1(Game.MAGIC, "99", "A"),
            CanonicalNameRecordV1(Game.MAGIC, "99", "B"),
        ],
    ],
)
def test_rejects_empty_invalid_or_reused_identity_before_output(tmp_path, additions):
    bundle, pin = parent(tmp_path)
    with pytest.raises(ValueError):
        build_extended_reference(
            bundle, pin, additions, output_directory=tmp_path / "new", generator_code_sha="b" * 40
        )
    assert not (tmp_path / "new").exists()


def test_does_not_overwrite_output(tmp_path):
    bundle, pin = parent(tmp_path)
    existing = tmp_path / "new"
    existing.mkdir()
    with pytest.raises(FileExistsError):
        build_extended_reference(
            bundle,
            pin,
            [CanonicalNameRecordV1(Game.MAGIC, "99", "New")],
            output_directory=existing,
            generator_code_sha="b" * 40,
        )


def test_null_metadata_roundtrips_but_empty_metadata_object_does_not(tmp_path):
    bundle, pin = parent(tmp_path)
    record = CanonicalNameRecordV1(Game.MAGIC, "99", "New")
    assert (
        build_extended_reference(
            bundle, pin, [record], output_directory=tmp_path / "good", generator_code_sha="b" * 40
        )["records"]
        == 5
    )
    empty = CanonicalNameRecordV1(Game.MAGIC, "99", "New", CardMetadataV1(None, None, None, None))
    with pytest.raises(ValueError, match="roundtrip_changed_records"):
        build_extended_reference(
            bundle, pin, [empty], output_directory=tmp_path / "bad", generator_code_sha="b" * 40
        )
    assert not (tmp_path / "bad" / "extension-evidence.v1.json").exists()
