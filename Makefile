SHELL := /bin/sh
PYTHON ?= python
PROJECT_ROOT := $(CURDIR)
export PYTHONPATH := $(PROJECT_ROOT)/src

.PHONY: load ratios test assert report dashboard api clean

load:
	$(PYTHON) src/etl/loader.py load

ratios:
	$(PYTHON) src/etl/loader.py ratios

test:
	$(PYTHON) -m pytest -v tests/etl/test_normaliser.py

assert:
	$(PYTHON) tests/run_sprint1_assertions.py

report:
	$(PYTHON) src/etl/loader.py report

dashboard:
	$(PYTHON) src/etl/loader.py dashboard

api:
	$(PYTHON) src/etl/loader.py api

clean:
	$(PYTHON) -c "from pathlib import Path; import shutil; root = Path.cwd(); targets = [root / 'db' / 'nifty100.db', root / 'db' / 'nifty100.db-wal', root / 'db' / 'nifty100.db-shm', root / 'output' / 'load_audit.csv', root / 'output' / 'validation_failures.csv', root / 'output' / 'report_summary.md', root / 'output' / 'dashboard.html', root / '.env.local']; [path.unlink() for path in targets if path.exists()]; [shutil.rmtree(cache, ignore_errors=True) for base in [root / 'src', root / 'tests', root / 'output', root / 'db'] for cache in base.rglob('__pycache__')]; shutil.rmtree(root / '.pytest_cache', ignore_errors=True); shutil.rmtree(root / '.mypy_cache', ignore_errors=True)"
