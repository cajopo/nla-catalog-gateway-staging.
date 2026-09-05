from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import fields, replace
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import Any

import pytest

import nla_catalog_gateway.sync as sync
from nla_catalog_gateway import reconciliation
from nla_catalog_gateway.runtime_contract import (
    CatalogProductRecordV1,
    CatalogVariantRecordV1,
    DatasetManifestV1,
    InventoryPolicy,
    ProductStatus,
    SelectedOptionV1,
)
from nla_catalog_gateway.sync import (
    ActivationKind,
    EventCategory,
    FailureCode,
    InboxState,
    ProjectionContext,
    RawWebhookEnvelope,
    ReconciliationFence,
    SyncContractError,
    SyncCore,
    SyncOperationError,
    ValidatedWebhookEvent,
    WebhookKey,
)
from nla_catalog_gateway.taxonomy import ClassificationReport, Game, ProductFamily

BASE_TIME = "2026-09-02T00:00:00Z"
EVENT_TIME = "2026-09-02T00:01:00Z"
SHOP = "synthetic.myshopify.com"


def _variant(
    product_id: str,
    *,
    price: str = "1.2300",
    inventory: int = -5,
    updated_at: str = BASE_TIME,
) -> CatalogVariantRecordV1:
    return CatalogVariantRecordV1(
        variant_gid=f"gid://shopify/ProductVariant/{product_id}0",
        product_gid=f"gid://shopify/Product/{product_id}",
        inventory_item_gid=f"gid://shopify/InventoryItem/{product_id}00",
        title="Default Title",
        sku=f"SKU-{product_id}",
        barcode=None,
        selected_options=(SelectedOptionV1("Title", "Default Title"),),
        price_text=price,
        compare_at_price_text=None,
        inventory_quantity=inventory,
        inventory_policy=InventoryPolicy.DENY,
        inventory_tracked=True,
        updated_at=updated_at,
    )


def _product(
    product_id: str,
    *,
    updated_at: str = BASE_TIME,
    price: str = "1.2300",
    inventory: int = -5,
    published: bool = True,
    status: ProductStatus = ProductStatus.ACTIVE,
    family: ProductFamily = ProductFamily.SINGLE,
    game: Game | None = Game.MAGIC,
    title: str | None = None,
) -> CatalogProductRecordV1:
    sealed = family is ProductFamily.SEALED
    unclassified = family is ProductFamily.UNCLASSIFIED
    return CatalogProductRecordV1(
        product_gid=f"gid://shopify/Product/{product_id}",
        handle=f"synthetic-{product_id}",
        commercial_title=title or f"Synthetic Product {product_id}",
        canonical_card_name=None if sealed or unclassified else f"Synthetic Card {product_id}",
        shopify_status=status,
        online_store_published=published,
        powertools_source_id=product_id,
        sync_source_id=product_id,
        total_inventory=inventory,
        tracks_inventory=True,
        updated_at=updated_at,
        game=game,
        product_family=family,
        product_subtype="booster-box" if sealed else None,
        classification_rule_version="2026-09-01.1",
        classification_rule_id=None if unclassified else f"family:{family.value}",
        unclassified_reason="unknown_product_type" if unclassified else None,
        subtype_rule_id="sealed:booster-box" if sealed else None,
        subtype_reason=None,
        variants=(
            _variant(
                product_id,
                price=price,
                inventory=inventory,
                updated_at=updated_at,
            ),
        ),
    )


def _records() -> tuple[CatalogProductRecordV1, ...]:
    return (
        _product("1"),
        _product(
            "2",
            family=ProductFamily.SEALED,
            status=ProductStatus.DRAFT,
            published=False,
            price="120.000",
            inventory=7,
        ),
    )


def _manifest(
    records: tuple[CatalogProductRecordV1, ...],
    *,
    generated_at: str = BASE_TIME,
    shop_domain: str = SHOP,
) -> DatasetManifestV1:
    return _reconciled_generation(
        records,
        generated_at=generated_at,
        shop_domain=shop_domain,
    ).dataset_manifest


def _reconciled_part_manifest(
    records: tuple[CatalogProductRecordV1, ...],
    *,
    part: reconciliation.SnapshotPart,
    generated_at: str,
    shop_domain: str = SHOP,
) -> reconciliation.SnapshotPartManifestV1:
    product_count = len(records)
    variant_count = sum(len(record.variants) for record in records)
    if part is reconciliation.SnapshotPart.PRODUCTS:
        object_counts = (
            ("Metafield", 0),
            ("Product", product_count),
            ("ResourcePublicationV2", product_count),
        )
        root_count = product_count
        operation_id = "gid://shopify/BulkOperation/11"
        content_sha256 = "e" * 64
    else:
        object_counts = (
            ("InventoryLevel", variant_count),
            ("Metafield", 0),
            ("ProductVariant", variant_count),
        )
        root_count = variant_count
        operation_id = "gid://shopify/BulkOperation/12"
        content_sha256 = "f" * 64
    values: dict[str, Any] = {
        "schema_version": 1,
        "part": part,
        "snapshot_set_id": "sha256:" + "1" * 64,
        "shop_domain": shop_domain,
        "api_version": "2026-07",
        "operation_id": operation_id,
        "operation_type": "QUERY",
        "status": "COMPLETED",
        "error_code": None,
        "url_present": True,
        "partial_data_url_present": False,
        "created_at": generated_at,
        "completed_at": generated_at,
        "online_store_publication_gid": "gid://shopify/Publication/1",
        "source_code_sha": "b" * 40,
        "query_sha256": sync._RECONCILED_QUERY_SHA256[part],
        "content_sha256": content_sha256,
        "snapshot_bytes": 1234,
        "object_count": sum(count for _, count in object_counts),
        "root_object_count": root_count,
        "object_counts": object_counts,
        "capture_fence_max_seconds": 24 * 60 * 60,
    }
    draft = object.__new__(reconciliation.SnapshotPartManifestV1)
    for name, value in values.items():
        object.__setattr__(draft, name, value)
    object.__setattr__(draft, "part_generation", "sha256:" + "0" * 64)
    values["part_generation"] = draft.expected_part_generation()
    return reconciliation.SnapshotPartManifestV1(**values)


def _replace_reconciled_part(
    part: reconciliation.SnapshotPartManifestV1,
    **changes: Any,
) -> reconciliation.SnapshotPartManifestV1:
    values = {field.name: getattr(part, field.name) for field in fields(part)}
    values.update(changes)
    draft = object.__new__(reconciliation.SnapshotPartManifestV1)
    for name, value in values.items():
        object.__setattr__(draft, name, value)
    object.__setattr__(draft, "part_generation", "sha256:" + "0" * 64)
    values["part_generation"] = draft.expected_part_generation()
    return reconciliation.SnapshotPartManifestV1(**values)


def _reconciled_report(
    records: tuple[CatalogProductRecordV1, ...],
) -> ClassificationReport:
    classified = sum(record.product_family is not ProductFamily.UNCLASSIFIED for record in records)
    return ClassificationReport(
        rule_version=records[0].classification_rule_version,
        total=len(records),
        classified=classified,
        unclassified=len(records) - classified,
        counts=MappingProxyType(
            dict(
                Counter(
                    f"{record.game.value if record.game else 'unknown'}/"
                    f"{record.product_family.value}"
                    for record in records
                )
            )
        ),
        rule_counts=MappingProxyType(
            dict(
                Counter(
                    record.classification_rule_id
                    for record in records
                    if record.classification_rule_id is not None
                )
            )
        ),
        unclassified_reasons=MappingProxyType(
            dict(
                Counter(
                    record.unclassified_reason
                    for record in records
                    if record.unclassified_reason is not None
                )
            )
        ),
        subtype_reasons=MappingProxyType(
            dict(
                Counter(
                    record.subtype_reason for record in records if record.subtype_reason is not None
                )
            )
        ),
    )


def _reconciled_generation(
    records: tuple[CatalogProductRecordV1, ...],
    *,
    generated_at: str,
    shop_domain: str = SHOP,
) -> reconciliation.ReconciledCatalogGenerationV1:
    parts = tuple(
        _reconciled_part_manifest(
            records,
            part=part,
            generated_at=generated_at,
            shop_domain=shop_domain,
        )
        for part in (
            reconciliation.SnapshotPart.PRODUCTS,
            reconciliation.SnapshotPart.VARIANTS,
        )
    )
    status_counts = tuple(
        (status.value, sum(record.shopify_status is status for record in records))
        for status in ProductStatus
    )
    counts = reconciliation._SourceCounts(
        product_count=len(records),
        variant_count=sum(len(record.variants) for record in records),
        inventory_item_count=sum(len(record.variants) for record in records),
        inventory_level_count=sum(len(record.variants) for record in records),
        publication_count=len(records),
        metafield_count=0,
        product_status_counts=status_counts,
        active_published_product_count=sum(record.publishable for record in records),
        source_identity_product_count=sum(
            record.powertools_source_id is not None for record in records
        ),
    )
    source = reconciliation._build_source_manifest(
        tuple(SimpleNamespace(manifest=part) for part in parts),  # type: ignore[arg-type]
        counts,
    )
    report = _reconciled_report(records)
    manifest = reconciliation._runtime_manifest(source, records, report)
    return reconciliation.ReconciledCatalogGenerationV1(
        source_manifest=source,
        source_manifest_bytes=source.to_json_bytes(),
        taxonomy_report=report,
        records=records,
        dataset_manifest=manifest,
    )


def _candidate_args(
    core: SyncCore,
    records: tuple[CatalogProductRecordV1, ...],
    *,
    generated_at: str,
    shop_domain: str = SHOP,
) -> dict[str, Any]:
    active = core.active_dataset().dataset_generation
    return {
        "fence": core.capture_reconciliation_fence(expected_active_generation=active),
        "reconciled_generation": _reconciled_generation(
            records,
            generated_at=generated_at,
            shop_domain=shop_domain,
        ),
    }


def _envelope(
    webhook_id: str = "event-1",
    *,
    shop_domain: str = SHOP,
    topic: str = "products/update",
    received_at: str = EVENT_TIME,
    payload: bytes = b'{"synthetic":true}',
) -> RawWebhookEnvelope:
    return RawWebhookEnvelope(
        shop_domain=shop_domain,
        webhook_id=webhook_id,
        topic=topic,
        api_version="2026-07",
        received_at=received_at,
        payload=payload,
    )


def _validated(
    envelope: RawWebhookEnvelope,
    *,
    product_id: str = "1",
    category: EventCategory = EventCategory.PRODUCT_UPDATE,
    source_updated_at: str = EVENT_TIME,
) -> ValidatedWebhookEvent:
    return ValidatedWebhookEvent(
        shop_domain=envelope.shop_domain,
        webhook_id=envelope.webhook_id,
        payload_sha256=envelope.payload_sha256,
        category=category,
        product_gid=f"gid://shopify/Product/{product_id}",
        source_updated_at=source_updated_at,
    )


class MutableClock:
    def __init__(self, value: str = "2026-09-02T00:01:01Z") -> None:
        self.value = value

    def __call__(self) -> str:
        return self.value


class Adapters:
    def __init__(self) -> None:
        self.category = EventCategory.PRODUCT_UPDATE
        self.product_id = "1"
        self.source_updated_at = EVENT_TIME
        self.validator_calls = 0
        self.projector_calls = 0
        self.validator_failure: BaseException | None = None
        self.projector_failure: BaseException | None = None
        self.projector_override: Any = None
        self.price = "9.9900"
        self.inventory = -(2**63)

    def validate(self, envelope: RawWebhookEnvelope) -> ValidatedWebhookEvent:
        self.validator_calls += 1
        if self.validator_failure is not None:
            raise self.validator_failure
        return _validated(
            envelope,
            product_id=self.product_id,
            category=self.category,
            source_updated_at=self.source_updated_at,
        )

    def project(
        self,
        context: ProjectionContext,
        event: ValidatedWebhookEvent,
        _envelope_value: RawWebhookEnvelope,
    ) -> tuple[CatalogProductRecordV1, ...]:
        self.projector_calls += 1
        if self.projector_failure is not None:
            raise self.projector_failure
        if self.projector_override is not None:
            return self.projector_override(context, event)
        if event.category is EventCategory.PRODUCT_CREATE:
            product_id = event.product_gid.rsplit("/", 1)[1]
            return (
                *context.records,
                _product(
                    product_id,
                    family=ProductFamily.SEALED,
                    status=ProductStatus.ACTIVE,
                    published=True,
                    price="55.5000",
                    inventory=11,
                    updated_at=event.source_updated_at,
                ),
            )
        if event.category is EventCategory.PRODUCT_DELETE:
            return tuple(
                record for record in context.records if record.product_gid != event.product_gid
            )
        updated: list[CatalogProductRecordV1] = []
        for record in context.records:
            if record.product_gid != event.product_gid:
                updated.append(record)
                continue
            variant = replace(
                record.variants[0],
                price_text=(
                    record.variants[0].price_text
                    if event.category is EventCategory.INVENTORY_CHANGE
                    else self.price
                ),
                inventory_quantity=self.inventory,
                updated_at=event.source_updated_at,
            )
            updated.append(
                replace(
                    record,
                    online_store_published=(
                        False
                        if event.category is EventCategory.PRODUCT_UNPUBLISH
                        else record.online_store_published
                    ),
                    total_inventory=self.inventory,
                    updated_at=event.source_updated_at,
                    variants=(variant,),
                )
            )
        return tuple(updated)


