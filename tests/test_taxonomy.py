from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from nla_catalog_gateway.taxonomy import (
    Game,
    ProductFacts,
    ProductFamily,
    TaxonomyConfig,
    TaxonomyError,
    classify_catalog,
    classify_product,
    default_config_path,
    load_taxonomy,
)

FIXTURE_PATH = Path(__file__).with_name("fixtures") / "synthetic_magic_display_taxonomy.json"


def _document() -> dict[str, Any]:
    return json.loads(default_config_path().read_text(encoding="utf-8"))


def _write_config(tmp_path: Path, document: Any, name: str = "taxonomy.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    return path


def _single(gid: int = 1, **changes: Any) -> ProductFacts:
    facts = ProductFacts(
        product_gid=f"gid://shopify/Product/{gid}",
        explicit_game="Magic",
        source_record_type="single",
        canonical_card_name="Lightning Bolt",
    )
    return replace(facts, **changes)


@pytest.mark.parametrize(
    ("alias", "expected"),
    [
        ("  MAGIC:   THE GATHERING ", Game.MAGIC),
        ("POKE\u0301MON", Game.POKEMON),
        (" Yu-Gi-Oh! ", Game.YUGIOH),
        ("ONE PIECE", Game.ONE_PIECE),
    ],
)
def test_default_aliases_normalize_all_supported_games(alias: str, expected: Game) -> None:
    result = classify_product(_single(explicit_game=alias), load_taxonomy())
    assert result.game is expected
    assert result.family is ProductFamily.SINGLE
    assert result.rule_version == "2026-09-07.1"
    assert result.rule_id == "source-record-type:single"
    assert result.reason is None


@pytest.mark.parametrize("game", Game)
def test_serialized_game_values_round_trip_as_explicit_game(game: Game) -> None:
    result = classify_product(_single(explicit_game=game.value), load_taxonomy())
    assert result.game is game
    assert result.as_dict()["game"] == game.value


def test_default_config_is_immutable_and_versioned() -> None:
    config = load_taxonomy()
    assert config.schema_version == 1
    assert config.rule_version == "2026-09-07.1"
    with pytest.raises(TypeError):
        config.game_aliases["new"] = Game.MAGIC  # type: ignore[index]


def test_classification_serialization_includes_rule_or_reason() -> None:
    classified = classify_product(_single(), load_taxonomy())
    assert classified.as_dict() == {
        "productGid": "gid://shopify/Product/1",
        "game": "magic",
        "productFamily": "single",
        "productSubtype": None,
        "classificationRuleVersion": "2026-09-07.1",
        "classificationRuleId": "source-record-type:single",
        "unclassifiedReason": None,
        "subtypeRuleId": None,
        "subtypeReason": None,
    }
    unclassified = classify_product(ProductFacts("gid://shopify/Product/2"), load_taxonomy())
    payload = unclassified.as_dict()
    assert payload["game"] is None
    assert payload["classificationRuleVersion"] == "2026-09-07.1"
    assert payload["classificationRuleId"] is None
    assert payload["unclassifiedReason"] == "missing_game_signal"


def test_synthetic_magic_display_fixture_uses_structured_type_not_gid() -> None:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    config_text = default_config_path().read_text(encoding="utf-8")
    assert set(fixture) == {"schemaVersion", "provenance", "records"}
    assert fixture["schemaVersion"] == 1
    assert fixture["provenance"] == {
        "source": "synthetic",
        "purpose": "taxonomy-contract-only",
        "containsProductionData": False,
    }
    assert len(fixture["records"]) == 4
    assert {record["expectedSubtype"] for record in fixture["records"]} == {
        "booster-box",
        "collector-booster-box",
    }
    assert len({record["productGid"] for record in fixture["records"]}) == 4
    before = deepcopy(fixture["records"])
    for record in fixture["records"]:
        assert set(record) == {
            "productGid",
            "productType",
            "tags",
            "commercialTitle",
            "expectedSubtype",
        }
        assert record["productGid"].startswith("gid://shopify/Product/90000000000000000")
        assert record["tags"] == ["Synthetic Fixture Tag"]
        assert record["commercialTitle"].startswith("Synthetic ")
        assert record["productGid"] not in config_text
        result = classify_product(
            ProductFacts(
                product_gid=record["productGid"],
                product_type=record["productType"],
                tags=tuple(record["tags"]),
                commercial_title=record["commercialTitle"],
            ),
            load_taxonomy(),
        )
        assert (result.game, result.family, result.subtype) == (
            Game.MAGIC,
            ProductFamily.SEALED,
            record["expectedSubtype"],
        )
        assert result.rule_id == "product-type:magic-display"
        assert result.subtype_rule_id == f"sealed-subtype:{record['expectedSubtype']}"
        assert result.reason is None
        assert result.subtype_reason is None
    assert fixture["records"] == before


def test_new_gid_with_known_product_type_is_classified_without_an_id_rule() -> None:
    result = classify_product(
        ProductFacts(
            product_gid="gid://shopify/Product/99999999999999",
            product_type=" magic   display ",
            commercial_title="Future Collector Booster Box - Future Set",
        ),
        load_taxonomy(),
    )
    assert (result.game, result.family, result.subtype) == (
        Game.MAGIC,
        ProductFamily.SEALED,
        "collector-booster-box",
    )


@pytest.mark.parametrize(
    ("product_type", "expected_game", "expected_rule_id"),
    [
        ("Magic Single", Game.MAGIC, "product-type:magic-single"),
        ("Pokémon Single", Game.POKEMON, "product-type:pokemon-single"),
        ("Yu-Gi-Oh! Single", Game.YUGIOH, "product-type:yu-gi-oh-single"),
        ("Yugioh Single", Game.YUGIOH, "product-type:yugioh-single"),
        ("One Piece Single", Game.ONE_PIECE, "product-type:one-piece-single"),
    ],
)
def test_observed_single_product_types_classify_from_structured_type_only(
    product_type: str,
    expected_game: Game,
    expected_rule_id: str,
) -> None:
    result = classify_product(
        _single(
            product_type=product_type,
            explicit_game=None,
            source_record_type=None,
        ),
        load_taxonomy(),
    )
    assert (result.game, result.family) == (expected_game, ProductFamily.SINGLE)
    assert result.rule_version == "2026-09-07.1"
    assert result.rule_id == expected_rule_id
    assert result.reason is None


@pytest.mark.parametrize(
    ("facts", "reason"),
    [
        (ProductFacts("gid://shopify/Product/10"), "missing_game_signal"),
        (_single(11, explicit_game="unknown"), "unknown_explicit_game"),
        (_single(12, explicit_game="Magic", tags=("Pokemon",)), "conflicting_game_signals"),
        (
            ProductFacts(
                "gid://shopify/Product/13",
                product_type="Magic Display",
                tags=("Pokemon",),
                commercial_title="Booster Box - Set",
            ),
            "conflicting_game_signals",
        ),
        (_single(14, source_record_type="mystery"), "unknown_source_record_type"),
        (_single(15, product_type="Unknown Box"), "unknown_product_type"),
        (_single(16, source_record_type=None), "missing_family_signal"),
        (_single(17, canonical_card_name=None), "missing_canonical_card_name"),
        (
            ProductFacts(
                "gid://shopify/Product/18",
                explicit_game="One Piece",
                source_record_type="sealed",
            ),
            "missing_commercial_title",
        ),
        (
            ProductFacts(
                "gid://shopify/Product/19",
                explicit_game="One Piece",
                source_record_type="accessory",
            ),
            "missing_commercial_title",
        ),
        (
            ProductFacts(
                "gid://shopify/Product/20",
                product_type="Magic Display",
                source_record_type="single",
                commercial_title="Booster Box - Set",
                canonical_card_name="Not a single",
            ),
            "conflicting_family_signals",
        ),
    ],
)
def test_unknown_missing_and_conflicting_signals_are_unclassified(
    facts: ProductFacts, reason: str
) -> None:
    result = classify_product(facts, load_taxonomy())
    assert result.family is ProductFamily.UNCLASSIFIED
    assert result.rule_version == "2026-09-07.1"
    assert result.rule_id is None
    assert result.reason == reason
    assert result.subtype is None


def test_unknown_structured_type_is_reported_even_without_a_game_signal() -> None:
    unknown_product_type = classify_product(
        ProductFacts("gid://shopify/Product/101", product_type="Future Box"),
        load_taxonomy(),
    )
    unknown_source_type = classify_product(
        ProductFacts("gid://shopify/Product/102", source_record_type="future"),
        load_taxonomy(),
    )
    assert (unknown_product_type.game, unknown_product_type.reason) == (
        None,
        "unknown_product_type",
    )
    assert (unknown_source_type.game, unknown_source_type.reason) == (
        None,
        "unknown_source_record_type",
    )


def test_title_never_promotes_a_product_to_sealed() -> None:
    result = classify_product(
        ProductFacts(
            "gid://shopify/Product/21",
            explicit_game="Magic",
            commercial_title="Collector Booster Box - Set",
        ),
        load_taxonomy(),
    )
    assert result.family is ProductFamily.UNCLASSIFIED
    assert result.reason == "missing_family_signal"


def test_subtype_is_family_bounded_and_unknown_subtype_stays_sealed() -> None:
    config = load_taxonomy()
    single = classify_product(_single(22, commercial_title="Collector Booster Box - Set"), config)
    accessory = classify_product(
        ProductFacts(
            "gid://shopify/Product/23",
            explicit_game="One Piece",
            source_record_type="accessory",
            commercial_title="Collector Booster Box - sleeves",
        ),
        config,
    )
    sealed = classify_product(
        ProductFacts(
            "gid://shopify/Product/24",
            explicit_game="YuGiOh",
            source_record_type="sealed",
            commercial_title="Starter Deck",
        ),
        config,
    )
    topper = classify_product(
        ProductFacts(
            "gid://shopify/Product/25",
            explicit_game="Magic",
            source_record_type="sealed",
            commercial_title="Booster Box Topper Pack - Set",
        ),
        config,
    )
    assert single.subtype is single.subtype_reason is None
    assert accessory.subtype is accessory.subtype_reason is None
    assert sealed.family is ProductFamily.SEALED
    assert (sealed.subtype, sealed.subtype_reason) == (None, "no_matching_subtype_rule")
    assert (topper.subtype, topper.subtype_reason) == (None, "no_matching_subtype_rule")


def test_subtype_specificity_is_independent_of_config_order(tmp_path: Path) -> None:
    document = _document()
    document["sealedSubtypeRules"].reverse()
    config = load_taxonomy(_write_config(tmp_path, document))
    result = classify_product(
        ProductFacts(
            "gid://shopify/Product/26",
            explicit_game="Magic",
            source_record_type="sealed",
            commercial_title="Collector Booster Box - Set",
        ),
        config,
    )
    assert result.subtype == "collector-booster-box"
    assert result.subtype_rule_id == "sealed-subtype:collector-booster-box"


def test_equal_specificity_different_subtypes_is_audited_as_ambiguous(tmp_path: Path) -> None:
    document = _document()
    document["sealedSubtypeRules"] = [
        {
            "id": "sealed-subtype:alpha",
            "productSubtype": "alpha",
            "containsAll": ["alpha box -"],
        },
        {
            "id": "sealed-subtype:omega",
            "productSubtype": "omega",
            "containsAll": ["omega box -"],
        },
    ]
    config = load_taxonomy(_write_config(tmp_path, document))
    result = classify_product(
        ProductFacts(
            "gid://shopify/Product/27",
            explicit_game="Magic",
            source_record_type="sealed",
            commercial_title="Alpha Box - Omega Box - Set",
        ),
        config,
    )
    assert result.family is ProductFamily.SEALED
    assert (result.subtype, result.subtype_rule_id) == (None, None)
    assert result.subtype_reason == "ambiguous_subtype_match"


def test_equal_specificity_same_subtype_has_stable_rule_id(tmp_path: Path) -> None:
    document = _document()
    document["sealedSubtypeRules"] = [
        {
            "id": "sealed-subtype:zeta",
            "productSubtype": "box",
            "containsAll": ["omega box -"],
        },
        {
            "id": "sealed-subtype:alpha",
            "productSubtype": "box",
            "containsAll": ["alpha box -"],
        },
    ]
    config = load_taxonomy(_write_config(tmp_path, document))
    result = classify_product(
        ProductFacts(
            "gid://shopify/Product/28",
            explicit_game="Magic",
            source_record_type="sealed",
            commercial_title="Alpha Box - Omega Box - Set",
        ),
        config,
    )
    assert result.subtype == "box"
    assert result.subtype_rule_id == "sealed-subtype:alpha"


def test_catalog_report_accounts_for_every_record_and_rule() -> None:
    products = (
        ProductFacts(
            "gid://shopify/Product/30",
            product_type="Magic Display",
            commercial_title="Unknown sealed format",
        ),
        ProductFacts(
            "gid://shopify/Product/31",
            explicit_game="One Piece",
            source_record_type="single",
            canonical_card_name="Monkey.D.Luffy",
        ),
        ProductFacts("gid://shopify/Product/32", explicit_game="Magic"),
    )
    classifications, report = classify_catalog(iter(products), load_taxonomy())
    assert len(classifications) == report.total == report.classified + report.unclassified == 3
    assert report.as_dict() == {
        "classificationRuleVersion": "2026-09-07.1",
        "total": 3,
        "classified": 2,
        "unclassified": 1,
        "counts": {
            "magic/sealed": 1,
            "magic/unclassified": 1,
            "one-piece/single": 1,
        },
        "ruleCounts": {
            "product-type:magic-display": 1,
            "source-record-type:single": 1,
        },
        "unclassifiedReasons": {"missing_family_signal": 1},
        "subtypeReasons": {"no_matching_subtype_rule": 1},
    }


def test_empty_catalog_has_a_reconciled_empty_report() -> None:
    classifications, report = classify_catalog([], load_taxonomy())
    assert classifications == ()
    assert report.as_dict() == {
        "classificationRuleVersion": "2026-09-07.1",
        "total": 0,
        "classified": 0,
        "unclassified": 0,
        "counts": {},
        "ruleCounts": {},
        "unclassifiedReasons": {},
        "subtypeReasons": {},
    }


def test_duplicate_gid_is_a_hard_error() -> None:
    with pytest.raises(TaxonomyError, match="duplicate product_gid"):
        classify_catalog([_single(40), _single(40)], load_taxonomy())


@pytest.mark.parametrize(
    "gid",
    [
        "",
        " ",
        "gid://shopify/Product/0",
        "gid://shopify/Product/01",
        "gid://shopify/ProductVariant/1",
        "gid://shopify/Product/1 ",
        1,
        None,
    ],
)
def test_malformed_or_mistyped_gid_is_a_hard_error(gid: Any) -> None:
    with pytest.raises(TaxonomyError, match="canonical Shopify Product GID"):
        classify_product(ProductFacts(product_gid=gid), load_taxonomy())  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"explicit_game": 1}, "explicit_game"),
        ({"source_record_type": 1}, "source_record_type"),
        ({"canonical_card_name": 1}, "canonical_card_name"),
        ({"product_type": None}, "product_type"),
        ({"commercial_title": None}, "commercial_title"),
        ({"tags": ["Magic"]}, "tags"),
        ({"tags": ("Magic", 1)}, "tags"),
    ],
)
def test_mistyped_product_fields_are_hard_errors(changes: dict[str, Any], message: str) -> None:
    with pytest.raises(TaxonomyError, match=message):
        classify_product(_single(**changes), load_taxonomy())


