"""
Unit tests for close_position_shared helper — PR #6 Commit 3.

Scope: helper's own invariants. Integration (helper composed with
compute_realized_pl end-to-end from a handler's perspective) lands
in Commit 8's regression test matrix.

Test matrix:
    1. Happy path: open position closes cleanly with all 5 fields set
    2. Quantity is forced to 0 regardless of prior value
    3. closed_at defaults to utcnow() if not provided
    4. closed_at respects caller-provided value (Alpaca filled_at
       for reconciled past fills)
    5. Input validation: realized_pl=None → ValueError
    6. Input validation: invalid close_reason → ValueError
    7. Input validation: invalid fill_source → ValueError
    8. realized_pl numeric coercion: non-Decimal input
    9. Idempotency: second call on closed position → PositionAlreadyClosed
       with full diagnostic context
    10. PositionNotFound when row doesn't exist
    11. RuntimeError when UPDATE fails but position isn't closed
        (catch-all race / RLS defense)
    12. All 9 valid close_reason values accepted
    13. All 4 valid fill_source values accepted
"""

import unittest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

from packages.quantum.services.close_helper import (
    close_position_shared,
    PositionAlreadyClosed,
    PositionNotFound,
    _VALID_CLOSE_REASONS,
    _VALID_FILL_SOURCES,
)


class _FakeSupabase:
    """Test double that records UPDATE/SELECT calls against
    paper_positions and returns configurable responses.

    Mimics the Supabase/PostgREST client chain:
        .table(name).update(payload).eq(col, val).neq(col, val).execute()
        .table(name).select(cols).eq(col, val).limit(n).execute()
    """

    def __init__(self):
        self.update_calls = []
        self.select_calls = []
        # Configurable per-call return
        self._update_return_data = []   # list of updated rows
        self._select_return_data = []   # list of rows for diagnostic fetch

    def set_update_returns(self, rows):
        self._update_return_data = rows

    def set_select_returns(self, rows):
        self._select_return_data = rows

    def table(self, name):
        assert name == "paper_positions", f"unexpected table: {name}"
        fc = self
        chain = MagicMock()

        # UPDATE path
        def capture_update(payload):
            call_record = {"payload": payload, "filters": {}}
            upd = MagicMock()

            def on_eq(col, val):
                call_record["filters"][f"{col}_eq"] = val
                eq_chain = MagicMock()

                def on_neq(col2, val2):
                    call_record["filters"][f"{col2}_neq"] = val2
                    neq_chain = MagicMock()
                    neq_chain.execute.return_value = MagicMock(
                        data=list(fc._update_return_data)
                    )
                    return neq_chain

                eq_chain.neq.side_effect = on_neq
                # Direct .execute() on the eq chain (no .neq) also
                # supported so we can handle future variants.
                eq_chain.execute.return_value = MagicMock(
                    data=list(fc._update_return_data)
                )
                return eq_chain

            upd.eq.side_effect = on_eq
            fc.update_calls.append(call_record)
            return upd

        chain.update.side_effect = capture_update

        # SELECT path
        def capture_select(cols):
            call_record = {"cols": cols, "filters": {}}
            sel = MagicMock()

            def on_sel_eq(col, val):
                call_record["filters"][f"{col}_eq"] = val
                eq_chain = MagicMock()

                def on_limit(n):
                    call_record["limit"] = n
                    lim = MagicMock()
                    lim.execute.return_value = MagicMock(
                        data=list(fc._select_return_data)
                    )
                    return lim

                eq_chain.limit.side_effect = on_limit
                return eq_chain

            sel.eq.side_effect = on_sel_eq
            fc.select_calls.append(call_record)
            return sel

        chain.select.side_effect = capture_select
        return chain


POSITION_ID = "pos-abcdef12-3456-7890-1234-567890abcdef"


class TestHappyPath(unittest.TestCase):
    """Successful close writes all required fields."""

    def _successful_close(self, **overrides):
        supabase = _FakeSupabase()
        # UPDATE returns 1 row → happy path
        supabase.set_update_returns([{"id": POSITION_ID}])
        kwargs = {
            "supabase": supabase,
            "position_id": POSITION_ID,
            "realized_pl": Decimal("-204.00"),
            "close_reason": "alpaca_fill_reconciler_standard",
            "fill_source": "alpaca_fill_reconciler",
        }
        kwargs.update(overrides)
        close_position_shared(**kwargs)
        return supabase

    def test_updates_all_required_fields(self):
        supabase = self._successful_close()
        self.assertEqual(len(supabase.update_calls), 1)
        payload = supabase.update_calls[0]["payload"]
        self.assertEqual(payload["status"], "closed")
        self.assertEqual(payload["quantity"], 0)
        self.assertEqual(payload["realized_pl"], "-204.00")
        self.assertEqual(payload["close_reason"], "alpaca_fill_reconciler_standard")
        self.assertEqual(payload["fill_source"], "alpaca_fill_reconciler")
        self.assertIn("closed_at", payload)
        self.assertIn("updated_at", payload)

    def test_filters_on_position_id_and_not_closed(self):
        """Conditional UPDATE must filter on both position_id AND
        status != 'closed' for the atomic compare-and-swap."""
        supabase = self._successful_close()
        filters = supabase.update_calls[0]["filters"]
        self.assertEqual(filters["id_eq"], POSITION_ID)
        self.assertEqual(filters["status_neq"], "closed")

    def test_quantity_is_always_zero_regardless_of_prior(self):
        """Helper sets quantity=0 unconditionally. Prior values on
        the row (e.g., AMZN qty=4 stale rows from Issue 1) get
        zeroed as part of the close."""
        supabase = self._successful_close()
        self.assertEqual(supabase.update_calls[0]["payload"]["quantity"], 0)

    def test_no_diagnostic_select_on_happy_path(self):
        """Single-round-trip happy path. Diagnostic SELECT only
        runs when UPDATE affects zero rows."""
        supabase = self._successful_close()
        self.assertEqual(len(supabase.select_calls), 0)


