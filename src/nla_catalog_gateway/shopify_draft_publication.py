"""Owner-gated publication of importer-owned, verified, zero-stock card drafts.

The creation ledger is never rewritten. A separate durable receipt prevents later
cycles from overriding PowerTools after successful publication. No price, stock,
variant or metadata mutation is permitted here.
"""

import hashlib
import json
import os
import re
import sqlite3
import stat
from contextlib import closing
from datetime import UTC, datetime

from nla_catalog_gateway.shopify_capture_http import CaptureHttpError
from nla_catalog_gateway.shopify_draft_import import ACCESS_QUERY, _initial_variant

PUBLICATION = """
query NlaOnlineStorePublication($id: ID!) {
  publication(id: $id) {
    id
    catalog { __typename ... on AppCatalog {
      apps(first: 2) { nodes { id handle } pageInfo { hasNextPage endCursor } }
    } }
  }
}
"""
PRODUCT = """
query NlaImportedPublicationCheck($id: ID!, $publicationId: ID!) {
  product(id: $id) {
    id handle title productType status totalInventory
    publishedOnPublication(publicationId: $publicationId)
    syncProductId: metafield(namespace: "sync", key: "productid") { type value }
    powertoolsId: metafield(namespace: "powertools", key: "id") { type value }
    resourcePublicationsV2(first: 20, onlyPublished: false) {
      nodes { isPublished publication { id } } pageInfo { hasNextPage endCursor }
    }
    media(first: 2) {
      nodes { id status mediaContentType } pageInfo { hasNextPage endCursor }
    }
    variants(first: 2) {
      nodes {
        id price inventoryQuantity inventoryPolicy selectedOptions { name value }
        inventoryItem {
          id tracked
          inventoryLevels(first: 50) {
            nodes { id quantities(names: ["available", "on_hand", "committed", "reserved"]) {
              name quantity
            } }
            pageInfo { hasNextPage endCursor }
          }
        }
      }
      pageInfo { hasNextPage endCursor }
    }
  }
}
"""
ACTIVATE = """
mutation NlaActivateImportedDraft($product: ProductUpdateInput!) {
  productUpdate(product: $product) { product { id status } userErrors { field message } }
}
"""
PUBLISH = """
mutation NlaPublishImportedDraft($id: ID!, $input: [PublicationInput!]!) {
  publishablePublish(id: $id, input: $input) { userErrors { field message } }
}
"""


def failure_reason(error):
    """Only fixed local codes enter receipts, never arbitrary provider text."""
    reasons = {
        "publication_request_digest_mismatch",
        "publication_identity_mismatch",
        "publication_product_changed",
        "publication_untracked_stock",
        "publication_incomplete_inventory",
        "publication_nonzero_inventory",
        "publication_media_not_ready",
        "publication_other_channel",
        "publication_snapshot_changed",
        "activation_not_owned_by_publisher",
        "activation_not_confirmed",
        "activation_changed_commercial_data",
        "publication_not_confirmed",
        "publication_readback_mismatch",
        "unexpected_initial_variants",
        "unexpected_initial_variant",
    }
    if isinstance(error, CaptureHttpError):
        return "shopify_request_failed"
    if type(error) is ValueError and len(error.args) == 1:
        reason = error.args[0]
        if type(reason) is str and reason in reasons:
            return reason
    if isinstance(error, sqlite3.Error):
        return "ledger_database_error"
    return "unexpected_publication_error"


def validate_ledger(ledger):
    if not ledger.is_absolute() or ledger.resolve() != ledger:
        raise ValueError("canonical_existing_ledger_required")
    facts = ledger.lstat()
    if not stat.S_ISREG(facts.st_mode) or facts.st_nlink != 1:
        raise ValueError("existing_regular_ledger_required")
    if os.name == "posix" and (facts.st_uid != 0 or stat.S_IMODE(facts.st_mode) != 0o600):
        raise ValueError("private_existing_ledger_required")


def commercial(product):
    return {
        k: v
        for k, v in product.items()
        if k not in ("status", "publishedOnPublication", "resourcePublicationsV2")
    }


