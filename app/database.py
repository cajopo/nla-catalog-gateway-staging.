from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


@dataclass(frozen=True, slots=True)
class DatabaseStatus:
    ready: bool
    path: str
    dataset_version: str | None = None
    product_count: int | None = None
    source_sha256: str | None = None
    error: str | None = None


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    @contextmanager
    def connect(self, readonly: bool = True) -> Iterator[sqlite3.Connection]:
        if readonly:
            uri = f"file:{self.path.resolve()}?mode=ro&immutable=1"
            connection = sqlite3.connect(uri, uri=True, timeout=5.0)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        try:
            yield connection
        finally:
            connection.close()

    def status(self, expected_product_count: int | None = None) -> DatabaseStatus:
        if not self.path.is_file():
            return DatabaseStatus(False, str(self.path), error="database_missing")
        try:
            with self.connect() as connection:
                integrity = connection.execute("PRAGMA quick_check").fetchone()[0]
                if integrity != "ok":
                    return DatabaseStatus(False, str(self.path), error=f"integrity:{integrity}")
                metadata = {row["key"]: row["value"] for row in connection.execute("SELECT key, value FROM metadata")}
                count = int(metadata.get("product_count", "0"))
                if expected_product_count is not None and count != expected_product_count:
                    return DatabaseStatus(
                        False, str(self.path), metadata.get("dataset_version"), count,
                        metadata.get("source_sha256"), f"count_mismatch:{count}!={expected_product_count}",
                    )
                return DatabaseStatus(
                    True, str(self.path), metadata.get("dataset_version"), count,
                    metadata.get("source_sha256"),
                )
        except (sqlite3.Error, ValueError, OSError) as exc:
            return DatabaseStatus(False, str(self.path), error=f"database_error:{type(exc).__name__}")

    def metadata(self) -> dict[str, str]:
        with self.connect() as connection:
            return {row["key"]: row["value"] for row in connection.execute("SELECT key, value FROM metadata")}
