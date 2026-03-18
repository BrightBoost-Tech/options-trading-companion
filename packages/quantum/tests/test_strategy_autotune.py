"""
Tests for strategy_autotune job handler.

Verifies:
1. Normalized outcome classification works for paper rows with details_json.pnl_outcome
2. Fallback classification from pnl_realized works
3. Win-rate math includes normalized paper wins
4. Paper-derived mutations are blocked by default
5. Enabling ENABLE_PAPER_AUTOTUNE allows the mutation path
6. Live/non-paper behavior remains unchanged
"""

import asyncio

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime, timedelta, timezone


# ---------------------------------------------------------------------------
# Fixtures: outcome records
# ---------------------------------------------------------------------------

def _make_outcome(
    pnl_realized,
    outcome_type="individual_trade",
    is_paper=False,
    pnl_outcome=None,
):
    """Build a minimal learning_feedback_loops record."""
    details_json = {}
    if pnl_outcome is not None:
        details_json["pnl_outcome"] = pnl_outcome
    if is_paper:
        details_json["is_paper"] = True
    return {
        "pnl_realized": pnl_realized,
        "pnl_predicted": None,
        "outcome_type": outcome_type,
        "details_json": details_json if details_json else None,
        "is_paper": is_paper,
    }


# Paper outcomes: outcome_type is "trade_closed" but pnl_outcome carries truth
_PAPER_WIN = _make_outcome(150.0, outcome_type="trade_closed", is_paper=True, pnl_outcome="win")
_PAPER_LOSS = _make_outcome(-80.0, outcome_type="trade_closed", is_paper=True, pnl_outcome="loss")
_PAPER_BREAKEVEN = _make_outcome(0.0, outcome_type="trade_closed", is_paper=True, pnl_outcome="breakeven")

# Live outcomes: outcome_type carries truth
_LIVE_WIN = _make_outcome(200.0, outcome_type="win")
_LIVE_LOSS = _make_outcome(-100.0, outcome_type="loss")


# ---------------------------------------------------------------------------
# Helpers for Supabase mock
# ---------------------------------------------------------------------------

class FakeResponse:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    """Chainable mock for supabase.table(...).select(...).eq(...).gte(...).execute()"""
    def __init__(self, data):
        self._data = data

    def select(self, *args, **kwargs):
        return self

    def eq(self, *args, **kwargs):
        return self

    def gte(self, *args, **kwargs):
        return self

    def execute(self):
        return FakeResponse(self._data)

    def insert(self, *args, **kwargs):
        return self


def _make_supabase(outcomes, strategy_config=None):
    """Build a mock supabase client that returns the given outcomes."""
    if strategy_config is None:
        strategy_config = {
            "version": 3,
            "conviction_floor": 0.40,
            "stop_loss_pct": 0.05,
            "max_risk_pct_portfolio": 0.10,
            "take_profit_pct": 0.10,
            "max_holding_days": 14,
        }

    mock_client = MagicMock()

    def table_dispatch(name):
        if name == "learning_feedback_loops":
            return FakeQuery(outcomes)
        elif name == "strategy_configs":
            return FakeQuery([])  # insert target
        else:
            return FakeQuery([])

    mock_client.table = MagicMock(side_effect=table_dispatch)
    return mock_client, strategy_config


# ===========================================================================
# Tests: outcome_normalizer.classify_outcome
# ===========================================================================

class TestClassifyOutcome:
    """Unit tests for the shared classify_outcome helper."""

    def test_details_json_pnl_outcome_takes_precedence(self):
        """details_json.pnl_outcome should be used even when pnl_realized disagrees."""
        from packages.quantum.jobs.handlers.outcome_normalizer import classify_outcome

        record = _make_outcome(pnl_realized=-50.0, pnl_outcome="win")
        assert classify_outcome(record) == "win"

    def test_fallback_to_pnl_realized_positive(self):
        from packages.quantum.jobs.handlers.outcome_normalizer import classify_outcome

        record = _make_outcome(pnl_realized=100.0)
        assert classify_outcome(record) == "win"

    def test_fallback_to_pnl_realized_negative(self):
        from packages.quantum.jobs.handlers.outcome_normalizer import classify_outcome

        record = _make_outcome(pnl_realized=-50.0)
        assert classify_outcome(record) == "loss"

    def test_fallback_to_pnl_realized_zero(self):
        from packages.quantum.jobs.handlers.outcome_normalizer import classify_outcome

        record = _make_outcome(pnl_realized=0.0)
        assert classify_outcome(record) == "breakeven"

    def test_none_pnl_realized_returns_breakeven(self):
        from packages.quantum.jobs.handlers.outcome_normalizer import classify_outcome

        record = {"pnl_realized": None, "details_json": None}
        assert classify_outcome(record) == "breakeven"

    def test_paper_trade_closed_classified_by_pnl_outcome(self):
        """Paper rows with outcome_type='trade_closed' use pnl_outcome."""
        from packages.quantum.jobs.handlers.outcome_normalizer import classify_outcome

        assert classify_outcome(_PAPER_WIN) == "win"
        assert classify_outcome(_PAPER_LOSS) == "loss"
        assert classify_outcome(_PAPER_BREAKEVEN) == "breakeven"


