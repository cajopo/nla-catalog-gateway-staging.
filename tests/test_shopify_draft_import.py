import hashlib
import json
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
    FIND_ATTEMPT_HANDLE,
    INITIALIZE_VARIANT,
    SET_IDENTITIES,
    VERIFY_DRAFT,
    create_draft_once,
    inspect_draft_attempt,
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
            "variants": {
                "nodes": [
                    {
                        "id": "gid://shopify/ProductVariant/456",
                        "price": "0.00",
                        "inventoryQuantity": 0,
                        "inventoryPolicy": "DENY",
                        "inventoryItem": {
                            "id": "gid://shopify/InventoryItem/789",
                            "tracked": False,
                        },
                        "selectedOptions": [{"name": "Title", "value": "Default Title"}],
                    }
                ],
                "pageInfo": {"hasNextPage": False},
            },
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
        if query == INITIALIZE_VARIANT:
            variant = self.product["variants"]["nodes"][0]
            variant["inventoryItem"]["tracked"] = True
            return {
                "productVariantsBulkUpdate": {
                    "product": {"id": self.product["id"]},
                    "productVariants": [{"id": variant["id"]}],
                    "userErrors": errors,
                }
            }
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


@pytest.mark.parametrize(
    "case,expected",
    [
        ("complete", "recorded_draft_matches"),
        ("missing_identities", "identity_fields_require_review"),
        ("published", "inspection_unconfirmed"),
        ("wrong_gid", "inspection_unconfirmed"),
        ("deleted", "recorded_product_not_found"),
        ("wrong_shop", "inspection_unconfirmed"),
        ("timeout", "inspection_unconfirmed"),
        ("unknown_found", "manual_ownership_check_required"),
        ("unknown_missing", "outcome_unknown_no_handle_match"),
    ],
)
def test_readonly_inspection_never_unblocks_attempt(tmp_path, case, expected):
    api = FakeShopify()
    assert run(tmp_path, api)["status"] == "draft_verified"
    ledger = tmp_path / "ledger.sqlite"
    if case.startswith("unknown"):
        with closing(sqlite3.connect(ledger)) as db:
            db.execute("UPDATE draft_attempts SET product_gid=NULL,state='needs_reconciliation'")
            db.commit()
    before = ledger.read_bytes()
    api.calls.clear()
    if case == "missing_identities":
        api.product["syncProductId"] = None
    if case == "published":
        api.product["status"] = "ACTIVE"
    if case == "wrong_gid":
        api.product["id"] = "gid://shopify/Product/999"
    if case == "deleted":
        api.product = None
    if case == "wrong_shop":
        api.shop = "different.myshopify.com"
    if case == "timeout":
        api.fail_on = VERIFY_DRAFT

    def read(query, variables):
        assert query in (ACCESS_QUERY, VERIFY_DRAFT, FIND_ATTEMPT_HANDLE)
        if query == FIND_ATTEMPT_HANDLE:
            assert variables == {"identifier": {"handle": "nla-cm-42"}}
            return {"product": api.product if case == "unknown_found" else None}
        return api(query, variables)

    result = inspect_draft_attempt(ledger, shop=SHOP, cardmarket_id=42, graphql=read)
    assert result["status"] == expected and result["retryAllowed"] is False
    assert ledger.read_bytes() == before
    assert run(tmp_path, api)["status"] == "already_reserved"


def test_inspection_missing_ledger_does_not_create_file(tmp_path):
    ledger = tmp_path / "missing.sqlite"
    with pytest.raises(sqlite3.OperationalError):
        inspect_draft_attempt(ledger, shop=SHOP, cardmarket_id=42, graphql=FakeShopify())
    assert not ledger.exists()


def test_inspection_missing_attempt_and_corrupt_request(tmp_path):
    api = FakeShopify()
    run(tmp_path, api)
    ledger = tmp_path / "ledger.sqlite"
    api.calls.clear()
    assert inspect_draft_attempt(ledger, shop=SHOP, cardmarket_id=43, graphql=api) == {
        "status": "no_attempt",
        "retryAllowed": False,
    }
    with closing(sqlite3.connect(ledger)) as db:
        db.execute("UPDATE draft_attempts SET request_json='{}'")
        db.commit()
    with pytest.raises(ValueError, match="digest_mismatch"):
        inspect_draft_attempt(ledger, shop=SHOP, cardmarket_id=42, graphql=api)
    assert api.calls == []


def test_draft_and_only_new_identity_fields_no_price_stock_or_publication_writes(tmp_path):
    api = FakeShopify()
    assert run(tmp_path, api) == {"status": "draft_verified", "productGid": GID, "published": False}
    assert [q for q, _ in api.calls] == [
        ACCESS_QUERY,
        CREATE_DRAFT,
        SET_IDENTITIES,
        VERIFY_DRAFT,
        INITIALIZE_VARIANT,
        VERIFY_DRAFT,
    ]
    assert api.calls[1][1]["product"] == {
        "title": "Card name",
        "productType": "Magic Single",
        "handle": "nla-cm-42",
        "status": "DRAFT",
    }
    for field in api.calls[2][1]["metafields"]:
        assert field["ownerId"] == GID and field["compareDigest"] is None
    assert run(tmp_path, api)["status"] == "already_reserved"
    assert api.calls[4][1] == {
        "productId": GID,
        "variants": [
            {
                "id": "gid://shopify/ProductVariant/456",
                "inventoryPolicy": "DENY",
                "inventoryItem": {"tracked": True},
            }
        ],
    }
    assert len(api.calls) == 6


@pytest.mark.parametrize("query", [CREATE_DRAFT, SET_IDENTITIES, VERIFY_DRAFT, INITIALIZE_VARIANT])
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


