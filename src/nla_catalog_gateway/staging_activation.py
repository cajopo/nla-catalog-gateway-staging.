"""Atomic, pinned activation of immutable staging generation packages."""

from __future__ import annotations

import ctypes
import hashlib
import importlib
import json
import os
import re
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, cast

from nla_catalog_gateway.staging_generation import (
    REPOSITORY_ROOT,
    VerifiedStagingGenerationV1,
    open_staging_generation,
)

ACTIVATION_SCHEMA_VERSION = 1
ACTIVATION_FILENAME = "activation.v1.json"
GENERATIONS_DIRECTORY = "generations"
ABSENT_ACTIVATION_SHA256 = hashlib.sha256(b"").hexdigest()
MAX_ACTIVATION_BYTES = 1024

_LOCK_FILENAME = ".activation.v1.lock"
_TEMP_PREFIX = ".activation.v1.tmp-"
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_CONCRETE_PATH_TYPE = type(Path())
_POINTER_FIELDS = frozenset({"schemaVersion", "currentManifestSha256", "previousManifestSha256"})
_ERROR = "staging activation failed"
_AMBIGUOUS_ERROR = "staging activation outcome is ambiguous"
_REPARSE_POINT_ATTRIBUTE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_WINDOWS_INVALID_HANDLE = ctypes.c_void_p(-1).value
_WINDOWS_GENERIC_READ = 0x80000000
_WINDOWS_GENERIC_WRITE = 0x40000000
_WINDOWS_FILE_SHARE_READ = 0x00000001
_WINDOWS_FILE_SHARE_WRITE = 0x00000002
_WINDOWS_OPEN_ALWAYS = 4
_WINDOWS_FILE_ATTRIBUTE_NORMAL = 0x00000080
_WINDOWS_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000


class StagingActivationError(ValueError):
    """A fixed, value-free activation rejection."""


class StagingActivationOutcomeAmbiguous(StagingActivationError):
    """The pointer could not be attested after an atomic replacement."""


@dataclass(frozen=True, slots=True)
class _ActivationPointer:
    current_manifest_sha256: str = field(repr=False)
    previous_manifest_sha256: str | None = field(repr=False)


@dataclass(frozen=True, slots=True, init=False, repr=False)
class ActiveStagingGenerationV1:
    """Opaque active generation plus the exact externally pinned pointer state."""

    generation: VerifiedStagingGenerationV1 = field(repr=False)
    current_manifest_sha256: str = field(repr=False)
    previous_manifest_sha256: str | None = field(repr=False)
    activation_sha256: str = field(repr=False)

    def __new__(cls, *_args: object, **_kwargs: object) -> ActiveStagingGenerationV1:
        raise StagingActivationError(_ERROR)

    def __reduce__(self) -> object:
        raise StagingActivationError(_ERROR)

    def __reduce_ex__(self, _protocol: int) -> object:
        raise StagingActivationError(_ERROR)


def _fail() -> StagingActivationError:
    return StagingActivationError(_ERROR)


def _ambiguous() -> StagingActivationOutcomeAmbiguous:
    return StagingActivationOutcomeAmbiguous(_AMBIGUOUS_ERROR)


def _sha256(value: object) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise _fail()
    return value


def _validated_root(value: object) -> Path:
    if type(value) is not _CONCRETE_PATH_TYPE or not value.is_absolute():
        raise _fail()
    root = value.resolve(strict=True)
    if (
        root != value
        or value.is_symlink()
        or not value.is_dir()
        or root == REPOSITORY_ROOT
        or root.is_relative_to(REPOSITORY_ROOT)
    ):
        raise _fail()
    generations = root / GENERATIONS_DIRECTORY
    resolved_generations = generations.resolve(strict=True)
    if resolved_generations != generations or generations.is_symlink() or not generations.is_dir():
        raise _fail()
    return root


