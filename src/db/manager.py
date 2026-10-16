# src/db/manager.py
# This file contains the database manager for the library.

import json
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from exceptions import DataValidationError

DEFAULT_DB_PATH = Path("data") / "library.db"
DEFAULT_CACHE_TTL_SECONDS = 86_400

SCHEMA = """
CREATE TABLE IF NOT EXISTS works (
    work_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    first_publish_year INTEGER,
    languages TEXT NOT NULL DEFAULT '[]',
    subjects TEXT NOT NULL DEFAULT '[]',
    isbns TEXT NOT NULL DEFAULT '[]',
    author_ids TEXT NOT NULL DEFAULT '[]',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS authors (
    author_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS api_cache (
    cache_key TEXT PRIMARY KEY,
    endpoint TEXT NOT NULL,
    response_json TEXT NOT NULL,
    fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TEXT NOT NULL,
    hit_count INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_works_title ON works (title);
CREATE INDEX IF NOT EXISTS idx_works_year ON works (first_publish_year);
CREATE INDEX IF NOT EXISTS idx_authors_name ON authors (name);
CREATE INDEX IF NOT EXISTS idx_api_cache_expires_at ON api_cache (expires_at);
"""

_UPSERT_WORK = """
INSERT INTO works (
    work_id, title, description, first_publish_year,
    languages, subjects, isbns, author_ids, updated_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(work_id) DO UPDATE SET
    title = excluded.title,
    description = excluded.description,
    first_publish_year = excluded.first_publish_year,
    languages = excluded.languages,
    subjects = excluded.subjects,
    isbns = excluded.isbns,
    author_ids = excluded.author_ids,
    updated_at = excluded.updated_at
"""

_UPSERT_AUTHOR = """
INSERT INTO authors (author_id, name, updated_at)
VALUES (?, ?, ?)
ON CONFLICT(author_id) DO UPDATE SET
    name = excluded.name,
    updated_at = excluded.updated_at
"""

_UPSERT_CACHE = """
INSERT INTO api_cache (
    cache_key, endpoint, response_json, fetched_at, expires_at, hit_count
) VALUES (?, ?, ?, ?, ?, 0)
ON CONFLICT(cache_key) DO UPDATE SET
    endpoint = excluded.endpoint,
    response_json = excluded.response_json,
    fetched_at = excluded.fetched_at,
    expires_at = excluded.expires_at,
    hit_count = 0
"""


class DatabaseManager:
    """SQLite storage for works, authors, and cached API responses."""

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH) -> None:
        """Initialize the database manager."""
        self.db_path = Path(db_path)
        self._connection: sqlite3.Connection | None = None
        self._in_batch = False

    def __enter__(self) -> "DatabaseManager":
        """Enter the database manager context."""
        self.connect()
        return self

    def __exit__(self, *args: object) -> None:
        """Exit the database manager context."""
        self.close()

    def connect(self) -> sqlite3.Connection:
        """Connect to the database."""
        if self._connection is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._connection = sqlite3.connect(self.db_path)
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.executescript(SCHEMA)
        return self._connection

    def close(self) -> None:
        """Close the database connection."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    @contextmanager
    def batch(self) -> Iterator[None]:
        """Commit every write inside this block as one transaction."""
        if self._in_batch:
            yield
            return
        self._in_batch = True
        try:
            yield
            self.connect().commit()
        except Exception:
            self.connect().rollback()
            raise
        finally:
            self._in_batch = False

    def upsert_work(self, work: dict) -> None:
        """Upsert a work."""
        self.upsert_works([work])

    def upsert_works(self, works: Sequence[dict]) -> None:
        """Upsert multiple works."""
        rows = [self._work_row(work) for work in works]
        with self.batch():
            self.connect().executemany(_UPSERT_WORK, rows)

    def upsert_author(self, author: dict) -> None:
        """Upsert an author."""
        self.upsert_authors([author])

    def upsert_authors(self, authors: Sequence[dict]) -> None:
        """Upsert multiple authors."""
        rows = [self._author_row(author) for author in authors]
        with self.batch():
            self.connect().executemany(_UPSERT_AUTHOR, rows)

    def get_cached(self, cache_key: str) -> dict | list | None:
        """Return a cached response when it is still inside its TTL."""
        now = _utc_now()
        connection = self.connect()
        row = connection.execute(
            """
            SELECT response_json FROM api_cache
            WHERE cache_key = ? AND expires_at > ?
            """,
            (cache_key, now),
        ).fetchone()
        if row is None:
            connection.execute(
                "DELETE FROM api_cache WHERE cache_key = ? AND expires_at <= ?",
                (cache_key, now),
            )
            self._commit()
            return None
        connection.execute(
            "UPDATE api_cache SET hit_count = hit_count + 1 WHERE cache_key = ?",
            (cache_key,),
        )
        self._commit()
        return json.loads(row["response_json"])

    def set_cached(
        self,
        cache_key: str,
        endpoint: str,
        response: dict | list,
        *,
        ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
    ) -> None:
        if ttl_seconds < 1:
            raise DataValidationError(
                "TTL must be at least 1 second.",
                field="ttl_seconds",
            )
        now = datetime.now(UTC)
        expires_at = (now + timedelta(seconds=ttl_seconds)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        with self.batch():
            self.connect().execute(
                _UPSERT_CACHE,
                (
                    cache_key,
                    endpoint,
                    json.dumps(response, separators=(",", ":")),
                    now.strftime("%Y-%m-%d %H:%M:%S"),
                    expires_at,
                ),
            )

    def _commit(self) -> None:
        """Commit the current batch."""
        if not self._in_batch:
            self.connect().commit()

    @staticmethod
    def _work_row(work: dict) -> tuple:
        """Get the work row."""
        work_id = str(work.get("work_id", "")).strip()
        title = str(work.get("title", "")).strip()
        if not work_id:
            raise DataValidationError("work_id is empty.", field="work_id")
        if not title:
            raise DataValidationError("title is empty.", field="title")
        return (
            work_id,
            title,
            work.get("description"),
            work.get("first_publish_year"),
            _json_list(work.get("languages"), "languages"),
            _json_list(work.get("subjects"), "subjects"),
            _json_list(work.get("isbns"), "isbns"),
            _json_list(work.get("author_ids"), "author_ids"),
            _utc_now(),
        )

    @staticmethod
    def _author_row(author: dict) -> tuple:
        """Get the author row."""
        author_id = str(author.get("author_id", "")).strip()
        name = str(author.get("name", "")).strip()
        if not author_id:
            raise DataValidationError("author_id is empty.", field="author_id")
        if not name:
            raise DataValidationError("name is empty.", field="name")
        return (author_id, name, _utc_now())


def _utc_now() -> str:
    """Get the current UTC time."""
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


def _json_list(value: object, field: str) -> str:
    """Get the JSON list."""
    if value is None:
        return "[]"
    if not isinstance(value, list):
        raise DataValidationError(f"{field} must be a list.", field=field)
    return json.dumps(value)
