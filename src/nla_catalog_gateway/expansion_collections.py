"""Create missing, unpublished expansion collections; never alter existing resources.

The caller supplies verified source expansion identities and holds the importer
pipeline lock. A durable intent precedes every create. An uncertain create is
only reconciled by its remote identity marker, never blindly sent again.
"""

import json
import re
import sqlite3
import unicodedata
from contextlib import closing
from pathlib import Path

GAME_TAGS = {"lorcana": "Lorcana", "riftbound": "Riftbound"}
MARKER_NAMESPACE = "nla"
MARKER_KEY = "expansion_identity"
FIELDS = """
id handle
identity: metafield(namespace: "nla", key: "expansion_identity") { type value }
resourcePublicationsCount(onlyPublished: false) { count }
sources {
  __typename
  ... on CollectionConditionsSource {
    targetType
    inclusion {
      matchType
      conditions {
        __typename
        ... on CollectionSourceInclusionConditionProductTag { relation matchType values }
      }
      selections(first: 1) { nodes { product { id } } }
    }
    exclusion { conditions { __typename } selections(first: 1) { nodes { product { id } } } }
  }
}
"""
LIST_COLLECTIONS = """
query NlaExpansionCollections($after: String) {
  collections(first: 100, after: $after, sortKey: ID) {
    nodes {
      id handle
      identity: metafield(namespace: "nla", key: "expansion_identity") { type value }
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""
READ_COLLECTION = f"""
query NlaExpansionCollection($id: ID!) {{
  collection(id: $id) {{ {FIELDS} }}
}}
"""
CREATE_COLLECTION = f"""
mutation NlaCreateExpansionCollection($collection: CollectionCreateInput!) {{
  collectionCreate(collection: $collection) {{
    collection {{ {FIELDS} }}
    userErrors {{ field message }}
  }}
}}
"""


def expansion_collection_spec(candidate: dict) -> dict:
    """Normalize only an explicit, verified source identity supplied by the caller."""
    game = candidate.get("game")
    expansion_id = candidate.get("sourceExpansionId")
    name = candidate.get("sourceExpansionName")
    if (
        type(game) is not str
        or game not in GAME_TAGS
        or type(expansion_id) is not int
        or not 0 < expansion_id < 2**63
        or type(name) is not str
        or not name.strip()
        or name != name.strip()
        or len(name) > 255
        or any(ord(char) < 32 or char == "," for char in name)
    ):
        raise ValueError("invalid_expansion_collection_identity")
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    handle = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    if not handle or name.casefold() == GAME_TAGS[game].casefold():
        raise ValueError("invalid_expansion_collection_handle")
    if candidate.get("collectionTags", [GAME_TAGS[game], name]) != [GAME_TAGS[game], name]:
        raise ValueError("invalid_expansion_collection_tags")
    return dict(
        game=game,
        sourceExpansionId=expansion_id,
        sourceExpansionName=name,
        identity=f"cardtrader:{game}:{expansion_id}",
        handle=handle,
        tags=[GAME_TAGS[game], name],
    )


def collection_input(spec: dict) -> dict:
    """Use the same default template/tag membership as existing expansion collections."""
    return dict(
        title=spec["sourceExpansionName"],
        handle=spec["handle"],
        sortOrder="BEST_SELLING",
        metafields=[
            dict(
                namespace=MARKER_NAMESPACE,
                key=MARKER_KEY,
                type="single_line_text_field",
                value=spec["identity"],
            )
        ],
        sources=[
            dict(
                source=dict(
                    title=spec["identity"],
                    targetType="PRODUCTS",
                    inclusion=dict(
                        matchType="ALL",
                        conditions=[
                            dict(
                                productTag=dict(
                                    relation="TAGGED_WITH", matchType="ALL", values=spec["tags"]
                                )
                            )
                        ],
                    ),
                )
            )
        ],
    )


def collection_inventory(graphql) -> list[dict]:
    """Read all collection identities, including unpublished collections."""
    result, seen = [], set()
    cursor = None
    for _ in range(100):
        page = graphql(LIST_COLLECTIONS, {"after": cursor})["collections"]
        result.extend(page["nodes"])
        info = page["pageInfo"]
        if info["hasNextPage"] is False:
            return result
        cursor = info["endCursor"]
        if not cursor or cursor in seen:
            raise ValueError("invalid_expansion_collection_cursor")
        seen.add(cursor)
    raise ValueError("expansion_collection_page_limit")


def verify_collection(row: dict, spec: dict, *, unpublished: bool) -> str:
    """Identity and exact conditions must match; owner publication is preserved."""
    try:
        gid = row["id"]
        (source,) = row["sources"]
        inclusion = source["inclusion"]
        (condition,) = inclusion["conditions"]
        exclusion = source["exclusion"]
        valid = (
            re.fullmatch(r"gid://shopify/Collection/[1-9][0-9]*", gid) is not None
            and row["identity"] == dict(type="single_line_text_field", value=spec["identity"])
            and source["__typename"] == "CollectionConditionsSource"
            and source["targetType"] == "PRODUCTS"
            and inclusion["matchType"] == "ALL"
            and inclusion["selections"]["nodes"] == []
            and condition["__typename"] == "CollectionSourceInclusionConditionProductTag"
            and condition["relation"] == "TAGGED_WITH"
            and condition["matchType"] == "ALL"
            and sorted(condition["values"]) == sorted(spec["tags"])
            and (
                exclusion is None
                or (exclusion["conditions"] == [] and exclusion["selections"]["nodes"] == [])
            )
            and (not unpublished or row["resourcePublicationsCount"]["count"] == 0)
        )
    except (KeyError, TypeError, ValueError):
        valid = False
    if not valid:
        raise ValueError("expansion_collection_readback_mismatch")
    return gid


def reconcile_expansion_collections(*, graphql, specs, state_dir: Path, enabled=False) -> dict:
    """Idempotent create-only reconciliation under the caller's pipeline lock.

    Existing matching identities are read-only, including owner-published ones.
    A durable pending intent with no remote match requires inspection, not retry.
    """
    normalized = {}
    handles = {}
    for raw in specs:
        spec = expansion_collection_spec(raw)
        identity = spec["identity"]
        if identity in normalized and normalized[identity] != spec:
            raise ValueError("conflicting_expansion_collection_identity")
        if spec["handle"] in handles and handles[spec["handle"]] != identity:
            raise ValueError("conflicting_expansion_collection_handle")
        normalized[identity] = spec
        handles[spec["handle"]] = identity
    if type(enabled) is not bool:
        raise ValueError("invalid_expansion_collection_apply")
    if not enabled or not normalized:
        return dict(status="preview", planned=len(normalized), created=0, existing=0)
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    inventory = collection_inventory(graphql)
    result = dict(status="complete", planned=len(normalized), created=0, existing=0, collections=[])
    with closing(sqlite3.connect(state_dir / "collections.sqlite3")) as db:
        db.execute("PRAGMA synchronous=FULL")
        db.execute(
            "CREATE TABLE IF NOT EXISTS collections (identity TEXT PRIMARY KEY, "
            "spec TEXT NOT NULL, state TEXT NOT NULL, gid TEXT)"
        )
        db.commit()
        for identity, spec in normalized.items():
            encoded = json.dumps(spec, sort_keys=True, separators=(",", ":"))
            saved = db.execute(
                "SELECT spec,state,gid FROM collections WHERE identity=?", (identity,)
            ).fetchone()
            if saved and saved[0] != encoded:
                raise ValueError("expansion_collection_source_drift")
            matches = [r for r in inventory if (r.get("identity") or {}).get("value") == identity]
            if len(matches) > 1:
                raise ValueError("duplicate_expansion_collection_identity")
            if matches:
                row = graphql(READ_COLLECTION, {"id": matches[0]["id"]})["collection"]
                gid = verify_collection(row, spec, unpublished=False)
                if saved and saved[2] is not None and saved[2] != gid:
                    raise ValueError("expansion_collection_gid_changed")
                result["existing"] += 1
            else:
                if saved:
                    raise ValueError("expansion_collection_missing_inspect")
                if any(r["handle"] == spec["handle"] for r in inventory):
                    raise ValueError("expansion_collection_handle_occupied")
                db.execute(
                    "INSERT INTO collections VALUES (?,?,?,NULL)", (identity, encoded, "pending")
                )
                db.commit()
                response = graphql(CREATE_COLLECTION, {"collection": collection_input(spec)})[
                    "collectionCreate"
                ]
                if response["userErrors"]:
                    raise ValueError("expansion_collection_create_rejected")
                row = response["collection"]
                gid = verify_collection(row, spec, unpublished=True)
                if row["handle"] != spec["handle"]:
                    raise ValueError("expansion_collection_handle_changed")
                inventory.append(row)
                result["created"] += 1
            db.execute(
                "INSERT OR REPLACE INTO collections VALUES (?,?,?,?)",
                (identity, encoded, "complete", gid),
            )
            db.commit()
            result["collections"].append(dict(identity=identity, collectionGid=gid))
    return result
