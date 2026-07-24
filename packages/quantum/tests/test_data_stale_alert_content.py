"""A9 2026-07-02: data_stale alert content built from the arm that FIRED.

Pre-fix, `ops_health_check.run` ORed market_freshness | job_freshness to
decide WHEN to alert (:117) but built the message, details, and fingerprint
from market_freshness unconditionally (:139-149) — so every job-arm-only
firing emitted the self-contradictory
"Market data is stale ... Stale: 0 (). Reason: ok" shape (57/69 = 83% of the
trailing-30d `ops_data_stale` rows), and hashed the EMPTY market symbol list
into one shared fingerprint. The 2026-07-01 audit itself misdiagnosed the
class from that message.

Pins (content/fingerprint wiring ONLY — the firing predicate is untouched):
- job-arm-only → message names the job source + age + reason, carries NO
  market-data language; details carry trigger_source="job" + job_* keys and
  NO market keys; fingerprints are distinct per job_source.
- market-arm-only → the EXACT legacy message string AND the EXACT legacy
  fingerprint shape ({symbols, source}, no arms key) — cooldown history for
  the market class survives the deploy.
- both arms → both named, " | "-joined, trigger_source="market+job".
- REGRESSION FIXTURE: the verbatim 07-01 production shape (market fine,
  job-arm stale) can never again emit "Market data is stale" or
  "Stale: 0 (). Reason: ok".
- Source pins: run() routes through build_data_stale_alert_content; the
  legacy inline message construction is gone from run().
"""

import sys
import types
import unittest
from pathlib import Path

# Stub alpaca-py per convention.
from packages.quantum.tests._alpaca_stub import ensure_alpaca as _ensure_alpaca

_ensure_alpaca()

from packages.quantum.jobs.handlers.ops_health_check import (  # noqa: E402
    build_data_stale_alert_content,
)
from packages.quantum.services.ops_health_service import (  # noqa: E402
    DataFreshnessResult,
    MarketDataFreshnessResult,
    get_alert_fingerprint,
)


def _market(is_stale, stale_symbols=None, universe_size=9, age_seconds=673.406,
            source="MarketDataTruthLayer", reason="ok"):
    return MarketDataFreshnessResult(
        is_stale=is_stale,
        as_of=None,
        age_seconds=age_seconds,
        universe_size=universe_size,
        stale_symbols=stale_symbols or [],
        source=source,
        reason=reason,
    )


def _job(is_stale, source="job_runs", age_seconds=2700.0,
         reason="Last successful job > 30 min ago"):
    return DataFreshnessResult(
        is_stale=is_stale,
        as_of=None,
        age_seconds=age_seconds,
        reason=reason if is_stale else None,
        source=source,
    )


class TestJobArmOnly(unittest.TestCase):
    """The 83% class: job arm fired, market data is fine."""

    def test_message_names_the_job_not_the_market(self):
        msg, details, fp = build_data_stale_alert_content(
            _market(False), _job(True)
        )
        self.assertIn("Job-based data freshness is stale", msg)
        self.assertIn("Source: job_runs", msg)
        self.assertIn("Age: 45.0 min", msg)
        self.assertIn("Reason: Last successful job > 30 min ago", msg)
        self.assertNotIn("Market data is stale", msg)

    def test_details_carry_job_fields_and_no_market_fields(self):
        _, details, _ = build_data_stale_alert_content(
            _market(False), _job(True)
        )
        self.assertEqual(details["trigger_source"], "job")
        self.assertEqual(details["job_source"], "job_runs")
        self.assertEqual(details["job_age_seconds"], 2700.0)
        self.assertEqual(details["job_reason"], "Last successful job > 30 min ago")
        self.assertNotIn("universe_size", details)
        self.assertNotIn("stale_symbols", details)

    def test_fingerprint_distinct_per_job_source(self):
        _, _, fp_jobs = build_data_stale_alert_content(
            _market(False), _job(True, source="job_runs")
        )
        _, _, fp_sugg = build_data_stale_alert_content(
            _market(False), _job(True, source="trade_suggestions")
        )
        self.assertNotEqual(
            get_alert_fingerprint("data_stale", fp_jobs),
            get_alert_fingerprint("data_stale", fp_sugg),
        )

    def test_fingerprint_not_the_legacy_empty_market_shape(self):
        # Pre-fix, job-arm firings hashed {"symbols": [], "source":
        # "MarketDataTruthLayer"} — the shared bucket. Pin that the new
        # job-arm fingerprint differs from it.
        legacy = get_alert_fingerprint(
            "data_stale", {"symbols": [], "source": "MarketDataTruthLayer"}
        )
        _, _, fp = build_data_stale_alert_content(_market(False), _job(True))
        self.assertNotEqual(get_alert_fingerprint("data_stale", fp), legacy)


