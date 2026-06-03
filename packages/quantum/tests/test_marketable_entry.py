"""High-EV-gated marketable-from-start entry pricing — regression tests.

Pins the hard constraints of the live fill-aggression lever:
  - HIGH-EV GATE: cross only when net EV >= K x the actual cross cost
    (K a named env-calibratable assumption); below the gate => passive mid.
  - DIRECTION: debit prices UP toward the combo natural, credit DOWN —
    never past natural (capped at natural, cent-rounded).
  - NO-QUOTE (load-bearing): missing per-leg NBBO => deterministic
    'no_quote_no_aggression' passive-mid fallback — never a silent mid
    upgrade and never a blind estimated cross.
  - BUDGET: re-checked AT the marketable price; over-ceiling => no upgrade
    (the unchanged mid order is within ceiling).
  - FLAG OFF = byte-identical submission price (would-be decision logged
    only); flag ON = gated marketable applied.
  - Scope: live entries only (alpaca_live + suggestion-born, not closes);
    fail-soft (errors preserve passive mid).
"""

import copy
from unittest.mock import MagicMock

import pytest

from packages.quantum.execution.marketable_entry import (
    DEFAULT_EV_CROSS_K,
    compute_marketable_decision,
    maybe_apply_marketable_entry,
)


# ── Fixtures: NFLX-replica debit spread (2026-06-03 numbers) ───────────────
LONG = "O:NFLX260702P00085000"
SHORT = "O:NFLX260702P00078000"


def _order(**overrides):
    order = {
        "id": "order-1",
        "suggestion_id": "sugg-1",
        "position_id": None,
        "execution_mode": "alpaca_live",
        "order_type": "limit",
        "side": "buy",
        "requested_qty": 2,
        "requested_price": 3.68,
        "tcm": {"expected_spread_cost_usd": 7.36},
        "order_json": {
            "symbol": "NFLX",
            "legs": [
                {"symbol": LONG, "action": "buy", "quantity": 2, "strike": 85},
                {"symbol": SHORT, "action": "sell", "quantity": 2, "strike": 78},
            ],
        },
    }
    order.update(overrides)
    return order


def _suggestion(**overrides):
    sugg = {
        "net_ev": 82.08,
        "ev": 86.58,
        "sizing_metadata": {"risk_budget_dollars": 830.17},
    }
    sugg.update(overrides)
    return sugg


def _quotes(long_bid=5.50, long_ask=5.66, short_bid=1.92, short_ask=2.04):
    # mids: long 5.58, short 1.98 -> combo mid 3.60-ish; natural = 5.66-1.92
    return {
        LONG: {"bid": long_bid, "ask": long_ask},
        SHORT: {"bid": short_bid, "ask": short_ask},
    }


# natural for the default quotes: 5.66 - 1.92 = 3.74; staged mid 3.68
# cross = 0.06/share -> $12 total on 2 contracts; EV 82.08 >= 3 x 12 = 36 ✓
# max_loss at marketable = 3.74 * 200 = $748 <= budget 830.17 ✓


class TestHighEvGate:
    def test_high_ev_candidate_upgrades_to_marketable(self):
        d = compute_marketable_decision(_order(), _suggestion(), _quotes())
        assert d["upgrade"] is True
        assert d["reason"] == "marketable_applied"
        assert d["marketable_price"] == pytest.approx(3.74)
        assert d["cross_cost_total"] == pytest.approx(12.0)
        assert d["gate"]["passed"] is True

    def test_low_ev_candidate_keeps_passive_mid(self):
        # May micro-era class: EV $13 vs threshold 3 x $12 = $36 -> no cross
        d = compute_marketable_decision(
            _order(), _suggestion(net_ev=13.17, ev=13.17), _quotes()
        )
        assert d["upgrade"] is False
        assert d["reason"] == "ev_gate_failed"
        assert d["gate"]["passed"] is False

    def test_ev_unavailable_keeps_passive_mid(self):
        d = compute_marketable_decision(
            _order(), _suggestion(net_ev=None, ev=None), _quotes()
        )
        assert d["upgrade"] is False
        assert d["reason"] == "ev_unavailable"

    def test_k_is_respected(self):
        # Same numbers, K=10: threshold $120 > EV 82 -> gate fails
        d = compute_marketable_decision(_order(), _suggestion(), _quotes(), k=10.0)
        assert d["upgrade"] is False
        assert d["reason"] == "ev_gate_failed"
        assert d["gate"]["k"] == 10.0

    def test_default_k_is_three(self):
        assert DEFAULT_EV_CROSS_K == 3.0


