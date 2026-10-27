import hashlib
import json
import os
import sqlite3
import stat
from contextlib import closing
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from nla_catalog_gateway import shopify_draft_publication as publication
from nla_catalog_gateway.shopify_draft_import import PRODUCT_TYPES
from test_shopify_draft_import import GID, SHOP, FakeShopify
from test_shopify_draft_import import run as create_verified_draft

PUBLICATION_ID = "gid://shopify/Publication/1234"
OTHER_PUBLICATION = "gid://shopify/Publication/5678"


def connection(nodes):
    return {"nodes": nodes, "pageInfo": {"hasNextPage": False, "endCursor": None}}


class FakePublication:
    def __init__(self, product):
        self.calls = []
        self.shop = SHOP
        self.scopes = ["write_products", "read_publications", "write_publications"]
        self.publication = {
            "id": PUBLICATION_ID,
            "catalog": {
                "__typename": "AppCatalog",
                "apps": connection([{"id": "gid://shopify/App/580111", "handle": "online_store"}]),
            },
        }
        self.product = deepcopy(product)
        self.product.pop("publishedAt")
        self.product.update(
            title="Card name",
            productType="Magic Single",
            publishedOnPublication=False,
            resourcePublicationsV2=connection([]),
            media=connection(
                [
                    {
                        "id": "gid://shopify/MediaImage/321",
                        "status": "READY",
                        "mediaContentType": "IMAGE",
                    }
                ]
            ),
        )
        self.product["variants"]["nodes"][0]["inventoryItem"]["inventoryLevels"] = connection(
            [
                {
                    "id": f"gid://shopify/InventoryLevel/{identifier}",
                    "quantities": [
                        {"name": name, "quantity": 0}
                        for name in ("available", "on_hand", "committed", "reserved")
                    ],
                }
                for identifier in (111, 222)
            ]
        )

    def __call__(self, query, variables):
        self.calls.append((query, deepcopy(variables)))
        if query == publication.ACCESS_QUERY:
            return {
                "shop": {"myshopifyDomain": self.shop},
                "currentAppInstallation": {
                    "accessScopes": [{"handle": scope} for scope in self.scopes]
                },
            }
        if query == publication.PUBLICATION:
            return {"publication": deepcopy(self.publication)}
        if query == publication.PRODUCT:
            return {"product": deepcopy(self.product)}
        if query == publication.ACTIVATE:
            assert variables == {"product": {"id": GID, "status": "ACTIVE"}}
            self.product["status"] = "ACTIVE"
            return {"productUpdate": {"product": {"id": GID, "status": "ACTIVE"}, "userErrors": []}}
        assert query == publication.PUBLISH
        assert variables == {"id": GID, "input": [{"publicationId": PUBLICATION_ID}]}
        self.product["publishedOnPublication"] = True
        self.product["resourcePublicationsV2"] = connection(
            [{"isPublished": True, "publication": {"id": PUBLICATION_ID}}]
        )
        return {"publishablePublish": {"userErrors": []}}


@pytest.fixture
def setup(tmp_path, monkeypatch, request):
    api = FakeShopify()
    game = getattr(request, "param", "magic")
    assert create_verified_draft(tmp_path, api, game=game)["status"] == "draft_verified"
    ledger = tmp_path / "ledger.sqlite"
    ledger.chmod(0o600)
    native_lstat = Path.lstat

    def root_ledger_facts(path, *args, **kwargs):
        facts = native_lstat(path, *args, **kwargs)
        if path == ledger:
            fields = list(facts)
            fields[4] = 0  # Simulate the deployment owner only for this ledger.
            return os.stat_result(fields)
        return facts

    monkeypatch.setattr(Path, "lstat", root_ledger_facts)
    publisher = FakePublication(api.product)
    publisher.product["productType"] = PRODUCT_TYPES[game]
    return ledger, publisher