class TestMarketArmOnly(unittest.TestCase):
    """Market-arm firings must be byte-identical to the legacy output."""

    def test_exact_legacy_message(self):
        m = _market(
            True, stale_symbols=["SPY", "QQQ", "SOFI", "MARA"],
            universe_size=11, age_seconds=901.0, reason="stale_symbols",
        )
        msg, details, _ = build_data_stale_alert_content(m, _job(False))
        self.assertEqual(
            msg,
            "Market data is stale. Universe: 11 symbols. "
            "Stale: 4 (SPY, QQQ, SOFI). "
            "Source: MarketDataTruthLayer. Reason: stale_symbols",
        )
        self.assertEqual(details["trigger_source"], "market")
        self.assertEqual(details["universe_size"], 11)
        self.assertNotIn("job_source", details)

    def test_exact_legacy_fingerprint_shape(self):
        # Cooldown continuity: a market-arm-only firing must produce the
        # same fingerprint as the pre-fix code did for the same inputs.
        m = _market(True, stale_symbols=["SPY", "QQQ"], reason="stale_symbols")
        _, _, fp = build_data_stale_alert_content(m, _job(False))
        self.assertEqual(fp, {"symbols": ["QQQ", "SPY"], "source": "MarketDataTruthLayer"})
        self.assertNotIn("arms", fp)


class TestBothArms(unittest.TestCase):
    def test_both_named_and_joined(self):
        m = _market(True, stale_symbols=["SPY"], reason="stale_symbols")
        msg, details, fp = build_data_stale_alert_content(m, _job(True))
        self.assertIn("Market data is stale", msg)
        self.assertIn("Job-based data freshness is stale", msg)
        self.assertIn(" | ", msg)
        self.assertEqual(details["trigger_source"], "market+job")
        self.assertEqual(fp["arms"], ["market", "job"])
        self.assertIn("symbols", fp)
        self.assertIn("job_source", fp)


class TestRegressionFixture(unittest.TestCase):
    """The verbatim 2026-07-01 production rows: market fine (universe 9,
    stale 0, reason ok, age 54..673s), job arm stale. That exact
    self-contradictory shape can never emit again."""

    def test_the_contradiction_can_never_emit(self):
        for age in (54.368, 382.43, 416.369, 673.406):
            m = _market(False, universe_size=9, age_seconds=age, reason="ok")
            msg, details, _ = build_data_stale_alert_content(m, _job(True))
            self.assertNotIn("Market data is stale", msg)
            self.assertNotIn("Stale: 0 (). Reason: ok", msg)
            self.assertNotIn("stale_symbols", details)
            self.assertEqual(details["trigger_source"], "job")


class TestHandlerSourceWiring(unittest.TestCase):
    """run() routes data_stale content through the helper; the legacy inline
    construction is gone from the call site."""

    @classmethod
    def setUpClass(cls):
        cls.src = (
            Path(__file__).parent.parent / "jobs" / "handlers" / "ops_health_check.py"
        ).read_text(encoding="utf-8")

    def test_run_uses_the_helper(self):
        self.assertIn(
            "build_data_stale_alert_content(market_freshness, job_freshness)",
            self.src,
        )

    def test_legacy_inline_message_gone_from_run(self):
        # The market message template must exist exactly ONCE — inside the
        # helper — never rebuilt inline at the send site.
        self.assertEqual(self.src.count("Market data is stale. Universe:"), 1)

    def test_predicate_untouched(self):
        # 1c guard: the OR predicate is not this PR's surface.
        self.assertIn(
            "is_data_stale = market_freshness.is_stale or job_freshness.is_stale",
            self.src,
        )


if __name__ == "__main__":
    unittest.main()
