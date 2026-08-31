from __future__ import annotations

import importlib.util
import json
import runpy
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

import pytest

PREFLIGHT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "preflight_repo.py"
PREFLIGHT_SPEC = importlib.util.spec_from_file_location("nla_repo_preflight", PREFLIGHT_PATH)
if PREFLIGHT_SPEC is None or PREFLIGHT_SPEC.loader is None:  # pragma: no cover
    raise RuntimeError("cannot load repository preflight module")
preflight = importlib.util.module_from_spec(PREFLIGHT_SPEC)
sys.modules[PREFLIGHT_SPEC.name] = preflight
PREFLIGHT_SPEC.loader.exec_module(preflight)

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
        "Data/catalog.json",
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
        "catalog.sqlite3-wal.bak",
        "catalog.db-wal.backup",
        "catalog.db.b64",
        "catalog.db-wal",
        "catalog.jsonl",
        "catalog.jsonl.gz",
        "source.tar",
        "source.tar.gz",
        "source.tar.bz2",
        "source.tar.xz",
        "source.tar.gz.b64.part-000",
        "source.b64.part-001",
        "source.7z.001",
        "source.part-002",
        "source.z01",
        "source.r00",
        "source.R99",
        "source.r000",
        "source.s00",
        "source.003",
        "source.7z",
        "source.rar",
        "source.gz",
        "source.b64",
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


@pytest.mark.parametrize(
    "command",
    [
        "git \\\n  push origin main",
        "git pu\\\nsh origin main",
        "git `\npush origin main",
        'git p"ush" origin main',
        "git -c credential.helper= push origin main",
        "bash -c 'git push origin main'",
        "sh -lc 'git push origin main'",
        "sh -x -c 'git push origin main'",
        "env sh -c 'git push origin main'",
        "env -- sh -c 'git push origin main'",
        "env -i sh -c 'git push origin main'",
        "command -- git push origin main",
        "/bin/sh -c 'git push origin main'",
        'cmd /c "git push origin main"',
        'cmd /q /c "git push origin main"',
        "cmd /c g^it p^ush origin main",
        'powershell -NoProfile -Command "git push origin main"',
        'pwsh -c "git push origin main"',
        "bash -c $'git push origin main'",
        "g`it p`ush origin main",
        "& 'C:\\Program Files\\Git\\cmd\\git.exe' push origin main",
        "PowerShell -Command \"& ('g'+'it') push origin main\"",
        "PowerShell -Command \"& ('g'+'i'+'t') push origin main\"",
        "echo `git push origin main`",
        "echo x`git push origin main`",
        "value=x`git push origin main`",
        "exec git push origin main",
        "cmd /c call g^it p^ush origin main",
        "eval 'git push origin main'",
        "Start-Process git -ArgumentList push",
        "Start-Process -FilePath git -ArgumentList push",
    ],
)
def test_obfuscated_git_push_is_rejected(tmp_path: Path, command: str) -> None:
    workflow = (
        "permissions: read-all\n"
        "jobs:\n"
        "  test:\n"
        "    steps:\n"
        "      - run: |\n" + "\n".join(f"          {line}" for line in command.splitlines()) + "\n"
    )
    root = _repo(tmp_path, {".github/workflows/test.yml": workflow})
    assert "workflow:git_push" in _reasons(preflight.run_preflight(root))


@pytest.mark.parametrize(
    "command",
    [
        "git status",
        'echo "git push origin main"',
        "printf '%s' 'git push'",
        "echo \"bash -c 'git push origin main'\"",
        "printf '%s' 'cmd /c git push origin main'",
        'Write-Output "g`it p`ush origin main"',
        "bash -c 'git status'",
        "sh -x",
        "cmd /q",
        "powershell -NoProfile",
        'cmd /c "echo git push origin main"',
        "pwsh -Command 'Write-Output \"git push origin main\"'",
        "echo '`git push origin main`'",
        "Start-Process git -ArgumentList --version",
        "Start-Process echo -ArgumentList 'git push origin main'",
    ],
)
def test_safe_shell_commands_are_not_rejected(tmp_path: Path, command: str) -> None:
    workflow = f"permissions: read-all\njobs:\n  test:\n    steps:\n      - run: {command}\n"
    root = _repo(tmp_path, {".github/workflows/test.yml": workflow})
    assert "workflow:git_push" not in _reasons(preflight.run_preflight(root))


