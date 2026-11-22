"""Mock Hardware Security Module (HSM) & Token Service.

Implements:
1. Epoch-scoped HMAC-SHA-256 tokens using 256-bit mock secrets.
2. 24-hour sliding dual-key overlap window and emergency key revocation.
3. Strict rate limiting per bank and absolute prohibition of bulk export APIs.
4. Comprehensive audit logging into data/kms/hsm_mock.db (kms_access_logs).
5. Pseudonymous edge pipeline with stream mode, converting bank raw transactions
   into central risk edges (src_tok, dst_tok, log(1+Amt), delta_t).
"""

import collections
import datetime
import hashlib
import hmac
import math
import os
import secrets
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from src.common.ids import get_bank_db_path, normalize_bank_id
from src.init_dbs import get_db_connection


class TokenServiceError(Exception):
    """Base exception for Token Service errors."""
    pass


class RevokedEpochError(TokenServiceError):
    """Raised when tokenization is attempted on a revoked key epoch."""
    pass


class ExpiredEpochError(TokenServiceError):
    """Raised when tokenization is attempted on an expired key epoch."""
    pass


class RateLimitExceededError(TokenServiceError):
    """Raised when a bank exceeds its allotted tokenization request quota."""
    pass


def normalize_account_identifier(account_id: str, bank_id: Optional[str] = None) -> str:
    """Normalize account identifier into canonical uppercase format across all banks.

    Ensures that identical accounts tokenize identically regardless of regional whitespace
    or casing variations.
    """
    if not account_id or not isinstance(account_id, str):
        raise ValueError(f"Invalid account identifier: {account_id}")

    clean_id = account_id.strip().upper()
    if bank_id:
        clean_bank = normalize_bank_id(bank_id)
        if not clean_id.startswith(f"{clean_bank}:") and not clean_id.startswith(f"ACC_{clean_bank}"):
            return f"{clean_bank}:{clean_id}"
    return clean_id


