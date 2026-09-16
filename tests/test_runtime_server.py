from __future__ import annotations

import asyncio
import gc
import json
import threading
import time
from collections.abc import Iterable
from typing import Any

import pytest

from nla_catalog_gateway import runtime_server
from nla_catalog_gateway.runtime_api import (
    RequestCancelled,
    RuntimeHttpRequest,
    RuntimeHttpResponse,
    RuntimeLimits,
)
from nla_catalog_gateway.runtime_server import (
    RuntimeServerConfigurationError,
    create_runtime_app,
)

APP_PROXY_PATH = "/apps/nla/catalog"
HEADERS = (
    ("content-type", "application/json; charset=utf-8"),
    ("cache-control", "no-store"),
)


class _Service:
    def __init__(self, response: Any = None) -> None:
        self.response = response
        self.calls: list[str] = []
        self.catalog_request: RuntimeHttpRequest | None = None
        self.cancellation: Any = None
        self.thread_ids: list[int] = []

    def _record(self, name: str) -> None:
        self.calls.append(name)
        self.thread_ids.append(threading.get_ident())

    def liveness(self) -> RuntimeHttpResponse:
        self._record("liveness")
        return self._outcome(b'{"status":"live"}')

    def readiness(self, *, cancellation: Any) -> RuntimeHttpResponse:
        self._record("readiness")
        self.cancellation = cancellation
        return self._outcome(b'{"status":"ready"}')

    def catalog(self, request: RuntimeHttpRequest, *, cancellation: Any) -> RuntimeHttpResponse:
        self._record("catalog")
        self.catalog_request = request
        self.cancellation = cancellation
        return self._outcome(b'{"catalog":true}')

    def _outcome(self, default_body: bytes) -> RuntimeHttpResponse:
        if isinstance(self.response, BaseException):
            raise self.response
        if self.response is not None:
            return self.response
        return RuntimeHttpResponse(200, HEADERS, default_body)


def _scope(
    *,
    method: str = "POST",
    path: str = APP_PROXY_PATH,
    query: bytes = b"",
    headers: Iterable[Any] = (),
) -> dict[str, Any]:
    return {
        "type": "http",
        "method": method,
        "path": path,
        "raw_path": path.encode(),
        "query_string": query,
        "headers": list(headers),
    }


async def _invoke_scope(
    app: Any,
    scope: Any,
    *,
    messages: Iterable[Any] = ({"type": "http.request"},),
) -> list[dict[str, Any]]:
    queue: asyncio.Queue[Any] = asyncio.Queue()
    for message in messages:
        queue.put_nowait(message)
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return await queue.get()

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    await asyncio.wait_for(app(scope, receive, send), 2)
    return sent


def _invoke(
    app: Any,
    *,
    method: str = "POST",
    path: str = APP_PROXY_PATH,
    query: bytes = b"",
    headers: Iterable[Any] = (),
    messages: Iterable[Any] = ({"type": "http.request"},),
) -> list[dict[str, Any]]:
    return asyncio.run(
        _invoke_scope(
            app,
            _scope(method=method, path=path, query=query, headers=headers),
            messages=messages,
        )
    )


def _status(sent: list[dict[str, Any]]) -> int:
    return sent[0]["status"]


def _body(sent: list[dict[str, Any]]) -> bytes:
    return sent[1]["body"]


def test_health_routes_forward_exact_runtime_responses_from_worker_thread() -> None:
    main_thread = threading.get_ident()
    service = _Service()
    app = create_runtime_app(service, app_proxy_path=APP_PROXY_PATH)  # type: ignore[arg-type]

    live = _invoke(app, method="GET", path="/livez")
    ready = _invoke(
        app,
        method="GET",
        path="/readyz",
        messages=(
            {"type": "http.request", "body": b"", "more_body": True},
            {"type": "http.request", "body": b"", "more_body": False},
        ),
    )

    assert service.calls == ["liveness", "readiness"]
    assert all(thread_id != main_thread for thread_id in service.thread_ids)
    assert live == [
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"cache-control", b"no-store"),
            ],
        },
        {"type": "http.response.body", "body": b'{"status":"live"}', "more_body": False},
    ]
    assert _status(ready) == 200
    assert json.loads(_body(ready)) == {"status": "ready"}
    assert service.cancellation.cancelled is False


