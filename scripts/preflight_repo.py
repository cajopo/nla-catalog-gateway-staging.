#!/usr/bin/env python3
"""Fail closed when repository-only boundaries are violated."""

from __future__ import annotations

import hashlib
import html
import json
import math
import re
import shlex
import shutil
import subprocess
from collections import Counter, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, unquote, urlsplit

import yaml
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode

ROOT = Path(__file__).resolve().parents[1]
MAX_TRACKABLE_BYTES = 5 * 1024 * 1024
MAX_TRACKED_AGGREGATE_BYTES = 64 * 1024 * 1024
MAX_TRACKED_FILE_COUNT = 10_000
MAX_GIT_INDEX_BYTES = 8 * 1024 * 1024
MAX_GIT_OBJECT_SIZE_BYTES = 32
MAX_SHELL_SCAN_CHARS = 32 * 1024
MAX_SHELL_SCAN_DEPTH = 3
MAX_HEREDOC_QUEUE = 8
MAX_WORKFLOW_SCAN_NODES = 10_000
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
SHELL_SEPARATORS = {";", "&", "&&", "|", "|&", "||", "(", ")"}
SHELL_COMMAND_PREFIXES = {"!", "command", "env", "exec", "if", "sudo", "then", "time"}
SHELL_CONTROL_FLOW_WORDS = {
    "case",
    "catch",
    "do",
    "done",
    "elif",
    "else",
    "esac",
    "fi",
    "finally",
    "for",
    "foreach",
    "function",
    "if",
    "select",
    "switch",
    "then",
    "trap",
    "try",
    "until",
    "while",
    "{",
    "}",
}
POSIX_SHELL_EXECUTABLES = {"bash", "dash", "ksh", "sh", "zsh"}
CMD_EXECUTABLES = {"cmd", "cmd.exe"}
POWERSHELL_EXECUTABLES = {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}
SAFE_DIRECT_EXECUTABLES = {
    ":",
    "cat",
    "docker",
    "echo",
    "false",
    "get-command",
    "git",
    "new-item",
    "ni",
    "pip-audit",
    "printf",
    "pytest",
    "ruff",
    "set-content",
    "set-item",
    "sc",
    "si",
    "saps",
    "start-process",
    "true",
    "write-output",
}
POWERSHELL_PROVIDER_MUTATORS = {"new-item", "ni", "sc", "set-content", "set-item", "si"}
POWERSHELL_START_PROCESS_NAMES = {"saps", "start-process"}
SAFE_GIT_SUBCOMMANDS = {
    "cat-file",
    "diff",
    "log",
    "ls-files",
    "rev-parse",
    "show",
    "status",
    "version",
}
SAFE_GIT_CONFIG_KEYS = {"color.ui"}
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
ANSI_C_QUOTE_PATTERN = re.compile(r"\$'(?P<body>(?:\\.|[^'\\])*)'")
HEREDOC_DELIMITER_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}\Z")
PYTHON_EXECUTABLE_PATTERN = re.compile(r"(?:python(?:3(?:\.\d+)?)?|py)(?:\.exe)?\Z", re.I)
CMD_COMMAND_OPTION_PATTERN = re.compile(
    r"/(?:(?:(?:[audsq])|(?:[efv]:(?:on|off)))/)*"
    r"(?P<mode>c|k)(?P<payload>.*)\Z",
    re.IGNORECASE,
)
POWERSHELL_COMMAND_OPTIONS = {
    f"{prefix}{name[:length]}"
    for prefix in ("-", "/")
    for name in ("command",)
    for length in range(1, len(name) + 1)
}
POWERSHELL_ENCODED_COMMAND_OPTIONS = {
    f"{prefix}{name[:length]}"
    for prefix in ("-", "/")
    for name in ("encodedcommand",)
    for length in range(1, len(name) + 1)
}
WORKFLOW_EXPRESSION_PATTERN = re.compile(r"\$\{\{.*?\}\}", re.DOTALL)
SECRETS_IDENTIFIER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])secrets(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
GITHUB_COMMAND_FILE_IDENTIFIER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])GITHUB_(?:ENV|PATH)(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
COMMAND_RESOLUTION_ENV_ASSIGNMENT_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])(?:\$(?:env:(?:path|pathext)|\{env:(?:path|pathext)\})"
    r"|(?:path|pathext))\s*\+?=",
    re.IGNORECASE,
)
BASH_INDIRECT_EXPANSION_PATTERN = re.compile(r"\$\{![^}\r\n]+\}")
SHELL_SUBEXPRESSION_PATTERN = re.compile(r"(?:\$\(|<\(|>\(|@\()")
GIT_OBJECT_SIZE_PATTERN = re.compile(rb"(?:0|[1-9][0-9]*)(?:\r?\n)?\Z")
REMOVED_FIXTURE_PATH_SHA256 = "e5d2a692b1a78016d9e5164938c5968b53d408c9dd774d7e1b1bc98e5b296792"
REMOVED_PRODUCT_ID_SHA256 = frozenset(
    {
        "2150d71b7555d7492e0674cb978e4aaa60200a822aca30b7eca6419ccea935d8",
        "3eeb107a9fdc78c10db9e41100a052ad962bdd8675d0aaab5982b7aa0b49b7cc",
        "90bfd59d22b47668ec66958a3b70e5073d9a192916fefe7806925e2fa2b610a7",
        "cc5ff51b400b13f22b214cf92f12e05a981586a922473892a7d74e20ef3fa73a",
    }
)
REMOVED_TITLE_WORD_SHA256 = {
    9: frozenset({"e6b7215aacc422dadab37890b29459342448208362e9141b957ef202302b4569"}),
    10: frozenset({"a22b978f138b8bf6dfdb4405b48c83c7ab2c0c9ff89e16277f52c0ea1377dfe4"}),
    11: frozenset(
        {
            "1465626ed0f1dd190d1f11c1c590350b1572039e6e258f1f12212864e461d538",
            "261d3aecf007e47ad9565efb48e76065b1655a9ce8cdd5c5142241978be38c88",
        }
    ),
}
LONG_DECIMAL_PATTERN = re.compile(r"(?<![0-9])[0-9]{12,}(?![0-9])")
WORD_PATTERN = re.compile(r"[A-Za-z0-9]+")


