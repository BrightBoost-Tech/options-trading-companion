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
        """Wave 1.1: Sign without secret in non-prod requires ALLOW_DEV_SIGNING=true."""
        data = {"test": "data"}

        # Without ALLOW_DEV_SIGNING, should return UNVERIFIED
        with patch.dict("os.environ", {"OBSERVABILITY_HMAC_SECRET": "", "APP_ENV": "development", "ALLOW_DEV_SIGNING": ""}):
            from packages.quantum.observability import lineage
            result = lineage.LineageSigner.sign(data)

            # Wave 1.1: Without explicit ALLOW_DEV_SIGNING, should be UNVERIFIED
            assert result.status == "UNVERIFIED"
            assert result.signature == ""

        # With ALLOW_DEV_SIGNING=true, should work
        with patch.dict("os.environ", {"OBSERVABILITY_HMAC_SECRET": "", "APP_ENV": "development", "ALLOW_DEV_SIGNING": "true"}):
            from packages.quantum.observability import lineage
            result = lineage.LineageSigner.sign(data)

            # With explicit flag, should be SIGNED
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


# =============================================================================
# Wave 1.1 Tests: Runtime Secret Read
# =============================================================================

class TestWave11RuntimeSecretRead:
    """Wave 1.1: Test that secrets are read at runtime, not import time."""

    def test_secret_changes_are_picked_up_at_runtime(self):
        """Changing OBSERVABILITY_HMAC_SECRET should affect subsequent sign() calls."""
        data = {"test": "data"}

        # Sign with first secret
        with patch.dict("os.environ", {"OBSERVABILITY_HMAC_SECRET": "secret-one-32-chars-minimum-here"}):
            from packages.quantum.observability import lineage as lineage_module
            result1 = lineage_module.LineageSigner.sign(data)

        # Sign with different secret
        with patch.dict("os.environ", {"OBSERVABILITY_HMAC_SECRET": "secret-two-32-chars-minimum-here"}):
            from packages.quantum.observability import lineage as lineage_module
            result2 = lineage_module.LineageSigner.sign(data)

        # Same data, different secrets = different signatures
        assert result1.hash == result2.hash  # Hash is deterministic from data
        assert result1.signature != result2.signature  # Signature depends on secret

    def test_dev_signing_requires_explicit_flag(self):
        """Without ALLOW_DEV_SIGNING=true, no secret in dev should return UNVERIFIED."""
        data = {"test": "data"}

        # No secret, no explicit allow flag
        with patch.dict("os.environ", {"OBSERVABILITY_HMAC_SECRET": "", "APP_ENV": "development", "ALLOW_DEV_SIGNING": ""}):
            from packages.quantum.observability import lineage as lineage_module
            result = lineage_module.LineageSigner.sign(data)

            assert result.status == "UNVERIFIED"
            assert result.signature == ""

    def test_dev_signing_with_explicit_flag(self):
        """With ALLOW_DEV_SIGNING=true in dev, signing should succeed."""
        data = {"test": "data"}

        with patch.dict("os.environ", {"OBSERVABILITY_HMAC_SECRET": "", "APP_ENV": "development", "ALLOW_DEV_SIGNING": "true"}):
            from packages.quantum.observability import lineage as lineage_module
            result = lineage_module.LineageSigner.sign(data)

            assert result.status == "SIGNED"
            assert result.signature != ""

    def test_production_without_secret_returns_unverified(self):
        """In production, missing secret should return UNVERIFIED."""
        data = {"test": "data"}

        with patch.dict("os.environ", {"OBSERVABILITY_HMAC_SECRET": "", "APP_ENV": "production"}):
            from packages.quantum.observability import lineage as lineage_module
            result = lineage_module.LineageSigner.sign(data)

            assert result.status == "UNVERIFIED"
            assert result.signature == ""


# =============================================================================
# Wave 1.1 Tests: Event Key Determinism
# =============================================================================