def _canonical_pointer_bytes(pointer: _ActivationPointer) -> bytes:
    return json.dumps(
        {
            "currentManifestSha256": pointer.current_manifest_sha256,
            "previousManifestSha256": pointer.previous_manifest_sha256,
            "schemaVersion": ACTIVATION_SCHEMA_VERSION,
        },
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _parse_pointer(raw: bytes) -> _ActivationPointer:
    if not raw or len(raw) > MAX_ACTIVATION_BYTES:
        raise _fail()
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise _fail() from None
    if (
        type(value) is not dict
        or frozenset(value) != _POINTER_FIELDS
        or type(value["schemaVersion"]) is not int
        or value["schemaVersion"] != ACTIVATION_SCHEMA_VERSION
    ):
        raise _fail()
    current = _sha256(value["currentManifestSha256"])
    previous_value = value["previousManifestSha256"]
    previous = None if previous_value is None else _sha256(previous_value)
    pointer = _ActivationPointer(current, previous)
    if previous == current or _canonical_pointer_bytes(pointer) != raw:
        raise _fail()
    return pointer


def _read_pointer(root: Path, expected_sha256: str) -> tuple[_ActivationPointer, bytes]:
    expected = _sha256(expected_sha256)
    path = root / ACTIVATION_FILENAME
    try:
        before = path.stat(follow_symlinks=False)
        if path.is_symlink() or not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise _fail()
        with path.open("rb") as source:
            opened = os.fstat(source.fileno())
            raw = source.read(MAX_ACTIVATION_BYTES + 1)
            after_read = os.fstat(source.fileno())
        after = path.stat(follow_symlinks=False)
    except (OSError, ValueError):
        raise _fail() from None

    def identity(item: os.stat_result) -> tuple[int, int, int, int, int, int]:
        return (
            item.st_dev,
            item.st_ino,
            item.st_size,
            item.st_mtime_ns,
            item.st_mode,
            item.st_nlink,
        )

    if not (
        identity(before) == identity(opened) == identity(after_read) == identity(after)
        and hashlib.sha256(raw).hexdigest() == expected
    ):
        raise _fail()
    return _parse_pointer(raw), raw


def _read_expected_state(
    root: Path,
    expected_sha256: str,
    *,
    allow_absent: bool,
) -> tuple[_ActivationPointer | None, bytes]:
    path = root / ACTIVATION_FILENAME
    if not path.exists():
        if path.is_symlink() or not allow_absent or expected_sha256 != ABSENT_ACTIVATION_SHA256:
            raise _fail()
        return None, b""
    return _read_pointer(root, expected_sha256)


def _package_directory(root: Path, manifest_sha256: str) -> Path:
    manifest = _sha256(manifest_sha256)
    return root / GENERATIONS_DIRECTORY / manifest


def _best_effort_unlink(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        return


def _lock_file_identity(path: Path, handle: BinaryIO) -> tuple[int, int]:
    path_state = path.stat(follow_symlinks=False)
    opened_state = os.fstat(handle.fileno())
    if (
        path.is_symlink()
        or not stat.S_ISREG(path_state.st_mode)
        or path_state.st_nlink != 1
        or bool(getattr(path_state, "st_file_attributes", 0) & _REPARSE_POINT_ATTRIBUTE)
        or (path_state.st_dev, path_state.st_ino) != (opened_state.st_dev, opened_state.st_ino)
    ):
        raise OSError
    return path_state.st_dev, path_state.st_ino


def _windows_create_lock_handle(path: Path) -> int:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    )
    create_file.restype = ctypes.c_void_p
    handle = create_file(
        str(path),
        _WINDOWS_GENERIC_READ | _WINDOWS_GENERIC_WRITE,
        _WINDOWS_FILE_SHARE_READ | _WINDOWS_FILE_SHARE_WRITE,
        None,
        _WINDOWS_OPEN_ALWAYS,
        _WINDOWS_FILE_ATTRIBUTE_NORMAL | _WINDOWS_FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    if handle == _WINDOWS_INVALID_HANDLE:
        raise OSError
    return int(handle)


def _windows_close_handle(handle: int) -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (ctypes.c_void_p,)
    close_handle.restype = ctypes.c_int
    close_handle(ctypes.c_void_p(handle))


def _binary_file_from_descriptor(descriptor: int) -> BinaryIO:
    try:
        return cast(BinaryIO, os.fdopen(descriptor, "r+b", buffering=0))
    except Exception:
        os.close(descriptor)
        raise


def _open_windows_lock_file(path: Path) -> BinaryIO:
    handle = _windows_create_lock_handle(path)
    try:
        api = importlib.import_module("msvcrt")
        descriptor = api.open_osfhandle(handle, os.O_RDWR | os.O_BINARY)
    except Exception:
        _windows_close_handle(handle)
        raise
    return _binary_file_from_descriptor(descriptor)


def _open_posix_lock_file(path: Path) -> BinaryIO:
    flags = (
        os.O_RDWR
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        descriptor = os.open(path, flags | os.O_CREAT | os.O_EXCL, stat.S_IRUSR | stat.S_IWUSR)
    except FileExistsError:
        descriptor = os.open(path, flags)
    return _binary_file_from_descriptor(descriptor)


def _open_operator_lock(path: Path) -> BinaryIO:
    if os.name == "nt":
        return _open_windows_lock_file(path)
    return _open_posix_lock_file(path)


def _acquire_advisory_lock(handle: BinaryIO) -> None:
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()
        os.fsync(handle.fileno())
    handle.seek(0)
    if os.name == "nt":
        api = importlib.import_module("msvcrt")
        api.locking(handle.fileno(), api.LK_NBLCK, 1)
        return
    api = importlib.import_module("fcntl")
    api.flock(handle.fileno(), api.LOCK_EX | api.LOCK_NB)


def _release_advisory_lock(handle: BinaryIO) -> None:
    try:
        handle.seek(0)
        if os.name == "nt":
            api = importlib.import_module("msvcrt")
            api.locking(handle.fileno(), api.LK_UNLCK, 1)
            return
        api = importlib.import_module("fcntl")
        api.flock(handle.fileno(), api.LOCK_UN)
    except OSError:
        # Closing the descriptor below is the final, process-owned release boundary.
        return


def _fsync_directory(root: Path) -> None:
    if os.name == "nt":
        return
    directory_descriptor = os.open(root, os.O_RDONLY)
    try:
        os.fsync(directory_descriptor)
    finally:
        os.close(directory_descriptor)


def _open_package(root: Path, manifest_sha256: str) -> VerifiedStagingGenerationV1:
    try:
        return open_staging_generation(_package_directory(root, manifest_sha256), manifest_sha256)
    except Exception:
        raise _fail() from None


@contextmanager
def _operator_lock(root: Path) -> Iterator[None]:
    path = root / _LOCK_FILENAME
    handle: BinaryIO | None = None
    acquired = False
    failed = False
    try:
        handle = _open_operator_lock(path)
        identity = _lock_file_identity(path, handle)
        _acquire_advisory_lock(handle)
        acquired = True
        if _lock_file_identity(path, handle) != identity:
            raise OSError
        yield
    except StagingActivationError:
        raise
    except Exception:
        failed = True
    finally:
        if acquired and handle is not None:
            _release_advisory_lock(handle)
        if handle is not None:
            handle.close()
    if failed:
        raise _fail() from None


def _recover_installed_pointer(
    root: Path,
    raw: bytes,
    digest: str,
    *,
    directory_synced: bool,
) -> str:
    try:
        if not directory_synced:
            _fsync_directory(root)
        _pointer, observed = _read_pointer(root, digest)
        if observed != raw:
            raise _ambiguous()
        return digest
    except Exception:
        raise _ambiguous() from None


def _atomic_write_pointer(root: Path, raw: bytes) -> str:
    digest = hashlib.sha256(raw).hexdigest()
    descriptor, temporary_name = tempfile.mkstemp(prefix=_TEMP_PREFIX, dir=root)
    temporary = Path(temporary_name)
    replaced = False
    directory_synced = False
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, root / ACTIVATION_FILENAME)
        replaced = True
        _fsync_directory(root)
        directory_synced = True
        _pointer, observed = _read_pointer(root, digest)
        if observed != raw:
            raise _fail()
        return digest
    except Exception:
        if not replaced:
            raise _fail() from None
        return _recover_installed_pointer(
            root,
            raw,
            digest,
            directory_synced=directory_synced,
        )
    finally:
        if not replaced:
            _best_effort_unlink(temporary)


def _new_active(
    generation: VerifiedStagingGenerationV1,
    pointer: _ActivationPointer,
    activation_sha256: str,
) -> ActiveStagingGenerationV1:
    active = object.__new__(ActiveStagingGenerationV1)
    object.__setattr__(active, "generation", generation)
    object.__setattr__(active, "current_manifest_sha256", pointer.current_manifest_sha256)
    object.__setattr__(active, "previous_manifest_sha256", pointer.previous_manifest_sha256)
    object.__setattr__(active, "activation_sha256", activation_sha256)
    return active


def load_active_staging_generation(
    root_directory: Path,
    expected_activation_sha256: str,
) -> ActiveStagingGenerationV1:
    """Load the exact active package selected by an externally pinned pointer."""

    try:
        root = _validated_root(root_directory)
        pointer, raw = _read_pointer(root, expected_activation_sha256)
        generation = _open_package(root, pointer.current_manifest_sha256)
        reread, reread_raw = _read_pointer(root, expected_activation_sha256)
        if reread != pointer or reread_raw != raw:
            raise _fail()
        return _new_active(generation, pointer, expected_activation_sha256)
    except Exception:
        rejection_message = _ERROR
    raise StagingActivationError(rejection_message) from None


def promote_staging_generation(
    root_directory: Path,
    candidate_manifest_sha256: str,
    expected_activation_sha256: str,
) -> str:
    """Verify and atomically promote one immutable generation package."""

    try:
        root = _validated_root(root_directory)
        candidate = _sha256(candidate_manifest_sha256)
        expected = _sha256(expected_activation_sha256)
        with _operator_lock(root):
            current, raw = _read_expected_state(root, expected, allow_absent=True)
            _open_package(root, candidate)
            if current is None:
                replacement = _ActivationPointer(candidate, None)
            else:
                _open_package(root, current.current_manifest_sha256)
                if candidate == current.current_manifest_sha256:
                    raise _fail()
                replacement = _ActivationPointer(candidate, current.current_manifest_sha256)
            reread, reread_raw = _read_expected_state(root, expected, allow_absent=True)
            if reread != current or reread_raw != raw:
                raise _fail()
            return _atomic_write_pointer(root, _canonical_pointer_bytes(replacement))
    except StagingActivationOutcomeAmbiguous:
        ambiguous = True
    except Exception:
        rejection_message = _ERROR
        ambiguous = False
    if ambiguous:
        raise _ambiguous() from None
    raise StagingActivationError(rejection_message) from None


def rollback_staging_generation(
    root_directory: Path,
    expected_activation_sha256: str,
) -> str:
    """Verify the retained previous package and atomically exchange it with current."""

    try:
        root = _validated_root(root_directory)
        expected = _sha256(expected_activation_sha256)
        with _operator_lock(root):
            current, raw = _read_expected_state(root, expected, allow_absent=False)
            if current is None or current.previous_manifest_sha256 is None:
                raise _fail()
            _open_package(root, current.current_manifest_sha256)
            _open_package(root, current.previous_manifest_sha256)
            reread, reread_raw = _read_expected_state(root, expected, allow_absent=False)
            if reread != current or reread_raw != raw:
                raise _fail()
            replacement = _ActivationPointer(
                current.previous_manifest_sha256, current.current_manifest_sha256
            )
            return _atomic_write_pointer(root, _canonical_pointer_bytes(replacement))
    except StagingActivationOutcomeAmbiguous:
        ambiguous = True
    except Exception:
        rejection_message = _ERROR
        ambiguous = False
    if ambiguous:
        raise _ambiguous() from None
    raise StagingActivationError(rejection_message) from None


__all__ = (
    "ABSENT_ACTIVATION_SHA256",
    "ACTIVATION_FILENAME",
    "ACTIVATION_SCHEMA_VERSION",
    "GENERATIONS_DIRECTORY",
    "ActiveStagingGenerationV1",
    "StagingActivationError",
    "StagingActivationOutcomeAmbiguous",
    "load_active_staging_generation",
    "promote_staging_generation",
    "rollback_staging_generation",
)
