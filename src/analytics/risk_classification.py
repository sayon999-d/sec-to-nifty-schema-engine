from __future__ import annotations

import logging
import sqlite3
import sys
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in {None, ""}:
    SRC_ROOT = Path(__file__).resolve().parents[1]
    if str(SRC_ROOT) not in sys.path:
        sys.path.insert(0, str(SRC_ROOT))
    from analytics.common import as_float, is_financials_sector
else:
    from .common import as_float, is_financials_sector


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "db" / "nifty100.db"
OUTPUT_DIR = PROJECT_ROOT / "output"
CASHFLOW_XLSX = OUTPUT_DIR / "cashflow_intelligence.xlsx"
VALUATION_SUMMARY_XLSX = OUTPUT_DIR / "valuation_summary.xlsx"
MARKET_CAP_XLSX = OUTPUT_DIR / "market_cap.xlsx"
DISTRESS_ALERTS_CSV = OUTPUT_DIR / "distress_alerts.csv"
RISK_CLASSIFICATION_CSV = OUTPUT_DIR / "risk_classification.csv"

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


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table});").fetchall()
    return {str(row[1]) for row in rows}


def _load_companies() -> pd.DataFrame:
    with _connect() as conn:
        sector_cols = _table_columns(conn, "sectors")
        fr_cols = _table_columns(conn, "financial_ratios")

        sector_expr = "NULL"
        if "sector" in sector_cols:
            sector_expr = "s.sector"
        elif "broad_sector" in sector_cols:
            sector_expr = "s.broad_sector"
        elif "sector_name" in sector_cols:
            sector_expr = "s.sector_name"

        fr_sector_expr = "NULL"
        if "sector" in fr_cols:
            fr_sector_expr = "fr.sector"
        elif "broad_sector" in fr_cols:
            fr_sector_expr = "fr.broad_sector"
        elif "sector_name" in fr_cols:
            fr_sector_expr = "fr.sector_name"

        return pd.read_sql_query(
            f"""
            SELECT
                c.id AS company_id,
                c.company_name,
                c.ticker,
                COALESCE({sector_expr}, {fr_sector_expr}, 'Unknown') AS sector
            FROM companies c
            LEFT JOIN sectors s
              ON s.company_id = c.id
            LEFT JOIN (
                SELECT company_id, MAX(financial_year) AS financial_year
                FROM financial_ratios
                GROUP BY company_id
            ) fr_year
              ON fr_year.company_id = c.id
            LEFT JOIN financial_ratios fr
              ON fr.company_id = fr_year.company_id
             AND fr.financial_year = fr_year.financial_year
            ORDER BY c.id;
            """,
            conn,
        )


