from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

APP_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
DB_PATH = APP_ROOT / "db" / "nifty100.db"
OUTPUT_DIR = APP_ROOT / "output"
MARKET_CAP_XLSX = OUTPUT_DIR / "market_cap.xlsx"
SECTORS_XLSX = OUTPUT_DIR / "sectors.xlsx"

LOGGER = logging.getLogger(__name__)
if not LOGGER.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s - %(message)s"))
    LOGGER.addHandler(handler)
LOGGER.setLevel(logging.INFO)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _safe_read_excel(path: Path) -> pd.DataFrame:
    candidates = [
        path,
        OUTPUT_DIR / path.name,
        Path.cwd() / path.name,
        APP_ROOT / path.name,
        WORKSPACE_ROOT / path.name,
    ]
    resolved = next((candidate for candidate in candidates if candidate.exists()), None)
    if resolved is None:
        return pd.DataFrame()
    try:
        return pd.read_excel(resolved)
    except Exception as exc:  # pragma: no cover - defensive I/O
        LOGGER.warning("Failed to read %s: %s", resolved, exc)
        return pd.DataFrame()


def _write_excel(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        frame.to_excel(path, index=False)
    except Exception as exc:  # pragma: no cover - defensive I/O
        LOGGER.warning("Failed to write %s: %s", path, exc)


def _ensure_reference_excels() -> None:
    sectors_path = SECTORS_XLSX
    if not sectors_path.exists():
        sectors_frame = _sector_lookup()
        if not sectors_frame.empty:
            _write_excel(sectors_path, sectors_frame)


def _company_universe() -> pd.DataFrame:
    with _connect() as conn:
        return pd.read_sql_query(
            "SELECT id AS company_id, company_name, ticker FROM companies ORDER BY id;",
            conn,
        )


def _sector_lookup() -> pd.DataFrame:
    df = _safe_read_excel(SECTORS_XLSX)
    if not df.empty:
        cols = {str(col).strip().lower(): col for col in df.columns}
        if "company_id" in cols and "sector_name" in cols:
            mapped = df.rename(
                columns={
                    cols["company_id"]: "company_id",
                    cols["sector_name"]: "sector",
                }
            )
            if "broad_sector" in cols:
                mapped = mapped.rename(columns={cols["broad_sector"]: "broad_sector"})
            elif "sector" in mapped.columns:
                mapped["broad_sector"] = mapped["sector"]
            return mapped[[c for c in ["company_id", "sector", "broad_sector"] if c in mapped.columns]].copy()

    with _connect() as conn:
        df = pd.read_sql_query(
            """
            SELECT s.company_id, s.sector_name AS sector, s.industry_name, s.sub_industry_name
            FROM sectors s
            ORDER BY s.company_id;
            """,
            conn,
        )
    df["broad_sector"] = df["sector"].fillna("Unknown")
    return df


def _market_cap_lookup() -> pd.DataFrame:
    with _connect() as conn:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()
        }
    if "market_cap" in tables:
        with _connect() as conn:
            table_df = pd.read_sql_query("SELECT * FROM market_cap ORDER BY company_id, financial_year;", conn)
        if not table_df.empty:
            return table_df

    df = _safe_read_excel(MARKET_CAP_XLSX)
    if not df.empty:
        cols = {str(col).strip().lower(): col for col in df.columns}
        rename_map: dict[str, str] = {}
        for expected in ["company_id", "financial_year", "market_cap_crore", "pe_ratio", "pb_ratio", "ev_ebitda"]:
            if expected in cols:
                rename_map[cols[expected]] = expected
        if rename_map:
            df = df.rename(columns=rename_map)
        return df

    LOGGER.info("market_cap source unavailable; valuation will build it from warehouse data")
    return pd.DataFrame()


def _latest_stock_prices() -> pd.DataFrame:
    with _connect() as conn:
        return pd.read_sql_query(
            """
            WITH ranked AS (
                SELECT
                    sp.company_id,
                    sp.trade_date,
                    sp.close_price,
                    ROW_NUMBER() OVER (
                        PARTITION BY sp.company_id
                        ORDER BY sp.trade_date DESC
                    ) AS rn
                FROM stock_prices sp
                WHERE sp.close_price IS NOT NULL
            )
            SELECT company_id, trade_date, close_price
            FROM ranked
            WHERE rn = 1
            ORDER BY company_id;
            """,
            conn,
        )


