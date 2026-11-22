"""Test suite for Phase 02: Synthetic Generator.

Verifies:
1. Determinism (same seed = identical accounts, transactions, and hash).
2. Account counts and distribution match configuration within tolerances.
3. No negative balances or transaction amounts.
4. Transaction endpoints validity and foreign key satisfaction.
5. Participating vs unjoined bank configuration flags.
6. Merchant tiers and M_local bounds.
"""

import hashlib
import json
import os
import sqlite3
import pytest
import yaml

from src.common.ids import get_bank_db_path, normalize_bank_id
from src.simulator.generator import SyntheticGenerator, run_generation


@pytest.fixture(scope="module")
def gen_output(tmp_path_factory):
    """Run generation in a temporary directory for testing."""
    temp_dir = tmp_path_factory.mktemp("gen_test_dir")
    base_data = str(temp_dir / "data")
    summary_path = str(temp_dir / "sim_summary.md")

    bank_accounts, transactions = run_generation(
        config_path="configs/simulation_v1.yaml",
        accounts_override=1000,
        full=False,
        data_dir=base_data,
        summary_path=summary_path,
        seed=123
    )

    return {
        "base_data": base_data,
        "summary_path": summary_path,
        "bank_accounts": bank_accounts,
        "transactions": transactions,
        "seed": 123
    }


def test_determinism(tmp_path_factory):
    """Verify that running the generator with the identical seed produces identical output."""
    dir1 = str(tmp_path_factory.mktemp("det1") / "data")
    dir2 = str(tmp_path_factory.mktemp("det2") / "data")

    gen1 = SyntheticGenerator(config_path="configs/simulation_v1.yaml", seed=999)
    accs1 = gen1.generate_accounts(total_accounts=500)
    txs1 = gen1.generate_transactions(accs1)

    gen2 = SyntheticGenerator(config_path="configs/simulation_v1.yaml", seed=999)
    accs2 = gen2.generate_accounts(total_accounts=500)
    txs2 = gen2.generate_transactions(accs2)

    # 1. Accounts comparison
    for b in gen1.all_banks:
        list1 = [(a.account_id, a.balance_inr, a.account_type, a.synthetic_name) for a in accs1[b]]
        list2 = [(a.account_id, a.balance_inr, a.account_type, a.synthetic_name) for a in accs2[b]]
        assert list1 == list2, f"Accounts diverged for bank {b}"

    # 2. Transactions comparison
    tx_tuples1 = [(t.txn_id, t.src_account_id, t.dst_account_id, t.amount_inr, t.timestamp) for t in txs1]
    tx_tuples2 = [(t.txn_id, t.src_account_id, t.dst_account_id, t.amount_inr, t.timestamp) for t in txs2]
    assert tx_tuples1 == tx_tuples2, "Transactions diverged between identical runs!"

    # 3. Hash comparison
    h1 = hashlib.sha256(json.dumps(tx_tuples1).encode("utf-8")).hexdigest()
    h2 = hashlib.sha256(json.dumps(tx_tuples2).encode("utf-8")).hexdigest()
    assert h1 == h2, f"Transaction hashes diverged: {h1} != {h2}"


def test_counts_match_config(gen_output):
    """Verify account counts and distribution match YAML configuration."""
    bank_accounts = gen_output["bank_accounts"]
    total_accs = sum(len(accs) for accs in bank_accounts.values())

    # 1,000 requested accounts + 5 inward clearing accounts (1 per bank)
    assert total_accs == 1005

    # Check distribution proportions
    with open("configs/simulation_v1.yaml", "r") as f:
        cfg = yaml.safe_load(f)["simulation"]["account_distribution"]

    all_regular_accs = [
        a for accs in bank_accounts.values()
        for a in accs if not a.account_id.endswith("_NPCI_INWARD")
    ]
    n_reg = len(all_regular_accs)
    retail_ratio = sum(1 for a in all_regular_accs if a.account_type == "retail") / n_reg
    merchant_ratio = sum(1 for a in all_regular_accs if a.account_type == "kirana_merchant") / n_reg
    student_ratio = sum(1 for a in all_regular_accs if a.account_type == "student") / n_reg

    # Check within reasonable random tolerance (+/- 3%)
    assert abs(retail_ratio - cfg["retail"]) < 0.04
    assert abs(merchant_ratio - cfg["kirana_merchant"]) < 0.03
    assert abs(student_ratio - cfg["student"]) < 0.03


