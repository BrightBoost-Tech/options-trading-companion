"""
Tests for PositionPnLService and refresh_ledger_marks_v4 job handler.

Tests:
1. PnL computation formulas (LONG/SHORT)
2. Mark insertion and materialized column updates
3. Group-level NLV aggregation
4. Job handler batch processing
5. Edge cases (no positions, stale quotes, missing data)
"""

import unittest
from unittest.mock import MagicMock, patch, PropertyMock
from decimal import Decimal
from datetime import datetime, timezone

from packages.quantum.services.position_pnl_service import (
    PositionPnLService,
    compute_leg_unrealized_pnl,
)


class TestPnLComputation(unittest.TestCase):
    """Tests for unrealized PnL computation formulas."""

    def test_long_position_profit(self):
        """LONG position with profit: (mark - cost) * qty * multiplier."""
        # Bought at 2.00, now at 3.00, 10 contracts
        # PnL = (3.00 - 2.00) * 10 * 100 = 1000
        pnl = compute_leg_unrealized_pnl(
            side="LONG",
            avg_cost_open=2.00,
            mark_mid=3.00,
            qty_current=10,
            multiplier=100
        )
        self.assertEqual(pnl, 1000.0)

    def test_long_position_loss(self):
        """LONG position with loss: (mark - cost) * qty * multiplier."""
        # Bought at 3.00, now at 2.00, 10 contracts
        # PnL = (2.00 - 3.00) * 10 * 100 = -1000
        pnl = compute_leg_unrealized_pnl(
            side="LONG",
            avg_cost_open=3.00,
            mark_mid=2.00,
            qty_current=10,
            multiplier=100
        )
        self.assertEqual(pnl, -1000.0)

    def test_short_position_profit(self):
        """SHORT position with profit: (cost - mark) * abs(qty) * multiplier."""
        # Sold at 3.00, now at 2.00, 10 contracts (qty_current is negative for display)
        # PnL = (3.00 - 2.00) * 10 * 100 = 1000
        pnl = compute_leg_unrealized_pnl(
            side="SHORT",
            avg_cost_open=3.00,
            mark_mid=2.00,
            qty_current=-10,  # Short positions have negative qty
            multiplier=100
        )
        self.assertEqual(pnl, 1000.0)

    def test_short_position_loss(self):
        """SHORT position with loss: (cost - mark) * abs(qty) * multiplier."""
        # Sold at 2.00, now at 3.00, 10 contracts
        # PnL = (2.00 - 3.00) * 10 * 100 = -1000
        pnl = compute_leg_unrealized_pnl(
            side="SHORT",
            avg_cost_open=2.00,
            mark_mid=3.00,
            qty_current=-10,
            multiplier=100
        )
        self.assertEqual(pnl, -1000.0)

    def test_none_mark_returns_none(self):
        """Returns None when mark_mid is None."""
        pnl = compute_leg_unrealized_pnl(
            side="LONG",
            avg_cost_open=2.00,
            mark_mid=None,
            qty_current=10,
            multiplier=100
        )
        self.assertIsNone(pnl)

    def test_none_cost_returns_none(self):
        """Returns None when avg_cost_open is None."""
        pnl = compute_leg_unrealized_pnl(
            side="LONG",
            avg_cost_open=None,
            mark_mid=3.00,
            qty_current=10,
            multiplier=100
        )
        self.assertIsNone(pnl)

    def test_zero_quantity_returns_none(self):
        """Returns None when qty_current is 0 (closed position)."""
        pnl = compute_leg_unrealized_pnl(
            side="LONG",
            avg_cost_open=2.00,
            mark_mid=3.00,
            qty_current=0,
            multiplier=100
        )
        self.assertIsNone(pnl)

    def test_custom_multiplier(self):
        """Works with custom multiplier (e.g., 1 for stock)."""
        # Stock: bought 100 shares at $50, now at $55
        # PnL = (55 - 50) * 100 * 1 = 500
        pnl = compute_leg_unrealized_pnl(
            side="LONG",
            avg_cost_open=50.00,
            mark_mid=55.00,
            qty_current=100,
            multiplier=1
        )
        self.assertEqual(pnl, 500.0)


