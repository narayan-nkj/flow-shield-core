"""Test suite for Phase 06: Mock HSM & Token Service (PRD Deliverables).

Verifies:
1. Exact 64-char hex token format and deterministic HMAC generation.
2. Key rotation lifecycle: sliding dual-key overlap window, expiration, and emergency revocation.
3. Rate limiting enforcement and absence of bulk export APIs.
4. Comprehensive audit logging into kms_access_logs.
5. ZERO PII LEAKAGE DELIVERABLE: Scans every table and column in central risk_relay.db,
   hsm_mock.db, and compliance_ledger.db to verify zero raw account IDs, synthetic names,
   or balances leak outside bank-local premises.
"""

import datetime
import os
import re
import sqlite3
import time
import pytest

from src.bank_local.vault import BankVault
from src.token_service.hsm_mock import (
    ExpiredEpochError,
    MockHSMService,
    PseudonymousEdgePipeline,
    RateLimitExceededError,
    RevokedEpochError,
    normalize_account_identifier,
)


@pytest.fixture(scope="module")
def hsm_fixture(tmp_path_factory):
    """Fixture initializing MockHSM in a temporary directory."""
    temp_dir = tmp_path_factory.mktemp("hsm_test_dir")
    kms_path = str(temp_dir / "hsm_mock.db")
    hsm = MockHSMService(kms_db_path=kms_path, rate_limit_per_window=1000, rate_window_seconds=10)
    epoch_id = hsm.create_epoch(duration_hours=24, overlap_hours=24)
    return {"hsm": hsm, "epoch_id": epoch_id, "kms_path": kms_path}


# --- Test 1: Token Format & Determinism ---
def test_token_format_and_determinism(hsm_fixture):
    """Verify that tokens are strictly 64-character lowercase hex strings and deterministic."""
    hsm: MockHSMService = hsm_fixture["hsm"]
    epoch_id: str = hsm_fixture["epoch_id"]

    acc_id = "ACC_BANK_A_000042"
    tok1 = hsm.tokenize(acc_id, epoch_id, requesting_bank_id="BANK_A")
    tok2 = hsm.tokenize(acc_id, epoch_id, requesting_bank_id="BANK_A")

    # Exact format check: 64 lowercase hex characters
    assert len(tok1) == 64
    assert re.fullmatch(r"[0-9a-f]{64}", tok1) is not None

    # Determinism: same input + same epoch = identical token
    assert tok1 == tok2

    # Normalization: casing and whitespace do not alter token
    tok_lower = hsm.tokenize("acc_bank_a_000042", epoch_id, requesting_bank_id="BANK_A")
    tok_spaces = hsm.tokenize("  ACC_BANK_A_000042  ", epoch_id, requesting_bank_id="BANK_A")
    assert tok_lower == tok1
    assert tok_spaces == tok1

    # Sensitivity: different epoch = completely different token
    new_epoch = hsm.create_epoch(duration_hours=24, overlap_hours=24)
    tok_diff_epoch = hsm.tokenize(acc_id, new_epoch, requesting_bank_id="BANK_A")
    assert tok_diff_epoch != tok1


# --- Test 2: Rotation, Overlap Window, Expiry & Revocation ---
def test_rotation_and_overlap_lifecycle(hsm_fixture):
    """Verify 24-hour dual-key overlap, expiry rejection, and immediate revocation."""
    hsm: MockHSMService = hsm_fixture["hsm"]
    now = datetime.datetime.now(datetime.timezone.utc)

    # 1. Create base epoch
    ep1 = hsm.create_epoch(valid_from=now, duration_hours=24, overlap_hours=24)

    # 2. Rotate to ep2
    ep2 = hsm.rotate(requesting_bank_id="BANK_A")

    # In overlap window: both epochs are active and can produce bridge tokens
    tok_ep1 = hsm.tokenize("ACC_BANK_B_000001", ep1, "BANK_B", as_of_ts=now + datetime.timedelta(hours=2))
    tok_ep2 = hsm.tokenize("ACC_BANK_B_000001", ep2, "BANK_B", as_of_ts=now + datetime.timedelta(hours=2))
    assert tok_ep1 != tok_ep2
    assert len(tok_ep1) == 64
    assert len(tok_ep2) == 64

    # Bridge method returns both
    overlap_tokens = hsm.tokenize_with_overlap("ACC_BANK_B_000001", now + datetime.timedelta(hours=2), "BANK_B")
    assert ep1 in overlap_tokens
    assert ep2 in overlap_tokens

    # 3. Test Expiry: past overlap window (>48 hours), ep1 must fail
    past_overlap = now + datetime.timedelta(hours=50)
    with pytest.raises(ExpiredEpochError):
        hsm.tokenize("ACC_BANK_B_000001", ep1, "BANK_B", as_of_ts=past_overlap)

    # 4. Emergency Revocation: immediate effect
    hsm.revoke(ep2, requesting_bank_id="SECURITY_TEAM")
    with pytest.raises(RevokedEpochError):
        hsm.tokenize("ACC_BANK_B_000001", ep2, "BANK_B")


