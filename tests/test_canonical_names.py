from __future__ import annotations

import csv
import hashlib
import io
import json
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from nla_catalog_gateway import canonical_names as names
from nla_catalog_gateway.canonical_names import (
    CANONICAL_GAME_ORDER,
    CSV_HEADER,
    MANIFEST_FILENAME,
    SIDECAR_FILENAME,
    CanonicalNameRecordV1,
    CanonicalNamesError,
    CanonicalNameSidecarEvidenceV1,
    CanonicalNamesManifestV1,
    CanonicalNameSourceEvidenceV1,
    build_canonical_name_sidecar,
    load_canonical_names,
    load_canonical_names_manifest,
)
from nla_catalog_gateway.taxonomy import Game

SHA = "a" * 64
CODE_SHA = "b" * 40


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _record(game: Game, source_id: str, name: str = "Lightning Bolt") -> CanonicalNameRecordV1:
    return CanonicalNameRecordV1(game, source_id, name)


def _sidecar(records: list[CanonicalNameRecordV1]) -> bytes:
    return b"".join(record.to_json_bytes() + b"\n" for record in records)


def _manifest_for_sidecar(
    raw: bytes,
    records: list[CanonicalNameRecordV1],
    *,
    generator_code_sha: str = CODE_SHA,
) -> CanonicalNamesManifestV1:
    counts = Counter(record.game for record in records)
    return CanonicalNamesManifestV1(
        generator_code_sha=generator_code_sha,
        sources=tuple(
            CanonicalNameSourceEvidenceV1(game, SHA, 1, counts[game])
            for game in CANONICAL_GAME_ORDER
        ),
        sidecar=CanonicalNameSidecarEvidenceV1(
            hashlib.sha256(raw).hexdigest(), len(raw), len(records)
        ),
    )


def _csv_bytes(rows: list[tuple[str, str]], *, header: tuple[str, ...] = CSV_HEADER) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(header)
    for source_id, canonical_name in rows:
        writer.writerow((source_id, canonical_name, "", "", "", "", "", ""))
    return output.getvalue().encode("utf-8")


def _write_sources(
    root: Path, rows: dict[Game, list[tuple[str, str]]] | None = None
) -> tuple[dict[Game, Path], dict[Game, bytes]]:
    supplied = rows or {}
    paths: dict[Game, Path] = {}
    payloads: dict[Game, bytes] = {}
    for game in CANONICAL_GAME_ORDER:
        raw = _csv_bytes(supplied.get(game, []))
        path = root / f"{game.value}.csv"
        path.write_bytes(raw)
        paths[game] = path
        payloads[game] = raw
    return paths, payloads


def test_record_is_canonical_and_strict() -> None:
    record = _record(Game.POKEMON, "42", "Éclair, Mage")
    assert record.as_dict() == {
        "canonicalCardName": "Éclair, Mage",
        "game": "pokemon",
        "sourceId": "42",
    }
    raw = b'{"canonicalCardName":"\xc3\x89clair, Mage","game":"pokemon","sourceId":"42"}'
    assert record.to_json_bytes() == raw
    assert CanonicalNameRecordV1.from_json_bytes(raw) == record


@pytest.mark.parametrize("game", ["magic", None, 1])
def test_record_rejects_non_enum_game(game: object) -> None:
    with pytest.raises(CanonicalNamesError, match="game"):
        CanonicalNameRecordV1(game, "1", "Name")  # type: ignore[arg-type]


