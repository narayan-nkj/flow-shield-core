"""Regression test suite for CHANGE REQUEST CR02-B: P0 Data & Math Fixes.

Covers:
1. Cross-bank inward clearing, balance conservation, and non-negative balances (Bug 1).
2. Edge deduplication idempotency (Bug 2a).
3. Receiver local_token_map reverse lookup isolation (Bug 2b).
4. last_in_ts holding time hand-computed calculation (Bug 2c).
5. S_sweep double-counting prevention and [0, 1] clamping (Bug 3a).
6. Dormant account conservative r_repeat and uninflated M_local (Bug 3b).
"""

import datetime
import os
import sqlite3
import pytest
import yaml

from src.bank_local.local_features import extract_local_features
from src.bank_local.vault import BankVault
from src.common.ids import get_bank_db_path
from src.simulator.generator import SyntheticAccount, SyntheticGenerator
from src.token_service.hsm_mock import MockHSMService, PseudonymousEdgePipeline


# ==============================================================================
# BUG 1: Inward Clearing & Balance Conservation
# ==============================================================================
def test_cross_bank_conservation_and_non_negative_balances(tmp_path):
    """Verify that cross-bank transfers conserve funds, reflect in receiver DB, and no balance goes negative."""
    data_dir = str(tmp_path / "data")
    gen = SyntheticGenerator(config_path="configs/simulation_v1.yaml", seed=42)
    accounts = gen.generate_accounts(total_accounts=500)
    txns = gen.generate_transactions(accounts)
    gen.write_to_databases(accounts, txns, base_data_dir=data_dir)

    banks_dir = os.path.join(data_dir, "banks")
    all_banks = ["BANK_A", "BANK_B", "BANK_C", "BANK_D", "BANK_E"]

    # 1. Verify every cross-bank transaction has a matching incoming record in receiver bank
    cross_bank_txs = [t for t in txns if t.sending_bank != t.receiving_bank]
    assert len(cross_bank_txs) > 0, "No cross-bank transactions generated!"

    for ctx in cross_bank_txs:
        # Check receiver DB has matching inward record with identical amount
        recv_db = get_bank_db_path(ctx.receiving_bank, base_dir=banks_dir)
        conn_r = sqlite3.connect(recv_db)
        cur_r = conn_r.cursor()
        cur_r.execute(
            "SELECT amount_inr, dst_account_id FROM raw_transactions WHERE txn_id = ?;",
            (f"{ctx.txn_id}_IN",)
        )
        row = cur_r.fetchone()
        conn_r.close()

        assert row is not None, f"Receiver bank {ctx.receiving_bank} missing incoming record for {ctx.txn_id}!"
        assert row[0] == ctx.amount_inr, f"Amount mismatch in receiver {ctx.receiving_bank}: {row[0]} != {ctx.amount_inr}"
        assert row[1] == ctx.dst_account_id

    # 2. Verify that NO account in any bank database has a negative balance
    total_db_balance = 0.0
    for b in all_banks:
        db_path = get_bank_db_path(b, base_dir=banks_dir)
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT account_id, balance_inr FROM accounts;")
        for acc_id, bal in cur.fetchall():
            assert bal >= 0.0, f"Account {acc_id} in {b} has negative balance: {bal}!"
            total_db_balance += bal
        conn.close()

    assert total_db_balance > 0.0


def test_whole_dataset_conservation_and_inward_records():
    """Verify conservation across the entire generated dataset in data/banks/."""
    banks_dir = "data/banks"
    all_banks = ["BANK_A", "BANK_B", "BANK_C", "BANK_D", "BANK_E"]

    for b in all_banks:
        db_path = get_bank_db_path(b, base_dir=banks_dir)
        if not os.path.exists(db_path):
            pytest.skip("Full dataset not yet generated in data/banks")

        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        # Check no negative balances
        cur.execute("SELECT account_id, balance_inr FROM accounts WHERE balance_inr < 0.0;")
        negatives = cur.fetchall()
        assert len(negatives) == 0, f"Found accounts with negative balance in {b}: {negatives[:5]}"

        # Check inward transactions match
        cur.execute("""
            SELECT txn_id, src_account_id, dst_account_id, amount_inr
            FROM raw_transactions
            WHERE txn_id LIKE '%_IN';
        """)
        inward_txs = cur.fetchall()
        for in_tx in inward_txs:
            assert in_tx[1] == f"ACC_{b}_NPCI_INWARD", f"Inward transaction src must be clearing gateway: {in_tx}"
            assert in_tx[3] > 0.0

        conn.close()


