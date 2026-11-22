# CHAKRA-DPI: 30-Day Step-by-Step Execution Guide & Starter Kit

**Project Name:** CHAKRA-DPI (Cross-Bank Fraud Velocity & Citizen Protection Infrastructure)  
**Track:** Seva First Innovation Challenge (SFIC) 2026 – Eastern Region (Junior / Undergraduate)  
**Application ID:** `SFIC-WB-3789`  
**Target:** 30-Day Modular Build & Evaluation Sprint  

---

## 1. Day 1 Immediate Kickoff (First 3 Hours Execution)

### 1.1 Terminal Commands & Directory Setup

Run the following commands in your shell to set up the clean virtual environment and repository structure:

```bash
# 1. Create and enter repository directory
mkdir chakra-dpi && cd chakra-dpi

# 2. Initialize git repository
git init

# 3. Create virtual environment
python -m venv .venv

# 4. Activate virtual environment
# Windows (PowerShell): .\.venv\Scripts\Activate.ps1
# Linux / macOS: source .venv/bin/activate

# 5. Install required dependencies
pip install numpy pandas networkx scikit-learn scipy pyyaml fastapi uvicorn streamlit plotly pyvis pytest pydantic
pip freeze > requirements.txt

# 6. Create modular directory structure
mkdir -p configs/notice_templates \
         data/banks data/kms data/central data/audit \
         src/simulator src/bank_local src/token_service src/risk_service src/compliance \
         eval ui tests docs
```

---

### 1.2 Configuration Specifications

#### `configs/simulation_v1.yaml`
```yaml
seed: 42
simulation:
  time_horizon_days: 7
  total_accounts: 5000
  participating_banks:
    - BANK_A
    - BANK_B
    - BANK_C
  unjoined_banks:
    - BANK_D
    - BANK_E
  account_distribution:
    retail: 0.85
    kirana_merchant: 0.10
    student: 0.04
    nodal_whitelisted: 0.01

scenarios:
  konnagar_scam:
    disputed_amount_inr: 500000
    hops: 5
    leakage_bank: BANK_D
  durga_puja_surge:
    volume_multiplier: 10.0
    duration_hours: 48
  student_fee_passthrough:
    amount_range_inr: [25000, 75000]
    hold_time_max_sec: 180
```

#### `configs/features_v1.yaml`
```yaml
temporal_windows:
  rolling_window_sec: 3600       # 1-hour window for graph calculation
  burst_window_sec: 600          # 10-minute burst window
  velocity_decay_lambda: 0.00385 # ln(2) / 180 seconds half-life

statutory:
  rbi_threshold_inr: 1000        # Minimum suspected transaction limit
  cold_start_days: 14            # Fallback to cohort statistics if account age < 14 days

risk_bands:
  priority_threshold: 0.85
  additional_review_threshold: 0.35
  status: "CALIBRATED_UNVERIFIED_ADVISORY_ONLY"
```

---

### 1.3 Physical Isolation Schema Initializer (`src/init_dbs.py`)

Save and run this script to instantiate the four physically isolated SQLite databases:

