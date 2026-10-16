# src/cli/menu.py
# This file contains the menu for the library.
import asyncio
import csv
import json
import re
import sqlite3
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import pandas as pd

from api.async_client import AsyncLibraryClient
from api.sync_client import SyncLibraryClient
from config import get_settings
from db.manager import DatabaseManager
from exceptions import APIError, DataValidationError, LibraryError
from processing.cleaner import is_valid_isbn, normalize_text
from reporting.generator import ReportGenerator

PAGE_SIZE = 50
"""The number of works to fetch per page."""
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_MENU = """
======================================================================
OPEN LIBRARY INTELLIGENCE & CATALOG AUTOMATION SYSTEM
======================================================================
[1] Ingest Works by Subject
[2] Search Books by Author/Title/ISBN
[3] Process & Deduplicate Local Catalog File
[4] Generate Analytical Reports
[5] System Health, Cache Maintenance & Database Administration
[6] Run Quality Checks & Test Suite Diagnostic
[0] Exit
======================================================================
"""


class CLIApp:
    """Loop-driven terminal menu for the catalog tool."""

    def __init__(self, database: DatabaseManager | None = None) -> None:
        """Store the database used by every menu action."""
        self.database = database or DatabaseManager()

    def run(self) -> None:
        """Prompt until the user exits, catching expected failures."""
        actions = {
            "1": self._ingest_subject,
            "2": self._search,
            "3": self._process_catalog,
            "4": self._generate_reports,
            "5": self._administer,
            "6": self._diagnostics,
        }
        with self.database:
            while True:
                try:
                    print(_MENU)
                    choice = input("Select an option: ").strip()
                    if choice == "0":
                        print("Goodbye.")
                        return
                    action = actions.get(choice)
                    if action is None:
                        print("Enter a number from 0 to 6.")
                        continue
                    action()
                except (DataValidationError, APIError, LibraryError) as exc:
                    print(f"Error: {exc}")
                except KeyboardInterrupt:
                    print("\nGoodbye.")
                    return
                except EOFError:
                    print()
                    return
                except Exception as exc:
                    print(f"Unexpected error: {exc}")

    def _ingest_subject(self) -> None:
        """Ingest works by subject."""
        subject = _required_text("Subject: ", "subject")
        depth = _positive_int("Page depth: ")
        sync_started = time.perf_counter()
        sync_pages = self._fetch_sync(subject, depth)
        sync_elapsed = time.perf_counter() - sync_started
        async_started = time.perf_counter()
        async_pages = asyncio.run(self._fetch_async(subject, depth))
        async_elapsed = time.perf_counter() - async_started
        stored = self._store_subject_pages(subject, sync_pages)
        print(f"Sync fetch:   {sync_elapsed:.2f}s")
        print(f"Async fetch:  {async_elapsed:.2f}s")
        faster = "async" if async_elapsed < sync_elapsed else "sync"
        print(f"Faster run:   {faster}")
        print(f"Cached works: {stored}")
        if not async_pages:
            print("Async fetch returned no pages.")

    def _search(self) -> None:
        """Search books by author/title/ISBN."""
        query = _clean_search(input("Author, title, or ISBN: "))
        rows = self._search_local(query)
        if not rows:
            print("No local match. Querying Open Library.")
            with SyncLibraryClient() as client:
                payload = client.search(query)
            self.database.set_cached(f"search:{query}", "search", payload)
            self._store_search_docs(payload.get("docs", []))
            rows = self._search_local(query)
        _print_works(rows)

    def _process_catalog(self) -> None:
        """Process and deduplicate local catalog file."""
        path = _existing_file("Catalog file (CSV or JSON): ")
        seen: set[tuple[str, str]] = set()
        works: list[dict] = []
        for index, record in enumerate(_iter_catalog(path), start=1):
            work = _catalog_work(record, seen)
            if work is not None:
                works.append(work)
            if index % 25 == 0:
                _progress("Reading catalog", index, index)
        if works:
            self.database.upsert_works(works)
        print(f"Upserted {len(works)} unique works.")

    def _generate_reports(self) -> None:
        """Generate analytical reports."""
        paths = ReportGenerator().export(self._works_frame())
        for label, path in paths.items():
            print(f"{label}: {path}")

    def _administer(self) -> None:
        """System health, cache maintenance and database administration."""
        print(f"Works:       {self._count('works')}")
        print(f"Authors:     {self._count('authors')}")
        print(f"Cache rows:  {self._count('api_cache')}")
        size = self.database.db_path.stat().st_size
        print(f"Database:    {size} bytes")
        print(f"Hit ratio:   {self._hit_ratio():.2%}")
        if _yes_no("Purge expired cache entries? "):
            print(f"Removed {self._purge_expired()} expired cache entries.")
        print("Runtime settings:")
        settings = get_settings().model_dump()
        if not settings:
            print("  No settings are defined yet.")
        for key, value in settings.items():
            print(f"  {key}: {value}")

    def _diagnostics(self) -> None:
        """Run quality checks and test suite diagnostic."""
        commands = (
            ["uv", "run", "ruff", "check"],
            ["uv", "run", "ruff", "format", "--check"],
            ["uv", "run", "pytest"],
        )
        for command in commands:
            print(f"\n$ {' '.join(command)}")
            completed = subprocess.run(command, cwd=_PROJECT_ROOT, check=False)
            print(f"Exit code: {completed.returncode}")

    def _fetch_sync(self, subject: str, depth: int) -> list[dict]:
        """Fetch works by subject using synchronous client."""
        pages = []
        with SyncLibraryClient() as client:
            for index in range(depth):
                pages.append(
                    client.get_subject(
                        subject,
                        limit=PAGE_SIZE,
                        offset=index * PAGE_SIZE,
                    )
                )
                _progress("Sync fetch", index + 1, depth)
        return pages

    async def _fetch_async(self, subject: str, depth: int) -> list[dict]:
        """Fetch works by subject using asynchronous client."""
        completed = 0

        async with AsyncLibraryClient() as client:

            async def fetch(index: int) -> dict:
                nonlocal completed
                payload = await client.get_subject(
                    subject,
                    limit=PAGE_SIZE,
                    offset=index * PAGE_SIZE,
                )
                completed += 1
                _progress("Async fetch", completed, depth)
                return payload

            return list(await asyncio.gather(*(fetch(index) for index in range(depth))))

    def _store_subject_pages(self, subject: str, pages: list[dict]) -> int:
        """Store subject pages in database."""
        works: list[dict] = []
        authors: list[dict] = []
        for index, page in enumerate(pages):
            self.database.set_cached(
                f"subjects:{subject}:{index * PAGE_SIZE}",
                "subjects",
                page,
            )
            for item in page.get("works", []):
                work, page_authors = _work_from_subject(item)
                if work is not None:
                    works.append(work)
                    authors.extend(page_authors)
        if authors:
            self.database.upsert_authors(authors)
        if works:
            self.database.upsert_works(works)
        return len(works)

    def _store_search_docs(self, docs: list[dict]) -> None:
        """Store search documents in database."""
        works = []
        authors = []
        for doc in docs:
            work, page_authors = _work_from_search(doc)
            if work is not None:
                works.append(work)
                authors.extend(page_authors)
        if authors:
            self.database.upsert_authors(authors)
        if works:
            self.database.upsert_works(works)

    def _search_local(self, query: str) -> list[sqlite3.Row]:
        """Search local database for books by author/title/ISBN."""
        pattern = f"%{query}%"
        return (
            self.database.connect()
            .execute(
                """
            SELECT DISTINCT
                w.work_id,
                w.title,
                w.first_publish_year,
                a.name AS author
            FROM works AS w
            LEFT JOIN authors AS a
              ON w.author_ids LIKE '%' || a.author_id || '%'
            WHERE w.title LIKE ?
               OR w.isbns LIKE ?
               OR a.name LIKE ?
            ORDER BY w.title
            """,
                (pattern, pattern, pattern),
            )
            .fetchall()
        )

    def _works_frame(self) -> pd.DataFrame:
        """Get works frame from database."""
        rows = self.database.connect().execute("SELECT * FROM works").fetchall()
        columns = [
            "work_id",
            "title",
            "first_publish_year",
            "languages",
            "author_ids",
        ]
        if not rows:
            return pd.DataFrame(columns=columns)
        return pd.DataFrame([dict(row) for row in rows])

    def _count(self, table: str) -> int:
        if table not in {"works", "authors", "api_cache"}:
            raise DataValidationError("Unknown table.", field="table")
        row = (
            self.database.connect()
            .execute(f"SELECT COUNT(*) AS total FROM {table}")
            .fetchone()
        )
        return int(row["total"])

    def _hit_ratio(self) -> float:
        row = (
            self.database.connect()
            .execute(
                """
            SELECT COALESCE(SUM(hit_count), 0) AS hits, COUNT(*) AS entries
            FROM api_cache
            """
            )
            .fetchone()
        )
        fetches = int(row["hits"]) + int(row["entries"])
        if fetches == 0:
            return 0.0
        return int(row["hits"]) / fetches

    def _purge_expired(self) -> int:
        cursor = self.database.connect().execute(
            "DELETE FROM api_cache WHERE expires_at <= datetime('now')"
        )
        self.database.connect().commit()
        return cursor.rowcount


