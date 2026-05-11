"""Tests for MTM-staleness PR-2: broker-authoritative fallback.

PR-1 (PR #919) shipped observability infrastructure — `mtm_refresh_partial`
alerts at both refresh sites + `last_marked_at` column for staleness
queries. PR-2 ships the structural fix: when
`truth_layer.snapshot_many()` returns incomplete leg pricing for a
multi-leg position, refresh_marks now falls back to Alpaca's
broker-authoritative position values instead of silently skipping.

Bug context: 2026-05-12 CSX situation. DB unrealized_pl = -$8 (Friday's
mark) while Alpaca truth = -$196 (intraday). Snapshot path silently
skipped CSX; risk envelope ran on stale value; operator manually closed.

This test suite covers:
- Helper `_compute_position_value_from_broker` returns correct signed
  current_value for single-leg + multi-leg positions
- Broker fallback returns None when any leg is missing from Alpaca
  (true drift case — caller should treat as silent-skip + alert)
- `refresh_marks` calls the helper when snapshot returns None
- `refresh_marks` return envelope includes `fallback_used` counter
- `mtm_broker_prefetch_failed` alert fires when Alpaca pre-fetch errors
- `mtm_refresh_partial` alert (from PR-1) only fires when BOTH paths fail

Source-level structural assertions for the alert + return-value contract
(matching PR-1's test style). Behavioral tests for the helper itself use
a minimal supabase mock so the per-position math gets actual coverage.
"""

import re
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


_QUANTUM_ROOT = Path(__file__).resolve().parent.parent
MTM_SERVICE_PATH = _QUANTUM_ROOT / "services" / "paper_mark_to_market_service.py"


# ─────────────────────────────────────────────────────────────────────
# Source-level: refresh_marks integration with the broker fallback
# ─────────────────────────────────────────────────────────────────────


