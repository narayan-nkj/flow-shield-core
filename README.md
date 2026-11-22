# CHAKRA-DPI

**Cross-Bank Fraud Velocity & Citizen Protection Infrastructure**  
*Seva First Innovation Challenge (SFIC) 2026 – Eastern Region (Junior / Undergraduate)*  
**Application ID:** `SFIC-WB-3789`  
**Theme:** Disaster Management & Community Safety (Community Cyber Safety)  

---

## 1. Quick Start & Virtual Environment Setup

### 1.1 Prerequisites
* Python 3.12 (standard) or Python 3.11+
* Standard multi-core CPU (No GPU required)

### 1.2 Virtual Environment Initialization
```bash
# 1. Clone repository and navigate to root
cd CHAKRA-DPI

# 2. Setup virtual environment and dependencies (Python 3.12)
make setup

# Or manually:
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 3. Initialize the 4 physically isolated SQLite databases
make init-db
# Or directly:
python3 src/init_dbs.py
```

### 1.3 Makefile Automation Targets
* `make setup` : Create virtualenv and install dependencies
* `make init-db` : Instantiate all 4 SQLite databases
* `make init-db-reset` : Delete and recreate all SQLite databases
* `make test` : Execute automated pytest suite
* `make check-links` : Verify markdown relative links across documentation
* `make run-api` : Launch Central Risk Relay FastAPI service (port 8000)
* `make run-ui` : Launch Streamlit Nodal Officer Review Dashboard (port 8501)
* `make eval` : Execute 4-Pillar Evaluation Suite
* `make clean` : Remove caches, temporary files, and pytest artifacts

---

## 2. Architecture & Documentation
* [`docs/PRD.md`](docs/PRD.md): Technical requirements and system architecture (Single Source of Truth; WHAT & WHY).
* [`docs/PROGRESS.md`](docs/PROGRESS.md): Master Phase and milestone progress tracker (Sequencing & Roadmap).
* [`docs/DECISIONS.md`](docs/DECISIONS.md): Architecture Decision Records (ADR) and conflict log.
* [`docs/data_dictionary.md`](docs/data_dictionary.md): Comprehensive schema & privacy boundary matrix.
* [`CLAUDE.md`](CLAUDE.md): Local project guidelines and operating standards (local only).
