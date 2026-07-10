from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
DB_PATH = PROJECT_ROOT / "db" / "nifty100.db"
SCREENER_OUTPUT = PROJECT_ROOT / "output" / "screener_output.xlsx"
PEER_OUTPUT = PROJECT_ROOT / "output" / "peer_comparison.xlsx"
RADAR_DIR = PROJECT_ROOT / "reports" / "radar_charts"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


def mark(ok: bool, message: str) -> None:
    print(f"{'[✓]' if ok else '[✗]'} {message}")


def _python_bin() -> str:
    candidates = [
        PROJECT_ROOT.parent / ".venv" / "bin" / "python",
        Path(sys.executable),
        Path("python3"),
        Path("python"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return sys.executable


def _run_pytest() -> tuple[bool, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC_ROOT)
    command = [_python_bin(), "-m", "pytest", "-q", "tests/kpi/test_sprint3_dq.py"]
    completed = subprocess.run(command, cwd=PROJECT_ROOT, env=env, text=True, capture_output=True)
    if completed.returncode == 0:
        return True, completed.stdout.strip()
    detail = "\n".join(part for part in [completed.stdout.strip(), completed.stderr.strip()] if part)
    return False, detail


def main() -> int:
    ok = True
    if not DB_PATH.exists():
        mark(False, f"database missing: {DB_PATH}")
        return 1

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        ratios = conn.execute("select count(*) from financial_ratios where financial_year between 2020 and 2026").fetchone()[0]
        mark(ratios > 0, f"financial_ratios has {ratios} in-range rows")
        ok &= ratios > 0

    try:
        from screener.engine import ScreenerEngine
        from analytics.peer import generate_peer_reports
    except Exception as exc:
        mark(False, f"import failure: {exc}")
        return 1

    screener_results = ScreenerEngine().run()
    screening_ok = True
    for name in [
        "Quality Compounder",
        "Value Pick",
        "Growth Accelerator",
        "Dividend Champion",
        "Debt-Free Blue Chip",
        "Turnaround Watch",
    ]:
        frame = screener_results.get(name)
        count = 0 if frame is None else int(frame["company_id"].nunique()) if not frame.empty else 0
        passed = 5 <= count <= 50
        mark(passed, f"{name} isolates {count} company/companies")
        screening_ok &= passed
    ok &= screening_ok

    generate_peer_reports()

    peer_sheet_ok = False
    if PEER_OUTPUT.exists():
        try:
            xls = pd.ExcelFile(PEER_OUTPUT)
            peer_sheet_ok = len(xls.sheet_names) == 11
        except Exception:
            peer_sheet_ok = False
    mark(peer_sheet_ok, "peer_comparison.xlsx contains exactly 11 sheets")
    ok &= peer_sheet_ok

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        highest_roe = conn.execute(
            """
            SELECT company_id
            FROM peer_percentiles
            WHERE peer_group_name = 'IT Services' AND metric = 'return_on_equity_pct'
            ORDER BY value DESC, company_id
            LIMIT 1;
            """
        ).fetchone()
        highest_percentile = conn.execute(
            """
            SELECT company_id
            FROM peer_percentiles
            WHERE peer_group_name = 'IT Services' AND metric = 'return_on_equity_pct'
            ORDER BY percentile_rank DESC, company_id
            LIMIT 1;
            """
        ).fetchone()
        it_services_ok = highest_roe is not None and highest_percentile is not None and int(highest_roe[0]) == int(highest_percentile[0])
        mark(it_services_ok, "IT Services highest ROE matches highest percentile rank")
        ok &= it_services_ok

    pytest_ok, pytest_detail = _run_pytest()
    mark(pytest_ok, "14 Data Quality unit tests run green")
    if not pytest_ok and pytest_detail:
        print(pytest_detail)
    ok &= pytest_ok

    radar_ok = RADAR_DIR.exists() and any(RADAR_DIR.glob("*_radar.png"))
    mark(radar_ok, "radar charts generated")
    ok &= radar_ok

    if ok:
        print("[✓] Sprint 3 exit criteria satisfied")
        return 0
    print("[✗] Sprint 3 exit criteria failed")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
