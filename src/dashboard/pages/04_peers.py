from __future__ import annotations

from pathlib import Path
import sqlite3
import sys

import pandas as pd

try:
    import plotly.graph_objects as go
    import streamlit as st
except Exception:  
    st = None
    go = None

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from analytics.peer import generate_peer_reports
from dashboard.utils.db import get_companies

DB_PATH = PROJECT_ROOT / "db" / "nifty100.db"

RADAR_METRICS = [
    ("return_on_equity_pct", "ROE"),
    ("return_on_capital_employed_pct", "ROCE"),
    ("net_profit_margin_pct", "NPM"),
    ("operating_profit_margin_pct", "OPM"),
    ("revenue_cagr_5yr", "Rev CAGR"),
    ("pat_cagr_5yr", "PAT CAGR"),
    ("debt_to_equity", "D/E"),
    ("interest_coverage", "ICR"),
]


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _peer_groups() -> list[str]:
    with _connect() as conn:
        frame = pd.read_sql_query(
            "SELECT DISTINCT peer_group_name FROM peer_groups WHERE peer_group_name IS NOT NULL ORDER BY peer_group_name;",
            conn,
        )
    if frame.empty:
        return []
    return [str(value) for value in frame["peer_group_name"].dropna().tolist() if str(value).strip()]


def _latest_company_peer_group(company_id: int) -> str | None:
    with _connect() as conn:
        frame = pd.read_sql_query(
            """
            SELECT peer_group_name
            FROM peer_groups
            WHERE company_id = ?
              AND peer_group_name IS NOT NULL
            ORDER BY financial_year DESC
            LIMIT 1;
            """,
            conn,
            params=(company_id,),
        )
    if frame.empty:
        return None
    value = frame.iloc[0]["peer_group_name"]
    return str(value).strip() if pd.notna(value) else None


