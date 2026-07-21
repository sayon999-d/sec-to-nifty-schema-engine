from __future__ import annotations

import logging
import re
import sqlite3
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "db" / "nifty100.db"
OUTPUT_DIR = PROJECT_ROOT / "output"
ANALYSIS_XLSX = PROJECT_ROOT / "analysis.xlsx"
PARSED_OUTPUT = OUTPUT_DIR / "analysis_parsed.csv"
FAILURE_OUTPUT = OUTPUT_DIR / "parse_failures.csv"
LOG_PATH = OUTPUT_DIR / "analysis_parse_warnings.log"

REGEX = re.compile(r"(\d+)\s*Years?:?\s*([\d.]+)%", re.IGNORECASE)
TARGET_METRICS = {
    "compounded_sales_growth",
    "compounded_profit_growth",
    "stock_price_cagr",
    "roe",
}

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


def _ensure_output_dir() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _safe_to_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return text


def _load_analysis_source() -> pd.DataFrame:
    if ANALYSIS_XLSX.exists():
        try:
            return pd.read_excel(ANALYSIS_XLSX)
        except Exception as exc:  # pragma: no cover - defensive I/O
            LOGGER.warning("analysis.xlsx read failed, falling back to database: %s", exc)

    with _connect() as conn:
        if "analysis" not in {
            row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()
        }:
            return pd.DataFrame()
        df = pd.read_sql_query(
            """
            SELECT company_id, financial_year, source_name, analyst_name, recommendation, target_price, risk_rating, source_url
            FROM analysis
            ORDER BY company_id, financial_year;
            """,
            conn,
        )
    if df.empty:
        return df
    df["source_blob"] = (
        df[["source_name", "analyst_name", "recommendation", "risk_rating", "source_url"]]
        .fillna("")
        .astype(str)
        .agg(" | ".join, axis=1)
    )
    return df


def _extract_rows(frame: pd.DataFrame) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    parsed_rows: list[dict[str, Any]] = []
    failure_rows: list[dict[str, Any]] = []
    text_columns = [
        col
        for col in frame.columns
        if frame[col].dtype == object or str(frame[col].dtype).startswith("string")
    ]
    if not text_columns:
        text_columns = list(frame.columns)

    for _, row in frame.iterrows():
        company_id = row.get("company_id")
        row_text = " | ".join(_safe_to_text(row.get(col)) for col in text_columns if _safe_to_text(row.get(col)))
        matched_any = False
        for metric in TARGET_METRICS:
            candidates = []
            if metric in row.index:
                candidates.append(row.get(metric))
            if "source_blob" in row.index:
                candidates.append(row.get("source_blob"))
            if "source_name" in row.index:
                candidates.append(row.get("source_name"))
            if "source_url" in row.index:
                candidates.append(row.get("source_url"))
            metric_text = " ".join(_safe_to_text(value) for value in candidates if _safe_to_text(value))
            match = REGEX.search(metric_text)
            if match:
                matched_any = True
                period_years = int(match.group(1))
                value_pct = float(match.group(2))
                parsed_rows.append(
                    {
                        "company_id": company_id,
                        "metric_type": metric,
                        "period_years": period_years,
                        "value_pct": value_pct,
                    }
                )
            else:
                failure_rows.append(
                    {
                        "company_id": company_id,
                        "metric_type": metric,
                        "input_text": metric_text[:500],
                        "reason": "regex_miss",
                    }
                )
        if not matched_any and row_text:
            LOGGER.warning("No regex match for company_id=%s", company_id)
    return parsed_rows, failure_rows


def _cross_validate(parsed: pd.DataFrame) -> None:
    if parsed.empty:
        return
    with _connect() as conn:
        if "financial_ratios" not in {
            row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()
        }:
            return
        ratios = pd.read_sql_query(
            """
            SELECT company_id, financial_year, revenue_cagr_5yr, pat_cagr_5yr, eps_cagr_5yr
            FROM financial_ratios
            ORDER BY company_id, financial_year;
            """,
            conn,
        )
    if ratios.empty:
        return

    metric_map = {
        "compounded_sales_growth": "revenue_cagr_5yr",
        "compounded_profit_growth": "pat_cagr_5yr",
        "stock_price_cagr": "eps_cagr_5yr",
        "roe": "return_on_equity_pct",
    }
    merged = parsed.merge(ratios, on="company_id", how="left")
    for _, row in merged.iterrows():
        metric_type = row.get("metric_type")
        source_col = metric_map.get(str(metric_type))
        if not source_col:
            continue
        source_value = row.get(source_col)
        parsed_value = row.get("value_pct")
        if pd.notna(parsed_value) and pd.notna(source_value) and abs(float(parsed_value) - float(source_value)) > 5.0:
            message = (
                f"Cross-validation divergence > 5% for company_id={row.get('company_id')} "
                f"metric={metric_type} parsed={parsed_value} source={source_value}"
            )
            LOGGER.warning(message)
            with LOG_PATH.open("a", encoding="utf-8") as handle:
                handle.write(message + "\n")


def parse_analysis(path: Path = ANALYSIS_XLSX) -> tuple[pd.DataFrame, pd.DataFrame]:
    _ensure_output_dir()
    frame = _load_analysis_source()
    if frame.empty:
        parsed = pd.DataFrame(columns=["company_id", "metric_type", "period_years", "value_pct"])
        failures = pd.DataFrame(columns=["company_id", "metric_type", "input_text", "reason"])
    else:
        parsed_rows, failure_rows = _extract_rows(frame)
        parsed = pd.DataFrame(parsed_rows, columns=["company_id", "metric_type", "period_years", "value_pct"])
        failures = pd.DataFrame(failure_rows, columns=["company_id", "metric_type", "input_text", "reason"])
        _cross_validate(parsed)
    parsed.to_csv(PARSED_OUTPUT, index=False)
    failures.to_csv(FAILURE_OUTPUT, index=False)
    return parsed, failures


def main() -> int:
    parse_analysis()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
