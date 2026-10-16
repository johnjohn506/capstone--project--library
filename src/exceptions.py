# src/exceptions.py
# This file contains the custom exceptions for the library.

# Base class for errors raised by this application.
class LibraryError(Exception):
    """Base class for errors raised by this application."""

# An Open Library request failed.
class APIError(LibraryError):
    """An Open Library request failed."""

    # Initialize the APIError.
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        url: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.url = url
        super().__init__(message)

# The requested work or author does not exist.
class ResourceNotFoundError(APIError):
    """The requested work or author does not exist."""

# User input or an API payload failed validation.
class DataValidationError(LibraryError):
    """User input or an API payload failed validation."""

# A specific field failed validation.
    def __init__(self, message: str, *, field: str | None = None) -> None:
        self.field = field
        super().__init__(message)
