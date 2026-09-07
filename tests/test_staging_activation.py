from __future__ import annotations

import hashlib
import json
import os
import pickle
import runpy
import stat
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from scripts import manage_staging_activation, package_staging_generation

import test_generation_bundle as bundle_helpers
import test_staging_generation as staging_helpers
from nla_catalog_gateway import staging_activation, staging_generation

ERROR = "staging activation failed"


def _fixed_failure(call: Any) -> None:
    with pytest.raises(staging_activation.StagingActivationError) as captured:
        call()
    assert str(captured.value) == ERROR
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


def _install_generation(tmp_path: Path, root: Path, code_character: str) -> SimpleNamespace:
    build_root = (tmp_path / f"build-{code_character}").resolve()
    build_root.mkdir()
    package = staging_helpers._make_package(build_root)
    if code_character != "c":
        report_path = package.directory / staging_generation.EVIDENCE_FILENAME
        report = json.loads(report_path.read_bytes())
        report["bindings"]["codeSha"] = code_character * 40
        package.manifest_sha256 = staging_helpers._rewrite_report(package.directory, report)
    destination = root / staging_activation.GENERATIONS_DIRECTORY / package.manifest_sha256
    # A cross-parent directory rename needs the package directory to be writable
    # on POSIX.  The installed fixture still models the immutable package.
    package.directory.chmod(stat.S_IRWXU)
    os.rename(package.directory, destination)
    destination.chmod(package_staging_generation._READ_ONLY_DIRECTORY_MODE)
    package.directory = destination
    return package


@pytest.fixture
def activation_store(tmp_path: Path) -> SimpleNamespace:
    root = (tmp_path / "activation-store").resolve()
    root.mkdir()
    (root / staging_activation.GENERATIONS_DIRECTORY).mkdir()
    packages = tuple(_install_generation(tmp_path, root, character) for character in "cde")
    return SimpleNamespace(root=root, packages=packages)


def _promote_first(store: SimpleNamespace) -> str:
    return staging_activation.promote_staging_generation(
        store.root,
        store.packages[0].manifest_sha256,
        staging_activation.ABSENT_ACTIVATION_SHA256,
    )


def test_first_activation_and_restart_load_the_same_verified_generation(
    activation_store: SimpleNamespace,
) -> None:
    package = activation_store.packages[0]
    pin = _promote_first(activation_store)
    first = staging_activation.load_active_staging_generation(activation_store.root, pin)
    restarted = staging_activation.load_active_staging_generation(activation_store.root, pin)
    assert first.current_manifest_sha256 == package.manifest_sha256
    assert first.previous_manifest_sha256 is None
    assert first.activation_sha256 == pin
    assert first.generation.records == package.records
    assert restarted.current_manifest_sha256 == first.current_manifest_sha256
    assert restarted.generation.records == first.generation.records
    assert "myshopify" not in repr(first)
    with pytest.raises(staging_activation.StagingActivationError, match=ERROR):
        staging_activation.ActiveStagingGenerationV1()
    with pytest.raises(staging_activation.StagingActivationError, match=ERROR):
        first.__reduce__()
    with pytest.raises(staging_activation.StagingActivationError, match=ERROR):
        pickle.dumps(first)
    with pytest.raises(FrozenInstanceError):
        first.activation_sha256 = "0" * 64

    pointer = activation_store.root / staging_activation.ACTIVATION_FILENAME
    raw = pointer.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == pin
    assert raw == staging_activation._canonical_pointer_bytes(
        staging_activation._ActivationPointer(package.manifest_sha256, None)
    )
    assert frozenset(json.loads(raw)) == frozenset(
        {"schemaVersion", "currentManifestSha256", "previousManifestSha256"}
    )
    assert bundle_helpers.SHOP.encode() not in raw
    assert b"gid://shopify" not in raw
    assert str(activation_store.root).encode() not in raw


