"""E19-2 Blocker 6 — THE FULL PRODUCTION ROUTE.

Drives, with NO intermediate mocks of orchestrator/ranker/fork/handler:

    scanner fixture (external input boundary)
        → suggestions_open.run                (REAL handler)
        → run_midday_cycle                    (REAL orchestrator)
        → apply_calibration (REAL, blob ×0.5 from the calibration data
          boundary) → compute_risk_adjusted_ev (REAL) → calibrated RAeV=-999
        → orchestrator persists NOT_EXECUTABLE / edge_below_minimum
        → handler invokes fork (REAL)
        → raw-basis clone + accepted verdict produced
        → top-level job result truthful (green here; partial under injection)

Injections happen ONLY at genuine external boundaries: the scanner (data
producer), the calibration adjustments blob (data), broker/market reads
(CashService / regime / progression / position scope), and the database
(the hardened contract fake). The SOFI numbers are the 2026-07-13 live
exhibit; the REJECTION ITSELF is caused by the real calibration + ranker
math, never pre-seeded.
"""
import os
import unittest
import uuid
from unittest.mock import patch

from packages.quantum.policy_lab.config import PolicyConfig
from packages.quantum.tests.test_prerejection_fork_e19 import (
    FakeSupabase, UID, _cohort_configs,
)
from packages.quantum.policy_lab import fork as fork_mod


def _scanner_candidate():
    """The scanner-output shape (options_scanner candidate_dict) for the
    SOFI vertical: RAW ev 30.73 — after the ×0.5 calibration blob the
    calibrated ev is ~15.37, and the canonical ranker's slippage(5%)+fees
    ($1.30) push net edge below MIN_EDGE_AFTER_COSTS=$15 → -999."""
    return {
        "symbol": "SOFI", "ticker": "SOFI",
        "type": "LONG_CALL_DEBIT_SPREAD", "strategy": "LONG_CALL_DEBIT_SPREAD",
        "strategy_key": "long_call_debit_spread",
        "lifecycle_state": "live_full",
        "suggested_entry": 0.30, "ev": 30.73, "score": 65.0,
        "probability_of_profit": 0.55,
        "unified_score_details": {},
        "iv_rank": 50.0, "iv_rank_quality": "ok", "iv_rv_spread": None,
        "premium_direction": "debit", "trend": "up",
        "badges": [], "execution_drag_estimate": 0.05,
        "legs": [
            {"symbol": "SOFI260821C00026000", "side": "buy", "strike": 26.0,
             "type": "call", "expiry": "2026-08-21", "mid": 0.60,
             "bid": 0.55, "ask": 0.65, "delta": 0.40, "quantity": 1},
            {"symbol": "SOFI260821C00028000", "side": "sell", "strike": 28.0,
             "type": "call", "expiry": "2026-08-21", "mid": 0.30,
             "bid": 0.25, "ask": 0.35, "delta": 0.20, "quantity": 1},
        ],
    }


class _RejStats:
    def to_dict(self):
        return {}

    def top_reasons(self, _n):
        return []

    def record(self, *_a, **_k):
        pass


class _FakeState:
    value = "normal"


class _FakeSnap:
    state = _FakeState()
    vix = 18.0
    rv_20d = 0.15
    iv_rank = 50.0
    breadth = 0.5
    regime_score = 50.0
    as_of_ts = "2026-07-13T16:00:00+00:00"


class _FakeSymSnap:
    """Per-symbol regime/IV context — an external market-data product."""
    state = _FakeState()
    symbol = "SOFI"
    iv_rank = 50.0
    iv_rank_quality = "ok"
    iv_rv_spread = None
    rv_20d = 0.15
    as_of_ts = "2026-07-13T16:00:00+00:00"
    quality_flags = {}


def _async_return(value):
    async def _f(*_a, **_k):
        return value
    return _f


class _FakeCashService:
    """Broker-capital boundary. Patched at the ORCHESTRATOR's namespace
    (patch.object(wo, 'CashService')) — class-path patches are defeated in
    the full CI suite by earlier tests that stub sys.modules."""

    def __init__(self, *_a, **_k):
        pass

    async def get_deployable_capital(self, *_a, **_k):
        return 2000.0


