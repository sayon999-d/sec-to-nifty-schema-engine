from __future__ import annotations

import sys
from pathlib import Path

if __package__ in {None, ""}:
    SRC_ROOT = Path(__file__).resolve().parents[1]
    if str(SRC_ROOT) not in sys.path:
        sys.path.insert(0, str(SRC_ROOT))
    from analytics.common import MetricOutcome, append_edge_case_log, as_float, is_financials_sector, safe_divide
else:
    from .common import MetricOutcome, append_edge_case_log, as_float, is_financials_sector, safe_divide


def net_profit_margin(net_profit: float | int | None, sales: float | int | None) -> MetricOutcome:
    sales_value = as_float(sales)
    if sales_value in {None, 0}:
        return MetricOutcome(value=None)
    return MetricOutcome(value=(as_float(net_profit) or 0.0) / sales_value * 100.0)


def operating_profit_margin(
    operating_profit: float | int | None,
    sales: float | int | None,
    *,
    source_percentage: float | int | None = None,
    edge_log_path=None,
    company_id: int | str | None = None,
    financial_year: int | str | None = None,
) -> MetricOutcome:
    sales_value = as_float(sales)
    if sales_value in {None, 0}:
        return MetricOutcome(value=None)
    computed = (as_float(operating_profit) or 0.0) / sales_value * 100.0
    source_value = as_float(source_percentage)
    if edge_log_path is not None and source_value is not None and abs(computed - source_value) > 1.0:
        append_edge_case_log(
            edge_log_path,
            category="formula discrepancy",
            company_id=company_id,
            financial_year=financial_year,
            metric="operating_profit_margin",
            computed_value=round(computed, 6),
            source_value=round(source_value, 6),
            detail="operating profit margin differs from source by more than 1.0 percentage point",
        )
    return MetricOutcome(value=computed)


def return_on_equity(
    net_profit: float | int | None,
    equity_capital: float | int | None,
    reserves: float | int | None,
) -> MetricOutcome:
    equity = (as_float(equity_capital) or 0.0) + (as_float(reserves) or 0.0)
    if equity <= 0:
        return MetricOutcome(value=None)
    return MetricOutcome(value=(as_float(net_profit) or 0.0) / equity * 100.0)


def return_on_capital_employed(
    ebit: float | int | None,
    equity_capital: float | int | None,
    reserves: float | int | None,
    borrowings: float | int | None,
    *,
    broad_sector: str | None = None,
) -> MetricOutcome:
    capital_employed = (as_float(equity_capital) or 0.0) + (as_float(reserves) or 0.0) + (as_float(borrowings) or 0.0)
    if capital_employed <= 0:
        return MetricOutcome(value=None)
    return MetricOutcome(value=(as_float(ebit) or 0.0) / capital_employed * 100.0)


def return_on_assets(net_profit: float | int | None, total_assets: float | int | None) -> MetricOutcome:
    assets = as_float(total_assets)
    if assets in {None, 0}:
        return MetricOutcome(value=None)
    return MetricOutcome(value=(as_float(net_profit) or 0.0) / assets * 100.0)


def debt_to_equity(
    borrowings: float | int | None,
    equity_capital: float | int | None,
    reserves: float | int | None,
    *,
    broad_sector: str | None = None,
) -> MetricOutcome:
    borrowings_value = as_float(borrowings) or 0.0
    equity = (as_float(equity_capital) or 0.0) + (as_float(reserves) or 0.0)
    if borrowings_value == 0:
        return MetricOutcome(value=0.0)
    if equity <= 0:
        return MetricOutcome(value=None)
    ratio = borrowings_value / equity
    high_leverage_flag = ratio > 5.0 and not is_financials_sector(broad_sector)
    return MetricOutcome(value=ratio, high_leverage_flag=high_leverage_flag)


def interest_coverage_ratio(
    operating_profit: float | int | None,
    other_income: float | int | None,
    interest: float | int | None,
) -> MetricOutcome:
    interest_value = as_float(interest)
    if interest_value in {None, 0}:
        return MetricOutcome(value=None, label="Debt Free")
    value = ((as_float(operating_profit) or 0.0) + (as_float(other_income) or 0.0)) / interest_value
    warning_flag = value < 1.5 and interest_value > 0
    return MetricOutcome(value=value, icr_warning_flag=warning_flag)


def asset_turnover(sales: float | int | None, total_assets: float | int | None) -> MetricOutcome:
    assets = as_float(total_assets)
    if assets in {None, 0}:
        return MetricOutcome(value=None)
    return MetricOutcome(value=(as_float(sales) or 0.0) / assets)


def net_debt(borrowings: float | int | None, investments: float | int | None) -> MetricOutcome:
    return MetricOutcome(value=(as_float(borrowings) or 0.0) - (as_float(investments) or 0.0))