def test_catalog_forwards_raw_query_duplicate_headers_and_stream_chunks_exactly() -> None:
    raw_query = b"shop=nla.myshopify.com&path_prefix=%2Fapps%2Fnla&signature=SIGNED_BYTES"
    raw_headers = [
        [b"content-type", b"application/json"],
        [b"x-duplicate", b"first"],
        [b"x-duplicate", b"second"],
    ]
    chunks = (b'{"contractVersion":', b"1", b"}")
    response = RuntimeHttpResponse(
        207,
        (("content-type", "application/json"), ("x-result", "caf\xe9\tok")),
        b"exact-response-bytes",
    )
    service = _Service(response)
    app = create_runtime_app(service, app_proxy_path=APP_PROXY_PATH)  # type: ignore[arg-type]

    sent = _invoke(
        app,
        query=raw_query,
        headers=raw_headers,
        messages=tuple(
            {
                "type": "http.request",
                "body": chunk,
                "more_body": index < len(chunks) - 1,
            }
            for index, chunk in enumerate(chunks)
        ),
    )

    assert service.calls == ["catalog"]
    assert service.catalog_request == RuntimeHttpRequest(
        method="POST",
        path=APP_PROXY_PATH,
        raw_query=raw_query,
        headers=tuple(tuple(entry) for entry in raw_headers),
        body_chunks=chunks,
    )
    assert service.cancellation.cancelled is False
    assert sent == [
        {
            "type": "http.response.start",
            "status": 207,
            "headers": [
                (b"content-type", b"application/json"),
                (b"x-result", b"caf\xe9\tok"),
            ],
        },
        {
            "type": "http.response.body",
            "body": b"exact-response-bytes",
            "more_body": False,
        },
    ]


@pytest.mark.parametrize(
    ("method", "path", "query"),
    [
        ("POST", "/catalog", b""),
        ("GET", APP_PROXY_PATH, b""),
        ("POST", "/livez", b""),
        ("GET", "/livez", b"secret=must-not-route"),
        ("GET", "/readyz", b"secret=must-not-route"),
    ],
)
def test_no_unconfigured_wrong_method_or_queried_health_route_reaches_service(
    method: str, path: str, query: bytes
) -> None:
    service = _Service()
    app = create_runtime_app(service, app_proxy_path=APP_PROXY_PATH)  # type: ignore[arg-type]

    sent = _invoke(app, method=method, path=path, query=query)

    assert service.calls == []
    assert _status(sent) == 400
    assert b"secret" not in _body(sent)


def test_health_request_with_a_body_fails_before_service_call() -> None:
    service = _Service()
    app = create_runtime_app(service, app_proxy_path=APP_PROXY_PATH)  # type: ignore[arg-type]

    sent = _invoke(
        app,
        method="GET",
        path="/livez",
        messages=({"type": "http.request", "body": b"not-empty"},),
    )

    assert service.calls == []
    assert _status(sent) == 400
    assert b"not-empty" not in _body(sent)


