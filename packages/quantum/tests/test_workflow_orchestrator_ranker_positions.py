"""
Regression test for Issue 3B — the portfolio-aware-ranker fetch of open
positions must SELECT only columns that exist on `paper_positions`.

Commit d12f69b (2026-04-16, "4-area audit fixes — DTE buckets,
portfolio-aware ranker, sector mapping, snapshot TTL") introduced a
SELECT that included `max_loss` — a column that never existed on
`paper_positions` (only `max_credit` is declared; trade_journal has
`max_loss` but not paper_positions). PostgREST surfaced the missing
column as an exception; the surrounding try/except swallowed it and
assigned `_ranker_positions = []`, silently degrading the ranker to
portfolio-blind for 2 consecutive cycles before Issue 3B diagnosis.

The fix drops `max_loss` from the SELECT. Downstream consumers in
`canonical_ranker.compute_risk_adjusted_ev` already have a fallback:
`p.get("max_credit") or p.get("max_loss") or 0` handles rows that
don't carry the `max_loss` key at all.

Tests:
 1. Source-level assertion: the `paper_positions` SELECT in
    `workflow_orchestrator` must NOT reference `max_loss` and MUST
    retain `max_credit` and `sector` (which the ranker uses).
 2. Downstream contract: `compute_risk_adjusted_ev` handles a
    populated `existing_positions` list whose rows lack `max_loss`
    keys — i.e., concentration_penalty and correlation_factor stay
    sensible, no exception raised.
"""

import os
import sys
import types
import unittest

# Stub the alpaca-py surface the repo's modules import lazily (not
# needed here but matches the pattern used by neighbouring test files).
_alpaca_pkg = types.ModuleType("alpaca")
_alpaca_trading = types.ModuleType("alpaca.trading")
_alpaca_trading_requests = types.ModuleType("alpaca.trading.requests")
sys.modules.setdefault("alpaca", _alpaca_pkg)
sys.modules.setdefault("alpaca.trading", _alpaca_trading)
sys.modules.setdefault("alpaca.trading.requests", _alpaca_trading_requests)


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
ORCHESTRATOR_PATH = os.path.join(
    REPO_ROOT, "packages", "quantum", "services", "workflow_orchestrator.py"
)


class TestRankerPositionsSelect(unittest.TestCase):
    """
    Issue 3B regression. The SELECT on paper_positions for the
    portfolio-aware ranker must not reference a column that doesn't
    exist on the table.
    """

    def test_select_excludes_max_loss_and_keeps_max_credit_sector(self):
        with open(ORCHESTRATOR_PATH, "r", encoding="utf-8") as f:
            src = f.read()

        # Find the ranker-positions SELECT. There's exactly one spot
        # in workflow_orchestrator that selects these fields from
        # paper_positions for the portfolio-aware ranker.
        marker = '.table("paper_positions")'
        self.assertIn(
            marker, src,
            "Expected workflow_orchestrator to fetch paper_positions "
            "for the portfolio-aware ranker path",
        )

        # Extract the .select(...) argument that immediately follows
        # the paper_positions table reference in the ranker block. We
        # check only the SELECT column-list string, not surrounding
        # comments that may legitimately mention max_loss as context.
        ranker_block_start = src.find("RANKER_PORTFOLIO_AWARE")
        self.assertGreater(ranker_block_start, 0)
        ranker_block = src[ranker_block_start:ranker_block_start + 1500]

        self.assertIn(
            ".table(\"paper_positions\")", ranker_block,
            "paper_positions SELECT must live inside the "
            "RANKER_PORTFOLIO_AWARE block",
        )

        # Parse out the SELECT column-list literal.
        table_pos = ranker_block.find(".table(\"paper_positions\")")
        after_table = ranker_block[table_pos:]
        select_start = after_table.find(".select(\"") + len(".select(\"")
        self.assertGreater(
            select_start, len(".select(\"") - 1,
            "Could not find .select(\"...\") after paper_positions",
        )
        select_end = after_table.find("\"", select_start)
        select_columns = after_table[select_start:select_end]

        self.assertNotIn(
            "max_loss", select_columns,
            f"SELECT column list {select_columns!r} must NOT reference "
            "max_loss — column does not exist on paper_positions "
            "(d12f69b schema-drift regression from Issue 3B).",
        )
        self.assertIn(
            "max_credit", select_columns,
            f"SELECT column list {select_columns!r} must still include "
            "max_credit (it's the fallback canonical_ranker reads "
            "when computing concentration)",
        )
        self.assertIn(
            "sector", select_columns,
            f"SELECT column list {select_columns!r} must still include "
            "sector (used by sector concentration checks)",
        )


class TestCanonicalRankerHandlesMissingMaxLoss(unittest.TestCase):
    """
    Downstream contract: even if the SELECT returns rows with no
    max_loss key, compute_risk_adjusted_ev must not raise and must
    compute a sensible concentration_penalty from max_credit.
    """

    def test_existing_positions_without_max_loss_key_do_not_raise(self):
        from packages.quantum.analytics.canonical_ranker import (
            compute_risk_adjusted_ev,
        )

        # Suggestion with plenty of edge so it passes the small-account
        # filter; we're testing the marginal-risk + concentration path,
        # not the filter.
        suggestion = {
            "ticker": "AMD",
            "ev": 200.0,
            "sizing_metadata": {
                "contracts": 1,
                "max_loss_total": 500.0,
                "expected_slippage": 5.0,
            },
        }

        # Rows as they'd come back from the fixed SELECT
        # ("symbol,quantity,max_credit,sector") — no max_loss key.
        existing_positions = [
            {
                "symbol": "AMD",
                "quantity": 1,
                "max_credit": 400.0,
                "sector": "Technology",
            },
        ]

        result = compute_risk_adjusted_ev(
            suggestion,
            existing_positions=existing_positions,
            portfolio_budget=10000.0,
        )

        # Should compute a real number, not raise.
        self.assertIsInstance(result, float)
        # Small-account filter: net_edge ≈ 200 − 5 − 0.65*1*2 = ~193.70 > 15,
        # so we don't short-circuit to -999.
        self.assertGreater(result, 0)

    def test_empty_positions_list_means_portfolio_blind_not_crash(self):
        """
        Sanity check: empty existing_positions (the error path's
        degraded state) doesn't raise — it just produces the
        portfolio-blind ranking the ranker used to fall back to.
        """
        from packages.quantum.analytics.canonical_ranker import (
            compute_risk_adjusted_ev,
        )

        suggestion = {
            "ticker": "AMD",
            "ev": 200.0,
            "sizing_metadata": {
                "contracts": 1,
                "max_loss_total": 500.0,
                "expected_slippage": 5.0,
            },
        }

        result = compute_risk_adjusted_ev(
            suggestion,
            existing_positions=[],
            portfolio_budget=10000.0,
        )
        self.assertIsInstance(result, float)
        self.assertGreater(result, 0)


if __name__ == "__main__":
    unittest.main()
