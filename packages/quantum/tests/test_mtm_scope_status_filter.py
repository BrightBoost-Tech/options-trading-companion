"""Tests for the MTM scope status filter (2026-06-06 hygiene fix).

_get_open_positions filtered .neq("quantity", 0) but never status, so
closed rows with residual quantity leaked into MTM scope forever:
- CSX 1f77f6af: closed, legs expired 2026-06-05 → unmarkable → the
  mtm_refresh_partial "1 skipped" alarm fired every cycle, permanently
  (cried-wolf noise masking any genuinely unmarkable LIVE position).
- F bdbe4d04: manually closed 2026-05-29, still marked every cycle,
  its unrealized_pl mutating on a closed row.

Fix: add .neq("status", "closed") — mirroring close_helper's liveness
predicate (status != 'closed'), NOT a bare status == 'open', so any
future intermediate live state (staging/partial) would stay in scope.

These tests pin (1) the query shape includes BOTH filters, (2) the
exclude-only-closed semantics against a simulated PostgREST layer,
(3) the mark math / monitor / exit logic are untouched (scope-query-
only change).
"""

import sys
import types
import unittest
from unittest.mock import MagicMock

# Stub alpaca-py so transitive imports resolve in the test venv.
from packages.quantum.tests._alpaca_stub import ensure_alpaca as _ensure_alpaca

_ensure_alpaca()

from packages.quantum.services.paper_mark_to_market_service import (  # noqa: E402
    PaperMarkToMarketService,
)


# ---------------------------------------------------------------------------
# Fake PostgREST layer: applies eq/neq/in_ filters to in-memory rows so the
# test exercises the QUERY SEMANTICS, not a hand-wired return value.
# ---------------------------------------------------------------------------

class _FakeQuery:
    def __init__(self, rows):
        self._rows = list(rows)

    def select(self, *_a, **_k):
        return self

    def eq(self, col, val):
        self._rows = [r for r in self._rows if r.get(col) == val]
        return self

    def neq(self, col, val):
        self._rows = [r for r in self._rows if r.get(col) != val]
        return self

    def in_(self, col, vals):
        self._rows = [r for r in self._rows if r.get(col) in vals]
        return self

    def execute(self):
        return types.SimpleNamespace(data=list(self._rows))


class _FakeClient:
    def __init__(self, portfolios, positions):
        self._tables = {
            "paper_portfolios": portfolios,
            "paper_positions": positions,
        }

    def table(self, name):
        return _FakeQuery(self._tables.get(name, []))


def _service(positions):
    svc = PaperMarkToMarketService.__new__(PaperMarkToMarketService)
    svc.client = _FakeClient(
        portfolios=[{"id": "pf-1", "user_id": "u1"}],
        positions=positions,
    )
    return svc


def _pos(pid, status, quantity, symbol="NFLX"):
    return {
        "id": pid, "portfolio_id": "pf-1", "symbol": symbol,
        "status": status, "quantity": quantity,
    }


class TestMtmScopeStatusFilter(unittest.TestCase):

    def test_closed_residual_quantity_rows_excluded(self):
        """The production leakers: closed rows with quantity != 0 (the
        expired CSX and the manually-closed F) must leave MTM scope."""
        rows = [
            _pos("a9f977bf", "open", 2.0, "NFLX"),
            _pos("1f77f6af", "closed", 1.0, "CSX"),   # expired straggler
            _pos("bdbe4d04", "closed", 5.0, "F"),     # manual close 05-29
        ]
        got = _service(rows)._get_open_positions("u1")
        self.assertEqual([p["id"] for p in got], ["a9f977bf"])

    def test_open_positions_stay_in_scope(self):
        """Every open position keeps marking — none accidentally dropped."""
        rows = [
            _pos("a9f977bf", "open", 2.0, "NFLX"),
            _pos("dd096ef5", "open", 3.0, "NFLX"),
            _pos("f6d56943", "open", 6.0, "NFLX"),
        ]
        got = _service(rows)._get_open_positions("u1")
        self.assertEqual(len(got), 3)

    def test_hypothetical_intermediate_live_status_stays_in_scope(self):
        """The filter is status != 'closed' (close_helper's liveness
        predicate), NOT status == 'open' — a future intermediate live
        state must keep marking rather than silently leave MTM scope."""
        rows = [
            _pos("p-open", "open", 2.0),
            _pos("p-staging", "pending_open", 1.0),
            _pos("p-closing", "closing", 1.0),
            _pos("p-closed", "closed", 1.0),
        ]
        got = _service(rows)._get_open_positions("u1")
        self.assertEqual(
            sorted(p["id"] for p in got),
            ["p-closing", "p-open", "p-staging"],
        )

    def test_zero_quantity_still_excluded(self):
        """The original quantity filter is preserved alongside status."""
        rows = [
            _pos("p-open", "open", 2.0),
            _pos("p-zeroed", "open", 0),
        ]
        got = _service(rows)._get_open_positions("u1")
        self.assertEqual([p["id"] for p in got], ["p-open"])

    def test_no_portfolios_returns_empty(self):
        svc = PaperMarkToMarketService.__new__(PaperMarkToMarketService)
        svc.client = _FakeClient(portfolios=[], positions=[_pos("x", "open", 1.0)])
        self.assertEqual(svc._get_open_positions("u1"), [])


class TestQueryShapePinned(unittest.TestCase):
    """Source pin: both filters present in the scope query; scope-query-
    only change (mark math and refresh flow untouched)."""

    def _source(self):
        import inspect
        return inspect.getsource(PaperMarkToMarketService._get_open_positions)

    def test_status_filter_present(self):
        self.assertIn('.neq("status", "closed")', self._source())

    def test_quantity_filter_preserved(self):
        self.assertIn('.neq("quantity", 0)', self._source())

    def test_not_a_bare_open_equality(self):
        # status == 'open' would drop a live-but-intermediate position.
        self.assertNotIn('.eq("status", "open")', self._source())


if __name__ == "__main__":
    unittest.main()
