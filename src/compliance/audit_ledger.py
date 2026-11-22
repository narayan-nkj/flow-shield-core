"""Append-only cryptographic hash-chained audit ledger module.

Guarantees non-repudiation using SHA-256 hash chains:
    row_hash = SHA256(prev_hash || payload_json)
Where payload_json uses sorted keys and UTF-8 encoding.
"""
