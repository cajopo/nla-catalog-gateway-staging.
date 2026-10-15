"""Operational health failure semantics without network, Shopify or live services."""

import asyncio
import hashlib
import http.client
import json
import runpy
import stat
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from scripts import observe_catalog_health as observe
from scripts import serve_operational_health as serve

from nla_catalog_gateway import operational_health as health

NOW = datetime(2026, 10, 15, 12, tzinfo=UTC)
RUN = "20261015t110000z-1234abcd"
MARKET_RUN = "market-20261015t110000z-1234abcd"


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def unit(**overrides):
    return {
        "LoadState": "loaded",
        "ActiveState": "inactive",
        "SubState": "dead",
        "Result": "success",
        "ExecMainStatus": "0",
        "Job": "",
        **overrides,
    }


@pytest.fixture
def state(tmp_path, monkeypatch):
    paths = health.ObserverPaths(tmp_path / "refresh", tmp_path / "market", tmp_path / "store")
    pointer = {"currentManifestSha256": "a" * 64}
    dump(paths.store / "activation.v1.json", pointer)
    receipt = {
        "run": RUN,
        "status": "ready",
        "sourceStartedAt": "2026-10-15T11:00:00Z",
        "manifestSha256": "a" * 64,
        "activationSha256": hashlib.sha256(
            (paths.store / "activation.v1.json").read_bytes()
        ).hexdigest(),
    }
    dump(paths.refresh / "last-success.json", receipt)
    dump(paths.market / "last-market-success.json", {"status": "draft_cycle_complete"})
    monkeypatch.setattr(health, "systemd_unit", lambda name: unit())
    monkeypatch.setattr(
        health.shutil, "disk_usage", lambda path: SimpleNamespace(free=health.MIN_FREE_BYTES)
    )
    monkeypatch.setattr(health, "runtime_ready", lambda port: port == 10001)
    return paths, pointer, receipt


@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {"ActiveState": "active"},
        {"ActiveState": "activating"},
        {"Job": "123"},
    ],
)
def test_healthy_job_states(overrides):
    assert health.job_healthy(unit(**overrides), None, None)
    assert health.job_healthy(unit(**overrides), {"run": RUN}, None) == bool(overrides)


@pytest.mark.parametrize(
    "overrides",
    [
        {"extra": "secret"},
        {"LoadState": "not-found"},
        {"Result": "exit-code"},
        {"ExecMainStatus": "1"},
        {"ActiveState": "failed"},
        {"SubState": ""},
        {"Job": "unknown"},
    ],
)
def test_bad_job_contract_or_failure(overrides):
    assert not health.job_healthy(unit(**overrides), None, None)


def test_stopped_receipt_dominates_running_unit():
    assert not health.job_healthy(unit(ActiveState="active"), {"run": RUN}, {"status": "stopped"})


