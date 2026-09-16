from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from pathlib import Path

import pytest

from nla_catalog_gateway import durable_inbox
from nla_catalog_gateway.durable_inbox import (
    DurableInboxError,
    DurableWebhookInbox,
    ReceiptOutcome,
)
from nla_catalog_gateway.sync import RawWebhookEnvelope

SHOP = "synthetic-nla.myshopify.com"
GENERATION = "sha256:" + "a" * 64


def envelope(**changes: object) -> RawWebhookEnvelope:
    values = dict(
        shop_domain=SHOP,
        webhook_id="delivery-1",
        topic="products/update",
        api_version="2026-07",
        received_at="2026-09-16T00:00:00Z",
        payload=b'{"id":123}',
    )
    values.update(changes)
    return RawWebhookEnvelope(**values)


def inbox(tmp_path: Path, **limits: int) -> DurableWebhookInbox:
    return DurableWebhookInbox(tmp_path / "inbox.sqlite3", SHOP, **limits)


def test_reopen_replay_and_completion(tmp_path: Path) -> None:
    store = inbox(tmp_path)
    assert store.receive(envelope()) is ReceiptOutcome.RECEIVED
    (delivery,) = inbox(tmp_path).pending()
    assert delivery.envelope == envelope()
    assert delivery.revision == 1 and not delivery.reconciliation_required
    assert store.pending() == (delivery,)
    store.complete(delivery, dataset_generation=GENERATION)
    assert inbox(tmp_path).pending() == ()
    assert inbox(tmp_path).receive(envelope()) is ReceiptOutcome.DUPLICATE
    assert store.pending() == ()
    with pytest.raises(DurableInboxError):
        store.complete(delivery, dataset_generation=GENERATION)


def test_duplicate_keeps_first_receipt_and_revision(tmp_path: Path) -> None:
    store = inbox(tmp_path)
    store.receive(envelope())
    (first,) = store.pending()
    assert store.receive(envelope(received_at="2026-09-16T01:00:00Z")) == "duplicate"
    assert store.pending() == (first,)
    assert "123" not in repr(first) and "payload" not in repr(first)


@pytest.mark.parametrize(
    "change",
    [
        {"payload": b'{"id":456}'},
        {"topic": "products/delete"},
        {"api_version": "2026-04"},
    ],
)
@pytest.mark.parametrize("previously_completed", [False, True])
def test_conflicts_persist_and_reopen_completion(
    tmp_path: Path,
    change: dict[str, object],
    previously_completed: bool,
) -> None:
    store = inbox(tmp_path)
    store.receive(envelope())
    (old,) = store.pending()
    if previously_completed:
        store.complete(old, dataset_generation=GENERATION)
    assert store.receive(envelope(**change)) is ReceiptOutcome.CONFLICT
    (current,) = inbox(tmp_path).pending()
    assert current.revision == 2 and current.reconciliation_required
    assert current.envelope == old.envelope
    assert store.receive(envelope()) is ReceiptOutcome.DUPLICATE
    assert inbox(tmp_path).pending() == (current,)
    with pytest.raises(DurableInboxError):
        store.complete(old, dataset_generation=GENERATION, reconciled=True)
    with pytest.raises(DurableInboxError):
        store.complete(current, dataset_generation=GENERATION)
    store.complete(current, dataset_generation=GENERATION, reconciled=True)
    assert inbox(tmp_path).pending() == ()


def test_unknown_topic_requires_explicit_reconciliation(tmp_path: Path) -> None:
    store = inbox(tmp_path)
    store.receive(envelope(topic="future/change"))
    (pending,) = store.pending()
    assert pending.reconciliation_required
    # A forged snapshot flag must not bypass the persisted requirement.
    with pytest.raises(DurableInboxError):
        store.complete(
            replace(pending, reconciliation_required=False), dataset_generation=GENERATION
        )
    store.complete(pending, dataset_generation=GENERATION, reconciled=True)


def test_concurrent_receipts_have_one_identity(tmp_path: Path) -> None:
    store = inbox(tmp_path)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: store.receive(envelope()), range(20)))
    assert results.count(ReceiptOutcome.RECEIVED) == 1
    assert results.count(ReceiptOutcome.DUPLICATE) == 19
    assert len(inbox(tmp_path).pending()) == 1


