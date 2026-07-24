from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from api.main import app
from api.routers.companies import get_company_profile, list_companies
from api.routers.health import health
from api.routers.peers import compare_company_peers
from api.routers.screener import screener
from api.routers.sectors import sectors


def test_health_payload_has_uptime_and_counts():
    payload = json.loads(health().content.decode("utf-8"))
    assert "uptime_seconds" in payload
    assert "table_counts" in payload


def test_companies_endpoint_returns_list():
    payload = json.loads(list_companies().content.decode("utf-8"))
    assert isinstance(payload, list)


def test_company_profile_404():
    with pytest.raises(Exception):
        get_company_profile("NOTREAL")


def test_screener_endpoint_runs():
    payload = json.loads(screener().content.decode("utf-8"))
    assert isinstance(payload, list)


def test_sectors_endpoint_runs():
    payload = json.loads(sectors().content.decode("utf-8"))
    assert isinstance(payload, list)


def test_peers_compare_handles_missing():
    with pytest.raises(Exception):
        compare_company_peers("NOTREAL")

