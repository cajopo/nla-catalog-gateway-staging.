"""Framework-independent, evidence-bound HTTP boundary for the catalog runtime.

The module ships no server or deployment configuration.  Safe defaults still reject
proxy traffic, expose no dataset, and deny catalog output.  Concrete adapters bind the
accepted App Proxy verifier and catalog-core evidence to one immutable request lease.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, Protocol
from weakref import WeakKeyDictionary

from nla_catalog_gateway.app_proxy_security import (
    AppProxyConfigurationError,
    AppProxyVerificationError,
    AppProxyVerifier,
    VerifiedAppProxyRequest,
)
from nla_catalog_gateway.canonical_search import (
    CanonicalSearchError,
    SearchMode,
    SingleCardSearchIndex,
    normalize_search_text,
    prepare_single_card_search,
    search_single_cards,
)
from nla_catalog_gateway.core_evidence import VerifiedCatalogCoreEvidenceV1
from nla_catalog_gateway.facets import FacetContractError, PreparedFacetCatalog
from nla_catalog_gateway.generation_bundle import VerifiedReconciledGenerationV1
from nla_catalog_gateway.pagination import (
    AtomicCatalogActivation,
    CatalogPaginator,
    CatalogProjection,
    CursorCodecV1,
    CursorContextMismatchError,
    CursorExpiredError,
    DatasetUnavailableError,
    InvalidCursorError,
    PaginationContractError,
    StaleGenerationError,
    UnsupportedPaginationRequestError,
)
from nla_catalog_gateway.runtime_contract import (
    CONTRACT_VERSION,
    DEFAULT_CAPABILITIES_V1,
    MAX_CONTRACT_BYTES,
    CapabilityState,
    CatalogErrorCode,
    CatalogErrorV1,
    CatalogItemV1,
    CatalogPageV1,
    CatalogProductRecordV1,
    CatalogRequestV1,
    CursorContextV1,
    RequestFamily,
    RuntimeContractError,
)
from nla_catalog_gateway.taxonomy import ProductFamily

MAX_REQUEST_BODY_BYTES = 64 * 1024
MAX_RESPONSE_BODY_BYTES = MAX_CONTRACT_BYTES
MAX_CURSOR_CHARS = 16 * 1024
MAX_QUERY_CHARS = 256
MAX_RAW_QUERY_BYTES = 8 * 1024
MAX_PATH_BYTES = 2 * 1024
MAX_HEADER_COUNT = 64
MAX_HEADER_NAME_BYTES = 256
MAX_HEADER_VALUE_BYTES = 8 * 1024
MAX_HEADER_BYTES = 32 * 1024
MAX_BODY_CHUNKS = 128
DEFAULT_REQUEST_TIMEOUT_MS = 2_000

_MAX_REQUEST_TIMEOUT_MS = 30_000
_MAX_RAW_QUERY_BYTES = 64 * 1024
_MAX_PATH_BYTES = 8 * 1024
_MAX_HEADER_COUNT = 256
_MAX_HEADER_NAME_BYTES = 1024
_MAX_HEADER_VALUE_BYTES = 16 * 1024
_MAX_HEADER_BYTES = 64 * 1024
_MAX_BODY_CHUNKS = 1024
_MIN_RESPONSE_BODY_BYTES = 512
_BOMS = (
    b"\xef\xbb\xbf",
    b"\xff\xfe",
    b"\xfe\xff",
    b"\xff\xfe\x00\x00",
    b"\x00\x00\xfe\xff",
)
_CURSOR_RE = re.compile(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\Z")
_GENERATION_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_CODE_SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
_PRODUCT_GID_RE = re.compile(r"gid://shopify/Product/([1-9][0-9]*)\Z")
_HEADER_NAME_RE = re.compile(rb"[!#$%&'*+\-.^_`|~0-9A-Za-z]+\Z")
_SHOP_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.myshopify\.com\Z")

_JSON_HEADERS = (
    ("content-type", "application/json; charset=utf-8"),
    ("cache-control", "no-store"),
    ("x-content-type-options", "nosniff"),
)

_BACKEND_STATUS = MappingProxyType(
    {
        CatalogErrorCode.INVALID_CURSOR: 400,
        CatalogErrorCode.RESTART_REQUIRED: 409,
        CatalogErrorCode.DATASET_UNAVAILABLE: 503,
        CatalogErrorCode.TEMPORARILY_UNAVAILABLE: 503,
        CatalogErrorCode.UNSUPPORTED_CAPABILITY: 503,
        CatalogErrorCode.CURSOR_CONTEXT_MISMATCH: 400,
        CatalogErrorCode.DATASET_GENERATION_MISMATCH: 409,
    }
)


class RuntimeApiContractError(ValueError):
    """A bounded, value-free failure for the runtime transport contract."""


class IncompatibleCatalogRequestError(RuntimeApiContractError):
    """The request combines individually valid but incompatible fields."""


class InvalidOpaqueCursorError(RuntimeApiContractError):
    """The opaque cursor does not meet the transport syntax or size bound."""


class ProxyRequestRejected(Exception):
    """The trusted App Proxy adapter rejected the request."""


class ProxyVerifierUnavailable(Exception):
    """The trusted App Proxy adapter cannot currently verify requests."""


class RequestDeadlineExceeded(Exception):
    """The bounded request deadline elapsed."""


class RequestCancelled(BaseException):
    """Cooperative cancellation that must never be normalized into an HTTP error."""


class CatalogBackendFailure(Exception):
    """A typed, value-free failure reported by a future catalog adapter."""

    def __init__(self, code: CatalogErrorCode) -> None:
        if type(code) is not CatalogErrorCode or code not in _BACKEND_STATUS:
            raise RuntimeApiContractError("backend failure code is invalid")
        self.code = code
        super().__init__("catalog backend failure")


class _OutputContractFailure(Exception):
    """An adapter returned an object that cannot be exposed safely."""


def _make_authorizer_verifier_registry() -> tuple[
    Callable[[object, AppProxyVerifier], None],
    Callable[[object], AppProxyVerifier | None],
]:
    """Create a closure-owned, identity-keyed, one-write verifier registry."""

    bindings: WeakKeyDictionary[object, AppProxyVerifier] = WeakKeyDictionary()
    lock = threading.Lock()

    def register(authorizer: object, verifier: AppProxyVerifier) -> None:
        if type(verifier) is not AppProxyVerifier:
            raise RuntimeApiContractError("App Proxy verifier is invalid")
        with lock:
            if authorizer in bindings:
                raise RuntimeApiContractError("App Proxy verifier is already bound")
            bindings[authorizer] = verifier

    def lookup(authorizer: object) -> AppProxyVerifier | None:
        with lock:
            return bindings.get(authorizer)

    return register, lookup


_register_authorizer_verifier, _lookup_authorizer_verifier = _make_authorizer_verifier_registry()


@dataclass(frozen=True, slots=True)
class RuntimeLimits:
    """Hard-bounded request resources, configurable only below fixed ceilings."""

    max_request_body_bytes: int = MAX_REQUEST_BODY_BYTES
    max_response_body_bytes: int = MAX_RESPONSE_BODY_BYTES
    max_cursor_chars: int = MAX_CURSOR_CHARS
    max_raw_query_bytes: int = MAX_RAW_QUERY_BYTES
    max_path_bytes: int = MAX_PATH_BYTES
    max_header_count: int = MAX_HEADER_COUNT
    max_header_name_bytes: int = MAX_HEADER_NAME_BYTES
    max_header_value_bytes: int = MAX_HEADER_VALUE_BYTES
    max_header_bytes: int = MAX_HEADER_BYTES
    max_body_chunks: int = MAX_BODY_CHUNKS
    request_timeout_ms: int = DEFAULT_REQUEST_TIMEOUT_MS

    def __post_init__(self) -> None:
        bounds = (
            (self.max_request_body_bytes, 1, MAX_REQUEST_BODY_BYTES),
            (
                self.max_response_body_bytes,
                _MIN_RESPONSE_BODY_BYTES,
                MAX_RESPONSE_BODY_BYTES,
            ),
            (self.max_cursor_chars, 1, MAX_CURSOR_CHARS),
            (self.max_raw_query_bytes, 1, _MAX_RAW_QUERY_BYTES),
            (self.max_path_bytes, 1, _MAX_PATH_BYTES),
            (self.max_header_count, 1, _MAX_HEADER_COUNT),
            (self.max_header_name_bytes, 1, _MAX_HEADER_NAME_BYTES),
            (self.max_header_value_bytes, 1, _MAX_HEADER_VALUE_BYTES),
            (self.max_header_bytes, 1, _MAX_HEADER_BYTES),
            (self.max_body_chunks, 1, _MAX_BODY_CHUNKS),
            (self.request_timeout_ms, 1, _MAX_REQUEST_TIMEOUT_MS),
        )
        if any(
            type(value) is not int or not minimum <= value <= maximum
            for value, minimum, maximum in bounds
        ):
            raise RuntimeApiContractError("runtime limit is outside its hard bound")


@dataclass(frozen=True, slots=True)
class RuntimeHttpRequest:
    """Raw framework-neutral request values supplied by a thin HTTP adapter."""

    method: str
    path: str
    raw_query: bytes
    headers: tuple[tuple[bytes, bytes], ...]
    body_chunks: tuple[bytes, ...]


@dataclass(frozen=True, slots=True)
class RuntimeHttpResponse:
    """A complete response for a thin HTTP adapter to transmit unchanged."""

    status: int
    headers: tuple[tuple[str, str], ...]
    body: bytes


@dataclass(frozen=True, slots=True)
class VerifiedProxyIdentity:
    """Minimal redacted identity returned by the future #12 adapter."""

    shop_domain: str

    def __post_init__(self) -> None:
        _validated_shop(self.shop_domain)


