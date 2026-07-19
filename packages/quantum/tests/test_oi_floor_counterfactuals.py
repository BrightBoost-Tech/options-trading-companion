"""Lane H — exact-leg OI capture + hypothetical-floor counterfactuals.

Covers the OBSERVE-FIRST OI surface on the quote-provenance recorder:
the 0-vs-absent seam (H9), the pure counterfactual (pass/fail/indeterminate),
env-configurable floors + doctrine-derived references, the note/map join, and
the durable ``details->oi`` payload the route flushes — asserting on the
flushed insert, never recorder internals. Writer fail-soft is re-pinned with
OI present (schema-absent stays a typed no-op).
"""

import json
import unittest
from collections import defaultdict
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from packages.quantum.services.quote_provenance import (
    DEFAULT_OI_FLOOR_CANDIDATES,
    OI_FLOOR_REFERENCES,
    QuoteProvenanceRecorder,
    TABLE_NAME,
    coerce_oi,
    compute_oi_counterfactuals,
    oi_floor_candidates,
    resolve_leg_oi,
)


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
            supabase=supabase, cycle_date=date(2026, 7, 18), **kw)


def _leg(sym, strike, side="buy", bid=1.0, ask=1.1, **extra):
    d = {"symbol": sym, "side": side, "strike": strike,
         "expiry": "2026-08-21", "bid": bid, "ask": ask,
         "mid": (bid + ask) / 2}
    d.update(extra)
    return d


# ─────────────────────────────────────────────────────────────────
# coerce_oi — the 0-vs-absent seam
# ─────────────────────────────────────────────────────────────────
class TestCoerceOI(unittest.TestCase):
    def test_zero_is_a_real_value(self):
        self.assertEqual(coerce_oi(0), 0)
        self.assertEqual(coerce_oi("0"), 0)
        self.assertEqual(coerce_oi(0.0), 0)

    def test_none_and_unparseable_are_unavailable(self):
        self.assertIsNone(coerce_oi(None))
        self.assertIsNone(coerce_oi("not-a-number"))
        self.assertIsNone(coerce_oi(""))

    def test_positive_and_negative(self):
        self.assertEqual(coerce_oi(1234), 1234)
        self.assertEqual(coerce_oi("500"), 500)
        # A negative OI is corruption → typed UNAVAILABLE, never a real value.
        self.assertIsNone(coerce_oi(-5))


# ─────────────────────────────────────────────────────────────────
# resolve_leg_oi — exact-leg join, leg-stamp vs map fallback
# ─────────────────────────────────────────────────────────────────
class TestResolveLegOI(unittest.TestCase):
    def test_absent_is_typed_unavailable_never_zero(self):
        info = resolve_leg_oi(_leg("X260821C00100000", 100.0), None)
        self.assertIsNone(info["oi"])
        self.assertFalse(info["oi_available"])
        self.assertEqual(info["oi_unavailable_reason"], "oi_absent_from_snapshot")

    def test_zero_from_map_is_available(self):
        m = {"X260821C00100000": {"oi": 0, "volume": 0, "source": "alpaca"}}
        info = resolve_leg_oi(_leg("O:X260821C00100000", 100.0), m)
        self.assertEqual(info["oi"], 0)          # a real value
        self.assertTrue(info["oi_available"])
        self.assertIsNone(info["oi_unavailable_reason"])
        self.assertEqual(info["oi_source"], "alpaca")

    def test_map_join_by_bare_contract(self):
        m = {"X260821C00100000": {"oi": 742, "volume": 55,
                                  "source": "polygon", "oi_known_at": "2026-07-18"}}
        info = resolve_leg_oi(_leg("O:X260821C00100000", 100.0), m)
        self.assertEqual(info["oi"], 742)
        self.assertEqual(info["oi_volume"], 55)
        self.assertEqual(info["oi_source"], "polygon")
        self.assertEqual(info["oi_known_at"], "2026-07-18")
        self.assertEqual(info["oi_freshness"], "known_at_present")

    def test_leg_stamp_wins_over_map(self):
        m = {"X260821C00100000": {"oi": 111, "source": "alpaca"}}
        info = resolve_leg_oi(
            _leg("X260821C00100000", 100.0, oi=999, oi_source="stamped"), m)
        self.assertEqual(info["oi"], 999)
        self.assertEqual(info["oi_source"], "stamped")

    def test_known_at_absent_freshness_typed(self):
        m = {"X260821C00100000": {"oi": 300, "source": "alpaca"}}
        info = resolve_leg_oi(_leg("X260821C00100000", 100.0), m)
        self.assertIsNone(info["oi_known_at"])
        self.assertEqual(info["oi_freshness"], "known_at_unavailable")


