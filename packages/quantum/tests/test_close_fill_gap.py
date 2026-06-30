"""
Unit tests for close_fill_gap — the Phase-3 PRECURSOR instrumentation.

Scope: the pure record/format/threading helpers in
``packages.quantum.services.close_fill_gap``. These are ADDITIVE, observe-only
functions — nothing here drives a close decision; the tests pin the math
(gap_fraction), the degenerate/missing guards, the order_json thread
round-trip, and the unconditional log emission for BOTH a force-close and a
normal close.

Test matrix:
    1. SOFI 06-30 fixture (cross 1.31, mid 1.525, fill 1.36) -> gap ~0.23
    2. compute_gap_fraction degenerate (mid == cross) -> None, no ZeroDivision
    3. compute_gap_fraction missing input(s) -> None
    4. format line: full triple includes the spec fields + numeric gap
    5. format line: missing cross/mid -> fill-only, gap_fraction=NA
    6. format line: degenerate mid==cross -> gap_fraction=None (stamp present)
    7. log emission: force-close (envelope_force_close) emits the line
    8. log emission: normal close (target_profit_hit) emits the line
    9. log_close_fill_gap returns the exact emitted line + never raises
   10. read_stamp / stamp_payload round-trip through order_json
   11. stamp_order_json best-effort: writes merged order_json, never raises
"""

import logging
import unittest
from unittest.mock import MagicMock

from packages.quantum.services.close_fill_gap import (
    CROSS_KEY,
    MID_KEY,
    FILL_KEY,
    GAP_KEY,
    LOG_PREFIX,
    compute_gap_fraction,
    format_close_fill_gap_line,
    log_close_fill_gap,
    read_stamp,
    stamp_payload,
    stamp_order_json,
)

# SOFI 06-30 fixture from the Phase-3 recon.
SOFI_CROSS = 1.31
SOFI_MID = 1.525
SOFI_FILL = 1.36
SOFI_GAP = (SOFI_FILL - SOFI_CROSS) / (SOFI_MID - SOFI_CROSS)  # ~0.2326


class TestComputeGapFraction(unittest.TestCase):
    def test_sofi_fixture_gap_is_about_0_23(self):
        gap = compute_gap_fraction(SOFI_CROSS, SOFI_MID, SOFI_FILL)
        self.assertIsNotNone(gap)
        # ~0.23: filled close to the conservative full-cross estimate.
        self.assertAlmostEqual(gap, 0.2326, places=3)
        self.assertEqual(round(gap, 2), 0.23)

    def test_degenerate_mid_equals_cross_returns_none_no_zerodiv(self):
        # mid == cross would divide by zero — must return None, never raise.
        self.assertIsNone(compute_gap_fraction(1.40, 1.40, 1.42))

    def test_missing_inputs_return_none(self):
        self.assertIsNone(compute_gap_fraction(None, SOFI_MID, SOFI_FILL))
        self.assertIsNone(compute_gap_fraction(SOFI_CROSS, None, SOFI_FILL))
        self.assertIsNone(compute_gap_fraction(SOFI_CROSS, SOFI_MID, None))
        self.assertIsNone(compute_gap_fraction("not-a-number", SOFI_MID, SOFI_FILL))

    def test_string_numerics_are_coerced(self):
        gap = compute_gap_fraction("1.31", "1.525", "1.36")
        self.assertAlmostEqual(gap, SOFI_GAP, places=6)


class TestFormatLine(unittest.TestCase):
    def test_full_triple_line_has_spec_fields_and_numeric_gap(self):
        line = format_close_fill_gap_line(
            "SOFI", "abcd-1234", SOFI_CROSS, SOFI_MID, SOFI_FILL,
            reason="stop_loss_hit",
        )
        self.assertIn(LOG_PREFIX, line)
        self.assertIn("symbol=SOFI", line)
        self.assertIn("position_id=abcd-1234", line)
        self.assertIn("reason=stop_loss_hit", line)
        self.assertIn("cross=1.31", line)
        self.assertIn("mid=1.525", line)
        self.assertIn("fill=1.36", line)
        self.assertIn("gap_fraction=0.23", line)  # ~0.2326
        self.assertNotIn("gap_fraction=NA", line)

    def test_missing_cross_mid_logs_fill_only_with_na(self):
        # Older order without the stage stamp -> fill-only, gap_fraction=NA.
        line = format_close_fill_gap_line(
            "QQQ", "pid-9", None, None, 0.81, reason="target_profit_hit",
        )
        self.assertIn("fill=0.81", line)
        self.assertIn("gap_fraction=NA", line)

    def test_degenerate_line_shows_gap_none(self):
        line = format_close_fill_gap_line(
            "SPY", "pid-x", 1.40, 1.40, 1.42, reason="stop_loss_hit",
        )
        # Stamp present but mid==cross -> computed gap None (distinct from NA).
        self.assertIn("gap_fraction=None", line)


