"""Lane 4B — candidate terminal disposition through THE PRODUCTION ROUTE.

Doctrine (v1.4 07-12): inject at the ORIGIN, assert at the TOP. Every test
here drives the REAL ``suggestions_open.run`` -> ``run_midday_cycle`` with
stubs only at genuine external boundaries (scanner output, calibration blob,
broker/regime reads, the hardened contract DB fake) and asserts on durable
DB rows + the top-level cycle counts — never on recorder internals.

Wired call sites proven end-to-end:
  - post-rank_and_select selection  -> attempt row (selected=true)
  - ranker verdict (edge_below_minimum) + persist outcome -> rank_blocked
    final carrying the persisted suggestion_id (ONE final, refined not
    duplicated)
  - persisted executable            -> persisted_executable final
  - H7 pre-filter ACTIVE drop       -> h7_dropped final
  - allocator drop (AAPL/IWM seam)  -> allocator_dropped final
  - unpriceable loop death          -> h7_dropped final (reason in detail)
  - marketdata quality gate HARD E4 (fatal) / E5 (skip-policy) -> h7_dropped
    final (pre-persist death; detail.reason distinguishes E4/E5), and soft
    mode does NOT drop (persisted_blocked at persist) — byte-identical on/off
  - schema-absent (migration unapplied) -> typed no-op, cycle output intact
  - writer on/off                   -> candidate outputs byte-identical
"""

import copy
import os
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from packages.quantum.policy_lab import fork as fork_mod
from packages.quantum.services.candidate_disposition import (
    TABLE,
    candidate_fingerprint,
)
from packages.quantum.tests.test_prerejection_fork_e19 import (
    FakeSupabase,
    UID,
    _cohort_configs,
)
from packages.quantum.tests.test_prerejection_full_route_e19 import (
    _FakeCashService,
    _FakeRegimeEngine,
    _RejStats,
    _scanner_candidate,
)
from packages.quantum.tests.test_candidate_disposition_writer import (
    SchemaAbsentFake,
)
from packages.quantum.services import workflow_orchestrator as _wo
from packages.quantum.services.market_data_truth_layer import (
    TruthSnapshotV4,
    TruthQuoteV4,
    TruthTimestampsV4,
    TruthQualityV4,
    TruthSourceV4,
)

def _pin_real_module(stack, name):
    """Scoped real-module pinning (the shared CI pollution-class fix — same
    pattern as ``_pin_real_module`` in test_job_origin_provenance.py on
    feat/job-origin-provenance, ExitStack form for unittest).

    Why: test_weekly_report_win_rate.py:17 permanently replaces
    ``sys.modules['packages.quantum.services.sizing_engine']`` with a
    MagicMock at COLLECTION time and never restores it. The production route
    driven here re-reads ``sys.modules`` at CALL time — the H7 wire-in in
    ``run_midday_cycle`` does ``from packages.quantum.services.sizing_engine
    import estimate_close_bp, DEFAULT_ROUND_TRIP_SAFETY_FACTOR`` inside the
    function body (workflow_orchestrator.py) — so a full-suite run hands it
    the leaked mock (CI-only ``'<=' not supported between instances of
    'MagicMock' and 'float'``), the ACTIVE H7 drop dies non-fatally, and the
    candidate falls through to the sizing loop's round_trip reason. Local
    single-file runs have no pollution and pass.

    Pin the GENUINE module into ``sys.modules`` for the drive's duration and
    restore the ambient entry afterwards — even when that ambient state is
    another suite's leak (their module-level bindings may depend on it).
    """
    import importlib
    import sys
    import types

    def _is_real(mod):
        # A genuine imported module: ModuleType with a ModuleSpec. A leaked
        # MagicMock fails isinstance; a bare types.ModuleType stub has
        # __spec__ None.
        return isinstance(mod, types.ModuleType) and getattr(
            mod, "__spec__", None
        ) is not None

    sentinel = object()
    ambient = sys.modules.get(name, sentinel)

    def _restore():
        if ambient is sentinel:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = ambient

    stack.callback(_restore)

    mod = ambient if ambient is not sentinel else None
    if not _is_real(mod):
        parent_name, _, attr = name.rpartition(".")
        parent = sys.modules.get(parent_name)
        cand = getattr(parent, attr, None) if parent is not None else None
        if _is_real(cand):
            mod = cand
        else:
            sys.modules.pop(name, None)
            mod = importlib.import_module(name)
    sys.modules[name] = mod
    return mod