def test_bounded_replay_order_capacity_and_completed_dedupe(tmp_path: Path) -> None:
    store = inbox(tmp_path, max_events=2)
    store.receive(envelope(webhook_id="first"))
    store.receive(envelope(webhook_id="second"))
    (first,) = store.pending(limit=1)
    assert first.envelope.webhook_id == "first"
    store.complete(first, dataset_generation=GENERATION)
    assert store.pending()[0].envelope.webhook_id == "second"
    assert store.receive(envelope(webhook_id="first")) == "duplicate"
    with pytest.raises(DurableInboxError):
        store.receive(envelope(webhook_id="third"))
    assert len(store.pending()) == 1


def test_byte_capacity_does_not_acknowledge_or_lose_existing(tmp_path: Path) -> None:
    store = inbox(tmp_path, max_bytes=1)
    with pytest.raises(DurableInboxError):
        store.receive(envelope())
    assert store.pending() == ()


@pytest.mark.parametrize("limit", [0, -1, 101, True, "1"])
def test_invalid_replay_limit(tmp_path: Path, limit: object) -> None:
    with pytest.raises(DurableInboxError):
        inbox(tmp_path).pending(limit=limit)


@pytest.mark.parametrize(
    "options",
    [
        {"max_events": 0},
        {"max_events": True},
        {"max_bytes": 0},
        {"max_bytes": "1"},
    ],
)
def test_invalid_capacity(tmp_path: Path, options: dict[str, object]) -> None:
    with pytest.raises(DurableInboxError):
        inbox(tmp_path, **options)


@pytest.mark.parametrize("path", ["not-a-path", Path("relative.db")])
def test_invalid_path(path: object) -> None:
    with pytest.raises(DurableInboxError):
        DurableWebhookInbox(path, SHOP)


def test_missing_parent_and_invalid_shop(tmp_path: Path) -> None:
    with pytest.raises(DurableInboxError):
        DurableWebhookInbox(tmp_path / "absent" / "inbox.db", SHOP)
    with pytest.raises(DurableInboxError):
        DurableWebhookInbox(tmp_path / "inbox.db", "not-a-shop")


def test_cross_shop_and_invalid_or_tampered_envelope(tmp_path: Path) -> None:
    store = inbox(tmp_path)
    for value in (None, envelope(shop_domain="other.myshopify.com")):
        with pytest.raises(DurableInboxError):
            store.receive(value)
    invalid = envelope()
    object.__setattr__(invalid, "payload_sha256", "wrong")
    with pytest.raises(DurableInboxError):
        store.receive(invalid)
    assert store.pending() == ()
    with pytest.raises(DurableInboxError):
        DurableWebhookInbox(tmp_path / "inbox.sqlite3", "other.myshopify.com")


@pytest.mark.parametrize(
    "change",
    [
        {"sequence": True},
        {"sequence": 0},
        {"sequence": 999},
        {"revision": True},
        {"revision": 0},
        {"revision": 999},
        {"reconciliation_required": 1},
        {"envelope": None},
        {"envelope": envelope(shop_domain="other.myshopify.com")},
    ],
)
def test_bad_completion_token(tmp_path: Path, change: dict[str, object]) -> None:
    store = inbox(tmp_path)
    store.receive(envelope())
    (original,) = store.pending()
    with pytest.raises(DurableInboxError):
        store.complete(replace(original, **change), dataset_generation=GENERATION)
    assert store.pending() == (original,)


@pytest.mark.parametrize("generation", [None, "wrong", "sha256:" + "g" * 64])
def test_bad_completion_arguments(tmp_path: Path, generation: object) -> None:
    store = inbox(tmp_path)
    store.receive(envelope())
    (pending,) = store.pending()
    with pytest.raises(DurableInboxError):
        store.complete(pending, dataset_generation=generation)
    with pytest.raises(DurableInboxError):
        store.complete(None, dataset_generation=GENERATION)
    with pytest.raises(DurableInboxError):
        store.complete(pending, dataset_generation=GENERATION, reconciled=1)


