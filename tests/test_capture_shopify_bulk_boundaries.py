"""Capture helper and CLI boundaries; real Linux files, no external HTTP calls."""

from __future__ import annotations

import hashlib
import json
import os
import runpy
import stat
import sys
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from scripts import capture_shopify_bulk as cli

import test_reconcile_split_snapshot as fixtures
from nla_catalog_gateway.canonical_names import MANIFEST_FILENAME, SIDECAR_FILENAME

SHOP = "synthetic-nla.myshopify.com"
OPERATION = "gid://shopify/BulkOperation/123"
PUBLICATION = "gid://shopify/Publication/456"
NOW = datetime(2026, 9, 18, 12, tzinfo=UTC)
QUERY = b"{ products { edges { node { id } } } }\n"
SENSITIVE = "synthetic-secret-and-signed-url-must-not-appear"


@pytest.fixture
def fixed_time(monkeypatch):
    monkeypatch.setattr(cli, "_utcnow", lambda: NOW)


@pytest.fixture
def private_directory(tmp_path):
    if sys.platform != "linux":
        return None
    directory = tmp_path / "capture"
    directory.mkdir(mode=0o700)
    return directory


def _counts_document():
    return {
        "shop": {"myshopifyDomain": SHOP},
        **{
            name: {"count": count, "precision": "EXACT"}
            for name, count in {"products": 3, "variants": 4, "published": 2, "singles": 1}.items()
        },
    }


def _operation_document(**changes):
    return {
        "id": OPERATION,
        "type": "QUERY",
        "query": QUERY.decode(),
        "createdAt": "2026-09-18T11:59:00Z",
        "completedAt": "2026-09-18T12:00:00Z",
        "status": "COMPLETED",
        "errorCode": None,
        "partialDataUrl": None,
        "url": "https://storage.googleapis.com/synthetic" + "?signature=" + SENSITIVE,
        "fileSize": "10",
        "objectCount": "2",
        "rootObjectCount": "1",
        **changes,
    }


def test_timestamp_gid_json_and_clock_are_canonical():
    assert cli._utcnow().tzinfo is UTC
    assert cli._utcnow().microsecond == 0
    assert cli._timestamp("2026-09-18T12:00:00Z") == NOW
    assert cli._gid(OPERATION) == OPERATION
    assert cli._json({"z": 1, "a": "é"}) == '{"a":"é","z":1}'.encode()
    for invalid in ("123", "gid://shopify/Product/123", "gid://shopify/BulkOperation/01"):
        with pytest.raises(ValueError):
            cli._gid(invalid)
    with pytest.raises(ValueError):
        cli._timestamp("2026-09-18T12:00:00")


def test_counts_use_independent_query_and_scope():
    calls = []

    def graphql(query, variables):
        calls.append((query, variables))
        return _counts_document()

    assert cli._counts(
        SimpleNamespace(graphql=graphql),
        {"counts": "count query"},
        {"shopDomain": SHOP, "singleQuery": "all structured singles"},
    ) == {"products": 3, "variants": 4, "published": 2, "singles": 1}
    assert calls == [("count query", {"singleQuery": "all structured singles"})]


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("shop", {"myshopifyDomain": "different.myshopify.com"}),
        ("products", {"count": 3, "precision": "AT_LEAST"}),
        ("variants", {"count": True, "precision": "EXACT"}),
        ("variants", {"count": "4", "precision": "EXACT"}),
        ("variants", {"count": -1, "precision": "EXACT"}),
        ("products", {"count": 0, "precision": "EXACT"}),
        ("singles", {"count": 0, "precision": "EXACT"}),
        ("singles", {"count": 4, "precision": "EXACT"}),
        ("published", {"count": 4, "precision": "EXACT"}),
    ],
)
def test_counts_reject_wrong_shop_approximation_and_inconsistent_totals(field, replacement):
    document = _counts_document()
    document[field] = replacement
    with pytest.raises(cli.CaptureError):
        cli._counts(
            SimpleNamespace(graphql=lambda *_: document),
            {"counts": "counts"},
            {"shopDomain": SHOP, "singleQuery": "singles"},
        )