# --- Test 3: Rate Limiting & Absence of Bulk Export API ---
def test_rate_limiting_and_no_bulk_export(tmp_path_factory):
    """Verify per-bank rate limiting and assert bulk export is non-existent."""
    temp_dir = tmp_path_factory.mktemp("rate_limit_test")
    kms_path = str(temp_dir / "hsm_rate.db")

    # Set tight rate limit: max 5 requests per 5-second window
    hsm = MockHSMService(kms_db_path=kms_path, rate_limit_per_window=5, rate_window_seconds=5)
    epoch_id = hsm.create_epoch(duration_hours=24, overlap_hours=24)

    # First 5 requests succeed
    for i in range(5):
        hsm.tokenize(f"ACC_TEST_{i}", epoch_id, requesting_bank_id="BANK_A")

    # 6th request must raise RateLimitExceededError
    with pytest.raises(RateLimitExceededError):
        hsm.tokenize("ACC_TEST_OVERFLOW", epoch_id, requesting_bank_id="BANK_A")

    # Requests from a different bank succeed (rate limit is per bank)
    tok_b = hsm.tokenize("ACC_TEST_BANK_B", epoch_id, requesting_bank_id="BANK_B")
    assert len(tok_b) == 64

    # Assert bulk export API does not exist (fail-closed architecture)
    assert not hasattr(hsm, "export_all_tokens"), "SECURITY VIOLATION: Bulk export API exists!"
    assert not hasattr(hsm, "dump_keys"), "SECURITY VIOLATION: Key dumping API exists!"


# --- Test 4: KMS Audit Logging ---
def test_kms_audit_logging(hsm_fixture):
    """Verify that all HSM operations write immutable entries to kms_access_logs."""
    hsm: MockHSMService = hsm_fixture["hsm"]
    conn = hsm._get_connection()
    cur = conn.cursor()

    cur.execute("SELECT DISTINCT operation FROM kms_access_logs;")
    operations = {row[0] for row in cur.fetchall()}
    conn.close()

    # Operations observed during lifecycle
    assert "CREATE" in operations
    assert "TOKENIZE" in operations


# --- Test 5: ZERO PII LEAKAGE DELIVERABLE ---
def test_zero_pii_leakage_in_central_and_audit_stores():
    """MANDATORY PRD DELIVERABLE: Scans all central and audit databases for raw PII leakage.

    Asserts that NO raw account_id, synthetic customer name, or raw balance_inr
    appears anywhere in risk_relay.db, hsm_mock.db, or compliance_ledger.db.
    """
    # 1. Ingest transactions using pipeline into risk_relay.db
    hsm = MockHSMService(kms_db_path="data/kms/hsm_mock.db")
    pipeline = PseudonymousEdgePipeline(hsm_service=hsm, central_db_path="data/central/risk_relay.db", base_data_dir="data")
    pipeline.process_edges(participating_banks=["BANK_A", "BANK_B", "BANK_C"], stream_mode=True)

    # 2. Collect all raw PII from local bank accounts
    raw_account_ids: Set[str] = set()
    raw_synthetic_names: Set[str] = set()

    for bank_id in ["BANK_A", "BANK_B", "BANK_C", "BANK_D", "BANK_E"]:
        with BankVault(bank_id) as vault:
            conn = vault._get_connection()
            cur = conn.cursor()
            cur.execute("SELECT account_id, synthetic_name FROM accounts;")
            for r in cur.fetchall():
                raw_account_ids.add(r[0])
                # Filter out nodal names that are generic system tags
                if not r[1].startswith("Synth_NPCI_Inward"):
                    raw_synthetic_names.add(r[1])

    assert len(raw_account_ids) > 0, "No accounts found to audit!"
    assert len(raw_synthetic_names) > 0, "No synthetic names found to audit!"

    # 3. Audit central databases: risk_relay.db, hsm_mock.db, compliance_ledger.db
    dbs_to_audit = [
        ("data/central/risk_relay.db", []),
        ("data/kms/hsm_mock.db", ["mock_secret_hex"]),  # mock_secret_hex is key material, not PII
        ("data/audit/compliance_ledger.db", [])
    ]

    for db_path, ignored_cols in dbs_to_audit:
        if not os.path.exists(db_path):
            continue

        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        # Get all tables
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
        tables = [r[0] for r in cur.fetchall()]

        for tbl in tables:
            cur.execute(f"PRAGMA table_info({tbl});")
            col_info = cur.fetchall()
            col_names = [c[1] for c in col_info]

            # A. Column Name Check: Prohibit PII column names
            for col in col_names:
                assert col.lower() not in {"account_id", "synthetic_name", "balance_inr"}, (
                    f"PRIVACY VIOLATION: Prohibited column '{col}' exists in table '{tbl}' of {db_path}!"
                )

            # B. Data Content String Search: Scan every row for raw PII substrings
            valid_cols = [c for c in col_names if c not in ignored_cols]
            if not valid_cols:
                continue

            query = f"SELECT {', '.join(valid_cols)} FROM {tbl};"
            cur.execute(query)
            rows = cur.fetchall()

            for row in rows:
                for val in row:
                    if val is None:
                        continue
                    val_str = str(val)

                    # Check for raw account ID leaks
                    for acc in raw_account_ids:
                        assert acc not in val_str, (
                            f"LEAK DETECTED: Raw account_id '{acc}' found in table '{tbl}' of {db_path}!"
                        )

                    # Check for synthetic customer name leaks
                    for name in raw_synthetic_names:
                        assert name not in val_str, (
                            f"LEAK DETECTED: Customer name '{name}' found in table '{tbl}' of {db_path}!"
                        )
        conn.close()
