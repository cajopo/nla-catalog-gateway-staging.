"""Native Linux filesystem coverage; run this module in the Ubuntu CI jobs.

Other hosts return without claiming Linux coverage. No portable test backend is
installed: all successful opens and all rejected filesystem changes are real.
"""

from __future__ import annotations

import os
import shutil
import sys
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path

import pytest

import test_generation_bundle as bundles
from nla_catalog_gateway import generation_bundle


def _seal(directory: Path) -> None:
    for path in directory.iterdir():
        path.chmod(0o444)
    directory.chmod(0o555)


def _restore_permissions(directory: Path) -> None:
    for root, _directories, files in os.walk(directory, followlinks=False):
        Path(root).chmod(0o755)
        for name in files:
            path = Path(root) / name
            if not path.is_symlink():
                path.chmod(0o644)


@pytest.fixture
def linux_bundle(tmp_path: Path):
    if sys.platform != "linux":
        yield None
        return
    case = bundles._write_bundle(tmp_path / "generation", bundles._base_records())
    _seal(case.directory)
    try:
        yield case
    finally:
        _restore_permissions(tmp_path)


def _fd_count() -> int:
    return len(os.listdir("/proc/self/fd"))


def _reject(case, *, directory=None, pin=None) -> None:
    before = _fd_count()
    with pytest.raises(generation_bundle.GenerationBundleError) as error:
        with generation_bundle.open_reconciled_generation(
            case.directory if directory is None else directory,
            case.summary_sha256 if pin is None else pin,
        ):
            pytest.fail("unsafe native Linux bundle was accepted")
    assert str(error.value) in {
        bundles.TRUST_ERROR,
        bundles.FILESYSTEM_ERROR,
        bundles.SHAPE_ERROR,
        bundles.CONTENT_ERROR,
        bundles.CHANGED_ERROR,
    }
    assert _fd_count() == before


def test_native_linux_round_trip_and_descriptor_cleanup(linux_bundle) -> None:
    if linux_bundle is None:
        return
    case = linux_bundle
    assert type(generation_bundle._filesystem_backend()).__name__ == "_LinuxFilesystemBackend"
    before = _fd_count()
    with generation_bundle.open_reconciled_generation(
        case.directory, case.summary_sha256
    ) as verified:
        assert verified.generation.records == case.records
        assert verified.summary_sha256 == case.summary_sha256
        assert _fd_count() > before
    assert _fd_count() == before


@pytest.mark.parametrize("pin", ["f" * 64, "not-a-digest"])
def test_native_linux_rejects_wrong_external_pin(linux_bundle, pin) -> None:
    if linux_bundle is None:
        return
    _reject(linux_bundle, pin=pin)


@pytest.mark.parametrize("unsafe", ["extra", "missing", "writable-file", "writable-directory"])
def test_native_linux_rejects_shape_and_write_permissions(linux_bundle, unsafe) -> None:
    if linux_bundle is None:
        return
    case = linux_bundle
    victim = case.directory / bundles.CATALOG_NAME
    case.directory.chmod(0o755)
    if unsafe == "extra":
        (case.directory / "unexpected").write_bytes(b"private-test-data")
    elif unsafe == "missing":
        victim.unlink()
    elif unsafe == "writable-file":
        victim.chmod(0o644)
    if unsafe != "writable-directory":
        case.directory.chmod(0o555)
    _reject(case)


@pytest.mark.parametrize(
    "alias", ["file-symlink", "directory-symlink", "ancestor-symlink", "hardlink"]
)
def test_native_linux_rejects_real_links(linux_bundle, tmp_path: Path, alias) -> None:
    if linux_bundle is None:
        return
    case = linux_bundle
    victim = case.directory / bundles.CATALOG_NAME
    selected = case.directory
    if alias == "file-symlink":
        case.directory.chmod(0o755)
        target = tmp_path / "real-catalog"
        victim.rename(target)
        victim.symlink_to(target)
        case.directory.chmod(0o555)
    elif alias == "hardlink":
        os.link(victim, tmp_path / "catalog-alias")
    else:
        target = case.directory if alias == "directory-symlink" else tmp_path
        link = tmp_path / "alias"
        link.symlink_to(target, target_is_directory=True)
        selected = link if alias == "directory-symlink" else link / case.directory.name
    _reject(case, directory=selected)


