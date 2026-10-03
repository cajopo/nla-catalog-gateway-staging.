"""Operator entry points use synthetic inputs and never contact a remote service."""

import json
import os
import runpy
import stat
import sys
import urllib.request
from contextlib import contextmanager, nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts import capture_cardtrader_catalog as source_cli
from scripts import capture_import_identities as identity_cli
from scripts import compare_cardtrader_catalog as compare_cli
from scripts import prepare_cardtrader_reference as prepare_cli


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("real network is forbidden in operator boundary tests")

    monkeypatch.setattr(urllib.request.OpenerDirector, "open", forbidden)
    monkeypatch.setattr(os, "umask", lambda _: 0o077)


def arguments(module, root):
    fields = {
        source_cli: ("credential-file", "output"),
        identity_cli: ("credential-file", "run-root", "output"),
        compare_cli: ("capture", "projection", "output"),
        prepare_cli: ("capture", "projection", "parent", "output"),
    }[module]
    argv = [module.__name__]
    for field in fields:
        argv.extend(("--" + field, str(root / field)))
    if module is identity_cli:
        argv.extend(("--shop", "test.myshopify.com"))
    if module in (compare_cli, prepare_cli):
        argv.extend(("--projection-sha256", "a" * 64))
    if module is prepare_cli:
        argv.extend(("--parent-sha256", "b" * 64, "--generator-sha", "c" * 40))
    return argv