def test_catalog_and_config_types_are_validated() -> None:
    config = load_taxonomy()
    with pytest.raises(TaxonomyError, match="TaxonomyConfig"):
        classify_product(_single(), object())  # type: ignore[arg-type]
    with pytest.raises(TaxonomyError, match="TaxonomyConfig"):
        classify_catalog([], object())  # type: ignore[arg-type]
    with pytest.raises(TaxonomyError, match="iterable of ProductFacts"):
        classify_catalog("not-products", config)
    with pytest.raises(TaxonomyError, match="must be iterable"):
        classify_catalog(1, config)  # type: ignore[arg-type]
    with pytest.raises(TaxonomyError, match="must contain ProductFacts"):
        classify_catalog([object()], config)  # type: ignore[list-item]


def test_taxonomy_config_cannot_be_constructed_or_forged_directly() -> None:
    with pytest.raises(TypeError, match="must be created by load_taxonomy"):
        TaxonomyConfig()  # type: ignore[call-arg]

    unvalidated = object.__new__(TaxonomyConfig)
    with pytest.raises(TaxonomyError, match="TaxonomyConfig"):
        classify_catalog([], unvalidated)


def test_unreadable_malformed_duplicate_and_nonobject_json_are_rejected(
    tmp_path: Path,
) -> None:
    with pytest.raises(TaxonomyError, match="cannot read taxonomy config"):
        load_taxonomy(tmp_path / "missing.json")

    malformed = tmp_path / "malformed.json"
    malformed.write_text("{", encoding="utf-8")
    with pytest.raises(TaxonomyError, match="invalid taxonomy JSON"):
        load_taxonomy(malformed)

    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"schemaVersion":1,"schemaVersion":1}', encoding="utf-8")
    with pytest.raises(TaxonomyError, match="duplicate JSON key"):
        load_taxonomy(duplicate)

    with pytest.raises(TaxonomyError, match="taxonomy must be an object"):
        load_taxonomy(_write_config(tmp_path, [], "array.json"))


