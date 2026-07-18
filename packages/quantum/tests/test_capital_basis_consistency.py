"""
Regression tests for capital basis consistency between sizing and risk budget.

Updated 2026-05-01 for #93 fix: cash_service.get_deployable_capital now
reads Alpaca options_buying_power directly (via equity_state helper)
instead of computing buying_power - cash_buffer - reserved_capital from
DB-derived sources. The previous logic produced phantom reservations
when trade_suggestions stayed `pending` indefinitely.

Pre-#93 tests asserted the old DB arithmetic (paper-baseline floor +
buffer + reserved subtraction). Those scenarios are no longer reachable
via the public API; the broker-truth read is the only path. Tests below
exercise the new contract:
- Alpaca returns OBP → that value is the deployable
- Alpaca unavailable → fall back to v3_go_live_state.paper_baseline_capital
- Both unavailable → 0.0 (caller's CapitalScanPolicy gates the cycle)
"""

import asyncio
import sys
import unittest
from unittest.mock import MagicMock, patch

# --- sys.modules isolation: stub-only-if-absent + GUARANTEED restore ---------
# Stub heavy dependencies ONLY around the module-level import below, then
# RESTORE sys.modules immediately. The PRE-FIX version assigned these into
# sys.modules at module level and NEVER restored them, so it PERMANENTLY
# shadowed the REAL modules for every later-collected test in the same CI shard
# (pytest imports ALL test modules at COLLECTION time before running any test —
# an un-restored stub is live for that whole phase). Concretely:
# test_entries_only_halt.py does `import packages.quantum.ops_endpoints` at its
# module level, and the leaked MagicMock made `logging.getLogger(<MagicMock>)`
# raise "A logger name must be a string" (4 spurious failures — green
# single-file, red at full-suite collection order). This is the 2026-07-17
# sys.modules poison class; identical fix to test_weekly_report_win_rate.py and
# test_inbox_ranker_comprehensive.py.
#
# The restore MUST be immediate (try/finally), NOT a module-scoped
# tearDownModule: teardown fires only after THIS module's tests run, i.e. after
# every other module has already been collected against the leaked stub.
#
# ops_endpoints is imported lazily at CALL time inside CashService._is_paper_mode
# / _paper_baseline_fallback; both call sites are `try/except Exception`-guarded
# and fall back to the live (non-paper) branch, so the tests below stay correct
# when the real module is resolved at call time.
_STUB_KEYS = (
    "supabase",
    "packages.quantum.check_version",
    "packages.quantum.ops_endpoints",
)
_saved_modules = {_k: sys.modules.get(_k) for _k in _STUB_KEYS}
for _k in _STUB_KEYS:
    if _saved_modules[_k] is None:  # never shadow an already-imported real module
        sys.modules[_k] = MagicMock()
try:
    from packages.quantum.services.cash_service import CashService  # noqa: E402
    from packages.quantum.services.equity_state import (  # noqa: E402
        _reset_caches_for_testing,
    )
finally:
    for _k in _STUB_KEYS:
        if _saved_modules[_k] is None:
            sys.modules.pop(_k, None)
        else:
            sys.modules[_k] = _saved_modules[_k]
del _saved_modules

USER_ID = "test-user-capital-consistency"


def _make_chain_mock(**table_responses):
    """Build a Supabase mock whose .table(name) returns a chain mock."""
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