class TestLogEmission(unittest.TestCase):
    """BOTH a force-close and a normal close emit ONE structured line.

    The call sites (paper_exit_evaluator internal-fill block +
    alpaca_order_handler._close_position_on_fill) invoke log_close_fill_gap
    UNCONDITIONALLY for every close, passing the close `reason` through. Here we
    exercise both reason classes via the shared emitter.
    """

    def _emit_and_capture(self, reason):
        log = logging.getLogger(f"test_close_fill_gap.{reason}")
        log.propagate = True
        with self.assertLogs(log, level="INFO") as cm:
            returned = log_close_fill_gap(
                "SOFI", "pid-1", SOFI_CROSS, SOFI_MID, SOFI_FILL,
                reason=reason, log=log,
            )
        return cm.output, returned

    def test_force_close_emits_line(self):
        output, returned = self._emit_and_capture("envelope_force_close")
        joined = "\n".join(output)
        self.assertIn(LOG_PREFIX, joined)
        self.assertIn("reason=envelope_force_close", joined)
        self.assertIn("gap_fraction=0.23", joined)
        # Emitter returns the exact emitted line.
        self.assertIn(returned, joined)

    def test_normal_close_emits_line(self):
        output, returned = self._emit_and_capture("target_profit_hit")
        joined = "\n".join(output)
        self.assertIn(LOG_PREFIX, joined)
        self.assertIn("reason=target_profit_hit", joined)
        self.assertIn("gap_fraction=0.23", joined)
        self.assertIn(returned, joined)

    def test_emitter_never_raises_on_bad_logger(self):
        class _BoomLogger:
            def info(self, *_a, **_k):
                raise RuntimeError("logging backend down")

        # Must NOT propagate — a logging failure can never break a close.
        line = log_close_fill_gap(
            "X", "pid", SOFI_CROSS, SOFI_MID, SOFI_FILL, log=_BoomLogger(),
        )
        self.assertIn(LOG_PREFIX, line)


class TestThreadingRoundTrip(unittest.TestCase):
    def test_read_stamp_round_trip(self):
        order_json = {}
        order_json.update(stamp_payload(SOFI_CROSS, SOFI_MID))
        cross, mid = read_stamp(order_json)
        self.assertEqual(cross, SOFI_CROSS)
        self.assertEqual(mid, SOFI_MID)

    def test_read_stamp_missing_keys_returns_none_none(self):
        self.assertEqual(read_stamp({}), (None, None))
        self.assertEqual(read_stamp(None), (None, None))
        self.assertEqual(read_stamp("not-a-dict"), (None, None))

    def test_stamp_payload_computes_gap_and_keys(self):
        payload = stamp_payload(SOFI_CROSS, SOFI_MID, SOFI_FILL)
        self.assertEqual(payload[CROSS_KEY], SOFI_CROSS)
        self.assertEqual(payload[MID_KEY], SOFI_MID)
        self.assertEqual(payload[FILL_KEY], SOFI_FILL)
        self.assertAlmostEqual(payload[GAP_KEY], SOFI_GAP, places=6)

    def test_stamp_payload_degenerate_gap_is_none(self):
        payload = stamp_payload(1.40, 1.40, 1.42)
        self.assertIsNone(payload[GAP_KEY])


class TestStampOrderJson(unittest.TestCase):
    def test_merges_into_existing_order_json_no_data_loss(self):
        supabase = MagicMock()
        # Existing order_json carries unrelated keys that must survive.
        (
            supabase.table.return_value.select.return_value.eq.return_value
            .single.return_value.execute.return_value.data
        ) = {"order_json": {"source_engine": "paper_exit_evaluator"}}

        stamp_order_json(supabase, "order-1", SOFI_CROSS, SOFI_MID)

        # The update call carried a merged order_json with cross/mid + the
        # pre-existing key intact.
        update_calls = [
            c for c in supabase.table.return_value.update.call_args_list
        ]
        self.assertEqual(len(update_calls), 1)
        written = update_calls[0].args[0]["order_json"]
        self.assertEqual(written[CROSS_KEY], SOFI_CROSS)
        self.assertEqual(written[MID_KEY], SOFI_MID)
        self.assertEqual(written["source_engine"], "paper_exit_evaluator")

    def test_best_effort_never_raises_on_db_error(self):
        supabase = MagicMock()
        supabase.table.side_effect = RuntimeError("db down")
        # Must swallow — never break a close.
        stamp_order_json(supabase, "order-2", SOFI_CROSS, SOFI_MID)


if __name__ == "__main__":
    unittest.main()