class TestClosedAtTimestamp(unittest.TestCase):
    def test_default_closed_at_is_utcnow(self):
        supabase = _FakeSupabase()
        supabase.set_update_returns([{"id": POSITION_ID}])
        before = datetime.now(timezone.utc)
        close_position_shared(
            supabase=supabase,
            position_id=POSITION_ID,
            realized_pl=Decimal("100"),
            close_reason="target_profit_hit",
            fill_source="exit_evaluator",
        )
        after = datetime.now(timezone.utc)
        closed_at_iso = supabase.update_calls[0]["payload"]["closed_at"]
        closed_at = datetime.fromisoformat(closed_at_iso)
        self.assertLessEqual(before, closed_at)
        self.assertLessEqual(closed_at, after)

    def test_respects_caller_provided_closed_at(self):
        """Reconciler uses Alpaca's filled_at when booking a past fill."""
        supabase = _FakeSupabase()
        supabase.set_update_returns([{"id": POSITION_ID}])
        alpaca_fill_time = datetime(2026, 4, 17, 17, 15, 11, 251325, tzinfo=timezone.utc)
        close_position_shared(
            supabase=supabase,
            position_id=POSITION_ID,
            realized_pl=Decimal("-204"),
            close_reason="alpaca_fill_reconciler_standard",
            fill_source="alpaca_fill_reconciler",
            closed_at=alpaca_fill_time,
        )
        closed_at_iso = supabase.update_calls[0]["payload"]["closed_at"]
        self.assertEqual(closed_at_iso, alpaca_fill_time.isoformat())


class TestInputValidation(unittest.TestCase):
    """Defense in depth vs DB CHECK constraints."""

    def _helper(self, **overrides):
        """Invoke with valid defaults, apply overrides, expect ValueError."""
        supabase = _FakeSupabase()
        kwargs = {
            "supabase": supabase,
            "position_id": POSITION_ID,
            "realized_pl": Decimal("100"),
            "close_reason": "target_profit_hit",
            "fill_source": "exit_evaluator",
        }
        kwargs.update(overrides)
        return kwargs, supabase

    def test_realized_pl_none_raises(self):
        kwargs, supabase = self._helper(realized_pl=None)
        with self.assertRaises(ValueError) as cm:
            close_position_shared(**kwargs)
        self.assertIn("realized_pl", str(cm.exception))
        # MUST NOT have made any DB calls — fail early.
        self.assertEqual(len(supabase.update_calls), 0)

    def test_invalid_close_reason_raises(self):
        kwargs, supabase = self._helper(close_reason="made_up_reason")
        with self.assertRaises(ValueError) as cm:
            close_position_shared(**kwargs)
        self.assertIn("close_reason", str(cm.exception))
        self.assertEqual(len(supabase.update_calls), 0)

    def test_invalid_fill_source_raises(self):
        kwargs, supabase = self._helper(fill_source="unknown_handler")
        with self.assertRaises(ValueError) as cm:
            close_position_shared(**kwargs)
        self.assertIn("fill_source", str(cm.exception))
        self.assertEqual(len(supabase.update_calls), 0)

    def test_float_realized_pl_coerced_to_decimal_string(self):
        """Accept non-Decimal numeric types for interoperability, but
        internally coerce via Decimal(str(...)) to avoid float
        imprecision in the DB write."""
        supabase = _FakeSupabase()
        supabase.set_update_returns([{"id": POSITION_ID}])
        close_position_shared(
            supabase=supabase,
            position_id=POSITION_ID,
            realized_pl=0.1,  # float
            close_reason="target_profit_hit",
            fill_source="exit_evaluator",
        )
        payload_realized_pl = supabase.update_calls[0]["payload"]["realized_pl"]
        # Should be the string "0.1", not "0.1000000000000000055511151231257827021181583404541015625"
        self.assertEqual(payload_realized_pl, "0.1")

    def test_integer_realized_pl_coerced_cleanly(self):
        supabase = _FakeSupabase()
        supabase.set_update_returns([{"id": POSITION_ID}])
        close_position_shared(
            supabase=supabase,
            position_id=POSITION_ID,
            realized_pl=500,  # int
            close_reason="target_profit_hit",
            fill_source="exit_evaluator",
        )
        self.assertEqual(
            supabase.update_calls[0]["payload"]["realized_pl"], "500"
        )