@pytest.mark.parametrize(
    "command",
    [
        "bash -c",
        "powershell -EncodedCommand synthetic-payload",
        "sudo -u user git push origin main",
        "time -p git push origin main",
    ],
)
def test_ambiguous_shell_wrappers_fail_closed(tmp_path: Path, command: str) -> None:
    workflow = (
        f"permissions: read-all\njobs:\n  test:\n    steps:\n      - run: |\n          {command}\n"
    )
    root = _repo(tmp_path, {".github/workflows/test.yml": workflow})
    assert "workflow:ambiguous_run_step" in _reasons(preflight.run_preflight(root))


@pytest.mark.parametrize(
    "checkout_step",
    [
        "      - uses: actions/checkout@v4\n",
        "      - uses: actions/checkout@v4\n        with: {}\n",
        "      - uses: actions/checkout@v4\n        with:\n          persist-credentials: true\n",
        (
            "      - uses: actions/checkout@v4\n"
            "        with:\n"
            "          persist-credentials: ${{ false }}\n"
        ),
        (
            "      - uses: actions/checkout@v4\n"
            "        with:\n"
            "          persist-credentials: 'false'\n"
        ),
        (
            "      - uses: actions/checkout@v4\n"
            "        with:\n"
            '          persist-credentials: "FALSE"\n'
        ),
        ("      - uses: actions/checkout@v4\n        with:\n          persist-credentials: null\n"),
        ("      - uses: actions/checkout@v4\n        with:\n          persist-credentials: 0\n"),
    ],
)
def test_checkout_credentials_missing_true_or_ambiguous_fail(
    tmp_path: Path,
    checkout_step: str,
) -> None:
    workflow = "permissions: read-all\njobs:\n  test:\n    steps:\n" + checkout_step
    root = _repo(tmp_path, {".github/workflows/test.yml": workflow})
    assert "workflow:checkout_persist_credentials" in _reasons(preflight.run_preflight(root))


def test_checkout_with_boolean_false_passes(tmp_path: Path) -> None:
    workflow = (
        "permissions: read-all\n"
        "jobs:\n"
        "  test:\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "        with:\n"
        "          persist-credentials: false\n"
    )
    root = _repo(tmp_path, {".github/workflows/test.yml": workflow})
    assert preflight.run_preflight(root)["ok"] is True


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


@pytest.mark.parametrize(
    ("host", "parameter"),
    [
        ("storage." + "googleapis.com", "X-Goog-" + "Signature"),
        ("storage." + "googleapis.com", "Signature"),
        ("bucket.s3.us-east-1." + "amazonaws.com", "X-Amz-" + "Signature"),
        ("bucket.s3." + "amazonaws.com", "Signature"),
        ("account.blob.core." + "windows.net", "sig"),
    ],
)
def test_signed_capability_urls_are_rejected(
    tmp_path: Path,
    host: str,
    parameter: str,
) -> None:
    url = f"https://{host}/bucket/object?{parameter}=abcdef123456"
    root = _repo(tmp_path, {"notes.txt": url + "\n"})
    assert "secret:signed_capability_url" in _reasons(preflight.run_preflight(root))


def test_percent_encoded_capability_url_is_rejected(tmp_path: Path) -> None:
    host = "bucket.s3." + "amazonaws.com"
    parameter = "X-Amz-" + "Signature"
    encoded_query = (parameter + "=abcdef123456").replace("-", "%2D").replace("=", "%3D")
    url = f"https://{host}/object%3F{encoded_query}"
    root = _repo(tmp_path, {"notes.txt": url + "\n"})
    assert "secret:signed_capability_url" in _reasons(preflight.run_preflight(root))


