"""Test suite for Phase 05: Bank-Local Vault & Local Features.

Verifies:
1. Hand-computed Z-score formula correctness.
2. Cold-start fallback to peer cohorts for accounts < 14 days.
3. M_local discrimination (Durga Puja merchant >> Fraud mule).
4. Boundary payload fail-closed whitelisting (rejects account_id, synthetic_name, balance_inr).
5. Algorithmic fairness: asserts zero protected demographic attributes.
6. BankVault physical isolation and path security checks.
"""

import os
import pytest
import yaml
from pydantic import ValidationError

from src.bank_local.local_features import (
    LocalFeaturePayload,
    calculate_local_metrics,
    compute_m_local,
    compute_z_dormancy,
    extract_local_features,
)
from src.bank_local.vault import BankVault


# --- Test 1: Hand-Computed Z-Score Example ---
def test_hand_computed_z_score():
    """Verify exact numerical precision for Z_dormancy per PRD eq 3."""
    v_24h = 10000.0
    mu_90d = 2000.0
    sigma_90d = 1000.0
    eps0 = 1.0

    # Hand calculation: (10000.0 - 2000.0) / (1000.0 + 1.0) = 8000.0 / 1001.0 = 7.992007992007992
    expected_z = 8000.0 / 1001.0
    actual_z = compute_z_dormancy(v_24h, mu_90d, sigma_90d, eps0=eps0)

    assert abs(actual_z - expected_z) < 1e-9
    assert round(actual_z, 4) == 7.9920


# --- Test 2: Cold-Start Fallback (<14 Days) ---
def test_cold_start_fallback():
    """Verify that accounts under 14 days old fall back to peer-cohort metrics and set cold_start=True."""
    with BankVault("BANK_A") as vault:
        # Find or inspect a cold start account
        conn = vault._get_connection()
        cur = conn.cursor()
        cur.execute("SELECT account_id FROM accounts WHERE account_age_days < 14 LIMIT 1;")
        row = cur.fetchone()

        if not row:
            pytest.skip("No cold-start account present in sample data")

        cold_acc_id = row[0]
        z_dorm, m_local, is_cold = calculate_local_metrics(
            vault=vault,
            account_id=cold_acc_id,
            as_of_ts="2026-11-22T00:00:00Z"
        )

        assert is_cold is True, f"Account {cold_acc_id} must have cold_start=True"
        assert isinstance(z_dorm, float)
        assert 0.0 <= m_local <= 1.0


# --- Test 3: M_local Distinction (Durga Puja Merchant vs Mule Account) ---
def test_m_local_merchant_vs_mule():
    """Verify that M_local is substantially higher for Kirana merchants than for rapid sweep mules."""
    # 1. Typical genuine Kirana merchant during festival:
    # High repeat customer ratio (0.85), zero sweep-out (0.0), established account (age > 1 year)
    m_local_merchant = compute_m_local(
        r_repeat=0.85,
        s_sweep=0.0,
        account_age_days=730,
        w_a=0.4,
        w_b=0.4,
        w_c=0.2
    )
    # 0.4 * 0.85 + 0.4 * 1.0 + 0.2 * 1.0 = 0.34 + 0.40 + 0.20 = 0.94
    assert m_local_merchant >= 0.90

    # 2. Typical rapid layering mule account:
    # Zero repeat customers (0.0), 100% balance swept out in <10 minutes (1.0), fresh account (30 days)
    m_local_mule = compute_m_local(
        r_repeat=0.0,
        s_sweep=1.0,
        account_age_days=30,
        w_a=0.4,
        w_b=0.4,
        w_c=0.2
    )
    # 0.4 * 0.0 + 0.4 * (1 - 1.0) + 0.2 * (30 / 365) = 0.0 + 0.0 + 0.0164 = ~0.016
    assert m_local_mule <= 0.10

    # Strict proportionality discrimination: merchant score >> mule score
    assert m_local_merchant > (m_local_mule + 0.70)


