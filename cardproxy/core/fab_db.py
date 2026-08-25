"""
SQLite-backed FAB card collection storage.

Replaces the previous ``fab-cards-collection-commit-<sha>.json`` snapshot. The
DB lives at ``<collection_output>/fab-cards-collection.sqlite3`` and stores one
row per ``(name, pitch)`` plus a small key/value metadata table.

Write policy
------------
``insert_cards_if_absent`` uses ``INSERT OR IGNORE`` — the refresh path only
adds brand-new ``(name, pitch)`` rows and never mutates existing ones. The
``locked`` column is reserved for hand-curated entries: any future path that
starts mutating existing rows must honour it.
"""

import json
import os
import sqlite3
from collections.abc import Iterable
from typing import Any

from .models import CollectionMetadata

DB_FILENAME = "fab-cards-collection.sqlite3"
SCHEMA_VERSION = 1

_UPDATABLE_FIELDS = frozenset(
    (
        "uuid",
        "printing_uuid",
        "identifier",
        "image_url",
        "is_hero",
        "is_token",
        "tokens",
        "backside",
        "locked",
    )
)


class FabCollectionDB:
    """Thin SQLite wrapper for the FAB card collection."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        # check_same_thread=False lets the GUI's background regen thread and
        # the render thread each use the connection they open — connections
        # themselves are not shared between threads.
        self.connection = sqlite3.connect(db_path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self._ensure_schema()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "FabCollectionDB":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _ensure_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY
            );

            CREATE TABLE IF NOT EXISTS cards (
                name           TEXT NOT NULL,
                pitch          TEXT NOT NULL,
                uuid           TEXT,
                printing_uuid  TEXT,
                identifier     TEXT,
                image_url      TEXT,
                is_hero        INTEGER NOT NULL DEFAULT 0,
                is_token       INTEGER NOT NULL DEFAULT 0,
                tokens         TEXT,
                backside       TEXT,
                locked         INTEGER NOT NULL DEFAULT 0,
                created_at     TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at     TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (name, pitch)
            );

            CREATE INDEX IF NOT EXISTS idx_cards_identifier
                ON cards(identifier);

            CREATE TABLE IF NOT EXISTS collection_metadata (
                key   TEXT PRIMARY KEY,
                value TEXT
            );
            """
        )
        self.connection.execute(
            "INSERT OR IGNORE INTO schema_version(version) VALUES (?)",
            (SCHEMA_VERSION,),
        )
        self.connection.commit()

    def is_empty(self) -> bool:
        return self.connection.execute("SELECT 1 FROM cards LIMIT 1").fetchone() is None

    def card_count(self) -> int:
        return self.connection.execute("SELECT COUNT(*) FROM cards").fetchone()[0]

    def get_card(self, name: str, pitch: str) -> dict | None:
        row = self.connection.execute(
            "SELECT * FROM cards WHERE name = ? AND pitch = ?",
            (name, pitch),
        ).fetchone()
        return _row_to_card(row) if row is not None else None

    def resolve_identifier(self, identifier: str) -> tuple[str, str] | None:
        row = self.connection.execute(
            "SELECT name, pitch FROM cards WHERE identifier = ? LIMIT 1",
            (identifier,),
        ).fetchone()
        return (row["name"], row["pitch"]) if row is not None else None

    def get_commit_hash(self) -> str | None:
        row = self.connection.execute(
            "SELECT value FROM collection_metadata WHERE key = 'hash'"
        ).fetchone()
        return row["value"] if row is not None else None

    def get_metadata(self) -> dict[str, str]:
        return {
            r["key"]: r["value"]
            for r in self.connection.execute(
                "SELECT key, value FROM collection_metadata"
            )
        }

    def iter_cards(self) -> Iterable[dict]:
        for r in self.connection.execute("SELECT * FROM cards ORDER BY name, pitch"):
            yield _row_to_card(r)

    def insert_cards_if_absent(self, cards: Iterable[dict]) -> int:
        """
        Bulk-insert candidate cards. Rows whose (name, pitch) already exist
        are left untouched (locked or not). Returns the number of rows that
        were actually inserted.
        """

        rows = [
            (
                c["name"],
                c["pitch"],
                c.get("uuid"),
                c.get("printing_uuid"),
                c.get("identifier"),
                c.get("image_url"),
                1 if c.get("is_hero") else 0,
                1 if c.get("is_token") else 0,
                json.dumps(c["tokens"]) if c.get("tokens") else None,
                json.dumps(c["backside"]) if c.get("backside") else None,
            )
            for c in cards
        ]
        if not rows:
            return 0
        before = self.card_count()
        with self.connection:
            self.connection.executemany(
                """
                INSERT OR IGNORE INTO cards
                    (name, pitch, uuid, printing_uuid, identifier, image_url,
                     is_hero, is_token, tokens, backside)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
        return self.card_count() - before

    def upsert_metadata(self, metadata: CollectionMetadata) -> None:
        with self.connection:
            for k, v in metadata.model_dump().items():
                self.connection.execute(
                    """
                    INSERT INTO collection_metadata(key, value) VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                    """,
                    (k, str(v)),
                )

    def set_locked(self, name: str, pitch: str, locked: bool = True) -> bool:
        with self.connection:
            cur = self.connection.execute(
                "UPDATE cards SET locked = ?, updated_at = datetime('now') "
                "WHERE name = ? AND pitch = ?",
                (1 if locked else 0, name, pitch),
            )
        return cur.rowcount > 0

    def update_card(
        self,
        name: str,
        pitch: str,
        fields: dict[str, Any],
        respect_lock: bool = True,
    ) -> bool:
        """
        Manual per-entry update. When ``respect_lock`` is True (default) rows
        with ``locked = 1`` are refused. Returns True iff a row was updated.
        """

        payload: dict[str, Any] = {}
        for k, v in fields.items():
            if k not in _UPDATABLE_FIELDS:
                raise ValueError(f"Unknown card field: {k}")
            if k in ("tokens", "backside"):
                payload[k] = json.dumps(v) if v is not None else None
            elif k in ("is_hero", "is_token", "locked"):
                payload[k] = 1 if v else 0
            else:
                payload[k] = v

        if not payload:
            return False

        row = self.connection.execute(
            "SELECT locked FROM cards WHERE name = ? AND pitch = ?",
            (name, pitch),
        ).fetchone()
        if row is None:
            return False
        if respect_lock and row["locked"]:
            return False

        set_clause = ", ".join(f"{k} = ?" for k in payload)
        params = [*payload.values(), name, pitch]
        with self.connection:
            self.connection.execute(
                f"UPDATE cards SET {set_clause}, updated_at = datetime('now') "
                "WHERE name = ? AND pitch = ?",
                params,
            )
        return True


def _row_to_card(row: sqlite3.Row) -> dict:
    return {
        "name": row["name"],
        "pitch": row["pitch"],
        "uuid": row["uuid"],
        "printing_uuid": row["printing_uuid"],
        "identifier": row["identifier"],
        "image_url": row["image_url"],
        "is_hero": bool(row["is_hero"]),
        "is_token": bool(row["is_token"]),
        "tokens": json.loads(row["tokens"]) if row["tokens"] else None,
        "backside": json.loads(row["backside"]) if row["backside"] else None,
        "locked": bool(row["locked"]),
    }
