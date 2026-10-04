"""Offline request/response tests; no Shopify or storage network is permitted."""

from __future__ import annotations

import hashlib
import http.client
import io
import itertools
import json
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from email.message import Message
from types import SimpleNamespace

import pytest

from nla_catalog_gateway import shopify_capture_http as transport

SHOP = "synthetic-nla.myshopify.com"
VERSION = "2026-07"
CLIENT = "synthetic-client-id"
SHARED = "synthetic-client-secret-for-tests"
ACCESS = "synthetic-access-token"
RENEWED = "synthetic-renewed-token"
SCOPES = "read_products,read_inventory,read_locations"
DOWNLOAD = (
    "https://storage.googleapis.com/synthetic-bulk/result.jsonl"
    "?signature=synthetic-private-signature"
)
QUERY = "query SyntheticCapture { shop { id } }"


class Response(io.BytesIO):
    def __init__(self, body=b"", *, status=200, headers=None, url=None):
        super().__init__(body)
        self.status = status
        self.headers = Message()
        for name, value in {"X-Shopify-API-Version": VERSION, **(headers or {})}.items():
            if value is not None:
                self.headers[name] = str(value)
        self.url = url
        self.requested_sizes = []

    def geturl(self):
        return self.url

    def read(self, size=-1):
        self.requested_sizes.append(size)
        return super().read(size)

    def read1(self, size=-1):
        self.requested_sizes.append(size)
        return super().read1(size)


def _json(value, **kwargs):
    return Response(json.dumps(value).encode(), **kwargs)


def _token(**changes):
    return _json({"access_token": ACCESS, "scope": SCOPES, "expires_in": 3600, **changes})


class HttpBoundary:
    def __init__(self):
        self.handlers = ()
        self.responses = []
        self.calls = []

    def build(self, *handlers):
        self.handlers = handlers
        return self

    def open(self, request, *, timeout):
        self.calls.append((request, timeout))
        assert self.responses, "unexpected extra HTTP request"
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        if response.url is None:
            response.url = request.full_url
        return response


@pytest.fixture
def boundary(monkeypatch):
    def forbid_network(*_args, **_kwargs):
        pytest.fail("offline capture test attempted a real connection")

    monkeypatch.setattr(socket, "create_connection", forbid_network)
    result = HttpBoundary()
    monkeypatch.setattr(urllib.request, "build_opener", result.build)
    return result


def _client(**changes):
    return transport.ShopifyCaptureHttp(
        **{
            "shop_domain": SHOP,
            "api_version": VERSION,
            "client_id": CLIENT,
            "client_secret": SHARED,
            **changes,
        }
    )


def _headers(request):
    return {name.lower(): value for name, value in request.header_items()}


def _safe_error(error):
    assert error.__cause__ is None
    assert error.__context__ is None
    for value in (CLIENT, SHARED, ACCESS, RENEWED, DOWNLOAD, "synthetic-private-signature"):
        assert value not in str(error)
        assert value not in repr(error)
    assert "\n" not in str(error)


def test_oauth_and_graphql_construct_exact_requests_and_cache_token(boundary):
    client = _client()
    assert not boundary.calls
    assert SHARED not in repr(client) and CLIENT not in repr(client)
    boundary.responses = [_token(), _json({"data": {"shop": {"id": "synthetic"}}})]
    assert client.graphql(QUERY, {"limit": 3}) == {"shop": {"id": "synthetic"}}
    oauth, query = [request for request, _ in boundary.calls]
    assert oauth.full_url == f"https://{SHOP}/admin/oauth/access_token"
    assert oauth.get_method() == "POST"
    assert urllib.parse.parse_qs(oauth.data.decode()) == {
        "grant_type": ["client_credentials"],
        "client_id": [CLIENT],
        "client_secret": [SHARED],
    }
    assert _headers(oauth)["content-type"].startswith("application/x-www-form-urlencoded")
    assert "x-shopify-access-token" not in _headers(oauth)
    assert query.full_url == f"https://{SHOP}/admin/api/{VERSION}/graphql.json"
    assert query.get_method() == "POST"
    assert json.loads(query.data) == {"query": QUERY, "variables": {"limit": 3}}
    assert _headers(query)["x-shopify-access-token"] == ACCESS
    assert SHARED.encode() not in query.data
    assert ACCESS not in repr(client)
    assert all(0 < timeout <= 30 for _, timeout in boundary.calls)
    boundary.responses = [_json({"data": {"cached": True}})]
    assert client.graphql(QUERY, {}) == {"cached": True}
    assert len(boundary.calls) == 3


