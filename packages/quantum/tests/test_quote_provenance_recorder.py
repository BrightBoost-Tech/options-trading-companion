"""Unit tests for the Lane 4C quote-provenance recorder.

Covers: flag polarity, note→leg-set source joins, crossed/zero-bid
flags, always-persist vs sampling policy, per-cycle volume cap,
schema-absent typed no-op, loud persist-failure counter, and the
secret-absence guarantee at the single persistence seam.
"""

import json
import unittest
from collections import defaultdict
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from packages.quantum.services.quote_provenance import (
    QuoteProvenanceRecorder,
    TABLE_NAME,
    is_provenance_enabled,
    leg_fingerprint,
    scrub,
)


class _FakeQuery:
    def __init__(self, parent, table_name):
        self._parent = parent
        self._table = table_name
        self._payload = None

    def insert(self, payload):
        self._payload = payload
        return self

    def execute(self):
        return self._parent._execute(self._table, self._payload)


class FakeSupabase:
    """Captures batched inserts; scriptable failure."""

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


def _legs(bid=1.00, ask=1.10, sym_a="TEST260821C00100000",
          sym_b="TEST260821C00105000"):
    return [
        {"symbol": sym_a, "side": "buy", "strike": 100.0,
         "expiry": "2026-08-21", "bid": bid, "ask": ask, "mid": (bid + ask) / 2},
        {"symbol": sym_b, "side": "sell", "strike": 105.0,
         "expiry": "2026-08-21", "bid": 0.50, "ask": 0.60, "mid": 0.55},
    ]


def _recorder(supabase=None, env=None, **kw):
    env = env or {}
    with patch.dict("os.environ", env, clear=False):
        return QuoteProvenanceRecorder(
            supabase=supabase, cycle_date=date(2026, 7, 17), **kw)


class TestFlagPolarity(unittest.TestCase):
    def test_default_on(self):
        with patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("QUOTE_PROVENANCE_ENABLED", None)
            self.assertTrue(is_provenance_enabled())

    def test_empty_string_on(self):
        with patch.dict("os.environ", {"QUOTE_PROVENANCE_ENABLED": ""}):
            self.assertTrue(is_provenance_enabled())

    def test_explicit_falsy_off(self):
        for v in ("0", "false", "no", "off", " FALSE "):
            with patch.dict("os.environ", {"QUOTE_PROVENANCE_ENABLED": v}):
                self.assertFalse(is_provenance_enabled(), v)

    def test_truthy_on(self):
        for v in ("1", "true", "yes", "on"):
            with patch.dict("os.environ", {"QUOTE_PROVENANCE_ENABLED": v}):
                self.assertTrue(is_provenance_enabled(), v)


