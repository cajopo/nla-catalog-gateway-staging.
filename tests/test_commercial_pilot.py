from __future__ import annotations

import json
import runpy
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from nla_catalog_gateway.commercial import pilot

NOW = datetime(2026, 10, 20, 12, tzinfo=UTC)
CHECK = ["check", "--shop-domain", "pilot.myshopify.com", "--shop-gid", "gid://shopify/Shop/103"]


def _decision(*, allowed=True):
    return SimpleNamespace(
        allowed=allowed,
        observed_at=NOW,
        valid_until=NOW if allowed else None,
        reason="active" if allowed else "no_subscription",
        plan_handle="catalog-complete" if allowed else None,
    )


def test_two_shop_demo_exercises_isolation_and_denied_subscription():
    report = pilot.demo(now=NOW)
    assert report["mode"] == "synthetic_demo"
    assert report["isolatedWorkspaces"] is True
    assert report["liveRequests"] == report["runtimeChanges"] == 0
    alpha, beta = report["shops"]
    assert alpha["shopGid"] != beta["shopGid"]
    assert alpha["subscription"]["allowed"] is True
    assert alpha["eligibility"]["catalog"] == "eligible"
    assert alpha["eligibility"]["importer"] == "operator_authorization_required"
    assert beta["subscription"]["allowed"] is False
    assert beta["eligibility"]["catalog"] == "subscription_required"
    assert beta["eligibility"]["importer"] == "subscription_required"
    assert all(shop["activation"] == "not_performed" for shop in (alpha, beta))
    assert all(shop["installationVerified"] is False for shop in (alpha, beta))


def test_operator_authorization_does_not_activate_importer():
    identity = SimpleNamespace(shop_domain="demo.myshopify.com", shop_gid="gid://shopify/Shop/1")
    report = pilot._report(identity, _decision(), importer_authorized=True, synthetic=False)
    assert report["eligibility"]["importer"] == "eligible"
    assert report["activation"] == "not_performed"
    assert report["installationVerified"] is False


def test_preview_is_explicitly_synthetic_and_escapes_shop_text():
    report = pilot.demo(now=NOW)
    report["shops"][0]["shopDomain"] = "<script>alert('unsafe')</script>"
    document = pilot.render_preview(report)
    assert "<script>" not in document
    assert "&lt;script&gt;" in document
    assert "dati sintetici" in document
    assert "abbonamento reale" in document
    assert "Richiede abbonamento" in document


def test_demo_command_and_new_html_file(tmp_path, capsys):
    destination = tmp_path / "preview.html"
    assert pilot.main(["demo", "--html", str(destination)]) == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "synthetic_demo"
    assert "Dimostrazione locale" in destination.read_text(encoding="utf-8")
    original = destination.read_bytes()
    assert pilot.main(["demo", "--html", str(destination)]) == 1
    assert json.loads(capsys.readouterr().out)["result"] == "rejected"
    assert destination.read_bytes() == original


def test_demo_command_without_output_file(capsys):
    assert pilot.main(["demo"]) == 0
    assert json.loads(capsys.readouterr().out)["liveRequests"] == 0


@pytest.mark.parametrize("authorized", [False, True])
def test_provision_command_is_local_idempotent_and_rejects_conflicting_consent(
    tmp_path, capsys, authorized
):
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    command = [
        "provision",
        "--root",
        str(root.resolve()),
        "--shop-domain",
        "pilot.myshopify.com",
        "--shop-gid",
        "gid://shopify/Shop/103",
    ]
    if authorized:
        command.append("--authorize-importer")
    assert pilot.main(command) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["result"] == "workspace_provisioned"
    assert first["installationVerified"] is False
    assert first["importerOperatorAuthorized"] is authorized
    assert first["activation"] == "not_performed"
    assert pilot.main(command) == 0
    assert json.loads(capsys.readouterr().out) == first
    if not authorized:
        assert pilot.main([*command, "--authorize-importer"]) == 1
        assert json.loads(capsys.readouterr().out)["result"] == "rejected"


def test_check_uses_only_explicit_commercial_environment(monkeypatch, capsys):
    calls = []

    class Transport:
        def __init__(self, **kwargs):
            calls.append(kwargs)

    class Client:
        def __init__(self, transport, policy):
            assert isinstance(transport, Transport)
            assert policy.app_gid == "gid://shopify/App/100"
            assert policy.allowed_plan_handles == frozenset({"catalog-complete"})

        def verify(self, **kwargs):
            calls.append(kwargs)
            return _decision()

    monkeypatch.setattr(pilot, "StdlibPartnerTransport", Transport)
    monkeypatch.setattr(pilot, "PartnerSubscriptionClient", Client)
    environment = {
        "NLA_COMMERCIAL_APP_GID": "gid://shopify/App/100",
        "NLA_COMMERCIAL_PLAN_HANDLES": " catalog-complete ",
        "NLA_COMMERCIAL_PARTNER_ORGANIZATION_ID": "123",
        "NLA_COMMERCIAL_PARTNER_ACCESS_TOKEN": "test-only",
    }
    assert pilot.main(CHECK, environ=environment) == 0
    output = capsys.readouterr().out
    report = json.loads(output)
    assert report["mode"] == "shopify_subscription_check"
    assert report["eligibility"]["importer"] == "operator_authorization_required"
    assert "test-only" not in output
    assert calls[0] == {"organization_id": "123", "access_token": "test-only"}
    assert calls[1]["shop_domain"] == "pilot.myshopify.com"
    assert calls[1]["shop_gid"] == "gid://shopify/Shop/103"
    assert calls[1]["now"].tzinfo is UTC


@pytest.mark.parametrize("environment", [{}, {"NLA_SHOP_DOMAIN": "existing.myshopify.com"}])
def test_check_never_uses_existing_runtime_credentials(environment, capsys):
    assert pilot.main(CHECK, environ=environment) == 1
    assert json.loads(capsys.readouterr().out) == pilot._ERROR


def test_default_environment_and_remote_errors_do_not_leak(monkeypatch, capsys):
    monkeypatch.setattr(pilot.os, "environ", {})
    assert pilot.main(CHECK) == 1
    assert "rejected" in capsys.readouterr().out

    def fail():
        raise RuntimeError("secret must never appear")

    monkeypatch.setattr(pilot, "demo", fail)
    assert pilot.main(["demo"]) == 1
    output = capsys.readouterr().out
    assert "secret must never appear" not in output
    assert json.loads(output) == pilot._ERROR


def test_entry_point_and_usage_error(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["commercial", "demo"])
    with pytest.raises(SystemExit) as captured:
        runpy.run_module("nla_catalog_gateway.commercial", run_name="__main__")
    assert captured.value.code == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "synthetic_demo"
    with pytest.raises(SystemExit) as captured:
        pilot.main([])
    assert captured.value.code == 2
    assert "required" in capsys.readouterr().err


def test_importing_pilot_entry_point_never_runs_it(monkeypatch, capsys):
    def unexpected_start(*args, **kwargs):
        raise AssertionError("import started the pilot")

    monkeypatch.setattr(pilot, "main", unexpected_start)
    runpy.run_module("nla_catalog_gateway.commercial", run_name="commercial_import_test")
    assert capsys.readouterr().out == ""


def test_denied_live_check_has_nonzero_exit_status(monkeypatch, capsys):
    monkeypatch.setattr(pilot, "_check", lambda *args: {"subscription": {"allowed": False}})
    assert pilot.main(CHECK, environ={}) == 2
    assert json.loads(capsys.readouterr().out)["subscription"]["allowed"] is False
