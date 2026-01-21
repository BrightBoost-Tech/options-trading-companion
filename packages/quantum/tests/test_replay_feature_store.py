"""
Tests for Replay Feature Store v4.

Tests:
1. Canonical hashing produces deterministic output
2. BlobStore deduplication works correctly
3. DecisionContext collects inputs and features
4. ReplayTruthLayer serves stored data correctly
5. Golden replay test: full cycle produces identical hashes
"""

import gzip
import json
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

# Set REPLAY_ENABLE before imports
os.environ["REPLAY_ENABLE"] = "1"


class TestCanonicalHashing(unittest.TestCase):
    """Tests for canonical.py hashing utilities."""

    def test_canonical_json_bytes_deterministic(self):
        """Same object always produces same bytes."""
        from packages.quantum.services.replay.canonical import canonical_json_bytes

        obj = {"z": 1, "a": 2, "m": [3, 1, 2]}

        # Multiple calls should produce identical bytes
        bytes1 = canonical_json_bytes(obj)
        bytes2 = canonical_json_bytes(obj)

        self.assertEqual(bytes1, bytes2)

    def test_canonical_json_bytes_sorted_keys(self):
        """Keys are sorted alphabetically."""
        from packages.quantum.services.replay.canonical import canonical_json_bytes

        obj = {"z": 1, "a": 2, "m": 3}
        result = canonical_json_bytes(obj)

        # Should start with "a" key
        self.assertTrue(result.startswith(b'{"a":'))

    def test_normalize_float_precision(self):
        """Floats are normalized to fixed precision."""
        from packages.quantum.services.replay.canonical import normalize_float

        # Should round to 6 decimal places
        result = normalize_float(1.23456789)
        self.assertEqual(result, "1.234568")

        # Integer should work too
        result = normalize_float(42)
        self.assertEqual(result, "42.000000")

    def test_normalize_float_special_values(self):
        """Special float values handled correctly."""
        from packages.quantum.services.replay.canonical import normalize_float

        self.assertEqual(normalize_float(float("inf")), "Infinity")
        self.assertEqual(normalize_float(float("-inf")), "-Infinity")
        self.assertEqual(normalize_float(float("nan")), "NaN")
        self.assertIsNone(normalize_float(None))

    def test_normalize_timestamp_various_formats(self):
        """Timestamps normalized from various formats."""
        from packages.quantum.services.replay.canonical import normalize_timestamp

        # Datetime
        dt = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        result = normalize_timestamp(dt)
        self.assertIsInstance(result, int)

        # Milliseconds
        result = normalize_timestamp(1705314600000)
        self.assertEqual(result, 1705314600000)

        # Seconds
        result = normalize_timestamp(1705314600)
        self.assertEqual(result, 1705314600000)

    def test_sha256_hex_format(self):
        """SHA256 returns 64-char lowercase hex."""
        from packages.quantum.services.replay.canonical import sha256_hex

        result = sha256_hex(b"test data")

        self.assertEqual(len(result), 64)
        self.assertTrue(all(c in "0123456789abcdef" for c in result))

    def test_compute_aggregate_hash_sorted(self):
        """Aggregate hash is computed from sorted inputs."""
        from packages.quantum.services.replay.canonical import compute_aggregate_hash

        hashes = ["zzz", "aaa", "mmm"]
        result1 = compute_aggregate_hash(hashes)

        # Different order should produce same result
        hashes_reordered = ["mmm", "zzz", "aaa"]
        result2 = compute_aggregate_hash(hashes_reordered)

        self.assertEqual(result1, result2)