class TestNoteJoin(unittest.TestCase):
    def test_leg_set_joins_note_sources_alpaca(self):
        fake = FakeSupabase()
        rec = _recorder(fake)
        rec.note_quote("O:TEST260821C00100000", source="alpaca",
                       bid=1.0, ask=1.1, mid=1.05, stale_age_ms=1200)
        rec.note_quote("TEST260821C00105000", source="alpaca",
                       bid=0.5, ask=0.6, mid=0.55)
        rec.record_spread_verdict(
            symbol="TEST", strategy_key="long_call_debit_spread",
            verdict="rejected", reject_reason="spread_too_wide",
            threshold=0.10, option_spread_pct=0.42,
            is_credit_spread=False, combo_source="cost_range",
            combo_width_share=0.21, entry_cost_share=0.5,
            max_loss_share=0.5, legs=_legs(),
        )
        rec.flush()
        rows = fake.rows
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["record_type"], "leg_set")
        self.assertEqual(row["source"], "alpaca")
        self.assertEqual(row["verdict"], "rejected")
        self.assertEqual(row["reject_reason"], "spread_too_wide")
        self.assertEqual(row["threshold"], 0.10)
        self.assertEqual(row["spread_basis"]["denominator_basis"],
                         "entry_cost")
        self.assertEqual(row["spread_basis"]["combo_source"], "cost_range")
        self.assertEqual(len(row["legs"]), 2)
        self.assertEqual(row["legs"][0]["source"], "alpaca")
        self.assertEqual(row["legs"][0]["stale_age_ms"], 1200)
        self.assertEqual(row["cycle_date"], "2026-07-17")
        self.assertEqual(row["leg_fingerprint"], leg_fingerprint(_legs()))

    def test_mixed_sources(self):
        fake = FakeSupabase()
        rec = _recorder(fake)
        rec.note_quote("TEST260821C00100000", source="alpaca", bid=1, ask=1.1)
        rec.note_quote("TEST260821C00105000", source="polygon_fallback",
                       bid=0.5, ask=0.6, fallback_reason="429")
        rec.record_spread_verdict(
            symbol="TEST", strategy_key="k", verdict="rejected",
            reject_reason="spread_too_wide", threshold=0.1,
            option_spread_pct=0.5, legs=_legs(),
        )
        rec.flush()
        row = fake.rows[0]
        self.assertEqual(row["source"], "mixed")
        self.assertEqual(row["fallback_reason"], "429")
        srcs = {l["contract"]: l["source"] for l in row["legs"]}
        self.assertEqual(srcs["TEST260821C00100000"], "alpaca")
        self.assertEqual(srcs["TEST260821C00105000"], "polygon_fallback")

    def test_chain_note_fallback_when_no_leg_note(self):
        fake = FakeSupabase()
        rec = _recorder(fake)
        rec.note_chain("TEST", source="polygon_fallback",
                       fallback_reason="miss", contracts_count=42)
        rec.record_spread_verdict(
            symbol="TEST", strategy_key="k", verdict="rejected",
            reject_reason="spread_too_wide", threshold=0.1,
            option_spread_pct=0.5, legs=_legs(),
        )
        rec.flush()
        row = fake.rows[0]
        self.assertEqual(row["source"], "polygon_fallback")
        self.assertEqual(row["fallback_reason"], "miss")

    def test_unknown_source_when_no_notes(self):
        fake = FakeSupabase()
        rec = _recorder(fake)
        rec.record_spread_verdict(
            symbol="TEST", strategy_key="k", verdict="rejected",
            reject_reason="spread_too_wide", threshold=0.1,
            option_spread_pct=0.5, legs=_legs(),
        )
        rec.flush()
        self.assertEqual(fake.rows[0]["source"], "unknown")

    def test_crossed_and_zero_bid_flags(self):
        fake = FakeSupabase()
        rec = _recorder(fake)
        legs = [
            {"symbol": "X260821C00058000", "side": "buy", "strike": 58.0,
             "expiry": "2026-07-17", "bid": 0.0, "ask": 0.0},   # dead leg
            {"symbol": "X260821C00060000", "side": "sell", "strike": 60.0,
             "expiry": "2026-07-17", "bid": 1.20, "ask": 1.10},  # crossed
        ]
        rec.record_spread_verdict(
            symbol="X", strategy_key="k", verdict="rejected",
            reject_reason="spread_too_wide", threshold=0.1,
            option_spread_pct=9.9, legs=legs,
        )
        rec.flush()
        row = fake.rows[0]
        self.assertTrue(row["zero_bid"])
        self.assertTrue(row["crossed"])
        by_contract = {l["contract"]: l for l in row["legs"]}
        self.assertTrue(by_contract["X260821C00058000"]["zero_bid"])
        self.assertFalse(by_contract["X260821C00058000"]["crossed"])
        self.assertTrue(by_contract["X260821C00060000"]["crossed"])

    def test_condor_basis(self):
        fake = FakeSupabase()
        rec = _recorder(fake)
        rec.record_spread_verdict(
            symbol="TEST", strategy_key="iron_condor", verdict="passed",
            threshold=0.25, option_spread_pct=0.12, is_condor=True,
            legs=_legs(),
        )
        rec.mark_selected("TEST", "iron_condor")
        rec.flush()
        row = fake.rows[0]
        self.assertEqual(row["spread_basis"]["denominator_basis"],
                         "max_leg_spread_pct")
        self.assertTrue(row["selected"])


