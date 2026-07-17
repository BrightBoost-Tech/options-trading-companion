"""Funnel telemetry phase-2 — strategy attribution on suggestion_rejections.

Route-driven proofs (doctrine: inject the failure at its ORIGIN, assert
the truth at the TOP) that:

1. Every post-selection rejection persists ``strategy_key`` — the
   attempted strategy is KNOWN at those sites (runtime evidence pre-fix:
   0/5,076 recent rows attributed).
2. The selector's PHASE GATE exclusion is a TYPED, ATTRIBUTED
   ``strategy_phase_excluded`` rejection — distinct from the generic
   ``strategy_hold_no_candidates`` bucket it used to hide in.
3. Pre-strategy rejections (missing_quotes etc.) stay honestly NULL —
   attribution is never fabricated for a rejection that happened before
   a strategy existed.
4. HOLD/CASH (empty pool, NO exclusions) is NOT mislabeled
   phase-excluded.
5. Persistence failures stay loud (warning + counter) with the strategy
   kwarg present — the retry/fail-soft path is not weakened.

Tests drive the REAL ``scan_for_opportunities`` (real process_symbol,
real RejectionStats with persistence configured, and — for the phase
tests — the REAL StrategySelector.get_candidates) with stubs only at
genuine data boundaries (market data, regime engine, agents, supabase).
Assertions are on the scan OUTPUT: the in-memory histograms AND the
durable ``suggestion_rejections`` insert payloads.
"""

import unittest
from collections import defaultdict
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import packages.quantum.options_scanner as scanner_mod
from packages.quantum.analytics.regime_engine_v3 import RegimeState
from packages.quantum.analytics.strategy_selector import StrategySelector
from packages.quantum.options_scanner import RejectionStats

SYMBOL = "TEST"


# ─────────────────────────────────────────────────────────────────
# Fake supabase — permissive recorder; suggestion_rejections inserts
# are captured for payload assertions. strategy_lifecycle_states is
# scriptable so the route can pass the lifecycle gate when needed.
# ─────────────────────────────────────────────────────────────────