def test_promote_preserves_previous_and_rollback_exchanges_verified_packages(
    activation_store: SimpleNamespace,
) -> None:
    first, second = activation_store.packages[:2]
    first_pin = _promote_first(activation_store)
    second_pin = staging_activation.promote_staging_generation(
        activation_store.root, second.manifest_sha256, first_pin
    )
    promoted = staging_activation.load_active_staging_generation(activation_store.root, second_pin)
    assert promoted.current_manifest_sha256 == second.manifest_sha256
    assert promoted.previous_manifest_sha256 == first.manifest_sha256
    assert first.directory.is_dir()
    assert second.directory.is_dir()

    rollback_pin = staging_activation.rollback_staging_generation(activation_store.root, second_pin)
    rolled_back = staging_activation.load_active_staging_generation(
        activation_store.root, rollback_pin
    )
    assert rolled_back.current_manifest_sha256 == first.manifest_sha256
    assert rolled_back.previous_manifest_sha256 == second.manifest_sha256
    assert first.directory.is_dir()
    assert second.directory.is_dir()


def test_bad_pins_and_invalid_transitions_leave_pointer_unchanged(
    activation_store: SimpleNamespace,
) -> None:
    first, second = activation_store.packages[:2]
    bad_pin = "f" * 64
    _fixed_failure(
        lambda: staging_activation.promote_staging_generation(
            activation_store.root, first.manifest_sha256, bad_pin
        )
    )
    assert not (activation_store.root / staging_activation.ACTIVATION_FILENAME).exists()
    first_pin = _promote_first(activation_store)
    original = (activation_store.root / staging_activation.ACTIVATION_FILENAME).read_bytes()
    for operation in (
        lambda: staging_activation.load_active_staging_generation(activation_store.root, bad_pin),
        lambda: staging_activation.promote_staging_generation(
            activation_store.root, second.manifest_sha256, bad_pin
        ),
        lambda: staging_activation.rollback_staging_generation(activation_store.root, bad_pin),
        lambda: staging_activation.promote_staging_generation(
            activation_store.root, first.manifest_sha256, first_pin
        ),
        lambda: staging_activation.rollback_staging_generation(activation_store.root, first_pin),
    ):
        _fixed_failure(operation)
        assert (activation_store.root / staging_activation.ACTIVATION_FILENAME).read_bytes() == (
            original
        )


def test_pointer_and_active_package_tampering_fail_closed(
    activation_store: SimpleNamespace,
) -> None:
    package = activation_store.packages[0]
    pin = _promote_first(activation_store)
    pointer = activation_store.root / staging_activation.ACTIVATION_FILENAME
    canonical = pointer.read_bytes()
    pointer.write_bytes(canonical + b"\n")
    tampered_pin = hashlib.sha256(pointer.read_bytes()).hexdigest()
    _fixed_failure(
        lambda: staging_activation.load_active_staging_generation(
            activation_store.root, tampered_pin
        )
    )
    pointer.write_bytes(canonical)
    projection = package.directory / staging_generation.PROJECTION_FILENAME
    package.directory.chmod(stat.S_IRWXU)
    projection.chmod(stat.S_IRUSR | stat.S_IWUSR)
    with projection.open("r+b") as output:
        output.seek(0)
        output.write(b"BROKEN!!")
    projection.chmod(stat.S_IRUSR)
    package.directory.chmod(stat.S_IRUSR | stat.S_IXUSR)
    _fixed_failure(
        lambda: staging_activation.load_active_staging_generation(activation_store.root, pin)
    )


def test_concurrent_promotions_with_one_pin_have_exactly_one_winner(
    activation_store: SimpleNamespace,
) -> None:
    first_pin = _promote_first(activation_store)
    candidates = [package.manifest_sha256 for package in activation_store.packages[1:]]

    def attempt(candidate: str) -> tuple[bool, str | None]:
        try:
            return (
                True,
                staging_activation.promote_staging_generation(
                    activation_store.root, candidate, first_pin
                ),
            )
        except staging_activation.StagingActivationError:
            return False, None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(attempt, candidates))
    assert sum(accepted for accepted, _pin in results) == 1
    winning_pin = next(pin for accepted, pin in results if accepted)
    active = staging_activation.load_active_staging_generation(activation_store.root, winning_pin)
    assert active.current_manifest_sha256 in candidates
    assert active.previous_manifest_sha256 == activation_store.packages[0].manifest_sha256
    assert (activation_store.root / staging_activation._LOCK_FILENAME).is_file()


