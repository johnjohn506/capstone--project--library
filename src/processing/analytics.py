# src/processing/analytics.py
# This file contains the analytics for the library.
import json

import pandas as pd

from exceptions import DataValidationError
from processing.cleaner import normalize_text


class DataProcessor:
    """Prepare catalog tables for reporting."""

    def fill_missing(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Normalize text, turn blanks into missing values, and drop untitled works."""
        cleaned = frame.copy()
        for column in cleaned.select_dtypes(include="object").columns:
            cleaned[column] = cleaned[column].map(_normalize_cell)
            cleaned[column] = cleaned[column].replace("", pd.NA)
        if "title" in cleaned.columns:
            cleaned = cleaned.dropna(subset=["title"])
        if "first_publish_year" in cleaned.columns:
            cleaned["first_publish_year"] = pd.to_numeric(
                cleaned["first_publish_year"],
                errors="coerce",
            ).astype("Int64")
        return cleaned.reset_index(drop=True)

    def parse_dates(self, frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
        """Parse timestamp columns and leave unreadable values missing."""
        parsed = frame.copy()
        for column in columns:
            if column not in parsed.columns:
                continue
            parsed[column] = pd.to_datetime(parsed[column], errors="coerce", utc=True)
        return parsed

    def join_authors(
        self,
        works: pd.DataFrame,
        authors: pd.DataFrame,
    ) -> pd.DataFrame:
        """Attach an author name to each work, one row per author id."""
        _require_columns(works, ["author_ids"])
        _require_columns(authors, ["author_id"])
        expanded = works.copy()
        expanded["author_id"] = expanded["author_ids"].map(_json_items)
        expanded = expanded.explode("author_id", ignore_index=True)
        return expanded.merge(authors, on="author_id", how="left")

    def summarize_publication_years(self, works: pd.DataFrame) -> pd.DataFrame:
        """Count works for each publication year, most common year first."""
        _require_columns(works, ["work_id", "first_publish_year"])
        return (
            works.dropna(subset=["first_publish_year"])
            .groupby("first_publish_year", as_index=False)
            .agg(work_count=("work_id", "count"))
            .sort_values(
                ["work_count", "first_publish_year"],
                ascending=[False, True],
                ignore_index=True,
            )
        )

    def summarize_languages(self, works: pd.DataFrame) -> pd.DataFrame:
        """Count works for each language, most common language first."""
        _require_columns(works, ["work_id", "languages"])
        expanded = works.copy()
        expanded["language"] = expanded["languages"].map(_json_items)
        expanded = expanded.explode("language", ignore_index=True)
        expanded = expanded.dropna(subset=["language"])
        return (
            expanded.groupby("language", as_index=False)
            .agg(work_count=("work_id", "count"))
            .sort_values(
                ["work_count", "language"],
                ascending=[False, True],
                ignore_index=True,
            )
        )


def _normalize_cell(value: object) -> object:
    if isinstance(value, str):
        return normalize_text(value)
    return value


def _json_items(value: object) -> list:
    if value is None or pd.isna(value):
        return []
    if isinstance(value, list):
        return value
    if not isinstance(value, str) or not value.strip():
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return [value.strip()]
    if isinstance(parsed, list):
        return parsed
    return []


def _require_columns(frame: pd.DataFrame, columns: list[str]) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise DataValidationError(
            f"Missing columns: {', '.join(missing)}.",
            field="columns",
        )
