"""Offline fault injection for the parameterized staging activation operator."""

import hashlib
import json
import os
import runpy
import stat
import sys
import tempfile
import unittest
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from scripts import activate_staging_refresh as operator


def port_bindings(port):
    return {"10000/tcp": [{"HostIp": "127.0.0.1", "HostPort": str(port)}]}


def plan_values():
    return {
        "capture": "/private/capture",
        "store": "/private/store",
        "config": "/private/config",
        "work": "/private/operations/run-one",
        "run_id": "run-one",
        "current": "nla-catalog-staging-private",
        "expected_id": "1" * 64,
        "image": "sha256:" + "2" * 64,
        "old_pin": "3" * 64,
        "old_code": "4" * 40,
        "new_code": "5" * 40,
        "summary": "6" * 64,
        "manifest": "7" * 64,
        "started": "2026-09-21T12:00:00Z",
        "shop": "test.myshopify.com",
        "counts": {"products": 9, "published": 8, "singles": 8, "variants": 10},
    }


class StagingActivationOfflineTests(unittest.TestCase):
    def setUp(self):
        self.module = operator
        self.temporary = tempfile.TemporaryDirectory(prefix="nla-activation-offline-")
        self.root = Path(self.temporary.name).resolve()
        assert self.root.parent == Path(tempfile.gettempdir()).resolve()
        assert self.root.name.startswith("nla-activation-offline-")
        self.addCleanup(self.temporary.cleanup)
        m = self.module
        self.plan = replace(
            operator.load_plan(plan_values()),
            work=self.root / "operator",
            config=self.root / "config",
        )
        self.plan.config.mkdir()
        self.env = {
            "NLA_ACTIVATION_SHA256": self.plan.old_pin,
            "NLA_EVIDENCE_CODE_SHA": self.plan.old_code,
            "NLA_CURSOR_HMAC_SECRET_B64": "example-secret",
            "NLA_APP_PROXY_SHARED_SECRET_B64": "placeholder-secret",
            "NLA_SHOP_DOMAIN": "test.myshopify.com",
            "NLA_STAGING_STORE_ROOT": "/var/lib/nla-catalog",
        }
        self.old_bytes = m.env_bytes(self.env)
        (self.plan.config / "accepted-runtime.env").write_bytes(self.old_bytes)
        self.old_manifest = "a" * 64
        self.new_manifest = "b" * 64
        self.before = {
            "schemaVersion": 1,
            "currentManifestSha256": self.old_manifest,
            "previousManifestSha256": None,
        }
        self.pointer_document = self.before.copy()
        self.current_pin = self.plan.old_pin
        self.promoted_pin = m.pointer_pin(self.new_manifest, self.old_manifest)
        self.rollback_pin = m.pointer_pin(self.old_manifest, self.new_manifest)
        self.old = {
            "Id": self.plan.expected_id,
            "Image": self.plan.image,
            "State": {"Running": True},
            "HostConfig": {"PortBindings": port_bindings(10000)},
        }
        self.containers = {self.plan.current: self.old.copy()}
        self.operations = []
        self.started_ids = []
        self.created = []
        self.selections = []
        self.stages = []
        self.ready_checks = []
        self.failure = None
        self.injected = False
        self.checked = (
            self.old,
            self.old_bytes,
            self.env.copy(),
            self.before.copy(),
            self.new_manifest,
            self.root / "source",
            self.root / "destination",
        )
        replacements = {
            "docker": self.docker,
            "inspect": lambda name: self.containers[name],
            "private_read": lambda path: path.read_bytes(),
            "pointer": lambda plan: (self.pointer_document.copy(), self.current_pin),
            "install": lambda *_: None,
            "create_runtime": self.create_runtime,
            "select": self.select,
            "ready": self.ready,
            "serving": self.serving,
            "retire": self.retire,
            "sync_directory": lambda *_: None,
            "note": self.note,
        }
        for name, replacement in replacements.items():
            context = patch.object(m, name, replacement)
            context.start()
            self.addCleanup(context.stop)
        # Any missed transport invocation is a hard test failure, not a real command.
        for target in ("run", "Popen"):
            context = patch.object(
                m.subprocess, target, side_effect=AssertionError("REAL_PROCESS_FORBIDDEN")
            )
            context.start()
            self.addCleanup(context.stop)
        context = patch.object(
            m.urllib.request, "build_opener", side_effect=AssertionError("REAL_NETWORK_FORBIDDEN")
        )
        context.start()
        self.addCleanup(context.stop)

    def docker(self, *args):
        self.operations.append(args)
        if (
            self.failure == "after_old_rename"
            and not self.injected
            and args == ("rename", self.plan.candidate, self.plan.current)
        ):
            self.injected = True
            raise RuntimeError("INJECTED_AFTER_OLD_RENAME")
        if args[0] == "ps":
            return "\n".join(self.containers)
        if args[0] == "stop":
            if self.containers[args[-1]]["Id"] == self.plan.expected_id:
                # Both forward activation and rollback commit a ready replacement
                # before they may stop the original, still-serving process.
                assert self.resulting_env() != self.env
                assert self.ready_checks
            self.containers[args[-1]]["State"] = {"Running": False}
        elif args[0] == "rename":
            assert args[2] not in self.containers
            self.containers[args[2]] = self.containers.pop(args[1])
        elif args[0] == "update":
            assert args[-1] in self.containers
        elif args[0] == "start":
            self.started_ids.append(self.containers[args[1]]["Id"])
            self.containers[args[1]]["State"] = {"Running": True}
        else:
            raise AssertionError("UNEXPECTED_DOCKER_COMMAND")
        return ""

    def create_runtime(self, plan, name, env_path, reference, values, port):
        assert name not in self.containers
        assert reference["Id"] == self.plan.expected_id
        assert port in operator.RUNTIME_PORTS and port != operator.runtime_port(reference)
        written = dict(line.split("=", 1) for line in env_path.read_text().splitlines())
        self.assertEqual(written, values)
        self.assertEqual(set(written), set(self.env))
        self.assertLessEqual(
            {k for k in self.env if self.env[k] != written[k]}, self.module.ENV_KEYS
        )
        identifier = "candidate-id" if name == self.plan.candidate else "restored-id"
        self.containers[name] = {
            "Id": identifier,
            "Image": plan.image,
            "State": {"Running": False},
            "HostConfig": {"PortBindings": port_bindings(port)},
        }
        self.created.append((name, written.copy(), identifier))
        return identifier

    def select(self, plan, action, expected, target=None):
        m = self.module
        self.assertEqual(plan.image, self.plan.image)
        self.selections.append((action, expected, target))
        self.assertEqual(expected, self.current_pin)
        if action == "promote":
            if self.failure == "ambiguous_promote":
                raise m.InspectBeforeRetry("INJECTED_AMBIGUOUS_PROMOTION")
            self.assertEqual(target, self.new_manifest)
            self.pointer_document = {
                "schemaVersion": 1,
                "currentManifestSha256": self.new_manifest,
                "previousManifestSha256": self.old_manifest,
            }
            self.current_pin = self.promoted_pin
        elif action == "rollback":
            self.pointer_document = {
                "schemaVersion": 1,
                "currentManifestSha256": self.old_manifest,
                "previousManifestSha256": self.new_manifest,
            }
            self.current_pin = self.rollback_pin
        else:
            self.fail("unexpected selection action")

    def ready(self, plan, name, identifier, expected_pin, port):
        self.ready_checks.append((identifier, expected_pin))
        self.assertEqual(self.containers[name]["Id"], identifier)
        self.assertEqual(operator.runtime_port(self.containers[name]), port)
        self.assertEqual(self.current_pin, expected_pin)
        original = next(c for c in self.containers.values() if c["Id"] == self.plan.expected_id)
        assert original["State"]["Running"], "old process stopped during warmup"
        if identifier == "candidate-id":
            if self.failure == "readiness":
                raise RuntimeError("INJECTED_READINESS_FAILURE")
            if self.failure == "external_pointer":
                self.current_pin = "c" * 64
                raise RuntimeError("INJECTED_EXTERNAL_POINTER_CHANGE")

    def serving(self, name, identifier, port):
        assert self.containers[name]["Id"] == identifier == self.plan.expected_id
        assert self.containers[name]["State"]["Running"]
        assert operator.runtime_port(self.containers[name]) == port

    def retire(self, plan):
        assert self.containers[plan.backup]["Id"] == plan.expected_id
        self.docker("update", "--restart", "no", plan.backup)
        self.docker("stop", "-t", "30", plan.backup)

    def note(self, plan, stage):
        self.stages.append(stage)
        if self.failure == "post_commit" and stage.startswith("ACTIVATED_READY_"):
            raise OSError("INJECTED_RECEIPT_FAILURE_AFTER_ENV_COMMIT")

    def resulting_env(self):
        return dict(
            line.split("=", 1)
            for line in (self.plan.config / "accepted-runtime.env").read_text().splitlines()
        )

    def assert_original_never_restarted(self):
        self.assertNotIn(self.plan.expected_id, self.started_ids)
        self.assertNotIn(("start", self.plan.backup), self.operations)
        # Recorded start(CURRENT) must follow a rename of a newly created runtime.
        last_current_id = self.plan.expected_id
        for operation in self.operations:
            if operation == ("rename", self.plan.candidate, self.plan.current):
                # One injected failed rename is immediately followed by rollback.
                last_current_id = "candidate-id"
            elif operation == ("rename", self.plan.restored, self.plan.current):
                last_current_id = "restored-id"
            elif operation == ("start", self.plan.current):
                self.assertNotEqual(last_current_id, self.plan.expected_id)

    def test_success_changes_only_two_pins(self):
        m = self.module
        m.apply(self.plan, self.checked)
        actual = self.resulting_env()
        self.assertEqual({k for k in self.env if actual[k] != self.env[k]}, m.ENV_KEYS)
        self.assertEqual(actual["NLA_ACTIVATION_SHA256"], self.promoted_pin)
        self.assertEqual(actual["NLA_EVIDENCE_CODE_SHA"], self.plan.new_code)
        self.assertEqual(self.containers[self.plan.current]["Id"], "candidate-id")
        self.assertEqual(self.containers[self.plan.backup]["Id"], self.plan.expected_id)
        self.assertEqual([s[0] for s in self.selections], ["promote"])
        self.assert_original_never_restarted()

    def test_image_upgrade_keeps_original_serving_until_candidate_is_ready(self):
        self.plan = replace(self.plan, image="sha256:" + "9" * 64)
        self.module.apply(self.plan, self.checked)
        self.assertEqual(self.containers[self.plan.current]["Image"], self.plan.image)
        self.assertEqual(self.containers[self.plan.backup]["Image"], self.plan.old_image)
        self.assertEqual(self.resulting_env()["NLA_EVIDENCE_CODE_SHA"], self.plan.new_code)
        self.assert_original_never_restarted()

    def test_failed_image_upgrade_warms_previous_image_with_actual_rollback_pin(self):
        self.plan = replace(self.plan, image="sha256:" + "9" * 64)
        self.failure = "readiness"
        with self.assertRaisesRegex(RuntimeError, "rollback_completed"):
            self.module.apply(self.plan, self.checked)
        self.assertEqual(self.containers[self.plan.current]["Image"], self.plan.old_image)
        self.assertEqual(self.containers[self.plan.failed]["Image"], self.plan.image)
        self.assertEqual(self.containers[self.plan.backup]["Image"], self.plan.old_image)
        self.assertEqual(
            self.resulting_env(), {**self.env, "NLA_ACTIVATION_SHA256": self.rollback_pin}
        )
        self.assert_original_never_restarted()

    def test_readiness_failure_restores_new_container_with_actual_rollback_pin(self):
        m = self.module
        self.failure = "readiness"
        with self.assertRaisesRegex(RuntimeError, "rollback_completed"):
            m.apply(self.plan, self.checked)
        actual = self.resulting_env()
        self.assertEqual(actual, {**self.env, "NLA_ACTIVATION_SHA256": self.rollback_pin})
        self.assertNotEqual(self.rollback_pin, self.plan.old_pin)
        self.assertEqual(actual["NLA_EVIDENCE_CODE_SHA"], self.plan.old_code)
        self.assertEqual(self.containers[self.plan.current]["Id"], "restored-id")
        self.assertEqual(self.containers[self.plan.failed]["Id"], "candidate-id")
        self.assertEqual([s[0] for s in self.selections], ["promote", "rollback"])
        self.assertIn("ROLLBACK_READY_ACTUAL_POINTER_REPINNED", self.stages)
        self.assert_original_never_restarted()

    def test_external_pointer_change_stops_without_rollback(self):
        m = self.module
        self.failure = "external_pointer"
        with self.assertRaisesRegex(m.InspectBeforeRetry, "external_pointer"):
            m.apply(self.plan, self.checked)
        self.assertEqual([s[0] for s in self.selections], ["promote"])
        self.assertEqual(self.resulting_env(), self.env)
        self.assertEqual(self.current_pin, "c" * 64)

    def test_ambiguous_promotion_does_not_stop_or_retry(self):
        m = self.module
        self.failure = "ambiguous_promote"
        with self.assertRaises(m.InspectBeforeRetry):
            m.apply(self.plan, self.checked)
        self.assertEqual(self.operations, [])
        self.assertEqual([s[0] for s in self.selections], ["promote"])
        self.assertEqual(self.containers[self.plan.current]["Id"], self.plan.expected_id)
        self.assertEqual(self.resulting_env(), self.env)

    def test_failure_after_old_rename_restores_without_starting_original(self):
        m = self.module
        self.failure = "after_old_rename"
        with self.assertRaisesRegex(RuntimeError, "rollback_completed"):
            m.apply(self.plan, self.checked)
        self.assertTrue(self.injected)
        self.assertEqual(self.containers[self.plan.current]["Id"], "restored-id")
        self.assertEqual(self.containers[self.plan.backup]["Id"], self.plan.expected_id)
        self.assertEqual(self.resulting_env()["NLA_ACTIVATION_SHA256"], self.rollback_pin)
        self.assertEqual([s[0] for s in self.selections], ["promote", "rollback"])
        self.assert_original_never_restarted()

    def test_post_environment_commit_failure_does_not_rollback(self):
        m = self.module
        self.failure = "post_commit"
        with self.assertRaisesRegex(m.InspectBeforeRetry, "committed_state"):
            m.apply(self.plan, self.checked)
        self.assertEqual([s[0] for s in self.selections], ["promote"])
        self.assertEqual(self.resulting_env()["NLA_ACTIVATION_SHA256"], self.promoted_pin)
        self.assertEqual(self.resulting_env()["NLA_EVIDENCE_CODE_SHA"], self.plan.new_code)
        self.assertEqual(self.containers[self.plan.current]["Id"], "candidate-id")

    def test_success_report_with_wrong_promoted_pin_never_stops_runtime(self):
        def select(*args):
            self.select(*args)
            self.current_pin = "unexpected"

        with patch.object(self.module, "select", select):
            with self.assertRaisesRegex(self.module.InspectBeforeRetry, "promotion_pin"):
                self.module.apply(self.plan, self.checked)
        self.assertEqual(self.operations, [])
        self.assertEqual(self.resulting_env(), self.env)

    def test_failure_before_old_stop_restores_without_restarting_old_pin(self):
        def note(plan, stage):
            if stage == "DATASET_POINTER_PROMOTED":
                raise OSError("injected receipt failure")
            self.note(plan, stage)

        with patch.object(self.module, "note", note):
            with self.assertRaisesRegex(RuntimeError, "rollback_completed"):
                self.module.apply(self.plan, self.checked)
        self.assertEqual(self.containers[self.plan.current]["Id"], "restored-id")
        self.assert_original_never_restarted()

    def test_unknown_runtime_stops_rollback_without_touching_unknown_container(self):
        def ready(*args):
            self.containers[self.plan.current]["Id"] = "unexpected-runtime"
            raise RuntimeError("runtime replaced externally")

        with patch.object(self.module, "ready", ready):
            with self.assertRaisesRegex(self.module.InspectBeforeRetry, "unexpected_runtime"):
                self.module.apply(self.plan, self.checked)
        self.assertEqual([s[0] for s in self.selections], ["promote"])
        self.assertEqual(self.containers[self.plan.current]["Id"], "unexpected-runtime")
        self.assertEqual(self.resulting_env(), self.env)

    def test_unknown_candidate_stops_rollback_without_touching_either_runtime(self):
        def ready(*args):
            self.containers[self.plan.candidate]["Id"] = "unexpected-candidate"
            raise RuntimeError("candidate replaced externally")

        with patch.object(self.module, "ready", ready):
            with self.assertRaisesRegex(self.module.InspectBeforeRetry, "unexpected_candidate"):
                self.module.apply(self.plan, self.checked)
        self.assertEqual([s[0] for s in self.selections], ["promote"])
        self.assertEqual(self.current_pin, self.promoted_pin)
        self.assertEqual(self.resulting_env(), self.env)
        self.assertEqual(self.containers[self.plan.current]["Id"], self.plan.expected_id)
        self.assertEqual(self.containers[self.plan.candidate]["Id"], "unexpected-candidate")
        self.assertTrue(self.containers[self.plan.current]["State"]["Running"])
        self.assertTrue(self.containers[self.plan.candidate]["State"]["Running"])
        self.assertEqual(
            self.operations,
            [("start", self.plan.candidate), ("ps", "-a", "--format", "{{.Names}}")],
        )
        self.assertEqual(len(self.created), 1)

    def test_unknown_rollback_pin_does_not_start_restored_runtime(self):
        def select(plan, action, expected, target=None):
            self.select(plan, action, expected, target)
            if action == "rollback":
                self.current_pin = "unexpected"

        self.failure = "readiness"
        with patch.object(self.module, "select", select):
            with self.assertRaisesRegex(self.module.InspectBeforeRetry, "rollback_pin"):
                self.module.apply(self.plan, self.checked)
        self.assertNotIn("restored-id", self.started_ids)
        self.assertEqual(self.resulting_env(), self.env)

    def test_install_failure_cannot_promote_or_stop_runtime(self):
        with patch.object(self.module, "install", side_effect=OSError("copy failed")):
            with self.assertRaises(OSError):
                self.module.apply(self.plan, self.checked)
        self.assertEqual(self.selections, [])
        self.assertEqual(self.operations, [])
        self.assertEqual(self.resulting_env(), self.env)

    def test_next_cycle_alternates_back_to_first_port(self):
        self.old["HostConfig"]["PortBindings"] = port_bindings(10001)
        self.module.apply(self.plan, self.checked)
        self.assertEqual(operator.runtime_port(self.containers[self.plan.current]), 10000)
        self.assertFalse(self.containers[self.plan.backup]["State"]["Running"])

    def test_rollback_warmup_failure_keeps_original_serving(self):
        self.failure = "readiness"

        def ready(*args):
            self.ready(*args)
            raise RuntimeError("restoration_warmup_failed")

        with patch.object(self.module, "ready", ready):
            with self.assertRaisesRegex(RuntimeError, "restoration_warmup_failed"):
                self.module.apply(self.plan, self.checked)
        self.assertTrue(self.containers[self.plan.current]["State"]["Running"])
        self.assertEqual(self.containers[self.plan.current]["Id"], self.plan.expected_id)
        self.assertEqual(self.resulting_env(), self.env)

    def test_unready_survivor_does_not_stop_candidate(self):
        self.failure = "readiness"
        with patch.object(self.module, "serving", side_effect=OSError("old_unready")):
            with self.assertRaisesRegex(OSError, "old_unready"):
                self.module.apply(self.plan, self.checked)
        self.assertTrue(self.containers[self.plan.candidate]["State"]["Running"])
        self.assertEqual([s[0] for s in self.selections], ["promote"])

    def test_retirement_failure_is_not_completion_or_automatic_rollback(self):
        with patch.object(self.module, "retire", side_effect=OSError("stop_failed")):
            with self.assertRaisesRegex(self.module.InspectBeforeRetry, "committed_state"):
                self.module.apply(self.plan, self.checked)
        self.assertTrue(self.containers[self.plan.backup]["State"]["Running"])
        self.assertEqual(self.resulting_env()["NLA_ACTIVATION_SHA256"], self.promoted_pin)
        self.assertFalse(any(s.startswith("ACTIVATED_READY") for s in self.stages))