# ==============================================================================
# BUG 2a: Edge Deduplication Idempotency
# ==============================================================================
def test_edge_deduplication_idempotent(tmp_path):
    """Verify that running PseudonymousEdgePipeline twice yields the identical edge count (idempotent)."""
    data_dir = str(tmp_path / "data")
    central_db = str(tmp_path / "risk_relay.db")
    kms_db = str(tmp_path / "hsm_mock.db")

    gen = SyntheticGenerator(config_path="configs/simulation_v1.yaml", seed=42)
    accounts = gen.generate_accounts(total_accounts=300)
    txns = gen.generate_transactions(accounts)
    gen.write_to_databases(accounts, txns, base_data_dir=data_dir)

    from src.init_dbs import init_kms_db, init_risk_db
    init_kms_db(db_path=kms_db)
    init_risk_db(db_path=central_db)

    hsm = MockHSMService(kms_db_path=kms_db)
    pipeline = PseudonymousEdgePipeline(
        hsm_service=hsm,
        central_db_path=central_db,
        base_data_dir=data_dir
    )

    # First run
    count1 = pipeline.process_edges(participating_banks=["BANK_A", "BANK_B", "BANK_C"])

    conn = sqlite3.connect(central_db)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM pseudonymous_edges;")
    db_count1 = cur.fetchone()[0]
    conn.close()

    assert db_count1 == count1
    assert count1 > 0

    # Second run (must be strictly idempotent)
    count2 = pipeline.process_edges(participating_banks=["BANK_A", "BANK_B", "BANK_C"])

    conn = sqlite3.connect(central_db)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM pseudonymous_edges;")
    db_count2 = cur.fetchone()[0]
    conn.close()

    assert db_count2 == db_count1, f"Pipeline not idempotent! First run: {db_count1}, second run: {db_count2}"
    assert count2 == count1


# ==============================================================================
# BUG 2b: Receiver local_token_map Reverse Lookup
# ==============================================================================
def test_receiver_local_token_map_reverse_lookup(tmp_path):
    """Verify that every dst_token can be resolved by exactly the receiving bank that owns it, and no other bank."""
    data_dir = str(tmp_path / "data")
    central_db = str(tmp_path / "risk_relay.db")
    kms_db = str(tmp_path / "hsm_mock.db")

    gen = SyntheticGenerator(config_path="configs/simulation_v1.yaml", seed=42)
    accounts = gen.generate_accounts(total_accounts=300)
    txns = gen.generate_transactions(accounts)
    gen.write_to_databases(accounts, txns, base_data_dir=data_dir)

    from src.init_dbs import init_kms_db, init_risk_db
    init_kms_db(db_path=kms_db)
    init_risk_db(db_path=central_db)

    hsm = MockHSMService(kms_db_path=kms_db)
    pipeline = PseudonymousEdgePipeline(
        hsm_service=hsm,
        central_db_path=central_db,
        base_data_dir=data_dir
    )
    pipeline.process_edges(participating_banks=["BANK_A", "BANK_B", "BANK_C"])

    # Collect dst_tokens from central DB
    conn = sqlite3.connect(central_db)
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT dst_token FROM pseudonymous_edges;")
    dst_tokens = [r[0] for r in cur.fetchall()]
    conn.close()

    assert len(dst_tokens) > 0

    banks_dir = os.path.join(data_dir, "banks")
    participating = ["BANK_A", "BANK_B", "BANK_C"]

    # For every participating bank, verify that accounts receiving transactions
    # have their tokens registered in their own local_token_map, and NO other bank can resolve them.
    for b in participating:
        b_db = get_bank_db_path(b, base_dir=banks_dir)
        conn_b = sqlite3.connect(b_db)
        cur_b = conn_b.cursor()
        cur_b.execute(f"SELECT DISTINCT dst_account_id FROM raw_transactions WHERE dst_account_id LIKE 'ACC_{b}_%';")
        dest_accs = [r[0] for r in cur_b.fetchall() if not r[0].endswith("_NPCI_INWARD")]
        conn_b.close()

        assert len(dest_accs) > 0, f"Expected incoming accounts in {b}"

        for acc in dest_accs[:15]:
            tok = hsm.tokenize(account_id=acc, epoch_id="EPOCH-SIMULATION-V1", requesting_bank_id=b)
            resolving_banks = []
            for other_b in participating:
                other_db = get_bank_db_path(other_b, base_dir=banks_dir)
                c_other = sqlite3.connect(other_db)
                cur_o = c_other.cursor()
                cur_o.execute("SELECT account_id FROM local_token_map WHERE token_hash = ?;", (tok,))
                row = cur_o.fetchone()
                c_other.close()
                if row:
                    resolving_banks.append((other_b, row[0]))

            assert len(resolving_banks) == 1, (
                f"Token for {acc} in {b} must be resolvable by exactly ONE bank ({b}), but found in {resolving_banks}!"
            )
            assert resolving_banks[0][0] == b
            assert resolving_banks[0][1] == acc


