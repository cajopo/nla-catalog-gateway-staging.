"""Concrete, bounded HTTPS transport for the private Shopify capture command."""

from __future__ import annotations

import hashlib
import http.client
import json
import math
import re
import ssl
import time
import urllib.parse
import urllib.request
from typing import BinaryIO

_SHOP_RE = re.compile(r"(?:[a-z0-9]|[a-z0-9][a-z0-9-]{0,61}[a-z0-9])\.myshopify\.com\Z")
_VERSION_RE = re.compile(r"[0-9]{4}-(?:01|04|07|10)\Z")
_REQUIRED_SCOPES = frozenset({"read_products", "read_inventory", "read_locations"})
_MAXIMUM_JSON_BYTES = 4 * 1024 * 1024
_CHUNK_BYTES = 64 * 1024


class CaptureHttpError(ValueError):
    """Public error deliberately excludes credentials, URLs and remote responses."""

    def __init__(self) -> None:
        super().__init__("Shopify capture HTTPS request failed")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _finite_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("nonfinite JSON number")
    return result


def _reject_constant(value: str) -> None:
    raise ValueError("nonfinite JSON constant")


def _positive_seconds(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("invalid timeout")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise ValueError("invalid timeout")
    return result


class ShopifyCaptureHttp:
    """Keep OAuth credentials in memory; never retry an ambiguous GraphQL request."""

    def __init__(
        self,
        shop_domain: str,
        api_version: str,
        client_id: str,
        client_secret: str,
        *,
        timeout_seconds: float = 30,
    ) -> None:
        try:
            self._configure(shop_domain, api_version, client_id, client_secret, timeout_seconds)
        except Exception:  # noqa: S110 -- do not retain or log possibly secret exception details
            pass
        else:
            return
        # Raise after leaving the handler: even __context__ must not retain a secret.
        raise CaptureHttpError() from None

    def _configure(self, shop, version, client_id, client_secret, timeout) -> None:
        if not isinstance(shop, str) or _SHOP_RE.fullmatch(shop) is None:
            raise ValueError("invalid shop")
        if not isinstance(version, str) or _VERSION_RE.fullmatch(version) is None:
            raise ValueError("invalid API version")
        for credential in (client_id, client_secret):
            if (
                not isinstance(credential, str)
                or not credential
                or len(credential) > 16384
                or any(ord(character) < 32 or ord(character) == 127 for character in credential)
            ):
                raise ValueError("invalid credentials")
        self._timeout = _positive_seconds(timeout)
        self._api_version = version
        self._token_url = f"https://{shop}/admin/oauth/access_token"
        self._graphql_url = f"https://{shop}/admin/api/{version}/graphql.json"
        self._client_id = client_id
        self._client_secret = client_secret
        self._token: str | None = None
        self._refresh_at = 0.0
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()),
            _NoRedirect(),
        )

    def _remaining(self, deadline: float) -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError("request deadline exceeded")
        return min(self._timeout, remaining)

    def _read_chunk(self, response, size: int, deadline: float) -> bytes:
        timeout = self._remaining(deadline)
        # urllib's HTTPS response is an HTTPResponse. Updating its socket timeout
        # bounds the final blocking receive by the remaining overall deadline.
        if isinstance(response, http.client.HTTPResponse) and response.fp is not None:
            response.fp.raw._sock.settimeout(timeout)
        chunk = response.read1(size)
        self._remaining(deadline)
        if not isinstance(chunk, bytes) or len(chunk) > size:
            raise ValueError("invalid response bytes")
        return chunk

    @staticmethod
    def _validate_response(response, url: str, maximum_bytes: int) -> int | None:
        if response.status != 200 or response.geturl() != url:
            raise ValueError("unexpected HTTP response")
        if response.headers.get("Content-Encoding", "identity").strip().lower() != "identity":
            raise ValueError("encoded response")
        length = response.headers.get("Content-Length")
        if length is None:
            return None
        if not re.fullmatch(r"[0-9]+", length):
            raise ValueError("invalid content length")
        result = int(length)
        if result > maximum_bytes:
            raise ValueError("response too large")
        return result

    def _request_json(
        self,
        url: str,
        body: bytes,
        headers: dict[str, str],
        *,
        expected_api_version: str | None = None,
    ) -> dict:
        if len(body) > _MAXIMUM_JSON_BYTES:
            raise ValueError("request too large")
        deadline = time.monotonic() + self._timeout
        request = urllib.request.Request(  # noqa: S310 -- private, fixed validated HTTPS URLs
            url,
            data=body,
            headers={"Accept": "application/json", "Accept-Encoding": "identity", **headers},
            method="POST",
        )
        with self._opener.open(request, timeout=self._remaining(deadline)) as response:
            if (
                expected_api_version is not None
                and response.headers.get("X-Shopify-API-Version") != expected_api_version
            ):
                raise ValueError("unexpected Shopify API version")
            expected = self._validate_response(response, url, _MAXIMUM_JSON_BYTES)
            data = bytearray()
            while True:
                chunk = self._read_chunk(
                    response, min(_CHUNK_BYTES, _MAXIMUM_JSON_BYTES + 1 - len(data)), deadline
                )
                if not chunk:
                    break
                data.extend(chunk)
                if len(data) > _MAXIMUM_JSON_BYTES:
                    raise ValueError("response too large")
            if expected is not None and len(data) != expected:
                raise ValueError("incomplete response")
        result = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_float=_finite_float,
            parse_constant=_reject_constant,
        )
        if not isinstance(result, dict):
            raise ValueError("invalid JSON response")
        return result

    def _access_token(self) -> str:
        started = time.monotonic()
        if self._token is not None and started < self._refresh_at:
            return self._token
        body = urllib.parse.urlencode(
            {
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            }
        ).encode("utf-8")
        payload = self._request_json(
            self._token_url, body, {"Content-Type": "application/x-www-form-urlencoded"}
        )
        token = payload.get("access_token")
        expires = payload.get("expires_in")
        scope = payload.get("scope")
        if (
            not isinstance(token, str)
            or not token
            or len(token) > 16384
            or not token.isascii()
            or any(ord(character) <= 32 or ord(character) == 127 for character in token)
            or type(expires) is not int
            or expires <= 0
            or not isinstance(scope, str)
            or not _REQUIRED_SCOPES.issubset({item.strip() for item in scope.split(",")})
        ):
            raise ValueError("invalid OAuth response")
        self._refresh_at = started + expires - min(60, expires / 10)
        if not math.isfinite(self._refresh_at) or time.monotonic() >= self._refresh_at:
            raise ValueError("expired OAuth response")
        self._token = token
        return token

    def graphql(self, query: str, variables: dict) -> dict:
        """Return GraphQL data, failing closed on transport or top-level API errors."""
        try:
            if not isinstance(query, str) or not query.strip() or not isinstance(variables, dict):
                raise ValueError("invalid GraphQL request")
            body = json.dumps(
                {"query": query, "variables": variables}, allow_nan=False, separators=(",", ":")
            ).encode("utf-8")
            payload = self._request_json(
                self._graphql_url,
                body,
                {
                    "Content-Type": "application/json",
                    "X-Shopify-Access-Token": self._access_token(),
                },
                expected_api_version=self._api_version,
            )
            if payload.get("errors") or not isinstance(payload.get("data"), dict):
                raise ValueError("GraphQL response failed")
            return payload["data"]
        except Exception:  # noqa: S110 -- discard secret-bearing remote errors before raising
            pass
        raise CaptureHttpError() from None

    def download(
        self,
        url: str,
        output: BinaryIO,
        expected_bytes: int,
        *,
        maximum_bytes: int = 2 * 1024 * 1024 * 1024,
        maximum_seconds: float = 1200,
    ) -> str:
        """Copy original Bulk bytes to a caller-owned stream and return their SHA-256."""
        try:
            return self._download(url, output, expected_bytes, maximum_bytes, maximum_seconds)
        except Exception:  # noqa: S110 -- discard signed URLs and response details before raising
            pass
        raise CaptureHttpError() from None

    def _download(self, url, output, expected, maximum_bytes, maximum_seconds) -> str:
        if not isinstance(url, str) or any(
            character.isspace() or ord(character) < 32 or ord(character) == 127 or character == "\\"
            for character in url
        ):
            raise ValueError("invalid Bulk URL")
        parsed = urllib.parse.urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.netloc not in {"storage.googleapis.com", "storage.googleapis.com:443"}
            or parsed.fragment
            or "#" in url
        ):
            raise ValueError("invalid Bulk URL")
        if (
            type(expected) is not int
            or type(maximum_bytes) is not int
            or expected < 0
            or maximum_bytes <= 0
            or expected > maximum_bytes
        ):
            raise ValueError("invalid download bounds")
        deadline = time.monotonic() + _positive_seconds(maximum_seconds)
        request = urllib.request.Request(  # noqa: S310 -- exact allowlisted HTTPS authority
            url, headers={"Accept-Encoding": "identity"}, method="GET"
        )
        digest = hashlib.sha256()
        received = 0
        with self._opener.open(request, timeout=self._remaining(deadline)) as response:
            length = self._validate_response(response, url, maximum_bytes)
            if length is not None and length != expected:
                raise ValueError("unexpected download size")
            while True:
                chunk = self._read_chunk(
                    response, min(_CHUNK_BYTES, expected + 1 - received), deadline
                )
                if not chunk:
                    break
                received += len(chunk)
                if received > expected:
                    raise ValueError("download too large")
                if output.write(chunk) != len(chunk):
                    raise ValueError("incomplete output write")
                self._remaining(deadline)
                digest.update(chunk)
        if received != expected:
            raise ValueError("incomplete download")
        return digest.hexdigest()
