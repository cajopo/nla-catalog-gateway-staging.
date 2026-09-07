from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import test_app_proxy_security as proxy_helpers
import test_core_evidence as evidence_helpers
import test_generation_bundle as bundle_helpers
from nla_catalog_gateway import core_evidence, pagination, runtime_api
from nla_catalog_gateway.app_proxy_security import (
    AppProxyConfigurationError,
    AppProxyVerifier,
)
from nla_catalog_gateway.core_evidence import verify_catalog_core_evidence
from nla_catalog_gateway.generation_bundle import VerifiedReconciledGenerationV1
from nla_catalog_gateway.pagination import (
    CatalogProjection,
    CursorCodecV1,
    build_catalog_projection,
)
from nla_catalog_gateway.runtime_api import (
    AppProxyVerifierAuthorizer,
    CatalogBackendFailure,
    CatalogRequestEnvelopeV1,
    EvidenceBoundCapabilityGate,
    EvidenceBoundCatalogBackend,
    ProxyRequestRejected,
    ProxyVerifierUnavailable,
    RequestCancellation,
    RequestCancelled,
    RequestControl,
    RuntimeApiContractError,
)
from nla_catalog_gateway.runtime_contract import (
    CatalogErrorCode,
    CatalogFiltersV1,
    CatalogRequestV1,
    RequestFamily,
)
from nla_catalog_gateway.taxonomy import Game

CODE_SHA = "c" * 40
CURSOR_KEY = b"k" * 32
CURSOR_NOW = datetime(2026, 9, 6, 12, tzinfo=UTC)


def _control(cancellation: Any = None) -> RequestControl:
    return RequestControl(
        10,
        RequestCancellation() if cancellation is None else cancellation,
        lambda: 0,
    )


def _request(
    *,
    family: RequestFamily = RequestFamily.ALL,
    query: str | None = None,
    in_stock: bool | None = None,
    subtype: str | None = None,
    page_size: int = 100,
) -> CatalogRequestV1:
    return CatalogRequestV1(
        game=Game.MAGIC,
        product_family=family,
        query=query,
        filters=CatalogFiltersV1(
            in_stock=in_stock,
            product_subtype=subtype,
        ),
        page_size=page_size,
    )


def _bound_case(
    tmp_path: Path,
    name: str,
    records: tuple[Any, ...],
    summary_sha256: str,
) -> SimpleNamespace:
    _, _, generation = bundle_helpers._generation(records)
    verified = VerifiedReconciledGenerationV1(generation, summary_sha256)
    evidence = verify_catalog_core_evidence(
        verified,
        projection_path=(tmp_path / f"{name}-proof.sqlite3").resolve(),
        code_sha=CODE_SHA,
    )
    projection = build_catalog_projection(
        tmp_path / f"{name}.sqlite3",
        manifest=generation.dataset_manifest,
        records=records,
    )
    codec = CursorCodecV1(CURSOR_KEY, ttl_seconds=1_800)
    backend = EvidenceBoundCatalogBackend(
        verified,
        projection,
        codec,
        evidence,
        expected_code_sha=CODE_SHA,
        clock=lambda: CURSOR_NOW,
    )
    return SimpleNamespace(
        verified=verified,
        projection=projection,
        codec=codec,
        evidence=evidence,
        backend=backend,
        gate=EvidenceBoundCapabilityGate(backend),
        records=records,
    )


def _gids(result: Any) -> tuple[str, ...]:
    return tuple(item.product_gid for item in result.page.items)


def test_request_envelope_rejects_query_that_exceeds_bound_after_nfkc() -> None:
    query = "\ufb03" * 256
    assert len(query) == runtime_api.MAX_QUERY_CHARS
    with pytest.raises(RuntimeApiContractError):
        CatalogRequestEnvelopeV1(
            _request(family=RequestFamily.SINGLE, query=query),
            None,
        )