class TestWave11EventKeyDeterminism:
    """Wave 1.1: Test event_key computation for idempotency."""

    def test_same_inputs_produce_same_event_key(self):
        """Same inputs should always produce the same event_key."""
        from packages.quantum.observability.audit_log_service import compute_event_key

        suggestion_id = "suggestion-123"
        trace_id = "trace-456"
        event_name = "suggestion_generated"
        payload_hash = "abcd1234"

        key1 = compute_event_key(suggestion_id, trace_id, event_name, payload_hash)
        key2 = compute_event_key(suggestion_id, trace_id, event_name, payload_hash)

        assert key1 == key2

    def test_event_key_is_sha256_hex(self):
        """event_key should be a 64-character hex string (SHA256)."""
        from packages.quantum.observability.audit_log_service import compute_event_key

        key = compute_event_key("suggestion-123", "trace-456", "event", "hash")

        assert len(key) == 64
        assert all(c in '0123456789abcdef' for c in key)

    def test_suggestion_scoped_event_key_ignores_payload_hash(self):
        """For suggestion-scoped events, different payload_hash = same event_key."""
        from packages.quantum.observability.audit_log_service import compute_event_key

        suggestion_id = "suggestion-123"
        event_name = "suggestion_generated"

        # Different payload hashes
        key1 = compute_event_key(suggestion_id, "trace-1", event_name, "hash-aaa")
        key2 = compute_event_key(suggestion_id, "trace-2", event_name, "hash-bbb")

        # Same key because suggestion_id + event_name determines it
        assert key1 == key2

    def test_trace_scoped_event_key_includes_payload_hash(self):
        """For trace-scoped events (no suggestion_id), payload_hash affects key."""
        from packages.quantum.observability.audit_log_service import compute_event_key

        trace_id = "trace-456"
        event_name = "some_event"

        # No suggestion_id, different payload hashes
        key1 = compute_event_key(None, trace_id, event_name, "hash-aaa")
        key2 = compute_event_key(None, trace_id, event_name, "hash-bbb")

        # Different keys because payload_hash is included
        assert key1 != key2

    def test_different_events_produce_different_keys(self):
        """Different event names should produce different keys."""
        from packages.quantum.observability.audit_log_service import compute_event_key

        suggestion_id = "suggestion-123"
        trace_id = "trace-456"
        payload_hash = "hash-123"

        key1 = compute_event_key(suggestion_id, trace_id, "event_a", payload_hash)
        key2 = compute_event_key(suggestion_id, trace_id, "event_b", payload_hash)

        assert key1 != key2


# =============================================================================
# Wave 1.1 Tests: Payload Hash Verification
# =============================================================================

class TestWave11PayloadHashVerification:
    """Wave 1.1: Test that verification checks both hash AND signature."""

    def test_verify_with_hash_detects_hash_mismatch(self):
        """verify_with_hash should detect when stored hash doesn't match computed hash."""
        data = {"test": "data"}
        wrong_hash = "0" * 64  # Wrong hash

        with patch.dict("os.environ", {"OBSERVABILITY_HMAC_SECRET": "test-secret-32-chars-minimum-here"}):
            from packages.quantum.observability import lineage as lineage_module

            # Sign the data to get a valid signature
            result = lineage_module.LineageSigner.sign(data)

            # Verify with wrong stored hash
            is_valid, computed_hash, status = lineage_module.LineageSigner.verify_with_hash(
                stored_hash=wrong_hash,
                stored_signature=result.signature,
                data=data
            )

            assert is_valid is False
            assert status == "TAMPERED"
            assert computed_hash != wrong_hash

    def test_verify_with_hash_detects_signature_failure(self):
        """verify_with_hash should detect invalid signature even if hash matches."""
        data = {"test": "data"}

        with patch.dict("os.environ", {"OBSERVABILITY_HMAC_SECRET": "test-secret-32-chars-minimum-here"}):
            from packages.quantum.observability import lineage as lineage_module

            # Compute correct hash
            correct_hash = lineage_module.LineageSigner.compute_hash(data)

            # Verify with correct hash but wrong signature
            is_valid, computed_hash, status = lineage_module.LineageSigner.verify_with_hash(
                stored_hash=correct_hash,
                stored_signature="invalid-signature",
                data=data
            )

            assert is_valid is False
            assert status == "TAMPERED"
            assert computed_hash == correct_hash

    def test_verify_with_hash_returns_verified_for_valid_data(self):
        """verify_with_hash should return VERIFIED when both hash and signature match."""
        data = {"test": "data"}

        with patch.dict("os.environ", {"OBSERVABILITY_HMAC_SECRET": "test-secret-32-chars-minimum-here"}):
            from packages.quantum.observability import lineage as lineage_module

            result = lineage_module.LineageSigner.sign(data)

            is_valid, computed_hash, status = lineage_module.LineageSigner.verify_with_hash(
                stored_hash=result.hash,
                stored_signature=result.signature,
                data=data
            )

            assert is_valid is True
            assert status == "VERIFIED"
            assert computed_hash == result.hash


