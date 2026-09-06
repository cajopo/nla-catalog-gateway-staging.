from __future__ import annotations

import json
import pickle
import runpy
import stat
import sys
from contextlib import contextmanager
from dataclasses import FrozenInstanceError, fields, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from scripts import prove_real_catalog_cores

import test_generation_bundle as bundle_helpers
from nla_catalog_gateway import core_evidence
from nla_catalog_gateway.core_evidence import (
    CatalogCoreEvidenceError,
    VerifiedCatalogCoreEvidenceV1,
    verify_catalog_core_evidence,
)
from nla_catalog_gateway.facets import FacetDimension
from nla_catalog_gateway.generation_bundle import VerifiedReconciledGenerationV1
from nla_catalog_gateway.runtime_contract import (
    DEFAULT_CAPABILITIES_V1,
    CatalogPageV1,
    CatalogProductRecordV1,
    CatalogRequestV1,
    RequestFamily,
)
from nla_catalog_gateway.taxonomy import Game, ProductFamily

ERROR = "catalog core evidence verification failed"
CODE_SHA = "c" * 40
SUMMARY_SHA = "d" * 64


def _records() -> tuple[CatalogProductRecordV1, ...]:
    records: list[CatalogProductRecordV1] = []
    product_id = 1
    for game in Game:
        for sample in range(3):
            record = replace(
                bundle_helpers._product(str(product_id)),
                game=game,
                canonical_card_name=(
                    f"Shared {game.value}" if sample < 2 else f"Unique {game.value}"
                ),
            )
            if sample == 1:
                record = replace(
                    record,
                    total_inventory=0,
                    variants=(replace(record.variants[0], inventory_quantity=0),),
                )
            records.append(record)
            product_id += 1
        for subtype in ("booster-box", None):
            sealed = replace(
                bundle_helpers._product(str(product_id), family=ProductFamily.SEALED),
                game=game,
                product_subtype=subtype,
                subtype_rule_id=None if subtype is None else "sealed:booster-box",
                subtype_reason="no_subtype_match" if subtype is None else None,
            )
            records.append(sealed)
            product_id += 1
        records.append(
            replace(
                bundle_helpers._product(str(product_id), family=ProductFamily.ACCESSORY),
                game=game,
            )
        )
        product_id += 1
        records.append(
            replace(
                bundle_helpers._product(
                    str(product_id),
                    status=bundle_helpers.runtime.ProductStatus.DRAFT,
                    published=False,
                ),
                game=game,
                canonical_card_name=None,
            )
        )
        product_id += 1
    records.append(bundle_helpers._product(str(product_id), family=ProductFamily.UNCLASSIFIED))
    return tuple(records)


def _verified(
    records: tuple[CatalogProductRecordV1, ...] | None = None,
) -> VerifiedReconciledGenerationV1:
    _, _, generation = bundle_helpers._generation(_records() if records is None else records)
    return VerifiedReconciledGenerationV1(generation, SUMMARY_SHA)


def _verification_result() -> core_evidence._VerificationResult:
    evidence = core_evidence._new_evidence(
        shop_domain=bundle_helpers.SHOP,
        summary_sha256=SUMMARY_SHA,
        dataset_generation="sha256:" + "1" * 64,
        catalog_content_sha256="2" * 64,
        projection_fingerprint="3" * 64,
        code_sha=CODE_SHA,
    )
    measurements = core_evidence._OperationalMeasurements(
        projection_build_nanoseconds=11,
        pagination_traversal_nanoseconds=12,
        search_query_nanoseconds=13,
        facet_evaluation_nanoseconds=14,
        sync_bootstrap_nanoseconds=15,
        pagination_page_count=16,
        search_query_count=17,
        facet_evaluation_count=18,
    )
    return core_evidence._VerificationResult(evidence, measurements)


def _assert_fixed_error(call: Any) -> None:
    with pytest.raises(CatalogCoreEvidenceError) as captured:
        call()
    assert str(captured.value) == ERROR
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


