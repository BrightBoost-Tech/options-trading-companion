"""Tests for #115c — Anti-pattern 2 cleanup at non-iv_rank sites.

Coverage by site:

  opportunity_scorer.py:64 — debit/cost both None now bails with
    explicit error result instead of fabricating premium=0.

  conviction_service.py:296+297 — leakage/predicted_ev both None now
    stores neutral 1.0 explicitly + logs, instead of arithmetic
    collapse to neutral.

  conviction_service.py:361 — avg_return None despite sufficient
    trade_count now skips bucket + logs, instead of fabricating
    pnl_edge=0.

Three sites EXCLUDED from #115c (intentional design):
  transaction_cost_model.py:217 (audit-only field),
  opportunity_scorer.py:50, 51 (no-leg sentinel for single-leg
  strategies). These are documented in the backlog entry.

Same `sys.modules` pollution guard as PR-B-1/PR-B-2.
"""

import importlib
import logging
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

# Pollution remediation — capture real classes at file-load time
# (test_weekly_report_win_rate.py poisons conviction_service +
# opportunity_scorer at module import).
for _modname in (
    "packages.quantum.analytics.conviction_service",
    "packages.quantum.analytics.opportunity_scorer",
):
    sys.modules.pop(_modname, None)

ConvictionService_mod = importlib.import_module(
    "packages.quantum.analytics.conviction_service"
)
OpportunityScorer_mod = importlib.import_module(
    "packages.quantum.analytics.opportunity_scorer"
)

ConvictionService = ConvictionService_mod.ConvictionService
OpportunityScorer = OpportunityScorer_mod.OpportunityScorer

assert callable(ConvictionService), "conviction_service mocked at file-load"
assert callable(OpportunityScorer), "opportunity_scorer mocked at file-load"


# ─────────────────────────────────────────────────────────────────────
# Site 4: opportunity_scorer.py:64 — debit/cost both None bails
# ─────────────────────────────────────────────────────────────────────


class TestDebitCostBothNoneBails(unittest.TestCase):
    """A debit candidate with both `debit` and `cost` missing must NOT
    score as if premium=0. Pre-#115c silently produced max_loss=0 +
    max_profit=width*100 — fabricated free-money score from missing
    data.
    """

    def _candidate_debit_no_premium(self):
        return {
            "symbol": "AAPL",
            "type": "long_call",
            "short_strike": 0.0,
            "long_strike": 100.0,
            "dte": 30,
            # debit + cost intentionally absent
        }

    def test_missing_premium_returns_error_result(self):
        result = OpportunityScorer.score(
            self._candidate_debit_no_premium(),
            {"price": 105.0, "iv_rank": 50.0},
        )
        self.assertEqual(result["score"], 0.0)
        self.assertEqual(result["debug"]["reason"], "premium_missing")

    def test_missing_premium_does_not_inflate_score(self):
        """Pre-#115c bug: width=100, premium=0 → max_profit=10000,
        max_loss=0. Score reaches its EV-cap (50 pts) trivially.
        Post-fix: score is 0.
        """
        result = OpportunityScorer.score(
            self._candidate_debit_no_premium(),
            {"price": 105.0, "iv_rank": 50.0},
        )
        self.assertLess(result["score"], 1.0)

    def test_present_debit_still_scores_normally(self):
        candidate = {
            "symbol": "AAPL",
            "type": "long_call",
            "short_strike": 0.0,
            "long_strike": 100.0,
            "debit": 1.5,
            "dte": 30,
        }
        result = OpportunityScorer.score(
            candidate, {"price": 105.0, "iv_rank": 50.0},
        )
        self.assertNotEqual(result["debug"].get("reason"), "premium_missing")

    def test_cost_field_alternative_still_works(self):
        """The `cost` fallback for `debit` is preserved (single-leg
        debit candidates use 'cost' instead of 'debit')."""
        candidate = {
            "symbol": "AAPL",
            "type": "long_call",
            "short_strike": 0.0,
            "long_strike": 100.0,
            "cost": 1.5,
            "dte": 30,
        }
        result = OpportunityScorer.score(
            candidate, {"price": 105.0, "iv_rank": 50.0},
        )
        self.assertNotEqual(result["debug"].get("reason"), "premium_missing")


# ─────────────────────────────────────────────────────────────────────
# Sites 5-6: conviction_service v3 multiplier — leakage/predicted_ev
# ─────────────────────────────────────────────────────────────────────


