# CHAKRA-DPI Data Dictionary & Privacy Boundary Matrix

**Project Name:** CHAKRA-DPI (Cross-Bank Fraud Velocity & Citizen Protection Infrastructure)  
**Application ID:** `SFIC-WB-3789`  
**Governing Standard:** `docs/PRD.md` Section 4 & `CLAUDE.md` Section 3  
**Last Updated:** 2026-11-22  

---

## 1. Privacy Boundary Architecture Overview

The system strictly enforces physical data segregation across **4 isolated SQLite database files**.

```text
========================================================================================
[BANK-LOCAL FIREWALL: INSIDE PREMISES] (data/banks/bank_{a..e}.db)
- Holds Raw PII: Account numbers, synthetic names, local balances, transaction histories.
- Holds Private Reverse-Map: local_token_map (Account ID <-> Token).
------------------------------ STRICT PRIVACY BOUNDARY ---------------------------------
[MOCK HSM / KMS LAYER] (data/kms/hsm_mock.db)
- Holds 24h Epoch Secrets (mock_secret_hex) and KMS access logs. Zero transaction data.
----------------------------------------------------------------------------------------
[CENTRAL RISK RELAY] (data/central/risk_relay.db)
- Zero PII: Only 64-char HMAC tokens, log(1+Amt), delta_t, and model advisory scores.
----------------------------------------------------------------------------------------
[COMPLIANCE & AUDIT LEDGER] (data/audit/compliance_ledger.db)
- Zero PII: Append-only hash-chained human decisions, notices, SLA clocks, and disputes.
========================================================================================
```

---

## 2. Bank-Local Vaults (`data/banks/bank_{a..e}.db`)

### Table: `accounts`
Stores customer master records. **STRICTLY CONFIDENTIAL — Stays inside local bank premises.**

Each bank also instantiates one internal nodal clearing account (`ACC_{BANK_ID}_NPCI_INWARD`, e.g., `ACC_BANK_A_NPCI_INWARD`) to record inward cross-bank transfers without storing sender identity from other banks.

| Column Name | Data Type | Constraints | Privacy Boundary Side | Description |
| :--- | :--- | :--- | :--- | :--- |
| `account_id` | `TEXT` | `PRIMARY KEY` | **INSIDE Bank Firewall (PII)** | Bank-internal unique account number (e.g. `ACC_BANK_A_000001` or `ACC_BANK_A_NPCI_INWARD`). |
| `bank_id` | `TEXT` | `NOT NULL` | **INSIDE Bank Firewall** | Canonical bank identifier (`BANK_A` to `BANK_E`). |
| `synthetic_name` | `TEXT` | `NOT NULL` | **INSIDE Bank Firewall (PII)** | Simulated customer full name. |
| `account_type` | `TEXT` | `CHECK(IN ('retail', 'kirana_merchant', 'student', 'nodal_whitelisted'))` | **INSIDE Bank Firewall** | Behavioral category for activity baselining. |
| `merchant_size_tier` | `TEXT` | `NULLABLE` | **INSIDE Bank Firewall** | Merchant tier: `micro`, `small`, `medium`. |
| `account_age_days` | `INTEGER` | `NOT NULL` | **INSIDE Bank Firewall** | Account tenure in days; used for cold-start (<14d) routing. |
| `balance_inr` | `REAL` | `NOT NULL` | **INSIDE Bank Firewall (PII)** | Current unencumbered account balance in INR. |
| `mu_90d` | `REAL` | `DEFAULT 0.0` | **INSIDE Bank Firewall** | 90-day historical mean daily volume. |
| `sigma_90d` | `REAL` | `DEFAULT 1.0` | **INSIDE Bank Firewall** | 90-day volume standard deviation. |
| `m_local_score` | `REAL` | `DEFAULT 0.5` | **INSIDE Bank Firewall** | Composite merchant protection metric $M_{\text{local}} \in [0, 1]$. |

### Table: `raw_transactions`
Stores core banking raw transaction entries.

**Cross-Bank Inward Settlement:** For cross-bank transactions, the sender bank logs the customer's account as `src_account_id` and the external account as `dst_account_id`. The receiving bank logs the inward transfer with `src_account_id = ACC_{RECEIVER}_NPCI_INWARD` and `scenario_label = {scenario}_incoming`. This guarantees that the receiver bank cannot access or infer the sender bank's customer PII.