class TestPositionPnLService(unittest.TestCase):
    """Tests for PositionPnLService class."""

    def setUp(self):
        """Set up mock supabase client."""
        self.mock_client = MagicMock()
        self.service = PositionPnLService(self.mock_client, api_key="test-key")

    def test_compute_leg_unrealized_pnl_method(self):
        """Service method matches standalone function."""
        pnl = self.service.compute_leg_unrealized_pnl(
            side="LONG",
            avg_cost_open=2.00,
            mark_mid=3.00,
            qty_current=10,
            multiplier=100
        )
        self.assertEqual(pnl, 1000.0)

    def test_compute_group_nlv_success(self):
        """Computes NLV = realized + unrealized - fees."""
        # Setup mock response
        self.mock_client.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
            data={
                "id": "group-1",
                "realized_pnl": 500.0,
                "unrealized_pnl": 300.0,
                "fees_paid": 50.0,
                "net_liquidation_value": 750.0
            }
        )

        result = self.service.compute_group_nlv("group-1")

        self.assertTrue(result["success"])
        self.assertEqual(result["nlv"], 750.0)  # 500 + 300 - 50
        self.assertEqual(result["realized_pnl"], 500.0)
        self.assertEqual(result["unrealized_pnl"], 300.0)
        self.assertEqual(result["fees_paid"], 50.0)

    def test_compute_group_nlv_not_found(self):
        """Returns error when group not found."""
        self.mock_client.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
            data=None
        )

        result = self.service.compute_group_nlv("missing-group")

        self.assertFalse(result["success"])
        self.assertIn("not found", result["error"])

    def test_compute_group_nlv_handles_nulls(self):
        """Handles NULL values in group fields."""
        self.mock_client.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
            data={
                "id": "group-1",
                "realized_pnl": None,
                "unrealized_pnl": None,
                "fees_paid": None,
                "net_liquidation_value": None
            }
        )

        result = self.service.compute_group_nlv("group-1")

        self.assertTrue(result["success"])
        self.assertEqual(result["nlv"], 0.0)
        self.assertEqual(result["realized_pnl"], 0.0)
        self.assertEqual(result["unrealized_pnl"], 0.0)
        self.assertEqual(result["fees_paid"], 0.0)


class TestRefreshMarksForUser(unittest.TestCase):
    """Tests for refresh_marks_for_user method."""

    def setUp(self):
        """Set up mock supabase client and service."""
        self.mock_client = MagicMock()
        self.service = PositionPnLService(self.mock_client, api_key="test-key")

    def test_no_open_legs_returns_success(self):
        """Returns success with zero counts when no open legs."""
        # Mock empty legs query
        self.mock_client.table.return_value.select.return_value.eq.return_value.neq.return_value.execute.return_value = MagicMock(
            data=[]
        )

        result = self.service.refresh_marks_for_user("user-1")

        self.assertTrue(result["success"])
        self.assertEqual(result["legs_marked"], 0)
        self.assertEqual(result["groups_updated"], 0)
        self.assertEqual(result["marks_inserted"], 0)
        self.assertIn("No open legs", result["diagnostics"]["message"])

    def test_marks_open_legs_successfully(self):
        """Marks open legs and updates materialized columns."""
        # Mock open legs
        mock_leg = {
            "id": "leg-1",
            "group_id": "group-1",
            "user_id": "user-1",
            "symbol": "AAPL240119C00150000",
            "underlying": "AAPL",
            "side": "LONG",
            "qty_opened": 10,
            "qty_closed": 0,
            "qty_current": 10,
            "avg_cost_open": 2.50,
            "multiplier": 100
        }

        # Create a custom service with mocked _fetch_quotes
        service = PositionPnLService(self.mock_client, api_key="test-key")

        # Mock _fetch_quotes directly
        service._fetch_quotes = MagicMock(return_value={
            "AAPL240119C00150000": {
                "bid": 3.00,
                "ask": 3.10,
                "mid": 3.05,
                "last": 3.04,
                "quality_score": 85,
                "freshness_ms": 500,
                "is_stale": False
            }
        })

        # Mock legs query
        self.mock_client.table.return_value.select.return_value.eq.return_value.neq.return_value.execute.return_value = MagicMock(
            data=[mock_leg]
        )

        # Mock mark insert
        self.mock_client.table.return_value.insert.return_value.execute.return_value = MagicMock(
            data=[{"id": "mark-1"}]
        )

        # Mock leg update
        self.mock_client.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

        # Mock group queries for _update_group_pnl
        self.mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{"unrealized_pnl": 550.0}]
        )
        self.mock_client.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
            data={"realized_pnl": 0, "fees_paid": 0}
        )

        result = service.refresh_marks_for_user("user-1")

        self.assertTrue(result["success"])
        self.assertEqual(result["legs_marked"], 1)
        self.assertEqual(result["groups_updated"], 1)
        self.assertEqual(result["marks_inserted"], 1)

    def test_no_api_key_returns_empty_quotes(self):
        """Returns empty quotes when no API key configured."""
        service_no_key = PositionPnLService(self.mock_client, api_key=None)

        # Mock legs
        self.mock_client.table.return_value.select.return_value.eq.return_value.neq.return_value.execute.return_value = MagicMock(
            data=[{"id": "leg-1", "symbol": "AAPL", "group_id": "group-1", "user_id": "user-1"}]
        )

        with patch.dict("os.environ", {}, clear=True):
            result = service_no_key.refresh_marks_for_user("user-1")

        self.assertFalse(result["success"])
        self.assertIn("No quotes fetched", result["errors"][0])