@pytest.mark.parametrize("status", ["CREATED", "RUNNING", "COMPLETED"])
def test_operation_accepts_only_bound_query_identity_and_interval(fixed_time, status):
    document = _operation_document(status=status)
    calls = []

    def graphql(query, variables):
        calls.append((query, variables))
        return {"bulkOperation": document}

    assert (
        cli._operation(
            SimpleNamespace(graphql=graphql),
            {"status": "status query"},
            OPERATION,
            QUERY,
            "2026-09-18T11:58:00Z",
        )
        is document
    )
    assert calls == [("status query", {"id": OPERATION})]


@pytest.mark.parametrize(
    "changes",
    [
        {"id": "gid://shopify/BulkOperation/999"},
        {"type": "MUTATION"},
        {"query": "query not approved"},
        {"createdAt": "2026-09-18T11:57:59Z"},
        {"createdAt": "2026-09-18T12:00:01Z"},
        {"status": "FAILED"},
        {"status": "CANCELED"},
        {"errorCode": "INTERNAL_SERVER_ERROR"},
        {"partialDataUrl": "https://storage.googleapis.com/partial"},
    ],
)
def test_operation_rejects_unbound_or_failed_export(fixed_time, changes):
    with pytest.raises(ValueError):
        cli._operation(
            SimpleNamespace(graphql=lambda *_: {"bulkOperation": _operation_document(**changes)}),
            {"status": "status"},
            OPERATION,
            QUERY,
            "2026-09-18T11:58:00Z",
        )


@pytest.mark.parametrize("as_strings", [False, True])
def test_terminal_keeps_numbers_but_never_persists_signed_urls(fixed_time, as_strings):
    document = _operation_document()
    if not as_strings:
        for key in ("fileSize", "objectCount", "rootObjectCount"):
            document[key] = int(document[key])
    terminal = cli._terminal(document)
    assert terminal["fileSize"] == 10
    assert terminal["objectCount"] == 2
    assert terminal["rootObjectCount"] == 1
    assert terminal["urlPresent"] is True
    assert terminal["partialDataUrlPresent"] is False
    assert SENSITIVE not in json.dumps(terminal)
    assert "url" not in terminal and "partialDataUrl" not in terminal


@pytest.mark.parametrize(
    "changes",
    [
        {"fileSize": True},
        {"fileSize": "1.5"},
        {"objectCount": 1.5},
        {"rootObjectCount": None},
        {"fileSize": -1},
        {"fileSize": 0},
        {"rootObjectCount": 3},
        {"url": ""},
        {"url": None},
        {"partialDataUrl": "partial"},
        {"errorCode": "FAILED"},
        {"completedAt": "2026-09-18T12:00:01Z"},
    ],
)
def test_terminal_rejects_invalid_counts_and_completion(fixed_time, changes):
    with pytest.raises(ValueError):
        cli._terminal(_operation_document(**changes))


def test_terminal_rejects_size_limit_before_download(fixed_time, monkeypatch):
    monkeypatch.setattr(cli, "MAX_DOWNLOAD_BYTES", 9)
    with pytest.raises(cli.CaptureError, match="bounds"):
        cli._terminal(_operation_document())


@pytest.mark.parametrize("code_sha", [None, True, "a" * 39, "A" * 40, "g" * 40])
def test_configuration_rejects_code_pin_before_reading_inputs(code_sha):
    with pytest.raises(cli.CaptureError, match="code SHA"):
        cli._configuration(SHOP, PUBLICATION, code_sha, None, None, None)


