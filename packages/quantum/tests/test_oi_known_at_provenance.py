"""OI observation-date provenance (v1.6 finding A5-OI-KNOWNAT) — route-driven.

The failure is injected at the PROVIDER PAYLOAD PARSE (the real
``MarketDataTruthLayer._parse_alpaca_chain_item`` /
``_fetch_polygon_option_chain`` / ``option_chain`` seams) and the truth is
asserted at the TOP: the DURABLE ``option_quote_provenance`` leg-set row the
recorder flushes (``details->oi->legs``). No source-string pins.

Pins the doctrine of the fix:
  * the GENUINE provider OI observation date threads through when the payload
    actually carries it (Alpaca ``openInterestDate`` / Polygon
    ``open_interest_date``);
  * retrieval/known-at time is stored SEPARATELY and is NEVER used as the
    observation date;
  * a provider that supplies no date stays typed ``provider_date_unavailable``;
  * ``oi_freshness`` is computed ONLY from a real observation date
    (fresh vs stale), never from retrieval;
  * OI 0 is a REAL value that still carries its date; a malformed date →
    typed ``malformed_date``, never a fabricated date.
"""

import unittest
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from packages.quantum.options_scanner import _build_oi_by_contract
from packages.quantum.services.market_data_truth_layer import MarketDataTruthLayer
from packages.quantum.services.quote_provenance import (
    QuoteProvenanceRecorder,
    TABLE_NAME,
)

_TODAY = datetime.now(timezone.utc).date()
_FRESH_DATE = (_TODAY - timedelta(days=1)).isoformat()   # age ~1 → fresh
_STALE_DATE = (_TODAY - timedelta(days=40)).isoformat()  # age ~40 → stale


# ── fake supabase capturing the batched insert ─────────────────────────────
class _FakeQuery:
    def __init__(self, parent, table_name):
        self._parent = parent
        self._table = table_name

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


class _FakeCache:
    def get(self, *_a, **_k):
        return None

    def set(self, *_a, **_k):
        return None


def _recorder(fake, env=None):
    env = env or {}
    with patch.dict("os.environ", env, clear=False):
        return QuoteProvenanceRecorder(supabase=fake, cycle_date=date(2026, 7, 18))


def _persist_leg(chain, env=None):
    """Drive _build_oi_by_contract → recorder → flush; return the single
    persisted ``details->oi->legs`` entry (and the full row)."""
    fake = FakeSupabase()
    rec = _recorder(fake, env=env)
    oi_map = _build_oi_by_contract(chain)
    legs = [{
        "symbol": c.get("contract") or c.get("ticker"),
        "side": "buy",
        "strike": c.get("strike") or 100.0,
        "expiry": c.get("expiry") or "2026-08-21",
        "bid": 1.00, "ask": 1.10, "mid": 1.05,
    } for c in chain]
    rec.record_spread_verdict(
        symbol="X", strategy_key="k", verdict="rejected",
        reject_reason="spread_too_wide", threshold=0.1, option_spread_pct=0.5,
        legs=legs, oi_by_contract=oi_map,
    )
    rec.flush()
    assert len(fake.rows) == 1, fake.rows
    row = fake.rows[0]
    return row["details"]["oi"]["legs"][0], row


