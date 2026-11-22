# CHAKRA-DPI: Architecture Decision Records (ADR) & Conflict Log

**Project Name:** CHAKRA-DPI (Cross-Bank Fraud Velocity & Citizen Protection Infrastructure)  
**Track:** Seva First Innovation Challenge (SFIC) 2026 – Eastern Region (Junior / Undergraduate)  
**Application ID:** `SFIC-WB-3789`  
**Governing Standard:** Document Precedence Rule (`CLAUDE.md`)  
**Last Updated:** 2026-11-22  

---

## 1. Document Precedence Framework

* **Single Source of Truth:** `docs/PRD.md` is the single source of truth for schemas, formulas, guardrails, architecture, and requirements.
* **Sequencing & Schedule:** Project sequencing and roadmap tracking are governed by `docs/PROGRESS.md`.
* **Mandatory Reporting:** All architectural decisions and changes are documented here with rationales and surfaced to the user. No conflict or divergence is ever silently resolved by an agent.

---

## 2. Active Decision Records & Known Conflicts Scan

### ADR-001: Currency Unit Representation ("$1,000" vs "INR 1,000")
* **Status:** PROPOSED DEFAULT (Pending User Confirmation)
* **Context & Conflict:**
  * `docs/PRD.md` Section 2.1 (FR-3) mentions: `Filter transactions under the statutory threshold (>= $1,000 / INR 1,000)`.
  * `docs/EXECUTION_GUIDE.md` Section 1.2 (`configs/features_v1.yaml`) defines `rbi_threshold_inr: 1000`.
  * The dollar sign `$` in the PRD is a typographical artifact carried over from generic AML descriptions, whereas the project operates within the Indian financial regulatory perimeter (RBI, NPCI, I4C).
* **Precedence Rule Applied:** PRD requirements + regulatory domain context.
* **Proposed Default:**
  * Standardize strictly on **`INR` (Indian Rupee, ₹)** across all schemas, configs, database columns (`amount_inr`, `balance_inr`), and UI displays.
  * Disallow `$` anywhere in financial logic or data models.

---

### ADR-002: RBI Statutory SLA Timeline Definition ("20+10+30" vs "Day 20 / Day 30 / Day 60")
* **Status:** PROPOSED DEFAULT (Pending User Confirmation)
* **Context & Conflict:**
  * `docs/PRD.md` Section 1.2 & Section 3 Layer 4 cite: `RBI Annex III SLA Clock (20d + 10d + 30d)`.
  * `docs/PRD.md` Section 2.1 (FR-5) & Section 4.4 cite cumulative checkpoints:
    $$\text{Day 0 (Lien Log)} \rightarrow \text{Day 20 (Customer Notice Window)} \rightarrow \text{Day 30 (Bank Review Cap)} \rightarrow \text{Day 60 (LEA Ceiling)}$$
  * `docs/EXECUTION_GUIDE.md` Section 1.3 defines schema columns: `t0_advisory_ts`, `d20_explanation_due`, `d30_bank_decision_due`, `d60_lea_hard_cap`.
* **Precedence Rule Applied:** PRD formulas and schema alignment.
* **Proposed Default:**
  * Clarify that **"20+10+30" represents the additive stage durations that accumulate to the 60-day hard statutory cap**:
    1. **Stage 1 (Days 0 to 20 — 20 days duration):** Customer notice window to submit explanation or dispute evidence.
    2. **Stage 2 (Days 20 to 30 — 10 days duration):** Bank Nodal Officer evaluation and review decision cap.
    3. **Stage 3 (Days 30 to 60 — 30 days duration):** Final law enforcement / competent authority determination or automatic release.
  * Schema columns will strictly store cumulative ISO-8601 timestamps:
    - $T_0$: Advisory / Lien timestamp
    - $D_{20} = T_0 + 20\text{ days}$
    - $D_{30} = T_0 + 30\text{ days}$ ($D_{20} + 10\text{ days}$)
    - $D_{60} = T_0 + 60\text{ days}$ ($D_{30} + 30\text{ days}$)

---