class TestIdempotency(unittest.TestCase):
    """PositionAlreadyClosed raised on duplicate close attempt, not
    silently accepted."""

    def test_already_closed_raises_with_diagnostic_context(self):
        supabase = _FakeSupabase()
        # UPDATE returns 0 rows (no matching row with status != 'closed')
        supabase.set_update_returns([])
        # Diagnostic SELECT finds the row in closed state
        supabase.set_select_returns([{
            "status": "closed",
            "close_reason": "target_profit_hit",
            "fill_source": "exit_evaluator",
            "closed_at": "2026-04-20T14:58:29.976295+00:00",
        }])

        with self.assertRaises(PositionAlreadyClosed) as cm:
            close_position_shared(
                supabase=supabase,
                position_id=POSITION_ID,
                realized_pl=Decimal("-204"),
                close_reason="alpaca_fill_reconciler_standard",
                fill_source="alpaca_fill_reconciler",
            )

        exc = cm.exception
        self.assertEqual(exc.position_id, POSITION_ID)
        self.assertEqual(exc.new_fill_source, "alpaca_fill_reconciler")
        self.assertEqual(exc.existing_close_reason, "target_profit_hit")
        self.assertEqual(exc.existing_fill_source, "exit_evaluator")
        self.assertEqual(
            exc.existing_closed_at, "2026-04-20T14:58:29.976295+00:00"
        )
        # Message includes all diagnostic fields for log capture.
        self.assertIn(POSITION_ID, str(exc))
        self.assertIn("alpaca_fill_reconciler", str(exc))
        self.assertIn("target_profit_hit", str(exc))
        # UPDATE was attempted (1 call), SELECT was then made for
        # diagnostics (1 call).
        self.assertEqual(len(supabase.update_calls), 1)
        self.assertEqual(len(supabase.select_calls), 1)


class TestPositionNotFound(unittest.TestCase):
    def test_missing_position_raises_not_found(self):
        supabase = _FakeSupabase()
        # UPDATE returns 0 rows, diagnostic SELECT also returns 0 rows
        supabase.set_update_returns([])
        supabase.set_select_returns([])

        with self.assertRaises(PositionNotFound) as cm:
            close_position_shared(
                supabase=supabase,
                position_id="nonexistent-id",
                realized_pl=Decimal("100"),
                close_reason="target_profit_hit",
                fill_source="exit_evaluator",
            )
        self.assertIn("nonexistent-id", str(cm.exception))


class TestUnexpectedRaceCondition(unittest.TestCase):
    """Row exists, status is not 'closed', yet UPDATE affected 0 rows.
    Fall-through path — shouldn't happen under normal flow but we
    fail loudly rather than silently."""

    def test_runtime_error_on_unexpected_zero_rows(self):
        supabase = _FakeSupabase()
        supabase.set_update_returns([])
        # Row exists with a non-'closed' status somehow
        supabase.set_select_returns([{
            "status": "open",  # row exists, not closed
            "close_reason": None,
            "fill_source": None,
            "closed_at": None,
        }])

        with self.assertRaises(RuntimeError) as cm:
            close_position_shared(
                supabase=supabase,
                position_id=POSITION_ID,
                realized_pl=Decimal("100"),
                close_reason="target_profit_hit",
                fill_source="exit_evaluator",
            )
        self.assertIn("0 rows", str(cm.exception))
        self.assertIn("status='open'", str(cm.exception))


class TestEnumAcceptance(unittest.TestCase):
    """All 9 close_reason values and all 4 fill_source values
    accepted by the helper. DB CHECKs enforce the same set."""

    def test_all_9_close_reasons_accepted(self):
        for reason in sorted(_VALID_CLOSE_REASONS):
            supabase = _FakeSupabase()
            supabase.set_update_returns([{"id": POSITION_ID}])
            close_position_shared(
                supabase=supabase,
                position_id=POSITION_ID,
                realized_pl=Decimal("10"),
                close_reason=reason,
                fill_source="exit_evaluator",
            )
            self.assertEqual(
                supabase.update_calls[0]["payload"]["close_reason"], reason
            )

    def test_all_4_fill_sources_accepted(self):
        for source in sorted(_VALID_FILL_SOURCES):
            supabase = _FakeSupabase()
            supabase.set_update_returns([{"id": POSITION_ID}])
            close_position_shared(
                supabase=supabase,
                position_id=POSITION_ID,
                realized_pl=Decimal("10"),
                close_reason="target_profit_hit",
                fill_source=source,
            )
            self.assertEqual(
                supabase.update_calls[0]["payload"]["fill_source"], source
            )


if __name__ == "__main__":
    unittest.main()
