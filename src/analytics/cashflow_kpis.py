from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd

if __package__ in {None, ""}:
    SRC_ROOT = Path(__file__).resolve().parents[1]
    if str(SRC_ROOT) not in sys.path:
        sys.path.insert(0, str(SRC_ROOT))
    from analytics.common import MetricOutcome, as_float, rolling_average, sign_of
else:
    from .common import MetricOutcome, as_float, rolling_average, sign_of


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "db" / "nifty100.db"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "output" / "capital_allocation.csv"
HISTORICAL_YEAR_MIN = 2020
HISTORICAL_YEAR_MAX = 2026
CAPITAL_ALLOCATION_COLUMNS = [
    "company_id",
    "year",
    "cfo_sign",
    "cfi_sign",
    "cff_sign",
    "pattern_label",
]


def _direction_symbol(value: Any) -> str:
    number = as_float(value)
    if number is None or number == 0:
        return "0"
    return "+" if number > 0 else "-"


def _first_present(row: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row and row[key] is not None:
            return row[key]
    return None


def _extract_cash_flow_values(row: Mapping[str, Any]) -> tuple[Any, Any, Any]:
    cfo = _first_present(
        row,
        "cash_from_operations_cr",
        "net_cash_from_operations",
        "cfo",
        "operating_activity",
    )
    cfi = _first_present(
        row,
        "investing_activity",
        "net_cash_from_investing",
        "cfi",
    )
    cff = _first_present(
        row,
        "financing_activity",
        "net_cash_from_financing",
        "cff",
    )
    return cfo, cfi, cff


def free_cash_flow(operating_activity: float | int | None, investing_activity: float | int | None) -> MetricOutcome:
    return MetricOutcome(value=(as_float(operating_activity) or 0.0) + (as_float(investing_activity) or 0.0))


def cfo_quality_score(
    cfo_values: Iterable[float | int | None],
    pat_values: Iterable[float | int | None],
    *,
    window: int = 5,
) -> MetricOutcome:
    ratios: list[float] = []
    for cfo, pat in zip(list(cfo_values)[-window:], list(pat_values)[-window:]):
        pat_value = as_float(pat)
        if pat_value in {None, 0}:
            continue
        ratios.append((as_float(cfo) or 0.0) / pat_value)

    average_ratio = rolling_average(ratios)
    if average_ratio is None:
        return MetricOutcome(value=None)
    if average_ratio > 1.0:
        label = "High Quality"
    elif average_ratio >= 0.5:
        label = "Moderate"
    else:
        label = "Accrual Risk"
    return MetricOutcome(value=average_ratio, label=label)


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


def classify_capital_allocation(
    cfo: float | int | None,
    cfi: float | int | None,
    cff: float | int | None,
    *,
    cfo_pat_ratio: float | int | None = None,
    shareholder_threshold: float = 1.0,
) -> MetricOutcome:
    matrix = (_direction_symbol(cfo), _direction_symbol(cfi), _direction_symbol(cff))
    if matrix == ("+", "-", "-"):
        label = "Shareholder Returns" if (as_float(cfo_pat_ratio) or 0.0) > shareholder_threshold else "Reinvestor"
    elif matrix == ("+", "+", "-"):
        label = "Liquidating Assets"
    elif matrix == ("-", "+", "+"):
        label = "Distress Signal"
    elif matrix == ("-", "-", "+"):
        label = "Growth Funded by Debt"
    elif matrix == ("+", "+", "+"):
        label = "Cash Accumulator"
    elif matrix == ("-", "-", "-"):
        label = "Pre-Revenue"
    else:
        label = "Mixed"
    return MetricOutcome(value=None, label=label)


def load_cashflow_records(conn: sqlite3.Connection) -> pd.DataFrame:
    """
    Load cash flow rows from SQLite with the historical year bound directly from
    the database row object.
    """

    query = """
        SELECT
            company_id,
            financial_year AS year,
            net_cash_from_operations AS cash_from_operations_cr,
            net_cash_from_investing AS investing_activity,
            net_cash_from_financing AS financing_activity
        FROM cashflow
        WHERE financial_year BETWEEN ? AND ?
        ORDER BY company_id, financial_year;
    """.strip()
    return pd.read_sql_query(query, conn, params=(HISTORICAL_YEAR_MIN, HISTORICAL_YEAR_MAX))


def iter_capital_allocation_records(records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """
    Convert row mappings to the canonical CSV payload.

    The year value is taken strictly from the row object:
    `year = int(row["year"])`
    """

    rows: list[dict[str, Any]] = []
    seen_company_year: set[tuple[int, int]] = set()

    for row in records:
        year = int(row["year"])
        company_id = int(row["company_id"])
        company_year = (company_id, year)
        if company_year in seen_company_year:
            continue
        seen_company_year.add(company_year)

        cfo, cfi, cff = _extract_cash_flow_values(row)
        pattern_label = row.get("pattern_label")
        if pattern_label in {None, ""}:
            pattern_label = classify_capital_allocation(cfo, cfi, cff).label

        rows.append(
            {
                "company_id": company_id,
                "year": year,
                "cfo_sign": _direction_symbol(cfo),
                "cfi_sign": _direction_symbol(cfi),
                "cff_sign": _direction_symbol(cff),
                "pattern_label": pattern_label,
            }
        )

    return rows


def build_capital_allocation_frame(
    records: Iterable[Mapping[str, Any]],
    output_path: Path = DEFAULT_OUTPUT_PATH,
) -> pd.DataFrame:
    rows = iter_capital_allocation_records(records)
    frame = pd.DataFrame(rows, columns=CAPITAL_ALLOCATION_COLUMNS)
    if not frame.empty:
        frame = frame.drop_duplicates(subset=["company_id", "year"], keep="first")
        frame = frame.sort_values(["company_id", "year"], kind="stable").reset_index(drop=True)
        frame = frame.astype({"company_id": "int64", "year": "int64"})
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output_path, index=False)
    return frame


def export_capital_allocation_from_db(
    db_path: Path = DEFAULT_DB_PATH,
    output_path: Path = DEFAULT_OUTPUT_PATH,
) -> pd.DataFrame:
    db_path = Path(db_path)
    with sqlite3.connect(db_path) as conn:
        cashflow_frame = load_cashflow_records(conn)
    return build_capital_allocation_frame(cashflow_frame.to_dict(orient="records"), output_path=output_path)


def main(argv: list[str] | None = None) -> int:
    _ = argv
    export_capital_allocation_from_db()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