# ==============================================================================
# BUG 2c: last_in_ts Holding Time Calculation
# ==============================================================================
def test_last_in_ts_holding_time_hand_computed(tmp_path):
    """Verify holding time delta_t_sec is computed from most recent inbound timestamp (10:00:00 in, 10:03:00 out -> 180s)."""
    data_dir = str(tmp_path / "data")
    central_db = str(tmp_path / "risk_relay.db")
    kms_db = str(tmp_path / "hsm_mock.db")

    from src.init_dbs import init_bank_db, init_kms_db, init_risk_db
    init_kms_db(db_path=kms_db)
    init_risk_db(db_path=central_db)
    banks_dir = os.path.join(data_dir, "banks")
    init_bank_db("BANK_A", base_dir=banks_dir)

    # Insert 3 accounts in Bank A: Acc1 (funder), Acc2 (mule), Acc3 (receiver)
    db_a = get_bank_db_path("BANK_A", base_dir=banks_dir)
    conn = sqlite3.connect(db_a)
    conn.execute("PRAGMA foreign_keys = ON;")
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO accounts (account_id, bank_id, synthetic_name, account_type, account_age_days, balance_inr)
        VALUES
        ('ACC_BANK_A_000001', 'BANK_A', 'Synth_Funder', 'retail', 100, 50000.0),
        ('ACC_BANK_A_000002', 'BANK_A', 'Synth_Mule', 'retail', 50, 10000.0),
        ('ACC_BANK_A_000003', 'BANK_A', 'Synth_Receiver', 'retail', 50, 10000.0);
    """)

    # Tx1: Acc1 -> Acc2 at 10:00:00 (Inflow to Acc2)
    # Tx2: Acc2 -> Acc3 at 10:03:00 (Outflow from Acc2, holding time must be 180s)
    # Tx3: Acc1 -> Acc3 at 10:05:00 (Outflow from Acc1 who had NO prior inflow -> documented default)
    cur.execute("""
        INSERT INTO raw_transactions (txn_id, src_account_id, dst_account_id, amount_inr, channel, timestamp, scenario_label)
        VALUES
        ('TXN_TEST_001', 'ACC_BANK_A_000001', 'ACC_BANK_A_000002', 5000.0, 'UPI', '2026-11-20T10:00:00Z', 'inflow'),
        ('TXN_TEST_002', 'ACC_BANK_A_000002', 'ACC_BANK_A_000003', 4500.0, 'UPI', '2026-11-20T10:03:00Z', 'passthrough'),
        ('TXN_TEST_003', 'ACC_BANK_A_000001', 'ACC_BANK_A_000003', 2000.0, 'UPI', '2026-11-20T10:05:00Z', 'no_inflow_outflow');
    """)
    conn.commit()
    conn.close()

    hsm = MockHSMService(kms_db_path=kms_db)
    pipeline = PseudonymousEdgePipeline(
        hsm_service=hsm,
        central_db_path=central_db,
        base_data_dir=data_dir
    )
    pipeline.process_edges(participating_banks=["BANK_A"])

    # Query edges
    conn_c = sqlite3.connect(central_db)
    cur_c = conn_c.cursor()
    cur_c.execute("SELECT edge_id, event_ts, delta_t_sec FROM pseudonymous_edges ORDER BY event_ts ASC;")
    rows = cur_c.fetchall()
    conn_c.close()

    assert len(rows) == 3

    # Row 1 (TXN_TEST_001): Acc1 had no prior inflow -> default holding time (86400.0)
    assert rows[0][2] == 86400.0, f"Expected default 86400.0 for initial outflow, got {rows[0][2]}"

    # Row 2 (TXN_TEST_002): Acc2 received at 10:00:00, sent at 10:03:00 -> delta_t_sec = 180.0
    assert rows[1][2] == 180.0, f"Expected delta_t_sec=180.0, got {rows[1][2]}"

    # Row 3 (TXN_TEST_003): Acc1 has still had no INFLOW -> default holding time (86400.0)
    assert rows[2][2] == 86400.0, f"Expected default 86400.0, got {rows[2][2]}"


# ==============================================================================
# BUG 3a: S_sweep Double-Counting & Clamping
# ==============================================================================
def test_s_sweep_no_double_counting_and_clamped(tmp_path):
    """Verify that multiple overlapping inflow windows do NOT double-count an outflow, and S_sweep in [0, 1]."""
    base_data = str(tmp_path / "data")
    banks_dir = os.path.join(base_data, "banks")
    os.makedirs(banks_dir, exist_ok=True)
    from src.init_dbs import init_bank_db
    init_bank_db("BANK_A", base_dir=banks_dir)

    db_path = get_bank_db_path("BANK_A", base_dir=banks_dir)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO accounts (account_id, bank_id, synthetic_name, account_type, account_age_days, balance_inr)
        VALUES
        ('ACC_TEST_MULE', 'BANK_A', 'Synth_Mule_Sweep', 'retail', 200, 20000.0),
        ('ACC_PAYER_1', 'BANK_A', 'Synth_Payer_1', 'retail', 200, 50000.0),
        ('ACC_PAYER_2', 'BANK_A', 'Synth_Payer_2', 'retail', 200, 50000.0),
        ('ACC_RECV', 'BANK_A', 'Synth_Recv_1', 'retail', 200, 50000.0);
    """)

    # Inflow 1: 10:00:00 for INR 1,000 (window: 10:00 - 10:10)
    # Inflow 2: 10:05:00 for INR 1,000 (window: 10:05 - 10:15)
    # Total Inflow = 2,000 INR
    # Single Outflow: 10:07:00 for INR 1,000 (falls in BOTH windows!)
    # Correct swept_volume = 1,000 INR -> S_sweep = 1,000 / 2,000 = 0.50
    # Double-counted bug produces swept_volume = 2,000 INR -> S_sweep = 1.00
    cur.execute("""
        INSERT INTO raw_transactions (txn_id, src_account_id, dst_account_id, amount_inr, channel, timestamp, scenario_label)
        VALUES
        ('TXN_IN_1', 'ACC_PAYER_1', 'ACC_TEST_MULE', 1000.0, 'UPI', '2026-11-20T10:00:00Z', 'inflow_1'),
        ('TXN_IN_2', 'ACC_PAYER_2', 'ACC_TEST_MULE', 1000.0, 'UPI', '2026-11-20T10:05:00Z', 'inflow_2'),
        ('TXN_OUT_1', 'ACC_TEST_MULE', 'ACC_RECV', 1000.0, 'UPI', '2026-11-20T10:07:00Z', 'outflow_1');
    """)
    conn.commit()
    conn.close()

    vault = BankVault(bank_id="BANK_A", data_dir=banks_dir)
    payload = extract_local_features(
        account_id="ACC_TEST_MULE",
        token_hash="a" * 64,
        vault=vault,
        as_of_ts="2026-11-20T10:15:00Z",
        config_path="configs/features_v1.yaml"
    )

    # In extract_local_features:
    # 2 unique payers with 1 txn each -> r_repeat = 0.0
    # S_sweep should be 0.50, non_sweep = 0.50
    # Age stability = min(1.0, 200/365.0) = 0.5479
    # Expected M_local = 0.4 * 0.0 + 0.4 * (1.0 - 0.50) + 0.2 * (200 / 365.0) = 0.20 + 0.1096 = 0.3096
    expected_m_local = 0.4 * 0.0 + 0.4 * (1.0 - 0.50) + 0.2 * min(1.0, 200 / 365.0)
    assert abs(payload.m_local - expected_m_local) < 1e-3, (
        f"S_sweep double-counting detected! Got M_local={payload.m_local}, expected={expected_m_local}"
    )


