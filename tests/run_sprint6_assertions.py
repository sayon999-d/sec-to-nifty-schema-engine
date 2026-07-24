from __future__ import annotations

from pathlib import Path
import sqlite3
import sys

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OUTPUT = ROOT / "output"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _print(flag: bool, text: str) -> None:
    print(f"[{'✓' if flag else '✗'}] {text}")


def _count(path: Path) -> int:
    return int(pd.read_csv(path).shape[0]) if path.exists() and path.suffix == ".csv" else 0


def main() -> int:
    results = pytest.main([str(ROOT / "tests"), "--maxfail=1", "--disable-warnings", "--html", str(OUTPUT / "pytest_report.html")])
    ok = results == 0
    _print(ok, "pytest suite completed cleanly")
    with sqlite3.connect(ROOT / "db" / "nifty100.db") as conn:
        conn.row_factory = sqlite3.Row
        company_count = conn.execute("SELECT COUNT(*) FROM companies;").fetchone()[0]
        ratio_count = conn.execute("SELECT COUNT(*) FROM financial_ratios;").fetchone()[0]
    _print(company_count >= 92, f"companies count >= 92 ({company_count})")
    _print(ratio_count > 0, f"financial_ratios rows > 0 ({ratio_count})")
    required_files = [
        OUTPUT / "cluster_labels.csv",
        OUTPUT / "outlier_report.csv",
        OUTPUT / "portfolio_stats.csv",
        OUTPUT / "pytest_report.html",
        ROOT / "reports" / "elbow_plot.png",
    ]
    for file in required_files:
        _print(file.exists(), f"artifact present: {file.name}")
    return int(results)


if __name__ == "__main__":
    raise SystemExit(main())