def verify_identity(product, row):
    cm, blueprint, gid, digest, encoded = row
    if hashlib.sha256(encoded.encode()).hexdigest() != digest:
        raise ValueError("publication_request_digest_mismatch")
    request = json.loads(encoded)
    expected = request["variables"]["product"]
    if (
        request["blueprintId"] != blueprint
        or re.fullmatch(r"gid://shopify/Product/[1-9][0-9]*", gid or "") is None
        or expected["handle"] != f"nla-cm-{cm}"
        or product is None
        or product["id"] != gid
        or product["handle"] != expected["handle"]
        or product["syncProductId"] != {"type": "number_integer", "value": str(cm)}
        or product["powertoolsId"] != {"type": "single_line_text_field", "value": str(cm)}
    ):
        raise ValueError("publication_identity_mismatch")
    return expected


def verify_ready(product, expected, publication_id):
    if (
        product["status"] not in ("DRAFT", "ACTIVE")
        or product["title"] != expected["title"]
        or product["productType"] != expected["productType"]
        or type(product["totalInventory"]) is not int
        or product["totalInventory"] != 0
    ):
        raise ValueError("publication_product_changed")
    variant = _initial_variant(product)
    if variant["inventoryItem"]["tracked"] is not True:
        raise ValueError("publication_untracked_stock")
    levels = variant["inventoryItem"]["inventoryLevels"]
    if levels["pageInfo"]["hasNextPage"] is not False:
        raise ValueError("publication_incomplete_inventory")
    for level in levels["nodes"]:
        quantities = {q["name"]: q["quantity"] for q in level["quantities"]}
        if (
            set(quantities) != {"available", "on_hand", "committed", "reserved"}
            or len(level["quantities"]) != 4
            or any(type(q) is not int or q != 0 for q in quantities.values())
        ):
            raise ValueError("publication_nonzero_inventory")
    media = product["media"]
    if (
        media["pageInfo"]["hasNextPage"] is not False
        or len(media["nodes"]) != 1
        or media["nodes"][0]["status"] != "READY"
        or media["nodes"][0]["mediaContentType"] != "IMAGE"
    ):
        raise ValueError("publication_media_not_ready")
    channels = product["resourcePublicationsV2"]
    if channels["pageInfo"]["hasNextPage"] is not False or any(
        n["publication"]["id"] != publication_id for n in channels["nodes"]
    ):
        raise ValueError("publication_other_channel")


