"""
Shadow-fill realism (TCM 1.1.0 / fill_model natural_v1) — regression tests.

The defect (2026-06-04 diagnostic): the cohort shadow books filled 100% of
generated trades at exact mid via simulate_fill's missing-quote fallback,
contaminating calibration/learning inputs with two biases:
  - PRICE: fills at mid (live crosses toward natural; ≤5% of entry cost,
    bounded by the scanner's 10% combo-width gate);
  - SELECTION (dominant): shadow fills 100% vs live's ~12% instant-or-never.

The fix pins here:
  1. PRICE — the fallback applies the cross cost the TCM already stored at
     staging (tcm.expected_spread_cost_usd), adverse of mid: buys fill
     HIGHER, sells fill LOWER. Degradation when the stored cost is absent:
     the 5% half-width bound. Exact-mid fills no longer occur.
  2. LABEL — every simulated fill carries would_be_live_marketable so
     consumers can FILTER to the live-marketable subset. Label, not gate:
     fills still happen (cohort volume preserved). None (UNKNOWN, never
     False) when the quote is missing; None for multi-leg combos (the quote
     is leg-1-only — a combo limit cannot be judged against one leg's NBBO).
  3. ISOLATION (load-bearing) — simulate_fill never mutates the input order;
     requested_price (the column live submission reads) is untouched.
     Reversibility: fill_model/tcm_version segregate new fills from legacy
     mid-filled rows; no backfill.
"""

import copy
import importlib
import random
import sys

import pytest

# Defense against cross-test pollution: test_inbox_ranker_comprehensive.py
# replaces sys.modules["packages.quantum.execution.transaction_cost_model"]
# with a MagicMock at module level (session-wide leak). That file collects
# alphabetically BEFORE this one, so a plain import here would bind the mock.
# Evict any mock and re-import the real module.
sys.modules.pop("packages.quantum.execution.transaction_cost_model", None)
_tcm_module = importlib.import_module(
    "packages.quantum.execution.transaction_cost_model"
)
TransactionCostModel = _tcm_module.TransactionCostModel
_live_marketability_label = _tcm_module._live_marketability_label


def _spread_order(**overrides):
    """A NFLX-replica 2-leg debit spread order (the 2026-06-03 shadow fill)."""
    order = {
        "id": "order-nflx-replica",
        "status": "staged",
        "requested_qty": 3,
        "filled_qty": 0,
        "avg_fill_price": 0,
        "order_type": "limit",
        "requested_price": 3.68,
        "side": "buy",
        "order_json": {
            "symbol": "NFLX",
            "legs": [
                {"symbol": "O:NFLX260702P00085000", "action": "buy", "quantity": 3},
                {"symbol": "O:NFLX260702P00078000", "action": "sell", "quantity": 3},
            ],
        },
        "tcm": {
            "fill_probability": 0.5,
            "expected_fill_price": 3.68,
            "expected_spread_cost_usd": 11.04,
            "tcm_version": "1.0.0",
        },
    }
    order.update(overrides)
    return order


def _single_leg_order(**overrides):
    order = {
        "id": "order-single-leg",
        "status": "staged",
        "requested_qty": 2,
        "filled_qty": 0,
        "avg_fill_price": 0,
        "order_type": "limit",
        "requested_price": 100.0,
        "side": "buy",
        "order_json": {
            "symbol": "AAPL",
            "legs": [{"symbol": "O:AAPL260702C00310000", "action": "buy", "quantity": 2}],
        },
        "tcm": {"fill_probability": 0.5, "expected_fill_price": 100.0},
    }
    order.update(overrides)
    return order


