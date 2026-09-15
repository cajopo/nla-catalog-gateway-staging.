"""Authenticated keyset pagination over an immutable catalog projection.

This is an internal, code-only proof for the pagination workstream.  It consumes the
frozen runtime v1 DTOs but deliberately does not enable their provisional/unsupported
serving capabilities or provide an HTTP surface.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
import re
import sqlite3
import stat
import tempfile
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

from nla_catalog_gateway.canonical_search import CanonicalSearchError, SingleCardSuggestion
from nla_catalog_gateway.runtime_contract import (
    MAX_CONTRACT_BYTES,
    CatalogItemV1,
    CatalogPageV1,
    CatalogProductRecordV1,
    CatalogRequestV1,
    CatalogVariantItemV1,
    CursorContextV1,
    DatasetManifestV1,
    RuntimeContractError,
)
from nla_catalog_gateway.search_sql import (
    normalized_query,
    search_facts,
    search_scope,
    select_suggestions,
)
from nla_catalog_gateway.taxonomy import Game, ProductFamily

PROJECTION_SCHEMA_VERSION: Final = 2
PROJECTION_APPLICATION_ID: Final = 0x4E4C4131
MIN_CURSOR_SECRET_BYTES: Final = 32
MAX_CURSOR_SECRET_BYTES: Final = 4096
MAX_CURSOR_TTL_SECONDS: Final = 86_400
MAX_CURSOR_TOKEN_CHARS: Final = 3 * MAX_CONTRACT_BYTES
MAX_PROJECTION_PRODUCTS: Final = 1_000_000
MAX_PROJECTION_VARIANTS: Final = 10_000_000
MAX_VARIANTS_PER_PRODUCT: Final = 10_000
MAX_PROJECTION_FILE_BYTES: Final = 64 * 1024 * 1024 * 1024
FILE_HASH_CHUNK_BYTES: Final = 1024 * 1024
SQLITE_HEADER_BYTES: Final = 100
_SQLITE_PROGRESS_VM_STEPS: Final = 1_000

_READ_ONLY_MODE: Final = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH
_WRITE_BITS: Final = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH

_GENERATION_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_PRODUCT_GID_RE = re.compile(r"gid://shopify/Product/([1-9][0-9]*)\Z")
_VARIANT_GID_RE = re.compile(r"gid://shopify/ProductVariant/([1-9][0-9]*)\Z")
_BASE64URL_RE = re.compile(r"[A-Za-z0-9_-]+\Z")


class PaginationError(RuntimeError):
    """Base class for bounded internal pagination failures."""


class PaginationContractError(PaginationError):
    """The caller supplied an invalid bounded pagination value."""


class ProjectionBuildError(PaginationError):
    """An immutable projection could not be built."""


class DatasetUnavailableError(PaginationError):
    """No verified immutable projection can be selected."""


class StaleGenerationError(PaginationError):
    """The requested cursor generation is no longer active."""


class InvalidCursorError(PaginationError):
    """The token is not an authenticated canonical CursorContextV1."""


class CursorContextMismatchError(InvalidCursorError):
    """The authenticated cursor belongs to another canonical request."""


class CursorExpiredError(InvalidCursorError):
    """The authenticated cursor is no longer valid."""


class UnsupportedPaginationRequestError(PaginationError):
    """The request asks this issue-isolated slice to implement another workstream."""


_SCHEMA = f"""
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = DELETE;
PRAGMA synchronous = FULL;
PRAGMA application_id = {PROJECTION_APPLICATION_ID};
PRAGMA user_version = {PROJECTION_SCHEMA_VERSION};

CREATE TABLE projection_metadata (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    schema_version INTEGER NOT NULL CHECK (schema_version = {PROJECTION_SCHEMA_VERSION}),
    dataset_manifest_json BLOB NOT NULL,
    product_count INTEGER NOT NULL CHECK (product_count > 0),
    variant_count INTEGER NOT NULL CHECK (variant_count >= product_count),
    public_item_count INTEGER NOT NULL CHECK (
        public_item_count >= 0 AND public_item_count <= product_count
    )
) STRICT;

CREATE TABLE products (
    product_gid TEXT PRIMARY KEY,
    product_gid_length INTEGER NOT NULL CHECK (product_gid_length > 0),
    product_gid_digits TEXT NOT NULL,
    handle TEXT NOT NULL UNIQUE,
    commercial_title TEXT NOT NULL,
    canonical_card_name TEXT,
    game TEXT,
    product_family TEXT NOT NULL,
    product_subtype TEXT,
    is_public INTEGER NOT NULL CHECK (is_public IN (0, 1)),
    normalized_card_name TEXT NOT NULL,
    search_codes_json TEXT NOT NULL,
    has_positive_inventory INTEGER NOT NULL CHECK (has_positive_inventory IN (0, 1)),
    product_record_json BLOB NOT NULL,
    UNIQUE (product_gid_length, product_gid_digits)
) STRICT;

CREATE TABLE variants (
    variant_gid TEXT PRIMARY KEY,
    product_gid TEXT NOT NULL REFERENCES products(product_gid),
    variant_gid_length INTEGER NOT NULL CHECK (variant_gid_length > 0),
    variant_gid_digits TEXT NOT NULL,
    inventory_item_gid TEXT NOT NULL UNIQUE,
    public_variant_json BLOB NOT NULL,
    UNIQUE (product_gid, variant_gid_length, variant_gid_digits)
) STRICT;

CREATE INDEX products_public_game_order
    ON products(game, product_gid_length, product_gid_digits)
    WHERE is_public = 1;
CREATE INDEX products_public_game_family_order
    ON products(game, product_family, product_gid_length, product_gid_digits)
    WHERE is_public = 1;
CREATE INDEX variants_parent_order
    ON variants(product_gid, variant_gid_length, variant_gid_digits);