class TestBlobStore(unittest.TestCase):
    """Tests for BlobStore content-addressable storage."""

    def test_put_returns_hash(self):
        """put() returns deterministic hash."""
        from packages.quantum.services.replay.blob_store import BlobStore

        store = BlobStore()
        obj = {"symbol": "SPY", "price": 500.0}

        hash1, _, _ = store.put(obj)
        hash2, _, _ = store.put(obj)

        # Same object should get same hash
        self.assertEqual(hash1, hash2)
        self.assertEqual(len(hash1), 64)

    def test_put_different_objects_different_hashes(self):
        """Different objects get different hashes."""
        from packages.quantum.services.replay.blob_store import BlobStore

        store = BlobStore()

        hash1, _, _ = store.put({"a": 1})
        hash2, _, _ = store.put({"a": 2})

        self.assertNotEqual(hash1, hash2)

    def test_put_compresses_data(self):
        """put() compresses the payload."""
        from packages.quantum.services.replay.blob_store import BlobStore

        store = BlobStore()
        obj = {"data": "x" * 1000}  # Compressible data

        _, compressed, uncompressed_size = store.put(obj)

        # Compressed should be smaller
        self.assertLess(len(compressed), uncompressed_size)

        # Should be valid gzip
        decompressed = gzip.decompress(compressed)
        self.assertGreater(len(decompressed), 0)

    def test_pending_blobs_tracked(self):
        """Pending blobs are tracked for later commit."""
        from packages.quantum.services.replay.blob_store import BlobStore

        store = BlobStore()
        store.clear_pending()

        store.put({"a": 1})
        store.put({"b": 2})

        pending = store.get_pending_hashes()
        self.assertEqual(len(pending), 2)

    def test_duplicate_not_added_to_pending(self):
        """Same blob is not added to pending twice."""
        from packages.quantum.services.replay.blob_store import BlobStore

        store = BlobStore()
        store.clear_pending()

        store.put({"a": 1})
        store.put({"a": 1})  # Duplicate

        pending = store.get_pending_hashes()
        self.assertEqual(len(pending), 1)

    def test_persisted_cache_only_after_commit(self):
        """Blobs only marked as persisted after successful commit."""
        from packages.quantum.services.replay.blob_store import BlobStore

        store = BlobStore()
        store.clear_pending()
        store.clear_persisted_cache()

        hash1, _, _ = store.put({"test": "data"})

        # Before commit: not persisted
        self.assertFalse(store.is_persisted(hash1))
        self.assertEqual(len(store.get_pending_hashes()), 1)

        # Mock successful commit
        mock_client = MagicMock()
        mock_client.table.return_value.upsert.return_value.execute.return_value = MagicMock(data=[{}])

        store.commit(mock_client)

        # After commit: persisted and no pending
        self.assertTrue(store.is_persisted(hash1))
        self.assertEqual(len(store.get_pending_hashes()), 0)

    def test_already_persisted_not_readded_to_pending(self):
        """Blobs already persisted are not re-added to pending."""
        from packages.quantum.services.replay.blob_store import BlobStore

        store = BlobStore()
        store.clear_pending()
        store.clear_persisted_cache()

        # First put - goes to pending
        hash1, _, _ = store.put({"test": "data"})
        self.assertEqual(len(store.get_pending_hashes()), 1)

        # Mock commit to mark as persisted
        mock_client = MagicMock()
        mock_client.table.return_value.upsert.return_value.execute.return_value = MagicMock(data=[{}])
        store.commit(mock_client)

        # Second put of same object - should not go to pending
        hash2, _, _ = store.put({"test": "data"})
        self.assertEqual(hash1, hash2)
        self.assertEqual(len(store.get_pending_hashes()), 0)