class PreflightError(RuntimeError):
    """Raised when repository state cannot be inspected safely."""


@dataclass(frozen=True, slots=True)
class TrackedBlob:
    """One stage-zero Git index entry and its bounded regular-file bytes."""

    relative: Path
    mode: str
    content: bytes | None
    declared_size: int | None = None


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


def _git(
    root: Path,
    *arguments: str,
    max_output_bytes: int | None = None,
) -> bytes:
    git_executable = shutil.which("git")
    if git_executable is None:
        raise PreflightError("git executable not found")
    try:
        if max_output_bytes is not None:
            with subprocess.Popen(  # noqa: S603 - fixed executable, controlled arguments
                [git_executable, "-C", str(root), *arguments],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            ) as process:
                stdout = process.stdout
                if stdout is None:  # pragma: no cover - PIPE always supplies stdout
                    raise PreflightError("git stdout pipe unavailable")
                output = stdout.read(max_output_bytes + 1)
                if len(output) > max_output_bytes:
                    process.kill()
                    process.wait()
                    raise PreflightError(
                        f"git command output exceeds inspection limit: {' '.join(arguments)}"
                    )
                if process.wait() != 0:
                    raise PreflightError(f"git command failed: {' '.join(arguments)}")
                return output
        completed = subprocess.run(  # noqa: S603 - fixed executable, controlled arguments
            [git_executable, "-C", str(root), *arguments],
            check=True,
            capture_output=True,
        )
    except PreflightError:
        raise
    except (OSError, subprocess.CalledProcessError) as exc:
        raise PreflightError(f"git command failed: {' '.join(arguments)}") from exc
    return completed.stdout