# The ×0.5 calibration blob that pushes SOFI raw ev 30.73 below
# MIN_EDGE_AFTER_COSTS at the REAL ranker -> raev -999 (the 07-13 exhibit).
CAL_BLOB_HALF = {
    "LONG_CALL_DEBIT_SPREAD": {
        "normal": {"ev_multiplier": 0.5, "pop_multiplier": 1.0},
    },
}


def _second_candidate(**over):
    """A second, structurally-distinct candidate (different strikes)."""
    c = copy.deepcopy(_scanner_candidate())
    c["legs"][0]["symbol"] = "SOFI260821C00027000"
    c["legs"][0]["strike"] = 27.0
    c["legs"][1]["symbol"] = "SOFI260821C00029000"
    c["legs"][1]["strike"] = 29.0
    c.update(over)
    return c


def _executable_candidate():
    """A candidate whose REAL ranker math clears MIN_EDGE_AFTER_COSTS at the
    contract count the REAL sizing produces: entry $3.00 -> max_loss $300 ->
    few contracts -> round-trip fees stay far below ev $100."""
    c = _second_candidate()
    c["suggested_entry"] = 3.00
    c["ev"] = 100.0
    c["max_loss_per_contract"] = 300.0
    return c


class _RouteBase(unittest.TestCase):
    def setUp(self):
        for var in ("SHADOW_RAW_EV_ENABLED", "REPLAY_ENABLE",
                    "H7_PREFILTER_ENABLED"):
            os.environ.pop(var, None)
        os.environ["PROGRESSION_PHASE_OVERRIDE"] = ""

    def tearDown(self):
        for var in ("SHADOW_RAW_EV_ENABLED", "H7_PREFILTER_ENABLED",
                    "PROGRESSION_PHASE_OVERRIDE"):
            os.environ.pop(var, None)

    def _seed(self, client):
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
            {"id": "pf-neu", "cash_balance": 10000, "net_liq": 10000},
        ]

    def _drive(self, client, cands, cal_blob=None, extra_patches=()):
        from packages.quantum.jobs.handlers import suggestions_open as so
        from packages.quantum.services import workflow_orchestrator as wo
        from packages.quantum.analytics import calibration_service as cal

        class _NotStale:
            blocked = False
            reason = ""
            age_seconds = 0
            stale_symbols = []

        import datetime as _dt

        class _UTCDate:
            @staticmethod
            def today():
                return _dt.datetime.now(_dt.timezone.utc).date()

        blob = cal_blob if cal_blob is not None else {}
        with ExitStack() as stack:
            # The route's call-time ``from ...sizing_engine import`` must see
            # the real module, not test_weekly_report_win_rate.py's leaked
            # collection-time MagicMock (see _pin_real_module).
            _pin_real_module(
                stack, "packages.quantum.services.sizing_engine")
            for p in (
                patch("packages.quantum.risk.staleness_gate."
                      "check_staleness_gate", lambda: _NotStale()),
                patch.object(so, "is_market_day", lambda: (True, "open")),
                patch.object(so, "get_admin_client", lambda: client),
                patch.object(so, "get_active_user_ids", lambda _c: [UID]),
                patch.object(so, "ensure_default_strategy_exists",
                             lambda *a, **k: None),
                patch.object(so, "load_strategy_config",
                             lambda *a, **k: {"version": 1}),
                patch.object(wo, "scan_for_opportunities",
                             lambda **_k: (copy.deepcopy(cands), _RejStats())),
                patch.object(cal, "CALIBRATION_ENABLED", True),
                patch.object(cal, "get_calibration_adjustments",
                             lambda *_a, **_k: blob),
                patch.object(wo, "CashService", _FakeCashService),
                patch.object(wo, "RegimeEngineV3", _FakeRegimeEngine),
                patch("packages.quantum.services.progression_service."
                      "ProgressionService.get_state",
                      lambda *_a, **_k: {"current_phase": "alpaca_paper"}),
                patch("packages.quantum.risk.position_scope."
                      "live_routed_portfolio_ids", lambda *_a, **_k: ["pf-live"]),
                patch("packages.quantum.observability.alerts."
                      "_get_admin_supabase", lambda: client),
                patch("packages.quantum.policy_lab.config."
                      "is_policy_lab_enabled", lambda: True),
                patch.object(fork_mod, "is_policy_lab_enabled", lambda: True),
                patch.object(fork_mod, "load_cohort_configs", _cohort_configs),
                patch.object(fork_mod, "date", _UTCDate),
                patch.object(fork_mod, "get_current_champion",
                             lambda *_a, **_k: "aggressive"),
                *extra_patches,
            ):
                stack.enter_context(p)
            return so.run({"date": "2026-07-17", "type": "open"})

    # -- shared helpers ----------------------------------------------------
    def _ctd_rows(self, client):
        return client.tables.get(TABLE, [])

    def _finals(self, client):
        return [r for r in self._ctd_rows(client) if r.get("is_final")]

    def _cycle_counts(self, result):
        """The midday cycle's counts dict, wherever the handler nested it."""
        found = []

        def walk(node):
            if isinstance(node, dict):
                if "candidate_disposition" in node:
                    found.append(node)
                for v in node.values():
                    walk(v)
            elif isinstance(node, (list, tuple)):
                for v in node:
                    walk(v)

        walk(result)
        self.assertTrue(found, f"no counts.candidate_disposition in {result}")
        return found[0]

    def _assert_one_final_per_identity(self, client):
        seen = {}
        for r in self._finals(client):
            key = (r["cycle_id"], r["candidate_fingerprint"])
            self.assertNotIn(key, seen,
                             f"two finals for one identity: {key}")
            seen[key] = r
        return seen


