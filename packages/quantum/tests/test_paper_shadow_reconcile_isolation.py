"""Paper-shadow Phase 1b — RECONCILE-LOOP isolation completion (Step 1 safety).

1a isolated the 3 PRIMARY position-selection filters (poll, intraday fetch,
evaluator fetch). This proves the SECONDARY reconcile loops in
alpaca_order_sync are now also isolated — the ones that match by
status/source_engine, not routing_mode, and so previously did NOT exclude
paper_shadow:

  - Step 2 (orphan repair) → delegates to _process_orders_for_user, which
    re-resolves the user's portfolios; the bulletproof guard excludes
    paper_shadow at that p_ids resolution (user-scoping-proof), plus a
    defense-in-depth filter on the orphan-detection query.
  - Step 3 (stuck-open reconcile) → CLOSES positions; excluded by portfolio.

Load-bearing safety: a paper_shadow position is NOT swept by orphan-repair OR
stuck-open reconcile; a LIVE position still IS. This MUST hold before the
executor places any order.
"""

import os
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent


# ─────────────────────────────────────────────────────────────────────
# Fake PostgREST-ish client supporting eq/neq/in_/is_/gt + not_.in_/not_.is_
# so the REAL handler code runs through the REAL filter chains.
# ─────────────────────────────────────────────────────────────────────
class _Resp:
    def __init__(self, data):
        self.data = data


class _NotProxy:
    def __init__(self, q):
        self._q = q

    def in_(self, col, vals):
        s = set(vals)
        return _FakeQuery([r for r in self._q._rows if r.get(col) not in s], self._q._log)

    def is_(self, col, val):
        # PostgREST is_(col,"null"); not_.is_ → col IS NOT NULL
        if val in ("null", None):
            return _FakeQuery([r for r in self._q._rows if r.get(col) is not None], self._q._log)
        return _FakeQuery([r for r in self._q._rows if r.get(col) != val], self._q._log)


class _FakeQuery:
    def __init__(self, rows, log):
        self._rows = list(rows)
        self._log = log

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        return _FakeQuery([r for r in self._rows if r.get(col) == val], self._log)

    def neq(self, col, val):
        return _FakeQuery([r for r in self._rows if r.get(col) != val], self._log)

    def in_(self, col, vals):
        s = set(vals)
        return _FakeQuery([r for r in self._rows if r.get(col) in s], self._log)

    def is_(self, col, val):
        if val in ("null", None):
            return _FakeQuery([r for r in self._rows if r.get(col) is None], self._log)
        return _FakeQuery([r for r in self._rows if r.get(col) == val], self._log)

    def gt(self, col, val):
        return _FakeQuery(
            [r for r in self._rows if r.get(col) is not None and float(r.get(col)) > val], self._log
        )

    @property
    def not_(self):
        return _NotProxy(self)

    def execute(self):
        return _Resp(list(self._rows))


class _FakeSupabase:
    def __init__(self, tables):
        self._tables = tables
        self.tables_accessed = []

    def table(self, name):
        self.tables_accessed.append(name)
        return _FakeQuery(self._tables.get(name, []), self.tables_accessed)


# ═════════════════════════════════════════════════════════════════════
# Step 2 — orphan repair: _process_orders_for_user excludes paper_shadow
# (the user-scoping-proof guard — the real isolation point)
# ═════════════════════════════════════════════════════════════════════
class TestStep2OrphanRepairExcludesPaperShadow(unittest.TestCase):
    def _call(self, supabase):
        from packages.quantum.paper_endpoints import _process_orders_for_user
        return _process_orders_for_user(supabase, mock.MagicMock(), "U")

    def test_paper_shadow_only_user_is_fully_skipped(self):
        # User owns ONLY a paper_shadow portfolio with an orphan fill.
        # After the .neq filter, p_ids is empty → early return, paper_orders
        # NEVER queried → the executor's orphan is never processed.
        supa = _FakeSupabase({
            "paper_portfolios": [
                {"id": "port-shadow", "user_id": "U", "routing_mode": "paper_shadow", "cash_balance": 1000},
            ],
            "paper_orders": [
                {"id": "o-shadow", "user_id": "U", "portfolio_id": "port-shadow",
                 "status": "filled", "position_id": None, "filled_qty": 1},
            ],
        })
        result = self._call(supa)
        self.assertEqual(result["processed"], 0)
        self.assertNotIn("paper_orders", supa.tables_accessed,
                         "paper_shadow-only user must early-return before touching paper_orders")

    def test_mixed_user_paper_shadow_orphan_not_processed(self):
        # User owns BOTH a live and a paper_shadow portfolio; the orphan is in
        # the paper_shadow one. p_ids excludes port-shadow → the orphan query
        # (scoped to p_ids) returns nothing → not processed. This is the case a
        # query-level filter on the Step-2 detection alone could NOT isolate.
        supa = _FakeSupabase({
            "paper_portfolios": [
                {"id": "port-live", "user_id": "U", "routing_mode": "live_eligible", "cash_balance": 5000},
                {"id": "port-shadow", "user_id": "U", "routing_mode": "paper_shadow", "cash_balance": 1000},
            ],
            "paper_orders": [
                {"id": "o-shadow", "user_id": "U", "portfolio_id": "port-shadow",
                 "status": "filled", "position_id": None, "filled_qty": 1},
            ],
        })
        result = self._call(supa)
        self.assertEqual(result["processed"], 0,
                         "a paper_shadow orphan under a mixed user must not be processed")


