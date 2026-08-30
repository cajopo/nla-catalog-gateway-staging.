from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable

WHITESPACE_RE = re.compile(r"\s+")
BRACKET_RE = re.compile(r"\s*\[([^\]]+)\]\s*$")
RARITY_RE = re.compile(r"\s+\(([^()]*)\)\s*$")

CONTROLLED_TAGS = {
    "magic", "magic single", "pokémon", "pokemon", "pokémon single", "pokemon single",
    "yu-gi-oh!", "yu-gi-oh! single", "yugioh single", "one piece", "one piece single",
    "nla_catalog_only", "normal", "foil", "etched", "reverse holo", "reverse", "holo",
    "non-foil", "near mint", "lightly played", "moderately played", "heavily played",
    "poor", "damaged", "mint", "english", "italian", "french", "german", "spanish",
    "portuguese", "japanese", "korean", "chinese", "russian", "common", "uncommon",
    "rare", "mythic", "mythic rare", "promo", "token", "tip card", "land",
}

GAME_BY_PRODUCT_TYPE = {
    "magic single": "magic",
    "pokémon single": "pokemon",
    "pokemon single": "pokemon",
    "yu-gi-oh! single": "yugioh",
    "yugioh single": "yugioh",
    "one piece single": "one-piece",
}

GAME_LABELS = {
    "magic": "Magic: The Gathering",
    "pokemon": "Pokémon",
    "yugioh": "Yu-Gi-Oh!",
    "one-piece": "One Piece",
}


@dataclass(frozen=True, slots=True)
class ParsedTitle:
    canonical_name: str
    set_name: str | None
    rarity: str | None
    set_code: str | None
    collector_number: str | None


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "")
    value = value.replace("’", "'").replace("`", "'").replace("–", "-").replace("—", "-")
    value = value.casefold().strip()
    return WHITESPACE_RE.sub(" ", value)


def infer_game(product_type: str, tags: Iterable[str] = ()) -> str | None:
    game = GAME_BY_PRODUCT_TYPE.get(normalize_text(product_type))
    if game:
        return game
    normalized_tags = {normalize_text(tag) for tag in tags}
    if "magic" in normalized_tags:
        return "magic"
    if "pokémon" in normalized_tags or "pokemon" in normalized_tags:
        return "pokemon"
    if "yu-gi-oh!" in normalized_tags:
        return "yugioh"
    if "one piece" in normalized_tags:
        return "one-piece"
    return None


def _parse_bracket(value: str) -> tuple[str | None, str | None]:
    token = value.strip()
    if not token:
        return None, None
    if "-" not in token:
        return token, None
    set_code, collector = token.rsplit("-", 1)
    return set_code.strip() or None, collector.strip() or None


def parse_product_title(title: str, tags: Iterable[str] = ()) -> ParsedTitle:
    working = WHITESPACE_RE.sub(" ", (title or "").strip())
    bracket_value: str | None = None
    bracket_match = BRACKET_RE.search(working)
    if bracket_match:
        bracket_value = bracket_match.group(1).strip()
        working = working[: bracket_match.start()].rstrip()

    rarity: str | None = None
    rarity_match = RARITY_RE.search(working)
    if rarity_match:
        rarity = rarity_match.group(1).strip() or None
        working = working[: rarity_match.start()].rstrip()

    set_name: str | None = None
    canonical_name = working
    candidate_tags = []
    for tag in tags:
        clean = WHITESPACE_RE.sub(" ", (tag or "").strip())
        if clean and normalize_text(clean) not in CONTROLLED_TAGS:
            candidate_tags.append(clean)

    for candidate in sorted(candidate_tags, key=len, reverse=True):
        suffix = f" - {candidate}"
        if working.casefold().endswith(suffix.casefold()):
            set_name = candidate
            canonical_name = working[: -len(suffix)].rstrip()
            break

    if set_name is None and " - " in working:
        canonical_name, set_name = [part.strip() for part in working.rsplit(" - ", 1)]

    set_code, collector_number = _parse_bracket(bracket_value or "")
    return ParsedTitle(
        canonical_name=canonical_name or title.strip(),
        set_name=set_name or None,
        rarity=rarity,
        set_code=set_code,
        collector_number=collector_number,
    )
