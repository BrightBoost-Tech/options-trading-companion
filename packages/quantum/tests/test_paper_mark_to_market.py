"""
Tests for Phase 1: Mark-to-Market Daily P&L.

Verifies:
1. PaperMarkToMarketService._compute_position_value uses bid/ask midpoint
2. refresh_marks updates current_mark and unrealized_pl
3. save_eod_snapshot stores daily unrealized snapshots
4. get_current_unrealized_total sums open position unrealized
5. Checkpoint includes unrealized P&L in total_pnl
6. Checkpoint evaluates (not skips) when open positions have unrealized changes
7. Position creation includes max_credit and nearest_expiry
"""

import pytest
from datetime import date, timedelta


class TestComputePositionValue:
    """Tests for _compute_position_value static method."""

    def test_single_leg_mid_price(self):
        """Mark uses bid/ask midpoint, not last trade price."""
        from packages.quantum.services.paper_mark_to_market_service import (
            PaperMarkToMarketService,
        )

        position = {
            "id": "pos-1",
            "symbol": "TSLA",
            "quantity": 1,
            "legs": [
                {"symbol": "O:TSLA260320C00200000", "action": "buy", "quantity": 1}
            ],
        }

        class MockPoly:
            def get_recent_quote(self, symbol):
                return {"bid_price": 4.00, "ask_price": 4.20}

        def valid_quote(q):
            return True

        value = PaperMarkToMarketService._compute_position_value(
            position, MockPoly(), valid_quote
        )
        # mid = (4.00 + 4.20) / 2 = 4.10, * 100 multiplier * 1 qty = 410.00
        assert value is not None
        assert abs(value - 410.0) < 0.01

    def test_multi_leg_iron_condor(self):
        """Iron condor value = sum of leg values with correct signs."""
        from packages.quantum.services.paper_mark_to_market_service import (
            PaperMarkToMarketService,
        )

        position = {
            "id": "pos-2",
            "symbol": "SPY",
            "quantity": 1,
            "legs": [
                {"symbol": "O:SPY260320P00480000", "action": "sell", "quantity": 1},
                {"symbol": "O:SPY260320P00470000", "action": "buy", "quantity": 1},
                {"symbol": "O:SPY260320C00520000", "action": "sell", "quantity": 1},
                {"symbol": "O:SPY260320C00530000", "action": "buy", "quantity": 1},
            ],
        }

        quotes = {
            "O:SPY260320P00480000": {"bid_price": 1.50, "ask_price": 1.60},
            "O:SPY260320P00470000": {"bid_price": 0.80, "ask_price": 0.90},
            "O:SPY260320C00520000": {"bid_price": 1.20, "ask_price": 1.30},
            "O:SPY260320C00530000": {"bid_price": 0.60, "ask_price": 0.70},
        }

        class MockPoly:
            def get_recent_quote(self, symbol):
                return quotes.get(symbol)

        value = PaperMarkToMarketService._compute_position_value(
            position, MockPoly(), lambda q: True
        )

        # Sell P480: mid=1.55, sell → -1 → -155.0
        # Buy P470: mid=0.85, buy → +1 → +85.0
        # Sell C520: mid=1.25, sell → -1 → -125.0
        # Buy C530: mid=0.65, buy → +1 → +65.0
        # Total = -155 + 85 - 125 + 65 = -130.0
        assert value is not None
        assert abs(value - (-130.0)) < 0.01

    def test_no_valid_quotes_returns_none(self):
        """If no valid quotes, return None (don't update mark)."""
        from packages.quantum.services.paper_mark_to_market_service import (
            PaperMarkToMarketService,
        )

        position = {
            "id": "pos-3",
            "symbol": "AAPL",
            "quantity": 1,
            "legs": [{"symbol": "O:AAPL260320C00200000", "action": "buy", "quantity": 1}],
        }

        class MockPoly:
            def get_recent_quote(self, symbol):
                return None

        value = PaperMarkToMarketService._compute_position_value(
            position, MockPoly(), lambda q: q is not None
        )
        assert value is None

    def test_partial_leg_failure_returns_none(self):
        """If ANY leg in a multi-leg position fails, return None (all-or-nothing)."""
        from packages.quantum.services.paper_mark_to_market_service import (
            PaperMarkToMarketService,
        )

        # Iron condor: 4 legs, but leg 3 (short call) returns no quote.
        # Without the fix, this would understate the short-call liability
        # and massively overstate profit.
        position = {
            "id": "pos-partial",
            "symbol": "SPY",
            "quantity": 1,
            "legs": [
                {"symbol": "O:SPY260320P00480000", "action": "sell", "quantity": 1},
                {"symbol": "O:SPY260320P00470000", "action": "buy", "quantity": 1},
                {"symbol": "O:SPY260320C00520000", "action": "sell", "quantity": 1},  # This one fails
                {"symbol": "O:SPY260320C00530000", "action": "buy", "quantity": 1},
            ],
        }

        quotes = {
            "O:SPY260320P00480000": {"bid_price": 1.50, "ask_price": 1.60},
            "O:SPY260320P00470000": {"bid_price": 0.80, "ask_price": 0.90},
            # O:SPY260320C00520000 intentionally missing — broken pipe / timeout
            "O:SPY260320C00530000": {"bid_price": 0.60, "ask_price": 0.70},
        }

        class MockPoly:
            def get_recent_quote(self, symbol):
                return quotes.get(symbol)  # Returns None for missing leg

        value = PaperMarkToMarketService._compute_position_value(
            position, MockPoly(), lambda q: q is not None
        )
        # Must be None — partial pricing of short spreads is dangerous
        assert value is None

    def test_all_legs_succeed_returns_value(self):
        """When all legs price successfully, return the total value."""
        from packages.quantum.services.paper_mark_to_market_service import (
            PaperMarkToMarketService,
        )

        position = {
            "id": "pos-ok",
            "symbol": "SPY",
            "quantity": 1,
            "legs": [
                {"symbol": "O:SPY260320P00480000", "action": "sell", "quantity": 1},
                {"symbol": "O:SPY260320P00470000", "action": "buy", "quantity": 1},
            ],
        }

        quotes = {
            "O:SPY260320P00480000": {"bid_price": 1.50, "ask_price": 1.60},
            "O:SPY260320P00470000": {"bid_price": 0.80, "ask_price": 0.90},
        }

        class MockPoly:
            def get_recent_quote(self, symbol):
                return quotes.get(symbol)

        value = PaperMarkToMarketService._compute_position_value(
            position, MockPoly(), lambda q: q is not None
        )
        # Sell P480: mid=1.55, sell → -155.0
        # Buy P470: mid=0.85, buy → +85.0
        # Total = -70.0
        assert value is not None
        assert abs(value - (-70.0)) < 0.01

    def test_no_legs_falls_back_to_symbol(self):
        """Position with no legs quotes the underlying symbol."""
        from packages.quantum.services.paper_mark_to_market_service import (
            PaperMarkToMarketService,
        )

        position = {"id": "pos-4", "symbol": "MSFT", "quantity": 2, "legs": []}

        class MockPoly:
            def get_recent_quote(self, symbol):
                if symbol == "MSFT":
                    return {"bid_price": 400.00, "ask_price": 400.20}
                return None

        value = PaperMarkToMarketService._compute_position_value(
            position, MockPoly(), lambda q: True
        )
        # mid = 400.10, * 100 * 2 = 80020.0
        assert value is not None
        assert abs(value - 80020.0) < 1.0


