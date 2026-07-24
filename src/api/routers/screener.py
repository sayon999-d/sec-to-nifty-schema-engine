from __future__ import annotations

"""Screener endpoints."""

import sqlite3
from pathlib import Path

import pandas as pd

from api._compat import HTTPException, JSONResponse, APIRouter
from screener.engine import ScreenerEngine

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DB_PATH = PROJECT_ROOT / "db" / "nifty100.db"

router = APIRouter()


def _load_latest() -> pd.DataFrame:
    engine = ScreenerEngine(db_path=DB_PATH)
    frame = engine.load_frame()
    if frame.empty:
        return frame
    return frame.sort_values(["company_id", "year"]).groupby("company_id", as_index=False).tail(1).reset_index(drop=True)


@router.get("/screener")
def screener(min_roe: float | None = None, max_de: float | None = None, min_fcf: float | None = None, sector: str | None = None, max_pe: float | None = None) -> JSONResponse:
    """Apply a general-purpose financial filter matrix."""

    frame = _load_latest()
    if frame.empty:
        return JSONResponse([])
    for value, name in [(min_roe, "min_roe"), (max_de, "max_de"), (min_fcf, "min_fcf"), (max_pe, "max_pe")]:
        if value is not None and not isinstance(value, (int, float)):
            raise HTTPException(400, f"Invalid value for {name}")
    if sector:
        frame = frame.loc[frame["broad_sector"].astype(str).str.contains(sector, case=False, na=False)]
    if min_roe is not None:
        frame = frame.loc[pd.to_numeric(frame["return_on_equity_pct"], errors="coerce") >= float(min_roe)]
    if max_de is not None:
        de = pd.to_numeric(frame["debt_to_equity"], errors="coerce")
        frame = frame.loc[de.isna() | (de <= float(max_de)) | frame["broad_sector"].astype(str).eq("Financials")]
    if min_fcf is not None:
        frame = frame.loc[pd.to_numeric(frame["free_cash_flow_cr"], errors="coerce").fillna(float("-inf")) >= float(min_fcf)]
    if max_pe is not None and "pe_ratio" in frame.columns:
        frame = frame.loc[pd.to_numeric(frame["pe_ratio"], errors="coerce").isna() | (pd.to_numeric(frame["pe_ratio"], errors="coerce") <= float(max_pe))]
    return JSONResponse(frame.fillna("").to_dict(orient="records"))