@pytest.mark.parametrize("source_id", [None, "", "0", "01", "-1", "1.0", " 1", "1" * 65])
def test_record_rejects_noncanonical_source_id(source_id: object) -> None:
    with pytest.raises(CanonicalNamesError, match="sourceId"):
        CanonicalNameRecordV1(Game.MAGIC, source_id, "Name")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "canonical_name",
    [None, "", " \t", "x" * 1025, "bad\x00name", "\ud800"],
)
def test_record_rejects_invalid_canonical_name(canonical_name: object) -> None:
    with pytest.raises(CanonicalNamesError, match="card name"):
        CanonicalNameRecordV1(Game.MAGIC, "1", canonical_name)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"\xef\xbb\xbf{}",
        b"[]",
        b'{"canonicalCardName":"Name","game":"magic","sourceId":"1","x":1}',
        b'{"canonicalCardName":"Name","game":"bad","sourceId":"1"}',
        b'{"canonicalCardName":"Name","game":"magic","sourceId":1}',
        b'{ "canonicalCardName":"Name","game":"magic","sourceId":"1"}',
        b'{"canonicalCardName":"Name","game":"magic","game":"magic","sourceId":"1"}',
        b'{"canonicalCardName":"\\ud800","game":"magic","sourceId":"1"}',
        b'{"canonicalCardName":"Name","game":"magic","sourceId":"1","x":1.5}',
        b'{"canonicalCardName":"Name","game":"magic","sourceId":"1","x":NaN}',
        b'{"x":12345678901234567890}',
        b"\xff",
        b" " * (names.MAX_RECORD_BYTES + 1),
    ],
)
def test_record_parser_rejects_invalid_or_noncanonical_json(raw: bytes) -> None:
    with pytest.raises(CanonicalNamesError):
        CanonicalNameRecordV1.from_json_bytes(raw)


def test_canonical_json_rejects_unsupported_and_recursive_values() -> None:
    with pytest.raises(CanonicalNamesError, match="serializable"):
        names._canonical_json_bytes({"bad": object()})
    recursive: list[object] = []
    recursive.append(recursive)
    with pytest.raises(CanonicalNamesError, match="serializable"):
        names._canonical_json_bytes(recursive)


def test_source_and_sidecar_evidence_round_trip() -> None:
    source = CanonicalNameSourceEvidenceV1(Game.MAGIC, SHA, 10, 2)
    assert source.as_dict() == {
        "bytes": 10,
        "game": "magic",
        "recordCount": 2,
        "sha256": SHA,
    }
    assert CanonicalNameSourceEvidenceV1.from_dict(source.as_dict()) == source

    sidecar = CanonicalNameSidecarEvidenceV1(SHA, 10, 2)
    assert sidecar.as_dict() == {"bytes": 10, "recordCount": 2, "sha256": SHA}
    assert CanonicalNameSidecarEvidenceV1.from_dict(sidecar.as_dict()) == sidecar
    assert CanonicalNameSidecarEvidenceV1(hashlib.sha256(b"").hexdigest(), 0, 0).byte_count == 0


@pytest.mark.parametrize(
    "factory",
    [
        lambda: CanonicalNameSourceEvidenceV1("magic", SHA, 1, 0),
        lambda: CanonicalNameSourceEvidenceV1(Game.MAGIC, "A" * 64, 1, 0),
        lambda: CanonicalNameSourceEvidenceV1(Game.MAGIC, SHA, 0, 0),
        lambda: CanonicalNameSourceEvidenceV1(Game.MAGIC, SHA, 1, -1),
        lambda: CanonicalNameSourceEvidenceV1(Game.MAGIC, SHA, 1, 2**63),
        lambda: CanonicalNameSourceEvidenceV1.from_dict([]),
        lambda: CanonicalNameSourceEvidenceV1.from_dict({"game": "magic"}),
        lambda: CanonicalNameSourceEvidenceV1.from_dict(
            {"bytes": 1, "game": "bad", "recordCount": 0, "sha256": SHA}
        ),
        lambda: CanonicalNameSidecarEvidenceV1("A" * 64, 1, 1),
        lambda: CanonicalNameSidecarEvidenceV1(SHA, -1, 0),
        lambda: CanonicalNameSidecarEvidenceV1(SHA, 0, 1),
        lambda: CanonicalNameSidecarEvidenceV1.from_dict([]),
        lambda: CanonicalNameSidecarEvidenceV1.from_dict({"bytes": 1}),
        lambda: CanonicalNameSidecarEvidenceV1.from_dict(
            {"bytes": "1", "recordCount": 1, "sha256": SHA}
        ),
    ],
)
def test_evidence_rejects_invalid_contracts(factory: Any) -> None:
    with pytest.raises(CanonicalNamesError):
        factory()


