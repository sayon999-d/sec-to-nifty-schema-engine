from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from etl.normaliser import normalize_ticker, normalize_year


@pytest.mark.parametrize(
    "raw_year, expected",
    [
        ("31-03-2025", 2025),
        ("2025", 2025),
        ("FY25", 2025),
        ("FY 25", 2025),
        ("FY2025", 2025),
        ("fy25", 2025),
        ("31/03/2025", 2025),
        ("2025-03-31", 2025),
        (dt.date(2025, 3, 31), 2025),
        (dt.datetime(2024, 12, 31, 23, 59), 2024),
        (pd.Timestamp("2023-03-31"), 2023),
        (2022, 2022),
        (" 2021 ", 2021),
        ("FY24-25", 2025),
        ("2024/25", 2025),
        ("31 Mar 2020", 2020),
        ("March 31, 2019", 2019),
        ("2000", 2000),
        ("00", 2000),
        ("99", 2099),
    ],
)
def test_normalize_year_valid_cases(raw_year, expected):
    assert normalize_year(raw_year) == expected


@pytest.mark.parametrize(
    "raw_year",
    [
        "",
        "   ",
        None,
    ],
)
def test_normalize_year_invalid_cases(raw_year):
    with pytest.raises((ValueError, TypeError)):
        normalize_year(raw_year)


@pytest.mark.parametrize(
    "raw_ticker, expected",
    [
        ("reliance.ns", "RELIANCE"),
        ("SBIN.NS", "SBIN"),
        ("TCS-EQ", "TCS"),
        ("M&M.BO", "MM"),
        ("  hdfc bank  ", "HDFCBANK"),
        ("BAJAJ-AUTO.BSE", "BAJAJAUTO"),
        ("Maruti Suzuki Ltd.", "MARUTISUZUKILTD"),
        ("ICICI_BANK", "ICICIBANK"),
        ("L&T:NSE", "LT"),
        ("  yes bank  ", "YESBANK"),
        ("reliance industries limited", "RELIANCEINDUSTRIESLIMITED"),
        ("HCL-TECH", "HCLTECH"),
        ("A&B-C", "ABC"),
        ("NIFTY 100 INDEX", "NIFTY100"),
        ("^NSEI", "NSEI"),
    ],
)
def test_normalize_ticker_edge_cases(raw_ticker, expected):
    assert normalize_ticker(raw_ticker) == expected


@pytest.mark.parametrize(
    "raw_ticker",
    [
        "",
        "   ",
        None,
        "!!!",
    ],
)
def test_normalize_ticker_invalid_cases(raw_ticker):
    with pytest.raises((ValueError, TypeError)):
        normalize_ticker(raw_ticker)