def _required_text(prompt: str, field: str) -> str:
    """Validate required text input."""
    cleaned = normalize_text(input(prompt))
    if not cleaned:
        raise DataValidationError(f"{field} is empty.", field=field)
    return cleaned


def _positive_int(prompt: str) -> int:
    """Validate positive integer input."""
    raw = input(prompt).strip()
    if not re.fullmatch(r"[1-9]\d*", raw):
        raise DataValidationError(
            "Enter a whole number greater than 0.",
            field="page_depth",
        )
    return int(raw)


def _clean_search(raw: str) -> str:
    """Clean search input."""
    cleaned = normalize_text(raw)
    if not cleaned:
        raise DataValidationError("Query is empty.", field="query")
    compact = re.sub(r"[^0-9Xx]", "", cleaned).upper()
    isbn_shape = re.fullmatch(r"[0-9Xx\-\s]+", cleaned)
    if isbn_shape and len(compact) in {10, 13}:
        if not is_valid_isbn(cleaned):
            raise DataValidationError("ISBN checksum is invalid.", field="isbn")
        return compact
    return cleaned


def _existing_file(prompt: str) -> Path:
    """Validate existing file input."""
    path = Path(input(prompt).strip().strip('"'))
    if path.suffix.lower() not in {".csv", ".json"} or not path.is_file():
        raise DataValidationError(
            "Choose an existing CSV or JSON file.",
            field="catalog",
        )
    return path


