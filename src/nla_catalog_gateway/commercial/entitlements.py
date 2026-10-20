"""Read-only Shopify App Pricing evidence for the isolated commercial pilot.

Only the Partner API is used (Manage apps permission), never Admin billing mutations.
The supported subset is a single fixed recurring item, without an active trial.
Evidence is an in-memory trusted control-plane value, not a signed license or a
merchant-supplied JSON format. Transport injection is for trusted wiring/tests.
"""

from __future__ import annotations

import http.client
import json
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol

PARTNER_API_VERSION = "2026-07"
_MAX_RESPONSE_BYTES = 262_144
_GID_APP = re.compile(r"gid://shopify/App/[1-9][0-9]{0,19}\Z")
_GID_SHOP = re.compile(r"gid://shopify/Shop/[1-9][0-9]{0,19}\Z")
_DOMAIN = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.myshopify\.com\Z")
_HANDLE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
_PERIOD_DAYS = {"EVERY_30_DAYS": 31, "ANNUAL": 366}
ACTIVE_SUBSCRIPTION_QUERY = """query CommercialActiveSubscription($appId: ID!, $shopId: ID!) {
  activeSubscription(appId: $appId, shopId: $shopId) {
    app { id }
    shop { id myshopifyDomain }
    billingPeriod
    cancelAtEndOfCycle
    trialEndsAt
    currentBillingCycle { startTime endTime }
    items { handle price { __typename active } }
  }
}
"""


class SubscriptionUnavailable(Exception):
    """A fixed error without provider payload, credentials or request details."""

    def __init__(self) -> None:
        super().__init__("subscription service unavailable")


def _matches(value: object, pattern: re.Pattern[str]) -> bool:
    return type(value) is str and pattern.fullmatch(value) is not None


def _utc(value: object) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("invalid subscription time")
    return value.astimezone(UTC)


def _timestamp(value: object) -> datetime:
    if type(value) is not str or len(value) > 40 or "T" not in value:
        raise ValueError("invalid subscription time")
    return _utc(datetime.fromisoformat(value.replace("Z", "+00:00")))


@dataclass(frozen=True, slots=True)
class EntitlementPolicy:
    app_gid: str
    allowed_plan_handles: frozenset[str]
    max_age_seconds: int = 300

    def __post_init__(self) -> None:
        if (
            not _matches(self.app_gid, _GID_APP)
            or type(self.allowed_plan_handles) is not frozenset
            or not 1 <= len(self.allowed_plan_handles) <= 16
            or any(not _matches(handle, _HANDLE) for handle in self.allowed_plan_handles)
            or type(self.max_age_seconds) is not int
            or not 1 <= self.max_age_seconds <= 300
        ):
            raise ValueError("invalid entitlement policy")


@dataclass(frozen=True, slots=True)
class SubscriptionEvidence:
    state: str
    app_gid: str
    shop_gid: str
    shop_domain: str
    observed_at: datetime
    plan_handle: str | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    billing_period: str | None = None


@dataclass(frozen=True, slots=True)
class AccessDecision:
    allowed: bool
    reason: str
    app_gid: str
    shop_gid: str
    shop_domain: str
    observed_at: datetime
    valid_until: datetime | None = None
    plan_handle: str | None = None


class PartnerTransport(Protocol):
    def query(self, app_gid: str, shop_gid: str) -> dict: ...


def _identity(app_gid: object, shop_gid: object, shop_domain: object) -> None:
    if not (
        _matches(app_gid, _GID_APP)
        and _matches(shop_gid, _GID_SHOP)
        and _matches(shop_domain, _DOMAIN)
    ):
        raise ValueError("invalid subscription identity")


