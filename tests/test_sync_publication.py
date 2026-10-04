from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import test_core_evidence as evidence_helpers
import test_generation_bundle as bundle_helpers
import test_sync as sync_helpers
from nla_catalog_gateway import runtime_api, sync_publication
from nla_catalog_gateway.core_evidence import verify_catalog_core_evidence
from nla_catalog_gateway.generation_bundle import VerifiedReconciledGenerationV1
from nla_catalog_gateway.pagination import CursorCodecV1, build_catalog_projection
from nla_catalog_gateway.runtime_api import (
    EvidenceBoundCatalogBackend,
    RequestCancellation,
    RequestControl,
)
from nla_catalog_gateway.runtime_contract import CatalogProductRecordV1
from nla_catalog_gateway.sync import SyncContractError, SyncCore, SyncOperationError
from nla_catalog_gateway.sync_publication import (
    SyncPublicationError,
    publish_reconciled_generation,
)

CODE_SHA = "c" * 40
CURSOR_KEY = b"k" * 32


def _verified(
    records: tuple[CatalogProductRecordV1, ...],
    summary_sha256: str,
) -> VerifiedReconciledGenerationV1:
    _, _, generation = bundle_helpers._generation(records)
    return VerifiedReconciledGenerationV1(generation, summary_sha256)


def _core(verified: VerifiedReconciledGenerationV1) -> SyncCore:
    def forbidden(*_args: object) -> Any:
        raise AssertionError

    return SyncCore(
        expected_shop_domain=bundle_helpers.SHOP,
        initial_reconciled_generation=verified.generation,
        validator=forbidden,
        projector=forbidden,
    )


def _runtime_case(tmp_path: Path) -> SimpleNamespace:
    records = evidence_helpers._records()
    verified = _verified(records, "a" * 64)
    evidence = verify_catalog_core_evidence(
        verified,
        projection_path=(tmp_path / "active-proof.sqlite3").resolve(),
        code_sha=CODE_SHA,
    )
    projection = build_catalog_projection(
        (tmp_path / "active.sqlite3").resolve(),
        manifest=verified.generation.dataset_manifest,
        records=records,
    )
    codec = CursorCodecV1(CURSOR_KEY, ttl_seconds=1_800)
    backend = EvidenceBoundCatalogBackend(
        verified,
        projection,
        codec,
        evidence,
        expected_code_sha=CODE_SHA,
        clock=lambda: datetime(2026, 9, 7, tzinfo=UTC),
    )
    return SimpleNamespace(
        records=records,
        verified=verified,
        evidence=evidence,
        projection=projection,
        codec=codec,
        backend=backend,
    )


def _control() -> RequestControl:
    return RequestControl(10, RequestCancellation(), lambda: 0)


def _candidate(case: SimpleNamespace) -> tuple[VerifiedReconciledGenerationV1, SyncCore]:
    records = (
        replace(case.records[0], commercial_title="Changed synthetic title"),
        *case.records[1:],
    )
    verified = _verified(records, "b" * 64)
    return verified, _core(verified)


def _assert_fixed_rejection(call: Any) -> None:
    with pytest.raises(SyncPublicationError) as captured:
        call()
    assert str(captured.value) == "sync generation publication failed"
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


def test_reconciled_view_is_verified_then_atomically_published(tmp_path: Path) -> None:
    case = _runtime_case(tmp_path)
    verified, core = _candidate(case)
    old_lease = case.backend.acquire(control=_control())
    proof_path = (tmp_path / "candidate-proof.sqlite3").resolve()
    projection_path = (tmp_path / "candidate.sqlite3").resolve()

    published = publish_reconciled_generation(
        core,
        verified,
        backend=case.backend,
        cursor_codec=case.codec,
        proof_projection_path=proof_path,
        projection_path=projection_path,
        code_sha=CODE_SHA,
    )

    new_lease = case.backend.acquire(control=_control())
    assert published == verified.generation.dataset_manifest.dataset_generation
    assert case.backend.active_generation == published
    assert (
        old_lease.dataset_generation == case.verified.generation.dataset_manifest.dataset_generation
    )
    assert new_lease.dataset_generation == published
    assert not proof_path.exists()
    assert projection_path.is_file()
    old_lease.close()
    new_lease.close()


