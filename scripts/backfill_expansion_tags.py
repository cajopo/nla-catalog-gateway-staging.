"""Apply the owner's exact 31 October tag backfill; no other Shopify writes.

The immutable approved manifest is private and hash-pinned. Each bounded batch
is read live before tagsAdd, then read again. SQLite records intent before the
mutation; resuming an uncertain batch always rereads it before any additive retry.
"""

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path

from nla_catalog_gateway.shopify_capture_http import ShopifyCaptureHttp
from nla_catalog_gateway.shopify_draft_import import ACCESS_QUERY, PRODUCT_TYPES
from scripts import refresh_staging_catalog as refresh
from scripts.import_cardtrader_drafts import config_values

APPROVED_SHA = "a90776646654f074836be1086695bf04bc2d4d865d96e8e10e5039bfc0d8a2ed"
APPROVED_COUNT = 5612
SHOP = "bb5c19-c9.myshopify.com"
READ = """
query NlaBackfillTagProducts($ids: [ID!]!) {
  nodes(ids: $ids) {
    ... on Product {
      id handle productType tags
      syncProductId: metafield(namespace: "sync", key: "productid") { type value }
      powertoolsId: metafield(namespace: "powertools", key: "id") { type value }
      nlaGame: metafield(namespace: "nla", key: "game") { type value }
      sourceRecordType: metafield(namespace: "nla", key: "source_record_type") { type value }
    }
  }
}
"""


def load_plan(path):
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != APPROVED_SHA:
        raise ValueError("unapproved_manifest")
    plan = json.loads(raw)
    rows = plan["products"]
    if len(rows) != APPROVED_COUNT or len({row["productGid"] for row in rows}) != len(rows):
        raise ValueError("unapproved_product_count")
    return rows


def validate_product(product, row):
    expected = row["cardmarketId"]
    if (
        type(product) is not dict
        or product.get("id") != row["productGid"]
        or product.get("handle") != row["handle"]
        or product.get("syncProductId") != {"type": "number_integer", "value": expected}
        or product.get("powertoolsId") != {"type": "single_line_text_field", "value": expected}
        or type(product.get("tags")) is not list
        or any(type(tag) is not str for tag in product["tags"])
    ):
        raise ValueError("fresh_product_identity_mismatch")
    if row["family"] == "single":
        matches = product.get("productType") == PRODUCT_TYPES[row["game"]]
    else:
        matches = (
            product.get("productType") == ""
            and product.get("nlaGame") == {"type": "single_line_text_field", "value": row["game"]}
            and product.get("sourceRecordType")
            == {"type": "single_line_text_field", "value": "sealed"}
        )
    if not matches:
        raise ValueError("fresh_product_classification_mismatch")
    return set(product["tags"])


def read_batch(graphql, rows):
    nodes = graphql(READ, {"ids": [r["productGid"] for r in rows]}).get("nodes")
    if type(nodes) is not list or len(nodes) != len(rows):
        raise ValueError("invalid_product_readback")
    return [validate_product(p, r) for p, r in zip(nodes, rows, strict=True)]


def tag_mutation(rows):
    declarations, fields, variables = [], [], {}
    for i, row in enumerate(rows):
        declarations.extend((f"$id{i}: ID!", f"$tags{i}: [String!]!"))
        fields.append(
            f"p{i}: tagsAdd(id: $id{i}, tags: $tags{i}) "
            "{ node { id } userErrors { field message } }"
        )
        variables[f"id{i}"] = row["productGid"]
        variables[f"tags{i}"] = row["tagsToAdd"]
    return "mutation NlaAddExpansionTags(" + ", ".join(declarations) + ") {\n" + "\n".join(
        fields
    ) + "\n}", variables


