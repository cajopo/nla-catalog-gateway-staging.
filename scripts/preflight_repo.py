#!/usr/bin/env python3
"""Fail closed when repository-only boundaries are violated."""

from __future__ import annotations

import html
import json
import math
import re
import shlex
import shutil
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, unquote, urlsplit

import yaml
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode

ROOT = Path(__file__).resolve().parents[1]
MAX_TRACKABLE_BYTES = 5 * 1024 * 1024
MAX_SHELL_SCAN_CHARS = 32 * 1024
MAX_SHELL_SCAN_DEPTH = 3
MAX_URL_DECODE_CHARS = 128 * 1024
MAX_URL_DECODE_STEPS = 6
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
    r"\.(?:db|sqlite|sqlite3)(?:[-.](?:journal|shm|wal|backup|bak|tmp))*"
    r"|\.jsonl"
    r"|\.tar(?:\.(?:gz|bz2|xz|zst))?"
    r"|\.(?:tgz|tbz2?|txz|zip|7z|rar|gz|bz2|xz|zst)"
    r"|\.(?:b64|base64)"
    r"|\.part(?:[-._]?\d+)?"
    r"|\.z\d{2}"
    r"|\.[rs]\d{2,3}"
    r"|\.\d{3}"
    r")\Z",
    re.IGNORECASE,
)
FORBIDDEN_FILE_WITH_WRAPPERS_PATTERN = re.compile(
    r"(?:"
    r"(?:"
    r"\.(?:db|sqlite|sqlite3)(?:[-.](?:journal|shm|wal|backup|bak|tmp))*"
    r"|\.jsonl"
    r"|\.tar(?:\.(?:gz|bz2|xz|zst))?"
    r"|\.(?:tgz|tbz2?|txz|zip|7z|rar|gz|bz2|xz|zst)"
    r")"
    r"(?:\.(?:b64|base64))?"
    r"|\.(?:b64|base64)"
    r")"
    r"(?:\.part(?:[-._]?\d+)?|\.\d{3})?\Z",
    re.IGNORECASE,
)
SPECIFIC_SECRET_PATTERNS = {
    "aws_access_key_id": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "github_token": re.compile(
        r"(?<![A-Za-z0-9_])(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"
        r"(?![A-Za-z0-9_])"
    ),
    "shopify_token": re.compile(
        r"(?<![A-Za-z0-9_])shp(?:at|ca|pa|ss)_[A-Za-z0-9]{20,}(?![A-Za-z0-9_])"
    ),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----"),
}
CREDENTIAL_NAME_PATTERN = r"""
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
        |SECRET[_-]?KEY
        |SECRET
    )
    [A-Z0-9_.-]*
"""
UNQUOTED_CREDENTIAL_ASSIGNMENT = re.compile(
    r"""
    (?:
        ^[ \t]*(?:-[ \t]+)?(?:export[ \t]+)?
        |[,\{][ \t]*
    )
    (?P<name>"""
    + CREDENTIAL_NAME_PATTERN
    + r""")
    [ \t]*[:=][ \t]*
    (?:
        "(?P<double_value>(?:\\.|[^"\\\r\n]){16,})"
        |'(?P<single_value>(?:\\.|[^'\\\r\n]){16,})'
        |(?P<bare_value>[^\s#;,\}\]]{16,})
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)
QUOTED_CREDENTIAL_ASSIGNMENT = re.compile(
    r"""
    (?:^[ \t]*(?:-[ \t]+)?|[,\{][ \t]*)
    (?P<key_quote>["'])
    (?P<name>"""
    + CREDENTIAL_NAME_PATTERN
    + r""")
    (?P=key_quote)
    [ \t]*:[ \t]*
    (?:
        "(?P<double_value>(?:\\.|[^"\\\r\n]){16,})"
        |'(?P<single_value>(?:\\.|[^'\\\r\n]){16,})'
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)
CREDENTIAL_ASSIGNMENT_PATTERNS = (
    UNQUOTED_CREDENTIAL_ASSIGNMENT,
    QUOTED_CREDENTIAL_ASSIGNMENT,
)
PLACEHOLDER_VALUE_PATTERN = re.compile(
    r"\A(?:"
    r"(?:change[-_ ]?me|not[-_ ]a[-_ ]secret|test[-_ ]only)"
    r"(?:[-_ ](?:placeholder|secret|token|key|value))?"
    r"|(?:dummy|example|fake|placeholder)(?:[-_ ](?:secret|token|key|password|value))?"
    r"|your[-_ ](?:api[-_ ]?key|access[-_ ]?key|access[-_ ]?token|auth[-_ ]?token"
    r"|client[-_ ]?secret|password|passwd|private[-_ ]?token|secret(?:[-_ ]?key)?)"
    r"|\$\{\{[ \t]*secrets\.[A-Z0-9_]+[ \t]*\}\}"
    r")\Z",
    re.IGNORECASE,
)
URL_PATTERN = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
SHELL_SEPARATORS = {";", "&", "&&", "|", "||", "(", ")"}
SHELL_COMMAND_PREFIXES = {"!", "command", "env", "exec", "if", "sudo", "then", "time"}
POSIX_SHELL_EXECUTABLES = {"bash", "dash", "ksh", "sh", "zsh"}
CMD_EXECUTABLES = {"cmd", "cmd.exe"}
POWERSHELL_EXECUTABLES = {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}
GIT_OPTIONS_WITH_VALUES = {
    "-c",
    "-C",
    "--config-env",
    "--exec-path",
    "--git-dir",
    "--namespace",
    "--super-prefix",
    "--work-tree",
}
SHOPIFY_PRODUCT_GID_PATTERN = re.compile(r"\Agid://shopify/Product/[1-9][0-9]*\Z")
SHOPIFY_SNAPSHOT_NAME_PATTERN = re.compile(
    r"(?:shopify[-_.]?)?(?:products?|snapshot)(?:[-_.][^.]+)*\.json\Z",
    re.IGNORECASE,
)
SHOPIFY_PRODUCT_FIELDS = {
    "handle",
    "producttype",
    "publishedat",
    "status",
    "tags",
    "title",
    "updatedat",
    "variants",
    "vendor",
}
JSON_URL_ESCAPE_PATTERN = re.compile(
    r"\\+(?P<escape>/|u[0-9A-Fa-f]{4})",
)
URL_ENCODING_HINT_PATTERN = re.compile(
    r"%(?:[0-9A-Fa-f]{2})|\\+(?:/|u[0-9A-Fa-f]{4})"
    r"|&(?:amp|#(?:[0-9]+|x[0-9A-Fa-f]+));",
    re.IGNORECASE,
)
ENV_OPTIONS_WITH_VALUES = {"-C", "--chdir", "-S", "--split-string", "-u", "--unset"}
ENV_OPTIONS_WITHOUT_VALUES = {"-0", "--debug", "-i", "--ignore-environment", "--null"}
POWERSHELL_LITERAL_CONCAT_PATTERN = re.compile(
    r"\([ \t]*(?:['\"][A-Za-z0-9_.-]+['\"][ \t]*\+[ \t]*)+"
    r"['\"][A-Za-z0-9_.-]+['\"][ \t]*\)",
)
POWERSHELL_LITERAL_PATTERN = re.compile(r"(['\"])([A-Za-z0-9_.-]+)\1")


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


