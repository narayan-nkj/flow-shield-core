# CHAKRA-DPI Scenario Catalogue & Evaluation Archetypes

**Governing Document:** `docs/PRD.md` Section 1.2 & `configs/simulation_v1.yaml`  
**Last Updated:** 2026-11-22T14:00:02.137985+00:00  
**Random Seed:** `777`  

This catalogue details all simulated behavioral scenarios injected into the CHAKRA-DPI multi-bank pipeline, distinguishing true fraud rings from critical hard negatives.

---

## 1. Scenario Archetype Matrix

| Scenario Identifier | Classification Type | Expected Label | Core Risk Signal Tested | Institutional Scope |
| :--- | :--- | :--- | :--- | :--- |
| `konnagar_scam` | **Fraud Ring (Primary)** | **Positive (`is_mule=1`)** | Multi-hop velocity ($V_p$), rapid hold times, exit leakage | Participating (`A, B, C`) $\to$ Unjoined (`BANK_D`) |
| `durga_puja_surge` | **Hard Negative (Fairness)** | **Negative (`is_mule=0`)** | $M_{\text{local}}$ merchant protection during 10x volume surges | Local Kirana merchants across all banks |
| `student_fee_passthrough` | **Hard Negative (Precision)** | **Negative (`is_mule=0`)** | $V_p$ resilience against rapid ($<180\text{s}$) tuition payments | Students $\to$ University Nodal Accounts |
| `smurfing_fan_out` | **Fraud Ring (Layering)** | **Positive (`is_mule=1`)** | High out-degree entropy ($H_{\text{entropy}}$) & burst fan-out | Single origin $\to$ 15 mules across `A, B, C` |
| `concentrator_fan_in` | **Fraud Ring (Collection)** | **Positive (`is_mule=1`)** | In-degree concentration, multi-source pooling | 12 feeder mules $\to$ Single master mule |
| `dormant_awakening` | **Fraud Ring (Mule)** | **Positive (`is_mule=1`)** | Dormancy spike ($Z_{\text{dormancy}} > 5.0$) & immediate disbursement | Long-dormant accounts ($>180$d) suddenly active |
| `unjoined_leakage` | **Fraud Ring (Leakage)** | **Positive (`is_mule=1`)** | Cross-bank velocity chain escaping to unjoined bank | `BANK_A \to BANK_B \to BANK_C \to BANK_E` |
| `warm_up` | **Background Baseline** | **Negative (`is_mule=0`)** | Prior-window stabilization for $\mu_{90d}, \sigma_{90d}$ | Normal background retail & merchant transfers |

---

## 2. In-Depth Scenario Profiles

### Scenario 1: Konnagar ₹5,00,000 Scam Ring (`konnagar_scam`)
- **Description:** Simulates an inter-state cyber fraud incident originating in Konnagar (Hooghly district, West Bengal). A victim is defrauded of ₹5,00,000, which is immediately split and moved through a 5-hop relay chain across participating banks (`BANK_A`, `BANK_B`, `BANK_C`) before leaking out at non-participating `BANK_D`.
- **Key Features:** Mean hold time $< 90$ seconds per hop; high pass-through velocity ($V_p \to 1.0$).
- **Case Demonstration:** Target mule at Hop 2 reproduces Case `SYN-0042` with surgical lien demonstration (₹85,000 unrestricted balance, ₹2,500 disputed lien).

### Scenario 2: Durga Puja Merchant Volume Surge (`durga_puja_surge`) — Hard Negative
- **Description:** Simulates the massive retail shopping peak during Durga Puja in West Bengal. Local Kirana stores experience a 10x surge in transaction volume over 48 hours.
- **Why this is a Hard Negative:** Blanket fraud rules trigger massive false-positive liens during festival surges due to abnormal volume spikes. CHAKRA-DPI protects these merchants via high $M_{\text{local}}$ scores derived from high repeat-customer ratios ($R_{\text{repeat}} > 0.80$) and non-sweep balance retention.

### Scenario 3: Student Fee Pass-Through (`student_fee_passthrough`) — Hard Negative
- **Description:** A student receives ₹25,000–₹75,000 for university tuition fees from a parent and transfers it within 3 minutes ($\le 180$ seconds) to the university fee collection nodal account.
- **Why this is a Hard Negative:** The velocity formula $V_p$ penalizes rapid funds pass-through ($\exp(-\lambda \cdot \tau_{\text{hold}})$). However, because the recipient is an authentic educational nodal account (`nodal_whitelisted`), the system correctly suppresses alerts, avoiding innocent student account freezes.

### Scenario 4: Smurfing / Fan-Out (`smurfing_fan_out`)
- **Description:** A primary illicit node receives ₹3,500,000 and executes a rapid fan-out to 15 distinct mule accounts in sub-threshold amounts (₹18,000–₹24,000) within 10 minutes.
- **Detection Mechanism:** Identified by extreme recipient distribution entropy ($H_{\text{entropy}}$) and burst temporal velocity.

### Scenario 5: Concentrator / Fan-In Ring (`concentrator_fan_in`)
- **Description:** 12 dispersed smurfed nodes simultaneously funnel funds into a single master collection mule at `BANK_C` within a 15-minute window.
- **Detection Mechanism:** In-degree fan-in concentration and rapid balance accumulation without prior commercial history.

### Scenario 6: Dormant Account Awakening (`dormant_awakening`)
- **Description:** Accounts older than 180 days with negligible activity ($\mu_{90d} < 1500$) suddenly receive ₹4,50,000 via RTGS and rapidly disburse funds across multiple downstream hops.
- **Detection Mechanism:** Extreme dormancy-to-spike z-score ($Z_{\text{dormancy}} = \frac{V_{24h} - \mu_{90d}}{\sigma_{90d}} > 5.0$).

### Scenario 7: Unjoined Bank Leakage (`unjoined_leakage`)
- **Description:** A 4-hop cross-bank laundering chain moves through participating banks `BANK_A \to BANK_B \to BANK_C`, terminating at unjoined `BANK_E`.
- **Detection Mechanism:** Demonstrates provenance coverage ratio degradation ($3/5$ banks participating) and highlights cross-institutional visibility boundaries.

---
*Report auto-generated by `src/simulator/scenarios.py` under SFIC 2026 Phase 03.*