def _core(
    adapters: Adapters | None = None,
    *,
    clock: Any = None,
    probe: Any = None,
    stale_after_seconds: int = 300,
    max_inbox_events: int = 100,
    max_inbox_retained_bytes: int = 1024 * 1024,
    max_processing_attempts: int = 3,
    records: tuple[CatalogProductRecordV1, ...] | None = None,
) -> tuple[SyncCore, Adapters, MutableClock]:
    actual_records = records or _records()
    actual_adapters = adapters or Adapters()
    actual_clock = clock or MutableClock()
    return (
        SyncCore(
            expected_shop_domain=SHOP,
            initial_reconciled_generation=_reconciled_generation(
                actual_records,
                generated_at=BASE_TIME,
            ),
            validator=actual_adapters.validate,
            projector=actual_adapters.project,
            clock=actual_clock,
            activation_probe=probe,
            stale_after_seconds=stale_after_seconds,
            max_inbox_events=max_inbox_events,
            max_inbox_retained_bytes=max_inbox_retained_bytes,
            max_processing_attempts=max_processing_attempts,
        ),
        actual_adapters,
        actual_clock,
    )


def test_receive_process_update_is_non_lossy_versioned_and_idempotent() -> None:
    core, adapters, clock = _core()
    envelope = _envelope()
    receipt = core.receive(envelope)
    assert receipt.status.state is InboxState.RECEIVED
    assert receipt.status.delivery_attempts == 1
    assert receipt.status.processing_attempts == 0
    assert not receipt.duplicate
    assert not receipt.conflict

    status = core.process(receipt.key)
    assert status.state is InboxState.PROJECTED
    assert status.category is EventCategory.PRODUCT_UPDATE
    assert status.failure_code is None
    assert not status.dead_letter
    assert status.projected_generation is not None
    active = core.active_dataset()
    previous = core.previous_dataset()
    assert previous is not None
    assert active.parent_dataset_generation == previous.dataset_generation
    assert active.base_dataset_generation == previous.dataset_generation
    assert active.dataset_generation == status.projected_generation
    assert active.applied_event_count == 1
    assert active.records[0].variants[0].price_text == "9.9900"
    assert active.records[0].variants[0].inventory_quantity == -(2**63)
    assert active.records[0].total_inventory == -(2**63)
    assert active.records[1].variants[0].price_text == "120.000"
    assert active.records[1].variants[0].inventory_quantity == 7
    assert previous.records[0].variants[0].price_text == "1.2300"

    retry = core.ingest(
        _envelope(received_at="2026-09-02T02:01:00+02:00", payload=envelope.payload)
    )
    assert retry.duplicate
    assert retry.status.state is InboxState.PROJECTED
    assert retry.status.delivery_attempts == 2
    assert adapters.validator_calls == 1
    assert adapters.projector_calls == 1
    assert core.active_dataset().dataset_generation == active.dataset_generation

    clock.value = "2026-09-02T00:01:05.5Z"
    metrics = core.metrics()
    assert metrics.shop_domain == SHOP
    assert metrics.source_cut_at == EVENT_TIME
    assert metrics.dataset_version == active.dataset_generation
    assert metrics.built_at == "2026-09-02T00:01:01Z"
    assert metrics.taxonomy_rule_version == "2026-09-01.1"
    assert metrics.unclassified_product_count == 0
    assert metrics.last_event_at == EVENT_TIME
    assert metrics.last_projected_at == EVENT_TIME
    assert metrics.lag_seconds == 5
    assert not metrics.stale
    assert metrics.deliveries_total == 2
    assert metrics.unique_events_total == 1
    assert metrics.duplicate_deliveries_total == 1
    assert metrics.projected_events_total == 1
    assert metrics.activations_total == 1


def test_public_key_alias_cannot_corrupt_private_inbox_identity() -> None:
    core, adapters, _ = _core()
    envelope = _envelope("alias-1")
    receipt = core.receive(envelope)
    original_key = receipt.key
    assert type(original_key) is WebhookKey
    assert isinstance(original_key, tuple)
    with pytest.raises(AttributeError):
        object.__setattr__(original_key, "webhook_id", "forged")

    object.__setattr__(receipt, "key", WebhookKey(SHOP, "forged"))
    retry = core.receive(envelope)
    assert retry.duplicate
    assert core.metrics().unique_events_total == 1
    assert core.metrics().inbox_events == 1
    assert core.process(WebhookKey(SHOP, "alias-1")).state is InboxState.PROJECTED
    assert adapters.validator_calls == 1


def test_report_key_alias_cannot_corrupt_pending_reconciliation() -> None:
    core, _, _ = _core()
    core.ingest(_envelope("pending-1", topic="products/unknown"))
    report = core.pending_reconciliation()[0]
    with pytest.raises(AttributeError):
        object.__setattr__(report.key, "webhook_id", "forged")
    object.__setattr__(report, "key", WebhookKey(SHOP, "forged"))
    pending = core.pending_reconciliation()
    assert len(pending) == 1
    assert pending[0].key == WebhookKey(SHOP, "pending-1")


@pytest.mark.parametrize(
    ("topic", "category", "product_id"),
    [
        ("products/create", EventCategory.PRODUCT_CREATE, "3"),
        ("inventory_levels/update", EventCategory.INVENTORY_CHANGE, "1"),
        ("products/update", EventCategory.PRODUCT_UNPUBLISH, "1"),
    ],
)
def test_supported_event_categories_activate_complete_candidates(
    topic: str, category: EventCategory, product_id: str
) -> None:
    adapters = Adapters()
    adapters.category = category
    adapters.product_id = product_id
    core, _, _ = _core(adapters)
    result = core.ingest(_envelope(topic=topic))
    assert result.status.state is InboxState.PROJECTED
    active = core.active_dataset()
    records = {record.product_gid: record for record in active.records}
    if category is EventCategory.PRODUCT_CREATE:
        assert active.product_count == 3
        assert records["gid://shopify/Product/3"].product_family is ProductFamily.SEALED
    elif category is EventCategory.PRODUCT_UNPUBLISH:
        assert not records["gid://shopify/Product/1"].online_store_published
        assert active.public_item_count == 0
    else:
        assert records["gid://shopify/Product/1"].variants[0].inventory_quantity == -(2**63)


def test_inventory_event_cannot_overwrite_price() -> None:
    adapters = Adapters()
    adapters.category = EventCategory.INVENTORY_CHANGE

    def overwrite_price(
        context: ProjectionContext, event: ValidatedWebhookEvent
    ) -> tuple[CatalogProductRecordV1, ...]:
        current = context.records[0]
        variant = replace(
            current.variants[0],
            price_text="0",
            inventory_quantity=22,
            updated_at=event.source_updated_at,
        )
        return (
            replace(
                current,
                total_inventory=22,
                updated_at=event.source_updated_at,
                variants=(variant,),
            ),
            context.records[1],
        )

    adapters.projector_override = overwrite_price
    core, _, _ = _core(adapters)
    before = core.active_dataset()
    result = core.ingest(_envelope(topic="inventory_levels/update"))
    assert result.status.state is InboxState.RECONCILE_REQUIRED
    assert core.active_dataset() == before


@pytest.mark.parametrize(
    ("topic", "category"),
    [
        ("products/update", EventCategory.PRODUCT_UPDATE),
        ("products/update", EventCategory.PRODUCT_UNPUBLISH),
        ("inventory_levels/update", EventCategory.INVENTORY_CHANGE),
    ],
)
@pytest.mark.parametrize("replacement_identity", ["999", None])
def test_non_create_delete_event_cannot_rewrite_source_identity(
    topic: str,
    category: EventCategory,
    replacement_identity: str | None,
) -> None:
    adapters = Adapters()
    adapters.category = category

    def rewrite_identity(
        context: ProjectionContext, event: ValidatedWebhookEvent
    ) -> tuple[CatalogProductRecordV1, ...]:
        target = context.records[0]
        variant = replace(target.variants[0], updated_at=event.source_updated_at)
        return (
            replace(
                target,
                powertools_source_id=replacement_identity,
                sync_source_id=replacement_identity,
                online_store_published=(
                    False
                    if event.category is EventCategory.PRODUCT_UNPUBLISH
                    else target.online_store_published
                ),
                total_inventory=(
                    22
                    if event.category is EventCategory.INVENTORY_CHANGE
                    else target.total_inventory
                ),
                updated_at=event.source_updated_at,
                variants=(variant,),
            ),
            context.records[1],
        )

    adapters.projector_override = rewrite_identity
    core, _, _ = _core(adapters)
    before = core.active_dataset()
    suffix = replacement_identity or "none"
    result = core.ingest(_envelope(f"identity-{category.value}-{suffix}", topic=topic))
    assert result.status.state is InboxState.RECONCILE_REQUIRED
    assert core.active_dataset() == before


def test_delete_category_removes_only_the_target_and_can_rollback() -> None:
    adapters = Adapters()
    adapters.category = EventCategory.PRODUCT_DELETE
    adapters.product_id = "2"
    core, _, _ = _core(adapters)
    before = core.active_dataset()
    result = core.ingest(_envelope(topic="products/delete"))
    assert result.status.state is InboxState.PROJECTED
    assert [record.product_gid for record in core.active_dataset().records] == [
        "gid://shopify/Product/1"
    ]
    rolled_back = core.rollback(expected_active_generation=result.status.projected_generation or "")
    assert rolled_back == before.dataset_generation
    assert core.active_dataset().product_count == 2
    assert core.previous_dataset() is not None
    metrics = core.metrics()
    assert metrics.projection_paused
    assert metrics.stale
    assert metrics.rollbacks_total == 1
    assert metrics.unresolved_reconciliation_events == 1


def test_unknown_topic_and_conflicting_delivery_require_reconciliation() -> None:
    core, adapters, _ = _core()
    unknown = core.ingest(_envelope(topic="products/unknown"))
    assert unknown.status.state is InboxState.RECONCILE_REQUIRED
    assert adapters.validator_calls == 0

    projected = core.ingest(_envelope("event-2"))
    generation = core.active_dataset().dataset_generation
    assert projected.status.state is InboxState.PROJECTED
    conflict = core.receive(_envelope("event-2", payload=b'{"different":true}'))
    assert conflict.conflict
    assert not conflict.duplicate
    assert conflict.status.state is InboxState.RECONCILE_REQUIRED
    assert core.active_dataset().dataset_generation == generation
    metrics = core.metrics()
    assert metrics.conflicting_deliveries_total == 1
    assert metrics.reconciliation_decisions_total == 2
    assert metrics.unresolved_reconciliation_events == 2
    reports = core.pending_reconciliation()
    assert [report.key.webhook_id for report in reports] == ["event-1", "event-2"]
    assert all(report.state is InboxState.RECONCILE_REQUIRED for report in reports)
    assert all("payload" not in repr(report) for report in reports)


class HostileError(Exception):
    def __str__(self) -> str:
        raise AssertionError("exception text must never be rendered")


class HostileBaseError(BaseException):
    pass


def test_validation_failure_retries_then_projects_without_leaking_exception_text() -> None:
    adapters = Adapters()
    adapters.validator_failure = HostileError("secret-payload")
    core, _, _ = _core(adapters)
    envelope = _envelope()
    first = core.ingest(envelope)
    assert first.status.state is InboxState.FAILED
    assert first.status.failure_code is FailureCode.VALIDATION_ADAPTER_FAILED
    assert not first.status.dead_letter
    assert core.previous_dataset() is None

    adapters.validator_failure = None
    retry = core.ingest(envelope)
    assert retry.duplicate
    assert retry.status.state is InboxState.PROJECTED
    assert retry.status.failure_code is None
    assert retry.status.processing_attempts == 2
    metrics = core.metrics()
    assert metrics.unresolved_failed_events == 0
    assert metrics.failed_attempts_total == 1


