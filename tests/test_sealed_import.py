"""Synthetic sealed source -> importer -> publication -> unchanged runtime contracts."""

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts import import_cardtrader_drafts as importer
from scripts import prepare_cardtrader_reference as preparation
from scripts.compare_cardtrader_catalog import CATEGORIES

import test_import_cardtrader_drafts as import_tests
import test_pagination as page_tests
import test_reconciliation as reconciliation_tests
from nla_catalog_gateway import cardtrader_capture as capture
from nla_catalog_gateway import shopify_draft_import as draft
from nla_catalog_gateway import shopify_draft_publication as publication
from nla_catalog_gateway.canonical_names import MANIFEST_FILENAME, SIDECAR_FILENAME
from nla_catalog_gateway.cardtrader_candidates import compare_catalog
from nla_catalog_gateway.reconciliation import reconcile_snapshot_parts
from nla_catalog_gateway.runtime_contract import ProductFamily, RequestFamily
from nla_catalog_gateway.taxonomy import load_taxonomy
from test_multigame_import import SixGameSource
from test_shopify_draft_import import GID, SHOP, FakeShopify
from test_shopify_draft_import import run as create
from test_shopify_draft_publication import FakePublication, publish, writes

import_case = import_tests.setup


class SealedShopify(FakeShopify):
    def __call__(self, query, variables):
        if query == draft.CREATE_DRAFT:
            product = variables["product"]
            self.product.update(handle=product["handle"], productType=product["productType"])
            for alias, field in zip(
                ("nlaGame", "sourceRecordType"), product["metafields"], strict=True
            ):
                self.product[alias] = {"type": field["type"], "value": field["value"]}
        result = super().__call__(query, variables)
        if query == draft.SET_IDENTITIES:
            for alias, field in zip(
                ("syncProductId", "powertoolsId"), variables["metafields"], strict=True
            ):
                self.product[alias] = {"type": field["type"], "value": field["value"]}
        return result


def sealed_source(game_id, category):
    source = SixGameSource()
    row = deepcopy(source.rows[100 + game_id][0])
    row.update(category_id=category, name="Synthetic Expansion Booster Box", fixed_properties={})
    source.rows = {key: [] for key in source.rows}
    source.rows[100 + game_id] = [row]
    return source


@pytest.mark.parametrize("game_id,category", [(18, 215), (22, 259), (4, 54)])
def test_sealed_capture_import_publication_to_real_runtime(
    import_case, tmp_path, monkeypatch, game_id, category
):
    args, original, _, _ = import_case
    source = sealed_source(game_id, category)
    root = tmp_path / "sealed-capture"
    capture.capture_catalog(source, root, game_scope="six-games")
    args["capture"] = root
    api = SealedShopify()
    args["client"] = SimpleNamespace(graphql=api)
    monkeypatch.setattr(importer.identities, "missing_guard", lambda *_: lambda _: True)
    parent = Path(original["reference"])
    before = {name: (parent / name).read_bytes() for name in (MANIFEST_FILENAME, SIDECAR_FILENAME)}
    result = importer.run_locked(**args, apply=True)
    assert result["status"] == "batch_complete"
    assert result["attempts"][0]["status"] == "draft_verified"
    prepared = json.loads((args["run"] / "reference/preparation.json").read_bytes())
    assert prepared["reference"] == str(parent)
    assert prepared["referenceEvidence"]["addedRecords"] == 0
    assert prepared["candidates"][0]["productFamily"] == "sealed"
    assert all((parent / name).read_bytes() == value for name, value in before.items())
    assert json.loads(args["config_path"].read_bytes()) == original
    request = next(v["product"] for q, v in api.calls if q == draft.CREATE_DRAFT)
    assert (
        request["productType"] == "" and request["title"] == source.rows[100 + game_id][0]["name"]
    )
    assert set(request) == {"title", "productType", "handle", "status", "metafields"} | (
        {"tags"} if game_id in (18, 22) else set()
    )
    if game_id in (18, 22):
        assert request["tags"] == ["Lorcana" if game_id == 18 else "Riftbound", "Synthetic Set"]
    publisher = FakePublication(api.product)
    publisher.product.update(productType="", title=request["title"])
    assert publish(args["ledger"], publisher)["published"] == 1
    count = len(writes(publisher))
    publisher.product["sourceRecordType"]["value"] = "single"
    assert publish(args["ledger"], publisher)["published"] == 0
    assert len(writes(publisher)) == count  # Completed ownership handoff is terminal.

    # Feed the actual generated fields through the real Bulk reconciliation,
    # projection builder and runtime family pagination, not synthetic DTOs.
    rec = reconciliation_tests
    product = rec._product(
        123, handle=request["handle"], source_id=str(2000 + game_id), product_type=""
    )
    product.update(title=request["title"], tags=[])
    rows = [product, rec._publication(123)] + [
        rec._metafield(GID, 900 + i, field["key"], field["value"])
        for i, field in enumerate(request["metafields"])
    ]
    variants = [rec._variant(123, 456, 789)]
    expected = rec._expectation(
        product_count=1, variant_count=1, expected_active_online_store_published_product_count=1
    )
    inputs = rec._inputs(tmp_path / "bulk", products=rows, variants=variants, expectation=expected)
    reconciled = reconcile_snapshot_parts(
        inputs, expectation=expected, taxonomy_config=load_taxonomy()
    )
    record = reconciled.records[0]
    assert record.product_family is ProductFamily.SEALED
    assert record.game.value == prepared["candidates"][0]["game"]
    assert record.canonical_card_name is None and record.card_metadata is None
    projection = page_tests._projection(tmp_path / "projection", reconciled.records)
    request_scope = page_tests._request(
        game=record.game, family=RequestFamily.SEALED, query="Synthetic Expansion"
    )
    assert [
        p.product_gid
        for p in page_tests._paginator(projection).fetch_page(request_scope).page.items
    ] == [GID]
    single_scope = page_tests._request(game=record.game, family=RequestFamily.SINGLE)
    assert page_tests._paginator(projection).fetch_page(single_scope).page.items == ()


