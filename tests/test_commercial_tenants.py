from __future__ import annotations

import json
import os
import stat
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace

import pytest

from nla_catalog_gateway.commercial import tenants
from nla_catalog_gateway.commercial.tenants import (
    TenantIdentity,
    TenantProvisionError,
    provision_tenant,
)


@pytest.fixture
def private_root(tmp_path: Path) -> Path:
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    return root


def _identity(number: int = 101, domain: str = "alpha") -> TenantIdentity:
    return TenantIdentity(f"{domain}.myshopify.com", f"gid://shopify/Shop/{number}")


def test_canonical_identity_and_stable_immutable_key() -> None:
    identity = TenantIdentity("ALPHA.myshopify.com", "gid://shopify/Shop/101")
    assert identity == _identity()
    assert identity.tenant_key == "shop-101"
    with pytest.raises(FrozenInstanceError):
        identity.shop_domain = "beta.myshopify.com"


@pytest.mark.parametrize(
    "domain",
    [
        None,
        1,
        "",
        "../alpha.myshopify.com",
        "alpha.com",
        " alpha.myshopify.com",
        "alpha.myshopify.com\n",
        "https://alpha.myshopify.com",
        "alpha.myshopify.com:443",
        "alpha.myshopify.com/path",
        "alpha.myshopify.com.",
        "a.b.myshopify.com",
        "alpha.myshopify.com@evil.test",
        "a_b.myshopify.com",
        "é.myshopify.com",
        "-alpha.myshopify.com",
        "alpha-.myshopify.com",
        "a" * 64 + ".myshopify.com",
    ],
)
def test_rejects_noncanonical_shop_input(domain) -> None:
    with pytest.raises(TenantProvisionError):
        TenantIdentity(domain, "gid://shopify/Shop/101")


@pytest.mark.parametrize(
    "gid",
    [
        None,
        1,
        "",
        "gid://shopify/Product/101",
        "gid://shopify/Shop/0",
        "gid://shopify/Shop/01",
        "gid://shopify/Shop/-1",
        "gid://shopify/Shop/1\n",
        "gid://shopify/Shop/1/../2",
        "gid://shopify/Shop/" + "1" * 21,
    ],
)
def test_rejects_invalid_shop_gid(gid) -> None:
    with pytest.raises(TenantProvisionError):
        TenantIdentity("alpha.myshopify.com", gid)


@pytest.mark.parametrize("authorized", [False, True])
def test_private_two_shop_provisioning_and_exact_idempotency(
    private_root: Path, authorized
) -> None:
    first = provision_tenant(private_root, _identity(), importer_authorized=authorized)
    second = provision_tenant(private_root, _identity(202, "beta"))
    assert first.root == private_root / "shop-101"
    assert second.root == private_root / "shop-202"
    assert first.root != second.root
    assert first.catalog_dir == first.root / "catalog"
    assert first.importer_dir == first.root / "importer"
    assert first.state_dir == first.root / "state"
    before = first.manifest_path.stat()
    expected = {
        "schema_version": 1,
        "shop_domain": "alpha.myshopify.com",
        "shop_gid": "gid://shopify/Shop/101",
        "importer_authorized": authorized,
    }
    assert json.loads(first.manifest_path.read_text()) == expected
    (first.catalog_dir / "merchant-owned.txt").write_text("preserve")
    again = provision_tenant(private_root, _identity(), importer_authorized=authorized)
    assert first == again
    assert first.manifest_path.stat().st_mtime_ns == before.st_mtime_ns
    assert (first.catalog_dir / "merchant-owned.txt").read_text() == "preserve"
    assert not list(second.catalog_dir.iterdir())
    assert not second.importer_authorized
    if os.name != "nt":
        assert stat.S_IMODE(first.root.stat().st_mode) == 0o700
        assert stat.S_IMODE(first.manifest_path.stat().st_mode) == 0o600


def test_binding_and_consent_cannot_be_rewritten(private_root: Path) -> None:
    original = provision_tenant(private_root, _identity())
    raw = original.manifest_path.read_bytes()
    for identity, consent in [(_identity(101, "beta"), False), (_identity(), True)]:
        with pytest.raises(TenantProvisionError):
            provision_tenant(private_root, identity, importer_authorized=consent)
        assert original.manifest_path.read_bytes() == raw


@pytest.mark.parametrize(
    "identity, consent",
    [(None, False), ({}, False), (_identity(), 1), (_identity(), "yes"), (_identity(), None)],
)
def test_requires_typed_identity_and_explicit_boolean(
    private_root: Path, identity, consent
) -> None:
    with pytest.raises(TenantProvisionError):
        provision_tenant(private_root, identity, importer_authorized=consent)
    assert not list(private_root.iterdir())