class TestSamplingAndCap(unittest.TestCase):
    def test_rejected_and_selected_always_persist_rest_sampled(self):
        fake = FakeSupabase()
        rec = _recorder(fake, env={"QUOTE_PROVENANCE_SAMPLE_N": "10"})
        # 20 passed (not selected) → 2 sampled; 3 rejected → all;
        # 1 passed+selected → persisted.
        for i in range(20):
            rec.record_spread_verdict(
                symbol=f"P{i}", strategy_key="k", verdict="passed",
                threshold=0.1, option_spread_pct=0.05, legs=_legs(),
            )
        for i in range(3):
            rec.record_spread_verdict(
                symbol=f"R{i}", strategy_key="k", verdict="rejected",
                reject_reason="spread_too_wide", threshold=0.1,
                option_spread_pct=0.5, legs=_legs(),
            )
        rec.record_spread_verdict(
            symbol="SEL", strategy_key="k", verdict="passed",
            threshold=0.1, option_spread_pct=0.05, legs=_legs(),
        )
        rec.mark_selected("SEL", "k")
        counts = rec.flush()
        rows = fake.rows
        rejected = [r for r in rows if r["verdict"] == "rejected"]
        selected = [r for r in rows if r.get("selected")]
        sampled = [r for r in rows if r.get("sampled")]
        self.assertEqual(len(rejected), 3)
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["symbol"], "SEL")
        self.assertEqual(len(sampled), 2)          # 20 // 10
        self.assertEqual(counts["sampled_out"], 18)
        self.assertEqual(len(rows), 6)
        self.assertEqual(counts["rows_written"], 6)

    def test_volume_cap_prioritizes_decision_bearing_rows(self):
        fake = FakeSupabase()
        rec = _recorder(fake, env={
            "QUOTE_PROVENANCE_MAX_ROWS_PER_CYCLE": "5",
            "QUOTE_PROVENANCE_SAMPLE_N": "1",       # keep all → force cap
        })
        for i in range(4):
            rec.record_spread_verdict(
                symbol=f"R{i}", strategy_key="k", verdict="rejected",
                reject_reason="spread_too_wide", threshold=0.1,
                option_spread_pct=0.5, legs=_legs(),
            )
        for i in range(10):
            rec.record_spread_verdict(
                symbol=f"P{i}", strategy_key="k", verdict="passed",
                threshold=0.1, option_spread_pct=0.05, legs=_legs(),
            )
        counts = rec.flush()
        rows = fake.rows
        self.assertEqual(len(rows), 5)
        # 14 records: the in-memory buffer guard (2x cap = 10) absorbed 4,
        # the flush cap dropped 5 more — every dropped row is COUNTED.
        self.assertEqual(counts["buffer_dropped"], 4)
        self.assertEqual(counts["dropped_over_cap"], 5)
        # All 4 rejected survived the cap; only 1 passed row made it.
        self.assertEqual(
            len([r for r in rows if r["verdict"] == "rejected"]), 4)

    def test_anomalous_fetch_events_always_persist(self):
        fake = FakeSupabase()
        rec = _recorder(fake, env={"QUOTE_PROVENANCE_SAMPLE_N": "1000"})
        rec.record_snapshot_boundary(
            requested_options=["O:X260821C00058000"],
            alpaca_snaps={},
            polygon_snaps={},
            dark=["O:X260821C00058000"],
            fetch_meta={"requests": [
                {"boundary": "alpaca_options_snapshots", "status": 429,
                 "symbols_count": 1}]},
            requested_at="2026-07-17T16:00:00",
            received_at="2026-07-17T16:00:01",
        )
        rec.flush()
        rows = fake.rows
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["record_type"], "fetch_event")
        self.assertEqual(row["fallback_reason"], "429")
        self.assertEqual(row["http_statuses"], [429])
        self.assertEqual(row["details"]["dark"], ["O:X260821C00058000"])
        self.assertFalse(row["sampled"])


