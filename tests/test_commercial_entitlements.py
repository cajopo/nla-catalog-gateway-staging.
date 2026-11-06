"""Synthetic Partner API contracts; no store, token or billing is contacted."""

from __future__ import annotations

import copy
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from nla_catalog_gateway.commercial import entitlements as e

APP = "gid://shopify/App/100"
SHOP = "gid://shopify/Shop/200"
DOMAIN = "synthetic-one.myshopify.com"
NOW = datetime(2026, 10, 20, 12, tzinfo=UTC)
POLICY = e.EntitlementPolicy(APP, frozenset({"unified"}))
IDENTITY = dict(app_gid=APP, shop_gid=SHOP, shop_domain=DOMAIN)


def payload():
    return {
        "data": {
            "activeSubscription": {
                "app": {"id": APP},
                "shop": {"id": SHOP, "myshopifyDomain": DOMAIN},
                "billingPeriod": "EVERY_30_DAYS",
                "cancelAtEndOfCycle": False,
                "trialEndsAt": None,
                "currentBillingCycle": {
                    "startTime": "2026-10-01T00:00:00Z",
                    "endTime": "2026-10-31T00:00:00Z",
                },
                "items": [
                    {"handle": "unified", "price": {"__typename": "FlatRatePrice", "active": True}}
                ],
            }
        }
    }


class FakeTransport:
    def __init__(self, response=None, error=None):
        self.response = payload() if response is None else response
        self.error = error
        self.calls = []

    def query(self, app_gid, shop_gid):
        self.calls.append((app_gid, shop_gid))
        if self.error is not None:
            raise self.error
        return copy.deepcopy(self.response)


def verify(response=None, error=None):
    transport = FakeTransport(response, error)
    return e.PartnerSubscriptionClient(transport, POLICY).verify(**IDENTITY, now=NOW)


def test_verified_fixed_subscription_is_bounded_by_freshness_and_billing_cycle():
    result = verify()
    assert result.allowed and result.reason == "allowed"
    assert result.valid_until == NOW + timedelta(seconds=300)
    assert result.plan_handle == "unified"
    transport = FakeTransport()
    client = e.PartnerSubscriptionClient(transport, POLICY)
    evidence = client.fetch(**IDENTITY, now=NOW)
    assert transport.calls == [(APP, SHOP)]
    assert evidence.billing_period == "EVERY_30_DAYS"
    near_end = datetime(2026, 10, 30, 23, 59, 59, tzinfo=UTC)
    result = client.verify(**IDENTITY, now=near_end)
    assert result.valid_until == datetime(2026, 10, 31, tzinfo=UTC)
    response = payload()
    response["data"]["activeSubscription"]["cancelAtEndOfCycle"] = True
    assert verify(response).allowed


def test_annual_period_and_explicit_empty_graphql_errors_are_supported():
    response = payload()
    subscription = response["data"]["activeSubscription"]
    subscription["billingPeriod"] = "ANNUAL"
    subscription["currentBillingCycle"]["endTime"] = "2027-10-01T00:00:00+00:00"
    response["errors"] = []
    assert verify(response).allowed