class _FakeRegimeEngine:
    """Market-regime data boundary, anchored at the orchestrator namespace."""

    def __init__(self, *_a, **_k):
        pass

    def compute_global_snapshot(self, *_a, **_k):
        return _FakeSnap()

    def compute_symbol_snapshot(self, *_a, **_k):
        return _FakeSymSnap()

    def get_effective_regime(self, *_a, **_k):
        return _FakeState()

    def map_to_scoring_regime(self, *_a, **_k):
        return "normal"


class TestFullProductionRoute(unittest.TestCase):
    def setUp(self):
        os.environ.pop("SHADOW_RAW_EV_ENABLED", None)
        os.environ.pop("REPLAY_ENABLE", None)
        os.environ["PROGRESSION_PHASE_OVERRIDE"] = ""

    def tearDown(self):
        os.environ.pop("SHADOW_RAW_EV_ENABLED", None)
        os.environ.pop("PROGRESSION_PHASE_OVERRIDE", None)

    def _drive(self, client, inject=None):
        from packages.quantum.jobs.handlers import suggestions_open as so
        from packages.quantum.services import workflow_orchestrator as wo
        from packages.quantum.analytics import calibration_service as cal

        cal_blob = {
            "LONG_CALL_DEBIT_SPREAD": {
                "normal": {"ev_multiplier": 0.5, "pop_multiplier": 1.0},
            },
        }

        class _NotStale:
            blocked = False
            reason = ""
            age_seconds = 0
            stale_symbols = []

        # Clock alignment (test-env only): the orchestrator stamps cycle_date
        # from UTC; fork.py queries date.today() (process-local). On the UTC
        # production containers these are identical; on a local machine at
        # night they diverge. Shim the fork's date source to UTC so the test
        # asserts the production relationship, not the developer's timezone.
        import datetime as _dt

        class _UTCDate:
            @staticmethod
            def today():
                return _dt.datetime.now(_dt.timezone.utc).date()

        if inject:
            inject(client)

        with patch("packages.quantum.risk.staleness_gate.check_staleness_gate",
                   lambda: _NotStale()), \
             patch.object(so, "is_market_day", lambda: (True, "open")), \
             patch.object(so, "get_admin_client", lambda: client), \
             patch.object(so, "get_active_user_ids", lambda _c: [UID]), \
             patch.object(so, "ensure_default_strategy_exists",
                          lambda *a, **k: None), \
             patch.object(so, "load_strategy_config",
                          lambda *a, **k: {"version": 1}), \
             patch.object(wo, "scan_for_opportunities",
                          lambda **_k: ([_scanner_candidate()], _RejStats())), \
             patch.object(cal, "CALIBRATION_ENABLED", True), \
             patch.object(cal, "get_calibration_adjustments",
                          lambda *_a, **_k: cal_blob), \
             patch.object(wo, "CashService", _FakeCashService), \
             patch.object(wo, "RegimeEngineV3", _FakeRegimeEngine), \
             patch("packages.quantum.services.progression_service."
                   "ProgressionService.get_state",
                   lambda *_a, **_k: {"current_phase": "alpaca_paper"}), \
             patch("packages.quantum.risk.position_scope."
                   "live_routed_portfolio_ids", lambda *_a, **_k: ["pf-live"]), \
             patch("packages.quantum.observability.alerts._get_admin_supabase",
                   lambda: client), \
             patch("packages.quantum.policy_lab.config.is_policy_lab_enabled",
                   lambda: True), \
             patch.object(fork_mod, "is_policy_lab_enabled", lambda: True), \
             patch.object(fork_mod, "load_cohort_configs", _cohort_configs), \
             patch.object(fork_mod, "date", _UTCDate), \
             patch.object(fork_mod, "get_current_champion",
                          lambda *_a, **_k: "aggressive"):
            return so.run({"date": "2026-07-13", "type": "open"})

    def _seed(self, client, neutral_net_liq=10000):
        client.tables["trade_suggestions"] = []
        client.tables["paper_positions"] = []
        client.tables["policy_lab_cohorts"] = [
            {"id": "c-agg", "user_id": UID, "cohort_name": "aggressive",
             "portfolio_id": "pf-agg", "is_active": True},
            {"id": "c-neu", "user_id": UID, "cohort_name": "neutral",
             "portfolio_id": "pf-neu", "is_active": True},
        ]
        client.tables["paper_portfolios"] = [
            {"id": "pf-agg", "cash_balance": 2000, "net_liq": 2000},
            {"id": "pf-neu", "cash_balance": neutral_net_liq,
             "net_liq": neutral_net_liq},
        ]

    def test_calibration_rejection_created_by_route_then_forked(self):
        client = FakeSupabase()
        self._seed(client)
        result = self._drive(client)

        # 1. THE ORCHESTRATOR (not the fixture) persisted the calibrated
        #    rejection: NOT_EXECUTABLE / edge_below_minimum with raev=-999
        #    and BOTH bases stamped.
        rows = client.tables["trade_suggestions"]
        sources = [r for r in rows
                   if r.get("ticker") == "SOFI" and r.get("cohort_name") is None]
        import json as _json
        self.assertEqual(
            len(sources), 1,
            "rows="
            + str([(r.get("ticker"), r.get("status"), r.get("cohort_name"))
                   for r in rows])
            + " || cycle_results="
            + _json.dumps(result.get("cycle_results"), default=str)[:1200]
            + " || notes=" + _json.dumps(result.get("notes"), default=str)[:800])
        src = sources[0]
        self.assertEqual(src["status"], "NOT_EXECUTABLE")
        self.assertEqual(src["blocked_reason"], "edge_below_minimum")
        self.assertEqual(src["risk_adjusted_ev"], -999.0)
        self.assertAlmostEqual(float(src["ev_raw"]), 30.73, places=2)
        self.assertAlmostEqual(float(src["ev"]), 15.365, places=2)

        # 2. The REAL fork observed it: raw-basis NOT_EXECUTABLE clone +
        #    exactly one accepted verdict from the persisted clone.
        clones = [r for r in rows
                  if r.get("cohort_name") == "neutral"
                  and r.get("blocked_reason") == "shadow_prerejection_fork"]
        self.assertEqual(len(clones), 1)
        self.assertEqual(clones[0]["ev"], clones[0]["ev_raw"])
        self.assertEqual(clones[0]["sizing_metadata"]["ev_basis"], "raw")
        verdicts = [r for r in client.tables.get("policy_decisions", [])
                    if r.get("suggestion_id") == src["id"]
                    and r.get("decision") == "accepted"]
        self.assertEqual(len(verdicts), 1)
        self.assertEqual(verdicts[0]["features_snapshot"]["clone_suggestion_id"],
                         clones[0]["id"])

        # 3. TOP-LEVEL job truth: green when the experiment succeeded.
        from packages.quantum.jobs.runner import _classify_handler_return
        self.assertTrue(result["ok"], result.get("notes"))
        self.assertEqual(int(result["counts"]["errors"]), 0)
        self.assertEqual(_classify_handler_return(result), "succeeded")

    def test_same_route_with_verdict_failure_is_job_partial(self):
        client = FakeSupabase()
        self._seed(client)

        def inject(c):
            c.raise_when("policy_decisions", "upsert")

        result = self._drive(client, inject=inject)
        from packages.quantum.jobs.runner import _classify_handler_return
        self.assertFalse(result["ok"])
        self.assertGreaterEqual(int(result["counts"]["errors"]), 1)
        self.assertEqual(_classify_handler_return(result), "partial")

    # -----------------------------------------------------------------------
    # B17 — REAL-ROUTE UNIT PROOF: assert the values the route ACTUALLY
    # produced, computed dynamically from route artifacts + canonical
    # constants. No hardcoded 60 or 0.464892 (those were the SYNTHETIC unit
    # fixture, whose max_loss_total=60 at contracts=1; the route produces
    # max_loss_total/contracts = 720/24 = 30). Two challenger sizes.
    # -----------------------------------------------------------------------
    def _route_artifacts(self, client, result):
        rows = client.tables["trade_suggestions"]
        src = [r for r in rows
               if r.get("ticker") == "SOFI" and r.get("cohort_name") is None][0]
        clone = [r for r in rows
                 if r.get("cohort_name") == "neutral"
                 and r.get("blocked_reason") == "shadow_prerejection_fork"][0]
        return src, clone

    def test_real_route_unit_proof_two_sizes(self):
        from packages.quantum.analytics.canonical_ranker import (
            DEFAULT_FEE_PER_CONTRACT,
        )
        results = []
        for neutral_net_liq in (3000, 12000):
            client = FakeSupabase()
            self._seed(client, neutral_net_liq=neutral_net_liq)
            result = self._drive(client)
            self.assertTrue(result["ok"], result.get("notes"))
            src, clone = self._route_artifacts(client, result)

            # --- source contract-count basis (report + coherence) ---
            src_sizing_ct = int(src["sizing_metadata"]["contracts"])
            src_order_ct = int(src["order_json"]["contracts"])
            self.assertEqual(src_sizing_ct, src_order_ct,
                             "route source has a contract-count basis mismatch")
            src_mlt = float(src["sizing_metadata"]["max_loss_total"])
            per_contract_denom = round(src_mlt / src_sizing_ct, 6)

            # --- expected eligibility values from ARTIFACTS + constants ---
            ev_raw = float(src["ev_raw"])
            expected_slippage = abs(ev_raw) * 0.05
            expected_fee = DEFAULT_FEE_PER_CONTRACT * 2
            expected_net = ev_raw - expected_slippage - expected_fee
            expected_raev = round(expected_net / per_contract_denom, 6)

            self.assertAlmostEqual(clone["risk_adjusted_ev"], expected_raev,
                                   places=6)
            # NOT the synthetic 60/0.464892
            self.assertNotAlmostEqual(clone["risk_adjusted_ev"], 0.464892,
                                      places=6)
            self.assertNotEqual(per_contract_denom, 60.0)

            # clone qty + risk scaling
            clone_ct = int(clone["order_json"]["contracts"])
            self.assertEqual(clone["sizing_metadata"]["clone_contracts"], clone_ct)
            self.assertAlmostEqual(float(clone["max_loss_total"]),
                                   per_contract_denom * clone_ct, places=2)

            # source row byte-identical across runs (captured for cross-check)
            src_snapshot = {k: src[k] for k in
                            ("ev", "ev_raw", "risk_adjusted_ev", "status",
                             "blocked_reason")}
            src_snapshot["contracts"] = src_order_ct
            src_snapshot["max_loss_total"] = src_mlt

            # verdict stamps
            v = [r for r in client.tables["policy_decisions"]
                 if r.get("suggestion_id") == src["id"]
                 and r.get("decision") == "accepted"][0]
            fs = v["features_snapshot"]
            self.assertEqual(fs["eligibility_ev_unit"], "per_contract")
            self.assertEqual(fs["eligibility_contracts"], 1)
            self.assertEqual(fs["clone_contracts"], clone_ct)
            self.assertEqual(fs["eligibility_cost_basis"],
                             fork_mod._ELIGIBILITY_COST_BASIS)
            self.assertEqual(fs["raev_basis"], "raw_per_contract_normalized")
            self.assertEqual(fs["experiment_version"], fork_mod.EXPERIMENT_VERSION)
            self.assertEqual(fs["calibration_identity"], src.get("model_version"))
            # no executable suggestion; no broker table touched
            self.assertNotIn("paper_orders", client.tables)

            results.append((clone_ct, clone["risk_adjusted_ev"],
                            per_contract_denom, expected_raev, src_snapshot))

        # two sizes → different clone quantities, SAME normalized decision + raev
        c0, c1 = results
        self.assertNotEqual(c0[0], c1[0], f"clone qty must differ: {c0[0]} vs {c1[0]}")
        self.assertEqual(c0[1], c1[1])          # same normalized raev
        self.assertEqual(c0[2], c1[2])          # same per-contract denominator
        self.assertEqual(c0[4], c1[4])          # source row byte-identical


if __name__ == "__main__":
    unittest.main()
