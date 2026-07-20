from __future__ import annotations

from pathlib import Path
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

from dashboard.utils.db import get_companies, get_pl, get_ratios

METRIC_MAP = {
    "Revenue": "revenue",
    "PAT": "net_income",
    "Operating Profit": "operating_profit",
    "ROE": "return_on_equity_pct",
    "ROCE": "return_on_capital_employed_pct",
    "NPM": "net_profit_margin_pct",
    "OPM": "operating_profit_margin_pct",
    "FCF": "free_cash_flow_cr",
}


def _company_choices() -> list[tuple[str, str]]:
    companies = get_companies()
    if companies.empty:
        return []
    ticker_col = "ticker" if "ticker" in companies.columns else companies.columns[0]
    name_col = "company_name" if "company_name" in companies.columns else companies.columns[-1]
    choices: list[tuple[str, str]] = []
    for _, row in companies.iterrows():
        ticker = str(row.get(ticker_col, "")).strip()
        name = str(row.get(name_col, "")).strip()
        if not ticker:
            continue
        choices.append((f"{name} ({ticker})", ticker))
    return choices


def _historical_frame(ticker: str) -> pd.DataFrame:
    pl = get_pl(ticker)
    ratios = get_ratios(ticker)
    if pl.empty and ratios.empty:
        return pd.DataFrame()
    pl = pl.copy()
    ratios = ratios.copy()
    if not pl.empty:
        pl = pl.sort_values("financial_year")
    if not ratios.empty:
        ratios = ratios.sort_values("financial_year")
    merged = pl.merge(
        ratios[
            [
                col
                for col in [
                    "financial_year",
                    "return_on_equity_pct",
                    "return_on_capital_employed_pct",
                    "net_profit_margin_pct",
                    "operating_profit_margin_pct",
                    "free_cash_flow_cr",
                ]
                if col in ratios.columns
            ]
        ],
        on="financial_year",
        how="left",
    )
    if "free_cash_flow_cr" not in merged.columns and "free_cash_flow_cr" in ratios.columns:
        merged["free_cash_flow_cr"] = ratios["free_cash_flow_cr"].values[: len(merged)]
    return merged.sort_values("financial_year").tail(10).reset_index(drop=True)


def _yoy_change(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    prev = numeric.shift(1)
    change = ((numeric - prev) / prev.abs()) * 100.0
    return change.replace([pd.NA, pd.NaT, float("inf"), float("-inf")], pd.NA)


def _chart_metric(frame: pd.DataFrame, metric_label: str) -> go.Scatter:
    source_col = METRIC_MAP[metric_label]
    values = pd.to_numeric(frame.get(source_col), errors="coerce")
    yoy = _yoy_change(values)
    text = [
        f"{value:.1f}%"
        if pd.notna(value)
        else ""
        for value in yoy
    ]
    return go.Scatter(
        x=frame["financial_year"],
        y=values,
        mode="lines+markers+text",
        name=metric_label,
        text=text,
        textposition="top center",
        hovertemplate=f"{metric_label}: %{{y:.2f}}<br>Year: %{{x}}<extra></extra>",
    )


def main() -> None:
    if st is None:
        return
    st.title("Trends")

    company_choices = _company_choices()
    if not company_choices:
        st.warning("No companies available.")
        return

    labels = [label for label, _ in company_choices]
    selected_label = st.selectbox("Company", labels)
    ticker = next((ticker for label, ticker in company_choices if label == selected_label), None)
    if not ticker:
        st.error("Ticker not found — please try another.")
        return

    available_metrics = list(METRIC_MAP.keys())
    selected_metrics = st.multiselect("Overlay up to 3 metrics", available_metrics, default=["Revenue"], max_selections=3)
    if not selected_metrics:
        st.info("Select at least one metric.")
        return

    frame = _historical_frame(ticker)
    if frame.empty:
        st.info("No historical data available.")
        return

    fig = go.Figure()
    for metric in selected_metrics[:3]:
        if METRIC_MAP[metric] in frame.columns:
            fig.add_trace(_chart_metric(frame, metric))
    fig.update_layout(title=f"10-Year Trend Overlay - {selected_label}", xaxis_title="Financial Year", yaxis_title="Value")
    st.plotly_chart(fig, use_container_width=True)


if __name__ == "__main__":
    main()