class _FakeQuery:
    def __init__(self, parent, table_name):
        self._parent = parent
        self._table = table_name
        self._op = "select"
        self._payload = None

    def select(self, *a, **k):
        self._op = "select"
        return self

    def insert(self, payload):
        self._op = "insert"
        self._payload = payload
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def eq(self, *a, **k):
        return self

    def neq(self, *a, **k):
        return self

    def gte(self, *a, **k):
        return self

    def lte(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        return self._parent._execute(self._table, self._op, self._payload)


class FakeSupabase:
    def __init__(self, lifecycle_rows=None):
        self.lifecycle_rows = lifecycle_rows or []
        self.inserted = defaultdict(list)

    def table(self, name):
        return _FakeQuery(self, name)

    @property
    def rejection_rows(self):
        return self.inserted["suggestion_rejections"]

    def _execute(self, table, op, payload):
        if table == "strategy_lifecycle_states" and op == "select":
            return SimpleNamespace(data=list(self.lifecycle_rows))
        if op == "insert":
            self.inserted[table].append(payload)
            return SimpleNamespace(data=[payload])
        if table == "risk_alerts" and op == "select":
            # Non-empty → iv-pipeline alert dedup short-circuits.
            return SimpleNamespace(data=[{"id": "dedup-hit"}])
        return SimpleNamespace(data=[])


# ─────────────────────────────────────────────────────────────────
# Data-boundary fixtures
# ─────────────────────────────────────────────────────────────────


class _FakeGlobalSnapshot:
    state = RegimeState.NORMAL

    def to_dict(self):
        return {"state": "NORMAL"}


def _fake_truth_layer(closes_profile="rising", chain=None, quote=True):
    truth = MagicMock()
    truth.normalize_symbol.side_effect = lambda s: s
    if quote:
        truth.snapshot_many.return_value = {
            SYMBOL: {
                "quote": {"bid": 99.95, "ask": 100.05, "mid": 100.0,
                          "last": 100.0},
            }
        }
    else:
        truth.snapshot_many.return_value = {}
    if closes_profile == "rising":
        truth.daily_bars.return_value = [
            {"close": 100.0 + i} for i in range(60)
        ]
    else:  # flat → NEUTRAL trend
        truth.daily_bars.return_value = [{"close": 100.0}] * 60
    truth.option_chain.return_value = chain if chain is not None else []
    return truth


def _fake_regime(iv_rank=45.0):
    regime = MagicMock()
    regime.iv_repo = None
    regime.compute_symbol_snapshot.return_value = SimpleNamespace(
        iv_rank=iv_rank, iv_rank_quality="real", iv_rv_spread=None,
    )
    regime.get_effective_regime.return_value = SimpleNamespace(value="normal")
    return regime


def _wide_spread_chain():
    """Two calls ~35 DTE whose combo spread is wide relative to the
    entry cost: buy@ask 3.50 / sell@bid 1.00 → combo_spread_share=1.00,
    mid debit 2.00 → spread_pct 50% > 10% threshold and combo > $0.20 →
    spread_too_wide_real at the liquidity gate."""
    expiry = (datetime.now().date() + timedelta(days=35)).isoformat()

    def contract(strike, delta, bid, ask):
        mid = round((bid + ask) / 2.0, 4)
        return {
            "contract": f"{SYMBOL}{int(strike)}C",
            "strike": strike,
            "expiry": expiry,
            "type": "call",
            "greeks": {
                "delta": delta, "gamma": 0.02, "vega": 0.10, "theta": -0.05,
            },
            "quote": {"bid": bid, "ask": ask, "mid": mid, "last": mid},
        }

    return [
        contract(100.0, 0.55, 3.00, 3.50),
        contract(105.0, 0.30, 1.00, 1.50),
    ]


def _run_scan(fake_supabase, truth, regime, selector=None, env=None):
    """Drive the REAL scan_for_opportunities for one symbol. When
    ``selector`` is None the REAL StrategySelector runs (phase-gate
    tests need it); otherwise the provided stub is used."""
    polygon = MagicMock()
    polygon.get_recent_quote.return_value = {}
    polygon.get_historical_prices.return_value = {"prices": []}
    polygon.get_option_chain.return_value = []
    polygon.get_ticker_details.return_value = {"sic_description": "Tech"}

    earnings = MagicMock()
    earnings.get_earnings_map.return_value = {}

    patches = [
        patch.object(scanner_mod, "MarketDataTruthLayer", return_value=truth),
        patch.object(scanner_mod, "RegimeEngineV3", return_value=regime),
        patch.object(scanner_mod, "PolygonService", return_value=polygon),
        patch.object(scanner_mod, "EarningsCalendarService",
                     return_value=earnings),
        patch.object(scanner_mod, "UniverseService", MagicMock()),
        patch.object(scanner_mod, "ExecutionService", MagicMock()),
        patch.object(scanner_mod, "IVRepository", MagicMock()),
        patch.object(scanner_mod, "IVPointService", MagicMock()),
        patch.object(scanner_mod, "build_agent_pipeline", lambda *a, **k: []),
    ]
    if selector is not None:
        patches.append(
            patch.object(scanner_mod, "StrategySelector",
                         return_value=selector)
        )
    if env is not None:
        patches.append(patch.dict("os.environ", env))

    with patch("builtins.print"):  # keep route noise out of test output
        for p in patches:
            p.start()
        try:
            return scanner_mod.scan_for_opportunities(
                symbols=[SYMBOL],
                supabase_client=fake_supabase,
                global_snapshot=_FakeGlobalSnapshot(),
            )
        finally:
            for p in patches:
                p.stop()


def _rows_for(fake, reason):
    return [r for r in fake.rejection_rows if r["reason"] == reason]


# ─────────────────────────────────────────────────────────────────
# 1. Post-selection rejections carry strategy_key (primary, fallback,
#    all_strategies_rejected identity preservation)
# ─────────────────────────────────────────────────────────────────


class TestPostSelectionAttribution(unittest.TestCase):
    """Real selector, BULLISH pool [LONG_CALL_DEBIT_SPREAD,
    SHORT_PUT_CREDIT_SPREAD], chain dark at the ORIGIN → primary and
    fallback both die at no_chain, each row attributed to ITS attempt."""

    @classmethod
    def setUpClass(cls):
        cls.fake = FakeSupabase()
        cls.candidates, cls.rej_stats = _run_scan(
            cls.fake,
            truth=_fake_truth_layer(closes_profile="rising", chain=[]),
            regime=_fake_regime(iv_rank=45.0),  # normal vol → 2-strategy pool
            selector=None,  # REAL selector
        )
        cls.stats = cls.rej_stats.to_dict()

    def test_route_reached_gates(self):
        self.assertNotIn(
            "processing_error", self.stats["rejection_counts"],
            f"fixture drift: {self.stats['rejection_counts']}",
        )
        self.assertEqual(self.candidates, [])

    def test_primary_rejection_carries_strategy_key(self):
        rows = _rows_for(self.fake, "no_chain")
        strategies = [r["strategy_key"] for r in rows]
        self.assertIn("LONG_CALL_DEBIT_SPREAD", strategies)

    def test_fallback_rejection_carries_strategy_key(self):
        rows = _rows_for(self.fake, "no_chain")
        strategies = [r["strategy_key"] for r in rows]
        self.assertIn("SHORT_PUT_CREDIT_SPREAD", strategies)

    def test_per_attempt_identities_preserved(self):
        """all_strategies_rejected: each attempt keeps its OWN identity;
        the multi-attempt summary row itself stays honestly NULL."""
        no_chain = _rows_for(self.fake, "no_chain")
        self.assertEqual(
            sorted(r["strategy_key"] for r in no_chain),
            ["LONG_CALL_DEBIT_SPREAD", "SHORT_PUT_CREDIT_SPREAD"],
        )
        summary = _rows_for(self.fake, "all_strategies_rejected")
        self.assertEqual(len(summary), 1)
        self.assertIsNone(summary[0]["strategy_key"])
        # In-memory dimension matches the durable rows.
        by_strat = self.stats["rejection_counts_by_strategy_and_reason"]
        self.assertEqual(
            by_strat["LONG_CALL_DEBIT_SPREAD"]["no_chain"], 1)
        self.assertEqual(
            by_strat["SHORT_PUT_CREDIT_SPREAD"]["no_chain"], 1)
        self.assertEqual(
            by_strat[RejectionStats.PRE_STRATEGY_KEY][
                "all_strategies_rejected"], 1)


class TestDeepGateAttribution(unittest.TestCase):
    """A rejection deep in the pipeline (liquidity/spread gate, a
    record_with_sample site) carries strategy_key too — attribution is
    threaded through the sample path, not just plain record()."""

    def test_spread_rejection_attributed(self):
        fake = FakeSupabase(lifecycle_rows=[
            {"strategy_name": "LONG_CALL_DEBIT_SPREAD",
             "current_state": "live_full"},
            {"strategy_name": "SHORT_PUT_CREDIT_SPREAD",
             "current_state": "live_full"},
        ])
        selector = MagicMock()
        selector.get_candidates.return_value = [{
            "strategy": "LONG_CALL_DEBIT_SPREAD",
            "legs": [
                {"side": "buy", "type": "call", "delta_target": 0.55},
                {"side": "sell", "type": "call", "delta_target": 0.30},
            ],
        }]
        candidates, rej_stats = _run_scan(
            fake,
            truth=_fake_truth_layer(
                closes_profile="rising", chain=_wide_spread_chain()),
            regime=_fake_regime(iv_rank=45.0),
            selector=selector,
        )
        d = rej_stats.to_dict()
        self.assertNotIn("processing_error", d["rejection_counts"],
                         d["rejection_counts"])
        self.assertEqual(candidates, [])
        rows = _rows_for(fake, "spread_too_wide_real")
        self.assertEqual(len(rows), 1, [r["reason"] for r in
                                        fake.rejection_rows])
        self.assertEqual(rows[0]["strategy_key"], "LONG_CALL_DEBIT_SPREAD")
        self.assertEqual(rows[0]["symbol"], SYMBOL)
        # The sample still rides along in spread_debug.
        self.assertIn("spread_debug", rows[0])


# ─────────────────────────────────────────────────────────────────
# 2. Phase exclusion: typed + attributed, phase-dependent
# ─────────────────────────────────────────────────────────────────


class TestPhaseExclusionTyped(unittest.TestCase):
    """NEUTRAL + high IV → real selector pool is [IRON_CONDOR] only.
    alpaca_paper: the phase gate empties the pool → typed
    strategy_phase_excluded attributed to IRON_CONDOR, and NO
    strategy_hold_no_candidates mislabel. micro_live (same inputs):
    no exclusion — the condor flows to the chain and dies no_chain
    WITH condor attribution."""

    def _scan(self, phase):
        fake = FakeSupabase()
        candidates, rej_stats = _run_scan(
            fake,
            truth=_fake_truth_layer(closes_profile="flat", chain=[]),
            regime=_fake_regime(iv_rank=70.0),  # high vol → condor pool
            selector=None,  # REAL selector (the phase gate under test)
            env={"CURRENT_PROGRESSION_PHASE": phase},
        )
        return fake, candidates, rej_stats.to_dict()

    def test_alpaca_paper_records_typed_attributed_exclusion(self):
        fake, candidates, d = self._scan("alpaca_paper")
        self.assertNotIn("processing_error", d["rejection_counts"])
        self.assertEqual(candidates, [])
        rows = _rows_for(fake, "strategy_phase_excluded")
        self.assertEqual(len(rows), 1,
                         [r["reason"] for r in fake.rejection_rows])
        self.assertEqual(rows[0]["strategy_key"], "IRON_CONDOR")
        self.assertEqual(rows[0]["symbol"], SYMBOL)
        # NOT the generic bucket: the emptiness is explained by the
        # typed row, never double-labeled a scored HOLD.
        self.assertEqual(_rows_for(fake, "strategy_hold_no_candidates"), [])
        self.assertNotIn("strategy_hold_no_candidates",
                         d["rejection_counts"])
        self.assertEqual(
            d["rejection_counts_by_strategy_and_reason"]["IRON_CONDOR"][
                "strategy_phase_excluded"], 1)

    def test_micro_live_same_inputs_no_exclusion(self):
        fake, candidates, d = self._scan("micro_live")
        self.assertNotIn("processing_error", d["rejection_counts"])
        self.assertEqual(candidates, [])
        # No phase exclusion in micro_live.
        self.assertEqual(_rows_for(fake, "strategy_phase_excluded"), [])
        self.assertNotIn("strategy_phase_excluded", d["rejection_counts"])
        # The condor attempt PROCEEDED and died downstream at the dark
        # chain — attributed to IRON_CONDOR.
        rows = _rows_for(fake, "no_chain")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["strategy_key"], "IRON_CONDOR")