# ==============================================================================
# BUG 3b: Dormant Account Conservative r_repeat & M_local
# ==============================================================================
def test_dormant_account_low_m_local(tmp_path):
    """Verify that a dormant account with NO transaction history does NOT receive an inflated M_local."""
    base_data = str(tmp_path / "data")
    banks_dir = os.path.join(base_data, "banks")
    os.makedirs(banks_dir, exist_ok=True)
    from src.init_dbs import init_bank_db
    init_bank_db("BANK_A", base_dir=banks_dir)

    db_path = get_bank_db_path("BANK_A", base_dir=banks_dir)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    # Mature dormant account (e.g. 500 days old) but ZERO transactions
    cur.execute("""
        INSERT INTO accounts (account_id, bank_id, synthetic_name, account_type, account_age_days, balance_inr)
        VALUES ('ACC_DORMANT_MULE', 'BANK_A', 'Synth_Dormant_Mule', 'retail', 500, 5000.0);
    """)
    conn.commit()
    conn.close()

    vault = BankVault(bank_id="BANK_A", data_dir=banks_dir)
    payload = extract_local_features(
        account_id="ACC_DORMANT_MULE",
        token_hash="a" * 64,
        vault=vault,
        as_of_ts="2026-11-20T12:00:00Z",
        config_path="configs/features_v1.yaml"
    )

    # Dormant account with zero customer history must NOT receive merchant protection discount!
    # Under old bug, r_repeat=0.5 and (1 - S_sweep)=1.0 -> M_local was 0.4*0.5 + 0.4*1.0 + 0.2*1.0 = 0.80!
    # Under conservative fix, r_repeat=0.0 and (1 - S_sweep)=0.0 (no retained merchant sales) -> M_local <= 0.20
    assert payload.m_local <= 0.25, (
        f"SECURITY FLAW: Dormant account received inflated merchant protection score M_local = {payload.m_local}!"
    )
