from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import shutil
import sqlite3
import stat
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import nla_catalog_gateway.pagination as pagination
from nla_catalog_gateway.bulk import (
    ALLOWED_TYPES,
    PRODUCT_STATUSES,
    SourceSnapshotEvidence,
    SourceSnapshotManifest,
)
from nla_catalog_gateway.pagination import (
    MAX_CONTRACT_BYTES,
    AtomicCatalogActivation,
    AuthenticatedCatalogPage,
    CatalogPaginator,
    CatalogProjection,
    CursorCodecV1,
    CursorContextMismatchError,
    CursorExpiredError,
    DatasetUnavailableError,
    InvalidCursorError,
    PaginationContractError,
    ProjectionBuildError,
    StaleGenerationError,
    UnsupportedPaginationRequestError,
    build_catalog_projection,
)
from nla_catalog_gateway.runtime_contract import (
    DEFAULT_CAPABILITIES_V1,
    CapabilityState,
    CatalogFiltersV1,
    CatalogPageV1,
    CatalogProductRecordV1,
    CatalogRequestV1,
    CatalogVariantRecordV1,
    CursorContextV1,
    DatasetManifestV1,
    InventoryPolicy,
    ProductStatus,
    RequestFamily,
    SelectedOptionV1,
)
from nla_catalog_gateway.taxonomy import Game, ProductFamily

GENERATION_A = f"sha256:{'a' * 64}"
GENERATION_B = f"sha256:{'b' * 64}"
NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)
HMAC_KEY = b"pagination-test-key-material-placeholder"
OPTIONS = (SelectedOptionV1(name="Language", value="Italiano"),)


def _variant(
    product: str,
    variant: str,
    *,
    inventory_item: str | None = None,
) -> CatalogVariantRecordV1:
    return CatalogVariantRecordV1(
        variant_gid=f"gid://shopify/ProductVariant/{variant}",
        product_gid=f"gid://shopify/Product/{product}",
        inventory_item_gid=(f"gid://shopify/InventoryItem/{inventory_item or variant}"),
        title="Default Title",
        sku=None,
        barcode="",
        selected_options=OPTIONS,
        price_text="1.00",
        compare_at_price_text=None,
        inventory_quantity=1,
        inventory_policy=InventoryPolicy.DENY,
        inventory_tracked=True,
        updated_at="2026-09-01T01:02:03.400Z",
    )


def _record(
    product: str,
    *,
    handle: str | None = None,
    variants: tuple[CatalogVariantRecordV1, ...] | None = None,
    game: Game | None = Game.MAGIC,
    family: ProductFamily = ProductFamily.SINGLE,
    status: ProductStatus = ProductStatus.ACTIVE,
    published: bool = True,
) -> CatalogProductRecordV1:
    is_unclassified = family is ProductFamily.UNCLASSIFIED
    is_sealed = family is ProductFamily.SEALED
    return CatalogProductRecordV1(
        product_gid=f"gid://shopify/Product/{product}",
        handle=handle or f"product-{product}",
        commercial_title="Synthetic product",
        canonical_card_name=None if is_unclassified or is_sealed else "Synthetic card",
        shopify_status=status,
        online_store_published=published,
        powertools_source_id=None,
        sync_source_id=None,
        total_inventory=1,
        tracks_inventory=True,
        updated_at="2026-09-01T01:02:03.400Z",
        game=game,
        product_family=family,
        product_subtype="booster-box" if is_sealed else None,
        classification_rule_version="2026-09-01.1",
        classification_rule_id=None if is_unclassified else f"family:{family.value}",
        unclassified_reason="unknown_type" if is_unclassified else None,
        subtype_rule_id="sealed:booster-box" if is_sealed else None,
        subtype_reason=None,
        variants=variants or (_variant(product, product),),
    )


def _request(
    *,
    page_size: int = 100,
    game: Game = Game.MAGIC,
    family: RequestFamily = RequestFamily.ALL,
    query: str | None = None,
    in_stock: bool | None = None,
) -> CatalogRequestV1:
    return CatalogRequestV1(
        game=game,
        product_family=family,
        query=query,
        filters=CatalogFiltersV1(in_stock=in_stock, product_subtype=None),
        page_size=page_size,
    )


def _projection(
    tmp_path: Path,
    records: tuple[CatalogProductRecordV1, ...],
    *,
    source_marker: str = "a",
    name: str = "catalog.sqlite3",
) -> CatalogProjection:
    return build_catalog_projection(
        tmp_path / name,
        manifest=_manifest(records, source_marker=source_marker),
        records=records,
    )


def _manifest(
    records: tuple[CatalogProductRecordV1, ...], *, source_marker: str = "a"
) -> DatasetManifestV1:
    product_count = len(records)
    variant_count = sum(len(record.variants) for record in records)
    active_published = sum(record.publishable for record in records)
    identities = sum(record.powertools_source_id is not None for record in records)
    status_counts = tuple(
        (status, sum(record.shopify_status.value == status for record in records))
        for status in PRODUCT_STATUSES
    )
    object_counts = dict.fromkeys(ALLOWED_TYPES, 0)
    object_counts["Product"] = product_count
    object_counts["ProductVariant"] = variant_count
    source = SourceSnapshotManifest(
        schema_version=2,
        source=SourceSnapshotEvidence(
            shop_domain="synthetic.myshopify.com",
            api_version="2026-07",
            operation_id="gid://shopify/BulkOperation/1",
            status="COMPLETED",
            partial_data_url_present=False,
            file_size=1234,
            object_count=product_count + variant_count,
            product_count=product_count,
            expected_active_online_store_published_product_count=active_published,
            query_sha256=source_marker * 64,
            online_store_publication_gid="gid://shopify/Publication/1",
            completed_at="2026-09-01T01:00:00Z",
            source_code_sha="d" * 40,
        ),
        snapshot_sha256="e" * 64,
        database_sha256="f" * 64,
        snapshot_bytes=1234,
        line_count=product_count + variant_count,
        object_counts=tuple((name, object_counts[name]) for name in ALLOWED_TYPES),
        product_status_counts=status_counts,
        verified_active_online_store_published_product_count=active_published,
        source_identity_products=identities,
    )
    source_bytes = (
        json.dumps(source.as_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode()
    return DatasetManifestV1.build(
        records,
        source_manifest=source,
        source_manifest_bytes=source_bytes,
        excluded_product_status_counts=tuple((status, 0) for status in PRODUCT_STATUSES),
        excluded_variant_count=0,
        excluded_source_identity_product_count=0,
        excluded_active_online_store_published_product_count=0,
    )


def _build(
    destination: Path,
    records: tuple[CatalogProductRecordV1, ...],
    *,
    manifest: DatasetManifestV1 | None = None,
) -> CatalogProjection:
    return build_catalog_projection(
        destination,
        manifest=manifest or _manifest(records),
        records=records,
    )


def _paginator(projection: CatalogProjection, *, secret: bytes = HMAC_KEY) -> CatalogPaginator:
    return CatalogPaginator(
        AtomicCatalogActivation(projection),
        CursorCodecV1(secret, ttl_seconds=1800),
        clock=lambda: NOW,
    )


def _traverse(paginator: CatalogPaginator, request: CatalogRequestV1) -> list[str]:
    cursor = None
    returned: list[str] = []
    while True:
        result = paginator.fetch_page(request, cursor=cursor)
        returned.extend(item.product_gid for item in result.page.items)
        cursor = result.next_cursor
        if cursor is None:
            return returned


def _token_for_raw(raw: bytes, secret: bytes = HMAC_KEY) -> str:
    encoded = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    signature = hmac.new(secret, raw, hashlib.sha256).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
    return f"{encoded}.{encoded_signature}"


def _empty_projection_schema(path: Path, schema: str) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(schema)
    connection.close()
    path.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)


@contextmanager
def _writable_projection(path: Path) -> Iterator[sqlite3.Connection]:
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    connection = sqlite3.connect(path)
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()
        path.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)


def test_projection_accounts_for_every_record_and_only_pages_public_products(
    tmp_path: Path,
) -> None:
    records = (
        _record("10", family=ProductFamily.SEALED),
        _record("2"),
        _record("3", status=ProductStatus.DRAFT),
        _record("4", published=False),
        _record("5", game=None, family=ProductFamily.UNCLASSIFIED),
        _record("6", game=Game.POKEMON),
        _record("7", family=ProductFamily.ACCESSORY),
    )
    projection = _projection(tmp_path, records)
    assert projection.dataset_generation == projection.manifest.dataset_generation
    assert projection.stats == pagination.ProjectionStats(7, 7, 4)
    assert _traverse(_paginator(projection), _request(page_size=1)) == [
        "gid://shopify/Product/2",
        "gid://shopify/Product/7",
        "gid://shopify/Product/10",
    ]
    assert _traverse(
        _paginator(projection),
        _request(page_size=1, family=RequestFamily.SEALED),
    ) == ["gid://shopify/Product/10"]
    assert _traverse(
        _paginator(projection),
        _request(page_size=1, game=Game.POKEMON),
    ) == ["gid://shopify/Product/6"]