def tracked_blobs(root: Path) -> list[TrackedBlob]:
    """Read bounded stage-zero regular-file bytes directly from the Git index."""
    entries = _git(
        root,
        "ls-files",
        "--stage",
        "-z",
        max_output_bytes=MAX_GIT_INDEX_BYTES,
    )
    if len(entries) > MAX_GIT_INDEX_BYTES:
        raise PreflightError("Git index listing exceeds inspection limit")

    indexed: list[tuple[Path, str, str]] = []
    seen_paths: set[Path] = set()
    for raw_entry in entries.split(b"\0"):
        if not raw_entry:
            continue
        if len(indexed) >= MAX_TRACKED_FILE_COUNT:
            raise PreflightError("tracked file count exceeds inspection limit")
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
        indexed.append((relative, mode, blob_sha))

    indexed.sort(key=lambda item: item[0].as_posix())
    sizes: dict[Path, int] = {}
    aggregate_size = 0
    for relative, mode, blob_sha in indexed:
        if mode not in {"100644", "100755"}:
            continue
        raw_size = _git(
            root,
            "cat-file",
            "-s",
            blob_sha,
            max_output_bytes=MAX_GIT_OBJECT_SIZE_BYTES,
        )
        if (
            len(raw_size) > MAX_GIT_OBJECT_SIZE_BYTES
            or GIT_OBJECT_SIZE_PATTERN.fullmatch(raw_size) is None
        ):
            raise PreflightError(f"cannot parse Git blob size: {relative.as_posix()}")
        size = int(raw_size.strip())
        sizes[relative] = size
        aggregate_size += size
        if aggregate_size > MAX_TRACKED_AGGREGATE_BYTES:
            raise PreflightError("tracked bytes exceed aggregate inspection limit")

    blobs: list[TrackedBlob] = []
    for relative, mode, blob_sha in indexed:
        if mode not in {"100644", "100755"}:
            blobs.append(
                TrackedBlob(
                    relative=relative,
                    mode=mode,
                    content=b"",
                    declared_size=0,
                )
            )
            continue
        size = sizes[relative]
        if size > MAX_TRACKABLE_BYTES:
            blobs.append(
                TrackedBlob(
                    relative=relative,
                    mode=mode,
                    content=None,
                    declared_size=size,
                )
            )
            continue
        content = _git(
            root,
            "cat-file",
            "blob",
            blob_sha,
            max_output_bytes=size,
        )
        if len(content) != size:
            raise PreflightError(f"Git blob size changed during inspection: {relative.as_posix()}")
        blobs.append(
            TrackedBlob(
                relative=relative,
                mode=mode,
                content=content,
                declared_size=size,
            )
        )
    return blobs


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


def _heredoc_openers(line: str) -> list[tuple[int, int, str, bool]] | None:
    """Return supported heredoc operators outside quotes and comments."""
    openers: list[tuple[int, int, str, bool]] = []
    in_single_quote = False
    in_double_quote = False
    index = 0
    while index < len(line):
        character = line[index]
        if character == "\\" and not in_single_quote:
            index += 2
            continue
        if character == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
            index += 1
            continue
        if character == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            index += 1
            continue
        if character == "#" and not in_single_quote and not in_double_quote:
            break
        if (
            character != "<"
            or in_single_quote
            or in_double_quote
            or not line.startswith("<<", index)
        ):
            index += 1
            continue
        if line.startswith("<<<", index):
            index += 3
            continue

        start = index
        index += 2
        if index < len(line) and line[index] == "-":
            return None
        while index < len(line) and line[index] in " \t":
            index += 1
        if index == len(line):
            return None

        quoted = line[index] == "'"
        if line[index] == '"':
            return None
        if quoted:
            delimiter_start = index + 1
            delimiter_end = line.find("'", delimiter_start)
            if delimiter_end == -1:
                return None
            delimiter = line[delimiter_start:delimiter_end]
            end = delimiter_end + 1
            if end < len(line) and line[end] not in " \t;&|()<>#":
                return None
        else:
            delimiter_start = index
            while index < len(line) and line[index] not in " \t;&|()<>":
                index += 1
            delimiter = line[delimiter_start:index]
            end = index
        if HEREDOC_DELIMITER_PATTERN.fullmatch(delimiter) is None:
            return None
        openers.append((start, end, delimiter, quoted))
        index = end
    return openers


def _supported_python_heredoc_header(
    line: str,
    openers: list[tuple[int, int, str, bool]],
) -> bool:
    characters = list(line)
    for start, end, _, _ in openers:
        characters[start:end] = " " * (end - start)
    header = "".join(characters)
    lexer = shlex.shlex(header, posix=True, punctuation_chars=";&|()")
    lexer.commenters = "#"
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        return False
    if not tokens or any(token in SHELL_SEPARATORS for token in tokens):
        return False
    return PYTHON_EXECUTABLE_PATTERN.fullmatch(_executable_name(tokens[0])) is not None