### ADR-003: Risk Band Calibration Status Lifecycle
* **Status:** PROPOSED DEFAULT (Pending User Confirmation)
* **Context & Conflict:**
  * `docs/EXECUTION_GUIDE.md` Section 1.2 (`configs/features_v1.yaml`) provides default config: `status: "CALIBRATED_UNVERIFIED_ADVISORY_ONLY"`.
  * `docs/PRD.md` Section 8 (UI Spec) states that the Nodal Officer Desk initially displays `"uncalibrated placeholder score bands"` before formal calibration is executed.
* **Precedence Rule Applied:** PRD requirement for algorithmic integrity + Execution Guide default config.
* **Proposed Default:**
  * Implement an explicit lifecycle status transition:
    1. During Phases 01–07 (pre-calibration / baseline training), store and display status as:  
       `"UNCALIBRATED_ADVISORY_ONLY"` (or `"UNCALIBRATED"`).
    2. Once Phase 10 (Model Calibration & ECE Verification) executes and satisfies the calibration threshold ($\text{ECE} \le 0.10$), dynamically transition the status to:  
       `"CALIBRATED_UNVERIFIED_ADVISORY_ONLY"`.
  * This prevents the dashboard from claiming calibrated probabilities before calibration curves are actually fitted and validated.

---

### ADR-004: Bank Identifier Format Canonicalization ("BANK_A" vs "bank_a")
* **Status:** PROPOSED DEFAULT (Pending User Confirmation)
* **Context & Conflict:**
  * `docs/EXECUTION_GUIDE.md` Section 1.2 (`configs/simulation_v1.yaml`) defines bank lists in uppercase: `BANK_A, BANK_B, BANK_C, BANK_D, BANK_E`.
  * `docs/EXECUTION_GUIDE.md` Section 1.3 (`src/init_dbs.py`) iterates over lowercase names: `["bank_a", "bank_b", ...]` and creates `data/banks/{bank_id.lower()}.db`.
  * `docs/PRD.md` Section 4.1 specifies `data/banks/bank_a.db` with `bank_id TEXT NOT NULL`.
* **Precedence Rule Applied:** PRD schema consistency + filesystem safety.
* **Proposed Default:**
  * Canonicalize all **in-memory data, token request payloads, logs, and database row values** to uppercase: `"BANK_A"`, `"BANK_B"`, `"BANK_C"`, `"BANK_D"`, `"BANK_E"`.
  * Enforce lowercase **strictly for SQLite filenames on disk**: `data/banks/bank_a.db`.
  * Implement a standard path resolver helper in `src/bank_local/vault.py`:
    ```python
    def get_bank_db_path(bank_id: str) -> str:
        canonical_id = bank_id.strip().upper()
        return f"data/banks/{canonical_id.lower()}.db"
    ```

---

### ADR-005: Account Population Scale (5,000 vs 50,000 Accounts)
* **Status:** PROPOSED DEFAULT (Pending User Confirmation)
* **Context & Conflict:**
  * `docs/EXECUTION_GUIDE.md` Section 1.2 sets `total_accounts: 5000` in `simulation_v1.yaml`.
  * `docs/PRD.md` Section 2.1 (FR-1) & Section 6 (Pillar 4) specify synthetic ledgers for `up to 50,000 accounts` and `50,000 synthetic edges` for CPU stress benchmarking.
* **Precedence Rule Applied:** Execution Guide sequencing/defaults for dev + PRD requirement for benchmarking.
* **Proposed Default:**
  * Use **5,000 accounts** as the default baseline in `configs/simulation_v1.yaml` for rapid local iteration, unit/integration testing (Phases 01–18), and interactive Streamlit UI runs.
  * Provide an explicit benchmark configuration profile (`configs/benchmark_50k.yaml` or CLI flag `--benchmark`) that scales the population to **50,000 accounts / edges** during Phase 19 (`eval/benchmark_cpu.py`).

---

### ADR-006: Audit Ledger Hash Chaining Cryptographic Formula
* **Status:** PROPOSED DEFAULT (Pending User Confirmation)
* **Context & Conflict:**
  * `docs/EXECUTION_GUIDE.md` Section 3 Guardrail 4 specifies:  
    $$\text{Audit logs compute cryptographic hash chains using } \text{SHA256}(\text{prev\_hash} \parallel \text{payload\_json})$$
  * `docs/PRD.md` Section 2.1 (FR-6) & Section 4.4 define the table schema with `prev_hash` and `row_hash` columns.