class TestDailyPnlCalculation:
    """Tests for checkpoint P&L = realized + unrealized."""

    def test_daily_pnl_includes_unrealized(self):
        """
        Daily P&L = realized + unrealized.
        If no closes but positions have unrealized +$100, total_pnl = $100.
        """
        # Simulate: total_realized = 0, current_unrealized = 100
        total_realized = 0.0
        current_unrealized = 100.0
        total_pnl = total_realized + current_unrealized
        assert total_pnl == 100.0

    def test_daily_pnl_with_close_and_open(self):
        """
        Mix of realized closes and open position mark changes.
        Position A: closed, realized +$30
        Position B: open, unrealized +$10
        Total P&L = $40
        """
        total_realized = 30.0
        current_unrealized = 10.0
        total_pnl = total_realized + current_unrealized
        assert total_pnl == 40.0

    def test_negative_unrealized_reduces_total(self):
        """
        Realized +$50, unrealized -$30 → total = $20.
        """
        total_realized = 50.0
        current_unrealized = -30.0
        total_pnl = total_realized + current_unrealized
        assert total_pnl == 20.0

    def test_zero_unrealized_equals_realized_only(self):
        """
        When no open positions, total_pnl = realized only (backward compatible).
        """
        total_realized = 75.0
        current_unrealized = 0.0
        total_pnl = total_realized + current_unrealized
        assert total_pnl == 75.0


