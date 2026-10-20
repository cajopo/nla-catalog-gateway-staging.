"""Operational health failure semantics without network, Shopify or live services."""

import asyncio
import hashlib
import http.client
import json
import os
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
BACKUP_JOB = "backup-" + "1" * 32


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
        "ExecMainStartTimestamp": "@" + str(int(NOW.timestamp()) - 3600),
        **overrides,
    }


def timer(**overrides):
    return {
        "LoadState": "loaded",
        "ActiveState": "active",
        "SubState": "waiting",
        "Result": "success",
        "UnitFileState": "enabled",
        **overrides,
    }


def systemd_output(names, value):
    return "\n\n".join(
        "Id=" + name + "\n" + "\n".join(key + "=" + item for key, item in value(name).items())
        for name in names
    )


def mock_units(monkeypatch, service=lambda name: unit(), timers=lambda name: timer()):
    monkeypatch.setattr(
        health,
        "systemd_units",
        lambda names, properties: {
            name: (timers(name) if name.endswith(".timer") else service(name)) for name in names
        },
    )


def backup_receipt(paths, **overrides):
    return {
        "schemaVersion": 1,
        "jobId": BACKUP_JOB,
        "status": "complete",
        "startedAt": "2026-10-15T10:00:00.012345+00:00",
        "checkpointCreatedAt": "2026-10-15T10:00:01.012345+00:00",
        "snapshotTime": "2026-10-15T10:10:00.123456789Z",
        "finishedAt": "2026-10-15T11:00:00.012345+00:00",
        "snapshotId": "b" * 64,
        "checkpointManifestSha256": "c" * 64,
        "snapshotPaths": [str(paths.backup / "jobs" / BACKUP_JOB / "checkpoint")],
        "integrityMode": "read-data",
        "integrityStatus": "passed",
        **overrides,
    }


def write_backup(paths, **overrides):
    receipt = backup_receipt(paths, **overrides)
    dump(paths.backup / "last-success.json", receipt)
    dump(paths.backup / "receipts" / (BACKUP_JOB + ".json"), receipt)
    return receipt


@pytest.fixture
def state(tmp_path, monkeypatch):
    paths = health.ObserverPaths(
        tmp_path / "refresh", tmp_path / "market", tmp_path / "store", tmp_path / "backup"
    )
    (paths.backup / "jobs").mkdir(parents=True)
    write_backup(paths)
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
    mock_units(monkeypatch)
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
    mock_units(monkeypatch, lambda name: unit(Result="exit-code") if name == target else unit())
    expected = "backup_attention" if target == health.UNITS[2] else "job_attention"
    assert health.collect(paths, now=NOW) == expected