# ===========================================================================
# Tests: _compute_metrics
# ===========================================================================

class TestComputeMetrics:
    """Tests for _compute_metrics using normalized classification."""

    def test_paper_wins_counted_as_wins(self):
        """Paper rows with pnl_outcome='win' must be included in win count."""
        from packages.quantum.jobs.handlers.strategy_autotune import _compute_metrics

        outcomes = [_PAPER_WIN, _PAPER_WIN, _PAPER_LOSS]
        metrics = _compute_metrics(outcomes)

        assert metrics["wins"] == 2
        assert metrics["losses"] == 1
        assert metrics["win_rate"] == pytest.approx(2 / 3)

    def test_mixed_paper_and_live(self):
        """Metrics should aggregate paper + live correctly."""
        from packages.quantum.jobs.handlers.strategy_autotune import _compute_metrics

        outcomes = [_LIVE_WIN, _PAPER_WIN, _LIVE_LOSS, _PAPER_LOSS]
        metrics = _compute_metrics(outcomes)

        assert metrics["wins"] == 2
        assert metrics["losses"] == 2
        assert metrics["win_rate"] == pytest.approx(0.5)
        assert metrics["paper_count"] == 2
        assert metrics["live_count"] == 2

    def test_all_live_outcomes(self):
        """Pure live outcomes should work unchanged."""
        from packages.quantum.jobs.handlers.strategy_autotune import _compute_metrics

        outcomes = [_LIVE_WIN, _LIVE_WIN, _LIVE_LOSS]
        metrics = _compute_metrics(outcomes)

        assert metrics["wins"] == 2
        assert metrics["losses"] == 1
        assert metrics["paper_count"] == 0
        assert metrics["live_count"] == 3

    def test_avg_pnl_computation(self):
        from packages.quantum.jobs.handlers.strategy_autotune import _compute_metrics

        outcomes = [
            _make_outcome(100.0),
            _make_outcome(-50.0),
            _make_outcome(0.0),
        ]
        metrics = _compute_metrics(outcomes)
        assert metrics["avg_pnl"] == pytest.approx(50.0 / 3)

    def test_breakeven_counted(self):
        from packages.quantum.jobs.handlers.strategy_autotune import _compute_metrics

        outcomes = [_PAPER_BREAKEVEN, _LIVE_WIN]
        metrics = _compute_metrics(outcomes)

        assert metrics["breakevens"] == 1
        assert metrics["wins"] == 1

    def test_empty_list(self):
        from packages.quantum.jobs.handlers.strategy_autotune import _compute_metrics

        metrics = _compute_metrics([])
        assert metrics["win_rate"] == 0.0
        assert metrics["avg_pnl"] == 0.0
        assert metrics["samples"] == 0


# ===========================================================================
# Tests: _is_paper helper
# ===========================================================================

class TestIsPaper:
    """Tests for _is_paper helper."""

    def test_is_paper_true_on_record(self):
        from packages.quantum.jobs.handlers.strategy_autotune import _is_paper

        assert _is_paper({"is_paper": True}) is True

    def test_is_paper_false_on_record(self):
        from packages.quantum.jobs.handlers.strategy_autotune import _is_paper

        assert _is_paper({"is_paper": False, "details_json": None}) is False

    def test_is_paper_from_details_json(self):
        from packages.quantum.jobs.handlers.strategy_autotune import _is_paper

        record = {"is_paper": False, "details_json": {"is_paper": True}}
        assert _is_paper(record) is True

    def test_not_paper_when_absent(self):
        from packages.quantum.jobs.handlers.strategy_autotune import _is_paper

        assert _is_paper({}) is False


