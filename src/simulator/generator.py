#!/usr/bin/env python3
"""CHAKRA-DPI Synthetic Account & Transaction Generator.

Generates realistic IBM AMLSim-style synthetic multi-bank transaction ledgers:
- Multi-bank distribution across participating (BANK_A, B, C) and unjoined (BANK_D, E) banks.
- Account types: retail, kirana_merchant, student, nodal_whitelisted with size tiers.
- Indian synthetic nomenclature (clearly synthetic prefix).
- Realistic transaction dynamics: retail P2P, repeat merchant payments, salary credits,
  student micropayments, and utility bills with lognormal amounts and diurnal seasonality.
- Bank-local physical isolation: writes each bank's data strictly into its own SQLite DB.
- Cross-bank handling without PII leakage.
- Deterministic seeding and summary reporting.
"""

import argparse
import datetime
import json
import math
import os
import random
import sqlite3
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import yaml

# Add root directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from src.common.ids import get_bank_db_path, normalize_bank_id
from src.init_dbs import init_bank_db


# --- Synthetic Name Pools (Eastern Region / West Bengal Context) ---
FIRST_NAMES_MALE = [
    "Rajesh", "Suresh", "Amit", "Rohit", "Vikram", "Rahul", "Manoj",
    "Sanjay", "Aniket", "Subhash", "Debabrata", "Sourav", "Tathagata",
    "Tanmoy", "Abhishek", "Joydeep", "Debanjan", "Anirban", "Bikash", "Prasenjit"
]
FIRST_NAMES_FEMALE = [
    "Priya", "Sunita", "Ananya", "Pooja", "Sneha", "Deepa", "Shreya",
    "Moumita", "Swati", "Payel", "Rupa", "Tumpa", "Ankita", "Sarmistha",
    "Ritu", "Neha", "Debolina", "Tanushree", "Mousumi", "Kakali"
]
LAST_NAMES = [
    "Banerjee", "Chatterjee", "Mukherjee", "Bhattacharya", "Chakraborty",
    "Ghosh", "Bose", "Dutta", "Mitra", "Sen", "Das", "Roy", "Sarkar",
    "Pal", "De", "Mondal", "Kundu", "Bhowmick", "Saha", "Samanta"
]
MERCHANT_SHOP_NAMES = [
    "Maa Tara Stores", "Konnagar Kirana Bhandar", "Ghosh Variety Store",
    "Dutta Departmental Store", "Annapurna Provision Mart", "Sen Stationary",
    "Bhowmick Enterprise", "Paul Grocery", "Maa Manasa Stores", "Roy Super Bazaar",
    "Chakraborty Confectionery", "New Bengal Ration Shop", "Hooghly Corner Mart",
    "Dey Daily Needs", "Nandi Brothers General Store", "Kundu Tea & Spices"
]
NODAL_NAMES = [
    "WB State Electricity Bill Pool", "Greater Kolkata Municipal Water Fund",
    "University Semester Fee Gateway", "District Wholesale Grain Nodal",
    "Apex Milk Cooperative Liquidity Vault", "Kolkata Metro Card Topup Pool"
]


@dataclass
class SyntheticAccount:
    account_id: str
    bank_id: str
    synthetic_name: str
    account_type: str
    merchant_size_tier: Optional[str]
    account_age_days: int
    balance_inr: float
    mu_90d: float
    sigma_90d: float
    m_local_score: float


@dataclass
class SyntheticTransaction:
    txn_id: str
    src_account_id: str
    dst_account_id: str
    amount_inr: float
    channel: str
    timestamp: str
    scenario_label: str
    sending_bank: str
    receiving_bank: str


