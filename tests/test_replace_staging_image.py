"""Offline code-only handoff; real filesystem receipts and shared runtime builder."""

import copy
import hashlib
import json
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from scripts import replace_staging_image as m


@pytest.fixture(params=[10000, 10001])
def case(tmp_path, monkeypatch, request):
    root = tmp_path / "runs"
    root.mkdir()
    envdir = tmp_path / "config"
    envdir.mkdir()
    config = dict(
        run_root=root,
        config=envdir,
        store=tmp_path / "store",
        current="current",
        image="sha256:" + "2" * 64,
        shop="test.myshopify.com",
    )
    raw = m.a.env_bytes(
        dict(
            NLA_ACTIVATION_SHA256="a" * 64,
            NLA_EVIDENCE_CODE_SHA="b" * 40,
            NLA_SHOP_DOMAIN=config["shop"],
            NLA_STAGING_STORE_ROOT="/var/lib/nla-catalog",
        )
    )
    (envdir / "accepted-runtime.env").write_bytes(raw)
    previous = dict(
        run="20260926t000000z-aaaaaaaa",
        status="ready",
        sourceStartedAt="2026-09-25T00:00:00Z",
        activatedAt="2026-09-26T00:00:00Z",
        manifestSha256="c" * 64,
        previousManifestSha256="d" * 64,
        activationSha256="a" * 64,
        resources=dict(runtime="1" * 64, before="3" * 64, verifier="4" * 64, promote="5" * 64),
    )
    before = json.dumps(previous).encode()
    (root / previous["run"]).mkdir()
    (root / previous["run"] / "completed.json").write_bytes(before)
    (root / "last-success.json").write_bytes(before)
    plan = m.load_plan(
        dict(
            config="/candidate.json",
            run_id="20260926t010000z-bbbbbbbb",
            expected_id="1" * 64,
            old_image="sha256:" + "1" * 64,
            new_image=config["image"],
            activation_sha256="a" * 64,
            manifest_sha256="c" * 64,
            accepted_env_sha256=hashlib.sha256(raw).hexdigest(),
            last_success_sha256=hashlib.sha256(before).hexdigest(),
        )
    )
    host = {
        key: None
        for key in (
            "ReadonlyRootfs",
            "CapDrop",
            "CapAdd",
            "SecurityOpt",
            "Memory",
            "NanoCpus",
            "PidsLimit",
            "Tmpfs",
            "PortBindings",
            "Mounts",
            "LogConfig",
            "NetworkMode",
        )
    }
    host["RestartPolicy"] = {"Name": "unless-stopped", "MaximumRetryCount": 0}
    host["PortBindings"] = {"10000/tcp": [{"HostIp": "127.0.0.1", "HostPort": str(request.param)}]}
    old = dict(
        Id=plan.expected_id,
        Image=plan.old_image,
        State=dict(Running=True),
        HostConfig=host,
        Config={
            **{key: None for key in ("User", "Entrypoint", "Cmd", "WorkingDir", "ExposedPorts")},
            "Env": raw.decode().splitlines(),
        },
        Mounts=[
            dict(
                Type="bind",
                Source=str(config["store"]),
                Destination="/var/lib/nla-catalog",
                RW=False,
            )
        ],
    )
    pointer = dict(currentManifestSha256="c" * 64, previousManifestSha256="d" * 64)
    c = SimpleNamespace(
        config=config,
        plan=plan,
        raw=raw,
        previous=previous,
        before=before,
        containers={"current": old},
        events=[],
        fail=None,
        pointer=pointer,
        locked=False,
        old_port=request.param,
        new_port=10001 if request.param == 10000 else 10000,
    )
    monkeypatch.setattr(m.a, "private_read", lambda p: p.read_bytes())
    monkeypatch.setattr(m.a, "sync_directory", lambda p: c.events.append(("sync", p)))
    monkeypatch.setattr(m.a, "pointer", lambda p: (pointer, "a" * 64))
    monkeypatch.setattr(m.a, "inspect", lambda name: copy.deepcopy(c.containers[name]))
    monkeypatch.setattr(m, "MARKET_PENDING", tmp_path / "market-pending")

    def systemctl(args, **kw):
        assert args[:2] == ["/usr/bin/systemctl", "show"]
        return SimpleNamespace(
            stdout="LoadState=loaded\nActiveState=inactive\nSubState=dead\nMainPID=0\nJob=\n"
        )

    monkeypatch.setattr(m.subprocess, "run", systemctl)

    def docker(*args):
        c.events.append(args)
        action = args[0]
        if action == "image":
            assert args == ("image", "inspect", plan.new_image)
            return json.dumps([{"Id": plan.new_image}])
        if action == "ps":
            return "\n".join(c.containers)
        if action == "create":
            new = copy.deepcopy(old)
            new.update(Id="2" * 64, Image=args[-1], State=dict(Running=False))
            port = args[args.index("-p") + 1].split(":")[1]
            new["HostConfig"]["PortBindings"]["10000/tcp"][0]["HostPort"] = port
            c.containers[args[2]] = new
            assert (root / "pending-run.json").exists()
            return new["Id"]
        if action == "rename":
            assert args[2] not in c.containers
            c.containers[args[2]] = c.containers.pop(args[1])
        elif action in {"stop", "start"}:
            c.containers[args[-1]]["State"]["Running"] = action == "start"
        elif action == "update":
            c.containers[args[-1]]["HostConfig"]["RestartPolicy"]["Name"] = args[2]
        else:
            pytest.fail(f"unexpected docker mutation: {args}")
        return ""

    monkeypatch.setattr(m.a, "docker", docker)

    def ready(runtime, name, identifier, pin, port):
        assert c.containers[name]["Id"] == identifier
        assert c.containers[name]["State"]["Running"]
        assert m.a.runtime_port(c.containers[name]) == port
        assert pin == "a" * 64
        c.events.append(("ready", identifier, port))
        if identifier == "2" * 64 and c.fail:
            raise c.fail

    monkeypatch.setattr(m.a, "ready", ready)

    @contextmanager
    def healthy(*args, **kwargs):
        yield SimpleNamespace(status=200)

    monkeypatch.setattr(
        m.a.urllib.request, "build_opener", lambda *args: SimpleNamespace(open=healthy)
    )

    @contextmanager
    def lock(_):
        c.locked = True
        yield
        c.locked = False

    monkeypatch.setattr(m.r, "pipeline_lock", lock)
    return c