def test_failed_event_becomes_dead_letter_and_is_not_processed_again() -> None:
    adapters = Adapters()
    adapters.validator_failure = ValueError("do not leak")
    core, _, _ = _core(adapters, max_processing_attempts=2)
    envelope = _envelope()
    assert core.ingest(envelope).status.state is InboxState.FAILED
    second = core.ingest(envelope)
    assert second.status.dead_letter
    calls = adapters.validator_calls
    third = core.ingest(envelope)
    assert third.status.dead_letter
    assert adapters.validator_calls == calls
    metrics = core.metrics()
    assert metrics.dead_letter_events == 1
    assert metrics.unresolved_failed_events == 1
    assert metrics.failed_attempts_total == 2
    reports = core.dead_letters()
    assert len(reports) == 1
    assert reports[0].key == envelope.key
    assert reports[0].failure_code is FailureCode.VALIDATION_ADAPTER_FAILED
    assert reports[0].dead_letter
    assert "payload" not in repr(reports[0])


@pytest.mark.parametrize(
    "mutator",
    [
        lambda event: object(),
        lambda event: replace(event, shop_domain="other.myshopify.com"),
        lambda event: replace(event, webhook_id="other-id"),
        lambda event: replace(event, payload_sha256="f" * 64),
        lambda event: replace(event, category=EventCategory.PRODUCT_DELETE),
    ],
)
def test_invalid_validated_event_binding_fails_closed(mutator: Any) -> None:
    adapters = Adapters()

    def invalid_validator(envelope: RawWebhookEnvelope) -> Any:
        return mutator(_validated(envelope))

    records = _records()
    core = SyncCore(
        expected_shop_domain=SHOP,
        initial_reconciled_generation=_reconciled_generation(
            records,
            generated_at=BASE_TIME,
        ),
        validator=invalid_validator,
        projector=adapters.project,
        clock=MutableClock(),
    )
    result = core.ingest(_envelope())
    assert result.status.state is InboxState.FAILED
    assert result.status.failure_code is FailureCode.VALIDATED_EVENT_INVALID
    assert core.previous_dataset() is None


def test_core_rejects_cross_shop_delivery_and_reconciliation() -> None:
    core, adapters, _ = _core()
    original = core.active_dataset()
    with pytest.raises(SyncContractError, match="shop does not match"):
        core.receive(_envelope(shop_domain="other.myshopify.com"))
    assert adapters.validator_calls == 0
    assert core.active_dataset() == original
    assert core.metrics().inbox_events == 0

    with pytest.raises(SyncOperationError, match="shop does not match"):
        core.install_reconciliation(
            shop_domain="other.myshopify.com",
            **_candidate_args(core, _records(), generated_at="2026-09-02T00:02:00Z"),
            expected_active_generation=original.dataset_generation,
        )
    assert core.active_dataset() == original


def test_shop_domain_is_exactly_one_canonical_label() -> None:
    with pytest.raises(SyncContractError):
        WebhookKey("a.b.myshopify.com", "event")
    with pytest.raises(SyncContractError):
        _envelope(shop_domain="a.b.myshopify.com")
    core, _, _ = _core()
    candidate = _candidate_args(core, _records(), generated_at="2026-09-02T00:02:00Z")
    with pytest.raises(SyncContractError):
        core.install_reconciliation(
            shop_domain="a.b.myshopify.com",
            **candidate,
            expected_active_generation=_manifest(_records()).dataset_generation,
        )


def test_projector_failure_invalid_candidate_and_drift_are_isolated() -> None:
    adapters = Adapters()
    adapters.projector_failure = HostileError("commercial-secret")
    core, _, _ = _core(adapters)
    original = core.active_dataset().dataset_generation
    failure = core.ingest(_envelope())
    assert failure.status.failure_code is FailureCode.PROJECTION_ADAPTER_FAILED
    assert core.active_dataset().dataset_generation == original

    adapters.projector_failure = None
    adapters.projector_override = lambda _context, _event: []
    invalid = core.ingest(_envelope())
    assert invalid.status.failure_code is FailureCode.CANDIDATE_INVALID
    assert core.active_dataset().dataset_generation == original

    adapters.projector_override = lambda context, event: (
        replace(context.records[0], commercial_title="Changed target", updated_at=EVENT_TIME),
        replace(context.records[1], commercial_title="Changed unrelated"),
    )
    drift = core.ingest(_envelope())
    assert drift.status.state is InboxState.RECONCILE_REQUIRED
    assert core.active_dataset().dataset_generation == original


@pytest.mark.parametrize("category", [EventCategory.PRODUCT_CREATE, EventCategory.PRODUCT_UPDATE])
def test_candidate_rejects_globally_duplicate_source_identity(category: EventCategory) -> None:
    adapters = Adapters()
    adapters.category = category
    if category is EventCategory.PRODUCT_CREATE:
        adapters.product_id = "3"

    def duplicate_source(
        context: ProjectionContext, event: ValidatedWebhookEvent
    ) -> tuple[CatalogProductRecordV1, ...]:
        if category is EventCategory.PRODUCT_CREATE:
            duplicate = replace(
                _product("3", updated_at=event.source_updated_at),
                powertools_source_id="1",
                sync_source_id="1",
            )
            return (*context.records, duplicate)
        target = context.records[0]
        return (
            replace(
                target,
                powertools_source_id="2",
                sync_source_id="2",
                updated_at=event.source_updated_at,
                variants=(replace(target.variants[0], updated_at=event.source_updated_at),),
            ),
            context.records[1],
        )

    adapters.projector_override = duplicate_source
    core, _, _ = _core(adapters)
    topic = "products/create" if category is EventCategory.PRODUCT_CREATE else "products/update"
    result = core.ingest(_envelope(f"duplicate-source-{category.value}", topic=topic))
    assert result.status.state is InboxState.FAILED
    assert result.status.failure_code is FailureCode.CANDIDATE_INVALID
    assert core.active_dataset().records == _records()


def test_clock_and_activation_failures_leave_active_generation_unchanged_then_retry() -> None:
    adapters = Adapters()

    class BrokenClock:
        def __call__(self) -> str:
            raise HostileError("clock-secret")

    core, _, _ = _core(adapters, clock=BrokenClock())
    original = core.active_dataset().dataset_generation
    failed = core.ingest(_envelope())
    assert failed.status.failure_code is FailureCode.CLOCK_FAILED
    assert core.active_dataset().dataset_generation == original

    attempts = {ActivationKind.EVENT: 0}

    def fail_once(kind: ActivationKind) -> None:
        if kind is ActivationKind.EVENT and attempts[kind] == 0:
            attempts[kind] += 1
            raise HostileError("activation-secret")

    core, adapters, _ = _core(probe=fail_once)
    first = core.ingest(_envelope())
    assert first.status.failure_code is FailureCode.ACTIVATION_FAILED
    assert core.previous_dataset() is None
    second = core.ingest(_envelope())
    assert second.status.state is InboxState.PROJECTED
    assert adapters.projector_calls == 2


def test_retry_reuses_the_first_validated_event_and_digest_without_semantic_drift() -> None:
    adapters = Adapters()
    adapters.projector_failure = HostileError("first-attempt-only")
    core, _, _ = _core(adapters)
    envelope = _envelope("frozen-retry")

    first = core.ingest(envelope)
    assert first.status.state is InboxState.FAILED
    assert first.status.failure_code is FailureCode.PROJECTION_ADAPTER_FAILED
    frozen_entry = core._entries[(SHOP, envelope.webhook_id)]
    assert frozen_entry.validated_event == _validated(envelope)
    assert frozen_entry.event_identity_sha256 == sync._event_identity_sha256(
        envelope, _validated(envelope)
    )

    adapters.projector_failure = None
    adapters.product_id = "2"
    adapters.category = EventCategory.PRODUCT_UNPUBLISH
    adapters.source_updated_at = "2026-09-02T00:04:00Z"
    retried = core.ingest(envelope)

    assert retried.status.state is InboxState.PROJECTED
    assert retried.status.category is EventCategory.PRODUCT_UPDATE
    assert adapters.validator_calls == 1
    active = core.active_dataset()
    assert active.source_cut_at == EVENT_TIME
    assert active.records[0].variants[0].price_text == "9.9900"
    assert active.records[1] == _records()[1]


def test_frozen_event_digest_tamper_and_validation_race_fail_closed() -> None:
    adapters = Adapters()
    adapters.projector_failure = HostileError("freeze-event")
    core, _, _ = _core(adapters)
    envelope = _envelope("tampered-frozen")
    assert core.ingest(envelope).status.state is InboxState.FAILED
    entry = core._entries[(SHOP, envelope.webhook_id)]
    assert entry.validated_event is not None
    object.__setattr__(entry.validated_event, "product_gid", "gid://shopify/Product/2")
    assert core.process(envelope.key).state is InboxState.RECONCILE_REQUIRED

    holder: dict[str, SyncCore] = {}

    def racing_validator(value: RawWebhookEnvelope) -> ValidatedWebhookEvent:
        current = holder["core"]._entries[(SHOP, value.webhook_id)]
        other = _validated(value, product_id="2")
        holder["core"]._entries[(SHOP, value.webhook_id)] = replace(
            current,
            validated_event=other,
            event_identity_sha256=sync._event_identity_sha256(value, other),
        )
        return _validated(value)

    records = _records()
    other_core = SyncCore(
        expected_shop_domain=SHOP,
        initial_reconciled_generation=_reconciled_generation(
            records,
            generated_at=BASE_TIME,
        ),
        validator=racing_validator,
        projector=Adapters().project,
        clock=MutableClock(),
    )
    holder["core"] = other_core
    assert other_core.ingest(_envelope("validation-race")).status.state is (
        InboxState.RECONCILE_REQUIRED
    )


@pytest.mark.parametrize("stage", ["validator", "projector", "activation"])
def test_base_exceptions_are_not_swallowed_and_cannot_activate(stage: str) -> None:
    adapters = Adapters()
    probe = None
    if stage == "validator":
        adapters.validator_failure = HostileBaseError()
    elif stage == "projector":
        adapters.projector_failure = HostileBaseError()
    else:

        def raise_base_error(_kind: ActivationKind) -> None:
            raise HostileBaseError

        probe = raise_base_error
    core, _, _ = _core(adapters, probe=probe)
    original = core.active_dataset().dataset_generation
    with pytest.raises(HostileBaseError):
        core.ingest(_envelope())
    assert core.active_dataset().dataset_generation == original


def test_out_of_order_equal_and_missing_target_events_require_reconciliation() -> None:
    for index, timestamp in enumerate(("2026-09-01T23:59:59Z", BASE_TIME), start=1):
        adapters = Adapters()
        adapters.source_updated_at = timestamp
        core, _, _ = _core(adapters)
        result = core.ingest(_envelope(f"stale-{index}"))
        assert result.status.state is InboxState.RECONCILE_REQUIRED
        assert core.previous_dataset() is None

    adapters = Adapters()
    adapters.product_id = "999"
    core, _, _ = _core(adapters)
    missing = core.ingest(_envelope("missing"))
    assert missing.status.state is InboxState.RECONCILE_REQUIRED


def test_newer_then_older_event_and_concurrent_duplicate_are_race_safe() -> None:
    adapters = Adapters()
    core, _, _ = _core(adapters)
    first = core.ingest(_envelope("newer"))
    assert first.status.state is InboxState.PROJECTED
    adapters.source_updated_at = "2026-09-02T00:00:30Z"
    older = core.ingest(_envelope("older", received_at="2026-09-02T00:01:30Z"))
    assert older.status.state is InboxState.RECONCILE_REQUIRED

    adapters = Adapters()
    core, _, _ = _core(adapters)
    envelope = _envelope("concurrent")
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _index: core.ingest(envelope), range(24)))
    assert sum(not result.duplicate for result in results) == 1
    assert all(result.status.state is InboxState.PROJECTED for result in results)
    assert adapters.validator_calls == 1
    assert adapters.projector_calls == 1
    assert core.metrics().duplicate_deliveries_total == 23


