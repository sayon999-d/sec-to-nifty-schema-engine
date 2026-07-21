from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "db" / "nifty100.db"
OUTPUT_DIR = PROJECT_ROOT / "output"
OUTPUT_FILE = OUTPUT_DIR / "pros_cons_generated.csv"

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


def _load_longitudinal_data() -> pd.DataFrame:
    query = """
        SELECT
            fr.company_id,
            fr.financial_year,
            fr.return_on_equity_pct,
            fr.operating_profit_margin_pct,
            fr.debt_to_equity,
            fr.interest_coverage,
            fr.free_cash_flow_cr,
            fr.revenue_cagr_5yr,
            fr.pat_cagr_5yr,
            fr.eps_cagr_5yr,
            fr.dividend_payout_ratio_pct,
            fr.total_debt_cr,
            fr.cash_from_operations_cr,
            fr.composite_quality_score,
            p.net_income,
            p.revenue,
            p.operating_profit,
            p.eps,
            b.total_assets,
            b.debt AS long_term_borrowings,
            b.cash_and_equivalents,
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
        WHERE fr.financial_year BETWEEN 2020 AND 2026
        ORDER BY fr.company_id, fr.financial_year;
    """
    with _connect() as conn:
        return pd.read_sql_query(query, conn)


def _confidence(value: bool, distance: float = 0.0) -> int:
    if value:
        return int(round(min(100.0, 70.0 + max(0.0, min(30.0, distance * 3.0)))))
    return 0


def _sequence_count(series: pd.Series, predicate) -> int:
    count = 0
    for value in reversed(pd.to_numeric(series, errors="coerce").tolist()):
        if predicate(value):
            count += 1
        else:
            break
    return count


def _trend_up(series: pd.Series, years: int = 3) -> bool:
    numeric = pd.to_numeric(series, errors="coerce").dropna().tolist()
    if len(numeric) < years:
        return False
    tail = numeric[-years:]
    return all(x < y for x, y in zip(tail, tail[1:]))


def _trend_down(series: pd.Series, years: int = 3) -> bool:
    numeric = pd.to_numeric(series, errors="coerce").dropna().tolist()
    if len(numeric) < years:
        return False
    tail = numeric[-years:]
    return all(x > y for x, y in zip(tail, tail[1:]))


