"""Bounded retention: synthetic files and simulated Docker, never live resources."""

import hashlib
import json
import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts import refresh_staging_catalog as refresh


@pytest.fixture
def retained(tmp_path, monkeypatch):
    root, store = tmp_path / "runs", tmp_path / "store"
    root.mkdir()
    (store / "generations").mkdir(parents=True)
    config = {"run_root": root, "store": store, "current": "current"}
    receipts, containers, removed = [], {}, []
    for number in range(3):
        run = root / f"2026092{number}t120000z-aaaaaaaa"
        run.mkdir()
        raw = f"synthetic manifest {number}".encode()
        manifest = hashlib.sha256(raw).hexdigest()
        generation = store / "generations" / manifest
        generation.mkdir()
        (generation / "staging-generation-manifest.v1.json").write_bytes(raw)
        (run / "capture.txt").write_text("synthetic data")
        resource = {
            role: f"{number * 10 + i + 1:064x}"
            for i, role in enumerate(("runtime", "verifier", "promote"))
        }
        resource["before"] = receipts[-1]["resources"]["runtime"] if receipts else "f" * 64
        receipt = {
            "run": run.name,
            "status": "ready",
            "manifestSha256": manifest,
            "previousManifestSha256": receipts[-1]["manifestSha256"] if receipts else "e" * 64,
            "activationSha256": "d" * 64,
            "sourceStartedAt": "2026-09-21T12:00:00Z",
            "activatedAt": "2026-09-21T13:00:00Z",
            "resources": resource,
        }
        (run / "completed.json").write_text(json.dumps(receipt))
        receipts.append(receipt)
        for identifier in resource.values():
            containers[identifier] = {
                "Id": identifier,
                "State": {"Status": "exited", "Running": False},
                "HostConfig": {"RestartPolicy": {"Name": "no"}},
                "Mounts": [{"Type": "bind", "Source": str(store)}],
            }
    current = receipts[-1]
    current_id = current["resources"]["runtime"]
    containers[current_id]["State"] = {"Status": "running", "Running": True}
    containers[current_id]["HostConfig"]["RestartPolicy"]["Name"] = "unless-stopped"
    pointer = {
        "currentManifestSha256": current["manifestSha256"],
        "previousManifestSha256": current["previousManifestSha256"],
    }
    case = SimpleNamespace(
        root=root,
        store=store,
        config=config,
        run=run,
        receipts=receipts,
        completed=current,
        containers=containers,
        removed=removed,
        pointer=pointer,
        pin=current["activationSha256"],
        current_id=current_id,
        mounts="",
        overrides={},
        before_rm=None,
        before_tree=None,
        directory_checks=0,
    )
    native_lstat = Path.lstat
    native_read = Path.read_text

    def lstat(path, *args, **kwargs):
        facts = list(native_lstat(path, *args, **kwargs))
        facts[4] = 10001 if path.is_relative_to(store / "generations") else 0
        for index, value in case.overrides.get(path, {}).items():
            facts[index] = value
        return os.stat_result(facts)

    monkeypatch.setattr(Path, "lstat", lstat)
    monkeypatch.setattr(
        Path,
        "read_text",
        lambda path, *a, **kw: (
            case.mounts
            if str(path) == str(Path("/proc/self/mountinfo"))
            else native_read(path, *a, **kw)
        ),
    )
    monkeypatch.setattr(refresh.activation, "private_read", lambda path: path.read_bytes())
    monkeypatch.setattr(refresh.activation, "sync_directory", lambda _: None)
    monkeypatch.setattr(refresh.shutil.rmtree, "avoids_symlink_attacks", True)
    monkeypatch.setattr(refresh.activation, "pointer", lambda _: (case.pointer, case.pin))

    def inspect(name):
        if name == "current":
            return containers[case.current_id]
        if case.before_rm:
            case.before_rm(name)
        return containers[name]

    def docker(*args):
        if args[0] == "ps":
            return "\n".join(containers)
        assert args == ("rm", args[1]) and args[1] not in current["resources"].values()
        assert (run / "retention-plan.json").exists()
        removed.append(args[1])
        del containers[args[1]]
        if case.before_tree:
            case.before_tree()
        return args[1]

    monkeypatch.setattr(refresh.activation, "inspect", inspect)
    monkeypatch.setattr(refresh.activation, "docker", docker)
    return case


