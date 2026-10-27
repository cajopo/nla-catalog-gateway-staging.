"""Read-only identity comparison, never an approval to create Shopify products."""

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping

from nla_catalog_gateway.cardtrader_scope import GAMES


def _id(value: object) -> bool:
    return type(value) is int and 0 < value < 2**63


def compare_catalog(
    blueprints: list[dict],
    products: Iterable[dict],
    categories: Mapping[int, tuple[int, str]],
    expansions: Mapping[int, int],
) -> list[dict]:
    """Account for every input row against a supplied, possibly stale snapshot.

    Categories must be explicitly mapped from observed CardTrader definitions to
    (game_id, family). Unknown categories are reported, never inferred from names.
    Caller must supply all source rows in scope to detect cross-expansion clashes.
    Even an absent identity needs a fresh Shopify check before any future write.
    """
    if any(
        not _id(category)
        or type(game) is not int
        or game not in GAMES
        or family not in ("single", "sealed", "accessory", "unclassified")
        for category, (game, family) in categories.items()
    ):
        raise ValueError("invalid_category_mapping")
    if any(not _id(key) or not _id(game) or game not in GAMES for key, game in expansions.items()):
        raise ValueError("invalid_expansion_mapping")
    existing = defaultdict(dict)
    by_gid = {}
    for product in products:
        gid = product.get("productGid")
        game = product.get("game")
        if not isinstance(gid, str) or not gid.startswith("gid://shopify/Product/"):
            raise ValueError("invalid_product_identity")
        if game not in GAMES.values():
            raise ValueError("invalid_product_game")
        if gid in by_gid and by_gid[gid] != product:
            raise ValueError("conflicting_product_rows")
        by_gid[gid] = product
        for key in ("syncSourceId", "powerToolsSourceId"):
            if key not in product:
                raise ValueError("missing_identity_field")
            source = product[key]
            if source is not None:
                if not isinstance(source, str) or not source:
                    raise ValueError("invalid_source_identity")
                existing[source][gid] = product

    blueprint_counts = Counter(row.get("id") for row in blueprints if _id(row.get("id")))
    source_counts = Counter()
    for row in blueprints:
        identifiers = row.get("card_market_ids")
        if isinstance(identifiers, list):
            source_counts.update(set(i for i in identifiers if _id(i)))

    report = []
    for index, row in enumerate(blueprints):
        blueprint_id, game_id = row.get("id"), row.get("game_id")
        category_id, expansion_id = row.get("category_id"), row.get("expansion_id")
        raw_ids = row.get("card_market_ids")
        ids_valid = isinstance(raw_ids, list) and all(_id(i) for i in raw_ids)
        ids = sorted(set(raw_ids)) if ids_valid else []
        matches = {gid: p for i in ids for gid, p in existing.get(str(i), {}).items()}
        game = GAMES.get(game_id) if _id(game_id) else None
        category = categories.get(category_id) if _id(category_id) else None
        if not all(_id(i) for i in (blueprint_id, game_id, category_id, expansion_id)):
            decision = "invalid_blueprint_identity"
        elif game is None:
            decision = "out_of_scope_game"
        elif blueprint_counts[blueprint_id] > 1:
            decision = "duplicate_blueprint_id"
        elif category is None or category[1] == "unclassified":
            decision = "unclassified_category"
        elif category[0] != game_id:
            decision = "category_game_conflict"
        elif expansion_id not in expansions:
            decision = "unclassified_expansion"
        elif expansions[expansion_id] != game_id:
            decision = "expansion_game_conflict"
        elif category[1] != "single":
            decision = "non_card_category"
        elif not ids_valid:
            decision = "invalid_cardmarket_ids"
        elif not ids:
            decision = "missing_cardmarket_id"
        elif len(ids) != 1:
            decision = "multiple_cardmarket_ids"
        elif source_counts[ids[0]] > 1:
            decision = "shared_cardmarket_id"
        elif len(matches) > 1:
            decision = "multiple_shopify_products"
        elif matches and any(
            p["game"] != game
            or p.get("productFamily") != "single"
            or p["syncSourceId"] != str(ids[0])
            or p["powerToolsSourceId"] != str(ids[0])
            for p in matches.values()
        ):
            decision = "shopify_identity_conflict"
        elif matches:
            decision = "existing_identity_match"
        else:
            decision = "absent_from_supplied_snapshot"
        report.append(
            {
                "rowIndex": index,
                "blueprintId": blueprint_id if _id(blueprint_id) else None,
                "game": game,
                "cardmarketIds": ids,
                "shopifyProductGids": sorted(matches),
                "decision": decision,
                "creationApproved": False,
            }
        )
    return report
