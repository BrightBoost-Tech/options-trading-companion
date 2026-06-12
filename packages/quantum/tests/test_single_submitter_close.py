"""Single-submitter close + terminal-reject classification (06-12).

The live close path submitted every order TWICE (docs/
double_submit_close_trace.md): `_stage_order_internal` broker-submits
alpaca-mode orders itself AND `_close_position` calls submit_and_track
again — on 06-11 the duplicate's pre-cancel killed the first resting order;
on 06-12 the first submission FILLED (SPY, 120ms) and the duplicate was
gateway-rejected `position intent mismatch`, whose failure path marked the
already-filled row needs_manual_review (false critical).

Also pinned here: the "retry storm" was a LYING MESSAGE, not behavior —
both retry layers interpolated their MAX constants ("after 3 attempts: …
after 10 attempts") regardless of actual count (1). Messages now carry the
honest count, and terminal rejects are classified explicitly:
- duplicate-close (42210000 / intent mismatch): no retry, NO manual-review
  mark (the fill reconciler owns the row), graceful return
- other terminal (sign-incoherent, insufficient, extra_forbidden): no
  retry, one needs_manual_review + one critical alert
- transient errors: bounded outer retry (MAX_SUBMIT_ATTEMPTS)
"""

import sys
import types
import unittest
from unittest.mock import MagicMock, patch

sys.modules.setdefault("alpaca", types.ModuleType("alpaca"))
sys.modules.setdefault("alpaca.trading", types.ModuleType("alpaca.trading"))
sys.modules.setdefault("alpaca.trading.requests", types.ModuleType("alpaca.trading.requests"))

import packages.quantum.brokers.alpaca_order_handler as handler  # noqa: E402


def _close_order():
    return {
        "id": "ord-close-1",
        "position_id": "pos-1",
        "side": "buy",
        "requested_qty": 1,
        "user_id": "u1",
        "order_json": {
            "limit_price": 1.96,
            "is_credit_close": False,
            "time_in_force": "day",
            "legs": [
                {"symbol": "O:SPY260724P00681000", "action": "buy", "quantity": 1},
                {"symbol": "O:SPY260724P00676000", "action": "sell", "quantity": 1},
            ],
        },
    }


def _mocks(submit_side_effect):
    alpaca = MagicMock()
    alpaca.paper = False
    alpaca.cancel_open_orders_for_symbols.return_value = []
    alpaca.submit_option_order.side_effect = submit_side_effect
    supabase = MagicMock()
    return alpaca, supabase


class TestSingleSubmitterWiring(unittest.TestCase):
    """Exactly one component owns broker submission for closes."""

    def test_stage_has_submit_to_broker_param_and_gate(self):
        import inspect
        from packages.quantum import paper_endpoints as pe
        sig = inspect.signature(pe._stage_order_internal)
        self.assertIn("submit_to_broker", sig.parameters)
        self.assertTrue(sig.parameters["submit_to_broker"].default)  # entries unchanged
        src = inspect.getsource(pe._stage_order_internal)
        self.assertIn("if not submit_to_broker:", src)

    def test_close_position_passes_false(self):
        import inspect
        from packages.quantum.services import paper_exit_evaluator as pee
        src = inspect.getsource(pee.PaperExitEvaluator._close_position)
        self.assertIn("submit_to_broker=False", src)
        # and it still owns the explicit submission
        self.assertIn("submit_and_track(", src)


class TestTerminalRejectClassification(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(handler.time, "sleep", lambda *_: None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_duplicate_close_no_retry_no_manual_review(self):
        """The 06-12 SPY shape: intent mismatch after the prior submission
        filled → ONE attempt, graceful return, row untouched (the reconciler
        owns it — no false critical racing a filled row)."""
        err = RuntimeError(
            'Alpaca API call failed after 1 attempt(s) (max 10): '
            '{"code":42210000,"message":"position intent mismatch, '
            'inferred: buy_to_open, specified: buy_to_close"}'
        )
        alpaca, supabase = _mocks(submit_side_effect=err)
        result = handler.submit_and_track(alpaca, supabase, _close_order(), "u1")
        self.assertEqual(alpaca.submit_option_order.call_count, 1)
        self.assertEqual(result["status"], "duplicate_close_prior_fill")
        self.assertEqual(result["attempts"], 1)
        supabase.table.return_value.update.assert_not_called()

    def test_terminal_insufficient_one_attempt_one_alert(self):
        err = RuntimeError("403 insufficient options buying power")
        alpaca, supabase = _mocks(submit_side_effect=err)
        with patch.object(handler, "datetime", wraps=handler.datetime), \
             patch("packages.quantum.observability.alerts.alert") as mock_alert, \
             patch("packages.quantum.observability.alerts._get_admin_supabase",
                   return_value=MagicMock()):
            result = handler.submit_and_track(alpaca, supabase, _close_order(), "u1")
        self.assertEqual(alpaca.submit_option_order.call_count, 1)
        self.assertEqual(result.get("status"), "needs_manual_review")
        self.assertEqual(mock_alert.call_count, 1)
        # honest count in the alert message — never the MAX constant
        msg = mock_alert.call_args.kwargs["message"]
        self.assertIn("after 1 attempt(s)", msg)

    def test_sign_incoherent_is_terminal(self):
        err = ValueError("Sign-incoherent debit close: limit_price=-1.39 …")
        alpaca, supabase = _mocks(submit_side_effect=err)
        with patch("packages.quantum.observability.alerts.alert"), \
             patch("packages.quantum.observability.alerts._get_admin_supabase",
                   return_value=MagicMock()):
            handler.submit_and_track(alpaca, supabase, _close_order(), "u1")
        self.assertEqual(alpaca.submit_option_order.call_count, 1)

    def test_transient_bounded_retry_then_success(self):
        ok = {"alpaca_order_id": "alp-1", "status": "accepted"}
        alpaca, supabase = _mocks(
            submit_side_effect=[RuntimeError("connection reset"), RuntimeError("timeout"), ok]
        )
        result = handler.submit_and_track(alpaca, supabase, _close_order(), "u1")
        self.assertEqual(alpaca.submit_option_order.call_count, 3)
        # the broker's own status wins the dict spread (existing behavior);
        # the point is: not a failure status, and bounded retries.
        self.assertEqual(result["status"], "accepted")

    def test_transient_exhaustion_reports_actual_attempts(self):
        err = RuntimeError("timeout talking to gateway")
        alpaca, supabase = _mocks(submit_side_effect=err)
        with patch("packages.quantum.observability.alerts.alert") as mock_alert, \
             patch("packages.quantum.observability.alerts._get_admin_supabase",
                   return_value=MagicMock()):
            handler.submit_and_track(alpaca, supabase, _close_order(), "u1")
        self.assertEqual(
            alpaca.submit_option_order.call_count, handler.MAX_SUBMIT_ATTEMPTS
        )
        msg = mock_alert.call_args.kwargs["message"]
        self.assertIn(f"after {handler.MAX_SUBMIT_ATTEMPTS} attempt(s)", msg)


class TestHonestRetryMessages(unittest.TestCase):
    def test_call_with_retry_message_counts_actual_attempts(self):
        import inspect
        from packages.quantum.brokers import alpaca_client as ac
        src = inspect.getsource(ac.AlpacaClient._call_with_retry)
        self.assertIn("attempts_made", src)
        self.assertNotIn(
            'failed after {self.MAX_RETRIES} attempts', src,
            "the lying fixed-count raise message is back",
        )


if __name__ == "__main__":
    unittest.main()