def publish(ledger, api, **overrides):
    values = dict(shop=SHOP, publication_id=PUBLICATION_ID, graphql=api, enabled=True)
    values.update(overrides)
    return publication.publish_verified_drafts(ledger, **values)


def writes(api):
    return [(q, v) for q, v in api.calls if q.lstrip().startswith("mutation ")]


def publication_rows(ledger):
    with closing(sqlite3.connect(ledger)) as db:
        return db.execute(
            "SELECT product_gid,publication_gid,snapshot_json,state FROM draft_publications"
        ).fetchall()


def creation_rows(ledger):
    with closing(sqlite3.connect(ledger)) as db:
        return db.execute("SELECT * FROM draft_attempts").fetchall()


def add_second_verified_candidate(ledger):
    with closing(sqlite3.connect(ledger)) as db:
        request = json.loads(db.execute("SELECT request_json FROM draft_attempts").fetchone()[0])
        request["blueprintId"] = 10
        request["variables"]["product"]["handle"] = "nla-cm-43"
        encoded = json.dumps(request, sort_keys=True)
        db.execute(
            "INSERT INTO draft_attempts "
            "SELECT shop,43,10,?,?,'draft_verified',?,created_at FROM draft_attempts LIMIT 1",
            (
                hashlib.sha256(encoded.encode()).hexdigest(),
                encoded,
                "gid://shopify/Product/124",
            ),
        )
        db.commit()


def test_default_disabled_has_no_network_or_filesystem_effect(tmp_path):
    ledger = tmp_path / "does-not-exist.sqlite"
    api = FakePublication(FakeShopify().product)
    result = publication.publish_verified_drafts(
        ledger, shop=SHOP, publication_id=PUBLICATION_ID, graphql=api
    )
    assert result == {"status": "disabled", "published": 0, "results": []}
    assert not api.calls and not ledger.exists()


def test_missing_ledger_is_not_created_and_does_not_contact_shopify(tmp_path):
    ledger = tmp_path / "missing.sqlite"
    api = FakePublication(FakeShopify().product)
    with pytest.raises(FileNotFoundError):
        publish(ledger, api)
    assert not ledger.exists() and not api.calls


def test_ledger_directory_is_rejected_before_network_calls(tmp_path):
    api = FakePublication(FakeShopify().product)
    with pytest.raises(ValueError, match="existing_regular_ledger_required"):
        publish(tmp_path, api)
    assert not api.calls


def test_hardlinked_ledger_is_rejected_without_writing_either_path(setup):
    ledger, api = setup
    linked = ledger.with_name("another-owner.sqlite")
    os.link(ledger, linked)
    before = ledger.read_bytes()
    with pytest.raises(ValueError, match="existing_regular_ledger_required"):
        publish(ledger, api)
    assert not api.calls and linked.read_bytes() == before and ledger.read_bytes() == before


@pytest.mark.parametrize("uid,mode", [(1000, 0o600), (0, 0o644), (0, 0o600)])
def test_posix_ledger_requires_root_owned_private_file(monkeypatch, uid, mode):
    ledger = SimpleNamespace()
    ledger.is_absolute = lambda: True
    ledger.resolve = lambda: ledger
    ledger.lstat = lambda: SimpleNamespace(st_mode=stat.S_IFREG | mode, st_nlink=1, st_uid=uid)
    monkeypatch.setattr(publication, "os", SimpleNamespace(name="posix"))
    if uid == 0 and mode == 0o600:
        publication.validate_ledger(ledger)
    else:
        with pytest.raises(ValueError, match="private_existing_ledger_required"):
            publication.validate_ledger(ledger)


def test_standalone_validation_rejects_relative_ledger():
    with pytest.raises(ValueError, match="canonical_existing_ledger_required"):
        publication.validate_ledger(Path("relative.sqlite"))


