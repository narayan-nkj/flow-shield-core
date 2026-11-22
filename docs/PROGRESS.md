# CHAKRA-DPI: Master Progress Schedule & Tracking

**Project Name:** CHAKRA-DPI (Cross-Bank Fraud Velocity & Citizen Protection Infrastructure)  
**Track:** Seva First Innovation Challenge (SFIC) 2026 – Eastern Region (Junior / Undergraduate)  
**Application ID:** `SFIC-WB-3789`  
**Master Plan Reference:** `docs/PRD.md` (Single Source of Truth; Sequencing tracked in `docs/PROGRESS.md`)  
**Last Updated:** 2026-11-22  

---

## 1. Master Milestone Summary

* **Phase 1 (Days 1–10):** Foundations & Synthetic Pipeline (Storage, Simulation, HSM Mock, PSI, Graph Engine, Threat Model)
* **Phase 2 (Days 11–20):** Modeling, Risk API & Compliance Engine (Splits, LR Baseline, Calibration, Explainer, API, Notices, SLA, Ledger, Evaluation)
* **Phase 3 (Days 21–30):** War-Room Dashboard, Benchmarking & Final Packaging (Streamlit UI, CPU Benchmarks, Docker, E2E Tests, Docs, Video Script, Submission)

---

## 2. Phase-by-Phase Execution Tracker

| Phase / Step ID | Guide Day | Description / Task | Target Deliverables | Status | Notes / Execution Log |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Phase 01** | Day 1 | Environment setup, folder architecture, YAML configs, isolated SQLite schema | `configs/simulation_v1.yaml`, `configs/features_v1.yaml`, `src/init_dbs.py`, `docs/data_dictionary.md`, 4 DBs | **COMPLETE** | 7/7 tests passed in `test_phase1_schema.py`. Zero PII columns in central/audit DBs. Append-only triggers & FKs verified. (2026-11-22) |
| **Phase 02** | Day 2 | Synthetic accounts & normal transaction flow generator | `src/simulator/generator.py`, `docs/generated/sim_summary.md` | **COMPLETE** | 13/13 tests passed in test suite. Deterministic AMLSim normal generator instantiated across 5 banks (28k+ txns). Zero cross-bank PII leakage. (2026-11-22) |
| **Phase 03** | Day 3 | Fraud & stress scenario generators | `src/simulator/scenarios.py`, `docs/generated/scenarios.md` | **COMPLETE** | 8 composable scenarios (Konnagar scam, Puja surge, student pass-through, smurfing, etc.). Ground truth in data/ground_truth/labels.csv. (2026-11-22) |
| **Phase 04** | Day 4 | Transaction generation pipeline & log sanity verification | `src/simulator/verify_scenarios.py`, `docs/generated/scenario_verification.md` | **COMPLETE** | 19/19 tests passed. Verified hold times (mules vs students vs merchants) & YAML parameter matching. (2026-11-22) |
| **Phase 05** | Day 5 | Bank-local feature extractor ($Z_{\text{dormancy}}, M_{\text{local}}$) | `src/bank_local/vault.py`, `src/bank_local/local_features.py` | **COMPLETE** | 25/25 tests passed. BankVault physical isolation & LocalFeaturePayload fail-closed Pydantic whitelist verified. (2026-11-22) |
| **Phase 06** | Day 6 | Mock HSM / Token Service (HMAC-SHA256, 24h key rotation) | `src/token_service/hsm_mock.py`, `docs/privacy_notes.md` | **COMPLETE** | 30/30 tests passed. Mandatory zero PII leak audit passed. 24h key rotation, rate limiting, and edge pipeline operational. (2026-11-22) |
| **Phase 07** | Day 7 | PSI benchmark module for comparative compute cost analysis | `src/token_service/psi_benchmark.py`, `docs/generated/psi_vs_hmac.md` | **COMPLETE** | 34/34 tests passed. Empirical lab completed (1k..50k IDs). DH-PSI vs HMAC trade-offs documented with Plotly dataset. (2026-11-22) |
| **CR02-A** | Refactor | Repository hygiene, security untracking, PRD single source of truth, Python 3.12 | `.gitignore`, `scripts/check_links.py`, `pyproject.toml`, `.python-version` | **COMPLETE** | Untracked CLAUDE.md, 3 presentation PDFs, ground truth CSVs. Removed EXECUTION_GUIDE.md. Rebuilt .venv with Python 3.12. (2026-11-22) |
| **Phase 07B** | Day 10 | Phase 1 integration tests & comprehensive threat model | `tests/test_phase1.py`, `docs/threat_model.md` | NOT STARTED | Confirms zero PII egress & privacy boundary |
| **Phase 08** | Days 8–9 | Temporal Graph Engine ($V_p$ velocity, $H_{\text{entropy}}$, 2-hop aggregation) | `src/risk_service/graph_engine.py` | NOT STARTED | NetworkX sliding-window multigraph |
| **Phase 08A** | Day 11 | Chronological train/validation/test dataset splits | `src/risk_service/splits.py` | NOT STARTED | Leakage-free temporal data partitioning |
| **Phase 09** | Day 12 | Baseline risk scoring model (Rule baseline & Regularized LR) | `src/risk_service/baseline_model.py` | NOT STARTED | Supervised model training |
| **Phase 10** | Day 13 | Probabilistic model calibration (Platt Scaling / Isotonic) | Model calibration scripts, ECE curves | NOT STARTED | Verifies calibration reliability; updates status |
| **Phase 11** | Day 14 | Explainability module for signed feature contributions ($w_i \cdot x_i$) | `src/risk_service/explainer.py` | NOT STARTED | Generates officer-facing SHAP-like contributions |
| **Phase 12** | Day 15 | Central Risk Relay FastAPI service | `src/risk_service/api.py` | NOT STARTED | Ingestion and advisory query endpoints |
| **Phase 13** | Day 16 | Vernacular notice generator (EN, BN, HI) + NCRP/STR JSON | `src/compliance/notice_engine.py` | NOT STARTED | Deterministic templates for customer protection |
| **Phase 14** | Day 17 | RBI statutory SLA tracker (20d notice + 10d bank + 30d LEA cap) | `src/compliance/sla_tracker.py` | NOT STARTED | RBI Draft KYC Directions 2026 Annex III |
| **Phase 15** | Day 18 | Append-only SHA-256 hash-chained audit ledger | `src/compliance/audit_ledger.py` | NOT STARTED | Tamper-evident ledger & verification script |
| **Phase 16** | Day 19 | Pillar 1 & 2 evaluation (Detection & Fairness / Proportionality) | `eval/evaluate_detection.py`, `eval/evaluate_fairness.py` | NOT STARTED | Precision, Recall, PR-AUC, festival false flags |
| **Phase 17** | Day 20 | Pillar 3 Privacy evaluation & Model Card publication | `eval/evaluate_privacy.py`, `docs/model_card.md` | NOT STARTED | Linkability metrics & governance documentation |
| **Phase 18** | Days 21–24 | Streamlit Nodal Officer War-Room Dashboard (Pages 1–4) | `ui/app.py`, page components | NOT STARTED | 4-page UI for privacy, review, SLA, & governance |
| **Phase 19** | Day 25 | CPU latency & throughput benchmarking ($p_{50}, p_{95}, p_{99}$) | `eval/benchmark_cpu.py` | NOT STARTED | Measures CPU-only performance on 50k edges |
| **Phase 19A** | Day 26 | Docker containerization & orchestration | `Dockerfile`, `docker-compose.yml` | NOT STARTED | Multi-container setup for reproducible deploy |
| **Phase 19B** | Day 27 | End-to-end integration tests & automated validation | `tests/test_e2e.py` | NOT STARTED | Full system workflow test from scam to SLA |
| **Phase 19C** | Day 28 | Comprehensive README, architecture docs & traceability | `README.md`, `docs/traceability_matrix.md` | NOT STARTED | Traceability against all PRD requirements |
| **Phase 19D** | Day 29 | 3-minute demonstration video script & storyboard | `docs/demo_video_script.md` | NOT STARTED | Demo narrative covering Konnagar & Puja surge |
| **Phase 19E** | Day 30 | Repository submission checklist & final artifact audit | `docs/submission_checklist.md`, release build | NOT STARTED | Final quality gate for SFIC 2026 submission |