"""

_EXPECTED_SCHEMA_SQL = {
    ("table", "projection_metadata"): f"""
        CREATE TABLE projection_metadata (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            schema_version INTEGER NOT NULL CHECK (schema_version = {PROJECTION_SCHEMA_VERSION}),
            dataset_manifest_json BLOB NOT NULL,
            product_count INTEGER NOT NULL CHECK (product_count > 0),
            variant_count INTEGER NOT NULL CHECK (variant_count >= product_count),
            public_item_count INTEGER NOT NULL CHECK (
                public_item_count >= 0 AND public_item_count <= product_count
            )
        ) STRICT
    """,
    ("table", "products"): """
        CREATE TABLE products (
            product_gid TEXT PRIMARY KEY,
            product_gid_length INTEGER NOT NULL CHECK (product_gid_length > 0),
            product_gid_digits TEXT NOT NULL,
            handle TEXT NOT NULL UNIQUE,
            commercial_title TEXT NOT NULL,
            canonical_card_name TEXT,
            game TEXT,
            product_family TEXT NOT NULL,
            product_subtype TEXT,
            is_public INTEGER NOT NULL CHECK (is_public IN (0, 1)),
            normalized_card_name TEXT NOT NULL,
            search_codes_json TEXT NOT NULL,
            has_positive_inventory INTEGER NOT NULL CHECK (has_positive_inventory IN (0, 1)),
            product_record_json BLOB NOT NULL,
            UNIQUE (product_gid_length, product_gid_digits)
        ) STRICT
    """,
    ("table", "variants"): """
        CREATE TABLE variants (
            variant_gid TEXT PRIMARY KEY,
            product_gid TEXT NOT NULL REFERENCES products(product_gid),
            variant_gid_length INTEGER NOT NULL CHECK (variant_gid_length > 0),
            variant_gid_digits TEXT NOT NULL,
            inventory_item_gid TEXT NOT NULL UNIQUE,
            public_variant_json BLOB NOT NULL,
            UNIQUE (product_gid, variant_gid_length, variant_gid_digits)
        ) STRICT
    """,
    ("index", "products_public_game_order"): """
        CREATE INDEX products_public_game_order
        ON products(game, product_gid_length, product_gid_digits)
        WHERE is_public = 1
    """,
    ("index", "products_public_game_family_order"): """
        CREATE INDEX products_public_game_family_order
        ON products(game, product_family, product_gid_length, product_gid_digits)
        WHERE is_public = 1
    """,
    ("index", "variants_parent_order"): """
        CREATE INDEX variants_parent_order
        ON variants(product_gid, variant_gid_length, variant_gid_digits)
    """,
}

_FIRST_PAGE_ALL_SQL = """
SELECT product_gid, handle, commercial_title, canonical_card_name,
       game, product_family, product_subtype, product_record_json
FROM products
WHERE is_public = 1 AND game = ?
ORDER BY product_gid_length, product_gid_digits
LIMIT ?
"""

_NEXT_PAGE_ALL_SQL = """
SELECT product_gid, handle, commercial_title, canonical_card_name,
       game, product_family, product_subtype, product_record_json
FROM products
WHERE is_public = 1 AND game = ?
  AND (product_gid_length, product_gid_digits) > (?, ?)
ORDER BY product_gid_length, product_gid_digits
LIMIT ?
"""

_FIRST_PAGE_FAMILY_SQL = """
SELECT product_gid, handle, commercial_title, canonical_card_name,
       game, product_family, product_subtype, product_record_json
FROM products
WHERE is_public = 1 AND game = ? AND product_family = ?
ORDER BY product_gid_length, product_gid_digits
LIMIT ?
"""

_NEXT_PAGE_FAMILY_SQL = """
SELECT product_gid, handle, commercial_title, canonical_card_name,
       game, product_family, product_subtype, product_record_json
FROM products
WHERE is_public = 1 AND game = ? AND product_family = ?
  AND (product_gid_length, product_gid_digits) > (?, ?)
