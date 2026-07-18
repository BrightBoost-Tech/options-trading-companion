"""Truth-layer wiring proof for the Lane 4C quote-provenance recorder.

Doctrine: inject the failure at its ORIGIN, assert the truth at the TOP.
The failures (Alpaca 429 / empty miss / connection error) are injected at
``session.get`` — the deepest HTTP boundary — and the assertions run on
the DURABLE rows produced by ``recorder.flush()`` after driving the REAL
``MarketDataTruthLayer.snapshot_many`` (real routing, real fallback, real
parse). No intermediate truth-layer function is mocked.

Also proves the two non-negotiables at this boundary:
- secret-absence: real env keys set for the drive never reach a row;
- observe-only: snapshot_many returns identical data with and without a
  recorder attached.
"""

import json
import unittest
from collections import defaultdict
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import requests

from packages.quantum.services.market_data_truth_layer import MarketDataTruthLayer
from packages.quantum.services.quote_provenance import (
    QuoteProvenanceRecorder,
    TABLE_NAME,
)

OCC = "O:TSTX260821C00100000"
BARE = "TSTX260821C00100000"

FAKE_ALPACA_KEY = "AKTESTKEYID99SECRET"
FAKE_ALPACA_SECRET = "ALPACASECRETVALUE77"
FAKE_POLYGON_KEY = "POLYKEYSECRET42"


class _FakeCache:
    """No-op cache so every drive hits the fetch path deterministically."""

    def get(self, *_a, **_k):
        return None

    def set(self, *_a, **_k):
        return None


