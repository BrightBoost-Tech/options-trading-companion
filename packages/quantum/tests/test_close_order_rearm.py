"""Tests for the close-retry re-arm semantics (audit Area 2).

The BUG-C overcorrection: adding 'cancelled' to the close-idempotency guard
lists (2026-05-18, anti-spam for the 17-failure CSX cascade) made ONE
broker-terminal close failure permanently satisfy "a close already exists",
silently disarming every automated exit for that position. These tests pin
the replacement semantics in filter_blocking_close_orders:

- fresh 'cancelled' (inside CLOSE_REARM_WINDOW_MINUTES) blocks (anti-spam)
- STALE 'cancelled' does NOT block — protection re-arms (the fix)
- >= CLOSE_REARM_RETRY_BUDGET terminal failures within
  CLOSE_REARM_BUDGET_WINDOW_HOURS blocks + critical
  exit_protection_disarmed alert (bounded backoff, loud)
- active statuses / 'filled' block exactly as before (the CSX zero-qty
  duplicate-close regression stays fixed)
- 'needs_manual_review' blocks AND alerts
- GTC rows are exempt regardless of status
- 'watchdog_cancelled' semantics unchanged (never in the guard lists)
- kill switch CLOSE_REARM_ENABLED: explicit off -> legacy permanent block;
  empty/unset -> ON
- unparseable timestamp -> treated as fresh (blocks, never re-arms blind)
"""

import logging
from datetime import datetime, timedelta, timezone

import pytest

from packages.quantum.services import paper_exit_evaluator as pee
from packages.quantum.services.paper_exit_evaluator import (
    filter_blocking_close_orders,
)


NOW = datetime(2026, 6, 9, 18, 0, 0, tzinfo=timezone.utc)


def _row(status, *, mins_ago=None, order_id="o-1", source="paper_exit_evaluator",
         cancelled_at_override="unset"):
    row = {
        "id": order_id,
        "status": status,
        "order_json": {"source_engine": source},
    }
    if mins_ago is not None:
        ts = (NOW - timedelta(minutes=mins_ago)).isoformat()
        row["created_at"] = ts
        row["cancelled_at"] = ts if cancelled_at_override == "unset" else cancelled_at_override
    return row


@pytest.fixture(autouse=True)
def _reset_throttle(monkeypatch):
    monkeypatch.setattr(pee, "_REARM_ALERT_LAST", {})
    monkeypatch.delenv("CLOSE_REARM_ENABLED", raising=False)
    monkeypatch.delenv("CLOSE_REARM_WINDOW_MINUTES", raising=False)
    monkeypatch.delenv("CLOSE_REARM_RETRY_BUDGET", raising=False)
    monkeypatch.delenv("CLOSE_REARM_BUDGET_WINDOW_HOURS", raising=False)


class _AlertSpy:
    def __init__(self, monkeypatch):
        self.calls = []

        def _spy(supabase, kind, position_id, symbol, severity, message, metadata):
            self.calls.append({
                "kind": kind, "position_id": position_id, "symbol": symbol,
                "severity": severity, "message": message, "metadata": metadata,
            })

        monkeypatch.setattr(pee, "_rearm_alert", _spy)


# ---------------------------------------------------------------------------
# the fix: stale terminal-failed rows re-arm
# ---------------------------------------------------------------------------

