from __future__ import annotations

import hashlib
import json
import os
import pickle
import runpy
import stat
import subprocess
import sys
from contextlib import ExitStack, contextmanager
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from scripts import package_staging_generation, prove_real_catalog_cores

import test_core_evidence as evidence_helpers
import test_generation_bundle as bundle_helpers
from nla_catalog_gateway import core_evidence, staging_generation
from nla_catalog_gateway.pagination import build_catalog_projection

ERROR = "staging generation verification failed"
CODE_SHA = "c" * 40


def _assert_fixed_error(call: Any) -> None:
    with pytest.raises(staging_generation.StagingGenerationError) as captured:
        call()
    assert str(captured.value) == ERROR
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


def _measurements() -> core_evidence._OperationalMeasurements:
    return core_evidence._OperationalMeasurements(
        projection_build_nanoseconds=1,
        pagination_traversal_nanoseconds=2,
        search_query_nanoseconds=3,
        facet_evaluation_nanoseconds=4,
        sync_bootstrap_nanoseconds=5,
        pagination_page_count=6,
        search_query_count=7,
        facet_evaluation_count=8,
    )


def _make_package(root: Path) -> SimpleNamespace:
    package = (root / "portable-generation").resolve()
    package.mkdir()
    verified = evidence_helpers._verified()
    projection = build_catalog_projection(
        package / staging_generation.PROJECTION_FILENAME,
        manifest=verified.generation.dataset_manifest,
        records=verified.generation.records,
    )
    evidence = core_evidence._new_evidence(
        shop_domain=bundle_helpers.SHOP,
        summary_sha256=evidence_helpers.SUMMARY_SHA,
        dataset_generation=projection.dataset_generation,
        catalog_content_sha256=projection.manifest.catalog_content_sha256,
        projection_fingerprint=projection._file_fingerprint.content_sha256,
        code_sha=CODE_SHA,
    )
    result = core_evidence._VerificationResult(evidence, _measurements())
    report_raw = prove_real_catalog_cores._report_bytes(result)
    package_staging_generation._write_bytes(
        package / staging_generation.EVIDENCE_FILENAME, report_raw
    )
    manifest_raw = package_staging_generation._manifest_bytes(package)
    package_staging_generation._write_bytes(
        package / staging_generation.MANIFEST_FILENAME, manifest_raw
    )
    package.chmod(package_staging_generation._READ_ONLY_DIRECTORY_MODE)
    return SimpleNamespace(
        directory=package,
        manifest_sha256=hashlib.sha256(manifest_raw).hexdigest(),
        records=verified.generation.records,
        evidence=evidence,
    )


@pytest.fixture
def package_case(tmp_path: Path) -> SimpleNamespace:
    return _make_package(tmp_path)


def _make_writable(path: Path) -> None:
    path.chmod(stat.S_IMODE(path.stat().st_mode) | stat.S_IWUSR)


def _rewrite_manifest(package: Path, value: object, *, canonical: bool = True) -> str:
    manifest = package / staging_generation.MANIFEST_FILENAME
    _make_writable(package)
    _make_writable(manifest)
    raw = (
        package_staging_generation._canonical_json_bytes(value)
        if canonical
        else json.dumps(value, sort_keys=True).encode()
    )
    manifest.write_bytes(raw)
    manifest.chmod(package_staging_generation._READ_ONLY_FILE_MODE)
    package.chmod(package_staging_generation._READ_ONLY_DIRECTORY_MODE)
    return hashlib.sha256(raw).hexdigest()


def _refresh_manifest(package: Path) -> str:
    current = json.loads((package / staging_generation.MANIFEST_FILENAME).read_bytes())
    current["artifacts"] = [
        package_staging_generation._artifact(package / filename)
        for filename in staging_generation.ARTIFACT_FILENAMES
    ]
    return _rewrite_manifest(package, current)


def _rewrite_report(package: Path, value: object, *, canonical: bool = True) -> str:
    report = package / staging_generation.EVIDENCE_FILENAME
    _make_writable(package)
    _make_writable(report)
    raw = (
        package_staging_generation._canonical_json_bytes(value)
        if canonical
        else json.dumps(value, sort_keys=True).encode()
    )
    report.write_bytes(raw)
    report.chmod(package_staging_generation._READ_ONLY_FILE_MODE)
    return _refresh_manifest(package)


