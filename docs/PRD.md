# CHAKRA-DPI: Product Requirements Document (PRD) & Technical Specification

**Project Name:** CHAKRA-DPI (Cross-Bank Fraud Velocity & Citizen Protection Infrastructure)  
**Track:** Seva First Innovation Challenge (SFIC) 2026 – Eastern Region (Junior / Undergraduate)  
**Application ID:** `SFIC-WB-3789`  
**Theme:** Disaster Management & Community Safety (Community Cyber Safety)  

---

## 1. Executive Summary & Scope

### 1.1 Product Scope & Strict Guardrails
* **Core Purpose:** A lightweight, zero-new-hardware, CPU-first software layer designed to sit between bank-local infrastructure and national payment rails (NPCI / IDPIC / I4C). It detects cross-institutional high-velocity mule fund transfers while protecting innocent merchants from blanket account freezes through surgical lien advisories and explainable risk scoring.
* **Maturity & Deployment Scope:** Operating strictly in a synthetic research environment using mock HMAC keys and simulated payment logs. No live payment-rail integration, real customer PII, or automated fund freezing is performed.
* **Human-in-the-Loop Imperative:** All outputs are strictly advisory risk signals. The decision to place a lien, freeze an account, or escalate to LEA remains 100% under human authority (Bank Nodal Officers / Competent Authorities).

### 1.2 Target Personas
1. **Bank Nodal Officer (Fraud Operations):** Reviews flagged cases, verifies cross-bank coverage, inspects feature SHAP/coefficient explanations, and renders manual decisions.
2. **Compliance & Audit Officer:** Tracks statutory compliance under RBI Draft (KYC) Amendment Directions 2026 (Annex III), manages statutory countdowns (20+10+30 days), generates vernacular notices, and inspects immutable audit trails.
3. **Simulation Operator / SFIC Evaluator:** Triggers scenario-based attacks (e.g., Konnagar ₹5,00,000 scam, Durga Puja merchant surge, smurfing, unjoined bank leakage) to test model behavior, privacy boundaries, and system latency.

---

## 2. Functional & Non-Functional Requirements

### 2.1 Functional Requirements (FR)
* **FR-1 Multi-Bank Synthetic Data Generation:** Generate IBM AMLSim-style synthetic transaction ledgers for up to 50,000 accounts across 5 simulated banks (3 participating, 2 non-participating) containing normal users, local merchants, and injected fraud rings.
* **FR-2 Bank-Local Privacy & Pseudonymization:** Provide bank-isolated normalization and derivation of local features. Normalize raw identifiers into epoch-scoped HMAC-SHA-256 tokens using a 24-hour dual-key sliding window.
* **FR-3 Temporal Risk & Scoring Engine:** Ingest cross-bank edge logs to construct an in-memory directed multigraph $G_t = (V, E_t)$. Filter transactions under the statutory threshold ($\ge \$1,000$ / $\text{INR } 1,000$). Output baseline calibrated Logistic Regression scores $p \in [0, 1]$ categorized into advisory bands ($p \ge 0.85$, $0.35 \le p < 0.85$, $p < 0.35$).
* **FR-4 Nodal Officer Review Dashboard:** Display case evidence including graph sub-structures, signed feature contribution scores, institution coverage ratio (e.g., 3 of 5 banks participating), feed freshness indicators, and human action buttons.
* **FR-5 Vernacular Notice & RBI Statutory SLA Tracker:** Generate deterministic, templated customer advisories in English, Bengali, and Hindi. Track the 60-day statutory timeline:
  $$\text{Day 0 (Lien Log)} \rightarrow \text{Day 20 (Customer Notice Window)} \rightarrow \text{Day 30 (Bank Review Cap)} \rightarrow \text{Day 60 (LEA Ceiling)}$$
* **FR-6 Append-Only Hash-Chained Audit Ledger:** Store every system state transition (`features -> score -> officer decision -> notice generated -> SLA log -> customer disagreement`) in a cryptographic hash-chained audit database.
* **FR-7 Evaluation & Sensitivity Testing Suite:** Run automated scripts to benchmark Precision, Recall, PR-AUC, calibration curves, merchant false-alert rates, key rotation sensitivity, and CPU latency percentiles ($p_{50}, p_{95}, p_{99}$).

### 2.2 Non-Functional Requirements (NFR)
* **Privacy Transparency:** Treat tokens as strictly **pseudonymous**, explicitly documenting residual metadata linkability and providing comparative benchmarks against Private Set Intersection (PSI).
* **Algorithmic Fairness:** Exclude all protected demographic indicators (gender, religion, caste, language, location) from feature vectors.
* **Explainability:** Ensure all recommendations include signed feature contribution breakdowns and data freshness metrics.
* **CPU-First Performance:** Require zero GPU hardware; execute complete generation, graph traversal, scoring, and UI rendering on standard multi-core laptop CPUs.

