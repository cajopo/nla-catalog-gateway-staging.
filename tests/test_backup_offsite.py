"""Backup contract tests use no network, production files or credentials."""

import json
import stat
import subprocess
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts import backup_offsite as backup


@pytest.fixture
def clock(monkeypatch):
    state = SimpleNamespace(seconds=100, moment=datetime(2026, 10, 15, 1, tzinfo=UTC))

    class Clock(datetime):
        @classmethod
        def now(cls, timezone):
            return state.moment

    monkeypatch.setattr(backup, "datetime", Clock)
    monkeypatch.setattr(backup, "time", SimpleNamespace(monotonic=lambda: state.seconds))
    return state


@pytest.fixture
def config(tmp_path, monkeypatch, clock):
    monkeypatch.setattr(backup, "protected", lambda path, **kwargs: Path(path))
    (tmp_path / "manifest.json").write_text("{}")
    passphrase_path, credentials = tmp_path / "password", tmp_path / "credentials.json"
    passphrase_path.write_text("fixture password")
    credentials.write_text(
        json.dumps({"AWS_ACCESS_KEY_ID": "fixture", "AWS_SECRET_ACCESS_KEY": "secret"})
    )
    return {
        "state_root": str(tmp_path),
        "password_file": str(passphrase_path),
        "credential_file": str(credentials),
        "restic_binary": "/verified/restic",
        "checkpoint": {},
        "integrity_mode": "metadata",
        "job_timeout_seconds": 30,
        "schedule_guard_seconds": 300,
    }


@pytest.fixture
def budget(config):
    return backup.JobBudget(config)


def capture(config, destination, *, deadline):
    assert deadline == 130
    destination.mkdir()
    data = destination / "files" / "0000"
    data.parent.mkdir()
    data.write_text("coherent checkpoint")
    manifest = {
        "createdAt": "2026-10-15T01:00:00+00:00",
        "files": [{"filename": "files/0000", "sha256": backup.digest(data)}],
        "images": [],
    }
    (destination / "manifest.json").write_text(json.dumps(manifest))
    return manifest


def runner(commands, *, mutate=None):
    def invoke(binary, arguments, env, deadline):
        commands.append(arguments)
        assert binary == "/verified/restic" and deadline == 130
        if arguments[0] == "backup":
            if mutate:
                mutate(Path(arguments[-1]))
            return json.dumps({"message_type": "summary", "snapshot_id": "a" * 64})
        if arguments[0] == "snapshots":
            upload = commands[0]
            return json.dumps(
                [
                    {
                        "id": "a" * 64,
                        "paths": [upload[-1]],
                        "tags": [upload[-2]],
                        "hostname": backup.HOST,
                        "time": "2026-10-15T01:00:00Z",
                    }
                ]
            )
        return '{"message_type":"summary","num_errors":0}'

    return invoke


@pytest.fixture
def publications(monkeypatch):
    documents = {}
    monkeypatch.setattr(
        backup, "publish", lambda path, value, **kwargs: documents.update({path: dict(value)})
    )
    return documents


def test_complete_recurs_and_leaves_private_terminal_receipts(config, publications, monkeypatch):
    monkeypatch.setenv("RESTIC_PASSWORD", "must-not-inherit")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "must-not-inherit")
    for mode in ("metadata", "read-data"):
        commands = []
        config["integrity_mode"] = mode
        result = backup.run(
            config, capture=capture, run_command=runner(commands), lock=lambda _: nullcontext()
        )
        assert result["status"] == "complete"
        assert result["snapshotId"] == "a" * 64
        assert result["integrityMode"] == mode
        assert len(result["checkpointManifestSha256"]) == 64
        assert commands[-1] == (["check"] if mode == "metadata" else ["check", "--read-data"])
        assert not list((Path(config["state_root"]) / "jobs").iterdir())
    assert len(publications) == 3
    assert all("secret" not in json.dumps(receipt) for receipt in publications.values())