class TestPriceFix:
    """Fallback fills are adverse of mid by the stored cross cost."""

    def test_debit_spread_fills_above_mid_by_stored_cross(self):
        order = _spread_order()
        result = TransactionCostModel.simulate_fill(order, quote=None)

        assert result["status"] == "filled"
        # 11.04 USD / (3 contracts * 100) = 0.0368/share adverse, buy pays MORE
        assert result["avg_fill_price"] == pytest.approx(3.68 + 0.0368, abs=1e-4)
        assert result["avg_fill_price"] > 3.68
        assert result["last_fill_price"] == result["avg_fill_price"]
        assert result["simulated_cross_per_share"] == pytest.approx(0.0368, abs=1e-4)
        assert result["simulated_cross_source"] == "tcm_expected_spread_cost"
        assert result["mid_price_basis"] == pytest.approx(3.68)

    def test_exact_mid_fill_no_longer_occurs_for_spreads(self):
        """The 4/4-at-exact-mid (deviation $0.0000) defect is dead."""
        result = TransactionCostModel.simulate_fill(_spread_order(), quote=None)
        assert result["avg_fill_price"] != pytest.approx(3.68, abs=1e-9)

    def test_credit_sell_fills_below_mid(self):
        """Adverse direction: a sell RECEIVES less than mid (not more)."""
        order = _spread_order(
            side="sell",
            requested_price=1.50,
            tcm={
                "fill_probability": 0.5,
                "expected_fill_price": 1.50,
                "expected_spread_cost_usd": 6.00,  # / (3*100) = 0.02/share
            },
        )
        result = TransactionCostModel.simulate_fill(order, quote=None)

        assert result["status"] == "filled"
        assert result["avg_fill_price"] == pytest.approx(1.50 - 0.02, abs=1e-4)
        assert result["avg_fill_price"] < 1.50

    def test_sell_price_floor_clamped_above_zero(self):
        order = _spread_order(
            side="sell",
            requested_price=0.02,
            tcm={"expected_fill_price": 0.02, "expected_spread_cost_usd": 30.0},
        )
        result = TransactionCostModel.simulate_fill(order, quote=None)
        assert result["avg_fill_price"] >= 0.01

    def test_degradation_half_width_bound_when_cost_absent(self):
        """No expected_spread_cost_usd → 5% half-width bound, never exact mid."""
        order = _spread_order(tcm={"fill_probability": 0.5, "expected_fill_price": 3.68})
        result = TransactionCostModel.simulate_fill(order, quote=None)

        assert result["status"] == "filled"
        assert result["avg_fill_price"] == pytest.approx(3.68 * 1.05, abs=1e-4)
        assert result["simulated_cross_source"] == "half_width_bound_estimate"
        assert result["avg_fill_price"] != pytest.approx(3.68, abs=1e-9)

    def test_degradation_sell_side(self):
        order = _spread_order(
            side="sell",
            tcm={"fill_probability": 0.5, "expected_fill_price": 3.68},
        )
        result = TransactionCostModel.simulate_fill(order, quote=None)
        assert result["avg_fill_price"] == pytest.approx(3.68 * 0.95, abs=1e-4)


class TestMarketabilityLabel:
    """Label, never gate. None = UNKNOWN (missing quote / combo), not False."""

    def test_label_null_when_quote_missing(self):
        result = TransactionCostModel.simulate_fill(_spread_order(), quote=None)
        assert result["would_be_live_marketable"] is None
        assert result["marketability_basis"] == "quote_missing"

    def test_label_null_when_quote_invalid(self):
        result = TransactionCostModel.simulate_fill(
            _spread_order(), quote={"bid_price": 0, "ask_price": 0}
        )
        assert result["would_be_live_marketable"] is None
        assert result["marketability_basis"] == "quote_missing"

    def test_single_leg_marketable_true(self):
        """Buy limit at/through the ask = instantly marketable → True."""
        order = _single_leg_order(requested_price=100.5)
        quote = {"bid_price": 99.0, "ask_price": 100.0}
        result = TransactionCostModel.simulate_fill(order, quote)

        assert result["status"] == "filled"
        assert result["would_be_live_marketable"] is True
        assert result["marketability_basis"] == "single_leg_nbbo"

    def test_single_leg_resting_false(self):
        """An inside-spread fill (rested at arrival) → False, not True."""
        order = _single_leg_order(requested_price=99.9)  # inside 99/100
        quote = {"bid_price": 99.0, "ask_price": 100.0}
        # prob = (99.9-99)/1 * 0.5 = 0.45; pick a seed whose draw fills.
        seed = next(s for s in range(1000) if random.Random(s).random() < 0.45)
        result = TransactionCostModel.simulate_fill(order, quote, seed=seed)

        assert result["status"] == "filled"
        assert result["would_be_live_marketable"] is False
        assert result["marketability_basis"] == "single_leg_nbbo"

    def test_multi_leg_label_null_even_with_quote(self):
        """A combo limit must NOT be judged against one leg's NBBO — no
        fabricated verdict for spreads."""
        order = _spread_order()
        quote = {"bid_price": 1.00, "ask_price": 1.20}  # leg-1 NBBO
        result = TransactionCostModel.simulate_fill(order, quote)

        # ask (1.20) <= combo limit (3.68) → the quote path fills it, but the
        # marketability verdict must stay UNKNOWN for combos.
        assert result["status"] == "filled"
        assert result["would_be_live_marketable"] is None
        assert result["marketability_basis"] == "multi_leg_combo_nbbo_unavailable"

    def test_label_does_not_gate_volume(self):
        """The fill still HAPPENS (cohort volume preserved) — the label only
        tags it."""
        result = TransactionCostModel.simulate_fill(_spread_order(), quote=None)
        assert result["status"] == "filled"
        assert result["filled_qty"] == 3
        assert result["last_fill_qty"] == 3
        assert result["would_be_live_marketable"] is None  # tagged, not blocked

    def test_label_helper_market_order(self):
        label = _live_marketability_label(
            _single_leg_order(order_type="market"), 99.0, 100.0, None, "market"
        )
        assert label["would_be_live_marketable"] is True
        assert label["marketability_basis"] == "market_order"


