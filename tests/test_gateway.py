from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from pathlib import Path
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from app.app_proxy import AppProxyError, canonicalize_query_string, verify_app_proxy
from app.config import Settings
from app.cursor import CursorCodec, CursorError
from app.main import create_app
from app.normalization import infer_game, normalize_text, parse_product_title
from app.sync.build_index import build_catalog


def product(gid: int, title: str, handle: str, product_type: str, tags: list[str], power_id: int, inventory: int = 0) -> dict:
    return {
        "id": f"gid://shopify/Product/{gid}", "legacyResourceId": str(gid), "handle": handle,
        "title": title, "status": "ACTIVE", "productType": product_type,
        "vendor": "NEXT LEVEL ARENA", "tags": tags, "totalInventory": inventory,
        "tracksInventory": True, "onlineStoreUrl": None, "updatedAt": "2026-08-30T00:00:00Z",
        "syncProductId": {"value": str(power_id)}, "powertoolsId": {"value": str(power_id)},
        "featuredMedia": {"mediaContentType": "IMAGE", "preview": {"image": {"url": f"https://cdn.example/{gid}.jpg"}}},
    }


def variant(gid: int, parent: int, price: str = "0.00", inventory: int = 0, available: bool = False) -> dict:
    return {
        "id": f"gid://shopify/ProductVariant/{gid}", "__parentId": f"gid://shopify/Product/{parent}",
        "legacyResourceId": str(gid), "title": "English / Near Mint / Normal", "sku": f"TEST-{gid}",
        "price": price, "availableForSale": available, "inventoryQuantity": inventory,
        "selectedOptions": [
            {"name": "Language", "value": "English"},
            {"name": "Condition", "value": "Near Mint"},
            {"name": "Edition", "value": "Normal"},
        ],
    }


@pytest.fixture()
def database(tmp_path: Path) -> Path:
    snapshot = tmp_path / "snapshot.jsonl"
    db = tmp_path / "catalog.sqlite3"
    records = [
        product(1, "Lightning Bolt - Magic 2010 (Common) [M10-146]", "lightning-bolt-m10", "Magic Single", ["Magic", "Magic Single", "Magic 2010", "Common", "English", "nla_catalog_only"], 101),
        variant(11, 1),
        product(2, "Lightning Bolt - Beta (Common) [LEB]", "lightning-bolt-beta", "Magic Single", ["Magic", "Magic Single", "Beta", "Common", "English", "nla_catalog_only"], 102, 2),
        variant(12, 2, "299.99", 2, True),
        product(3, "Emeritus of Conflict // Lightning Bolt - Secrets of Strixhaven (Mythic) [SOS-113]", "emeritus-lightning-bolt", "Magic Single", ["Magic", "Magic Single", "Secrets of Strixhaven", "Mythic", "English"], 103),
        variant(13, 3),
        product(4, "Darksteel Colossus - Darksteel (Rare) [DST-109]", "darksteel-colossus", "Magic Single", ["Magic", "Magic Single", "Darksteel", "Rare", "English"], 104),
        variant(14, 4),
        product(5, "Pikachu - Black Bolt (Common) [BLK-25]", "pikachu-black-bolt", "Pokémon Single", ["Pokémon", "Pokémon Single", "Black Bolt", "Common", "English"], 105),
        variant(15, 5),
        product(6, "Blue-Eyes White Dragon - Legend of Blue Eyes (Ultra Rare) [LOB-001]", "blue-eyes-white-dragon", "Yu-Gi-Oh! Single", ["Yu-Gi-Oh!", "Yu-Gi-Oh! Single", "Legend of Blue Eyes", "English"], 106),
        variant(16, 6),
        product(7, "Monkey.D.Luffy - Romance Dawn (Leader) [OP01-003]", "monkey-d-luffy", "One Piece Single", ["One Piece", "One Piece Single", "Romance Dawn", "English"], 107),
        variant(17, 7),
    ]
    snapshot.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")
    build_catalog(snapshot, db, expected_count=7, dataset_version="fixture-v1")
    return db


