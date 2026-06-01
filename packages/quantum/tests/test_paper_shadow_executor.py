"""Paper-shadow executor (Phase 1b core) — isolation + lifecycle + geometry.

Load-bearing: every executor order goes through ONE account-isolated
choke-point that can only reach the paper account; the own-fill lifecycle
reuses core functions; the geometry policy is correct. Flag OFF → the submit
path refuses. All unit-level, mocked broker.
"""

import os
import unittest
from pathlib import Path
from unittest import mock

from packages.quantum.services import paper_shadow_executor as ex
from packages.quantum.services import paper_shadow_isolation as iso

REPO_ROOT = Path(__file__).resolve().parent.parent


class _Resp:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    def __init__(self, rows, store=None, table=None):
        self._rows = list(rows)
        self._store = store
        self._table = table

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        return _FakeQuery([r for r in self._rows if r.get(col) == val], self._store, self._table)

    def limit(self, n):
        return _FakeQuery(self._rows[:n], self._store, self._table)

    def insert(self, payload):
        self._store[self._table] = self._store.get(self._table, []) + [payload]
        return _FakeQuery([payload], self._store, self._table)

    def execute(self):
        return _Resp(list(self._rows))


class _FakeSupabase:
    def __init__(self, tables):
        self._tables = tables

    def table(self, name):
        return _FakeQuery(self._tables.get(name, []), self._tables, name)


_PAPER_ENV = {"ALPACA_PAPER_API_KEY": "PK", "ALPACA_PAPER_SECRET_KEY": "SK"}


# ═════════════════════════════════════════════════════════════════════
# Account isolation — the choke-point can only reach the paper account
# ═════════════════════════════════════════════════════════════════════
class TestGuardedPaperSubmitIsolation(unittest.TestCase):
    def _fake_client(self, account):
        c = mock.MagicMock()
        c.get_account_number.return_value = account
        return c

    def test_refuses_when_flag_off(self):
        with mock.patch.dict(os.environ, {iso.FLAG_ENV: "0"}, clear=True):
            with self.assertRaises(ex.PaperShadowExecutorDisabled):
                ex.guarded_paper_submit(mock.MagicMock(), {"id": "o1"}, "U")

    def test_fails_closed_without_paper_creds(self):
        # Flag on, but no dedicated paper creds → build_paper_client fails closed.
        with mock.patch.dict(os.environ, {iso.FLAG_ENV: "1"}, clear=True):
            with self.assertRaises(iso.PaperShadowConfigError):
                ex.guarded_paper_submit(mock.MagicMock(), {"id": "o1"}, "U")

    def test_submits_via_dedicated_client_on_paper_account(self):
        fake_client = self._fake_client("PA3I8CYLXBOS")
        env = {iso.FLAG_ENV: "1", **_PAPER_ENV}
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(ex, "build_paper_client", return_value=fake_client), \
             mock.patch("packages.quantum.brokers.alpaca_order_handler.submit_and_track") as sat, \
             mock.patch("packages.quantum.brokers.alpaca_client.get_alpaca_client",
                        side_effect=AssertionError("global live client must NOT be used")):
            sat.return_value = {"status": "submitted"}
            out = ex.guarded_paper_submit(mock.MagicMock(), {"id": "o1"}, "U")
        sat.assert_called_once()
        # submit_and_track(client, supabase, order, user) — the dedicated client.
        self.assertIs(sat.call_args[0][0], fake_client)
        self.assertEqual(out["status"], "submitted")

    def test_aborts_on_live_account_no_order(self):
        fake_client = self._fake_client("211900084")  # LIVE
        env = {iso.FLAG_ENV: "1", **_PAPER_ENV}
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(ex, "build_paper_client", return_value=fake_client), \
             mock.patch("packages.quantum.brokers.alpaca_order_handler.submit_and_track") as sat:
            with self.assertRaises(iso.PaperShadowAccountMismatch):
                ex.guarded_paper_submit(mock.MagicMock(), {"id": "o1"}, "U")
        sat.assert_not_called()  # never submitted — no order to live


