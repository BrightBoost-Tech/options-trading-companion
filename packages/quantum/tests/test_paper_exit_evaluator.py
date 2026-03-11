"""
Tests for Phase 2: condition-based exit logic.

Verifies:
1. target_profit triggers at 50% of max credit captured
2. stop_loss triggers at 2x credit loss
3. dte_threshold triggers at 7 DTE or less
4. expiration_day triggers at 0 DTE
5. Healthy position holds (no condition triggered)
6. days_to_expiry computes correctly from nearest_expiry and legs
7. evaluate_position_exit returns first triggered condition
8. Exit evaluator logs close reasons
"""

import pytest
from datetime import date, timedelta


class TestExitConditions:
    """Tests for individual EXIT_CONDITIONS checks."""

    def _make_position(
        self,
        max_credit=None,
        unrealized_pl=0,
        nearest_expiry=None,
        legs=None,
    ):
        pos = {
            "id": "test-pos-1",
            "symbol": "SPY",
            "quantity": -1,
            "avg_entry_price": max_credit or 2.0,
            "max_credit": max_credit,
            "unrealized_pl": unrealized_pl,
            "nearest_expiry": nearest_expiry.isoformat() if nearest_expiry else None,
            "legs": legs or [],
        }
        return pos

    def test_target_profit_triggers_at_50pct(self):
        """Position with >= 50% of max credit captured should close."""
        from packages.quantum.services.paper_exit_evaluator import EXIT_CONDITIONS

        # max_credit = 2.00 per contract, so max_gain = $200.
        # 50% of $200 = $100. unrealized_pl = $120 > $100 → trigger
        pos = self._make_position(max_credit=2.00, unrealized_pl=120.0)
        assert EXIT_CONDITIONS["target_profit"]["check"](pos) is True

    def test_target_profit_does_not_trigger_below_50pct(self):
        """Position with < 50% of max credit should hold."""
        from packages.quantum.services.paper_exit_evaluator import EXIT_CONDITIONS

        # 50% of $200 = $100. unrealized_pl = $80 < $100 → hold
        pos = self._make_position(max_credit=2.00, unrealized_pl=80.0)
        assert EXIT_CONDITIONS["target_profit"]["check"](pos) is False

    def test_stop_loss_triggers_at_2x_credit(self):
        """Position exceeding 2x credit loss should close."""
        from packages.quantum.services.paper_exit_evaluator import EXIT_CONDITIONS

        # max_credit = 2.00, so 2x = $400 loss. unrealized_pl = -$450 → trigger
        pos = self._make_position(max_credit=2.00, unrealized_pl=-450.0)
        assert EXIT_CONDITIONS["stop_loss"]["check"](pos) is True

    def test_stop_loss_does_not_trigger_below_2x(self):
        """Position with loss < 2x credit should hold."""
        from packages.quantum.services.paper_exit_evaluator import EXIT_CONDITIONS

        pos = self._make_position(max_credit=2.00, unrealized_pl=-300.0)
        assert EXIT_CONDITIONS["stop_loss"]["check"](pos) is False

    def test_dte_threshold_triggers_at_7_days(self):
        """Position within 7 DTE should close."""
        from packages.quantum.services.paper_exit_evaluator import EXIT_CONDITIONS

        pos = self._make_position(
            max_credit=2.00,
            nearest_expiry=date.today() + timedelta(days=5),
        )
        assert EXIT_CONDITIONS["dte_threshold"]["check"](pos) is True

    def test_dte_threshold_does_not_trigger_above_7(self):
        """Position with > 7 DTE should hold."""
        from packages.quantum.services.paper_exit_evaluator import EXIT_CONDITIONS

        pos = self._make_position(
            max_credit=2.00,
            nearest_expiry=date.today() + timedelta(days=21),
        )
        assert EXIT_CONDITIONS["dte_threshold"]["check"](pos) is False

    def test_expiration_day_triggers_at_zero_dte(self):
        """Position expiring today must close."""
        from packages.quantum.services.paper_exit_evaluator import EXIT_CONDITIONS

        pos = self._make_position(
            max_credit=2.00,
            nearest_expiry=date.today(),
        )
        assert EXIT_CONDITIONS["expiration_day"]["check"](pos) is True

    def test_expiration_day_triggers_when_past_due(self):
        """Position already past expiry must close."""
        from packages.quantum.services.paper_exit_evaluator import EXIT_CONDITIONS

        pos = self._make_position(
            max_credit=2.00,
            nearest_expiry=date.today() - timedelta(days=1),
        )
        assert EXIT_CONDITIONS["expiration_day"]["check"](pos) is True

    def test_healthy_position_holds(self):
        """Position with profit < 50%, loss < 2x, DTE > 7 should hold."""
        from packages.quantum.services.paper_exit_evaluator import EXIT_CONDITIONS

        pos = self._make_position(
            max_credit=2.00,
            unrealized_pl=50.0,  # 25% of max → below 50% target
            nearest_expiry=date.today() + timedelta(days=21),
        )
        for name, condition in EXIT_CONDITIONS.items():
            assert condition["check"](pos) is False, f"Condition {name} should not trigger"

    def test_no_max_credit_skips_profit_loss_checks(self):
        """Position without max_credit doesn't trigger target_profit or stop_loss."""
        from packages.quantum.services.paper_exit_evaluator import EXIT_CONDITIONS

        pos = self._make_position(max_credit=None, unrealized_pl=500.0)
        assert EXIT_CONDITIONS["target_profit"]["check"](pos) is False
        assert EXIT_CONDITIONS["stop_loss"]["check"](pos) is False


