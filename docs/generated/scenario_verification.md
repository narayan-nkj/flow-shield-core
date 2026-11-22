# CHAKRA-DPI Scenario & Log Verification Report (Guide Day 4)

**Verification Timestamp:** 2026-11-22T14:09:21.644346+00:00
**Configuration File:** `configs/simulation_v1.yaml`
**Random Seed:** `42`

---

## 1. Scenario Parameter Confirmation Matrix

| Verification Metric | Expected Specification | Actual Injected Value | Audit Status |
| :--- | :--- | :--- | :--- |
| **Konnagar Scam Hop Count** | `5` | 5 | **✔ PASS** |
| **Konnagar Exit Bank Leakage** | `BANK_D` | BANK_D | **✔ PASS** |
| **Konnagar Disputed Amount** | `INR 500,000.00` | INR 500,000.00 | **✔ PASS** |
| **Case SYN-0042 Target Reproduction** | `Present with surgical lien values` | Found on ACC_BANK_C_002001 (Unrestricted: INR 85,000.00, Disputed: INR 2,500.00) | **✔ PASS** |
| **Student Fee Pass-Through Max Hold Time** | `<= 180.0s` | Max: 165.0s, Mean: 95.8s | **✔ PASS** |

---

## 2. Injected Scenario Volumes & Breakdown

* **Total Unique Ground-Truth Transactions:** 115,599
* **Total Bank DB Rows (including inward views):** 201,243
* **Central Risk Relay Ingested Edges:** 19,819
* **Total Labeled Accounts:** 516

| Scenario Group | Transaction Count | Volume (INR) | Primary Risk Archetype |
| :--- | :--- | :--- | :--- |
| `durga_puja_merchant_surge` | 81,590 | INR 50,823,437.77 | Simulation Activity |
| `normal_merchant_payment` | 12,982 | INR 5,935,855.90 | Simulation Activity |
| `normal_retail_p2p` | 10,199 | INR 19,184,624.47 | Simulation Activity |
| `warm_up_merchant_payment` | 3,826 | INR 1,119,191.03 | Simulation Activity |
| `warm_up_p2p` | 2,528 | INR 2,349,803.93 | Simulation Activity |
| `normal_salary_inflow` | 1,667 | INR 58,937,837.55 | Simulation Activity |
| `normal_bill_payment` | 1,416 | INR 3,111,289.97 | Simulation Activity |
| `normal_student_transfer` | 1,083 | INR 257,690.39 | Simulation Activity |
| `normal_student_allowance` | 199 | INR 850,259.15 | Simulation Activity |
| `student_fee_parent_inflow` | 25 | INR 1,256,655.31 | Simulation Activity |
| `student_fee_university_outflow` | 25 | INR 1,256,655.31 | Simulation Activity |
| `smurfing_fan_out_hop` | 15 | INR 332,577.98 | Simulation Activity |
| `dormant_awakening_dispersal` | 15 | INR 2,250,000.00 | Simulation Activity |
| `concentrator_fan_in_feeder` | 12 | INR 290,914.47 | Simulation Activity |
| `dormant_awakening_inflow` | 5 | INR 2,250,000.00 | Simulation Activity |
| `smurfing_fan_out_funding_inflow` | 1 | INR 350,000.00 | Simulation Activity |
| `innocent_kirana_victim_payment` | 1 | INR 2,500.00 | Simulation Activity |
| `konnagar_scam_hop_1` | 1 | INR 500,000.00 | Simulation Activity |
| `konnagar_scam_hop_2` | 1 | INR 500,000.00 | Simulation Activity |
| `konnagar_scam_hop_3` | 1 | INR 500,000.00 | Simulation Activity |
| `konnagar_scam_hop_4` | 1 | INR 500,000.00 | Simulation Activity |
| `konnagar_scam_exit_BANK_D` | 1 | INR 500,000.00 | Simulation Activity |
| `concentrator_onward_sweep_outflow` | 1 | INR 280,295.68 | Simulation Activity |
| `unjoined_leakage_hop_1` | 1 | INR 250,000.00 | Simulation Activity |
| `unjoined_leakage_hop_2` | 1 | INR 250,000.00 | Simulation Activity |
| `unjoined_leakage_hop_3` | 1 | INR 250,000.00 | Simulation Activity |
| `unjoined_leakage_exit_BANK_E` | 1 | INR 250,000.00 | Simulation Activity |

---

## 3. Physical Bank Isolation & Transaction Volumes

| Bank Identifier | Status | In-DB Transaction Entries | Total Recorded Volume (INR) |
| :--- | :--- | :--- | :--- |
| `BANK_A` | Participating | 41,018 | INR 62,059,350.01 |
| `BANK_B` | Participating | 39,925 | INR 56,287,425.58 |
| `BANK_C` | Participating | 41,006 | INR 51,610,643.91 |
| `BANK_D` | Unjoined / External | 39,170 | INR 53,603,170.19 |
| `BANK_E` | Unjoined / External | 40,124 | INR 51,017,630.43 |

---

## 4. Hold-Time Empirical Distribution Analysis

Hold time $\tau_{\text{hold}}$ is the primary input to Pass-Through Velocity $V_p(u, \Delta T) \propto \exp(-\lambda \cdot \tau_{\text{hold}})$.

| Entity Category | Sample Count | Min Hold | Mean Hold | Median (p50) | p90 | Max Hold | Compliance |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Mules (Konnagar)** | 4 | 51.0s | 57.2s | 57.0s | 63.1s | 64.0s | Rapid Velocity |
| **Students (Tuition)** | 25 | 42.0s | 95.8s | 101.0s | 141.0s | 165.0s | Safe Tuition Flow (<= 180s) |
| **Kirana Merchants** | 514 | > 48.0h | > 48.0h | > 48.0h | > 48.0h | > 48.0h | High Retention ($S_{\text{sweep}} = 0.0\%$) |

---
*Verification completed and validated under SFIC 2026 Phase 04.*