"""
Regression tests for PR #780 follow-up — extend Alpaca-authoritative
equity via `equity_state.get_alpaca_equity()` to:
  - `paper_mark_to_market.py` (MTM envelope check)
  - `paper_autopilot_service.py._estimate_equity` (circuit breaker)

PR #780 explicitly deferred these two call sites:
    "Scope discipline: this PR touches intraday_risk_monitor.py only.
     The broader rollout to paper_mark_to_market / paper_autopilot
     _service is explicitly out of scope — done in a follow-up once
     the extracted module has a 48h observation window under
     production traffic."

The follow-up is now due. Prior code at both call sites used:
    asyncio.get_event_loop().run_until_complete(
        cash_svc.get_deployable_capital(user_id)
    )
which ALWAYS raises RuntimeError inside an already-running event loop
(RQ worker context). The `except` fell through to a notional-of-open-
positions sum — which produced absurdly tight per-symbol envelope
limits on small portfolios (e.g. AMZN $1,310 notional → $39 per-symbol
loss limit at 3%). Exactly the bug class Issue 3B observed.

Contract after this PR:
  - get_alpaca_equity() returns Optional[float] — concrete on success,
    None on Alpaca failure.
  - Callers MUST skip the envelope check when equity is None, NOT
    fabricate a substitute denominator. Matches intraday_risk_monitor's
    contract since 83872db — fabricated equity was the 2026-04-16
    false-force-close mechanism.

Tests
  1. MTM envelope path uses equity_state.get_alpaca_equity, not
     cash_svc.get_deployable_capital.
  2. Autopilot._estimate_equity uses equity_state.get_alpaca_equity
     and returns None on Alpaca unavailability (no notional fallback).
  3. Autopilot circuit breaker skips envelope check when equity is
     None (instead of firing false-positive with a fabricated
     denominator).
  4. Source-level shape guards: neither file contains the
     event-loop/cash_svc anti-pattern any more.
"""

import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch


# Stub alpaca-py per convention.
_alpaca_pkg = types.ModuleType("alpaca")
_alpaca_trading = types.ModuleType("alpaca.trading")
_alpaca_trading_requests = types.ModuleType("alpaca.trading.requests")


class _StubPortfolioHistoryRequest:
    def __init__(self, period=None, timeframe=None, **_):
        self.period = period
        self.timeframe = timeframe


_alpaca_trading_requests.GetPortfolioHistoryRequest = _StubPortfolioHistoryRequest
sys.modules.setdefault("alpaca", _alpaca_pkg)
sys.modules.setdefault("alpaca.trading", _alpaca_trading)
sys.modules.setdefault("alpaca.trading.requests", _alpaca_trading_requests)


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


class TestPaperAutopilotEstimateEquity(unittest.TestCase):
    """Autopilot._estimate_equity must delegate to equity_state."""

    def _make_service(self):
        from packages.quantum.services.paper_autopilot_service import (
            PaperAutopilotService,
        )
        svc = PaperAutopilotService.__new__(PaperAutopilotService)
        svc.client = MagicMock()
        svc.config = {}
        return svc

    def test_returns_alpaca_equity_value(self):
        svc = self._make_service()
        from packages.quantum.services import equity_state

        with patch.object(equity_state, "get_alpaca_equity", return_value=97276.32) as mock_eq:
            result = svc._estimate_equity("user-x", positions=[{"id": "p1"}])

        self.assertEqual(result, 97276.32)
        # Per #72-H1: autopilot now forwards its supabase client so
        # equity_state can write risk_alerts on Alpaca failure.
        mock_eq.assert_called_once_with("user-x", supabase=svc.client)

    def test_returns_none_on_alpaca_unavailable(self):
        """Hard contract: None on Alpaca failure, never the notional
        fallback the prior code used. Callers are obligated to skip
        the envelope check."""
        svc = self._make_service()
        from packages.quantum.services import equity_state

        with patch.object(equity_state, "get_alpaca_equity", return_value=None):
            result = svc._estimate_equity(
                "user-x",
                positions=[
                    {"avg_entry_price": 13.1, "quantity": 1},
                    {"avg_entry_price": 2.94, "quantity": 6},
                ],
            )

        self.assertIsNone(
            result,
            "_estimate_equity MUST return None when Alpaca is "
            "unavailable. Prior fallback computed sum(notional) which "
            "produced absurdly tight per-symbol envelope limits. See "
            "Issue 3B diagnosis + PR #780 follow-up commit body.",
        )