# =============================================================================
# Wave 1.1 Tests: AuditLogService Strengthened Verification
# =============================================================================

class TestWave11AuditLogServiceVerification:
    """Wave 1.1: Test strengthened verify_audit_event behavior."""

    def test_verify_audit_event_returns_dict_with_status(self):
        """verify_audit_event should return a dict with detailed verification info."""
        from packages.quantum.observability.audit_log_service import AuditLogService

        audit_service = AuditLogService(None)

        # Mock event with valid fields
        with patch.dict("os.environ", {"OBSERVABILITY_HMAC_SECRET": "test-secret-32-chars-minimum-here"}):
            from packages.quantum.observability.lineage import sign_payload

            payload = {"test": "data"}
            payload_hash, payload_sig = sign_payload(payload)

            event = {
                "payload": payload,
                "payload_hash": payload_hash,
                "payload_sig": payload_sig
            }

            result = audit_service.verify_audit_event(event)

            assert isinstance(result, dict)
            assert "valid" in result
            assert "status" in result
            assert "stored_hash" in result
            assert "computed_hash" in result
            assert "signature_checked" in result

    def test_verify_audit_event_returns_unverified_for_missing_fields(self):
        """verify_audit_event should return UNVERIFIED when hash/sig are missing."""
        from packages.quantum.observability.audit_log_service import AuditLogService

        audit_service = AuditLogService(None)

        # Event with missing signature fields
        event = {
            "payload": {"test": "data"},
            "payload_hash": "",
            "payload_sig": ""
        }

        result = audit_service.verify_audit_event(event)

        assert result["valid"] is False
        assert result["status"] == "UNVERIFIED"

    def test_verify_audit_event_simple_returns_boolean(self):
        """verify_audit_event_simple should return a simple boolean."""
        from packages.quantum.observability.audit_log_service import AuditLogService

        audit_service = AuditLogService(None)

        event = {
            "payload": {"test": "data"},
            "payload_hash": "",
            "payload_sig": ""
        }

        result = audit_service.verify_audit_event_simple(event)

        assert isinstance(result, bool)
        assert result is False


# =============================================================================
# Wave 1.2 Tests: Analytics Event Key Determinism
# =============================================================================