class TestHoldNotMislabeledPhaseExcluded(unittest.TestCase):
    """NEUTRAL + LOW IV → the real selector's pool is genuinely empty
    (no premium edge) with NO phase exclusions: the verdict must stay
    strategy_hold_no_candidates and never become phase-excluded."""

    def test_hold_cash_stays_hold(self):
        fake = FakeSupabase()
        candidates, rej_stats = _run_scan(
            fake,
            truth=_fake_truth_layer(closes_profile="flat", chain=[]),
            regime=_fake_regime(iv_rank=40.0),  # neutral + normal vol → empty pool
            selector=None,
            env={"CURRENT_PROGRESSION_PHASE": "alpaca_paper"},
        )
        d = rej_stats.to_dict()
        self.assertNotIn("processing_error", d["rejection_counts"])
        self.assertEqual(candidates, [])
        self.assertEqual(_rows_for(fake, "strategy_phase_excluded"), [])
        rows = _rows_for(fake, "strategy_hold_no_candidates")
        self.assertEqual(len(rows), 1)
        # The generic bucket stays honestly UNattributed (no strategy
        # was selected — nothing to attribute).
        self.assertIsNone(rows[0]["strategy_key"])


class TestSelectorSeamContract(unittest.TestCase):
    """Unit contract on the get_candidates out-param: report-only,
    dedup'd, and byte-identical candidates with or without it."""

    def _call(self, phase, out=None):
        with patch.dict("os.environ", {"CURRENT_PROGRESSION_PHASE": phase}):
            return StrategySelector().get_candidates(
                ticker=SYMBOL,
                sentiment="NEUTRAL",
                current_price=100.0,
                iv_rank=70.0,
                effective_regime="normal",
                phase_exclusions_out=out,
            )

    def test_exclusions_reported_in_alpaca_paper(self):
        out = []
        cands = self._call("alpaca_paper", out)
        self.assertEqual(cands, [])
        self.assertEqual(
            out, [{"strategy": "IRON_CONDOR", "phase": "alpaca_paper"}])

    def test_no_exclusions_in_micro_live(self):
        out = []
        cands = self._call("micro_live", out)
        self.assertEqual([c["strategy"] for c in cands], ["IRON_CONDOR"])
        self.assertEqual(out, [])

    def test_candidates_identical_with_and_without_out_param(self):
        for phase in ("alpaca_paper", "micro_live"):
            with_out = self._call(phase, [])
            without_out = self._call(phase, None)
            self.assertEqual(with_out, without_out, phase)

    def test_shock_empty_pool_reports_nothing(self):
        """SHOCK's early [] return happens BEFORE the phase gate — it
        is a regime verdict, not a phase exclusion."""
        out = []
        with patch.dict("os.environ",
                        {"CURRENT_PROGRESSION_PHASE": "alpaca_paper"}):
            cands = StrategySelector().get_candidates(
                ticker=SYMBOL,
                sentiment="NEUTRAL",
                current_price=100.0,
                iv_rank=70.0,
                effective_regime="shock",
                phase_exclusions_out=out,
            )
        self.assertEqual(cands, [])
        self.assertEqual(out, [])


