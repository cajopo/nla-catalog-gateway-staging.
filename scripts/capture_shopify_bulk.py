"""One Linux capture step: Shopify read-only Bulk exports -> verified candidate.

Run again with the same private directory when status is pending. No scheduler,
activation, credential persistence, cancellation or blind launch retry lives here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import uuid
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from nla_catalog_gateway import bulk, reconciliation
from nla_catalog_gateway.canonical_names import load_canonical_names, load_canonical_names_manifest
from nla_catalog_gateway.shopify_capture_http import ShopifyCaptureHttp
from nla_catalog_gateway.staging_generation import open_staging_generation
from scripts import reconcile_split_snapshot as reconcile
from scripts.package_staging_generation import run_packaging

ROOT = Path(__file__).resolve().parents[1]
API_VERSION = "2026-07"
PARTS = ("products", "variants")
MAX_CONTROL_BYTES = 128 * 1024
MAX_DOWNLOAD_BYTES = 2 * 1024**3
CHECKPOINT = "capture-checkpoint.v1.json"


class CaptureError(ValueError):
    """Fixed local diagnostic; never include remote response text or signed URLs."""


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise CaptureError("invalid capture arguments")


def _json(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _timestamp(value: str) -> datetime:
    return reconciliation._canonical_timestamp(value, "capture timestamp")[1]


def _gid(value: str) -> str:
    reconciliation._validated_gid(value, "BulkOperation", "capture operation ID")
    return value


@contextmanager
def _input(path: Path, *, external: bool = True, maximum: int = MAX_DOWNLOAD_BYTES):
    checked, state = reconcile._linux_regular_file(path, "capture input", external=external)
    if state.byte_count > maximum:
        raise CaptureError("capture input exceeds bound")
    with ExitStack() as stack:
        pinned = reconcile._linux_pin_regular_file(
            checked, state, "capture input", stack, freeze_maximum=None, external=external
        )
        yield pinned.handle
        reconcile._linux_verify_pinned_input(pinned)


def _read(path: Path, *, external: bool = True) -> bytes:
    with _input(path, external=external, maximum=MAX_CONTROL_BYTES) as source:
        return source.read(MAX_CONTROL_BYTES + 1)


def _digest(path: Path) -> str:
    with _input(path) as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def _check_directory(path: Path, descriptor: int) -> None:
    facts = os.fstat(descriptor)
    with reconcile._linux_directory(path, external=True) as current:
        other = os.fstat(current)
    if (
        (facts.st_dev, facts.st_ino) != (other.st_dev, other.st_ino)
        or facts.st_uid != os.geteuid()
        or stat.S_IMODE(facts.st_mode) != 0o700
    ):
        raise CaptureError("capture directory must remain private and unchanged")


@contextmanager
def _locked_directory(path: Path):
    # Import inside the Linux-only boundary so --help works on the operator's PC.
    if not sys.platform.startswith("linux") or reconcile._has_unsafe_path_component(path):
        raise CaptureError("capture requires a normalized external Linux directory")
    import fcntl

    with reconcile._linux_directory(path, external=True) as directory:
        _check_directory(path, directory)
        descriptor = None
        try:
            descriptor = os.open(
                ".capture.lock",
                os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                0o600,
                dir_fd=directory,
            )
            facts = os.fstat(descriptor)
            if (
                not stat.S_ISREG(facts.st_mode)
                or facts.st_nlink != 1
                or facts.st_uid != os.geteuid()
                or stat.S_IMODE(facts.st_mode) != 0o600
            ):
                raise CaptureError("capture lock is invalid")
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield directory
        finally:
            if descriptor is not None:
                os.close(descriptor)


@contextmanager
def _created_output(directory: int, name: str):
    descriptor = None
    try:
        descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=directory)
        with os.fdopen(descriptor, "wb", closefd=False) as target:
            yield target
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _save(directory: int, state: dict) -> None:
    # Exclusive random temporary + replace/fsync: a durable launch intent precedes
    # each mutation. A crash can leave a private temporary, never a false success.
    name = f".checkpoint-{uuid.uuid4().hex}.tmp"
    with _created_output(directory, name) as target:
        raw = _json(state)
        if len(raw) > MAX_CONTROL_BYTES or target.write(raw) != len(raw):
            raise CaptureError("checkpoint cannot be persisted")
        target.flush()
        os.fsync(target.fileno())
    os.replace(name, CHECKPOINT, src_dir_fd=directory, dst_dir_fd=directory)
    os.fsync(directory)


def _control(path: Path, directory: int, name: str, document: dict) -> None:
    raw = _json(document)
    if os.path.lexists(path / name):
        if _read(path / name) != raw:
            raise CaptureError("existing control file differs")
        return
    with _created_output(directory, name) as target:
        if target.write(raw) != len(raw):
            raise CaptureError("control file cannot be persisted")
        target.flush()
        os.fchmod(target.fileno(), 0o400)
        os.fsync(target.fileno())
    os.fsync(directory)


def _configuration(shop, publication, code_sha, names, manifest_path, manifest_sha):
    reconciliation._validated_gid(publication, "Publication", "Online Store publication")
    if type(code_sha) is not str or re.fullmatch(r"[0-9a-f]{40}", code_sha) is None:
        raise CaptureError("invalid code SHA")
    manifest = load_canonical_names_manifest(_read(manifest_path), expected_sha256=manifest_sha)
    with _input(names, maximum=manifest.sidecar.byte_count) as source:
        load_canonical_names(source, manifest=manifest)
    queries = {
        part: _read(ROOT / "graphql" / f"catalog_{part}_snapshot.graphql", external=False)
        for part in PARTS
    }
    controls = {
        name: _read(ROOT / "graphql" / f"capture_{name}.graphql", external=False)
        for name in ("counts", "start", "status")
    }
    taxonomy = bulk._strict_json(
        _read(ROOT / "src/nla_catalog_gateway/catalog_taxonomy.v1.json", external=False),
        "taxonomy",
    )
    types = sorted(
        name for name, rule in taxonomy["productTypes"].items() if rule["productFamily"] == "single"
    )
    # Canonical-name enrichment accounts for *all* structured singles in the
    # baseline, not just the active/published projection.
    single_query = (
        "("
        + " OR ".join("product_type:" + json.dumps(name, ensure_ascii=False) for name in types)
        + ")"
    )
    identity = {
        "shopDomain": shop,
        "apiVersion": API_VERSION,
        "onlineStorePublicationGid": publication,
        "sourceCodeSha": code_sha,
        "canonicalNameManifestSha256": manifest_sha,
        "canonicalNameSidecarSha256": manifest.sidecar.sha256,
        "canonicalNameRecordCount": manifest.sidecar.record_count,
        "singleQuery": single_query,
        "queryHashes": {name: hashlib.sha256(raw).hexdigest() for name, raw in queries.items()},
        "controlHashes": {name: hashlib.sha256(raw).hexdigest() for name, raw in controls.items()},
    }
    return identity, queries, {name: raw.decode("utf-8") for name, raw in controls.items()}


def _counts(client, controls, identity):
    data = client.graphql(controls["counts"], {"singleQuery": identity["singleQuery"]})
    if data["shop"]["myshopifyDomain"] != identity["shopDomain"]:
        raise CaptureError("authenticated shop differs")
    counts = {}
    for key in ("products", "variants", "published", "singles"):
        item = data[key]
        if item["precision"] != "EXACT" or type(item["count"]) is not int or item["count"] < 0:
            raise CaptureError("counts must be exact independent integers")
        counts[key] = item["count"]
    if not (
        0 < counts["singles"] <= counts["products"]
        and 0 <= counts["published"] <= counts["products"]
    ):
        raise CaptureError("independent counts are inconsistent")
    return counts


def _operation(client, controls, identifier, query, before):
    data = client.graphql(controls["status"], {"id": _gid(identifier)})["bulkOperation"]
    if data["id"] != identifier or data["type"] != "QUERY":
        raise CaptureError("export identity differs")
    reconciliation._terminal_query_transport_mode(data["query"], query)
    created = _timestamp(data["createdAt"])
    if not _timestamp(before) <= created <= _utcnow():
        raise CaptureError("export lies outside this capture interval")
    if data["status"] not in {"CREATED", "RUNNING", "COMPLETED"}:
        raise CaptureError("export did not complete successfully")
    if data["errorCode"] is not None or data["partialDataUrl"] is not None:
        raise CaptureError("partial or failed export is not acceptable")
    return data


def _terminal(data):
    numbers = {}
    for key in ("fileSize", "objectCount", "rootObjectCount"):
        value = data[key]
        if type(value) is str and re.fullmatch(r"[0-9]+", value):
            value = int(value)
        if type(value) is not int:
            raise CaptureError("export counts are invalid")
        numbers[key] = value
    evidence = reconciliation.BulkOperationTerminalEvidenceV1(
        operation_id=data["id"],
        operation_type=data["type"],
        status=data["status"],
        error_code=data["errorCode"],
        query=data["query"],
        created_at=data["createdAt"],
        completed_at=data["completedAt"],
        file_size=numbers["fileSize"],
        object_count=numbers["objectCount"],
        root_object_count=numbers["rootObjectCount"],
        url_present=isinstance(data["url"], str) and bool(data["url"]),
        partial_data_url_present=data["partialDataUrl"] is not None,
    )
    if evidence.file_size > MAX_DOWNLOAD_BYTES or _timestamp(evidence.completed_at) > _utcnow():
        raise CaptureError("export exceeds capture bounds")
    return {
        "schemaVersion": 1,
        "operationId": evidence.operation_id,
        "operationType": evidence.operation_type,
        "status": evidence.status,
        "errorCode": None,
        "query": evidence.query,
        "createdAt": evidence.created_at,
        "completedAt": evidence.completed_at,
        **numbers,
        "urlPresent": True,
        "partialDataUrlPresent": False,
    }


def _download(client, path, directory, part, data):
    target_name = f"{part}.jsonl"
    if os.path.lexists(path / target_name):
        raise CaptureError("uncheckpointed download requires operator inspection")
    partial = f".{part}-{uuid.uuid4().hex}.partial"
    with _created_output(directory, partial) as target:
        digest = client.download(data["url"], target, int(data["fileSize"]))
        target.flush()
        os.fchmod(target.fileno(), 0o400)
        os.fsync(target.fileno())
    _check_directory(path, directory)
    reconcile._linux_rename_noreplace(directory, partial, target_name)
    os.fsync(directory)
    return digest


def _expectation(state):
    identity, counts = state["identity"], state["beforeCounts"]
    return {
        "schemaVersion": 2,
        "snapshotSetId": state["snapshotSetId"],
        **{
            key: identity[key]
            for key in (
                "apiVersion",
                "shopDomain",
                "onlineStorePublicationGid",
                "sourceCodeSha",
                "canonicalNameManifestSha256",
                "canonicalNameRecordCount",
            )
        },
        "productCount": counts["products"],
        "variantCount": counts["variants"],
        "expectedActiveOnlineStorePublishedProductCount": counts["published"],
        "expectedCanonicalNameProductCount": counts["singles"],
    }


def run_capture(
    *,
    client: ShopifyCaptureHttp,
    capture_directory: Path,
    shop_domain: str,
    online_store_publication_gid: str,
    code_sha: str,
    canonical_names_jsonl: Path,
    canonical_names_manifest: Path,
    canonical_manifest_sha256: str,
    recover_products_operation_id: str | None = None,
    recover_variants_operation_id: str | None = None,
) -> dict:
    """Execute one step, retaining the checkpoint on failure; never touch active data."""
    identity, queries, controls = _configuration(
        shop_domain,
        online_store_publication_gid,
        code_sha,
        canonical_names_jsonl,
        canonical_names_manifest,
        canonical_manifest_sha256,
    )
    path = capture_directory
    recovery = dict(
        zip(PARTS, (recover_products_operation_id, recover_variants_operation_id), strict=True)
    )
    with _locked_directory(path) as directory:
        if os.path.lexists(path / CHECKPOINT):
            state = bulk._strict_json(_read(path / CHECKPOINT), "capture checkpoint")
            if state["schemaVersion"] != 1 or state["identity"] != identity:
                raise CaptureError("resume configuration differs from original capture")
        else:
            # A fresh open-file description avoids inherited directory offsets
            # after creating the lock, including on the host's tmpfs filesystem.
            with reconcile._linux_descriptor(
                ".", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, directory
            ) as scan:
                names = set(os.listdir(scan))
            if names != {".capture.lock"} or any(recovery.values()):
                raise CaptureError("new capture directory must be empty")
            before = _utcnow().isoformat().replace("+00:00", "Z")
            counts = _counts(client, controls, identity)
            state = {
                "schemaVersion": 1,
                "identity": identity,
                "beforeObservedAt": before,
                "beforeCounts": counts,
                "snapshotSetId": "sha256:" + uuid.uuid4().hex * 2,
                "parts": {part: {"launchIntent": False, "operationId": None} for part in PARTS},
                "packageManifestSha256": None,
            }
            _save(directory, state)
        if state["packageManifestSha256"] is not None:
            open_staging_generation(path / "candidate", state["packageManifestSha256"])
            return {"status": "candidate-ready", "manifestSha256": state["packageManifestSha256"]}
        age = _utcnow() - _timestamp(state["beforeObservedAt"])
        if not timedelta(0) <= age <= timedelta(seconds=reconciliation.CAPTURE_FENCE_MAX_SECONDS):
            raise CaptureError("capture expired; retained operations require operator inspection")
        # Also authenticates the shop on resumed runs. Never replace original counts.
        if _counts(client, controls, identity) != state["beforeCounts"]:
            raise CaptureError("catalog counts changed during capture")
        for part in PARTS:
            entry = state["parts"][part]
            if recovery[part] is not None:
                if entry["operationId"] is not None or entry["launchIntent"] is not True:
                    raise CaptureError("recovery requires an unresolved launch intent")
                _operation(
                    client, controls, recovery[part], queries[part], state["beforeObservedAt"]
                )
                entry["operationId"] = _gid(recovery[part])
                _save(directory, state)
            if entry["operationId"] is None:
                if entry["launchIntent"] is not False:
                    raise CaptureError("launch outcome is uncertain; supply verified operation ID")
                entry["launchIntent"] = True
                _check_directory(path, directory)
                _save(directory, state)
                response = client.graphql(
                    controls["start"], {"query": queries[part].decode("utf-8")}
                )
                result = response["bulkOperationRunQuery"]
                if result["userErrors"] != []:
                    raise CaptureError("export launch failed; inspect before retrying")
                entry["operationId"] = _gid(result["bulkOperation"]["id"])
                _save(directory, state)
        identifiers = [state["parts"][part]["operationId"] for part in PARTS]
        if len(set(identifiers)) != 2:
            raise CaptureError("split exports must have distinct operation IDs")
        terminal = {
            part: _operation(
                client,
                controls,
                state["parts"][part]["operationId"],
                queries[part],
                state["beforeObservedAt"],
            )
            for part in PARTS
        }
        if any(data["status"] != "COMPLETED" for data in terminal.values()):
            return {"status": "pending", "operationIds": identifiers}
        evidence = {part: _terminal(data) for part, data in terminal.items()}
        if _counts(client, controls, identity) != state["beforeCounts"]:
            raise CaptureError("catalog counts changed after exports")
        state["afterObservedAt"] = _utcnow().isoformat().replace("+00:00", "Z")
        state["afterCounts"] = state["beforeCounts"].copy()
        _save(directory, state)
        for part in PARTS:
            entry = state["parts"][part]
            if evidence[part]["rootObjectCount"] != state["beforeCounts"][part]:
                raise CaptureError("export root count differs from independent count")
            if "downloadSha256" in entry:
                if (
                    entry["terminal"] != evidence[part]
                    or _digest(path / f"{part}.jsonl") != entry["downloadSha256"]
                ):
                    raise CaptureError("completed download differs from checkpoint")
            else:
                entry["downloadSha256"] = _download(client, path, directory, part, terminal[part])
                entry["terminal"] = evidence[part]
                _save(directory, state)
            _control(path, directory, f"{part}-terminal.json", evidence[part])
        _control(path, directory, "expectation.json", _expectation(state))
        _check_directory(path, directory)
        if "summarySha256" not in state:
            summary = reconcile.run_reconciliation(
                products_snapshot=path / "products.jsonl",
                variants_snapshot=path / "variants.jsonl",
                products_query=ROOT / "graphql/catalog_products_snapshot.graphql",
                variants_query=ROOT / "graphql/catalog_variants_snapshot.graphql",
                products_terminal=path / "products-terminal.json",
                variants_terminal=path / "variants-terminal.json",
                expectation_path=path / "expectation.json",
                output_directory=path / "bundle",
                canonical_names_jsonl=canonical_names_jsonl,
                canonical_names_manifest=canonical_names_manifest,
            )
            state["summarySha256"] = hashlib.sha256(_json(summary)).hexdigest()
            _save(directory, state)
        state["packageManifestSha256"] = run_packaging(
            path / "bundle", state["summarySha256"], code_sha, path / "candidate"
        )
        _save(directory, state)
        return {"status": "candidate-ready", "manifestSha256": state["packageManifestSha256"]}


def main(argv: list[str] | None = None) -> int:
    parser = _Parser(description=__doc__)
    for name in ("capture-directory", "canonical-names-jsonl", "canonical-names-manifest"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in (
        "shop-domain",
        "online-store-publication-gid",
        "code-sha",
        "canonical-manifest-sha256",
    ):
        parser.add_argument("--" + name, required=True)
    for part in PARTS:
        parser.add_argument(f"--recover-{part}-operation-id")
    try:
        args = parser.parse_args(argv)
        client = ShopifyCaptureHttp(
            args.shop_domain,
            API_VERSION,
            os.environ["SHOPIFY_CLIENT_ID"],
            os.environ["SHOPIFY_CLIENT_SECRET"],
        )
        receipt = run_capture(client=client, **vars(args))
    except (Exception, KeyboardInterrupt):
        print(
            "Capture not completed; private checkpoint retained. No catalog was activated.",
            file=sys.stderr,
        )
        return 1
    print(_json(receipt).decode("utf-8"))
    return 0 if receipt["status"] == "candidate-ready" else 3


if __name__ == "__main__":
    raise SystemExit(main())