def test_portable_package_round_trip_is_opaque_and_runtime_ready(
    package_case: SimpleNamespace,
) -> None:
    opened = staging_generation.open_staging_generation(
        package_case.directory, package_case.manifest_sha256
    )
    assert opened.records == package_case.records
    assert opened.manifest_sha256 == package_case.manifest_sha256
    assert opened.projection.dataset_generation == opened.evidence.dataset_generation
    assert opened.projection.manifest.catalog_content_sha256 == (
        opened.evidence.catalog_content_sha256
    )
    assert opened.evidence.shop_domain == bundle_helpers.SHOP
    assert opened.evidence.code_sha == CODE_SHA
    assert "myshopify" not in repr(opened)
    with pytest.raises(staging_generation.StagingGenerationError, match=ERROR):
        staging_generation.VerifiedStagingGenerationV1()
    with pytest.raises(staging_generation.StagingGenerationError, match=ERROR):
        pickle.dumps(opened)
    with pytest.raises(staging_generation.StagingGenerationError, match=ERROR):
        opened.__reduce__()
    with pytest.raises(FrozenInstanceError):
        opened.manifest_sha256 = "0" * 64


def test_manifest_is_minimal_canonical_and_contains_no_catalog_values(
    package_case: SimpleNamespace,
) -> None:
    raw = (package_case.directory / staging_generation.MANIFEST_FILENAME).read_bytes()
    value = json.loads(raw)
    assert package_staging_generation._canonical_json_bytes(value) == raw
    assert frozenset(value) == frozenset({"artifacts", "packageFormat", "schemaVersion"})
    text = raw.decode()
    assert bundle_helpers.SHOP not in text
    assert "gid://shopify" not in text
    assert str(package_case.directory) not in text
    assert tuple(item["filename"] for item in value["artifacts"]) == (
        staging_generation.EVIDENCE_FILENAME,
        staging_generation.PROJECTION_FILENAME,
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update({"unknown": True}),
        lambda value: value.update(schemaVersion=True),
        lambda value: value.update(schemaVersion=2),
        lambda value: value.update(packageFormat="wrong"),
        lambda value: value.update(artifacts=[]),
        lambda value: value["artifacts"].reverse(),
        lambda value: value["artifacts"][0].update({"unknown": 1}),
        lambda value: value["artifacts"][0].update(bytes=0),
        lambda value: value["artifacts"][0].update(bytes=2**63),
        lambda value: value["artifacts"][0].update(bytes=65 * 1024),
        lambda value: value["artifacts"][0].update(sha256="A" * 64),
    ],
)
def test_manifest_shape_and_bounds_fail_closed(
    package_case: SimpleNamespace,
    mutation: Any,
) -> None:
    manifest = json.loads(
        (package_case.directory / staging_generation.MANIFEST_FILENAME).read_bytes()
    )
    mutation(manifest)
    digest = _rewrite_manifest(package_case.directory, manifest)
    _assert_fixed_error(
        lambda: staging_generation.open_staging_generation(package_case.directory, digest)
    )


def test_manifest_rejects_noncanonical_duplicate_truncated_and_wrong_pin(
    package_case: SimpleNamespace,
) -> None:
    manifest_path = package_case.directory / staging_generation.MANIFEST_FILENAME
    value = json.loads(manifest_path.read_bytes())
    noncanonical_digest = _rewrite_manifest(package_case.directory, value, canonical=False)
    _assert_fixed_error(
        lambda: staging_generation.open_staging_generation(
            package_case.directory, noncanonical_digest
        )
    )
    duplicate = b'{"artifacts":[],"artifacts":[],"packageFormat":"x","schemaVersion":1}'
    _make_writable(package_case.directory)
    _make_writable(manifest_path)
    manifest_path.write_bytes(duplicate)
    manifest_path.chmod(package_staging_generation._READ_ONLY_FILE_MODE)
    package_case.directory.chmod(package_staging_generation._READ_ONLY_DIRECTORY_MODE)
    _assert_fixed_error(
        lambda: staging_generation.open_staging_generation(
            package_case.directory, hashlib.sha256(duplicate).hexdigest()
        )
    )
    _assert_fixed_error(
        lambda: staging_generation.open_staging_generation(package_case.directory, "0" * 64)
    )
    _assert_fixed_error(
        lambda: staging_generation.open_staging_generation(package_case.directory, "bad")
    )