def test_plan_names_and_evidence_are_not_tied_to_one_capture():
    values = plan_values()
    values["run_id"] = "another-run"
    plan = operator.load_plan(values)
    assert plan.prefix == "nla-refresh-another-run"
    assert plan.verifier == plan.prefix + "-runtime-verify"
    assert len({plan.current, plan.backup, plan.candidate, plan.failed, plan.restored}) == 5
    values["counts"]["products"] = 123
    assert plan.counts["products"] == 9


@pytest.mark.parametrize(
    ("field", "value"),
    [
        (field, "bad")
        for field in ("old_pin", "summary", "manifest", "expected_id", "old_code", "new_code")
    ]
    + [
        (field, None)
        for field in ("old_pin", "old_code", "current", "run_id", "image", "shop", "capture")
    ]
    + [
        ("capture", path)
        for path in ("relative", "/x/../y", "/x//y", "/x,y", "/x\n", "/x\r", "/x\x00")
    ]
    + [
        ("image", "latest"),
        ("shop", "attacker.example"),
        ("current", "--option"),
        ("run_id", "../bad"),
    ]
    + [("started", "not-a-date"), ("started", None)]
    + [
        ("counts", counts)
        for counts in (
            None,
            {},
            {"products": 1},
            {"products": 0, "published": 0, "singles": 0, "variants": 0},
        )
    ],
)
def test_reject_invalid_expected_plan(field, value):
    with pytest.raises((ValueError, TypeError)):
        operator.load_plan({**plan_values(), field: value})


