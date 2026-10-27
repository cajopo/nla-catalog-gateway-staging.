"""Synthetic six-game evidence and frozen four-game compatibility for issue #122."""

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

import test_app_proxy_security as proxy_helpers
import test_canonical_names as name_helpers
import test_canonical_reference_extension as extension_helpers
import test_core_evidence as evidence_helpers
import test_generation_bundle as bundle_helpers
import test_pagination as page_helpers
import test_reconciliation as reconciliation_helpers
import test_runtime_api_integration as api_helpers
from nla_catalog_gateway import core_evidence, reconciliation, runtime_api
from nla_catalog_gateway.canonical_names import (
    CANONICAL_GAME_ORDER,
    MANIFEST_FILENAME,
    SIDECAR_FILENAME,
    CanonicalNameRecordV1,
    CanonicalNamesError,
    build_canonical_name_sidecar,
    load_canonical_names,
    load_canonical_names_manifest,
)
from nla_catalog_gateway.canonical_reference_extension import build_extended_reference
from nla_catalog_gateway.card_metadata import CardMetadataV1
from nla_catalog_gateway.facets import parse_url_state, serialize_url_state, switch_game
from nla_catalog_gateway.runtime_contract import (
    DEFAULT_CAPABILITIES_V1,
    CapabilityState,
    CatalogFiltersV1,
    CatalogItemV1,
    CatalogPageV1,
    CatalogProductRecordV1,
    CatalogRequestV1,
    CursorContextV1,
    ProductStatus,
    RequestFamily,
    RuntimeContractError,
    contract_version_for_game,
)
from nla_catalog_gateway.taxonomy import (
    LEGACY_GAMES,
    Game,
    ProductFacts,
    ProductFamily,
    classify_product,
    default_config_path,
    load_taxonomy,
)

NEW_GAMES = (Game.LORCANA, Game.RIFTBOUND)


def test_contract_version_helper_requires_canonical_game_and_preserves_unclassified_v1():
    assert contract_version_for_game(None) == 1
    with pytest.raises(RuntimeContractError, match="game must be canonical"):
        contract_version_for_game("lorcana")


def _new_records():
    records = []
    for index, game in enumerate(NEW_GAMES):
        for offset, family in enumerate(
            (
                ProductFamily.SINGLE,
                ProductFamily.SINGLE,
                ProductFamily.SEALED,
                ProductFamily.ACCESSORY,
            )
        ):
            number = str(10000 + index * 10 + offset)
            record = page_helpers._record(number, game=game, family=family)
            record = replace(record, commercial_title="Shared starter box")
            if family is ProductFamily.SINGLE:
                record = replace(
                    record,
                    canonical_card_name="Shared champion",
                    powertools_source_id=number,
                    sync_source_id=number,
                    card_metadata=CardMetadataV1("RFT-001", "SET", "Shared expansion", "Rare"),
                    total_inventory=offset,
                    variants=(replace(record.variants[0], inventory_quantity=offset),),
                )
            records.append(record)
    return tuple(records)


@pytest.mark.parametrize("game", NEW_GAMES)
def test_new_game_requires_explicit_v2_and_legacy_capability_matrix_stays_frozen(game):
    request = page_helpers._request(game=game, family=RequestFamily.SINGLE)
    assert request.contract_version == 2
    record = next(record for record in _new_records() if record.game is game)
    item = CatalogItemV1.from_product_record(record)
    assert item.contract_version == record.contract_version == 2
    assert CatalogProductRecordV1.from_json_bytes(record.to_json_bytes()) == record
    assert CatalogRequestV1.from_json_bytes(request.to_json_bytes()) == request
    for dto in (request, record, item):
        for version in (1, True, None, 3):
            with pytest.raises(RuntimeContractError):
                replace(dto, contract_version=version)
    assert (
        DEFAULT_CAPABILITIES_V1.request_state(game, RequestFamily.SINGLE)
        is CapabilityState.UNSUPPORTED
    )
    with pytest.raises(RuntimeContractError, match="not verified"):
        request.require_executable()
    for legacy in LEGACY_GAMES:
        assert page_helpers._request(game=legacy).contract_version == 1
        with pytest.raises(RuntimeContractError):
            replace(page_helpers._request(game=legacy), contract_version=2)