@pytest.mark.parametrize("raced", [False, True])
def test_native_linux_rejects_fifo_without_blocking(linux_bundle, monkeypatch, raced) -> None:
    if linux_bundle is None:
        return
    case = linux_bundle
    victim = case.directory / bundles.CATALOG_NAME

    def replace_with_fifo():
        case.directory.chmod(0o755)
        victim.unlink()
        os.mkfifo(victim, 0o444)
        case.directory.chmod(0o555)

    if not raced:
        replace_with_fifo()
    original_open = os.open
    seen_flags = []

    def guarded_open(path, flags, *args, **kwargs):
        # Check the safety flag before entering the real potentially blocking call.
        if os.fspath(path) in {bundles.CATALOG_NAME, os.fspath(victim)}:
            seen_flags.append(flags)
            assert flags & os.O_NONBLOCK
            if raced:
                replace_with_fifo()
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(generation_bundle.os, "open", guarded_open)
    _reject(case)
    if raced:
        assert len(seen_flags) == 1
        assert seen_flags[0] & os.O_NONBLOCK


def test_native_linux_rejects_repository_bundle(linux_bundle, monkeypatch) -> None:
    if linux_bundle is None:
        return
    monkeypatch.setattr(generation_bundle, "REPOSITORY_ROOT", linux_bundle.directory.parent)
    _reject(linux_bundle)