@pytest.mark.parametrize("market", [True, False])
def test_pending_inactive_and_stopped_are_attention(state, monkeypatch, market):
    paths, _, _ = state
    root = paths.market if market else paths.refresh
    filename = "pending-market-run.json" if market else "pending-run.json"
    name = MARKET_RUN if market else RUN
    dump(root / filename, {"run": name})
    assert health.collect(paths, now=NOW) == "job_attention"
    mock_units(monkeypatch, lambda name: unit(ActiveState="activating"))
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
    mock_units(monkeypatch, lambda name: unit(ActiveState="active"))
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
        return SimpleNamespace(stdout=systemd_output(health.UNITS, lambda name: unit()))

    monkeypatch.setattr(health.subprocess, "run", run)
    assert health.systemd_units(health.UNITS, health.PROPERTIES) == {
        name: unit() for name in health.UNITS
    }
    argv, kwargs = calls[0]
    assert argv[:5] == ["/usr/bin/systemctl", "show", *health.UNITS]
    assert "--timestamp=unix" in argv
    assert "--property=Id," + ",".join(health.PROPERTIES) in argv
    assert kwargs["timeout"] == 3 and kwargs["check"] and kwargs["capture_output"]
    assert set(kwargs["env"]) == {"PATH", "LC_ALL"}
    monkeypatch.setattr(
        health.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout="x" * 4097)
    )
    with pytest.raises(ValueError, match="invalid service observation"):
        health.systemd_units((health.UNITS[0],), health.PROPERTIES)


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
        "--backup-root",
        str(tmp_path / "backup"),
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
    "extra",
    [
        [],
        ["--min-free-bytes", "0"],
        ["--max-source-age-seconds", "0"],
        ["--max-backup-age-seconds", "0"],
    ],
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
    captured = systemd_output((health.UNITS[0],), lambda name: unit(Job=job))
    monkeypatch.setattr(health.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=captured))
    observed = health.systemd_units((health.UNITS[0],), health.PROPERTIES)[health.UNITS[0]]
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
    mock_units(
        monkeypatch,
        lambda name: unit(ActiveState=market_state) if name == health.UNITS[1] else unit(),
    )
    assert health.collect(paths, now=NOW) == expected
    if expected == "healthy":
        mock_units(
            monkeypatch,
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


@pytest.mark.parametrize(
    "change",
    [
        {"schemaVersion": True},
        {"schemaVersion": 2},
        {"jobId": None},
        {"jobId": "../credentials"},
        {"status": "failed"},
        {"status": "skipped_busy"},
        {"integrityMode": "metadata"},
        {"integrityStatus": "failed"},
        {"snapshotId": "shortid"},
        {"snapshotId": int("1" * 64)},
        {"checkpointManifestSha256": int("1" * 64)},
        {"checkpointManifestSha256": "not-a-sha"},
        {"snapshotPaths": ["/another/job/checkpoint"]},
        {"startedAt": "2026-10-15T10:00:02+00:00"},
        {"snapshotTime": "2026-10-15T09:59:00+00:00"},
        {"finishedAt": "2026-10-15T10:00:00+00:00"},
        {"finishedAt": "2026-10-15T12:00:01+00:00"},
    ],
)
def test_backup_evidence_rejected(state, change):
    paths, _, _ = state
    write_backup(paths, **change)
    assert health.collect(paths, now=NOW) == "backup_attention"


@pytest.mark.parametrize("age,expected", [(0, True), (93599, True), (93600, False), (-1, False)])
def test_backup_freshness_uses_checkpoint_not_finish(state, age, expected):
    paths, _, _ = state
    captured = NOW - timedelta(seconds=age)
    stamp = captured.isoformat()
    write_backup(
        paths,
        startedAt=stamp,
        checkpointCreatedAt=stamp,
        snapshotTime=stamp,
        finishedAt=max(captured, NOW).isoformat(),
    )
    assert (
        health.backup_healthy(paths.backup, unit(), NOW, health.MAX_BACKUP_AGE_SECONDS) is expected
    )
    if age > 0:
        assert not health.backup_healthy(paths.backup, unit(), NOW, 1)


@pytest.mark.parametrize(
    "field", ["startedAt", "checkpointCreatedAt", "snapshotTime", "finishedAt"]
)
@pytest.mark.parametrize("value", ["malformed", "2026-10-15T10:00:01", None])
def test_invalid_backup_timestamp_fails_closed(state, field, value):
    paths, _, _ = state
    write_backup(paths, **{field: value})
    with pytest.raises((ValueError, TypeError)):
        health.collect(paths, now=NOW)


@pytest.mark.parametrize("target", ["last-success.json", "receipts/" + BACKUP_JOB + ".json"])
def test_missing_or_malformed_backup_receipt(state, target):
    paths, _, _ = state
    path = paths.backup / target
    path.unlink()
    with pytest.raises(FileNotFoundError):
        health.collect(paths, now=NOW)
    path.write_text("not-json")
    with pytest.raises(ValueError):
        health.collect(paths, now=NOW)


def test_backup_immutable_receipt_must_match(state):
    paths, _, _ = state
    dump(
        paths.backup / "receipts" / (BACKUP_JOB + ".json"),
        backup_receipt(paths, snapshotId="d" * 64),
    )
    assert health.collect(paths, now=NOW) == "backup_attention"


@pytest.mark.parametrize(
    "active,job", [("inactive", ""), ("active", ""), ("activating", ""), ("inactive", "123")]
)
def test_backup_running_or_queued_does_not_extend_checkpoint_age(state, monkeypatch, active, job):
    paths, _, _ = state
    mock_units(monkeypatch, lambda name: unit(ActiveState=active, Job=job))
    assert health.collect(paths, now=NOW) == "healthy"
    assert health.collect(paths, now=NOW + timedelta(hours=27)) == "backup_attention"


@pytest.mark.parametrize(
    "active,job,expected",
    [
        ("active", "", "healthy"),
        ("activating", "", "healthy"),
        ("inactive", "", "backup_attention"),
        ("inactive", "123", "backup_attention"),
    ],
)
def test_backup_live_staging_and_inactive_leftovers(state, monkeypatch, active, job, expected):
    paths, _, _ = state
    directory = paths.backup / "jobs" / ("backup-" + "2" * 32)
    directory.mkdir()
    os.utime(directory, (NOW.timestamp() - 60, NOW.timestamp() - 60))
    mock_units(monkeypatch, lambda name: unit(ActiveState=active, Job=job))
    assert health.collect(paths, now=NOW) == expected
    # A terminal failed receipt always wins, even while the service appears live.
    dump(paths.backup / "receipts" / (directory.name + ".json"), {"status": "failed"})
    assert health.collect(paths, now=NOW) == "backup_attention"


@pytest.mark.parametrize(
    "case", ["two", "unsafe", "file", "old", "future", "timestamp", "jobs-file"]
)
def test_retained_or_unsafe_staging_fails_closed(state, monkeypatch, case):
    paths, _, _ = state
    jobs = paths.backup / "jobs"
    if case == "jobs-file":
        jobs.rmdir()
        jobs.write_text("private")
    else:
        directory = jobs / ("unexpected" if case == "unsafe" else "backup-" + "2" * 32)
        if case == "file":
            directory.write_text("private")
        else:
            directory.mkdir()
            offset = -7200 if case == "old" else (1 if case == "future" else -60)
            os.utime(directory, (NOW.timestamp() + offset, NOW.timestamp() + offset))
        if case == "two":
            (jobs / ("backup-" + "3" * 32)).mkdir()
    mock_units(
        monkeypatch,
        lambda name: unit(
            ActiveState="active",
            **({"ExecMainStartTimestamp": "n/a"} if case == "timestamp" else {}),
        ),
    )
    assert health.collect(paths, now=NOW) == "backup_attention"


@pytest.mark.parametrize("target", health.TIMERS)
@pytest.mark.parametrize(
    "change",
    [
        {"UnitFileState": "disabled"},
        {"UnitFileState": "enabled-runtime"},
        {"LoadState": "not-found"},
        {"ActiveState": "inactive", "SubState": "dead"},
        {"Result": "resources"},
        {"SubState": "failed"},
    ],
)
def test_disabled_or_failed_scheduler(state, monkeypatch, target, change):
    paths, _, _ = state
    mock_units(monkeypatch, timers=lambda name: timer(**change) if name == target else timer())
    assert health.collect(paths, now=NOW) == "scheduler_attention"


@pytest.mark.parametrize(
    "market_active,expected",
    [("inactive", "scheduler_attention"), ("active", "healthy"), ("activating", "healthy")],
)
def test_market_can_temporarily_pause_enabled_refresh_timer(
    state, monkeypatch, market_active, expected
):
    paths, _, _ = state
    mock_units(
        monkeypatch,
        lambda name: unit(ActiveState=market_active) if name == health.UNITS[1] else unit(),
        lambda name: (
            timer(ActiveState="inactive", SubState="dead")
            if name == health.TIMERS[0]
            else timer(SubState="running")
        ),
    )
    assert health.collect(paths, now=NOW) == expected


@pytest.mark.parametrize(
    "case", ["duplicate-id", "unexpected-id", "duplicate-key", "missing-property", "missing-unit"]
)
def test_batched_systemctl_rejects_ambiguous_metadata(monkeypatch, case):
    names = health.UNITS
    output = systemd_output(names, lambda name: unit())
    if case == "duplicate-id":
        output += "\n\n" + systemd_output((names[0],), lambda name: unit())
    elif case == "unexpected-id":
        output = output.replace(names[0], "unexpected.service")
    elif case == "duplicate-key":
        output += "\nJob="
    elif case == "missing-property":
        output = output.replace("Job=\n", "", 1)
    else:
        output = systemd_output(names[:2], lambda name: unit())
    monkeypatch.setattr(health.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=output))
    with pytest.raises(ValueError, match="invalid service observation"):
        health.systemd_units(names, health.PROPERTIES)