@pytest.mark.parametrize(
    "error,reason",
    [
        (ValueError("publication_other_channel"), "publication_other_channel"),
        (ValueError("secret_remote_response"), "unexpected_publication_error"),
        (ValueError(["secret_remote_response"]), "unexpected_publication_error"),
        (
            ValueError("publication_other_channel", "secret_remote_response"),
            "unexpected_publication_error",
        ),
        (publication.CaptureHttpError(), "shopify_request_failed"),
        (sqlite3.OperationalError("secret_remote_response"), "ledger_database_error"),
    ],
)
def test_inspection_error_reason_is_allowlisted_and_never_leaks_payload(setup, error, reason):
    ledger, api = setup

    def graphql(query, variables):
        if query == publication.PRODUCT:
            raise error
        return api(query, variables)

    result = publish(ledger, graphql)
    assert result["status"] == "publication_stopped_inspect"
    assert result["results"][0]["reason"] == reason
    assert "secret_remote_response" not in json.dumps(result)
    assert not writes(api) and publication_rows(ledger) == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"max_products": 0},
        {"max_products": 10001},
        {"max_products": True},
        {"publication_id": "gid://shopify/Publication/0"},
        {"publication_id": "gid://shopify/Product/1234"},
        {"ledger": Path("relative.sqlite")},
    ],
)
def test_invalid_controls_do_not_contact_shopify(setup, overrides):
    ledger, api = setup
    overrides = dict(overrides)
    target = overrides.pop("ledger", ledger)
    with pytest.raises(ValueError, match="invalid_publication_controls"):
        publish(target, api, **overrides)
    assert not api.calls


@pytest.mark.parametrize("setup", ["magic", "lorcana", "riftbound"], indirect=True)
def test_publication_writes_only_status_and_one_channel_preserving_creation_ledger(setup):
    ledger, api = setup
    before = deepcopy(api.product)
    imported = creation_rows(ledger)
    result = publish(ledger, api)
    assert result["status"] == "publication_complete"
    assert result["published"] == 1 and result["alreadyPublished"] == 0
    assert result["remaining"] == 0
    assert result["results"] == [{"cardmarketId": 42, "status": "published_verified"}]
    assert writes(api) == [
        (publication.ACTIVATE, {"product": {"id": GID, "status": "ACTIVE"}}),
        (publication.PUBLISH, {"id": GID, "input": [{"publicationId": PUBLICATION_ID}]}),
    ]
    assert [q for q, _ in api.calls] == [
        publication.ACCESS_QUERY,
        publication.PUBLICATION,
        publication.PRODUCT,
        publication.ACTIVATE,
        publication.PRODUCT,
        publication.PUBLISH,
        publication.PRODUCT,
    ]
    for key in before:
        if key not in {"status", "publishedOnPublication", "resourcePublicationsV2"}:
            assert api.product[key] == before[key]
    assert creation_rows(ledger) == imported
    assert publication_rows(ledger)[0][3] == "published"


def test_pending_reservation_is_committed_before_either_network_write(setup):
    ledger, api = setup
    stages = []

    def graphql(query, variables):
        if query in (publication.ACTIVATE, publication.PUBLISH):
            saved = publication_rows(ledger)
            assert len(saved) == 1
            assert saved[0][:2] == (GID, PUBLICATION_ID) and saved[0][3] == "pending"
            assert json.loads(saved[0][2])["variants"]["nodes"][0]["price"] == "0.00"
            stages.append(query)
        return api(query, variables)

    assert publish(ledger, graphql)["published"] == 1
    assert stages == [publication.ACTIVATE, publication.PUBLISH]