| Column Name | Data Type | Constraints | Privacy Boundary Side | Description |
| :--- | :--- | :--- | :--- | :--- |
| `txn_id` | `TEXT` | `PRIMARY KEY` | **INSIDE Bank Firewall** | Unique transaction reference string. |
| `src_account_id` | `TEXT` | `NOT NULL, FK(accounts)` | **INSIDE Bank Firewall (PII)** | Debited internal account identifier. |
| `dst_account_id` | `TEXT` | `NOT NULL` | **INSIDE Bank Firewall (PII)** | Credited counterparty account identifier. |
| `amount_inr` | `REAL` | `NOT NULL` | **INSIDE Bank Firewall (PII)** | Unmasked transaction value in INR. |
| `channel` | `TEXT` | `CHECK(IN ('UPI', 'IMPS', 'RTGS'))` | **INSIDE Bank Firewall** | Inter-bank payment rail used. |
| `timestamp` | `TEXT` | `NOT NULL` (Indexed) | **INSIDE Bank Firewall** | ISO-8601 transaction initiation timestamp. |
| `scenario_label` | `TEXT` | `NULLABLE` | **INSIDE Bank Firewall** | Ground-truth simulation tag (e.g. `konnagar_scam_hop_2`). |

### Table: `local_token_map`
Local reverse-lookup table enabling the bank to map central advisories back to customer accounts.

| Column Name | Data Type | Constraints | Privacy Boundary Side | Description |
| :--- | :--- | :--- | :--- | :--- |
| `token_hash` | `TEXT` | `PRIMARY KEY` | **INSIDE Bank Firewall** | 64-character hex HMAC-SHA-256 token. |
| `account_id` | `TEXT` | `NOT NULL, FK(accounts)` | **INSIDE Bank Firewall (PII)** | Internal account ID corresponding to the token. |
| `epoch_id` | `TEXT` | `NOT NULL` | **INSIDE Bank Firewall** | Key epoch ID during which token was generated. |
| `created_at` | `TEXT` | `NOT NULL` | **INSIDE Bank Firewall** | Mapping generation timestamp. |

---

## 3. Mock KMS / HSM Store (`data/kms/hsm_mock.db`)

**CRYPTOGRAPHIC ISOLATION GUARANTEE:** This store manages 256-bit rotating HMAC keys. Raw account numbers are normalized via `normalize_account_identifier` prior to hashing. No account identifiers, transaction logs, or customer balances are ever stored in KMS tables.

### Table: `epoch_keys`
Stores rotating cryptographic secrets managed by the simulated multi-party KMS.

| Column Name | Data Type | Constraints | Privacy Boundary Side | Description |
| :--- | :--- | :--- | :--- | :--- |
| `epoch_id` | `TEXT` | `PRIMARY KEY` | **Mock KMS / HSM Store** | Unique epoch identifier (e.g. `EPOCH-2026-11-22`). |
| `mock_secret_hex` | `TEXT` | `NOT NULL` | **Mock KMS / HSM Store** | 256-bit mock secret key (64 hex characters). |
| `valid_from` | `TEXT` | `NOT NULL` | **Mock KMS / HSM Store** | Epoch start timestamp (ISO-8601 UTC). |
| `valid_to` | `TEXT` | `NOT NULL` | **Mock KMS / HSM Store** | Epoch scheduled end timestamp (24h lifespan). |
| `overlap_until` | `TEXT` | `NOT NULL` | **Mock KMS / HSM Store** | Grace period expiration for dual-key transition window. |
| `is_revoked` | `INTEGER` | `DEFAULT 0` | **Mock KMS / HSM Store** | Emergency revocation flag ($0 = \text{active}, 1 = \text{revoked}$). |

### Table: `kms_access_logs`
Audit log recording every key issuance and tokenization request.

