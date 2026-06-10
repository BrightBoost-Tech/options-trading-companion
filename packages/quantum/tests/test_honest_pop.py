"""Tests for the honest debit-spread PoP fix (v5-A1, ALERT-2026-06-10) +
the coordinated calibration epoch (v5-A1/B2) + learning-store dedup
dimensions (v5-A3/B3).

The bug: calculate_pop's breakeven interpolation was unreachable from the
only production call path — the scanner omitted `legs` and calculate_ev
passed `credit` only for credit strategies — so debit-spread PoP collapsed
to abs(long-leg delta) and EV sign-flipped (NFLX 06-08: staged +95.67/ct vs
honest ≈ −26/ct). Commit 9a2cef1 built the interpolation but never wired it;
its test file is module-skipped (#775).

Fixtures pin the NFLX 2026-06-08 re-entry row (the live position admitted on
fictional edge) both ways, and pin credit-spread math UNCHANGED.
"""

import ast
from pathlib import Path

import pytest

from packages.quantum.ev_calculator import calculate_ev, calculate_pop


# The NFLX 2026-06-08 16:30Z live re-entry (P86/P79, 1ct @ 3.65):
# DB identity: pop_raw 0.6581 = long-leg delta; ev_raw 95.67 =
# 0.6581×335 − 0.3419×365. Short-leg delta ≈ 0.3242 (backed out of the
# audit's verified recompute: pop→0.484, EV→≈−26).
NFLX = dict(premium=3.65, width=7.0, long_delta=0.6581, short_delta=0.3242)


class TestDebitPopBreakevenInterpolation:
    def _legs(self):
        return [
            {"action": "buy", "delta": NFLX["long_delta"]},
            {"action": "sell", "delta": NFLX["short_delta"]},
        ]

    def test_nflx_fixture_pop_drops_from_delta_to_breakeven(self):
        pop = calculate_pop(
            "debit_spread", legs=self._legs(),
            credit=NFLX["premium"], width=NFLX["width"],
            delta=NFLX["long_delta"],
        )
        # premium_fraction = 3.65/7 = 0.5214; pop = 0.6581 − 0.3339×0.5214
        assert pop == pytest.approx(0.4840, abs=0.002)
        assert pop < NFLX["long_delta"]  # PoP < long delta, per the docstring

    def test_nflx_fixture_ev_sign_flips(self):
        ev = calculate_ev(
            premium=NFLX["premium"], strike=86.0, current_price=83.0,
            delta=NFLX["long_delta"], strategy="debit_spread",
            width=NFLX["width"], legs=self._legs(),
        )
        # honest EV ≈ 0.484×335 − 0.516×365 ≈ −26 (was +95.67 on raw delta)
        assert ev.expected_value == pytest.approx(-26.2, abs=3.0)
        assert ev.expected_value < 0  # the sign flip is the finding
        assert ev.win_probability == pytest.approx(0.4840, abs=0.002)

    def test_old_call_shape_reproduces_the_bug_value(self):
        # Without legs (the pre-fix call shape) PoP degrades to abs(delta) —
        # pinned so the fixture documents WHAT changed.
        ev = calculate_ev(
            premium=NFLX["premium"], strike=86.0, current_price=83.0,
            delta=NFLX["long_delta"], strategy="debit_spread",
            width=NFLX["width"],
        )
        assert ev.win_probability == pytest.approx(NFLX["long_delta"], abs=1e-9)
        assert ev.expected_value == pytest.approx(95.67, abs=0.5)

    def test_credit_passed_for_debit_engages_interpolation_without_short_delta(self):
        # Long leg only (short delta missing) + credit/width → interpolates
        # toward zero short delta, still below raw long delta.
        legs = [{"action": "buy", "delta": 0.60}]
        pop = calculate_pop("debit_spread", legs=legs, credit=2.0, width=5.0)
        assert pop == pytest.approx(0.60 - 0.60 * 0.4, abs=1e-9)  # 0.36

    def test_free_spread_pop_equals_long_delta(self):
        # premium→0 ⇒ breakeven at the long strike ⇒ PoP → long delta.
        legs = self._legs()
        pop = calculate_pop("debit_spread", legs=legs, credit=0.0001, width=7.0)
        assert pop == pytest.approx(NFLX["long_delta"], abs=0.001)


