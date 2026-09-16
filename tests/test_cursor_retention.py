"""Keep signed HTTP pagination pinned across verified generation activation."""

from dataclasses import replace
from datetime import timedelta

import pytest

import test_runtime_api_integration as integration
from nla_catalog_gateway import runtime_api
from nla_catalog_gateway.pagination import CatalogProjection, CursorCodecV1
from nla_catalog_gateway.runtime_api import (
    CatalogBackendFailure,
    CatalogResponseEnvelopeV1,
    RequestCancellation,
    RequestControl,
    RequestDeadlineExceeded,
    RuntimeApiContractError,
)
from nla_catalog_gateway.runtime_contract import CatalogErrorCode
from nla_catalog_gateway.taxonomy import Game
from test_runtime_suggestions import _request
from test_runtime_suggestions import http_case as _http_case

http_case = _http_case


def _activate(case, candidate, codec=None):
    case.backend.activate(
        candidate.verified, candidate.projection, codec or candidate.codec, candidate.evidence
    )


def _changed(case, tmp_path, name="changed"):
    records = tuple(replace(r, commercial_title=name) for r in case.records)
    return integration._bound_case(tmp_path, name, records, "b" * 64)


def _page(response):
    assert response.status == 200, response.body
    return CatalogResponseEnvelopeV1.from_json_bytes(response.body)


def _assert_error(response, code):
    assert response.status != 200
    assert code.value.encode() in response.body


def _context(page, codec, request, now=integration.CURSOR_NOW):
    return codec.decode(page.next_cursor, expected_request=request, now=now)


@pytest.fixture
def timed_case(http_case, monkeypatch):
    case, call = http_case
    now = [integration.CURSOR_NOW]
    monkeypatch.setattr(case.backend, "_clock", lambda: now[0])
    _activate(case, case)
    return case, call, now


@pytest.mark.parametrize("query", [None, "bolt", "019", "met-00"])
@pytest.mark.parametrize("sold_out_only", [False, True])
def test_signed_traversal_survives_multiple_activations(http_case, tmp_path, query, sold_out_only):
    case, call = http_case
    selected = _request(query, page_size=1, in_stock=False if sold_out_only else None)
    page = _page(call(selected))
    old_generation = page.page.dataset_generation
    found = list(integration._gids(page))
    for name in ("second", "third"):
        new = _changed(case, tmp_path, name)
        _activate(case, new)
        fresh = _page(call(selected))
        assert fresh.page.dataset_generation == new.backend.active_generation != old_generation
        page = _page(call(selected, page.next_cursor))
        assert page.page.dataset_generation == old_generation
        found.extend(integration._gids(page))
    while page.next_cursor is not None:
        page = _page(call(selected, page.next_cursor))
        assert page.page.dataset_generation == old_generation
        found.extend(integration._gids(page))
    expected = (1, 3, 4) if sold_out_only else (1, 2, 3, 4)
    assert found == [f"gid://shopify/Product/{number}" for number in expected]
    assert len(found) == len(set(found))


