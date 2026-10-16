# src/api/http.py
# This file contains the HTTP client for the Open Library API.

import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

from exceptions import APIError, DataValidationError, ResourceNotFoundError

BASE_URL = "https://openlibrary.org"
DEFAULT_TIMEOUT = 10.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_SECONDS = 0.5
USER_AGENT = "capstone-project/0.1 (Open Library catalog tool)"
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def require_text(value: str, field: str) -> str:
    """Require a non-empty text value."""
    cleaned = value.strip()
    if not cleaned:
        raise DataValidationError(f"{field} is empty.", field=field)
    return cleaned


def normalize_subject(subject: str) -> str:
    """Normalize the subject."""
    cleaned = "_".join(subject.strip().lower().split())
    if not cleaned or re.fullmatch(r"[\w]+", cleaned) is None:
        raise DataValidationError(
            "Subject contains no usable characters.",
            field="subject",
        )
    return cleaned


def work_path(work_id: str) -> str:
    """Get the path for the work."""
    work_id = require_text(work_id, "work_id")
    work_id = work_id.removeprefix("/works/").removesuffix(".json")
    return f"/works/{work_id}.json"


def author_works_path(author_id: str) -> str:
    """Get the path for the author's works."""
    author_id = require_text(author_id, "author_id")
    author_id = author_id.removeprefix("/authors/").removesuffix("/works.json")
    return f"/authors/{author_id}/works.json"


def retry_delay_seconds(
    response: httpx.Response | None,
    attempt: int,
    base_seconds: float,
) -> float:
    """Get the retry delay seconds."""
    if response is not None and response.status_code == 429:
        delay = _retry_after_seconds(response.headers.get("Retry-After"))
        if delay is not None:
            return delay
    return base_seconds * (2**attempt)


def raise_for_status(response: httpx.Response) -> None:
    """Raise an exception for the response."""
    if response.status_code < 400:
        return
    url = str(response.url)
    if response.status_code == 404:
        raise ResourceNotFoundError(
            f"Open Library resource not found: {url}",
            status_code=404,
            url=url,
        )
    raise APIError(
        f"Open Library request failed with status {response.status_code}: {url}",
        status_code=response.status_code,
        url=url,
    )


def _retry_after_seconds(value: str | None) -> float | None:
    """Get the retry after seconds."""
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - datetime.now(UTC)).total_seconds())
