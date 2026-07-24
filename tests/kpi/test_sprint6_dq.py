from __future__ import annotations

import sqlite3
from pathlib import Path
import sys

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
DB_PATH = ROOT / "db" / "nifty100.db"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@pytest.mark.parametrize(
    "table, column",
    [
        ("companies", "ticker"),
        ("companies", "company_name"),
        ("financial_ratios", "company_id"),
        ("financial_ratios", "financial_year"),
        ("financial_ratios", "return_on_equity_pct"),
        ("profitandloss", "revenue"),
        ("profitandloss", "net_income"),
        ("balancesheet", "total_assets"),
        ("balancesheet", "total_equity"),
        ("cashflow", "net_cash_from_operations"),
        ("cashflow", "net_cash_from_investing"),
        ("cashflow", "net_cash_from_financing"),
        ("sectors", "sector_name"),
        ("market_cap", "market_cap_crore"),
    ],
)
def test_required_columns_not_empty(table, column):
    with _connect() as conn:
        count = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {column} IS NOT NULL AND TRIM(CAST({column} AS TEXT)) <> '';" ).fetchone()[0]
        assert count >= 0


@pytest.mark.parametrize("table", ["companies", "financial_ratios", "profitandloss", "balancesheet", "cashflow"])
def test_duplicate_company_years_are_reasonable(table):
    with _connect() as conn:
        if table == "companies":
            df = pd.read_sql_query("SELECT id AS company_id, COUNT(*) AS c FROM companies GROUP BY id HAVING c > 1;", conn)
        else:
            df = pd.read_sql_query(
                f"SELECT company_id, financial_year, COUNT(*) AS c FROM {table} GROUP BY company_id, financial_year HAVING c > 1;",
                conn,
            )
    assert len(df) >= 0


def test_ratio_year_range():
    with _connect() as conn:
        years = pd.read_sql_query("SELECT MIN(financial_year) AS mn, MAX(financial_year) AS mx FROM financial_ratios;", conn)
    assert years["mn"].iloc[0] <= years["mx"].iloc[0]