@pytest.mark.parametrize("query", [CREATE_DRAFT, SET_IDENTITIES, INITIALIZE_VARIANT])
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
    assert len(api.calls) == 6


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


@pytest.mark.parametrize(
    "change",
    [
        {"id": "gid://shopify/Product/456"},
        {"price": "1.00"},
        {"inventoryQuantity": 1},
        {"inventoryQuantity": False},
        {"inventoryPolicy": "CONTINUE"},
        {"selectedOptions": []},
        {"inventoryItem": {"id": "gid://shopify/InventoryItem/789", "tracked": 0}},
        {"inventoryItem": {"id": "wrong", "tracked": False}},
    ],
)
def test_changed_default_variant_is_not_initialized(tmp_path, change):
    api = FakeShopify()
    api.product["variants"]["nodes"][0].update(change)
    assert run(tmp_path, api)["status"] == "needs_reconciliation"
    assert not any(q == INITIALIZE_VARIANT for q, _ in api.calls)
    before = len(api.calls)
    assert run(tmp_path, api)["status"] == "already_reserved"
    assert len(api.calls) == before


@pytest.mark.parametrize("case", ["empty", "multiple", "more_pages"])
def test_only_one_complete_default_variant_can_be_initialized(tmp_path, case):
    api = FakeShopify()
    connection = api.product["variants"]
    if case == "empty":
        connection["nodes"] = []
    elif case == "multiple":
        connection["nodes"].append(deepcopy(connection["nodes"][0]))
    else:
        connection["pageInfo"]["hasNextPage"] = True
    assert run(tmp_path, api)["status"] == "needs_reconciliation"
    assert not any(q == INITIALIZE_VARIANT for q, _ in api.calls)


def test_already_tracked_safe_default_needs_no_variant_write(tmp_path):
    api = FakeShopify()
    api.product["variants"]["nodes"][0]["inventoryItem"]["tracked"] = True
    assert run(tmp_path, api)["status"] == "draft_verified"
    assert not any(q == INITIALIZE_VARIANT for q, _ in api.calls)


@pytest.mark.parametrize(
    "case",
    [
        "wrong_product",
        "wrong_variant",
        "after_price",
        "after_tracking",
        "after_identity",
        "after_status",
        "after_timeout",
        "interrupt",
    ],
)
def test_initialization_uncertainty_never_retries_or_reports_verified(tmp_path, case):
    api = FakeShopify()
    initialized = False

    def graphql(query, variables):
        nonlocal initialized
        if query == VERIFY_DRAFT and initialized and case == "after_timeout":
            raise TimeoutError()
        result = api(query, variables)
        if query == INITIALIZE_VARIANT:
            initialized = True
            if case == "interrupt":
                raise KeyboardInterrupt()
            if case == "wrong_product":
                result["productVariantsBulkUpdate"]["product"]["id"] = "gid://shopify/Product/999"
            if case == "wrong_variant":
                result["productVariantsBulkUpdate"]["productVariants"] = []
        if query == VERIFY_DRAFT and initialized:
            p = result["product"]
            if case == "after_price":
                p["variants"]["nodes"][0]["price"] = "1.00"
            if case == "after_tracking":
                p["variants"]["nodes"][0]["inventoryItem"]["tracked"] = False
            if case == "after_identity":
                p["syncProductId"] = None
            if case == "after_status":
                p["status"] = "ACTIVE"
        return result

    if case == "interrupt":
        with pytest.raises(KeyboardInterrupt):
            run(tmp_path, graphql)
    else:
        assert run(tmp_path, graphql)["status"] == "needs_reconciliation"
    count = len(api.calls)
    blocked = run(tmp_path, api)
    assert blocked["status"] == "already_reserved" and blocked["productGid"] == GID
    assert len(api.calls) == count


@pytest.mark.parametrize(
    "case", ["relative_ledger", "invalid_identity", "corrupt_handle", "invalid_lookup"]
)
def test_inspection_rejects_invalid_identity_evidence(tmp_path, case):
    api = FakeShopify()
    run(tmp_path, api)
    ledger = tmp_path / "ledger.sqlite"
    if case == "relative_ledger":
        with pytest.raises(ValueError, match="persistent_absolute"):
            inspect_draft_attempt(Path("relative"), shop=SHOP, cardmarket_id=42, graphql=api)
        return
    if case == "invalid_identity":
        with pytest.raises(ValueError, match="invalid_import_identity"):
            inspect_draft_attempt(ledger, shop=SHOP, cardmarket_id=True, graphql=api)
        return
    with closing(sqlite3.connect(ledger)) as db:
        if case == "corrupt_handle":
            encoded = db.execute("SELECT request_json FROM draft_attempts").fetchone()[0]
            request = json.loads(encoded)
            request["variables"]["product"]["handle"] = "other"
            encoded = json.dumps(request)
            db.execute(
                "UPDATE draft_attempts SET request_json=?,request_sha256=?",
                (encoded, hashlib.sha256(encoded.encode()).hexdigest()),
            )
        else:
            db.execute("UPDATE draft_attempts SET product_gid=NULL")
        db.commit()
    if case == "corrupt_handle":
        with pytest.raises(ValueError, match="attempt_handle_mismatch"):
            inspect_draft_attempt(ledger, shop=SHOP, cardmarket_id=42, graphql=api)
    else:

        def graphql(query, variables):
            if query == FIND_ATTEMPT_HANDLE:
                return {"product": {"handle": "nla-cm-42", "id": "invalid"}}
            return api(query, variables)

        assert (
            inspect_draft_attempt(ledger, shop=SHOP, cardmarket_id=42, graphql=graphql)["status"]
            == "inspection_unconfirmed"
        )
