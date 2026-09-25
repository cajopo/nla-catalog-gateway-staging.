"""Read recent Shopify identities; never interpret snapshot absence as write approval."""

import re
from collections.abc import Callable
from datetime import UTC, datetime
from time import sleep

RECENT_IDENTITIES_QUERY = """
query NlaRecentProductIdentities($query: String!, $after: String) {
  products(first: 50, sortKey: UPDATED_AT, query: $query, after: $after) {
    nodes {
      id
      updatedAt
      syncProductId: metafield(namespace: "sync", key: "productid") { type value }
      powertoolsId: metafield(namespace: "powertools", key: "id") { type value }
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""


def _timestamp(value: object) -> datetime:
    if (
        not isinstance(value, str)
        or re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z", value) is None
    ):
        raise ValueError("invalid_identity_timestamp")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _identity(node: dict, field: str, expected_type: str) -> str | None:
    value = node[field]
    if value is None:
        return None
    if (
        not isinstance(value, dict)
        or value.get("type") != expected_type
        or not isinstance(value.get("value"), str)
        or not value["value"]
    ):
        raise ValueError("invalid_identity_metafield")
    return value["value"]


def read_identity_changes(
    graphql: Callable[[str, dict], dict],
    since: str,
    *,
    max_pages: int = 100,
    pause: Callable[[float], None] = sleep,
) -> dict:
    """Collect all pages or fail without returning a partial successful result.

    Use the baseline capture START (not completion) as the inclusive lower bound.
    Results include all product statuses. They can reveal duplicates absent from
    the baseline, but are not an atomic snapshot or permission to create: concurrent
    writes, search indexing lag and metadata update semantics remain relevant.
    On a limit/error obtain a fresh complete baseline; never treat a prefix as all.
    """
    lower_bound = _timestamp(since)
    if lower_bound > datetime.now(UTC):
        raise ValueError("future_identity_timestamp")
    if type(max_pages) is not int or not 1 <= max_pages <= 100:
        raise ValueError("invalid_identity_page_limit")
    search = f"status:active,draft,archived,unlisted updated_at:>='{since}'"
    products = []
    seen_gids: set[str] = set()
    cursors: set[str] = set()
    cursor = None
    observed_start = datetime.now(UTC).isoformat()
    previous_time = lower_bound
    for page_number in range(1, max_pages + 1):
        result = graphql(RECENT_IDENTITIES_QUERY, {"query": search, "after": cursor})
        connection = result["products"]
        nodes = connection["nodes"]
        page = connection["pageInfo"]
        if not isinstance(nodes, list) or len(nodes) > 50 or type(page["hasNextPage"]) is not bool:
            raise ValueError("invalid_identity_page")
        for node in nodes:
            gid = node["id"]
            updated = _timestamp(node["updatedAt"])
            if (
                not isinstance(gid, str)
                or re.fullmatch(r"gid://shopify/Product/[1-9][0-9]*", gid) is None
                or gid in seen_gids
                or updated < previous_time
            ):
                raise ValueError("inconsistent_identity_page")
            seen_gids.add(gid)
            previous_time = updated
            products.append(
                {
                    "productGid": gid,
                    "updatedAt": node["updatedAt"],
                    "syncSourceId": _identity(node, "syncProductId", "number_integer"),
                    "powerToolsSourceId": _identity(node, "powertoolsId", "single_line_text_field"),
                }
            )
        if not page["hasNextPage"]:
            return {
                "since": since,
                "observedStart": observed_start,
                "observedEnd": datetime.now(UTC).isoformat(),
                "pages": page_number,
                "products": products,
                "creationApproved": False,
            }
        next_cursor = page["endCursor"]
        if (
            not nodes
            or not isinstance(next_cursor, str)
            or not next_cursor
            or next_cursor in cursors
        ):
            raise ValueError("invalid_identity_cursor")
        cursors.add(next_cursor)
        cursor = next_cursor
        if page_number < max_pages:
            pause(2.0)
    raise ValueError("identity_page_limit_requires_fresh_baseline")