class TestRankBlockedAndPersistSeams(_RouteBase):
    def test_calibrated_rejection_gets_one_rank_blocked_final(self):
        client = FakeSupabase()
        self._seed(client)
        cand = _scanner_candidate()
        expected_fp = candidate_fingerprint(cand)

        result = self._drive(client, [cand], cal_blob=CAL_BLOB_HALF)
        self.assertTrue(result["ok"], result.get("notes"))

        # Selection seam: durable attempt row, selected=true.
        rows = self._ctd_rows(client)
        self.assertTrue(rows, "no candidate_terminal_dispositions rows")
        self.assertTrue(all(r["selected"] for r in rows))
        self.assertEqual({r["candidate_fingerprint"] for r in rows},
                         {expected_fp})

        # Exactly ONE final: rank_blocked, refined with the persisted
        # suggestion_id at the persist seam (not a second final).
        finals = self._finals(client)
        self.assertEqual(len(finals), 1)
        final = finals[0]
        self.assertEqual(final["disposition"], "rank_blocked")
        self.assertEqual(final["attempt"], 1)
        self.assertEqual(final["detail"]["reason"], "edge_below_minimum")
        self.assertEqual(final["detail"]["risk_adjusted_ev"], -999.0)
        self.assertEqual(final["detail"]["status"], "NOT_EXECUTABLE")
        self.assertIsNotNone(final.get("code_sha"))

        # Identity joins the persisted row: fingerprint == the row's
        # legs_fingerprint AND suggestion_id == the row's id.
        src = [r for r in client.tables["trade_suggestions"]
               if r.get("ticker") == "SOFI" and r.get("cohort_name") is None][0]
        self.assertEqual(final["candidate_fingerprint"],
                         src["legs_fingerprint"])
        self.assertEqual(final["suggestion_id"], src["id"])

        # Cycle-result telemetry.
        counts = self._cycle_counts(result)
        ctd = counts["candidate_disposition"]
        self.assertFalse(ctd["table_missing"])
        self.assertEqual(ctd["attempts_recorded"], 1)
        self.assertGreaterEqual(ctd["finals_recorded"], 1)
        self.assertEqual(ctd["write_failures"], 0)
        self.assertEqual(ctd["table_missing_noops"], 0)

    def test_uncalibrated_executable_gets_persisted_executable_final(self):
        client = FakeSupabase()
        self._seed(client)
        cand = _executable_candidate()

        result = self._drive(client, [cand], cal_blob=None)
        self.assertTrue(result["ok"], result.get("notes"))

        finals = self._assert_one_final_per_identity(client)
        ((_, final),) = finals.items()
        self.assertEqual(final["disposition"], "persisted_executable")
        self.assertEqual(final["detail"]["status"], "pending")
        self.assertTrue(final["detail"]["is_new"])

        # The final joins the PERSISTED row by suggestion_id (the champion
        # fork stamps cohort_name onto pending source rows afterwards — the
        # id link survives that mutation).
        src = [r for r in client.tables["trade_suggestions"]
               if r.get("id") == final["suggestion_id"]][0]
        self.assertEqual(src["status"], "pending")
        self.assertEqual(final["candidate_fingerprint"],
                         src["legs_fingerprint"])


