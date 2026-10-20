"""Value-free acceptance evidence for the existing real catalog cores.

This module is an integration gate, not a serving or capability boundary. It
materializes one caller-selected projection to exercise the existing cores.
Standalone proofs remove it; packaging may retain the exact successful artifact.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import stat
import time
import unicodedata
from dataclasses import dataclass, field, replace
from pathlib import Path

from nla_catalog_gateway.canonical_search import report_missing_canonical_names
from nla_catalog_gateway.facets import FacetDimension, FacetEvaluation, evaluate_facets
from nla_catalog_gateway.generation_bundle import VerifiedReconciledGenerationV1
from nla_catalog_gateway.pagination import (
    AtomicCatalogActivation,
    CatalogPaginator,
    CatalogProjection,
    CursorCodecV1,
    build_catalog_projection,
)
from nla_catalog_gateway.runtime_contract import (
    CatalogFiltersV1,
    CatalogItemV1,
    CatalogProductRecordV1,
    CatalogRequestV1,
    RequestFamily,
)
from nla_catalog_gateway.sync import SyncCore
from nla_catalog_gateway.taxonomy import Game, ProductFamily

_CONCRETE_PATH_TYPE = type(Path())
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_CODE_SHA_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
_PRODUCT_GID_PATTERN = re.compile(r"gid://shopify/Product/([1-9][0-9]*)\Z")
_ERROR = "catalog core evidence verification failed"
_PAGE_SIZE = 100
CORE_VERIFICATION_VERSION = 2
_PUBLIC_FAMILIES = (
    ProductFamily.SINGLE,
    ProductFamily.SEALED,
    ProductFamily.ACCESSORY,
)
_REQUEST_FAMILIES = (
    RequestFamily.ALL,
    RequestFamily.SINGLE,
    RequestFamily.SEALED,
    RequestFamily.ACCESSORY,
)


class CatalogCoreEvidenceError(ValueError):
    """A fixed, value-free catalog-core evidence rejection."""


@dataclass(frozen=True, slots=True, init=False, repr=False)
class VerifiedCatalogCoreEvidenceV1:
    """Opaque evidence that one verified generation passed every core check."""

    shop_domain: str = field(repr=False)
    summary_sha256: str = field(repr=False)
    dataset_generation: str = field(repr=False)
    catalog_content_sha256: str = field(repr=False)
    projection_fingerprint: str = field(repr=False)
    code_sha: str = field(repr=False)
    verification_version: int = field(repr=False)

    def __new__(cls, *_args: object, **_kwargs: object) -> VerifiedCatalogCoreEvidenceV1:
        raise CatalogCoreEvidenceError(_ERROR)

    def __reduce__(self) -> object:
        raise CatalogCoreEvidenceError(_ERROR)

    def __reduce_ex__(self, _protocol: int) -> object:
        raise CatalogCoreEvidenceError(_ERROR)


@dataclass(frozen=True, slots=True)
class _OperationalMeasurements:
    projection_build_nanoseconds: int
    pagination_traversal_nanoseconds: int
    search_query_nanoseconds: int
    facet_evaluation_nanoseconds: int
    sync_bootstrap_nanoseconds: int
    pagination_page_count: int
    search_query_count: int
    facet_evaluation_count: int


@dataclass(frozen=True, slots=True)
class _VerificationResult:
    evidence: VerifiedCatalogCoreEvidenceV1
    measurements: _OperationalMeasurements
    projection: CatalogProjection | None = None


def _report_bytes(result: _VerificationResult) -> bytes:
    """Serialize the canonical portable evidence report shared by both producers."""

    if type(result) is not _VerificationResult:
        raise ValueError
    if (
        type(result.evidence) is not VerifiedCatalogCoreEvidenceV1
        or type(result.evidence.verification_version) is not int
        or result.evidence.verification_version != CORE_VERIFICATION_VERSION
    ):
        raise ValueError
    measurements = result.measurements
    if type(measurements) is not _OperationalMeasurements:
        raise ValueError
    durations = {
        "facetEvaluation": measurements.facet_evaluation_nanoseconds,
        "paginationTraversal": measurements.pagination_traversal_nanoseconds,
        "projectionBuild": measurements.projection_build_nanoseconds,
        "searchQuery": measurements.search_query_nanoseconds,
        "syncBootstrap": measurements.sync_bootstrap_nanoseconds,
    }
    counts = {
        "facetEvaluations": measurements.facet_evaluation_count,
        "paginationPages": measurements.pagination_page_count,
        "searchQueries": measurements.search_query_count,
        "syncBootstraps": 1,
    }
    if any(
        type(value) is not int or value < 0 for value in (*durations.values(), *counts.values())
    ):
        raise ValueError
    return json.dumps(
        {
            "bindings": {
                "catalogContentSha256": result.evidence.catalog_content_sha256,
                "codeSha": result.evidence.code_sha,
                "datasetGeneration": result.evidence.dataset_generation,
                "projectionFingerprint": result.evidence.projection_fingerprint,
                "shopDomain": result.evidence.shop_domain,
                "summarySha256": result.evidence.summary_sha256,
            },
            "durationNanoseconds": durations,
            "operationCounts": counts,
            "result": "ACCEPTED",
            "schemaVersion": CORE_VERIFICATION_VERSION,
        },
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _gid_key(product_gid: str) -> tuple[int, str]:
    if type(product_gid) is not str:
        raise CatalogCoreEvidenceError(_ERROR)
    match = _PRODUCT_GID_PATTERN.fullmatch(product_gid)
    if match is None:
        raise CatalogCoreEvidenceError(_ERROR)
    digits = match.group(1)
    return (len(digits), digits)


def _request(game: Game, family: RequestFamily) -> CatalogRequestV1:
    return CatalogRequestV1(
        game=game,
        product_family=family,
        query=None,
        filters=CatalogFiltersV1(in_stock=None, product_subtype=None),
        page_size=_PAGE_SIZE,
    )


def _expected_pagination(
    records: tuple[CatalogProductRecordV1, ...],
) -> dict[tuple[Game, RequestFamily], tuple[str, ...]]:
    expected: dict[tuple[Game, RequestFamily], tuple[str, ...]] = {}
    for game in Game:
        for family in _REQUEST_FAMILIES:
            product_family = None if family is RequestFamily.ALL else ProductFamily(family.value)
            gids = (
                record.product_gid
                for record in records
                if record.publishable
                and record.product_family is not ProductFamily.UNCLASSIFIED
                and record.game is game
                and (product_family is None or record.product_family is product_family)
            )
            expected[(game, family)] = tuple(sorted(gids, key=_gid_key))
    return expected


def _verify_pagination(
    paginator: CatalogPaginator,
    expected_by_request: dict[tuple[Game, RequestFamily], tuple[str, ...]],
) -> int:
    page_count = 0
    for game in Game:
        for family in _REQUEST_FAMILIES:
            expected = expected_by_request[(game, family)]
            request = _request(game, family)
            cursor: str | None = None
            actual: list[str] = []
            maximum_pages = max(1, (len(expected) + _PAGE_SIZE - 1) // _PAGE_SIZE)
            for _page_number in range(maximum_pages):
                result = paginator.fetch_page(request, cursor=cursor)
                page_count += 1
                page_gids = tuple(item.product_gid for item in result.page.items)
                if len(page_gids) != len(set(page_gids)):
                    raise CatalogCoreEvidenceError(_ERROR)
                actual.extend(page_gids)
                cursor = result.next_cursor
                if cursor is None:
                    break
            else:
                raise CatalogCoreEvidenceError(_ERROR)
            actual_tuple = tuple(actual)
            if len(expected) >= 25_001 and actual_tuple[24_998:25_001] != expected[24_998:25_001]:
                raise CatalogCoreEvidenceError(_ERROR)
            if (
                cursor is not None
                or actual_tuple != expected
                or len(actual_tuple) != len(set(actual_tuple))
            ):
                raise CatalogCoreEvidenceError(_ERROR)
    return page_count


def _expected_normalized_name(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _expected_suggestion_label(name: str, game: Game) -> str:
    """Independent suffix oracle; product matching still uses the unmodified name."""
    label = name
    start = label.rfind(" (V.")
    if start >= 0 and label.endswith(")"):
        suffix = label[start + 4 : -1]
        number, separator, rarity = suffix.partition(" - ")
        if (
            number
            and number.isascii()
            and number.isdecimal()
            and (not separator or (rarity and "(" not in rarity and ")" not in rarity))
        ):
            label = label[:start]
    if game is Game.ONE_PIECE:
        start = label.rfind(" (")
        if start >= 0 and label.endswith(")"):
            prefix, separator, number = label[start + 2 : -1].partition("-")
            expansion = prefix == "P" or any(
                prefix.startswith(series)
                and len(prefix) == len(series) + 2
                and prefix[len(series) :].isascii()
                and prefix[len(series) :].isdecimal()
                for series in ("OP", "ST", "EB", "PRB")
            )
            if (
                expansion
                and separator
                and len(number) == 3
                and number.isascii()
                and number.isdecimal()
            ):
                label = label[:start]
    if game is Game.POKEMON:
        head, separator, suffix = label.rpartition(" ")
        if separator and suffix[:3].lower() == "lv.":
            level = suffix[3:]
            if level and level.isascii() and level.isdecimal():
                label = head
    return label if label.strip() else name


def _verify_search(
    records: tuple[CatalogProductRecordV1, ...],
    paginator: CatalogPaginator,
    projection: CatalogProjection,
) -> int:
    by_gid = {record.product_gid: record for record in records}
    if len(by_gid) != len(records):
        raise CatalogCoreEvidenceError(_ERROR)
    query_count = 0
    for game in Game:
        scoped = tuple(
            sorted(
                (
                    record
                    for record in records
                    if record.game is game and record.product_family is ProductFamily.SINGLE
                ),
                key=lambda record: _gid_key(record.product_gid),
            )
        )
        report = report_missing_canonical_names(records, game=game)
        expected_missing = tuple(
            (record.product_gid, game, record.publishable)
            for record in scoped
            if record.canonical_card_name is None
        )
        actual_missing = tuple(
            (item.product_gid, item.game, item.publishable) for item in report.missing
        )
        if report.single_record_count != len(scoped) or actual_missing != expected_missing:
            raise CatalogCoreEvidenceError(_ERROR)

        searchable = tuple(
            record
            for record in scoped
            if record.publishable and record.canonical_card_name is not None
        )
        if not searchable:
            raise CatalogCoreEvidenceError(_ERROR)
        facts = tuple(
            (
                record,
                _expected_normalized_name(record.canonical_card_name or ""),
                tuple(
                    _expected_normalized_name(code)
                    for variant in record.variants
                    for code in (variant.sku, variant.barcode)
                    if code
                )
                + (
                    (_expected_normalized_name(record.card_metadata.collector_number),)
                    if record.card_metadata is not None
                    and record.card_metadata.collector_number is not None
                    else ()
                ),
                any(variant.inventory_quantity > 0 for variant in record.variants),
            )
            for record in searchable
        )
        samples = [facts[index] for index in sorted({0, len(facts) // 2, len(facts) - 1})]
        queries = {name[:256] for _, name, _, _ in samples}
        queries.update(name[-4:] for _, name, _, _ in samples)
        queries.update(code[:256] for _, _, codes, _ in samples for code in codes[:1])
        queries.update(
            code.replace("-", "")[:256] for _, _, codes, _ in samples for code in codes[:1]
        )
        queries.update(
            _expected_normalized_name(record.card_metadata.collector_number)[:256]
            for record, _, _, _ in samples
            if record.card_metadata is not None and record.card_metadata.collector_number
        )
        for raw_query in sorted(queries):
            query = _expected_normalized_name(raw_query)
            compact_code_query = query.replace("-", "")
            if not query:
                continue
            for stock in (None, False, True):
                request = replace(
                    _request(game, RequestFamily.SINGLE),
                    query=raw_query,
                    filters=CatalogFiltersV1(in_stock=stock, product_subtype=None),
                )
                expected = [
                    fact
                    for fact in facts
                    if (
                        query in fact[1]
                        or any(
                            query in code
                            or (compact_code_query and compact_code_query in code.replace("-", ""))
                            for code in fact[2]
                        )
                    )
                    and (stock is None or fact[3] is stock)
                ]
                actual_gids: list[str] = []
                cursor = None
                for _ in range(max(1, (len(expected) + _PAGE_SIZE - 1) // _PAGE_SIZE)):
                    page = paginator.fetch_page(request, cursor=cursor)
                    actual_gids.extend(item.product_gid for item in page.page.items)
                    cursor = page.next_cursor
                    if cursor is None:
                        break
                if cursor is not None or actual_gids != [fact[0].product_gid for fact in expected]:
                    raise CatalogCoreEvidenceError(_ERROR)
                groups: dict[str, list[tuple[str, bool]]] = {}
                for record, _, _, available in expected:
                    label = _expected_suggestion_label(record.canonical_card_name or "", game)
                    groups.setdefault(_expected_normalized_name(label), []).append(
                        (label, available)
                    )
                names = sorted(
                    groups,
                    key=lambda name: (
                        0 if name == query else 1 if name.startswith(query) else 2,
                        name,
                    ),
                )[:10]
                expected_suggestions = tuple(
                    (
                        min(name for name, _ in groups[key]),
                        key,
                        len(groups[key]),
                        sum(available for _, available in groups[key]),
                    )
                    for key in names
                )
                suggestions = projection.suggest(request, limit=10)
                if (
                    tuple(
                        (
                            s.canonical_card_name,
                            s.normalized_card_name,
                            s.print_count,
                            s.available_print_count,
                        )
                        for s in suggestions
                    )
                    != expected_suggestions
                ):
                    raise CatalogCoreEvidenceError(_ERROR)
                query_count += 1
    return query_count


def _facet(
    evaluation: FacetEvaluation,
    dimension: FacetDimension,
) -> tuple[tuple[tuple[str, int], ...], int]:
    selected = tuple(facet for facet in evaluation.facets if facet.dimension is dimension)
    if len(selected) != 1:
        raise CatalogCoreEvidenceError(_ERROR)
    facet = selected[0]
    return tuple((item.value, item.count) for item in facet.values), facet.missing_value_count


def _verify_facets(records: tuple[CatalogProductRecordV1, ...]) -> int:
    public_records = tuple(
        record
        for record in records
        if record.publishable and record.product_family is not ProductFamily.UNCLASSIFIED
    )
    items = tuple(CatalogItemV1.from_product_record(record) for record in public_records)
    evaluation_count = 0
    for game in Game:
        game_records = tuple(record for record in public_records if record.game is game)
        family_expected = tuple(
            (family.value, sum(record.product_family is family for record in game_records))
            for family in _PUBLIC_FAMILIES
        )
        for request_family in (RequestFamily.ALL, RequestFamily.SEALED):
            selected_records = (
                game_records
                if request_family is RequestFamily.ALL
                else tuple(
                    record
                    for record in game_records
                    if record.product_family is ProductFamily.SEALED
                )
            )
            evaluation = evaluate_facets(items, _request(game, request_family))
            evaluation_count += 1
            expected_gids = tuple(
                record.product_gid
                for record in sorted(
                    selected_records, key=lambda record: _gid_key(record.product_gid)
                )
            )
            actual_gids = tuple(item.product_gid for item in evaluation.items)
            stock_expected = (
                (
                    "true",
                    sum(
                        any(variant.inventory_quantity > 0 for variant in record.variants)
                        for record in selected_records
                    ),
                ),
                (
                    "false",
                    sum(
                        not any(variant.inventory_quantity > 0 for variant in record.variants)
                        for record in selected_records
                    ),
                ),
            )
            family_actual, family_missing = _facet(evaluation, FacetDimension.PRODUCT_FAMILY)
            stock_actual, stock_missing = _facet(evaluation, FacetDimension.IN_STOCK)
            if (
                actual_gids != expected_gids
                or family_actual != family_expected
                or stock_actual != stock_expected
                or family_missing != 0
                or stock_missing != 0
            ):
                raise CatalogCoreEvidenceError(_ERROR)
            if request_family is RequestFamily.SEALED:
                subtype_names = sorted(
                    {
                        record.product_subtype
                        for record in selected_records
                        if record.product_subtype is not None
                    }
                )
                subtype_expected = tuple(
                    (
                        subtype,
                        sum(record.product_subtype == subtype for record in selected_records),
                    )
                    for subtype in subtype_names
                )
                subtype_actual, subtype_missing = _facet(evaluation, FacetDimension.PRODUCT_SUBTYPE)
                if subtype_actual != subtype_expected or subtype_missing != sum(
                    record.product_subtype is None for record in selected_records
                ):
                    raise CatalogCoreEvidenceError(_ERROR)
    return evaluation_count


def _verify_sync(
    verified: VerifiedReconciledGenerationV1,
    shop_domain: str,
) -> None:
    calls = {"validator": 0, "projector": 0, "activation": 0}

    def validator(*_args: object) -> object:
        calls["validator"] += 1
        raise AssertionError

    def projector(*_args: object) -> object:
        calls["projector"] += 1
        raise AssertionError

    def activation(*_args: object) -> None:
        calls["activation"] += 1
        raise AssertionError

    generation = verified.generation
    manifest = generation.dataset_manifest
    core = SyncCore(
        expected_shop_domain=shop_domain,
        initial_reconciled_generation=generation,
        validator=validator,
        projector=projector,
        activation_probe=activation,
    )
    active = core.active_dataset()
    variant_count = sum(len(record.variants) for record in generation.records)
    identity_count = sum(record.powertools_source_id is not None for record in generation.records)
    public_count = sum(
        record.publishable and record.product_family is not ProductFamily.UNCLASSIFIED
        for record in generation.records
    )
    unclassified_count = sum(
        record.product_family is ProductFamily.UNCLASSIFIED for record in generation.records
    )
    if (
        any(calls.values())
        or active.shop_domain != shop_domain
        or active.source_cut_at != generation.source_manifest.capture_completed_at
        or active.dataset_generation != manifest.dataset_generation
        or active.base_dataset_generation != manifest.dataset_generation
        or active.parent_dataset_generation is not None
        or active.catalog_content_sha256 != manifest.catalog_content_sha256
        or active.taxonomy_rule_version != manifest.taxonomy_rule_version
        or active.built_at != manifest.generated_at
        or active.applied_event_count != 0
        or active.last_event_identity_sha256 is not None
        or active.product_status_counts != manifest.included_product_status_counts
        or active.records != generation.records
        or active.product_count != len(generation.records)
        or active.product_count != manifest.included_product_count
        or active.variant_count != variant_count
        or active.variant_count != manifest.included_variant_count
        or active.source_identity_product_count != identity_count
        or active.source_identity_product_count != manifest.included_source_identity_product_count
        or active.public_item_count != public_count
        or active.public_item_count != manifest.public_item_count
        or active.product_family_counts != manifest.product_family_counts
        or unclassified_count != manifest.unclassified_product_count
        or dict(active.product_family_counts)[ProductFamily.UNCLASSIFIED.value]
        != unclassified_count
    ):
        raise CatalogCoreEvidenceError(_ERROR)


def _new_evidence(
    *,
    shop_domain: str,
    summary_sha256: str,
    dataset_generation: str,
    catalog_content_sha256: str,
    projection_fingerprint: str,
    code_sha: str,
) -> VerifiedCatalogCoreEvidenceV1:
    evidence = object.__new__(VerifiedCatalogCoreEvidenceV1)
    object.__setattr__(evidence, "shop_domain", shop_domain)
    object.__setattr__(evidence, "summary_sha256", summary_sha256)
    object.__setattr__(evidence, "dataset_generation", dataset_generation)
    object.__setattr__(evidence, "catalog_content_sha256", catalog_content_sha256)
    object.__setattr__(evidence, "projection_fingerprint", projection_fingerprint)
    object.__setattr__(evidence, "code_sha", code_sha)
    object.__setattr__(evidence, "verification_version", CORE_VERIFICATION_VERSION)
    return evidence


def _remove_projection(path: Path) -> None:
    mode = stat.S_IMODE(path.stat(follow_symlinks=False).st_mode)
    path.chmod(mode | stat.S_IWUSR)
    path.unlink()


def _verify(
    verified: VerifiedReconciledGenerationV1,
    projection_path: Path,
    code_sha: str,
    *,
    retain_projection: bool = False,
    incremental_core: SyncCore | None = None,
) -> _VerificationResult:
    if type(retain_projection) is not bool:
        raise CatalogCoreEvidenceError(_ERROR)
    if type(verified) is not VerifiedReconciledGenerationV1:
        raise CatalogCoreEvidenceError(_ERROR)
    if type(projection_path) is not _CONCRETE_PATH_TYPE or not projection_path.is_absolute():
        raise CatalogCoreEvidenceError(_ERROR)
    resolved_projection = projection_path.resolve()
    if (
        projection_path != resolved_projection
        or resolved_projection == REPOSITORY_ROOT
        or resolved_projection.is_relative_to(REPOSITORY_ROOT)
        or projection_path.exists()
    ):
        raise CatalogCoreEvidenceError(_ERROR)
    if type(code_sha) is not str or _CODE_SHA_PATTERN.fullmatch(code_sha) is None:
        raise CatalogCoreEvidenceError(_ERROR)

    checked = VerifiedReconciledGenerationV1(
        generation=verified.generation,
        summary_sha256=verified.summary_sha256,
    )

    generation = checked.generation
    manifest = generation.dataset_manifest
    view = None
    summary_sha256 = checked.summary_sha256
    if incremental_core is not None:
        if type(incremental_core) is not SyncCore:
            raise CatalogCoreEvidenceError(_ERROR)
        view, manifest = incremental_core.publication_snapshot(manifest)
        summary_sha256 = hashlib.sha256(
            json.dumps(
                {
                    "domain": "nla-incremental-proof-v1",
                    "baseSummary": checked.summary_sha256,
                    "manifest": manifest.as_dict(),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
    records = generation.records if view is None else view.records
    expected_by_request = _expected_pagination(records)
    parts = generation.source_manifest.parts
    if type(parts) is not tuple or len(parts) != 2:
        raise CatalogCoreEvidenceError(_ERROR)
    shop_domain = parts[0].shop_domain
    if view is not None and view.shop_domain != shop_domain:
        raise CatalogCoreEvidenceError(_ERROR)

    projection = None
    completed = False
    try:
        started = time.perf_counter_ns()
        projection = build_catalog_projection(
            projection_path,
            manifest=manifest,
            records=records,
        )
        projection_build_nanoseconds = time.perf_counter_ns() - started
        paginator = CatalogPaginator(
            AtomicCatalogActivation(projection),
            CursorCodecV1(secrets.token_bytes(32), ttl_seconds=86_400),
        )
        started = time.perf_counter_ns()
        pagination_page_count = _verify_pagination(paginator, expected_by_request)
        pagination_traversal_nanoseconds = time.perf_counter_ns() - started
        started = time.perf_counter_ns()
        search_query_count = _verify_search(records, paginator, projection)
        search_query_nanoseconds = time.perf_counter_ns() - started
        started = time.perf_counter_ns()
        facet_evaluation_count = _verify_facets(records)
        facet_evaluation_nanoseconds = time.perf_counter_ns() - started
        started = time.perf_counter_ns()
        _verify_sync(checked, shop_domain)
        if incremental_core is not None and incremental_core.publication_snapshot(
            generation.dataset_manifest
        ) != (view, manifest):
            raise CatalogCoreEvidenceError(_ERROR)
        sync_bootstrap_nanoseconds = time.perf_counter_ns() - started
        reopened = type(projection).open(
            projection.path,
            expected_generation=projection.dataset_generation,
        )
        if reopened._file_fingerprint != projection._file_fingerprint:
            raise CatalogCoreEvidenceError(_ERROR)
        fingerprint = reopened._file_fingerprint.content_sha256
        result = _VerificationResult(
            evidence=_new_evidence(
                shop_domain=shop_domain,
                summary_sha256=summary_sha256,
                dataset_generation=manifest.dataset_generation,
                catalog_content_sha256=manifest.catalog_content_sha256,
                projection_fingerprint=fingerprint,
                code_sha=code_sha,
            ),
            measurements=_OperationalMeasurements(
                projection_build_nanoseconds=projection_build_nanoseconds,
                pagination_traversal_nanoseconds=pagination_traversal_nanoseconds,
                search_query_nanoseconds=search_query_nanoseconds,
                facet_evaluation_nanoseconds=facet_evaluation_nanoseconds,
                sync_bootstrap_nanoseconds=sync_bootstrap_nanoseconds,
                pagination_page_count=pagination_page_count,
                search_query_count=search_query_count,
                facet_evaluation_count=facet_evaluation_count,
            ),
            projection=reopened if retain_projection else None,
        )
        completed = True
        return result
    finally:
        if projection is not None and not (retain_projection and completed):
            _remove_projection(projection.path)


def _verify_with_measurements(
    verified: VerifiedReconciledGenerationV1,
    *,
    projection_path: Path,
    code_sha: str,
    retain_projection: bool = False,
    incremental_core: SyncCore | None = None,
) -> _VerificationResult:
    """Optionally hand the exact successful projection to its packaging owner.

    Failed proofs still remove their projection. The owner must clean retained
    output if a later packaging step fails; standalone proof stays ephemeral.
    """
    try:
        options = {} if incremental_core is None else {"incremental_core": incremental_core}
        result = _verify(
            verified, projection_path, code_sha, retain_projection=retain_projection, **options
        )
    except Exception:
        rejected = True
    else:
        rejected = False
    if rejected:
        # Raise outside the handler so the public exception retains no nested
        # value-bearing failure through ``__context__``.
        raise CatalogCoreEvidenceError(_ERROR)
    return result


def verify_catalog_core_evidence(
    verified: VerifiedReconciledGenerationV1,
    *,
    projection_path: Path,
    code_sha: str,
) -> VerifiedCatalogCoreEvidenceV1:
    """Exercise pagination, search, facets, and sync without promoting output."""

    return _verify_with_measurements(
        verified,
        projection_path=projection_path,
        code_sha=code_sha,
    ).evidence


__all__ = [
    "CatalogCoreEvidenceError",
    "VerifiedCatalogCoreEvidenceV1",
    "verify_catalog_core_evidence",
]
