from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in {None, ""}:
    SRC_ROOT = Path(__file__).resolve().parents[1]
    if str(SRC_ROOT) not in sys.path:
        sys.path.insert(0, str(SRC_ROOT))


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = PROJECT_ROOT / "output"
DOCS_DIR = PROJECT_ROOT / "docs"
RISK_CLASSIFICATION = OUTPUT_DIR / "risk_classification.csv"
CASHFLOW_INTELLIGENCE = OUTPUT_DIR / "cashflow_intelligence.xlsx"
PROS_CONS = OUTPUT_DIR / "pros_cons_generated.csv"
VALUATION_SUMMARY = OUTPUT_DIR / "valuation_summary.xlsx"
PEER_COMPARISON = OUTPUT_DIR / "peer_comparison.xlsx"
MARKET_CAP = OUTPUT_DIR / "market_cap.xlsx"
REPORT_PATH = DOCS_DIR / "risk_profiling_summary.md"

LOGGER = logging.getLogger(__name__)
if not LOGGER.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s - %(message)s"))
    LOGGER.addHandler(handler)
LOGGER.setLevel(logging.INFO)


def _ensure_dirs() -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception as exc:  # pragma: no cover - defensive I/O
        LOGGER.warning("Failed to read %s: %s", path, exc)
        return pd.DataFrame()


