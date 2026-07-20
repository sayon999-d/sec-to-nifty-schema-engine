from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

try:
    import streamlit as st
except Exception:  
    st = None

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from screener.engine import ScreenerEngine

SLIDER_KEYS = {
    "roe_min": "ROE min",
    "de_max": "D/E max",
    "fcf_min": "FCF min",
    "rev_cagr_min": "Revenue CAGR min",
    "pat_cagr_min": "PAT CAGR min",
    "opm_min": "OPM min",
    "pe_max": "P/E max",
    "pb_max": "P/B max",
    "dividend_yield_min": "Dividend Yield min",
    "icr_min": "ICR min",
}

PRESET_DEFAULTS: dict[str, dict[str, float]] = {
    "Quality Compounder": {
        "roe_min": 15.0,
        "de_max": 1.0,
        "fcf_min": 0.0,
        "rev_cagr_min": 10.0,
        "pat_cagr_min": 0.0,
        "opm_min": 0.0,
        "pe_max": 50.0,
        "pb_max": 10.0,
        "dividend_yield_min": 0.0,
        "icr_min": 1.5,
    },
    "Value Pick": {
        "roe_min": 0.0,
        "de_max": 2.0,
        "fcf_min": 0.0,
        "rev_cagr_min": 0.0,
        "pat_cagr_min": 0.0,
        "opm_min": 0.0,
        "pe_max": 20.0,
        "pb_max": 3.0,
        "dividend_yield_min": 1.0,
        "icr_min": 1.5,
    },
    "Growth Accelerator": {
        "roe_min": 0.0,
        "de_max": 2.0,
        "fcf_min": 0.0,
        "rev_cagr_min": 15.0,
        "pat_cagr_min": 20.0,
        "opm_min": 0.0,
        "pe_max": 60.0,
        "pb_max": 12.0,
        "dividend_yield_min": 0.0,
        "icr_min": 1.5,
    },
    "Dividend Champion": {
        "roe_min": 0.0,
        "de_max": 2.0,
        "fcf_min": 0.0,
        "rev_cagr_min": 0.0,
        "pat_cagr_min": 0.0,
        "opm_min": 0.0,
        "pe_max": 40.0,
        "pb_max": 8.0,
        "dividend_yield_min": 2.0,
        "icr_min": 1.5,
    },
    "Debt-Free Blue Chip": {
        "roe_min": 12.0,
        "de_max": 0.0,
        "fcf_min": 0.0,
        "rev_cagr_min": 0.0,
        "pat_cagr_min": 0.0,
        "opm_min": 0.0,
        "pe_max": 50.0,
        "pb_max": 10.0,
        "dividend_yield_min": 0.0,
        "icr_min": 1.5,
    },
    "Turnaround Watch": {
        "roe_min": -100.0,
        "de_max": 10.0,
        "fcf_min": 0.0,
        "rev_cagr_min": 10.0,
        "pat_cagr_min": -100.0,
        "opm_min": -100.0,
        "pe_max": 100.0,
        "pb_max": 20.0,
        "dividend_yield_min": 0.0,
        "icr_min": 1.0,
    },
}


def _init_state() -> None:
    for key, label in SLIDER_KEYS.items():
        if key not in st.session_state:
            st.session_state[key] = float(PRESET_DEFAULTS["Quality Compounder"].get(key, 0.0))
    if "preset" not in st.session_state:
        st.session_state["preset"] = "Quality Compounder"


def _apply_preset(name: str) -> None:
    preset = PRESET_DEFAULTS.get(name)
    if not preset:
        return
    for key, value in preset.items():
        st.session_state[key] = value
    st.session_state["preset"] = name


def _render_sidebar_controls() -> None:
    st.sidebar.header("Metric Filters")
    cols = st.sidebar.columns(2)
    preset_names = list(PRESET_DEFAULTS.keys())
    if cols[0].button("Quality Compounder"):
        _apply_preset("Quality Compounder")
    if cols[1].button("Value Pick"):
        _apply_preset("Value Pick")
    if st.sidebar.button("Growth Accelerator"):
        _apply_preset("Growth Accelerator")
    if st.sidebar.button("Dividend Champion"):
        _apply_preset("Dividend Champion")
    if st.sidebar.button("Debt-Free Blue Chip"):
        _apply_preset("Debt-Free Blue Chip")
    if st.sidebar.button("Turnaround Watch"):
        _apply_preset("Turnaround Watch")

    st.sidebar.markdown("---")
    st.sidebar.caption(f"Active preset: {st.session_state.get('preset', 'Quality Compounder')}")
    st.sidebar.slider("ROE min", -100.0, 100.0, float(st.session_state["roe_min"]), key="roe_min")
    st.sidebar.slider("D/E max", 0.0, 20.0, float(st.session_state["de_max"]), key="de_max")
    st.sidebar.slider("FCF min", -1000000.0, 1000000.0, float(st.session_state["fcf_min"]), key="fcf_min")
    st.sidebar.slider("Revenue CAGR min", -100.0, 100.0, float(st.session_state["rev_cagr_min"]), key="rev_cagr_min")
    st.sidebar.slider("PAT CAGR min", -100.0, 100.0, float(st.session_state["pat_cagr_min"]), key="pat_cagr_min")
    st.sidebar.slider("OPM min", -100.0, 100.0, float(st.session_state["opm_min"]), key="opm_min")
    st.sidebar.slider("P/E max", 0.0, 200.0, float(st.session_state["pe_max"]), key="pe_max")
    st.sidebar.slider("P/B max", 0.0, 50.0, float(st.session_state["pb_max"]), key="pb_max")
    st.sidebar.slider("Dividend Yield min", 0.0, 20.0, float(st.session_state["dividend_yield_min"]), key="dividend_yield_min")
    st.sidebar.slider("ICR min", 0.0, 50.0, float(st.session_state["icr_min"]), key="icr_min")