@pytest.mark.parametrize("escaping", ["json", "html", "numeric_html", "unicode_json"])
def test_escaped_capability_urls_are_rejected(tmp_path: Path, escaping: str) -> None:
    host = "storage." + "googleapis.com"
    parameter = "X-Goog-" + "Signature"
    if escaping == "json":
        url = f"https:\\/\\/{host}\\/object?Expires=1&{parameter}=abcdef123456"
    elif escaping == "html":
        url = f"https://{host}/object?Expires=1&amp;{parameter}=abcdef123456"
    elif escaping == "numeric_html":
        url = f"https://{host}/object?Expires=1&#x26;{parameter}=abcdef123456"
    else:
        url = (
            f"https:\\u002f\\u002f{host}\\u002fobject\\u003fExpires"
            f"\\u003d1\\u0026{parameter}\\u003dabcdef123456"
        )
    root = _repo(tmp_path, {"payload.json": json.dumps({"url": url})})
    assert "secret:signed_capability_url" in _reasons(preflight.run_preflight(root))


def test_unicode_escaped_url_components_are_rejected(tmp_path: Path) -> None:
    scheme = "h" + r"\u0074" + "tps:"
    host = "stor" + r"\u0061" + "ge." + "googleapis.com"
    parameter = "X-Goog-Sign" + r"\u0061" + "ture"
    content = f'{{"url":"{scheme}\\/\\/{host}\\/object?{parameter}=abcdef123456"}}'
    root = _repo(tmp_path, {"payload.json": content})
    assert "secret:signed_capability_url" in _reasons(preflight.run_preflight(root))


def test_multilevel_percent_encoded_capability_url_is_rejected(tmp_path: Path) -> None:
    host = "bucket.s3." + "amazonaws.com"
    parameter = "X-Amz-" + "Signature"
    encoded = f"https://{host}/object?{parameter}=abcdef123456"
    for _ in range(4):
        encoded = quote(encoded, safe="")
    root = _repo(tmp_path, {"notes.txt": encoded})
    assert "secret:signed_capability_url" in _reasons(preflight.run_preflight(root))


def test_nonconvergent_url_encoding_fails_closed(tmp_path: Path) -> None:
    host = "storage." + "googleapis.com"
    parameter = "X-Goog-" + "Signature"
    encoded = f"https://{host}/object?{parameter}=abcdef123456"
    for _ in range(preflight.MAX_URL_DECODE_STEPS + 2):
        encoded = quote(encoded, safe="")
    root = _repo(tmp_path, {"notes.txt": encoded})
    assert "secret:ambiguous_capability_url_encoding" in _reasons(preflight.run_preflight(root))


def test_deceptive_or_unsigned_capability_urls_pass(tmp_path: Path) -> None:
    host = "amazonaws." + "com.example.org"
    marker = "Signature"
    root = _repo(
        tmp_path,
        {
            "notes.txt": (
                f"https://{host}/object?{marker}=abcdef123456\n"
                "https://storage.googleapis.com/bucket/public-object\n"
            )
        },
    )
    assert preflight.run_preflight(root)["ok"] is True


def test_multilevel_encoded_deceptive_host_passes(tmp_path: Path) -> None:
    host = "amazonaws." + "com.example.org"
    parameter = "X-Amz-" + "Signature"
    encoded = f"https://{host}/object?{parameter}=abcdef123456"
    for _ in range(4):
        encoded = quote(encoded, safe="")
    root = _repo(tmp_path, {"notes.txt": encoded})
    assert preflight.run_preflight(root)["ok"] is True


@pytest.mark.parametrize("kind", ["p", "o", "u", "s", "r"])
def test_current_github_token_families_are_rejected(tmp_path: Path, kind: str) -> None:
    prefix = "gh" + kind + "_"
    root = _repo(tmp_path, {"notes.txt": prefix + "A" * 30 + "\n"})
    assert "secret:github_token" in _reasons(preflight.run_preflight(root))