def publish_verified_drafts(
    ledger, *, shop, publication_id, graphql, enabled=False, max_products=100
):
    """Caller holds importer and refresh locks. Only advance individually read-back steps.

    A lost response stops this call. Next invocation reads Shopify and the saved
    commercial snapshot before deciding which status/publication step is missing.
    A successful receipt is terminal: never reactivate later merchant/PT changes.
    """
    if enabled is not True:
        return {"status": "disabled", "published": 0, "results": []}
    if (
        type(max_products) is not int
        or not 1 <= max_products <= 10000
        or not ledger.is_absolute()
        or ledger.resolve() != ledger
        or re.fullmatch(r"gid://shopify/Publication/[1-9][0-9]*", publication_id) is None
    ):
        raise ValueError("invalid_publication_controls")
    validate_ledger(ledger)
    access = graphql(ACCESS_QUERY, {})
    scopes = {s["handle"] for s in access["currentAppInstallation"]["accessScopes"]}
    if (
        access["shop"]["myshopifyDomain"] != shop
        or not {"write_products", "write_publications", "read_publications"} <= scopes
    ):
        raise ValueError("publication_access_not_granted")
    publication = graphql(PUBLICATION, {"id": publication_id})["publication"]
    if (
        publication is None
        or publication["id"] != publication_id
        or publication["catalog"]["__typename"] != "AppCatalog"
        or publication["catalog"]["apps"]["pageInfo"]["hasNextPage"] is not False
        or publication["catalog"]["apps"]["nodes"]
        != [{"id": "gid://shopify/App/580111", "handle": "online_store"}]
    ):
        raise ValueError("not_verified_online_store")
    result = {
        "status": "publication_complete",
        "published": 0,
        "alreadyPublished": 0,
        "results": [],
    }
    with closing(sqlite3.connect(ledger.as_uri() + "?mode=rw", uri=True, timeout=10)) as db:
        db.execute("PRAGMA synchronous=FULL")
        db.execute("""CREATE TABLE IF NOT EXISTS draft_publications (
          shop TEXT NOT NULL, cardmarket_id INTEGER NOT NULL, product_gid TEXT NOT NULL,
          publication_gid TEXT NOT NULL, snapshot_json TEXT NOT NULL,
          state TEXT NOT NULL, updated_at TEXT NOT NULL,
          PRIMARY KEY(shop,cardmarket_id))""")
        rows = db.execute(
            "SELECT d.cardmarket_id,d.blueprint_id,d.product_gid,d.request_sha256,d.request_json "
            "FROM draft_attempts d LEFT JOIN draft_publications p ON "
            "p.shop=d.shop AND p.cardmarket_id=d.cardmarket_id "
            "WHERE d.shop=? AND d.state='draft_verified' "
            "AND (p.state IS NULL OR p.state!='published') ORDER BY d.created_at LIMIT ?",
            (shop, max_products),
        ).fetchall()
        for row in rows:
            cm, _, gid, _, _ = row
            step = "inspect"
            try:
                saved = db.execute(
                    "SELECT product_gid,publication_gid,snapshot_json FROM draft_publications "
                    "WHERE shop=? AND cardmarket_id=?",
                    (shop, cm),
                ).fetchone()
                product = graphql(PRODUCT, {"id": gid, "publicationId": publication_id})["product"]
                expected = verify_identity(product, row)
                if product["status"] == "ACTIVE" and product["publishedOnPublication"] is True:
                    if saved and (
                        saved[:2] != (gid, publication_id)
                        or json.loads(saved[2]) != commercial(product)
                    ):
                        raise ValueError("publication_snapshot_changed")
                    already = True
                else:
                    verify_ready(product, expected, publication_id)
                    if saved:
                        if saved[:2] != (gid, publication_id) or json.loads(saved[2]) != commercial(
                            product
                        ):
                            raise ValueError("publication_snapshot_changed")
                    elif product["status"] != "DRAFT":
                        raise ValueError("activation_not_owned_by_publisher")
                    if not saved:
                        db.execute(
                            "INSERT INTO draft_publications VALUES (?,?,?,?,?,'pending',?)",
                            (
                                shop,
                                cm,
                                gid,
                                publication_id,
                                json.dumps(commercial(product), sort_keys=True),
                                datetime.now(UTC).isoformat(),
                            ),
                        )
                        db.commit()
                    before = commercial(product)
                    if product["status"] == "DRAFT":
                        step = "activate"
                        activated = graphql(ACTIVATE, {"product": {"id": gid, "status": "ACTIVE"}})[
                            "productUpdate"
                        ]
                        if activated["userErrors"] or activated["product"] != {
                            "id": gid,
                            "status": "ACTIVE",
                        }:
                            raise ValueError("activation_not_confirmed")
                        product = graphql(PRODUCT, {"id": gid, "publicationId": publication_id})[
                            "product"
                        ]
                        verify_identity(product, row)
                        verify_ready(product, expected, publication_id)
                        if product["status"] != "ACTIVE" or commercial(product) != before:
                            raise ValueError("activation_changed_commercial_data")
                    step = "publish"
                    published = graphql(
                        PUBLISH, {"id": gid, "input": [{"publicationId": publication_id}]}
                    )["publishablePublish"]
                    if published["userErrors"]:
                        raise ValueError("publication_not_confirmed")
                    product = graphql(PRODUCT, {"id": gid, "publicationId": publication_id})[
                        "product"
                    ]
                    verify_identity(product, row)
                    verify_ready(product, expected, publication_id)
                    if (
                        product["status"] != "ACTIVE"
                        or product["publishedOnPublication"] is not True
                        or commercial(product) != before
                    ):
                        raise ValueError("publication_readback_mismatch")
                    already = False
                db.execute(
                    "INSERT INTO draft_publications VALUES (?,?,?,?,?,'published',?) "
                    "ON CONFLICT(shop,cardmarket_id) DO UPDATE SET state='published',"
                    "updated_at=excluded.updated_at",
                    (
                        shop,
                        cm,
                        gid,
                        publication_id,
                        json.dumps(commercial(product), sort_keys=True),
                        datetime.now(UTC).isoformat(),
                    ),
                )
                db.commit()
                result["alreadyPublished" if already else "published"] += 1
                result["results"].append({"cardmarketId": cm, "status": "published_verified"})
            except Exception as error:
                result["status"] = "publication_stopped_inspect"
                result["results"].append(
                    {
                        "cardmarketId": cm,
                        "status": "unconfirmed",
                        "stage": step,
                        "reason": failure_reason(error),
                    }
                )
                break
        result["remaining"] = db.execute(
            "SELECT count(*) FROM draft_attempts d LEFT JOIN draft_publications p ON "
            "p.shop=d.shop AND p.cardmarket_id=d.cardmarket_id WHERE d.shop=? "
            "AND d.state='draft_verified' AND (p.state IS NULL OR p.state!='published')",
            (shop,),
        ).fetchone()[0]
    return result