# ─────────────────────────────────────────────────────────────────
# compute_oi_counterfactuals — pass / fail / indeterminate
# ─────────────────────────────────────────────────────────────────
def _oi_row(oi, available=True):
    return {"oi": oi, "oi_available": available}


class TestCounterfactuals(unittest.TestCase):
    def test_all_above_floor_passes(self):
        rows = [_oi_row(1500), _oi_row(2000)]
        cf = {c["floor"]: c for c in compute_oi_counterfactuals(rows, [100, 1000])}
        self.assertEqual(cf[100]["verdict"], "pass")
        self.assertTrue(cf[100]["would_pass"])
        self.assertEqual(cf[1000]["verdict"], "pass")
        self.assertEqual(cf[1000]["min_leg_oi"], 1500)

    def test_one_below_floor_fails(self):
        rows = [_oi_row(300), _oi_row(1500)]
        cf = {c["floor"]: c for c in compute_oi_counterfactuals(rows, [100, 250, 500, 1000])}
        self.assertEqual(cf[100]["verdict"], "pass")
        self.assertEqual(cf[250]["verdict"], "pass")
        self.assertEqual(cf[500]["verdict"], "fail")
        self.assertTrue(cf[500]["would_fail"])
        self.assertEqual(cf[500]["legs_below_floor"], 1)
        self.assertEqual(cf[1000]["verdict"], "fail")

    def test_zero_oi_fails_positive_floor_not_indeterminate(self):
        # 0 is AVAILABLE — it FAILS floor 100 as a real fail, never abstains.
        rows = [_oi_row(0), _oi_row(5000)]
        cf = {c["floor"]: c for c in compute_oi_counterfactuals(rows, [100])}
        self.assertEqual(cf[100]["verdict"], "fail")
        self.assertFalse(cf[100]["would_pass"])
        self.assertEqual(cf[100]["legs_unknown"], 0)
        self.assertEqual(cf[100]["min_leg_oi"], 0)

    def test_zero_floor_passes_zero_oi(self):
        rows = [_oi_row(0), _oi_row(0)]
        cf = {c["floor"]: c for c in compute_oi_counterfactuals(rows, [0])}
        self.assertEqual(cf[0]["verdict"], "pass")   # 0 >= 0

    def test_any_unavailable_is_indeterminate(self):
        # Even with a huge available leg, one dark leg → INDETERMINATE (H9).
        rows = [_oi_row(None, available=False), _oi_row(99999)]
        cf = {c["floor"]: c for c in compute_oi_counterfactuals(rows, [100, 1000])}
        self.assertEqual(cf[100]["verdict"], "indeterminate")
        self.assertEqual(cf[1000]["verdict"], "indeterminate")
        self.assertFalse(cf[100]["would_pass"])
        self.assertFalse(cf[100]["would_fail"])
        self.assertEqual(cf[100]["legs_unknown"], 1)
        self.assertEqual(cf[100]["legs_evaluable"], 1)


# ─────────────────────────────────────────────────────────────────
# oi_floor_candidates — defaults + env + doctrine references
# ─────────────────────────────────────────────────────────────────
class TestFloorCandidates(unittest.TestCase):
    def test_default_candidates(self):
        with patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("OI_FLOOR_CANDIDATES", None)
            self.assertEqual(oi_floor_candidates(), [100, 250, 500, 1000])
            self.assertEqual(oi_floor_candidates(), DEFAULT_OI_FLOOR_CANDIDATES)

    def test_env_override(self):
        with patch.dict("os.environ", {"OI_FLOOR_CANDIDATES": "50, 750 , 5000"}):
            self.assertEqual(oi_floor_candidates(), [50, 750, 5000])

    def test_env_bad_tokens_filtered_else_default(self):
        with patch.dict("os.environ", {"OI_FLOOR_CANDIDATES": "abc,,-5"}):
            # All tokens invalid → fall back to defaults (never empty).
            self.assertEqual(oi_floor_candidates(), [100, 250, 500, 1000])

    def test_references_anchor_100_and_1000(self):
        # The two doctrine-anchored floors carry their provenance.
        self.assertIn("guardrails", OI_FLOOR_REFERENCES[100])
        self.assertIn("micro_live_config", OI_FLOOR_REFERENCES[1000])


