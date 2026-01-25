"""
Canonical serialization and hashing utilities for deterministic replay.

Refactored to re-export from packages.quantum.observability.canonical.
This ensures backward compatibility while unifying the implementation.
"""

from packages.quantum.observability.canonical import (
    canonical_json_bytes,
    compute_content_hash,
    compute_aggregate_hash,
    normalize_float,
    normalize_timestamp,
    sha256_hex,
    CanonicalJSONEncoder,
)

__all__ = [
    "canonical_json_bytes",
    "compute_content_hash",
    "compute_aggregate_hash",
    "normalize_float",
    "normalize_timestamp",
    "sha256_hex",
    "CanonicalJSONEncoder",
]