def _shell_tokens(script: str) -> list[str] | None:
    normalized = re.sub(r"(?:\\|`)[ \t]*\r?\n[ \t]*", "", script)
    normalized = re.sub(r"`(?=[A-Za-z0-9_])", "", normalized)
    normalized = re.sub(r"\^(?=[A-Za-z0-9_])", "", normalized)
    normalized = re.sub(r"\$'((?:\\.|[^'\\])*)'", r"'\1'", normalized)
    normalized = POWERSHELL_LITERAL_CONCAT_PATTERN.sub(
        lambda match: "".join(
            part.group(2) for part in POWERSHELL_LITERAL_PATTERN.finditer(match.group(0))
        ),
        normalized,
    )
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n").replace("\n", ";")
    lexer = shlex.shlex(normalized, posix=True, punctuation_chars=";&|()")
    lexer.commenters = "#"
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError:
        return None


def _executable_name(token: str) -> str:
    return token.replace("\\", "/").rsplit("/", 1)[-1].casefold()


def _command_end(tokens: list[str], start: int) -> int:
    end = start
    while end < len(tokens) and tokens[end] not in SHELL_SEPARATORS:
        end += 1
    return end


def _command_executable(tokens: list[str], start: int, end: int) -> int | None:
    index = start
    while index < end:
        token = tokens[index]
        normalized = token.casefold()
        if "=" in token and not token.startswith("="):
            index += 1
            continue
        if normalized == "env":
            index += 1
            while index < end:
                option = tokens[index]
                if option == "--":
                    index += 1
                    break
                if "=" in option and not option.startswith("="):
                    index += 1
                    continue
                option_name = option.partition("=")[0]
                if option_name in ENV_OPTIONS_WITHOUT_VALUES:
                    index += 1
                    continue
                if option_name in ENV_OPTIONS_WITH_VALUES:
                    index += 1 if "=" in option else 2
                    if index > end:
                        return None
                    continue
                if option.startswith("-"):
                    return None
                break
            continue
        if normalized == "command":
            index += 1
            if index < end and tokens[index] == "--":
                index += 1
            elif index < end and tokens[index] == "-p":
                index += 1
            elif index < end and tokens[index] in {"-V", "-v"}:
                return end
            continue
        if normalized in SHELL_COMMAND_PREFIXES:
            index += 1
            if index < end and tokens[index].startswith("-"):
                return None
            continue
        break
    return index