def test_real_core_gate_returns_bound_opaque_evidence_and_cleans_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verified = _verified()
    projection_path = tmp_path / "core-proof.sqlite3"
    capability_bytes = DEFAULT_CAPABILITIES_V1.to_json_bytes()

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("capability gate must not be called")

    monkeypatch.setattr(CatalogRequestV1, "require_executable", forbidden)
    monkeypatch.setattr(CatalogPageV1, "require_output_capability", forbidden)
    evidence = verify_catalog_core_evidence(
        verified,
        projection_path=projection_path,
        code_sha=CODE_SHA,
    )

    assert type(evidence) is VerifiedCatalogCoreEvidenceV1
    assert not projection_path.exists()
    assert evidence.shop_domain == bundle_helpers.SHOP
    assert evidence.summary_sha256 == SUMMARY_SHA
    assert evidence.dataset_generation == verified.generation.dataset_manifest.dataset_generation
    assert (
        evidence.catalog_content_sha256
        == verified.generation.dataset_manifest.catalog_content_sha256
    )
    assert len(evidence.projection_fingerprint) == 64
    assert evidence.code_sha == CODE_SHA
    assert DEFAULT_CAPABILITIES_V1.to_json_bytes() == capability_bytes
    assert repr(evidence).startswith("<nla_catalog_gateway.core_evidence.")
    assert SUMMARY_SHA not in repr(evidence)
    assert not hasattr(evidence, "as_dict")
    assert not hasattr(evidence, "to_json_bytes")
    assert [field.name for field in fields(evidence)] == [
        "shop_domain",
        "summary_sha256",
        "dataset_generation",
        "catalog_content_sha256",
        "projection_fingerprint",
        "code_sha",
    ]
    with pytest.raises(FrozenInstanceError):
        evidence.code_sha = "e" * 40  # type: ignore[misc]
    _assert_fixed_error(lambda: pickle.dumps(evidence))
    _assert_fixed_error(lambda: evidence.__reduce__())


def test_evidence_has_no_public_constructor_or_pickle_reduction() -> None:
    _assert_fixed_error(VerifiedCatalogCoreEvidenceV1)
    evidence = core_evidence._new_evidence(
        shop_domain=bundle_helpers.SHOP,
        summary_sha256=SUMMARY_SHA,
        dataset_generation="sha256:" + "1" * 64,
        catalog_content_sha256="2" * 64,
        projection_fingerprint="3" * 64,
        code_sha=CODE_SHA,
    )
    _assert_fixed_error(lambda: evidence.__reduce_ex__(5))


@pytest.mark.parametrize("value", ["bad", "gid://shopify/Product/0", object()])
def test_gid_key_rejects_noncanonical_values(value: object) -> None:
    _assert_fixed_error(lambda: core_evidence._gid_key(value))  # type: ignore[arg-type]


@pytest.mark.parametrize("code_sha", ["C" * 40, "c" * 39, b"c" * 40])
def test_public_gate_rejects_invalid_code_sha(
    tmp_path: Path,
    code_sha: object,
) -> None:
    _assert_fixed_error(
        lambda: verify_catalog_core_evidence(
            _verified(),
            projection_path=tmp_path / "proof.sqlite3",
            code_sha=code_sha,  # type: ignore[arg-type]
        )
    )


def test_public_gate_rejects_wrong_wrapper_path_shapes_and_existing_destination(
    tmp_path: Path,
) -> None:
    verified = _verified()
    with pytest.raises(TypeError):
        verify_catalog_core_evidence(verified, tmp_path / "positional.sqlite3", CODE_SHA)  # type: ignore[misc]
    _assert_fixed_error(
        lambda: verify_catalog_core_evidence(  # type: ignore[arg-type]
            object(), projection_path=tmp_path / "proof.sqlite3", code_sha=CODE_SHA
        )
    )
    _assert_fixed_error(
        lambda: verify_catalog_core_evidence(  # type: ignore[arg-type]
            verified,
            projection_path=str(tmp_path / "proof.sqlite3"),
            code_sha=CODE_SHA,
        )
    )
    _assert_fixed_error(
        lambda: verify_catalog_core_evidence(
            verified,
            projection_path=Path("relative.sqlite3"),
            code_sha=CODE_SHA,
        )
    )
    noncanonical = tmp_path / "child" / ".." / "proof.sqlite3"
    _assert_fixed_error(
        lambda: verify_catalog_core_evidence(
            verified, projection_path=noncanonical, code_sha=CODE_SHA
        )
    )
    existing = tmp_path / "existing.sqlite3"
    existing.write_bytes(b"preserve")
    _assert_fixed_error(
        lambda: verify_catalog_core_evidence(verified, projection_path=existing, code_sha=CODE_SHA)
    )
    assert existing.read_bytes() == b"preserve"
    _assert_fixed_error(
        lambda: verify_catalog_core_evidence(
            verified,
            projection_path=core_evidence.REPOSITORY_ROOT / "forbidden.sqlite3",
            code_sha=CODE_SHA,
        )
    )
    _assert_fixed_error(
        lambda: verify_catalog_core_evidence(
            verified,
            projection_path=core_evidence.REPOSITORY_ROOT,
            code_sha=CODE_SHA,
        )
    )


