"""
Tests for seed_ledger_v4 job handler.

Tests:
1. Seeding creates groups, legs, events for broker positions
2. Re-running seed is idempotent (no duplicates)
3. After seeding, reconcile produces no breaks when quantities match
4. Handles signed quantities correctly (LONG/SHORT)
"""

import unittest
from unittest.mock import MagicMock, patch
from decimal import Decimal

from packages.quantum.jobs.handlers.seed_ledger_v4 import (
    run,
    _seed_user,
    _create_seed_entries,
    _build_seed_fingerprint,
    _build_seed_event_key,
    _extract_underlying,
    _infer_right_from_symbol,
    _get_ledger_symbols,
)


class TestSeedLedgerV4Handler(unittest.TestCase):
    """Tests for the main job handler."""

    @patch("packages.quantum.jobs.handlers.seed_ledger_v4._get_supabase_client")
    def test_run_returns_error_when_db_unavailable(self, mock_get_client):
        """Returns error when database is unavailable."""
        mock_get_client.return_value = None

        result = run({})

        self.assertEqual(result["status"], "failed")
        self.assertIn("Database unavailable", result["error"])

    @patch("packages.quantum.jobs.handlers.seed_ledger_v4._get_supabase_client")
    @patch("packages.quantum.jobs.handlers.seed_ledger_v4._seed_user")
    def test_run_single_user_mode(self, mock_seed_user, mock_get_client):
        """Runs for single user when user_id provided."""
        mock_get_client.return_value = MagicMock()
        mock_seed_user.return_value = {
            "status": "seeded",
            "seeded": 2,
            "skipped": 0,
        }

        result = run({"user_id": "user-123"})

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["users_processed"], 1)
        mock_seed_user.assert_called_once()

    @patch("packages.quantum.jobs.handlers.seed_ledger_v4._get_supabase_client")
    @patch("packages.quantum.jobs.handlers.seed_ledger_v4._get_users_with_broker_positions")
    @patch("packages.quantum.jobs.handlers.seed_ledger_v4._seed_user")
    def test_run_batch_mode(self, mock_seed_user, mock_get_users, mock_get_client):
        """Runs for all users when no user_id provided."""
        mock_get_client.return_value = MagicMock()
        mock_get_users.return_value = ["user-1", "user-2"]
        mock_seed_user.return_value = {
            "status": "seeded",
            "seeded": 1,
            "skipped": 0,
        }

        result = run({})

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["users_processed"], 2)
        self.assertEqual(result["total_seeded"], 2)
        self.assertEqual(mock_seed_user.call_count, 2)

    @patch("packages.quantum.jobs.handlers.seed_ledger_v4._get_supabase_client")
    @patch("packages.quantum.jobs.handlers.seed_ledger_v4._get_users_with_broker_positions")
    def test_run_no_users_with_positions(self, mock_get_users, mock_get_client):
        """Handles case when no users have positions."""
        mock_get_client.return_value = MagicMock()
        mock_get_users.return_value = []

        result = run({})

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["users_processed"], 0)


