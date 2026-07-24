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
    "table",
    ["companies", "financial_ratios", "profitandloss", "balancesheet", "cashflow", "sectors", "market_cap", "peer_groups", "prosandcons", "documents"],
)
def test_table_exists_and_has_rows(table):
    with _connect() as conn:
        row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name = ?;", (table,)).fetchone()
        assert row is not None
        count = conn.execute(f"SELECT COUNT(*) FROM {table};").fetchone()[0]
        assert count >= 0


@pytest.mark.parametrize(
    "table, minimum",
    [("companies", 92), ("financial_ratios", 100), ("profitandloss", 100), ("balancesheet", 100), ("cashflow", 100)],
)
def test_row_count_thresholds(table, minimum):
    with _connect() as conn:
        count = conn.execute(f"SELECT COUNT(*) FROM {table};").fetchone()[0]
        assert count >= minimum


@pytest.mark.parametrize("column", ["company_id", "financial_year"])
def test_financial_ratios_required_columns(column):
    with _connect() as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(financial_ratios);").fetchall()}
        assert column in columns


@pytest.mark.parametrize("table", ["financial_ratios", "profitandloss", "balancesheet", "cashflow"])
def test_tables_have_company_and_year_keys(table):
    with _connect() as conn:
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table});").fetchall()}
        assert "company_id" in columns
        assert "financial_year" in columns

