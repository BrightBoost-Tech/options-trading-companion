"""Mirror parity — quote/OI provenance writer row-shape ↔ the
option_quote_provenance schema conventions (20260717120000).

The OI 0-vs-absent semantics are exercised in test_oi_floor_counterfactuals.
This file pins the SCHEMA-CONVENTIONS parity the writer depends on:

  1. Every TOP-LEVEL key the recorder flushes is a column the migration
     declares (no phantom-column write — the #1098 42703 class). Checked for
     BOTH row shapes (fetch_event and leg_set).
  2. OI is carried ONLY inside jsonb (``legs`` / ``details``), never as a typed
     top-level column — precisely so the missing-vs-zero distinction (None→JSON
     null vs 0) survives serialization instead of collapsing in a numeric
     column. Proven with a json round-trip of a flushed row.
  3. The schema-absent no-op marker is a typed counter, never a raise (the
     migration ships unapplied).

Failure/observation injected at the ORIGIN (the recorder inputs); the durable
row shape asserted at the TOP (the flushed insert payload).
"""

import json
import re
import unittest
from collections import defaultdict
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from packages.quantum.services.quote_provenance import (
    QuoteProvenanceRecorder,
    TABLE_NAME,
)

MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "supabase" / "migrations"
    / "20260717120000_option_quote_provenance.sql"
)

_TYPES = "uuid|timestamptz|date|text|jsonb|bigint|numeric|boolean|integer"


def _declared_columns():
    """Column names declared in the CREATE TABLE option_quote_provenance body."""
    sql = MIGRATION.read_text(encoding="utf-8")
    m = re.search(
        r"CREATE TABLE IF NOT EXISTS option_quote_provenance\s*\((.*?)\n\);",
        sql, re.S,
    )
    assert m is not None, "CREATE TABLE body not found"
    cols = set()
    for line in m.group(1).splitlines():
        line = line.strip()
        if line.startswith("--") or not line:
            continue
        cm = re.match(rf"([a-z_]+)\s+(?:{_TYPES})\b", line)
        if cm:
            cols.add(cm.group(1))
    return cols


# ── Fake supabase capturing the batched insert ──────────────────────────────
class _FakeQuery:
    def __init__(self, parent, table_name):
        self._parent = parent
        self._table = table_name

    def insert(self, payload):
        self._payload = payload
        return self

    def execute(self):
        return self._parent._execute(self._table, self._payload)


class FakeSupabase:
    def __init__(self, raise_exc=None):
        self.inserted = defaultdict(list)
        self.raise_exc = raise_exc

    def table(self, name):
        return _FakeQuery(self, name)

    def _execute(self, table, payload):
        if self.raise_exc is not None:
            raise self.raise_exc
        self.inserted[table].append(payload)
        return SimpleNamespace(data=payload)

    @property
    def rows(self):
        flat = []
        for batch in self.inserted[TABLE_NAME]:
            flat.extend(batch)
        return flat


def _recorder(supabase=None, env=None, **kw):
    env = env or {}
    with patch.dict("os.environ", env, clear=False):
        return QuoteProvenanceRecorder(
            supabase=supabase, cycle_date=date(2026, 7, 18),
            job_run_id="jr-oqp-1", **kw)


def _leg(sym, strike, side="buy", bid=1.0, ask=1.1):
    return {"symbol": sym, "side": side, "strike": strike,
            "expiry": "2026-08-21", "bid": bid, "ask": ask,
            "mid": (bid + ask) / 2}


DECLARED = _declared_columns()


class TestDeclaredColumnParse(unittest.TestCase):
    def test_core_columns_present(self):
        # Sanity that the parser found the schema (not an empty set).
        for c in ("record_type", "legs", "details", "cycle_date",
                  "job_run_id", "verdict", "selected", "sampled"):
            self.assertIn(c, DECLARED)
        # There is deliberately NO top-level oi column — OI lives in jsonb.
        self.assertNotIn("oi", DECLARED)