| Column Name | Data Type | Constraints | Privacy Boundary Side | Description |
| :--- | :--- | :--- | :--- | :--- |
| `log_id` | `INTEGER` | `PRIMARY KEY AUTOINCREMENT` | **Mock KMS / HSM Store** | Unique access log entry identifier. |
| `requesting_bank_id` | `TEXT` | `NOT NULL` | **Mock KMS / HSM Store** | Requesting bank (`BANK_A` ... `BANK_E`). |
| `epoch_id` | `TEXT` | `NOT NULL, FK(epoch_keys)` | **Mock KMS / HSM Store** | Target epoch identifier. |
| `operation` | `TEXT` | `NOT NULL` | **Mock KMS / HSM Store** | Operation performed (`TOKENIZE`, `ROTATE`, `REVOKE`). |
| `timestamp` | `TEXT` | `NOT NULL` | **Mock KMS / HSM Store** | Log entry timestamp (ISO-8601 UTC). |

---

## 4. Central Risk Relay (`data/central/risk_relay.db`)

**ZERO RAW PII GUARANTEE:** This database contains zero customer names, account numbers, Aadhaar numbers, or raw balances.

### Table: `pseudonymous_edges`
Cross-bank transaction edges ingested for temporal graph traversal.

| Column Name | Data Type | Constraints | Privacy Boundary Side | Description |
| :--- | :--- | :--- | :--- | :--- |
| `edge_id` | `TEXT` | `PRIMARY KEY` | **OUTSIDE Bank (Zero PII Relay)** | Unique ingested edge UUID. |
| `src_token` | `TEXT` | `NOT NULL` (Indexed) | **OUTSIDE Bank (Zero PII Relay)** | 64-char HMAC-SHA-256 origin pseudonym. |
| `dst_token` | `TEXT` | `NOT NULL` (Indexed) | **OUTSIDE Bank (Zero PII Relay)** | 64-char HMAC-SHA-256 destination pseudonym. |
| `log_amount` | `REAL` | `NOT NULL` | **OUTSIDE Bank (Zero PII Relay)** | Transformed value: $\log(1 + \text{Amount})$. |
| `delta_t_sec` | `REAL` | `NOT NULL` | **OUTSIDE Bank (Zero PII Relay)** | Inter-transaction delta time in seconds. |
| `channel_id` | `TEXT` | `NOT NULL` | **OUTSIDE Bank (Zero PII Relay)** | Channel identifier (`UPI`, `IMPS`, `RTGS`). |
| `source_bank_id` | `TEXT` | `NOT NULL` | **OUTSIDE Bank (Zero PII Relay)** | Originating institutional ID (`BANK_A` ... `BANK_E`). |
| `epoch_id` | `TEXT` | `NOT NULL` | **OUTSIDE Bank (Zero PII Relay)** | Tokenization epoch ID. |
| `event_ts` | `TEXT` | `NOT NULL` (Indexed) | **OUTSIDE Bank (Zero PII Relay)** | Transaction initiation timestamp. |
| `ingested_ts` | `TEXT` | `NOT NULL` | **OUTSIDE Bank (Zero PII Relay)** | Timestamp when edge arrived at central relay. |

### Table: `advisory_cases`
Advisory outputs produced by the temporal graph scoring engine.

