from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Any

import pytest

import nla_catalog_gateway.runtime_api as runtime_api
from nla_catalog_gateway.runtime_api import (
    CatalogBackendFailure,
    CatalogLeaseResult,
    CatalogRequestEnvelopeV1,
    CatalogResponseEnvelopeV1,
    DenyAllProxyAuthorizer,
    FailClosedCapabilityGate,
    IncompatibleCatalogRequestError,
    InvalidOpaqueCursorError,
    ProxyRequestRejected,
    ProxyVerifierUnavailable,
    RequestCancellation,
    RequestCancelled,
    RequestControl,
    RequestDeadlineExceeded,
    RuntimeApiContractError,
    RuntimeCatalogService,
    RuntimeHttpRequest,
    RuntimeLimits,
    UnavailableCatalogBackend,
    VerifiedProxyIdentity,
)
from nla_catalog_gateway.runtime_contract import (
    CatalogErrorCode,
    CatalogErrorV1,
    CatalogFiltersV1,
    CatalogItemV1,
    CatalogPageV1,
    CatalogRequestV1,
    CatalogVariantItemV1,
    CursorContextV1,
    InventoryPolicy,
    RequestFamily,
)
from nla_catalog_gateway.taxonomy import Game, ProductFamily

GENERATION_A = "sha256:" + "a" * 64
GENERATION_B = "sha256:" + "b" * 64
SHOP = "synthetic.myshopify.com"
PATH = "/apps/nla/catalog"
EXPIRES = "2026-09-06T00:00:00Z"
OPAQUE_CURSOR = "opaque.signature"


def _request(
    *,
    family: RequestFamily = RequestFamily.ALL,
    query: str | None = None,
    in_stock: bool | None = None,
    subtype: str | None = None,
    page_size: int = 2,
) -> CatalogRequestV1:
    return CatalogRequestV1(
        game=Game.MAGIC,
        product_family=family,
        query=query,
        filters=CatalogFiltersV1(in_stock=in_stock, product_subtype=subtype),
        page_size=page_size,
    )


def _page(
    request: CatalogRequestV1,
    *,
    generation: str = GENERATION_A,
    terminal: bool = True,
) -> CatalogPageV1:
    context = CursorContextV1.from_request(
        request,
        generation,
        last_product_gid=None,
        expires_at=EXPIRES,
    )
    if terminal:
        return CatalogPageV1(
            dataset_generation=generation,
            request=request,
            request_context_sha256=context.request_context_sha256,
            items=(),
            returned_product_count=0,
            returned_variant_count=0,
            has_next_page=False,
            next_cursor_context=None,
        )
    item = CatalogItemV1(
        product_gid="gid://shopify/Product/1",
        handle="synthetic-card",
        commercial_title="Synthetic Card",
        canonical_card_name="Synthetic Card",
        game=Game.MAGIC,
        product_family=ProductFamily.SINGLE,
        product_subtype=None,
        variants=(
            CatalogVariantItemV1(
                variant_gid="gid://shopify/ProductVariant/2",
                title="Default Title",
                selected_options=(),
                price_text="1.00",
                compare_at_price_text=None,
                inventory_quantity=1,
                inventory_policy=InventoryPolicy.DENY,
                inventory_tracked=True,
            ),
        ),
    )
    next_context = CursorContextV1.from_request(
        request,
        generation,
        last_product_gid=item.product_gid,
        expires_at=EXPIRES,
    )
    return CatalogPageV1(
        dataset_generation=generation,
        request=request,
        request_context_sha256=context.request_context_sha256,
        items=(item,),
        returned_product_count=1,
        returned_variant_count=1,
        has_next_page=True,
        next_cursor_context=next_context,
    )


def _body(
    request: CatalogRequestV1 | None = None,
    *,
    cursor: str | None = None,
) -> bytes:
    return CatalogRequestEnvelopeV1(request=request or _request(), cursor=cursor).to_json_bytes()


def _http_request(
    body: bytes | None = None,
    *,
    headers: tuple[tuple[bytes, bytes], ...] | None = None,
    chunks: tuple[bytes, ...] | None = None,
    raw_query: bytes = b"shop=synthetic.myshopify.com&signature=redacted",
) -> RuntimeHttpRequest:
    actual_body = body or _body()
    return RuntimeHttpRequest(
        method="POST",
        path=PATH,
        raw_query=raw_query,
        headers=headers
        or (
            (b"content-type", b"application/json"),
            (b"content-length", str(len(actual_body)).encode("ascii")),
        ),
        body_chunks=chunks or (actual_body,),
    )


def _error(response: Any) -> CatalogErrorV1:
    return CatalogErrorV1.from_json_bytes(response.body)


class _Authorizer:
    def __init__(self, outcome: Any = None) -> None:
        self.outcome = VerifiedProxyIdentity(SHOP) if outcome is None else outcome
        self.calls: list[tuple[bytes, str]] = []

    def verify(
        self,
        *,
        raw_query: bytes,
        request_path: str,
        control: RequestControl,
    ) -> VerifiedProxyIdentity:
        control.checkpoint()
        self.calls.append((raw_query, request_path))
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


class _Lease:
    def __init__(
        self,
        result: Any,
        *,
        generation: Any = GENERATION_A,
        shop: Any = SHOP,
    ) -> None:
        self.dataset_generation = generation
        self.shop_domain = shop
        self.result = result
        self.calls: list[tuple[CatalogRequestV1, str | None, RequestControl]] = []
        self.close_calls = 0

    def fetch_page(
        self,
        request: CatalogRequestV1,
        cursor: str | None,
        *,
        control: RequestControl,
    ) -> CatalogLeaseResult:
        self.calls.append((request, cursor, control))
        if isinstance(self.result, BaseException):
            raise self.result
        if callable(self.result):
            return self.result(control)
        return self.result

    def close(self) -> None:
        self.close_calls += 1


class _Backend:
    def __init__(self, outcome: Any) -> None:
        self.outcome = outcome
        self.calls = 0

    def acquire(
        self,
        *,
        control: RequestControl,
        request: CatalogRequestV1 | None = None,
        cursor: str | None = None,
    ) -> _Lease:
        control.checkpoint()
        self.calls += 1
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        if callable(self.outcome):
            return self.outcome()
        return self.outcome


class _Gate:
    def __init__(
        self,
        *,
        catalog_outcome: Any = None,
        ready_outcome: Any = True,
    ) -> None:
        self.catalog_outcome = catalog_outcome
        self.ready_outcome = ready_outcome
        self.catalog_calls: list[tuple[Any, CatalogRequestV1]] = []
        self.ready_calls: list[Any] = []

    def require_catalog(
        self, lease: Any, request: CatalogRequestV1, *, control: RequestControl
    ) -> None:
        control.checkpoint()
        self.catalog_calls.append((lease, request))
        if isinstance(self.catalog_outcome, BaseException):
            raise self.catalog_outcome
        return self.catalog_outcome

    def ready(self, lease: Any, *, control: RequestControl) -> bool:
        control.checkpoint()
        self.ready_calls.append(lease)
        if isinstance(self.ready_outcome, BaseException):
            raise self.ready_outcome
        return self.ready_outcome


