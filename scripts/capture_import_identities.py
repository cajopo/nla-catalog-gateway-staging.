"""Repeatable read-only pre-import identity export; retained intent prevents resend.

One invocation starts or polls the same Bulk operation. No product mutations.
Use a new private directory per batch; never delete an uncertain run to retry.
"""

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from datetime import UTC, datetime
from pathlib import Path

from nla_catalog_gateway.shopify_capture_http import ShopifyCaptureHttp
from nla_catalog_gateway.shopify_draft_import import ACCESS_QUERY, FIND_ATTEMPT_HANDLE
from nla_catalog_gateway.shopify_identity_changes import read_identity_changes
from scripts import activate_staging_refresh as activation
from scripts import refresh_staging_catalog as refresh

ROOT = Path(__file__).resolve().parents[1]
QUERY = (ROOT / "graphql/import_identity_snapshot.graphql").read_text()
QUERY_SHA = hashlib.sha256(QUERY.encode()).hexdigest()
CONTROLS = {
    name: (ROOT / "graphql" / f"capture_{name}.graphql").read_text()
    for name in ("counts", "start", "status")
}

DEFINITION_QUERY = (ROOT / "graphql/import_identity_definition.graphql").read_text()


def normalized(value):
    value = value.strip()
    return str(int(value)) if value.isdecimal() else value


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("identity_timestamp_timezone_required")
    return parsed


def scan_identities(path, expected_sha, expected_count):
    """Validate every row and collect both identities; never approve creation."""
    if path.is_symlink() or type(expected_count) is not int or expected_count < 1:
        raise ValueError("invalid_identity_file")
    seen, identities = set(), set()
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for line in source:
            digest.update(line)
            item = json.loads(line)
            if (
                set(item) != {"id", "syncProductId", "powertoolsId"}
                or not isinstance(item["id"], str)
                or re.fullmatch(r"gid://shopify/Product/[1-9][0-9]*", item["id"]) is None
                or item["id"] in seen
            ):
                raise ValueError("invalid_identity_row")
            seen.add(item["id"])
            for key, kind in (
                ("syncProductId", "number_integer"),
                ("powertoolsId", "single_line_text_field"),
            ):
                field = item[key]
                if field is None:
                    continue
                if (
                    type(field) is not dict
                    or field.get("type") != kind
                    or type(field.get("value")) is not str
                    or not field["value"].strip()
                ):
                    raise ValueError("invalid_identity_field")
                identities.add(normalized(field["value"]))
    if digest.hexdigest() != expected_sha or len(seen) != expected_count:
        raise ValueError("identity_hash_or_count_mismatch")
    return identities


def read_fresh_identities(work, shop):
    """Recheck complete receipt + bytes each use. Caller still needs live guards.

    Absence is not atomic with PowerTools and is never creation permission by itself.
    """
    receipt = refresh.document(work / "completed.json")
    intent = refresh.document(work / "intent.json")
    operation = refresh.document(work / "operation.json")
    if (
        receipt["status"] != "complete"
        or receipt["shop"] != shop
        or intent["shop"] != shop
        or intent["querySha256"] != QUERY_SHA
        or receipt["operationId"] != operation["id"]
        or receipt["products"] != intent["products"]
        or receipt["shopifyChanged"] is not False
    ):
        raise ValueError("identity_receipt_mismatch")
    start, end = timestamp(receipt["startedAt"]), timestamp(receipt["completedAt"])
    now = datetime.now(UTC)
    if not timestamp(intent["startedAt"]) <= start <= end <= now:
        raise ValueError("invalid_identity_capture_times")
    if not 0 <= (now - start).total_seconds() <= 1800:
        raise ValueError("identity_export_stale")
    identities = scan_identities(work / "identities.jsonl", receipt["sha256"], receipt["products"])
    return receipt, identities


def verify_missing(work, shop, cardmarket_id, graphql):
    """Full fresh snapshot + live guards for create_draft_once's callback.

    Returns False on an existing identity/handle. Errors fail closed. This cannot
    lock PowerTools or make Shopify's eventual-consistency interfaces atomic.
    """
    if type(cardmarket_id) is not int or not 0 < cardmarket_id < 2**63:
        raise ValueError("invalid_cardmarket_id")
    receipt, identities = read_fresh_identities(work, shop)
    wanted = str(cardmarket_id)
    if wanted in identities:
        return False
    if graphql(ACCESS_QUERY, {})["shop"]["myshopifyDomain"] != shop:
        raise ValueError("identity_guard_wrong_shop")
    for namespace, key, kind in (
        ("sync", "productid", "number_integer"),
        ("powertools", "id", "single_line_text_field"),
    ):
        connection = graphql(DEFINITION_QUERY, dict(namespace=namespace, key=key))[
            "metafieldDefinitions"
        ]
        if connection["pageInfo"]["hasNextPage"] is not False or connection["nodes"] != [
            dict(namespace=namespace, key=key, type={"name": kind})
        ]:
            raise ValueError("identity_definition_changed")
    changes = read_identity_changes(graphql, receipt["startedAt"])
    for product in changes["products"]:
        for field in ("syncSourceId", "powerToolsSourceId"):
            if product[field] is not None and normalized(product[field]) == wanted:
                return False
    found = graphql(FIND_ATTEMPT_HANDLE, {"identifier": {"handle": f"nla-cm-{wanted}"}})["product"]
    if (datetime.now(UTC) - timestamp(receipt["startedAt"])).total_seconds() > 1800:
        raise ValueError("identity_export_stale")
    return found is None


