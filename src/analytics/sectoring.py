from __future__ import annotations

from typing import Any

_GROUP_ORDER = [
    "Financials",
    "IT Services",
    "Industrials",
    "Consumer Discretionary",
    "Consumer Staples",
    "Energy",
    "Utilities",
    "Healthcare",
    "Materials",
    "Communications",
    "Real Estate",
]


def _sic_code(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return None
    try:
        return int(digits[:2])
    except Exception:
        return None


def broad_sector_from_row(sector_name: Any, industry_name: Any = None, sub_industry_name: Any = None) -> str:
    code = _sic_code(sector_name)
    if code is None:
        return "Unknown"
    if 60 <= code <= 67:
        return "Financials"
    if code in {36, 73}:
        return "IT Services"
    if code in {41, 48}:
        return "Communications"
    if code in {49}:
        return "Utilities"
    if code in {13, 14, 29}:
        return "Energy"
    if code in {80, 81, 82, 83, 84, 85, 86, 87}:
        return "Healthcare"
    if code in {10, 11, 12, 15, 16, 17, 26, 27, 28, 30, 31, 32, 33}:
        return "Materials"
    if code in {20, 21, 22, 23, 24, 25}:
        return "Consumer Staples"
    if code in {34, 35, 36, 37, 38, 39, 40, 44, 45, 46, 47, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59}:
        return "Consumer Discretionary"
    if code in {70, 71, 72, 74, 75, 76, 78, 79}:
        return "Industrials"
    if code in {61, 62, 63, 64, 65, 66}:
        return "Financials"
    if code in {67, 68, 69}:
        return "Real Estate"
    idx = code % (len(_GROUP_ORDER) - 1)
    return _GROUP_ORDER[1 + idx]


def peer_group_from_row(sector_name: Any, industry_name: Any = None, sub_industry_name: Any = None) -> str:
    return broad_sector_from_row(sector_name, industry_name, sub_industry_name)


def all_peer_groups() -> list[str]:
    return list(_GROUP_ORDER)