def test_rollback_pause_and_full_reconciliation_recovery() -> None:
    core, adapters, clock = _core()
    with pytest.raises(SyncOperationError, match="No previous"):
        core.rollback(expected_active_generation=core.active_dataset().dataset_generation)
    projected = core.ingest(_envelope())
    projected_generation = projected.status.projected_generation or ""
    with pytest.raises(SyncOperationError, match="changed before rollback"):
        core.rollback(expected_active_generation="sha256:" + "f" * 64)
    base_generation = core.rollback(expected_active_generation=projected_generation)

    paused = core.ingest(_envelope("paused", received_at="2026-09-02T00:02:00Z"))
    assert paused.status.state is InboxState.RECONCILE_REQUIRED
    base_records = _records()
    candidate = _candidate_args(core, base_records, generated_at="2026-09-02T00:02:00Z")
    installed = core.install_reconciliation(
        shop_domain=SHOP,
        **candidate,
        expected_active_generation=base_generation,
    )
    assert installed == candidate["reconciled_generation"].dataset_manifest.dataset_generation
    metrics = core.metrics()
    assert not metrics.projection_paused
    assert metrics.unresolved_reconciliation_events == 0
    assert metrics.reconciliation_installs_total == 1
    assert core.previous_dataset() is not None

    adapters.source_updated_at = "2026-09-02T00:03:00Z"
    clock.value = "2026-09-02T00:03:01Z"
    resumed = core.ingest(_envelope("resumed", received_at="2026-09-02T00:03:00Z"))
    assert resumed.status.state is InboxState.PROJECTED