def test_manifest_round_trip_and_independent_pin() -> None:
    records = [_record(Game.MAGIC, "1")]
    raw_sidecar = _sidecar(records)
    manifest = _manifest_for_sidecar(raw_sidecar, records, generator_code_sha="c" * 64)
    raw_manifest = manifest.to_json_bytes()
    assert manifest.as_dict()["schemaVersion"] == 1
    assert manifest.manifest_sha256 == hashlib.sha256(raw_manifest).hexdigest()
    assert manifest.manifest_byte_count == len(raw_manifest)
    assert CanonicalNamesManifestV1.from_json_bytes(raw_manifest) == manifest
    assert (
        load_canonical_names_manifest(raw_manifest, expected_sha256=manifest.manifest_sha256)
        == manifest
    )
    with pytest.raises(CanonicalNamesError, match="does not match"):
        load_canonical_names_manifest(raw_manifest, expected_sha256="d" * 64)
    with pytest.raises(CanonicalNamesError, match="expected"):
        load_canonical_names_manifest(raw_manifest, expected_sha256="D" * 64)
    with pytest.raises(CanonicalNamesError, match="does not match"):
        load_canonical_names_manifest("not-bytes", expected_sha256="d" * 64)  # type: ignore[arg-type]


def test_manifest_constructor_rejects_invalid_invariants() -> None:
    empty = b""
    manifest = _manifest_for_sidecar(empty, [])
    with pytest.raises(CanonicalNamesError, match="schemaVersion"):
        replace(manifest, schema_version=2)
    with pytest.raises(CanonicalNamesError, match="generatorCodeSha"):
        replace(manifest, generator_code_sha="b" * 41)
    with pytest.raises(CanonicalNamesError, match="source evidence"):
        replace(manifest, sources=list(manifest.sources))  # type: ignore[arg-type]
    bad_sources = (object(), *manifest.sources[1:])
    with pytest.raises(CanonicalNamesError, match="source evidence"):
        replace(manifest, sources=bad_sources)  # type: ignore[arg-type]
    with pytest.raises(CanonicalNamesError, match="sources"):
        replace(manifest, sources=tuple(reversed(manifest.sources)))
    with pytest.raises(CanonicalNamesError, match="sidecar evidence"):
        replace(manifest, sidecar=object())  # type: ignore[arg-type]
    changed_source = replace(manifest.sources[0], record_count=1)
    with pytest.raises(CanonicalNamesError, match="record counts"):
        replace(manifest, sources=(changed_source, *manifest.sources[1:]))


def test_manifest_parser_rejects_invalid_shapes_and_noncanonical_bytes() -> None:
    manifest = _manifest_for_sidecar(b"", [])
    document = manifest.as_dict()
    invalid_documents = [
        [],
        {**document, "extra": True},
        {**document, "sources": {}},
        {**document, "sources": [*document["sources"], document["sources"][0]]},
        {**document, "sidecar": []},
        {**document, "sidecar": {"bytes": 0}},
        {**document, "generatorCodeSha": "bad"},
    ]
    for invalid in invalid_documents:
        with pytest.raises(CanonicalNamesError):
            CanonicalNamesManifestV1.from_json_bytes(_canonical_json(invalid))
    pretty = json.dumps(document, indent=2).encode()
    with pytest.raises(CanonicalNamesError, match="canonical JSON"):
        CanonicalNamesManifestV1.from_json_bytes(pretty)
    with pytest.raises(CanonicalNamesError):
        CanonicalNamesManifestV1.from_json_bytes(
            b'{"generatorCodeSha":"' + b"b" * 40 + b'","generatorCodeSha":"' + b"b" * 40 + b'"}'
        )