---

## 3. System Architecture

The system utilizes a 4-layer decoupled microservice architecture to enforce physical data boundaries between bank firewalls and central risk aggregation.

```text
+-------------------------------------------------------------------------+
| LAYER 1: BANK-LOCAL NODES (Isolated per Bank: Bank A, B, C; D & E Unjoined)
| - Raw PII Vault (Account ID, Name, Merchant History, Balance)           |
| - Local Feature Extractor (Z_dormancy, M_local, Cold-Start Cohort)      |
| - Local Reverse Lookup Table (Token <-> Account ID, stays INSIDE bank)  |
+---------------------------|---------------------------------------------+
                            | (Leaves Bank: Normalized ID -> Token Request
                            |  + Min Local Features. ZERO RAW PII.)
============ STRICT PRIVACY BOUNDARY (No Name/Aadhaar/Acct ID) ============
                            v
+-------------------------------------------------------------------------+
| LAYER 2: MOCK TOKEN SERVICE (Simulated Multi-Party HSM / KMS)           |
| - Epoch-Scoped HMAC-SHA-256 (K_epoch, 256-bit mock key)                 |
| - Sliding 24h Dual-Key Overlap Window + Rotation + Revocation           |
| - Rate-Limited Matching + No Bulk Export + Key Access Audit Log         |
| - [Experimental Module]: Private Set Intersection (PSI) Cost/Latency Lab|
+---------------------------|---------------------------------------------+
                            | (Emits Pseudonymous Edge:
                            |  src_tok, dst_tok, log(1+Amt), dt, channel,
                            |  bank_id, epoch_id, event_ts)
                            v
+-------------------------------------------------------------------------+
| LAYER 3: CENTRAL RISK & TEMPORAL GRAPH SERVICE (FastAPI + NetworkX)     |
| - In-Memory Sliding-Window Temporal Multigraph G_t = (V, E_t)           |
| - Graph Invariants: V_p (Velocity), H_entropy (Fan-In/Out), 2-Hop Agg   |
| - Scoring Engine: Rule Baseline + Regularized Logistic Regression       |
|   (Hook for LightGBM / TGN later comparison) + Calibration              |
| - Provenance Engine: Coverage Ratio (3/5 banks) + Feed Freshness Flags  |
+---------------------------|---------------------------------------------+
                            | (Returns Advisory Tier + Signed Feature
                            |  Contributions + Linked Token Subgraph)
                            v
+-------------------------------------------------------------------------+
| LAYER 4: BANK REVIEW CONSOLE & COMPLIANCE ENGINE (Streamlit / FastAPI)  |
| - Nodal-Officer Dashboard (Case SYN-0042 view, Advisory-Only Banner)    |
| - Human Decision Capture (Refer Bank/LEA vs No Action + Reasoning)      |
| - Vernacular Notice Engine (EN / BN / HI) + FIU-IND STR / NCRP JSON     |
| - RBI Annex III SLA Clock (20d + 10d + 30d) + Grievance/Disagreement Log|
| - Append-Only Hash-Chained Audit Ledger                                 |
+-------------------------------------------------------------------------+
```

---

## 4. Database & Physical Isolation Schema

To prove that raw customer identity never leaves bank premises, storage is split into **4 distinct SQLite database files**.

### 4.1 Bank-Local Vault (`data/banks/bank_a.db`)
* **`accounts`**: `account_id` (PK), `bank_id`, `synthetic_name`, `account_type` (`retail`, `kirana_merchant`, `student`, `nodal_whitelisted`), `merchant_size_tier`, `account_age_days`, `balance_inr`, `mu_90d`, `sigma_90d`, `m_local_score`.
* **`raw_transactions`**: `txn_id` (PK), `src_account_id`, `dst_account_id`, `amount_inr`, `channel` (`UPI`, `IMPS`, `RTGS`), `timestamp`, `scenario_label`.
* **`local_token_map`**: `token_hash` (PK), `account_id`, `epoch_id`, `created_at`.

### 4.2 Mock HSM / Key Management Store (`data/kms/hsm_mock.db`)
* **`epoch_keys`**: `epoch_id` (PK), `mock_secret_hex`, `valid_from`, `valid_to`, `overlap_until`, `is_revoked`.
* **`kms_access_logs`**: `log_id` (PK), `requesting_bank_id`, `epoch_id`, `operation` (`TOKENIZE`, `ROTATE`, `REVOKE`), `timestamp`.

