from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "db" / "nifty100.db"
OUTPUT_DIR = PROJECT_ROOT / "output"
SOURCE_SNAPSHOT = OUTPUT_DIR / "capital_allocation.csv"
OUTPUT_FILE = OUTPUT_DIR / "pattern_changes.csv"

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


def _current_patterns() -> pd.DataFrame:
    try:
        from .cashflow_kpis import export_capital_allocation_from_db

        export_capital_allocation_from_db(DB_PATH, SOURCE_SNAPSHOT)
    except Exception as exc:  # pragma: no cover - defensive
        LOGGER.warning("Capital allocation export failed, reusing current snapshot if available: %s", exc)
    if SOURCE_SNAPSHOT.exists():
        return pd.read_csv(SOURCE_SNAPSHOT)
    return pd.DataFrame(columns=["company_id", "year", "cfo_sign", "cfi_sign", "cff_sign", "pattern_label"])


def build_pattern_changes(output_file: Path = OUTPUT_FILE) -> pd.DataFrame:
    _ensure_output_dir()
    frame = _current_patterns()
    if frame.empty:
        result = pd.DataFrame(columns=["company_id", "from_pattern", "to_pattern", "from_year", "to_year"])
        result.to_csv(output_file, index=False)
        return result

    frame["year"] = pd.to_numeric(frame["year"], errors="coerce")
    frame = frame.dropna(subset=["company_id", "year", "pattern_label"]).copy()
    frame["company_id"] = frame["company_id"].astype(int)
    frame["year"] = frame["year"].astype(int)
    rows: list[dict[str, object]] = []
    for company_id, group in frame.sort_values(["company_id", "year"]).groupby("company_id"):
        prev_pattern = None
        prev_year = None
        for _, row in group.iterrows():
            current_pattern = str(row["pattern_label"])
            current_year = int(row["year"])
            if prev_pattern is not None and current_pattern != prev_pattern:
                rows.append(
                    {
                        "company_id": int(company_id),
                        "from_pattern": prev_pattern,
                        "to_pattern": current_pattern,
                        "from_year": int(prev_year) if prev_year is not None else None,
                        "to_year": current_year,
                    }
                )
            prev_pattern = current_pattern
            prev_year = current_year

    result = pd.DataFrame(rows, columns=["company_id", "from_pattern", "to_pattern", "from_year", "to_year"])
    result.to_csv(output_file, index=False)
    return result


def main() -> int:
    build_pattern_changes()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
