from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Iterable

from app.cursor import CursorCodec
from app.database import Database
from app.models import (
    BrowseResponse,
    CatalogItem,
    FacetValue,
    FacetsResponse,
    GameInfo,
    GamesResponse,
    PageInfo,
    SearchResponse,
    Suggestion,
    SuggestResponse,
)
from app.normalization import GAME_LABELS, normalize_text

ALLOWED_GAMES = frozenset(GAME_LABELS)


@dataclass(frozen=True, slots=True)
class CatalogFilters:
    set_name: str | None = None
    language: str | None = None
    rarity: str | None = None
    availability: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "set": self.set_name,
            "language": self.language,
            "rarity": self.rarity,
            "availability": self.availability,
        }

    @property
    def fingerprint(self) -> str:
        raw = json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()[:20]


class CatalogRepository:
    def __init__(
        self,
        database: Database,
        cursor_codec: CursorCodec,
        public_base_url: str,
        max_page_size: int = 60,
    ) -> None:
        self.database = database
        self.cursor_codec = cursor_codec
        self.public_base_url = public_base_url.rstrip("/")
        self.max_page_size = max_page_size

    @staticmethod
    def validate_game(game: str) -> str:
        normalized = normalize_text(game).replace(" ", "-")
        aliases = {
            "mtg": "magic",
            "magic-the-gathering": "magic",
            "pokémon": "pokemon",
            "onepiece": "one-piece",
            "yu-gi-oh": "yugioh",
            "yu-gi-oh!": "yugioh",
        }
        normalized = aliases.get(normalized, normalized)
        if normalized not in ALLOWED_GAMES:
            raise ValueError("Unsupported game")
        return normalized

    def dataset_version(self) -> str:
        return self.database.metadata().get("dataset_version", "unknown")

    def _limit(self, limit: int) -> int:
        return max(1, min(limit, self.max_page_size))

    @staticmethod
    def _filter_sql(filters: CatalogFilters, params: list[Any]) -> str:
        clauses: list[str] = []
        if filters.set_name:
            clauses.append("set_name = ? COLLATE NOCASE")
            params.append(filters.set_name)
        if filters.language:
            clauses.append("language = ? COLLATE NOCASE")
            params.append(filters.language)
        if filters.rarity:
            clauses.append("rarity = ? COLLATE NOCASE")
            params.append(filters.rarity)
        if filters.availability == "available":
            clauses.append("available = 1")
        elif filters.availability == "sold-out":
            clauses.append("available = 0")
        return "".join(f" AND {clause}" for clause in clauses)

    def search(
        self,
        game: str,
        query: str,
        limit: int,
        cursor: str | None = None,
        filters: CatalogFilters | None = None,
    ) -> SearchResponse:
        game = self.validate_game(game)
        normalized_query = normalize_text(query)
        if len(normalized_query) < 2:
            raise ValueError("Query must contain at least two characters")
        filters = filters or CatalogFilters()
        version = self.dataset_version()
        qhash = self.cursor_codec.query_hash(normalized_query)
        limit = self._limit(limit)

        last_rank = -1
        last_name = ""
        last_id = 0
        if cursor:
            payload = self.cursor_codec.decode(
                cursor,
                expected={
                    "mode": "search",
                    "game": game,
                    "q": qhash,
                    "v": version,
                    "f": filters.fingerprint,
                },
            )
            last_rank = int(payload["rank"])
            last_name = str(payload["name"])
            last_id = int(payload["id"])

        params: list[Any] = [
            game,
            normalized_query,
            normalized_query + "%",
            "%" + normalized_query + "%",
        ]
        filter_sql = self._filter_sql(filters, params)
        params.extend([last_rank, last_rank, last_name, last_rank, last_name, last_id, limit + 1])
        sql = f"""
            WITH ranked AS (
                SELECT p.*,
                    CASE
                        WHEN normalized_name = ?2 THEN 0
                        WHEN normalized_name LIKE ?3 THEN 1
                        ELSE 2
                    END AS result_rank
                FROM products p
                WHERE game = ?1
                  AND normalized_name LIKE ?4
                  {filter_sql}
            )
            SELECT * FROM ranked
            WHERE result_rank > ?
               OR (result_rank = ? AND normalized_name > ?)
               OR (result_rank = ? AND normalized_name = ? AND id > ?)
            ORDER BY result_rank, normalized_name, id
            LIMIT ?
        """
        with self.database.connect() as connection:
            rows = connection.execute(sql, params).fetchall()
            exact_params: list[Any] = [game, normalized_query]
            exact_filter_sql = self._filter_sql(filters, exact_params)
            exact_count = connection.execute(
                f"SELECT COUNT(*) FROM products WHERE game = ? AND normalized_name = ? {exact_filter_sql}",
                exact_params,
            ).fetchone()[0]

        has_next = len(rows) > limit
        page_rows = rows[:limit]
        end_cursor = None
        if has_next and page_rows:
            last = page_rows[-1]
            end_cursor = self.cursor_codec.encode(
                {
                    "mode": "search",
                    "game": game,
                    "q": qhash,
                    "v": version,
                    "f": filters.fingerprint,
                    "rank": last["result_rank"],
                    "name": last["normalized_name"],
                    "id": last["id"],
                }
            )
        return SearchResponse(
            items=[self._to_item(row) for row in page_rows],
            pageInfo=PageInfo(hasNextPage=has_next, endCursor=end_cursor),
            query=query,
            game=game,
            exactCount=exact_count,
            datasetVersion=version,
        )

    def browse(
        self,
        game: str,
        limit: int,
        cursor: str | None = None,
        filters: CatalogFilters | None = None,
    ) -> BrowseResponse:
        game = self.validate_game(game)
        filters = filters or CatalogFilters()
        version = self.dataset_version()
        limit = self._limit(limit)
        last_name = ""
        last_id = 0
        if cursor:
            payload = self.cursor_codec.decode(
                cursor,
                expected={
                    "mode": "browse",
                    "game": game,
                    "v": version,
                    "f": filters.fingerprint,
                },
            )
            last_name = str(payload["name"])
            last_id = int(payload["id"])

        params: list[Any] = [game]
        filter_sql = self._filter_sql(filters, params)
        params.extend([last_name, last_name, last_id, limit + 1])
        with self.database.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM products
                WHERE game = ?
                  {filter_sql}
                  AND (normalized_name > ? OR (normalized_name = ? AND id > ?))
                ORDER BY normalized_name, id
                LIMIT ?
                """,
                params,
            ).fetchall()

        has_next = len(rows) > limit
        page_rows = rows[:limit]
        end_cursor = None
        if has_next and page_rows:
            last = page_rows[-1]
            end_cursor = self.cursor_codec.encode(
                {
                    "mode": "browse",
                    "game": game,
                    "v": version,
                    "f": filters.fingerprint,
                    "name": last["normalized_name"],
                    "id": last["id"],
                }
            )
        return BrowseResponse(
            items=[self._to_item(row) for row in page_rows],
            pageInfo=PageInfo(hasNextPage=has_next, endCursor=end_cursor),
            game=game,
            datasetVersion=version,
        )

    def suggest(self, game: str, query: str, limit: int = 8) -> SuggestResponse:
        game = self.validate_game(game)
        normalized_query = normalize_text(query)
        if len(normalized_query) < 2:
            return SuggestResponse(items=[], query=query, game=game, datasetVersion=self.dataset_version())
        limit = max(1, min(limit, 20))
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT canonical_name, normalized_name,
                    COUNT(*) AS print_count,
                    SUM(available) AS available_count,
                    MAX(image_url) AS image_url,
                    CASE
                        WHEN normalized_name = ? THEN 0
                        WHEN normalized_name LIKE ? THEN 1
                        ELSE 2
                    END AS result_rank
                FROM products
                WHERE game = ? AND normalized_name LIKE ?
                GROUP BY canonical_name, normalized_name
                ORDER BY result_rank, normalized_name
                LIMIT ?
                """,
                (normalized_query, normalized_query + "%", game, "%" + normalized_query + "%", limit),
            ).fetchall()
        return SuggestResponse(
            items=[
                Suggestion(
                    canonicalName=row["canonical_name"],
                    game=game,
                    printCount=row["print_count"],
                    availablePrintCount=row["available_count"],
                    imageUrl=row["image_url"],
                )
                for row in rows
            ],
            query=query,
            game=game,
            datasetVersion=self.dataset_version(),
        )

    def games(self) -> GamesResponse:
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT game, COUNT(*) AS product_count, SUM(available) AS available_count
                FROM products GROUP BY game ORDER BY game"""
            ).fetchall()
        return GamesResponse(
            games=[
                GameInfo(
                    key=row["game"],
                    label=GAME_LABELS.get(row["game"], row["game"]),
                    productCount=row["product_count"],
                    availableCount=row["available_count"],
                )
                for row in rows
            ],
            datasetVersion=self.dataset_version(),
        )

    def facets(self, game: str, query: str | None = None, facet_limit: int = 100) -> FacetsResponse:
        game = self.validate_game(game)
        normalized_query = normalize_text(query or "")
        base_where = "game = ?"
        base_params: list[Any] = [game]
        if normalized_query:
            base_where += " AND normalized_name LIKE ?"
            base_params.append("%" + normalized_query + "%")
        with self.database.connect() as connection:
            sets = self._facet(connection, "set_name", base_where, base_params, facet_limit)
            languages = self._facet(connection, "language", base_where, base_params, 30)
            rarities = self._facet(connection, "rarity", base_where, base_params, 30)
            availability_rows = connection.execute(
                f"SELECT available, COUNT(*) AS count FROM products WHERE {base_where} GROUP BY available ORDER BY available DESC",
                base_params,
            ).fetchall()
        return FacetsResponse(
            game=game,
            sets=sets,
            languages=languages,
            rarities=rarities,
            availability=[
                FacetValue(value="available" if row["available"] else "sold-out", count=row["count"])
                for row in availability_rows
            ],
            datasetVersion=self.dataset_version(),
        )

    @staticmethod
    def _facet(
        connection: sqlite3.Connection,
        column: str,
        where_sql: str,
        params: Iterable[Any],
        limit: int,
    ) -> list[FacetValue]:
        if column not in {"set_name", "language", "rarity"}:
            raise ValueError("Unsupported facet")
        rows = connection.execute(
            f"""SELECT {column} AS value, COUNT(*) AS count FROM products
            WHERE {where_sql} AND {column} IS NOT NULL AND {column} != ''
            GROUP BY {column} ORDER BY count DESC, value LIMIT ?""",
            [*params, limit],
        ).fetchall()
        return [FacetValue(value=row["value"], count=row["count"]) for row in rows]

    def _to_item(self, row: sqlite3.Row) -> CatalogItem:
        display_price = None
        if row["price_cents"] is not None and int(row["price_cents"]) > 0:
            euros = int(row["price_cents"]) / 100
            display_price = f"{euros:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
        public_id = row["powertools_product_id"] or row["shopify_product_id"]
        return CatalogItem(
            publicId=str(public_id),
            handle=row["handle"],
            url=f"{self.public_base_url}/products/{row['handle']}",
            game=row["game"],
            canonicalName=row["canonical_name"],
            setName=row["set_name"],
            setCode=row["set_code"],
            collectorNumber=row["collector_number"],
            rarity=row["rarity"],
            language=row["language"],
            condition=row["condition"],
            finish=row["finish"],
            imageUrl=row["image_url"],
            available=bool(row["available"]),
            availabilityLabel="Disponibile" if row["available"] else "Esaurito",
            inventory=int(row["inventory"] or 0),
            displayPrice=display_price,
        )