def test_hook_stabilizes_one_committed_view_and_normalizes_callback_errors() -> None:
    verified = _verified(evidence_helpers._records(), "b" * 64)
    core = _core(verified)
    active = core.active_dataset()
    observed: list[object] = []

    core.publish_active_dataset(
        expected_active_generation=active.dataset_generation,
        publisher=observed.append,
    )
    assert observed == [active]
    with pytest.raises(SyncContractError):
        core.publish_active_dataset(
            expected_active_generation=active.dataset_generation,
            publisher=object(),  # type: ignore[arg-type]
        )
    with pytest.raises(SyncOperationError, match="active generation changed"):
        core.publish_active_dataset(
            expected_active_generation="sha256:" + "f" * 64,
            publisher=observed.append,
        )

    def rejected(_view: object) -> None:
        raise ValueError("sensitive callback value")

    with pytest.raises(SyncOperationError) as captured:
        core.publish_active_dataset(
            expected_active_generation=active.dataset_generation,
            publisher=rejected,
        )
    assert str(captured.value) == "Dataset publication failed."
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None

    class Abort(BaseException):
        pass

    def abort(_view: object) -> None:
        raise Abort

    with pytest.raises(Abort):
        core.publish_active_dataset(
            expected_active_generation=active.dataset_generation,
            publisher=abort,
        )


def test_incremental_or_forged_lineage_never_reaches_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _runtime_case(tmp_path)
    verified, core = _candidate(case)
    active_generation = case.backend.active_generation

    def forbidden(*_args: object, **_kwargs: object) -> Any:
        raise AssertionError("verification must not run")

    monkeypatch.setattr(sync_publication, "verify_catalog_core_evidence", forbidden)
    valid_path = (tmp_path / "valid.sqlite3").resolve()
    existing_path = (tmp_path / "existing.sqlite3").resolve()
    existing_path.touch()
    for invalid_path in (
        object(),
        Path("relative.sqlite3"),
        tmp_path / "missing" / ".." / "normalized.sqlite3",
        sync_publication._REPOSITORY_ROOT,
        sync_publication._REPOSITORY_ROOT / "candidate.sqlite3",
        existing_path,
    ):
        with pytest.raises(ValueError):
            sync_publication._output_path(invalid_path)  # type: ignore[arg-type]
    assert sync_publication._output_path(valid_path) == valid_path
    _assert_fixed_rejection(
        lambda: publish_reconciled_generation(  # type: ignore[arg-type]
            object(),
            verified,
            backend=case.backend,
            cursor_codec=case.codec,
            proof_projection_path=(tmp_path / "wrong-type-proof.sqlite3").resolve(),
            projection_path=(tmp_path / "wrong-type.sqlite3").resolve(),
            code_sha=CODE_SHA,
        )
    )
    same_path = (tmp_path / "same.sqlite3").resolve()
    _assert_fixed_rejection(
        lambda: publish_reconciled_generation(
            core,
            verified,
            backend=case.backend,
            cursor_codec=case.codec,
            proof_projection_path=same_path,
            projection_path=same_path,
            code_sha=CODE_SHA,
        )
    )
    incremental, _, _ = sync_helpers._core()
    incremental.ingest(sync_helpers._envelope())
    base = sync_helpers._reconciled_generation(
        sync_helpers._records(),
        generated_at=sync_helpers.BASE_TIME,
    )
    base_verified = VerifiedReconciledGenerationV1(base, "d" * 64)
    assert incremental.active_dataset().applied_event_count == 1
    _assert_fixed_rejection(
        lambda: publish_reconciled_generation(
            incremental,
            base_verified,
            backend=case.backend,
            cursor_codec=case.codec,
            proof_projection_path=(tmp_path / "incremental-proof.sqlite3").resolve(),
            projection_path=(tmp_path / "incremental.sqlite3").resolve(),
            code_sha=CODE_SHA,
        )
    )

    object.__setattr__(core._pair.active.generation, "event_lineage_sha256", "f" * 64)
    _assert_fixed_rejection(
        lambda: publish_reconciled_generation(
            core,
            verified,
            backend=case.backend,
            cursor_codec=case.codec,
            proof_projection_path=(tmp_path / "forged-proof.sqlite3").resolve(),
            projection_path=(tmp_path / "forged.sqlite3").resolve(),
            code_sha=CODE_SHA,
        )
    )
    assert case.backend.active_generation == active_generation


