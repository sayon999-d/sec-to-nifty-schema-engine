from __future__ import annotations

import datetime as _dt
import re
from typing import Any

import pandas as pd

_FY_PATTERN = re.compile(
    r"(?i)\bFY\s*[-/]?\s*(?P<year>\d{2,4})(?:\s*[-/]\s*(?P<end>\d{2,4}))?\b"
)
_YEAR_RANGE_PATTERN = re.compile(r"\b(?P<start>\d{2,4})\s*[-/]\s*(?P<end>\d{2,4})\b")
_YEAR_TOKEN_PATTERN = re.compile(r"\b(19\d{2}|20\d{2})\b")
_TICKER_PREFIX_PATTERNS = (
    re.compile(r"(?i)^\s*(?:NSE|BSE)\s*[:._-]\s*"),
    re.compile(r"(?i)^\s*(?:NSE|BSE)\s+"),
)
_TICKER_SUFFIX_PATTERNS = (
    r"[\s._:-]*(?:NSE|BSE|NS|BO|EQ|BE|BZ)$",
    r"[\s._:-]*INDEX$",
    r"[\s._:-]*PRICE$",
)


def _two_digit_to_year(value: int) -> int:
    """Map a two-digit year token to a 2000-based calendar year."""

    return 2000 + value


def _parse_year_token(value: str) -> int:
    """Parse a year token expressed as two or four digits."""

    if len(value) == 4:
        return int(value)
    if len(value) == 2:
        return _two_digit_to_year(int(value))
    raise ValueError(f"Unsupported year token: {value}")


def normalize_year(raw_year: Any) -> int:
    """Normalize date-like, fiscal-year, and year tokens to a four-digit year."""

    if raw_year is None:
        raise ValueError("year value cannot be None")

    if isinstance(raw_year, bool):
        raise ValueError("boolean values are not valid years")

    if isinstance(raw_year, int):
        if 1900 <= raw_year <= 2100:
            return raw_year
        if 0 <= raw_year <= 99:
            return _two_digit_to_year(raw_year)
        raise ValueError(f"year integer out of range: {raw_year}")

    if isinstance(raw_year, float) and raw_year.is_integer():
        return normalize_year(int(raw_year))

    if isinstance(raw_year, (_dt.datetime, _dt.date, pd.Timestamp)):
        return int(raw_year.year)

    text = str(raw_year).strip()
    if not text:
        raise ValueError("year value cannot be empty")

    if text.isdigit():
        value = int(text)
        return normalize_year(value)

    fy_match = _FY_PATTERN.search(text)
    if fy_match:
        end = fy_match.group("end") or fy_match.group("year")
        return _parse_year_token(end)

    range_match = _YEAR_RANGE_PATTERN.fullmatch(text)
    if range_match:
        end = range_match.group("end")
        return _parse_year_token(end)

    year_token_match = _YEAR_TOKEN_PATTERN.search(text)
    if year_token_match:
        return int(year_token_match.group(1))

    try:
        parsed = pd.to_datetime(text, errors="raise", dayfirst=True)
        return int(parsed.year)
    except Exception:
        pass

    try:
        parsed = pd.to_datetime(text, errors="raise", dayfirst=False)
        return int(parsed.year)
    except Exception as exc:
        raise ValueError(f"unable to normalize year: {raw_year!r}") from exc


def normalize_ticker(raw_ticker: Any) -> str:
    """Normalize raw ticker strings into canonical uppercase alphanumeric symbols."""

    if raw_ticker is None:
        raise ValueError("ticker value cannot be None")

    text = str(raw_ticker).strip().upper()
    if not text:
        raise ValueError("ticker value cannot be empty")

    for pattern in _TICKER_PREFIX_PATTERNS:
        text = pattern.sub("", text)

    for pattern in _TICKER_SUFFIX_PATTERNS:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)

    text = re.sub(r"[^A-Z0-9]", "", text)
    if not text:
        raise ValueError(f"unable to normalize ticker: {raw_ticker!r}")
    return text