@pytest.mark.parametrize(
    ("path", "value", "reason"),
    [
        (("data", "activeSubscription"), None, "no_subscription"),
        (("errors",), [{"message": "do not expose provider-secret"}], "unavailable"),
        (("errors",), None, "unavailable"),
        (("data",), None, "invalid_response"),
        (("data", "activeSubscription"), "bad", "invalid_response"),
        (("data", "activeSubscription", "app", "id"), "gid://shopify/App/101", "invalid_response"),
        (
            ("data", "activeSubscription", "shop", "id"),
            "gid://shopify/Shop/201",
            "invalid_response",
        ),
        (
            ("data", "activeSubscription", "shop", "myshopifyDomain"),
            "synthetic-two.myshopify.com",
            "invalid_response",
        ),
        (("data", "activeSubscription", "billingPeriod"), "UNKNOWN", "invalid_response"),
        (("data", "activeSubscription", "billingPeriod"), [], "invalid_response"),
        (("data", "activeSubscription", "cancelAtEndOfCycle"), 1, "invalid_response"),
        (
            ("data", "activeSubscription", "trialEndsAt"),
            "2026-10-25T00:00:00Z",
            "unsupported_trial",
        ),
        (("data", "activeSubscription", "trialEndsAt"), "not-date", "invalid_response"),
        (("data", "activeSubscription", "currentBillingCycle"), None, "invalid_response"),
        (
            ("data", "activeSubscription", "currentBillingCycle", "startTime"),
            None,
            "invalid_response",
        ),
        (
            ("data", "activeSubscription", "currentBillingCycle", "startTime"),
            "2026-10-01",
            "invalid_response",
        ),
        (
            ("data", "activeSubscription", "currentBillingCycle", "startTime"),
            "2026-10-01T00:00:00",
            "invalid_response",
        ),
        (
            ("data", "activeSubscription", "currentBillingCycle", "startTime"),
            "X" * 41,
            "invalid_response",
        ),
        (("data", "activeSubscription", "items"), None, "unsupported_subscription"),
        (("data", "activeSubscription", "items"), [], "unsupported_subscription"),
        (("data", "activeSubscription", "items"), [{}, {}], "unsupported_subscription"),
        (("data", "activeSubscription", "items"), [{}], "invalid_response"),
        (("data", "activeSubscription", "items"), [None], "invalid_response"),
        (
            ("data", "activeSubscription", "items"),
            [{"handle": "unified", "price": {"__typename": "TieredPrice", "active": True}}],
            "unsupported_subscription",
        ),
        (
            ("data", "activeSubscription", "items"),
            [{"handle": "unified", "price": {"__typename": "FlatRatePrice", "active": 1}}],
            "unsupported_subscription",
        ),
        (
            ("data", "activeSubscription", "items"),
            [{"handle": "other", "price": {"__typename": "FlatRatePrice", "active": True}}],
            "unknown_plan",
        ),
        (
            ("data", "activeSubscription", "items"),
            [{"handle": "unified\n", "price": {"__typename": "FlatRatePrice", "active": True}}],
            "invalid_response",
        ),
        (
            ("data", "activeSubscription", "currentBillingCycle", "endTime"),
            "2026-10-20T12:00:00Z",
            "expired_or_future_subscription",
        ),
        (
            ("data", "activeSubscription", "currentBillingCycle", "startTime"),
            "2026-10-21T00:00:00Z",
            "expired_or_future_subscription",
        ),
        (
            ("data", "activeSubscription", "currentBillingCycle", "endTime"),
            "2026-09-01T00:00:00Z",
            "invalid_billing_period",
        ),
        (
            ("data", "activeSubscription", "currentBillingCycle", "endTime"),
            "2027-10-01T00:00:00Z",
            "invalid_billing_period",
        ),
    ],
)
def test_provider_shapes_identities_plans_and_time_bounds_fail_closed(path, value, reason):
    response = payload()
    parent = response
    for key in path[:-1]:
        parent = parent[key]
    parent[path[-1]] = value
    decision = verify(response)
    assert not decision.allowed and decision.reason == reason
    assert decision.plan_handle is None and decision.valid_until is None
    assert "provider-secret" not in repr(decision)


@pytest.mark.parametrize("response", [{}, [], {"data": {}}, {"data": {"x": 1}}])
def test_missing_or_nonobject_response_is_not_no_subscription(response):
    assert verify(response).reason == "invalid_response"


def test_remote_failure_is_unavailable_without_raw_error_or_active_fallback():
    decision = verify(error=RuntimeError("secret-token-and-provider-body"))
    assert not decision.allowed and decision.reason == "unavailable"
    assert "secret-token" not in repr(decision)


def evidence():
    return e.PartnerSubscriptionClient(FakeTransport(), POLICY).fetch(**IDENTITY, now=NOW)


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"app_gid": "gid://shopify/App/101"}, "identity_mismatch"),
        ({"shop_gid": "gid://shopify/Shop/201"}, "identity_mismatch"),
        ({"shop_domain": "synthetic-two.myshopify.com"}, "identity_mismatch"),
        ({"observed_at": NOW - timedelta(seconds=300)}, "stale_evidence"),
        ({"observed_at": NOW + timedelta(microseconds=1)}, "stale_evidence"),
        ({"observed_at": None}, "invalid_evidence"),
        ({"state": "cancelled"}, "invalid_evidence"),
        ({"plan_handle": None}, "invalid_evidence"),
        ({"plan_handle": "unified ", "state": "active"}, "invalid_evidence"),
        ({"billing_period": None}, "invalid_billing_period"),
        ({"billing_period": []}, "invalid_evidence"),
        ({"valid_from": datetime(2026, 10, 1)}, "invalid_evidence"),
        ({"valid_until": None}, "invalid_evidence"),
        ({"valid_from": NOW + timedelta(seconds=1)}, "expired_or_future_subscription"),
        ({"valid_until": NOW}, "expired_or_future_subscription"),
    ],
)
def test_trusted_evidence_replay_binding_and_corruption(changes, reason):
    decision = e.decide_access(POLICY, **IDENTITY, evidence=replace(evidence(), **changes), now=NOW)
    assert not decision.allowed and decision.reason == reason