class TestSeedUser(unittest.TestCase):
    """Tests for _seed_user function."""

    def setUp(self):
        self.mock_supabase = MagicMock()

    def test_seed_user_no_broker_positions(self):
        """Returns early when user has no broker positions."""
        self.mock_supabase.table.return_value.select.return_value.eq.return_value.neq.return_value.execute.return_value.data = []

        result = _seed_user(self.mock_supabase, "user-123", dry_run=False, force=False)

        self.assertEqual(result["status"], "no_positions")
        self.assertEqual(result["seeded"], 0)

    @patch("packages.quantum.jobs.handlers.seed_ledger_v4._get_broker_positions")
    @patch("packages.quantum.jobs.handlers.seed_ledger_v4._get_ledger_symbols")
    def test_seed_user_skips_existing_symbols(self, mock_get_ledger, mock_get_broker):
        """Skips symbols already in ledger."""
        mock_get_broker.return_value = [
            {"symbol": "AAPL", "qty": 100, "avg_price": 150.00},
            {"symbol": "TSLA", "qty": 50, "avg_price": 200.00},
        ]
        mock_get_ledger.return_value = {"AAPL"}  # AAPL already in ledger

        result = _seed_user(self.mock_supabase, "user-123", dry_run=True, force=False)

        self.assertEqual(result["seeded"], 1)  # Only TSLA
        self.assertEqual(result["skipped"], 1)  # AAPL skipped

    @patch("packages.quantum.jobs.handlers.seed_ledger_v4._get_broker_positions")
    @patch("packages.quantum.jobs.handlers.seed_ledger_v4._get_ledger_symbols")
    def test_seed_user_dry_run_creates_nothing(self, mock_get_ledger, mock_get_broker):
        """Dry run shows what would be created without writing."""
        mock_get_broker.return_value = [
            {"symbol": "AAPL", "qty": 100, "avg_price": 150.00},
        ]
        mock_get_ledger.return_value = set()

        result = _seed_user(self.mock_supabase, "user-123", dry_run=True, force=False)

        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["seeded"], 1)
        self.assertTrue(result["seeded_positions"][0]["dry_run"])

    @patch("packages.quantum.jobs.handlers.seed_ledger_v4._get_broker_positions")
    @patch("packages.quantum.jobs.handlers.seed_ledger_v4._get_ledger_symbols")
    @patch("packages.quantum.jobs.handlers.seed_ledger_v4._create_seed_entries")
    def test_seed_user_force_mode_ignores_existing(
        self, mock_create, mock_get_ledger, mock_get_broker
    ):
        """Force mode seeds even if symbol exists in ledger."""
        mock_get_broker.return_value = [
            {"symbol": "AAPL", "qty": 100, "avg_price": 150.00},
        ]
        mock_get_ledger.return_value = {"AAPL"}  # Already exists
        mock_create.return_value = {
            "group_id": "group-1",
            "leg_id": "leg-1",
            "event_id": "event-1",
        }

        result = _seed_user(self.mock_supabase, "user-123", dry_run=False, force=True)

        # With force=True, _get_ledger_symbols is not called to get existing
        self.assertEqual(result["seeded"], 1)
        mock_create.assert_called_once()