| Column Name | Data Type | Constraints | Privacy Boundary Side | Description |
| :--- | :--- | :--- | :--- | :--- |
| `case_id` | `TEXT` | `PRIMARY KEY` | **OUTSIDE Bank (Zero PII Relay)** | Case reference ID (e.g. `CASE-SYN-0042`). |
| `target_token` | `TEXT` | `NOT NULL` (Indexed) | **OUTSIDE Bank (Zero PII Relay)** | Flagged account's pseudonymous HMAC token. |
| `score_p` | `REAL` | `NOT NULL` | **OUTSIDE Bank (Zero PII Relay)** | Calibrated probability score $p \in [0, 1]$. |
| `score_band` | `TEXT` | `CHECK(IN ('PRIORITY', 'ADDITIONAL_REVIEW', 'NO_ELEVATED_ALERT'))` | **OUTSIDE Bank (Zero PII Relay)** | Advisory priority band. |
| `feature_values_json` | `TEXT` | `NOT NULL` | **OUTSIDE Bank (Zero PII Relay)** | JSON map of feature values ($V_p, H_{\text{entropy}}, Z_{\text{dorm}}, M_{\text{local}}$). |
| `feature_contributions_json`| `TEXT` | `NOT NULL` | **OUTSIDE Bank (Zero PII Relay)** | Signed linear attributions ($w_i \cdot x_i$). |
| `linked_tokens_json` | `TEXT` | `NOT NULL` | **OUTSIDE Bank (Zero PII Relay)** | JSON list of upstream/downstream subgraph tokens. |
| `participating_banks_count` | `INTEGER` | `NOT NULL` | **OUTSIDE Bank (Zero PII Relay)** | Count of participating banks in path (provenance). |
| `total_banks_count` | `INTEGER` | `NOT NULL` | **OUTSIDE Bank (Zero PII Relay)** | Total ecosystem banks (e.g. 5). |
| `stale_feed_flag` | `INTEGER` | `DEFAULT 0` | **OUTSIDE Bank (Zero PII Relay)** | Warning flag ($1$ if any upstream bank feed $>300\text{s}$ stale). |
| `model_version` | `TEXT` | `NOT NULL` | **OUTSIDE Bank (Zero PII Relay)** | Model artifact version identifier. |
| `feature_version` | `TEXT` | `NOT NULL` | **OUTSIDE Bank (Zero PII Relay)** | Feature schema version identifier. |
| `run_id` | `TEXT` | `NOT NULL` | **OUTSIDE Bank (Zero PII Relay)** | Evaluation / simulation run ID. |
| `created_at` | `TEXT` | `NOT NULL` (Indexed) | **OUTSIDE Bank (Zero PII Relay)** | Case generation timestamp. |

---

## 5. Compliance & Audit Ledger (`data/audit/compliance_ledger.db`)

**IMMUTABILITY GUARANTEE:** All tables in this database are append-only. SQLite triggers reject any `UPDATE` or `DELETE` attempt with an `ABORT` exception.

### Table: `reviewer_decisions`
Records Nodal Officer determinations on advisory cases.

| Column Name | Data Type | Constraints | Privacy Boundary Side | Description |
| :--- | :--- | :--- | :--- | :--- |
| `decision_id` | `TEXT` | `PRIMARY KEY` | **OUTSIDE Bank (Audit Ledger)** | Unique decision identifier UUID. |
| `case_id` | `TEXT` | `NOT NULL` (Indexed) | **OUTSIDE Bank (Audit Ledger)** | Reference to `advisory_cases.case_id`. |
| `reviewer_id` | `TEXT` | `NOT NULL` | **OUTSIDE Bank (Audit Ledger)** | Officer badge/system ID (e.g. `OFFICER_WB_042`). |
| `decision_type` | `TEXT` | `CHECK(IN ('REFER_BANK_LEA', 'NO_ACTION', 'REQUEST_CUSTOMER_EXPLANATION'))` | **OUTSIDE Bank (Audit Ledger)** | Formal human determination rendered. |
| `officer_reasoning` | `TEXT` | `NOT NULL` | **OUTSIDE Bank (Audit Ledger)** | Plain-language statutory justification text. |
| `decided_at` | `TEXT` | `NOT NULL` | **OUTSIDE Bank (Audit Ledger)** | Timestamp of decision execution. |
| `prev_hash` | `TEXT` | `NOT NULL` | **OUTSIDE Bank (Audit Ledger)** | SHA-256 hash of the immediately preceding ledger row. |
| `row_hash` | `TEXT` | `NOT NULL` | **OUTSIDE Bank (Audit Ledger)** | Cryptographic row signature: $\text{SHA256}(\text{prev\_hash} \parallel \text{payload\_json})$. |

### Table: `customer_notices`
Stores multi-lingual notices generated for innocent customer explanation windows.

| Column Name | Data Type | Constraints | Privacy Boundary Side | Description |
| :--- | :--- | :--- | :--- | :--- |
| `notice_id` | `TEXT` | `PRIMARY KEY` | **OUTSIDE Bank (Audit Ledger)** | Unique advisory notice UUID. |
| `case_id` | `TEXT` | `NOT NULL` (Indexed) | **OUTSIDE Bank (Audit Ledger)** | Target advisory case ID. |
| `language` | `TEXT` | `CHECK(IN ('EN', 'BN', 'HI'))` | **OUTSIDE Bank (Audit Ledger)** | Advisory language: English, Bengali, Hindi. |
| `template_version` | `TEXT` | `NOT NULL` | **OUTSIDE Bank (Audit Ledger)** | Deterministic notice template version. |
| `reason_codes_json` | `TEXT` | `NOT NULL` | **OUTSIDE Bank (Audit Ledger)** | Standard plain-language reason codes. |
| `notice_body` | `TEXT` | `NOT NULL` | **OUTSIDE Bank (Audit Ledger)** | Rendered notice text containing surgical lien details. |
| `generated_at` | `TEXT` | `NOT NULL` | **OUTSIDE Bank (Audit Ledger)** | Notice generation timestamp. |

