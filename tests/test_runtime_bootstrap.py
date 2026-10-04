from __future__ import annotations

import asyncio
import base64
import os
import runpy
import stat
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import test_generation_bundle as bundle_helpers
import test_staging_generation as staging_helpers
from nla_catalog_gateway import runtime_bootstrap, staging_activation
from nla_catalog_gateway.runtime_server import RuntimeAsgiApp

ERROR = "runtime bootstrap configuration is invalid"


def _store(tmp_path: Path) -> SimpleNamespace:
    build = (tmp_path / "build").resolve()
    build.mkdir()
    package = staging_helpers._make_package(build)
    root = (tmp_path / "store").resolve()
    root.mkdir()
    generations = root / staging_activation.GENERATIONS_DIRECTORY
    generations.mkdir()
    destination = generations / package.manifest_sha256
    # POSIX cross-parent directory renames require a writable source directory.
    package.directory.chmod(stat.S_IRWXU)
    os.rename(package.directory, destination)
    destination.chmod(staging_helpers.package_staging_generation._READ_ONLY_DIRECTORY_MODE)
    pin = staging_activation.promote_staging_generation(
        root,
        package.manifest_sha256,
        staging_activation.ABSENT_ACTIVATION_SHA256,
    )
    return SimpleNamespace(root=root, pin=pin, package=package)


def _environment(store: SimpleNamespace) -> dict[str, str]:
    return {
        "NLA_SHOP_DOMAIN": bundle_helpers.SHOP,
        "NLA_APP_PROXY_SIGNED_PATH_PREFIX": "/apps/nla",
        "NLA_APP_PROXY_BACKEND_PATH": "/proxy/catalog",
        "NLA_APP_PROXY_SHARED_SECRET_B64": base64.b64encode(b"proxy-secret").decode(),
        "NLA_CURSOR_HMAC_SECRET_B64": base64.b64encode(b"k" * 32).decode(),
        "NLA_STAGING_STORE_ROOT": str(store.root),
        "NLA_ACTIVATION_SHA256": store.pin,
        "NLA_EVIDENCE_CODE_SHA": "c" * 40,
        "NLA_CURSOR_TTL_SECONDS": "900",
        "NLA_REQUEST_TIMEOUT_MS": "1500",
    }


async def _invoke_health(app: RuntimeAsgiApp, path: str) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []
    messages: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    messages.put_nowait({"type": "http.request"})

    async def receive() -> dict[str, Any]:
        return await messages.get()

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    await app(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [],
        },
        receive,
        send,
    )
    return sent


def _fixed_failure(environ: Any) -> None:
    with pytest.raises(runtime_bootstrap.RuntimeBootstrapError) as captured:
        runtime_bootstrap.create_app(environ)
    assert str(captured.value) == ERROR
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