def _latest_ratios_for_group(group_name: str) -> pd.DataFrame:
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
            fr.financial_year,
            fr.return_on_equity_pct,
            fr.return_on_capital_employed_pct,
            fr.net_profit_margin_pct,
            fr.operating_profit_margin_pct,
            fr.revenue_cagr_5yr,
            fr.pat_cagr_5yr,
            fr.debt_to_equity,
            fr.interest_coverage,
            fr.composite_quality_score
        FROM financial_ratios fr
        JOIN latest l ON l.company_id = fr.company_id AND l.financial_year = fr.financial_year
        JOIN companies c ON c.id = fr.company_id
        JOIN peer_groups pg
          ON pg.company_id = fr.company_id
         AND pg.financial_year = fr.financial_year
        WHERE pg.peer_group_name = ?
        ORDER BY c.company_name;
    """
    with _connect() as conn:
        return pd.read_sql_query(query, conn, params=(group_name,))


def _company_latest_row(company_id: int) -> pd.DataFrame:
    query = """
        SELECT
            fr.company_id,
            c.company_name,
            c.ticker,
            fr.financial_year,
            fr.return_on_equity_pct,
            fr.return_on_capital_employed_pct,
            fr.net_profit_margin_pct,
            fr.operating_profit_margin_pct,
            fr.revenue_cagr_5yr,
            fr.pat_cagr_5yr,
            fr.debt_to_equity,
            fr.interest_coverage,
            fr.composite_quality_score
        FROM financial_ratios fr
        JOIN companies c ON c.id = fr.company_id
        WHERE fr.company_id = ?
        ORDER BY fr.financial_year DESC
        LIMIT 1;
    """
    with _connect() as conn:
        return pd.read_sql_query(query, conn, params=(company_id,))


def _peer_average(group_frame: pd.DataFrame) -> dict[str, float]:
    averages: dict[str, float] = {}
    for metric, _ in RADAR_METRICS:
        averages[metric] = float(pd.to_numeric(group_frame[metric], errors="coerce").mean() or 0.0) if metric in group_frame.columns else 0.0
    return averages


def _value_for_radar(value: float | None, metric: str) -> float:
    if value is None or pd.isna(value):
        return 0.0
    numeric = float(value)
    if metric == "debt_to_equity":
        return max(0.0, 100.0 - min(100.0, numeric * 20.0))
    if metric == "interest_coverage":
        return min(100.0, numeric * 10.0)
    return max(0.0, min(100.0, numeric))


def _build_radar(company_row: pd.Series, group_frame: pd.DataFrame):
    if go is None:
        return None
    company_values = [_value_for_radar(pd.to_numeric(company_row.get(metric), errors="coerce"), metric) for metric, _ in RADAR_METRICS]
    group_average = _peer_average(group_frame)
    average_values = [_value_for_radar(group_average.get(metric), metric) for metric, _ in RADAR_METRICS]
    labels = [label for _, label in RADAR_METRICS]
    labels += [labels[0]]
    company_values += [company_values[0]]
    average_values += [average_values[0]]

    fig = go.Figure()
    fig.add_trace(
        go.Scatterpolar(
            r=average_values,
            theta=labels,
            fill="toself",
            name="Peer Group Average",
            line=dict(color="#F4B400", dash="dash"),
            opacity=0.35,
        )
    )
    fig.add_trace(
        go.Scatterpolar(
            r=company_values,
            theta=labels,
            fill="toself",
            name=str(company_row.get("company_name", "Selected Company")),
            line=dict(color="#5DADE2"),
            opacity=0.65,
        )
    )
    fig.update_layout(
        title=f"Peer Radar - {company_row.get('company_name', 'N/A')}",
        polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
        showlegend=True,
        height=520,
    )
    return fig


def _benchmark_table(company_row: pd.Series, group_frame: pd.DataFrame) -> pd.DataFrame:
    if group_frame.empty:
        return pd.DataFrame([{
            "benchmark": company_row.get("company_name", "N/A"),
            "company_id": company_row.get("company_id", "N/A"),
            "peer_group": "N/A",
        }])
    selected_company = pd.DataFrame([{
        "benchmark": company_row.get("company_name", "N/A"),
        "company_id": company_row.get("company_id", "N/A"),
        "peer_group": group_frame.iloc[0].get("peer_group_name", "N/A"),
        "ROE": company_row.get("return_on_equity_pct"),
        "ROCE": company_row.get("return_on_capital_employed_pct"),
        "NPM": company_row.get("net_profit_margin_pct"),
        "OPM": company_row.get("operating_profit_margin_pct"),
        "Rev CAGR": company_row.get("revenue_cagr_5yr"),
        "PAT CAGR": company_row.get("pat_cagr_5yr"),
        "D/E": company_row.get("debt_to_equity"),
        "ICR": company_row.get("interest_coverage"),
    }])
    median_row = {
        "benchmark": "Group Median",
        "company_id": None,
        "peer_group": group_frame.iloc[0].get("peer_group_name", "N/A"),
    }
    for metric, label in RADAR_METRICS:
        median_row[label if label != "Rev CAGR" and label != "PAT CAGR" else label] = pd.to_numeric(group_frame[metric], errors="coerce").median()
    return pd.concat([selected_company, pd.DataFrame([median_row])], ignore_index=True)


def main() -> None:
    if st is None:
        return
    st.title("Peers")

    peer_groups = _peer_groups()
    if not peer_groups:
        st.warning("No peer groups found.")
        return

    selected_group = st.selectbox("Peer Group", peer_groups, key="peer_group_select")

    companies = get_companies()
    if companies.empty:
        st.warning("No companies available to select.")
        return

    companies = companies.copy()
    id_col = "id" if "id" in companies.columns else companies.columns[0]
    name_col = "company_name" if "company_name" in companies.columns else companies.columns[-1]
    ticker_col = "ticker" if "ticker" in companies.columns else None

    companies["display_label"] = companies.apply(
        lambda row: f"{str(row.get(name_col, '')).strip()} ({str(row.get(ticker_col, '')).strip()})"
        if ticker_col and str(row.get(ticker_col, "")).strip()
        else str(row.get(name_col, "")).strip(),
        axis=1,
    )
    companies["display_label"] = companies["display_label"].replace("", pd.NA).dropna()
    company_labels = companies["display_label"].dropna().tolist()
    selected_label = st.selectbox("Company", company_labels, key="peer_company_select")
    selected_row = companies.loc[companies["display_label"].eq(selected_label)].head(1)
    if selected_row.empty:
        st.warning("No benchmark company could be resolved.")
        return

    company_id = int(selected_row.iloc[0][id_col])
    actual_group = _latest_company_peer_group(company_id) or selected_group
    if actual_group != selected_group:
        st.caption(f"Active company belongs to {actual_group}; showing that group instead.")
        selected_group = actual_group

    group_frame = _latest_ratios_for_group(selected_group)
    company_frame = _company_latest_row(company_id)
    if company_frame.empty:
        st.warning("Ticker/company data not found.")
        return

    company_row = company_frame.iloc[0]
    company_group_frame = group_frame.loc[group_frame["company_id"].eq(company_id)].copy()
    if company_group_frame.empty:
        company_group_frame = group_frame.copy()

    st.caption(f"Selected company: {company_row.get('company_name', 'N/A')} | Benchmark group: {selected_group}")

    radar_fig = _build_radar(company_row, group_frame if not group_frame.empty else company_group_frame)
    if radar_fig is not None:
        st.plotly_chart(radar_fig, use_container_width=True)
    else:
        st.info("Radar chart unavailable.")

    benchmark_table = _benchmark_table(company_row, group_frame)
    if not benchmark_table.empty:
        st.dataframe(benchmark_table, use_container_width=True)
    else:
        st.info("Benchmark data unavailable.")

    generate_peer_reports()


if __name__ == "__main__":
    main()