# ===========================================================================
# Tests: paper-autotune guard
# ===========================================================================

class TestPaperAutotuneGuard:
    """
    Tests that paper-derived mutations are blocked by default
    and allowed when ENABLE_PAPER_AUTOTUNE=true.
    """

    @patch("packages.quantum.jobs.handlers.strategy_autotune.ENABLE_PAPER_AUTOTUNE", False)
    def test_paper_mutation_blocked_by_default(self):
        """When ENABLE_PAPER_AUTOTUNE=false, paper outcomes block mutation."""
        from packages.quantum.jobs.handlers.strategy_autotune import _evaluate_and_update

        # 12 paper losses → low win rate → would trigger mutation
        outcomes = [_PAPER_LOSS] * 12
        client, config = _make_supabase(outcomes)

        result = asyncio.run(_evaluate_and_update("user-1234-abcd", "spy_opt_autolearn_v6", client, 10))

        assert result["paper_guard_blocked"] is True
        assert result["updated"] is False
        assert result["mutation_basis"] == "blocked_paper_only"
        # Metrics should still be computed
        assert result["win_rate"] == 0.0
        assert result["samples"] == 12

    @patch("packages.quantum.jobs.handlers.strategy_autotune.ENABLE_PAPER_AUTOTUNE", True)
    @patch("packages.quantum.jobs.handlers.strategy_autotune.load_strategy_config")
    def test_paper_mutation_allowed_when_enabled(self, mock_load_config):
        """When ENABLE_PAPER_AUTOTUNE=true, paper outcomes can trigger mutation."""
        from packages.quantum.jobs.handlers.strategy_autotune import _evaluate_and_update

        mock_load_config.return_value = {
            "version": 3,
            "conviction_floor": 0.40,
            "stop_loss_pct": 0.05,
        }

        outcomes = [_PAPER_LOSS] * 12
        client, _ = _make_supabase(outcomes)

        result = asyncio.run(_evaluate_and_update("user-1234-abcd", "spy_opt_autolearn_v6", client, 10))

        assert result["updated"] is True
        assert result.get("paper_guard_blocked") is None
        assert result["new_version"] == 4

    @patch("packages.quantum.jobs.handlers.strategy_autotune.ENABLE_PAPER_AUTOTUNE", False)
    @patch("packages.quantum.jobs.handlers.strategy_autotune.load_strategy_config")
    def test_mixed_paper_and_live_uses_live_basis(self, mock_load_config):
        """Mixed dataset should use live-only rows for mutation decision."""
        from packages.quantum.jobs.handlers.strategy_autotune import _evaluate_and_update

        mock_load_config.return_value = {
            "version": 5,
            "conviction_floor": 0.40,
            "stop_loss_pct": 0.05,
        }

        outcomes = [_LIVE_LOSS] * 11 + [_PAPER_LOSS]
        client, _ = _make_supabase(outcomes)

        result = asyncio.run(_evaluate_and_update("user-1234-abcd", "spy_opt_autolearn_v6", client, 10))

        # Live-only basis: 0/11 win rate -> triggers mutation
        assert result["updated"] is True
        assert result.get("mutation_basis") == "live_only"

    @patch("packages.quantum.jobs.handlers.strategy_autotune.ENABLE_PAPER_AUTOTUNE", False)
    @patch("packages.quantum.jobs.handlers.strategy_autotune.load_strategy_config")
    def test_pure_live_mutation_unblocked(self, mock_load_config):
        """Pure live outcomes should mutate normally regardless of guard."""
        from packages.quantum.jobs.handlers.strategy_autotune import _evaluate_and_update

        mock_load_config.return_value = {
            "version": 5,
            "conviction_floor": 0.40,
            "stop_loss_pct": 0.05,
        }

        outcomes = [_LIVE_LOSS] * 12
        client, _ = _make_supabase(outcomes)

        result = asyncio.run(_evaluate_and_update("user-1234-abcd", "spy_opt_autolearn_v6", client, 10))

        assert result["updated"] is True
        assert result.get("paper_guard_blocked") is None
        assert result["new_version"] == 6

    @patch("packages.quantum.jobs.handlers.strategy_autotune.ENABLE_PAPER_AUTOTUNE", False)
    def test_guard_does_not_block_when_no_mutation_needed(self):
        """High win rate -> no mutation -> guard irrelevant."""
        from packages.quantum.jobs.handlers.strategy_autotune import _evaluate_and_update

        outcomes = [_PAPER_WIN] * 10 + [_PAPER_LOSS] * 2
        client, _ = _make_supabase(outcomes)

        result = asyncio.run(_evaluate_and_update("user-1234-abcd", "spy_opt_autolearn_v6", client, 10))

        # win_rate = 10/12 ~ 83% -> no mutation needed, guard never fires
        assert result["updated"] is False
        assert result.get("paper_guard_blocked") is None

    @patch("packages.quantum.jobs.handlers.strategy_autotune.ENABLE_PAPER_AUTOTUNE", False)
    @patch("packages.quantum.jobs.handlers.strategy_autotune.load_strategy_config")
    def test_mixed_dataset_live_driven_mutation(self, mock_load_config):
        """Mixed dataset with poor live metrics should mutate using live-only basis."""
        from packages.quantum.jobs.handlers.strategy_autotune import _evaluate_and_update

        mock_load_config.return_value = {
            "version": 2,
            "conviction_floor": 0.40,
            "stop_loss_pct": 0.05,
        }

        # 10 live losses + 5 paper wins -- live metrics are bad, paper looks good
        outcomes = [_LIVE_LOSS] * 10 + [_PAPER_WIN] * 5
        client, _ = _make_supabase(outcomes)

        result = asyncio.run(_evaluate_and_update("user-1234-abcd", "spy_opt_autolearn_v6", client, 10))

        assert result["updated"] is True
        assert result.get("mutation_basis") == "live_only"

    @patch("packages.quantum.jobs.handlers.strategy_autotune.ENABLE_PAPER_AUTOTUNE", False)
    def test_mixed_dataset_paper_weakness_only(self):
        """Mixed dataset where paper weakness triggers combined mutation check,
        but live-only metrics are healthy so no mutation occurs."""
        from packages.quantum.jobs.handlers.strategy_autotune import _evaluate_and_update

        # 5 live wins + 7 paper losses
        # Combined: 5/12 = 41.7% win rate (< 45%) -> needs_mutation=True
        # Live-only: 5/5 = 100% win rate, avg_pnl=$200 -> needs_mutation=False
        # Guard recomputes with live-only -> no mutation
        outcomes = [_LIVE_WIN] * 5 + [_PAPER_LOSS] * 7
        client, _ = _make_supabase(outcomes)

        result = asyncio.run(_evaluate_and_update("user-1234-abcd", "spy_opt_autolearn_v6", client, 10))

        assert result["updated"] is False
        assert result.get("mutation_basis") == "live_only"