# ─────────────────────────────────────────────────────────────────
# record_spread_verdict → flush : durable details->oi payload
# ─────────────────────────────────────────────────────────────────
class TestDurablePayload(unittest.TestCase):
    def _flush_one(self, legs, oi_by_contract, env=None):
        fake = FakeSupabase()
        rec = _recorder(fake, env=env)
        rec.record_spread_verdict(
            symbol="X", strategy_key="long_call_debit_spread",
            verdict="rejected", reject_reason="spread_too_wide",
            threshold=0.1, option_spread_pct=0.5, legs=legs,
            oi_by_contract=oi_by_contract,
        )
        rec.flush()
        self.assertEqual(len(fake.rows), 1)
        return fake.rows[0]

    def test_details_oi_present_with_counterfactuals(self):
        legs = [_leg("O:X260821C00100000", 100.0),
                _leg("O:X260821C00105000", 105.0, side="sell")]
        m = {
            "X260821C00100000": {"oi": 1500, "volume": 40, "source": "alpaca"},
            "X260821C00105000": {"oi": 300, "volume": 10, "source": "alpaca"},
        }
        row = self._flush_one(legs, m)
        oi = row["details"]["oi"]
        self.assertEqual(oi["legs_total"], 2)
        self.assertEqual(oi["legs_oi_available"], 2)
        self.assertEqual(oi["legs_oi_unavailable"], 0)
        self.assertFalse(oi["any_oi_unavailable"])
        self.assertEqual(oi["min_leg_oi"], 300)
        self.assertEqual(oi["floors_evaluated"], [100, 250, 500, 1000])
        cf = {c["floor"]: c["verdict"] for c in oi["counterfactuals"]}
        self.assertEqual(cf[100], "pass")
        self.assertEqual(cf[250], "pass")
        self.assertEqual(cf[500], "fail")     # 300 < 500
        self.assertEqual(cf[1000], "fail")
        # Per-leg OI rode along on the leg rows too (exact-leg).
        by_contract = {l["contract"]: l for l in row["legs"]}
        self.assertEqual(by_contract["X260821C00100000"]["oi"], 1500)
        self.assertTrue(by_contract["X260821C00100000"]["oi_available"])
        self.assertEqual(by_contract["X260821C00105000"]["oi_volume"], 10)

    def test_zero_and_absent_distinct_in_payload(self):
        # One leg OI=0 (real), one leg dark (absent) → leg set INDETERMINATE.
        legs = [_leg("O:X260821C00100000", 100.0),
                _leg("O:X260821C00105000", 105.0, side="sell")]
        m = {"X260821C00100000": {"oi": 0, "source": "alpaca"}}  # other leg missing
        row = self._flush_one(legs, m)
        oi = row["details"]["oi"]
        self.assertEqual(oi["legs_oi_available"], 1)     # the 0-leg
        self.assertEqual(oi["legs_oi_unavailable"], 1)   # the dark leg
        self.assertTrue(oi["any_oi_unavailable"])
        self.assertEqual(oi["min_leg_oi"], 0)            # 0 is the available min
        by_contract = {l["contract"]: l for l in row["legs"]}
        self.assertEqual(by_contract["X260821C00100000"]["oi"], 0)
        self.assertTrue(by_contract["X260821C00100000"]["oi_available"])
        self.assertIsNone(by_contract["X260821C00105000"]["oi"])
        self.assertFalse(by_contract["X260821C00105000"]["oi_available"])
        cf = {c["floor"]: c["verdict"] for c in oi["counterfactuals"]}
        # Any dark leg → indeterminate at every floor (never fabricated).
        self.assertTrue(all(v == "indeterminate" for v in cf.values()))

    def test_no_oi_map_all_unavailable(self):
        legs = [_leg("O:X260821C00100000", 100.0)]
        row = self._flush_one(legs, None)
        oi = row["details"]["oi"]
        self.assertEqual(oi["legs_oi_available"], 0)
        self.assertTrue(oi["any_oi_unavailable"])
        self.assertIsNone(oi["min_leg_oi"])
        cf = {c["floor"]: c["verdict"] for c in oi["counterfactuals"]}
        self.assertTrue(all(v == "indeterminate" for v in cf.values()))

    def test_env_floors_flow_into_payload(self):
        legs = [_leg("O:X260821C00100000", 100.0)]
        m = {"X260821C00100000": {"oi": 600, "source": "alpaca"}}
        row = self._flush_one(legs, m, env={"OI_FLOOR_CANDIDATES": "500,700"})
        oi = row["details"]["oi"]
        self.assertEqual(oi["floors_evaluated"], [500, 700])
        cf = {c["floor"]: c["verdict"] for c in oi["counterfactuals"]}
        self.assertEqual(cf[500], "pass")   # 600 >= 500
        self.assertEqual(cf[700], "fail")   # 600 < 700

    def test_no_secret_in_oi_payload(self):
        # OI capture must not smuggle any secret-shaped material into the row.
        legs = [_leg("O:X260821C00100000", 100.0)]
        m = {"X260821C00100000": {"oi": 500, "source": "alpaca"}}
        row = self._flush_one(legs, m)
        blob = json.dumps(row)
        self.assertNotIn("apiKey", blob)
        self.assertNotIn("Bearer", blob)