class TestWave12AnalyticsEventKeyDeterminism:
    """Wave 1.2: Test analytics event_key computation for idempotency."""

    def test_same_inputs_produce_same_analytics_event_key(self):
        """Same inputs should always produce the same event_key."""
        from packages.quantum.services.analytics_service import compute_analytics_event_key

        event_name = "suggestion_generated"
        suggestion_id = "suggestion-123"
        trace_id = "trace-456"
        timestamp = "2026-01-18T12:00:00Z"

        key1 = compute_analytics_event_key(event_name, suggestion_id, trace_id, timestamp)
        key2 = compute_analytics_event_key(event_name, suggestion_id, trace_id, timestamp)

        assert key1 == key2

    def test_analytics_event_key_is_sha256_hex(self):
        """event_key should be a 64-character hex string (SHA256)."""
        from packages.quantum.services.analytics_service import compute_analytics_event_key

        key = compute_analytics_event_key("event", "suggestion-123", "trace-456", "2026-01-18T12:00:00Z")

        assert len(key) == 64
        assert all(c in '0123456789abcdef' for c in key)

    def test_suggestion_scoped_analytics_key_ignores_timestamp(self):
        """For suggestion-scoped events, different timestamps = same event_key."""
        from packages.quantum.services.analytics_service import compute_analytics_event_key

        suggestion_id = "suggestion-123"
        event_name = "suggestion_generated"

        # Different timestamps
        key1 = compute_analytics_event_key(event_name, suggestion_id, "trace-1", "2026-01-18T12:00:00Z")
        key2 = compute_analytics_event_key(event_name, suggestion_id, "trace-2", "2026-01-18T13:00:00Z")

        # Same key because suggestion_id + event_name determines it
        assert key1 == key2

    def test_trace_scoped_analytics_key_includes_timestamp(self):
        """For trace-scoped events (no suggestion_id), timestamp affects key."""
        from packages.quantum.services.analytics_service import compute_analytics_event_key

        trace_id = "trace-456"
        event_name = "some_event"

        # No suggestion_id, different timestamps
        key1 = compute_analytics_event_key(event_name, None, trace_id, "2026-01-18T12:00:00Z")
        key2 = compute_analytics_event_key(event_name, None, trace_id, "2026-01-18T13:00:00Z")

        # Different keys because timestamp is included
        assert key1 != key2

    def test_different_events_produce_different_analytics_keys(self):
        """Different event names should produce different keys."""
        from packages.quantum.services.analytics_service import compute_analytics_event_key

        suggestion_id = "suggestion-123"
        timestamp = "2026-01-18T12:00:00Z"

        key1 = compute_analytics_event_key("event_a", suggestion_id, "trace", timestamp)
        key2 = compute_analytics_event_key("event_b", suggestion_id, "trace", timestamp)

        assert key1 != key2


# =============================================================================
# Wave 1.2 Tests: Insert-Idempotent Suggestion Helper
# =============================================================================

class TestWave12InsertOrGetSuggestion:
    """Wave 1.2: Test insert_or_get_suggestion helper."""

    def test_insert_or_get_suggestion_exists_as_function(self):
        """Verify insert_or_get_suggestion function exists and is callable."""
        from packages.quantum.services.workflow_orchestrator import insert_or_get_suggestion

        assert callable(insert_or_get_suggestion)

    def test_insert_or_get_suggestion_signature(self):
        """Verify function accepts expected parameters."""
        from packages.quantum.services.workflow_orchestrator import insert_or_get_suggestion
        import inspect

        sig = inspect.signature(insert_or_get_suggestion)
        params = list(sig.parameters.keys())

        assert "supabase" in params
        assert "suggestion" in params
        assert "unique_fields" in params


# =============================================================================
# Wave 1.2 Tests: Paper Execution Stage Analytics
# =============================================================================

class TestWave12PaperStageAnalytics:
    """Wave 1.2: Test that stage_order emits analytics events."""

    def test_paper_execution_service_imports_analytics(self):
        """Verify PaperExecutionService has access to AnalyticsService."""
        from packages.quantum.services.paper_execution_service import PaperExecutionService, AnalyticsService

        # If import succeeds, AnalyticsService is available
        assert AnalyticsService is not None

    def test_paper_execution_service_has_stage_order(self):
        """Verify stage_order method exists."""
        from packages.quantum.services.paper_execution_service import PaperExecutionService

        assert hasattr(PaperExecutionService, 'stage_order')
        assert callable(getattr(PaperExecutionService, 'stage_order'))
