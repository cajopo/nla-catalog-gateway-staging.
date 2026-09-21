"""Small offline checks for bounded polling of the existing durable capture."""

from types import SimpleNamespace

import pytest
from scripts import capture_shopify_bulk as cli


@pytest.fixture
def clock(monkeypatch):
    state = SimpleNamespace(now=0, sleeps=[])

    def sleep(seconds):
        state.sleeps.append(seconds)
        state.now += seconds

    monkeypatch.setattr(cli.time, "monotonic", lambda: state.now)
    monkeypatch.setattr(cli.time, "sleep", sleep)
    return state


def test_pending_resumes_same_client_and_directory_and_clears_recovery(monkeypatch, clock):
    calls = []
    client = object()
    directory = object()

    def capture(**configuration):
        calls.append(configuration)
        return {"status": "pending" if len(calls) < 3 else "candidate-ready"}

    monkeypatch.setattr(cli, "run_capture", capture)
    assert cli.wait_for_capture(
        client=client,
        capture_directory=directory,
        recover_products_operation_id="gid://shopify/BulkOperation/1",
        recover_variants_operation_id="gid://shopify/BulkOperation/2",
        wait_seconds=180,
        poll_seconds=60,
    ) == {"status": "candidate-ready"}
    assert clock.sleeps == [60, 60]
    assert all(c["client"] is client and c["capture_directory"] is directory for c in calls)
    assert calls[0]["recover_products_operation_id"] is not None
    assert all(c["recover_products_operation_id"] is None for c in calls[1:])
    assert all(c["recover_variants_operation_id"] is None for c in calls[1:])


@pytest.mark.parametrize("wait", [0, 20, 60])
def test_deadline_returns_pending_without_starting_another_step(monkeypatch, clock, wait):
    calls = []

    def capture(**configuration):
        calls.append(configuration)
        return {"status": "pending"}

    monkeypatch.setattr(cli, "run_capture", capture)
    assert cli.wait_for_capture(client=None, wait_seconds=wait, poll_seconds=60) == {
        "status": "pending"
    }
    assert len(calls) == 1
    assert clock.sleeps == ([] if wait == 0 else [wait])


def test_capture_step_can_exhaust_polling_budget(monkeypatch, clock):
    def capture(**_):
        clock.now = 200
        return {"status": "pending"}

    monkeypatch.setattr(cli, "run_capture", capture)
    assert cli.wait_for_capture(client=None, wait_seconds=100, poll_seconds=60)["status"] == (
        "pending"
    )
    assert clock.sleeps == []


@pytest.mark.parametrize("failure", [ValueError("synthetic"), KeyboardInterrupt()])
def test_errors_and_interrupts_are_not_retried(monkeypatch, clock, failure):
    calls = []

    def capture(**_):
        calls.append(1)
        raise failure

    monkeypatch.setattr(cli, "run_capture", capture)
    with pytest.raises(type(failure)):
        cli.wait_for_capture(client=None, wait_seconds=100, poll_seconds=60)
    assert calls == [1] and clock.sleeps == []


def test_unknown_status_fails_closed(monkeypatch, clock):
    monkeypatch.setattr(cli, "run_capture", lambda **_: {"status": "unexpected"})
    with pytest.raises(cli.CaptureError, match="unexpected capture status"):
        cli.wait_for_capture(client=None, wait_seconds=100, poll_seconds=60)
    assert clock.sleeps == []


@pytest.mark.parametrize(("wait", "poll"), [(-1, 60), (86401, 60), (10, 0), (10, 3601)])
def test_invalid_schedule_makes_no_capture_call(monkeypatch, clock, wait, poll):
    def unexpected(**_):
        pytest.fail("capture must not start")

    monkeypatch.setattr(cli, "run_capture", unexpected)
    with pytest.raises(cli.CaptureError, match="invalid capture wait configuration"):
        cli.wait_for_capture(client=None, wait_seconds=wait, poll_seconds=poll)


def test_ready_needs_no_wait(monkeypatch, clock):
    monkeypatch.setattr(cli, "run_capture", lambda **_: {"status": "candidate-ready"})
    assert cli.wait_for_capture(client=None, wait_seconds=0, poll_seconds=60) == {
        "status": "candidate-ready"
    }
    assert clock.sleeps == []