@pytest.mark.parametrize(
    "category", [i for i, (_, _, family) in CATEGORIES.items() if family == "sealed"]
)
def test_every_declared_sealed_category_accepts_future_expansion(category):
    game_id, _, _ = CATEGORIES[category]
    row = dict(
        id=9999, game_id=game_id, category_id=category, expansion_id=99999, card_market_ids=[88888]
    )
    result = compare_catalog(
        [row], [], {i: (g, f) for i, (g, _, f) in CATEGORIES.items()}, {99999: game_id}
    )[0]
    assert (
        result["decision"] == "absent_from_supplied_snapshot"
        and result["productFamily"] == "sealed"
    )
    assert result["creationApproved"] is False


@pytest.mark.parametrize(
    "kind",
    [
        "missing",
        "multiple",
        "shared",
        "wrong_family",
        "wrong_game",
        "duplicate_products",
        "duplicate_blueprints",
    ],
)
def test_sealed_identity_ambiguities_do_not_become_candidates(kind):
    row = dict(id=1, game_id=18, category_id=215, expansion_id=118, card_market_ids=[42])
    product = dict(
        productGid=GID,
        game="lorcana",
        productFamily="sealed",
        syncSourceId="42",
        powerToolsSourceId="42",
    )
    rows = [row]
    products = []
    expected = {
        "missing": "missing_cardmarket_id",
        "multiple": "multiple_cardmarket_ids",
        "shared": "shared_cardmarket_id",
        "wrong_family": "shopify_identity_conflict",
        "wrong_game": "shopify_identity_conflict",
        "duplicate_products": "multiple_shopify_products",
        "duplicate_blueprints": "duplicate_blueprint_id",
    }[kind]
    if kind == "missing":
        row["card_market_ids"] = []
    if kind == "multiple":
        row["card_market_ids"] = [42, 43]
    if kind == "shared":
        rows.append({**row, "id": 2, "category_id": 214})
    if kind == "duplicate_blueprints":
        rows.append(deepcopy(row))
    if kind == "wrong_family":
        products = [{**product, "productFamily": "single"}]
    if kind == "wrong_game":
        products = [{**product, "game": "riftbound"}]
    if kind == "duplicate_products":
        products = [product, {**product, "productGid": "gid://shopify/Product/456"}]
    report = compare_catalog(
        rows, products, {i: (g, f) for i, (g, _, f) in CATEGORIES.items()}, {118: 18}
    )
    assert all(r["decision"] == expected for r in report)


@pytest.mark.parametrize("field", ["nlaGame", "sourceRecordType", "productType"])
def test_sealed_draft_classification_must_read_back_before_verified(tmp_path, field):
    api = SealedShopify()

    def altered(query, variables):
        result = api(query, variables)
        if query == draft.VERIFY_DRAFT:
            result["product"].pop(field)
        return result

    result = create(tmp_path, altered, game="lorcana", product_family="sealed")
    assert result["status"] == "needs_reconciliation"
    calls = len(api.calls)
    assert (
        create(tmp_path, api, game="lorcana", product_family="sealed")["status"]
        == "already_reserved"
    )
    assert len(api.calls) == calls


@pytest.mark.parametrize("field", ["nlaGame", "sourceRecordType", "productType"])
def test_sealed_publication_refuses_classification_drift(tmp_path, monkeypatch, field):
    api = SealedShopify()
    assert (
        create(tmp_path, api, game="lorcana", product_family="sealed")["status"] == "draft_verified"
    )
    publisher = FakePublication(api.product)
    publisher.product["productType"] = ""
    publisher.product[field] = (
        "wrong" if field == "productType" else {"type": "single_line_text_field", "value": "wrong"}
    )
    monkeypatch.setattr(publication, "validate_ledger", lambda _: None)
    result = publish(tmp_path / "ledger.sqlite", publisher)
    assert result["published"] == 0 and writes(publisher) == []