def test_reconciled_v2_boundary_installs_from_memory_without_opening_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core, _, _ = _core()
    active = core.active_dataset()
    fence = core.capture_reconciliation_fence(expected_active_generation=active.dataset_generation)
    reconciled = _reconciled_generation(_records(), generated_at="2026-09-02T00:02:00Z")

    def forbid_path_open(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("the in-memory sync boundary must not read a Path")

    monkeypatch.setattr(Path, "open", forbid_path_open)
    installed = core.install_reconciliation(
        shop_domain=SHOP,
        fence=fence,
        reconciled_generation=reconciled,
        expected_active_generation=active.dataset_generation,
    )
    assert installed == reconciled.dataset_manifest.dataset_generation
    assert core.active_dataset().records == reconciled.records


def test_reconciled_v2_boundary_rejects_wrong_types_report_and_part_order() -> None:
    core, _, _ = _core()
    active = core.active_dataset()
    fence = core.capture_reconciliation_fence(expected_active_generation=active.dataset_generation)
    with pytest.raises(SyncOperationError, match="validation, catch-up"):
        core.install_reconciliation(
            shop_domain=SHOP,
            fence=fence,
            reconciled_generation=object(),  # type: ignore[arg-type]
            expected_active_generation=active.dataset_generation,
        )
    with pytest.raises(SyncContractError, match="fence must be canonical"):
        core.install_reconciliation(
            shop_domain=SHOP,
            fence=object(),  # type: ignore[arg-type]
            reconciled_generation=_reconciled_generation(
                _records(), generated_at="2026-09-02T00:02:00Z"
            ),
            expected_active_generation=active.dataset_generation,
        )

    reconciled = _reconciled_generation(_records(), generated_at="2026-09-02T00:02:00Z")
    with pytest.raises(SyncOperationError, match="validation, catch-up"):
        core.install_reconciliation(
            shop_domain=SHOP,
            fence=fence,
            reconciled_generation=replace(reconciled, source_manifest=object()),
            expected_active_generation=active.dataset_generation,
        )
    malformed_source = replace(
        reconciled.source_manifest,
        parts=(object(), reconciled.source_manifest.parts[1]),
    )
    with pytest.raises(SyncOperationError, match="validation, catch-up"):
        core.install_reconciliation(
            shop_domain=SHOP,
            fence=fence,
            reconciled_generation=replace(reconciled, source_manifest=malformed_source),
            expected_active_generation=active.dataset_generation,
        )
    forged_report = replace(reconciled.taxonomy_report, total=3)
    with pytest.raises(SyncOperationError, match="validation, catch-up"):
        core.install_reconciliation(
            shop_domain=SHOP,
            fence=fence,
            reconciled_generation=replace(reconciled, taxonomy_report=forged_report),
            expected_active_generation=active.dataset_generation,
        )

    forged_source = replace(
        reconciled.source_manifest,
        parts=tuple(reversed(reconciled.source_manifest.parts)),
    )
    with pytest.raises(SyncOperationError, match="validation, catch-up"):
        core.install_reconciliation(
            shop_domain=SHOP,
            fence=fence,
            reconciled_generation=replace(
                reconciled,
                source_manifest=forged_source,
                source_manifest_bytes=forged_source.to_json_bytes(),
            ),
            expected_active_generation=active.dataset_generation,
        )
    assert core.active_dataset() == active


@pytest.mark.parametrize(
    "forgery",
    ["mixed-capture", "same-operation", "query", "no-overlap", "oversized-window"],
)
def test_reconciled_v2_boundary_rejects_self_consistent_part_forgeries(
    forgery: str,
) -> None:
    core, _, _ = _core()
    active = core.active_dataset()
    fence = core.capture_reconciliation_fence(expected_active_generation=active.dataset_generation)
    reconciled = _reconciled_generation(_records(), generated_at="2026-09-02T00:02:00Z")
    products, variants = reconciled.source_manifest.parts
    if forgery == "mixed-capture":
        variants = _replace_reconciled_part(variants, snapshot_set_id="sha256:" + "2" * 64)
    elif forgery == "same-operation":
        variants = _replace_reconciled_part(variants, operation_id=products.operation_id)
    elif forgery == "query":
        variants = _replace_reconciled_part(variants, query_sha256="0" * 64)
    elif forgery == "no-overlap":
        products = _replace_reconciled_part(
            products,
            created_at="2026-09-02T00:02:00Z",
            completed_at="2026-09-02T00:03:00Z",
        )
        variants = _replace_reconciled_part(
            variants,
            created_at="2026-09-02T00:04:00Z",
            completed_at="2026-09-02T00:05:00Z",
        )
    else:
        products = _replace_reconciled_part(
            products,
            created_at="2026-09-02T00:00:00Z",
            completed_at="2026-09-03T00:00:00Z",
        )
        variants = _replace_reconciled_part(
            variants,
            created_at="2026-09-02T23:59:00Z",
            completed_at="2026-09-03T23:59:00Z",
        )
    forged_source = replace(reconciled.source_manifest, parts=(products, variants))
    forged = replace(
        reconciled,
        source_manifest=forged_source,
        source_manifest_bytes=forged_source.to_json_bytes(),
    )
    with pytest.raises(SyncOperationError, match="validation, catch-up"):
        core.install_reconciliation(
            shop_domain=SHOP,
            fence=fence,
            reconciled_generation=forged,
            expected_active_generation=active.dataset_generation,
        )
    assert core.active_dataset() == active


def test_reconciliation_fence_replays_frozen_post_fence_event_before_commit() -> None:
    adapters = Adapters()
    core, _, clock = _core(adapters)
    original = core.active_dataset()
    fence = core.capture_reconciliation_fence(
        expected_active_generation=original.dataset_generation
    )
    reconciled = _reconciled_generation(_records(), generated_at="2026-09-02T00:02:00Z")

    adapters.source_updated_at = "2026-09-02T00:03:00Z"
    delivery = core.ingest(_envelope("post-fence", received_at="2026-09-02T00:03:00Z"))
    assert delivery.status.state is InboxState.VALIDATED
    assert core.active_dataset() == original
    assert core.metrics().projection_paused

    adapters.product_id = "2"
    adapters.category = EventCategory.PRODUCT_UNPUBLISH
    adapters.source_updated_at = "2026-09-02T00:04:00Z"
    clock.value = "2026-09-02T00:04:01Z"
    installed = core.install_reconciliation(
        shop_domain=SHOP,
        fence=fence,
        reconciled_generation=reconciled,
        expected_active_generation=original.dataset_generation,
    )

    active = core.active_dataset()
    assert installed == active.dataset_generation
    assert active.dataset_generation != reconciled.dataset_manifest.dataset_generation
    assert active.source_cut_at == "2026-09-02T00:03:00Z"
    assert active.records[0].variants[0].price_text == "9.9900"
    assert active.records[1] == _records()[1]
    assert core.event_status(delivery.key).state is InboxState.PROJECTED
    assert adapters.validator_calls == 1
    assert not core.metrics().projection_paused


@pytest.mark.parametrize("failure_mode", ["failed", "conflicting", "unprocessed"])
def test_post_fence_unresolved_delivery_blocks_reconciliation_install(
    failure_mode: str,
) -> None:
    adapters = Adapters()
    core, _, _ = _core(adapters)
    original = core.active_dataset()
    fence = core.capture_reconciliation_fence(
        expected_active_generation=original.dataset_generation
    )
    reconciled = _reconciled_generation(_records(), generated_at="2026-09-02T00:02:00Z")
    envelope = _envelope("post-fence-unresolved")
    if failure_mode == "failed":
        adapters.validator_failure = HostileError("redacted")
        assert core.ingest(envelope).status.state is InboxState.FAILED
    elif failure_mode == "conflicting":
        assert core.ingest(envelope).status.state is InboxState.VALIDATED
        assert core.receive(
            _envelope("post-fence-unresolved", payload=b'{"different":true}')
        ).conflict
    else:
        assert core.receive(envelope).status.state is InboxState.RECEIVED

    with pytest.raises(SyncOperationError, match="catch-up is incomplete"):
        core.install_reconciliation(
            shop_domain=SHOP,
            fence=fence,
            reconciled_generation=reconciled,
            expected_active_generation=original.dataset_generation,
        )
    assert core.active_dataset() == original
    metrics = core.metrics()
    assert metrics.projection_paused
    assert metrics.stale


def test_reconciliation_fence_is_core_bound_and_tamper_evident() -> None:
    core, _, _ = _core()
    active = core.active_dataset()
    fence = core.capture_reconciliation_fence(expected_active_generation=active.dataset_generation)
    reconciled = _reconciled_generation(_records(), generated_at="2026-09-02T00:02:00Z")
    forged = replace(fence, delivery_sequence=fence.delivery_sequence + 1)
    assert type(forged) is ReconciliationFence
    with pytest.raises(SyncOperationError, match="fence is not active"):
        core.install_reconciliation(
            shop_domain=SHOP,
            fence=forged,
            reconciled_generation=reconciled,
            expected_active_generation=active.dataset_generation,
        )
    with pytest.raises(SyncOperationError, match="active reconciliation fence"):
        core.rollback(expected_active_generation=active.dataset_generation)


@pytest.mark.parametrize("failure_mode", ["exception", "invalid-return"])
def test_fence_token_failure_is_value_free_and_preserves_registered_fence(
    failure_mode: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core, _, _ = _core()
    active = core.active_dataset()
    registered = core.capture_reconciliation_fence(
        expected_active_generation=active.dataset_generation
    )

    def fail_token(_size: int) -> str:
        if failure_mode == "exception":
            raise HostileError("SECRET_TOKEN_FAILURE")
        return "not-a-token"

    monkeypatch.setattr(sync.secrets, "token_hex", fail_token)
    with pytest.raises(SyncOperationError) as caught:
        core.capture_reconciliation_fence(expected_active_generation=active.dataset_generation)
    assert str(caught.value) == "Reconciliation fence creation failed."
    assert core._active_reconciliation_fence == registered
    assert core.metrics().projection_paused


def test_fence_token_base_exception_propagates_without_partial_fence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core, _, _ = _core()
    active = core.active_dataset()

    def abort_token(_size: int) -> str:
        raise HostileBaseError()

    monkeypatch.setattr(sync.secrets, "token_hex", abort_token)
    with pytest.raises(HostileBaseError):
        core.capture_reconciliation_fence(expected_active_generation=active.dataset_generation)
    assert core._active_reconciliation_fence is None
    assert not core.metrics().projection_paused


def test_reconciliation_fence_rejects_wrong_generation_and_changed_active_pair() -> None:
    core, _, _ = _core()
    active = core.active_dataset()
    with pytest.raises(SyncOperationError, match="changed before the reconciliation fence"):
        core.capture_reconciliation_fence(expected_active_generation="sha256:" + "f" * 64)

    fence = core.capture_reconciliation_fence(expected_active_generation=active.dataset_generation)
    reconciled = _reconciled_generation(_records(), generated_at="2026-09-02T00:02:00Z")
    object.__setattr__(core._pair.active.generation, "dataset_generation", "sha256:" + "e" * 64)
    with pytest.raises(SyncOperationError, match="changed before reconciliation"):
        core.install_reconciliation(
            shop_domain=SHOP,
            fence=fence,
            reconciled_generation=reconciled,
            expected_active_generation=active.dataset_generation,
        )


def test_reconciliation_rejects_build_time_behind_generation_high_watermark() -> None:
    clock = MutableClock("2026-09-02T00:05:00Z")
    core, _, _ = _core(clock=clock)
    assert core.ingest(_envelope("future-build")).status.state is InboxState.PROJECTED
    active = core.active_dataset()
    clock.value = "2026-09-02T00:01:30Z"
    fence = core.capture_reconciliation_fence(expected_active_generation=active.dataset_generation)
    reconciled = _reconciled_generation(active.records, generated_at="2026-09-02T00:02:00Z")
    with pytest.raises(SyncOperationError, match="validation, catch-up"):
        core.install_reconciliation(
            shop_domain=SHOP,
            fence=fence,
            reconciled_generation=reconciled,
            expected_active_generation=active.dataset_generation,
        )
    assert core.active_dataset() == active


def test_stale_post_fence_event_must_be_an_exact_noop_to_install() -> None:
    adapters = Adapters()
    core, _, _ = _core(adapters)
    active = core.active_dataset()
    fence = core.capture_reconciliation_fence(expected_active_generation=active.dataset_generation)
    reconciled = _reconciled_generation(_records(), generated_at="2026-09-02T00:02:00Z")
    assert core.ingest(_envelope("stale-post-fence")).status.state is InboxState.VALIDATED
    with pytest.raises(SyncOperationError, match="validation, catch-up"):
        core.install_reconciliation(
            shop_domain=SHOP,
            fence=fence,
            reconciled_generation=reconciled,
            expected_active_generation=active.dataset_generation,
        )
    assert core.active_dataset() == active

    adapters = Adapters()
    adapters.projector_override = lambda context, _event: context.records
    core, _, _ = _core(adapters)
    active = core.active_dataset()
    fence = core.capture_reconciliation_fence(expected_active_generation=active.dataset_generation)
    reconciled = _reconciled_generation(_records(), generated_at="2026-09-02T00:02:00Z")
    delivery = core.ingest(_envelope("stale-noop"))
    assert delivery.status.state is InboxState.VALIDATED
    assert (
        core.install_reconciliation(
            shop_domain=SHOP,
            fence=fence,
            reconciled_generation=reconciled,
            expected_active_generation=active.dataset_generation,
        )
        == reconciled.dataset_manifest.dataset_generation
    )
    assert core.event_status(delivery.key).state is InboxState.PROJECTED


@pytest.mark.parametrize("tamper", ["topic", "digest", "state"])
def test_reconciliation_catch_up_revalidates_frozen_entry_at_both_boundaries(
    tamper: str,
) -> None:
    holder: dict[str, SyncCore] = {}

    def probe(kind: ActivationKind) -> None:
        if tamper == "state" and kind is ActivationKind.RECONCILIATION:
            core = holder["core"]
            key = (SHOP, "tampered-catch-up")
            core._entries[key] = replace(core._entries[key], state=InboxState.FAILED)

    core, adapters, clock = _core(probe=probe)
    holder["core"] = core
    active = core.active_dataset()
    fence = core.capture_reconciliation_fence(expected_active_generation=active.dataset_generation)
    reconciled = _reconciled_generation(_records(), generated_at="2026-09-02T00:02:00Z")
    adapters.source_updated_at = "2026-09-02T00:03:00Z"
    envelope = _envelope(
        "tampered-catch-up",
        received_at="2026-09-02T00:03:00Z",
    )
    adapters_entry = core.ingest(envelope)
    assert adapters_entry.status.state is InboxState.VALIDATED
    key = (SHOP, envelope.webhook_id)
    if tamper == "topic":
        object.__setattr__(core._entries[key].envelope, "topic", "products/unknown")
    elif tamper == "digest":
        core._entries[key] = replace(core._entries[key], event_identity_sha256="f" * 64)
    clock.value = "2026-09-02T00:04:00Z"
    message = "Deliveries changed" if tamper == "state" else "validation, catch-up"
    with pytest.raises(SyncOperationError, match=message):
        core.install_reconciliation(
            shop_domain=SHOP,
            fence=fence,
            reconciled_generation=reconciled,
            expected_active_generation=active.dataset_generation,
        )
    assert core.active_dataset() == active


def test_projected_duplicate_after_fence_is_replayed_as_idempotent_noop() -> None:
    core, adapters, _ = _core()
    envelope = _envelope("projected-before-fence")
    assert core.ingest(envelope).status.state is InboxState.PROJECTED
    active = core.active_dataset()
    fence = core.capture_reconciliation_fence(expected_active_generation=active.dataset_generation)
    reconciled = _reconciled_generation(active.records, generated_at="2026-09-02T00:02:00Z")
    duplicate = core.receive(
        _envelope(
            "projected-before-fence",
            received_at="2026-09-02T00:03:00Z",
        )
    )
    assert duplicate.duplicate
    installed = core.install_reconciliation(
        shop_domain=SHOP,
        fence=fence,
        reconciled_generation=reconciled,
        expected_active_generation=active.dataset_generation,
    )
    assert installed == reconciled.dataset_manifest.dataset_generation
    assert adapters.validator_calls == 1


def test_post_fence_duplicate_cannot_reorder_distinct_events_for_one_product() -> None:
    adapters = Adapters()

    def deterministic_projection(
        context: ProjectionContext, event: ValidatedWebhookEvent
    ) -> tuple[CatalogProductRecordV1, ...]:
        target = context.records[0]
        price = "3.0000" if event.source_updated_at.endswith("03:00Z") else "4.0000"
        variant = replace(
            target.variants[0],
            price_text=price,
            updated_at=event.source_updated_at,
        )
        return (
            replace(target, updated_at=event.source_updated_at, variants=(variant,)),
            context.records[1],
        )

    adapters.projector_override = deterministic_projection
    core, _, clock = _core(adapters)
    active = core.active_dataset()
    fence = core.capture_reconciliation_fence(expected_active_generation=active.dataset_generation)
    reconciled = _reconciled_generation(_records(), generated_at="2026-09-02T00:02:00Z")
    first_envelope = _envelope("first-after-fence", payload=b'{"event":1}')
    adapters.source_updated_at = "2026-09-02T00:03:00Z"
    assert core.ingest(first_envelope).status.state is InboxState.VALIDATED
    adapters.source_updated_at = "2026-09-02T00:04:00Z"
    assert (
        core.ingest(_envelope("second-after-fence", payload=b'{"event":2}')).status.state
        is InboxState.VALIDATED
    )
    assert core.receive(first_envelope).duplicate

    clock.value = "2026-09-02T00:05:00Z"
    core.install_reconciliation(
        shop_domain=SHOP,
        fence=fence,
        reconciled_generation=reconciled,
        expected_active_generation=active.dataset_generation,
    )
    assert core.active_dataset().records[0].variants[0].price_text == "4.0000"


def test_reconciliation_and_rollback_probes_fail_without_a_partial_swap() -> None:
    kinds: list[ActivationKind] = []

    def probe(kind: ActivationKind) -> None:
        kinds.append(kind)
        if kind is not ActivationKind.EVENT:
            raise HostileError("probe-secret")

    core, _, _ = _core(probe=probe)
    projected = core.ingest(_envelope())
    generation = core.active_dataset().dataset_generation
    with pytest.raises(SyncOperationError, match="Rollback validation"):
        core.rollback(expected_active_generation=projected.status.projected_generation or "")
    assert core.active_dataset().dataset_generation == generation
    with pytest.raises(SyncOperationError, match="activation"):
        core.install_reconciliation(
            shop_domain=SHOP,
            **_candidate_args(core, _records(), generated_at="2026-09-02T00:02:00Z"),
            expected_active_generation=generation,
        )
    assert core.active_dataset().dataset_generation == generation
    assert kinds == [ActivationKind.EVENT, ActivationKind.ROLLBACK, ActivationKind.RECONCILIATION]


def test_reconciliation_rejects_generation_race_and_invalid_input() -> None:
    core, _, _ = _core()
    current = core.active_dataset().dataset_generation
    with pytest.raises(SyncOperationError, match="fence does not match"):
        core.install_reconciliation(
            shop_domain=SHOP,
            **_candidate_args(core, _records(), generated_at="2026-09-02T00:02:00Z"),
            expected_active_generation="sha256:" + "f" * 64,
        )
    candidate = _candidate_args(core, _records(), generated_at="2026-09-02T00:02:00Z")
    forged = replace(
        candidate["reconciled_generation"],
        records=(_records()[0],),
    )
    with pytest.raises(SyncOperationError, match="validation, catch-up"):
        core.install_reconciliation(
            shop_domain=SHOP,
            fence=candidate["fence"],
            reconciled_generation=forged,
            expected_active_generation=current,
        )


def test_reconciliation_rejects_stale_source_cut_manifest_and_build_time() -> None:
    core, _, clock = _core()
    projected = core.ingest(_envelope())
    active = core.active_dataset()
    assert active.records[0].variants[0].price_text == "9.9900"
    assert active.source_cut_at == EVENT_TIME

    with pytest.raises(SyncOperationError, match="validation, catch-up"):
        core.install_reconciliation(
            shop_domain=SHOP,
            **_candidate_args(core, _records(), generated_at=BASE_TIME),
            expected_active_generation=projected.status.projected_generation or "",
        )
    with pytest.raises(SyncOperationError, match="validation, catch-up"):
        core.install_reconciliation(
            shop_domain=SHOP,
            **_candidate_args(core, _records(), generated_at="2026-09-02T00:01:00.500000Z"),
            expected_active_generation=active.dataset_generation,
        )
    clock.value = "2026-09-02T00:00:30Z"
    with pytest.raises(SyncOperationError, match="validation, catch-up"):
        core.install_reconciliation(
            shop_domain=SHOP,
            **_candidate_args(core, _records(), generated_at=EVENT_TIME),
            expected_active_generation=active.dataset_generation,
        )
    assert core.active_dataset() == active


def test_reconciliation_rejects_forged_or_foreign_source_evidence() -> None:
    core, _, _ = _core()
    projected = core.ingest(_envelope())
    active = core.active_dataset()
    assert active.records[0].variants[0].price_text == "9.9900"

    candidate = _candidate_args(core, _records(), generated_at="2026-09-02T00:02:00Z")
    generation = candidate["reconciled_generation"]
    forged_manifest = replace(
        generation.dataset_manifest,
        generated_at="2026-09-02T00:02:30Z",
    )
    with pytest.raises(SyncOperationError, match="validation, catch-up"):
        core.install_reconciliation(
            shop_domain=SHOP,
            fence=candidate["fence"],
            reconciled_generation=replace(generation, dataset_manifest=forged_manifest),
            expected_active_generation=projected.status.projected_generation or "",
        )

    candidate = _candidate_args(core, _records(), generated_at="2026-09-02T00:02:00Z")
    generation = candidate["reconciled_generation"]
    with pytest.raises(SyncOperationError, match="validation, catch-up"):
        core.install_reconciliation(
            shop_domain=SHOP,
            fence=candidate["fence"],
            reconciled_generation=replace(
                generation,
                source_manifest_bytes=generation.source_manifest_bytes + b" ",
            ),
            expected_active_generation=active.dataset_generation,
        )

    candidate = _candidate_args(core, _records(), generated_at="2026-09-02T00:02:00Z")
    generation = candidate["reconciled_generation"]
    forged_source = replace(
        generation.source_manifest,
        source_identity_product_count=generation.source_manifest.source_identity_product_count + 1,
    )
    with pytest.raises(SyncOperationError, match="validation, catch-up"):
        core.install_reconciliation(
            shop_domain=SHOP,
            fence=candidate["fence"],
            reconciled_generation=replace(generation, source_manifest=forged_source),
            expected_active_generation=active.dataset_generation,
        )

    foreign = _candidate_args(
        core,
        _records(),
        generated_at="2026-09-02T00:02:00Z",
        shop_domain="other.myshopify.com",
    )
    with pytest.raises(SyncOperationError, match="validation, catch-up"):
        core.install_reconciliation(
            shop_domain=SHOP,
            **foreign,
            expected_active_generation=active.dataset_generation,
        )
    assert core.active_dataset() == active


def test_reconciliation_cut_blocks_received_and_failed_event_replay() -> None:
    core, adapters, _ = _core()
    received = core.receive(_envelope("received-before-cut"))
    current = core.active_dataset().dataset_generation
    core.install_reconciliation(
        shop_domain=SHOP,
        **_candidate_args(core, _records(), generated_at="2026-09-02T00:02:00Z"),
        expected_active_generation=current,
    )
    installed = core.active_dataset()
    received_status = core.process(received.key)
    assert received_status.state is InboxState.PROJECTED
    assert received_status.projected_generation == installed.dataset_generation
    assert received_status.reconciliation_generation == installed.dataset_generation
    assert adapters.projector_calls == 0
    assert core.active_dataset() == installed
    assert installed.records[0].variants[0].price_text == "1.2300"
    assert installed.source_cut_at == "2026-09-02T00:02:00Z"

    failing_adapters = Adapters()
    failing_adapters.projector_failure = HostileError("never render")
    other, _, _ = _core(failing_adapters)
    failed = other.ingest(_envelope("failed-before-cut"))
    assert failed.status.state is InboxState.FAILED
    other.install_reconciliation(
        shop_domain=SHOP,
        **_candidate_args(other, _records(), generated_at="2026-09-02T00:02:00Z"),
        expected_active_generation=other.active_dataset().dataset_generation,
    )
    reconciled = other.active_dataset()
    calls = failing_adapters.projector_calls
    failing_adapters.projector_failure = None
    retry = other.process(failed.key)
    assert retry.state is InboxState.PROJECTED
    assert retry.failure_code is None
    assert retry.projected_generation == reconciled.dataset_generation
    assert retry.reconciliation_generation == reconciled.dataset_generation
    assert failing_adapters.projector_calls == calls
    assert other.active_dataset() == reconciled


@pytest.mark.parametrize(
    "starting_state",
    ["received", "validated", "failed", "projected", "reconcile_required"],
)
def test_pre_fence_resolution_is_monotonic_terminal_and_auditable(
    starting_state: str,
) -> None:
    adapters = Adapters()
    core, _, _ = _core(adapters)
    envelope = _envelope(f"covered-{starting_state}")
    if starting_state == "received":
        delivery = core.receive(envelope)
    elif starting_state == "validated":
        active = core.active_dataset().dataset_generation
        core.capture_reconciliation_fence(expected_active_generation=active)
        delivery = core.ingest(envelope)
    elif starting_state == "failed":
        adapters.validator_failure = HostileError("redacted")
        delivery = core.ingest(envelope)
        adapters.validator_failure = None
    elif starting_state == "projected":
        delivery = core.ingest(envelope)
    else:
        envelope = _envelope(
            f"covered-{starting_state}",
            topic="products/unknown",
        )
        delivery = core.ingest(envelope)

    before = core.event_status(delivery.key)
    assert before.state.value == starting_state
    before_rank = sync._STATE_RANK[before.state]
    calls = (adapters.validator_calls, adapters.projector_calls)
    active = core.active_dataset()
    fence = core.capture_reconciliation_fence(expected_active_generation=active.dataset_generation)
    installed = core.install_reconciliation(
        shop_domain=SHOP,
        fence=fence,
        reconciled_generation=_reconciled_generation(
            active.records,
            generated_at="2026-09-02T00:02:00Z",
        ),
        expected_active_generation=active.dataset_generation,
    )

    after = core.event_status(delivery.key)
    expected_state = (
        InboxState.RECONCILE_REQUIRED
        if before.state is InboxState.RECONCILE_REQUIRED
        else InboxState.PROJECTED
    )
    assert after.state is expected_state
    assert sync._STATE_RANK[after.state] >= before_rank
    assert after.reconciliation_generation == installed
    if before_rank < sync._STATE_RANK[InboxState.PROJECTED]:
        assert after.projected_generation == installed
        assert after.failure_code is None
    else:
        assert after.projected_generation == before.projected_generation
    assert core.process(delivery.key) == after
    assert (adapters.validator_calls, adapters.projector_calls) == calls
    assert core.pending_reconciliation() == ()
    assert core.dead_letters() == ()
    metrics = core.metrics()
    assert metrics.unresolved_failed_events == 0
    assert metrics.unresolved_reconciliation_events == 0
    assert not metrics.projection_paused
    assert not metrics.stale


def test_conflict_after_reconciliation_resolution_preserves_audit_and_reopens_pending() -> None:
    core, _, _ = _core()
    envelope = _envelope("resolved-conflict", topic="products/unknown")
    delivery = core.ingest(envelope)
    before = core.event_status(delivery.key)
    assert before.state is InboxState.RECONCILE_REQUIRED
    active = core.active_dataset()
    installed = core.install_reconciliation(
        shop_domain=SHOP,
        **_candidate_args(
            core,
            active.records,
            generated_at="2026-09-02T00:02:00Z",
        ),
        expected_active_generation=active.dataset_generation,
    )
    resolved = core.event_status(delivery.key)
    assert resolved.state is InboxState.RECONCILE_REQUIRED
    assert resolved.reconciliation_generation == installed
    assert core.pending_reconciliation() == ()

    conflict = core.receive(
        _envelope(
            "resolved-conflict",
            topic="products/unknown",
            payload=b'{"conflict":true}',
        )
    )
    assert conflict.conflict
    assert conflict.status.state is InboxState.RECONCILE_REQUIRED
    assert conflict.status.reconciliation_generation is None
    pending = core.pending_reconciliation()
    assert len(pending) == 1
    assert pending[0].state is InboxState.RECONCILE_REQUIRED
    assert pending[0].reconciliation_generation is None


def test_rollback_does_not_lower_reconciliation_high_watermarks() -> None:
    core, _, _ = _core()
    projected = core.ingest(_envelope())
    base_generation = core.rollback(
        expected_active_generation=projected.status.projected_generation or ""
    )
    rolled_back = core.active_dataset()
    assert rolled_back.source_cut_at == BASE_TIME

    with pytest.raises(SyncOperationError, match="validation, catch-up"):
        core.install_reconciliation(
            shop_domain=SHOP,
            **_candidate_args(core, _records(), generated_at="2026-09-02T00:00:30Z"),
            expected_active_generation=base_generation,
        )
    assert core.active_dataset() == rolled_back
    assert core.metrics().projection_paused
    assert core.metrics().stale


@pytest.mark.parametrize("arrival_phase", ["build", "activation"])
def test_reconciliation_preserves_conflict_arriving_after_captured_watermark(
    arrival_phase: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    holder: dict[str, SyncCore] = {}

    def inject_conflict() -> None:
        holder["core"].receive(
            _envelope(
                payload=b'{"conflict":"during-reconciliation"}',
                received_at="2026-09-02T00:00:30Z",
            )
        )

    def probe(kind: ActivationKind) -> None:
        if arrival_phase == "activation" and kind is ActivationKind.RECONCILIATION:
            inject_conflict()

    core, _, _ = _core(probe=probe)
    holder["core"] = core
    core.ingest(_envelope())
    active = core.active_dataset()
    candidate = _candidate_args(core, active.records, generated_at="2026-09-02T00:02:00Z")

    if arrival_phase == "build":
        original = sync._copy_reconciled_generation

        def build_with_conflict(*args: Any, **kwargs: Any) -> Any:
            candidate = original(*args, **kwargs)
            inject_conflict()
            return candidate

        monkeypatch.setattr(sync, "_copy_reconciled_generation", build_with_conflict)

    with pytest.raises(SyncOperationError, match="Deliveries changed"):
        core.install_reconciliation(
            shop_domain=SHOP,
            **candidate,
            expected_active_generation=active.dataset_generation,
        )
    assert core.active_dataset() == active
    pending = core.pending_reconciliation()
    assert len(pending) == 1
    assert pending[0].key == WebhookKey(SHOP, "event-1")
    assert pending[0].state is InboxState.RECONCILE_REQUIRED
    metrics = core.metrics()
    assert metrics.unresolved_reconciliation_events == 1
    assert metrics.projection_paused
    assert metrics.stale


def test_reconciliation_coverage_uses_fence_sequence_not_event_timestamp() -> None:
    core, _, _ = _core()
    core.ingest(
        _envelope(
            "future-unknown",
            topic="products/unknown",
            received_at="2026-09-02T00:03:00Z",
        )
    )
    current = core.active_dataset().dataset_generation
    installed = core.install_reconciliation(
        shop_domain=SHOP,
        **_candidate_args(core, _records(), generated_at="2026-09-02T00:02:00Z"),
        expected_active_generation=current,
    )
    status = core.event_status(WebhookKey(SHOP, "future-unknown"))
    assert status.state is InboxState.RECONCILE_REQUIRED
    assert status.reconciliation_generation == installed
    assert core.pending_reconciliation() == ()
    assert not core.metrics().projection_paused


def test_reconciliation_clears_covered_validated_event_watermark() -> None:
    adapters = Adapters()
    adapters.source_updated_at = BASE_TIME
    core, _, _ = _core(adapters)
    result = core.ingest(_envelope("covered-stale"))
    assert result.status.state is InboxState.RECONCILE_REQUIRED
    current = core.active_dataset().dataset_generation
    installed = core.install_reconciliation(
        shop_domain=SHOP,
        **_candidate_args(core, _records(), generated_at="2026-09-02T00:02:00Z"),
        expected_active_generation=current,
    )
    status = core.event_status(result.key)
    assert status.state is InboxState.RECONCILE_REQUIRED
    assert status.reconciliation_generation == installed
    assert core.pending_reconciliation() == ()
    assert not core.metrics().projection_paused


def test_capacity_missing_keys_and_key_type_fail_closed() -> None:
    core, _, _ = _core(max_inbox_events=1)
    core.receive(_envelope())
    with pytest.raises(SyncOperationError, match="at capacity"):
        core.receive(_envelope("event-2"))
    missing = WebhookKey(SHOP, "missing")
    with pytest.raises(SyncOperationError, match="does not exist"):
        core.process(missing)
    with pytest.raises(SyncOperationError, match="does not exist"):
        core.event_status(missing)
    with pytest.raises(SyncContractError, match="key is invalid"):
        core.process("not-a-key")  # type: ignore[arg-type]
    with pytest.raises(SyncContractError, match="key is invalid"):
        core.event_status("not-a-key")  # type: ignore[arg-type]


def test_inbox_retained_budget_counts_entire_unique_envelope_not_retries() -> None:
    envelope = _envelope(payload=b"12345678")
    retained_bytes = sync._retained_envelope_bytes(envelope)
    core, _, _ = _core(max_inbox_retained_bytes=retained_bytes)
    first = core.receive(envelope)
    retry = core.receive(envelope)
    assert not first.duplicate
    assert retry.duplicate
    with pytest.raises(SyncOperationError, match="at capacity"):
        core.receive(_envelope("event-2", payload=b"x"))
    metrics = core.metrics()
    assert metrics.inbox_events == 1
    assert metrics.inbox_retained_bytes == retained_bytes


def test_inbox_budget_includes_metadata_not_only_payload() -> None:
    envelope = _envelope(payload=b"{}")
    core, _, _ = _core(max_inbox_retained_bytes=len(envelope.payload))
    with pytest.raises(SyncOperationError, match="at capacity"):
        core.receive(envelope)
    metrics = core.metrics()
    assert metrics.deliveries_total == 0
    assert metrics.inbox_retained_bytes == 0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"shop_domain": "INVALID"},
        {"webhook_id": "bad id"},
        {"topic": "bad-topic"},
        {"topic": "a" * 100_000 + "/b"},
        {"api_version": "unstable"},
        {"received_at": "not-time"},
        {"received_at": "2026-02-30T00:00:00Z"},
        {"received_at": "2026-09-02T00:00:00-00:00"},
        {"received_at": "2026-09-02T00:00:00." + "1" * 100_000 + "Z"},
        {"payload": b""},
        {"payload": b"x" * (sync.MAX_WEBHOOK_PAYLOAD_BYTES + 1)},
        {"payload_sha256": "f" * 64},
    ],
)
def test_raw_envelope_rejects_invalid_metadata_and_payload(kwargs: dict[str, Any]) -> None:
    values: dict[str, Any] = {
        "shop_domain": SHOP,
        "webhook_id": "event-1",
        "topic": "products/update",
        "api_version": "2026-07",
        "received_at": EVENT_TIME,
        "payload": b"{}",
    }
    values.update(kwargs)
    with pytest.raises(SyncContractError):
        RawWebhookEnvelope(**values)


