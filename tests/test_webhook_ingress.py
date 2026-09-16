from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import threading
from dataclasses import replace
from pathlib import Path

import pytest

import test_runtime_bootstrap as bootstrap_helpers
import test_runtime_server as transport_helpers
from nla_catalog_gateway import runtime_bootstrap, runtime_server, webhook_ingress
from nla_catalog_gateway.durable_inbox import DurableWebhookInbox
from nla_catalog_gateway.runtime_api import (
    RequestCancellation,
    RequestCancelled,
    RuntimeCatalogService,
    RuntimeHttpRequest,
)
from nla_catalog_gateway.runtime_server import RuntimeServerConfigurationError, create_runtime_app
from nla_catalog_gateway.webhook_ingress import ShopifyWebhookReceiver, WebhookConfigurationError

SHOP = "synthetic-nla.myshopify.com"
SHARED = b"synthetic-webhook-shared-material"
PATH = "/webhooks/catalog"
BODY = b' {"id":123, "title":"Synthetic card"}\n'


def _headers(body: bytes = BODY) -> tuple[tuple[bytes, bytes], ...]:
    return (
        (b"x-shopify-hmac-sha256", base64.b64encode(hmac.digest(SHARED, body, hashlib.sha256))),
        (b"x-shopify-shop-domain", SHOP.encode()),
        (b"x-shopify-webhook-id", b"delivery-1"),
        (b"x-shopify-topic", b"products/update"),
        (b"x-shopify-api-version", b"2026-07"),
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode()),
    )


def _setup(tmp_path: Path, **limits: int) -> tuple[DurableWebhookInbox, ShopifyWebhookReceiver]:
    inbox = DurableWebhookInbox(tmp_path / "inbox.sqlite3", SHOP, **limits)
    return inbox, ShopifyWebhookReceiver(inbox, SHARED, SHOP)


def _request(**changes: object) -> RuntimeHttpRequest:
    return replace(RuntimeHttpRequest("POST", PATH, b"", _headers(), (BODY,)), **changes)


def _receive(receiver: ShopifyWebhookReceiver, **changes: object):
    return receiver.receive(_request(**changes), cancellation=RequestCancellation())


def _app(receiver: ShopifyWebhookReceiver, **options: object):
    return create_runtime_app(
        RuntimeCatalogService(expected_shop_domain=SHOP, endpoint_path="/proxy/catalog"),
        app_proxy_path="/proxy/catalog",
        webhook_path=PATH,
        webhook_receiver=receiver,
        **options,
    )


def test_real_asgi_receipt_reopen_duplicate_and_conflict(tmp_path: Path) -> None:
    inbox, receiver = _setup(tmp_path)
    app = _app(receiver)
    for _ in range(2):
        result = transport_helpers._invoke(
            app,
            path=PATH,
            headers=_headers(),
            messages=({"type": "http.request", "body": BODY},),
        )
        assert result[0]["status"] == 200
        assert result[1]["body"] == b'{"received":true}'
    (original,) = DurableWebhookInbox(tmp_path / "inbox.sqlite3", SHOP).pending()
    assert original.envelope.payload == BODY
    assert original.revision == 1
    inbox.complete(original, dataset_generation="sha256:" + "a" * 64)
    changed = b'{"id":456}'
    assert _receive(receiver, headers=_headers(changed), body_chunks=(changed,)).status == 200
    (conflict,) = inbox.pending()
    assert conflict.reconciliation_required and conflict.envelope.payload == BODY


def test_bad_authentication_never_receives_even_duplicate(tmp_path: Path, monkeypatch) -> None:
    inbox, receiver = _setup(tmp_path)
    assert _receive(receiver).status == 200
    monkeypatch.setattr(inbox, "receive", lambda _: pytest.fail("unauthorized storage write"))
    assert _receive(receiver, body_chunks=(BODY.replace(b"123", b"999"),)).status == 401


@pytest.mark.parametrize(
    "signature", [b"not-base64", b"", b"YQ==", b"A" * 43 + b"=", b"A" * 43 + b"B"]
)
def test_invalid_signatures(tmp_path: Path, signature: bytes) -> None:
    inbox, receiver = _setup(tmp_path)
    headers = ((b"x-shopify-hmac-sha256", signature), *_headers()[1:])
    assert _receive(receiver, headers=headers).status == 401
    assert inbox.pending() == ()


