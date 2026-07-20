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

from dashboard.utils.db import get_companies, get_pl, get_ratios, get_valuation

DB_PATH = PROJECT_ROOT / "db" / "nifty100.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _company_options() -> list[dict[str, str]]:
    companies = get_companies()
    if companies.empty:
        return []
    id_col = "id" if "id" in companies.columns else companies.columns[0]
    ticker_col = "ticker" if "ticker" in companies.columns else None
    name_col = "company_name" if "company_name" in companies.columns else companies.columns[-1]
    options: list[dict[str, str]] = []
    for _, row in companies.iterrows():
        ticker = str(row.get(ticker_col, "")).strip() if ticker_col else ""
        company_name = str(row.get(name_col, "")).strip()
        if not ticker and not company_name:
            continue
        label = f"{company_name} ({ticker})" if ticker else company_name
        options.append(
            {
                "label": label,
                "ticker": ticker,
                "company_id": str(row.get(id_col, "")),
                "company_name": company_name,
            }
        )
    return options


def _resolve_company_label(search_text: str, options: list[dict[str, str]]) -> list[dict[str, str]]:
    if not search_text:
        return options
    needle = search_text.strip().lower()
    filtered = [
        option
        for option in options
        if needle in option["label"].lower() or needle in option["ticker"].lower()
    ]
    return filtered or options


def _company_row(ticker: str) -> pd.DataFrame:
    companies = get_companies()
    if companies.empty or "ticker" not in companies.columns:
        return pd.DataFrame()
    return companies.loc[companies["ticker"].astype(str).eq(ticker)].head(1)


def _latest_market_price_and_pe(ticker: str, eps_value: float | None) -> tuple[float | None, float | None]:
    valuation = get_valuation(ticker)
    if valuation.empty:
        return None, None
    valuation = valuation.copy()
    for column in ("financial_year", "year", "market_cap_crore", "pe_ratio", "pb_ratio", "ev_ebitda", "trade_date"):
        if column in valuation.columns:
            valuation[column] = pd.to_numeric(valuation[column], errors="coerce") if column != "trade_date" else valuation[column]
    if "financial_year" in valuation.columns:
        valuation["financial_year"] = pd.to_numeric(valuation["financial_year"], errors="coerce")
        valuation = valuation.sort_values(["financial_year", "trade_date"], ascending=[False, False])
    latest = valuation.iloc[0]
    price = None
    if "pe_ratio" in valuation.columns and pd.notna(latest.get("pe_ratio")):
        price = float(latest.get("pe_ratio")) * float(eps_value) if eps_value not in {None, 0} else None
    if price is None and "market_cap_crore" in valuation.columns and eps_value not in {None, 0}:
        market_cap = pd.to_numeric(pd.Series([latest.get("market_cap_crore")]), errors="coerce").iloc[0]
        if pd.notna(market_cap):
            price = float(market_cap) / 1e2 if market_cap else None
    pe = (price / eps_value) if price is not None and eps_value not in {None, 0} else None
    if pe is None and "pe_ratio" in valuation.columns:
        pe = pd.to_numeric(pd.Series([latest.get("pe_ratio")]), errors="coerce").iloc[0]
    return price, pe


def _latest_ratios(ticker: str) -> pd.DataFrame:
    ratios = get_ratios(ticker)
    if ratios.empty:
        return ratios
    if "financial_year" in ratios.columns:
        ratios = ratios.sort_values("financial_year")
    return ratios.tail(10).copy()


def _pros_cons(company_id: int) -> tuple[list[str], list[str]]:
    with _connect() as conn:
        df = pd.read_sql_query(
            """
            SELECT pros, cons
            FROM prosandcons
            WHERE company_id = ?
            ORDER BY financial_year DESC
            LIMIT 1;
            """,
            conn,
            params=(company_id,),
        )
    if df.empty:
        return [], []
    pros = [item.strip() for item in str(df.iloc[0].get("pros", "")).split(".") if item.strip()]
    cons = [item.strip() for item in str(df.iloc[0].get("cons", "")).split(".") if item.strip()]
    return pros, cons


def _latest_pl_with_history(ticker: str) -> pd.DataFrame:
    pl = get_pl(ticker)
    if pl.empty:
        return pl
    return pl.sort_values("financial_year").tail(10).copy()


def _render_company_header(company: pd.Series) -> None:
    st.subheader("Profile Card")
    st.write(
        {
            "Company": company.get("company_name", "N/A"),
            "Ticker": company.get("ticker", "N/A"),
            "Company ID": company.get("id", "N/A"),
            "SIC": company.get("sic", "N/A"),
            "Location": f"{company.get('cityba', 'N/A')}, {company.get('stateba', 'N/A')}",
            "Listing Status": company.get("listing_status", "N/A"),
        }
    )


