.PHONY: setup init-db init-db-reset test run-api run-ui eval clean help check-links

PYTHON ?= python3.12
VENV ?= .venv
VENV_PYTHON = $(VENV)/bin/python
VENV_PIP = $(VENV)/bin/pip

help:
	@echo "CHAKRA-DPI Automation Tasks"
	@echo "---------------------------"
	@echo "make setup         : Create Python 3.12 virtualenv and install dependencies"
	@echo "make init-db       : Instantiate all 4 SQLite databases"
	@echo "make init-db-reset : Wipe and recreate all 4 SQLite databases"
	@echo "make test          : Run pytest test suite"
	@echo "make check-links   : Run markdown relative link checker"
	@echo "make run-api       : Start the Central Risk Relay FastAPI service"
	@echo "make run-ui        : Start the Streamlit Nodal Officer War-Room Dashboard"
	@echo "make eval          : Run the automated 4-Pillar Evaluation Suite"
	@echo "make clean         : Clean temporary files and caches"

setup:
	$(PYTHON) -m venv $(VENV)
	$(VENV_PIP) install --upgrade pip
	$(VENV_PIP) install -r requirements.txt

init-db:
	@if [ -f $(VENV_PYTHON) ]; then $(VENV_PYTHON) src/init_dbs.py; else $(PYTHON) src/init_dbs.py; fi

init-db-reset:
	@if [ -f $(VENV_PYTHON) ]; then $(VENV_PYTHON) src/init_dbs.py --reset; else $(PYTHON) src/init_dbs.py --reset; fi

test:
	@if [ -f $(VENV_PYTHON) ]; then $(VENV_PYTHON) -m pytest tests/ -v; else $(PYTHON) -m pytest tests/ -v; fi

check-links:
	@if [ -f $(VENV_PYTHON) ]; then $(VENV_PYTHON) scripts/check_links.py; else $(PYTHON) scripts/check_links.py; fi

run-api:
	@if [ -f $(VENV_PYTHON) ]; then $(VENV_PYTHON) -m uvicorn src.risk_service.api:app --host 0.0.0.0 --port 8000 --reload; else $(PYTHON) -m uvicorn src.risk_service.api:app --host 0.0.0.0 --port 8000 --reload; fi

run-ui:
	@if [ -f $(VENV_PYTHON) ]; then $(VENV_PYTHON) -m streamlit run ui/app.py --server.port 8501; else $(PYTHON) -m streamlit run ui/app.py --server.port 8501; fi

eval:
	@if [ -f $(VENV_PYTHON) ]; then \
		$(VENV_PYTHON) eval/evaluate_detection.py && \
		$(VENV_PYTHON) eval/evaluate_fairness.py && \
		$(VENV_PYTHON) eval/evaluate_privacy.py && \
		$(VENV_PYTHON) eval/benchmark_cpu.py; \
	else \
		$(PYTHON) eval/evaluate_detection.py && \
		$(PYTHON) eval/evaluate_fairness.py && \
		$(PYTHON) eval/evaluate_privacy.py && \
		$(PYTHON) eval/benchmark_cpu.py; \
	fi

clean:
	rm -rf __pycache__ .pytest_cache htmlcov .coverage
	find . -type d -name "__pycache__" -exec rm -rf {} +