class TestAutopilotCircuitBreakerSkipsWhenEquityNone(unittest.TestCase):
    """
    When _estimate_equity returns None (Alpaca unavailable), the
    circuit breaker must skip the envelope check rather than invoke
    check_all_envelopes with a fabricated denominator.
    """

    def test_skip_path_does_not_call_check_all_envelopes(self):
        # Read the relevant source block and verify its logic-shape:
        src_path = os.path.join(
            REPO_ROOT, "packages", "quantum", "services",
            "paper_autopilot_service.py",
        )
        with open(src_path, "r", encoding="utf-8") as f:
            src = f.read()

        # Find the circuit-breaker block
        start = src.find("# Circuit breaker: block new entries if")
        self.assertGreater(start, 0)
        # End at the outer except line
        end = src.find("except Exception as cb_err:", start)
        self.assertGreater(end, 0)
        block = src[start:end]

        self.assertIn("cb_equity is None", block,
            "Circuit breaker must explicitly check for None equity")
        self.assertIn("skipping envelope check", block,
            "Should emit a warning log when skipping")
        # The check_all_envelopes call must be reachable only when
        # cb_equity is not None (we verify by checking the structural
        # order: None-check comes before the call).
        skip_pos = block.find("cb_equity is None")
        call_pos = block.find("check_all_envelopes(")
        self.assertLess(skip_pos, call_pos,
            "cb_equity None-check must precede check_all_envelopes call")


class TestPaperMtmEnvelopeUsesEquityState(unittest.TestCase):
    """Source-level verification of the MTM handler change."""

    def test_mtm_handler_imports_equity_state(self):
        src_path = os.path.join(
            REPO_ROOT, "packages", "quantum", "jobs", "handlers",
            "paper_mark_to_market.py",
        )
        with open(src_path, "r", encoding="utf-8") as f:
            src = f.read()

        self.assertIn(
            "from packages.quantum.services import equity_state", src,
            "MTM handler must import equity_state module",
        )
        # Per #72-H1: MTM handler now forwards its supabase client so
        # equity_state can write risk_alerts on Alpaca failure. Use a
        # shape-tolerant substring match (any kwargs after user_id are
        # acceptable; what matters is that the canonical entrypoint is
        # called with user_id as the first positional arg).
        self.assertIn(
            "equity_state.get_alpaca_equity(user_id", src,
            "MTM handler must call get_alpaca_equity with user_id",
        )

    def test_mtm_handler_no_longer_uses_event_loop_cash_svc_antipattern(self):
        src_path = os.path.join(
            REPO_ROOT, "packages", "quantum", "jobs", "handlers",
            "paper_mark_to_market.py",
        )
        with open(src_path, "r", encoding="utf-8") as f:
            src = f.read()

        # Locate the envelope-check block — the one that used the
        # event-loop antipattern before.
        block_start = src.find("# 1b. Run risk envelope check")
        self.assertGreater(block_start, 0)
        block_end = src.find("# 2.", block_start)
        self.assertGreater(block_end, 0)
        block = src[block_start:block_end]

        self.assertNotIn(
            "run_until_complete", block,
            "event-loop antipattern must not appear in the MTM envelope "
            "block. Prior code called asyncio.get_event_loop()."
            "run_until_complete which always raised RuntimeError in the "
            "RQ worker context.",
        )
        self.assertNotIn(
            "CashService(client)", block,
            "cash_svc fallback must not appear in the MTM envelope block",
        )

    def test_mtm_handler_skips_envelope_when_equity_none(self):
        src_path = os.path.join(
            REPO_ROOT, "packages", "quantum", "jobs", "handlers",
            "paper_mark_to_market.py",
        )
        with open(src_path, "r", encoding="utf-8") as f:
            src = f.read()

        # Locate MTM envelope block
        block_start = src.find("# 1b. Run risk envelope check")
        block_end = src.find("# 2.", block_start)
        block = src[block_start:block_end]

        self.assertIn(
            "equity is None", block,
            "MTM must explicitly check for None equity",
        )
        self.assertIn(
            "skipping envelope check", block,
            "MTM should log a warning when skipping the envelope check",
        )


class TestAutopilotEstimateEquityNoNotionalFallback(unittest.TestCase):
    """
    Source-level shape guard — the autopilot _estimate_equity body
    must NOT compute the notional-sum fallback any more. That fallback
    was the mechanism behind the $39 per-symbol false-tight envelope.
    """

    def test_no_notional_sum_fallback_in_estimate_equity(self):
        src_path = os.path.join(
            REPO_ROOT, "packages", "quantum", "services",
            "paper_autopilot_service.py",
        )
        with open(src_path, "r", encoding="utf-8") as f:
            src = f.read()

        # Locate _estimate_equity
        start = src.find("def _estimate_equity(")
        self.assertGreater(start, 0)
        end = src.find("\n    def ", start + 1)
        body = src[start:end if end > 0 else len(src)]

        # No event loop / cash service
        self.assertNotIn(
            "run_until_complete", body,
            "_estimate_equity must not call run_until_complete",
        )
        self.assertNotIn(
            "CashService", body,
            "_estimate_equity must not use CashService fallback",
        )
        # No sum-over-notional pattern
        self.assertNotIn(
            "avg_entry_price", body,
            "_estimate_equity must not compute notional fallback using "
            "avg_entry_price × quantity × 100 — that pattern produced "
            "the $39 per-symbol false-tight envelope limit (Issue 3B).",
        )
        # Must use equity_state
        self.assertIn(
            "equity_state.get_alpaca_equity", body,
            "_estimate_equity must delegate to equity_state.get_alpaca_equity",
        )


if __name__ == "__main__":
    unittest.main()