def test_public_gate_revalidates_wrapper_digest_and_source_parts(tmp_path: Path) -> None:
    verified = _verified()
    object.__setattr__(verified, "summary_sha256", "invalid")
    _assert_fixed_error(
        lambda: verify_catalog_core_evidence(
            verified,
            projection_path=tmp_path / "digest.sqlite3",
            code_sha=CODE_SHA,
        )
    )

    verified = _verified()
    source = replace(verified.generation.source_manifest, parts=())
    generation = replace(verified.generation, source_manifest=source)
    forged = VerifiedReconciledGenerationV1(generation, SUMMARY_SHA)
    _assert_fixed_error(
        lambda: verify_catalog_core_evidence(
            forged,
            projection_path=tmp_path / "parts.sqlite3",
            code_sha=CODE_SHA,
        )
    )


def test_missing_game_search_rejects_and_removes_projection(tmp_path: Path) -> None:
    records = tuple(record for record in _records() if record.game is Game.MAGIC)
    verified = _verified(records)
    projection_path = tmp_path / "missing-game.sqlite3"
    _assert_fixed_error(
        lambda: verify_catalog_core_evidence(
            verified, projection_path=projection_path, code_sha=CODE_SHA
        )
    )
    assert not projection_path.exists()


def test_projection_build_and_cleanup_failures_are_fixed_and_value_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verified = _verified()
    sensitive = "secret-path-value"

    def fail_build(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError(sensitive)

    monkeypatch.setattr(core_evidence, "build_catalog_projection", fail_build)
    _assert_fixed_error(
        lambda: verify_catalog_core_evidence(
            verified,
            projection_path=tmp_path / "build-failure.sqlite3",
            code_sha=CODE_SHA,
        )
    )

    monkeypatch.undo()
    projection_path = tmp_path / "cleanup-failure.sqlite3"

    def fail_cleanup(_path: Path) -> None:
        raise RuntimeError(sensitive)

    monkeypatch.setattr(core_evidence, "_remove_projection", fail_cleanup)
    _assert_fixed_error(
        lambda: verify_catalog_core_evidence(
            verified, projection_path=projection_path, code_sha=CODE_SHA
        )
    )
    assert projection_path.exists()
    projection_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    projection_path.unlink()


def test_projection_fingerprint_change_rejects_and_cleans(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projection_path = tmp_path / "changed.sqlite3"

    class FakeProjection:
        path = projection_path
        dataset_generation = "sha256:" + "1" * 64
        _file_fingerprint = SimpleNamespace(content_sha256="1" * 64)

        @classmethod
        def open(cls, _path: Path, *, expected_generation: str) -> SimpleNamespace:
            assert expected_generation == cls.dataset_generation
            return SimpleNamespace(_file_fingerprint=SimpleNamespace(content_sha256="2" * 64))

    def build(*_args: object, **_kwargs: object) -> FakeProjection:
        projection_path.write_bytes(b"temporary")
        return FakeProjection()

    class NoOp:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

    monkeypatch.setattr(core_evidence, "build_catalog_projection", build)
    monkeypatch.setattr(core_evidence, "AtomicCatalogActivation", NoOp)
    monkeypatch.setattr(core_evidence, "CursorCodecV1", NoOp)
    monkeypatch.setattr(core_evidence, "CatalogPaginator", NoOp)
    monkeypatch.setattr(core_evidence, "_verify_pagination", lambda *_args: None)
    monkeypatch.setattr(core_evidence, "_verify_search", lambda *_args: None)
    monkeypatch.setattr(core_evidence, "_verify_facets", lambda *_args: None)
    monkeypatch.setattr(core_evidence, "_verify_sync", lambda *_args: None)
    _assert_fixed_error(
        lambda: verify_catalog_core_evidence(
            _verified(), projection_path=projection_path, code_sha=CODE_SHA
        )
    )
    assert not projection_path.exists()


class _FakePaginator:
    def __init__(
        self,
        expected: dict[tuple[Game, RequestFamily], tuple[str, ...]],
        *,
        duplicate: bool = False,
        wrong: bool = False,
        never_terminal: bool = False,
        corrupt_deep: bool = False,
    ) -> None:
        self.expected = expected
        self.duplicate = duplicate
        self.wrong = wrong
        self.never_terminal = never_terminal
        self.corrupt_deep = corrupt_deep

    def fetch_page(
        self,
        request: CatalogRequestV1,
        *,
        cursor: str | None = None,
    ) -> SimpleNamespace:
        values = self.expected[(request.game, request.product_family)]
        start = 0 if cursor is None else int(cursor)
        page_values = values[start : start + 100]
        if self.duplicate and values:
            page_values = (values[0], values[0])
        if self.wrong and values:
            page_values = ("gid://shopify/Product/999999",)
        if self.corrupt_deep and start <= 24_998 < start + len(page_values):
            offset = 24_998 - start
            page_values = (
                *page_values[:offset],
                "gid://shopify/Product/999999",
                *page_values[offset + 1 :],
            )
        next_offset = start + len(page_values)
        next_cursor = str(next_offset) if self.never_terminal or next_offset < len(values) else None
        items = tuple(SimpleNamespace(product_gid=gid) for gid in page_values)
        return SimpleNamespace(page=SimpleNamespace(items=items), next_cursor=next_cursor)


def _pagination_map(
    target: tuple[str, ...],
) -> dict[tuple[Game, RequestFamily], tuple[str, ...]]:
    return {
        (game, family): target if (game, family) == (Game.MAGIC, RequestFamily.ALL) else ()
        for game in Game
        for family in core_evidence._REQUEST_FAMILIES
    }


def test_deep_pagination_bound_is_exercised() -> None:
    target = tuple(f"gid://shopify/Product/{index}" for index in range(1, 25_002))
    expected = _pagination_map(target)
    core_evidence._verify_pagination(_FakePaginator(expected), expected)  # type: ignore[arg-type]
    _assert_fixed_error(
        lambda: core_evidence._verify_pagination(  # type: ignore[arg-type]
            _FakePaginator(expected, corrupt_deep=True), expected
        )
    )


@pytest.mark.parametrize(
    "option",
    ["duplicate", "wrong", "never_terminal"],
)
def test_pagination_rejects_duplicates_mismatch_and_nonterminal_pages(option: str) -> None:
    expected = _pagination_map(("gid://shopify/Product/1",))
    paginator = _FakePaginator(expected, **{option: True})
    _assert_fixed_error(
        lambda: core_evidence._verify_pagination(paginator, expected)  # type: ignore[arg-type]
    )


def test_search_rejects_duplicate_input_and_accounting_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _records()[0]
    _assert_fixed_error(lambda: core_evidence._verify_search((record, record)))

    monkeypatch.setattr(
        core_evidence,
        "report_missing_canonical_names",
        lambda *_args, **_kwargs: SimpleNamespace(single_record_count=-1, missing=()),
    )
    _assert_fixed_error(lambda: core_evidence._verify_search(_records()))


def test_search_rejects_missing_selected_hit_and_cross_game_hit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = _records()
    monkeypatch.setattr(
        core_evidence,
        "search_single_cards",
        lambda *_args, **_kwargs: SimpleNamespace(
            match_tier=core_evidence.MatchTier.EXACT, hits=()
        ),
    )
    _assert_fixed_error(lambda: core_evidence._verify_search(records))

    monkeypatch.undo()

    def cross_game_hits(
        source: tuple[CatalogProductRecordV1, ...],
        *,
        game: Game,
        query: str,
    ) -> SimpleNamespace:
        selected = next(
            record
            for record in source
            if record.game is game and record.canonical_card_name == query
        )
        other = next(record for record in source if record.game is not game and record.game)
        return SimpleNamespace(
            match_tier=core_evidence.MatchTier.EXACT,
            hits=(
                SimpleNamespace(
                    product_gid=selected.product_gid,
                    match_tier=core_evidence.MatchTier.EXACT,
                ),
                SimpleNamespace(
                    product_gid=other.product_gid,
                    match_tier=core_evidence.MatchTier.EXACT,
                ),
            ),
        )

    monkeypatch.setattr(core_evidence, "search_single_cards", cross_game_hits)
    _assert_fixed_error(lambda: core_evidence._verify_search(records))


def test_search_rejects_partial_multi_print_omission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = _records()

    def one_print_only(
        source: tuple[CatalogProductRecordV1, ...],
        *,
        game: Game,
        query: str,
    ) -> SimpleNamespace:
        selected = next(
            record
            for record in source
            if record.game is game and record.canonical_card_name == query and record.publishable
        )
        return SimpleNamespace(
            match_tier=core_evidence.MatchTier.EXACT,
            hits=(
                SimpleNamespace(
                    product_gid=selected.product_gid,
                    match_tier=core_evidence.MatchTier.EXACT,
                ),
            ),
        )

    monkeypatch.setattr(core_evidence, "search_single_cards", one_print_only)
    _assert_fixed_error(lambda: core_evidence._verify_search(records))


def test_search_samples_unique_names_when_no_multi_print_exists() -> None:
    records = tuple(
        replace(record, canonical_card_name=f"Unique {record.product_gid}")
        if record.product_family is ProductFamily.SINGLE and record.canonical_card_name is not None
        else record
        for record in _records()
    )
    assert core_evidence._verify_search(records) == 12


def test_facet_helpers_reject_missing_dimension_and_wrong_complete_maps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _assert_fixed_error(
        lambda: core_evidence._facet(SimpleNamespace(facets=()), FacetDimension.IN_STOCK)  # type: ignore[arg-type]
    )
    original = core_evidence.evaluate_facets

    def missing_items(*args: object, **kwargs: object) -> SimpleNamespace:
        result = original(*args, **kwargs)  # type: ignore[arg-type]
        return SimpleNamespace(items=(), facets=result.facets)

    monkeypatch.setattr(core_evidence, "evaluate_facets", missing_items)
    _assert_fixed_error(lambda: core_evidence._verify_facets(_records()))


def test_facets_reject_wrong_sealed_subtype_map(monkeypatch: pytest.MonkeyPatch) -> None:
    original = core_evidence.evaluate_facets

    def wrong_subtypes(items: tuple[object, ...], request: CatalogRequestV1) -> SimpleNamespace:
        result = original(items, request)  # type: ignore[arg-type]
        if request.product_family is not RequestFamily.SEALED:
            return result  # type: ignore[return-value]
        facets = tuple(
            SimpleNamespace(
                dimension=facet.dimension,
                values=() if facet.dimension is FacetDimension.PRODUCT_SUBTYPE else facet.values,
                missing_value_count=facet.missing_value_count,
            )
            for facet in result.facets
        )
        return SimpleNamespace(items=result.items, facets=facets)

    monkeypatch.setattr(core_evidence, "evaluate_facets", wrong_subtypes)
    _assert_fixed_error(lambda: core_evidence._verify_facets(_records()))


@pytest.mark.parametrize("callback", ["validator", "projector", "activation_probe"])
def test_sync_sentinel_callbacks_are_tripwires(
    monkeypatch: pytest.MonkeyPatch,
    callback: str,
) -> None:
    class CallbackSync:
        def __init__(self, **kwargs: Any) -> None:
            name = "activation" if callback == "activation_probe" else callback
            try:
                kwargs[callback](object())
            except AssertionError:
                pass
            self.name = name

        def active_dataset(self) -> SimpleNamespace:
            return SimpleNamespace()

    monkeypatch.setattr(core_evidence, "SyncCore", CallbackSync)
    _assert_fixed_error(lambda: core_evidence._verify_sync(_verified(), bundle_helpers.SHOP))


def test_sync_rejects_mismatched_active_view(monkeypatch: pytest.MonkeyPatch) -> None:
    class WrongSync:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def active_dataset(self) -> SimpleNamespace:
            return SimpleNamespace(shop_domain="wrong.myshopify.com")

    monkeypatch.setattr(core_evidence, "SyncCore", WrongSync)
    _assert_fixed_error(lambda: core_evidence._verify_sync(_verified(), bundle_helpers.SHOP))


def test_runner_enters_verified_context_and_passes_all_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verified = _verified()
    observed: list[tuple[object, ...]] = []

    @contextmanager
    def opened(directory: Path, digest: str) -> Any:
        observed.append((directory, digest))
        yield verified

    result = _verification_result()

    def checked(
        value: object,
        *,
        projection_path: Path,
        code_sha: str,
    ) -> core_evidence._VerificationResult:
        observed.append((value, projection_path, code_sha))
        return result

    monkeypatch.setattr(prove_real_catalog_cores, "open_reconciled_generation", opened)
    monkeypatch.setattr(prove_real_catalog_cores, "_verify_with_measurements", checked)
    bundle = tmp_path / "bundle"
    projection = tmp_path / "projection.sqlite3"
    report = tmp_path / "report.json"
    prove_real_catalog_cores.run_proof(bundle, SUMMARY_SHA, projection, CODE_SHA, report)
    assert observed == [(bundle, SUMMARY_SHA), (verified, projection, CODE_SHA)]
    document = json.loads(report.read_bytes())
    assert document == {
        "bindings": {
            "catalogContentSha256": "2" * 64,
            "codeSha": CODE_SHA,
            "datasetGeneration": "sha256:" + "1" * 64,
            "projectionFingerprint": "3" * 64,
            "shopDomain": bundle_helpers.SHOP,
            "summarySha256": SUMMARY_SHA,
        },
        "durationNanoseconds": {
            "facetEvaluation": 14,
            "paginationTraversal": 12,
            "projectionBuild": 11,
            "searchQuery": 13,
            "syncBootstrap": 15,
        },
        "operationCounts": {
            "facetEvaluations": 18,
            "paginationPages": 16,
            "searchQueries": 17,
            "syncBootstraps": 1,
        },
        "result": "ACCEPTED",
        "schemaVersion": 1,
    }
    assert str(tmp_path) not in report.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("bundle_exists", "projection_relative", "report_relative"),
    [
        (True, ".", "../report.json"),
        (True, "projection.sqlite3", "../report.json"),
        (False, "projection.sqlite3", "."),
        (True, "../projection.sqlite3", "report.json"),
    ],
)
def test_runner_rejects_projection_or_report_inside_closed_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bundle_exists: bool,
    projection_relative: str,
    report_relative: str,
) -> None:
    bundle = tmp_path / "bundle"
    if bundle_exists:
        bundle.mkdir()
    projection = (bundle / projection_relative).resolve()
    report = (bundle / report_relative).resolve()
    opened = False

    def forbidden_open(*_args: object) -> object:
        nonlocal opened
        opened = True
        raise AssertionError

    monkeypatch.setattr(prove_real_catalog_cores, "open_reconciled_generation", forbidden_open)
    with pytest.raises(ValueError):
        prove_real_catalog_cores.run_proof(
            bundle,
            SUMMARY_SHA,
            projection,
            CODE_SHA,
            report,
        )
    assert not opened


