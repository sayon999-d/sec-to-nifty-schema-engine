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
REPORT_DIR = PROJECT_ROOT / "reports" / "portfolio"

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


def _portfolio_frame() -> pd.DataFrame:
    query = """
        WITH latest AS (
            SELECT company_id, MAX(financial_year) AS financial_year
            FROM financial_ratios
            GROUP BY company_id
        )
        SELECT
            c.ticker,
            c.company_name,
            c.sic,
            fr.financial_year,
            fr.return_on_equity_pct,
            fr.return_on_capital_employed_pct,
            fr.net_profit_margin_pct,
            fr.operating_profit_margin_pct,
            fr.debt_to_equity,
            fr.interest_coverage,
            fr.composite_quality_score,
            p.revenue,
            p.net_income
        FROM financial_ratios fr
        JOIN latest l ON l.company_id = fr.company_id AND l.financial_year = fr.financial_year
        JOIN companies c ON c.id = fr.company_id
        LEFT JOIN profitandloss p ON p.company_id = fr.company_id AND p.financial_year = fr.financial_year
        WHERE fr.financial_year BETWEEN 2019 AND 2024
        ORDER BY c.ticker;
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
        "composite_quality_score",
        "revenue",
        "net_income",
    ]:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["financial_year"]).copy()
    frame["financial_year"] = frame["financial_year"].astype(int)
    return frame


def _arrow(curr: float | None, prev: float | None) -> str:
    if curr is None or prev is None:
        return "►"
    if curr > prev * 1.02:
        return "▲"
    if curr < prev * 0.98:
        return "▼"
    return "►"


def _trend_table() -> pd.DataFrame:
    with _connect() as conn:
        frame = pd.read_sql_query(
            """
            SELECT
                c.ticker,
                c.company_name,
                fr.financial_year,
                fr.return_on_equity_pct,
                fr.return_on_capital_employed_pct,
                fr.net_profit_margin_pct,
                fr.operating_profit_margin_pct,
                fr.debt_to_equity,
                fr.interest_coverage,
                fr.composite_quality_score
            FROM financial_ratios fr
            JOIN companies c ON c.id = fr.company_id
            WHERE fr.financial_year BETWEEN 2019 AND 2024
            ORDER BY c.ticker, fr.financial_year;
            """,
            conn,
        )
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
        "composite_quality_score",
    ]:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["financial_year"]).copy()
    frame["financial_year"] = frame["financial_year"].astype(int)
    return frame


def _write_portfolio_report(frame: pd.DataFrame) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / "portfolio_summary.pdf"
    history = _trend_table()
    with PdfPages(path) as pdf:
        for _, row in frame.iterrows():
            company_history = history.loc[history["ticker"].eq(row["ticker"])].sort_values("financial_year")
            prev = company_history.iloc[-2] if len(company_history) >= 2 else None
            latest = company_history.iloc[-1] if not company_history.empty else None
            fig, ax = plt.subplots(figsize=(11, 14))
            ax.axis("off")
            ax.set_title(f"{row.get('company_name', 'N/A')} ({row.get('ticker', 'N/A')})", fontsize=18, weight="bold")
            latest_year = int(row.get("financial_year") or 0)
            def _fmt(value: object) -> str:
                return "N/A" if pd.isna(value) else f"{float(value):.2f}" if isinstance(value, (int, float)) else str(value)
            lines = [
                f"ROE {_fmt(row.get('return_on_equity_pct'))} {_arrow(latest.get('return_on_equity_pct') if latest is not None else None, prev.get('return_on_equity_pct') if prev is not None else None)}",
                f"ROCE {_fmt(row.get('return_on_capital_employed_pct'))} {_arrow(latest.get('return_on_capital_employed_pct') if latest is not None else None, prev.get('return_on_capital_employed_pct') if prev is not None else None)}",
                f"NPM {_fmt(row.get('net_profit_margin_pct'))} {_arrow(latest.get('net_profit_margin_pct') if latest is not None else None, prev.get('net_profit_margin_pct') if prev is not None else None)}",
                f"OPM {_fmt(row.get('operating_profit_margin_pct'))} {_arrow(latest.get('operating_profit_margin_pct') if latest is not None else None, prev.get('operating_profit_margin_pct') if prev is not None else None)}",
                f"D/E {_fmt(row.get('debt_to_equity'))} {_arrow(latest.get('debt_to_equity') if latest is not None else None, prev.get('debt_to_equity') if prev is not None else None)}",
                f"ICR {_fmt(row.get('interest_coverage'))} {_arrow(latest.get('interest_coverage') if latest is not None else None, prev.get('interest_coverage') if prev is not None else None)}",
                f"Financial Year: {latest_year}",
                f"Revenue: {_fmt(row.get('revenue'))}",
                f"Net Income: {_fmt(row.get('net_income'))}",
            ]
            y = 0.9
            for line in lines:
                ax.text(0.05, y, line, fontsize=11)
                y -= 0.06
            pdf.savefig(fig, bbox_inches="tight")
            plt.close(fig)


def generate_portfolio_summary() -> None:
    frame = _portfolio_frame()
    if frame.empty:
        return
    _write_portfolio_report(frame.sort_values("ticker"))


def main() -> int:
    generate_portfolio_summary()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
