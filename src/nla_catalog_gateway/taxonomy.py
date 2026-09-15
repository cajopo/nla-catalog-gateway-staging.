"""Deterministic, fail-closed taxonomy for the read-only catalog projection."""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any

from nla_catalog_gateway.card_metadata import CardMetadataV1

SUPPORTED_SCHEMA_VERSION = 1
PRODUCT_GID_PATTERN = re.compile(r"gid://shopify/Product/[1-9][0-9]*\Z")
PRODUCT_ID_TOKEN_PATTERN = re.compile(
    r"gid://shopify/product/|(?<![0-9])[1-9][0-9]{9,19}(?![0-9])",
    re.IGNORECASE,
)
RULE_ID_PATTERN = re.compile(r"[a-z0-9]+(?:(?:-|:)[a-z0-9]+)*\Z")
SUBTYPE_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")


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


CLASSIFIABLE_FAMILIES = frozenset(
    {ProductFamily.SINGLE, ProductFamily.SEALED, ProductFamily.ACCESSORY}
)


class TaxonomyError(ValueError):
    """Raised when configuration or product identity violates a hard invariant."""


class _DuplicateJsonKeyError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ProductFacts:
    product_gid: str
    explicit_game: str | None = None
    product_type: str = ""
    tags: tuple[str, ...] = ()
    source_record_type: str | None = None
    commercial_title: str = ""
    canonical_card_name: str | None = None
    card_metadata: CardMetadataV1 | None = None


@dataclass(frozen=True, slots=True)
class ProductTypeRule:
    rule_id: str
    game: Game
    family: ProductFamily


@dataclass(frozen=True, slots=True)
class SourceRecordTypeRule:
    rule_id: str
    family: ProductFamily


@dataclass(frozen=True, slots=True)
class SubtypeRule:
    rule_id: str
    subtype: str
    contains_all: tuple[str, ...]

    @property
    def specificity(self) -> tuple[int, int]:
        return sum(map(len, self.contains_all)), len(self.contains_all)


@dataclass(frozen=True, slots=True, init=False)
class TaxonomyConfig:
    schema_version: int
    rule_version: str
    game_aliases: Mapping[str, Game]
    product_types: Mapping[str, ProductTypeRule]
    source_record_types: Mapping[str, SourceRecordTypeRule]
    sealed_subtypes: tuple[SubtypeRule, ...]
    _validated: bool

    def __new__(cls, *args: Any, **kwargs: Any) -> TaxonomyConfig:
        raise TypeError("TaxonomyConfig must be created by load_taxonomy")


@dataclass(frozen=True, slots=True)
class Classification:
    product_gid: str
    game: Game | None
    family: ProductFamily
    subtype: str | None
    rule_version: str
    rule_id: str | None
    reason: str | None
    subtype_rule_id: str | None = None
    subtype_reason: str | None = None

    @property
    def classified(self) -> bool:
        return self.family is not ProductFamily.UNCLASSIFIED

    def as_dict(self) -> dict[str, Any]:
        return {
            "productGid": self.product_gid,
            "game": self.game.value if self.game else None,
            "productFamily": self.family.value,
            "productSubtype": self.subtype,
            "classificationRuleVersion": self.rule_version,
            "classificationRuleId": self.rule_id,
            "unclassifiedReason": self.reason,
            "subtypeRuleId": self.subtype_rule_id,
            "subtypeReason": self.subtype_reason,
        }


