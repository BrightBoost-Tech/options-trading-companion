"""B1/B2 one-beta bucket control + same-run reservation (P0-B, 2026-07-12).

Pure exposure math per basis (honest / legacy-premium / mixed / NULL) +
reservation accumulation, THEN the executor-integration behaviors: would-block
logged + alarm fires + entry PROCEEDS when off · armed → honest rejection stamp
· 2-candidate reservation (#2 sees #1) · ≤1 candidate byte-identical.
"""
import os
import types
import unittest
from datetime import datetime, timezone
from unittest import mock

from packages.quantum.risk import bucket_control as bkt


def _clear():
    os.environ.pop("BUCKET_CONTROL_ENFORCE", None)
    os.environ.pop("BUCKET_MAX_PCT", None)


# ── pure: bucket map + basis + reservation ──────────────────────────────────

class TestBucketMapAndBasis(unittest.TestCase):
    def test_us_equity_beta_bucket(self):
        for t in ("SPY", "DIA", "QQQ", "IWM", "qqq"):
            self.assertEqual(bkt.bucket_for(t), "us_equity_beta")

    def test_other_symbol_own_bucket(self):
        self.assertEqual(bkt.bucket_for("NFLX"), "NFLX")
        self.assertEqual(bkt.bucket_for("MARA"), "MARA")

    def test_position_risk_honest(self):
        # W3 (2026-07-12): 3-tuple (usd, legacy, is_unknown)
        v, legacy, unknown = bkt.position_risk_usd({"max_loss_total": 372.0, "cost_basis_total": 149.0})
        self.assertEqual((v, legacy, unknown), (372.0, False, False))

    def test_position_risk_legacy_premium_caveat(self):
        v, legacy, unknown = bkt.position_risk_usd({"max_loss_total": None, "cost_basis_total": 149.0})
        self.assertEqual((v, legacy, unknown), (149.0, True, False))

    def test_position_risk_null_never_fabricated(self):
        v, legacy, unknown = bkt.position_risk_usd({"max_loss_total": None, "cost_basis_total": None})
        self.assertEqual((v, unknown), (0.0, True))  # nothing to price → UNKNOWN, not a guess

    def test_candidate_risk_honest_then_premium(self):
        self.assertEqual(bkt.candidate_risk_usd({"max_loss_total": 372.0})[0], 372.0)
        prem = bkt.candidate_risk_usd({"order_json": {"limit_price": 1.49, "contracts": 1}})
        self.assertEqual(prem, (149.0, True, False))


class TestExposureMath(unittest.TestCase):
    def tearDown(self):
        _clear()

    def test_mixed_basis_sum_and_block(self):
        _clear()
        # cap = 0.25 × 2068 = 517. Open: QQQ honest 372 + IWM legacy-premium 149
        # = 521 (same us_equity_beta bucket). Candidate QQQ 372 → 893 > 517.
        opens = [
            {"symbol": "QQQ", "max_loss_total": 372.0},
            {"symbol": "IWM", "max_loss_total": None, "cost_basis_total": 149.0},
            {"symbol": "NFLX", "max_loss_total": 500.0},  # different bucket, excluded
        ]
        d = bkt.evaluate_bucket("SPY", 372.0, opens, bkt.BucketReservations(), 2068.0)
        self.assertEqual(d["bucket"], "us_equity_beta")
        self.assertEqual(d["open_exposure"], 521.0)  # 372 + 149, NFLX excluded
        self.assertTrue(d["legacy_premium_basis"])    # IWM counted at premium
        self.assertTrue(d["would_block"])
        self.assertEqual(d["cap"], 517.0)

    def test_reservation_seen_by_next_candidate(self):
        _clear()
        res = bkt.BucketReservations()
        # empty book, cand #1 = 372 < cap 517 → no block.
        d1 = bkt.evaluate_bucket("QQQ", 372.0, [], res, 2068.0)
        self.assertFalse(d1["would_block"])
        res.add("us_equity_beta", 372.0)              # #1 commits
        # cand #2 sees #1's reservation → 372 + 372 = 744 > 517 → block.
        d2 = bkt.evaluate_bucket("QQQ", 372.0, [], res, 2068.0)
        self.assertEqual(d2["reserved"], 372.0)
        self.assertTrue(d2["would_block"])

    def test_equity_unreadable_never_blocks(self):
        d = bkt.evaluate_bucket("QQQ", 9999.0, [], bkt.BucketReservations(), 0.0)
        self.assertFalse(d["would_block"])  # cap 0 → fail-safe

    def test_flag_and_pct_polarity(self):
        _clear()
        self.assertFalse(bkt.is_bucket_enforce_enabled())
        self.assertEqual(bkt.bucket_max_pct(), 0.25)
        os.environ["BUCKET_CONTROL_ENFORCE"] = "1"
        os.environ["BUCKET_MAX_PCT"] = "0.40"
        self.assertTrue(bkt.is_bucket_enforce_enabled())
        self.assertEqual(bkt.bucket_max_pct(), 0.40)
        os.environ["BUCKET_CONTROL_ENFORCE"] = "true"   # strict '=1'
        self.assertFalse(bkt.is_bucket_enforce_enabled())


# ── executor integration (drives _execute_per_cohort) ───────────────────────

_TODAY = datetime.now(timezone.utc).date().isoformat()