---

## 3. PRD Phase 1 Checkpoint & Deliverables Audit

Governed by `docs/PRD.md` Section 9 (*Phase 1: Foundations, Days 1–10*).

| Mandatory PRD Phase 1 Deliverable | Target Requirement | Current Implementation Status | Verification Evidence / Deliverable Artifact |
| :--- | :--- | :--- | :--- |
| **Monorepo & Physical Storage Schemas** | 4 physically isolated SQLite databases with zero shared storage | **MET (100%)** | `data/banks/bank_{a..e}.db`, `data/kms/hsm_mock.db`, `data/central/risk_relay.db`, `data/audit/compliance_ledger.db`. Implemented in `src/init_dbs.py`. |
| **Multi-Bank Synthetic Generator** | 5 banks, realistic Indian names, normal distributions, AMLSim dynamics | **MET (100%)** | `src/simulator/generator.py` generates retail, kirana, student, and nodal accounts. Documented in `docs/generated/sim_summary.md`. |
| **Targeted Scenario Generators** | Konnagar ₹5L scam (5 hops, BANK_D exit), Durga Puja 10x surge, student pass-through | **MET (100%)** | `src/simulator/scenarios.py` with 8 composable scenarios. Documented in `docs/generated/scenarios.md` & verified in `docs/generated/scenario_verification.md`. |
| **Bank-Local Feature Extractor** | $Z_{\text{dormancy}}$, $M_{\text{local}}$, cold-start cohort fallback, fail-closed payload | **MET (100%)** | `src/bank_local/vault.py` (physical boundary) & `src/bank_local/local_features.py` (`LocalFeaturePayload` Pydantic model with `extra="forbid"`). |
| **Passing Tests for Zero PII Leakage** | Exhaustive scan asserting no raw account IDs, names, or balances in central/audit DBs | **MET (100%)** | `tests/test_token_service.py::test_zero_pii_leakage_in_central_and_audit_stores` PASSED across all tables and columns. |
| **Passing Tests for HMAC Key Rotation** | 24-hour dual-key sliding overlap window, expiry, and emergency revocation | **MET (100%)** | `tests/test_token_service.py::test_rotation_and_overlap_lifecycle` PASSED. Mock HSM audit logs recorded in `kms_access_logs`. |
| **Data Dictionary Finalized** | Complete documentation of all tables, columns, and privacy boundary sides | **MET (100%)** | Finalized in `docs/data_dictionary.md` covering all 4 databases, ground truth, and boundary payloads. |
| **Comparative Compute Lab (PSI vs HMAC)** | Empirical benchmarks on sizes 1k, 5k, 10k, 50k with trade-off analysis | **MET (100%)** | Implemented in `src/token_service/psi_benchmark.py`. Published in `docs/generated/psi_vs_hmac.md` and `docs/generated/psi_vs_hmac.json`. |

---

## 4. Execution Status Legend
* **NOT STARTED:** Pending previous phase completion.
* **IN PROGRESS:** Active engineering or verification turn.
* **BLOCKED:** Waiting for conflict resolution or external dependency.
* **COMPLETE:** Verified by Phase Close Protocol (automated tests passed, isolation checked, audit verified).
