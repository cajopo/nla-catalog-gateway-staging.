"""HTTP search suggestions: scoped, bounded and pinned with the result page."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

import test_app_proxy_security as proxy
import test_generation_bundle as bundle
import test_runtime_api as api
import test_runtime_api_integration as integration
import test_runtime_server as asgi
from nla_catalog_gateway import runtime_api
from nla_catalog_gateway.canonical_search import SingleCardSuggestion
from nla_catalog_gateway.card_metadata import CardMetadataV1
from nla_catalog_gateway.pagination import CatalogProjection
from nla_catalog_gateway.runtime_api import (
    AppProxyVerifierAuthorizer,
    CatalogRequestEnvelopeV1,
    CatalogResponseEnvelopeV1,
    RequestCancelled,
    RequestDeadlineExceeded,
    RuntimeApiContractError,
    RuntimeCatalogService,
    RuntimeHttpRequest,
)
from nla_catalog_gateway.runtime_contract import ProductStatus, RequestFamily
from nla_catalog_gateway.taxonomy import Game


def _request(query="bolt", **kwargs):
    return integration._request(family=RequestFamily.SINGLE, query=query, **kwargs)


def _suggestion(**kwargs):
    return replace(SingleCardSuggestion("Bolt", "bolt", 2, 0), **kwargs)


_DEFAULT_SUGGESTIONS = (_suggestion(),)


def _envelope(suggestions=_DEFAULT_SUGGESTIONS):
    return CatalogResponseEnvelopeV1(api._page(_request()), None, suggestions=suggestions)


def test_suggestion_wire_round_trip_and_legacy_omission():
    envelope = _envelope()
    wire = envelope.to_json_bytes()
    document = json.loads(wire)
    assert document["suggestions"] == [
        {"canonicalCardName": "Bolt", "matchingProductCount": 2, "availableProductCount": 0}
    ]
    assert CatalogResponseEnvelopeV1.from_json_bytes(wire) == envelope
    assert json.loads(_envelope(()).to_json_bytes())["suggestions"] == []
    assert "suggestions" not in json.loads(_envelope(None).to_json_bytes())
    assert b"normalizedCardName" not in wire


@pytest.mark.parametrize(
    "suggestions",
    [[], (_suggestion(),) * 11, (object(),), (_suggestion(),) * 2],
)
def test_reject_invalid_suggestion_container(suggestions):
    with pytest.raises(RuntimeApiContractError):
        _envelope(suggestions)


@pytest.mark.parametrize(
    "changes",
    [
        {"canonical_card_name": None},
        {"canonical_card_name": "\ud800"},
        {"canonical_card_name": " "},
        {"canonical_card_name": "x" * 1025},
        {"normalized_card_name": "incorrect"},
        {"print_count": True},
        {"print_count": 0},
        {"available_print_count": False},
        {"available_print_count": -1},
        {"available_print_count": 3},
    ],
)
def test_reject_invalid_suggestion_fields(changes):
    with pytest.raises(RuntimeApiContractError):
        _envelope((_suggestion(**changes),))


@pytest.mark.parametrize("catalog_request", [api._request(), _request("  ")])
def test_reject_suggestions_outside_search(catalog_request):
    with pytest.raises(RuntimeApiContractError):
        CatalogResponseEnvelopeV1(api._page(catalog_request), None, suggestions=())


@pytest.mark.parametrize(
    "value",
    [
        None,
        {},
        [None],
        [{}],
        [{}] * 11,
        [{"canonicalCardName": 7, "matchingProductCount": 1, "availableProductCount": 0}],
        [{"canonicalCardName": "Bolt", "matchingProductCount": 0, "availableProductCount": 0}],
    ],
)
def test_reject_malformed_wire_suggestions(value):
    document = _envelope().as_dict()
    document["suggestions"] = value
    with pytest.raises(RuntimeApiContractError):
        CatalogResponseEnvelopeV1.from_json_bytes(runtime_api._canonical_json_bytes(document))


def test_revalidate_suggestions_on_output():
    envelope = _envelope()
    object.__setattr__(envelope, "suggestions", (object(),))
    with pytest.raises(RuntimeApiContractError, match="response envelope is invalid"):
        envelope.to_json_bytes()


def test_request_suggestions_are_explicit_opt_in():
    legacy = CatalogRequestEnvelopeV1(_request(), None)
    assert "includeSuggestions" not in json.loads(legacy.to_json_bytes())
    enabled = replace(legacy, include_suggestions=True)
    assert CatalogRequestEnvelopeV1.from_json_bytes(enabled.to_json_bytes()) == enabled
    assert json.loads(enabled.to_json_bytes())["includeSuggestions"] is True


@pytest.mark.parametrize("flag", [None, 1, "true", []])
def test_reject_non_boolean_suggestion_option(flag):
    document = CatalogRequestEnvelopeV1(_request(), None).as_dict()
    document["includeSuggestions"] = flag
    with pytest.raises(RuntimeApiContractError):
        CatalogRequestEnvelopeV1.from_json_bytes(runtime_api._canonical_json_bytes(document))


@pytest.mark.parametrize(
    "catalog_request,cursor",
    [(api._request(), None), (_request("  "), None), (_request(), api.OPAQUE_CURSOR)],
)
def test_reject_suggestion_option_outside_first_search_page(catalog_request, cursor):
    with pytest.raises(runtime_api.IncompatibleCatalogRequestError):
        CatalogRequestEnvelopeV1(catalog_request, cursor, include_suggestions=True)


@pytest.mark.parametrize("requested", [True, False])
def test_reject_unsolicited_or_missing_backend_suggestions(requested):
    result = runtime_api.CatalogLeaseResult(
        api._page(_request()), None, None if requested else (_suggestion(),)
    )
    with pytest.raises(runtime_api._OutputContractFailure):
        runtime_api._validated_result(
            result,
            request=_request(),
            dataset_generation=api.GENERATION_A,
            cursor_char_limit=runtime_api.MAX_CURSOR_CHARS,
            request_body_byte_limit=runtime_api.MAX_REQUEST_BODY_BYTES,
            include_suggestions=requested,
        )


@pytest.fixture
def http_case(tmp_path):
    def card(number, name, stock=0):
        record = bundle._product(str(number))
        return replace(
            record,
            canonical_card_name=name,
            total_inventory=stock,
            variants=(replace(record.variants[0], sku="SET-019", inventory_quantity=stock),),
            card_metadata=CardMetadataV1("MET-007", "EXP", "Set name", "Rare"),
        )

    records = (
        card(1, "Bolt"),
        card(2, "BOLT", 2),
        card(3, "Bolt Adept"),
        card(4, "Thunder Bolt"),
        replace(card(5, "Foreign Bolt"), game=Game.POKEMON),
        replace(card(6, "Hidden Bolt"), online_store_published=False),
        replace(card(7, "Draft Bolt"), shopify_status=ProductStatus.DRAFT),
        replace(card(8, "Other card"), game=Game.YUGIOH),
        replace(card(9, "Other card"), game=Game.ONE_PIECE),
    )
    case = integration._bound_case(tmp_path, "suggestions", records, "a" * 64)
    verifier = proxy._verifier(config=proxy._config(allowed_shops=frozenset({bundle.SHOP})))
    service = RuntimeCatalogService(
        expected_shop_domain=bundle.SHOP,
        backend=case.backend,
        capability_gate=case.gate,
        authorizer=AppProxyVerifierAuthorizer(verifier),
        endpoint_path="/proxy/catalog",
    )
    # Real runtime gates, App Proxy signatures and evidence-bound leases: no overrides.
    assert service.readiness().status == 200
    case.service = service
    signed = proxy._signed_query(
        [(name, bundle.SHOP if name == "shop" else value) for name, value in proxy._base_pairs()]
    )
    case.signed_query = signed

    def call(request, cursor=None, *, raw_query=signed, include_suggestions=None):
        if include_suggestions is None:
            include_suggestions = cursor is None and bool((request.query or "").strip())
        body = CatalogRequestEnvelopeV1(
            request, cursor, include_suggestions=include_suggestions
        ).to_json_bytes()
        return service.catalog(
            RuntimeHttpRequest(
                method="POST",
                path="/proxy/catalog",
                raw_query=raw_query,
                headers=((b"content-type", b"application/json"),),
                body_chunks=(body,),
            )
        )

    return case, call


@pytest.mark.parametrize("version", [1, 2.0, True])
def test_runtime_rejects_obsolete_or_invalid_evidence_version(http_case, version):
    case, call = http_case
    object.__setattr__(case.evidence, "verification_version", version)
    assert case.service.readiness().status == 503
    assert call(_request()).status == 503
    with pytest.raises(RuntimeApiContractError):
        case.backend.activate(case.verified, case.projection, case.codec, case.evidence)


def test_asgi_serves_verified_catalog_without_gate_overrides(http_case):
    case, _ = http_case
    app = asgi.create_runtime_app(case.service, app_proxy_path="/proxy/catalog")
    assert asgi._status(asgi._invoke(app, method="GET", path="/readyz")) == 200
    body = CatalogRequestEnvelopeV1(
        _request("SET-019"), None, include_suggestions=True
    ).to_json_bytes()
    sent = asgi._invoke(
        app,
        path="/proxy/catalog",
        query=case.signed_query,
        headers=((b"content-type", b"application/json"),),
        messages=({"type": "http.request", "body": body},),
    )
    assert asgi._status(sent) == 200
    response = CatalogResponseEnvelopeV1.from_json_bytes(asgi._body(sent))
    assert response.page.returned_product_count == 4
    assert sum(s.print_count for s in response.suggestions) == 4
    assert sum(s.available_print_count for s in response.suggestions) == 1
    unsigned = asgi._invoke(
        app,
        path="/proxy/catalog",
        headers=((b"content-type", b"application/json"),),
        messages=({"type": "http.request", "body": body},),
    )
    assert asgi._status(unsigned) == 401
    assert asgi._status(asgi._invoke(app, path="/catalog", query=case.signed_query)) == 400


@pytest.mark.parametrize("query", ["SET019", "SET-019", "MET007", "MET-007"])
def test_http_code_spellings_share_pages_suggestions_and_stock_scope(http_case, query):
    _, call = http_case
    first = call(_request(query, page_size=1))
    assert first.status == 200
    parsed = CatalogResponseEnvelopeV1.from_json_bytes(first.body)
    assert parsed.page.items[0].product_gid == "gid://shopify/Product/1"
    assert sum(s.print_count for s in parsed.suggestions) == 4
    assert sum(s.available_print_count for s in parsed.suggestions) == 1
    seen = [parsed.page.items[0].product_gid]
    while parsed.next_cursor is not None:
        response = call(_request(query, page_size=1), parsed.next_cursor)
        assert response.status == 200
        parsed = CatalogResponseEnvelopeV1.from_json_bytes(response.body)
        assert parsed.suggestions is None
        seen.extend(item.product_gid for item in parsed.page.items)
    assert seen == [f"gid://shopify/Product/{i}" for i in range(1, 5)]
    stock = call(_request(query, in_stock=True))
    assert stock.status == 200
    parsed = CatalogResponseEnvelopeV1.from_json_bytes(stock.body)
    assert [item.product_gid for item in parsed.page.items] == ["gid://shopify/Product/2"]
    assert sum(s.print_count for s in parsed.suggestions) == 1


def test_http_suggestions_same_scope_counts_and_first_page_only(http_case):
    _, call = http_case
    first = call(_request(page_size=1))
    assert first.status == 200
    parsed = CatalogResponseEnvelopeV1.from_json_bytes(first.body)
    assert [
        (s.normalized_card_name, s.print_count, s.available_print_count) for s in parsed.suggestions
    ] == [("bolt", 2, 1), ("bolt adept", 1, 0), ("thunder bolt", 1, 0)]
    next_page = call(_request(page_size=1), parsed.next_cursor)
    assert next_page.status == 200
    assert "suggestions" not in json.loads(next_page.body)
    sold = json.loads(call(_request(in_stock=False)).body)
    assert all(s["availableProductCount"] == 0 for s in sold["suggestions"])
    assert sum(s["matchingProductCount"] for s in sold["suggestions"]) == 3
    by_code = json.loads(call(_request("SET-019")).body)
    assert sum(s["matchingProductCount"] for s in by_code["suggestions"]) == 4
    pokemon = json.loads(call(replace(_request(), game=Game.POKEMON)).body)
    assert [s["canonicalCardName"] for s in pokemon["suggestions"]] == ["Foreign Bolt"]
    assert json.loads(call(_request("no match")).body)["suggestions"] == []
    assert "suggestions" not in json.loads(call(_request("  ")).body)
    legacy = json.loads(call(_request(), include_suggestions=False).body)
    assert set(legacy) == {"contractVersion", "nextCursor", "page"}
    rejected = call(_request(), raw_query=b"invalid")
    assert rejected.status == 401
    assert "suggestions" not in json.loads(rejected.body)


def test_http_collector_number_metadata_suggestions_and_pagination(http_case):
    _, call = http_case
    selected = _request("met-00", page_size=1)
    cursor = None
    found = []
    while True:
        response = call(selected, cursor)
        assert response.status == 200
        parsed = CatalogResponseEnvelopeV1.from_json_bytes(response.body)
        if cursor is None:
            assert sum(s.print_count for s in parsed.suggestions) == 4
            assert sum(s.available_print_count for s in parsed.suggestions) == 1
        found.extend(item.product_gid for item in parsed.page.items)
        assert all(item.card_metadata.collector_number == "MET-007" for item in parsed.page.items)
        cursor = parsed.next_cursor
        if cursor is None:
            break
    assert found == [f"gid://shopify/Product/{n}" for n in (1, 2, 3, 4)]
    assert json.loads(call(_request("Set name")).body)["page"]["items"] == []


@pytest.mark.parametrize("error", [RequestCancelled(), RequestDeadlineExceeded(), RuntimeError()])
def test_suggestion_failure_never_returns_partial_success(http_case, monkeypatch, error):
    _, call = http_case

    def fail(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(CatalogProjection, "suggest", fail)
    if isinstance(error, RequestCancelled):
        with pytest.raises(RequestCancelled) as caught:
            call(_request())
        assert caught.value is error
    else:
        response = call(_request())
        assert response.status == 503
        assert "suggestions" not in json.loads(response.body)


def test_suggestions_use_the_leased_generation_during_activation(http_case, tmp_path, monkeypatch):
    case, call = http_case
    changed = tuple(replace(r, canonical_card_name="New name") for r in case.records)
    new_case = integration._bound_case(tmp_path, "new-suggestions", changed, "b" * 64)
    original = CatalogProjection.suggest

    def activate_then_suggest(projection, request, **kwargs):
        case.backend.activate(
            new_case.verified,
            new_case.projection,
            new_case.codec,
            new_case.evidence,
        )
        return original(projection, request, **kwargs)

    monkeypatch.setattr(CatalogProjection, "suggest", activate_then_suggest)
    response = call(_request())
    assert response.status == 200
    parsed = CatalogResponseEnvelopeV1.from_json_bytes(response.body)
    assert (
        parsed.page.dataset_generation
        == case.verified.generation.dataset_manifest.dataset_generation
    )
    assert parsed.suggestions[0].normalized_card_name == "bolt"
    assert case.backend.active_generation == new_case.backend.active_generation