def test_top_level_keys_schema_and_version_are_strict(tmp_path: Path) -> None:
    document = _document()
    document.pop("productTypes")
    document["unexpected"] = True
    with pytest.raises(TaxonomyError, match=r"missing=.*productTypes.*unexpected=.*unexpected"):
        load_taxonomy(_write_config(tmp_path, document, "keys.json"))

    for index, schema_version in enumerate((True, 2)):
        document = _document()
        document["schemaVersion"] = schema_version
        with pytest.raises(TaxonomyError, match="schemaVersion"):
            load_taxonomy(_write_config(tmp_path, document, f"schema-{index}.json"))

    for index, rule_version in enumerate((" ", 1)):
        document = _document()
        document["classificationRuleVersion"] = rule_version
        with pytest.raises(TaxonomyError, match="classificationRuleVersion"):
            load_taxonomy(_write_config(tmp_path, document, f"version-{index}.json"))


def test_mapping_cannot_contain_a_shopify_product_gid(tmp_path: Path) -> None:
    document = _document()
    document["productTypes"]["gid://shopify/Product/123"] = {
        "game": "magic",
        "productFamily": "sealed",
    }
    with pytest.raises(TaxonomyError, match="must not contain Shopify product identity"):
        load_taxonomy(_write_config(tmp_path, document))


