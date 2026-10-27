"""Verified source identities and explicit, backwards-compatible capture scopes."""

# IDs verified against the retained 2026-10-23 CardTrader games export.
GAMES = {1: "magic", 4: "yugioh", 5: "pokemon", 15: "one-piece", 18: "lorcana", 22: "riftbound"}
LEGACY_GAME_IDS = frozenset((1, 4, 5, 15))
GAME_SCOPES = ("legacy", "six-games")


def game_ids_for_scope(scope: object) -> frozenset[int]:
    """Old receipts and scheduled commands remain four-game until explicit opt-in."""
    if scope == "legacy":
        return LEGACY_GAME_IDS
    if scope == "six-games":
        return frozenset(GAMES)
    raise ValueError("invalid_game_scope")