class MockHSMService:
    """Simulated Multi-Party Hardware Security Module managing rotating HMAC keys."""

    def __init__(
        self,
        kms_db_path: str = "data/kms/hsm_mock.db",
        rate_limit_per_window: int = 25000,
        rate_window_seconds: int = 10
    ):
        self.kms_db_path = str(Path(kms_db_path).resolve())
        self.rate_limit_per_window = rate_limit_per_window
        self.rate_window_seconds = rate_window_seconds

        # In-memory rate limiting tracker: bank_id -> deque of timestamps
        self._rate_trackers: Dict[str, collections.deque] = collections.defaultdict(collections.deque)

        # Ensure database and tables exist
        self._ensure_schema()

    def _get_connection(self) -> sqlite3.Connection:
        os.makedirs(os.path.dirname(self.kms_db_path), exist_ok=True)
        conn = sqlite3.connect(self.kms_db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _ensure_schema(self):
        conn = self._get_connection()
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

    def _log_access(self, requesting_bank_id: str, epoch_id: str, operation: str):
        """Append an immutable audit entry to kms_access_logs."""
        conn = self._get_connection()
        cur = conn.cursor()
        ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
        cur.execute("""
            INSERT INTO kms_access_logs (requesting_bank_id, epoch_id, operation, timestamp)
            VALUES (?, ?, ?, ?);
        """, (requesting_bank_id, epoch_id, operation, ts))
        conn.commit()
        conn.close()

    def _check_rate_limit(self, requesting_bank_id: str):
        """Sliding-window rate limiter per requesting bank."""
        now = time.time()
        tracker = self._rate_trackers[requesting_bank_id]

        # Prune expired timestamps
        cutoff = now - self.rate_window_seconds
        while tracker and tracker[0] < cutoff:
            tracker.popleft()

        if len(tracker) >= self.rate_limit_per_window:
            raise RateLimitExceededError(
                f"Rate limit exceeded for bank '{requesting_bank_id}': "
                f"Maximum {self.rate_limit_per_window} requests per {self.rate_window_seconds}s."
            )

        tracker.append(now)

    def create_epoch(
        self,
        epoch_id: Optional[str] = None,
        valid_from: Optional[datetime.datetime] = None,
        duration_hours: int = 24,
        overlap_hours: int = 24,
        requesting_bank_id: str = "SYSTEM"
    ) -> str:
        """Create a new epoch with a cryptographically secure 256-bit mock secret."""
        t_from = valid_from or datetime.datetime.now(datetime.timezone.utc)
        t_to = t_from + datetime.timedelta(hours=duration_hours)
        t_overlap = t_to + datetime.timedelta(hours=overlap_hours)

        ep_id = epoch_id or f"EPOCH-{t_from.strftime('%Y%m%d%H%M%S%f')}-{secrets.token_hex(3).upper()}"
        secret_hex = secrets.token_hex(32)  # 256 bits = 32 bytes

        conn = self._get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT epoch_id FROM epoch_keys WHERE epoch_id = ?;", (ep_id,))
            if cur.fetchone():
                return ep_id

            cur.execute("""
                INSERT INTO epoch_keys (epoch_id, mock_secret_hex, valid_from, valid_to, overlap_until, is_revoked)
                VALUES (?, ?, ?, ?, ?, 0);
            """, (
                ep_id, secret_hex,
                t_from.isoformat(),
                t_to.isoformat(),
                t_overlap.isoformat()
            ))
            conn.commit()
        finally:
            conn.close()

        self._log_access(requesting_bank_id, ep_id, "CREATE")
        return ep_id

    def rotate(
        self,
        new_epoch_id: Optional[str] = None,
        requesting_bank_id: str = "SYSTEM"
    ) -> str:
        """Rotate the active epoch key, preserving the dual-key sliding overlap window."""
        now = datetime.datetime.now(datetime.timezone.utc)
        conn = self._get_connection()
        cur = conn.cursor()

        # Update currently active epochs: valid_to becomes now, sliding overlap_until becomes now + 24h (CR02-C)
        cur.execute("""
            SELECT epoch_id, valid_from FROM epoch_keys
            WHERE is_revoked = 0 AND valid_from <= ? AND valid_to > ?;
        """, (now.isoformat(), now.isoformat()))
        active_epochs = cur.fetchall()

        sliding_overlap = now + datetime.timedelta(hours=24)
        for ep in active_epochs:
            cur.execute("""
                UPDATE epoch_keys
                SET valid_to = ?, overlap_until = ?
                WHERE epoch_id = ?;
            """, (now.isoformat(), sliding_overlap.isoformat(), ep["epoch_id"]))

        conn.commit()
        conn.close()

        # Instantiate new epoch starting now
        new_id = self.create_epoch(
            epoch_id=new_epoch_id,
            valid_from=now,
            requesting_bank_id=requesting_bank_id
        )

        for ep in active_epochs:
            self._log_access(requesting_bank_id, ep["epoch_id"], "ROTATE")

        return new_id

    def revoke(self, epoch_id: str, requesting_bank_id: str = "SYSTEM"):
        """Emergency key revocation with immediate effect."""
        conn = self._get_connection()
        cur = conn.cursor()
        cur.execute("UPDATE epoch_keys SET is_revoked = 1 WHERE epoch_id = ?;", (epoch_id,))
        if cur.rowcount == 0:
            conn.close()
            raise ValueError(f"Epoch '{epoch_id}' not found in KMS store.")
        conn.commit()
        conn.close()

        self._log_access(requesting_bank_id, epoch_id, "REVOKE")

    def get_epoch_info(self, epoch_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve metadata for an epoch."""
        conn = self._get_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM epoch_keys WHERE epoch_id = ?;", (epoch_id,))
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else None

    def tokenize(
        self,
        account_id: str,
        epoch_id: str,
        requesting_bank_id: str,
        as_of_ts: Optional[datetime.datetime] = None
    ) -> str:
        """Compute pseudonymous 64-character HMAC-SHA-256 token for an account identifier.

        Enforces:
        - Strict per-bank rate limits.
        - Immediate rejection of revoked epochs.
        - Validity window checks (valid_from <= as_of <= overlap_until).
        - Audit logging.
        """
        self._check_rate_limit(requesting_bank_id)

        ep = self.get_epoch_info(epoch_id)
        if not ep:
            raise ValueError(f"Epoch '{epoch_id}' does not exist in Mock HSM.")

        if ep["is_revoked"] == 1:
            raise RevokedEpochError(f"Epoch '{epoch_id}' has been revoked. Tokenization blocked.")

        ts_check = as_of_ts or datetime.datetime.now(datetime.timezone.utc)
        valid_from = datetime.datetime.fromisoformat(ep["valid_from"].replace("Z", "+00:00"))
        overlap_until = datetime.datetime.fromisoformat(ep["overlap_until"].replace("Z", "+00:00"))

        if ts_check < valid_from:
            raise TokenServiceError(f"Epoch '{epoch_id}' is not yet valid (valid_from: {valid_from}).")
        if ts_check > overlap_until:
            raise ExpiredEpochError(f"Epoch '{epoch_id}' has expired (overlap_until: {overlap_until}).")

        # Canonical normalization
        canonical_id = normalize_account_identifier(account_id)
        key_bytes = bytes.fromhex(ep["mock_secret_hex"])

        # Compute HMAC-SHA-256
        token = hmac.new(key_bytes, canonical_id.encode("utf-8"), hashlib.sha256).hexdigest()

        # Audit log access
        self._log_access(requesting_bank_id, epoch_id, "TOKENIZE")
        return token

    def tokenize_with_overlap(
        self,
        account_id: str,
        as_of_ts: datetime.datetime,
        requesting_bank_id: str
    ) -> Dict[str, str]:
        """Return tokens under all active epochs (primary and dual-key overlap) for linkage bridging."""
        conn = self._get_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT epoch_id FROM epoch_keys
            WHERE is_revoked = 0 AND valid_from <= ? AND overlap_until >= ?;
        """, (as_of_ts.isoformat(), as_of_ts.isoformat()))
        rows = cur.fetchall()
        conn.close()

        tokens: Dict[str, str] = {}
        for r in rows:
            ep_id = r["epoch_id"]
            tokens[ep_id] = self.tokenize(
                account_id=account_id,
                epoch_id=ep_id,
                requesting_bank_id=requesting_bank_id,
                as_of_ts=as_of_ts
            )
        return tokens

    def measure_linkage_continuity(
        self,
        account_ids: List[str],
        epoch_1: str,
        epoch_2: str
    ) -> float:
        """Measure graph linkage continuity across two epochs.

        Returns:
            1.0 if epochs share the identical key (continuous linkage),
            0.0 if keys differ and tokens cannot be cross-linked without bridge metadata.
        """
        ep1 = self.get_epoch_info(epoch_1)
        ep2 = self.get_epoch_info(epoch_2)
        if not ep1 or not ep2:
            return 0.0

        if ep1["mock_secret_hex"] == ep2["mock_secret_hex"]:
            return 1.0

        # Across disjoint epochs with different secrets, deterministic hashes never collide
        tokens_1 = {self.tokenize(acc, epoch_1, "TEST", as_of_ts=datetime.datetime.fromisoformat(ep1["valid_from"])) for acc in account_ids}
        tokens_2 = {self.tokenize(acc, epoch_2, "TEST", as_of_ts=datetime.datetime.fromisoformat(ep2["valid_from"])) for acc in account_ids}
        intersection = tokens_1.intersection(tokens_2)
        return len(intersection) / len(account_ids) if account_ids else 0.0


# --- Pseudonymous Edge Pipeline ---
# Default holding time for accounts with no prior inbound credit in observation window
# 86,400 seconds (24 hours) represents a mature balance holding time, preventing false velocity spikes.
DEFAULT_NO_INFLOW_HOLD_TIME_SEC: float = 86400.0


def get_bank_for_account(account_id: str) -> Optional[str]:
    """Extract bank identifier from canonical account ID format (e.g., 'ACC_BANK_A_000123' -> 'BANK_A')."""
    parts = account_id.split("_")
    if len(parts) >= 3 and parts[0] == "ACC" and parts[1] == "BANK":
        return f"{parts[1]}_{parts[2]}"
    return None


class PseudonymousEdgePipeline:
    """Converts bank-local raw transactions into central pseudonymous edges.

    ZERO PII GUARANTEE:
    - Ingests raw transactions from bank-local SQLite databases.
    - Transforms identifiers into 64-char HMAC tokens.
    - Transforms transaction amounts into log(1 + Amount).
    - Writes strictly to `data/central/risk_relay.db`.
    """

    def __init__(
        self,
        hsm_service: MockHSMService,
        central_db_path: str = "data/central/risk_relay.db",
        base_data_dir: str = "data",
        min_threshold_inr: float = 1000.0  # RBI threshold filter per FR-3
    ):
        self.hsm = hsm_service
        self.central_db_path = central_db_path
        self.base_data_dir = base_data_dir
        self.min_threshold_inr = min_threshold_inr

    def _get_central_connection(self) -> sqlite3.Connection:
        os.makedirs(os.path.dirname(self.central_db_path), exist_ok=True)
        conn = sqlite3.connect(self.central_db_path)
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def process_edges(
        self,
        participating_banks: List[str] = None,
        epoch_id: Optional[str] = None,
        stream_mode: bool = True
    ) -> int:
        """Run the ingestion pipeline across participating banks."""
        if participating_banks is None:
            participating_banks = ["BANK_A", "BANK_B", "BANK_C"]

        banks_dir = os.path.join(self.base_data_dir, "banks")

        # 1. Determine time bounds of transactions
        # If active epoch does not exist or does not cover transactions, create one spanning the data horizon
        if epoch_id is None:
            # Check earliest transaction date
            min_ts = "2026-11-01T00:00:00Z"
            for bank_id in participating_banks:
                db_path = get_bank_db_path(bank_id, base_dir=banks_dir)
                if os.path.exists(db_path):
                    conn_b = sqlite3.connect(db_path)
                    cur_b = conn_b.cursor()
                    cur_b.execute("SELECT MIN(timestamp) FROM raw_transactions;")
                    r = cur_b.fetchone()
                    if r and r[0] and r[0] < min_ts:
                        min_ts = r[0]
                    conn_b.close()

            earliest_dt = datetime.datetime.fromisoformat(min_ts.replace("Z", "+00:00")) - datetime.timedelta(days=1)
            active_epoch = self.hsm.create_epoch(
                epoch_id="EPOCH-SIMULATION-V1",
                valid_from=earliest_dt,
                duration_hours=720,  # 30 days
                overlap_hours=720
            )
        else:
            active_epoch = epoch_id

        # 2. Extract transactions across participating banks
        raw_tx_records = []
        for bank_id in participating_banks:
            db_path = get_bank_db_path(bank_id, base_dir=banks_dir)
            if not os.path.exists(db_path):
                continue

            conn_b = sqlite3.connect(db_path)
            conn_b.row_factory = sqlite3.Row
            cur = conn_b.cursor()
            # We filter by statutory threshold >= INR 1,000 per PRD FR-3
            cur.execute("""
                SELECT txn_id, src_account_id, dst_account_id, amount_inr, channel, timestamp
                FROM raw_transactions
                WHERE amount_inr >= ?;
            """, (self.min_threshold_inr,))
            rows = cur.fetchall()
            for r in rows:
                raw_tx_records.append({
                    "txn_id": r["txn_id"],
                    "src_account_id": r["src_account_id"],
                    "dst_account_id": r["dst_account_id"],
                    "amount_inr": r["amount_inr"],
                    "channel": r["channel"],
                    "timestamp": r["timestamp"],
                    "source_bank_id": bank_id
                })
            conn_b.close()

        # Deduplicate cross-bank transactions:
        # A participating sending bank provides the primary edge (real sender -> recipient).
        # A participating receiving bank only provides an inward edge if the sender was external/non-participating.
        primary_txs = [
            tx for tx in raw_tx_records
            if not tx["src_account_id"].endswith("_NPCI_INWARD") and not tx["txn_id"].endswith("_IN")
        ]
        seen_canonical_ids = {tx["txn_id"] for tx in primary_txs}

        inward_txs = []
        for tx in raw_tx_records:
            if tx["src_account_id"].endswith("_NPCI_INWARD") or tx["txn_id"].endswith("_IN"):
                canonical_id = tx["txn_id"][:-3] if tx["txn_id"].endswith("_IN") else tx["txn_id"]
                if canonical_id not in seen_canonical_ids:
                    seen_canonical_ids.add(canonical_id)
                    inward_txs.append(tx)

        tx_to_process = primary_txs + inward_txs
        if stream_mode:
            # Sort chronologically to simulate streaming ingestion
            tx_to_process.sort(key=lambda x: x["timestamp"])

        # 3. Transform to pseudonymous edges
        transformed_edges = []
        last_in_ts: Dict[str, float] = {}  # token -> unix timestamp of most recent inbound credit

        for tx in tx_to_process:
            canonical_txn_id = tx["txn_id"][:-3] if tx["txn_id"].endswith("_IN") else tx["txn_id"]
            t_event = datetime.datetime.fromisoformat(tx["timestamp"].replace("Z", "+00:00"))
            event_unix = t_event.timestamp()

            # Tokenize endpoints
            src_tok = self.hsm.tokenize(
                account_id=tx["src_account_id"],
                epoch_id=active_epoch,
                requesting_bank_id=tx["source_bank_id"],
                as_of_ts=t_event
            )
            dst_tok = self.hsm.tokenize(
                account_id=tx["dst_account_id"],
                epoch_id=active_epoch,
                requesting_bank_id=tx["source_bank_id"],
                as_of_ts=t_event
            )

            # Store mapping inside local banks for reverse lookup:
            # 1. Source account -> source bank local_token_map
            src_bank = get_bank_for_account(tx["src_account_id"]) or tx["source_bank_id"]
            if src_bank in participating_banks and not tx["src_account_id"].endswith("_NPCI_INWARD"):
                bank_db = get_bank_db_path(src_bank, base_dir=banks_dir)
                if os.path.exists(bank_db):
                    conn_loc = sqlite3.connect(bank_db)
                    conn_loc.execute("""
                        INSERT OR IGNORE INTO local_token_map (token_hash, account_id, epoch_id, created_at)
                        VALUES (?, ?, ?, ?);
                    """, (src_tok, tx["src_account_id"], active_epoch, tx["timestamp"]))
                    conn_loc.commit()
                    conn_loc.close()

            # 2. Destination account -> destination bank local_token_map (CR02-B Fix)
            dst_bank = get_bank_for_account(tx["dst_account_id"])
            if dst_bank and dst_bank in participating_banks:
                dst_db = get_bank_db_path(dst_bank, base_dir=banks_dir)
                if os.path.exists(dst_db):
                    conn_dst = sqlite3.connect(dst_db)
                    conn_dst.execute("""
                        INSERT OR IGNORE INTO local_token_map (token_hash, account_id, epoch_id, created_at)
                        VALUES (?, ?, ?, ?);
                    """, (dst_tok, tx["dst_account_id"], active_epoch, tx["timestamp"]))
                    conn_dst.commit()
                    conn_dst.close()

            # Compute log amount: log(1 + Amount)
            log_amt = round(math.log(1.0 + float(tx["amount_inr"])), 4)

            # Compute delta_t relative to most recent INBOUND credit timestamp (CR02-B Fix)
            if src_tok in last_in_ts:
                delta_t = max(0.0, event_unix - last_in_ts[src_tok])
            else:
                delta_t = DEFAULT_NO_INFLOW_HOLD_TIME_SEC

            # Update last_in_ts for the receiving node only
            last_in_ts[dst_tok] = event_unix

            # Deterministic edge_id from canonical transaction ID (CR02-B Fix)
            edge_id = f"EDGE-{hashlib.sha256(canonical_txn_id.encode('utf-8')).hexdigest()[:16].upper()}"
            ingested_ts = datetime.datetime.now(datetime.timezone.utc).isoformat()

            transformed_edges.append((
                edge_id, src_tok, dst_tok, log_amt, delta_t,
                tx["channel"], tx["source_bank_id"], active_epoch,
                tx["timestamp"], ingested_ts
            ))

        # 4. Ingest into central risk_relay.db
        conn_c = self._get_central_connection()
        cur_c = conn_c.cursor()
        cur_c.executemany("""
            INSERT OR REPLACE INTO pseudonymous_edges (
                edge_id, src_token, dst_token, log_amount, delta_t_sec,
                channel_id, source_bank_id, epoch_id, event_ts, ingested_ts
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, transformed_edges)
        conn_c.commit()
        conn_c.close()

        print(f"[✔] Edge Pipeline: {len(transformed_edges):,} pseudonymous edges ingested into '{self.central_db_path}'.")
        return len(transformed_edges)
