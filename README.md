# Capstone Project

Catalog tool for the Open Library API. It searches works, stores them in SQLite, cleans a local catalog, and writes Excel, CSV, and JSON reports.

Requires Python 3.12. Dependencies are managed with [uv](https://docs.astral.sh/uv/).

## Setup

```powershell
uv sync
```

`uv sync` creates the local environment from `uv.lock`. Later commands use `uv run` so they execute inside that environment.

## Run the application

```powershell
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

## Quality pipeline

Run these from the repository root, in order. This is the same sequence the diagnostics menu and GitHub Actions use.

```powershell
uv run ruff check
uv run ruff format --check
uv run pytest
```

`ruff check` reports lint problems. `ruff format --check` fails when a file needs formatting; `uv run ruff format` rewrites those files. `pytest` runs the suite in `tests/`, including the mocked Open Library client tests.

## Layout

- `src/api/` — synchronous and asynchronous Open Library clients
- `src/db/` — SQLite storage for works, authors, and the API cache
- `src/processing/` — ISBN checks and pandas summaries
- `src/reporting/` — Excel, CSV, and JSON export
- `src/cli/` — interactive menu
- `.github/workflows/ci.yml` — runs the quality pipeline on every push and pull request