class TestH7AndAllocatorSeams(_RouteBase):
    def test_h7_active_prefilter_drop_is_a_durable_final(self):
        os.environ["H7_PREFILTER_ENABLED"] = "true"
        client = FakeSupabase()
        self._seed(client)
        # Round-trip requirement far above the $2,000 OBP -> ACTIVE drop.
        cand = _scanner_candidate()
        cand["max_loss_per_contract"] = 50000.0

        result = self._drive(client, [cand], cal_blob=None)
        self.assertTrue(result["ok"], result.get("notes"))

        # Nothing persisted…
        self.assertEqual(
            [r for r in client.tables.get("trade_suggestions", [])
             if r.get("cohort_name") is None], [])
        # …but the fate IS durable (the pre-Lane-4B gap).
        finals = self._finals(client)
        self.assertEqual(len(finals), 1)
        self.assertEqual(finals[0]["disposition"], "h7_dropped")
        self.assertEqual(finals[0]["detail"]["reason"], "h7_prefilter")
        # Typed subreason: the prefilter is a round-trip BP check.
        self.assertEqual(finals[0]["detail"]["h7_subreason"], "roundtrip_bp")
        self.assertEqual(finals[0]["detail"]["available_bp"], 2000.0)

        ctd = self._cycle_counts(result)["candidate_disposition"]
        self.assertEqual(ctd["attempts_recorded"], 1)
        self.assertEqual(ctd["finals_recorded"], 1)

    def test_allocator_drop_is_a_durable_final(self):
        client = FakeSupabase()
        self._seed(client)
        cand = _scanner_candidate()

        # Origin injection at the allocator's documented output contract:
        # [] is its real envelope-exhausted shape (portfolio_allocator
        # docstring) — the exact AAPL/IWM class where selected candidates
        # vanished with no durable fate.
        result = self._drive(
            client, [cand], cal_blob=None,
            extra_patches=(
                patch("packages.quantum.services.portfolio_allocator."
                      "PortfolioAllocator.allocate",
                      lambda self, **kw: []),
            ),
        )
        self.assertTrue(result["ok"], result.get("notes"))

        self.assertEqual(
            [r for r in client.tables.get("trade_suggestions", [])
             if r.get("cohort_name") is None], [])
        finals = self._finals(client)
        self.assertEqual(len(finals), 1)
        self.assertEqual(finals[0]["disposition"], "allocator_dropped")
        self.assertEqual(finals[0]["detail"]["reason"],
                         "not_in_allocator_output")
        self.assertEqual(finals[0]["candidate_fingerprint"],
                         candidate_fingerprint(cand))


class TestLoopDeathSeam(_RouteBase):
    def test_unpriceable_selected_candidate_gets_final(self):
        client = FakeSupabase()
        self._seed(client)
        cand = _scanner_candidate()
        cand["suggested_entry"] = 0.0  # unpriceable at the sizing loop

        result = self._drive(client, [cand], cal_blob=None)
        self.assertTrue(result["ok"], result.get("notes"))

        finals = self._finals(client)
        self.assertEqual(len(finals), 1)
        self.assertEqual(finals[0]["disposition"], "h7_dropped")
        self.assertEqual(finals[0]["detail"]["reason"],
                         "unpriceable_candidate")
        # Typed subreason: a data/priceability death sits in the quality_gate
        # family (never reached sizing), NOT stamped the marketdata-gate
        # sizing_outcome (it did not traverse the gate).
        self.assertEqual(finals[0]["detail"]["h7_subreason"], "quality_gate")
        self.assertNotIn("sizing_outcome", finals[0]["detail"])
        self.assertTrue(finals[0]["selected"])

    def test_risk_budget_exhausted_gets_risk_budget_subreason(self):
        """E2 (:~3502): final_risk_dollars<=0 -> h7_dropped + 'risk_budget'.

        Origin injection at the risk-budget enforcement seam: the REAL
        clamp_risk_budget (the function that caps a candidate's per-trade
        allocation against the remaining global envelope) zeroes it, exactly
        as an exhausted envelope would. remaining_global stays positive (the
        real engine, $2,000 book) so the CYCLE-level skip never trips — the
        per-candidate E2 branch does, and drives the REAL record_final."""
        client = FakeSupabase()
        self._seed(client)
        cand = _scanner_candidate()  # priceable, sizes fine absent the clamp

        result = self._drive(
            client, [cand], cal_blob=None,
            extra_patches=(
                patch.object(_wo, "clamp_risk_budget",
                             lambda *_a, **_k: 0.0),
            ),
        )
        self.assertTrue(result["ok"], result.get("notes"))

        # Nothing persisted; the fate is durable.
        self.assertEqual(
            [r for r in client.tables.get("trade_suggestions", [])
             if r.get("cohort_name") is None], [])
        finals = self._finals(client)
        self.assertEqual(len(finals), 1)
        self.assertEqual(finals[0]["disposition"], "h7_dropped")
        self.assertEqual(finals[0]["detail"]["reason"],
                         "risk_budget_exhausted")
        self.assertEqual(finals[0]["detail"]["h7_subreason"], "risk_budget")
        self.assertTrue(finals[0]["selected"])
        self.assertEqual(finals[0]["candidate_fingerprint"],
                         candidate_fingerprint(cand))

    def test_sized_to_zero_gets_sizing_zero_subreason(self):
        """E3 (:~4064): the sizing engine returns contracts==0 (the dominant
        selected-then-vanished death) -> h7_dropped + 'sizing_zero'.

        Natural origin: a max_loss far above the $2,000 OBP. The H7 prefilter
        is SHADOW by default (records nothing), so this h7-fit death surfaces
        HERE as sized_to_zero — exactly the packet's Monday-evidence
        prediction. MIDDAY_TEST_MODE pinned False so the contracts==0 stands
        (test mode would override it to 1)."""
        client = FakeSupabase()
        self._seed(client)
        cand = _scanner_candidate()
        cand["max_loss_per_contract"] = 50000.0  # unaffordable -> contracts=0
        expected_fp = candidate_fingerprint(cand)

        result = self._drive(
            client, [cand], cal_blob=None,
            extra_patches=(
                patch.object(_wo, "MIDDAY_TEST_MODE", False),
            ),
        )
        self.assertTrue(result["ok"], result.get("notes"))

        self.assertEqual(
            [r for r in client.tables.get("trade_suggestions", [])
             if r.get("cohort_name") is None], [])
        finals = self._finals(client)
        self.assertEqual(len(finals), 1)
        final = finals[0]
        self.assertEqual(final["disposition"], "h7_dropped")
        self.assertEqual(final["detail"]["h7_subreason"], "sizing_zero")
        # The 6 root causes stay in detail.reason verbatim (here: the
        # round-trip verdict); we assert it is preserved, not its exact text.
        self.assertTrue(final["detail"].get("reason"))
        self.assertEqual(final["detail"]["available_bp"], 2000.0)
        self.assertEqual(final["candidate_fingerprint"], expected_fp)


