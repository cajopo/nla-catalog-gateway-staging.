from __future__ import annotations

import json
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts.package_staging_generation import run_packaging

import test_core_evidence as evidence_helpers
import test_generation_bundle as bundles
import test_sync as sync_helpers
from nla_catalog_gateway import core_evidence
from nla_catalog_gateway.card_metadata import CardMetadataV1
from nla_catalog_gateway.generation_bundle import VerifiedReconciledGenerationV1
from nla_catalog_gateway.pagination import CursorCodecV1
from nla_catalog_gateway.runtime_api import (
    EvidenceBoundCapabilityGate,
    EvidenceBoundCatalogBackend,
    RequestCancellation,
    RequestControl,
    RuntimeApiContractError,
)
from nla_catalog_gateway.runtime_contract import (
    CatalogFiltersV1,
    CatalogRequestV1,
    DatasetManifestV1,
    IncrementalLineageV1,
    RequestFamily,
    RuntimeContractError,
)
from nla_catalog_gateway.staging_generation import open_staging_generation
from nla_catalog_gateway.sync import EventCategory, InboxState, SyncContractError, SyncCore
from nla_catalog_gateway.sync_publication import (
    SyncPublicationError,
    publish_incremental_generation,
)
from nla_catalog_gateway.taxonomy import Game

CODE = "c" * 40