class TestDecisionContext(unittest.TestCase):
    """Tests for DecisionContext context manager."""

    def test_context_enters_and_exits(self):
        """Context manager enters and exits cleanly."""
        from packages.quantum.services.replay.decision_context import (
            DecisionContext,
            get_current_decision_context,
        )

        with DecisionContext(
            strategy_name="test",
            as_of_ts=datetime.now(timezone.utc)
        ) as ctx:
            self.assertIsNotNone(ctx)
            self.assertEqual(get_current_decision_context(), ctx)

        # After exit, context should be cleared
        self.assertIsNone(get_current_decision_context())

    def test_record_input_computes_hash(self):
        """record_input() computes and returns blob hash."""
        from packages.quantum.services.replay.decision_context import DecisionContext

        with DecisionContext(
            strategy_name="test",
            as_of_ts=datetime.now(timezone.utc)
        ) as ctx:
            blob_hash = ctx.record_input(
                key="SPY:polygon:snapshot_v4",
                snapshot_type="quote",
                payload={"symbol": "SPY", "price": 500.0},
                metadata={"provider": "polygon"}
            )

            self.assertEqual(len(blob_hash), 64)
            self.assertEqual(len(ctx.inputs), 1)

    def test_record_feature_computes_hash(self):
        """record_feature() computes and stores features hash."""
        from packages.quantum.services.replay.decision_context import DecisionContext

        with DecisionContext(
            strategy_name="test",
            as_of_ts=datetime.now(timezone.utc)
        ) as ctx:
            features_hash = ctx.record_feature(
                symbol="SPY",
                namespace="regime_features",
                features={"iv_rank": 50.0, "trend": "UP"}
            )

            self.assertEqual(len(features_hash), 64)
            self.assertEqual(len(ctx.features), 1)

    def test_get_input_hash_deterministic(self):
        """Input hash is deterministic."""
        from packages.quantum.services.replay.decision_context import DecisionContext

        with DecisionContext(
            strategy_name="test",
            as_of_ts=datetime.now(timezone.utc)
        ) as ctx1:
            ctx1.record_input("key1", "quote", {"a": 1})
            ctx1.record_input("key2", "quote", {"b": 2})
            hash1 = ctx1.get_input_hash()

        with DecisionContext(
            strategy_name="test",
            as_of_ts=datetime.now(timezone.utc)
        ) as ctx2:
            # Same inputs in different order
            ctx2.record_input("key2", "quote", {"b": 2})
            ctx2.record_input("key1", "quote", {"a": 1})
            hash2 = ctx2.get_input_hash()

        # Sorted hashes should produce same aggregate
        self.assertEqual(hash1, hash2)

    @patch("packages.quantum.services.replay.blob_store.BlobStore.commit")
    def test_commit_writes_to_db(self, mock_blob_commit):
        """commit() writes decision data to database (via fallback)."""
        from packages.quantum.services.replay.decision_context import DecisionContext

        mock_client = MagicMock()
        # RPC fails, so it falls back to sequential insert
        mock_client.rpc.side_effect = Exception("RPC not available")
        mock_client.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[{}])
        mock_blob_commit.return_value = 1

        with DecisionContext(
            strategy_name="test",
            as_of_ts=datetime.now(timezone.utc)
        ) as ctx:
            ctx.record_input("key1", "quote", {"a": 1})
            ctx.record_feature("SPY", "regime", {"iv": 50})

            result = ctx.commit(mock_client, status="ok")

        self.assertEqual(result["status"], "ok")
        self.assertGreaterEqual(result["inputs_count"], 0)

        # Verify DB calls were made (via sequential fallback)
        mock_client.table.assert_called()

    @patch("packages.quantum.services.replay.blob_store.BlobStore.commit")
    def test_commit_tries_rpc_first(self, mock_blob_commit):
        """commit() tries RPC atomic commit before falling back."""
        from packages.quantum.services.replay.decision_context import DecisionContext

        mock_client = MagicMock()
        mock_blob_commit.return_value = 1

        # Mock RPC success
        mock_client.rpc.return_value.execute.return_value = MagicMock(data={"status": "inserted"})

        with DecisionContext(
            strategy_name="test_rpc",
            as_of_ts=datetime.now(timezone.utc)
        ) as ctx:
            ctx.record_input("key1", "quote", {"a": 1})
            result = ctx.commit(mock_client, status="ok")

        # RPC should have been called
        mock_client.rpc.assert_called_once()
        self.assertEqual(result.get("commit_method"), "rpc")

    @patch("packages.quantum.services.replay.blob_store.BlobStore.commit")
    def test_commit_falls_back_on_rpc_failure(self, mock_blob_commit):
        """commit() falls back to sequential on RPC failure."""
        from packages.quantum.services.replay.decision_context import DecisionContext

        mock_client = MagicMock()
        mock_blob_commit.return_value = 1

        # Mock RPC failure
        mock_client.rpc.side_effect = Exception("RPC not available")
        mock_client.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[{}])

        with DecisionContext(
            strategy_name="test_fallback",
            as_of_ts=datetime.now(timezone.utc)
        ) as ctx:
            ctx.record_input("key1", "quote", {"a": 1})
            result = ctx.commit(mock_client, status="ok")

        # Should have fallen back to sequential
        self.assertEqual(result.get("commit_method"), "sequential")
        mock_client.table.assert_called()