def test_foreign_database_not_modified(tmp_path: Path) -> None:
    path = tmp_path / "inbox.sqlite3"
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE keep_me (value)")
        db.execute("INSERT INTO keep_me VALUES ('untouched')")
    before = path.read_bytes()
    with pytest.raises(DurableInboxError):
        inbox(tmp_path)
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "sql",
    [
        "PRAGMA application_id = 123",
        "PRAGMA user_version = 999",
        "DELETE FROM inbox_config",
        "INSERT INTO inbox_config SELECT * FROM inbox_config",
    ],
)
def test_wrong_store_metadata_rejected(tmp_path: Path, sql: str) -> None:
    store = inbox(tmp_path)
    with closing(sqlite3.connect(tmp_path / "inbox.sqlite3")) as db, db:
        db.execute(sql)
    with pytest.raises(DurableInboxError):
        store.pending()


def test_corrupted_payload_rejected(tmp_path: Path) -> None:
    store = inbox(tmp_path)
    store.receive(envelope())
    with closing(sqlite3.connect(tmp_path / "inbox.sqlite3")) as db, db:
        db.execute("UPDATE deliveries SET payload = ?", (b"changed",))
    with pytest.raises(DurableInboxError, match=r"^durable webhook inbox operation failed$"):
        store.pending()


@pytest.mark.parametrize(
    "assignment",
    [
        "sequence = -1",
        "revision = 'invalid'",
        "reconciliation_required = 2",
    ],
)
def test_corrupt_replay_state_rejected(tmp_path: Path, assignment: str) -> None:
    store = inbox(tmp_path)
    store.receive(envelope())
    with closing(sqlite3.connect(tmp_path / "inbox.sqlite3")) as db, db:
        db.execute("PRAGMA ignore_check_constraints = ON")
        db.execute("UPDATE deliveries SET " + assignment)  # noqa: S608
    with pytest.raises(DurableInboxError):
        store.pending()


def test_missing_file_not_recreated_by_existing_instance(tmp_path: Path) -> None:
    store = inbox(tmp_path)
    path = tmp_path / "inbox.sqlite3"
    path.rename(tmp_path / "retained.sqlite3")
    with pytest.raises(DurableInboxError):
        store.receive(envelope())
    assert not path.exists()


def test_symlink_rejected_without_platform_privileges(tmp_path: Path, monkeypatch) -> None:
    store = inbox(tmp_path)
    monkeypatch.setattr(Path, "is_symlink", lambda _: True)
    with pytest.raises(DurableInboxError):
        store.pending()


def test_failed_commit_rolls_back_and_error_is_value_free(tmp_path: Path, monkeypatch) -> None:
    store = inbox(tmp_path)
    connect = sqlite3.connect

    class FailedCommit(sqlite3.Connection):
        def commit(self) -> None:
            raise sqlite3.OperationalError("private injected diagnostic")

    with monkeypatch.context() as scoped:
        scoped.setattr(
            durable_inbox.sqlite3,
            "connect",
            lambda *a, **k: connect(
                *a,
                **k,
                factory=FailedCommit,
            ),
        )
        with pytest.raises(DurableInboxError) as error:
            store.receive(envelope())
        assert str(error.value) == "durable webhook inbox operation failed"
    assert inbox(tmp_path).pending() == ()


def test_real_process_exit_committed_receipt_and_uncommitted_change(tmp_path: Path) -> None:
    path = tmp_path / "inbox.sqlite3"
    script = """
import os, sys
from pathlib import Path
from nla_catalog_gateway.durable_inbox import DurableWebhookInbox
from nla_catalog_gateway.sync import RawWebhookEnvelope
store = DurableWebhookInbox(Path(sys.argv[1]), "synthetic-nla.myshopify.com")
store.receive(RawWebhookEnvelope("synthetic-nla.myshopify.com", "delivery-1",
    "products/update", "2026-07", "2026-09-16T00:00:00Z", b'{"id":123}'))
with store._transaction() as db:
    db.execute("UPDATE deliveries SET completed_generation = ?", ("sha256:" + "a"*64,))
    os._exit(0)
"""
    environment = dict(os.environ, PYTHONPATH=str(Path(__file__).parents[1] / "src"))
    subprocess.run(  # noqa: S603
        [sys.executable, "-B", "-c", script, str(path)],
        check=True,
        timeout=20,
        capture_output=True,
        env=environment,
    )
    (pending,) = inbox(tmp_path).pending()
    assert pending.envelope == envelope()
    assert inbox(tmp_path).receive(envelope()) == "duplicate"
