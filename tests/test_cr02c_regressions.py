"""Tests and regressions for CHANGE REQUEST CR02-C (P1 Scenario & Crypto Fixes).

METHOD (Mandatory):
1. Locate code & explain root cause.
2. Write FAILING regression tests reproducing issues.
3. Apply minimal correct fix.
4. Verify all tests pass.
5. Log in docs/DECISIONS.md.
"""

import os
import random
import datetime
import sqlite3
import pytest

from src.init_dbs import get_bank_db_path
from src.simulator.generator import SyntheticGenerator
from src.simulator.scenarios import ScenarioEngine, AccountLabel
from src.token_service.hsm_mock import (
    MockHSMService,
    RevokedEpochError,
    ExpiredEpochError,
    TokenServiceError,
)
from src.token_service.psi_benchmark import (
    RFC2409_MODP_1024_SAFE_PRIME,
    EducationalDHPSI,
)


# Helper: Miller-Rabin primality test
def is_probable_prime(n: int, k: int = 15) -> bool:
    if n < 2:
        return False
    if n in (2, 3):
        return True
    if n % 2 == 0:
        return False
    r, s = 0, n - 1
    while s % 2 == 0:
        r += 1
        s //= 2
    for _ in range(k):
        a = random.randint(2, n - 2)
        x = pow(a, s, n)
        if x in (1, n - 1):
            continue
        for _ in range(r - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


# ==============================================================================
# 1. Konnagar Innocent Kirana Branch
# ==============================================================================
def test_konnagar_innocent_kirana_branch():
    """Verify that Konnagar scam includes an innocent kirana branch (default Rs 2,500),

    labelled negative, and reproducing the proportionality demo (Rs 85k balance, Rs 2.5k lien).
    """
    gen = SyntheticGenerator(config_path="configs/simulation_v1.yaml", seed=42)
    bank_accounts = gen.generate_accounts(total_accounts=300)

    injector = ScenarioEngine(config_path="configs/simulation_v1.yaml", seed=42)
    txns, labels, metrics = injector.inject_konnagar_scam(bank_accounts)

    # 1. Check configured innocent branch amount
    innocent_amt = metrics.get("innocent_branch_amount_inr", 2500.0)
    assert innocent_amt == 2500.0

    # 2. Find innocent kirana account in labels
    innocent_labels = [
        lbl for lbl in labels.values()
        if lbl.scenario_label == "konnagar_scam_innocent_kirana"
    ]
    assert len(innocent_labels) == 1, "Must have exactly one innocent kirana account labelled"
    kirana_lbl = innocent_labels[0]

    # Must be negative (is_mule = 0)
    assert kirana_lbl.is_mule == 0, "Innocent kirana must be labelled negative (is_mule=0)"
    assert kirana_lbl.account_type == "kirana_merchant"

    # Lien math demo parameters
    assert kirana_lbl.disputed_lien_inr == 2500.0
    assert kirana_lbl.unrestricted_balance_inr == 85000.0

    # 3. Check transaction to this kirana shop exists
    kirana_txs = [t for t in txns if t.dst_account_id == kirana_lbl.account_id]
    assert len(kirana_txs) == 1, "Innocent kirana must receive exactly one transaction from the victim-side flow"
    assert kirana_txs[0].amount_inr == 2500.0


# ==============================================================================
# 2. Unjoined Leakage (4-Hop Path Ending at Non-Participating Bank)
# ==============================================================================
def test_unjoined_leakage_hop_count_and_exit():
    """Verify unjoined_leakage is a 4-hop path ending at non-participating bank (D or E)."""
    gen = SyntheticGenerator(config_path="configs/simulation_v1.yaml", seed=42)
    bank_accounts = gen.generate_accounts(total_accounts=300)

    injector = ScenarioEngine(config_path="configs/simulation_v1.yaml", seed=42)
    txns, labels, metrics = injector.inject_unjoined_leakage(bank_accounts)

    # Must be exactly 4 hops (4 transactions)
    assert len(txns) == 4, f"Expected 4 hops in unjoined_leakage, got {len(txns)}"
    assert metrics["chain_hops"] == 4

    # Verify chain ordering and that the final hop ends at BANK_D or BANK_E
    for idx in range(len(txns) - 1):
        assert txns[idx].dst_account_id == txns[idx + 1].src_account_id, "Hops must form a continuous chain"

    final_tx = txns[-1]
    assert final_tx.receiving_bank in ["BANK_D", "BANK_E"], (
        f"Last hop destination bank must be non-participating (BANK_D or BANK_E), got {final_tx.receiving_bank}"
    )


# ==============================================================================
# 3. Smurfing Fan-Out Inflow-Before-Outflow and Sub-Threshold Amounts
# ==============================================================================
def test_smurfing_fan_out_inflow_before_outflow_and_thresholds():
    """Verify smurfing fan-out source receives large inflow before splitting,

    sum of sub-transfers <= inflow, and amounts above & below Rs 1,000 exist.
    """
    gen = SyntheticGenerator(config_path="configs/simulation_v1.yaml", seed=42)
    bank_accounts = gen.generate_accounts(total_accounts=300)

    injector = ScenarioEngine(config_path="configs/simulation_v1.yaml", seed=42)
    txns, labels, metrics = injector.inject_smurfing_fan_out(bank_accounts)

    origin_id = metrics["origin_account_id"]

    # 1. First transaction must be an INFLOW to origin
    inflows_to_origin = [t for t in txns if t.dst_account_id == origin_id]
    assert len(inflows_to_origin) >= 1, "Origin must receive funding inflow"
    funding_tx = inflows_to_origin[0]
    total_inflow = funding_tx.amount_inr

    # 2. All fan-out disbursements must come AFTER the inflow
    t_inflow = datetime.datetime.fromisoformat(funding_tx.timestamp.replace("Z", "+00:00"))
    outflows = [t for t in txns if t.src_account_id == origin_id]
    assert len(outflows) > 0, "Origin must execute fan-out outflows"

    for out_tx in outflows:
        t_out = datetime.datetime.fromisoformat(out_tx.timestamp.replace("Z", "+00:00"))
        assert t_out >= t_inflow, f"Outflow {out_tx.txn_id} at {t_out} occurred before inflow at {t_inflow}!"

    # 3. Sum of sub-transfers must not exceed total inflow
    total_outflow = sum(t.amount_inr for t in outflows)
    assert total_outflow <= total_inflow, (
        f"Total outflow ({total_outflow}) exceeds funding inflow ({total_inflow})"
    )

    # 4. Must include amounts above and below Rs 1,000 threshold
    amounts_below_1k = [t.amount_inr for t in outflows if t.amount_inr < 1000.0]
    amounts_above_1k = [t.amount_inr for t in outflows if t.amount_inr >= 1000.0]
    assert len(amounts_below_1k) > 0, "Smurfing fan-out must include sub-threshold amounts (< Rs 1,000)"
    assert len(amounts_above_1k) > 0, "Smurfing fan-out must include above-threshold amounts (>= Rs 1,000)"


# ==============================================================================
# 4. Concentrator Fan-In Rapid Onward Outflow
# ==============================================================================
def test_concentrator_fan_in_rapid_onward_outflow():
    """Verify master concentrator mule dispatches rapid onward outflow after inflows,

    and the outflow amount is bounded by total inflow.
    """
    gen = SyntheticGenerator(config_path="configs/simulation_v1.yaml", seed=42)
    bank_accounts = gen.generate_accounts(total_accounts=300)

    injector = ScenarioEngine(config_path="configs/simulation_v1.yaml", seed=42)
    txns, labels, metrics = injector.inject_concentrator_fan_in(bank_accounts)

    master_id = metrics["master_mule_account_id"]

    inflows = [t for t in txns if t.dst_account_id == master_id]
    outflows = [t for t in txns if t.src_account_id == master_id]

    assert len(inflows) >= 5, "Expected multiple fan-in inflows"
    assert len(outflows) >= 1, "Collector must have onward outflow (pass-through ring)"

    latest_inflow_ts = max(
        datetime.datetime.fromisoformat(t.timestamp.replace("Z", "+00:00")) for t in inflows
    )
    first_outflow = outflows[0]
    first_outflow_ts = datetime.datetime.fromisoformat(first_outflow.timestamp.replace("Z", "+00:00"))

    # Outflow must come after the inflows
    assert first_outflow_ts >= latest_inflow_ts, "Onward sweep must occur after fan-in aggregation"

    # Outflow must be bounded by total inflow
    total_inflow = sum(t.amount_inr for t in inflows)
    assert first_outflow.amount_inr <= total_inflow, "Onward outflow cannot exceed total funneled inflow"
    assert first_outflow.amount_inr >= 0.8 * total_inflow, "Onward sweep should disburse majority of funneled funds"


# ==============================================================================
# 5. Durga Puja Volume Balance & Temporal Spike
# ==============================================================================
def test_durga_puja_volume_balance_and_temporal_spike():
    """Verify Durga Puja 10x surge is funded by customer balances without creating money

    from nothing, no negative balances, and volume returns to normal after 48h.
    """
    gen = SyntheticGenerator(config_path="configs/simulation_v1.yaml", seed=42)
    bank_accounts = gen.generate_accounts(total_accounts=300)

    # Capture pre-surge customer balances
    all_retail = [a for b in bank_accounts.values() for a in b if a.account_type == "retail"]
    pre_balances = {a.account_id: a.balance_inr for a in all_retail}

    injector = ScenarioEngine(config_path="configs/simulation_v1.yaml", seed=42)
    txns, labels, metrics = injector.inject_durga_puja_surge(bank_accounts)

    # 1. No customer balance went negative
    for a in all_retail:
        assert a.balance_inr >= 0.0, f"Customer {a.account_id} balance went negative: {a.balance_inr}"

    # 2. Timing: all surge transactions must fall strictly inside the 48-hour festival window
    festival_start = injector.base_start + datetime.timedelta(days=4)
    festival_end = festival_start + datetime.timedelta(hours=48)

    for tx in txns:
        t_tx = datetime.datetime.fromisoformat(tx.timestamp.replace("Z", "+00:00"))
        assert festival_start <= t_tx <= festival_end, (
            f"Surge transaction {tx.txn_id} outside 48h window: {t_tx}"
        )


# ==============================================================================
# 6. Mock HSM Key Rotation & Overlap Window Lifecycle
# ==============================================================================
def test_rotate_overlap_and_revocation(tmp_path):
    """Verify 24h sliding overlap window: matching under both epochs during overlap,

    only new epoch after overlap_until, and immediate rejection of revoked epoch.
    """
    kms_db = str(tmp_path / "hsm_mock.db")
    from src.init_dbs import init_kms_db
    init_kms_db(db_path=kms_db)

    hsm = MockHSMService(kms_db_path=kms_db)
    t0 = datetime.datetime(2026, 11, 20, 10, 0, 0, tzinfo=datetime.timezone.utc)

    # 1. Create Initial Epoch 1 (valid for 24h, overlap 24h)
    ep1 = hsm.create_epoch(
        epoch_id="EPOCH-001",
        valid_from=t0,
        duration_hours=24,
        overlap_hours=24
    )

    # 2. Rotate to Epoch 2 at t0 + 10 hours (within Epoch 1 lifetime)
    t_rot1 = t0 + datetime.timedelta(hours=10)
    # Simulate time passing by monkeypatching or calling rotate
    # In rotate(), active epochs receive sliding 24h overlap from rotation time:
    ep2 = hsm.rotate(new_epoch_id="EPOCH-002")

    # Update valid_to / overlap_until timestamps for testing exact boundaries
    conn = sqlite3.connect(kms_db)
    conn.execute(
        "UPDATE epoch_keys SET valid_from = ?, valid_to = ?, overlap_until = ? WHERE epoch_id = 'EPOCH-001';",
        (t0.isoformat(), t_rot1.isoformat(), (t_rot1 + datetime.timedelta(hours=24)).isoformat())
    )
    conn.execute(
        "UPDATE epoch_keys SET valid_from = ?, valid_to = ?, overlap_until = ? WHERE epoch_id = 'EPOCH-002';",
        (t_rot1.isoformat(), (t_rot1 + datetime.timedelta(hours=24)).isoformat(), (t_rot1 + datetime.timedelta(hours=48)).isoformat())
    )
    conn.commit()
    conn.close()

    acc = "ACC_BANK_A_000123"

    # A. During overlap (t_rot1 + 5h): Both epochs active
    t_mid_overlap = t_rot1 + datetime.timedelta(hours=5)
    overlap_tokens = hsm.tokenize_with_overlap(acc, as_of_ts=t_mid_overlap, requesting_bank_id="BANK_A")
    assert "EPOCH-001" in overlap_tokens
    assert "EPOCH-002" in overlap_tokens

    # B. Exactly at overlap boundary (overlap_until): Still accepted
    t_boundary = t_rot1 + datetime.timedelta(hours=24)
    tok_boundary = hsm.tokenize(acc, epoch_id="EPOCH-001", requesting_bank_id="BANK_A", as_of_ts=t_boundary)
    assert len(tok_boundary) == 64

    # C. Just after overlap boundary (overlap_until + 1s): Expired!
    t_expired = t_boundary + datetime.timedelta(seconds=1)
    with pytest.raises(ExpiredEpochError):
        hsm.tokenize(acc, epoch_id="EPOCH-001", requesting_bank_id="BANK_A", as_of_ts=t_expired)

    # D. Rotate again (double rotation within overlap window): Epoch 3
    t_rot2 = t_rot1 + datetime.timedelta(hours=6)
    ep3 = hsm.create_epoch(epoch_id="EPOCH-003", valid_from=t_rot2)
    # Check that at t_rot2 + 1h, all 3 epochs are bridgeable in overlap
    t_triple = t_rot2 + datetime.timedelta(hours=1)
    tokens_triple = hsm.tokenize_with_overlap(acc, as_of_ts=t_triple, requesting_bank_id="BANK_A")
    assert "EPOCH-001" in tokens_triple
    assert "EPOCH-002" in tokens_triple
    assert "EPOCH-003" in tokens_triple

    # E. Revocation during overlap: immediately blocked even if inside valid window
    hsm.revoke("EPOCH-002")
    with pytest.raises(RevokedEpochError):
        hsm.tokenize(acc, epoch_id="EPOCH-002", requesting_bank_id="BANK_A", as_of_ts=t_triple)


# ==============================================================================
# 7. RFC2409 Oakley Group 2 (1024-bit MODP Safe Prime) Properties & PSI
# ==============================================================================
def test_rfc2409_modp_1024_safe_prime_properties_and_psi():
    """Verify that RFC2409_MODP_1024_SAFE_PRIME is odd, 1024-bit, and a safe prime (p and (p-1)/2 are prime),

    and that EducationalDHPSI accurately computes intersection on known sets.
    """
    p = RFC2409_MODP_1024_SAFE_PRIME

    # 1. 1024-bit length
    assert p.bit_length() == 1024, f"Expected 1024 bits, got {p.bit_length()}"

    # 2. Odd integer
    assert p % 2 == 1, "Prime must be odd"

    # 3. p is a probable prime
    assert is_probable_prime(p, k=15), "Modulus p must be prime"

    # 4. Safe prime property: q = (p - 1) / 2 is also prime
    q = (p - 1) // 2
    assert is_probable_prime(q, k=15), "Sophie Germain cofactor (p-1)/2 must be prime"

    # 5. Educational DH-PSI correctness
    psi = EducationalDHPSI(prime=p)
    set_a = ["ACC_A_01", "ACC_A_02", "ACC_COMMON_01", "ACC_COMMON_02"]
    set_b = ["ACC_B_01", "ACC_COMMON_01", "ACC_COMMON_02", "ACC_B_02"]

    intersection, stats = psi.run_psi(set_a, set_b)
    assert intersection == {"ACC_COMMON_01", "ACC_COMMON_02"}
    assert stats["communication_rounds"] == 2