def test_huge_decimal_gids_and_variant_fanout_use_canonical_text_order(
    tmp_path: Path,
) -> None:
    huge = "9" * 1000
    variants = tuple(_variant("2", value) for value in ("2", "10", "100", huge))
    records = (
        _record(huge, variants=(_variant(huge, f"8{huge}"),)),
        _record("10", variants=(_variant("10", "66666666666666666666"),)),
        _record("2", variants=variants),
    )
    result = _paginator(_projection(tmp_path, records)).fetch_page(_request())
    assert [item.product_gid.rsplit("/", 1)[1] for item in result.page.items] == [
        "2",
        "10",
        huge,
    ]
    assert [variant.variant_gid.rsplit("/", 1)[1] for variant in result.page.items[0].variants] == [
        "2",
        "10",
        "100",
        huge,
    ]
    assert result.page.returned_product_count == 3
    assert result.page.returned_variant_count == 6
    assert result.next_cursor is None


def test_empty_and_terminal_pages_have_no_cursor(tmp_path: Path) -> None:
    projection = _projection(tmp_path, (_record("1"),))
    paginator = _paginator(projection)
    empty = paginator.fetch_page(_request(game=Game.POKEMON))
    assert empty.page.items == ()
    assert empty.page.has_next_page is False
    assert empty.next_cursor is None

    terminal = paginator.fetch_page(_request(page_size=1))
    assert [item.product_gid for item in terminal.page.items] == ["gid://shopify/Product/1"]
    assert terminal.next_cursor is None

    after_end = CursorContextV1.from_request(
        _request(page_size=1),
        projection.dataset_generation,
        last_product_gid="gid://shopify/Product/999",
        expires_at="2026-09-02T12:30:00.000000Z",
    )
    signed_after_end = CursorCodecV1(HMAC_KEY).encode(after_end)
    empty_after_end = paginator.fetch_page(_request(page_size=1), cursor=signed_after_end)
    assert empty_after_end.page.items == ()
    assert empty_after_end.next_cursor is None


