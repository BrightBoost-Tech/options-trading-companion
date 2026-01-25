"""
Observability v4: Cryptographic Lineage Signing & Verification

Provides deterministic canonicalization, SHA256 hashing, and HMAC-SHA256 signing
for decision lineage data. Enables tamper detection and integrity verification.

Usage:
    from packages.quantum.observability.lineage import LineageSigner

    # Sign lineage data
    lineage_dict = builder.build()
    signature_result = LineageSigner.sign(lineage_dict)
    # -> SignatureResult(hash="abc123...", signature="def456...", version="v4")

    # Verify lineage data
    is_valid = LineageSigner.verify(lineage_dict, signature_result.signature)

Security Notes:
    - OBSERVABILITY_HMAC_SECRET must be set in production
    - If missing in production, signing returns UNVERIFIED status
    - Wave 1.1: Dev signing requires ALLOW_DEV_SIGNING=true explicitly
    - Wave 1.1: Secrets read at runtime, not import time
"""

import hashlib
import hmac
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from packages.quantum.observability.canonical import canonical_json_bytes, compute_content_hash


# =============================================================================
# Configuration
# =============================================================================

# Version identifier for the signing scheme
LINEAGE_VERSION = "v4"

# Wave 1.1: Dev signing placeholder (only used when explicitly allowed)
_DEV_SECRET_PLACEHOLDER = b"dev-lineage-secret-do-not-use-in-production"


@dataclass
class SignatureResult:
    """Result of signing operation."""
    hash: str
    signature: str
    version: str = LINEAGE_VERSION
    status: str = "SIGNED"  # SIGNED, UNVERIFIED (no secret configured)


class LineageSignerError(Exception):
    """Error during lineage signing/verification."""
    pass


# =============================================================================
# Lineage Signer
# =============================================================================

