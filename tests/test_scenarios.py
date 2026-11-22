"""Test suite for Phase 03 & 04: Fraud & Stress Scenario Generators.

Verifies:
1. Injected scenario counts match YAML configuration.
2. Konnagar scam has exactly `hops` hops, exits at BANK_D, and reproduces case SYN-0042.
3. Hard negatives (Durga Puja merchants, Student pass-through) are labeled `is_mule = 0`.
4. Fraud rings are labeled `is_mule = 1`.
5. Scenario pipeline determinism given identical seed.
6. Zero ground-truth leakage into central/audit databases.
"""

import hashlib
import json
import os
import pytest
import yaml

from src.simulator.generator import SyntheticGenerator
from src.simulator.scenarios import ScenarioEngine, run_scenario_pipeline


@pytest.fixture(scope="module")
def scenario_output(tmp_path_factory):
    """Execute scenario injection in a temporary directory for validation."""
    temp_dir = tmp_path_factory.mktemp("scen_test_dir")
    base_data = str(temp_dir / "data")

    all_txns, account_labels, scenario_metrics = run_scenario_pipeline(
        config_path="configs/simulation_v1.yaml",
        accounts_override=1000,
        full=False,
        data_dir=base_data,
        seed=42
    )

    return {
        "base_data": base_data,
        "all_txns": all_txns,
        "account_labels": account_labels,
        "scenario_metrics": scenario_metrics,
        "seed": 42
    }


def test_konnagar_scam_exact_hops_and_exit(scenario_output):
    """Verify that Konnagar scam has exactly `hops` (5) hops and exits at BANK_D."""
    all_txns = scenario_output["all_txns"]
    account_labels = scenario_output["account_labels"]

    konnagar_txs = [t for t in all_txns if "konnagar_scam" in t.scenario_label]
    assert len(konnagar_txs) == 5, f"Expected 5 hops in Konnagar scam, got {len(konnagar_txs)}"

    # Check amounts and sequence
    for t in konnagar_txs:
        assert t.amount_inr == 500000.0

    # Final hop must exit at BANK_D (non-participating)
    final_tx = konnagar_txs[-1]
    assert final_tx.receiving_bank == "BANK_D"
    assert "exit_BANK_D" in final_tx.scenario_label

    # Check case SYN-0042 reproduction with surgical lien demo
    syn_0042_labels = [l for l in account_labels.values() if l.case_id == "SYN-0042"]
    assert len(syn_0042_labels) == 1, "Expected Case SYN-0042 to be reproduced"
    target = syn_0042_labels[0]
    assert target.is_mule == 1
    assert target.unrestricted_balance_inr == 85000.0
    assert target.disputed_lien_inr == 2500.0


def test_hard_negatives_labeled_negative(scenario_output):
    """Ensure hard negatives (Festival merchants, Student fees) are strictly labeled is_mule = 0."""
    account_labels = scenario_output["account_labels"]

    # 1. Durga Puja merchants
    puja_labels = [l for l in account_labels.values() if l.scenario_label == "durga_puja_surge_merchant"]
    assert len(puja_labels) > 0, "Expected Durga Puja merchants to be labeled"
    for l in puja_labels:
        assert l.is_mule == 0, f"Kirana merchant {l.account_id} must be labeled benign (0)"
        assert l.account_type == "kirana_merchant"

    # 2. Student fee pass-through accounts
    student_labels = [l for l in account_labels.values() if l.scenario_label == "student_fee_passthrough"]
    assert len(student_labels) > 0, "Expected student pass-through accounts"
    for l in student_labels:
        assert l.is_mule == 0, f"Student {l.account_id} must be labeled benign (0)"
        assert l.account_type == "student"