@pytest.mark.parametrize("prefix", ["AK" + "IA", "AS" + "IA"])
def test_aws_access_key_ids_are_rejected(tmp_path: Path, prefix: str) -> None:
    root = _repo(tmp_path, {"notes.txt": prefix + "A1" * 8 + "\n"})
    assert "secret:aws_access_key_id" in _reasons(preflight.run_preflight(root))


def test_github_fine_grained_token_is_rejected(tmp_path: Path) -> None:
    prefix = "github_" + "pat_"
    root = _repo(tmp_path, {"notes.txt": prefix + "A1_" * 12 + "\n"})
    assert "secret:github_token" in _reasons(preflight.run_preflight(root))


@pytest.mark.parametrize("kind", ["at", "ca", "pa", "ss"])
def test_shopify_token_families_are_rejected(tmp_path: Path, kind: str) -> None:
    prefix = "shp" + kind + "_"
    root = _repo(tmp_path, {"notes.txt": prefix + "A1" * 16 + "\n"})
    assert "secret:shopify_token" in _reasons(preflight.run_preflight(root))


@pytest.mark.parametrize("kind", ["", "RSA ", "EC ", "OPENSSH ", "DSA ", "ENCRYPTED "])
def test_private_key_headers_are_rejected(tmp_path: Path, kind: str) -> None:
    key_header = "-----BEGIN " + kind + "PRIVATE KEY-----"
    root = _repo(tmp_path, {"key.pem": key_header + "\n"})
    assert "secret:private_key" in _reasons(preflight.run_preflight(root))


@pytest.mark.parametrize("style", ["bare", "double", "single", "json"])
def test_generic_credential_forms_are_rejected(tmp_path: Path, style: str) -> None:
    key_name = "DATABASE_" + "PASSWORD"
    value = "Tr0ub4dor&CorrectHorse!"
    if style == "bare":
        content = f"export {key_name}={value}\n"
    elif style == "double":
        content = f'{key_name}="{value}"\n'
    elif style == "single":
        content = f"- {key_name}: '{value}'\n"
    else:
        content = f'{{"{key_name}": "{value}"}}\n'
    root = _repo(tmp_path, {"config.txt": content})
    assert any(
        reason.startswith("secret:credential_assignment")
        for reason in _reasons(preflight.run_preflight(root))
    )


def test_allowlist_text_cannot_hide_a_real_credential_or_url(tmp_path: Path) -> None:
    key_name = "AWS_" + "SECRET_ACCESS_KEY"
    marker = "pragma: allowlist " + "secret"
    host = "storage." + "googleapis.com"
    signature = "X-Goog-" + "Signature"
    content = (
        f"{key_name}=AbCdEfGhIjKlMnOpQrStUvWxYz0123456789ABCD # {marker}\n"
        f"https://{host}/bucket/object?{signature}=abcdef123456 # {marker}\n"
    )
    root = _repo(tmp_path, {"config.txt": content})
    reasons = _reasons(preflight.run_preflight(root))
    assert any(reason.startswith("secret:credential_assignment") for reason in reasons)
    assert "secret:signed_capability_url" in reasons


def test_placeholder_and_low_entropy_values_are_not_flagged(tmp_path: Path) -> None:
    key_name = "CLIENT_" + "SECRET"
    root = _repo(
        tmp_path,
        {
            "config.env.example": f"{key_name}=change-me-placeholder\n",
            "test.txt": f"{key_name}={'a' * 20}\n",
        },
    )
    assert preflight.run_preflight(root)["ok"] is True


@pytest.mark.parametrize(
    "value",
    [
        "ProdExample_A7f9Q2zLm4Ns8Vk1",
        "fake-A7f9Q2zLm4Ns8Vk1",
        "dummy-A7f9Q2zLm4Ns8Vk1",
        "your-api-key-A7f9Q2zLm4Ns8Vk1",
        "change-me-placeholder-A7f9Q2zLm4Ns8Vk1",
        "not-a-secret-A7f9Q2zLm4Ns8Vk1",
    ],
)
def test_placeholder_substrings_cannot_hide_credentials(
    tmp_path: Path,
    value: str,
) -> None:
    key_name = "CLIENT_" + "SECRET"
    root = _repo(tmp_path, {"config.env": f"{key_name}={value}\n"})
    assert any(
        reason.startswith("secret:credential_assignment")
        for reason in _reasons(preflight.run_preflight(root))
    )


