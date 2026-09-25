from copy import deepcopy

import pytest

from nla_catalog_gateway.shopify_identity_changes import (
    RECENT_IDENTITIES_QUERY,
    read_identity_changes,
)

SINCE = "2026-09-25T09:32:46Z"


def node(identifier=1):
    return {
        "id": f"gid://shopify/Product/{identifier}",
        "updatedAt": SINCE,
        "syncProductId": {"type": "number_integer", "value": "123"},
        "powertoolsId": {"type": "single_line_text_field", "value": "123"},
    }


def page(nodes, more=False, cursor=None):
    return {"products": {"nodes": nodes, "pageInfo": {"hasNextPage": more, "endCursor": cursor}}}


def test_reads_all_statuses_and_all_pages_without_creation_approval():
    calls = []
    pauses = []
    pages = iter([page([node()], True, "one"), page([node(2)])])

    def graphql(query, variables):
        calls.append((query, variables))
        return next(pages)

    result = read_identity_changes(graphql, SINCE, pause=pauses.append)
    assert len(result["products"]) == 2
    assert result["pages"] == 2
    assert result["creationApproved"] is False
    assert result["products"][0]["syncSourceId"] == "123"
    assert result["products"][0]["powerToolsSourceId"] == "123"
    assert calls[0] == (
        RECENT_IDENTITIES_QUERY,
        {"query": f"status:active,draft,archived,unlisted updated_at:>='{SINCE}'", "after": None},
    )
    assert calls[1][1]["after"] == "one"
    assert pauses == [2.0]
    assert "mutation" not in RECENT_IDENTITIES_QUERY


def test_empty_result_and_missing_identifiers_are_distinct():
    assert read_identity_changes(lambda *_: page([]), SINCE)["products"] == []
    product = node()
    product.update(syncProductId=None, powertoolsId=None)
    result = read_identity_changes(lambda *_: page([product]), SINCE)
    assert result["products"][0]["syncSourceId"] is None


@pytest.mark.parametrize(
    "since", ["bad", "2026-09-25", "9999-01-01T00:00:00Z", "2026-02-30T00:00:00Z", None]
)
def test_invalid_date_never_calls_shopify(since):
    with pytest.raises(ValueError):
        read_identity_changes(lambda *_: pytest.fail("API called"), since)


@pytest.mark.parametrize("limit", [0, 101, True, 1.5])
def test_invalid_limit_never_calls_shopify(limit):
    with pytest.raises(ValueError):
        read_identity_changes(lambda *_: pytest.fail("API called"), SINCE, max_pages=limit)


@pytest.mark.parametrize(
    "change",
    [
        {"id": "wrong"},
        {"id": "gid://shopify/Product/0"},
        {"updatedAt": "2026-09-25T09:32:45Z"},
        {"syncProductId": {"type": "single_line_text_field", "value": "123"}},
        {"powertoolsId": {"type": "single_line_text_field", "value": ""}},
    ],
)
def test_invalid_product_aborts(change):
    product = node()
    product.update(change)
    with pytest.raises(ValueError):
        read_identity_changes(lambda *_: page([product]), SINCE)


@pytest.mark.parametrize(
    "response",
    [
        page([], True, "one"),
        page([node()], True, ""),
        page([node()], True, None),
        page([node()] * 51),
        page({}, False),
        page([], 1),
    ],
)
def test_invalid_page_aborts(response):
    with pytest.raises(ValueError):
        read_identity_changes(lambda *_: deepcopy(response), SINCE)


def test_duplicate_gid_rejects_drifting_pages():
    pages = iter([page([node()], True, "one"), page([node()])])
    with pytest.raises(ValueError, match="inconsistent_identity_page"):
        read_identity_changes(lambda *_: next(pages), SINCE, pause=lambda _: None)


def test_repeated_cursor_aborts():
    pages = iter([page([node()], True, "same"), page([node(2)], True, "same")])
    with pytest.raises(ValueError, match="invalid_identity_cursor"):
        read_identity_changes(lambda *_: next(pages), SINCE, pause=lambda _: None)


def test_page_limit_never_returns_partial_result():
    with pytest.raises(ValueError, match="requires_fresh_baseline"):
        read_identity_changes(lambda *_: page([node()], True, "one"), SINCE, max_pages=1)


def test_api_failure_is_not_empty_success():
    def graphql(*_):
        raise RuntimeError("transport failure")

    with pytest.raises(RuntimeError):
        read_identity_changes(graphql, SINCE)