class TestIsolationInvariant:
    """Load-bearing: simulate_fill writes only the fill RESULT. The input
    order — including requested_price, the column live submission reads —
    is never mutated."""

    def test_requested_price_never_mutated(self):
        order = _spread_order()
        before = copy.deepcopy(order)
        result = TransactionCostModel.simulate_fill(order, quote=None)

        assert order == before, "simulate_fill mutated the input order"
        assert order["requested_price"] == 3.68
        assert "requested_price" not in result

    def test_quote_path_does_not_mutate_order(self):
        order = _single_leg_order(requested_price=100.5)
        before = copy.deepcopy(order)
        TransactionCostModel.simulate_fill(order, {"bid_price": 99.0, "ask_price": 100.0})
        assert order == before

    def test_source_has_no_requested_price_write(self):
        """Negative assertion at the source level: simulate_fill's module
        never assigns into order['requested_price']."""
        import os

        path = os.path.join(
            os.path.dirname(__file__), "..", "execution", "transaction_cost_model.py"
        )
        with open(path, "r") as f:
            source = f.read()
        assert 'order["requested_price"] =' not in source
        assert "order['requested_price'] =" not in source


class TestReversibility:
    """fill_model + version segregate new fills from legacy mid-filled rows."""

    def test_fill_model_stamped_on_fallback_fill(self):
        result = TransactionCostModel.simulate_fill(_spread_order(), quote=None)
        assert result["fill_model"] == "natural_v1"

    def test_fill_model_stamped_on_quote_path_fill(self):
        order = _single_leg_order(requested_price=100.5)
        result = TransactionCostModel.simulate_fill(
            order, {"bid_price": 99.0, "ask_price": 100.0}
        )
        assert result["fill_model"] == "natural_v1"

    def test_tcm_version_bumped(self):
        assert TransactionCostModel.VERSION == "1.1.0"

    def test_commit_merge_helper_preserves_staging_tcm(self):
        """_fill_realism_tcm_update merges realism fields into the existing
        tcm blob (staging fields kept) and returns None for non-TCM fills
        (e.g. broker-path rows) so their tcm is untouched."""
        from packages.quantum.paper_endpoints import _fill_realism_tcm_update

        order = _spread_order()
        fill_res = TransactionCostModel.simulate_fill(order, quote=None)
        merged = _fill_realism_tcm_update(order, fill_res)

        assert merged is not None
        # staging fields preserved
        assert merged["expected_spread_cost_usd"] == 11.04
        assert merged["fill_probability"] == 0.5
        # realism fields added
        assert merged["fill_model"] == "natural_v1"
        assert merged["would_be_live_marketable"] is None
        assert merged["marketability_basis"] == "quote_missing"
        assert merged["simulated_cross_per_share"] == pytest.approx(0.0368, abs=1e-4)
        # the order's own tcm blob is not mutated in place
        assert "fill_model" not in order["tcm"]

        # non-TCM fill result (no fill_model) → None → caller leaves tcm alone
        assert _fill_realism_tcm_update(order, {"status": "filled"}) is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