def _read_optional_frame(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_excel(path)
    except Exception as exc:  # pragma: no cover - defensive I/O
        LOGGER.warning("Failed to read %s: %s", path, exc)
        return pd.DataFrame()


def _load_cashflow_intelligence() -> pd.DataFrame:
    frame = _read_optional_frame(CASHFLOW_XLSX)
    if frame.empty:
        return frame
    cols = {str(col).strip().lower(): col for col in frame.columns}
    rename_map: dict[str, str] = {}
    for source, target in [
        ("company_id", "company_id"),
        ("sector", "sector"),
        ("cfo_quality_label", "cfo_quality_label"),
        ("capex_label", "capex_label"),
        ("fcf_cagr_5yr", "fcf_cagr_5yr"),
        ("fcf_conversion_pct", "fcf_conversion_pct"),
        ("distress_flag", "distress_flag"),
        ("deleveraging_flag", "deleveraging_flag"),
        ("capital_allocation_label", "capital_allocation_label"),
    ]:
        if source in cols:
            rename_map[cols[source]] = target
    if rename_map:
        frame = frame.rename(columns=rename_map)
    return frame


def _load_valuation() -> pd.DataFrame:
    frame = _read_optional_frame(VALUATION_SUMMARY_XLSX)
    if frame.empty:
        frame = _read_optional_frame(MARKET_CAP_XLSX)
    if frame.empty:
        return frame
    cols = {str(col).strip().lower(): col for col in frame.columns}
    rename_map: dict[str, str] = {}
    for source, target in [
        ("company_id", "company_id"),
        ("company_name", "company_name"),
        ("sector", "sector"),
        ("flag", "valuation_flag"),
        ("pe_vs_sector_median_pct", "pe_vs_sector_median_pct"),
        ("p/e", "pe_ratio"),
        ("pe_ratio", "pe_ratio"),
        ("p/b", "pb_ratio"),
        ("pb_ratio", "pb_ratio"),
        ("ev/ebitda", "ev_ebitda"),
        ("ev_ebitda", "ev_ebitda"),
        ("fcf_yield_pct", "fcf_yield_pct"),
        ("5yr_median_pe", "median_pe_5yr"),
    ]:
        if source in cols:
            rename_map[cols[source]] = target
    if rename_map:
        frame = frame.rename(columns=rename_map)
    if "valuation_flag" not in frame.columns:
        frame["valuation_flag"] = "N/A"
    return frame


def _load_distress_alerts() -> pd.DataFrame:
    frame = pd.read_csv(DISTRESS_ALERTS_CSV) if DISTRESS_ALERTS_CSV.exists() else pd.DataFrame()
    if frame.empty:
        return frame
    cols = {str(col).strip().lower(): col for col in frame.columns}
    rename_map = {}
    for source in ["company_id", "cfo", "cff", "net_profit", "sector"]:
        if source in cols:
            rename_map[cols[source]] = source
    if rename_map:
        frame = frame.rename(columns=rename_map)
    return frame


def _streak_negative_fcf(conn: sqlite3.Connection, company_id: int) -> bool:
    frame = pd.read_sql_query(
        """
        SELECT financial_year, COALESCE(net_cash_from_operations, 0) + COALESCE(net_cash_from_investing, 0) AS fcf
        FROM cashflow
        WHERE company_id = ? AND financial_year BETWEEN 2020 AND 2026
        ORDER BY financial_year ASC;
        """,
        conn,
        params=(company_id,),
    )
    if frame.empty or len(frame) < 3:
        return False
    values = pd.to_numeric(frame["fcf"], errors="coerce").fillna(0).tolist()
    streak = 0
    for value in reversed(values):
        if value < 0:
            streak += 1
        else:
            break
    return streak >= 3


def _has_rising_debt(conn: sqlite3.Connection, company_id: int) -> bool:
    frame = pd.read_sql_query(
        """
        SELECT financial_year, debt
        FROM balancesheet
        WHERE company_id = ? AND financial_year BETWEEN 2020 AND 2026
        ORDER BY financial_year ASC;
        """,
        conn,
        params=(company_id,),
    )
    if frame.empty or len(frame) < 2:
        return False
    debt = pd.to_numeric(frame["debt"], errors="coerce").dropna().tolist()
    if len(debt) < 2:
        return False
    return debt[-1] > debt[-2]


def _derive_low_risk(row: pd.Series) -> bool:
    cfo_label = str(row.get("cfo_quality_label", "")).strip().lower()
    valuation_flag = str(row.get("valuation_flag", "")).strip().lower()
    valuation_pe = as_float(row.get("pe_vs_sector_median_pct"))
    de_value = as_float(row.get("de_ratio"))
    fcf_positive = as_float(row.get("fcf_cagr_5yr")) is not None or str(row.get("fcf_positive", "")).lower() == "true"

    return (
        cfo_label == "high quality"
        and (de_value is not None and de_value < 0.5 or str(row.get("debt_free", "")).strip().lower() == "yes")
        and fcf_positive
        and valuation_flag in {"fair", "discount"}
        and (valuation_pe is None or valuation_pe <= 0)
    )


def _row_value(row: pd.Series | None, key: str, default: Any = "") -> Any:
    if row is None:
        return default
    try:
        return row.get(key, default)
    except Exception:
        return default


def _classify_company(
    company: pd.Series,
    cashflow: pd.Series | None,
    valuation: pd.Series | None,
    distress_alerts: pd.DataFrame,
    conn: sqlite3.Connection,
) -> tuple[str, list[str]]:
    factors: list[str] = []
    company_id = int(company["company_id"])
    sector = str(company.get("sector") or "").strip()
    cfo_quality_label = str(_row_value(cashflow, "cfo_quality_label", "")).strip()
    capex_label = str(_row_value(cashflow, "capex_label", "")).strip()
    valuation_flag = str(_row_value(valuation, "valuation_flag", "")).strip()

    distress_row = distress_alerts.loc[distress_alerts["company_id"] == company_id] if not distress_alerts.empty and "company_id" in distress_alerts.columns else pd.DataFrame()
    distress_signal = False
    if not distress_row.empty:
        distress_signal = True
        factors.append("Operational Distress")
        if "cfo" in distress_row.columns and "cff" in distress_row.columns:
            cfo_val = as_float(distress_row.iloc[0].get("cfo"))
            cff_val = as_float(distress_row.iloc[0].get("cff"))
            if cfo_val is not None and cff_val is not None and cfo_val < 0 and cff_val > 0:
                factors.append("CFO Burn With Financing Inflow")

    if cfo_quality_label.lower() == "accrual risk":
        factors.append("Accrual Risk")
    elif cfo_quality_label.lower() == "moderate":
        factors.append("Moderate Cash Flow Quality")

    de_ratio = as_float(company.get("de_ratio"))
    if de_ratio is not None and not is_financials_sector(sector) and de_ratio > 2.0:
        factors.append("High Leverage")

    net_debt_to_ebitda = as_float(company.get("net_debt_to_ebitda"))
    if net_debt_to_ebitda is not None and net_debt_to_ebitda > 3.0:
        factors.append("High Net Debt")

    if valuation_flag.lower() == "caution":
        factors.append("Overvaluation Caution")

    if _streak_negative_fcf(conn, company_id):
        factors.append("Consecutive Negative FCF")

    if capex_label.lower() == "capital intensive":
        factors.append("High CapEx Intensity")

    pe_vs_sector = as_float(_row_value(valuation, "pe_vs_sector_median_pct", None))
    if valuation_flag.lower() == "fair" and pe_vs_sector is not None:
        if pe_vs_sector < 0 and (as_float(company.get("revenue_cagr_5yr")) or 0.0) < 5.0:
            factors.append("Fair Valuation With Sluggish Growth")

    if _has_rising_debt(conn, company_id):
        factors.append("Rising Leverage")

    if not factors and _derive_low_risk(company):
        return "Low Risk", ["High CFO Quality", "Low Debt", "Positive FCF", "Fair Or Discount Valuation"]

    risky_triggers = {
        "Operational Distress",
        "Accrual Risk",
        "High Leverage",
        "High Net Debt",
        "Overvaluation Caution",
        "Consecutive Negative FCF",
    }
    if any(trigger in factors for trigger in risky_triggers):
        return "Risky", factors

    moderate_triggers = {
        "High CapEx Intensity",
        "Moderate Cash Flow Quality",
        "Fair Valuation With Sluggish Growth",
        "Rising Leverage",
    }
    if any(trigger in factors for trigger in moderate_triggers):
        return "Moderate", factors

    if cfo_quality_label.lower() == "high quality":
        factors.append("High CFO Quality")
    if valuation_flag.lower() in {"fair", "discount"}:
        factors.append("Fair Or Discount Valuation")
    if as_float(company.get("de_ratio")) is not None and as_float(company.get("de_ratio")) < 0.5:
        factors.append("Low Debt")

    if factors:
        if any(item in factors for item in ["High CFO Quality", "Low Debt", "Fair Or Discount Valuation"]):
            return "Low Risk", factors

    return "Moderate", factors or ["Insufficient Data"]


def build_risk_classification(output_path: Path = RISK_CLASSIFICATION_CSV) -> pd.DataFrame:

    _ensure_output_dir()
    companies = _load_companies()
    cashflow = _load_cashflow_intelligence()
    valuation = _load_valuation()
    distress_alerts = _load_distress_alerts()

    if companies.empty:
        empty = pd.DataFrame(
            columns=[
                "company_id",
                "company_name",
                "sector",
                "risk_bucket",
                "primary_risk_factors",
                "cfo_quality_label",
                "valuation_flag",
            ]
        )
        empty.to_csv(output_path, index=False)
        return empty

    with _connect() as conn:
        risk_rows: list[dict[str, Any]] = []
        for _, company in companies.iterrows():
            company_id = int(company["company_id"])

            cashflow_row = None
            if not cashflow.empty and "company_id" in cashflow.columns:
                subset = cashflow.loc[cashflow["company_id"] == company_id]
                if not subset.empty:
                    cashflow_row = subset.iloc[0]

            valuation_row = None
            if not valuation.empty and "company_id" in valuation.columns:
                subset = valuation.loc[valuation["company_id"] == company_id]
                if not subset.empty:
                    valuation_row = subset.iloc[0]

            bucket, factors = _classify_company(company, cashflow_row, valuation_row, distress_alerts, conn)
            risk_rows.append(
                {
                    "company_id": company_id,
                    "company_name": company.get("company_name", ""),
                    "sector": company.get("sector", "Unknown"),
                    "risk_bucket": bucket,
                    "primary_risk_factors": ", ".join(dict.fromkeys(factors)),
                    "cfo_quality_label": "" if cashflow_row is None else cashflow_row.get("cfo_quality_label", ""),
                    "valuation_flag": "" if valuation_row is None else valuation_row.get("valuation_flag", ""),
                }
            )

    result = pd.DataFrame(risk_rows).sort_values(["risk_bucket", "company_id"]).reset_index(drop=True)
    result.to_csv(output_path, index=False)
    LOGGER.info("Wrote risk classification to %s", output_path)
    return result


def main() -> int:
    build_risk_classification()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