@pytest.mark.parametrize("location", ["key", "value", "fragment"])
def test_mapping_cannot_contain_a_bare_shopify_product_id(tmp_path: Path, location: str) -> None:
    document = _document()
    product_id = "900000000000009999"
    if location == "key":
        document["productTypes"][product_id] = {
            "id": "product-type:forbidden",
            "game": "magic",
            "productFamily": "sealed",
        }
    elif location == "value":
        document["productTypes"]["Magic Display"]["id"] = product_id
    else:
        document["sealedSubtypeRules"][0]["containsAll"] = [product_id]
    with pytest.raises(TaxonomyError, match="must not contain Shopify product identity"):
        load_taxonomy(_write_config(tmp_path, document, f"bare-id-{location}.json"))


@pytest.mark.parametrize("section", ["gameAliases", "productTypes", "sourceRecordTypes"])
def test_normalized_mapping_sections_must_be_objects(tmp_path: Path, section: str) -> None:
    document = _document()
    document[section] = []
    with pytest.raises(TaxonomyError, match=f"{section} must be an object"):
        load_taxonomy(_write_config(tmp_path, document))


@pytest.mark.parametrize(
    ("section", "first", "second"),
    [
        ("gameAliases", " ", None),
        ("gameAliases", "Magic", " magic "),
        ("productTypes", " ", None),
        ("productTypes", "Magic Display", " magic   display "),
        ("sourceRecordTypes", " ", None),
        ("sourceRecordTypes", "single", " SINGLE "),
    ],
)
def test_normalized_mapping_keys_cannot_be_empty_or_collide(
    tmp_path: Path, section: str, first: str, second: str | None
) -> None:
    document = _document()
    existing = next(iter(document[section].values()))
    if first.strip():
        document[section].pop(first, None)
    document[section][first] = existing
    if second is not None:
        document[section][second] = existing
        message = "normalized key collision"
    else:
        message = "empty normalized key"
    with pytest.raises(TaxonomyError, match=message):
        load_taxonomy(_write_config(tmp_path, document))