class TestReplayTruthLayer(unittest.TestCase):
    """Tests for ReplayTruthLayer."""

    def test_from_decision_id_returns_none_on_missing(self):
        """from_decision_id returns None if decision not found."""
        from packages.quantum.services.replay.replay_truth_layer import ReplayTruthLayer

        mock_client = MagicMock()
        mock_client.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(data=None)

        result = ReplayTruthLayer.from_decision_id(mock_client, "missing-id")
        self.assertIsNone(result)

    def test_get_stored_input_returns_payload(self):
        """get_stored_input returns stored payload."""
        from packages.quantum.services.replay.replay_truth_layer import ReplayTruthLayer

        # Create instance directly with mock data
        layer = ReplayTruthLayer(
            decision_id="test-id",
            decision_run={"strategy_name": "test"},
            inputs=[{
                "key": "SPY:polygon:snapshot_v4",
                "snapshot_type": "quote",
                "blob_hash": "abc123",
                "metadata": {"provider": "polygon"}
            }],
            features=[],
            supabase=None,
        )

        # Pre-populate blob cache
        layer.blobs_cache["abc123"] = {"symbol": "SPY", "price": 500.0}

        result = layer.get_stored_input("SPY:polygon:snapshot_v4", "quote")

        self.assertIsNotNone(result)
        self.assertEqual(result["payload"]["symbol"], "SPY")

    def test_get_stored_feature_returns_features(self):
        """get_stored_feature returns stored features."""
        from packages.quantum.services.replay.replay_truth_layer import ReplayTruthLayer

        layer = ReplayTruthLayer(
            decision_id="test-id",
            decision_run={"strategy_name": "test"},
            inputs=[],
            features=[{
                "symbol": "SPY",
                "namespace": "regime_features",
                "features": {"iv_rank": 50.0},
                "features_hash": "hash123"
            }],
            supabase=None,
        )

        result = layer.get_stored_feature("SPY", "regime_features")

        self.assertIsNotNone(result)
        self.assertEqual(result["features"]["iv_rank"], 50.0)

    def test_rates_divs_returns_stored_payload(self):
        """rates_divs() returns stored rates/divs payload."""
        from packages.quantum.services.replay.replay_truth_layer import ReplayTruthLayer

        layer = ReplayTruthLayer(
            decision_id="test-id",
            decision_run={"strategy_name": "test"},
            inputs=[{
                "key": "SPY:rates_divs:2024-01-15",
                "snapshot_type": "rates_divs",
                "blob_hash": "rates123",
                "metadata": {}
            }],
            features=[],
            supabase=None,
        )

        # Pre-populate blob cache
        layer.blobs_cache["rates123"] = {
            "risk_free_rate": 0.05,
            "dividend_yield": 0.015
        }

        result = layer.rates_divs("SPY", datetime(2024, 1, 15))

        self.assertIsNotNone(result)
        self.assertEqual(result["risk_free_rate"], 0.05)
        self.assertEqual(result["dividend_yield"], 0.015)

    def test_rates_divs_returns_fallback_when_missing(self):
        """rates_divs() returns default when no stored data."""
        from packages.quantum.services.replay.replay_truth_layer import ReplayTruthLayer

        layer = ReplayTruthLayer(
            decision_id="test-id",
            decision_run={"strategy_name": "test"},
            inputs=[],
            features=[],
            supabase=None,
        )

        result = layer.rates_divs("MISSING", datetime(2024, 1, 15))

        self.assertEqual(result["risk_free_rate"], None)
        self.assertEqual(result["dividend_yield"], None)

    def test_surface_snapshot_returns_stored_payload(self):
        """surface_snapshot() returns stored surface data."""
        from packages.quantum.services.replay.replay_truth_layer import ReplayTruthLayer

        layer = ReplayTruthLayer(
            decision_id="test-id",
            decision_run={"strategy_name": "test"},
            inputs=[{
                "key": "SPY:surface:v1",
                "snapshot_type": "surface",
                "blob_hash": "surface123",
                "metadata": {}
            }],
            features=[],
            supabase=None,
        )

        # Pre-populate blob cache
        layer.blobs_cache["surface123"] = {
            "symbol": "SPY",
            "atm_iv_30d": 0.18,
            "skew_25d": -0.05,
            "iv_rank": 45.0
        }

        result = layer.surface_snapshot("SPY")

        self.assertIsNotNone(result)
        self.assertEqual(result["atm_iv_30d"], 0.18)
        self.assertEqual(result["iv_rank"], 45.0)

    def test_surface_snapshot_returns_none_when_missing(self):
        """surface_snapshot() returns None when no stored data."""
        from packages.quantum.services.replay.replay_truth_layer import ReplayTruthLayer

        layer = ReplayTruthLayer(
            decision_id="test-id",
            decision_run={"strategy_name": "test"},
            inputs=[],
            features=[],
            supabase=None,
        )

        result = layer.surface_snapshot("MISSING")

        self.assertIsNone(result)


