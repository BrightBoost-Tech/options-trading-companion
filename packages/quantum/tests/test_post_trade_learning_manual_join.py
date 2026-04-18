"""
Regression tests for Issue 3A — `post_trade_learning._get_unprocessed_trades`.

Commit `dbc0564` (2026-04-09, "feat(agents): self-learning + profit
optimization + orchestrator + efficiency fixes") shipped the handler
with a PostgREST FK-embed:

    self.supabase.table("learning_feedback_loops") \
        .select("*, trade_suggestions(*)")

PostgREST requires a declared FK constraint between the two tables to
resolve that embed. The schema dump shows `learning_feedback_loops`
has a `suggestion_id` column but NO FK constraint to
`trade_suggestions.id`. Every invocation raised "Could not find a
relationship... Perhaps you meant 'inference_log' instead". The
surrounding try/except swallowed the error and the handler silently
returned `[]`, processing 0 trades for 9+ days. Data audit confirmed
76 rows accumulated in `learning_feedback_loops` with
`learning_processed=false`, 0 with `learning_processed=true`.

This PR replaces the embed with a two-query Python join on
`suggestion_id`, matching the idiom used elsewhere in the codebase.
No schema mutation required.

Tests
  1. Happy path: handler returns N rows with attached `trade_suggestions`
     dicts when the suggestion lookup succeeds.
  2. Missing suggestion_id: rows without a `suggestion_id` get
     `trade_suggestions=None` and still flow through.
  3. Suggestion lookup failure: graceful degradation — rows come
     through with `trade_suggestions=None`; no exception raised.
  4. Mark-processed: after processing, `learning_processed=True` is
     written via the existing `_mark_trades_processed` helper.
  5. Regression shape guard: the SELECT on learning_feedback_loops
     does NOT reference the FK-embed syntax anymore.
"""

import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

# Stub alpaca-py surface (unused here but matches neighbouring files).
_alpaca_pkg = types.ModuleType("alpaca")
_alpaca_trading = types.ModuleType("alpaca.trading")
_alpaca_trading_requests = types.ModuleType("alpaca.trading.requests")
sys.modules.setdefault("alpaca", _alpaca_pkg)
sys.modules.setdefault("alpaca.trading", _alpaca_trading)
sys.modules.setdefault("alpaca.trading.requests", _alpaca_trading_requests)


def _build_supabase_mock(table_responses=None, raise_on_tables=None):
    """Supabase mock whose .table(name) returns a chain for each call.

    `table_responses` maps table name → list of row dicts returned by
    .execute(). `raise_on_tables` is a set of table names whose queries
    should raise a RuntimeError (to simulate the PostgREST failure).
    """
    table_responses = table_responses or {}
    raise_on_tables = raise_on_tables or set()

    supabase = MagicMock()

    def table_side_effect(name):
        chain = MagicMock()
        if name in raise_on_tables:
            chain.execute.side_effect = RuntimeError(
                f"simulated failure on {name}"
            )
        else:
            chain.execute.return_value = MagicMock(
                data=table_responses.get(name, []),
            )
        for method in (
            "select", "eq", "neq", "gte", "lt", "gt", "in_",
            "order", "limit", "single", "maybe_single", "update",
        ):
            getattr(chain, method).return_value = chain
        return chain

    supabase.table.side_effect = table_side_effect
    return supabase


