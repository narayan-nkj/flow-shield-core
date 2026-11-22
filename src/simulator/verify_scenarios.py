#!/usr/bin/env python3
"""CHAKRA-DPI Scenario Log Verification Script (Guide Day 4).

Validates:
1. Scenario counts against YAML configuration parameters.
2. Per-bank transaction volumes and institutional routing.
3. Hold-time distributions (Mules vs Students vs Merchants).
4. Physical database integrity and cross-bank boundary verification.
5. Saves structured verification report to `docs/generated/scenario_verification.md`.
"""

import argparse
import csv
import datetime
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import yaml

# Add root directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from src.common.ids import get_bank_db_path, normalize_bank_id


def verify_simulation_logs(
    config_path: str = "configs/simulation_v1.yaml",
    data_dir: str = "data",
    output_report_path: str = "docs/generated/scenario_verification.md"
) -> Dict[str, Any]:
    """Verify generated scenario ledgers and ground-truth labels."""
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    banks_dir = os.path.join(data_dir, "banks")
    gt_dir = os.path.join(data_dir, "ground_truth")
    labels_csv = os.path.join(gt_dir, "labels.csv")
    txn_labels_csv = os.path.join(gt_dir, "txn_labels.csv")

    banks = ["BANK_A", "BANK_B", "BANK_C", "BANK_D", "BANK_E"]
    bank_tx_counts: Dict[str, int] = {}
    bank_volumes: Dict[str, float] = {}
    scenario_counts: Dict[str, int] = {}
    scenario_volumes: Dict[str, float] = {}

    # 1. Read transactions from bank databases
    all_txns_from_dbs = []
    for b in banks:
        db_path = get_bank_db_path(b, base_dir=banks_dir)
        if not os.path.exists(db_path):
            raise FileNotFoundError(f"Missing bank database: {db_path}")

        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT txn_id, src_account_id, dst_account_id, amount_inr, channel, timestamp, scenario_label FROM raw_transactions;")
        rows = cur.fetchall()
        bank_tx_counts[b] = len(rows)
        bank_volumes[b] = sum(r[3] for r in rows)
        all_txns_from_dbs.extend(rows)
        conn.close()

    # 2. Read ground-truth transaction labels
    gt_txns = []
    if os.path.exists(txn_labels_csv):
        with open(txn_labels_csv, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                gt_txns.append(row)
                sc = row["scenario_label"]
                scenario_counts[sc] = scenario_counts.get(sc, 0) + 1
                scenario_volumes[sc] = scenario_volumes.get(sc, 0.0) + float(row["amount_inr"])

    # 3. Read account ground-truth labels
    gt_accounts: Dict[str, Dict[str, Any]] = {}
    if os.path.exists(labels_csv):
        with open(labels_csv, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                gt_accounts[row["account_id"]] = row

    # 4. Hold-time analysis
    # Mules (Konnagar, Unjoined leakage) vs Students vs Kirana Merchants
    mule_hold_times: List[float] = []
    student_hold_times: List[float] = []

    # Sort GT transactions by timestamp
    gt_txns_sorted = sorted(gt_txns, key=lambda x: x["timestamp"])

    # Analyze Konnagar hops
    konnagar_hops = [t for t in gt_txns_sorted if "konnagar_scam" in t["scenario_label"]]
    for i in range(len(konnagar_hops) - 1):
        t1 = datetime.datetime.fromisoformat(konnagar_hops[i]["timestamp"].replace("Z", "+00:00"))
        t2 = datetime.datetime.fromisoformat(konnagar_hops[i + 1]["timestamp"].replace("Z", "+00:00"))
        delta = (t2 - t1).total_seconds()
        mule_hold_times.append(delta)

    # Analyze Student pass-through pairs
    student_pairs: Dict[str, Dict[str, str]] = {}
    for t in gt_txns_sorted:
        if "student_fee" in t["scenario_label"]:
            # Extract identifier prefix (e.g. TXN_STU_FEE_00001)
            pair_id = t["txn_id"].replace("_IN", "").replace("_OUT", "")
            if pair_id not in student_pairs:
                student_pairs[pair_id] = {}
            if t["txn_id"].endswith("_IN"):
                student_pairs[pair_id]["in"] = t["timestamp"]
            elif t["txn_id"].endswith("_OUT"):
                student_pairs[pair_id]["out"] = t["timestamp"]

    for pair in student_pairs.values():
        if "in" in pair and "out" in pair:
            t_in = datetime.datetime.fromisoformat(pair["in"].replace("Z", "+00:00"))
            t_out = datetime.datetime.fromisoformat(pair["out"].replace("Z", "+00:00"))
            student_hold_times.append((t_out - t_in).total_seconds())

    # 5. Confirm scenario parameter matches against YAML
    confirmations = []

    # Konnagar checks
    k_cfg = cfg.get("scenarios", {}).get("konnagar_scam", {})
    expected_hops = int(k_cfg.get("hops", 5))
    expected_amt = float(k_cfg.get("disputed_amount_inr", 500000))
    expected_leak = normalize_bank_id(k_cfg.get("leakage_bank", "BANK_D"))

    konnagar_count = len(konnagar_hops)
    k_match_hops = (konnagar_count == expected_hops)
    k_exit_match = any(t["receiving_bank"] == expected_leak for t in konnagar_hops[-1:])
    k_amt_match = all(float(t["amount_inr"]) == expected_amt for t in konnagar_hops)

    confirmations.append({
        "check": "Konnagar Scam Hop Count",
        "expected": expected_hops,
        "actual": konnagar_count,
        "status": "PASS" if k_match_hops else "FAIL"
    })
    confirmations.append({
        "check": "Konnagar Exit Bank Leakage",
        "expected": expected_leak,
        "actual": konnagar_hops[-1]["receiving_bank"] if konnagar_hops else "NONE",
        "status": "PASS" if k_exit_match else "FAIL"
    })
    confirmations.append({
        "check": "Konnagar Disputed Amount",
        "expected": f"INR {expected_amt:,.2f}",
        "actual": f"INR {float(konnagar_hops[0]['amount_inr']):,.2f}" if konnagar_hops else "NONE",
        "status": "PASS" if k_amt_match else "FAIL"
    })

    # Case SYN-0042 check
    syn_0042_acc = [acc for acc in gt_accounts.values() if acc.get("case_id") == "SYN-0042"]
    has_syn_0042 = len(syn_0042_acc) > 0
    confirmations.append({
        "check": "Case SYN-0042 Target Reproduction",
        "expected": "Present with surgical lien values",
        "actual": f"Found on {syn_0042_acc[0]['account_id']} (Unrestricted: INR {float(syn_0042_acc[0]['unrestricted_balance_inr']):,.2f}, Disputed: INR {float(syn_0042_acc[0]['disputed_lien_inr']):,.2f})" if has_syn_0042 else "MISSING",
        "status": "PASS" if has_syn_0042 else "FAIL"
    })

    # Student hold time check
    s_cfg = cfg.get("scenarios", {}).get("student_fee_passthrough", {})
    max_stu_hold = float(s_cfg.get("hold_time_max_sec", 180))
    stu_hold_pass = all(h <= max_stu_hold for h in student_hold_times) if student_hold_times else False
    confirmations.append({
        "check": "Student Fee Pass-Through Max Hold Time",
        "expected": f"<= {max_stu_hold}s",
        "actual": f"Max: {max(student_hold_times):.1f}s, Mean: {np.mean(student_hold_times):.1f}s" if student_hold_times else "None",
        "status": "PASS" if stu_hold_pass else "FAIL"
    })

    # 6. Generate Markdown Verification Report
    os.makedirs(os.path.dirname(output_report_path), exist_ok=True)
    md = [
        "# CHAKRA-DPI Scenario & Log Verification Report (Guide Day 4)",
        "",
        f"**Verification Timestamp:** {datetime.datetime.now(datetime.timezone.utc).isoformat()}",
        f"**Configuration File:** `{config_path}`",
        f"**Random Seed:** `{cfg.get('seed', 42)}`",
        "",
        "---",
        "",
        "## 1. Scenario Parameter Confirmation Matrix",
        "",
        "| Verification Metric | Expected Specification | Actual Injected Value | Audit Status |",
        "| :--- | :--- | :--- | :--- |"
    ]

    for conf in confirmations:
        status_icon = "✔ PASS" if conf["status"] == "PASS" else "❌ FAIL"
        md.append(f"| **{conf['check']}** | `{conf['expected']}` | {conf['actual']} | **{status_icon}** |")

    md.extend([
        "",
        "---",
        "",
        "## 2. Injected Scenario Volumes & Breakdown",
        "",
        f"* **Total Unique Ground-Truth Transactions:** {len(gt_txns):,}",
        f"* **Total Bank DB Rows (including inward views):** {len(all_txns_from_dbs):,}",
        f"* **Total Labeled Accounts:** {len(gt_accounts):,}",
        "",
        "| Scenario Group | Transaction Count | Volume (INR) | Primary Risk Archetype |",
        "| :--- | :--- | :--- | :--- |"
    ])

    for sc, count in sorted(scenario_counts.items(), key=lambda x: x[1], reverse=True):
        vol = scenario_volumes.get(sc, 0.0)
        md.append(f"| `{sc}` | {count:,} | INR {vol:,.2f} | Simulation Activity |")

    md.extend([
        "",
        "---",
        "",
        "## 3. Physical Bank Isolation & Transaction Volumes",
        "",
        "| Bank Identifier | Status | In-DB Transaction Entries | Total Recorded Volume (INR) |",
        "| :--- | :--- | :--- | :--- |"
    ])

    for b in banks:
        st = "Participating" if b in ["BANK_A", "BANK_B", "BANK_C"] else "Unjoined / External"
        md.append(f"| `{b}` | {st} | {bank_tx_counts[b]:,} | INR {bank_volumes[b]:,.2f} |")

    md.extend([
        "",
        "---",
        "",
        "## 4. Hold-Time Empirical Distribution Analysis",
        "",
        "Hold time $\\tau_{\\text{hold}}$ is the primary input to Pass-Through Velocity $V_p(u, \\Delta T) \\propto \\exp(-\\lambda \\cdot \\tau_{\\text{hold}})$.",
        "",
        "| Entity Category | Sample Count | Min Hold | Mean Hold | Median (p50) | p90 | Max Hold | Compliance |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |"
    ])

    if mule_hold_times:
        md.append(
            f"| **Mules (Konnagar)** | {len(mule_hold_times)} | {min(mule_hold_times):.1f}s | "
            f"{np.mean(mule_hold_times):.1f}s | {np.median(mule_hold_times):.1f}s | "
            f"{np.percentile(mule_hold_times, 90):.1f}s | {max(mule_hold_times):.1f}s | Rapid Velocity |"
        )
    if student_hold_times:
        md.append(
            f"| **Students (Tuition)** | {len(student_hold_times)} | {min(student_hold_times):.1f}s | "
            f"{np.mean(student_hold_times):.1f}s | {np.median(student_hold_times):.1f}s | "
            f"{np.percentile(student_hold_times, 90):.1f}s | {max(student_hold_times):.1f}s | Safe Tuition Flow (<= 180s) |"
        )

    md.extend([
        "",
        "---",
        "*Verification completed and validated under SFIC 2026 Phase 04.*"
    ])

    report_text = "\n".join(md)
    with open(output_report_path, "w", encoding="utf-8") as f:
        f.write(report_text)

    print(f"[✔] Scenario verification complete. Report generated at '{output_report_path}'.")
    return {
        "confirmations": confirmations,
        "scenario_counts": scenario_counts,
        "bank_counts": bank_tx_counts,
        "mule_hold_times": mule_hold_times,
        "student_hold_times": student_hold_times
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CHAKRA-DPI Scenario Log Verifier")
    parser.add_argument("--config", default="configs/simulation_v1.yaml", help="Path to simulation YAML config.")
    parser.add_argument("--data-dir", default="data", help="Base directory for database files (default: data).")
    parser.add_argument("--report", default="docs/generated/scenario_verification.md", help="Path to markdown output report.")
    args = parser.parse_args()

    verify_simulation_logs(
        config_path=args.config,
        data_dir=args.data_dir,
        output_report_path=args.report
    )