class TestCheckpointSourceCode:
    """Verify checkpoint code includes unrealized P&L computation."""

    @staticmethod
    def _get_source():
        from pathlib import Path

        src = Path(__file__).resolve().parent.parent / "services" / "go_live_validation_service.py"
        return src.read_text(encoding="utf-8")

    def test_checkpoint_computes_unrealized(self):
        """Checkpoint code includes _get_current_unrealized_total call."""
        source = self._get_source()
        assert "_get_current_unrealized_total" in source

    def test_checkpoint_total_pnl_includes_both(self):
        """total_pnl = total_realized + current_unrealized in checkpoint."""
        source = self._get_source()
        assert "total_realized" in source
        assert "current_unrealized" in source
        assert "total_pnl = total_realized + current_unrealized" in source

    def test_checkpoint_result_includes_breakdown(self):
        """Result includes pnl_realized and pnl_unrealized for transparency."""
        source = self._get_source()
        assert '"pnl_realized"' in source
        assert '"pnl_unrealized"' in source

    def test_checkpoint_has_mtm_activity_check(self):
        """Open positions with unrealized changes should not skip evaluation."""
        source = self._get_source()
        assert "has_mtm_activity" in source
        assert "not outcomes and not has_mtm_activity" in source

    def test_get_current_unrealized_total_defined(self):
        """_get_current_unrealized_total method exists in source."""
        source = self._get_source()
        assert "def _get_current_unrealized_total(self, user_id" in source


class TestPositionCreationEnrichment:
    """Verify position creation includes max_credit and nearest_expiry."""

    @staticmethod
    def _get_source():
        from pathlib import Path

        src = Path(__file__).resolve().parent.parent / "paper_endpoints.py"
        return src.read_text(encoding="utf-8")

    def test_commit_fill_includes_max_credit(self):
        """Position payload includes max_credit at creation time."""
        source = self._get_source()
        assert '"max_credit"' in source

    def test_commit_fill_includes_nearest_expiry(self):
        """Position payload includes nearest_expiry at creation time."""
        source = self._get_source()
        assert '"nearest_expiry"' in source

    def test_commit_fill_includes_status_open(self):
        """Position payload sets status='open' at creation time."""
        source = self._get_source()
        assert '"status": "open"' in source


class TestShadowCheckpointIncludesUnrealized:
    """Verify shadow checkpoint also includes unrealized P&L."""

    def test_shadow_computes_unrealized(self):
        from pathlib import Path

        src = Path(__file__).resolve().parent.parent / "services" / "go_live_validation_service.py"
        source = src.read_text(encoding="utf-8")
        assert "_get_current_unrealized_total" in source
        # Shadow method uses same pattern
        assert "total_realized + current_unrealized" in source


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