def test_explicit_secret_template_is_a_safe_placeholder(tmp_path: Path) -> None:
    key_name = "CLIENT_" + "SECRET"
    value = "${{ secrets.CLIENT_SECRET }}"
    root = _repo(tmp_path, {"config.env": f'{key_name}="{value}"\n'})
    assert preflight.run_preflight(root)["ok"] is True


def test_specific_token_is_never_suppressed_as_a_placeholder(tmp_path: Path) -> None:
    prefix = "gh" + "p_"
    value = prefix + "fake" + "A7f9Q2zLm4Ns8Vk1" * 2
    root = _repo(tmp_path, {"notes.txt": value})
    assert "secret:github_token" in _reasons(preflight.run_preflight(root))


@pytest.mark.parametrize(
    ("escaped_prefix", "suffix", "reason"),
    [
        ("gh" + r"\u0070" + "_", "ABCDEFGHIJKLMNOPQRSTUVWXYZ012345", "github_token"),
        ("g" + r"\u0068" + "p_", "ABCDEFGHIJKLMNOPQRSTUVWXYZ012345", "github_token"),
        ("shp" + r"\u0061" + "t_", "ABCDEFGHIJKLMNOPQRSTUVWXYZ012345", "shopify_token"),
        ("s" + r"\u0068" + "pat_", "ABCDEFGHIJKLMNOPQRSTUVWXYZ012345", "shopify_token"),
        ("AKI" + r"\u0041", "ABCDEFGHIJKLMNOP", "aws_access_key_id"),
        ("A" + r"\u004b" + "IA", "ABCDEFGHIJKLMNOP", "aws_access_key_id"),
    ],
)
def test_unicode_escaped_specific_secrets_are_rejected(
    tmp_path: Path,
    escaped_prefix: str,
    suffix: str,
    reason: str,
) -> None:
    root = _repo(tmp_path, {"payload.json": f'{{"note":"{escaped_prefix}{suffix}"}}'})
    assert f"secret:{reason}" in _reasons(preflight.run_preflight(root))


@pytest.mark.parametrize(
    "key_name",
    ["CLIENT_SECR" + r"\u0045" + "T", "passw" + r"\u006f" + "rd"],
)
def test_unicode_escaped_credential_key_is_rejected(
    tmp_path: Path,
    key_name: str,
) -> None:
    value = "AbCdEfGhIjKlMnOpQrStUvWxYz012345"
    root = _repo(tmp_path, {"payload.json": f'{{"{key_name}":"{value}"}}'})
    assert any(
        reason.startswith("secret:credential_assignment:")
        for reason in _reasons(preflight.run_preflight(root))
    )


@pytest.mark.parametrize(
    "document",
    [
        {"products": [{"id": "PRODUCT_GID", "title": "Card", "variants": []}]},
        [{"id": "PRODUCT_GID", "handle": "card", "variants": []}],
        {
            "data": {
                "products": {
                    "edges": [{"node": {"id": "PRODUCT_GID", "status": "ACTIVE", "title": "Card"}}]
                }
            }
        },
    ],
)
def test_small_shopify_product_snapshots_are_rejected(
    tmp_path: Path,
    document: object,
) -> None:
    product_gid = "gid://shopify/" + "Product/123"
    serialized = json.dumps(document).replace("PRODUCT_GID", product_gid)
    root = _repo(tmp_path, {"products-export.json": serialized})
    assert "forbidden_shopify_snapshot" in _reasons(preflight.run_preflight(root))


def test_canonical_numeric_product_snapshot_is_rejected(tmp_path: Path) -> None:
    document = {"products": [{"id": 123, "title": "Card", "variants": []}]}
    root = _repo(tmp_path, {"products.json": json.dumps(document)})
    assert "forbidden_shopify_snapshot" in _reasons(preflight.run_preflight(root))