class ProxyAuthorizer(Protocol):
    """Adapter seam for #12; raw query bytes must be passed unchanged."""

    def verify(
        self,
        *,
        raw_query: bytes,
        request_path: str,
        control: RequestControl,
    ) -> VerifiedProxyIdentity: ...


class RequestCancellation:
    """Thread-safe cooperative cancellation shared with a pinned backend lease."""

    __slots__ = ("_event",)

    def __init__(self) -> None:
        self._event = threading.Event()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise RequestCancelled


@dataclass(frozen=True, slots=True)
class RequestControl:
    """Monotonic deadline and cancellation signal passed to every dependency."""

    deadline_ns: int
    cancellation: RequestCancellation
    _clock_ns: Callable[[], int] = field(repr=False, compare=False)

    def checkpoint(self) -> None:
        self.cancellation.raise_if_cancelled()
        try:
            now = self._clock_ns()
        except Exception as exc:
            raise RequestDeadlineExceeded from exc
        if type(now) is not int or now < 0 or now >= self.deadline_ns:
            raise RequestDeadlineExceeded


@dataclass(frozen=True, slots=True)
class CatalogLeaseResult:
    """Page plus the only cursor clients may submit on their next request."""

    page: CatalogPageV1
    next_cursor: str | None


class CatalogGenerationLease(Protocol):
    """One immutable generation selected exactly once for one request."""

    @property
    def dataset_generation(self) -> str: ...

    @property
    def shop_domain(self) -> str: ...

    def fetch_page(
        self,
        request: CatalogRequestV1,
        cursor: str | None,
        *,
        control: RequestControl,
    ) -> CatalogLeaseResult: ...

    def close(self) -> None: ...


class CatalogBackend(Protocol):
    """Future adapter that atomically acquires one immutable generation lease."""

    def acquire(self, *, control: RequestControl) -> CatalogGenerationLease: ...


class RuntimeCapabilityGate(Protocol):
    """Future evidence gate; it must be bound to the acquired lease."""

    def require_catalog(
        self,
        lease: CatalogGenerationLease,
        request: CatalogRequestV1,
        *,
        control: RequestControl,
    ) -> None: ...

    def ready(self, lease: CatalogGenerationLease, *, control: RequestControl) -> bool: ...


class DenyAllProxyAuthorizer:
    """Safe default until the accepted #12 adapter is available."""

    def verify(
        self,
        *,
        raw_query: bytes,
        request_path: str,
        control: RequestControl,
    ) -> VerifiedProxyIdentity:
        del raw_query, request_path, control
        raise ProxyRequestRejected


class UnavailableCatalogBackend:
    """Safe default until the accepted #7 projection adapter is available."""

    def acquire(self, *, control: RequestControl) -> CatalogGenerationLease:
        del control
        raise CatalogBackendFailure(CatalogErrorCode.DATASET_UNAVAILABLE)


class FailClosedCapabilityGate:
    """Never authorizes output; baseline evidence must provide a later adapter."""

    def require_catalog(
        self,
        lease: CatalogGenerationLease,
        request: CatalogRequestV1,
        *,
        control: RequestControl,
    ) -> None:
        del lease, request, control
        raise CatalogBackendFailure(CatalogErrorCode.UNSUPPORTED_CAPABILITY)

    def ready(self, lease: CatalogGenerationLease, *, control: RequestControl) -> bool:
        del lease, control
        return False


class AppProxyVerifierAuthorizer:
    """Adapt the accepted App Proxy verifier without exposing signed query values."""

    __slots__ = ("__weakref__",)

    def __init__(self, verifier: AppProxyVerifier) -> None:
        if type(self) is not AppProxyVerifierAuthorizer or type(verifier) is not AppProxyVerifier:
            raise RuntimeApiContractError("App Proxy verifier is invalid")
        _register_authorizer_verifier(self, verifier)

    def verify(
        self,
        *,
        raw_query: bytes,
        request_path: str,
        control: RequestControl,
    ) -> VerifiedProxyIdentity:
        control.checkpoint()
        verifier = _bound_app_proxy_verifier(self)
        if verifier is None:
            raise ProxyVerifierUnavailable
        failure: str | None = None
        verified: VerifiedAppProxyRequest | None = None
        try:
            verified = verifier.verify(
                raw_query=raw_query,
                request_path=request_path,
            )
        except AppProxyVerificationError:
            failure = "rejected"
        except AppProxyConfigurationError:
            failure = "unavailable"
        except Exception:
            failure = "unavailable"
        control.checkpoint()
        if failure == "rejected":
            raise ProxyRequestRejected
        if failure is not None:
            raise ProxyVerifierUnavailable
        if type(verified) is not VerifiedAppProxyRequest:
            raise ProxyVerifierUnavailable
        invalid_identity = False
        try:
            identity = VerifiedProxyIdentity(verified.shop)
        except Exception:
            invalid_identity = True
        if invalid_identity:
            raise ProxyVerifierUnavailable
        control.checkpoint()
        return identity


@dataclass(frozen=True, slots=True, repr=False)
class _EvidenceBoundGeneration:
    verified: VerifiedReconciledGenerationV1 = field(repr=False)
    projection: CatalogProjection = field(repr=False)
    cursor_codec: CursorCodecV1 = field(repr=False)
    evidence: VerifiedCatalogCoreEvidenceV1 = field(repr=False)
    records: tuple[CatalogProductRecordV1, ...] = field(repr=False)
    items: tuple[CatalogItemV1, ...] = field(repr=False)
    search: SingleCardSearchIndex = field(repr=False, compare=False)
    facets: PreparedFacetCatalog = field(repr=False, compare=False)
    paginator: CatalogPaginator = field(repr=False)
    clock: Callable[[], datetime] = field(repr=False, compare=False)
    binding: tuple[str, str, str, str, str, str] = field(repr=False)


