from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import pandas as pd

if __package__ in {None, ""}:
    import sys

    SRC_ROOT = Path(__file__).resolve().parents[1]
    if str(SRC_ROOT) not in sys.path:
        sys.path.insert(0, str(SRC_ROOT))

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "db" / "nifty100.db"
REPORT_DIR = PROJECT_ROOT / "reports" / "sector"

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


def _sector_frame() -> pd.DataFrame:
    query = """
        WITH latest AS (
            SELECT company_id, MAX(financial_year) AS financial_year
            FROM financial_ratios
            GROUP BY company_id
        )
        SELECT
            s.sector_name,
            c.company_name,
            c.ticker,
            fr.financial_year,
            fr.return_on_equity_pct,
            fr.return_on_capital_employed_pct,
            fr.net_profit_margin_pct,
            fr.operating_profit_margin_pct,
            fr.debt_to_equity,
            fr.interest_coverage,
            fr.free_cash_flow_cr,
            fr.composite_quality_score,
            p.revenue
        FROM financial_ratios fr
        JOIN latest l ON l.company_id = fr.company_id AND l.financial_year = fr.financial_year
        JOIN companies c ON c.id = fr.company_id
        LEFT JOIN sectors s ON s.company_id = fr.company_id
        LEFT JOIN profitandloss p ON p.company_id = fr.company_id AND p.financial_year = fr.financial_year
        WHERE fr.financial_year BETWEEN 2019 AND 2024
        ORDER BY s.sector_name, c.company_name;
    """
    with _connect() as conn:
        frame = pd.read_sql_query(query, conn)
    if frame.empty:
        return frame
    for column in [
        "financial_year",
        "return_on_equity_pct",
        "return_on_capital_employed_pct",
        "net_profit_margin_pct",
        "operating_profit_margin_pct",
        "debt_to_equity",
        "interest_coverage",
        "free_cash_flow_cr",
        "composite_quality_score",
        "revenue",
    ]:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["financial_year"]).copy()
    frame["financial_year"] = frame["financial_year"].astype(int)
    return frame


def _write_sector_report(sector: str, frame: pd.DataFrame) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / f"{sector.replace(' ', '_').lower()}_report.pdf"
    with PdfPages(path) as pdf:
        fig, ax = plt.subplots(figsize=(11, 14))
        ax.axis("off")
        ax.set_title(f"Sector Dashboard - {sector}", fontsize=18, weight="bold")
        clean = frame.dropna(subset=["company_name", "ticker"]).copy()
        median_row = clean.median(numeric_only=True)
        lines = [f"{col}: {median_row[col]:.2f}" for col in [
            "return_on_equity_pct",
            "return_on_capital_employed_pct",
            "net_profit_margin_pct",
            "operating_profit_margin_pct",
            "debt_to_equity",
            "interest_coverage",
            "free_cash_flow_cr",
            "composite_quality_score",
        ] if col in median_row.index]
        y = 0.9
        for line in lines:
            ax.text(0.05, y, line, fontsize=10)
            y -= 0.05
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)

        fig2, ax2 = plt.subplots(figsize=(11, 14))
        ax2.axis("off")
        ax2.set_title(f"{sector} - Company Matrix", fontsize=18, weight="bold")
        table_frame = clean[[
            "company_name",
            "ticker",
            "revenue",
            "return_on_equity_pct",
            "return_on_capital_employed_pct",
            "net_profit_margin_pct",
            "operating_profit_margin_pct",
            "debt_to_equity",
        ]].head(40)
        table = ax2.table(cellText=table_frame.fillna("").values.tolist(), colLabels=table_frame.columns.tolist(), loc="center")
        table.auto_set_font_size(False)
        table.set_fontsize(7)
        table.scale(1, 1.2)
        pdf.savefig(fig2, bbox_inches="tight")
        plt.close(fig2)


def generate_sector_reports() -> None:
    frame = _sector_frame()
    if frame.empty:
        return
    for sector, group in frame.groupby("sector_name", dropna=False):
        _write_sector_report(str(sector or "Unknown"), group.dropna(subset=["financial_year"]).copy())


def main() -> int:
    generate_sector_reports()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