class TestDirectionAndNaturalCap:
    def test_debit_prices_up_never_past_natural(self):
        d = compute_marketable_decision(_order(), _suggestion(), _quotes())
        natural = 5.66 - 1.92
        assert d["marketable_price"] > 3.68  # adverse: pays more
        assert d["marketable_price"] <= round(natural, 2) + 1e-9  # never past

    def test_credit_prices_down_never_past_natural(self):
        # Net-credit combo: sell the 85, buy the 78. Staged credit 1.50.
        order = _order(
            side="sell",
            requested_price=1.50,
            order_json={
                "symbol": "NFLX",
                "legs": [
                    {"symbol": LONG, "action": "sell", "quantity": 2, "strike": 85},
                    {"symbol": SHORT, "action": "buy", "quantity": 2, "strike": 78},
                ],
            },
        )
        # natural credit = sell bid - buy ask = 5.50 - 2.04 = 3.46?? use
        # realistic credit quotes instead: short leg rich, long leg cheap.
        quotes = {
            LONG: {"bid": 2.10, "ask": 2.26},   # sold leg: natural takes BID
            SHORT: {"bid": 0.62, "ask": 0.74},  # bought leg: natural pays ASK
        }
        # mid credit = 2.18 - 0.68 = 1.50 (staged); natural = 2.10 - 0.74 = 1.36
        sugg = _suggestion(net_ev=200.0, sizing_metadata={"risk_budget_dollars": 2000.0})
        d = compute_marketable_decision(order, sugg, quotes)
        assert d["upgrade"] is True
        assert d["marketable_price"] == pytest.approx(1.36)
        assert d["marketable_price"] < 1.50          # adverse: receives less
        assert d["marketable_price"] >= 1.36 - 1e-9  # never below natural

    def test_already_marketable_left_alone(self):
        # Market moved down: natural (3.50) below staged mid (3.68) -> no change
        d = compute_marketable_decision(
            _order(), _suggestion(), _quotes(long_bid=5.30, long_ask=5.42, short_bid=1.92)
        )
        assert d["upgrade"] is False
        assert d["reason"] == "already_marketable"


class TestNoQuoteFallback:
    """Load-bearing: no NBBO => passive mid with a logged reason — never a
    silent mid fill, never a blind estimated cross."""

    def test_missing_leg_quote_no_aggression(self):
        quotes = _quotes()
        quotes[SHORT] = None
        d = compute_marketable_decision(_order(), _suggestion(), quotes)
        assert d["upgrade"] is False
        assert d["reason"] == "no_quote_no_aggression"
        assert d["quote_status"] == f"missing:{SHORT}"
        # never a guessed cross: no marketable price computed at all
        assert d["marketable_price"] is None
        assert d["cross_per_share"] is None

    def test_zero_bid_ask_treated_as_missing(self):
        # The Polygon guardrail returns zeros on failure — zeros are missing.
        quotes = _quotes()
        quotes[LONG] = {"bid": 0.0, "ask": 0.0}
        d = compute_marketable_decision(_order(), _suggestion(), quotes)
        assert d["upgrade"] is False
        assert d["reason"] == "no_quote_no_aggression"

    def test_crossed_quote_treated_as_missing(self):
        quotes = _quotes()
        quotes[LONG] = {"bid": 5.70, "ask": 5.50}  # ask < bid: garbage
        d = compute_marketable_decision(_order(), _suggestion(), quotes)
        assert d["reason"] == "no_quote_no_aggression"