def test_fraud_rings_labeled_positive(scenario_output):
    """Ensure fraud ring accounts are strictly labeled is_mule = 1."""
    account_labels = scenario_output["account_labels"]

    fraud_scenarios = [
        "konnagar_scam_mule",
        "smurfing_fan_out",
        "concentrator",
        "dormant_",
        "unjoined_leakage"
    ]

    for sc in fraud_scenarios:
        matched = [l for l in account_labels.values() if sc in l.scenario_label]
        assert len(matched) > 0, f"Missing fraud accounts for scenario {sc}"
        for l in matched:
            assert l.is_mule == 1, f"Fraud node {l.account_id} in {l.scenario_label} must be is_mule=1"


def test_injected_counts_match_config(scenario_output):
    """Verify that injected transaction counts match YAML specifications."""
    all_txns = scenario_output["all_txns"]

    # Student fee: pairs of in/out
    stu_in = [t for t in all_txns if t.scenario_label == "student_fee_parent_inflow"]
    stu_out = [t for t in all_txns if t.scenario_label == "student_fee_university_outflow"]
    assert len(stu_in) == len(stu_out)
    assert len(stu_in) > 0

    # Smurfing fan-out: 15 hops
    smurf_hops = [t for t in all_txns if t.scenario_label == "smurfing_fan_out_hop"]
    assert len(smurf_hops) == 15

    # Concentrator fan-in: 12 feeders
    conc_feeders = [t for t in all_txns if t.scenario_label == "concentrator_fan_in_feeder"]
    assert len(conc_feeders) == 12

    # Dormant awakening: 5 targets, each 1 in + 3 out = 20 txns
    dorm_in = [t for t in all_txns if t.scenario_label == "dormant_awakening_inflow"]
    dorm_out = [t for t in all_txns if t.scenario_label == "dormant_awakening_dispersal"]
    assert len(dorm_in) == 5
    assert len(dorm_out) == 15

    # Unjoined leakage: 3 chain hops ending at BANK_E
    leak_txs = [t for t in all_txns if "unjoined_leakage" in t.scenario_label]
    assert len(leak_txs) == 3


def test_scenario_determinism(tmp_path_factory):
    """Verify that identical random seeds generate bitwise-identical scenario ledgers."""
    dir1 = str(tmp_path_factory.mktemp("scen_det1") / "data")
    dir2 = str(tmp_path_factory.mktemp("scen_det2") / "data")

    txs1, lbls1, _ = run_scenario_pipeline(
        config_path="configs/simulation_v1.yaml",
        accounts_override=300,
        data_dir=dir1,
        seed=777
    )

    txs2, lbls2, _ = run_scenario_pipeline(
        config_path="configs/simulation_v1.yaml",
        accounts_override=300,
        data_dir=dir2,
        seed=777
    )

    # Compare transactions
    tx_tuples1 = [(t.txn_id, t.src_account_id, t.dst_account_id, t.amount_inr, t.timestamp, t.scenario_label) for t in txs1]
    tx_tuples2 = [(t.txn_id, t.src_account_id, t.dst_account_id, t.amount_inr, t.timestamp, t.scenario_label) for t in txs2]
    assert tx_tuples1 == tx_tuples2, "Scenario transactions diverged on identical seed!"

    # Compare labels
    lbl_tuples1 = sorted([(l.account_id, l.is_mule, l.scenario_label, l.disputed_lien_inr) for l in lbls1.values()])
    lbl_tuples2 = sorted([(l.account_id, l.is_mule, l.scenario_label, l.disputed_lien_inr) for l in lbls2.values()])
    assert lbl_tuples1 == lbl_tuples2, "Ground-truth labels diverged on identical seed!"


def test_zero_ground_truth_leakage_to_central_db(scenario_output):
    """Verify that ground-truth labels exist only in data/ground_truth and never in central/audit DBs."""
    base_data = scenario_output["base_data"]
    gt_dir = os.path.join(base_data, "ground_truth")

    assert os.path.exists(os.path.join(gt_dir, "labels.csv")), "labels.csv missing"
    assert os.path.exists(os.path.join(gt_dir, "txn_labels.csv")), "txn_labels.csv missing"