def test_wrong_evidence_type_and_policy_app_are_denied():
    assert e.decide_access(POLICY, **IDENTITY, evidence=None, now=NOW).reason == "invalid_evidence"
    different = e.EntitlementPolicy("gid://shopify/App/101", frozenset({"unified"}))
    assert e.decide_access(different, **IDENTITY, evidence=evidence(), now=NOW).reason == (
        "identity_mismatch"
    )
    transport = FakeTransport()
    client = e.PartnerSubscriptionClient(transport, POLICY)
    assert not client.verify(
        app_gid="gid://shopify/App/101", shop_gid=SHOP, shop_domain=DOMAIN, now=NOW
    ).allowed
    assert transport.calls == []


@pytest.mark.parametrize(
    "args",
    [
        ("bad", frozenset({"unified"}), 300),
        (APP, set(), 300),
        (APP, frozenset(), 300),
        (APP, frozenset({str(i) for i in range(17)}), 300),
        (APP, frozenset({None}), 300),
        (APP, frozenset({"bad space"}), 300),
        (APP, frozenset({"unified"}), True),
        (APP, frozenset({"unified"}), 0),
        (APP, frozenset({"unified"}), 301),
    ],
)
def test_policy_requires_explicit_bounded_canonical_allowlist(args):
    with pytest.raises(ValueError, match="invalid entitlement policy"):
        e.EntitlementPolicy(*args)


@pytest.mark.parametrize(
    "changes",
    [
        {"app_gid": "bad"},
        {"shop_gid": "gid://shopify/Product/200"},
        {"shop_domain": "SYNTHETIC.myshopify.com"},
        {"shop_domain": "one.myshopify.com.attacker.test"},
        {"now": datetime(2026, 10, 20)},
        {"now": None},
    ],
)
def test_invalid_request_raises_fixed_error_before_transport(changes):
    transport = FakeTransport()
    with pytest.raises(ValueError, match="invalid subscription"):
        e.PartnerSubscriptionClient(transport, POLICY).verify(**(IDENTITY | {"now": NOW} | changes))
    assert transport.calls == []


def test_policy_type_rejected_at_both_entry_points():
    with pytest.raises(ValueError, match="invalid entitlement policy"):
        e.PartnerSubscriptionClient(FakeTransport(), None)
    with pytest.raises(ValueError, match="invalid entitlement policy"):
        e.decide_access(None, **IDENTITY, evidence=evidence(), now=NOW)


class FakeResponse:
    status = 200
    mime = "application/json; charset=utf-8"
    raw = json.dumps(payload()).encode()

    def getheader(self, name, default):
        assert name == "Content-Type" and default == ""
        return self.mime

    def read1(self, bound):
        assert 0 < bound <= 65_536
        chunk, self.raw = self.raw[:bound], self.raw[bound:]
        return chunk


class FakeConnection:
    def __init__(self, response=None, error=None):
        self.response = FakeResponse() if response is None else response
        self.error = error
        self.closed = False
        self.sock = None
        self.calls = []

    def request(self, *args):
        self.calls.append(args)
        if self.error is not None:
            raise self.error

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


def wire(monkeypatch, response=None, error=None):
    connection = FakeConnection(response, error)

    def factory(host, *, timeout):
        assert host == "partners.shopify.com" and timeout == 10
        return connection

    monkeypatch.setattr(e.http.client, "HTTPSConnection", factory)
    return connection, e.StdlibPartnerTransport("123", "synthetic-token")


def test_https_adapter_uses_exact_partner_endpoint_query_bound_ids_and_redacts(monkeypatch):
    connection, transport = wire(monkeypatch)
    assert transport.query(APP, SHOP) == payload()
    method, path, body, headers = connection.calls[0]
    assert method == "POST" and path == "/123/api/2026-07/graphql.json"
    sent = json.loads(body)
    assert sent == {
        "query": e.ACTIVE_SUBSCRIPTION_QUERY,
        "variables": {"appId": APP, "shopId": SHOP},
    }
    assert "mutation" not in sent["query"] and "activeSubscription" in sent["query"]
    assert headers["X-Shopify-Access-Token"] == "synthetic-token"
    assert connection.closed
    assert "synthetic-token" not in repr(transport)


