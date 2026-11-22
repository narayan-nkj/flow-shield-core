#!/usr/bin/env python3
"""CHAKRA-DPI Database Initializer & Physical Isolation Schema Builder.

Instantiates 4 physically decoupled SQLite database files:
1. Bank-Local Vaults (data/banks/bank_{a..e}.db)
2. Mock KMS / HSM Store (data/kms/hsm_mock.db)
3. Central Risk Relay (data/central/risk_relay.db)
4. Compliance & Audit Ledger (data/audit/compliance_ledger.db)

Enforces:
- Foreign key constraints (PRAGMA foreign_keys = ON)
- Append-only immutability triggers on compliance audit tables
- Performance indexing on lookup and timestamp columns
- Idempotency with optional --reset flag
"""

import argparse
import os
import sqlite3
import sys
from pathlib import Path
from typing import List

# Add parent directory to sys.path to allow execution both as module and standalone
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.common.ids import get_bank_db_path, normalize_bank_id


def get_db_connection(db_path: str) -> sqlite3.Connection:
    """Create and return a SQLite connection with foreign keys enabled."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_bank_db(bank_id: str, base_dir: str = "data/banks") -> str:
    """Initialize bank-local database with account, transaction, and token mapping tables."""
    canonical_id = normalize_bank_id(bank_id)
    db_path = get_bank_db_path(canonical_id, base_dir=base_dir)
    conn = get_db_connection(db_path)
    cur = conn.cursor()

    # Accounts table (Raw PII Vault - stays strictly inside bank premises)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS accounts (
        account_id TEXT PRIMARY KEY,
        bank_id TEXT NOT NULL,
        synthetic_name TEXT NOT NULL,
        account_type TEXT CHECK(account_type IN ('retail', 'kirana_merchant', 'student', 'nodal_whitelisted')),
        merchant_size_tier TEXT,
        account_age_days INTEGER NOT NULL,
        balance_inr REAL NOT NULL,
        mu_90d REAL DEFAULT 0.0,
        sigma_90d REAL DEFAULT 1.0,
        m_local_score REAL DEFAULT 0.5
    );
    """)

    # Raw Transactions table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS raw_transactions (
        txn_id TEXT PRIMARY KEY,
        src_account_id TEXT NOT NULL,
        dst_account_id TEXT NOT NULL,
        amount_inr REAL NOT NULL,
        channel TEXT CHECK(channel IN ('UPI', 'IMPS', 'RTGS')),
        timestamp TEXT NOT NULL,
        scenario_label TEXT,
        FOREIGN KEY(src_account_id) REFERENCES accounts(account_id)
    );
    """)

    # Local reverse lookup token map (stays inside bank firewall)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS local_token_map (
        token_hash TEXT PRIMARY KEY,
        account_id TEXT NOT NULL,
        epoch_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(account_id) REFERENCES accounts(account_id)
    );
    """)

    # Performance Indexes
    cur.execute("CREATE INDEX IF NOT EXISTS idx_raw_tx_timestamp ON raw_transactions(timestamp);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_raw_tx_src ON raw_transactions(src_account_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_raw_tx_dst ON raw_transactions(dst_account_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_local_token_acct ON local_token_map(account_id);")

    conn.commit()
    conn.close()
    return db_path


