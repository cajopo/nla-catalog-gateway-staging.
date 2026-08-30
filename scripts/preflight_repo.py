#!/usr/bin/env python3
"""Fail closed when repository-only boundaries are violated."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_TRACKABLE_BYTES = 5 * 1024 * 1024
IGNORED_DIRS = {
    ".git",
    ".venv",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "build",
    "dist",
    "htmlcov",
}
FORBIDDEN_PATH_PARTS = {"bootstrap", "data"}
FORBIDDEN_SUFFIXES = {".db", ".jsonl", ".sqlite", ".sqlite3", ".zip"}
SECRET_PATTERNS = {
    "github_token": re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b"),
    "shopify_access_token": re.compile(r"\bshpat_[A-Za-z0-9]{20,}\b"),
    "shopify_shared_secret": re.compile(r"\bshpss_[A-Za-z0-9]{20,}\b"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}
WORKFLOW_FORBIDDEN = {
    "contents_write": re.compile(r"^\s*contents:\s*write\s*$", re.MULTILINE),
    "git_push": re.compile(r"\bgit\s+[^\n]*\bpush\b"),
    "self_modifying_bootstrap": re.compile(r"bootstrap/source|BUILD_REQUEST"),
}


def files_to_scan() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if any(part in IGNORED_DIRS for part in relative.parts):
            continue
        files.append(path)
    return sorted(files)


def main() -> int:
    failures: list[dict[str, str]] = []
    files = files_to_scan()
    for path in files:
        relative = path.relative_to(ROOT)
        relative_text = relative.as_posix()
        if any(part in FORBIDDEN_PATH_PARTS for part in relative.parts):
            failures.append({"path": relative_text, "reason": "forbidden_runtime_data_path"})
        if path.suffix.lower() in FORBIDDEN_SUFFIXES or ".b64.part-" in path.name:
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

    report = {
        "failures": failures,
        "ok": not failures,
        "scannedFiles": len(files),
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
