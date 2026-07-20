from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd

try:  
    import streamlit as st
except Exception:  
    class _StreamlitFallback:
        def cache_data(self, ttl: int = 600):
            def decorator(func):
                return func

            return decorator

    st = _StreamlitFallback()  


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DB_PATH = PROJECT_ROOT / "db" / "nifty100.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _read_sql(query: str, params: tuple[Any, ...] = ()) -> pd.DataFrame:
    with _connect() as conn:
        return pd.read_sql_query(query, conn, params=params)


@st.cache_data(ttl=600)
def get_companies() -> pd.DataFrame:
    return _read_sql("SELECT * FROM companies;")


@st.cache_data(ttl=600)
def get_ratios(ticker: str, year: int | None = None) -> pd.DataFrame:
    if year is None:
        query = """
            SELECT fr.*
            FROM financial_ratios fr
            JOIN companies c ON c.id = fr.company_id
            WHERE c.ticker = ?
            ORDER BY fr.financial_year ASC;
        """
        return _read_sql(query, (ticker,))
    query = """
        SELECT fr.*
        FROM financial_ratios fr
        JOIN companies c ON c.id = fr.company_id
        WHERE c.ticker = ? AND fr.financial_year = ?
        ORDER BY fr.financial_year ASC;
    """
    return _read_sql(query, (ticker, year))


@st.cache_data(ttl=600)
def get_pl(ticker: str) -> pd.DataFrame:
    query = """
        SELECT p.*
        FROM profitandloss p
        JOIN companies c ON c.id = p.company_id
        WHERE c.ticker = ?
        ORDER BY p.financial_year ASC;
    """
    return _read_sql(query, (ticker,))


@st.cache_data(ttl=600)
def get_bs(ticker: str) -> pd.DataFrame:
    query = """
        SELECT b.*
        FROM balancesheet b
        JOIN companies c ON c.id = b.company_id
        WHERE c.ticker = ?
        ORDER BY b.financial_year ASC;
    """
    return _read_sql(query, (ticker,))


@st.cache_data(ttl=600)
def get_cf(ticker: str) -> pd.DataFrame:
    query = """
        SELECT cf.*
        FROM cashflow cf
        JOIN companies c ON c.id = cf.company_id
        WHERE c.ticker = ?
        ORDER BY cf.financial_year ASC;
    """
    return _read_sql(query, (ticker,))


@st.cache_data(ttl=600)
def get_sectors() -> pd.DataFrame:
    return _read_sql("SELECT * FROM sectors;")


@st.cache_data(ttl=600)
def get_peers(group_name: str) -> pd.DataFrame:
    return _read_sql("SELECT * FROM peer_groups WHERE peer_group_name = ?;", (group_name,))


@st.cache_data(ttl=600)
def get_valuation(ticker: str) -> pd.DataFrame:
    with _connect() as conn:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()
        }
    if "market_cap" not in tables:
        return pd.DataFrame()
    query = """
        SELECT mc.*
        FROM market_cap mc
        JOIN companies c ON c.id = mc.company_id
        WHERE c.ticker = ?
        ORDER BY mc.financial_year ASC;
    """
    return _read_sql(query, (ticker,))


@st.cache_data(ttl=600)
def get_documents(ticker: str) -> pd.DataFrame:
    query = """
        SELECT d.*
        FROM documents d
        JOIN companies c ON c.id = d.company_id
        WHERE c.ticker = ?
        ORDER BY d.document_date DESC;
    """
    return _read_sql(query, (ticker,))


@st.cache_data(ttl=600)
def get_market_cap_lookup() -> pd.DataFrame:
    with _connect() as conn:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()
        }
    if "market_cap" not in tables:
        return pd.DataFrame()
    return _read_sql("SELECT * FROM market_cap;")


@st.cache_data(ttl=600)
def get_reports_years() -> pd.DataFrame:
    query = """
        SELECT DISTINCT financial_year AS year
        FROM financial_ratios
        ORDER BY year DESC;
    """
    return _read_sql(query)


@st.cache_data(ttl=600)
def get_available_years() -> list[int]:
    frames: list[pd.DataFrame] = []
    try:
        frames.append(get_reports_years())
    except Exception:
        frames.append(pd.DataFrame())
    try:
        frames.append(get_valuation("__missing__"))
    except Exception:
        frames.append(pd.DataFrame())

    years: set[int] = set()
    for frame in frames:
        if frame.empty:
            continue
        for column in ("year", "financial_year"):
            if column in frame.columns:
                series = pd.to_numeric(frame[column], errors="coerce").dropna().astype(int)
                years.update(series.tolist())

    if not years:
        with _connect() as conn:
            table_years = pd.read_sql_query(
                """
                SELECT DISTINCT financial_year AS year FROM financial_ratios
                UNION
                SELECT DISTINCT financial_year AS year FROM profitandloss
                UNION
                SELECT DISTINCT financial_year AS year FROM balancesheet
                UNION
                SELECT DISTINCT financial_year AS year FROM cashflow
                ORDER BY year DESC;
                """,
                conn,
            )
        if not table_years.empty and "year" in table_years.columns:
            series = pd.to_numeric(table_years["year"], errors="coerce").dropna().astype(int)
            years.update(series.tolist())

    return sorted(years, reverse=True)