@pytest.fixture
def test_capabilities(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test-only override; no shipped implementation can enable runtime output."""

    monkeypatch.setattr(runtime_api, "_runtime_composition_is_evidence_bound", lambda *_: True)


def _service(
    lease: _Lease | None = None,
    *,
    backend: Any = None,
    authorizer: Any = None,
    gate: Any = None,
    limits: RuntimeLimits | None = None,
    clock: Any = None,
) -> RuntimeCatalogService:
    actual_lease = lease or _Lease(CatalogLeaseResult(_page(_request()), None))
    return RuntimeCatalogService(
        expected_shop_domain=SHOP,
        backend=backend or _Backend(actual_lease),
        authorizer=authorizer or _Authorizer(),
        capability_gate=gate or _Gate(),
        endpoint_path=PATH,
        limits=limits,
        clock_ns=clock or (lambda: 0),
    )


def test_default_components_are_fail_closed() -> None:
    control = RequestControl(10, RequestCancellation(), lambda: 0)
    with pytest.raises(ProxyRequestRejected):
        DenyAllProxyAuthorizer().verify(raw_query=b"", request_path=PATH, control=control)
    with pytest.raises(CatalogBackendFailure) as caught:
        UnavailableCatalogBackend().acquire(control=control)
    assert caught.value.code is CatalogErrorCode.DATASET_UNAVAILABLE
    gate = FailClosedCapabilityGate()
    with pytest.raises(CatalogBackendFailure) as caught:
        gate.require_catalog(_Lease(None), _request(), control=control)
    assert caught.value.code is CatalogErrorCode.UNSUPPORTED_CAPABILITY
    assert gate.ready(_Lease(None), control=control) is False


def test_runtime_limits_accept_defaults_and_reject_every_out_of_bound_field() -> None:
    limits = RuntimeLimits()
    assert limits.max_request_body_bytes == runtime_api.MAX_REQUEST_BODY_BYTES
    low_cases = {
        "max_request_body_bytes": 0,
        "max_response_body_bytes": 511,
        "max_cursor_chars": 0,
        "max_raw_query_bytes": 0,
        "max_path_bytes": 0,
        "max_header_count": 0,
        "max_header_name_bytes": 0,
        "max_header_value_bytes": 0,
        "max_header_bytes": 0,
        "max_body_chunks": 0,
        "request_timeout_ms": 0,
    }
    for name, value in low_cases.items():
        with pytest.raises(RuntimeApiContractError):
            replace(limits, **{name: value})
    for name in low_cases:
        with pytest.raises(RuntimeApiContractError):
            replace(limits, **{name: 10**9})
    with pytest.raises(RuntimeApiContractError):
        replace(limits, max_request_body_bytes=True)


def test_backend_failure_only_accepts_public_backend_codes() -> None:
    for code in runtime_api._BACKEND_STATUS:
        assert CatalogBackendFailure(code).code is code
    with pytest.raises(RuntimeApiContractError):
        CatalogBackendFailure(CatalogErrorCode.INVALID_REQUEST)
    with pytest.raises(RuntimeApiContractError):
        CatalogBackendFailure("dataset_unavailable")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "shop",
    [
        "A.myshopify.com",
        "a.b.myshopify.com",
        "-a.myshopify.com",
        "a-.myshopify.com",
        "x" * 64 + ".myshopify.com",
    ],
)
def test_verified_proxy_identity_requires_canonical_single_label_shop(shop: str) -> None:
    with pytest.raises(RuntimeApiContractError):
        VerifiedProxyIdentity(shop)
    assert VerifiedProxyIdentity(SHOP).shop_domain == SHOP


def test_cancellation_and_request_control_are_cooperative_and_monotonic() -> None:
    token = RequestCancellation()
    assert token.cancelled is False
    token.raise_if_cancelled()
    token.cancel()
    assert token.cancelled is True
    with pytest.raises(RequestCancelled):
        token.raise_if_cancelled()

    active = RequestControl(10, RequestCancellation(), lambda: 9)
    active.checkpoint()
    for clock in (lambda: 10, lambda: -1, lambda: "9"):
        with pytest.raises(RequestDeadlineExceeded):
            RequestControl(10, RequestCancellation(), clock).checkpoint()  # type: ignore[arg-type]

    def broken_clock() -> int:
        raise RuntimeError("secret clock")

    with pytest.raises(RequestDeadlineExceeded):
        RequestControl(10, RequestCancellation(), broken_clock).checkpoint()


def test_request_envelope_round_trips_canonically() -> None:
    envelope = CatalogRequestEnvelopeV1(_request(), OPAQUE_CURSOR)
    raw = envelope.to_json_bytes()
    assert (
        raw
        == json.dumps(
            envelope.as_dict(), ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode()
    )
    assert CatalogRequestEnvelopeV1.from_json_bytes(raw) == envelope


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"[]",
        b"{",
        b"\xef\xbb\xbf{}",
        b"\xff",
        b'{"contractVersion":1,"contractVersion":1,"cursor":null,"request":{}}',
        b'{"contractVersion":1.0,"cursor":null,"request":{}}',
        b'{"contractVersion":NaN,"cursor":null,"request":{}}',
        b'{"contractVersion":99999999999999999999,"cursor":null,"request":{}}',
        b'{"contractVersion":1,"cursor":null,"request":{},"unknown":1}',
        b'{"contractVersion":true,"cursor":null,"request":{}}',
    ],
)
def test_request_envelope_rejects_ambiguous_or_invalid_json(raw: bytes) -> None:
    with pytest.raises(RuntimeApiContractError):
        CatalogRequestEnvelopeV1.from_json_bytes(raw)


def test_request_envelope_rejects_nested_duplicate_keys_and_raw_cursor_context() -> None:
    request_json = json.dumps(_request().as_dict(), separators=(",", ":"))
    duplicated = request_json.replace('"game":"magic"', '"game":"magic","game":"magic"')
    raw = ('{"contractVersion":1,"cursor":null,"request":' + duplicated + "}").encode()
    with pytest.raises(RuntimeApiContractError):
        CatalogRequestEnvelopeV1.from_json_bytes(raw)

    raw_context = (
        CursorContextV1.from_request(
            _request(),
            GENERATION_A,
            last_product_gid=None,
            expires_at=EXPIRES,
        )
        .to_json_bytes()
        .decode()
    )
    with pytest.raises(InvalidOpaqueCursorError):
        CatalogRequestEnvelopeV1(_request(), raw_context)


def test_request_envelope_rejects_non_bytes_oversize_surrogate_and_bad_request() -> None:
    with pytest.raises(RuntimeApiContractError):
        CatalogRequestEnvelopeV1.from_json_bytes("{}")  # type: ignore[arg-type]
    with pytest.raises(RuntimeApiContractError):
        CatalogRequestEnvelopeV1.from_json_bytes(b"{}", byte_limit=1)
    raw = _body().replace(b'"q":null', b'"q":"\\ud800"')
    with pytest.raises(RuntimeApiContractError):
        CatalogRequestEnvelopeV1.from_json_bytes(raw)
    raw = _body().replace(b'"sort":"product_gid_asc"', b'"sort":"other"')
    with pytest.raises(RuntimeApiContractError):
        CatalogRequestEnvelopeV1.from_json_bytes(raw)


def test_request_envelope_bounds_query_cursor_and_incompatible_context() -> None:
    with pytest.raises(RuntimeApiContractError):
        CatalogRequestEnvelopeV1(_request(family=RequestFamily.SINGLE, query="q" * 257), None)
    with pytest.raises(IncompatibleCatalogRequestError):
        CatalogRequestEnvelopeV1(_request(family=RequestFamily.ALL, query="q"), None)
    for cursor in ("", "not-signed", ".signature", "opaque.", "é.signature"):
        with pytest.raises(InvalidOpaqueCursorError):
            CatalogRequestEnvelopeV1(_request(), cursor)
    with pytest.raises(InvalidOpaqueCursorError):
        CatalogRequestEnvelopeV1.from_json_bytes(_body(cursor=OPAQUE_CURSOR), cursor_char_limit=3)

    incompatible = _request(family=RequestFamily.SEALED, subtype="booster-box").as_dict()
    incompatible["productFamily"] = "single"
    raw = json.dumps(
        {"contractVersion": 1, "cursor": None, "request": incompatible},
        separators=(",", ":"),
    ).encode()
    with pytest.raises(IncompatibleCatalogRequestError):
        CatalogRequestEnvelopeV1.from_json_bytes(raw)


def test_request_envelope_direct_type_version_and_serialization_are_strict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(RuntimeApiContractError):
        CatalogRequestEnvelopeV1(_request(), None, contract_version=True)
    with pytest.raises(RuntimeApiContractError):
        CatalogRequestEnvelopeV1("request", None)  # type: ignore[arg-type]
    envelope = CatalogRequestEnvelopeV1(_request(), None)
    object.__setattr__(envelope.request, "query", object())
    with pytest.raises(RuntimeApiContractError):
        CatalogRequestEnvelopeV1(envelope.request, None)
    family = _request()
    object.__setattr__(family, "product_family", object())
    with pytest.raises(RuntimeApiContractError):
        CatalogRequestEnvelopeV1(family, None)
    object.__setattr__(envelope, "request", object())
    with pytest.raises(RuntimeApiContractError):
        envelope.to_json_bytes()

    good = CatalogRequestEnvelopeV1(_request(), None)
    monkeypatch.setattr(runtime_api, "MAX_REQUEST_BODY_BYTES", 1)
    with pytest.raises(RuntimeApiContractError):
        good.to_json_bytes()


def test_response_envelope_round_trips_terminal_and_authenticated_next_cursor(
    test_capabilities: None,
) -> None:
    request = _request(family=RequestFamily.SINGLE)
    terminal = CatalogResponseEnvelopeV1(_page(request), None)
    assert CatalogResponseEnvelopeV1.from_json_bytes(terminal.to_json_bytes()) == terminal

    continued = CatalogResponseEnvelopeV1(_page(request, terminal=False), OPAQUE_CURSOR)
    raw = continued.to_json_bytes()
    assert CatalogResponseEnvelopeV1.from_json_bytes(raw) == continued
    document = json.loads(raw)
    assert document["nextCursor"] == OPAQUE_CURSOR
    assert "nextCursorContext" not in document["page"]
    assert "nextCursorContext" in _page(request, terminal=False).as_dict()


def test_response_envelope_rejects_invalid_type_version_page_and_cursor_state() -> None:
    page = _page(_request())
    with pytest.raises(RuntimeApiContractError):
        CatalogResponseEnvelopeV1(page, None, contract_version=False)
    with pytest.raises(RuntimeApiContractError):
        CatalogResponseEnvelopeV1("page", None)  # type: ignore[arg-type]
    with pytest.raises(RuntimeApiContractError):
        CatalogResponseEnvelopeV1(page, OPAQUE_CURSOR)
    with pytest.raises(RuntimeApiContractError):
        CatalogResponseEnvelopeV1.from_json_bytes(
            b'{"contractVersion":1,"nextCursor":null,"page":null}'
        )
    with pytest.raises(RuntimeApiContractError):
        CatalogResponseEnvelopeV1.from_json_bytes(
            b'{"contractVersion":2,"nextCursor":null,"page":{}}'
        )
    with pytest.raises(RuntimeApiContractError):
        CatalogResponseEnvelopeV1.from_json_bytes(
            b'{"contractVersion":1,"nextCursor":null,"page":{}}'
        )


def test_public_response_decoder_rejects_unsigned_context_unknown_fields_and_noncanonical_json(
    test_capabilities: None,
) -> None:
    envelope = CatalogResponseEnvelopeV1(
        _page(_request(family=RequestFamily.SINGLE), terminal=False),
        OPAQUE_CURSOR,
    )
    raw = envelope.to_json_bytes()
    document = json.loads(raw)
    document["page"]["nextCursorContext"] = _page(
        _request(family=RequestFamily.SINGLE), terminal=False
    ).as_dict()["nextCursorContext"]
    with pytest.raises(RuntimeApiContractError, match="missing or unknown fields"):
        CatalogResponseEnvelopeV1.from_json_bytes(
            json.dumps(document, separators=(",", ":"), sort_keys=True).encode()
        )

    document = json.loads(raw)
    document["page"]["unknown"] = True
    with pytest.raises(RuntimeApiContractError, match="missing or unknown fields"):
        CatalogResponseEnvelopeV1.from_json_bytes(
            json.dumps(document, separators=(",", ":"), sort_keys=True).encode()
        )

    with pytest.raises(RuntimeApiContractError, match="not canonical"):
        CatalogResponseEnvelopeV1.from_json_bytes(b" " + raw)


def test_public_page_requires_boolean_nonterminal_state_with_an_item() -> None:
    terminal = CatalogResponseEnvelopeV1(_page(_request()), None)
    values = terminal.page.as_dict()
    values["hasNextPage"] = True
    raw = json.dumps(
        {"contractVersion": 1, "nextCursor": OPAQUE_CURSOR, "page": values},
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    with pytest.raises(RuntimeApiContractError, match="must contain an item"):
        CatalogResponseEnvelopeV1.from_json_bytes(raw)

    values["hasNextPage"] = 1
    with pytest.raises(RuntimeApiContractError, match="must be a boolean"):
        runtime_api._PublicCatalogPageV1.from_dict(values)


def test_private_public_page_copy_rejects_forged_or_invalid_fields() -> None:
    safe = CatalogResponseEnvelopeV1(_page(_request()), None).page
    with pytest.raises(RuntimeApiContractError, match="public page fields are invalid"):
        runtime_api._PublicCatalogPageV1(
            dataset_generation=safe.dataset_generation,
            request=safe.request,
            request_context_sha256=safe.request_context_sha256,
            items=safe.items,
            returned_product_count=1,
            returned_variant_count=safe.returned_variant_count,
            has_next_page=False,
        )
    with pytest.raises(RuntimeApiContractError, match="must be canonical"):
        runtime_api._PublicCatalogPageV1.from_catalog_page(object())  # type: ignore[arg-type]

    forged = _page(_request())
    object.__setattr__(forged, "request", object())
    with pytest.raises(RuntimeApiContractError, match="must be canonical"):
        runtime_api._PublicCatalogPageV1.from_catalog_page(forged)

    with pytest.raises(RuntimeApiContractError, match="must be an object"):
        runtime_api._PublicCatalogPageV1.from_dict([])  # type: ignore[arg-type]
    values = safe.as_dict()
    values["request"] = None
    with pytest.raises(RuntimeApiContractError, match="page is invalid"):
        runtime_api._PublicCatalogPageV1.from_dict(values)


def test_response_envelope_normalizes_render_failures_and_bounds_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    envelope = CatalogResponseEnvelopeV1(_page(_request()), None)
    object.__setattr__(envelope, "page", object())
    with pytest.raises(RuntimeApiContractError):
        envelope.to_json_bytes()

    restored_internal = CatalogResponseEnvelopeV1(
        _page(_request(family=RequestFamily.SINGLE), terminal=False),
        OPAQUE_CURSOR,
    )
    object.__setattr__(
        restored_internal,
        "page",
        _page(_request(family=RequestFamily.SINGLE), terminal=False),
    )
    with pytest.raises(RuntimeApiContractError, match="response envelope is invalid"):
        restored_internal.to_json_bytes()

    tampered_page = CatalogResponseEnvelopeV1(_page(_request()), None)
    object.__setattr__(tampered_page.page, "returned_product_count", 1)
    with pytest.raises(RuntimeApiContractError, match="response envelope is invalid"):
        tampered_page.to_json_bytes()

    tampered_cursor = CatalogResponseEnvelopeV1(_page(_request()), None)
    object.__setattr__(tampered_cursor, "next_cursor", OPAQUE_CURSOR)
    with pytest.raises(RuntimeApiContractError, match="response envelope is invalid"):
        tampered_cursor.to_json_bytes()

    good = CatalogResponseEnvelopeV1(_page(_request()), None)
    monkeypatch.setattr(runtime_api, "MAX_RESPONSE_BODY_BYTES", 1)
    with pytest.raises(RuntimeApiContractError):
        good.to_json_bytes()


def test_envelope_subclasses_cannot_use_canonical_decoders() -> None:
    class RequestSubclass(CatalogRequestEnvelopeV1):
        pass

    class ResponseSubclass(CatalogResponseEnvelopeV1):
        pass

    with pytest.raises(RuntimeApiContractError):
        RequestSubclass.from_json_bytes(_body())
    with pytest.raises(RuntimeApiContractError):
        RequestSubclass(_request(), None).to_json_bytes()
    with pytest.raises(RuntimeApiContractError):
        ResponseSubclass.from_json_bytes(
            CatalogResponseEnvelopeV1(_page(_request()), None).to_json_bytes()
        )
    with pytest.raises(RuntimeApiContractError):
        ResponseSubclass(_page(_request()), None).to_json_bytes()


@pytest.mark.parametrize("limit", [True, 0, 10**9, object()])
def test_envelope_parser_limits_are_exact_positive_bounded_integers(limit: Any) -> None:
    with pytest.raises(RuntimeApiContractError):
        CatalogRequestEnvelopeV1.from_json_bytes(_body(), byte_limit=limit)
    with pytest.raises(RuntimeApiContractError):
        CatalogRequestEnvelopeV1.from_json_bytes(_body(), cursor_char_limit=limit)
    with pytest.raises(RuntimeApiContractError):
        CatalogResponseEnvelopeV1.from_json_bytes(
            CatalogResponseEnvelopeV1(_page(_request()), None).to_json_bytes(),
            byte_limit=limit,
        )


def test_catalog_success_is_pinned_once_and_preserves_raw_proxy_query(
    test_capabilities: None,
) -> None:
    request = _request()
    lease_a = _Lease(CatalogLeaseResult(_page(request, generation=GENERATION_A), None))
    lease_b = _Lease(
        CatalogLeaseResult(_page(request, generation=GENERATION_B), None), generation=GENERATION_B
    )
    active = {"lease": lease_a}

    def acquire() -> _Lease:
        selected = active["lease"]
        active["lease"] = lease_b
        return selected

    backend = _Backend(acquire)
    authorizer = _Authorizer()
    service = _service(backend=backend, authorizer=authorizer)
    raw_query = b"signature=exact%2Bbytes&shop=synthetic.myshopify.com"
    response = service.catalog(_http_request(_body(request), raw_query=raw_query))

    assert response.status == 200
    envelope = CatalogResponseEnvelopeV1.from_json_bytes(response.body)
    assert envelope.page.dataset_generation == GENERATION_A
    assert envelope.page.request == request
    assert envelope.next_cursor is None
    assert backend.calls == 1
    assert len(lease_a.calls) == 1
    assert not lease_b.calls
    assert lease_a.close_calls == 1
    assert authorizer.calls == [(raw_query, PATH)]


def test_two_concurrent_requests_each_keep_their_acquired_generation(
    test_capabilities: None,
) -> None:
    request = _request()
    first_entered = threading.Event()
    release_first = threading.Event()

    def first_fetch(_control: RequestControl) -> CatalogLeaseResult:
        first_entered.set()
        assert release_first.wait(timeout=5)
        return CatalogLeaseResult(_page(request, generation=GENERATION_A), None)

    lease_a = _Lease(first_fetch, generation=GENERATION_A)
    lease_b = _Lease(
        CatalogLeaseResult(_page(request, generation=GENERATION_B), None),
        generation=GENERATION_B,
    )

    class ActivatingBackend:
        def __init__(self) -> None:
            self.active = lease_a
            self.lock = threading.Lock()

        def acquire(
            self,
            *,
            control: RequestControl,
            request: CatalogRequestV1 | None = None,
            cursor: str | None = None,
        ) -> _Lease:
            control.checkpoint()
            with self.lock:
                return self.active

        def activate(self) -> None:
            with self.lock:
                self.active = lease_b

    backend = ActivatingBackend()
    service = _service(backend=backend)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(service.catalog, _http_request(_body(request)))
        assert first_entered.wait(timeout=5)
        backend.activate()
        second = service.catalog(_http_request(_body(request)))
        release_first.set()
        first = first_future.result(timeout=5)

    assert CatalogResponseEnvelopeV1.from_json_bytes(first.body).page.dataset_generation == (
        GENERATION_A
    )
    assert CatalogResponseEnvelopeV1.from_json_bytes(second.body).page.dataset_generation == (
        GENERATION_B
    )
    assert lease_a.close_calls == lease_b.close_calls == 1


def test_catalog_nonterminal_page_returns_only_opaque_cursor_for_reuse(
    test_capabilities: None,
) -> None:
    request = _request(family=RequestFamily.SINGLE)
    lease = _Lease(CatalogLeaseResult(_page(request, terminal=False), OPAQUE_CURSOR))
    response = _service(lease).catalog(_http_request(_body(request)))
    assert response.status == 200
    decoded = CatalogResponseEnvelopeV1.from_json_bytes(response.body)
    assert decoded.next_cursor == OPAQUE_CURSOR
    assert decoded.page.has_next_page is True


def test_non_evidence_composition_cannot_be_bypassed_by_allow_all_adapters() -> None:
    request = _request()
    lease = _Lease(CatalogLeaseResult(_page(request), None))
    backend = _Backend(lease)
    authorizer = _Authorizer()
    service = _service(backend=backend, authorizer=authorizer, gate=_Gate())
    response = service.catalog(_http_request(_body(request)))
    assert response.status == 503
    assert _error(response).code is CatalogErrorCode.UNSUPPORTED_CAPABILITY
    assert not lease.calls
    assert lease.close_calls == 0
    assert backend.calls == 0
    assert not authorizer.calls
    assert json.loads(service.readiness().body)["status"] == "not_ready"
    assert backend.calls == 0


def test_rejected_generation_is_denied_before_fetch(
    test_capabilities: None,
) -> None:
    lease = _Lease(CatalogLeaseResult(_page(_request()), None))
    gate = _Gate(catalog_outcome=CatalogBackendFailure(CatalogErrorCode.UNSUPPORTED_CAPABILITY))

    response = _service(lease, gate=gate).catalog(_http_request())

    assert response.status == 503
    assert _error(response).code is CatalogErrorCode.UNSUPPORTED_CAPABILITY
    assert len(gate.catalog_calls) == 1
    assert not lease.calls
    assert lease.close_calls == 1


def test_default_service_components_never_expose_catalog_output() -> None:
    request = _http_request()
    assert _error(
        RuntimeCatalogService(expected_shop_domain=SHOP, clock_ns=lambda: 0).catalog(request)
    ).code is (CatalogErrorCode.UNSUPPORTED_CAPABILITY)
    service = RuntimeCatalogService(
        expected_shop_domain=SHOP, authorizer=_Authorizer(), clock_ns=lambda: 0
    )
    response = service.catalog(request)
    assert response.status == 503
    assert _error(response).code is CatalogErrorCode.UNSUPPORTED_CAPABILITY


@pytest.mark.parametrize(
    ("outcome", "status", "code"),
    [
        (ProxyRequestRejected(), 401, CatalogErrorCode.INVALID_REQUEST),
        (ProxyVerifierUnavailable(), 503, CatalogErrorCode.TEMPORARILY_UNAVAILABLE),
        (RuntimeError("SECRET_VERIFY"), 503, CatalogErrorCode.TEMPORARILY_UNAVAILABLE),
        (object(), 503, CatalogErrorCode.TEMPORARILY_UNAVAILABLE),
    ],
)
def test_proxy_failures_are_fixed_and_value_free(
    outcome: Any,
    status: int,
    code: CatalogErrorCode,
    test_capabilities: None,
) -> None:
    response = _service(authorizer=_Authorizer(outcome)).catalog(_http_request())
    assert response.status == status
    assert _error(response).code is code
    assert b"SECRET" not in response.body


@pytest.mark.parametrize(
    ("failure_code", "status"),
    list(runtime_api._BACKEND_STATUS.items()),
)
def test_backend_failure_codes_map_deterministically(
    failure_code: CatalogErrorCode,
    status: int,
    test_capabilities: None,
) -> None:
    response = _service(backend=_Backend(CatalogBackendFailure(failure_code))).catalog(
        _http_request()
    )
    assert response.status == status
    assert _error(response).code is failure_code


def test_backend_acquire_and_fetch_exceptions_are_value_free(
    test_capabilities: None,
) -> None:
    acquire = _service(backend=_Backend(RuntimeError("SECRET_ACQUIRE"))).catalog(_http_request())
    assert acquire.status == 503
    assert _error(acquire).code is CatalogErrorCode.TEMPORARILY_UNAVAILABLE
    assert b"SECRET" not in acquire.body

    lease = _Lease(RuntimeError("SECRET_FETCH"))
    fetch = _service(lease).catalog(_http_request())
    assert fetch.status == 503
    assert _error(fetch).code is CatalogErrorCode.TEMPORARILY_UNAVAILABLE
    assert b"SECRET" not in fetch.body
    assert lease.close_calls == 1


def test_arbitrary_base_exceptions_propagate_and_acquired_leases_close(
    test_capabilities: None,
) -> None:
    class FatalBoundary(BaseException):
        pass

    with pytest.raises(FatalBoundary):
        _service(authorizer=_Authorizer(FatalBoundary())).catalog(_http_request())
    with pytest.raises(FatalBoundary):
        _service(backend=_Backend(FatalBoundary())).catalog(_http_request())

    for gate_or_result in ("gate", "fetch"):
        fatal = FatalBoundary()
        lease = _Lease(
            fatal if gate_or_result == "fetch" else CatalogLeaseResult(_page(_request()), None)
        )
        gate = _Gate(catalog_outcome=fatal if gate_or_result == "gate" else None)
        with pytest.raises(FatalBoundary):
            _service(lease, gate=gate).catalog(_http_request())
        assert lease.close_calls == 1


def test_hostile_exception_text_is_never_observed_or_returned(
    test_capabilities: None,
) -> None:
    class HostileError(Exception):
        def __str__(self) -> str:
            raise RuntimeError("SECRET_STR")

        def __repr__(self) -> str:
            raise RuntimeError("SECRET_REPR")

    response = _service(authorizer=_Authorizer(HostileError())).catalog(_http_request())
    expected = CatalogErrorV1.for_code(CatalogErrorCode.TEMPORARILY_UNAVAILABLE)
    assert response.body == expected.to_json_bytes()
    assert expected.field is None
    assert expected.request_context_sha256 is None


def test_gate_failures_and_non_none_result_fail_closed(test_capabilities: None) -> None:
    lease = _Lease(CatalogLeaseResult(_page(_request()), None))
    typed = _service(
        lease,
        gate=_Gate(catalog_outcome=CatalogBackendFailure(CatalogErrorCode.UNSUPPORTED_CAPABILITY)),
    ).catalog(_http_request())
    assert _error(typed).code is CatalogErrorCode.UNSUPPORTED_CAPABILITY

    unexpected = _service(lease, gate=_Gate(catalog_outcome=RuntimeError("SECRET_GATE"))).catalog(
        _http_request()
    )
    assert _error(unexpected).code is CatalogErrorCode.TEMPORARILY_UNAVAILABLE
    assert b"SECRET" not in unexpected.body

    invalid = _service(lease, gate=_Gate(catalog_outcome=True)).catalog(_http_request())
    assert invalid.status == 500
    assert _error(invalid).code is CatalogErrorCode.CONTRACT_VIOLATION


def test_invalid_cursor_from_transport_or_backend_never_reaches_another_generation(
    test_capabilities: None,
) -> None:
    invalid_transport = _service().catalog(_http_request(_body().replace(b"null", b'"bad"', 1)))
    assert invalid_transport.status == 400
    assert _error(invalid_transport).code is CatalogErrorCode.INVALID_CURSOR

    lease = _Lease(CatalogBackendFailure(CatalogErrorCode.INVALID_CURSOR))
    invalid_backend = _service(lease).catalog(_http_request(_body(cursor=OPAQUE_CURSOR)))
    assert invalid_backend.status == 400
    assert _error(invalid_backend).code is CatalogErrorCode.INVALID_CURSOR
    assert lease.calls[0][1] == OPAQUE_CURSOR


def test_incompatible_request_maps_to_fixed_error(test_capabilities: None) -> None:
    request = _request(family=RequestFamily.ALL).as_dict()
    request["q"] = "card"
    raw = json.dumps(
        {"contractVersion": 1, "cursor": None, "request": request}, separators=(",", ":")
    ).encode()
    response = _service().catalog(_http_request(raw))
    assert response.status == 422
    assert _error(response).code is CatalogErrorCode.INCOMPATIBLE_FILTER


def test_malformed_request_is_not_misclassified_as_incompatible(
    test_capabilities: None,
) -> None:
    request = _request(family=RequestFamily.SEALED, subtype="booster-box").as_dict()
    request["productFamily"] = "single"
    request["pageSize"] = "bad"
    raw = json.dumps(
        {"contractVersion": 1, "cursor": None, "request": request}, separators=(",", ":")
    ).encode()
    response = _service().catalog(_http_request(raw))
    assert response.status == 400
    assert _error(response).code is CatalogErrorCode.INVALID_REQUEST

    request["pageSize"] = 2
    request["q"] = "q" * 257
    raw = json.dumps(
        {"contractVersion": 1, "cursor": None, "request": request}, separators=(",", ":")
    ).encode()
    response = _service().catalog(_http_request(raw))
    assert response.status == 400
    assert _error(response).code is CatalogErrorCode.INVALID_REQUEST


@pytest.mark.parametrize(
    "mutation",
    [
        {"method": "GET"},
        {"path": "/other"},
        {"path": "relative"},
        {"raw_query": "query"},
        {"raw_query": b"?signature=value"},
        {"headers": []},
        {"headers": ()},
        {"body_chunks": []},
        {"body_chunks": ()},
        {"body_chunks": ("body",)},
    ],
)
def test_catalog_rejects_invalid_transport_shapes_before_backend(
    mutation: dict[str, Any],
    test_capabilities: None,
) -> None:
    original = _http_request()
    values = {
        "method": original.method,
        "path": original.path,
        "raw_query": original.raw_query,
        "headers": original.headers,
        "body_chunks": original.body_chunks,
    }
    values.update(mutation)
    backend = _Backend(_Lease(CatalogLeaseResult(_page(_request()), None)))
    response = _service(backend=backend).catalog(RuntimeHttpRequest(**values))  # type: ignore[arg-type]
    assert response.status == 400
    assert _error(response).code is CatalogErrorCode.INVALID_REQUEST
    assert backend.calls == 0


def test_catalog_rejects_non_request_and_oversized_path_query_and_chunk_count() -> None:
    service = _service()
    assert _error(service.catalog(object())).code is CatalogErrorCode.INVALID_REQUEST  # type: ignore[arg-type]

    path = replace(_http_request(), path="/" + "x" * runtime_api.MAX_PATH_BYTES)
    assert _error(service.catalog(path)).code is CatalogErrorCode.INVALID_REQUEST
    query = replace(_http_request(), raw_query=b"x" * (runtime_api.MAX_RAW_QUERY_BYTES + 1))
    assert _error(service.catalog(query)).code is CatalogErrorCode.INVALID_REQUEST
    chunks = replace(
        _http_request(),
        body_chunks=(b"x",) * (runtime_api.MAX_BODY_CHUNKS + 1),
    )
    assert _error(service.catalog(chunks)).code is CatalogErrorCode.INVALID_REQUEST


@pytest.mark.parametrize(
    "headers",
    [
        ((b"content-type",),),
        (("content-type", b"application/json"),),
        ((b"", b"application/json"),),
        ((b"bad name", b"application/json"),),
        ((b"content-type", b"application/json\r\n"),),
        ((b"content-type", b"application/json"), (b"Content-Type", b"application/json")),
        ((b"x", b"y"),),
        ((b"content-type", b"text/plain"),),
        ((b"content-type", b"application/json"), (b"content-encoding", b"gzip")),
        ((b"content-type", b"application/json"), (b"transfer-encoding", b"chunked")),
        ((b"content-type", b"application/json"), (b"content-length", b"")),
        ((b"content-type", b"application/json"), (b"content-length", b"1x")),
        ((b"content-type", b"application/json"), (b"content-length", b"9" * 20)),
    ],
)
def test_catalog_rejects_ambiguous_headers(headers: tuple[Any, ...]) -> None:
    response = _service().catalog(_http_request(headers=headers))
    assert response.status == 400
    assert _error(response).code is CatalogErrorCode.INVALID_REQUEST


def test_header_and_body_aggregate_bounds_and_content_length_are_enforced(
    test_capabilities: None,
) -> None:
    limits = RuntimeLimits(
        max_request_body_bytes=1024,
        max_header_count=2,
        max_header_name_bytes=20,
        max_header_value_bytes=32,
        max_header_bytes=40,
    )
    service = _service(limits=limits)
    cases = (
        ((b"content-type", b"application/json"), (b"x", b"y"), (b"z", b"q")),
        ((b"content-type-name-too-long", b"x"),),
        ((b"content-type", b"x" * 33),),
        ((b"content-type", b"application/json"), (b"x", b"y" * 25)),
    )
    for headers in cases:
        assert _error(service.catalog(_http_request(headers=headers))).code is (
            CatalogErrorCode.INVALID_REQUEST
        )

    wrong_length = _http_request(
        headers=((b"content-type", b"application/json"), (b"content-length", b"1"))
    )
    assert _error(service.catalog(wrong_length)).code is CatalogErrorCode.INVALID_REQUEST

    too_large_length = _http_request(
        headers=((b"content-type", b"application/json"), (b"content-length", b"1025"))
    )
    assert _error(service.catalog(too_large_length)).code is CatalogErrorCode.INVALID_REQUEST

    oversized_body = _http_request(
        headers=((b"content-type", b"application/json"),),
        chunks=(b"x" * 700, b"y" * 700),
    )
    assert _error(service.catalog(oversized_body)).code is CatalogErrorCode.INVALID_REQUEST

    default_service = _service()
    excessive_declared_length = _http_request(
        headers=(
            (b"content-type", b"application/json"),
            (b"content-length", str(runtime_api.MAX_REQUEST_BODY_BYTES + 1).encode()),
        )
    )
    assert _error(default_service.catalog(excessive_declared_length)).code is (
        CatalogErrorCode.INVALID_REQUEST
    )

    empty_body = replace(
        _http_request(),
        headers=((b"content-type", b"application/json"),),
        body_chunks=(b"",),
    )
    assert _error(default_service.catalog(empty_body)).code is CatalogErrorCode.INVALID_REQUEST


def test_valid_header_variants_and_chunked_body_reach_the_pinned_lease(
    test_capabilities: None,
) -> None:
    body = _body()
    chunks = (body[:10], b"", body[10:])
    headers = (
        (b"Content-Type", b" application/json; charset=utf-8\t"),
        (b"Content-Encoding", b"identity"),
    )
    lease = _Lease(CatalogLeaseResult(_page(_request()), None))
    response = _service(lease).catalog(_http_request(body, headers=headers, chunks=chunks))
    assert response.status == 200
    assert len(lease.calls) == 1


def test_shop_and_generation_must_be_canonical_and_bound_to_proxy_identity(
    test_capabilities: None,
) -> None:
    cases = (
        _Lease(CatalogLeaseResult(_page(_request()), None), shop="other.myshopify.com"),
        _Lease(CatalogLeaseResult(_page(_request()), None), shop=object()),
        _Lease(CatalogLeaseResult(_page(_request()), None), generation="bad"),
        _Lease(CatalogLeaseResult(_page(_request()), None), generation=object()),
    )
    for lease in cases:
        response = _service(lease).catalog(_http_request())
        assert response.status == 500
        assert _error(response).code is CatalogErrorCode.CONTRACT_VIOLATION
        assert lease.close_calls == 1

    foreign_proxy = _Authorizer(VerifiedProxyIdentity("other.myshopify.com"))
    backend = _Backend(_Lease(CatalogLeaseResult(_page(_request()), None)))
    response = _service(backend=backend, authorizer=foreign_proxy).catalog(_http_request())
    assert response.status == 401
    assert backend.calls == 0


def test_dependency_result_is_defensively_round_tripped_and_generation_bound(
    test_capabilities: None,
) -> None:
    request = _request()
    invalid_results = (
        object(),
        CatalogLeaseResult("page", None),
        CatalogLeaseResult(_page(request, generation=GENERATION_B), None),
        CatalogLeaseResult(_page(_request(page_size=1)), None),
        CatalogLeaseResult(_page(request), OPAQUE_CURSOR),
    )
    for result in invalid_results:
        response = _service(_Lease(result)).catalog(_http_request(_body(request)))
        assert response.status == 500
        assert _error(response).code is CatalogErrorCode.CONTRACT_VIOLATION

    corrupted_page = _page(request)
    object.__setattr__(corrupted_page, "request", object())
    response = _service(_Lease(CatalogLeaseResult(corrupted_page, None))).catalog(
        _http_request(_body(request))
    )
    assert response.status == 500
    assert _error(response).code is CatalogErrorCode.CONTRACT_VIOLATION


def test_response_byte_bound_fails_closed(test_capabilities: None) -> None:
    limits = RuntimeLimits(max_response_body_bytes=512)
    request = _request(family=RequestFamily.SINGLE)
    lease = _Lease(CatalogLeaseResult(_page(request, terminal=False), OPAQUE_CURSOR))
    response = _service(lease, limits=limits).catalog(_http_request(_body(request)))
    assert response.status == 500
    assert _error(response).code is CatalogErrorCode.CONTRACT_VIOLATION


def test_emitted_cursor_must_fit_the_next_canonical_request_at_exact_boundary(
    test_capabilities: None,
) -> None:
    request = _request(family=RequestFamily.SINGLE)
    cursor = "a" * 150 + "." + "b" * 150
    next_request_size = len(CatalogRequestEnvelopeV1(request, cursor).to_json_bytes())
    initial_request = _body(request)
    assert len(initial_request) < next_request_size

    page = _page(request, terminal=False)
    exact = _service(
        _Lease(CatalogLeaseResult(page, cursor)),
        limits=RuntimeLimits(max_request_body_bytes=next_request_size),
    ).catalog(_http_request(initial_request))
    assert exact.status == 200

    overflow = _service(
        _Lease(CatalogLeaseResult(page, cursor)),
        limits=RuntimeLimits(max_request_body_bytes=next_request_size - 1),
    ).catalog(_http_request(initial_request))
    assert overflow.status == 500
    assert _error(overflow).code is CatalogErrorCode.CONTRACT_VIOLATION


def test_response_render_failure_is_a_contract_violation(
    monkeypatch: pytest.MonkeyPatch,
    test_capabilities: None,
) -> None:
    def fail_render(_self: CatalogResponseEnvelopeV1) -> bytes:
        raise RuntimeError("SECRET_RENDER")

    monkeypatch.setattr(CatalogResponseEnvelopeV1, "to_json_bytes", fail_render)
    response = _service().catalog(_http_request())
    assert response.status == 500
    assert _error(response).code is CatalogErrorCode.CONTRACT_VIOLATION
    assert b"SECRET" not in response.body


def test_timeout_and_clock_failures_are_fixed_and_value_free(test_capabilities: None) -> None:
    for clock in (lambda: -1, lambda: "zero"):
        response = _service(clock=clock).catalog(_http_request())
        assert response.status == 503
        assert _error(response).code is CatalogErrorCode.TEMPORARILY_UNAVAILABLE

    def broken_clock() -> int:
        raise RuntimeError("SECRET_CLOCK")

    response = _service(clock=broken_clock).catalog(_http_request())
    assert response.status == 503
    assert b"SECRET" not in response.body

    ticks = iter((0, 0, 0, 0, 3_000_000_000))
    response = _service(clock=lambda: next(ticks)).catalog(_http_request())
    assert response.status == 503
    assert _error(response).code is CatalogErrorCode.TEMPORARILY_UNAVAILABLE


def test_cancellation_wins_before_and_during_dependency_failures(test_capabilities: None) -> None:
    token = RequestCancellation()
    token.cancel()
    with pytest.raises(RequestCancelled):
        _service(clock=lambda: (_ for _ in ()).throw(RuntimeError("clock"))).catalog(
            _http_request(), cancellation=token
        )

    for phase in ("verify", "acquire", "fetch"):
        token = RequestCancellation()

        class CancellingAuthorizer(_Authorizer):
            def verify(
                self,
                _phase: str = phase,
                _token: RequestCancellation = token,
                **kwargs: Any,
            ) -> VerifiedProxyIdentity:
                if _phase == "verify":
                    _token.cancel()
                    raise RuntimeError("SECRET_VERIFY")
                return super().verify(**kwargs)

        class CancellingBackend(_Backend):
            def acquire(
                self,
                _phase: str = phase,
                _token: RequestCancellation = token,
                **kwargs: Any,
            ) -> _Lease:
                if _phase == "acquire":
                    _token.cancel()
                    raise RuntimeError("SECRET_ACQUIRE")
                return super().acquire(**kwargs)

        def fetch(
            _control: RequestControl,
            _phase: str = phase,
            _token: RequestCancellation = token,
        ) -> CatalogLeaseResult:
            if _phase == "fetch":
                _token.cancel()
                raise RuntimeError("SECRET_FETCH")
            return CatalogLeaseResult(_page(_request()), None)

        service = _service(
            _Lease(fetch),
            backend=CancellingBackend(_Lease(fetch)),
            authorizer=CancellingAuthorizer(),
        )
        with pytest.raises(RequestCancelled):
            service.catalog(_http_request(), cancellation=token)


def test_lease_returned_after_acquire_cancellation_is_released(
    test_capabilities: None,
) -> None:
    token = RequestCancellation()
    lease = _Lease(CatalogLeaseResult(_page(_request()), None))

    def acquire_then_cancel() -> _Lease:
        token.cancel()
        return lease

    with pytest.raises(RequestCancelled):
        _service(backend=_Backend(acquire_then_cancel)).catalog(_http_request(), cancellation=token)
    assert lease.close_calls == 1


def test_lease_returned_after_acquire_deadline_is_released(
    test_capabilities: None,
) -> None:
    now = {"value": 0}
    lease = _Lease(CatalogLeaseResult(_page(_request()), None))

    def acquire_then_expire() -> _Lease:
        now["value"] = 3_000_000_000
        return lease

    response = _service(backend=_Backend(acquire_then_expire), clock=lambda: now["value"]).catalog(
        _http_request()
    )
    assert response.status == 503
    assert _error(response).code is CatalogErrorCode.TEMPORARILY_UNAVAILABLE
    assert lease.close_calls == 1


def test_invalid_cancellation_object_is_a_fixed_temporary_failure() -> None:
    response = _service().catalog(_http_request(), cancellation=object())  # type: ignore[arg-type]
    assert response.status == 503
    assert _error(response).code is CatalogErrorCode.TEMPORARILY_UNAVAILABLE


def test_liveness_is_process_only_and_never_touches_dependencies() -> None:
    backend = _Backend(RuntimeError("must not run"))
    response = _service(backend=backend).liveness()
    assert response.status == 200
    assert json.loads(response.body) == {"contractVersion": 1, "status": "live"}
    assert backend.calls == 0
    assert response.headers == runtime_api._JSON_HEADERS


def test_readiness_is_false_under_frozen_contract_without_backend_access() -> None:
    backend = _Backend(RuntimeError("must not run"))
    response = _service(backend=backend).readiness()
    assert response.status == 503
    assert json.loads(response.body)["status"] == "not_ready"
    assert backend.calls == 0


def test_unavailable_backend_remains_not_ready_after_composition_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _Backend(RuntimeError("unavailable"))
    monkeypatch.setattr(runtime_api, "_runtime_composition_is_evidence_bound", lambda *_: True)

    response = _service(backend=backend).readiness()

    assert response.status == 503
    assert json.loads(response.body)["status"] == "not_ready"
    assert backend.calls == 1


def test_readiness_uses_one_lease_and_releases_it(test_capabilities: None) -> None:
    lease = _Lease(None)
    backend = _Backend(lease)
    gate = _Gate(ready_outcome=True)
    response = _service(backend=backend, gate=gate).readiness()
    assert response.status == 200
    assert json.loads(response.body) == {"contractVersion": 1, "status": "ready"}
    assert backend.calls == 1
    assert gate.ready_calls == [lease]
    assert lease.close_calls == 1


@pytest.mark.parametrize("ready", [False, None, 1])
def test_readiness_requires_exact_true_and_releases_lease(
    ready: Any,
    test_capabilities: None,
) -> None:
    lease = _Lease(None)
    response = _service(lease, gate=_Gate(ready_outcome=ready)).readiness()
    assert response.status == 503
    assert json.loads(response.body)["status"] == "not_ready"
    assert lease.close_calls == 1


def test_readiness_normalizes_backend_gate_identity_and_clock_failures(
    test_capabilities: None,
) -> None:
    cases = (
        _service(backend=_Backend(RuntimeError("SECRET_BACKEND"))),
        _service(_Lease(None, generation="bad")),
        _service(_Lease(None, shop="other.myshopify.com")),
        _service(_Lease(None), gate=_Gate(ready_outcome=RuntimeError("SECRET_GATE"))),
        _service(clock=lambda: -1),
    )
    for service in cases:
        response = service.readiness()
        assert response.status == 503
        assert json.loads(response.body)["status"] == "not_ready"
        assert b"SECRET" not in response.body

    lease = _Lease(None)
    response = _service(
        lease,
        gate=_Gate(ready_outcome=CatalogBackendFailure(CatalogErrorCode.TEMPORARILY_UNAVAILABLE)),
    ).readiness()
    assert response.status == 503
    assert lease.close_calls == 1


def test_readiness_cancellation_wins_and_invalid_token_fails_closed(
    test_capabilities: None,
) -> None:
    token = RequestCancellation()
    token.cancel()
    with pytest.raises(RequestCancelled):
        _service().readiness(cancellation=token)
    response = _service().readiness(cancellation=object())  # type: ignore[arg-type]
    assert response.status == 503
    assert json.loads(response.body)["status"] == "not_ready"


def test_readiness_gate_and_release_cancellation_are_propagated(
    test_capabilities: None,
) -> None:
    token = RequestCancellation()
    lease = _Lease(None)

    class CancellingGate(_Gate):
        def ready(self, lease: Any, *, control: RequestControl) -> bool:
            del lease, control
            token.cancel()
            return False

    with pytest.raises(RequestCancelled):
        _service(lease, gate=CancellingGate()).readiness(cancellation=token)
    assert lease.close_calls == 1

    close_token = RequestCancellation()

    class CancellingCloseLease(_Lease):
        def close(self) -> None:
            self.close_calls += 1
            close_token.cancel()

    close_lease = CancellingCloseLease(None)
    with pytest.raises(RequestCancelled):
        _service(close_lease).readiness(cancellation=close_token)
    assert close_lease.close_calls == 1


def test_lease_close_failure_is_normalized_and_cancellation_is_preserved(
    test_capabilities: None,
) -> None:
    class BrokenCloseLease(_Lease):
        def close(self) -> None:
            self.close_calls += 1
            raise RuntimeError("SECRET_CLOSE")

    lease = BrokenCloseLease(CatalogLeaseResult(_page(_request()), None))
    response = _service(lease).catalog(_http_request())
    assert response.status == 503
    assert _error(response).code is CatalogErrorCode.TEMPORARILY_UNAVAILABLE
    assert b"SECRET" not in response.body

    token = RequestCancellation()

    def cancel_then_fail(_control: RequestControl) -> CatalogLeaseResult:
        token.cancel()
        raise RuntimeError("fetch")

    lease = BrokenCloseLease(cancel_then_fail)
    with pytest.raises(RequestCancelled):
        _service(lease).catalog(_http_request(), cancellation=token)
    assert lease.close_calls == 1


def test_lease_close_must_return_none(test_capabilities: None) -> None:
    class InvalidCloseLease(_Lease):
        def close(self) -> bool:
            self.close_calls += 1
            return True

    lease = InvalidCloseLease(CatalogLeaseResult(_page(_request()), None))
    response = _service(lease).catalog(_http_request())
    assert response.status == 503
    assert _error(response).code is CatalogErrorCode.TEMPORARILY_UNAVAILABLE


def test_forged_backend_error_code_cannot_escape_normalization() -> None:
    error = CatalogBackendFailure(CatalogErrorCode.DATASET_UNAVAILABLE)
    object.__setattr__(error, "code", object())
    response = runtime_api._backend_error_response(error)
    assert response.status == 503
    assert _error(response).code is CatalogErrorCode.TEMPORARILY_UNAVAILABLE

    class EvilFailure(CatalogBackendFailure):
        @property
        def code(self) -> Any:
            raise RuntimeError("SECRET_CODE")

        @code.setter
        def code(self, _value: Any) -> None:
            pass

    response = runtime_api._backend_error_response(
        EvilFailure(CatalogErrorCode.DATASET_UNAVAILABLE)
    )
    assert response.status == 503
    assert b"SECRET" not in response.body


def test_runtime_service_constructor_is_strict() -> None:
    with pytest.raises(RuntimeApiContractError):
        RuntimeCatalogService(
            expected_shop_domain=SHOP,
            limits=object(),  # type: ignore[arg-type]
        )
    with pytest.raises(RuntimeApiContractError):
        RuntimeCatalogService(expected_shop_domain=SHOP, endpoint_path="relative")
    with pytest.raises(RuntimeApiContractError):
        RuntimeCatalogService(
            expected_shop_domain=SHOP,
            clock_ns=object(),  # type: ignore[arg-type]
        )
    with pytest.raises(RuntimeApiContractError):
        RuntimeCatalogService(expected_shop_domain="other.example.com")


def test_path_validation_rejects_query_fragment_control_surrogate_and_overflow() -> None:
    for path in ("/a?b", "/a#b", "/a\n", "/\ud800"):
        with pytest.raises(RuntimeApiContractError):
            RuntimeCatalogService(expected_shop_domain=SHOP, endpoint_path=path)
    with pytest.raises(RuntimeApiContractError):
        RuntimeCatalogService(
            expected_shop_domain=SHOP,
            endpoint_path="/" + "x" * 20,
            limits=RuntimeLimits(max_path_bytes=10),
        )


def test_private_normalizers_are_total_and_value_free(
    monkeypatch: pytest.MonkeyPatch,
    test_capabilities: None,
) -> None:
    with pytest.raises(RuntimeApiContractError):
        runtime_api._canonical_json_bytes(object())
    response = runtime_api._normalized_error_response(RuntimeError("SECRET_UNKNOWN"))
    assert response.status == 503
    assert b"SECRET" not in response.body

    assert runtime_api._raw_request_is_incompatible([]) is False
    assert runtime_api._raw_request_is_incompatible({}) is False
    request = _request().as_dict()
    request["filters"] = []
    assert runtime_api._raw_request_is_incompatible(request) is False
    request["filters"] = {"unknown": None}
    assert runtime_api._raw_request_is_incompatible(request) is False

    original = runtime_api.CatalogResponseEnvelopeV1

    def reject_response(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeApiContractError("fixed")

    monkeypatch.setattr(runtime_api, "CatalogResponseEnvelopeV1", reject_response)
    with pytest.raises(runtime_api._OutputContractFailure):
        runtime_api._validated_result(
            CatalogLeaseResult(_page(_request()), None),
            request=_request(),
            dataset_generation=GENERATION_A,
            cursor_char_limit=runtime_api.MAX_CURSOR_CHARS,
            request_body_byte_limit=runtime_api.MAX_REQUEST_BODY_BYTES,
        )
    monkeypatch.setattr(runtime_api, "CatalogResponseEnvelopeV1", original)
