"""Phase 1 Schema and Isolation Test Suite.

Verifies:
1. All 4 isolated database files are successfully created.
2. Foreign key constraints are enforced (PRAGMA foreign_keys = ON).
3. Append-only triggers block UPDATE and DELETE on audit ledger tables.
4. Privacy Boundary: Central and Audit DBs contain ZERO raw PII columns
   (no account_id, synthetic_name, balance_inr).
5. Bank ID helper round-trip normalization.
"""

import os
import sqlite3
import tempfile
import pytest

from src.common.ids import (
    bank_id_from_filename,
    get_bank_db_path,
    get_bank_filename,
    normalize_bank_id,
)
from src.init_dbs import (
    get_db_connection,
    init_all,
    init_bank_db,
    init_compliance_db,
    init_kms_db,
    init_risk_db,
)


@pytest.fixture(scope="module")
def isolated_dbs(tmp_path_factory):
    """Fixture that initializes all 4 DB layers in a temporary directory."""
    temp_dir = tmp_path_factory.mktemp("chakra_test_data")
    base_data_dir = str(temp_dir)
    banks = ["BANK_A", "BANK_B", "BANK_C", "BANK_D", "BANK_E"]

    init_all(base_data_dir=base_data_dir, banks=banks, reset=True)

    db_paths = {
        "banks": [get_bank_db_path(b, base_dir=os.path.join(base_data_dir, "banks")) for b in banks],
        "kms": os.path.join(base_data_dir, "kms", "hsm_mock.db"),
        "central": os.path.join(base_data_dir, "central", "risk_relay.db"),
        "audit": os.path.join(base_data_dir, "audit", "compliance_ledger.db"),
    }
    return db_paths


# --- Test 1: All DBs Create Successfully ---
def test_all_dbs_created(isolated_dbs):
    """Verify that all database files exist on the filesystem."""
    for bank_path in isolated_dbs["banks"]:
        assert os.path.exists(bank_path), f"Bank DB missing: {bank_path}"

    assert os.path.exists(isolated_dbs["kms"]), "KMS DB missing"
    assert os.path.exists(isolated_dbs["central"]), "Central Risk DB missing"
    assert os.path.exists(isolated_dbs["audit"]), "Compliance Audit DB missing"


# --- Test 2: Foreign Key Constraints Enforced ---
def test_foreign_keys_enforced_bank_db(isolated_dbs):
    """Ensure inserting orphaned transaction raises IntegrityError when FK is ON."""
    bank_path = isolated_dbs["banks"][0]
    conn = get_db_connection(bank_path)

    # Attempt inserting transaction with non-existent account_id
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("""
            INSERT INTO raw_transactions (txn_id, src_account_id, dst_account_id, amount_inr, channel, timestamp)
            VALUES ('TX-001', 'NON_EXISTENT_ACC', 'DEST_ACC', 5000.0, 'UPI', '2026-11-22T10:00:00Z');
        """)
        conn.commit()
    conn.close()


def test_foreign_keys_enforced_kms_db(isolated_dbs):
    """Ensure inserting KMS access log with non-existent epoch_id raises IntegrityError."""
    kms_path = isolated_dbs["kms"]
    conn = get_db_connection(kms_path)

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("""
            INSERT INTO kms_access_logs (requesting_bank_id, epoch_id, operation, timestamp)
            VALUES ('BANK_A', 'NON_EXISTENT_EPOCH', 'TOKENIZE', '2026-11-22T10:00:00Z');
        """)
        conn.commit()
    conn.close()


