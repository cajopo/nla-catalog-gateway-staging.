"""Fail-closed product taxonomy for the NLA catalog projection."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any


class Game(StrEnum):
    MAGIC = "magic"
    POKEMON = "pokemon"
    YUGIOH = "yugioh"
    ONE_PIECE = "one-piece"


class ProductFamily(StrEnum):
    SINGLE = "single"
    SEALED = "sealed"
    ACCESSORY = "accessory"
    UNCLASSIFIED = "unclassified"


class TaxonomyError(ValueError):
    """Raised when taxonomy configuration or input violates a hard invariant."""


@dataclass(frozen=True, slots=True)
class ProductFacts:
    product_gid: str
    explicit_game: str | None = None
    product_type: str = ""
    tags: tuple[str, ...] = ()
    source_record_type: str | None = None
    commercial_title: str = ""
    canonical_card_name: str | None = None


@dataclass(frozen=True, slots=True)
class ProductTypeRule:
    game: Game
    family: ProductFamily


@dataclass(frozen=True, slots=True)
class SubtypeRule:
    subtype: str
    contains: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TaxonomyConfig:
    version: str
    game_aliases: dict[str, Game]
    product_types: dict[str, ProductTypeRule]
    source_record_types: dict[str, ProductFamily]
    sealed_subtypes: tuple[SubtypeRule, ...]


@dataclass(frozen=True, slots=True)
class Classification:
    product_gid: str
    game: Game | None
    family: ProductFamily
    subtype: str | None
    rule_version: str
    rule_id: str | None
    reason: str | None

    @property
    def classified(self) -> bool:
        return self.family is not ProductFamily.UNCLASSIFIED


@dataclass(frozen=True, slots=True)
class ClassificationReport:
    total: int
    classified: int
    unclassified: int
    counts: dict[str, int]
    unclassified_reasons: dict[str, int]

    def as_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "classified": self.classified,
            "unclassified": self.unclassified,
            "counts": dict(sorted(self.counts.items())),
            "unclassifiedReasons": dict(sorted(self.unclassified_reasons.items())),
        }


def _key(value: str) -> str:
    return " ".join(value.casefold().split())


def default_config_path() -> Path:
    return Path(__file__).with_name("catalog_taxonomy.v1.json")


def load_taxonomy(path: Path | None = None) -> TaxonomyConfig:
    config_path = path or default_config_path()
    try:
        document = json.loads(config_path.read_text(encoding="utf-8"))
        version = str(document["version"]).strip()
        if not version:
            raise TaxonomyError("taxonomy version must not be empty")
        game_aliases = {
            _key(alias): Game(game) for alias, game in document["gameAliases"].items()
        }
        product_types = {
            _key(product_type): ProductTypeRule(
                game=Game(rule["game"]),
                family=ProductFamily(rule["family"]),
            )
            for product_type, rule in document["productTypes"].items()
        }
        source_record_types = {
            _key(source_type): ProductFamily(family)
            for source_type, family in document["sourceRecordTypes"].items()
        }
        sealed_subtypes = tuple(
            SubtypeRule(
                subtype=str(rule["subtype"]),
                contains=tuple(_key(item) for item in rule["contains"]),
            )
            for rule in document["sealedSubtypes"]
        )
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, TaxonomyError):
            raise
        raise TaxonomyError(f"invalid taxonomy config {config_path}: {exc}") from exc
    if not game_aliases or not source_record_types:
        raise TaxonomyError("taxonomy requires game aliases and source record types")
    if any(not rule.contains or not rule.subtype for rule in sealed_subtypes):
        raise TaxonomyError("sealed subtype rules require subtype and contains values")
    return TaxonomyConfig(
        version=version,
        game_aliases=game_aliases,
        product_types=product_types,
        source_record_types=source_record_types,
        sealed_subtypes=sealed_subtypes,
    )


def _unclassified(
    facts: ProductFacts,
    config: TaxonomyConfig,
    *,
    game: Game | None,
    reason: str,
) -> Classification:
    return Classification(
        product_gid=facts.product_gid,
        game=game,
        family=ProductFamily.UNCLASSIFIED,
        subtype=None,
        rule_version=config.version,
        rule_id=None,
        reason=reason,
    )


def _resolve_game(
    facts: ProductFacts,
    config: TaxonomyConfig,
    product_type_rule: ProductTypeRule | None,
) -> tuple[Game | None, str | None]:
    games: set[Game] = set()
    unknown_explicit = False
    if facts.explicit_game and facts.explicit_game.strip():
        game = config.game_aliases.get(_key(facts.explicit_game))
        if game is None:
            unknown_explicit = True
        else:
            games.add(game)
    games.update(
        config.game_aliases[_key(tag)]
        for tag in facts.tags
        if _key(tag) in config.game_aliases
    )
    if product_type_rule is not None:
        games.add(product_type_rule.game)
    if unknown_explicit:
        return None, "unknown_explicit_game"
    if len(games) > 1:
        return None, "conflicting_game_signals"
    if not games:
        return None, "missing_game_signal"
    return games.pop(), None


def _sealed_subtype(title: str, config: TaxonomyConfig) -> str | None:
    normalized_title = _key(title)
    for rule in config.sealed_subtypes:
        if all(fragment in normalized_title for fragment in rule.contains):
            return rule.subtype
    return None


def classify_product(facts: ProductFacts, config: TaxonomyConfig) -> Classification:
    if not facts.product_gid.strip():
        raise TaxonomyError("product_gid must not be empty")

    product_type_key = _key(facts.product_type)
    product_type_rule = config.product_types.get(product_type_key)
    game, game_error = _resolve_game(facts, config, product_type_rule)
    if game_error:
        return _unclassified(facts, config, game=game, reason=game_error)

    source_family = None
    if facts.source_record_type and facts.source_record_type.strip():
        source_family = config.source_record_types.get(_key(facts.source_record_type))
        if source_family is None:
            return _unclassified(
                facts,
                config,
                game=game,
                reason="unknown_source_record_type",
            )

    if product_type_key and product_type_rule is None:
        return _unclassified(facts, config, game=game, reason="unknown_product_type")
    if product_type_rule and source_family and product_type_rule.family is not source_family:
        return _unclassified(facts, config, game=game, reason="conflicting_family_signals")

    family = product_type_rule.family if product_type_rule else source_family
    if family is None:
        return _unclassified(facts, config, game=game, reason="missing_family_signal")
    if family is ProductFamily.SINGLE and not (facts.canonical_card_name or "").strip():
        return _unclassified(
            facts,
            config,
            game=game,
            reason="missing_canonical_card_name",
        )
    if (
        family in {ProductFamily.SEALED, ProductFamily.ACCESSORY}
        and not facts.commercial_title.strip()
    ):
        return _unclassified(facts, config, game=game, reason="missing_commercial_title")

    subtype = (
        _sealed_subtype(facts.commercial_title, config)
        if family is ProductFamily.SEALED
        else None
    )
    rule_id = (
        f"product-type:{product_type_key}"
        if product_type_rule
        else f"source-record-type:{_key(facts.source_record_type or '')}"
    )
    return Classification(
        product_gid=facts.product_gid,
        game=game,
        family=family,
        subtype=subtype,
        rule_version=config.version,
        rule_id=rule_id,
        reason=None,
    )


def classify_catalog(
    products: list[ProductFacts],
    config: TaxonomyConfig,
) -> tuple[tuple[Classification, ...], ClassificationReport]:
    product_ids = [product.product_gid for product in products]
    if len(product_ids) != len(set(product_ids)):
        raise TaxonomyError("duplicate product_gid in taxonomy input")
    classifications = tuple(classify_product(product, config) for product in products)
    classified = sum(item.classified for item in classifications)
    unclassified = len(classifications) - classified
    counts = Counter(
        f"{item.game.value if item.game else 'unknown'}/{item.family.value}"
        for item in classifications
    )
    reasons = Counter(
        item.reason or "unspecified" for item in classifications if not item.classified
    )
    report = ClassificationReport(
        total=len(classifications),
        classified=classified,
        unclassified=unclassified,
        counts=dict(counts),
        unclassified_reasons=dict(reasons),
    )
    return classifications, report