def _latest_equity_and_eps() -> pd.DataFrame:
    with _connect() as conn:
        return pd.read_sql_query(
            """
            WITH latest AS (
                SELECT company_id, MAX(financial_year) AS financial_year
                FROM financial_ratios
                WHERE financial_year <= 2024
                GROUP BY company_id
            )
            SELECT
                fr.company_id,
                fr.financial_year,
                fr.earnings_per_share,
                fr.book_value_per_share,
                fr.free_cash_flow_cr,
                fr.dividend_payout_ratio_pct,
                fr.composite_quality_score,
                p.net_income,
                p.operating_profit,
                b.total_equity
            FROM financial_ratios fr
            JOIN latest l
              ON l.company_id = fr.company_id
             AND l.financial_year = fr.financial_year
            LEFT JOIN profitandloss p
              ON p.company_id = fr.company_id
             AND p.financial_year = fr.financial_year
            LEFT JOIN balancesheet b
              ON b.company_id = fr.company_id
             AND b.financial_year = fr.financial_year
            ORDER BY fr.company_id;
            """,
            conn,
        )


def _ensure_market_cap_table() -> pd.DataFrame:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS market_cap (
                company_id INTEGER NOT NULL,
                financial_year INTEGER NOT NULL,
                market_cap_crore REAL,
                pe_ratio REAL,
                pb_ratio REAL,
                ev_ebitda REAL,
                trade_date TEXT,
                source_ref TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (company_id, financial_year),
                FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
            );
            """
        )
        existing = pd.read_sql_query("SELECT company_id, financial_year FROM market_cap ORDER BY company_id, financial_year;", conn)
        if not existing.empty and len(existing) >= 92:
            return pd.read_sql_query("SELECT * FROM market_cap ORDER BY company_id, financial_year;", conn)

    companies = _company_universe()
    if companies.empty:
        return pd.DataFrame()

    prices = _latest_stock_prices()
    fundamentals = _latest_equity_and_eps()

    merged = companies.merge(prices, on="company_id", how="left").merge(fundamentals, on="company_id", how="left")
    merged["financial_year"] = 2024
    merged["trade_date"] = merged.get("trade_date", pd.Series(dtype=str))
    merged["close_price"] = _safe_numeric(merged.get("close_price", pd.Series(dtype=float)))
    merged["earnings_per_share"] = _safe_numeric(merged.get("earnings_per_share", pd.Series(dtype=float)))
    merged["book_value_per_share"] = _safe_numeric(merged.get("book_value_per_share", pd.Series(dtype=float)))
    merged["net_income"] = _safe_numeric(merged.get("net_income", pd.Series(dtype=float)))
    merged["total_equity"] = _safe_numeric(merged.get("total_equity", pd.Series(dtype=float)))
    merged["operating_profit"] = _safe_numeric(merged.get("operating_profit", pd.Series(dtype=float)))

    shares_outstanding = np.where(
        merged["earnings_per_share"].fillna(0) != 0,
        merged["net_income"].abs() / merged["earnings_per_share"].abs(),
        np.where(
            merged["book_value_per_share"].fillna(0) != 0,
            merged["total_equity"].abs() / merged["book_value_per_share"].abs(),
            np.nan,
        ),
    )
    merged["shares_outstanding_proxy"] = shares_outstanding
    merged["market_cap_crore"] = np.where(
        merged["close_price"].fillna(0) > 0,
        (merged["close_price"] * merged["shares_outstanding_proxy"]) / 1e7,
        np.nan,
    )
    merged["pe_ratio"] = np.where(
        merged["earnings_per_share"].fillna(0) != 0,
        merged["close_price"] / merged["earnings_per_share"].abs(),
        np.nan,
    )
    merged["pb_ratio"] = np.where(
        merged["total_equity"].fillna(0) != 0,
        merged["market_cap_crore"] / merged["total_equity"].abs(),
        np.nan,
    )
    merged["ev_ebitda"] = np.where(
        merged["operating_profit"].fillna(0) != 0,
        merged["market_cap_crore"] / merged["operating_profit"].abs(),
        np.nan,
    )
    merged["source_ref"] = "derived_from_stock_prices_and_ratios"

    payload = merged[
        [
            "company_id",
            "financial_year",
            "market_cap_crore",
            "pe_ratio",
            "pb_ratio",
            "ev_ebitda",
            "trade_date",
            "source_ref",
        ]
    ].copy()

    with _connect() as conn:
        conn.execute("DELETE FROM market_cap;")
        payload.to_sql("market_cap", conn, if_exists="append", index=False)
        conn.commit()
        return pd.read_sql_query("SELECT * FROM market_cap ORDER BY company_id, financial_year;", conn)


def _export_market_cap_workbook(market_cap: pd.DataFrame) -> None:
    if market_cap.empty:
        return
    company_meta = _company_universe()
    sectors = _sector_lookup()[["company_id", "sector", "broad_sector"]]
    latest_ratios = _latest_equity_and_eps()[["company_id", "financial_year", "free_cash_flow_cr", "composite_quality_score"]]

    export = market_cap.merge(company_meta, on="company_id", how="left")
    export = export.merge(sectors, on="company_id", how="left")
    export = export.merge(latest_ratios, on=["company_id", "financial_year"], how="left")
    export["fcf_yield_pct"] = np.where(
        _safe_numeric(export["market_cap_crore"]).fillna(0) != 0,
        (_safe_numeric(export["free_cash_flow_cr"]).fillna(0) / _safe_numeric(export["market_cap_crore"])) * 100.0,
        np.nan,
    )
    export = export[
        [
            "company_id",
            "company_name",
            "ticker",
            "financial_year",
            "sector",
            "broad_sector",
            "market_cap_crore",
            "pe_ratio",
            "pb_ratio",
            "ev_ebitda",
            "free_cash_flow_cr",
            "fcf_yield_pct",
            "source_ref",
        ]
    ].copy()
    _write_excel(MARKET_CAP_XLSX, export.sort_values(["company_id", "financial_year"]))


def _financial_ratios_2024() -> pd.DataFrame:
    with _connect() as conn:
        return pd.read_sql_query(
            """
            SELECT
                fr.company_id,
                fr.financial_year,
                fr.free_cash_flow_cr,
                fr.composite_quality_score,
                fr.return_on_equity_pct,
                fr.return_on_capital_employed_pct,
                fr.net_profit_margin_pct,
                fr.debt_to_equity,
                fr.interest_coverage,
                fr.earnings_per_share,
                fr.book_value_per_share,
                fr.dividend_payout_ratio_pct,
                fr.cash_from_operations_cr,
                fr.total_debt_cr,
                p.revenue,
                p.net_income,
                p.operating_profit,
                b.total_assets,
                b.total_equity,
                s.sector_name
            FROM financial_ratios fr
            LEFT JOIN profitandloss p
              ON p.company_id = fr.company_id
             AND p.financial_year = fr.financial_year
            LEFT JOIN balancesheet b
              ON b.company_id = fr.company_id
             AND b.financial_year = fr.financial_year
            LEFT JOIN sectors s
              ON s.company_id = fr.company_id
            WHERE fr.financial_year = 2024
            ORDER BY fr.company_id;
            """,
            conn,
        )


def _latest_ratio_history() -> pd.DataFrame:
    with _connect() as conn:
        return pd.read_sql_query(
            """
            SELECT
                fr.company_id,
                fr.financial_year,
                fr.free_cash_flow_cr,
                fr.earnings_per_share,
                fr.composite_quality_score
            FROM financial_ratios fr
            WHERE fr.financial_year BETWEEN 2020 AND 2024
            ORDER BY fr.company_id, fr.financial_year;
            """,
            conn,
        )


def _safe_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _pick_col(frame: pd.DataFrame, candidates: list[str]) -> str | None:
    for candidate in candidates:
        if candidate in frame.columns:
            return candidate
    return None


def _sector_median_pe(latest_2024: pd.DataFrame, market_cap: pd.DataFrame) -> pd.DataFrame:
    if latest_2024.empty:
        return pd.DataFrame(columns=["broad_sector", "sector_median_pe"])

    merged = latest_2024.merge(_sector_lookup(), on="company_id", how="left")
    if not market_cap.empty:
        merged = merged.merge(market_cap, on=["company_id", "financial_year"], how="left", suffixes=("", "_mc"))

    pe_col = _pick_col(merged, ["pe_ratio", "P/E", "pe", "price_to_earnings", "market_pe"])
    if pe_col is None:
        if {"market_cap_crore", "earnings_per_share"}.issubset(merged.columns):
            merged["pe_ratio"] = np.where(
                _safe_numeric(merged["earnings_per_share"]).fillna(0) != 0,
                _safe_numeric(merged["market_cap_crore"]) / _safe_numeric(merged["earnings_per_share"]).abs(),
                np.nan,
            )
            pe_col = "pe_ratio"
        else:
            merged["pe_ratio"] = np.nan
            pe_col = "pe_ratio"

    return (
        merged.groupby("broad_sector")[pe_col]
        .median()
        .reset_index()
        .rename(columns={pe_col: "sector_median_pe"})
    )


def _apply_overvaluation_flag(pe: Any, median_pe: Any) -> str:
    pe_value = pd.to_numeric(pd.Series([pe]), errors="coerce").iloc[0]
    median_value = pd.to_numeric(pd.Series([median_pe]), errors="coerce").iloc[0]
    if pd.isna(pe_value) or pd.isna(median_value) or median_value == 0:
        return "N/A"
    if pe_value > (median_value * 1.5):
        return "Caution"
    if pe_value < (median_value * 0.7):
        return "Discount"
    return "Fair"


def build_valuation_summary() -> pd.DataFrame:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _ensure_reference_excels()

    companies = _company_universe()
    latest_2024 = _financial_ratios_2024()
    market_cap = _ensure_market_cap_table()
    _export_market_cap_workbook(market_cap)
    history = _latest_ratio_history()
    sector_medians = _sector_median_pe(latest_2024, market_cap)
    sectors = _sector_lookup()

    if companies.empty:
        summary = pd.DataFrame(
            columns=[
                "company_id",
                "company_name",
                "sector",
                "P/E",
                "P/B",
                "EV/EBITDA",
                "FCF_yield_pct",
                "5yr_median_PE",
                "PE_vs_sector_median_pct",
                "flag",
            ]
        )
        summary.to_excel(OUTPUT_DIR / "valuation_summary.xlsx", index=False)
        summary.to_csv(OUTPUT_DIR / "valuation_flags.csv", index=False)
        return summary

    latest = companies.merge(latest_2024, on="company_id", how="left")
    latest = latest.merge(sectors[["company_id", "broad_sector"]], on="company_id", how="left")

    if not market_cap.empty:
        latest = latest.merge(market_cap, on=["company_id", "financial_year"], how="left", suffixes=("", "_mc"))

    latest["sector"] = latest["broad_sector"].fillna(latest.get("sector_name")).fillna("Unknown")
    latest["market_cap_crore"] = latest.get("market_cap_crore", np.nan)

    pe_col = _pick_col(latest, ["pe_ratio", "P/E", "pe", "price_to_earnings"])
    pb_col = _pick_col(latest, ["pb_ratio", "P/B", "pb", "price_to_book"])
    ev_col = _pick_col(latest, ["ev_ebitda", "EV/EBITDA", "ev_to_ebitda", "ev_ebitda_ratio"])

    if pe_col is None:
        latest["P/E"] = np.where(
            _safe_numeric(latest["earnings_per_share"]).fillna(0) != 0,
            _safe_numeric(latest["market_cap_crore"]) / _safe_numeric(latest["earnings_per_share"]).abs(),
            np.nan,
        )
    else:
        latest["P/E"] = latest[pe_col]

    if pb_col is None:
        latest["P/B"] = np.where(
            _safe_numeric(latest["total_equity"]).fillna(0) != 0,
            _safe_numeric(latest["market_cap_crore"]) / _safe_numeric(latest["total_equity"]).abs(),
            np.nan,
        )
    else:
        latest["P/B"] = latest[pb_col]

    latest["EV/EBITDA"] = latest[ev_col] if ev_col else np.nan
    latest["FCF_yield_pct"] = np.where(
        _safe_numeric(latest["market_cap_crore"]).fillna(0) != 0,
        (_safe_numeric(latest["free_cash_flow_cr"]).fillna(0) / _safe_numeric(latest["market_cap_crore"])) * 100.0,
        np.nan,
    )

    latest_history = history.copy()
    latest_history["pe_ratio"] = np.where(
        _safe_numeric(latest_history["earnings_per_share"]).fillna(0) != 0,
        1.0 / _safe_numeric(latest_history["earnings_per_share"]).abs().replace(0, np.nan),
        np.nan,
    )
    median_history = (
        latest_history.groupby("company_id")["pe_ratio"]
        .median()
        .reset_index()
        .rename(columns={"pe_ratio": "5yr_median_PE"})
    )
    latest = latest.merge(median_history, on="company_id", how="left")

    latest = latest.merge(sector_medians, left_on="sector", right_on="broad_sector", how="left")
    latest["PE_vs_sector_median_pct"] = np.where(
        _safe_numeric(latest["sector_median_pe"]).fillna(0) != 0,
        ((_safe_numeric(latest["P/E"]) / _safe_numeric(latest["sector_median_pe"])) - 1.0) * 100.0,
        np.nan,
    )
    latest["flag"] = latest.apply(
        lambda row: _apply_overvaluation_flag(row.get("P/E"), row.get("sector_median_pe")),
        axis=1,
    )

    summary = latest[
        [
            "company_id",
            "company_name",
            "sector",
            "P/E",
            "P/B",
            "EV/EBITDA",
            "FCF_yield_pct",
            "5yr_median_PE",
            "PE_vs_sector_median_pct",
            "flag",
        ]
    ].copy()

    summary = summary.sort_values(["flag", "company_id"], kind="stable").reset_index(drop=True)
    summary.to_excel(OUTPUT_DIR / "valuation_summary.xlsx", index=False)
    summary.loc[summary["flag"].isin(["Caution", "Discount"])].to_csv(
        OUTPUT_DIR / "valuation_flags.csv", index=False
    )
    return summary


if __name__ == "__main__":  
    build_valuation_summary()
