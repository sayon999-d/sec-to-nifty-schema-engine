from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from analytics.peer import _metric_percentile
from analytics.sectoring import all_peer_groups, broad_sector_from_row, peer_group_from_row
from screener.engine import load_screener_config


DB = ROOT / "db" / "nifty100.db"
CONFIG = ROOT / "config" / "screener_config.yaml"


def _frame():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    frame = pd.read_sql_query("select company_id, financial_year, debt_to_equity, return_on_equity_pct, interest_coverage, composite_quality_score from financial_ratios where financial_year between 2020 and 2026 limit 20", conn)
    conn.close()
    return frame


def test_config_loads_screeners():
    cfg = load_screener_config(CONFIG)
    assert "screeners" in cfg and len(cfg["screeners"]) == 6


def test_broad_sector_mapping_financials():
    assert broad_sector_from_row("SIC-60") == "Financials"


def test_broad_sector_mapping_it_services():
    assert broad_sector_from_row("SIC-73") == "IT Services"


def test_peer_group_mapping_matches_broad_sector():
    assert peer_group_from_row("SIC-73") == "IT Services"


def test_all_peer_groups_has_eleven_groups():
    assert len(all_peer_groups()) == 11


def test_percentile_inversion_for_debt_to_equity():
    frame = _frame()
    ranks = _metric_percentile(frame, "debt_to_equity")
    assert ranks.max() <= 1.0 and ranks.min() >= 0.0


def test_percentile_returns_none_for_missing():
    series = pd.Series([None, None])
    assert _metric_percentile(pd.DataFrame({"debt_to_equity": series}), "debt_to_equity").isna().all()


def test_screener_config_contains_quality_compounder():
    cfg = load_screener_config(CONFIG)
    assert cfg["screeners"]["quality_compounder"]["name"] == "Quality Compounder"


def test_screener_config_contains_value_pick():
    cfg = load_screener_config(CONFIG)
    assert cfg["screeners"]["value_pick"]["name"] == "Value Pick"


def test_screener_config_contains_growth_accelerator():
    cfg = load_screener_config(CONFIG)
    assert cfg["screeners"]["growth_accelerator"]["name"] == "Growth Accelerator"


def test_screener_config_contains_dividend_champion():
    cfg = load_screener_config(CONFIG)
    assert cfg["screeners"]["dividend_champion"]["name"] == "Dividend Champion"


def test_screener_config_contains_debt_free_blue_chip():
    cfg = load_screener_config(CONFIG)
    assert cfg["screeners"]["debt_free_blue_chip"]["name"] == "Debt-Free Blue Chip"


def test_screener_config_contains_turnaround_watch():
    cfg = load_screener_config(CONFIG)
    assert cfg["screeners"]["turnaround_watch"]["name"] == "Turnaround Watch"


def test_dq_dataset_has_rows():
    conn = sqlite3.connect(DB)
    count = conn.execute("select count(*) from financial_ratios where financial_year between 2020 and 2026").fetchone()[0]
    conn.close()
    assert count > 0

