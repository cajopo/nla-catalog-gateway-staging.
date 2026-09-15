"""Source card attributes; no identifier is inferred from a Shopify title or SKU."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True, slots=True)
class CardMetadataV1:
    """Raw PowerTools CSV fields, joined through game and verified source ID.

    The collector number is searchable literally. Expansion names/codes and rarity
    are display attributes, not independent search matches or invented printed IDs.
    Empty CSV cells become None; nonempty values are preserved exactly.
    """

    collector_number: str | None
    expansion_code: str | None
    expansion_name: str | None
    rarity: str | None

    FIELDS: ClassVar[frozenset[str]] = frozenset(
        {"collectorNumber", "expansionCode", "expansionName", "rarity"}
    )

    def __post_init__(self) -> None:
        for value in self.as_dict().values():
            if value is not None and (
                type(value) is not str
                or not value
                or len(value) > 1024
                or any(
                    (ord(char) < 32 and char not in "\t\r\n") or 0xD800 <= ord(char) <= 0xDFFF
                    for char in value
                )
            ):
                raise ValueError("card metadata field is invalid")

    def as_dict(self) -> dict[str, str | None]:
        return {
            "collectorNumber": self.collector_number,
            "expansionCode": self.expansion_code,
            "expansionName": self.expansion_name,
            "rarity": self.rarity,
        }

    @classmethod
    def from_dict(cls, value: object) -> CardMetadataV1:
        if type(value) is not dict or frozenset(value) != cls.FIELDS:
            raise ValueError("card metadata must contain its exact fields")
        return cls(
            collector_number=value["collectorNumber"],
            expansion_code=value["expansionCode"],
            expansion_name=value["expansionName"],
            rarity=value["rarity"],
        )


def optional_card_metadata(value: dict[str, object]) -> CardMetadataV1 | None:
    """Absent extension preserves legacy bytes; an explicit null is not canonical."""
    return CardMetadataV1.from_dict(value["cardMetadata"]) if "cardMetadata" in value else None