# ── Alpaca snapshot parse seam ─────────────────────────────────────────────
class TestAlpacaParsePath(unittest.TestCase):
    def _parse(self, snap):
        tl = MarketDataTruthLayer(api_key="POLYKEY")
        return tl._parse_alpaca_chain_item("XYZ260821C00100000", "XYZ", snap)

    def test_alpaca_payload_with_genuine_date_threads_and_is_fresh(self):
        snap = {
            "latestQuote": {"bp": 1.0, "ap": 1.1}, "latestTrade": {"p": 1.05},
            "greeks": {}, "dailyBar": {"c": 1.04, "v": 10},
            "openInterest": 1500, "openInterestDate": _FRESH_DATE,
        }
        item = self._parse(snap)
        # Parse threaded the genuine field + its name, separate from retrieval.
        self.assertEqual(item["open_interest_date"], _FRESH_DATE)
        self.assertEqual(item["oi_date_field"], "openInterestDate")
        self.assertIsNotNone(item["retrieved_ts"])
        self.assertNotEqual(item["open_interest_date"], item["retrieved_ts"])

        leg, _row = _persist_leg([item])
        self.assertEqual(leg["oi"], 1500)
        self.assertEqual(leg["oi_observation_date"], _FRESH_DATE)
        # Retrieval kept SEPARATE from the observation date.
        self.assertEqual(leg["oi_retrieved_at"], item["retrieved_ts"])
        self.assertNotEqual(leg["oi_retrieved_at"], leg["oi_observation_date"])
        # Freshness computed from the observation date only.
        self.assertEqual(leg["oi_freshness"], "fresh")
        self.assertIsNotNone(leg["oi_observation_age_days"])
        self.assertEqual(leg["oi_date_provenance"], "alpaca:openInterestDate")

    def test_alpaca_payload_without_date_is_provider_date_unavailable(self):
        snap = {
            "latestQuote": {"bp": 1.0, "ap": 1.1}, "latestTrade": {"p": 1.05},
            "greeks": {}, "dailyBar": {"c": 1.04, "v": 10},
            "openInterest": 1500,   # OI present, but NO date field
        }
        item = self._parse(snap)
        self.assertIsNone(item["open_interest_date"])
        self.assertIsNone(item["oi_date_field"])

        leg, _row = _persist_leg([item])
        self.assertEqual(leg["oi"], 1500)                 # OI still available
        self.assertIsNone(leg["oi_observation_date"])
        self.assertIsNone(leg["oi_observation_age_days"])
        self.assertEqual(leg["oi_freshness"], "provider_date_unavailable")
        self.assertEqual(leg["oi_date_provenance"], "provider_date_unavailable")

    def test_zero_oi_with_genuine_date_is_real_value(self):
        # OI 0 is a REAL listed-but-untraded value — it still carries its date.
        snap = {
            "latestQuote": {"bp": 1.0, "ap": 1.1}, "latestTrade": {"p": 1.05},
            "greeks": {}, "dailyBar": {"c": 1.04, "v": 0},
            "openInterest": 0, "openInterestDate": _FRESH_DATE,
        }
        item = self._parse(snap)
        leg, _row = _persist_leg([item])
        self.assertEqual(leg["oi"], 0)                    # real value, not None
        self.assertTrue(leg["oi_available"])
        self.assertEqual(leg["oi_observation_date"], _FRESH_DATE)
        self.assertEqual(leg["oi_freshness"], "fresh")

    def test_stale_date_freshness_computed(self):
        snap = {
            "latestQuote": {"bp": 1.0, "ap": 1.1}, "latestTrade": {"p": 1.05},
            "greeks": {}, "dailyBar": {"c": 1.04, "v": 10},
            "openInterest": 1500, "openInterestDate": _STALE_DATE,
        }
        item = self._parse(snap)
        leg, _row = _persist_leg([item])
        self.assertEqual(leg["oi_observation_date"], _STALE_DATE)
        self.assertEqual(leg["oi_freshness"], "stale")
        self.assertGreater(leg["oi_observation_age_days"], 4)

    def test_malformed_date_is_typed_never_fabricated(self):
        snap = {
            "latestQuote": {"bp": 1.0, "ap": 1.1}, "latestTrade": {"p": 1.05},
            "greeks": {}, "dailyBar": {"c": 1.04, "v": 10},
            "openInterest": 1500, "openInterestDate": "not-a-date",
        }
        item = self._parse(snap)
        # The raw malformed value is threaded (typing happens downstream), but
        # it is NEVER coerced into a fabricated date at the parse.
        self.assertEqual(item["open_interest_date"], "not-a-date")

        leg, _row = _persist_leg([item])
        self.assertIsNone(leg["oi_observation_date"])     # never fabricated
        self.assertIsNone(leg["oi_observation_age_days"])
        self.assertEqual(leg["oi_freshness"], "malformed_date")
        self.assertIn("malformed_date", leg["oi_date_provenance"])