class SyntheticGenerator:
    """Deterministic generator for synthetic accounts and normal transaction flows."""

    def __init__(self, config_path: str, seed: Optional[int] = None):
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)

        self.seed = seed if seed is not None else self.config.get("seed", 42)
        self.rng = random.Random(self.seed)
        self.np_rng = np.random.default_rng(self.seed)

        sim_cfg = self.config["simulation"]
        self.participating_banks = [normalize_bank_id(b) for b in sim_cfg["participating_banks"]]
        self.unjoined_banks = [normalize_bank_id(b) for b in sim_cfg["unjoined_banks"]]
        self.all_banks = self.participating_banks + self.unjoined_banks
        self.account_distribution = sim_cfg["account_distribution"]
        self.time_horizon_days = sim_cfg.get("time_horizon_days", 7)

        # Baseline start timestamp for 7-day window
        self.start_dt = datetime.datetime(2026, 11, 15, 0, 0, 0, tzinfo=datetime.timezone.utc)

    def generate_name(self, account_type: str) -> str:
        """Generate clearly fake synthetic names with regional realism."""
        if account_type == "kirana_merchant":
            shop = self.rng.choice(MERCHANT_SHOP_NAMES)
            owner_last = self.rng.choice(LAST_NAMES)
            return f"Synth_{shop} ({owner_last})"
        elif account_type == "nodal_whitelisted":
            nodal = self.rng.choice(NODAL_NAMES)
            return f"Synth_{nodal}"
        else:
            first = self.rng.choice(FIRST_NAMES_MALE if self.rng.random() < 0.5 else FIRST_NAMES_FEMALE)
            last = self.rng.choice(LAST_NAMES)
            tag = " (Student)" if account_type == "student" else ""
            return f"Synth_{first}_{last}{tag}"

    def generate_accounts(self, total_accounts: int) -> Dict[str, List[SyntheticAccount]]:
        """Generate synthetic accounts distributed proportionally across banks."""
        accounts_per_bank = total_accounts // len(self.all_banks)
        bank_accounts: Dict[str, List[SyntheticAccount]] = {b: [] for b in self.all_banks}

        acc_counter = 1
        for bank_id in self.all_banks:
            # 1. Ensure each bank has an internal inward clearing nodal account for incoming cross-bank txns
            clearing_acc_id = f"ACC_{bank_id}_NPCI_INWARD"
            clearing_account = SyntheticAccount(
                account_id=clearing_acc_id,
                bank_id=bank_id,
                synthetic_name=f"Synth_NPCI_Inward_Clearing_Gateway_{bank_id}",
                account_type="nodal_whitelisted",
                merchant_size_tier=None,
                account_age_days=1825,
                balance_inr=50000000.0,  # 5 Crore INR initial liquidity
                mu_90d=1500000.0,
                sigma_90d=250000.0,
                m_local_score=0.99
            )
            bank_accounts[bank_id].append(clearing_account)

            # 2. Distribute regular accounts by configured distribution
            types = ["retail", "kirana_merchant", "student", "nodal_whitelisted"]
            probs = [self.account_distribution[t] for t in types]
            chosen_types = self.rng.choices(types, weights=probs, k=accounts_per_bank)

            for acc_type in chosen_types:
                acc_id = f"ACC_{bank_id}_{acc_counter:06d}"
                acc_counter += 1

                # Account Age & Cold-Start (<14 days)
                if acc_type == "student":
                    is_cold = self.rng.random() < 0.12
                    age_days = self.rng.randint(1, 13) if is_cold else self.rng.randint(14, 730)
                elif acc_type == "kirana_merchant":
                    is_cold = self.rng.random() < 0.03
                    age_days = self.rng.randint(1, 13) if is_cold else self.rng.randint(14, 2500)
                elif acc_type == "nodal_whitelisted":
                    is_cold = False
                    age_days = self.rng.randint(365, 3650)
                else:  # retail
                    is_cold = self.rng.random() < 0.06
                    age_days = self.rng.randint(1, 13) if is_cold else self.rng.randint(14, 1825)

                # Balances & Merchant Tiers
                merchant_tier = None
                if acc_type == "kirana_merchant":
                    tier_roll = self.rng.random()
                    if tier_roll < 0.60:
                        merchant_tier = "micro"
                        balance = float(self.np_rng.lognormal(mean=10.2, sigma=0.5))  # ~27k
                    elif tier_roll < 0.90:
                        merchant_tier = "small"
                        balance = float(self.np_rng.lognormal(mean=11.2, sigma=0.4))  # ~73k
                    else:
                        merchant_tier = "medium"
                        balance = float(self.np_rng.lognormal(mean=12.5, sigma=0.4))  # ~270k
                    balance = max(1000.0, min(balance, 2500000.0))
                elif acc_type == "student":
                    balance = float(max(200.0, self.np_rng.lognormal(mean=8.0, sigma=0.6)))  # ~3k
                elif acc_type == "nodal_whitelisted":
                    balance = float(max(500000.0, self.np_rng.lognormal(mean=14.5, sigma=0.5)))  # ~2M
                else:  # retail
                    balance = float(max(500.0, self.np_rng.lognormal(mean=9.5, sigma=0.7)))  # ~13k

                # Compute mu_90d and sigma_90d
                if is_cold:
                    # Cohort defaults
                    if acc_type == "kirana_merchant":
                        mu_90d, sigma_90d = 25000.0, 5000.0
                    elif acc_type == "student":
                        mu_90d, sigma_90d = 800.0, 200.0
                    else:
                        mu_90d, sigma_90d = 4000.0, 1200.0
                else:
                    daily_base = balance * 0.15
                    mu_90d = float(max(100.0, daily_base * self.rng.uniform(0.7, 1.4)))
                    sigma_90d = float(max(20.0, mu_90d * self.rng.uniform(0.2, 0.5)))

                # Compute M_local (Merchant protection score)
                if acc_type == "kirana_merchant":
                    # Established kirana shops have high repeat customer ratio, low sweep, mature age
                    repeat_ratio = self.rng.uniform(0.75, 0.95)
                    non_sweep = self.rng.uniform(0.80, 0.98)
                    age_stability = min(1.0, age_days / 365.0)
                    m_local = 0.4 * repeat_ratio + 0.4 * non_sweep + 0.2 * age_stability
                elif acc_type == "nodal_whitelisted":
                    m_local = 0.95
                else:
                    repeat_ratio = self.rng.uniform(0.10, 0.40)
                    non_sweep = self.rng.uniform(0.30, 0.70)
                    age_stability = min(1.0, age_days / 365.0)
                    m_local = 0.4 * repeat_ratio + 0.4 * non_sweep + 0.2 * age_stability

                account = SyntheticAccount(
                    account_id=acc_id,
                    bank_id=bank_id,
                    synthetic_name=self.generate_name(acc_type),
                    account_type=acc_type,
                    merchant_size_tier=merchant_tier,
                    account_age_days=age_days,
                    balance_inr=round(balance, 2),
                    mu_90d=round(mu_90d, 2),
                    sigma_90d=round(sigma_90d, 2),
                    m_local_score=round(m_local, 4)
                )
                bank_accounts[bank_id].append(account)

        return bank_accounts

    def _sample_timestamp(self) -> datetime.datetime:
        """Sample a realistic timestamp respecting diurnal peak patterns over 7 days."""
        day = self.rng.randint(0, self.time_horizon_days - 1)
        # Bimodal daily activity: morning (9-12) and evening (17-21)
        if self.rng.random() < 0.75:
            if self.rng.random() < 0.45:
                hour = int(self.np_rng.normal(10.5, 1.2))  # Morning peak
            else:
                hour = int(self.np_rng.normal(19.0, 1.5))  # Evening peak
        else:
            hour = self.rng.randint(0, 23)

        hour = max(0, min(23, hour))
        minute = self.rng.randint(0, 59)
        second = self.rng.randint(0, 59)

        return self.start_dt + datetime.timedelta(days=day, hours=hour, minutes=minute, seconds=second)

    def _select_channel(self, amount: float) -> str:
        """Select appropriate payment channel according to transaction size."""
        if amount > 200000.0:
            return "RTGS" if self.rng.random() < 0.85 else "IMPS"
        elif amount > 50000.0:
            return "IMPS" if self.rng.random() < 0.70 else "UPI"
        else:
            return "UPI" if self.rng.random() < 0.90 else "IMPS"

    def _execute_transfer(self, sender: SyntheticAccount, receiver: SyntheticAccount, desired_amount: float) -> float:
        """Ensure balance conservation and that sender balance never drops below zero.

        Deducts amount from sender and adds identical amount to receiver.
        Returns the actual transferred amount (or 0.0 if insufficient funds).
        """
        reserve = 0.0 if sender.account_type == "nodal_whitelisted" else 50.0
        available = max(0.0, sender.balance_inr - reserve)
        if available <= 0.0:
            return 0.0
        amount = min(desired_amount, available)
        amount = round(amount, 2)
        if amount < 1.0:
            return 0.0
        sender.balance_inr = round(sender.balance_inr - amount, 2)
        receiver.balance_inr = round(receiver.balance_inr + amount, 2)
        return amount

    def generate_transactions(
        self, bank_accounts: Dict[str, List[SyntheticAccount]]
    ) -> List[SyntheticTransaction]:
        """Generate normal AMLSim-style cross-bank and intra-bank transaction ledgers."""
        all_accounts = [acc for b_accs in bank_accounts.values() for acc in b_accs]
        retail_accs = [a for a in all_accounts if a.account_type == "retail"]
        merchant_accs = [a for a in all_accounts if a.account_type == "kirana_merchant"]
        student_accs = [a for a in all_accounts if a.account_type == "student"]
        nodal_accs = [a for a in all_accounts if a.account_type == "nodal_whitelisted" and not a.account_id.endswith("_NPCI_INWARD")]

        transactions: List[SyntheticTransaction] = []
        txn_counter = 1

        # 1. Kirana Merchant Customer Payments (High repeat customer ratio)
        # Map each merchant to a dedicated cluster of ~15-30 loyal local customers
        merchant_loyalty: Dict[str, List[SyntheticAccount]] = {}
        for m in merchant_accs:
            # Prefer customers from the same bank, but allow 30% from other banks (local neighborhood)
            local_pool = [r for r in retail_accs if r.bank_id == m.bank_id]
            cross_pool = [r for r in retail_accs if r.bank_id != m.bank_id]
            k_local = min(len(local_pool), self.rng.randint(12, 22))
            k_cross = min(len(cross_pool), self.rng.randint(4, 10))
            loyal_customers = self.rng.sample(local_pool, k_local) + self.rng.sample(cross_pool, k_cross)
            merchant_loyalty[m.account_id] = loyal_customers

        # Generate grocery payments over 7 days
        for m in merchant_accs:
            loyal_custs = merchant_loyalty[m.account_id]
            tx_count = self.rng.randint(15, 35)  # 2 to 5 txns per day
            for _ in range(tx_count):
                sender = self.rng.choice(loyal_custs)
                # Kirana amounts: typical ₹80 - ₹3,500
                desired_amount = float(self.np_rng.lognormal(mean=5.8, sigma=0.8))  # ~330 INR
                desired_amount = max(30.0, min(desired_amount, 9500.0))
                amount = self._execute_transfer(sender, m, desired_amount)
                if amount <= 0.0:
                    continue

                ts = self._sample_timestamp()

                tx = SyntheticTransaction(
                    txn_id=f"TXN_{txn_counter:08d}",
                    src_account_id=sender.account_id,
                    dst_account_id=m.account_id,
                    amount_inr=amount,
                    channel="UPI",
                    timestamp=ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    scenario_label="normal_merchant_payment",
                    sending_bank=sender.bank_id,
                    receiving_bank=m.bank_id
                )
                transactions.append(tx)
                txn_counter += 1

        # 2. Retail P2P Payments (Social / Family Transfers)
        # Average ~2 to 4 P2P transfers per retail user per week
        p2p_count = int(len(retail_accs) * 2.5)
        for _ in range(p2p_count):
            sender = self.rng.choice(retail_accs)
            receiver = self.rng.choice(retail_accs)
            while receiver.account_id == sender.account_id:
                receiver = self.rng.choice(retail_accs)

            # Amount: ₹200 to ₹25,000
            desired_amount = float(self.np_rng.lognormal(mean=7.2, sigma=0.9))  # ~1300 INR
            desired_amount = max(100.0, min(desired_amount, 45000.0))
            amount = self._execute_transfer(sender, receiver, desired_amount)
            if amount <= 0.0:
                continue

            ts = self._sample_timestamp()
            channel = self._select_channel(amount)

            tx = SyntheticTransaction(
                txn_id=f"TXN_{txn_counter:08d}",
                src_account_id=sender.account_id,
                dst_account_id=receiver.account_id,
                amount_inr=amount,
                channel=channel,
                timestamp=ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                scenario_label="normal_retail_p2p",
                sending_bank=sender.bank_id,
                receiving_bank=receiver.bank_id
            )
            transactions.append(tx)
            txn_counter += 1

        # 3. Salary & Inflow Credits (From Nodal / Corporate to Retail)
        if nodal_accs:
            for r in retail_accs:
                # ~40% of retail users receive a salary credit in this 7-day window
                if self.rng.random() < 0.40:
                    employer_nodal = self.rng.choice(nodal_accs)
                    desired_salary = float(self.np_rng.lognormal(mean=10.4, sigma=0.4))  # ~33,000 INR
                    desired_salary = max(15000.0, min(desired_salary, 150000.0))
                    salary_amt = self._execute_transfer(employer_nodal, r, desired_salary)
                    if salary_amt <= 0.0:
                        continue

                    # Payday usually on 1st, 15th, or month end
                    day_offset = self.rng.choice([0, 1, 5, 6])
                    hour = self.rng.randint(6, 11)
                    ts = self.start_dt + datetime.timedelta(days=day_offset, hours=hour, minutes=self.rng.randint(0, 59))

                    tx = SyntheticTransaction(
                        txn_id=f"TXN_{txn_counter:08d}",
                        src_account_id=employer_nodal.account_id,
                        dst_account_id=r.account_id,
                        amount_inr=salary_amt,
                        channel="IMPS" if salary_amt < 100000.0 else "RTGS",
                        timestamp=ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        scenario_label="normal_salary_inflow",
                        sending_bank=employer_nodal.bank_id,
                        receiving_bank=r.bank_id
                    )
                    transactions.append(tx)
                    txn_counter += 1

        # 4. Student Small Transfers & Pocket Money
        for s in student_accs:
            # Pocket money transfer from a retail parent
            parent = self.rng.choice(retail_accs)
            desired_parent_amt = float(self.rng.uniform(1500.0, 7500.0))
            parent_amt = self._execute_transfer(parent, s, desired_parent_amt)
            if parent_amt > 0.0:
                ts_parent = self._sample_timestamp()

                tx_parent = SyntheticTransaction(
                    txn_id=f"TXN_{txn_counter:08d}",
                    src_account_id=parent.account_id,
                    dst_account_id=s.account_id,
                    amount_inr=parent_amt,
                    channel="UPI",
                    timestamp=ts_parent.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    scenario_label="normal_student_allowance",
                    sending_bank=parent.bank_id,
                    receiving_bank=s.bank_id
                )
                transactions.append(tx_parent)
                txn_counter += 1

            # Micro outlays: cafeteria, books, printouts (3 to 8 txns)
            for _ in range(self.rng.randint(3, 8)):
                m_target = self.rng.choice(merchant_accs)
                desired_micro = float(self.rng.uniform(20.0, 450.0))
                micro_amt = self._execute_transfer(s, m_target, desired_micro)
                if micro_amt <= 0.0:
                    continue

                ts_micro = self._sample_timestamp()

                tx_micro = SyntheticTransaction(
                    txn_id=f"TXN_{txn_counter:08d}",
                    src_account_id=s.account_id,
                    dst_account_id=m_target.account_id,
                    amount_inr=micro_amt,
                    channel="UPI",
                    timestamp=ts_micro.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    scenario_label="normal_student_transfer",
                    sending_bank=s.bank_id,
                    receiving_bank=m_target.bank_id
                )
                transactions.append(tx_micro)
                txn_counter += 1

        # 5. Utility Bill Payments (Retail to Nodal)
        if nodal_accs:
            for r in retail_accs:
                if self.rng.random() < 0.35:
                    utility = self.rng.choice(nodal_accs)
                    desired_bill = float(self.rng.uniform(250.0, 4200.0))
                    bill_amt = self._execute_transfer(r, utility, desired_bill)
                    if bill_amt <= 0.0:
                        continue

                    ts_bill = self._sample_timestamp()

                    tx_bill = SyntheticTransaction(
                        txn_id=f"TXN_{txn_counter:08d}",
                        src_account_id=r.account_id,
                        dst_account_id=utility.account_id,
                        amount_inr=bill_amt,
                        channel="UPI",
                        timestamp=ts_bill.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        scenario_label="normal_bill_payment",
                        sending_bank=r.bank_id,
                        receiving_bank=utility.bank_id
                    )
                    transactions.append(tx_bill)
                    txn_counter += 1

        # Sort all transactions chronologically
        transactions.sort(key=lambda t: t.timestamp)
        return transactions

    def write_to_databases(
        self,
        bank_accounts: Dict[str, List[SyntheticAccount]],
        transactions: List[SyntheticTransaction],
        base_data_dir: str = "data"
    ):
        """Write accounts and transactions into each bank's physically isolated SQLite DB."""
        banks_dir = os.path.join(base_data_dir, "banks")
        os.makedirs(banks_dir, exist_ok=True)

        # 1. Initialize databases and write accounts
        for bank_id, accs in bank_accounts.items():
            init_bank_db(bank_id, base_dir=banks_dir)
            db_path = get_bank_db_path(bank_id, base_dir=banks_dir)
            conn = sqlite3.connect(db_path)
            conn.execute("PRAGMA foreign_keys = ON;")
            cur = conn.cursor()

            # Insert accounts in batch
            cur.executemany("""
                INSERT OR REPLACE INTO accounts (
                    account_id, bank_id, synthetic_name, account_type,
                    merchant_size_tier, account_age_days, balance_inr,
                    mu_90d, sigma_90d, m_local_score
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, [
                (
                    a.account_id, a.bank_id, a.synthetic_name, a.account_type,
                    a.merchant_size_tier, a.account_age_days, a.balance_inr,
                    a.mu_90d, a.sigma_90d, a.m_local_score
                ) for a in accs
            ])
            conn.commit()
            conn.close()

        # 2. Write transactions:
        # Cross-bank logic:
        # - Sender bank writes raw transaction with real sender account and target account.
        # - Receiver bank writes transaction where sender is its local clearing gateway account,
        #   protecting the other bank's customer PII while ensuring receiver's ledger records incoming funds.
        tx_by_sender: Dict[str, List[Tuple]] = {b: [] for b in self.all_banks}
        tx_by_receiver: Dict[str, List[Tuple]] = {b: [] for b in self.all_banks}

        for tx in transactions:
            # Sender Bank entry
            tx_by_sender[tx.sending_bank].append((
                tx.txn_id, tx.src_account_id, tx.dst_account_id,
                tx.amount_inr, tx.channel, tx.timestamp, tx.scenario_label
            ))

            # Receiver Bank entry (if cross-bank)
            if tx.sending_bank != tx.receiving_bank:
                # Receiver uses its inward clearing gateway account as src_account_id
                receiver_clearing_src = f"ACC_{tx.receiving_bank}_NPCI_INWARD"
                inward_tx_id = f"{tx.txn_id}_IN"
                inward_label = f"{tx.scenario_label}_incoming"
                tx_by_receiver[tx.receiving_bank].append((
                    inward_tx_id, receiver_clearing_src, tx.dst_account_id,
                    tx.amount_inr, tx.channel, tx.timestamp, inward_label
                ))

        # Commit transactions into respective bank databases
        for bank_id in self.all_banks:
            db_path = get_bank_db_path(bank_id, base_dir=banks_dir)
            conn = sqlite3.connect(db_path)
            conn.execute("PRAGMA foreign_keys = ON;")
            cur = conn.cursor()

            # Insert outgoing / internal transactions
            cur.executemany("""
                INSERT OR IGNORE INTO raw_transactions (
                    txn_id, src_account_id, dst_account_id, amount_inr,
                    channel, timestamp, scenario_label
                ) VALUES (?, ?, ?, ?, ?, ?, ?);
            """, tx_by_sender[bank_id])

            # Insert incoming cross-bank transactions
            cur.executemany("""
                INSERT OR IGNORE INTO raw_transactions (
                    txn_id, src_account_id, dst_account_id, amount_inr,
                    channel, timestamp, scenario_label
                ) VALUES (?, ?, ?, ?, ?, ?, ?);
            """, tx_by_receiver[bank_id])

            conn.commit()
            conn.close()

    def generate_summary_report(
        self,
        bank_accounts: Dict[str, List[SyntheticAccount]],
        transactions: List[SyntheticTransaction],
        output_path: str = "docs/generated/sim_summary.md"
    ) -> str:
        """Create a structured Markdown report summarizing the synthetic ledger generation."""
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        all_accounts = [acc for b_accs in bank_accounts.values() for acc in b_accs]
        total_accounts = len(all_accounts)
        total_txns = len(transactions)
        total_vol = sum(t.amount_inr for t in transactions)

        amounts = np.array([t.amount_inr for t in transactions]) if transactions else np.array([0.0])

        # Channel distribution
        channel_counts: Dict[str, int] = {}
        for t in transactions:
            channel_counts[t.channel] = channel_counts.get(t.channel, 0) + 1

        # Scenario distribution
        scenario_counts: Dict[str, int] = {}
        for t in transactions:
            scenario_counts[t.scenario_label] = scenario_counts.get(t.scenario_label, 0) + 1

        # Inter-bank vs Intra-bank
        cross_bank_count = sum(1 for t in transactions if t.sending_bank != t.receiving_bank)
        intra_bank_count = total_txns - cross_bank_count

        # Account type counts
        type_counts: Dict[str, int] = {}
        cold_start_count = 0
        for a in all_accounts:
            type_counts[a.account_type] = type_counts.get(a.account_type, 0) + 1
            if a.account_age_days < 14:
                cold_start_count += 1

        # Build markdown text
        md = [
            "# CHAKRA-DPI Synthetic Ledger Generation Summary",
            "",
            f"**Generation Timestamp:** {datetime.datetime.now(datetime.timezone.utc).isoformat()}",
            f"**Random Seed:** `{self.seed}`",
            f"**Simulated Time Horizon:** `{self.time_horizon_days}` days ({self.start_dt.date()} to {(self.start_dt + datetime.timedelta(days=self.time_horizon_days)).date()})",
            "",
            "---",
            "",
            "## 1. Account Distribution & Demographics",
            "",
            f"* **Total Accounts Instantiated:** {total_accounts:,}",
            f"* **Cold-Start Accounts (< 14 days):** {cold_start_count:,} ({cold_start_count/total_accounts*100:.1f}%)",
            "",
            "| Bank Identifier | Status | Total Accounts | Retail | Kirana Merchant | Student | Nodal / Clearing |",
            "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |"
        ]

        for bank_id in self.all_banks:
            accs = bank_accounts[bank_id]
            status = "Participating" if bank_id in self.participating_banks else "Unjoined / External"
            b_retail = sum(1 for a in accs if a.account_type == "retail")
            b_merch = sum(1 for a in accs if a.account_type == "kirana_merchant")
            b_stud = sum(1 for a in accs if a.account_type == "student")
            b_nodal = sum(1 for a in accs if a.account_type == "nodal_whitelisted")
            md.append(f"| `{bank_id}` | {status} | {len(accs):,} | {b_retail:,} | {b_merch:,} | {b_stud:,} | {b_nodal:,} |")

        md.extend([
            "",
            "---",
            "",
            "## 2. Transaction Dynamics & Velocity",
            "",
            f"* **Total Transactions Generated:** {total_txns:,}",
            f"* **Total Transaction Volume:** INR {total_vol:,.2f}",
            f"* **Cross-Bank Inter-Institutional Transactions:** {cross_bank_count:,} ({cross_bank_count/total_txns*100:.1f}%)",
            f"* **Intra-Bank Domestic Transactions:** {intra_bank_count:,} ({intra_bank_count/total_txns*100:.1f}%)",
            "",
            "### Transaction Volume by Payment Channel",
            "| Channel | Transaction Count | Share (%) | Volume (INR) |",
            "| :--- | :--- | :--- | :--- |"
        ])

        for ch in ["UPI", "IMPS", "RTGS"]:
            c = channel_counts.get(ch, 0)
            vol = sum(t.amount_inr for t in transactions if t.channel == ch)
            share = (c / total_txns * 100) if total_txns > 0 else 0
            md.append(f"| `{ch}` | {c:,} | {share:.1f}% | INR {vol:,.2f} |")

        md.extend([
            "",
            "### Transaction Breakdown by Behavioral Scenario",
            "| Scenario Archetype | Count | Share (%) | Description |",
            "| :--- | :--- | :--- | :--- |"
        ])

        for sc, c in sorted(scenario_counts.items(), key=lambda x: x[1], reverse=True):
            share = (c / total_txns * 100) if total_txns > 0 else 0
            md.append(f"| `{sc}` | {c:,} | {share:.1f}% | Normal synthetic activity flow |")

        md.extend([
            "",
            "### Amount Percentiles (INR)",
            "| Percentile | Value (INR) |",
            "| :--- | :--- |",
            f"| **p10** | INR {np.percentile(amounts, 10):,.2f} |",
            f"| **p25** | INR {np.percentile(amounts, 25):,.2f} |",
            f"| **p50 (Median)** | INR {np.percentile(amounts, 50):,.2f} |",
            f"| **p75** | INR {np.percentile(amounts, 75):,.2f} |",
            f"| **p90** | INR {np.percentile(amounts, 90):,.2f} |",
            f"| **p95** | INR {np.percentile(amounts, 95):,.2f} |",
            f"| **p99** | INR {np.percentile(amounts, 99):,.2f} |",
            f"| **Max** | INR {np.max(amounts):,.2f} |",
            "",
            "---",
            "*Report auto-generated by `src/simulator/generator.py` under SFIC 2026 Phase 02.*"
        ])

        report_content = "\n".join(md)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report_content)

        return report_content


def run_generation(
    config_path: str = "configs/simulation_v1.yaml",
    accounts_override: Optional[int] = None,
    full: bool = False,
    data_dir: str = "data",
    summary_path: str = "docs/generated/sim_summary.md",
    seed: Optional[int] = None
) -> Tuple[Dict[str, List[SyntheticAccount]], List[SyntheticTransaction]]:
    """Run full end-to-end synthetic account and transaction generation pipeline."""
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    if full:
        target_accounts = cfg["simulation"].get("benchmark_accounts", 50000)
    elif accounts_override is not None:
        target_accounts = accounts_override
    else:
        target_accounts = cfg["simulation"].get("total_accounts", 5000)

    print(f"[*] Initializing Synthetic Generator (Target: {target_accounts:,} accounts)...")
    gen = SyntheticGenerator(config_path=config_path, seed=seed)

    print("[*] Generating synthetic multi-bank accounts...")
    bank_accounts = gen.generate_accounts(total_accounts=target_accounts)

    print("[*] Generating IBM AMLSim-style multi-bank transaction flows...")
    transactions = gen.generate_transactions(bank_accounts)

    print(f"[*] Writing data to 5 bank databases in '{data_dir}/banks'...")
    gen.write_to_databases(bank_accounts, transactions, base_data_dir=data_dir)

    print(f"[*] Compiling summary report to '{summary_path}'...")
    gen.generate_summary_report(bank_accounts, transactions, output_path=summary_path)

    print(f"[✔] Generation complete: {sum(len(a) for a in bank_accounts.values()):,} accounts and {len(transactions):,} transactions written.")
    return bank_accounts, transactions


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CHAKRA-DPI Synthetic Ledger Generator")
    parser.add_argument("--config", default="configs/simulation_v1.yaml", help="Path to simulation YAML config.")
    parser.add_argument("--accounts", type=int, default=None, help="Override target account count (default: 5000 from config).")
    parser.add_argument("--full", action="store_true", help="Generate full benchmark scale (50,000 accounts).")
    parser.add_argument("--data-dir", default="data", help="Base directory for database files (default: data).")
    parser.add_argument("--summary-path", default="docs/generated/sim_summary.md", help="Path to output summary Markdown.")
    parser.add_argument("--seed", type=int, default=None, help="Override random seed.")
    args = parser.parse_args()

    run_generation(
        config_path=args.config,
        accounts_override=args.accounts,
        full=args.full,
        data_dir=args.data_dir,
        summary_path=args.summary_path,
        seed=args.seed
    )