def test_manifest_valid_digest_mismatch_reaches_artifact_cross_check(
    package_case: SimpleNamespace,
) -> None:
    manifest = json.loads(
        (package_case.directory / staging_generation.MANIFEST_FILENAME).read_bytes()
    )
    manifest["artifacts"][0]["sha256"] = "0" * 64
    digest = _rewrite_manifest(package_case.directory, manifest)
    _assert_fixed_error(
        lambda: staging_generation.open_staging_generation(package_case.directory, digest)
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update({"unknown": True}),
        lambda value: value.update(schemaVersion=True),
        lambda value: value.update(schemaVersion=1),
        lambda value: value.update(result="REJECTED"),
        lambda value: value["bindings"].update({"unknown": "x"}),
        lambda value: value["bindings"].update(shopDomain="bad"),
        lambda value: value["bindings"].update(summarySha256="A" * 64),
        lambda value: value["bindings"].update(datasetGeneration="bad"),
        lambda value: value["bindings"].update(catalogContentSha256="bad"),
        lambda value: value["bindings"].update(projectionFingerprint="bad"),
        lambda value: value["bindings"].update(codeSha="bad"),
        lambda value: value.update(durationNanoseconds={}),
        lambda value: value["durationNanoseconds"].update(searchQuery=-1),
        lambda value: value.update(operationCounts={}),
        lambda value: value["operationCounts"].update(paginationPages=-1),
        lambda value: value["operationCounts"].update(syncBootstraps=0),
    ],
)
def test_evidence_report_shape_and_bindings_fail_closed(
    package_case: SimpleNamespace,
    mutation: Any,
) -> None:
    report = json.loads(
        (package_case.directory / staging_generation.EVIDENCE_FILENAME).read_bytes()
    )
    mutation(report)
    digest = _rewrite_report(package_case.directory, report)
    _assert_fixed_error(
        lambda: staging_generation.open_staging_generation(package_case.directory, digest)
    )


def test_report_rejects_noncanonical_and_truncated_content(package_case: SimpleNamespace) -> None:
    report_path = package_case.directory / staging_generation.EVIDENCE_FILENAME
    report = json.loads(report_path.read_bytes())
    digest = _rewrite_report(package_case.directory, report, canonical=False)
    _assert_fixed_error(
        lambda: staging_generation.open_staging_generation(package_case.directory, digest)
    )
    _make_writable(package_case.directory)
    _make_writable(report_path)
    report_path.write_bytes(b"{")
    report_path.chmod(package_staging_generation._READ_ONLY_FILE_MODE)
    digest = _refresh_manifest(package_case.directory)
    _assert_fixed_error(
        lambda: staging_generation.open_staging_generation(package_case.directory, digest)
    )


def test_projection_tampering_and_binding_mismatch_fail_closed(
    package_case: SimpleNamespace,
) -> None:
    projection_path = package_case.directory / staging_generation.PROJECTION_FILENAME
    _make_writable(package_case.directory)
    _make_writable(projection_path)
    with projection_path.open("r+b") as output:
        output.seek(0)
        output.write(b"BROKEN!!")
    projection_path.chmod(package_staging_generation._READ_ONLY_FILE_MODE)
    digest = _refresh_manifest(package_case.directory)
    _assert_fixed_error(
        lambda: staging_generation.open_staging_generation(package_case.directory, digest)
    )


def test_valid_report_fingerprint_mismatch_reaches_projection_cross_check(
    package_case: SimpleNamespace,
) -> None:
    report = json.loads(
        (package_case.directory / staging_generation.EVIDENCE_FILENAME).read_bytes()
    )
    report["bindings"]["projectionFingerprint"] = "0" * 64
    digest = _rewrite_report(package_case.directory, report)
    _assert_fixed_error(
        lambda: staging_generation.open_staging_generation(package_case.directory, digest)
    )


