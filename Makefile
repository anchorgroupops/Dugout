PY ?= python3
VENV ?= /tmp/dugout-venv
ACT := . $(VENV)/bin/activate

.PHONY: install-dev test cov cov-html run clean help

help:
	@echo "Targets:"
	@echo "  install-dev  Create venv and install dev dependencies"
	@echo "  test         Run pytest"
	@echo "  cov          Run pytest with coverage (term-missing)"
	@echo "  cov-html     Run pytest with HTML coverage report (htmlcov/)"
	@echo "  run          Run API server (gunicorn on :8000)"
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
	$(ACT) && gunicorn -b 0.0.0.0:8000 api:app

clean:
	rm -rf $(VENV) .pytest_cache htmlcov .coverage coverage.xml
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
