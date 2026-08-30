from __future__ import annotations

import json
import logging
from dataclasses import asdict

from app.config import Settings, get_settings
from app.sync.build_index import build_catalog
from app.sync.shopify_bulk import download_snapshot, run_bulk_export

LOGGER = logging.getLogger("nla_gateway.bootstrap")


def bootstrap_catalog(settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    if settings.database_path.is_file():
        return {"status": "already_exists", "database": str(settings.database_path)}

    if settings.shopify_bulk_url:
        download_snapshot(settings.shopify_bulk_url, settings.snapshot_path)
        operation_id = "provided-url"
        expected_count = settings.expected_product_count
    elif settings.shopify_shop and settings.shopify_admin_token:
        bulk = run_bulk_export(
            settings.shopify_shop,
            settings.shopify_admin_token,
            settings.shopify_api_version,
        )
        download_snapshot(bulk.url, settings.snapshot_path)
        operation_id = bulk.operation_id
        expected_count = settings.expected_product_count or bulk.root_object_count
    elif settings.snapshot_path.is_file():
        operation_id = "local-snapshot"
        expected_count = settings.expected_product_count
    else:
        raise RuntimeError(
            "No bootstrap source. Set SHOPIFY_BULK_URL or SHOPIFY_SHOP + SHOPIFY_ADMIN_TOKEN, "
            "or place SNAPSHOT_PATH on disk."
        )

    result = build_catalog(
        settings.snapshot_path,
        settings.database_path,
        expected_count=expected_count,
    )
    payload = {"status": "built", "operationId": operation_id, **asdict(result)}
    LOGGER.info("Catalog bootstrap completed: %s", json.dumps(payload, sort_keys=True))
    return payload


if __name__ == "__main__":
    print(json.dumps(bootstrap_catalog(), indent=2, sort_keys=True))