# ===========================================================================
# Tests: live autotune behavior unchanged
# ===========================================================================

class TestLiveAutotuneBehavior:
    """Verify live-only autotune behavior hasn't regressed."""

    @patch("packages.quantum.jobs.handlers.strategy_autotune.ENABLE_PAPER_AUTOTUNE", False)
    @patch("packages.quantum.jobs.handlers.strategy_autotune.load_strategy_config")
    def test_low_win_rate_triggers_mutation(self, mock_load_config):
        """Low win rate on live trades should trigger conviction_floor bump."""
        from packages.quantum.jobs.handlers.strategy_autotune import _evaluate_and_update

        mock_load_config.return_value = {
            "version": 1,
            "conviction_floor": 0.40,
            "stop_loss_pct": 0.05,
        }

        # 3 wins, 9 losses → 25% win rate
        outcomes = [_LIVE_WIN] * 3 + [_LIVE_LOSS] * 9
        client, _ = _make_supabase(outcomes)

        result = asyncio.run(_evaluate_and_update("user-1234-abcd", "spy_opt_autolearn_v6", client, 10))

        assert result["updated"] is True
        assert result["mutation_reason"] == "low_win_rate"
        assert result["win_rate"] == pytest.approx(0.25)

    @patch("packages.quantum.jobs.handlers.strategy_autotune.ENABLE_PAPER_AUTOTUNE", False)
    def test_insufficient_samples_skips(self):
        """Fewer outcomes than min_samples should skip."""
        from packages.quantum.jobs.handlers.strategy_autotune import _evaluate_and_update

        outcomes = [_LIVE_WIN] * 5
        client, _ = _make_supabase(outcomes)

        result = asyncio.run(_evaluate_and_update("user-1234-abcd", "spy_opt_autolearn_v6", client, 10))

        assert result["skipped"] is True
        assert result["samples"] == 5

    @patch("packages.quantum.jobs.handlers.strategy_autotune.ENABLE_PAPER_AUTOTUNE", False)
    def test_good_performance_no_update(self):
        """Good win rate + positive PnL → no update."""
        from packages.quantum.jobs.handlers.strategy_autotune import _evaluate_and_update

        outcomes = [_LIVE_WIN] * 10 + [_LIVE_LOSS]
        client, _ = _make_supabase(outcomes)

        result = asyncio.run(_evaluate_and_update("user-1234-abcd", "spy_opt_autolearn_v6", client, 10))

        assert result["updated"] is False
        assert result["win_rate"] == pytest.approx(10 / 11)