@pytest.mark.parametrize("failure_stage", ("verifier", "build", "backend", "path", "stale"))
def test_publication_failure_leaves_previous_generation_served(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    case = _runtime_case(tmp_path)
    verified, core = _candidate(case)
    active_generation = case.backend.active_generation
    proof_path = (tmp_path / "failed-proof.sqlite3").resolve()
    projection_path = (tmp_path / "failed.sqlite3").resolve()

    def fail(*_args: object, **_kwargs: object) -> Any:
        raise RuntimeError("sensitive dependency value")

    build_calls: list[object] = []
    if failure_stage == "verifier":
        monkeypatch.setattr(sync_publication, "verify_catalog_core_evidence", fail)
    elif failure_stage == "build":
        monkeypatch.setattr(sync_publication, "build_catalog_projection", fail)
    elif failure_stage == "backend":
        monkeypatch.setattr(runtime_api, "_new_evidence_bound_generation", fail)
    elif failure_stage == "path":
        original_output_path = sync_publication._output_path
        candidate_resolutions = 0

        def redirect_path(value: Path) -> Path:
            nonlocal candidate_resolutions
            resolved = original_output_path(value)
            if value == projection_path:
                candidate_resolutions += 1
                if candidate_resolutions == 2:
                    return (tmp_path / "redirected.sqlite3").resolve()
            return resolved

        def track_build(*_args: object, **_kwargs: object) -> object:
            build_calls.append(object())
            raise AssertionError

        monkeypatch.setattr(sync_publication, "_output_path", redirect_path)
        monkeypatch.setattr(sync_publication, "build_catalog_projection", track_build)
    else:

        def stale_publish(
            _self: SyncCore,
            *,
            expected_active_generation: str,
            publisher: Any,
        ) -> None:
            del expected_active_generation
            publisher(replace(core.active_dataset(), event_lineage_sha256="f" * 64))

        monkeypatch.setattr(SyncCore, "publish_active_dataset", stale_publish)
    _assert_fixed_rejection(
        lambda: publish_reconciled_generation(
            core,
            verified,
            backend=case.backend,
            cursor_codec=case.codec,
            proof_projection_path=proof_path,
            projection_path=projection_path,
            code_sha=CODE_SHA,
        )
    )
    assert case.backend.active_generation == active_generation
    lease = case.backend.acquire(control=_control())
    assert lease.dataset_generation == active_generation
    lease.close()
    assert not proof_path.exists()
    assert projection_path.is_file() is (failure_stage in {"backend", "stale"})
    assert build_calls == []


def test_intervening_backend_aba_activation_wins_conditional_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _runtime_case(tmp_path)
    verified, core = _candidate(case)
    intervening_records = (
        replace(case.records[0], commercial_title="Intervening synthetic title"),
        *case.records[1:],
    )
    intervening_verified = _verified(intervening_records, "e" * 64)
    intervening_evidence = verify_catalog_core_evidence(
        intervening_verified,
        projection_path=(tmp_path / "intervening-proof.sqlite3").resolve(),
        code_sha=CODE_SHA,
    )
    intervening_projection = build_catalog_projection(
        (tmp_path / "intervening.sqlite3").resolve(),
        manifest=intervening_verified.generation.dataset_manifest,
        records=intervening_records,
    )
    initial_generation = case.backend.active_generation
    tokens = [case.backend.capture_activation_token()]
    original_build = sync_publication.build_catalog_projection

    def interleaving_build(*args: object, **kwargs: object) -> object:
        candidate = original_build(*args, **kwargs)
        case.backend.activate(
            intervening_verified,
            intervening_projection,
            case.codec,
            intervening_evidence,
        )
        tokens.append(case.backend.capture_activation_token())
        case.backend.activate(case.verified, case.projection, case.codec, case.evidence)
        tokens.append(case.backend.capture_activation_token())
        return candidate

    monkeypatch.setattr(sync_publication, "build_catalog_projection", interleaving_build)
    _assert_fixed_rejection(
        lambda: publish_reconciled_generation(
            core,
            verified,
            backend=case.backend,
            cursor_codec=case.codec,
            proof_projection_path=(tmp_path / "slow-proof.sqlite3").resolve(),
            projection_path=(tmp_path / "slow.sqlite3").resolve(),
            code_sha=CODE_SHA,
        )
    )

    assert case.backend.active_generation == initial_generation
    assert tokens[0] is not tokens[1] and tokens[1] is not tokens[2]

    foreign_generation = sync_helpers._reconciled_generation(
        case.records,
        generated_at="2026-09-06T00:00:00Z",
        shop_domain="foreign.myshopify.com",
    )
    foreign_verified = VerifiedReconciledGenerationV1(foreign_generation, "f" * 64)
    foreign_evidence = verify_catalog_core_evidence(
        foreign_verified,
        projection_path=(tmp_path / "foreign-proof.sqlite3").resolve(),
        code_sha=CODE_SHA,
    )
    foreign_projection = build_catalog_projection(
        (tmp_path / "foreign.sqlite3").resolve(),
        manifest=foreign_generation.dataset_manifest,
        records=foreign_generation.records,
    )
    current_token = case.backend.capture_activation_token()
    with pytest.raises(runtime_api.RuntimeApiContractError):
        case.backend.activate_if_current(
            current_token,
            foreign_verified,
            foreign_projection,
            case.codec,
            foreign_evidence,
        )
    assert case.backend.active_generation == initial_generation
    assert case.backend.capture_activation_token() is current_token