def test_environment_allowlist(config, tmp_path):
    job = tmp_path / "job"
    job.mkdir()
    env = backup.environment(config, job)
    assert set(env) == {
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "RESTIC_REPOSITORY",
        "RESTIC_PASSWORD_FILE",
        "AWS_DEFAULT_REGION",
        "GOMAXPROCS",
        "PATH",
        "HOME",
        "TMPDIR",
    }
    assert env["RESTIC_REPOSITORY"] == backup.REPOSITORY


@pytest.mark.parametrize(
    "content",
    [
        "{}",
        "[]",
        "not-json",
        '{"AWS_ACCESS_KEY_ID":"", "AWS_SECRET_ACCESS_KEY":"x"}',
        '{"AWS_ACCESS_KEY_ID":7,"AWS_SECRET_ACCESS_KEY":"x"}',
        '{"AWS_ACCESS_KEY_ID":"x\\n", "AWS_SECRET_ACCESS_KEY":"x"}',
    ],
)
def test_bad_credentials(config, tmp_path, content):
    Path(config["credential_file"]).write_text(content)
    with pytest.raises(backup.BackupError):
        backup.environment(config, tmp_path)


def test_empty_password(config, tmp_path):
    Path(config["password_file"]).write_text("\n")
    with pytest.raises(backup.BackupError, match="empty_password"):
        backup.environment(config, tmp_path)


@pytest.mark.parametrize(
    "reason", ["restic_failed", "restic_output_limit", "restic_timeout", "restic_reap_failed"]
)
def test_failed_job_retained_and_never_replaces_success(config, publications, reason):
    def fail(*args):
        raise backup.BackupError(reason)

    result = backup.run(config, capture=capture, run_command=fail, lock=lambda _: nullcontext())
    assert result["status"] == "failed"
    assert result["failureCode"] == reason
    root = Path(config["state_root"])
    assert (root / "jobs" / result["jobId"] / "checkpoint" / "manifest.json").exists()
    assert root / "last-success.json" not in publications
    with pytest.raises(backup.BackupError, match="retained_job"):
        backup.run(config, lock=lambda _: nullcontext())


def test_whole_job_deadline_spans_capture_and_multiple_commands(config, publications, clock):
    received = []
    base = runner([])

    def advancing(*args):
        received.append(args[-1])
        output = base(*args)
        clock.seconds += 10
        return output

    result = backup.run(
        config, capture=capture, run_command=advancing, lock=lambda _: nullcontext()
    )
    assert received == [130, 130, 130]
    assert result["status"] == "failed" and result["failureCode"] == "job_timeout"
    assert result["snapshotId"] == "a" * 64 and "integrityStatus" not in result
    assert (Path(config["state_root"]) / "jobs" / result["jobId"] / "checkpoint").is_dir()
    assert Path(config["state_root"]) / "last-success.json" not in publications


def test_capture_timeout_keeps_checkpoint_and_never_starts_restic(config, publications, clock):
    calls = []

    def late_capture(*args, **kwargs):
        value = capture(*args, **kwargs)
        clock.seconds = kwargs["deadline"]
        return value

    result = backup.run(
        config, capture=late_capture, run_command=runner(calls), lock=lambda _: nullcontext()
    )
    assert result["status"] == "failed" and result["reason"] == "checkpoint_failed"
    assert result["failureCode"] == "job_timeout" and not calls
    assert (
        Path(config["state_root"]) / "jobs" / result["jobId"] / "checkpoint" / "manifest.json"
    ).exists()
    assert Path(config["state_root"]) / "last-success.json" not in publications


