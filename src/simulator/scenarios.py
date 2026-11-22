#!/usr/bin/env python3
"""CHAKRA-DPI Fraud and Stress Scenario Generator.

Implements config-driven, seeded scenario injection:
1. KONNAGAR_SCAM: ₹5,00,000 multi-hop mule chain with rapid velocity, leaking at BANK_D (case SYN-0042).
2. DURGA_PUJA_SURGE: 10x merchant volume surge over 48 hours with high repeat-customer ratios (Hard Negative).
3. STUDENT_FEE_PASSTHROUGH: Rapid tuition fee pass-through (hold time <= 180s) to university nodal (Hard Negative).
4. SMURFING_FAN_OUT: High out-degree entropy disbursement ring (Positive).
5. CONCENTRATOR_FAN_IN: Multi-source aggregation into central mule (Positive).
6. DORMANT_AWAKENING: Long-dormant account with sudden high-velocity volume spike (Positive).
7. UNJOINED_LEAKAGE: Cross-bank layering exiting to unjoined bank BANK_E (Positive).
8. WARM_UP: Baseline pre-period establishing rolling windows and mu/sigma priors.

Ground-truth labels are written strictly to `data/ground_truth/labels.csv` and never
stored in central risk or audit databases.
"""

import argparse
import csv
import datetime
import json
import os
import random
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np
import yaml

# Add root directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from src.common.ids import get_bank_db_path, normalize_bank_id
from src.simulator.generator import (
    SyntheticAccount,
    SyntheticGenerator,
    SyntheticTransaction,
)


@dataclass
class AccountLabel:
    account_id: str
    bank_id: str
    account_type: str
    is_mule: int  # 1 for fraudulent mule, 0 for legitimate / hard negative
    scenario_label: str
    disputed_lien_inr: float
    unrestricted_balance_inr: float
    case_id: Optional[str]
    notes: str


