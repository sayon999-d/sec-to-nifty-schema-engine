from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from openpyxl import Workbook

if __package__ in {None, ""}:
    import sys

    SRC_ROOT = Path(__file__).resolve().parents[1]
    if str(SRC_ROOT) not in sys.path:
        sys.path.insert(0, str(SRC_ROOT))
    from analytics.common import MetricOutcome, as_float, rolling_average
else:
    from .common import MetricOutcome, as_float, rolling_average

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "db" / "nifty100.db"
OUTPUT_DIR = PROJECT_ROOT / "output"
OUTPUT_XLSX = OUTPUT_DIR / "cashflow_intelligence.xlsx"
DISTRESS_ALERTS = OUTPUT_DIR / "distress_alerts.csv"

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


def _historical_frame() -> pd.DataFrame:
    query = """
        SELECT
            cf.company_id,
            cf.financial_year AS year,
            cf.net_cash_from_operations AS cfo,
            cf.net_cash_from_investing AS cfi,
            cf.net_cash_from_financing AS cff,
            cf.net_cash_flow,
            cf.interest_paid,
            cf.dividend_paid,
            p.revenue,
            p.operating_profit,
            p.net_income,
            p.eps,
            b.debt AS long_term_borrowings,
            b.total_assets,
            b.total_equity,
            s.sector_name AS sector
        FROM cashflow cf
        LEFT JOIN profitandloss p
          ON p.company_id = cf.company_id
         AND p.financial_year = cf.financial_year
        LEFT JOIN balancesheet b
          ON b.company_id = cf.company_id
         AND b.financial_year = cf.financial_year
        LEFT JOIN sectors s
          ON s.company_id = cf.company_id
        WHERE cf.financial_year BETWEEN 2020 AND 2026
        ORDER BY cf.company_id, cf.financial_year;
    """
    with _connect() as conn:
        return pd.read_sql_query(query, conn)


def _latest_market_frame() -> pd.DataFrame:
    frame = _historical_frame()
    if frame.empty:
        return frame
    return frame.sort_values(["company_id", "year"]).groupby("company_id", as_index=False).tail(1).reset_index(drop=True)


def free_cash_flow(operating_activity: float | int | None, investing_activity: float | int | None) -> MetricOutcome:
    return MetricOutcome(value=(as_float(operating_activity) or 0.0) + (as_float(investing_activity) or 0.0))


def cfo_quality_score(cfo_values: Iterable[float | int | None], pat_values: Iterable[float | int | None], *, window: int = 5) -> MetricOutcome:
    ratios: list[float] = []
    for cfo, pat in zip(list(cfo_values)[-window:], list(pat_values)[-window:]):
        pat_value = as_float(pat)
        if pat_value in {None, 0}:
            continue
        ratios.append((as_float(cfo) or 0.0) / pat_value)
    avg = rolling_average(ratios)
    if avg is None:
        return MetricOutcome(value=None)
    if avg > 1.0:
        label = "High Quality"
    elif avg >= 0.5:
        label = "Moderate"
    else:
        label = "Accrual Risk"
    return MetricOutcome(value=avg, label=label)


def capex_intensity(investing_activity: float | int | None, sales: float | int | None) -> MetricOutcome:
    sales_value = as_float(sales)
    if sales_value in {None, 0}:
        return MetricOutcome(value=None)
    ratio = abs(as_float(investing_activity) or 0.0) / sales_value * 100.0
    if ratio < 3.0:
        label = "Asset Light"
    elif ratio <= 8.0:
        label = "Moderate"
    else:
        label = "Capital Intensive"
    return MetricOutcome(value=ratio, label=label)


def fcf_conversion_rate(fcf: float | int | None, operating_profit: float | int | None) -> MetricOutcome:
    op_profit = as_float(operating_profit)
    if op_profit in {None, 0}:
        return MetricOutcome(value=None)
    return MetricOutcome(value=((as_float(fcf) or 0.0) / op_profit) * 100.0)


def _cagr_from_series(series: pd.Series) -> float | None:
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    if len(numeric) < 2:
        return None
    start = numeric.iloc[0]
    end = numeric.iloc[-1]
    years = len(numeric) - 1
    if start in {None, 0} or years <= 0:
        return None
    try:
        return ((end / start) ** (1 / years) - 1) * 100.0
    except Exception:
        return None


