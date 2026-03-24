"""
Tests for the event signal engine.

Tests:
1. Event detection with mock data
2. Event scoring composite scores
3. Event adjustments for pre-earnings, ex-div, opex
4. Graceful degradation without Polygon
5. Biotech amplification
"""

import pytest
from datetime import date, timedelta

from packages.quantum.events.event_engine import (
    EventSignal,
    CatalystEvent,
    detect_events,
    _third_friday,
    _is_biotech_sector,
    _detect_opex_events,
    _finalize_signal,
)
from packages.quantum.events.event_scorer import (
    EventScore,
    score_event_impact,
    _event_type_risk_weight,
)
from packages.quantum.events.event_adjustments import (
    EventAdjustment,
    compute_event_adjustment,
)


# ---------------------------------------------------------------------------
# Event Engine Tests
# ---------------------------------------------------------------------------

class TestThirdFriday:
    def test_march_2026(self):
        f = _third_friday(2026, 3)
        assert f == date(2026, 3, 20)
        assert f.weekday() == 4  # Friday

    def test_april_2026(self):
        f = _third_friday(2026, 4)
        assert f.weekday() == 4

    def test_january_2026(self):
        f = _third_friday(2026, 1)
        assert f == date(2026, 1, 16)
        assert f.weekday() == 4


class TestBiotechDetection:
    def test_biotech_keyword(self):
        assert _is_biotech_sector("Health Care", "pharmaceutical preparations") is True

    def test_non_biotech(self):
        assert _is_biotech_sector("Technology", "computer software") is False

    def test_biotech_in_sector(self):
        assert _is_biotech_sector("Biotech", "") is True


class TestOpexDetection:
    def test_detects_next_opex(self):
        today = date(2026, 3, 10)
        events = _detect_opex_events(today, 30)
        assert len(events) >= 1
        assert events[0].event_type == "opex"
        assert events[0].event_date.weekday() == 4  # Friday

    def test_opex_confidence(self):
        events = _detect_opex_events(date(2026, 3, 1), 30)
        if events:
            assert events[0].confidence == 1.0  # Known dates


class TestFinalizeSignal:
    def test_sorts_by_date(self):
        signal = EventSignal(symbol="TEST")
        signal.events = [
            CatalystEvent(event_type="opex", event_date=date(2026, 4, 17), days_until=30, confidence=1.0),
            CatalystEvent(event_type="earnings", event_date=date(2026, 3, 25), days_until=7, confidence=0.6),
        ]
        _finalize_signal(signal, date(2026, 3, 18))
        assert signal.nearest_event.event_type == "earnings"
        assert signal.nearest_days == 7
        assert signal.is_earnings_week is True

    def test_empty_events(self):
        signal = EventSignal(symbol="TEST")
        _finalize_signal(signal, date(2026, 3, 18))
        assert signal.nearest_event is None
        assert signal.nearest_days == 999


class TestDetectEventsNoPolygon:
    def test_no_crash_without_polygon(self):
        """Should detect opex even without Polygon service."""
        signal = detect_events("SPY", polygon_service=None, as_of=date(2026, 3, 18))
        assert signal.symbol == "SPY"
        # Should at least have opex
        assert any(e.event_type == "opex" for e in signal.events)


# ---------------------------------------------------------------------------
# Event Scorer Tests
# ---------------------------------------------------------------------------