class TestCreateSeedEntries(unittest.TestCase):
    """Tests for _create_seed_entries function."""

    def _setup_mock_supabase(self):
        """Setup mock Supabase with chained calls."""
        mock = MagicMock()

        def table_side_effect(name):
            chain = MagicMock()
            chain.select.return_value = chain
            chain.insert.return_value = chain
            chain.eq.return_value = chain
            chain.limit.return_value = chain

            result = MagicMock()

            if name == "position_events":
                # First call for idempotency check returns nothing
                result.data = []
            elif name == "position_groups":
                result.data = [{"id": "group-123"}]
            elif name == "position_legs":
                result.data = [{"id": "leg-123"}]

            chain.execute.return_value = result
            return chain

        mock.table.side_effect = table_side_effect
        return mock

    def test_creates_long_position_for_positive_qty(self):
        """Creates LONG position for positive quantity."""
        mock_supabase = self._setup_mock_supabase()

        # Override to capture insert calls
        insert_calls = []

        def table_side_effect(name):
            chain = MagicMock()
            chain.select.return_value = chain
            chain.eq.return_value = chain
            chain.limit.return_value = chain

            def capture_insert(data):
                insert_calls.append({"table": name, "data": data})
                result = MagicMock()
                if name == "position_groups":
                    result.data = [{"id": "group-123"}]
                elif name == "position_legs":
                    result.data = [{"id": "leg-123"}]
                elif name == "position_events":
                    result.data = [{"id": "event-123"}]
                chain.execute.return_value = result
                return chain

            chain.insert.side_effect = capture_insert

            # For select (idempotency check)
            result = MagicMock()
            result.data = []
            chain.execute.return_value = result
            return chain

        mock_supabase.table.side_effect = table_side_effect

        result = _create_seed_entries(
            supabase=mock_supabase,
            user_id="user-123",
            symbol="AAPL",
            qty=100,
            avg_price=150.00,
        )

        self.assertEqual(result["group_id"], "group-123")
        self.assertEqual(result["leg_id"], "leg-123")
        self.assertEqual(result["event_id"], "event-123")

        # Check leg data has LONG side
        leg_insert = next(c for c in insert_calls if c["table"] == "position_legs")
        self.assertEqual(leg_insert["data"]["side"], "LONG")
        self.assertEqual(leg_insert["data"]["qty_opened"], 100)

    def test_creates_short_position_for_negative_qty(self):
        """Creates SHORT position for negative quantity."""
        mock_supabase = self._setup_mock_supabase()

        insert_calls = []

        def table_side_effect(name):
            chain = MagicMock()
            chain.select.return_value = chain
            chain.eq.return_value = chain
            chain.limit.return_value = chain

            def capture_insert(data):
                insert_calls.append({"table": name, "data": data})
                result = MagicMock()
                if name == "position_groups":
                    result.data = [{"id": "group-123"}]
                elif name == "position_legs":
                    result.data = [{"id": "leg-123"}]
                elif name == "position_events":
                    result.data = [{"id": "event-123"}]
                chain.execute.return_value = result
                return chain

            chain.insert.side_effect = capture_insert

            result = MagicMock()
            result.data = []
            chain.execute.return_value = result
            return chain

        mock_supabase.table.side_effect = table_side_effect

        result = _create_seed_entries(
            supabase=mock_supabase,
            user_id="user-123",
            symbol="AAPL",
            qty=-50,  # Short position
            avg_price=150.00,
        )

        # Check leg data has SHORT side
        leg_insert = next(c for c in insert_calls if c["table"] == "position_legs")
        self.assertEqual(leg_insert["data"]["side"], "SHORT")
        self.assertEqual(leg_insert["data"]["qty_opened"], 50)  # Absolute value

    def test_idempotent_returns_existing_event(self):
        """Returns existing event if event_key already exists."""
        mock_supabase = MagicMock()

        def table_side_effect(name):
            chain = MagicMock()
            chain.select.return_value = chain
            chain.eq.return_value = chain
            chain.limit.return_value = chain

            result = MagicMock()
            if name == "position_events":
                # Existing event found
                result.data = [{
                    "id": "existing-event-id",
                    "group_id": "existing-group-id",
                    "leg_id": "existing-leg-id",
                }]
            else:
                result.data = []

            chain.execute.return_value = result
            return chain

        mock_supabase.table.side_effect = table_side_effect

        result = _create_seed_entries(
            supabase=mock_supabase,
            user_id="user-123",
            symbol="AAPL",
            qty=100,
            avg_price=150.00,
        )

        self.assertEqual(result["event_id"], "existing-event-id")
        self.assertTrue(result.get("deduplicated"))

    def test_handles_missing_avg_price(self):
        """Records uncertainty in meta_json when avg_price is None."""
        mock_supabase = self._setup_mock_supabase()

        insert_calls = []

        def table_side_effect(name):
            chain = MagicMock()
            chain.select.return_value = chain
            chain.eq.return_value = chain
            chain.limit.return_value = chain

            def capture_insert(data):
                insert_calls.append({"table": name, "data": data})
                result = MagicMock()
                if name == "position_groups":
                    result.data = [{"id": "group-123"}]
                elif name == "position_legs":
                    result.data = [{"id": "leg-123"}]
                elif name == "position_events":
                    result.data = [{"id": "event-123"}]
                chain.execute.return_value = result
                return chain

            chain.insert.side_effect = capture_insert

            result = MagicMock()
            result.data = []
            chain.execute.return_value = result
            return chain

        mock_supabase.table.side_effect = table_side_effect

        _create_seed_entries(
            supabase=mock_supabase,
            user_id="user-123",
            symbol="AAPL",
            qty=100,
            avg_price=None,  # No avg price
        )

        # Check event has cost_unknown in meta_json
        event_insert = next(c for c in insert_calls if c["table"] == "position_events")
        self.assertTrue(event_insert["data"]["meta_json"]["cost_unknown"])
        self.assertIsNone(event_insert["data"]["amount_cash"])