def test_proxy_authorizer_uses_real_verifier_and_value_free_error_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = AppProxyVerifierAuthorizer(proxy_helpers._verifier())
    control = _control()

    identity = adapter.verify(
        raw_query=proxy_helpers._signed_query(),
        request_path="/proxy/catalog",
        control=control,
    )
    assert identity.shop_domain == proxy_helpers._TEST_SHOP

    with pytest.raises(ProxyRequestRejected) as rejected:
        adapter.verify(
            raw_query=proxy_helpers._signed_query(key=b"attacker"),
            request_path="/proxy/catalog",
            control=control,
        )
    assert str(rejected.value) == ""
    assert rejected.value.__cause__ is None
    assert rejected.value.__context__ is None

    def unavailable(
        _self: AppProxyVerifier,
        *,
        raw_query: bytes,
        request_path: str,
    ) -> Any:
        del raw_query, request_path
        raise AppProxyConfigurationError("sensitive configuration")

    monkeypatch.setattr(AppProxyVerifier, "verify", unavailable)
    with pytest.raises(ProxyVerifierUnavailable) as unavailable_error:
        adapter.verify(
            raw_query=b"sensitive query",
            request_path="/proxy/catalog",
            control=control,
        )
    assert str(unavailable_error.value) == ""
    assert unavailable_error.value.__cause__ is None
    assert unavailable_error.value.__context__ is None

    def internal(
        _self: AppProxyVerifier,
        *,
        raw_query: bytes,
        request_path: str,
    ) -> Any:
        del raw_query, request_path
        raise RuntimeError("sensitive internal value")

    monkeypatch.setattr(AppProxyVerifier, "verify", internal)
    with pytest.raises(ProxyVerifierUnavailable) as internal_error:
        adapter.verify(
            raw_query=b"sensitive query",
            request_path="/proxy/catalog",
            control=control,
        )
    assert str(internal_error.value) == ""
    assert internal_error.value.__cause__ is None
    assert internal_error.value.__context__ is None


def test_proxy_authorizer_rejects_invalid_dependency_and_untrusted_outputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(RuntimeApiContractError):
        AppProxyVerifierAuthorizer(object())  # type: ignore[arg-type]

    verifier = proxy_helpers._verifier()
    adapter = AppProxyVerifierAuthorizer(verifier)

    def wrong_output(
        _self: AppProxyVerifier,
        *,
        raw_query: bytes,
        request_path: str,
    ) -> object:
        del raw_query, request_path
        return object()

    monkeypatch.setattr(AppProxyVerifier, "verify", wrong_output)
    with pytest.raises(ProxyVerifierUnavailable):
        adapter.verify(raw_query=b"redacted", request_path="/proxy/catalog", control=_control())

    invalid_verified = runtime_api.VerifiedAppProxyRequest(
        "invalid.example.com",
        "/proxy/catalog",
    )

    def invalid_identity(
        _self: AppProxyVerifier,
        *,
        raw_query: bytes,
        request_path: str,
    ) -> Any:
        del raw_query, request_path
        return invalid_verified

    monkeypatch.setattr(AppProxyVerifier, "verify", invalid_identity)
    with pytest.raises(ProxyVerifierUnavailable):
        adapter.verify(raw_query=b"redacted", request_path="/proxy/catalog", control=_control())


