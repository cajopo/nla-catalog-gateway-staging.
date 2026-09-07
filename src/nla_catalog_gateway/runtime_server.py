"""Thin ASGI transport for the evidence-bound catalog runtime.

The adapter owns no catalog or authorization logic.  It exposes only the two
health probes and one explicitly configured Shopify App Proxy path, preserves
the request bytes handed to it by the ASGI server, and fails closed with fixed
public errors.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from typing import Any

from nla_catalog_gateway.runtime_api import (
    RequestCancellation,
    RequestCancelled,
    RuntimeCatalogService,
    RuntimeHttpRequest,
    RuntimeHttpResponse,
    RuntimeLimits,
)
from nla_catalog_gateway.runtime_contract import CatalogErrorCode, CatalogErrorV1

AsgiReceive = Callable[[], Awaitable[Mapping[str, Any]]]
AsgiSend = Callable[[Mapping[str, Any]], Awaitable[None]]
AsgiScope = Mapping[str, Any]

LIVENESS_PATH = "/livez"
READINESS_PATH = "/readyz"

_ERROR_HEADERS = (
    ("content-type", "application/json; charset=utf-8"),
    ("cache-control", "no-store"),
    ("x-content-type-options", "nosniff"),
)
_HEADER_NAME_BYTES = frozenset(
    b"!#$%&'*+-.^_`|~0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
)
_MAX_RESPONSE_HEADER_COUNT = 64
_MAX_RESPONSE_HEADER_NAME_BYTES = 256
_MAX_RESPONSE_HEADER_VALUE_BYTES = 8 * 1024
_MAX_RESPONSE_HEADER_BYTES = 32 * 1024


class RuntimeServerConfigurationError(ValueError):
    """A fixed, value-free ASGI adapter configuration failure."""


class _InvalidAsgiRequest(Exception):
    pass


class _RequestTooLarge(Exception):
    pass


class _RequestTimedOut(Exception):
    pass


class _Disconnected(Exception):
    pass


class RuntimeAsgiApp:
    """ASGI 3 callable around one injected :class:`RuntimeCatalogService`."""

    __slots__ = ("_app_proxy_path", "_limits", "_service")

    def __init__(
        self,
        service: RuntimeCatalogService,
        *,
        app_proxy_path: str,
        limits: RuntimeLimits | None = None,
    ) -> None:
        if not all(
            callable(getattr(service, name, None)) for name in ("catalog", "liveness", "readiness")
        ):
            raise RuntimeServerConfigurationError("runtime service is invalid")
        if limits is None:
            limits = RuntimeLimits()
        if type(limits) is not RuntimeLimits:
            raise RuntimeServerConfigurationError("runtime limits are invalid")
        _validate_configured_path(app_proxy_path, limits)
        self._service = service
        self._app_proxy_path = app_proxy_path
        self._limits = limits

    async def __call__(self, scope: AsgiScope, receive: AsgiReceive, send: AsgiSend) -> None:
        """Handle one HTTP request without adding a second public catalog route."""

        if not callable(receive) or not callable(send):
            raise RuntimeServerConfigurationError("ASGI callables are invalid")
        try:
            method, path, raw_query, headers = _request_metadata(scope, self._limits)
            route = self._route(method, path, raw_query)
            cancellation = RequestCancellation()
            body_chunks = await _receive_body_with_timeout(
                receive,
                cancellation,
                self._limits,
            )
            if route != "catalog" and any(body_chunks):
                raise _InvalidAsgiRequest
        except _Disconnected:
            return
        except _RequestTimedOut:
            await _send_response(
                send,
                _fixed_error(503, CatalogErrorCode.TEMPORARILY_UNAVAILABLE),
                self._limits,
            )
            return
        except _RequestTooLarge:
            await _send_response(
                send,
                _fixed_error(413, CatalogErrorCode.INVALID_REQUEST),
                self._limits,
            )
            return
        except Exception:
            await _send_response(
                send,
                _fixed_error(400, CatalogErrorCode.INVALID_REQUEST),
                self._limits,
            )
            return

        if route == "catalog":
            request = RuntimeHttpRequest(
                method=method,
                path=path,
                raw_query=raw_query,
                headers=headers,
                body_chunks=body_chunks,
            )

            def call() -> RuntimeHttpResponse:
                return self._service.catalog(request, cancellation=cancellation)

        elif route == "liveness":
            call = self._service.liveness
        else:

            def call() -> RuntimeHttpResponse:
                return self._service.readiness(cancellation=cancellation)

        response = await _run_service(call, receive, cancellation)
        if response is None:
            return
        await _send_response(send, response, self._limits)

    def _route(self, method: str, path: str, raw_query: bytes) -> str:
        if method == "GET" and path == LIVENESS_PATH and not raw_query:
            return "liveness"
        if method == "GET" and path == READINESS_PATH and not raw_query:
            return "readiness"
        if method == "POST" and path == self._app_proxy_path:
            return "catalog"
        raise _InvalidAsgiRequest


def create_runtime_app(
    service: RuntimeCatalogService,
    *,
    app_proxy_path: str,
    limits: RuntimeLimits | None = None,
) -> RuntimeAsgiApp:
    """Create the sole public ASGI adapter for an injected runtime service."""

    return RuntimeAsgiApp(service, app_proxy_path=app_proxy_path, limits=limits)


def _validate_configured_path(path: Any, limits: RuntimeLimits) -> None:
    if (
        type(path) is not str
        or path in {LIVENESS_PATH, READINESS_PATH}
        or not path.startswith("/")
        or "?" in path
        or "#" in path
    ):
        raise RuntimeServerConfigurationError("App Proxy path is invalid")
    try:
        encoded = path.encode("utf-8")
    except UnicodeEncodeError:
        raise RuntimeServerConfigurationError("App Proxy path is invalid") from None
    if len(encoded) > limits.max_path_bytes or any(byte < 32 or byte == 127 for byte in encoded):
        raise RuntimeServerConfigurationError("App Proxy path is invalid")


def _request_metadata(
    scope: AsgiScope, limits: RuntimeLimits
) -> tuple[str, str, bytes, tuple[tuple[bytes, bytes], ...]]:
    if type(scope) is not dict or scope.get("type") != "http":
        raise _InvalidAsgiRequest
    method = scope.get("method")
    path = scope.get("path")
    raw_query = scope.get("query_string", b"")
    if type(method) is not str or type(path) is not str or type(raw_query) is not bytes:
        raise _InvalidAsgiRequest
    try:
        encoded_path = path.encode("utf-8")
    except UnicodeEncodeError:
        raise _InvalidAsgiRequest from None
    if not encoded_path:
        raise _InvalidAsgiRequest
    if len(encoded_path) > limits.max_path_bytes or len(raw_query) > limits.max_raw_query_bytes:
        raise _RequestTooLarge
    raw_path = scope.get("raw_path")
    if type(raw_path) is not bytes or raw_path != encoded_path:
        raise _InvalidAsgiRequest
    raw_headers = scope.get("headers")
    if type(raw_headers) not in {list, tuple}:
        raise _InvalidAsgiRequest
    if len(raw_headers) > limits.max_header_count:
        raise _RequestTooLarge
    headers: list[tuple[bytes, bytes]] = []
    total = 0
    for entry in raw_headers:
        if type(entry) not in {list, tuple} or len(entry) != 2:
            raise _InvalidAsgiRequest
        name, value = entry
        if type(name) is not bytes or type(value) is not bytes:
            raise _InvalidAsgiRequest
        total += len(name) + len(value)
        if (
            len(name) > limits.max_header_name_bytes
            or len(value) > limits.max_header_value_bytes
            or total > limits.max_header_bytes
        ):
            raise _RequestTooLarge
        if name.lower() == b"content-length":
            declared_length = value.strip(b" \t")
            if declared_length.isdigit() and (
                len(declared_length) > 19 or int(declared_length) > limits.max_request_body_bytes
            ):
                raise _RequestTooLarge
        headers.append((name, value))
    return method, path, raw_query, tuple(headers)


async def _receive_body(
    receive: AsgiReceive,
    cancellation: RequestCancellation,
    limits: RuntimeLimits,
) -> tuple[bytes, ...]:
    chunks: list[bytes] = []
    total = 0
    while True:
        try:
            message = await receive()
        except asyncio.CancelledError:
            cancellation.cancel()
            raise
        except BaseException:
            raise _InvalidAsgiRequest from None
        if type(message) is not dict:
            raise _InvalidAsgiRequest
        message_type = message.get("type")
        if message_type == "http.disconnect":
            cancellation.cancel()
            raise _Disconnected
        if message_type != "http.request":
            raise _InvalidAsgiRequest
        body = message.get("body", b"")
        more_body = message.get("more_body", False)
        if type(body) is not bytes or type(more_body) is not bool:
            raise _InvalidAsgiRequest
        next_count = len(chunks) + 1
        next_total = total + len(body)
        if next_count > limits.max_body_chunks or next_total > limits.max_request_body_bytes:
            cancellation.cancel()
            raise _RequestTooLarge
        chunks.append(body)
        total = next_total
        if not more_body:
            return tuple(chunks)


async def _receive_body_with_timeout(
    receive: AsgiReceive,
    cancellation: RequestCancellation,
    limits: RuntimeLimits,
) -> tuple[bytes, ...]:
    try:
        async with asyncio.timeout(limits.request_timeout_ms / 1_000):
            return await _receive_body(receive, cancellation, limits)
    except TimeoutError:
        cancellation.cancel()
        raise _RequestTimedOut from None


async def _run_service(
    call: Callable[[], RuntimeHttpResponse],
    receive: AsgiReceive,
    cancellation: RequestCancellation,
) -> RuntimeHttpResponse | None:
    service_task = asyncio.create_task(asyncio.to_thread(call))
    disconnect_task = asyncio.create_task(_wait_for_disconnect(receive))
    try:
        done, _ = await asyncio.wait(
            (service_task, disconnect_task), return_when=asyncio.FIRST_COMPLETED
        )
        if disconnect_task in done:
            cancellation.cancel()
            await _cancel_and_drain(service_task)
            connection_state = disconnect_task.result()
            if connection_state == "invalid":
                return _fixed_error(400, CatalogErrorCode.INVALID_REQUEST)
            return None
        disconnect_task.cancel()
        with suppress(asyncio.CancelledError):
            await disconnect_task
        try:
            return service_task.result()
        except RequestCancelled:
            return _fixed_error(503, CatalogErrorCode.TEMPORARILY_UNAVAILABLE)
        except BaseException:
            return _fixed_error(503, CatalogErrorCode.TEMPORARILY_UNAVAILABLE)
    except asyncio.CancelledError:
        cancellation.cancel()
        await _cancel_and_drain(service_task)
        await _cancel_and_drain(disconnect_task)
        raise


async def _cancel_and_drain(task: asyncio.Task[Any]) -> None:
    """Retrieve a completed failure without waiting for a cancelled worker thread."""

    task.cancel()
    with suppress(BaseException):
        await task


async def _wait_for_disconnect(receive: AsgiReceive) -> str:
    try:
        message = await receive()
    except asyncio.CancelledError:
        raise
    except BaseException:
        return "closed"
    if type(message) is dict and message.get("type") == "http.disconnect":
        return "disconnected"
    return "invalid"


def _fixed_error(status: int, code: CatalogErrorCode) -> RuntimeHttpResponse:
    return RuntimeHttpResponse(
        status=status,
        headers=_ERROR_HEADERS,
        body=CatalogErrorV1.for_code(code).to_json_bytes(),
    )


async def _send_response(
    send: AsgiSend, response: RuntimeHttpResponse, limits: RuntimeLimits
) -> None:
    try:
        status, headers, body = _validated_response(response, limits)
    except Exception:
        status, headers, body = _validated_response(
            _fixed_error(503, CatalogErrorCode.TEMPORARILY_UNAVAILABLE), limits
        )
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body, "more_body": False})


def _validated_response(
    response: RuntimeHttpResponse, limits: RuntimeLimits
) -> tuple[int, list[tuple[bytes, bytes]], bytes]:
    if (
        type(response) is not RuntimeHttpResponse
        or type(response.status) is not int
        or not 200 <= response.status <= 599
        or type(response.headers) is not tuple
        or len(response.headers) > _MAX_RESPONSE_HEADER_COUNT
        or type(response.body) is not bytes
        or len(response.body) > limits.max_response_body_bytes
    ):
        raise _InvalidAsgiRequest
    encoded_headers: list[tuple[bytes, bytes]] = []
    total = 0
    for entry in response.headers:
        if type(entry) is not tuple or len(entry) != 2:
            raise _InvalidAsgiRequest
        name, value = entry
        if type(name) is not str or type(value) is not str:
            raise _InvalidAsgiRequest
        try:
            raw_name = name.encode("ascii")
            raw_value = value.encode("latin-1")
        except UnicodeEncodeError:
            raise _InvalidAsgiRequest from None
        total += len(raw_name) + len(raw_value)
        if (
            not raw_name
            or raw_name != raw_name.lower()
            or raw_name == b"content-length"
            or len(raw_name) > _MAX_RESPONSE_HEADER_NAME_BYTES
            or len(raw_value) > _MAX_RESPONSE_HEADER_VALUE_BYTES
            or total > _MAX_RESPONSE_HEADER_BYTES
            or any(byte not in _HEADER_NAME_BYTES for byte in raw_name)
            or any((byte < 32 and byte != 9) or byte == 127 for byte in raw_value)
        ):
            raise _InvalidAsgiRequest
        encoded_headers.append((raw_name, raw_value))
    return response.status, encoded_headers, response.body


__all__ = [
    "LIVENESS_PATH",
    "READINESS_PATH",
    "RuntimeAsgiApp",
    "RuntimeServerConfigurationError",
    "create_runtime_app",
]