def test_verified_loader_accepts_cross_game_ids_and_returns_immutable_mapping() -> None:
    records = [
        _record(Game.MAGIC, "2", "Magic Name"),
        _record(Game.POKEMON, "2", "Pokemon Name"),
        _record(Game.ONE_PIECE, "9", "One Piece Name"),
    ]
    raw = _sidecar(records)
    manifest = _manifest_for_sidecar(raw, records)
    loaded = load_canonical_names(io.BytesIO(raw), manifest=manifest)
    assert loaded[(Game.MAGIC, "2")].canonical_card_name == "Magic Name"
    assert loaded[(Game.POKEMON, "2")].canonical_card_name == "Pokemon Name"
    with pytest.raises(TypeError):
        loaded[(Game.YUGIOH, "2")] = _record(Game.YUGIOH, "2")  # type: ignore[index]


class _BadRead:
    def __init__(self, result: object = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error

    def readline(self, _limit: int) -> object:
        if self.error is not None:
            raise self.error
        return self.result


def test_verified_loader_rejects_invalid_manifest_or_handle() -> None:
    manifest = _manifest_for_sidecar(b"", [])
    with pytest.raises(CanonicalNamesError, match="manifest object"):
        load_canonical_names(io.BytesIO(), manifest=object())  # type: ignore[arg-type]
    with pytest.raises(CanonicalNamesError, match="binary"):
        load_canonical_names(_BadRead(""), manifest=manifest)  # type: ignore[arg-type]
    with pytest.raises(CanonicalNamesError, match="cannot be read"):
        load_canonical_names(_BadRead(error=OSError()), manifest=manifest)  # type: ignore[arg-type]
    with pytest.raises(CanonicalNamesError, match="cannot be read"):
        load_canonical_names(object(), manifest=manifest)  # type: ignore[arg-type]


def test_verified_loader_rejects_line_boundaries_order_and_duplicates() -> None:
    first = _record(Game.MAGIC, "2")
    second = _record(Game.MAGIC, "10")
    invalid_values = [
        (first.to_json_bytes(), [first]),
        (b"x" * (names.MAX_RECORD_BYTES + 2) + b"\n", [first]),
        (_sidecar([second, first]), [second, first]),
        (_sidecar([first, first]), [first, first]),
    ]
    for raw, declared_records in invalid_values:
        manifest = _manifest_for_sidecar(raw, declared_records)
        with pytest.raises(CanonicalNamesError):
            load_canonical_names(io.BytesIO(raw), manifest=manifest)


def test_verified_loader_rejects_evidence_and_game_count_mismatches() -> None:
    records = [_record(Game.MAGIC, "1")]
    raw = _sidecar(records)
    manifest = _manifest_for_sidecar(raw, records)
    evidence_mutations = [
        replace(manifest.sidecar, sha256="f" * 64),
        replace(manifest.sidecar, byte_count=len(raw) + 1),
    ]
    for evidence in evidence_mutations:
        changed = replace(manifest, sidecar=evidence)
        with pytest.raises(CanonicalNamesError):
            load_canonical_names(io.BytesIO(raw), manifest=changed)

    too_short = replace(manifest.sidecar, byte_count=len(raw) - 1)
    with pytest.raises(CanonicalNamesError, match="bytes do not match"):
        load_canonical_names(io.BytesIO(raw), manifest=replace(manifest, sidecar=too_short))

    extra_source = replace(manifest.sources[0], record_count=2)
    adjusted_source = replace(manifest.sources[1], record_count=0)
    with pytest.raises(CanonicalNamesError, match="record counts"):
        replace(manifest, sources=(extra_source, adjusted_source, *manifest.sources[2:]))

    moved = (
        replace(manifest.sources[0], record_count=0),
        replace(manifest.sources[1], record_count=1),
        *manifest.sources[2:],
    )
    with pytest.raises(CanonicalNamesError, match="game counts"):
        load_canonical_names(io.BytesIO(raw), manifest=replace(manifest, sources=moved))


def test_builder_emits_deterministic_bundle_and_loader_accepts_it(tmp_path: Path) -> None:
    rows = {
        Game.MAGIC: [("10", "Ten"), ("2", "Two")],
        Game.POKEMON: [("2", "Deux")],
        Game.ONE_PIECE: [("7", "Luffy, Captain")],
    }
    sources, payloads = _write_sources(tmp_path, rows)
    output = tmp_path / "bundle"
    manifest = build_canonical_name_sidecar(
        sources, output_directory=output, generator_code_sha=CODE_SHA
    )
    assert {path.name for path in output.iterdir()} == {SIDECAR_FILENAME, MANIFEST_FILENAME}
    assert (output / MANIFEST_FILENAME).read_bytes() == manifest.to_json_bytes()
    assert manifest.sources == tuple(
        CanonicalNameSourceEvidenceV1(
            game,
            hashlib.sha256(payloads[game]).hexdigest(),
            len(payloads[game]),
            len(rows.get(game, [])),
        )
        for game in CANONICAL_GAME_ORDER
    )
    expected_records = [
        _record(Game.MAGIC, "2", "Two"),
        _record(Game.MAGIC, "10", "Ten"),
        _record(Game.POKEMON, "2", "Deux"),
        _record(Game.ONE_PIECE, "7", "Luffy, Captain"),
    ]
    sidecar_raw = (output / SIDECAR_FILENAME).read_bytes()
    assert sidecar_raw == _sidecar(expected_records)
    with (output / SIDECAR_FILENAME).open("rb") as handle:
        assert tuple(load_canonical_names(handle, manifest=manifest).values()) == tuple(
            expected_records
        )

    second_output = tmp_path / "bundle-2"
    second = build_canonical_name_sidecar(
        sources, output_directory=second_output, generator_code_sha=CODE_SHA
    )
    assert second == manifest
    assert (second_output / SIDECAR_FILENAME).read_bytes() == sidecar_raw


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"\xef\xbb\xbf" + _csv_bytes([]),
        _csv_bytes([]) + b"\x00",
        b"\xff",
        _csv_bytes([], header=("wrong",)),
        _csv_bytes([]).splitlines(keepends=True)[0] + b'"unterminated\n',
        _csv_bytes([]) + b"1,Name\n",
        _csv_bytes([("0", "Name")]),
        _csv_bytes([("1", "Name"), ("1", "Other")]),
        _csv_bytes([("1", " ")]),
    ],
)
def test_builder_rejects_invalid_csv_content(tmp_path: Path, raw: bytes) -> None:
    sources, _ = _write_sources(tmp_path)
    sources[Game.MAGIC].write_bytes(raw)
    with pytest.raises(CanonicalNamesError):
        build_canonical_name_sidecar(
            sources, output_directory=tmp_path / "bundle", generator_code_sha=CODE_SHA
        )
    assert not (tmp_path / "bundle").exists()
    assert not any(path.name.startswith(".canonical-names-") for path in tmp_path.iterdir())


