from __future__ import annotations

"""Corporate and historical API endpoints."""

import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd

from api._compat import FileResponse, HTTPException, JSONResponse, APIRouter
from dashboard.utils.db import get_companies, get_ratios

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DB_PATH = PROJECT_ROOT / "db" / "nifty100.db"
REPORT_DIR = PROJECT_ROOT / "reports" / "tearsheets"

router = APIRouter()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _company_id(ticker: str) -> int:
    companies = get_companies()
    match = companies.loc[companies["ticker"].astype(str).str.upper().eq(str(ticker).upper())]
    if match.empty:
        raise HTTPException(404, f"Ticker not found: {ticker}")
    return int(match.iloc[0]["id"])


def _table_for_ticker(table: str, ticker: str, from_year: int | None = None, to_year: int | None = None) -> pd.DataFrame:
    company_id = _company_id(ticker)
    query = f"SELECT * FROM {table} WHERE company_id = ?"
    params: list[Any] = [company_id]
    if from_year is not None:
        query += " AND financial_year >= ?"
        params.append(int(from_year))
    if to_year is not None:
        query += " AND financial_year <= ?"
        params.append(int(to_year))
    query += " ORDER BY financial_year ASC;"
    with _connect() as conn:
        return pd.read_sql_query(query, conn, params=tuple(params))


@router.get("/companies")
def list_companies(sector: str | None = None, market_cap_category: str | None = None, search: str | None = None) -> JSONResponse:
    """Return a filtered company summary dataset."""

    frame = get_companies().copy()
    if frame.empty:
        return JSONResponse([])
    if sector and "sector" in frame.columns:
        frame = frame.loc[frame["sector"].astype(str).str.contains(sector, case=False, na=False)]
    if market_cap_category and "market_cap_category" in frame.columns:
        frame = frame.loc[frame["market_cap_category"].astype(str).str.contains(market_cap_category, case=False, na=False)]
    if search:
        pattern = str(search).replace("*", ".*")
        cols = [col for col in ["company_name", "ticker"] if col in frame.columns]
        if cols:
            mask = pd.Series(False, index=frame.index)
            for col in cols:
                mask |= frame[col].astype(str).str.contains(pattern, case=False, na=False, regex=True)
            frame = frame.loc[mask]
    return JSONResponse(frame.fillna("").to_dict(orient="records"))


@router.get("/companies/{ticker}")
def get_company_profile(ticker: str) -> JSONResponse:
    """Return a comprehensive operational company profile."""

    company_id = _company_id(ticker)
    companies = get_companies()
    profile = companies.loc[companies["id"].astype(int).eq(company_id)]
    if profile.empty:
        raise HTTPException(404, f"Ticker not found: {ticker}")
    row = profile.iloc[0].to_dict()
    ratios = get_ratios(ticker)
    row["ratios"] = ratios.fillna("").to_dict(orient="records")
    for table, key in [("profitandloss", "pl"), ("balancesheet", "bs"), ("cashflow", "cashflow")]:
        row[key] = _table_for_ticker(table, ticker).fillna("").to_dict(orient="records")
    return JSONResponse(row)


@router.get("/companies/{ticker}/pl")
def get_pl(ticker: str, from_year: int | None = None, to_year: int | None = None) -> JSONResponse:
    return JSONResponse(_table_for_ticker("profitandloss", ticker, from_year, to_year).fillna("").to_dict(orient="records"))


@router.get("/companies/{ticker}/bs")
def get_bs(ticker: str, from_year: int | None = None, to_year: int | None = None) -> JSONResponse:
    return JSONResponse(_table_for_ticker("balancesheet", ticker, from_year, to_year).fillna("").to_dict(orient="records"))


@router.get("/companies/{ticker}/cashflow")
def get_cashflow(ticker: str, from_year: int | None = None, to_year: int | None = None) -> JSONResponse:
    return JSONResponse(_table_for_ticker("cashflow", ticker, from_year, to_year).fillna("").to_dict(orient="records"))


@router.get("/companies/{ticker}/ratios")
def get_company_ratios(ticker: str, from_year: int | None = None, to_year: int | None = None) -> JSONResponse:
    frame = get_ratios(ticker)
    if frame.empty:
        return JSONResponse([])
    if from_year is not None:
        frame = frame.loc[pd.to_numeric(frame["financial_year"], errors="coerce") >= int(from_year)]
    if to_year is not None:
        frame = frame.loc[pd.to_numeric(frame["financial_year"], errors="coerce") <= int(to_year)]
    return JSONResponse(frame.fillna("").to_dict(orient="records"))


@router.get("/companies/{ticker}/tearsheet")
def get_tearsheet(ticker: str) -> FileResponse:
    """Stream the precompiled tearsheet PDF."""

    company = get_companies().loc[get_companies()["ticker"].astype(str).str.upper().eq(ticker.upper())]
    if company.empty:
        raise HTTPException(404, f"Ticker not found: {ticker}")
    path = REPORT_DIR / f"{ticker}_tearsheet.pdf"
    if not path.exists():
        raise HTTPException(404, f"Tearsheet not found for {ticker}")
    return FileResponse(str(path), media_type="application/pdf", filename=path.name)