def test_cleanup_hashing_expires_before_any_unlink(config, publications, clock, monkeypatch):
    original = backup.digest

    def slow(path, *, budget=None):
        if budget is not None and path.name == "0000":
            clock.seconds = budget.deadline
        return original(path, budget=budget)

    monkeypatch.setattr(backup, "digest", slow)
    result = backup.run(
        config, capture=capture, run_command=runner([]), lock=lambda _: nullcontext()
    )
    assert result["reason"] == "cleanup_failed" and result["failureCode"] == "job_timeout"
    assert result["integrityStatus"] == "passed" and result["snapshotId"] == "a" * 64
    retained = Path(config["state_root"]) / "jobs" / result["jobId"] / "checkpoint"
    assert (retained / "manifest.json").exists() and (retained / "files" / "0000").exists()
    assert Path(config["state_root"]) / "last-success.json" not in publications


@pytest.mark.parametrize(
    "hour,minute,second", [(1, 59, 0), (2, 0, 0), (3, 0, 0), (14, 0, 0), (15, 0, 0)]
)
def test_near_schedule_skips_without_artifacts(config, publications, clock, hour, minute, second):
    clock.moment = clock.moment.replace(hour=hour, minute=minute, second=second)
    result = backup.run(config, lock=lambda _: pytest.fail("must skip before lock"))
    assert result["status"] == "skipped_busy" and not publications
    assert not (Path(config["state_root"]) / "jobs").exists()


def test_budget_schedule_exact_admission_boundary_and_next_day(config, clock):
    clock.moment = clock.moment.replace(hour=1, minute=54, second=30)
    assert backup.JobBudget(config).remaining() == 30
    clock.moment = clock.moment.replace(second=31)
    with pytest.raises(backup.checkpoint.CheckpointBusy):
        backup.JobBudget(config)
    clock.moment = clock.moment.replace(hour=15, minute=1)
    assert backup.JobBudget(config).deadline == 130


def test_busy_skip(config, publications):
    def busy(*args):
        raise BlockingIOError

    assert backup.run(config, lock=busy)["status"] == "skipped_busy"

    def busy_capture(*args, **kwargs):
        raise backup.checkpoint.CheckpointBusy("checkpoint busy")

    assert (
        backup.run(config, capture=busy_capture, lock=lambda _: nullcontext())["status"]
        == "skipped_busy"
    )
    assert len(publications) == 1
    result = backup.run(
        config, capture=capture, run_command=runner([]), lock=lambda _: nullcontext()
    )
    assert result["status"] == "complete"


def test_expired_busy_capture_does_not_remove_even_empty_owned_directories(
    config, publications, clock
):
    def busy(*args, **kwargs):
        clock.seconds = kwargs["deadline"]
        raise backup.checkpoint.CheckpointBusy("checkpoint busy")

    result = backup.run(config, capture=busy, lock=lambda _: nullcontext())
    assert result["status"] == "failed" and result["failureCode"] == "job_timeout"
    job = Path(config["state_root"]) / "jobs" / result["jobId"]
    assert {path.name for path in job.iterdir()} == {"home", "tmp"}
    assert Path(config["state_root"]) / "last-success.json" not in publications


@pytest.fixture
def child(monkeypatch, clock):
    state = SimpleNamespace(
        chunks=[b"ok", b""],
        status=0,
        launch_error=None,
        wait_errors=[],
        ready=[True],
        closed=False,
        killed=False,
        waits=[],
        calls=[],
    )

    class Pipe:
        def fileno(self):
            return 12

        def close(self):
            state.closed = True

    class Process:
        def __init__(self, arguments, **kwargs):
            state.calls.append((arguments, kwargs))
            if state.launch_error:
                raise state.launch_error
            self.stdout = Pipe()
            self.running = True

        def poll(self):
            return None if self.running else state.status

        def wait(self, *, timeout):
            state.waits.append(timeout)
            if state.wait_errors:
                raise state.wait_errors.pop(0)
            self.running = False
            return state.status

        def kill(self):
            state.killed = True

    def read(descriptor, maximum):
        assert descriptor == 12 and maximum == 65536
        chunk = state.chunks.pop(0)
        if isinstance(chunk, Exception):
            raise chunk
        return chunk

    def select(inputs, writers, errors, timeout):
        assert timeout <= 0.25 and not writers and not errors
        ready = state.ready.pop(0) if len(state.ready) > 1 else state.ready[0]
        return (inputs if ready else [], [], [])

    monkeypatch.setattr(backup, "os", SimpleNamespace(read=read))
    monkeypatch.setattr(backup, "select", SimpleNamespace(select=select))
    monkeypatch.setattr(
        backup,
        "subprocess",
        SimpleNamespace(
            Popen=Process,
            DEVNULL=subprocess.DEVNULL,
            PIPE=subprocess.PIPE,
            TimeoutExpired=subprocess.TimeoutExpired,
        ),
    )
    return state