class TestFailureModes(unittest.TestCase):
    def _one_rejected(self, rec):
        rec.record_spread_verdict(
            symbol="T", strategy_key="k", verdict="rejected",
            reject_reason="spread_too_wide", threshold=0.1,
            option_spread_pct=0.5, legs=_legs(),
        )

    def test_schema_absent_is_typed_noop(self):
        fake = FakeSupabase(raise_exc=Exception(
            'relation "option_quote_provenance" does not exist (42P01)'))
        rec = _recorder(fake)
        self._one_rejected(rec)
        counts = rec.flush()   # must not raise
        self.assertTrue(counts["schema_absent"])
        self.assertEqual(counts["schema_absent_noops"], 1)
        self.assertEqual(counts["persist_failures"], 0)
        self.assertEqual(counts["rows_written"], 0)

    def test_pgrst205_is_schema_absent(self):
        fake = FakeSupabase(raise_exc=Exception(
            "{'code': 'PGRST205', 'message': \"Could not find the table "
            "'public.option_quote_provenance' in the schema cache\"}"))
        rec = _recorder(fake)
        self._one_rejected(rec)
        counts = rec.flush()
        self.assertTrue(counts["schema_absent"])
        self.assertEqual(counts["persist_failures"], 0)

    def test_generic_failure_counts_loud(self):
        fake = FakeSupabase(raise_exc=Exception("connection reset"))
        rec = _recorder(fake)
        self._one_rejected(rec)
        counts = rec.flush()   # must not raise
        self.assertEqual(counts["persist_failures"], 1)
        self.assertFalse(counts["schema_absent"])
        self.assertEqual(counts["rows_written"], 0)

    def test_disabled_recorder_is_total_noop(self):
        fake = FakeSupabase()
        rec = _recorder(fake, enabled=False)
        rec.note_quote("X", source="alpaca", bid=1, ask=2)
        rec.note_chain("T", source="alpaca")
        self._one_rejected(rec)
        rec.mark_selected("T", "k")
        counts = rec.flush()
        self.assertEqual(fake.rows, [])
        self.assertEqual(counts["rows_written"], 0)
        self.assertEqual(counts["buffered_leg_sets"], 0)

    def test_no_supabase_is_noop(self):
        rec = _recorder(None)
        self._one_rejected(rec)
        counts = rec.flush()
        self.assertEqual(counts["rows_written"], 0)
        self.assertEqual(counts["persist_failures"], 0)


class TestSecretAbsence(unittest.TestCase):
    SECRET = "PKTESTKEYID12345SECRETVALUE"

    def test_scrub_redacts_key_like_keys_and_values(self):
        poisoned = {
            "APCA-API-KEY-ID": self.SECRET,
            "authorization": f"Bearer {self.SECRET}",
            "url": f"https://api.polygon.io/v3/snapshot?apiKey={self.SECRET}",
            "nested": [{"secret_key": self.SECRET, "ok": "keep-me"}],
        }
        cleaned = json.dumps(scrub(poisoned))
        self.assertNotIn(self.SECRET, cleaned)
        self.assertIn("keep-me", cleaned)

    def test_flushed_rows_never_contain_secret_material(self):
        fake = FakeSupabase()
        rec = _recorder(fake, env={"QUOTE_PROVENANCE_SAMPLE_N": "1"})
        # Poison every input surface a careless caller could touch.
        rec.record_snapshot_boundary(
            requested_options=["O:T260821C00100000"],
            alpaca_snaps={},
            polygon_snaps={"O:T260821C00100000": {
                "quote": {"bid": 1.0, "ask": 1.1, "mid": 1.05},
                "staleness_ms": 100,
            }},
            dark=[],
            fetch_meta={"requests": [{
                "boundary": "alpaca_options_snapshots", "status": 429,
                "error": f"429 at ?apiKey={self.SECRET}",
                "APCA-API-SECRET-KEY": self.SECRET,
            }]},
            requested_at="t0", received_at="t1",
        )
        rec.record_spread_verdict(
            symbol="T", strategy_key="k", verdict="rejected",
            reject_reason="spread_too_wide", threshold=0.1,
            option_spread_pct=0.5,
            legs=[{"symbol": "T260821C00100000", "side": "buy",
                   "strike": 100.0, "expiry": "2026-08-21",
                   "bid": 1.0, "ask": 1.1}],
        )
        rec.flush()
        blob = json.dumps(fake.rows)
        self.assertNotIn(self.SECRET, blob)
        self.assertGreater(len(fake.rows), 0)


class TestFingerprint(unittest.TestCase):
    def test_deterministic_and_order_independent(self):
        legs = _legs()
        self.assertEqual(leg_fingerprint(legs),
                         leg_fingerprint(list(reversed(legs))))
        self.assertIsNone(leg_fingerprint([]))
        self.assertIsNone(leg_fingerprint(None))
        other = _legs(sym_a="OTHER260821C00100000")
        self.assertNotEqual(leg_fingerprint(legs), leg_fingerprint(other))


if __name__ == "__main__":
    unittest.main()