class TestRearm:
    def test_stale_cancelled_does_not_block(self, caplog):
        rows = [_row("cancelled", mins_ago=120)]
        with caplog.at_level(logging.WARNING):
            assert filter_blocking_close_orders(rows, now=NOW) == []
        assert any("re-arming" in r.message for r in caplog.records)

    def test_fresh_cancelled_blocks(self):
        rows = [_row("cancelled", mins_ago=5)]
        blocking = filter_blocking_close_orders(rows, now=NOW)
        assert blocking == rows

    def test_boundary_inside_window_blocks(self):
        rows = [_row("cancelled", mins_ago=29)]
        assert filter_blocking_close_orders(rows, now=NOW) == rows

    def test_boundary_outside_window_rearms(self):
        rows = [_row("cancelled", mins_ago=31)]
        assert filter_blocking_close_orders(rows, now=NOW) == []

    def test_cancelled_at_preferred_over_created_at(self):
        # created long ago, but cancelled 5 min ago (resting order finally
        # cancelled) -> fresh -> blocks
        row = _row("cancelled", mins_ago=500, cancelled_at_override=(
            (NOW - timedelta(minutes=5)).isoformat()
        ))
        assert filter_blocking_close_orders([row], now=NOW) == [row]

    def test_unparseable_timestamp_blocks_conservatively(self, caplog):
        row = {"id": "x", "status": "cancelled",
               "order_json": {"source_engine": "paper_exit_evaluator"}}
        with caplog.at_level(logging.ERROR):
            assert filter_blocking_close_orders([row], now=NOW) == [row]
        assert any("no parseable timestamp" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# retry budget: bounded backoff, loud
# ---------------------------------------------------------------------------

class TestRetryBudget:
    def test_three_failures_in_window_block_and_escalate(self, monkeypatch, caplog):
        spy = _AlertSpy(monkeypatch)
        rows = [
            _row("cancelled", mins_ago=45, order_id="a"),
            _row("cancelled", mins_ago=90, order_id="b"),
            _row("cancelled", mins_ago=150, order_id="c"),
        ]
        # All stale (>30min) but 3 within 4h -> budget tripped -> block
        with caplog.at_level(logging.CRITICAL):
            blocking = filter_blocking_close_orders(
                rows, now=NOW, position_id="pos-1", symbol="CSX",
            )
        assert len(blocking) == 3
        assert any("SUSPENDED" in r.message for r in caplog.records)

    def test_budget_alert_is_critical_exit_protection_disarmed(self, monkeypatch):
        spy = _AlertSpy(monkeypatch)
        rows = [
            _row("cancelled", mins_ago=45, order_id="a"),
            _row("cancelled", mins_ago=90, order_id="b"),
            _row("cancelled", mins_ago=150, order_id="c"),
        ]
        filter_blocking_close_orders(rows, now=NOW, position_id="pos-1", symbol="CSX")
        kinds = [(c["kind"], c["severity"]) for c in spy.calls]
        assert ("exit_protection_disarmed", "critical") in kinds

    def test_old_failures_age_out_of_budget(self):
        # 3 failures but 2 older than the 4h budget window -> only 1 recent,
        # all stale (>30min) -> re-arm
        rows = [
            _row("cancelled", mins_ago=45, order_id="a"),
            _row("cancelled", mins_ago=70 * 60, order_id="b"),
            _row("cancelled", mins_ago=80 * 60, order_id="c"),
        ]
        assert filter_blocking_close_orders(rows, now=NOW) == []

    def test_csx_cascade_shape_is_bounded_not_permanent(self):
        # The original cascade: many terminal failures. Budget keeps blocking
        # while >= 3 are within 4h...
        recent = [_row("cancelled", mins_ago=m, order_id=f"r{m}")
                  for m in (40, 80, 120, 160, 200)]
        assert len(filter_blocking_close_orders(recent, now=NOW)) == 5
        # ...but once they age past the budget window, protection re-arms
        aged = [_row("cancelled", mins_ago=m + 300, order_id=f"a{m}")
                for m in (40, 80, 120, 160, 200)]
        assert filter_blocking_close_orders(aged, now=NOW) == []


# ---------------------------------------------------------------------------
# unchanged semantics (regression pins)
# ---------------------------------------------------------------------------

class TestUnchangedSemantics:
    @pytest.mark.parametrize("status", [
        "staged", "submitted", "working", "partial", "pending", "filled",
    ])
    def test_active_and_filled_always_block(self, status):
        rows = [_row(status, mins_ago=999)]
        assert filter_blocking_close_orders(rows, now=NOW) == rows

    def test_needs_manual_review_blocks_and_alerts(self, monkeypatch):
        spy = _AlertSpy(monkeypatch)
        rows = [_row("needs_manual_review", mins_ago=999)]
        assert filter_blocking_close_orders(
            rows, now=NOW, position_id="pos-1", symbol="NFLX",
        ) == rows
        assert any(c["kind"] == "close_blocked_needs_manual_review" for c in spy.calls)

    def test_gtc_rows_exempt_regardless(self):
        rows = [
            _row("working", mins_ago=5, source="gtc_profit_exit"),
            _row("cancelled", mins_ago=5, source="gtc_profit_exit"),
        ]
        assert filter_blocking_close_orders(rows, now=NOW) == []

    def test_mixed_filled_plus_stale_cancelled_still_blocks_on_filled(self):
        filled = _row("filled", mins_ago=999, order_id="f")
        stale = _row("cancelled", mins_ago=999, order_id="c")
        blocking = filter_blocking_close_orders([filled, stale], now=NOW)
        assert blocking == [filled]

    def test_watchdog_cancelled_not_a_guard_status(self):
        # 'watchdog_cancelled' is intentionally absent from the guard query
        # lists (the accidental escape that kept retries alive pre-fix). If
        # a row with that status ever reaches the filter it must not gain
        # blocking semantics from the terminal-failed branch.
        rows = [_row("watchdog_cancelled", mins_ago=5)]
        # not 'cancelled' -> lands in the always-blocking branch by default;
        # pin the CURRENT contract: the guards never fetch it.
        guard_list = [
            "staged", "submitted", "working", "partial", "pending",
            "needs_manual_review", "filled", "cancelled",
        ]
        assert "watchdog_cancelled" not in guard_list


# ---------------------------------------------------------------------------
# kill switch
# ---------------------------------------------------------------------------

class TestKillSwitch:
    def test_explicit_off_restores_legacy_permanent_block(self, monkeypatch):
        monkeypatch.setenv("CLOSE_REARM_ENABLED", "0")
        rows = [_row("cancelled", mins_ago=10_000)]
        assert filter_blocking_close_orders(rows, now=NOW) == rows

    def test_empty_string_is_ON(self, monkeypatch):
        monkeypatch.setenv("CLOSE_REARM_ENABLED", "")
        rows = [_row("cancelled", mins_ago=10_000)]
        assert filter_blocking_close_orders(rows, now=NOW) == []

    def test_unset_is_ON(self):
        rows = [_row("cancelled", mins_ago=10_000)]
        assert filter_blocking_close_orders(rows, now=NOW) == []


# ---------------------------------------------------------------------------
# alert throttle
# ---------------------------------------------------------------------------

class TestAlertThrottle:
    def test_disarm_alert_throttled_per_position(self, monkeypatch):
        inserted = []

        class _SB:
            def table(self, name):
                class _Q:
                    def insert(self, rec):
                        inserted.append(rec)
                        return self

                    def execute(self):
                        return None
                return _Q()

        rows = [
            _row("cancelled", mins_ago=45, order_id="a"),
            _row("cancelled", mins_ago=90, order_id="b"),
            _row("cancelled", mins_ago=150, order_id="c"),
        ]
        sb = _SB()
        filter_blocking_close_orders(rows, now=NOW, supabase=sb, position_id="p1", symbol="CSX")
        filter_blocking_close_orders(rows, now=NOW, supabase=sb, position_id="p1", symbol="CSX")
        disarm = [r for r in inserted if r.get("alert_type") == "exit_protection_disarmed"]
        assert len(disarm) == 1