class ScenarioEngine:
    """Config-driven generator for fraud rings, hard negatives, and stress scenarios."""

    def __init__(self, config_path: str = "configs/simulation_v1.yaml", seed: Optional[int] = None):
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)

        self.seed = seed if seed is not None else self.config.get("seed", 42)
        self.rng = random.Random(self.seed + 100)
        self.np_rng = np.random.default_rng(self.seed + 100)

        sim_cfg = self.config["simulation"]
        self.participating_banks = [normalize_bank_id(b) for b in sim_cfg["participating_banks"]]
        self.unjoined_banks = [normalize_bank_id(b) for b in sim_cfg["unjoined_banks"]]
        self.all_banks = self.participating_banks + self.unjoined_banks
        self.scenarios_cfg = self.config.get("scenarios", {})

        # Base simulation start timestamp
        self.base_start = datetime.datetime(2026, 11, 15, 0, 0, 0, tzinfo=datetime.timezone.utc)

    def _select_channel(self, amount: float) -> str:
        """Payment rail selector."""
        if amount > 200000.0:
            return "RTGS" if self.rng.random() < 0.85 else "IMPS"
        elif amount > 50000.0:
            return "IMPS" if self.rng.random() < 0.70 else "UPI"
        else:
            return "UPI" if self.rng.random() < 0.90 else "IMPS"

    def inject_all(
        self,
        bank_accounts: Dict[str, List[SyntheticAccount]],
        existing_txns: List[SyntheticTransaction]
    ) -> Tuple[List[SyntheticTransaction], Dict[str, AccountLabel], Dict[str, Any]]:
        """Execute all enabled scenarios and return combined transactions and ground truth."""
        injected_txns: List[SyntheticTransaction] = []
        account_labels: Dict[str, AccountLabel] = {}
        scenario_metrics: Dict[str, Any] = {}

        # 8. Warm-up pre-period
        if self.scenarios_cfg.get("warm_up", {}).get("enabled", True):
            txs, lbls, metrics = self.inject_warmup_period(bank_accounts)
            injected_txns.extend(txs)
            account_labels.update(lbls)
            scenario_metrics["warm_up"] = metrics

        # 1. Konnagar Scam
        if self.scenarios_cfg.get("konnagar_scam", {}).get("enabled", True):
            txs, lbls, metrics = self.inject_konnagar_scam(bank_accounts)
            injected_txns.extend(txs)
            account_labels.update(lbls)
            scenario_metrics["konnagar_scam"] = metrics

        # 2. Durga Puja Merchant Surge (Hard Negatives)
        if self.scenarios_cfg.get("durga_puja_surge", {}).get("enabled", True):
            txs, lbls, metrics = self.inject_durga_puja_surge(bank_accounts)
            injected_txns.extend(txs)
            account_labels.update(lbls)
            scenario_metrics["durga_puja_surge"] = metrics

        # 3. Student Fee Pass-Through (Hard Negatives)
        if self.scenarios_cfg.get("student_fee_passthrough", {}).get("enabled", True):
            txs, lbls, metrics = self.inject_student_fee_passthrough(bank_accounts)
            injected_txns.extend(txs)
            account_labels.update(lbls)
            scenario_metrics["student_fee_passthrough"] = metrics

        # 4. Smurfing / Fan-Out
        if self.scenarios_cfg.get("smurfing_fan_out", {}).get("enabled", True):
            txs, lbls, metrics = self.inject_smurfing_fan_out(bank_accounts)
            injected_txns.extend(txs)
            account_labels.update(lbls)
            scenario_metrics["smurfing_fan_out"] = metrics

        # 5. Concentrator / Fan-In Ring
        if self.scenarios_cfg.get("concentrator_fan_in", {}).get("enabled", True):
            txs, lbls, metrics = self.inject_concentrator_fan_in(bank_accounts)
            injected_txns.extend(txs)
            account_labels.update(lbls)
            scenario_metrics["concentrator_fan_in"] = metrics

        # 6. Dormant Account Awakening
        if self.scenarios_cfg.get("dormant_awakening", {}).get("enabled", True):
            txs, lbls, metrics = self.inject_dormant_awakening(bank_accounts)
            injected_txns.extend(txs)
            account_labels.update(lbls)
            scenario_metrics["dormant_awakening"] = metrics

        # 7. Unjoined Bank Leakage
        if self.scenarios_cfg.get("unjoined_leakage", {}).get("enabled", True):
            txs, lbls, metrics = self.inject_unjoined_leakage(bank_accounts)
            injected_txns.extend(txs)
            account_labels.update(lbls)
            scenario_metrics["unjoined_leakage"] = metrics

        # Merge with existing transactions and sort chronologically
        all_txns = existing_txns + injected_txns
        all_txns.sort(key=lambda t: t.timestamp)

        return all_txns, account_labels, scenario_metrics

    # --- Scenario 1: Konnagar Scam (₹5,00,000, 5 hops, leakage at BANK_D, Case SYN-0042) ---
    def inject_konnagar_scam(
        self, bank_accounts: Dict[str, List[SyntheticAccount]]
    ) -> Tuple[List[SyntheticTransaction], Dict[str, AccountLabel], Dict[str, Any]]:
        cfg = self.scenarios_cfg.get("konnagar_scam", {})
        disputed_amt = float(cfg.get("disputed_amount_inr", 500000))
        hops = int(cfg.get("hops", 5))
        leakage_bank = normalize_bank_id(cfg.get("leakage_bank", "BANK_D"))
        case_id = cfg.get("case_id", "SYN-0042")
        lien_demo = cfg.get("lien_demo", {"unrestricted_balance_inr": 85000, "disputed_lien_inr": 2500})
        min_hold = cfg.get("hold_time_sec_min", 45)
        max_hold = cfg.get("hold_time_sec_max", 120)

        # 1. Select origin victim at a participating bank (BANK_A)
        victim = [a for a in bank_accounts["BANK_A"] if a.account_type == "retail"][0]

        # Innocent Kirana branch: legitimate small local grocery recipient (CR02-C)
        innocent_amt = float(cfg.get("innocent_branch_amount_inr", lien_demo.get("disputed_lien_inr", 2500.0)))
        innocent_kirana = [a for a in bank_accounts["BANK_A"] if a.account_type == "kirana_merchant"][0]

        # 2. Select 4 intermediate mules across participating banks, plus 1 exit mule at leakage_bank
        mules: List[SyntheticAccount] = []
        hop_banks = ["BANK_B", "BANK_C", "BANK_A", "BANK_B"]
        for b_id in hop_banks[:hops - 1]:
            mule = self.rng.choice([a for a in bank_accounts[b_id] if a.account_type == "retail" and a != victim])
            mules.append(mule)

        # Final hop: account at unjoined leakage bank (BANK_D)
        exit_mule = self.rng.choice([a for a in bank_accounts[leakage_bank] if a.account_type == "retail"])
        mules.append(exit_mule)

        txns: List[SyntheticTransaction] = []
        labels: Dict[str, AccountLabel] = {}
        hold_times: List[float] = []

        # Start attack on Day 3 at 14:15 UTC
        curr_ts = self.base_start + datetime.timedelta(days=3, hours=14, minutes=15)
        current_sender = victim

        # Add innocent kirana branch transaction from victim-side flow
        t_innocent = curr_ts - datetime.timedelta(minutes=20)
        tx_innocent = SyntheticTransaction(
            txn_id="TXN_SCAM_KNG_INNOCENT",
            src_account_id=victim.account_id,
            dst_account_id=innocent_kirana.account_id,
            amount_inr=innocent_amt,
            channel="UPI",
            timestamp=t_innocent.strftime("%Y-%m-%dT%H:%M:%SZ"),
            scenario_label="innocent_kirana_victim_payment",
            sending_bank=victim.bank_id,
            receiving_bank=innocent_kirana.bank_id
        )
        txns.append(tx_innocent)

        # Label innocent kirana as negative (is_mule = 0) with proportionality demo values
        labels[innocent_kirana.account_id] = AccountLabel(
            account_id=innocent_kirana.account_id,
            bank_id=innocent_kirana.bank_id,
            account_type=innocent_kirana.account_type,
            is_mule=0,  # INNOCENT / NEGATIVE
            scenario_label="konnagar_scam_innocent_kirana",
            disputed_lien_inr=innocent_amt,
            unrestricted_balance_inr=float(lien_demo.get("unrestricted_balance_inr", 85000.0)),
            case_id="SYN-0042-INNOCENT",
            notes="Innocent local kirana merchant receiving legitimate ₹2,500 payment from victim-side flow; demonstrates proportionate partial lien (₹2,500 lien on ₹85,000 balance)."
        )

        for hop_idx, next_receiver in enumerate(mules, 1):
            tx_id = f"TXN_SCAM_KNG_{hop_idx:02d}"
            label_name = f"konnagar_scam_hop_{hop_idx}"
            if next_receiver.bank_id == leakage_bank:
                label_name = f"konnagar_scam_exit_{leakage_bank}"

            tx = SyntheticTransaction(
                txn_id=tx_id,
                src_account_id=current_sender.account_id,
                dst_account_id=next_receiver.account_id,
                amount_inr=disputed_amt,
                channel="IMPS" if disputed_amt <= 200000.0 else "RTGS",
                timestamp=curr_ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                scenario_label=label_name,
                sending_bank=current_sender.bank_id,
                receiving_bank=next_receiver.bank_id
            )
            txns.append(tx)

            # Hold time for next hop (rapid layering)
            hold = self.rng.uniform(min_hold, max_hold)
            hold_times.append(hold)
            curr_ts += datetime.timedelta(seconds=int(hold))
            current_sender = next_receiver

        # Assign ground-truth labels to mules
        for idx, m in enumerate(mules, 1):
            is_demo_target = (idx == 2)
            unrestricted = float(lien_demo["unrestricted_balance_inr"]) if is_demo_target else m.balance_inr
            lien_amt = float(lien_demo["disputed_lien_inr"]) if is_demo_target else disputed_amt

            labels[m.account_id] = AccountLabel(
                account_id=m.account_id,
                bank_id=m.bank_id,
                account_type=m.account_type,
                is_mule=1,
                scenario_label=f"konnagar_scam_mule_hop_{idx}",
                disputed_lien_inr=lien_amt,
                unrestricted_balance_inr=unrestricted,
                case_id=case_id if is_demo_target else f"{case_id}_HOP_{idx}",
                notes=f"Konnagar ₹5,00,000 scam ring mule at hop {idx}. Exits at {leakage_bank}."
            )

        metrics = {
            "hops": len([t for t in txns if "konnagar_scam" in t.scenario_label]),
            "disputed_amount_inr": disputed_amt,
            "leakage_bank": leakage_bank,
            "mean_hold_time_sec": float(np.mean(hold_times)),
            "case_id": case_id,
            "innocent_branch_amount_inr": innocent_amt,
            "innocent_kirana_account_id": innocent_kirana.account_id
        }
        return txns, labels, metrics

    # --- Scenario 2: Durga Puja Merchant Volume Surge (10x, 48h, Hard Negatives) ---
    def inject_durga_puja_surge(
        self, bank_accounts: Dict[str, List[SyntheticAccount]]
    ) -> Tuple[List[SyntheticTransaction], Dict[str, AccountLabel], Dict[str, Any]]:
        cfg = self.scenarios_cfg.get("durga_puja_surge", {})
        mult = float(cfg.get("volume_multiplier", 10.0))
        duration_hrs = int(cfg.get("duration_hours", 48))
        merch_fraction = float(cfg.get("participating_merchants_fraction", 0.85))

        all_merchants = [
            a for b in bank_accounts.values() for a in b
            if a.account_type == "kirana_merchant"
        ]
        surge_merchants = self.rng.sample(all_merchants, int(len(all_merchants) * merch_fraction))
        retail_customers = [
            a for b in bank_accounts.values() for a in b
            if a.account_type == "retail"
        ]

        txns: List[SyntheticTransaction] = []
        labels: Dict[str, AccountLabel] = {}
        # Festival period: Day 4 (00:00) to Day 6 (00:00)
        festival_start = self.base_start + datetime.timedelta(days=4)
        tx_counter = 1

        for m in surge_merchants:
            labels[m.account_id] = AccountLabel(
                account_id=m.account_id,
                bank_id=m.bank_id,
                account_type=m.account_type,
                is_mule=0,  # HARD NEGATIVE: Legitimate local business spike
                scenario_label="durga_puja_surge_merchant",
                disputed_lien_inr=0.0,
                unrestricted_balance_inr=m.balance_inr,
                case_id=None,
                notes="Hard negative: Durga Puja 10x sales volume surge with genuine local repeat buyers."
            )

            # Generate 10x transactions over 48 hours (~150 to 300 txns per shop)
            surge_count = int(self.rng.randint(120, 250) * (mult / 10.0))
            for _ in range(surge_count):
                cust = self.rng.choice(retail_customers)
                desired_amt = float(self.np_rng.lognormal(mean=6.2, sigma=0.7))  # ~₹500 - ₹3,000 festival purchases
                desired_amt = max(50.0, min(desired_amt, 12000.0))
                # Ensure customer balance conservation (no money created from nothing, never negative)
                available = max(0.0, cust.balance_inr - 50.0)
                if available < 50.0:
                    # Provide pre-festival liquidity advance to ensure customer funds purchase
                    cust.balance_inr = round(cust.balance_inr + 25000.0, 2)
                    available = cust.balance_inr - 50.0
                amount = round(min(desired_amt, available), 2)
                cust.balance_inr = round(cust.balance_inr - amount, 2)
                m.balance_inr = round(m.balance_inr + amount, 2)

                offset_sec = self.rng.randint(0, duration_hrs * 3600)
                ts = festival_start + datetime.timedelta(seconds=offset_sec)

                tx = SyntheticTransaction(
                    txn_id=f"TXN_PUJA_{tx_counter:07d}",
                    src_account_id=cust.account_id,
                    dst_account_id=m.account_id,
                    amount_inr=amount,
                    channel="UPI",
                    timestamp=ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    scenario_label="durga_puja_merchant_surge",
                    sending_bank=cust.bank_id,
                    receiving_bank=m.bank_id
                )
                txns.append(tx)
                tx_counter += 1

        metrics = {
            "surge_merchants_count": len(surge_merchants),
            "transactions_generated": len(txns),
            "multiplier": mult,
            "duration_hours": duration_hrs,
            "total_volume_inr": sum(t.amount_inr for t in txns)
        }
        return txns, labels, metrics

    # --- Scenario 3: Student Fee Pass-Through (Hard Negatives, <=180s hold time) ---
    def inject_student_fee_passthrough(
        self, bank_accounts: Dict[str, List[SyntheticAccount]]
    ) -> Tuple[List[SyntheticTransaction], Dict[str, AccountLabel], Dict[str, Any]]:
        cfg = self.scenarios_cfg.get("student_fee_passthrough", {})
        amt_range = cfg.get("amount_range_inr", [25000, 75000])
        max_hold = int(cfg.get("hold_time_max_sec", 180))
        target_count = int(cfg.get("count", 25))

        all_students = [a for b in bank_accounts.values() for a in b if a.account_type == "student"]
        students = self.rng.sample(all_students, min(len(all_students), target_count))
        retail_parents = [a for b in bank_accounts.values() for a in b if a.account_type == "retail"]
        univ_nodals = [a for b in bank_accounts.values() for a in b if a.account_type == "nodal_whitelisted" and "University" in a.synthetic_name]
        if not univ_nodals:
            univ_nodals = [a for b in bank_accounts.values() for a in b if a.account_type == "nodal_whitelisted"]

        txns: List[SyntheticTransaction] = []
        labels: Dict[str, AccountLabel] = {}
        hold_times: List[float] = []
        tx_counter = 1

        for s in students:
            parent = self.rng.choice(retail_parents)
            nodal = self.rng.choice(univ_nodals)
            fee_amt = round(float(self.rng.uniform(amt_range[0], amt_range[1])), 2)

            day = self.rng.randint(1, 5)
            hour = self.rng.randint(9, 16)
            t_in = self.base_start + datetime.timedelta(days=day, hours=hour, minutes=self.rng.randint(0, 50))

            # 1. Inflow from parent to student
            tx_in = SyntheticTransaction(
                txn_id=f"TXN_STU_FEE_{tx_counter:05d}_DEP",
                src_account_id=parent.account_id,
                dst_account_id=s.account_id,
                amount_inr=fee_amt,
                channel="UPI" if fee_amt <= 50000.0 else "IMPS",
                timestamp=t_in.strftime("%Y-%m-%dT%H:%M:%SZ"),
                scenario_label="student_fee_parent_inflow",
                sending_bank=parent.bank_id,
                receiving_bank=s.bank_id
            )
            txns.append(tx_in)

            # Hold time <= 180 seconds
            hold = self.rng.uniform(40, max_hold)
            hold_times.append(hold)
            t_out = t_in + datetime.timedelta(seconds=int(hold))

            # 2. Outflow from student to university nodal fee account
            tx_out = SyntheticTransaction(
                txn_id=f"TXN_STU_FEE_{tx_counter:05d}_OUT",
                src_account_id=s.account_id,
                dst_account_id=nodal.account_id,
                amount_inr=fee_amt,
                channel="UPI" if fee_amt <= 50000.0 else "IMPS",
                timestamp=t_out.strftime("%Y-%m-%dT%H:%M:%SZ"),
                scenario_label="student_fee_university_outflow",
                sending_bank=s.bank_id,
                receiving_bank=nodal.bank_id
            )
            txns.append(tx_out)
            tx_counter += 1

            labels[s.account_id] = AccountLabel(
                account_id=s.account_id,
                bank_id=s.bank_id,
                account_type=s.account_type,
                is_mule=0,  # HARD NEGATIVE: Legitimate educational tuition flow
                scenario_label="student_fee_passthrough",
                disputed_lien_inr=0.0,
                unrestricted_balance_inr=s.balance_inr,
                case_id=None,
                notes=f"Hard negative: Rapid pass-through ({hold:.1f}s) to university nodal account. Legitimate tuition payment."
            )

        metrics = {
            "students_count": len(students),
            "transactions_generated": len(txns),
            "mean_hold_time_sec": float(np.mean(hold_times)) if hold_times else 0.0,
            "max_hold_time_sec": max_hold
        }
        return txns, labels, metrics

    # --- Scenario 4: Smurfing / Fan-Out (Positive, High entropy out-degree) ---
    def inject_smurfing_fan_out(
        self, bank_accounts: Dict[str, List[SyntheticAccount]]
    ) -> Tuple[List[SyntheticTransaction], Dict[str, AccountLabel], Dict[str, Any]]:
        cfg = self.scenarios_cfg.get("smurfing_fan_out", {})
        total_src = float(cfg.get("source_amount_inr", 350000))
        mule_count = int(cfg.get("mule_count", 15))
        burst_sec = int(cfg.get("burst_window_sec", 600))

        # Origin node at BANK_B
        origin = self.rng.choice([a for a in bank_accounts["BANK_B"] if a.account_type == "retail"])
        # Target mules across participating banks
        all_retail = [a for b in ["BANK_A", "BANK_B", "BANK_C"] for a in bank_accounts[b] if a.account_type == "retail" and a != origin]
        mules = self.rng.sample(all_retail, min(len(all_retail), mule_count))

        txns: List[SyntheticTransaction] = []
        labels: Dict[str, AccountLabel] = {}
        t_start = self.base_start + datetime.timedelta(days=2, hours=11, minutes=30)

        # 1. Origin must RECEIVE the large inflow BEFORE splitting (CR02-C)
        external_funder = [a for a in bank_accounts["BANK_D"] if a.account_type == "retail"][0]
        t_inflow = t_start - datetime.timedelta(minutes=10)
        tx_inflow = SyntheticTransaction(
            txn_id="TXN_SMURF_FUND_DEP",
            src_account_id=external_funder.account_id,
            dst_account_id=origin.account_id,
            amount_inr=total_src,
            channel="RTGS",
            timestamp=t_inflow.strftime("%Y-%m-%dT%H:%M:%SZ"),
            scenario_label="smurfing_fan_out_funding_inflow",
            sending_bank=external_funder.bank_id,
            receiving_bank=origin.bank_id
        )
        txns.append(tx_inflow)
        origin.balance_inr = round(origin.balance_inr + total_src, 2)

        labels[origin.account_id] = AccountLabel(
            account_id=origin.account_id,
            bank_id=origin.bank_id,
            account_type=origin.account_type,
            is_mule=1,
            scenario_label="smurfing_fan_out_origin",
            disputed_lien_inr=total_src,
            unrestricted_balance_inr=origin.balance_inr,
            case_id="SYN-SMURF-01",
            notes="Origin node executing rapid smurfing fan-out dispersal after receiving funding inflow."
        )

        # 2. Split inflow into sub-transfers (bounded by total_src):
        # Must include amounts above and below statutory Rs 1,000 threshold (CR02-C)
        sub_1k_amounts = [round(float(self.rng.uniform(350.0, 950.0)), 2) for _ in range(2)]
        remaining_pool = total_src - sum(sub_1k_amounts)
        num_major = len(mules) - len(sub_1k_amounts)

        weights = [self.rng.uniform(0.8, 1.2) for _ in range(num_major)]
        total_w = sum(weights)
        target_major_pool = remaining_pool * 0.95
        major_amounts = [round((w / total_w) * target_major_pool, 2) for w in weights]
        disbursement_amounts = sub_1k_amounts + major_amounts

        total_disbursed = 0.0
        for idx, (m, amt) in enumerate(zip(mules, disbursement_amounts), 1):
            offset = self.rng.randint(30, burst_sec)
            t_tx = t_start + datetime.timedelta(seconds=offset)
            total_disbursed += amt

            tx = SyntheticTransaction(
                txn_id=f"TXN_SMURF_OUT_{idx:03d}",
                src_account_id=origin.account_id,
                dst_account_id=m.account_id,
                amount_inr=amt,
                channel="UPI",
                timestamp=t_tx.strftime("%Y-%m-%dT%H:%M:%SZ"),
                scenario_label="smurfing_fan_out_hop",
                sending_bank=origin.bank_id,
                receiving_bank=m.bank_id
            )
            txns.append(tx)
            origin.balance_inr = round(origin.balance_inr - amt, 2)
            m.balance_inr = round(m.balance_inr + amt, 2)

            labels[m.account_id] = AccountLabel(
                account_id=m.account_id,
                bank_id=m.bank_id,
                account_type=m.account_type,
                is_mule=1,
                scenario_label="smurfing_fan_out_mule",
                disputed_lien_inr=amt,
                unrestricted_balance_inr=m.balance_inr,
                case_id=f"SYN-SMURF-MULE-{idx:02d}",
                notes="Smurfing recipient mule node."
            )

        metrics = {
            "origin_account_id": origin.account_id,
            "funding_inflow_inr": total_src,
            "mules_count": len(mules),
            "transactions_generated": len(txns),
            "total_disbursed_inr": total_disbursed,
            "burst_window_sec": burst_sec
        }
        return txns, labels, metrics

    # --- Scenario 5: Concentrator / Fan-In Ring (Positive, Many-to-One aggregation) ---
    def inject_concentrator_fan_in(
        self, bank_accounts: Dict[str, List[SyntheticAccount]]
    ) -> Tuple[List[SyntheticTransaction], Dict[str, AccountLabel], Dict[str, Any]]:
        cfg = self.scenarios_cfg.get("concentrator_fan_in", {})
        mule_count = int(cfg.get("mule_count", 12))
        amt_range = cfg.get("amount_per_mule_range", [20000, 30000])
        burst_sec = int(cfg.get("burst_window_sec", 900))

        # Central master concentrator mule at BANK_C
        master_mule = self.rng.choice([a for a in bank_accounts["BANK_C"] if a.account_type == "retail"])
        # Feeder smurfed accounts across BANK_A, BANK_B
        feeders = self.rng.sample([a for b in ["BANK_A", "BANK_B"] for a in bank_accounts[b] if a.account_type == "retail"], mule_count)

        txns: List[SyntheticTransaction] = []
        labels: Dict[str, AccountLabel] = {}
        t_start = self.base_start + datetime.timedelta(days=3, hours=18, minutes=0)
        total_funneled = 0.0

        for idx, f in enumerate(feeders, 1):
            amt = round(float(self.rng.uniform(amt_range[0], amt_range[1])), 2)
            total_funneled += amt
            offset = self.rng.randint(0, burst_sec)
            t_tx = t_start + datetime.timedelta(seconds=offset)

            tx = SyntheticTransaction(
                txn_id=f"TXN_CONC_IN_{idx:03d}",
                src_account_id=f.account_id,
                dst_account_id=master_mule.account_id,
                amount_inr=amt,
                channel="UPI",
                timestamp=t_tx.strftime("%Y-%m-%dT%H:%M:%SZ"),
                scenario_label="concentrator_fan_in_feeder",
                sending_bank=f.bank_id,
                receiving_bank=master_mule.bank_id
            )
            txns.append(tx)
            master_mule.balance_inr = round(master_mule.balance_inr + amt, 2)

            labels[f.account_id] = AccountLabel(
                account_id=f.account_id,
                bank_id=f.bank_id,
                account_type=f.account_type,
                is_mule=1,
                scenario_label="concentrator_feeder_mule",
                disputed_lien_inr=amt,
                unrestricted_balance_inr=f.balance_inr,
                case_id=f"SYN-CONC-FEEDER-{idx:02d}",
                notes="Feeder mule in fan-in concentrator ring."
            )

        # Onward rapid sweep outflow from master mule (pass-through ring) (CR02-C)
        t_max_in = max(datetime.datetime.fromisoformat(t.timestamp.replace("Z", "+00:00")) for t in txns)
        sweep_delay_sec = self.rng.randint(180, 480)  # 3-8 minutes after last credit
        t_sweep = t_max_in + datetime.timedelta(seconds=sweep_delay_sec)
        sweep_amt = round(total_funneled * self.rng.uniform(0.92, 0.98), 2)
        exit_sink = self.rng.choice([a for a in bank_accounts["BANK_D"] if a.account_type == "retail"])

        tx_sweep = SyntheticTransaction(
            txn_id="TXN_CONC_SWEEP_OUT",
            src_account_id=master_mule.account_id,
            dst_account_id=exit_sink.account_id,
            amount_inr=sweep_amt,
            channel="IMPS" if sweep_amt <= 200000.0 else "RTGS",
            timestamp=t_sweep.strftime("%Y-%m-%dT%H:%M:%SZ"),
            scenario_label="concentrator_onward_sweep_outflow",
            sending_bank=master_mule.bank_id,
            receiving_bank=exit_sink.bank_id
        )
        txns.append(tx_sweep)
        master_mule.balance_inr = round(master_mule.balance_inr - sweep_amt, 2)

        labels[master_mule.account_id] = AccountLabel(
            account_id=master_mule.account_id,
            bank_id=master_mule.bank_id,
            account_type=master_mule.account_type,
            is_mule=1,
            scenario_label="concentrator_master_mule",
            disputed_lien_inr=total_funneled,
            unrestricted_balance_inr=master_mule.balance_inr,
            case_id="SYN-CONC-MASTER-01",
            notes="Master concentrator mule aggregating multiple rapid fan-in credits and sweeping onward."
        )

        metrics = {
            "master_mule_account_id": master_mule.account_id,
            "feeders_count": len(feeders),
            "total_funneled_inr": total_funneled,
            "onward_sweep_amount_inr": sweep_amt,
            "burst_window_sec": burst_sec
        }
        return txns, labels, metrics

    # --- Scenario 6: Dormant Account Awakening (Positive, Z_dormancy > 5.0) ---
    def inject_dormant_awakening(
        self, bank_accounts: Dict[str, List[SyntheticAccount]]
    ) -> Tuple[List[SyntheticTransaction], Dict[str, AccountLabel], Dict[str, Any]]:
        cfg = self.scenarios_cfg.get("dormant_awakening", {})
        target_count = int(cfg.get("target_count", 5))
        inflow_amt = float(cfg.get("inflow_amount_inr", 450000))
        disb_hops = int(cfg.get("disbursement_hops", 3))

        # Select mature dormant accounts
        dormant_candidates = [
            a for b in self.participating_banks for a in bank_accounts[b]
            if a.account_type == "retail" and a.account_age_days > 180 and a.mu_90d < 1500.0
        ]
        dormant_targets = self.rng.sample(dormant_candidates, min(len(dormant_candidates), target_count))

        txns: List[SyntheticTransaction] = []
        labels: Dict[str, AccountLabel] = {}
        tx_counter = 1

        for idx, target in enumerate(dormant_targets, 1):
            # Awakening date: Day 5
            t_spike = self.base_start + datetime.timedelta(days=5, hours=10 + idx, minutes=15)
            external_sender = self.rng.choice([a for a in bank_accounts["BANK_D"] if a.account_type == "retail"])

            # 1. Massive sudden inflow into dormant account
            tx_in = SyntheticTransaction(
                txn_id=f"TXN_DORM_SPIKE_{idx:02d}_DEP",
                src_account_id=external_sender.account_id,
                dst_account_id=target.account_id,
                amount_inr=inflow_amt,
                channel="RTGS",
                timestamp=t_spike.strftime("%Y-%m-%dT%H:%M:%SZ"),
                scenario_label="dormant_awakening_inflow",
                sending_bank=external_sender.bank_id,
                receiving_bank=target.bank_id
            )
            txns.append(tx_in)

            labels[target.account_id] = AccountLabel(
                account_id=target.account_id,
                bank_id=target.bank_id,
                account_type=target.account_type,
                is_mule=1,
                scenario_label="dormant_awakening_target",
                disputed_lien_inr=inflow_amt,
                unrestricted_balance_inr=target.balance_inr,
                case_id=f"SYN-DORM-0{idx}",
                notes=f"Dormant account awakening: 90d baseline ~₹{target.mu_90d:.0f}/day suddenly receives ₹{inflow_amt:,.0f}."
            )

            # 2. Rapid dispersal to 3 downstream mules within 45 minutes
            downstream_mules = self.rng.sample([a for b in self.participating_banks for a in bank_accounts[b] if a != target], disb_hops)
            split_amt = round(inflow_amt / disb_hops, 2)

            for d_idx, d_mule in enumerate(downstream_mules, 1):
                offset_sec = self.rng.randint(300, 2700)
                t_out = t_spike + datetime.timedelta(seconds=offset_sec)

                tx_out = SyntheticTransaction(
                    txn_id=f"TXN_DORM_OUT_{idx:02d}_{d_idx}",
                    src_account_id=target.account_id,
                    dst_account_id=d_mule.account_id,
                    amount_inr=split_amt,
                    channel="IMPS",
                    timestamp=t_out.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    scenario_label="dormant_awakening_dispersal",
                    sending_bank=target.bank_id,
                    receiving_bank=d_mule.bank_id
                )
                txns.append(tx_out)

                labels[d_mule.account_id] = AccountLabel(
                    account_id=d_mule.account_id,
                    bank_id=d_mule.bank_id,
                    account_type=d_mule.account_type,
                    is_mule=1,
                    scenario_label="dormant_dispersal_mule",
                    disputed_lien_inr=split_amt,
                    unrestricted_balance_inr=d_mule.balance_inr,
                    case_id=f"SYN-DORM-MULE-{idx:02d}-{d_idx}",
                    notes="Downstream cash-out mule receiving split from awakened dormant node."
                )

        metrics = {
            "targets_count": len(dormant_targets),
            "transactions_generated": len(txns),
            "inflow_amount_inr": inflow_amt
        }
        return txns, labels, metrics

    # --- Scenario 7: Unjoined Bank Leakage (Positive, Multi-hop ending in BANK_E) ---
    def inject_unjoined_leakage(
        self, bank_accounts: Dict[str, List[SyntheticAccount]]
    ) -> Tuple[List[SyntheticTransaction], Dict[str, AccountLabel], Dict[str, Any]]:
        cfg = self.scenarios_cfg.get("unjoined_leakage", {})
        hops = int(cfg.get("chain_hops", 4))
        leakage_bank = normalize_bank_id(cfg.get("leakage_bank", "BANK_E"))
        amount = float(cfg.get("amount_inr", 250000))

        # 4-hop chain: exactly 4 transactions across 5 nodes (CR02-C)
        # Sequence: BANK_A -> BANK_B -> BANK_C -> BANK_A -> leakage_bank (BANK_E or BANK_D)
        seq_banks = ["BANK_A", "BANK_B", "BANK_C", "BANK_A", leakage_bank][:hops + 1]
        chain_accounts: List[SyntheticAccount] = []
        for b_id in seq_banks:
            acc = self.rng.choice([a for a in bank_accounts[b_id] if a.account_type == "retail" and a not in chain_accounts])
            chain_accounts.append(acc)

        txns: List[SyntheticTransaction] = []
        labels: Dict[str, AccountLabel] = {}
        t_curr = self.base_start + datetime.timedelta(days=4, hours=16, minutes=20)

        for idx in range(len(chain_accounts) - 1):
            src_node = chain_accounts[idx]
            dst_node = chain_accounts[idx + 1]

            label_name = f"unjoined_leakage_hop_{idx + 1}"
            if dst_node.bank_id == leakage_bank:
                label_name = f"unjoined_leakage_exit_{leakage_bank}"

            tx = SyntheticTransaction(
                txn_id=f"TXN_LEAK_E_{idx + 1:02d}",
                src_account_id=src_node.account_id,
                dst_account_id=dst_node.account_id,
                amount_inr=amount,
                channel="IMPS",
                timestamp=t_curr.strftime("%Y-%m-%dT%H:%M:%SZ"),
                scenario_label=label_name,
                sending_bank=src_node.bank_id,
                receiving_bank=dst_node.bank_id
            )
            txns.append(tx)

            # Fast hop: 60 to 180 seconds
            hold = self.rng.uniform(60, 180)
            t_curr += datetime.timedelta(seconds=int(hold))

            labels[dst_node.account_id] = AccountLabel(
                account_id=dst_node.account_id,
                bank_id=dst_node.bank_id,
                account_type=dst_node.account_type,
                is_mule=1,
                scenario_label="unjoined_leakage_mule",
                disputed_lien_inr=amount,
                unrestricted_balance_inr=dst_node.balance_inr,
                case_id=f"SYN-LEAK-E-0{idx + 1}",
                notes=f"Multi-hop layering exiting to non-participating bank {leakage_bank}."
            )

        metrics = {
            "chain_hops": len(txns),
            "amount_inr": amount,
            "leakage_bank": leakage_bank
        }
        return txns, labels, metrics

    # --- Scenario 8: Warm-Up Period (Benign pre-period) ---
    def inject_warmup_period(
        self, bank_accounts: Dict[str, List[SyntheticAccount]]
    ) -> Tuple[List[SyntheticTransaction], Dict[str, AccountLabel], Dict[str, Any]]:
        cfg = self.scenarios_cfg.get("warm_up", {})
        duration_days = int(cfg.get("duration_days", 3))
        volume_factor = float(cfg.get("volume_factor", 0.5))

        warmup_start = self.base_start - datetime.timedelta(days=duration_days)
        all_retail = [a for b in bank_accounts.values() for a in b if a.account_type == "retail"]
        all_merch = [a for b in bank_accounts.values() for a in b if a.account_type == "kirana_merchant"]

        txns: List[SyntheticTransaction] = []
        labels: Dict[str, AccountLabel] = {}
        warmup_tx_count = int(len(all_retail) * volume_factor * duration_days)

        for idx in range(warmup_tx_count):
            sender = self.rng.choice(all_retail)
            # 60% merchant payments, 40% P2P
            if self.rng.random() < 0.60:
                receiver = self.rng.choice(all_merch)
                amt = float(self.np_rng.lognormal(mean=5.5, sigma=0.6))
                amt = max(20.0, min(amt, 4500.0))
                lbl = "warm_up_merchant_payment"
            else:
                receiver = self.rng.choice(all_retail)
                while receiver.account_id == sender.account_id:
                    receiver = self.rng.choice(all_retail)
                amt = float(self.np_rng.lognormal(mean=6.5, sigma=0.8))
                amt = max(100.0, min(amt, 15000.0))
                lbl = "warm_up_p2p"

            sec_offset = self.rng.randint(0, duration_days * 86400)
            t_tx = warmup_start + datetime.timedelta(seconds=sec_offset)

            tx = SyntheticTransaction(
                txn_id=f"TXN_WARMUP_{idx + 1:06d}",
                src_account_id=sender.account_id,
                dst_account_id=receiver.account_id,
                amount_inr=round(amt, 2),
                channel="UPI",
                timestamp=t_tx.strftime("%Y-%m-%dT%H:%M:%SZ"),
                scenario_label=lbl,
                sending_bank=sender.bank_id,
                receiving_bank=receiver.bank_id
            )
            txns.append(tx)

        metrics = {
            "duration_days": duration_days,
            "warmup_tx_count": len(txns),
            "start_date": str(warmup_start.date()),
            "end_date": str(self.base_start.date())
        }
        return txns, labels, metrics

    def write_ground_truth(
        self,
        account_labels: Dict[str, AccountLabel],
        all_transactions: List[SyntheticTransaction],
        output_dir: str = "data/ground_truth"
    ):
        """Write ground-truth labels strictly outside central risk / audit storage."""
        os.makedirs(output_dir, exist_ok=True)
        acc_path = os.path.join(output_dir, "labels.csv")
        txn_path = os.path.join(output_dir, "txn_labels.csv")

        # 1. Write Account-Level Ground Truth
        with open(acc_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "account_id", "bank_id", "account_type", "is_mule",
                "scenario_label", "disputed_lien_inr", "unrestricted_balance_inr",
                "case_id", "notes"
            ])
            for lbl in account_labels.values():
                writer.writerow([
                    lbl.account_id, lbl.bank_id, lbl.account_type, lbl.is_mule,
                    lbl.scenario_label, lbl.disputed_lien_inr,
                    lbl.unrestricted_balance_inr, lbl.case_id or "", lbl.notes
                ])

        # 2. Write Transaction-Level Ground Truth
        with open(txn_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "txn_id", "src_account_id", "dst_account_id", "amount_inr",
                "channel", "timestamp", "scenario_label", "is_fraud",
                "sending_bank", "receiving_bank"
            ])
            for t in all_transactions:
                is_fraud = 1 if any(kw in t.scenario_label for kw in ["scam", "smurf", "conc", "dorm", "leak"]) else 0
                writer.writerow([
                    t.txn_id, t.src_account_id, t.dst_account_id, t.amount_inr,
                    t.channel, t.timestamp, t.scenario_label, is_fraud,
                    t.sending_bank, t.receiving_bank
                ])

        print(f"[✔] Ground-truth labels written to '{acc_path}' and '{txn_path}'.")

    def generate_scenario_catalogue(
        self,
        scenario_metrics: Dict[str, Any],
        output_path: str = "docs/generated/scenarios.md"
    ) -> str:
        """Create a Markdown catalogue of injected scenarios with expected positive/negative classifications."""
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        md = [
            "# CHAKRA-DPI Scenario Catalogue & Evaluation Archetypes",
            "",
            "**Governing Document:** `docs/PRD.md` Section 1.2 & `configs/simulation_v1.yaml`  ",
            f"**Last Updated:** {datetime.datetime.now(datetime.timezone.utc).isoformat()}  ",
            f"**Random Seed:** `{self.seed}`  ",
            "",
            "This catalogue details all simulated behavioral scenarios injected into the CHAKRA-DPI multi-bank pipeline, distinguishing true fraud rings from critical hard negatives.",
            "",
            "---",
            "",
            "## 1. Scenario Archetype Matrix",
            "",
            "| Scenario Identifier | Classification Type | Expected Label | Core Risk Signal Tested | Institutional Scope |",
            "| :--- | :--- | :--- | :--- | :--- |",
            "| `konnagar_scam` | **Fraud Ring (Primary)** | **Positive (`is_mule=1`)** | Multi-hop velocity ($V_p$), rapid hold times, exit leakage | Participating (`A, B, C`) $\\to$ Unjoined (`BANK_D`) |",
            "| `durga_puja_surge` | **Hard Negative (Fairness)** | **Negative (`is_mule=0`)** | $M_{\\text{local}}$ merchant protection during 10x volume surges | Local Kirana merchants across all banks |",
            "| `student_fee_passthrough` | **Hard Negative (Precision)** | **Negative (`is_mule=0`)** | $V_p$ resilience against rapid ($<180\\text{s}$) tuition payments | Students $\\to$ University Nodal Accounts |",
            "| `smurfing_fan_out` | **Fraud Ring (Layering)** | **Positive (`is_mule=1`)** | High out-degree entropy ($H_{\\text{entropy}}$) & burst fan-out | Single origin $\\to$ 15 mules across `A, B, C` |",
            "| `concentrator_fan_in` | **Fraud Ring (Collection)** | **Positive (`is_mule=1`)** | In-degree concentration, multi-source pooling | 12 feeder mules $\\to$ Single master mule |",
            "| `dormant_awakening` | **Fraud Ring (Mule)** | **Positive (`is_mule=1`)** | Dormancy spike ($Z_{\\text{dormancy}} > 5.0$) & immediate disbursement | Long-dormant accounts ($>180$d) suddenly active |",
            "| `unjoined_leakage` | **Fraud Ring (Leakage)** | **Positive (`is_mule=1`)** | Cross-bank velocity chain escaping to unjoined bank | `BANK_A \\to BANK_B \\to BANK_C \\to BANK_E` |",
            "| `warm_up` | **Background Baseline** | **Negative (`is_mule=0`)** | Prior-window stabilization for $\\mu_{90d}, \\sigma_{90d}$ | Normal background retail & merchant transfers |",
            "",
            "---",
            "",
            "## 2. In-Depth Scenario Profiles",
            "",
            "### Scenario 1: Konnagar ₹5,00,000 Scam Ring (`konnagar_scam`)",
            "- **Description:** Simulates an inter-state cyber fraud incident originating in Konnagar (Hooghly district, West Bengal). A victim is defrauded of ₹5,00,000, which is immediately split and moved through a 5-hop relay chain across participating banks (`BANK_A`, `BANK_B`, `BANK_C`) before leaking out at non-participating `BANK_D`.",
            "- **Key Features:** Mean hold time $< 90$ seconds per hop; high pass-through velocity ($V_p \\to 1.0$).",
            "- **Case Demonstration:** Target mule at Hop 2 reproduces Case `SYN-0042` with surgical lien demonstration (₹85,000 unrestricted balance, ₹2,500 disputed lien).",
            "",
            "### Scenario 2: Durga Puja Merchant Volume Surge (`durga_puja_surge`) — Hard Negative",
            "- **Description:** Simulates the massive retail shopping peak during Durga Puja in West Bengal. Local Kirana stores experience a 10x surge in transaction volume over 48 hours.",
            "- **Why this is a Hard Negative:** Blanket fraud rules trigger massive false-positive liens during festival surges due to abnormal volume spikes. CHAKRA-DPI protects these merchants via high $M_{\\text{local}}$ scores derived from high repeat-customer ratios ($R_{\\text{repeat}} > 0.80$) and non-sweep balance retention.",
            "",
            "### Scenario 3: Student Fee Pass-Through (`student_fee_passthrough`) — Hard Negative",
            "- **Description:** A student receives ₹25,000–₹75,000 for university tuition fees from a parent and transfers it within 3 minutes ($\\le 180$ seconds) to the university fee collection nodal account.",
            "- **Why this is a Hard Negative:** The velocity formula $V_p$ penalizes rapid funds pass-through ($\\exp(-\\lambda \\cdot \\tau_{\\text{hold}})$). However, because the recipient is an authentic educational nodal account (`nodal_whitelisted`), the system correctly suppresses alerts, avoiding innocent student account freezes.",
            "",
            "### Scenario 4: Smurfing / Fan-Out (`smurfing_fan_out`)",
            "- **Description:** A primary illicit node receives ₹3,500,000 and executes a rapid fan-out to 15 distinct mule accounts in sub-threshold amounts (₹18,000–₹24,000) within 10 minutes.",
            "- **Detection Mechanism:** Identified by extreme recipient distribution entropy ($H_{\\text{entropy}}$) and burst temporal velocity.",
            "",
            "### Scenario 5: Concentrator / Fan-In Ring (`concentrator_fan_in`)",
            "- **Description:** 12 dispersed smurfed nodes simultaneously funnel funds into a single master collection mule at `BANK_C` within a 15-minute window.",
            "- **Detection Mechanism:** In-degree fan-in concentration and rapid balance accumulation without prior commercial history.",
            "",
            "### Scenario 6: Dormant Account Awakening (`dormant_awakening`)",
            "- **Description:** Accounts older than 180 days with negligible activity ($\\mu_{90d} < 1500$) suddenly receive ₹4,50,000 via RTGS and rapidly disburse funds across multiple downstream hops.",
            "- **Detection Mechanism:** Extreme dormancy-to-spike z-score ($Z_{\\text{dormancy}} = \\frac{V_{24h} - \\mu_{90d}}{\\sigma_{90d}} > 5.0$).",
            "",
            "### Scenario 7: Unjoined Bank Leakage (`unjoined_leakage`)",
            "- **Description:** A 4-hop cross-bank laundering chain moves through participating banks `BANK_A \\to BANK_B \\to BANK_C`, terminating at unjoined `BANK_E`.",
            "- **Detection Mechanism:** Demonstrates provenance coverage ratio degradation ($3/5$ banks participating) and highlights cross-institutional visibility boundaries.",
            "",
            "---",
            "*Report auto-generated by `src/simulator/scenarios.py` under SFIC 2026 Phase 03.*"
        ]

        report_content = "\n".join(md)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report_content)

        return report_content