@pytest.mark.parametrize("setup", ["magic", "lorcana", "riftbound"], indirect=True)
def test_successful_handoff_never_reads_or_reactivates_product_on_later_cycles(setup):
    ledger, api = setup
    assert publish(ledger, api)["published"] == 1
    api.product.update(status="DRAFT", title="Changed by PowerTools", publishedOnPublication=False)
    api.product["variants"]["nodes"][0].update(price="12.50", inventoryQuantity=7)
    after_handoff = deepcopy(api.product)
    api.calls.clear()
    result = publish(ledger, api)
    assert result["published"] == 0 and result["remaining"] == 0
    assert result["results"] == []
    assert [q for q, _ in api.calls] == [publication.ACCESS_QUERY, publication.PUBLICATION]
    assert api.product == after_handoff


def test_product_budget_leaves_next_verified_candidate_unmodified(setup):
    ledger, api = setup
    add_second_verified_candidate(ledger)
    result = publish(ledger, api, max_products=1)
    assert result["published"] == 1 and result["remaining"] == 1
    assert [r["cardmarketId"] for r in result["results"]] == [42]
    assert all(v["id"] == GID for q, v in api.calls if q == publication.PRODUCT)
    assert len(publication_rows(ledger)) == 1


def test_unconfirmed_product_stops_before_later_verified_candidates(setup):
    ledger, api = setup
    add_second_verified_candidate(ledger)
    api.product["title"] = "PowerTools changed this card"
    result = publish(ledger, api)
    assert result["status"] == "publication_stopped_inspect" and result["remaining"] == 2
    assert [r["cardmarketId"] for r in result["results"]] == [42]
    assert all(v["id"] == GID for q, v in api.calls if q == publication.PRODUCT)
    assert not writes(api) and publication_rows(ledger) == []


def test_already_published_import_is_recorded_without_rewriting_powertools_data(setup):
    ledger, api = setup
    api.product.update(status="ACTIVE", publishedOnPublication=True, title="PowerTools title")
    api.product["variants"]["nodes"][0].update(price="9.00", inventoryQuantity=3)
    before = deepcopy(api.product)
    result = publish(ledger, api)
    assert result["alreadyPublished"] == 1 and result["published"] == 0
    assert not writes(api) and api.product == before
    api.calls.clear()
    assert publish(ledger, api)["results"] == []
    assert publication.PRODUCT not in [q for q, _ in api.calls]


@pytest.mark.parametrize("state", ["reserved", "draft_created", "needs_reconciliation"])
def test_unverified_creation_is_never_a_publication_candidate(setup, state):
    ledger, api = setup
    with closing(sqlite3.connect(ledger)) as db:
        db.execute("UPDATE draft_attempts SET state=?", (state,))
        db.commit()
    result = publish(ledger, api)
    assert result["results"] == [] and result["published"] == 0
    assert publication_rows(ledger) == []
    assert [q for q, _ in api.calls] == [publication.ACCESS_QUERY, publication.PUBLICATION]


@pytest.mark.parametrize("field", ["request_json", "request_sha256", "blueprint_id", "product_gid"])
def test_corrupt_ownership_evidence_cannot_authorize_activation(setup, field):
    ledger, api = setup
    changed = {
        "request_json": ("UPDATE draft_attempts SET request_json=?", ('{"secret":"remote"}',)),
        "request_sha256": ("UPDATE draft_attempts SET request_sha256=?", ("0" * 64,)),
        "blueprint_id": ("UPDATE draft_attempts SET blueprint_id=?", (999,)),
        "product_gid": ("UPDATE draft_attempts SET product_gid=?", ("gid://shopify/Product/999",)),
    }
    with closing(sqlite3.connect(ledger)) as db:
        db.execute(*changed[field])
        db.commit()
    result = publish(ledger, api)
    assert result["status"] == "publication_stopped_inspect"
    assert not writes(api) and publication_rows(ledger) == []
    assert "remote" not in json.dumps(result)


@pytest.mark.parametrize(
    "case", ["shop", "write_products", "write_publications", "read_publications"]
)
def test_wrong_shop_or_missing_access_fails_before_inspection_or_writes(setup, case):
    ledger, api = setup
    if case == "shop":
        api.shop = "other.myshopify.com"
    else:
        api.scopes.remove(case)
    with pytest.raises(ValueError, match="publication_access_not_granted"):
        publish(ledger, api)
    assert [q for q, _ in api.calls] == [publication.ACCESS_QUERY]


