"""⑤ Score-on-scan capture NON-INTERFERENCE (contract §C8) — REAL scan route.

Drives the REAL ``scan_for_opportunities`` (via the canonical
``test_lifecycle_fail_closed_route`` fixtures) with the observe-only flag ON vs
OFF and proves:

  (a) the scanner's ``candidates`` output is BYTE-IDENTICAL with capture on/off;
  (b) capture ON actually captured the emitted candidate's envelope;
  (c) capture adds ZERO provider calls (option_chain call-count identical);
  (d) capture does ONE batched write at the scan boundary (no per-candidate DB
      call on the hot path — the latency contract).

Doctrine (§9): drive the production route, assert on the OUTPUT.
"""

import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import packages.quantum.options_scanner as scanner_mod
from packages.quantum.tests.test_lifecycle_fail_closed_route import (
    FakeSupabase,
    STRATEGY,
    SYMBOL,
    _FakeGlobalSnapshot,
    _FakeSymbolSnapshot,
    _fixture_chain,
    _suggestion,
)

FLAG = "TERMINAL_DISTRIBUTION_SCAN_OBSERVE_ENABLED"
_LIVE_ROWS = [{"strategy_name": STRATEGY, "current_state": "live_full"}]


def _run_scan_exposed(fake_supabase):
    """Mirror of the canonical _run_scan but returns the truth mock too, so we
    can assert provider call-counts. Real process_symbol pipeline; stubs only at
    external data boundaries."""
    truth = MagicMock()
    truth.normalize_symbol.side_effect = lambda s: s
    truth.snapshot_many.return_value = {
        SYMBOL: {"quote": {"bid": 99.95, "ask": 100.05, "mid": 100.0, "last": 100.0}}
    }
    truth.daily_bars.return_value = [{"close": 100.0}] * 60
    truth.option_chain.return_value = _fixture_chain()

    regime = MagicMock()
    regime.iv_repo = None
    regime.compute_symbol_snapshot.return_value = _FakeSymbolSnapshot()
    regime.get_effective_regime.return_value = SimpleNamespace(value="normal")

    selector = MagicMock()
    selector.get_candidates.return_value = [_suggestion()]
    selector.determine_strategy.return_value = _suggestion()

    polygon = MagicMock()
    polygon.get_ticker_details.return_value = {"sic_description": "Tech"}

    earnings = MagicMock()
    earnings.get_earnings_map.return_value = {}

    with patch.object(scanner_mod, "MarketDataTruthLayer", return_value=truth), \
         patch.object(scanner_mod, "RegimeEngineV3", return_value=regime), \
         patch.object(scanner_mod, "StrategySelector", return_value=selector), \
         patch.object(scanner_mod, "PolygonService", return_value=polygon), \
         patch.object(scanner_mod, "EarningsCalendarService", return_value=earnings), \
         patch.object(scanner_mod, "UniverseService", MagicMock()), \
         patch.object(scanner_mod, "ExecutionService", MagicMock()), \
         patch.object(scanner_mod, "IVRepository", MagicMock()), \
         patch.object(scanner_mod, "IVPointService", MagicMock()), \
         patch.object(scanner_mod, "build_agent_pipeline", lambda *a, **k: []):
        candidates, rej = scanner_mod.scan_for_opportunities(
            symbols=[SYMBOL], supabase_client=fake_supabase,
            global_snapshot=_FakeGlobalSnapshot(),
        )
    return candidates, rej, truth


def _projection(candidates):
    return json.dumps(candidates, sort_keys=True, default=str)


class TestCaptureNonInterference(unittest.TestCase):
    def setUp(self):
        os.environ.pop(FLAG, None)

    def tearDown(self):
        os.environ.pop(FLAG, None)

    def test_candidates_byte_identical_capture_on_vs_off(self):
        # OFF
        os.environ.pop(FLAG, None)
        cand_off, _, _ = _run_scan_exposed(FakeSupabase(lifecycle_rows=_LIVE_ROWS))
        # ON
        os.environ[FLAG] = "1"
        cand_on, _, _ = _run_scan_exposed(FakeSupabase(lifecycle_rows=_LIVE_ROWS))
        self.assertEqual(len(cand_off), 1)
        self.assertEqual(len(cand_on), 1)
        # The candidate the scanner EMITS is byte-identical — capture is pure add.
        self.assertEqual(_projection(cand_off), _projection(cand_on))

    def test_envelope_captured_when_on(self):
        os.environ[FLAG] = "1"
        fake = FakeSupabase(lifecycle_rows=_LIVE_ROWS)
        cand, _, _ = _run_scan_exposed(fake)
        self.assertEqual(len(cand), 1)
        inserts = fake.inserted.get("td_scan_envelopes", [])
        # Exactly ONE batched insert (not one per candidate — the latency proof).
        self.assertEqual(len(inserts), 1, "capture must flush ONE batched write")
        rows = inserts[0]
        self.assertTrue(any(r["emitted"] for r in rows),
                        "the emitted candidate's envelope must be captured emitted")
        # The captured envelope carries the exact legs + delta (IV None: fixture
        # chain has no iv, honestly threaded to None — never defaulted).
        env = rows[0]["envelope"]
        self.assertEqual(len(env["legs"]), 2)
        self.assertIsNotNone(env["legs"][0]["delta"])

    def test_no_envelope_written_when_off(self):
        os.environ.pop(FLAG, None)
        fake = FakeSupabase(lifecycle_rows=_LIVE_ROWS)
        _run_scan_exposed(fake)
        self.assertEqual(fake.inserted.get("td_scan_envelopes", []), [])

    def test_no_new_provider_call_capture_on_vs_off(self):
        os.environ.pop(FLAG, None)
        _, _, truth_off = _run_scan_exposed(FakeSupabase(lifecycle_rows=_LIVE_ROWS))
        os.environ[FLAG] = "1"
        _, _, truth_on = _run_scan_exposed(FakeSupabase(lifecycle_rows=_LIVE_ROWS))
        # Capture reads the ALREADY-fetched chain — zero extra provider calls.
        self.assertEqual(truth_on.option_chain.call_count,
                         truth_off.option_chain.call_count)
        self.assertEqual(truth_on.snapshot_many.call_count,
                         truth_off.snapshot_many.call_count)
        self.assertEqual(truth_on.daily_bars.call_count,
                         truth_off.daily_bars.call_count)


if __name__ == "__main__":
    unittest.main()
