from __future__ import annotations

import json
import subprocess
import sys

from nla_catalog_gateway import READ_ONLY_PROJECTION, __version__


def test_package_metadata_is_explicit() -> None:
    assert __version__ == "0.0.1"
    assert READ_ONLY_PROJECTION is True


def test_module_smoke_output_is_machine_readable() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "nla_catalog_gateway"],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)
    assert payload == {
        "readOnlyProjection": True,
        "service": "nla-catalog-gateway",
        "status": "foundation",
        "version": "0.0.1",
    }