# ═════════════════════════════════════════════════════════════════════
# Step 3 — stuck-open reconcile (CLOSES positions): handler-level proof
# ═════════════════════════════════════════════════════════════════════
class TestStep3StuckOpenReconcileExcludesPaperShadow(unittest.TestCase):
    def _run_with(self, tables):
        supa = _FakeSupabase(tables)
        from packages.quantum.jobs.handlers import alpaca_order_sync
        closed = []

        def _fake_close(client, pid, filled_order, alpaca_data):
            closed.append(pid)

        with mock.patch.object(alpaca_order_sync, "get_admin_client", return_value=supa), \
             mock.patch("packages.quantum.brokers.alpaca_client.get_alpaca_client",
                        return_value=mock.MagicMock()), \
             mock.patch("packages.quantum.brokers.alpaca_order_handler._close_position_on_fill",
                        side_effect=_fake_close), \
             mock.patch.dict(os.environ, {"RECONCILE_POSITIONS_ENABLED": "0"}, clear=False):
            result = alpaca_order_sync.run({})
        return result, closed

    def test_stuck_open_closes_live_not_paper_shadow(self):
        tables = {
            "paper_portfolios": [
                {"id": "port-live", "user_id": "U", "routing_mode": "live_eligible"},
                {"id": "port-shadow", "user_id": "U", "routing_mode": "paper_shadow"},
            ],
            "paper_orders": [
                # LIVE stuck-open filled CLOSE order → must be reconciled.
                {"id": "ord-live", "portfolio_id": "port-live", "status": "filled",
                 "position_id": "pos-live", "filled_qty": 1, "side": "sell",
                 "alpaca_order_id": "ax-live", "avg_fill_price": 1.0, "filled_at": None,
                 "broker_response": {}, "order_json": {"source_engine": "paper_exit_evaluator"}},
                # PAPER_SHADOW stuck-open filled CLOSE order → must NOT be reconciled.
                {"id": "ord-shadow", "portfolio_id": "port-shadow", "status": "filled",
                 "position_id": "pos-shadow", "filled_qty": 1, "side": "sell",
                 "alpaca_order_id": "ax-shadow", "avg_fill_price": 1.0, "filled_at": None,
                 "broker_response": {}, "order_json": {"source_engine": "paper_exit_evaluator"}},
            ],
            "paper_positions": [
                {"id": "pos-live", "status": "open"},
                {"id": "pos-shadow", "status": "open"},
            ],
        }
        result, closed = self._run_with(tables)
        self.assertIn("pos-live", closed, "LIVE stuck-open position must still be reconciled")
        self.assertNotIn("pos-shadow", closed, "paper_shadow position must NOT be reconciled by the live sync")
        self.assertEqual(result.get("stuck_open_closed"), 1)

    def test_byte_identical_when_no_paper_shadow(self):
        # No paper_shadow rows → the LIVE stuck-open position is reconciled
        # exactly as before (the filter is a proven no-op).
        tables = {
            "paper_portfolios": [
                {"id": "port-live", "user_id": "U", "routing_mode": "live_eligible"},
            ],
            "paper_orders": [
                {"id": "ord-live", "portfolio_id": "port-live", "status": "filled",
                 "position_id": "pos-live", "filled_qty": 1, "side": "sell",
                 "alpaca_order_id": "ax-live", "avg_fill_price": 1.0, "filled_at": None,
                 "broker_response": {}, "order_json": {"source_engine": "paper_exit_evaluator"}},
            ],
            "paper_positions": [
                {"id": "pos-live", "status": "open"},
            ],
        }
        result, closed = self._run_with(tables)
        self.assertEqual(closed, ["pos-live"])
        self.assertEqual(result.get("stuck_open_closed"), 1)


# ═════════════════════════════════════════════════════════════════════
# Source-level regression guards on the 3 reconcile-loop filters
# ═════════════════════════════════════════════════════════════════════
class TestReconcileFiltersWired(unittest.TestCase):
    def _src(self, rel):
        return (REPO_ROOT / rel).read_text(encoding="utf-8")

    def test_process_orders_excludes_paper_shadow(self):
        s = self._src("paper_endpoints.py")
        self.assertIn('.neq("routing_mode", "paper_shadow")', s)

    def test_order_sync_step2_and_step3_exclude_by_portfolio(self):
        s = self._src("jobs/handlers/alpaca_order_sync.py")
        # both the orphan (Step 2) and stuck (Step 3) queries gain the guarded
        # portfolio exclusion reusing shadow_portfolio_ids
        self.assertIn("orphan_query = orphan_query.not_.in_(\"portfolio_id\", shadow_portfolio_ids)", s)
        self.assertIn("stuck_query = stuck_query.not_.in_(\"portfolio_id\", shadow_portfolio_ids)", s)


if __name__ == "__main__":
    unittest.main()