# ─────────────────────────────────────────────────────────────────
# Writer fail-soft is preserved with OI present
# ─────────────────────────────────────────────────────────────────
class TestFailSoftWithOI(unittest.TestCase):
    def _one(self, rec):
        rec.record_spread_verdict(
            symbol="X", strategy_key="k", verdict="rejected",
            reject_reason="spread_too_wide", threshold=0.1,
            option_spread_pct=0.5,
            legs=[_leg("O:X260821C00100000", 100.0)],
            oi_by_contract={"X260821C00100000": {"oi": 500, "source": "alpaca"}},
        )

    def test_schema_absent_typed_noop_with_oi(self):
        fake = FakeSupabase(raise_exc=Exception(
            'relation "option_quote_provenance" does not exist (42P01)'))
        rec = _recorder(fake)
        self._one(rec)
        counts = rec.flush()   # must not raise
        self.assertTrue(counts["schema_absent"])
        self.assertEqual(counts["persist_failures"], 0)
        self.assertEqual(counts["rows_written"], 0)

    def test_generic_failure_counts_loud_with_oi(self):
        fake = FakeSupabase(raise_exc=Exception("connection reset"))
        rec = _recorder(fake)
        self._one(rec)
        counts = rec.flush()
        self.assertEqual(counts["persist_failures"], 1)
        self.assertFalse(counts["schema_absent"])

    def test_disabled_recorder_writes_nothing_with_oi(self):
        fake = FakeSupabase()
        rec = _recorder(fake, enabled=False)
        self._one(rec)
        counts = rec.flush()
        self.assertEqual(fake.rows, [])
        self.assertEqual(counts["rows_written"], 0)

    def test_malformed_oi_map_degrades_to_unavailable(self):
        # A garbage map VALUE must degrade the leg to typed-unavailable, NOT
        # drop the row or raise (fail-soft, observe-first).
        fake = FakeSupabase()
        rec = _recorder(fake)
        rec.record_spread_verdict(
            symbol="X", strategy_key="k", verdict="rejected",
            reject_reason="spread_too_wide", threshold=0.1,
            option_spread_pct=0.5,
            legs=[_leg("O:X260821C00100000", 100.0)],
            oi_by_contract={"X260821C00100000": "not-a-dict"},
        )
        counts = rec.flush()   # must not raise
        self.assertEqual(counts["persist_failures"], 0)
        self.assertEqual(counts["rows_written"], 1)
        row = fake.rows[0]
        self.assertFalse(row["legs"][0]["oi_available"])
        self.assertIsNone(row["legs"][0]["oi"])


if __name__ == "__main__":
    unittest.main()
