# src/exceptions.py
# This file contains the custom exceptions for the library.


class LibraryError(Exception):
    """Base class for errors raised by this application."""


class APIError(LibraryError):
    """An Open Library request failed."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        url: str | None = None,
    ) -> None:
        """Initialize the APIError."""
        self.status_code = status_code
        self.url = url
        super().__init__(message)


class ResourceNotFoundError(APIError):
    """The requested work or author does not exist."""


class DataValidationError(LibraryError):
    """User input or an API payload failed validation."""

    def __init__(self, message: str, *, field: str | None = None) -> None:
        """Initialize the DataValidationError."""
        self.field = field
        super().__init__(message)