def test_external_report_boundary_rejects_unsafe_paths_and_invalid_metrics(
    tmp_path: Path,
) -> None:
    repository_report = prove_real_catalog_cores.REPOSITORY_ROOT / "forbidden-report.json"
    existing = tmp_path / "existing-report.json"
    existing.write_bytes(b"preserve")
    for value in ("report.json", Path("report.json"), repository_report, existing):
        with pytest.raises(ValueError):
            prove_real_catalog_cores._validated_report_path(value)  # type: ignore[arg-type]
    assert existing.read_bytes() == b"preserve"
    with pytest.raises(ValueError):
        prove_real_catalog_cores._report_bytes(object())  # type: ignore[arg-type]

    forged = object.__new__(core_evidence._VerificationResult)
    object.__setattr__(forged, "evidence", _verification_result().evidence)
    object.__setattr__(forged, "measurements", object())
    with pytest.raises(ValueError):
        prove_real_catalog_cores._report_bytes(forged)

    result = _verification_result()
    invalid_measurements = replace(result.measurements, pagination_page_count=-1)
    invalid_result = replace(result, measurements=invalid_measurements)
    with pytest.raises(ValueError):
        prove_real_catalog_cores._report_bytes(invalid_result)


def test_external_report_install_failure_leaves_no_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = tmp_path / "report.json"

    def fail_link(*_args: object) -> None:
        raise OSError("sensitive")

    monkeypatch.setattr(prove_real_catalog_cores.os, "link", fail_link)
    with pytest.raises(OSError):
        prove_real_catalog_cores._write_report(report, _verification_result())
    assert not report.exists()
    assert tuple(tmp_path.iterdir()) == ()


