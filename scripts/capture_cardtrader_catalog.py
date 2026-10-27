"""Read-only catalog acquisition entry point; never creates Shopify products."""

import argparse
import json
import os
import stat
from pathlib import Path

from nla_catalog_gateway.cardtrader_capture import capture_catalog
from nla_catalog_gateway.cardtrader_catalog import CardTraderCatalogClient
from nla_catalog_gateway.cardtrader_scope import GAME_SCOPES


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credential-file", type=Path, required=True)
    parser.add_argument("--game-scope", choices=GAME_SCOPES, default="legacy")
    parser.add_argument(
        "--output", type=Path, required=True, help="New absolute private run directory"
    )
    args = parser.parse_args()
    try:
        facts = args.credential_file.lstat()
        if not stat.S_ISREG(facts.st_mode):
            raise ValueError("credential_not_regular")
        if os.name == "posix" and (
            facts.st_uid != os.geteuid() or stat.S_IMODE(facts.st_mode) != 0o600
        ):
            raise ValueError("credential_not_private")
        credentials = json.loads(args.credential_file.read_bytes())
        client = CardTraderCatalogClient(credentials["api_token"])
        result = capture_catalog(client, args.output, game_scope=args.game_scope)
        print(json.dumps({key: value for key, value in result.items() if key != "files"}))
        return 0
    except Exception:
        print(json.dumps({"status": "capture_failed", "automaticImportEnabled": False}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
