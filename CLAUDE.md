# CLAUDE.md — CHAKRA-DPI Project Guidelines & Operating Standards

**Project Name:** CHAKRA-DPI (Cross-Bank Fraud Velocity & Citizen Protection Infrastructure)  
**Track:** Seva First Innovation Challenge (SFIC) 2026 – Eastern Region (Junior / Undergraduate)  
**Application ID:** `SFIC-WB-3789`  
**Theme:** Disaster Management & Community Safety (Community Cyber Safety)  
**Target Architecture:** CPU-First, Zero-New-Hardware, Zero PII Leakage, Human-in-the-Loop Advisory  

---

## 1. Document Precedence Rule

Two authoritative source documents govern this project:
1. `docs/PRD.md` — Technical Specification (WHAT and WHY)
2. `docs/EXECUTION_GUIDE.md` — 30-Day Plan & Starter Kit (WHEN and HOW)

### **The Rule of Precedence:**
* **Schemas, Formulas, Guardrails, and Requirements:** `docs/PRD.md` **WINS**.
* **Sequencing, Default Config Values, and Starter Code:** `docs/EXECUTION_GUIDE.md` **WINS**.
* **Conflict Protocol:** Any ambiguity, divergence, or conflict between the PRD and the Execution Guide **MUST** be logged in `docs/DECISIONS.md` and explicitly presented to the user for confirmation. It must **NEVER** be silently resolved by the agent.

---

## 2. Mandatory Engineering Principles & Non-Negotiable Guardrails

1. **Strict Advisory Role:**  
   The system generates advisory signals ($p \in [0, 1]$) only. Under **NO circumstances** shall automated fund freeze, lien placement, or blocking code exist in the codebase. All actions require manual intervention by Bank Nodal Officers / Competent Authorities.
2. **Zero PII Leakage across Bank Boundaries:**  
   The central risk relay (`data/central/risk_relay.db`) stores strictly pseudonymous HMAC tokens (64-character SHA-256 strings) and transformed transaction values ($\log(1+\text{Amount})$). Customer names, account numbers, Aadhaar numbers, phone numbers, and raw balances must **never** leave the bank-local vault (`data/banks/bank_{x}.db`).
3. **No Demographic or Protected Attributes in Feature Vectors:**  
   Machine learning vectors rely strictly on graph topology and transaction dynamics ($V_p, H_{\text{entropy}}, Z_{\text{dormancy}}, M_{\text{local}}$). Protected demographic indicators (gender, religion, caste, language, geographic location) are strictly excluded from the risk engine.
4. **Append-Only Cryptographic Audit Integrity:**  
   All compliance ledger and reviewer state transitions compute cryptographic hash chains using:
   $$\text{row\_hash} = \text{SHA256}(\text{prev\_hash} \parallel \text{payload\_json})$$
   where `prev_hash` of the genesis block is `0000000000000000000000000000000000000000000000000000000000000000`. Records are immutable.
5. **CPU-First / Zero GPU Dependency:**  
   All synthetic generation, NetworkX graph processing, Logistic Regression scoring, and Streamlit dashboards must execute on standard multi-core laptop CPUs without GPU acceleration or specialized hardware requirements.
6. **Statutory RBI Compliance (Draft KYC Directions 2026 Annex III):**  
   Strict tracking of the 60-day statutory timeline: Day 0 (Lien/Advisory log) $\rightarrow$ Day 20 (Customer notice explanation window) $\rightarrow$ Day 30 (Bank review cap) $\rightarrow$ Day 60 (LEA statutory ceiling).

---

## 3. Physical Storage & Boundary Architecture

To enforce physical isolation, storage is divided into **4 distinct, decoupled SQLite databases**:

| Database Path | Scope / Layer | Isolation Guarantee |
| :--- | :--- | :--- |
| `data/banks/bank_{a..e}.db` | Layer 1: Bank-Local Vaults | Contains raw PII, local balances, and reverse lookup table (`local_token_map`). Never accessed by central services. |
| `data/kms/hsm_mock.db` | Layer 2: Simulated KMS / HSM | Stores epoch-scoped 256-bit secrets, key rotation schedules, and audit access logs. Never stores transaction data. |
| `data/central/risk_relay.db` | Layer 3: Central Risk Relay | Ingests pseudonymous edges (`src_token`, `dst_token`, $\log(1+\text{Amt})$, $\Delta t$) and outputs advisory cases. Zero raw PII. |
| `data/audit/compliance_ledger.db` | Layer 4: Compliance & Audit | Stores officer decisions, generated vernacular notices, SLA tracking clocks, and grievance logs with SHA-256 hash chains. |