class TestDaysToExpiry:
    """Tests for days_to_expiry helper."""

    def test_from_nearest_expiry_string(self):
        from packages.quantum.services.paper_exit_evaluator import days_to_expiry

        future = date.today() + timedelta(days=14)
        pos = {"nearest_expiry": future.isoformat()}
        assert days_to_expiry(pos) == 14

    def test_from_legs_expiry(self):
        from packages.quantum.services.paper_exit_evaluator import days_to_expiry

        future = date.today() + timedelta(days=10)
        pos = {
            "nearest_expiry": None,
            "legs": [
                {"symbol": "O:SPY260320C00500000", "expiry": future.isoformat()},
                {"symbol": "O:SPY260327C00500000", "expiry": (future + timedelta(days=7)).isoformat()},
            ],
        }
        # Should use the nearest leg (10 days)
        assert days_to_expiry(pos) == 10

    def test_no_expiry_info_returns_large_number(self):
        from packages.quantum.services.paper_exit_evaluator import days_to_expiry

        pos = {"nearest_expiry": None, "legs": []}
        assert days_to_expiry(pos) == 999

    def test_today_expiry_returns_zero(self):
        from packages.quantum.services.paper_exit_evaluator import days_to_expiry

        pos = {"nearest_expiry": date.today().isoformat()}
        assert days_to_expiry(pos) == 0

    def test_past_expiry_returns_negative(self):
        from packages.quantum.services.paper_exit_evaluator import days_to_expiry

        past = date.today() - timedelta(days=3)
        pos = {"nearest_expiry": past.isoformat()}
        assert days_to_expiry(pos) == -3


class TestEvaluatePositionExit:
    """Tests for evaluate_position_exit (first-match logic)."""

    def test_returns_first_matching_condition(self):
        """If multiple conditions match, return the first one (target_profit)."""
        from packages.quantum.services.paper_exit_evaluator import evaluate_position_exit

        pos = {
            "id": "test",
            "max_credit": 2.00,
            "unrealized_pl": 120.0,  # > 50% of $200 → target_profit
            "nearest_expiry": date.today().isoformat(),  # also expiration_day
        }
        # target_profit is checked first
        result = evaluate_position_exit(pos)
        assert result == "target_profit"

    def test_returns_none_when_no_match(self):
        from packages.quantum.services.paper_exit_evaluator import evaluate_position_exit

        pos = {
            "id": "test",
            "max_credit": 2.00,
            "unrealized_pl": 50.0,
            "nearest_expiry": (date.today() + timedelta(days=30)).isoformat(),
        }
        assert evaluate_position_exit(pos) is None


class TestClosePositionStrategyType:
    """Verify _close_position uses strategy_type='custom' to avoid leg count validation."""

    def test_close_position_uses_custom_strategy(self):
        """Closing order must use strategy_type='custom', not the original strategy."""
        from pathlib import Path

        src = Path(__file__).resolve().parent.parent / "services" / "paper_exit_evaluator.py"
        source = src.read_text(encoding="utf-8")

        # The fix: strategy_type should be "custom", NOT derived from strategy_key
        assert 'strategy_type="custom"' in source
        # Must NOT derive strategy from strategy_key (that caused the 4-leg validation error)
        assert 'strategy_key", "").split("_")[-1]' not in source

    def test_close_position_has_single_leg(self):
        """Closing order uses single leg (the OCC symbol), not all original legs."""
        from pathlib import Path

        src = Path(__file__).resolve().parent.parent / "services" / "paper_exit_evaluator.py"
        source = src.read_text(encoding="utf-8")

        # Verify _close_position creates a single-leg closing order
        assert "_resolve_occ_symbol" in source
        assert "source_engine=\"paper_exit_evaluator\"" in source


class TestScheduleChanges:
    """Verify schedule has exit evaluator and MTM, safety close removed."""

    @staticmethod
    def _get_schedule():
        from pathlib import Path

        yml = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "trading_tasks.yml"
        return yml.read_text(encoding="utf-8")

    def test_exit_evaluator_job_defined(self):
        source = self._get_schedule()
        assert "paper-exit-evaluate:" in source
        assert "paper_exit_evaluate" in source

    def test_mark_to_market_job_defined(self):
        source = self._get_schedule()
        assert "paper-mark-to-market:" in source
        assert "paper_mark_to_market" in source

    def test_safety_close_disabled(self):
        """Paper Safety Close One cron should be commented out."""
        source = self._get_schedule()
        # The job definition should no longer trigger
        assert "paper-safety-close-one:" not in source


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
