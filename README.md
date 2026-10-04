# NLA Catalog Gateway

Read-only catalog infrastructure for the Next Level Arena Shopify storefront.

This repository is being rebuilt through isolated workstreams. The current foundation intentionally contains no production catalog API and no Shopify credentials or data artifacts. Runtime features enter only through their dedicated pull requests after the platform pipeline is green.

## Approved system boundary

- Shopify is the commercial source of truth.
- TCG PowerTools continues to synchronize Shopify.
- The gateway is a derived, read-only projection for catalog browse, search, filters and deep pagination.
- The Shopify theme consumes the gateway only through the approved integration layer.
- Product pages, cart and checkout remain Shopify-native.

## Local verification

```bash
python -m pip install -e '.[dev]'
ruff check .
ruff format --check .
pytest --cov=nla_catalog_gateway --cov-report=term-missing
python scripts/preflight_repo.py
python -m build
```

A minimal container smoke test is available:

```bash
docker build -t nla-catalog-gateway:foundation .
docker run --rm nla-catalog-gateway:foundation python -m nla_catalog_gateway
```

The expected output is a JSON foundation status. The image's default command is the fail-closed
staging runtime launcher; it requires the host-only configuration and external verified package
documented in `docs/workstreams/ws-09b-staging-deploy.md`. Building or running this smoke is not a
claim that the catalog runtime has been deployed.