def test_noncanonical_numeric_product_snapshot_is_rejected(tmp_path: Path) -> None:
    document = {"products": [{"id": 123, "title": "Card", "variants": []}]}
    root = _repo(tmp_path, {"catalog.json": json.dumps(document)})
    assert "forbidden_shopify_snapshot" in _reasons(preflight.run_preflight(root))


def test_canonical_top_level_product_list_is_rejected(tmp_path: Path) -> None:
    document = [{"id": 123, "title": "Card", "variants": []}]
    root = _repo(tmp_path, {"products.json": json.dumps(document)})
    assert "forbidden_shopify_snapshot" in _reasons(preflight.run_preflight(root))


def test_canonical_nonempty_list_is_treated_as_a_snapshot(tmp_path: Path) -> None:
    root = _repo(tmp_path, {"products.json": json.dumps([{"enabled": True}])})
    assert "forbidden_shopify_snapshot" in _reasons(preflight.run_preflight(root))


@pytest.mark.parametrize(
    "id_key",
    ["id", "admin_graphql_api_id", "gid", "shopify_product_gid"],
)
def test_shopify_product_gid_identity_keys_are_rejected(
    tmp_path: Path,
    id_key: str,
) -> None:
    product_gid = "gid://shopify/" + "Product/123"
    document = {id_key: product_gid, "product_type": "Single", "variants": []}
    root = _repo(tmp_path, {"catalog.json": json.dumps(document)})
    assert "forbidden_shopify_snapshot" in _reasons(preflight.run_preflight(root))


@pytest.mark.parametrize(
    "product_id",
    [
        "gid://shopify/Product/0",
        "gid://shopify/Product/0123",
        "gid://shopify/product/123",
        "gid://example/Product/123",
    ],
)
def test_shopify_gid_near_misses_in_config_are_safe(
    tmp_path: Path,
    product_id: str,
) -> None:
    document = {"default": {"id": product_id, "title": "Example"}}
    root = _repo(tmp_path, {"config.json": json.dumps(document)})
    assert preflight.run_preflight(root)["ok"] is True


def test_declarative_products_config_is_not_a_snapshot(tmp_path: Path) -> None:
    product_gid = "gid://shopify/" + "Product/123"
    document = {
        "products": {"enabled": True, "page_size": 50},
        "references": {"default_product_gid": product_gid},
    }
    root = _repo(tmp_path, {"products.json": json.dumps(document)})
    assert preflight.run_preflight(root)["ok"] is True


def test_featured_product_reference_is_not_a_snapshot(tmp_path: Path) -> None:
    product_gid = "gid://shopify/" + "Product/123"
    document = {"featured_product": {"id": product_gid, "title": "Hero"}}
    root = _repo(tmp_path, {"config.json": json.dumps(document)})
    assert preflight.run_preflight(root)["ok"] is True


def test_scanner_source_does_not_match_itself() -> None:
    source = PREFLIGHT_PATH.read_text(encoding="utf-8")
    assert preflight.secret_failures(source) == []


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


def test_repository_inspection_failure_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_inspection(_: Path) -> list[preflight.TrackedBlob]:
        raise preflight.PreflightError("synthetic inspection failure")

    monkeypatch.setattr(preflight, "tracked_blobs", fail_inspection)
    report = preflight.run_preflight(Path.cwd())
    assert report["ok"] is False
    assert report["scannedFiles"] == 0
    assert _reasons(report)[0].startswith("repository_inspection:")


def test_secret_entropy_and_placeholder_helpers() -> None:
    assert preflight._shannon_entropy("aaaaaaaaaaaaaaaa") == 0.0
    assert preflight._looks_like_placeholder("YOUR-API-KEY") is True
    assert preflight._looks_like_placeholder("ActualRandomValue") is False


def test_unique_yaml_loader_rejects_unhashable_key() -> None:
    with pytest.raises(preflight.PreflightError, match="invalid or ambiguous workflow YAML"):
        preflight._load_workflow("? [a, b]\n: value\n")