@pytest.mark.parametrize("value", [None, [], {}, {"unexpected": True}])
def test_reject_missing_or_extra_plan_fields(value):
    with pytest.raises(ValueError, match="plan fields"):
        operator.load_plan(value)


@pytest.mark.parametrize("count", [True, 1.0, -1, "9"])
def test_counts_are_nonnegative_integers_not_coercions(count):
    values = plan_values()
    values["counts"]["published"] = count
    with pytest.raises(ValueError, match="counts"):
        operator.load_plan(values)


def test_private_write_is_exclusive_and_digest_matches(tmp_path):
    path = tmp_path / "private.json"
    operator.private_write(path, b"first")
    assert operator.digest(path) == hashlib.sha256(b"first").hexdigest()
    with pytest.raises(FileExistsError):
        operator.private_write(path, b"replacement")
    assert path.read_bytes() == b"first"


def test_pointer_pin_matches_actual_canonical_bytes(tmp_path):
    value = {
        "schemaVersion": 1,
        "currentManifestSha256": "a" * 64,
        "previousManifestSha256": "b" * 64,
    }
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    (tmp_path / "activation.v1.json").write_bytes(raw)
    plan = replace(operator.load_plan(plan_values()), store=tmp_path)
    document, digest = operator.pointer(plan)
    assert document == value
    assert digest == operator.pointer_pin("a" * 64, "b" * 64)