class TestRefreshMarksIntegratesBrokerFallback(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.src = MTM_SERVICE_PATH.read_text(encoding="utf-8")

    def test_bulk_prefetch_call_present(self):
        """refresh_marks must call alpaca.get_positions ONCE before the
        per-position loop. Bulk pre-fetch shape per PR-2 design."""
        # Find the refresh_marks function body
        anchor = self.src.find("def refresh_marks(self")
        self.assertGreater(anchor, 0)
        end_match = re.search(
            r"\n    def [a-zA-Z_]", self.src[anchor + 50:]
        )
        end = (anchor + 50 + end_match.start()) if end_match else len(self.src)
        body = self.src[anchor:end]

        self.assertIn("alpaca.get_positions()", body)
        self.assertIn("broker_positions_by_symbol", body)
        # Pre-fetch must happen BEFORE the main per-position evaluation
        # loop (not before the earlier symbol-collection loop, which is
        # also a `for pos in positions:` line at the top of refresh_marks).
        # Anchor on the main loop's body: `pos_id = pos["id"]` is unique
        # to that loop.
        prefetch_idx = body.find("alpaca.get_positions()")
        main_loop_idx = body.find('pos_id = pos["id"]')
        self.assertGreater(main_loop_idx, 0, "main evaluation loop missing")
        self.assertLess(prefetch_idx, main_loop_idx,
            "Pre-fetch must happen before the main per-position eval loop")

    def test_fallback_called_when_snapshot_returns_none(self):
        """When _compute_position_value_from_snapshots returns None,
        refresh_marks must try _compute_position_value_from_broker
        before skipping."""
        anchor = self.src.find("def refresh_marks(self")
        end_match = re.search(
            r"\n    def [a-zA-Z_]", self.src[anchor + 50:]
        )
        end = (anchor + 50 + end_match.start()) if end_match else len(self.src)
        body = self.src[anchor:end]

        self.assertIn("_compute_position_value_from_broker", body)
        self.assertIn("fallback_used", body)

    def test_fallback_used_in_return_envelope(self):
        """Operator must be able to monitor the success metric directly.

        refresh_marks has multiple return statements — the early-return
        for no_open_positions is the first `return {` substring. Anchor
        on the final-return dict by searching for `"total_positions":`
        which only appears in that final dict.
        """
        anchor = self.src.find("def refresh_marks(self")
        end_match = re.search(
            r"\n    def [a-zA-Z_]", self.src[anchor + 50:]
        )
        end = (anchor + 50 + end_match.start()) if end_match else len(self.src)
        body = self.src[anchor:end]

        # Find the final return dict (the one with total_positions)
        return_idx = body.find('"total_positions"')
        self.assertGreater(return_idx, 0,
            "Final return dict (with total_positions) not found")
        return_block = body[max(0, return_idx - 600):return_idx + 200]
        self.assertIn('"fallback_used"', return_block)

    def test_prefetch_failure_emits_alert(self):
        """When the Alpaca pre-fetch throws, mtm_broker_prefetch_failed
        alert fires. snapshot-only path then proceeds; positions with
        incomplete snapshots silently skip + fire PR-1's alert."""
        self.assertIn('alert_type="mtm_broker_prefetch_failed"', self.src)
        # The alert call must be inside an except block
        idx = self.src.find('alert_type="mtm_broker_prefetch_failed"')
        block = self.src[max(0, idx - 800):idx]
        self.assertIn("except Exception", block)

    def test_pr1_alert_reframed_for_post_pr2_semantics(self):
        """PR-1's mtm_refresh_partial alert now fires only when BOTH
        snapshot AND broker fallback failed. Alert message + metadata
        must reflect this."""
        idx = self.src.find('alert_type="mtm_refresh_partial"')
        self.assertGreater(idx, 0)
        block = self.src[idx:idx + 2500]

        # Message must mention broker fallback explicitly
        self.assertIn("broker fallback", block)
        # Metadata must include fallback_used count
        self.assertIn('"fallback_used"', block)
        # Consequence text must explain the post-PR-2 semantics — "true
        # drift" framing is split across a line break in the source, so
        # check the two key terms separately rather than as a single
        # phrase.
        block_lower = block.lower()
        self.assertIn("true", block_lower)
        self.assertIn("drift", block_lower)

    def test_error_string_disambiguates_post_pr2_skip(self):
        """The error entry on the silent-skip path now indicates BOTH
        paths failed (vs PR-1's 'incomplete_quotes_skipped' which only
        meant snapshot failed)."""
        self.assertIn("snapshot_incomplete_and_broker_lookup_missing", self.src)


# ─────────────────────────────────────────────────────────────────────
# Behavioral tests for the new helper
# ─────────────────────────────────────────────────────────────────────


class TestComputePositionValueFromBroker(unittest.TestCase):
    """Tests the new _compute_position_value_from_broker static method
    directly. Uses bare dicts (no DB or Alpaca client needed)."""

    def setUp(self):
        from packages.quantum.services.paper_mark_to_market_service import (
            PaperMarkToMarketService,
        )
        self.helper = PaperMarkToMarketService._compute_position_value_from_broker

    def test_single_leg_position_uses_position_symbol(self):
        """For a leg-less position, lookup is by position-level symbol."""
        position = {
            "id": "pos-1",
            "symbol": "AAPL",
            "quantity": 10,
            "legs": [],
        }
        broker = {
            "AAPL": {"symbol": "AAPL", "current_price": 150.00},
        }
        value = self.helper(position, broker)
        # 150 * 100 (multiplier) * 10 (qty) = 150_000
        self.assertEqual(value, 150000.0)

    def test_multi_leg_debit_spread_sums_with_signs(self):
        """CSX-shape debit spread: long 43C + short 47C.

        long_value = +current_price_43 × 100 × qty
        short_value = -current_price_47 × 100 × qty
        signed_sum is what refresh_marks's downstream math expects."""
        position = {
            "id": "pos-csx",
            "symbol": "CSX",
            "quantity": 1,
            "legs": [
                {"occ_symbol": "O:CSX260605C00043000", "action": "buy",  "quantity": 1},
                {"occ_symbol": "O:CSX260605C00047000", "action": "sell", "quantity": 1},
            ],
        }
        broker = {
            "O:CSX260605C00043000": {"symbol": "O:CSX260605C00043000", "current_price": 1.10},
            "O:CSX260605C00047000": {"symbol": "O:CSX260605C00047000", "current_price": 0.90},
        }
        # 1.10 * 100 * 1 - 0.90 * 100 * 1 = 110 - 90 = 20
        # (i.e., net spread value $0.20 = $20 per spread)
        # assertAlmostEqual handles the float-precision residue from
        # the per-leg multiplications.
        value = self.helper(position, broker)
        self.assertAlmostEqual(value, 20.0, places=6)

    def test_returns_none_when_leg_missing_from_alpaca(self):
        """Drift case: position in DB has 2 legs but Alpaca returns
        only 1. Helper returns None so caller silent-skips + alerts."""
        position = {
            "id": "pos-drift",
            "quantity": 1,
            "legs": [
                {"occ_symbol": "O:FOO260605C00100000", "action": "buy",  "quantity": 1},
                {"occ_symbol": "O:FOO260605C00110000", "action": "sell", "quantity": 1},
            ],
        }
        broker = {
            "O:FOO260605C00100000": {"symbol": "O:FOO260605C00100000", "current_price": 1.00},
            # MISSING: O:FOO260605C00110000
        }
        self.assertIsNone(self.helper(position, broker))

    def test_returns_none_when_alpaca_current_price_falsy(self):
        """Alpaca returned the leg but with no current_price (expired,
        halted, etc.). Helper returns None — caller alerts."""
        position = {
            "id": "pos-haltedleg",
            "quantity": 1,
            "legs": [
                {"occ_symbol": "O:HALT260605C00100000", "action": "buy", "quantity": 1},
            ],
        }
        broker = {
            "O:HALT260605C00100000": {
                "symbol": "O:HALT260605C00100000",
                "current_price": None,
            },
        }
        self.assertIsNone(self.helper(position, broker))

    def test_returns_none_when_empty_broker_dict(self):
        """Pre-fetch failed earlier in refresh_marks → broker dict empty.
        Helper returns None for every position; caller alerts as before."""
        position = {
            "id": "pos-noprefetch",
            "quantity": 1,
            "legs": [
                {"occ_symbol": "O:X260605C00100000", "action": "buy", "quantity": 1},
            ],
        }
        self.assertIsNone(self.helper(position, {}))

    def test_returns_none_when_position_has_no_symbol_or_legs(self):
        """Defensive: malformed position with neither symbol nor legs."""
        self.assertIsNone(self.helper({"id": "bad", "quantity": 1}, {}))


# ─────────────────────────────────────────────────────────────────────
# Behavioral tests via refresh_marks with patched dependencies
# ─────────────────────────────────────────────────────────────────────


class TestRefreshMarksFallbackFlow(unittest.TestCase):
    """Exercise refresh_marks end-to-end with controlled snapshot +
    broker responses. Verifies the fallback wiring + return envelope."""

    def _make_service(self, positions, snapshots, broker_positions):
        """Build a PaperMarkToMarketService with mocked dependencies."""
        from packages.quantum.services.paper_mark_to_market_service import (
            PaperMarkToMarketService,
        )

        supabase = MagicMock()
        service = PaperMarkToMarketService(supabase)

        # Mock _get_open_positions
        service._get_open_positions = MagicMock(return_value=positions)

        # Mock MarketDataTruthLayer.snapshot_many
        truth_layer_class = MagicMock()
        truth_layer_class.return_value.snapshot_many = MagicMock(
            return_value=snapshots
        )

        # Mock get_alpaca_client
        alpaca_client = MagicMock()
        alpaca_client.get_positions = MagicMock(
            return_value=list(broker_positions.values())
        )

        return service, supabase, truth_layer_class, alpaca_client

    def test_snapshot_succeeds_fallback_unused(self):
        """Happy path: snapshot returns complete data; fallback_used=0."""
        positions = [{
            "id": "pos-1",
            "symbol": "AAPL",
            "avg_entry_price": 150.00,
            "quantity": 1,
            "legs": [],
        }]
        snapshots = {"AAPL": {"quote": {"bid": 152.0, "ask": 154.0}}}
        broker = {}  # not consulted

        service, supabase, truth_layer_class, alpaca_client = self._make_service(
            positions, snapshots, broker,
        )

        with patch(
            "packages.quantum.services.market_data_truth_layer.MarketDataTruthLayer",
            truth_layer_class,
        ), patch(
            "packages.quantum.brokers.alpaca_client.get_alpaca_client",
            return_value=alpaca_client,
        ):
            result = service.refresh_marks("user-1")

        self.assertEqual(result["positions_marked"], 1)
        self.assertEqual(result["positions_skipped"], 0)
        self.assertEqual(result["fallback_used"], 0)

    def test_snapshot_fails_broker_rescues(self):
        """Snapshot returns incomplete; broker fallback provides value;
        fallback_used=1, no skip."""
        positions = [{
            "id": "pos-csx",
            "symbol": "CSX",
            "avg_entry_price": 2.16,
            "quantity": 1,
            "legs": [
                {"occ_symbol": "O:CSX260605C00043000", "action": "buy",  "quantity": 1},
                {"occ_symbol": "O:CSX260605C00047000", "action": "sell", "quantity": 1},
            ],
        }]
        snapshots = {}  # empty → snapshot returns None for spread
        broker = {
            "O:CSX260605C00043000": {"symbol": "O:CSX260605C00043000", "current_price": 1.10},
            "O:CSX260605C00047000": {"symbol": "O:CSX260605C00047000", "current_price": 0.90},
        }

        service, supabase, truth_layer_class, alpaca_client = self._make_service(
            positions, snapshots, broker,
        )

        with patch(
            "packages.quantum.services.market_data_truth_layer.MarketDataTruthLayer",
            truth_layer_class,
        ), patch(
            "packages.quantum.brokers.alpaca_client.get_alpaca_client",
            return_value=alpaca_client,
        ):
            result = service.refresh_marks("user-1")

        self.assertEqual(result["positions_marked"], 1)
        self.assertEqual(result["positions_skipped"], 0)
        self.assertEqual(result["fallback_used"], 1)

    def test_both_paths_fail_triggers_skip(self):
        """Snapshot incomplete + broker fallback missing leg → skip
        + alert. positions_skipped=1, fallback_used=0."""
        positions = [{
            "id": "pos-drift",
            "symbol": "FOO",
            "avg_entry_price": 2.00,
            "quantity": 1,
            "legs": [
                {"occ_symbol": "O:FOO260605C00100000", "action": "buy",  "quantity": 1},
                {"occ_symbol": "O:FOO260605C00110000", "action": "sell", "quantity": 1},
            ],
        }]
        snapshots = {}
        broker = {
            # Only one leg in broker response — drift
            "O:FOO260605C00100000": {"symbol": "O:FOO260605C00100000", "current_price": 1.00},
        }

        service, supabase, truth_layer_class, alpaca_client = self._make_service(
            positions, snapshots, broker,
        )

        with patch(
            "packages.quantum.services.market_data_truth_layer.MarketDataTruthLayer",
            truth_layer_class,
        ), patch(
            "packages.quantum.brokers.alpaca_client.get_alpaca_client",
            return_value=alpaca_client,
        ):
            result = service.refresh_marks("user-1")

        self.assertEqual(result["positions_marked"], 0)
        self.assertEqual(result["positions_skipped"], 1)
        self.assertEqual(result["fallback_used"], 0)


if __name__ == "__main__":
    unittest.main()