def test_native_configuration_verifies_real_manifest_and_all_single_query(private_directory):
    if private_directory is None:
        return
    directory, manifest = fixtures.make_canonical_sidecar(private_directory)
    args = (
        SHOP,
        PUBLICATION,
        "a" * 40,
        directory / SIDECAR_FILENAME,
        directory / MANIFEST_FILENAME,
        manifest.manifest_sha256,
    )
    identity, queries, controls = cli._configuration(*args)
    assert identity["apiVersion"] == cli.API_VERSION == "2026-07"
    assert identity["canonicalNameManifestSha256"] == manifest.manifest_sha256
    assert identity["canonicalNameSidecarSha256"] == manifest.sidecar.sha256
    assert identity["canonicalNameRecordCount"] == 4
    assert identity["onlineStorePublicationGid"] == PUBLICATION
    assert identity["sourceCodeSha"] == "a" * 40
    taxonomy = json.loads(
        (cli.ROOT / "src/nla_catalog_gateway/catalog_taxonomy.v1.json").read_bytes()
    )
    singles = [
        name for name, rule in taxonomy["productTypes"].items() if rule["productFamily"] == "single"
    ]
    for name in singles:
        assert "product_type:" + json.dumps(name, ensure_ascii=False) in identity["singleQuery"]
    assert "status:" not in identity["singleQuery"]
    assert "published_status:" not in identity["singleQuery"]
    assert "Magic Display" not in identity["singleQuery"]
    assert identity["queryHashes"] == {
        part: hashlib.sha256(raw).hexdigest() for part, raw in queries.items()
    }
    assert identity["controlHashes"] == {
        name: hashlib.sha256(raw.encode()).hexdigest() for name, raw in controls.items()
    }
    with pytest.raises(ValueError):
        cli._configuration(*args[:-1], "0" * 64)
    with (directory / SIDECAR_FILENAME).open("ab") as target:
        target.write(b"\n")
    with pytest.raises(ValueError):
        cli._configuration(*args)


def test_locked_directory_rejects_unsupported_platform_and_unsafe_path(monkeypatch, tmp_path):
    monkeypatch.setattr(cli.sys, "platform", "unsupported")
    with pytest.raises(cli.CaptureError, match="Linux"):
        with cli._locked_directory(tmp_path):
            pytest.fail("unsupported host entered directory")
    monkeypatch.setattr(cli.sys, "platform", "linux")
    with pytest.raises(cli.CaptureError, match="normalized"):
        with cli._locked_directory(tmp_path / "unsafe."):
            pytest.fail("unsafe path entered directory")


def test_native_input_control_and_digest_are_bounded_and_pinned(private_directory, monkeypatch):
    if private_directory is None:
        return
    path = private_directory / "input"
    path.write_bytes(b"original")
    assert cli._read(path) == b"original"
    assert cli._digest(path) == hashlib.sha256(b"original").hexdigest()
    monkeypatch.setattr(cli, "MAX_CONTROL_BYTES", 7)
    with pytest.raises(cli.CaptureError, match="bound"):
        cli._read(path)
    with pytest.raises(ValueError):
        with cli._input(path) as source:
            assert source.read() == b"original"
            path.write_bytes(b"modified")