def run(case):
    refresh.retention(case.config, case.run, case.completed)


def rewrite(case, number):
    receipt = case.receipts[number]
    (case.root / f"2026092{number}t120000z-aaaaaaaa" / "completed.json").write_text(
        json.dumps(receipt)
    )


def image_receipt(case):
    """Historical image replacement shares the dataset, not previous ownership."""
    receipt = {
        **case.completed,
        "kind": "image-upgrade",
        "run": "20260922t123000z-bbbbbbbb",
        "resources": {"runtime": case.current_id, "replaced": "a" * 64},
        "oldImage": "sha256:" + "1" * 64,
        "newImage": "sha256:" + "2" * 64,
    }
    directory = case.root / receipt["run"]
    directory.mkdir()
    (directory / "completed.json").write_text(json.dumps(receipt))
    case.containers["a" * 64] = {
        "Id": "a" * 64,
        "State": {"Status": "exited", "Running": False},
        "HostConfig": {"RestartPolicy": {"Name": "no"}},
        "Mounts": [{"Type": "bind", "Source": str(case.store)}],
    }
    return directory, receipt


def test_image_receipt_same_manifest_ownership_and_original_evidence_preserved(retained):
    case = retained
    directory, receipt = image_receipt(case)
    original = (case.run / "completed.json").read_bytes()
    run(case)
    assert "a" * 64 in case.removed
    assert case.current_id not in case.removed
    assert (directory / "completed.json").exists()
    assert (case.run / "completed.json").read_bytes() == original
    assert receipt["manifestSha256"] == case.pointer["currentManifestSha256"]


@pytest.mark.parametrize("failure", ["kind", "roles", "image", "same-runtime", "ownership"])
def test_invalid_image_receipt_stops_retention_before_deletion(retained, failure):
    case = retained
    directory, receipt = image_receipt(case)
    if failure == "kind":
        receipt["kind"] = "unknown"
    elif failure == "roles":
        receipt["resources"]["promote"] = "f" * 64
    elif failure == "image":
        receipt["newImage"] = "latest"
    elif failure == "same-runtime":
        receipt["resources"]["replaced"] = case.current_id
    else:
        receipt["resources"]["replaced"] = case.receipts[0]["resources"]["runtime"]
    (directory / "completed.json").write_text(json.dumps(receipt))
    with pytest.raises(ValueError):
        run(case)
    assert not case.removed


def test_retention_keeps_two_generations_and_only_immediate_container_backup(retained):
    case = retained
    # Missing old container is a previously removed resource, not a retry target.
    del case.containers[case.receipts[0]["resources"]["verifier"]]
    case.containers["c" * 64] = {"Id": "c" * 64, "Mounts": [{"Type": "volume", "Source": "other"}]}
    (case.root / "unknown-directory").mkdir()
    (case.root / "20260101t010101z-bbbbbbbb").mkdir()  # Incomplete evidence retained.
    run(case)
    assert not (case.root / case.receipts[0]["run"]).exists()
    assert not (case.store / "generations" / case.receipts[0]["manifestSha256"]).exists()
    for receipt in case.receipts[1:]:
        assert (case.root / receipt["run"]).is_dir()
        assert (case.store / "generations" / receipt["manifestSha256"]).is_dir()
    assert set(case.containers) == set(case.completed["resources"].values()) | {"c" * 64}
    assert len(case.removed) == len(set(case.removed))
    assert (case.root / "unknown-directory").is_dir()


@pytest.mark.parametrize("failure", ["pin", "current-manifest", "previous-manifest", "runtime"])
def test_current_state_change_stops_before_deletion(retained, failure):
    case = retained
    if failure == "pin":
        case.pin = "wrong"
    elif failure == "runtime":
        case.current_id = case.receipts[0]["resources"]["runtime"]
    else:
        case.pointer[
            "currentManifestSha256" if failure == "current-manifest" else "previousManifestSha256"
        ] = "wrong"
    with pytest.raises(ValueError, match="runtime changed"):
        run(case)
    assert not case.removed