def test_bound_backend_browses_searches_and_filters_real_synthetic_catalog(
    tmp_path: Path,
) -> None:
    case = _bound_case(tmp_path, "catalog", evidence_helpers._records(), "a" * 64)
    control = _control()
    lease = case.backend.acquire(control=control)
    assert case.gate.ready(lease, control=control) is True

    sealed = _request(family=RequestFamily.SEALED, page_size=1)
    case.gate.require_catalog(lease, sealed, control=control)
    first = lease.fetch_page(sealed, None, control=control)
    assert _gids(first) == ("gid://shopify/Product/4",)
    assert first.next_cursor is not None
    second = lease.fetch_page(sealed, first.next_cursor, control=control)
    assert _gids(second) == ("gid://shopify/Product/5",)
    assert second.next_cursor is None

    search = _request(
        family=RequestFamily.SINGLE,
        query="Shared magic",
        page_size=1,
    )
    searched = lease.fetch_page(search, None, control=control)
    assert _gids(searched) == ("gid://shopify/Product/1",)
    assert searched.next_cursor is not None
    searched_next = lease.fetch_page(search, searched.next_cursor, control=control)
    assert _gids(searched_next) == ("gid://shopify/Product/2",)
    assert searched_next.next_cursor is None

    in_stock = _request(
        family=RequestFamily.SINGLE,
        query="Shared magic",
        in_stock=True,
    )
    assert _gids(lease.fetch_page(in_stock, None, control=control)) == ("gid://shopify/Product/1",)

    subtype = _request(
        family=RequestFamily.SEALED,
        subtype="booster-box",
    )
    filtered = lease.fetch_page(subtype, None, control=control)
    assert _gids(filtered) == ("gid://shopify/Product/4",)
    assert "facets" not in filtered.page.as_dict()
    assert "suggestions" not in filtered.page.as_dict()

    lease.close()
    lease.close()
    assert case.gate.ready(lease, control=control) is False
    with pytest.raises(CatalogBackendFailure) as closed:
        lease.fetch_page(sealed, None, control=control)
    assert closed.value.code is CatalogErrorCode.DATASET_UNAVAILABLE


def test_bound_backend_rejects_invalid_construction_control_and_typed_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _bound_case(tmp_path, "backend-guards", evidence_helpers._records(), "a" * 64)
    control = _control()
    lease = case.backend.acquire(control=control)
    assert lease.shop_domain == bundle_helpers.SHOP

    with pytest.raises(RuntimeApiContractError):
        EvidenceBoundCatalogBackend(
            case.verified,
            case.projection,
            case.codec,
            case.evidence,
            expected_code_sha="invalid",
        )
    with pytest.raises(CatalogBackendFailure) as invalid_acquire:
        case.backend.acquire(control=object())  # type: ignore[arg-type]
    assert invalid_acquire.value.code is CatalogErrorCode.TEMPORARILY_UNAVAILABLE
    with pytest.raises(CatalogBackendFailure) as invalid_fetch:
        lease.fetch_page(_request(), None, control=object())  # type: ignore[arg-type]
    assert invalid_fetch.value.code is CatalogErrorCode.TEMPORARILY_UNAVAILABLE
    with pytest.raises(RuntimeApiContractError):
        EvidenceBoundCapabilityGate(object())  # type: ignore[arg-type]
    assert case.gate.ready(object(), control=control) is False  # type: ignore[arg-type]

    closed: list[Any] = []
    original_close = runtime_api.EvidenceBoundCatalogLease.close

    def tracked_close(self: Any) -> None:
        closed.append(self)
        original_close(self)

    monkeypatch.setattr(runtime_api.EvidenceBoundCatalogLease, "close", tracked_close)
    ticks = iter((0, 10))
    expiring = RequestControl(10, RequestCancellation(), lambda: next(ticks))
    with pytest.raises(runtime_api.RequestDeadlineExceeded):
        case.backend.acquire(control=expiring)
    assert len(closed) == 1

    def typed_failure(*_args: Any, **_kwargs: Any) -> Any:
        raise CatalogBackendFailure(CatalogErrorCode.DATASET_UNAVAILABLE)

    monkeypatch.setattr(runtime_api, "_fetch_evidence_bound_page", typed_failure)
    with pytest.raises(CatalogBackendFailure) as typed:
        lease.fetch_page(_request(), None, control=control)
    assert typed.value.code is CatalogErrorCode.DATASET_UNAVAILABLE

    uninitialized_gate = object.__new__(EvidenceBoundCapabilityGate)
    assert (
        runtime_api._runtime_composition_is_evidence_bound(
            AppProxyVerifierAuthorizer(proxy_helpers._verifier()),
            case.backend,
            uninitialized_gate,
        )
        is False
    )