def test_game_aliases_require_supported_typed_targets_and_full_coverage(tmp_path: Path) -> None:
    for index, target in enumerate((1, "chess")):
        document = _document()
        document["gameAliases"]["magic"] = target
        with pytest.raises(TaxonomyError, match=r"supported game|unsupported game"):
            load_taxonomy(_write_config(tmp_path, document, f"game-target-{index}.json"))

    document = _document()
    document["gameAliases"] = {"magic": "magic"}
    with pytest.raises(TaxonomyError, match="cover every supported game"):
        load_taxonomy(_write_config(tmp_path, document, "game-coverage.json"))


@pytest.mark.parametrize("mutation", ["omitted", "swapped"])
def test_game_aliases_require_canonical_self_aliases(tmp_path: Path, mutation: str) -> None:
    document = _document()
    if mutation == "omitted":
        document["gameAliases"].pop("magic")
        document["gameAliases"]["mtg"] = "magic"
    else:
        document["gameAliases"]["magic"] = "pokemon"
        document["gameAliases"]["pokemon"] = "magic"

    with pytest.raises(TaxonomyError, match=r"canonical key .* must map to itself"):
        load_taxonomy(_write_config(tmp_path, document, f"game-canonical-{mutation}.json"))


def test_product_type_rule_shape_game_and_family_are_strict(tmp_path: Path) -> None:
    cases: list[tuple[Any, str]] = [
        ([], "must be an object"),
        ({"game": "magic"}, "invalid keys"),
        (
            {
                "id": "product-type:magic-display",
                "game": "magic",
                "productFamily": "sealed",
                "extra": True,
            },
            "invalid keys",
        ),
        (
            {"id": "product-type:magic-display", "game": 1, "productFamily": "sealed"},
            "supported game",
        ),
        (
            {
                "id": "product-type:magic-display",
                "game": "chess",
                "productFamily": "sealed",
            },
            "unsupported game",
        ),
        (
            {"id": "product-type:magic-display", "game": "magic", "productFamily": 1},
            "supported product family",
        ),
        (
            {
                "id": "product-type:magic-display",
                "game": "magic",
                "productFamily": "mystery",
            },
            "unsupported product family",
        ),
        (
            {
                "id": "product-type:magic-display",
                "game": "magic",
                "productFamily": "unclassified",
            },
            "must not target unclassified",
        ),
    ]
    for index, (rule, message) in enumerate(cases):
        document = _document()
        document["productTypes"] = {"Magic Display": rule}
        with pytest.raises(TaxonomyError, match=message):
            load_taxonomy(_write_config(tmp_path, document, f"product-rule-{index}.json"))


