from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import pandas as pd
from matplotlib.gridspec import GridSpec

if __package__ in {None, ""}:
    SRC_ROOT = Path(__file__).resolve().parents[1]
    import sys

    if str(SRC_ROOT) not in sys.path:
        sys.path.insert(0, str(SRC_ROOT))
    from analytics.cashflow_kpis import build_cashflow_intelligence, classify_capital_allocation
    from nlp.pros_cons_generator import generate_pros_cons
else:
    from analytics.cashflow_kpis import build_cashflow_intelligence, classify_capital_allocation
    from nlp.pros_cons_generator import generate_pros_cons

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "db" / "nifty100.db"
REPORT_DIR = PROJECT_ROOT / "reports" / "tearsheets"
OUTPUT_DIR = PROJECT_ROOT / "output"
SKIPPED_FILE = OUTPUT_DIR / "skipped_tearsheets.csv"

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


def _ensure_dirs() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _companies() -> pd.DataFrame:
    with _connect() as conn:
        return pd.read_sql_query("SELECT id AS company_id, ticker, company_name, sic, cityba, stateba FROM companies ORDER BY ticker;", conn)


def _company_frame(company_id: int) -> pd.DataFrame:
    with _connect() as conn:
        return pd.read_sql_query(
            """
            SELECT
                fr.company_id,
                fr.financial_year,
                fr.return_on_equity_pct,
                fr.return_on_capital_employed_pct,
                fr.net_profit_margin_pct,
                fr.operating_profit_margin_pct,
                fr.debt_to_equity,
                fr.interest_coverage,
                fr.free_cash_flow_cr,
                fr.cash_from_operations_cr,
                fr.composite_quality_score,
                p.revenue,
                p.net_income,
                b.total_equity,
                b.debt,
                b.total_liabilities,
                cf.net_cash_from_operations AS cfo,
                cf.net_cash_from_investing AS cfi,
                cf.net_cash_from_financing AS cff
            FROM financial_ratios fr
            LEFT JOIN cashflow cf ON cf.company_id = fr.company_id AND cf.financial_year = fr.financial_year
            LEFT JOIN profitandloss p ON p.company_id = fr.company_id AND p.financial_year = fr.financial_year
            LEFT JOIN balancesheet b ON b.company_id = fr.company_id AND b.financial_year = fr.financial_year
            WHERE fr.company_id = ? AND fr.financial_year BETWEEN 2019 AND 2024
            ORDER BY fr.financial_year ASC;
            """,
            conn,
            params=(company_id,),
        )


def _pros_cons(company_id: int) -> pd.DataFrame:
    csv_path = OUTPUT_DIR / "pros_cons_generated.csv"
    if not csv_path.exists():
        return pd.DataFrame(columns=["company_id", "type", "rule_id", "text", "confidence_pct"])
    frame = pd.read_csv(csv_path)
    if frame.empty or "company_id" not in frame.columns:
        return pd.DataFrame(columns=["company_id", "type", "rule_id", "text", "confidence_pct"])
    frame["company_id"] = pd.to_numeric(frame["company_id"], errors="coerce")
    frame = frame.dropna(subset=["company_id"]).copy()
    return frame.loc[frame["company_id"].astype(int).eq(int(company_id))].copy()


def _render_page_text(ax, title: str, lines: list[str], header_color: str = "#0F172A") -> None:
    ax.set_facecolor("#0B1220")
    ax.axis("off")
    ax.text(0.02, 0.96, title, fontsize=16, weight="bold", color="white", va="top")
    y = 0.86
    for line in lines:
        ax.text(0.03, y, line, fontsize=9, color="white", va="top", wrap=True)
        y -= 0.05


def _kpi_card(ax, label: str, value: object) -> None:
    ax.set_facecolor("#E5E7EB")
    ax.axis("off")
    ax.text(0.5, 0.72, label, ha="center", va="center", fontsize=10, weight="bold", color="#0F172A")
    ax.text(0.5, 0.35, f"{value:.2f}" if isinstance(value, (int, float)) and pd.notna(value) else "N/A", ha="center", va="center", fontsize=14, weight="bold", color="#111827")