---

## 4. Development & Coding Standards

* **Runtime:** Python 3.11+
* **Type Safety & Schemas:** Use strict type hints and Pydantic models for all data exchange boundaries.
* **Database Access:** Always use parameterized SQL queries (`?`) to prevent injection. Ensure connections are safely opened and closed via context managers.
* **Bank ID Standardization:** Canonical bank identifier is uppercase `BANK_A` in all code, configs, and database fields. Database filenames are lowercase `bank_a.db` managed via helper function `get_bank_db_path(bank_id: str)`.
* **Testing:** All features must have unit and integration tests under `tests/` executed via `pytest`.
* **Reproducibility:** Fix random seeds (`seed: 42`) in all simulation, split, and training routines.

---

## 5. Phase Close Protocol

Before any phase is marked as completed in `docs/PROGRESS.md`, the following checklist **MUST** be verified and satisfied:

1. **Automated Verification:**
   - Execute the test suite for the phase: `pytest tests/test_<phase>.py -v`.
   - Ensure all tests pass with zero regressions.
2. **Boundary & Privacy Verification:**
   - Verify that no raw account IDs or customer names are written to `data/central/` or `data/audit/`.
   - Confirm pseudonymous tokens conform to 64-character hex format.
3. **Cryptographic Chain Validation (if compliance touched):**
   - Verify that all rows in `reviewer_decisions` or `grievance_disagreement_log` correctly validate: $\text{SHA256}(\text{prev\_hash} \parallel \text{payload\_json}) == \text{row\_hash}$.
4. **Documentation & Traceability:**
   - Update `docs/PROGRESS.md` with:
     - Exact status change (e.g., `COMPLETE`).
     - Deliverable file path(s).
     - Execution timestamp and test summary.
5. **Decisions & Conflicts Scan:**
   - Ensure any config, schema, or implementation deviations are logged in `docs/DECISIONS.md`.
   - Notify the user of any open questions or conflict resolutions.
6. **Workspace Hygiene:**
   - Confirm no untracked temporary scratch files or orphaned `.pyc` / `.DS_Store` files clutter the tree.

---

## 6. Project Structure Overview

```text
chakra-dpi/
├── CLAUDE.md                    # Project guidelines & precedence rules (this file)
├── configs/                     # Simulation & feature configurations
│   ├── simulation_v1.yaml
│   ├── features_v1.yaml
│   └── notice_templates/       # Vernacular advisory templates (en, bn, hi)
├── data/                        # 4 physically isolated SQLite databases (gitignored data)
│   ├── banks/                   # bank_a.db ... bank_e.db
│   ├── kms/                     # hsm_mock.db
│   ├── central/                 # risk_relay.db
│   └── audit/                   # compliance_ledger.db
├── docs/                        # Specifications, tracking & architecture docs
│   ├── PRD.md                   # Primary specification (WHAT & WHY)
│   ├── EXECUTION_GUIDE.md       # Master 30-day plan & starter code (WHEN & HOW)
│   ├── PROGRESS.md              # Master progress schedule
│   └── DECISIONS.md             # Architecture Decision Records & conflict logs
├── src/                         # Modular application packages
│   ├── simulator/               # IBM AMLSim-style synthetic account & scenario generators
│   ├── bank_local/              # Bank vault & local feature extraction (Z_dorm, M_local)
│   ├── token_service/           # Mock HSM, HMAC-SHA-256 tokenization, PSI benchmarks
│   ├── risk_service/            # NetworkX graph engine, calibrated LR model, FastAPI
│   └── compliance/              # Notice generator, RBI SLA tracker, hash-chained ledger
├── eval/                        # 4-Pillar evaluation scripts & CPU benchmarks
├── ui/                          # Streamlit 4-page Nodal Officer War-Room Dashboard
├── tests/                       # Automated pytest suite (Phase 1, Phase 2, E2E)
└── requirements.txt             # Locked project dependencies
```