@pytest.mark.parametrize("change", ["bytes", "restored-mtime", "replace-file", "replace-directory"])
def test_native_linux_rejects_changes_during_verification(
    linux_bundle, monkeypatch, change
) -> None:
    if linux_bundle is None:
        return
    case = linux_bundle
    original_scan = generation_bundle._scan_pinned_file
    changed = False

    def scan_then_change(artifact):
        nonlocal changed
        result = original_scan(artifact)
        if changed:
            return result
        changed = True
        path = artifact.path
        original_stat = path.stat()
        raw = path.read_bytes()
        if change == "replace-directory":
            retained = case.directory.with_name("replaced-generation")
            case.directory.rename(retained)
            shutil.copytree(retained, case.directory)
            _seal(case.directory)
        elif change == "replace-file":
            replacement = case.directory.parent / "replacement"
            replacement.write_bytes(raw)
            replacement.chmod(0o444)
            os.utime(replacement, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
            case.directory.chmod(0o755)
            os.replace(replacement, path)
            case.directory.chmod(0o555)
        else:
            path.chmod(0o644)
            path.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
            if change == "restored-mtime":
                path.write_bytes(raw)
            path.chmod(0o444)
            os.utime(path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
            if change == "restored-mtime":
                assert path.stat().st_ctime_ns != original_stat.st_ctime_ns
        return result

    monkeypatch.setattr(generation_bundle, "_scan_pinned_file", scan_then_change)
    _reject(case)
    assert changed


@pytest.mark.parametrize("during", ["scan", "fdopen", "consumer"])
def test_native_linux_closes_descriptors_after_exception(linux_bundle, monkeypatch, during) -> None:
    if linux_bundle is None:
        return
    case = linux_bundle
    before = _fd_count()
    if during in {"scan", "fdopen"}:

        def fail_scan(*_args, **_kwargs):
            raise OSError("private path must not escape")

        if during == "scan":
            monkeypatch.setattr(generation_bundle, "_scan_pinned_file", fail_scan)
        else:
            monkeypatch.setattr(generation_bundle.os, "fdopen", fail_scan)
        _reject(case)
    else:
        with pytest.raises(RuntimeError, match="consumer failed"):
            with generation_bundle.open_reconciled_generation(case.directory, case.summary_sha256):
                raise RuntimeError("consumer failed")
    assert _fd_count() == before


@pytest.mark.parametrize("kind", ["directory", "artifact"])
def test_native_linux_interrupt_after_open_closes_owned_descriptor(linux_bundle, kind) -> None:
    if linux_bundle is None:
        return
    path = linux_bundle.directory
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
    if kind == "directory":
        flags |= os.O_DIRECTORY
    else:
        path /= bundles.CATALOG_NAME
        flags |= os.O_NONBLOCK
    before = _fd_count()
    interruption = KeyboardInterrupt("synthetic ownership interruption")
    # Stop after the native open assigned its result, before the caller receives it.
    with bundles._interrupt_on_line(
        generation_bundle._linux_descriptor.__wrapped__, "yield descriptor", interruption
    ):
        with pytest.raises(KeyboardInterrupt) as error:
            with generation_bundle._linux_descriptor(os.fspath(path), flags):
                pytest.fail("ownership interruption was not delivered")
    assert error.value is interruption
    assert _fd_count() == before


@pytest.mark.parametrize("race", ["replace-before-open", "reuse-open-identity"])
def test_native_linux_rejects_open_identity_races(linux_bundle, monkeypatch, race) -> None:
    if linux_bundle is None:
        return
    case = linux_bundle
    selected = next(iter(generation_bundle._ARTIFACT_FILENAMES))
    path = case.directory / selected
    fired = False
    original_open = os.open
    original_stat = os.stat

    def replace_artifact():
        nonlocal fired
        fired = True
        case.directory.chmod(0o755)
        if race == "reuse-open-identity":
            os.replace(case.directory / bundles.SUMMARY_NAME, path)
        else:
            replacement = case.directory.parent / "before-open-replacement"
            replacement.write_bytes(path.read_bytes())
            replacement.chmod(0o444)
            os.replace(replacement, path)
        case.directory.chmod(0o555)

    def open_after_replace(name, flags, *args, **kwargs):
        if name == selected and not fired:
            replace_artifact()
        return original_open(name, flags, *args, **kwargs)

    def stat_after_move(name, *args, **kwargs):
        if name == selected and kwargs.get("dir_fd") is not None and not fired:
            replace_artifact()
        return original_stat(name, *args, **kwargs)

    if race == "replace-before-open":
        monkeypatch.setattr(generation_bundle.os, "open", open_after_replace)
    else:
        monkeypatch.setattr(generation_bundle.os, "stat", stat_after_move)
    _reject(case)
    assert fired


@pytest.mark.parametrize(
    "invalid",
    ["bundle-state", "file-set", "artifact-state", "directory-fd", "artifact-fd", "changed-file"],
)
def test_native_linux_revalidation_rejects_inconsistent_pinned_state(linux_bundle, invalid) -> None:
    if linux_bundle is None:
        return
    case = linux_bundle
    backend = generation_bundle._filesystem_backend()
    before = _fd_count()
    with backend.open(case.directory) as pinned, ExitStack() as stack:
        candidate = pinned
        if invalid == "bundle-state":
            candidate = replace(pinned, linux_state=None)
        elif invalid == "file-set":
            candidate = replace(pinned, files={})
        elif invalid == "directory-fd":
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            descriptor = stack.enter_context(
                generation_bundle._linux_descriptor(os.fspath(case.directory.parent), flags)
            )
            candidate = replace(pinned, directory_handle=descriptor)
        else:
            files = dict(pinned.files)
            artifact = files[bundles.CATALOG_NAME]
            if invalid == "artifact-state":
                files[bundles.CATALOG_NAME] = replace(artifact, linux_state=None)
                candidate = replace(pinned, files=files)
            elif invalid == "artifact-fd":
                # A real descriptor for a different inode cannot attest this artifact.
                other = stack.enter_context((case.directory / bundles.SUMMARY_NAME).open("rb"))
                files[bundles.CATALOG_NAME] = replace(artifact, handle=other)
                candidate = replace(pinned, files=files)
            else:
                artifact.path.chmod(0o644)
        with pytest.raises(generation_bundle.GenerationBundleError) as error:
            backend.verify(candidate)
        assert str(error.value) in {bundles.SHAPE_ERROR, bundles.CHANGED_ERROR}
    assert _fd_count() == before


@pytest.mark.parametrize("boundary", ["relative", "parent", "repository-root", "unavailable"])
def test_native_linux_directory_boundary_fails_closed(linux_bundle, monkeypatch, boundary) -> None:
    if linux_bundle is None:
        return
    case = linux_bundle
    selected = case.directory
    if boundary == "relative":
        selected = Path("generation")
    elif boundary == "parent":
        selected = case.directory / ".." / case.directory.name
    elif boundary == "repository-root":
        monkeypatch.setattr(generation_bundle, "REPOSITORY_ROOT", case.directory)
    else:
        monkeypatch.setattr(generation_bundle, "_LINUX_HANDLE_API_AVAILABLE", False)
    before = _fd_count()
    with pytest.raises(generation_bundle.GenerationBundleError) as error:
        with generation_bundle._linux_directory(selected):
            pytest.fail("invalid directory boundary was accepted")
    assert str(error.value) == bundles.FILESYSTEM_ERROR
    assert _fd_count() == before