@pytest.mark.parametrize(
    ("limits", "scope", "messages"),
    [
        (
            RuntimeLimits(max_raw_query_bytes=4),
            _scope(query=b"12345"),
            ({"type": "http.request"},),
        ),
        (
            RuntimeLimits(max_path_bytes=len(APP_PROXY_PATH.encode())),
            _scope(path=APP_PROXY_PATH + "x"),
            ({"type": "http.request"},),
        ),
        (
            RuntimeLimits(max_header_count=2),
            _scope(headers=((b"a", b"1"), (b"b", b"2"), (b"c", b"3"))),
            ({"type": "http.request"},),
        ),
        (
            RuntimeLimits(max_header_name_bytes=4),
            _scope(headers=((b"abcde", b"1"),)),
            ({"type": "http.request"},),
        ),
        (
            RuntimeLimits(max_header_value_bytes=4),
            _scope(headers=((b"a", b"12345"),)),
            ({"type": "http.request"},),
        ),
        (
            RuntimeLimits(max_header_bytes=6),
            _scope(headers=((b"abc", b"12"), (b"d", b"3"))),
            ({"type": "http.request"},),
        ),
        (
            RuntimeLimits(max_request_body_bytes=4),
            _scope(headers=((b"content-length", b"5"),)),
            ({"type": "http.request", "body": b"trap"},),
        ),
        (
            RuntimeLimits(max_request_body_bytes=4),
            _scope(headers=((b"content-length", b"99999999999999999999"),)),
            ({"type": "http.request", "body": b"trap"},),
        ),
        (
            RuntimeLimits(max_request_body_bytes=4),
            _scope(),
            ({"type": "http.request", "body": b"12345"},),
        ),
        (
            RuntimeLimits(max_body_chunks=2),
            _scope(),
            (
                {"type": "http.request", "body": b"a", "more_body": True},
                {"type": "http.request", "body": b"b", "more_body": True},
                {"type": "http.request", "body": b"c", "more_body": False},
            ),
        ),
    ],
)
def test_input_bounds_fail_before_unbounded_accumulation(
    limits: RuntimeLimits, scope: dict[str, Any], messages: Iterable[Any]
) -> None:
    service = _Service()
    app = create_runtime_app(  # type: ignore[arg-type]
        service, app_proxy_path=APP_PROXY_PATH, limits=limits
    )

    sent = asyncio.run(_invoke_scope(app, scope, messages=messages))

    assert service.calls == []
    assert _status(sent) == 413
    assert b"trap" not in _body(sent)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda scope: object(),
        lambda scope: {**scope, "type": "websocket"},
        lambda scope: {**scope, "method": b"POST"},
        lambda scope: {**scope, "path": b"/apps/nla/catalog"},
        lambda scope: {**scope, "query_string": "not-bytes"},
        lambda scope: {**scope, "path": "\ud800", "raw_path": None},
        lambda scope: {**scope, "path": "", "raw_path": b""},
        lambda scope: {**scope, "raw_path": "not-bytes"},
        lambda scope: {**scope, "raw_path": b"/encoded-alias"},
        lambda scope: {key: value for key, value in scope.items() if key != "headers"},
        lambda scope: {**scope, "headers": [b"not-a-pair"]},
        lambda scope: {**scope, "headers": [(b"a",)]},
        lambda scope: {**scope, "headers": [("not-bytes", b"value")]},
        lambda scope: {**scope, "headers": [(b"name", "not-bytes")]},
    ],
)
def test_invalid_asgi_metadata_is_value_safe_and_fail_closed(mutation: Any) -> None:
    service = _Service()
    app = create_runtime_app(service, app_proxy_path=APP_PROXY_PATH)  # type: ignore[arg-type]
    scope = mutation(_scope())

    sent = asyncio.run(_invoke_scope(app, scope))

    assert service.calls == []
    assert _status(sent) == 400
    assert b"not-bytes" not in _body(sent)
    assert b"encoded-alias" not in _body(sent)


@pytest.mark.parametrize(
    "message",
    [
        b"not-a-message",
        {"type": "lifespan.startup"},
        {"type": "http.request", "body": "not-bytes"},
        {"type": "http.request", "more_body": 1},
    ],
)
def test_invalid_body_events_are_fixed_failures(message: Any) -> None:
    service = _Service()
    app = create_runtime_app(service, app_proxy_path=APP_PROXY_PATH)  # type: ignore[arg-type]

    sent = _invoke(app, messages=(message,))

    assert service.calls == []
    assert _status(sent) == 400
    assert b"not-bytes" not in _body(sent)


def test_receive_failure_is_fixed_and_does_not_reveal_exception() -> None:
    service = _Service()
    app = create_runtime_app(service, app_proxy_path=APP_PROXY_PATH)  # type: ignore[arg-type]
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        raise RuntimeError("SIGNATURE_QUERY_CURSOR_SECRET")

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    asyncio.run(app(_scope(), receive, send))

    assert service.calls == []
    assert _status(sent) == 400
    assert b"SIGNATURE_QUERY_CURSOR_SECRET" not in _body(sent)


def test_disconnect_before_body_returns_without_response_or_service_call() -> None:
    service = _Service()
    app = create_runtime_app(service, app_proxy_path=APP_PROXY_PATH)  # type: ignore[arg-type]

    sent = _invoke(app, messages=({"type": "http.disconnect"},))

    assert sent == []
    assert service.calls == []


class _BlockingService(_Service):
    def __init__(self) -> None:
        super().__init__()
        self.started = threading.Event()

    def catalog(self, request: RuntimeHttpRequest, *, cancellation: Any) -> RuntimeHttpResponse:
        self._record("catalog")
        self.catalog_request = request
        self.cancellation = cancellation
        self.started.set()
        while not cancellation.cancelled:
            time.sleep(0.001)
        raise RequestCancelled