@pytest.mark.parametrize("apply", [False, True])
def test_cli_defaults_to_read_only_and_requires_explicit_apply(monkeypatch, capsys, apply):
    values = plan_values()
    calls = []
    checked = object()
    monkeypatch.setattr(operator, "private_read", lambda path: json.dumps(values).encode())
    monkeypatch.setattr(operator, "preflight", lambda plan: checked)
    monkeypatch.setattr(operator, "apply", lambda plan, result: calls.append((plan, result)))
    args = ["--plan", "/private/plan.json"] + (["--apply"] if apply else [])
    assert operator.main(args) == 0
    if apply:
        assert len(calls) == 1 and calls[0][1] is checked
        assert capsys.readouterr().out == ""
    else:
        assert calls == []
        assert capsys.readouterr().out == "READ_ONLY_PREFLIGHT_ACCEPTED_NO_CHANGES\n"


@pytest.mark.parametrize("error", [OSError("SECRET"), KeyboardInterrupt()])
def test_cli_failure_is_fixed_and_never_applies(monkeypatch, capsys, error):
    def fail(_):
        raise error

    monkeypatch.setattr(operator, "private_read", fail)
    monkeypatch.setattr(operator, "apply", lambda *_: pytest.fail("must not apply"))
    assert operator.main(["--plan", "/private/SECRET.json", "--apply"]) == 1
    output = capsys.readouterr()
    assert output.err == ""
    assert (
        output.out
        == "OPERATOR_STOPPED_INSPECT_PRIVATE_RECEIPTS_AND_NAMED_CONTAINERS_BEFORE_RETRY\n"
    )


def test_main_entrypoint_rejects_missing_plan(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["activate_staging_refresh.py"])
    with pytest.raises(SystemExit, match="1"):
        runpy.run_path(operator.__file__, run_name="__main__")
    assert "OPERATOR_STOPPED" in capsys.readouterr().out


def test_docker_transport_uses_fixed_executable_and_no_shell(monkeypatch):
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(stdout='[{"Id":"synthetic-id"}]\n')

    monkeypatch.setattr(operator.subprocess, "run", run)
    assert operator.inspect("test-runtime") == {"Id": "synthetic-id"}
    args, options = calls[0]
    assert args == ["/usr/bin/docker", "inspect", "test-runtime"]
    assert options == {"check": True, "capture_output": True, "text": True}