def _git_command_pushes(tokens: list[str], executable: int, end: int) -> bool:
    index = executable + 1
    while index < end:
        option = tokens[index]
        if option == "--":
            index += 1
            break
        if not option.startswith("-"):
            break
        index += 1
        if option in GIT_OPTIONS_WITH_VALUES and "=" not in option and index < end:
            index += 1
    return index < end and tokens[index].casefold() == "push"


def _wrapped_shell_payload(
    tokens: list[str],
    executable: int,
    end: int,
) -> tuple[bool, str | None]:
    name = _executable_name(tokens[executable])
    arguments = tokens[executable + 1 : end]
    if name in POSIX_SHELL_EXECUTABLES:
        for index, argument in enumerate(arguments):
            is_command_flag = argument == "-c" or bool(
                re.fullmatch(r"-[A-Za-z]*c[A-Za-z]*", argument)
            )
            if is_command_flag:
                return True, arguments[index + 1] if index + 1 < len(arguments) else None
        return False, None
    if name in CMD_EXECUTABLES:
        for index, argument in enumerate(arguments):
            if argument.casefold() in {"/c", "/k"}:
                payload = " ".join(arguments[index + 1 :])
                return True, payload or None
        return False, None
    if name in POWERSHELL_EXECUTABLES:
        for index, argument in enumerate(arguments):
            normalized = argument.casefold()
            if normalized in {"-encodedcommand", "-enc", "-e"}:
                return True, None
            if normalized in {"-command", "-c"}:
                payload = " ".join(arguments[index + 1 :])
                return True, payload or None
        return False, None
    if name in {"call", "eval"}:
        payload = " ".join(arguments)
        return True, payload or None
    if name == "start-process":
        file_path: str | None = None
        for index, argument in enumerate(arguments):
            if argument.casefold() in {"-filepath", "-file"}:
                file_path = arguments[index + 1] if index + 1 < len(arguments) else None
                break
            if not argument.startswith("-"):
                file_path = argument
                break
        if file_path is None:
            return True, None
        if _executable_name(file_path) not in {"git", "git.exe"}:
            return False, None
        if any(argument.strip("',").casefold() == "push" for argument in arguments):
            return True, "git push"
        return False, None
    return False, None


def _contains_git_push(script: str, *, _depth: int = 0) -> bool | None:
    if len(script) > MAX_SHELL_SCAN_CHARS or _depth > MAX_SHELL_SCAN_DEPTH:
        return None
    substitutions = _backtick_substitutions(script)
    if substitutions is None:
        continued_script = re.sub(r"(?:\\|`)[ \t]*\r?\n[ \t]*", "", script)
        substitutions = _backtick_substitutions(continued_script)
        if substitutions is None:
            return None
    for payload in substitutions:
        if _depth >= MAX_SHELL_SCAN_DEPTH:
            return None
        nested = _contains_git_push(payload, _depth=_depth + 1)
        if nested is not False:
            return nested
    tokens = _shell_tokens(script)
    if tokens is None:
        return None

    index = 0
    while index < len(tokens):
        if tokens[index] in SHELL_SEPARATORS:
            index += 1
            continue
        end = _command_end(tokens, index)
        executable = _command_executable(tokens, index, end)
        if executable is None:
            return None
        if executable == end:
            index = end
            continue
        name = _executable_name(tokens[executable])
        if name in {"git", "git.exe"} and _git_command_pushes(tokens, executable, end):
            return True
        wrapped, payload = _wrapped_shell_payload(tokens, executable, end)
        if wrapped:
            if payload is None or _depth >= MAX_SHELL_SCAN_DEPTH:
                return None
            nested = _contains_git_push(payload, _depth=_depth + 1)
            if nested is not False:
                return nested
        index = end
    return False