# ===========================================================================
# Tests: _mutate_params (regression)
# ===========================================================================

class TestMutateParams:
    """Verify mutation logic hasn't changed."""

    def test_low_win_rate_bumps_conviction_floor(self):
        from packages.quantum.jobs.handlers.strategy_autotune import _mutate_params

        config = {"conviction_floor": 0.40, "stop_loss_pct": 0.05}
        result = _mutate_params(config, "low_win_rate")

        assert result["conviction_floor"] == 0.45
        assert result["stop_loss_pct"] == 0.04

    def test_negative_pnl_reduces_risk(self):
        from packages.quantum.jobs.handlers.strategy_autotune import _mutate_params

        config = {
            "max_risk_pct_portfolio": 0.10,
            "take_profit_pct": 0.10,
            "max_holding_days": 14,
        }
        result = _mutate_params(config, "negative_pnl")

        assert result["max_risk_pct_portfolio"] == pytest.approx(0.085)
        assert result["take_profit_pct"] == 0.08
        assert result["max_holding_days"] == 12

    def test_conviction_floor_caps_at_055(self):
        from packages.quantum.jobs.handlers.strategy_autotune import _mutate_params

        config = {"conviction_floor": 0.53, "stop_loss_pct": 0.03}
        result = _mutate_params(config, "low_win_rate")

        assert result["conviction_floor"] == 0.55


# ===========================================================================
# Tests: win-rate before/after normalization demonstration
# ===========================================================================

class TestWinRateBeforeAfterNormalization:
    """
    Demonstrate that the old outcome_type=='win' logic fails on paper rows,
    and the new normalized classification handles them correctly.
    """

    def test_old_logic_misses_paper_wins(self):
        """
        Before: outcome_type=='win' check → paper rows (trade_closed) all miss.
        This test shows why normalization was needed.
        """
        outcomes = [_PAPER_WIN, _PAPER_WIN, _PAPER_LOSS, _LIVE_WIN, _LIVE_LOSS]

        # OLD logic: count only outcome_type == "win"
        old_wins = sum(1 for o in outcomes if o.get("outcome_type") == "win")
        old_win_rate = old_wins / len(outcomes)

        # Only LIVE_WIN has outcome_type=="win"
        assert old_wins == 1
        assert old_win_rate == pytest.approx(0.2)

    def test_new_logic_counts_paper_wins_correctly(self):
        """
        After: normalized classification -> paper wins counted.
        """
        from packages.quantum.jobs.handlers.strategy_autotune import _compute_metrics

        outcomes = [_PAPER_WIN, _PAPER_WIN, _PAPER_LOSS, _LIVE_WIN, _LIVE_LOSS]
        metrics = _compute_metrics(outcomes)

        # Paper wins + live win = 3 wins out of 5
        assert metrics["wins"] == 3
        assert metrics["win_rate"] == pytest.approx(0.6)


# ===========================================================================
# Tests: no print statements
# ===========================================================================

class TestNoPrintStatements:
    """Verify print-based logging has been removed."""

    def test_no_print_calls_in_strategy_autotune(self):
        import inspect
        from packages.quantum.jobs.handlers import strategy_autotune
        source = inspect.getsource(strategy_autotune)
        # Allow print in __name__ == "__main__" blocks but not in function bodies
        lines = source.split('\n')
        print_lines = [i+1 for i, line in enumerate(lines)
                       if 'print(' in line and '__name__' not in line and '# ' not in line.split('print(')[0]]
        assert print_lines == [], f"print() calls found on lines: {print_lines}"