class EvidenceBoundCatalogBackend:
    """Atomically select one complete, immutable evidence-bound generation."""

    __slots__ = ("_active", "_clock", "_expected_code_sha", "_lock", "_token")

    def __init__(
        self,
        verified: VerifiedReconciledGenerationV1,
        projection: CatalogProjection,
        cursor_codec: CursorCodecV1,
        evidence: VerifiedCatalogCoreEvidenceV1,
        *,
        expected_code_sha: str,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if (
            type(expected_code_sha) is not str
            or _CODE_SHA_RE.fullmatch(expected_code_sha) is None
            or (clock is not None and not callable(clock))
        ):
            raise RuntimeApiContractError("catalog runtime binding is invalid")
        self._lock = threading.Lock()
        self._token = object()
        self._expected_code_sha = expected_code_sha
        self._clock = clock or (lambda: datetime.now(UTC))
        self._active = _new_evidence_bound_generation(
            verified,
            projection,
            cursor_codec,
            evidence,
            expected_code_sha=self._expected_code_sha,
            clock=self._clock,
        )

    @property
    def active_generation(self) -> str:
        with self._lock:
            return self._active.binding[2]

    def activate(
        self,
        verified: VerifiedReconciledGenerationV1,
        projection: CatalogProjection,
        cursor_codec: CursorCodecV1,
        evidence: VerifiedCatalogCoreEvidenceV1,
    ) -> None:
        candidate = _new_evidence_bound_generation(
            verified,
            projection,
            cursor_codec,
            evidence,
            expected_code_sha=self._expected_code_sha,
            clock=self._clock,
        )
        with self._lock:
            self._active = candidate

    def acquire(self, *, control: RequestControl) -> EvidenceBoundCatalogLease:
        if type(control) is not RequestControl:
            raise CatalogBackendFailure(CatalogErrorCode.TEMPORARILY_UNAVAILABLE)
        control.checkpoint()
        with self._lock:
            lease = EvidenceBoundCatalogLease(
                backend_token=self._token,
                generation=self._active,
            )
        try:
            control.checkpoint()
        except BaseException:
            lease.close()
            raise
        return lease


class EvidenceBoundCatalogLease:
    """One pinned generation; close is idempotent and prevents later reads."""

    __slots__ = ("_backend_token", "_closed", "_generation", "_lock")

    def __init__(self, *, backend_token: object, generation: _EvidenceBoundGeneration) -> None:
        self._backend_token = backend_token
        self._generation = generation
        self._lock = threading.Lock()
        self._closed = False

    @property
    def dataset_generation(self) -> str:
        return self._generation.binding[2]

    @property
    def shop_domain(self) -> str:
        return self._generation.binding[0]

    def fetch_page(
        self,
        request: CatalogRequestV1,
        cursor: str | None,
        *,
        control: RequestControl,
    ) -> CatalogLeaseResult:
        if type(control) is not RequestControl:
            raise CatalogBackendFailure(CatalogErrorCode.TEMPORARILY_UNAVAILABLE)
        with self._lock:
            if self._closed:
                raise CatalogBackendFailure(CatalogErrorCode.DATASET_UNAVAILABLE)
            control.checkpoint()
            try:
                result = _fetch_evidence_bound_page(
                    self._generation,
                    request,
                    cursor,
                    control=control,
                )
            except (CatalogBackendFailure, RequestDeadlineExceeded):
                raise
            except Exception as exc:
                failure_code = _catalog_execution_error_code(exc)
            else:
                failure_code = None
            if failure_code is not None:
                raise CatalogBackendFailure(failure_code)
            control.checkpoint()
            return result

    def close(self) -> None:
        with self._lock:
            self._closed = True

    def _authorized_generation(self, backend_token: object) -> _EvidenceBoundGeneration | None:
        with self._lock:
            if self._closed or self._backend_token is not backend_token:
                return None
            return self._generation


class EvidenceBoundCapabilityGate:
    """Authorize only exact leases carrying the accepted six-way evidence binding."""

    __slots__ = ("_backend_token",)

    def __init__(self, backend: EvidenceBoundCatalogBackend) -> None:
        if type(backend) is not EvidenceBoundCatalogBackend:
            raise RuntimeApiContractError("catalog capability backend is invalid")
        self._backend_token = backend._token

    def require_catalog(
        self,
        lease: CatalogGenerationLease,
        request: CatalogRequestV1,
        *,
        control: RequestControl,
    ) -> None:
        control.checkpoint()
        if not _canonical_request(request) or not self._authorizes(lease):
            raise CatalogBackendFailure(CatalogErrorCode.UNSUPPORTED_CAPABILITY)
        control.checkpoint()

    def ready(self, lease: CatalogGenerationLease, *, control: RequestControl) -> bool:
        control.checkpoint()
        result = self._authorizes(lease)
        control.checkpoint()
        return result

    def _authorizes(self, lease: CatalogGenerationLease) -> bool:
        if type(lease) is not EvidenceBoundCatalogLease:
            return False
        generation = lease._authorized_generation(self._backend_token)
        return generation is not None and _evidence_binding_is_current(generation)


@dataclass(frozen=True, slots=True)
class CatalogRequestEnvelopeV1:
    """Strict POST body: canonical request plus an opaque authenticated cursor."""

    request: CatalogRequestV1
    cursor: str | None
    contract_version: int = CONTRACT_VERSION

    FIELDS = frozenset({"contractVersion", "cursor", "request"})

    def __post_init__(self) -> None:
        if type(self.contract_version) is not int or self.contract_version != CONTRACT_VERSION:
            raise RuntimeApiContractError("request envelope contractVersion must be 1")
        if type(self.request) is not CatalogRequestV1:
            raise RuntimeApiContractError("request envelope request must be canonical")
        _validate_request_scope(self.request)
        _validated_cursor(self.cursor, MAX_CURSOR_CHARS)

    def as_dict(self) -> dict[str, Any]:
        return {
            "contractVersion": self.contract_version,
            "cursor": self.cursor,
            "request": self.request.as_dict(),
        }

    def to_json_bytes(self) -> bytes:
        if type(self) is not CatalogRequestEnvelopeV1:
            raise RuntimeApiContractError("request envelope type is invalid")
        try:
            value = self.as_dict()
        except Exception as exc:
            raise RuntimeApiContractError("request envelope is invalid") from exc
        raw = _canonical_json_bytes(value)
        if len(raw) > MAX_REQUEST_BODY_BYTES:
            raise RuntimeApiContractError("request envelope exceeds the byte limit")
        return raw

    @classmethod
    def from_json_bytes(
        cls,
        raw: bytes,
        *,
        byte_limit: int = MAX_REQUEST_BODY_BYTES,
        cursor_char_limit: int = MAX_CURSOR_CHARS,
    ) -> CatalogRequestEnvelopeV1:
        if cls is not CatalogRequestEnvelopeV1:
            raise RuntimeApiContractError("request envelope type is invalid")
        _validated_public_limit(byte_limit, MAX_REQUEST_BODY_BYTES)
        _validated_public_limit(cursor_char_limit, MAX_CURSOR_CHARS)
        value = _load_json_object(raw, byte_limit=byte_limit)
        _exact_keys(value, cls.FIELDS)
        if (
            type(value["contractVersion"]) is not int
            or value["contractVersion"] != CONTRACT_VERSION
        ):
            raise RuntimeApiContractError("request envelope contractVersion must be 1")
        request_value = value["request"]
        if _raw_request_is_incompatible(request_value):
            raise IncompatibleCatalogRequestError("catalog request fields are incompatible")
        try:
            request = CatalogRequestV1.from_dict(request_value)
        except RuntimeContractError as exc:
            raise RuntimeApiContractError("catalog request is invalid") from exc
        _validate_request_scope(request)
        cursor = _validated_cursor(value["cursor"], cursor_char_limit)
        return cls(request=request, cursor=cursor)


@dataclass(frozen=True, slots=True)
class _PublicCatalogPageV1:
    """Validated public page fields, excluding unsigned internal cursor context."""

    dataset_generation: str
    request: CatalogRequestV1
    request_context_sha256: str
    items: tuple[CatalogItemV1, ...]
    returned_product_count: int
    returned_variant_count: int
    has_next_page: bool
    contract_version: int = CONTRACT_VERSION

    FIELDS = frozenset(
        {
            "contractVersion",
            "datasetGeneration",
            "hasNextPage",
            "items",
            "request",
            "requestContextSha256",
            "returnedProductCount",
            "returnedVariantCount",
        }
    )

    def __post_init__(self) -> None:
        if type(self.has_next_page) is not bool:
            raise RuntimeApiContractError("public page hasNextPage must be a boolean")
        try:
            terminal = CatalogPageV1(
                contract_version=self.contract_version,
                dataset_generation=self.dataset_generation,
                request=self.request,
                request_context_sha256=self.request_context_sha256,
                items=self.items,
                returned_product_count=self.returned_product_count,
                returned_variant_count=self.returned_variant_count,
                has_next_page=False,
                next_cursor_context=None,
            )
            terminal = CatalogPageV1.from_json_bytes(terminal.to_json_bytes())
        except (AttributeError, RuntimeContractError, TypeError, ValueError) as exc:
            raise RuntimeApiContractError("public page fields are invalid") from exc
        if self.has_next_page and not terminal.items:
            raise RuntimeApiContractError("nonterminal public page must contain an item")
        object.__setattr__(self, "dataset_generation", terminal.dataset_generation)
        object.__setattr__(self, "request", terminal.request)
        object.__setattr__(self, "request_context_sha256", terminal.request_context_sha256)
        object.__setattr__(self, "items", terminal.items)
        object.__setattr__(self, "returned_product_count", terminal.returned_product_count)
        object.__setattr__(self, "returned_variant_count", terminal.returned_variant_count)
        object.__setattr__(self, "contract_version", terminal.contract_version)

    @classmethod
    def from_catalog_page(cls, page: CatalogPageV1) -> _PublicCatalogPageV1:
        if type(page) is not CatalogPageV1:
            raise RuntimeApiContractError("response envelope page must be canonical")
        try:
            canonical = CatalogPageV1.from_json_bytes(page.to_json_bytes())
        except (AttributeError, RuntimeContractError, TypeError, ValueError) as exc:
            raise RuntimeApiContractError("response envelope page must be canonical") from exc
        return cls(
            contract_version=canonical.contract_version,
            dataset_generation=canonical.dataset_generation,
            request=canonical.request,
            request_context_sha256=canonical.request_context_sha256,
            items=canonical.items,
            returned_product_count=canonical.returned_product_count,
            returned_variant_count=canonical.returned_variant_count,
            has_next_page=canonical.has_next_page,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "contractVersion": self.contract_version,
            "datasetGeneration": self.dataset_generation,
            "hasNextPage": self.has_next_page,
            "items": [item.as_dict() for item in self.items],
            "request": self.request.as_dict(),
            "requestContextSha256": self.request_context_sha256,
            "returnedProductCount": self.returned_product_count,
            "returnedVariantCount": self.returned_variant_count,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> _PublicCatalogPageV1:
        if type(value) is not dict:
            raise RuntimeApiContractError("response envelope page must be an object")
        _exact_keys(value, cls.FIELDS)
        terminal_value = dict(value)
        has_next_page = terminal_value["hasNextPage"]
        terminal_value["hasNextPage"] = False
        terminal_value["nextCursorContext"] = None
        try:
            terminal = CatalogPageV1.from_dict(terminal_value)
        except RuntimeContractError as exc:
            raise RuntimeApiContractError("response envelope page is invalid") from exc
        return cls(
            contract_version=terminal.contract_version,
            dataset_generation=terminal.dataset_generation,
            request=terminal.request,
            request_context_sha256=terminal.request_context_sha256,
            items=terminal.items,
            returned_product_count=terminal.returned_product_count,
            returned_variant_count=terminal.returned_variant_count,
            has_next_page=has_next_page,
        )


@dataclass(frozen=True, slots=True)
class CatalogResponseEnvelopeV1:
    """Safe public page plus the opaque cursor issued by the pinned backend."""

    page: _PublicCatalogPageV1 | CatalogPageV1
    next_cursor: str | None
    contract_version: int = CONTRACT_VERSION

    FIELDS = frozenset({"contractVersion", "nextCursor", "page"})

    def __post_init__(self) -> None:
        if type(self.contract_version) is not int or self.contract_version != CONTRACT_VERSION:
            raise RuntimeApiContractError("response envelope contractVersion must be 1")
        if type(self.page) is CatalogPageV1:
            page = _PublicCatalogPageV1.from_catalog_page(self.page)
        elif type(self.page) is _PublicCatalogPageV1:
            page = _PublicCatalogPageV1(
                contract_version=self.page.contract_version,
                dataset_generation=self.page.dataset_generation,
                request=self.page.request,
                request_context_sha256=self.page.request_context_sha256,
                items=self.page.items,
                returned_product_count=self.page.returned_product_count,
                returned_variant_count=self.page.returned_variant_count,
                has_next_page=self.page.has_next_page,
            )
        else:
            raise RuntimeApiContractError("response envelope page must be canonical")
        cursor = _validated_cursor(self.next_cursor, MAX_CURSOR_CHARS)
        if page.has_next_page != (cursor is not None):
            raise RuntimeApiContractError("opaque cursor must match terminal page state")
        object.__setattr__(self, "page", page)

    def as_dict(self) -> dict[str, Any]:
        if (
            type(self.contract_version) is not int
            or self.contract_version != CONTRACT_VERSION
            or type(self.page) is not _PublicCatalogPageV1
        ):
            raise RuntimeApiContractError("response envelope is invalid")
        page = _PublicCatalogPageV1(
            contract_version=self.page.contract_version,
            dataset_generation=self.page.dataset_generation,
            request=self.page.request,
            request_context_sha256=self.page.request_context_sha256,
            items=self.page.items,
            returned_product_count=self.page.returned_product_count,
            returned_variant_count=self.page.returned_variant_count,
            has_next_page=self.page.has_next_page,
        )
        cursor = _validated_cursor(self.next_cursor, MAX_CURSOR_CHARS)
        if page.has_next_page != (cursor is not None):
            raise RuntimeApiContractError("opaque cursor must match terminal page state")
        return {
            "contractVersion": self.contract_version,
            "nextCursor": cursor,
            "page": page.as_dict(),
        }

    def to_json_bytes(self) -> bytes:
        if type(self) is not CatalogResponseEnvelopeV1:
            raise RuntimeApiContractError("response envelope type is invalid")
        try:
            value = self.as_dict()
        except Exception as exc:
            raise RuntimeApiContractError("response envelope is invalid") from exc
        raw = _canonical_json_bytes(value)
        if len(raw) > MAX_RESPONSE_BODY_BYTES:
            raise RuntimeApiContractError("response envelope exceeds the byte limit")
        return raw

    @classmethod
    def from_json_bytes(
        cls, raw: bytes, *, byte_limit: int = MAX_RESPONSE_BODY_BYTES
    ) -> CatalogResponseEnvelopeV1:
        if cls is not CatalogResponseEnvelopeV1:
            raise RuntimeApiContractError("response envelope type is invalid")
        _validated_public_limit(byte_limit, MAX_RESPONSE_BODY_BYTES)
        value = _load_json_object(raw, byte_limit=byte_limit)
        _exact_keys(value, cls.FIELDS)
        if (
            type(value["contractVersion"]) is not int
            or value["contractVersion"] != CONTRACT_VERSION
        ):
            raise RuntimeApiContractError("response envelope contractVersion must be 1")
        page_value = value["page"]
        if type(page_value) is not dict:
            raise RuntimeApiContractError("response envelope page must be an object")
        page = _PublicCatalogPageV1.from_dict(page_value)
        result = cls(
            page=page,
            next_cursor=_validated_cursor(value["nextCursor"], MAX_CURSOR_CHARS),
        )
        if result.to_json_bytes() != raw:
            raise RuntimeApiContractError("response envelope JSON is not canonical")
        return result


class RuntimeCatalogService:
    """Minimal synchronous boundary for a future thin HTTP/ASGI adapter."""

    def __init__(
        self,
        *,
        expected_shop_domain: str,
        backend: CatalogBackend | None = None,
        authorizer: ProxyAuthorizer | None = None,
        capability_gate: RuntimeCapabilityGate | None = None,
        endpoint_path: str = "/apps/nla/catalog",
        limits: RuntimeLimits | None = None,
        clock_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        if limits is None:
            limits = RuntimeLimits()
        if type(limits) is not RuntimeLimits:
            raise RuntimeApiContractError("runtime limits must be canonical")
        self._expected_shop_domain = _validated_shop(expected_shop_domain)
        _validated_path(endpoint_path, limits.max_path_bytes)
        if not callable(clock_ns):
            raise RuntimeApiContractError("runtime clock must be callable")
        self._backend = backend if backend is not None else UnavailableCatalogBackend()
        self._authorizer = authorizer if authorizer is not None else DenyAllProxyAuthorizer()
        self._capability_gate = (
            capability_gate if capability_gate is not None else FailClosedCapabilityGate()
        )
        self._endpoint_path = endpoint_path
        self._limits = limits
        self._clock_ns = clock_ns

    def catalog(
        self,
        request: RuntimeHttpRequest,
        *,
        cancellation: RequestCancellation | None = None,
    ) -> RuntimeHttpResponse:
        """Verify, parse, acquire once, execute once, validate, and serialize."""

        if cancellation is None:
            cancellation = RequestCancellation()
        if type(cancellation) is not RequestCancellation:
            return _error_response(503, CatalogErrorCode.TEMPORARILY_UNAVAILABLE)
        try:
            control = self._new_control(cancellation)
            return self._catalog(request, control)
        except Exception as exc:
            cancellation.raise_if_cancelled()
            return _normalized_error_response(exc)

    def liveness(self) -> RuntimeHttpResponse:
        """Process-only liveness: it never consults a backend or Shopify."""

        return _health_response(200, "live")

    def readiness(self, *, cancellation: RequestCancellation | None = None) -> RuntimeHttpResponse:
        """Fail closed unless one pinned lease has accepted capability evidence."""

        if cancellation is None:
            cancellation = RequestCancellation()
        if type(cancellation) is not RequestCancellation:
            return _health_response(503, "not_ready")
        try:
            control = self._new_control(cancellation)
            control.checkpoint()
            if not _runtime_composition_is_evidence_bound(
                self._authorizer,
                self._backend,
                self._capability_gate,
            ):
                return _health_response(503, "not_ready")
            if not _contract_output_is_verified():
                return _health_response(503, "not_ready")
            lease = self._acquire(control)
            try:
                _, lease_shop = _lease_identity(lease)
                if lease_shop != self._expected_shop_domain:
                    raise _OutputContractFailure
                try:
                    ready = self._capability_gate.ready(lease, control=control)
                except CatalogBackendFailure:
                    control.checkpoint()
                    raise
                except Exception as exc:
                    control.checkpoint()
                    raise CatalogBackendFailure(CatalogErrorCode.TEMPORARILY_UNAVAILABLE) from exc
                control.checkpoint()
                if type(ready) is not bool or not ready:
                    response = _health_response(503, "not_ready")
                else:
                    control.checkpoint()
                    response = _health_response(200, "ready")
            except BaseException:
                _release_lease(lease, control=control, suppress=True)
                raise
            _release_lease(lease, control=control, suppress=False)
            return response
        except RequestCancelled:
            raise
        except Exception:
            cancellation.raise_if_cancelled()
            return _health_response(503, "not_ready")

    def _new_control(self, cancellation: RequestCancellation) -> RequestControl:
        cancellation.raise_if_cancelled()
        try:
            now = self._clock_ns()
        except Exception as exc:
            raise RequestDeadlineExceeded from exc
        if type(now) is not int or now < 0:
            raise RequestDeadlineExceeded
        return RequestControl(
            deadline_ns=now + self._limits.request_timeout_ms * 1_000_000,
            cancellation=cancellation,
            _clock_ns=self._clock_ns,
        )

    def _catalog(self, request: RuntimeHttpRequest, control: RequestControl) -> RuntimeHttpResponse:
        content_length = self._validate_metadata(request, control)
        if not _runtime_composition_is_evidence_bound(
            self._authorizer,
            self._backend,
            self._capability_gate,
        ):
            raise CatalogBackendFailure(CatalogErrorCode.UNSUPPORTED_CAPABILITY)
        try:
            identity = self._authorizer.verify(
                raw_query=request.raw_query,
                request_path=request.path,
                control=control,
            )
        except (ProxyRequestRejected, ProxyVerifierUnavailable):
            control.checkpoint()
            raise
        except Exception as exc:
            control.checkpoint()
            raise ProxyVerifierUnavailable from exc
        try:
            if type(identity) is not VerifiedProxyIdentity:
                raise RuntimeApiContractError("verified proxy identity is invalid")
            shop_domain = _validated_shop(identity.shop_domain)
        except Exception as exc:
            raise ProxyVerifierUnavailable from exc
        if shop_domain != self._expected_shop_domain:
            raise ProxyRequestRejected
        control.checkpoint()
        body = self._read_body(request.body_chunks, content_length, control)
        envelope = CatalogRequestEnvelopeV1.from_json_bytes(
            body,
            byte_limit=self._limits.max_request_body_bytes,
            cursor_char_limit=self._limits.max_cursor_chars,
        )
        control.checkpoint()
        lease = self._acquire(control)
        try:
            lease_generation, lease_shop = _lease_identity(lease)
            if lease_shop != self._expected_shop_domain:
                raise _OutputContractFailure
            self._require_capabilities(lease, envelope.request, control)
            control.checkpoint()
            try:
                result = lease.fetch_page(
                    envelope.request,
                    envelope.cursor,
                    control=control,
                )
            except CatalogBackendFailure:
                control.checkpoint()
                raise
            except Exception as exc:
                control.checkpoint()
                raise CatalogBackendFailure(CatalogErrorCode.TEMPORARILY_UNAVAILABLE) from exc
            control.checkpoint()
            response = _validated_result(
                result,
                request=envelope.request,
                dataset_generation=lease_generation,
                cursor_char_limit=self._limits.max_cursor_chars,
                request_body_byte_limit=self._limits.max_request_body_bytes,
            )
            try:
                body = response.to_json_bytes()
            except Exception as exc:
                raise _OutputContractFailure from exc
            if len(body) > self._limits.max_response_body_bytes:
                raise _OutputContractFailure
            control.checkpoint()
            http_response = RuntimeHttpResponse(status=200, headers=_JSON_HEADERS, body=body)
        except BaseException:
            _release_lease(lease, control=control, suppress=True)
            raise
        _release_lease(lease, control=control, suppress=False)
        return http_response

    def _validate_metadata(
        self, request: RuntimeHttpRequest, control: RequestControl
    ) -> int | None:
        if type(request) is not RuntimeHttpRequest:
            raise RuntimeApiContractError("HTTP request must be canonical")
        if type(request.method) is not str or request.method != "POST":
            raise RuntimeApiContractError("catalog method is invalid")
        path = _validated_path(request.path, self._limits.max_path_bytes)
        if path != self._endpoint_path:
            raise RuntimeApiContractError("catalog path is invalid")
        if type(request.raw_query) is not bytes:
            raise RuntimeApiContractError("raw query must be bytes")
        if len(
            request.raw_query
        ) > self._limits.max_raw_query_bytes or request.raw_query.startswith(b"?"):
            raise RuntimeApiContractError("raw query is invalid")
        if type(request.body_chunks) is not tuple or not (
            1 <= len(request.body_chunks) <= self._limits.max_body_chunks
        ):
            raise RuntimeApiContractError("body chunk count is invalid")
        control.checkpoint()
        return _validated_headers(request.headers, self._limits)

    def _read_body(
        self,
        chunks: tuple[bytes, ...],
        content_length: int | None,
        control: RequestControl,
    ) -> bytes:
        parts: list[bytes] = []
        total = 0
        for chunk in chunks:
            control.checkpoint()
            if type(chunk) is not bytes:
                raise RuntimeApiContractError("body chunks must be bytes")
            total += len(chunk)
            if total > self._limits.max_request_body_bytes:
                raise RuntimeApiContractError("request body exceeds the byte limit")
            parts.append(chunk)
        if total == 0 or (content_length is not None and content_length != total):
            raise RuntimeApiContractError("request body length is invalid")
        return b"".join(parts)

    def _acquire(self, control: RequestControl) -> CatalogGenerationLease:
        try:
            lease = self._backend.acquire(control=control)
        except CatalogBackendFailure:
            control.checkpoint()
            raise
        except Exception as exc:
            control.checkpoint()
            raise CatalogBackendFailure(CatalogErrorCode.TEMPORARILY_UNAVAILABLE) from exc
        try:
            control.checkpoint()
        except BaseException:
            _release_lease(lease, control=control, suppress=True, checkpoint=False)
            raise
        return lease

    def _require_capabilities(
        self,
        lease: CatalogGenerationLease,
        request: CatalogRequestV1,
        control: RequestControl,
    ) -> None:
        try:
            request.require_executable()
        except RuntimeContractError as exc:
            control.checkpoint()
            raise CatalogBackendFailure(CatalogErrorCode.UNSUPPORTED_CAPABILITY) from exc
        try:
            result = self._capability_gate.require_catalog(lease, request, control=control)
        except CatalogBackendFailure:
            control.checkpoint()
            raise
        except Exception as exc:
            control.checkpoint()
            raise CatalogBackendFailure(CatalogErrorCode.TEMPORARILY_UNAVAILABLE) from exc
        control.checkpoint()
        if result is not None:
            raise _OutputContractFailure


def _canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, UnicodeEncodeError, ValueError) as exc:
        raise RuntimeApiContractError("runtime value is not canonically serializable") from exc


def _runtime_composition_is_evidence_bound(
    authorizer: object,
    backend: object,
    capability_gate: object,
) -> bool:
    try:
        return (
            type(authorizer) is AppProxyVerifierAuthorizer
            and _bound_app_proxy_verifier(authorizer) is not None
            and type(backend) is EvidenceBoundCatalogBackend
            and type(capability_gate) is EvidenceBoundCapabilityGate
            and capability_gate._backend_token is backend._token
        )
    except Exception:
        return False


def _bound_app_proxy_verifier(authorizer: object) -> AppProxyVerifier | None:
    if type(authorizer) is not AppProxyVerifierAuthorizer:
        return None
    verifier = _lookup_authorizer_verifier(authorizer)
    return verifier if type(verifier) is AppProxyVerifier else None


def _duplicate_key(_pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in _pairs:
        if key in result:
            raise RuntimeApiContractError("runtime JSON contains a duplicate key")
        result[key] = value
    return result


def _parse_integer(value: str) -> int:
    if len(value.lstrip("-")) > 19:
        raise RuntimeApiContractError("runtime JSON integer is outside signed 64-bit range")
    return int(value)


def _reject_number(_value: str) -> None:
    raise RuntimeApiContractError("runtime JSON number is unsupported")


def _load_json_object(raw: bytes, *, byte_limit: int) -> dict[str, Any]:
    if type(raw) is not bytes or not raw or len(raw) > byte_limit or raw.startswith(_BOMS):
        raise RuntimeApiContractError("runtime JSON input is invalid")
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_duplicate_key,
            parse_constant=_reject_number,
            parse_float=_reject_number,
            parse_int=_parse_integer,
        )
    except RuntimeApiContractError:
        raise
    except (RecursionError, UnicodeDecodeError, ValueError) as exc:
        raise RuntimeApiContractError("runtime JSON input is invalid") from exc
    _validate_unicode(value)
    if type(value) is not dict:
        raise RuntimeApiContractError("runtime JSON root must be an object")
    return value


def _validate_unicode(root: Any) -> None:
    pending = [root]
    while pending:
        value = pending.pop()
        if type(value) is str:
            if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
                raise RuntimeApiContractError("runtime JSON contains invalid Unicode")
        elif type(value) is dict:
            pending.extend(value.keys())
            pending.extend(value.values())
        elif type(value) is list:
            pending.extend(value)


def _exact_keys(value: dict[str, Any], expected: frozenset[str]) -> None:
    if any(type(key) is not str for key in value) or frozenset(value) != expected:
        raise RuntimeApiContractError("runtime object has missing or unknown fields")


def _validated_public_limit(value: Any, hard_maximum: int) -> int:
    if type(value) is not int or not 1 <= value <= hard_maximum:
        raise RuntimeApiContractError("runtime parser limit is invalid")
    return value


def _validated_cursor(value: Any, char_limit: int) -> str | None:
    if value is None:
        return None
    if (
        type(value) is not str
        or not 1 <= len(value) <= char_limit
        or _CURSOR_RE.fullmatch(value) is None
    ):
        raise InvalidOpaqueCursorError("opaque cursor is invalid")
    return value


def _validate_request_scope(request: CatalogRequestV1) -> None:
    query = request.query
    _validate_query_bound(query)
    if type(request.product_family) is not RequestFamily:
        raise RuntimeApiContractError("catalog family is invalid")
    if query not in (None, "") and request.product_family is not RequestFamily.SINGLE:
        raise IncompatibleCatalogRequestError("catalog query is incompatible with family")


def _validate_query_bound(query: Any) -> None:
    if query is not None and type(query) is not str:
        raise RuntimeApiContractError("catalog query is invalid")
    if query is not None and len(query) > MAX_QUERY_CHARS:
        raise RuntimeApiContractError("catalog query exceeds the character limit")
    if query is None:
        return
    try:
        normalized = normalize_search_text(query)
    except CanonicalSearchError:
        invalid = True
    else:
        invalid = len(normalized) > MAX_QUERY_CHARS
    if invalid:
        raise RuntimeApiContractError("catalog query exceeds the normalized character limit")


def _raw_request_is_incompatible(value: Any) -> bool:
    if type(value) is not dict or frozenset(value) != CatalogRequestV1.FIELDS:
        return False
    filters = value.get("filters")
    if type(filters) is not dict or frozenset(filters) != frozenset({"inStock", "productSubtype"}):
        return False
    family = value.get("productFamily")
    subtype = filters.get("productSubtype")
    candidate = (
        type(family) is str
        and family in {item.value for item in RequestFamily}
        and type(subtype) is str
        and family != RequestFamily.SEALED.value
    )
    if not candidate:
        return False
    sanitized = dict(value)
    sanitized["productFamily"] = RequestFamily.SEALED.value
    try:
        request = CatalogRequestV1.from_dict(sanitized)
        _validate_query_bound(request.query)
    except RuntimeContractError:
        return False
    return True


def _validated_shop(value: Any) -> str:
    if type(value) is not str or _SHOP_RE.fullmatch(value) is None:
        raise RuntimeApiContractError("verified shop domain is invalid")
    return value


def _validated_generation(value: Any) -> str:
    if type(value) is not str or _GENERATION_RE.fullmatch(value) is None:
        raise _OutputContractFailure
    return value


def _validated_path(value: Any, byte_limit: int) -> str:
    if type(value) is not str or not value.startswith("/") or "?" in value or "#" in value:
        raise RuntimeApiContractError("HTTP path is invalid")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise RuntimeApiContractError("HTTP path is invalid") from exc
    if len(encoded) > byte_limit or any(byte < 32 or byte == 127 for byte in encoded):
        raise RuntimeApiContractError("HTTP path is invalid")
    return value


def _validated_headers(headers: Any, limits: RuntimeLimits) -> int | None:
    if type(headers) is not tuple or len(headers) > limits.max_header_count:
        raise RuntimeApiContractError("HTTP headers are invalid")
    normalized: dict[bytes, bytes] = {}
    total = 0
    for entry in headers:
        if type(entry) is not tuple or len(entry) != 2:
            raise RuntimeApiContractError("HTTP header entry is invalid")
        name, value = entry
        if type(name) is not bytes or type(value) is not bytes:
            raise RuntimeApiContractError("HTTP header values must be bytes")
        total += len(name) + len(value)
        if (
            not name
            or len(name) > limits.max_header_name_bytes
            or len(value) > limits.max_header_value_bytes
            or total > limits.max_header_bytes
            or _HEADER_NAME_RE.fullmatch(name) is None
            or any((byte < 32 and byte != 9) or byte == 127 for byte in value)
        ):
            raise RuntimeApiContractError("HTTP header is invalid")
        lowered = name.lower()
        if lowered in normalized:
            raise RuntimeApiContractError("duplicate HTTP header is invalid")
        normalized[lowered] = value.strip(b" \t")
    content_type = normalized.get(b"content-type")
    if content_type is None or content_type.lower() not in {
        b"application/json",
        b"application/json; charset=utf-8",
    }:
        raise RuntimeApiContractError("content type is invalid")
    content_encoding = normalized.get(b"content-encoding")
    if content_encoding is not None and content_encoding.lower() != b"identity":
        raise RuntimeApiContractError("content encoding is invalid")
    if b"transfer-encoding" in normalized:
        raise RuntimeApiContractError("transfer encoding is invalid")
    raw_length = normalized.get(b"content-length")
    if raw_length is None:
        return None
    if not raw_length or len(raw_length) > 19 or not raw_length.isdigit():
        raise RuntimeApiContractError("content length is invalid")
    content_length = int(raw_length)
    if content_length > limits.max_request_body_bytes:
        raise RuntimeApiContractError("content length exceeds the byte limit")
    return content_length


def _product_gid_key(product_gid: str) -> tuple[int, str]:
    if type(product_gid) is not str:
        raise RuntimeApiContractError("catalog Product GID is invalid")
    match = _PRODUCT_GID_RE.fullmatch(product_gid)
    if match is None:
        raise RuntimeApiContractError("catalog Product GID is invalid")
    digits = match.group(1)
    return len(digits), digits


def _canonical_request(request: object) -> bool:
    if type(request) is not CatalogRequestV1:
        return False
    try:
        canonical = CatalogRequestV1.from_json_bytes(request.to_json_bytes())
        _validate_request_scope(canonical)
    except Exception:
        return False
    return canonical == request


def _new_evidence_bound_generation(
    verified: VerifiedReconciledGenerationV1,
    projection: CatalogProjection,
    cursor_codec: CursorCodecV1,
    evidence: VerifiedCatalogCoreEvidenceV1,
    *,
    expected_code_sha: str,
    clock: Callable[[], datetime],
) -> _EvidenceBoundGeneration:
    try:
        if (
            type(verified) is not VerifiedReconciledGenerationV1
            or type(projection) is not CatalogProjection
            or type(cursor_codec) is not CursorCodecV1
            or type(evidence) is not VerifiedCatalogCoreEvidenceV1
            or type(expected_code_sha) is not str
            or _CODE_SHA_RE.fullmatch(expected_code_sha) is None
            or not callable(clock)
        ):
            raise RuntimeApiContractError("catalog runtime binding is invalid")
        checked = VerifiedReconciledGenerationV1(
            verified.generation,
            verified.summary_sha256,
        )
        generation = checked.generation
        manifest = generation.dataset_manifest
        records = generation.records
        manifest.validate_records(records)
        parts = generation.source_manifest.parts
        if type(parts) is not tuple or len(parts) != 2:
            raise RuntimeApiContractError("catalog runtime binding is invalid")
        shop_domain = _validated_shop(parts[0].shop_domain)
        if (
            parts[1].shop_domain != shop_domain
            or parts[1].source_code_sha != parts[0].source_code_sha
            or type(parts[0].source_code_sha) is not str
            or _CODE_SHA_RE.fullmatch(parts[0].source_code_sha) is None
        ):
            raise RuntimeApiContractError("catalog runtime binding is invalid")
        reopened = CatalogProjection.open(
            projection.path,
            expected_generation=manifest.dataset_generation,
        )
        if (
            reopened._file_fingerprint != projection._file_fingerprint
            or reopened.manifest != manifest
            or projection.manifest != manifest
        ):
            raise RuntimeApiContractError("catalog runtime binding is invalid")
        codec = CursorCodecV1(cursor_codec.secret, cursor_codec.ttl_seconds)
        binding = (
            shop_domain,
            checked.summary_sha256,
            manifest.dataset_generation,
            manifest.catalog_content_sha256,
            reopened._file_fingerprint.content_sha256,
            expected_code_sha,
        )
        evidence_binding = (
            evidence.shop_domain,
            evidence.summary_sha256,
            evidence.dataset_generation,
            evidence.catalog_content_sha256,
            evidence.projection_fingerprint,
            evidence.code_sha,
        )
        if (
            binding != evidence_binding
            or evidence.code_sha != expected_code_sha
            or _SHA256_RE.fullmatch(binding[1]) is None
            or _GENERATION_RE.fullmatch(binding[2]) is None
            or _SHA256_RE.fullmatch(binding[3]) is None
            or _SHA256_RE.fullmatch(binding[4]) is None
        ):
            raise RuntimeApiContractError("catalog runtime binding is invalid")
        public_items = [
            CatalogItemV1.from_product_record(record)
            for record in records
            if record.publishable and record.product_family is not ProductFamily.UNCLASSIFIED
        ]
        public_items.sort(key=lambda item: _product_gid_key(item.product_gid))
        paginator = CatalogPaginator(
            AtomicCatalogActivation(reopened),
            codec,
            clock=clock,
        )
        search = prepare_single_card_search(records)
        facets = PreparedFacetCatalog(tuple(public_items))
        return _EvidenceBoundGeneration(
            verified=checked,
            projection=reopened,
            cursor_codec=codec,
            evidence=evidence,
            records=records,
            items=tuple(public_items),
            search=search,
            facets=facets,
            paginator=paginator,
            clock=clock,
            binding=binding,
        )
    except RuntimeApiContractError:
        raise
    except Exception:
        raise RuntimeApiContractError("catalog runtime binding is invalid") from None


def _evidence_binding_is_current(generation: _EvidenceBoundGeneration) -> bool:
    try:
        if type(generation) is not _EvidenceBoundGeneration:
            return False
        verified = generation.verified
        projection = generation.projection
        evidence = generation.evidence
        if (
            type(verified) is not VerifiedReconciledGenerationV1
            or type(projection) is not CatalogProjection
            or type(generation.cursor_codec) is not CursorCodecV1
            or type(evidence) is not VerifiedCatalogCoreEvidenceV1
            or type(generation.search) is not SingleCardSearchIndex
            or type(generation.facets) is not PreparedFacetCatalog
            or type(generation.paginator) is not CatalogPaginator
        ):
            return False
        projection._assert_file_unchanged()
        manifest = verified.generation.dataset_manifest
        parts = verified.generation.source_manifest.parts
        if type(parts) is not tuple or len(parts) != 2:
            return False
        binding = (
            parts[0].shop_domain,
            verified.summary_sha256,
            manifest.dataset_generation,
            manifest.catalog_content_sha256,
            projection._file_fingerprint.content_sha256,
            generation.binding[5],
        )
        evidence_binding = (
            evidence.shop_domain,
            evidence.summary_sha256,
            evidence.dataset_generation,
            evidence.catalog_content_sha256,
            evidence.projection_fingerprint,
            evidence.code_sha,
        )
        return (
            generation.binding == binding == evidence_binding
            and parts[1].shop_domain == binding[0]
            and parts[1].source_code_sha == parts[0].source_code_sha
            and type(parts[0].source_code_sha) is str
            and _CODE_SHA_RE.fullmatch(parts[0].source_code_sha) is not None
            and projection.dataset_generation == binding[2]
            and projection.manifest == manifest
            and generation.paginator._activation.active_generation == binding[2]
        )
    except Exception:
        return False


def _fetch_evidence_bound_page(
    generation: _EvidenceBoundGeneration,
    request: CatalogRequestV1,
    cursor: str | None,
    *,
    control: RequestControl,
) -> CatalogLeaseResult:
    if not _canonical_request(request):
        raise CatalogBackendFailure(CatalogErrorCode.UNSUPPORTED_CAPABILITY)
    control.checkpoint()
    if request.query in (None, "") and not request.filters.nonempty:
        result = generation.paginator.fetch_page(
            request,
            cursor=cursor,
            checkpoint=control.checkpoint,
        )
        return CatalogLeaseResult(result.page, result.next_cursor)

    now = generation.clock()
    if cursor is None:
        context = CursorContextV1.from_request(
            request,
            generation.binding[2],
            last_product_gid=None,
            expires_at=generation.cursor_codec.expires_at(now),
        )
    else:
        context = generation.cursor_codec.decode(
            cursor,
            expected_request=request,
            expected_generation=generation.binding[2],
            now=now,
        )
    control.checkpoint()
    query_product_gids: tuple[str, ...] | None = None
    if request.query not in (None, ""):
        search = search_single_cards(
            generation.search,
            game=request.game,
            query=request.query,
            checkpoint=control.checkpoint,
        )
        if search.mode is SearchMode.BROWSE:
            browse_gids: list[str] = []
            for item in generation.items:
                control.checkpoint()
                if item.game is request.game and item.product_family is ProductFamily.SINGLE:
                    browse_gids.append(item.product_gid)
            query_product_gids = tuple(browse_gids)
        else:
            hit_gids: list[str] = []
            for hit in search.hits:
                control.checkpoint()
                hit_gids.append(hit.product_gid)
            query_product_gids = tuple(hit_gids)
    evaluation = generation.facets.evaluate(
        request,
        query_product_gids=query_product_gids,
        checkpoint=control.checkpoint,
    )
    return _keyset_tuple_page(
        generation,
        request,
        context,
        evaluation.items,
        control=control,
    )


def _keyset_tuple_page(
    generation: _EvidenceBoundGeneration,
    request: CatalogRequestV1,
    context: CursorContextV1,
    items: tuple[CatalogItemV1, ...],
    *,
    control: RequestControl,
) -> CatalogLeaseResult:
    control.checkpoint()
    after_key = (
        None if context.last_product_gid is None else _product_gid_key(context.last_product_gid)
    )
    page_items: list[CatalogItemV1] = []
    has_next_page = False
    for item in items:
        control.checkpoint()
        item_key = _product_gid_key(item.product_gid)
        if after_key is not None and item_key <= after_key:
            continue
        if len(page_items) == request.page_size:
            has_next_page = True
            break
        page_items.append(item)
    returned_variant_count = 0
    for item in page_items:
        control.checkpoint()
        returned_variant_count += len(item.variants)
    immutable_items = tuple(page_items)
    next_context = (
        CursorContextV1.from_request(
            request,
            generation.binding[2],
            last_product_gid=immutable_items[-1].product_gid,
            expires_at=context.expires_at,
        )
        if has_next_page
        else None
    )
    page = CatalogPageV1(
        dataset_generation=generation.binding[2],
        request=request,
        request_context_sha256=context.request_context_sha256,
        items=immutable_items,
        returned_product_count=len(immutable_items),
        returned_variant_count=returned_variant_count,
        has_next_page=has_next_page,
        next_cursor_context=next_context,
    )
    page.validate_for_context(context)
    control.checkpoint()
    next_cursor = None if next_context is None else generation.cursor_codec.encode(next_context)
    control.checkpoint()
    return CatalogLeaseResult(page, next_cursor)


def _catalog_execution_error_code(error: Exception) -> CatalogErrorCode:
    if isinstance(error, CursorContextMismatchError):
        code = CatalogErrorCode.CURSOR_CONTEXT_MISMATCH
    elif isinstance(error, StaleGenerationError):
        code = CatalogErrorCode.RESTART_REQUIRED
    elif isinstance(error, (CursorExpiredError, InvalidCursorError)):
        code = CatalogErrorCode.INVALID_CURSOR
    elif isinstance(error, DatasetUnavailableError):
        code = CatalogErrorCode.DATASET_UNAVAILABLE
    elif isinstance(error, UnsupportedPaginationRequestError):
        code = CatalogErrorCode.UNSUPPORTED_CAPABILITY
    elif isinstance(error, (CanonicalSearchError, FacetContractError, RuntimeContractError)):
        code = CatalogErrorCode.DATASET_UNAVAILABLE
    elif isinstance(error, PaginationContractError):
        code = CatalogErrorCode.TEMPORARILY_UNAVAILABLE
    else:
        code = CatalogErrorCode.TEMPORARILY_UNAVAILABLE
    return code


def _lease_identity(lease: Any) -> tuple[str, str]:
    try:
        generation = _validated_generation(lease.dataset_generation)
        shop_domain = _validated_shop(lease.shop_domain)
    except _OutputContractFailure:
        raise
    except Exception as exc:
        raise _OutputContractFailure from exc
    return generation, shop_domain


def _validated_result(
    value: Any,
    *,
    request: CatalogRequestV1,
    dataset_generation: str,
    cursor_char_limit: int,
    request_body_byte_limit: int,
) -> CatalogResponseEnvelopeV1:
    if type(value) is not CatalogLeaseResult or type(value.page) is not CatalogPageV1:
        raise _OutputContractFailure
    try:
        page = CatalogPageV1.from_json_bytes(value.page.to_json_bytes())
        page.require_output_capability()
        request_bytes = request.to_json_bytes()
        page_request_bytes = page.request.to_json_bytes()
        next_cursor = _validated_cursor(value.next_cursor, cursor_char_limit)
        next_request_bytes = (
            None
            if next_cursor is None
            else CatalogRequestEnvelopeV1(request=request, cursor=next_cursor).to_json_bytes()
        )
    except Exception as exc:
        raise _OutputContractFailure from exc
    if (
        page.dataset_generation != dataset_generation
        or page_request_bytes != request_bytes
        or page.has_next_page != (next_cursor is not None)
    ):
        raise _OutputContractFailure
    if next_request_bytes is not None and len(next_request_bytes) > request_body_byte_limit:
        raise _OutputContractFailure
    try:
        return CatalogResponseEnvelopeV1(page=page, next_cursor=next_cursor)
    except RuntimeApiContractError as exc:
        raise _OutputContractFailure from exc


def _backend_error_response(error: CatalogBackendFailure) -> RuntimeHttpResponse:
    try:
        code = error.code
    except Exception:
        return _error_response(503, CatalogErrorCode.TEMPORARILY_UNAVAILABLE)
    if type(code) is not CatalogErrorCode or code not in _BACKEND_STATUS:
        return _error_response(503, CatalogErrorCode.TEMPORARILY_UNAVAILABLE)
    return _error_response(_BACKEND_STATUS[code], code)


def _normalized_error_response(error: Exception) -> RuntimeHttpResponse:
    if isinstance(error, RequestDeadlineExceeded | ProxyVerifierUnavailable):
        return _error_response(503, CatalogErrorCode.TEMPORARILY_UNAVAILABLE)
    if isinstance(error, ProxyRequestRejected):
        return _error_response(401, CatalogErrorCode.INVALID_REQUEST)
    if isinstance(error, InvalidOpaqueCursorError):
        return _error_response(400, CatalogErrorCode.INVALID_CURSOR)
    if isinstance(error, IncompatibleCatalogRequestError):
        return _error_response(422, CatalogErrorCode.INCOMPATIBLE_FILTER)
    if isinstance(error, RuntimeApiContractError):
        return _error_response(400, CatalogErrorCode.INVALID_REQUEST)
    if isinstance(error, CatalogBackendFailure):
        return _backend_error_response(error)
    if isinstance(error, _OutputContractFailure):
        return _error_response(500, CatalogErrorCode.CONTRACT_VIOLATION)
    return _error_response(503, CatalogErrorCode.TEMPORARILY_UNAVAILABLE)


def _error_response(status: int, code: CatalogErrorCode) -> RuntimeHttpResponse:
    body = CatalogErrorV1.for_code(code).to_json_bytes()
    return RuntimeHttpResponse(status=status, headers=_JSON_HEADERS, body=body)


def _health_response(status: int, state: str) -> RuntimeHttpResponse:
    body = _canonical_json_bytes({"contractVersion": CONTRACT_VERSION, "status": state})
    return RuntimeHttpResponse(status=status, headers=_JSON_HEADERS, body=body)


def _contract_output_is_verified() -> bool:
    try:
        return all(
            DEFAULT_CAPABILITIES_V1.feature_state(name) is CapabilityState.VERIFIED
            for name in ("activeIndex", "catalogOutput", "cursorCodec")
        )
    except Exception:
        return False


def _release_lease(
    lease: Any,
    *,
    control: RequestControl,
    suppress: bool,
    checkpoint: bool = True,
) -> None:
    try:
        result = lease.close()
        if result is not None:
            raise RuntimeApiContractError("lease close result is invalid")
        if checkpoint:
            control.checkpoint()
    except RequestCancelled:
        if not suppress:
            raise
    except Exception as exc:
        if not suppress:
            raise CatalogBackendFailure(CatalogErrorCode.TEMPORARILY_UNAVAILABLE) from exc


__all__ = [
    "AppProxyVerifierAuthorizer",
    "CatalogBackend",
    "CatalogBackendFailure",
    "CatalogGenerationLease",
    "CatalogLeaseResult",
    "CatalogRequestEnvelopeV1",
    "CatalogResponseEnvelopeV1",
    "DenyAllProxyAuthorizer",
    "EvidenceBoundCapabilityGate",
    "EvidenceBoundCatalogBackend",
    "EvidenceBoundCatalogLease",
    "FailClosedCapabilityGate",
    "IncompatibleCatalogRequestError",
    "InvalidOpaqueCursorError",
    "ProxyAuthorizer",
    "ProxyRequestRejected",
    "ProxyVerifierUnavailable",
    "RequestCancellation",
    "RequestCancelled",
    "RequestControl",
    "RequestDeadlineExceeded",
    "RuntimeApiContractError",
    "RuntimeCapabilityGate",
    "RuntimeCatalogService",
    "RuntimeHttpRequest",
    "RuntimeHttpResponse",
    "RuntimeLimits",
    "UnavailableCatalogBackend",
    "VerifiedProxyIdentity",
]