@pytest.mark.parametrize(
    ("attribute", "value"),
    [
        ("status", 302),
        ("status", 401),
        ("status", 429),
        ("mime", "text/html"),
        ("raw", b"x" * 262145),
        ("raw", b"[]"),
        ("raw", b'{"duplicate":1,"duplicate":2}'),
        ("raw", b'{"x":NaN}'),
        ("raw", b"not-json"),
        ("raw", b"\xff"),
    ],
    ids=lambda value: type(value).__name__,
)
def test_https_transport_errors_never_expose_raw_provider_or_follow_redirects(
    monkeypatch, attribute, value
):
    response = FakeResponse()
    setattr(response, attribute, value)
    connection, transport = wire(monkeypatch, response)
    with pytest.raises(e.SubscriptionUnavailable) as error:
        transport.query(APP, SHOP)
    assert str(error.value) == "subscription service unavailable"
    assert error.value.__context__ is None and error.value.__cause__ is None
    assert len(connection.calls) == 1 and connection.closed


def test_network_failure_is_sanitized_and_connection_closed(monkeypatch):
    connection, transport = wire(monkeypatch, error=OSError("synthetic-token"))
    with pytest.raises(e.SubscriptionUnavailable, match=r"^subscription service unavailable$"):
        transport.query(APP, SHOP)
    assert connection.closed


@pytest.mark.parametrize(
    "args",
    [
        ("../123", "token", 10),
        ("123", "", 10),
        ("123", "a" * 4097, 10),
        ("123", "á", 10),
        ("123", "token\n", 10),
        ("123", None, 10),
        ("123", "token", True),
        ("123", "token", 0),
        ("123", "token", 11),
    ],
)
def test_transport_configuration_is_bounded_without_echoing_secret(args):
    with pytest.raises(ValueError, match=r"^invalid subscription transport$") as error:
        e.StdlibPartnerTransport(*args)
    assert "token" not in str(error.value)


@pytest.mark.parametrize("app_gid,shop_gid", [("bad", SHOP), (APP, "bad")])
def test_transport_rejects_noncanonical_gids_before_connecting(monkeypatch, app_gid, shop_gid):
    connection, transport = wire(monkeypatch)
    with pytest.raises(ValueError, match="invalid subscription identity"):
        transport.query(app_gid, shop_gid)
    assert connection.calls == []


def test_connection_setup_and_cleanup_errors_are_sanitized(monkeypatch):
    def broken_constructor(*_args, **_kwargs):
        raise OSError("synthetic-token")

    monkeypatch.setattr(e.http.client, "HTTPSConnection", broken_constructor)
    transport = e.StdlibPartnerTransport("123", "synthetic-token")
    with pytest.raises(e.SubscriptionUnavailable) as error:
        transport.query(APP, SHOP)
    assert error.value.__context__ is None and error.value.__cause__ is None
    assert "synthetic-token" not in repr(error.value)

    connection, transport = wire(monkeypatch)
    connection.close = broken_constructor
    with pytest.raises(e.SubscriptionUnavailable) as error:
        transport.query(APP, SHOP)
    assert error.value.__context__ is None and error.value.__cause__ is None


def test_elapsed_provider_time_cannot_renew_evidence_or_bypass_ttl(monkeypatch):
    ticks = iter([0.0, 301.0])
    monkeypatch.setattr(e.time, "monotonic", lambda: next(ticks))
    decision = verify()
    assert not decision.allowed and decision.reason == "stale_evidence"


def test_slow_trickle_body_exceeds_absolute_deadline_and_denies(monkeypatch):
    timeline = {"now": 0.0}
    monkeypatch.setattr(e.time, "monotonic", lambda: timeline["now"])
    response = FakeResponse()

    def trickle(_bound):
        timeline["now"] += 11.0
        return b"{"

    response.read1 = trickle
    connection, transport = wire(monkeypatch, response)
    with pytest.raises(e.SubscriptionUnavailable) as error:
        transport.query(APP, SHOP)
    assert connection.closed
    assert error.value.__context__ is None and error.value.__cause__ is None


def test_socket_timeout_shrinks_with_remaining_deadline(monkeypatch):
    timeline = {"now": 0.0}
    monkeypatch.setattr(e.time, "monotonic", lambda: timeline["now"])
    response = FakeResponse()
    original_read = response.read1

    def bounded_read(bound):
        timeline["now"] += 2.0
        return original_read(bound)

    class FakeSocket:
        def __init__(self):
            self.timeouts = []

        def settimeout(self, value):
            self.timeouts.append(value)

    response.read1 = bounded_read
    connection, transport = wire(monkeypatch, response)
    connection.sock = FakeSocket()
    assert transport.query(APP, SHOP) == payload()
    assert connection.sock.timeouts == [10.0, 10.0, 8.0]