def _backtick_substitutions(script: str) -> list[str] | None:
    payloads: list[str] = []
    in_single_quote = False
    in_double_quote = False
    index = 0
    while index < len(script):
        character = script[index]
        if character == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
            index += 1
            continue
        if character == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            index += 1
            continue
        if character != "`" or in_single_quote:
            index += 1
            continue
        closing = index + 1
        while closing < len(script):
            if script[closing] == "`" and script[closing - 1] != "\\":
                break
            closing += 1
        if closing == len(script):
            if index > 0 and (script[index - 1].isalnum() or script[index - 1] == "_"):
                index += 2
                continue
            return None
        payloads.append(script[index + 1 : closing])
        index = closing + 1
    return payloads


def _checkout_failures(step: dict[Any, Any]) -> list[str]:
    uses = step.get("uses")
    if uses is None:
        return []
    if not isinstance(uses, str):
        return ["ambiguous_uses_step"]
    if uses.partition("@")[0].casefold() != "actions/checkout":
        return []

    inputs = step.get("with")
    if not isinstance(inputs, dict):
        return ["checkout_persist_credentials"]
    value = inputs.get("persist-credentials")
    if value is False:
        return []
    return ["checkout_persist_credentials"]


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
            failures.extend(_checkout_failures(step))
            if "run" not in step:
                continue
            script = step["run"]
            if not isinstance(script, str):
                failures.append("invalid_run_step")
                continue
            contains_push = _contains_git_push(script)
            if contains_push is None:
                failures.append("ambiguous_run_step")
            elif contains_push:
                failures.append("git_push")
    return failures


def _shannon_entropy(value: str) -> float:
    counts = Counter(value)
    length = len(value)
    return -sum((count / length) * math.log2(count / length) for count in counts.values())


def _looks_like_placeholder(value: str) -> bool:
    return PLACEHOLDER_VALUE_PATTERN.fullmatch(value.strip()) is not None


def _decode_url_text(value: str) -> tuple[str, bool]:
    """Decode URL-relevant escaping to stability within strict resource bounds."""
    if len(value) > MAX_URL_DECODE_CHARS:
        return value, URL_ENCODING_HINT_PATTERN.search(value) is None
    decoded = value
    for _ in range(MAX_URL_DECODE_STEPS):
        next_value = html.unescape(decoded)
        next_value = JSON_URL_ESCAPE_PATTERN.sub(
            _decode_json_url_escape,
            next_value,
        )
        next_value = unquote(next_value)
        if next_value == decoded:
            return decoded, True
        decoded = next_value
    next_value = html.unescape(decoded)
    next_value = JSON_URL_ESCAPE_PATTERN.sub(
        _decode_json_url_escape,
        next_value,
    )
    next_value = unquote(next_value)
    return decoded, next_value == decoded


def _decode_json_url_escape(match: re.Match[str]) -> str:
    escape = match.group("escape")
    if escape == "/":
        return "/"
    return chr(int(escape[1:], 16))


def _is_signed_capability_url(raw_url: str) -> bool | None:
    decoded, converged = _decode_url_text(raw_url)
    if not converged:
        return None
    try:
        parsed = urlsplit(decoded)
        host = (parsed.hostname or "").casefold()
    except ValueError:
        return False
    parameter_names = {
        name.casefold() for name, _ in parse_qsl(parsed.query, keep_blank_values=True)
    }

    google_host = host == "storage.googleapis.com" or host.endswith(".storage.googleapis.com")
    amazon_host = host == "amazonaws.com" or host.endswith(".amazonaws.com")
    azure_host = host == "blob.core.windows.net" or host.endswith(".blob.core.windows.net")
    if google_host and parameter_names.intersection(
        {"googleaccessid", "signature", "x-goog-signature"}
    ):
        return True
    if amazon_host and parameter_names.intersection(
        {"awsaccesskeyid", "signature", "x-amz-signature"}
    ):
        return True
    return azure_host and "sig" in parameter_names