@pytest.mark.parametrize("module", [source_cli, identity_cli, compare_cli, prepare_cli])
def test_module_entrypoint_rejects_missing_inputs_offline(module, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", arguments(module, tmp_path))
    with pytest.raises(SystemExit) as exited:
        runpy.run_path(module.__file__, run_name="__main__")
    assert exited.value.code == 1
    assert "failed" in capsys.readouterr().out or module is identity_cli
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("invalid", ["directory", "mode", "owner"])
def test_source_credentials_must_be_private_regular_files(tmp_path, monkeypatch, capsys, invalid):
    path = tmp_path / "credential-file"
    path.mkdir() if invalid == "directory" else path.write_text('{"api_token":"test-only-token"}')
    original = Path.lstat

    def facts(target, *args, **kwargs):
        if target == path and invalid != "directory":
            return SimpleNamespace(
                st_mode=stat.S_IFREG | (0o644 if invalid == "mode" else 0o600),
                st_uid=1 if invalid == "owner" else 0,
            )
        return original(target, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", facts)
    monkeypatch.setattr(source_cli, "os", SimpleNamespace(name="posix", geteuid=lambda: 0))
    monkeypatch.setattr(sys, "argv", arguments(source_cli, tmp_path))
    assert source_cli.main() == 1
    assert json.loads(capsys.readouterr().out) == {
        "status": "capture_failed",
        "automaticImportEnabled": False,
    }


@pytest.mark.parametrize("case", ["success", "non_linux", "non_root", "failure"])
def test_identity_main_binds_arguments_and_redacts_failures(case, tmp_path, monkeypatch, capsys):
    events = []
    credentials = {"client_id": "fixture-id", "client_secret": "test-only-secret"}

    @contextmanager
    def lock(path):
        events.append(("lock", path))
        yield
        events.append(("unlock", path))

    def client(*args):
        assert args == ("test.myshopify.com", "2026-07", "fixture-id", "test-only-secret")
        events.append(("client",))
        return SimpleNamespace(graphql=object())

    def execute(*args):
        events.append(("execute",))
        assert args[1:] == ("test.myshopify.com", tmp_path / "output")
        if case == "failure":
            raise RuntimeError("private-error-must-not-be-printed")
        return dict(status="complete")

    monkeypatch.setattr(
        identity_cli, "sys", SimpleNamespace(platform="win32" if case == "non_linux" else "linux")
    )
    monkeypatch.setattr(
        identity_cli,
        "os",
        SimpleNamespace(geteuid=lambda: 1 if case == "non_root" else 0, umask=lambda _: None),
    )
    monkeypatch.setattr(identity_cli.refresh, "pipeline_lock", lock)
    monkeypatch.setattr(
        identity_cli.activation, "private_read", lambda _: json.dumps(credentials).encode()
    )
    monkeypatch.setattr(identity_cli, "ShopifyCaptureHttp", client)
    monkeypatch.setattr(identity_cli, "capture_once", execute)
    monkeypatch.setattr(sys, "argv", arguments(identity_cli, tmp_path))
    assert identity_cli.main() == (0 if case == "success" else 1)
    output = capsys.readouterr().out
    assert "private-error-must-not-be-printed" not in output and "test-only-secret" not in output
    if case == "success":
        assert json.loads(output)["status"] == "complete"
        assert events[0] == ("client",)
        assert events[1:] == [
            ("lock", tmp_path / "run-root"),
            ("execute",),
            ("unlock", tmp_path / "run-root"),
        ]
    elif case in ("non_linux", "non_root"):
        assert events == []
    else:
        assert ("execute",) in events


@pytest.mark.parametrize("case", ["success", "relative", "failure"])
def test_prepare_main_reports_counts_without_activating(tmp_path, monkeypatch, capsys, case):
    calls = []

    def prepare(*args):
        calls.append(args)
        assert args == (
            tmp_path / "capture",
            tmp_path / "projection",
            "a" * 64,
            tmp_path / "parent",
            "b" * 64,
            tmp_path / "output",
            "c" * 40,
        )
        if case == "failure":
            raise ValueError("private-error-must-not-be-printed")
        return dict(candidates=[{}], exceptions=[{}, {}], referenceEvidence=dict(addedRecords=1))

    monkeypatch.setattr(prepare_cli, "prepare", prepare)
    argv = arguments(prepare_cli, tmp_path)
    if case == "relative":
        argv[argv.index("--output") + 1] = "relative"
    monkeypatch.setattr(sys, "argv", argv)
    assert prepare_cli.main() == (0 if case == "success" else 1)
    output = capsys.readouterr().out
    assert "private-error-must-not-be-printed" not in output
    report = json.loads(output)
    assert report["shopifyChanged"] is False
    if case == "success":
        assert report == dict(
            status="reference_prepared",
            candidates=1,
            exceptions=2,
            addedRecords=1,
            activated=False,
            shopifyChanged=False,
        )
    assert len(calls) == (0 if case == "relative" else 1)


@pytest.mark.parametrize("case", ["identity_relative", "identity_pending"])
def test_identity_guards_stop_before_dispatch(tmp_path, monkeypatch, capsys, case):
    monkeypatch.setattr(identity_cli, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(
        identity_cli, "os", SimpleNamespace(geteuid=lambda: 0, umask=lambda _: None)
    )
    monkeypatch.setattr(identity_cli.refresh, "pipeline_lock", lambda _: nullcontext())
    monkeypatch.setattr(
        identity_cli.activation,
        "private_read",
        lambda _: b'{"client_id":"fixture-id","client_secret":"test-only-secret"}',
    )
    monkeypatch.setattr(identity_cli, "ShopifyCaptureHttp", lambda *_: object())

    def forbidden(*args, **kwargs):
        pytest.fail("an invalid operator prerequisite reached remote dispatch")

    monkeypatch.setattr(identity_cli, "capture_once", forbidden)
    argv = arguments(identity_cli, tmp_path)
    if case == "identity_relative":
        argv[argv.index("--output") + 1] = "relative"
    else:
        root = tmp_path / "run-root"
        root.mkdir()
        (root / "pending-run.json").write_text("{}")
    monkeypatch.setattr(sys, "argv", argv)
    assert identity_cli.main() == 1
    assert json.loads(capsys.readouterr().out)["status"] == "identity_capture_unconfirmed"
