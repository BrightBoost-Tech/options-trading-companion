"""
Tests for Observability v4: Lineage Signing and Verification

Tests:
- Canonicalization stability (same dict, different order = same hash)
- Signature verification (verify returns True for valid, False for tampered)
- DecisionLineageBuilder determinism (shuffled input order = stable hash)
- Integration patterns
"""

import pytest
import json
from unittest.mock import patch

from packages.quantum.observability.lineage import (
    LineageSigner,
    SignatureResult,
    get_code_sha,
    sign_payload,
    LINEAGE_VERSION,
)
from packages.quantum.services.decision_lineage_builder import DecisionLineageBuilder


# =============================================================================
# Canonicalization Tests
# =============================================================================

class TestCanonicalization:
    """Test that canonicalization produces stable output."""

    def test_same_dict_different_key_order_produces_same_bytes(self):
        """Dicts with same content but different key order should canonicalize identically."""
        dict1 = {"b": 2, "a": 1, "c": 3}
        dict2 = {"a": 1, "c": 3, "b": 2}
        dict3 = {"c": 3, "a": 1, "b": 2}

        bytes1 = LineageSigner.canonicalize(dict1)
        bytes2 = LineageSigner.canonicalize(dict2)
        bytes3 = LineageSigner.canonicalize(dict3)

        assert bytes1 == bytes2 == bytes3

    def test_nested_dict_canonicalization(self):
        """Nested dicts should also be canonicalized consistently."""
        dict1 = {"outer": {"b": 2, "a": 1}, "x": 10}
        dict2 = {"x": 10, "outer": {"a": 1, "b": 2}}

        bytes1 = LineageSigner.canonicalize(dict1)
        bytes2 = LineageSigner.canonicalize(dict2)

        assert bytes1 == bytes2

    def test_empty_dict_canonicalization(self):
        """Empty dict should canonicalize to '{}'."""
        result = LineageSigner.canonicalize({})
        assert result == b'{}'

    def test_none_input_canonicalization(self):
        """None input should be treated as empty dict."""
        result = LineageSigner.canonicalize(None)
        assert result == b'{}'

    def test_list_in_dict_canonicalization(self):
        """Lists in dicts should be preserved in order."""
        dict1 = {"items": [1, 2, 3], "name": "test"}
        dict2 = {"name": "test", "items": [1, 2, 3]}

        bytes1 = LineageSigner.canonicalize(dict1)
        bytes2 = LineageSigner.canonicalize(dict2)

        assert bytes1 == bytes2

    def test_special_characters_canonicalization(self):
        """Special characters should be handled consistently."""
        data = {"message": "Hello, world! \n\t\"quoted\""}
        result = LineageSigner.canonicalize(data)
        # Should be valid JSON
        assert b'"Hello, world!' in result


# =============================================================================
# Hash Stability Tests
# =============================================================================

class TestHashStability:
    """Test that hashing produces stable output."""

    def test_same_dict_produces_same_hash(self):
        """Same dict should always produce same hash."""
        data = {"strategy": "vertical_spread", "score": 75.5}

        hash1 = LineageSigner.compute_hash(data)
        hash2 = LineageSigner.compute_hash(data)

        assert hash1 == hash2

    def test_different_key_order_produces_same_hash(self):
        """Different key order should produce same hash."""
        dict1 = {"b": 2, "a": 1}
        dict2 = {"a": 1, "b": 2}

        hash1 = LineageSigner.compute_hash(dict1)
        hash2 = LineageSigner.compute_hash(dict2)

        assert hash1 == hash2

    def test_different_content_produces_different_hash(self):
        """Different content should produce different hash."""
        dict1 = {"value": 1}
        dict2 = {"value": 2}

        hash1 = LineageSigner.compute_hash(dict1)
        hash2 = LineageSigner.compute_hash(dict2)

        assert hash1 != hash2

    def test_hash_is_sha256_hex(self):
        """Hash should be 64-character hex string (SHA256)."""
        data = {"test": "data"}
        hash_val = LineageSigner.compute_hash(data)

        assert len(hash_val) == 64
        assert all(c in '0123456789abcdef' for c in hash_val)


# =============================================================================
# Signature Tests
# =============================================================================