# --- Test 3: Append-Only Triggers Block UPDATE and DELETE ---
def test_reviewer_decisions_append_only(isolated_dbs):
    """Ensure UPDATE and DELETE on reviewer_decisions are blocked by triggers."""
    audit_path = isolated_dbs["audit"]
    conn = get_db_connection(audit_path)

    # Insert a valid initial decision row
    conn.execute("""
        INSERT INTO reviewer_decisions (
            decision_id, case_id, reviewer_id, decision_type,
            officer_reasoning, decided_at, prev_hash, row_hash
        ) VALUES (
            'DEC-001', 'CASE-001', 'OFFICER-1', 'NO_ACTION',
            'Legitimate student tuition payment', '2026-11-22T12:00:00Z',
            '0000000000000000000000000000000000000000000000000000000000000000',
            'dummyhash123'
        );
    """)
    conn.commit()

    # Attempt UPDATE — Must fail with trigger error
    with pytest.raises(sqlite3.DatabaseError) as exc_update:
        conn.execute("""
            UPDATE reviewer_decisions
            SET officer_reasoning = 'Altered reason'
            WHERE decision_id = 'DEC-001';
        """)
        conn.commit()
    assert "append-only" in str(exc_update.value).lower()

    # Attempt DELETE — Must fail with trigger error
    with pytest.raises(sqlite3.DatabaseError) as exc_delete:
        conn.execute("DELETE FROM reviewer_decisions WHERE decision_id = 'DEC-001';")
        conn.commit()
    assert "append-only" in str(exc_delete.value).lower()

    conn.close()


def test_grievance_log_append_only(isolated_dbs):
    """Ensure UPDATE and DELETE on grievance_disagreement_log are blocked by triggers."""
    audit_path = isolated_dbs["audit"]
    conn = get_db_connection(audit_path)

    conn.execute("""
        INSERT INTO grievance_disagreement_log (
            entry_id, case_id, actor, statement_text, escalation_ref,
            logged_at, prev_hash, row_hash
        ) VALUES (
            'GRV-001', 'CASE-001', 'CUSTOMER', 'I did not initiate this payment', NULL,
            '2026-11-22T13:00:00Z',
            '0000000000000000000000000000000000000000000000000000000000000000',
            'dummyhash456'
        );
    """)
    conn.commit()

    # Attempt UPDATE — Must fail
    with pytest.raises(sqlite3.DatabaseError) as exc_update:
        conn.execute("""
            UPDATE grievance_disagreement_log
            SET statement_text = 'Tampered statement'
            WHERE entry_id = 'GRV-001';
        """)
        conn.commit()
    assert "append-only" in str(exc_update.value).lower()

    # Attempt DELETE — Must fail
    with pytest.raises(sqlite3.DatabaseError) as exc_delete:
        conn.execute("DELETE FROM grievance_disagreement_log WHERE entry_id = 'GRV-001';")
        conn.commit()
    assert "append-only" in str(exc_delete.value).lower()

    conn.close()


# --- Test 4: Privacy Boundary (Zero PII in Central and Audit DBs) ---
def test_privacy_boundary_zero_pii_columns(isolated_dbs):
    """Verify that central and audit databases contain zero PII column names."""
    prohibited_columns = {"account_id", "synthetic_name", "balance_inr"}
    dbs_to_check = [isolated_dbs["central"], isolated_dbs["audit"]]

    for db_path in dbs_to_check:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        # Fetch all tables
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
        tables = [row[0] for row in cur.fetchall()]

        for table in tables:
            cur.execute(f"PRAGMA table_info({table});")
            columns = [col[1].lower() for col in cur.fetchall()]

            for prohibited in prohibited_columns:
                assert prohibited not in columns, (
                    f"PRIVACY VIOLATION: Column '{prohibited}' found in table '{table}' of {db_path}!"
                )
        conn.close()


# --- Test 5: Bank ID Helper Roundtrip ---
def test_bank_id_normalization_and_roundtrip():
    """Verify that bank ID normalizer and filename converters round-trip accurately."""
    # Test normalization
    assert normalize_bank_id("bank_a") == "BANK_A"
    assert normalize_bank_id("BANK_b") == "BANK_B"
    assert normalize_bank_id("  bank_c  ") == "BANK_C"

    # Test filename generation
    assert get_bank_filename("BANK_A") == "bank_a.db"
    assert get_bank_filename("bank_b") == "bank_b.db"

    # Test roundtrip
    for bank in ["BANK_A", "BANK_B", "BANK_C", "BANK_D", "BANK_E"]:
        filename = get_bank_filename(bank)
        recovered_id = bank_id_from_filename(filename)
        assert recovered_id == bank, f"Roundtrip failed for {bank} -> {filename} -> {recovered_id}"

    # Test invalid inputs
    with pytest.raises(ValueError):
        normalize_bank_id("")
    with pytest.raises(ValueError):
        normalize_bank_id(None)