def test_page_size_plus_one_sentinel_is_not_loaded_as_a_returned_product(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projection = _projection(tmp_path, (_record("1"), _record("2")))
    original = CatalogProjection._variant_rows
    requested_variant_parents: list[tuple[str, ...]] = []

    def recording_variant_rows(
        connection: sqlite3.Connection,
        product_gids: tuple[str, ...],
        *,
        checkpoint: Callable[[], None] | None = None,
    ) -> dict[str, tuple[pagination.CatalogVariantItemV1, ...]]:
        requested_variant_parents.append(product_gids)
        return original(connection, product_gids, checkpoint=checkpoint)

    monkeypatch.setattr(
        CatalogProjection,
        "_variant_rows",
        staticmethod(recording_variant_rows),
    )
    first = _paginator(projection).fetch_page(_request(page_size=1))
    assert first.page.has_next_page is True
    assert [item.product_gid for item in first.page.items] == ["gid://shopify/Product/1"]
    assert requested_variant_parents == [("gid://shopify/Product/1",)]


def test_optional_checkpoint_propagates_cancellation_without_returning_a_page(
    tmp_path: Path,
) -> None:
    projection = _projection(tmp_path, (_record("1"),))
    paginator = _paginator(projection)
    cancellation = RuntimeError("request cancelled")

    def checkpoint() -> None:
        raise cancellation

    with pytest.raises(RuntimeError, match="request cancelled") as captured:
        paginator.fetch_page(_request(), checkpoint=checkpoint)
    assert captured.value is cancellation

    context = CursorContextV1.from_request(
        _request(),
        projection.dataset_generation,
        last_product_gid=None,
        expires_at="2026-09-02T12:30:00.000000Z",
    )
    with pytest.raises(PaginationContractError, match="checkpoint"):
        projection.fetch_page(_request(), context, checkpoint=object())  # type: ignore[arg-type]
    with pytest.raises(PaginationContractError, match="checkpoint"):
        paginator.fetch_page(_request(), checkpoint=object())  # type: ignore[arg-type]


def test_paginator_runs_checkpoint_after_projection_and_cursor_encoding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projection = _projection(tmp_path, (_record("1"), _record("2")))
    request = _request(page_size=1)
    context = CursorContextV1.from_request(
        request,
        projection.dataset_generation,
        last_product_gid=None,
        expires_at="2026-09-02T12:30:00.000000Z",
    )
    page = projection.fetch_page(request, context)
    assert page.next_cursor_context is not None
    events: list[str] = []

    def fetch_page(*_args: object, **_kwargs: object) -> CatalogPageV1:
        events.append("fetch")
        return page

    def encode(*_args: object, **_kwargs: object) -> str:
        events.append("encode")
        return "next-cursor"

    monkeypatch.setattr(
        CatalogProjection,
        "fetch_page",
        fetch_page,
    )
    monkeypatch.setattr(CursorCodecV1, "encode", encode)

    def checkpoint() -> None:
        events.append("checkpoint")

    result = _paginator(projection).fetch_page(request, checkpoint=checkpoint)

    assert result.next_cursor == "next-cursor"
    assert events == [
        "checkpoint",
        "checkpoint",
        "fetch",
        "checkpoint",
        "encode",
        "checkpoint",
    ]


def test_variant_decode_loop_runs_value_free_checkpoint(tmp_path: Path) -> None:
    projection = _projection(tmp_path, (_record("1"),))
    cancellation = RuntimeError("request cancelled")
    calls = 0

    def checkpoint() -> None:
        nonlocal calls
        calls += 1
        raise cancellation

    with pagination._readonly_connection(projection.path) as connection:
        variants = CatalogProjection._variant_rows(
            connection,
            ("gid://shopify/Product/1",),
        )
        assert tuple(variants) == ("gid://shopify/Product/1",)
        with pytest.raises(RuntimeError, match="request cancelled") as captured:
            CatalogProjection._variant_rows(
                connection,
                ("gid://shopify/Product/1",),
                checkpoint=checkpoint,
            )
    assert captured.value is cancellation
    assert calls == 1

    with pagination._readonly_connection(projection.path) as connection:
        rows = CatalogProjection._variant_rows(
            connection,
            ("gid://shopify/Product/1",),
        )
    assert tuple(rows) == ("gid://shopify/Product/1",)
    assert len(rows["gid://shopify/Product/1"]) == 1


def test_sqlite_progress_checkpoint_preserves_exception_and_is_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projection = _projection(tmp_path, (_record("1"),))
    paginator = _paginator(projection)
    cancellation = RuntimeError("request cancelled")
    inside_sql = False
    progress_events: list[tuple[bool, int]] = []
    progress_results: list[int] = []

    class TrackingConnection(sqlite3.Connection):
        def set_progress_handler(self, progress_handler: Callable[[], int] | None, n: int) -> None:
            progress_events.append((progress_handler is not None, n))
            if progress_handler is not None:
                progress_results.append(progress_handler())
            super().set_progress_handler(progress_handler, n)

    original_connect = sqlite3.connect
    original_product_rows = CatalogProjection._product_rows

    def tracking_connect(*args: object, **kwargs: object) -> sqlite3.Connection:
        return original_connect(*args, **kwargs, factory=TrackingConnection)

    def long_product_rows(
        connection: sqlite3.Connection,
        *,
        request: CatalogRequestV1,
        after_digits: str | None,
        limit: int,
    ) -> list[sqlite3.Row]:
        nonlocal inside_sql
        inside_sql = True
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
            inside_sql = False
        return original_product_rows(
            connection,
            request=request,
            after_digits=after_digits,
            limit=limit,
        )

    def checkpoint() -> None:
        if inside_sql:
            raise cancellation

    monkeypatch.setattr(pagination.sqlite3, "connect", tracking_connect)
    monkeypatch.setattr(
        CatalogProjection,
        "_product_rows",
        staticmethod(long_product_rows),
    )

    with pytest.raises(RuntimeError, match="request cancelled") as captured:
        paginator.fetch_page(_request(), checkpoint=checkpoint)
    assert captured.value is cancellation
    assert progress_events == [
        (True, pagination._SQLITE_PROGRESS_VM_STEPS),
        (False, 0),
    ]
    assert progress_results == [0]


def test_sqlite_progress_checkpoint_returns_continue_on_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projection = _projection(tmp_path, (_record("1"),))
    progress_results: list[int] = []

    class TrackingConnection(sqlite3.Connection):
        def set_progress_handler(self, progress_handler: Callable[[], int] | None, n: int) -> None:
            if progress_handler is not None:
                progress_results.append(progress_handler())
            super().set_progress_handler(progress_handler, n)

    original_connect = sqlite3.connect

    def tracking_connect(*args: object, **kwargs: object) -> sqlite3.Connection:
        return original_connect(*args, **kwargs, factory=TrackingConnection)

    monkeypatch.setattr(pagination.sqlite3, "connect", tracking_connect)
    result = _paginator(projection).fetch_page(_request(), checkpoint=lambda: None)

    assert [item.product_gid for item in result.page.items] == ["gid://shopify/Product/1"]
    assert progress_results == [0]


def test_complete_traversal_over_30000_products_has_no_gap_or_duplicate(
    tmp_path: Path,
) -> None:
    records = tuple(_record(str(number)) for number in range(1, 30_006))
    projection = _projection(tmp_path, records)
    expected = [f"gid://shopify/Product/{number}" for number in range(1, 30_006)]

    by_hundred = _traverse(_paginator(projection), _request(page_size=100))

    assert by_hundred == expected
    assert len(set(by_hundred)) == len(expected)
    assert by_hundred[24_998:25_001] == [
        "gid://shopify/Product/24999",
        "gid://shopify/Product/25000",
        "gid://shopify/Product/25001",
    ]


def test_page_size_one_traversal_has_no_gap_or_duplicate(tmp_path: Path) -> None:
    records = tuple(_record(str(number)) for number in range(1, 302))
    returned = _traverse(_paginator(_projection(tmp_path, records)), _request(page_size=1))
    expected = [f"gid://shopify/Product/{number}" for number in range(1, 302)]
    assert returned == expected
    assert len(set(returned)) == len(expected)


def test_every_game_and_present_family_plus_all_is_isolated(tmp_path: Path) -> None:
    records: list[CatalogProductRecordV1] = []
    expected: dict[tuple[Game, RequestFamily], list[str]] = {}
    families = (
        (ProductFamily.SINGLE, RequestFamily.SINGLE),
        (ProductFamily.SEALED, RequestFamily.SEALED),
        (ProductFamily.ACCESSORY, RequestFamily.ACCESSORY),
    )
    number = 100
    for game in Game:
        all_for_game: list[str] = []
        for product_family, request_family in families:
            number += 1
            gid = f"gid://shopify/Product/{number}"
            records.append(_record(str(number), game=game, family=product_family))
            expected[(game, request_family)] = [gid]
            all_for_game.append(gid)
        expected[(game, RequestFamily.ALL)] = all_for_game
    projection = _projection(tmp_path, tuple(reversed(records)))
    paginator = _paginator(projection)
    for (game, family), gids in expected.items():
        assert (
            _traverse(
                paginator,
                _request(page_size=2, game=game, family=family),
            )
            == gids
        )


def test_sealed_growth_requires_restart_and_new_generation_is_complete(
    tmp_path: Path,
) -> None:
    old = _projection(
        tmp_path,
        (
            _record("100", family=ProductFamily.SEALED),
            _record("200", family=ProductFamily.SEALED),
        ),
        name="sealed-old.sqlite3",
    )
    grown = _projection(
        tmp_path,
        (
            _record("100", family=ProductFamily.SEALED),
            _record("150", family=ProductFamily.SEALED),
            _record("200", family=ProductFamily.SEALED),
        ),
        source_marker="b",
        name="sealed-grown.sqlite3",
    )
    activation = AtomicCatalogActivation(old)
    paginator = CatalogPaginator(activation, CursorCodecV1(HMAC_KEY), clock=lambda: NOW)
    request = _request(page_size=1, family=RequestFamily.SEALED)
    old_first = paginator.fetch_page(request)
    assert old_first.next_cursor is not None
    activation.activate(grown)
    with pytest.raises(StaleGenerationError):
        paginator.fetch_page(request, cursor=old_first.next_cursor)
    assert _traverse(paginator, request) == [
        "gid://shopify/Product/100",
        "gid://shopify/Product/150",
        "gid://shopify/Product/200",
    ]


def test_pagination_proof_does_not_promote_runtime_capabilities() -> None:
    assert DEFAULT_CAPABILITIES_V1.feature_state("cursorCodec") is CapabilityState.UNSUPPORTED
    assert DEFAULT_CAPABILITIES_V1.feature_state("catalogOutput") is CapabilityState.UNSUPPORTED


def test_cursor_signs_exact_context_bytes_and_is_url_safe() -> None:
    request = _request(page_size=24)
    context = CursorContextV1.from_request(
        request,
        GENERATION_A,
        last_product_gid="gid://shopify/Product/25000",
        expires_at="2026-09-02T12:30:00.000000Z",
    )
    codec = CursorCodecV1(HMAC_KEY)
    token = codec.encode(context)
    body_segment, signature_segment = token.split(".")
    raw = base64.urlsafe_b64decode(body_segment + "=" * (-len(body_segment) % 4))
    signature = base64.urlsafe_b64decode(signature_segment + "=" * (-len(signature_segment) % 4))
    assert raw == context.to_json_bytes()
    assert signature == hmac.new(HMAC_KEY, raw, hashlib.sha256).digest()
    assert re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", token)
    assert (
        codec.decode(
            token,
            expected_request=request,
            expected_generation=GENERATION_A,
            now=NOW,
        )
        == context
    )
    assert "secret" not in repr(codec).casefold()


def test_cursor_rejects_tampering_wrong_secret_and_unsigned_context() -> None:
    request = _request()
    context = CursorContextV1.from_request(
        request,
        GENERATION_A,
        last_product_gid="gid://shopify/Product/2",
        expires_at="2026-09-02T12:30:00.000000Z",
    )
    codec = CursorCodecV1(HMAC_KEY)
    token = codec.encode(context)
    body, signature = token.split(".")
    tampered_body = ("A" if body[0] != "A" else "B") + body[1:]
    tampered_signature = ("A" if signature[0] != "A" else "B") + signature[1:]
    invalid_tokens = (
        context.to_json_bytes().decode(),
        body,
        f"{tampered_body}.{signature}",
        f"{body}.{tampered_signature}",
    )
    for invalid in invalid_tokens:
        with pytest.raises(InvalidCursorError, match="cursor token is invalid"):
            codec.decode(invalid, expected_request=request, now=NOW)
    with pytest.raises(InvalidCursorError):
        CursorCodecV1(b"z" * 32).decode(token, expected_request=request, now=NOW)


def test_cursor_rejects_wrong_version_context_generation_and_expiry() -> None:
    request = _request(page_size=24)
    other_request = _request(page_size=25)
    context = CursorContextV1.from_request(
        request,
        GENERATION_A,
        last_product_gid="gid://shopify/Product/2",
        expires_at="2026-09-02T12:30:00.000000Z",
    )
    codec = CursorCodecV1(HMAC_KEY)
    token = codec.encode(context)
    with pytest.raises(CursorContextMismatchError):
        codec.decode(token, expected_request=other_request, now=NOW)
    with pytest.raises(CursorContextMismatchError):
        codec.decode(token, expected_request=_request(page_size=24, query=""), now=NOW)
    with pytest.raises(StaleGenerationError):
        codec.decode(
            token,
            expected_request=request,
            expected_generation=GENERATION_B,
            now=NOW,
        )
    with pytest.raises(CursorExpiredError):
        codec.decode(token, expected_request=request, now=NOW + timedelta(minutes=30))

    payload = context.as_dict()
    payload["cursorVersion"] = 2
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    with pytest.raises(InvalidCursorError):
        codec.decode(_token_for_raw(raw), expected_request=request, now=NOW)


def test_cursor_codec_authenticates_search_and_filter_request_contexts() -> None:
    codec = CursorCodecV1(HMAC_KEY)
    requests = (
        _request(family=RequestFamily.SINGLE, query="Black Lotus"),
        _request(family=RequestFamily.SEALED, in_stock=True),
    )
    for request in requests:
        context = CursorContextV1.from_request(
            request,
            GENERATION_A,
            last_product_gid="gid://shopify/Product/2",
            expires_at="2026-09-02T12:30:00.000000Z",
        )
        token = codec.encode(context)

        assert (
            codec.decode(
                token,
                expected_request=request,
                expected_generation=GENERATION_A,
                now=NOW,
            )
            == context
        )


def test_generation_activation_makes_old_cursor_deterministically_stale(
    tmp_path: Path,
) -> None:
    first = _projection(tmp_path, (_record("1"), _record("2")), name="first.sqlite3")
    second = _projection(
        tmp_path,
        (_record("10"), _record("20")),
        source_marker="b",
        name="second.sqlite3",
    )
    activation = AtomicCatalogActivation(first)
    paginator = CatalogPaginator(activation, CursorCodecV1(HMAC_KEY), clock=lambda: NOW)
    first_page = paginator.fetch_page(_request(page_size=1))
    assert first_page.next_cursor is not None
    activation.activate(second)
    assert activation.active_generation == second.dataset_generation
    with pytest.raises(StaleGenerationError, match="stale"):
        paginator.fetch_page(_request(page_size=1), cursor=first_page.next_cursor)
    stale_and_expired = CatalogPaginator(
        activation,
        CursorCodecV1(HMAC_KEY),
        clock=lambda: NOW + timedelta(minutes=31),
    )
    with pytest.raises(StaleGenerationError, match="stale"):
        stale_and_expired.fetch_page(_request(page_size=1), cursor=first_page.next_cursor)
    assert [
        item.product_gid for item in paginator.fetch_page(_request(page_size=1)).page.items
    ] == ["gid://shopify/Product/10"]


def test_cursor_request_pins_one_projection_before_activation_race(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _projection(tmp_path, (_record("1"), _record("2")), name="race-old.sqlite3")
    second = _projection(
        tmp_path,
        (_record("10"), _record("20")),
        source_marker="b",
        name="race-new.sqlite3",
    )
    activation = AtomicCatalogActivation(first)
    codec = CursorCodecV1(HMAC_KEY)
    paginator = CatalogPaginator(activation, codec, clock=lambda: NOW)
    request = _request(page_size=1)
    first_page = paginator.fetch_page(request)
    assert first_page.next_cursor is not None
    original_decode = CursorCodecV1.decode

    def activate_during_decode(
        self: CursorCodecV1,
        token: str,
        *,
        expected_request: CatalogRequestV1,
        now: datetime,
        expected_generation: str | None = None,
    ) -> CursorContextV1:
        activation.activate(second)
        return original_decode(
            self,
            token,
            expected_request=expected_request,
            expected_generation=expected_generation,
            now=now,
        )

    monkeypatch.setattr(CursorCodecV1, "decode", activate_during_decode)
    result = paginator.fetch_page(request, cursor=first_page.next_cursor)
    assert result.page.dataset_generation == first.dataset_generation
    assert [item.product_gid for item in result.page.items] == ["gid://shopify/Product/2"]
    assert activation.active_generation == second.dataset_generation


def test_concurrent_activation_never_mixes_generation_and_rows(tmp_path: Path) -> None:
    first = _projection(
        tmp_path,
        (_record("1"), _record("2")),
        name="concurrent-a.sqlite3",
    )
    second = _projection(
        tmp_path,
        (_record("100"), _record("200")),
        source_marker="b",
        name="concurrent-b.sqlite3",
    )
    activation = AtomicCatalogActivation(first)
    paginator = CatalogPaginator(activation, CursorCodecV1(HMAC_KEY), clock=lambda: NOW)
    barrier = threading.Barrier(3)
    results: list[tuple[str, tuple[str, ...]]] = []

    def reader() -> None:
        barrier.wait()
        result = paginator.fetch_page(_request())
        results.append(
            (
                result.page.dataset_generation,
                tuple(item.product_gid for item in result.page.items),
            )
        )

    def activator() -> None:
        barrier.wait()
        activation.activate(second)

    readers = [threading.Thread(target=reader) for _ in range(2)]
    writer = threading.Thread(target=activator)
    for thread in (*readers, writer):
        thread.start()
    for thread in (*readers, writer):
        thread.join()

    allowed = {
        (first.dataset_generation, ("gid://shopify/Product/1", "gid://shopify/Product/2")),
        (second.dataset_generation, ("gid://shopify/Product/100", "gid://shopify/Product/200")),
    }
    assert len(results) == 2
    assert set(results) <= allowed
    assert activation.active_generation == second.dataset_generation


def test_sql_is_keyset_only_and_all_data_values_are_bound() -> None:
    sql_values = (
        pagination._FIRST_PAGE_ALL_SQL,
        pagination._NEXT_PAGE_ALL_SQL,
        pagination._FIRST_PAGE_FAMILY_SQL,
        pagination._NEXT_PAGE_FAMILY_SQL,
    )
    combined = "\n".join(sql_values).upper()
    assert "OFFSET" not in combined
    assert "CAST(" not in combined
    assert "(PRODUCT_GID_LENGTH, PRODUCT_GID_DIGITS) > (?, ?)" in combined
    assert all("?" in sql for sql in sql_values)


def test_request_scope_rejects_non_single_search_and_forged_types(
    tmp_path: Path,
) -> None:
    projection = _projection(tmp_path, (_record("1"),))
    paginator = _paginator(projection)
    with pytest.raises(UnsupportedPaginationRequestError, match="search"):
        paginator.fetch_page(_request(query="bolt"))
    assert paginator.fetch_page(_request(in_stock=True)).page.returned_product_count == 1
    with pytest.raises(PaginationContractError, match="CatalogRequestV1"):
        paginator.fetch_page(object())  # type: ignore[arg-type]

    forged_request = _request()
    object.__setattr__(forged_request, "page_size", 0)
    with pytest.raises(PaginationContractError, match="canonical CatalogRequestV1"):
        paginator.fetch_page(forged_request)


def test_supplied_context_and_product_records_are_canonically_reconstructed(
    tmp_path: Path,
) -> None:
    record = _record("1")
    forged_record = _record("2")
    object.__setattr__(forged_record, "handle", "")
    with pytest.raises(PaginationContractError, match="canonical CatalogProductRecordV1"):
        build_catalog_projection(
            tmp_path / "forged-record.sqlite3",
            manifest=_manifest((record,)),
            records=(record, forged_record),
        )

    projection = _projection(tmp_path, (record,), name="canonical.sqlite3")
    request = _request()
    context = CursorContextV1.from_request(
        request,
        projection.dataset_generation,
        last_product_gid=None,
        expires_at="2026-09-02T12:30:00.000000Z",
    )
    forged_context = replace(context)
    object.__setattr__(forged_context, "last_sort_values", ("forged",))
    with pytest.raises(PaginationContractError, match="canonical CursorContextV1"):
        projection.fetch_page(request, forged_context)
    with pytest.raises(PaginationContractError, match="canonical CursorContextV1"):
        CursorCodecV1(HMAC_KEY).encode(forged_context)


def test_manifest_is_canonical_persisted_and_bound_to_deep_canonical_records(
    tmp_path: Path,
) -> None:
    record = _record("1")
    records = (record,)
    manifest = _manifest(records)
    projection = _build(tmp_path / "manifest-bound.sqlite3", records, manifest=manifest)

    assert projection.manifest == manifest
    assert projection.manifest is not manifest
    assert projection.dataset_generation == manifest.dataset_generation
    with pagination._readonly_connection(projection.path) as connection:
        persisted = connection.execute(
            "SELECT dataset_manifest_json FROM projection_metadata WHERE singleton = ?", (1,)
        ).fetchone()[0]
    assert persisted == manifest.to_json_bytes()

    altered = replace(record, commercial_title="Different canonical content")
    mismatch_path = tmp_path / "manifest-mismatch.sqlite3"
    with pytest.raises(PaginationContractError, match="manifest does not match"):
        _build(mismatch_path, (altered,), manifest=manifest)
    assert not mismatch_path.exists()

    with _writable_projection(projection.path) as connection:
        connection.execute(
            "UPDATE products SET commercial_title = ?, product_record_json = ?",
            (altered.commercial_title, altered.to_json_bytes()),
        )
    with pytest.raises(DatasetUnavailableError):
        CatalogProjection.open(projection.path)

    noncanonical = _projection(tmp_path, (_record("2"),), name="noncanonical-manifest.sqlite3")
    pretty_manifest = json.dumps(noncanonical.manifest.as_dict(), indent=2, sort_keys=True).encode()
    with _writable_projection(noncanonical.path) as connection:
        connection.execute(
            "UPDATE projection_metadata SET dataset_manifest_json = ? WHERE singleton = ?",
            (pretty_manifest, 1),
        )
    with pytest.raises(DatasetUnavailableError):
        CatalogProjection.open(noncanonical.path)

    oversized = _projection(tmp_path, (_record("3"),), name="oversized-manifest.sqlite3")
    with _writable_projection(oversized.path) as connection:
        connection.execute(
            "UPDATE projection_metadata SET dataset_manifest_json = ? WHERE singleton = ?",
            (b"x" * (MAX_CONTRACT_BYTES + 1), 1),
        )
    with pytest.raises(DatasetUnavailableError):
        CatalogProjection.open(oversized.path)


def test_hostile_nested_record_and_manifest_fail_with_stable_bounded_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class HostileTuple(tuple[object, ...]):
        def __iter__(self) -> Iterator[object]:
            raise RuntimeError("attacker-controlled nested iterator")

    record = _record("1")
    manifest = _manifest((record,))
    hostile_record = replace(record)
    object.__setattr__(hostile_record, "variants", HostileTuple(record.variants))
    with pytest.raises(PaginationContractError) as record_error:
        _build(
            tmp_path / "hostile-record.sqlite3",
            (hostile_record,),
            manifest=manifest,
        )
    assert str(record_error.value) == (
        "projection records must be canonical CatalogProductRecordV1"
    )

    hostile_manifest = replace(manifest)
    object.__setattr__(
        hostile_manifest,
        "product_family_counts",
        HostileTuple(manifest.product_family_counts),
    )
    with pytest.raises(PaginationContractError) as manifest_error:
        _build(
            tmp_path / "hostile-manifest.sqlite3",
            (record,),
            manifest=hostile_manifest,
        )
    assert str(manifest_error.value) == ("dataset manifest must be canonical DatasetManifestV1")

    monkeypatch.setattr(pagination, "MAX_CONTRACT_BYTES", len(manifest.to_json_bytes()) - 1)
    with pytest.raises(PaginationContractError, match="manifest exceeds"):
        _build(tmp_path / "oversized-manifest.sqlite3", (record,), manifest=manifest)


def test_projection_is_never_overwritten_and_opens_read_only(tmp_path: Path) -> None:
    path = tmp_path / "immutable.sqlite3"
    projection = _projection(tmp_path, (_record("1"),), name=path.name)
    original = path.read_bytes()
    with pytest.raises(ProjectionBuildError, match="already exists"):
        build_catalog_projection(
            path,
            manifest=_manifest((_record("2"),), source_marker="b"),
            records=(_record("2"),),
        )
    assert path.read_bytes() == original
    with pagination._readonly_connection(projection.path) as connection:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("DELETE FROM products")


def test_activated_projection_pins_content_identity_and_fails_closed_after_changes(
    tmp_path: Path,
) -> None:
    records = (_record("1"), _record("2"))
    projection = _projection(tmp_path, records, name="activated.sqlite3")
    paginator = _paginator(projection)
    first = paginator.fetch_page(_request(page_size=1))
    assert first.next_cursor is not None
    assert projection.path.stat().st_mode & stat.S_IWUSR == 0
    assert (
        projection._file_fingerprint.content_sha256
        == hashlib.sha256(projection.path.read_bytes()).hexdigest()
    )

    altered = replace(records[1], commercial_title="Valid altered row")
    with _writable_projection(projection.path) as connection:
        connection.execute(
            "UPDATE products SET commercial_title = ?, product_record_json = ? "
            "WHERE product_gid = ?",
            (altered.commercial_title, altered.to_json_bytes(), altered.product_gid),
        )
    with pytest.raises(DatasetUnavailableError):
        paginator.fetch_page(_request(page_size=1), cursor=first.next_cursor)

    replacement_source = _projection(
        tmp_path,
        (_record("10"), _record("20")),
        name="replacement-source.sqlite3",
    )
    replacement_paginator = _paginator(replacement_source)
    replacement_first = replacement_paginator.fetch_page(_request(page_size=1))
    assert replacement_first.next_cursor is not None
    copied = tmp_path / "byte-identical-copy.sqlite3"
    shutil.copy2(replacement_source.path, copied)
    copied.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    replacement_source.path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    os.replace(copied, replacement_source.path)
    with pytest.raises(DatasetUnavailableError):
        replacement_paginator.fetch_page(
            _request(page_size=1), cursor=replacement_first.next_cursor
        )


def test_post_query_file_guard_failure_is_propagated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projection = _projection(tmp_path, (_record("1"),))
    request = _request()
    context = CursorContextV1.from_request(
        request,
        projection.dataset_generation,
        last_product_gid=None,
        expires_at="2026-09-02T12:30:00.000000Z",
    )
    checks = 0

    def fail_second_check(_self: CatalogProjection) -> None:
        nonlocal checks
        checks += 1
        if checks == 2:
            raise DatasetUnavailableError("catalog dataset is unavailable")

    monkeypatch.setattr(CatalogProjection, "_assert_file_unchanged", fail_second_check)
    with pytest.raises(DatasetUnavailableError):
        projection.fetch_page(request, context)
    assert checks == 2


def test_projection_file_fingerprint_failures_are_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projection = _projection(tmp_path, (_record("1"),), name="fingerprint.sqlite3")

    projection.path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    with pytest.raises(DatasetUnavailableError):
        pagination._projection_file_state(projection.path, include_content_hash=False)
    projection.path.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)

    with monkeypatch.context() as nested:
        nested.setattr(pagination, "MAX_PROJECTION_FILE_BYTES", projection.path.stat().st_size - 1)
        with pytest.raises(DatasetUnavailableError):
            pagination._projection_file_state(projection.path, include_content_hash=False)

    invalid_header = tmp_path / "invalid-header.sqlite3"
    invalid_header.write_bytes(b"x" * pagination.SQLITE_HEADER_BYTES)
    invalid_header.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    with pytest.raises(DatasetUnavailableError):
        pagination._projection_file_state(invalid_header, include_content_hash=False)

    with monkeypatch.context() as nested:
        nested.setattr(Path, "is_symlink", lambda _path: True)
        with pytest.raises(DatasetUnavailableError):
            pagination._projection_file_state(projection.path, include_content_hash=False)

    with monkeypatch.context() as nested:
        nested.setattr(
            Path,
            "is_symlink",
            lambda _path: (_ for _ in ()).throw(RuntimeError("attacker-controlled path error")),
        )
        with pytest.raises(DatasetUnavailableError) as error:
            pagination._projection_file_state(projection.path, include_content_hash=False)
        assert str(error.value) == "catalog dataset is unavailable"

    real_signature = pagination._stat_signature
    signatures = iter(((1,), (2,)))
    with monkeypatch.context() as nested:
        nested.setattr(pagination, "_stat_signature", lambda _value: next(signatures))
        with pytest.raises(DatasetUnavailableError):
            pagination._projection_file_state(projection.path, include_content_hash=False)
    assert pagination._stat_signature is real_signature

    with monkeypatch.context() as nested:
        nested.setattr(
            pagination,
            "_projection_file_state",
            lambda _path, *, include_content_hash: (
                projection._file_fingerprint.stamp,
                None,
            ),
        )
        with pytest.raises(DatasetUnavailableError):
            pagination._projection_file_fingerprint(projection.path)

    real_fingerprint = pagination._projection_file_fingerprint
    fingerprint_calls = 0

    def changed_between_activation_checks(path: Path) -> object:
        nonlocal fingerprint_calls
        fingerprint_calls += 1
        fingerprint = real_fingerprint(path)
        if fingerprint_calls == 2:
            return replace(fingerprint, content_sha256="0" * 64)
        return fingerprint

    with monkeypatch.context() as nested:
        nested.setattr(
            pagination, "_projection_file_fingerprint", changed_between_activation_checks
        )
        with pytest.raises(DatasetUnavailableError):
            CatalogProjection.open(projection.path)
    assert fingerprint_calls == 2


def test_basic_constructor_and_activation_bounds(tmp_path: Path) -> None:
    with pytest.raises(PaginationContractError, match="secret"):
        CursorCodecV1(b"short")
    with pytest.raises(PaginationContractError, match="secret"):
        CursorCodecV1(b"x" * 4097)
    with pytest.raises(PaginationContractError, match="TTL"):
        CursorCodecV1(HMAC_KEY, ttl_seconds=0)
    with pytest.raises(PaginationContractError, match="TTL"):
        CursorCodecV1(HMAC_KEY, ttl_seconds=True)  # type: ignore[arg-type]
    with pytest.raises(PaginationContractError, match="DatasetManifestV1"):
        build_catalog_projection(
            tmp_path / "bad.sqlite3",
            manifest=object(),  # type: ignore[arg-type]
            records=(_record("1"),),
        )
    with pytest.raises(PaginationContractError, match="destination"):
        build_catalog_projection(  # type: ignore[arg-type]
            "bad.sqlite3", manifest=_manifest((_record("1"),)), records=(_record("1"),)
        )
    with pytest.raises(PaginationContractError, match="records"):
        build_catalog_projection(
            tmp_path / "empty.sqlite3", manifest=_manifest((_record("1"),)), records=()
        )
    with pytest.raises(DatasetUnavailableError):
        CatalogProjection.open("not-a-path")  # type: ignore[arg-type]
    with pytest.raises(PaginationContractError):
        pagination._gid_digits(1, pagination._PRODUCT_GID_RE, "Product GID")
    with pytest.raises(PaginationContractError):
        pagination._gid_digits("bad", pagination._PRODUCT_GID_RE, "Product GID")
    with pytest.raises(DatasetUnavailableError):
        pagination._normalized_schema_sql(object())

    activation = AtomicCatalogActivation()
    assert activation.active_generation is None
    with pytest.raises(DatasetUnavailableError):
        activation.select()
    with pytest.raises(PaginationContractError, match="CatalogProjection"):
        activation.activate(object())  # type: ignore[arg-type]
    with pytest.raises(PaginationContractError, match="generation"):
        activation.select("bad")
    active = _projection(tmp_path, (_record("2"),), name="active-bounds.sqlite3")
    activation.activate(active)
    with pytest.raises(StaleGenerationError):
        activation.select(GENERATION_B)


def test_paginator_and_authenticated_page_constructor_guards(tmp_path: Path) -> None:
    projection = _projection(tmp_path, (_record("1"), _record("2")))
    activation = AtomicCatalogActivation(projection)
    codec = CursorCodecV1(HMAC_KEY)
    with pytest.raises(PaginationContractError, match="activation"):
        CatalogPaginator(object(), codec)  # type: ignore[arg-type]
    with pytest.raises(PaginationContractError, match="codec"):
        CatalogPaginator(activation, object())  # type: ignore[arg-type]
    with pytest.raises(PaginationContractError, match="clock"):
        CatalogPaginator(activation, codec, clock=1)  # type: ignore[arg-type]
    with pytest.raises(PaginationContractError, match="UTC"):
        CatalogPaginator(activation, codec, clock=lambda: datetime(2026, 9, 2)).fetch_page(
            _request()
        )
    with pytest.raises(PaginationContractError, match="clock failed"):
        CatalogPaginator(
            activation,
            codec,
            clock=lambda: (_ for _ in ()).throw(OverflowError("synthetic")),
        ).fetch_page(_request())
    with pytest.raises(PaginationContractError, match="timestamp range"):
        codec.expires_at(datetime.max.replace(tzinfo=UTC))

    result = _paginator(projection).fetch_page(_request(page_size=1))
    with pytest.raises(PaginationContractError, match="CatalogPageV1"):
        AuthenticatedCatalogPage(object(), None)  # type: ignore[arg-type]
    with pytest.raises(PaginationContractError, match="next cursor"):
        AuthenticatedCatalogPage(result.page, "")
    with pytest.raises(PaginationContractError, match="presence"):
        AuthenticatedCatalogPage(result.page, None)


def test_cursor_malformed_and_noncanonical_encodings_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request()
    codec = CursorCodecV1(HMAC_KEY)
    malformed: tuple[object, ...] = (
        b"bytes",
        "",
        "a",
        ".a",
        "a.",
        "a.b.c",
        "====.AAAA",
        "A.AAAA",
        "AB.AAAA",
        "x" * (pagination.MAX_CURSOR_TOKEN_CHARS + 1),
    )
    for token in malformed:
        with pytest.raises(InvalidCursorError):
            codec.decode(token, expected_request=request, now=NOW)  # type: ignore[arg-type]

    original_decode = base64.b64decode

    def broken_decode(*_args: object, **_kwargs: object) -> bytes:
        raise binascii.Error("synthetic")

    import binascii

    monkeypatch.setattr(base64, "b64decode", broken_decode)
    with pytest.raises(InvalidCursorError):
        codec.decode("AA.AA", expected_request=request, now=NOW)
    monkeypatch.setattr(base64, "b64decode", original_decode)

    noncanonical_body = "AB"
    with pytest.raises(InvalidCursorError):
        codec.decode(f"{noncanonical_body}.{'A' * 43}", expected_request=request, now=NOW)


def test_cursor_rejects_invalid_signed_payloads_and_strict_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request()
    codec = CursorCodecV1(HMAC_KEY)
    invalid_raw_values = (
        b"not-json",
        b'{"cursorVersion":1}',
    )
    for raw in invalid_raw_values:
        with pytest.raises(InvalidCursorError):
            codec.decode(_token_for_raw(raw), expected_request=request, now=NOW)

    oversized = b"x" * (MAX_CONTRACT_BYTES + 1)
    with pytest.raises(InvalidCursorError):
        codec.decode(_token_for_raw(oversized), expected_request=request, now=NOW)

    context = CursorContextV1.from_request(
        request,
        GENERATION_A,
        last_product_gid=None,
        expires_at="2026-09-02T12:30:00.000000Z",
    )
    raw = context.to_json_bytes()
    pretty_raw = json.dumps(context.as_dict(), indent=2, sort_keys=True).encode()
    with pytest.raises(InvalidCursorError):
        codec.decode(_token_for_raw(pretty_raw), expected_request=request, now=NOW)
    body = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    short_signature = base64.urlsafe_b64encode(b"short").rstrip(b"=").decode()
    with pytest.raises(InvalidCursorError):
        codec.decode(f"{body}.{short_signature}", expected_request=request, now=NOW)
    with pytest.raises(PaginationContractError, match="generation"):
        codec.decode(
            codec.encode(context),
            expected_request=request,
            expected_generation="bad",
            now=NOW,
        )
    with pytest.raises(PaginationContractError, match="context"):
        codec.encode(object())  # type: ignore[arg-type]
    with pytest.raises(PaginationContractError, match="CatalogRequestV1"):
        codec.decode(
            codec.encode(context),
            expected_request=object(),  # type: ignore[arg-type]
            now=NOW,
        )

    monkeypatch.setattr(pagination, "MAX_CONTRACT_BYTES", len(raw) - 1)
    with pytest.raises(PaginationContractError, match="byte limit"):
        codec.encode(context)


def test_projection_build_rejects_identity_and_resource_bound_violations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(PaginationContractError, match="CatalogProductRecordV1"):
        build_catalog_projection(
            tmp_path / "wrong-record.sqlite3",
            manifest=_manifest((_record("9"),)),
            records=(object(),),  # type: ignore[arg-type]
        )
    with pytest.raises(ProjectionBuildError, match="Product identity"):
        build_catalog_projection(
            tmp_path / "duplicate-product.sqlite3",
            manifest=_manifest((_record("9"),)),
            records=(_record("1"), _record("1")),
        )
    with pytest.raises(ProjectionBuildError, match="Product identity"):
        build_catalog_projection(
            tmp_path / "duplicate-handle.sqlite3",
            manifest=_manifest((_record("9"),)),
            records=(_record("1", handle="same"), _record("2", handle="same")),
        )
    duplicate_variant = (
        _record("1", variants=(_variant("1", "50", inventory_item="51"),)),
        _record("2", variants=(_variant("2", "50", inventory_item="52"),)),
    )
    with pytest.raises(ProjectionBuildError, match="Variant"):
        build_catalog_projection(
            tmp_path / "duplicate-variant.sqlite3",
            manifest=_manifest((_record("9"),)),
            records=duplicate_variant,
        )
    duplicate_inventory = (
        _record("1", variants=(_variant("1", "51", inventory_item="60"),)),
        _record("2", variants=(_variant("2", "52", inventory_item="60"),)),
    )
    with pytest.raises(ProjectionBuildError, match="inventory-item"):
        build_catalog_projection(
            tmp_path / "duplicate-inventory.sqlite3",
            manifest=_manifest((_record("9"),)),
            records=duplicate_inventory,
        )

    monkeypatch.setattr(pagination, "MAX_PROJECTION_PRODUCTS", 1)
    with pytest.raises(PaginationContractError, match="outside bounds"):
        build_catalog_projection(
            tmp_path / "too-many-products.sqlite3",
            manifest=_manifest((_record("9"),)),
            records=(_record("1"), _record("2")),
        )
    monkeypatch.setattr(pagination, "MAX_PROJECTION_PRODUCTS", 1_000_000)
    monkeypatch.setattr(pagination, "MAX_VARIANTS_PER_PRODUCT", 1)
    two_variants = (_variant("1", "1"), _variant("1", "2"))
    two_variant_record = _record("1", variants=two_variants)
    with pytest.raises(PaginationContractError, match="fanout"):
        build_catalog_projection(
            tmp_path / "fanout.sqlite3",
            manifest=_manifest((two_variant_record,)),
            records=(two_variant_record,),
        )
    monkeypatch.setattr(pagination, "MAX_VARIANTS_PER_PRODUCT", 10_000)
    monkeypatch.setattr(pagination, "MAX_PROJECTION_VARIANTS", 1)
    with pytest.raises(PaginationContractError, match="Variant count"):
        build_catalog_projection(
            tmp_path / "variant-count.sqlite3",
            manifest=_manifest((two_variant_record,)),
            records=(two_variant_record,),
        )

    monkeypatch.setattr(pagination, "MAX_PROJECTION_VARIANTS", 10_000_000)
    record = replace(_record("3"), commercial_title="x" * 10_000)
    manifest = _manifest((record,))
    monkeypatch.setattr(pagination, "MAX_CONTRACT_BYTES", len(record.to_json_bytes()) - 1)
    with pytest.raises(PaginationContractError, match="Product record"):
        build_catalog_projection(
            tmp_path / "oversized-record.sqlite3",
            manifest=manifest,
            records=(record,),
        )


def test_projection_open_and_atomic_install_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(DatasetUnavailableError):
        CatalogProjection.open(tmp_path / "missing.sqlite3")
    malformed = tmp_path / "malformed.sqlite3"
    malformed.write_bytes(b"not sqlite")
    with pytest.raises(DatasetUnavailableError):
        CatalogProjection.open(malformed)

    projection = _projection(tmp_path, (_record("1"),), name="valid.sqlite3")
    with pytest.raises(StaleGenerationError):
        CatalogProjection.open(projection.path, expected_generation=GENERATION_B)

    with _writable_projection(projection.path) as connection:
        connection.execute("PRAGMA application_id = 0")
    with pytest.raises(DatasetUnavailableError):
        CatalogProjection.open(projection.path)

    original_link = os.link

    def failed_link(_source: object, _destination: object) -> None:
        raise OSError("synthetic")

    monkeypatch.setattr(os, "link", failed_link)
    failed_path = tmp_path / "failed-link.sqlite3"
    with pytest.raises(ProjectionBuildError, match="build failed"):
        _build(failed_path, (_record("2"),))
    assert not failed_path.exists()
    assert not list(tmp_path.glob(".nla-catalog-*.tmp"))
    monkeypatch.setattr(os, "link", original_link)

    def failed_mkstemp(*_args: object, **_kwargs: object) -> tuple[int, str]:
        raise OSError("synthetic")

    monkeypatch.setattr(pagination.tempfile, "mkstemp", failed_mkstemp)
    with pytest.raises(ProjectionBuildError, match="build failed"):
        _build(tmp_path / "failed-temp.sqlite3", (_record("3"),))


def test_projection_build_normalizes_destination_and_integrity_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_mkdir = Path.mkdir

    def failed_mkdir(*_args: object, **_kwargs: object) -> None:
        raise OSError("synthetic")

    monkeypatch.setattr(Path, "mkdir", failed_mkdir)
    with pytest.raises(ProjectionBuildError, match="destination"):
        _build(tmp_path / "unavailable" / "catalog.sqlite3", (_record("1"),))
    monkeypatch.setattr(Path, "mkdir", original_mkdir)

    real_connect = sqlite3.connect

    class BadCheck:
        def fetchone(self) -> tuple[str]:
            return ("bad",)

    class ConnectionWithBadCheck:
        def __init__(self, path: object) -> None:
            self._connection = real_connect(path)

        def __getattr__(self, name: str) -> object:
            return getattr(self._connection, name)

        def execute(self, sql: str, *args: object) -> object:
            if sql == "PRAGMA quick_check":
                return BadCheck()
            return self._connection.execute(sql, *args)

    monkeypatch.setattr(
        pagination.sqlite3,
        "connect",
        lambda path: ConnectionWithBadCheck(path),
    )
    with pytest.raises(ProjectionBuildError, match="integrity"):
        _build(tmp_path / "bad-check.sqlite3", (_record("2"),))
    monkeypatch.setattr(pagination.sqlite3, "connect", real_connect)

    original_unlink = Path.unlink

    def fail_temporary_unlink(path: Path, *args: object, **kwargs: object) -> None:
        if path.name.startswith(".nla-catalog-"):
            raise OSError("synthetic")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_temporary_unlink)
    cleanup_destination = tmp_path / "cleanup-failure.sqlite3"
    with pytest.raises(ProjectionBuildError, match="cleanup failed"):
        _build(cleanup_destination, (_record("3"),))
    assert not cleanup_destination.exists()
    monkeypatch.setattr(Path, "unlink", original_unlink)
    for temporary in tmp_path.glob(".nla-catalog-*.tmp"):
        temporary.unlink()

    def fail_every_unlink(_path: Path, *_args: object, **_kwargs: object) -> None:
        raise OSError("synthetic")

    monkeypatch.setattr(Path, "unlink", fail_every_unlink)
    rollback_destination = tmp_path / "rollback-failure.sqlite3"
    with pytest.raises(ProjectionBuildError, match="rollback failed"):
        _build(rollback_destination, (_record("4"),))
    monkeypatch.setattr(Path, "unlink", original_unlink)
    rollback_destination.unlink()
    for temporary in tmp_path.glob(".nla-catalog-*.tmp"):
        temporary.unlink()

    original_link = os.link

    def fail_link_and_temporary_unlink(path: Path, *args: object, **kwargs: object) -> None:
        if path.name.startswith(".nla-catalog-"):
            raise OSError("synthetic")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(os, "link", lambda *_args: (_ for _ in ()).throw(OSError("synthetic")))
    monkeypatch.setattr(Path, "unlink", fail_link_and_temporary_unlink)
    with pytest.raises(ProjectionBuildError, match="cleanup failed"):
        _build(tmp_path / "link-and-cleanup-failure.sqlite3", (_record("5"),))
    monkeypatch.setattr(os, "link", original_link)
    monkeypatch.setattr(Path, "unlink", original_unlink)
    for temporary in tmp_path.glob(".nla-catalog-*.tmp"):
        temporary.unlink()

    def failed_open(
        _cls: type[CatalogProjection],
        _path: Path,
        *,
        expected_generation: str | None = None,
    ) -> CatalogProjection:
        del expected_generation
        raise DatasetUnavailableError("catalog dataset is unavailable")

    monkeypatch.setattr(CatalogProjection, "open", classmethod(failed_open))
    verification_destination = tmp_path / "verification-failure.sqlite3"
    with pytest.raises(ProjectionBuildError, match="verification failed"):
        _build(verification_destination, (_record("6"),))
    assert not verification_destination.exists()

    def fail_verification_rollback(path: Path, *args: object, **kwargs: object) -> None:
        if path.name == "verification-rollback.sqlite3":
            raise OSError("synthetic")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_verification_rollback)
    rollback_after_verification = tmp_path / "verification-rollback.sqlite3"
    with pytest.raises(ProjectionBuildError, match="verification and rollback"):
        _build(rollback_after_verification, (_record("7"),))
    monkeypatch.setattr(Path, "unlink", original_unlink)
    rollback_after_verification.unlink()


