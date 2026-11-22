.PHONY: setup init-db test run-api run-ui eval clean help

PYTHON ?= python3
PIP ?= pip3
VENV ?= .venv

help:
	@echo "CHAKRA-DPI Automation Tasks"
	@echo "---------------------------"
	@echo "make setup       : Create virtualenv and install dependencies"
	@echo "make init-db     : Instantiate all 4 SQLite databases"
	@echo "make init-db-reset : Wipe and recreate all 4 SQLite databases"
	@echo "make test        : Run pytest test suite"
	@echo "make run-api     : Start the Central Risk Relay FastAPI service"
	@echo "make run-ui      : Start the Streamlit Nodal Officer War-Room Dashboard"
	@echo "make eval        : Run the automated 4-Pillar Evaluation Suite"
	@echo "make clean       : Clean temporary files and caches"

setup:
	$(PYTHON) -m venv $(VENV)
	. $(VENV)/bin/activate && $(PIP) install --upgrade pip && $(PIP) install -r requirements.txt

init-db:
	$(PYTHON) src/init_dbs.py

init-db-reset:
	$(PYTHON) src/init_dbs.py --reset

test:
	$(PYTHON) -m pytest tests/ -v

run-api:
	$(PYTHON) -m uvicorn src.risk_service.api:app --host 0.0.0.0 --port 8000 --reload

run-ui:
	$(PYTHON) -m streamlit run ui/app.py --server.port 8501

eval:
	$(PYTHON) eval/evaluate_detection.py
	$(PYTHON) eval/evaluate_fairness.py
	$(PYTHON) eval/evaluate_privacy.py
	$(PYTHON) eval/benchmark_cpu.py

clean:
	rm -rf __pycache__ .pytest_cache htmlcov .coverage
	find . -type d -name "__pycache__" -exec rm -rf {} +