def init_kms_db(db_path: str = "data/kms/hsm_mock.db") -> str:
    """Initialize Mock KMS / HSM database for epoch key storage and audit logging."""
    conn = get_db_connection(db_path)
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS epoch_keys (
        epoch_id TEXT PRIMARY KEY,
        mock_secret_hex TEXT NOT NULL,
        valid_from TEXT NOT NULL,
        valid_to TEXT NOT NULL,
        overlap_until TEXT NOT NULL,
        is_revoked INTEGER DEFAULT 0
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS kms_access_logs (
        log_id INTEGER PRIMARY KEY AUTOINCREMENT,
        requesting_bank_id TEXT NOT NULL,
        epoch_id TEXT NOT NULL,
        operation TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        FOREIGN KEY(epoch_id) REFERENCES epoch_keys(epoch_id)
    );
    """)

    conn.commit()
    conn.close()
    return db_path


def init_risk_db(db_path: str = "data/central/risk_relay.db") -> str:
    """Initialize Central Risk Relay database with pseudonymous edge store and advisory cases.

    ZERO PII GUARANTEE: Never stores raw account IDs, customer names, or raw balances.
    """
    conn = get_db_connection(db_path)
    cur = conn.cursor()

    # Pseudonymous Ingested Edges
    cur.execute("""
    CREATE TABLE IF NOT EXISTS pseudonymous_edges (
        edge_id TEXT PRIMARY KEY,
        src_token TEXT NOT NULL,
        dst_token TEXT NOT NULL,
        log_amount REAL NOT NULL,
        delta_t_sec REAL NOT NULL,
        channel_id TEXT NOT NULL,
        source_bank_id TEXT NOT NULL,
        epoch_id TEXT NOT NULL,
        event_ts TEXT NOT NULL,
        ingested_ts TEXT NOT NULL
    );
    """)

    # Advisory Cases Generated by Scoring Engine
    cur.execute("""
    CREATE TABLE IF NOT EXISTS advisory_cases (
        case_id TEXT PRIMARY KEY,
        target_token TEXT NOT NULL,
        score_p REAL NOT NULL,
        score_band TEXT CHECK(score_band IN ('PRIORITY', 'ADDITIONAL_REVIEW', 'NO_ELEVATED_ALERT')),
        feature_values_json TEXT NOT NULL,
        feature_contributions_json TEXT NOT NULL,
        linked_tokens_json TEXT NOT NULL,
        participating_banks_count INTEGER NOT NULL,
        total_banks_count INTEGER NOT NULL,
        stale_feed_flag INTEGER DEFAULT 0,
        model_version TEXT NOT NULL,
        feature_version TEXT NOT NULL,
        run_id TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    """)

    # Performance Indexes
    cur.execute("CREATE INDEX IF NOT EXISTS idx_edges_event_ts ON pseudonymous_edges(event_ts);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_edges_src_token ON pseudonymous_edges(src_token);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_edges_dst_token ON pseudonymous_edges(dst_token);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_advisory_target_token ON advisory_cases(target_token);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_advisory_created_at ON advisory_cases(created_at);")

    conn.commit()
    conn.close()
    return db_path


def init_compliance_db(db_path: str = "data/audit/compliance_ledger.db") -> str:
    """Initialize Compliance & Audit Ledger database with tamper-evident hash chaining.

    Enforces append-only immutability via SQLite triggers (ABORT on UPDATE and DELETE).
    """
    conn = get_db_connection(db_path)
    cur = conn.cursor()

    # Nodal Officer Reviewer Decisions
    cur.execute("""
    CREATE TABLE IF NOT EXISTS reviewer_decisions (
        decision_id TEXT PRIMARY KEY,
        case_id TEXT NOT NULL,
        reviewer_id TEXT NOT NULL,
        decision_type TEXT CHECK(decision_type IN ('REFER_BANK_LEA', 'NO_ACTION', 'REQUEST_CUSTOMER_EXPLANATION')),
        officer_reasoning TEXT NOT NULL,
        decided_at TEXT NOT NULL,
        prev_hash TEXT NOT NULL,
        row_hash TEXT NOT NULL
    );
    """)

    # Customer Notices (Multi-lingual advisories)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS customer_notices (
        notice_id TEXT PRIMARY KEY,
        case_id TEXT NOT NULL,
        language TEXT CHECK(language IN ('EN', 'BN', 'HI')),
        template_version TEXT NOT NULL,
        reason_codes_json TEXT NOT NULL,
        notice_body TEXT NOT NULL,
        generated_at TEXT NOT NULL
    );
    """)

    # RBI Statutory SLA Clock Events (Draft KYC Directions 2026 Annex III)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS sla_clock_events (
        clock_id TEXT PRIMARY KEY,
        case_id TEXT NOT NULL,
        t0_advisory_ts TEXT NOT NULL,
        d20_explanation_due TEXT NOT NULL,
        d30_bank_decision_due TEXT NOT NULL,
        d60_lea_hard_cap TEXT NOT NULL,
        current_status TEXT NOT NULL,
        extension_note TEXT
    );
    """)

    # Grievance & Disagreement Log
    cur.execute("""
    CREATE TABLE IF NOT EXISTS grievance_disagreement_log (
        entry_id TEXT PRIMARY KEY,
        case_id TEXT NOT NULL,
        actor TEXT CHECK(actor IN ('CUSTOMER', 'OFFICER')),
        statement_text TEXT NOT NULL,
        escalation_ref TEXT,
        logged_at TEXT NOT NULL,
        prev_hash TEXT NOT NULL,
        row_hash TEXT NOT NULL
    );
    """)

    # Performance Indexes
    cur.execute("CREATE INDEX IF NOT EXISTS idx_rev_decisions_case_id ON reviewer_decisions(case_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_customer_notices_case_id ON customer_notices(case_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sla_clock_events_case_id ON sla_clock_events(case_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_grievance_log_case_id ON grievance_disagreement_log(case_id);")

    # Cryptographic Append-Only Immutability Triggers for Reviewer Decisions
    cur.execute("""
    CREATE TRIGGER IF NOT EXISTS abort_reviewer_decisions_update
    BEFORE UPDATE ON reviewer_decisions
    BEGIN
        SELECT RAISE(ABORT, 'Audit ledger is append-only: UPDATE prohibited on reviewer_decisions');
    END;
    """)

    cur.execute("""
    CREATE TRIGGER IF NOT EXISTS abort_reviewer_decisions_delete
    BEFORE DELETE ON reviewer_decisions
    BEGIN
        SELECT RAISE(ABORT, 'Audit ledger is append-only: DELETE prohibited on reviewer_decisions');
    END;
    """)

    # Cryptographic Append-Only Immutability Triggers for Grievance Log
    cur.execute("""
    CREATE TRIGGER IF NOT EXISTS abort_grievance_log_update
    BEFORE UPDATE ON grievance_disagreement_log
    BEGIN
        SELECT RAISE(ABORT, 'Audit ledger is append-only: UPDATE prohibited on grievance_disagreement_log');
    END;
    """)

    cur.execute("""
    CREATE TRIGGER IF NOT EXISTS abort_grievance_log_delete
    BEFORE DELETE ON grievance_disagreement_log
    BEGIN
        SELECT RAISE(ABORT, 'Audit ledger is append-only: DELETE prohibited on grievance_disagreement_log');
    END;
    """)

    conn.commit()
    conn.close()
    return db_path


def reset_all_databases(base_data_dir: str = "data", banks: List[str] = None):
    """Safely remove all database files if reset requested."""
    if banks is None:
        banks = ["BANK_A", "BANK_B", "BANK_C", "BANK_D", "BANK_E"]
    
    # Remove bank DBs
    for bank in banks:
        db_path = get_bank_db_path(bank, base_dir=os.path.join(base_data_dir, "banks"))
        if os.path.exists(db_path):
            os.remove(db_path)
            print(f"[!] Removed database: {db_path}")

    # Remove central, kms, and audit DBs
    other_dbs = [
        os.path.join(base_data_dir, "kms", "hsm_mock.db"),
        os.path.join(base_data_dir, "central", "risk_relay.db"),
        os.path.join(base_data_dir, "audit", "compliance_ledger.db")
    ]
    for db in other_dbs:
        if os.path.exists(db):
            os.remove(db)
            print(f"[!] Removed database: {db}")


def init_all(base_data_dir: str = "data", banks: List[str] = None, reset: bool = False):
    """Idempotently initialize all 4 database layers."""
    if banks is None:
        banks = ["BANK_A", "BANK_B", "BANK_C", "BANK_D", "BANK_E"]

    if reset:
        print("[*] --reset flag detected: Purging existing database files...")
        reset_all_databases(base_data_dir=base_data_dir, banks=banks)

    banks_dir = os.path.join(base_data_dir, "banks")
    kms_path = os.path.join(base_data_dir, "kms", "hsm_mock.db")
    risk_path = os.path.join(base_data_dir, "central", "risk_relay.db")
    compliance_path = os.path.join(base_data_dir, "audit", "compliance_ledger.db")

    for bank in banks:
        path = init_bank_db(bank, base_dir=banks_dir)
        print(f"[+] Bank Database initialized: {path}")

    init_kms_db(kms_path)
    print(f"[+] Mock KMS Database initialized: {kms_path}")

    init_risk_db(risk_path)
    print(f"[+] Central Risk Relay Database initialized: {risk_path}")

    init_compliance_db(compliance_path)
    print(f"[+] Compliance & Audit Ledger Database initialized: {compliance_path}")

    print("\n[✔] All 4 physically isolated SQLite databases successfully instantiated.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CHAKRA-DPI Database Initializer")
    parser.add_argument("--reset", action="store_true", help="Delete and recreate all database files.")
    parser.add_argument("--data-dir", default="data", help="Base directory for database storage (default: data).")
    args = parser.parse_args()

    init_all(base_data_dir=args.data_dir, reset=args.reset)
