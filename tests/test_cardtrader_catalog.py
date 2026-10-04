"""Synthetic-only tests; no real catalog records or credentials."""

import http.client
import json
import urllib.error
from unittest.mock import Mock

import pytest

from nla_catalog_gateway.cardtrader_catalog import (
    BASE_URL,
    MAX_RESPONSE_BYTES,
    CardTraderCatalogClient,
    CardTraderCatalogError,
    _NoRedirect,
    catalog_rows,
)


class Response:
    def __init__(self, body=b"[]", status=200):
        self.body, self.status = body, status
        self.bound = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def read(self, bound):
        self.bound = bound
        return self.body


@pytest.mark.parametrize("payload", [[], [{}], {"array": []}, {"array": [{"id": 123}]}])
def test_documented_and_observed_collections(payload):
    assert catalog_rows(payload) == (payload["array"] if isinstance(payload, dict) else payload)


@pytest.mark.parametrize(
    "payload", [None, "secret", [None], {"array": {}}, {"data": []}, {"array": [], "error": "x"}]
)
def test_unknown_or_error_envelopes_rejected(payload):
    with pytest.raises(CardTraderCatalogError, match=r"^invalid_collection$"):
        catalog_rows(payload)


@pytest.mark.parametrize("token", [None, "", "x" * 8193, "secret\n", "Bearer test", "è"])
def test_invalid_credentials(token):
    with pytest.raises(CardTraderCatalogError, match=r"^invalid_token$"):
        CardTraderCatalogClient(token)


@pytest.mark.parametrize("timeout", [None, True, 0, -1, 61, float("nan")])
def test_invalid_timeout(timeout):
    with pytest.raises(CardTraderCatalogError, match=r"^invalid_timeout$"):
        CardTraderCatalogClient("synthetic", timeout=timeout)


@pytest.mark.parametrize("kind", ["games", "categories", "expansions", "blueprints"])
def test_get_only_fixed_origin_and_bounded_body(kind):
    response = Response(json.dumps({"array": [{"id": 123}]}).encode())
    opener = Mock()
    opener.open.return_value = response
    client = CardTraderCatalogClient("synthetic", opener=opener)
    options = {"expansion_id": 456} if kind == "blueprints" else {}
    assert client.collection(kind, **options) == [{"id": 123}]
    request = opener.open.call_args.args[0]
    assert request.get_method() == "GET"
    assert request.full_url == BASE_URL + (
        "blueprints/export?expansion_id=456" if kind == "blueprints" else kind
    )
    assert request.get_header("Authorization") == "Bearer synthetic"
    assert response.bound == MAX_RESPONSE_BYTES + 1


@pytest.mark.parametrize("identifier", [None, 0, -1, True, "456", 2**63])
def test_invalid_expansion(identifier):
    with pytest.raises(CardTraderCatalogError, match=r"^invalid_expansion_id$"):
        CardTraderCatalogClient("synthetic").collection("blueprints", expansion_id=identifier)


@pytest.mark.parametrize("kind,identifier", [("products", None), ("../info", None), ("games", 123)])
def test_non_catalog_paths_rejected(kind, identifier):
    with pytest.raises(CardTraderCatalogError, match=r"^unsupported_catalog_request$"):
        CardTraderCatalogClient("synthetic").collection(kind, expansion_id=identifier)


@pytest.mark.parametrize(
    "response,reason",
    [
        (Response(b"private", 201), "unexpected_status"),
        (Response(b"private"), "invalid_json"),
        (Response(b"\xff"), "invalid_json"),
        (Response(b"x" * (MAX_RESPONSE_BYTES + 1)), "response_too_large"),
    ],
)
def test_malformed_responses_fail_without_echo(response, reason):
    opener = Mock()
    opener.open.return_value = response
    with pytest.raises(CardTraderCatalogError, match="^" + reason + "$"):
        CardTraderCatalogClient("synthetic", opener=opener).collection("games")


@pytest.mark.parametrize(
    "error,status",
    [
        (urllib.error.HTTPError("https://private", 403, "private", {}, None), 403),
        (urllib.error.URLError("private"), None),
        (TimeoutError("private"), None),
        (http.client.BadStatusLine("private"), None),
        (http.client.IncompleteRead(b"private"), None),
    ],
)
def test_network_errors_do_not_expose_values(error, status):
    opener = Mock()
    opener.open.side_effect = error
    with pytest.raises(CardTraderCatalogError, match=r"^request_failed$") as caught:
        CardTraderCatalogClient("synthetic", opener=opener).collection("games")
    assert caught.value.http_status == status
    assert caught.value.__suppress_context__


def test_redirects_are_not_followed():
    assert _NoRedirect().redirect_request(None, None, 302, "", {}, "https://other") is None