@pytest.fixture()
def client(database: Path):
    settings = Settings(
        ENVIRONMENT="test", DATABASE_PATH=database,
        CURSOR_SECRET="test-secret-that-is-long-enough",
        PUBLIC_BASE_URL="https://nextlevelarena.it",
        RATE_LIMIT_PER_MINUTE=1000, EXPECTED_PRODUCT_COUNT=7,
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def test_normalization_and_title_parsing():
    assert normalize_text("  Monkey.D.Luffy — V.1  ") == "monkey.d.luffy - v.1"
    parsed = parse_product_title("Lightning Bolt - Magic 2010 (Common) [M10-146]", ["Magic", "Magic 2010", "Common", "English"])
    assert (parsed.canonical_name, parsed.set_name, parsed.rarity, parsed.set_code, parsed.collector_number) == ("Lightning Bolt", "Magic 2010", "Common", "M10", "146")
    assert infer_game("Magic Single") == "magic"
    assert infer_game("Pokémon Single") == "pokemon"
    assert infer_game("Yu-Gi-Oh! Single") == "yugioh"
    assert infer_game("One Piece Single") == "one-piece"


def test_ingest_integrity(database: Path):
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 7
        row = connection.execute("SELECT canonical_name, set_name, available, price_cents FROM products WHERE handle='lightning-bolt-beta'").fetchone()
        assert (row["canonical_name"], row["set_name"], row["available"], row["price_cents"]) == ("Lightning Bolt", "Beta", 1, 29999)
    finally:
        connection.close()


def test_cursor_roundtrip_context_and_tamper():
    codec = CursorCodec("secret", 60)
    token = codec.encode({"mode": "search", "game": "magic", "q": "abc"})
    assert codec.decode(token, {"mode": "search", "game": "magic", "q": "abc"})["game"] == "magic"
    with pytest.raises(CursorError):
        codec.decode(token, {"mode": "search", "game": "pokemon", "q": "abc"})
    body, signature = token.split(".")
    tampered = ("A" if body[0] != "A" else "B") + body[1:] + "." + signature
    with pytest.raises(CursorError):
        codec.decode(tampered)


def signed_query(secret: str, timestamp: int = 1_700_000_000) -> str:
    raw = urlencode([
        ("extra", "1"), ("extra", "2"), ("shop", "nla.myshopify.com"),
        ("logged_in_customer_id", ""), ("path_prefix", "/apps/nla-catalog"),
        ("timestamp", str(timestamp)),
    ], doseq=True)
    message, _ = canonicalize_query_string(raw)
    signature = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    return raw + "&signature=" + signature


def test_app_proxy_hmac_shop_and_age():
    raw = signed_query("hush")
    assert verify_app_proxy(raw, "hush", "nla.myshopify.com", now=1_700_000_010)["shop"] == "nla.myshopify.com"
    with pytest.raises(AppProxyError):
        verify_app_proxy(raw.replace("signature=", "signature=x"), "hush", "nla.myshopify.com", now=1_700_000_010)
    with pytest.raises(AppProxyError):
        verify_app_proxy(raw, "hush", "other.myshopify.com", now=1_700_000_010)
    with pytest.raises(AppProxyError):
        verify_app_proxy(raw, "hush", "nla.myshopify.com", max_age_seconds=5, now=1_700_000_010)


def test_search_exact_first_and_cross_game_safe(client: TestClient):
    response = client.get("/api/catalog/search", params={"game": "magic", "q": "Lightning Bolt"})
    assert response.status_code == 200
    data = response.json()
    assert data["exactCount"] == 2
    assert [item["canonicalName"] for item in data["items"][:2]] == ["Lightning Bolt", "Lightning Bolt"]
    assert all(item["game"] == "magic" for item in data["items"])
    assert "Pikachu" not in {item["canonicalName"] for item in data["items"]}


def test_contains_browse_cursor_and_commerce_state(client: TestClient):
    colossus = client.get("/api/catalog/search", params={"game": "magic", "q": "Colossus"})
    assert [item["canonicalName"] for item in colossus.json()["items"]] == ["Darksteel Colossus"]
    first = client.get("/api/catalog/browse", params={"game": "magic", "limit": 2}).json()
    second_response = client.get("/api/catalog/browse", params={"game": "magic", "limit": 2, "cursor": first["pageInfo"]["endCursor"]})
    assert second_response.status_code == 200
    ids = [item["publicId"] for item in first["items"] + second_response.json()["items"]]
    assert len(ids) == len(set(ids))
    wrong_game = client.get("/api/catalog/browse", params={"game": "pokemon", "limit": 2, "cursor": first["pageInfo"]["endCursor"]})
    assert wrong_game.status_code == 400
    lightning = client.get("/api/catalog/search", params={"game": "magic", "q": "Lightning Bolt"}).json()["items"]
    assert {item["availabilityLabel"] for item in lightning[:2]} == {"Disponibile", "Esaurito"}
    available = next(item for item in lightning if item["available"])
    assert available["displayPrice"] == "299,99 €"
    assert available["url"].startswith("https://nextlevelarena.it/products/")


def test_suggestions_and_validation(client: TestClient):
    items = client.get("/api/catalog/suggest", params={"game": "magic", "q": "lightning"}).json()["items"]
    assert next(item for item in items if item["canonicalName"] == "Lightning Bolt")["printCount"] == 2
    assert client.get("/api/catalog/search", params={"game": "all", "q": "Bolt"}).status_code == 422
    assert client.get("/api/catalog/search", params={"game": "magic", "q": "x"}).status_code == 422
