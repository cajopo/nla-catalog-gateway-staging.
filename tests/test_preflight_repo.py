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
    tmp_path.mkdir(parents=True, exist_ok=True)
    _git(tmp_path, "init")
    for relative, content in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _git(tmp_path, "add", "-f", ".")
    return tmp_path


def _reasons(report: dict[str, object]) -> list[str]:
    failures = report["failures"]
    assert isinstance(failures, list)
    return [item["reason"] for item in failures]


def test_safe_repository_passes(tmp_path: Path) -> None:
    root = _repo(
        tmp_path,
        {
            "README.md": "safe\n",
            ".github/workflows/test.yml": (
                "permissions: read-all\n"
                "jobs:\n"
                "  test:\n"
                "    runs-on: ubuntu-latest\n"
                "    steps:\n"
                "      - run: echo safe\n"
            ),
        },
    )
    report = preflight.run_preflight(root)
    assert report["ok"] is True
    assert report["scannedFiles"] == 2


@pytest.mark.parametrize(
    "path",
    [
        "dist/catalog.json",
        "build/catalog.json",
        "data/catalog.json",
        "bootstrap/source.txt",
        "output/catalog.json",
    ],
)
def test_force_added_generated_directories_are_rejected(
    tmp_path: Path,
    path: str,
) -> None:
    root = _repo(tmp_path, {path: "{}"})
    assert "forbidden_tracked_path" in _reasons(preflight.run_preflight(root))


@pytest.mark.parametrize(
    "name",
    [
        "catalog.db",
        "catalog.sqlite",
        "catalog.sqlite3",
        "catalog.sqlite3-journal",
        "catalog.sqlite3-wal",
        "catalog.sqlite3-shm",
        "catalog.db-wal",
        "catalog.jsonl",
        "catalog.jsonl.gz",
        "source.tar.gz",
        "source.zip",
        "index.zst",
    ],
)
def test_force_added_catalog_artifacts_are_rejected(
    tmp_path: Path,
    name: str,
) -> None:
    root = _repo(tmp_path, {name: "text"})
    assert "forbidden_artifact_type" in _reasons(preflight.run_preflight(root))


@pytest.mark.parametrize(
    "permissions",
    [
        "permissions: write-all",
        "permissions: 'write-all'",
        "permissions: {contents: write}",
        '"permissions": {contents: write}',
        "permissions:\n  contents: write # dangerous",
        (
            "permissions: read-all\n"
            "jobs: {test: {permissions: write-all, runs-on: ubuntu-latest, "
            'steps: [{run: "true"}]}}\n'
        ),
        ("permissions: read-all\njobs:\n  test:\n    permissions:\n      contents: 'write'\n"),
    ],
)
def test_every_write_permission_form_is_rejected(
    tmp_path: Path,
    permissions: str,
) -> None:
    root = _repo(tmp_path, {".github/workflows/test.yml": permissions + "\n"})
    assert any(
        reason.startswith("workflow:write_permission")
        for reason in _reasons(preflight.run_preflight(root))
    )


@pytest.mark.parametrize(
    "permissions",
    [
        "permissions: read-all",
        "permissions: {}",
        "permissions: {contents: read, actions: none}",
        "permissions:\n  contents: read\n  actions: none",
        ("permissions: read-all\njobs:\n  test:\n    permissions:\n      contents: read\n"),
    ],
)
def test_read_only_permission_forms_pass(
    tmp_path: Path,
    permissions: str,
) -> None:
    root = _repo(tmp_path, {".github/workflows/test.yml": permissions + "\n"})
    assert preflight.run_preflight(root)["ok"] is True


def test_missing_top_level_permissions_fails_closed(tmp_path: Path) -> None:
    root = _repo(
        tmp_path,
        {".github/workflows/test.yml": ("jobs:\n  test:\n    runs-on: ubuntu-latest\n")},
    )
    assert "workflow:missing_top_level_permissions" in _reasons(preflight.run_preflight(root))


@pytest.mark.parametrize(
    "workflow",
    [
        "permissions: *dangerous\n",
        "permissions: read-all\npermissions: write-all\n",
        "permissions: read-all\njobs: []\n",
        "permissions: read-all\njobs:\n  test: []\n",
        "permissions: read-all\njobs:\n  test:\n    steps: {}\n",
        "permissions: read-all\njobs:\n  test:\n    steps:\n      - 3\n",
        "permissions: read-all\njobs:\n  test:\n    steps:\n      - run: 3\n",
    ],
)
def test_ambiguous_workflow_structures_fail_closed(
    tmp_path: Path,
    workflow: str,
) -> None:
    root = _repo(tmp_path, {".github/workflows/test.yml": workflow})
    reasons = _reasons(preflight.run_preflight(root))
    assert any(reason.startswith("workflow:") for reason in reasons)
    assert preflight.run_preflight(root)["ok"] is False