@pytest.mark.parametrize("kind", ["permissions", "owner", "replacement"])
def test_native_private_directory_requires_owner_mode_and_identity(
    private_directory, monkeypatch, kind
):
    if private_directory is None:
        return
    descriptor = os.open(private_directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        if kind == "permissions":
            private_directory.chmod(0o755)
        elif kind == "owner":
            owner = os.geteuid()
            monkeypatch.setattr(cli.os, "geteuid", lambda: owner + 1)
        else:
            private_directory.rename(private_directory.with_name("previous"))
            private_directory.mkdir(mode=0o700)
        with pytest.raises(cli.CaptureError, match="private and unchanged"):
            cli._check_directory(private_directory, descriptor)
    finally:
        os.close(descriptor)


@pytest.mark.parametrize("kind", ["permissions", "owner", "hardlink", "fifo", "symlink"])
def test_native_lock_rejects_untrusted_files(private_directory, monkeypatch, kind):
    if private_directory is None:
        return
    lock = private_directory / ".capture.lock"
    if kind == "fifo":
        os.mkfifo(lock, 0o600)
    elif kind == "symlink":
        lock.symlink_to(private_directory / "elsewhere")
    else:
        lock.write_bytes(b"")
        lock.chmod(0o644 if kind == "permissions" else 0o600)
        if kind == "hardlink":
            os.link(lock, private_directory / "second-link")
        elif kind == "owner":
            original = cli._check_directory

            def change_expected_owner(path, descriptor):
                original(path, descriptor)
                owner = os.geteuid()
                monkeypatch.setattr(cli.os, "geteuid", lambda: owner + 1)

            monkeypatch.setattr(cli, "_check_directory", change_expected_owner)
    before = len(os.listdir("/proc/self/fd"))
    with pytest.raises((cli.CaptureError, OSError)):
        with cli._locked_directory(private_directory):
            pytest.fail("untrusted lock accepted")
    assert len(os.listdir("/proc/self/fd")) == before


def test_native_lock_excludes_concurrent_runner_and_closes_descriptors(private_directory):
    if private_directory is None:
        return
    before = len(os.listdir("/proc/self/fd"))
    with cli._locked_directory(private_directory):
        with pytest.raises(BlockingIOError):
            with cli._locked_directory(private_directory):
                pytest.fail("second writer accepted")
    assert len(os.listdir("/proc/self/fd")) == before


def test_native_checkpoint_and_control_files_are_durable_and_exact(private_directory):
    if private_directory is None:
        return
    with cli._locked_directory(private_directory) as directory:
        cli._save(directory, {"version": 1})
        cli._save(directory, {"version": 2})
        assert json.loads((private_directory / cli.CHECKPOINT).read_bytes()) == {"version": 2}
        assert stat.S_IMODE((private_directory / cli.CHECKPOINT).stat().st_mode) == 0o600
        cli._control(private_directory, directory, "control.json", {"safe": True})
        control = private_directory / "control.json"
        assert stat.S_IMODE(control.stat().st_mode) == 0o400
        cli._control(private_directory, directory, "control.json", {"safe": True})
        with pytest.raises(cli.CaptureError, match="differs"):
            cli._control(private_directory, directory, "control.json", {"safe": False})
        assert control.read_bytes() == cli._json({"safe": True})


@pytest.mark.parametrize("operation", ["checkpoint", "control"])
def test_native_short_writes_never_publish_control_files(private_directory, monkeypatch, operation):
    if private_directory is None:
        return
    fdopen = os.fdopen

    @contextmanager
    def short_write(descriptor, mode, **kwargs):
        with fdopen(descriptor, mode, **kwargs) as target:
            yield SimpleNamespace(write=lambda raw: target.write(raw) - 1)

    with cli._locked_directory(private_directory) as directory:
        monkeypatch.setattr(cli.os, "fdopen", short_write)
        with pytest.raises(cli.CaptureError, match="persisted"):
            if operation == "checkpoint":
                cli._save(directory, {"version": 1})
            else:
                cli._control(private_directory, directory, "control.json", {"version": 1})
    assert not (private_directory / cli.CHECKPOINT).exists()


def test_native_output_constructor_failure_closes_owned_descriptor(private_directory, monkeypatch):
    if private_directory is None:
        return

    def fail_fdopen(*_args, **_kwargs):
        raise OSError("synthetic fdopen failure")

    before = len(os.listdir("/proc/self/fd"))
    with cli._locked_directory(private_directory) as directory:
        monkeypatch.setattr(cli.os, "fdopen", fail_fdopen)
        with pytest.raises(OSError, match="fdopen"):
            with cli._created_output(directory, "incomplete.tmp"):
                pytest.fail("failed stream constructor yielded")
    assert len(os.listdir("/proc/self/fd")) == before
    assert (private_directory / "incomplete.tmp").read_bytes() == b""


def test_native_output_exclusive_create_preserves_existing_file(private_directory):
    if private_directory is None:
        return
    existing = private_directory / "retained.tmp"
    existing.write_bytes(b"must survive")
    before = len(os.listdir("/proc/self/fd"))
    with cli._locked_directory(private_directory) as directory:
        with pytest.raises(FileExistsError):
            with cli._created_output(directory, existing.name):
                pytest.fail("exclusive create overwrote file")
    assert existing.read_bytes() == b"must survive"
    assert len(os.listdir("/proc/self/fd")) == before


@pytest.mark.parametrize("boundary", ["lock", "output"])
def test_native_interrupt_after_descriptor_assignment_closes_owner(private_directory, boundary):
    if private_directory is None:
        return
    helper = cli._locked_directory if boundary == "lock" else cli._created_output
    code = helper.__wrapped__.__code__
    old_trace = sys.gettrace()

    def interrupt(frame, event, _argument):
        if (
            frame.f_code is code
            and event == "line"
            and frame.f_locals.get("descriptor") is not None
        ):
            raise KeyboardInterrupt("synthetic descriptor acquisition interrupt")
        return interrupt

    before = len(os.listdir("/proc/self/fd"))
    directory = os.open(private_directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        sys.settrace(interrupt)
        with pytest.raises(KeyboardInterrupt):
            context = (
                cli._locked_directory(private_directory)
                if boundary == "lock"
                else cli._created_output(directory, "interrupted.tmp")
            )
            with context:
                pytest.fail("interrupted acquisition yielded")
    finally:
        sys.settrace(old_trace)
        os.close(directory)
    assert len(os.listdir("/proc/self/fd")) == before


def test_native_oversize_checkpoint_is_not_published(private_directory, monkeypatch):
    if private_directory is None:
        return
    monkeypatch.setattr(cli, "MAX_CONTROL_BYTES", 1)
    with cli._locked_directory(private_directory) as directory:
        with pytest.raises(cli.CaptureError, match="persisted"):
            cli._save(directory, {"version": 1})
    assert not (private_directory / cli.CHECKPOINT).exists()


def test_native_existing_download_requires_inspection(private_directory):
    if private_directory is None:
        return
    existing = private_directory / "products.jsonl"
    existing.write_bytes(b"must survive")
    with cli._locked_directory(private_directory) as directory:
        with pytest.raises(cli.CaptureError, match="inspection"):
            cli._download(None, private_directory, directory, "products", _operation_document())
    assert existing.read_bytes() == b"must survive"


@pytest.mark.parametrize("case", ["nonempty", "recover-products", "recover-variants"])
def test_native_new_capture_guards_precede_any_http_call(private_directory, case):
    if private_directory is None:
        return
    source = private_directory.parent / "source"
    source.mkdir()
    sidecar, manifest = fixtures.make_canonical_sidecar(source)
    retained = private_directory / "retained.jsonl"
    if case == "nonempty":
        retained.write_bytes(b"existing input must survive")

    def unexpected_http(*_args, **_kwargs):
        pytest.fail("invalid fresh capture reached HTTP")

    with pytest.raises(cli.CaptureError, match="new capture directory must be empty"):
        cli.run_capture(
            client=SimpleNamespace(graphql=unexpected_http),
            capture_directory=private_directory,
            shop_domain=SHOP,
            online_store_publication_gid=PUBLICATION,
            code_sha="a" * 40,
            canonical_names_jsonl=sidecar / SIDECAR_FILENAME,
            canonical_names_manifest=sidecar / MANIFEST_FILENAME,
            canonical_manifest_sha256=manifest.manifest_sha256,
            recover_products_operation_id=OPERATION if case == "recover-products" else None,
            recover_variants_operation_id=OPERATION if case == "recover-variants" else None,
        )
    assert not (private_directory / cli.CHECKPOINT).exists()
    if case == "nonempty":
        assert retained.read_bytes() == b"existing input must survive"
    assert {path.name for path in private_directory.iterdir()} == (
        {".capture.lock", "retained.jsonl"} if case == "nonempty" else {".capture.lock"}
    )


@pytest.mark.parametrize("offset", [-86401, 1])
def test_resume_age_guard_precedes_any_http_call(tmp_path, monkeypatch, fixed_time, offset):
    # Isolated guard test, not an end-to-end adapter or replacement for either core.
    state = {
        "schemaVersion": 1,
        "identity": {"same": True},
        "packageManifestSha256": None,
        "beforeObservedAt": (NOW + timedelta(seconds=offset)).isoformat().replace("+00:00", "Z"),
    }
    monkeypatch.setattr(cli, "_configuration", lambda *_: ({"same": True}, {}, {}))
    monkeypatch.setattr(cli, "_read", lambda *_: cli._json(state))
    monkeypatch.setattr(cli.os.path, "lexists", lambda *_: True)

    @contextmanager
    def locked(_path):
        yield 123

    monkeypatch.setattr(cli, "_locked_directory", locked)

    def unexpected_count(*_):
        pytest.fail("invalid-age checkpoint reached HTTP")

    monkeypatch.setattr(cli, "_counts", unexpected_count)
    with pytest.raises(cli.CaptureError):
        cli.run_capture(
            client=None,
            capture_directory=tmp_path,
            shop_domain=SHOP,
            online_store_publication_gid=PUBLICATION,
            code_sha="a" * 40,
            canonical_names_jsonl=tmp_path / "names",
            canonical_names_manifest=tmp_path / "manifest",
            canonical_manifest_sha256="b" * 64,
        )


def _arguments(tmp_path):
    return [
        "--capture-directory",
        str(tmp_path / "capture"),
        "--canonical-names-jsonl",
        str(tmp_path / "names"),
        "--canonical-names-manifest",
        str(tmp_path / "manifest"),
        "--shop-domain",
        SHOP,
        "--online-store-publication-gid",
        PUBLICATION,
        "--code-sha",
        "a" * 40,
        "--canonical-manifest-sha256",
        "b" * 64,
    ]


@pytest.mark.parametrize(("status", "code"), [("candidate-ready", 0), ("pending", 3)])
def test_cli_receipt_and_environment_credentials(tmp_path, monkeypatch, capsys, status, code):
    seen = []
    monkeypatch.setenv("SHOPIFY_CLIENT_ID", "synthetic-id")
    monkeypatch.setenv("SHOPIFY_CLIENT_SECRET", SENSITIVE)
    sentinel = object()

    def constructor(*args):
        seen.append(args)
        return sentinel

    def capture(**kwargs):
        assert kwargs["client"] is sentinel
        assert kwargs["capture_directory"] == tmp_path / "capture"
        assert kwargs["recover_products_operation_id"] == OPERATION
        assert kwargs["recover_variants_operation_id"] is None
        return {"status": status}

    monkeypatch.setattr(cli, "ShopifyCaptureHttp", constructor)
    monkeypatch.setattr(cli, "run_capture", capture)
    assert cli.main([*_arguments(tmp_path), "--recover-products-operation-id", OPERATION]) == code
    assert seen == [(SHOP, cli.API_VERSION, "synthetic-id", SENSITIVE)]
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"status": status}
    assert captured.err == "" and SENSITIVE not in captured.out


def test_cli_wait_options_resume_and_only_print_final_receipt(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SHOPIFY_CLIENT_ID", "synthetic-id")
    monkeypatch.setenv("SHOPIFY_CLIENT_SECRET", SENSITIVE)
    monkeypatch.setattr(cli, "ShopifyCaptureHttp", lambda *_: None)
    monkeypatch.setattr(cli.time, "monotonic", lambda: 0)
    sleeps = []
    monkeypatch.setattr(cli.time, "sleep", sleeps.append)
    receipts = iter([{"status": "pending"}, {"status": "candidate-ready"}])
    monkeypatch.setattr(cli, "run_capture", lambda **_: next(receipts))
    assert cli.main([*_arguments(tmp_path), "--wait-seconds", "120", "--poll-seconds", "5"]) == 0
    assert sleeps == [5]
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"status": "candidate-ready"}
    assert captured.err == ""


@pytest.mark.parametrize("failure", [RuntimeError(SENSITIVE), KeyboardInterrupt(SENSITIVE)])
def test_cli_redacts_unexpected_errors_and_interrupts(tmp_path, monkeypatch, capsys, failure):
    monkeypatch.setenv("SHOPIFY_CLIENT_ID", "synthetic-id")
    monkeypatch.setenv("SHOPIFY_CLIENT_SECRET", SENSITIVE)

    def fail(*_):
        raise failure

    monkeypatch.setattr(cli, "ShopifyCaptureHttp", fail)
    assert cli.main(_arguments(tmp_path)) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == (
        "Capture not completed; private checkpoint retained. No catalog was activated."
    )
    assert SENSITIVE not in captured.err


def test_cli_redacts_argument_errors(tmp_path, capsys):
    try:
        code = cli.main([*_arguments(tmp_path), "--unknown", SENSITIVE])
    except SystemExit as error:
        code = error.code
    assert code != 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert SENSITIVE not in captured.err


def test_cli_missing_credentials_and_module_entrypoint(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("SHOPIFY_CLIENT_ID", raising=False)
    monkeypatch.delenv("SHOPIFY_CLIENT_SECRET", raising=False)
    assert cli.main(_arguments(tmp_path)) == 1
    assert capsys.readouterr().out == ""
    monkeypatch.setattr(sys, "argv", [str(cli.__file__), *_arguments(tmp_path)])
    with pytest.raises(SystemExit) as result:
        runpy.run_path(str(cli.__file__), run_name="__main__")
    assert result.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "No catalog was activated" in captured.err
