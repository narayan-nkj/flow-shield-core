"""Bank-Local Feature Extractor & Privacy Boundary Payload Validator.

Implements:
1. Z_dormancy(u, t): Dormancy-to-spike z-score with peer-cohort cold-start fallback for accounts < 14 days.
2. M_local(u): Composite merchant protection score (R_repeat, 1 - S_sweep, T_age_tier).
3. LocalFeaturePayload: Strictly whitelisted Pydantic model enforcing zero-PII egress (extra="forbid").
"""

import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml
from pydantic import BaseModel, ConfigDict, Field

from src.bank_local.vault import BankVault


class LocalFeaturePayload(BaseModel):
    """Strictly whitelisted boundary payload permitted to leave bank premises.

    ZERO-PII FAIL-CLOSED POLICY:
    - extra="forbid" raises a validation error if any unapproved field
      (e.g., account_id, synthetic_name, balance_inr) is included.
    - Only privacy-preserving derived signals are permitted.
    """
    model_config = ConfigDict(extra="forbid", strict=True)

    token_hash: str = Field(..., description="64-character pseudonymous HMAC-SHA-256 token", min_length=64, max_length=64)
    z_dormancy: float = Field(..., description="Dormancy-to-spike z-score relative to 90d baseline or cohort")
    m_local: float = Field(..., ge=0.0, le=1.0, description="Local merchant protection composite score [0, 1]")
    cold_start: bool = Field(..., description="True if account is < 14 days old and fell back to peer cohort")
    source_bank_id: str = Field(..., description="Canonical ID of the originating bank (e.g. BANK_A)")


def compute_z_dormancy(
    v_24h: float,
    mu_90d: float,
    sigma_90d: float,
    eps0: float = 1.0
) -> float:
    """Compute Dormancy-to-Spike Z-Score per PRD Section 5.1 (eq 3).

    Z_dorm(u, t) = (V_24h(u, t) - mu_90d(u)) / (sigma_90d(u) + eps0)
    """
    if v_24h < 0.0 or mu_90d < 0.0 or sigma_90d < 0.0:
        raise ValueError("Transaction volume metrics must be non-negative")
    return float((v_24h - mu_90d) / (sigma_90d + eps0))


def compute_m_local(
    r_repeat: float,
    s_sweep: float,
    account_age_days: int,
    w_a: float = 0.4,
    w_b: float = 0.4,
    w_c: float = 0.2,
    has_inflow: bool = True
) -> float:
    """Compute Composite Merchant Protection Score M_local(u) per PRD Section 5.1 (eq 4).

    M_local(u) = w_a * R_repeat + w_b * (1 - S_sweep) + w_c * T_age_tier
    If has_inflow is False, no customer sales were received, so the retention bonus (1 - S_sweep) is 0.0.
    """
    r_repeat_clamped = max(0.0, min(1.0, r_repeat))
    s_sweep_clamped = max(0.0, min(1.0, s_sweep))
    t_age_tier = min(1.0, max(0.0, account_age_days / 365.0))
    non_sweep = (1.0 - s_sweep_clamped) if has_inflow else 0.0

    score = w_a * r_repeat_clamped + w_b * non_sweep + w_c * t_age_tier
    return float(max(0.0, min(1.0, score)))