@pytest.mark.parametrize(
    "failure",
    [
        "run",
        "status",
        "resources",
        "pin",
        "pin-type",
        "conflict",
        "missing-current",
        "inventory",
        "unknown",
        "ancestor",
        "running",
        "restart",
        "status-container",
        "generation",
    ],
)
def test_inconsistent_evidence_stops_before_deletion(retained, failure):
    case = retained
    old = case.receipts[0]
    identifier = old["resources"]["runtime"]
    if failure in ("run", "status"):
        old[failure] = "wrong"
    elif failure == "resources":
        old["resources"]["unknown"] = "a" * 64
    elif failure in ("pin", "pin-type"):
        old["previousManifestSha256"] = "wrong" if failure == "pin" else None
    elif failure == "conflict":
        old["resources"]["verifier"] = case.completed["resources"]["runtime"]
    elif failure == "missing-current":
        (case.run / "completed.json").unlink()
    elif failure == "inventory":
        case.containers[identifier]["Id"] = "wrong"
    elif failure in ("unknown", "ancestor"):
        case.containers["c" * 64] = {
            "Id": "c" * 64,
            "Mounts": [
                {
                    "Type": "bind",
                    "Source": str(case.root if failure == "unknown" else case.root.parent),
                }
            ],
        }
    elif failure == "running":
        case.containers[identifier]["State"]["Running"] = True
    elif failure == "restart":
        case.containers[identifier]["HostConfig"]["RestartPolicy"]["Name"] = "always"
    elif failure == "status-container":
        case.containers[identifier]["State"]["Status"] = "restarting"
    elif failure == "generation":
        (
            case.store
            / "generations"
            / old["manifestSha256"]
            / "staging-generation-manifest.v1.json"
        ).write_text("changed")
    rewrite(case, 0)
    with pytest.raises(ValueError):
        run(case)
    assert not case.removed


@pytest.mark.parametrize(
    "failure",
    ["owner", "directory-type", "mount", "rmtree", "file-owner", "file-type", "links", "device"],
)
def test_unsafe_trees_are_preserved(retained, failure, monkeypatch):
    case = retained
    directory = case.root / case.receipts[0]["run"]
    file = directory / "capture.txt"
    if failure == "owner":
        case.overrides[directory] = {4: 99}
    elif failure == "directory-type":
        case.overrides[directory] = {0: stat.S_IFREG | 0o600}
    elif failure == "mount":
        case.mounts = f"1 2 3 / {file.as_posix()} rw - ext4 /dev/test rw\n"
    elif failure == "rmtree":
        monkeypatch.setattr(refresh.shutil.rmtree, "avoids_symlink_attacks", False)
    else:
        case.overrides[file] = {
            "file-owner": {4: 99},
            "file-type": {0: stat.S_IFIFO | 0o600},
            "links": {3: 2},
            "device": {2: file.lstat().st_dev + 1},
        }[failure]
    with pytest.raises(ValueError, match="unsafe retention"):
        run(case)
    assert not case.removed and file.exists()


def test_missing_obsolete_generation_does_not_block_owned_run_cleanup(retained):
    case = retained
    directory = case.store / "generations" / case.receipts[0]["manifestSha256"]
    (directory / "staging-generation-manifest.v1.json").unlink()
    directory.rmdir()
    run(case)
    assert not (case.root / case.receipts[0]["run"]).exists()


