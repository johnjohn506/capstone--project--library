# tests/test_api_clients.py
# This file contains the tests for the API clients.
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from api.async_client import AsyncLibraryClient
from api.sync_client import SyncLibraryClient
from exceptions import APIError, DataValidationError, ResourceNotFoundError


def _response(
    status: int, payload: dict | None = None, headers: dict | None = None
) -> Mock:
    """Create a mock response."""
    response = Mock()
    response.status_code = status
    response.url = "https://openlibrary.org/example"
    response.headers = headers or {}
    response.json.return_value = payload or {}
    return response


def test_search_returns_payload_and_builds_the_query() -> None:
    """Test that the search returns the payload and builds the query."""
    http = Mock()
    http.get.return_value = _response(200, {"numFound": 1, "docs": [{"title": "Dune"}]})
    client = SyncLibraryClient(client=http, backoff_seconds=0)

    result = client.search("dune", page=2)

    assert result["docs"][0]["title"] == "Dune"
    http.get.assert_called_once_with(
        "https://openlibrary.org/search.json",
        params={"q": "dune", "page": 2},
    )


def test_search_rejects_blank_query_before_calling_http() -> None:
    """Test that the search rejects a blank query before calling HTTP."""
    http = Mock()
    client = SyncLibraryClient(client=http)

    with pytest.raises(DataValidationError) as exc:
        client.search("   ")

    assert exc.value.field == "query"
    http.get.assert_not_called()


def test_missing_work_raises_not_found() -> None:
    """Test that the missing work raises a not found error."""
    http = Mock()
    http.get.return_value = _response(404)
    client = SyncLibraryClient(client=http, backoff_seconds=0)

    with pytest.raises(ResourceNotFoundError) as exc:
        client.get_work("OL0W")

    assert exc.value.status_code == 404
    http.get.assert_called_once_with(
        "https://openlibrary.org/works/OL0W.json",
        params=None,
    )


def test_retryable_status_is_retried_then_returned() -> None:
    """Test that the retryable status is retried then returned."""
    http = Mock()
    http.get.side_effect = [_response(503), _response(200, {"title": "Dune"})]
    client = SyncLibraryClient(client=http, max_retries=2, backoff_seconds=0)

    assert client.get_work("OL45883W") == {"title": "Dune"}
    assert http.get.call_count == 2


def test_transport_errors_raise_after_retries_are_exhausted() -> None:
    """Test that the transport errors raise after retries are exhausted."""
    http = Mock()
    http.get.side_effect = httpx.ConnectError("down")
    client = SyncLibraryClient(client=http, max_retries=1, backoff_seconds=0)

    with pytest.raises(APIError) as exc:
        client.search("dune")

    assert http.get.call_count == 2
    assert exc.value.url == "https://openlibrary.org/search.json"
    assert exc.value.__cause__ is not None


@pytest.mark.asyncio
async def test_async_subject_normalizes_the_path() -> None:
    """Test that the async subject normalizes the path."""
    http = Mock()
    http.get = AsyncMock(return_value=_response(200, {"name": "science_fiction"}))
    client = AsyncLibraryClient(client=http, backoff_seconds=0)

    result = await client.get_subject("Science Fiction", limit=10, offset=0)

    assert result["name"] == "science_fiction"
    http.get.assert_awaited_once_with(
        "https://openlibrary.org/subjects/science_fiction.json",
        params={"limit": 10, "offset": 0},
    )


@pytest.mark.asyncio
async def test_async_retries_connect_errors() -> None:
    """Test that the async retries connect errors."""
    http = Mock()
    http.get = AsyncMock(
        side_effect=[httpx.ConnectError("down"), _response(200, {"works": []})]
    )
    client = AsyncLibraryClient(client=http, max_retries=1, backoff_seconds=0)

    result = await client.get_author_works("/authors/OL26320A/works.json")

    assert result == {"works": []}
    assert http.get.await_count == 2
