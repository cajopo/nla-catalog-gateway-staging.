from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from scripts import preflight_repo as preflight

GIT_EXECUTABLE = shutil.which("git")
if GIT_EXECUTABLE is None:  # pragma: no cover - Git is guaranteed in CI
    raise RuntimeError("git executable not found")


def _git(root: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603 - fixed executable and test-controlled arguments
        [GIT_EXECUTABLE, "-C", str(root), *args],
        check=True,
        capture_output=True,
    )


def _repo(tmp_path: Path, files: dict[str, str]) -> Path:
    _git(tmp_path, "init")
    for relative, content in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _git(tmp_path, "add", "-f", ".")
    return tmp_path


def test_force_added_generated_file_is_rejected(tmp_path: Path) -> None:
    root = _repo(tmp_path, {"dist/catalog.json": "{}"})
    report = preflight.run_preflight(root)
    assert report["ok"] is False
    assert report["failures"] == [
        {"path": "dist/catalog.json", "reason": "forbidden_tracked_path"}
    ]


@pytest.mark.parametrize(
    "permissions",
    [
        "permissions: write-all",
        "permissions: 'write-all'",
        "permissions: {contents: write}",
        'permissions: { contents: "write" }',
        "permissions:\n  contents: write # dangerous",
        "jobs:\n  test:\n    permissions:\n      contents: 'write'",
    ],
)
def test_every_explicit_write_permission_form_is_rejected(
    tmp_path: Path,
    permissions: str,
) -> None:
    root = _repo(tmp_path, {".github/workflows/test.yml": permissions + "\n"})
    reasons = [item["reason"] for item in preflight.run_preflight(root)["failures"]]
    assert "workflow:contents_or_scope_write" in reasons


@pytest.mark.parametrize(
    "permissions",
    [
        "permissions: read-all",
        "permissions: {}",
        "permissions: {contents: read, actions: none}",
        "permissions:\n  contents: read\n  actions: none",
        "jobs:\n  test:\n    permissions:\n      contents: read",
    ],
)
def test_read_only_permission_forms_pass(tmp_path: Path, permissions: str) -> None:
    root = _repo(tmp_path, {".github/workflows/test.yml": permissions + "\n"})
    assert preflight.run_preflight(root)["ok"] is True


def test_alias_or_noncanonical_permissions_fail_closed(tmp_path: Path) -> None:
    root = _repo(
        tmp_path,
        {".github/workflows/test.yml": "permissions: *dangerous\n"},
    )
    assert preflight.run_preflight(root)["failures"] == [
        {"path": ".github/workflows/test.yml", "reason": "workflow:ambiguous_permissions"}
    ]


def test_yaml_hash_inside_quotes_is_not_treated_as_comment(tmp_path: Path) -> None:
    root = _repo(
        tmp_path,
        {".github/workflows/test.yml": 'permissions: "write#still-value"\n'},
    )
    assert preflight.run_preflight(root)["ok"] is False


def test_untracked_generated_file_is_outside_reviewed_revision(tmp_path: Path) -> None:
    root = _repo(tmp_path, {"README.md": "safe\n"})
    generated = root / "dist/catalog.json"
    generated.parent.mkdir()
    generated.write_text("{}", encoding="utf-8")
    report = preflight.run_preflight(root)
    assert report["ok"] is True
    assert report["scannedFiles"] == 1