def _render_kpis(ticker: str, ratios: pd.DataFrame) -> None:
    latest = ratios.iloc[-1] if not ratios.empty else pd.Series(dtype=object)
    eps_value = pd.to_numeric(pd.Series([latest.get("earnings_per_share")]), errors="coerce").iloc[0] if not ratios.empty else None
    price, pe_ratio = _latest_market_price_and_pe(ticker, eps_value)
    metrics = [
        ("ROE", latest.get("return_on_equity_pct", "N/A")),
        ("ROCE", latest.get("return_on_capital_employed_pct", "N/A")),
        ("NPM", latest.get("net_profit_margin_pct", "N/A")),
        ("D/E", latest.get("debt_to_equity", "N/A")),
        ("5Y Rev CAGR", latest.get("revenue_cagr_5yr", "N/A")),
        ("Latest FCF", latest.get("free_cash_flow_cr", "N/A")),
    ]
    cols = st.columns(6)
    for col, (label, value) in zip(cols, metrics):
        with col:
            st.metric(label, value)
    if pe_ratio is not None:
        st.caption(f"Computed active P/E: {pe_ratio:.2f}")
    if price is not None:
        st.caption(f"Latest stock price used for computation: {price:.2f}")


def _render_charts(ticker: str) -> None:
    pl = _latest_pl_with_history(ticker)
    ratios = _latest_ratios(ticker)

    if go is None:
        return

    if not pl.empty:
        revenue_series = pd.to_numeric(pl.get("revenue"), errors="coerce")
        profit_series = pd.to_numeric(pl.get("net_income"), errors="coerce")
        fig = go.Figure()
        fig.add_trace(go.Bar(x=pl["financial_year"], y=revenue_series, name="Revenue"))
        fig.add_trace(go.Bar(x=pl["financial_year"], y=profit_series, name="Net Profit"))
        fig.update_layout(barmode="group", title="10-Year Revenue vs Net Profit", legend_title_text="")
        st.plotly_chart(fig, use_container_width=True)

    if not ratios.empty:
        fig2 = go.Figure()
        fig2.add_trace(
            go.Scatter(
                x=ratios["financial_year"],
                y=pd.to_numeric(ratios.get("return_on_equity_pct"), errors="coerce"),
                name="ROE",
                mode="lines+markers",
                yaxis="y1",
            )
        )
        fig2.add_trace(
            go.Scatter(
                x=ratios["financial_year"],
                y=pd.to_numeric(ratios.get("return_on_capital_employed_pct"), errors="coerce"),
                name="ROCE",
                mode="lines+markers",
                yaxis="y2",
            )
        )
        fig2.update_layout(
            title="ROE vs ROCE",
            yaxis=dict(title="ROE (%)"),
            yaxis2=dict(title="ROCE (%)", overlaying="y", side="right"),
            legend_title_text="",
        )
        st.plotly_chart(fig2, use_container_width=True)


def _render_qualitative_badges(company_id: int) -> None:
    pros, cons = _pros_cons(company_id)
    st.markdown("**Pros**")
    if pros:
        for item in pros:
            st.success(f"✓ {item}")
    else:
        st.info("No pros available.")
    st.markdown("**Cons**")
    if cons:
        for item in cons:
            st.error(f"✗ {item}")
    else:
        st.info("No cons available.")


def main() -> None:
    if st is None:
        return
    st.title("Company Profile")

    options = _company_options()
    search_text = st.text_input("Ticker search", placeholder="Search by ticker or company name")
    filtered = _resolve_company_label(search_text, options)
    labels = [item["label"] for item in filtered]

    selected_label = st.selectbox("Select ticker", labels) if labels else ""
    selected = next((item for item in filtered if item["label"] == selected_label), None)
    if not selected:
        st.error("Ticker not found — please try another.")
        return

    ticker = selected["ticker"]
    if not ticker:
        st.error("Ticker not found — please try another.")
        return

    companies = get_companies()
    profile = companies.loc[companies["ticker"].astype(str).eq(ticker)].head(1) if not companies.empty else pd.DataFrame()
    if profile.empty:
        st.error("Ticker not found — please try another.")
        return

    company = profile.iloc[0]
    _render_company_header(company)

    ratios = _latest_ratios(ticker)
    if ratios.empty:
        st.warning("No historical ratio data available for this ticker.")
    else:
        _render_kpis(ticker, ratios)

    _render_charts(ticker)
    _render_qualitative_badges(int(company["id"]))


if __name__ == "__main__":
    main()
