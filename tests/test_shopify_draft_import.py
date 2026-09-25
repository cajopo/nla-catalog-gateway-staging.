import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
from pathlib import Path
from threading import Barrier

import pytest

from nla_catalog_gateway.shopify_draft_import import (
    ACCESS_QUERY,
    CREATE_DRAFT,
    SET_IDENTITIES,
    VERIFY_DRAFT,
    create_draft_once,
)

SHOP = "nla-test.myshopify.com"
GID = "gid://shopify/Product/123"


class FakeShopify:
    def __init__(self):
        self.calls = []
        self.fail_on = None
        self.errors_on = None
        self.scopes = ["write_products"]
        self.shop = SHOP
        self.product = {
            "id": GID,
            "handle": "nla-cm-42",
            "status": "DRAFT",
            "totalInventory": 0,
            "publishedAt": None,
        }

    def __call__(self, query, variables):
        self.calls.append((query, deepcopy(variables)))
        if query == self.fail_on:
            raise TimeoutError("do not propagate remote response")
        errors = [{"message": "remote rejected"}] if query == self.errors_on else []
        if query == ACCESS_QUERY:
            return {
                "shop": {"myshopifyDomain": self.shop},
                "currentAppInstallation": {
                    "accessScopes": [{"handle": scope} for scope in self.scopes]
                },
            }
        if query == CREATE_DRAFT:
            return {"productCreate": {"product": deepcopy(self.product), "userErrors": errors}}
        if query == SET_IDENTITIES:
            self.product["syncProductId"] = {"type": "number_integer", "value": "42"}
            self.product["powertoolsId"] = {"type": "single_line_text_field", "value": "42"}
            return {"metafieldsSet": {"userErrors": errors}}
        assert query == VERIFY_DRAFT
        return {"product": deepcopy(self.product)}


def run(tmp_path, api, **overrides):
    ledger = overrides.pop("ledger", tmp_path / "ledger.sqlite")
    values = dict(
        shop=SHOP,
        blueprint_id=9,
        cardmarket_id=42,
        game="magic",
        title="Card name",
        image_url="https://cdn.cardtrader.com/image.jpg",
        graphql=api,
        verify_missing=lambda: True,
        enabled=True,
    )
    values.update(overrides)
    return create_draft_once(ledger, **values)


def test_default_disabled_has_no_file_or_network_side_effect(tmp_path):
    api = FakeShopify()
    assert run(tmp_path, api, enabled=False) == {"status": "disabled"}
    assert not list(tmp_path.iterdir()) and not api.calls


def test_draft_and_only_new_identity_fields_no_price_stock_or_publication_writes(tmp_path):
    api = FakeShopify()
    assert run(tmp_path, api) == {"status": "draft_verified", "productGid": GID, "published": False}
    assert [q for q, _ in api.calls] == [ACCESS_QUERY, CREATE_DRAFT, SET_IDENTITIES, VERIFY_DRAFT]
    assert api.calls[1][1]["product"] == {
        "title": "Card name",
        "productType": "Magic Single",
        "handle": "nla-cm-42",
        "status": "DRAFT",
    }
    for field in api.calls[2][1]["metafields"]:
        assert field["ownerId"] == GID and field["compareDigest"] is None
    assert run(tmp_path, api)["status"] == "already_reserved"
    assert len(api.calls) == 4


@pytest.mark.parametrize("query", [CREATE_DRAFT, SET_IDENTITIES, VERIFY_DRAFT])
def test_ambiguous_outcome_never_resends(tmp_path, query):
    api = FakeShopify()
    api.fail_on = query
    assert run(tmp_path, api) == {"status": "needs_reconciliation"}
    before = len(api.calls)
    assert run(tmp_path, api)["state"] == "needs_reconciliation"
    assert len(api.calls) == before
    with closing(sqlite3.connect(tmp_path / "ledger.sqlite")) as db:
        request = db.execute("select request_json from draft_attempts").fetchone()[0]
        assert "remote response" not in request


@pytest.mark.parametrize("query", [CREATE_DRAFT, SET_IDENTITIES])
def test_mutation_user_errors_do_not_allow_retry(tmp_path, query):
    api = FakeShopify()
    api.errors_on = query
    assert run(tmp_path, api)["status"] == "needs_reconciliation"
    assert run(tmp_path, api)["status"] == "already_reserved"


def test_null_created_product_is_uncertain_not_retryable(tmp_path):
    api = FakeShopify()
    api.product = None
    assert run(tmp_path, api)["status"] == "needs_reconciliation"
    assert run(tmp_path, api)["status"] == "already_reserved"
    assert [q for q, _ in api.calls] == [ACCESS_QUERY, CREATE_DRAFT]