def apply(c):
    return m.apply(c.plan, c.config, m.preflight(c.plan, c.config))


def test_success_preserves_data_env_original_receipt_and_age(case):
    c = case
    receipt = apply(c)
    assert receipt["kind"] == "image-upgrade"
    assert receipt["resources"] == {"runtime": "2" * 64, "replaced": "1" * 64}
    assert receipt["sourceStartedAt"] == c.previous["sourceStartedAt"]
    assert receipt["installationComplete"] is False
    assert (c.config["run_root"] / c.previous["run"] / "completed.json").read_bytes() == c.before
    assert (c.config["config"] / "accepted-runtime.env").read_bytes() == c.raw
    assert m.r.document(c.config["run_root"] / "last-success.json") == receipt
    assert (c.config["run_root"] / "pending-run.json").exists()
    assert c.containers["current"]["Image"] == c.plan.new_image
    assert m.a.runtime_port(c.containers["current"]) == c.new_port
    ready_index = c.events.index(("ready", "2" * 64, c.new_port))
    stop_index = next(i for i, event in enumerate(c.events) if event[0] == "stop")
    assert ready_index < stop_index
    assert (
        m.r.freshness(c.config)["sourceAgeSeconds"]
        >= int((datetime.now(UTC) - datetime(2026, 9, 25, tzinfo=UTC)).total_seconds()) - 2
    )
    with pytest.raises(m.a.InspectBeforeRetry):
        m.preflight(c.plan, c.config)


def test_readiness_failure_restores_same_old_container_and_receipt(case):
    c = case
    c.fail = RuntimeError("failed readiness")
    with pytest.raises(m.a.InspectBeforeRetry, match="old_runtime_restored"):
        apply(c)
    assert c.containers["current"]["Id"] == c.plan.expected_id
    assert c.containers["current"]["Image"] == c.plan.old_image
    assert c.containers["current"]["State"]["Running"]
    assert (c.config["run_root"] / "last-success.json").read_bytes() == c.before
    assert (
        m.r.document(c.config["run_root"] / c.plan.run_id / "rollback.json")["status"] == "restored"
    )
    assert not (c.config["run_root"] / c.plan.run_id / "completed.json").exists()
    assert (c.config["run_root"] / "pending-run.json").exists()
    assert not any(event[0] == "stop" and event[-1] == "current" for event in c.events)
    failed = c.containers["nla-image-" + c.plan.run_id + "-failed"]
    assert not failed["State"]["Running"]
    assert failed["HostConfig"]["RestartPolicy"]["Name"] == "no"


def test_interrupt_keeps_pending_and_never_claims_completion(case):
    case.fail = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        apply(case)
    assert (case.config["run_root"] / "last-success.json").read_bytes() == case.before
    assert (case.config["run_root"] / "pending-run.json").exists()