class TestSignature:
    """Test signature generation and verification."""

    def test_sign_returns_signature_result(self):
        """sign() should return a SignatureResult."""
        data = {"test": "data"}

        with patch.dict("os.environ", {"OBSERVABILITY_HMAC_SECRET": "test-secret-32-chars-minimum-here"}):
            # Re-import to pick up patched env
            from packages.quantum.observability import lineage
            result = lineage.LineageSigner.sign(data)

            assert isinstance(result, SignatureResult)
            assert result.hash
            assert result.version == LINEAGE_VERSION

    def test_sign_without_secret_returns_unverified(self):
        """Sign without secret in non-prod should use dev secret."""
        data = {"test": "data"}

        with patch.dict("os.environ", {"OBSERVABILITY_HMAC_SECRET": "", "APP_ENV": "development"}):
            from packages.quantum.observability import lineage
            result = lineage.LineageSigner.sign(data)

            # In dev, uses dev secret so should be SIGNED
            assert result.status == "SIGNED"
            assert result.signature  # Should have a signature

    def test_verify_valid_signature(self):
        """verify() should return True for valid signature."""
        data = {"test": "data"}

        with patch.dict("os.environ", {"OBSERVABILITY_HMAC_SECRET": "test-secret-32-chars-minimum-here"}):
            from packages.quantum.observability import lineage
            result = lineage.LineageSigner.sign(data)
            is_valid = lineage.LineageSigner.verify(data, result.signature)

            assert is_valid is True

    def test_verify_tampered_data(self):
        """verify() should return False for tampered data."""
        original_data = {"test": "data"}
        tampered_data = {"test": "TAMPERED"}

        with patch.dict("os.environ", {"OBSERVABILITY_HMAC_SECRET": "test-secret-32-chars-minimum-here"}):
            from packages.quantum.observability import lineage
            result = lineage.LineageSigner.sign(original_data)
            is_valid = lineage.LineageSigner.verify(tampered_data, result.signature)

            assert is_valid is False

    def test_verify_invalid_signature(self):
        """verify() should return False for invalid signature."""
        data = {"test": "data"}

        with patch.dict("os.environ", {"OBSERVABILITY_HMAC_SECRET": "test-secret-32-chars-minimum-here"}):
            from packages.quantum.observability import lineage
            is_valid = lineage.LineageSigner.verify(data, "invalid-signature")

            assert is_valid is False

    def test_verify_empty_signature(self):
        """verify() should return False for empty signature."""
        data = {"test": "data"}

        with patch.dict("os.environ", {"OBSERVABILITY_HMAC_SECRET": "test-secret-32-chars-minimum-here"}):
            from packages.quantum.observability import lineage
            is_valid = lineage.LineageSigner.verify(data, "")

            assert is_valid is False


# =============================================================================
# Verify With Hash Tests
# =============================================================================

class TestVerifyWithHash:
    """Test verify_with_hash() functionality."""

    def test_verify_with_hash_valid(self):
        """Should return VERIFIED for valid data."""
        data = {"test": "data"}

        with patch.dict("os.environ", {"OBSERVABILITY_HMAC_SECRET": "test-secret-32-chars-minimum-here"}):
            from packages.quantum.observability import lineage
            result = lineage.LineageSigner.sign(data)

            is_valid, computed_hash, status = lineage.LineageSigner.verify_with_hash(
                stored_hash=result.hash,
                stored_signature=result.signature,
                data=data
            )

            assert is_valid is True
            assert computed_hash == result.hash
            assert status == "VERIFIED"

    def test_verify_with_hash_tampered_data(self):
        """Should return TAMPERED if data doesn't match stored hash."""
        original_data = {"test": "original"}
        tampered_data = {"test": "tampered"}

        with patch.dict("os.environ", {"OBSERVABILITY_HMAC_SECRET": "test-secret-32-chars-minimum-here"}):
            from packages.quantum.observability import lineage
            result = lineage.LineageSigner.sign(original_data)

            is_valid, computed_hash, status = lineage.LineageSigner.verify_with_hash(
                stored_hash=result.hash,
                stored_signature=result.signature,
                data=tampered_data
            )

            assert is_valid is False
            assert status == "TAMPERED"
            assert computed_hash != result.hash


# =============================================================================
# DecisionLineageBuilder Determinism Tests
# =============================================================================

class TestLineageBuilderDeterminism:
    """Test that DecisionLineageBuilder produces deterministic output."""

    def test_same_inputs_produce_same_hash(self):
        """Same inputs in same order should produce same hash."""
        builder1 = DecisionLineageBuilder()
        builder1.add_agent("AgentA", score=80)
        builder1.add_agent("AgentB", score=70)
        builder1.set_strategy("strategy_x")
        builder1.add_constraint("max_risk", 100)

        builder2 = DecisionLineageBuilder()
        builder2.add_agent("AgentA", score=80)
        builder2.add_agent("AgentB", score=70)
        builder2.set_strategy("strategy_x")
        builder2.add_constraint("max_risk", 100)

        lineage1 = builder1.build()
        lineage2 = builder2.build()

        hash1 = LineageSigner.compute_hash(lineage1)
        hash2 = LineageSigner.compute_hash(lineage2)

        assert hash1 == hash2

    def test_shuffled_agent_order_produces_same_hash(self):
        """Agents added in different order should produce same hash (sorted by name)."""
        builder1 = DecisionLineageBuilder()
        builder1.add_agent("Zebra", score=90)
        builder1.add_agent("Alpha", score=80)
        builder1.add_agent("Mike", score=70)

        builder2 = DecisionLineageBuilder()
        builder2.add_agent("Alpha", score=80)
        builder2.add_agent("Mike", score=70)
        builder2.add_agent("Zebra", score=90)

        lineage1 = builder1.build()
        lineage2 = builder2.build()

        hash1 = LineageSigner.compute_hash(lineage1)
        hash2 = LineageSigner.compute_hash(lineage2)

        assert hash1 == hash2

    def test_shuffled_constraint_order_produces_same_hash(self):
        """Constraints added in different order should produce same hash (sorted by key)."""
        builder1 = DecisionLineageBuilder()
        builder1.add_constraint("z_constraint", 1)
        builder1.add_constraint("a_constraint", 2)
        builder1.add_constraint("m_constraint", 3)

        builder2 = DecisionLineageBuilder()
        builder2.add_constraint("a_constraint", 2)
        builder2.add_constraint("m_constraint", 3)
        builder2.add_constraint("z_constraint", 1)

        lineage1 = builder1.build()
        lineage2 = builder2.build()

        hash1 = LineageSigner.compute_hash(lineage1)
        hash2 = LineageSigner.compute_hash(lineage2)

        assert hash1 == hash2

    def test_build_is_idempotent(self):
        """Calling build() multiple times should return same structure."""
        builder = DecisionLineageBuilder()
        builder.add_agent("AgentA", score=80)
        builder.set_strategy("strategy_x")

        lineage1 = builder.build()
        lineage2 = builder.build()

        # Should be equal dicts
        assert lineage1 == lineage2

        # Hashes should match
        hash1 = LineageSigner.compute_hash(lineage1)
        hash2 = LineageSigner.compute_hash(lineage2)
        assert hash1 == hash2


