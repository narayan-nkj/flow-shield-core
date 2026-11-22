# CHAKRA-DPI

**Cross-Bank Fraud Velocity & Citizen Protection Infrastructure**  
*Seva First Innovation Challenge (SFIC) 2026 – Eastern Region (Junior / Undergraduate)*  
**Application ID:** `SFIC-WB-3789`  
**Theme:** Disaster Management & Community Safety (Community Cyber Safety)  

---

## 1. Quick Start & Virtual Environment Setup

### 1.1 Prerequisites
* Python 3.11+
* Standard multi-core CPU (No GPU required)

### 1.2 Virtual Environment Initialization
```bash
# 1. Clone repository and navigate to root
cd CHAKRA-DPI

# 2. Create Python virtual environment
python3 -m venv .venv

# 3. Activate virtual environment
# Linux / macOS:
source .venv/bin/activate
# Windows (PowerShell):
# .\.venv\Scripts\Activate.ps1

# 4. Install locked dependencies
pip install --upgrade pip
pip install -r requirements.txt

# 5. Initialize the 4 physically isolated SQLite databases
make init-db
# Or directly:
python3 src/init_dbs.py
```

### 1.3 Makefile Automation Targets
* `make setup` : Create virtualenv and install dependencies
* `make init-db` : Instantiate all 4 SQLite databases
* `make init-db-reset` : Delete and recreate all SQLite databases
* `make test` : Execute automated pytest suite
* `make run-api` : Launch Central Risk Relay FastAPI service (port 8000)
* `make run-ui` : Launch Streamlit Nodal Officer Review Dashboard (port 8501)
* `make eval` : Execute 4-Pillar Evaluation Suite

---

## 2. Architecture & Documentation
* [`CLAUDE.md`](file:///Users/narayanjha/Documents/Git-Projects/SFIC/CHAKRA-DPI/CLAUDE.md): System operating standards & precedence rules.
* [`docs/PRD.md`](file:///Users/narayanjha/Documents/Git-Projects/SFIC/CHAKRA-DPI/docs/PRD.md): Technical requirements and system architecture (WHAT & WHY).
* [`docs/EXECUTION_GUIDE.md`](file:///Users/narayanjha/Documents/Git-Projects/SFIC/CHAKRA-DPI/docs/EXECUTION_GUIDE.md): 30-Day Master Sprint Plan (WHEN & HOW).
* [`docs/PROGRESS.md`](file:///Users/narayanjha/Documents/Git-Projects/SFIC/CHAKRA-DPI/docs/PROGRESS.md): Master Phase and Day progress tracker.
* [`docs/DECISIONS.md`](file:///Users/narayanjha/Documents/Git-Projects/SFIC/CHAKRA-DPI/docs/DECISIONS.md): Architecture Decision Records (ADR) and conflict log.
* [`docs/data_dictionary.md`](file:///Users/narayanjha/Documents/Git-Projects/SFIC/CHAKRA-DPI/docs/data_dictionary.md): Comprehensive schema & privacy boundary matrix.