def test_corrupt_but_structurally_valid_projection_is_rejected_or_fails_closed(
    tmp_path: Path,
) -> None:
    projection = _projection(
        tmp_path,
        (_record("1"), _record("2")),
        name="corruptible.sqlite3",
    )
    with _writable_projection(projection.path) as connection:
        connection.execute(
            "UPDATE projection_metadata SET variant_count = ? WHERE singleton = ?", (99, 1)
        )
    with pytest.raises(DatasetUnavailableError):
        CatalogProjection.open(projection.path)

    sparse = _projection(
        tmp_path,
        (
            _record("10", variants=(_variant("10", "101"), _variant("10", "102"))),
            _record("20"),
        ),
        name="sparse.sqlite3",
    )
    with _writable_projection(sparse.path) as connection:
        connection.execute(
            "DELETE FROM variants WHERE product_gid = ?", ("gid://shopify/Product/20",)
        )
        connection.execute(
            "UPDATE projection_metadata SET variant_count = ? WHERE singleton = ?", (2, 1)
        )
    with pytest.raises(DatasetUnavailableError):
        CatalogProjection.open(sparse.path)
    with pagination._readonly_connection(sparse.path) as connection:
        with pytest.raises(DatasetUnavailableError):
            CatalogProjection._variant_rows(connection, ("gid://shopify/Product/20",))
    context = CursorContextV1.from_request(
        _request(),
        sparse.dataset_generation,
        last_product_gid=None,
        expires_at="2026-09-02T12:30:00.000000Z",
    )
    with pytest.raises(DatasetUnavailableError):
        sparse.fetch_page(_request(), context)