```python
import os
import sqlite3

def init_bank_db(bank_id: str):
    db_path = f"data/banks/{bank_id.lower()}.db"
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS accounts (
        account_id TEXT PRIMARY KEY,
        bank_id TEXT NOT NULL,
        synthetic_name TEXT NOT NULL,
        account_type TEXT CHECK(account_type IN ('retail', 'kirana_merchant', 'student', 'nodal_whitelisted')),
        merchant_size_tier TEXT,
        account_age_days INTEGER NOT NULL,
        balance_inr REAL NOT NULL,
        mu_90d REAL DEFAULT 0.0,
        sigma_90d REAL DEFAULT 1.0,
        m_local_score REAL DEFAULT 0.5
    );
    """)
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS raw_transactions (
        txn_id TEXT PRIMARY KEY,
        src_account_id TEXT NOT NULL,
        dst_account_id TEXT NOT NULL,
        amount_inr REAL NOT NULL,
        channel TEXT CHECK(channel IN ('UPI', 'IMPS', 'RTGS')),
        timestamp TEXT NOT NULL,
        scenario_label TEXT
    );
    """)
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS local_token_map (
        token_hash TEXT PRIMARY KEY,
        account_id TEXT NOT NULL,
        epoch_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(account_id) REFERENCES accounts(account_id)
    );
    """)
    
    conn.commit()
    conn.close()
    print(f"[+] Bank Database initialized: {db_path}")

def init_kms_db():
    db_path = "data/kms/hsm_mock.db"
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS epoch_keys (
        epoch_id TEXT PRIMARY KEY,
        mock_secret_hex TEXT NOT NULL,
        valid_from TEXT NOT NULL,
        valid_to TEXT NOT NULL,
        overlap_until TEXT NOT NULL,
        is_revoked INTEGER DEFAULT 0
    );
    """)
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS kms_access_logs (
        log_id INTEGER PRIMARY KEY AUTOINCREMENT,
        requesting_bank_id TEXT NOT NULL,
        epoch_id TEXT NOT NULL,
        operation TEXT NOT NULL,
        timestamp TEXT NOT NULL
    );
    """)
    
    conn.commit()
    conn.close()
    print(f"[+] Mock KMS Database initialized: {db_path}")

def init_risk_db():
    db_path = "data/central/risk_relay.db"
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS pseudonymous_edges (
        edge_id TEXT PRIMARY KEY,
        src_token TEXT NOT NULL,
        dst_token TEXT NOT NULL,
        log_amount REAL NOT NULL,
        delta_t_sec REAL NOT NULL,
        channel_id TEXT NOT NULL,
        source_bank_id TEXT NOT NULL,
        epoch_id TEXT NOT NULL,
        event_ts TEXT NOT NULL,
        ingested_ts TEXT NOT NULL
    );
    """)
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS advisory_cases (
        case_id TEXT PRIMARY KEY,
        target_token TEXT NOT NULL,
        score_p REAL NOT NULL,
        score_band TEXT CHECK(score_band IN ('PRIORITY', 'ADDITIONAL_REVIEW', 'NO_ELEVATED_ALERT')),
        feature_values_json TEXT NOT NULL,
        feature_contributions_json TEXT NOT NULL,
        linked_tokens_json TEXT NOT NULL,
        participating_banks_count INTEGER NOT NULL,
        total_banks_count INTEGER NOT NULL,
        stale_feed_flag INTEGER DEFAULT 0,
        model_version TEXT NOT NULL,
        feature_version TEXT NOT NULL,
        run_id TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    """)
    
    conn.commit()
    conn.close()
    print(f"[+] Central Risk Relay Database initialized: {db_path}")

def init_compliance_db():
    db_path = "data/audit/compliance_ledger.db"
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS reviewer_decisions (
        decision_id TEXT PRIMARY KEY,
        case_id TEXT NOT NULL,
        reviewer_id TEXT NOT NULL,
        decision_type TEXT CHECK(decision_type IN ('REFER_BANK_LEA', 'NO_ACTION', 'REQUEST_CUSTOMER_EXPLANATION')),
        officer_reasoning TEXT NOT NULL,
        decided_at TEXT NOT NULL,
        prev_hash TEXT NOT NULL,
        row_hash TEXT NOT NULL
    );
    """)
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS customer_notices (
        notice_id TEXT PRIMARY KEY,
        case_id TEXT NOT NULL,
        language TEXT CHECK(language IN ('EN', 'BN', 'HI')),
        template_version TEXT NOT NULL,
        reason_codes_json TEXT NOT NULL,
        notice_body TEXT NOT NULL,
        generated_at TEXT NOT NULL
    );
    """)
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS sla_clock_events (
        clock_id TEXT PRIMARY KEY,
        case_id TEXT NOT NULL,
        t0_advisory_ts TEXT NOT NULL,
        d20_explanation_due TEXT NOT NULL,
        d30_bank_decision_due TEXT NOT NULL,
        d60_lea_hard_cap TEXT NOT NULL,
        current_status TEXT NOT NULL,
        extension_note TEXT
    );
    """)
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS grievance_disagreement_log (
        entry_id TEXT PRIMARY KEY,
        case_id TEXT NOT NULL,
        actor TEXT CHECK(actor IN ('CUSTOMER', 'OFFICER')),
        statement_text TEXT NOT NULL,
        escalation_ref TEXT,
        logged_at TEXT NOT NULL,
        prev_hash TEXT NOT NULL,
        row_hash TEXT NOT NULL
    );
    """)
    
    conn.commit()
    conn.close()
    print(f"[+] Compliance & Audit Ledger Database initialized: {db_path}")

if __name__ == "__main__":
    for bank in ["bank_a", "bank_b", "bank_c", "bank_d", "bank_e"]:
        init_bank_db(bank)
    init_kms_db()
    init_risk_db()
    init_compliance_db()
    print("\n[✔] All 4 physically isolated SQLite databases successfully instantiated.")
```

---

## 2. Comprehensive 30-Day Execution Plan

