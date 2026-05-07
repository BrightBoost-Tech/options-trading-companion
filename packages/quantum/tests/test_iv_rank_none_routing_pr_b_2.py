"""Tests for #115 PR-B-2 — None-routing at the remaining 3 consumer sites.

Same flag (`IV_RANK_NONE_ROUTING_ENABLED`, default OFF) introduced by
PR-B-1. Each site has site-specific semantics determined during the
intent diagnostic; tests assert both flag-OFF (legacy preserved) and
flag-ON (new routing) behavior.

The same `sys.modules` poisoning by `test_weekly_report_win_rate.py`
that bit PR-B-1 applies here for `conviction_service`. Fix mirrored:
clear pollution + bind real classes at file load time, then have test
methods read the captured globals.
"""

import importlib
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Defensive remediation — see test_iv_rank_none_routing.py for the long
# explanation. weekly_report stamps several sys.modules keys with
# MagicMocks at module-import time; clear them before our imports.
for _modname in (
    "packages.quantum.analytics.conviction_service",
    "packages.quantum.analytics.opportunity_scorer",
    "packages.quantum.agents.agents.strategy_design_agent",
):
    sys.modules.pop(_modname, None)

ConvictionService_mod = importlib.import_module(
    "packages.quantum.analytics.conviction_service"
)
OpportunityScorer_mod = importlib.import_module(
    "packages.quantum.analytics.opportunity_scorer"
)
StrategyDesignAgent_mod = importlib.import_module(
    "packages.quantum.agents.agents.strategy_design_agent"
)

ConvictionService = ConvictionService_mod.ConvictionService
PositionDescriptor = ConvictionService_mod.PositionDescriptor
OpportunityScorer = OpportunityScorer_mod.OpportunityScorer
StrategyDesignAgent = StrategyDesignAgent_mod.StrategyDesignAgent

assert not isinstance(ConvictionService, MagicMock), (
    "conviction_service was already mocked at file-load time"
)
assert not isinstance(StrategyDesignAgent, MagicMock), (
    "strategy_design_agent was already mocked at file-load time"
)


class _FlagFixture(unittest.TestCase):
    def setUp(self):
        self._prior = os.environ.pop("IV_RANK_NONE_ROUTING_ENABLED", None)

    def tearDown(self):
        os.environ.pop("IV_RANK_NONE_ROUTING_ENABLED", None)
        if self._prior is not None:
            os.environ["IV_RANK_NONE_ROUTING_ENABLED"] = self._prior


class TestStrategyDesignAgent(_FlagFixture):
    """Site 1: high-IV override branch must be skipped (not silently
    routed through fabricated 50.0) when iv_rank is None and the flag
    is ON.
    """

    def _eval(self, context):
        return StrategyDesignAgent().evaluate(context)

    def test_flag_off_iv_none_uses_50_default(self):
        """Legacy: missing iv_rank → 50.0 → high-IV branch evaluates
        as `50 >= 60` False → no override → recommended stays as
        legacy strategy.
        """
        sig = self._eval({
            "legacy_strategy": "LONG CALL",
            "effective_regime": "NORMAL",
            "iv_rank": None,
        })
        self.assertEqual(
            sig.metadata["constraints"]["strategy.recommended"],
            "long_call",
        )
        self.assertFalse(sig.metadata["constraints"]["strategy.override_selector"])

    def test_flag_on_iv_none_skips_high_iv_branch(self):
        """Flag ON: missing iv_rank → branch skipped, but legacy
        strategy still emerges. SHOCK / CHOP / policy gates still
        run; output equivalent to flag-OFF for non-edge cases.
        """
        os.environ["IV_RANK_NONE_ROUTING_ENABLED"] = "1"
        sig = self._eval({
            "legacy_strategy": "LONG CALL",
            "effective_regime": "NORMAL",
            "iv_rank": None,
        })
        self.assertEqual(
            sig.metadata["constraints"]["strategy.recommended"],
            "long_call",
        )

    def test_flag_on_high_iv_still_overrides(self):
        """Flag ON with valid high iv_rank: high-IV override branch
        fires normally. PR-B-2 must not break the iv-aware path.
        """
        os.environ["IV_RANK_NONE_ROUTING_ENABLED"] = "1"
        sig = self._eval({
            "legacy_strategy": "LONG CALL",
            "effective_regime": "NORMAL",
            "iv_rank": 75.0,
        })
        self.assertEqual(
            sig.metadata["constraints"]["strategy.recommended"],
            "credit_put_spread",
        )
        self.assertTrue(sig.metadata["constraints"]["strategy.override_selector"])

    def test_flag_off_high_iv_still_overrides(self):
        """Sanity: legacy iv-aware override path is unchanged."""
        sig = self._eval({
            "legacy_strategy": "LONG CALL",
            "effective_regime": "NORMAL",
            "iv_rank": 75.0,
        })
        self.assertEqual(
            sig.metadata["constraints"]["strategy.recommended"],
            "credit_put_spread",
        )

    def test_flag_on_shock_overrides_regardless_of_iv(self):
        """Flag ON: SHOCK regime override does not depend on iv_rank;
        confirm the missing-iv branch-skip didn't accidentally suppress
        non-iv overrides.
        """
        os.environ["IV_RANK_NONE_ROUTING_ENABLED"] = "1"
        sig = self._eval({
            "legacy_strategy": "LONG CALL",
            "effective_regime": "SHOCK",
            "iv_rank": None,
        })
        self.assertEqual(
            sig.metadata["constraints"]["strategy.recommended"],
            "cash",
        )