def test_builder_rejects_source_larger_than_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sources, _ = _write_sources(tmp_path)
    monkeypatch.setattr(names, "MAX_SOURCE_BYTES", 1)
    with pytest.raises(CanonicalNamesError, match="bytes"):
        build_canonical_name_sidecar(
            sources, output_directory=tmp_path / "bundle", generator_code_sha=CODE_SHA
        )


def test_builder_rejects_invalid_boundaries(tmp_path: Path) -> None:
    sources, _ = _write_sources(tmp_path)
    with pytest.raises(CanonicalNamesError, match="mapping"):
        build_canonical_name_sidecar(  # type: ignore[arg-type]
            [], output_directory=tmp_path / "bundle", generator_code_sha=CODE_SHA
        )
    with pytest.raises(CanonicalNamesError, match="mapping"):
        build_canonical_name_sidecar(
            {Game.MAGIC: sources[Game.MAGIC]},
            output_directory=tmp_path / "bundle",
            generator_code_sha=CODE_SHA,
        )
    string_keys = {game.value: path for game, path in sources.items()}
    with pytest.raises(CanonicalNamesError, match="mapping"):
        build_canonical_name_sidecar(  # type: ignore[arg-type]
            string_keys,
            output_directory=tmp_path / "bundle",
            generator_code_sha=CODE_SHA,
        )
    with pytest.raises(CanonicalNamesError, match="output directory"):
        build_canonical_name_sidecar(  # type: ignore[arg-type]
            sources, output_directory="bundle", generator_code_sha=CODE_SHA
        )
    with pytest.raises(CanonicalNamesError, match="code SHA"):
        build_canonical_name_sidecar(
            sources, output_directory=tmp_path / "bundle", generator_code_sha="B" * 40
        )
    with pytest.raises(CanonicalNamesError, match="filesystem"):
        build_canonical_name_sidecar(
            sources,
            output_directory=tmp_path / "missing" / "bundle",
            generator_code_sha=CODE_SHA,
        )
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(CanonicalNamesError, match="output boundary"):
        build_canonical_name_sidecar(
            sources, output_directory=existing, generator_code_sha=CODE_SHA
        )
    duplicate_sources = dict(sources)
    duplicate_sources[Game.POKEMON] = duplicate_sources[Game.MAGIC]
    with pytest.raises(CanonicalNamesError, match="distinct"):
        build_canonical_name_sidecar(
            duplicate_sources,
            output_directory=tmp_path / "bundle",
            generator_code_sha=CODE_SHA,
        )
    invalid_sources = dict(sources)
    invalid_sources[Game.POKEMON] = "not-a-path"  # type: ignore[assignment]
    with pytest.raises(CanonicalNamesError, match="CSV source"):
        build_canonical_name_sidecar(
            invalid_sources,
            output_directory=tmp_path / "bundle",
            generator_code_sha=CODE_SHA,
        )


