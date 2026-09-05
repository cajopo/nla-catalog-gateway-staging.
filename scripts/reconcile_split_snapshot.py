#!/usr/bin/env python3
"""Reconcile two downloaded Shopify Bulk JSONL parts without network access."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from collections.abc import Sequence
from contextlib import ExitStack
from ctypes import wintypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO, NoReturn, cast

from nla_catalog_gateway import bulk
from nla_catalog_gateway import reconciliation as reconciliation_model
from nla_catalog_gateway.reconciliation import (
    BulkOperationTerminalEvidenceV1,
    ReconciledCatalogGenerationV1,
    ReconciliationExpectationV1,
    SnapshotPart,
    SnapshotPartInputV1,
    SnapshotPartManifestV1,
    create_snapshot_part_manifest,
    reconcile_snapshot_parts,
)
from nla_catalog_gateway.taxonomy import load_taxonomy

CONTROL_DOCUMENT_MAX_BYTES = 64 * 1024
SUMMARY_SCHEMA_VERSION = 1
TAXONOMY_REPORT_SCHEMA_VERSION = 1

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_CONCRETE_PATH_TYPE = type(Path())
_REPARSE_POINT_ATTRIBUTE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_WINDOWS_HANDLE_API_AVAILABLE = sys.platform == "win32"
_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_DELETE_ACCESS = 0x00010000
_FILE_LIST_DIRECTORY = 0x00000001
_FILE_READ_ATTRIBUTES = 0x00000080
_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_FILE_SHARE_DELETE = 0x00000004
_CREATE_NEW = 1
_OPEN_EXISTING = 3
_FILE_ATTRIBUTE_NORMAL = 0x00000080
_FILE_FLAG_SEQUENTIAL_SCAN = 0x08000000
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_FILE_DISPOSITION_INFO_CLASS = 4
_FILE_STREAM_INFO_CLASS = 7
_DRIVE_FIXED = 3
_VOLUME_NAME_GUID = 0x1
_VOLUME_NAME_BUFFER_CHARS = 32_768
_STREAM_INFO_INITIAL_BYTES = 4_096
_STREAM_INFO_MAX_BYTES = 1024 * 1024
_ERROR_INSUFFICIENT_BUFFER = 122
_ERROR_MORE_DATA = 234
_ERROR_HANDLE_EOF = 38
_FINAL_VOLUME_GUID_PATTERN = re.compile(
    r"^\\\\\?\\(Volume\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
    r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\})\\(.*)$"
)
_O_BINARY = getattr(os, "O_BINARY", 0)
_WIN32_LAST_ERROR = getattr(ctypes, "get_last_error", lambda: 0)
_INVALID_NATIVE_HANDLE = ctypes.c_void_p(-1).value
_OUTPUT_FILENAMES = frozenset(
    {
        "catalog-records.v1.jsonl",
        "dataset-manifest.v1.json",
        "products-part-manifest.v1.json",
        "reconciliation-summary.v1.json",
        "source-manifest.v2.json",
        "taxonomy-report.v1.json",
        "variants-part-manifest.v1.json",
    }
)
_EXPECTATION_KEYS = {
    "apiVersion",
    "expectedActiveOnlineStorePublishedProductCount",
    "onlineStorePublicationGid",
    "productCount",
    "schemaVersion",
    "shopDomain",
    "snapshotSetId",
    "sourceCodeSha",
    "variantCount",
}
_TERMINAL_KEYS = {
    "completedAt",
    "createdAt",
    "errorCode",
    "fileSize",
    "objectCount",
    "operationId",
    "operationType",
    "partialDataUrlPresent",
    "query",
    "rootObjectCount",
    "schemaVersion",
    "status",
    "urlPresent",
}


class ReconciliationCliError(ValueError):
    """Raised when local CLI inputs or output boundaries are unsafe."""


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        del message
        raise ReconciliationCliError("command arguments are invalid")


@dataclass(frozen=True, slots=True)
class _FileIdentity:
    device: int
    inode: int


@dataclass(frozen=True, slots=True)
class _InputFileState:
    identity: _FileIdentity
    byte_count: int
    modified_ns: int


@dataclass(frozen=True, slots=True)
class _CanonicalHandlePath:
    volume_guid: str
    components: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _PinnedInputFile:
    path: Path
    state: _InputFileState
    handle: BinaryIO
    context: str
    frozen_bytes: bytes | None = field(default=None, repr=False, compare=False)
    canonical_path: _CanonicalHandlePath | None = field(default=None, repr=False)


@dataclass(slots=True)
class _CreatedArtifact:
    path: Path
    identity: _FileIdentity
    handle: BinaryIO | None = field(default=None, repr=False, compare=False)
    expected_sha256: str | None = None
    expected_byte_count: int | None = None
    delete_capable: bool = False


@dataclass(slots=True)
class _DirectoryLease:
    path: Path
    identity: _FileIdentity
    native_handle: int
    parent_native_handle: int
    closed: bool = False
    canonical_path: _CanonicalHandlePath | None = field(default=None, repr=False)
    parent_canonical_path: _CanonicalHandlePath | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class _ArtifactEvidence:
    filename: str
    sha256: str
    byte_count: int
    record_count: int

    def as_dict(self) -> dict[str, object]:
        return {
            "bytes": self.byte_count,
            "filename": self.filename,
            "recordCount": self.record_count,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class _TerminalQueryAuditEvidence:
    part: SnapshotPart
    approved_query_sha256: str
    raw_terminal_query_sha256: str
    transport: str

    def as_dict(self) -> dict[str, str]:
        return {
            "approvedQuerySha256": self.approved_query_sha256,
            "part": self.part.value,
            "rawTerminalQuerySha256": self.raw_terminal_query_sha256,
            "transport": self.transport,
        }


def _canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (RecursionError, TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ReconciliationCliError("generated evidence is not canonical JSON") from exc


def _windows_kernel32() -> Any:
    if not _WINDOWS_HANDLE_API_AVAILABLE:
        raise ReconciliationCliError("strong filesystem handle guarantees are unavailable")
    try:
        return ctypes.WinDLL("kernel32", use_last_error=True)
    except (AttributeError, OSError) as exc:
        raise ReconciliationCliError("strong filesystem handle guarantees are unavailable") from exc


def _windows_msvcrt() -> Any:
    if not _WINDOWS_HANDLE_API_AVAILABLE:
        raise ReconciliationCliError("strong filesystem handle guarantees are unavailable")
    try:
        import msvcrt
    except ImportError as exc:
        raise ReconciliationCliError("strong filesystem handle guarantees are unavailable") from exc
    return msvcrt


def _require_local_ntfs(path: Path, context: str) -> None:
    kernel32 = _windows_kernel32()
    volume_path = ctypes.create_unicode_buffer(_VOLUME_NAME_BUFFER_CHARS)
    get_volume_path = kernel32.GetVolumePathNameW
    get_volume_path.argtypes = (wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD)
    get_volume_path.restype = wintypes.BOOL
    if not get_volume_path(os.fspath(path), volume_path, len(volume_path)):
        raise ReconciliationCliError(f"{context} filesystem boundary cannot be verified")

    get_drive_type = kernel32.GetDriveTypeW
    get_drive_type.argtypes = (wintypes.LPCWSTR,)
    get_drive_type.restype = wintypes.UINT
    if get_drive_type(volume_path.value) != _DRIVE_FIXED:
        raise ReconciliationCliError(f"{context} must be on a local fixed NTFS volume")

    filesystem_name = ctypes.create_unicode_buffer(_VOLUME_NAME_BUFFER_CHARS)
    get_volume_information = kernel32.GetVolumeInformationW
    get_volume_information.argtypes = (
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.LPDWORD,
        wintypes.LPDWORD,
        wintypes.LPDWORD,
        wintypes.LPWSTR,
        wintypes.DWORD,
    )
    get_volume_information.restype = wintypes.BOOL
    if not get_volume_information(
        volume_path.value,
        None,
        0,
        None,
        None,
        None,
        filesystem_name,
        len(filesystem_name),
    ):
        raise ReconciliationCliError(f"{context} filesystem boundary cannot be verified")
    if filesystem_name.value.upper() != "NTFS":
        raise ReconciliationCliError(f"{context} must be on a local fixed NTFS volume")


def _native_create_file(
    path: Path,
    *,
    access: int,
    share: int,
    creation: int,
    flags: int,
    context: str,
) -> int:
    kernel32 = _windows_kernel32()
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    create_file.restype = wintypes.HANDLE
    raw_handle = create_file(os.fspath(path), access, share, None, creation, flags, None)
    if raw_handle == _INVALID_NATIVE_HANDLE:
        raise ReconciliationCliError(f"{context} cannot be locked safely")
    return int(raw_handle)


def _native_close(raw_handle: int) -> None:
    kernel32 = _windows_kernel32()
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL
    if not close_handle(raw_handle):
        raise ReconciliationCliError("filesystem handle cannot be closed safely")


def _native_binary_file(
    path: Path,
    *,
    writable: bool,
    create: bool,
    context: str,
) -> BinaryIO:
    msvcrt = _windows_msvcrt()
    access = _GENERIC_READ | (_GENERIC_WRITE if writable else 0)
    share = _FILE_SHARE_READ | (_FILE_SHARE_DELETE if writable else 0)
    flags = _FILE_ATTRIBUTE_NORMAL | _FILE_FLAG_OPEN_REPARSE_POINT
    if not writable:
        flags |= _FILE_FLAG_SEQUENTIAL_SCAN
    raw_handle = _native_create_file(
        path,
        access=access,
        share=share,
        creation=_CREATE_NEW if create else _OPEN_EXISTING,
        flags=flags,
        context=context,
    )
    descriptor: int | None = None
    try:
        descriptor = msvcrt.open_osfhandle(
            raw_handle,
            _O_BINARY | (os.O_RDWR if writable else os.O_RDONLY),
        )
        raw_handle = 0
        return os.fdopen(descriptor, "r+b" if writable else "rb", buffering=0)
    except (AttributeError, OSError, ValueError) as exc:
        if descriptor is not None:
            os.close(descriptor)
        else:
            _native_close(raw_handle)
        raise ReconciliationCliError(f"{context} cannot be bound to a binary handle") from exc


def _native_sealed_file(path: Path, context: str) -> BinaryIO:
    msvcrt = _windows_msvcrt()
    raw_handle = _native_create_file(
        path,
        access=_GENERIC_READ | _DELETE_ACCESS,
        share=_FILE_SHARE_READ,
        creation=_OPEN_EXISTING,
        flags=_FILE_ATTRIBUTE_NORMAL | _FILE_FLAG_OPEN_REPARSE_POINT | _FILE_FLAG_SEQUENTIAL_SCAN,
        context=context,
    )
    descriptor: int | None = None
    try:
        descriptor = msvcrt.open_osfhandle(raw_handle, _O_BINARY | os.O_RDONLY)
        raw_handle = 0
        return os.fdopen(descriptor, "rb", buffering=0)
    except (OSError, ValueError) as exc:
        if descriptor is not None:
            os.close(descriptor)
        else:
            _native_close(raw_handle)
        raise ReconciliationCliError(f"{context} cannot be sealed to an exact handle") from exc


def _native_os_handle(handle: BinaryIO, context: str) -> int:
    try:
        msvcrt = _windows_msvcrt()
        return int(msvcrt.get_osfhandle(handle.fileno()))
    except (AttributeError, OSError, ValueError) as exc:
        raise ReconciliationCliError(f"{context} native handle is unavailable") from exc


def _parse_canonical_handle_path(value: str, context: str) -> _CanonicalHandlePath:
    match = _FINAL_VOLUME_GUID_PATTERN.fullmatch(value)
    if match is None or "/" in value or "\x00" in value:
        raise ReconciliationCliError(f"{context} canonical path cannot be verified")
    volume_guid, remainder = match.groups()
    components = () if not remainder else tuple(remainder.split("\\"))
    if any(
        not component
        or component in {".", ".."}
        or ":" in component
        or component.rstrip(" .") != component
        for component in components
    ):
        raise ReconciliationCliError(f"{context} canonical path cannot be verified")
    return _CanonicalHandlePath(
        volume_guid=volume_guid.casefold(),
        components=tuple(component.casefold() for component in components),
    )


def _native_handle_canonical_path(raw_handle: int, context: str) -> _CanonicalHandlePath:
    kernel32 = _windows_kernel32()
    get_final_path = kernel32.GetFinalPathNameByHandleW
    get_final_path.argtypes = (
        wintypes.HANDLE,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    )
    get_final_path.restype = wintypes.DWORD
    buffer = ctypes.create_unicode_buffer(_VOLUME_NAME_BUFFER_CHARS)
    result = int(
        get_final_path(
            raw_handle,
            buffer,
            len(buffer),
            _VOLUME_NAME_GUID,
        )
    )
    if result == 0 or result >= len(buffer):
        raise ReconciliationCliError(f"{context} canonical path cannot be verified")
    return _parse_canonical_handle_path(buffer.value, context)


def _native_file_streams(
    raw_handle: int,
    context: str,
    *,
    directory: bool = False,
) -> tuple[tuple[str, int], ...]:
    class _FileStreamInfo(ctypes.Structure):
        _fields_ = (
            ("next_entry_offset", wintypes.DWORD),
            ("stream_name_length", wintypes.DWORD),
            ("stream_size", ctypes.c_longlong),
            ("stream_allocation_size", ctypes.c_longlong),
        )

    kernel32 = _windows_kernel32()
    get_information = kernel32.GetFileInformationByHandleEx
    get_information.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    )
    get_information.restype = wintypes.BOOL
    size = _STREAM_INFO_INITIAL_BYTES
    while True:
        storage = ctypes.create_string_buffer(size + 7)
        aligned_address = (ctypes.addressof(storage) + 7) & ~7
        buffer = (ctypes.c_ubyte * size).from_address(aligned_address)
        if get_information(raw_handle, _FILE_STREAM_INFO_CLASS, buffer, size):
            break
        error_code = _WIN32_LAST_ERROR()
        if directory and error_code == _ERROR_HANDLE_EOF:
            return ()
        if error_code not in {_ERROR_INSUFFICIENT_BUFFER, _ERROR_MORE_DATA}:
            raise ReconciliationCliError(f"{context} NTFS streams cannot be verified")
        size *= 2
        if size > _STREAM_INFO_MAX_BYTES:
            raise ReconciliationCliError(f"{context} NTFS stream metadata exceeds its bound")

    header_size = ctypes.sizeof(_FileStreamInfo)
    offset = 0
    streams: list[tuple[str, int]] = []
    seen_names: set[str] = set()
    while True:
        if offset > size - header_size:
            raise ReconciliationCliError(f"{context} NTFS stream metadata is invalid")
        header = _FileStreamInfo.from_buffer_copy(buffer, offset)
        name_length = int(header.stream_name_length)
        name_start = offset + header_size
        name_end = name_start + name_length
        if name_length == 0 or name_length % 2 or name_end > size:
            raise ReconciliationCliError(f"{context} NTFS stream metadata is invalid")
        try:
            name = bytes(buffer[name_start:name_end]).decode("utf-16-le", errors="strict")
        except UnicodeDecodeError as exc:
            raise ReconciliationCliError(f"{context} NTFS stream metadata is invalid") from exc
        folded_name = name.casefold()
        if (
            "\x00" in name
            or folded_name in seen_names
            or int(header.stream_size) < 0
            or int(header.stream_allocation_size) < 0
        ):
            raise ReconciliationCliError(f"{context} NTFS stream metadata is invalid")
        seen_names.add(folded_name)
        streams.append((name, int(header.stream_size)))
        next_offset = int(header.next_entry_offset)
        if next_offset == 0:
            break
        if (
            next_offset % 8
            or next_offset < header_size + name_length
            or next_offset > size - offset
        ):
            raise ReconciliationCliError(f"{context} NTFS stream metadata is invalid")
        offset += next_offset
    return tuple(streams)


def _require_unnamed_data_stream(raw_handle: int, expected_size: int, context: str) -> None:
    streams = _native_file_streams(raw_handle, context)
    if streams != (("::$DATA", expected_size),):
        raise ReconciliationCliError(f"{context} must contain only its unnamed data stream")


def _require_no_directory_streams(raw_handle: int, context: str) -> None:
    if _native_file_streams(raw_handle, context, directory=True):
        raise ReconciliationCliError(f"{context} must not contain named data streams")


def _canonical_child(parent: _CanonicalHandlePath, name: str) -> _CanonicalHandlePath:
    if (
        not name
        or name in {".", ".."}
        or "\\" in name
        or "/" in name
        or ":" in name
        or name.rstrip(" .") != name
    ):
        raise ReconciliationCliError("canonical child name is unsafe")
    return _CanonicalHandlePath(parent.volume_guid, (*parent.components, name.casefold()))


def _canonical_is_within(
    candidate: _CanonicalHandlePath,
    parent: _CanonicalHandlePath,
) -> bool:
    return (
        candidate.volume_guid == parent.volume_guid
        and len(candidate.components) >= len(parent.components)
        and candidate.components[: len(parent.components)] == parent.components
    )


def _native_path_canonical_path(
    path: Path,
    context: str,
    *,
    directory: bool,
) -> _CanonicalHandlePath:
    raw_handle = _native_create_file(
        path,
        access=_FILE_READ_ATTRIBUTES,
        share=_FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE,
        creation=_OPEN_EXISTING,
        flags=(
            _FILE_FLAG_OPEN_REPARSE_POINT
            | (_FILE_FLAG_BACKUP_SEMANTICS if directory else _FILE_ATTRIBUTE_NORMAL)
        ),
        context=context,
    )
    try:
        return _native_handle_canonical_path(raw_handle, context)
    finally:
        _native_close(raw_handle)


def _repository_canonical_path() -> _CanonicalHandlePath:
    return _native_path_canonical_path(
        REPOSITORY_ROOT,
        "repository root",
        directory=True,
    )


def _require_external_canonical_path(
    canonical_path: _CanonicalHandlePath,
    context: str,
) -> None:
    if _canonical_is_within(canonical_path, _repository_canonical_path()):
        raise ReconciliationCliError(f"{context} must be external to the repository")


def _native_reopen_for_delete(handle: BinaryIO, context: str) -> int:
    kernel32 = _windows_kernel32()
    reopen_file = kernel32.ReOpenFile
    reopen_file.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
    )
    reopen_file.restype = wintypes.HANDLE
    raw_handle = reopen_file(
        _native_os_handle(handle, context),
        _DELETE_ACCESS | _FILE_READ_ATTRIBUTES,
        _FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE,
        0,
    )
    if raw_handle == _INVALID_NATIVE_HANDLE:
        error_code = _WIN32_LAST_ERROR()
        raise ReconciliationCliError(
            f"{context} cannot acquire exact delete access (win32={error_code})"
        )
    return int(raw_handle)


def _native_set_delete(raw_handle: int, delete: bool, context: str) -> None:
    class _FileDispositionInfo(ctypes.Structure):
        _fields_ = (("delete_file", ctypes.c_ubyte),)

    kernel32 = _windows_kernel32()
    set_information = kernel32.SetFileInformationByHandle
    set_information.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    )
    set_information.restype = wintypes.BOOL
    disposition = _FileDispositionInfo(delete)
    if not set_information(
        raw_handle,
        _FILE_DISPOSITION_INFO_CLASS,
        ctypes.byref(disposition),
        ctypes.sizeof(disposition),
    ):
        action = "deleted" if delete else "preserved"
        raise ReconciliationCliError(f"{context} cannot be {action} by exact handle")


def _native_mark_delete(raw_handle: int, context: str) -> None:
    _native_set_delete(raw_handle, True, context)


def _native_cancel_delete(raw_handle: int, context: str) -> None:
    _native_set_delete(raw_handle, False, context)


def _open_directory_lease(path: Path, identity: _FileIdentity) -> _DirectoryLease:
    parent_handle = _native_create_file(
        path.parent,
        access=_FILE_LIST_DIRECTORY | _FILE_READ_ATTRIBUTES,
        share=_FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE,
        creation=_OPEN_EXISTING,
        flags=_FILE_FLAG_BACKUP_SEMANTICS | _FILE_FLAG_OPEN_REPARSE_POINT,
        context="output parent directory",
    )
    try:
        raw_handle = _native_create_file(
            path,
            access=_DELETE_ACCESS | _FILE_READ_ATTRIBUTES,
            share=_FILE_SHARE_READ | _FILE_SHARE_WRITE,
            creation=_OPEN_EXISTING,
            flags=_FILE_FLAG_BACKUP_SEMANTICS | _FILE_FLAG_OPEN_REPARSE_POINT,
            context="output staging directory",
        )
    except BaseException:
        _native_close(parent_handle)
        raise
    try:
        parent_canonical_path = _native_handle_canonical_path(
            parent_handle,
            "output parent directory",
        )
        _require_external_canonical_path(parent_canonical_path, "output directory")
        canonical_path = _native_handle_canonical_path(raw_handle, "output staging directory")
        if canonical_path != _canonical_child(parent_canonical_path, path.name):
            raise ReconciliationCliError("output staging directory canonical path is inconsistent")
        lease = _DirectoryLease(
            path=path,
            identity=identity,
            native_handle=raw_handle,
            parent_native_handle=parent_handle,
            canonical_path=canonical_path,
            parent_canonical_path=parent_canonical_path,
        )
        _require_no_directory_streams(raw_handle, "output staging directory")
        _require_directory_identity(path, identity)
    except BaseException:
        _native_close(raw_handle)
        _native_close(parent_handle)
        raise
    return lease


def _verify_directory_lease_canonical_path(lease: _DirectoryLease) -> None:
    if lease.closed or lease.canonical_path is None or lease.parent_canonical_path is None:
        raise ReconciliationCliError("output directory canonical path cannot be verified")
    parent = _native_handle_canonical_path(
        lease.parent_native_handle,
        "output parent directory",
    )
    current = _native_handle_canonical_path(lease.native_handle, "output directory")
    if parent != lease.parent_canonical_path or current != lease.canonical_path:
        raise ReconciliationCliError("output directory canonical path changed")
    _require_external_canonical_path(parent, "output directory")
    _require_no_directory_streams(lease.native_handle, "output directory")


def _verify_output_shape(lease: _DirectoryLease) -> None:
    if lease.closed:
        raise ReconciliationCliError("output directory shape cannot be verified safely")
    _verify_directory_lease_canonical_path(lease)
    _require_directory_identity(lease.path, lease.identity)
    try:
        names = tuple(entry.name for entry in os.scandir(lease.path))
    except OSError as exc:
        raise ReconciliationCliError("output directory shape cannot be verified safely") from exc
    if len(names) != len(_OUTPUT_FILENAMES) or frozenset(names) != _OUTPUT_FILENAMES:
        raise ReconciliationCliError("output directory shape is not exact")
    _require_directory_identity(lease.path, lease.identity)
    _verify_directory_lease_canonical_path(lease)


def _rename_directory_by_handle(lease: _DirectoryLease, target: Path) -> None:
    class _FileRenameInfo(ctypes.Structure):
        _fields_ = (
            ("replace_if_exists", ctypes.c_ubyte),
            ("root_directory", wintypes.HANDLE),
            ("file_name_length", wintypes.DWORD),
            ("file_name", wintypes.WCHAR * 1),
        )

    if lease.closed:
        raise ReconciliationCliError("output directory lease is closed")
    if target.parent != lease.path.parent:
        raise ReconciliationCliError("output directory rename must remain in its parent")
    _verify_directory_lease_canonical_path(lease)
    parent_canonical_path = cast(_CanonicalHandlePath, lease.parent_canonical_path)
    expected_canonical_path = _canonical_child(parent_canonical_path, target.name)
    encoded_target = os.fspath(target).encode("utf-16-le")
    offset = _FileRenameInfo.file_name.offset
    buffer_size = ctypes.sizeof(_FileRenameInfo) + len(encoded_target)
    buffer = ctypes.create_string_buffer(buffer_size)
    rename = _FileRenameInfo.from_buffer(buffer)
    rename.replace_if_exists = False
    rename.root_directory = None
    rename.file_name_length = len(encoded_target)
    ctypes.memmove(ctypes.addressof(buffer) + offset, encoded_target, len(encoded_target))
    kernel32 = _windows_kernel32()
    set_information = kernel32.SetFileInformationByHandle
    set_information.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    )
    set_information.restype = wintypes.BOOL
    if not set_information(
        lease.native_handle,
        3,
        ctypes.byref(buffer),
        buffer_size,
    ):
        error_code = _WIN32_LAST_ERROR()
        raise ReconciliationCliError(
            f"output directory cannot be published safely (win32={error_code})"
        )
    lease.path = target
    lease.canonical_path = expected_canonical_path
    _verify_directory_lease_canonical_path(lease)


def _delete_directory_by_handle(lease: _DirectoryLease) -> None:
    if lease.closed:
        return
    try:
        _native_mark_delete(lease.native_handle, "output directory")
        try:
            _require_no_directory_streams(lease.native_handle, "output directory")
        except BaseException as exc:
            try:
                _native_cancel_delete(lease.native_handle, "output directory")
            except ReconciliationCliError as cancel_error:
                raise cancel_error from exc
            raise
    except BaseException:
        _native_close(lease.native_handle)
        _native_close(lease.parent_native_handle)
        lease.closed = True
        raise
    _native_close(lease.native_handle)
    _native_close(lease.parent_native_handle)
    lease.closed = True


def _close_directory_lease(lease: _DirectoryLease) -> None:
    if lease.closed:
        return
    _verify_output_shape(lease)
    _native_close(lease.native_handle)
    _native_close(lease.parent_native_handle)
    lease.closed = True


def _path_has_alias(path: Path) -> bool:
    current = path
    while True:
        try:
            facts = current.lstat()
            attributes = getattr(facts, "st_file_attributes", 0)
            if (
                attributes & _REPARSE_POINT_ATTRIBUTE
                or current.is_symlink()
                or current.is_junction()
            ):
                return True
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise ReconciliationCliError("filesystem alias state cannot be verified") from exc
        if current.parent == current:
            return False
        current = current.parent


def _contains_parent_reference(path: Path) -> bool:
    return any(part == ".." for part in path.parts)


def _has_unsafe_path_component(path: Path) -> bool:
    return any(
        part != path.anchor and (":" in part or (part and part.rstrip(" .") != part))
        for part in path.parts
    )


def _require_supported_path_namespace(path: Path, context: str) -> None:
    raw = os.fspath(path)
    folded = raw.casefold()
    if folded.startswith("\\\\?\\"):
        supported_drive = re.match(r"^\\\\\?\\[a-z]:\\", raw, re.IGNORECASE)
        supported_volume = re.match(
            r"^\\\\\?\\Volume\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-"
            r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}\\",
            raw,
        )
        if supported_drive is None and supported_volume is None:
            raise ReconciliationCliError(f"{context} uses an unsupported filesystem namespace")
        return
    if folded.startswith("\\\\.\\") or folded.startswith("\\??\\") or folded.startswith("\\\\"):
        raise ReconciliationCliError(f"{context} uses an unsupported filesystem namespace")


def _regular_file(
    value: object,
    context: str,
    *,
    external: bool,
) -> tuple[Path, _InputFileState]:
    if type(value) is not _CONCRETE_PATH_TYPE:
        raise ReconciliationCliError(f"{context} must be a concrete filesystem path")
    path = value
    _require_supported_path_namespace(path, context)
    if (
        not path.is_absolute()
        or _contains_parent_reference(path)
        or _has_unsafe_path_component(path)
    ):
        raise ReconciliationCliError(f"{context} must be an absolute normalized path")
    if _path_has_alias(path):
        raise ReconciliationCliError(f"{context} must not use filesystem aliases")
    try:
        resolved = path.resolve(strict=True)
        facts = resolved.lstat()
    except (OSError, RuntimeError) as exc:
        raise ReconciliationCliError(f"{context} is unavailable") from exc
    if not stat.S_ISREG(facts.st_mode) or facts.st_nlink != 1:
        raise ReconciliationCliError(f"{context} must be one regular, unaliased file")
    _require_local_ntfs(resolved, context)
    canonical_path = _native_path_canonical_path(resolved, context, directory=False)
    if external:
        _require_external_canonical_path(canonical_path, context)
    return resolved, _InputFileState(
        identity=_FileIdentity(facts.st_dev, facts.st_ino),
        byte_count=facts.st_size,
        modified_ns=facts.st_mtime_ns,
    )


def _input_state(path: Path, context: str) -> _InputFileState:
    if _path_has_alias(path):
        raise ReconciliationCliError(f"{context} must not use filesystem aliases")
    try:
        facts = path.lstat()
    except OSError as exc:
        raise ReconciliationCliError(f"{context} identity cannot be verified") from exc
    if not stat.S_ISREG(facts.st_mode) or facts.st_nlink != 1:
        raise ReconciliationCliError(f"{context} must be one regular, unaliased file")
    return _InputFileState(
        identity=_FileIdentity(facts.st_dev, facts.st_ino),
        byte_count=facts.st_size,
        modified_ns=facts.st_mtime_ns,
    )


def _handle_input_state(handle: BinaryIO, context: str) -> _InputFileState:
    try:
        facts = os.fstat(handle.fileno())
    except (OSError, ValueError) as exc:
        raise ReconciliationCliError(f"{context} handle identity cannot be verified") from exc
    if not stat.S_ISREG(facts.st_mode) or facts.st_nlink != 1:
        raise ReconciliationCliError(f"{context} handle must remain a single regular file")
    return _InputFileState(
        identity=_FileIdentity(facts.st_dev, facts.st_ino),
        byte_count=facts.st_size,
        modified_ns=facts.st_mtime_ns,
    )


def _verify_pinned_input(pinned: _PinnedInputFile) -> None:
    current = _handle_input_state(pinned.handle, pinned.context)
    if current != pinned.state:
        raise ReconciliationCliError(f"{pinned.context} identity changed")
    raw_handle = _native_os_handle(pinned.handle, pinned.context)
    _require_unnamed_data_stream(raw_handle, current.byte_count, pinned.context)
    if (
        pinned.canonical_path is not None
        and _native_handle_canonical_path(raw_handle, pinned.context) != pinned.canonical_path
    ):
        raise ReconciliationCliError(f"{pinned.context} canonical path changed")


def _pin_regular_file(
    path: Path,
    state: _InputFileState,
    context: str,
    stack: ExitStack,
    *,
    freeze_maximum: int | None = None,
    external: bool = False,
) -> _PinnedInputFile:
    try:
        handle = stack.enter_context(
            _native_binary_file(
                path,
                writable=False,
                create=False,
                context=context,
            )
        )
    except ReconciliationCliError:
        raise
    except OSError as exc:
        raise ReconciliationCliError(f"{context} cannot be opened safely") from exc
    raw_handle = _native_os_handle(handle, context)
    canonical_path = _native_handle_canonical_path(raw_handle, context)
    if external:
        _require_external_canonical_path(canonical_path, context)
    pinned = _PinnedInputFile(
        path=path,
        state=state,
        handle=handle,
        context=context,
        canonical_path=canonical_path,
    )
    _verify_pinned_input(pinned)
    if freeze_maximum is not None:
        if freeze_maximum < 1:
            raise ReconciliationCliError(f"{context} immutable byte bound is invalid")
        try:
            handle.seek(0)
            raw = handle.read(freeze_maximum + 1)
        except (OSError, ValueError) as exc:
            raise ReconciliationCliError(f"{context} cannot be frozen") from exc
        if len(raw) != state.byte_count:
            raise ReconciliationCliError(f"{context} immutable byte snapshot is incomplete")
        _verify_pinned_input(pinned)
        pinned = _PinnedInputFile(
            path=path,
            state=state,
            handle=handle,
            context=context,
            frozen_bytes=raw,
            canonical_path=canonical_path,
        )
    return pinned


def _read_pinned_bytes(
    pinned: _PinnedInputFile,
    *,
    maximum: int,
) -> bytes:
    _verify_pinned_input(pinned)
    raw = pinned.frozen_bytes
    if type(raw) is not bytes:
        raise ReconciliationCliError(f"{pinned.context} was not frozen at pin time")
    if len(raw) > maximum:
        raise ReconciliationCliError(f"{pinned.context} immutable byte snapshot exceeds its bound")
    return raw


def _load_control_document(source: Path | _PinnedInputFile, context: str) -> dict[str, Any]:
    if type(source) is _PinnedInputFile:
        raw = _read_pinned_bytes(source, maximum=CONTROL_DOCUMENT_MAX_BYTES)
    else:
        try:
            with source.open("rb") as handle:
                raw = handle.read(CONTROL_DOCUMENT_MAX_BYTES + 1)
        except OSError as exc:
            raise ReconciliationCliError(f"{context} cannot be read") from exc
    if not raw or len(raw) > CONTROL_DOCUMENT_MAX_BYTES:
        raise ReconciliationCliError(f"{context} violates the byte bound")
    try:
        value = bulk._strict_json(raw, context)
    except bulk.BulkContractError as exc:
        raise ReconciliationCliError(f"{context} is invalid") from exc
    if type(value) is not dict:
        raise ReconciliationCliError(f"{context} must be an object")
    return value


def _require_schema_version(payload: dict[str, Any], context: str) -> None:
    if type(payload["schemaVersion"]) is not int or payload["schemaVersion"] != 1:
        raise ReconciliationCliError(f"{context} schemaVersion must be integer 1")


def _load_expectation(source: Path | _PinnedInputFile) -> ReconciliationExpectationV1:
    payload = _load_control_document(source, "reconciliation expectation")
    try:
        bulk._exact_keys(payload, _EXPECTATION_KEYS, "reconciliation expectation")
    except bulk.BulkContractError as exc:
        raise ReconciliationCliError("reconciliation expectation has invalid fields") from exc
    _require_schema_version(payload, "reconciliation expectation")
    return ReconciliationExpectationV1(
        snapshot_set_id=payload["snapshotSetId"],
        shop_domain=payload["shopDomain"],
        api_version=payload["apiVersion"],
        online_store_publication_gid=payload["onlineStorePublicationGid"],
        source_code_sha=payload["sourceCodeSha"],
        product_count=payload["productCount"],
        variant_count=payload["variantCount"],
        expected_active_online_store_published_product_count=payload[
            "expectedActiveOnlineStorePublishedProductCount"
        ],
    )


def _load_terminal_evidence(
    source: Path | _PinnedInputFile, context: str
) -> BulkOperationTerminalEvidenceV1:
    payload = _load_control_document(source, context)
    try:
        bulk._exact_keys(payload, _TERMINAL_KEYS, context)
    except bulk.BulkContractError as exc:
        raise ReconciliationCliError(f"{context} has invalid fields") from exc
    _require_schema_version(payload, context)
    return BulkOperationTerminalEvidenceV1(
        operation_id=payload["operationId"],
        operation_type=payload["operationType"],
        status=payload["status"],
        error_code=payload["errorCode"],
        query=payload["query"],
        created_at=payload["createdAt"],
        completed_at=payload["completedAt"],
        file_size=payload["fileSize"],
        object_count=payload["objectCount"],
        root_object_count=payload["rootObjectCount"],
        url_present=payload["urlPresent"],
        partial_data_url_present=payload["partialDataUrlPresent"],
    )


def _terminal_query_audit(
    *,
    part: SnapshotPart,
    terminal: BulkOperationTerminalEvidenceV1,
    query: _PinnedInputFile,
) -> _TerminalQueryAuditEvidence:
    _verify_pinned_input(query)
    canonical_query = _read_pinned_bytes(
        query,
        maximum=reconciliation_model.MAX_BULK_QUERY_BYTES,
    )
    canonical_query = reconciliation_model._read_query_bytes(
        query.path,
        frozen=canonical_query,
    )
    _verify_pinned_input(query)
    transport = reconciliation_model._terminal_query_transport_mode(terminal.query, canonical_query)
    return _TerminalQueryAuditEvidence(
        part=part,
        approved_query_sha256=hashlib.sha256(canonical_query).hexdigest(),
        raw_terminal_query_sha256=hashlib.sha256(terminal.query.encode("utf-8")).hexdigest(),
        transport=transport,
    )


def _validated_output_directory(value: object) -> Path:
    if type(value) is not _CONCRETE_PATH_TYPE:
        raise ReconciliationCliError("output directory must be a concrete filesystem path")
    path = value
    _require_supported_path_namespace(path, "output directory")
    if not path.is_absolute() or _contains_parent_reference(path):
        raise ReconciliationCliError("output directory must be an absolute normalized path")
    if _has_unsafe_path_component(path):
        raise ReconciliationCliError("output directory contains an unsafe path component")
    parent = path.parent
    if _path_has_alias(parent):
        raise ReconciliationCliError("output directory parent must not use filesystem aliases")
    try:
        resolved_parent = parent.resolve(strict=True)
        parent_facts = resolved_parent.stat()
    except (OSError, RuntimeError) as exc:
        raise ReconciliationCliError("output directory parent is unavailable") from exc
    if not stat.S_ISDIR(parent_facts.st_mode):
        raise ReconciliationCliError("output directory parent must be a directory")
    _require_local_ntfs(resolved_parent, "output directory parent")
    parent_canonical_path = _native_path_canonical_path(
        resolved_parent,
        "output directory parent",
        directory=True,
    )
    _require_external_canonical_path(parent_canonical_path, "output directory")
    resolved = resolved_parent / path.name
    if os.path.lexists(resolved):
        raise ReconciliationCliError("output directory must not already exist")
    return resolved


def _directory_identity(path: Path) -> _FileIdentity:
    if _path_has_alias(path):
        raise ReconciliationCliError("output directory is not a safe directory")
    try:
        facts = path.lstat()
    except OSError as exc:
        raise ReconciliationCliError("output directory identity cannot be verified") from exc
    if not stat.S_ISDIR(facts.st_mode):
        raise ReconciliationCliError("output directory is not a safe directory")
    return _FileIdentity(facts.st_dev, facts.st_ino)


def _require_directory_identity(path: Path, expected: _FileIdentity) -> None:
    if _directory_identity(path) != expected:
        raise ReconciliationCliError("output directory identity changed")


def _artifact_identity(path: Path) -> _FileIdentity:
    if _path_has_alias(path):
        raise ReconciliationCliError("output artifact uses a filesystem alias")
    try:
        facts = path.lstat()
    except OSError as exc:
        raise ReconciliationCliError("output artifact identity cannot be verified") from exc
    if not stat.S_ISREG(facts.st_mode) or facts.st_nlink != 1:
        raise ReconciliationCliError("output artifact is not a regular unaliased file")
    return _FileIdentity(facts.st_dev, facts.st_ino)


def _require_artifact_identity(artifact: _CreatedArtifact) -> None:
    if _artifact_identity(artifact.path) != artifact.identity:
        raise ReconciliationCliError("output artifact identity changed")


def _artifact_handle_state(
    artifact: _CreatedArtifact,
    *,
    delete_guarded: bool = False,
) -> _InputFileState:
    if artifact.handle is None or artifact.handle.closed:
        raise ReconciliationCliError("output artifact handle is unavailable")
    try:
        facts = os.fstat(artifact.handle.fileno())
    except (OSError, ValueError) as exc:
        raise ReconciliationCliError("output artifact handle cannot be verified") from exc
    valid_link_counts = {0, 1} if delete_guarded else {1}
    if not stat.S_ISREG(facts.st_mode) or facts.st_nlink not in valid_link_counts:
        raise ReconciliationCliError("output artifact handle is not one regular file")
    state = _InputFileState(
        identity=_FileIdentity(facts.st_dev, facts.st_ino),
        byte_count=facts.st_size,
        modified_ns=facts.st_mtime_ns,
    )
    _require_unnamed_data_stream(
        _native_os_handle(artifact.handle, "output artifact"),
        state.byte_count,
        "output artifact",
    )
    return state


def _verify_artifact_handle_contents(
    artifact: _CreatedArtifact,
    *,
    delete_guarded: bool = False,
) -> None:
    if artifact.expected_sha256 is None or artifact.expected_byte_count is None:
        raise ReconciliationCliError("output artifact expected content is unavailable")
    before = (
        _artifact_handle_state(artifact, delete_guarded=True)
        if delete_guarded
        else _artifact_handle_state(artifact)
    )
    if before.identity != artifact.identity:
        raise ReconciliationCliError("output artifact handle identity changed")
    digest = hashlib.sha256()
    byte_count = 0
    try:
        artifact.handle.seek(0)
        while chunk := artifact.handle.read(1024 * 1024):
            digest.update(chunk)
            byte_count += len(chunk)
    except (OSError, ValueError) as exc:
        raise ReconciliationCliError("output artifact cannot be verified from its handle") from exc
    after = (
        _artifact_handle_state(artifact, delete_guarded=True)
        if delete_guarded
        else _artifact_handle_state(artifact)
    )
    if before != after:
        raise ReconciliationCliError("output artifact state changed while verifying")
    if byte_count != artifact.expected_byte_count or digest.hexdigest() != artifact.expected_sha256:
        raise ReconciliationCliError("output artifact content does not match its evidence")


def _verify_artifact_contents(artifact: _CreatedArtifact) -> None:
    _verify_artifact_handle_contents(artifact)
    _require_artifact_identity(artifact)


def _open_output_file(
    directory: Path,
    identity: _FileIdentity,
    filename: str,
    created: list[_CreatedArtifact],
) -> tuple[Path, Any, _CreatedArtifact]:
    if filename not in _OUTPUT_FILENAMES or Path(filename).name != filename:
        raise ReconciliationCliError("output filename is not approved")
    _require_directory_identity(directory, identity)
    path = directory / filename
    try:
        handle = _native_binary_file(
            path,
            writable=True,
            create=True,
            context="output artifact",
        )
    except ReconciliationCliError as exc:
        raise ReconciliationCliError("output artifact cannot be created exclusively") from exc
    try:
        facts = os.fstat(handle.fileno())
        if not stat.S_ISREG(facts.st_mode) or facts.st_nlink != 1:
            raise ReconciliationCliError("output artifact is not a regular unaliased file")
        artifact = _CreatedArtifact(
            path=path,
            identity=_FileIdentity(facts.st_dev, facts.st_ino),
            handle=handle,
        )
        created.append(artifact)
        _require_unnamed_data_stream(
            _native_os_handle(handle, "output artifact"),
            facts.st_size,
            "output artifact",
        )
        _require_directory_identity(directory, identity)
        _require_artifact_identity(artifact)
    except BaseException:
        handle.close()
        raise
    return path, handle, artifact


def _write_bytes(
    directory: Path,
    identity: _FileIdentity,
    filename: str,
    raw: bytes,
    created: list[_CreatedArtifact],
    *,
    record_count: int = 1,
) -> _ArtifactEvidence:
    _path, handle, artifact = _open_output_file(directory, identity, filename, created)
    try:
        written = handle.write(raw)
        if written != len(raw):
            raise ReconciliationCliError("output artifact write was incomplete")
        handle.flush()
        os.fsync(handle.fileno())
    except ReconciliationCliError:
        raise
    except (OSError, ValueError) as exc:
        raise ReconciliationCliError("output artifact cannot be written safely") from exc
    artifact.expected_sha256 = hashlib.sha256(raw).hexdigest()
    artifact.expected_byte_count = len(raw)
    _require_directory_identity(directory, identity)
    _verify_artifact_contents(artifact)
    return _ArtifactEvidence(filename, artifact.expected_sha256, len(raw), record_count)


def _write_records(
    directory: Path,
    identity: _FileIdentity,
    generation: ReconciledCatalogGenerationV1,
    created: list[_CreatedArtifact],
) -> _ArtifactEvidence:
    filename = "catalog-records.v1.jsonl"
    _path, handle, artifact = _open_output_file(directory, identity, filename, created)
    digest = hashlib.sha256()
    byte_count = 0
    record_count = 0
    try:
        for record in generation.records:
            raw = record.to_json_bytes() + b"\n"
            written = handle.write(raw)
            if written != len(raw):
                raise ReconciliationCliError("catalog record write was incomplete")
            digest.update(raw)
            byte_count += len(raw)
            record_count += 1
        handle.flush()
        os.fsync(handle.fileno())
    except ReconciliationCliError:
        raise
    except (OSError, ValueError) as exc:
        raise ReconciliationCliError("catalog records cannot be written safely") from exc
    artifact.expected_sha256 = digest.hexdigest()
    artifact.expected_byte_count = byte_count
    _require_directory_identity(directory, identity)
    _verify_artifact_contents(artifact)
    if record_count != generation.dataset_manifest.included_product_count:
        raise ReconciliationCliError("catalog record output count is inconsistent")
    return _ArtifactEvidence(filename, digest.hexdigest(), byte_count, record_count)


def _delete_artifact_by_handle(artifact: _CreatedArtifact) -> None:
    handle = artifact.handle
    if handle is None or handle.closed:
        raise ReconciliationCliError("output artifact exact handle is unavailable for cleanup")
    state = _artifact_handle_state(artifact)
    if state.identity != artifact.identity:
        raise ReconciliationCliError("output artifact replacement is not owned by this run")
    if artifact.delete_capable:
        raw_handle = _native_os_handle(handle, "output artifact")
        _native_mark_delete(raw_handle, "output artifact")
        try:
            _require_unnamed_data_stream(raw_handle, state.byte_count, "output artifact")
        except BaseException as exc:
            try:
                _native_cancel_delete(raw_handle, "output artifact")
            except ReconciliationCliError as cancel_error:
                raise cancel_error from exc
            raise
        handle.close()
        artifact.handle = None
        return
    delete_handle = _native_reopen_for_delete(handle, "output artifact")
    try:
        _native_mark_delete(delete_handle, "output artifact")
        try:
            _require_unnamed_data_stream(
                delete_handle,
                state.byte_count,
                "output artifact",
            )
        except BaseException as exc:
            try:
                _native_cancel_delete(delete_handle, "output artifact")
            except ReconciliationCliError as cancel_error:
                raise cancel_error from exc
            raise
        handle.close()
        artifact.handle = None
    finally:
        _native_close(delete_handle)


def _seal_artifact_path(artifact: _CreatedArtifact) -> None:
    if artifact.handle is not None and not artifact.handle.closed:
        return
    if not os.path.lexists(artifact.path):
        return
    handle = _native_sealed_file(artifact.path, "output artifact")
    artifact.handle = handle
    artifact.delete_capable = True
    try:
        if _artifact_handle_state(artifact).identity != artifact.identity:
            raise ReconciliationCliError("output artifact replacement is not owned by this run")
    except BaseException:
        handle.close()
        artifact.handle = None
        raise


def _close_created_output(created: list[_CreatedArtifact]) -> None:
    for artifact in created:
        _verify_artifact_contents(artifact)
    try:
        for artifact in created:
            assert artifact.handle is not None
            artifact.handle.close()
            artifact.handle = None
    except OSError as exc:
        raise ReconciliationCliError("published output handles could not be closed safely") from exc


def _cancel_published_delete_guards(raw_handles: list[int]) -> None:
    first_error: ReconciliationCliError | None = None
    for raw_handle in reversed(raw_handles):
        try:
            _native_cancel_delete(raw_handle, "published output artifact")
        except ReconciliationCliError as exc:
            if first_error is None:
                first_error = exc
    if first_error is not None:
        raise ReconciliationCliError(
            "published output delete guard could not be released safely"
        ) from first_error


def _attest_and_close_published_output(
    lease: _DirectoryLease,
    created: list[_CreatedArtifact],
) -> None:
    if len(created) != len(_OUTPUT_FILENAMES) or any(
        artifact.path.name not in _OUTPUT_FILENAMES or not artifact.delete_capable
        for artifact in created
    ):
        raise ReconciliationCliError("published output seal is incomplete")
    for artifact in created:
        _verify_artifact_contents(artifact)
    _verify_output_shape(lease)

    guarded_handles: list[int] = []
    try:
        for artifact in created:
            assert artifact.handle is not None
            raw_handle = _native_os_handle(artifact.handle, "published output artifact")
            _native_mark_delete(raw_handle, "published output artifact")
            guarded_handles.append(raw_handle)
        for artifact in created:
            _verify_artifact_handle_contents(artifact, delete_guarded=True)
        # All seven carriers are delete-pending at this single attestation point.
        _verify_output_shape(lease)
    except BaseException as exc:
        try:
            _cancel_published_delete_guards(guarded_handles)
        except ReconciliationCliError as cancel_error:
            raise cancel_error from exc
        raise

    _cancel_published_delete_guards(guarded_handles)
    try:
        for artifact in created:
            assert artifact.handle is not None
            artifact.handle.close()
            artifact.handle = None
    except OSError as exc:
        raise ReconciliationCliError("published output handles could not be closed safely") from exc


def _cleanup_created_output(
    lease: _DirectoryLease,
    created: list[_CreatedArtifact],
) -> None:
    unsafe = False
    for artifact in reversed(created):
        if artifact.path.parent != lease.path:
            unsafe = True
            continue
        try:
            _seal_artifact_path(artifact)
            if artifact.handle is None:
                continue
            _delete_artifact_by_handle(artifact)
        except (OSError, ReconciliationCliError):
            unsafe = True
    try:
        _delete_directory_by_handle(lease)
    except (OSError, ReconciliationCliError):
        unsafe = True
    if unsafe:
        raise ReconciliationCliError("incomplete output could not be cleaned safely")


def _create_staging_directory(target: Path) -> tuple[_DirectoryLease, _FileIdentity]:
    parent = target.parent
    parent_identity = _directory_identity(parent)
    try:
        staging = Path(tempfile.mkdtemp(prefix=".nla-reconcile-staging-", dir=parent))
    except OSError as exc:
        raise ReconciliationCliError("output staging directory cannot be created safely") from exc
    identity = _directory_identity(staging)
    lease = _open_directory_lease(staging, identity)
    try:
        if staging.parent != parent or _has_unsafe_path_component(staging):
            raise ReconciliationCliError("output staging directory is unsafe")
        _require_directory_identity(parent, parent_identity)
    except ReconciliationCliError as exc:
        try:
            _cleanup_created_output(lease, [])
        except ReconciliationCliError as cleanup_error:
            raise cleanup_error from exc
        raise
    return lease, parent_identity


def _publish_staging_directory(
    lease: _DirectoryLease,
    target: Path,
    parent_identity: _FileIdentity,
    created: list[_CreatedArtifact],
) -> None:
    _verify_output_shape(lease)
    _require_directory_identity(lease.path, lease.identity)
    _require_directory_identity(target.parent, parent_identity)
    for artifact in created:
        _verify_artifact_contents(artifact)
    if os.path.lexists(target):
        raise ReconciliationCliError("output directory must not already exist")
    _close_created_output(created)
    try:
        _rename_directory_by_handle(lease, target)
    except OSError as exc:
        raise ReconciliationCliError("output directory cannot be published safely") from exc
    for artifact in created:
        artifact.path = target / artifact.path.name
    try:
        _require_directory_identity(target.parent, parent_identity)
        _require_directory_identity(target, lease.identity)
        for artifact in created:
            _seal_artifact_path(artifact)
        _verify_output_shape(lease)
        for artifact in created:
            _verify_artifact_contents(artifact)
    except ReconciliationCliError as exc:
        raise ReconciliationCliError("published output identity cannot be verified") from exc


def _write_generation_output(
    output_directory: Path,
    products_manifest: SnapshotPartManifestV1,
    variants_manifest: SnapshotPartManifestV1,
    generation: ReconciledCatalogGenerationV1,
    terminal_query_audits: tuple[_TerminalQueryAuditEvidence, _TerminalQueryAuditEvidence],
) -> dict[str, object]:
    taxonomy_bytes = _canonical_json_bytes(
        {
            "schemaVersion": TAXONOMY_REPORT_SCHEMA_VERSION,
            **generation.taxonomy_report.as_dict(),
        }
    )
    static_artifacts = (
        ("dataset-manifest.v1.json", generation.dataset_manifest.to_json_bytes()),
        ("products-part-manifest.v1.json", products_manifest.to_json_bytes()),
        ("source-manifest.v2.json", generation.source_manifest_bytes),
        ("taxonomy-report.v1.json", taxonomy_bytes),
        ("variants-part-manifest.v1.json", variants_manifest.to_json_bytes()),
    )
    target = _validated_output_directory(output_directory)
    lease, parent_identity = _create_staging_directory(target)
    directory = lease.path
    identity = lease.identity
    created: list[_CreatedArtifact] = []
    try:
        artifacts = [
            _write_bytes(directory, identity, filename, raw, created)
            for filename, raw in static_artifacts
        ]
        artifacts.append(_write_records(directory, identity, generation, created))
        artifacts.sort(key=lambda item: item.filename)
        summary = {
            "artifacts": [item.as_dict() for item in artifacts],
            "capabilityPromotion": "not-performed",
            "catalogRecordCount": len(generation.records),
            "classifiedProductCount": generation.taxonomy_report.classified,
            "datasetActivation": "not-performed",
            "datasetGeneration": generation.dataset_manifest.dataset_generation,
            "schemaVersion": SUMMARY_SCHEMA_VERSION,
            "snapshotSetId": generation.source_manifest.snapshot_set_id,
            "sourceGeneration": generation.source_manifest.source_generation,
            "status": "reconciled-provisional",
            "taxonomyRuleVersion": generation.taxonomy_report.rule_version,
            "terminalQueryAudits": [item.as_dict() for item in terminal_query_audits],
            "unclassifiedProductCount": generation.taxonomy_report.unclassified,
            "variantCount": generation.source_manifest.variant_count,
        }
        summary_bytes = _canonical_json_bytes(summary)
        _write_bytes(
            directory,
            identity,
            "reconciliation-summary.v1.json",
            summary_bytes,
            created,
        )
        _require_directory_identity(directory, identity)
        for artifact in created:
            _require_artifact_identity(artifact)
        _publish_staging_directory(lease, target, parent_identity, created)
        _attest_and_close_published_output(lease, created)
        _close_directory_lease(lease)
        return summary
    except BaseException as exc:
        try:
            _cleanup_created_output(lease, created)
        except ReconciliationCliError as cleanup_error:
            raise cleanup_error from exc
        raise


def run_reconciliation(
    *,
    products_snapshot: Path,
    variants_snapshot: Path,
    products_query: Path,
    variants_query: Path,
    products_terminal: Path,
    variants_terminal: Path,
    expectation_path: Path,
    output_directory: Path,
) -> dict[str, object]:
    """Validate external evidence, reconcile it, and publish one provisional output set."""

    external_values = (
        (products_snapshot, "products snapshot"),
        (variants_snapshot, "variants snapshot"),
        (products_terminal, "products terminal evidence"),
        (variants_terminal, "variants terminal evidence"),
        (expectation_path, "reconciliation expectation"),
    )
    resolved_external = [
        _regular_file(path, context, external=True) for path, context in external_values
    ]
    products_query_path, products_query_state = _regular_file(
        products_query, "products query", external=False
    )
    variants_query_path, variants_query_state = _regular_file(
        variants_query, "variants query", external=False
    )
    identities = [state.identity for _path, state in resolved_external]
    identities.extend((products_query_state.identity, variants_query_state.identity))
    if len(set(identities)) != len(identities):
        raise ReconciliationCliError("input files must have distinct identities")
    (
        (products_snapshot_path, products_snapshot_state),
        (variants_snapshot_path, variants_snapshot_state),
        (products_terminal_path, products_terminal_state),
        (variants_terminal_path, variants_terminal_state),
        (resolved_expectation_path, expectation_state),
    ) = resolved_external
    with ExitStack() as stack:
        products_snapshot_input = _pin_regular_file(
            products_snapshot_path,
            products_snapshot_state,
            "products snapshot",
            stack,
            external=True,
        )
        variants_snapshot_input = _pin_regular_file(
            variants_snapshot_path,
            variants_snapshot_state,
            "variants snapshot",
            stack,
            external=True,
        )
        products_terminal_input = _pin_regular_file(
            products_terminal_path,
            products_terminal_state,
            "products terminal evidence",
            stack,
            freeze_maximum=CONTROL_DOCUMENT_MAX_BYTES,
            external=True,
        )
        variants_terminal_input = _pin_regular_file(
            variants_terminal_path,
            variants_terminal_state,
            "variants terminal evidence",
            stack,
            freeze_maximum=CONTROL_DOCUMENT_MAX_BYTES,
            external=True,
        )
        expectation_input = _pin_regular_file(
            resolved_expectation_path,
            expectation_state,
            "reconciliation expectation",
            stack,
            freeze_maximum=CONTROL_DOCUMENT_MAX_BYTES,
            external=True,
        )
        products_query_input = _pin_regular_file(
            products_query_path,
            products_query_state,
            "products query",
            stack,
            freeze_maximum=reconciliation_model.MAX_BULK_QUERY_BYTES,
        )
        variants_query_input = _pin_regular_file(
            variants_query_path,
            variants_query_state,
            "variants query",
            stack,
            freeze_maximum=reconciliation_model.MAX_BULK_QUERY_BYTES,
        )
        pinned_inputs = (
            products_snapshot_input,
            variants_snapshot_input,
            products_terminal_input,
            variants_terminal_input,
            expectation_input,
            products_query_input,
            variants_query_input,
        )
        expectation = _load_expectation(expectation_input)
        products_terminal_evidence = _load_terminal_evidence(
            products_terminal_input, "products terminal evidence"
        )
        variants_terminal_evidence = _load_terminal_evidence(
            variants_terminal_input, "variants terminal evidence"
        )
        terminal_query_audits = (
            _terminal_query_audit(
                part=SnapshotPart.PRODUCTS,
                terminal=products_terminal_evidence,
                query=products_query_input,
            ),
            _terminal_query_audit(
                part=SnapshotPart.VARIANTS,
                terminal=variants_terminal_evidence,
                query=variants_query_input,
            ),
        )
        for pinned in pinned_inputs:
            _verify_pinned_input(pinned)
        products_manifest = create_snapshot_part_manifest(
            products_snapshot_path,
            query_path=products_query_path,
            part=SnapshotPart.PRODUCTS,
            expectation=expectation,
            terminal_evidence=products_terminal_evidence,
            snapshot_handle=products_snapshot_input.handle,
            query_bytes=products_query_input.frozen_bytes,
        )
        _verify_pinned_input(products_snapshot_input)
        _verify_pinned_input(products_query_input)
        variants_manifest = create_snapshot_part_manifest(
            variants_snapshot_path,
            query_path=variants_query_path,
            part=SnapshotPart.VARIANTS,
            expectation=expectation,
            terminal_evidence=variants_terminal_evidence,
            snapshot_handle=variants_snapshot_input.handle,
            query_bytes=variants_query_input.frozen_bytes,
        )
        _verify_pinned_input(variants_snapshot_input)
        _verify_pinned_input(variants_query_input)
        generation = reconcile_snapshot_parts(
            (
                SnapshotPartInputV1(
                    manifest=products_manifest,
                    snapshot_path=products_snapshot_path,
                    query_path=products_query_path,
                    snapshot_handle=products_snapshot_input.handle,
                    query_bytes=products_query_input.frozen_bytes,
                ),
                SnapshotPartInputV1(
                    manifest=variants_manifest,
                    snapshot_path=variants_snapshot_path,
                    query_path=variants_query_path,
                    snapshot_handle=variants_snapshot_input.handle,
                    query_bytes=variants_query_input.frozen_bytes,
                ),
            ),
            expectation=expectation,
            taxonomy_config=load_taxonomy(),
        )
        for pinned in pinned_inputs:
            _verify_pinned_input(pinned)
        return _write_generation_output(
            output_directory,
            products_manifest,
            variants_manifest,
            generation,
            terminal_query_audits,
        )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = _SafeArgumentParser(description=__doc__)
    parser.add_argument("--products-jsonl", required=True, type=Path)
    parser.add_argument("--variants-jsonl", required=True, type=Path)
    parser.add_argument("--products-query", required=True, type=Path)
    parser.add_argument("--variants-query", required=True, type=Path)
    parser.add_argument("--products-terminal", required=True, type=Path)
    parser.add_argument("--variants-terminal", required=True, type=Path)
    parser.add_argument("--expectation", required=True, type=Path)
    parser.add_argument("--output-directory", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        summary = run_reconciliation(
            products_snapshot=args.products_jsonl,
            variants_snapshot=args.variants_jsonl,
            products_query=args.products_query,
            variants_query=args.variants_query,
            products_terminal=args.products_terminal,
            variants_terminal=args.variants_terminal,
            expectation_path=args.expectation,
            output_directory=args.output_directory,
        )
        print(
            _canonical_json_bytes(
                {
                    "datasetGeneration": summary["datasetGeneration"],
                    "outputCreated": True,
                    "summarySha256": hashlib.sha256(_canonical_json_bytes(summary)).hexdigest(),
                    "sourceGeneration": summary["sourceGeneration"],
                    "status": "ok",
                }
            ).decode("utf-8")
        )
        return 0
    except Exception:
        print("split snapshot reconciliation failed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ReconciliationCliError",
    "main",
    "parse_args",
    "run_reconciliation",
]