def test_external_report_cleanup_failure_rolls_back_installed_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = tmp_path / "report.json"
    original_unlink = Path.unlink
    failed = False

    def fail_temporary_once(path: Path, *args: object, **kwargs: object) -> None:
        nonlocal failed
        if path.name.startswith(".nla-core-evidence-") and not failed:
            failed = True
            raise OSError("sensitive")
        original_unlink(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "unlink", fail_temporary_once)
    with pytest.raises(OSError):
        prove_real_catalog_cores._write_report(report, _verification_result())
    assert not report.exists()
    leftovers = tuple(tmp_path.iterdir())
    assert len(leftovers) == 1
    monkeypatch.undo()
    leftovers[0].unlink()


def test_external_report_cleanup_failure_before_install_leaves_no_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = tmp_path / "report.json"
    original_unlink = Path.unlink

    def fail_link(*_args: object) -> None:
        raise OSError("link failure")

    def fail_temporary(path: Path, *args: object, **kwargs: object) -> None:
        if path.name.startswith(".nla-core-evidence-"):
            raise OSError("cleanup failure")
        original_unlink(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(prove_real_catalog_cores.os, "link", fail_link)
    monkeypatch.setattr(Path, "unlink", fail_temporary)
    with pytest.raises(OSError, match="cleanup failure"):
        prove_real_catalog_cores._write_report(report, _verification_result())
    assert not report.exists()
    leftovers = tuple(tmp_path.iterdir())
    assert len(leftovers) == 1
    monkeypatch.undo()
    leftovers[0].unlink()


def test_runner_console_is_exact_and_value_free(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NLA_RECONCILED_BUNDLE_DIRECTORY", "bundle")
    monkeypatch.setenv("NLA_RECONCILIATION_SUMMARY_SHA256", SUMMARY_SHA)
    monkeypatch.setenv("NLA_CORE_EVIDENCE_PROJECTION_PATH", "projection")
    monkeypatch.setenv("NLA_CORE_EVIDENCE_CODE_SHA", CODE_SHA)
    monkeypatch.setenv("NLA_CORE_EVIDENCE_REPORT_PATH", "report")
    monkeypatch.setattr(prove_real_catalog_cores, "run_proof", lambda *_args: None)
    monkeypatch.setattr(sys, "argv", ["prove_real_catalog_cores.py"])
    assert prove_real_catalog_cores.main() == 0
    assert capsys.readouterr() == ("VALUE_FREE_RESULT: ACCEPTED\n", "")

    sensitive = "do-not-print-this"

    def reject(*_args: object) -> None:
        raise RuntimeError(sensitive)

    monkeypatch.setattr(prove_real_catalog_cores, "run_proof", reject)
    monkeypatch.setattr(sys, "argv", ["prove_real_catalog_cores.py", sensitive])
    assert prove_real_catalog_cores.main() == 1
    assert capsys.readouterr() == ("VALUE_FREE_RESULT: REJECTED\n", "")

    monkeypatch.setattr(sys, "argv", ["prove_real_catalog_cores.py"])
    assert prove_real_catalog_cores.main() == 1
    assert capsys.readouterr() == ("VALUE_FREE_RESULT: REJECTED\n", "")


def test_runner_module_guard_is_value_free(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["prove_real_catalog_cores.py"])
    with pytest.raises(SystemExit, match="1"):
        runpy.run_path(prove_real_catalog_cores.__file__, run_name="__main__")
    assert capsys.readouterr() == ("VALUE_FREE_RESULT: REJECTED\n", "")