def test_activation_semantically_verifies_schema_gids_and_canonical_payloads(
    tmp_path: Path,
) -> None:
    good = _projection(tmp_path, (_record("1"),), name="good.sqlite3")
    activation = AtomicCatalogActivation(good)

    gid_corrupt = _projection(tmp_path, (_record("2"),), name="gid-corrupt.sqlite3")
    with _writable_projection(gid_corrupt.path) as connection:
        connection.execute(
            "UPDATE products SET product_gid_digits = ?, product_gid_length = ?",
            ("999", 3),
        )
    with pytest.raises(DatasetUnavailableError):
        activation.activate(gid_corrupt)
    assert activation.active_generation == good.dataset_generation

    payload_corrupt = _projection(tmp_path, (_record("3"),), name="payload-corrupt.sqlite3")
    pretty_record = json.dumps(_record("3").as_dict(), indent=2, sort_keys=True).encode()
    with _writable_projection(payload_corrupt.path) as connection:
        connection.execute("UPDATE products SET product_record_json = ?", (pretty_record,))
    with pytest.raises(DatasetUnavailableError):
        CatalogProjection.open(payload_corrupt.path)

    variant_corrupt = _projection(tmp_path, (_record("4"),), name="variant-corrupt.sqlite3")
    with _writable_projection(variant_corrupt.path) as connection:
        connection.execute(
            "UPDATE variants SET variant_gid_digits = ?, variant_gid_length = ?",
            ("999", 3),
        )
    with pytest.raises(DatasetUnavailableError):
        CatalogProjection.open(variant_corrupt.path)

    schema_corrupt = _projection(tmp_path, (_record("5"),), name="schema-corrupt.sqlite3")
    with _writable_projection(schema_corrupt.path) as connection:
        connection.execute("CREATE TABLE extra_state (value TEXT) STRICT")
    with pytest.raises(DatasetUnavailableError):
        CatalogProjection.open(schema_corrupt.path)

    index_corrupt = _projection(tmp_path, (_record("6"),), name="index-corrupt.sqlite3")
    with _writable_projection(index_corrupt.path) as connection:
        connection.execute("DROP INDEX variants_parent_order")
        connection.execute("CREATE INDEX variants_parent_order ON variants(variant_gid_digits)")
    with pytest.raises(DatasetUnavailableError):
        CatalogProjection.open(index_corrupt.path)

    nonstrict = tmp_path / "nonstrict.sqlite3"
    _empty_projection_schema(nonstrict, pagination._SCHEMA.replace(") STRICT;", ");"))
    with pytest.raises(DatasetUnavailableError):
        CatalogProjection.open(nonstrict)

    extra_column = tmp_path / "extra-column.sqlite3"
    _empty_projection_schema(
        extra_column,
        pagination._SCHEMA.replace(
            "product_record_json BLOB NOT NULL,",
            "product_record_json BLOB NOT NULL, unexpected TEXT,",
        ),
    )
    with pytest.raises(DatasetUnavailableError):
        CatalogProjection.open(extra_column)

    nonpartial = tmp_path / "nonpartial-index.sqlite3"
    _empty_projection_schema(nonpartial, pagination._SCHEMA.replace("WHERE is_public = 1;", ";"))
    with pytest.raises(DatasetUnavailableError):
        CatalogProjection.open(nonpartial)

    forged_predicate = tmp_path / "forged-index-predicate.sqlite3"
    _empty_projection_schema(
        forged_predicate,
        pagination._SCHEMA.replace("WHERE is_public = 1;", "WHERE is_public = 0;", 1),
    )
    with pytest.raises(DatasetUnavailableError):
        CatalogProjection.open(forged_predicate)

    no_foreign_key = tmp_path / "no-foreign-key.sqlite3"
    _empty_projection_schema(
        no_foreign_key,
        pagination._SCHEMA.replace(
            "product_gid TEXT NOT NULL REFERENCES products(product_gid),",
            "product_gid TEXT NOT NULL,",
        ),
    )
    with pytest.raises(DatasetUnavailableError):
        CatalogProjection.open(no_foreign_key)

    no_product_primary_key = tmp_path / "no-product-primary-key.sqlite3"
    _empty_projection_schema(
        no_product_primary_key,
        pagination._SCHEMA.replace(
            "product_gid TEXT PRIMARY KEY,",
            "product_gid TEXT,",
        ),
    )
    with pytest.raises(DatasetUnavailableError):
        CatalogProjection.open(no_product_primary_key)