class TestEventScorer:
    def _make_signal(self, days: int = 5, event_type: str = "earnings") -> EventSignal:
        signal = EventSignal(symbol="AAPL")
        signal.events = [CatalystEvent(
            event_type=event_type,
            event_date=date.today() + timedelta(days=days),
            days_until=days,
            confidence=0.8,
        )]
        signal.nearest_event = signal.events[0]
        signal.nearest_days = days
        if days <= 7 and event_type == "earnings":
            signal.is_earnings_week = True
        return signal

    def test_imminent_earnings_high_risk(self):
        signal = self._make_signal(days=1)
        score = score_event_impact(signal, current_iv=0.45, historical_iv=0.25)
        assert score.event_risk_score > 50  # Imminent + elevated IV
        assert score.days_to_event == 1

    def test_distant_earnings_low_risk(self):
        signal = self._make_signal(days=30)
        score = score_event_impact(signal, current_iv=0.30, historical_iv=0.28)
        assert score.event_risk_score < 20

    def test_no_events_zero_scores(self):
        signal = EventSignal(symbol="SPY")
        score = score_event_impact(signal)
        assert score.event_risk_score == 0
        assert score.event_opportunity_score == 0

    def test_iv_premium_increases_risk(self):
        signal = self._make_signal(days=5)
        low_iv = score_event_impact(signal, current_iv=0.26, historical_iv=0.25)
        high_iv = score_event_impact(signal, current_iv=0.45, historical_iv=0.25)
        assert high_iv.event_risk_score > low_iv.event_risk_score

    def test_expected_move(self):
        signal = self._make_signal(days=3)
        score = score_event_impact(
            signal, atm_straddle_price=5.0, spot_price=100.0
        )
        assert score.expected_move_pct == pytest.approx(0.05, abs=0.001)

    def test_event_type_weights(self):
        assert _event_type_risk_weight("earnings") > _event_type_risk_weight("ex_dividend")
        assert _event_type_risk_weight("fda_decision") > _event_type_risk_weight("earnings")

    def test_biotech_amplification(self):
        signal = self._make_signal(days=3)
        signal.is_biotech = False
        normal_score = score_event_impact(signal, current_iv=0.40, historical_iv=0.25)

        signal_bio = self._make_signal(days=3)
        signal_bio.is_biotech = True
        bio_score = score_event_impact(signal_bio, current_iv=0.40, historical_iv=0.25)

        assert bio_score.event_risk_score > normal_score.event_risk_score


# ---------------------------------------------------------------------------
# Event Adjustments Tests
# ---------------------------------------------------------------------------

class TestEventAdjustments:
    def _make_signal_and_score(self, days: int, event_type: str = "earnings"):
        signal = EventSignal(symbol="TEST")
        event = CatalystEvent(
            event_type=event_type,
            event_date=date.today() + timedelta(days=days),
            days_until=days,
            confidence=0.8,
        )
        signal.events = [event]
        signal.nearest_event = event
        signal.nearest_days = days
        score = score_event_impact(signal)
        return signal, score

    def test_earnings_imminent_suppresses(self):
        signal, score = self._make_signal_and_score(1)
        adj = compute_event_adjustment(signal, score)
        assert adj.suppress_new_entry is True
        assert adj.sizing_multiplier == 0.0
        assert adj.require_defined_risk is True

    def test_earnings_week_reduces_sizing(self):
        signal, score = self._make_signal_and_score(5)
        adj = compute_event_adjustment(signal, score)
        assert adj.sizing_multiplier < 1.0
        assert adj.ev_multiplier < 1.0

    def test_earnings_distant_no_adjustment(self):
        signal, score = self._make_signal_and_score(20)
        adj = compute_event_adjustment(signal, score)
        assert adj.sizing_multiplier == 1.0
        assert adj.ev_multiplier == 1.0

    def test_post_earnings_iv_crush_exit(self):
        signal, score = self._make_signal_and_score(0)
        adj = compute_event_adjustment(
            signal, score,
            is_credit_strategy=True,
            current_iv=0.15,
            historical_iv=0.25,
        )
        assert adj.suggest_exit is True

    def test_ex_div_requires_defined_risk(self):
        signal, score = self._make_signal_and_score(1, "ex_dividend")
        adj = compute_event_adjustment(signal, score)
        assert adj.require_defined_risk is True

    def test_opex_reduces_sizing(self):
        signal, score = self._make_signal_and_score(1, "opex")
        adj = compute_event_adjustment(signal, score)
        assert adj.sizing_multiplier < 1.0

    def test_biotech_always_reduces_sizing(self):
        signal, score = self._make_signal_and_score(20)
        signal.is_biotech = True
        adj = compute_event_adjustment(signal, score)
        assert adj.sizing_multiplier < 1.0  # Even at 20 days out

    def test_no_events_no_adjustment(self):
        signal = EventSignal(symbol="SPY")
        score = EventScore(symbol="SPY")
        adj = compute_event_adjustment(signal, score)
        assert adj.sizing_multiplier == 1.0
        assert adj.ev_multiplier == 1.0
        assert adj.suppress_new_entry is False

    def test_to_dict(self):
        signal, score = self._make_signal_and_score(5)
        adj = compute_event_adjustment(signal, score)
        d = adj.to_dict()
        assert "ev_multiplier" in d
        assert "sizing_multiplier" in d
        assert "reason" in d