class TestV3MultiplierLeakageMissing(unittest.TestCase):
    """The V3 multiplier path (lines 296-297) explicitly stores 1.0
    when leakage or predicted_ev is None, instead of arithmetic
    collapse via `or 0.0`.
    """

    def _service(self):
        svc = ConvictionService(scoring_engine=MagicMock(), supabase=None)
        return svc

    def test_neither_field_missing_proceeds_to_math(self):
        """Happy path: both fields present → existing math runs."""
        svc = self._service()
        multipliers: dict = {}
        # Direct invocation of the inner storage path: simulate one row
        # passing through the V3 multiplier loop. We exercise via the
        # private _store helper since the loop is a closure inside
        # _get_performance_multipliers_v3 with significant DB plumbing.
        svc._store_v3_multiplier(multipliers, "IRON_CONDOR", "30d", "normal", 1.15)
        self.assertIn("IRON_CONDOR:30d:normal", multipliers)
        self.assertEqual(multipliers["IRON_CONDOR:30d:normal"], 1.15)

    def test_source_emits_neutral_log_when_leakage_missing(self):
        """Source-level guard: the new branch must log + store 1.0."""
        src = (
            Path(__file__).parent.parent / "analytics" / "conviction_service.py"
        ).read_text(encoding="utf-8")
        # The fix replaces `avg_leakage = float(row.get("avg_ev_leakage") or 0.0)`
        # with an explicit None-check + neutral 1.0 storage.
        anchor = src.find('row.get("avg_ev_leakage")')
        self.assertGreater(anchor, 0)
        # Walk forward: must find the None-check + 1.0 store within the
        # next few lines.
        window = src[anchor:anchor + 800]
        self.assertIn("is None or", window)
        self.assertIn("_store_v3_multiplier", window)
        self.assertIn("1.0", window)
        self.assertIn("logger.info", window)


# ─────────────────────────────────────────────────────────────────────
# Site 7: conviction_service legacy — avg_return None despite trades
# ─────────────────────────────────────────────────────────────────────


class TestLegacyMultiplierAvgReturnMissing(unittest.TestCase):
    """The legacy multiplier path (line 361) skips buckets where
    `avg_return` is None despite `trade_count >= 5` instead of
    fabricating pnl_edge=0.
    """

    def test_source_skips_bucket_when_avg_return_missing(self):
        src = (
            Path(__file__).parent.parent / "analytics" / "conviction_service.py"
        ).read_text(encoding="utf-8")
        # Find the new `raw_avg_return` extraction; verify the None-check
        # short-circuits via `continue`.
        anchor = src.find('row.get("avg_return")')
        self.assertGreater(anchor, 0)
        # Walk forward — must see None check + continue + log
        window = src[anchor:anchor + 600]
        self.assertIn("raw_avg_return is None", window)
        self.assertIn("continue", window)
        self.assertIn("logger.info", window)

    def test_trade_count_gate_runs_first(self):
        """Insufficient-samples buckets must be skipped BEFORE the
        avg_return None-check fires — otherwise we'd log "missing
        avg_return" for buckets that would have been skipped anyway,
        creating noise.
        """
        src = (
            Path(__file__).parent.parent / "analytics" / "conviction_service.py"
        ).read_text(encoding="utf-8")
        trade_count_idx = src.find("trade_count = row.get(")
        avg_return_idx = src.find('row.get("avg_return")')
        sample_size_skip_idx = src.find("if trade_count < 5:")
        self.assertGreater(trade_count_idx, 0)
        self.assertGreater(avg_return_idx, 0)
        self.assertGreater(sample_size_skip_idx, 0)
        # Order: trade_count read → trade_count<5 skip → avg_return read
        self.assertLess(trade_count_idx, sample_size_skip_idx)
        self.assertLess(sample_size_skip_idx, avg_return_idx)


# ─────────────────────────────────────────────────────────────────────
# EXCLUDED sites — verify intentional design hasn't been touched
# ─────────────────────────────────────────────────────────────────────


class TestExcludedSitesUnchanged(unittest.TestCase):
    """Sites 1, 2, 3 are intentional design per the diagnostic. Verify
    they remain in their pre-#115c form so a future audit doesn't
    flag them again as anti-pattern 2.
    """

    def test_transaction_cost_model_audit_field_preserved(self):
        src = (
            Path(__file__).parent.parent / "execution"
            / "transaction_cost_model.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'fill_probability = float(tcm_data.get("fill_probability") or 0.5)',
            src,
            "fill_probability sentinel is intentional (audit-only field; "
            "see #115c diagnostic). Preserve verbatim.",
        )

    def test_opportunity_scorer_strike_sentinels_preserved(self):
        src = (
            Path(__file__).parent.parent / "analytics" / "opportunity_scorer.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "short_strike = float(trade_candidate.get('short_strike') or 0.0)",
            src,
        )
        self.assertIn(
            "long_strike = float(trade_candidate.get('long_strike') or 0.0)",
            src,
        )


if __name__ == "__main__":
    unittest.main()