* **Precedence Rule Applied:** Execution Guide starter formula + PRD schema integrity.
* **Proposed Default:**
  * Adopt the exact formula specified in the Execution Guide:
    $$\text{row\_hash} = \text{SHA256}(\text{prev\_hash} + \text{payload\_json})$$
  * **Canonical serialization rules for `payload_json`:**
    1. All dictionary keys must be sorted alphabetically: `json.dumps(payload, sort_keys=True, separators=(',', ':'))`.
    2. Encoding must strictly be `UTF-8`.
    3. The genesis block `prev_hash` is initialized to 64 zeros:  
       `"0000000000000000000000000000000000000000000000000000000000000000"`.

---

### ADR-007: Repository Hygiene, Secret Untracking, Single Source of Truth & Python 3.12 Standard (CR02-A)
* **Status:** ACCEPTED (Implemented per CR02-A)
* **Context & Conflict:**
  * Git repository hygiene required removing private defense PDFs, local agent instructions (`CLAUDE.md`, `AGENTS.md`, `.cursorrules`), and synthetic ground-truth labels from Git index and tracking while keeping them locally.
  * `docs/EXECUTION_GUIDE.md` was removed to establish `docs/PRD.md` as the single authoritative source of truth, with project sequencing tracked via `docs/PROGRESS.md`.
  * Python runtime was standardized on Python 3.12 (with support for 3.11+).
* **Decisions Adopted:**
  1. **Git Untracking:** Untracked `CLAUDE.md`, 3 defense PDFs (`CHAKRA-DPI_panel_checklist.pdf`, `CHAKRA-DPI-Material.pdf`, `CHAKRA-DPI.pdf`), and `data/ground_truth/*.csv`. Added to `.gitignore`.
  2. **Ground Truth Regenerability:** Verified ground-truth labels are deterministically regenerable on demand from seed (`src/simulator/scenarios.py`).
  3. **Single Source of Truth:** `docs/PRD.md` is the single source of truth for all schemas, formulas, guardrails, and requirements. Sequencing is tracked in `docs/PROGRESS.md`.
  4. **Link Hygiene:** Added `scripts/check_links.py` to prevent broken relative links in markdown documentation.
  5. **Runtime Standard:** Virtual environment recreated with Python 3.12.16; `.python-version` set to `3.12`; `pyproject.toml` specifies `requires-python = ">=3.11, <3.13"`.

---

