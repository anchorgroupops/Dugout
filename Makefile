PY ?= python3
VENV ?= .venv
ACT := . $(VENV)/bin/activate

.PHONY: install-dev test cov cov-html run clean help

help:
	@echo "Targets:"
	@echo "  install-dev  Create venv and install dev dependencies"
	@echo "  test         Run pytest"
	@echo "  cov          Run pytest with coverage (term-missing)"
	@echo "  cov-html     Run pytest with HTML coverage report (htmlcov/)"
	@echo "  run          Run dev Flask app (sync_daemon.py on :5000) — legacy local convenience"
	@echo "  clean        Remove venv, caches, coverage artifacts"

install-dev:
	$(PY) -m venv $(VENV)
	$(ACT) && pip install --upgrade pip && pip install -r requirements-dev.txt

test:
	$(ACT) && pytest

cov:
	$(ACT) && pytest --cov=. --cov-report=term-missing --cov-report=xml

cov-html:
	$(ACT) && pytest --cov=. --cov-report=html

run:
	@echo "legacy local convenience — production uses docker compose (see docker-compose.sharks.yml)"
	$(ACT) && python tools/sync_daemon.py

clean:
	rm -rf $(VENV) .pytest_cache htmlcov .coverage coverage.xml
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