### 4.3 Central Risk & Temporal Graph Store (`data/central/risk_relay.db`)
* **`pseudonymous_edges`**: `edge_id` (PK), `src_token`, `dst_token`, `log_amount` ($\log(1+\text{Amt})$), `delta_t_sec`, `channel_id`, `source_bank_id`, `epoch_id`, `event_ts`, `ingested_ts`.
* **`advisory_cases`**: `case_id` (PK), `target_token`, `score_p`, `score_band` (`PRIORITY`, `ADDITIONAL_REVIEW`, `NO_ELEVATED_ALERT`), `feature_values_json`, `feature_contributions_json`, `linked_tokens_json`, `participating_banks_count`, `total_banks_count`, `stale_feed_flag`, `model_version`, `feature_version`, `run_id`, `created_at`.

### 4.4 Append-Only Compliance & Audit Ledger (`data/audit/compliance_ledger.db`)
* **`reviewer_decisions`**: `decision_id` (PK), `case_id`, `reviewer_id`, `decision_type` (`REFER_BANK_LEA`, `NO_ACTION`, `REQUEST_CUSTOMER_EXPLANATION`), `officer_reasoning`, `decided_at`, `prev_hash`, `row_hash`.
* **`customer_notices`**: `notice_id` (PK), `case_id`, `language` (`EN`, `BN`, `HI`), `template_version`, `reason_codes_json`, `notice_body`, `generated_at`.
* **`sla_clock_events`**: `clock_id` (PK), `case_id`, `t0_advisory_ts`, `d20_explanation_due`, `d30_bank_decision_due`, `d60_lea_hard_cap`, `current_status`, `extension_note`.
* **`grievance_disagreement_log`**: `entry_id` (PK), `case_id`, `actor` (`CUSTOMER`, `OFFICER`), `statement_text`, `escalation_ref`, `logged_at`, `prev_hash`, `row_hash`.

---

## 5. Mathematical Specification & Modeling

### 5.1 Derived Graph & Local Features

1. **Pass-Through Velocity ($V_p$):**
   $$V_p(u, \Delta T) = \left( \frac{\min \left( \sum_{e \in \text{In}} w(e), \sum_{e \in \text{Out}} w(e) \right)}{\sum_{e \in \text{In}} w(e) + \epsilon} \right) \cdot \exp \left( -\lambda \cdot \overline{\tau}_{\text{hold}}(u) \right)$$
   Where $w(e) = \log(1 + \text{Amount})$ and $\overline{\tau}_{\text{hold}}(u)$ is the mean holding time inside window $\Delta T$.

2. **Recipient Distribution Entropy ($H_{\text{entropy}}$):**
   $$H_{\text{out}}(u, \Delta T) = -\sum_{v \in N_{\text{out}}(u, \Delta T)} p_{uv} \log_2 (p_{uv})$$
   Where $p_{uv} = \frac{\text{Amount}(u \to v)}{\sum_{k \in N_{\text{out}}} \text{Amount}(u \to k)}$.

3. **Dormancy-to-Spike Z-Score ($Z_{\text{dormancy}}$):**
   $$Z_{\text{dorm}}(u, t) = \frac{V_{24\text{h}}(u, t) - \mu_{90\text{d}}(u)}{\sigma_{90\text{d}}(u) + \epsilon_0}$$
   (Cold-start accounts $< 14$ days fall back to peer-cohort baseline metrics $\mu_{\text{cohort}}, \sigma_{\text{cohort}}$).

4. **Merchant Protection Composite Score ($M_{\text{local}}$):**
   $$M_{\text{local}}(u) = w_a \cdot R_{\text{repeat}} + w_b \cdot (1 - S_{\text{sweep}}) + w_c \cdot T_{\text{age\_tier}}$$
   Where $R_{\text{repeat}}$ is the ratio of repeat local customers, $S_{\text{sweep}}$ is the 10-minute balance sweep-out ratio, and $T_{\text{age\_tier}}$ is account age stability.

### 5.2 Baseline Calibrated Model
Primary scoring uses regularized Logistic Regression calibrated via Platt Scaling / Isotonic Regression:

$$p(u) = \sigma \left( b + w_1 V_p + w_2 H_{\text{entropy}} + w_3 Z_{\text{dormancy}} - w_4 M_{\text{local}} \right)$$

Where $\sigma(z) = \frac{1}{1 + e^{-z}}$. Feature contribution vector for explainability:

$$C_i = w_i \cdot x_i$$

---

## 6. Evaluation Framework

The platform includes an automated 4-pillar evaluation suite (`eval/run_all.py`):

