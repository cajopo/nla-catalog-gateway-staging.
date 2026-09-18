"""Native Linux failure boundaries; other hosts do not exercise these tests.

Real descriptors and files are used throughout. Fault injection is confined to
individual failing syscalls or short I/O, never a substitute filesystem backend.
"""

from __future__ import annotations

import hashlib
import os
import sys
from contextlib import ExitStack, contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts import reconcile_split_snapshot as cli


@pytest.fixture
def linux_root(tmp_path: Path):
    if sys.platform != "linux":
        yield None
        return
    before = len(os.listdir("/proc/self/fd"))
    yield tmp_path
    assert len(os.listdir("/proc/self/fd")) == before


def _input(root: Path):
    path = root / "input.json"
    path.write_bytes(b"synthetic-input")
    return cli._linux_regular_file(path, "test input", external=True)


@pytest.mark.parametrize(
    "kind",
    [
        "string",
        "relative",
        "double-root",
        "parent",
        "colon",
        "trailing-dot",
        "trailing-space",
        "repository",
        "repository-child",
        "unavailable",
    ],
)
def test_linux_path_rejects_unsafe_namespace(linux_root, monkeypatch, kind):
    if linux_root is None:
        return
    paths = {
        "string": str(linux_root),
        "relative": Path("relative"),
        "double-root": Path("//double-root"),
        "parent": linux_root / ".." / "escape",
        "colon": linux_root / "name:stream",
        "trailing-dot": linux_root / "name.",
        "trailing-space": linux_root / "name ",
        "repository": cli.REPOSITORY_ROOT,
        "repository-child": cli.REPOSITORY_ROOT / "snapshot.jsonl",
        "unavailable": linux_root,
    }
    if kind == "unavailable":
        monkeypatch.setattr(cli, "_LINUX_HANDLE_API_AVAILABLE", False)
    with pytest.raises(cli.ReconciliationCliError, match="filesystem path is invalid"):
        cli._linux_path(paths[kind], external=True)


def test_linux_directory_walk_accepts_root_and_rejects_symlink_ancestor(linux_root):
    if linux_root is None:
        return
    assert cli._linux_path(cli.REPOSITORY_ROOT, external=False) == cli.REPOSITORY_ROOT
    with cli._linux_directory(Path("/"), external=False) as descriptor:
        assert os.fstat(descriptor).st_ino == Path("/").stat().st_ino
    nested = linux_root / "real" / "nested"
    nested.mkdir(parents=True)
    with cli._linux_directory(nested, external=True) as descriptor:
        assert os.fstat(descriptor).st_ino == nested.stat().st_ino
    (linux_root / "alias").symlink_to(nested.parent, target_is_directory=True)
    with pytest.raises(OSError):
        with cli._linux_directory(linux_root / "alias" / "nested", external=True):
            pytest.fail("symlink ancestor was accepted")
    with pytest.raises(OSError):
        with cli._linux_directory(nested / "missing", external=True):
            pytest.fail("missing directory was accepted")


@pytest.mark.parametrize("kind", ["directory", "symlink", "hardlink", "fifo", "missing", "nul"])
def test_linux_regular_file_rejects_nonexclusive_or_invalid_input(linux_root, kind):
    if linux_root is None:
        return
    path = linux_root / "input"
    if kind == "directory":
        path.mkdir()
    elif kind == "symlink":
        target = linux_root / "target"
        target.write_bytes(b"original")
        path.symlink_to(target)
    elif kind == "hardlink":
        path.write_bytes(b"original")
        os.link(path, linux_root / "alias")
    elif kind == "fifo":
        os.mkfifo(path, 0o600)
    elif kind == "nul":
        path = linux_root / "nul\x00name"
    with pytest.raises(cli.ReconciliationCliError, match="cannot be verified safely"):
        cli._linux_regular_file(path, "test input", external=True)


@pytest.mark.parametrize("freeze", [None, 15, 64])
def test_linux_pin_preserves_exact_bytes_and_closes_handle(linux_root, freeze):
    if linux_root is None:
        return
    path, state = _input(linux_root)
    with ExitStack() as stack:
        pinned = cli._linux_pin_regular_file(
            path, state, "test input", stack, freeze_maximum=freeze, external=True
        )
        cli._linux_verify_pinned_input(pinned)
        assert pinned.state == state
        if freeze is None:
            assert pinned.frozen_bytes is None
            assert pinned.handle.read() == b"synthetic-input"
        else:
            assert pinned.frozen_bytes == b"synthetic-input"
        handle = pinned.handle
    assert handle.closed


