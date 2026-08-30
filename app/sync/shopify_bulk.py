from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import httpx

BULK_QUERY = r'''
query NlaCatalogSnapshot {
  products(query: "status:active published_status:published") {
    edges {
      node {
        id
        legacyResourceId
        handle
        title
        status
        productType
        vendor
        tags
        totalInventory
        tracksInventory
        onlineStoreUrl
        updatedAt
        syncProductId: metafield(namespace: "sync", key: "productid") { value }
        powertoolsId: metafield(namespace: "powertools", key: "id") { value }
        featuredMedia {
          mediaContentType
          preview { image { url altText width height } }
        }
        variants {
          edges {
            node {
              id
              legacyResourceId
              title
              sku
              barcode
              price
              compareAtPrice
              availableForSale
              inventoryQuantity
              sellableOnlineQuantity
              inventoryPolicy
              selectedOptions { name value }
            }
          }
        }
      }
    }
  }
}
'''.strip()

RUN_MUTATION = r'''
mutation RunNlaCatalogSnapshot($query: String!) {
  bulkOperationRunQuery(query: $query) {
    bulkOperation { id status createdAt }
    userErrors { field message }
  }
}
'''.strip()

STATUS_QUERY = r'''
query NlaBulkStatus($id: ID!) {
  bulkOperation(id: $id) {
    id status errorCode completedAt rootObjectCount objectCount fileSize url partialDataUrl
  }
}
'''.strip()


@dataclass(frozen=True, slots=True)
class BulkResult:
    operation_id: str
    root_object_count: int
    object_count: int
    file_size: int
    url: str


def _endpoint(shop: str, api_version: str) -> str:
    clean = shop.strip().lower().removeprefix("https://").rstrip("/")
    if not clean.endswith(".myshopify.com"):
        raise ValueError("SHOPIFY_SHOP must be a *.myshopify.com domain")
    return f"https://{clean}/admin/api/{api_version}/graphql.json"


def _graphql(client: httpx.Client, endpoint: str, query: str, variables: dict) -> dict:
    response = client.post(endpoint, json={"query": query, "variables": variables})
    response.raise_for_status()
    payload = response.json()
    if payload.get("errors"):
        raise RuntimeError(f"Shopify GraphQL error: {payload['errors']}")
    return payload["data"]


def run_bulk_export(
    shop: str,
    token: str,
    api_version: str = "2026-07",
    timeout_seconds: int = 3600,
    poll_seconds: int = 5,
) -> BulkResult:
    endpoint = _endpoint(shop, api_version)
    headers = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}
    with httpx.Client(headers=headers, timeout=60.0, follow_redirects=True) as client:
        data = _graphql(client, endpoint, RUN_MUTATION, {"query": BULK_QUERY})
        result = data["bulkOperationRunQuery"]
        if result["userErrors"]:
            raise RuntimeError(f"Bulk operation rejected: {result['userErrors']}")
        operation_id = result["bulkOperation"]["id"]
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            operation = _graphql(client, endpoint, STATUS_QUERY, {"id": operation_id})["bulkOperation"]
            status = operation["status"]
            if status == "COMPLETED":
                if not operation.get("url"):
                    raise RuntimeError("Bulk operation completed without a result URL")
                return BulkResult(
                    operation_id=operation_id,
                    root_object_count=int(operation.get("rootObjectCount") or 0),
                    object_count=int(operation.get("objectCount") or 0),
                    file_size=int(operation.get("fileSize") or 0),
                    url=operation["url"],
                )
            if status in {"FAILED", "CANCELED", "EXPIRED"}:
                raise RuntimeError(f"Bulk operation {status}: {operation.get('errorCode') or 'unknown'}")
            time.sleep(poll_seconds)
    raise TimeoutError("Timed out waiting for Shopify bulk operation")


def download_snapshot(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".downloading")
    temporary.unlink(missing_ok=True)
    with httpx.stream("GET", url, follow_redirects=True, timeout=120.0) as response:
        response.raise_for_status()
        with temporary.open("wb") as output:
            for chunk in response.iter_bytes(1024 * 1024):
                output.write(chunk)
    temporary.replace(destination)
