"""GTC resting profit-limit — regression tests.

Pins the four load-bearing properties of the build:
  1. TIF PLUMBING: build_alpaca_order_request reads order_json.time_in_force
     with default "day" — every pre-existing order path is byte-identical
     (entries, closes, anything without an explicit tif emits DAY; unknown
     values coerce to DAY, never GTC).
  2. WATCHDOG EXEMPTION (mandatory): the idle watchdog still cancels DAY
     orders past the threshold but NEVER cancels a GTC order — a resting
     GTC is supposed to idle; without the exemption it would die at the
     first sync.
  3. OCO / INVERSE-OCO: a resting gtc_profit_exit order does NOT satisfy
     the close-idempotency guards (it must not disarm stop/envelope
     force-closes); ordinary close orders still block duplicates.
  4. PLACEMENT (flag-gated, default OFF): flag OFF = pure no-op; flag ON
     places a closing mleg GTC limit at entry x (1 + cohort FLAT tp), with
     #999's is_credit_close marker, inverted legs, and the
     gtc_profit_exit source_engine — and SKIPS time-scaled-default
     positions (cohort unresolved), non-live entries, non-debit shapes,
     and positions that already have a close order.
"""

import copy
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from packages.quantum.brokers.alpaca_order_handler import build_alpaca_order_request
from packages.quantum.brokers import alpaca_order_handler
from packages.quantum.models import TradeTicket
from packages.quantum.services.gtc_profit_exit import maybe_place_gtc_profit_exit
from packages.quantum.services.paper_exit_evaluator import (
    filter_blocking_close_orders,
    is_gtc_profit_exit_order,
)

USER_ID = "user-1"


# ── 1. TIF plumbing ─────────────────────────────────────────────────────────
class TestTifPlumbing:
    def _order(self, order_json_extra=None):
        oj = {
            "symbol": "NFLX",
            "legs": [
                {"symbol": "O:NFLX260702P00085000", "action": "buy", "quantity": 2},
                {"symbol": "O:NFLX260702P00078000", "action": "sell", "quantity": 2},
            ],
            "limit_price": 3.68,
        }
        oj.update(order_json_extra or {})
        return {
            "id": "o-1",
            "order_json": oj,
            "side": "buy",
            "requested_price": 3.68,
            "requested_qty": 2,
        }

    def test_default_is_day_byte_identical(self):
        req = build_alpaca_order_request(self._order())
        assert req["time_in_force"] == "day"

    def test_gtc_passes_through(self):
        req = build_alpaca_order_request(self._order({"time_in_force": "gtc"}))
        assert req["time_in_force"] == "gtc"

    def test_unknown_value_coerces_to_day_never_gtc(self):
        for bogus in ("ioc", "GTC_PLUS", "", None, 7):
            req = build_alpaca_order_request(self._order({"time_in_force": bogus}))
            assert req["time_in_force"] == "day", f"bogus tif {bogus!r} must be day"

    def test_close_order_without_tif_still_day(self):
        order = self._order({"is_credit_close": True})
        order["position_id"] = "pos-1"
        req = build_alpaca_order_request(order)
        assert req["time_in_force"] == "day"
        assert req["limit_price"] == -3.68  # #999 sign convention untouched

    def test_trade_ticket_default_tif_is_day(self):
        t = TradeTicket(symbol="NFLX", legs=[], limit_price=1.0)
        assert t.time_in_force == "day"
        assert t.model_dump()["time_in_force"] == "day"


# ── 2. Watchdog TIF-exemption ──────────────────────────────────────────────
def _iso(dt):
    return dt.isoformat().replace("+00:00", "Z")


def _working_order(idle_seconds, tif=None):
    submitted = datetime.now(timezone.utc) - timedelta(seconds=idle_seconds)
    oj = {"symbol": "NFLX", "legs": []}
    if tif is not None:
        oj["time_in_force"] = tif
    return {
        "id": "order-1",
        "alpaca_order_id": "alp-1",
        "status": "working",
        "submitted_at": _iso(submitted),
        "broker_status": "new",
        "position_id": None,
        "side": "buy",
        "order_json": oj,
    }


def _mock_supabase_for_poll(order):
    updates = []

    def make_chain(name):
        chain = MagicMock()
        chain.execute.return_value = MagicMock(data=[])
        for m in ("select", "eq", "neq", "in_", "gte", "lte", "lt", "limit"):
            getattr(chain, m).return_value = chain
        chain.not_ = MagicMock()
        chain.not_.is_.return_value = chain
        if name == "paper_portfolios":
            chain.execute.return_value = MagicMock(data=[{"id": "port-1"}])
        elif name == "paper_orders":
            chain.execute.return_value = MagicMock(data=[order])

            def capture_update(payload):
                updates.append(payload)
                up = MagicMock()
                up.eq.return_value.execute.return_value = MagicMock()
                return up

            chain.update.side_effect = capture_update
        return chain

    sb = MagicMock()
    sb.table.side_effect = make_chain
    return sb, updates