class TestSchemaAbsentRoute(_RouteBase):
    def test_missing_table_is_typed_noop_and_cycle_output_intact(self):
        client = SchemaAbsentFake()
        self._seed(client)
        cand = _scanner_candidate()

        result = self._drive(client, [cand], cal_blob=CAL_BLOB_HALF)
        self.assertTrue(result["ok"], result.get("notes"))

        # Primary work unaffected: the calibrated rejection still persisted.
        src = [r for r in client.tables["trade_suggestions"]
               if r.get("ticker") == "SOFI" and r.get("cohort_name") is None][0]
        self.assertEqual(src["status"], "NOT_EXECUTABLE")
        self.assertEqual(src["blocked_reason"], "edge_below_minimum")

        # Typed no-op, visible in the cycle counts; no phantom table rows.
        self.assertNotIn(TABLE, client.tables)
        ctd = self._cycle_counts(result)["candidate_disposition"]
        self.assertTrue(ctd["table_missing"])
        self.assertGreaterEqual(ctd["table_missing_noops"], 1)
        self.assertEqual(ctd["write_failures"], 0)
        self.assertEqual(ctd["attempts_recorded"], 0)
        self.assertEqual(ctd["finals_recorded"], 0)


class TestNoDecisionDelta(_RouteBase):
    """Observe-only proof: candidate outputs byte-identical with the writer
    recording (table present), typed-no-oping (table absent), and fully
    disabled (recorder construction fails)."""

    @staticmethod
    def _projection(client):
        rows = client.tables.get("trade_suggestions", [])
        return sorted(
            (
                (
                    r.get("ticker"), r.get("strategy"), r.get("window"),
                    r.get("cohort_name"), r.get("status"),
                    r.get("blocked_reason"), r.get("ev"), r.get("ev_raw"),
                    r.get("risk_adjusted_ev"), r.get("legs_fingerprint"),
                    str(r.get("order_json", {}).get("legs")),
                    r.get("order_json", {}).get("contracts"),
                )
                for r in rows
            ),
            key=lambda t: tuple(str(x) for x in t),
        )

    def test_outputs_identical_writer_on_off(self):
        projections = {}

        # (a) writer ON (table present)
        client_on = FakeSupabase()
        self._seed(client_on)
        res_on = self._drive(client_on, [_scanner_candidate()],
                             cal_blob=CAL_BLOB_HALF)
        self.assertTrue(res_on["ok"], res_on.get("notes"))
        projections["on"] = self._projection(client_on)
        self.assertTrue(self._ctd_rows(client_on))  # writer really wrote

        # (b) table absent (typed no-op)
        client_absent = SchemaAbsentFake()
        self._seed(client_absent)
        res_absent = self._drive(client_absent, [_scanner_candidate()],
                                 cal_blob=CAL_BLOB_HALF)
        self.assertTrue(res_absent["ok"], res_absent.get("notes"))
        projections["absent"] = self._projection(client_absent)

        # (c) recorder construction fails -> _ctd None (writer OFF)
        client_off = FakeSupabase()
        self._seed(client_off)
        res_off = self._drive(
            client_off, [_scanner_candidate()], cal_blob=CAL_BLOB_HALF,
            extra_patches=(
                patch("packages.quantum.services.candidate_disposition."
                      "CandidateDispositionRecorder.create",
                      side_effect=RuntimeError("writer forced off")),
            ),
        )
        self.assertTrue(res_off["ok"], res_off.get("notes"))
        projections["off"] = self._projection(client_off)
        self.assertEqual(self._ctd_rows(client_off), [])

        self.assertEqual(projections["on"], projections["absent"])
        self.assertEqual(projections["on"], projections["off"])
        # And the decision itself is the known exhibit in all three runs.
        self.assertTrue(any(p[4] == "NOT_EXECUTABLE"
                            for p in projections["on"]))


