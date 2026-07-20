from __future__ import annotations

from pathlib import Path
import sqlite3
import sys

import pandas as pd

try:
    import plotly.express as px
    import streamlit as st
except Exception:  
    st = None
    px = None

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

DB_PATH = PROJECT_ROOT / "db" / "nifty100.db"

PATTERN_ORDER = [
    "Reinvestor",
    "Shareholder Returns",
    "Liquidating Assets",
    "Distress Signal",
    "Growth Funded by Debt",
    "Cash Accumulator",
    "Pre-Revenue",
    "Mixed",
]


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _latest_capital_frame() -> pd.DataFrame:
    query = """
        WITH latest AS (
            SELECT company_id, MAX(financial_year) AS financial_year
            FROM cashflow
            GROUP BY company_id
        )
        SELECT
            c.id AS company_id,
            c.company_name,
            c.ticker,
            fr.financial_year,
            cf.net_cash_from_operations AS cfo,
            cf.net_cash_from_investing AS cfi,
            cf.net_cash_from_financing AS cff,
            cf.net_cash_flow,
            fr.cash_from_operations_cr,
            fr.free_cash_flow_cr,
            fr.return_on_equity_pct,
            fr.composite_quality_score,
            s.sector_name,
            s.industry_name,
            s.sub_industry_name
        FROM cashflow cf
        JOIN latest l ON l.company_id = cf.company_id AND l.financial_year = cf.financial_year
        JOIN companies c ON c.id = cf.company_id
        LEFT JOIN financial_ratios fr ON fr.company_id = cf.company_id AND fr.financial_year = cf.financial_year
        LEFT JOIN sectors s ON s.company_id = cf.company_id
        ORDER BY c.id;
    """
    with _connect() as conn:
        frame = pd.read_sql_query(query, conn)
    return frame


def _sign(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "0"
    if float(value) > 0:
        return "+"
    if float(value) < 0:
        return "-"
    return "0"


def _classify_pattern(row: pd.Series) -> str:
    cfo_sign = _sign(row.get("cfo"))
    cfi_sign = _sign(row.get("cfi"))
    cff_sign = _sign(row.get("cff"))
    pattern = (cfo_sign, cfi_sign, cff_sign)
    if pattern == ("+", "-", "-"):
        return "Shareholder Returns" if pd.to_numeric(pd.Series([row.get("cash_from_operations_cr")]), errors="coerce").iloc[0] not in {None, 0} else "Reinvestor"
    if pattern == ("+", "+", "-"):
        return "Liquidating Assets"
    if pattern == ("-", "+", "+"):
        return "Distress Signal"
    if pattern == ("-", "-", "+"):
        return "Growth Funded by Debt"
    if pattern == ("+", "+", "+"):
        return "Cash Accumulator"
    if pattern == ("-", "-", "-"):
        return "Pre-Revenue"
    return "Mixed"


def _capital_table() -> pd.DataFrame:
    frame = _latest_capital_frame()
    if frame.empty:
        return frame
    frame = frame.copy()
    frame["cfo_sign"] = frame["cfo"].apply(_sign)
    frame["cfi_sign"] = frame["cfi"].apply(_sign)
    frame["cff_sign"] = frame["cff"].apply(_sign)
    frame["pattern_label"] = frame.apply(_classify_pattern, axis=1)
    return frame


def _treemap(frame: pd.DataFrame):
    if px is None or frame.empty:
        return None
    counts = frame.groupby("pattern_label", dropna=False).agg(
        company_count=("company_id", "count"),
    ).reset_index()
    counts["root"] = "Capital Allocation"
    return px.treemap(
        counts,
        path=["root", "pattern_label"],
        values="company_count",
        color="company_count",
        color_continuous_scale="Blues",
        title="Capital Allocation Patterns",
    )


def main() -> None:
    if st is None:
        return
    st.title("Capital Allocation")

    frame = _capital_table()
    if frame.empty:
        st.warning("No capital allocation data available.")
        return

    pattern_options = ["All Patterns"] + [pattern for pattern in PATTERN_ORDER if pattern in frame["pattern_label"].unique().tolist()]
    selected_pattern = st.selectbox("Allocation pattern", pattern_options)

    fig = _treemap(frame)
    if fig is not None:
        st.plotly_chart(fig, use_container_width=True)

    if selected_pattern != "All Patterns":
        filtered = frame.loc[frame["pattern_label"].astype(str).eq(selected_pattern)].copy()
    else:
        filtered = frame.copy()

    if filtered.empty:
        st.info("No company list available for the selected pattern.")
        return

    st.markdown(f"### {selected_pattern if selected_pattern != 'All Patterns' else 'All Patterns'}")
    st.dataframe(
        filtered[[
            col for col in [
                "company_id",
                "company_name",
                "ticker",
                "financial_year",
                "cfo_sign",
                "cfi_sign",
                "cff_sign",
                "pattern_label",
                "sector_name",
                "industry_name",
                "sub_industry_name",
            ] if col in filtered.columns
        ]].sort_values(["pattern_label", "company_name"]),
        use_container_width=True,
    )


if __name__ == "__main__":
    main()