# ═════════════════════════════════════════════════════════════════════
# Own-fill lifecycle — reuse core (H13), never the live processor
# ═════════════════════════════════════════════════════════════════════
class TestOwnFillLifecycleReusesCore(unittest.TestCase):
    def test_commit_open_fill_reuses_repair_primitive(self):
        order = {"id": "o1", "user_id": "U"}
        portfolio = {"id": "port-shadow"}
        with mock.patch("packages.quantum.paper_endpoints._repair_filled_order_commit") as repair, \
             mock.patch("packages.quantum.services.analytics_service.AnalyticsService") as Analytics:
            repair.return_value = {"repaired": True, "position_id": "pos1"}
            out = ex.commit_open_fill(mock.MagicMock(), order, portfolio)
        repair.assert_called_once()
        args = repair.call_args[0]
        self.assertEqual(args[2], "U")        # user_id
        self.assertIs(args[3], order)         # the order
        self.assertIs(args[4], portfolio)     # the paper_shadow portfolio
        self.assertEqual(out["position_id"], "pos1")

    def test_reconcile_close_fill_reuses_core(self):
        with mock.patch("packages.quantum.brokers.alpaca_order_handler._close_position_on_fill") as close:
            ex.reconcile_close_fill(mock.MagicMock(), "pos1", {"id": "o2"}, {"filled_qty": 1})
        close.assert_called_once()
        self.assertEqual(close.call_args[0][1], "pos1")

    def test_live_processor_still_skips_paper_shadow(self):
        # The executor's own-fill design depends on the live processor skipping
        # paper_shadow (#1005). Regression guard that the filter is intact.
        s = (REPO_ROOT / "paper_endpoints.py").read_text(encoding="utf-8")
        self.assertIn('.neq("routing_mode", "paper_shadow")', s)


# ═════════════════════════════════════════════════════════════════════
# paper_shadow portfolio bootstrap
# ═════════════════════════════════════════════════════════════════════
class TestShadowPortfolioBootstrap(unittest.TestCase):
    def test_returns_existing_paper_shadow_portfolio(self):
        supa = _FakeSupabase({"paper_portfolios": [
            {"id": "p1", "user_id": "U", "routing_mode": "paper_shadow"},
            {"id": "p2", "user_id": "U", "routing_mode": "live_eligible"},
        ]})
        port = ex.get_or_create_shadow_portfolio(supa, "U")
        self.assertEqual(port["id"], "p1")

    def test_creates_paper_shadow_portfolio_when_absent(self):
        supa = _FakeSupabase({"paper_portfolios": [
            {"id": "p2", "user_id": "U", "routing_mode": "live_eligible"},
        ]})
        port = ex.get_or_create_shadow_portfolio(supa, "U")
        self.assertEqual(port["routing_mode"], "paper_shadow")
        self.assertEqual(port["cash_balance"], ex.SYNTHETIC_TIER_CAPITAL)


# ═════════════════════════════════════════════════════════════════════
# Canonical geometry exit policy (arm B) — pure
# ═════════════════════════════════════════════════════════════════════
class TestGeometryExitPolicy(unittest.TestCase):
    # debit CALL spread: buy 100C / sell 105C, net debit 2.0
    #   width=5, breakeven=102, R1_frac level = 100 + 0.8*5 = 104
    DEBIT_CALL = {"avg_entry_price": 2.0, "legs": [
        {"action": "buy", "type": "call", "strike": 100},
        {"action": "sell", "type": "call", "strike": 105},
    ]}

    def test_take_profit_when_spot_reaches_frac_level(self):
        d, _ = ex.geometry_exit_decision(self.DEBIT_CALL, underlying_spot=104.5, dte=10)
        self.assertEqual(d, "take_profit")

    def test_hold_between_breakeven_and_profit_level(self):
        d, _ = ex.geometry_exit_decision(self.DEBIT_CALL, underlying_spot=103.0, dte=10)
        self.assertEqual(d, "hold")

    def test_stop_on_breakeven_breach(self):
        d, reason = ex.geometry_exit_decision(self.DEBIT_CALL, underlying_spot=101.0, dte=10)
        self.assertEqual(d, "stop")
        self.assertIn("R2", reason)

    def test_na_for_non_debit_vertical(self):
        single_leg = {"avg_entry_price": 1.0, "legs": [{"action": "buy", "type": "call", "strike": 100}]}
        d, _ = ex.geometry_exit_decision(single_leg, underlying_spot=110.0, dte=10)
        self.assertEqual(d, "n/a")

    def test_na_when_spot_missing(self):
        d, _ = ex.geometry_exit_decision(self.DEBIT_CALL, underlying_spot=None, dte=10)
        self.assertEqual(d, "n/a")