def test_raw_envelope_hash_key_and_safe_repr() -> None:
    envelope = _envelope()
    assert envelope.payload_sha256 == sync.hashlib.sha256(envelope.payload).hexdigest()
    assert envelope.key == WebhookKey(SHOP, "event-1")
    assert "synthetic" not in repr(envelope)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"shop_domain": "INVALID"},
        {"webhook_id": "bad id"},
        {"payload_sha256": "x" * 64},
        {"category": "product_update"},
        {"product_gid": "gid://shopify/Variant/1"},
        {"product_gid": "gid://shopify/Product/" + "1" * 100_000},
        {"source_updated_at": "bad"},
        {"source_updated_at": "2026-09-02T00:00:00." + "1" * 100_000 + "Z"},
    ],
)
def test_validated_event_rejects_invalid_contract_fields(kwargs: dict[str, Any]) -> None:
    envelope = _envelope()
    values: dict[str, Any] = {
        "shop_domain": SHOP,
        "webhook_id": envelope.webhook_id,
        "payload_sha256": envelope.payload_sha256,
        "category": EventCategory.PRODUCT_UPDATE,
        "product_gid": "gid://shopify/Product/1",
        "source_updated_at": EVENT_TIME,
    }
    values.update(kwargs)
    with pytest.raises(SyncContractError):
        ValidatedWebhookEvent(**values)