def test_forged_identity_is_revalidated(private_root: Path) -> None:
    identity = _identity()
    object.__setattr__(identity, "shop_gid", "../../escape")
    with pytest.raises(TenantProvisionError):
        provision_tenant(private_root, identity)


@pytest.mark.parametrize("root", ["relative", Path("relative"), None])
def test_requires_absolute_concrete_private_path(root) -> None:
    with pytest.raises(TenantProvisionError):
        provision_tenant(root, _identity())


def test_rejects_nonconcrete_path_subclass(private_root: Path) -> None:
    class DeceptivePath(type(Path())):
        pass

    with pytest.raises(TenantProvisionError):
        provision_tenant(DeceptivePath(private_root), _identity())


@pytest.mark.parametrize("checkout", ["checkout", Path("relative")])
def test_invalid_checkout_root(private_root: Path, checkout) -> None:
    with pytest.raises(TenantProvisionError):
        provision_tenant(private_root, _identity(), checkout_root=checkout)


def test_checkout_and_ancestor_storage_are_refused(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir(mode=0o700)
    nested = checkout / "data"
    nested.mkdir(mode=0o700)
    for root in (checkout, nested, tmp_path):
        with pytest.raises(TenantProvisionError):
            provision_tenant(root, _identity(), checkout_root=checkout)
    with pytest.raises(TenantProvisionError):
        provision_tenant(tenants._CHECKOUT_ROOT, _identity(), checkout_root=tmp_path)


def test_explicit_external_checkout_and_traversal(private_root: Path, tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    assert (
        provision_tenant(private_root, _identity(), checkout_root=checkout).identity == _identity()
    )
    with pytest.raises(TenantProvisionError):
        provision_tenant(private_root / ".." / "outside", _identity())


def test_missing_root_and_regular_file_ancestors_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(TenantProvisionError):
        provision_tenant(tmp_path / "absent", _identity())
    file = tmp_path / "not-a-directory"
    file.write_text("do not overwrite")
    with pytest.raises(TenantProvisionError):
        provision_tenant(file / "child", _identity())
    assert file.read_text() == "do not overwrite"


def test_file_where_tenant_directory_expected(private_root: Path) -> None:
    path = private_root / _identity().tenant_key
    path.write_text("do not overwrite")
    with pytest.raises(TenantProvisionError):
        provision_tenant(private_root, _identity())
    assert path.read_text() == "do not overwrite"


@pytest.mark.parametrize("content", ["", "not json", "{}", "x" * 6000])
def test_corrupted_or_secret_injected_manifest_not_replaced(private_root: Path, content) -> None:
    workspace = provision_tenant(private_root, _identity())
    workspace.manifest_path.write_text(content)
    with pytest.raises(TenantProvisionError):
        provision_tenant(private_root, _identity())
    assert workspace.manifest_path.read_text() == content


@pytest.mark.parametrize("entry", ["state", "importer", "catalog", "tenant.json"])
def test_incomplete_provisioning_stays_incomplete(private_root: Path, entry) -> None:
    root = private_root / _identity().tenant_key
    root.mkdir(mode=0o700)
    if entry == "tenant.json":
        (root / entry).write_text("untrusted")
    else:
        (root / entry).mkdir(mode=0o700)
    with pytest.raises(TenantProvisionError):
        provision_tenant(private_root, _identity())
    assert {item.name for item in root.iterdir()} == {entry}


def test_unknown_existing_root_content_is_preserved(private_root: Path) -> None:
    workspace = provision_tenant(private_root, _identity())
    extra = workspace.root / "unexpected.txt"
    extra.write_text("preserve")
    with pytest.raises(TenantProvisionError):
        provision_tenant(private_root, _identity())
    assert extra.read_text() == "preserve"


def test_manifest_must_be_regular_not_a_directory(private_root: Path) -> None:
    workspace = provision_tenant(private_root, _identity())
    workspace.manifest_path.unlink()
    workspace.manifest_path.mkdir()
    with pytest.raises(TenantProvisionError):
        provision_tenant(private_root, _identity())


def test_hardlinked_manifest_is_not_trusted(private_root: Path, tmp_path: Path) -> None:
    workspace = provision_tenant(private_root, _identity())
    os.link(workspace.manifest_path, tmp_path / "linked-manifest")
    with pytest.raises(TenantProvisionError):
        provision_tenant(private_root, _identity())


def test_symlink_ancestors_and_workspace_entries(private_root: Path, tmp_path: Path) -> None:
    if os.name == "nt":
        return  # Native POSIX link cases run on Linux CI; junction bit is covered below.
    alias = tmp_path / "alias"
    alias.symlink_to(private_root, target_is_directory=True)
    with pytest.raises(TenantProvisionError):
        provision_tenant(alias, _identity())
    workspace = provision_tenant(private_root, _identity())
    workspace.state_dir.rmdir()
    workspace.state_dir.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(TenantProvisionError):
        provision_tenant(private_root, _identity())
    workspace.state_dir.unlink()
    workspace.state_dir.mkdir(mode=0o700)
    outside = tmp_path / "outside.json"
    outside.write_bytes(workspace.manifest_path.read_bytes())
    workspace.manifest_path.unlink()
    workspace.manifest_path.symlink_to(outside)
    with pytest.raises(TenantProvisionError):
        provision_tenant(private_root, _identity())


def test_reparse_point_rejection_even_for_existing_directory(
    private_root: Path, monkeypatch
) -> None:
    original = Path.lstat

    def reparse(path):
        if path == private_root:
            return SimpleNamespace(
                st_mode=stat.S_IFDIR | 0o700, st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT
            )
        return original(path)

    monkeypatch.setattr(Path, "lstat", reparse)
    with pytest.raises(TenantProvisionError):
        provision_tenant(private_root, _identity())
    assert not list(private_root.iterdir())


def test_noncanonical_resolved_root_is_refused(private_root: Path, monkeypatch) -> None:
    original = Path.resolve

    def redirected(path, *args, **kwargs):
        return (
            private_root / "redirected" if path == private_root else original(path, *args, **kwargs)
        )

    monkeypatch.setattr(Path, "resolve", redirected)
    with pytest.raises(TenantProvisionError):
        provision_tenant(private_root, _identity())


def test_posix_ownership_and_permissions_are_required(monkeypatch) -> None:
    monkeypatch.setattr(tenants, "_WINDOWS", False)
    monkeypatch.setattr(os, "getuid", lambda: 123, raising=False)
    tenants._assert_private(SimpleNamespace(st_uid=123, st_mode=stat.S_IFDIR | 0o700))
    for uid, mode in [(456, 0o700), (123, 0o755), (123, 0o770)]:
        with pytest.raises(TenantProvisionError):
            tenants._assert_private(SimpleNamespace(st_uid=uid, st_mode=stat.S_IFDIR | mode))
    monkeypatch.setattr(tenants, "_WINDOWS", True)
    tenants._assert_private(SimpleNamespace(st_uid=456, st_mode=stat.S_IFDIR | 0o777))


def test_manifest_replacement_between_lstat_and_open_is_rejected(private_root: Path, monkeypatch):
    workspace = provision_tenant(private_root, _identity())
    original = os.fstat

    def different_inode(descriptor):
        facts = original(descriptor)
        return SimpleNamespace(st_dev=facts.st_dev, st_ino=facts.st_ino + 1)

    monkeypatch.setattr(os, "fstat", different_inode)
    with pytest.raises(TenantProvisionError):
        provision_tenant(private_root, _identity())
    assert workspace.manifest_path.is_file()


def test_exclusive_manifest_write_never_overwrites_a_preexisting_file(
    private_root: Path, monkeypatch
):
    original = Path.mkdir
    target = private_root / "shop-101"

    def injected(path, *args, **kwargs):
        result = original(path, *args, **kwargs)
        if path.name == "state" and path.parent == target:
            (target / "tenant.json").write_text("racing writer")
        return result

    monkeypatch.setattr(Path, "mkdir", injected)
    with pytest.raises(TenantProvisionError):
        provision_tenant(private_root, _identity())
    assert (target / "tenant.json").read_text() == "racing writer"


def test_interrupted_initialization_is_not_silently_repaired(private_root: Path, monkeypatch):
    original = os.fsync

    def disk_error(_descriptor):
        raise OSError("synthetic storage failure")

    monkeypatch.setattr(os, "fsync", disk_error)
    with pytest.raises(TenantProvisionError):
        provision_tenant(private_root, _identity())
    monkeypatch.setattr(os, "fsync", original)
    # The incomplete marker prevents adopting bytes whose sync failed.
    with pytest.raises(TenantProvisionError):
        provision_tenant(private_root, _identity())
    assert (private_root / "shop-101" / ".initializing").is_file()


def test_concurrent_initializers_preserve_one_complete_workspace(private_root: Path) -> None:
    def provision(_number):
        try:
            return provision_tenant(private_root, _identity())
        except TenantProvisionError:
            return None  # An in-progress initializer fails closed and is retryable.

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(provision, range(24)))
    successful = [item for item in results if item is not None]
    assert successful
    assert all(item == successful[0] for item in successful)
    assert len(list(private_root.iterdir())) == 1
    assert provision_tenant(private_root, _identity()) == successful[0]


def test_uninitialized_identity_is_rejected_without_creating_storage(private_root: Path) -> None:
    forged = object.__new__(TenantIdentity)
    with pytest.raises(TenantProvisionError):
        provision_tenant(private_root, forged)
    assert not list(private_root.iterdir())