### ADR-008: P0 Data & Mathematical Bug Fixes (CR02-B)
* **Status:** ACCEPTED (Implemented per CR02-B)
* **Context & Issues Resolved:**
  1. **Inward Clearing & Balance Conservation (`src/simulator/generator.py`):**
     * *Bug:* Outgoing transactions previously did not enforce sender liquidity or maintain running balances, risking negative balances. Additionally, base scenario transactions ending in `_IN` collided with inward clearing gateway identifiers.
     * *Root Cause:* `generate_transactions()` did not track running balances or clamp amounts by available balance; `scenarios.py` used `_IN` suffix for deposit transactions (`TXN_STU_FEE_..._IN`, `TXN_DORM_SPIKE_..._IN`).
     * *Fix:* Added `_execute_transfer()` helper enforcing `sender.balance_inr >= amount`, deducting debit from sender and adding credit to receiver, strictly conserving total funds. Renamed scenario deposit transactions to `_DEP` and cleaned legacy records in bank DBs.
     * *Test Name:* `tests/test_cr02b_regressions.py::test_cross_bank_conservation_and_non_negative_balances`, `tests/test_cr02b_regressions.py::test_whole_dataset_conservation_and_inward_records`.
  2. **Edge Deduplication, Receiver Token Map & Holding Time (`src/token_service/hsm_mock.py`):**
     * *Bug 2a (Edge Deduplication):* Re-running `process_edges()` produced duplicate edges due to random UUIDs and uncoordinated processing of inward clearing mirrors.
     * *Root Cause:* Random `uuid.uuid4()` generated new IDs per execution; inward clearing gateway records were treated as independent transactions instead of accounting mirrors.
     * *Fix 2a:* Edge ID derived deterministically via `EDGE-SHA256(canonical_txn_id)[:16]`. Outgoing transactions from participating banks are prioritized; mirror inward records for participating senders are deduplicated, rendering the pipeline completely idempotent.
     * *Bug 2b (Receiver Token Map):* Destination tokens (`dst_token`) were not written to receiving bank `local_token_map`, preventing receiving banks from resolving counterparty accounts locally.
     * *Root Cause:* `process_edges()` only inserted `src_tok` into `source_bank_id`'s `local_token_map`.
     * *Fix 2b:* Extracted destination bank identifier from `dst_account_id` and inserted `dst_tok -> dst_account_id` into that receiving bank's `local_token_map`. Preserved strict zero-cross-bank-leakage (only the owning bank can resolve its own account).
     * *Bug 2c (`last_in_ts` Holding Time):* Holding time $\Delta t$ was measured from any prior event rather than the most recent inbound credit.
     * *Root Cause:* `last_event_ts` recorded outbound events as baseline timestamps for subsequent outflows.
     * *Fix 2c:* Maintained `last_in_ts` tracking strictly incoming credits. When an account disperses funds, $\Delta t = \max(0, event\_unix - last\_in\_ts[src])$. For accounts with no prior inflow in observation window, defaulted to `DEFAULT_NO_INFLOW_HOLD_TIME_SEC = 86400.0` (24h, representing mature balance holding).
     * *Test Names:* `tests/test_cr02b_regressions.py::test_edge_deduplication_idempotent`, `tests/test_cr02b_regressions.py::test_receiver_local_token_map_reverse_lookup`, `tests/test_cr02b_regressions.py::test_last_in_ts_holding_time_hand_computed`.
  3. **$S_{\text{sweep}}$ Double-Counting & Dormant Account $M_{\text{local}}$ Default (`src/bank_local/local_features.py`):**
     * *Bug 3a ($S_{\text{sweep}}$ Double-Counting):* An outflow within overlapping 10-minute windows of multiple inflows was added multiple times to `swept_volume`, inflating $S_{\text{sweep}}$.
     * *Root Cause:* Nested iteration over inflows and outflows summed amount without tracking unique outflow transaction IDs.
     * *Fix 3a:* Maintained `swept_tx_ids = set()` ensuring each outflow is counted at most once toward swept volume; clamped $S_{\text{sweep}} \in [0.0, 1.0]$.
     * *Bug 3b (Dormant Account $R_{\text{repeat}}$ & $M_{\text{local}}$):* Mature dormant accounts with zero transactions received $R_{\text{repeat}} = 0.5$ and $(1 - S_{\text{sweep}}) = 1.0$, resulting in an inflated $M_{\text{local}} = 0.80$, suppressing mule alerts.
     * *Root Cause:* Defaulting $R_{\text{repeat}} = 0.5$ when no inflows existed, and granting full merchant retention bonus $(1 - S_{\text{sweep}}) = 1.0$ when total inflow was zero.
     * *Fix 3b:* Defaulted $R_{\text{repeat}} = 0.0$ when incoming transaction count $< 2$. When `total_inflow == 0`, set merchant retention credit to $0.0$, capping dormant account $M_{\text{local}} \le 0.20$ ($w_c \cdot T_{\text{age}}$ only).
     * *Test Names:* `tests/test_cr02b_regressions.py::test_s_sweep_no_double_counting_and_clamped`, `tests/test_cr02b_regressions.py::test_dormant_account_low_m_local`.

---

## 3. ADR Template for Future Additions

```markdown
### ADR-XXX: [Title]
* **Status:** [PROPOSED | ACCEPTED | REJECTED]
* **Context & Conflict:** [Detailed description of the divergence or architectural question]
* **Precedence Rule Applied:** [PRD (Requirements/Schema) vs Execution Guide (Sequencing/Config)]
* **Proposed Default / Resolution:** [Exact implementation decision]
* **Impact Analysis:** [Affected components, files, schemas, or tests]
```