def _mask_heredoc_bodies(script: str) -> str | None:
    """Mask data sent directly to Python while preserving shell syntax."""
    masked: list[str] = []
    pending: list[tuple[str, bool]] = []
    for line in script.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        newline = line[len(content) :]
        if pending:
            delimiter, quoted = pending[0]
            if content == delimiter:
                pending.pop(0)
            elif not quoted and ("$" in content or "`" in content):
                return None
            masked.append(newline)
            continue

        openers = _heredoc_openers(content)
        if openers is None:
            return None
        if not openers:
            masked.append(line)
            continue
        if len(openers) > MAX_HEREDOC_QUEUE or not _supported_python_heredoc_header(
            content, openers
        ):
            return None
        pending.extend((delimiter, quoted) for _, _, delimiter, quoted in openers)
        masked.append(line)
    if pending:
        return None
    return "".join(masked)


def _normalize_ansi_c_quote(match: re.Match[str]) -> str:
    body = match.group("body")
    if "\\" in body:
        return "$__PREFLIGHT_DYNAMIC_ANSI_C__"
    return f"'{body}'"


def _shell_tokens(script: str) -> list[str] | None:
    normalized = re.sub(r"(?:\\|`)[ \t]*\r?\n[ \t]*", "", script)
    normalized = re.sub(r"`(?=[A-Za-z0-9_])", "", normalized)
    normalized = re.sub(r"\^(?=[A-Za-z0-9_])", "", normalized)
    normalized = ANSI_C_QUOTE_PATTERN.sub(_normalize_ansi_c_quote, normalized)
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
    return token.lstrip("@").replace("\\", "/").rsplit("/", 1)[-1].casefold()


def _is_dynamic_command_token(token: str) -> bool:
    """Identify shell-expanded tokens only where they select a command or Git verb."""
    if token in {"$", "@"} or "$" in token or token.startswith("&("):
        return True
    if re.search(
        r"![^!\s]+!|%[^%\s]+%|%(?:[0-9*]|~[A-Za-z0-9_$:.-]+)"
        r"|%%?(?:~[A-Za-z]*?)?[A-Za-z](?![A-Za-z0-9_])",
        token,
    ):
        return True
    return any(marker in token for marker in ("*", "?", "[", "{", "}"))


def _command_end(tokens: list[str], start: int) -> int:
    end = start
    while end < len(tokens) and tokens[end] not in SHELL_SEPARATORS:
        end += 1
    return end


def _uses_env_split_string(tokens: list[str], start: int, end: int) -> bool:
    index = start
    while index < end and "=" in tokens[index] and not tokens[index].startswith("="):
        index += 1
    while index < end and _executable_name(tokens[index]) in {"command", "exec"}:
        index += 1
        if index < end and tokens[index] in {"--", "-p"}:
            index += 1
    if index == end or _executable_name(tokens[index]) != "env":
        return False
    index += 1
    while index < end:
        argument = tokens[index]
        normalized = argument.casefold()
        long_option = normalized.partition("=")[0]
        if normalized.startswith("-s") or (
            long_option.startswith("--s") and "--split-string".startswith(long_option)
        ):
            return True
        if argument == "--":
            return False
        if "=" in argument and not argument.startswith("="):
            index += 1
            continue
        option_name = argument.partition("=")[0]
        if option_name in ENV_OPTIONS_WITHOUT_VALUES:
            index += 1
            continue
        if option_name in ENV_OPTIONS_WITH_VALUES:
            index += 1 if "=" in argument else 2
            if index > end:
                return False
            continue
        break
    return False


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
    if index < end and _is_dynamic_command_token(tokens[index]):
        return None
    return index