@pytest.mark.parametrize("age,expected", [(0, True), (86399, True), (86400, False), (-1, False)])
def test_source_age_from_capture_not_activation(state, age, expected):
    _, pointer, receipt = state
    receipt.update(
        sourceStartedAt=(NOW - timedelta(seconds=age)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        activatedAt="2026-10-15T12:00:00Z",
    )
    assert health.source_healthy(pointer, receipt["activationSha256"], receipt, NOW) is expected
    assert not health.source_healthy(pointer, receipt["activationSha256"], receipt, NOW, max_age=0)


@pytest.mark.parametrize(
    "change",
    [
        {"status": "incomplete"},
        {"manifestSha256": "invalid"},
        {"manifestSha256": "b" * 64},
        {"activationSha256": "wrong"},
    ],
)
def test_source_requires_matching_identity(state, change):
    _, pointer, receipt = state
    pin = receipt["activationSha256"]
    receipt.update(change)
    assert not health.source_healthy(pointer, pin, receipt, NOW)


def test_collector_healthy_with_old_process_absent(state):
    paths, _, _ = state
    assert health.collect(paths, now=NOW) == "healthy"
    assert health.collect(paths, now=NOW, max_source_age_seconds=1) == "source_stale_or_unverified"


@pytest.mark.parametrize("target", health.UNITS)
def test_unit_failure_never_masked_by_old_success(state, monkeypatch, target):
    paths, _, _ = state
    monkeypatch.setattr(
        health, "systemd_unit", lambda name: unit(Result="exit-code") if name == target else unit()
    )
    assert health.collect(paths, now=NOW) == "job_attention"


@pytest.mark.parametrize("market", [True, False])
def test_pending_inactive_and_stopped_are_attention(state, monkeypatch, market):
    paths, _, _ = state
    root = paths.market if market else paths.refresh
    filename = "pending-market-run.json" if market else "pending-run.json"
    name = MARKET_RUN if market else RUN
    dump(root / filename, {"run": name})
    assert health.collect(paths, now=NOW) == "job_attention"
    monkeypatch.setattr(health, "systemd_unit", lambda name: unit(ActiveState="activating"))
    assert health.collect(paths, now=NOW) == "healthy"
    dump(root / name / "stopped.json", {"private": "never-log-this"})
    assert health.collect(paths, now=NOW) == "job_attention"


def test_invalid_pending_run_cannot_escape_root(state):
    paths, _, _ = state
    dump(paths.refresh / "pending-run.json", {"run": "../credentials"})
    with pytest.raises(ValueError, match="invalid pending observation"):
        health.collect(paths, now=NOW)


def test_market_partial_is_attention(state):
    paths, _, _ = state
    dump(paths.market / "last-market-success.json", {"status": "draft_cycle_partial"})
    assert health.collect(paths, now=NOW) == "market_incomplete"


def test_low_disk_and_runtime_unavailable(state, monkeypatch):
    paths, _, _ = state
    assert health.collect(paths, now=NOW, min_free_bytes=health.MIN_FREE_BYTES + 1) == "low_disk"
    monkeypatch.setattr(health, "runtime_ready", lambda port: False)
    assert health.collect(paths, now=NOW) == "runtime_unavailable"


@pytest.mark.parametrize("candidate", [None, "other-run", RUN])
def test_activation_receipt_race(state, monkeypatch, candidate):
    paths, _, receipt = state
    monkeypatch.setattr(health, "systemd_unit", lambda name: unit(ActiveState="active"))
    dump(paths.refresh / "pending-run.json", {"run": RUN})
    dump(paths.refresh / "last-success.json", {**receipt, "manifestSha256": "b" * 64})
    if candidate is not None:
        dump(paths.refresh / RUN / "completed.json", {**receipt, "run": candidate})
    expected = "healthy" if candidate == RUN else "source_stale_or_unverified"
    assert health.collect(paths, now=NOW) == expected


@pytest.mark.parametrize("change", ["pointer", "bytes"])
def test_incoherent_pointer_is_retried_and_bounded(state, monkeypatch, change):
    paths, _, _ = state
    original = health.read_document
    reads = 0

    def read(path, **kwargs):
        nonlocal reads
        value, raw = original(path, **kwargs)
        if path.name == "activation.v1.json":
            reads += 1
            if reads % 2 == 0:
                if change == "pointer":
                    value = {**value, "race": True}
                else:
                    raw += b" "
        return value, raw

    monkeypatch.setattr(health, "read_document", read)
    assert health.collect(paths, now=NOW) == "source_stale_or_unverified"
    assert reads == 6


def test_document_bounds(tmp_path, monkeypatch):
    path = tmp_path / "input.json"
    dump(path, {"ok": True})
    assert health.read_document(path)[0] == {"ok": True}
    path.write_bytes(b" " * (health.MAX_DOCUMENT_BYTES + 1))
    with pytest.raises(ValueError, match="invalid observation input"):
        health.read_document(path)
    monkeypatch.setattr(
        health.os, "fstat", lambda fd: SimpleNamespace(st_mode=stat.S_IFREG, st_size=1)
    )
    with pytest.raises(ValueError, match="invalid observation input"):
        health.read_document(path)
    monkeypatch.setattr(
        health.os, "fstat", lambda fd: SimpleNamespace(st_mode=stat.S_IFIFO, st_size=1)
    )
    with pytest.raises(ValueError, match="invalid observation input"):
        health.read_document(path)


def test_document_json_object_required(tmp_path):
    path = tmp_path / "input.json"
    path.write_text("[]")
    with pytest.raises(ValueError, match="invalid observation input"):
        health.read_document(path)


def test_systemctl_fixed_readonly_contract(monkeypatch):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(stdout="\n".join(key + "=" + value for key, value in unit().items()))

    monkeypatch.setattr(health.subprocess, "run", run)
    assert health.systemd_unit(health.UNITS[0]) == unit()
    argv, kwargs = calls[0]
    assert argv[:3] == ["/usr/bin/systemctl", "show", "nla-catalog-refresh.service"]
    assert kwargs["timeout"] == 3 and kwargs["check"] and kwargs["capture_output"]
    assert set(kwargs["env"]) == {"PATH", "LC_ALL"}
    monkeypatch.setattr(
        health.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout="x" * 4097)
    )
    with pytest.raises(ValueError, match="invalid service observation"):
        health.systemd_unit(health.UNITS[0])


