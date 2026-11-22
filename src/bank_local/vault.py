"""Bank-Local Physical Vault & Isolated Data Access Layer.

Enforces:
1. Strict per-bank physical database isolation (one BankVault instance wraps ONLY that bank's SQLite DB).
2. Boundary path check: disallows path traversal or reading another bank's DB by design.
3. Local reverse lookup (token_hash -> account_id) that stays 100% inside bank premises.
4. Cohort statistics extraction for cold-start (<14d) feature derivation.
"""

import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.common.ids import get_bank_db_path, get_bank_filename, normalize_bank_id


class BankVault:
    """Isolated access wrapper for a single bank's private SQLite database."""

    VALID_BANKS = {"BANK_A", "BANK_B", "BANK_C", "BANK_D", "BANK_E"}

    def __init__(self, bank_id: str, data_dir: str = "data/banks"):
        self.bank_id = normalize_bank_id(bank_id)
        if self.bank_id not in self.VALID_BANKS:
            raise ValueError(f"Unauthorized bank identifier: {bank_id}. Must be one of {self.VALID_BANKS}")

        self.base_data_dir = Path(data_dir).resolve()
        expected_filename = get_bank_filename(self.bank_id)
        self.db_path = (self.base_data_dir / expected_filename).resolve()

        # Physical boundary security check: prevent path traversal or crossing into another bank
        try:
            self.db_path.relative_to(self.base_data_dir)
        except ValueError as exc:
            raise PermissionError(f"Security violation: path traversal detected outside bank directory: {self.db_path}") from exc

        if self.db_path.name != expected_filename:
            raise PermissionError(f"Security violation: BankVault for {self.bank_id} attempted to bind to {self.db_path.name}")

        self._conn: Optional[sqlite3.Connection] = None

    def _get_connection(self) -> sqlite3.Connection:
        """Create or return active SQLite connection with foreign keys enabled."""
        if self._conn is None:
            if not self.db_path.exists():
                raise FileNotFoundError(f"Bank database does not exist: {self.db_path}")
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA foreign_keys = ON;")
        return self._conn

    def close(self):
        """Close database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def get_account(self, account_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve local account master record by account_id."""
        conn = self._get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT account_id, bank_id, synthetic_name, account_type,
                   merchant_size_tier, account_age_days, balance_inr,
                   mu_90d, sigma_90d, m_local_score
            FROM accounts
            WHERE account_id = ?;
            """,
            (account_id,)
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def list_transactions(
        self,
        account_id: Optional[str] = None,
        window_start: Optional[str] = None,
        window_end: Optional[str] = None,
        as_sender: bool = True,
        as_receiver: bool = True
    ) -> List[Dict[str, Any]]:
        """Retrieve transactions within a temporal window, optionally filtered by account."""
        conn = self._get_connection()
        cur = conn.cursor()

        query_parts = ["SELECT txn_id, src_account_id, dst_account_id, amount_inr, channel, timestamp, scenario_label FROM raw_transactions WHERE 1=1"]
        params: List[Any] = []

        if account_id:
            if as_sender and as_receiver:
                query_parts.append("AND (src_account_id = ? OR dst_account_id = ?)")
                params.extend([account_id, account_id])
            elif as_sender:
                query_parts.append("AND src_account_id = ?")
                params.append(account_id)
            elif as_receiver:
                query_parts.append("AND dst_account_id = ?")
                params.append(account_id)

        if window_start:
            query_parts.append("AND timestamp >= ?")
            params.append(window_start)
        if window_end:
            query_parts.append("AND timestamp <= ?")
            params.append(window_end)

        query_parts.append("ORDER BY timestamp ASC")
        query = " ".join(query_parts)

        cur.execute(query, tuple(params))
        rows = cur.fetchall()
        return [dict(r) for r in rows]

    def store_token_mapping(
        self,
        token_hash: str,
        account_id: str,
        epoch_id: str,
        created_at: Optional[str] = None
    ) -> None:
        """Store reverse lookup token mapping inside local bank firewall."""
        conn = self._get_connection()
        cur = conn.cursor()
        ts = created_at or "2026-11-22T00:00:00Z"

        cur.execute(
            """
            INSERT OR REPLACE INTO local_token_map (token_hash, account_id, epoch_id, created_at)
            VALUES (?, ?, ?, ?);
            """,
            (token_hash, account_id, epoch_id, ts)
        )
        conn.commit()

    def reverse_lookup(self, token_hash: str) -> Optional[str]:
        """Resolve a pseudonymous HMAC token back to its real account_id.

        STRICTLY LOCAL: This operation occurs strictly inside bank premises
        to allow Bank Nodal Officers to identify the account when reviewing
        central advisory signals.
        """
        conn = self._get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT account_id FROM local_token_map WHERE token_hash = ?;",
            (token_hash,)
        )
        row = cur.fetchone()
        return row["account_id"] if row else None

    def get_cohort_statistics(
        self,
        account_type: str,
        merchant_size_tier: Optional[str] = None
    ) -> Tuple[float, float]:
        """Compute peer-cohort baseline metrics (mu_cohort, sigma_cohort) for cold-start fallback.

        FAIRNESS ENFORCEMENT: Cohorts are strictly partitioned by commercial attributes
        (account_type and merchant_size_tier). Demographic attributes are never used.
        """
        conn = self._get_connection()
        cur = conn.cursor()

        if account_type == "kirana_merchant" and merchant_size_tier:
            cur.execute(
                """
                SELECT AVG(mu_90d), AVG(sigma_90d)
                FROM accounts
                WHERE account_type = ? AND merchant_size_tier = ? AND account_age_days >= 14;
                """,
                (account_type, merchant_size_tier)
            )
        else:
            cur.execute(
                """
                SELECT AVG(mu_90d), AVG(sigma_90d)
                FROM accounts
                WHERE account_type = ? AND account_age_days >= 14;
                """,
                (account_type,)
            )

        row = cur.fetchone()
        avg_mu = row[0] if row and row[0] is not None else 2500.0
        avg_sigma = row[1] if row and row[1] is not None else 800.0
        return float(avg_mu), float(avg_sigma)