ORDER BY product_gid_length, product_gid_digits
LIMIT ?
"""

_EXPECTED_SCHEMA_OBJECTS = frozenset(_EXPECTED_SCHEMA_SQL)


def _validated_generation(value: object) -> str:
    if type(value) is not str or len(value) != 71 or _GENERATION_RE.fullmatch(value) is None:
        raise PaginationContractError("dataset generation is invalid")
    return value


def _gid_digits(value: object, pattern: re.Pattern[str], context: str) -> str:
    if type(value) is not str:
        raise PaginationContractError(f"{context} is invalid")
    match = pattern.fullmatch(value)
    if match is None:
        raise PaginationContractError(f"{context} is invalid")
    return match.group(1)


def _utc_timestamp(value: object) -> str:
    if type(value) is not datetime or value.tzinfo is not UTC:
        raise PaginationContractError("pagination clock must return a UTC datetime")
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _validated_request(request: object) -> CatalogRequestV1:
    if type(request) is not CatalogRequestV1:
        raise PaginationContractError("request must be CatalogRequestV1")
    try:
        return CatalogRequestV1.from_json_bytes(request.to_json_bytes())
    except (AttributeError, OverflowError, RecursionError, RuntimeContractError) as exc:
        raise PaginationContractError("request must be canonical CatalogRequestV1") from exc


def _validate_proof_request(request: object) -> CatalogRequestV1:
    canonical = _validated_request(request)
    if canonical.query not in (None, "") and canonical.product_family.value != "single":
        raise UnsupportedPaginationRequestError("search currently requires the single family")
    try:
        normalized_query(canonical)
    except CanonicalSearchError as exc:
        raise PaginationContractError("search query is invalid") from exc
    return canonical


def _validated_cursor_context(context: object) -> CursorContextV1:
    if type(context) is not CursorContextV1:
        raise PaginationContractError("cursor context must be CursorContextV1")
    try:
        return CursorContextV1.from_json_bytes(context.to_json_bytes())
    except (AttributeError, OverflowError, RecursionError, RuntimeContractError) as exc:
        raise PaginationContractError("cursor context must be canonical CursorContextV1") from exc


def _validated_product_record(record: object) -> tuple[CatalogProductRecordV1, bytes]:
    if type(record) is not CatalogProductRecordV1:
        raise PaginationContractError("projection records must be CatalogProductRecordV1")
    try:
        raw = record.to_json_bytes()
        if len(raw) > MAX_CONTRACT_BYTES:
            raise PaginationContractError("catalog Product record exceeds the byte bound")
        canonical = CatalogProductRecordV1.from_json_bytes(raw)
        canonical_raw = canonical.to_json_bytes()
        return canonical, canonical_raw
    except PaginationContractError:
        raise
    except Exception as exc:
        raise PaginationContractError(
            "projection records must be canonical CatalogProductRecordV1"
        ) from exc


def _validated_dataset_manifest(manifest: object) -> tuple[DatasetManifestV1, bytes]:
    if type(manifest) is not DatasetManifestV1:
        raise PaginationContractError("dataset manifest must be DatasetManifestV1")
    try:
        supplied_raw = manifest.to_json_bytes()
        if len(supplied_raw) > MAX_CONTRACT_BYTES:
            raise PaginationContractError("dataset manifest exceeds the byte bound")
        canonical = DatasetManifestV1.from_json_bytes(supplied_raw)
        canonical_raw = canonical.to_json_bytes()
        return canonical, canonical_raw
    except PaginationContractError:
        raise
    except Exception as exc:
        raise PaginationContractError(
            "dataset manifest must be canonical DatasetManifestV1"
        ) from exc


def _url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _url_decode(value: str) -> bytes:
    if _BASE64URL_RE.fullmatch(value) is None or len(value) % 4 == 1:
        raise InvalidCursorError("cursor token is invalid")
    try:
        decoded = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except (binascii.Error, ValueError) as exc:
        raise InvalidCursorError("cursor token is invalid") from exc
    if _url_encode(decoded) != value:
        raise InvalidCursorError("cursor token is invalid")
    return decoded


@dataclass(frozen=True, slots=True)
class CursorCodecV1:
    """HMAC-SHA256 codec whose signed message is the exact canonical context bytes."""

    secret: bytes = field(repr=False)
    ttl_seconds: int = 1800

    def __post_init__(self) -> None:
        if type(self.secret) is not bytes or not (
            MIN_CURSOR_SECRET_BYTES <= len(self.secret) <= MAX_CURSOR_SECRET_BYTES
        ):
            raise PaginationContractError("cursor secret length is invalid")
        if type(self.ttl_seconds) is not int or not (
            1 <= self.ttl_seconds <= MAX_CURSOR_TTL_SECONDS
        ):
            raise PaginationContractError("cursor TTL is invalid")

    def expires_at(self, now: datetime) -> str:
        _utc_timestamp(now)
        try:
            expires = now + timedelta(seconds=self.ttl_seconds)
        except OverflowError as exc:
            raise PaginationContractError("cursor expiry is outside the timestamp range") from exc
        return _utc_timestamp(expires)

    def encode(self, context: CursorContextV1) -> str:
        canonical = _validated_cursor_context(context)
        raw = canonical.to_json_bytes()
        if len(raw) > MAX_CONTRACT_BYTES:
            raise PaginationContractError("cursor context exceeds the byte limit")
        message = (b"nla-search-v2\x00" if canonical.request.query not in (None, "") else b"") + raw
        signature = hmac.new(self.secret, message, hashlib.sha256).digest()
        return f"{_url_encode(raw)}.{_url_encode(signature)}"

    def decode(
        self,
        token: str,
        *,
        expected_request: CatalogRequestV1,
        now: datetime,
        expected_generation: str | None = None,
    ) -> CursorContextV1:
        expected_request = _validated_request(expected_request)
        now_text = _utc_timestamp(now)
        if type(token) is not str or not token or len(token) > MAX_CURSOR_TOKEN_CHARS:
            raise InvalidCursorError("cursor token is invalid")
        parts = token.split(".")
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise InvalidCursorError("cursor token is invalid")
        raw = _url_decode(parts[0])
        signature = _url_decode(parts[1])
        if len(raw) > MAX_CONTRACT_BYTES or len(signature) != hashlib.sha256().digest_size:
            raise InvalidCursorError("cursor token is invalid")
        message = (b"nla-search-v2\x00" if expected_request.query not in (None, "") else b"") + raw
        expected_signature = hmac.new(self.secret, message, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected_signature):
            raise InvalidCursorError("cursor token is invalid")
        try:
            context = CursorContextV1.from_json_bytes(raw)
            canonical = context.to_json_bytes()
        except RuntimeContractError as exc:
            raise InvalidCursorError("cursor token is invalid") from exc
        if canonical != raw:
            raise InvalidCursorError("cursor token is invalid")
        if context.request != expected_request:
            raise CursorContextMismatchError("cursor request context does not match")
        if expected_generation is not None:
            generation = _validated_generation(expected_generation)
            if context.dataset_generation != generation:
                raise StaleGenerationError("cursor dataset generation is stale")
        try:
            context.assert_not_expired(now_text)
        except RuntimeContractError as exc:
            raise CursorExpiredError("cursor has expired") from exc
        return context


@dataclass(frozen=True, slots=True)
class ProjectionStats:
    product_count: int
    variant_count: int
    public_item_count: int


@dataclass(frozen=True, slots=True)
class _ProjectionFileStamp:
    device: int
    inode: int
    size: int
    modified_ns: int
    changed_ns: int
    mode: int
    link_count: int
    header_sha256: str


@dataclass(frozen=True, slots=True)
class _ProjectionFileFingerprint:
    stamp: _ProjectionFileStamp
    content_sha256: str


def _stat_signature(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
        value.st_mode,
        value.st_nlink,
    )


def _path_identity_signature(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_nlink,
    )


def _projection_file_state(
    path: Path, *, include_content_hash: bool
) -> tuple[_ProjectionFileStamp, str | None]:
    try:
        if path.is_symlink():
            raise DatasetUnavailableError("catalog dataset is unavailable")
        content_hasher = hashlib.sha256() if include_content_hash else None
        with path.open("rb") as source:
            before = os.fstat(source.fileno())
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_size < SQLITE_HEADER_BYTES
                or before.st_size > MAX_PROJECTION_FILE_BYTES
                or before.st_mode & _WRITE_BITS
            ):
                raise DatasetUnavailableError("catalog dataset is unavailable")
            header = source.read(SQLITE_HEADER_BYTES)
            if len(header) != SQLITE_HEADER_BYTES or not header.startswith(b"SQLite format 3\x00"):
                raise DatasetUnavailableError("catalog dataset is unavailable")
            if content_hasher is not None:
                content_hasher.update(header)
                while chunk := source.read(FILE_HASH_CHUNK_BYTES):
                    content_hasher.update(chunk)
            after = os.fstat(source.fileno())
        current = path.stat(follow_symlinks=False)
        if (
            not stat.S_ISREG(current.st_mode)
            or _stat_signature(before) != _stat_signature(after)
            or _path_identity_signature(after) != _path_identity_signature(current)
        ):
            raise DatasetUnavailableError("catalog dataset is unavailable")
        stamp = _ProjectionFileStamp(
            device=after.st_dev,
            inode=after.st_ino,
            size=after.st_size,
            modified_ns=after.st_mtime_ns,
            changed_ns=after.st_ctime_ns,
            mode=after.st_mode,
            link_count=after.st_nlink,
            header_sha256=hashlib.sha256(header).hexdigest(),
        )
        digest = None if content_hasher is None else content_hasher.hexdigest()
        return stamp, digest
    except DatasetUnavailableError:
        raise
    except Exception as exc:
        raise DatasetUnavailableError("catalog dataset is unavailable") from exc


def _projection_file_fingerprint(path: Path) -> _ProjectionFileFingerprint:
    stamp, digest = _projection_file_state(path, include_content_hash=True)
    if digest is None:
        raise DatasetUnavailableError("catalog dataset is unavailable")
    return _ProjectionFileFingerprint(stamp=stamp, content_sha256=digest)


@dataclass(frozen=True, slots=True)
class CatalogProjection:
    """One verified SQLite file that is opened only in immutable read-only mode."""

    path: Path
    dataset_generation: str
    manifest: DatasetManifestV1
    stats: ProjectionStats
    _file_fingerprint: _ProjectionFileFingerprint = field(repr=False)

    @classmethod
    def open(cls, path: Path, *, expected_generation: str | None = None) -> CatalogProjection:
        expected = (
            None if expected_generation is None else _validated_generation(expected_generation)
        )
        if not isinstance(path, Path):
            raise DatasetUnavailableError("catalog dataset is unavailable")
        try:
            if path.is_symlink() or not path.is_file():
                raise DatasetUnavailableError("catalog dataset is unavailable")
            resolved = path.resolve(strict=True)
            fingerprint_before = _projection_file_fingerprint(resolved)
            with _readonly_connection(resolved) as connection:
                _verify_projection_schema(connection)
                application_id = connection.execute("PRAGMA application_id").fetchone()[0]
                user_version = connection.execute("PRAGMA user_version").fetchone()[0]
                quick_check = connection.execute("PRAGMA quick_check").fetchall()
                foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
                metadata = connection.execute(
                    """SELECT schema_version, dataset_manifest_json, product_count,
                              variant_count, public_item_count
                       FROM projection_metadata ORDER BY singleton"""
                ).fetchall()
                if (
                    application_id != PROJECTION_APPLICATION_ID
                    or user_version != PROJECTION_SCHEMA_VERSION
                ):
                    raise DatasetUnavailableError("catalog dataset is unavailable")
                if len(metadata) != 1 or foreign_keys:
                    raise DatasetUnavailableError("catalog dataset is unavailable")
                row = metadata[0]
                manifest_raw = row["dataset_manifest_json"]
                if type(manifest_raw) is not bytes or len(manifest_raw) > MAX_CONTRACT_BYTES:
                    raise DatasetUnavailableError("catalog dataset is unavailable")
                manifest = DatasetManifestV1.from_json_bytes(manifest_raw)
                if manifest.to_json_bytes() != manifest_raw:
                    raise DatasetUnavailableError("catalog dataset is unavailable")
                generation = manifest.dataset_generation
                stats = ProjectionStats(
                    product_count=row["product_count"],
                    variant_count=row["variant_count"],
                    public_item_count=row["public_item_count"],
                )
                actual = ProjectionStats(
                    product_count=connection.execute("SELECT COUNT(*) FROM products").fetchone()[0],
                    variant_count=connection.execute("SELECT COUNT(*) FROM variants").fetchone()[0],
                    public_item_count=connection.execute(
                        "SELECT COUNT(*) FROM products WHERE is_public = ?", (1,)
                    ).fetchone()[0],
                )
                valid_quick_check = len(quick_check) == 1 and tuple(quick_check[0]) == ("ok",)
                if (
                    row["schema_version"] != PROJECTION_SCHEMA_VERSION
                    or not valid_quick_check
                    or any(
                        type(value) is not int
                        for value in (
                            stats.product_count,
                            stats.variant_count,
                            stats.public_item_count,
                        )
                    )
                    or stats != actual
                    or stats.product_count < 1
                    or stats.product_count > MAX_PROJECTION_PRODUCTS
                    or stats.variant_count < stats.product_count
                    or stats.variant_count > MAX_PROJECTION_VARIANTS
                    or not 0 <= stats.public_item_count <= stats.product_count
                ):
                    raise DatasetUnavailableError("catalog dataset is unavailable")
                records = _verify_projection_semantics(connection, stats)
                manifest.validate_records(records)
            fingerprint_after = _projection_file_fingerprint(resolved)
            if fingerprint_after != fingerprint_before:
                raise DatasetUnavailableError("catalog dataset is unavailable")
        except DatasetUnavailableError:
            raise
        except (
            OSError,
            OverflowError,
            RecursionError,
            sqlite3.Error,
            TypeError,
            ValueError,
            PaginationContractError,
        ) as exc:
            raise DatasetUnavailableError("catalog dataset is unavailable") from exc
        if expected is not None and generation != expected:
            raise StaleGenerationError("catalog dataset generation is stale")
        return cls(
            path=resolved,
            dataset_generation=generation,
            manifest=manifest,
            stats=stats,
            _file_fingerprint=fingerprint_after,
        )

    def _assert_file_unchanged(self) -> None:
        stamp, _ = _projection_file_state(self.path, include_content_hash=False)
        if stamp != self._file_fingerprint.stamp:
            raise DatasetUnavailableError("catalog dataset is unavailable")

    def fetch_page(
        self,
        request: CatalogRequestV1,
        context: CursorContextV1,
        *,
        checkpoint: Callable[[], None] | None = None,
    ) -> CatalogPageV1:
        request = _validate_proof_request(request)
        context = _validated_cursor_context(context)
        if checkpoint is not None and not callable(checkpoint):
            raise PaginationContractError("pagination checkpoint is invalid")
        if context.request != request:
            raise CursorContextMismatchError("cursor request context does not match")
        if context.dataset_generation != self.dataset_generation:
            raise StaleGenerationError("cursor dataset generation is stale")
        after_digits = (
            None
            if context.last_product_gid is None
            else _gid_digits(context.last_product_gid, _PRODUCT_GID_RE, "Product GID")
        )
        checkpoint_failure: BaseException | None = None

        def run_checkpoint() -> None:
            nonlocal checkpoint_failure
            if checkpoint is None:
                return
            try:
                checkpoint()
            except BaseException as exc:
                checkpoint_failure = exc
                raise

        def sqlite_progress_checkpoint() -> int:
            try:
                run_checkpoint()
            except BaseException:
                return 1
            return 0

        run_checkpoint()
        try:
            self._assert_file_unchanged()
            run_checkpoint()
            with _readonly_connection(self.path) as connection:
                try:
                    if checkpoint is not None:
                        connection.set_progress_handler(
                            sqlite_progress_checkpoint, _SQLITE_PROGRESS_VM_STEPS
                        )
                    rows = self._product_rows(
                        connection,
                        request=request,
                        after_digits=after_digits,
                        limit=request.page_size + 1,
                    )
                    run_checkpoint()
                    has_next_page = len(rows) > request.page_size
                    page_rows = rows[: request.page_size]
                    product_gids: list[str] = []
                    for row in page_rows:
                        run_checkpoint()
                        product_gids.append(row["product_gid"])
                    variants = self._variant_rows(
                        connection,
                        tuple(product_gids),
                        checkpoint=run_checkpoint,
                    )
                    run_checkpoint()
                finally:
                    if checkpoint is not None:
                        connection.set_progress_handler(None, 0)
            self._assert_file_unchanged()
            item_values: list[CatalogItemV1] = []
            for row in page_rows:
                run_checkpoint()
                item_values.append(self._item_from_row(row, variants[row["product_gid"]]))
            items = tuple(item_values)
            run_checkpoint()
        except DatasetUnavailableError:
            raise
        except (
            KeyError,
            OSError,
            OverflowError,
            RecursionError,
            sqlite3.Error,
            RuntimeContractError,
            TypeError,
            ValueError,
        ) as exc:
            if checkpoint_failure is not None:
                raise checkpoint_failure from None
            raise DatasetUnavailableError("catalog dataset is unavailable") from exc
        try:
            next_context = (
                CursorContextV1.from_request(
                    request,
                    self.dataset_generation,
                    last_product_gid=items[-1].product_gid,
                    expires_at=context.expires_at,
                )
                if has_next_page
                else None
            )
            page = CatalogPageV1(
                dataset_generation=self.dataset_generation,
                request=request,
                request_context_sha256=context.request_context_sha256,
                items=items,
                returned_product_count=len(items),
                returned_variant_count=sum(len(item.variants) for item in items),
                has_next_page=has_next_page,
                next_cursor_context=next_context,
            )
            page.validate_for_context(context)
        except (OverflowError, RecursionError, RuntimeContractError) as exc:
            raise DatasetUnavailableError("catalog dataset is unavailable") from exc
        run_checkpoint()
        return page

    @staticmethod
    def _product_rows(
        connection: sqlite3.Connection,
        *,
        request: CatalogRequestV1,
        after_digits: str | None,
        limit: int,
    ) -> list[sqlite3.Row]:
        if request.query not in (None, "") or request.filters.nonempty:
            where, parameters = search_scope(request)
            if after_digits is not None:
                where += " AND (product_gid_length, product_gid_digits) > (?, ?)"
                parameters += (len(after_digits), after_digits)
            # Only fixed predicates are assembled; query/filter/cursor values stay bound.
            sql = f"""SELECT product_gid, handle, commercial_title, canonical_card_name,
                             game, product_family, product_subtype, product_record_json
                      FROM products WHERE {where}
                      ORDER BY product_gid_length, product_gid_digits LIMIT ?"""  # noqa: S608
            return connection.execute(sql, (*parameters, limit)).fetchall()
        family = request.product_family
        if family.value == "all":
            if after_digits is None:
                sql = _FIRST_PAGE_ALL_SQL
                parameters = (request.game.value, limit)
            else:
                sql = _NEXT_PAGE_ALL_SQL
                parameters = (
                    request.game.value,
                    len(after_digits),
                    after_digits,
                    limit,
                )
        elif after_digits is None:
            sql = _FIRST_PAGE_FAMILY_SQL
            parameters = (request.game.value, family.value, limit)
        else:
            sql = _NEXT_PAGE_FAMILY_SQL
            parameters = (
                request.game.value,
                family.value,
                len(after_digits),
                after_digits,
                limit,
            )
        return connection.execute(sql, parameters).fetchall()

    def suggest(
        self,
        request: CatalogRequestV1,
        *,
        limit: int = 10,
        checkpoint: Callable[[], None] | None = None,
    ) -> tuple[SingleCardSuggestion, ...]:
        """Bounded same-query groups; sold-out prints remain included by default."""
        request = _validate_proof_request(request)
        if request.product_family.value != "single":
            raise UnsupportedPaginationRequestError("suggestions require the single family")
        if checkpoint is not None and not callable(checkpoint):
            raise PaginationContractError("pagination checkpoint is invalid")
        failure: BaseException | None = None

        def progress() -> int:
            nonlocal failure
            try:
                if checkpoint is not None:
                    checkpoint()
            except BaseException as exc:
                failure = exc
                return 1
            return 0

        if progress():
            assert failure is not None
            raise failure
        self._assert_file_unchanged()
        try:
            with _readonly_connection(self.path) as connection:
                connection.set_progress_handler(progress, _SQLITE_PROGRESS_VM_STEPS)
                result = select_suggestions(connection, request, limit=limit)
        except sqlite3.Error as exc:
            if failure is not None:
                raise failure from None
            raise DatasetUnavailableError("catalog dataset is unavailable") from exc
        self._assert_file_unchanged()
        if progress():
            assert failure is not None
            raise failure
        return result

    @staticmethod
    def _variant_rows(
        connection: sqlite3.Connection,
        product_gids: tuple[str, ...],
        *,
        checkpoint: Callable[[], None] | None = None,
    ) -> dict[str, tuple[CatalogVariantItemV1, ...]]:
        if not product_gids:
            return {}
        placeholders = ",".join("?" for _ in product_gids)
        sql = f"""SELECT v.product_gid, v.public_variant_json
                  FROM variants AS v
                  JOIN products AS p ON p.product_gid = v.product_gid
                  WHERE v.product_gid IN ({placeholders})
                  ORDER BY p.product_gid_length, p.product_gid_digits,
                           v.variant_gid_length, v.variant_gid_digits"""  # noqa: S608
        rows = connection.execute(sql, product_gids).fetchall()
        grouped: dict[str, list[CatalogVariantItemV1]] = {gid: [] for gid in product_gids}
        for row in rows:
            if checkpoint is not None:
                checkpoint()
            raw = row["public_variant_json"]
            grouped[row["product_gid"]].append(CatalogVariantItemV1.from_json_bytes(raw))
        result: dict[str, tuple[CatalogVariantItemV1, ...]] = {}
        for gid, values in grouped.items():
            if checkpoint is not None:
                checkpoint()
            if not values:
                raise DatasetUnavailableError("catalog dataset is unavailable")
            result[gid] = tuple(values)
        return result

    @staticmethod
    def _item_from_row(
        row: sqlite3.Row, variants: tuple[CatalogVariantItemV1, ...]
    ) -> CatalogItemV1:
        return CatalogItemV1(
            product_gid=row["product_gid"],
            handle=row["handle"],
            commercial_title=row["commercial_title"],
            canonical_card_name=row["canonical_card_name"],
            game=Game(row["game"]),
            product_family=ProductFamily(row["product_family"]),
            product_subtype=row["product_subtype"],
            variants=variants,
            card_metadata=CatalogProductRecordV1.from_json_bytes(
                row["product_record_json"]
            ).card_metadata,
        )


@contextmanager
def _readonly_connection(path: Path) -> Iterator[sqlite3.Connection]:
    uri = f"{path.as_uri()}?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True, timeout=5.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA trusted_schema = OFF")
    try:
        yield connection
    finally:
        connection.close()


def _normalized_schema_sql(value: object) -> str:
    if type(value) is not str:
        raise DatasetUnavailableError("catalog dataset is unavailable")
    return " ".join(value.strip().removesuffix(";").split())


def _verify_projection_schema(connection: sqlite3.Connection) -> None:
    schema_sql = {
        (row["type"], row["name"]): _normalized_schema_sql(row["sql"])
        for row in connection.execute(
            """SELECT type, name, sql FROM sqlite_schema
               WHERE substr(name, 1, 7) != ? ORDER BY type, name""",
            ("sqlite_",),
        )
    }
    expected_sql = {
        identity: _normalized_schema_sql(sql) for identity, sql in _EXPECTED_SCHEMA_SQL.items()
    }
    if frozenset(schema_sql) != _EXPECTED_SCHEMA_OBJECTS or schema_sql != expected_sql:
        raise DatasetUnavailableError("catalog dataset is unavailable")


def _verify_projection_semantics(
    connection: sqlite3.Connection, stats: ProjectionStats
) -> tuple[CatalogProductRecordV1, ...]:
    products = connection.execute(
        """SELECT product_gid, product_gid_length, product_gid_digits, handle,
                  commercial_title, canonical_card_name, game, product_family,
                  product_subtype, is_public, normalized_card_name, search_codes_json,
                  has_positive_inventory, product_record_json
           FROM products
           ORDER BY product_gid_length, product_gid_digits"""
    )
    variants = iter(
        connection.execute(
            """SELECT v.variant_gid, v.product_gid, v.variant_gid_length,
                      v.variant_gid_digits, v.inventory_item_gid, v.public_variant_json
               FROM variants AS v
               JOIN products AS p ON p.product_gid = v.product_gid
               ORDER BY p.product_gid_length, p.product_gid_digits,
                        v.variant_gid_length, v.variant_gid_digits"""
        )
    )
    next_variant = next(variants, None)
    product_count = 0
    variant_count = 0
    public_count = 0
    canonical_records: list[CatalogProductRecordV1] = []
    for row in products:
        raw_record = row["product_record_json"]
        if type(raw_record) is not bytes or len(raw_record) > MAX_CONTRACT_BYTES:
            raise DatasetUnavailableError("catalog dataset is unavailable")
        record = CatalogProductRecordV1.from_json_bytes(raw_record)
        if record.to_json_bytes() != raw_record:
            raise DatasetUnavailableError("catalog dataset is unavailable")
        product_digits = _gid_digits(record.product_gid, _PRODUCT_GID_RE, "Product GID")
        is_public = record.publishable and record.product_family is not ProductFamily.UNCLASSIFIED
        expected_product = (
            record.product_gid,
            len(product_digits),
            product_digits,
            record.handle,
            record.commercial_title,
            record.canonical_card_name,
            None if record.game is None else record.game.value,
            record.product_family.value,
            record.product_subtype,
            int(is_public),
            *search_facts(record),
        )
        actual_product = tuple(row[name] for name in row.keys()[:-1])
        if actual_product != expected_product or len(record.variants) > MAX_VARIANTS_PER_PRODUCT:
            raise DatasetUnavailableError("catalog dataset is unavailable")
        product_count += 1
        public_count += int(is_public)
        canonical_records.append(record)
        for expected_variant in record.variants:
            if next_variant is None:
                raise DatasetUnavailableError("catalog dataset is unavailable")
            variant_digits = _gid_digits(
                expected_variant.variant_gid, _VARIANT_GID_RE, "ProductVariant GID"
            )
            raw_variant = next_variant["public_variant_json"]
            if type(raw_variant) is not bytes or len(raw_variant) > MAX_CONTRACT_BYTES:
                raise DatasetUnavailableError("catalog dataset is unavailable")
            public_variant = CatalogVariantItemV1.from_json_bytes(raw_variant)
            expected_public_variant = CatalogVariantItemV1.from_variant_record(expected_variant)
            expected_variant_row = (
                expected_variant.variant_gid,
                record.product_gid,
                len(variant_digits),
                variant_digits,
                expected_variant.inventory_item_gid,
            )
            actual_variant_row = tuple(next_variant[name] for name in next_variant.keys()[:-1])
            if (
                actual_variant_row != expected_variant_row
                or public_variant != expected_public_variant
                or public_variant.to_json_bytes() != raw_variant
            ):
                raise DatasetUnavailableError("catalog dataset is unavailable")
            variant_count += 1
            next_variant = next(variants, None)
    if (
        next_variant is not None
        or product_count != stats.product_count
        or variant_count != stats.variant_count
        or public_count != stats.public_item_count
    ):
        raise DatasetUnavailableError("catalog dataset is unavailable")
    return tuple(canonical_records)


def build_catalog_projection(
    destination: Path,
    *,
    manifest: DatasetManifestV1,
    records: tuple[CatalogProductRecordV1, ...],
) -> CatalogProjection:
    """Build and atomically install one never-overwritten projection file."""

    if not isinstance(destination, Path):
        raise PaginationContractError("projection destination must be a Path")
    canonical_manifest, manifest_raw = _validated_dataset_manifest(manifest)
    generation = canonical_manifest.dataset_generation
    if type(records) is not tuple or not records or len(records) > MAX_PROJECTION_PRODUCTS:
        raise PaginationContractError("projection records are invalid or outside bounds")
    try:
        resolved = destination.resolve()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        if resolved.exists():
            raise ProjectionBuildError("immutable projection destination already exists")
    except ProjectionBuildError:
        raise
    except (OSError, RuntimeError) as exc:
        raise ProjectionBuildError("immutable projection destination is unavailable") from exc

    product_rows: list[tuple[object, ...]] = []
    variant_rows: list[tuple[object, ...]] = []
    seen_products: set[str] = set()
    seen_handles: set[str] = set()
    seen_variants: set[str] = set()
    seen_inventory_items: set[str] = set()
    canonical_records: list[CatalogProductRecordV1] = []
    public_count = 0
    for supplied_record in records:
        record, raw_record = _validated_product_record(supplied_record)
        if record.product_gid in seen_products or record.handle in seen_handles:
            raise ProjectionBuildError("projection Product identity is duplicated")
        if len(record.variants) > MAX_VARIANTS_PER_PRODUCT:
            raise PaginationContractError("Product Variant fanout exceeds the bound")
        product_digits = _gid_digits(record.product_gid, _PRODUCT_GID_RE, "Product GID")
        is_public = record.publishable and record.product_family is not ProductFamily.UNCLASSIFIED
        public_count += int(is_public)
        product_rows.append(
            (
                record.product_gid,
                len(product_digits),
                product_digits,
                record.handle,
                record.commercial_title,
                record.canonical_card_name,
                None if record.game is None else record.game.value,
                record.product_family.value,
                record.product_subtype,
                int(is_public),
                *search_facts(record),
                raw_record,
            )
        )
        canonical_records.append(record)
        seen_products.add(record.product_gid)
        seen_handles.add(record.handle)
        for variant in record.variants:
            if (
                variant.variant_gid in seen_variants
                or variant.inventory_item_gid in seen_inventory_items
            ):
                raise ProjectionBuildError(
                    "projection Variant or inventory-item identity is duplicated"
                )
            variant_digits = _gid_digits(variant.variant_gid, _VARIANT_GID_RE, "ProductVariant GID")
            raw_variant = CatalogVariantItemV1.from_variant_record(variant).to_json_bytes()
            variant_rows.append(
                (
                    variant.variant_gid,
                    record.product_gid,
                    len(variant_digits),
                    variant_digits,
                    variant.inventory_item_gid,
                    raw_variant,
                )
            )
            seen_variants.add(variant.variant_gid)
            seen_inventory_items.add(variant.inventory_item_gid)
            if len(variant_rows) > MAX_PROJECTION_VARIANTS:
                raise PaginationContractError("projection Variant count exceeds the bound")

    try:
        canonical_manifest.validate_records(tuple(canonical_records))
    except Exception as exc:
        raise PaginationContractError("dataset manifest does not match projection records") from exc

    product_rows.sort(key=lambda row: (row[1], row[2]))
    product_order = {row[0]: (row[1], row[2]) for row in product_rows}
    variant_rows.sort(key=lambda row: (*product_order[row[1]], row[2], row[3]))
    try:
        descriptor = tempfile.mkstemp(prefix=".nla-catalog-", suffix=".tmp", dir=resolved.parent)
        os.close(descriptor[0])
    except OSError as exc:
        raise ProjectionBuildError("immutable projection build failed") from exc
    temporary = Path(descriptor[1])
    installed = False
    try:
        connection = sqlite3.connect(temporary)
        try:
            connection.executescript(_SCHEMA)
            connection.executemany(
                "INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                product_rows,
            )
            connection.executemany("INSERT INTO variants VALUES (?, ?, ?, ?, ?, ?)", variant_rows)
            connection.execute(
                "INSERT INTO projection_metadata VALUES (?, ?, ?, ?, ?, ?)",
                (
                    1,
                    PROJECTION_SCHEMA_VERSION,
                    manifest_raw,
                    len(product_rows),
                    len(variant_rows),
                    public_count,
                ),
            )
            connection.commit()
            if connection.execute("PRAGMA quick_check").fetchone() != ("ok",):
                raise ProjectionBuildError("projection integrity check failed")
        finally:
            connection.close()
        os.link(temporary, resolved)
        installed = True
    except ProjectionBuildError:
        raise
    except (OSError, OverflowError, RuntimeContractError, sqlite3.Error) as exc:
        raise ProjectionBuildError("immutable projection build failed") from exc
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError as exc:
            if installed:
                try:
                    resolved.unlink()
                except OSError as rollback_exc:
                    raise ProjectionBuildError(
                        "immutable projection cleanup and rollback failed"
                    ) from rollback_exc
            raise ProjectionBuildError("immutable projection cleanup failed") from exc
    try:
        resolved.chmod(_READ_ONLY_MODE)
        return CatalogProjection.open(resolved, expected_generation=generation)
    except Exception as exc:
        try:
            resolved.chmod(_READ_ONLY_MODE | stat.S_IWUSR)
            resolved.unlink()
        except Exception as rollback_exc:
            raise ProjectionBuildError(
                "immutable projection verification and rollback failed"
            ) from rollback_exc
        raise ProjectionBuildError("immutable projection verification failed") from exc


class AtomicCatalogActivation:
    """Lock-linearized selection of complete immutable generation objects."""

    def __init__(self, initial: CatalogProjection | None = None) -> None:
        self._lock = threading.Lock()
        self._active: CatalogProjection | None = None
        if initial is not None:
            self.activate(initial)

    @property
    def active_generation(self) -> str | None:
        with self._lock:
            return None if self._active is None else self._active.dataset_generation

    def activate(self, projection: CatalogProjection) -> None:
        if type(projection) is not CatalogProjection:
            raise PaginationContractError("activation requires CatalogProjection")
        verified = CatalogProjection.open(
            projection.path, expected_generation=projection.dataset_generation
        )
        with self._lock:
            self._active = verified

    def select(self, expected_generation: str | None = None) -> CatalogProjection:
        expected = (
            None if expected_generation is None else _validated_generation(expected_generation)
        )
        with self._lock:
            selected = self._active
            if selected is None:
                raise DatasetUnavailableError("catalog dataset is unavailable")
            if expected is not None and selected.dataset_generation != expected:
                raise StaleGenerationError("cursor dataset generation is stale")
            return selected


@dataclass(frozen=True, slots=True)
class AuthenticatedCatalogPage:
    """Internal page plus its authenticated client token, if another page exists."""

    page: CatalogPageV1
    next_cursor: str | None

    def __post_init__(self) -> None:
        if type(self.page) is not CatalogPageV1:
            raise PaginationContractError("authenticated page must contain CatalogPageV1")
        if self.next_cursor is not None and (
            type(self.next_cursor) is not str or not self.next_cursor
        ):
            raise PaginationContractError("authenticated next cursor is invalid")
        if self.page.has_next_page != (self.next_cursor is not None):
            raise PaginationContractError("authenticated cursor presence is inconsistent")


class CatalogPaginator:
    """Issue-#7 internal paginator; it does not authorize runtime output."""

    def __init__(
        self,
        activation: AtomicCatalogActivation,
        cursor_codec: CursorCodecV1,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if type(activation) is not AtomicCatalogActivation:
            raise PaginationContractError("paginator activation is invalid")
        if type(cursor_codec) is not CursorCodecV1:
            raise PaginationContractError("paginator cursor codec is invalid")
        if clock is not None and not callable(clock):
            raise PaginationContractError("paginator clock is invalid")
        self._activation = activation
        self._cursor_codec = cursor_codec
        self._clock = clock or (lambda: datetime.now(UTC))

    def fetch_page(
        self,
        request: CatalogRequestV1,
        *,
        cursor: str | None = None,
        checkpoint: Callable[[], None] | None = None,
    ) -> AuthenticatedCatalogPage:
        request = _validate_proof_request(request)
        if checkpoint is not None and not callable(checkpoint):
            raise PaginationContractError("pagination checkpoint is invalid")
        if checkpoint is not None:
            checkpoint()
        try:
            now = self._clock()
        except Exception as exc:
            raise PaginationContractError("paginator clock failed") from exc
        _utc_timestamp(now)
        if cursor is None:
            projection = self._activation.select()
            context = CursorContextV1.from_request(
                request,
                projection.dataset_generation,
                last_product_gid=None,
                expires_at=self._cursor_codec.expires_at(now),
            )
        else:
            projection = self._activation.select()
            context = self._cursor_codec.decode(
                cursor,
                expected_request=request,
                expected_generation=projection.dataset_generation,
                now=now,
            )
        if checkpoint is not None:
            checkpoint()
        page = projection.fetch_page(request, context, checkpoint=checkpoint)
        if checkpoint is not None:
            checkpoint()
        next_cursor = (
            None
            if page.next_cursor_context is None
            else self._cursor_codec.encode(page.next_cursor_context)
        )
        if checkpoint is not None:
            checkpoint()
        return AuthenticatedCatalogPage(page=page, next_cursor=next_cursor)