def calculate_local_metrics(
    vault: BankVault,
    account_id: str,
    as_of_ts: str,
    config_path: str = "configs/features_v1.yaml"
) -> Tuple[float, float, bool]:
    """Calculate Z_dormancy, M_local, and cold_start flag directly from bank records."""
    account = vault.get_account(account_id)
    if not account:
        raise ValueError(f"Account '{account_id}' not found in bank {vault.bank_id}")

    # Load configuration
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    weights = cfg.get("merchant_protection_weights", {"w_a": 0.4, "w_b": 0.4, "w_c": 0.2})
    w_a = weights.get("w_a", 0.4)
    w_b = weights.get("w_b", 0.4)
    w_c = weights.get("w_c", 0.2)

    cold_start_threshold = cfg.get("statutory", {}).get("cold_start_days", 14)
    sweep_window_sec = cfg.get("temporal_windows", {}).get("burst_window_sec", 600)  # 10 minutes

    # Parse reference timestamp
    dt_end = datetime.datetime.fromisoformat(as_of_ts.replace("Z", "+00:00"))
    dt_24h_start = dt_end - datetime.timedelta(hours=24)
    dt_7d_start = dt_end - datetime.timedelta(days=7)

    # 1. 24-hour transaction volume V_24h (outflows + inflows)
    txns_24h = vault.list_transactions(
        account_id=account_id,
        window_start=dt_24h_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        window_end=dt_end.strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    v_24h = sum(t["amount_inr"] for t in txns_24h)

    # 2. Check Cold-Start (<14 days)
    age_days = account["account_age_days"]
    if age_days < cold_start_threshold:
        is_cold = True
        mu_ref, sigma_ref = vault.get_cohort_statistics(
            account_type=account["account_type"],
            merchant_size_tier=account.get("merchant_size_tier")
        )
    else:
        is_cold = False
        mu_ref = account["mu_90d"]
        sigma_ref = account["sigma_90d"]

    # Compute Z_dormancy
    z_dorm = compute_z_dormancy(v_24h=v_24h, mu_90d=mu_ref, sigma_90d=sigma_ref, eps0=1.0)

    # 3. Compute M_local components over 7-day observation window
    txns_7d = vault.list_transactions(
        account_id=account_id,
        window_start=dt_7d_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        window_end=dt_end.strftime("%Y-%m-%dT%H:%M:%SZ")
    )

    incoming_txns = [t for t in txns_7d if t["dst_account_id"] == account_id]
    outgoing_txns = [t for t in txns_7d if t["src_account_id"] == account_id]

    # A. Repeat Customer Ratio (R_repeat)
    # Require at least 2 incoming transactions to evaluate repeat customer behavior
    if len(incoming_txns) >= 2:
        payers: Dict[str, int] = {}
        for t in incoming_txns:
            p = t["src_account_id"]
            payers[p] = payers.get(p, 0) + 1

        repeat_tx_count = sum(cnt for cnt in payers.values() if cnt >= 2)
        r_repeat = repeat_tx_count / len(incoming_txns)
    else:
        # Conservative default: accounts with 0 or 1 inflow have no proven customer base
        r_repeat = 0.0

    # B. 10-Minute Sweep-Out Ratio (S_sweep)
    # S_sweep = swept_volume / total_inflow clamped strictly to [0, 1]
    # Each outflow transaction is counted at most once across overlapping 10-minute inflow windows
    total_inflow = sum(t["amount_inr"] for t in incoming_txns)
    if total_inflow > 0 and outgoing_txns:
        swept_tx_ids = set()
        for in_tx in incoming_txns:
            t_in = datetime.datetime.fromisoformat(in_tx["timestamp"].replace("Z", "+00:00"))
            t_window = t_in + datetime.timedelta(seconds=sweep_window_sec)

            for out_tx in outgoing_txns:
                t_out = datetime.datetime.fromisoformat(out_tx["timestamp"].replace("Z", "+00:00"))
                if t_in <= t_out <= t_window:
                    swept_tx_ids.add(out_tx["txn_id"])

        swept_volume = sum(
            out_tx["amount_inr"] for out_tx in outgoing_txns if out_tx["txn_id"] in swept_tx_ids
        )
        s_sweep = max(0.0, min(1.0, swept_volume / total_inflow))
    else:
        s_sweep = 0.0

    m_local = compute_m_local(
        r_repeat=r_repeat,
        s_sweep=s_sweep,
        account_age_days=age_days,
        w_a=w_a,
        w_b=w_b,
        w_c=w_c,
        has_inflow=(total_inflow > 0.0)
    )

    return z_dorm, m_local, is_cold


def extract_local_features(
    vault: BankVault,
    account_id: str,
    as_of_ts: str,
    token_hash: str,
    config_path: str = "configs/features_v1.yaml"
) -> LocalFeaturePayload:
    """Extract and validate the MINIMUM local feature payload permitted to leave bank premises.

    Zero PII Guarantee: Returns strictly (token_hash, z_dormancy, m_local, cold_start, source_bank_id).
    Customer names, account numbers, and balances are never exposed.
    """
    z_dorm, m_local, is_cold = calculate_local_metrics(
        vault=vault,
        account_id=account_id,
        as_of_ts=as_of_ts,
        config_path=config_path
    )

    # Validates against strict Pydantic model
    return LocalFeaturePayload(
        token_hash=token_hash,
        z_dormancy=round(z_dorm, 4),
        m_local=round(m_local, 4),
        cold_start=is_cold,
        source_bank_id=vault.bank_id
    )
