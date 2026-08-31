#!/usr/bin/env python3
"""Fail closed when repository-only boundaries are violated."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MAX_TRACKABLE_BYTES = 5 * 1024 * 1024
FORBIDDEN_TRACKED_DIRS = {
    ".venv",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "bootstrap",
    "build",
    "data",
    "dist",
    "htmlcov",
}
FORBIDDEN_FILE_ENDINGS = (
    ".db",
    ".jsonl",
    ".jsonl.gz",
    ".sqlite",
    ".sqlite3",
    ".tar.gz",
    ".zip",
    ".zst",
)
SECRET_PATTERNS = {
    "github_token": re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b"),
    "shopify_access_token": re.compile(r"\bshpat_[A-Za-z0-9]{20,}\b"),
    "shopify_shared_secret": re.compile(r"\bshpss_[A-Za-z0-9]{20,}\b"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}
WORKFLOW_FORBIDDEN = {
    "git_push": re.compile(r"\bgit\s+[^\n]*\bpush\b"),
    "self_modifying_bootstrap": re.compile(r"bootstrap/source|BUILD_REQUEST"),
}
PERMISSION_ENTRY = re.compile(
    r"^[A-Za-z0-9_-]+\s*:\s*([\"']?)(read|none|write)\1\s*$",
    re.IGNORECASE,
)
PERMISSIONS_HEADER = re.compile(
    r"^(\s*)(?:permissions|['\"]permissions['\"])\s*:\s*(.*?)\s*$",
    re.IGNORECASE,
)


class PreflightError(RuntimeError):
    """Raised when repository state cannot be inspected safely."""


def _strip_yaml_comment(line: str) -> str:
    """Strip a YAML comment while preserving hash characters inside quotes."""
    quote: str | None = None
    escaped = False
    for index, character in enumerate(line):
        if quote == '"' and character == "\\" and not escaped:
            escaped = True
            continue
        if character in {"'", '"'} and not escaped:
            if quote is None:
                quote = character
            elif quote == character:
                quote = None
        if character == "#" and quote is None:
            return line[:index]
        escaped = False
    return line


def _normalized_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1].strip()
    return value.casefold()


def _permission_value_reason(value: str) -> str | None:
    normalized = _normalized_scalar(value)
    if normalized in {"write", "write-all"}:
        return "contents_or_scope_write"
    if normalized in {"read", "read-all", "none"}:
        return None
    return "ambiguous_permissions"


def _inline_permissions_reason(value: str) -> str | None:
    normalized = value.strip()
    scalar_reason = _permission_value_reason(normalized)
    if scalar_reason != "ambiguous_permissions":
        return scalar_reason
    if normalized == "{}":
        return None
    if not (normalized.startswith("{") and normalized.endswith("}")):
        return "ambiguous_permissions"
    body = normalized[1:-1].strip()
    if not body:
        return None
    for entry in body.split(","):
        if ":" not in entry:
            return "ambiguous_permissions"
        _key, entry_value = entry.split(":", 1)
        reason = _permission_value_reason(entry_value)
        if reason:
            return reason
    return None


def workflow_permission_failures(text: str) -> list[str]:
    """Return permission violations for top-level and job-level mappings."""
    lines = text.splitlines()
    failures: list[str] = []
    top_level_permissions_seen = False
    index = 0
    while index < len(lines):
        line = _strip_yaml_comment(lines[index]).rstrip()
        header = PERMISSIONS_HEADER.match(line)
        if header is None:
            index += 1
            continue
        base_indent = len(header.group(1).expandtabs(2))
        if base_indent == 0:
            top_level_permissions_seen = True
        inline_value = header.group(2).strip()
        if inline_value:
            reason = _inline_permissions_reason(inline_value)
            if reason:
                failures.append(reason)
            index += 1
            continue

        index += 1
        saw_entry = False
        while index < len(lines):
            candidate = _strip_yaml_comment(lines[index]).rstrip()
            if not candidate.strip():
                index += 1
                continue
            indent = len(candidate) - len(candidate.lstrip(" \t"))
            if indent <= base_indent:
                break
            saw_entry = True
            entry = candidate.strip()
            match = PERMISSION_ENTRY.match(entry)
            if match is None:
                failures.append("ambiguous_permissions")
            elif match.group(2).casefold() == "write":
                failures.append("contents_or_scope_write")
            index += 1
        if not saw_entry:
            failures.append("ambiguous_permissions")
    if not top_level_permissions_seen:
        failures.append("missing_top_level_permissions")
    return failures


def tracked_files(root: Path) -> list[Path]:
    """List exactly the files Git would include in the reviewed revision."""
    git_executable = shutil.which("git")
    if git_executable is None:
        raise PreflightError("git executable not found")
    try:
        completed = subprocess.run(  # noqa: S603 - fixed executable and arguments
            [git_executable, "-C", str(root), "ls-files", "-z"],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise PreflightError(f"cannot enumerate tracked files: {exc}") from exc
    relative_paths = [
        Path(item.decode("utf-8"))
        for item in completed.stdout.split(b"\0")
        if item
    ]
    return sorted(root / relative for relative in relative_paths)


def run_preflight(root: Path) -> dict[str, Any]:
    failures: list[dict[str, str]] = []
    try:
        files = tracked_files(root)
    except (PreflightError, UnicodeDecodeError) as exc:
        return {
            "failures": [{"path": ".", "reason": f"repository_inspection:{exc}"}],
            "ok": False,
            "scannedFiles": 0,
        }

    for path in files:
        relative = path.relative_to(root)
        relative_text = relative.as_posix()
        if path.is_symlink():
            failures.append({"path": relative_text, "reason": "tracked_symlink"})
            continue
        if not path.is_file():
            failures.append({"path": relative_text, "reason": "tracked_path_missing"})
            continue
        if any(part in FORBIDDEN_TRACKED_DIRS for part in relative.parts):
            failures.append({"path": relative_text, "reason": "forbidden_tracked_path"})
        lower_name = path.name.casefold()
        if lower_name.endswith(FORBIDDEN_FILE_ENDINGS) or ".b64.part-" in lower_name:
            failures.append({"path": relative_text, "reason": "forbidden_artifact_type"})
        if path.stat().st_size > MAX_TRACKABLE_BYTES:
            failures.append({"path": relative_text, "reason": "file_larger_than_5_mib"})
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            failures.append({"path": relative_text, "reason": "non_utf8_repository_file"})
            continue
        for name, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                failures.append({"path": relative_text, "reason": f"secret_pattern:{name}"})
        if relative.parts[:2] == (".github", "workflows"):
            for name, pattern in WORKFLOW_FORBIDDEN.items():
                if pattern.search(text):
                    failures.append({"path": relative_text, "reason": f"workflow:{name}"})
            for reason in workflow_permission_failures(text):
                failures.append({"path": relative_text, "reason": f"workflow:{reason}"})

    return {
        "failures": failures,
        "ok": not failures,
        "scannedFiles": len(files),
    }


def main() -> int:
    report = run_preflight(ROOT)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
