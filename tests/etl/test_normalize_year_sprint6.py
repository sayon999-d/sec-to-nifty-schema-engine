from __future__ import annotations

import datetime as dt
from pathlib import Path
import sys

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from etl.normaliser import normalize_year


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("FY24", 2024),
        ("FY 24", 2024),
        ("FY24-25", 2025),
        ("2024", 2024),
        ("2024-03-31", 2024),
        ("31/03/2024", 2024),
        ("31 Mar 2024", 2024),
        ("March 31, 2024", 2024),
        ("2024/25", 2025),
        ("24-25", 2025),
        (dt.date(2024, 3, 31), 2024),
        (dt.datetime(2023, 12, 31), 2023),
        (pd.Timestamp("2022-03-31"), 2022),
        (2021, 2021),
        (21, 2021),
        ("00", 2000),
        ("99", 2099),
        ("FY25", 2025),
        ("fy26", 2026),
        (" 2020 ", 2020),
    ],
)
def test_normalize_year_valid_cases(raw, expected):
    assert normalize_year(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "   ", True, False])
def test_normalize_year_invalid_cases(raw):
    with pytest.raises((ValueError, TypeError)):
        normalize_year(raw)