class TestGoldenReplay(unittest.TestCase):
    """Golden replay test: verify deterministic replay."""

    def test_golden_replay_produces_identical_hashes(self):
        """
        Full cycle: create context -> record inputs/features -> verify replay.

        This is the key determinism test.
        """
        from packages.quantum.services.replay.decision_context import DecisionContext
        from packages.quantum.services.replay.canonical import compute_content_hash

        # Simulate a decision cycle
        test_snapshot = {
            "symbol": "SPY",
            "quote": {"bid": 499.0, "ask": 501.0, "mid": 500.0},
            "timestamps": {"source_ts": 1705314600000, "received_ts": 1705314601000},
        }
        test_features = {
            "iv_rank": 50.0,
            "trend_score": 0.5,
            "vol_score": -0.2,
        }

        # First run
        with DecisionContext(
            strategy_name="golden_test",
            as_of_ts=datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        ) as ctx1:
            ctx1.record_input(
                key="SPY:polygon:snapshot_v4",
                snapshot_type="quote",
                payload=test_snapshot,
                metadata={"quality": {"score": 100}}
            )
            ctx1.record_feature("__global__", "regime_features", test_features)

            input_hash_1 = ctx1.get_input_hash()
            features_hash_1 = ctx1.get_features_hash()

        # Second run with identical inputs (simulating replay)
        with DecisionContext(
            strategy_name="golden_test",
            as_of_ts=datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        ) as ctx2:
            ctx2.record_input(
                key="SPY:polygon:snapshot_v4",
                snapshot_type="quote",
                payload=test_snapshot,  # Same payload
                metadata={"quality": {"score": 100}}
            )
            ctx2.record_feature("__global__", "regime_features", test_features)  # Same features

            input_hash_2 = ctx2.get_input_hash()
            features_hash_2 = ctx2.get_features_hash()

        # Hashes must match
        self.assertEqual(input_hash_1, input_hash_2, "Input hashes should be identical")
        self.assertEqual(features_hash_1, features_hash_2, "Features hashes should be identical")

    def test_different_inputs_produce_different_hashes(self):
        """Different inputs must produce different hashes."""
        from packages.quantum.services.replay.decision_context import DecisionContext

        with DecisionContext(
            strategy_name="test1",
            as_of_ts=datetime.now(timezone.utc)
        ) as ctx1:
            ctx1.record_input("key", "quote", {"price": 100.0})
            hash1 = ctx1.get_input_hash()

        with DecisionContext(
            strategy_name="test2",
            as_of_ts=datetime.now(timezone.utc)
        ) as ctx2:
            ctx2.record_input("key", "quote", {"price": 100.01})  # Different price
            hash2 = ctx2.get_input_hash()

        self.assertNotEqual(hash1, hash2)


class TestReplayDisabled(unittest.TestCase):
    """Tests for when REPLAY_ENABLE=0."""

    def test_record_input_returns_empty_when_disabled(self):
        """record_input is no-op when disabled."""
        # Temporarily disable
        original = os.environ.get("REPLAY_ENABLE")
        os.environ["REPLAY_ENABLE"] = "0"

        try:
            # Need to reimport to pick up new env value
            import importlib
            import packages.quantum.services.replay.decision_context as dc
            importlib.reload(dc)

            with dc.DecisionContext(
                strategy_name="test",
                as_of_ts=datetime.now(timezone.utc)
            ) as ctx:
                result = ctx.record_input("key", "quote", {"data": "test"})

            self.assertEqual(result, "")
        finally:
            if original:
                os.environ["REPLAY_ENABLE"] = original
            else:
                os.environ["REPLAY_ENABLE"] = "1"

            # Reload to restore original state
            importlib.reload(dc)


