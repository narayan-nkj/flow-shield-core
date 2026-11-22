# CHAKRA-DPI Privacy Engineering & Residual Linkability Notes

**Project Name:** CHAKRA-DPI (Cross-Bank Fraud Velocity & Citizen Protection Infrastructure)  
**Track:** Seva First Innovation Challenge (SFIC) 2026 – Eastern Region  
**Application ID:** `SFIC-WB-3789`  
**Governing Principles:** NFR Privacy Transparency & PRD Section 3 (Layer 2)  
**Last Updated:** 2026-11-22  

---

## 1. Executive Privacy Transparency Declaration

CHAKRA-DPI enforces strict physical and cryptographic boundaries to prevent customer Personally Identifiable Information (PII) from leaving bank firewalls. However, in full alignment with academic and regulatory honesty:

> [!IMPORTANT]
> **Pseudonymity is NOT Full Anonymity:**  
> The identifiers used in the Central Risk Relay (`data/central/risk_relay.db`) are **epoch-scoped pseudonyms** generated via $\text{HMAC-SHA-256}(\text{account\_id}, K_{\text{epoch}})$, not unconditionally anonymous identities. While raw names, account numbers, and balances never leave bank premises, **residual linkability exists** through side-channel metadata.

---

## 2. Vector Analysis of Residual Linkability

### 2.1 Graph Topology & Neighborhood Linkability
Within an active key epoch, the mapping from account identifier to HMAC token is deterministic:
$$\forall u, \quad \text{HMAC}(u, K_{\text{epoch}}) \to \text{token}_u$$
Consequently, all edges involving node $u$ share the exact same pseudonymous vertex $\text{token}_u$. An adversary with access to the central risk multigraph $G_t = (V, E_t)$ can observe:
* **Degree Centrality:** In-degree and out-degree fan-out distributions.
* **Neighborhood Fingerprinting:** Persistent sub-graph motifs (e.g., a merchant regularly transacting with the same cluster of 20 loyal customer nodes).
* **Cross-Bank Route Continuity:** End-to-end paths across participating institutions.

### 2.2 Temporal & Amount Side-Channel Correlation
Even though amounts are transformed into $\log(1 + \text{Amount})$ and account numbers are replaced with hashes, metadata correlation remains possible:
1. **Timestamp Correlation ($\Delta t$):** High-velocity transactions occurring within seconds of an external observable event (e.g., an ATM cash-out or point-of-sale terminal swipe) can be correlated by an adversary observing both live payment rails and the central relay.
2. **Amount Granularity ($\log(1 + \text{Amount})$):** The function $f(x) = \log(1 + x)$ is strictly monotonic and invertible:
   $$x = \exp(f(x)) - 1$$
   While the log transformation prevents raw balances from sitting in plain text, unique or uncommon transaction values (e.g., ₹4,99,999.00) remain distinct fingerprints in the central store.

### 2.3 Threat Model: Key Leakage & Dictionary / Rainbow Table Attacks
If a 256-bit epoch secret $K_{\text{epoch}}$ is compromised (e.g. through HSM intrusion or insider threat):
* The adversary can mount an **offline dictionary attack**. Because the universe of valid bank account numbers or phone numbers/VPAs is finite and structured, an attacker can pre-compute $\text{HMAC}(v, K_{\text{epoch}})$ for all candidate accounts and immediately invert all pseudonyms in the database.
* **Defense Implemented:** 
  - Epoch rotation limits key exposure to a strict 24-hour window.
  - Emergency key revocation (`is_revoked = 1`) immediately invalidates compromised epochs.
  - Rate limiting prevents brute-force token matching across the central boundary.

---

## 3. Cryptographic & Architectural Defenses

| Privacy Defense Layer | Implementation in CHAKRA-DPI | Efficacy & Trade-Off |
| :--- | :--- | :--- |
| **Physical Isolation** | 4 separate SQLite databases on disk; BankVault enforces path boundaries by design. | Eliminates accidental cross-database SQL joins; enforces zero-PII egress at the filesystem level. |
| **24-Hour Sliding Key Rotation** | Rotating 256-bit HMAC keys with a dual-key overlap window. | Breaks permanent cross-temporal linkability; tokens generated in Week 1 cannot be linked to Week 2 without bridge metadata. |
| **Fail-Closed Boundary Models** | `LocalFeaturePayload` Pydantic model with `extra="forbid"`. | Automatically rejects any extra field (e.g., `account_id`, `synthetic_name`, `balance_inr`) at runtime. |
| **Strict Rate-Limiting** | Per-bank query quotas enforced by Mock HSM. | Prevents automated scraping and brute-force identity matching across institutional boundaries. |
| **No Bulk Export API** | Central Risk Service exposes edge ingestion and single-token advisory queries only. | Prohibits bulk pseudonym mapping extraction. |

---

## 4. Benchmark Comparison: HMAC vs. Private Set Intersection (PSI)

In Phase 07, CHAKRA-DPI introduces a comparative compute lab benchmarking pseudonymous HMACs against cryptographic **Private Set Intersection (PSI)**:

* **HMAC Approach (Current Baseline):**  
  * *Pros:* Microsecond latency ($< 0.05$ ms per edge), zero specialized hardware requirements, highly efficient on CPU.
  * *Trade-Off:* Relies on trust in the multi-party KMS / HSM layer; residual metadata linkability exists.
* **Cryptographic PSI Approach:**  
  * *Pros:* Cryptographically zero metadata leakage; institutions learn strictly the intersection of flagged accounts.
  * *Trade-Off:* Exponentially higher computational complexity and network bandwidth overhead (orders of magnitude slower than CPU-first requirements).

---

*This document is maintained as part of the official SFIC 2026 transparency artifacts.*