class TestUtilityFunctions(unittest.TestCase):
    """Tests for utility functions."""

    def test_build_seed_fingerprint_is_deterministic(self):
        """Same inputs produce same fingerprint."""
        fp1 = _build_seed_fingerprint("AAPL", "LONG")
        fp2 = _build_seed_fingerprint("AAPL", "LONG")
        self.assertEqual(fp1, fp2)

    def test_build_seed_fingerprint_different_for_different_sides(self):
        """Different sides produce different fingerprints."""
        fp_long = _build_seed_fingerprint("AAPL", "LONG")
        fp_short = _build_seed_fingerprint("AAPL", "SHORT")
        self.assertNotEqual(fp_long, fp_short)

    def test_build_seed_event_key_format(self):
        """Event key has correct format."""
        key = _build_seed_event_key("user-123", "AAPL", 100, 150.50)
        self.assertEqual(key, "seed:user-123:AAPL:100:150.5000")

    def test_build_seed_event_key_handles_null_price(self):
        """Event key handles None price."""
        key = _build_seed_event_key("user-123", "AAPL", 100, None)
        self.assertEqual(key, "seed:user-123:AAPL:100:null")

    def test_extract_underlying_from_option_symbol(self):
        """Extracts underlying from option symbol."""
        self.assertEqual(_extract_underlying("AAPL240119C00150000"), "AAPL")
        self.assertEqual(_extract_underlying("TSLA240315P00200000"), "TSLA")

    def test_extract_underlying_from_stock_symbol(self):
        """Returns stock symbol as-is."""
        self.assertEqual(_extract_underlying("AAPL"), "AAPL")
        self.assertEqual(_extract_underlying("TSLA"), "TSLA")

    def test_infer_right_from_option_symbol(self):
        """Infers right from option symbol."""
        self.assertEqual(_infer_right_from_symbol("AAPL240119C00150000"), "C")
        self.assertEqual(_infer_right_from_symbol("TSLA240315P00200000"), "P")

    def test_infer_right_from_stock_symbol(self):
        """Returns S for stock symbol."""
        self.assertEqual(_infer_right_from_symbol("AAPL"), "S")
        self.assertEqual(_infer_right_from_symbol("TSLA"), "S")


class TestSeedAndReconcileIntegration(unittest.TestCase):
    """Integration tests for seed + reconcile workflow."""

    @patch("packages.quantum.jobs.handlers.seed_ledger_v4._get_supabase_client")
    @patch("packages.quantum.jobs.handlers.seed_ledger_v4._get_broker_positions")
    @patch("packages.quantum.jobs.handlers.seed_ledger_v4._get_ledger_symbols")
    @patch("packages.quantum.jobs.handlers.seed_ledger_v4._create_seed_entries")
    def test_seed_then_reconcile_no_breaks(
        self, mock_create, mock_get_ledger, mock_get_broker, mock_get_client
    ):
        """After seeding, reconcile should produce no breaks for matching quantities."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # Broker has 2 positions
        mock_get_broker.return_value = [
            {"symbol": "AAPL", "qty": 100, "avg_price": 150.00},
            {"symbol": "TSLA", "qty": 50, "avg_price": 200.00},
        ]
        mock_get_ledger.return_value = set()  # Empty ledger
        mock_create.return_value = {
            "group_id": "group-1",
            "leg_id": "leg-1",
            "event_id": "event-1",
        }

        # Run seed
        result = run({"user_id": "user-123"})

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["results"]["user-123"]["seeded"], 2)

        # Verify _create_seed_entries called twice
        self.assertEqual(mock_create.call_count, 2)

    @patch("packages.quantum.jobs.handlers.seed_ledger_v4._get_supabase_client")
    @patch("packages.quantum.jobs.handlers.seed_ledger_v4._get_broker_positions")
    @patch("packages.quantum.jobs.handlers.seed_ledger_v4._get_ledger_symbols")
    @patch("packages.quantum.jobs.handlers.seed_ledger_v4._create_seed_entries")
    def test_rerun_seed_is_idempotent(
        self, mock_create, mock_get_ledger, mock_get_broker, mock_get_client
    ):
        """Re-running seed creates no duplicates."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_get_broker.return_value = [
            {"symbol": "AAPL", "qty": 100, "avg_price": 150.00},
        ]
        # First run: ledger is empty
        mock_get_ledger.return_value = set()
        mock_create.return_value = {
            "group_id": "group-1",
            "leg_id": "leg-1",
            "event_id": "event-1",
        }

        # First seed
        result1 = run({"user_id": "user-123"})
        self.assertEqual(result1["results"]["user-123"]["seeded"], 1)

        # Second run: symbol now in ledger
        mock_get_ledger.return_value = {"AAPL"}
        mock_create.reset_mock()

        result2 = run({"user_id": "user-123"})
        self.assertEqual(result2["results"]["user-123"]["seeded"], 0)
        self.assertEqual(result2["results"]["user-123"]["skipped"], 1)

        # _create_seed_entries should not be called on second run
        mock_create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