### Table: `sla_clock_events`
Tracks statutory 60-day deadlines mandated under RBI Draft KYC Directions 2026 (Annex III).

| Column Name | Data Type | Constraints | Privacy Boundary Side | Description |
| :--- | :--- | :--- | :--- | :--- |
| `clock_id` | `TEXT` | `PRIMARY KEY` | **OUTSIDE Bank (Audit Ledger)** | Unique SLA clock tracking UUID. |
| `case_id` | `TEXT` | `NOT NULL` (Indexed) | **OUTSIDE Bank (Audit Ledger)** | Target advisory case ID. |
| `t0_advisory_ts` | `TEXT` | `NOT NULL` | **OUTSIDE Bank (Audit Ledger)** | $T_0$: Advisory timestamp when lien logged. |
| `d20_explanation_due` | `TEXT` | `NOT NULL` | **OUTSIDE Bank (Audit Ledger)** | $T_0 + 20\text{ days}$: Customer notice & explanation window deadline. |
| `d30_bank_decision_due` | `TEXT` | `NOT NULL` | **OUTSIDE Bank (Audit Ledger)** | $T_0 + 30\text{ days}$: Bank internal determination cap ($D_{20} + 10\text{ days}$). |
| `d60_lea_hard_cap` | `TEXT` | `NOT NULL` | **OUTSIDE Bank (Audit Ledger)** | $T_0 + 60\text{ days}$: Statutory ceiling ($D_{30} + 30\text{ days}$). |
| `current_status` | `TEXT` | `NOT NULL` | **OUTSIDE Bank (Audit Ledger)** | `ACTIVE`, `CUSTOMER_EXPLAINED`, `RESOLVED`, `EXPIRED`. |
| `extension_note` | `TEXT` | `NULLABLE` | **OUTSIDE Bank (Audit Ledger)** | Documented extension rationale if applicable. |

### Table: `grievance_disagreement_log`
Audit log recording formal customer disagreements and officer responses.

| Column Name | Data Type | Constraints | Privacy Boundary Side | Description |
| :--- | :--- | :--- | :--- | :--- |
| `entry_id` | `TEXT` | `PRIMARY KEY` | **OUTSIDE Bank (Audit Ledger)** | Disagreement entry UUID. |
| `case_id` | `TEXT` | `NOT NULL` (Indexed) | **OUTSIDE Bank (Audit Ledger)** | Target advisory case ID. |
| `actor` | `TEXT` | `CHECK(IN ('CUSTOMER', 'OFFICER'))` | **OUTSIDE Bank (Audit Ledger)** | Submitting party (`CUSTOMER` or `OFFICER`). |
| `statement_text` | `TEXT` | `NOT NULL` | **OUTSIDE Bank (Audit Ledger)** | Verbatim dispute or rebuttal text. |
| `escalation_ref` | `TEXT` | `NULLABLE` | **OUTSIDE Bank (Audit Ledger)** | External Banking Ombudsman / LEA case reference. |
| `logged_at` | `TEXT` | `NOT NULL` | **OUTSIDE Bank (Audit Ledger)** | Dispute log timestamp. |
| `prev_hash` | `TEXT` | `NOT NULL` | **OUTSIDE Bank (Audit Ledger)** | SHA-256 hash of preceding grievance row. |
| `row_hash` | `TEXT` | `NOT NULL` | **OUTSIDE Bank (Audit Ledger)** | Cryptographic signature: $\text{SHA256}(\text{prev\_hash} \parallel \text{payload\_json})$. |

---

## 6. Ground-Truth Dataset (`data/ground_truth/`)