def _shopify_product_record(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    normalized_keys = {
        re.sub(r"[-_]", "", key).casefold(): item
        for key, item in value.items()
        if isinstance(key, str)
    }
    product_id = normalized_keys.get("id")
    if product_id is None:
        product_id = normalized_keys.get("admingraphqlapiid")
    if product_id is None:
        product_id = normalized_keys.get("gid")
    if product_id is None:
        product_id = normalized_keys.get("shopifyproductgid")
    product_fields = SHOPIFY_PRODUCT_FIELDS.intersection(normalized_keys)
    graphql_product = (
        isinstance(product_id, str)
        and SHOPIFY_PRODUCT_GID_PATTERN.fullmatch(product_id) is not None
        and len(product_fields) >= 2
    )
    rest_product = (
        isinstance(product_id, int)
        and not isinstance(product_id, bool)
        and product_id > 0
        and {"title", "variants"}.issubset(normalized_keys)
    )
    return graphql_product or rest_product


def _contains_shopify_product(value: object) -> bool:
    stack: list[object] = [value]
    while stack:
        current = stack.pop()
        if _shopify_product_record(current):
            return True
        if isinstance(current, dict):
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)
    return False


def _looks_like_shopify_snapshot(relative: Path, text: str) -> bool:
    if relative.suffix.casefold() != ".json":
        return False
    try:
        document = json.loads(text)
    except (json.JSONDecodeError, RecursionError):
        return False

    contains_product = _contains_shopify_product(document)
    if contains_product is True:
        return True
    canonical_name = SHOPIFY_SNAPSHOT_NAME_PATTERN.fullmatch(relative.name) is not None
    if canonical_name and isinstance(document, list):
        return True
    if not canonical_name or not isinstance(document, dict):
        return False
    products = document.get("products")
    return isinstance(products, list)


def secret_failures(text: str) -> list[str]:
    failures: list[str] = []
    seen_failures: set[str] = set()

    for line in text.splitlines():
        decoded_line, converged = _decode_url_text(line)
        variants = (line,) if decoded_line == line else (line, decoded_line)
        for variant in variants:
            for name, pattern in SPECIFIC_SECRET_PATTERNS.items():
                if name not in seen_failures and pattern.search(variant):
                    failures.append(name)
                    seen_failures.add(name)
        if not converged:
            reason = "ambiguous_capability_url_encoding"
            if reason not in seen_failures:
                failures.append(reason)
                seen_failures.add(reason)
        url_states = [
            _is_signed_capability_url(match.group(0))
            for match in URL_PATTERN.finditer(decoded_line)
        ]
        if any(state is True for state in url_states):
            reason = "signed_capability_url"
            if reason not in seen_failures:
                failures.append(reason)
                seen_failures.add(reason)
        for variant in variants:
            for pattern in CREDENTIAL_ASSIGNMENT_PATTERNS:
                for match in pattern.finditer(variant):
                    value = next(
                        candidate
                        for candidate in (
                            match.group("double_value"),
                            match.group("single_value"),
                            match.groupdict().get("bare_value"),
                        )
                        if candidate is not None
                    )
                    reason = f"credential_assignment:{match.group('name').casefold()}"
                    if (
                        reason not in seen_failures
                        and not _looks_like_placeholder(value)
                        and _shannon_entropy(value) >= 2.5
                    ):
                        failures.append(reason)
                        seen_failures.add(reason)
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
        if any(part.casefold() in FORBIDDEN_TRACKED_DIRS for part in relative.parts):
            failures.append({"path": relative_text, "reason": "forbidden_tracked_path"})
        forbidden_filename = FORBIDDEN_FILE_PATTERN.search(
            relative.name
        ) or FORBIDDEN_FILE_WITH_WRAPPERS_PATTERN.search(relative.name)
        if forbidden_filename:
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
        if _looks_like_shopify_snapshot(relative, text):
            failures.append({"path": relative_text, "reason": "forbidden_shopify_snapshot"})
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