def test_git_executable_missing_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(preflight.shutil, "which", lambda _: None)
    with pytest.raises(preflight.PreflightError, match="git executable not found"):
        preflight._git(Path.cwd(), "status")


def test_git_command_failure_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_command(*_: object, **__: object) -> None:
        raise OSError("synthetic command failure")

    monkeypatch.setattr(preflight.subprocess, "run", fail_command)
    with pytest.raises(preflight.PreflightError, match="git command failed"):
        preflight._git(Path.cwd(), "status")


@pytest.mark.parametrize(
    ("entries", "message"),
    [
        (b"malformed\0", "cannot parse Git index entry"),
        (b"100644 abc 0\t\xff\0", "cannot parse Git index entry"),
        (b"100644 abc 1\tfile.txt\0", "unmerged Git index entry"),
    ],
)
def test_malformed_git_index_entries_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    entries: bytes,
    message: str,
) -> None:
    monkeypatch.setattr(preflight, "_git", lambda *_: entries)
    with pytest.raises(preflight.PreflightError, match=message):
        preflight.tracked_blobs(Path.cwd())


def test_duplicate_git_index_path_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    entry = b"100644 abc 0\tfile.txt\0"

    def fake_git(_: Path, *arguments: str) -> bytes:
        return entry + entry if arguments[0] == "ls-files" else b"safe\n"

    monkeypatch.setattr(preflight, "_git", fake_git)
    with pytest.raises(preflight.PreflightError, match="duplicate Git index path"):
        preflight.tracked_blobs(Path.cwd())


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("unexpected", ["ambiguous_permissions"]),
        (None, ["ambiguous_permissions"]),
        ({3: "read"}, ["ambiguous_permissions"]),
        ({"contents": 3}, ["ambiguous_permissions"]),
        ({"contents": "admin"}, ["ambiguous_permissions"]),
    ],
)
def test_ambiguous_permission_values_fail_closed(
    value: object,
    expected: list[str],
) -> None:
    assert preflight._permission_failures(value) == expected


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ("echo safe; git status", False),
        ("env MODE=safe git status", False),
        ("echo git push", False),
        ("git", False),
        ("git --version", False),
        ("git -- push", True),
        ("/usr/bin/git -c=color.ui=never push", True),
        ("env", False),
        ("env -u NAME git status", False),
        ("env --unset=NAME git status", False),
        ("env -u", None),
        ("env --unknown git status", None),
        ("command -p git push", True),
        ("command -v git", False),
        ("command -V git", False),
        ("command git status", False),
        ("Start-Process -NoNewWindow", None),
        ("Start-Process -FilePath", None),
    ],
)
def test_shell_token_scanner_distinguishes_commands(
    script: str,
    expected: bool | None,
) -> None:
    assert preflight._contains_git_push(script) is expected


def test_shell_scanner_bounds_fail_closed() -> None:
    oversized = "x" * (preflight.MAX_SHELL_SCAN_CHARS + 1)
    assert preflight._contains_git_push(oversized) is None
    assert (
        preflight._contains_git_push("bash -c 'git status'", _depth=preflight.MAX_SHELL_SCAN_DEPTH)
        is None
    )
    backtick = "`"
    assert preflight._contains_git_push(f"echo {backtick}unterminated") is None
    assert (
        preflight._contains_git_push(
            f"echo {backtick}git status{backtick}",
            _depth=preflight.MAX_SHELL_SCAN_DEPTH,
        )
        is None
    )
    assert preflight._backtick_substitutions(f"g{backtick}it") == []


def test_unbalanced_shell_quote_fails_closed(tmp_path: Path) -> None:
    workflow = (
        "permissions: read-all\njobs:\n  test:\n    steps:\n      - run: echo 'unterminated\n"
    )
    root = _repo(tmp_path, {".github/workflows/test.yml": workflow})
    assert "workflow:ambiguous_run_step" in _reasons(preflight.run_preflight(root))