# --- Test 4: Whitelisted Boundary Payload (Fail-Closed Zero-PII Egress) ---
def test_whitelisted_payload_rejects_extra_fields():
    """Verify that LocalFeaturePayload rejects any unapproved field (fail closed)."""
    valid_token = "a" * 64

    # Valid payload must succeed
    payload = LocalFeaturePayload(
        token_hash=valid_token,
        z_dormancy=1.52,
        m_local=0.88,
        cold_start=False,
        source_bank_id="BANK_A"
    )
    assert payload.token_hash == valid_token

    # Attempting to leak account_id must raise ValidationError
    with pytest.raises(ValidationError):
        LocalFeaturePayload(
            token_hash=valid_token,
            z_dormancy=1.52,
            m_local=0.88,
            cold_start=False,
            source_bank_id="BANK_A",
            account_id="ACC_BANK_A_000042"  # Prohibited!
        )

    # Attempting to leak customer name must raise ValidationError
    with pytest.raises(ValidationError):
        LocalFeaturePayload(
            token_hash=valid_token,
            z_dormancy=1.52,
            m_local=0.88,
            cold_start=False,
            source_bank_id="BANK_A",
            synthetic_name="Synth_Rajesh_Banerjee"  # Prohibited!
        )

    # Attempting to leak balance must raise ValidationError
    with pytest.raises(ValidationError):
        LocalFeaturePayload(
            token_hash=valid_token,
            z_dormancy=1.52,
            m_local=0.88,
            cold_start=False,
            source_bank_id="BANK_A",
            balance_inr=85000.0  # Prohibited!
        )

    # Invalid token length must raise ValidationError
    with pytest.raises(ValidationError):
        LocalFeaturePayload(
            token_hash="short_token",
            z_dormancy=1.52,
            m_local=0.88,
            cold_start=False,
            source_bank_id="BANK_A"
        )


# --- Test 5: Algorithmic Fairness - Protected Demographic Attributes Blocklist ---
def test_fairness_protected_attributes_blocklist():
    """Assert that no protected demographic attribute is present anywhere in local features."""
    with open("configs/features_v1.yaml", "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    blocklist = set(cfg.get("protected_attributes_blocklist", []))
    assert blocklist == {"gender", "religion", "caste", "language", "location"}

    # Check Pydantic boundary payload fields
    payload_fields = set(LocalFeaturePayload.model_fields.keys())
    intersection = payload_fields.intersection(blocklist)
    assert len(intersection) == 0, f"FAIRNESS VIOLATION: Protected fields {intersection} in LocalFeaturePayload!"

    # Verify field names don't contain protected keywords as substrings
    for field_name in payload_fields:
        for blocked in blocklist:
            assert blocked not in field_name.lower(), f"Suspicious field {field_name} matches blocked attribute {blocked}"


# --- Test 6: BankVault Physical Isolation & Security Boundary ---
def test_bank_vault_physical_isolation():
    """Verify that BankVault strictly isolates databases and rejects illegal access."""
    # 1. Valid BankVault instance
    with BankVault("BANK_A") as vault:
        assert vault.bank_id == "BANK_A"
        assert vault.db_path.name == "bank_a.db"
        acc = vault.get_account("ACC_BANK_A_NPCI_INWARD")
        assert acc is not None

    # 2. Case normalization works
    with BankVault("bank_b") as vault:
        assert vault.bank_id == "BANK_B"
        assert vault.db_path.name == "bank_b.db"

    # 3. Invalid bank ID raises ValueError
    with pytest.raises(ValueError):
        BankVault("BANK_UNKNOWN")

    # 4. Path traversal attempts raise ValueError/PermissionError
    with pytest.raises((ValueError, PermissionError)):
        BankVault("../central/risk_relay")

    # 5. Reverse lookup & token mapping roundtrip
    with BankVault("BANK_A") as vault:
        test_token = "f" * 64
        test_acc = "ACC_BANK_A_000001"
        vault.store_token_mapping(test_token, test_acc, "EPOCH-2026-11-22")
        resolved_acc = vault.reverse_lookup(test_token)
        assert resolved_acc == test_acc