@pytest.mark.parametrize("game", (Game.MAGIC, *NEW_GAMES))
def test_cursor_and_page_reject_cross_version_request_context(game):
    request = page_helpers._request(game=game)
    cursor = CursorContextV1.from_request(
        request,
        "sha256:" + "a" * 64,
        last_product_gid=None,
        expires_at="2026-10-27T12:00:00Z",
    )
    page = CatalogPageV1(
        contract_version=request.contract_version,
        dataset_generation=cursor.dataset_generation,
        request=request,
        request_context_sha256=cursor.request_context_sha256,
        items=(),
        returned_product_count=0,
        returned_variant_count=0,
        has_next_page=False,
        next_cursor_context=None,
    )
    assert CursorContextV1.from_json_bytes(cursor.to_json_bytes()) == cursor
    assert CatalogPageV1.from_json_bytes(page.to_json_bytes()) == page
    wrong_version = 2 if request.contract_version == 1 else 1
    for dto in (cursor, page):
        with pytest.raises(RuntimeContractError, match="contractVersion must match request"):
            replace(dto, contract_version=wrong_version)


@pytest.mark.parametrize("game", NEW_GAMES)
def test_taxonomy_uses_declared_importer_type_and_explicit_family_without_title_identity(game):
    taxonomy = load_taxonomy()
    declared_type = "Lorcana Single" if game is Game.LORCANA else "Riftbound Single"
    facts = ProductFacts(
        "gid://shopify/Product/1000",
        product_type=declared_type,
        canonical_card_name="Verified name",
    )
    classified = classify_product(facts, taxonomy)
    assert (classified.game, classified.family) == (game, ProductFamily.SINGLE)
    assert (
        classify_product(replace(facts, canonical_card_name=None), taxonomy).reason
        == "missing_canonical_card_name"
    )
    unknown = classify_product(replace(facts, product_type="Unverified commercial type"), taxonomy)
    assert unknown.family is ProductFamily.UNCLASSIFIED
    for family in (ProductFamily.SEALED, ProductFamily.ACCESSORY):
        structured = ProductFacts(
            facts.product_gid,
            explicit_game=game.value,
            source_record_type=family.value,
            commercial_title="Booster Box - synthetic",
        )
        assert classify_product(structured, taxonomy).family is family
        assert (
            classify_product(replace(structured, explicit_game=None), taxonomy).reason
            == "missing_game_signal"
        )
    rows = [{"gid": facts.product_gid, "product_type": declared_type, "sync_source_id": "900"}]
    with pytest.raises(reconciliation.ReconciliationDataError, match="canonical-name mapping"):
        reconciliation._apply_canonical_names(
            reconciliation_helpers._CanonicalRowsConnection(rows),
            (facts,),
            taxonomy,
            reconciliation_helpers._canonical_names_input(),
        )


def test_legacy_taxonomy_config_is_still_readable_and_new_types_require_new_rules(tmp_path):
    document = json.loads(default_config_path().read_bytes())
    document["classificationRuleVersion"] = "2026-09-07.1"
    document["gameAliases"] = {
        key: value for key, value in document["gameAliases"].items() if value in LEGACY_GAMES
    }
    document["productTypes"] = {
        key: value
        for key, value in document["productTypes"].items()
        if value["game"] in LEGACY_GAMES
    }
    path = tmp_path / "legacy-taxonomy.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    taxonomy = load_taxonomy(path)
    assert taxonomy.rule_version == "2026-09-07.1"
    assert (
        classify_product(
            ProductFacts("gid://shopify/Product/1", explicit_game="lorcana"), taxonomy
        ).reason
        == "unknown_explicit_game"
    )


@pytest.mark.parametrize("game", NEW_GAMES)
def test_product_factory_propagates_v2_from_verified_classification(game):
    record = next(record for record in _new_records() if record.game is game)
    classification = classify_product(
        ProductFacts(
            record.product_gid,
            explicit_game=game.value,
            source_record_type="single",
            canonical_card_name=record.canonical_card_name,
        ),
        load_taxonomy(),
    )
    fields = (
        "handle",
        "commercial_title",
        "canonical_card_name",
        "shopify_status",
        "online_store_published",
        "powertools_source_id",
        "sync_source_id",
        "total_inventory",
        "tracks_inventory",
        "updated_at",
        "variants",
        "card_metadata",
    )
    projected = CatalogProductRecordV1.from_classification(
        classification=classification, **{name: getattr(record, name) for name in fields}
    )
    assert projected.contract_version == 2
    assert projected.game is game