@pytest.mark.parametrize(
    "case", ["missing", "gid", "catalog", "app", "handle", "more_pages", "extra_app"]
)
def test_publication_must_be_the_unique_verified_online_store_app(setup, case):
    ledger, api = setup
    if case == "missing":
        api.publication = None
    elif case == "gid":
        api.publication["id"] = OTHER_PUBLICATION
    elif case == "catalog":
        api.publication["catalog"]["__typename"] = "MarketCatalog"
    elif case == "app":
        api.publication["catalog"]["apps"]["nodes"][0]["id"] = "gid://shopify/App/99"
    elif case == "handle":
        api.publication["catalog"]["apps"]["nodes"][0]["handle"] = "other_channel"
    elif case == "more_pages":
        api.publication["catalog"]["apps"]["pageInfo"]["hasNextPage"] = True
    else:
        api.publication["catalog"]["apps"]["nodes"].append(
            {"id": "gid://shopify/App/99", "handle": "other_channel"}
        )
    with pytest.raises(ValueError, match="not_verified_online_store"):
        publish(ledger, api)
    assert not writes(api) and publication.PRODUCT not in [q for q, _ in api.calls]


@pytest.mark.parametrize(
    "case",
    [
        "missing_product",
        "wrong_gid",
        "handle",
        "sync_identity",
        "powertools_identity",
        "title",
        "product_type",
        "archived",
        "active_without_reservation",
        "total_stock",
        "boolean_total",
        "price",
        "variant_stock",
        "continue_selling",
        "options",
        "untracked",
        "multiple_variants",
        "variant_page",
        "location_stock",
        "compensating_stock",
        "missing_quantity",
        "duplicate_quantity",
        "boolean_quantity",
        "inventory_page",
        "missing_media",
        "multiple_media",
        "media_not_ready",
        "video",
        "media_page",
        "other_published_channel",
        "other_unpublished_channel",
        "publication_page",
    ],
)
def test_changed_or_incomplete_product_is_rejected_before_any_write(setup, case):
    ledger, api = setup
    product = api.product
    variant = product["variants"]["nodes"][0]
    levels = variant["inventoryItem"]["inventoryLevels"]
    if case == "missing_product":
        api.product = None
    elif case == "wrong_gid":
        product["id"] = "gid://shopify/Product/999"
    elif case == "handle":
        product["handle"] = "another-product"
    elif case == "sync_identity":
        product["syncProductId"]["value"] = "43"
    elif case == "powertools_identity":
        product["powertoolsId"] = None
    elif case == "title":
        product["title"] = "Updated title"
    elif case == "product_type":
        product["productType"] = "Pokemon Single"
    elif case == "archived":
        product["status"] = "ARCHIVED"
    elif case == "active_without_reservation":
        product["status"] = "ACTIVE"
    elif case in ("total_stock", "boolean_total"):
        product["totalInventory"] = 1 if case == "total_stock" else False
    elif case == "price":
        variant["price"] = "1.00"
    elif case == "variant_stock":
        variant["inventoryQuantity"] = 1
    elif case == "continue_selling":
        variant["inventoryPolicy"] = "CONTINUE"
    elif case == "options":
        variant["selectedOptions"] = [{"name": "Condition", "value": "NM"}]
    elif case == "untracked":
        variant["inventoryItem"]["tracked"] = False
    elif case == "multiple_variants":
        product["variants"]["nodes"].append(deepcopy(variant))
    elif case == "variant_page":
        product["variants"]["pageInfo"]["hasNextPage"] = True
    elif case in ("location_stock", "compensating_stock"):
        levels["nodes"][1]["quantities"][0]["quantity"] = 1
        if case == "compensating_stock":
            levels["nodes"][0]["quantities"][0]["quantity"] = -1
    elif case == "missing_quantity":
        levels["nodes"][1]["quantities"].pop()
    elif case == "duplicate_quantity":
        levels["nodes"][1]["quantities"].append({"name": "available", "quantity": 0})
    elif case == "boolean_quantity":
        levels["nodes"][1]["quantities"][0]["quantity"] = False
    elif case == "inventory_page":
        levels["pageInfo"]["hasNextPage"] = True
    elif case == "missing_media":
        product["media"]["nodes"] = []
    elif case == "multiple_media":
        product["media"]["nodes"].append(deepcopy(product["media"]["nodes"][0]))
    elif case == "media_not_ready":
        product["media"]["nodes"][0]["status"] = "PROCESSING"
    elif case == "video":
        product["media"]["nodes"][0]["mediaContentType"] = "VIDEO"
    elif case == "media_page":
        product["media"]["pageInfo"]["hasNextPage"] = True
    elif case in ("other_published_channel", "other_unpublished_channel"):
        product["resourcePublicationsV2"]["nodes"].append(
            {
                "isPublished": case == "other_published_channel",
                "publication": {"id": OTHER_PUBLICATION},
            }
        )
    else:
        product["resourcePublicationsV2"]["pageInfo"]["hasNextPage"] = True
    before = deepcopy(api.product)
    result = publish(ledger, api)
    assert result["status"] == "publication_stopped_inspect"
    assert result["results"][0]["stage"] == "inspect"
    assert result["published"] == 0 and result["remaining"] == 1
    assert not writes(api) and api.product == before
    assert publication_rows(ledger) == []


