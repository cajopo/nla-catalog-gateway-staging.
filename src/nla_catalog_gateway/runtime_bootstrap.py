"""Fail-closed host configuration and composition for the staging ASGI app."""

from __future__ import annotations

import base64
import binascii
import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import uvicorn

from nla_catalog_gateway.app_proxy_security import AppProxyVerifier, AppProxyVerifierConfig
from nla_catalog_gateway.pagination import CursorCodecV1
from nla_catalog_gateway.runtime_api import (
    AppProxyVerifierAuthorizer,
    EvidenceBoundCapabilityGate,
    EvidenceBoundCatalogBackend,
    RuntimeCatalogService,
    RuntimeLimits,
)
from nla_catalog_gateway.runtime_server import RuntimeAsgiApp, create_runtime_app
from nla_catalog_gateway.staging_activation import (
    ABSENT_ACTIVATION_SHA256,
    GENERATIONS_DIRECTORY,
    _fsync_directory,
    load_active_staging_generation,
)
from nla_catalog_gateway.staging_generation import REPOSITORY_ROOT

_ERROR = "runtime bootstrap configuration is invalid"
_LIMIT_CONCURRENCY = 32
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_CODE_SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
_POSITIVE_INTEGER_RE = re.compile(r"[1-9][0-9]*\Z")

_SHOP_DOMAIN = "NLA_SHOP_DOMAIN"
_SIGNED_PATH_PREFIX = "NLA_APP_PROXY_SIGNED_PATH_PREFIX"
_BACKEND_PATH = "NLA_APP_PROXY_BACKEND_PATH"
_APP_PROXY_MATERIAL_ENV = "NLA_APP_PROXY_SHARED_SECRET_B64"
_CURSOR_MATERIAL_ENV = "NLA_CURSOR_HMAC_SECRET_B64"
_STORE_ROOT = "NLA_STAGING_STORE_ROOT"
_ACTIVATION_SHA256 = "NLA_ACTIVATION_SHA256"
_EVIDENCE_CODE_SHA = "NLA_EVIDENCE_CODE_SHA"
_CURSOR_TTL_SECONDS = "NLA_CURSOR_TTL_SECONDS"
_REQUEST_TIMEOUT_MS = "NLA_REQUEST_TIMEOUT_MS"
_ALLOW_EMPTY_STORE = "NLA_ALLOW_EMPTY_STAGING_STORE"
_PORT = "PORT"
_REPARSE_POINT_ATTRIBUTE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_CONCRETE_PATH_TYPE = type(Path())


class RuntimeBootstrapError(ValueError):
    """A fixed, value-free startup rejection."""


@dataclass(frozen=True, slots=True, repr=False)
class _RuntimeBootstrapConfig:
    shop_domain: str
    signed_path_prefix: str
    backend_path: str
    app_proxy_material: bytes = field(repr=False)
    cursor_material: bytes = field(repr=False)
    store_root: Path = field(repr=False)
    activation_sha256: str = field(repr=False)
    evidence_code_sha: str
    cursor_ttl_seconds: int
    request_timeout_ms: int
    allow_empty_store: bool


def _fail() -> RuntimeBootstrapError:
    return RuntimeBootstrapError(_ERROR)


def _required(environ: Mapping[str, str], name: str) -> str:
    value = environ.get(name)
    if type(value) is not str or not value:
        raise _fail()
    return value


def _base64_secret(environ: Mapping[str, str], name: str) -> bytes:
    value = _required(environ, name)
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        raise _fail() from None
    if base64.b64encode(decoded).decode("ascii") != value:
        raise _fail()
    return decoded


def _positive_integer(environ: Mapping[str, str], name: str, default: int) -> int:
    value = environ.get(name)
    if value is None:
        return default
    if type(value) is not str or _POSITIVE_INTEGER_RE.fullmatch(value) is None:
        raise _fail()
    return int(value)


def _boolean(environ: Mapping[str, str], name: str, default: bool) -> bool:
    value = environ.get(name)
    if value is None:
        return default
    if value == "true":
        return True
    if value == "false":
        return False
    raise _fail()


def _plain_directory(path: Path) -> bool:
    facts = path.stat(follow_symlinks=False)
    return stat.S_ISDIR(facts.st_mode) and not bool(
        getattr(facts, "st_file_attributes", 0) & _REPARSE_POINT_ATTRIBUTE
    )


def _directory_identity(path: Path) -> tuple[int, int]:
    facts = path.stat(follow_symlinks=False)
    if not _plain_directory(path):
        raise OSError
    return facts.st_dev, facts.st_ino


def _require_directory_identity(path: Path, expected: tuple[int, int]) -> None:
    if _directory_identity(path) != expected:
        raise OSError


def _bounded_names(path: Path, maximum: int) -> tuple[str, ...]:
    names: list[str] = []
    with os.scandir(path) as entries:
        for entry in entries:
            names.append(entry.name)
            if len(names) > maximum:
                raise OSError
    return tuple(names)


def _validated_empty_store_root(value: Path) -> Path:
    if type(value) is not _CONCRETE_PATH_TYPE or not value.is_absolute():
        raise OSError
    root = value.resolve(strict=True)
    if (
        root != value
        or value.is_symlink()
        or not _plain_directory(value)
        or root == REPOSITORY_ROOT
        or root.is_relative_to(REPOSITORY_ROOT)
    ):
        raise OSError
    return root