@pytest.mark.parametrize("games", [(Game.LORCANA,), (Game.RIFTBOUND,), NEW_GAMES])
def test_reference_extension_preserves_pinned_v1_and_explicitly_writes_schema2(tmp_path, games):
    parent, pin = extension_helpers.parent(tmp_path)
    old_manifest = (parent / MANIFEST_FILENAME).read_bytes()
    old_sidecar = (parent / SIDECAR_FILENAME).read_bytes()
    additions = [
        CanonicalNameRecordV1(game, str(100 + index), "New verified card")
        for index, game in enumerate(games)
    ]
    result = build_extended_reference(
        parent, pin, additions, output_directory=tmp_path / "extended", generator_code_sha="c" * 40
    )
    assert (parent / MANIFEST_FILENAME).read_bytes() == old_manifest
    assert (parent / SIDECAR_FILENAME).read_bytes() == old_sidecar
    assert load_canonical_names_manifest(old_manifest, expected_sha256=pin).schema_version == 1
    bundle = tmp_path / "extended" / "bundle"
    manifest = load_canonical_names_manifest(
        (bundle / MANIFEST_FILENAME).read_bytes(), expected_sha256=result["manifestSha256"]
    )
    assert manifest.schema_version == 2
    assert tuple(source.game for source in manifest.sources) == (*CANONICAL_GAME_ORDER, *games)
    with (bundle / SIDECAR_FILENAME).open("rb") as stream:
        records = load_canonical_names(stream, manifest=manifest)
    assert all(records[(record.game, record.source_id)] == record for record in additions)
    assert (bundle / SIDECAR_FILENAME).read_bytes().startswith(old_sidecar)
    with pytest.raises(CanonicalNamesError):
        replace(manifest, schema_version=1)
    with pytest.raises(CanonicalNamesError):
        replace(manifest, sources=tuple(reversed(manifest.sources)))
    with pytest.raises(CanonicalNamesError):
        replace(manifest, sources=(*manifest.sources, manifest.sources[-1]))


def test_legacy_builder_output_and_optional_cli_sources(tmp_path):
    from scripts import build_canonical_name_sidecar as cli

    sources, _ = name_helpers._write_sources(tmp_path, {Game.MAGIC: [("1", "Original")]})
    legacy = build_canonical_name_sidecar(
        sources, output_directory=tmp_path / "old", generator_code_sha="a" * 40
    )
    assert legacy.schema_version == 1
    args = []
    for game, source in sources.items():
        args.extend((f"--{game.value}", str(source)))
    for game in NEW_GAMES:
        source = tmp_path / f"{game.value}.csv"
        source.write_bytes(
            name_helpers._csv_bytes([("200" if game is Game.LORCANA else "201", "Shared champion")])
        )
        args.extend((f"--{game.value}", str(source)))
    output = tmp_path / "new"
    assert cli.main([*args, "--output", str(output), "--generator-code-sha", "a" * 40]) == 0
    assert (
        (output / SIDECAR_FILENAME)
        .read_bytes()
        .startswith((tmp_path / "old" / SIDECAR_FILENAME).read_bytes())
    )


