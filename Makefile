SHELL := /bin/sh
PROJECT_ROOT := $(CURDIR)
PYTHON ?= ../.venv/bin/python
export PYTHONPATH := $(PROJECT_ROOT)/src

.PHONY: load ratios test assert sprint2-ratios sprint2-assert sprint3-screen sprint3-peer sprint3-assert sprint4-valuation sprint4-dashboard sprint5-nlp-parse sprint5-nlp-rules sprint5-cashflow sprint5-pdf-batch sprint5-build-all sprint6-clustering sprint6-api-start sprint6-test-suite sprint6-build-all report dashboard api clean

load:
	$(PYTHON) src/etl/loader.py load

ratios:
	$(PYTHON) src/etl/loader.py ratios

sprint2-ratios:
	$(PYTHON) src/etl/loader.py ratios

test:
	$(PYTHON) -m pytest -v tests/etl/test_normaliser.py

assert:
	$(PYTHON) tests/run_sprint1_assertions.py

sprint2-assert:
	$(PYTHON) tests/run_sprint2_assertions.py

sprint3-screen:
	$(PYTHON) -c "from screener.engine import run_screener_reports; run_screener_reports()"

sprint3-peer:
	$(PYTHON) -c "from analytics.peer import generate_peer_reports; generate_peer_reports()"

sprint3-assert:
	$(PYTHON) tests/run_sprint3_assertions.py

sprint4-valuation:
	$(PYTHON) src/analytics/valuation.py

sprint4-dashboard:
	$(PYTHON) -m streamlit run src/dashboard/app.py --server.port 8501

sprint5-nlp-parse:
	$(PYTHON) src/nlp/parser.py

sprint5-nlp-rules:
	$(PYTHON) src/nlp/pros_cons_generator.py

sprint5-cashflow:
	$(PYTHON) src/analytics/cashflow_kpis.py

sprint5-pdf-batch:
	$(PYTHON) -c "from reports.tearsheet import generate_tearsheets; from reports.sector_report import generate_sector_reports; from reports.portfolio import generate_portfolio_summary; generate_tearsheets(); generate_sector_reports(); generate_portfolio_summary()"

sprint5-build-all:
	$(PYTHON) src/nlp/parser.py
	$(PYTHON) src/nlp/pros_cons_generator.py
	$(PYTHON) src/analytics/cashflow_kpis.py
	$(PYTHON) -c "from reports.tearsheet import generate_tearsheets; from reports.sector_report import generate_sector_reports; from reports.portfolio import generate_portfolio_summary; generate_tearsheets(); generate_sector_reports(); generate_portfolio_summary()"

sprint6-clustering:
	$(PYTHON) src/analytics/clustering.py

sprint6-api-start:
	$(PYTHON) -m uvicorn api.main:app --host 0.0.0.0 --port 8000

sprint6-test-suite:
	$(PYTHON) -m pytest tests/ --html=reports/pytest_report.html

sprint6-build-all:
	$(PYTHON) src/analytics/clustering.py
	$(PYTHON) -m pytest tests/ --html=reports/pytest_report.html

report:
	$(PYTHON) src/etl/loader.py report

dashboard:
	$(PYTHON) src/etl/loader.py dashboard

api:
	$(PYTHON) src/etl/loader.py api

clean:
	$(PYTHON) -c "from pathlib import Path; import shutil; root = Path.cwd(); targets = [root / 'db' / 'nifty100.db', root / 'db' / 'nifty100.db-wal', root / 'db' / 'nifty100.db-shm', root / 'output' / 'load_audit.csv', root / 'output' / 'validation_failures.csv', root / 'output' / 'report_summary.md', root / 'output' / 'dashboard.html', root / '.env.local']; [path.unlink() for path in targets if path.exists()]; [shutil.rmtree(cache, ignore_errors=True) for base in [root / 'src', root / 'tests', root / 'output', root / 'db'] for cache in base.rglob('__pycache__')]; shutil.rmtree(root / '.pytest_cache', ignore_errors=True); shutil.rmtree(root / '.mypy_cache', ignore_errors=True)"