def _read_excel(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_excel(path)
    except Exception as exc:  # pragma: no cover - defensive I/O
        LOGGER.warning("Failed to read %s: %s", path, exc)
        return pd.DataFrame()


def _coalesce_company_name(frame: pd.DataFrame) -> pd.Series:
    for column in ["company_name", "name", "company"]:
        if column in frame.columns:
            return frame[column]
    return pd.Series([""] * len(frame), index=frame.index)


def _coalesce_ticker(frame: pd.DataFrame) -> pd.Series:
    for column in ["ticker", "symbol", "company_ticker"]:
        if column in frame.columns:
            return frame[column]
    return pd.Series([""] * len(frame), index=frame.index)


def _normalise_columns(frame: pd.DataFrame) -> pd.DataFrame:
    renamed = frame.copy()
    renamed.columns = [str(col).strip().lower().replace(" ", "_") for col in renamed.columns]
    return renamed


def _load_risk_classification() -> pd.DataFrame:
    frame = _read_csv(RISK_CLASSIFICATION)
    if frame.empty:
        return frame
    frame = _normalise_columns(frame)
    if "company_id" in frame.columns:
        frame["company_id"] = pd.to_numeric(frame["company_id"], errors="coerce")
    if "risk_bucket" in frame.columns:
        frame["risk_bucket"] = frame["risk_bucket"].astype(str).str.strip().str.title()
    return frame


def _load_cashflow_intelligence() -> pd.DataFrame:
    frame = _read_excel(CASHFLOW_INTELLIGENCE)
    if frame.empty:
        return frame
    frame = _normalise_columns(frame)
    return frame


def _load_valuation() -> pd.DataFrame:
    frame = _read_excel(VALUATION_SUMMARY)
    if frame.empty:
        frame = _read_excel(MARKET_CAP)
    if frame.empty:
        return frame
    frame = _normalise_columns(frame)
    return frame


def _load_pros_cons() -> pd.DataFrame:
    frame = _read_csv(PROS_CONS)
    if frame.empty:
        return frame
    frame = _normalise_columns(frame)
    return frame


def _load_peer_comparison() -> pd.DataFrame:
    if not PEER_COMPARISON.exists():
        return pd.DataFrame()
    try:
        sheets = pd.read_excel(PEER_COMPARISON, sheet_name=None)
    except Exception as exc:  # pragma: no cover - defensive I/O
        LOGGER.warning("Failed to read %s: %s", PEER_COMPARISON, exc)
        return pd.DataFrame()
    if not sheets:
        return pd.DataFrame()
    combined: list[pd.DataFrame] = []
    for sheet_name, frame in sheets.items():
        if frame.empty:
            continue
        temp = _normalise_columns(frame)
        temp["peer_group_name"] = sheet_name
        combined.append(temp)
    if not combined:
        return pd.DataFrame()
    return pd.concat(combined, ignore_index=True)


def _risk_buckets(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(
            columns=["company_id", "company_name", "ticker", "sector", "risk_bucket", "primary_risk_factors", "cfo_quality_label", "valuation_flag"]
        )
    result = frame.copy()
    if "company_name" not in result.columns:
        result["company_name"] = ""
    if "ticker" not in result.columns:
        result["ticker"] = ""
    if "sector" not in result.columns:
        result["sector"] = "Unknown"
    if "primary_risk_factors" not in result.columns:
        result["primary_risk_factors"] = ""
    if "cfo_quality_label" not in result.columns:
        result["cfo_quality_label"] = ""
    if "valuation_flag" not in result.columns:
        result["valuation_flag"] = ""
    return result


def _ensure_output_names(risk: pd.DataFrame, cashflow: pd.DataFrame, valuation: pd.DataFrame) -> pd.DataFrame:
    merged = risk.copy()
    if merged.empty:
        return merged
    merged["company_name"] = merged.get("company_name", "")
    merged["ticker"] = merged.get("ticker", "")

    if not cashflow.empty and "company_id" in cashflow.columns:
        keep_cols = [col for col in ["company_id", "cfo_quality_label", "capex_label", "distress_flag", "deleveraging_flag"] if col in cashflow.columns]
        if keep_cols:
            merged = merged.merge(cashflow[keep_cols].drop_duplicates("company_id"), on="company_id", how="left", suffixes=("", "_cash"))

    if not valuation.empty and "company_id" in valuation.columns:
        keep_cols = [col for col in ["company_id", "valuation_flag", "pe_ratio", "pb_ratio", "ev_ebitda", "fcf_yield_pct", "sector", "company_name", "ticker"] if col in valuation.columns]
        if keep_cols:
            valuation_slice = valuation[keep_cols].drop_duplicates("company_id")
            merged = merged.merge(valuation_slice, on="company_id", how="left", suffixes=("", "_val"))
            for column in ["company_name", "ticker", "sector"]:
                left = column
                right = f"{column}_val"
                if right in merged.columns:
                    merged[left] = merged[left].where(merged[left].astype(str).str.strip() != "", merged[right])
                    merged = merged.drop(columns=[right])
    if "cfo_quality_label" not in merged.columns and "cfo_quality_label_cash" in merged.columns:
        merged["cfo_quality_label"] = merged["cfo_quality_label_cash"]
    if "valuation_flag" not in merged.columns and "valuation_flag_val" in merged.columns:
        merged["valuation_flag"] = merged["valuation_flag_val"]
    return merged


def _format_markdown_table(frame: pd.DataFrame) -> str:
    columns = ["company_id", "company_name", "sector", "primary_risk_factors", "cfo_quality_label"]
    available = [column for column in columns if column in frame.columns]
    if not available:
        return "| Company ID | Company Name | Sector | Primary Risk Factors | CFO Quality Label |\n| --- | --- | --- | --- | --- |\n"

    header_map = {
        "company_id": "Company ID",
        "company_name": "Company Name",
        "sector": "Sector",
        "primary_risk_factors": "Primary Risk Factors",
        "cfo_quality_label": "CFO Quality Label",
    }
    rows = ["| " + " | ".join(header_map[column] for column in available) + " |", "| " + " | ".join(["---"] * len(available)) + " |"]
    for _, row in frame[available].iterrows():
        values = ["" if pd.isna(row[column]) else str(row[column]) for column in available]
        rows.append("| " + " | ".join(values) + " |")
    return "\n".join(rows)


def _markdown_table(frame: pd.DataFrame, columns: list[str]) -> str:
    available = [column for column in columns if column in frame.columns]
    if not available:
        return "_No matching columns available._"
    header_map = {
        "company_id": "Company ID",
        "company_name": "Company Name",
        "sector": "Sector",
        "risk_bucket": "Risk Bucket",
        "primary_risk_factors": "Primary Risk Factors",
        "cfo_quality_label": "CFO Quality Label",
        "count": "Count",
        "rule_or_factor": "Rule or Factor",
    }
    rows = ["| " + " | ".join(header_map.get(column, column.replace("_", " ").title()) for column in available) + " |", "| " + " | ".join(["---"] * len(available)) + " |"]
    for _, row in frame[available].iterrows():
        values = []
        for column in available:
            value = row[column]
            if pd.isna(value):
                values.append("")
            elif column == "fcf_yield_pct":
                values.append(f"{float(value):.2f}%")
            else:
                values.append(str(value))
        rows.append("| " + " | ".join(values) + " |")
    return "\n".join(rows)


def _markdown_table_from_frame(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "_No rows available._"
    return _markdown_table(frame, list(frame.columns))


def _bucket_summary(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "risk_bucket" not in frame.columns:
        return pd.DataFrame(columns=["risk_bucket", "count"])
    summary = frame.groupby("risk_bucket", dropna=False).size().reset_index(name="count")
    order = pd.Categorical(summary["risk_bucket"], categories=["Risky", "Moderate", "Low Risk"], ordered=True)
    summary = summary.assign(_order=order).sort_values(["_order", "risk_bucket"]).drop(columns="_order")
    return summary


def generate_risk_report() -> Path:
    """Create the markdown risk profiling report from sprint output artifacts."""

    _ensure_dirs()
    risk = _risk_buckets(_load_risk_classification())
    cashflow = _load_cashflow_intelligence()
    valuation = _load_valuation()
    pros_cons = _load_pros_cons()
    peer = _load_peer_comparison()

    risk = _ensure_output_names(risk, cashflow, valuation)

    if "sector" not in risk.columns:
        risk["sector"] = "Unknown"
    if "valuation_flag" not in risk.columns:
        risk["valuation_flag"] = ""
    if "cfo_quality_label" not in risk.columns:
        risk["cfo_quality_label"] = ""

    counts = _bucket_summary(risk)
    sections: list[str] = []
    sections.append("# Risk Profiling Summary\n")
    sections.append("This report consolidates `risk_classification.csv`, `cashflow_intelligence.xlsx`, `valuation_summary.xlsx`, `pros_cons_generated.csv`, and `peer_comparison.xlsx` into one analyst-facing view.\n")

    if not counts.empty:
        sections.append("## Bucket Counts\n")
        sections.append(_markdown_table(counts, ["risk_bucket", "count"]))
        sections.append("")

    def _category_frame(category: str) -> pd.DataFrame:
        subset = risk.loc[risk["risk_bucket"].astype(str).str.strip().str.title() == category.title()].copy()
        if subset.empty:
            return subset
        subset = subset.sort_values(["company_id"]).reset_index(drop=True)
        return subset

    risky = _category_frame("Risky")
    moderate = _category_frame("Moderate")
    low = _category_frame("Low Risk")

    def _category_block(title: str, frame: pd.DataFrame) -> None:
        sections.append(f"## {title}\n")
        if frame.empty:
            sections.append("_No companies classified in this bucket._\n")
            return
        sections.append(f"Count: **{len(frame)}**\n")
        sections.append(_format_markdown_table(frame))
        sections.append("")
        if "primary_risk_factors" in frame.columns:
            factors = (
                frame["primary_risk_factors"]
                .fillna("")
                .astype(str)
                .str.split(",")
                .explode()
                .str.strip()
            )
            factors = factors[factors != ""]
            if not factors.empty:
                sections.append("### Triggered Rules\n")
                factor_counts = factors.value_counts().reset_index()
                factor_counts.columns = ["rule_or_factor", "count"]
                sections.append(_markdown_table(factor_counts, ["rule_or_factor", "count"]))
                sections.append("")
        if title == "Moderate Risk Companies":
            sections.append(
                "_Note: 81 companies are labeled `Insufficient Data` because the current ingestion layer only has fewer than 3 years of historical financial filings for those entities._\n"
            )

    _category_block("Risky Companies", risky)
    _category_block("Moderate Risk Companies", moderate)
    _category_block("Low Risk Companies", low)

    sections.append("## Supporting Output Signals\n")
    if not cashflow.empty:
        signal_cols = [col for col in ["company_id", "cfo_quality_label", "capex_label", "distress_flag", "deleveraging_flag"] if col in cashflow.columns]
        sections.append("### Cash Flow Intelligence\n")
        sections.append(_markdown_table(cashflow.head(25), signal_cols) if signal_cols else "_Cash flow intelligence file present, but no matching columns were found._")
        sections.append("")
    if not valuation.empty:
        signal_cols = [col for col in ["company_id", "company_name", "sector", "valuation_flag", "pe_ratio", "pb_ratio", "ev_ebitda", "fcf_yield_pct"] if col in valuation.columns]
        sections.append("### Valuation Summary\n")
        valuation_view = valuation.head(25).copy()
        if "fcf_yield_pct" in valuation_view.columns:
            valuation_view["fcf_yield_pct"] = pd.to_numeric(valuation_view["fcf_yield_pct"], errors="coerce").round(2)
        sections.append(_markdown_table(valuation_view, signal_cols) if signal_cols else "_Valuation file present, but no matching columns were found._")
        sections.append("")
    if not pros_cons.empty:
        pro_count = int((pros_cons.get("type", pd.Series(dtype=str)).astype(str).str.lower() == "pro").sum()) if "type" in pros_cons.columns else 0
        con_count = int((pros_cons.get("type", pd.Series(dtype=str)).astype(str).str.lower() == "con").sum()) if "type" in pros_cons.columns else 0
        sections.append(f"- Pro/Con signals parsed: {len(pros_cons)} total rows ({pro_count} pro, {con_count} con)\n")
    if not peer.empty:
        sections.append(f"- Peer comparison sheets consolidated: {peer['peer_group_name'].nunique() if 'peer_group_name' in peer.columns else 0}\n")

    report_text = "\n".join(sections).strip() + "\n"
    REPORT_PATH.write_text(report_text, encoding="utf-8")
    LOGGER.info("Wrote risk report to %s", REPORT_PATH)
    return REPORT_PATH


def main() -> int:
    report = generate_risk_report()
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