class TestWatchdogTifExemption(unittest.TestCase):
    def test_day_order_still_cancelled_past_threshold(self):
        order = _working_order(idle_seconds=292)  # no tif → day
        sb, updates = _mock_supabase_for_poll(order)
        alpaca = MagicMock()
        alpaca.get_order.return_value = {"status": "new", "filled_qty": 0}

        alpaca_order_handler.poll_pending_orders(alpaca, sb, USER_ID)

        alpaca.cancel_order.assert_called_once_with("alp-1")
        self.assertTrue(
            [p for p in updates if p.get("status") == "watchdog_cancelled"]
        )

    def test_gtc_order_exempt_from_idle_cancel(self):
        """A GTC resting order idle WAY past the threshold is NOT cancelled
        — it is supposed to rest."""
        order = _working_order(idle_seconds=6 * 3600, tif="gtc")  # 6 hours idle
        sb, updates = _mock_supabase_for_poll(order)
        alpaca = MagicMock()
        alpaca.get_order.return_value = {"status": "new", "filled_qty": 0}

        alpaca_order_handler.poll_pending_orders(alpaca, sb, USER_ID)

        alpaca.cancel_order.assert_not_called()
        self.assertFalse(
            [p for p in updates if p.get("status") == "watchdog_cancelled"]
        )
        # And it still syncs normally (status update written, not skipped)
        self.assertTrue(updates, "GTC order should still be status-synced")


# ── 3. OCO / inverse-OCO: idempotency-guard exemption ──────────────────────
class TestCloseGuardExemption:
    def test_gtc_profit_order_does_not_block(self):
        rows = [
            {"id": "gtc-1", "status": "working",
             "order_json": {"source_engine": "gtc_profit_exit"}},
        ]
        assert is_gtc_profit_exit_order(rows[0]) is True
        assert filter_blocking_close_orders(rows) == []

    def test_normal_close_order_still_blocks(self):
        rows = [
            {"id": "close-1", "status": "working",
             "order_json": {"source_engine": "paper_exit_evaluator"}},
        ]
        assert filter_blocking_close_orders(rows) == rows

    def test_mixed_rows_keep_only_real_blockers(self):
        gtc = {"id": "gtc-1", "status": "cancelled",
               "order_json": {"source_engine": "gtc_profit_exit"}}
        real = {"id": "close-1", "status": "filled",
                "order_json": {"source_engine": "paper_exit_evaluator"}}
        assert filter_blocking_close_orders([gtc, real]) == [real]

    def test_missing_order_json_blocks_conservatively(self):
        rows = [{"id": "x", "status": "working", "order_json": None}]
        assert filter_blocking_close_orders(rows) == rows


# ── 4. Placement (flag-gated) ──────────────────────────────────────────────
ENTRY_ORDER = {
    "id": "entry-1",
    "position_id": "pos-1",
    "suggestion_id": "sugg-1",
    "execution_mode": "alpaca_live",
    "alpaca_order_id": "alp-entry-1",
    "avg_fill_price": 3.08,
}

POSITION = {
    "id": "pos-1",
    "symbol": "NFLX",
    "status": "open",
    "quantity": 2.0,
    "avg_entry_price": 3.08,
    "portfolio_id": "port-live",
    "cohort_id": "cohort-agg",
    "trace_id": "trace-1",
    "legs": [
        {"symbol": "O:NFLX260702P00085000", "action": "buy", "type": "put",
         "strike": 85, "expiry": "2026-07-02"},
        {"symbol": "O:NFLX260702P00079000", "action": "sell", "type": "put",
         "strike": 79, "expiry": "2026-07-02"},
    ],
}


def _placement_supabase(entry=None, position=None, cohort_tp=0.50,
                        existing_close=None):
    entry = ENTRY_ORDER if entry is None else entry
    position = POSITION if position is None else position

    def make_chain(name):
        chain = MagicMock()
        for m in ("select", "eq", "in_", "limit", "order"):
            getattr(chain, m).return_value = chain
        if name == "paper_orders":
            # .single() path → the entry order; plain execute → existing-close
            chain.single.return_value.execute.return_value = MagicMock(data=entry)
            chain.execute.return_value = MagicMock(data=existing_close or [])
        elif name == "paper_positions":
            chain.single.return_value.execute.return_value = MagicMock(data=position)
        elif name == "policy_lab_cohorts":
            data = ([{"policy_config": {"target_profit_pct": cohort_tp}}]
                    if cohort_tp is not None else [])
            chain.execute.return_value = MagicMock(data=data)
        return chain

    sb = MagicMock()
    sb.table.side_effect = make_chain
    return sb