def test_bounded_large_product_gid_remains_exact_decimal_text() -> None:
    envelope = _envelope()
    digits = "9" * 300
    event = ValidatedWebhookEvent(
        shop_domain=SHOP,
        webhook_id=envelope.webhook_id,
        payload_sha256=envelope.payload_sha256,
        category=EventCategory.PRODUCT_UPDATE,
        product_gid=f"gid://shopify/Product/{digits}",
        source_updated_at=EVENT_TIME,
    )
    assert event.product_gid.rsplit("/", 1)[1] == digits
    assert type(event.product_gid) is str


@pytest.mark.parametrize(
    "field,value",
    [
        ("shop_domain", "INVALID"),
        ("webhook_id", "bad id"),
    ],
)
def test_webhook_key_rejects_invalid_fields(field: str, value: str) -> None:
    kwargs = {"shop_domain": SHOP, "webhook_id": "event"}
    kwargs[field] = value
    with pytest.raises(SyncContractError):
        WebhookKey(**kwargs)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"dataset_generation": "bad"},
        {"base_dataset_generation": "bad"},
        {"taxonomy_rule_version": ""},
        {"taxonomy_rule_version": "v" + "1" * 100_000},
        {"records": ()},
    ],
)
def test_projection_context_rejects_invalid_fields(kwargs: dict[str, Any]) -> None:
    manifest = _manifest(_records())
    values: dict[str, Any] = {
        "dataset_generation": manifest.dataset_generation,
        "base_dataset_generation": manifest.dataset_generation,
        "taxonomy_rule_version": manifest.taxonomy_rule_version,
        "records": _records(),
    }
    values.update(kwargs)
    with pytest.raises(SyncContractError):
        ProjectionContext(**values)


@pytest.mark.parametrize(
    "override",
    [
        {"validator": None},
        {"projector": None},
        {"clock": None},
        {"activation_probe": object()},
        {"expected_shop_domain": "a.b.myshopify.com"},
        {"initial_reconciled_generation": object()},
        {"stale_after_seconds": -1},
        {"stale_after_seconds": True},
        {"max_inbox_events": 0},
        {"max_inbox_retained_bytes": 0},
        {"max_processing_attempts": 0},
    ],
)
def test_core_constructor_rejects_invalid_configuration(override: dict[str, Any]) -> None:
    adapters = Adapters()
    records = _records()
    values: dict[str, Any] = {
        "expected_shop_domain": SHOP,
        "initial_reconciled_generation": _reconciled_generation(
            records,
            generated_at=BASE_TIME,
        ),
        "validator": adapters.validate,
        "projector": adapters.project,
        "clock": MutableClock(),
    }
    values.update(override)
    with pytest.raises(SyncContractError):
        SyncCore(**values)


