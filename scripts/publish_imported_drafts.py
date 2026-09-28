"""Publish verified importer-owned zero-stock drafts to the approved Online Store.

Default disabled. Uses the permanent creation ledger and a terminal publication
receipt. Never recaptures the catalog or writes price, stock, variants or metadata.
"""

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

from nla_catalog_gateway.shopify_capture_http import ShopifyCaptureHttp
from nla_catalog_gateway.shopify_draft_publication import publish_verified_drafts, validate_ledger
from scripts import import_cardtrader_drafts as drafts
from scripts import refresh_staging_catalog as refresh


def run(config_path, ledger, publication_id, *, apply=False, max_products=100):
    if apply is not True:
        return {"status": "disabled", "published": 0, "results": []}
    validate_ledger(ledger)
    _, config = drafts.config_values(config_path)
    if ledger.parent == config["run_root"]:
        raise ValueError("importer_and_refresh_locks_must_be_separate")
    # Same lock ordering as the scheduled market cycle.
    with refresh.pipeline_lock(ledger.parent), refresh.pipeline_lock(config["run_root"]):
        if (ledger.parent / "pending-market-run.json").exists() or (
            config["run_root"] / "pending-run.json"
        ).exists():
            raise ValueError("pending_cycle_requires_inspection")
        credentials = refresh.document(config["config"] / "shopify-app-credentials.json")
        client = ShopifyCaptureHttp(
            config["shop"],
            "2026-07",
            credentials["client_id"],
            credentials["client_secret"],
        )
        result = publish_verified_drafts(
            ledger,
            shop=config["shop"],
            publication_id=publication_id,
            graphql=client.graphql,
            enabled=True,
            max_products=max_products,
        )
        receipt = ledger.parent / ("publication-" + uuid.uuid4().hex + ".json")
        refresh.publish(receipt, dict(result, finishedAt=refresh.timestamp()))
        return dict(result, receipt=str(receipt))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh-config", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--publication", required=True)
    parser.add_argument("--max-products", type=int, default=100)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        if not __debug__ or sys.platform != "linux" or os.geteuid() != 0:
            raise ValueError("non_optimized_root_linux_required")
        os.umask(0o077)
        result = run(
            args.refresh_config,
            args.ledger,
            args.publication,
            apply=args.apply,
            max_products=args.max_products,
        )
        print(json.dumps({k: v for k, v in result.items() if k != "results"}))
        return 0 if result["status"] in ("disabled", "publication_complete") else 1
    except (Exception, KeyboardInterrupt):
        # No claim of no writes: an interrupted mutation may have succeeded.
        print(json.dumps({"status": "publication_unconfirmed_inspect_ledger"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