| Pillar | Focus Metrics | Primary Benchmark Objectives |
| :--- | :--- | :--- |
| **1. Detection Performance** | Precision, Recall, PR-AUC, ECE (Calibration Error) | Measure baseline ability to identify rapid smurfing & concentrator rings across 5 banks under synthetic splits. |
| **2. Proportionality & Fairness** | False Alert Rate on Merchants, Festival Subgroup Error | Benchmark false flag rate on local Kirana shops during simulated 10$\times$ Durga Puja sales volume. |
| **3. Privacy & Security** | Linkability vs. Overlap Window, Revocation Latency | Measure key rotation impact on graph linkage continuity; test dictionary attack resilience. |
| **4. System Throughput** | Edges/sec, $p_{50}, p_{95}, p_{99}$ Latency (ms) | Evaluate CPU-only graph execution performance for up to 50,000 synthetic edges. |

---

## 7. Technology Stack & Repository Structure

### 7.1 Tech Stack
* **Language & Runtime:** Python 3.11+
* **Data Processing & Graph:** `numpy`, `pandas`, `networkx`, `scipy`
* **Cryptography:** Python native `hmac`, `hashlib`, `secrets`
* **ML & Metrics:** `scikit-learn` (LogisticRegression, CalibratedClassifierCV)
* **API Layer:** `FastAPI`, `uvicorn`, `pydantic`
* **Storage:** SQLite 3 (4 physically decoupled database files)
* **Frontend Dashboard:** `Streamlit`, `Plotly`, `PyVis`
* **Testing & Infrastructure:** `pytest`, `Docker`

### 7.2 Monorepo Layout
```text
chakra-dpi/
├── configs/
│   ├── simulation_v1.yaml
│   ├── features_v1.yaml
│   └── notice_templates/
│       ├── en.json
│       ├── bn.json
│       └── hi.json
├── src/
│   ├── simulator/
│   │   ├── generator.py
│   │   └── scenarios.py
│   ├── bank_local/
│   │   ├── vault.py
│   │   └── local_features.py
│   ├── token_service/
│   │   ├── hsm_mock.py
│   │   └── psi_benchmark.py
│   ├── risk_service/
│   │   ├── graph_engine.py
│   │   ├── baseline_model.py
│   │   ├── explainer.py
│   │   └── api.py
│   └── compliance/
│       ├── notice_engine.py
│       ├── sla_tracker.py
│       └── audit_ledger.py
├── eval/
│   ├── evaluate_detection.py
│   ├── evaluate_fairness.py
│   ├── evaluate_privacy.py
│   └── benchmark_cpu.py
├── ui/
│   └── app.py
├── tests/
├── docs/
└── README.md
```

---

## 8. User Interface Specifications

The Streamlit dashboard (`ui/app.py`) presents 4 primary operating views:

1. **Scenario & Privacy Boundary Inspector:** Dual-pane window displaying the live Konnagar ₹5,00,000 scam flow. Shows raw bank records on the left and transformed pseudonymous tokens ($64$-char HMAC string) + $\log(1+\text{Amt})$ on the right to demonstrate zero PII leakage.
2. **Nodal Officer War-Room Desk:** Details case records (e.g., `CASE SYN-0042`), uncalibrated placeholder score bands, signed feature contribution bar charts ($+V_p, +Z_{\text{dormancy}}, -M_{\text{local}}$), data freshness indicators, bank coverage ratio ($3/5$), human action logs, and disagreement entries.
3. **Vernacular Notice & RBI SLA Desk:** Live language toggle (English, Bengali, Hindi) rendering dynamic customer advisory letters, lien math display (e.g., ₹85,000 balance unrestricted, ₹2,500 disputed lien), statutory 60-day deadline trackers, and exportable NCRP/STR JSON formats.
4. **Evaluation & Governance Laboratory:** Interactive parameter controls for score thresholds, calibration curves, merchant false-positive breakdowns, Durga Puja volume stress tests, and HMAC key rotation trade-off graphs.

---

## 9. 30-Day Execution Roadmap

| Milestone Phase | Timeline | Core Engineering Tasks | Key Deliverables |
| :--- | :--- | :--- | :--- |
| **Phase 1: Foundations** | Days 1–10 | Monorepo set up, SQLite schemas built, synthetic generator developed (5 banks, Konnagar & festival scenarios), HMAC tokenizer and feature extraction modules implemented. | Passing tests for zero PII leakage and HMAC key rotation; `data_dictionary.md` finalized. |
| **Phase 2: Core Scoring & Compliance** | Days 11–20 | Logistic Regression baseline trained & calibrated; FastAPI risk endpoints built; EN/BN/HI notice generators, SLA clock, and hash-chained audit logger completed. | Evaluation scripts (Pillars 1–3) operational; `model_card.md` published. |
| **Phase 3: UI & Hardening** | Days 21–30 | 4-page Streamlit War-Room created; CPU performance benchmark script executed; end-to-end synthetic demonstration recorded; repository prepared for evaluation. | Fully functioning CPU-first demo application; CPU benchmark report ($p_{50}/p_{95}/p_{99}$). |