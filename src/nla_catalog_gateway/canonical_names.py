"""Strict offline contract for canonical card names sourced outside Shopify."""

from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import os
import re
import shutil
import tempfile
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, BinaryIO, ClassVar

from nla_catalog_gateway.card_metadata import CardMetadataV1, optional_card_metadata
from nla_catalog_gateway.taxonomy import LEGACY_GAMES, Game

SCHEMA_VERSION = 1
SIDECAR_FILENAME = "canonical-names.v1.jsonl"
MANIFEST_FILENAME = "canonical-names-manifest.v1.json"
MAX_MANIFEST_BYTES = 64 * 1024
MAX_RECORD_BYTES = 24 * 1024
MAX_SOURCE_BYTES = 512 * 1024 * 1024
MAX_CANONICAL_NAME_CODEPOINTS = 1024
MAX_SOURCE_ID_DIGITS = 64
SIGNED_64_MAX = 2**63 - 1

CSV_HEADER = (
    "cardmarketId",
    "name",
    "collectorNumber",
    "rarity",
    "expansion",
    "expansionCode",
    "scryfallId",
    "tcgplayerId",
)
CANONICAL_GAME_ORDER = LEGACY_GAMES
SUPPORTED_GAME_ORDER = tuple(Game)

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_GENERATOR_CODE_SHA_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_SOURCE_ID_RE = re.compile(rf"[1-9][0-9]{{0,{MAX_SOURCE_ID_DIGITS - 1}}}\Z")
_BOMS = (b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff", b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")
_CONCRETE_PATH_TYPE = type(Path())


class CanonicalNamesError(ValueError):
    """A bounded, value-free error for an invalid canonical-name contract."""


class _DuplicateJsonKeyError(ValueError):
    pass


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKeyError
        result[key] = value
    return result


def _parse_integer(value: str) -> int:
    if len(value.lstrip("-")) > 19:
        raise CanonicalNamesError("canonical-name JSON integer is out of range")
    return int(value)


def _reject_float(_value: str) -> None:
    raise CanonicalNamesError("canonical-name JSON numbers must be integers")


def _reject_constant(_value: str) -> None:
    raise CanonicalNamesError("canonical-name JSON contains a non-finite number")


def _contains_surrogate(value: str) -> bool:
    return any(0xD800 <= ord(character) <= 0xDFFF for character in value)


def _validate_unicode_tree(root: Any) -> None:
    pending = [root]
    while pending:
        value = pending.pop()
        if type(value) is str:
            if _contains_surrogate(value):
                raise CanonicalNamesError("canonical-name JSON contains invalid Unicode")
        elif type(value) is dict:
            pending.extend(value.keys())
            pending.extend(value.values())
        elif type(value) is list:
            pending.extend(value)


def _canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (RecursionError, TypeError, UnicodeEncodeError, ValueError) as exc:
        raise CanonicalNamesError("canonical-name value is not serializable") from exc


def _strict_json(raw: bytes, *, context: str, max_bytes: int) -> Any:
    if type(raw) is not bytes or not raw or len(raw) > max_bytes or raw.startswith(_BOMS):
        raise CanonicalNamesError(f"{context} bytes are invalid")
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_int=_parse_integer,
            parse_float=_reject_float,
            parse_constant=_reject_constant,
        )
    except CanonicalNamesError:
        raise
    except (
        RecursionError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        _DuplicateJsonKeyError,
    ) as exc:
        raise CanonicalNamesError(f"{context} JSON is invalid") from exc
    _validate_unicode_tree(value)
    return value


def _require_exact_keys(value: Mapping[str, Any], expected: set[str], context: str) -> None:
    if set(value) != expected:
        raise CanonicalNamesError(f"{context} fields are invalid")


def _validated_count(value: object, context: str, *, positive: bool = False) -> int:
    minimum = 1 if positive else 0
    if type(value) is not int or value < minimum or value > SIGNED_64_MAX:
        raise CanonicalNamesError(f"{context} is invalid")
    return value


