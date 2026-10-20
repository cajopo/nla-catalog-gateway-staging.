"""Boundary regressions for new metadata-filter and facet validation branches."""

from dataclasses import replace

import pytest

import test_metadata_filters as metadata
import test_runtime_api as api
from nla_catalog_gateway import runtime_api
from nla_catalog_gateway.card_metadata import CardMetadataV1
from nla_catalog_gateway.pagination import UnsupportedPaginationRequestError
from nla_catalog_gateway.runtime_api import CatalogRequestEnvelopeV1, RuntimeApiContractError
from nla_catalog_gateway.runtime_contract import (
    CatalogFiltersV1,
    RequestFamily,
    RuntimeContractError,
)
from test_runtime_metadata_facets import envelope, facet_values
from test_runtime_suggestions import _request

metadata_projection = metadata.metadata_projection


def test_metadata_facets_reject_non_single_browse_without_query(metadata_projection):
    with pytest.raises(UnsupportedPaginationRequestError):
        metadata_projection.metadata_facets(api._request(family=RequestFamily.ALL, query=None))


@pytest.mark.parametrize(
    "malformed",
    [
        None,
        {"dimension": "expansionCode", "values": {}, "missingValueCount": 0},
        {"dimension": "expansionCode", "values": [None], "missingValueCount": 0},
    ],
)
def test_facet_wire_rejects_wrong_nested_types(malformed):
    document = envelope(facet_values()).as_dict()
    document["facets"][0] = malformed
    with pytest.raises(RuntimeApiContractError):
        runtime_api.CatalogResponseEnvelopeV1.from_json_bytes(
            runtime_api._canonical_json_bytes(document)
        )


@pytest.mark.parametrize("family", [None, "unknown-family"])
def test_unknown_family_is_invalid_not_metadata_incompatibility(family):
    document = CatalogRequestEnvelopeV1(_request(), None).as_dict()
    document["request"]["productFamily"] = family
    document["request"]["filters"]["expansionCode"] = "SET"
    with pytest.raises(RuntimeApiContractError) as caught:
        CatalogRequestEnvelopeV1.from_json_bytes(runtime_api._canonical_json_bytes(document))
    assert not isinstance(caught.value, runtime_api.IncompatibleCatalogRequestError)


@pytest.mark.parametrize("field", ["expansion_code", "rarity"])
@pytest.mark.parametrize("card_metadata", [None, CardMetadataV1(None, "OTHER", None, "Other")])
def test_page_contract_rejects_item_not_matching_metadata_filter(field, card_metadata):
    chosen = replace(_request(), filters=CatalogFiltersV1(None, None, **{field: "SELECTED"}))
    page = api._page(chosen)
    item = replace(api._page(_request(), terminal=False).items[0], card_metadata=card_metadata)
    with pytest.raises(RuntimeContractError, match="violates the metadata filter"):
        replace(page, items=(item,), returned_product_count=1, returned_variant_count=1)