class TestBudgetRecheck:
    def test_over_ceiling_at_marketable_no_upgrade(self):
        # Budget only covers the mid-priced order: 3.68*200=736 fits 740,
        # but marketable 3.74*200=748 would exceed -> keep passive mid.
        sugg = _suggestion(sizing_metadata={"risk_budget_dollars": 740.0})
        d = compute_marketable_decision(_order(), sugg, _quotes())
        assert d["upgrade"] is False
        assert d["reason"] == "budget_ceiling_at_marketable"
        assert d["budget"]["passed"] is False
        assert d["budget"]["max_loss_at_marketable"] == pytest.approx(748.0)

    def test_within_ceiling_at_marketable_upgrades(self):
        d = compute_marketable_decision(_order(), _suggestion(), _quotes())
        assert d["budget"]["passed"] is True
        assert d["upgrade"] is True

    def test_budget_unavailable_no_upgrade(self):
        sugg = _suggestion(sizing_metadata={})
        d = compute_marketable_decision(_order(), sugg, _quotes())
        assert d["upgrade"] is False
        assert d["reason"] == "risk_budget_unavailable"

    def test_credit_max_loss_uses_width_minus_credit(self):
        order = _order(
            side="sell",
            requested_price=1.50,
            order_json={
                "symbol": "NFLX",
                "legs": [
                    {"symbol": LONG, "action": "sell", "quantity": 2, "strike": 85},
                    {"symbol": SHORT, "action": "buy", "quantity": 2, "strike": 78},
                ],
            },
        )
        quotes = {
            LONG: {"bid": 2.10, "ask": 2.26},
            SHORT: {"bid": 0.62, "ask": 0.74},
        }
        # width 7, natural credit 1.36 -> max_loss = (7-1.36)*200 = 1128
        sugg = _suggestion(net_ev=200.0, sizing_metadata={"risk_budget_dollars": 1100.0})
        d = compute_marketable_decision(order, sugg, quotes)
        assert d["upgrade"] is False
        assert d["reason"] == "budget_ceiling_at_marketable"
        assert d["budget"]["max_loss_at_marketable"] == pytest.approx(1128.0)


# ── Wrapper: flag gating, scope guards, persistence, fail-soft ─────────────
def _mock_supabase(suggestion=None):
    sb = MagicMock()

    def table_side_effect(name):
        t = MagicMock()
        if name == "trade_suggestions":
            t.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
                data=suggestion
            )
        return t

    sb.table.side_effect = table_side_effect
    return sb


class TestWrapperFlagGating:
    def test_flag_off_price_byte_identical_decision_logged(self, monkeypatch):
        monkeypatch.delenv("MARKETABLE_ENTRY_ENABLED", raising=False)
        order = _order()
        before_price = order["requested_price"]
        sb = _mock_supabase(_suggestion())
        out = maybe_apply_marketable_entry(
            sb, order, "user-1", fetch_quote=lambda s: _quotes()[s]
        )
        assert out["requested_price"] == before_price  # byte-identical price
        me = out["tcm"]["marketable_entry"]
        assert me["mode"] == "would_be"
        assert me["upgrade"] is True  # it WOULD have crossed
        assert me["flag_on"] is False

    def test_flag_on_applies_marketable_price(self, monkeypatch):
        monkeypatch.setenv("MARKETABLE_ENTRY_ENABLED", "1")
        order = _order()
        sb = _mock_supabase(_suggestion())
        out = maybe_apply_marketable_entry(
            sb, order, "user-1", fetch_quote=lambda s: _quotes()[s]
        )
        assert out["requested_price"] == pytest.approx(3.74)
        me = out["tcm"]["marketable_entry"]
        assert me["mode"] == "applied"
        assert me["staged_mid"] == pytest.approx(3.68)  # recorded for slippage measurement

    def test_flag_on_low_ev_stays_passive(self, monkeypatch):
        monkeypatch.setenv("MARKETABLE_ENTRY_ENABLED", "1")
        order = _order()
        sb = _mock_supabase(_suggestion(net_ev=13.17, ev=13.17))
        out = maybe_apply_marketable_entry(
            sb, order, "user-1", fetch_quote=lambda s: _quotes()[s]
        )
        assert out["requested_price"] == pytest.approx(3.68)
        assert out["tcm"]["marketable_entry"]["reason"] == "ev_gate_failed"

    def test_flag_on_no_quote_stays_passive_with_reason(self, monkeypatch):
        monkeypatch.setenv("MARKETABLE_ENTRY_ENABLED", "1")
        order = _order()
        sb = _mock_supabase(_suggestion())
        out = maybe_apply_marketable_entry(
            sb, order, "user-1", fetch_quote=lambda s: None
        )
        assert out["requested_price"] == pytest.approx(3.68)
        assert out["tcm"]["marketable_entry"]["reason"] == "no_quote_no_aggression"