```text
===================================================================================
PHASE 1: FOUNDATIONS & SYNTHETIC PIPELINE (Days 1 - 10)
===================================================================================
Day 1  : Set up environment, folder architecture, YAML configs, and isolated SQLite schema.
Day 2  : Implement `src/simulator/generator.py` for synthetic accounts and normal transaction flows.
Day 3  : Build `src/simulator/scenarios.py` (Konnagar Scam, Durga Puja Surge, Pass-through, Warm-up).
Day 4  : Finalize transaction generation scripts and log verification.
Day 5  : Implement `src/bank_local/local_features.py` for $Z_{\text{dormancy}}$ and $M_{\text{local}}$ computation.
Day 6  : Develop `src/token_service/hsm_mock.py` (HMAC SHA-256 tokenization and 24h key rotation).
Day 7  : Implement `src/token_service/psi_benchmark.py` for comparative compute cost analysis.
Day 8  : Build `src/risk_service/graph_engine.py` using NetworkX for temporal edge aggregation.
Day 9  : Implement graph invariant functions for Pass-Through Velocity ($V_p$) and Entropy ($H_{\text{entropy}}$).
Day 10 : Execute Phase 1 integration tests (`tests/test_phase1.py`) and publish `docs/threat_model.md`.

===================================================================================
PHASE 2: MODELING, RISK API & COMPLIANCE ENGINE (Days 11 - 20)
===================================================================================
Day 11 : Prepare temporal chronological train/validation/test dataset splits.
Day 12 : Implement `src/risk_service/baseline_model.py` (Rule baseline & Regularized Logistic Regression).
Day 13 : Perform Platt Scaling / Isotonic calibration; export calibration curves and metric plots.
Day 14 : Build `src/risk_service/explainer.py` for signed feature contribution scoring ($w_i \cdot x_i$).
Day 15 : Develop `src/risk_service/api.py` (FastAPI endpoints for edge ingestion and risk queries).
Day 16 : Implement `src/compliance/notice_engine.py` (Deterministic EN/BN/HI templates & NCRP/STR JSON).
Day 17 : Build `src/compliance/sla_tracker.py` for tracking the statutory 60-day deadline timeline.
Day 18 : Implement `src/compliance/audit_ledger.py` with append-only SHA-256 hash-chaining.
Day 19 : Execute Pillar 1 & 2 evaluation scripts (`eval/evaluate_detection.py`, `eval/evaluate_fairness.py`).
Day 20 : Execute Pillar 3 privacy evaluation (`eval/evaluate_privacy.py`) and publish `docs/model_card.md`.

===================================================================================
PHASE 3: WAR-ROOM DASHBOARD, BENCHMARKING & FINAL PACKAGING (Days 21 - 30)
===================================================================================
Day 21 : Build Streamlit Dashboard (`ui/app.py`) Page 1: Live Scenario & Privacy Boundary Inspector.
Day 22 : Build Dashboard Page 2: Nodal Officer Review Console & Proportionality Calculator.
Day 23 : Build Dashboard Page 3: Vernacular Notice Generator & RBI Statutory SLA Tracker.
Day 24 : Build Dashboard Page 4: Evaluation & Governance Laboratory.
Day 25 : Develop `eval/benchmark_cpu.py` for measuring latency ($p_{50}, p_{95}, p_{99}$) and throughput.
Day 26 : Implement Docker containerization (`Dockerfile`, `docker-compose.yml`).
Day 27 : Conduct end-to-end integration testing and automated verification runs.
Day 28 : Write comprehensive `README.md` with system setup instructions and benchmark metrics.
Day 29 : Record 3-minute video demonstration highlighting scenario simulation and privacy isolation.
Day 30 : Update repository submission links and submit project materials for evaluation.
===================================================================================
```

---

## 3. Mandatory Engineering Principles & Guardrails

1. **Strict Advisory Role:** The system generates advisory signals ($p \in [0, 1]$) only. No automated freeze or lien execution logic exists anywhere in the codebase.
2. **Zero PII Leakage:** Central risk DB (`data/central/risk_relay.db`) stores strictly pseudonymous HMAC tokens ($64$-character SHA-256 hashes) and transformed log amounts ($\log(1+\text{Amount})$).
3. **No Demographic Features:** Machine learning feature vectors rely strictly on graph topology and transaction dynamics ($V_p, H_{\text{entropy}}, Z_{\text{dormancy}}, M_{\text{local}}$).
4. **Append-Only Integrity:** Audit logs compute cryptographic hash chains using $\text{SHA256}(\text{prev\_hash} \parallel \text{payload\_json})$ to guarantee non-repudiation.