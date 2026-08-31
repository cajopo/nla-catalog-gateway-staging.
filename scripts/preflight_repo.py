#!/usr/bin/env python3
"""Fail closed when repository-only boundaries are violated."""

from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode

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
    "output",
}
FORBIDDEN_FILE_PATTERN = re.compile(
    r"(?:"
    r"\.(?:db|sqlite|sqlite3)(?:[-.](?:journal|shm|wal|backup|bak|tmp))?"
    r"|\.jsonl(?:\.[a-z0-9]+)?"
    r"|\.tar\.gz"
    r"|\.tgz"
    r"|\.zip"
    r"|\.zst"
    r")\Z",
    re.IGNORECASE,
)
SPECIFIC_SECRET_PATTERNS = {
    "aws_access_key_id": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "github_token": re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b"),
    "shopify_access_token": re.compile(r"\bshpat_[A-Za-z0-9]{20,}\b"),
    "shopify_shared_secret": re.compile(r"\bshpss_[A-Za-z0-9]{20,}\b"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}
GENERIC_SECRET_ASSIGNMENT = re.compile(
    r"""(?ix)
    \b
    (?P<name>
        [A-Z0-9_.-]*
        (?:
            API[_-]?KEY
            |ACCESS[_-]?KEY
            |ACCESS[_-]?TOKEN
            |AUTH[_-]?TOKEN
            |CLIENT[_-]?SECRET
            |PASSWORD
            |PASSWD
            |PRIVATE[_-]?TOKEN
            |SECRET
        )
        [A-Z0-9_.-]*
    )
    \s*[:=]\s*
    (?:[bru]{0,2})?
    (?P<quote>["']?)
    (?P<value>[A-Za-z0-9+/=_.:-]{16,})
    (?P=quote)
    """
)
ALLOWLIST_MARKER = "pragma: allowlist " + "secret"
PLACEHOLDER_MARKERS = (
    "change-me",
    "changeme",
    "dummy",
    "example",
    "fake",
    "not-a-secret",
    "placeholder",
    "test-only",
    "your-",
)
GIT_PUSH_PATTERN = re.compile(
    r"\bgit\b[ \t]+(?:-[^;\r\n|&]+[ \t]+)*push\b",
    re.IGNORECASE,
)


class PreflightError(RuntimeError):
    """Raised when repository state cannot be inspected safely."""


@dataclass(frozen=True, slots=True)
class TrackedBlob:
    """One stage-zero Git index entry and its exact blob bytes."""

    relative: Path
    mode: str
    content: bytes


class UniqueKeySafeLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate or unhashable mapping keys."""


def _construct_unique_mapping(
    loader: UniqueKeySafeLoader,
    node: MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found an unhashable key",
                key_node.start_mark,
            ) from exc
        if duplicate:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _git(root: Path, *arguments: str) -> bytes:
    git_executable = shutil.which("git")
    if git_executable is None:
        raise PreflightError("git executable not found")
    try:
        completed = subprocess.run(  # noqa: S603 - fixed executable, controlled arguments
            [git_executable, "-C", str(root), *arguments],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise PreflightError(f"git command failed: {' '.join(arguments)}") from exc
    return completed.stdout


def tracked_blobs(root: Path) -> list[TrackedBlob]:
    """Read stage-zero paths and bytes directly from the Git index."""
    entries = _git(root, "ls-files", "--stage", "-z")
    blobs: list[TrackedBlob] = []
    seen_paths: set[Path] = set()
    for raw_entry in entries.split(b"\0"):
        if not raw_entry:
            continue
        try:
            metadata, raw_path = raw_entry.split(b"\t", 1)
            mode_bytes, sha_bytes, stage_bytes = metadata.split()
            mode = mode_bytes.decode("ascii")
            blob_sha = sha_bytes.decode("ascii")
            stage = stage_bytes.decode("ascii")
            relative = Path(raw_path.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise PreflightError("cannot parse Git index entry") from exc
        if stage != "0":
            raise PreflightError(f"unmerged Git index entry: {relative.as_posix()}")
        if relative in seen_paths:
            raise PreflightError(f"duplicate Git index path: {relative.as_posix()}")
        seen_paths.add(relative)
        content = _git(root, "cat-file", "blob", blob_sha)
        blobs.append(TrackedBlob(relative=relative, mode=mode, content=content))
    return sorted(blobs, key=lambda item: item.relative.as_posix())


def _load_workflow(text: str) -> Any:
    loader = UniqueKeySafeLoader(text)
    try:
        return loader.get_single_data()
    except yaml.YAMLError as exc:
        raise PreflightError("invalid or ambiguous workflow YAML") from exc
    finally:
        loader.dispose()


def _permission_failures(value: Any) -> list[str]:
    if isinstance(value, str):
        normalized = value.casefold()
        if normalized == "read-all":
            return []
        if normalized == "write-all":
            return ["write_permission"]
        return ["ambiguous_permissions"]
    if not isinstance(value, dict):
        return ["ambiguous_permissions"]

    failures: list[str] = []
    for scope, access in value.items():
        if not isinstance(scope, str) or not isinstance(access, str):
            failures.append("ambiguous_permissions")
            continue
        normalized = access.casefold()
        if normalized == "write":
            failures.append(f"write_permission:{scope}")
        elif normalized not in {"read", "none"}:
            failures.append("ambiguous_permissions")
    return failures


def _normalized_shell(script: str) -> str:
    return re.sub(r"\\[ \t]*\r?\n[ \t]*", " ", script)


def workflow_failures(text: str) -> list[str]:
    """Inspect parsed workflow permissions and shell steps."""
    try:
        document = _load_workflow(text)
    except PreflightError:
        return ["invalid_yaml"]
    if not isinstance(document, dict):
        return ["invalid_yaml"]

    failures: list[str] = []
    if "permissions" not in document:
        failures.append("missing_top_level_permissions")
    else:
        failures.extend(_permission_failures(document["permissions"]))

    jobs = document.get("jobs")
    if jobs is None:
        return failures
    if not isinstance(jobs, dict):
        return [*failures, "invalid_jobs"]

    for job_name, job in jobs.items():
        if not isinstance(job_name, str) or not isinstance(job, dict):
            failures.append("invalid_job")
            continue
        if "permissions" in job:
            failures.extend(_permission_failures(job["permissions"]))
        if "steps" not in job:
            continue
        steps = job["steps"]
        if not isinstance(steps, list):
            failures.append("invalid_steps")
            continue
        for step in steps:
            if not isinstance(step, dict):
                failures.append("invalid_step")
                continue
            if "run" not in step:
                continue
            script = step["run"]
            if not isinstance(script, str):
                failures.append("invalid_run_step")
            elif GIT_PUSH_PATTERN.search(_normalized_shell(script)):
                failures.append("git_push")
    return failures


def _shannon_entropy(value: str) -> float:
    counts = Counter(value)
    length = len(value)
    return -sum((count / length) * math.log2(count / length) for count in counts.values())


def _looks_like_placeholder(value: str) -> bool:
    normalized = value.casefold()
    return any(marker in normalized for marker in PLACEHOLDER_MARKERS)


def secret_failures(text: str) -> list[str]:
    failures: list[str] = []
    for name, pattern in SPECIFIC_SECRET_PATTERNS.items():
        if pattern.search(text):
            failures.append(name)

    capability_hosts = (
        "storage." + "googleapis.com",
        "amazonaws." + "com",
        "blob.core." + "windows.net",
    )
    signature_markers = (
        "x-goog-" + "signature=",
        "x-amz-" + "signature=",
        "googleaccessid=",
        "sig=",
    )
    for line in text.splitlines():
        if ALLOWLIST_MARKER in line.casefold():
            continue
        normalized = line.casefold()
        if any(host in normalized for host in capability_hosts) and any(
            marker in normalized for marker in signature_markers
        ):
            failures.append("signed_capability_url")
        for match in GENERIC_SECRET_ASSIGNMENT.finditer(line):
            value = match.group("value")
            if not _looks_like_placeholder(value) and _shannon_entropy(value) >= 2.5:
                failures.append(f"credential_assignment:{match.group('name').casefold()}")
    return failures


def run_preflight(root: Path) -> dict[str, Any]:
    failures: list[dict[str, str]] = []
    try:
        blobs = tracked_blobs(root)
    except PreflightError as exc:
        return {
            "failures": [{"path": ".", "reason": f"repository_inspection:{exc}"}],
            "ok": False,
            "scannedFiles": 0,
        }

    for blob in blobs:
        relative = blob.relative
        relative_text = relative.as_posix()
        if blob.mode == "120000":
            failures.append({"path": relative_text, "reason": "tracked_symlink"})
            continue
        if blob.mode not in {"100644", "100755"}:
            failures.append({"path": relative_text, "reason": f"unsupported_git_mode:{blob.mode}"})
        if any(part in FORBIDDEN_TRACKED_DIRS for part in relative.parts):
            failures.append({"path": relative_text, "reason": "forbidden_tracked_path"})
        if FORBIDDEN_FILE_PATTERN.search(relative.name):
            failures.append({"path": relative_text, "reason": "forbidden_artifact_type"})
        if len(blob.content) > MAX_TRACKABLE_BYTES:
            failures.append({"path": relative_text, "reason": "file_larger_than_5_mib"})
        try:
            text = blob.content.decode("utf-8")
        except UnicodeDecodeError:
            failures.append({"path": relative_text, "reason": "non_utf8_repository_file"})
            continue

        for reason in secret_failures(text):
            failures.append({"path": relative_text, "reason": f"secret:{reason}"})
        if relative.parts[:2] == (".github", "workflows"):
            for reason in workflow_failures(text):
                failures.append({"path": relative_text, "reason": f"workflow:{reason}"})

    return {
        "failures": failures,
        "ok": not failures,
        "scannedFiles": len(blobs),
    }


def main() -> int:
    report = run_preflight(ROOT)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