@pytest.mark.parametrize(
    ("post_body_event", "expected_status"),
    [
        ({"type": "http.disconnect"}, None),
        ({"type": "http.request", "body": b"unexpected"}, 400),
        (b"invalid-event", 400),
    ],
)
def test_disconnect_or_invalid_post_body_event_cancels_running_service(
    post_body_event: Any, expected_status: int | None
) -> None:
    service = _BlockingService()
    app = create_runtime_app(service, app_proxy_path=APP_PROXY_PATH)  # type: ignore[arg-type]

    sent = _invoke(
        app,
        messages=(
            {"type": "http.request", "body": b"{}", "more_body": False},
            post_body_event,
        ),
    )

    assert service.calls == ["catalog"]
    assert service.cancellation.cancelled is True
    if expected_status is None:
        assert sent == []
    else:
        assert _status(sent) == expected_status
        assert b"unexpected" not in _body(sent)


def test_receive_failure_after_body_cancels_running_service_without_response() -> None:
    service = _BlockingService()
    app = create_runtime_app(service, app_proxy_path=APP_PROXY_PATH)  # type: ignore[arg-type]
    calls = 0
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return {"type": "http.request", "body": b"{}"}
        raise RuntimeError("SIGNED_QUERY_SECRET")

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    asyncio.run(app(_scope(), receive, send))

    assert sent == []
    assert service.calls == ["catalog"]
    assert service.cancellation.cancelled is True


def test_disconnect_does_not_wait_for_a_noncooperative_service() -> None:
    class NonCooperativeService(_Service):
        def __init__(self) -> None:
            super().__init__()
            self.release = threading.Event()

        def catalog(self, request: RuntimeHttpRequest, *, cancellation: Any) -> RuntimeHttpResponse:
            self._record("catalog")
            self.catalog_request = request
            self.cancellation = cancellation
            self.release.wait(2)
            return RuntimeHttpResponse(200, HEADERS, b"late")

    service = NonCooperativeService()
    app = create_runtime_app(service, app_proxy_path=APP_PROXY_PATH)  # type: ignore[arg-type]

    async def scenario() -> list[dict[str, Any]]:
        task = asyncio.create_task(
            _invoke_scope(
                app,
                _scope(),
                messages=(
                    {"type": "http.request", "body": b"{}"},
                    {"type": "http.disconnect"},
                ),
            )
        )
        sent = await asyncio.wait_for(task, 0.5)
        service.release.set()
        return sent

    sent = asyncio.run(scenario())

    assert sent == []
    assert service.cancellation.cancelled is True


def test_simultaneous_disconnect_drains_completed_sensitive_service_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sensitive = "never-log-sensitive-service-failure"

    async def exercise() -> list[dict[str, Any]]:
        loop = asyncio.get_running_loop()
        unhandled: list[dict[str, Any]] = []
        loop.set_exception_handler(lambda _loop, context: unhandled.append(context))

        async def both_done(
            tasks: Any,
            *,
            return_when: Any,
            timeout: float | None = None,
        ) -> tuple[set[Any], set[Any]]:
            assert timeout is None
            del return_when
            selected = tuple(tasks)
            while not all(task.done() for task in selected):
                await asyncio.sleep(0)
            return set(selected), set()

        monkeypatch.setattr(runtime_server.asyncio, "wait", both_done)

        def fail() -> RuntimeHttpResponse:
            raise RuntimeError(sensitive)

        async def disconnect() -> dict[str, str]:
            return {"type": "http.disconnect"}

        result = await runtime_server._run_service(
            fail,
            disconnect,
            runtime_server.RequestCancellation(),
        )
        assert result is None
        gc.collect()
        await asyncio.sleep(0)
        return unhandled

    assert asyncio.run(exercise()) == []


@pytest.mark.parametrize(
    "error",
    [RuntimeError("SIGNED_QUERY_CURSOR_SECRET"), RequestCancelled()],
)
def test_service_failures_are_fixed_503_without_sensitive_values(
    error: BaseException, caplog: pytest.LogCaptureFixture
) -> None:
    service = _Service(error)
    app = create_runtime_app(service, app_proxy_path=APP_PROXY_PATH)  # type: ignore[arg-type]

    sent = _invoke(app, messages=({"type": "http.request", "body": b"{}"},))

    assert _status(sent) == 503
    assert b"SIGNED_QUERY_CURSOR_SECRET" not in _body(sent)
    assert caplog.records == []


