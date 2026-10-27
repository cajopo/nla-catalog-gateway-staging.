from __future__ import annotations

import json
from importlib.resources import files

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


def test_taxonomy_mapping_is_packaged() -> None:
    mapping = files("nla_catalog_gateway").joinpath("catalog_taxonomy.v1.json")
    payload = json.loads(mapping.read_text(encoding="utf-8"))
    assert payload["schemaVersion"] == 1
    assert payload["classificationRuleVersion"] == "2026-10-27.1"