class TestMarketDataTruthLayerHook(unittest.TestCase):
    """Tests for MarketDataTruthLayer replay hooks."""

    @patch("packages.quantum.services.market_data_truth_layer.MarketDataTruthLayer.snapshot_many")
    def test_snapshot_many_v4_records_to_context(self, mock_snapshot_many):
        """snapshot_many_v4 records inputs when context is active."""
        from packages.quantum.services.market_data_truth_layer import MarketDataTruthLayer
        from packages.quantum.services.replay.decision_context import (
            DecisionContext,
            get_current_decision_context,
        )

        # Mock raw snapshot response
        mock_snapshot_many.return_value = {
            "SPY": {
                "quote": {"bid": 499.0, "ask": 501.0},
                "provider_ts": 1705314600000,
            }
        }

        layer = MarketDataTruthLayer(api_key="test")

        with DecisionContext(
            strategy_name="test",
            as_of_ts=datetime.now(timezone.utc)
        ) as ctx:
            # Call snapshot_many_v4
            result = layer.snapshot_many_v4(["SPY"])

            # Should have recorded input
            self.assertGreater(len(ctx.inputs), 0)

            # Check that SPY was recorded
            input_keys = [k[0] for k in ctx.inputs.keys()]
            self.assertTrue(any("SPY" in k for k in input_keys))

    def test_rates_divs_records_to_context(self):
        """rates_divs() records inputs when context is active."""
        from packages.quantum.services.market_data_truth_layer import MarketDataTruthLayer
        from packages.quantum.services.replay.decision_context import DecisionContext

        layer = MarketDataTruthLayer(api_key="test")

        with DecisionContext(
            strategy_name="test",
            as_of_ts=datetime.now(timezone.utc)
        ) as ctx:
            # Call rates_divs
            result = layer.rates_divs("SPY")

            # Should have recorded input with rates_divs key
            input_keys = [k for k in ctx.inputs.keys()]
            rates_divs_keys = [k for k in input_keys if "rates_divs" in k[0]]
            self.assertGreater(len(rates_divs_keys), 0)

    def test_rates_divs_returns_env_values(self):
        """rates_divs() returns env-based constants."""
        from packages.quantum.services.market_data_truth_layer import MarketDataTruthLayer

        # Set env vars for testing (using correct var names)
        original_rf = os.environ.get("REPLAY_RISK_FREE_RATE")
        original_dy = os.environ.get("REPLAY_DIVIDEND_YIELD")

        try:
            os.environ["REPLAY_RISK_FREE_RATE"] = "0.045"
            os.environ["REPLAY_DIVIDEND_YIELD"] = "0.012"

            layer = MarketDataTruthLayer(api_key="test")
            result = layer.rates_divs("SPY")

            self.assertEqual(result["risk_free_rate"], 0.045)
            self.assertEqual(result["div_yield"], 0.012)
        finally:
            if original_rf:
                os.environ["REPLAY_RISK_FREE_RATE"] = original_rf
            else:
                os.environ.pop("REPLAY_RISK_FREE_RATE", None)
            if original_dy:
                os.environ["REPLAY_DIVIDEND_YIELD"] = original_dy
            else:
                os.environ.pop("REPLAY_DIVIDEND_YIELD", None)

    def test_rates_divs_records_input_with_correct_key(self):
        """rates_divs() records input with expected key format and payload."""
        from packages.quantum.services.market_data_truth_layer import MarketDataTruthLayer
        from packages.quantum.services.replay.decision_context import DecisionContext

        layer = MarketDataTruthLayer(api_key="test")
        fixed_date = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

        with DecisionContext(
            strategy_name="test_rates",
            as_of_ts=datetime.now(timezone.utc)
        ) as ctx:
            result = layer.rates_divs("SPY", as_of=fixed_date)

            # Verify key format: "SPY:rates_divs:2024-01-15"
            expected_key = ("SPY:rates_divs:2024-01-15", "rates_divs")
            self.assertIn(expected_key, ctx.inputs.keys())

            # Verify payload structure
            self.assertIn("risk_free_rate", result)
            self.assertIn("div_yield", result)
            self.assertIn("as_of", result)
            self.assertIn("source", result)
            self.assertEqual(result["as_of"], "2024-01-15")


class TestReplayTruthLayerNormalization(unittest.TestCase):
    """Tests for ReplayTruthLayer key normalization (Patch 2.1)."""

    def test_daily_bars_normalizes_ticker(self):
        """daily_bars() normalizes ticker to match stored key."""
        from packages.quantum.services.replay.replay_truth_layer import ReplayTruthLayer

        # Create layer with bars stored under normalized key "SPY"
        layer = ReplayTruthLayer(
            decision_id="test-id",
            decision_run={"strategy_name": "test"},
            inputs=[{
                "key": "SPY:bars:2024-01-01:2024-01-10",
                "snapshot_type": "bars",
                "blob_hash": "bars123",
                "metadata": {}
            }],
            features=[],
            supabase=None,
        )

        # Pre-populate blob cache
        test_bars = [{"o": 100, "h": 101, "l": 99, "c": 100.5, "v": 1000000}]
        layer.blobs_cache["bars123"] = test_bars

        # Call with non-normalized ticker (spaces, lowercase)
        start = datetime(2024, 1, 1)
        end = datetime(2024, 1, 10)
        result = layer.daily_bars(" spy ", start, end)

        # Should find stored bars despite non-normalized input
        self.assertEqual(result, test_bars)


if __name__ == "__main__":
    unittest.main()