class LineageSigner:
    """
    Cryptographic signing and verification for decision lineage data.

    Uses SHA256 for hashing and HMAC-SHA256 for signatures.
    Ensures deterministic canonicalization via sorted JSON.
    """

    @staticmethod
    def canonicalize(data: Dict[str, Any]) -> bytes:
        """
        Convert a dictionary to canonical bytes representation.

        Uses JSON with sorted keys and minimal separators to ensure
        the same logical dict always produces the same bytes.

        Args:
            data: Dictionary to canonicalize

        Returns:
            UTF-8 encoded bytes of the canonical JSON string
        """
        if data is None:
            data = {}
        return canonical_json_bytes(data)

    @staticmethod
    def compute_hash(data: Dict[str, Any]) -> str:
        """
        Compute SHA256 hash of canonicalized data.

        Args:
            data: Dictionary to hash

        Returns:
            Hex string of SHA256 hash
        """
        return compute_content_hash(data)

    @staticmethod
    def _get_secret() -> Optional[bytes]:
        """
        Get the HMAC secret, with production safety checks.

        Wave 1.1: Reads environment at runtime (not import time).
        Wave 1.1: Dev signing requires ALLOW_DEV_SIGNING=true explicitly.

        Returns:
            Secret as bytes, or None if not configured
        """
        # Wave 1.1: Read at runtime, not import time
        secret = os.getenv("OBSERVABILITY_HMAC_SECRET", "")
        app_env = os.getenv("APP_ENV", "development")
        is_production = app_env == "production"
        allow_dev_signing = os.getenv("ALLOW_DEV_SIGNING", "").lower() in ("true", "1", "yes")

        if not secret:
            if is_production:
                # In production, missing secret is a configuration error
                # Log warning but don't raise - allow unverified marking
                print("[LINEAGE] WARNING: OBSERVABILITY_HMAC_SECRET not configured in production")
                return None
            elif allow_dev_signing:
                # Wave 1.1: Only allow dev signing when explicitly enabled
                # This prevents silent signing with dev secret
                print("[LINEAGE] Using dev signing placeholder (ALLOW_DEV_SIGNING=true)")
                return _DEV_SECRET_PLACEHOLDER
            else:
                # Wave 1.1: No secret and dev signing not allowed -> UNVERIFIED
                print("[LINEAGE] WARNING: No secret configured and ALLOW_DEV_SIGNING not enabled")
                return None

        return secret.encode('utf-8')

    @staticmethod
    def sign(data: Dict[str, Any]) -> SignatureResult:
        """
        Sign lineage data with HMAC-SHA256.

        Args:
            data: Dictionary to sign (typically from DecisionLineageBuilder.build())

        Returns:
            SignatureResult with hash, signature, version, and status
        """
        # Compute hash
        data_hash = LineageSigner.compute_hash(data)

        # Get secret
        secret = LineageSigner._get_secret()

        if secret is None:
            # No secret configured - return unverified result
            return SignatureResult(
                hash=data_hash,
                signature="",
                version=LINEAGE_VERSION,
                status="UNVERIFIED"
            )

        # Compute HMAC-SHA256 signature over the hash
        signature = hmac.new(
            secret,
            data_hash.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        return SignatureResult(
            hash=data_hash,
            signature=signature,
            version=LINEAGE_VERSION,
            status="SIGNED"
        )

    @staticmethod
    def verify(data: Dict[str, Any], signature: str) -> bool:
        """
        Verify a signature against the data.

        Args:
            data: Dictionary that was signed
            signature: Signature to verify

        Returns:
            True if signature is valid, False otherwise
        """
        if not signature:
            return False

        secret = LineageSigner._get_secret()
        if secret is None:
            # Can't verify without secret
            return False

        # Recompute hash
        data_hash = LineageSigner.compute_hash(data)

        # Recompute expected signature
        expected_signature = hmac.new(
            secret,
            data_hash.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        # Constant-time comparison to prevent timing attacks
        return hmac.compare_digest(signature, expected_signature)

    @staticmethod
    def verify_with_hash(
        stored_hash: str,
        stored_signature: str,
        data: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, str, str]:
        """
        Verify signature with optional hash recomputation.

        Useful when you have stored hash and want to check both
        integrity (hash matches data) and authenticity (signature valid).

        Args:
            stored_hash: The stored hash value
            stored_signature: The stored signature
            data: Optional data to recompute hash (if None, only verifies signature)

        Returns:
            Tuple of (is_valid, computed_hash, status)
            status: "VERIFIED", "TAMPERED", or "UNVERIFIED"
        """
        secret = LineageSigner._get_secret()

        if secret is None:
            return (False, "", "UNVERIFIED")

        # If data provided, verify hash matches
        computed_hash = ""
        if data is not None:
            computed_hash = LineageSigner.compute_hash(data)
            if computed_hash != stored_hash:
                return (False, computed_hash, "TAMPERED")

        # Verify signature over the stored hash
        expected_signature = hmac.new(
            secret,
            stored_hash.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        if hmac.compare_digest(stored_signature or "", expected_signature):
            return (True, computed_hash or stored_hash, "VERIFIED")
        else:
            return (False, computed_hash or stored_hash, "TAMPERED")


# =============================================================================
# Utility Functions
# =============================================================================

def get_code_sha() -> str:
    """
    Get a stable code version identifier.

    Uses GIT_SHA env var if available, otherwise APP_VERSION.
    """
    git_sha = os.getenv("GIT_SHA", "")
    if git_sha:
        return git_sha[:12]  # Short SHA

    app_version = os.getenv("APP_VERSION", "unknown")
    return app_version


def sign_payload(payload: Dict[str, Any]) -> Tuple[str, str]:
    """
    Convenience function to sign any payload.

    Args:
        payload: Dictionary to sign

    Returns:
        Tuple of (payload_hash, payload_sig)
    """
    result = LineageSigner.sign(payload)
    return result.hash, result.signature
