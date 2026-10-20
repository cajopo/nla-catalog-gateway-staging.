"""Secret-free, create-only workspaces for the hosted commercial pilot.

Identities here are validated syntax, not proof of a Shopify installation or
merchant consent. The caller must supply those facts through a trusted control
plane. A workspace never grants runtime or importer capabilities by itself.

The existing private root must be controlled by the service owner. POSIX owner
and mode checks are enforced. On Windows the operator must first restrict its
ACL to the service account; chmod does not establish Windows ACL privacy. This
module rejects reparse points but is not a sandbox against the storage owner or
an administrator concurrently replacing its directories.
"""

from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

_SHOP_DOMAIN = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.myshopify\.com\Z")
_SHOP_GID = re.compile(r"gid://shopify/Shop/([1-9][0-9]{0,19})\Z")
_PATH_TYPE = type(Path())
_CHECKOUT_ROOT = Path(__file__).resolve().parents[3]
_WINDOWS = os.name == "nt"
_MANIFEST_NAME = "tenant.json"
_DIRECTORIES = ("catalog", "importer", "state")
_ERROR = "tenant provisioning refused; identity, consent or private workspace is invalid"


class TenantProvisionError(ValueError):
    """Provisioning failed closed without overwriting an existing artifact."""


@dataclass(frozen=True, slots=True)
class TenantIdentity:
    """Canonical Shopify domain and immutable Shop GID, without credentials."""

    shop_domain: str
    shop_gid: str

    def __post_init__(self) -> None:
        if type(self.shop_domain) is not str or type(self.shop_gid) is not str:
            raise TenantProvisionError(_ERROR)
        domain = self.shop_domain.lower()
        if _SHOP_DOMAIN.fullmatch(domain) is None or _SHOP_GID.fullmatch(self.shop_gid) is None:
            raise TenantProvisionError(_ERROR)
        object.__setattr__(self, "shop_domain", domain)

    @property
    def tenant_key(self) -> str:
        return "shop-" + self.shop_gid.rsplit("/", 1)[1]


@dataclass(frozen=True, slots=True)
class TenantWorkspace:
    """Paths are private local storage, never a runtime authorization decision."""

    identity: TenantIdentity
    importer_authorized: bool
    root: Path
    manifest_path: Path
    catalog_dir: Path
    importer_dir: Path
    state_dir: Path


def _facts(path: Path) -> os.stat_result:
    facts = path.lstat()
    if stat.S_ISLNK(facts.st_mode) or (
        getattr(facts, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    ):
        raise TenantProvisionError(_ERROR)
    return facts


def _assert_private(facts: os.stat_result) -> None:
    if not _WINDOWS and (facts.st_uid != os.getuid() or facts.st_mode & 0o077):
        raise TenantProvisionError(_ERROR)


def _directory(path: Path) -> None:
    facts = _facts(path)
    if not stat.S_ISDIR(facts.st_mode):
        raise TenantProvisionError(_ERROR)
    _assert_private(facts)


def _storage_root(private_root: Path, checkout_root: Path | None) -> None:
    if type(private_root) is not _PATH_TYPE or not private_root.is_absolute():
        raise TenantProvisionError(_ERROR)
    if ".." in private_root.parts:
        raise TenantProvisionError(_ERROR)
    if checkout_root is not None and (
        type(checkout_root) is not _PATH_TYPE or not checkout_root.is_absolute()
    ):
        raise TenantProvisionError(_ERROR)
    excluded = (_CHECKOUT_ROOT, (checkout_root or _CHECKOUT_ROOT).resolve())
    for checkout in excluded:
        if private_root.is_relative_to(checkout) or checkout.is_relative_to(private_root):
            raise TenantProvisionError(_ERROR)
    # Inspect every existing component before resolve can conceal a link/junction.
    for path in (*reversed(private_root.parents), private_root):
        if not stat.S_ISDIR(_facts(path).st_mode):
            raise TenantProvisionError(_ERROR)
    if private_root.resolve(strict=True) != private_root:
        raise TenantProvisionError(_ERROR)
    _directory(private_root)


def _manifest(identity: TenantIdentity, importer_authorized: bool) -> bytes:
    return (
        json.dumps(
            {
                "schema_version": 1,
                "shop_domain": identity.shop_domain,
                "shop_gid": identity.shop_gid,
                "importer_authorized": importer_authorized,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _read_manifest(path: Path, expected: bytes) -> None:
    before = _facts(path)
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise TenantProvisionError(_ERROR)
    _assert_private(before)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    with os.fdopen(os.open(path, flags), "rb") as handle:
        opened = os.fstat(handle.fileno())
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise TenantProvisionError(_ERROR)
        if handle.read(4097) != expected:
            raise TenantProvisionError(_ERROR)


def _workspace(root: Path, identity: TenantIdentity, authorized: bool) -> TenantWorkspace:
    return TenantWorkspace(
        identity=identity,
        importer_authorized=authorized,
        root=root,
        manifest_path=root / _MANIFEST_NAME,
        catalog_dir=root / "catalog",
        importer_dir=root / "importer",
        state_dir=root / "state",
    )


def provision_tenant(
    private_root: Path,
    identity: TenantIdentity,
    *,
    importer_authorized: bool = False,
    checkout_root: Path | None = None,
) -> TenantWorkspace:
    """Create a tenant exclusively, or verify the exact previously completed one.

    The root must already exist outside the checkout with private permissions.
    A Shop GID binds its directory to one canonical domain and consent setting;
    changes require a separate reviewed workflow. No arbitrary configuration,
    credentials, subscriptions or merchant data are accepted. Manifest-last is
    the completion marker: interrupted initialization and concurrent in-progress
    initialization fail closed and may be retried after operator inspection.
    Existing files and data are never replaced or repaired automatically.
    """
    if type(identity) is not TenantIdentity or type(importer_authorized) is not bool:
        raise TenantProvisionError(_ERROR)
    # Revalidate even if a caller forged a frozen dataclass instance.
    try:
        checked = TenantIdentity(identity.shop_domain, identity.shop_gid)
    except AttributeError:
        raise TenantProvisionError(_ERROR) from None
    expected = _manifest(checked, importer_authorized)
    try:
        _storage_root(private_root, checkout_root)
        root = private_root / checked.tenant_key
        try:
            root.mkdir(mode=0o700)
        except FileExistsError:
            _directory(root)
            if {path.name for path in root.iterdir()} != {*_DIRECTORIES, _MANIFEST_NAME}:
                raise TenantProvisionError(_ERROR) from None
            for name in _DIRECTORIES:
                _directory(root / name)
            _read_manifest(root / _MANIFEST_NAME, expected)
        else:
            _directory(root)
            marker = root / ".initializing"
            os.close(os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
            for name in _DIRECTORIES:
                (root / name).mkdir(mode=0o700)
                _directory(root / name)
            descriptor = os.open(root / _MANIFEST_NAME, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(expected)
                handle.flush()
                os.fsync(handle.fileno())
            marker.unlink()
        return _workspace(root, checked, importer_authorized)
    except OSError:
        raise TenantProvisionError(_ERROR) from None