class TestPlacement:
    def test_flag_off_is_pure_noop(self, monkeypatch):
        monkeypatch.delenv("GTC_PROFIT_EXIT_ENABLED", raising=False)
        sb = MagicMock()
        out = maybe_place_gtc_profit_exit(sb, "entry-1", USER_ID)
        assert out == {"placed": False, "reason": "flag_off"}
        sb.table.assert_not_called()

    def test_flag_on_places_gtc_at_flat_cohort_credit(self, monkeypatch):
        monkeypatch.setenv("GTC_PROFIT_EXIT_ENABLED", "true")  # lenient parse
        sb = _placement_supabase(cohort_tp=0.50)
        staged = {}

        def capture_stage(supabase, analytics, user_id, ticket, portfolio_id,
                          position_id=None, trace_id_override=None, **kw):
            staged.update({"ticket": ticket, "portfolio_id": portfolio_id,
                           "position_id": position_id})
            return "gtc-order-1"

        with patch("packages.quantum.paper_endpoints._stage_order_internal",
                   side_effect=capture_stage), \
             patch("packages.quantum.paper_endpoints.get_analytics_service",
                   return_value=MagicMock()):
            out = maybe_place_gtc_profit_exit(sb, "entry-1", USER_ID)

        assert out["placed"] is True
        assert out["gtc_order_id"] == "gtc-order-1"
        assert out["target_credit"] == pytest.approx(4.62)  # 3.08 × 1.5

        t = staged["ticket"]
        assert t.time_in_force == "gtc"
        assert t.is_credit_close is True          # #999 reused, not modified
        assert t.source_engine == "gtc_profit_exit"
        assert t.limit_price == pytest.approx(4.62)
        assert t.quantity == 2
        # legs inverted: bought 85P → sell; sold 79P → buy
        actions = {leg.symbol if hasattr(leg, "symbol") else leg["symbol"]:
                   (leg.action if hasattr(leg, "action") else leg["action"])
                   for leg in t.legs}
        assert actions["O:NFLX260702P00085000"] == "sell"
        assert actions["O:NFLX260702P00079000"] == "buy"
        assert staged["position_id"] == "pos-1"

    def test_skips_time_scaled_default_position(self, monkeypatch):
        """Cohort unresolved → default time-scaled target governs → a
        static GTC price would be wrong → SKIP."""
        monkeypatch.setenv("GTC_PROFIT_EXIT_ENABLED", "1")
        sb = _placement_supabase(cohort_tp=None)
        out = maybe_place_gtc_profit_exit(sb, "entry-1", USER_ID)
        assert out["placed"] is False
        assert out["reason"] == "no_flat_cohort_target_time_scaled_default"

    def test_skips_when_close_order_exists(self, monkeypatch):
        monkeypatch.setenv("GTC_PROFIT_EXIT_ENABLED", "1")
        sb = _placement_supabase(
            existing_close=[{"id": "close-1", "status": "working"}]
        )
        out = maybe_place_gtc_profit_exit(sb, "entry-1", USER_ID)
        assert out["placed"] is False
        assert out["reason"] == "close_order_already_exists"

    def test_skips_non_live_entry(self, monkeypatch):
        monkeypatch.setenv("GTC_PROFIT_EXIT_ENABLED", "1")
        entry = dict(ENTRY_ORDER, execution_mode="shadow_blocked")
        sb = _placement_supabase(entry=entry)
        out = maybe_place_gtc_profit_exit(sb, "entry-1", USER_ID)
        assert out["placed"] is False
        assert out["reason"] == "not_live_entry"

    def test_skips_short_or_single_leg(self, monkeypatch):
        monkeypatch.setenv("GTC_PROFIT_EXIT_ENABLED", "1")
        for pos in (dict(POSITION, quantity=-2.0),
                    dict(POSITION, legs=[POSITION["legs"][0]])):
            sb = _placement_supabase(position=pos)
            out = maybe_place_gtc_profit_exit(sb, "entry-1", USER_ID)
            assert out["placed"] is False
            assert out["reason"] == "not_open_long_multileg"

    def test_fail_soft_on_error(self, monkeypatch):
        monkeypatch.setenv("GTC_PROFIT_EXIT_ENABLED", "1")
        sb = MagicMock()
        sb.table.side_effect = RuntimeError("db down")
        out = maybe_place_gtc_profit_exit(sb, "entry-1", USER_ID)
        assert out["placed"] is False
        assert out["reason"].startswith("error:")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
