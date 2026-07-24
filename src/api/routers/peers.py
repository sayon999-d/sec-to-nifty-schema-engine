from __future__ import annotations

"""Peer comparison endpoints."""

from pathlib import Path

import pandas as pd

from api._compat import HTTPException, JSONResponse, APIRouter
from analytics.peer import build_peer_percentiles
from dashboard.utils.db import get_companies

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DB_PATH = PROJECT_ROOT / "db" / "nifty100.db"

router = APIRouter()


def _peer_frame() -> pd.DataFrame:
    try:
        return build_peer_percentiles(DB_PATH)
    except Exception:
        return pd.DataFrame()


@router.get("/peers/{group_name}")
def peers(group_name: str) -> JSONResponse:
    frame = _peer_frame()
    if frame.empty:
        return JSONResponse([])
    result = frame.loc[frame["peer_group_name"].astype(str).str.casefold().eq(group_name.casefold())]
    if result.empty:
        raise HTTPException(404, f"Peer group not found: {group_name}")
    return JSONResponse(result.fillna("").to_dict(orient="records"))


@router.get("/companies/{ticker}/peers/compare")
def compare_company_peers(ticker: str) -> JSONResponse:
    companies = get_companies()
    match = companies.loc[companies["ticker"].astype(str).str.upper().eq(ticker.upper())]
    if match.empty:
        raise HTTPException(404, f"Ticker not found: {ticker}")
    company_id = int(match.iloc[0]["id"])
    peer_frame = _peer_frame()
    if peer_frame.empty:
        return JSONResponse({"company_id": company_id, "vectors": []})
    group_name = None
    if "company_id" in peer_frame.columns:
        subset = peer_frame.loc[peer_frame["company_id"].astype(int).eq(company_id)]
        if not subset.empty:
            group_name = str(subset.iloc[0]["peer_group_name"])
    if not group_name:
        raise HTTPException(404, f"Peer group not found for {ticker}")
    group = peer_frame.loc[peer_frame["peer_group_name"].astype(str).eq(group_name)].copy()
    vectors = []
    for metric in sorted(group["metric"].dropna().astype(str).unique()):
        slice_ = group.loc[group["metric"].astype(str).eq(metric)]
        company_row = slice_.loc[slice_["company_id"].astype(int).eq(company_id)]
        if company_row.empty:
            continue
        vectors.append(
            {
                "metric": metric,
                "value": None if pd.isna(company_row.iloc[0]["value"]) else float(company_row.iloc[0]["value"]),
                "percentile_rank": None if pd.isna(company_row.iloc[0]["percentile_rank"]) else float(company_row.iloc[0]["percentile_rank"]),
            }
        )
    return JSONResponse({"company_id": company_id, "peer_group_name": group_name, "vectors": vectors})