def _validated_sha256(value: object, context: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise CanonicalNamesError(f"{context} is invalid")
    return value


def _validated_source_id(value: object) -> str:
    if type(value) is not str or _SOURCE_ID_RE.fullmatch(value) is None:
        raise CanonicalNamesError("canonical-name sourceId is invalid")
    return value


def _validated_name(value: object) -> str:
    if (
        type(value) is not str
        or not value.strip()
        or len(value) > MAX_CANONICAL_NAME_CODEPOINTS
        or "\x00" in value
        or _contains_surrogate(value)
    ):
        raise CanonicalNamesError("canonical card name is invalid")
    return value


@dataclass(frozen=True, slots=True)
class CanonicalNameRecordV1:
    """One immutable name keyed by game and canonical decimal source ID."""

    game: Game
    source_id: str
    canonical_card_name: str
    card_metadata: CardMetadataV1 | None = None

    FIELDS: ClassVar[frozenset[str]] = frozenset({"canonicalCardName", "game", "sourceId"})

    def __post_init__(self) -> None:
        if type(self.game) is not Game:
            raise CanonicalNamesError("canonical-name game is invalid")
        _validated_source_id(self.source_id)
        _validated_name(self.canonical_card_name)
        if self.card_metadata is not None and type(self.card_metadata) is not CardMetadataV1:
            raise CanonicalNamesError("canonical-name card metadata is invalid")

    def as_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "canonicalCardName": self.canonical_card_name,
            "game": self.game.value,
            "sourceId": self.source_id,
        }
        if self.card_metadata is not None:
            result["cardMetadata"] = self.card_metadata.as_dict()
        return result

    def to_json_bytes(self) -> bytes:
        return _canonical_json_bytes(self.as_dict())

    @classmethod
    def from_json_bytes(cls, raw: bytes) -> CanonicalNameRecordV1:
        try:
            value = _strict_json(raw, context="canonical-name record", max_bytes=MAX_RECORD_BYTES)
            if type(value) is not dict:
                raise CanonicalNamesError("canonical-name record must be an object")
            fields = cls.FIELDS | ({"cardMetadata"} if "cardMetadata" in value else set())
            _require_exact_keys(value, set(fields), "canonical-name record")
            record = cls(
                game=Game(value["game"]),
                source_id=value["sourceId"],
                canonical_card_name=value["canonicalCardName"],
                card_metadata=optional_card_metadata(value),
            )
            if record.to_json_bytes() != raw:
                raise CanonicalNamesError("canonical-name record is not canonical JSON")
            return record
        except CanonicalNamesError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise CanonicalNamesError("canonical-name record is invalid") from exc


@dataclass(frozen=True, slots=True)
class CanonicalNameSourceEvidenceV1:
    game: Game
    sha256: str
    byte_count: int
    record_count: int

    FIELDS: ClassVar[frozenset[str]] = frozenset({"bytes", "game", "recordCount", "sha256"})

    def __post_init__(self) -> None:
        if type(self.game) is not Game:
            raise CanonicalNamesError("canonical-name source game is invalid")
        _validated_sha256(self.sha256, "canonical-name source sha256")
        _validated_count(self.byte_count, "canonical-name source bytes", positive=True)
        _validated_count(self.record_count, "canonical-name source recordCount")

    def as_dict(self) -> dict[str, object]:
        return {
            "bytes": self.byte_count,
            "game": self.game.value,
            "recordCount": self.record_count,
            "sha256": self.sha256,
        }

    @classmethod
    def from_dict(cls, value: object) -> CanonicalNameSourceEvidenceV1:
        if type(value) is not dict:
            raise CanonicalNamesError("canonical-name source must be an object")
        _require_exact_keys(value, set(cls.FIELDS), "canonical-name source")
        try:
            game = Game(value["game"])
        except (KeyError, TypeError, ValueError) as exc:
            raise CanonicalNamesError("canonical-name source is invalid") from exc
        return cls(
            game=game,
            sha256=value["sha256"],
            byte_count=value["bytes"],
            record_count=value["recordCount"],
        )


@dataclass(frozen=True, slots=True)
class CanonicalNameSidecarEvidenceV1:
    sha256: str
    byte_count: int
    record_count: int

    FIELDS: ClassVar[frozenset[str]] = frozenset({"bytes", "recordCount", "sha256"})

    def __post_init__(self) -> None:
        _validated_sha256(self.sha256, "canonical-name sidecar sha256")
        _validated_count(self.byte_count, "canonical-name sidecar bytes")
        _validated_count(self.record_count, "canonical-name sidecar recordCount")
        if (self.byte_count == 0) != (self.record_count == 0):
            raise CanonicalNamesError("canonical-name sidecar counts are inconsistent")

    def as_dict(self) -> dict[str, object]:
        return {
            "bytes": self.byte_count,
            "recordCount": self.record_count,
            "sha256": self.sha256,
        }

    @classmethod
    def from_dict(cls, value: object) -> CanonicalNameSidecarEvidenceV1:
        if type(value) is not dict:
            raise CanonicalNamesError("canonical-name sidecar must be an object")
        _require_exact_keys(value, set(cls.FIELDS), "canonical-name sidecar")
        return cls(
            sha256=value["sha256"],
            byte_count=value["bytes"],
            record_count=value["recordCount"],
        )