def test_shape_permissions_links_symlinks_and_aliases_are_rejected(
    package_case: SimpleNamespace,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _make_writable(package_case.directory)
    extra = package_case.directory / "extra"
    extra.write_bytes(b"x")
    package_case.directory.chmod(package_staging_generation._READ_ONLY_DIRECTORY_MODE)
    _assert_fixed_error(
        lambda: staging_generation.open_staging_generation(
            package_case.directory, package_case.manifest_sha256
        )
    )
    _make_writable(package_case.directory)
    extra.unlink()
    _assert_fixed_error(
        lambda: staging_generation.open_staging_generation(
            package_case.directory, package_case.manifest_sha256
        )
    )
    package_case.directory.chmod(package_staging_generation._READ_ONLY_DIRECTORY_MODE)
    evidence_path = package_case.directory / staging_generation.EVIDENCE_FILENAME
    _make_writable(evidence_path)
    _assert_fixed_error(
        lambda: staging_generation.open_staging_generation(
            package_case.directory, package_case.manifest_sha256
        )
    )
    evidence_path.chmod(package_staging_generation._READ_ONLY_FILE_MODE)
    alias = tmp_path / "evidence-hardlink"
    os.link(evidence_path, alias)
    _assert_fixed_error(
        lambda: staging_generation.open_staging_generation(
            package_case.directory, package_case.manifest_sha256
        )
    )
    _make_writable(alias)
    alias.unlink()
    evidence_path.chmod(package_staging_generation._READ_ONLY_FILE_MODE)
    original_is_symlink = Path.is_symlink

    def selected_symlink(path: Path) -> bool:
        return path == evidence_path or original_is_symlink(path)

    monkeypatch.setattr(Path, "is_symlink", selected_symlink)
    _assert_fixed_error(
        lambda: staging_generation.open_staging_generation(
            package_case.directory, package_case.manifest_sha256
        )
    )


def test_directory_paths_and_shape_fail_closed(
    package_case: SimpleNamespace,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _assert_fixed_error(
        lambda: staging_generation.open_staging_generation(  # type: ignore[arg-type]
            "not-a-path", package_case.manifest_sha256
        )
    )
    _assert_fixed_error(
        lambda: staging_generation.open_staging_generation(
            Path("relative"), package_case.manifest_sha256
        )
    )
    file_path = (tmp_path / "file").resolve()
    file_path.write_bytes(b"x")
    _assert_fixed_error(
        lambda: staging_generation.open_staging_generation(file_path, package_case.manifest_sha256)
    )
    missing = (tmp_path / "missing").resolve()
    _assert_fixed_error(
        lambda: staging_generation.open_staging_generation(missing, package_case.manifest_sha256)
    )
    original_is_symlink = Path.is_symlink

    def directory_symlink(path: Path) -> bool:
        return path == package_case.directory or original_is_symlink(path)

    monkeypatch.setattr(Path, "is_symlink", directory_symlink)
    _assert_fixed_error(
        lambda: staging_generation.open_staging_generation(
            package_case.directory, package_case.manifest_sha256
        )
    )


def test_consumer_directory_scan_stops_at_fixed_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    consumed = 0

    def generated_entries() -> Any:
        nonlocal consumed
        for index in range(len(staging_generation.PACKAGE_FILENAMES) + 1):
            consumed += 1
            yield SimpleNamespace(name=f"entry-{index}")
        raise AssertionError("directory scan exceeded its fixed bound")

    @contextmanager
    def selected_scandir(*_args: object) -> Any:
        yield generated_entries()

    monkeypatch.setattr(staging_generation.os, "scandir", selected_scandir)
    _assert_fixed_error(lambda: staging_generation._directory_names(Path("unused")))
    assert consumed == len(staging_generation.PACKAGE_FILENAMES) + 1


def test_identity_change_during_open_is_rejected_value_free(
    package_case: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    original = staging_generation._require_unchanged

    def change_on_second_call(*args: object, **kwargs: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("sensitive-path-and-value")
        original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(staging_generation, "_require_unchanged", change_on_second_call)
    _assert_fixed_error(
        lambda: staging_generation.open_staging_generation(
            package_case.directory, package_case.manifest_sha256
        )
    )
    assert calls == 2


class _ScanHandle:
    def __init__(self, values: list[object]) -> None:
        self.values = values

    def seek(self, _offset: int) -> None:
        return None

    def read(self, _size: int) -> object:
        return self.values.pop(0)

    def fileno(self) -> int:
        raise AssertionError("fstat must be short-circuited")


@pytest.mark.parametrize(
    ("values", "state_size", "maximum"),
    [
        (["not-bytes"], 0, 1),
        ([b"xx"], 2, 1),
        ([b""], 1, 1),
    ],
)
def test_pinned_scan_rejects_nonbytes_bounds_and_short_reads(
    values: list[object], state_size: int, maximum: int
) -> None:
    state = staging_generation._FileState(1, 2, state_size, 3, 4, stat.S_IFREG, 1)
    pinned = staging_generation._PinnedFile(  # type: ignore[arg-type]
        Path("unused"), _ScanHandle(values), state
    )
    with pytest.raises(staging_generation.StagingGenerationError, match=ERROR):
        staging_generation._scan_file(pinned, maximum=maximum, retain=False)


def test_directory_and_open_handle_state_changes_are_rejected(
    package_case: SimpleNamespace,
) -> None:
    directory_state = staging_generation._file_state(
        package_case.directory.stat(follow_symlinks=False)
    )
    with pytest.raises(staging_generation.StagingGenerationError, match=ERROR):
        staging_generation._require_unchanged(
            package_case.directory,
            replace(directory_state, byte_count=directory_state.byte_count + 1),
            (),
        )
    with ExitStack() as stack:
        pinned = staging_generation._open_pinned_file(
            stack,
            package_case.directory / staging_generation.EVIDENCE_FILENAME,
        )
        stale = replace(
            pinned,
            state=replace(pinned.state, byte_count=pinned.state.byte_count + 1),
        )
        with pytest.raises(staging_generation.StagingGenerationError, match=ERROR):
            staging_generation._require_unchanged(package_case.directory, directory_state, (stale,))


def test_duplicate_open_file_identity_is_rejected(
    package_case: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = staging_generation._FileState(1, 2, 3, 4, 5, stat.S_IFREG, 1)

    def duplicated(_stack: ExitStack, path: Path) -> staging_generation._PinnedFile:
        return staging_generation._PinnedFile(path, object(), state)  # type: ignore[arg-type]

    monkeypatch.setattr(staging_generation, "_open_pinned_file", duplicated)
    _assert_fixed_error(
        lambda: staging_generation.open_staging_generation(
            package_case.directory, package_case.manifest_sha256
        )
    )


def test_producer_executes_proof_rebuilds_and_reopens_portable_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verified = evidence_helpers._verified()
    bundle = (tmp_path / "bundle").resolve()
    bundle.mkdir()
    observed: list[tuple[Path, str]] = []

    @contextmanager
    def opened(directory: Path, digest: str) -> Any:
        observed.append((directory, digest))
        yield verified

    monkeypatch.setattr(package_staging_generation, "open_reconciled_generation", opened)
    destination = (tmp_path / "staging-package").resolve()
    manifest_sha = package_staging_generation.run_packaging(
        bundle,
        evidence_helpers.SUMMARY_SHA,
        CODE_SHA,
        destination,
    )
    assert observed == [(bundle, evidence_helpers.SUMMARY_SHA)]
    assert frozenset(path.name for path in destination.iterdir()) == (
        staging_generation.PACKAGE_FILENAMES
    )
    opened_package = staging_generation.open_staging_generation(destination, manifest_sha)
    assert opened_package.records == verified.generation.records
    assert opened_package.evidence.code_sha == CODE_SHA
    assert not (destination / ".core-proof.sqlite3").exists()
    assert all(
        not (path.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
        for path in destination.iterdir()
    )


def test_producer_rejects_bad_destination_code_and_existing_output(
    tmp_path: Path,
) -> None:
    bundle = (tmp_path / "bundle").resolve()
    bundle.mkdir()
    existing = (tmp_path / "existing").resolve()
    existing.mkdir()
    sentinel = existing / "sentinel"
    sentinel.write_bytes(b"preserve")
    invalid = (
        (Path("relative"), CODE_SHA),
        (existing, CODE_SHA),
        ((tmp_path / "missing-parent" / "package").resolve(), CODE_SHA),
        ((bundle / "inside").resolve(), CODE_SHA),
        ((tmp_path / "package").resolve(), "bad"),
    )
    for destination, code_sha in invalid:
        with pytest.raises(ValueError):
            package_staging_generation.run_packaging(
                bundle,
                evidence_helpers.SUMMARY_SHA,
                code_sha,
                destination,
            )
    assert sentinel.read_bytes() == b"preserve"


def test_producer_install_failure_cleans_temporary_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verified = evidence_helpers._verified()
    bundle = (tmp_path / "bundle").resolve()
    bundle.mkdir()

    @contextmanager
    def opened(*_args: object) -> Any:
        yield verified

    monkeypatch.setattr(package_staging_generation, "open_reconciled_generation", opened)
    monkeypatch.setattr(
        package_staging_generation.os,
        "rename",
        lambda *_args: (_ for _ in ()).throw(OSError("sensitive")),
    )
    destination = (tmp_path / "failed-package").resolve()
    with pytest.raises(OSError, match="sensitive"):
        package_staging_generation.run_packaging(
            bundle, evidence_helpers.SUMMARY_SHA, CODE_SHA, destination
        )
    assert not destination.exists()
    assert not tuple(tmp_path.glob(".nla-staging-generation-*"))


def test_producer_rejects_projection_fingerprint_mismatch_and_cleans(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verified = evidence_helpers._verified()
    bundle = (tmp_path / "bundle").resolve()
    bundle.mkdir()

    @contextmanager
    def opened(*_args: object) -> Any:
        yield verified

    monkeypatch.setattr(package_staging_generation, "open_reconciled_generation", opened)
    monkeypatch.setattr(
        package_staging_generation,
        "_verify_with_measurements",
        lambda *_args, **_kwargs: evidence_helpers._verification_result(),
    )
    monkeypatch.setattr(
        package_staging_generation,
        "build_catalog_projection",
        lambda *_args, **_kwargs: object(),
    )
    destination = (tmp_path / "mismatch-package").resolve()
    with pytest.raises(ValueError):
        package_staging_generation.run_packaging(
            bundle, evidence_helpers.SUMMARY_SHA, CODE_SHA, destination
        )
    assert not destination.exists()


@pytest.mark.parametrize("failure_stage", ["candidate", "destination-race", "installed"])
def test_producer_rejects_evidence_mismatch_and_destination_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    verified = evidence_helpers._verified()
    bundle = (tmp_path / "bundle").resolve()
    bundle.mkdir()

    @contextmanager
    def opened(*_args: object) -> Any:
        yield verified

    monkeypatch.setattr(package_staging_generation, "open_reconciled_generation", opened)
    real_open = package_staging_generation.open_staging_generation
    destination = (tmp_path / "raced-package").resolve()
    calls = 0

    def selected_result(*args: object) -> object:
        nonlocal calls
        calls += 1
        real = real_open(*args)  # type: ignore[arg-type]
        if failure_stage == "candidate":
            return SimpleNamespace(evidence=object())
        if failure_stage == "destination-race" and calls == 1:
            destination.mkdir()
        if failure_stage == "installed" and calls == 2:
            return SimpleNamespace(evidence=object())
        return real

    monkeypatch.setattr(package_staging_generation, "open_staging_generation", selected_result)
    with pytest.raises(ValueError):
        package_staging_generation.run_packaging(
            bundle, evidence_helpers.SUMMARY_SHA, CODE_SHA, destination
        )
    if destination.exists():
        destination.rmdir()


def test_producer_rolls_back_post_publish_verification_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verified = evidence_helpers._verified()
    bundle = (tmp_path / "bundle").resolve()
    bundle.mkdir()

    @contextmanager
    def opened(*_args: object) -> Any:
        yield verified

    monkeypatch.setattr(package_staging_generation, "open_reconciled_generation", opened)
    real_open = package_staging_generation.open_staging_generation
    calls = 0

    def reject_second(*args: object) -> object:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("sensitive")
        return real_open(*args)  # type: ignore[arg-type]

    monkeypatch.setattr(package_staging_generation, "open_staging_generation", reject_second)
    destination = (tmp_path / "rolled-back-package").resolve()
    with pytest.raises(RuntimeError, match="sensitive"):
        package_staging_generation.run_packaging(
            bundle, evidence_helpers.SUMMARY_SHA, CODE_SHA, destination
        )
    assert calls == 2
    assert not destination.exists()


def test_producer_cleanup_refuses_replaced_work_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verified = evidence_helpers._verified()
    bundle = (tmp_path / "bundle").resolve()
    bundle.mkdir()
    sentinel = (tmp_path / "external-sentinel").resolve()
    sentinel.write_bytes(b"preserve")
    sentinel_mode = stat.S_IMODE(sentinel.stat().st_mode)
    displaced = (tmp_path / "displaced-work").resolve()
    replaced: list[Path] = []

    @contextmanager
    def opened(*_args: object) -> Any:
        yield verified

    def replace_work(*_args: object, **kwargs: object) -> object:
        work = Path(kwargs["projection_path"]).parent
        os.rename(work, displaced)
        work.mkdir()
        os.link(sentinel, work / staging_generation.EVIDENCE_FILENAME)
        replaced.append(work)
        raise RuntimeError("sensitive")

    monkeypatch.setattr(package_staging_generation, "open_reconciled_generation", opened)
    monkeypatch.setattr(package_staging_generation, "_verify_with_measurements", replace_work)
    destination = (tmp_path / "never-published").resolve()
    with pytest.raises(OSError, match="boundary"):
        package_staging_generation.run_packaging(
            bundle, evidence_helpers.SUMMARY_SHA, CODE_SHA, destination
        )
    assert len(replaced) == 1
    assert displaced.is_dir()
    assert replaced[0].is_dir()
    assert (replaced[0] / staging_generation.EVIDENCE_FILENAME).exists()
    assert sentinel.read_bytes() == b"preserve"
    assert stat.S_IMODE(sentinel.stat().st_mode) == sentinel_mode
    assert not destination.exists()


def test_producer_cleanup_refuses_replaced_post_publish_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verified = evidence_helpers._verified()
    bundle = (tmp_path / "bundle").resolve()
    bundle.mkdir()
    sentinel = (tmp_path / "external-sentinel").resolve()
    sentinel.write_bytes(b"preserve")
    sentinel_mode = stat.S_IMODE(sentinel.stat().st_mode)
    destination = (tmp_path / "published-then-replaced").resolve()
    displaced = (tmp_path / "displaced-published-package").resolve()

    @contextmanager
    def opened(*_args: object) -> Any:
        yield verified

    monkeypatch.setattr(package_staging_generation, "open_reconciled_generation", opened)
    real_open = package_staging_generation.open_staging_generation
    calls = 0

    def replace_destination(*args: object) -> object:
        nonlocal calls
        calls += 1
        if calls == 2:
            os.rename(destination, displaced)
            destination.mkdir()
            os.link(sentinel, destination / staging_generation.EVIDENCE_FILENAME)
            raise RuntimeError("sensitive")
        return real_open(*args)  # type: ignore[arg-type]

    monkeypatch.setattr(package_staging_generation, "open_staging_generation", replace_destination)
    with pytest.raises(OSError, match="boundary"):
        package_staging_generation.run_packaging(
            bundle, evidence_helpers.SUMMARY_SHA, CODE_SHA, destination
        )
    assert calls == 2
    assert displaced.is_dir()
    assert destination.is_dir()
    assert (destination / staging_generation.EVIDENCE_FILENAME).exists()
    assert sentinel.read_bytes() == b"preserve"
    assert stat.S_IMODE(sentinel.stat().st_mode) == sentinel_mode


def test_cleanup_refuses_unknown_entries_and_directories(tmp_path: Path) -> None:
    unknown = (tmp_path / "unknown-work").resolve()
    unknown.mkdir()
    unknown_identity = package_staging_generation._directory_identity(unknown)
    (unknown / "unknown").write_bytes(b"x")
    with pytest.raises(OSError, match="boundary"):
        package_staging_generation._cleanup_directory(unknown, unknown_identity)
    child = (tmp_path / "directory-work").resolve()
    child.mkdir()
    child_identity = package_staging_generation._directory_identity(child)
    (child / staging_generation.EVIDENCE_FILENAME).mkdir()
    with pytest.raises(OSError, match="boundary"):
        package_staging_generation._cleanup_directory(child, child_identity)
    absent = (tmp_path / "absent").resolve()
    package_staging_generation._cleanup_directory(absent, (-1, -1))


def test_cleanup_refuses_allowed_name_hardlink_without_touching_target(
    tmp_path: Path,
) -> None:
    directory = (tmp_path / "alias-work").resolve()
    directory.mkdir()
    directory_identity = package_staging_generation._directory_identity(directory)
    sentinel = (tmp_path / "external-sentinel").resolve()
    sentinel.write_bytes(b"preserve")
    sentinel_mode = stat.S_IMODE(sentinel.stat().st_mode)
    path = directory / staging_generation.EVIDENCE_FILENAME
    os.link(sentinel, path)
    with pytest.raises(OSError, match="boundary"):
        package_staging_generation._cleanup_directory(directory, directory_identity)
    assert directory.is_dir()
    assert path.exists()
    assert sentinel.read_bytes() == b"preserve"
    assert stat.S_IMODE(sentinel.stat().st_mode) == sentinel_mode


def test_cleanup_rechecks_child_identity_before_unlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = (tmp_path / "child-race-work").resolve()
    directory.mkdir()
    directory_identity = package_staging_generation._directory_identity(directory)
    path = directory / staging_generation.EVIDENCE_FILENAME
    path.write_bytes(b"created")
    displaced = tmp_path / "displaced-artifact"
    sentinel = tmp_path / "external-sentinel"
    sentinel.write_bytes(b"preserve")
    sentinel_mode = stat.S_IMODE(sentinel.stat().st_mode)
    original_chmod = Path.chmod

    def replace_after_chmod(path_value: Path, mode: int) -> None:
        original_chmod(path_value, mode)
        if path_value == path:
            path_value.rename(displaced)
            os.link(sentinel, path_value)

    monkeypatch.setattr(Path, "chmod", replace_after_chmod)
    with pytest.raises(OSError, match="boundary"):
        package_staging_generation._cleanup_directory(directory, directory_identity)
    assert displaced.exists()
    assert path.exists()
    assert sentinel.read_bytes() == b"preserve"
    assert stat.S_IMODE(sentinel.stat().st_mode) == sentinel_mode


def test_cleanup_directory_scan_stops_at_fixed_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = (tmp_path / "bounded-scan-work").resolve()
    directory.mkdir()
    directory_identity = package_staging_generation._directory_identity(directory)
    consumed = 0

    def generated_entries() -> Any:
        nonlocal consumed
        for index in range(len(package_staging_generation._WORK_FILENAMES) + 1):
            consumed += 1
            yield SimpleNamespace(name=f"entry-{index}")
        raise AssertionError("directory scan exceeded its fixed bound")

    @contextmanager
    def selected_scandir(*_args: object) -> Any:
        yield generated_entries()

    monkeypatch.setattr(package_staging_generation.os, "scandir", selected_scandir)
    with pytest.raises(OSError, match="boundary"):
        package_staging_generation._cleanup_directory(directory, directory_identity)
    assert consumed == len(package_staging_generation._WORK_FILENAMES) + 1


def test_cleanup_identity_helpers_fail_closed_without_touching_nodes(tmp_path: Path) -> None:
    directory = (tmp_path / "owned-directory").resolve()
    directory.mkdir()
    directory_identity = package_staging_generation._directory_identity(directory)
    artifact = (tmp_path / "owned-artifact").resolve()
    artifact.write_bytes(b"preserve")
    artifact_identity = package_staging_generation._artifact_identity(artifact)
    missing = (tmp_path / "missing-sensitive-name").resolve()

    calls = (
        lambda: package_staging_generation._require_directory_identity(missing, (-1, -1)),
        lambda: package_staging_generation._require_directory_identity(
            directory, (directory_identity[0], directory_identity[1] + 1)
        ),
        lambda: package_staging_generation._artifact_identity(missing),
        lambda: package_staging_generation._require_artifact_identity(
            artifact, (artifact_identity[0], artifact_identity[1] + 1)
        ),
        lambda: package_staging_generation._cleanup_directory(artifact, artifact_identity),
    )
    for call in calls:
        with pytest.raises(OSError) as captured:
            call()
        assert str(captured.value) == package_staging_generation._CLEANUP_BOUNDARY_ERROR

    assert directory.is_dir()
    assert artifact.read_bytes() == b"preserve"
    assert not missing.exists()


def test_empty_artifact_is_rejected(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.write_bytes(b"")
    with pytest.raises(ValueError):
        package_staging_generation._artifact(empty)


def test_runner_console_is_value_free(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(package_staging_generation._BUNDLE_ENV, str(tmp_path / "bundle"))
    monkeypatch.setenv(package_staging_generation._SUMMARY_ENV, "d" * 64)
    monkeypatch.setenv(package_staging_generation._CODE_SHA_ENV, CODE_SHA)
    monkeypatch.setenv(package_staging_generation._PACKAGE_ENV, str(tmp_path / "package"))
    monkeypatch.setattr(
        package_staging_generation,
        "run_packaging",
        lambda *_args: "e" * 64,
    )
    monkeypatch.setattr(sys, "argv", ["package_staging_generation.py"])
    assert package_staging_generation.main() == 0
    assert capsys.readouterr() == ("VALUE_FREE_RESULT: ACCEPTED\n", "")
    sensitive = "never-print-this"

    def reject(*_args: object) -> None:
        raise RuntimeError(sensitive)

    monkeypatch.setattr(package_staging_generation, "run_packaging", reject)
    assert package_staging_generation.main() == 1
    assert capsys.readouterr() == ("VALUE_FREE_RESULT: REJECTED\n", "")
    monkeypatch.setattr(sys, "argv", ["package_staging_generation.py", sensitive])
    assert package_staging_generation.main() == 1
    assert capsys.readouterr() == ("VALUE_FREE_RESULT: REJECTED\n", "")


def test_runner_module_guard_is_value_free(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "argv", ["package_staging_generation.py"])
    with pytest.raises(SystemExit, match="1"):
        runpy.run_path(package_staging_generation.__file__, run_name="__main__")
    assert capsys.readouterr() == ("VALUE_FREE_RESULT: REJECTED\n", "")


def test_documented_direct_runner_imports_and_fails_value_free_without_configuration() -> None:
    repository = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(repository / "src")
    for name in (
        package_staging_generation._BUNDLE_ENV,
        package_staging_generation._SUMMARY_ENV,
        package_staging_generation._CODE_SHA_ENV,
        package_staging_generation._PACKAGE_ENV,
    ):
        environment.pop(name, None)

    completed = subprocess.run(  # noqa: S603 - fixed interpreter and repository script
        [sys.executable, str(repository / "scripts" / "package_staging_generation.py")],
        cwd=repository,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 1
    assert completed.stdout == "VALUE_FREE_RESULT: REJECTED\n"
    assert completed.stderr == ""