class TestMultiCandidateInvariant(_RouteBase):
    def test_two_identities_each_exactly_one_final(self):
        client = FakeSupabase()
        self._seed(client)
        a = _scanner_candidate()
        b = _second_candidate(score=60.0)

        result = self._drive(client, [a, b], cal_blob=CAL_BLOB_HALF)
        self.assertTrue(result["ok"], result.get("notes"))

        finals = self._assert_one_final_per_identity(client)
        selected_fps = {r["candidate_fingerprint"]
                        for r in self._ctd_rows(client)}
        final_fps = {fp for (_cycle, fp) in finals.keys()}
        # EVERY selected identity reached exactly one final disposition.
        self.assertEqual(selected_fps, final_fps)
        self.assertGreaterEqual(len(final_fps), 1)
        for r in finals.values():
            self.assertIn(r["disposition"],
                          {"rank_blocked", "h7_dropped",
                           "persisted_blocked", "persisted_executable",
                           "allocator_dropped"})


# ---------------------------------------------------------------------------
# Marketdata quality-gate HARD-mode seam (E4 fatal / E5 skip-policy).
#
# Origin injection at the DEEPEST constructable layer: the marketdata feed
# (MarketDataTruthLayer.snapshot_many_v4) returns the bad data, and the REAL
# gate functions (check_snapshots_executable + format_quality_gate_result +
# classify_snapshot_quality) do the classifying — no intermediate gate
# function is mocked. MIDDAY_TRUST_SCANNER_QUOTES=0 is the real production
# config that makes the snapshot gate run (scanner quotes not trusted).
#   - E4: empty snapshots -> every leg FAIL_MISSING_SNAPSHOT (fatal).
#   - E5: present-but-low-quality snapshots (score<min, not stale) -> WARN
#         (non-fatal) + policy=skip.
# Assertion is at the TOP: durable DB rows + top-level cycle counts.
# ---------------------------------------------------------------------------
import time as _time


def _empty_v4(self, symbols, raw_snapshots=None):
    """E4 origin: the feed returns nothing -> real gate sees missing/fatal."""
    return {}


def _low_quality_snap(sym):
    """A genuine TruthSnapshotV4 the REAL classifier grades WARN_LOW_QUALITY:
    present + fresh (not stale) + no fatal issue code, but quality_score below
    the min threshold -> non-executable WARNING, never fatal."""
    now_ms = int(_time.time() * 1000)
    return TruthSnapshotV4(
        symbol_canonical=sym,
        quote=TruthQuoteV4(bid=0.55, ask=0.65, mid=0.60),
        timestamps=TruthTimestampsV4(source_ts=now_ms, received_ts=now_ms),
        quality=TruthQualityV4(
            quality_score=50, issues=["low_quality"],
            is_stale=False, freshness_ms=100,
        ),
        source=TruthSourceV4(),
    )


def _low_quality_v4(self, symbols, raw_snapshots=None):
    """E5 origin: present-but-low-quality snapshots for every requested leg."""
    return {s: _low_quality_snap(s) for s in symbols}


def _gate_env(**over):
    """Env patch that makes the snapshot gate RUN (scanner quotes untrusted).
    Individual tests layer mode/policy on top."""
    base = {"MIDDAY_TRUST_SCANNER_QUOTES": "0",
            "MARKETDATA_MIN_QUALITY_SCORE": "60"}
    base.update(over)
    return patch.dict(os.environ, base, clear=False)