# ── Polygon snapshot parse seam (fallback provider) ────────────────────────
def _polygon_payload(oi=742, oi_date=None):
    item = {
        "details": {"ticker": "O:XYZ260821C00100000", "strike_price": 100.0,
                    "expiration_date": "2026-08-21", "contract_type": "call"},
        "last_quote": {"bid": 1.00, "ask": 1.10, "last_updated": 1780000000000},
        "last_trade": {"price": 1.05, "sip_timestamp": 1780000000000},
        "implied_volatility": 0.25,
        "greeks": {"delta": 0.55, "gamma": 0.02, "theta": -0.05, "vega": 0.10},
        "open_interest": oi,
        "day": {"volume": 33},
    }
    if oi_date is not None:
        item["open_interest_date"] = oi_date
    return {"results": [item], "next_url": None}


class TestPolygonFallbackParsePath(unittest.TestCase):
    def _fetch(self, payload):
        tl = MarketDataTruthLayer(api_key="POLYKEY")
        tl.cache = _FakeCache()
        with patch.object(tl, "_make_request", return_value=payload):
            return tl._fetch_polygon_option_chain(
                "XYZ", 100.0, None, None, None, None, None)

    def test_polygon_payload_with_explicit_date_threads(self):
        chain = self._fetch(_polygon_payload(oi=742, oi_date=_FRESH_DATE))
        self.assertEqual(len(chain), 1)
        item = chain[0]
        self.assertEqual(item["source"], "polygon")
        self.assertEqual(item["open_interest_date"], _FRESH_DATE)
        self.assertEqual(item["oi_date_field"], "open_interest_date")

        leg, _row = _persist_leg(chain)
        self.assertEqual(leg["oi"], 742)
        self.assertEqual(leg["oi_observation_date"], _FRESH_DATE)
        self.assertEqual(leg["oi_freshness"], "fresh")
        self.assertEqual(leg["oi_date_provenance"], "polygon:open_interest_date")
        # Retrieval time is separate and present.
        self.assertIsNotNone(leg["oi_retrieved_at"])
        self.assertNotEqual(leg["oi_retrieved_at"], leg["oi_observation_date"])

    def test_polygon_payload_missing_date_is_unavailable(self):
        chain = self._fetch(_polygon_payload(oi=742, oi_date=None))
        item = chain[0]
        self.assertIsNone(item["open_interest_date"])

        leg, _row = _persist_leg(chain)
        self.assertEqual(leg["oi"], 742)
        self.assertIsNone(leg["oi_observation_date"])
        self.assertEqual(leg["oi_freshness"], "provider_date_unavailable")


class TestOptionChainFallbackRouting(unittest.TestCase):
    """Full option_chain: Alpaca dark → Polygon fallback serves the date."""

    def test_fallback_to_polygon_threads_the_date_to_the_row(self):
        tl = MarketDataTruthLayer(api_key="POLYKEY")
        tl.cache = _FakeCache()
        with patch.object(tl, "_fetch_alpaca_option_chain", return_value=[]), \
                patch.object(tl, "_make_request",
                             return_value=_polygon_payload(oi=900, oi_date=_FRESH_DATE)):
            chain = tl.option_chain("XYZ")   # strike_range None → no spot fetch

        self.assertEqual(len(chain), 1)
        self.assertEqual(chain[0]["source"], "polygon")
        self.assertEqual(chain[0]["open_interest_date"], _FRESH_DATE)

        leg, _row = _persist_leg(chain)
        self.assertEqual(leg["oi"], 900)
        self.assertEqual(leg["oi_observation_date"], _FRESH_DATE)
        self.assertEqual(leg["oi_date_provenance"], "polygon:open_interest_date")
        self.assertEqual(leg["oi_freshness"], "fresh")


if __name__ == "__main__":
    unittest.main()