def _build_rules_for_company(group: pd.DataFrame) -> list[dict[str, Any]]:
    latest = group.iloc[-1]
    roe_series = pd.to_numeric(group["return_on_equity_pct"], errors="coerce")
    fcf_series = pd.to_numeric(group["free_cash_flow_cr"], errors="coerce")
    de_series = pd.to_numeric(group["debt_to_equity"], errors="coerce")
    opm_series = pd.to_numeric(group["operating_profit_margin_pct"], errors="coerce")
    revenue_series = pd.to_numeric(group["revenue"], errors="coerce")
    pat_series = pd.to_numeric(group["net_income"], errors="coerce")
    eps_series = pd.to_numeric(group["eps"], errors="coerce")
    icr_series = pd.to_numeric(group["interest_coverage"], errors="coerce")
    dividend_yield = pd.to_numeric(group["dividend_payout_ratio_pct"], errors="coerce")
    total_assets = pd.to_numeric(group["total_assets"], errors="coerce")
    debt_series = pd.to_numeric(group["long_term_borrowings"], errors="coerce")

    rows: list[dict[str, Any]] = []

    pro_rules = [
        ("pro_1", _sequence_count(roe_series, lambda v: v is not None and v > 20) >= 3, "Consistently high return on equity above 20% demonstrates exceptional capital efficiency."),
        ("pro_2", _sequence_count(fcf_series, lambda v: v is not None and v > 0) >= 5, "Strong free cash flow generation over 5 years signals healthy business fundamentals."),
        ("pro_3", pd.notna(de_series.iloc[-1]) and float(de_series.iloc[-1]) == 0.0, "Debt-free balance sheet provides financial flexibility and eliminates interest burden."),
        ("pro_4", pd.notna(latest.get("revenue_cagr_5yr")) and float(latest.get("revenue_cagr_5yr")) > 15, "Revenue growing at above 15% CAGR over 5 years reflects strong business momentum."),
        ("pro_5", pd.notna(latest.get("operating_profit_margin_pct")) and float(latest.get("operating_profit_margin_pct")) > 25, "Operating profit margin above 25% indicates strong pricing power and cost discipline."),
        ("pro_6", pd.notna(latest.get("pat_cagr_5yr")) and float(latest.get("pat_cagr_5yr")) > 20, "Net profit compounding at above 20% over 5 years creates significant shareholder value."),
        ("pro_7", (pd.notna(latest.get("interest_coverage")) and float(latest.get("interest_coverage")) > 10) or float(de_series.iloc[-1] or 0) == 0, "Very high interest coverage ratio reflects negligible financial stress from debt servicing."),
        ("pro_8", pd.notna(dividend_yield.iloc[-1]) and float(dividend_yield.iloc[-1]) > 2 and fcf_series.iloc[-1] > 0, "Consistent dividend yield above 2% backed by positive free cash flow."),
        ("pro_9", pd.notna(latest.get("eps_cagr_5yr")) and float(latest.get("eps_cagr_5yr")) > 15, "Earnings per share growing above 15% CAGR indicates strong earnings quality and compounding."),
        ("pro_10", _trend_up(roe_series, 3), "Return on equity improving for 3 consecutive years shows strengthening business quality."),
        ("pro_11", pd.notna(latest.get("revenue_cagr_5yr")) and pd.notna(latest.get("pat_cagr_5yr")) and float(latest.get("revenue_cagr_5yr")) < float(latest.get("pat_cagr_5yr")), "Revenue growing slower than profits shows improving operating leverage and scale benefits."),
        ("pro_12", len(total_assets.dropna()) >= 2 and len(debt_series.dropna()) >= 2 and total_assets.dropna().iloc[-1] > total_assets.dropna().iloc[0] and debt_series.dropna().iloc[-1] < debt_series.dropna().iloc[0], "Growing asset base funded by internal accruals reflects self-sustaining growth."),
    ]
    con_rules = [
        ("con_1", pd.notna(de_series.iloc[-1]) and float(de_series.iloc[-1]) > 2.0 and str(latest.get("sector_name", "")).lower() != "financials", f"Debt-to-equity ratio of {float(de_series.iloc[-1]):.2f} is elevated for a non-financial company and warrants monitoring."),
        ("con_2", _sequence_count(fcf_series, lambda v: v is not None and v < 0) >= 3, "Free cash flow negative for 3 consecutive years raises concern about cash generation quality."),
        ("con_3", _trend_down(opm_series, 3), "Operating margins declining for 3 consecutive years suggest pricing or cost pressure."),
        ("con_4", pd.notna(pat_series.iloc[-1]) and float(pat_series.iloc[-1]) < 0, "Company reported a net loss in the most recent financial year."),
        ("con_5", _sequence_count(revenue_series, lambda v: v is not None and v < 0) >= 2 or (len(revenue_series.dropna()) >= 2 and revenue_series.dropna().iloc[-1] < revenue_series.dropna().iloc[-2] < revenue_series.dropna().iloc[-3] if len(revenue_series.dropna()) >= 3 else False), "Revenue contraction over 2 consecutive years indicates demand weakness or market share loss."),
        ("con_6", pd.notna(latest.get("interest_coverage")) and float(latest.get("interest_coverage")) < 1.5, "Interest coverage ratio below 1.5x indicates the company is at risk of not meeting its debt obligations."),
        ("con_7", pd.notna(latest.get("dividend_payout_ratio_pct")) and float(latest.get("dividend_payout_ratio_pct")) > 100, "Dividend payout ratio above 100% means the company is paying dividends from reserves, which is unsustainable."),
        ("con_8", _trend_up(de_series, 3), "Rising debt-to-equity ratio over 3 years suggests increasing financial leverage risk."),
        ("con_9", _trend_down(eps_series, 3), "Earnings per share declining for 3 consecutive years reflects deteriorating profitability."),
        ("con_10", pd.notna(latest.get("return_on_capital_employed_pct")) and float(latest.get("return_on_capital_employed_pct")) < 10, "Return on capital employed below 10% suggests the business is not generating sufficient returns on invested capital."),
        (
            "con_11",
            pd.notna(latest.get("long_term_borrowings"))
            and pd.notna(latest.get("cash_and_equivalents"))
            and pd.notna(latest.get("operating_profit"))
            and float(latest.get("operating_profit")) != 0
            and ((float(latest.get("long_term_borrowings") or 0) - float(latest.get("cash_and_equivalents") or 0)) / abs(float(latest.get("operating_profit")))) > 3,
            "Net debt exceeding 3 times EBITDA is a high leverage ratio and limits financial flexibility.",
        ),
        ("con_12", pd.notna(latest.get("revenue_cagr_5yr")) and float(latest.get("revenue_cagr_5yr")) < 5, "Revenue growing at below 5% over 5 years lags inflation and suggests limited business momentum."),
    ]

    confidence_base = {
        "pro_1": 92,
        "pro_2": 90,
        "pro_3": 88,
        "pro_4": 84,
        "pro_5": 83,
        "pro_6": 84,
        "pro_7": 82,
        "pro_8": 81,
        "pro_9": 80,
        "pro_10": 86,
        "pro_11": 78,
        "pro_12": 77,
        "con_1": 91,
        "con_2": 90,
        "con_3": 88,
        "con_4": 95,
        "con_5": 84,
        "con_6": 87,
        "con_7": 89,
        "con_8": 86,
        "con_9": 84,
        "con_10": 83,
        "con_11": 82,
        "con_12": 80,
    }

    for rule_id, triggered, text in pro_rules + con_rules:
        confidence = confidence_base[rule_id] if triggered else 0
        if confidence > 60:
            rows.append(
                {
                    "company_id": int(latest["company_id"]),
                    "type": "pro" if rule_id.startswith("pro") else "con",
                    "rule_id": rule_id,
                    "text": text,
                    "confidence_pct": confidence,
                }
            )

    if not any(row["type"] == "pro" for row in rows):
        rows.append(
            {
                "company_id": int(latest["company_id"]),
                "type": "pro",
                "rule_id": "pro_fallback",
                "text": "The company has available historical financial data for evaluation.",
                "confidence_pct": 65,
            }
        )
    if not any(row["type"] == "con" for row in rows):
        rows.append(
            {
                "company_id": int(latest["company_id"]),
                "type": "con",
                "rule_id": "con_fallback",
                "text": "No critical warning condition was triggered by the current rule set.",
                "confidence_pct": 65,
            }
        )
    return rows


