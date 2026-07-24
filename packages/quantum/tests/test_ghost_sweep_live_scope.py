"""Ghost-sweep live-scoping (2026-07-02, ledgered P2→P1).

RECON RESULT that shaped this fix: all 58 ghost_position warns 06-30→07-01
traced to ONE position — the neutral-cohort shadow SOFI
(08002beb / portfolio ed31cc5f, routing_mode=shadow_only) — firing every
sync cycle from 15 min after it opened until seconds before its force-close.
The sweep fired CORRECTLY per its code (DB-open position, no broker legs)
but SPURIOUSLY per intent: a shadow position never exists at the broker BY
DESIGN, so it can never be a broker desync. Dedup/rate-limiting was
considered and REJECTED: it would still emit one false "desync" per shadow
per window and would mute the nag-urgency of a REAL live ghost (H10: ghost
alerts are urgent). Scoping is the semantic fix.

Pins:
- shadow-only portfolios → sweep returns no_live_routed_portfolios, writes
  ZERO alerts (the 08002beb shape can never fire again)
- a live-routed position missing at the broker → STILL flagged (the control
  this sweep exists for is intact)
- scope-query failure → FAIL-OPEN to the legacy unscoped sweep (noisy beats
  blind for a detector) with a warning — never a silently narrower sweep
- source: the sweep routes through the #1014 canonical
  position_scope.live_routed_portfolio_ids
"""

import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

# Mirror test_ghost_position_rescue.py module stubs (alpaca-py not in CI)
from packages.quantum.tests._alpaca_stub import ensure_alpaca as _ensure_alpaca

_ensure_alpaca()

from packages.quantum.brokers.alpaca_order_handler import ghost_position_sweep  # noqa: E402

USER_ID = "test-user-ghost-scope"
SCOPE_TARGET = "packages.quantum.risk.position_scope.live_routed_portfolio_ids"

_OLD = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()


def _shadow_sofi_position():
    """The 08002beb incident shape: DB-open shadow spread, no broker legs."""
    return {
        "id": "08002beb-cb92-4e25-aa3f-b7e8777ddc27",
        "symbol": "SOFI",
        "legs": [
            {"symbol": "O:SOFI260807C00017000"},
            {"symbol": "O:SOFI260807C00020500"},
        ],
        "created_at": _OLD,
        "quantity": 17,
    }


def _chain_mock(table_responses, insert_sink):
    """Minimal fluent supabase mock (mirrors the stale-review test's)."""
    mock_supabase = MagicMock()

    def table_side_effect(name):
        chain = MagicMock()
        chain.execute.side_effect = lambda: MagicMock(
            data=table_responses.get(name, [])
        )
        for method in ("select", "eq", "neq", "gte", "lte", "lt", "gt",
                       "in_", "order", "limit", "filter"):
            getattr(chain, method).return_value = chain

        def capture_insert(payload):
            insert_sink.append((name, payload))
            return chain

        chain.insert.side_effect = capture_insert
        return chain

    mock_supabase.table.side_effect = table_side_effect
    return mock_supabase


def _alpaca_with(positions):
    alpaca = MagicMock()
    alpaca.get_option_positions.return_value = positions
    return alpaca


class TestShadowPositionsOutOfScope(unittest.TestCase):
    def test_shadow_only_user_sweeps_nothing(self):
        """The 58-warn incident shape: an open shadow with no broker legs
        must produce ZERO ghost alerts once no live-routed portfolios
        exist for the user."""
        inserts = []
        supabase = _chain_mock(
            {"paper_positions": [_shadow_sofi_position()]}, inserts
        )
        with patch(SCOPE_TARGET, return_value=[]):
            result = ghost_position_sweep(_alpaca_with([]), supabase, USER_ID)
        self.assertEqual(result["status"], "no_live_routed_portfolios")
        self.assertEqual(result["ghost_count"], 0)
        self.assertEqual(inserts, [])


class TestLiveGhostStillCaught(unittest.TestCase):
    def test_live_routed_ghost_flags(self):
        """Control intact: a LIVE-routed DB-open position with no matching
        broker legs still writes the ghost_position warn."""
        inserts = []
        live_pos = dict(_shadow_sofi_position(), id="live-pos-1", quantity=5)
        supabase = _chain_mock(
            {
                "paper_positions": [live_pos],
                "paper_orders": [],
                "risk_alerts": [],
            },
            inserts,
        )
        with patch(SCOPE_TARGET, return_value=["live-portfolio-1"]):
            result = ghost_position_sweep(_alpaca_with([]), supabase, USER_ID)
        self.assertEqual(result.get("ghost_count"), 1)
        ghost_inserts = [
            p for (t, p) in inserts
            if t == "risk_alerts" and p.get("alert_type") == "ghost_position"
        ]
        self.assertEqual(len(ghost_inserts), 1)
        self.assertEqual(ghost_inserts[0]["position_id"], "live-pos-1")

    def test_broker_matched_live_position_not_flagged(self):
        """A live position whose legs ARE at the broker is not a ghost."""
        inserts = []
        live_pos = dict(_shadow_sofi_position(), id="live-pos-2")
        supabase = _chain_mock(
            {
                "paper_positions": [live_pos],
                "paper_orders": [],
                "risk_alerts": [],
            },
            inserts,
        )
        broker_positions = [
            {"symbol": "O:SOFI260807C00017000"},
            {"symbol": "O:SOFI260807C00020500"},
        ]
        with patch(SCOPE_TARGET, return_value=["live-portfolio-1"]):
            result = ghost_position_sweep(
                _alpaca_with(broker_positions), supabase, USER_ID
            )
        self.assertEqual(result.get("ghost_count"), 0)
        self.assertEqual(
            [p for (t, p) in inserts if t == "risk_alerts"], []
        )


class TestScopeFailureFailsOpen(unittest.TestCase):
    def test_scope_query_failure_falls_back_to_unscoped(self):
        """DETECTOR polarity: a scope-query failure must NOT narrow the
        sweep — it falls back to the legacy all-portfolios query (noisy
        beats blind) and still flags the ghost."""
        inserts = []
        live_pos = dict(_shadow_sofi_position(), id="fallback-pos-1")
        supabase = _chain_mock(
            {
                "paper_portfolios": [{"id": "portfolio-any"}],
                "paper_positions": [live_pos],
                "paper_orders": [],
                "risk_alerts": [],
            },
            inserts,
        )
        with patch(SCOPE_TARGET, side_effect=RuntimeError("scope query down")):
            with self.assertLogs(
                "packages.quantum.brokers.alpaca_order_handler",
                level="WARNING",
            ) as cm:
                result = ghost_position_sweep(
                    _alpaca_with([]), supabase, USER_ID
                )
        self.assertEqual(result.get("ghost_count"), 1)
        joined = "\n".join(cm.output)
        self.assertIn("falling back to UNSCOPED sweep", joined)


class TestSourceWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = (
            Path(__file__).parent.parent / "brokers" / "alpaca_order_handler.py"
        ).read_text(encoding="utf-8")

    def test_uses_canonical_scope(self):
        self.assertIn(
            "from packages.quantum.risk.position_scope import live_routed_portfolio_ids",
            self.src,
        )
        self.assertIn("no_live_routed_portfolios", self.src)

    def test_ghost_half_keeps_nag_cadence(self):
        """Deliberate: NO dedup added to the ghost half — a REAL live ghost
        should nag every sync cycle (H10 urgency). Only the stale-review
        half carries the 1-hour idempotency gate."""
        self.assertNotIn("ghost_dedup", self.src)


if __name__ == "__main__":
    unittest.main()
