"""Single-draft execution with a durable no-resend ledger; no automatic rollout."""

import hashlib
import json
import re
import sqlite3
from collections.abc import Callable
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

ACCESS_QUERY = """
query NlaDraftImportAccess {
  shop { myshopifyDomain }
  currentAppInstallation { accessScopes { handle } }
}
"""
CREATE_DRAFT = """
mutation NlaCreateMissingDraft($product: ProductCreateInput!, $media: [CreateMediaInput!]) {
  productCreate(product: $product, media: $media) {
    product { id handle status totalInventory publishedAt }
    userErrors { field message }
  }
}
"""
SET_IDENTITIES = """
mutation NlaSetNewDraftIdentities($metafields: [MetafieldsSetInput!]!) {
  metafieldsSet(metafields: $metafields) {
    metafields { namespace key type value }
    userErrors { field code }
  }
}
"""
VERIFY_DRAFT = """
query NlaVerifyNewDraft($id: ID!) {
  product(id: $id) {
    id handle status totalInventory publishedAt
    syncProductId: metafield(namespace: "sync", key: "productid") { type value }
    powertoolsId: metafield(namespace: "powertools", key: "id") { type value }
  }
}
"""

FIND_ATTEMPT_HANDLE = """
query NlaFindAttemptHandle($identifier: ProductIdentifierInput!) {
  product: productByIdentifier(identifier: $identifier) { id handle }
}
"""

PRODUCT_TYPES = {
    "magic": "Magic Single",
    "pokemon": "Pokémon Single",
    "yugioh": "Yu-Gi-Oh! Single",
    "one-piece": "One Piece Single",
}


def _safe_draft(product: dict, handle: str) -> str:
    gid = product["id"]
    if (
        not isinstance(gid, str)
        or re.fullmatch(r"gid://shopify/Product/[1-9][0-9]*", gid) is None
        or product["handle"] != handle
        or product["status"] != "DRAFT"
        or type(product["totalInventory"]) is not int
        or product["totalInventory"] != 0
        or product["publishedAt"] is not None
    ):
        raise ValueError("unexpected_new_draft")
    return gid


def inspect_draft_attempt(
    ledger: Path,
    *,
    shop: str,
    cardmarket_id: int,
    graphql: Callable[[str, dict], dict],
) -> dict:
    """Read-only inspection; never adopt a handle match or unblock a reserved attempt.

    A recorded GID came from the creation response. Without it, an exact handle
    match is only a lead for manual reconciliation, not proof of ownership.
    Absence is not permission to retry (renames/deletion/index lag are possible).
    A matching draft still says nothing about media readiness or purchase safety.
    """
    if not isinstance(ledger, Path) or not ledger.is_absolute():
        raise ValueError("persistent_absolute_ledger_required")
    if type(cardmarket_id) is not int or not 0 < cardmarket_id < 2**63:
        raise ValueError("invalid_import_identity")
    with closing(sqlite3.connect(ledger.as_uri() + "?mode=ro", uri=True)) as db:
        db.execute("PRAGMA query_only=ON")
        row = db.execute(
            "SELECT state,product_gid,request_sha256,request_json FROM draft_attempts "
            "WHERE shop=? AND cardmarket_id=?",
            (shop, cardmarket_id),
        ).fetchone()
    if row is None:
        return {"status": "no_attempt", "retryAllowed": False}
    state, gid, digest, encoded = row
    if hashlib.sha256(encoded.encode()).hexdigest() != digest:
        raise ValueError("attempt_request_digest_mismatch")
    handle = f"nla-cm-{cardmarket_id}"
    if json.loads(encoded)["variables"]["product"]["handle"] != handle:
        raise ValueError("attempt_handle_mismatch")
    result = {"state": state, "productGid": gid, "retryAllowed": False}
    try:
        if graphql(ACCESS_QUERY, {})["shop"]["myshopifyDomain"] != shop:
            raise ValueError("inspection_shop_mismatch")
        if gid is None:
            found = graphql(FIND_ATTEMPT_HANDLE, {"identifier": {"handle": handle}})["product"]
            if found is None:
                return {**result, "status": "outcome_unknown_no_handle_match"}
            if (
                found["handle"] != handle
                or not isinstance(found["id"], str)
                or re.fullmatch(r"gid://shopify/Product/[1-9][0-9]*", found["id"]) is None
            ):
                raise ValueError("invalid_handle_result")
            return {
                **result,
                "status": "manual_ownership_check_required",
                "candidateProductGid": found["id"],
            }
        product = graphql(VERIFY_DRAFT, {"id": gid})["product"]
        if product is None:
            return {**result, "status": "recorded_product_not_found"}
        if _safe_draft(product, handle) != gid:
            raise ValueError("inspection_gid_mismatch")
        expected = str(cardmarket_id)
        if product.get("syncProductId") != {"type": "number_integer", "value": expected} or (
            product.get("powertoolsId") != {"type": "single_line_text_field", "value": expected}
        ):
            return {**result, "status": "identity_fields_require_review"}
        return {**result, "status": "recorded_draft_matches", "published": False}
    except Exception:
        return {**result, "status": "inspection_unconfirmed"}


