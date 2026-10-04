"""Optional metadata facets on signed, generation-pinned catalog responses."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

import test_runtime_api as api
import test_runtime_api_integration as integration
import test_runtime_suggestions as suggestions
from nla_catalog_gateway import runtime_api
from nla_catalog_gateway.facets import ContextualFacet, FacetDimension, FacetValueCount
from nla_catalog_gateway.pagination import CatalogProjection
from nla_catalog_gateway.runtime_api import (
    CatalogRequestEnvelopeV1,
    CatalogResponseEnvelopeV1,
    RequestCancelled,
    RequestDeadlineExceeded,
    RuntimeApiContractError,
    RuntimeHttpRequest,
)
from nla_catalog_gateway.runtime_contract import CatalogFiltersV1, RequestFamily
from nla_catalog_gateway.taxonomy import Game
from test_runtime_suggestions import _request

http_case = suggestions.http_case


def facet_values():
    return (
        ContextualFacet(FacetDimension.EXPANSION_CODE, (FacetValueCount("EXP", 4),)),
        ContextualFacet(FacetDimension.RARITY, (FacetValueCount("Rare", 4),)),
    )


def envelope(facets=None):
    return CatalogResponseEnvelopeV1(api._page(_request()), None, facets=facets)


def call_facets(case, chosen=None, *, cursor=None, enabled=True, signed=True, suggestions=False):
    body = CatalogRequestEnvelopeV1(
        chosen or _request(), cursor, include_facets=enabled, include_suggestions=suggestions
    ).to_json_bytes()
    return case.service.catalog(
        RuntimeHttpRequest(
            method="POST",
            path="/proxy/catalog",
            raw_query=case.signed_query if signed else b"",
            headers=((b"content-type", b"application/json"),),
            body_chunks=(body,),
        )
    )


def test_metadata_facet_request_is_opt_in_and_legacy_bytes_are_unchanged():
    legacy = CatalogRequestEnvelopeV1(_request(), None)
    assert legacy.to_json_bytes() == runtime_api._canonical_json_bytes(
        {"contractVersion": 1, "cursor": None, "request": _request().as_dict()}
    )
    enabled = replace(legacy, include_facets=True)
    assert CatalogRequestEnvelopeV1.from_json_bytes(enabled.to_json_bytes()) == enabled
    assert enabled.as_dict()["includeFacets"] is True
    both = replace(enabled, include_suggestions=True)
    assert CatalogRequestEnvelopeV1.from_json_bytes(both.to_json_bytes()) == both
    assert "includeFacets" not in replace(enabled, include_facets=False).as_dict()


@pytest.mark.parametrize("flag", [None, 0, 1, "true", [], {}])
def test_reject_non_boolean_metadata_facet_option(flag):
    with pytest.raises(RuntimeApiContractError):
        CatalogRequestEnvelopeV1(_request(), None, include_facets=flag)
    document = CatalogRequestEnvelopeV1(_request(), None).as_dict()
    document["includeFacets"] = flag
    with pytest.raises(RuntimeApiContractError):
        CatalogRequestEnvelopeV1.from_json_bytes(runtime_api._canonical_json_bytes(document))


@pytest.mark.parametrize(
    "family", [RequestFamily.ALL, RequestFamily.SEALED, RequestFamily.ACCESSORY]
)
def test_metadata_facets_only_accept_single_family(family):
    with pytest.raises(runtime_api.IncompatibleCatalogRequestError):
        CatalogRequestEnvelopeV1(api._request(family=family), None, include_facets=True)
    enabled = CatalogRequestEnvelopeV1(_request(), api.OPAQUE_CURSOR, include_facets=True)
    assert CatalogRequestEnvelopeV1.from_json_bytes(enabled.to_json_bytes()) == enabled
    # Browsing without a text query still needs the complete set choices.
    assert CatalogRequestEnvelopeV1(_request(None), None, include_facets=True).include_facets


def test_metadata_facet_response_roundtrip_and_legacy_omission():
    response = envelope(facet_values())
    assert response.as_dict()["facets"] == [
        {
            "dimension": "expansionCode",
            "values": [{"value": "EXP", "count": 4}],
            "missingValueCount": 0,
        },
        {"dimension": "rarity", "values": [{"value": "Rare", "count": 4}], "missingValueCount": 0},
    ]
    assert CatalogResponseEnvelopeV1.from_json_bytes(response.to_json_bytes()) == response
    legacy = envelope()
    assert set(legacy.as_dict()) == {"contractVersion", "page", "nextCursor"}
    assert (
        legacy.to_json_bytes()
        == CatalogResponseEnvelopeV1(api._page(_request()), None).to_json_bytes()
    )


@pytest.mark.parametrize("value", [None, {}, [], [{}], [None], "facets"])
def test_reject_malformed_facet_wire_containers(value):
    document = envelope().as_dict()
    document["facets"] = value
    with pytest.raises(RuntimeApiContractError):
        CatalogResponseEnvelopeV1.from_json_bytes(runtime_api._canonical_json_bytes(document))


@pytest.mark.parametrize(
    "change",
    [
        {"dimension": "inStock"},
        {"values": [{"value": "EXP", "count": True}]},
        {"values": [{"value": "EXP", "count": -1}]},
        {"values": [{"value": "", "count": 1}]},
        {"values": [{"value": "x" * 1025, "count": 1}]},
        {"values": [{"value": "bad\x00", "count": 1}]},
        {"values": [{"value": "EXP", "count": 1, "extra": 1}]},
        {"values": [{"value": "EXP", "count": 1}, {"value": "EXP", "count": 2}]},
        {"values": [{"value": "Z", "count": 1}, {"value": "A", "count": 1}]},
        {"missingValueCount": True},
        {"missingValueCount": -1},
        {"extra": "unknown"},
    ],
)
def test_reject_malformed_metadata_facet_fields(change):
    document = envelope(facet_values()).as_dict()
    document["facets"][0].update(change)
    with pytest.raises(RuntimeApiContractError):
        CatalogResponseEnvelopeV1.from_json_bytes(runtime_api._canonical_json_bytes(document))


def test_reject_wrong_dimension_order_and_revalidate_output():
    document = envelope(facet_values()).as_dict()
    document["facets"].reverse()
    with pytest.raises(RuntimeApiContractError):
        CatalogResponseEnvelopeV1.from_json_bytes(runtime_api._canonical_json_bytes(document))
    response = envelope(facet_values())
    object.__setattr__(response, "facets", (object(),))
    with pytest.raises(RuntimeApiContractError):
        response.to_json_bytes()


@pytest.mark.parametrize("requested", [True, False])
def test_reject_unsolicited_or_missing_backend_facets(requested):
    result = runtime_api.CatalogLeaseResult(
        api._page(_request()), None, facets=None if requested else facet_values()
    )
    with pytest.raises(runtime_api._OutputContractFailure):
        runtime_api._validated_result(
            result,
            request=_request(),
            dataset_generation=api.GENERATION_A,
            cursor_char_limit=runtime_api.MAX_CURSOR_CHARS,
            request_body_byte_limit=runtime_api.MAX_REQUEST_BODY_BYTES,
            include_facets=requested,
        )


def test_signed_http_facets_are_complete_scoped_and_optional(http_case):
    case, _ = http_case
    response = call_facets(case, _request(page_size=1), suggestions=True)
    assert response.status == 200
    parsed = CatalogResponseEnvelopeV1.from_json_bytes(response.body)
    assert parsed.page.returned_product_count == 1
    assert parsed.facets == facet_values()  # Counts all four, not just the first page.
    assert sum(value.print_count for value in parsed.suggestions) == 4
    next_page = call_facets(case, _request(page_size=1), cursor=parsed.next_cursor, enabled=False)
    assert next_page.status == 200
    assert "facets" not in json.loads(next_page.body)
    next_with_facets = call_facets(case, _request(page_size=1), cursor=parsed.next_cursor)
    assert next_with_facets.status == 200
    next_parsed = CatalogResponseEnvelopeV1.from_json_bytes(next_with_facets.body)
    assert next_parsed.page.items[0].product_gid == "gid://shopify/Product/2"
    assert next_parsed.facets == facet_values()
    assert next_parsed.page.dataset_generation == parsed.page.dataset_generation
    foreign = call_facets(case, replace(_request(), game=Game.POKEMON))
    assert foreign.status == 200
    assert [f["values"][0]["count"] for f in json.loads(foreign.body)["facets"]] == [1, 1]
    sold = call_facets(case, _request(in_stock=False))
    assert [f["values"][0]["count"] for f in json.loads(sold.body)["facets"]] == [3, 3]
    legacy = call_facets(case, enabled=False)
    assert set(json.loads(legacy.body)) == {"contractVersion", "page", "nextCursor"}
    denied = call_facets(case, signed=False)
    assert denied.status == 401
    assert "facets" not in json.loads(denied.body)


def test_http_selected_absent_set_stays_visible_with_zero_count(http_case):
    case, _ = http_case
    chosen = replace(_request(), filters=CatalogFiltersV1(None, None, expansion_code="ABSENT"))
    response = call_facets(case, chosen)
    assert response.status == 200
    parsed = CatalogResponseEnvelopeV1.from_json_bytes(response.body)
    assert parsed.page.items == ()
    assert [(v.value, v.count) for v in parsed.facets[0].values] == [("ABSENT", 0), ("EXP", 4)]
    assert parsed.facets[1].values == ()


@pytest.mark.parametrize("error", [RequestCancelled(), RequestDeadlineExceeded(), RuntimeError()])
def test_metadata_facet_failure_never_returns_partial_success(http_case, monkeypatch, error):
    case, _ = http_case

    def fail(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(CatalogProjection, "metadata_facets", fail)
    if isinstance(error, RequestCancelled):
        with pytest.raises(RequestCancelled) as caught:
            call_facets(case)
        assert caught.value is error
    else:
        response = call_facets(case)
        assert response.status == 503
        assert "facets" not in json.loads(response.body)


def test_metadata_facets_use_leased_generation_during_activation(http_case, tmp_path, monkeypatch):
    case, _ = http_case
    changed = tuple(
        replace(record, card_metadata=replace(record.card_metadata, expansion_code="NEW"))
        for record in case.records
    )
    new_case = integration._bound_case(tmp_path, "new-facets", changed, "b" * 64)
    original = CatalogProjection.metadata_facets

    def activate_then_count(projection, request, **kwargs):
        case.backend.activate(
            new_case.verified, new_case.projection, new_case.codec, new_case.evidence
        )
        return original(projection, request, **kwargs)

    monkeypatch.setattr(CatalogProjection, "metadata_facets", activate_then_count)
    response = call_facets(case)
    assert response.status == 200
    parsed = CatalogResponseEnvelopeV1.from_json_bytes(response.body)
    assert (
        parsed.page.dataset_generation
        == case.verified.generation.dataset_manifest.dataset_generation
    )
    assert parsed.facets == facet_values()
    assert case.backend.active_generation == new_case.backend.active_generation


def test_cursor_metadata_facets_keep_retained_generation_after_activation(http_case, tmp_path):
    case, _ = http_case
    chosen = _request(page_size=1)
    first = CatalogResponseEnvelopeV1.from_json_bytes(call_facets(case, chosen).body)
    changed = tuple(
        replace(record, card_metadata=replace(record.card_metadata, expansion_code="NEW"))
        for record in case.records
    )
    new_case = integration._bound_case(tmp_path, "retained-facets", changed, "b" * 64)
    case.backend.activate(new_case.verified, new_case.projection, new_case.codec, new_case.evidence)
    response = call_facets(case, chosen, cursor=first.next_cursor)
    assert response.status == 200
    parsed = CatalogResponseEnvelopeV1.from_json_bytes(response.body)
    assert parsed.page.dataset_generation == first.page.dataset_generation
    assert parsed.page.items[0].product_gid == "gid://shopify/Product/2"
    assert parsed.facets == facet_values()
    assert case.backend.active_generation != parsed.page.dataset_generation


def test_invalid_or_unretained_cursor_fails_before_metadata_read(http_case, tmp_path, monkeypatch):
    case, _ = http_case
    chosen = _request(page_size=1)
    first = CatalogResponseEnvelopeV1.from_json_bytes(call_facets(case, chosen).body)
    changed = tuple(replace(record, canonical_card_name="New Bolt") for record in case.records)
    foreign = integration._bound_case(tmp_path, "foreign-facets", changed, "b" * 64)
    control = integration._control()
    lease = foreign.backend.acquire(control=control)
    try:
        foreign_cursor = lease.fetch_page(chosen, None, control=control).next_cursor
    finally:
        lease.close()
    assert foreign_cursor is not None
    reads = []

    def forbidden(*args, **kwargs):
        reads.append(True)
        raise AssertionError("invalid cursor must precede facet reads")

    monkeypatch.setattr(CatalogProjection, "metadata_facets", forbidden)
    for request, cursor, expected_code in (
        (chosen, api.OPAQUE_CURSOR, "invalid_cursor"),
        (replace(chosen, query="different"), first.next_cursor, "cursor_context_mismatch"),
        (chosen, foreign_cursor, "restart_required"),
    ):
        response = call_facets(case, request, cursor=cursor)
        assert response.status in (400, 409)
        assert json.loads(response.body)["code"] == expected_code
        assert "facets" not in json.loads(response.body)
    assert reads == []
