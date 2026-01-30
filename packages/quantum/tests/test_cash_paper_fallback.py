"""
Tests for paper-mode deployable capital fallback in CashService.

When ops mode is "paper" and no portfolio snapshot or cash positions
provide buying_power, CashService should fall back to
v3_go_live_state.paper_baseline_capital (default 100k).
"""
import asyncio
import unittest
from unittest.mock import MagicMock, patch
import sys

# Mock ops_endpoints so deferred import inside _paper_baseline_fallback works
_mock_ops_module = MagicMock()

with patch.dict(sys.modules, {
    "packages.quantum.check_version": MagicMock(),
    "packages.quantum.ops_endpoints": _mock_ops_module,
}):
    from packages.quantum.services.cash_service import CashService


def _make_chain_mock(**table_responses):
    """
    Build a Supabase mock whose .table(name) returns a chain mock.

    table_responses maps table names to execute().data values.
    Pass a list for normal queries, a dict for .single() queries,
    or [] / None for empty results.
    """
    mock_supabase = MagicMock()

    def table_side_effect(name):
        chain = MagicMock()
        data = table_responses.get(name, [])
        chain.execute.return_value = MagicMock(data=data)
        for method in ["select", "eq", "neq", "gte", "lt", "in_",
                        "order", "limit", "single", "maybe_single"]:
            getattr(chain, method).return_value = chain
        return chain

    mock_supabase.table.side_effect = table_side_effect
    return mock_supabase


class TestPaperCapitalFallback(unittest.TestCase):
    """Paper-mode fallback: use paper_baseline_capital when buying_power missing."""

    def setUp(self):
        _mock_ops_module.reset_mock()

    def test_paper_fallback_triggers_when_no_snapshot(self):
        """
        In paper mode with no snapshot and no cash positions,
        buying_power should be paper_baseline_capital (75000 from DB).
        """
        _mock_ops_module.get_global_ops_control.return_value = {"mode": "paper"}
        mock_sb = _make_chain_mock(
            portfolio_snapshots=[],
            positions=[],
            v3_go_live_state=[{"paper_baseline_capital": 75000}],
            user_settings=None,
            trade_suggestions=[],
        )
        svc = CashService(mock_sb)
        result = asyncio.run(svc.get_deployable_capital("user-1"))
        self.assertEqual(result, 75000.0)

    def test_paper_fallback_uses_default_100k_when_no_state_row(self):
        """
        In paper mode with no v3_go_live_state row, default to 100000.
        """
        _mock_ops_module.get_global_ops_control.return_value = {"mode": "paper"}
        mock_sb = _make_chain_mock(
            portfolio_snapshots=[],
            positions=[],
            v3_go_live_state=[],
            user_settings=None,
            trade_suggestions=[],
        )
        svc = CashService(mock_sb)
        result = asyncio.run(svc.get_deployable_capital("user-1"))
        self.assertEqual(result, 100_000.0)

    def test_no_fallback_in_live_mode(self):
        """
        In live/micro_live mode, even with no snapshot and no cash,
        buying_power stays at 0 (no paper fallback).
        """
        _mock_ops_module.get_global_ops_control.return_value = {"mode": "micro_live"}
        mock_sb = _make_chain_mock(
            portfolio_snapshots=[],
            positions=[],
            user_settings=None,
            trade_suggestions=[],
        )
        svc = CashService(mock_sb)
        result = asyncio.run(svc.get_deployable_capital("user-1"))
        self.assertEqual(result, 0.0)

    def test_no_fallback_when_snapshot_has_buying_power(self):
        """
        If portfolio snapshot has buying_power, paper fallback is skipped
        even in paper mode.
        """
        _mock_ops_module.get_global_ops_control.side_effect = RuntimeError(
            "should not be called"
        )
        mock_sb = _make_chain_mock(
            portfolio_snapshots=[{"buying_power": 50000}],
            user_settings=None,
            trade_suggestions=[],
        )
        svc = CashService(mock_sb)
        result = asyncio.run(svc.get_deployable_capital("user-1"))
        self.assertEqual(result, 50000.0)

    def test_no_fallback_when_cash_positions_exist(self):
        """
        If cash positions provide buying_power above threshold,
        paper fallback is skipped.
        """
        _mock_ops_module.get_global_ops_control.side_effect = RuntimeError(
            "should not be called"
        )
        mock_sb = _make_chain_mock(
            portfolio_snapshots=[],
            positions=[{"symbol": "CUR:USD", "quantity": 25000, "current_price": 1.0}],
            user_settings=None,
            trade_suggestions=[],
        )
        svc = CashService(mock_sb)
        result = asyncio.run(svc.get_deployable_capital("user-1"))
        self.assertEqual(result, 25000.0)

    def test_paper_fallback_respects_cash_buffer_and_reserved(self):
        """
        Paper fallback sets buying_power but cash_buffer and reserved_capital
        are still subtracted normally.
        """
        _mock_ops_module.get_global_ops_control.return_value = {"mode": "paper"}
        mock_sb = _make_chain_mock(
            portfolio_snapshots=[],
            positions=[],
            v3_go_live_state=[{"paper_baseline_capital": 100000}],
            user_settings={"cash_buffer": 5000},
            trade_suggestions=[
                {"sizing_metadata": {"capital_required": 10000}},
            ],
        )
        svc = CashService(mock_sb)
        result = asyncio.run(svc.get_deployable_capital("user-1"))
        # 100000 - 5000 buffer - 10000 reserved = 85000
        self.assertEqual(result, 85000.0)


if __name__ == "__main__":
    unittest.main()
