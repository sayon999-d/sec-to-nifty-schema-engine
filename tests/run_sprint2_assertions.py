from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
DB_PATH = PROJECT_ROOT / "db" / "nifty100.db"
OUTPUT_DIR = PROJECT_ROOT / "output"
RATIO_LOG = OUTPUT_DIR / "ratio_edge_cases.log"
CAPITAL_ALLOCATION = OUTPUT_DIR / "capital_allocation.csv"
PRIMARY_KPI_COLUMNS = [
    "net_profit_margin_pct",
    "operating_profit_margin_pct",
    "return_on_equity_pct",
    "return_on_capital_employed_pct",
    "debt_to_equity",
    "interest_coverage",
    "asset_turnover",
    "free_cash_flow_cr",
    "capex_cr",
    "earnings_per_share",
    "book_value_per_share",
    "dividend_payout_ratio_pct",
    "total_debt_cr",
    "cash_from_operations_cr",
]
SPRINT2_METRICS = [
    "net_profit_margin_pct",
    "operating_profit_margin_pct",
    "return_on_equity_pct",
    "debt_to_equity",
    "interest_coverage",
    "asset_turnover",
    "free_cash_flow_cr",
    "capex_cr",
    "earnings_per_share",
    "book_value_per_share",
    "dividend_payout_ratio_pct",
    "total_debt_cr",
    "cash_from_operations_cr",
    "revenue_cagr_5yr",
    "pat_cagr_5yr",
    "eps_cagr_5yr",
    "composite_quality_score",
]


def mark(ok: bool, message: str) -> None:
    symbol = "[✓]" if ok else "[✗]"
    print(f"{symbol} {message}")


def run_pytest() -> tuple[bool, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC_ROOT)
    python_candidates = [
        PROJECT_ROOT.parent / ".venv" / "bin" / "python",
        Path(sys.executable),
        Path("python3"),
        Path("python"),
    ]
    python_bin = next((candidate for candidate in python_candidates if candidate.exists()), Path(sys.executable))
    command = [str(python_bin), "-m", "pytest", "-q", "tests/kpi/test_formulas.py"]
    completed = subprocess.run(command, cwd=PROJECT_ROOT, env=env, text=True, capture_output=True)
    if completed.returncode == 0:
        return True, completed.stdout.strip()
    detail = "\n".join(part for part in [completed.stdout.strip(), completed.stderr.strip()] if part)
    return False, detail


def table_columns(conn: sqlite3.Connection, table_name: str) -> list[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return [str(row[1]) for row in rows]


def main() -> int:
    ok = True

    if not DB_PATH.exists():
        mark(False, f"database missing: {DB_PATH}")
        return 1

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row_count = int(conn.execute("SELECT COUNT(*) FROM financial_ratios;").fetchone()[0])
        row_ok = row_count >= 1100
        mark(row_ok, f"financial_ratios row count >= 1,100 ({row_count})")
        ok &= row_ok

        existing_columns = set(table_columns(conn, "financial_ratios"))
        missing_columns = [column for column in SPRINT2_METRICS if column not in existing_columns]
        column_results = []
        if missing_columns:
            mark(False, f"missing Sprint 2 columns: {', '.join(missing_columns)}")
            ok = False
        else:
            for column in SPRINT2_METRICS:
                non_null = int(conn.execute(f"SELECT COUNT({column}) FROM financial_ratios WHERE {column} IS NOT NULL;").fetchone()[0])
                column_ok = non_null > 0
                column_results.append(column_ok)
                mark(column_ok, f"{column} populated ({non_null} non-null row(s))")
            ok &= all(column_results)

    pytest_ok, pytest_detail = run_pytest()
    mark(pytest_ok, "20 formula unit tests run green")
    if not pytest_ok and pytest_detail:
        print(pytest_detail)
    ok &= pytest_ok

    log_ok = RATIO_LOG.exists() and RATIO_LOG.stat().st_size > 0
    csv_ok = CAPITAL_ALLOCATION.exists() and CAPITAL_ALLOCATION.stat().st_size > 0
    mark(log_ok, f"ratio edge-case log present ({RATIO_LOG})")
    mark(csv_ok, f"capital allocation csv present ({CAPITAL_ALLOCATION})")
    ok &= log_ok and csv_ok

    if csv_ok:
        try:
            import pandas as pd

            frame = pd.read_csv(CAPITAL_ALLOCATION)
            csv_schema_ok = list(frame.columns) == ["company_id", "year", "cfo_sign", "cfi_sign", "cff_sign", "pattern_label"] and not frame.empty
        except Exception:
            csv_schema_ok = False
        mark(csv_schema_ok, "capital allocation csv schema validated")
        ok &= csv_schema_ok

    if log_ok:
        preview = RATIO_LOG.read_text(encoding="utf-8").splitlines()[:3]
        mark(len(preview) >= 2, "ratio edge-case log populated with records")
        ok &= len(preview) >= 2

    if ok:
        print("[✓] Sprint 2 exit criteria satisfied")
        return 0

    print("[✗] Sprint 2 exit criteria failed")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