def test_atomic_write_failure_keeps_previous_pointer_and_packages(
    activation_store: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first, second = activation_store.packages[:2]
    first_pin = _promote_first(activation_store)
    pointer = activation_store.root / staging_activation.ACTIVATION_FILENAME
    original = pointer.read_bytes()

    def fail_replace(*_args: object) -> None:
        raise OSError("sensitive-value")

    monkeypatch.setattr(staging_activation.os, "replace", fail_replace)
    _fixed_failure(
        lambda: staging_activation.promote_staging_generation(
            activation_store.root, second.manifest_sha256, first_pin
        )
    )
    assert pointer.read_bytes() == original
    assert first.directory.is_dir()
    assert second.directory.is_dir()
    assert not tuple(activation_store.root.glob(f"{staging_activation._TEMP_PREFIX}*"))
    assert (activation_store.root / staging_activation._LOCK_FILENAME).is_file()


@pytest.mark.parametrize("failure_stage", ["directory-fsync", "post-read"])
def test_post_replace_fault_recovers_the_installed_pointer_digest(
    activation_store: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    package = activation_store.packages[0]
    reads = 0
    syncs = 0
    original_read = staging_activation._read_pointer

    if failure_stage == "directory-fsync":

        def fail_first_sync(_root: Path) -> None:
            nonlocal syncs
            syncs += 1
            if syncs == 1:
                raise OSError("sensitive")

        monkeypatch.setattr(staging_activation, "_fsync_directory", fail_first_sync)
    else:

        def fail_first_post_read(root: Path, digest: str) -> Any:
            nonlocal reads
            reads += 1
            pointer, raw = original_read(root, digest)
            if reads == 1:
                return pointer, raw + b"not-the-installed-bytes"
            return pointer, raw

        monkeypatch.setattr(staging_activation, "_read_pointer", fail_first_post_read)

    pin = _promote_first(activation_store)
    active = staging_activation.load_active_staging_generation(activation_store.root, pin)
    assert active.current_manifest_sha256 == package.manifest_sha256
    if failure_stage == "directory-fsync":
        assert syncs == 2
    if failure_stage == "post-read":
        assert reads == 4


def test_persistent_directory_fsync_failure_is_explicitly_ambiguous(
    activation_store: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    syncs = 0

    def reject_sync(_root: Path) -> None:
        nonlocal syncs
        syncs += 1
        raise OSError("sensitive")

    monkeypatch.setattr(staging_activation, "_fsync_directory", reject_sync)
    with pytest.raises(
        staging_activation.StagingActivationOutcomeAmbiguous,
        match=r"^staging activation outcome is ambiguous$",
    ) as captured:
        _promote_first(activation_store)
    assert syncs == 2
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


def test_unattestable_post_replace_state_is_explicitly_ambiguous(
    activation_store: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pointer_path = activation_store.root / staging_activation.ACTIVATION_FILENAME

    def corrupt_after_replace(_root: Path) -> None:
        pointer_path.write_bytes(b"tampered")
        raise OSError("sensitive")

    monkeypatch.setattr(staging_activation, "_fsync_directory", corrupt_after_replace)
    with pytest.raises(
        staging_activation.StagingActivationOutcomeAmbiguous,
        match=r"^staging activation outcome is ambiguous$",
    ) as captured:
        _promote_first(activation_store)
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    assert pointer_path.read_bytes() == b"tampered"


def test_unattestable_rollback_state_is_explicitly_ambiguous(
    activation_store: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_pin = _promote_first(activation_store)
    second_pin = staging_activation.promote_staging_generation(
        activation_store.root,
        activation_store.packages[1].manifest_sha256,
        first_pin,
    )
    pointer_path = activation_store.root / staging_activation.ACTIVATION_FILENAME

    def corrupt_after_replace(_root: Path) -> None:
        pointer_path.write_bytes(b"tampered")
        raise OSError("sensitive")

    monkeypatch.setattr(staging_activation, "_fsync_directory", corrupt_after_replace)
    with pytest.raises(
        staging_activation.StagingActivationOutcomeAmbiguous,
        match=r"^staging activation outcome is ambiguous$",
    ) as captured:
        staging_activation.rollback_staging_generation(activation_store.root, second_pin)
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


def test_recovery_rejects_bytes_other_than_the_intended_pointer(
    activation_store: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = staging_activation._canonical_pointer_bytes(
        staging_activation._ActivationPointer(activation_store.packages[0].manifest_sha256, None)
    )
    digest = hashlib.sha256(raw).hexdigest()
    monkeypatch.setattr(
        staging_activation,
        "_read_pointer",
        lambda _root, _digest: (
            staging_activation._ActivationPointer(
                activation_store.packages[0].manifest_sha256, None
            ),
            b"different",
        ),
    )
    with pytest.raises(staging_activation.StagingActivationOutcomeAmbiguous):
        staging_activation._recover_installed_pointer(
            activation_store.root,
            raw,
            digest,
            directory_synced=True,
        )


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"{",
        b"{}",
        b'{"currentManifestSha256":"bad","previousManifestSha256":null,"schemaVersion":1}',
        staging_activation._canonical_pointer_bytes(
            staging_activation._ActivationPointer("a" * 64, "a" * 64)
        ),
        b"x" * (staging_activation.MAX_ACTIVATION_BYTES + 1),
    ],
)
def test_malformed_pointer_shapes_are_rejected(raw: bytes) -> None:
    with pytest.raises(staging_activation.StagingActivationError, match=ERROR):
        staging_activation._parse_pointer(raw)


def test_root_package_and_pointer_boundaries_fail_closed(
    activation_store: SimpleNamespace,
    tmp_path: Path,
) -> None:
    first = activation_store.packages[0]
    invalid_roots: tuple[object, ...] = (
        "not-a-path",
        Path("relative"),
        (tmp_path / "missing").resolve(),
    )
    for root in invalid_roots:
        _fixed_failure(
            lambda root=root: staging_activation.promote_staging_generation(  # type: ignore[arg-type]
                root, first.manifest_sha256, staging_activation.ABSENT_ACTIVATION_SHA256
            )
        )
    _fixed_failure(
        lambda: staging_activation.promote_staging_generation(
            activation_store.root, "BAD", staging_activation.ABSENT_ACTIVATION_SHA256
        )
    )
    with pytest.raises(staging_activation.StagingActivationError, match=ERROR):
        staging_activation._validated_root(staging_generation.REPOSITORY_ROOT)
    root_with_file = (tmp_path / "root-with-file").resolve()
    root_with_file.mkdir()
    (root_with_file / staging_activation.GENERATIONS_DIRECTORY).write_bytes(b"not-a-directory")
    with pytest.raises(staging_activation.StagingActivationError, match=ERROR):
        staging_activation._validated_root(root_with_file)
    missing_package = "0" * 64
    _fixed_failure(
        lambda: staging_activation.promote_staging_generation(
            activation_store.root,
            missing_package,
            staging_activation.ABSENT_ACTIVATION_SHA256,
        )
    )


def test_pointer_identity_alias_and_change_during_load_are_rejected(
    activation_store: SimpleNamespace,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin = _promote_first(activation_store)
    pointer = activation_store.root / staging_activation.ACTIVATION_FILENAME
    alias = tmp_path / "pointer-alias"
    os.link(pointer, alias)
    _fixed_failure(
        lambda: staging_activation.load_active_staging_generation(activation_store.root, pin)
    )
    alias.unlink()
    calls = 0
    original = staging_activation._read_pointer

    def change_on_second_read(root: Path, expected: str) -> Any:
        nonlocal calls
        calls += 1
        result = original(root, expected)
        if calls == 2:
            return staging_activation._ActivationPointer("f" * 64, None), result[1]
        return result

    monkeypatch.setattr(staging_activation, "_read_pointer", change_on_second_read)
    _fixed_failure(
        lambda: staging_activation.load_active_staging_generation(activation_store.root, pin)
    )
    assert calls == 2


def test_operator_lock_contention_and_cleanup_are_value_free(
    activation_store: SimpleNamespace,
) -> None:
    lock = activation_store.root / staging_activation._LOCK_FILENAME
    lock.write_bytes(b"stale-file-is-not-a-lock")
    with staging_activation._operator_lock(activation_store.root):
        _fixed_failure(
            lambda: staging_activation.promote_staging_generation(
                activation_store.root,
                activation_store.packages[0].manifest_sha256,
                staging_activation.ABSENT_ACTIVATION_SHA256,
            )
        )

    pin = staging_activation.promote_staging_generation(
        activation_store.root,
        activation_store.packages[0].manifest_sha256,
        staging_activation.ABSENT_ACTIVATION_SHA256,
    )
    assert staging_activation.load_active_staging_generation(activation_store.root, pin)
    assert lock.read_bytes() == b"stale-file-is-not-a-lock"


def test_lock_file_identity_rejects_every_alias_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "lock"
    path.write_bytes(b"x")
    opened = path.open("r+b")
    real = os.fstat(opened.fileno())
    states = (
        SimpleNamespace(
            st_mode=stat.S_IFLNK,
            st_nlink=1,
            st_file_attributes=0,
            st_dev=real.st_dev,
            st_ino=real.st_ino,
        ),
        SimpleNamespace(
            st_mode=stat.S_IFDIR,
            st_nlink=1,
            st_file_attributes=0,
            st_dev=real.st_dev,
            st_ino=real.st_ino,
        ),
        SimpleNamespace(
            st_mode=stat.S_IFREG,
            st_nlink=2,
            st_file_attributes=0,
            st_dev=real.st_dev,
            st_ino=real.st_ino,
        ),
        SimpleNamespace(
            st_mode=stat.S_IFREG,
            st_nlink=1,
            st_file_attributes=staging_activation._REPARSE_POINT_ATTRIBUTE,
            st_dev=real.st_dev,
            st_ino=real.st_ino,
        ),
        SimpleNamespace(
            st_mode=stat.S_IFREG,
            st_nlink=1,
            st_file_attributes=0,
            st_dev=real.st_dev,
            st_ino=real.st_ino + 1,
        ),
    )
    try:
        for state in states:
            with monkeypatch.context() as context:
                context.setattr(
                    Path,
                    "stat",
                    lambda *_args, state=state, **_kwargs: state,
                )
                with pytest.raises(OSError):
                    staging_activation._lock_file_identity(path, opened)
    finally:
        opened.close()


def test_advisory_lock_helpers_cover_windows_posix_and_release_faults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "lock"
    path.write_bytes(b"x")
    calls: list[tuple[object, ...]] = []
    windows = SimpleNamespace(
        LK_NBLCK=10,
        LK_UNLCK=11,
        locking=lambda *args: calls.append(("windows", *args)),
    )
    posix = SimpleNamespace(
        LOCK_EX=1,
        LOCK_NB=2,
        LOCK_UN=4,
        flock=lambda *args: calls.append(("posix", *args)),
    )

    def fake_import(name: str) -> SimpleNamespace:
        return windows if name == "msvcrt" else posix

    monkeypatch.setattr(staging_activation.importlib, "import_module", fake_import)
    with path.open("r+b") as handle:
        with monkeypatch.context() as context:
            context.setattr(staging_activation.os, "name", "nt")
            staging_activation._acquire_advisory_lock(handle)
            staging_activation._release_advisory_lock(handle)
        with monkeypatch.context() as context:
            context.setattr(staging_activation.os, "name", "posix")
            staging_activation._acquire_advisory_lock(handle)
            staging_activation._release_advisory_lock(handle)

        windows.locking = lambda *_args: (_ for _ in ()).throw(OSError())
        with monkeypatch.context() as context:
            context.setattr(staging_activation.os, "name", "nt")
            staging_activation._release_advisory_lock(handle)

    assert [call[0] for call in calls] == ["windows", "windows", "posix", "posix"]


def test_operator_lock_rejects_open_and_post_lock_identity_races(
    activation_store: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    def enter() -> None:
        with staging_activation._operator_lock(activation_store.root):
            pass

    with monkeypatch.context() as context:
        context.setattr(
            staging_activation,
            "_open_operator_lock",
            lambda _path: (_ for _ in ()).throw(OSError()),
        )
        _fixed_failure(enter)

    identities = iter(((1, 1), (2, 2)))
    with monkeypatch.context() as context:
        context.setattr(
            staging_activation,
            "_lock_file_identity",
            lambda *_args: next(identities),
        )
        context.setattr(staging_activation, "_acquire_advisory_lock", lambda _handle: None)
        context.setattr(staging_activation, "_release_advisory_lock", lambda _handle: None)
        _fixed_failure(enter)


def test_secure_lock_open_covers_posix_and_windows_failure_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    posix_path = tmp_path / "posix-lock"
    with staging_activation._open_posix_lock_file(posix_path) as opened:
        assert opened.read() == b""
    with staging_activation._open_posix_lock_file(posix_path) as reopened:
        assert reopened.read() == b""

    sentinel = object()
    with monkeypatch.context() as context:
        context.setattr(staging_activation.os, "name", "posix")
        context.setattr(staging_activation, "_open_posix_lock_file", lambda _path: sentinel)
        assert staging_activation._open_operator_lock(posix_path) is sentinel

    class FakeFunction:
        def __init__(self, result: object) -> None:
            self.result = result
            self.argtypes: object = None
            self.restype: object = None
            self.calls: list[tuple[object, ...]] = []

        def __call__(self, *args: object) -> object:
            self.calls.append(args)
            return self.result

    create_file = FakeFunction(staging_activation._WINDOWS_INVALID_HANDLE)
    close_handle = FakeFunction(1)
    kernel32 = SimpleNamespace(CreateFileW=create_file, CloseHandle=close_handle)
    with monkeypatch.context() as context:
        context.setattr(
            staging_activation.ctypes,
            "WinDLL",
            lambda *_args, **_kwargs: kernel32,
            raising=False,
        )
        with pytest.raises(OSError):
            staging_activation._windows_create_lock_handle(tmp_path / "reparse")
        staging_activation._windows_close_handle(123)
    assert create_file.calls
    assert close_handle.calls

    closed: list[int] = []
    conversion_failure = SimpleNamespace(
        open_osfhandle=lambda *_args: (_ for _ in ()).throw(OSError())
    )
    with monkeypatch.context() as context:
        context.setattr(staging_activation, "_windows_create_lock_handle", lambda _path: 456)
        context.setattr(
            staging_activation.importlib,
            "import_module",
            lambda _name: conversion_failure,
        )
        context.setattr(staging_activation, "_windows_close_handle", closed.append)
        with pytest.raises(OSError):
            staging_activation._open_windows_lock_file(tmp_path / "conversion-failure")
    assert closed == [456]

    descriptor_closes: list[int] = []
    with monkeypatch.context() as context:
        context.setattr(
            staging_activation.os,
            "fdopen",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError()),
        )
        context.setattr(staging_activation.os, "close", descriptor_closes.append)
        with pytest.raises(OSError):
            staging_activation._binary_file_from_descriptor(789)
    assert descriptor_closes == [789]


def test_best_effort_cleanup_ignores_a_missing_path(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    staging_activation._best_effort_unlink(missing)


def test_non_windows_atomic_pointer_flushes_parent_directory(
    activation_store: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[object] = []

    monkeypatch.setattr(staging_activation.os, "name", "posix")
    monkeypatch.setattr(
        staging_activation.os,
        "open",
        lambda path, flags: observed.append((path, flags)) or 777,
    )
    real_fsync = staging_activation.os.fsync

    def selected_fsync(file_descriptor: int) -> None:
        if file_descriptor == 777:
            observed.append("fsync-directory")
        else:
            real_fsync(file_descriptor)

    monkeypatch.setattr(staging_activation.os, "fsync", selected_fsync)
    monkeypatch.setattr(
        staging_activation.os,
        "close",
        lambda file_descriptor: observed.append(("close", file_descriptor)),
    )
    staging_activation._fsync_directory(activation_store.root)
    assert observed == [
        (activation_store.root, os.O_RDONLY),
        "fsync-directory",
        ("close", 777),
    ]


def test_state_change_before_promote_or_rollback_is_rejected(
    activation_store: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, second, third = activation_store.packages
    first_pin = _promote_first(activation_store)

    original = staging_activation._read_expected_state
    promote_calls = 0

    def changed_promote(*args: object, **kwargs: object) -> Any:
        nonlocal promote_calls
        promote_calls += 1
        state, raw = original(*args, **kwargs)  # type: ignore[arg-type]
        if promote_calls == 2:
            return staging_activation._ActivationPointer(third.manifest_sha256, None), raw
        return state, raw

    with monkeypatch.context() as context:
        context.setattr(staging_activation, "_read_expected_state", changed_promote)
        _fixed_failure(
            lambda: staging_activation.promote_staging_generation(
                activation_store.root, second.manifest_sha256, first_pin
            )
        )
    assert promote_calls == 2

    second_pin = staging_activation.promote_staging_generation(
        activation_store.root, second.manifest_sha256, first_pin
    )
    rollback_calls = 0

    def changed_rollback(*args: object, **kwargs: object) -> Any:
        nonlocal rollback_calls
        rollback_calls += 1
        state, raw = original(*args, **kwargs)  # type: ignore[arg-type]
        if rollback_calls == 2:
            return staging_activation._ActivationPointer(third.manifest_sha256, None), raw
        return state, raw

    monkeypatch.setattr(staging_activation, "_read_expected_state", changed_rollback)
    _fixed_failure(
        lambda: staging_activation.rollback_staging_generation(activation_store.root, second_pin)
    )
    assert rollback_calls == 2


def test_operator_runner_routes_actions_and_prints_no_values(
    activation_store: SimpleNamespace,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first, second = activation_store.packages[:2]
    first_pin = manage_staging_activation.run_action(
        activation_store.root,
        "promote",
        staging_activation.ABSENT_ACTIVATION_SHA256,
        first.manifest_sha256,
    )
    loaded = manage_staging_activation.run_action(activation_store.root, "load", first_pin)
    assert loaded.current_manifest_sha256 == first.manifest_sha256
    second_pin = manage_staging_activation.run_action(
        activation_store.root, "promote", first_pin, second.manifest_sha256
    )
    rollback_pin = manage_staging_activation.run_action(
        activation_store.root, "rollback", second_pin
    )
    assert isinstance(rollback_pin, str)
    for action, candidate in (("bad", None), ("load", "x"), ("promote", None)):
        with pytest.raises(ValueError):
            manage_staging_activation.run_action(
                activation_store.root, action, rollback_pin, candidate
            )

    monkeypatch.setenv(manage_staging_activation._ROOT_ENV, str(activation_store.root))
    monkeypatch.setenv(manage_staging_activation._ACTION_ENV, "load")
    monkeypatch.setenv(manage_staging_activation._PIN_ENV, rollback_pin)
    monkeypatch.delenv(manage_staging_activation._CANDIDATE_ENV, raising=False)
    monkeypatch.setattr(sys, "argv", ["manage_staging_activation.py"])
    assert manage_staging_activation.main() == 0
    assert capsys.readouterr() == ("VALUE_FREE_RESULT: ACCEPTED\n", "")
    sensitive = "never-print-this"
    monkeypatch.setenv(manage_staging_activation._PIN_ENV, sensitive)
    assert manage_staging_activation.main() == 1
    assert capsys.readouterr() == ("VALUE_FREE_RESULT: REJECTED\n", "")
    monkeypatch.setattr(sys, "argv", ["manage_staging_activation.py", sensitive])
    assert manage_staging_activation.main() == 1
    assert capsys.readouterr() == ("VALUE_FREE_RESULT: REJECTED\n", "")

    def ambiguous(*_args: object, **_kwargs: object) -> object:
        raise staging_activation.StagingActivationOutcomeAmbiguous(sensitive)

    monkeypatch.setattr(manage_staging_activation, "run_action", ambiguous)
    monkeypatch.setattr(sys, "argv", ["manage_staging_activation.py"])
    assert manage_staging_activation.main() == 2
    assert capsys.readouterr() == ("VALUE_FREE_RESULT: AMBIGUOUS\n", "")


def test_operator_runner_module_guard_is_value_free(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "argv", ["manage_staging_activation.py"])
    with pytest.raises(SystemExit, match="1"):
        runpy.run_path(manage_staging_activation.__file__, run_name="__main__")
    assert capsys.readouterr() == ("VALUE_FREE_RESULT: REJECTED\n", "")