def test_semantic_verifier_rejects_orphans_oversized_blobs_and_extra_variants(
    tmp_path: Path,
) -> None:
    orphan = _projection(tmp_path, (_record("1"),), name="orphan.sqlite3")
    public_variant = pagination.CatalogVariantItemV1.from_variant_record(
        _variant("999", "999")
    ).to_json_bytes()
    with _writable_projection(orphan.path) as connection:
        connection.execute(
            "INSERT INTO variants VALUES (?, ?, ?, ?, ?, ?)",
            (
                "gid://shopify/ProductVariant/999",
                "gid://shopify/Product/999",
                3,
                "999",
                "gid://shopify/InventoryItem/999",
                public_variant,
            ),
        )
    with pytest.raises(DatasetUnavailableError):
        CatalogProjection.open(orphan.path)

    oversized_product = _projection(tmp_path, (_record("2"),), name="oversized-product.sqlite3")
    with _writable_projection(oversized_product.path) as connection:
        connection.execute(
            "UPDATE products SET product_record_json = ?",
            (b"x" * (MAX_CONTRACT_BYTES + 1),),
        )
    with pytest.raises(DatasetUnavailableError):
        CatalogProjection.open(oversized_product.path)

    oversized_variant = _projection(tmp_path, (_record("3"),), name="oversized-variant.sqlite3")
    with _writable_projection(oversized_variant.path) as connection:
        connection.execute(
            "UPDATE variants SET public_variant_json = ?",
            (b"x" * (MAX_CONTRACT_BYTES + 1),),
        )
    with pytest.raises(DatasetUnavailableError):
        CatalogProjection.open(oversized_variant.path)

    extra = _projection(tmp_path, (_record("4"),), name="extra-variant.sqlite3")
    extra_variant = _variant("4", "400")
    extra_public = pagination.CatalogVariantItemV1.from_variant_record(
        extra_variant
    ).to_json_bytes()
    with _writable_projection(extra.path) as connection:
        connection.execute(
            "INSERT INTO variants VALUES (?, ?, ?, ?, ?, ?)",
            (
                extra_variant.variant_gid,
                extra_variant.product_gid,
                3,
                "400",
                extra_variant.inventory_item_gid,
                extra_public,
            ),
        )
        connection.execute(
            "UPDATE projection_metadata SET variant_count = ? WHERE singleton = ?", (2, 1)
        )
    with pytest.raises(DatasetUnavailableError):
        CatalogProjection.open(extra.path)