def test_reservation_committed_before_network_write(tmp_path):
    api = FakeShopify()

    def graphql(query, variables):
        if query == CREATE_DRAFT:
            with closing(sqlite3.connect(tmp_path / "ledger.sqlite")) as db:
                assert db.execute("select state from draft_attempts").fetchone()[0] == "reserved"
            raise KeyboardInterrupt()
        return api(query, variables)

    with pytest.raises(KeyboardInterrupt):
        run(tmp_path, graphql)
    assert run(tmp_path, api)["state"] == "reserved"
    assert len(api.calls) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"status": "ACTIVE"},
        {"totalInventory": 1},
        {"publishedAt": "2026-01-01"},
        {"handle": "other"},
        {"id": "invalid"},
        {"totalInventory": False},
    ],
)
def test_unexpected_created_product_never_receives_metadata(tmp_path, change):
    api = FakeShopify()
    api.product.update(change)
    assert run(tmp_path, api)["status"] == "needs_reconciliation"
    assert [q for q, _ in api.calls] == [ACCESS_QUERY, CREATE_DRAFT]
    if change.get("id") != "invalid":
        assert run(tmp_path, api)["productGid"] == GID


def test_current_duplicate_check_failure_never_creates_or_reserves(tmp_path):
    api = FakeShopify()
    assert run(tmp_path, api, verify_missing=lambda: False)["status"] == "not_verified_missing"
    assert len(api.calls) == 1
    with closing(sqlite3.connect(tmp_path / "ledger.sqlite")) as db:
        assert db.execute("select count(*) from draft_attempts").fetchone()[0] == 0


@pytest.mark.parametrize("wrong_shop", [False, True])
def test_requires_actual_write_scope_and_matching_shop(tmp_path, wrong_shop):
    api = FakeShopify()
    if wrong_shop:
        api.shop = "other.myshopify.com"
    else:
        api.scopes = ["read_products"]
    with pytest.raises(ValueError, match="access_not_granted"):
        run(tmp_path, api)
    assert len(api.calls) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"blueprint_id": True},
        {"cardmarket_id": 0},
        {"game": "unknown"},
        {"title": ""},
        {"shop": "evil.invalid"},
        {"image_url": "http://cdn.example/a"},
        {"image_url": "https://user:pass@cdn.example/a"},
    ],
)
def test_invalid_inputs_never_contact_shopify(tmp_path, changes):
    api = FakeShopify()
    with pytest.raises(ValueError):
        run(tmp_path, api, **changes)
    assert not api.calls


def test_changed_mapping_or_payload_never_reuses_reserved_identity(tmp_path):
    api = FakeShopify()
    run(tmp_path, api)
    assert run(tmp_path, api, blueprint_id=10)["status"] == "already_reserved"
    assert run(tmp_path, api, cardmarket_id=43)["status"] == "already_reserved"
    assert run(tmp_path, api, title="Changed")["status"] == "already_reserved"
    assert len(api.calls) == 4


@pytest.mark.parametrize(
    "change",
    [
        {"id": "gid://shopify/Product/999"},
        {"syncProductId": None},
        {"status": "ACTIVE"},
    ],
)
def test_verification_mismatch_holds_original_created_gid(tmp_path, change):
    api = FakeShopify()

    def graphql(query, variables):
        result = api(query, variables)
        if query == VERIFY_DRAFT:
            result["product"].update(change)
        return result

    assert run(tmp_path, graphql)["status"] == "needs_reconciliation"
    assert run(tmp_path, api)["productGid"] == GID


@pytest.mark.parametrize("ledger", [Path(":memory:"), Path("relative.sqlite"), ":memory:"])
def test_rejects_nonpersistent_or_relative_ledger(tmp_path, ledger):
    api = FakeShopify()
    with pytest.raises(ValueError, match="persistent_absolute_ledger_required"):
        run(tmp_path, api, ledger=ledger)
    assert not api.calls


def test_concurrent_attempts_create_once(tmp_path):
    api = FakeShopify()
    barrier = Barrier(2)

    def missing():
        barrier.wait(timeout=5)
        return True

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run, tmp_path, api, verify_missing=missing) for _ in range(2)]
        results = [f.result(timeout=10) for f in futures]
    assert {r["status"] for r in results} == {"draft_verified", "already_reserved"}
    assert sum(q == CREATE_DRAFT for q, _ in api.calls) == 1
