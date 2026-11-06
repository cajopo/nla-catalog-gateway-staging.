"""Operator-only commercial pilot commands, isolated from the NLA runtime."""

from __future__ import annotations

import argparse
import html
import json
import os
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path

from nla_catalog_gateway.commercial.entitlements import (
    EntitlementPolicy,
    PartnerSubscriptionClient,
    StdlibPartnerTransport,
)
from nla_catalog_gateway.commercial.tenants import TenantIdentity, provision_tenant

PRODUCT = "NLA TCG Catalog"
_ERROR = {"schemaVersion": 1, "result": "rejected"}
_DEMO_APP = "gid://shopify/App/100"
_DEMO_PLAN = "catalog-complete"


def _now() -> datetime:
    return datetime.now(UTC)


def _report(identity, decision, *, importer_authorized: bool, synthetic: bool) -> dict:
    """Report a commercial eligibility check, never a runtime activation."""
    importer = "eligible" if decision.allowed else "subscription_required"
    if decision.allowed and not importer_authorized:
        importer = "operator_authorization_required"
    return {
        "schemaVersion": 1,
        "product": PRODUCT,
        "mode": "synthetic_demo" if synthetic else "shopify_subscription_check",
        "shopDomain": identity.shop_domain,
        "shopGid": identity.shop_gid,
        "subscription": {
            "allowed": decision.allowed,
            "reason": decision.reason,
            "planHandle": decision.plan_handle,
            "checkedAt": decision.observed_at.isoformat(),
            "validUntil": (
                None if decision.valid_until is None else decision.valid_until.isoformat()
            ),
        },
        "eligibility": {
            "catalog": "eligible" if decision.allowed else "subscription_required",
            "importer": importer,
        },
        "activation": "not_performed",
        "installationVerified": False,
    }


class _DemoTransport:
    """Synthetic provider envelope; used only by the explicitly labelled demo."""

    def __init__(self, shop_domain: str, *, subscribed: bool, now: datetime) -> None:
        self.shop_domain = shop_domain
        self.subscribed = subscribed
        self.now = now

    def query(self, app_gid: str, shop_gid: str) -> dict:
        subscription = None
        if self.subscribed:
            subscription = {
                "app": {"id": app_gid},
                "shop": {"id": shop_gid, "myshopifyDomain": self.shop_domain},
                "billingPeriod": "EVERY_30_DAYS",
                "trialEndsAt": None,
                "cancelAtEndOfCycle": False,
                "currentBillingCycle": {
                    "startTime": (self.now - timedelta(days=1)).isoformat(),
                    "endTime": (self.now + timedelta(days=29)).isoformat(),
                },
                "items": [
                    {
                        "handle": _DEMO_PLAN,
                        "price": {"__typename": "FlatRatePrice", "active": True},
                    }
                ],
            }
        return {"data": {"activeSubscription": subscription}}


def demo(*, now: datetime | None = None) -> dict:
    """Exercise real provisioning and subscription parsing with synthetic shops."""
    instant = _now() if now is None else now
    policy = EntitlementPolicy(app_gid=_DEMO_APP, allowed_plan_handles=frozenset({_DEMO_PLAN}))
    shops = (
        (TenantIdentity("pilot-alpha.myshopify.com", "gid://shopify/Shop/101"), True),
        (TenantIdentity("pilot-beta.myshopify.com", "gid://shopify/Shop/102"), False),
    )
    reports = []
    with tempfile.TemporaryDirectory(prefix="nla-commercial-demo-") as directory:
        root = Path(directory).resolve()
        root.chmod(0o700)
        workspaces = []
        for identity, subscribed in shops:
            workspace = provision_tenant(root, identity, importer_authorized=False)
            workspaces.append(workspace)
            client = PartnerSubscriptionClient(
                _DemoTransport(identity.shop_domain, subscribed=subscribed, now=instant),
                policy,
            )
            decision = client.verify(
                app_gid=_DEMO_APP,
                shop_gid=identity.shop_gid,
                shop_domain=identity.shop_domain,
                now=instant,
            )
            reports.append(_report(identity, decision, importer_authorized=False, synthetic=True))
        isolated = workspaces[0].root != workspaces[1].root
    return {
        "schemaVersion": 1,
        "mode": "synthetic_demo",
        "product": PRODUCT,
        "isolatedWorkspaces": isolated,
        "shops": reports,
        "liveRequests": 0,
        "runtimeChanges": 0,
    }