@pytest.mark.parametrize("code", [1, 3, 10, 11, 12, 130, 254])
def test_all_nonzero_exit_codes_fail(child, code):
    child.status = code
    child.chunks = [b"secret", b""]
    with pytest.raises(backup.BackupError, match="restic_failed"):
        backup.command("/restic", ["backup"], {}, 101)
    assert child.closed and not child.killed


@pytest.mark.parametrize(
    "error,reason",
    [
        (subprocess.TimeoutExpired("restic", 1, output=b"secret"), "restic_timeout"),
        (OSError("secret"), "restic_unavailable"),
    ],
)
def test_command_errors_are_value_free(child, error, reason):
    child.launch_error = error
    with pytest.raises(backup.BackupError, match=reason) as failure:
        backup.command("/restic", [], {}, 101)
    assert "secret" not in str(failure.value)


def test_command_owned_and_sanitized(child):
    child.ready = [False, True]
    assert backup.command("/restic", ["check"], {"safe": "value"}, 101) == "ok"
    args, kwargs = child.calls[0]
    assert args == ["/restic", "--json", "--no-cache", "check"]
    assert kwargs["stderr"] == subprocess.DEVNULL and kwargs["stdin"] == subprocess.DEVNULL
    assert kwargs["env"] == {"safe": "value"} and kwargs["bufsize"] == 0
    assert child.closed and child.waits == [1, 10] and not child.killed
    child.chunks = [b"\xff", b""]
    with pytest.raises(backup.BackupError, match="invalid_restic_output"):
        backup.command("/restic", [], {}, 101)


