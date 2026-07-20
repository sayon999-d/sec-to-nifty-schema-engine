from __future__ import annotations

from pathlib import Path
import sqlite3
import sys

import pandas as pd

try:
    import plotly.express as px
    import plotly.graph_objects as go
    import streamlit as st
except Exception:  
    st = None
    px = None
    go = None

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from dashboard.utils.db import get_companies, get_market_cap_lookup, get_sectors

DB_PATH = PROJECT_ROOT / "db" / "nifty100.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _latest_sector_frame() -> pd.DataFrame:
    query = """
        WITH latest AS (
            SELECT company_id, MAX(financial_year) AS financial_year
            FROM financial_ratios
            GROUP BY company_id
        )
        SELECT
            fr.company_id,
            c.company_name,
            c.ticker,
            s.sector_name,
            s.industry_name,
            s.sub_industry_name,
            fr.financial_year,
            fr.return_on_equity_pct,
            fr.return_on_capital_employed_pct,
            fr.net_profit_margin_pct,
            fr.operating_profit_margin_pct,
            fr.debt_to_equity,
            fr.revenue_cagr_5yr,
            fr.pat_cagr_5yr,
            fr.composite_quality_score,
            p.revenue,
            mc.market_cap_crore,
            mc.pb_ratio,
            mc.pe_ratio,
            mc.ev_ebitda
        FROM financial_ratios fr
        JOIN latest l ON l.company_id = fr.company_id AND l.financial_year = fr.financial_year
        JOIN companies c ON c.id = fr.company_id
        LEFT JOIN sectors s ON s.company_id = fr.company_id
        LEFT JOIN profitandloss p ON p.company_id = fr.company_id AND p.financial_year = fr.financial_year
        LEFT JOIN market_cap mc ON mc.company_id = fr.company_id AND mc.financial_year = fr.financial_year
        ORDER BY fr.company_id;
    """
    with _connect() as conn:
        frame = pd.read_sql_query(query, conn)
    if frame.empty:
        return frame
    frame["sector_name"] = frame["sector_name"].fillna("Unknown")
    frame["sub_industry_name"] = frame["sub_industry_name"].fillna(frame["sector_name"])
    return frame


def _sector_medians(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    medians = (
        frame.groupby("sector_name", dropna=False)
        .agg(
            revenue=("revenue", "median"),
            return_on_equity_pct=("return_on_equity_pct", "median"),
            market_cap_crore=("market_cap_crore", "median"),
            composite_quality_score=("composite_quality_score", "median"),
        )
        .reset_index()
        .rename(columns={"sector_name": "sector"})
    )
    return medians


def main() -> None:
    if st is None:
        return
    st.title("Sectors")

    sector_frame = _latest_sector_frame()
    if sector_frame.empty:
        st.warning("No sector data available.")
        return

    broad_sector = st.selectbox("Broad sector", sorted(sector_frame["sector_name"].dropna().astype(str).unique().tolist()))
    filtered = sector_frame.loc[sector_frame["sector_name"].astype(str).eq(broad_sector)].copy()
    if filtered.empty:
        st.info("No companies found for this sector.")
        return

    if px is not None:
        bubble_frame = filtered.copy()
        for column in ["revenue", "return_on_equity_pct", "market_cap_crore"]:
            bubble_frame[column] = pd.to_numeric(bubble_frame.get(column), errors="coerce")
        bubble_frame = bubble_frame.dropna(subset=["revenue", "return_on_equity_pct"]).copy()
        if bubble_frame["market_cap_crore"].isna().all():
            bubble_frame["market_cap_crore"] = 1.0
        else:
            fallback_size = float(bubble_frame["market_cap_crore"].median(skipna=True) or 1.0)
            bubble_frame["market_cap_crore"] = bubble_frame["market_cap_crore"].fillna(fallback_size).clip(lower=1.0)
        bubble = px.scatter(
            bubble_frame,
            x="revenue",
            y="return_on_equity_pct",
            size="market_cap_crore",
            color="sub_industry_name",
            hover_name="company_name",
            title=f"Sector Bubble Chart - {broad_sector}",
            labels={
                "revenue": "Revenue",
                "return_on_equity_pct": "ROE",
                "market_cap_crore": "Market Cap",
                "sub_industry_name": "Sub-Sector",
            },
        )
        st.plotly_chart(bubble, use_container_width=True)

    medians = _sector_medians(sector_frame)
    if not medians.empty and go is not None:
        bar_fig = go.Figure()
        bar_fig.add_trace(
            go.Bar(
                x=medians["sector"],
                y=pd.to_numeric(medians["revenue"], errors="coerce"),
                name="Median Revenue",
                marker_color="#5DADE2",
            )
        )
        bar_fig.add_trace(
            go.Bar(
                x=medians["sector"],
                y=pd.to_numeric(medians["return_on_equity_pct"], errors="coerce"),
                name="Median ROE",
                marker_color="#58D68D",
            )
        )
        bar_fig.add_trace(
            go.Bar(
                x=medians["sector"],
                y=pd.to_numeric(medians["composite_quality_score"], errors="coerce"),
                name="Median Quality Score",
                marker_color="#F4B400",
            )
        )
        bar_fig.update_layout(
            title="Sector Median KPI Snapshot",
            barmode="group",
            xaxis_title="Sector",
            yaxis_title="Median Value",
        )
        st.plotly_chart(bar_fig, use_container_width=True)

    st.dataframe(filtered[[
        col for col in [
            "company_name",
            "ticker",
            "sector_name",
            "sub_industry_name",
            "revenue",
            "return_on_equity_pct",
            "market_cap_crore",
            "composite_quality_score",
        ] if col in filtered.columns
    ]], use_container_width=True)


if __name__ == "__main__":
    main()