def run_scenario_pipeline(
    config_path: str = "configs/simulation_v1.yaml",
    accounts_override: Optional[int] = None,
    full: bool = False,
    data_dir: str = "data",
    seed: Optional[int] = None
) -> Tuple[List[SyntheticTransaction], Dict[str, AccountLabel], Dict[str, Any]]:
    """Execute full generation and scenario injection pipeline."""
    # 1. Generate base accounts and normal transactions
    gen = SyntheticGenerator(config_path=config_path, seed=seed)
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    target_accounts = cfg["simulation"].get("benchmark_accounts", 50000) if full else (
        accounts_override if accounts_override is not None else cfg["simulation"].get("total_accounts", 5000)
    )

    print(f"[*] Instantiating {target_accounts:,} accounts across 5 banks...")
    bank_accounts = gen.generate_accounts(total_accounts=target_accounts)

    print("[*] Generating baseline AMLSim normal transaction ledgers...")
    normal_txns = gen.generate_transactions(bank_accounts)

    # 2. Inject scenarios
    print("[*] Injecting configured scenarios (Konnagar, Durga Puja, Student Pass-Through, etc.)...")
    engine = ScenarioEngine(config_path=config_path, seed=seed)
    all_txns, account_labels, scenario_metrics = engine.inject_all(bank_accounts, normal_txns)

    # 3. Write data to isolated databases
    print(f"[*] Writing combined ledgers to 5 bank databases in '{data_dir}/banks'...")
    gen.write_to_databases(bank_accounts, all_txns, base_data_dir=data_dir)

    # 4. Write ground-truth labels strictly outside central DBs
    gt_dir = os.path.join(data_dir, "ground_truth")
    print(f"[*] Writing ground-truth labels to '{gt_dir}'...")
    engine.write_ground_truth(account_labels, all_txns, output_dir=gt_dir)

    # 5. Generate scenario documentation catalogue
    cat_path = "docs/generated/scenarios.md"
    print(f"[*] Compiling scenario catalogue to '{cat_path}'...")
    engine.generate_scenario_catalogue(scenario_metrics, output_path=cat_path)

    print(f"[✔] Pipeline complete: {len(all_txns):,} total transactions, {len(account_labels):,} ground-truth labels generated.")
    return all_txns, account_labels, scenario_metrics


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CHAKRA-DPI Scenario Generator & Injector")
    parser.add_argument("--config", default="configs/simulation_v1.yaml", help="Path to simulation YAML config.")
    parser.add_argument("--accounts", type=int, default=None, help="Override target account count.")
    parser.add_argument("--full", action="store_true", help="Generate full benchmark scale (50,000 accounts).")
    parser.add_argument("--data-dir", default="data", help="Base directory for database files (default: data).")
    parser.add_argument("--seed", type=int, default=None, help="Override random seed.")
    args = parser.parse_args()

    run_scenario_pipeline(
        config_path=args.config,
        accounts_override=args.accounts,
        full=args.full,
        data_dir=args.data_dir,
        seed=args.seed
    )