@pytest.mark.parametrize("kind", ["unattested", "changed", "other-handle", "closed", "missing"])
def test_linux_verify_pinned_input_rejects_changed_attestation(linux_root, kind):
    if linux_root is None:
        return
    path, state = _input(linux_root)
    with ExitStack() as stack:
        pinned = cli._linux_pin_regular_file(
            path, state, "test input", stack, freeze_maximum=None, external=True
        )
        if kind == "unattested":
            pinned = replace(pinned, state=replace(state, linux_state=None))
        elif kind == "changed":
            path.write_bytes(b"different-size")
        elif kind == "other-handle":
            other = linux_root / "other"
            other.write_bytes(b"synthetic-input")
            pinned = replace(pinned, handle=stack.enter_context(other.open("rb")))
        elif kind == "closed":
            pinned.handle.close()
        else:
            path.unlink()
        with pytest.raises(cli.ReconciliationCliError, match="identity cannot be verified"):
            cli._linux_verify_pinned_input(pinned)


@pytest.mark.parametrize(
    "kind", ["zero-bound", "negative-bound", "small-bound", "missing", "stale"]
)
def test_linux_pin_rejects_bad_bounds_and_stale_state(linux_root, kind):
    if linux_root is None:
        return
    path, state = _input(linux_root)
    maximum = {"zero-bound": 0, "negative-bound": -1, "small-bound": 1}.get(kind)
    if kind == "missing":
        path.unlink()
    elif kind == "stale":
        state = replace(state, byte_count=state.byte_count + 1)
    with ExitStack() as stack:
        with pytest.raises(cli.ReconciliationCliError, match="cannot be pinned safely"):
            cli._linux_pin_regular_file(
                path, state, "test input", stack, freeze_maximum=maximum, external=True
            )


def test_linux_pin_rejects_short_snapshot_read(linux_root, monkeypatch):
    if linux_root is None:
        return
    path, state = _input(linux_root)
    real_fdopen = os.fdopen

    @contextmanager
    def short_reader(*args, **kwargs):
        with real_fdopen(*args, **kwargs) as handle:
            yield SimpleNamespace(fileno=handle.fileno, read=lambda bound: handle.read(bound)[:-1])

    monkeypatch.setattr(cli.os, "fdopen", short_reader)
    with ExitStack() as stack:
        with pytest.raises(cli.ReconciliationCliError, match="cannot be pinned safely") as error:
            cli._linux_pin_regular_file(
                path, state, "test input", stack, freeze_maximum=64, external=True
            )
    assert "snapshot is incomplete" in str(error.value.__cause__)


@pytest.mark.parametrize("kind", ["absent", "existing", "missing-source"])
def test_linux_rename_is_atomic_and_never_replaces_target(linux_root, kind):
    if linux_root is None:
        return
    source = linux_root / "source"
    target = linux_root / "target"
    source.mkdir()
    (source / "source.txt").write_bytes(b"source")
    if kind == "existing":
        target.mkdir()
        (target / "target.txt").write_bytes(b"target")
    with cli._linux_directory(linux_root, external=True) as descriptor:
        if kind == "absent":
            cli._linux_rename_noreplace(descriptor, source.name, target.name)
            assert not source.exists()
            assert (target / "source.txt").read_bytes() == b"source"
        else:
            name = "missing" if kind == "missing-source" else source.name
            with pytest.raises(cli.ReconciliationCliError, match="cannot be published atomically"):
                cli._linux_rename_noreplace(descriptor, name, target.name)
            assert (source / "source.txt").read_bytes() == b"source"
            if kind == "existing":
                assert (target / "target.txt").read_bytes() == b"target"
                assert not (target / "source.txt").exists()
            else:
                assert not target.exists()