def _classify_capital_allocation(row: pd.Series) -> str:
    if row.get("cfo") > 0 and row.get("cfi") < 0 and row.get("cff") < 0:
        return "Reinvestor"
    if row.get("cfo") > 0 and row.get("cfi") > 0 and row.get("cff") < 0:
        return "Liquidating Assets"
    if row.get("cfo") < 0 and row.get("cfi") > 0 and row.get("cff") > 0:
        return "Distress Signal"
    if row.get("cfo") < 0 and row.get("cfi") < 0 and row.get("cff") > 0:
        return "Growth Funded by Debt"
    if row.get("cfo") > 0 and row.get("cfi") > 0 and row.get("cff") > 0:
        return "Cash Accumulator"
    if row.get("cfo") < 0 and row.get("cfi") < 0 and row.get("cff") < 0:
        return "Pre-Revenue"
    return "Mixed"


def classify_capital_allocation(
    cfo: float | int | None,
    cfi: float | int | None,
    cff: float | int | None,
    *,
    cfo_pat_ratio: float | int | None = None,
) -> MetricOutcome:
    pattern = _classify_capital_allocation(pd.Series({"cfo": cfo, "cfi": cfi, "cff": cff}))
    if pattern == "Reinvestor" and (as_float(cfo_pat_ratio) or 0.0) > 1.0:
        pattern = "Shareholder Returns"
    return MetricOutcome(value=None, label=pattern)


def _build_latest_summary(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=[
            "company_id",
            "sector",
            "cfo_quality_score",
            "cfo_quality_label",
            "capex_intensity_pct",
            "capex_label",
            "fcf_cagr_5yr",
            "fcf_conversion_pct",
            "distress_flag",
            "deleveraging_flag",
            "capital_allocation_label",
        ])

    rows: list[dict[str, Any]] = []
    for company_id, group in frame.groupby("company_id", sort=True):
        ordered = group.sort_values("year")
        latest = ordered.iloc[-1]
        cfo_series = ordered["cfo"].tolist()
        pat_series = ordered["net_income"].tolist()
        cfo_quality = cfo_quality_score(cfo_series, pat_series, window=5)
        capex = capex_intensity(latest.get("cfi"), latest.get("revenue"))
        fcf = free_cash_flow(latest.get("cfo"), latest.get("cfi"))
        fcf_series = (pd.to_numeric(ordered["cfo"], errors="coerce").fillna(0) + pd.to_numeric(ordered["cfi"], errors="coerce").fillna(0))
        fcf_cagr = _cagr_from_series(fcf_series)
        fcf_conversion = fcf_conversion_rate(fcf.value, latest.get("operating_profit"))
        distress_flag = int((as_float(latest.get("cfo")) or 0.0) < 0 and (as_float(latest.get("cff")) or 0.0) > 0)
        debt_series = pd.to_numeric(ordered["long_term_borrowings"], errors="coerce")
        deleveraging_flag = int((as_float(latest.get("cff")) or 0.0) < 0 and len(debt_series.dropna()) >= 2 and debt_series.dropna().iloc[-1] < debt_series.dropna().iloc[-2])
        rows.append(
            {
                "company_id": int(company_id),
                "sector": latest.get("sector", "Unknown"),
                "cfo_quality_score": round(float(cfo_quality.value or 0.0), 4) if cfo_quality.value is not None else None,
                "cfo_quality_label": cfo_quality.label,
                "capex_intensity_pct": round(float(capex.value or 0.0), 4) if capex.value is not None else None,
                "capex_label": capex.label,
                "fcf_cagr_5yr": round(float(fcf_cagr), 4) if fcf_cagr is not None else None,
                "fcf_conversion_pct": round(float(fcf_conversion.value or 0.0), 4) if fcf_conversion.value is not None else None,
                "distress_flag": distress_flag,
                "deleveraging_flag": deleveraging_flag,
                "capital_allocation_label": _classify_capital_allocation(latest),
            }
        )

    summary = pd.DataFrame(rows)
    summary = summary.sort_values("company_id").reset_index(drop=True)
    return summary


def _write_excel(summary: pd.DataFrame, output_path: Path = OUTPUT_XLSX) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Cash Flow Intelligence"
    ws.append(list(summary.columns))
    for row in summary.itertuples(index=False):
        ws.append(list(row))
    for cell in ws[1]:
        cell.style = "Headline 1"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)


def _pattern_changes() -> pd.DataFrame:
    from .allocation import build_pattern_changes
    return build_pattern_changes()


