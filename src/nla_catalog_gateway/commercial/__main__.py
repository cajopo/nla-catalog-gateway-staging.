"""Explicit entry point; the operational runtime never starts the pilot."""

from nla_catalog_gateway.commercial.pilot import main

if __name__ == "__main__":
    raise SystemExit(main())
