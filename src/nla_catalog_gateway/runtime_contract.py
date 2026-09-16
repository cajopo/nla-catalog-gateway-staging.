"""Pure, deterministic v1 contracts for the read-only catalog runtime.

This module deliberately contains no transport, persistence, Shopify, cursor-codec,
search, or serving implementation.  It defines strict data-transfer objects and the
gates that keep provisional producer evidence from being mistaken for a verified
runtime capability.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, ClassVar, Self

from nla_catalog_gateway.bulk import (
    ALLOWED_TYPES,
    PRODUCT_STATUSES,
    SourceSnapshotEvidence,
    SourceSnapshotManifest,
)
from nla_catalog_gateway.card_metadata import CardMetadataV1, optional_card_metadata
from nla_catalog_gateway.taxonomy import Classification, Game, ProductFamily

CONTRACT_VERSION = 1
SOURCE_MANIFEST_SCHEMA_VERSION = 2
MAX_CONTRACT_BYTES = 2 * 1024 * 1024
MAX_SOURCE_MANIFEST_BYTES = 64 * 1024
MAX_ERROR_MESSAGE_LENGTH = 512
SIGNED_64_MIN = -(2**63)
SIGNED_64_MAX = 2**63 - 1

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_GENERATION_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_POSITIVE_DECIMAL_RE = re.compile(r"[1-9][0-9]*\Z")
_PRICE_RE = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z")
_RULE_VERSION_RE = re.compile(r"[0-9A-Za-z][0-9A-Za-z._-]*\Z")
_RULE_ID_RE = re.compile(r"[a-z0-9]+(?:(?:-|:)[a-z0-9]+)*\Z")
_SUBTYPE_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_REASON_RE = re.compile(r"[a-z0-9]+(?:_[a-z0-9]+)*\Z")
_FIELD_PATH_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:\.[A-Za-z][A-Za-z0-9]*)*\Z")
_GID_RE = re.compile(r"gid://shopify/([A-Za-z][A-Za-z0-9]*)/([1-9][0-9]*)\Z")
_RFC3339_RE = re.compile(
    r"(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})T"
    r"(?P<clock>[0-9]{2}:[0-9]{2}:[0-9]{2})"
    r"(?:\.(?P<fraction>[0-9]+))?(?P<zone>Z|[+-][0-9]{2}:[0-9]{2})\Z"
)
_BOMS = (
    b"\xef\xbb\xbf",
    b"\xff\xfe",
    b"\xfe\xff",
    b"\xff\xfe\x00\x00",
    b"\x00\x00\xfe\xff",
)


class RuntimeContractError(ValueError):
    """A bounded, value-free failure for an invalid runtime contract."""


class CapabilityState(StrEnum):
    VERIFIED = "verified"
    PROVISIONAL = "provisional"
    UNSUPPORTED = "unsupported"


class FieldDisposition(StrEnum):
    REQUIRED = "required"
    NULLABLE = "nullable"
    PROVISIONAL = "provisional"
    UNSUPPORTED = "unsupported"


class RequestFamily(StrEnum):
    ALL = "all"
    SINGLE = "single"
    SEALED = "sealed"
    ACCESSORY = "accessory"


class ProductStatus(StrEnum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"
    DRAFT = "DRAFT"
    UNLISTED = "UNLISTED"


class InventoryPolicy(StrEnum):
    CONTINUE = "CONTINUE"
    DENY = "DENY"


class CatalogErrorCode(StrEnum):
    INVALID_REQUEST = "invalid_request"
    INVALID_CURSOR = "invalid_cursor"
    RESTART_REQUIRED = "restart_required"
    DATASET_UNAVAILABLE = "dataset_unavailable"
    TEMPORARILY_UNAVAILABLE = "temporarily_unavailable"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    INCOMPATIBLE_FILTER = "incompatible_filter"
    CURSOR_CONTEXT_MISMATCH = "cursor_context_mismatch"
    DATASET_GENERATION_MISMATCH = "dataset_generation_mismatch"
    CONTRACT_VIOLATION = "contract_violation"


class CatalogEndpoint(StrEnum):
    CATALOG = "catalog"


PUBLIC_ERROR_MESSAGES_V1: Mapping[CatalogErrorCode, str] = MappingProxyType(
    {
        CatalogErrorCode.INVALID_REQUEST: "The catalog request is invalid.",
        CatalogErrorCode.INVALID_CURSOR: "The catalog cursor is invalid.",
        CatalogErrorCode.RESTART_REQUIRED: "The catalog changed; restart pagination.",
        CatalogErrorCode.DATASET_UNAVAILABLE: "The catalog dataset is unavailable.",
        CatalogErrorCode.TEMPORARILY_UNAVAILABLE: "The catalog is temporarily unavailable.",
        CatalogErrorCode.UNSUPPORTED_CAPABILITY: (
            "The requested catalog capability is unavailable."
        ),
        CatalogErrorCode.INCOMPATIBLE_FILTER: (
            "The catalog filter is incompatible with this request."
        ),
        CatalogErrorCode.CURSOR_CONTEXT_MISMATCH: "The catalog cursor context is invalid.",
        CatalogErrorCode.DATASET_GENERATION_MISMATCH: ("The catalog changed; restart pagination."),
        CatalogErrorCode.CONTRACT_VIOLATION: "The catalog contract is invalid.",
    }
)


FEATURE_CAPABILITIES_V1: tuple[tuple[str, CapabilityState], ...] = (
    ("catalogItem", CapabilityState.PROVISIONAL),
    ("catalogProductRecord", CapabilityState.PROVISIONAL),
    ("datasetManifest", CapabilityState.PROVISIONAL),
    ("requestContext", CapabilityState.PROVISIONAL),
    ("activeIndex", CapabilityState.UNSUPPORTED),
    ("catalogOutput", CapabilityState.UNSUPPORTED),
    ("cursorCodec", CapabilityState.UNSUPPORTED),
    ("facets", CapabilityState.UNSUPPORTED),
)

REQUEST_CAPABILITIES_V1: tuple[tuple[str, CapabilityState], ...] = tuple(
    (f"{game.value}/{family.value}", CapabilityState.PROVISIONAL)
    for game in Game
    for family in RequestFamily
)

COMPATIBILITY_MATRIX_V1: Mapping[str, str] = MappingProxyType(
    {
        "additiveNullableField": "minor",
        "enumChange": "major",
        "fieldRemoval": "major",
        "fieldRename": "major",
        "nullabilityChange": "major",
        "semanticChange": "major",
        "typeChange": "major",
    }
)


def _fail(message: str) -> RuntimeContractError:
    return RuntimeContractError(message)


def _canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, UnicodeEncodeError, ValueError) as exc:
        raise _fail("contract value is not canonically serializable") from exc


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _fail("contract JSON contains a duplicate key")
        result[key] = value
    return result


def _parse_integer(value: str) -> int:
    if len(value.lstrip("-")) > 19:
        raise _fail("contract JSON integer is outside signed 64-bit range")
    return int(value)


def _reject_float(_value: str) -> None:
    raise _fail("contract JSON numbers must be signed integers")


def _reject_constant(_value: str) -> None:
    raise _fail("contract JSON contains a non-finite number")


def _contains_surrogate(value: str) -> bool:
    return any(0xD800 <= ord(character) <= 0xDFFF for character in value)


def _validate_unicode_tree(root: Any) -> None:
    pending = [root]
    while pending:
        value = pending.pop()
        if type(value) is str:
            if _contains_surrogate(value):
                raise _fail("contract JSON contains invalid Unicode")
        elif type(value) is dict:
            pending.extend(value.keys())
            pending.extend(value.values())
        elif type(value) is list:
            pending.extend(value)


def _load_json_object(raw: bytes, *, byte_limit: int = MAX_CONTRACT_BYTES) -> dict[str, Any]:
    if type(raw) is not bytes:
        raise _fail("contract JSON input must be bytes")
    if not raw:
        raise _fail("contract JSON input is empty")
    if len(raw) > byte_limit:
        raise _fail("contract JSON input exceeds the byte limit")
    if raw.startswith(_BOMS):
        raise _fail("contract JSON input must not contain a BOM")
    try:
        text = raw.decode("utf-8")
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
            parse_float=_reject_float,
            parse_int=_parse_integer,
        )
    except RuntimeContractError:
        raise
    except (RecursionError, UnicodeDecodeError, ValueError) as exc:
        raise _fail("contract JSON input is invalid") from exc
    _validate_unicode_tree(value)
    if type(value) is not dict:
        raise _fail("contract JSON root must be an object")
    return value


def _exact_keys(value: dict[str, Any], expected: frozenset[str], context: str) -> None:
    if any(type(key) is not str for key in value) or frozenset(value) != expected:
        raise _fail(f"{context} has missing or unknown fields")


def _string(value: Any, context: str, *, nonempty: bool = True) -> str:
    if type(value) is not str or (nonempty and not value.strip()):
        raise _fail(f"{context} must be a string")
    if _contains_surrogate(value):
        raise _fail(f"{context} contains invalid Unicode")
    return value


def _nullable_string(value: Any, context: str, *, nonempty: bool = False) -> str | None:
    if value is None:
        return None
    return _string(value, context, nonempty=nonempty)


def _boolean(value: Any, context: str) -> bool:
    if type(value) is not bool:
        raise _fail(f"{context} must be boolean")
    return value


def _signed_integer(value: Any, context: str) -> int:
    if type(value) is not int or not SIGNED_64_MIN <= value <= SIGNED_64_MAX:
        raise _fail(f"{context} must be a signed 64-bit integer")
    return value


def _nonnegative_integer(value: Any, context: str) -> int:
    integer = _signed_integer(value, context)
    if integer < 0:
        raise _fail(f"{context} must be non-negative")
    return integer


def _positive_integer(value: Any, context: str) -> int:
    integer = _signed_integer(value, context)
    if integer < 1:
        raise _fail(f"{context} must be positive")
    return integer


def _enum(enum_type: type[StrEnum], value: Any, context: str) -> Any:
    if type(value) is not str:
        raise _fail(f"{context} must be a canonical enum string")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise _fail(f"{context} is not a supported enum value") from exc


def _gid(value: Any, kind: str, context: str) -> str:
    text = _string(value, context)
    match = _GID_RE.fullmatch(text)
    if match is None or match.group(1) != kind:
        raise _fail(f"{context} must be a canonical Shopify {kind} GID")
    return text


def _typed_gid_sort_key(value: str, kind: str, context: str) -> tuple[int, str]:
    text = _gid(value, kind, context)
    digits = text.removeprefix(f"gid://shopify/{kind}/")
    return (len(digits), digits)


def _gid_sort_key(value: str) -> tuple[int, str]:
    return _typed_gid_sort_key(value, "Product", "sortable Product GID")


def _variant_gid_sort_key(value: str) -> tuple[int, str]:
    return _typed_gid_sort_key(value, "ProductVariant", "sortable ProductVariant GID")


def _sha256(value: Any, context: str) -> str:
    text = _string(value, context)
    if _SHA256_RE.fullmatch(text) is None:
        raise _fail(f"{context} must be a lowercase SHA-256 digest")
    return text


def _generation(value: Any, context: str) -> str:
    text = _string(value, context)
    if _GENERATION_RE.fullmatch(text) is None:
        raise _fail(f"{context} must be a canonical content generation")
    return text


def _price(value: Any, context: str) -> str:
    text = _string(value, context)
    if _PRICE_RE.fullmatch(text) is None:
        raise _fail(f"{context} must be non-lossy decimal text")
    return text


def _source_identifier(value: Any, context: str) -> str | None:
    text = _nullable_string(value, context, nonempty=True)
    if text is not None and _POSITIVE_DECIMAL_RE.fullmatch(text) is None:
        raise _fail(f"{context} must be canonical positive decimal text")
    return text


def _optional_card_metadata(value: dict[str, Any]) -> CardMetadataV1 | None:
    try:
        return optional_card_metadata(value)
    except ValueError as exc:
        raise _fail("card metadata is invalid") from exc


def _validated_timestamp(value: Any, context: str) -> tuple[str, re.Match[str], datetime]:
    text = _string(value, context)
    match = _RFC3339_RE.fullmatch(text)
    if match is None:
        raise _fail(f"{context} must use the canonical timezone-aware RFC3339 subset")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _fail(f"{context} is not a calendar-valid timestamp") from exc
    return text, match, parsed


def _timestamp(value: Any, context: str) -> str:
    return _validated_timestamp(value, context)[0]


def _expiry_order_key(value: Any, context: str) -> tuple[str, int, str]:
    text, match, parsed = _validated_timestamp(value, context)
    zone = match.group("zone")
    if zone == "-00:00":
        raise _fail(f"{context} must use a known timezone offset")
    if zone == "Z":
        offset_seconds = 0
    else:
        offset_sign = 1 if zone[0] == "+" else -1
        offset_seconds = offset_sign * (int(zone[1:3]) * 3_600 + int(zone[4:6]) * 60)
    whole_seconds = (
        parsed.toordinal() * 86_400
        + parsed.hour * 3_600
        + parsed.minute * 60
        + parsed.second
        - offset_seconds
    )
    fraction = (match.group("fraction") or "").rstrip("0")
    return text, whole_seconds, fraction


def _expiry_timestamp(value: Any, context: str) -> str:
    return _expiry_order_key(value, context)[0]


def _rule_version(value: Any, context: str) -> str:
    text = _string(value, context)
    if _RULE_VERSION_RE.fullmatch(text) is None:
        raise _fail(f"{context} must be a canonical rule version")
    return text


def _nullable_rule_id(value: Any, context: str) -> str | None:
    text = _nullable_string(value, context, nonempty=True)
    if text is not None and _RULE_ID_RE.fullmatch(text) is None:
        raise _fail(f"{context} must be a canonical rule identifier")
    return text


def _nullable_subtype(value: Any, context: str) -> str | None:
    text = _nullable_string(value, context, nonempty=True)
    if text is not None and _SUBTYPE_RE.fullmatch(text) is None:
        raise _fail(f"{context} must be a canonical subtype")
    return text


def _nullable_reason(value: Any, context: str) -> str | None:
    text = _nullable_string(value, context, nonempty=True)
    if text is not None and _REASON_RE.fullmatch(text) is None:
        raise _fail(f"{context} must be a canonical machine-readable reason")
    return text


def _is_exact_serializable_dto_type(dto_type: Any) -> bool:
    return any(dto_type is expected_type for expected_type in SERIALIZABLE_DTOS_V1)


class _JsonDto:
    FIELDS: ClassVar[frozenset[str]]

    def to_json_bytes(self) -> bytes:
        if not _is_exact_serializable_dto_type(type(self)):
            raise _fail("unsupported runtime contract DTO type")
        return _canonical_json_bytes(self.as_dict())

    @classmethod
    def from_json_bytes(cls, raw: bytes) -> Self:
        if not _is_exact_serializable_dto_type(cls):
            raise _fail("unsupported runtime contract DTO type")
        return cls.from_dict(_load_json_object(raw))


@dataclass(frozen=True, slots=True)
class SelectedOptionV1(_JsonDto):
    name: str
    value: str

    FIELDS = frozenset({"name", "value"})

    def __post_init__(self) -> None:
        _string(self.name, "selected option name")
        _string(self.value, "selected option value")

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "value": self.value}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Self:
        if type(value) is not dict:
            raise _fail("selected option must be an object")
        _exact_keys(value, cls.FIELDS, "selected option")
        return cls(
            name=_string(value["name"], "selected option name"),
            value=_string(value["value"], "selected option value"),
        )


@dataclass(frozen=True, slots=True)
class CatalogVariantRecordV1(_JsonDto):
    variant_gid: str
    product_gid: str
    inventory_item_gid: str
    title: str
    sku: str | None
    barcode: str | None
    selected_options: tuple[SelectedOptionV1, ...]
    price_text: str
    compare_at_price_text: str | None
    inventory_quantity: int
    inventory_policy: InventoryPolicy
    inventory_tracked: bool
    updated_at: str

    FIELDS = frozenset(
        {
            "barcode",
            "compareAtPriceText",
            "inventoryItemGid",
            "inventoryPolicy",
            "inventoryQuantity",
            "inventoryTracked",
            "priceText",
            "productGid",
            "selectedOptions",
            "sku",
            "title",
            "updatedAt",
            "variantGid",
        }
    )

    def __post_init__(self) -> None:
        _gid(self.variant_gid, "ProductVariant", "variantGid")
        _gid(self.product_gid, "Product", "productGid")
        _gid(self.inventory_item_gid, "InventoryItem", "inventoryItemGid")
        _string(self.title, "variant title")
        _nullable_string(self.sku, "variant SKU")
        _nullable_string(self.barcode, "variant barcode")
        if type(self.selected_options) is not tuple:
            raise _fail("selectedOptions must be a tuple")
        for option in self.selected_options:
            if type(option) is not SelectedOptionV1:
                raise _fail("selectedOptions must contain selected option records")
        _price(self.price_text, "variant priceText")
        if self.compare_at_price_text is not None:
            _price(self.compare_at_price_text, "variant compareAtPriceText")
        _signed_integer(self.inventory_quantity, "variant inventoryQuantity")
        if type(self.inventory_policy) is not InventoryPolicy:
            raise _fail("variant inventoryPolicy must be canonical")
        _boolean(self.inventory_tracked, "variant inventoryTracked")
        _timestamp(self.updated_at, "variant updatedAt")

    def as_dict(self) -> dict[str, Any]:
        return {
            "barcode": self.barcode,
            "compareAtPriceText": self.compare_at_price_text,
            "inventoryItemGid": self.inventory_item_gid,
            "inventoryPolicy": self.inventory_policy.value,
            "inventoryQuantity": self.inventory_quantity,
            "inventoryTracked": self.inventory_tracked,
            "priceText": self.price_text,
            "productGid": self.product_gid,
            "selectedOptions": [option.as_dict() for option in self.selected_options],
            "sku": self.sku,
            "title": self.title,
            "updatedAt": self.updated_at,
            "variantGid": self.variant_gid,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Self:
        if type(value) is not dict:
            raise _fail("catalog variant record must be an object")
        _exact_keys(value, cls.FIELDS, "catalog variant record")
        options = value["selectedOptions"]
        if type(options) is not list:
            raise _fail("selectedOptions must be an array")
        return cls(
            variant_gid=_gid(value["variantGid"], "ProductVariant", "variantGid"),
            product_gid=_gid(value["productGid"], "Product", "productGid"),
            inventory_item_gid=_gid(value["inventoryItemGid"], "InventoryItem", "inventoryItemGid"),
            title=_string(value["title"], "variant title"),
            sku=_nullable_string(value["sku"], "variant SKU"),
            barcode=_nullable_string(value["barcode"], "variant barcode"),
            selected_options=tuple(SelectedOptionV1.from_dict(option) for option in options),
            price_text=_price(value["priceText"], "variant priceText"),
            compare_at_price_text=(
                None
                if value["compareAtPriceText"] is None
                else _price(value["compareAtPriceText"], "variant compareAtPriceText")
            ),
            inventory_quantity=_signed_integer(
                value["inventoryQuantity"], "variant inventoryQuantity"
            ),
            inventory_policy=_enum(
                InventoryPolicy, value["inventoryPolicy"], "variant inventoryPolicy"
            ),
            inventory_tracked=_boolean(value["inventoryTracked"], "variant inventoryTracked"),
            updated_at=_timestamp(value["updatedAt"], "variant updatedAt"),
        )


@dataclass(frozen=True, slots=True)
class CatalogVariantItemV1(_JsonDto):
    """Minimum public Variant view nested under one Product-level catalog item."""

    variant_gid: str
    title: str
    selected_options: tuple[SelectedOptionV1, ...]
    price_text: str
    compare_at_price_text: str | None
    inventory_quantity: int
    inventory_policy: InventoryPolicy
    inventory_tracked: bool

    FIELDS = frozenset(
        {
            "compareAtPriceText",
            "inventoryPolicy",
            "inventoryQuantity",
            "inventoryTracked",
            "priceText",
            "selectedOptions",
            "title",
            "variantGid",
        }
    )

    def __post_init__(self) -> None:
        _gid(self.variant_gid, "ProductVariant", "public variantGid")
        _string(self.title, "public variant title")
        if type(self.selected_options) is not tuple:
            raise _fail("public selectedOptions must be a tuple")
        for option in self.selected_options:
            if type(option) is not SelectedOptionV1:
                raise _fail("public selectedOptions must contain selected option records")
        _price(self.price_text, "public variant priceText")
        if self.compare_at_price_text is not None:
            _price(self.compare_at_price_text, "public variant compareAtPriceText")
        _signed_integer(self.inventory_quantity, "public variant inventoryQuantity")
        if type(self.inventory_policy) is not InventoryPolicy:
            raise _fail("public variant inventoryPolicy must be canonical")
        _boolean(self.inventory_tracked, "public variant inventoryTracked")

    @classmethod
    def from_variant_record(cls, record: CatalogVariantRecordV1) -> Self:
        if type(record) is not CatalogVariantRecordV1:
            raise _fail("public variant source must be a variant record")
        return cls(
            variant_gid=record.variant_gid,
            title=record.title,
            selected_options=record.selected_options,
            price_text=record.price_text,
            compare_at_price_text=record.compare_at_price_text,
            inventory_quantity=record.inventory_quantity,
            inventory_policy=record.inventory_policy,
            inventory_tracked=record.inventory_tracked,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "compareAtPriceText": self.compare_at_price_text,
            "inventoryPolicy": self.inventory_policy.value,
            "inventoryQuantity": self.inventory_quantity,
            "inventoryTracked": self.inventory_tracked,
            "priceText": self.price_text,
            "selectedOptions": [option.as_dict() for option in self.selected_options],
            "title": self.title,
            "variantGid": self.variant_gid,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Self:
        if type(value) is not dict:
            raise _fail("public catalog variant must be an object")
        _exact_keys(value, cls.FIELDS, "public catalog variant")
        options = value["selectedOptions"]
        if type(options) is not list:
            raise _fail("public selectedOptions must be an array")
        raw_compare_at = value["compareAtPriceText"]
        return cls(
            variant_gid=_gid(value["variantGid"], "ProductVariant", "public variantGid"),
            title=_string(value["title"], "public variant title"),
            selected_options=tuple(SelectedOptionV1.from_dict(option) for option in options),
            price_text=_price(value["priceText"], "public variant priceText"),
            compare_at_price_text=(
                None
                if raw_compare_at is None
                else _price(raw_compare_at, "public variant compareAtPriceText")
            ),
            inventory_quantity=_signed_integer(
                value["inventoryQuantity"], "public variant inventoryQuantity"
            ),
            inventory_policy=_enum(
                InventoryPolicy,
                value["inventoryPolicy"],
                "public variant inventoryPolicy",
            ),
            inventory_tracked=_boolean(
                value["inventoryTracked"], "public variant inventoryTracked"
            ),
        )


@dataclass(frozen=True, slots=True)
class CatalogProductRecordV1(_JsonDto):
    product_gid: str
    handle: str
    commercial_title: str
    canonical_card_name: str | None
    shopify_status: ProductStatus
    online_store_published: bool
    powertools_source_id: str | None
    sync_source_id: str | None
    total_inventory: int
    tracks_inventory: bool
    updated_at: str
    game: Game | None
    product_family: ProductFamily
    product_subtype: str | None
    classification_rule_version: str
    classification_rule_id: str | None
    unclassified_reason: str | None
    subtype_rule_id: str | None
    subtype_reason: str | None
    variants: tuple[CatalogVariantRecordV1, ...]
    contract_version: int = CONTRACT_VERSION
    card_metadata: CardMetadataV1 | None = None

    FIELDS = frozenset(
        {
            "canonicalCardName",
            "classificationRuleId",
            "classificationRuleVersion",
            "commercialTitle",
            "contractVersion",
            "game",
            "handle",
            "onlineStorePublished",
            "powerToolsSourceId",
            "productFamily",
            "productGid",
            "productSubtype",
            "shopifyStatus",
            "subtypeReason",
            "subtypeRuleId",
            "syncSourceId",
            "totalInventory",
            "tracksInventory",
            "unclassifiedReason",
            "updatedAt",
            "variants",
        }
    )

    def __post_init__(self) -> None:
        if type(self.contract_version) is not int or self.contract_version != CONTRACT_VERSION:
            raise _fail("catalog product record contractVersion must be 1")
        _gid(self.product_gid, "Product", "productGid")
        _string(self.handle, "product handle")
        _string(self.commercial_title, "commercialTitle")
        _nullable_string(self.canonical_card_name, "canonicalCardName", nonempty=True)
        if type(self.shopify_status) is not ProductStatus:
            raise _fail("shopifyStatus must be canonical")
        _boolean(self.online_store_published, "onlineStorePublished")
        power_id = _source_identifier(self.powertools_source_id, "powerToolsSourceId")
        sync_id = _source_identifier(self.sync_source_id, "syncSourceId")
        if (power_id is None) != (sync_id is None) or power_id != sync_id:
            raise _fail("source IDs must both be null or identical canonical decimal text")
        _signed_integer(self.total_inventory, "totalInventory")
        _boolean(self.tracks_inventory, "tracksInventory")
        _timestamp(self.updated_at, "product updatedAt")
        if self.game is not None and type(self.game) is not Game:
            raise _fail("game must be canonical")
        if type(self.product_family) is not ProductFamily:
            raise _fail("productFamily must be a persisted taxonomy family")
        if self.card_metadata is not None and (
            type(self.card_metadata) is not CardMetadataV1
            or self.product_family is not ProductFamily.SINGLE
            or self.sync_source_id is None
        ):
            raise _fail("card metadata requires a source-identified single")
        _nullable_subtype(self.product_subtype, "productSubtype")
        _rule_version(self.classification_rule_version, "classificationRuleVersion")
        _nullable_rule_id(self.classification_rule_id, "classificationRuleId")
        _nullable_reason(self.unclassified_reason, "unclassifiedReason")
        _nullable_rule_id(self.subtype_rule_id, "subtypeRuleId")
        _nullable_reason(self.subtype_reason, "subtypeReason")
        self._validate_classification()
        if type(self.variants) is not tuple or not self.variants:
            raise _fail("variants must be a non-empty tuple")
        variant_gids: set[str] = set()
        inventory_item_gids: set[str] = set()
        for variant in self.variants:
            if type(variant) is not CatalogVariantRecordV1:
                raise _fail("variants must contain catalog variant records")
            if variant.product_gid != self.product_gid:
                raise _fail("variant productGid must match its parent Product GID")
            if (
                variant.variant_gid in variant_gids
                or variant.inventory_item_gid in inventory_item_gids
            ):
                raise _fail("variant and inventory-item GIDs must be unique within a product")
            variant_gids.add(variant.variant_gid)
            inventory_item_gids.add(variant.inventory_item_gid)
        ordered_variant_gids = tuple(sorted(variant_gids, key=_variant_gid_sort_key))
        if tuple(variant.variant_gid for variant in self.variants) != ordered_variant_gids:
            raise _fail("variants must use ascending ProductVariant GID order")

    @property
    def publishable(self) -> bool:
        return self.shopify_status is ProductStatus.ACTIVE and self.online_store_published

    def _validate_classification(self) -> None:
        if self.product_family is ProductFamily.UNCLASSIFIED:
            if self.classification_rule_id is not None or self.unclassified_reason is None:
                raise _fail("unclassified products require a reason and no classification rule")
            if any(
                value is not None
                for value in (self.product_subtype, self.subtype_rule_id, self.subtype_reason)
            ):
                raise _fail("unclassified products cannot carry subtype classification")
            return
        if self.game is None or self.classification_rule_id is None:
            raise _fail("classified products require game and classification rule")
        if self.unclassified_reason is not None:
            raise _fail("classified products cannot carry an unclassified reason")
        if self.product_family is not ProductFamily.SEALED and any(
            value is not None
            for value in (self.product_subtype, self.subtype_rule_id, self.subtype_reason)
        ):
            raise _fail("only sealed products may carry subtype classification")
        if self.product_family is ProductFamily.SEALED:
            if (self.product_subtype is None) != (self.subtype_rule_id is None):
                raise _fail("sealed subtype and subtype rule must be present together")
            if self.product_subtype is not None and self.subtype_reason is not None:
                raise _fail("classified sealed subtype cannot carry a subtype reason")
            if self.product_subtype is None and self.subtype_reason is None:
                raise _fail("sealed product without a subtype requires a subtype reason")
        if (
            self.publishable
            and self.product_family is ProductFamily.SINGLE
            and not (self.canonical_card_name or "").strip()
        ):
            raise _fail("publishable single requires canonicalCardName")

    @classmethod
    def from_classification(
        cls,
        *,
        classification: Classification,
        handle: str,
        commercial_title: str,
        canonical_card_name: str | None,
        shopify_status: ProductStatus,
        online_store_published: bool,
        powertools_source_id: str | None,
        sync_source_id: str | None,
        total_inventory: int,
        tracks_inventory: bool,
        updated_at: str,
        variants: tuple[CatalogVariantRecordV1, ...],
        card_metadata: CardMetadataV1 | None = None,
    ) -> Self:
        if type(classification) is not Classification:
            raise _fail("classification must be a taxonomy Classification")
        return cls(
            product_gid=classification.product_gid,
            handle=handle,
            commercial_title=commercial_title,
            canonical_card_name=canonical_card_name,
            shopify_status=shopify_status,
            online_store_published=online_store_published,
            powertools_source_id=powertools_source_id,
            sync_source_id=sync_source_id,
            total_inventory=total_inventory,
            tracks_inventory=tracks_inventory,
            updated_at=updated_at,
            game=classification.game,
            product_family=classification.family,
            product_subtype=classification.subtype,
            classification_rule_version=classification.rule_version,
            classification_rule_id=classification.rule_id,
            unclassified_reason=classification.reason,
            subtype_rule_id=classification.subtype_rule_id,
            subtype_reason=classification.subtype_reason,
            variants=variants,
            card_metadata=card_metadata,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "canonicalCardName": self.canonical_card_name,
            **({"cardMetadata": self.card_metadata.as_dict()} if self.card_metadata else {}),
            "classificationRuleId": self.classification_rule_id,
            "classificationRuleVersion": self.classification_rule_version,
            "commercialTitle": self.commercial_title,
            "contractVersion": self.contract_version,
            "game": self.game.value if self.game else None,
            "handle": self.handle,
            "onlineStorePublished": self.online_store_published,
            "powerToolsSourceId": self.powertools_source_id,
            "productFamily": self.product_family.value,
            "productGid": self.product_gid,
            "productSubtype": self.product_subtype,
            "shopifyStatus": self.shopify_status.value,
            "subtypeReason": self.subtype_reason,
            "subtypeRuleId": self.subtype_rule_id,
            "syncSourceId": self.sync_source_id,
            "totalInventory": self.total_inventory,
            "tracksInventory": self.tracks_inventory,
            "unclassifiedReason": self.unclassified_reason,
            "updatedAt": self.updated_at,
            "variants": [variant.as_dict() for variant in self.variants],
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Self:
        if type(value) is not dict:
            raise _fail("catalog product record must be an object")
        fields = cls.FIELDS | ({"cardMetadata"} if "cardMetadata" in value else set())
        _exact_keys(value, fields, "catalog product record")
        raw_variants = value["variants"]
        if type(raw_variants) is not list:
            raise _fail("variants must be an array")
        game = value["game"]
        return cls(
            contract_version=_positive_integer(value["contractVersion"], "contractVersion"),
            product_gid=_gid(value["productGid"], "Product", "productGid"),
            handle=_string(value["handle"], "product handle"),
            commercial_title=_string(value["commercialTitle"], "commercialTitle"),
            canonical_card_name=_nullable_string(
                value["canonicalCardName"], "canonicalCardName", nonempty=True
            ),
            shopify_status=_enum(ProductStatus, value["shopifyStatus"], "shopifyStatus"),
            online_store_published=_boolean(value["onlineStorePublished"], "onlineStorePublished"),
            powertools_source_id=_source_identifier(
                value["powerToolsSourceId"], "powerToolsSourceId"
            ),
            sync_source_id=_source_identifier(value["syncSourceId"], "syncSourceId"),
            total_inventory=_signed_integer(value["totalInventory"], "totalInventory"),
            tracks_inventory=_boolean(value["tracksInventory"], "tracksInventory"),
            updated_at=_timestamp(value["updatedAt"], "product updatedAt"),
            game=None if game is None else _enum(Game, game, "game"),
            product_family=_enum(ProductFamily, value["productFamily"], "productFamily"),
            product_subtype=_nullable_subtype(value["productSubtype"], "productSubtype"),
            classification_rule_version=_rule_version(
                value["classificationRuleVersion"], "classificationRuleVersion"
            ),
            classification_rule_id=_nullable_rule_id(
                value["classificationRuleId"], "classificationRuleId"
            ),
            unclassified_reason=_nullable_reason(value["unclassifiedReason"], "unclassifiedReason"),
            subtype_rule_id=_nullable_rule_id(value["subtypeRuleId"], "subtypeRuleId"),
            subtype_reason=_nullable_reason(value["subtypeReason"], "subtypeReason"),
            variants=tuple(CatalogVariantRecordV1.from_dict(item) for item in raw_variants),
            card_metadata=_optional_card_metadata(value),
        )


@dataclass(frozen=True, slots=True)
class CatalogItemV1(_JsonDto):
    """One public catalog item per Shopify Product, never per representative Variant."""

    product_gid: str
    handle: str
    commercial_title: str
    canonical_card_name: str | None
    game: Game
    product_family: ProductFamily
    product_subtype: str | None
    variants: tuple[CatalogVariantItemV1, ...]
    contract_version: int = CONTRACT_VERSION
    card_metadata: CardMetadataV1 | None = None

    FIELDS = frozenset(
        {
            "canonicalCardName",
            "commercialTitle",
            "contractVersion",
            "game",
            "handle",
            "productFamily",
            "productGid",
            "productSubtype",
            "variants",
        }
    )

    def __post_init__(self) -> None:
        if type(self.contract_version) is not int or self.contract_version != CONTRACT_VERSION:
            raise _fail("catalog item contractVersion must be 1")
        _gid(self.product_gid, "Product", "productGid")
        _string(self.handle, "catalog item handle")
        _string(self.commercial_title, "commercialTitle")
        _nullable_string(self.canonical_card_name, "canonicalCardName", nonempty=True)
        if type(self.game) is not Game:
            raise _fail("catalog item game must be canonical")
        if type(self.product_family) is not ProductFamily:
            raise _fail("catalog item productFamily must be canonical ProductFamily")
        if self.product_family is ProductFamily.UNCLASSIFIED:
            raise _fail("public catalog item must have a classified productFamily")
        if self.card_metadata is not None and (
            type(self.card_metadata) is not CardMetadataV1
            or self.product_family is not ProductFamily.SINGLE
        ):
            raise _fail("public card metadata requires a single")
        _nullable_subtype(self.product_subtype, "productSubtype")
        if self.product_family is not ProductFamily.SEALED and self.product_subtype is not None:
            raise _fail("only sealed public items may carry productSubtype")
        if (
            self.product_family is ProductFamily.SINGLE
            and not (self.canonical_card_name or "").strip()
        ):
            raise _fail("public single requires canonicalCardName")
        if type(self.variants) is not tuple or not self.variants:
            raise _fail("catalog item variants must be a non-empty tuple")
        seen: set[str] = set()
        for variant in self.variants:
            if type(variant) is not CatalogVariantItemV1:
                raise _fail("catalog item variants must contain public variant records")
            if variant.variant_gid in seen:
                raise _fail("catalog item variant GIDs must be unique")
            seen.add(variant.variant_gid)
        ordered_variant_gids = tuple(sorted(seen, key=_variant_gid_sort_key))
        if tuple(variant.variant_gid for variant in self.variants) != ordered_variant_gids:
            raise _fail("catalog item variants must use ascending ProductVariant GID order")

    @classmethod
    def from_product_record(cls, record: CatalogProductRecordV1) -> Self:
        if type(record) is not CatalogProductRecordV1:
            raise _fail("catalog item source must be a product record")
        if not record.publishable or record.product_family is ProductFamily.UNCLASSIFIED:
            raise _fail("catalog item source must be active, published, and classified")
        return cls(
            product_gid=record.product_gid,
            handle=record.handle,
            commercial_title=record.commercial_title,
            canonical_card_name=record.canonical_card_name,
            game=record.game,
            product_family=record.product_family,
            product_subtype=record.product_subtype,
            variants=tuple(
                CatalogVariantItemV1.from_variant_record(variant) for variant in record.variants
            ),
            card_metadata=record.card_metadata,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "canonicalCardName": self.canonical_card_name,
            **({"cardMetadata": self.card_metadata.as_dict()} if self.card_metadata else {}),
            "commercialTitle": self.commercial_title,
            "contractVersion": self.contract_version,
            "game": self.game.value,
            "handle": self.handle,
            "productFamily": self.product_family.value,
            "productGid": self.product_gid,
            "productSubtype": self.product_subtype,
            "variants": [variant.as_dict() for variant in self.variants],
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Self:
        if type(value) is not dict:
            raise _fail("catalog item must be an object")
        fields = cls.FIELDS | ({"cardMetadata"} if "cardMetadata" in value else set())
        _exact_keys(value, fields, "catalog item")
        raw_variants = value["variants"]
        if type(raw_variants) is not list:
            raise _fail("catalog item variants must be an array")
        return cls(
            contract_version=_positive_integer(value["contractVersion"], "contractVersion"),
            product_gid=_gid(value["productGid"], "Product", "productGid"),
            handle=_string(value["handle"], "catalog item handle"),
            commercial_title=_string(value["commercialTitle"], "commercialTitle"),
            canonical_card_name=_nullable_string(
                value["canonicalCardName"], "canonicalCardName", nonempty=True
            ),
            game=_enum(Game, value["game"], "game"),
            product_family=_enum(ProductFamily, value["productFamily"], "productFamily"),
            product_subtype=_nullable_subtype(value["productSubtype"], "productSubtype"),
            variants=tuple(CatalogVariantItemV1.from_dict(item) for item in raw_variants),
            card_metadata=_optional_card_metadata(value),
        )


@dataclass(frozen=True, slots=True)
class CatalogFiltersV1(_JsonDto):
    in_stock: bool | None
    product_subtype: str | None

    FIELDS = frozenset({"inStock", "productSubtype"})

    def __post_init__(self) -> None:
        if self.in_stock is not None:
            _boolean(self.in_stock, "filter inStock")
        _nullable_subtype(self.product_subtype, "filter productSubtype")

    @property
    def nonempty(self) -> bool:
        return self.in_stock is not None or self.product_subtype is not None

    def as_dict(self) -> dict[str, Any]:
        return {"inStock": self.in_stock, "productSubtype": self.product_subtype}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Self:
        if type(value) is not dict:
            raise _fail("filters must be an object")
        _exact_keys(value, cls.FIELDS, "filters")
        in_stock = value["inStock"]
        return cls(
            in_stock=None if in_stock is None else _boolean(in_stock, "filter inStock"),
            product_subtype=_nullable_subtype(value["productSubtype"], "filter productSubtype"),
        )


def _capability_entries(value: Any, context: str) -> tuple[tuple[str, CapabilityState], ...]:
    if type(value) is not tuple:
        raise _fail(f"{context} must be an immutable tuple")
    for entry in value:
        if type(entry) is not tuple or len(entry) != 2:
            raise _fail(f"{context} entries must be pairs")
        name, state = entry
        _string(name, f"{context} name")
        if type(state) is not CapabilityState:
            raise _fail(f"{context} state must be canonical")
    return value


@dataclass(frozen=True, slots=True)
class CapabilityMatrixV1(_JsonDto):
    features: tuple[tuple[str, CapabilityState], ...] = FEATURE_CAPABILITIES_V1
    requests: tuple[tuple[str, CapabilityState], ...] = REQUEST_CAPABILITIES_V1

    FIELDS = frozenset({"features", "requests"})

    def __post_init__(self) -> None:
        features = _capability_entries(self.features, "capability matrix features")
        requests = _capability_entries(self.requests, "capability matrix requests")
        if any(state is CapabilityState.VERIFIED for _, state in (*features, *requests)):
            raise _fail("v1 capabilities cannot claim verified without baseline evidence")
        if self.features != FEATURE_CAPABILITIES_V1 or self.requests != REQUEST_CAPABILITIES_V1:
            raise _fail("capability matrix must equal the frozen v1 matrix")

    def as_dict(self) -> dict[str, Any]:
        return {
            "features": {name: state.value for name, state in self.features},
            "requests": {name: state.value for name, state in self.requests},
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Self:
        if type(value) is not dict:
            raise _fail("capability matrix must be an object")
        _exact_keys(value, cls.FIELDS, "capability matrix")
        expected = cls().as_dict()
        if value != expected:
            raise _fail("capability matrix must equal the frozen v1 matrix")
        return cls()

    def feature_state(self, feature: str) -> CapabilityState:
        _string(feature, "capability feature")
        for name, state in self.features:
            if name == feature:
                return state
        raise _fail("unknown capability feature")

    def request_state(self, game: Game, family: RequestFamily) -> CapabilityState:
        if type(game) is not Game or type(family) is not RequestFamily:
            raise _fail("capability request arguments must be canonical enums")
        key = f"{game.value}/{family.value}"
        return dict(self.requests)[key]


DEFAULT_CAPABILITIES_V1 = CapabilityMatrixV1()


@dataclass(frozen=True, slots=True)
class CatalogRequestV1(_JsonDto):
    game: Game
    product_family: RequestFamily
    query: str | None
    filters: CatalogFiltersV1
    page_size: int
    sort: str = "product_gid_asc"
    contract_version: int = CONTRACT_VERSION

    FIELDS = frozenset(
        {
            "contractVersion",
            "filters",
            "game",
            "pageSize",
            "productFamily",
            "q",
            "sort",
        }
    )

    def __post_init__(self) -> None:
        if type(self.contract_version) is not int or self.contract_version != CONTRACT_VERSION:
            raise _fail("catalog request contractVersion must be 1")
        if type(self.game) is not Game:
            raise _fail("catalog request game must be canonical")
        if type(self.product_family) is not RequestFamily:
            raise _fail("catalog request productFamily must be canonical")
        _nullable_string(self.query, "catalog request q")
        if type(self.filters) is not CatalogFiltersV1:
            raise _fail("catalog request filters must be CatalogFiltersV1")
        if not 1 <= _positive_integer(self.page_size, "pageSize") <= 100:
            raise _fail("pageSize must be between 1 and 100")
        sort = _string(self.sort, "sort")
        if sort != "product_gid_asc":
            raise _fail("sort must be product_gid_asc")
        if (
            self.filters.product_subtype is not None
            and self.product_family is not RequestFamily.SEALED
        ):
            raise _fail("productSubtype filter is only compatible with sealed requests")
        if (
            DEFAULT_CAPABILITIES_V1.request_state(self.game, self.product_family)
            is CapabilityState.UNSUPPORTED
        ):
            raise _fail("game and productFamily request combination is unsupported")

    def as_dict(self) -> dict[str, Any]:
        return {
            "contractVersion": self.contract_version,
            "filters": self.filters.as_dict(),
            "game": self.game.value,
            "pageSize": self.page_size,
            "productFamily": self.product_family.value,
            "q": self.query,
            "sort": self.sort,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Self:
        if type(value) is not dict:
            raise _fail("catalog request must be an object")
        _exact_keys(value, cls.FIELDS, "catalog request")
        return cls(
            contract_version=_positive_integer(value["contractVersion"], "contractVersion"),
            game=_enum(Game, value["game"], "game"),
            product_family=_enum(RequestFamily, value["productFamily"], "request productFamily"),
            query=_nullable_string(value["q"], "catalog request q"),
            filters=CatalogFiltersV1.from_dict(value["filters"]),
            page_size=_positive_integer(value["pageSize"], "pageSize"),
            sort=_string(value["sort"], "sort"),
        )

    def require_executable(self) -> None:
        if self.query not in (None, ""):
            raise _fail("non-empty catalog search is unsupported")
        if self.filters.nonempty:
            raise _fail("non-empty catalog filters are not verified")
        state = DEFAULT_CAPABILITIES_V1.request_state(self.game, self.product_family)
        if state is not CapabilityState.VERIFIED:
            raise _fail("request capability is not verified")
        if DEFAULT_CAPABILITIES_V1.feature_state("catalogOutput") is not CapabilityState.VERIFIED:
            raise _fail("catalog output capability is not verified")


def _request_context_dict(dataset_generation: str, request: CatalogRequestV1) -> dict[str, Any]:
    if type(request) is not CatalogRequestV1:
        raise _fail("request context request must be CatalogRequestV1")
    context = {
        "contractVersion": CONTRACT_VERSION,
        "cursorVersion": 1,
        "datasetGeneration": dataset_generation,
        "endpoint": CatalogEndpoint.CATALOG.value,
        "request": request.as_dict(),
    }
    if request.query not in (None, ""):
        context["searchSemanticsVersion"] = 2
    return context


@dataclass(frozen=True, slots=True)
class CursorContextV1(_JsonDto):
    dataset_generation: str
    endpoint: CatalogEndpoint
    request: CatalogRequestV1
    last_sort_values: tuple[str, ...]
    last_product_gid: str | None
    expires_at: str
    cursor_version: int = 1
    contract_version: int = CONTRACT_VERSION

    FIELDS = frozenset(
        {
            "contractVersion",
            "cursorVersion",
            "datasetGeneration",
            "endpoint",
            "expiresAt",
            "lastProductGid",
            "lastSortValues",
            "request",
        }
    )

    def __post_init__(self) -> None:
        if type(self.contract_version) is not int or self.contract_version != CONTRACT_VERSION:
            raise _fail("cursor context contractVersion must be 1")
        if type(self.cursor_version) is not int or self.cursor_version != 1:
            raise _fail("cursorVersion must be 1")
        _generation(self.dataset_generation, "datasetGeneration")
        if type(self.endpoint) is not CatalogEndpoint:
            raise _fail("cursor endpoint must be canonical")
        if type(self.request) is not CatalogRequestV1:
            raise _fail("cursor context request must be CatalogRequestV1")
        if type(self.last_sort_values) is not tuple or any(
            type(value) is not str for value in self.last_sort_values
        ):
            raise _fail("lastSortValues must be a tuple of strings")
        if self.last_product_gid is not None:
            _gid(self.last_product_gid, "Product", "lastProductGid")
        expected_sort_values = () if self.last_product_gid is None else (self.last_product_gid,)
        if self.last_sort_values != expected_sort_values:
            raise _fail("lastSortValues must exactly bind the final Product GID")
        _expiry_timestamp(self.expires_at, "expiresAt")

    @classmethod
    def from_request(
        cls,
        request: CatalogRequestV1,
        dataset_generation: str,
        *,
        last_product_gid: str | None,
        expires_at: str,
    ) -> Self:
        return cls(
            dataset_generation=dataset_generation,
            endpoint=CatalogEndpoint.CATALOG,
            request=request,
            last_sort_values=(() if last_product_gid is None else (last_product_gid,)),
            last_product_gid=last_product_gid,
            expires_at=expires_at,
        )

    def request_context_dict(self) -> dict[str, Any]:
        return _request_context_dict(self.dataset_generation, self.request)

    def request_context_bytes(self) -> bytes:
        return _canonical_json_bytes(self.request_context_dict())

    @property
    def request_context_sha256(self) -> str:
        return hashlib.sha256(self.request_context_bytes()).hexdigest()

    @property
    def context_sha256(self) -> str:
        return hashlib.sha256(self.to_json_bytes()).hexdigest()

    def as_dict(self) -> dict[str, Any]:
        return {
            "contractVersion": self.contract_version,
            "cursorVersion": self.cursor_version,
            "datasetGeneration": self.dataset_generation,
            "endpoint": self.endpoint.value,
            "expiresAt": self.expires_at,
            "lastProductGid": self.last_product_gid,
            "lastSortValues": list(self.last_sort_values),
            "request": self.request.as_dict(),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Self:
        if type(value) is not dict:
            raise _fail("cursor context must be an object")
        _exact_keys(value, cls.FIELDS, "cursor context")
        last_product_gid = value["lastProductGid"]
        last_sort_values = value["lastSortValues"]
        if type(last_sort_values) is not list:
            raise _fail("lastSortValues must be an array")
        return cls(
            contract_version=_positive_integer(value["contractVersion"], "contractVersion"),
            cursor_version=_positive_integer(value["cursorVersion"], "cursorVersion"),
            dataset_generation=_generation(value["datasetGeneration"], "datasetGeneration"),
            endpoint=_enum(CatalogEndpoint, value["endpoint"], "cursor endpoint"),
            request=CatalogRequestV1.from_dict(value["request"]),
            last_sort_values=tuple(
                _string(item, "lastSortValues item") for item in last_sort_values
            ),
            last_product_gid=(
                None
                if last_product_gid is None
                else _gid(last_product_gid, "Product", "lastProductGid")
            ),
            expires_at=_expiry_timestamp(value["expiresAt"], "expiresAt"),
        )

    def assert_matches(self, request: CatalogRequestV1, dataset_generation: str) -> None:
        if type(request) is not CatalogRequestV1:
            raise _fail("cursor match request must be CatalogRequestV1")
        candidate_generation = _generation(dataset_generation, "cursor match datasetGeneration")
        if self.request != request:
            raise _fail("cursor request context does not match")
        if self.dataset_generation != candidate_generation:
            raise _fail("cursor dataset generation does not match")

    def assert_not_expired(self, now: str) -> None:
        _, now_seconds, now_fraction = _expiry_order_key(now, "current time")
        _, expiry_seconds, expiry_fraction = _expiry_order_key(self.expires_at, "expiresAt")
        fraction_width = max(len(now_fraction), len(expiry_fraction))
        now_fraction_key = now_fraction.ljust(fraction_width, "0")
        expiry_fraction_key = expiry_fraction.ljust(fraction_width, "0")
        if now_seconds > expiry_seconds or (
            now_seconds == expiry_seconds and now_fraction_key >= expiry_fraction_key
        ):
            raise _fail("cursor context has expired")


@dataclass(frozen=True, slots=True)
class CatalogPageV1(_JsonDto):
    dataset_generation: str
    request: CatalogRequestV1
    request_context_sha256: str
    items: tuple[CatalogItemV1, ...]
    returned_product_count: int
    returned_variant_count: int
    has_next_page: bool
    next_cursor_context: CursorContextV1 | None
    contract_version: int = CONTRACT_VERSION

    FIELDS = frozenset(
        {
            "contractVersion",
            "datasetGeneration",
            "hasNextPage",
            "items",
            "nextCursorContext",
            "request",
            "requestContextSha256",
            "returnedProductCount",
            "returnedVariantCount",
        }
    )

    def __post_init__(self) -> None:
        if type(self.contract_version) is not int or self.contract_version != CONTRACT_VERSION:
            raise _fail("catalog page contractVersion must be 1")
        _generation(self.dataset_generation, "datasetGeneration")
        if type(self.request) is not CatalogRequestV1:
            raise _fail("catalog page request must be CatalogRequestV1")
        _sha256(self.request_context_sha256, "requestContextSha256")
        expected_request_digest = hashlib.sha256(
            _canonical_json_bytes(_request_context_dict(self.dataset_generation, self.request))
        ).hexdigest()
        if self.request_context_sha256 != expected_request_digest:
            raise _fail("catalog page requestContextSha256 must bind its request")
        if type(self.items) is not tuple:
            raise _fail("catalog page items must be a tuple")
        if any(type(item) is not CatalogItemV1 for item in self.items):
            raise _fail("catalog page items must contain CatalogItemV1 records")
        if len({item.product_gid for item in self.items}) != len(self.items):
            raise _fail("catalog page Product GIDs must be unique")
        if len({item.handle for item in self.items}) != len(self.items):
            raise _fail("catalog page handles must be unique locators")
        variant_gids = [variant.variant_gid for item in self.items for variant in item.variants]
        if len(set(variant_gids)) != len(variant_gids):
            raise _fail("catalog page Variant GIDs must be unique")
        sorted_gids = sorted((item.product_gid for item in self.items), key=_gid_sort_key)
        if [item.product_gid for item in self.items] != sorted_gids:
            raise _fail("catalog page items must use ascending Product GID order")
        if len(self.items) > self.request.page_size:
            raise _fail("catalog page exceeds the bound pageSize")
        for item in self.items:
            if item.game is not self.request.game:
                raise _fail("catalog page item leaks across the requested game")
            if (
                self.request.product_family is not RequestFamily.ALL
                and item.product_family.value != self.request.product_family.value
            ):
                raise _fail("catalog page item leaks across the requested family")
        if _nonnegative_integer(self.returned_product_count, "returnedProductCount") != len(
            self.items
        ):
            raise _fail("returnedProductCount must equal the Product item count")
        expected_variants = sum(len(item.variants) for item in self.items)
        if (
            _nonnegative_integer(self.returned_variant_count, "returnedVariantCount")
            != expected_variants
        ):
            raise _fail("returnedVariantCount must equal nested variant count")
        _boolean(self.has_next_page, "hasNextPage")
        if self.has_next_page != (self.next_cursor_context is not None):
            raise _fail("hasNextPage must match nextCursorContext presence")
        if self.next_cursor_context is not None:
            self._validate_next_cursor(self.next_cursor_context)

    def _validate_next_cursor(self, cursor: CursorContextV1) -> None:
        if type(cursor) is not CursorContextV1:
            raise _fail("nextCursorContext must be CursorContextV1")
        if not self.items:
            raise _fail("non-terminal catalog page must contain a Product item")
        if cursor.dataset_generation != self.dataset_generation:
            raise _fail("next cursor must bind the page dataset generation")
        if cursor.request != self.request:
            raise _fail("next cursor must preserve the page request")
        if cursor.last_product_gid != self.items[-1].product_gid:
            raise _fail("next cursor must bind the final Product GID")

    def validate_for_context(self, context: CursorContextV1) -> None:
        if type(context) is not CursorContextV1:
            raise _fail("catalog page context must be CursorContextV1")
        if context.dataset_generation != self.dataset_generation:
            raise _fail("catalog page and cursor generations must match")
        if context.request_context_sha256 != self.request_context_sha256:
            raise _fail("catalog page and cursor request contexts must match")
        if context.last_product_gid is not None and self.items:
            if _gid_sort_key(self.items[0].product_gid) <= _gid_sort_key(context.last_product_gid):
                raise _fail("catalog page must begin after the cursor Product GID")
        if self.next_cursor_context is not None and (
            self.next_cursor_context.request_context_dict() != context.request_context_dict()
            or self.next_cursor_context.expires_at != context.expires_at
        ):
            raise _fail("next cursor must preserve the complete request context")

    def as_dict(self) -> dict[str, Any]:
        return {
            "contractVersion": self.contract_version,
            "datasetGeneration": self.dataset_generation,
            "hasNextPage": self.has_next_page,
            "items": [item.as_dict() for item in self.items],
            "nextCursorContext": (
                self.next_cursor_context.as_dict() if self.next_cursor_context else None
            ),
            "request": self.request.as_dict(),
            "requestContextSha256": self.request_context_sha256,
            "returnedProductCount": self.returned_product_count,
            "returnedVariantCount": self.returned_variant_count,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Self:
        if type(value) is not dict:
            raise _fail("catalog page must be an object")
        _exact_keys(value, cls.FIELDS, "catalog page")
        raw_items = value["items"]
        if type(raw_items) is not list:
            raise _fail("catalog page items must be an array")
        raw_cursor = value["nextCursorContext"]
        if raw_cursor is not None and type(raw_cursor) is not dict:
            raise _fail("nextCursorContext must be an object or null")
        return cls(
            contract_version=_positive_integer(value["contractVersion"], "contractVersion"),
            dataset_generation=_generation(value["datasetGeneration"], "datasetGeneration"),
            request=CatalogRequestV1.from_dict(value["request"]),
            request_context_sha256=_sha256(value["requestContextSha256"], "requestContextSha256"),
            items=tuple(CatalogItemV1.from_dict(item) for item in raw_items),
            returned_product_count=_nonnegative_integer(
                value["returnedProductCount"], "returnedProductCount"
            ),
            returned_variant_count=_nonnegative_integer(
                value["returnedVariantCount"], "returnedVariantCount"
            ),
            has_next_page=_boolean(value["hasNextPage"], "hasNextPage"),
            next_cursor_context=(
                None if raw_cursor is None else CursorContextV1.from_dict(raw_cursor)
            ),
        )

    def require_output_capability(self) -> None:
        if DEFAULT_CAPABILITIES_V1.feature_state("catalogOutput") is not CapabilityState.VERIFIED:
            raise _fail("catalog output capability is not verified")


@dataclass(frozen=True, slots=True)
class CatalogErrorV1(_JsonDto):
    code: CatalogErrorCode
    message: str
    field: str | None
    request_context_sha256: str | None
    contract_version: int = CONTRACT_VERSION

    FIELDS = frozenset({"code", "contractVersion", "field", "message", "requestContextSha256"})

    def __post_init__(self) -> None:
        if type(self.contract_version) is not int or self.contract_version != CONTRACT_VERSION:
            raise _fail("catalog error contractVersion must be 1")
        if type(self.code) is not CatalogErrorCode:
            raise _fail("catalog error code must be canonical")
        message = _string(self.message, "catalog error message")
        if message != PUBLIC_ERROR_MESSAGES_V1[self.code]:
            raise _fail("catalog error message must equal the frozen public message")
        field = _nullable_string(self.field, "catalog error field", nonempty=True)
        if field is not None and (len(field) > 128 or _FIELD_PATH_RE.fullmatch(field) is None):
            raise _fail("catalog error field must be a bounded canonical path")
        if self.request_context_sha256 is not None:
            _sha256(self.request_context_sha256, "requestContextSha256")

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "contractVersion": self.contract_version,
            "field": self.field,
            "message": self.message,
            "requestContextSha256": self.request_context_sha256,
        }

    @classmethod
    def for_code(
        cls,
        code: CatalogErrorCode,
        *,
        field: str | None = None,
        request_context_sha256: str | None = None,
    ) -> Self:
        if type(code) is not CatalogErrorCode:
            raise _fail("catalog error code must be canonical")
        return cls(
            code=code,
            message=PUBLIC_ERROR_MESSAGES_V1[code],
            field=field,
            request_context_sha256=request_context_sha256,
        )

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Self:
        if type(value) is not dict:
            raise _fail("catalog error must be an object")
        _exact_keys(value, cls.FIELDS, "catalog error")
        raw_digest = value["requestContextSha256"]
        return cls(
            contract_version=_positive_integer(value["contractVersion"], "contractVersion"),
            code=_enum(CatalogErrorCode, value["code"], "catalog error code"),
            message=_string(value["message"], "catalog error message"),
            field=_nullable_string(value["field"], "catalog error field", nonempty=True),
            request_context_sha256=(
                None if raw_digest is None else _sha256(raw_digest, "requestContextSha256")
            ),
        )


def _fixed_count_tuple(
    value: Any, expected_keys: tuple[str, ...], context: str
) -> tuple[tuple[str, int], ...]:
    if type(value) is not tuple or any(
        type(entry) is not tuple or len(entry) != 2 for entry in value
    ):
        raise _fail(f"{context} must be an immutable count tuple")
    if (
        any(type(entry[0]) is not str for entry in value)
        or tuple(entry[0] for entry in value) != expected_keys
    ):
        raise _fail(f"{context} must contain the frozen keys")
    result: list[tuple[str, int]] = []
    for key, count in value:
        result.append((key, _nonnegative_integer(count, f"{context} value")))
    return tuple(result)


def _count_tuple_from_dict(
    value: Any, expected_keys: tuple[str, ...], context: str
) -> tuple[tuple[str, int], ...]:
    if type(value) is not dict:
        raise _fail(f"{context} must be an object")
    _exact_keys(value, frozenset(expected_keys), context)
    return tuple(
        (key, _nonnegative_integer(value[key], f"{context} value")) for key in expected_keys
    )


@dataclass(frozen=True, slots=True)
class IncrementalLineageV1:
    """Event-derived provenance; snapshot fields still identify the base export."""

    base_dataset_generation: str
    parent_dataset_generation: str
    shop_domain: str
    source_cut_at: str
    event_count: int
    event_lineage_sha256: str

    FIELDS = frozenset(
        {
            "baseDatasetGeneration",
            "parentDatasetGeneration",
            "shopDomain",
            "sourceCutAt",
            "eventCount",
            "eventLineageSha256",
            "syncContractVersion",
        }
    )

    def __post_init__(self) -> None:
        _generation(self.base_dataset_generation, "incremental base generation")
        _generation(self.parent_dataset_generation, "incremental parent generation")
        shop = _string(self.shop_domain, "incremental shop")
        if re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.myshopify\.com", shop) is None:
            raise _fail("incremental shop is invalid")
        _timestamp(self.source_cut_at, "incremental source cut")
        _positive_integer(self.event_count, "incremental event count")
        _sha256(self.event_lineage_sha256, "incremental lineage")

    def as_dict(self) -> dict[str, Any]:
        return {
            "baseDatasetGeneration": self.base_dataset_generation,
            "parentDatasetGeneration": self.parent_dataset_generation,
            "shopDomain": self.shop_domain,
            "sourceCutAt": self.source_cut_at,
            "eventCount": self.event_count,
            "eventLineageSha256": self.event_lineage_sha256,
            "syncContractVersion": 1,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Self:
        if type(value) is not dict:
            raise _fail("incremental lineage must be an object")
        _exact_keys(value, cls.FIELDS, "incremental lineage")
        if type(value["syncContractVersion"]) is not int or value["syncContractVersion"] != 1:
            raise _fail("incremental lineage version is invalid")
        return cls(
            base_dataset_generation=value["baseDatasetGeneration"],
            parent_dataset_generation=value["parentDatasetGeneration"],
            shop_domain=value["shopDomain"],
            source_cut_at=value["sourceCutAt"],
            event_count=value["eventCount"],
            event_lineage_sha256=value["eventLineageSha256"],
        )


@dataclass(frozen=True, slots=True)
class DatasetManifestV1(_JsonDto):
    source_snapshot_manifest_schema_version: int
    source_snapshot_manifest_sha256: str
    source_snapshot_sha256: str
    source_query_sha256: str
    taxonomy_rule_version: str
    catalog_content_sha256: str
    dataset_generation: str
    generated_at: str
    source_product_count: int
    included_product_count: int
    excluded_product_count: int
    source_product_status_counts: tuple[tuple[str, int], ...]
    included_product_status_counts: tuple[tuple[str, int], ...]
    excluded_product_status_counts: tuple[tuple[str, int], ...]
    classified_product_count: int
    unclassified_product_count: int
    product_family_counts: tuple[tuple[str, int], ...]
    source_variant_count: int
    included_variant_count: int
    excluded_variant_count: int
    source_identity_product_count: int
    included_source_identity_product_count: int
    excluded_source_identity_product_count: int
    source_active_online_store_published_product_count: int
    included_active_online_store_published_product_count: int
    excluded_active_online_store_published_product_count: int
    public_item_count: int
    capability_matrix: CapabilityMatrixV1 = DEFAULT_CAPABILITIES_V1
    contract_version: int = CONTRACT_VERSION
    incremental_lineage: IncrementalLineageV1 | None = None

    FIELDS = frozenset(
        {
            "capabilityMatrix",
            "catalogContentSha256",
            "classifiedProductCount",
            "contractVersion",
            "datasetGeneration",
            "excludedActiveOnlineStorePublishedProductCount",
            "excludedProductCount",
            "excludedProductStatusCounts",
            "excludedSourceIdentityProductCount",
            "excludedVariantCount",
            "generatedAt",
            "includedActiveOnlineStorePublishedProductCount",
            "includedProductCount",
            "includedProductStatusCounts",
            "includedSourceIdentityProductCount",
            "includedVariantCount",
            "productFamilyCounts",
            "publicItemCount",
            "sourceActiveOnlineStorePublishedProductCount",
            "sourceIdentityProductCount",
            "sourceProductCount",
            "sourceProductStatusCounts",
            "sourceQuerySha256",
            "sourceSnapshotManifestSchemaVersion",
            "sourceSnapshotManifestSha256",
            "sourceSnapshotSha256",
            "sourceVariantCount",
            "taxonomyRuleVersion",
            "unclassifiedProductCount",
        }
    )

    def __post_init__(self) -> None:
        if self.incremental_lineage is not None:
            if type(self.incremental_lineage) is not IncrementalLineageV1:
                raise _fail("incremental lineage is invalid")
            IncrementalLineageV1.from_dict(self.incremental_lineage.as_dict())
            if (
                _expiry_order_key(self.incremental_lineage.source_cut_at, "source cut")[1:]
                > (_expiry_order_key(self.generated_at, "generatedAt")[1:])
            ):
                raise _fail("incremental source cut exceeds generation time")
        if type(self.contract_version) is not int or self.contract_version != CONTRACT_VERSION:
            raise _fail("dataset manifest contractVersion must be 1")
        if (
            type(self.source_snapshot_manifest_schema_version) is not int
            or self.source_snapshot_manifest_schema_version != SOURCE_MANIFEST_SCHEMA_VERSION
        ):
            raise _fail("source snapshot manifest schema version must be 2")
        _sha256(self.source_snapshot_manifest_sha256, "sourceSnapshotManifestSha256")
        _sha256(self.source_snapshot_sha256, "sourceSnapshotSha256")
        _sha256(self.source_query_sha256, "sourceQuerySha256")
        _rule_version(self.taxonomy_rule_version, "taxonomyRuleVersion")
        _sha256(self.catalog_content_sha256, "catalogContentSha256")
        _generation(self.dataset_generation, "datasetGeneration")
        _timestamp(self.generated_at, "generatedAt")
        for name, count in self._scalar_counts():
            _nonnegative_integer(count, name)
        if self.source_product_count == 0:
            raise _fail("source Product count must be positive")
        if self.included_product_count == 0:
            raise _fail("included Product count must be positive")
        statuses = tuple(PRODUCT_STATUSES)
        source_statuses = _fixed_count_tuple(
            self.source_product_status_counts, statuses, "sourceProductStatusCounts"
        )
        included_statuses = _fixed_count_tuple(
            self.included_product_status_counts,
            statuses,
            "includedProductStatusCounts",
        )
        excluded_statuses = _fixed_count_tuple(
            self.excluded_product_status_counts,
            statuses,
            "excludedProductStatusCounts",
        )
        families = tuple(family.value for family in ProductFamily)
        family_counts = _fixed_count_tuple(
            self.product_family_counts, families, "productFamilyCounts"
        )
        if self.source_product_count != self.included_product_count + self.excluded_product_count:
            raise _fail("source products must equal included plus excluded products")
        if sum(dict(source_statuses).values()) != self.source_product_count:
            raise _fail("source status counts must equal source products")
        if sum(dict(included_statuses).values()) != self.included_product_count:
            raise _fail("included status counts must equal included products")
        if sum(dict(excluded_statuses).values()) != self.excluded_product_count:
            raise _fail("excluded status counts must equal excluded products")
        for status in statuses:
            if dict(source_statuses)[status] != (
                dict(included_statuses)[status] + dict(excluded_statuses)[status]
            ):
                raise _fail("source status counts must equal included plus excluded counts")
        if self.included_product_count != (
            self.classified_product_count + self.unclassified_product_count
        ):
            raise _fail("included products must equal classified plus unclassified products")
        if sum(dict(family_counts).values()) != self.included_product_count:
            raise _fail("product family counts must equal included products")
        if self.unclassified_product_count != dict(family_counts)["unclassified"]:
            raise _fail("unclassified count must equal unclassified family count")
        self._validate_split(
            self.source_variant_count,
            self.included_variant_count,
            self.excluded_variant_count,
            "Variant",
        )
        for scope, variant_count, product_count in (
            ("source", self.source_variant_count, self.source_product_count),
            ("included", self.included_variant_count, self.included_product_count),
            ("excluded", self.excluded_variant_count, self.excluded_product_count),
        ):
            if variant_count < product_count:
                raise _fail(f"{scope} Variant count cannot be less than {scope} Product count")
        self._validate_split(
            self.source_identity_product_count,
            self.included_source_identity_product_count,
            self.excluded_source_identity_product_count,
            "source identity",
        )
        self._validate_split(
            self.source_active_online_store_published_product_count,
            self.included_active_online_store_published_product_count,
            self.excluded_active_online_store_published_product_count,
            "active published Product",
        )
        if self.source_identity_product_count > self.source_product_count:
            raise _fail("source identity count cannot exceed source Product count")
        if self.included_source_identity_product_count > self.included_product_count:
            raise _fail("included identity count cannot exceed included Product count")
        if self.excluded_source_identity_product_count > self.excluded_product_count:
            raise _fail("excluded identity count cannot exceed excluded Product count")
        if (
            self.source_active_online_store_published_product_count
            > dict(source_statuses)[ProductStatus.ACTIVE.value]
        ):
            raise _fail("source active published count cannot exceed ACTIVE status count")
        if (
            self.included_active_online_store_published_product_count
            > dict(included_statuses)[ProductStatus.ACTIVE.value]
        ):
            raise _fail("included active published count cannot exceed ACTIVE status count")
        if (
            self.excluded_active_online_store_published_product_count
            > dict(excluded_statuses)[ProductStatus.ACTIVE.value]
        ):
            raise _fail("excluded active published count cannot exceed ACTIVE status count")
        if self.public_item_count > self.included_active_online_store_published_product_count:
            raise _fail("public item count cannot exceed included active published products")
        if self.public_item_count > self.classified_product_count:
            raise _fail("public item count cannot exceed classified included products")
        minimum_public_items = (
            self.included_active_online_store_published_product_count
            + self.classified_product_count
            - self.included_product_count
        )
        if self.public_item_count < minimum_public_items:
            raise _fail("public item count is below the active-published/classified intersection")
        if type(self.capability_matrix) is not CapabilityMatrixV1:
            raise _fail("capabilityMatrix must be CapabilityMatrixV1")
        if self.dataset_generation != self.expected_generation():
            raise _fail("datasetGeneration does not match content-derived identity")

    def _scalar_counts(self) -> tuple[tuple[str, int], ...]:
        return (
            ("sourceProductCount", self.source_product_count),
            ("includedProductCount", self.included_product_count),
            ("excludedProductCount", self.excluded_product_count),
            ("classifiedProductCount", self.classified_product_count),
            ("unclassifiedProductCount", self.unclassified_product_count),
            ("sourceVariantCount", self.source_variant_count),
            ("includedVariantCount", self.included_variant_count),
            ("excludedVariantCount", self.excluded_variant_count),
            ("sourceIdentityProductCount", self.source_identity_product_count),
            (
                "includedSourceIdentityProductCount",
                self.included_source_identity_product_count,
            ),
            (
                "excludedSourceIdentityProductCount",
                self.excluded_source_identity_product_count,
            ),
            (
                "sourceActiveOnlineStorePublishedProductCount",
                self.source_active_online_store_published_product_count,
            ),
            (
                "includedActiveOnlineStorePublishedProductCount",
                self.included_active_online_store_published_product_count,
            ),
            (
                "excludedActiveOnlineStorePublishedProductCount",
                self.excluded_active_online_store_published_product_count,
            ),
            ("publicItemCount", self.public_item_count),
        )

    @staticmethod
    def _validate_split(source: int, included: int, excluded: int, context: str) -> None:
        if source != included + excluded:
            raise _fail(f"source {context} count must equal included plus excluded")

    def generation_descriptor(self) -> dict[str, Any]:
        if self.incremental_lineage is not None:
            return {
                **self.incremental_lineage.as_dict(),
                "catalogContentSha256": self.catalog_content_sha256,
                "contractVersion": CONTRACT_VERSION,
                "domain": "nla-catalog-incremental-generation-v1",
                "taxonomyRuleVersion": self.taxonomy_rule_version,
            }
        return {
            "catalogContentSha256": self.catalog_content_sha256,
            "contractVersion": CONTRACT_VERSION,
            "domain": "nla-catalog-dataset-generation-v1",
            "sourceQuerySha256": self.source_query_sha256,
            "sourceSnapshotManifestSchemaVersion": self.source_snapshot_manifest_schema_version,
            "sourceSnapshotManifestSha256": self.source_snapshot_manifest_sha256,
            "sourceSnapshotSha256": self.source_snapshot_sha256,
            "taxonomyRuleVersion": self.taxonomy_rule_version,
        }

    def expected_generation(self) -> str:
        digest = hashlib.sha256(_canonical_json_bytes(self.generation_descriptor())).hexdigest()
        return f"sha256:{digest}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "capabilityMatrix": self.capability_matrix.as_dict(),
            **(
                {"incrementalLineage": self.incremental_lineage.as_dict()}
                if self.incremental_lineage is not None
                else {}
            ),
            "catalogContentSha256": self.catalog_content_sha256,
            "classifiedProductCount": self.classified_product_count,
            "contractVersion": self.contract_version,
            "datasetGeneration": self.dataset_generation,
            "excludedActiveOnlineStorePublishedProductCount": (
                self.excluded_active_online_store_published_product_count
            ),
            "excludedProductCount": self.excluded_product_count,
            "excludedProductStatusCounts": dict(self.excluded_product_status_counts),
            "excludedSourceIdentityProductCount": self.excluded_source_identity_product_count,
            "excludedVariantCount": self.excluded_variant_count,
            "generatedAt": self.generated_at,
            "includedActiveOnlineStorePublishedProductCount": (
                self.included_active_online_store_published_product_count
            ),
            "includedProductCount": self.included_product_count,
            "includedProductStatusCounts": dict(self.included_product_status_counts),
            "includedSourceIdentityProductCount": self.included_source_identity_product_count,
            "includedVariantCount": self.included_variant_count,
            "productFamilyCounts": dict(self.product_family_counts),
            "publicItemCount": self.public_item_count,
            "sourceActiveOnlineStorePublishedProductCount": (
                self.source_active_online_store_published_product_count
            ),
            "sourceIdentityProductCount": self.source_identity_product_count,
            "sourceProductCount": self.source_product_count,
            "sourceProductStatusCounts": dict(self.source_product_status_counts),
            "sourceQuerySha256": self.source_query_sha256,
            "sourceSnapshotManifestSchemaVersion": (self.source_snapshot_manifest_schema_version),
            "sourceSnapshotManifestSha256": self.source_snapshot_manifest_sha256,
            "sourceSnapshotSha256": self.source_snapshot_sha256,
            "sourceVariantCount": self.source_variant_count,
            "taxonomyRuleVersion": self.taxonomy_rule_version,
            "unclassifiedProductCount": self.unclassified_product_count,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Self:
        if type(value) is not dict:
            raise _fail("dataset manifest must be an object")
        incremental = "incrementalLineage" in value
        _exact_keys(
            value,
            cls.FIELDS | ({"incrementalLineage"} if incremental else set()),
            "dataset manifest",
        )
        statuses = tuple(PRODUCT_STATUSES)
        families = tuple(family.value for family in ProductFamily)
        kwargs: dict[str, Any] = {
            "incremental_lineage": (
                IncrementalLineageV1.from_dict(value["incrementalLineage"]) if incremental else None
            ),
            "contract_version": _positive_integer(value["contractVersion"], "contractVersion"),
            "source_snapshot_manifest_schema_version": _positive_integer(
                value["sourceSnapshotManifestSchemaVersion"],
                "sourceSnapshotManifestSchemaVersion",
            ),
            "source_snapshot_manifest_sha256": _sha256(
                value["sourceSnapshotManifestSha256"], "sourceSnapshotManifestSha256"
            ),
            "source_snapshot_sha256": _sha256(
                value["sourceSnapshotSha256"], "sourceSnapshotSha256"
            ),
            "source_query_sha256": _sha256(value["sourceQuerySha256"], "sourceQuerySha256"),
            "taxonomy_rule_version": _rule_version(
                value["taxonomyRuleVersion"], "taxonomyRuleVersion"
            ),
            "catalog_content_sha256": _sha256(
                value["catalogContentSha256"], "catalogContentSha256"
            ),
            "dataset_generation": _generation(value["datasetGeneration"], "datasetGeneration"),
            "generated_at": _timestamp(value["generatedAt"], "generatedAt"),
            "source_product_status_counts": _count_tuple_from_dict(
                value["sourceProductStatusCounts"], statuses, "sourceProductStatusCounts"
            ),
            "included_product_status_counts": _count_tuple_from_dict(
                value["includedProductStatusCounts"],
                statuses,
                "includedProductStatusCounts",
            ),
            "excluded_product_status_counts": _count_tuple_from_dict(
                value["excludedProductStatusCounts"],
                statuses,
                "excludedProductStatusCounts",
            ),
            "product_family_counts": _count_tuple_from_dict(
                value["productFamilyCounts"], families, "productFamilyCounts"
            ),
            "capability_matrix": CapabilityMatrixV1.from_dict(value["capabilityMatrix"]),
        }
        scalar_fields = {
            "classified_product_count": "classifiedProductCount",
            "excluded_active_online_store_published_product_count": (
                "excludedActiveOnlineStorePublishedProductCount"
            ),
            "excluded_product_count": "excludedProductCount",
            "excluded_source_identity_product_count": "excludedSourceIdentityProductCount",
            "excluded_variant_count": "excludedVariantCount",
            "included_active_online_store_published_product_count": (
                "includedActiveOnlineStorePublishedProductCount"
            ),
            "included_product_count": "includedProductCount",
            "included_source_identity_product_count": "includedSourceIdentityProductCount",
            "included_variant_count": "includedVariantCount",
            "public_item_count": "publicItemCount",
            "source_active_online_store_published_product_count": (
                "sourceActiveOnlineStorePublishedProductCount"
            ),
            "source_identity_product_count": "sourceIdentityProductCount",
            "source_product_count": "sourceProductCount",
            "source_variant_count": "sourceVariantCount",
            "unclassified_product_count": "unclassifiedProductCount",
        }
        kwargs.update(
            {
                attribute: _nonnegative_integer(value[key], key)
                for attribute, key in scalar_fields.items()
            }
        )
        return cls(**kwargs)

    @classmethod
    def build(
        cls,
        records: tuple[CatalogProductRecordV1, ...],
        *,
        source_manifest: SourceSnapshotManifest,
        source_manifest_bytes: bytes,
        excluded_product_status_counts: tuple[tuple[str, int], ...],
        excluded_variant_count: int,
        excluded_source_identity_product_count: int,
        excluded_active_online_store_published_product_count: int,
    ) -> Self:
        _validate_records(records)
        _validate_source_manifest(source_manifest, source_manifest_bytes)
        statuses = tuple(PRODUCT_STATUSES)
        excluded_statuses = _fixed_count_tuple(
            excluded_product_status_counts, statuses, "excludedProductStatusCounts"
        )
        included_statuses = tuple(
            (
                status,
                sum(record.shopify_status.value == status for record in records),
            )
            for status in statuses
        )
        source_statuses = _fixed_count_tuple(
            source_manifest.product_status_counts, statuses, "source productStatusCounts"
        )
        included = len(records)
        excluded = sum(dict(excluded_statuses).values())
        source_count = source_manifest.source.product_count
        if source_count != included + excluded:
            raise _fail("source snapshot Product count does not reconcile")
        for status in statuses:
            if dict(source_statuses)[status] != (
                dict(included_statuses)[status] + dict(excluded_statuses)[status]
            ):
                raise _fail("source snapshot status counts do not reconcile")
        object_counts = dict(source_manifest.object_counts)
        included_variants = sum(len(record.variants) for record in records)
        excluded_variants = _nonnegative_integer(excluded_variant_count, "excludedVariantCount")
        if object_counts["ProductVariant"] != included_variants + excluded_variants:
            raise _fail("source snapshot ProductVariant count does not reconcile")
        included_identities = sum(record.powertools_source_id is not None for record in records)
        excluded_identities = _nonnegative_integer(
            excluded_source_identity_product_count,
            "excludedSourceIdentityProductCount",
        )
        if source_manifest.source_identity_products != (included_identities + excluded_identities):
            raise _fail("source snapshot identity count does not reconcile")
        included_active_published = sum(record.publishable for record in records)
        excluded_active_published = _nonnegative_integer(
            excluded_active_online_store_published_product_count,
            "excludedActiveOnlineStorePublishedProductCount",
        )
        source_active_published = (
            source_manifest.verified_active_online_store_published_product_count
        )
        if source_active_published != included_active_published + excluded_active_published:
            raise _fail("source snapshot active published count does not reconcile")
        family_counts = tuple(
            (family.value, sum(record.product_family is family for record in records))
            for family in ProductFamily
        )
        unclassified = dict(family_counts)[ProductFamily.UNCLASSIFIED.value]
        public_items = sum(
            record.publishable and record.product_family is not ProductFamily.UNCLASSIFIED
            for record in records
        )
        content_sha = _catalog_content_sha256(records)
        manifest_sha = hashlib.sha256(source_manifest_bytes).hexdigest()
        descriptor = {
            "catalogContentSha256": content_sha,
            "contractVersion": CONTRACT_VERSION,
            "domain": "nla-catalog-dataset-generation-v1",
            "sourceQuerySha256": source_manifest.source.query_sha256,
            "sourceSnapshotManifestSchemaVersion": source_manifest.schema_version,
            "sourceSnapshotManifestSha256": manifest_sha,
            "sourceSnapshotSha256": source_manifest.snapshot_sha256,
            "taxonomyRuleVersion": records[0].classification_rule_version,
        }
        generation = f"sha256:{hashlib.sha256(_canonical_json_bytes(descriptor)).hexdigest()}"
        return cls(
            source_snapshot_manifest_schema_version=source_manifest.schema_version,
            source_snapshot_manifest_sha256=manifest_sha,
            source_snapshot_sha256=source_manifest.snapshot_sha256,
            source_query_sha256=source_manifest.source.query_sha256,
            taxonomy_rule_version=records[0].classification_rule_version,
            catalog_content_sha256=content_sha,
            dataset_generation=generation,
            generated_at=source_manifest.source.completed_at,
            source_product_count=source_count,
            included_product_count=included,
            excluded_product_count=excluded,
            source_product_status_counts=source_statuses,
            included_product_status_counts=included_statuses,
            excluded_product_status_counts=excluded_statuses,
            classified_product_count=included - unclassified,
            unclassified_product_count=unclassified,
            product_family_counts=family_counts,
            source_variant_count=object_counts["ProductVariant"],
            included_variant_count=included_variants,
            excluded_variant_count=excluded_variants,
            source_identity_product_count=source_manifest.source_identity_products,
            included_source_identity_product_count=included_identities,
            excluded_source_identity_product_count=excluded_identities,
            source_active_online_store_published_product_count=source_active_published,
            included_active_online_store_published_product_count=included_active_published,
            excluded_active_online_store_published_product_count=excluded_active_published,
            public_item_count=public_items,
        )

    def validate_records(self, records: tuple[CatalogProductRecordV1, ...]) -> None:
        _validate_records(records)
        if len(records) != self.included_product_count:
            raise _fail("manifest included Product count does not match records")
        if sum(len(record.variants) for record in records) != self.included_variant_count:
            raise _fail("manifest included Variant count does not match records")
        if sum(record.powertools_source_id is not None for record in records) != (
            self.included_source_identity_product_count
        ):
            raise _fail("manifest included source identity count does not match records")
        family_counts = dict(self.product_family_counts)
        for family in ProductFamily:
            if (
                sum(record.product_family is family for record in records)
                != family_counts[family.value]
            ):
                raise _fail("manifest family count does not match records")
        status_counts = dict(self.included_product_status_counts)
        for status in ProductStatus:
            if (
                sum(record.shopify_status is status for record in records)
                != status_counts[status.value]
            ):
                raise _fail("manifest included status count does not match records")
        if sum(record.publishable for record in records) != (
            self.included_active_online_store_published_product_count
        ):
            raise _fail("manifest included active published count does not match records")
        if (
            sum(
                record.publishable and record.product_family is not ProductFamily.UNCLASSIFIED
                for record in records
            )
            != self.public_item_count
        ):
            raise _fail("manifest public item count does not match records")
        if any(
            record.classification_rule_version != self.taxonomy_rule_version for record in records
        ):
            raise _fail("manifest taxonomy rule version does not match records")
        if _catalog_content_sha256(records) != self.catalog_content_sha256:
            raise _fail("manifest catalog content hash does not match records")


def _validate_source_manifest(
    source_manifest: SourceSnapshotManifest, source_manifest_bytes: bytes
) -> None:
    if type(source_manifest) is not SourceSnapshotManifest:
        raise _fail("source manifest must be SourceSnapshotManifest")
    if type(source_manifest.source) is not SourceSnapshotEvidence:
        raise _fail("source manifest evidence must be SourceSnapshotEvidence")
    _load_json_object(source_manifest_bytes, byte_limit=MAX_SOURCE_MANIFEST_BYTES)
    source = source_manifest.source
    for field_name, field_value in (
        ("shopDomain", source.shop_domain),
        ("apiVersion", source.api_version),
        ("operationId", source.operation_id),
        ("status", source.status),
        ("querySha256", source.query_sha256),
        ("onlineStorePublicationGid", source.online_store_publication_gid),
        ("completedAt", source.completed_at),
        ("sourceCodeSha", source.source_code_sha),
    ):
        _string(field_value, f"source evidence {field_name}")
    _boolean(source.partial_data_url_present, "source evidence partialDataUrlPresent")
    for field_name, field_value in (
        ("fileSize", source.file_size),
        ("objectCount", source.object_count),
        ("productCount", source.product_count),
    ):
        _positive_integer(field_value, f"source evidence {field_name}")
    _nonnegative_integer(
        source.expected_active_online_store_published_product_count,
        "source evidence expectedActiveOnlineStorePublishedProductCount",
    )
    try:
        source.validate()
    except (AttributeError, TypeError, ValueError) as exc:
        raise _fail("source snapshot manifest evidence is invalid") from exc
    if (
        type(source_manifest.schema_version) is not int
        or source_manifest.schema_version != SOURCE_MANIFEST_SCHEMA_VERSION
    ):
        raise _fail("source snapshot manifest schema version must be 2")
    _sha256(source_manifest.snapshot_sha256, "source snapshotSha256")
    _sha256(source_manifest.database_sha256, "source databaseSha256")
    if _positive_integer(source_manifest.snapshot_bytes, "source snapshotBytes") != (
        source_manifest.source.file_size
    ):
        raise _fail("source snapshotBytes must equal evidence fileSize")
    if _positive_integer(source_manifest.line_count, "source lineCount") != (
        source_manifest.source.object_count
    ):
        raise _fail("source lineCount must equal evidence objectCount")
    object_counts = _fixed_count_tuple(
        source_manifest.object_counts, tuple(ALLOWED_TYPES), "source objectCounts"
    )
    if sum(dict(object_counts).values()) != source_manifest.line_count:
        raise _fail("source object counts must equal lineCount")
    if dict(object_counts)["Product"] != source_manifest.source.product_count:
        raise _fail("source Product object count must equal evidence productCount")
    if dict(object_counts)["ProductVariant"] < source_manifest.source.product_count:
        raise _fail("source ProductVariant count cannot be less than Product count")
    status_counts = _fixed_count_tuple(
        source_manifest.product_status_counts,
        tuple(PRODUCT_STATUSES),
        "source productStatusCounts",
    )
    if sum(dict(status_counts).values()) != source_manifest.source.product_count:
        raise _fail("source product status counts must equal Product count")
    active_published = _nonnegative_integer(
        source_manifest.verified_active_online_store_published_product_count,
        "source verified active published Product count",
    )
    if active_published != (
        source_manifest.source.expected_active_online_store_published_product_count
    ):
        raise _fail("source verified active published count must equal independent evidence")
    if active_published > dict(status_counts)[ProductStatus.ACTIVE.value]:
        raise _fail("source active published count cannot exceed ACTIVE status count")
    source_identities = _nonnegative_integer(
        source_manifest.source_identity_products, "source identity Product count"
    )
    if source_identities > source_manifest.source.product_count:
        raise _fail("source identity count cannot exceed Product count")
    try:
        expected_bytes = (
            json.dumps(
                source_manifest.as_dict(),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
    except (AttributeError, TypeError, ValueError) as exc:
        raise _fail("source manifest cannot be rendered canonically") from exc
    if source_manifest_bytes != expected_bytes:
        raise _fail("source manifest bytes must equal the canonical #5 renderer")


def _validate_records(records: tuple[CatalogProductRecordV1, ...]) -> None:
    if type(records) is not tuple or not records:
        raise _fail("dataset records must be a non-empty tuple")
    product_gids: set[str] = set()
    handles: set[str] = set()
    variant_gids: set[str] = set()
    inventory_item_gids: set[str] = set()
    rule_version: str | None = None
    for record in records:
        if type(record) is not CatalogProductRecordV1:
            raise _fail("dataset records must contain product records")
        if record.product_gid in product_gids:
            raise _fail("dataset Product GIDs must be unique")
        product_gids.add(record.product_gid)
        if record.handle in handles:
            raise _fail("dataset handles must be unique locators")
        handles.add(record.handle)
        if rule_version is None:
            rule_version = record.classification_rule_version
        elif record.classification_rule_version != rule_version:
            raise _fail("dataset records must share one taxonomy rule version")
        for variant in record.variants:
            if variant.variant_gid in variant_gids:
                raise _fail("dataset ProductVariant GIDs must be unique")
            if variant.inventory_item_gid in inventory_item_gids:
                raise _fail("dataset InventoryItem GIDs must be unique")
            variant_gids.add(variant.variant_gid)
            inventory_item_gids.add(variant.inventory_item_gid)


_CATALOG_CONTENT_PREFIX = (
    b'{"contractVersion":'
    + str(CONTRACT_VERSION).encode("ascii")
    + b',"domain":"nla-catalog-product-records-v1","records":['
)
_CATALOG_CONTENT_SUFFIX = b"]}"


def _catalog_content_sha256(records: tuple[CatalogProductRecordV1, ...]) -> str:
    digest = hashlib.sha256()
    digest.update(_CATALOG_CONTENT_PREFIX)
    separator = b""
    for record in sorted(records, key=lambda item: _gid_sort_key(item.product_gid)):
        digest.update(separator)
        digest.update(_canonical_json_bytes(record.as_dict()))
        separator = b","
    digest.update(_CATALOG_CONTENT_SUFFIX)
    return digest.hexdigest()


_FIELD_DISPOSITIONS_V1 = {
    "CapabilityMatrixV1": {
        "features": FieldDisposition.PROVISIONAL,
        "requests": FieldDisposition.PROVISIONAL,
    },
    "CatalogErrorV1": {
        "code": FieldDisposition.REQUIRED,
        "contractVersion": FieldDisposition.REQUIRED,
        "field": FieldDisposition.NULLABLE,
        "message": FieldDisposition.REQUIRED,
        "requestContextSha256": FieldDisposition.NULLABLE,
    },
    "CatalogFiltersV1": {
        "inStock": FieldDisposition.NULLABLE,
        "productSubtype": FieldDisposition.NULLABLE,
    },
    "CatalogItemV1": {
        "canonicalCardName": FieldDisposition.NULLABLE,
        "commercialTitle": FieldDisposition.REQUIRED,
        "contractVersion": FieldDisposition.REQUIRED,
        "game": FieldDisposition.REQUIRED,
        "handle": FieldDisposition.REQUIRED,
        "productFamily": FieldDisposition.REQUIRED,
        "productGid": FieldDisposition.REQUIRED,
        "productSubtype": FieldDisposition.NULLABLE,
        "variants": FieldDisposition.PROVISIONAL,
    },
    "CatalogPageV1": {
        "contractVersion": FieldDisposition.REQUIRED,
        "datasetGeneration": FieldDisposition.REQUIRED,
        "hasNextPage": FieldDisposition.REQUIRED,
        "items": FieldDisposition.PROVISIONAL,
        "nextCursorContext": FieldDisposition.NULLABLE,
        "request": FieldDisposition.PROVISIONAL,
        "requestContextSha256": FieldDisposition.REQUIRED,
        "returnedProductCount": FieldDisposition.REQUIRED,
        "returnedVariantCount": FieldDisposition.REQUIRED,
    },
    "CatalogProductRecordV1": {
        "canonicalCardName": FieldDisposition.NULLABLE,
        "classificationRuleId": FieldDisposition.NULLABLE,
        "classificationRuleVersion": FieldDisposition.REQUIRED,
        "commercialTitle": FieldDisposition.REQUIRED,
        "contractVersion": FieldDisposition.REQUIRED,
        "game": FieldDisposition.NULLABLE,
        "handle": FieldDisposition.REQUIRED,
        "onlineStorePublished": FieldDisposition.REQUIRED,
        "powerToolsSourceId": FieldDisposition.NULLABLE,
        "productFamily": FieldDisposition.REQUIRED,
        "productGid": FieldDisposition.REQUIRED,
        "productSubtype": FieldDisposition.NULLABLE,
        "shopifyStatus": FieldDisposition.REQUIRED,
        "subtypeReason": FieldDisposition.NULLABLE,
        "subtypeRuleId": FieldDisposition.NULLABLE,
        "syncSourceId": FieldDisposition.NULLABLE,
        "totalInventory": FieldDisposition.REQUIRED,
        "tracksInventory": FieldDisposition.REQUIRED,
        "unclassifiedReason": FieldDisposition.NULLABLE,
        "updatedAt": FieldDisposition.REQUIRED,
        "variants": FieldDisposition.PROVISIONAL,
    },
    "CatalogRequestV1": {
        "contractVersion": FieldDisposition.REQUIRED,
        "filters": FieldDisposition.PROVISIONAL,
        "game": FieldDisposition.REQUIRED,
        "pageSize": FieldDisposition.REQUIRED,
        "productFamily": FieldDisposition.REQUIRED,
        "q": FieldDisposition.NULLABLE,
        "sort": FieldDisposition.REQUIRED,
    },
    "CatalogVariantItemV1": {
        "compareAtPriceText": FieldDisposition.NULLABLE,
        "inventoryPolicy": FieldDisposition.REQUIRED,
        "inventoryQuantity": FieldDisposition.REQUIRED,
        "inventoryTracked": FieldDisposition.REQUIRED,
        "priceText": FieldDisposition.REQUIRED,
        "selectedOptions": FieldDisposition.REQUIRED,
        "title": FieldDisposition.REQUIRED,
        "variantGid": FieldDisposition.REQUIRED,
    },
    "CatalogVariantRecordV1": {
        "barcode": FieldDisposition.NULLABLE,
        "compareAtPriceText": FieldDisposition.NULLABLE,
        "inventoryItemGid": FieldDisposition.REQUIRED,
        "inventoryPolicy": FieldDisposition.REQUIRED,
        "inventoryQuantity": FieldDisposition.REQUIRED,
        "inventoryTracked": FieldDisposition.REQUIRED,
        "priceText": FieldDisposition.REQUIRED,
        "productGid": FieldDisposition.REQUIRED,
        "selectedOptions": FieldDisposition.REQUIRED,
        "sku": FieldDisposition.NULLABLE,
        "title": FieldDisposition.REQUIRED,
        "updatedAt": FieldDisposition.REQUIRED,
        "variantGid": FieldDisposition.REQUIRED,
    },
    "CursorContextV1": {
        "contractVersion": FieldDisposition.REQUIRED,
        "cursorVersion": FieldDisposition.REQUIRED,
        "datasetGeneration": FieldDisposition.REQUIRED,
        "endpoint": FieldDisposition.REQUIRED,
        "expiresAt": FieldDisposition.REQUIRED,
        "lastProductGid": FieldDisposition.NULLABLE,
        "lastSortValues": FieldDisposition.REQUIRED,
        "request": FieldDisposition.PROVISIONAL,
    },
    "DatasetManifestV1": {
        "capabilityMatrix": FieldDisposition.PROVISIONAL,
        "catalogContentSha256": FieldDisposition.REQUIRED,
        "classifiedProductCount": FieldDisposition.REQUIRED,
        "contractVersion": FieldDisposition.REQUIRED,
        "datasetGeneration": FieldDisposition.REQUIRED,
        "excludedActiveOnlineStorePublishedProductCount": FieldDisposition.REQUIRED,
        "excludedProductCount": FieldDisposition.REQUIRED,
        "excludedProductStatusCounts": FieldDisposition.REQUIRED,
        "excludedSourceIdentityProductCount": FieldDisposition.REQUIRED,
        "excludedVariantCount": FieldDisposition.REQUIRED,
        "generatedAt": FieldDisposition.REQUIRED,
        "includedActiveOnlineStorePublishedProductCount": FieldDisposition.REQUIRED,
        "includedProductCount": FieldDisposition.REQUIRED,
        "includedProductStatusCounts": FieldDisposition.REQUIRED,
        "includedSourceIdentityProductCount": FieldDisposition.REQUIRED,
        "includedVariantCount": FieldDisposition.REQUIRED,
        "productFamilyCounts": FieldDisposition.REQUIRED,
        "publicItemCount": FieldDisposition.PROVISIONAL,
        "sourceActiveOnlineStorePublishedProductCount": FieldDisposition.REQUIRED,
        "sourceIdentityProductCount": FieldDisposition.REQUIRED,
        "sourceProductCount": FieldDisposition.REQUIRED,
        "sourceProductStatusCounts": FieldDisposition.REQUIRED,
        "sourceQuerySha256": FieldDisposition.REQUIRED,
        "sourceSnapshotManifestSchemaVersion": FieldDisposition.REQUIRED,
        "sourceSnapshotManifestSha256": FieldDisposition.REQUIRED,
        "sourceSnapshotSha256": FieldDisposition.REQUIRED,
        "sourceVariantCount": FieldDisposition.REQUIRED,
        "taxonomyRuleVersion": FieldDisposition.REQUIRED,
        "unclassifiedProductCount": FieldDisposition.REQUIRED,
    },
    "SelectedOptionV1": {
        "name": FieldDisposition.REQUIRED,
        "value": FieldDisposition.REQUIRED,
    },
}

FIELD_DISPOSITIONS_V1: Mapping[str, Mapping[str, FieldDisposition]] = MappingProxyType(
    {
        dto_name: MappingProxyType(dispositions)
        for dto_name, dispositions in _FIELD_DISPOSITIONS_V1.items()
    }
)


SERIALIZABLE_DTOS_V1: tuple[type[_JsonDto], ...] = (
    SelectedOptionV1,
    CatalogVariantRecordV1,
    CatalogVariantItemV1,
    CatalogProductRecordV1,
    CatalogItemV1,
    CatalogFiltersV1,
    CapabilityMatrixV1,
    CatalogRequestV1,
    CursorContextV1,
    CatalogPageV1,
    CatalogErrorV1,
    DatasetManifestV1,
)


def decode_contract(raw: bytes, dto_type: type[_JsonDto]) -> _JsonDto:
    if not _is_exact_serializable_dto_type(dto_type):
        raise _fail("unsupported runtime contract DTO type")
    return dto_type.from_json_bytes(raw)