def test_builder_rejects_directory_source(tmp_path: Path) -> None:
    sources, _ = _write_sources(tmp_path)
    directory = tmp_path / "source-directory"
    directory.mkdir()
    sources[Game.POKEMON] = directory
    with pytest.raises(CanonicalNamesError, match="CSV source"):
        build_canonical_name_sidecar(
            sources, output_directory=tmp_path / "bundle", generator_code_sha=CODE_SHA
        )


def test_csv_loader_wraps_read_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source.csv"
    source.write_bytes(_csv_bytes([]))

    def fail_open(_self: Path, _mode: str) -> object:
        raise OSError

    monkeypatch.setattr(Path, "open", fail_open)
    with pytest.raises(CanonicalNamesError, match="cannot be read"):
        names._load_csv_source(source, Game.MAGIC)


def test_builder_wraps_staging_and_publish_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sources, _ = _write_sources(tmp_path)

    def fail_mkdtemp(*_args: object, **_kwargs: object) -> str:
        raise OSError

    monkeypatch.setattr(names.tempfile, "mkdtemp", fail_mkdtemp)
    with pytest.raises(CanonicalNamesError, match="staging"):
        build_canonical_name_sidecar(
            sources, output_directory=tmp_path / "bundle", generator_code_sha=CODE_SHA
        )

    monkeypatch.undo()

    def fail_rename(_self: Path, _target: Path) -> None:
        raise OSError

    monkeypatch.setattr(Path, "rename", fail_rename)
    with pytest.raises(CanonicalNamesError, match="cannot be built"):
        build_canonical_name_sidecar(
            sources, output_directory=tmp_path / "bundle", generator_code_sha=CODE_SHA
        )
    assert not any(path.name.startswith(".canonical-names-") for path in tmp_path.iterdir())


def test_cleanup_failure_does_not_mask_value_free_rejection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sources, _ = _write_sources(tmp_path)
    sources[Game.MAGIC].write_bytes(b"invalid")

    def fail_cleanup(_path: Path) -> None:
        raise OSError

    monkeypatch.setattr(names.shutil, "rmtree", fail_cleanup)
    with pytest.raises(CanonicalNamesError, match="CSV"):
        build_canonical_name_sidecar(
            sources, output_directory=tmp_path / "bundle", generator_code_sha=CODE_SHA
        )
