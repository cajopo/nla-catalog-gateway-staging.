"""Family search extends existing schema-v2 generations, not the source capture."""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from dataclasses import replace

import pytest

import nla_catalog_gateway.pagination as pagination
import test_app_proxy_security as proxy
import test_core_evidence as evidence
import test_generation_bundle as bundle
import test_runtime_api_integration as integration
from nla_catalog_gateway.canonical_search import normalize_search_text
from nla_catalog_gateway.pagination import CatalogProjection, CursorContextMismatchError
from nla_catalog_gateway.runtime_api import (
    AppProxyVerifierAuthorizer,
    CatalogRequestEnvelopeV1,
    CatalogResponseEnvelopeV1,
    IncompatibleCatalogRequestError,
    RequestDeadlineExceeded,
    RuntimeCatalogService,
    RuntimeHttpRequest,
)
from nla_catalog_gateway.runtime_contract import CatalogFiltersV1, ProductStatus, RequestFamily
from nla_catalog_gateway.search_sql import search_facts, search_scope
from nla_catalog_gateway.taxonomy import Game, ProductFamily
from test_pagination import _paginator, _projection, _record, _request


def commercial(number, family, title, *, stock=0, **kwargs):
    record = _record(str(number), family=family, **kwargs)
    return replace(
        record,
        canonical_card_name=None,
        commercial_title=title,
        total_inventory=stock,
        variants=(replace(record.variants[0], inventory_quantity=stock),),
    )


@pytest.fixture
def family_projection(tmp_path):
    return _projection(
        tmp_path,
        (
            replace(_record("1"), canonical_card_name="Bolt"),
            commercial(2, ProductFamily.SEALED, "Édition Bolt Display"),
            commercial(3, ProductFamily.ACCESSORY, "Bolt Card Binder", stock=2),
            commercial(4, ProductFamily.UNCLASSIFIED, "Bolt Mystery"),
            commercial(5, ProductFamily.SEALED, "Bolt Display", game=Game.POKEMON),
            commercial(6, ProductFamily.SEALED, "Bolt Display", published=False),
            commercial(7, ProductFamily.SEALED, "Bolt Display", status=ProductStatus.DRAFT),
            replace(_record("8"), commercial_title="Bolt", canonical_card_name="Other card"),
            commercial(9, ProductFamily.SEALED, "Bolt Collector Display", stock=1),
            replace(_record("10"), canonical_card_name="Thunder Bolt"),
            replace(
                commercial(11, ProductFamily.ACCESSORY, "Different title"),
                canonical_card_name="Bolt",  # Not authoritative for a non-single.
            ),
            commercial(12, ProductFamily.SEALED, "Literal %_'/[] Display"),
        ),
    )


def found(projection, family, query, **kwargs):
    selected = _request(family=family, query=query, **kwargs)
    return [
        int(item.product_gid.rsplit("/", 1)[1])
        for item in _paginator(projection).fetch_page(selected).page.items
    ]


@pytest.mark.parametrize(
    "family,expected",
    [
        (RequestFamily.SINGLE, [1, 10]),
        (RequestFamily.SEALED, [2, 9]),
        (RequestFamily.ACCESSORY, [3]),
        (RequestFamily.ALL, [1, 2, 3, 9, 10]),
    ],
)
def test_family_title_search_and_all_union_keep_single_semantics(
    family_projection, family, expected
):
    assert found(family_projection, family, " BOLT ") == expected
    assert found(family_projection, family, "no match") == []


@pytest.mark.parametrize(
    "query", ["ÉDITION", "e\u0301dition", "\u00c9dition  BOLT", "Édition\tBolt"]
)
def test_commercial_search_reuses_unicode_case_whitespace_and_accent_contract(
    family_projection, query
):
    assert found(family_projection, RequestFamily.SEALED, query) == [2]
    assert found(family_projection, RequestFamily.SEALED, "edition") == []  # Accents retained.


@pytest.mark.parametrize("query", ["%", "_", "'", "/", "[", "]", "%_'/[]", "%' OR 1=1 --"])
def test_commercial_search_is_literal_and_bound(family_projection, query):
    expected = [] if "OR" in query else [12]
    assert found(family_projection, RequestFamily.SEALED, query) == expected
    assert found(family_projection, RequestFamily.ALL, query) == expected