@dataclass(frozen=True, slots=True)
class ClassificationReport:
    rule_version: str
    total: int
    classified: int
    unclassified: int
    counts: Mapping[str, int]
    rule_counts: Mapping[str, int]
    unclassified_reasons: Mapping[str, int]
    subtype_reasons: Mapping[str, int]

    def as_dict(self) -> dict[str, Any]:
        return {
            "classificationRuleVersion": self.rule_version,
            "total": self.total,
            "classified": self.classified,
            "unclassified": self.unclassified,
            "counts": dict(sorted(self.counts.items())),
            "ruleCounts": dict(sorted(self.rule_counts.items())),
            "unclassifiedReasons": dict(sorted(self.unclassified_reasons.items())),
            "subtypeReasons": dict(sorted(self.subtype_reasons.items())),
        }


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKeyError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _require_object(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TaxonomyError(f"{context} must be an object")
    return value


def _require_exact_keys(value: Mapping[str, Any], expected: set[str], context: str) -> None:
    actual = set(value)
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    if missing or unexpected:
        raise TaxonomyError(
            f"{context} has invalid keys; missing={missing}, unexpected={unexpected}"
        )


def _require_nonempty_string(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TaxonomyError(f"{context} must be a non-empty string")
    return value.strip()


def _reject_product_identity_tokens(value: Any, context: str = "taxonomy") -> None:
    if isinstance(value, str):
        if PRODUCT_ID_TOKEN_PATTERN.search(value):
            raise TaxonomyError(f"{context} must not contain Shopify product identity")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _reject_product_identity_tokens(key, f"{context} key")
            _reject_product_identity_tokens(item, f"{context}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _reject_product_identity_tokens(item, f"{context}[{index}]")


def _normalized_entries(value: Any, context: str) -> tuple[tuple[str, Any], ...]:
    document = _require_object(value, context)
    entries: list[tuple[str, Any]] = []
    original_by_normalized: dict[str, str] = {}
    for raw_key, item in document.items():
        normalized = _normalize(raw_key)
        if not normalized:
            raise TaxonomyError(f"{context} contains an empty normalized key")
        if normalized in original_by_normalized:
            first = original_by_normalized[normalized]
            raise TaxonomyError(
                f"{context} contains normalized key collision: {first!r} and {raw_key!r}"
            )
        original_by_normalized[normalized] = raw_key
        entries.append((normalized, item))
    return tuple(entries)


def _parse_game(value: Any, context: str) -> Game:
    if not isinstance(value, str):
        raise TaxonomyError(f"{context} must be a supported game string")
    try:
        return Game(value)
    except ValueError as exc:
        raise TaxonomyError(f"{context} has unsupported game {value!r}") from exc


def _parse_classifiable_family(value: Any, context: str) -> ProductFamily:
    if not isinstance(value, str):
        raise TaxonomyError(f"{context} must be a supported product family string")
    try:
        family = ProductFamily(value)
    except ValueError as exc:
        raise TaxonomyError(f"{context} has unsupported product family {value!r}") from exc
    if family not in CLASSIFIABLE_FAMILIES:
        raise TaxonomyError(f"{context} must not target unclassified")
    return family


def _parse_rule_id(value: Any, context: str) -> str:
    rule_id = _require_nonempty_string(value, context)
    if not RULE_ID_PATTERN.fullmatch(rule_id):
        raise TaxonomyError(f"{context} must be a normalized rule identifier")
    return rule_id


def _parse_game_aliases(value: Any) -> dict[str, Game]:
    aliases = {
        alias: _parse_game(game, f"gameAliases.{alias}")
        for alias, game in _normalized_entries(value, "gameAliases")
    }
    if set(aliases.values()) != set(Game):
        raise TaxonomyError("gameAliases must cover every supported game")
    for game in Game:
        canonical_key = _normalize(game.value)
        if aliases.get(canonical_key) is not game:
            raise TaxonomyError(f"gameAliases canonical key {game.value!r} must map to itself")
    return aliases


def _parse_product_types(value: Any) -> dict[str, ProductTypeRule]:
    rules: dict[str, ProductTypeRule] = {}
    for product_type, raw_rule in _normalized_entries(value, "productTypes"):
        rule = _require_object(raw_rule, f"productTypes.{product_type}")
        _require_exact_keys(
            rule,
            {"id", "game", "productFamily"},
            f"productTypes.{product_type}",
        )
        rules[product_type] = ProductTypeRule(
            rule_id=_parse_rule_id(rule["id"], f"productTypes.{product_type}.id"),
            game=_parse_game(rule["game"], f"productTypes.{product_type}.game"),
            family=_parse_classifiable_family(
                rule["productFamily"], f"productTypes.{product_type}.productFamily"
            ),
        )
    return rules


def _parse_source_record_types(value: Any) -> dict[str, SourceRecordTypeRule]:
    source_types: dict[str, SourceRecordTypeRule] = {}
    for source_type, raw_rule in _normalized_entries(value, "sourceRecordTypes"):
        context = f"sourceRecordTypes.{source_type}"
        rule = _require_object(raw_rule, context)
        _require_exact_keys(rule, {"id", "productFamily"}, context)
        source_types[source_type] = SourceRecordTypeRule(
            rule_id=_parse_rule_id(rule["id"], f"{context}.id"),
            family=_parse_classifiable_family(rule["productFamily"], f"{context}.productFamily"),
        )
    if {rule.family for rule in source_types.values()} != CLASSIFIABLE_FAMILIES:
        raise TaxonomyError("sourceRecordTypes must cover every classifiable family")
    return source_types


def _parse_subtype_rule(raw_rule: Any, index: int) -> SubtypeRule:
    context = f"sealedSubtypeRules[{index}]"
    rule = _require_object(raw_rule, context)
    _require_exact_keys(rule, {"id", "productSubtype", "containsAll"}, context)
    rule_id = _parse_rule_id(rule["id"], f"{context}.id")
    subtype = _require_nonempty_string(rule["productSubtype"], f"{context}.productSubtype")
    if not SUBTYPE_PATTERN.fullmatch(subtype):
        raise TaxonomyError(f"{context}.productSubtype must be a normalized subtype")
    raw_fragments = rule["containsAll"]
    if not isinstance(raw_fragments, list) or not raw_fragments:
        raise TaxonomyError(f"{context}.containsAll must be a non-empty array")
    fragments: list[str] = []
    seen_fragments: set[str] = set()
    for fragment_index, raw_fragment in enumerate(raw_fragments):
        if not isinstance(raw_fragment, str):
            raise TaxonomyError(f"{context}.containsAll[{fragment_index}] must be a string")
        fragment = _normalize(raw_fragment)
        if not fragment:
            raise TaxonomyError(f"{context}.containsAll contains an empty normalized fragment")
        if fragment in seen_fragments:
            raise TaxonomyError(f"{context}.containsAll contains duplicate normalized fragments")
        seen_fragments.add(fragment)
        fragments.append(fragment)
    return SubtypeRule(
        rule_id=rule_id,
        subtype=subtype,
        contains_all=tuple(sorted(fragments)),
    )


def _parse_subtype_rules(value: Any) -> tuple[SubtypeRule, ...]:
    if not isinstance(value, list):
        raise TaxonomyError("sealedSubtypeRules must be an array")
    rules = tuple(_parse_subtype_rule(raw_rule, index) for index, raw_rule in enumerate(value))
    ids: set[str] = set()
    matchers: set[tuple[str, ...]] = set()
    for rule in rules:
        normalized_id = _normalize(rule.rule_id)
        if normalized_id in ids:
            raise TaxonomyError("sealedSubtypeRules contains duplicate normalized rule IDs")
        if rule.contains_all in matchers:
            raise TaxonomyError("sealedSubtypeRules contains duplicate normalized matchers")
        ids.add(normalized_id)
        matchers.add(rule.contains_all)
    return rules


def _build_taxonomy_config(
    *,
    schema_version: int,
    rule_version: str,
    game_aliases: dict[str, Game],
    product_types: dict[str, ProductTypeRule],
    source_record_types: dict[str, SourceRecordTypeRule],
    sealed_subtypes: tuple[SubtypeRule, ...],
) -> TaxonomyConfig:
    config = object.__new__(TaxonomyConfig)
    object.__setattr__(config, "schema_version", schema_version)
    object.__setattr__(config, "rule_version", rule_version)
    object.__setattr__(config, "game_aliases", MappingProxyType(dict(game_aliases)))
    object.__setattr__(config, "product_types", MappingProxyType(dict(product_types)))
    object.__setattr__(
        config,
        "source_record_types",
        MappingProxyType(dict(source_record_types)),
    )
    object.__setattr__(config, "sealed_subtypes", tuple(sealed_subtypes))
    object.__setattr__(config, "_validated", True)
    return config


def default_config_path() -> Path:
    return Path(__file__).with_name("catalog_taxonomy.v1.json")


def load_taxonomy(path: Path | None = None) -> TaxonomyConfig:
    config_path = path or default_config_path()
    try:
        raw_text = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise TaxonomyError(f"cannot read taxonomy config {config_path}: {exc}") from exc
    try:
        raw_document = json.loads(raw_text, object_pairs_hook=_reject_duplicate_json_keys)
    except (json.JSONDecodeError, _DuplicateJsonKeyError) as exc:
        raise TaxonomyError(f"invalid taxonomy JSON {config_path}: {exc}") from exc

    document = _require_object(raw_document, "taxonomy")
    _require_exact_keys(
        document,
        {
            "schemaVersion",
            "classificationRuleVersion",
            "gameAliases",
            "productTypes",
            "sourceRecordTypes",
            "sealedSubtypeRules",
        },
        "taxonomy",
    )
    schema_version = document["schemaVersion"]
    if type(schema_version) is not int or schema_version != SUPPORTED_SCHEMA_VERSION:
        raise TaxonomyError(f"taxonomy schemaVersion must equal integer {SUPPORTED_SCHEMA_VERSION}")
    rule_version = _require_nonempty_string(
        document["classificationRuleVersion"], "classificationRuleVersion"
    )
    _reject_product_identity_tokens(document)
    game_aliases = _parse_game_aliases(document["gameAliases"])
    product_types = _parse_product_types(document["productTypes"])
    source_record_types = _parse_source_record_types(document["sourceRecordTypes"])
    sealed_subtypes = _parse_subtype_rules(document["sealedSubtypeRules"])
    all_rule_ids = [rule.rule_id for rule in product_types.values()]
    all_rule_ids.extend(rule.rule_id for rule in source_record_types.values())
    all_rule_ids.extend(rule.rule_id for rule in sealed_subtypes)
    if len(all_rule_ids) != len(set(all_rule_ids)):
        raise TaxonomyError("taxonomy rules contain duplicate rule IDs")
    return _build_taxonomy_config(
        schema_version=schema_version,
        rule_version=rule_version,
        game_aliases=game_aliases,
        product_types=product_types,
        source_record_types=source_record_types,
        sealed_subtypes=sealed_subtypes,
    )


def _validate_facts(facts: ProductFacts) -> None:
    if not isinstance(facts, ProductFacts):
        raise TaxonomyError("taxonomy input must contain ProductFacts")
    if not isinstance(facts.product_gid, str) or not PRODUCT_GID_PATTERN.fullmatch(
        facts.product_gid
    ):
        raise TaxonomyError("product_gid must be a canonical Shopify Product GID")
    optional_strings = {
        "explicit_game": facts.explicit_game,
        "source_record_type": facts.source_record_type,
        "canonical_card_name": facts.canonical_card_name,
    }
    for field_name, value in optional_strings.items():
        if value is not None and not isinstance(value, str):
            raise TaxonomyError(f"{field_name} must be a string or null")
    required_strings = {
        "product_type": facts.product_type,
        "commercial_title": facts.commercial_title,
    }
    for field_name, value in required_strings.items():
        if not isinstance(value, str):
            raise TaxonomyError(f"{field_name} must be a string")
    if not isinstance(facts.tags, tuple) or any(not isinstance(tag, str) for tag in facts.tags):
        raise TaxonomyError("tags must be a tuple of strings")


def _validate_config(config: TaxonomyConfig) -> None:
    if not isinstance(config, TaxonomyConfig) or getattr(config, "_validated", False) is not True:
        raise TaxonomyError("config must be a TaxonomyConfig")


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
        rule_version=config.rule_version,
        rule_id=None,
        reason=reason,
    )


def _resolve_game(
    facts: ProductFacts,
    config: TaxonomyConfig,
    product_type_rule: ProductTypeRule | None,
) -> tuple[Game | None, str | None]:
    games: set[Game] = set()
    if facts.explicit_game and facts.explicit_game.strip():
        explicit_game = config.game_aliases.get(_normalize(facts.explicit_game))
        if explicit_game is None:
            return None, "unknown_explicit_game"
        games.add(explicit_game)
    for tag in facts.tags:
        tag_game = config.game_aliases.get(_normalize(tag))
        if tag_game is not None:
            games.add(tag_game)
    if product_type_rule is not None:
        games.add(product_type_rule.game)
    if len(games) > 1:
        return None, "conflicting_game_signals"
    if not games:
        return None, "missing_game_signal"
    return next(iter(games)), None


def _resolve_subtype(
    title: str, config: TaxonomyConfig
) -> tuple[str | None, str | None, str | None]:
    normalized_title = _normalize(title)
    matches = [
        rule
        for rule in config.sealed_subtypes
        if all(fragment in normalized_title for fragment in rule.contains_all)
    ]
    if not matches:
        return None, None, "no_matching_subtype_rule"
    best_specificity = max(rule.specificity for rule in matches)
    best = [rule for rule in matches if rule.specificity == best_specificity]
    if len({rule.subtype for rule in best}) > 1:
        return None, None, "ambiguous_subtype_match"
    selected = min(best, key=lambda rule: rule.rule_id)
    return selected.subtype, selected.rule_id, None


def product_type_rule(product_type: str, config: TaxonomyConfig) -> ProductTypeRule | None:
    """Return the configured structured rule for one Shopify product type."""

    _validate_config(config)
    if type(product_type) is not str:
        raise TaxonomyError("product_type must be a string")
    return config.product_types.get(_normalize(product_type))


def classify_product(facts: ProductFacts, config: TaxonomyConfig) -> Classification:
    _validate_config(config)
    _validate_facts(facts)
    product_type_key = _normalize(facts.product_type)
    product_type_rule = config.product_types.get(product_type_key)
    source_rule = None
    source_type_key = ""
    if facts.source_record_type and facts.source_record_type.strip():
        source_type_key = _normalize(facts.source_record_type)
        source_rule = config.source_record_types.get(source_type_key)
    if product_type_key and product_type_rule is None:
        game, _ = _resolve_game(facts, config, None)
        return _unclassified(facts, config, game=game, reason="unknown_product_type")
    if source_type_key and source_rule is None:
        game, _ = _resolve_game(facts, config, product_type_rule)
        return _unclassified(facts, config, game=game, reason="unknown_source_record_type")

    game, game_error = _resolve_game(facts, config, product_type_rule)
    if game_error:
        return _unclassified(facts, config, game=game, reason=game_error)
    if product_type_rule and source_rule and product_type_rule.family is not source_rule.family:
        return _unclassified(facts, config, game=game, reason="conflicting_family_signals")

    family = (
        product_type_rule.family
        if product_type_rule
        else source_rule.family
        if source_rule
        else None
    )
    if family is None:
        return _unclassified(facts, config, game=game, reason="missing_family_signal")
    if family is ProductFamily.SINGLE and not (facts.canonical_card_name or "").strip():
        return _unclassified(facts, config, game=game, reason="missing_canonical_card_name")
    if family in {ProductFamily.SEALED, ProductFamily.ACCESSORY} and not (
        facts.commercial_title.strip()
    ):
        return _unclassified(facts, config, game=game, reason="missing_commercial_title")

    subtype = None
    subtype_rule_id = None
    subtype_reason = None
    if family is ProductFamily.SEALED:
        subtype, subtype_rule_id, subtype_reason = _resolve_subtype(facts.commercial_title, config)
    rule_id = product_type_rule.rule_id if product_type_rule else source_rule.rule_id
    return Classification(
        product_gid=facts.product_gid,
        game=game,
        family=family,
        subtype=subtype,
        rule_version=config.rule_version,
        rule_id=rule_id,
        reason=None,
        subtype_rule_id=subtype_rule_id,
        subtype_reason=subtype_reason,
    )


def classify_catalog(
    products: Iterable[ProductFacts], config: TaxonomyConfig
) -> tuple[tuple[Classification, ...], ClassificationReport]:
    _validate_config(config)
    if isinstance(products, (str, bytes)):
        raise TaxonomyError("taxonomy catalog input must be an iterable of ProductFacts")
    try:
        product_list = tuple(products)
    except TypeError as exc:
        raise TaxonomyError("taxonomy catalog input must be iterable") from exc
    seen_gids: set[str] = set()
    for facts in product_list:
        _validate_facts(facts)
        if facts.product_gid in seen_gids:
            raise TaxonomyError(f"duplicate product_gid: {facts.product_gid}")
        seen_gids.add(facts.product_gid)

    classifications = tuple(classify_product(facts, config) for facts in product_list)
    classified = sum(item.classified for item in classifications)
    unclassified = len(classifications) - classified
    counts = Counter(
        f"{item.game.value if item.game else 'unknown'}/{item.family.value}"
        for item in classifications
    )
    rule_counts = Counter(item.rule_id for item in classifications if item.rule_id is not None)
    unclassified_reasons = Counter(
        item.reason for item in classifications if item.reason is not None
    )
    subtype_reasons = Counter(
        item.subtype_reason for item in classifications if item.subtype_reason is not None
    )
    report = ClassificationReport(
        rule_version=config.rule_version,
        total=len(classifications),
        classified=classified,
        unclassified=unclassified,
        counts=MappingProxyType(dict(counts)),
        rule_counts=MappingProxyType(dict(rule_counts)),
        unclassified_reasons=MappingProxyType(dict(unclassified_reasons)),
        subtype_reasons=MappingProxyType(dict(subtype_reasons)),
    )
    return classifications, report