@dataclass(frozen=True, slots=True)
class CanonicalNamesManifestV1:
    generator_code_sha: str
    sources: tuple[CanonicalNameSourceEvidenceV1, ...]
    sidecar: CanonicalNameSidecarEvidenceV1
    schema_version: int = SCHEMA_VERSION

    FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"generatorCodeSha", "schemaVersion", "sidecar", "sources"}
    )

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version not in (1, 2):
            raise CanonicalNamesError("canonical-name manifest schemaVersion must be 1 or 2")
        if (
            type(self.generator_code_sha) is not str
            or _GENERATOR_CODE_SHA_RE.fullmatch(self.generator_code_sha) is None
        ):
            raise CanonicalNamesError("canonical-name manifest generatorCodeSha is invalid")
        if type(self.sources) is not tuple or any(
            type(source) is not CanonicalNameSourceEvidenceV1 for source in self.sources
        ):
            raise CanonicalNamesError("canonical-name manifest source evidence is invalid")
        games = tuple(source.game for source in self.sources)
        expected = tuple(game for game in SUPPORTED_GAME_ORDER if game in games)
        if (
            games != expected
            or not set(CANONICAL_GAME_ORDER) <= set(games)
            or (self.schema_version == 1) != (games == CANONICAL_GAME_ORDER)
        ):
            raise CanonicalNamesError("canonical-name manifest sources are invalid")
        if type(self.sidecar) is not CanonicalNameSidecarEvidenceV1:
            raise CanonicalNamesError("canonical-name manifest sidecar evidence is invalid")
        if sum(source.record_count for source in self.sources) != self.sidecar.record_count:
            raise CanonicalNamesError("canonical-name manifest record counts are inconsistent")

    @property
    def manifest_sha256(self) -> str:
        return hashlib.sha256(self.to_json_bytes()).hexdigest()

    @property
    def manifest_byte_count(self) -> int:
        return len(self.to_json_bytes())

    def as_dict(self) -> dict[str, object]:
        return {
            "generatorCodeSha": self.generator_code_sha,
            "schemaVersion": self.schema_version,
            "sidecar": self.sidecar.as_dict(),
            "sources": [source.as_dict() for source in self.sources],
        }

    def to_json_bytes(self) -> bytes:
        return _canonical_json_bytes(self.as_dict())

    @classmethod
    def from_json_bytes(cls, raw: bytes) -> CanonicalNamesManifestV1:
        value = _strict_json(raw, context="canonical-name manifest", max_bytes=MAX_MANIFEST_BYTES)
        if type(value) is not dict:
            raise CanonicalNamesError("canonical-name manifest must be an object")
        _require_exact_keys(value, set(cls.FIELDS), "canonical-name manifest")
        source_values = value["sources"]
        if type(source_values) is not list:
            raise CanonicalNamesError("canonical-name manifest sources must be an array")
        manifest = cls(
            schema_version=value["schemaVersion"],
            generator_code_sha=value["generatorCodeSha"],
            sources=tuple(CanonicalNameSourceEvidenceV1.from_dict(item) for item in source_values),
            sidecar=CanonicalNameSidecarEvidenceV1.from_dict(value["sidecar"]),
        )
        if manifest.to_json_bytes() != raw:
            raise CanonicalNamesError("canonical-name manifest is not canonical JSON")
        return manifest


def load_canonical_names_manifest(raw: bytes, *, expected_sha256: str) -> CanonicalNamesManifestV1:
    """Load canonical manifest bytes only when an independent SHA-256 pin matches."""

    expected = _validated_sha256(expected_sha256, "expected canonical-name manifest sha256")
    actual = hashlib.sha256(raw).hexdigest() if type(raw) is bytes else ""
    if not hmac.compare_digest(actual, expected):
        raise CanonicalNamesError("canonical-name manifest sha256 does not match")
    return CanonicalNamesManifestV1.from_json_bytes(raw)