class TestConvictionService(_FlagFixture):
    """Site 2: helper must return None when iv_rank is None and flag
    is ON, so the caller routes to conviction=0.5 instead of scoring
    against a fabricated 50.0.
    """

    def _service(self):
        # Pass mock scoring engine via constructor to avoid the
        # __new__ bypass (sys.modules pollution can poison
        # ConvictionService itself if test ordering shifts).
        svc = ConvictionService(scoring_engine=MagicMock(), supabase=None)
        svc.scoring.calculate_score.return_value = {"raw_score": 50.0}
        return svc

    def _pos(self, iv_rank):
        return PositionDescriptor(
            symbol="AAPL",
            underlying="AAPL",
            strategy_type="long_call",
            direction="long",
            iv_rank=iv_rank,
        )

    def test_flag_off_iv_none_uses_50_fallback(self):
        """Legacy: helper computes a score from fabricated 50.0
        volatility factor and returns the scoring engine result
        (50.0 in our mock).
        """
        result = self._service()._compute_raw_score_helper(
            self._pos(iv_rank=None), "normal",
        )
        self.assertEqual(result, 50.0)

    def test_flag_on_iv_none_returns_none(self):
        """Flag ON: helper returns None so the caller branches to
        conviction=0.5 (neutral).
        """
        os.environ["IV_RANK_NONE_ROUTING_ENABLED"] = "1"
        result = self._service()._compute_raw_score_helper(
            self._pos(iv_rank=None), "normal",
        )
        self.assertIsNone(result)

    def test_flag_on_valid_iv_uses_value(self):
        """Flag ON with a real iv_rank: scoring runs normally."""
        os.environ["IV_RANK_NONE_ROUTING_ENABLED"] = "1"
        result = self._service()._compute_raw_score_helper(
            self._pos(iv_rank=70.0), "normal",
        )
        self.assertEqual(result, 50.0)  # mock returns 50 regardless of factors


class TestOpportunityScorerIvBonus(_FlagFixture):
    """Site 3: the most-impactful site. Pre-fix silently gave debit
    candidates the maximum 10-point bonus when iv_rank was missing.
    """

    def _ctx(self, iv_rank, **overrides):
        ctx = {
            "iv_rank": iv_rank,
            "bid": 1.0,
            "ask": 1.05,
        }
        ctx.update(overrides)
        return ctx

    def _candidate(self, is_credit):
        # Public entrypoint is `score`, and `is_credit` is derived from
        # the `type` field via 'credit' substring check, OR from a
        # non-None `credit` key. Use a 5-wide vertical so the geometry
        # is sane.
        if is_credit:
            return {
                "symbol": "AAPL",
                "type": "credit_put_spread",
                "short_strike": 100.0,
                "long_strike": 95.0,
                "credit": 1.0,
                "dte": 30,
            }
        return {
            "symbol": "AAPL",
            "type": "long_call",
            "short_strike": 0.0,
            "long_strike": 100.0,
            "debit": 1.0,
            "dte": 30,
        }

    def _score(self, candidate, market_ctx):
        # Public entrypoint; iv_bonus surfaces in the debug subdict.
        market_ctx = dict(market_ctx)
        market_ctx.setdefault("price", 105.0)
        return OpportunityScorer.score(candidate, market_ctx)

    def test_flag_off_iv_none_debit_gets_max_bonus(self):
        """Legacy: `or 0.0` → debit gets `(50 - 0) * 0.2 = 10` bonus.
        This is the bug the fix addresses; we lock in the legacy
        behavior so a future regression is detectable.
        """
        result = self._score(
            self._candidate(is_credit=False),
            self._ctx(iv_rank=None),
        )
        self.assertEqual(result["debug"]["iv_bonus"], 10.0)

    def test_flag_on_iv_none_no_bonus(self):
        """Flag ON: missing iv_rank → no fabricated bonus."""
        os.environ["IV_RANK_NONE_ROUTING_ENABLED"] = "1"
        result = self._score(
            self._candidate(is_credit=False),
            self._ctx(iv_rank=None),
        )
        self.assertEqual(result["debug"]["iv_bonus"], 0.0)

    def test_flag_on_credit_with_high_iv_still_bonused(self):
        """Flag ON + valid high iv_rank: credit gets normal bonus."""
        os.environ["IV_RANK_NONE_ROUTING_ENABLED"] = "1"
        result = self._score(
            self._candidate(is_credit=True),
            self._ctx(iv_rank=80.0),
        )
        # (80 - 50) * 0.2 = 6.0
        self.assertEqual(result["debug"]["iv_bonus"], 6.0)

    def test_flag_off_credit_with_high_iv_still_bonused(self):
        """Sanity: legacy bonus computation unchanged for valid input."""
        result = self._score(
            self._candidate(is_credit=True),
            self._ctx(iv_rank=80.0),
        )
        self.assertEqual(result["debug"]["iv_bonus"], 6.0)


if __name__ == "__main__":
    unittest.main()