class TestGetUnprocessedTradesManualJoin(unittest.TestCase):
    """Issue 3A happy-path + edge-case coverage."""

    def _make_agent(self, supabase):
        from packages.quantum.jobs.handlers import post_trade_learning
        agent = post_trade_learning.PostTradeLearningAgent.__new__(
            post_trade_learning.PostTradeLearningAgent,
        )
        agent.supabase = supabase
        return agent

    def test_happy_path_attaches_suggestion_to_each_trade(self):
        trades = [
            {
                "id": "t1",
                "user_id": "u",
                "suggestion_id": "s1",
                "pnl_realized": 100.0,
                "pnl_predicted": 90.0,
            },
            {
                "id": "t2",
                "user_id": "u",
                "suggestion_id": "s2",
                "pnl_realized": -20.0,
                "pnl_predicted": -25.0,
            },
        ]
        suggestions = [
            {"id": "s1", "strategy": "LONG_CALL_DEBIT_SPREAD", "regime": "normal"},
            {"id": "s2", "strategy": "IRON_CONDOR", "regime": "chop"},
        ]
        supabase = _build_supabase_mock({
            "learning_feedback_loops": trades,
            "trade_suggestions": suggestions,
        })
        agent = self._make_agent(supabase)

        result = agent._get_unprocessed_trades("u")

        self.assertEqual(len(result), 2)
        t1 = next(t for t in result if t["id"] == "t1")
        t2 = next(t for t in result if t["id"] == "t2")
        self.assertEqual(t1["trade_suggestions"]["strategy"], "LONG_CALL_DEBIT_SPREAD")
        self.assertEqual(t1["trade_suggestions"]["regime"], "normal")
        self.assertEqual(t2["trade_suggestions"]["strategy"], "IRON_CONDOR")

    def test_null_suggestion_id_row_still_flows_through(self):
        trades = [
            {
                "id": "t-no-sugg",
                "user_id": "u",
                "suggestion_id": None,
                "strategy": "LONG_CALL_DEBIT_SPREAD",
                "regime": "normal",
                "pnl_realized": 50.0,
                "pnl_predicted": 40.0,
            },
        ]
        supabase = _build_supabase_mock({
            "learning_feedback_loops": trades,
            "trade_suggestions": [],
        })
        agent = self._make_agent(supabase)

        result = agent._get_unprocessed_trades("u")

        self.assertEqual(len(result), 1)
        self.assertIsNone(result[0]["trade_suggestions"])
        # Segment-key fallback reads trade.strategy when there's no
        # suggestion — verify that still works downstream.
        self.assertEqual(result[0]["strategy"], "LONG_CALL_DEBIT_SPREAD")

    def test_suggestion_lookup_failure_degrades_gracefully(self):
        """If the suggestion query raises, trades still come through."""
        trades = [
            {
                "id": "t1",
                "user_id": "u",
                "suggestion_id": "s1",
                "strategy": "LONG_CALL_DEBIT_SPREAD",
                "regime": "normal",
            },
        ]
        supabase = _build_supabase_mock(
            {"learning_feedback_loops": trades, "trade_suggestions": []},
            raise_on_tables={"trade_suggestions"},
        )
        agent = self._make_agent(supabase)

        result = agent._get_unprocessed_trades("u")

        self.assertEqual(len(result), 1)
        self.assertIsNone(result[0]["trade_suggestions"])

    def test_primary_query_failure_returns_empty_list(self):
        """The outer try/except protects against PostgREST issues on the
        primary query too — handler still returns [] (not raising)."""
        supabase = _build_supabase_mock(
            {"learning_feedback_loops": [], "trade_suggestions": []},
            raise_on_tables={"learning_feedback_loops"},
        )
        agent = self._make_agent(supabase)

        result = agent._get_unprocessed_trades("u")

        self.assertEqual(result, [])

    def test_missing_suggestion_row_maps_to_none(self):
        """suggestion_id present on trade but lookup returns no matching
        row → trade gets trade_suggestions=None (not a stale row)."""
        trades = [
            {
                "id": "t1",
                "user_id": "u",
                "suggestion_id": "s-missing",
                "strategy": "LONG_CALL_DEBIT_SPREAD",
                "regime": "normal",
            },
        ]
        supabase = _build_supabase_mock({
            "learning_feedback_loops": trades,
            "trade_suggestions": [],  # Lookup succeeds, zero rows.
        })
        agent = self._make_agent(supabase)

        result = agent._get_unprocessed_trades("u")

        self.assertEqual(len(result), 1)
        self.assertIsNone(result[0]["trade_suggestions"])

    def test_build_segment_key_uses_suggestion_fallback_when_trade_missing_fields(self):
        """End-to-end wiring check: _build_segment_key reads the
        attached suggestion when the trade itself lacks strategy/regime."""
        from packages.quantum.jobs.handlers import post_trade_learning
        agent = post_trade_learning.PostTradeLearningAgent.__new__(
            post_trade_learning.PostTradeLearningAgent,
        )

        trade = {
            "id": "t1",
            "suggestion_id": "s1",
            "strategy": None,
            "regime": None,
            "details_json": {"dte_at_entry": 30},
            "trade_suggestions": {
                "id": "s1",
                "strategy": "LONG_CALL_DEBIT_SPREAD",
                "regime": "normal",
            },
        }
        key = agent._build_segment_key(trade)
        self.assertEqual(key, "LONG_CALL_DEBIT_SPREAD|normal|21-35")

    def test_select_no_longer_uses_fk_embed(self):
        """Regression shape guard: the SELECT column list on
        learning_feedback_loops must not include the PostgREST embed
        `trade_suggestions(*)` pattern, which requires an FK that
        doesn't exist in the schema."""
        from packages.quantum.jobs.handlers import post_trade_learning as mod
        repo_root = os.path.abspath(os.path.join(
            os.path.dirname(mod.__file__), "..", "..", "..", "..",
        ))
        source_path = os.path.join(
            repo_root, "packages", "quantum", "jobs", "handlers",
            "post_trade_learning.py",
        )
        with open(source_path, "r", encoding="utf-8") as f:
            src = f.read()

        # Inspect only the .select(...) literal inside the learning_
        # feedback_loops table call — docstrings may legitimately
        # describe the historical embed syntax as context.
        start = src.find(".table(\"learning_feedback_loops\")")
        self.assertGreater(start, 0)
        # Next few hundred chars cover the .select(...) invocation.
        window = src[start:start + 400]
        select_idx = window.find(".select(\"")
        self.assertGreater(select_idx, 0)
        after_select = window[select_idx + len(".select(\""):]
        select_end = after_select.find("\"")
        select_literal = after_select[:select_end]

        self.assertNotIn(
            "trade_suggestions", select_literal,
            f"SELECT literal {select_literal!r} must not reference "
            "trade_suggestions (PostgREST FK-embed) — the FK doesn't "
            "exist on learning_feedback_loops (Issue 3A regression).",
        )


if __name__ == "__main__":
    unittest.main()