def decide_access(
    policy: EntitlementPolicy,
    *,
    app_gid: str,
    shop_gid: str,
    shop_domain: str,
    evidence: SubscriptionEvidence,
    now: datetime,
) -> AccessDecision:
    """Decide from trusted in-memory evidence; never accept evidence from merchants."""
    checked_at = _utc(now)
    _identity(app_gid, shop_gid, shop_domain)
    if type(policy) is not EntitlementPolicy:
        raise ValueError("invalid entitlement policy")
    policy.__post_init__()
    reason = "invalid_evidence"
    plan = None
    valid_until = None
    if type(evidence) is SubscriptionEvidence:
        if (
            evidence.app_gid != app_gid
            or app_gid != policy.app_gid
            or evidence.shop_gid != shop_gid
            or evidence.shop_domain != shop_domain
        ):
            reason = "identity_mismatch"
        else:
            try:
                observed_at = _utc(evidence.observed_at)
                age = (checked_at - observed_at).total_seconds()
                if not 0 <= age < policy.max_age_seconds:
                    reason = "stale_evidence"
                elif evidence.state in {
                    "no_subscription",
                    "unavailable",
                    "invalid_response",
                    "unsupported_subscription",
                    "unsupported_trial",
                }:
                    reason = evidence.state
                elif evidence.state == "active":
                    start = _utc(evidence.valid_from)
                    end = _utc(evidence.valid_until)
                    period_days = _PERIOD_DAYS.get(evidence.billing_period)
                    if not _matches(evidence.plan_handle, _HANDLE):
                        reason = "invalid_evidence"
                    elif evidence.plan_handle not in policy.allowed_plan_handles:
                        reason = "unknown_plan"
                    elif period_days is None or not timedelta(0) < end - start <= timedelta(
                        days=period_days
                    ):
                        reason = "invalid_billing_period"
                    elif not start <= observed_at <= checked_at < end:
                        reason = "expired_or_future_subscription"
                    else:
                        reason = "allowed"
                        plan = evidence.plan_handle
                        valid_until = min(
                            end, observed_at + timedelta(seconds=policy.max_age_seconds)
                        )
            except (TypeError, ValueError, OverflowError):
                reason = "invalid_evidence"
    return AccessDecision(
        reason == "allowed", reason, app_gid, shop_gid, shop_domain, checked_at, valid_until, plan
    )


def _object(value: object) -> dict:
    if type(value) is not dict:
        raise ValueError("invalid subscription response")
    return value


class PartnerSubscriptionClient:
    """Fetch fresh provider evidence; no cache, local license, or active fallback."""

    __slots__ = ("_policy", "_transport")

    def __init__(self, transport: PartnerTransport, policy: EntitlementPolicy) -> None:
        if type(policy) is not EntitlementPolicy:
            raise ValueError("invalid entitlement policy")
        policy.__post_init__()
        self._transport = transport
        self._policy = policy

    def fetch(
        self, *, app_gid: str, shop_gid: str, shop_domain: str, now: datetime
    ) -> SubscriptionEvidence:
        observed_at = _utc(now)
        _identity(app_gid, shop_gid, shop_domain)
        base = (app_gid, shop_gid, shop_domain, observed_at)
        if app_gid != self._policy.app_gid:
            return SubscriptionEvidence("invalid_response", *base)
        try:
            payload = self._transport.query(app_gid, shop_gid)
        except Exception:
            return SubscriptionEvidence("unavailable", *base)
        try:
            envelope = _object(payload)
            if "errors" in envelope and envelope["errors"] != []:
                return SubscriptionEvidence("unavailable", *base)
            data = _object(envelope["data"])
            subscription = data["activeSubscription"]
            if subscription is None:
                return SubscriptionEvidence("no_subscription", *base)
            subscription = _object(subscription)
            app = _object(subscription["app"])
            shop = _object(subscription["shop"])
            if (
                app["id"] != app_gid
                or shop["id"] != shop_gid
                or shop["myshopifyDomain"] != shop_domain
            ):
                return SubscriptionEvidence("invalid_response", *base)
            period = subscription["billingPeriod"]
            if type(period) is not str or period not in _PERIOD_DAYS:
                raise ValueError("invalid subscription response")
            if type(subscription["cancelAtEndOfCycle"]) is not bool:
                raise ValueError("invalid subscription response")
            trial_end = subscription["trialEndsAt"]
            if trial_end is not None:
                _timestamp(trial_end)
                return SubscriptionEvidence("unsupported_trial", *base)
            cycle = _object(subscription["currentBillingCycle"])
            start, end = _timestamp(cycle["startTime"]), _timestamp(cycle["endTime"])
            items = subscription["items"]
            if type(items) is not list or len(items) != 1:
                return SubscriptionEvidence("unsupported_subscription", *base)
            item = _object(items[0])
            price = _object(item["price"])
            if price["__typename"] != "FlatRatePrice" or price["active"] is not True:
                return SubscriptionEvidence("unsupported_subscription", *base)
            handle = item["handle"]
            if not _matches(handle, _HANDLE):
                raise ValueError("invalid subscription response")
            return SubscriptionEvidence("active", *base, handle, start, end, period)
        except (KeyError, TypeError, ValueError, OverflowError):
            return SubscriptionEvidence("invalid_response", *base)

    def verify(
        self, *, app_gid: str, shop_gid: str, shop_domain: str, now: datetime
    ) -> AccessDecision:
        started = time.monotonic()
        evidence = self.fetch(app_gid=app_gid, shop_gid=shop_gid, shop_domain=shop_domain, now=now)
        checked_at = _utc(now) + timedelta(seconds=max(0.0, time.monotonic() - started))
        return decide_access(
            self._policy,
            app_gid=app_gid,
            shop_gid=shop_gid,
            shop_domain=shop_domain,
            evidence=evidence,
            now=checked_at,
        )


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("invalid subscription response")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise ValueError("invalid subscription response")