def _numeric_series(frame: pd.DataFrame, column: str, default: float = 0.0) -> pd.Series:
    if column not in frame.columns:
        return pd.Series([default] * len(frame), index=frame.index, dtype="float64")
    return pd.to_numeric(frame[column], errors="coerce").fillna(default).astype(float)


def _fixed_two_page_pdf(path: Path, title: str, company_name: str, ticker: str, frame: pd.DataFrame, pros_cons_frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with PdfPages(path) as pdf:
        fig1 = plt.figure(figsize=(11, 14))
        fig1.suptitle(f"{company_name} ({ticker})", fontsize=18, weight="bold")
        gs = GridSpec(4, 3, figure=fig1, height_ratios=[0.9, 0.9, 1.4, 1.4])
        latest = frame.sort_values("financial_year").tail(10)
        cards = [
            ("ROE", latest["return_on_equity_pct"].tail(1).iloc[0] if not latest.empty else None),
            ("ROCE", latest["return_on_capital_employed_pct"].tail(1).iloc[0] if not latest.empty else None),
            ("NPM", latest["net_profit_margin_pct"].tail(1).iloc[0] if not latest.empty else None),
            ("OPM", latest["operating_profit_margin_pct"].tail(1).iloc[0] if not latest.empty else None),
            ("D/E", latest["debt_to_equity"].tail(1).iloc[0] if not latest.empty else None),
            ("ICR", latest["interest_coverage"].tail(1).iloc[0] if not latest.empty else None),
        ]
        for idx, (label, value) in enumerate(cards):
            _kpi_card(fig1.add_subplot(gs[idx // 3, idx % 3]), label, value)

        ax_bar = fig1.add_subplot(gs[2, :])
        ax_line = fig1.add_subplot(gs[3, :])
        fig1.patch.set_facecolor("white")
        if not frame.empty:
            hist = frame.sort_values("financial_year").tail(10)
            hist = hist.dropna(subset=["financial_year"]).copy()
            years = pd.to_numeric(hist["financial_year"], errors="coerce").fillna(0).astype(int)
            revenue = _numeric_series(hist, "revenue", 0.0)
            net_income = _numeric_series(hist, "net_income", 0.0)
            roe = _numeric_series(hist, "return_on_equity_pct", 0.0)
            roce = _numeric_series(hist, "return_on_capital_employed_pct", 0.0)
            ax_bar.bar(years - 0.15, revenue, width=0.3, label="Revenue", color="#5DADE2")
            ax_bar.bar(years + 0.15, net_income, width=0.3, label="Net Profit", color="#58D68D")
            ax_bar.set_title("Revenue vs Net Profit")
            ax_bar.legend()
            ax_bar.grid(True, axis="y", alpha=0.2)
            ax_line2 = ax_line.twinx()
            ax_line.plot(years, roe, marker="o", color="#1D4ED8", label="ROE")
            ax_line2.plot(years, roce, marker="o", color="#DC2626", label="ROCE")
            ax_line.set_title("ROE vs ROCE")
            ax_line.grid(True, axis="y", alpha=0.2)
            ax_line.legend(loc="upper left")
            ax_line2.legend(loc="upper right")
        pdf.savefig(fig1, bbox_inches="tight")
        plt.close(fig1)

        fig2, axes2 = plt.subplots(2, 2, figsize=(11, 14))
        fig2.suptitle(f"{company_name} ({ticker}) - Financial History", fontsize=18, weight="bold")
        if not frame.empty:
            hist = frame.sort_values("financial_year").tail(10)
            hist = hist.dropna(subset=["financial_year"]).copy()
            years = pd.to_numeric(hist["financial_year"], errors="coerce").fillna(0).astype(int)
            equity = _numeric_series(hist, "total_equity", 0.0)
            debt = _numeric_series(hist, "debt", 0.0)
            liabilities = _numeric_series(hist, "total_liabilities", 0.0)
            cfo = _numeric_series(hist, "cfo", 0.0)
            fcf = _numeric_series(hist, "free_cash_flow_cr", 0.0)
            axes2[0, 0].bar(years, equity, label="Equity", color="#5DADE2")
            axes2[0, 0].bar(years, debt, bottom=equity, label="Borrowings", color="#F4B400")
            axes2[0, 0].bar(years, liabilities, bottom=equity + debt, label="Liabilities", color="#EF4444")
            axes2[0, 0].legend()
            axes2[0, 0].set_title("Balance Sheet Stack")
            axes2[0, 1].bar(years, cfo, label="CFO", color="#16A34A")
            axes2[0, 1].bar(years, fcf, bottom=cfo, label="FCF", color="#60A5FA")
            axes2[0, 1].legend()
            axes2[0, 1].set_title("Cash Flow Waterfall Proxy")
            axes2[1, 0].axis("off")
            axes2[1, 1].axis("off")
            if not pros_cons_frame.empty:
                pros = [str(item).strip() for item in pros_cons_frame.loc[pros_cons_frame["type"].astype(str).str.lower().eq("pro"), "text"].tolist() if str(item).strip()]
                cons = [str(item).strip() for item in pros_cons_frame.loc[pros_cons_frame["type"].astype(str).str.lower().eq("con"), "text"].tolist() if str(item).strip()]
                axes2[1, 0].set_title("Pros", color="green")
                axes2[1, 1].set_title("Cons", color="red")
                axes2[1, 0].table(cellText=[[f"• {item}"] for item in pros[:8]] or [["No pros available"]], loc="center")
                axes2[1, 1].table(cellText=[[f"• {item}"] for item in cons[:8]] or [["No cons available"]], loc="center")
            latest_row = hist.iloc[-1] if not hist.empty else None
            allocation_label = (
                classify_capital_allocation(
                    latest_row.get("cfo") if latest_row is not None else None,
                    latest_row.get("cfi") if latest_row is not None else None,
                    latest_row.get("cff") if latest_row is not None else None,
                    cfo_pat_ratio=1.0,
                ).label
                if latest_row is not None
                else "N/A"
            )
            badge_text = allocation_label or "N/A"
            fig2.text(0.5, 0.02, f"Capital Allocation Patterns: {badge_text or 'N/A'}", ha="center", fontsize=10, bbox=dict(boxstyle="round,pad=0.4", facecolor="#FEF3C7", edgecolor="#D97706"))
        pdf.savefig(fig2, bbox_inches="tight")
        plt.close(fig2)


def generate_tearsheets() -> pd.DataFrame:
    _ensure_dirs()
    companies = _companies()
    skipped_rows = []
    pros_cons_frame = generate_pros_cons()
    build_cashflow_intelligence()
    for _, company in companies.iterrows():
        company_id = int(company["company_id"])
        ticker = str(company["ticker"])
        company_name = str(company["company_name"])
        frame = _company_frame(company_id)
        if frame["financial_year"].nunique() < 3:
            skipped_rows.append({"ticker": ticker, "company_id": company_id, "reason": "insufficient_history"})
            continue
        qualitative = pros_cons_frame.loc[pros_cons_frame["company_id"].eq(company_id)] if not pros_cons_frame.empty else pd.DataFrame()
        _fixed_two_page_pdf(REPORT_DIR / f"{ticker}_tearsheet.pdf", "Tearsheet", company_name, ticker, frame, qualitative)
    skipped = pd.DataFrame(skipped_rows, columns=["ticker", "company_id", "reason"])
    skipped.to_csv(SKIPPED_FILE, index=False)
    return skipped


def main() -> int:
    generate_tearsheets()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