@pytest.mark.parametrize("mutation", [publication.ACTIVATE, publication.PUBLISH])
@pytest.mark.parametrize("interrupted", [False, True])
def test_lost_response_resumes_from_readback_without_repeating_applied_mutation(
    setup, mutation, interrupted
):
    ledger, api = setup

    def graphql(query, variables):
        result = api(query, variables)
        if query == mutation:
            if interrupted:
                raise KeyboardInterrupt
            raise TimeoutError("secret_remote_response")
        return result

    if interrupted:
        with pytest.raises(KeyboardInterrupt):
            publish(ledger, graphql)
    else:
        result = publish(ledger, graphql)
        assert result["status"] == "publication_stopped_inspect"
        assert "secret_remote_response" not in json.dumps(result)
    assert publication_rows(ledger)[0][3] == "pending"
    result = publish(ledger, api)
    assert result["status"] == "publication_complete" and result["remaining"] == 0
    assert result["alreadyPublished"] == int(mutation == publication.PUBLISH)
    assert [q for q, _ in writes(api)] == [publication.ACTIVATE, publication.PUBLISH]
    assert publication_rows(ledger)[0][3] == "published"


@pytest.mark.parametrize("mutation", [publication.ACTIVATE, publication.PUBLISH])
def test_commercial_drift_after_mutation_stops_without_compensating_writes(setup, mutation):
    ledger, api = setup

    def graphql(query, variables):
        result = api(query, variables)
        if query == mutation:
            api.product["variants"]["nodes"][0]["price"] = "3.00"
        return result

    result = publish(ledger, graphql)
    assert result["status"] == "publication_stopped_inspect"
    assert result["results"][0]["stage"] == (
        "activate" if mutation == publication.ACTIVATE else "publish"
    )
    assert result["published"] == 0 and publication_rows(ledger)[0][3] == "pending"
    assert [q for q, _ in writes(api)] == (
        [publication.ACTIVATE]
        if mutation == publication.ACTIVATE
        else [publication.ACTIVATE, publication.PUBLISH]
    )
    api.calls.clear()
    assert publish(ledger, api)["status"] == "publication_stopped_inspect"
    assert not writes(api) and api.product["variants"]["nodes"][0]["price"] == "3.00"


