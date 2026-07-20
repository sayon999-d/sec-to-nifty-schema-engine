from __future__ import annotations

from pathlib import Path
import sys
from urllib.error import URLError
from urllib.request import urlopen

import pandas as pd
import sqlite3

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

from dashboard.utils.db import get_available_years, get_companies, get_market_cap_lookup, get_sectors

DB_PATH = PROJECT_ROOT / "db" / "nifty100.db"
API_CLUSTER_URL = "http://127.0.0.1:8000/api/v1/clusters"
API_CLUSTER_NOTE = "Open the cluster API in a separate browser tab from the root host, not from a nested dashboard route."


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _year_frame(year: int) -> pd.DataFrame:
    query = """
        SELECT
            fr.company_id,
            fr.financial_year,
            fr.return_on_equity_pct,
            fr.debt_to_equity,
            fr.revenue_cagr_5yr,
            fr.composite_quality_score,
            fr.icr_label
        FROM financial_ratios fr
        WHERE fr.financial_year = ?
        ORDER BY fr.company_id;
    """
    with _connect() as conn:
        return pd.read_sql_query(query, conn, params=(year,))


def _clean_year_options() -> list[int]:
    years = get_available_years()
    cleaned = sorted({int(year) for year in years if pd.notna(year) and 2019 <= int(year) <= 2024}, reverse=True)
    if cleaned:
        return cleaned
    return list(range(2024, 2018, -1))


def _summary_metrics(year: int) -> dict[str, float | int]:
    ratios = _year_frame(year)
    if ratios.empty:
        fallback_years = [available for available in _clean_year_options() if available != year]
        for fallback_year in fallback_years:
            ratios = _year_frame(fallback_year)
            if not ratios.empty:
                year = fallback_year
                break
    companies = get_companies()
    sectors = get_sectors()
    market_cap = get_market_cap_lookup()
    sector_count = sectors["sector_name"].nunique() if "sector_name" in sectors.columns else 0
    debt_free = 0
    median_pe = 0.0
    median_de = 0.0
    avg_roe = 0.0
    median_cagr = 0.0
    if not ratios.empty:
        avg_roe = float(pd.to_numeric(ratios["return_on_equity_pct"], errors="coerce").mean() or 0)
        median_de = float(pd.to_numeric(ratios["debt_to_equity"], errors="coerce").median() or 0)
        median_cagr = float(pd.to_numeric(ratios["revenue_cagr_5yr"], errors="coerce").median() or 0)
        debt_free = int(
            pd.Series(ratios.get("icr_label", pd.Series(dtype=str)))
            .astype(str)
            .str.contains("Debt Free", case=False, na=False)
            .sum()
        )
    if not market_cap.empty and "financial_year" in market_cap.columns:
        latest_market_cap = market_cap.copy()
        latest_market_cap["financial_year"] = pd.to_numeric(latest_market_cap["financial_year"], errors="coerce")
        latest_market_cap = latest_market_cap[latest_market_cap["financial_year"] == year]
        if not latest_market_cap.empty and "pe_ratio" in latest_market_cap.columns:
            median_pe = float(pd.to_numeric(latest_market_cap["pe_ratio"], errors="coerce").median() or 0)
    return {
        "Avg ROE": avg_roe,
        "Median P/E": median_pe,
        "Median D/E": median_de,
        "Total Companies": int(companies.shape[0]),
        "Median 5Y Rev CAGR": median_cagr,
        "Debt-Free count": debt_free,
        "Total Sectors": sector_count,
    }


def _cluster_summary() -> pd.DataFrame:
    path = PROJECT_ROOT / "output" / "cluster_labels.csv"
    if not path.exists():
        return pd.DataFrame()
    frame = pd.read_csv(path)
    if frame.empty or "cluster_name" not in frame.columns:
        return pd.DataFrame()
    return frame.groupby("cluster_name", dropna=False).size().reset_index(name="company_count").sort_values("company_count", ascending=False)


def _api_is_reachable(url: str = API_CLUSTER_URL, timeout: float = 1.5) -> bool:
    try:
        with urlopen(url, timeout=timeout) as response:  # noqa: S310 - local endpoint probe
            return 200 <= getattr(response, "status", 0) < 500
    except URLError:
        return False
    except Exception:
        return False


def main() -> None:
    if st is None:
        return
    st.title("Home")
    year_options = _clean_year_options()
    year = st.sidebar.selectbox(
        "Reporting Year",
        year_options,
        index=0 if year_options else None,
        format_func=lambda value: str(int(value)),
    )
    metrics = _summary_metrics(year)
    cols = st.columns(6)
    ordered_metrics = [
        ("Avg ROE", metrics["Avg ROE"]),
        ("Median P/E", metrics["Median P/E"]),
        ("Median D/E", metrics["Median D/E"]),
        ("Total Companies", metrics["Total Companies"]),
        ("Median 5Y Rev CAGR", metrics["Median 5Y Rev CAGR"]),
        ("Debt-Free count", metrics["Debt-Free count"]),
    ]
    for col, (label, value) in zip(cols, ordered_metrics):
        with col:
            st.metric(label, f"{value:,.2f}" if isinstance(value, float) else f"{value:,}")

    sectors = get_sectors()
    if not sectors.empty and px is not None:
        sector_col = "sector_name" if "sector_name" in sectors.columns else sectors.columns[0]
        sector_counts = sectors.groupby(sector_col, dropna=False).size().reset_index(name="company_count")
        fig = px.pie(sector_counts, names=sector_col, values="company_count", title="Sector Breakdown", hole=0.45)
        st.plotly_chart(fig, use_container_width=True)
    st.subheader("Top-5 Composite Score")
    ratios = _year_frame(year)
    if ratios.empty:
        st.info("Composite score data unavailable for the selected year.")
        return
    top_5 = ratios.copy()
    top_5["composite_quality_score"] = pd.to_numeric(top_5["composite_quality_score"], errors="coerce")
    top_5 = top_5.sort_values("composite_quality_score", ascending=False).head(5)
    if not top_5.empty:
        st.dataframe(top_5[["company_id", "financial_year", "composite_quality_score"]])
    else:
        st.info("Composite score data unavailable for the selected year.")

    st.subheader("Sprint 6 Cluster Summary")
    st.caption("Direct API shortcut: `/api/v1/clusters`")
    st.caption(API_CLUSTER_NOTE)
    cluster_summary = _cluster_summary()
    if cluster_summary.empty:
        st.info("Cluster labels have not been generated yet.")
    else:
        if _api_is_reachable():
            st.markdown(f"[Open Cluster Summary Endpoint]({API_CLUSTER_URL})")
        else:
            st.warning("Cluster API is not running. Start it with `make sprint6-api-start` and then reopen this page.")
            st.code(API_CLUSTER_URL)
        st.dataframe(cluster_summary, use_container_width=True)


if __name__ == "__main__":
    main()