@pytest.mark.parametrize(
    "change",
    [
        "runtime",
        "container-running",
        "container-restart",
        "directory",
        "new-container",
        "new-mount",
    ],
)
def test_changes_after_plan_stop_remaining_removals(retained, change):
    case = retained
    identifier = case.receipts[0]["resources"]["runtime"]

    def change_container(name):
        if (case.run / "retention-plan.json").exists() and name == identifier:
            if change == "container-running":
                case.containers[name]["State"]["Running"] = True
            elif change == "container-restart":
                case.containers[name]["HostConfig"]["RestartPolicy"]["Name"] = "always"

    case.before_rm = change_container

    def change_tree():
        if change == "runtime":
            case.pin = "changed"
        elif change == "directory":
            path = case.store / "generations" / case.receipts[0]["manifestSha256"]
            case.overrides[path] = {1: path.lstat().st_ino + 1}
        elif change == "new-container":
            case.containers["c" * 64] = {
                "Id": "c" * 64,
                "Mounts": [{"Type": "bind", "Source": str(case.store)}],
            }
        elif change == "new-mount":
            path = case.store / "generations" / case.receipts[0]["manifestSha256"]
            case.mounts = f"1 2 3 / {path.as_posix()} rw - ext4 /dev/test rw\n"

    case.before_tree = change_tree
    with pytest.raises(ValueError):
        run(case)
    assert (case.root / case.receipts[0]["run"]).exists()


def test_noncanonical_run_and_nested_symlink_are_rejected(retained, monkeypatch):
    case = retained
    native = Path.resolve
    directory = case.root / case.receipts[0]["run"]
    monkeypatch.setattr(
        Path,
        "resolve",
        lambda path, *a, **kw: case.root if path == directory else native(path, *a, **kw),
    )
    with pytest.raises(ValueError, match="noncanonical"):
        run(case)
    file = directory / "capture.txt"
    monkeypatch.setattr(
        Path,
        "resolve",
        lambda path, *a, **kw: case.root if path == file else native(path, *a, **kw),
    )
    with pytest.raises(ValueError, match="unsafe retention entry"):
        run(case)
    assert not case.removed


@pytest.mark.parametrize(
    ("age", "pending", "status"),
    [
        (86399, False, "fresh"),
        (86400, False, "stale"),
        (60, True, "refresh_incomplete"),
        (90000, True, "stale"),
    ],
)
def test_freshness_uses_capture_start_and_reports_pending(
    retained, monkeypatch, age, pending, status
):
    case = retained
    (case.root / "last-success.json").write_text(json.dumps(case.completed))
    if pending:
        (case.root / "pending-run.json").write_text("pending")
    now = datetime(2026, 9, 21, 12, tzinfo=UTC) + timedelta(seconds=age)
    monkeypatch.setattr(
        refresh, "datetime", SimpleNamespace(strptime=datetime.strptime, now=lambda _: now)
    )
    result = refresh.freshness(case.config)
    assert result["status"] == status and result["sourceAgeSeconds"] == age
    assert result["marketNewUpdates"] is False and result["pendingRun"] == pending


@pytest.mark.parametrize("failure", ["manifest", "pin", "runtime", "stopped", "future"])
def test_freshness_rejects_unbound_or_future_receipts(retained, monkeypatch, failure):
    case = retained
    receipt = dict(case.completed)
    if failure == "manifest":
        receipt["manifestSha256"] = "wrong"
    elif failure == "pin":
        case.pin = "wrong"
    elif failure == "runtime":
        case.current_id = case.receipts[0]["resources"]["runtime"]
    elif failure == "stopped":
        case.containers[case.current_id]["State"]["Running"] = False
    else:
        receipt["sourceStartedAt"] = "9999-01-01T00:00:00Z"
    (case.root / "last-success.json").write_text(json.dumps(receipt))
    with pytest.raises(ValueError):
        refresh.freshness(case.config)


@pytest.mark.parametrize(
    ("status", "code"), [("fresh", 0), ("stale", 2), ("refresh_incomplete", 2)]
)
def test_status_cli_is_read_only_and_nonfresh_is_nonzero(monkeypatch, capsys, status, code):
    monkeypatch.setattr(refresh, "configuration", lambda _: {})
    monkeypatch.setattr(refresh, "freshness", lambda _: {"status": status})
    monkeypatch.setattr(refresh, "run_once", lambda *args: pytest.fail("status must not apply"))
    assert refresh.main(["--config", "private.json", "--status"]) == code
    assert json.loads(capsys.readouterr().out)["status"] == status
