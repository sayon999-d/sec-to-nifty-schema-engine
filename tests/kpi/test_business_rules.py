from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
DB_PATH = ROOT / "db" / "nifty100.db"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from analytics.cagr import calculate_cagr
from analytics.common import as_float
from analytics.ratios import debt_to_equity, interest_coverage_ratio
from etl.normaliser import normalize_ticker
from analytics import valuation


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def test_header_parameter_check_uses_header_one(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    from openpyxl import Workbook

    workbook_path = tmp_path / "ingestion_source.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["metadata row", "ignored"])
    ws.append(["company_id", "metric_type", "period_years", "value_pct"])
    ws.append([1, "roe", 5, 21.5])
    wb.save(workbook_path)

    frame = valuation._safe_read_excel(workbook_path)
    assert list(frame.columns) == ["company_id", "metric_type", "period_years", "value_pct"]
    assert frame.iloc[0]["company_id"] == 1
    assert frame.iloc[0]["metric_type"] == "roe"


def test_ticker_normalization_trims_and_uppercases():
    assert normalize_ticker(" sec001 ") == "SEC001"
    assert normalize_ticker("  nse:relIance  ") == "RELIANCE"


def test_currency_unit_consistency_for_crore_scaled_metrics():
    with _connect() as conn:
        ratios = pd.read_sql_query(
            """
            SELECT free_cash_flow_cr, cash_from_operations_cr, total_debt_cr
            FROM financial_ratios
            WHERE financial_year BETWEEN 2020 AND 2026
            LIMIT 25;
            """,
            conn,
        )
        market_cap = pd.read_sql_query(
            """
            SELECT market_cap_crore
            FROM market_cap
            WHERE financial_year BETWEEN 2020 AND 2026
            LIMIT 25;
            """,
            conn,
        )

    assert not ratios.empty
    assert not market_cap.empty
    for column in ["free_cash_flow_cr", "cash_from_operations_cr", "total_debt_cr"]:
        assert column in ratios.columns
        assert pd.api.types.is_numeric_dtype(pd.to_numeric(ratios[column], errors="coerce"))
    assert "market_cap_crore" in market_cap.columns
    assert pd.api.types.is_numeric_dtype(pd.to_numeric(market_cap["market_cap_crore"], errors="coerce"))
    assert pd.to_numeric(market_cap["market_cap_crore"], errors="coerce").abs().median() < 10_000_000


def test_financials_sector_debt_to_equity_carve_out():
    financial_services = debt_to_equity(1_000, 100, 0, broad_sector="Financial Services")
    financials = debt_to_equity(1_000, 100, 0, broad_sector="Financials")

    assert round(financial_services.value or 0, 2) == 10.0
    assert financial_services.high_leverage_flag is False
    assert round(financials.value or 0, 2) == 10.0
    assert financials.high_leverage_flag is False


def test_turnaround_cagr_handling_returns_turnaround_flag():
    outcome = calculate_cagr(-50, 120, 5)
    assert outcome.value is None
    assert outcome.flag in {"TURNAROUND", "Turnaround"}


def test_zero_interest_coverage_returns_debt_free_label():
    outcome = interest_coverage_ratio(80, 10, 0)
    assert outcome.value is None
    assert outcome.label == "Debt Free"


def test_simulated_data_tagging_in_valuation_sources():
    market_cap = valuation._market_cap_lookup()
    stock_prices = valuation._latest_stock_prices()

    assert not market_cap.empty
    assert not stock_prices.empty
    assert "is_simulated" in market_cap.columns
    assert "is_simulated" in stock_prices.columns
    assert set(pd.to_numeric(market_cap["is_simulated"], errors="coerce").fillna(0).astype(int).unique()).issubset({0, 1})
    assert set(pd.to_numeric(stock_prices["is_simulated"], errors="coerce").fillna(0).astype(int).unique()).issubset({0, 1})


def test_pipeline_zero_failure_rule_across_all_companies():
    with _connect() as conn:
        frame = pd.read_sql_query(
            """
            SELECT
                c.id AS company_id,
                c.ticker,
                fr.financial_year,
                fr.return_on_equity_pct,
                fr.debt_to_equity,
                fr.interest_coverage,
                fr.net_profit_margin_pct,
                fr.composite_quality_score,
                fr.earnings_per_share,
                p.revenue,
                p.operating_profit,
                p.net_income,
                b.total_equity,
                b.debt AS borrowings,
                b.cash_and_equivalents,
                cf.net_cash_from_operations
            FROM companies c
            LEFT JOIN financial_ratios fr
              ON fr.company_id = c.id
             AND fr.financial_year = (
                 SELECT MAX(fr2.financial_year)
                 FROM financial_ratios fr2
                 WHERE fr2.company_id = c.id AND fr2.financial_year <= 2024
             )
            LEFT JOIN profitandloss p
              ON p.company_id = c.id
             AND p.financial_year = fr.financial_year
            LEFT JOIN balancesheet b
              ON b.company_id = c.id
             AND b.financial_year = fr.financial_year
            LEFT JOIN cashflow cf
              ON cf.company_id = c.id
             AND cf.financial_year = fr.financial_year
            ORDER BY c.id;
            """,
            conn,
        )

    with _connect() as conn:
        company_count = int(pd.read_sql_query("SELECT COUNT(*) AS c FROM companies;", conn)["c"].iloc[0])
    assert company_count == 92
    assert len(frame) == 92

    failures: list[str] = []
    for _, row in frame.iterrows():
        try:
            debt_to_equity(
                row.get("borrowings"),
                row.get("total_equity"),
                0,
                broad_sector="Financials" if "BANK" in str(row.get("ticker", "")).upper() else "Industrials",
            )
            interest_coverage_ratio(row.get("operating_profit"), 0, 0)
            calculate_cagr(row.get("revenue"), row.get("revenue"), 5)
            calculate_cagr(row.get("net_income"), row.get("net_income"), 5)
            _ = as_float(row.get("return_on_equity_pct"))
        except Exception as exc:  # pragma: no cover - defensive test guard
            failures.append(f"{row.get('company_id')}: {exc}")

    assert failures == []