**EVALUATION-ONLY BOUNDARY:** These datasets exist strictly on local researcher/evaluator storage for benchmarking detection accuracy, fairness, and false alert rates. They are **never ingested into or accessible by** Central Risk Relay (`risk_relay.db`) or Compliance Ledger (`compliance_ledger.db`).

### File: `data/ground_truth/labels.csv`
Account-level ground-truth annotations across normal users, fraud rings, and hard negatives.

| Column Name | Data Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `account_id` | `TEXT` | `PRIMARY KEY` | Target account identifier. |
| `bank_id` | `TEXT` | `NOT NULL` | Bank holding the account (`BANK_A` ... `BANK_E`). |
| `account_type` | `TEXT` | `NOT NULL` | `retail`, `kirana_merchant`, `student`, `nodal_whitelisted`. |
| `is_mule` | `INTEGER` | `0 or 1` | Ground-truth binary flag: `1` for fraudulent mule; `0` for benign / hard negative. |
| `scenario_label` | `TEXT` | `NOT NULL` | Archetype label (e.g., `konnagar_scam_mule_hop_2`, `konnagar_scam_innocent_kirana`, `durga_puja_surge_merchant`, `student_fee_passthrough`). |
| `disputed_lien_inr`| `REAL` | `NOT NULL` | Disputed amount attributable to this account (e.g. ₹2,500 for innocent kirana proportionality demo; ₹500,000 for scam mules). |
| `unrestricted_balance_inr` | `REAL` | `NOT NULL` | Genuine funds eligible for unrestricted operations (e.g. ₹85,000 for innocent kirana proportionality demo). |
| `case_id` | `TEXT` | `NULLABLE` | Case identifier for UI reproduction (e.g. `SYN-0042`). |
| `notes` | `TEXT` | `NULLABLE` | Analytical rationale documenting why an entity is a fraud mule or hard negative. |

### File: `data/ground_truth/txn_labels.csv`
Transaction-level ground-truth annotations for precision-recall evaluation.

| Column Name | Data Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `txn_id` | `TEXT` | `PRIMARY KEY` | Unique transaction reference string. |
| `src_account_id` | `TEXT` | `NOT NULL` | Sending account identifier. |
| `dst_account_id` | `TEXT` | `NOT NULL` | Receiving account identifier. |
| `amount_inr` | `REAL` | `NOT NULL` | Transaction amount in INR. |
| `channel` | `TEXT` | `NOT NULL` | Payment rail: `UPI`, `IMPS`, `RTGS`. |
| `timestamp` | `TEXT` | `NOT NULL` | ISO-8601 transaction initiation timestamp. |
| `scenario_label` | `TEXT` | `NOT NULL` | Injected scenario identifier. |
| `is_fraud` | `INTEGER` | `0 or 1` | `1` if transaction is part of an illicit ring; `0` if normal/benign. |
| `sending_bank` | `TEXT` | `NOT NULL` | Sending bank identifier. |
| `receiving_bank` | `TEXT` | `NOT NULL` | Receiving bank identifier. |

---

## 7. Bank Boundary Egress Payload (`LocalFeaturePayload`)

**PRIVACY WHITELIST & FAIL-CLOSED ENFORCEMENT:** The bank-local feature extractor outputs strictly the fields in this payload to the Central Risk Relay. Pydantic schema validation is configured with `extra="forbid"`, which raises an exception if any unauthorized field (e.g. `account_id`, `synthetic_name`, `balance_inr`) is passed.

| Field Name | Type | Validation / Constraints | Privacy Guarantee |
| :--- | :--- | :--- | :--- |
| `token_hash` | `str` | Exactly 64 hex characters | Epoch-scoped pseudonymous HMAC-SHA-256 token. |
| `z_dormancy` | `float` | Dimensionless | $(V_{24\text{h}} - \mu_{90\text{d}}) / (\sigma_{90\text{d}} + 1.0)$. |
| `m_local` | `float` | Clamped to $[0.0, 1.0]$ | Composite merchant protection score: $w_a R_{\text{repeat}} + w_b (1 - S_{\text{sweep}}) + w_c T_{\text{age\_tier}}$. |
| `cold_start` | `bool` | `True` or `False` | Flag indicating fallback to commercial peer-cohort metrics (<14 days). |
| `source_bank_id` | `str` | `BANK_A` ... `BANK_E` | Canonical institutional identifier for graph edge routing. |