def test_core_bootstraps_from_exact_reconciled_v2_without_path_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapters = Adapters()
    records = _records()
    reconciled = _reconciled_generation(records, generated_at=BASE_TIME)

    def forbid_path_open(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("fresh sync bootstrap must not read a Path")

    monkeypatch.setattr(Path, "open", forbid_path_open)
    core = SyncCore(
        expected_shop_domain=SHOP,
        initial_reconciled_generation=reconciled,
        validator=adapters.validate,
        projector=adapters.project,
        clock=MutableClock(),
    )
    active = core.active_dataset()
    assert active.dataset_generation == reconciled.dataset_manifest.dataset_generation
    assert active.source_cut_at == reconciled.source_manifest.capture_completed_at
    assert active.records == records
    assert active.records[0] is not reconciled.records[0]
    object.__setattr__(reconciled.records[0], "commercial_title", "hostile-late-mutation")
    assert core.active_dataset() == active
    assert core.previous_dataset() is None


def test_core_constructor_rejects_legacy_bootstrap_keywords() -> None:
    adapters = Adapters()
    with pytest.raises(TypeError, match="initial_source_cut_at"):
        SyncCore(
            expected_shop_domain=SHOP,
            initial_reconciled_generation=_reconciled_generation(
                _records(),
                generated_at=BASE_TIME,
            ),
            initial_source_cut_at=BASE_TIME,  # type: ignore[call-arg]
            validator=adapters.validate,
            projector=adapters.project,
            clock=MutableClock(),
        )


def test_core_constructor_rejects_reconciled_v2_forgery_and_mismatch() -> None:
    adapters = Adapters()
    reconciled = _reconciled_generation(_records(), generated_at=BASE_TIME)
    values: dict[str, Any] = {
        "expected_shop_domain": SHOP,
        "initial_reconciled_generation": reconciled,
        "validator": adapters.validate,
        "projector": adapters.project,
        "clock": MutableClock(),
    }
    invalid_candidates = (
        object(),
        replace(reconciled, source_manifest=object()),
        replace(reconciled, source_manifest_bytes=bytearray(reconciled.source_manifest_bytes)),
        replace(
            reconciled,
            source_manifest=replace(
                reconciled.source_manifest,
                source_identity_product_count=(
                    reconciled.source_manifest.source_identity_product_count + 1
                ),
            ),
        ),
        replace(
            reconciled,
            dataset_manifest=replace(reconciled.dataset_manifest, generated_at=EVENT_TIME),
        ),
        _reconciled_generation(
            _records(),
            generated_at=BASE_TIME,
            shop_domain="other.myshopify.com",
        ),
    )
    for invalid in invalid_candidates:
        with pytest.raises(SyncContractError) as caught:
            SyncCore(**(values | {"initial_reconciled_generation": invalid}))
        assert str(caught.value) == "initial reconciled generation is invalid"


@pytest.mark.parametrize("field_name", ["snapshot_set_id", "capture_completed_at"])
def test_core_normalizes_hostile_reconciled_source_comparisons(field_name: str) -> None:
    class EvilSourceField:
        def __eq__(self, _other: object) -> bool:
            raise RuntimeError("SECRET_NESTED_COMPARE")

        def __ne__(self, _other: object) -> bool:
            raise RuntimeError("SECRET_NESTED_COMPARE")

        def __str__(self) -> str:
            raise RuntimeError("SECRET_NESTED_STRING")

    adapters = Adapters()
    reconciled = _reconciled_generation(_records(), generated_at=BASE_TIME)
    hostile_source = object.__new__(reconciliation.ReconciledSourceManifestV2)
    for field in fields(reconciled.source_manifest):
        value = (
            EvilSourceField()
            if field.name == field_name
            else getattr(reconciled.source_manifest, field.name)
        )
        object.__setattr__(hostile_source, field.name, value)
    with pytest.raises(SyncContractError) as caught:
        SyncCore(
            expected_shop_domain=SHOP,
            initial_reconciled_generation=replace(
                reconciled,
                source_manifest=hostile_source,
            ),
            validator=adapters.validate,
            projector=adapters.project,
            clock=MutableClock(),
        )
    assert str(caught.value) == "initial reconciled generation is invalid"


def test_metrics_report_stale_fractional_and_offset_clock_deterministically() -> None:
    clock = MutableClock("2026-09-02T02:00:01.0000001+02:00")
    core, _, _ = _core(clock=clock, stale_after_seconds=0)
    metrics = core.metrics()
    assert metrics.lag_seconds == 1
    assert metrics.stale
    assert metrics.inbox_events == 0
    assert metrics.inbox_retained_bytes == 0
    clock.value = "2026-09-01T23:59:59Z"
    assert core.metrics().lag_seconds == 0


def test_clock_contract_error_and_hostile_envelope_mutation_are_normalized() -> None:
    core, _, clock = _core()
    clock.value = "invalid"
    with pytest.raises(SyncOperationError, match="clock failed"):
        core.metrics()

    envelope = _envelope()
    object.__setattr__(envelope, "payload", object())
    with pytest.raises(SyncContractError):
        core.receive(envelope)
    with pytest.raises(SyncContractError, match="raw webhook envelope"):
        core.receive(object())  # type: ignore[arg-type]


def test_unknown_offset_record_is_rejected_initially_and_retryable_from_projector() -> None:
    invalid_target = _product("1", updated_at="2026-09-02T00:00:00-00:00")
    with pytest.raises(SyncContractError, match="initial reconciled generation is invalid"):
        _core(records=(invalid_target, _records()[1]))

    adapters = Adapters()

    def unknown_offset_candidate(
        context: ProjectionContext, _event: ValidatedWebhookEvent
    ) -> tuple[CatalogProductRecordV1, ...]:
        target = context.records[0]
        return (
            replace(
                target,
                updated_at="2026-09-02T00:01:00-00:00",
                variants=(
                    replace(
                        target.variants[0],
                        updated_at="2026-09-02T00:01:00-00:00",
                    ),
                ),
            ),
            context.records[1],
        )

    adapters.projector_override = unknown_offset_candidate
    core, _, _ = _core(adapters)
    envelope = _envelope("unknown-offset")
    failed = core.ingest(envelope)
    assert failed.status.state is InboxState.FAILED
    assert failed.status.failure_code is FailureCode.CANDIDATE_INVALID
    assert core.metrics().stale
    adapters.projector_override = None
    retried = core.ingest(envelope)
    assert retried.status.state is InboxState.PROJECTED
    assert not core.metrics().stale


def test_ordering_exception_is_normalized_to_reconciliation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core, _, _ = _core()

    def invalid_order(*_args: Any) -> bool:
        raise SyncContractError("fixed")

    monkeypatch.setattr(core, "_order_is_safe", invalid_order)
    result = core.ingest(_envelope("bad-order"))
    assert result.status.state is InboxState.RECONCILE_REQUIRED
    assert core.metrics().stale


def test_transition_helper_rejects_backward_and_noncanonical_states() -> None:
    core, _, _ = _core()
    receipt = core.receive(_envelope())
    entry = core._entries[receipt.key]
    failed = core._transition_entry(entry, InboxState.FAILED)
    with pytest.raises(SyncContractError, match="not monotonic"):
        core._transition_entry(failed, InboxState.VALIDATED)
    with pytest.raises(SyncContractError, match="not monotonic"):
        core._transition_entry(entry, "validated")  # type: ignore[arg-type]


def test_commercial_values_placeholder_and_unclassified_accounting_are_preserved() -> None:
    records = (
        _product("1", price="0", inventory=0),
        _product("2", family=ProductFamily.ACCESSORY, price="19.9900", inventory=12),
        _product(
            "3",
            family=ProductFamily.UNCLASSIFIED,
            game=None,
            price="88.000",
            inventory=-9,
        ),
    )
    core, _, _ = _core(records=records)
    result = core.ingest(_envelope())
    assert result.status.state is InboxState.PROJECTED
    active = core.active_dataset()
    by_gid = {record.product_gid: record for record in active.records}
    assert by_gid["gid://shopify/Product/2"].variants[0].price_text == "19.9900"
    assert by_gid["gid://shopify/Product/2"].variants[0].inventory_quantity == 12
    assert by_gid["gid://shopify/Product/3"].variants[0].price_text == "88.000"
    assert by_gid["gid://shopify/Product/3"].variants[0].inventory_quantity == -9
    assert dict(active.product_family_counts)["unclassified"] == 1
    assert core.metrics().unclassified_product_count == 1


def test_candidate_accepts_canonical_products_without_source_identity() -> None:
    records = (
        replace(_product("1"), powertools_source_id=None, sync_source_id=None),
        _records()[1],
    )
    core, _, _ = _core(records=records)
    assert core.active_dataset().source_identity_product_count == 1


def test_target_reclassification_is_versioned_and_duplicate_delivery_is_idempotent() -> None:
    adapters = Adapters()
    core, _, clock = _core(adapters)

    def classify_sealed(
        context: ProjectionContext, event: ValidatedWebhookEvent
    ) -> tuple[CatalogProductRecordV1, ...]:
        target = _product(
            "1",
            family=ProductFamily.SEALED,
            price="45.6700",
            inventory=4,
            updated_at=event.source_updated_at,
        )
        return (target, context.records[1])

    adapters.projector_override = classify_sealed
    envelope = _envelope("reclassify-sealed")
    first = core.ingest(envelope)
    assert first.status.state is InboxState.PROJECTED
    assert core.active_dataset().records[0].product_family is ProductFamily.SEALED
    assert core.ingest(envelope).status.projected_generation == first.status.projected_generation

    adapters.source_updated_at = "2026-09-02T00:02:00Z"
    clock.value = "2026-09-02T00:02:01Z"

    def classify_unknown(
        context: ProjectionContext, event: ValidatedWebhookEvent
    ) -> tuple[CatalogProductRecordV1, ...]:
        target = _product(
            "1",
            family=ProductFamily.UNCLASSIFIED,
            game=None,
            price="45.6700",
            inventory=4,
            updated_at=event.source_updated_at,
        )
        return (target, context.records[1])

    adapters.projector_override = classify_unknown
    second = core.ingest(_envelope("reclassify-unknown", received_at="2026-09-02T00:02:00Z"))
    assert second.status.state is InboxState.PROJECTED
    assert core.active_dataset().records[0].unclassified_reason == "unknown_product_type"
    assert core.metrics().unclassified_product_count == 1


def test_private_serialization_and_timestamp_helpers_fail_closed() -> None:
    with pytest.raises(SyncContractError, match="canonically serializable"):
        sync._canonical_json_bytes({"unsupported": {1, 2}})
    with pytest.raises(SyncContractError, match="invalid"):
        sync._timestamp_key(object(), "timestamp")
    start = sync._timestamp_key("2026-09-02T00:00:00.9Z", "start")
    end = sync._timestamp_key("2026-09-02T00:00:01.1Z", "end")
    assert sync._elapsed_whole_seconds(start, end) == 0
    assert sync._timestamp_key("2026-09-02T02:00:00+02:00", "positive")[1] == start[1]
    assert sync._timestamp_key("2026-09-01T23:00:00-01:00", "negative")[1] == start[1]
    assert sync._timestamp_key(sync._system_clock(), "system clock")[0].endswith("Z")


def test_incremental_generation_rejects_cross_shop_event_even_if_called_directly() -> None:
    core, _, _ = _core()
    parent = core._pair.active.generation
    envelope = _envelope(shop_domain="other.myshopify.com")
    event = _validated(envelope)
    with pytest.raises(SyncContractError, match="shop does not match"):
        sync._advance_generation(parent, parent.records, envelope, event, EVENT_TIME)


def test_record_set_guards_reject_type_identity_taxonomy_and_variant_collisions() -> None:
    records = _records()
    with pytest.raises(SyncContractError, match="canonical product records"):
        sync._copy_records((object(),))

    hostile = records[0]
    object.__setattr__(hostile, "commercial_title", object())
    try:
        with pytest.raises(SyncContractError, match="product record is invalid"):
            sync._copy_records((hostile,))
    finally:
        object.__setattr__(hostile, "commercial_title", "Synthetic Product 1")

    with pytest.raises(SyncContractError, match="identities or handles"):
        sync._copy_records((records[0], records[0]))
    same_handle = replace(records[1], handle=records[0].handle)
    with pytest.raises(SyncContractError, match="identities or handles"):
        sync._copy_records((records[0], same_handle))
    other_taxonomy = replace(records[1], classification_rule_version="2026-09-02.2")
    with pytest.raises(SyncContractError, match="taxonomy rule version"):
        sync._copy_records((records[0], other_taxonomy))

    first_variant = records[0].variants[0]
    second_variant = records[1].variants[0]
    duplicate_variant = replace(second_variant, variant_gid=first_variant.variant_gid)
    with pytest.raises(SyncContractError, match="Variant identities"):
        sync._copy_records((records[0], replace(records[1], variants=(duplicate_variant,))))
    duplicate_inventory = replace(
        second_variant, inventory_item_gid=first_variant.inventory_item_gid
    )
    with pytest.raises(SyncContractError, match="Variant identities"):
        sync._copy_records((records[0], replace(records[1], variants=(duplicate_inventory,))))


def _tampered_generation(generation: Any, field_name: str, value: Any) -> Any:
    clone = object.__new__(sync._SyncGeneration)
    for field in fields(sync._SyncGeneration):
        object.__setattr__(
            clone,
            field.name,
            value if field.name == field_name else getattr(generation, field.name),
        )
    return clone


def test_generation_validation_detects_tampering(monkeypatch: pytest.MonkeyPatch) -> None:
    core, _, _ = _core()
    initial = core._pair.active.generation
    with pytest.raises(SyncContractError, match="sync generation"):
        sync._validate_generation(object())
    with pytest.raises(SyncContractError, match="source cut"):
        sync._validate_generation(
            _tampered_generation(initial, "source_cut_at", "2026-09-02T00:00:01Z")
        )
    with pytest.raises(SyncContractError, match="record timestamp"):
        sync._validate_generation(
            _tampered_generation(initial, "source_cut_at", "2026-09-01T23:59:59Z")
        )
    with pytest.raises(SyncContractError, match="base"):
        sync._validate_generation(
            _tampered_generation(initial, "base_dataset_generation", "sha256:" + "f" * 64)
        )
    with pytest.raises(SyncContractError, match="taxonomy"):
        sync._validate_generation(
            _tampered_generation(initial, "taxonomy_rule_version", "other-version")
        )
    with pytest.raises(SyncContractError, match="content hash"):
        sync._validate_generation(_tampered_generation(initial, "catalog_content_sha256", "f" * 64))
    with pytest.raises(SyncContractError, match="counts"):
        sync._validate_generation(_tampered_generation(initial, "product_count", 999))
    with pytest.raises(SyncContractError, match="initial sync generation"):
        sync._validate_generation(
            _tampered_generation(initial, "parent_dataset_generation", initial.dataset_generation)
        )

    def reject_records(
        _self: DatasetManifestV1, _records_value: tuple[CatalogProductRecordV1, ...]
    ) -> None:
        raise ValueError("secret")

    monkeypatch.setattr(DatasetManifestV1, "validate_records", reject_records)
    with pytest.raises(SyncContractError, match="records are invalid"):
        sync._validate_generation(initial)


def test_incremental_generation_validation_detects_parent_and_descriptor_tampering() -> None:
    core, _, _ = _core()
    core.ingest(_envelope())
    generation = core._pair.active.generation
    with pytest.raises(SyncContractError, match="requires a parent"):
        sync._validate_generation(
            _tampered_generation(generation, "parent_dataset_generation", None)
        )
    with pytest.raises(SyncContractError, match="does not match its descriptor"):
        sync._validate_generation(
            _tampered_generation(generation, "dataset_generation", "sha256:" + "f" * 64)
        )


def test_manifest_copy_guards_wrong_type_and_hostile_mutation() -> None:
    with pytest.raises(SyncContractError, match="canonical DatasetManifestV1"):
        sync._copy_manifest(object())
    manifest = _manifest(_records())
    original = manifest.capability_matrix
    object.__setattr__(manifest, "capability_matrix", object())
    try:
        with pytest.raises(SyncContractError, match="runtime manifest is invalid"):
            sync._copy_manifest(manifest)
    finally:
        object.__setattr__(manifest, "capability_matrix", original)


def test_projection_delta_guards_unpublish_timestamp_and_taxonomy_drift() -> None:
    adapters = Adapters()
    adapters.category = EventCategory.PRODUCT_UNPUBLISH
    adapters.projector_override = lambda context, event: (
        replace(context.records[0], updated_at=event.source_updated_at),
        context.records[1],
    )
    core, _, _ = _core(adapters)
    assert core.ingest(_envelope()).status.state is InboxState.RECONCILE_REQUIRED

    adapters = Adapters()
    adapters.projector_override = lambda context, _event: (
        replace(
            context.records[0],
            updated_at="2026-09-02T00:00:30Z",
            variants=(
                replace(
                    context.records[0].variants[0],
                    updated_at="2026-09-02T00:00:30Z",
                ),
            ),
        ),
        context.records[1],
    )
    core, _, _ = _core(adapters)
    assert core.ingest(_envelope()).status.state is InboxState.RECONCILE_REQUIRED

    adapters = Adapters()

    def new_taxonomy(
        context: ProjectionContext, event: ValidatedWebhookEvent
    ) -> tuple[CatalogProductRecordV1, ...]:
        return tuple(
            replace(
                record,
                classification_rule_version="2026-09-02.2",
                updated_at=event.source_updated_at,
                variants=tuple(
                    replace(variant, updated_at=event.source_updated_at)
                    for variant in record.variants
                ),
            )
            for record in context.records
        )

    adapters.projector_override = new_taxonomy
    core, _, _ = _core(adapters)
    assert core.ingest(_envelope()).status.state is InboxState.RECONCILE_REQUIRED


def test_generation_build_timestamp_cannot_regress() -> None:
    core, _, clock = _core()
    clock.value = "2026-09-01T23:59:59Z"
    result = core.ingest(_envelope())
    assert result.status.state is InboxState.FAILED
    assert result.status.failure_code is FailureCode.CANDIDATE_INVALID


def test_event_status_success_and_reconcile_is_idempotent() -> None:
    core, _, _ = _core()
    receipt = core.receive(_envelope(topic="products/unknown"))
    status = core.process(receipt.key)
    assert core.event_status(receipt.key) == status
    decisions = core.metrics().reconciliation_decisions_total
    assert core._mark_reconcile(receipt.key, None) == status
    assert core.metrics().reconciliation_decisions_total == decisions


def test_conflict_during_validation_wins_over_projection_and_failure() -> None:
    adapters = Adapters()
    records = _records()
    holder: dict[str, SyncCore] = {}

    def validator(envelope: RawWebhookEnvelope) -> ValidatedWebhookEvent:
        holder["core"].receive(_envelope(envelope.webhook_id, payload=b'{"conflicting":true}'))
        return _validated(envelope)

    core = SyncCore(
        expected_shop_domain=SHOP,
        initial_reconciled_generation=_reconciled_generation(
            records,
            generated_at=BASE_TIME,
        ),
        validator=validator,
        projector=adapters.project,
        clock=MutableClock(),
    )
    holder["core"] = core
    result = core.ingest(_envelope())
    assert result.status.state is InboxState.RECONCILE_REQUIRED
    assert adapters.projector_calls == 0

    def failing_validator(envelope: RawWebhookEnvelope) -> ValidatedWebhookEvent:
        holder["core"].receive(_envelope(envelope.webhook_id, payload=b'{"another-conflict":true}'))
        raise ValueError("secret")

    other = SyncCore(
        expected_shop_domain=SHOP,
        initial_reconciled_generation=_reconciled_generation(
            records,
            generated_at=BASE_TIME,
        ),
        validator=failing_validator,
        projector=adapters.project,
        clock=MutableClock(),
    )
    holder["core"] = other
    failed = other.ingest(_envelope())
    assert failed.status.state is InboxState.RECONCILE_REQUIRED
    assert failed.status.failure_code is None


@pytest.mark.parametrize("mode", ["conflict", "generation-race"])
def test_activation_commit_rechecks_event_and_generation_state(mode: str) -> None:
    adapters = Adapters()
    holder: dict[str, SyncCore] = {}

    def probe(kind: ActivationKind) -> None:
        if kind is not ActivationKind.EVENT:
            return
        core = holder["core"]
        if mode == "conflict":
            core.receive(_envelope(payload=b'{"late-conflict":true}'))
        else:
            pair = core._pair
            replacement_slot = sync._GenerationSlot(
                pair.active.generation, pair.active.applied_orders
            )
            core._pair = sync._GenerationPair(replacement_slot, pair.previous)

    core, _, _ = _core(adapters, probe=probe)
    holder["core"] = core
    original = core.active_dataset().dataset_generation
    result = core.ingest(_envelope())
    assert result.status.state is InboxState.RECONCILE_REQUIRED
    assert core.active_dataset().dataset_generation == original


@pytest.mark.parametrize("operation", ["rollback", "reconciliation"])
def test_admin_operations_recheck_generation_pair_after_probe(operation: str) -> None:
    holder: dict[str, SyncCore] = {}

    def probe(kind: ActivationKind) -> None:
        if kind.value != operation:
            return
        core = holder["core"]
        pair = core._pair
        core._pair = sync._GenerationPair(pair.active, pair.previous)

    core, _, _ = _core(probe=probe)
    holder["core"] = core
    projected = core.ingest(_envelope())
    current = core.active_dataset().dataset_generation
    if operation == "rollback":
        with pytest.raises(SyncOperationError, match="changed before rollback"):
            core.rollback(expected_active_generation=projected.status.projected_generation or "")
    else:
        with pytest.raises(SyncOperationError, match="changed before reconciliation"):
            core.install_reconciliation(
                shop_domain=SHOP,
                **_candidate_args(core, _records(), generated_at="2026-09-02T00:02:00Z"),
                expected_active_generation=current,
            )
    assert core.active_dataset().dataset_generation == current