@pytest.mark.parametrize(
    "name,value",
    [
        (b"x-shopify-shop-domain", b"other.myshopify.com"),
        (b"x-shopify-webhook-id", b""),
        (b"x-shopify-topic", b"bad"),
        (b"x-shopify-api-version", b"unstable"),
        (b"x-shopify-topic", b"\xff"),
        (b"content-type", b"text/plain"),
        (b"content-length", b"-1"),
        (b"content-length", b"9"),
        (b"content-length", b"0" * 11),
    ],
)
def test_invalid_metadata_does_not_write(tmp_path: Path, name: bytes, value: bytes) -> None:
    inbox, receiver = _setup(tmp_path)
    headers = tuple((key, value if key == name else val) for key, val in _headers())
    assert _receive(receiver, headers=headers).status in (400, 401)
    assert inbox.pending() == ()


@pytest.mark.parametrize("index", range(7))
def test_required_headers_unique_case_insensitively(tmp_path: Path, index: int) -> None:
    inbox, receiver = _setup(tmp_path)
    key, value = _headers()[index]
    assert _receive(receiver, headers=(*_headers(), (key.upper(), value))).status == 400
    if key != b"content-length":
        assert _receive(receiver, headers=tuple(h for h in _headers() if h[0] != key)).status == 400
    assert inbox.pending() == ()


@pytest.mark.parametrize(
    "extra",
    [
        (b"content-encoding", b"gzip"),
        (b"transfer-encoding", b"chunked"),
    ],
)
def test_ambiguous_body_encoding_rejected(tmp_path: Path, extra) -> None:
    inbox, receiver = _setup(tmp_path)
    assert _receive(receiver, headers=(*_headers(), extra)).status == 400
    assert inbox.pending() == ()


def test_no_length_mixed_case_and_chunked_asgi_bytes(tmp_path: Path) -> None:
    inbox, receiver = _setup(tmp_path)
    headers = tuple((k.upper(), v) for k, v in _headers() if k != b"content-length")
    assert (
        _receive(
            receiver,
            headers=(*headers, (b"x-extra", b"ignored")),
            body_chunks=(BODY[:10], BODY[10:]),
        ).status
        == 200
    )
    assert inbox.pending()[0].envelope.payload == BODY


def test_unknown_topic_is_durably_received_for_reconciliation(tmp_path: Path) -> None:
    inbox, receiver = _setup(tmp_path)
    headers = tuple((k, b"future/change" if k == b"x-shopify-topic" else v) for k, v in _headers())
    assert _receive(receiver, headers=headers).status == 200
    assert inbox.pending()[0].reconciliation_required


def test_capacity_and_storage_errors_are_retryable_and_value_free(
    tmp_path: Path, monkeypatch
) -> None:
    inbox, receiver = _setup(tmp_path, max_bytes=1)
    assert _receive(receiver).status == 503
    assert inbox.pending() == ()

    def failure(_):
        raise OSError("private local storage detail")

    monkeypatch.setattr(inbox, "receive", failure)
    result = _receive(receiver)
    assert result.status == 503 and b"private" not in result.body


def test_cancellation_before_and_after_commit(tmp_path: Path, monkeypatch) -> None:
    inbox, receiver = _setup(tmp_path)
    cancelled = RequestCancellation()
    cancelled.cancel()
    with pytest.raises(RequestCancelled):
        receiver.receive(_request(), cancellation=cancelled)
    assert inbox.pending() == ()
    control = RequestCancellation()
    original = inbox.receive

    def commit_and_disconnect(event):
        original(event)
        control.cancel()

    monkeypatch.setattr(inbox, "receive", commit_and_disconnect)
    with pytest.raises(RequestCancelled):
        receiver.receive(_request(), cancellation=control)
    assert len(inbox.pending()) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"method": "GET"},
        {"raw_query": b"x=y"},
        {"headers": []},
        {"headers": ()},
        {"headers": ((b"x", b"a"),) * 65},
        {"headers": ((b"x", b"a" * 8193),)},
        {"headers": ("bad",)},
        {"headers": (("x", b"a"),)},
        {"headers": ((b"x", "a"),)},
        {"body_chunks": []},
        {"body_chunks": ()},
        {"body_chunks": (b"",)},
        {"body_chunks": (b"x",) * 1025},
        {"body_chunks": ("string",)},
    ],
)
def test_invalid_direct_input(tmp_path: Path, changes: dict[str, object]) -> None:
    inbox, receiver = _setup(tmp_path)
    assert _receive(receiver, **changes).status == 400
    assert inbox.pending() == ()