# ═════════════════════════════════════════════════════════════════════
# LEADING INVARIANT — every order routes through the single door
# ═════════════════════════════════════════════════════════════════════
class _OrderFetchSupabase:
    """Minimal supabase whose paper_orders.select().eq().single() returns a row
    (so _submit_staged can fetch the staged order before the door)."""
    def __init__(self):
        self.last_id = None

    def table(self, name):
        return self

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        self.last_id = val
        return self

    def single(self):
        return self

    def execute(self):
        return _Resp({"id": self.last_id})


_CANDIDATE = {
    "symbol": "SPY", "quantity": 1, "limit_price": 1.30,
    "legs": [
        {"symbol": "O:SPY260619C00100000", "action": "buy", "quantity": 1,
         "type": "call", "strike": 100, "expiry": "2026-06-19"},
        {"symbol": "O:SPY260619C00105000", "action": "sell", "quantity": 1,
         "type": "call", "strike": 105, "expiry": "2026-06-19"},
    ],
}
_POSITION = {
    "id": "pos-1", "symbol": "SPY", "quantity": 1, "avg_entry_price": 1.0,
    "current_mark": 1.3, "legs": _CANDIDATE["legs"],
}


class TestSingleChokePointInvariant(unittest.TestCase):
    def test_open_pair_routes_both_arms_through_the_single_door(self):
        supa = _OrderFetchSupabase()
        with mock.patch("packages.quantum.paper_endpoints._stage_order_internal",
                        side_effect=["ord-a", "ord-b"]), \
             mock.patch("packages.quantum.services.analytics_service.AnalyticsService"), \
             mock.patch.object(ex, "guarded_paper_submit",
                               return_value={"status": "submitted"}) as door:
            out = ex.open_pair(supa, "U", _CANDIDATE, {"id": "port-shadow"})
        self.assertEqual(door.call_count, 2)  # arm A + arm B, both via the door
        self.assertEqual(set(out.keys()), {"arm_a", "arm_b"})

    def test_close_arm_routes_through_the_single_door(self):
        supa = _OrderFetchSupabase()
        with mock.patch("packages.quantum.paper_endpoints._stage_order_internal",
                        return_value="ord-close"), \
             mock.patch("packages.quantum.services.analytics_service.AnalyticsService"), \
             mock.patch.object(ex, "guarded_paper_submit",
                               return_value={"status": "submitted"}) as door:
            ex.close_arm(supa, "U", _POSITION, "premium:target_profit", "port-shadow")
        door.assert_called_once()

    def test_no_second_submission_door_in_the_module(self):
        # Source invariant: submit_and_track appears ONLY inside
        # guarded_paper_submit; the orchestration never calls a broker submit
        # primitive or acquires a paper client any other way.
        src = (REPO_ROOT / "services" / "paper_shadow_executor.py").read_text(encoding="utf-8")
        door_start = src.find("def guarded_paper_submit")
        door_end = src.find("\ndef ", door_start + 1)
        door_body = src[door_start:door_end]
        # the door imports + calls submit_and_track
        self.assertIn("import submit_and_track", door_body)
        self.assertIn("submit_and_track(", door_body)
        # NOTHING outside the door imports or CALLS a broker submit primitive,
        # nor acquires a paper client any other way (comments may mention the
        # name; an import/call is the violation).
        rest = src[:door_start] + src[door_end:]
        self.assertNotIn("import submit_and_track", rest)
        self.assertNotIn("submit_and_track(", rest)
        # never acquires the global live client (the module uses build_paper_client;
        # the docstring may mention get_alpaca_client to say it is NOT used).
        self.assertNotIn("import get_alpaca_client", src)
        self.assertNotIn("get_alpaca_client(", rest)