def test_commercial_search_retains_game_stock_and_subtype_boundaries(family_projection):
    assert found(family_projection, RequestFamily.ALL, "bolt", in_stock=True) == [1, 3, 9, 10]
    assert found(family_projection, RequestFamily.ALL, "bolt", in_stock=False) == [2]
    assert found(family_projection, RequestFamily.ALL, "bolt", game=Game.POKEMON) == [5]
    assert found(family_projection, RequestFamily.ALL, "bolt", game=Game.ONE_PIECE) == []
    assert found(family_projection, RequestFamily.SEALED, "booster-box") == [2, 9, 12]
    selected = _request(family=RequestFamily.SEALED, query="bolt")
    selected = replace(selected, filters=CatalogFiltersV1(None, "booster-box"))
    assert _paginator(family_projection).fetch_page(selected).page.returned_product_count == 2
    selected = replace(selected, filters=CatalogFiltersV1(None, "bundle"))
    assert _paginator(family_projection).fetch_page(selected).page.items == ()


def test_all_retains_single_code_search_but_never_searches_commercial_variant_labels(tmp_path):
    single = _record("1")
    single = replace(single, variants=(replace(single.variants[0], sku="SRC-001"),))
    sealed = commercial(2, ProductFamily.SEALED, "Different title")
    sealed = replace(sealed, variants=(replace(sealed.variants[0], sku="SRC-001", title="BOLT"),))
    projection = _projection(tmp_path, (single, sealed))
    assert found(projection, RequestFamily.ALL, "src-001") == [1]
    assert found(projection, RequestFamily.SEALED, "src-001") == []
    assert found(projection, RequestFamily.ALL, "bolt") == []


def test_all_does_not_run_commercial_normalizer_for_single_rows(tmp_path, monkeypatch):
    projection = _projection(tmp_path, (_record("1"), _record("2")))

    def unexpected_title_normalization(value):
        raise AssertionError("single rows must not enter commercial search")

    monkeypatch.setattr(pagination, "normalize_search_text", unexpected_title_normalization)
    assert found(projection, RequestFamily.ALL, "synthetic card") == [1, 2]
    assert found(projection, RequestFamily.ALL, "unmatched") == []


def test_family_search_keyset_cursor_binds_all_filters_and_numeric_order(family_projection):
    selected = _request(family=RequestFamily.ALL, query="bolt", page_size=2)
    paginator = _paginator(family_projection)
    first = paginator.fetch_page(selected)
    assert first.next_cursor is not None
    for changed in (
        replace(selected, product_family=RequestFamily.SEALED),
        replace(selected, game=Game.POKEMON),
        replace(selected, query="display"),
        replace(selected, filters=CatalogFiltersV1(True, None)),
    ):
        with pytest.raises(CursorContextMismatchError):
            paginator.fetch_page(changed, cursor=first.next_cursor)
    result, seen = first, []
    while True:
        seen.extend(int(item.product_gid.rsplit("/", 1)[1]) for item in result.page.items)
        if result.next_cursor is None:
            break
        result = paginator.fetch_page(selected, cursor=result.next_cursor)
    assert seen == [1, 2, 3, 9, 10]
    assert len(seen) == len(set(seen))


def test_read_time_title_search_preserves_schema_facts_and_unclassified_accounting(
    family_projection,
):
    original_digest = hashlib.sha256(family_projection.path.read_bytes()).hexdigest()
    assert pagination.PROJECTION_SCHEMA_VERSION == 2
    assert found(family_projection, RequestFamily.ALL, None) == [1, 2, 3, 8, 9, 10, 11, 12]
    assert found(family_projection, RequestFamily.ALL, "bolt") == [1, 2, 3, 9, 10]
    with closing(sqlite3.connect(family_projection.path)) as connection:
        unknown = connection.execute(
            "SELECT product_family, is_public FROM products WHERE product_gid_digits = '4'"
        ).fetchone()
        assert unknown == (
            "unclassified",
            0,
        )  # Retained for accounting; not invented classification.
        assert connection.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 12
        assert connection.execute(
            "SELECT normalized_card_name FROM products WHERE product_gid_digits = '2'"
        ).fetchone() == ("",)
    assert family_projection.manifest.unclassified_product_count == 1
    reopened = CatalogProjection.open(family_projection.path)
    assert reopened.manifest == family_projection.manifest
    assert hashlib.sha256(family_projection.path.read_bytes()).hexdigest() == original_digest
    assert search_facts(commercial(2, ProductFamily.SEALED, "Édition Bolt")) == ("", "[]", 0)