def build_cashflow_intelligence(output_xlsx: Path = OUTPUT_XLSX, distress_csv: Path = DISTRESS_ALERTS) -> pd.DataFrame:
    _ensure_output_dir()
    frame = _latest_market_frame()
    summary = _build_latest_summary(frame)
    _write_excel(summary, output_xlsx)

    distress = frame.sort_values(["company_id", "year"]).groupby("company_id", as_index=False).tail(1).copy()
    distress["distress_flag"] = distress["cfo"].apply(lambda value: int((as_float(value) or 0.0) < 0))
    distress["deleveraging_flag"] = distress["cff"].apply(lambda value: int((as_float(value) or 0.0) < 0))
    distress = distress.loc[(distress["distress_flag"] == 1) | (distress["deleveraging_flag"] == 1)].copy()
    distress = distress[[
        col for col in [
            "company_id",
            "sector",
            "year",
            "cfo",
            "cfi",
            "cff",
            "net_income",
            "distress_flag",
            "deleveraging_flag",
        ] if col in distress.columns
    ]]
    distress.to_csv(distress_csv, index=False)

    try:
        _pattern_changes()
    except Exception as exc:  # pragma: no cover - defensive
        LOGGER.warning("Pattern change build failed: %s", exc)
    return summary


def export_capital_allocation_from_db(db_path: Path = DB_PATH, output_path: Path = OUTPUT_DIR / "capital_allocation.csv") -> pd.DataFrame:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        frame = pd.read_sql_query(
            """
            SELECT
                company_id,
                financial_year AS year,
                net_cash_from_operations AS cfo,
                net_cash_from_investing AS cfi,
                net_cash_from_financing AS cff
            FROM cashflow
            WHERE financial_year BETWEEN 2020 AND 2026
            ORDER BY company_id, financial_year;
            """,
            conn,
        )
    if frame.empty:
        result = pd.DataFrame(columns=["company_id", "year", "cfo_sign", "cfi_sign", "cff_sign", "pattern_label"])
        result.to_csv(output_path, index=False)
        return result
    frame["pattern_label"] = frame.apply(_classify_capital_allocation, axis=1)
    rows = []
    for row in frame.to_dict(orient="records"):
        rows.append(
            {
                "company_id": int(row["company_id"]),
                "year": int(row["year"]),
                "cfo_sign": "+" if (as_float(row.get("cfo")) or 0.0) > 0 else "-" if (as_float(row.get("cfo")) or 0.0) < 0 else "0",
                "cfi_sign": "+" if (as_float(row.get("cfi")) or 0.0) > 0 else "-" if (as_float(row.get("cfi")) or 0.0) < 0 else "0",
                "cff_sign": "+" if (as_float(row.get("cff")) or 0.0) > 0 else "-" if (as_float(row.get("cff")) or 0.0) < 0 else "0",
                "pattern_label": row["pattern_label"],
            }
        )
    result = pd.DataFrame(rows).drop_duplicates(subset=["company_id", "year"], keep="first").sort_values(["company_id", "year"]).reset_index(drop=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output_path, index=False)
    return result


def build_capital_allocation_frame(records: Iterable[dict[str, Any]] | pd.DataFrame, output_path: Path = OUTPUT_DIR / "capital_allocation.csv") -> pd.DataFrame:
    if isinstance(records, pd.DataFrame):
        frame = records.copy()
    else:
        frame = pd.DataFrame(list(records))
    if frame.empty:
        result = pd.DataFrame(columns=["company_id", "year", "cfo_sign", "cfi_sign", "cff_sign", "pattern_label"])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        result.to_csv(output_path, index=False)
        return result
    if "pattern_label" not in frame.columns:
        frame["pattern_label"] = frame.apply(_classify_capital_allocation, axis=1)
    rows = []
    for row in frame.to_dict(orient="records"):
        rows.append(
            {
                "company_id": int(row["company_id"]),
                "year": int(row["year"]),
                "cfo_sign": "+" if (as_float(row.get("cfo")) or 0.0) > 0 else "-" if (as_float(row.get("cfo")) or 0.0) < 0 else "0",
                "cfi_sign": "+" if (as_float(row.get("cfi")) or 0.0) > 0 else "-" if (as_float(row.get("cfi")) or 0.0) < 0 else "0",
                "cff_sign": "+" if (as_float(row.get("cff")) or 0.0) > 0 else "-" if (as_float(row.get("cff")) or 0.0) < 0 else "0",
                "pattern_label": row["pattern_label"],
            }
        )
    result = pd.DataFrame(rows, columns=["company_id", "year", "cfo_sign", "cfi_sign", "cff_sign", "pattern_label"])
    result = result.drop_duplicates(subset=["company_id", "year"], keep="first").sort_values(["company_id", "year"]).reset_index(drop=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output_path, index=False)
    return result


def main() -> int:
    build_cashflow_intelligence()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