def capture_once(client, shop, work):
    """Caller holds the existing whole-pipeline lock. Never restart a saved intent."""
    if not work.is_absolute() or work.resolve() != work:
        raise ValueError("canonical_absolute_directory_required")
    if not work.exists():
        work.mkdir(mode=0o700)
        activation.sync_directory(work.parent)
    if not work.is_dir():
        raise ValueError("identity_directory_required")
    facts = work.stat()
    if os.name == "posix" and (
        facts.st_uid != os.geteuid() or stat.S_IMODE(facts.st_mode) != 0o700
    ):
        raise ValueError("identity_directory_not_private")

    def count():
        data = client.graphql(CONTROLS["counts"], {"singleQuery": "status:active"})
        value = data["products"]
        if (
            data["shop"]["myshopifyDomain"] != shop
            or value["precision"] != "EXACT"
            or type(value["count"]) is not int
            or value["count"] < 1
        ):
            raise ValueError("identity_count_unconfirmed")
        return value["count"]

    if not (work / "intent.json").exists():
        if list(work.iterdir()):
            raise ValueError("identity_directory_not_empty")
        refresh.publish(
            work / "intent.json",
            dict(shop=shop, querySha256=QUERY_SHA, startedAt=refresh.timestamp(), products=count()),
        )
        response = client.graphql(CONTROLS["start"], {"query": QUERY})["bulkOperationRunQuery"]
        identifier = response["bulkOperation"]["id"]
        if (
            response["userErrors"]
            or re.fullmatch(r"gid://shopify/BulkOperation/[1-9][0-9]*", identifier) is None
        ):
            raise ValueError("identity_start_unconfirmed_inspect_before_retry")
        refresh.publish(work / "operation.json", {"id": identifier})
    intent = refresh.document(work / "intent.json")
    if intent["shop"] != shop or intent["querySha256"] != QUERY_SHA:
        raise ValueError("identity_intent_mismatch")
    identifier = refresh.document(work / "operation.json")["id"]
    if (work / "completed.json").exists():
        receipt, _ = read_fresh_identities(work, shop)
        return receipt
    operation = client.graphql(CONTROLS["status"], {"id": identifier})["bulkOperation"]
    if (
        operation["id"] != identifier
        or operation["type"] != "QUERY"
        or operation["query"].strip() != QUERY.strip()
        or not timestamp(intent["startedAt"])
        <= timestamp(operation["createdAt"])
        <= datetime.now(UTC)
    ):
        raise ValueError("identity_operation_mismatch")
    if operation["status"] in ("CREATED", "RUNNING"):
        return dict(status="running", operationId=identifier, shopifyChanged=False)
    if (
        operation["status"] != "COMPLETED"
        or operation["errorCode"] is not None
        or operation["partialDataUrl"] is not None
        or int(operation["rootObjectCount"]) != intent["products"]
        or count() != intent["products"]
        or not timestamp(operation["createdAt"])
        <= timestamp(operation["completedAt"])
        <= datetime.now(UTC)
    ):
        raise ValueError("identity_export_not_complete")
    target = work / "identities.jsonl"
    with os.fdopen(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as output:
        digest = client.download(
            operation["url"], output, int(operation["fileSize"]), maximum_bytes=256 * 1024**2
        )
        output.flush()
        os.fsync(output.fileno())
    scan_identities(target, digest, intent["products"])
    receipt = dict(
        status="complete",
        shop=shop,
        operationId=identifier,
        startedAt=operation["createdAt"],
        completedAt=operation["completedAt"],
        sha256=digest,
        products=intent["products"],
        shopifyChanged=False,
    )
    refresh.publish(work / "completed.json", receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shop", required=True)
    for name in ("credential-file", "run-root", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        if not __debug__ or sys.platform != "linux" or os.geteuid() != 0:
            raise ValueError("non_optimized_root_linux_required")
        if not all(
            p.is_absolute() and p.resolve() == p
            for p in (args.credential_file, args.run_root, args.output)
        ):
            raise ValueError("canonical_absolute_paths_required")
        os.umask(0o077)
        credentials = json.loads(activation.private_read(args.credential_file))
        client = ShopifyCaptureHttp(
            shop_domain=args.shop,
            api_version="2026-07",
            client_id=credentials["client_id"],
            client_secret=credentials["client_secret"],
        )
        with refresh.pipeline_lock(args.run_root):
            if (args.run_root / "pending-run.json").exists():
                raise ValueError("refresh_pending")
            result = capture_once(client, args.shop, args.output)
        print(json.dumps(result))
        return 0
    except Exception:
        print(json.dumps(dict(status="identity_capture_unconfirmed", shopifyChanged=False)))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