def test_no_negative_balances_or_amounts(gen_output):
    """Ensure all accounts have balance > 0 and all transactions have amount > 0."""
    base_data = gen_output["base_data"]
    banks_dir = os.path.join(base_data, "banks")

    for bank_id in ["BANK_A", "BANK_B", "BANK_C", "BANK_D", "BANK_E"]:
        db_path = get_bank_db_path(bank_id, base_dir=banks_dir)
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        # Check account balances
        cur.execute("SELECT MIN(balance_inr), COUNT(*) FROM accounts;")
        min_balance, acc_count = cur.fetchone()
        assert acc_count > 0
        assert min_balance > 0, f"Negative or zero balance found in {bank_id}: {min_balance}"

        # Check transaction amounts
        cur.execute("SELECT MIN(amount_inr), COUNT(*) FROM raw_transactions;")
        min_amount, tx_count = cur.fetchone()
        assert tx_count > 0
        assert min_amount > 0, f"Negative or zero amount found in {bank_id}: {min_amount}"

        conn.close()


def test_all_txn_endpoints_exist_and_satisfy_fk(gen_output):
    """Verify that every transaction's src_account_id exists in the bank's accounts table."""
    base_data = gen_output["base_data"]
    banks_dir = os.path.join(base_data, "banks")

    for bank_id in ["BANK_A", "BANK_B", "BANK_C", "BANK_D", "BANK_E"]:
        db_path = get_bank_db_path(bank_id, base_dir=banks_dir)
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys = ON;")
        cur = conn.cursor()

        # Query all transactions and check if src_account_id exists in accounts table
        cur.execute("""
            SELECT t.txn_id, t.src_account_id
            FROM raw_transactions t
            LEFT JOIN accounts a ON t.src_account_id = a.account_id
            WHERE a.account_id IS NULL;
        """)
        orphaned = cur.fetchall()
        assert len(orphaned) == 0, f"Found orphaned transactions in {bank_id}: {orphaned}"

        # Verify foreign keys check passed without database corruption
        cur.execute("PRAGMA foreign_key_check;")
        fk_violations = cur.fetchall()
        assert len(fk_violations) == 0, f"Foreign key violations in {bank_id}: {fk_violations}"

        conn.close()


def test_participating_flags():
    """Verify participating vs unjoined bank identification."""
    gen = SyntheticGenerator(config_path="configs/simulation_v1.yaml")
    assert gen.participating_banks == ["BANK_A", "BANK_B", "BANK_C"]
    assert gen.unjoined_banks == ["BANK_D", "BANK_E"]
    assert len(gen.all_banks) == 5


def test_merchant_size_tiers_and_m_local(gen_output):
    """Verify merchant size tiers and bounds on m_local_score, mu_90d, sigma_90d."""
    base_data = gen_output["base_data"]
    banks_dir = os.path.join(base_data, "banks")

    all_merchant_tiers = set()
    for bank_id in ["BANK_A", "BANK_B", "BANK_C", "BANK_D", "BANK_E"]:
        db_path = get_bank_db_path(bank_id, base_dir=banks_dir)
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        # Kirana merchants must have valid tiers
        cur.execute("""
            SELECT merchant_size_tier, COUNT(*)
            FROM accounts
            WHERE account_type = 'kirana_merchant'
            GROUP BY merchant_size_tier;
        """)
        tiers = dict(cur.fetchall())
        for tier in tiers.keys():
            assert tier in ("micro", "small", "medium"), f"Unexpected tier {tier} in {bank_id}"
            all_merchant_tiers.add(tier)

        # Non-merchants should have NULL tier
        cur.execute("""
            SELECT COUNT(*) FROM accounts
            WHERE account_type != 'kirana_merchant' AND merchant_size_tier IS NOT NULL;
        """)
        invalid_tiers = cur.fetchone()[0]
        assert invalid_tiers == 0

        # M_local in [0, 1]
        cur.execute("SELECT MIN(m_local_score), MAX(m_local_score) FROM accounts;")
        min_m, max_m = cur.fetchone()
        assert 0.0 <= min_m <= max_m <= 1.0

        # mu_90d and sigma_90d > 0
        cur.execute("SELECT MIN(mu_90d), MIN(sigma_90d) FROM accounts;")
        min_mu, min_sigma = cur.fetchone()
        assert min_mu > 0
        assert min_sigma > 0

        conn.close()

    assert all_merchant_tiers == {"micro", "small", "medium"}, f"Missing expected merchant tiers: {all_merchant_tiers}"