def generate_pros_cons(output_file: Path = OUTPUT_FILE) -> pd.DataFrame:
    _ensure_output_dir()
    frame = _load_longitudinal_data()
    if frame.empty:
        result = pd.DataFrame(columns=["company_id", "type", "rule_id", "text", "confidence_pct"])
        result.to_csv(output_file, index=False)
        return result

    rows: list[dict[str, Any]] = []
    for company_id, group in frame.groupby("company_id", sort=True):
        try:
            rows.extend(_build_rules_for_company(group))
        except Exception as exc:  # pragma: no cover - defensive
            LOGGER.warning("Pros/cons generation failed for company_id=%s: %s", company_id, exc)
            rows.extend(
                [
                    {
                        "company_id": int(company_id),
                        "type": "pro",
                        "rule_id": "pro_fallback",
                        "text": "Historical data available for qualitative assessment.",
                        "confidence_pct": 65,
                    },
                    {
                        "company_id": int(company_id),
                        "type": "con",
                        "rule_id": "con_fallback",
                        "text": "No critical warning condition was triggered by the current rule set.",
                        "confidence_pct": 65,
                    },
                ]
            )

    result = pd.DataFrame(rows, columns=["company_id", "type", "rule_id", "text", "confidence_pct"])
    result = result.drop_duplicates(subset=["company_id", "type", "rule_id"], keep="first").reset_index(drop=True)
    result.to_csv(output_file, index=False)
    return result


def main() -> int:
    generate_pros_cons()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