@pytest.mark.parametrize(
    "status,error", [(200, None), (503, None), (None, OSError), (None, http.client.HTTPException)]
)
def test_runtime_probe_bounded_loopback(monkeypatch, status, error):
    calls = []

    class Connection:
        def __init__(self, *args, **kwargs):
            calls.append((args, kwargs))

        def request(self, *args):
            assert args == ("GET", "/readyz")
            if error:
                raise error("private diagnostic")

        def getresponse(self):
            return SimpleNamespace(status=status)

        def close(self):
            calls.append("closed")

    monkeypatch.setattr(health.http.client, "HTTPConnection", Connection)
    assert health.runtime_ready(10000) is (status == 200)
    assert calls == [(("127.0.0.1", 10000), {"timeout": 1}), "closed"]


def request(app, **scope):
    messages = []

    async def send(message):
        messages.append(message)

    asyncio.run(
        app(
            {"type": "http", "method": "GET", "path": "/opsz", "query_string": b"", **scope},
            None,
            send,
        )
    )
    return messages


@pytest.mark.parametrize(
    "age,healthy,extra,expected",
    [
        (0, True, {}, 200),
        (89, True, {}, 200),
        (90, True, {}, 503),
        (-1, True, {}, 503),
        (0, False, {}, 503),
        (0, "True", {}, 503),
        (0, True, {"secret": "never-visible"}, 503),
    ],
)
def test_http_observation_freshness_and_no_leak(
    tmp_path, monkeypatch, age, healthy, extra, expected
):
    class Clock:
        @staticmethod
        def now(tz):
            return NOW

    monkeypatch.setattr(health, "datetime", Clock)
    monkeypatch.setattr(
        health,
        "timestamp",
        lambda value: datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC),
    )
    path = tmp_path / "health.json"
    dump(
        path,
        {
            "checkedAt": (NOW - timedelta(seconds=age)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "healthy": healthy,
            **extra,
        },
    )
    response = request(health.OperationalHealthApp(path))
    assert response[0]["status"] == expected
    assert response[1]["body"] == (b"healthy\n" if expected == 200 else b"attention\n")
    assert b"no-store" in dict(response[0]["headers"]).values()
    assert "never-visible" not in str(response)


def test_http_missing_invalid_and_fixed_routes(tmp_path):
    path = tmp_path / "missing.json"
    app = health.OperationalHealthApp(path)
    assert request(app)[0]["status"] == 503
    path.write_text("secret-malformed-json")
    assert request(app)[1]["body"] == b"attention\n"
    for scope in ({"method": "POST"}, {"path": "/etc/passwd"}, {"query_string": b"path=secret"}):
        assert request(app, **scope)[0]["status"] == 404
    with pytest.raises(ValueError, match="HTTP only"):
        request(app, type="lifespan")


def test_observation_publication_is_sanitized(tmp_path):
    path = tmp_path / "status.json"
    health.write_observation(path, now=NOW, healthy=True)
    assert json.loads(path.read_text()) == {"checkedAt": "2026-10-15T12:00:00Z", "healthy": True}
    health.write_observation(path, now=NOW, healthy=False)
    assert not json.loads(path.read_text())["healthy"]
    assert not path.with_suffix(".tmp").exists()


def observer_args(tmp_path):
    return [
        "--refresh-root",
        str(tmp_path / "refresh"),
        "--market-root",
        str(tmp_path / "market"),
        "--store",
        str(tmp_path / "store"),
        "--output",
        str(tmp_path / "health.json"),
    ]


@pytest.mark.parametrize("reason", ["healthy", "low_disk", "private leaked data"])
def test_collector_cli_only_logs_enum(tmp_path, monkeypatch, capsys, reason):
    monkeypatch.setattr(observe, "collect", lambda *a, **k: reason)
    assert observe.main(observer_args(tmp_path)) == 0
    expected = reason if reason in health.REASONS else "observation_unknown"
    assert capsys.readouterr().out == "OPERATIONAL_HEALTH:" + expected + "\n"
    assert json.loads((tmp_path / "health.json").read_text())["healthy"] is (reason == "healthy")


@pytest.mark.parametrize(
    "extra", [[], ["--min-free-bytes", "0"], ["--max-source-age-seconds", "0"]]
)
def test_collector_failure_failclosed_valuefree(tmp_path, monkeypatch, capsys, extra):
    def fail(*args, **kwargs):
        raise subprocess.TimeoutExpired("secret command", 3, output="secret output")

    monkeypatch.setattr(observe, "collect", fail)
    assert observe.main(observer_args(tmp_path) + extra) == 0
    assert capsys.readouterr().out == "OPERATIONAL_HEALTH:observation_unknown\n"
    assert not json.loads((tmp_path / "health.json").read_text())["healthy"]


def test_collector_output_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(observe, "collect", lambda *a, **k: "healthy")
    args = observer_args(tmp_path)
    args[-1] = str(tmp_path / "missing" / "out.json")
    assert observe.main(args) == 1


def test_server_cli_fixed_loopback_and_logging(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(serve.uvicorn, "run", lambda *a, **k: calls.append((a, k)))
    assert serve.main(["--observation", str(tmp_path / "health.json")]) == 0
    app, options = calls[0][0][0], calls[0][1]
    assert isinstance(app, health.OperationalHealthApp)
    assert options == {
        "host": "127.0.0.1",
        "port": 10002,
        "workers": 1,
        "lifespan": "off",
        "access_log": False,
        "log_config": None,
        "log_level": "critical",
        "proxy_headers": False,
        "server_header": False,
        "limit_concurrency": 16,
        "timeout_keep_alive": 2,
        "timeout_graceful_shutdown": 5,
    }


def test_script_entrypoints(tmp_path, monkeypatch):
    monkeypatch.setattr(health, "collect", lambda *a, **k: "healthy")
    monkeypatch.delitem(sys.modules, "scripts.observe_catalog_health", raising=False)
    monkeypatch.delitem(sys.modules, "scripts.serve_operational_health", raising=False)
    monkeypatch.setattr(sys, "argv", ["observe", *observer_args(tmp_path)])
    with pytest.raises(SystemExit) as result:
        runpy.run_module("scripts.observe_catalog_health", run_name="__main__")
    assert result.value.code == 0
    monkeypatch.setattr(serve.uvicorn, "run", lambda *a, **k: None)
    monkeypatch.setattr(sys, "argv", ["serve", "--observation", str(tmp_path / "health.json")])
    with pytest.raises(SystemExit) as result:
        runpy.run_module("scripts.serve_operational_health", run_name="__main__")
    assert result.value.code == 0


@pytest.mark.parametrize("job", ["", "0", "123"])
def test_systemd_255_show_job_scalar_contract(monkeypatch, job):
    # v255 systemctl-show.c prints the (0, /) no-job D-Bus tuple as empty.
    captured = (
        "LoadState=loaded\nActiveState=inactive\nSubState=dead\n"
        "Result=success\nExecMainStatus=0\nJob=" + job + "\n"
    )
    monkeypatch.setattr(health.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=captured))
    observed = health.systemd_unit(health.UNITS[0])
    assert health.job_healthy(observed, None, None)
    assert health.job_running(observed) is (job == "123")
    assert health.job_healthy(observed, {"run": RUN}, None) is (job == "123")


@pytest.mark.parametrize(
    "market_state,market_time,refresh_time,expected",
    [
        ("activating", "2026-10-15T10:00:00Z", "2026-10-15T11:00:00Z", "healthy"),
        ("inactive", "2026-10-15T10:00:00Z", "2026-10-15T11:00:00Z", "job_attention"),
        ("activating", "2026-10-15T11:30:00Z", "2026-10-15T11:00:00Z", "job_attention"),
        ("activating", "2026-10-15T10:00:00Z", "2026-10-15T13:00:00Z", "job_attention"),
    ],
)
def test_market_parent_owns_nested_refresh_pending(
    state, monkeypatch, market_state, market_time, refresh_time, expected
):
    paths, _, _ = state
    dump(paths.refresh / "pending-run.json", {"run": RUN, "startedAt": refresh_time})
    dump(paths.market / "pending-market-run.json", {"run": MARKET_RUN, "startedAt": market_time})
    monkeypatch.setattr(
        health,
        "systemd_unit",
        lambda name: unit(ActiveState=market_state) if name == health.UNITS[1] else unit(),
    )
    assert health.collect(paths, now=NOW) == expected
    if expected == "healthy":
        monkeypatch.setattr(
            health,
            "systemd_unit",
            lambda name: (
                unit(ActiveState=market_state)
                if name == health.UNITS[1]
                else unit(Result="exit-code")
            ),
        )
        assert health.collect(paths, now=NOW) == "job_attention"


def test_market_receipt_budget_supports_full_configured_attempt_count(state):
    paths, _, _ = state
    receipt = {
        "status": "draft_cycle_complete",
        "attempts": [
            {
                "cardmarketId": str(number),
                "status": "draft_verified",
                "productGid": "gid://shopify/Product/123456789012345",
                "published": False,
            }
            for number in range(50 * 100)
        ],
    }
    target = paths.market / "last-market-success.json"
    dump(target, receipt)
    assert target.stat().st_size > health.MAX_DOCUMENT_BYTES
    assert health.collect(paths, now=NOW) == "healthy"
    target.write_bytes(b" " * (health.MAX_MARKET_RECEIPT_BYTES + 1))
    with pytest.raises(ValueError, match="invalid observation input"):
        health.collect(paths, now=NOW)


@pytest.mark.parametrize("age,expected", [(0, 200), (90, 503)])
def test_head_matches_get_status_without_body(tmp_path, age, expected):
    path = tmp_path / "health.json"
    checked = datetime.now(UTC) - timedelta(seconds=age)
    dump(path, {"checkedAt": checked.strftime("%Y-%m-%dT%H:%M:%SZ"), "healthy": True})
    app = health.OperationalHealthApp(path)
    get, head = request(app), request(app, method="HEAD")
    assert get[0]["status"] == head[0]["status"] == expected
    assert get[0]["headers"] == head[0]["headers"]
    assert head[1]["body"] == b""
    assert request(app, method="HEAD", path="/unknown")[1]["body"] == b""