def test_signed_runtime_six_games_search_pagination_facets_and_cross_version_rejection(tmp_path):
    records = (*evidence_helpers._records(), *_new_records())
    case = api_helpers._bound_case(tmp_path, "six", records, "a" * 64)
    verifier = proxy_helpers._verifier(
        config=proxy_helpers._config(allowed_shops=frozenset({bundle_helpers.SHOP}))
    )
    service = runtime_api.RuntimeCatalogService(
        expected_shop_domain=bundle_helpers.SHOP,
        backend=case.backend,
        authorizer=runtime_api.AppProxyVerifierAuthorizer(verifier),
        capability_gate=case.gate,
        endpoint_path="/proxy/catalog",
    )
    query = proxy_helpers._signed_query(
        [
            (key, bundle_helpers.SHOP if key == "shop" else value)
            for key, value in proxy_helpers._base_pairs()
        ]
    )

    def call(request, cursor=None):
        body = runtime_api.CatalogRequestEnvelopeV1(
            request,
            cursor,
            contract_version=request.contract_version,
            include_suggestions=cursor is None
            and request.product_family is RequestFamily.SINGLE
            and bool(request.query),
            include_facets=request.product_family is RequestFamily.SINGLE,
        ).to_json_bytes()
        response = service.catalog(
            runtime_api.RuntimeHttpRequest(
                method="POST",
                path="/proxy/catalog",
                raw_query=query,
                headers=(
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ),
                body_chunks=(body,),
            )
        )
        assert response.status == 200
        return runtime_api.CatalogResponseEnvelopeV1.from_json_bytes(response.body)

    for game in Game:
        request = page_helpers._request(game=game, family=RequestFamily.SINGLE, page_size=1)
        response = call(request)
        assert response.contract_version == contract_version_for_game(game)
        gids = []
        while True:
            assert all(item.game is game for item in response.page.items)
            gids.extend(item.product_gid for item in response.page.items)
            if response.next_cursor is None:
                break
            response = call(request, response.next_cursor)
        expected = [
            record.product_gid
            for record in records
            if record.game is game
            and record.publishable
            and record.product_family is ProductFamily.SINGLE
        ]
        assert gids == expected and len(gids) == len(set(gids))
    for game in NEW_GAMES:
        request = page_helpers._request(game=game, family=RequestFamily.SINGLE, query="RFT001")
        response = call(request)
        assert response.page.returned_product_count == 2
        assert response.suggestions[0].print_count == 2
        assert response.suggestions[0].available_print_count == 1
        assert all(facet.values[0].count == 2 for facet in response.facets)
        assert (
            call(replace(request, filters=CatalogFiltersV1(True, None))).page.returned_product_count
            == 1
        )
        assert call(replace(request, query="Shared expansion")).page.returned_product_count == 0
        assert call(replace(request, query="Shared champion")).page.returned_product_count == 2
        assert parse_url_state(serialize_url_state(request)) == request
        assert switch_game(request, Game.MAGIC).contract_version == 1
        assert switch_game(switch_game(request, Game.MAGIC), game).contract_version == 2
        for family in (RequestFamily.SEALED, RequestFamily.ACCESSORY):
            commercial = page_helpers._request(game=game, family=family, query="starter")
            assert call(commercial).page.returned_product_count == 1
        with pytest.raises(runtime_api.RuntimeApiContractError):
            runtime_api.CatalogRequestEnvelopeV1(request, None, contract_version=1)
        with pytest.raises(runtime_api.RuntimeApiContractError):
            replace(response, contract_version=1)
        forged_item = replace(response.page.items[0])
        object.__setattr__(forged_item, "contract_version", 1)
        with pytest.raises(runtime_api.RuntimeApiContractError):
            replace(response.page, items=(forged_item, *response.page.items[1:]))
        object.__setattr__(response, "contract_version", 1)
        with pytest.raises(runtime_api.RuntimeApiContractError):
            response.as_dict()
        with pytest.raises(RuntimeContractError):
            replace(response.page.request, game=Game.MAGIC)


@pytest.mark.parametrize("family", [None, ProductFamily.SEALED, ProductFamily.ACCESSORY])
def test_staged_new_game_coverage_preserves_legacy_requirements(tmp_path, family):
    new = (
        _new_records()[0]
        if family is None
        else next(r for r in _new_records() if r.product_family is family)
    )
    if family is None:
        new = replace(new, shopify_status=ProductStatus.DRAFT, online_store_published=False)
    records = (*evidence_helpers._records(), new)
    core_evidence.verify_catalog_core_evidence(
        evidence_helpers._verified(records),
        projection_path=tmp_path / "staged.sqlite3",
        code_sha="c" * 40,
    )
    missing_legacy = tuple(record for record in records if record.game is not Game.POKEMON)
    with pytest.raises(core_evidence.CatalogCoreEvidenceError):
        core_evidence.verify_catalog_core_evidence(
            evidence_helpers._verified(missing_legacy),
            projection_path=tmp_path / "missing.sqlite3",
            code_sha="c" * 40,
        )


def test_commercial_evidence_traverses_multiple_pages_and_rejects_truncation(tmp_path):
    records = tuple(
        page_helpers._record(str(10000 + number), game=Game.LORCANA, family=ProductFamily.SEALED)
        for number in range(101)
    )
    projection = page_helpers._projection(tmp_path, records)
    paginator = page_helpers._paginator(projection)
    assert core_evidence._verify_commercial_search(records, paginator, Game.LORCANA) > 0
    for cursor in (None, "unexpected-cursor"):
        corrupted = SimpleNamespace(
            fetch_page=lambda *_args, next_cursor=cursor, **_kwargs: SimpleNamespace(
                page=SimpleNamespace(items=()), next_cursor=next_cursor
            )
        )
        with pytest.raises(core_evidence.CatalogCoreEvidenceError):
            core_evidence._verify_commercial_search(records, corrupted, Game.LORCANA)