def test_create_app_loads_pinned_generation_from_host_only_configuration(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    app = runtime_bootstrap.create_app(_environment(store))

    assert type(app) is RuntimeAsgiApp
    assert app._app_proxy_path == "/proxy/catalog"
    assert app._limits.request_timeout_ms == 1500
    sent = asyncio.run(_invoke_health(app, "/livez"))
    assert sent[0]["status"] == 200
    assert sent[1]["body"] == b'{"contractVersion":1,"status":"live"}'


def test_default_optional_limits_and_process_environment_are_supported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    environ = _environment(store)
    environ.pop("NLA_CURSOR_TTL_SECONDS")
    environ.pop("NLA_REQUEST_TIMEOUT_MS")
    environ["NLA_ALLOW_EMPTY_STAGING_STORE"] = "false"
    monkeypatch.setattr(runtime_bootstrap.os, "environ", environ)

    app = runtime_bootstrap.create_app()

    assert app._limits.request_timeout_ms == 2_000


def test_explicit_clean_empty_store_starts_live_but_not_ready(tmp_path: Path) -> None:
    root = (tmp_path / "empty-store").resolve()
    root.mkdir()
    (root / staging_activation.GENERATIONS_DIRECTORY).mkdir()
    store = SimpleNamespace(root=root, pin=staging_activation.ABSENT_ACTIVATION_SHA256)
    environ = _environment(store)
    environ["NLA_ALLOW_EMPTY_STAGING_STORE"] = "true"

    app = runtime_bootstrap.create_app(environ)

    live = asyncio.run(_invoke_health(app, "/livez"))
    ready = asyncio.run(_invoke_health(app, "/readyz"))
    assert live[0]["status"] == 200
    assert ready[0]["status"] == 503
    assert ready[1]["body"] == b'{"contractVersion":1,"status":"not_ready"}'


def test_explicit_virgin_mount_is_initialized_before_fail_closed_start(tmp_path: Path) -> None:
    root = (tmp_path / "virgin-store").resolve()
    root.mkdir()
    store = SimpleNamespace(root=root, pin=staging_activation.ABSENT_ACTIVATION_SHA256)
    environ = _environment(store)
    environ["NLA_ALLOW_EMPTY_STAGING_STORE"] = "true"

    app = runtime_bootstrap.create_app(environ)

    assert type(app) is RuntimeAsgiApp
    assert tuple(path.name for path in root.iterdir()) == (
        staging_activation.GENERATIONS_DIRECTORY,
    )
    assert asyncio.run(_invoke_health(app, "/readyz"))[0]["status"] == 503


def test_empty_store_requires_explicit_mode_and_exact_empty_shape(tmp_path: Path) -> None:
    root = (tmp_path / "empty-store").resolve()
    root.mkdir()
    generations = root / staging_activation.GENERATIONS_DIRECTORY
    generations.mkdir()
    store = SimpleNamespace(root=root, pin=staging_activation.ABSENT_ACTIVATION_SHA256)
    environ = _environment(store)
    _fixed_failure(environ)

    environ["NLA_ALLOW_EMPTY_STAGING_STORE"] = "true"
    arbitrary_pin = dict(environ)
    arbitrary_pin["NLA_ACTIVATION_SHA256"] = "0" * 64
    _fixed_failure(arbitrary_pin)

    (generations / "unexpected").write_bytes(b"x")
    _fixed_failure(environ)

    (generations / "unexpected").unlink()
    (root / "unexpected").write_bytes(b"x")
    _fixed_failure(environ)


def test_empty_store_shape_rejects_missing_file_and_reparse_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = (tmp_path / "missing").resolve()
    assert runtime_bootstrap._is_clean_empty_store(missing) is False

    file_root = (tmp_path / "file-root").resolve()
    file_root.write_bytes(b"x")
    assert runtime_bootstrap._is_clean_empty_store(file_root) is False

    wrong_child = (tmp_path / "wrong-child").resolve()
    wrong_child.mkdir()
    (wrong_child / staging_activation.GENERATIONS_DIRECTORY).write_bytes(b"x")
    assert runtime_bootstrap._is_clean_empty_store(wrong_child) is False

    facts = SimpleNamespace(
        st_mode=stat.S_IFDIR,
        st_file_attributes=runtime_bootstrap._REPARSE_POINT_ATTRIBUTE,
    )
    monkeypatch.setattr(Path, "stat", lambda *_args, **_kwargs: facts)
    assert runtime_bootstrap._plain_directory(file_root) is False


def test_empty_store_initialization_requires_a_canonical_external_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = (tmp_path / "repository").resolve()
    repository.mkdir()
    inside = repository / "store"
    inside.mkdir()
    monkeypatch.setattr(runtime_bootstrap, "REPOSITORY_ROOT", repository)

    assert runtime_bootstrap._initialize_clean_empty_store(repository) is False
    assert runtime_bootstrap._initialize_clean_empty_store(inside) is False
    assert not (inside / staging_activation.GENERATIONS_DIRECTORY).exists()

    external = (tmp_path / "external").resolve()
    external.mkdir()
    hop = tmp_path / "hop"
    hop.mkdir()
    noncanonical = hop / ".." / external.name
    assert runtime_bootstrap._initialize_clean_empty_store(noncanonical) is False
    assert not (external / staging_activation.GENERATIONS_DIRECTORY).exists()

    with pytest.raises(OSError):
        runtime_bootstrap._validated_empty_store_root(Path("relative"))
    with pytest.raises(OSError):
        runtime_bootstrap._validated_empty_store_root("not-a-path")  # type: ignore[arg-type]

    with monkeypatch.context() as context:
        context.setattr(Path, "is_symlink", lambda path: path == external)
        with pytest.raises(OSError):
            runtime_bootstrap._validated_empty_store_root(external)

    assert runtime_bootstrap._validated_empty_store_root(external) == external


def test_virgin_store_initialization_race_and_failure_remain_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = (tmp_path / "race-store").resolve()
    root.mkdir()
    real_mkdir = Path.mkdir

    def raced_mkdir(path: Path, *args: Any, **kwargs: Any) -> None:
        real_mkdir(path, *args, **kwargs)
        raise FileExistsError

    monkeypatch.setattr(Path, "mkdir", raced_mkdir)
    assert runtime_bootstrap._initialize_clean_empty_store(root) is True

    monkeypatch.setattr(Path, "mkdir", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError()))
    second = (tmp_path / "failed-store").resolve()
    real_mkdir(second)
    assert runtime_bootstrap._initialize_clean_empty_store(second) is False


