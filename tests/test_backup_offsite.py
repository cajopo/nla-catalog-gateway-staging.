"""Backup contract tests use no network, production files or credentials."""

import json
import stat
import subprocess
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts import backup_offsite as backup


@pytest.fixture
def config(tmp_path, monkeypatch):
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
        "command_timeout_seconds": 30,
    }


def capture(config, destination):
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
    def invoke(binary, arguments, env, timeout):
        commands.append(arguments)
        assert binary == "/verified/restic" and timeout == 30
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


def test_failed_job_retained_and_never_replaces_success(config, publications):
    def fail(*args):
        raise backup.BackupError("restic_failed")

    result = backup.run(config, capture=capture, run_command=fail, lock=lambda _: nullcontext())
    assert result["status"] == "failed"
    root = Path(config["state_root"])
    assert (root / "jobs" / result["jobId"] / "checkpoint" / "manifest.json").exists()
    assert root / "last-success.json" not in publications
    with pytest.raises(backup.BackupError, match="retained_job"):
        backup.run(config, lock=lambda _: nullcontext())


def test_busy_skip(config, publications):
    def busy(*args):
        raise BlockingIOError

    assert backup.run(config, lock=busy)["status"] == "skipped_busy"

    def busy_capture(*args):
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


@pytest.mark.parametrize("code", [1, 3, 10, 11, 12, 130, 254])
def test_all_nonzero_exit_codes_fail(monkeypatch, code):
    monkeypatch.setattr(
        backup.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=code, stdout=b"secret")
    )
    with pytest.raises(backup.BackupError, match="restic_failed"):
        backup.command("/restic", ["backup"], {}, 1)


@pytest.mark.parametrize(
    "error,reason",
    [
        (subprocess.TimeoutExpired("restic", 1, output=b"secret"), "restic_timeout"),
        (OSError("secret"), "restic_unavailable"),
    ],
)
def test_command_errors_are_value_free(monkeypatch, error, reason):
    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(backup.subprocess, "run", fail)
    with pytest.raises(backup.BackupError, match=reason) as failure:
        backup.command("/restic", [], {}, 1)
    assert "secret" not in str(failure.value)


def test_command_owned_and_sanitized(monkeypatch):
    def invoke(args, **kwargs):
        assert args == ["/restic", "--json", "--no-cache", "check"]
        assert kwargs["stderr"] == subprocess.DEVNULL
        assert kwargs["stdin"] == subprocess.DEVNULL
        assert kwargs["timeout"] == 1 and kwargs["env"] == {"safe": "value"}
        return SimpleNamespace(returncode=0, stdout=b"ok")

    monkeypatch.setattr(backup.subprocess, "run", invoke)
    assert backup.command("/restic", ["check"], {"safe": "value"}, 1) == "ok"
    monkeypatch.setattr(
        backup.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout=b"\xff")
    )
    with pytest.raises(backup.BackupError, match="invalid_restic_output"):
        backup.command("/restic", [], {}, 1)


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
def test_backup_requires_full_snapshot(config, tmp_path, response):
    with pytest.raises(backup.BackupError, match="invalid_snapshot"):
        backup.transfer(
            config,
            tmp_path,
            {},
            {},
            "job",
            lambda *a: json.dumps({"message_type": "summary", **response}),
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
def test_snapshot_binding_rejected(config, tmp_path, change):
    commands = []
    base = runner(commands)

    def invoke(*args):
        output = base(*args)
        return json.dumps(change(json.loads(output))) if args[1][0] == "snapshots" else output

    with pytest.raises(backup.BackupError):
        backup.transfer(config, tmp_path, {}, {}, "job", invoke)


@pytest.mark.parametrize(
    "check", [{}, {"num_errors": 1}, {"num_errors": 0, "broken_packs": ["pack"]}]
)
def test_integrity_failures(config, tmp_path, check):
    commands = []
    base = runner(commands)

    def invoke(*args):
        output = base(*args)
        return json.dumps({"message_type": "summary", **check}) if args[1][0] == "check" else output

    with pytest.raises(backup.BackupError, match="integrity_check_failed"):
        backup.transfer(config, tmp_path, {"createdAt": "fixture"}, {}, "job", invoke)


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
def test_cleanup_rejects_manifest_escape(config, tmp_path, filename):
    job = tmp_path / "job"
    job.mkdir()
    captured = job / "checkpoint"
    captured.mkdir()
    (captured / "manifest.json").write_text("{}")
    with pytest.raises(backup.BackupError, match="unsafe_cleanup_manifest"):
        backup.cleanup(job, captured, {"files": [{"filename": filename}], "images": []}, "a" * 64)


def test_cleanup_duplicate(config, tmp_path):
    job = tmp_path / "job"
    job.mkdir()
    captured = job / "checkpoint"
    captured.mkdir()
    with pytest.raises(backup.BackupError, match="duplicate_cleanup_file"):
        backup.cleanup(
            job, captured, {"files": [{"filename": "manifest.json"}], "images": []}, "a" * 64
        )


@pytest.mark.parametrize("location", ["checkpoint", "home/file"])
def test_busy_artifacts_fail_closed(config, publications, location):
    def busy_capture(config, destination):
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
        ("command_timeout_seconds", True),
        ("command_timeout_seconds", 0),
        ("command_timeout_seconds", 7201),
        ("restic_binary", "/bad"),
    ]:
        changed = {**config, field: value}
        path.write_text(json.dumps(changed))
        with pytest.raises(backup.BackupError):
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
    monkeypatch.setattr(backup.sys, "platform", "win32")
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
    assert "ExecStartPre" not in service and "ExecStopPost" not in service
    assert "01:00:00 UTC" in timer and "Persistent=false" in timer
