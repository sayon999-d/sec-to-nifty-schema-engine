from __future__ import annotations

"""Sector analytics endpoints."""

from pathlib import Path

import pandas as pd

from api._compat import HTTPException, JSONResponse, APIRouter
from dashboard.utils.db import get_sectors

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DB_PATH = PROJECT_ROOT / "db" / "nifty100.db"

router = APIRouter()


def _sector_frame() -> pd.DataFrame:
    sectors = get_sectors().copy()
    if sectors.empty:
        return sectors
    return sectors


@router.get("/sectors")
def sectors() -> JSONResponse:
    frame = _sector_frame()
    if frame.empty:
        return JSONResponse([])
    return JSONResponse(frame.fillna("").to_dict(orient="records"))


@router.get("/sectors/{sector}/companies")
def sector_companies(sector: str) -> JSONResponse:
    frame = _sector_frame()
    if frame.empty:
        raise HTTPException(404, f"Sector not found: {sector}")
    mask = frame.astype(str).apply(lambda col: col.str.contains(sector, case=False, na=False))
    result = frame.loc[mask.any(axis=1)].copy()
    if result.empty:
        raise HTTPException(404, f"Sector not found: {sector}")
    return JSONResponse(result.fillna("").to_dict(orient="records"))