@pytest.mark.parametrize(
    "family", [RequestFamily.ALL, RequestFamily.SEALED, RequestFamily.ACCESSORY]
)
def test_commercial_search_uses_existing_keyset_index_without_sort(family_projection, family):
    where, parameters = search_scope(_request(family=family, query="bolt"))
    with closing(sqlite3.connect(family_projection.path)) as connection:
        connection.create_function("nla_search_text", 1, normalize_search_text, deterministic=True)
        plan = connection.execute(
            f"""EXPLAIN QUERY PLAN SELECT product_gid FROM products WHERE {where}
                AND (product_gid_length, product_gid_digits) > (?, ?)
                ORDER BY product_gid_length, product_gid_digits LIMIT ?""",  # noqa: S608
            (*parameters, 1, "2", 3),
        ).fetchall()
    detail = " ".join(row[-1] for row in plan)
    expected_index = (
        "products_public_game_order"
        if family is RequestFamily.ALL
        else "products_public_game_family_order"
    )
    assert expected_index in detail
    assert "TEMP B-TREE" not in detail


def test_commercial_scan_honors_deadline_and_preserves_exception(tmp_path, monkeypatch):
    projection = _projection(
        tmp_path,
        tuple(commercial(n, ProductFamily.SEALED, "Display") for n in range(1, 401)),
    )
    calls = 0

    def normalize(value):
        nonlocal calls
        calls += 1
        return normalize_search_text(value)

    deadline = RequestDeadlineExceeded()

    def checkpoint():
        if calls:
            raise deadline

    monkeypatch.setattr(pagination, "normalize_search_text", normalize)
    with pytest.raises(RequestDeadlineExceeded) as caught:
        _paginator(projection).fetch_page(
            _request(family=RequestFamily.ALL, query="missing"), checkpoint=checkpoint
        )
    assert caught.value is deadline
    assert 0 < calls < 400


@pytest.mark.parametrize(
    "family", [RequestFamily.ALL, RequestFamily.SEALED, RequestFamily.ACCESSORY]
)
@pytest.mark.parametrize("extension", ["include_suggestions", "include_facets"])
def test_family_search_does_not_enable_single_only_extensions(family, extension):
    with pytest.raises(IncompatibleCatalogRequestError):
        CatalogRequestEnvelopeV1(_request(family=family, query="box"), None, **{extension: True})


def test_family_search_passes_evidence_bound_backend_without_gate_overrides(tmp_path):
    case = integration._bound_case(tmp_path, "families", evidence._records(), "a" * 64)
    verifier = proxy._verifier(config=proxy._config(allowed_shops=frozenset({bundle.SHOP})))
    service = RuntimeCatalogService(
        expected_shop_domain=bundle.SHOP,
        backend=case.backend,
        capability_gate=case.gate,
        authorizer=AppProxyVerifierAuthorizer(verifier),
        endpoint_path="/proxy/catalog",
    )
    signature = proxy._signed_query(
        [(name, bundle.SHOP if name == "shop" else value) for name, value in proxy._base_pairs()]
    )
    control = integration._control()
    lease = case.backend.acquire(control=control)
    try:
        for family, number in ((RequestFamily.SEALED, 4), (RequestFamily.ACCESSORY, 6)):
            for selected_family in (family, RequestFamily.ALL):
                selected = _request(family=selected_family, query=f"Synthetic Product {number}")
                case.gate.require_catalog(lease, selected, control=control)
                result = lease.fetch_page(selected, None, control=control)
                assert integration._gids(result) == (f"gid://shopify/Product/{number}",)
                body = CatalogRequestEnvelopeV1(selected, None).to_json_bytes()
                http_request = RuntimeHttpRequest(
                    method="POST",
                    path="/proxy/catalog",
                    raw_query=signature,
                    headers=((b"content-type", b"application/json"),),
                    body_chunks=(body,),
                )
                response = service.catalog(http_request)
                assert response.status == 200
                parsed = CatalogResponseEnvelopeV1.from_json_bytes(response.body)
                assert integration._gids(parsed) == (f"gid://shopify/Product/{number}",)
                assert parsed.suggestions is None
                assert parsed.facets is None
                assert service.catalog(replace(http_request, raw_query=b"")).status == 401
                no_game = body.replace(b'"game":"magic",', b"")
                assert service.catalog(replace(http_request, body_chunks=(no_game,))).status == 400
    finally:
        lease.close()