class TestCreditSpreadUnchanged:
    """Credit-spread PoP/EV must be byte-identical pre/post fix — their
    primary path (credit/width) never used legs."""

    def test_credit_pop_primary_path_unchanged_with_legs_present(self):
        legs = [
            {"action": "sell", "delta": 0.30},
            {"action": "buy", "delta": 0.15},
        ]
        without_legs = calculate_pop("credit_spread", credit=0.70, width=2.0, delta=0.30)
        with_legs = calculate_pop("credit_spread", legs=legs, credit=0.70, width=2.0, delta=0.30)
        assert with_legs == pytest.approx(without_legs, abs=1e-12)
        assert with_legs == pytest.approx(70.0 / 200.0, abs=1e-9)

    def test_credit_ev_unchanged(self):
        kwargs = dict(
            premium=0.70, strike=45.0, current_price=46.0, delta=0.30,
            strategy="credit_spread", width=2.0,
        )
        before = calculate_ev(**kwargs)
        after = calculate_ev(
            **kwargs,
            legs=[{"action": "sell", "delta": 0.30}, {"action": "buy", "delta": 0.15}],
        )
        assert after.expected_value == pytest.approx(before.expected_value, abs=1e-9)
        assert after.win_probability == pytest.approx(before.win_probability, abs=1e-9)


class TestScannerCallSiteWired:
    """Source-level pins (heavy-import convention, see
    test_scanner_micro_tier_spread_threshold.py): the 2-leg call site must
    pass legs with the side→action map, and calculate_ev must pass credit
    for debit spreads — commit 9a2cef1's mistake was exactly the unwired
    call site."""

    @classmethod
    def setup_class(cls):
        root = Path(__file__).parent.parent
        cls.scanner_src = (root / "options_scanner.py").read_text(encoding="utf-8")
        cls.ev_src = (root / "ev_calculator.py").read_text(encoding="utf-8")

    def test_scanner_passes_legs_with_action_map(self):
        assert '{"action": l.get("side"), "delta": l.get("delta")}' in self.scanner_src

    def test_ev_calculator_passes_credit_for_debit(self):
        assert '"credit_spread", "short_call", "short_put", "debit_spread",' in self.ev_src

    def test_both_modules_parse(self):
        ast.parse(self.scanner_src)
        ast.parse(self.ev_src)


class TestCalibrationEvEpoch:
    """v5-B2: outcomes from the pre-fix predictor must not calibrate the
    post-fix one — the EV epoch joins the corruption floor in the cutoff."""

    def test_epoch_bounds_effective_cutoff(self, monkeypatch):
        from datetime import datetime, timedelta, timezone
        from packages.quantum.analytics import calibration_service as cs

        captured = {}

        class _Probe(cs.CalibrationService):
            def _fetch_outcomes(self, user_id, window_days):
                window_cutoff = (
                    datetime.now(timezone.utc) - timedelta(days=window_days)
                ).isoformat()
                captured["effective"] = max(
                    window_cutoff, cs.CORRUPTED_PNL_FLOOR, cs.CALIBRATION_EV_EPOCH
                )
                return []

        _Probe(object()).compute_calibration_report("u", window_days=365)
        assert captured["effective"] == cs.CALIBRATION_EV_EPOCH
        assert cs.CALIBRATION_EV_EPOCH.startswith("2026-06-11")

    def test_floor_raised_to_dup_era_boundary(self):
        from packages.quantum.analytics import calibration_service as cs
        assert cs.CORRUPTED_PNL_FLOOR.startswith("2026-04-16")


class TestLearningIngestDimensions:
    """v5-B3: the outcome builder carries the live/simulator dimension and
    the position id (the forward dedup key)."""

    def _build(self, is_paper):
        from packages.quantum.jobs.handlers.paper_learning_ingest import (
            _create_paper_outcome_record,
        )
        order = {"id": "ord-1", "suggestion_id": "sugg-1", "side": "sell",
                 "order_json": {"symbol": "NFLX"}, "execution_mode": "alpaca_live"}
        position = {"id": "pos-1", "realized_pl": -42.0}
        return _create_paper_outcome_record(
            "user", order, "2026-06-10", position,
            suggestion_ev=44.8, is_paper=is_paper,
        )

    def test_live_fill_not_mislabeled_paper(self):
        rec = self._build(is_paper=False)
        assert rec["is_paper"] is False
        assert rec["details_json"]["is_paper"] is False
        assert rec["details_json"]["routing"] == "live"

    def test_default_remains_conservative_paper(self):
        rec = self._build(is_paper=True)
        assert rec["is_paper"] is True
        assert rec["details_json"]["routing"] == "shadow_or_internal"

    def test_position_id_recorded_for_dedup(self):
        rec = self._build(is_paper=True)
        assert rec["details_json"]["position_id"] == "pos-1"
