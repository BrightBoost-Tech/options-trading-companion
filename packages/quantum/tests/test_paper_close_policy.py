"""
Tests for Phase 2: EV-aware exit ranking and close policies.

Verifies:
1. close_all policy closes all positions regardless of max_closes_per_day
2. ev_rank policy sorts by worst unrealized P&L first
3. min_one policy uses oldest-first ordering
4. OCC symbol resolution from position legs
"""

import pytest
from unittest.mock import MagicMock


class TestClosePositionSelection:
    """Tests for _select_positions_to_close and policy behavior."""

    def _make_positions(self):
        """Create mock positions with varying unrealized P&L."""
        return [
            {"id": "pos-1", "symbol": "AAPL", "quantity": 2, "unrealized_pl": -50.0,
             "created_at": "2026-03-09T10:00:00Z", "strategy_key": "AAPL_long_call"},
            {"id": "pos-2", "symbol": "MSFT", "quantity": 1, "unrealized_pl": 20.0,
             "created_at": "2026-03-09T10:30:00Z", "strategy_key": "MSFT_long_call"},
            {"id": "pos-3", "symbol": "AMZN", "quantity": 3, "unrealized_pl": -10.0,
             "created_at": "2026-03-09T11:00:00Z", "strategy_key": "AMZN_long_call"},
            {"id": "pos-4", "symbol": "META", "quantity": 1, "unrealized_pl": 5.0,
             "created_at": "2026-03-09T11:30:00Z", "strategy_key": "META_long_call"},
            {"id": "pos-5", "symbol": "AVGO", "quantity": 2, "unrealized_pl": -30.0,
             "created_at": "2026-03-09T12:00:00Z", "strategy_key": "AVGO_long_call"},
        ]

    def _make_svc(self):
        from packages.quantum.services.paper_autopilot_service import PaperAutopilotService
        return PaperAutopilotService.__new__(PaperAutopilotService)

    def test_close_all_returns_all_positions(self):
        """close_all policy should return all positions regardless of quota."""
        positions = self._make_positions()
        result = self._make_svc()._select_positions_to_close(
            positions, remaining_quota=1, policy="close_all"
        )
        assert len(result) == 5

    def test_ev_rank_worst_first(self):
        """ev_rank policy should close worst unrealized P&L first."""
        positions = self._make_positions()
        result = self._make_svc()._select_positions_to_close(
            positions, remaining_quota=3, policy="ev_rank"
        )
        assert len(result) == 3
        # Order should be: -50 (AAPL), -30 (AVGO), -10 (AMZN)
        assert result[0]["id"] == "pos-1"  # -50
        assert result[1]["id"] == "pos-5"  # -30
        assert result[2]["id"] == "pos-3"  # -10

    def test_ev_rank_respects_quota(self):
        """ev_rank should not exceed remaining_quota."""
        positions = self._make_positions()
        result = self._make_svc()._select_positions_to_close(
            positions, remaining_quota=2, policy="ev_rank"
        )
        assert len(result) == 2

    def test_min_one_oldest_first(self):
        """min_one policy should use oldest-first ordering."""
        positions = self._make_positions()
        result = self._make_svc()._select_positions_to_close(
            positions, remaining_quota=2, policy="min_one"
        )
        assert len(result) == 2
        assert result[0]["id"] == "pos-1"  # Oldest
        assert result[1]["id"] == "pos-2"

    def test_close_all_ignores_quota(self):
        """close_all should ignore remaining_quota entirely."""
        positions = self._make_positions()
        result = self._make_svc()._select_positions_to_close(
            positions, remaining_quota=0, policy="close_all"
        )
        # Even with quota=0, close_all returns everything
        assert len(result) == 5


class TestResolveOccSymbol:
    """Tests for OCC symbol resolution from position legs."""

    def test_resolve_from_position_legs(self):
        """Should resolve OCC symbol directly from position.legs."""
        from packages.quantum.services.paper_autopilot_service import PaperAutopilotService

        position = {
            "id": "pos-1",
            "symbol": "AMZN",
            "legs": [{"symbol": "O:AMZN260320C00185000", "action": "buy", "quantity": 2}],
        }
        result = PaperAutopilotService._resolve_occ_symbol(position, MagicMock())
        assert result == "O:AMZN260320C00185000"

    def test_resolve_fallback_to_opening_order(self):
        """Without position legs, should query opening order."""
        from packages.quantum.services.paper_autopilot_service import PaperAutopilotService

        position = {
            "id": "pos-1",
            "symbol": "MSFT",
            "legs": None,
        }

        mock_supabase = MagicMock()
        mock_supabase.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{
                "order_json": {
                    "legs": [{"symbol": "O:MSFT260320C00400000", "action": "buy"}]
                }
            }]
        )

        result = PaperAutopilotService._resolve_occ_symbol(position, mock_supabase)
        assert result == "O:MSFT260320C00400000"

    def test_resolve_fallback_to_underlying(self):
        """Without OCC in either place, should fall back to underlying."""
        from packages.quantum.services.paper_autopilot_service import PaperAutopilotService

        position = {
            "id": "pos-1",
            "symbol": "NVDA",
            "legs": [],
        }

        mock_supabase = MagicMock()
        mock_supabase.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[]
        )

        result = PaperAutopilotService._resolve_occ_symbol(position, mock_supabase)
        assert result == "NVDA"


class TestDefaultConfig:
    """Verify default config values for 10-day test."""

    def test_default_close_policy_is_close_all(self):
        """Default close policy should be close_all for 10-day test."""
        import os
        # Read source to verify default
        path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "services",
            "paper_autopilot_service.py"
        )
        with open(path, "r") as f:
            source = f.read()

        assert '"close_all"' in source
        assert 'PAPER_AUTOPILOT_CLOSE_POLICY", "close_all"' in source

    def test_default_max_closes_is_99(self):
        """Default max closes should be 99 (effectively unlimited)."""
        import os
        path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "services",
            "paper_autopilot_service.py"
        )
        with open(path, "r") as f:
            source = f.read()

        assert 'PAPER_AUTOPILOT_MAX_CLOSES_PER_DAY", "99"' in source


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