def test_task_cancellation_cancels_the_thread_service_and_propagates() -> None:
    service = _BlockingService()
    app = create_runtime_app(service, app_proxy_path=APP_PROXY_PATH)  # type: ignore[arg-type]

    async def scenario() -> None:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        queue.put_nowait({"type": "http.request", "body": b"{}"})

        async def receive() -> dict[str, Any]:
            return await queue.get()

        async def send(_message: dict[str, Any]) -> None:
            raise AssertionError("a cancelled request must not send")

        task = asyncio.create_task(app(_scope(), receive, send))
        while not service.started.is_set():
            await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert service.cancellation.cancelled is True


def test_cancellation_while_waiting_for_first_body_event_propagates() -> None:
    service = _Service()
    app = create_runtime_app(service, app_proxy_path=APP_PROXY_PATH)  # type: ignore[arg-type]

    async def scenario() -> None:
        waiting = asyncio.Event()

        async def receive() -> dict[str, Any]:
            waiting.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

        async def send(_message: dict[str, Any]) -> None:
            raise AssertionError("a cancelled request must not send")

        task = asyncio.create_task(app(_scope(), receive, send))
        await waiting.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert service.calls == []


def test_body_stream_timeout_is_fixed_cancels_and_drains_pending_receive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _Service()
    limits = RuntimeLimits(request_timeout_ms=10)
    app = create_runtime_app(  # type: ignore[arg-type]
        service,
        app_proxy_path=APP_PROXY_PATH,
        limits=limits,
    )
    cancellation = runtime_server.RequestCancellation()
    monkeypatch.setattr(runtime_server, "RequestCancellation", lambda: cancellation)

    async def scenario() -> tuple[list[dict[str, Any]], bool]:
        calls = 0
        pending_receive_drained = False
        sent: list[dict[str, Any]] = []

        async def receive() -> dict[str, Any]:
            nonlocal calls, pending_receive_drained
            calls += 1
            if calls == 1:
                return {
                    "type": "http.request",
                    "body": b"sensitive-partial-body",
                    "more_body": True,
                }
            try:
                await asyncio.Event().wait()
            finally:
                pending_receive_drained = True
            raise AssertionError("unreachable")

        async def send(message: dict[str, Any]) -> None:
            sent.append(message)

        await app(_scope(), receive, send)
        assert calls == 2
        return sent, pending_receive_drained

    sent, pending_receive_drained = asyncio.run(scenario())

    assert _status(sent) == 503
    assert b"sensitive-partial-body" not in _body(sent)
    assert service.calls == []
    assert cancellation.cancelled is True
    assert pending_receive_drained is True


class _HostileBaseException(BaseException):
    pass


@pytest.mark.parametrize(
    "response",
    [
        object(),
        RuntimeHttpResponse(True, HEADERS, b"bad"),
        RuntimeHttpResponse(199, HEADERS, b"bad"),
        RuntimeHttpResponse(600, HEADERS, b"bad"),
        RuntimeHttpResponse(200, list(HEADERS), b"bad"),  # type: ignore[arg-type]
        RuntimeHttpResponse(200, (("x", "1"),) * 65, b"bad"),
        RuntimeHttpResponse(200, HEADERS, "not-bytes"),  # type: ignore[arg-type]
        RuntimeHttpResponse(200, (["x", "1"],), b"bad"),  # type: ignore[arg-type]
        RuntimeHttpResponse(200, ((b"x", "1"),), b"bad"),  # type: ignore[arg-type]
        RuntimeHttpResponse(200, (("x", b"1"),), b"bad"),  # type: ignore[arg-type]
        RuntimeHttpResponse(200, (("X-Test", "ok"),), b"bad"),
        RuntimeHttpResponse(200, (("content-length", "3"),), b"bad"),
        RuntimeHttpResponse(
            200,
            (("content-length", "3"), ("content-length", "3")),
            b"bad",
        ),
        RuntimeHttpResponse(200, (("\xe9", "1"),), b"bad"),
        RuntimeHttpResponse(200, (("x", "\u20ac"),), b"bad"),
        RuntimeHttpResponse(200, (("", "1"),), b"bad"),
        RuntimeHttpResponse(200, (("x" * 257, "1"),), b"bad"),
        RuntimeHttpResponse(200, (("x", "1" * 8193),), b"bad"),
        RuntimeHttpResponse(200, (("bad name", "1"),), b"bad"),
        RuntimeHttpResponse(200, (("x", "SIGNED\rQUERY"),), b"bad"),
        RuntimeHttpResponse(
            200,
            tuple((f"x-{index}", "1" * 8000) for index in range(5)),
            b"bad",
        ),
    ],
)
def test_invalid_service_responses_fail_closed(response: Any) -> None:
    service = _Service(response)
    app = create_runtime_app(service, app_proxy_path=APP_PROXY_PATH)  # type: ignore[arg-type]

    sent = _invoke(app, messages=({"type": "http.request", "body": b"{}"},))

    assert _status(sent) == 503
    assert b"SIGNED" not in _body(sent)


