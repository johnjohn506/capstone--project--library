# Capstone Project

Catalog tool for the Open Library API. It searches works, stores them in SQLite, cleans a local catalog, and writes Excel, CSV, and JSON reports.

Requires Python 3.12. Dependencies are managed with [uv](https://docs.astral.sh/uv/).

## Setup

```powershell
uv sync
uv run python main.py
```

## Menu

1. Ingest works by subject
2. Search by author, title, or ISBN
3. Process and deduplicate a local catalog file
4. Generate analytical reports under `data/outputs/`
5. Health check, cache maintenance, and database administration
6. Run the quality checks and test suite
0. Exit

The database file is `data/library.db`.

## Layout

- `src/api/` — synchronous and asynchronous Open Library clients
- `src/db/` — SQLite storage for works, authors, and the API cache
- `src/processing/` — ISBN checks and pandas summaries
- `src/reporting/` — Excel, CSV, and JSON export
- `src/cli/` — interactive menu