def test_inflight_http_first_page_retains_its_actual_expiry(timed_case, tmp_path, monkeypatch):
    case, call, now = timed_case
    new = _changed(case, tmp_path)
    original = runtime_api._fetch_evidence_bound_page
    original_generation = case.backend.active_generation

    def activate_before_emission(*args, **kwargs):
        _activate(case, new)
        now[0] += timedelta(seconds=10)
        return original(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(runtime_api, "_fetch_evidence_bound_page", activate_before_emission)
        first = _page(call(_request(page_size=1)))
    assert first.page.dataset_generation == original_generation
    expiry = _context(first, case.codec, _request(page_size=1), now[0]).expires_at
    assert expiry == case.codec.expires_at(now[0])
    now[0] += timedelta(seconds=1799)
    second = _page(call(_request(page_size=1), first.next_cursor))
    assert second.page.dataset_generation == original_generation
    assert _context(second, case.codec, _request(page_size=1), now[0]).expires_at == expiry
    now[0] += timedelta(seconds=1)
    _assert_error(call(_request(page_size=1), second.next_cursor), CatalogErrorCode.INVALID_CURSOR)


def test_same_dataset_key_rotation_keeps_original_codec(http_case):
    case, call = http_case
    request = _request(page_size=1)
    first = _page(call(request))
    new_codec = CursorCodecV1(b"r" * 32, ttl_seconds=60)
    _activate(case, case, new_codec)
    fresh = _page(call(request))
    assert fresh.page.dataset_generation == first.page.dataset_generation
    assert fresh.next_cursor != first.next_cursor
    for original, codec in ((first, case.codec), (fresh, new_codec)):
        second = _page(call(request, original.next_cursor))
        context = codec.decode(
            second.next_cursor, expected_request=request, now=integration.CURSOR_NOW
        )
        assert context.expires_at == _context(original, codec, request).expires_at
    assert len(case.backend._cursor_generations) == 2


@pytest.mark.parametrize("change", ["game", "query", "filter", "unknown", "tampered", "expired"])
def test_retained_cursor_rejections_precede_database_reads(
    http_case, tmp_path, monkeypatch, change
):
    case, call = http_case
    request = _request(page_size=1)
    first = _page(call(request))
    new = _changed(case, tmp_path)
    _activate(case, new)
    cursor = first.next_cursor
    expected = CatalogErrorCode.CURSOR_CONTEXT_MISMATCH
    if change == "game":
        request = replace(request, game=Game.POKEMON)
    elif change == "query":
        request = replace(request, query="other")
    elif change == "filter":
        request = replace(request, filters=replace(request.filters, in_stock=True))
    elif change == "unknown":
        cursor = case.codec.encode(
            replace(_context(first, case.codec, request), dataset_generation="sha256:" + "0" * 64)
        )
        expected = CatalogErrorCode.RESTART_REQUIRED
    elif change == "expired":
        cursor = case.codec.encode(
            replace(_context(first, case.codec, request), expires_at="2026-09-06T12:00:00Z")
        )
        expected = CatalogErrorCode.INVALID_CURSOR
    else:
        cursor = "invalid.signature"
        expected = CatalogErrorCode.INVALID_CURSOR
    reads = []

    def forbidden_read(*_args, **_kwargs):
        reads.append(True)
        raise AssertionError("unverified cursor reached SQL")

    monkeypatch.setattr(CatalogProjection, "fetch_page", forbidden_read)
    _assert_error(call(request, cursor), expected)
    assert not reads


@pytest.mark.parametrize("failure", ["file", "evidence"])
def test_retained_generation_keeps_integrity_and_evidence_gates(http_case, tmp_path, failure):
    case, call = http_case
    request = _request(page_size=1)
    first = _page(call(request))
    _activate(case, _changed(case, tmp_path))
    if failure == "file":
        # Relocate only this test's fixture, never a real catalog package.
        case.projection.path.rename(tmp_path / "unavailable.sqlite3")
    else:
        object.__setattr__(case.evidence, "verification_version", 0)
    assert call(request, first.next_cursor).status == 503
    assert call(request).status == 200


def test_capacity_defers_activation_without_evicting_live_cursors(
    timed_case, tmp_path, monkeypatch
):
    case, call, now = timed_case
    monkeypatch.setattr(runtime_api, "MAX_CURSOR_GENERATIONS", 1)
    request = _request(page_size=1)
    first = _page(call(request))
    new = _changed(case, tmp_path)
    with pytest.raises(RuntimeApiContractError, match="retention capacity"):
        _activate(case, new)
    assert case.backend.active_generation == first.page.dataset_generation
    _activate(case, case)  # Reusing the same binding needs no additional slot.
    assert call(request, first.next_cursor).status == 200
    now[0] += timedelta(seconds=1800)
    _activate(case, new)
    assert not case.backend._cursor_generations
    assert case.projection.path.is_file()  # Expiry releases memory, not files.
    assert call(request).status == 200
    _assert_error(call(request, first.next_cursor), CatalogErrorCode.INVALID_CURSOR)


def test_open_lease_reserves_capacity_and_close_is_idempotent(http_case, tmp_path, monkeypatch):
    case, _ = http_case
    monkeypatch.setattr(runtime_api, "MAX_CURSOR_GENERATIONS", 1)
    lease = case.backend.acquire(control=integration._control())
    slot = next(iter(case.backend._cursor_generations.values()))
    new = _changed(case, tmp_path)
    with pytest.raises(RuntimeApiContractError, match="retention capacity"):
        _activate(case, new)
    lease.close()
    lease.close()
    assert slot.leases == 0
    _activate(case, new)
    assert not case.backend._cursor_generations
    with pytest.raises(CatalogBackendFailure):
        lease.fetch_page(_request(), None, control=integration._control())


def test_acquire_failure_and_cancellation_do_not_leak_slots(http_case, monkeypatch):
    case, _ = http_case
    ticks = iter((0, 10))
    control = RequestControl(10, RequestCancellation(), lambda: next(ticks))
    with pytest.raises(RequestDeadlineExceeded):
        case.backend.acquire(control=control)
    assert all(slot.leases == 0 for slot in case.backend._cursor_generations.values())
    with pytest.raises(CatalogBackendFailure) as missing_request:
        case.backend.acquire(control=integration._control(), cursor="invalid.signature")
    assert missing_request.value.code is CatalogErrorCode.INVALID_CURSOR
    monkeypatch.setattr(runtime_api, "MAX_CURSOR_GENERATIONS", 0)
    with pytest.raises(CatalogBackendFailure) as full:
        case.backend.acquire(control=integration._control())
    assert full.value.code is CatalogErrorCode.TEMPORARILY_UNAVAILABLE
    assert not case.backend._cursor_generations


@pytest.mark.parametrize("bad_clock", [None, integration.CURSOR_NOW.replace(tzinfo=None)])
def test_invalid_retention_clock_fails_closed(http_case, monkeypatch, bad_clock):
    case, call = http_case
    monkeypatch.setattr(case.backend, "_clock", lambda: bad_clock)
    assert call(_request()).status == 503


def test_restart_does_not_claim_in_memory_cursor_history(http_case, tmp_path):
    case, call = http_case
    first = _page(call(_request(page_size=1)))
    new = _changed(case, tmp_path)
    with pytest.raises(CatalogBackendFailure) as missing:
        new.backend.acquire(
            control=integration._control(), request=_request(page_size=1), cursor=first.next_cursor
        )
    assert missing.value.code is CatalogErrorCode.RESTART_REQUIRED
