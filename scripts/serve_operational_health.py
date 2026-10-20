"""Serve only sanitized operational status on a fixed loopback socket."""

import argparse
from pathlib import Path

import uvicorn

from nla_catalog_gateway.operational_health import OperationalHealthApp


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observation", required=True, type=Path)
    args = parser.parse_args(argv)
    uvicorn.run(
        OperationalHealthApp(args.observation),
        host="127.0.0.1",
        port=10002,
        workers=1,
        lifespan="off",
        access_log=False,
        log_config=None,
        log_level="critical",
        proxy_headers=False,
        server_header=False,
        limit_concurrency=16,
        timeout_keep_alive=2,
        timeout_graceful_shutdown=5,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