class TestWrapperScopeGuards:
    """Non-live / non-entry orders pass through untouched — no DB writes,
    no quote fetches."""

    def test_non_live_execution_mode_untouched(self, monkeypatch):
        monkeypatch.setenv("MARKETABLE_ENTRY_ENABLED", "1")
        for mode in ("alpaca_paper", "internal_paper", "shadow_blocked"):
            order = _order(execution_mode=mode)
            before = copy.deepcopy(order)
            sb = _mock_supabase(_suggestion())
            out = maybe_apply_marketable_entry(
                sb, order, "user-1",
                fetch_quote=lambda s: pytest.fail("must not fetch quotes"),
            )
            assert out == before
            sb.table.assert_not_called()

    def test_close_order_untouched(self, monkeypatch):
        monkeypatch.setenv("MARKETABLE_ENTRY_ENABLED", "1")
        order = _order(position_id="pos-1")  # close path
        before = copy.deepcopy(order)
        sb = _mock_supabase(_suggestion())
        out = maybe_apply_marketable_entry(
            sb, order, "user-1",
            fetch_quote=lambda s: pytest.fail("must not fetch quotes"),
        )
        assert out == before
        sb.table.assert_not_called()

    def test_no_suggestion_id_untouched(self, monkeypatch):
        monkeypatch.setenv("MARKETABLE_ENTRY_ENABLED", "1")
        order = _order(suggestion_id=None)
        before = copy.deepcopy(order)
        sb = _mock_supabase()
        out = maybe_apply_marketable_entry(sb, order, "user-1")
        assert out == before
        sb.table.assert_not_called()


class TestWrapperFailSoft:
    def test_fetcher_exception_preserves_passive_mid(self, monkeypatch):
        monkeypatch.setenv("MARKETABLE_ENTRY_ENABLED", "1")
        order = _order()

        def boom(sym):
            raise RuntimeError("polygon down")

        sb = _mock_supabase(_suggestion())
        out = maybe_apply_marketable_entry(sb, order, "user-1", fetch_quote=boom)
        # quote fetch failures degrade to no_quote_no_aggression, mid kept
        assert out["requested_price"] == pytest.approx(3.68)
        assert out["tcm"]["marketable_entry"]["reason"] == "no_quote_no_aggression"

    def test_persist_failure_when_applied_falls_back_to_mid(self, monkeypatch):
        monkeypatch.setenv("MARKETABLE_ENTRY_ENABLED", "1")
        order = _order()
        sb = MagicMock()

        def table_side_effect(name):
            t = MagicMock()
            if name == "trade_suggestions":
                t.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
                    data=_suggestion()
                )
            else:
                t.update.return_value.eq.return_value.execute.side_effect = RuntimeError(
                    "db down"
                )
            return t

        sb.table.side_effect = table_side_effect
        out = maybe_apply_marketable_entry(
            sb, order, "user-1", fetch_quote=lambda s: _quotes()[s]
        )
        # DB row could not record the upgraded price -> do NOT submit it
        assert out["requested_price"] == pytest.approx(3.68)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