def create_draft_once(
    ledger: Path,
    *,
    shop: str,
    blueprint_id: int,
    cardmarket_id: int,
    game: str,
    title: str,
    image_url: str,
    graphql: Callable[[str, dict], dict],
    verify_missing: Callable[[], bool],
    enabled: bool = False,
) -> dict:
    """Create only after the caller's reviewed current-identity check succeeds.

    This primitive is NOT a source validator or production import command. Caller
    must bind the source row and full comparison to these arguments, verify the
    existing identity definitions, and check current Shopify for BOTH identities.
    An empty delta query alone is insufficient. Default disabled; no scheduler.

    Ledger must be private, persistent and backed up, outside Git. Keep it across
    all runs. Every existing reservation (including uncertain/rejected outcomes)
    blocks resending. Manual read-only reconciliation is required after interruption.
    This guards this importer's retries, not concurrent third-party creation.
    Only the product returned by this call's productCreate can receive initial
    metadata, using create-only CAS. No price/stock/options/publication writes.
    """
    if enabled is not True:
        return {"status": "disabled"}
    if not isinstance(ledger, Path) or not ledger.is_absolute():
        raise ValueError("persistent_absolute_ledger_required")
    if (
        not isinstance(shop, str)
        or re.fullmatch(r"[a-z0-9][a-z0-9-]*\.myshopify\.com", shop) is None
    ):
        raise ValueError("invalid_import_shop")
    if any(type(i) is not int or not 0 < i < 2**63 for i in (blueprint_id, cardmarket_id)):
        raise ValueError("invalid_import_identity")
    if (
        game not in PRODUCT_TYPES
        or not isinstance(title, str)
        or not title.strip()
        or len(title) > 255
    ):
        raise ValueError("invalid_import_product")
    image = urlsplit(image_url)
    if (
        image.scheme != "https"
        or not image.hostname
        or image.username
        or image.password
        or image.fragment
    ):
        raise ValueError("invalid_import_image")
    handle = f"nla-cm-{cardmarket_id}"
    variables = {
        "product": {
            "title": title,
            "productType": PRODUCT_TYPES[game],
            "handle": handle,
            "status": "DRAFT",
        },
        "media": [{"mediaContentType": "IMAGE", "originalSource": image_url, "alt": title}],
    }
    encoded = json.dumps({"blueprintId": blueprint_id, "variables": variables}, sort_keys=True)
    digest = hashlib.sha256(encoded.encode()).hexdigest()
    # SQLite commits the reservation before the first network write. A crash at
    # any later point leaves a reservation, never permission to send again.
    with closing(sqlite3.connect(ledger, timeout=10)) as db:
        db.execute("PRAGMA synchronous=FULL")
        db.execute("""CREATE TABLE IF NOT EXISTS draft_attempts (
          shop TEXT NOT NULL, cardmarket_id INTEGER NOT NULL, blueprint_id INTEGER NOT NULL,
          request_sha256 TEXT NOT NULL, request_json TEXT NOT NULL, state TEXT NOT NULL,
          product_gid TEXT, created_at TEXT NOT NULL,
          PRIMARY KEY(shop, cardmarket_id), UNIQUE(shop, blueprint_id))""")
        existing = db.execute(
            "SELECT state,product_gid FROM draft_attempts "
            "WHERE shop=? AND (cardmarket_id=? OR blueprint_id=?)",
            (shop, cardmarket_id, blueprint_id),
        ).fetchone()
        if existing:
            return {"status": "already_reserved", "state": existing[0], "productGid": existing[1]}
        access = graphql(ACCESS_QUERY, {})
        scopes = {row["handle"] for row in access["currentAppInstallation"]["accessScopes"]}
        if access["shop"]["myshopifyDomain"] != shop or "write_products" not in scopes:
            raise ValueError("import_access_not_granted")
        if verify_missing() is not True:
            return {"status": "not_verified_missing"}
        try:
            db.execute(
                "INSERT INTO draft_attempts VALUES (?,?,?,?,?,'reserved',NULL,?)",
                (shop, cardmarket_id, blueprint_id, digest, encoded, datetime.now(UTC).isoformat()),
            )
            db.commit()
        except sqlite3.IntegrityError:
            db.rollback()
            return {"status": "already_reserved"}

        def record(state: str, gid: str | None = None) -> None:
            db.execute(
                "UPDATE draft_attempts SET state=?,product_gid=COALESCE(?,product_gid) "
                "WHERE shop=? AND cardmarket_id=?",
                (state, gid, shop, cardmarket_id),
            )
            db.commit()

        try:
            created = graphql(CREATE_DRAFT, variables)["productCreate"]
            product = created.get("product")
            if isinstance(product, dict) and isinstance(product.get("id"), str):
                if re.fullmatch(r"gid://shopify/Product/[1-9][0-9]*", product["id"]):
                    record("draft_created", product["id"])
            if created["userErrors"] or created["product"] is None:
                record("needs_reconciliation")
                return {"status": "needs_reconciliation"}
            gid = _safe_draft(created["product"], handle)
            fields = [
                {
                    "ownerId": gid,
                    "namespace": namespace,
                    "key": key,
                    "type": kind,
                    "value": str(cardmarket_id),
                    "compareDigest": None,
                }
                for namespace, key, kind in (
                    ("sync", "productid", "number_integer"),
                    ("powertools", "id", "single_line_text_field"),
                )
            ]
            assigned = graphql(SET_IDENTITIES, {"metafields": fields})["metafieldsSet"]
            if assigned["userErrors"]:
                raise ValueError("initial_identities_not_confirmed")
            verified = graphql(VERIFY_DRAFT, {"id": gid})["product"]
            if _safe_draft(verified, handle) != gid:
                raise ValueError("unexpected_verification_identity")
            for alias, field in zip(("syncProductId", "powertoolsId"), fields, strict=True):
                if verified[alias] != {"type": field["type"], "value": field["value"]}:
                    raise ValueError("initial_identities_not_confirmed")
            record("draft_verified", gid)
            return {"status": "draft_verified", "productGid": gid, "published": False}
        except Exception:
            # No remote response/error text is stored or returned. Keep the attempt
            # even if the API accepted a request but the response was lost.
            record("needs_reconciliation")
            return {"status": "needs_reconciliation"}