class _Resp:
    def __init__(self, data): self.data = data


class _SuggQuery:
    def __init__(self, rows, filters=None):
        self._rows = rows
        self._f = dict(filters or {})
    def select(self, *a, **k): return self
    def eq(self, c, v):
        f = dict(self._f); f[c] = v
        return _SuggQuery(self._rows, f)
    def order(self, *a, **k): return self
    def limit(self, n): return self
    def execute(self):
        return _Resp([r for r in self._rows if all(r.get(k) == v for k, v in self._f.items())])


class _FakeSupabase:
    def __init__(self, sugg): self._s = sugg
    def table(self, name):
        return _SuggQuery(self._s) if name == "trade_suggestions" else _SuggQuery([])


def _sugg(sid, ticker="QQQ", raev=50.0, max_loss=372.0):
    return {"id": sid, "user_id": "user-1", "ticker": ticker, "symbol": ticker,
            "cohort_name": "aggressive", "status": "pending", "cycle_date": _TODAY,
            "ev": raev, "risk_adjusted_ev": raev, "max_loss_total": max_loss,
            "order_json": {"limit_price": 1.5, "contracts": 1}}


def _run(suggestions, *, enforce, equity=2068.0):
    from packages.quantum.services.paper_autopilot_service import PaperAutopilotService
    from packages.quantum.brokers.execution_router import ExecutionMode

    svc = PaperAutopilotService.__new__(PaperAutopilotService)
    svc.client = _FakeSupabase(suggestions)
    svc.get_open_positions = lambda uid: []          # flat book
    svc.get_already_executed_suggestion_ids_today = lambda uid: set()
    svc._estimate_equity = lambda uid, pos: equity
    stamps = []
    svc._stamp_blocked_reason = lambda sid, reason, msg=None: stamps.append((sid, reason))

    cfg = types.SimpleNamespace(max_suggestions_per_day=5)
    configs = {"aggressive": cfg}
    portfolios = {"aggressive": "port-agg"}
    staged = []
    alarms = []

    env = {"BUCKET_CONTROL_ENFORCE": "1"} if enforce else {}
    with mock.patch.dict(os.environ, env, clear=False), \
         mock.patch("packages.quantum.services.reentry_cooldown.is_enabled", return_value=False), \
         mock.patch("packages.quantum.risk.utilization_gate.is_enabled", return_value=False), \
         mock.patch("packages.quantum.policy_lab.config.load_cohort_configs", return_value=configs), \
         mock.patch("packages.quantum.policy_lab.fork._get_cohort_portfolios", return_value=portfolios), \
         mock.patch("packages.quantum.paper_endpoints.get_analytics_service", return_value=mock.MagicMock()), \
         mock.patch("packages.quantum.paper_endpoints._suggestion_to_ticket", side_effect=lambda s: {"sid": s["id"]}), \
         mock.patch("packages.quantum.paper_endpoints._process_orders_for_user", return_value={"processed": 0}), \
         mock.patch("packages.quantum.brokers.execution_router.get_execution_mode", return_value=ExecutionMode.ALPACA_LIVE), \
         mock.patch("packages.quantum.observability.alerts.alert", side_effect=lambda *a, **k: alarms.append(k.get("alert_type"))), \
         mock.patch("packages.quantum.observability.alerts._get_admin_supabase", return_value=mock.MagicMock()), \
         mock.patch("packages.quantum.paper_endpoints._stage_order_internal",
                    side_effect=lambda *a, **k: staged.append(k.get("suggestion_id_override")) or "ord-x"):
        if not enforce:
            os.environ.pop("BUCKET_CONTROL_ENFORCE", None)
        svc._execute_per_cohort("user-1")
    _clear()
    return staged, stamps, alarms


class TestExecutorIntegration(unittest.TestCase):
    def test_two_candidates_off_both_proceed_alarm_fires(self):
        # cap 517; #1 372 ok, reserve; #2 744>517 would_block → PROCEEDS + alarm.
        staged, stamps, alarms = _run([_sugg("q1"), _sugg("q2")], enforce=False)
        self.assertEqual(staged, ["q1", "q2"])
        self.assertNotIn(("q2", "bucket_exposure_cap"), stamps)
        self.assertIn("bucket_exposure_would_block", alarms)

    def test_two_candidates_armed_second_rejected(self):
        staged, stamps, alarms = _run([_sugg("q1"), _sugg("q2")], enforce=True)
        self.assertEqual(staged, ["q1"])                    # #2 rejected
        self.assertIn(("q2", "bucket_exposure_cap"), stamps)

    def test_single_candidate_byte_identical(self):
        # ≤1 candidate → no reservation consulted → never blocks, either mode.
        for enforce in (False, True):
            staged, stamps, _ = _run([_sugg("solo")], enforce=enforce)
            self.assertEqual(staged, ["solo"])
            self.assertEqual([s for s in stamps if s[1] == "bucket_exposure_cap"], [])

    def test_different_buckets_no_block(self):
        # QQQ + NFLX are different buckets → neither reserves against the other.
        staged, stamps, _ = _run([_sugg("q1", "QQQ"), _sugg("n1", "NFLX")], enforce=True)
        self.assertEqual(staged, ["q1", "n1"])


if __name__ == "__main__":
    unittest.main()