@pytest.mark.parametrize(
    "scopes",
    [
        ",".join(f"{mode}_{resource}" for mode, resource in zip(modes, resources, strict=True))
        for resources in [("products", "inventory", "locations")]
        for modes in itertools.product(("read", "write"), repeat=3)
    ],
)
def test_write_scopes_also_grant_corresponding_reads(boundary, scopes):
    boundary.responses = [_token(scope=scopes), _json({"data": {"ok": True}})]
    assert _client().graphql(QUERY, {}) == {"ok": True}
    assert len(boundary.calls) == 2


def test_proxy_and_redirect_handlers_are_fail_closed(boundary, monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://synthetic-proxy.invalid:1234")
    _client()
    proxies = [
        handler for handler in boundary.handlers if isinstance(handler, urllib.request.ProxyHandler)
    ]
    assert len(proxies) == 1 and proxies[0].proxies == {}
    https = [
        handler for handler in boundary.handlers if isinstance(handler, urllib.request.HTTPSHandler)
    ]
    assert len(https) == 1
    assert https[0]._context.check_hostname is True
    assert https[0]._context.verify_mode == ssl.CERT_REQUIRED
    redirects = [
        handler
        for handler in boundary.handlers
        if isinstance(handler, urllib.request.HTTPRedirectHandler)
    ]
    assert len(redirects) == 1
    request = urllib.request.Request(f"https://{SHOP}/admin/oauth/access_token")
    try:
        redirected = redirects[0].redirect_request(
            request, None, 302, "redirect", Message(), "https://foreign.invalid/collect"
        )
    except urllib.error.HTTPError:
        pass
    else:
        assert redirected is None


def test_token_expiry_requires_new_client_credentials_request(boundary, monkeypatch):
    now = [100.0]
    monkeypatch.setattr(transport.time, "monotonic", lambda: now[0])
    client = _client()
    boundary.responses = [_token(), _json({"data": {}})]
    client.graphql(QUERY, {})
    now[0] = 200.0
    boundary.responses = [_json({"data": {}})]
    client.graphql(QUERY, {})
    now[0] = 3701.0
    boundary.responses = [_token(access_token=RENEWED), _json({"data": {}})]
    client.graphql(QUERY, {})
    assert len(boundary.calls) == 5
    assert _headers(boundary.calls[-1][0])["x-shopify-access-token"] == RENEWED


@pytest.mark.parametrize(
    "changes",
    [
        {"shop_domain": "https://synthetic-nla.myshopify.com"},
        {"shop_domain": "synthetic-nla.myshopify.com.attacker.invalid"},
        {"shop_domain": "synthetic-nla.myshopify.com:443"},
        {"shop_domain": "Synthetic-Nla.myshopify.com"},
        {"api_version": "2026-08"},
        {"api_version": "unstable"},
        {"client_id": ""},
        {"client_secret": ""},
        {"timeout_seconds": 0},
        {"timeout_seconds": True},
    ],
)
def test_invalid_configuration_is_rejected_without_network(boundary, changes):
    with pytest.raises(transport.CaptureHttpError) as error:
        _client(**changes)
    _safe_error(error.value)
    assert not boundary.calls


@pytest.mark.parametrize(
    "changes",
    [
        {"scope": "read_products,read_inventory"},
        {"scope": "read_products,read_locations"},
        {"scope": "read_inventory,read_locations"},
        {"scope": "read_products_extra,read_inventory,read_locations"},
        {"scope": "write_products_extra,read_inventory,read_locations"},
        {"scope": "write_publications,read_inventory,read_locations"},
        {"scope": "write_products,read_inventory"},
        {"scope": ["read_products", "read_inventory", "read_locations"]},
        {"access_token": ""},
        {"access_token": ACCESS + "\r\nInjected: value"},
        {"expires_in": 0},
        {"expires_in": True},
        {"expires_in": "3600"},
    ],
)
def test_invalid_token_or_missing_scope_never_reaches_graphql(boundary, changes):
    boundary.responses = [_token(**changes)]
    with pytest.raises(transport.CaptureHttpError) as error:
        _client().graphql(QUERY, {})
    _safe_error(error.value)
    assert len(boundary.calls) == 1


@pytest.mark.parametrize(
    "body",
    [
        b"not-json",
        b'{"data":{},"data":{"secret":"test-only-token"}}',
        b'{"data":{"x":1,"x":2}}',
        b'{"data":{"x":NaN}}',
        b"[]",
        b'{"data":null}',
        b'{"errors":[{"message":"synthetic-client-secret-for-tests"}],"data":{}}',
        b" " * (4 * 1024 * 1024 + 1),
    ],
    ids=[
        "invalid",
        "duplicate-root",
        "duplicate-nested",
        "nan",
        "array",
        "null",
        "errors",
        "large",
    ],
)
def test_invalid_graphql_json_is_bounded_and_sanitized(boundary, body):
    response = Response(body)
    boundary.responses = [_token(), response]
    with pytest.raises(transport.CaptureHttpError) as error:
        _client().graphql(QUERY, {})
    _safe_error(error.value)
    assert response.closed
    assert response.requested_sizes and all(
        0 < size <= 4 * 1024 * 1024 + 1 for size in response.requested_sizes
    )


@pytest.mark.parametrize("version", [None, "2026-04", "2026-10"])
def test_graphql_rejects_missing_or_different_response_api_version(boundary, version):
    response = _json({"data": {}}, headers={"X-Shopify-API-Version": version})
    boundary.responses = [_token(), response]
    with pytest.raises(transport.CaptureHttpError) as error:
        _client().graphql(QUERY, {})
    _safe_error(error.value)
    assert len(boundary.calls) == 2
    assert response.closed


@pytest.mark.parametrize("stage", ["oauth", "graphql", "download"])
@pytest.mark.parametrize("kind", ["http-error", "url-error", "redirect-status", "changed-origin"])
def test_http_failures_never_expose_secrets_or_follow_other_origins(boundary, stage, kind):
    if kind == "http-error":
        failure = urllib.error.HTTPError(DOWNLOAD, 403, SHARED, {}, io.BytesIO(ACCESS.encode()))
    elif kind == "url-error":
        failure = urllib.error.URLError(DOWNLOAD + SHARED)
    elif kind == "redirect-status":
        failure = Response(status=302, headers={"Location": "https://foreign.invalid/collect"})
    else:
        failure = Response(b"{}", url="https://foreign.invalid/collect")
    boundary.responses = ([_token()] if stage == "graphql" else []) + [failure]
    client = _client()
    with pytest.raises(transport.CaptureHttpError) as error:
        if stage == "download":
            client.download(DOWNLOAD, io.BytesIO(), expected_bytes=2)
        else:
            client.graphql(QUERY, {})
    _safe_error(error.value)
    assert len(boundary.calls) == (2 if stage == "graphql" else 1)


@pytest.mark.parametrize("authenticated", [False, True])
def test_download_preserves_original_bytes_hash_and_never_sends_token(boundary, authenticated):
    raw = b' {"unicode":"\xc3\xa0", "id":123}\r\n{"id":456}\n'
    response = Response(raw, headers={"Content-Length": len(raw)})
    client = _client()
    if authenticated:
        boundary.responses = [_token(), _json({"data": {}})]
        client.graphql(QUERY, {})
        boundary.calls.clear()
    boundary.responses = [response]
    output = io.BytesIO()
    assert (
        client.download(DOWNLOAD, output, expected_bytes=len(raw))
        == hashlib.sha256(raw).hexdigest()
    )
    assert output.getvalue() == raw and not output.closed
    assert response.closed
    request, timeout = boundary.calls[0]
    assert request.full_url == DOWNLOAD and request.get_method() == "GET"
    assert request.data is None and timeout == 30
    assert "x-shopify-access-token" not in _headers(request)
    assert "authorization" not in _headers(request)
    assert SHARED not in repr(client) and DOWNLOAD not in repr(client)


@pytest.mark.parametrize(
    "url",
    [
        "http://storage.googleapis.com/synthetic/result.jsonl",
        "https://storage.googleapis.com.attacker.invalid/result.jsonl",
        "https://foreign.invalid/result.jsonl",
        "https://127.0.0.1/result.jsonl",
        "https://storage.googleapis.com:444/result.jsonl",
        "https://user@storage.googleapis.com/result.jsonl",
        "https://storage.googleapis.com/result.jsonl#fragment",
        "https://storage.googleapis.com/result\r\nInjected: value",
    ],
)
def test_download_rejects_untrusted_url_before_request(boundary, url):
    with pytest.raises(transport.CaptureHttpError) as error:
        _client().download(url, io.BytesIO(), expected_bytes=1)
    _safe_error(error.value)
    assert not boundary.calls


@pytest.mark.parametrize(
    ("raw", "expected", "headers"),
    [
        (b"short", 6, {}),
        (b"too-long", 4, {}),
        (b"data", 4, {"Content-Length": "5"}),
        (b"data", 4, {"Content-Length": "invalid"}),
        (b"data", 4, {"Content-Encoding": "gzip"}),
    ],
)
def test_download_rejects_size_or_encoding_mismatch(boundary, raw, expected, headers):
    response = Response(raw, headers=headers)
    boundary.responses = [response]
    with pytest.raises(transport.CaptureHttpError) as error:
        _client().download(DOWNLOAD, io.BytesIO(), expected_bytes=expected)
    _safe_error(error.value)
    assert response.closed


@pytest.mark.parametrize(
    "changes",
    [
        {"expected_bytes": -1},
        {"expected_bytes": True},
        {"expected_bytes": 11, "maximum_bytes": 10},
        {"maximum_bytes": 0},
        {"maximum_seconds": 0},
        {"maximum_seconds": True},
    ],
)
def test_download_rejects_invalid_bounds_before_request(boundary, changes):
    with pytest.raises(transport.CaptureHttpError) as error:
        _client().download(DOWNLOAD, io.BytesIO(), **{"expected_bytes": 4, **changes})
    _safe_error(error.value)
    assert not boundary.calls


def test_download_detects_deadline_crossed_while_reading(boundary, monkeypatch):
    now = [0.0]
    monkeypatch.setattr(transport.time, "monotonic", lambda: now[0])

    class SlowResponse(Response):
        def read1(self, size=-1):
            now[0] = 2.0
            return super().read1(size)

    response = SlowResponse(b"data")
    boundary.responses = [response]
    with pytest.raises(transport.CaptureHttpError) as error:
        _client().download(DOWNLOAD, io.BytesIO(), expected_bytes=4, maximum_seconds=1)
    _safe_error(error.value)
    assert response.closed


@pytest.mark.parametrize("kind", ["short", "exception"])
def test_download_never_reports_success_after_output_failure(boundary, kind):
    class BrokenOutput(io.BytesIO):
        def write(self, raw):
            if kind == "exception":
                raise OSError(SHARED + DOWNLOAD)
            return super().write(raw[:-1])

    response = Response(b"data")
    boundary.responses = [response]
    with pytest.raises(transport.CaptureHttpError) as error:
        _client().download(DOWNLOAD, BrokenOutput(), expected_bytes=4)
    _safe_error(error.value)
    assert response.closed


def test_actual_http_response_updates_socket_timeout_without_network(boundary):
    timeouts = []
    raw_body = b"original\r\nbytes\n"

    class SocketRaw(io.RawIOBase):
        def __init__(self):
            super().__init__()
            self._sock = self
            self.source = io.BytesIO(
                b"HTTP/1.1 200 OK\r\nContent-Length: "
                + str(len(raw_body)).encode()
                + b"\r\n\r\n"
                + raw_body
            )

        def readable(self):
            return True

        def readinto(self, output):
            return self.source.readinto(output)

        def settimeout(self, timeout):
            timeouts.append(timeout)

        def close(self):
            self.source.close()
            super().close()

    raw = SocketRaw()
    sock = SimpleNamespace(makefile=lambda _mode: io.BufferedReader(raw))
    response = http.client.HTTPResponse(sock, method="GET", url=DOWNLOAD)
    response.url = DOWNLOAD  # urllib assigns this after the HTTP connection returns.
    response.begin()
    boundary.responses = [response]
    output = io.BytesIO()
    assert (
        _client().download(DOWNLOAD, output, len(raw_body)) == hashlib.sha256(raw_body).hexdigest()
    )
    assert output.getvalue() == raw_body
    assert timeouts and all(0 < timeout <= 30 for timeout in timeouts)
    assert response.closed and raw.closed


@pytest.mark.parametrize("kind", ["nonbytes", "overread"])
def test_invalid_transport_chunk_is_not_accepted(boundary, kind):
    class InvalidChunk(Response):
        def read1(self, size=-1):
            return "not bytes" if kind == "nonbytes" else b"x" * (size + 1)

    response = InvalidChunk()
    boundary.responses = [response]
    with pytest.raises(transport.CaptureHttpError) as error:
        _client().download(DOWNLOAD, io.BytesIO(), expected_bytes=1)
    _safe_error(error.value)
    assert response.closed


@pytest.mark.parametrize("kind", ["finite-float", "overflow-float", "long-header", "short-body"])
def test_json_number_and_announced_size_boundaries(boundary, kind):
    body = b'{"data":{"cost":1.25}}'
    headers = {}
    if kind == "overflow-float":
        body = b'{"data":{"cost":1e999}}'
    elif kind == "long-header":
        headers["Content-Length"] = str(4 * 1024 * 1024 + 1)
    elif kind == "short-body":
        headers["Content-Length"] = str(len(body) + 1)
    response = Response(body, headers=headers)
    boundary.responses = [_token(), response]
    client = _client()
    if kind == "finite-float":
        assert client.graphql(QUERY, {}) == {"cost": 1.25}
    else:
        with pytest.raises(transport.CaptureHttpError) as error:
            client.graphql(QUERY, {})
        _safe_error(error.value)
    assert response.closed


@pytest.mark.parametrize(
    ("query", "variables"),
    [("", {}), ("  ", {}), (None, {}), (QUERY, []), (QUERY, {"bad": float("nan")})],
)
def test_invalid_graphql_request_never_reaches_network(boundary, query, variables):
    with pytest.raises(transport.CaptureHttpError) as error:
        _client().graphql(query, variables)
    _safe_error(error.value)
    assert not boundary.calls


def test_oversize_graphql_request_is_not_sent(boundary):
    boundary.responses = [_token()]
    with pytest.raises(transport.CaptureHttpError) as error:
        _client().graphql("x" * (4 * 1024 * 1024), {})
    _safe_error(error.value)
    assert len(boundary.calls) == 1
    assert boundary.calls[0][0].full_url.endswith("/admin/oauth/access_token")


def test_token_expiring_during_response_is_not_cached(boundary, monkeypatch):
    now = [0.0]
    monkeypatch.setattr(transport.time, "monotonic", lambda: now[0])

    class DelayedToken(Response):
        def read1(self, size=-1):
            now[0] = 2.0
            return super().read1(size)

    delayed = DelayedToken(
        json.dumps({"access_token": ACCESS, "scope": SCOPES, "expires_in": 1}).encode()
    )
    boundary.responses = [delayed]
    client = _client()
    with pytest.raises(transport.CaptureHttpError) as error:
        client.graphql(QUERY, {})
    _safe_error(error.value)
    assert len(boundary.calls) == 1 and delayed.closed
    boundary.responses = [_token(), _json({"data": {}})]
    assert client.graphql(QUERY, {}) == {}
    assert len(boundary.calls) == 3
