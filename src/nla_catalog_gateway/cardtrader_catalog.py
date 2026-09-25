"""Read-only CardTrader catalog transport; no marketplace or Shopify mutations.

Reference: https://www.cardtrader.com/it/docs/api/full/reference
Live evidence (2026-09-25): collections may use {"array": [...]} rather than
the direct arrays in documentation. Unknown envelopes are rejected.
"""

from __future__ import annotations

import http.client
import json
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = "https://api.cardtrader.com/api/v2/"
MAX_RESPONSE_BYTES = 32 * 1024 * 1024


class CardTraderCatalogError(ValueError):
    """Fixed error codes only: never include remote bodies or credentials."""

    def __init__(self, reason: str, http_status: int | None = None) -> None:
        super().__init__(reason)
        self.http_status = http_status


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


def catalog_rows(payload: object) -> list[dict]:
    """Accept only the documented or observed collection shape."""
    if isinstance(payload, dict) and set(payload) == {"array"}:
        payload = payload["array"]
    if not isinstance(payload, list) or any(not isinstance(row, dict) for row in payload):
        raise CardTraderCatalogError("invalid_collection")
    return payload


class CardTraderCatalogClient:
    """One fixed HTTPS origin, GET-only catalog endpoints, bounded responses.

    The caller controls scheduling/backoff; a failure never yields a partial list
    or an implicit empty-success result. No token persistence or logging here.
    """

    def __init__(self, token: str, *, timeout: float = 30, opener=None) -> None:
        if (
            not isinstance(token, str)
            or not token
            or len(token) > 8192
            or any(not 33 <= ord(char) <= 126 for char in token)
            or token.lower().startswith("bearer ")
        ):
            raise CardTraderCatalogError("invalid_token")
        if type(timeout) not in (int, float) or not 0 < timeout <= 60:
            raise CardTraderCatalogError("invalid_timeout")
        self._token = token
        self._timeout = timeout
        self._opener = opener or urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _NoRedirect()
        )

    def collection(self, kind: str, *, expansion_id: int | None = None) -> list[dict]:
        if kind == "blueprints":
            if type(expansion_id) is not int or not 0 < expansion_id < 2**63:
                raise CardTraderCatalogError("invalid_expansion_id")
            path = "blueprints/export?" + urllib.parse.urlencode({"expansion_id": expansion_id})
        elif kind in ("games", "categories", "expansions") and expansion_id is None:
            path = kind
        else:
            raise CardTraderCatalogError("unsupported_catalog_request")
        request = urllib.request.Request(  # noqa: S310 -- fixed HTTPS origin and allowlisted paths
            BASE_URL + path,
            headers={"Authorization": "Bearer " + self._token, "Accept": "application/json"},
            method="GET",
        )
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                if response.status != 200:
                    raise CardTraderCatalogError("unexpected_status", response.status)
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise CardTraderCatalogError("response_too_large")
                try:
                    payload = json.loads(raw)
                except (ValueError, UnicodeError, RecursionError):
                    raise CardTraderCatalogError("invalid_json") from None
                return catalog_rows(payload)
        except urllib.error.HTTPError as error:
            status = error.code
        except CardTraderCatalogError:
            raise
        except (OSError, http.client.HTTPException):
            status = None
        raise CardTraderCatalogError("request_failed", status) from None
