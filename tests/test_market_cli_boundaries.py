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
from scripts import import_cardtrader_drafts as import_cli
from scripts import prepare_cardtrader_reference as prepare_cli
from scripts import publish_imported_drafts as publish_cli
from scripts import refresh_market_catalog as market_cli


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
        import_cli: ("refresh-config", "capture", "identities", "run", "ledger"),
        prepare_cli: ("capture", "projection", "parent", "output"),
        publish_cli: ("refresh-config", "ledger"),
        market_cli: (
            "state",
            "refresh-config",
            "refresh-package",
            "ledger",
            "cardtrader-credentials",
        ),
    }[module]
    argv = [module.__name__]
    for field in fields:
        argv.extend(("--" + field, str(root / field)))
    if module is identity_cli:
        argv.extend(("--shop", "test.myshopify.com"))
    if module in (compare_cli, prepare_cli):
        argv.extend(("--projection-sha256", "a" * 64))
    if module is prepare_cli:
        argv.extend(("--parent-sha256", "b" * 64))
    if module in (prepare_cli, import_cli, market_cli):
        argv.extend(("--generator-sha", "c" * 40))
    if module is publish_cli:
        argv.extend(("--publication", "gid://shopify/Publication/12"))
    return argv


@pytest.mark.parametrize(
    "module",
    [source_cli, identity_cli, compare_cli, import_cli, prepare_cli, publish_cli, market_cli],
)
def test_module_entrypoint_rejects_missing_inputs_offline(module, tmp_path, monkeypatch, capsys):
    argv = arguments(module, tmp_path)
    if module is publish_cli:
        argv.append("--apply")
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as exited:
        runpy.run_path(module.__file__, run_name="__main__")
    assert exited.value.code == 1
    assert "failed" in capsys.readouterr().out or module in (
        identity_cli,
        import_cli,
        publish_cli,
        market_cli,
    )
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


@pytest.mark.parametrize("module", [identity_cli, import_cli, publish_cli, market_cli])
@pytest.mark.parametrize("case", ["success", "non_linux", "non_root", "failure"])
def test_operator_main_binds_arguments_and_redacts_failures(
    module, case, tmp_path, monkeypatch, capsys
):
    events = []
    config = dict(
        shop="test.myshopify.com", run_root=tmp_path / "refresh-state", config=tmp_path / "config"
    )
    credentials = {
        "client_id": "fixture-id",
        "client_secret": "test-only-secret",
        "api_token": "test-only",
    }
    expected = {
        identity_cli: "complete",
        import_cli: "batch_complete",
        publish_cli: "publication_complete",
        market_cli: "draft_cycle_partial",
    }[module]

    @contextmanager
    def lock(path):
        events.append(("lock", path))
        yield
        events.append(("unlock", path))

    def client(*args):
        assert args == (config["shop"], "2026-07", "fixture-id", "test-only-secret")
        events.append(("client",))
        return SimpleNamespace(graphql=object())

    def execute(*args, **kwargs):
        events.append(("execute",))
        if module is identity_cli:
            assert args[1:] == (config["shop"], tmp_path / "output") and not kwargs
        elif module is import_cli:
            assert args[:5] == tuple(
                tmp_path / name
                for name in ("refresh-config", "capture", "identities", "run", "ledger")
            )
            assert args[5] == "c" * 40 and kwargs == dict(apply=True, max_attempts=2)
        elif module is publish_cli:
            assert args == (
                tmp_path / "refresh-config",
                tmp_path / "ledger",
                "gid://shopify/Publication/12",
            )
            assert kwargs == dict(apply=True, max_products=2)
        else:
            assert args[:5] == (
                tmp_path / "state",
                tmp_path / "refresh-config",
                tmp_path / "refresh-package",
                tmp_path / "ledger",
                "c" * 40,
            )
            assert kwargs == dict(
                apply_drafts=True,
                max_attempts=2,
                max_batches=3,
                publish_online_store="gid://shopify/Publication/12",
            )
        if case == "failure":
            raise RuntimeError("private-error-must-not-be-printed")
        return dict(status=expected)

    monkeypatch.setattr(
        module, "sys", SimpleNamespace(platform="win32" if case == "non_linux" else "linux")
    )
    monkeypatch.setattr(
        module,
        "os",
        SimpleNamespace(geteuid=lambda: 1 if case == "non_root" else 0, umask=lambda _: None),
    )
    monkeypatch.setattr(import_cli, "config_values", lambda _: ({}, config))
    monkeypatch.setattr(import_cli.refresh, "document", lambda _: credentials)
    monkeypatch.setattr(import_cli.refresh, "pipeline_lock", lock)
    monkeypatch.setattr(
        identity_cli.activation, "private_read", lambda _: json.dumps(credentials).encode()
    )
    if module is not publish_cli:
        monkeypatch.setattr(module, "ShopifyCaptureHttp", client)
    if module is market_cli:
        monkeypatch.setattr(module, "CardTraderCatalogClient", lambda token: object())
    action = {
        identity_cli: "capture_once",
        import_cli: "run_locked",
        publish_cli: "run",
        market_cli: "cycle",
    }[module]
    monkeypatch.setattr(module, action, execute)
    argv = arguments(module, tmp_path)
    if module is import_cli:
        argv += ["--apply", "--max-attempts", "2"]
    elif module is publish_cli:
        argv += ["--apply", "--max-products", "2"]
    elif module is market_cli:
        argv += [
            "--apply-drafts",
            "--max-attempts",
            "2",
            "--max-batches",
            "3",
            "--publish-online-store",
            "gid://shopify/Publication/12",
        ]
    monkeypatch.setattr(sys, "argv", argv)
    assert module.main() == (0 if case == "success" else 1)
    output = capsys.readouterr().out
    assert "private-error-must-not-be-printed" not in output and "test-only-secret" not in output
    if case == "success":
        assert json.loads(output)["status"] == expected
    if case in ("non_linux", "non_root"):
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


@pytest.mark.parametrize("case", ["identity_relative", "identity_pending", "market_same_locks"])
def test_operator_guards_stop_before_dispatch(tmp_path, monkeypatch, capsys, case):
    module = market_cli if case == "market_same_locks" else identity_cli
    monkeypatch.setattr(module, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(module, "os", SimpleNamespace(geteuid=lambda: 0, umask=lambda _: None))
    monkeypatch.setattr(import_cli.refresh, "pipeline_lock", lambda _: nullcontext())
    monkeypatch.setattr(
        identity_cli.activation,
        "private_read",
        lambda _: b'{"client_id":"fixture-id","client_secret":"test-only-secret"}',
    )
    monkeypatch.setattr(module, "ShopifyCaptureHttp", lambda *_: object())

    def forbidden(*args, **kwargs):
        pytest.fail("an invalid operator prerequisite reached remote dispatch")

    monkeypatch.setattr(module, "cycle" if module is market_cli else "capture_once", forbidden)
    argv = arguments(module, tmp_path)
    if case == "identity_relative":
        argv[argv.index("--output") + 1] = "relative"
    elif case == "identity_pending":
        root = tmp_path / "run-root"
        root.mkdir()
        (root / "pending-run.json").write_text("{}")
    else:
        monkeypatch.setattr(
            import_cli, "config_values", lambda _: ({}, dict(run_root=tmp_path / "state"))
        )
    monkeypatch.setattr(sys, "argv", argv)
    assert module.main() == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == (
        "market_cycle_stopped_inspect_pending"
        if module is market_cli
        else "identity_capture_unconfirmed"
    )