class TestRefreshLedgerMarksV4Handler(unittest.TestCase):
    """Tests for refresh_ledger_marks_v4 job handler."""

    @patch("packages.quantum.jobs.handlers.refresh_ledger_marks_v4._get_supabase_client")
    def test_run_returns_success_no_users(self, mock_get_client):
        """Returns success when no users have open positions."""
        from packages.quantum.jobs.handlers.refresh_ledger_marks_v4 import run

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # Mock empty users query
        mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[]
        )

        result = run({})

        self.assertTrue(result["success"])
        self.assertEqual(result["users_processed"], 0)
        self.assertIn("No users with open positions", result["message"])

    @patch("packages.quantum.jobs.handlers.refresh_ledger_marks_v4.PositionPnLService")
    @patch("packages.quantum.jobs.handlers.refresh_ledger_marks_v4._get_supabase_client")
    def test_run_single_user_mode(self, mock_get_client, mock_pnl_service_class):
        """Runs for single user when user_id provided."""
        from packages.quantum.jobs.handlers.refresh_ledger_marks_v4 import run

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # Mock PnL service
        mock_service = MagicMock()
        mock_service.refresh_marks_for_user.return_value = {
            "success": True,
            "legs_marked": 5,
            "groups_updated": 2,
            "marks_inserted": 5,
            "errors": []
        }
        mock_pnl_service_class.return_value = mock_service

        result = run({"user_id": "user-123"})

        self.assertTrue(result["success"])
        self.assertEqual(result["users_processed"], 1)
        self.assertEqual(result["total_legs_marked"], 5)
        self.assertEqual(result["total_groups_updated"], 2)
        mock_service.refresh_marks_for_user.assert_called_once_with(
            user_id="user-123",
            group_ids=None,
            source="MARKET"
        )

    @patch("packages.quantum.jobs.handlers.refresh_ledger_marks_v4.PositionPnLService")
    @patch("packages.quantum.jobs.handlers.refresh_ledger_marks_v4._get_users_with_open_positions")
    @patch("packages.quantum.jobs.handlers.refresh_ledger_marks_v4._get_supabase_client")
    def test_run_batch_mode(self, mock_get_client, mock_get_users, mock_pnl_service_class):
        """Runs for all users when no user_id provided."""
        from packages.quantum.jobs.handlers.refresh_ledger_marks_v4 import run

        mock_get_client.return_value = MagicMock()
        mock_get_users.return_value = ["user-1", "user-2"]

        # Mock PnL service
        mock_service = MagicMock()
        mock_service.refresh_marks_for_user.return_value = {
            "success": True,
            "legs_marked": 3,
            "groups_updated": 1,
            "marks_inserted": 3,
            "errors": []
        }
        mock_pnl_service_class.return_value = mock_service

        result = run({})

        self.assertTrue(result["success"])
        self.assertEqual(result["users_processed"], 2)
        self.assertEqual(result["total_legs_marked"], 6)  # 3 * 2
        self.assertEqual(result["total_groups_updated"], 2)  # 1 * 2
        self.assertEqual(mock_service.refresh_marks_for_user.call_count, 2)

    @patch("packages.quantum.jobs.handlers.refresh_ledger_marks_v4.PositionPnLService")
    @patch("packages.quantum.jobs.handlers.refresh_ledger_marks_v4._get_supabase_client")
    def test_run_with_group_ids(self, mock_get_client, mock_pnl_service_class):
        """Passes group_ids to PnL service when provided."""
        from packages.quantum.jobs.handlers.refresh_ledger_marks_v4 import run

        mock_get_client.return_value = MagicMock()

        mock_service = MagicMock()
        mock_service.refresh_marks_for_user.return_value = {
            "success": True,
            "legs_marked": 2,
            "groups_updated": 2,
            "marks_inserted": 2,
            "errors": []
        }
        mock_pnl_service_class.return_value = mock_service

        result = run({
            "user_id": "user-123",
            "group_ids": ["group-1", "group-2"]
        })

        mock_service.refresh_marks_for_user.assert_called_once_with(
            user_id="user-123",
            group_ids=["group-1", "group-2"],
            source="MARKET"
        )

    @patch("packages.quantum.jobs.handlers.refresh_ledger_marks_v4.PositionPnLService")
    @patch("packages.quantum.jobs.handlers.refresh_ledger_marks_v4._get_supabase_client")
    def test_run_with_custom_source(self, mock_get_client, mock_pnl_service_class):
        """Uses custom source label when provided."""
        from packages.quantum.jobs.handlers.refresh_ledger_marks_v4 import run

        mock_get_client.return_value = MagicMock()

        mock_service = MagicMock()
        mock_service.refresh_marks_for_user.return_value = {
            "success": True,
            "legs_marked": 1,
            "groups_updated": 1,
            "marks_inserted": 1,
            "errors": []
        }
        mock_pnl_service_class.return_value = mock_service

        result = run({
            "user_id": "user-123",
            "source": "EOD"
        })

        mock_service.refresh_marks_for_user.assert_called_once_with(
            user_id="user-123",
            group_ids=None,
            source="EOD"
        )