def _record_order_key(record: CanonicalNameRecordV1) -> tuple[int, int, str]:
    return (
        SUPPORTED_GAME_ORDER.index(record.game),
        len(record.source_id),
        record.source_id,
    )


def load_canonical_names(
    handle: BinaryIO, *, manifest: CanonicalNamesManifestV1
) -> Mapping[tuple[Game, str], CanonicalNameRecordV1]:
    """Consume one binary handle and return an immutable, fully verified lookup."""

    if type(manifest) is not CanonicalNamesManifestV1:
        raise CanonicalNamesError("canonical-name manifest object is invalid")
    canonical_manifest = CanonicalNamesManifestV1.from_json_bytes(manifest.to_json_bytes())
    digest = hashlib.sha256()
    byte_count = 0
    previous_key: tuple[int, int, str] | None = None
    records: dict[tuple[Game, str], CanonicalNameRecordV1] = {}
    per_game: Counter[Game] = Counter()
    try:
        while True:
            raw_line = handle.readline(MAX_RECORD_BYTES + 2)
            if type(raw_line) is not bytes:
                raise CanonicalNamesError("canonical-name sidecar handle must be binary")
            if not raw_line:
                break
            if len(raw_line) > MAX_RECORD_BYTES + 1 or not raw_line.endswith(b"\n"):
                raise CanonicalNamesError("canonical-name sidecar line is invalid")
            digest.update(raw_line)
            byte_count += len(raw_line)
            if byte_count > canonical_manifest.sidecar.byte_count:
                raise CanonicalNamesError("canonical-name sidecar bytes do not match")
            raw_record = raw_line[:-1]
            record = CanonicalNameRecordV1.from_json_bytes(raw_record)
            order_key = _record_order_key(record)
            if previous_key is not None and order_key < previous_key:
                raise CanonicalNamesError("canonical-name sidecar order is invalid")
            previous_key = order_key
            key = (record.game, record.source_id)
            if key in records:
                raise CanonicalNamesError("canonical-name sidecar contains a duplicate key")
            records[key] = record
            per_game[record.game] += 1
    except CanonicalNamesError:
        raise
    except (AttributeError, OSError, ValueError) as exc:
        raise CanonicalNamesError("canonical-name sidecar cannot be read") from exc

    evidence = canonical_manifest.sidecar
    if (
        byte_count != evidence.byte_count
        or len(records) != evidence.record_count
        or not hmac.compare_digest(digest.hexdigest(), evidence.sha256)
    ):
        raise CanonicalNamesError("canonical-name sidecar evidence does not match")
    if any(per_game[source.game] != source.record_count for source in canonical_manifest.sources):
        raise CanonicalNamesError("canonical-name sidecar game counts do not match")
    return MappingProxyType(records)


def _load_csv_source(path: Path, game: Game) -> tuple[list[CanonicalNameRecordV1], bytes]:
    try:
        if type(path) is not _CONCRETE_PATH_TYPE or path.is_symlink() or not path.is_file():
            raise CanonicalNamesError("canonical-name CSV source is invalid")
        with path.open("rb") as source:
            raw = source.read(MAX_SOURCE_BYTES + 1)
    except CanonicalNamesError:
        raise
    except OSError as exc:
        raise CanonicalNamesError("canonical-name CSV source cannot be read") from exc
    if not raw or len(raw) > MAX_SOURCE_BYTES or raw.startswith(_BOMS) or b"\x00" in raw:
        raise CanonicalNamesError("canonical-name CSV source bytes are invalid")
    try:
        text = raw.decode("utf-8")
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        header = next(reader)
        if tuple(header) != CSV_HEADER:
            raise CanonicalNamesError("canonical-name CSV header is invalid")
        records: list[CanonicalNameRecordV1] = []
        seen: set[str] = set()
        for row in reader:
            if len(row) != len(CSV_HEADER):
                raise CanonicalNamesError("canonical-name CSV row is invalid")
            source_id = _validated_source_id(row[0])
            if source_id in seen:
                raise CanonicalNamesError("canonical-name CSV contains a duplicate key")
            seen.add(source_id)
            records.append(
                CanonicalNameRecordV1(
                    game=game,
                    source_id=source_id,
                    canonical_card_name=row[1],
                    card_metadata=(
                        CardMetadataV1(
                            collector_number=row[2] or None,
                            expansion_code=row[5] or None,
                            expansion_name=row[4] or None,
                            rarity=row[3] or None,
                        )
                        if any(row[2:6])
                        else None
                    ),
                )
            )
    except CanonicalNamesError:
        raise
    except (csv.Error, StopIteration, ValueError) as exc:
        raise CanonicalNamesError("canonical-name CSV is invalid") from exc
    records.sort(key=lambda record: (len(record.source_id), record.source_id))
    return records, raw