def _apply_filters(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    if result.empty:
        return result
    numeric_columns = [
        "return_on_equity_pct",
        "debt_to_equity",
        "free_cash_flow_cr",
        "revenue_cagr_5yr",
        "pat_cagr_5yr",
        "operating_profit_margin_pct",
        "pe_ratio",
        "pb_ratio",
        "dividend_yield_pct",
        "interest_coverage",
    ]
    for column in numeric_columns:
        if column in result.columns:
            result[column] = pd.to_numeric(result[column], errors="coerce")
    if "icr_numeric" not in result.columns and "interest_coverage" in result.columns:
        result["icr_numeric"] = pd.to_numeric(result["interest_coverage"], errors="coerce")
    result["icr_numeric"] = result["icr_numeric"].fillna(9999.0)

    def _max_filter(series: pd.Series, threshold: float) -> pd.Series:
        numeric = pd.to_numeric(series, errors="coerce")
        return numeric.isna() | (numeric <= threshold)

    def _min_filter(series: pd.Series, threshold: float) -> pd.Series:
        numeric = pd.to_numeric(series, errors="coerce")
        return numeric.isna() | (numeric >= threshold)

    mask = pd.Series(True, index=result.index)
    mask &= _min_filter(result["return_on_equity_pct"], float(st.session_state["roe_min"]))
    if "broad_sector" in result.columns:
        financials = result["broad_sector"].astype(str).eq("Financials")
        mask &= financials | _max_filter(result["debt_to_equity"], float(st.session_state["de_max"]))
    else:
        mask &= _max_filter(result["debt_to_equity"], float(st.session_state["de_max"]))
    mask &= _min_filter(result["free_cash_flow_cr"], float(st.session_state["fcf_min"]))
    mask &= _min_filter(result["revenue_cagr_5yr"], float(st.session_state["rev_cagr_min"]))
    mask &= _min_filter(result["pat_cagr_5yr"], float(st.session_state["pat_cagr_min"]))
    mask &= _min_filter(result["operating_profit_margin_pct"], float(st.session_state["opm_min"]))
    mask &= _max_filter(result["pe_ratio"], float(st.session_state["pe_max"]))
    mask &= _max_filter(result["pb_ratio"], float(st.session_state["pb_max"]))
    mask &= _min_filter(result["dividend_yield_pct"], float(st.session_state["dividend_yield_min"]))
    mask &= _min_filter(result["icr_numeric"], float(st.session_state["icr_min"]))

    filtered = result.loc[mask].copy()
    if "composite_quality_score" in filtered.columns:
        filtered["composite_quality_score"] = pd.to_numeric(filtered["composite_quality_score"], errors="coerce")
        filtered = filtered.sort_values("composite_quality_score", ascending=False)
    return filtered.reset_index(drop=True)


def main() -> None:
    if st is None:
        return
    st.title("Screener")
    _init_state()
    _render_sidebar_controls()

    engine = ScreenerEngine()
    full_frame = engine.load_frame()
    if full_frame.empty:
        st.warning("No screener data available.")
        return

    latest_frame = (
        full_frame.sort_values(["company_id", "year"])
        .groupby("company_id", as_index=False)
        .tail(1)
        .reset_index(drop=True)
    )
    filtered = _apply_filters(latest_frame)
    st.caption(f"{len(filtered)} companies match your filters")

    if filtered.empty:
        st.info("No results available for the selected filters.")
        return

    display_cols = [
        col
        for col in [
            "company_id",
            "company_name",
            "ticker",
            "year",
            "broad_sector",
            "return_on_equity_pct",
            "debt_to_equity",
            "free_cash_flow_cr",
            "revenue_cagr_5yr",
            "pat_cagr_5yr",
            "operating_profit_margin_pct",
            "pe_ratio",
            "pb_ratio",
            "dividend_yield_pct",
            "icr_numeric",
            "composite_quality_score",
        ]
        if col in filtered.columns
    ]
    st.dataframe(filtered[display_cols], use_container_width=True)

    csv = filtered.to_csv(index=False).encode("utf-8")
    preset_name = st.session_state.get("preset", "Quality Compounder")
    st.download_button(
        "Download CSV",
        csv,
        file_name=f"{preset_name.lower().replace(' ', '_')}.csv",
        mime="text/csv",
    )


if __name__ == "__main__":
    main()