def test_invalid_query_cursor_is_rejected_before_search_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _bound_case(tmp_path, "invalid-cursor", evidence_helpers._records(), "a" * 64)
    lease = case.backend.acquire(control=_control())

    def forbidden_search(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("search must not run before cursor verification")

    monkeypatch.setattr(runtime_api, "search_single_cards", forbidden_search)
    with pytest.raises(CatalogBackendFailure) as invalid:
        lease.fetch_page(
            _request(family=RequestFamily.SINGLE, query="Shared magic"),
            "bad.signature",
            control=_control(),
        )
    assert invalid.value.code is CatalogErrorCode.INVALID_CURSOR


def test_evidence_generation_constructor_rejects_each_malformed_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _bound_case(tmp_path, "constructor-guards", evidence_helpers._records(), "a" * 64)
    generation = case.verified.generation
    parts = generation.source_manifest.parts

    def verified_with_parts(candidate_parts: tuple[Any, ...]) -> VerifiedReconciledGenerationV1:
        source = replace(generation.source_manifest, parts=candidate_parts)
        candidate = replace(generation, source_manifest=source)
        return VerifiedReconciledGenerationV1(candidate, case.verified.summary_sha256)

    def construct(
        verified: Any = case.verified,
        projection: Any = case.projection,
    ) -> Any:
        return runtime_api._new_evidence_bound_generation(
            verified,
            projection,
            case.codec,
            case.evidence,
            expected_code_sha=CODE_SHA,
            clock=lambda: CURSOR_NOW,
        )

    with pytest.raises(RuntimeApiContractError):
        construct(verified=object())
    with pytest.raises(RuntimeApiContractError):
        construct(verified=verified_with_parts((parts[0],)))

    foreign = bundle_helpers._replace_part_manifest(
        parts[1],
        shop_domain="foreign.myshopify.com",
    )
    with pytest.raises(RuntimeApiContractError):
        construct(verified=verified_with_parts((parts[0], foreign)))

    forged_fingerprint = replace(
        case.projection._file_fingerprint,
        content_sha256="0" * 64,
    )
    forged_projection = replace(case.projection, _file_fingerprint=forged_fingerprint)
    with pytest.raises(RuntimeApiContractError):
        construct(projection=forged_projection)

    def broken_open(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("sensitive")

    monkeypatch.setattr(CatalogProjection, "open", broken_open)
    with pytest.raises(RuntimeApiContractError) as unexpected:
        construct()
    assert unexpected.value.__cause__ is None


def test_current_evidence_binding_rejects_malformed_and_unreadable_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _bound_case(tmp_path, "current-binding", evidence_helpers._records(), "a" * 64)
    active = case.backend._active
    assert runtime_api._evidence_binding_is_current(object()) is False
    assert runtime_api._evidence_binding_is_current(replace(active, cursor_codec=object())) is False

    generation = active.verified.generation
    source = replace(generation.source_manifest, parts=(generation.source_manifest.parts[0],))
    malformed = VerifiedReconciledGenerationV1(
        replace(generation, source_manifest=source),
        active.verified.summary_sha256,
    )
    assert runtime_api._evidence_binding_is_current(replace(active, verified=malformed)) is False

    def unreadable(_self: CatalogProjection) -> None:
        raise RuntimeError("sensitive")

    monkeypatch.setattr(CatalogProjection, "_assert_file_unchanged", unreadable)
    assert runtime_api._evidence_binding_is_current(active) is False


def test_runtime_private_validators_and_execution_error_mapping_are_total(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def invalid_normalization(_query: str) -> str:
        raise runtime_api.CanonicalSearchError("fixed")

    monkeypatch.setattr(runtime_api, "normalize_search_text", invalid_normalization)
    with pytest.raises(RuntimeApiContractError):
        runtime_api._validate_query_bound("query")
    for gid in (object(), "gid://shopify/Product/0"):
        with pytest.raises(RuntimeApiContractError):
            runtime_api._product_gid_key(gid)  # type: ignore[arg-type]

    assert runtime_api._canonical_request(object()) is False
    malformed_request = _request()
    object.__setattr__(malformed_request, "page_size", 0)
    assert runtime_api._canonical_request(malformed_request) is False

    cases = (
        (runtime_api.CursorContextMismatchError("fixed"), CatalogErrorCode.CURSOR_CONTEXT_MISMATCH),
        (runtime_api.DatasetUnavailableError("fixed"), CatalogErrorCode.DATASET_UNAVAILABLE),
        (
            runtime_api.UnsupportedPaginationRequestError("fixed"),
            CatalogErrorCode.UNSUPPORTED_CAPABILITY,
        ),
        (runtime_api.CanonicalSearchError("fixed"), CatalogErrorCode.DATASET_UNAVAILABLE),
        (runtime_api.FacetContractError("fixed"), CatalogErrorCode.DATASET_UNAVAILABLE),
        (runtime_api.RuntimeContractError("fixed"), CatalogErrorCode.DATASET_UNAVAILABLE),
        (runtime_api.PaginationContractError("fixed"), CatalogErrorCode.TEMPORARILY_UNAVAILABLE),
        (RuntimeError("fixed"), CatalogErrorCode.TEMPORARILY_UNAVAILABLE),
    )
    for error, expected in cases:
        assert runtime_api._catalog_execution_error_code(error) is expected


def test_whitespace_search_uses_game_scoped_browse_and_noncanonical_input_is_denied(
    tmp_path: Path,
) -> None:
    case = _bound_case(tmp_path, "browse", evidence_helpers._records(), "a" * 64)
    control = _control()
    lease = case.backend.acquire(control=control)

    request = _request(family=RequestFamily.SINGLE, query=" \t ", page_size=2)
    first = lease.fetch_page(request, None, control=control)
    assert _gids(first) == ("gid://shopify/Product/1", "gid://shopify/Product/2")
    assert first.next_cursor is not None

    with pytest.raises(CatalogBackendFailure) as denied:
        runtime_api._fetch_evidence_bound_page(
            case.backend._active,
            object(),  # type: ignore[arg-type]
            None,
            control=control,
        )
    assert denied.value.code is CatalogErrorCode.UNSUPPORTED_CAPABILITY


def test_activation_pins_old_lease_and_rejects_old_cursor_on_new_generation(
    tmp_path: Path,
) -> None:
    records_a = evidence_helpers._records()
    records_b = (
        replace(records_a[0], commercial_title="Changed synthetic title"),
        *records_a[1:],
    )
    case_a = _bound_case(tmp_path, "a", records_a, "a" * 64)
    case_b = _bound_case(tmp_path, "b", records_b, "b" * 64)
    control = _control()
    request = _request(family=RequestFamily.SINGLE, page_size=1)
    old_lease = case_a.backend.acquire(control=control)
    first = old_lease.fetch_page(request, None, control=control)
    old_generation = old_lease.dataset_generation
    assert first.next_cursor is not None

    with pytest.raises(RuntimeApiContractError):
        case_a.backend.activate(
            case_b.verified,
            case_b.projection,
            case_b.codec,
            case_a.evidence,
        )
    assert case_a.backend.active_generation == old_generation

    case_a.backend.activate(
        case_b.verified,
        case_b.projection,
        case_b.codec,
        case_b.evidence,
    )
    assert case_a.backend.active_generation != old_generation
    assert case_a.gate.ready(old_lease, control=control) is True
    assert _gids(old_lease.fetch_page(request, first.next_cursor, control=control)) == (
        "gid://shopify/Product/2",
    )

    new_lease = case_a.backend.acquire(control=control)
    with pytest.raises(CatalogBackendFailure) as stale:
        new_lease.fetch_page(request, first.next_cursor, control=control)
    assert stale.value.code is CatalogErrorCode.RESTART_REQUIRED


def test_gate_rejects_foreign_lease_and_binding_mismatch_is_value_free(
    tmp_path: Path,
) -> None:
    records = evidence_helpers._records()
    case = _bound_case(tmp_path, "accepted", records, "a" * 64)
    foreign = EvidenceBoundCatalogBackend(
        case.verified,
        case.projection,
        case.codec,
        case.evidence,
        expected_code_sha=CODE_SHA,
        clock=lambda: CURSOR_NOW,
    )
    foreign_lease = foreign.acquire(control=_control())
    with pytest.raises(CatalogBackendFailure) as denied:
        case.gate.require_catalog(foreign_lease, _request(), control=_control())
    assert denied.value.code is CatalogErrorCode.UNSUPPORTED_CAPABILITY

    bad_evidence = core_evidence._new_evidence(
        shop_domain=case.evidence.shop_domain,
        summary_sha256="f" * 64,
        dataset_generation=case.evidence.dataset_generation,
        catalog_content_sha256=case.evidence.catalog_content_sha256,
        projection_fingerprint=case.evidence.projection_fingerprint,
        code_sha=case.evidence.code_sha,
    )
    with pytest.raises(RuntimeApiContractError) as mismatch:
        EvidenceBoundCatalogBackend(
            case.verified,
            case.projection,
            case.codec,
            bad_evidence,
            expected_code_sha=CODE_SHA,
        )
    assert str(mismatch.value) == "catalog runtime binding is invalid"
    assert mismatch.value.__cause__ is None
    assert case.verified.generation.source_manifest.parts[0].source_code_sha == "b" * 40
    assert case.evidence.code_sha == CODE_SHA
    assert (
        case.evidence.code_sha != case.verified.generation.source_manifest.parts[0].source_code_sha
    )


class _TriggeredCancellation:
    def __init__(self, error: RequestCancelled) -> None:
        self.active = False
        self.error = error

    def raise_if_cancelled(self) -> None:
        if self.active:
            raise self.error


@pytest.mark.parametrize("phase", ["search", "facets", "sqlite"])
def test_runtime_paths_propagate_identical_cancellation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    case = _bound_case(tmp_path, phase, evidence_helpers._records(), "a" * 64)
    cancellation = RequestCancelled()
    trigger = _TriggeredCancellation(cancellation)
    control = _control(trigger)
    lease = case.backend.acquire(control=control)

    if phase == "search":
        original_search = runtime_api.search_single_cards

        def entering_search(*args: Any, **kwargs: Any) -> Any:
            trigger.active = True
            return original_search(*args, **kwargs)

        monkeypatch.setattr(runtime_api, "search_single_cards", entering_search)
        request = _request(family=RequestFamily.SINGLE, query="Shared magic")
    elif phase == "facets":
        original_facets = runtime_api.evaluate_facets

        def entering_facets(*args: Any, **kwargs: Any) -> Any:
            trigger.active = True
            return original_facets(*args, **kwargs)

        monkeypatch.setattr(runtime_api, "evaluate_facets", entering_facets)
        request = _request(in_stock=True)
    else:
        original_rows = CatalogProjection._product_rows

        def long_product_rows(
            connection: sqlite3.Connection,
            *,
            request: CatalogRequestV1,
            after_digits: str | None,
            limit: int,
        ) -> list[sqlite3.Row]:
            trigger.active = True
            try:
                connection.execute(
                    """WITH RECURSIVE counter(value) AS (
                           VALUES (0)
                           UNION ALL
                           SELECT value + 1 FROM counter WHERE value < 1000000
                       )
                       SELECT sum(value) FROM counter"""
                ).fetchone()
            finally:
                trigger.active = False
            return original_rows(
                connection,
                request=request,
                after_digits=after_digits,
                limit=limit,
            )

        monkeypatch.setattr(
            CatalogProjection,
            "_product_rows",
            staticmethod(long_product_rows),
        )
        request = _request(family=RequestFamily.SEALED)

    with pytest.raises(RequestCancelled) as caught:
        lease.fetch_page(request, None, control=control)
    assert caught.value is cancellation
    if phase == "sqlite":
        assert pagination._SQLITE_PROGRESS_VM_STEPS > 0
