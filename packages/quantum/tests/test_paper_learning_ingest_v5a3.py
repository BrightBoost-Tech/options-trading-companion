"""
Regression tests for the v5-A3 is_paper derivation + N4 learning_ingested
marker in paper_learning_ingest.

These live in a SEPARATE, non-skipped module on purpose: the broader
test_paper_learning_ingest.py is module-skipped ([Cluster M] #774), so tests
added there would not run. These MUST run in CI.

Covers:
- A1: is_paper derived from order.execution_mode alone (alpaca_live -> False;
  internal_paper / shadow_blocked / None / missing -> True), INDEPENDENT of
  portfolio_id being in query scope. The original bug: the closed-positions
  SELECT omitted portfolio_id, so the portfolio-membership conjunct was always
  False and every live broker fill was mislabeled is_paper=True.
- A2: learning_ingested marker flips True on successful ingest (it was a dead
  column that read False "always" — audit 2026-06-12 N4).
"""
import asyncio
from unittest.mock import MagicMock

from packages.quantum.jobs.handlers.paper_learning_ingest import (
    _resolve_is_paper,
    _ingest_paper_outcomes_for_user,
)


class TestResolveIsPaper:
    """A1 (unit) — is_paper from execution_mode (routing ground truth)."""

    def test_alpaca_live_is_live(self):
        assert _resolve_is_paper({"execution_mode": "alpaca_live"}) is False

    def test_internal_paper_is_paper(self):
        assert _resolve_is_paper({"execution_mode": "internal_paper"}) is True

    def test_shadow_blocked_is_paper(self):
        assert _resolve_is_paper({"execution_mode": "shadow_blocked"}) is True

    def test_missing_execution_mode_is_paper(self):
        # Conservative legacy default: never fabricate 'live'.
        assert _resolve_is_paper({}) is True

    def test_none_execution_mode_is_paper(self):
        assert _resolve_is_paper({"execution_mode": None}) is True

    def test_independent_of_portfolio_id_scope(self):
        # The v5-A3 regression guard: the result must NOT depend on portfolio_id.
        # An alpaca_live order with NO portfolio_id key at all is still live.
        assert _resolve_is_paper({"execution_mode": "alpaca_live"}) is False
        # A simulated order stays paper even if a (live-looking) portfolio_id is
        # present — execution_mode is the only signal consulted.
        assert _resolve_is_paper(
            {"execution_mode": "shadow_blocked", "portfolio_id": "live-xyz"}
        ) is True


# Deliberately NO portfolio_id key — mirrors the real closed-positions SELECT
# that omits it (the missing-column class the fix must be immune to).
_POSITION_NO_PORTFOLIO_ID = {
    "id": "pos-new",
    "realized_pl": 662.10,
    "status": "closed",
    "closed_at": "2026-06-16T16:45:00+00:00",
    "suggestion_id": None,  # no suggestion -> skips trade_suggestions + backfill
    "trace_id": None,
    "symbol": "NFLX",
}


def _mock_supabase_for_one_close(order, position):
    """Mock supabase returning exactly one closed position + one closing order,
    with no pre-existing learning rows. Returns (supabase, paper_positions_mock,
    lfl_mock) so callers can assert on the update + insert calls."""
    pp = MagicMock(name="paper_positions")
    # closed-positions query: select->eq->eq->gte->execute
    pp.select.return_value.eq.return_value.eq.return_value.gte.return_value.execute.return_value = MagicMock(
        data=[position]
    )
    # learning_ingested flag flip: update->eq->execute
    pp.update.return_value.eq.return_value.execute.return_value = MagicMock()

    po = MagicMock(name="paper_orders")
    # orders query: select->in_->eq->execute
    po.select.return_value.in_.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[order]
    )

    lfl = MagicMock(name="learning_feedback_loops")
    # order-id dedup query: select->eq->in_->execute (returns no existing rows)
    lfl.select.return_value.eq.return_value.in_.return_value.execute.return_value = MagicMock(
        data=[]
    )
    lfl.insert.return_value.execute.return_value = MagicMock()

    tables = {"paper_positions": pp, "paper_orders": po,
              "learning_feedback_loops": lfl}

    sb = MagicMock()
    sb.table.side_effect = lambda name: tables.get(name, MagicMock())
    return sb, pp, lfl


def _order(execution_mode, oid="order-new", symbol="NFLX"):
    return {
        "id": oid, "status": "filled", "side": "sell",
        "filled_qty": 6, "avg_fill_price": 4.79, "requested_price": 4.79,
        "position_id": "pos-new", "order_json": {"symbol": symbol},
        "suggestion_id": None, "execution_mode": execution_mode,
        "filled_at": "2026-06-16T16:45:00+00:00",
    }


def test_learning_ingested_marker_flips_on_success():
    """A2 — a successful ingest flips paper_positions.learning_ingested=True."""
    sb, pp, lfl = _mock_supabase_for_one_close(
        _order("internal_paper"), dict(_POSITION_NO_PORTFOLIO_ID)
    )

    result = asyncio.run(_ingest_paper_outcomes_for_user("user-1", sb, 7, "2026-06-16"))

    assert result["outcomes_created"] == 1
    pp.update.assert_called_once_with({"learning_ingested": True})
    pp.update.return_value.eq.assert_called_once_with("id", "pos-new")


def test_alpaca_live_labels_outcome_live_without_portfolio_id():
    """A1 (end-to-end) — an alpaca_live close yields is_paper=False even though
    the position dict carries NO portfolio_id (the exact regression that forced
    is_paper=True for every live broker fill)."""
    sb, pp, lfl = _mock_supabase_for_one_close(
        _order("alpaca_live", oid="order-live", symbol="SPY"),
        dict(_POSITION_NO_PORTFOLIO_ID),
    )

    result = asyncio.run(_ingest_paper_outcomes_for_user("user-1", sb, 7, "2026-06-16"))

    assert result["outcomes_created"] == 1
    inserted = lfl.insert.call_args[0][0]
    assert inserted["is_paper"] is False
    assert inserted["details_json"]["routing"] == "live"


def test_internal_paper_labels_outcome_paper():
    """A1 (end-to-end) — an internal_paper close yields is_paper=True."""
    sb, pp, lfl = _mock_supabase_for_one_close(
        _order("internal_paper", oid="order-shadow", symbol="QQQ"),
        dict(_POSITION_NO_PORTFOLIO_ID),
    )

    result = asyncio.run(_ingest_paper_outcomes_for_user("user-1", sb, 7, "2026-06-16"))

    assert result["outcomes_created"] == 1
    inserted = lfl.insert.call_args[0][0]
    assert inserted["is_paper"] is True
    assert inserted["details_json"]["routing"] == "shadow_or_internal"