def test_internal_authentication_failure_is_sanitized(tmp_path: Path, monkeypatch) -> None:
    inbox, receiver = _setup(tmp_path)

    def failure(*_):
        raise RuntimeError("private diagnostic")

    monkeypatch.setattr(webhook_ingress.hmac, "digest", failure)
    # Generate the request without the monkeypatched helper.
    request = RuntimeHttpRequest(
        "POST",
        PATH,
        b"",
        (
            (b"x-shopify-hmac-sha256", base64.b64encode(b"x" * 32)),
            (b"x-shopify-shop-domain", SHOP.encode()),
            (b"x-shopify-webhook-id", b"one"),
            (b"x-shopify-topic", b"products/update"),
            (b"x-shopify-api-version", b"2026-07"),
            (b"content-type", b"application/json"),
        ),
        (BODY,),
    )
    assert receiver.receive(request, cancellation=RequestCancellation()).status == 503
    assert inbox.pending() == ()


@pytest.mark.parametrize("secret", [b"", "string", b"x" * 1025])
def test_invalid_receiver_configuration(tmp_path: Path, secret: object) -> None:
    inbox, _ = _setup(tmp_path)
    with pytest.raises(WebhookConfigurationError):
        ShopifyWebhookReceiver(inbox, secret, SHOP)
    with pytest.raises(WebhookConfigurationError):
        ShopifyWebhookReceiver(inbox, SHARED, "other.myshopify.com")
    with pytest.raises(WebhookConfigurationError):
        ShopifyWebhookReceiver(None, SHARED, SHOP)


@pytest.mark.parametrize("path", ["/livez", "/readyz", "/proxy/catalog", "bad", None])
def test_route_configuration_cannot_collide(tmp_path: Path, path: object) -> None:
    _, receiver = _setup(tmp_path)
    with pytest.raises(RuntimeServerConfigurationError):
        create_runtime_app(
            transport_helpers._Service(),
            app_proxy_path="/proxy/catalog",
            webhook_path=path,
            webhook_receiver=receiver,
        )
    with pytest.raises(RuntimeServerConfigurationError):
        create_runtime_app(
            transport_helpers._Service(), app_proxy_path="/proxy/catalog", webhook_path=PATH
        )


def test_existing_catalog_limits_and_authentication_unchanged(tmp_path: Path) -> None:
    _, receiver = _setup(tmp_path)
    app = _app(receiver)
    denied = transport_helpers._invoke(
        app,
        path="/proxy/catalog",
        headers=_headers(),
        messages=({"type": "http.request", "body": BODY},),
    )
    # The unbound default service remains unavailable, even with webhook HMAC.
    assert denied[0]["status"] == 503
    body = b'{"padding":"' + b"a" * 70000 + b'"}'
    messages = ({"type": "http.request", "body": body},)
    assert (
        transport_helpers._invoke(app, path=PATH, headers=_headers(body), messages=messages)[0][
            "status"
        ]
        == 200
    )
    assert (
        transport_helpers._invoke(
            app, path="/proxy/catalog", headers=_headers(body), messages=messages
        )[0]["status"]
        == 413
    )
    assert transport_helpers._invoke(app, path=PATH, query=b"unexpected=1")[0]["status"] == 400
    disabled = create_runtime_app(transport_helpers._Service(), app_proxy_path="/proxy/catalog")
    assert transport_helpers._invoke(disabled, path=PATH)[0]["status"] == 400


def test_oversized_webhook_rejected_at_transport_and_receiver(tmp_path: Path, monkeypatch) -> None:
    inbox, receiver = _setup(tmp_path)
    monkeypatch.setattr(runtime_server, "MAX_WEBHOOK_PAYLOAD_BYTES", 8)
    monkeypatch.setattr(webhook_ingress, "MAX_WEBHOOK_PAYLOAD_BYTES", 8)
    assert _receive(receiver).status == 400
    result = transport_helpers._invoke(
        _app(receiver),
        path=PATH,
        headers=_headers(),
        messages=({"type": "http.request", "body": BODY},),
    )
    assert result[0]["status"] == 413 and inbox.pending() == ()