def test_stdout_cap_is_enforced_during_acquisition_and_reaps_owned_child(child):
    child.chunks = [b"x" * 65536] * (backup.MAX_STDOUT_BYTES // 65536 + 1)
    with pytest.raises(backup.BackupError, match="restic_output_limit"):
        backup.command("/restic", ["backup"], {}, 101)
    assert child.killed and child.closed and child.waits == [10]


def test_command_elapsed_deadline_and_wait_timeout_reap_child(child, clock):
    with pytest.raises(backup.BackupError, match="job_timeout"):
        backup.command("/restic", [], {}, 100)
    assert not child.calls
    child.wait_errors = [subprocess.TimeoutExpired("owned", 1)]
    with pytest.raises(backup.BackupError, match="restic_timeout"):
        backup.command("/restic", [], {}, 101)
    assert child.killed and child.closed and child.waits == [1, 10]


@pytest.mark.parametrize("stage", ["read", "eof"])
def test_deadline_is_checked_while_child_streams(child, clock, monkeypatch, stage):
    def read(*args):
        clock.seconds = 101
        return b"x" if stage == "read" else b""

    monkeypatch.setattr(backup.os, "read", read)
    with pytest.raises(backup.BackupError, match="restic_timeout"):
        backup.command("/restic", [], {}, 101)
    assert child.killed and child.closed


def test_read_error_and_failed_reaping_are_sanitized(child):
    child.chunks = [OSError("secret")]
    with pytest.raises(backup.BackupError, match="restic_unavailable"):
        backup.command("/restic", [], {}, 101)
    assert child.killed and child.closed
    child.chunks = [b""]
    child.wait_errors = [subprocess.TimeoutExpired("owned", 1), OSError("secret")]
    with pytest.raises(backup.BackupError, match="restic_reap_failed") as failure:
        backup.command("/restic", [], {}, 101)
    assert "secret" not in str(failure.value) and child.closed


def test_termination_during_read_reaps_owned_child(child):
    child.chunks = [backup.BackupError("job_terminated")]
    with pytest.raises(backup.BackupError, match="job_terminated"):
        backup.command("/restic", [], {}, 101)
    assert child.killed and child.closed and child.waits == [10]


@pytest.mark.parametrize(
    "output",
    [
        "",
        "{}",
        "[]",
        "invalid",
        '{"message_type":"summary"}\n{}',
        '{"message_type":"summary"}\n{"message_type":"summary"}',
    ],
)
def test_summary_requires_final_unique_object(output):
    with pytest.raises(backup.BackupError):
        backup.summary(output)


@pytest.mark.parametrize(
    "response",
    [{}, {"snapshot_id": "abcd"}, {"snapshot_id": 3}, {"snapshot_id": "a" * 64, "dry_run": True}],
)
def test_backup_requires_full_snapshot(config, tmp_path, response, budget):
    with pytest.raises(backup.BackupError, match="invalid_snapshot"):
        backup.transfer(
            config,
            tmp_path,
            {},
            {},
            "job",
            lambda *a: json.dumps({"message_type": "summary", **response}),
            budget=budget,
        )


@pytest.mark.parametrize(
    "change",
    [
        lambda _: [],
        lambda _: {},
        lambda rows: [{**rows[0], "id": "b" * 64}],
        lambda rows: [{**rows[0], "paths": ["wrong"]}],
        lambda rows: [{**rows[0], "tags": ["wrong"]}],
        lambda rows: [{**rows[0], "hostname": "wrong"}],
        lambda rows: [{**rows[0], "time": "invalid"}],
        lambda _: [{}],
    ],
)
def test_snapshot_binding_rejected(config, tmp_path, change, budget):
    commands = []
    base = runner(commands)

    def invoke(*args):
        output = base(*args)
        return json.dumps(change(json.loads(output))) if args[1][0] == "snapshots" else output

    with pytest.raises(backup.BackupError):
        backup.transfer(config, tmp_path, {}, {}, "job", invoke, budget=budget)


@pytest.mark.parametrize(
    "check", [{}, {"num_errors": 1}, {"num_errors": 0, "broken_packs": ["pack"]}]
)
def test_integrity_failures(config, tmp_path, check, budget):
    commands = []
    base = runner(commands)

    def invoke(*args):
        output = base(*args)
        return json.dumps({"message_type": "summary", **check}) if args[1][0] == "check" else output

    with pytest.raises(backup.BackupError, match="integrity_check_failed"):
        backup.transfer(
            config, tmp_path, {"createdAt": "fixture"}, {}, "job", invoke, budget=budget
        )


def test_failed_remote_check_retains_bound_snapshot(config, publications):
    base = runner([])

    def invoke(*args):
        if args[1][0] == "check":
            raise backup.BackupError("restic_failed")
        return base(*args)

    result = backup.run(config, capture=capture, run_command=invoke, lock=lambda _: nullcontext())
    assert result["status"] == "failed" and result["reason"] == "transfer_failed"
    assert result["snapshotId"] == "a" * 64
    assert "integrityStatus" not in result
    assert len(result["checkpointManifestSha256"]) == 64
    assert Path(config["state_root"]) / "last-success.json" not in publications


@pytest.mark.parametrize(
    "mutation",
    [
        lambda path: (path / "extra").write_text("unexpected"),
        lambda path: (path / "files" / "0000").write_text("changed"),
        lambda path: (path / "manifest.json").write_text("changed manifest"),
    ],
)
def test_cleanup_retains_changed_jobs(config, publications, mutation):
    result = backup.run(
        config,
        capture=capture,
        run_command=runner([], mutate=mutation),
        lock=lambda _: nullcontext(),
    )
    # Manifest mutation precedes transfer digest, so hashes alone cannot detect it;
    # transfer must bind the original captured manifest before invoking restic.
    assert result["status"] == "failed"


@pytest.mark.parametrize("filename", ["../escape", "", "/absolute"])
def test_cleanup_rejects_manifest_escape(config, tmp_path, filename, budget):
    job = tmp_path / "job"
    job.mkdir()
    captured = job / "checkpoint"
    captured.mkdir()
    (captured / "manifest.json").write_text("{}")
    with pytest.raises(backup.BackupError, match="unsafe_cleanup_manifest"):
        backup.cleanup(
            job,
            captured,
            {"files": [{"filename": filename}], "images": []},
            "a" * 64,
            budget=budget,
        )


def test_cleanup_duplicate(config, tmp_path, budget):
    job = tmp_path / "job"
    job.mkdir()
    captured = job / "checkpoint"
    captured.mkdir()
    with pytest.raises(backup.BackupError, match="duplicate_cleanup_file"):
        backup.cleanup(
            job,
            captured,
            {"files": [{"filename": "manifest.json"}], "images": []},
            "a" * 64,
            budget=budget,
        )


@pytest.mark.parametrize("location", ["checkpoint", "home/file"])
def test_busy_artifacts_fail_closed(config, publications, location):
    def busy_capture(config, destination, *, deadline):
        unexpected = destination.parent / location
        unexpected.write_text("retained")
        raise backup.checkpoint.CheckpointBusy("checkpoint busy")

    result = backup.run(config, capture=busy_capture, lock=lambda _: nullcontext())
    assert result["status"] == "failed"
    assert result["reason"] == "busy_job_has_artifacts"
    assert (Path(config["state_root"]) / "jobs" / result["jobId"] / location).exists()


@pytest.mark.parametrize("mode", [0o600, 0o700])
def test_binary_must_be_executable_and_hash_pinned(config, tmp_path, monkeypatch, mode):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    monkeypatch.setattr(Path, "stat", lambda self, **kwargs: SimpleNamespace(st_mode=mode))
    monkeypatch.setattr(backup, "digest", lambda _: "wrong")
    with pytest.raises(backup.BackupError, match="unverified_restic_binary"):
        backup.load_config(path)


def test_load_config(config, tmp_path, monkeypatch):
    binary = tmp_path / "restic"
    binary.write_text("fixture")
    config["restic_binary"] = str(binary)
    monkeypatch.setattr(backup, "RESTIC_SHA256", backup.digest(binary))
    monkeypatch.setattr(Path, "stat", lambda self, **kwargs: SimpleNamespace(st_mode=0o700))
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    assert backup.load_config(path) == config
    for field, value in [
        ("integrity_mode", "bad"),
        ("job_timeout_seconds", True),
        ("job_timeout_seconds", 0),
        ("job_timeout_seconds", 2701),
        ("schedule_guard_seconds", True),
        ("schedule_guard_seconds", 299),
        ("schedule_guard_seconds", 3601),
        ("restic_binary", "/bad"),
    ]:
        changed = {**config, field: value}
        path.write_text(json.dumps(changed))
        with pytest.raises(backup.BackupError):
            backup.load_config(path)
    legacy = {
        key: value
        for key, value in config.items()
        if key not in {"job_timeout_seconds", "schedule_guard_seconds"}
    }
    path.write_text(json.dumps({**legacy, "command_timeout_seconds": 7200}))
    with pytest.raises(backup.BackupError, match="invalid_config"):
        backup.load_config(path)
    path.write_text("{}")
    with pytest.raises(backup.BackupError, match="invalid_config"):
        backup.load_config(path)
    path.write_text("bad json")
    with pytest.raises(backup.BackupError, match="invalid_config"):
        backup.load_config(path)


def test_publish_atomic_private(tmp_path, monkeypatch):
    monkeypatch.setattr(backup.os, "open", lambda *args: 321)
    monkeypatch.setattr(backup.os, "close", lambda descriptor: None)
    monkeypatch.setattr(backup.os, "fsync", lambda descriptor: None)
    path = tmp_path / "receipt.json"
    backup.publish(path, {"status": "complete"})
    assert json.loads(path.read_text()) == {"status": "complete"}
    with pytest.raises(FileExistsError):
        backup.publish(path, {"status": "failed"})
    backup.publish(path, {"status": "second"}, replace=True)
    assert json.loads(path.read_text()) == {"status": "second"}


def test_main_platform_and_fixed_failures(monkeypatch, capsys):
    monkeypatch.setattr(backup, "sys", SimpleNamespace(platform="win32"))
    assert backup.main(["--config", "anything"]) == 1
    monkeypatch.setattr(backup.sys, "platform", "linux")
    monkeypatch.setattr(backup.os, "geteuid", lambda: 1, raising=False)
    assert backup.main(["--config", "anything"]) == 1
    monkeypatch.setattr(backup.os, "geteuid", lambda: 0)
    monkeypatch.setattr(backup.os, "umask", lambda mode: None)
    monkeypatch.setattr(backup, "load_config", lambda path: {})
    for status, expected in [("complete", 0), ("skipped_busy", 0), ("failed", 1)]:
        monkeypatch.setattr(
            backup, "run", lambda config, status=status: {"status": status, "jobId": "fixture"}
        )
        assert backup.main(["--config", "anything"]) == expected
    assert "secret" not in capsys.readouterr().out


def test_termination_is_value_free():
    with pytest.raises(backup.BackupError, match="job_terminated"):
        backup.terminated()


def test_protected_contract(tmp_path, monkeypatch):
    path = tmp_path / "input"
    path.write_text("fixture")
    real_lstat = Path.lstat

    def facts(self, **kwargs):
        if self == path:
            return SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_uid=0, st_nlink=1)
        return SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_uid=0, st_nlink=1)

    monkeypatch.setattr(Path, "lstat", facts)
    assert backup.protected(path, private=True) == path
    for change in [
        {"st_mode": stat.S_IFREG | 0o644},
        {"st_uid": 1},
        {"st_nlink": 2},
        {"st_mode": stat.S_IFDIR | 0o700},
    ]:

        def unsafe(self, change=change, **kwargs):
            value = facts(self)
            return SimpleNamespace(**{**vars(value), **change}) if self == path else value

        monkeypatch.setattr(Path, "lstat", unsafe)
        with pytest.raises(backup.BackupError):
            backup.protected(path, private=True)
    monkeypatch.setattr(
        Path,
        "lstat",
        lambda self: SimpleNamespace(
            st_mode=stat.S_IFDIR | (0o700 if self == tmp_path else 0o777),
            st_uid=0,
            st_nlink=1,
        ),
    )
    with pytest.raises(backup.BackupError, match="unsafe_parent"):
        backup.protected(tmp_path, directory=True)
    monkeypatch.setattr(Path, "lstat", real_lstat)
    with pytest.raises(backup.BackupError, match="unsafe_path"):
        backup.protected(Path("relative"))


def test_systemd_templates():
    root = Path(__file__).resolve().parents[1] / "ops" / "systemd"
    service = (root / "nla-backup-offsite.service.in").read_text()
    timer = (root / "nla-backup-offsite.timer.in").read_text()
    assert "User=root" in service and "UMask=0077" in service
    assert "KillMode=control-group" in service and "CPUQuota=50%" in service
    assert "MemoryMax=768M" in service and "ProtectSystem=strict" in service
    assert "TimeoutStartSec=47min" in service and "TimeoutStopSec=30s" in service
    assert "ExecStartPre" not in service and "ExecStopPost" not in service
    assert "01:00:00 UTC" in timer and "Persistent=false" in timer
