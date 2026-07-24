from __future__ import annotations

"""API health and compliance endpoints."""

import sqlite3
import time
from pathlib import Path

import pandas as pd

from api._compat import JSONResponse, APIRouter
from api.state import APP_START

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DB_PATH = PROJECT_ROOT / "db" / "nifty100.db"

router = APIRouter()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


@router.get("/health")
def health() -> JSONResponse:
    tables = ["companies", "financial_ratios", "profitandloss", "balancesheet", "cashflow", "sectors", "market_cap", "peer_groups", "prosandcons", "documents"]
    counts: dict[str, int] = {}
    with _connect() as conn:
        for table in tables:
            try:
                counts[table] = int(pd.read_sql_query(f"SELECT COUNT(*) AS count FROM {table};", conn)["count"].iloc[0])
            except Exception:
                counts[table] = 0
    payload = {"uptime_seconds": round(time.time() - APP_START, 3), "table_counts": counts, "database_present": Path(DB_PATH).exists()}
    return JSONResponse(payload)