@dataclass(frozen=True, slots=True, repr=False)
class StdlibPartnerTransport:
    """Verified TLS, capped body, socket timeouts and late-result refusal; no retries."""

    organization_id: str
    access_token: str = field(repr=False)
    timeout_seconds: int = 10

    def __post_init__(self) -> None:
        if (
            not _matches(self.organization_id, re.compile(r"[1-9][0-9]{0,19}\Z"))
            or type(self.access_token) is not str
            or not 1 <= len(self.access_token) <= 4096
            or not self.access_token.isascii()
            or any(not 33 <= ord(char) <= 126 for char in self.access_token)
            or type(self.timeout_seconds) is not int
            or not 1 <= self.timeout_seconds <= 10
        ):
            raise ValueError("invalid subscription transport")

    def query(self, app_gid: str, shop_gid: str) -> dict:
        self.__post_init__()
        if not _matches(app_gid, _GID_APP) or not _matches(shop_gid, _GID_SHOP):
            raise ValueError("invalid subscription identity")
        deadline = time.monotonic() + self.timeout_seconds
        connection = None
        failed = False
        result = {}
        try:
            connection = http.client.HTTPSConnection(
                "partners.shopify.com", timeout=self.timeout_seconds
            )
            body = json.dumps(
                {
                    "query": ACTIVE_SUBSCRIPTION_QUERY,
                    "variables": {"appId": app_gid, "shopId": shop_gid},
                },
                separators=(",", ":"),
            ).encode("utf-8")
            connection.request(
                "POST",
                f"/{self.organization_id}/api/{PARTNER_API_VERSION}/graphql.json",
                body,
                {"Content-Type": "application/json", "X-Shopify-Access-Token": self.access_token},
            )
            remaining = _remaining_seconds(deadline)
            if connection.sock is not None:
                connection.sock.settimeout(remaining)
            response = connection.getresponse()
            _remaining_seconds(deadline)
            if response.status != 200:
                raise SubscriptionUnavailable()
            content_type = response.getheader("Content-Type", "").split(";", 1)[0].strip()
            if content_type not in {"application/json", "application/graphql-response+json"}:
                raise SubscriptionUnavailable()
            raw = bytearray()
            while True:
                remaining = _remaining_seconds(deadline)
                if connection.sock is not None:
                    connection.sock.settimeout(remaining)
                chunk = response.read1(min(65_536, _MAX_RESPONSE_BYTES + 1 - len(raw)))
                _remaining_seconds(deadline)
                if not chunk:
                    break
                raw.extend(chunk)
                if len(raw) > _MAX_RESPONSE_BYTES:
                    raise SubscriptionUnavailable()
            result = _object(
                json.loads(
                    raw.decode("utf-8"),
                    object_pairs_hook=_unique_object,
                    parse_constant=_reject_constant,
                )
            )
            _remaining_seconds(deadline)
        except Exception:
            failed = True
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    failed = True
        # Raise after handlers exit: neither __context__ nor __cause__ retains a
        # secret-bearing upstream exception. Cleanup never overrides control signals.
        if failed:
            raise SubscriptionUnavailable()
        return result


def _remaining_seconds(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise SubscriptionUnavailable()
    return remaining
