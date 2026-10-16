# src/reporting/generator.py
# This file contains the generator for the library.

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from processing.analytics import DataProcessor

DEFAULT_OUTPUT_DIR = Path("data") / "outputs"
_HEADER_FILL = PatternFill("solid", fgColor="1F4E79")
_HEADER_FONT = Font(bold=True, color="FFFFFF")


class ReportGenerator:
    """Export catalog data to Excel, CSV, and JSON."""

    def __init__(self, output_dir: Path | str = DEFAULT_OUTPUT_DIR) -> None:
        """Store the directory where report files are written."""
        self.output_dir = Path(output_dir)
        self._processor = DataProcessor()

    def export(
        self,
        works: pd.DataFrame,
        *,
        report_date: date | None = None,
    ) -> dict[str, Path]:
        """Write the workbook, both CSV summaries, and the JSON handoff."""
        stamp = (report_date or datetime.now(UTC).date()).strftime("%Y%m%d")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        years = self._processor.summarize_publication_years(works)
        languages = self._processor.summarize_languages(works)
        excel_path = self.output_dir / f"library_report_{stamp}.xlsx"
        years_path = self.output_dir / f"publication_years_{stamp}.csv"
        languages_path = self.output_dir / f"languages_{stamp}.csv"
        json_path = self.output_dir / f"library_report_{stamp}.json"
        self.write_workbook(
            excel_path,
            {
                "Metrics": _metrics(works, languages),
                "Works": works,
                "Publication Years": years,
                "Languages": languages,
            },
        )
        self.write_csv(years_path, years)
        self.write_csv(languages_path, languages)
        self.write_json(
            json_path,
            {
                "generated_on": stamp,
                "metrics": _records(_metrics(works, languages)),
                "publication_years": _records(years),
                "languages": _records(languages),
            },
        )
        return {
            "excel": excel_path,
            "publication_years_csv": years_path,
            "languages_csv": languages_path,
            "json": json_path,
        }

    def write_workbook(self, path: Path, sheets: dict[str, pd.DataFrame]) -> None:
        """Write each dataset to a formatted worksheet."""
        workbook = Workbook()
        default = workbook.active
        workbook.remove(default)
        for title, frame in sheets.items():
            _write_sheet(workbook.create_sheet(title), frame)
        workbook.save(path)

    def write_csv(self, path: Path, frame: pd.DataFrame) -> None:
        """Write a summary table without the pandas index."""
        frame.to_csv(path, index=False)

    def write_json(self, path: Path, payload: dict) -> None:
        """Write a minified JSON document."""
        path.write_text(
            json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
            encoding="utf-8",
        )


def _metrics(works: pd.DataFrame, languages: pd.DataFrame) -> pd.DataFrame:
    if "first_publish_year" in works:
        dated = works["first_publish_year"].dropna()
    else:
        dated = pd.Series(dtype="Int64")
    return pd.DataFrame(
        [
            {"metric": "works", "value": len(works)},
            {"metric": "works_with_year", "value": len(dated)},
            {"metric": "languages", "value": len(languages)},
            {
                "metric": "earliest_year",
                "value": int(dated.min()) if len(dated) else None,
            },
            {
                "metric": "latest_year",
                "value": int(dated.max()) if len(dated) else None,
            },
        ]
    )


def _write_sheet(worksheet: Worksheet, frame: pd.DataFrame) -> None:
    """Write a worksheet with the given frame."""
    headers = [str(column) for column in frame.columns]
    worksheet.append(headers)
    for cell in worksheet[1]:
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
    for row in frame.itertuples(index=False):
        worksheet.append([_cell_value(value) for value in row])
    worksheet.freeze_panes = "A2"
    worksheet.auto_filter.ref = worksheet.dimensions
    for index, header in enumerate(headers, start=1):
        width = min(max(len(header), 12) + 2, 40)
        worksheet.column_dimensions[get_column_letter(index)].width = width


def _cell_value(value: object) -> object:
    """Convert a cell value to a string."""
    if value is None or pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        if value.tzinfo is not None:
            value = value.tz_convert(None)
        return value.to_pydatetime()
    if hasattr(value, "item"):
        return value.item()
    return value


def _records(frame: pd.DataFrame) -> list[dict]:
    """Convert a frame to a list of records."""
    return json.loads(frame.to_json(orient="records"))