# ═════════════════════════════════════════════════════════════════════
# Arm management — independent rules (A premium-%, B geometry)
# ═════════════════════════════════════════════════════════════════════
class TestArmManagement(unittest.TestCase):
    def test_arm_a_uses_premium_exit(self):
        with mock.patch("packages.quantum.services.paper_exit_evaluator.evaluate_position_exit",
                        return_value="target_profit") as ev:
            should_close, reason = ex.manage_arm(_POSITION, "A", premium_conditions={})
        ev.assert_called_once()
        self.assertTrue(should_close)
        self.assertIn("premium", reason)

    def test_arm_a_holds_when_no_premium_exit(self):
        with mock.patch("packages.quantum.services.paper_exit_evaluator.evaluate_position_exit",
                        return_value=None):
            should_close, reason = ex.manage_arm(_POSITION, "A", premium_conditions={})
        self.assertFalse(should_close)

    def test_arm_b_uses_geometry(self):
        # debit call 100/105 debit 2.0 → R1_frac level 104; spot 104.5 → take_profit
        pos = {"avg_entry_price": 2.0, "legs": [
            {"action": "buy", "type": "call", "strike": 100},
            {"action": "sell", "type": "call", "strike": 105}]}
        should_close, reason = ex.manage_arm(pos, "B", underlying_spot=104.5, dte=10)
        self.assertTrue(should_close)
        self.assertIn("geometry", reason)

    def test_unknown_arm_raises(self):
        with self.assertRaises(ValueError):
            ex.manage_arm(_POSITION, "Z")


# ═════════════════════════════════════════════════════════════════════
# Synthetic-capital override seam (run_midday_cycle additive, byte-identical)
# ═════════════════════════════════════════════════════════════════════
class TestSyntheticCapitalSeam(unittest.TestCase):
    def test_override_param_and_honored_branch_present(self):
        src = (REPO_ROOT / "services" / "workflow_orchestrator.py").read_text(encoding="utf-8")
        self.assertIn("deployable_capital_override: Optional[float] = None", src)
        self.assertIn("if deployable_capital_override is not None:", src)


# ═════════════════════════════════════════════════════════════════════
# Run loop — idempotent state machine over paper_shadow_pairs
# ═════════════════════════════════════════════════════════════════════
class _PairsStore:
    """In-memory paper_shadow_pairs (+ a stub paper_portfolios) supporting the
    select/eq/in_/insert/update chains the state machine uses."""
    def __init__(self):
        self.rows = []
        self._n = 0

    # query builder
    def table(self, name):
        self._name = name
        return _PQ(self, name)


class _PQ:
    def __init__(self, store, name, rows=None, filters=None):
        self.store = store
        self.name = name
        self._rows = rows if rows is not None else None
        self._f = filters or []
        self._pending_update = None
        self._pending_insert = None

    def _base(self):
        if self.name == "paper_portfolios":
            return [{"id": "port-shadow", "user_id": "U", "routing_mode": "paper_shadow",
                     "cash_balance": 2500}]
        return self.store.rows

    def select(self, *a, **k):
        return _PQ(self.store, self.name, list(self._base()), list(self._f))

    def eq(self, col, val):
        rows = [r for r in (self._rows if self._rows is not None else self._base()) if r.get(col) == val]
        q = _PQ(self.store, self.name, rows, self._f + [("eq", col, val)])
        q._pending_update = self._pending_update
        return q

    def in_(self, col, vals):
        s = set(vals)
        rows = [r for r in (self._rows or []) if r.get(col) in s]
        return _PQ(self.store, self.name, rows, self._f)

    def limit(self, n):
        return _PQ(self.store, self.name, (self._rows or [])[:n], self._f)

    def insert(self, payload):
        self.store._n += 1
        payload = {"id": f"pair-{self.store._n}", **payload}
        self.store.rows.append(payload)
        return _PQ(self.store, self.name, [payload], self._f)

    def update(self, fields):
        q = _PQ(self.store, self.name, self._rows, self._f)
        q._pending_update = fields
        return q

    def single(self):
        return self

    def execute(self):
        if self._pending_update is not None:
            # apply to rows matching the eq filters against the live store
            for r in self.store.rows:
                if all(r.get(c) == v for (op, c, v) in self._f if op == "eq"):
                    r.update(self._pending_update)
            return _Resp(None)
        rows = self._rows if self._rows is not None else self._base()
        return _Resp(list(rows))


def _cand(sk):
    return {"signal_key": sk, "symbol": "SPY", "quantity": 1, "limit_price": 1.0,
            "legs": _CANDIDATE["legs"]}


