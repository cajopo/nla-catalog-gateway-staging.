from __future__ import annotations

import hashlib
import json
import runpy
import sys

import pytest
from scripts import verify_staging_runtime as verifier

import test_staging_generation as packages


@pytest.fixture
def candidate(tmp_path):
    package = packages._make_package(tmp_path)
    return package, {
        "candidate_directory": package.directory,
        "manifest_sha256": package.manifest_sha256,
        "code_sha": package.evidence.code_sha,
        "summary_sha256": package.evidence.summary_sha256,
        "record_count": len(package.records),
    }


def test_real_package_binds_to_runtime_without_changing_files(candidate):
    package, config = candidate
    before = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in package.directory.iterdir()
    }
    result = verifier.verify_runtime(**config)
    assert result["status"] == "verified"
    assert result["runtimeBinding"] is True
    assert result["activeCatalogChanged"] is False
    assert result["records"] == len(package.records)
    assert sum(result["games"].values()) == result["records"]
    assert result["manifestSha256"] == config["manifest_sha256"]
    assert result["producerCodeSha"] == config["code_sha"]
    assert result["summarySha256"] == config["summary_sha256"]
    assert result["datasetGeneration"] == package.evidence.dataset_generation
    assert {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in package.directory.iterdir()
    } == before


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("record_count", True),
        ("record_count", 0),
        ("record_count", -1),
        ("record_count", 1.0),
        ("record_count", 99999),
        ("summary_sha256", None),
        ("summary_sha256", "not-a-pin"),
        ("summary_sha256", "0" * 64),
        ("manifest_sha256", "0" * 64),
        ("code_sha", "0" * 40),
        ("code_sha", "invalid"),
    ],
)
def test_mismatched_or_invalid_capture_evidence_is_rejected(candidate, field, value):
    _, config = candidate
    with pytest.raises(ValueError):
        verifier.verify_runtime(**{**config, field: value})


def _argv(config):
    return [
        item for key, value in config.items() for item in ("--" + key.replace("_", "-"), str(value))
    ]


def test_cli_emits_receipt_after_real_runtime_verification(candidate, capsys):
    _, config = candidate
    assert verifier.main(_argv(config)) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out)["records"] == config["record_count"]


@pytest.mark.parametrize("args", [[], ["--unrecognized", "SECRET"], ["--record-count", "SECRET"]])
def test_invalid_cli_does_not_disclose_arguments(args, capsys):
    assert verifier.main(args) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Runtime verification failed; no catalog was activated.\n"


@pytest.mark.parametrize("error", [RuntimeError("SECRET"), KeyboardInterrupt()])
def test_failed_check_has_no_success_receipt(candidate, monkeypatch, capsys, error):
    _, config = candidate

    def fail(**_):
        raise error

    monkeypatch.setattr(verifier, "verify_runtime", fail)
    assert verifier.main(_argv(config)) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Runtime verification failed; no catalog was activated.\n"


def test_module_entry_point_rejects_missing_arguments(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["verify_staging_runtime.py"])
    with pytest.raises(SystemExit, match="1"):
        runpy.run_path(verifier.__file__, run_name="__main__")
    assert capsys.readouterr().out == ""
