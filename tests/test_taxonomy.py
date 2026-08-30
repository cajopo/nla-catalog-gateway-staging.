from __future__ import annotations

import json
from pathlib import Path

import pytest

from nla_catalog_gateway.taxonomy import (
    Game,
    ProductFacts,
    ProductFamily,
    TaxonomyError,
    classify_catalog,
    classify_product,
    default_config_path,
    load_taxonomy,
)


def test_default_mapping_classifies_live_magic_displays_without_ids() -> None:
    config = load_taxonomy()
    fixture_path = Path(__file__).with_name("fixtures") / "live_magic_displays_2026-08-31.json"
    fixtures = json.loads(fixture_path.read_text(encoding="utf-8"))
    for fixture in fixtures:
        result = classify_product(
            ProductFacts(
                product_gid=fixture["productGid"],
                product_type=fixture["productType"],
                tags=tuple(fixture["tags"]),
                commercial_title=fixture["commercialTitle"],
            ),
            config,
        )
        assert (result.game, result.family, result.subtype) == (
            Game.MAGIC,
            ProductFamily.SEALED,
            fixture["expectedSubtype"],
        )
        assert result.rule_id == "product-type:magic display"
        assert result.reason is None


def test_known_source_single_requires_canonical_name() -> None:
    config = load_taxonomy()
    valid = classify_product(
        ProductFacts(
            product_gid="gid://shopify/Product/single",
            explicit_game="Pokémon",
            source_record_type="single",
            canonical_card_name="Pikachu",
        ),
        config,
    )
    invalid = classify_product(
        ProductFacts(
            product_gid="gid://shopify/Product/missing-name",
            explicit_game="pokemon",
            source_record_type="single",
        ),
        config,
    )
    assert valid.family is ProductFamily.SINGLE
    assert valid.rule_id == "source-record-type:single"
    assert invalid.family is ProductFamily.UNCLASSIFIED
    assert invalid.reason == "missing_canonical_card_name"


def test_accessory_and_unrecognized_sealed_subtype_are_supported() -> None:
    config = load_taxonomy()
    accessory = classify_product(
        ProductFacts(
            product_gid="gid://shopify/Product/accessory",
            explicit_game="One Piece",
            source_record_type="accessory",
            commercial_title="Card sleeves",
        ),
        config,
    )
    sealed = classify_product(
        ProductFacts(
            product_gid="gid://shopify/Product/sealed",
            explicit_game="YuGiOh",
            source_record_type="sealed",
            commercial_title="Starter Deck",
        ),
        config,
    )
    assert accessory.family is ProductFamily.ACCESSORY
    assert accessory.subtype is None
    assert sealed.family is ProductFamily.SEALED
    assert sealed.subtype is None


@pytest.mark.parametrize(
    ("facts", "reason"),
    [
        (ProductFacts("gid-1"), "missing_game_signal"),
        (ProductFacts("gid-2", explicit_game="unknown"), "unknown_explicit_game"),
        (
            ProductFacts("gid-3", explicit_game="Magic", tags=("Pokemon",)),
            "conflicting_game_signals",
        ),
        (
            ProductFacts("gid-4", explicit_game="Magic", source_record_type="mystery"),
            "unknown_source_record_type",
        ),
        (
            ProductFacts("gid-5", explicit_game="Magic", product_type="New Box Type"),
            "unknown_product_type",
        ),
        (
            ProductFacts("gid-6", explicit_game="Magic"),
            "missing_family_signal",
        ),
        (
            ProductFacts(
                "gid-7",
                explicit_game="Magic",
                source_record_type="sealed",
            ),
            "missing_commercial_title",
        ),
        (
            ProductFacts(
                "gid-8",
                product_type="Magic Display",
                source_record_type="single",
                commercial_title="Booster Box",
                canonical_card_name="Not actually a single",
            ),
            "conflicting_family_signals",
        ),
    ],
)
def test_ambiguous_or_unknown_signals_fail_closed(facts: ProductFacts, reason: str) -> None:
    result = classify_product(facts, load_taxonomy())
    assert result.family is ProductFamily.UNCLASSIFIED
    assert result.reason == reason
    assert result.rule_id is None
    assert result.subtype is None


def test_empty_product_gid_is_rejected() -> None:
    with pytest.raises(TaxonomyError, match="product_gid"):
        classify_product(ProductFacts(" ", explicit_game="Magic"), load_taxonomy())


def test_catalog_report_reconciles_and_is_sorted() -> None:
    config = load_taxonomy()
    products = [
        ProductFacts(
            "sealed",
            product_type="Magic Display",
            commercial_title="Unknown sealed format",
        ),
        ProductFacts(
            "single",
            explicit_game="One Piece",
            source_record_type="single",
            canonical_card_name="Monkey.D.Luffy",
        ),
        ProductFacts("unknown", explicit_game="Magic"),
    ]
    classifications, report = classify_catalog(products, config)
    assert len(classifications) == 3
    assert report.classified == 2
    assert report.unclassified == 1
    assert report.as_dict() == {
        "total": 3,
        "classified": 2,
        "unclassified": 1,
        "counts": {
            "magic/sealed": 1,
            "magic/unclassified": 1,
            "one-piece/single": 1,
        },
        "unclassifiedReasons": {"missing_family_signal": 1},
    }


def test_duplicate_catalog_id_is_rejected() -> None:
    with pytest.raises(TaxonomyError, match="duplicate"):
        classify_catalog([ProductFacts("same"), ProductFacts("same")], load_taxonomy())


def test_invalid_configurations_fail_closed(tmp_path: Path) -> None:
    malformed = tmp_path / "malformed.json"
    malformed.write_text("{", encoding="utf-8")
    with pytest.raises(TaxonomyError, match="invalid taxonomy config"):
        load_taxonomy(malformed)

    empty_version = tmp_path / "empty-version.json"
    document = json.loads(default_config_path().read_text(encoding="utf-8"))
    document["version"] = ""
    empty_version.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(TaxonomyError, match="version"):
        load_taxonomy(empty_version)

    missing_maps = tmp_path / "missing-maps.json"
    document["version"] = "v1"
    document["gameAliases"] = {}
    missing_maps.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(TaxonomyError, match="requires game aliases"):
        load_taxonomy(missing_maps)

    invalid_subtype = tmp_path / "invalid-subtype.json"
    document = json.loads(default_config_path().read_text(encoding="utf-8"))
    document["sealedSubtypes"] = [{"subtype": "", "contains": []}]
    invalid_subtype.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(TaxonomyError, match="sealed subtype"):
        load_taxonomy(invalid_subtype)
