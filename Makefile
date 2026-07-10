SHELL := /bin/sh
PROJECT_ROOT := $(CURDIR)
PYTHON ?= ../.venv/bin/python
export PYTHONPATH := $(PROJECT_ROOT)/src

.PHONY: load ratios test assert sprint2-ratios sprint2-assert sprint3-screen sprint3-peer sprint3-assert report dashboard api clean

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

report:
	$(PYTHON) src/etl/loader.py report

dashboard:
	$(PYTHON) src/etl/loader.py dashboard

api:
	$(PYTHON) src/etl/loader.py api

clean:
	$(PYTHON) -c "from pathlib import Path; import shutil; root = Path.cwd(); targets = [root / 'db' / 'nifty100.db', root / 'db' / 'nifty100.db-wal', root / 'db' / 'nifty100.db-shm', root / 'output' / 'load_audit.csv', root / 'output' / 'validation_failures.csv', root / 'output' / 'report_summary.md', root / 'output' / 'dashboard.html', root / '.env.local']; [path.unlink() for path in targets if path.exists()]; [shutil.rmtree(cache, ignore_errors=True) for base in [root / 'src', root / 'tests', root / 'output', root / 'db'] for cache in base.rglob('__pycache__')]; shutil.rmtree(root / '.pytest_cache', ignore_errors=True); shutil.rmtree(root / '.mypy_cache', ignore_errors=True)"