def test_non_exception_base_failure_from_service_is_value_safe() -> None:
    service = _Service(_HostileBaseException("SIGNED_QUERY_SECRET"))
    app = create_runtime_app(service, app_proxy_path=APP_PROXY_PATH)  # type: ignore[arg-type]

    sent = _invoke(app, messages=({"type": "http.request", "body": b"{}"},))

    assert _status(sent) == 503
    assert b"SIGNED_QUERY_SECRET" not in _body(sent)


def test_oversized_service_body_fails_closed_at_configured_response_bound() -> None:
    limits = RuntimeLimits(max_response_body_bytes=512)
    service = _Service(RuntimeHttpResponse(200, HEADERS, b"x" * 513))
    app = create_runtime_app(  # type: ignore[arg-type]
        service, app_proxy_path=APP_PROXY_PATH, limits=limits
    )

    sent = _invoke(app, messages=({"type": "http.request", "body": b"{}"},))

    assert _status(sent) == 503
    assert len(_body(sent)) < 512


@pytest.mark.parametrize(
    "path",
    [
        None,
        "/livez",
        "/readyz",
        "relative",
        "/has?query",
        "/has#fragment",
        "/\ud800",
        "/control\x7f",
        "/" + "x" * 2048,
    ],
)
def test_invalid_adapter_paths_are_rejected_without_echo(path: Any) -> None:
    with pytest.raises(
        RuntimeServerConfigurationError, match="App Proxy path is invalid"
    ) as raised:
        create_runtime_app(_Service(), app_proxy_path=path)  # type: ignore[arg-type]
    assert repr(path) not in str(raised.value)


def test_invalid_service_limits_and_callables_are_rejected() -> None:
    with pytest.raises(RuntimeServerConfigurationError, match="runtime service is invalid"):
        create_runtime_app(object(), app_proxy_path=APP_PROXY_PATH)  # type: ignore[arg-type]
    with pytest.raises(RuntimeServerConfigurationError, match="runtime limits are invalid"):
        create_runtime_app(  # type: ignore[arg-type]
            _Service(), app_proxy_path=APP_PROXY_PATH, limits=object()
        )

    app = create_runtime_app(_Service(), app_proxy_path=APP_PROXY_PATH)  # type: ignore[arg-type]

    async def send(_message: dict[str, Any]) -> None:
        return None

    with pytest.raises(RuntimeServerConfigurationError, match="ASGI callables are invalid"):
        asyncio.run(app(_scope(), None, send))  # type: ignore[arg-type]


def test_missing_raw_path_is_rejected_fail_closed() -> None:
    service = _Service()
    app = create_runtime_app(service, app_proxy_path=APP_PROXY_PATH)  # type: ignore[arg-type]
    scope = _scope()
    scope.pop("raw_path")

    sent = asyncio.run(_invoke_scope(app, scope))

    assert _status(sent) == 400
    assert service.calls == []


def test_tuple_headers_and_bounded_length_are_not_rewritten() -> None:
    service = _Service()
    app = create_runtime_app(service, app_proxy_path=APP_PROXY_PATH)  # type: ignore[arg-type]
    scope = _scope(headers=((b"content-length", b" 2 "), (b"x-value", b"raw")))
    scope["headers"] = tuple(scope["headers"])

    sent = asyncio.run(
        _invoke_scope(app, scope, messages=({"type": "http.request", "body": b"{}"},))
    )

    assert _status(sent) == 200
    assert service.catalog_request is not None
    assert service.catalog_request.headers == (
        (b"content-length", b" 2 "),
        (b"x-value", b"raw"),
    )