# ─────────────────────────────────────────────────────────────────
# 3. Pre-strategy rejections stay honestly NULL
# ─────────────────────────────────────────────────────────────────


class TestPreStrategyStaysNull(unittest.TestCase):
    def test_missing_quotes_row_has_null_strategy_key(self):
        fake = FakeSupabase()
        candidates, rej_stats = _run_scan(
            fake,
            truth=_fake_truth_layer(quote=False),  # ORIGIN: no quote at all
            regime=_fake_regime(),
            selector=None,
        )
        d = rej_stats.to_dict()
        self.assertEqual(candidates, [])
        rows = _rows_for(fake, "missing_quotes")
        self.assertEqual(len(rows), 1,
                         [r["reason"] for r in fake.rejection_rows])
        self.assertIsNone(rows[0]["strategy_key"])
        self.assertEqual(
            d["rejection_counts_by_strategy_and_reason"][
                RejectionStats.PRE_STRATEGY_KEY]["missing_quotes"], 1)

    def test_pre_selection_processing_error_stays_null(self):
        """A crash BEFORE strategy selection persists processing_error
        with strategy_key NULL — attribution is never fabricated."""
        fake = FakeSupabase()
        truth = _fake_truth_layer(closes_profile="rising", chain=[])
        # ORIGIN: daily_bars (pre-selection callee) explodes.
        truth.daily_bars.side_effect = RuntimeError("bars feed down")
        candidates, rej_stats = _run_scan(
            fake, truth=truth, regime=_fake_regime(), selector=None,
        )
        rows = _rows_for(fake, "processing_error")
        # The polygon history fallback swallows its own errors, so the
        # symbol either dies insufficient_history (fallback empty) or
        # processing_error — both must be NULL-attributed. Assert on
        # whichever the route produced.
        if rows:
            self.assertIsNone(rows[0]["strategy_key"])
        else:
            hist = _rows_for(fake, "insufficient_history")
            self.assertEqual(len(hist), 1)
            self.assertIsNone(hist[0]["strategy_key"])
        self.assertEqual(candidates, [])

    def test_post_selection_processing_error_is_attributed(self):
        """A crash AFTER selection carries the attempted strategy —
        the same reason code is attributed exactly when it is known."""
        fake = FakeSupabase()
        selector = MagicMock()
        selector.get_candidates.return_value = [{
            "strategy": "LONG_CALL_DEBIT_SPREAD",
            "legs": [
                {"side": "buy", "type": "call", "delta_target": 0.55},
                {"side": "sell", "type": "call", "delta_target": 0.30},
            ],
        }]
        truth = _fake_truth_layer(closes_profile="rising")
        # ORIGIN: the chain fetch (a post-selection callee) explodes —
        # and so does the polygon fallback inside process_symbol.
        truth.option_chain.side_effect = RuntimeError("chain feed down")
        polygon = MagicMock()
        polygon.get_recent_quote.return_value = {}
        polygon.get_historical_prices.return_value = {"prices": []}
        polygon.get_option_chain.side_effect = RuntimeError("polygon down")
        polygon.get_ticker_details.return_value = {"sic_description": "Tech"}
        earnings = MagicMock()
        earnings.get_earnings_map.return_value = {}
        with patch.object(scanner_mod, "MarketDataTruthLayer",
                          return_value=truth), \
             patch.object(scanner_mod, "RegimeEngineV3",
                          return_value=_fake_regime()), \
             patch.object(scanner_mod, "StrategySelector",
                          return_value=selector), \
             patch.object(scanner_mod, "PolygonService",
                          return_value=polygon), \
             patch.object(scanner_mod, "EarningsCalendarService",
                          return_value=earnings), \
             patch.object(scanner_mod, "UniverseService", MagicMock()), \
             patch.object(scanner_mod, "ExecutionService", MagicMock()), \
             patch.object(scanner_mod, "IVRepository", MagicMock()), \
             patch.object(scanner_mod, "IVPointService", MagicMock()), \
             patch.object(scanner_mod, "build_agent_pipeline",
                          lambda *a, **k: []), \
             patch("builtins.print"):
            candidates, rej_stats = scanner_mod.scan_for_opportunities(
                symbols=[SYMBOL],
                supabase_client=fake,
                global_snapshot=_FakeGlobalSnapshot(),
            )
        rows = _rows_for(fake, "processing_error")
        self.assertGreaterEqual(len(rows), 1,
                                [r["reason"] for r in fake.rejection_rows])
        self.assertEqual(rows[0]["strategy_key"], "LONG_CALL_DEBIT_SPREAD")
        self.assertEqual(candidates, [])