class TestQualityGateHardModeSeam(_RouteBase):
    """The E4/E5 invariant hole: a SELECTED candidate that the marketdata
    quality gate drops in HARD mode must still reach EXACTLY ONE final
    disposition (it used to `continue` with no final)."""

    def test_e4_fatal_hard_mode_gets_one_h7_dropped_final(self):
        client = FakeSupabase()
        self._seed(client)
        cand = _executable_candidate()  # clears sizing -> reaches the gate
        expected_fp = candidate_fingerprint(cand)

        result = self._drive(
            client, [cand], cal_blob=None,
            extra_patches=(
                _gate_env(MIDDAY_QUALITY_GATE_MODE="hard"),
                patch.object(_wo.MarketDataTruthLayer, "snapshot_many",
                             lambda self, *a, **k: {}),
                patch.object(_wo.MarketDataTruthLayer, "snapshot_many_v4",
                             _empty_v4),
            ),
        )
        self.assertTrue(result["ok"], result.get("notes"))

        # HARD mode drops it BEFORE persist -> nothing persisted.
        self.assertEqual(
            [r for r in client.tables.get("trade_suggestions", [])
             if r.get("cohort_name") is None], [])

        # …but the fate is durable: EXACTLY ONE final (the invariant hole).
        finals = self._finals(client)
        self.assertEqual(len(finals), 1)
        final = finals[0]
        self.assertEqual(final["disposition"], "h7_dropped")
        self.assertEqual(final["detail"]["reason"], "quality_gate_e4_fatal")
        # Typed subreason: the marketdata quality-gate family.
        self.assertEqual(final["detail"]["h7_subreason"], "quality_gate")
        # Typed discriminator: excludes marketdata deaths from the overloaded
        # h7_dropped bucket without reason-string parsing (C2 pkt Option-A).
        self.assertEqual(final["detail"]["sizing_outcome"],
                         "marketdata_quality_gate")
        self.assertEqual(final["detail"]["effective_action"], "skip_fatal")
        self.assertEqual(final["detail"]["quality_gate_mode"], "hard")
        self.assertGreaterEqual(final["detail"]["fatal_count"], 1)
        self.assertTrue(final["selected"])
        self.assertEqual(final["candidate_fingerprint"], expected_fp)

        ctd = self._cycle_counts(result)["candidate_disposition"]
        self.assertFalse(ctd["table_missing"])
        self.assertEqual(ctd["attempts_recorded"], 1)
        self.assertEqual(ctd["finals_recorded"], 1)
        self.assertEqual(ctd["write_failures"], 0)

    def test_e5_skip_policy_hard_mode_gets_one_h7_dropped_final(self):
        client = FakeSupabase()
        self._seed(client)
        cand = _executable_candidate()
        expected_fp = candidate_fingerprint(cand)

        result = self._drive(
            client, [cand], cal_blob=None,
            extra_patches=(
                _gate_env(MIDDAY_QUALITY_GATE_MODE="hard",
                          MARKETDATA_QUALITY_POLICY="skip"),
                patch.object(_wo.MarketDataTruthLayer, "snapshot_many",
                             lambda self, *a, **k: {}),
                patch.object(_wo.MarketDataTruthLayer, "snapshot_many_v4",
                             _low_quality_v4),
            ),
        )
        self.assertTrue(result["ok"], result.get("notes"))

        self.assertEqual(
            [r for r in client.tables.get("trade_suggestions", [])
             if r.get("cohort_name") is None], [])

        finals = self._finals(client)
        self.assertEqual(len(finals), 1)
        final = finals[0]
        self.assertEqual(final["disposition"], "h7_dropped")
        self.assertEqual(final["detail"]["reason"],
                         "quality_gate_e5_skip_policy")
        self.assertEqual(final["detail"]["h7_subreason"], "quality_gate")
        self.assertEqual(final["detail"]["sizing_outcome"],
                         "marketdata_quality_gate")
        self.assertEqual(final["detail"]["effective_action"], "skip_policy")
        self.assertEqual(final["detail"]["policy"], "skip")
        # E5 is the NON-fatal warning branch: warnings present, zero fatals.
        self.assertEqual(final["detail"]["fatal_count"], 0)
        self.assertGreaterEqual(final["detail"]["warning_count"], 1)
        self.assertEqual(final["candidate_fingerprint"], expected_fp)

        ctd = self._cycle_counts(result)["candidate_disposition"]
        self.assertEqual(ctd["attempts_recorded"], 1)
        self.assertEqual(ctd["finals_recorded"], 1)
        self.assertEqual(ctd["write_failures"], 0)

    def test_no_duplicate_final_across_gate_and_persist(self):
        """Belt-and-suspenders: the gate drop is the candidate's ONLY final —
        the persist seam is never reached, so no second final can appear."""
        client = FakeSupabase()
        self._seed(client)
        result = self._drive(
            client, [_executable_candidate()], cal_blob=None,
            extra_patches=(
                _gate_env(MIDDAY_QUALITY_GATE_MODE="hard"),
                patch.object(_wo.MarketDataTruthLayer, "snapshot_many",
                             lambda self, *a, **k: {}),
                patch.object(_wo.MarketDataTruthLayer, "snapshot_many_v4",
                             _empty_v4),
            ),
        )
        self.assertTrue(result["ok"], result.get("notes"))
        self._assert_one_final_per_identity(client)  # raises on a duplicate
        finals = self._finals(client)
        self.assertEqual(len(finals), 1)
        self.assertEqual(finals[0]["detail"]["sizing_outcome"],
                         "marketdata_quality_gate")