class TestDeployableReadsBrokerTruth(unittest.TestCase):
    """#93: get_deployable_capital reads Alpaca options_buying_power."""

    def setUp(self):
        _reset_caches_for_testing()

    def test_returns_alpaca_options_buying_power(self):
        """When Alpaca returns OBP, that is the deployable value."""
        with patch(
            "packages.quantum.brokers.alpaca_client.get_alpaca_client"
        ) as mock_factory:
            mock_client = MagicMock()
            mock_client.get_account.return_value = {
                "options_buying_power": "500.00",
            }
            mock_factory.return_value = mock_client

            svc = CashService(_make_chain_mock())
            result = asyncio.run(svc.get_deployable_capital(USER_ID))
            self.assertEqual(result, 500.0)

    def test_alpaca_failure_fails_closed_in_live_mode(self):
        """CONTRACT CHANGED — M4 item 0.2 (2026-07-06, owner decision):
        live-mode Alpaca failure returns 0.0 (entries blocked via
        CapitalScanPolicy), NEVER the $500 baseline — the old fallback
        changed the computed tier and inverted the scanned universe on
        07-06. The baseline survives only for explicit paper-mode
        operation (next test)."""
        with patch(
            "packages.quantum.brokers.alpaca_client.get_alpaca_client",
            side_effect=Exception("Alpaca down"),
        ):
            mock_sb = _make_chain_mock(
                v3_go_live_state=[{"paper_baseline_capital": 500}],
            )
            svc = CashService(mock_sb)
            with patch.object(CashService, "_is_paper_mode", return_value=False):
                result = asyncio.run(svc.get_deployable_capital(USER_ID))
            self.assertEqual(result, 0.0)

    def test_paper_mode_still_reads_baseline_on_alpaca_failure(self):
        """Explicit paper-mode operation keeps its baseline (its original
        purpose) — the M4-0.2 fail-closed applies to LIVE mode only."""
        with patch(
            "packages.quantum.brokers.alpaca_client.get_alpaca_client",
            side_effect=Exception("Alpaca down"),
        ):
            mock_sb = _make_chain_mock(
                v3_go_live_state=[{"paper_baseline_capital": 500}],
            )
            svc = CashService(mock_sb)
            with patch.object(CashService, "_is_paper_mode", return_value=True):
                result = asyncio.run(svc.get_deployable_capital(USER_ID))
            self.assertEqual(result, 500.0)

    def test_falls_back_to_zero_when_no_baseline(self):
        """Both Alpaca and baseline unavailable → 0 (caller skips cycle)."""
        with patch(
            "packages.quantum.brokers.alpaca_client.get_alpaca_client",
            return_value=None,
        ):
            mock_sb = _make_chain_mock(v3_go_live_state=[])
            svc = CashService(mock_sb)
            result = asyncio.run(svc.get_deployable_capital(USER_ID))
            self.assertEqual(result, 0.0)

    def test_does_not_subtract_pending_reservations(self):
        """#93 regression: pending trade_suggestions must NOT reduce
        deployable. Pre-#93 logic subtracted SUM(capital_required) from
        the buying_power source; that caused phantom reservations when
        suggestions stayed `pending` (paper_autopilot status-update
        bypass). Broker-truth read sidesteps the lifecycle entirely."""
        with patch(
            "packages.quantum.brokers.alpaca_client.get_alpaca_client"
        ) as mock_factory:
            mock_client = MagicMock()
            mock_client.get_account.return_value = {
                "options_buying_power": "500.00",
            }
            mock_factory.return_value = mock_client

            mock_sb = _make_chain_mock(
                trade_suggestions=[
                    {"sizing_metadata": {"capital_required": 292.0}},
                ],
            )
            svc = CashService(mock_sb)
            result = asyncio.run(svc.get_deployable_capital(USER_ID))
            # Pre-#93 would have returned 500 - 292 = 208.
            self.assertEqual(result, 500.0)


class TestRiskBudgetGuardrail(unittest.TestCase):
    """Tests for the risk budget engine capital mismatch guardrail."""

    def test_diagnostics_flags_capital_mismatch(self):
        """
        When usage >> deployable, diagnostics should include capital_mismatch.
        """
        # Import here to avoid complex mocking at module level
        from packages.quantum.services.risk_budget_engine import RiskBudgetEngine

        # RiskEngine.get_active_policy was retired in PR #4 — no mock needed.

        # Mock supabase for RiskBudgetEngine
        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(data=None)

        engine = RiskBudgetEngine(mock_sb)

        # Simulate: positions with total risk of 137,500 but deployable of only 20.51
        # 5 short puts at strike 275 = 275 * 100 * 5 = 137,500
        positions = [
            {
                "symbol": "O:SPY250117P00275000",
                "quantity": 5,
                "side": "sell",
                "strike": 275,
                "option_type": "put",
                "instrument_type": "option",
            }
        ]

        # This should trigger the guardrail
        with patch.object(engine, 'truth_layer'):
            report = engine.compute(
                user_id=USER_ID,
                deployable_capital=20.51,
                regime_input="chop",
                positions=positions,
            )

        # Check diagnostics contains capital_mismatch
        mismatch_diags = [d for d in report.diagnostics if "capital_mismatch" in d]
        self.assertTrue(
            len(mismatch_diags) > 0,
            f"Expected capital_mismatch in diagnostics, got: {report.diagnostics}"
        )

        # Verify the usage is approximately 137,500 (5 * 275 * 100)
        self.assertGreater(report.global_allocation.used, 100_000)


if __name__ == "__main__":
    unittest.main()