# =============================================================================
# Utility Function Tests
# =============================================================================

class TestUtilityFunctions:
    """Test utility functions."""

    def test_get_code_sha_returns_string(self):
        """get_code_sha() should return a string."""
        sha = get_code_sha()
        assert isinstance(sha, str)
        assert len(sha) > 0

    def test_get_code_sha_with_env(self):
        """get_code_sha() should use GIT_SHA if available."""
        with patch.dict("os.environ", {"GIT_SHA": "abc123def456"}):
            sha = get_code_sha()
            assert sha == "abc123def456"[:12]

    def test_sign_payload_returns_tuple(self):
        """sign_payload() should return (hash, signature) tuple."""
        payload = {"test": "data"}
        result = sign_payload(payload)

        assert isinstance(result, tuple)
        assert len(result) == 2
        hash_val, sig = result
        assert isinstance(hash_val, str)
        assert isinstance(sig, str)


# =============================================================================
# Integration Pattern Tests
# =============================================================================

class TestIntegrationPatterns:
    """Test common integration patterns."""

    def test_sign_and_verify_lineage_builder_output(self):
        """Full flow: build lineage -> sign -> verify."""
        # Build lineage
        builder = DecisionLineageBuilder()
        builder.add_agent("Scanner", score=85)
        builder.add_agent("SizingAgent", score=72)
        builder.set_strategy("vertical_spread")
        builder.set_sizing_source("SizingAgent")
        builder.add_constraint("max_risk_usd", 500)
        builder.add_constraint("regime", "elevated")

        lineage = builder.build()

        with patch.dict("os.environ", {"OBSERVABILITY_HMAC_SECRET": "test-secret-32-chars-minimum-here"}):
            from packages.quantum.observability import lineage as lineage_module

            # Sign
            sig_result = lineage_module.LineageSigner.sign(lineage)

            assert sig_result.status == "SIGNED"
            assert sig_result.hash
            assert sig_result.signature

            # Verify
            is_valid = lineage_module.LineageSigner.verify(lineage, sig_result.signature)
            assert is_valid is True

            # Verify with hash (full verification)
            is_valid, computed_hash, status = lineage_module.LineageSigner.verify_with_hash(
                stored_hash=sig_result.hash,
                stored_signature=sig_result.signature,
                data=lineage
            )
            assert is_valid is True
            assert status == "VERIFIED"
            assert computed_hash == sig_result.hash

    def test_detect_tampered_lineage(self):
        """Should detect if lineage was tampered after signing."""
        builder = DecisionLineageBuilder()
        builder.add_agent("Scanner", score=85)
        builder.set_strategy("vertical_spread")

        original_lineage = builder.build()

        with patch.dict("os.environ", {"OBSERVABILITY_HMAC_SECRET": "test-secret-32-chars-minimum-here"}):
            from packages.quantum.observability import lineage as lineage_module

            # Sign original
            sig_result = lineage_module.LineageSigner.sign(original_lineage)

            # Tamper with lineage
            tampered_lineage = original_lineage.copy()
            tampered_lineage["strategy_chosen"] = "TAMPERED_STRATEGY"

            # Verify should fail
            is_valid = lineage_module.LineageSigner.verify(tampered_lineage, sig_result.signature)
            assert is_valid is False

            # Verify with hash should return TAMPERED
            is_valid, computed_hash, status = lineage_module.LineageSigner.verify_with_hash(
                stored_hash=sig_result.hash,
                stored_signature=sig_result.signature,
                data=tampered_lineage
            )
            assert is_valid is False
            assert status == "TAMPERED"