@pytest.mark.parametrize("failure", ["image", "runtime", "env", "pointer", "pending", "market"])
def test_preflight_mismatch_never_creates_runtime(case, failure):
    c = case
    if failure == "image":
        c.containers["current"]["Image"] = c.plan.new_image
    elif failure == "runtime":
        c.containers["current"]["Id"] = "9" * 64
    elif failure == "env":
        (c.config["config"] / "accepted-runtime.env").write_bytes(b"changed")
    elif failure == "pointer":
        c.pointer["currentManifestSha256"] = "9" * 64
    elif failure == "pending":
        (c.config["run_root"] / "pending-run.json").write_text("{}")
    else:
        m.MARKET_PENDING.write_text("{}")
    with pytest.raises((ValueError, m.a.InspectBeforeRetry)):
        m.preflight(c.plan, c.config)
    assert not any(event[0] == "create" for event in c.events)


@pytest.mark.parametrize(
    "property", ["ActiveState=active", "MainPID=123", "Job=4", "LoadState=not-found"]
)
def test_active_or_unknown_units_are_rejected(case, monkeypatch, property):
    key = property.split("=")[0]
    values = dict(LoadState="loaded", ActiveState="inactive", SubState="dead", MainPID="0", Job="")
    values[key] = property.split("=")[1]
    monkeypatch.setattr(
        m.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(stdout="\n".join(k + "=" + v for k, v in values.items())),
    )
    with pytest.raises(ValueError, match="idle"):
        m.idle()


def test_default_cli_preflight_does_not_apply(case, monkeypatch):
    path = case.config["run_root"] / "plan.json"
    path.write_text(json.dumps(vars(case.plan)))
    monkeypatch.setattr(m.r, "configuration", lambda _: case.config)
    assert m.main(["--plan", str(path)]) == 0
    assert not (case.config["run_root"] / "pending-run.json").exists()
    assert not any(event[0] == "create" for event in case.events)


@pytest.mark.parametrize("failed_receipt", ["completed.json", "last-success.json"])
def test_publication_failure_never_rolls_back_after_possible_commit(
    case, monkeypatch, failed_receipt
):
    native = m.r.publish

    def publish(path, value, **kwargs):
        native(path, value, **kwargs)
        if path.name == failed_receipt:
            raise OSError("ambiguous durable write")

    monkeypatch.setattr(m.r, "publish", publish)
    with pytest.raises(m.a.InspectBeforeRetry, match="publication"):
        apply(case)
    assert case.containers["current"]["Id"] == "2" * 64
    assert (case.config["run_root"] / "pending-run.json").exists()
    assert not any(event[0] == "stop" for event in case.events)
    assert case.containers["nla-image-" + case.plan.run_id + "-before"]["State"]["Running"]


@pytest.mark.parametrize(
    "bindings",
    [
        None,
        {"10000/tcp": [{"HostIp": "0.0.0.0", "HostPort": "10000"}]},  # noqa: S104 -- rejected
        {"10000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "10002"}]},
    ],
)
def test_unsafe_or_unknown_port_binding_never_creates_runtime(case, bindings):
    case.containers["current"]["HostConfig"]["PortBindings"] = bindings
    with pytest.raises(m.a.InspectBeforeRetry, match="port_binding"):
        m.preflight(case.plan, case.config)
    assert not any(event[0] == "create" for event in case.events)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("expected_id", "latest"),
        ("old_image", None),
        ("new_image", "sha256:" + "1" * 64),
        ("run_id", "../existing"),
        ("config", "/path/../config.json"),
        ("config", "relative.json"),
        ("config", "/config\n.json"),
    ],
)
def test_invalid_plan_rejected(case, key, value):
    with pytest.raises(ValueError):
        m.load_plan({**vars(case.plan), key: value})


def test_external_pointer_change_prevents_automatic_rollback(case, monkeypatch):
    def changed(*args):
        case.pointer["currentManifestSha256"] = "9" * 64
        raise RuntimeError("external change")

    monkeypatch.setattr(m.a, "ready", changed)
    with pytest.raises(m.a.InspectBeforeRetry, match="dataset_or_accepted"):
        apply(case)
    assert case.containers["current"]["Id"] == case.plan.expected_id
    assert (case.config["run_root"] / "last-success.json").read_bytes() == case.before
    assert (case.config["run_root"] / "pending-run.json").exists()


def test_candidate_creation_failure_never_stops_previous_runtime(case, monkeypatch):
    def failed(*args):
        raise RuntimeError("ambiguous create")

    monkeypatch.setattr(m.a, "create_runtime", failed)
    with pytest.raises(RuntimeError, match="ambiguous create"):
        apply(case)
    assert case.containers["current"]["Id"] == case.plan.expected_id
    assert case.containers["current"]["State"]["Running"]
    assert not any(event[0] == "stop" for event in case.events)
    assert (case.config["run_root"] / "pending-run.json").exists()