@pytest.fixture(autouse=True)
def synthetic_bundle_filesystem(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    # Ubuntu CI exercises the production reader, not the synthetic filesystem seam.
    if sys.platform != "linux":
        bundles._install_backend(monkeypatch)
    yield
    if sys.platform == "linux":
        for directory in tmp_path.rglob("bundle"):
            if directory.is_dir() and not directory.is_symlink():
                directory.chmod(0o755)
                for artifact in directory.iterdir():
                    if artifact.is_file() and not artifact.is_symlink():
                        artifact.chmod(0o644)


def _control():
    return RequestControl(30, RequestCancellation(), lambda: 0)


def _case(tmp_path: Path):
    records = tuple(
        replace(
            record,
            canonical_card_name="Lightning Bolt",
            card_metadata=CardMetadataV1("123", "SYN", "Synthetic", "common"),
        )
        if index < 2
        else record
        for index, record in enumerate(evidence_helpers._records())
    )
    bundle = bundles._write_bundle(tmp_path / "bundle", records)
    if sys.platform == "linux":
        for artifact in bundle.directory.iterdir():
            artifact.chmod(0o444)
        bundle.directory.chmod(0o555)
    base_path = tmp_path / "base-package"
    base_pin = run_packaging(bundle.directory, bundle.summary_sha256, CODE, base_path)
    base = open_staging_generation(base_path, base_pin)
    codec = CursorCodecV1(b"synthetic-cursor-key" * 2, 1800)
    backend = EvidenceBoundCatalogBackend.from_staging_generation(
        base,
        codec,
        expected_code_sha=CODE,
        clock=lambda: datetime(2026, 9, 5, 12, tzinfo=UTC),
    )
    adapters = sync_helpers.Adapters()
    adapters.inventory = 0
    clock = sync_helpers.MutableClock("2026-09-05T10:01:01Z")
    core = SyncCore(
        expected_shop_domain=bundles.SHOP,
        initial_reconciled_generation=bundle.generation,
        validator=adapters.validate,
        projector=adapters.project,
        clock=clock,
    )
    return SimpleNamespace(
        core=core,
        bundle=bundle,
        base=base,
        codec=codec,
        backend=backend,
        adapters=adapters,
        clock=clock,
        root=tmp_path,
    )


def _event(case, category=EventCategory.PRODUCT_UPDATE, product_id="1", minute=1):
    case.adapters.category = category
    case.adapters.product_id = product_id
    case.adapters.source_updated_at = f"2026-09-05T10:{minute:02d}:00Z"
    case.clock.value = f"2026-09-05T10:{minute:02d}:01Z"
    topic = {
        EventCategory.PRODUCT_CREATE: "products/create",
        EventCategory.PRODUCT_DELETE: "products/delete",
        EventCategory.INVENTORY_CHANGE: "inventory_levels/update",
    }.get(category, "products/update")
    result = case.core.ingest(
        sync_helpers._envelope(
            f"event-{minute}",
            topic=topic,
            received_at=case.clock.value,
        )
    )
    assert result.status.state is InboxState.PROJECTED


def _package(case, name="incremental"):
    destination = case.root / name
    pin = run_packaging(
        case.bundle.directory,
        case.bundle.summary_sha256,
        CODE,
        destination,
        incremental_core=case.core,
    )
    return open_staging_generation(destination, pin)


def _page(backend, request, cursor=None):
    control = _control()
    lease = backend.acquire(control=control, request=request, cursor=cursor)
    try:
        EvidenceBoundCapabilityGate(backend).require_catalog(lease, request, control=control)
        return lease.fetch_page(request, cursor, control=control)
    finally:
        lease.close()


def test_incremental_package_reopens_serves_soldout_and_retains_old_cursor(tmp_path: Path):
    case = _case(tmp_path)
    request = CatalogRequestV1(
        game=Game.MAGIC,
        product_family=RequestFamily.SINGLE,
        query="Bolt",
        filters=CatalogFiltersV1(None, None),
        page_size=1,
    )
    old = _page(case.backend, request)
    assert old.next_cursor is not None
    baseline_raw = case.bundle.generation.dataset_manifest.to_json_bytes()
    assert b"incrementalLineage" not in baseline_raw
    _event(case)
    view, manifest = case.core.publication_snapshot(case.bundle.generation.dataset_manifest)
    assert manifest.dataset_generation == view.dataset_generation
    assert manifest.dataset_generation != manifest.incremental_lineage.base_dataset_generation
    assert DatasetManifestV1.from_json_bytes(manifest.to_json_bytes()) == manifest
    assert manifest.source_snapshot_sha256 == case.base.projection.manifest.source_snapshot_sha256
    assert case.bundle.generation.dataset_manifest.to_json_bytes() == baseline_raw
    verified = _package(case)
    assert verified.projection.manifest == manifest
    assert verified.evidence.summary_sha256 != case.bundle.summary_sha256
    published = publish_incremental_generation(
        case.core,
        verified,
        backend=case.backend,
        cursor_codec=case.codec,
    )
    assert published == manifest.dataset_generation == case.backend.active_generation
    assert verified.records[0].total_inventory == 0
    assert verified.records[0].variants[0].price_text == "9.9900"
    assert verified.records[0].card_metadata == case.bundle.records[0].card_metadata
    current = _page(case.backend, request)
    assert current.page.dataset_generation == published
    assert current.page.items[0].product_gid == "gid://shopify/Product/1"
    assert current.page.items[0].variants[0].inventory_quantity == 0
    assert current.page.items[0].variants[0].price_text == "9.9900"
    previous = _page(case.backend, request, old.next_cursor)
    assert previous.page.dataset_generation == old.page.dataset_generation
    assert previous.page.items[0].product_gid == "gid://shopify/Product/2"
    # Search only in verified printed code still works after the update.
    code_page = _page(case.backend, replace(request, query="123", page_size=100))
    assert {x.product_gid for x in code_page.page.items} == {
        "gid://shopify/Product/1",
        "gid://shopify/Product/2",
    }


@pytest.mark.parametrize(
    "category",
    [
        EventCategory.PRODUCT_CREATE,
        EventCategory.PRODUCT_DELETE,
        EventCategory.PRODUCT_UNPUBLISH,
        EventCategory.INVENTORY_CHANGE,
    ],
)
def test_event_effects_reach_reopened_projection_and_serving(tmp_path: Path, category):
    case = _case(tmp_path)
    if category is EventCategory.PRODUCT_CREATE:

        def new_card(context, event):
            record = sync_helpers._product("999", updated_at=event.source_updated_at)
            return (
                *context.records,
                replace(
                    record,
                    canonical_card_name="Lightning Bolt",
                    card_metadata=CardMetadataV1("NEW-999", None, None, None),
                ),
            )

        case.adapters.projector_override = new_card
    _event(case, category, "999" if category is EventCategory.PRODUCT_CREATE else "1")
    verified = _package(case)
    publish_incremental_generation(
        case.core, verified, backend=case.backend, cursor_codec=case.codec
    )
    request = CatalogRequestV1(
        game=Game.MAGIC,
        product_family=RequestFamily.ALL,
        query=None,
        filters=CatalogFiltersV1(None, None),
        page_size=100,
    )
    actual = {item.product_gid for item in _page(case.backend, request).page.items}
    expected = {
        record.product_gid
        for record in case.core.active_dataset().records
        if record.publishable and record.game is Game.MAGIC
    }
    assert actual == expected
    verified.projection.manifest.validate_records(verified.records)
    if category is EventCategory.PRODUCT_CREATE:
        printed = _page(
            case.backend,
            replace(
                request,
                product_family=RequestFamily.SINGLE,
                query="NEW-999",
            ),
        )
        assert tuple(item.product_gid for item in printed.page.items) == (
            "gid://shopify/Product/999",
        )


def test_missing_wrong_or_unadvanced_base_cannot_make_manifest(tmp_path: Path):
    case = _case(tmp_path)
    base = case.bundle.generation.dataset_manifest
    with pytest.raises(SyncContractError):
        case.core.publication_snapshot(base)
    _event(case)
    with pytest.raises(SyncContractError):
        case.core.publication_snapshot(replace(base, generated_at="2026-09-05T10:00:01Z"))
    with pytest.raises(SyncContractError):
        case.core.publication_snapshot(None)


@pytest.mark.parametrize(
    "change",
    [
        {"shopDomain": "invalid"},
        {"shopDomain": 1},
        {"eventCount": 0},
        {"eventCount": True},
        {"baseDatasetGeneration": "bad"},
        {"parentDatasetGeneration": "bad"},
        {"sourceCutAt": "bad"},
        {"eventLineageSha256": "bad"},
        {"syncContractVersion": 2},
        {"syncContractVersion": True},
        {"unknown": "x"},
    ],
)
def test_lineage_validation(change):
    value = IncrementalLineageV1(
        "sha256:" + "a" * 64,
        "sha256:" + "b" * 64,
        bundles.SHOP,
        bundles.NOW,
        1,
        "c" * 64,
    ).as_dict()
    value.update(change)
    with pytest.raises(RuntimeContractError):
        IncrementalLineageV1.from_dict(value)


def test_manifest_rejects_missing_lineage_tampering_and_future_cut(tmp_path: Path):
    case = _case(tmp_path)
    _event(case)
    _, manifest = case.core.publication_snapshot(case.bundle.generation.dataset_manifest)
    value = manifest.as_dict()
    del value["incrementalLineage"]
    with pytest.raises(RuntimeContractError):
        DatasetManifestV1.from_dict(value)
    for lineage in (None, {}, []):
        value["incrementalLineage"] = lineage
        with pytest.raises(RuntimeContractError):
            DatasetManifestV1.from_dict(value)
    with pytest.raises(RuntimeContractError):
        replace(manifest, incremental_lineage=object())
    with pytest.raises(RuntimeContractError):
        replace(manifest, generated_at=bundles.NOW)
    value = json.loads(manifest.to_json_bytes())
    value["incrementalLineage"]["eventCount"] += 1
    with pytest.raises(RuntimeContractError):
        DatasetManifestV1.from_dict(value)


def test_stale_package_and_baseline_package_cannot_publish(tmp_path: Path):
    case = _case(tmp_path)
    _event(case)
    old_package = _package(case)
    _event(case, minute=2)
    original = case.backend.active_generation
    for package in (case.base, old_package, object()):
        with pytest.raises(SyncPublicationError) as error:
            publish_incremental_generation(
                case.core, package, backend=case.backend, cursor_codec=case.codec
            )
        assert error.value.__context__ is None
        assert case.backend.active_generation == original


def test_concurrent_backend_activation_cannot_be_overwritten(tmp_path: Path, monkeypatch):
    case = _case(tmp_path)
    _event(case)
    verified = _package(case)
    original = case.core.publish_active_dataset

    def raced(**kwargs):
        case.backend.activate_staging_generation(case.base, case.codec)
        original(**kwargs)

    monkeypatch.setattr(case.core, "publish_active_dataset", raced)
    with pytest.raises(SyncPublicationError):
        publish_incremental_generation(
            case.core, verified, backend=case.backend, cursor_codec=case.codec
        )
    assert case.backend.active_generation == case.base.projection.dataset_generation


def test_package_proof_rejects_changed_core_or_wrong_type(tmp_path: Path, monkeypatch):
    case = _case(tmp_path)
    _event(case)
    verified = VerifiedReconciledGenerationV1(case.bundle.generation, case.bundle.summary_sha256)
    with pytest.raises(core_evidence.CatalogCoreEvidenceError):
        core_evidence._verify_with_measurements(
            verified,
            projection_path=tmp_path / "bad.sqlite3",
            code_sha=CODE,
            incremental_core=object(),
        )
    original = core_evidence._verify_search

    def advance(*args):
        result = original(*args)
        _event(case, minute=2)
        return result

    monkeypatch.setattr(core_evidence, "_verify_search", advance)
    with pytest.raises(core_evidence.CatalogCoreEvidenceError):
        _package(case)
    assert not (tmp_path / "incremental").exists()


def test_conditional_staging_activation_rejects_other_shop(tmp_path: Path):
    case = _case(tmp_path)
    _event(case)
    verified = _package(case)
    # A different shop in the independently checked evidence binding fails closed.
    object.__setattr__(verified.evidence, "shop_domain", "different.myshopify.com")
    with pytest.raises(RuntimeApiContractError):
        case.backend.activate_staging_generation_if_current(
            case.backend.capture_activation_token(),
            verified,
            case.codec,
        )


def test_core_proof_rejects_cross_shop_snapshot(tmp_path: Path, monkeypatch):
    case = _case(tmp_path)
    _event(case)
    view, manifest = case.core.publication_snapshot(case.bundle.generation.dataset_manifest)
    monkeypatch.setattr(
        case.core,
        "publication_snapshot",
        lambda _: (
            replace(view, shop_domain="different.myshopify.com"),
            manifest,
        ),
    )
    with pytest.raises(core_evidence.CatalogCoreEvidenceError):
        _package(case)
    assert not (tmp_path / "incremental").exists()


def test_publisher_rechecks_lineage_inside_stable_view(tmp_path: Path, monkeypatch):
    case = _case(tmp_path)
    _event(case)
    verified = _package(case)
    original = case.core.publish_active_dataset

    def changed(**options):
        publisher = options["publisher"]
        options["publisher"] = lambda view: publisher(replace(view, applied_event_count=99))
        original(**options)

    monkeypatch.setattr(case.core, "publish_active_dataset", changed)
    with pytest.raises(SyncPublicationError):
        publish_incremental_generation(
            case.core, verified, backend=case.backend, cursor_codec=case.codec
        )
    assert case.backend.active_generation == case.base.projection.dataset_generation