def _git_command_pushes(tokens: list[str], executable: int, end: int) -> bool | None:
    index = executable + 1
    while index < end:
        option = tokens[index]
        if option == "--":
            index += 1
            break
        if not option.startswith("-"):
            break
        config_value: str | None = None
        if option == "--config-env" or option.startswith("--config-env="):
            return None
        if option == "-c":
            if index + 1 == end:
                return None
            config_value = tokens[index + 1]
            index += 2
        elif option.startswith("-c="):
            config_value = option.partition("=")[2]
            index += 1
        elif option in GIT_OPTIONS_WITH_VALUES:
            if index + 1 == end:
                return None
            index += 2
        else:
            index += 1
        if config_value is not None:
            if _is_dynamic_command_token(config_value) or "=" not in config_value:
                return None
            config_key = config_value.partition("=")[0].casefold()
            if config_key not in SAFE_GIT_CONFIG_KEYS:
                return None
    if index == end:
        return False
    if _is_dynamic_command_token(tokens[index]):
        return None
    subcommand = tokens[index].casefold()
    if subcommand == "push":
        return True
    if subcommand in SAFE_GIT_SUBCOMMANDS:
        return False
    return None


def _contains_git_helper_environment_identifier(token: str) -> bool:
    return (
        re.search(
            r"(?:^|[^A-Za-z0-9_])(?:\$?env:)?(?:git_[A-Za-z0-9_]+|pager)"
            r"(?:\Z|[^A-Za-z0-9_])",
            token,
            re.IGNORECASE,
        )
        is not None
    )


def _is_allowed_executable_name(name: str) -> bool:
    direct_name = name.removesuffix(".exe")
    return (
        direct_name in SAFE_DIRECT_EXECUTABLES
        or name in POSIX_SHELL_EXECUTABLES
        or name in CMD_EXECUTABLES
        or name in POWERSHELL_EXECUTABLES
        or PYTHON_EXECUTABLE_PATTERN.fullmatch(name) is not None
    )


def _is_powershell_provider_mutator(tokens: list[str], executable: int) -> bool:
    return _executable_name(tokens[executable]).removesuffix(".exe") in POWERSHELL_PROVIDER_MUTATORS


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
            command_option = CMD_COMMAND_OPTION_PATTERN.fullmatch(argument)
            if command_option is not None:
                payload_parts = [command_option.group("payload"), *arguments[index + 1 :]]
                payload = " ".join(part for part in payload_parts if part)
                return True, payload or None
            if re.search(r"/[ck]", argument, re.IGNORECASE):
                return True, None
        return False, None
    if name in POWERSHELL_EXECUTABLES:
        for index, argument in enumerate(arguments):
            normalized = argument.casefold()
            if normalized in POWERSHELL_ENCODED_COMMAND_OPTIONS:
                return True, None
            if normalized in POWERSHELL_COMMAND_OPTIONS:
                payload = " ".join(arguments[index + 1 :])
                return True, payload or None
        return False, None
    if name in {"call", "eval", "iex", "invoke-expression"}:
        payload = " ".join(arguments)
        return True, payload or None
    if name in {"foreach-object", "icm", "invoke-command"}:
        return True, None
    if name in {".", "alias", "source"}:
        return True, None
    if name in {"start", "start.exe"}:
        return True, None
    if name.removesuffix(".exe") in POWERSHELL_START_PROCESS_NAMES:
        return True, None
    return False, None