class _FakeResp:
    def __init__(self, status_code=200, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.headers = headers or {}
        self.text = json.dumps(self._payload)

    def json(self):
        return self._payload


def _polygon_payload():
    return {
        "results": [{
            "ticker": OCC,
            "type": "O",
            "last_quote": {"bid": 1.00, "ask": 1.10,
                           "last_updated": 1780000000000},
            "last_trade": {"price": 1.05, "sip_timestamp": 1780000000000},
            "session": {"close": 1.04},
        }]
    }


class _FakeQuery:
    def __init__(self, parent, table_name):
        self._parent = parent
        self._table = table_name
        self._payload = None

    def insert(self, payload):
        self._payload = payload
        return self

    def execute(self):
        self._parent.inserted[self._table].append(self._payload)
        return SimpleNamespace(data=self._payload)


class FakeSupabase:
    def __init__(self):
        self.inserted = defaultdict(list)

    def table(self, name):
        return _FakeQuery(self, name)

    @property
    def rows(self):
        flat = []
        for batch in self.inserted[TABLE_NAME]:
            flat.extend(batch)
        return flat


def _make_session_get(alpaca_behavior):
    """Dispatch session.get by URL. ``alpaca_behavior`` is one of
    '429' | 'empty' | 'raise' | 'ok'."""

    def fake_get(url, params=None, headers=None, timeout=None, **_k):
        if "data.alpaca.markets" in url:
            if alpaca_behavior == "429":
                return _FakeResp(429, {"message": "too many requests"},
                                 headers={"Retry-After": "2"})
            if alpaca_behavior == "empty":
                return _FakeResp(200, {"snapshots": {}})
            if alpaca_behavior == "raise":
                raise requests.exceptions.ConnectionError("origin down")
            return _FakeResp(200, {"snapshots": {
                BARE: {
                    "latestQuote": {"bp": 1.00, "ap": 1.10},
                    "latestTrade": {"p": 1.05},
                    "greeks": {},
                    "dailyBar": {"c": 1.04, "v": 10},
                }
            }})
        # Polygon /v3/snapshot
        return _FakeResp(200, _polygon_payload())

    return fake_get


def _drive(alpaca_behavior, attach_recorder=True):
    """Drive the REAL snapshot_many for one OCC option symbol."""
    fake = FakeSupabase()
    env = {
        "ALPACA_API_KEY": FAKE_ALPACA_KEY,
        "ALPACA_SECRET_KEY": FAKE_ALPACA_SECRET,
        "QUOTE_PROVENANCE_SAMPLE_N": "1",
    }
    with patch.dict("os.environ", env, clear=False):
        tl = MarketDataTruthLayer(api_key=FAKE_POLYGON_KEY)
        tl.cache = _FakeCache()
        rec = None
        if attach_recorder:
            rec = QuoteProvenanceRecorder(
                supabase=fake, cycle_date=date(2026, 7, 17))
            tl.set_provenance_recorder(rec)
        with patch.object(tl, "session") as sess:
            sess.get.side_effect = _make_session_get(alpaca_behavior)
            results = tl.snapshot_many([OCC])
        counts = rec.flush() if rec is not None else None
    return results, fake, rec, counts


class TestSnapshotBoundary429(unittest.TestCase):
    def test_429_fallback_produces_durable_evidence(self):
        results, fake, rec, counts = _drive("429")

        # The route itself behaved: Polygon fallback served the quote.
        self.assertIn(OCC, results)
        self.assertEqual(results[OCC]["source"], "polygon")

        # DURABLE evidence: one fetch_event with source+reason+timestamps.
        events = [r for r in fake.rows if r["record_type"] == "fetch_event"]
        self.assertEqual(len(events), 1, fake.rows)
        ev = events[0]
        self.assertEqual(ev["boundary"], "snapshot_many_options")
        self.assertEqual(ev["fallback_reason"], "429")
        self.assertEqual(ev["source"], "polygon_fallback")
        self.assertIn(429, ev["http_statuses"])
        self.assertIsNotNone(ev["requested_at"])
        self.assertIsNotNone(ev["received_at"])
        self.assertEqual(ev["details"]["served_alpaca"], 0)
        self.assertEqual(ev["details"]["served_polygon_fallback"], 1)
        # Alpaca Retry-After header captured where visible.
        self.assertEqual(
            ev["details"]["requests"][0].get("retry_after"), "2")
        self.assertEqual(counts["rows_written"], len(fake.rows))

        # The per-contract note is joinable into a leg-set row with the
        # fallback source + reason (the verdict-side linkage).
        rec2_fake = FakeSupabase()
        rec._supabase = rec2_fake  # flush target for the leg-set row
        rec.record_spread_verdict(
            symbol="TSTX", strategy_key="k", verdict="rejected",
            reject_reason="spread_too_wide", threshold=0.10,
            option_spread_pct=0.42,
            legs=[{"symbol": BARE, "side": "buy", "strike": 100.0,
                   "expiry": "2026-08-21", "bid": 1.00, "ask": 1.10}],
        )
        rec.flush()
        leg_rows = [r for r in rec2_fake.rows if r["record_type"] == "leg_set"]
        self.assertEqual(len(leg_rows), 1)
        self.assertEqual(leg_rows[0]["legs"][0]["source"], "polygon_fallback")
        self.assertEqual(leg_rows[0]["fallback_reason"], "429")

    def test_429_rows_carry_no_secret_material(self):
        _results, fake, _rec, _counts = _drive("429")
        blob = json.dumps(fake.rows)
        self.assertNotIn(FAKE_ALPACA_KEY, blob)
        self.assertNotIn(FAKE_ALPACA_SECRET, blob)
        self.assertNotIn(FAKE_POLYGON_KEY, blob)
        self.assertGreater(len(fake.rows), 0)


class TestSnapshotBoundaryMissAndError(unittest.TestCase):
    def test_alpaca_empty_is_miss(self):
        results, fake, _rec, _counts = _drive("empty")
        self.assertIn(OCC, results)
        events = [r for r in fake.rows if r["record_type"] == "fetch_event"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["fallback_reason"], "miss")
        self.assertEqual(events[0]["http_statuses"], [200])

    def test_alpaca_exception_is_error_with_class_name_only(self):
        results, fake, _rec, _counts = _drive("raise")
        self.assertIn(OCC, results)
        events = [r for r in fake.rows if r["record_type"] == "fetch_event"]
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev["fallback_reason"], "error")
        errs = [r.get("error") for r in ev["details"]["requests"]]
        self.assertIn("ConnectionError", errs)
        # Error entries carry the exception CLASS, never a stringified
        # message that could embed URL/query material.
        self.assertNotIn("origin down", json.dumps(ev))

    def test_alpaca_ok_notes_alpaca_source(self):
        results, fake, rec, _counts = _drive("ok")
        self.assertIn(OCC, results)
        self.assertEqual(results[OCC]["source"], "alpaca")
        events = [r for r in fake.rows if r["record_type"] == "fetch_event"]
        self.assertEqual(len(events), 1)
        self.assertIsNone(events[0]["fallback_reason"])
        self.assertEqual(events[0]["source"], "alpaca")
        # Note joined as alpaca on a subsequent leg set.
        fake2 = FakeSupabase()
        rec._supabase = fake2
        rec.record_spread_verdict(
            symbol="TSTX", strategy_key="k", verdict="rejected",
            reject_reason="spread_too_wide", threshold=0.10,
            option_spread_pct=0.42,
            legs=[{"symbol": BARE, "side": "buy", "strike": 100.0,
                   "expiry": "2026-08-21", "bid": 1.00, "ask": 1.10}],
        )
        rec.flush()
        self.assertEqual(fake2.rows[0]["legs"][0]["source"], "alpaca")


class TestObserveOnly(unittest.TestCase):
    def test_snapshot_results_identical_with_and_without_recorder(self):
        with_rec, _f, _r, _c = _drive("429", attach_recorder=True)
        without_rec, _f2, _r2, _c2 = _drive("429", attach_recorder=False)
        # retrieved_ts is a wall-clock stamp — normalize before comparing.
        for snaps in (with_rec, without_rec):
            for s in snaps.values():
                s.pop("retrieved_ts", None)
                s.pop("staleness_ms", None)
        self.assertEqual(with_rec, without_rec)


if __name__ == "__main__":
    unittest.main()