def test_source_record_type_targets_are_strict_and_complete(tmp_path: Path) -> None:
    for index, (target, message) in enumerate(
        (
            (1, "supported product family"),
            ("mystery", "unsupported product family"),
            ("unclassified", "must not target unclassified"),
        )
    ):
        document = _document()
        document["sourceRecordTypes"]["single"] = {
            "id": "source-record-type:single",
            "productFamily": target,
        }
        with pytest.raises(TaxonomyError, match=message):
            load_taxonomy(_write_config(tmp_path, document, f"source-target-{index}.json"))

    document = _document()
    document["sourceRecordTypes"] = {
        "single": {
            "id": "source-record-type:single",
            "productFamily": "single",
        }
    }
    with pytest.raises(TaxonomyError, match="cover every classifiable family"):
        load_taxonomy(_write_config(tmp_path, document, "source-coverage.json"))


def test_source_record_type_rule_shape_is_strict(tmp_path: Path) -> None:
    cases: list[tuple[Any, str]] = [
        ("single", "must be an object"),
        ({"productFamily": "single"}, "invalid keys"),
        (
            {
                "id": "source-record-type:single",
                "productFamily": "single",
                "extra": True,
            },
            "invalid keys",
        ),
    ]
    for index, (rule, message) in enumerate(cases):
        document = _document()
        document["sourceRecordTypes"]["single"] = rule
        with pytest.raises(TaxonomyError, match=message):
            load_taxonomy(_write_config(tmp_path, document, f"source-shape-{index}.json"))


def test_explicit_rule_ids_are_unique_and_do_not_depend_on_match_punctuation(
    tmp_path: Path,
) -> None:
    document = _document()
    document["productTypes"] = {
        "Alpha Box": {
            "id": "product-type:alpha-space",
            "game": "magic",
            "productFamily": "sealed",
        },
        "Alpha-Box": {
            "id": "product-type:alpha-hyphen",
            "game": "pokemon",
            "productFamily": "sealed",
        },
    }
    config = load_taxonomy(_write_config(tmp_path, document, "explicit-rule-ids.json"))
    classifications, report = classify_catalog(
        [
            ProductFacts(
                "gid://shopify/Product/201",
                product_type="Alpha Box",
                commercial_title="Unknown format",
            ),
            ProductFacts(
                "gid://shopify/Product/202",
                product_type="Alpha-Box",
                commercial_title="Unknown format",
            ),
        ],
        config,
    )
    assert [item.rule_id for item in classifications] == [
        "product-type:alpha-space",
        "product-type:alpha-hyphen",
    ]
    assert report.as_dict()["ruleCounts"] == {
        "product-type:alpha-hyphen": 1,
        "product-type:alpha-space": 1,
    }


