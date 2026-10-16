# src/api/async_client.py
# This file contains the asynchronous client for the Open Library API.

import asyncio

import httpx

from api.http import (
    BASE_URL,
    DEFAULT_BACKOFF_SECONDS,
    DEFAULT_MAX_RETRIES,
    DEFAULT_TIMEOUT,
    RETRYABLE_STATUS_CODES,
    USER_AGENT,
    author_works_path,
    default_ssl_context,
    normalize_subject,
    raise_for_status,
    require_text,
    retry_delay_seconds,
    work_path,
)
from exceptions import APIError, DataValidationError


class AsyncLibraryClient:
    """Asynchronous client for the Open Library REST API."""

    def __init__(
        self,
        *,
        base_url: str = BASE_URL,
        timeout: float | httpx.Timeout = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """Initialize the asynchronous client."""
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self._client = client
        self._owns_client = client is None

    async def __aenter__(self) -> "AsyncLibraryClient":
        """Enter the asynchronous client context."""
        self._http()
        return self

    async def __aexit__(self, *args: object) -> None:
        """Exit the asynchronous client context."""
        await self.aclose()

    async def aclose(self) -> None:
        """Close the asynchronous client."""
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def search(self, query: str, *, page: int = 1) -> dict:
        """Search for works."""
        query = require_text(query, "query")
        if page < 1:
            raise DataValidationError("Page must be at least 1.", field="page")
        return await self._get("/search.json", params={"q": query, "page": page})

    async def get_work(self, work_id: str) -> dict:
        """Get a work."""
        return await self._get(work_path(work_id))

    async def get_author_works(self, author_id: str) -> dict:
        """Get the works of an author."""
        return await self._get(author_works_path(author_id))

    async def get_subject(
        self,
        subject: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        """Get a subject."""
        self._validate_paging(limit, offset)
        subject = normalize_subject(subject)
        return await self._get(
            f"/subjects/{subject}.json",
            params={"limit": limit, "offset": offset},
        )

    async def _get(self, path: str, params: dict | None = None) -> dict:
        """Get a resource."""
        url = f"{self.base_url}{path}"
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = await self._http().get(url, params=params)
            except httpx.TransportError as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                await asyncio.sleep(
                    retry_delay_seconds(None, attempt, self.backoff_seconds)
                )
                continue
            if (
                response.status_code in RETRYABLE_STATUS_CODES
                and attempt < self.max_retries
            ):
                await asyncio.sleep(
                    retry_delay_seconds(response, attempt, self.backoff_seconds)
                )
                continue
            raise_for_status(response)
            return response.json()
        detail = (
            f"{type(last_error).__name__}: {last_error}"
            if last_error
            else "no response"
        )
        message = (
            f"Open Library request failed after {self.max_retries + 1} "
            f"attempts ({detail}): {url}"
        )
        raise APIError(message, url=url) from last_error

    def _http(self) -> httpx.AsyncClient:
        """Get the HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                verify=default_ssl_context(),
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            )
        return self._client

    @staticmethod
    def _validate_paging(limit: int, offset: int) -> None:
        """Validate the paging."""
        if limit < 1:
            raise DataValidationError("Limit must be at least 1.", field="limit")
        if offset < 0:
            raise DataValidationError("Offset cannot be negative.", field="offset")