def _contains_git_push(script: str, *, _depth: int = 0) -> bool | None:
    if len(script) > MAX_SHELL_SCAN_CHARS or _depth > MAX_SHELL_SCAN_DEPTH:
        return None
    masked_script = _mask_heredoc_bodies(script)
    if masked_script is None:
        return None
    script = masked_script
    resolution_script = re.sub(r"(?:\\|`)[ \t]*\r?\n[ \t]*", "", script)
    if BASH_INDIRECT_EXPANSION_PATTERN.search(
        resolution_script
    ) or SHELL_SUBEXPRESSION_PATTERN.search(resolution_script):
        return None
    resolution_tokens = _shell_tokens(resolution_script)
    if COMMAND_RESOLUTION_ENV_ASSIGNMENT_PATTERN.search(resolution_script) or (
        resolution_tokens is not None
        and any(
            COMMAND_RESOLUTION_ENV_ASSIGNMENT_PATTERN.search(token) for token in resolution_tokens
        )
    ):
        return None
    backtick_scan = _scan_backtick_substitutions(script)
    if backtick_scan is None:
        continued_script = re.sub(r"(?:\\|`)[ \t]*\r?\n[ \t]*", "", script)
        backtick_scan = _scan_backtick_substitutions(continued_script)
        if backtick_scan is None:
            return None
        script = continued_script
    substitutions, marked_script = backtick_scan
    for payload in substitutions:
        if _depth >= MAX_SHELL_SCAN_DEPTH:
            return None
        nested = _contains_git_push(payload, _depth=_depth + 1)
        if nested is not False:
            return nested
    tokens = _shell_tokens(marked_script)
    if tokens is None:
        return None

    index = 0
    git_environment_configured = False
    while index < len(tokens):
        if tokens[index : index + 2] in (["&", "("], ["&", "{"]):
            return None
        if tokens[index] in SHELL_SEPARATORS:
            index += 1
            continue
        if tokens[index].casefold() in SHELL_CONTROL_FLOW_WORDS:
            return None
        end = _command_end(tokens, index)
        if index + 2 < end and tokens[index + 1 : index + 3] == ["()", "{"]:
            return None
        if _uses_env_split_string(tokens, index, end):
            return None
        executable = _command_executable(tokens, index, end)
        if executable is None:
            return None
        if executable == end:
            if any(
                _contains_git_helper_environment_identifier(token) for token in tokens[index:end]
            ):
                git_environment_configured = True
            index = end
            continue
        executable_token = tokens[executable].lstrip("@")
        if "/" in executable_token or "\\" in executable_token:
            return None
        name = _executable_name(tokens[executable])
        if name in CMD_EXECUTABLES:
            end = len(tokens)
        if any(_contains_git_helper_environment_identifier(token) for token in tokens[index:end]):
            git_environment_configured = True
        if name in {"git", "git.exe"}:
            if git_environment_configured:
                return None
            pushes = _git_command_pushes(tokens, executable, end)
            if pushes is not False:
                return pushes
        if name.removesuffix(".exe") == "printf" and any(
            argument.startswith(("-v", "--variable")) for argument in tokens[executable + 1 : end]
        ):
            return None
        if _is_powershell_provider_mutator(tokens, executable):
            return None
        wrapped, payload = _wrapped_shell_payload(tokens, executable, end)
        if wrapped:
            if payload is None or _depth >= MAX_SHELL_SCAN_DEPTH:
                return None
            nested = _contains_git_push(payload, _depth=_depth + 1)
            if nested is not False:
                return nested
            index = end
            continue
        if not _is_allowed_executable_name(name):
            return None
        index = end
    return False


def _scan_backtick_substitutions(script: str) -> tuple[list[str], str] | None:
    payloads: list[str] = []
    marked_parts: list[str] = []
    last_marked = 0
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
        marked_parts.extend((script[last_marked:index], "$__PREFLIGHT_DYNAMIC_BACKTICK__"))
        last_marked = closing + 1
        index = closing + 1
    marked_parts.append(script[last_marked:])
    return payloads, "".join(marked_parts)


def _backtick_substitutions(script: str) -> list[str] | None:
    scan = _scan_backtick_substitutions(script)
    return None if scan is None else scan[0]


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


def _workflow_secret_reference(document: Any) -> bool | None:
    stack = [document]
    seen_containers: set[int] = set()
    scanned_nodes = 0
    while stack:
        scanned_nodes += 1
        if scanned_nodes > MAX_WORKFLOW_SCAN_NODES:
            return None
        current = stack.pop()
        if isinstance(current, str):
            if any(
                SECRETS_IDENTIFIER_PATTERN.search(expression)
                for expression in WORKFLOW_EXPRESSION_PATTERN.findall(current)
            ):
                return True
            continue
        if not isinstance(current, (dict, list)):
            continue
        identity = id(current)
        if identity in seen_containers:
            continue
        seen_containers.add(identity)
        if isinstance(current, dict):
            if any(isinstance(key, str) and key.casefold() == "secrets" for key in current):
                return True
            for key, value in current.items():
                stack.extend((key, value))
        else:
            stack.extend(current)
    return False


def _workflow_risky_environment(value: Any) -> bool | None:
    if value is None:
        return False
    if not isinstance(value, dict):
        return None
    for name in value:
        if not isinstance(name, str):
            return None
        if re.fullmatch(r"(?:git_[A-Za-z0-9_]+|pager|path|pathext)", name, re.IGNORECASE):
            return True
    return False