def test_http_deadline_does_not_acknowledge_a_blocked_worker(tmp_path: Path, monkeypatch) -> None:
    inbox, receiver = _setup(tmp_path)
    release = threading.Event()
    entered = threading.Event()
    original = inbox.receive

    def slow(event):
        entered.set()
        assert release.wait(2)
        return original(event)

    monkeypatch.setattr(inbox, "receive", slow)
    monkeypatch.setattr(runtime_server, "WEBHOOK_REPLY_SECONDS", 0.05)

    async def exercise():
        try:
            result = await transport_helpers._invoke_scope(
                _app(receiver),
                transport_helpers._scope(path=PATH, headers=_headers()),
                messages=({"type": "http.request", "body": BODY},),
            )
            assert entered.is_set() and result[0]["status"] == 503
            assert not release.is_set()
        finally:
            release.set()

    asyncio.run(exercise())
    assert len(inbox.pending()) == 1  # Completed after timeout, safe for a retry.


@pytest.mark.parametrize("disconnect", [True, False])
def test_interrupted_http_body_never_receipts(
    tmp_path: Path, monkeypatch, disconnect: bool
) -> None:
    inbox, receiver = _setup(tmp_path)
    monkeypatch.setattr(runtime_server, "WEBHOOK_REPLY_SECONDS", 0.05)
    messages = [{"type": "http.request", "body": BODY[:4], "more_body": True}]
    if disconnect:
        messages.append({"type": "http.disconnect"})
    result = transport_helpers._invoke(
        _app(receiver), path=PATH, headers=_headers(), messages=messages
    )
    if disconnect:
        assert result == []
    else:
        assert result[0]["status"] == 503
    assert inbox.pending() == ()


def test_host_configuration_connects_actual_receiver(tmp_path: Path) -> None:
    store = bootstrap_helpers._store(tmp_path)
    environment = bootstrap_helpers._environment(store)
    environment.update(
        {
            "NLA_SHOP_DOMAIN": SHOP,
            "NLA_APP_PROXY_SHARED_SECRET_B64": base64.b64encode(SHARED).decode(),
            "NLA_WEBHOOK_PATH": PATH,
            "NLA_WEBHOOK_INBOX_PATH": str(tmp_path / "host-inbox.sqlite3"),
        }
    )
    # Bootstrap's evidence-bound shop must remain the package's verified shop.
    environment["NLA_SHOP_DOMAIN"] = bootstrap_helpers.bundle_helpers.SHOP
    app = runtime_bootstrap.create_app(environment)
    body = BODY
    headers = tuple(
        (key, environment["NLA_SHOP_DOMAIN"].encode() if key == b"x-shopify-shop-domain" else value)
        for key, value in _headers(body)
    )
    result = transport_helpers._invoke(
        app, path=PATH, headers=headers, messages=({"type": "http.request", "body": body},)
    )
    assert result[0]["status"] == 200
    persisted = DurableWebhookInbox(tmp_path / "host-inbox.sqlite3", environment["NLA_SHOP_DOMAIN"])
    assert persisted.pending()[0].envelope.payload == body
    denied = transport_helpers._invoke(
        app,
        path=environment["NLA_APP_PROXY_BACKEND_PATH"],
        headers=headers,
        messages=({"type": "http.request", "body": body},),
    )
    # A valid webhook signature cannot authorize the actual bound catalog API.
    assert denied[0]["status"] == 401
    assert len(persisted.pending()) == 1


@pytest.mark.parametrize(
    "case", ["path_only", "inbox_only", "relative", "source", "store", "collision"]
)
def test_partial_or_unsafe_host_configuration_fails_before_inbox_write(
    tmp_path: Path, case: str
) -> None:
    store = bootstrap_helpers._store(tmp_path)
    environment = bootstrap_helpers._environment(store)
    target = tmp_path / "inbox.sqlite3"
    environment.update(NLA_WEBHOOK_PATH=PATH, NLA_WEBHOOK_INBOX_PATH=str(target))
    if case == "path_only":
        del environment["NLA_WEBHOOK_INBOX_PATH"]
    elif case == "inbox_only":
        del environment["NLA_WEBHOOK_PATH"]
    elif case == "relative":
        environment["NLA_WEBHOOK_INBOX_PATH"] = "relative.sqlite3"
    elif case == "source":
        environment["NLA_WEBHOOK_INBOX_PATH"] = str(
            runtime_bootstrap.REPOSITORY_ROOT / "inbox.sqlite3"
        )
    elif case == "store":
        environment["NLA_WEBHOOK_INBOX_PATH"] = str(store.root / "inbox.sqlite3")
    else:
        environment["NLA_WEBHOOK_PATH"] = environment["NLA_APP_PROXY_BACKEND_PATH"]
    bootstrap_helpers._fixed_failure(environment)
    assert not target.exists()
