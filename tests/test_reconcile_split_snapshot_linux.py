"""Real Linux reconciliation; no simulated Windows filesystem or Shopify calls."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from scripts import reconcile_split_snapshot as cli
from scripts.package_staging_generation import run_packaging

import test_reconcile_split_snapshot as fixtures
from nla_catalog_gateway.canonical_names import (
    CANONICAL_GAME_ORDER,
    CSV_HEADER,
    MANIFEST_FILENAME,
    SIDECAR_FILENAME,
    build_canonical_name_sidecar,
)
from nla_catalog_gateway.generation_bundle import open_reconciled_generation
from nla_catalog_gateway.pagination import CursorCodecV1
from nla_catalog_gateway.runtime_api import (
    EvidenceBoundCapabilityGate,
    EvidenceBoundCatalogBackend,
    RequestCancellation,
    RequestControl,
)
from nla_catalog_gateway.runtime_contract import CatalogFiltersV1, CatalogRequestV1, RequestFamily
from nla_catalog_gateway.staging_generation import open_staging_generation
from nla_catalog_gateway.taxonomy import Game


@pytest.fixture
def native_inputs(tmp_path: Path):
    if sys.platform != "linux":
        yield None
        return
    inputs = fixtures.make_inputs(tmp_path)
    try:
        yield inputs
    finally:
        for root, _directories, names in os.walk(tmp_path, followlinks=False):
            Path(root).chmod(0o755)
            for name in names:
                path = Path(root) / name
                if not path.is_symlink():
                    path.chmod(0o644)


def _pin(output: Path) -> str:
    return hashlib.sha256((output / "reconciliation-summary.v2.json").read_bytes()).hexdigest()


def _fd_count() -> int:
    return len(os.listdir("/proc/self/fd"))


def test_native_linux_reconciles_deterministically_and_reopens(native_inputs, tmp_path):
    if native_inputs is None:
        return
    before = _fd_count()
    first, second = tmp_path / "first", tmp_path / "second"
    summary = cli.run_reconciliation(**native_inputs.kwargs(first))
    assert cli.run_reconciliation(**native_inputs.kwargs(second)) == summary
    assert {p.name for p in first.iterdir()} == cli._OUTPUT_FILENAMES
    assert first.stat().st_mode & 0o222 == 0
    for path in first.iterdir():
        assert path.read_bytes() == (second / path.name).read_bytes()
        assert path.stat().st_mode & 0o222 == 0
    with open_reconciled_generation(first, _pin(first)) as verified:
        assert verified.generation.dataset_manifest.included_product_count == 1
        record = verified.generation.records[0]
        assert record.product_gid == fixtures.gid("Product", 9_007_199_254_740_993)
        assert record.total_inventory == record.variants[0].inventory_quantity == 0
        assert record.variants[0].price_text == "0.00"
    assert _fd_count() == before
    assert not tuple(tmp_path.glob(".nla-reconcile-staging-*"))


def _single_card_inputs(inputs, root):
    sources = {}
    products, variants = [], []
    types = {
        Game.MAGIC: "Magic Single",
        Game.POKEMON: "Pokémon Single",
        Game.YUGIOH: "Yu-Gi-Oh! Single",
        Game.ONE_PIECE: "One Piece Single",
    }
    for index, game in enumerate(CANONICAL_GAME_ORDER, start=1):
        source_id = "9007199254745001" if game is Game.MAGIC else str(index)
        name = "Lightning Bolt" if game is Game.MAGIC else f"Unmatched {game.value}"
        product_rows, variant_rows = fixtures.product_rows(), fixtures.variant_rows()
        for rows in (product_rows, variant_rows):
            encoded = json.dumps(rows)
            for number in (
                9_007_199_254_740_993,
                9_007_199_254_741_101,
                9_007_199_254_742_001,
                9_007_199_254_743_001,
            ):
                encoded = encoded.replace(str(number), str(number + index))
            rows[:] = json.loads(encoded)
        product_rows[1]["publication"]["id"] = fixtures.PUBLICATION
        product_rows[0].update(productType=types[game], tags=[game.value], handle=f"card-{index}")
        product_rows[0]["syncProductId"]["value"] = source_id
        product_rows[0]["powertoolsId"]["value"] = source_id
        products.extend(product_rows)
        variants.extend(variant_rows)
        source = root / f"{game.value}.csv"
        source.write_text(
            ",".join(CSV_HEADER)
            + "\n"
            + ",".join((source_id, name, "123", "common", "Synthetic", "SYN", "", ""))
            + "\n",
            encoding="utf-8",
        )
        sources[game] = source
    for rows, path, query, terminal, operation, root_type in (
        (
            products,
            inputs.products_snapshot,
            inputs.products_query,
            inputs.products_terminal,
            1,
            "Product",
        ),
        (
            variants,
            inputs.variants_snapshot,
            inputs.variants_query,
            inputs.variants_terminal,
            2,
            "ProductVariant",
        ),
    ):
        raw = fixtures.write_jsonl(path, rows)
        fixtures.write_json(
            terminal,
            fixtures.terminal_document(
                query=query, raw=raw, rows=rows, operation=operation, root_type=root_type
            ),
        )
    sidecar = root / "names"
    manifest = build_canonical_name_sidecar(
        sources, output_directory=sidecar, generator_code_sha="d" * 40
    )
    expectation = fixtures.canonical_expectation_document(manifest)
    for key in (
        "productCount",
        "variantCount",
        "expectedActiveOnlineStorePublishedProductCount",
        "expectedCanonicalNameProductCount",
    ):
        expectation[key] = 4
    fixtures.write_json(inputs.expectation_path, expectation)
    return {
        "canonical_names_jsonl": sidecar / SIDECAR_FILENAME,
        "canonical_names_manifest": sidecar / MANIFEST_FILENAME,
    }


def _search(backend, game, query):
    request = CatalogRequestV1(
        game=game,
        product_family=RequestFamily.SINGLE,
        query=query,
        filters=CatalogFiltersV1(None, None),
        page_size=100,
    )
    control = RequestControl(30, RequestCancellation(), lambda: 0)
    lease = backend.acquire(control=control, request=request, cursor=None)
    try:
        EvidenceBoundCapabilityGate(backend).require_catalog(lease, request, control=control)
        return lease.fetch_page(request, None, control=control, include_suggestions=True)
    finally:
        lease.close()


def test_native_linux_raw_to_package_serves_name_code_suggestions_and_soldout(
    native_inputs, tmp_path
):
    if native_inputs is None:
        return
    names = _single_card_inputs(native_inputs, tmp_path)
    bundle = tmp_path / "bundle"
    summary = cli.run_reconciliation(**native_inputs.kwargs(bundle), **names)
    assert summary["canonicalNameAudit"]["matchedProductCount"] == 4
    package = tmp_path / "package"
    code = "c" * 40
    pin = run_packaging(bundle, _pin(bundle), code, package)
    reopened = open_staging_generation(package, pin)
    backend = EvidenceBoundCatalogBackend.from_staging_generation(
        reopened,
        CursorCodecV1(b"synthetic-cursor-key" * 2, 1800),
        expected_code_sha=code,
        clock=lambda: datetime(2026, 9, 5, 12, tzinfo=UTC),
    )
    for query in ("Bolt", "Ligh", "123"):
        result = _search(backend, Game.MAGIC, query)
        assert len(result.page.items) == 1
        assert result.page.items[0].variants[0].inventory_quantity == 0
        assert result.suggestions[0].canonical_card_name == "Lightning Bolt"
        assert result.next_cursor is None
    other = _search(backend, Game.POKEMON, "Bolt")
    assert not other.page.items
    assert not other.suggestions


@pytest.mark.parametrize("kind", ["file", "directory", "ancestor", "hardlink", "fifo"])
def test_native_linux_rejects_aliased_or_special_input(native_inputs, tmp_path, kind):
    if native_inputs is None:
        return
    inputs = native_inputs
    path = inputs.products_snapshot
    if kind == "hardlink":
        os.link(path, tmp_path / "other-link")
    elif kind == "fifo":
        path.unlink()
        os.mkfifo(path, 0o600)
    elif kind == "file":
        renamed = path.with_name("retained")
        path.rename(renamed)
        path.symlink_to(renamed)
    else:
        link = tmp_path / "alias"
        link.symlink_to(path.parent if kind == "directory" else tmp_path, target_is_directory=True)
        selected = link / path.name if kind == "directory" else link / "source" / path.name
        inputs = replace(inputs, products_snapshot=selected)
    before = _fd_count()
    output = tmp_path / "rejected"
    with pytest.raises((cli.ReconciliationCliError, OSError)):
        cli.run_reconciliation(**inputs.kwargs(output))
    assert not output.exists()
    assert _fd_count() == before


@pytest.mark.parametrize("target", ["empty", "nonempty", "symlink"])
def test_native_linux_never_overwrites_existing_target(native_inputs, tmp_path, target):
    if native_inputs is None:
        return
    output = tmp_path / "existing"
    retained = tmp_path / "retained"
    retained.mkdir()
    if target == "symlink":
        output.symlink_to(retained, target_is_directory=True)
    else:
        output.mkdir()
        if target == "nonempty":
            (output / "owner-data").write_bytes(b"preserve this")
    before = output.lstat()
    with pytest.raises((cli.ReconciliationCliError, OSError)):
        cli.run_reconciliation(**native_inputs.kwargs(output))
    assert output.lstat().st_ino == before.st_ino
    if target == "nonempty":
        assert (output / "owner-data").read_bytes() == b"preserve this"


def test_native_linux_target_created_at_publish_is_retained(native_inputs, tmp_path, monkeypatch):
    if native_inputs is None:
        return
    output = tmp_path / "collision"
    original = cli._linux_rename_noreplace

    def collide(parent, source, target):
        output.mkdir()
        return original(parent, source, target)

    monkeypatch.setattr(cli, "_linux_rename_noreplace", collide)
    with pytest.raises((cli.ReconciliationCliError, OSError)):
        cli.run_reconciliation(**native_inputs.kwargs(output))
    assert output.is_dir()
    assert not tuple(output.iterdir())
    assert not tuple(tmp_path.glob(".nla-reconcile-staging-*"))


def test_native_linux_changed_input_rejected_even_with_restored_mtime(
    native_inputs, tmp_path, monkeypatch
):
    if native_inputs is None:
        return
    original = cli.reconcile_snapshot_parts

    def reconcile_then_modify(*args, **kwargs):
        result = original(*args, **kwargs)
        path = native_inputs.products_snapshot
        before = path.stat()
        path.write_bytes(path.read_bytes())
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        assert path.stat().st_ctime_ns != before.st_ctime_ns
        return result

    monkeypatch.setattr(cli, "reconcile_snapshot_parts", reconcile_then_modify)
    output = tmp_path / "rejected"
    before = _fd_count()
    with pytest.raises((cli.ReconciliationCliError, OSError)):
        cli.run_reconciliation(**native_inputs.kwargs(output))
    assert not output.exists()
    assert _fd_count() == before


@pytest.mark.parametrize("failure", ["write", "pre-rename", "post-rename"])
def test_native_linux_output_failure_does_not_report_success(
    native_inputs, tmp_path, monkeypatch, failure
):
    if native_inputs is None:
        return
    output = tmp_path / "generation"
    original_fsync, original_rename = os.fsync, cli._linux_rename_noreplace
    published = False

    def rename(parent, source, target):
        nonlocal published
        if failure == "pre-rename":
            raise OSError("synthetic secret marker")
        original_rename(parent, source, target)
        published = True

    def fsync(descriptor):
        if (failure == "write" and stat.S_ISREG(os.fstat(descriptor).st_mode)) or (
            failure == "post-rename" and published
        ):
            raise OSError("synthetic secret marker")
        return original_fsync(descriptor)

    monkeypatch.setattr(cli, "_linux_rename_noreplace", rename)
    monkeypatch.setattr(cli.os, "fsync", fsync)
    before = _fd_count()
    with pytest.raises((cli.ReconciliationCliError, OSError)):
        cli.run_reconciliation(**native_inputs.kwargs(output))
    assert _fd_count() == before
    if failure != "post-rename":
        assert not output.exists()
        assert not tuple(tmp_path.glob(".nla-reconcile-staging-*"))
    elif output.exists():
        assert {p.name for p in output.iterdir()} == cli._OUTPUT_FILENAMES


def test_native_linux_cli_redacts_failure_and_returns_safe_success(native_inputs, tmp_path, capsys):
    if native_inputs is None:
        return
    output = tmp_path / "cli"
    assert cli.main(native_inputs.argv(output)) == 0
    captured = capsys.readouterr()
    receipt = json.loads(captured.out)
    assert receipt["status"] == "ok"
    assert receipt["summarySha256"] == _pin(output)
    assert captured.err == ""
    assert cli.main(native_inputs.argv(output)) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "split snapshot reconciliation failed\n"


@pytest.mark.parametrize("kind", ["artifact", "staging-directory"])
def test_native_linux_preserves_foreign_replacements(native_inputs, tmp_path, monkeypatch, kind):
    if native_inputs is None:
        return
    original = cli._linux_verify_output
    retained = tmp_path / "retained-own-artifact"
    foreign = None

    def replace_after_verify(directory, created):
        nonlocal foreign
        original(directory, created)
        staging = created[0].path.parent
        staging.chmod(0o700)
        if kind == "artifact":
            foreign = created[0].path
            foreign.rename(retained)
            foreign.write_bytes(b"foreign replacement must remain")
        else:
            staging.rename(retained)
            staging.mkdir()
            foreign = staging / "owner-data"
            foreign.write_bytes(b"foreign replacement must remain")
        raise OSError("synthetic interrupted publisher")

    monkeypatch.setattr(cli, "_linux_verify_output", replace_after_verify)
    before = _fd_count()
    with pytest.raises(cli.ReconciliationCliError):
        cli.run_reconciliation(**native_inputs.kwargs(tmp_path / "not-published"))
    assert foreign is not None
    assert foreign.read_bytes() == b"foreign replacement must remain"
    assert retained.exists()
    assert not (tmp_path / "not-published").exists()
    assert _fd_count() == before


def test_native_linux_replaced_staging_name_is_not_published(native_inputs, tmp_path, monkeypatch):
    if native_inputs is None:
        return
    original = cli._linux_verify_output
    stage = None
    retained = tmp_path / "moved-staging"

    def replace_after_verify(directory, created):
        nonlocal stage
        original(directory, created)
        stage = created[0].path.parent
        stage.rename(retained)
        stage.mkdir()
        (stage / "foreign").write_bytes(b"untouched")

    monkeypatch.setattr(cli, "_linux_verify_output", replace_after_verify)
    target = tmp_path / "not-published"
    with pytest.raises(cli.ReconciliationCliError):
        cli.run_reconciliation(**native_inputs.kwargs(target))
    assert not target.exists()
    assert stage is not None
    assert (stage / "foreign").read_bytes() == b"untouched"
    assert retained.is_dir()


@pytest.mark.parametrize("change", ["partial", "wrong-count", "signed-url"])
def test_native_linux_rejects_invalid_snapshot_evidence(native_inputs, tmp_path, change):
    if native_inputs is None:
        return
    terminal = json.loads(native_inputs.products_terminal.read_bytes())
    if change == "partial":
        terminal["partialDataUrlPresent"] = True
    elif change == "signed-url":
        terminal["url"] = "https://example.invalid/private-capability"
    else:
        terminal["rootObjectCount"] += 1
    fixtures.write_json(native_inputs.products_terminal, terminal)
    output = tmp_path / "invalid-evidence"
    with pytest.raises(ValueError):
        cli.run_reconciliation(**native_inputs.kwargs(output))
    assert not output.exists()


def _artifact_set(directory):
    created = []
    with cli._linux_directory(directory, external=True) as descriptor:
        for name in sorted(cli._OUTPUT_FILENAMES):
            cli._linux_write_artifact(descriptor, directory / name, (b"synthetic\n",), created)
    return created


@pytest.mark.parametrize(
    "change",
    ["none", "extra", "missing", "unregistered", "writable", "hash", "size", "handle", "read"],
)
def test_native_linux_output_attestation(native_inputs, tmp_path, monkeypatch, change):
    if native_inputs is None:
        return
    directory = tmp_path / "artifacts"
    directory.mkdir()
    created = _artifact_set(directory)
    first = created[0]
    if change == "extra":
        (directory / "unexpected").write_bytes(b"extra")
    elif change == "missing":
        first.path.unlink()
    elif change == "unregistered":
        created.pop()
    elif change == "writable":
        first.path.chmod(0o644)
    elif change == "hash":
        first.expected_sha256 = "0" * 64
    elif change == "size":
        first.expected_byte_count += 1
    elif change == "handle":
        original = cli._linux_state
        calls = 0

        def wrong_handle(facts):
            nonlocal calls
            calls += 1
            return original(facts) if calls != 2 else (0,)

        monkeypatch.setattr(cli, "_linux_state", wrong_handle)
    elif change == "read":
        original = os.read

        def changed_read(descriptor, count):
            raw = original(descriptor, count)
            return b"altered" if raw else raw

        monkeypatch.setattr(cli.os, "read", changed_read)
    before = _fd_count()
    with cli._linux_directory(directory, external=True) as descriptor:
        if change == "none":
            with os.scandir(descriptor) as entries:
                assert len(tuple(entries)) == 7
            cli._linux_verify_output(descriptor, created)
            cli._linux_verify_output(descriptor, created)
        else:
            with pytest.raises(cli.ReconciliationCliError):
                cli._linux_verify_output(descriptor, created)
    assert _fd_count() == before


@pytest.mark.parametrize("change", ["mode", "owner", "root", "late-mode", "count", "published"])
def test_native_linux_publication_guards(native_inputs, tmp_path, monkeypatch, change):
    if native_inputs is None:
        return
    output = tmp_path / "not-published"
    if change == "root":
        output = Path("/")
    elif change == "mode":
        tmp_path.chmod(0o777)
    elif change == "owner":
        original = os.geteuid()
        monkeypatch.setattr(cli.os, "geteuid", lambda: original + 1)
    elif change == "late-mode":
        original = cli._linux_verify_output

        def change_parent(directory, created):
            original(directory, created)
            tmp_path.chmod(0o777)

        monkeypatch.setattr(cli, "_linux_verify_output", change_parent)
    elif change == "count":
        original = cli._linux_write_artifact

        def wrong_count(directory, path, chunks, created):
            result = original(directory, path, chunks, created)
            return replace(result, record_count=2) if path.suffix == ".jsonl" else result

        monkeypatch.setattr(cli, "_linux_write_artifact", wrong_count)
    else:
        original = cli._linux_rename_noreplace

        def replace_published(parent, source, target):
            original(parent, source, target)
            output.rename(tmp_path / "retained-published")
            output.mkdir()
            (output / "foreign").write_bytes(b"preserve")

        monkeypatch.setattr(cli, "_linux_rename_noreplace", replace_published)
    before = _fd_count()
    with pytest.raises(cli.ReconciliationCliError):
        cli.run_reconciliation(**native_inputs.kwargs(output))
    assert _fd_count() == before
    if change == "published":
        assert (output / "foreign").read_bytes() == b"preserve"
    elif change != "root":
        assert not output.exists()


@pytest.mark.parametrize("change", ["none", "foreign-name", "foreign-handle", "late-name"])
def test_native_linux_cleanup_only_owns_observed_directory(
    native_inputs, tmp_path, monkeypatch, change
):
    if native_inputs is None:
        return
    stage = tmp_path / "stage"
    stage.mkdir()
    created = _artifact_set(stage)
    facts = stage.stat()
    identity = cli._FileIdentity(facts.st_dev, facts.st_ino)
    before = _fd_count()
    with (
        cli._linux_directory(tmp_path, external=True) as parent,
        cli._linux_directory(stage, external=True) as directory,
    ):
        if change == "foreign-name":
            stage.rename(tmp_path / "retained")
            stage.mkdir()
        elif change == "foreign-handle":
            identity = replace(identity, inode=identity.inode + 1)
        elif change == "late-name":
            original = os.stat
            calls = 0

            def swap_at_last_stat(path, *args, **kwargs):
                nonlocal calls
                if path == "stage":
                    calls += 1
                    if calls == 2:
                        stage.rename(tmp_path / "retained")
                        stage.mkdir()
                return original(path, *args, **kwargs)

            monkeypatch.setattr(cli.os, "stat", swap_at_last_stat)
        if change == "none":
            cli._linux_cleanup_output(parent, directory, identity, "stage", "target", created)
            assert not stage.exists()
        else:
            with pytest.raises(cli.ReconciliationCliError):
                cli._linux_cleanup_output(parent, directory, identity, "stage", "target", created)
            assert stage.exists()
    assert _fd_count() == before