def _workflow_github_command_file_reference(script: str) -> bool | None:
    if GITHUB_COMMAND_FILE_IDENTIFIER_PATTERN.search(script):
        return True
    if "github_" not in script.casefold():
        return False
    tokens = _shell_tokens(script)
    if tokens is None:
        return None
    return any(GITHUB_COMMAND_FILE_IDENTIFIER_PATTERN.search(token) for token in tokens)


def workflow_failures(text: str) -> list[str]:
    """Inspect parsed workflow permissions and shell steps."""
    try:
        document = _load_workflow(text)
    except PreflightError:
        return ["invalid_yaml"]
    if not isinstance(document, dict):
        return ["invalid_yaml"]

    failures: list[str] = []
    capability_reference = _workflow_secret_reference(document)
    if capability_reference is None:
        failures.append("ambiguous_secret_reference")
    elif capability_reference:
        failures.append("secret_reference")
    workflow_helper_environment = _workflow_risky_environment(document.get("env"))
    if workflow_helper_environment is None:
        failures.append("ambiguous_env")
    elif workflow_helper_environment:
        failures.append("risky_environment")
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
        job_helper_environment = _workflow_risky_environment(job.get("env"))
        if job_helper_environment is None:
            failures.append("ambiguous_env")
        elif job_helper_environment:
            failures.append("risky_environment")
        container = job.get("container")
        if isinstance(container, dict):
            container_helper_environment = _workflow_risky_environment(container.get("env"))
            if container_helper_environment is None:
                failures.append("ambiguous_env")
            elif container_helper_environment:
                failures.append("risky_environment")
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
            step_helper_environment = _workflow_risky_environment(step.get("env"))
            if step_helper_environment is None:
                failures.append("ambiguous_env")
            elif step_helper_environment:
                failures.append("risky_environment")
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
            github_command_file = _workflow_github_command_file_reference(script)
            if github_command_file is None:
                failures.append("ambiguous_github_command_file")
            elif github_command_file:
                failures.append("github_command_file_reference")
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


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def removed_shopify_observation_failures(relative: Path, text: str) -> list[str]:
    """Reject source observations removed by issue #35 without retaining their values."""
    failures: list[str] = []
    if _sha256_text(relative.as_posix().casefold()) == REMOVED_FIXTURE_PATH_SHA256:
        failures.append("removed_shopify_observation_path")

    if any(
        _sha256_text(match.group()) in REMOVED_PRODUCT_ID_SHA256
        for match in LONG_DECIMAL_PATTERN.finditer(text)
    ):
        failures.append("removed_shopify_observation_identifier")

    word_window: deque[str] = deque(maxlen=max(REMOVED_TITLE_WORD_SHA256, default=1))
    title_found = False
    for match in WORD_PATTERN.finditer(text):
        word_window.append(match.group().casefold())
        words = tuple(word_window)
        if any(
            len(words) >= word_count
            and _sha256_text(" ".join(words[-word_count:])) in forbidden_digests
            for word_count, forbidden_digests in REMOVED_TITLE_WORD_SHA256.items()
        ):
            title_found = True
            break
    if title_found:
        failures.append("removed_shopify_observation_title")
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
        declared_size = (
            blob.declared_size if blob.declared_size is not None else len(blob.content or b"")
        )
        if declared_size > MAX_TRACKABLE_BYTES:
            failures.append({"path": relative_text, "reason": "file_larger_than_5_mib"})
            continue
        if blob.content is None:
            failures.append({"path": relative_text, "reason": "tracked_blob_content_missing"})
            continue
        if len(blob.content) != declared_size:
            failures.append({"path": relative_text, "reason": "tracked_blob_size_mismatch"})
            continue
        try:
            text = blob.content.decode("utf-8")
        except UnicodeDecodeError:
            failures.append({"path": relative_text, "reason": "non_utf8_repository_file"})
            continue

        for reason in secret_failures(text):
            failures.append({"path": relative_text, "reason": f"secret:{reason}"})
        for reason in removed_shopify_observation_failures(relative, text):
            failures.append({"path": relative_text, "reason": reason})
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