class TestNoPhantomColumns(unittest.TestCase):
    def _flush_rows(self, recorder_fn):
        fake = FakeSupabase()
        rec = _recorder(fake, env={"QUOTE_PROVENANCE_SAMPLE_N": "1"})
        recorder_fn(rec)
        rec.flush()
        return fake.rows

    def test_leg_set_row_keys_are_all_declared_columns(self):
        def emit(rec):
            legs = [_leg("O:X260821C00100000", 100.0),
                    _leg("O:X260821C00105000", 105.0, side="sell")]
            m = {"X260821C00100000": {"oi": 0, "source": "alpaca"}}  # zero + missing
            rec.record_spread_verdict(
                symbol="X", strategy_key="long_call_debit_spread",
                verdict="rejected", reject_reason="spread_too_wide",
                threshold=0.1, option_spread_pct=0.5, legs=legs,
                oi_by_contract=m)

        rows = self._flush_rows(emit)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["record_type"], "leg_set")
        undeclared = set(row) - DECLARED
        self.assertEqual(undeclared, set(),
                         f"leg_set row writes phantom columns: {undeclared}")

    def test_fetch_event_row_keys_are_all_declared_columns(self):
        def emit(rec):
            rec.record_snapshot_boundary(
                requested_options=["O:X260821C00058000"],
                alpaca_snaps={}, polygon_snaps={},
                dark=["O:X260821C00058000"],
                fetch_meta={"requests": [
                    {"boundary": "alpaca_options_snapshots", "status": 429}]},
                requested_at="2026-07-18T16:00:00",
                received_at="2026-07-18T16:00:01")

        rows = self._flush_rows(emit)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["record_type"], "fetch_event")
        undeclared = set(row) - DECLARED
        self.assertEqual(undeclared, set(),
                         f"fetch_event row writes phantom columns: {undeclared}")

    def test_chain_fetch_event_row_keys_are_all_declared_columns(self):
        def emit(rec):
            rec.record_chain_boundary(
                "X", source="polygon_fallback", contracts_count=42,
                fetch_meta={"requests": [{"status": 200}]},
                requested_at="t0", received_at="t1")

        rows = self._flush_rows(emit)
        self.assertEqual(len(rows), 1)
        undeclared = set(rows[0]) - DECLARED
        self.assertEqual(undeclared, set(),
                         f"chain fetch_event writes phantom columns: {undeclared}")


class TestOIStaysInJsonbMissingVsZeroSurvives(unittest.TestCase):
    def _one(self, oi_map):
        fake = FakeSupabase()
        rec = _recorder(fake, env={"QUOTE_PROVENANCE_SAMPLE_N": "1"})
        legs = [_leg("O:X260821C00100000", 100.0),
                _leg("O:X260821C00105000", 105.0, side="sell")]
        rec.record_spread_verdict(
            symbol="X", strategy_key="k", verdict="rejected",
            reject_reason="spread_too_wide", threshold=0.1,
            option_spread_pct=0.5, legs=legs, oi_by_contract=oi_map)
        rec.flush()
        self.assertEqual(len(fake.rows), 1)
        return fake.rows[0]

    def test_no_top_level_oi_column(self):
        # OI must never be a top-level key (the schema has no oi column); it
        # rides jsonb so 0-vs-null is preserved rather than collapsed.
        row = self._one({"X260821C00100000": {"oi": 0, "source": "alpaca"}})
        self.assertNotIn("oi", row)

    def test_zero_and_missing_survive_json_round_trip_distinctly(self):
        # One leg OI=0 (available), one leg dark (missing). After a JSON
        # round-trip — exactly what PostgREST does to the jsonb column — 0 stays
        # 0 and missing stays null; they never collapse to the same value.
        row = self._one({"X260821C00100000": {"oi": 0, "source": "alpaca"}})
        round_tripped = json.loads(json.dumps(row))
        legs = {l["contract"]: l for l in round_tripped["legs"]}

        zero_leg = legs["X260821C00100000"]
        self.assertEqual(zero_leg["oi"], 0)              # a real value
        self.assertTrue(zero_leg["oi_available"])
        self.assertIsNone(zero_leg["oi_unavailable_reason"])

        missing_leg = legs["X260821C00105000"]
        self.assertIsNone(missing_leg["oi"])             # JSON null, not 0
        self.assertFalse(missing_leg["oi_available"])
        self.assertEqual(missing_leg["oi_unavailable_reason"],
                         "oi_absent_from_snapshot")

        # 0 != null must hold explicitly (the H9 seam).
        self.assertNotEqual(zero_leg["oi"], missing_leg["oi"])
        # details.oi echoes both classes.
        det_oi = round_tripped["details"]["oi"]
        self.assertEqual(det_oi["legs_oi_available"], 1)
        self.assertEqual(det_oi["legs_oi_unavailable"], 1)
        self.assertEqual(det_oi["min_leg_oi"], 0)        # 0 is the available min

    def test_all_missing_min_leg_oi_is_null_not_zero(self):
        row = self._one(None)  # no OI map → every leg unavailable
        det_oi = json.loads(json.dumps(row))["details"]["oi"]
        self.assertIsNone(det_oi["min_leg_oi"])          # null, never a fake 0
        self.assertEqual(det_oi["legs_oi_available"], 0)


class TestSchemaAbsentMarker(unittest.TestCase):
    def test_schema_absent_is_typed_noop_not_raise(self):
        fake = FakeSupabase(raise_exc=Exception(
            'relation "option_quote_provenance" does not exist (42P01)'))
        rec = _recorder(fake)
        rec.record_spread_verdict(
            symbol="X", strategy_key="k", verdict="rejected",
            reject_reason="spread_too_wide", threshold=0.1,
            option_spread_pct=0.5, legs=[_leg("O:X260821C00100000", 100.0)])
        counts = rec.flush()  # must not raise
        self.assertTrue(counts["schema_absent"])
        self.assertEqual(counts["schema_absent_noops"], 1)
        self.assertEqual(counts["persist_failures"], 0)
        self.assertEqual(counts["rows_written"], 0)


if __name__ == "__main__":
    unittest.main()
