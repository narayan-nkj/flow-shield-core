"""Bank ID and entity identifier normalization utilities for CHAKRA-DPI.

Ensures consistent handling of canonical bank IDs across in-memory data
structures, databases, and filesystem storage paths.
"""

from pathlib import Path


def normalize_bank_id(bank_id: str) -> str:
    """Normalize a bank identifier to its canonical uppercase string.

    Example:
        'bank_a' -> 'BANK_A'
        ' BANK_B ' -> 'BANK_B'
    """
    if not bank_id or not isinstance(bank_id, str):
        raise ValueError(f"Invalid bank_id: {bank_id}. Must be a non-empty string.")
    return bank_id.strip().upper()


def get_bank_filename(bank_id: str) -> str:
    """Return the filesystem database filename for a given bank identifier.

    Enforces lowercase naming conventions on disk to maintain cross-platform
    filesystem portability.

    Example:
        'BANK_A' -> 'bank_a.db'
        'bank_b' -> 'bank_b.db'
    """
    canonical_id = normalize_bank_id(bank_id)
    return f"{canonical_id.lower()}.db"


def get_bank_db_path(bank_id: str, base_dir: str = "data/banks") -> str:
    """Return the relative path to the SQLite database file for a bank.

    Example:
        get_bank_db_path('BANK_A') -> 'data/banks/bank_a.db'
    """
    filename = get_bank_filename(bank_id)
    return str(Path(base_dir) / filename)


def bank_id_from_filename(filename: str) -> str:
    """Extract canonical uppercase bank ID from a database filename or path.

    Example:
        'bank_a.db' -> 'BANK_A'
        'data/banks/bank_c.db' -> 'BANK_C'
    """
    path = Path(filename)
    stem = path.stem
    return normalize_bank_id(stem)
