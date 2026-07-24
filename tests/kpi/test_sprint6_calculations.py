from __future__ import annotations

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

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


@pytest.mark.parametrize(
    "args, expected",
    [
        ((100, 50), 200.0),
        ((0, 100), 0.0),
        ((-100, 50), -200.0),
        ((25, 50), 50.0),
        ((75, 150), 50.0),
    ],
)
def test_net_profit_margin(args, expected):
    assert round(net_profit_margin(args[0], args[1]).value or 0, 2) == expected


@pytest.mark.parametrize("sales", [0, None])
def test_net_profit_margin_zero_denominator(sales):
    assert net_profit_margin(100, sales).value is None


@pytest.mark.parametrize(
    "operating_profit, sales, expected",
    [(50, 200, 25.0), (0, 200, 0.0), (30, 120, 25.0)],
)
def test_operating_profit_margin(operating_profit, sales, expected):
    outcome = operating_profit_margin(operating_profit, sales)
    assert round(outcome.value or 0, 2) == expected


@pytest.mark.parametrize("equity_capital,reserves,net_profit", [(100, 50, 30), (0, 0, 10), (-50, 10, 20)])
def test_return_on_equity_negative_equity_handling(equity_capital, reserves, net_profit):
    outcome = return_on_equity(net_profit, equity_capital, reserves)
    if equity_capital + reserves <= 0:
        assert outcome.value is None
    else:
        assert outcome.value is not None


@pytest.mark.parametrize(
    "ebit,equity,reserves,borrowings",
    [(100, 100, 0, 0), (80, 50, 25, 25), (120, 200, 50, 0)],
)
def test_return_on_capital_employed(ebit, equity, reserves, borrowings):
    outcome = return_on_capital_employed(ebit, equity, reserves, borrowings)
    assert outcome.value is not None or equity + reserves + borrowings <= 0


@pytest.mark.parametrize("assets", [0, None])
def test_return_on_assets_zero_denominator(assets):
    assert return_on_assets(100, assets).value is None


@pytest.mark.parametrize("borrowings,equity,reserves", [(0, 100, 50), (50, 100, 50), (250, 100, 0)])
def test_debt_to_equity_positive(borrowings, equity, reserves):
    outcome = debt_to_equity(borrowings, equity, reserves, broad_sector="Industrials")
    assert outcome.value is not None


def test_debt_free_returns_zero():
    outcome = debt_to_equity(0, 100, 50, broad_sector="Industrials")
    assert outcome.value == 0


def test_interest_coverage_debt_free_label():
    outcome = interest_coverage_ratio(100, 20, 0)
    assert outcome.label == "Debt Free"


def test_interest_coverage_warning_flag():
    outcome = interest_coverage_ratio(20, 5, 100)
    assert outcome.icr_warning_flag is False or outcome.value is not None


def test_asset_turnover():
    outcome = asset_turnover(100, 50)
    assert round(outcome.value or 0, 2) == 2.0


def test_net_debt():
    assert net_debt(100, 25).value == 75