def test_shell_continued_git_push_is_rejected(tmp_path: Path) -> None:
    workflow = (
        "permissions: read-all\n"
        "jobs:\n"
        "  test:\n"
        "    steps:\n"
        "      - run: |\n"
        "          git \\\n"
        "            push origin main\n"
    )
    root = _repo(tmp_path, {".github/workflows/test.yml": workflow})
    assert "workflow:git_push" in _reasons(preflight.run_preflight(root))


def test_index_blob_is_scanned_instead_of_worktree(tmp_path: Path) -> None:
    path = ".github/workflows/test.yml"
    root = _repo(tmp_path, {path: "permissions: write-all\n"})
    (root / path).write_text("permissions: read-all\n", encoding="utf-8")
    reasons = _reasons(preflight.run_preflight(root))
    assert "workflow:write_permission" in reasons


def test_index_secret_is_scanned_instead_of_worktree(tmp_path: Path) -> None:
    name = "AWS_" + "SECRET_ACCESS_KEY"
    value = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789ABCD"
    root = _repo(tmp_path, {"config.env": f"{name}={value}\n"})
    (root / "config.env").write_text("SAFE=true\n", encoding="utf-8")
    reasons = _reasons(preflight.run_preflight(root))
    assert any(reason.startswith("secret:credential_assignment") for reason in reasons)


def test_signed_capability_url_is_rejected(tmp_path: Path) -> None:
    host = "storage." + "googleapis.com"
    signature = "X-Goog-" + "Signature"
    url = f"https://{host}/bucket/object?{signature}=abcdef123456"
    root = _repo(tmp_path, {"notes.txt": url + "\n"})
    assert "secret:signed_capability_url" in _reasons(preflight.run_preflight(root))


def test_specific_tokens_and_private_keys_are_rejected(tmp_path: Path) -> None:
    prefix = "gh" + "p_"
    token = prefix + "A" * 30
    root = _repo(tmp_path, {"notes.txt": token + "\n"})
    assert "secret:github_token" in _reasons(preflight.run_preflight(root))

    key_header = "-----BEGIN " + "PRIVATE KEY-----"
    root = _repo(tmp_path / "key-repo", {"key.pem": key_header + "\n"})
    assert "secret:private_key" in _reasons(preflight.run_preflight(root))


def test_placeholder_and_explicit_allowlist_are_not_flagged(tmp_path: Path) -> None:
    key_name = "CLIENT_" + "SECRET"
    root = _repo(
        tmp_path,
        {
            "config.env.example": f"{key_name}=change-me-placeholder\n",
            "test.txt": (f"{key_name}=AbCdEfGhIjKlMnOpQrStUvWx # pragma: allowlist secret\n"),
        },
    )
    assert preflight.run_preflight(root)["ok"] is True


def test_untracked_generated_file_is_outside_reviewed_revision(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path, {"README.md": "safe\n"})
    generated = root / "dist/catalog.json"
    generated.parent.mkdir()
    generated.write_text("{}", encoding="utf-8")
    report = preflight.run_preflight(root)
    assert report["ok"] is True
    assert report["scannedFiles"] == 1


def test_non_utf8_tracked_file_is_rejected(tmp_path: Path) -> None:
    _git(tmp_path, "init")
    (tmp_path / "binary.bin").write_bytes(b"\xff")
    _git(tmp_path, "add", "-f", ".")
    assert "non_utf8_repository_file" in _reasons(preflight.run_preflight(tmp_path))


def test_tracked_symlink_is_rejected(tmp_path: Path) -> None:
    _git(tmp_path, "init")
    (tmp_path / "target.txt").write_text("safe\n", encoding="utf-8")
    (tmp_path / "link.txt").symlink_to("target.txt")
    _git(tmp_path, "add", "-f", ".")
    assert "tracked_symlink" in _reasons(preflight.run_preflight(tmp_path))


def test_repository_inspection_failure_is_reported(tmp_path: Path) -> None:
    report = preflight.run_preflight(tmp_path)
    assert report["ok"] is False
    assert report["scannedFiles"] == 0
    assert _reasons(report)[0].startswith("repository_inspection:")


def test_secret_entropy_and_placeholder_helpers() -> None:
    assert preflight._shannon_entropy("aaaaaaaaaaaaaaaa") == 0.0
    assert preflight._looks_like_placeholder("YOUR-API-KEY") is True
    assert preflight._looks_like_placeholder("ActualRandomValue") is False
