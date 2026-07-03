from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from analytics.cagr import calculate_cagr
from analytics.cashflow_kpis import (
    build_capital_allocation_frame,
    capex_intensity,
    classify_capital_allocation,
    cfo_quality_score,
    fcf_conversion_rate,
    free_cash_flow,
)
from analytics.ratios import (
    asset_turnover,
    debt_to_equity,
    interest_coverage_ratio,
    net_debt,
    net_profit_margin,
    operating_profit_margin,
    return_on_assets,
    return_on_capital_employed,
    return_on_equity,
)


def test_net_profit_margin_and_zero_sales():
    assert round(net_profit_margin(20, 200).value, 2) == 10.0
    assert net_profit_margin(20, 0).value is None


def test_operating_profit_margin_logs_edge_case(tmp_path):
    log_path = tmp_path / "ratio_edge_cases.log"
    outcome = operating_profit_margin(30, 100, source_percentage=45, edge_log_path=log_path, company_id=7, financial_year=2024)
    assert round(outcome.value, 2) == 30.0
    assert log_path.exists() and "formula discrepancy" in log_path.read_text(encoding="utf-8")


def test_return_on_equity_handles_negative_equity():
    assert round(return_on_equity(25, 50, 50).value, 2) == 25.0
    assert return_on_equity(25, -10, 0).value is None


def test_return_on_capital_employed_and_assets():
    assert round(return_on_capital_employed(50, 100, 25, 25).value, 2) == 33.33
    assert return_on_assets(15, 0).value is None


def test_debt_to_equity_high_leverage_and_financials_suppression():
    non_financial = debt_to_equity(600, 100, 0, broad_sector="Industrials")
    financials = debt_to_equity(600, 100, 0, broad_sector="Financials")
    assert round(non_financial.value, 2) == 6.0
    assert non_financial.high_leverage_flag is True
    assert financials.high_leverage_flag is False


def test_interest_coverage_debt_free_and_warning():
    debt_free = interest_coverage_ratio(50, 10, 0)
    weak_cover = interest_coverage_ratio(30, 0, 40)
    assert debt_free.value is None
    assert debt_free.label == "Debt Free"
    assert weak_cover.icr_warning_flag is True


def test_asset_turnover_and_net_debt():
    assert round(asset_turnover(300, 150).value, 2) == 2.0
    assert net_debt(120, 30).value == 90


def test_cagr_positive_positive_and_zero_base():
    assert round(calculate_cagr(100, 121, 2).value, 2) == 10.0
    assert calculate_cagr(0, 200, 5).flag == "ZERO_BASE"


def test_cagr_decline_and_turnaround_flags():
    assert calculate_cagr(100, -5, 5).flag == "DECLINE_TO_LOSS"
    assert calculate_cagr(-20, 40, 5).flag == "TURNAROUND"
    assert calculate_cagr(-20, -10, 5).flag == "BOTH_NEGATIVE"
    assert calculate_cagr(100, 150, 0).flag == "INSUFFICIENT"


def test_cfo_quality_and_fcf_metrics():
    quality = cfo_quality_score([120, 110, 100, 130, 125], [100, 100, 100, 100, 100])
    capex = capex_intensity(8, 200)
    fcf = free_cash_flow(60, -15)
    conversion = fcf_conversion_rate(45, 30)
    assert quality.label == "High Quality"
    assert round(capex.value, 2) == 4.0
    assert capex.label == "Moderate"
    assert fcf.value == 45
    assert round(conversion.value, 2) == 150.0


def test_capital_allocation_classifier_and_csv(tmp_path):
    outcome = classify_capital_allocation(80, -20, -10, cfo_pat_ratio=1.4)
    frame = build_capital_allocation_frame(
        [{"company_id": 1, "year": 2024, "cfo": 80, "cfi": -20, "cff": -10, "pattern_label": outcome.label}],
        tmp_path / "capital_allocation.csv",
    )
    assert outcome.label == "Shareholder Returns"
    assert frame.iloc[0]["pattern_label"] == "Shareholder Returns"
    assert (tmp_path / "capital_allocation.csv").exists()


@pytest.mark.parametrize(
    "start,end,years,expected_value,expected_flag",
    [
        (100, 121, 2, 10.0, None),
        (100, 100, 1, 0.0, None),
        (100, -1, 5, None, "DECLINE_TO_LOSS"),
        (-5, 10, 3, None, "TURNAROUND"),
        (-5, -10, 3, None, "BOTH_NEGATIVE"),
        (0, 20, 3, None, "ZERO_BASE"),
        (None, 20, 3, None, "INSUFFICIENT"),
        (20, None, 3, None, "INSUFFICIENT"),
        (20, 25, 0, None, "INSUFFICIENT"),
    ],
)
def test_cagr_case_matrix(start, end, years, expected_value, expected_flag):
    outcome = calculate_cagr(start, end, years)
    if expected_value is None:
        assert outcome.value is None
    else:
        assert round(outcome.value, 2) == expected_value
    assert outcome.flag == expected_flag