class TestRunLoopIdempotency(unittest.TestCase):
    def setUp(self):
        self.store = _PairsStore()
        self.port = {"id": "port-shadow"}
        self.openp = mock.patch.object(
            ex, "open_pair",
            side_effect=lambda s, u, c, p: {"arm_a": {"order_id": "oa", "result": {}},
                                            "arm_b": {"order_id": "ob", "result": {}}})
        self.openp.start()
        self.addCleanup(self.openp.stop)

    def test_no_reopen_of_running_candidate(self):
        ex._step_open(self.store, "U", "2026-06-01", self.port, [_cand("S1")], cap=4)
        ex._step_open(self.store, "U", "2026-06-01", self.port, [_cand("S1")], cap=4)  # re-run
        s1 = [r for r in self.store.rows if r["signal_key"] == "S1"]
        self.assertEqual(len(s1), 1, "re-running must not re-open a running candidate")

    def test_concurrency_cap_respected(self):
        cands = [_cand(f"S{i}") for i in range(5)]
        ex._step_open(self.store, "U", "2026-06-01", self.port, cands, cap=2)
        self.assertEqual(len(self.store.rows), 2, "must not exceed the concurrency cap")

    def test_no_double_close_arm_already_closing(self):
        # an arm in 'closing' must NOT be closed again by manage
        self.store.rows.append({
            "id": "p1", "user_id": "U", "cycle_date": "2026-06-01", "pair_state": "open",
            "arm_a_state": "closing", "arm_a_position_id": "posA",
            "arm_b_state": "open", "arm_b_position_id": "posB"})
        with mock.patch.object(ex, "_get_position", return_value=_POSITION), \
             mock.patch.object(ex, "manage_arm", return_value=(True, "x")), \
             mock.patch.object(ex, "close_arm") as close, \
             mock.patch.object(ex, "_pairs_in", return_value=self.store.rows):
            ex._step_manage(self.store, "U", "2026-06-01", self.port, lambda p: (1.0, 5, None))
        # only arm B (state 'open') may be closed; arm A ('closing') must be skipped
        self.assertEqual(close.call_count, 1)

    def test_record_only_closed_to_recorded_once(self):
        self.store.rows += [
            {"id": "p1", "user_id": "U", "cycle_date": "2026-06-01", "pair_state": "closed"},
            {"id": "p2", "user_id": "U", "cycle_date": "2026-06-01", "pair_state": "recorded"}]
        n = ex._step_record(self.store, "U", "2026-06-01")
        self.assertEqual(n, 1)  # only the 'closed' one transitions
        states = {r["id"]: r["pair_state"] for r in self.store.rows}
        self.assertEqual(states["p1"], "recorded")
        self.assertEqual(states["p2"], "recorded")  # unchanged
        # re-run: no further transitions
        self.assertEqual(ex._step_record(self.store, "U", "2026-06-01"), 0)

    def test_open_tags_paper_regime_and_synthetic_capital(self):
        ex._step_open(self.store, "U", "2026-06-01", self.port, [_cand("S1")], cap=4)
        row = self.store.rows[0]
        self.assertEqual(row["synthetic_capital"], ex.SYNTHETIC_TIER_CAPITAL)
        self.assertEqual(row["pair_state"], "pending_open")


class TestRunLoopSingleDoorAndFlag(unittest.TestCase):
    def test_open_routes_through_open_pair_door(self):
        store = _PairsStore()
        with mock.patch.object(ex, "open_pair",
                               return_value={"arm_a": {"order_id": "oa"}, "arm_b": {"order_id": "ob"}}) as door:
            ex._step_open(store, "U", "2026-06-01", {"id": "p"}, [_cand("S1")], cap=4)
        door.assert_called_once()  # the open goes through open_pair (the single door)

    def test_cycle_noop_when_flag_off(self):
        with mock.patch.dict(os.environ, {iso.FLAG_ENV: "0"}, clear=True):
            out = ex.run_paper_shadow_cycle(
                mock.MagicMock(), "U", cycle_date="2026-06-01",
                select_fn=lambda: [], market_fn=lambda p: (None, None, None))
        self.assertEqual(out, {"ran": False, "reason": "flag_off"})

    def test_run_loop_source_has_no_second_submission_door(self):
        # the loop reuses open_pair/close_arm only — no broker submit primitive
        src = (REPO_ROOT / "services" / "paper_shadow_executor.py").read_text(encoding="utf-8")
        run_start = src.find("def run_paper_shadow_cycle")
        loop_src = src[run_start:]
        self.assertNotIn("submit_and_track(", loop_src)
        self.assertNotIn("import submit_and_track", loop_src)


# ═════════════════════════════════════════════════════════════════════
# Flag default OFF
# ═════════════════════════════════════════════════════════════════════
class TestFlagDefaultOff(unittest.TestCase):
    def test_is_enabled_default_off(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(ex.is_enabled())


if __name__ == "__main__":
    unittest.main()
