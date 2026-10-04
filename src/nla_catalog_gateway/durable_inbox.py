"""Local persistent receipt/replay of already authenticated catalog webhooks.

This is storage, not an HTTP authorizer or publication worker. A caller must
verify Shopify HMAC before receive(), and publish durably before complete().
Uncompleted deliveries replay after restart; publication must be idempotent.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path

from nla_catalog_gateway.sync import (
    DEFAULT_MAX_INBOX_EVENTS,
    DEFAULT_MAX_INBOX_RETAINED_BYTES,
    SUPPORTED_TOPIC_CATEGORIES,
    RawWebhookEnvelope,
    WebhookKey,
)

_ERROR = "durable webhook inbox operation failed"
_APPLICATION_ID = 1313625929
_GENERATION = re.compile(r"sha256:[0-9a-f]{64}\Z")


class DurableInboxError(RuntimeError):
    """Value-free failure; no delivery may be acknowledged on this exception."""


class ReceiptOutcome(StrEnum):
    RECEIVED = "received"
    DUPLICATE = "duplicate"
    CONFLICT = "conflict"


@dataclass(frozen=True, slots=True, repr=False)
class PendingDelivery:
    sequence: int
    revision: int
    envelope: RawWebhookEnvelope
    reconciliation_required: bool


class DurableWebhookInbox:
    """One private, host-owned SQLite inbox per shop; no automatic eviction.

    Each operation uses a separate connection and a bounded transaction. FULL
    synchronous rollback journaling commits receipt before returning. The parent
    directory must be private to the host operator, outside the source repository.
    """

    def __init__(
        self,
        path: Path,
        shop_domain: str,
        *,
        max_events: int = DEFAULT_MAX_INBOX_EVENTS,
        max_bytes: int = DEFAULT_MAX_INBOX_RETAINED_BYTES,
    ) -> None:
        try:
            if (
                not isinstance(path, Path)
                or not path.is_absolute()
                or not path.parent.is_dir()
                or type(max_events) is not int
                or max_events < 1
                or type(max_bytes) is not int
                or max_bytes < 1
            ):
                raise ValueError
            self._shop = WebhookKey(shop_domain, "configuration").shop_domain
            self._path = path
            self._max_events = max_events
            self._max_bytes = max_bytes
            with self._transaction(create=True):
                pass
        except (OSError, TypeError, ValueError):
            raise DurableInboxError(_ERROR) from None

    @property
    def shop_domain(self) -> str:
        return self._shop

    @contextmanager
    def _transaction(self, *, create: bool = False) -> Iterator[sqlite3.Connection]:
        try:
            if self._path.is_symlink():
                raise DurableInboxError(_ERROR)
            uri = self._path.as_uri() + ("?mode=rwc" if create else "?mode=rw")
            connection = sqlite3.connect(uri, uri=True, timeout=1)
            try:
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA synchronous = FULL")
                connection.execute("BEGIN IMMEDIATE")
                self._schema(connection, create=create)
                yield connection
                connection.commit()
            finally:
                connection.close()
        except (OSError, sqlite3.Error, TypeError, ValueError):
            raise DurableInboxError(_ERROR) from None

    def _schema(self, db: sqlite3.Connection, *, create: bool) -> None:
        app_id = db.execute("PRAGMA application_id").fetchone()[0]
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if app_id == 0 and version == 0 and create:
            if db.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone() is not None:
                raise DurableInboxError(_ERROR)
            db.execute("CREATE TABLE inbox_config (shop TEXT NOT NULL)")
            db.execute("INSERT INTO inbox_config VALUES (?)", (self._shop,))
            db.execute(
                """CREATE TABLE deliveries (
                    sequence INTEGER PRIMARY KEY,
                    webhook_id TEXT NOT NULL UNIQUE,
                    topic TEXT NOT NULL, api_version TEXT NOT NULL,
                    received_at TEXT NOT NULL, payload BLOB NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    retained_bytes INTEGER NOT NULL CHECK (retained_bytes > 0),
                    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
                    reconciliation_required INTEGER NOT NULL CHECK (
                        reconciliation_required IN (0, 1)),
                    completed_generation TEXT
                )"""
            )
            db.execute("PRAGMA application_id = 1313625929")
            db.execute("PRAGMA user_version = 1")
        elif app_id != _APPLICATION_ID or version != 1:
            raise DurableInboxError(_ERROR)
        shops = db.execute("SELECT shop FROM inbox_config").fetchall()
        if len(shops) != 1 or shops[0][0] != self._shop:
            raise DurableInboxError(_ERROR)

    def receive(self, envelope: RawWebhookEnvelope) -> ReceiptOutcome:
        """Commit receipt, or durably flag a conflict without replacing its bytes."""
        try:
            if type(envelope) is not RawWebhookEnvelope:
                raise ValueError
            safe = replace(envelope)
            if safe.shop_domain != self._shop:
                raise ValueError
        except (TypeError, ValueError):
            raise DurableInboxError(_ERROR) from None
        with self._transaction() as db:
            row = db.execute(
                "SELECT topic, api_version, payload_sha256 FROM deliveries WHERE webhook_id = ?",
                (safe.webhook_id,),
            ).fetchone()
            if row is not None:
                if tuple(row) == (safe.topic, safe.api_version, safe.payload_sha256):
                    return ReceiptOutcome.DUPLICATE
                db.execute(
                    """UPDATE deliveries SET revision = revision + 1,
                       reconciliation_required = 1, completed_generation = NULL
                       WHERE webhook_id = ?""",
                    (safe.webhook_id,),
                )
                return ReceiptOutcome.CONFLICT
            retained = len(safe.payload) + sum(
                len(value.encode("utf-8"))
                for value in (
                    safe.shop_domain,
                    safe.webhook_id,
                    safe.topic,
                    safe.api_version,
                    safe.received_at,
                    safe.payload_sha256,
                )
            )
            count, size = db.execute(
                "SELECT COUNT(*), COALESCE(SUM(retained_bytes), 0) FROM deliveries"
            ).fetchone()
            if count >= self._max_events or size + retained > self._max_bytes:
                raise DurableInboxError(_ERROR)
            db.execute(
                """INSERT INTO deliveries (webhook_id, topic, api_version, received_at,
                   payload, payload_sha256, retained_bytes, reconciliation_required)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    safe.webhook_id,
                    safe.topic,
                    safe.api_version,
                    safe.received_at,
                    safe.payload,
                    safe.payload_sha256,
                    retained,
                    int(safe.topic not in SUPPORTED_TOPIC_CATEGORIES),
                ),
            )
            return ReceiptOutcome.RECEIVED

    def pending(self, *, limit: int = 100) -> tuple[PendingDelivery, ...]:
        """Read a bounded batch without claiming/removing it, so crashes replay."""
        if type(limit) is not int or not 1 <= limit <= 100:
            raise DurableInboxError(_ERROR)
        with self._transaction() as db:
            rows = db.execute(
                """SELECT * FROM deliveries WHERE completed_generation IS NULL
                   ORDER BY sequence LIMIT ?""",
                (limit,),
            ).fetchall()
            result = []
            for row in rows:
                if (
                    type(row["sequence"]) is not int
                    or row["sequence"] < 1
                    or type(row["revision"]) is not int
                    or row["revision"] < 1
                    or row["reconciliation_required"] not in (0, 1)
                ):
                    raise DurableInboxError(_ERROR)
                envelope = RawWebhookEnvelope(
                    self._shop,
                    row["webhook_id"],
                    row["topic"],
                    row["api_version"],
                    row["received_at"],
                    row["payload"],
                    row["payload_sha256"],
                )
                result.append(
                    PendingDelivery(
                        row["sequence"],
                        row["revision"],
                        envelope,
                        bool(row["reconciliation_required"]),
                    )
                )
            return tuple(result)

    def complete(
        self,
        delivery: PendingDelivery,
        *,
        dataset_generation: str,
        reconciled: bool = False,
    ) -> None:
        """After durable publication, record completion with a conflict revision guard.

        The caller owns publication/reconciliation evidence; this records its receipt,
        not proof that a generation is actually active. An interrupted caller can replay.
        """
        if (
            type(delivery) is not PendingDelivery
            or type(delivery.envelope) is not RawWebhookEnvelope
            or delivery.envelope.shop_domain != self._shop
            or type(delivery.sequence) is not int
            or delivery.sequence < 1
            or type(delivery.revision) is not int
            or delivery.revision < 1
            or type(delivery.reconciliation_required) is not bool
            or type(dataset_generation) is not str
            or _GENERATION.fullmatch(dataset_generation) is None
            or type(reconciled) is not bool
            or (delivery.reconciliation_required and not reconciled)
        ):
            raise DurableInboxError(_ERROR)
        with self._transaction() as db:
            changed = db.execute(
                """UPDATE deliveries SET completed_generation = ?
                   WHERE sequence = ? AND webhook_id = ? AND payload_sha256 = ?
                   AND revision = ? AND completed_generation IS NULL
                   AND (reconciliation_required = 0 OR ? = 1)""",
                (
                    dataset_generation,
                    delivery.sequence,
                    delivery.envelope.webhook_id,
                    delivery.envelope.payload_sha256,
                    delivery.revision,
                    int(reconciled),
                ),
            ).rowcount
            if changed != 1:
                raise DurableInboxError(_ERROR)