def build_canonical_name_sidecar(
    sources: Mapping[Game, Path], *, output_directory: Path, generator_code_sha: str
) -> CanonicalNamesManifestV1:
    """Compile four authoritative CSV exports into one deterministic sidecar bundle."""

    if (
        type(sources) is not dict
        or any(type(game) is not Game for game in sources)
        or not set(CANONICAL_GAME_ORDER) <= set(sources)
    ):
        raise CanonicalNamesError("canonical-name CSV source mapping is invalid")
    if type(output_directory) is not _CONCRETE_PATH_TYPE:
        raise CanonicalNamesError("canonical-name output directory is invalid")
    if (
        type(generator_code_sha) is not str
        or _GENERATOR_CODE_SHA_RE.fullmatch(generator_code_sha) is None
    ):
        raise CanonicalNamesError("canonical-name generator code SHA is invalid")
    try:
        parent = output_directory.parent.resolve(strict=True)
        final_directory = parent / output_directory.name
        if not parent.is_dir() or os.path.lexists(final_directory):
            raise CanonicalNamesError("canonical-name output boundary is invalid")
        source_games = tuple(game for game in SUPPORTED_GAME_ORDER if game in sources)
        originals = [sources[game] for game in source_games]
        if any(
            type(source) is not _CONCRETE_PATH_TYPE or source.is_symlink() for source in originals
        ):
            raise CanonicalNamesError("canonical-name CSV source is invalid")
        resolved_sources = [source.resolve(strict=True) for source in originals]
    except CanonicalNamesError:
        raise
    except (KeyError, OSError, RuntimeError) as exc:
        raise CanonicalNamesError("canonical-name filesystem boundary is invalid") from exc
    if len(set(resolved_sources)) != len(resolved_sources):
        raise CanonicalNamesError("canonical-name CSV sources must be distinct")

    try:
        staging = Path(tempfile.mkdtemp(prefix=".canonical-names-", dir=parent))
    except OSError as exc:
        raise CanonicalNamesError("canonical-name staging directory cannot be created") from exc
    try:
        sidecar_path = staging / SIDECAR_FILENAME
        digest = hashlib.sha256()
        sidecar_bytes = 0
        sidecar_count = 0
        source_evidence: list[CanonicalNameSourceEvidenceV1] = []
        with sidecar_path.open("xb") as output:
            for game, resolved in zip(source_games, resolved_sources, strict=True):
                records, raw = _load_csv_source(resolved, game)
                source_evidence.append(
                    CanonicalNameSourceEvidenceV1(
                        game=game,
                        sha256=hashlib.sha256(raw).hexdigest(),
                        byte_count=len(raw),
                        record_count=len(records),
                    )
                )
                for record in records:
                    line = record.to_json_bytes() + b"\n"
                    output.write(line)
                    digest.update(line)
                    sidecar_bytes += len(line)
                    sidecar_count += 1
            output.flush()
            os.fsync(output.fileno())

        manifest = CanonicalNamesManifestV1(
            schema_version=1 if source_games == CANONICAL_GAME_ORDER else 2,
            generator_code_sha=generator_code_sha,
            sources=tuple(source_evidence),
            sidecar=CanonicalNameSidecarEvidenceV1(
                sha256=digest.hexdigest(),
                byte_count=sidecar_bytes,
                record_count=sidecar_count,
            ),
        )
        manifest_path = staging / MANIFEST_FILENAME
        with manifest_path.open("xb") as output:
            output.write(manifest.to_json_bytes())
            output.flush()
            os.fsync(output.fileno())
        staging.rename(final_directory)
        return manifest
    except CanonicalNamesError:
        raise
    except (OSError, ValueError) as exc:
        raise CanonicalNamesError("canonical-name sidecar cannot be built") from exc
    finally:
        if staging.exists():
            try:
                shutil.rmtree(staging)
            except OSError:
                # Preserve the original value-free rejection; the directory was uniquely
                # created by this invocation and was never published as the requested output.
                pass