def test_checkout_step_shapes_fail_closed_or_pass() -> None:
    assert preflight._checkout_failures({"uses": 3}) == ["ambiguous_uses_step"]
    assert preflight._checkout_failures({"uses": "actions/setup-python@v6"}) == []
    assert preflight._checkout_failures({"uses": "actions/checkout@v4", "with": []}) == [
        "checkout_persist_credentials"
    ]


def test_non_mapping_workflow_document_fails_closed() -> None:
    assert preflight.workflow_failures("[]\n") == ["invalid_yaml"]


def test_malformed_url_and_repeated_encoding_are_safe() -> None:
    assert preflight._is_signed_capability_url("https://[broken?sig=value") is False
    repeatedly_encoded = "https://example.org/%25252541"
    assert preflight._is_signed_capability_url(repeatedly_encoded) is False
    nonconvergent = "%41"
    for _ in range(preflight.MAX_URL_DECODE_STEPS + 1):
        nonconvergent = quote(nonconvergent, safe="")
    assert preflight._is_signed_capability_url(nonconvergent) is None


def test_url_decoder_size_bound_distinguishes_plain_and_encoded_text() -> None:
    plain = "a" * (preflight.MAX_URL_DECODE_CHARS + 1)
    encoded = plain + "%41"
    assert preflight._decode_url_text(plain) == (plain, True)
    assert preflight._decode_url_text(encoded) == (encoded, False)


def test_repeated_url_findings_are_deduplicated() -> None:
    host = "storage." + "googleapis.com"
    parameter = "X-Goog-" + "Signature"
    signed_url = f"https://{host}/object?{parameter}=abcdef123456"
    assert (
        preflight.secret_failures(signed_url + "\n" + signed_url).count("signed_capability_url")
        == 1
    )

    nonconvergent = "%41"
    for _ in range(preflight.MAX_URL_DECODE_STEPS + 1):
        nonconvergent = quote(nonconvergent, safe="")
    assert (
        preflight.secret_failures(nonconvergent + "\n" + nonconvergent).count(
            "ambiguous_capability_url_encoding"
        )
        == 1
    )


def test_shopify_snapshot_helpers_scan_complete_json_without_false_positives() -> None:
    assert preflight._looks_like_shopify_snapshot(Path("notes.txt"), "{}") is False
    assert preflight._looks_like_shopify_snapshot(Path("config.json"), "{") is False
    large_config = list(range(2_050))
    assert preflight._contains_shopify_product(large_config) is False
    assert (
        preflight._looks_like_shopify_snapshot(Path("large-config.json"), json.dumps(large_config))
        is False
    )


def test_shopify_snapshot_scan_cannot_be_hidden_behind_filler() -> None:
    product_gid = "gid://shopify/" + "Product/123"
    product = {"id": product_gid, "title": "Card", "variants": []}
    document = [product, *range(2_050)]
    assert preflight._looks_like_shopify_snapshot(Path("catalog.json"), json.dumps(document))


def test_unsupported_mode_and_large_blob_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blobs = [
        preflight.TrackedBlob(Path("submodule"), "160000", b"safe\n"),
        preflight.TrackedBlob(
            Path("large.txt"),
            "100644",
            b"a" * (preflight.MAX_TRACKABLE_BYTES + 1),
        ),
    ]
    monkeypatch.setattr(preflight, "tracked_blobs", lambda _: blobs)
    reasons = _reasons(preflight.run_preflight(Path.cwd()))
    assert "unsupported_git_mode:160000" in reasons
    assert "file_larger_than_5_mib" in reasons


@pytest.mark.parametrize(("ok", "expected"), [(True, 0), (False, 1)])
def test_main_reports_result_and_exit_code(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    ok: bool,
    expected: int,
) -> None:
    report = {"failures": [], "ok": ok, "scannedFiles": 1}
    monkeypatch.setattr(preflight, "run_preflight", lambda _: report)
    assert preflight.main() == expected
    assert '"scannedFiles": 1' in capsys.readouterr().out


def test_module_entrypoint_executes_repository_preflight() -> None:
    with pytest.raises(SystemExit) as raised:
        runpy.run_path(str(PREFLIGHT_PATH), run_name="__main__")
    assert raised.value.code == 0
