# src/processing/cleaner.py
# This file contains the cleaner for the library.
import re
import unicodedata

_ISBN13_RE = re.compile(r"(?<!\d)97[89](?:[-\s]?\d){10}(?!\d)")
_ISBN10_RE = re.compile(
    r"(?<!\d)\d(?:[-\s]?\d){8}[-\s]?[\dXx](?!\d)",
    re.IGNORECASE,
)
_SEPARATOR_RE = re.compile(r"[^0-9Xx]")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_text(value: str) -> str:
    """Normalize a string to one trimmed line of comparable text."""
    text = unicodedata.normalize("NFKC", value)
    text = _WHITESPACE_RE.sub(" ", text)
    text = _CONTROL_RE.sub("", text)
    return text.strip()


def extract_isbns(text: str) -> list[str]:
    """Return the unique valid ISBNs found in text, without separators."""
    normalized = unicodedata.normalize("NFKC", text)
    found: list[str] = []
    occupied: list[tuple[int, int]] = []
    for pattern in (_ISBN13_RE, _ISBN10_RE):
        for match in pattern.finditer(normalized):
            if _overlaps(match.span(), occupied):
                continue
            isbn = _SEPARATOR_RE.sub("", match.group()).upper()
            if not _checksum_ok(isbn):
                continue
            if isbn not in found:
                found.append(isbn)
            occupied.append(match.span())
    return found


def is_valid_isbn(value: str) -> bool:
    """Return whether the value is an ISBN-10 or ISBN-13 with a valid checksum."""
    isbn = _SEPARATOR_RE.sub("", normalize_text(value)).upper()
    return _checksum_ok(isbn)


def _checksum_ok(isbn: str) -> bool:
    """Return whether the ISBN is valid."""
    if len(isbn) == 10:
        return _isbn10_ok(isbn)
    if len(isbn) == 13 and isbn.isdigit():
        return _isbn13_ok(isbn)
    return False


def _isbn10_ok(isbn: str) -> bool:
    """Return whether the ISBN-10 is valid."""
    total = 0
    for index, character in enumerate(isbn):
        if character == "X":
            if index != 9:
                return False
            value = 10
        elif character.isdigit():
            value = int(character)
        else:
            return False
        total += value * (10 - index)
    return total % 11 == 0


def _isbn13_ok(isbn: str) -> bool:
    """Return whether the ISBN-13 is valid."""
    total = sum(
        int(digit) * (1 if index % 2 == 0 else 3) for index, digit in enumerate(isbn)
    )
    return total % 10 == 0


def _overlaps(span: tuple[int, int], occupied: list[tuple[int, int]]) -> bool:
    """Return whether the span overlaps with any of the occupied spans."""
    start, end = span
    return any(
        start < other_end and other_start < end for other_start, other_end in occupied
    )