def run(plan_path, checkpoint, graphql, *, apply=False, batch_size=50, progress=None):
    if type(apply) is not bool or type(batch_size) is not int or not 1 <= batch_size <= 50:
        raise ValueError("invalid_backfill_controls")
    rows = load_plan(plan_path)
    access = graphql(ACCESS_QUERY, {})
    scopes = {scope["handle"] for scope in access["currentAppInstallation"]["accessScopes"]}
    if access["shop"]["myshopifyDomain"] != SHOP or "write_products" not in scopes:
        raise ValueError("backfill_access_mismatch")
    if checkpoint.is_symlink():
        raise ValueError("invalid_checkpoint_path")
    checkpoint.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with closing(sqlite3.connect(checkpoint)) as db:
        db.execute("PRAGMA synchronous=FULL")
        db.execute("CREATE TABLE IF NOT EXISTS metadata (manifest_sha TEXT NOT NULL)")
        db.execute(
            "CREATE TABLE IF NOT EXISTS products "
            "(gid TEXT PRIMARY KEY, original_tags TEXT NOT NULL, state TEXT NOT NULL)"
        )
        saved = db.execute("SELECT manifest_sha FROM metadata").fetchall()
        if saved and saved != [(APPROVED_SHA,)]:
            raise ValueError("checkpoint_manifest_mismatch")
        if not saved:
            db.execute("INSERT INTO metadata VALUES (?)", (APPROVED_SHA,))
            db.commit()
        verified = needs_tags = 0
        next_progress = 250
        for start in range(0, len(rows), batch_size):
            batch = rows[start : start + batch_size]
            before = read_batch(graphql, batch)
            pending = []
            for row, current in zip(batch, before, strict=True):
                old = db.execute(
                    "SELECT original_tags,state FROM products WHERE gid=?", (row["productGid"],)
                ).fetchone()
                original = set(json.loads(old[0])) if old else set()
                if not original <= current:
                    raise ValueError("preexisting_tags_removed")
                present = set(row["tagsToAdd"]) <= current
                if old and old[1] == "verified" and not present:
                    raise ValueError("completed_tags_changed")
                if not present:
                    pending.append(row)
                if apply:
                    db.execute(
                        "INSERT OR REPLACE INTO products VALUES (?,?,?)",
                        (
                            row["productGid"],
                            json.dumps(sorted(original | current)),
                            "verified" if present else "pending",
                        ),
                    )
            needs_tags += len(pending)
            if apply:
                db.commit()  # Persist every original tag and intent BEFORE any network write.
                if pending:
                    query, variables = tag_mutation(pending)
                    result = graphql(query, variables)
                    if any(
                        result.get(f"p{i}") != {"node": {"id": row["productGid"]}, "userErrors": []}
                        for i, row in enumerate(pending)
                    ):
                        raise ValueError("tag_mutation_unconfirmed")
                after = read_batch(graphql, batch)
                for row, old_tags, new_tags in zip(batch, before, after, strict=True):
                    if not old_tags | set(row["tagsToAdd"]) <= new_tags:
                        raise ValueError("tag_readback_mismatch")
                    db.execute(
                        "UPDATE products SET state='verified' WHERE gid=?", (row["productGid"],)
                    )
                db.commit()
            verified += len(batch)
            if progress is not None and (verified >= next_progress or verified == len(rows)):
                progress(
                    {
                        "status": "progress",
                        "productsChecked": verified,
                        "productsTotal": len(rows),
                        "productsNeedingTags": needs_tags,
                    }
                )
                next_progress += 250
        return {
            "status": "complete" if apply else "preview",
            "productsChecked": verified,
            "productsNeedingTags": needs_tags,
            "manifestSha256": APPROVED_SHA,
            "shopifyChanged": apply and needs_tags > 0,
        }


class PacedShopify(ShopifyCaptureHttp):
    """Use Shopify's actual cost budget; credentials and response bodies stay private."""

    def _request_json(self, *args, **kwargs):
        result = super()._request_json(*args, **kwargs)
        throttle = result.get("extensions", {}).get("cost", {}).get("throttleStatus", {})
        available, maximum, rate = (
            throttle.get(key) for key in ("currentlyAvailable", "maximumAvailable", "restoreRate")
        )
        if all(type(value) in (int, float) and value >= 0 for value in (available, maximum, rate)):
            reserve = min(700, maximum)
            if rate > 0 and available < reserve:
                time.sleep(min(30, (reserve - available) / rate))
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("refresh-config", "manifest", "checkpoint", "result"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--batch-size", type=int, default=50)
    args = parser.parse_args(argv)
    try:
        if not __debug__ or sys.platform != "linux" or os.geteuid() != 0:
            raise ValueError("root_linux_required")
        os.umask(0o077)
        _, config = config_values(args.refresh_config)
        with refresh.pipeline_lock(config["run_root"]):
            credentials = refresh.document(config["config"] / "shopify-app-credentials.json")
            client = PacedShopify(
                config["shop"], "2026-07", credentials["client_id"], credentials["client_secret"]
            )
            result = run(
                args.manifest,
                args.checkpoint,
                client.graphql,
                apply=args.apply,
                batch_size=args.batch_size,
                progress=lambda value: print(json.dumps(value), flush=True),
            )
            refresh.publish(args.result, result, replace=True)
        print(json.dumps(result))
        return 0
    except Exception:
        print(json.dumps({"status": "backfill_unconfirmed_inspect_checkpoint"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
