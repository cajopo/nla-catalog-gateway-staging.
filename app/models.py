from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CatalogItem(BaseModel):
    publicId: str
    handle: str
    url: str
    game: str
    canonicalName: str
    setName: str | None = None
    setCode: str | None = None
    collectorNumber: str | None = None
    rarity: str | None = None
    language: str | None = None
    condition: str | None = None
    finish: str | None = None
    imageUrl: str | None = None
    available: bool
    availabilityLabel: Literal["Disponibile", "Esaurito"]
    inventory: int = 0
    displayPrice: str | None = None


class PageInfo(BaseModel):
    hasNextPage: bool
    endCursor: str | None = None


class SearchResponse(BaseModel):
    items: list[CatalogItem]
    pageInfo: PageInfo
    query: str
    game: str
    exactCount: int = 0
    datasetVersion: str


class BrowseResponse(BaseModel):
    items: list[CatalogItem]
    pageInfo: PageInfo
    game: str
    datasetVersion: str


class Suggestion(BaseModel):
    canonicalName: str
    game: str
    printCount: int
    availablePrintCount: int
    imageUrl: str | None = None


class SuggestResponse(BaseModel):
    items: list[Suggestion]
    query: str
    game: str
    datasetVersion: str


class GameInfo(BaseModel):
    key: str
    label: str
    productCount: int
    availableCount: int


class GamesResponse(BaseModel):
    games: list[GameInfo]
    datasetVersion: str


class FacetValue(BaseModel):
    value: str
    count: int


class FacetsResponse(BaseModel):
    game: str
    sets: list[FacetValue] = Field(default_factory=list)
    languages: list[FacetValue] = Field(default_factory=list)
    rarities: list[FacetValue] = Field(default_factory=list)
    availability: list[FacetValue] = Field(default_factory=list)
    datasetVersion: str