def _yes_no(prompt: str) -> bool:
    """Validate yes/no input."""
    answer = input(prompt).strip().casefold()
    if answer not in {"y", "n", "yes", "no"}:
        raise DataValidationError("Enter yes or no.", field="confirm")
    return answer in {"y", "yes"}


def _iter_catalog(path: Path) -> Iterator[dict]:
    """Iterate over catalog file."""
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8", newline="") as handle:
            yield from csv.DictReader(handle)
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("works", payload.get("docs", []))
    if not isinstance(payload, list):
        raise DataValidationError("JSON catalog must be a list.", field="catalog")
    yield from payload


def _catalog_work(record: dict, seen: set[tuple[str, str]]) -> dict | None:
    """Create catalog work from record."""
    title = normalize_text(str(record.get("title", "")))
    isbn = normalize_text(str(record.get("isbn", "")))
    identity = (title.casefold(), isbn)
    if not title or identity in seen:
        return None
    seen.add(identity)
    raw_id = record.get("work_id") or isbn or title
    work_id = normalize_text(str(raw_id)).replace(" ", "_")
    description = normalize_text(str(record.get("description", ""))) or None
    return {
        "work_id": work_id,
        "title": title,
        "description": description,
        "first_publish_year": record.get("first_publish_year"),
        "languages": _list_field(record.get("languages")),
        "subjects": _list_field(record.get("subjects")),
        "isbns": [isbn] if isbn else [],
        "author_ids": _list_field(record.get("author_ids")),
    }


def _work_from_subject(item: dict) -> tuple[dict | None, list[dict]]:
    """Create work from subject item."""
    work_id = str(item.get("key", "")).removeprefix("/works/").strip()
    title = normalize_text(str(item.get("title", "")))
    if not work_id or not title:
        return None, []
    authors = []
    author_ids = []
    for author in item.get("authors") or []:
        author_id = str(author.get("key", "")).removeprefix("/authors/").strip()
        name = normalize_text(str(author.get("name", "")))
        if author_id and name:
            author_ids.append(author_id)
            authors.append({"author_id": author_id, "name": name})
    return {
        "work_id": work_id,
        "title": title,
        "first_publish_year": item.get("first_publish_year"),
        "languages": [],
        "subjects": item.get("subject") or [],
        "isbns": [],
        "author_ids": author_ids,
    }, authors


def _work_from_search(doc: dict) -> tuple[dict | None, list[dict]]:
    """Create work from search document."""
    work_id = str(doc.get("key", "")).removeprefix("/works/").strip()
    title = normalize_text(str(doc.get("title", "")))
    if not work_id or not title:
        return None, []
    author_ids = [str(item) for item in doc.get("author_key") or []]
    names = [normalize_text(str(item)) for item in doc.get("author_name") or []]
    authors = [
        {"author_id": author_id, "name": name}
        for author_id, name in zip(author_ids, names, strict=False)
        if author_id and name
    ]
    return {
        "work_id": work_id,
        "title": title,
        "first_publish_year": doc.get("first_publish_year"),
        "languages": list(doc.get("language") or []),
        "subjects": list(doc.get("subject") or []),
        "isbns": [str(item) for item in doc.get("isbn") or []],
        "author_ids": author_ids,
    }, authors


def _list_field(value: object) -> list:
    """Create list from field value."""
    if isinstance(value, list):
        return [normalize_text(str(item)) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [normalize_text(part) for part in value.split(",") if part.strip()]
    return []


def _print_works(rows: list[sqlite3.Row]) -> None:
    """Print works to console."""
    if not rows:
        print("No results.")
        return
    print(f"{'Work':<14} {'Year':<6} {'Author':<24} Title")
    for row in rows:
        year = row["first_publish_year"]
        year_text = "" if year is None else str(year)
        author = (row["author"] or "")[:24]
        print(f"{row['work_id']:<14} {year_text:<6} {author:<24} {row['title']}")


def _progress(label: str, current: int, total: int) -> None:
    """Display progress bar."""
    filled = int(20 * current / total) if total else 20
    bar = "#" * filled + "-" * (20 - filled)
    print(f"\r{label} [{bar}] {current}/{total}", end="", flush=True)
    if current == total:
        print()