def render_preview(report: dict) -> str:
    """Render an escaped static preview, clearly separated from a live dashboard."""
    cards = []
    for shop in report["shops"]:
        domain = html.escape(shop["shopDomain"])
        subscription = "Attivo (simulato)" if shop["subscription"]["allowed"] else "Assente"
        catalog = (
            "Compreso nel piano"
            if shop["eligibility"]["catalog"] == "eligible"
            else "Richiede abbonamento"
        )
        importer = (
            "Richiede autorizzazione del negozio"
            if shop["subscription"]["allowed"]
            else "Richiede abbonamento"
        )
        cards.append(
            f"<article><h2>{domain}</h2><dl>"
            f"<dt>Abbonamento</dt><dd>{subscription}</dd>"
            f"<dt>Catalogo e ricerca</dt><dd>{catalog}</dd>"
            f"<dt>Nuove stampe</dt><dd>{importer}</dd>"
            "</dl><p>Attivazione operativa da completare</p></article>"
        )
    return (
        '<!doctype html><html lang="it"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>NLA TCG Catalog - Anteprima commerciale</title>"
        "<style>body{font:17px system-ui;max-width:960px;margin:4rem auto;"
        "padding:0 1.5rem;background:#10151e;color:#edf2f8}h1{font-size:2.4rem}"
        ".badge{color:#7edac2}section{display:grid;grid-template-columns:"
        "repeat(auto-fit,minmax(280px,1fr));gap:1rem}article{background:#1c2533;"
        "border:1px solid #344259;border-radius:12px;padding:1.4rem}"
        "h2{font-size:1.1rem;overflow-wrap:anywhere}dt{color:#aab8cb;margin-top:1rem}"
        "dd{margin:.3rem 0}p{line-height:1.6}footer{margin-top:2rem;color:#aab8cb}"
        '</style><main><p class="badge">Dimostrazione locale - dati sintetici</p>'
        "<h1>NLA TCG Catalog</h1><p>Catalogo, ricerca e nuove uscite "
        "in un unico prodotto per il tuo negozio Shopify.</p><section>"
        + "".join(cards)
        + "</section><footer>Questa anteprima non rappresenta un'installazione "
        "Shopify o un abbonamento reale. Nessun prodotto o servizio NLA "
        "e' stato modificato.</footer></main></html>"
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    preview = commands.add_parser("demo", help="Run a synthetic two-shop offline pilot")
    preview.add_argument("--html", type=Path, help="Create a new synthetic HTML preview")
    provision = commands.add_parser("provision", help="Create private operator workspace only")
    provision.add_argument("--root", required=True, type=Path)
    provision.add_argument("--shop-domain", required=True)
    provision.add_argument("--shop-gid", required=True)
    provision.add_argument("--authorize-importer", action="store_true")
    check = commands.add_parser("check", help="Read current Shopify subscription; never activate")
    check.add_argument("--shop-domain", required=True)
    check.add_argument("--shop-gid", required=True)
    return parser


def _check(arguments, environ: Mapping[str, str]) -> dict:
    identity = TenantIdentity(arguments.shop_domain, arguments.shop_gid)
    app_gid = environ["NLA_COMMERCIAL_APP_GID"]
    policy = EntitlementPolicy(
        app_gid=app_gid,
        allowed_plan_handles=frozenset(
            value.strip() for value in environ["NLA_COMMERCIAL_PLAN_HANDLES"].split(",")
        ),
    )
    token = environ["NLA_COMMERCIAL_PARTNER_ACCESS_TOKEN"]
    transport = StdlibPartnerTransport(
        organization_id=environ["NLA_COMMERCIAL_PARTNER_ORGANIZATION_ID"],
        access_token=token,
    )
    decision = PartnerSubscriptionClient(transport, policy).verify(
        app_gid=app_gid,
        shop_gid=identity.shop_gid,
        shop_domain=identity.shop_domain,
        now=_now(),
    )
    return _report(identity, decision, importer_authorized=False, synthetic=False)


def main(argv: list[str] | None = None, *, environ: Mapping[str, str] | None = None) -> int:
    """Keep errors value-free; secrets are accepted only through explicit environment."""
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "demo":
            result = demo()
            if arguments.html is not None:
                with arguments.html.open("x", encoding="utf-8") as stream:
                    stream.write(render_preview(result))
        elif arguments.command == "provision":
            identity = TenantIdentity(arguments.shop_domain, arguments.shop_gid)
            provision_tenant(
                arguments.root,
                identity,
                importer_authorized=arguments.authorize_importer,
            )
            result = {
                "schemaVersion": 1,
                "result": "workspace_provisioned",
                "shopDomain": identity.shop_domain,
                "shopGid": identity.shop_gid,
                "importerOperatorAuthorized": arguments.authorize_importer,
                "installationVerified": False,
                "activation": "not_performed",
            }
        else:
            result = _check(arguments, os.environ if environ is None else environ)
        print(json.dumps(result, sort_keys=True, ensure_ascii=True))
        if arguments.command == "check" and not result["subscription"]["allowed"]:
            return 2
        return 0
    except Exception:  # noqa: S110 -- do not expose host paths, credentials or remote errors
        pass
    print(json.dumps(_ERROR, sort_keys=True))
    return 1