# ─────────────────────────────────────────────────────────────────
# 4. Persistence failure stays loud with the strategy kwarg
# ─────────────────────────────────────────────────────────────────


class _RaisingSupabase:
    def table(self, name):
        return self

    def insert(self, payload):
        self.payload = payload
        return self

    def execute(self):
        raise RuntimeError("simulated non-transient db failure")


class TestPersistFailureStaysLoud(unittest.TestCase):
    def test_attributed_record_failure_warns_and_counts(self):
        rs = RejectionStats(
            supabase=_RaisingSupabase(), cycle_date=date(2026, 7, 16)
        )
        rs.set_symbol(SYMBOL)
        with self.assertLogs(
            "packages.quantum.options_scanner", level="WARNING"
        ) as cm:
            rs.record("strategy_phase_excluded", strategy="IRON_CONDOR")
        joined = "\n".join(cm.output)
        self.assertIn("suggestion_rejections insert failed", joined)
        self.assertIn("IRON_CONDOR", joined)  # strategy named in the warning
        d = rs.to_dict()
        self.assertEqual(d["persist_failures"], 1)
        # The aggregate attribution still landed despite the DB failure.
        self.assertEqual(
            d["rejection_counts_by_strategy_and_reason"]["IRON_CONDOR"][
                "strategy_phase_excluded"], 1)


if __name__ == "__main__":
    unittest.main()