@pytest.mark.parametrize("action", ["promote", "rollback"])
@pytest.mark.parametrize("status", ["accepted", "error", "unexpected-output"])
def test_selection_preserves_existing_pointer_cli_contract(monkeypatch, action, status):
    plan = operator.load_plan(plan_values())
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(
            returncode=1 if status == "error" else 0,
            stdout="other" if status == "unexpected-output" else "VALUE_FREE_RESULT: ACCEPTED\n",
        )

    monkeypatch.setattr(operator.subprocess, "run", run)
    target = plan.manifest if action == "promote" else None
    if status == "accepted":
        operator.select(plan, action, plan.old_pin, target)
    else:
        with pytest.raises(operator.InspectBeforeRetry):
            operator.select(plan, action, plan.old_pin, target)
    args, options = calls[0]
    assert args[:3] == ["/usr/bin/docker", "run", "--name"]
    assert plan.prefix + "-" + action in args
    assert "--network=none" in args
    assert "NLA_STAGING_ACTIVATION_SHA256=" + plan.old_pin in args
    assert args[-3:] == [plan.image, "python", "/app/scripts/manage_staging_activation.py"]
    assert ("NLA_STAGING_CANDIDATE_MANIFEST_SHA256=" + plan.manifest in args) == (
        target is not None
    )
    assert "shell" not in options


@pytest.mark.parametrize("response", [200, 503, OSError("unavailable")])
def test_readiness_has_pinned_container_and_pointer_and_bounded_wait(monkeypatch, response):
    plan = operator.load_plan(plan_values())
    observations = iter([0, 1, 1, 8, 8] if response == 200 else [0, 1, 1200])
    monkeypatch.setattr(operator.time, "monotonic", lambda: next(observations))
    monkeypatch.setattr(operator.time, "sleep", lambda _: None)

    def inspect(name):
        assert name == plan.candidate
        return {
            "Id": "new",
            "State": {"Running": True},
            "HostConfig": {"PortBindings": port_bindings(10001)},
        }

    monkeypatch.setattr(operator, "inspect", inspect)
    monkeypatch.setattr(operator, "pointer", lambda _: ({}, "new-pin"))

    def open_url(url, timeout):
        assert url == "http://127.0.0.1:10001/readyz" and timeout == 3
        if isinstance(response, OSError):
            raise response
        return nullcontext(SimpleNamespace(status=response))

    monkeypatch.setattr(
        operator.urllib.request, "build_opener", lambda _: SimpleNamespace(open=open_url)
    )
    if response == 200:
        operator.ready(plan, plan.candidate, "new", "new-pin", 10001)
    else:
        with pytest.raises(RuntimeError, match="readiness_timeout"):
            operator.ready(plan, plan.candidate, "new", "new-pin", 10001)


def test_stage_note_is_exclusive_and_contains_no_runtime_values(tmp_path, capsys):
    plan = replace(operator.load_plan(plan_values()), work=tmp_path)
    operator.note(plan, "PREFLIGHT_ACCEPTED")
    assert json.loads((tmp_path / "PREFLIGHT_ACCEPTED.json").read_bytes()) == {
        "stage": "PREFLIGHT_ACCEPTED"
    }
    assert capsys.readouterr().out == "PREFLIGHT_ACCEPTED\n"
    with pytest.raises(FileExistsError):
        operator.note(plan, "PREFLIGHT_ACCEPTED")