def test_already_published_sealed_requires_verified_classification(tmp_path, monkeypatch):
    api = SealedShopify()
    assert (
        create(tmp_path, api, game="lorcana", product_family="sealed")["status"] == "draft_verified"
    )
    publisher = FakePublication(api.product)
    publisher.product.update(productType="", status="ACTIVE", publishedOnPublication=True)
    publisher.product["sourceRecordType"]["value"] = "single"
    monkeypatch.setattr(publication, "validate_ledger", lambda _: None)
    result = publish(tmp_path / "ledger.sqlite", publisher)
    assert result["status"] == "publication_stopped_inspect"
    assert result["results"][0]["reason"] == "sealed_classification_mismatch"
    assert result["published"] == 0 and writes(publisher) == []


def test_resumed_published_sealed_rejects_classification_drift(tmp_path, monkeypatch):
    api = SealedShopify()
    assert (
        create(tmp_path, api, game="lorcana", product_family="sealed")["status"] == "draft_verified"
    )
    publisher = FakePublication(api.product)
    publisher.product["productType"] = ""
    monkeypatch.setattr(publication, "validate_ledger", lambda _: None)

    def lost_response(query, variables):
        result = publisher(query, variables)
        if query == publication.PUBLISH:
            raise TimeoutError("response lost")
        return result

    ledger = tmp_path / "ledger.sqlite"
    assert publish(ledger, lost_response)["status"] == "publication_stopped_inspect"
    publisher.product["sourceRecordType"]["value"] = "single"
    publisher.calls.clear()
    result = publish(ledger, publisher)
    assert result["status"] == "publication_stopped_inspect"
    assert result["results"][0]["reason"] == "sealed_classification_mismatch"
    assert not writes(publisher)


def test_sealed_and_single_share_the_same_no_resend_reservation(tmp_path):
    api = SealedShopify()
    assert (
        create(tmp_path, api, game="lorcana", product_family="sealed")["status"] == "draft_verified"
    )
    count = len(api.calls)
    assert (
        create(tmp_path, api, game="lorcana", product_family="single")["status"]
        == "already_reserved"
    )
    assert len(api.calls) == count


@pytest.mark.parametrize("family", ["accessory", "unclassified", "", None])
def test_unsupported_import_family_fails_before_file_or_api(tmp_path, family):
    api = SealedShopify()
    with pytest.raises(ValueError, match="invalid_import_product"):
        create(tmp_path, api, product_family=family)
    assert not api.calls and not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "case",
    ["canonical_conflict", "empty_title", "nonstring_title", "long_title", "family_mismatch"],
)
def test_sealed_preparation_quarantines_source_and_reference_conflicts(
    import_case, tmp_path, monkeypatch, case
):
    args, original, api, _ = import_case
    source = sealed_source(18, 215)
    row = source.rows[118][0]
    if case == "canonical_conflict":
        row["card_market_ids"] = [1]
    elif case == "empty_title":
        row["name"] = " "
    elif case == "nonstring_title":
        row["name"] = 10
    elif case == "long_title":
        row["name"] = "x" * 256
    if case == "family_mismatch":
        compare = preparation.compare_projection

        def mismatched(*values):
            report = compare(*values)
            report["details"][0]["productFamily"] = "single"
            return report

        monkeypatch.setattr(preparation, "compare_projection", mismatched)
    root = tmp_path / "invalid-sealed"
    capture.capture_catalog(source, root, game_scope="six-games")
    args["capture"] = root
    result = importer.run_locked(**args, apply=True)
    assert result["candidates"] == 0 and result["exceptions"] == 1
    assert result["attempts"] == [] and not api.calls
    assert json.loads(args["config_path"].read_bytes()) == original


def test_sealed_existing_identity_match_and_fresh_guard_absence(tmp_path):
    row = dict(id=1, game_id=18, category_id=215, expansion_id=118, card_market_ids=[42])
    product = dict(
        productGid=GID,
        game="lorcana",
        productFamily="sealed",
        syncSourceId="42",
        powerToolsSourceId="42",
    )
    report = compare_catalog(
        [row], [product], {i: (g, f) for i, (g, _, f) in CATEGORIES.items()}, {118: 18}
    )
    assert report[0]["decision"] == "existing_identity_match"
    api = SealedShopify()
    assert (
        create(
            tmp_path, api, game="lorcana", product_family="sealed", verify_missing=lambda: False
        )["status"]
        == "not_verified_missing"
    )
    assert all(not q.lstrip().startswith("mutation") for q, _ in api.calls)


def test_sealed_inspection_detects_metadata_change_without_resend(tmp_path):
    api = SealedShopify()
    assert (
        create(tmp_path, api, game="lorcana", product_family="sealed")["status"] == "draft_verified"
    )
    ledger = tmp_path / "ledger.sqlite"
    assert (
        draft.inspect_draft_attempt(ledger, shop=SHOP, cardmarket_id=42, graphql=api)["status"]
        == "recorded_draft_matches"
    )
    api.product["nlaGame"]["value"] = "riftbound"
    before = ledger.read_bytes()
    result = draft.inspect_draft_attempt(ledger, shop=SHOP, cardmarket_id=42, graphql=api)
    assert result["status"] == "inspection_unconfirmed" and result["retryAllowed"] is False
    assert ledger.read_bytes() == before