@pytest.mark.parametrize("kind", ["missing-symbol", "loader-error"])
def test_linux_rename_fails_closed_when_atomic_primitive_unavailable(linux_root, monkeypatch, kind):
    if linux_root is None:
        return

    def unavailable(*_args, **_kwargs):
        if kind == "loader-error":
            raise OSError("synthetic unavailable libc")
        return SimpleNamespace()

    monkeypatch.setattr(cli.ctypes, "CDLL", unavailable)
    with cli._linux_directory(linux_root, external=True) as descriptor:
        with pytest.raises(cli.ReconciliationCliError, match="cannot be published atomically"):
            cli._linux_rename_noreplace(descriptor, "source", "target")
    assert not tuple(linux_root.iterdir())


@pytest.mark.parametrize("filename", ["catalog-records.v1.jsonl", "other.json"])
@pytest.mark.parametrize("chunks", [(), (b"one\n", b"two\n")])
def test_linux_write_artifact_seals_and_attests_exact_bytes(linux_root, filename, chunks):
    if linux_root is None:
        return
    path = linux_root / filename
    created = []
    with cli._linux_directory(linux_root, external=True) as descriptor:
        evidence = cli._linux_write_artifact(descriptor, path, chunks, created)
    expected = b"".join(chunks)
    assert path.read_bytes() == expected
    assert path.stat().st_mode & 0o777 == 0o444
    assert evidence == cli._ArtifactEvidence(
        filename, hashlib.sha256(expected).hexdigest(), len(expected), len(chunks)
    )
    assert len(created) == 1
    assert created[0].expected_byte_count == len(expected)
    assert created[0].expected_sha256 == evidence.sha256
    assert created[0].linux_state == cli._linux_state(path.stat())


def test_linux_write_artifact_preserves_existing_file(linux_root):
    if linux_root is None:
        return
    path = linux_root / "artifact.json"
    path.write_bytes(b"existing")
    created = []
    with cli._linux_directory(linux_root, external=True) as descriptor:
        with pytest.raises(FileExistsError):
            cli._linux_write_artifact(descriptor, path, (b"replacement",), created)
    assert path.read_bytes() == b"existing"
    assert not created


def test_linux_write_artifact_rejects_oversize_record(linux_root):
    if linux_root is None:
        return
    path = linux_root / "catalog-records.v1.jsonl"
    created = []
    with cli._linux_directory(linux_root, external=True) as descriptor:
        with pytest.raises(cli.ReconciliationCliError, match="exceeds the runtime byte limit"):
            cli._linux_write_artifact(
                descriptor, path, (b"x" * (cli.runtime_contract.MAX_CONTRACT_BYTES + 2),), created
            )
    assert path.read_bytes() == b""
    assert len(created) == 1
    assert created[0].expected_sha256 is None


def test_linux_write_artifact_rejects_short_write(linux_root, monkeypatch):
    if linux_root is None:
        return
    real_fdopen = os.fdopen

    @contextmanager
    def short_writer(*args, **kwargs):
        with real_fdopen(*args, **kwargs) as handle:
            yield SimpleNamespace(write=lambda raw: handle.write(raw[:-1]))

    monkeypatch.setattr(cli.os, "fdopen", short_writer)
    path = linux_root / "artifact.json"
    created = []
    with cli._linux_directory(linux_root, external=True) as descriptor:
        with pytest.raises(cli.ReconciliationCliError, match="write was incomplete"):
            cli._linux_write_artifact(descriptor, path, (b"complete",), created)
    assert path.read_bytes() == b"complet"
    assert len(created) == 1
    assert created[0].expected_sha256 is None


@pytest.mark.parametrize("operation", ["fstat", "fdopen", "fchmod", "fsync"])
def test_linux_write_artifact_closes_descriptor_when_syscall_fails(
    linux_root, monkeypatch, operation
):
    if linux_root is None:
        return
    path = linux_root / "artifact.json"
    created = []

    def fail(*_args, **_kwargs):
        raise OSError("synthetic output failure")

    with cli._linux_directory(linux_root, external=True) as descriptor:
        with monkeypatch.context() as patch:
            patch.setattr(cli.os, operation, fail)
            with pytest.raises(OSError, match="synthetic output failure"):
                cli._linux_write_artifact(descriptor, path, (b"data",), created)
    assert path.is_file()
    assert len(created) == (0 if operation == "fstat" else 1)
    assert not created or created[0].expected_sha256 is None
