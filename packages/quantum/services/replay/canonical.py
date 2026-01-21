"""
Canonical serialization and hashing utilities for deterministic replay.

Provides:
- canonical_json_bytes: Deterministic JSON serialization
- sha256_hex: SHA256 hash as hex string
- normalize_float: Deterministic float representation
- normalize_timestamp: Consistent timestamp formatting
"""

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Union

# Precision for float normalization (6 decimal places)
FLOAT_PRECISION = 6
DECIMAL_QUANTIZE = Decimal(10) ** -FLOAT_PRECISION


def normalize_float(value: Union[float, int, Decimal, None]) -> Union[str, None]:
    """
    Normalize a float to a deterministic string representation.

    Uses Decimal with quantize to ensure consistent rounding across platforms.
    Returns string to avoid JSON floating-point representation issues.

    Args:
        value: Float, int, Decimal, or None

    Returns:
        Normalized string representation (e.g., "123.456789") or None
    """
    if value is None:
        return None

    try:
        if isinstance(value, float):
            # Handle special float values
            if value != value:  # NaN check
                return "NaN"
            if value == float("inf"):
                return "Infinity"
            if value == float("-inf"):
                return "-Infinity"

            # Convert to Decimal for precise rounding
            d = Decimal(str(value))
        elif isinstance(value, Decimal):
            d = value
        elif isinstance(value, int):
            d = Decimal(value)
        else:
            d = Decimal(str(value))

        # Quantize to fixed precision
        normalized = d.quantize(DECIMAL_QUANTIZE, rounding=ROUND_HALF_UP)
        return str(normalized)

    except Exception:
        # Fallback for edge cases
        return str(value)


def normalize_timestamp(
    ts: Union[datetime, int, float, str, None]
) -> Union[int, None]:
    """
    Normalize timestamps to epoch milliseconds (integer).

    Accepts:
    - datetime objects (timezone-aware or naive, assumed UTC)
    - int/float (auto-detects seconds vs milliseconds vs nanoseconds)
    - ISO format strings

    Args:
        ts: Timestamp in various formats

    Returns:
        Epoch milliseconds as integer, or None
    """
    if ts is None:
        return None

    try:
        if isinstance(ts, datetime):
            # Convert to UTC if naive
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            return int(ts.timestamp() * 1000)

        if isinstance(ts, str):
            # Parse ISO format
            if ts.endswith("Z"):
                ts = ts[:-1] + "+00:00"
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1000)

        if isinstance(ts, (int, float)):
            # Auto-detect unit by magnitude
            # Current epoch (2024) is approximately:
            # - Nanoseconds: 1.7e18
            # - Microseconds: 1.7e15
            # - Milliseconds: 1.7e12
            # - Seconds: 1.7e9
            ts_num = float(ts)
            if ts_num > 1e17:  # Nanoseconds (> 10^17)
                return int(ts_num / 1e6)
            elif ts_num > 1e14:  # Microseconds (> 10^14)
                return int(ts_num / 1e3)
            elif ts_num > 1e11:  # Milliseconds (> 10^11)
                return int(ts_num)
            else:  # Seconds (<= 10^11)
                return int(ts_num * 1000)

    except Exception:
        pass

    return None


class CanonicalJSONEncoder(json.JSONEncoder):
    """
    JSON encoder that produces deterministic output.

    - Floats normalized to fixed precision strings
    - Timestamps normalized to epoch ms
    - Datetimes converted to ISO Z format
    - Decimals converted to normalized strings
    """

    def default(self, obj: Any) -> Any:
        if isinstance(obj, datetime):
            # Always use UTC and Z suffix
            if obj.tzinfo is None:
                obj = obj.replace(tzinfo=timezone.utc)
            return obj.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

        if isinstance(obj, Decimal):
            return normalize_float(obj)

        if isinstance(obj, bytes):
            # Base64 encode bytes
            import base64
            return base64.b64encode(obj).decode("ascii")

        if isinstance(obj, set):
            # Convert sets to sorted lists
            return sorted(list(obj), key=str)

        # Let the default encoder raise for unknown types
        return super().default(obj)


def _normalize_value(value: Any) -> Any:
    """
    Recursively normalize values for canonical JSON.

    - Dicts: sorted by key, values normalized
    - Lists: values normalized (order preserved)
    - Floats: normalized to string
    - Datetimes: ISO Z format
    """
    if isinstance(value, dict):
        return {k: _normalize_value(v) for k, v in sorted(value.items())}

    if isinstance(value, (list, tuple)):
        return [_normalize_value(v) for v in value]

    if isinstance(value, float):
        # Handle special values
        if value != value:  # NaN
            return "NaN"
        if value == float("inf"):
            return "Infinity"
        if value == float("-inf"):
            return "-Infinity"
        # Normalize to string for precision
        return normalize_float(value)

    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    if isinstance(value, Decimal):
        return normalize_float(value)

    if isinstance(value, set):
        return sorted([_normalize_value(v) for v in value], key=str)

    # Primitives (str, int, bool, None) pass through unchanged
    return value


def canonical_json_bytes(obj: Any) -> bytes:
    """
    Serialize object to canonical JSON bytes.

    Produces deterministic output suitable for hashing:
    - Keys sorted alphabetically (recursively)
    - No whitespace (compact separators)
    - Floats normalized to fixed precision strings
    - UTF-8 encoding

    Args:
        obj: Python object to serialize

    Returns:
        UTF-8 encoded JSON bytes
    """
    # Pre-normalize the object to handle floats consistently
    normalized = _normalize_value(obj)

    # Serialize with sorted keys and no whitespace
    json_str = json.dumps(
        normalized,
        cls=CanonicalJSONEncoder,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )

    return json_str.encode("utf-8")


def sha256_hex(data: bytes) -> str:
    """
    Compute SHA256 hash of bytes and return as hex string.

    Args:
        data: Bytes to hash

    Returns:
        64-character lowercase hex string
    """
    return hashlib.sha256(data).hexdigest()


def compute_content_hash(obj: Any) -> str:
    """
    Compute deterministic hash of a Python object.

    Combines canonical_json_bytes and sha256_hex for convenience.

    Args:
        obj: Python object to hash

    Returns:
        SHA256 hex string of canonical JSON representation
    """
    return sha256_hex(canonical_json_bytes(obj))


def compute_aggregate_hash(hashes: list[str], delimiter: str = "|") -> str:
    """
    Compute aggregate hash from multiple hashes.

    Used for input_hash (sorted blob hashes) and features_hash (sorted feature hashes).

    Args:
        hashes: List of hash strings
        delimiter: Separator between hashes (default: "|")

    Returns:
        SHA256 hex of delimited sorted hashes
    """
    if not hashes:
        return sha256_hex(b"")

    sorted_hashes = sorted(hashes)
    combined = delimiter.join(sorted_hashes)
    return sha256_hex(combined.encode("utf-8"))
