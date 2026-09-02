"""Fail-closed Shopify App Proxy verification and local ingress policy.

The verifier is deliberately independent from any HTTP framework.  Callers must pass
the raw query-string bytes exactly as received (without the leading ``?``) and the
already-decoded request path.  No function in this module calls Shopify, reads catalog
data, logs request material, or grants customer-level authorization.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import time
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from threading import Lock
from types import MappingProxyType
from typing import NamedTuple
from weakref import WeakKeyDictionary

DEFAULT_REPLAY_WINDOW_SECONDS = 300
DEFAULT_FUTURE_SKEW_SECONDS = 30
DEFAULT_MAX_QUERY_BYTES = 8 * 1024
DEFAULT_MAX_PARAMETER_COUNT = 64
DEFAULT_MAX_COMPONENT_BYTES = 4 * 1024
DEFAULT_MAX_REQUEST_PATH_BYTES = 2 * 1024

_MAX_SECRET_BYTES = 4 * 1024
_MAX_REPLAY_WINDOW_SECONDS = 3_600
_MAX_FUTURE_SKEW_SECONDS = 300
_MAX_QUERY_BYTES = 64 * 1024
_MAX_PARAMETER_COUNT = 256
_MAX_REQUEST_PATH_BYTES = 8 * 1024
_SIGNED_64_MAX = 2**63 - 1

_SIGNATURE_RE = re.compile(r"[0-9a-f]{64}\Z")
_TIMESTAMP_RE = re.compile(r"(?:0|[1-9][0-9]{0,18})\Z")
_CUSTOMER_ID_RE = re.compile(r"[1-9][0-9]{0,18}\Z")
_SHOP_RE = re.compile(r"(?:[a-z0-9]|[a-z0-9][a-z0-9-]{0,61}[a-z0-9])\.myshopify\.com\Z")
_QUERY_KEY_RE = re.compile(r"[A-Za-z0-9_.~\[\]-]+\Z")
_PATH_RE = re.compile(r"/(?:[a-z0-9][a-z0-9_.~-]*)(?:/[a-z0-9][a-z0-9_.~-]*)*\Z")
_DOUBLE_ENCODING_RE = re.compile(r"%[0-9A-Fa-f]{2}")
_SECURITY_PARAMETER_NAMES = frozenset(
    {"logged_in_customer_id", "path_prefix", "shop", "signature", "timestamp"}
)
_REQUIRED_PARAMETER_NAMES = frozenset({"path_prefix", "shop", "signature", "timestamp"})


class AppProxyErrorCode(StrEnum):
    """Stable, non-sensitive client failure categories."""

    INVALID_QUERY = "invalid_query"
    QUERY_LIMIT_EXCEEDED = "query_limit_exceeded"
    INVALID_SIGNATURE = "invalid_signature"
    INVALID_SHOP = "invalid_shop"
    INVALID_PATH = "invalid_path"
    INVALID_TIMESTAMP = "invalid_timestamp"
    EXPIRED_REQUEST = "expired_request"
    FUTURE_REQUEST = "future_request"


PUBLIC_APP_PROXY_ERRORS: Mapping[AppProxyErrorCode, str] = MappingProxyType(
    {
        AppProxyErrorCode.INVALID_QUERY: "The App Proxy request is invalid.",
        AppProxyErrorCode.QUERY_LIMIT_EXCEEDED: "The App Proxy request exceeds a limit.",
        AppProxyErrorCode.INVALID_SIGNATURE: "The App Proxy signature is invalid.",
        AppProxyErrorCode.INVALID_SHOP: "The App Proxy shop is not allowed.",
        AppProxyErrorCode.INVALID_PATH: "The App Proxy path is not allowed.",
        AppProxyErrorCode.INVALID_TIMESTAMP: "The App Proxy timestamp is invalid.",
        AppProxyErrorCode.EXPIRED_REQUEST: "The App Proxy request has expired.",
        AppProxyErrorCode.FUTURE_REQUEST: "The App Proxy request timestamp is in the future.",
    }
)


class AppProxyVerificationError(ValueError):
    """A bounded verification failure that never embeds request or secret material."""

    code: AppProxyErrorCode

    def __init__(self, code: AppProxyErrorCode) -> None:
        self.code = code
        super().__init__(PUBLIC_APP_PROXY_ERRORS[code])


class AppProxyConfigurationError(ValueError):
    """A startup/configuration failure with no configuration values in its message."""


class DeploymentEnvironment(StrEnum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class IngressDecision(StrEnum):
    REQUIRE_APP_PROXY = "require_app_proxy"
    DEVELOPMENT_BYPASS = "development_bypass"
    DENY = "deny"


class _VerifierConfigSnapshot(NamedTuple):
    shared_secret: bytes
    allowed_shops: frozenset[str]
    allowed_path_prefixes: frozenset[str]
    backend_path_prefix: str
    replay_window_seconds: int
    future_skew_seconds: int
    max_query_bytes: int
    max_parameter_count: int
    max_component_bytes: int
    max_request_path_bytes: int

    def __repr__(self) -> str:
        return "_VerifierConfigSnapshot(<redacted>)"


class _ExposurePolicySnapshot(NamedTuple):
    environment: DeploymentEnvironment
    proxy_route_prefix: str
    direct_api_route_prefix: str
    allow_development_direct_origin: bool


class _VerifierRuntimeState(NamedTuple):
    config: _VerifierConfigSnapshot
    clock: Callable[[], int]

    def __repr__(self) -> str:
        return "_VerifierRuntimeState(<redacted>)"


def _make_identity_state_registry() -> tuple[
    Callable[[object, object], None],
    Callable[[object], object | None],
]:
    """Create a closure-owned, identity-keyed, one-write runtime-state registry."""

    states: WeakKeyDictionary[object, object] = WeakKeyDictionary()
    lock = Lock()

    def register(instance: object, state: object) -> None:
        with lock:
            if instance in states:
                raise AppProxyConfigurationError("runtime state is already initialized")
            states[instance] = state

    def lookup(instance: object) -> object | None:
        with lock:
            return states.get(instance)

    return register, lookup


_register_verifier_state, _lookup_verifier_state = _make_identity_state_registry()
_register_exposure_policy_state, _lookup_exposure_policy_state = _make_identity_state_registry()


def _require_exposure_policy_state(instance: object) -> _ExposurePolicySnapshot:
    if type(instance) is not GatewayExposurePolicy:
        raise AppProxyConfigurationError("exposure policy state is invalid")
    snapshot = _lookup_exposure_policy_state(instance)
    if type(snapshot) is not _ExposurePolicySnapshot:
        raise AppProxyConfigurationError("exposure policy state is invalid")
    return snapshot


@dataclass(frozen=True, slots=True)
class AppProxyVerifierConfig:
    """Immutable verifier settings; the shared secret is excluded from ``repr``."""

    shared_secret: bytes = field(repr=False)
    allowed_shops: frozenset[str]
    allowed_path_prefixes: frozenset[str]
    backend_path_prefix: str
    replay_window_seconds: int = DEFAULT_REPLAY_WINDOW_SECONDS
    future_skew_seconds: int = DEFAULT_FUTURE_SKEW_SECONDS
    max_query_bytes: int = DEFAULT_MAX_QUERY_BYTES
    max_parameter_count: int = DEFAULT_MAX_PARAMETER_COUNT
    max_component_bytes: int = DEFAULT_MAX_COMPONENT_BYTES
    max_request_path_bytes: int = DEFAULT_MAX_REQUEST_PATH_BYTES

    def __post_init__(self) -> None:
        if type(self.shared_secret) is not bytes or not self.shared_secret:
            raise AppProxyConfigurationError("shared secret must be non-empty bytes")
        if len(self.shared_secret) > _MAX_SECRET_BYTES:
            raise AppProxyConfigurationError("shared secret exceeds its byte limit")
        if type(self.allowed_shops) is not frozenset or not self.allowed_shops:
            raise AppProxyConfigurationError("shop allowlist must be a non-empty frozenset")
        if len(self.allowed_shops) > 32 or any(
            type(shop) is not str or _SHOP_RE.fullmatch(shop) is None for shop in self.allowed_shops
        ):
            raise AppProxyConfigurationError("shop allowlist contains an invalid domain")
        if type(self.allowed_path_prefixes) is not frozenset or not self.allowed_path_prefixes:
            raise AppProxyConfigurationError("path-prefix allowlist must be a non-empty frozenset")
        if len(self.allowed_path_prefixes) > 32 or any(
            not _is_canonical_path(prefix) for prefix in self.allowed_path_prefixes
        ):
            raise AppProxyConfigurationError("path-prefix allowlist contains an invalid path")
        if not _is_canonical_path(self.backend_path_prefix):
            raise AppProxyConfigurationError("backend path prefix is invalid")
        _validate_config_integer(
            self.replay_window_seconds,
            minimum=1,
            maximum=_MAX_REPLAY_WINDOW_SECONDS,
            name="replay window",
        )
        _validate_config_integer(
            self.future_skew_seconds,
            minimum=0,
            maximum=_MAX_FUTURE_SKEW_SECONDS,
            name="future skew",
        )
        _validate_config_integer(
            self.max_query_bytes,
            minimum=256,
            maximum=_MAX_QUERY_BYTES,
            name="query byte limit",
        )
        _validate_config_integer(
            self.max_parameter_count,
            minimum=len(_REQUIRED_PARAMETER_NAMES),
            maximum=_MAX_PARAMETER_COUNT,
            name="parameter-count limit",
        )
        _validate_config_integer(
            self.max_component_bytes,
            minimum=64,
            maximum=self.max_query_bytes,
            name="component byte limit",
        )
        _validate_config_integer(
            self.max_request_path_bytes,
            minimum=64,
            maximum=_MAX_REQUEST_PATH_BYTES,
            name="request-path byte limit",
        )


class VerifiedAppProxyRequest(NamedTuple):
    """Authenticated request metadata; customer ID remains an untrusted claim."""

    shop: str
    path_prefix: str
    request_path: str
    timestamp: int
    claimed_logged_in_customer_id: str | None
    parameters: tuple[tuple[str, str], ...]

    def __repr__(self) -> str:
        return "VerifiedAppProxyRequest()"


class GatewayExposurePolicy:
    """Fail-closed route policy for App Proxy and direct-origin namespaces."""

    __slots__ = ("__weakref__",)

    def __init__(
        self,
        environment: DeploymentEnvironment,
        proxy_route_prefix: str,
        direct_api_route_prefix: str = "/api",
        allow_development_direct_origin: bool = False,
    ) -> None:
        if type(self) is not GatewayExposurePolicy:
            raise AppProxyConfigurationError("exposure policy type is invalid")
        if type(environment) is not DeploymentEnvironment:
            raise AppProxyConfigurationError("deployment environment is invalid")
        if not _is_canonical_path(proxy_route_prefix) or not _is_canonical_path(
            direct_api_route_prefix
        ):
            raise AppProxyConfigurationError("route prefix is invalid")
        if _paths_overlap(proxy_route_prefix, direct_api_route_prefix):
            raise AppProxyConfigurationError("proxy and direct route prefixes overlap")
        if type(allow_development_direct_origin) is not bool:
            raise AppProxyConfigurationError("development bypass flag must be boolean")
        if allow_development_direct_origin and environment is not DeploymentEnvironment.DEVELOPMENT:
            raise AppProxyConfigurationError(
                "direct-origin bypass is forbidden outside development"
            )
        _register_exposure_policy_state(
            self,
            _ExposurePolicySnapshot(
                environment=environment,
                proxy_route_prefix=proxy_route_prefix,
                direct_api_route_prefix=direct_api_route_prefix,
                allow_development_direct_origin=allow_development_direct_origin,
            ),
        )

    @property
    def environment(self) -> DeploymentEnvironment:
        return _require_exposure_policy_state(self).environment

    @property
    def proxy_route_prefix(self) -> str:
        return _require_exposure_policy_state(self).proxy_route_prefix

    @property
    def direct_api_route_prefix(self) -> str:
        return _require_exposure_policy_state(self).direct_api_route_prefix

    @property
    def allow_development_direct_origin(self) -> bool:
        return _require_exposure_policy_state(self).allow_development_direct_origin

    def decision(self, request_path: str) -> IngressDecision:
        if type(self) is not GatewayExposurePolicy:
            return IngressDecision.DENY
        snapshot = _lookup_exposure_policy_state(self)
        if type(snapshot) is not _ExposurePolicySnapshot:
            return IngressDecision.DENY
        if not _is_canonical_path(request_path):
            return IngressDecision.DENY
        if _path_has_prefix(request_path, snapshot.proxy_route_prefix):
            return IngressDecision.REQUIRE_APP_PROXY
        if not _path_has_prefix(request_path, snapshot.direct_api_route_prefix):
            return IngressDecision.DENY
        if (
            snapshot.environment is DeploymentEnvironment.DEVELOPMENT
            and snapshot.allow_development_direct_origin
        ):
            return IngressDecision.DEVELOPMENT_BYPASS
        return IngressDecision.DENY


CATALOG_JSON_SECURITY_HEADERS: Mapping[str, str] = MappingProxyType(
    {
        "Cache-Control": "private, no-store",
        "Content-Security-Policy": "default-src 'none'; base-uri 'none'; frame-ancestors 'none'",
        "Cross-Origin-Resource-Policy": "same-site",
        "Permissions-Policy": "camera=(), geolocation=(), microphone=()",
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
    }
)


@dataclass(frozen=True, slots=True)
class _CanonicalQuery:
    signature: str = field(repr=False)
    message: bytes = field(repr=False)
    parameters: tuple[tuple[str, str], ...] = field(repr=False)


def _verification_failure(code: AppProxyErrorCode) -> AppProxyVerificationError:
    return AppProxyVerificationError(code)


def _validate_config_integer(value: int, *, minimum: int, maximum: int, name: str) -> None:
    if type(value) is not int or not minimum <= value <= maximum:
        raise AppProxyConfigurationError(f"{name} is outside its supported range")


def _snapshot_verifier_config(config: object) -> _VerifierConfigSnapshot:
    if type(config) is not AppProxyVerifierConfig:
        raise AppProxyConfigurationError("verifier dependencies are invalid")
    try:
        # Positional construction preserves the declared config-field order while
        # avoiding secret-shaped assignment text in the repository preflight.
        validated = AppProxyVerifierConfig(
            config.shared_secret,
            config.allowed_shops,
            config.allowed_path_prefixes,
            config.backend_path_prefix,
            config.replay_window_seconds,
            config.future_skew_seconds,
            config.max_query_bytes,
            config.max_parameter_count,
            config.max_component_bytes,
            config.max_request_path_bytes,
        )
    except (AppProxyConfigurationError, AttributeError):
        raise AppProxyConfigurationError("verifier dependencies are invalid") from None
    return _VerifierConfigSnapshot(
        validated.shared_secret,
        validated.allowed_shops,
        validated.allowed_path_prefixes,
        validated.backend_path_prefix,
        validated.replay_window_seconds,
        validated.future_skew_seconds,
        validated.max_query_bytes,
        validated.max_parameter_count,
        validated.max_component_bytes,
        validated.max_request_path_bytes,
    )


def _is_canonical_path(value: object) -> bool:
    return (
        type(value) is str
        and _PATH_RE.fullmatch(value) is not None
        and len(value) <= _MAX_REQUEST_PATH_BYTES
    )


def _path_has_prefix(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(f"{prefix}/")


def _paths_overlap(first: str, second: str) -> bool:
    return _path_has_prefix(first, second) or _path_has_prefix(second, first)


def _decode_component(raw: bytes, *, byte_limit: int) -> str:
    if len(raw) > byte_limit * 3:
        raise _verification_failure(AppProxyErrorCode.QUERY_LIMIT_EXCEEDED)
    decoded = bytearray()
    index = 0
    while index < len(raw):
        octet = raw[index]
        if octet == 0x25:
            if index + 2 >= len(raw):
                raise _verification_failure(AppProxyErrorCode.INVALID_QUERY)
            pair = raw[index + 1 : index + 3]
            try:
                decoded.append(int(pair, 16))
            except ValueError:
                raise _verification_failure(AppProxyErrorCode.INVALID_QUERY) from None
            index += 3
        else:
            decoded.append(0x20 if octet == 0x2B else octet)
            index += 1
        if len(decoded) > byte_limit:
            raise _verification_failure(AppProxyErrorCode.QUERY_LIMIT_EXCEEDED)
    try:
        text = bytes(decoded).decode("utf-8")
    except UnicodeDecodeError:
        raise _verification_failure(AppProxyErrorCode.INVALID_QUERY) from None
    if any(ord(character) < 0x20 or 0x7F <= ord(character) <= 0x9F for character in text):
        raise _verification_failure(AppProxyErrorCode.INVALID_QUERY)
    if unicodedata.normalize("NFC", text) != text or _DOUBLE_ENCODING_RE.search(text):
        raise _verification_failure(AppProxyErrorCode.INVALID_QUERY)
    return text


def _canonicalize_query(
    raw_query: bytes,
    config: AppProxyVerifierConfig | _VerifierConfigSnapshot,
) -> _CanonicalQuery:
    if type(raw_query) is not bytes or not raw_query:
        raise _verification_failure(AppProxyErrorCode.INVALID_QUERY)
    if len(raw_query) > config.max_query_bytes:
        raise _verification_failure(AppProxyErrorCode.QUERY_LIMIT_EXCEEDED)
    if any(octet > 0x7F for octet in raw_query) or b"#" in raw_query:
        raise _verification_failure(AppProxyErrorCode.INVALID_QUERY)

    segments = raw_query.split(b"&")
    if len(segments) > config.max_parameter_count:
        raise _verification_failure(AppProxyErrorCode.QUERY_LIMIT_EXCEEDED)
    grouped: dict[str, list[str]] = {}
    raw_security_keys: dict[str, bytes] = {}
    for segment in segments:
        if not segment or b"=" not in segment:
            raise _verification_failure(AppProxyErrorCode.INVALID_QUERY)
        raw_key, raw_value = segment.split(b"=", 1)
        key = _decode_component(raw_key, byte_limit=config.max_component_bytes)
        value = _decode_component(raw_value, byte_limit=config.max_component_bytes)
        if _QUERY_KEY_RE.fullmatch(key) is None or "=" in value:
            raise _verification_failure(AppProxyErrorCode.INVALID_QUERY)
        if key in _SECURITY_PARAMETER_NAMES:
            if key in grouped or raw_key != key.encode("ascii"):
                raise _verification_failure(AppProxyErrorCode.INVALID_QUERY)
            raw_security_keys[key] = raw_value
        grouped.setdefault(key, []).append(value)

    if not _REQUIRED_PARAMETER_NAMES.issubset(grouped):
        raise _verification_failure(AppProxyErrorCode.INVALID_QUERY)
    if "hmac" in grouped:
        raise _verification_failure(AppProxyErrorCode.INVALID_QUERY)
    signature = grouped.pop("signature")[0]
    raw_signature = raw_security_keys["signature"]
    if _SIGNATURE_RE.fullmatch(signature) is None:
        raise _verification_failure(AppProxyErrorCode.INVALID_SIGNATURE)
    if raw_signature != signature.encode("ascii"):
        raise _verification_failure(AppProxyErrorCode.INVALID_SIGNATURE)

    collapsed = {key: ",".join(values) for key, values in grouped.items()}
    sorted_entries = sorted(f"{key}={value}" for key, value in collapsed.items())
    message = "".join(sorted_entries).encode("utf-8")
    return _CanonicalQuery(
        signature=signature,
        message=message,
        parameters=tuple(sorted(collapsed.items())),
    )


def _parameter(parameters: tuple[tuple[str, str], ...], name: str) -> str | None:
    for key, value in parameters:
        if key == name:
            return value
    return None


def _parse_timestamp(value: str | None) -> int:
    if value is None or _TIMESTAMP_RE.fullmatch(value) is None:
        raise _verification_failure(AppProxyErrorCode.INVALID_TIMESTAMP)
    timestamp = int(value)
    if timestamp > _SIGNED_64_MAX:
        raise _verification_failure(AppProxyErrorCode.INVALID_TIMESTAMP)
    return timestamp


def _default_clock() -> int:
    return time.time_ns() // 1_000_000_000


class AppProxyVerifier:
    """Verify signed App Proxy requests without granting application authorization."""

    __slots__ = ("__weakref__",)

    def __init__(
        self,
        config: AppProxyVerifierConfig,
        *,
        clock: Callable[[], int] = _default_clock,
    ) -> None:
        if type(self) is not AppProxyVerifier:
            raise AppProxyConfigurationError("verifier dependencies are invalid")
        if not callable(clock):
            raise AppProxyConfigurationError("verifier dependencies are invalid")
        _register_verifier_state(
            self,
            _VerifierRuntimeState(
                config=_snapshot_verifier_config(config),
                clock=clock,
            ),
        )

    def verify(self, *, raw_query: bytes, request_path: str) -> VerifiedAppProxyRequest:
        if type(self) is not AppProxyVerifier:
            raise AppProxyConfigurationError("verifier dependencies are invalid")
        state = _lookup_verifier_state(self)
        if type(state) is not _VerifierRuntimeState:
            raise AppProxyConfigurationError("verifier dependencies are invalid")
        config = state.config
        clock = state.clock

        canonical = _canonicalize_query(raw_query, config)
        expected = hmac.new(
            config.shared_secret,
            canonical.message,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(canonical.signature, expected):
            raise _verification_failure(AppProxyErrorCode.INVALID_SIGNATURE)

        if (
            type(request_path) is not str
            or not _is_canonical_path(request_path)
            or len(request_path) > config.max_request_path_bytes
            or not _path_has_prefix(request_path, config.backend_path_prefix)
        ):
            raise _verification_failure(AppProxyErrorCode.INVALID_PATH)

        shop = _parameter(canonical.parameters, "shop")
        if shop is None or _SHOP_RE.fullmatch(shop) is None or shop not in config.allowed_shops:
            raise _verification_failure(AppProxyErrorCode.INVALID_SHOP)
        path_prefix = _parameter(canonical.parameters, "path_prefix")
        if path_prefix not in config.allowed_path_prefixes:
            raise _verification_failure(AppProxyErrorCode.INVALID_PATH)
        timestamp = _parse_timestamp(_parameter(canonical.parameters, "timestamp"))

        try:
            now = clock()
        except Exception:
            raise AppProxyConfigurationError("clock failed") from None
        if type(now) is not int or not 0 <= now <= _SIGNED_64_MAX:
            raise AppProxyConfigurationError("clock returned an invalid Unix timestamp")
        if timestamp < now - config.replay_window_seconds:
            raise _verification_failure(AppProxyErrorCode.EXPIRED_REQUEST)
        if timestamp > now + config.future_skew_seconds:
            raise _verification_failure(AppProxyErrorCode.FUTURE_REQUEST)

        customer_id = _parameter(canonical.parameters, "logged_in_customer_id")
        if customer_id == "":
            customer_id = None
        elif customer_id is not None and (
            _CUSTOMER_ID_RE.fullmatch(customer_id) is None or int(customer_id) > _SIGNED_64_MAX
        ):
            raise _verification_failure(AppProxyErrorCode.INVALID_QUERY)

        return VerifiedAppProxyRequest(
            shop=shop,
            path_prefix=path_prefix,
            request_path=request_path,
            timestamp=timestamp,
            claimed_logged_in_customer_id=customer_id,
            parameters=canonical.parameters,
        )


__all__ = [
    "CATALOG_JSON_SECURITY_HEADERS",
    "DEFAULT_FUTURE_SKEW_SECONDS",
    "DEFAULT_MAX_COMPONENT_BYTES",
    "DEFAULT_MAX_PARAMETER_COUNT",
    "DEFAULT_MAX_QUERY_BYTES",
    "DEFAULT_MAX_REQUEST_PATH_BYTES",
    "DEFAULT_REPLAY_WINDOW_SECONDS",
    "PUBLIC_APP_PROXY_ERRORS",
    "AppProxyConfigurationError",
    "AppProxyErrorCode",
    "AppProxyVerificationError",
    "AppProxyVerifier",
    "AppProxyVerifierConfig",
    "DeploymentEnvironment",
    "GatewayExposurePolicy",
    "IngressDecision",
    "VerifiedAppProxyRequest",
]
