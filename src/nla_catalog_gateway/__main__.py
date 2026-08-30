"""Container smoke entry point for the platform foundation."""

from __future__ import annotations

import json

from nla_catalog_gateway import READ_ONLY_PROJECTION, __version__


def main() -> None:
    """Print a machine-readable foundation status and exit successfully."""
    print(
        json.dumps(
            {
                "readOnlyProjection": READ_ONLY_PROJECTION,
                "service": "nla-catalog-gateway",
                "status": "foundation",
                "version": __version__,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
