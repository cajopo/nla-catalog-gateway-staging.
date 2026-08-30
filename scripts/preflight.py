from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = {
    "pyproject.toml", "Dockerfile", "render.yaml", "app/main.py", "app/catalog.py",
    "app/app_proxy.py", "app/sync/build_index.py", "tests/test_gateway.py",
    "theme/sections/nla-catalog-search.liquid", "theme/assets/nla-catalog.js",
}
SKIP_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache", "data"}
SECRET_PATTERNS = {
    "Shopify access token": re.compile(r"\bshpat_[A-Za-z0-9]{20,}\b"),
    "GitHub token": re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b"),
    "Private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}
MAX_GIT_FILE_BYTES = 95 * 1024 * 1024


def run(command: list[str]) -> None:
    completed = subprocess.run(command, cwd=ROOT, text=True, check=False)
    if completed.returncode:
        raise RuntimeError(f"Command failed ({completed.returncode}): {' '.join(command)}")


def source_files() -> list[Path]:
    files = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts):
            continue
        files.append(path)
    return files


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-tests", action="store_true")
    args = parser.parse_args()
    failures = []
    missing = sorted(path for path in REQUIRED if not (ROOT / path).is_file())
    if missing:
        failures.append(f"Missing required files: {missing}")
    for path in source_files():
        relative = path.relative_to(ROOT)
        if path.stat().st_size > MAX_GIT_FILE_BYTES:
            failures.append(f"Oversized Git candidate: {relative} ({path.stat().st_size} bytes)")
        if path.stat().st_size > 5 * 1024 * 1024:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                failures.append(f"{label} detected in {relative}")
    if not args.skip_tests and not failures:
        try:
            run([sys.executable, "-m", "ruff", "check", "."])
            run([sys.executable, "-m", "pytest", "-q"])
        except RuntimeError as exc:
            failures.append(str(exc))
    print(json.dumps({"ok": not failures, "scannedFiles": len(source_files()), "failures": failures}, indent=2, sort_keys=True))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
