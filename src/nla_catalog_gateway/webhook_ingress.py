"""Shopify raw-body authentication followed by durable local receipt, not projection."""

from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import UTC, datetime

from nla_catalog_gateway.durable_inbox import DurableWebhookInbox
from nla_catalog_gateway.runtime_api import (
    RequestCancellation,
    RuntimeHttpRequest,
    RuntimeHttpResponse,
)
from nla_catalog_gateway.sync import MAX_WEBHOOK_PAYLOAD_BYTES, RawWebhookEnvelope, WebhookKey

_REQUIRED = frozenset(
    {
        b"x-shopify-hmac-sha256",
        b"x-shopify-shop-domain",
        b"x-shopify-webhook-id",
        b"x-shopify-topic",
        b"x-shopify-api-version",
        b"content-type",
    }
)
_HEADERS = (
    ("content-type", "application/json; charset=utf-8"),
    ("cache-control", "no-store"),
    ("x-content-type-options", "nosniff"),
)


class WebhookConfigurationError(ValueError):
    """Invalid host configuration, with no values exposed."""


class _Unauthorized(Exception):
    pass


class ShopifyWebhookReceiver:
    """For one configured shop/app; no header is independently HMAC-signed.

    The publication worker must re-fetch authoritative records for the configured
    shop, not trust a header or payload as authority to mutate commercial data.
    """

    __slots__ = ("_inbox", "_secret", "_shop")

    def __init__(self, inbox: DurableWebhookInbox, shared_secret: bytes, shop_domain: str) -> None:
        try:
            if (
                type(inbox) is not DurableWebhookInbox
                or type(shared_secret) is not bytes
                or not 1 <= len(shared_secret) <= 1024
                or inbox.shop_domain != WebhookKey(shop_domain, "configuration").shop_domain
            ):
                raise ValueError
        except (TypeError, ValueError):
            raise WebhookConfigurationError("webhook configuration is invalid") from None
        self._inbox = inbox
        self._secret = shared_secret
        self._shop = shop_domain

    def receive(
        self,
        request: RuntimeHttpRequest,
        *,
        cancellation: RequestCancellation,
    ) -> RuntimeHttpResponse:
        cancellation.raise_if_cancelled()
        try:
            envelope = self._authenticate(request)
        except _Unauthorized:
            return _response(401)
        except (TypeError, ValueError):
            return _response(400)
        except Exception:
            return _response(503)
        cancellation.raise_if_cancelled()
        try:
            self._inbox.receive(envelope)
        except Exception:
            return _response(503)
        cancellation.raise_if_cancelled()
        # All three durable outcomes are receipts. Conflicts remain queued for
        # reconciliation; returning200 does not declare their contents applied.
        return _response(200)

    def _authenticate(self, request: RuntimeHttpRequest) -> RawWebhookEnvelope:
        if (
            type(request) is not RuntimeHttpRequest
            or request.method != "POST"
            or request.raw_query != b""
            or type(request.headers) is not tuple
            or len(request.headers) > 64
            or type(request.body_chunks) is not tuple
            or not 1 <= len(request.body_chunks) <= 1024
            or any(type(chunk) is not bytes for chunk in request.body_chunks)
        ):
            raise ValueError
        size = sum(map(len, request.body_chunks))
        if not 1 <= size <= MAX_WEBHOOK_PAYLOAD_BYTES:
            raise ValueError
        headers: dict[bytes, bytes] = {}
        for entry in request.headers:
            if type(entry) is not tuple or len(entry) != 2:
                raise ValueError
            name, value = entry
            if type(name) is not bytes or type(value) is not bytes or len(value) > 8192:
                raise ValueError
            key = name.lower()
            if key in {b"content-encoding", b"transfer-encoding"}:
                raise ValueError
            if key in _REQUIRED or key == b"content-length":
                if key in headers:
                    raise ValueError
                headers[key] = value
        if not _REQUIRED <= headers.keys():
            raise ValueError
        if headers[b"content-type"].lower() not in {
            b"application/json",
            b"application/json; charset=utf-8",
        }:
            raise ValueError
        length = headers.get(b"content-length")
        if length is not None and (not length.isdigit() or len(length) > 10 or int(length) != size):
            raise ValueError
        signature = headers[b"x-shopify-hmac-sha256"]
        try:
            supplied = base64.b64decode(signature, validate=True)
        except ValueError:
            raise _Unauthorized from None
        if len(supplied) != 32 or base64.b64encode(supplied) != signature:
            raise _Unauthorized
        body = b"".join(request.body_chunks)
        expected = hmac.digest(self._secret, body, hashlib.sha256)
        if not hmac.compare_digest(expected, supplied):
            raise _Unauthorized
        shop = headers[b"x-shopify-shop-domain"].decode("ascii")
        if shop != self._shop:
            raise _Unauthorized
        return RawWebhookEnvelope(
            shop_domain=shop,
            webhook_id=headers[b"x-shopify-webhook-id"].decode("ascii"),
            topic=headers[b"x-shopify-topic"].decode("ascii"),
            api_version=headers[b"x-shopify-api-version"].decode("ascii"),
            received_at=datetime.now(UTC).isoformat(),
            payload=body,
        )


def _response(status: int) -> RuntimeHttpResponse:
    return RuntimeHttpResponse(
        status,
        _HEADERS,
        b'{"received":true}' if status == 200 else b'{"received":false}',
    )