@pytest.mark.parametrize(
    "threshold", ["min_free_bytes", "max_source_age_seconds", "max_backup_age_seconds"]
)
def test_direct_collector_thresholds_fail_closed(state, threshold):
    paths, _, _ = state
    with pytest.raises(ValueError, match="invalid observation threshold"):
        health.collect(paths, now=NOW, **{threshold: 0})


def test_cli_requires_backup_root_and_threads_thresholds(tmp_path, monkeypatch):
    captured = []
    monkeypatch.setattr(
        observe, "collect", lambda paths, **kwargs: captured.append((paths, kwargs)) or "healthy"
    )
    assert observe.main([*observer_args(tmp_path), "--max-backup-age-seconds", "1234"]) == 0
    assert captured[0][0].backup == tmp_path / "backup"
    assert captured[0][1]["max_backup_age_seconds"] == 1234
    args = observer_args(tmp_path)
    index = args.index("--backup-root")
    del args[index : index + 2]
    with pytest.raises(SystemExit) as result:
        observe.main(args)
    assert result.value.code == 2


@pytest.mark.parametrize(
    "case,expected",
    [
        ("staging", "healthy"),
        ("completion", "healthy"),
        ("receipt-read-completion", "healthy"),
        ("future-staging", "backup_attention"),
        ("future-completion", "backup_attention"),
        ("future-receipt-read-completion", "backup_attention"),
        ("stale", "backup_attention"),
    ],
)
def test_backup_comparison_clock_advances_during_reads(state, monkeypatch, case, expected):
    paths, _, _ = state
    elapsed = [100.0]
    monkeypatch.setattr(health, "time", SimpleNamespace(monotonic=lambda: elapsed[0]))
    mock_units(monkeypatch)
    original_metadata = health.systemd_units
    original_read = health.read_document

    def publish_completion(seconds):
        write_backup(paths, finishedAt=(NOW + timedelta(seconds=seconds)).isoformat())

    def metadata(names, properties):
        elapsed[0] += 2
        if names == health.TIMERS:
            if "staging" in case:
                directory = paths.backup / "jobs" / ("backup-" + "2" * 32)
                directory.mkdir()
                delta = 5 if case.startswith("future") else 3
                stamp = NOW.timestamp() + delta
                os.utime(directory, (stamp, stamp))
            elif case in ("completion", "future-completion"):
                publish_completion(5 if case.startswith("future") else 3)
            elif case == "stale":
                stamp = (NOW - timedelta(seconds=93599)).isoformat()
                write_backup(paths, startedAt=stamp, checkpointCreatedAt=stamp, snapshotTime=stamp)
        values = original_metadata(names, properties)
        if names == health.UNITS and "staging" in case:
            values[health.UNITS[2]]["ActiveState"] = "activating"
        return values

    def read(path, **kwargs):
        if path == paths.backup / "last-success.json" and "receipt-read" in case:
            elapsed[0] += 1
            publish_completion(6 if case.startswith("future") else 4.5)
        return original_read(path, **kwargs)

    monkeypatch.setattr(health, "systemd_units", metadata)
    monkeypatch.setattr(health, "read_document", read)
    assert health.collect(paths, now=NOW) == expected