@pytest.fixture
def preflight_case(tmp_path, monkeypatch):
    """Real synthetic bytes, simulated POSIX ownership; no external processes."""
    root = tmp_path.resolve()
    plan = replace(
        operator.load_plan(plan_values()),
        capture=root / "capture",
        store=root / "store",
        config=root / "config",
        work=root / "operations" / "run",
    )
    for path in (plan.capture, plan.store / "generations", plan.config, plan.work.parent):
        path.mkdir(parents=True)
    source = plan.capture / "candidate"
    source.mkdir()
    artifacts = []
    for name in sorted(operator.FILES - {"staging-generation-manifest.v1.json"}):
        raw = b"synthetic artifact " + name.encode()
        (source / name).write_bytes(raw)
        artifacts.append(
            {"filename": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        )
    manifest_path = source / "staging-generation-manifest.v1.json"
    manifest_path.write_text(json.dumps({"artifacts": artifacts}))
    before = {"currentManifestSha256": "a" * 64, "previousManifestSha256": None}
    pointer_path = plan.store / "activation.v1.json"
    pointer_path.write_text(json.dumps(before))
    plan = replace(
        plan, manifest=operator.digest(manifest_path), old_pin=operator.digest(pointer_path)
    )
    values = {
        "NLA_ACTIVATION_SHA256": plan.old_pin,
        "NLA_EVIDENCE_CODE_SHA": plan.old_code,
        "NLA_STAGING_STORE_ROOT": "/var/lib/nla-catalog",
        "NLA_SHOP_DOMAIN": plan.shop,
        "NLA_APP_PROXY_SIGNED_PATH_PREFIX": "/apps/nla-catalog",
        "NLA_APP_PROXY_BACKEND_PATH": "/proxy/catalog",
    }
    (plan.config / "accepted-runtime.env").write_bytes(operator.env_bytes(values))
    documents = {
        "operator-receipt.json": {
            "manifestSha256": plan.manifest,
            "status": "candidate-ready",
            "activeCatalogChanged": False,
            "codeSha": plan.new_code,
            "captureStartedAt": plan.started,
            "counts": plan.counts,
        },
        "capture-checkpoint.v1.json": {
            "identity": {"sourceCodeSha": plan.new_code},
            "packageManifestSha256": plan.manifest,
            "summarySha256": plan.summary,
            "beforeObservedAt": plan.started,
            "beforeCounts": plan.counts,
        },
        "runtime-verification-receipt.json": {
            "status": "verified",
            "runtimeBinding": True,
            "manifestSha256": plan.manifest,
            "producerCodeSha": plan.new_code,
            "summarySha256": plan.summary,
            "records": plan.counts["products"],
            "activeCatalogChanged": False,
        },
    }
    for name, value in documents.items():
        (plan.capture / name).write_text(json.dumps(value))
    metadata = {}
    for path in (plan.work.parent, plan.config, plan.store, plan.store / "generations"):
        metadata[path] = (
            stat.S_IFDIR | 0o700,
            10001 if path in (plan.store, plan.store / "generations") else 0,
            1,
        )
    metadata[source] = (stat.S_IFDIR | 0o555, 0, 1)
    for path in source.iterdir():
        metadata[path] = (stat.S_IFREG | 0o444, 0, 1)
    for path in [
        *(plan.capture / name for name in documents),
        plan.config / "accepted-runtime.env",
    ]:
        metadata[path] = (stat.S_IFREG | 0o600, 0, 1)
    native_stat = Path.stat

    def simulated_stat(path, *args, **kwargs):
        facts = native_stat(path, *args, **kwargs)
        if path in metadata:
            fields = list(facts)
            fields[0], fields[4], fields[3] = metadata[path]
            return os.stat_result(fields)
        return facts

    monkeypatch.setattr(Path, "stat", simulated_stat)
    monkeypatch.setattr(operator.os, "geteuid", lambda: 0, raising=False)
    containers = {
        plan.current: {
            "Id": plan.expected_id,
            "Image": plan.image,
            "State": {"Running": True},
            "Config": {"Env": operator.env_bytes(values).decode().splitlines()},
            "HostConfig": {"PortBindings": port_bindings(10000)},
        },
        plan.verifier: {
            "Image": plan.image,
            "State": {"Status": "exited", "ExitCode": 0, "OOMKilled": False},
        },
    }
    commands = []
    state = {"names": plan.current}

    def run(args, **kwargs):
        commands.append(args)
        assert kwargs == {"check": True, "capture_output": True, "text": True}
        assert args[0] == "/usr/bin/docker"
        if args[1] == "inspect":
            return SimpleNamespace(stdout=json.dumps([containers[args[2]]]))
        assert args[1:] == ["ps", "-a", "--format", "{{.Names}}"]
        return SimpleNamespace(stdout=state["names"])

    monkeypatch.setattr(operator.subprocess, "run", run)
    return SimpleNamespace(
        plan=plan,
        source=source,
        documents=documents,
        metadata=metadata,
        containers=containers,
        state=state,
        commands=commands,
        values=values,
    )


@pytest.mark.parametrize("mismatch", [None, "current", "verifier"])
def test_upgrade_preflight_binds_previous_and_candidate_images_separately(preflight_case, mismatch):
    case = preflight_case
    plan = replace(case.plan, image="sha256:" + "9" * 64)
    case.containers[plan.verifier]["Image"] = plan.image
    if mismatch == "current":
        case.containers[plan.current]["Image"] = plan.image
    elif mismatch == "verifier":
        case.containers[plan.verifier]["Image"] = plan.old_image
    if mismatch:
        with pytest.raises(AssertionError):
            operator.preflight(plan)
    else:
        checked = operator.preflight(plan)
        assert checked[0]["Image"] == plan.old_image
    assert not plan.work.exists()


def test_old_image_defaults_to_candidate_without_mutating_plan_input():
    values = plan_values()
    assert operator.load_plan(values).old_image == values["image"]
    old_image = "sha256:" + "a" * 64
    assert operator.load_plan({**values, "old_image": old_image}).old_image == old_image
    assert "old_image" not in values


@pytest.mark.parametrize(
    "value", [None, True, "latest", "sha256:" + "A" * 64, "sha256:" + "a" * 63]
)
def test_old_image_requires_exact_lowercase_digest(value):
    with pytest.raises(ValueError, match="runtime identity"):
        operator.load_plan({**plan_values(), "old_image": value})


def test_real_preflight_accepts_bound_evidence_without_writing(preflight_case):
    case = preflight_case
    result = operator.preflight(case.plan)
    assert result[2] == case.values
    assert result[4] == case.plan.manifest
    assert result[5] == case.source
    assert result[6] == case.plan.store / "generations" / case.plan.manifest
    assert not result[6].exists() and not case.plan.work.exists()
    assert all(command[1] in ("inspect", "ps") for command in case.commands)


@pytest.mark.parametrize(
    ("file", "key", "value"),
    [
        ("operator-receipt.json", "manifestSha256", "0" * 64),
        ("operator-receipt.json", "activeCatalogChanged", True),
        ("operator-receipt.json", "status", "pending"),
        ("operator-receipt.json", "codeSha", "0" * 40),
        ("operator-receipt.json", "captureStartedAt", "old"),
        ("operator-receipt.json", "counts", {}),
        ("capture-checkpoint.v1.json", "packageManifestSha256", "0" * 64),
        ("capture-checkpoint.v1.json", "summarySha256", "0" * 64),
        ("runtime-verification-receipt.json", "runtimeBinding", False),
        ("runtime-verification-receipt.json", "status", "failed"),
        ("runtime-verification-receipt.json", "manifestSha256", "0" * 64),
        ("runtime-verification-receipt.json", "producerCodeSha", "0" * 40),
        ("runtime-verification-receipt.json", "records", 1),
        ("runtime-verification-receipt.json", "activeCatalogChanged", True),
    ],
)
def test_preflight_rejects_mismatched_receipts(preflight_case, file, key, value):
    case = preflight_case
    case.documents[file][key] = value
    (case.plan.capture / file).write_text(json.dumps(case.documents[file]))
    with pytest.raises(AssertionError):
        operator.preflight(case.plan)


@pytest.mark.parametrize(
    "failure",
    [
        "verifier-running",
        "verifier-exit",
        "verifier-oom",
        "verifier-image",
        "current-id",
        "current-image",
        "current-stopped",
        "reused-name",
        "reused-work",
        "reused-destination",
        "private-mode",
        "private-owner",
        "private-links",
        "private-type",
        "store-owner",
        "source-mode",
        "artifact-mode",
        "artifact-bytes",
        "extra-artifact",
        "pointer",
        "accepted-env",
        "live-env",
    ],
)
def test_preflight_rejects_unsafe_or_reused_state(preflight_case, failure):
    case = preflight_case
    plan = case.plan
    verifier = case.containers[plan.verifier]
    current = case.containers[plan.current]
    if failure == "verifier-running":
        verifier["State"]["Status"] = "running"
    elif failure == "verifier-exit":
        verifier["State"]["ExitCode"] = 1
    elif failure == "verifier-oom":
        verifier["State"]["OOMKilled"] = True
    elif failure == "verifier-image":
        verifier["Image"] = "different"
    elif failure == "current-id":
        current["Id"] = "different"
    elif failure == "current-image":
        current["Image"] = "different"
    elif failure == "current-stopped":
        current["State"]["Running"] = False
    elif failure == "reused-name":
        case.state["names"] += "\n" + plan.backup
    elif failure == "reused-work":
        plan.work.mkdir()
    elif failure == "reused-destination":
        (plan.store / "generations" / plan.manifest).mkdir()
    elif failure.startswith("private-"):
        case.metadata[plan.capture / "operator-receipt.json"] = {
            "private-mode": (stat.S_IFREG | 0o644, 0, 1),
            "private-owner": (stat.S_IFREG | 0o600, 1000, 1),
            "private-links": (stat.S_IFREG | 0o600, 0, 2),
            "private-type": (stat.S_IFLNK | 0o600, 0, 1),
        }[failure]
    elif failure == "store-owner":
        case.metadata[plan.store] = (stat.S_IFDIR | 0o700, 0, 1)
    elif failure == "source-mode":
        case.metadata[case.source] = (stat.S_IFDIR | 0o777, 0, 1)
    elif failure == "artifact-mode":
        case.metadata[case.source / "catalog-core-evidence.v1.json"] = (stat.S_IFREG | 0o644, 0, 1)
    elif failure == "artifact-bytes":
        (case.source / "catalog-core-evidence.v1.json").write_bytes(b"changed")
    elif failure == "extra-artifact":
        (case.source / "unexpected").write_bytes(b"extra")
    elif failure == "pointer":
        (plan.store / "activation.v1.json").write_text("{}")
    elif failure == "accepted-env":
        (plan.config / "accepted-runtime.env").write_bytes(b"NLA_ACTIVATION_SHA256=other\n")
    else:
        assert failure == "live-env"
        current["Config"]["Env"] = []
    with pytest.raises(AssertionError):
        operator.preflight(plan)


def test_install_copies_exclusively_sets_ownership_and_seals_package(tmp_path, monkeypatch):
    source, destination = tmp_path / "source", tmp_path / "destination"
    source.mkdir()
    for name in operator.FILES:
        (source / name).write_bytes(name.encode())
    owners, modes, synced = [], [], []
    monkeypatch.setattr(operator.os, "chown", lambda *args: owners.append(args), raising=False)
    monkeypatch.setattr(Path, "chmod", lambda *args: modes.append(args))
    monkeypatch.setattr(operator, "sync_directory", lambda path: synced.append(path))
    operator.install(source, destination)
    assert {path.name for path in destination.iterdir()} == operator.FILES
    for name in operator.FILES:
        assert (destination / name).read_bytes() == name.encode()
        assert (destination / name, 10001, 10001) in owners
        assert (destination / name, 0o444) in modes
    assert (destination, 10001, 10001) in owners
    assert (destination, 0o555) in modes
    assert synced == [destination, destination.parent]
    with pytest.raises(FileExistsError):
        operator.install(source, destination)


@pytest.mark.parametrize("fail", [False, True])
def test_directory_fsync_closes_descriptor_even_on_failure(monkeypatch, fail):
    calls = []
    monkeypatch.setattr(operator.os, "O_DIRECTORY", 65536, raising=False)
    monkeypatch.setattr(operator.os, "open", lambda *args: calls.append(args) or 123)
    monkeypatch.setattr(operator.os, "close", lambda fd: calls.append(("close", fd)))

    def fsync(fd):
        calls.append(("fsync", fd))
        if fail:
            raise OSError("synthetic failure")

    monkeypatch.setattr(operator.os, "fsync", fsync)
    if fail:
        with pytest.raises(OSError):
            operator.sync_directory("directory")
    else:
        operator.sync_directory("directory")
    assert calls == [("directory", operator.os.O_RDONLY | 65536), ("fsync", 123), ("close", 123)]


@pytest.mark.parametrize(
    "mismatch", [None, "Image", "Config", "HostConfig", "env-key", "env-value", "expected", "port"]
)
def test_runtime_creation_preserves_image_security_environment_and_mount(monkeypatch, mismatch):
    plan = operator.load_plan(plan_values())
    reference = {
        "Config": {
            **dict.fromkeys(("User", "Entrypoint", "Cmd", "WorkingDir", "ExposedPorts"), "same"),
            "Env": [
                "NLA_ACTIVATION_SHA256=old",
                "NLA_EVIDENCE_CODE_SHA=old-code",
                "OTHER=unchanged",
            ],
        },
        "HostConfig": dict.fromkeys(
            (
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
                "RestartPolicy",
            ),
            "same",
        ),
    }
    expected = {
        "NLA_ACTIVATION_SHA256": "new",
        "NLA_EVIDENCE_CODE_SHA": "new-code",
        "OTHER": "unchanged",
    }
    reference["HostConfig"]["PortBindings"] = port_bindings(10000)
    new = {**deepcopy(reference), "Image": plan.image, "Id": "new-id"}
    new["HostConfig"]["PortBindings"] = port_bindings(10001)
    new["Config"]["Env"] = operator.env_bytes(expected).decode().splitlines()
    if mismatch == "Image":
        new["Image"] = "other"
    elif mismatch == "Config":
        new["Config"]["User"] = "other"
    elif mismatch == "HostConfig":
        new["HostConfig"]["Memory"] = "other"
    elif mismatch == "env-key":
        new["Config"]["Env"].append("EXTRA=value")
    elif mismatch == "env-value":
        new["Config"]["Env"][-1] = "OTHER=changed"
    elif mismatch == "expected":
        expected["NLA_ACTIVATION_SHA256"] = "unexpected"
    elif mismatch == "port":
        new["HostConfig"]["PortBindings"] = port_bindings(10000)
    calls = []
    monkeypatch.setattr(operator, "docker", lambda *args: calls.append(args))
    monkeypatch.setattr(operator, "inspect", lambda name: new)
    if mismatch:
        with pytest.raises(AssertionError):
            operator.create_runtime(plan, plan.candidate, "private.env", reference, expected, 10001)
    else:
        assert (
            operator.create_runtime(plan, plan.candidate, "private.env", reference, expected, 10001)
            == "new-id"
        )
    args = calls[0]
    assert args[:3] == ("create", "--name", plan.candidate) and args[-1] == plan.image
    assert (
        args[args.index("--mount") + 1]
        == f"type=bind,src={plan.store},dst=/var/lib/nla-catalog,readonly"
    )
    for flag, value in (
        ("--memory", "3g"),
        ("--cpus", "2"),
        ("--cap-drop", "ALL"),
        ("--pids-limit", "128"),
        ("-p", "127.0.0.1:10001:10000"),
        ("--security-opt", "no-new-privileges"),
        ("--env-file", "private.env"),
    ):
        assert args[args.index(flag) + 1] == value
    assert "--read-only" in args


@pytest.mark.parametrize("mismatch", ["container", "stopped", "pointer", "port"])
def test_readiness_rejects_identity_change_before_http(monkeypatch, mismatch):
    plan = operator.load_plan(plan_values())
    monkeypatch.setattr(
        operator,
        "inspect",
        lambda _: {
            "Id": "other" if mismatch == "container" else "new",
            "State": {"Running": mismatch != "stopped"},
            "HostConfig": {"PortBindings": port_bindings(10000 if mismatch == "port" else 10001)},
        },
    )
    monkeypatch.setattr(
        operator, "pointer", lambda _: ({}, "wrong" if mismatch == "pointer" else "pin")
    )
    monkeypatch.setattr(
        operator.urllib.request,
        "build_opener",
        lambda _: SimpleNamespace(
            open=lambda *args, **kwargs: pytest.fail("identity gate must precede HTTP")
        ),
    )
    with pytest.raises(AssertionError):
        operator.ready(plan, plan.candidate, "new", "pin", 10001)


def test_optimized_python_refuses_preflight(monkeypatch):
    namespace = {"__name__": operator.__name__}
    exec(  # noqa: S102 -- compile this module under -O; never untrusted input
        compile(Path(operator.__file__).read_text(), operator.__file__, "exec", optimize=1),
        namespace,
    )
    monkeypatch.setattr(
        operator.os,
        "geteuid",
        lambda: pytest.fail("must refuse before reading state"),
        raising=False,
    )
    with pytest.raises(namespace["InspectBeforeRetry"], match="assertions_required"):
        namespace["preflight"](None)


def test_malformed_arguments_do_not_echo_values(capsys):
    assert operator.main(["--plan", "/private/plan", "--secret=SYNTHETIC_PRIVATE_VALUE"]) == 1
    output = capsys.readouterr()
    assert not output.err and "SYNTHETIC_PRIVATE_VALUE" not in output.out


@pytest.mark.parametrize(
    "bindings",
    [
        {},
        {"10000/tcp": [{"HostIp": "0.0.0.0", "HostPort": "10000"}]},  # noqa: S104 -- rejection fixture
        {"10000/tcp": [{"HostIp": "::1", "HostPort": "10001"}]},
        port_bindings(10002),
        {**port_bindings(10000), "9000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "9000"}]},
    ],
)
def test_only_exact_private_port_bindings_are_accepted(bindings):
    with pytest.raises(operator.InspectBeforeRetry, match="port_binding"):
        operator.runtime_port({"HostConfig": {"PortBindings": bindings}})


@pytest.mark.parametrize("failure", [None, "identity", "stopped", "port", "http"])
def test_survivor_must_be_the_expected_ready_private_runtime(monkeypatch, failure):
    state = {
        "Id": "other" if failure == "identity" else "old",
        "State": {"Running": failure != "stopped"},
        "HostConfig": {"PortBindings": port_bindings(10001 if failure == "port" else 10000)},
    }
    monkeypatch.setattr(operator, "inspect", lambda _: state)
    requests = []

    def open_url(url, timeout):
        requests.append((url, timeout))
        return nullcontext(SimpleNamespace(status=503 if failure == "http" else 200))

    monkeypatch.setattr(
        operator.urllib.request, "build_opener", lambda _: SimpleNamespace(open=open_url)
    )
    with pytest.raises(AssertionError) if failure else nullcontext():
        operator.serving("old-name", "old", 10000)
    assert requests == (
        [] if failure in {"identity", "stopped", "port"} else [("http://127.0.0.1:10000/readyz", 3)]
    )


@pytest.mark.parametrize("failure", [None, "identity", "still-running", "edge-down", "edge-status"])
def test_retirement_checks_actual_stop_and_edge_before_completion(monkeypatch, failure):
    plan = operator.load_plan(plan_values())
    state = {
        "Id": "other" if failure == "identity" else plan.expected_id,
        "State": {"Running": True},
    }
    monkeypatch.setattr(operator, "inspect", lambda _: state)
    commands = []

    def docker(*args):
        commands.append(args)
        if args[0] == "stop" and failure != "still-running":
            state["State"]["Running"] = False

    monkeypatch.setattr(operator, "docker", docker)
    observations = iter([0, 1, 20])
    monkeypatch.setattr(operator.time, "monotonic", lambda: next(observations))
    sleeps = []
    monkeypatch.setattr(operator.time, "sleep", sleeps.append)

    def open_url(url, timeout):
        assert not state["State"]["Running"]
        assert url == operator.EDGE_READY_URL and timeout == 3
        if failure == "edge-down":
            raise OSError("not ready")
        return nullcontext(SimpleNamespace(status=204 if failure == "edge-status" else 200))

    monkeypatch.setattr(
        operator.urllib.request, "build_opener", lambda _: SimpleNamespace(open=open_url)
    )
    edge_failure = failure in {"edge-down", "edge-status"}
    expected = operator.InspectBeforeRetry if edge_failure else AssertionError
    with pytest.raises(expected) if failure else nullcontext():
        operator.retire(plan)
    assert commands == (
        []
        if failure == "identity"
        else [("update", "--restart", "no", plan.backup), ("stop", "-t", "30", plan.backup)]
    )
    assert sleeps == ([1] if edge_failure else [])


def test_readiness_requires_uninterrupted_healthy_settle_window(monkeypatch):
    plan = operator.load_plan(plan_values())
    state = {
        "Id": "new",
        "State": {"Running": True},
        "HostConfig": {"PortBindings": port_bindings(10001)},
    }
    monkeypatch.setattr(operator, "inspect", lambda _: state)
    monkeypatch.setattr(operator, "pointer", lambda _: ({}, "pin"))
    # Healthy at 0/5 is too brief; unhealthy at 10 resets the window. The later
    # healthy 15/20 probes are still too brief, so readiness requires the 25 probe.
    observations = iter([0, 0, 0, 5, 5, 10, 15, 15, 20, 20, 25, 25])
    statuses = iter([200, 200, 503, 200, 200, 200])
    monkeypatch.setattr(operator.time, "monotonic", lambda: next(observations))
    sleeps = []
    monkeypatch.setattr(operator.time, "sleep", sleeps.append)
    monkeypatch.setattr(
        operator.urllib.request,
        "build_opener",
        lambda _: SimpleNamespace(
            open=lambda *args, **kwargs: nullcontext(SimpleNamespace(status=next(statuses)))
        ),
    )
    operator.ready(plan, plan.candidate, "new", "pin", 10001)
    assert list(statuses) == []
    assert sleeps == [5] * 5


def test_static_edge_config_preserves_policy_and_enables_both_private_upstreams():
    config = (Path(operator.__file__).parents[1] / "ops/caddy/Caddyfile.staging").read_text()
    assert config.count("reverse_proxy 127.0.0.1:10000 127.0.0.1:10001 {") == 2
    assert config.count("import nla_catalog_upstreams") == 2
    for directive in (
        "admin off",
        "lb_policy first",
        "health_uri /readyz",
        "health_interval 2s",
        "health_timeout 1s",
        "fail_duration 3s",
        "lb_try_duration 5s",
        "max_size 64KB",
        'respond "Not found" 404',
        "method POST",
        "strict_sni_host on",
    ):
        assert directive in config