def test_fetch_normalizes_corrupt_rows_and_runtime_page_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projection = _projection(tmp_path, (_record("1"),), name="fetch-corrupt.sqlite3")
    paginator = _paginator(projection)
    with _writable_projection(projection.path) as connection:
        connection.execute("UPDATE products SET product_family = ?", ("not-a-family",))
    monkeypatch.setattr(CatalogProjection, "_assert_file_unchanged", lambda _self: None)
    with pytest.raises(DatasetUnavailableError):
        paginator.fetch_page(_request())

    healthy = _projection(tmp_path, (_record("2"),), name="page-failure.sqlite3")
    request = _request()
    context = CursorContextV1.from_request(
        request,
        healthy.dataset_generation,
        last_product_gid=None,
        expires_at="2026-09-02T12:30:00.000000Z",
    )

    def fail_validation(_self: CatalogPageV1, _context: CursorContextV1) -> None:
        raise pagination.RuntimeContractError("synthetic")

    monkeypatch.setattr(CatalogPageV1, "validate_for_context", fail_validation)
    with pytest.raises(DatasetUnavailableError):
        healthy.fetch_page(request, context)


def test_projection_fetch_context_guards(tmp_path: Path) -> None:
    projection = _projection(tmp_path, (_record("1"),))
    request = _request()
    context = CursorContextV1.from_request(
        request,
        projection.dataset_generation,
        last_product_gid=None,
        expires_at="2026-09-02T12:30:00.000000Z",
    )
    with pytest.raises(PaginationContractError, match="CursorContextV1"):
        projection.fetch_page(request, object())  # type: ignore[arg-type]
    with pytest.raises(CursorContextMismatchError):
        projection.fetch_page(_request(page_size=1), context)
    with pytest.raises(StaleGenerationError):
        projection.fetch_page(
            request,
            replace(context, dataset_generation=GENERATION_B),
        )