@pytest.mark.parametrize("namespace", ["product", "source", "cross-namespace"])
def test_duplicate_explicit_classification_rule_ids_are_rejected(
    tmp_path: Path, namespace: str
) -> None:
    document = _document()
    duplicate_id = "classification-rule:duplicate"
    if namespace == "product":
        document["productTypes"] = {
            "Alpha Box": {
                "id": duplicate_id,
                "game": "magic",
                "productFamily": "sealed",
            },
            "Alpha-Box": {
                "id": duplicate_id,
                "game": "pokemon",
                "productFamily": "sealed",
            },
        }
    elif namespace == "source":
        document["sourceRecordTypes"]["single"]["id"] = duplicate_id
        document["sourceRecordTypes"]["sealed"]["id"] = duplicate_id
    else:
        document["productTypes"]["Magic Display"]["id"] = duplicate_id
        document["sourceRecordTypes"]["single"]["id"] = duplicate_id
    with pytest.raises(TaxonomyError, match="duplicate rule IDs"):
        load_taxonomy(_write_config(tmp_path, document, f"duplicate-{namespace}.json"))


def test_subtype_rule_collection_and_shape_are_strict(tmp_path: Path) -> None:
    document = _document()
    document["sealedSubtypeRules"] = {}
    with pytest.raises(TaxonomyError, match="must be an array"):
        load_taxonomy(_write_config(tmp_path, document, "subtypes-object.json"))

    cases: list[tuple[Any, str]] = [
        ("not-an-object", "must be an object"),
        ({"id": "rule", "productSubtype": "box"}, "invalid keys"),
        (
            {"id": "rule", "productSubtype": "box", "containsAll": ["box"], "x": 1},
            "invalid keys",
        ),
        ({"id": " ", "productSubtype": "box", "containsAll": ["box"]}, "non-empty"),
        ({"id": "Rule ID", "productSubtype": "box", "containsAll": ["box"]}, "rule identifier"),
        ({"id": "rule", "productSubtype": " ", "containsAll": ["box"]}, "non-empty"),
        ({"id": "rule", "productSubtype": "Box Type", "containsAll": ["box"]}, "subtype"),
        ({"id": "rule", "productSubtype": "box", "containsAll": "box"}, "non-empty array"),
        ({"id": "rule", "productSubtype": "box", "containsAll": []}, "non-empty array"),
        ({"id": "rule", "productSubtype": "box", "containsAll": [1]}, "must be a string"),
        ({"id": "rule", "productSubtype": "box", "containsAll": [" "]}, "empty normalized"),
        (
            {"id": "rule", "productSubtype": "box", "containsAll": ["Box", " box "]},
            "duplicate normalized",
        ),
    ]
    for index, (rule, message) in enumerate(cases):
        document = _document()
        document["sealedSubtypeRules"] = [rule]
        with pytest.raises(TaxonomyError, match=message):
            load_taxonomy(_write_config(tmp_path, document, f"subtype-rule-{index}.json"))


def test_subtype_rule_ids_and_matchers_cannot_collide(tmp_path: Path) -> None:
    document = _document()
    document["sealedSubtypeRules"][1]["id"] = document["sealedSubtypeRules"][0]["id"]
    with pytest.raises(TaxonomyError, match="duplicate normalized rule IDs"):
        load_taxonomy(_write_config(tmp_path, document, "duplicate-id.json"))

    document = _document()
    document["sealedSubtypeRules"][1]["containsAll"] = [" COLLECTOR   BOOSTER BOX - "]
    with pytest.raises(TaxonomyError, match="duplicate normalized matchers"):
        load_taxonomy(_write_config(tmp_path, document, "duplicate-matcher.json"))


def test_empty_subtype_rules_are_valid_and_audited_at_classification(tmp_path: Path) -> None:
    document = _document()
    document["sealedSubtypeRules"] = []
    config = load_taxonomy(_write_config(tmp_path, document))
    result = classify_product(
        ProductFacts(
            "gid://shopify/Product/50",
            product_type="Magic Display",
            commercial_title="Collector Booster Box - Set",
        ),
        config,
    )
    assert (result.subtype, result.subtype_reason) == (None, "no_matching_subtype_rule")