class TestPnLIntegrationScenarios(unittest.TestCase):
    """Integration-style tests for realistic PnL scenarios."""

    def test_iron_condor_pnl_calculation(self):
        """Calculate PnL for an iron condor (4 legs)."""
        # Iron condor on SPY:
        # Leg 1: Sell 1 put 380 @ 2.00 (SHORT)
        # Leg 2: Buy 1 put 375 @ 1.00 (LONG)
        # Leg 3: Sell 1 call 420 @ 2.50 (SHORT)
        # Leg 4: Buy 1 call 425 @ 1.50 (LONG)

        # Current marks:
        # Put 380: 1.50 (down from 2.00, short wins)
        # Put 375: 0.75 (down from 1.00, long loses)
        # Call 420: 3.00 (up from 2.50, short loses)
        # Call 425: 2.25 (up from 1.50, long wins)

        # Multiplier = 100
        legs = [
            {"side": "SHORT", "cost": 2.00, "mark": 1.50, "qty": -1},  # +$50
            {"side": "LONG", "cost": 1.00, "mark": 0.75, "qty": 1},   # -$25
            {"side": "SHORT", "cost": 2.50, "mark": 3.00, "qty": -1}, # -$50
            {"side": "LONG", "cost": 1.50, "mark": 2.25, "qty": 1},   # +$75
        ]

        total_pnl = 0
        for leg in legs:
            pnl = compute_leg_unrealized_pnl(
                side=leg["side"],
                avg_cost_open=leg["cost"],
                mark_mid=leg["mark"],
                qty_current=leg["qty"],
                multiplier=100
            )
            total_pnl += pnl

        # Net: +50 -25 -50 +75 = +50
        self.assertEqual(total_pnl, 50.0)

    def test_vertical_spread_breakeven(self):
        """Vertical spread at breakeven shows ~0 PnL."""
        # Bull call spread: Buy 400C @ 10.00, Sell 410C @ 5.00
        # Net debit = 5.00

        # If SPY at 405: 400C ≈ 5.50, 410C ≈ 0.50
        pnl_long = compute_leg_unrealized_pnl(
            side="LONG", avg_cost_open=10.00, mark_mid=5.50, qty_current=1, multiplier=100
        )
        pnl_short = compute_leg_unrealized_pnl(
            side="SHORT", avg_cost_open=5.00, mark_mid=0.50, qty_current=-1, multiplier=100
        )

        # Long: (5.50 - 10.00) * 1 * 100 = -450
        # Short: (5.00 - 0.50) * 1 * 100 = +450
        # Total = 0
        self.assertEqual(pnl_long, -450.0)
        self.assertEqual(pnl_short, 450.0)
        self.assertEqual(pnl_long + pnl_short, 0.0)


if __name__ == "__main__":
    unittest.main()