def test_empty_store_identity_and_single_wrong_child_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wrong = (tmp_path / "wrong-single-child").resolve()
    wrong.mkdir()
    (wrong / "wrong").mkdir()
    assert runtime_bootstrap._is_clean_empty_store(wrong) is False
    assert runtime_bootstrap._initialize_clean_empty_store(wrong) is False

    monkeypatch.setattr(runtime_bootstrap, "_directory_identity", lambda _path: (2, 2))
    with pytest.raises(OSError):
        runtime_bootstrap._require_directory_identity(wrong, (1, 1))


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("NLA_STAGING_STORE_ROOT", "relative"),
        ("NLA_ACTIVATION_SHA256", "A" * 64),
        ("NLA_EVIDENCE_CODE_SHA", "bad"),
        ("NLA_APP_PROXY_SHARED_SECRET_B64", "not-base64"),
        ("NLA_APP_PROXY_SHARED_SECRET_B64", "YR=="),
        ("NLA_CURSOR_HMAC_SECRET_B64", base64.b64encode(b"short").decode()),
        ("NLA_CURSOR_TTL_SECONDS", "0"),
        ("NLA_CURSOR_TTL_SECONDS", 1),
        ("NLA_CURSOR_TTL_SECONDS", "86401"),
        ("NLA_REQUEST_TIMEOUT_MS", "30001"),
        ("NLA_ALLOW_EMPTY_STAGING_STORE", "TRUE"),
        ("NLA_SHOP_DOMAIN", "not-a-shop"),
        ("NLA_APP_PROXY_SIGNED_PATH_PREFIX", "/Apps/NLA"),
        ("NLA_APP_PROXY_BACKEND_PATH", "/readyz"),
    ],
)
def test_invalid_host_values_fail_without_disclosure(tmp_path: Path, name: str, value: Any) -> None:
    environ = _environment(_store(tmp_path))
    environ[name] = value
    _fixed_failure(environ)


def test_missing_value_non_mapping_and_stale_activation_pin_fail_closed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    missing = _environment(store)
    missing.pop("NLA_SHOP_DOMAIN")
    _fixed_failure(missing)
    _fixed_failure([])
    stale = _environment(store)
    stale["NLA_ACTIVATION_SHA256"] = "0" * 64
    _fixed_failure(stale)


def test_runtime_launcher_disables_request_target_and_proxy_header_logging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(runtime_bootstrap.os, "environ", {"PORT": "12345"})
    monkeypatch.setattr(
        runtime_bootstrap.uvicorn,
        "run",
        lambda app, **options: observed.append((app, options)),
    )

    runtime_bootstrap.main()

    assert len(observed) == 1
    app, options = observed[0]
    assert app is runtime_bootstrap.create_app
    assert options == {
        "access_log": False,
        "factory": True,
        "host": "0.0.0.0",  # noqa: S104 - exact launcher assertion
        "limit_concurrency": 32,
        "port": 12345,
        "proxy_headers": False,
        "server_header": False,
        "workers": 1,
    }


def test_runtime_launcher_defaults_port_and_rejects_out_of_range_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[int] = []
    monkeypatch.setattr(runtime_bootstrap.os, "environ", {})
    monkeypatch.setattr(
        runtime_bootstrap.uvicorn,
        "run",
        lambda _app, **options: observed.append(options["port"]),
    )
    runtime_bootstrap.main()
    assert observed == [10_000]

    monkeypatch.setattr(runtime_bootstrap.os, "environ", {"PORT": "65536"})
    with pytest.raises(runtime_bootstrap.RuntimeBootstrapError, match=ERROR) as captured:
        runtime_bootstrap.main()
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


def test_runtime_module_guard_is_value_free(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runtime_bootstrap.os, "environ", {"PORT": "invalid"})
    with pytest.raises(SystemExit, match="1"):
        runpy.run_path(runtime_bootstrap.__file__, run_name="__main__")
    assert capsys.readouterr() == ("VALUE_FREE_RESULT: REJECTED\n", "")


def test_container_default_command_is_the_safe_runtime_launcher() -> None:
    dockerfile = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text(encoding="utf-8")
    assert 'CMD ["python", "-m", "nla_catalog_gateway.runtime_bootstrap"]' in dockerfile
    assert (
        "COPY scripts/manage_staging_activation.py ./scripts/manage_staging_activation.py"
        in dockerfile
    )
    assert "COPY scripts ./scripts" not in dockerfile
    assert "--shell /bin/sh appuser" in dockerfile
    assert "install -d -m 0700 -o appuser -g appuser /home/appuser/.ssh" in dockerfile
