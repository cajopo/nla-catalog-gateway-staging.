"""Publish only fully reconciled sync views through existing verified contracts.

Incremental sync identities are intentionally not ``DatasetManifestV1`` identities,
so this handoff rejects them instead of fabricating a projection manifest.
"""

from __future__ import annotations

import os
from pathlib import Path

from nla_catalog_gateway.core_evidence import verify_catalog_core_evidence
from nla_catalog_gateway.generation_bundle import VerifiedReconciledGenerationV1
from nla_catalog_gateway.pagination import CursorCodecV1, build_catalog_projection
from nla_catalog_gateway.runtime_api import EvidenceBoundCatalogBackend
from nla_catalog_gateway.runtime_contract import CatalogProductRecordV1
from nla_catalog_gateway.sync import GenerationView, SyncCore, _initial_event_lineage

_CONCRETE_PATH_TYPE = type(Path())
_ERROR = "sync generation publication failed"
_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class SyncPublicationError(RuntimeError):
    """A fixed, value-free publication rejection."""


def _matches_reconciliation(
    view: GenerationView,
    verified: VerifiedReconciledGenerationV1,
) -> bool:
    reconciled = verified.generation
    manifest = reconciled.dataset_manifest
    return (
        type(view),
        view.shop_domain,
        view.source_cut_at,
        view.dataset_generation,
        view.base_dataset_generation,
        view.parent_dataset_generation,
        view.catalog_content_sha256,
        view.taxonomy_rule_version,
        view.built_at,
        view.event_lineage_sha256,
        view.last_event_identity_sha256,
        view.applied_event_count,
        view.product_status_counts,
        view.product_family_counts,
        view.product_count,
        view.variant_count,
        view.source_identity_product_count,
        view.public_item_count,
        type(view.records),
        tuple((type(record), record.to_json_bytes()) for record in view.records),
    ) == (
        GenerationView,
        reconciled.source_manifest.parts[0].shop_domain,
        reconciled.source_manifest.capture_completed_at,
        manifest.dataset_generation,
        manifest.dataset_generation,
        None,
        manifest.catalog_content_sha256,
        manifest.taxonomy_rule_version,
        manifest.generated_at,
        _initial_event_lineage(manifest.dataset_generation),
        None,
        0,
        manifest.included_product_status_counts,
        manifest.product_family_counts,
        manifest.included_product_count,
        manifest.included_variant_count,
        manifest.included_source_identity_product_count,
        manifest.public_item_count,
        tuple,
        tuple((CatalogProductRecordV1, record.to_json_bytes()) for record in reconciled.records),
    )


def _output_path(value: Path) -> Path:
    if type(value) is not _CONCRETE_PATH_TYPE or not value.is_absolute():
        raise ValueError
    resolved = value.resolve()
    if (
        value != resolved
        or resolved == _REPOSITORY_ROOT
        or resolved.is_relative_to(_REPOSITORY_ROOT)
        or os.path.lexists(resolved)
    ):
        raise ValueError
    return resolved


def publish_reconciled_generation(
    core: SyncCore,
    verified: VerifiedReconciledGenerationV1,
    *,
    backend: EvidenceBoundCatalogBackend,
    cursor_codec: CursorCodecV1,
    proof_projection_path: Path,
    projection_path: Path,
    code_sha: str,
) -> str:
    """Verify, build, and atomically activate the current reconciled sync view."""

    try:
        if (type(core), type(verified), type(backend), type(cursor_codec)) != (
            SyncCore,
            VerifiedReconciledGenerationV1,
            EvidenceBoundCatalogBackend,
            CursorCodecV1,
        ):
            raise ValueError
        activation_token = backend.capture_activation_token()
        proof_path = _output_path(proof_projection_path)
        candidate_path = _output_path(projection_path)
        if proof_path == candidate_path:
            raise ValueError
        view = core.active_dataset()
        if not _matches_reconciliation(view, verified):
            raise ValueError
        evidence = verify_catalog_core_evidence(
            verified,
            projection_path=proof_path,
            code_sha=code_sha,
        )
        if _output_path(projection_path) != candidate_path:
            raise ValueError
        projection = build_catalog_projection(
            candidate_path,
            manifest=verified.generation.dataset_manifest,
            records=verified.generation.records,
        )

        def activate(current: GenerationView) -> None:
            if current != view or not _matches_reconciliation(current, verified):
                raise ValueError
            backend.activate_if_current(
                activation_token,
                verified,
                projection,
                cursor_codec,
                evidence,
            )

        core.publish_active_dataset(
            expected_active_generation=view.dataset_generation,
            publisher=activate,
        )
    except Exception:
        rejected = True
    else:
        rejected = False
    if rejected:
        raise SyncPublicationError(_ERROR)
    return view.dataset_generation


__all__ = ["SyncPublicationError", "publish_reconciled_generation"]