def _is_clean_empty_store(root: Path) -> bool:
    try:
        root = _validated_empty_store_root(root)
        _directory_identity(root)
        names = _bounded_names(root, 1)
        if names != (GENERATIONS_DIRECTORY,):
            return False
        generations = root / GENERATIONS_DIRECTORY
        _directory_identity(generations)
        return not _bounded_names(generations, 0)
    except OSError:
        return False


def _initialize_clean_empty_store(root: Path) -> bool:
    try:
        root = _validated_empty_store_root(root)
        identity = _directory_identity(root)
        names = _bounded_names(root, 1)
        if not names:
            _require_directory_identity(root, identity)
            try:
                (root / GENERATIONS_DIRECTORY).mkdir(mode=stat.S_IRWXU)
            except FileExistsError:
                pass
            _require_directory_identity(root, identity)
            _fsync_directory(root)
            _require_directory_identity(root, identity)
        elif names != (GENERATIONS_DIRECTORY,):
            return False
        return _is_clean_empty_store(root)
    except OSError:
        return False


def _configuration(environ: Mapping[str, str]) -> _RuntimeBootstrapConfig:
    if not isinstance(environ, Mapping):
        raise _fail()
    store_root = Path(_required(environ, _STORE_ROOT))
    activation_sha256 = _required(environ, _ACTIVATION_SHA256)
    evidence_code_sha = _required(environ, _EVIDENCE_CODE_SHA)
    if (
        not store_root.is_absolute()
        or _SHA256_RE.fullmatch(activation_sha256) is None
        or _CODE_SHA_RE.fullmatch(evidence_code_sha) is None
    ):
        raise _fail()
    return _RuntimeBootstrapConfig(
        shop_domain=_required(environ, _SHOP_DOMAIN),
        signed_path_prefix=_required(environ, _SIGNED_PATH_PREFIX),
        backend_path=_required(environ, _BACKEND_PATH),
        app_proxy_material=_base64_secret(environ, _APP_PROXY_MATERIAL_ENV),
        cursor_material=_base64_secret(environ, _CURSOR_MATERIAL_ENV),
        store_root=store_root,
        activation_sha256=activation_sha256,
        evidence_code_sha=evidence_code_sha,
        cursor_ttl_seconds=_positive_integer(environ, _CURSOR_TTL_SECONDS, 1_800),
        request_timeout_ms=_positive_integer(environ, _REQUEST_TIMEOUT_MS, 2_000),
        allow_empty_store=_boolean(environ, _ALLOW_EMPTY_STORE, False),
    )


def _compose(config: _RuntimeBootstrapConfig) -> RuntimeAsgiApp:
    limits = RuntimeLimits(request_timeout_ms=config.request_timeout_ms)
    cursor_codec = CursorCodecV1(config.cursor_material, config.cursor_ttl_seconds)
    verifier = AppProxyVerifier(
        AppProxyVerifierConfig(
            config.app_proxy_material,
            allowed_shops=frozenset({config.shop_domain}),
            allowed_path_prefixes=frozenset({config.signed_path_prefix}),
            backend_path_prefix=config.backend_path,
        )
    )
    backend: EvidenceBoundCatalogBackend | None
    capability_gate: EvidenceBoundCapabilityGate | None
    try:
        active = load_active_staging_generation(config.store_root, config.activation_sha256)
    except Exception:
        if (
            not config.allow_empty_store
            or config.activation_sha256 != ABSENT_ACTIVATION_SHA256
            or not _initialize_clean_empty_store(config.store_root)
        ):
            raise
        backend = None
        capability_gate = None
    else:
        backend = EvidenceBoundCatalogBackend.from_staging_generation(
            active.generation,
            cursor_codec,
            expected_code_sha=config.evidence_code_sha,
        )
        capability_gate = EvidenceBoundCapabilityGate(backend)
    service = RuntimeCatalogService(
        expected_shop_domain=config.shop_domain,
        backend=backend,
        authorizer=AppProxyVerifierAuthorizer(verifier),
        capability_gate=capability_gate,
        endpoint_path=config.backend_path,
        limits=limits,
    )
    return create_runtime_app(service, app_proxy_path=config.backend_path, limits=limits)


def create_app(environ: Mapping[str, str] | None = None) -> RuntimeAsgiApp:
    """Create the staging ASGI app from host-only values, or reject without values."""

    try:
        source = os.environ if environ is None else environ
        return _compose(_configuration(source))
    except Exception:
        message = _ERROR
    raise RuntimeBootstrapError(message) from None


def main() -> None:
    """Run Uvicorn with request-target logging and proxy-header trust disabled."""

    error_message: str | None = None
    try:
        port = _positive_integer(os.environ, _PORT, 10_000)
        if port > 65_535:
            raise ValueError
    except Exception:
        error_message = _ERROR
    if error_message is not None:
        raise RuntimeBootstrapError(error_message) from None
    uvicorn.run(
        create_app,
        factory=True,
        host="0.0.0.0",  # noqa: S104 - required container ingress bind
        port=port,
        access_log=False,
        server_header=False,
        proxy_headers=False,
        workers=1,
        limit_concurrency=_LIMIT_CONCURRENCY,
    )


if __name__ == "__main__":
    try:
        main()
    except RuntimeBootstrapError:
        print("VALUE_FREE_RESULT: REJECTED")
        raise SystemExit(1) from None


__all__ = ("RuntimeBootstrapError", "create_app", "main")
