from __future__ import annotations

import json

from nla_catalog_gateway import READ_ONLY_PROJECTION, __version__
from nla_catalog_gateway.__main__ import main


def test_package_metadata_is_explicit() -> None:
    assert __version__ == "0.0.1"
    assert READ_ONLY_PROJECTION is True


def test_module_smoke_output_is_machine_readable(capsys) -> None:
    main()
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "readOnlyProjection": True,
        "service": "nla-catalog-gateway",
        "status": "foundation",
        "version": "0.0.1",
    }