class TestQualityGateSoftModeUnchanged(_RouteBase):
    """DEFAULT (soft) mode must be byte-identical to pre-fix: the gate does
    NOT drop in soft mode (the candidate persists NOT_EXECUTABLE and earns the
    pre-existing persisted_blocked at the persist seam), and the added
    hard-mode records are observe-only (writer on/off -> identical persisted
    output)."""

    @staticmethod
    def _projection(client):
        rows = client.tables.get("trade_suggestions", [])
        return sorted(
            (
                (
                    r.get("ticker"), r.get("strategy"), r.get("window"),
                    r.get("cohort_name"), r.get("status"),
                    r.get("blocked_reason"),
                    str(r.get("order_json", {}).get("legs")),
                    r.get("order_json", {}).get("contracts"),
                )
                for r in rows
            ),
            key=lambda t: tuple(str(x) for x in t),
        )

    def _soft_patches(self, snap_v4):
        return (
            _gate_env(MARKETDATA_QUALITY_POLICY="skip"),  # mode unset -> soft
            patch.object(_wo.MarketDataTruthLayer, "snapshot_many",
                         lambda self, *a, **k: {}),
            patch.object(_wo.MarketDataTruthLayer, "snapshot_many_v4",
                         snap_v4),
        )

    def test_soft_mode_does_not_drop_and_earns_persisted_blocked(self):
        client = FakeSupabase()
        self._seed(client)
        result = self._drive(
            client, [_executable_candidate()], cal_blob=None,
            extra_patches=self._soft_patches(_low_quality_v4),
        )
        self.assertTrue(result["ok"], result.get("notes"))

        # SOFT mode PERSISTS the candidate (does NOT drop) as NOT_EXECUTABLE.
        src = [r for r in client.tables["trade_suggestions"]
               if r.get("ticker") == "SOFI" and r.get("cohort_name") is None]
        self.assertEqual(len(src), 1)
        self.assertEqual(src[0]["status"], "NOT_EXECUTABLE")
        self.assertEqual(src[0]["blocked_reason"], "marketdata_quality_gate")

        # The disposition is the PRE-EXISTING persist-seam value, unchanged by
        # this fix (soft mode never enters the new hard-mode branch).
        finals = self._finals(client)
        self.assertEqual(len(finals), 1)
        self.assertEqual(finals[0]["disposition"], "persisted_blocked")

    def test_soft_mode_output_byte_identical_writer_on_off(self):
        # (a) writer ON (table present)
        client_on = FakeSupabase()
        self._seed(client_on)
        res_on = self._drive(
            client_on, [_executable_candidate()], cal_blob=None,
            extra_patches=self._soft_patches(_low_quality_v4))
        self.assertTrue(res_on["ok"], res_on.get("notes"))
        self.assertTrue(self._ctd_rows(client_on))  # writer really wrote
        proj_on = self._projection(client_on)

        # (b) writer OFF (recorder construction forced to fail -> _ctd None)
        client_off = FakeSupabase()
        self._seed(client_off)
        res_off = self._drive(
            client_off, [_executable_candidate()], cal_blob=None,
            extra_patches=self._soft_patches(_low_quality_v4) + (
                patch("packages.quantum.services.candidate_disposition."
                      "CandidateDispositionRecorder.create",
                      side_effect=RuntimeError("writer forced off")),
            ),
        )
        self.assertTrue(res_off["ok"], res_off.get("notes"))
        self.assertEqual(self._ctd_rows(client_off), [])

        # The persisted decision output is byte-identical with the observe-only
        # writer recording vs fully disabled -> the E4/E5 fix is inert in soft
        # mode.
        self.assertEqual(proj_on, self._projection(client_off))
        self.assertTrue(any(p[4] == "NOT_EXECUTABLE" for p in proj_on))


if __name__ == "__main__":
    unittest.main()
