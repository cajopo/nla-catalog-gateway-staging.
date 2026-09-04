"""Framework-independent, read-only synchronization core.

The core stores immutable webhook envelopes, delegates payload interpretation to
callers, validates complete candidate record sets, and atomically switches one
in-memory generation pointer.  It deliberately contains no Shopify transport,
HMAC, webhook registration, queue, database, Bulk execution, or commercial-data
mutation.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from threading import Lock, RLock
from types import MappingProxyType
from typing import Any

from nla_catalog_gateway.bulk import SourceSnapshotEvidence, SourceSnapshotManifest
from nla_catalog_gateway.runtime_contract import (
    CONTRACT_VERSION,
    CatalogProductRecordV1,
    DatasetManifestV1,
    ProductStatus,
)
from nla_catalog_gateway.taxonomy import ProductFamily

SYNC_CONTRACT_VERSION = 1
MAX_WEBHOOK_PAYLOAD_BYTES = 16 * 1024 * 1024
DEFAULT_MAX_INBOX_EVENTS = 10_000
DEFAULT_MAX_INBOX_RETAINED_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_PROCESSING_ATTEMPTS = 3
MAX_TOPIC_BYTES = 255
MAX_TIMESTAMP_BYTES = 64
MAX_GID_BYTES = 512
MAX_TAXONOMY_RULE_VERSION_BYTES = 128

_SHOP_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.myshopify\.com\Z")
_WEBHOOK_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_TOPIC_RE = re.compile(r"[a-z0-9_]+/[a-z0-9_]+\Z")
_API_VERSION_RE = re.compile(r"[0-9]{4}-(?:01|04|07|10)\Z")
_PRODUCT_GID_RE = re.compile(r"gid://shopify/Product/[1-9][0-9]*\Z")
_GID_RE = re.compile(r"gid://shopify/(?:Product|ProductVariant|InventoryItem)/[1-9][0-9]*\Z")
_TAXONOMY_VERSION_RE = re.compile(r"[0-9A-Za-z][0-9A-Za-z._-]*\Z")
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_GENERATION_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_RFC3339_RE = re.compile(
    r"(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})T"
    r"(?P<clock>[0-9]{2}:[0-9]{2}:[0-9]{2})"
    r"(?:\.(?P<fraction>[0-9]+))?(?P<zone>Z|[+-][0-9]{2}:[0-9]{2})\Z"
)


class SyncContractError(ValueError):
    """A value-free failure at the synchronization contract boundary."""


class SyncOperationError(RuntimeError):
    """A value-free operational failure which left the active dataset unchanged."""


class InboxState(StrEnum):
    RECEIVED = "received"
    VALIDATED = "validated"
    FAILED = "failed"
    PROJECTED = "projected"
    RECONCILE_REQUIRED = "reconcile_required"


class EventCategory(StrEnum):
    PRODUCT_CREATE = "product_create"
    PRODUCT_UPDATE = "product_update"
    PRODUCT_DELETE = "product_delete"
    PRODUCT_UNPUBLISH = "product_unpublish"
    INVENTORY_CHANGE = "inventory_change"


class FailureCode(StrEnum):
    VALIDATION_ADAPTER_FAILED = "validation_adapter_failed"
    VALIDATED_EVENT_INVALID = "validated_event_invalid"
    PROJECTION_ADAPTER_FAILED = "projection_adapter_failed"
    CANDIDATE_INVALID = "candidate_invalid"
    CLOCK_FAILED = "clock_failed"
    ACTIVATION_FAILED = "activation_failed"


class ActivationKind(StrEnum):
    EVENT = "event"
    RECONCILIATION = "reconciliation"
    ROLLBACK = "rollback"


_STATE_RANK: Mapping[InboxState, int] = MappingProxyType(
    {
        InboxState.RECEIVED: 0,
        InboxState.VALIDATED: 1,
        InboxState.FAILED: 2,
        InboxState.PROJECTED: 3,
        InboxState.RECONCILE_REQUIRED: 4,
    }
)

SUPPORTED_TOPIC_CATEGORIES: Mapping[str, frozenset[EventCategory]] = MappingProxyType(
    {
        "inventory_levels/update": frozenset({EventCategory.INVENTORY_CHANGE}),
        "products/create": frozenset({EventCategory.PRODUCT_CREATE}),
        "products/delete": frozenset({EventCategory.PRODUCT_DELETE}),
        "products/update": frozenset(
            {EventCategory.PRODUCT_UPDATE, EventCategory.PRODUCT_UNPUBLISH}
        ),
    }
)


def _error(message: str) -> SyncContractError:
    return SyncContractError(message)


def _text(
    value: Any,
    pattern: re.Pattern[str],
    context: str,
    *,
    max_bytes: int | None = None,
) -> str:
    if (
        type(value) is not str
        or (max_bytes is not None and len(value) > max_bytes)
        or pattern.fullmatch(value) is None
    ):
        raise _error(f"{context} is invalid")
    return value


def _taxonomy_version(value: Any, context: str) -> str:
    return _text(
        value,
        _TAXONOMY_VERSION_RE,
        context,
        max_bytes=MAX_TAXONOMY_RULE_VERSION_BYTES,
    )


def _positive_integer(value: Any, context: str) -> int:
    if type(value) is not int or value <= 0:
        raise _error(f"{context} must be a positive integer")
    return value


def _nonnegative_integer(value: Any, context: str) -> int:
    if type(value) is not int or value < 0:
        raise _error(f"{context} must be a non-negative integer")
    return value


def _canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise _error("synchronization material is not canonically serializable") from None


def _timestamp_key(value: Any, context: str) -> tuple[str, int, str]:
    if type(value) is not str or len(value) > MAX_TIMESTAMP_BYTES:
        raise _error(f"{context} is invalid")
    match = _RFC3339_RE.fullmatch(value)
    if match is None or match.group("zone") == "-00:00":
        raise _error(f"{context} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise _error(f"{context} is invalid") from None
    zone = match.group("zone")
    if zone == "Z":
        offset_seconds = 0
    else:
        sign = 1 if zone[0] == "+" else -1
        offset_seconds = sign * (int(zone[1:3]) * 3_600 + int(zone[4:6]) * 60)
    whole_seconds = (
        parsed.toordinal() * 86_400
        + parsed.hour * 3_600
        + parsed.minute * 60
        + parsed.second
        - offset_seconds
    )
    fraction = (match.group("fraction") or "").rstrip("0")
    return value, whole_seconds, fraction


def _elapsed_whole_seconds(start: tuple[str, int, str], end: tuple[str, int, str]) -> int:
    elapsed = end[1] - start[1]
    if end[2] < start[2]:
        elapsed -= 1
    return max(0, elapsed)


def _system_clock() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _product_gid_key(value: str) -> tuple[int, str]:
    digits = value.rsplit("/", 1)[1]
    return len(digits), digits


def _copy_records(
    records: tuple[CatalogProductRecordV1, ...],
) -> tuple[CatalogProductRecordV1, ...]:
    if type(records) is not tuple or not records:
        raise _error("candidate records must be a non-empty tuple")
    copied: list[CatalogProductRecordV1] = []
    try:
        for record in records:
            if type(record) is not CatalogProductRecordV1:
                raise _error("candidate records must contain canonical product records")
            copied.append(CatalogProductRecordV1.from_json_bytes(record.to_json_bytes()))
    except SyncContractError:
        raise
    except Exception:
        raise _error("candidate product record is invalid") from None
    result = tuple(copied)
    _validate_record_set(result)
    return result


def _validate_record_set(records: tuple[CatalogProductRecordV1, ...]) -> None:
    product_gids: set[str] = set()
    handles: set[str] = set()
    variant_gids: set[str] = set()
    inventory_item_gids: set[str] = set()
    source_ids: set[str] = set()
    taxonomy_version = _taxonomy_version(
        records[0].classification_rule_version, "taxonomy rule version"
    )
    for record in records:
        _text(record.product_gid, _GID_RE, "Product GID", max_bytes=MAX_GID_BYTES)
        _timestamp_key(record.updated_at, "Product update timestamp")
        if record.product_gid in product_gids or record.handle in handles:
            raise _error("candidate Product identities or handles are not unique")
        if (
            _taxonomy_version(record.classification_rule_version, "taxonomy rule version")
            != taxonomy_version
        ):
            raise _error("candidate records do not share one taxonomy rule version")
        source_id = record.powertools_source_id
        if source_id is not None and source_id in source_ids:
            raise _error("candidate source identities are not unique")
        product_gids.add(record.product_gid)
        handles.add(record.handle)
        if source_id is not None:
            source_ids.add(source_id)
        for variant in record.variants:
            _text(variant.variant_gid, _GID_RE, "Variant GID", max_bytes=MAX_GID_BYTES)
            _text(
                variant.inventory_item_gid,
                _GID_RE,
                "InventoryItem GID",
                max_bytes=MAX_GID_BYTES,
            )
            _timestamp_key(variant.updated_at, "Variant update timestamp")
            if (
                variant.variant_gid in variant_gids
                or variant.inventory_item_gid in inventory_item_gids
            ):
                raise _error("candidate Variant identities are not unique")
            variant_gids.add(variant.variant_gid)
            inventory_item_gids.add(variant.inventory_item_gid)


def _catalog_content_sha256(records: tuple[CatalogProductRecordV1, ...]) -> str:
    ordered = sorted(records, key=lambda record: _product_gid_key(record.product_gid))
    material = {
        "contractVersion": CONTRACT_VERSION,
        "domain": "nla-catalog-product-records-v1",
        "records": [record.as_dict() for record in ordered],
    }
    return hashlib.sha256(_canonical_json_bytes(material)).hexdigest()


def _record_counts(
    records: tuple[CatalogProductRecordV1, ...],
) -> tuple[
    tuple[tuple[str, int], ...],
    tuple[tuple[str, int], ...],
    int,
    int,
    int,
]:
    status_counts = tuple(
        (status.value, sum(record.shopify_status is status for record in records))
        for status in ProductStatus
    )
    family_counts = tuple(
        (family.value, sum(record.product_family is family for record in records))
        for family in ProductFamily
    )
    variant_count = sum(len(record.variants) for record in records)
    identity_count = sum(record.powertools_source_id is not None for record in records)
    public_count = sum(
        record.publishable and record.product_family is not ProductFamily.UNCLASSIFIED
        for record in records
    )
    return status_counts, family_counts, variant_count, identity_count, public_count


class WebhookKey(tuple[str, str]):
    """A validated, genuinely immutable public webhook key."""

    __slots__ = ()

    def __new__(cls, shop_domain: str, webhook_id: str) -> WebhookKey:
        safe_shop = _text(shop_domain, _SHOP_RE, "shop domain")
        safe_id = _text(webhook_id, _WEBHOOK_ID_RE, "webhook ID")
        return tuple.__new__(cls, (safe_shop, safe_id))

    @property
    def shop_domain(self) -> str:
        return self[0]

    @property
    def webhook_id(self) -> str:
        return self[1]


@dataclass(frozen=True, slots=True, repr=False)
class RawWebhookEnvelope:
    shop_domain: str
    webhook_id: str
    topic: str
    api_version: str
    received_at: str
    payload: bytes
    payload_sha256: str = ""

    def __post_init__(self) -> None:
        _text(self.shop_domain, _SHOP_RE, "shop domain")
        _text(self.webhook_id, _WEBHOOK_ID_RE, "webhook ID")
        _text(self.topic, _TOPIC_RE, "webhook topic", max_bytes=MAX_TOPIC_BYTES)
        _text(self.api_version, _API_VERSION_RE, "API version")
        _timestamp_key(self.received_at, "received timestamp")
        if type(self.payload) is not bytes or not self.payload:
            raise _error("webhook payload must be non-empty bytes")
        if len(self.payload) > MAX_WEBHOOK_PAYLOAD_BYTES:
            raise _error("webhook payload exceeds the byte limit")
        digest = hashlib.sha256(self.payload).hexdigest()
        if self.payload_sha256 not in ("", digest):
            raise _error("webhook payload hash does not match the raw payload")
        object.__setattr__(self, "payload_sha256", digest)

    @property
    def key(self) -> WebhookKey:
        return WebhookKey(self.shop_domain, self.webhook_id)


def _retained_envelope_bytes(envelope: RawWebhookEnvelope) -> int:
    return len(envelope.payload) + sum(
        len(value.encode("utf-8"))
        for value in (
            envelope.shop_domain,
            envelope.webhook_id,
            envelope.topic,
            envelope.api_version,
            envelope.received_at,
            envelope.payload_sha256,
        )
    )


@dataclass(frozen=True, slots=True)
class ValidatedWebhookEvent:
    shop_domain: str
    webhook_id: str
    payload_sha256: str
    category: EventCategory
    product_gid: str
    source_updated_at: str

    def __post_init__(self) -> None:
        _text(self.shop_domain, _SHOP_RE, "validated shop domain")
        _text(self.webhook_id, _WEBHOOK_ID_RE, "validated webhook ID")
        _text(self.payload_sha256, _SHA256_RE, "validated payload hash")
        if type(self.category) is not EventCategory:
            raise _error("validated event category is invalid")
        _text(
            self.product_gid,
            _PRODUCT_GID_RE,
            "validated Product GID",
            max_bytes=MAX_GID_BYTES,
        )
        _timestamp_key(self.source_updated_at, "source update timestamp")


@dataclass(frozen=True, slots=True, repr=False)
class ProjectionContext:
    dataset_generation: str
    base_dataset_generation: str
    taxonomy_rule_version: str
    records: tuple[CatalogProductRecordV1, ...]

    def __post_init__(self) -> None:
        _text(self.dataset_generation, _GENERATION_RE, "dataset generation")
        _text(self.base_dataset_generation, _GENERATION_RE, "base dataset generation")
        _taxonomy_version(self.taxonomy_rule_version, "taxonomy rule version")
        _copy_records(self.records)


@dataclass(frozen=True, slots=True, init=False, repr=False)
class _SyncGeneration:
    base_manifest: DatasetManifestV1
    records: tuple[CatalogProductRecordV1, ...]
    shop_domain: str
    source_cut_at: str
    dataset_generation: str
    base_dataset_generation: str
    parent_dataset_generation: str | None
    catalog_content_sha256: str
    taxonomy_rule_version: str
    built_at: str
    event_lineage_sha256: str
    last_event_identity_sha256: str | None
    applied_event_count: int
    product_status_counts: tuple[tuple[str, int], ...]
    product_family_counts: tuple[tuple[str, int], ...]
    product_count: int
    variant_count: int
    source_identity_product_count: int
    public_item_count: int


@dataclass(frozen=True, slots=True, repr=False)
class GenerationView:
    shop_domain: str
    source_cut_at: str
    dataset_generation: str
    base_dataset_generation: str
    parent_dataset_generation: str | None
    catalog_content_sha256: str
    taxonomy_rule_version: str
    built_at: str
    event_lineage_sha256: str
    last_event_identity_sha256: str | None
    applied_event_count: int
    product_status_counts: tuple[tuple[str, int], ...]
    product_family_counts: tuple[tuple[str, int], ...]
    product_count: int
    variant_count: int
    source_identity_product_count: int
    public_item_count: int
    records: tuple[CatalogProductRecordV1, ...]


@dataclass(frozen=True, slots=True)
class EventStatus:
    state: InboxState
    delivery_attempts: int
    processing_attempts: int
    category: EventCategory | None
    failure_code: FailureCode | None
    projected_generation: str | None
    dead_letter: bool


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    key: WebhookKey
    status: EventStatus
    duplicate: bool
    conflict: bool


@dataclass(frozen=True, slots=True)
class SyncMetrics:
    observed_at: str
    shop_domain: str
    source_cut_at: str
    dataset_version: str
    built_at: str
    taxonomy_rule_version: str
    unclassified_product_count: int
    last_event_at: str | None
    last_projected_at: str | None
    lag_seconds: int
    stale_after_seconds: int
    stale: bool
    projection_paused: bool
    unresolved_failed_events: int
    unresolved_reconciliation_events: int
    dead_letter_events: int
    inbox_events: int
    inbox_retained_bytes: int
    deliveries_total: int
    unique_events_total: int
    duplicate_deliveries_total: int
    conflicting_deliveries_total: int
    projected_events_total: int
    failed_attempts_total: int
    reconciliation_decisions_total: int
    activations_total: int
    rollbacks_total: int
    reconciliation_installs_total: int


@dataclass(frozen=True, slots=True)
class SyncEventReport:
    key: WebhookKey
    topic: str
    state: InboxState
    delivery_attempts: int
    processing_attempts: int
    category: EventCategory | None
    failure_code: FailureCode | None
    dead_letter: bool


@dataclass(frozen=True, slots=True, repr=False)
class _InboxEntry:
    envelope: RawWebhookEnvelope
    state: InboxState
    delivery_attempts: int
    processing_attempts: int
    category: EventCategory | None
    failure_code: FailureCode | None
    projected_generation: str | None
    last_received_at: str
    source_updated_at: str | None
    last_delivery_sequence: int


@dataclass(frozen=True, slots=True)
class _AppliedOrder:
    timestamp_key: tuple[str, int, str]
    event_identity_sha256: str


@dataclass(frozen=True, slots=True, repr=False)
class _GenerationSlot:
    generation: _SyncGeneration
    applied_orders: Mapping[tuple[str, str], _AppliedOrder]


@dataclass(frozen=True, slots=True, repr=False)
class _GenerationPair:
    active: _GenerationSlot
    previous: _GenerationSlot | None


class _ProjectionNeedsReconciliation(Exception):
    pass


_InboxKey = tuple[str, str]


def _inbox_key(shop_domain: str, webhook_id: str) -> _InboxKey:
    return (
        _text(shop_domain, _SHOP_RE, "shop domain"),
        _text(webhook_id, _WEBHOOK_ID_RE, "webhook ID"),
    )


def _copy_manifest(manifest: DatasetManifestV1) -> DatasetManifestV1:
    if type(manifest) is not DatasetManifestV1:
        raise _error("runtime manifest must be canonical DatasetManifestV1")
    try:
        copied = DatasetManifestV1.from_json_bytes(manifest.to_json_bytes())
    except Exception:
        raise _error("runtime manifest is invalid") from None
    _taxonomy_version(copied.taxonomy_rule_version, "manifest taxonomy rule version")
    _timestamp_key(copied.generated_at, "manifest generation timestamp")
    return copied


def _copy_source_manifest(
    source_manifest: SourceSnapshotManifest,
    source_manifest_bytes: bytes,
) -> tuple[SourceSnapshotManifest, bytes]:
    if (
        type(source_manifest) is not SourceSnapshotManifest
        or type(source_manifest.source) is not SourceSnapshotEvidence
        or type(source_manifest_bytes) is not bytes
    ):
        raise _error("source snapshot evidence must be canonical")
    try:
        source = source_manifest.source
        copied_source = SourceSnapshotEvidence(
            shop_domain=source.shop_domain,
            api_version=source.api_version,
            operation_id=source.operation_id,
            status=source.status,
            partial_data_url_present=source.partial_data_url_present,
            file_size=source.file_size,
            object_count=source.object_count,
            product_count=source.product_count,
            expected_active_online_store_published_product_count=(
                source.expected_active_online_store_published_product_count
            ),
            query_sha256=source.query_sha256,
            online_store_publication_gid=source.online_store_publication_gid,
            completed_at=source.completed_at,
            source_code_sha=source.source_code_sha,
        )
        copied_manifest = SourceSnapshotManifest(
            schema_version=source_manifest.schema_version,
            source=copied_source,
            snapshot_sha256=source_manifest.snapshot_sha256,
            database_sha256=source_manifest.database_sha256,
            snapshot_bytes=source_manifest.snapshot_bytes,
            line_count=source_manifest.line_count,
            object_counts=tuple((name, count) for name, count in source_manifest.object_counts),
            product_status_counts=tuple(
                (status, count) for status, count in source_manifest.product_status_counts
            ),
            verified_active_online_store_published_product_count=(
                source_manifest.verified_active_online_store_published_product_count
            ),
            source_identity_products=source_manifest.source_identity_products,
        )
    except Exception:
        raise _error("source snapshot evidence is invalid") from None
    return copied_manifest, bytes(source_manifest_bytes)


def _new_generation(**values: Any) -> _SyncGeneration:
    generation = object.__new__(_SyncGeneration)
    for field_name, field_value in values.items():
        object.__setattr__(generation, field_name, field_value)
    _validate_generation(generation)
    return generation


def _initial_generation(
    manifest: DatasetManifestV1,
    records: tuple[CatalogProductRecordV1, ...],
    *,
    source_manifest: SourceSnapshotManifest,
    source_manifest_bytes: bytes,
    shop_domain: str,
    source_cut_at: str,
) -> _SyncGeneration:
    safe_shop = _text(shop_domain, _SHOP_RE, "dataset shop domain")
    _timestamp_key(source_cut_at, "source cut timestamp")
    safe_source_manifest, safe_source_manifest_bytes = _copy_source_manifest(
        source_manifest, source_manifest_bytes
    )
    safe_manifest = _copy_manifest(manifest)
    safe_records = _copy_records(records)
    try:
        rebuilt_manifest = DatasetManifestV1.build(
            safe_records,
            source_manifest=safe_source_manifest,
            source_manifest_bytes=safe_source_manifest_bytes,
            excluded_product_status_counts=safe_manifest.excluded_product_status_counts,
            excluded_variant_count=safe_manifest.excluded_variant_count,
            excluded_source_identity_product_count=(
                safe_manifest.excluded_source_identity_product_count
            ),
            excluded_active_online_store_published_product_count=(
                safe_manifest.excluded_active_online_store_published_product_count
            ),
        )
    except Exception:
        raise _error("source snapshot does not validate the runtime candidate") from None
    source_shop = _text(
        safe_source_manifest.source.shop_domain,
        _SHOP_RE,
        "source snapshot shop domain",
    )
    source_completed_at = safe_source_manifest.source.completed_at
    _timestamp_key(source_completed_at, "source snapshot completion timestamp")
    if source_shop != safe_shop:
        raise _error("source snapshot shop does not match the dataset")
    if source_cut_at != source_completed_at:
        raise _error("source cut must match the source snapshot completion timestamp")
    if rebuilt_manifest.to_json_bytes() != safe_manifest.to_json_bytes():
        raise _error("runtime manifest is not bound to the source snapshot evidence")
    status_counts, family_counts, variants, identities, public = _record_counts(safe_records)
    seed = hashlib.sha256(
        _canonical_json_bytes(
            {
                "baseDatasetGeneration": safe_manifest.dataset_generation,
                "domain": "nla-catalog-sync-event-lineage-v1",
                "syncContractVersion": SYNC_CONTRACT_VERSION,
            }
        )
    ).hexdigest()
    return _new_generation(
        base_manifest=safe_manifest,
        records=safe_records,
        shop_domain=safe_shop,
        source_cut_at=source_cut_at,
        dataset_generation=safe_manifest.dataset_generation,
        base_dataset_generation=safe_manifest.dataset_generation,
        parent_dataset_generation=None,
        catalog_content_sha256=safe_manifest.catalog_content_sha256,
        taxonomy_rule_version=safe_manifest.taxonomy_rule_version,
        built_at=safe_manifest.generated_at,
        event_lineage_sha256=seed,
        last_event_identity_sha256=None,
        applied_event_count=0,
        product_status_counts=status_counts,
        product_family_counts=family_counts,
        product_count=len(safe_records),
        variant_count=variants,
        source_identity_product_count=identities,
        public_item_count=public,
    )


def _generation_descriptor(generation: _SyncGeneration) -> dict[str, Any]:
    return {
        "baseDatasetGeneration": generation.base_dataset_generation,
        "catalogContentSha256": generation.catalog_content_sha256,
        "contractVersion": CONTRACT_VERSION,
        "domain": "nla-catalog-incremental-generation-v1",
        "eventCount": generation.applied_event_count,
        "eventLineageSha256": generation.event_lineage_sha256,
        "parentDatasetGeneration": generation.parent_dataset_generation,
        "shopDomain": generation.shop_domain,
        "sourceCutAt": generation.source_cut_at,
        "syncContractVersion": SYNC_CONTRACT_VERSION,
        "taxonomyRuleVersion": generation.taxonomy_rule_version,
    }


def _validate_generation(generation: _SyncGeneration) -> None:
    if type(generation) is not _SyncGeneration:
        raise _error("sync generation is invalid")
    manifest = _copy_manifest(generation.base_manifest)
    records = _copy_records(generation.records)
    _text(generation.shop_domain, _SHOP_RE, "generation shop domain")
    source_cut_key = _timestamp_key(generation.source_cut_at, "generation source cut")
    _text(generation.dataset_generation, _GENERATION_RE, "dataset generation")
    _text(generation.base_dataset_generation, _GENERATION_RE, "base dataset generation")
    _text(generation.catalog_content_sha256, _SHA256_RE, "catalog content hash")
    _text(generation.event_lineage_sha256, _SHA256_RE, "event lineage hash")
    built_key = _timestamp_key(generation.built_at, "generation build timestamp")
    if (source_cut_key[1], source_cut_key[2]) > (built_key[1], built_key[2]):
        raise _error("generation source cut cannot be later than its build timestamp")
    if any((_record_latest_key(record)[1:]) > source_cut_key[1:] for record in records):
        raise _error("generation record timestamp exceeds its source cut")
    count = _nonnegative_integer(generation.applied_event_count, "applied event count")
    if generation.base_dataset_generation != manifest.dataset_generation:
        raise _error("sync generation base does not match its runtime manifest")
    if generation.taxonomy_rule_version != manifest.taxonomy_rule_version:
        raise _error("sync generation taxonomy does not match its runtime manifest")
    if _catalog_content_sha256(records) != generation.catalog_content_sha256:
        raise _error("sync generation content hash does not match its records")
    status_counts, family_counts, variants, identities, public = _record_counts(records)
    if (
        generation.product_status_counts != status_counts
        or generation.product_family_counts != family_counts
        or generation.product_count != len(records)
        or generation.variant_count != variants
        or generation.source_identity_product_count != identities
        or generation.public_item_count != public
    ):
        raise _error("sync generation counts do not match its records")
    if count == 0:
        if (
            generation.parent_dataset_generation is not None
            or generation.last_event_identity_sha256 is not None
            or generation.dataset_generation != manifest.dataset_generation
            or generation.catalog_content_sha256 != manifest.catalog_content_sha256
        ):
            raise _error("initial sync generation does not match its runtime manifest")
        try:
            manifest.validate_records(records)
        except Exception:
            raise _error("initial sync generation records are invalid") from None
        return
    if generation.parent_dataset_generation is None:
        raise _error("incremental generation requires a parent generation")
    _text(generation.parent_dataset_generation, _GENERATION_RE, "parent dataset generation")
    _text(generation.last_event_identity_sha256, _SHA256_RE, "last event identity hash")
    expected = (
        "sha256:"
        + hashlib.sha256(_canonical_json_bytes(_generation_descriptor(generation))).hexdigest()
    )
    if generation.dataset_generation != expected:
        raise _error("incremental dataset generation does not match its descriptor")


def _event_identity_sha256(envelope: RawWebhookEnvelope, event: ValidatedWebhookEvent) -> str:
    material = {
        "apiVersion": envelope.api_version,
        "category": event.category.value,
        "domain": "nla-catalog-sync-event-identity-v1",
        "payloadSha256": envelope.payload_sha256,
        "productGid": event.product_gid,
        "shopDomain": envelope.shop_domain,
        "sourceUpdatedAt": event.source_updated_at,
        "syncContractVersion": SYNC_CONTRACT_VERSION,
        "topic": envelope.topic,
        "webhookId": envelope.webhook_id,
    }
    return hashlib.sha256(_canonical_json_bytes(material)).hexdigest()


def _record_latest_key(record: CatalogProductRecordV1) -> tuple[str, int, str]:
    return max(
        (
            _timestamp_key(record.updated_at, "record update timestamp"),
            *(
                _timestamp_key(variant.updated_at, "Variant update timestamp")
                for variant in record.variants
            ),
        ),
        key=lambda item: (item[1], item[2]),
    )


def _validate_projection_delta(
    before: tuple[CatalogProductRecordV1, ...],
    after: tuple[CatalogProductRecordV1, ...],
    event: ValidatedWebhookEvent,
) -> None:
    before_by_gid = {record.product_gid: record for record in before}
    after_by_gid = {record.product_gid: record for record in after}
    target = event.product_gid
    before_keys = set(before_by_gid)
    after_keys = set(after_by_gid)
    if event.category is EventCategory.PRODUCT_CREATE:
        valid_shape = (
            target not in before_keys
            and target in after_keys
            and after_keys - before_keys == {target}
            and not (before_keys - after_keys)
        )
    elif event.category is EventCategory.PRODUCT_DELETE:
        valid_shape = (
            target in before_keys
            and target not in after_keys
            and before_keys - after_keys == {target}
            and not (after_keys - before_keys)
        )
    else:
        valid_shape = target in before_keys and target in after_keys and before_keys == after_keys
    if not valid_shape:
        raise _ProjectionNeedsReconciliation
    common = before_keys & after_keys
    for product_gid in common - {target}:
        if before_by_gid[product_gid].to_json_bytes() != after_by_gid[product_gid].to_json_bytes():
            raise _ProjectionNeedsReconciliation
    if (
        event.category is EventCategory.PRODUCT_UNPUBLISH
        and after_by_gid[target].online_store_published
    ):
        raise _ProjectionNeedsReconciliation
    if event.category is EventCategory.INVENTORY_CHANGE and _non_inventory_material(
        before_by_gid[target]
    ) != _non_inventory_material(after_by_gid[target]):
        raise _ProjectionNeedsReconciliation
    if event.category is not EventCategory.PRODUCT_DELETE:
        source_key = _timestamp_key(event.source_updated_at, "source update timestamp")
        latest_after = _record_latest_key(after_by_gid[target])
        if (latest_after[1], latest_after[2]) < (source_key[1], source_key[2]):
            raise _ProjectionNeedsReconciliation


def _non_inventory_material(record: CatalogProductRecordV1) -> bytes:
    material = record.as_dict()
    material.pop("totalInventory")
    material.pop("tracksInventory")
    material.pop("updatedAt")
    variants = material.pop("variants")
    material["variants"] = [
        {
            key: value
            for key, value in variant.items()
            if key not in {"inventoryQuantity", "inventoryTracked", "updatedAt"}
        }
        for variant in variants
    ]
    return _canonical_json_bytes(material)


def _advance_generation(
    parent: _SyncGeneration,
    records: tuple[CatalogProductRecordV1, ...],
    envelope: RawWebhookEnvelope,
    event: ValidatedWebhookEvent,
    built_at: str,
) -> _SyncGeneration:
    _validate_generation(parent)
    if envelope.shop_domain != parent.shop_domain or event.shop_domain != parent.shop_domain:
        raise _error("incremental event shop does not match the dataset")
    built_key = _timestamp_key(built_at, "generation build timestamp")
    parent_built_key = _timestamp_key(parent.built_at, "parent build timestamp")
    if (built_key[1], built_key[2]) < (parent_built_key[1], parent_built_key[2]):
        raise _error("generation build timestamp cannot move backwards")
    safe_records = _copy_records(records)
    if safe_records[0].classification_rule_version != parent.taxonomy_rule_version:
        raise _ProjectionNeedsReconciliation
    _validate_projection_delta(parent.records, safe_records, event)
    event_identity = _event_identity_sha256(envelope, event)
    lineage = hashlib.sha256(
        _canonical_json_bytes(
            {
                "domain": "nla-catalog-sync-event-lineage-v1",
                "eventIdentitySha256": event_identity,
                "previousLineageSha256": parent.event_lineage_sha256,
                "syncContractVersion": SYNC_CONTRACT_VERSION,
            }
        )
    ).hexdigest()
    status_counts, family_counts, variants, identities, public = _record_counts(safe_records)
    event_source_key = _timestamp_key(event.source_updated_at, "event source timestamp")
    parent_cut_key = _timestamp_key(parent.source_cut_at, "parent source cut")
    source_cut_at = (
        event.source_updated_at
        if (event_source_key[1], event_source_key[2]) > (parent_cut_key[1], parent_cut_key[2])
        else parent.source_cut_at
    )
    values = {
        "base_manifest": parent.base_manifest,
        "records": safe_records,
        "shop_domain": parent.shop_domain,
        "source_cut_at": source_cut_at,
        "dataset_generation": "sha256:" + "0" * 64,
        "base_dataset_generation": parent.base_dataset_generation,
        "parent_dataset_generation": parent.dataset_generation,
        "catalog_content_sha256": _catalog_content_sha256(safe_records),
        "taxonomy_rule_version": parent.taxonomy_rule_version,
        "built_at": built_at,
        "event_lineage_sha256": lineage,
        "last_event_identity_sha256": event_identity,
        "applied_event_count": parent.applied_event_count + 1,
        "product_status_counts": status_counts,
        "product_family_counts": family_counts,
        "product_count": len(safe_records),
        "variant_count": variants,
        "source_identity_product_count": identities,
        "public_item_count": public,
    }
    draft = object.__new__(_SyncGeneration)
    for field_name, field_value in values.items():
        object.__setattr__(draft, field_name, field_value)
    generation_id = (
        "sha256:" + hashlib.sha256(_canonical_json_bytes(_generation_descriptor(draft))).hexdigest()
    )
    values["dataset_generation"] = generation_id
    return _new_generation(**values)


def _clone_envelope(envelope: RawWebhookEnvelope) -> RawWebhookEnvelope:
    if type(envelope) is not RawWebhookEnvelope:
        raise _error("delivery must be a raw webhook envelope")
    return RawWebhookEnvelope(
        shop_domain=envelope.shop_domain,
        webhook_id=envelope.webhook_id,
        topic=envelope.topic,
        api_version=envelope.api_version,
        received_at=envelope.received_at,
        payload=envelope.payload,
        payload_sha256=envelope.payload_sha256,
    )


def _clone_validated_event(event: ValidatedWebhookEvent) -> ValidatedWebhookEvent:
    if type(event) is not ValidatedWebhookEvent:
        raise _error("validation adapter returned an invalid event")
    return ValidatedWebhookEvent(
        shop_domain=event.shop_domain,
        webhook_id=event.webhook_id,
        payload_sha256=event.payload_sha256,
        category=event.category,
        product_gid=event.product_gid,
        source_updated_at=event.source_updated_at,
    )


def _generation_view(generation: _SyncGeneration) -> GenerationView:
    _validate_generation(generation)
    return GenerationView(
        shop_domain=generation.shop_domain,
        source_cut_at=generation.source_cut_at,
        dataset_generation=generation.dataset_generation,
        base_dataset_generation=generation.base_dataset_generation,
        parent_dataset_generation=generation.parent_dataset_generation,
        catalog_content_sha256=generation.catalog_content_sha256,
        taxonomy_rule_version=generation.taxonomy_rule_version,
        built_at=generation.built_at,
        event_lineage_sha256=generation.event_lineage_sha256,
        last_event_identity_sha256=generation.last_event_identity_sha256,
        applied_event_count=generation.applied_event_count,
        product_status_counts=generation.product_status_counts,
        product_family_counts=generation.product_family_counts,
        product_count=generation.product_count,
        variant_count=generation.variant_count,
        source_identity_product_count=generation.source_identity_product_count,
        public_item_count=generation.public_item_count,
        records=_copy_records(generation.records),
    )


class SyncCore:
    """Thread-safe reference coordinator for one read-only catalog projection."""

    def __init__(
        self,
        *,
        expected_shop_domain: str,
        initial_source_cut_at: str,
        initial_source_manifest: SourceSnapshotManifest,
        initial_source_manifest_bytes: bytes,
        initial_manifest: DatasetManifestV1,
        initial_records: tuple[CatalogProductRecordV1, ...],
        validator: Callable[[RawWebhookEnvelope], ValidatedWebhookEvent],
        projector: Callable[
            [ProjectionContext, ValidatedWebhookEvent, RawWebhookEnvelope],
            tuple[CatalogProductRecordV1, ...],
        ],
        clock: Callable[[], str] = _system_clock,
        activation_probe: Callable[[ActivationKind], None] | None = None,
        stale_after_seconds: int = 300,
        max_inbox_events: int = DEFAULT_MAX_INBOX_EVENTS,
        max_inbox_retained_bytes: int = DEFAULT_MAX_INBOX_RETAINED_BYTES,
        max_processing_attempts: int = DEFAULT_MAX_PROCESSING_ATTEMPTS,
    ) -> None:
        if not callable(validator) or not callable(projector) or not callable(clock):
            raise _error("sync adapters and clock must be callable")
        if activation_probe is not None and not callable(activation_probe):
            raise _error("activation probe must be callable")
        self._expected_shop_domain = _text(expected_shop_domain, _SHOP_RE, "expected shop domain")
        self._stale_after_seconds = _nonnegative_integer(stale_after_seconds, "stale threshold")
        self._max_inbox_events = _positive_integer(max_inbox_events, "inbox event limit")
        self._max_inbox_retained_bytes = _positive_integer(
            max_inbox_retained_bytes, "inbox retained byte limit"
        )
        self._max_processing_attempts = _positive_integer(
            max_processing_attempts, "processing attempt limit"
        )
        initial = _initial_generation(
            initial_manifest,
            initial_records,
            source_manifest=initial_source_manifest,
            source_manifest_bytes=initial_source_manifest_bytes,
            shop_domain=self._expected_shop_domain,
            source_cut_at=initial_source_cut_at,
        )
        self._validator = validator
        self._projector = projector
        self._clock = clock
        self._activation_probe = activation_probe
        self._lock = RLock()
        self._process_lock = Lock()
        self._pair = _GenerationPair(
            active=_GenerationSlot(initial, MappingProxyType({})),
            previous=None,
        )
        self._max_source_cut_key = _timestamp_key(
            initial.source_cut_at, "initial source high-watermark"
        )
        self._max_built_key = _timestamp_key(initial.built_at, "initial build high-watermark")
        self._entries: dict[_InboxKey, _InboxEntry] = {}
        self._inbox_retained_bytes = 0
        self._delivery_sequence = 0
        self._unresolved_failed: set[_InboxKey] = set()
        self._unresolved_reconciliation: set[_InboxKey] = set()
        self._projection_paused = False
        self._rollback_reconciliation_pending = False
        self._last_event_at: str | None = None
        self._last_projected_at: str | None = None
        self._deliveries_total = 0
        self._unique_events_total = 0
        self._duplicate_deliveries_total = 0
        self._conflicting_deliveries_total = 0
        self._projected_events_total = 0
        self._failed_attempts_total = 0
        self._reconciliation_decisions_total = 0
        self._activations_total = 0
        self._rollbacks_total = 0
        self._reconciliation_installs_total = 0

    def receive(self, envelope: RawWebhookEnvelope) -> DeliveryResult:
        safe = _clone_envelope(envelope)
        if safe.shop_domain != self._expected_shop_domain:
            raise _error("delivery shop does not match the configured dataset")
        key = _inbox_key(safe.shop_domain, safe.webhook_id)
        retained_bytes = _retained_envelope_bytes(safe)
        with self._lock:
            existing = self._entries.get(key)
            if existing is None and (
                len(self._entries) >= self._max_inbox_events
                or self._inbox_retained_bytes + retained_bytes > self._max_inbox_retained_bytes
            ):
                raise SyncOperationError("The synchronization inbox is at capacity.")
            self._delivery_sequence += 1
            delivery_sequence = self._delivery_sequence
            self._deliveries_total += 1
            self._record_last_event_locked(safe.received_at)
            if existing is None:
                entry = _InboxEntry(
                    envelope=safe,
                    state=InboxState.RECEIVED,
                    delivery_attempts=1,
                    processing_attempts=0,
                    category=None,
                    failure_code=None,
                    projected_generation=None,
                    last_received_at=safe.received_at,
                    source_updated_at=None,
                    last_delivery_sequence=delivery_sequence,
                )
                self._entries[key] = entry
                self._inbox_retained_bytes += retained_bytes
                self._unique_events_total += 1
                return DeliveryResult(WebhookKey(*key), self._status(entry), False, False)
            last_received = self._later_timestamp(existing.last_received_at, safe.received_at)
            equivalent = (
                existing.envelope.topic == safe.topic
                and existing.envelope.api_version == safe.api_version
                and existing.envelope.payload_sha256 == safe.payload_sha256
            )
            if equivalent:
                entry = replace(
                    existing,
                    delivery_attempts=existing.delivery_attempts + 1,
                    last_received_at=last_received,
                    last_delivery_sequence=delivery_sequence,
                )
                self._entries[key] = entry
                self._duplicate_deliveries_total += 1
                return DeliveryResult(WebhookKey(*key), self._status(entry), True, False)
            entry = self._transition_entry(
                replace(
                    existing,
                    delivery_attempts=existing.delivery_attempts + 1,
                    last_received_at=last_received,
                    last_delivery_sequence=delivery_sequence,
                ),
                InboxState.RECONCILE_REQUIRED,
                failure_code=None,
            )
            self._entries[key] = entry
            self._conflicting_deliveries_total += 1
            self._reconciliation_decisions_total += 1
            self._unresolved_failed.discard(key)
            self._unresolved_reconciliation.add(key)
            return DeliveryResult(WebhookKey(*key), self._status(entry), False, True)

    def process(self, key: WebhookKey) -> EventStatus:
        safe_key = _inbox_key(key.shop_domain, key.webhook_id) if type(key) is WebhookKey else None
        if safe_key is None:
            raise _error("event key is invalid")
        with self._process_lock:
            with self._lock:
                entry = self._entries.get(safe_key)
                if entry is None:
                    raise SyncOperationError("The synchronization event does not exist.")
                if entry.state in {InboxState.PROJECTED, InboxState.RECONCILE_REQUIRED}:
                    return self._status(entry)
                if (
                    entry.state is InboxState.FAILED
                    and entry.processing_attempts >= self._max_processing_attempts
                ):
                    return self._status(entry)
                entry = replace(entry, processing_attempts=entry.processing_attempts + 1)
                self._entries[safe_key] = entry
                stored_envelope = entry.envelope
                if self._projection_paused:
                    return self._mark_reconcile_locked(safe_key, entry.category)
            allowed_categories = SUPPORTED_TOPIC_CATEGORIES.get(stored_envelope.topic)
            if allowed_categories is None:
                return self._mark_reconcile(safe_key, None)
            callback_envelope = _clone_envelope(stored_envelope)
            try:
                raw_event = self._validator(callback_envelope)
            except Exception:
                return self._mark_failed(safe_key, FailureCode.VALIDATION_ADAPTER_FAILED)
            try:
                event = _clone_validated_event(raw_event)
                self._validate_event_binding(stored_envelope, event, allowed_categories)
            except Exception:
                return self._mark_failed(safe_key, FailureCode.VALIDATED_EVENT_INVALID)
            with self._lock:
                entry = self._entries[safe_key]
                if entry.state is InboxState.RECONCILE_REQUIRED:
                    return self._status(entry)
                if entry.state is InboxState.RECEIVED:
                    entry = self._transition_entry(
                        entry,
                        InboxState.VALIDATED,
                        category=event.category,
                        source_updated_at=event.source_updated_at,
                    )
                else:
                    entry = replace(
                        entry,
                        category=event.category,
                        source_updated_at=event.source_updated_at,
                    )
                self._entries[safe_key] = entry
                active_slot = self._pair.active
                try:
                    order_is_safe = self._order_is_safe(active_slot, stored_envelope, event)
                except Exception:
                    return self._mark_reconcile_locked(safe_key, event.category)
                if not order_is_safe:
                    return self._mark_reconcile_locked(safe_key, event.category)
            try:
                context = ProjectionContext(
                    dataset_generation=active_slot.generation.dataset_generation,
                    base_dataset_generation=active_slot.generation.base_dataset_generation,
                    taxonomy_rule_version=active_slot.generation.taxonomy_rule_version,
                    records=_copy_records(active_slot.generation.records),
                )
                projected_records = self._projector(
                    context,
                    _clone_validated_event(event),
                    _clone_envelope(stored_envelope),
                )
            except Exception:
                return self._mark_failed(safe_key, FailureCode.PROJECTION_ADAPTER_FAILED)
            try:
                built_at = self._safe_clock()
            except Exception:
                return self._mark_failed(safe_key, FailureCode.CLOCK_FAILED)
            try:
                candidate = _advance_generation(
                    active_slot.generation,
                    projected_records,
                    stored_envelope,
                    event,
                    built_at,
                )
            except _ProjectionNeedsReconciliation:
                return self._mark_reconcile(safe_key, event.category)
            except Exception:
                return self._mark_failed(safe_key, FailureCode.CANDIDATE_INVALID)
            try:
                self._invoke_activation_probe(ActivationKind.EVENT)
            except Exception:
                return self._mark_failed(safe_key, FailureCode.ACTIVATION_FAILED)
            return self._commit_projection(safe_key, active_slot, candidate, stored_envelope, event)

    def ingest(self, envelope: RawWebhookEnvelope) -> DeliveryResult:
        receipt = self.receive(envelope)
        status = self.process(receipt.key)
        return DeliveryResult(
            WebhookKey(receipt.key.shop_domain, receipt.key.webhook_id),
            status,
            receipt.duplicate,
            receipt.conflict,
        )

    def event_status(self, key: WebhookKey) -> EventStatus:
        safe_key = _inbox_key(key.shop_domain, key.webhook_id) if type(key) is WebhookKey else None
        if safe_key is None:
            raise _error("event key is invalid")
        with self._lock:
            entry = self._entries.get(safe_key)
            if entry is None:
                raise SyncOperationError("The synchronization event does not exist.")
            return self._status(entry)

    def active_dataset(self) -> GenerationView:
        with self._lock:
            generation = self._pair.active.generation
        return _generation_view(generation)

    def previous_dataset(self) -> GenerationView | None:
        with self._lock:
            slot = self._pair.previous
        return None if slot is None else _generation_view(slot.generation)

    def pending_reconciliation(self) -> tuple[SyncEventReport, ...]:
        with self._lock:
            keys = sorted(
                self._unresolved_reconciliation,
                key=lambda item: item,
            )
            return tuple(self._event_report(key, self._entries[key]) for key in keys)

    def dead_letters(self) -> tuple[SyncEventReport, ...]:
        with self._lock:
            keys = sorted(
                (
                    key
                    for key in self._unresolved_failed
                    if self._entries[key].processing_attempts >= self._max_processing_attempts
                ),
                key=lambda item: item,
            )
            return tuple(self._event_report(key, self._entries[key]) for key in keys)

    def rollback(self, *, expected_active_generation: str) -> str:
        _text(expected_active_generation, _GENERATION_RE, "expected active generation")
        with self._process_lock:
            with self._lock:
                pair = self._pair
                if pair.active.generation.dataset_generation != expected_active_generation:
                    raise SyncOperationError("The active generation changed before rollback.")
                if pair.previous is None:
                    raise SyncOperationError("No previous generation is available for rollback.")
                previous = pair.previous
            try:
                _validate_generation(previous.generation)
                self._invoke_activation_probe(ActivationKind.ROLLBACK)
            except Exception:
                raise SyncOperationError("Rollback validation or activation failed.") from None
            with self._lock:
                if self._pair is not pair:
                    raise SyncOperationError("The active generation changed before rollback.")
                self._pair = _GenerationPair(active=previous, previous=pair.active)
                self._projection_paused = True
                self._rollback_reconciliation_pending = True
                self._rollbacks_total += 1
                return previous.generation.dataset_generation

    def install_reconciliation(
        self,
        *,
        shop_domain: str,
        source_cut_at: str,
        source_manifest: SourceSnapshotManifest,
        source_manifest_bytes: bytes,
        manifest: DatasetManifestV1,
        records: tuple[CatalogProductRecordV1, ...],
        expected_active_generation: str,
    ) -> str:
        safe_shop = _text(shop_domain, _SHOP_RE, "reconciliation shop domain")
        source_cut_key = _timestamp_key(source_cut_at, "reconciliation source cut")
        if safe_shop != self._expected_shop_domain:
            raise SyncOperationError("The reconciliation shop does not match the dataset.")
        _text(expected_active_generation, _GENERATION_RE, "expected active generation")
        with self._process_lock:
            with self._lock:
                pair = self._pair
                if pair.active.generation.dataset_generation != expected_active_generation:
                    raise SyncOperationError("The active generation changed before reconciliation.")
                if (source_cut_key[1], source_cut_key[2]) <= (
                    self._max_source_cut_key[1],
                    self._max_source_cut_key[2],
                ):
                    raise SyncOperationError("The reconciliation source cut is not newer.")
                delivery_watermark = self._delivery_sequence
            try:
                candidate = _initial_generation(
                    manifest,
                    records,
                    source_manifest=source_manifest,
                    source_manifest_bytes=source_manifest_bytes,
                    shop_domain=safe_shop,
                    source_cut_at=source_cut_at,
                )
                candidate_built_key = _timestamp_key(
                    candidate.built_at, "reconciliation build timestamp"
                )
                if (candidate_built_key[1], candidate_built_key[2]) <= (
                    self._max_built_key[1],
                    self._max_built_key[2],
                ):
                    raise _error("reconciliation build timestamp must advance its high-watermark")
                self._invoke_activation_probe(ActivationKind.RECONCILIATION)
            except Exception:
                raise SyncOperationError(
                    "Reconciliation validation or activation failed."
                ) from None
            with self._lock:
                if self._pair is not pair:
                    raise SyncOperationError("The active generation changed before reconciliation.")
                self._pair = _GenerationPair(
                    active=_GenerationSlot(candidate, MappingProxyType({})),
                    previous=pair.active,
                )
                self._max_source_cut_key = source_cut_key
                self._max_built_key = candidate_built_key
                self._unresolved_failed = {
                    key
                    for key in self._unresolved_failed
                    if not self._entry_covered_by_reconciliation(
                        self._entries[key], delivery_watermark, source_cut_key
                    )
                }
                self._unresolved_reconciliation = {
                    key
                    for key in self._unresolved_reconciliation
                    if not self._entry_covered_by_reconciliation(
                        self._entries[key], delivery_watermark, source_cut_key
                    )
                }
                self._projection_paused = bool(
                    self._unresolved_failed or self._unresolved_reconciliation
                )
                self._rollback_reconciliation_pending = False
                self._reconciliation_installs_total += 1
                return candidate.dataset_generation

    def metrics(self) -> SyncMetrics:
        observed_at = self._safe_clock()
        observed_key = _timestamp_key(observed_at, "metrics timestamp")
        with self._lock:
            generation = self._pair.active.generation
            source_cut_key = _timestamp_key(generation.source_cut_at, "generation source cut")
            lag = _elapsed_whole_seconds(source_cut_key, observed_key)
            dead_letters = sum(
                self._entries[key].processing_attempts >= self._max_processing_attempts
                for key in self._unresolved_failed
            )
            unresolved_reconciliation = len(self._unresolved_reconciliation) + int(
                self._rollback_reconciliation_pending
            )
            stale = (
                lag > self._stale_after_seconds
                or self._projection_paused
                or bool(self._unresolved_failed)
                or unresolved_reconciliation > 0
            )
            unclassified = dict(generation.product_family_counts)[ProductFamily.UNCLASSIFIED.value]
            return SyncMetrics(
                observed_at=observed_at,
                shop_domain=generation.shop_domain,
                source_cut_at=generation.source_cut_at,
                dataset_version=generation.dataset_generation,
                built_at=generation.built_at,
                taxonomy_rule_version=generation.taxonomy_rule_version,
                unclassified_product_count=unclassified,
                last_event_at=self._last_event_at,
                last_projected_at=self._last_projected_at,
                lag_seconds=lag,
                stale_after_seconds=self._stale_after_seconds,
                stale=stale,
                projection_paused=self._projection_paused,
                unresolved_failed_events=len(self._unresolved_failed),
                unresolved_reconciliation_events=unresolved_reconciliation,
                dead_letter_events=dead_letters,
                inbox_events=len(self._entries),
                inbox_retained_bytes=self._inbox_retained_bytes,
                deliveries_total=self._deliveries_total,
                unique_events_total=self._unique_events_total,
                duplicate_deliveries_total=self._duplicate_deliveries_total,
                conflicting_deliveries_total=self._conflicting_deliveries_total,
                projected_events_total=self._projected_events_total,
                failed_attempts_total=self._failed_attempts_total,
                reconciliation_decisions_total=self._reconciliation_decisions_total,
                activations_total=self._activations_total,
                rollbacks_total=self._rollbacks_total,
                reconciliation_installs_total=self._reconciliation_installs_total,
            )

    def _safe_clock(self) -> str:
        try:
            value = self._clock()
            return _timestamp_key(value, "clock timestamp")[0]
        except Exception:
            raise SyncOperationError("The synchronization clock failed.") from None

    def _invoke_activation_probe(self, kind: ActivationKind) -> None:
        if self._activation_probe is None:
            return
        try:
            self._activation_probe(kind)
        except Exception:
            raise SyncOperationError("Dataset activation was rejected.") from None

    @staticmethod
    def _validate_event_binding(
        envelope: RawWebhookEnvelope,
        event: ValidatedWebhookEvent,
        allowed_categories: frozenset[EventCategory],
    ) -> None:
        if (
            event.shop_domain != envelope.shop_domain
            or event.webhook_id != envelope.webhook_id
            or event.payload_sha256 != envelope.payload_sha256
            or event.category not in allowed_categories
        ):
            raise _error("validated event is not bound to its delivery")

    def _order_is_safe(
        self,
        slot: _GenerationSlot,
        envelope: RawWebhookEnvelope,
        event: ValidatedWebhookEvent,
    ) -> bool:
        source_key = _timestamp_key(event.source_updated_at, "source update timestamp")
        source_cut_key = _timestamp_key(
            slot.generation.source_cut_at, "active source high-watermark"
        )
        if (source_key[1], source_key[2]) <= (source_cut_key[1], source_cut_key[2]):
            return False
        applied = slot.applied_orders.get((envelope.shop_domain, event.product_gid))
        if applied is not None:
            return (source_key[1], source_key[2]) > (
                applied.timestamp_key[1],
                applied.timestamp_key[2],
            )
        if event.category is EventCategory.PRODUCT_CREATE:
            return True
        current = next(
            (
                record
                for record in slot.generation.records
                if record.product_gid == event.product_gid
            ),
            None,
        )
        if current is None:
            return True
        baseline_key = _record_latest_key(current)
        return (source_key[1], source_key[2]) > (baseline_key[1], baseline_key[2])

    def _commit_projection(
        self,
        key: _InboxKey,
        expected_slot: _GenerationSlot,
        candidate: _SyncGeneration,
        envelope: RawWebhookEnvelope,
        event: ValidatedWebhookEvent,
    ) -> EventStatus:
        event_identity = _event_identity_sha256(envelope, event)
        order_key = (envelope.shop_domain, event.product_gid)
        source_order = _AppliedOrder(
            _timestamp_key(event.source_updated_at, "source update timestamp"),
            event_identity,
        )
        updated_orders = dict(expected_slot.applied_orders)
        updated_orders[order_key] = source_order
        new_slot = _GenerationSlot(candidate, MappingProxyType(updated_orders))
        with self._lock:
            entry = self._entries[key]
            if entry.state is InboxState.RECONCILE_REQUIRED:
                return self._status(entry)
            if self._pair.active is not expected_slot:
                return self._mark_reconcile_locked(key, event.category)
            entry = self._transition_entry(
                entry,
                InboxState.PROJECTED,
                category=event.category,
                failure_code=None,
                projected_generation=candidate.dataset_generation,
            )
            self._pair = _GenerationPair(active=new_slot, previous=expected_slot)
            self._max_source_cut_key = _timestamp_key(
                candidate.source_cut_at, "projected source high-watermark"
            )
            self._max_built_key = _timestamp_key(
                candidate.built_at, "projected build high-watermark"
            )
            self._entries[key] = entry
            self._unresolved_failed.discard(key)
            self._unresolved_reconciliation.discard(key)
            self._projected_events_total += 1
            self._activations_total += 1
            self._record_last_projected_locked(envelope.received_at)
            return self._status(entry)

    def _mark_failed(self, key: _InboxKey, failure_code: FailureCode) -> EventStatus:
        with self._lock:
            entry = self._entries[key]
            if entry.state is InboxState.RECONCILE_REQUIRED:
                return self._status(entry)
            entry = self._transition_entry(
                entry,
                InboxState.FAILED,
                failure_code=failure_code,
                projected_generation=None,
            )
            self._entries[key] = entry
            self._unresolved_failed.add(key)
            self._failed_attempts_total += 1
            return self._status(entry)

    def _mark_reconcile(self, key: _InboxKey, category: EventCategory | None) -> EventStatus:
        with self._lock:
            return self._mark_reconcile_locked(key, category)

    def _mark_reconcile_locked(self, key: _InboxKey, category: EventCategory | None) -> EventStatus:
        entry = self._entries[key]
        if entry.state is not InboxState.RECONCILE_REQUIRED:
            entry = self._transition_entry(
                entry,
                InboxState.RECONCILE_REQUIRED,
                category=category,
                failure_code=None,
                projected_generation=entry.projected_generation,
            )
            self._entries[key] = entry
            self._reconciliation_decisions_total += 1
        self._unresolved_failed.discard(key)
        self._unresolved_reconciliation.add(key)
        return self._status(entry)

    @staticmethod
    def _transition_entry(
        entry: _InboxEntry,
        state: InboxState,
        *,
        category: EventCategory | object | None = ...,
        failure_code: FailureCode | object | None = ...,
        projected_generation: str | object | None = ...,
        source_updated_at: str | object | None = ...,
    ) -> _InboxEntry:
        if type(state) is not InboxState or _STATE_RANK[state] < _STATE_RANK[entry.state]:
            raise _error("inbox state transition is not monotonic")
        return replace(
            entry,
            state=state,
            category=entry.category if category is ... else category,
            failure_code=entry.failure_code if failure_code is ... else failure_code,
            projected_generation=(
                entry.projected_generation if projected_generation is ... else projected_generation
            ),
            source_updated_at=(
                entry.source_updated_at if source_updated_at is ... else source_updated_at
            ),
        )

    def _status(self, entry: _InboxEntry) -> EventStatus:
        return EventStatus(
            state=entry.state,
            delivery_attempts=entry.delivery_attempts,
            processing_attempts=entry.processing_attempts,
            category=entry.category,
            failure_code=entry.failure_code,
            projected_generation=entry.projected_generation,
            dead_letter=(
                entry.state is InboxState.FAILED
                and entry.processing_attempts >= self._max_processing_attempts
            ),
        )

    def _event_report(self, key: _InboxKey, entry: _InboxEntry) -> SyncEventReport:
        status = self._status(entry)
        return SyncEventReport(
            key=WebhookKey(*key),
            topic=entry.envelope.topic,
            state=status.state,
            delivery_attempts=status.delivery_attempts,
            processing_attempts=status.processing_attempts,
            category=status.category,
            failure_code=status.failure_code,
            dead_letter=status.dead_letter,
        )

    @staticmethod
    def _entry_covered_by_reconciliation(
        entry: _InboxEntry,
        delivery_watermark: int,
        source_cut_key: tuple[str, int, str],
    ) -> bool:
        if entry.last_delivery_sequence > delivery_watermark:
            return False
        timestamps = [entry.last_received_at]
        if entry.source_updated_at is not None:
            timestamps.append(entry.source_updated_at)
        return all(
            (_timestamp_key(timestamp, "event coverage timestamp")[1:]) <= source_cut_key[1:]
            for timestamp in timestamps
        )

    def _record_last_event_locked(self, timestamp: str) -> None:
        if self._last_event_at is None:
            self._last_event_at = timestamp
            return
        self._last_event_at = self._later_timestamp(self._last_event_at, timestamp)

    def _record_last_projected_locked(self, timestamp: str) -> None:
        if self._last_projected_at is None:
            self._last_projected_at = timestamp
            return
        self._last_projected_at = self._later_timestamp(self._last_projected_at, timestamp)

    @staticmethod
    def _later_timestamp(first: str, second: str) -> str:
        first_key = _timestamp_key(first, "stored timestamp")
        second_key = _timestamp_key(second, "incoming timestamp")
        if (second_key[1], second_key[2]) > (first_key[1], first_key[2]):
            return second
        return first


__all__ = [
    "DEFAULT_MAX_INBOX_EVENTS",
    "DEFAULT_MAX_INBOX_RETAINED_BYTES",
    "DEFAULT_MAX_PROCESSING_ATTEMPTS",
    "MAX_GID_BYTES",
    "MAX_TAXONOMY_RULE_VERSION_BYTES",
    "MAX_TIMESTAMP_BYTES",
    "MAX_TOPIC_BYTES",
    "MAX_WEBHOOK_PAYLOAD_BYTES",
    "SUPPORTED_TOPIC_CATEGORIES",
    "SYNC_CONTRACT_VERSION",
    "ActivationKind",
    "DeliveryResult",
    "EventCategory",
    "EventStatus",
    "FailureCode",
    "GenerationView",
    "InboxState",
    "ProjectionContext",
    "RawWebhookEnvelope",
    "SyncContractError",
    "SyncCore",
    "SyncEventReport",
    "SyncMetrics",
    "SyncOperationError",
    "ValidatedWebhookEvent",
    "WebhookKey",
]