@pytest.mark.parametrize("published", [False, True])
def test_pending_snapshot_drift_is_rejected_even_when_new_variant_is_zero_stock(setup, published):
    ledger, api = setup
    interrupted_query = publication.PUBLISH if published else publication.ACTIVATE

    def graphql(query, variables):
        result = api(query, variables)
        if query == interrupted_query:
            raise TimeoutError("response lost")
        return result

    assert publish(ledger, graphql)["status"] == "publication_stopped_inspect"
    api.product["variants"]["nodes"][0]["id"] = "gid://shopify/ProductVariant/999"
    api.calls.clear()
    result = publish(ledger, api)
    assert result["status"] == "publication_stopped_inspect"
    assert result["results"][0]["stage"] == "inspect"
    assert not writes(api) and publication_rows(ledger)[0][3] == "pending"


@pytest.mark.parametrize("mutation", [publication.ACTIVATE, publication.PUBLISH])
@pytest.mark.parametrize("change", ["new_default_variant", "status"])
def test_readback_mismatch_cannot_be_reported_as_confirmed(setup, mutation, change):
    ledger, api = setup

    def graphql(query, variables):
        result = api(query, variables)
        if query == mutation:
            if change == "new_default_variant":
                api.product["variants"]["nodes"][0]["id"] = "gid://shopify/ProductVariant/999"
            else:
                api.product["status"] = "DRAFT"
        return result

    result = publish(ledger, graphql)
    assert result["status"] == "publication_stopped_inspect" and result["published"] == 0
    assert result["results"][0]["reason"] == (
        "activation_changed_commercial_data"
        if mutation == publication.ACTIVATE
        else "publication_readback_mismatch"
    )
    assert publication_rows(ledger)[0][3] == "pending"
    if mutation == publication.ACTIVATE:
        assert publication.PUBLISH not in [q for q, _ in api.calls]


def test_unconfirmed_publication_readback_retains_pending_attempt(setup):
    ledger, api = setup

    def graphql(query, variables):
        result = api(query, variables)
        if query == publication.PUBLISH:
            api.product["publishedOnPublication"] = False
        return result

    result = publish(ledger, graphql)
    assert result["status"] == "publication_stopped_inspect"
    assert result["results"][0]["reason"] == "publication_readback_mismatch"
    assert result["published"] == 0 and publication_rows(ledger)[0][3] == "pending"


@pytest.mark.parametrize("mutation", [publication.ACTIVATE, publication.PUBLISH])
def test_shopify_user_errors_stop_and_do_not_leak_provider_text(setup, mutation):
    ledger, api = setup

    def graphql(query, variables):
        if query == mutation:
            api.calls.append((query, deepcopy(variables)))
            if query == publication.ACTIVATE:
                return {
                    "productUpdate": {
                        "product": None,
                        "userErrors": [{"message": "secret_remote_response"}],
                    }
                }
            return {"publishablePublish": {"userErrors": [{"message": "secret_remote_response"}]}}
        return api(query, variables)

    result = publish(ledger, graphql)
    assert result["status"] == "publication_stopped_inspect"
    assert "secret_remote_response" not in json.dumps(result)
    assert result["published"] == 0 and publication_rows(ledger)[0][3] == "pending"
    if mutation == publication.ACTIVATE:
        assert publication.PUBLISH not in [q for q, _ in api.calls]


def test_fixture_preserves_real_ledger_metadata_and_other_path_ownership(setup):
    ledger, _ = setup
    simulated, native = ledger.lstat(), ledger.stat()
    assert simulated.st_uid == 0
    assert (simulated.st_mode, simulated.st_nlink, simulated.st_ino) == (
        native.st_mode,
        native.st_nlink,
        native.st_ino,
    )
    other = ledger.with_name("unrelated.txt")
    other.write_text("fixture")
    assert other.lstat().st_uid == other.stat().st_uid
