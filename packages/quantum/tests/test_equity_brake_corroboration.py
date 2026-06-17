"""
Tests for the v5 phantom-mark-safe daily/weekly equity brake (2026-06-17 incident).

The realized-blind brake (#1058) fed the loss envelope the BROKER equity delta,
which for an open multi-leg position carries the broker's per-leg last-trade
phantom marks. On 2026-06-17 a phantom broker unrealized of -285.52 force-closed
the live MARA whose EXECUTABLE close realized -15.00 (settled -16.02 next cycle).

The fix (equity_state): brake on realized (DB-authoritative, trusted, UN-GATED) +
executable-corroborated unrealized (#1034), exclude+flag the uncorroborated, and a
clean %-denominator. Realized protection (#1058/06-11) is preserved.

The envelope assertions hit check_loss_envelopes directly (the loss feeder) so the
test isolates the daily/weekly decision from greeks/concentration/stress.
"""
from unittest.mock import patch, MagicMock

from packages.quantum.services import equity_state
from packages.quantum.risk.risk_envelope import check_loss_envelopes, EnvelopeConfig

_EMC = "packages.quantum.analytics.exit_mark_corroboration.executable_close_estimate"


def _est(impl, complete=True):
    """An executable_close_estimate-shaped return."""
    return {
        "achievable_close": None,
        "achievable_implied_pl": impl,
        "quote_complete": complete,
        "legs_quotes": {},
    }


def _pos(pid, sym="MARA"):
    # Shape is irrelevant to corroborated_unrealized (estimate is patched) and
    # minimal-but-safe for check_loss_envelopes (_pos_field defaults).
    return {"id": pid, "symbol": sym}


def _loss_check(daily_pnl, equity, positions, weekly_pnl=0.0):
    cfg = EnvelopeConfig.from_env()
    return check_loss_envelopes(equity, daily_pnl, weekly_pnl, positions, cfg)


# ── corroborated_unrealized ─────────────────────────────────────────

class TestCorroboratedUnrealized:
    def test_all_corroborated_sums(self):
        with patch(_EMC) as m:
            m.side_effect = [_est(-15.0), _est(50.0)]
            total, unc = equity_state.corroborated_unrealized([_pos("a"), _pos("b", "NFLX")])
        assert round(total, 2) == 35.0
        assert unc == []

    def test_incomplete_quote_excluded_and_flagged(self):
        with patch(_EMC) as m:
            m.side_effect = [_est(-15.0), _est(None, complete=False)]
            total, unc = equity_state.corroborated_unrealized([_pos("a"), _pos("b", "NFLX")])
        assert round(total, 2) == -15.0
        assert len(unc) == 1
        assert unc[0]["position_id"] == "b" and unc[0]["reason"] == "quote_incomplete"

    def test_estimate_raises_excluded_not_crash(self):
        with patch(_EMC) as m:
            m.side_effect = RuntimeError("dark quotes")
            total, unc = equity_state.corroborated_unrealized([_pos("a")])
        assert total == 0.0
        assert len(unc) == 1 and unc[0]["reason"].startswith("estimate_error")


# ── corroborated_daily_pnl + the loss envelope decision ─────────────

class TestPhantomSafeBrake:
    def test_this_incident_no_false_force_close(self):
        """realized=0, open MARA executable -15 (broker phantom was -285) →
        daily=-15 on a clean denom → NO daily force_close."""
        with patch(_EMC) as m:
            m.return_value = _est(-15.0)
            daily, unc = equity_state.corroborated_daily_pnl(0.0, [_pos("mara")])
        assert round(daily, 2) == -15.0 and unc == []
        equity_clean = 2150.88 + daily  # last_equity + daily_brake_pnl
        viol, fci, _ = _loss_check(daily, equity_clean, [_pos("mara")])
        assert not any(v.envelope == "loss_daily" for v in viol)  # -0.7% > limit
        assert fci == []

    def test_realized_protection_preserved(self):
        """A REAL realized loss trips the brake with no corroboration gate."""
        with patch(_EMC) as m:
            m.return_value = _est(-15.0)
            daily, _ = equity_state.corroborated_daily_pnl(-200.0, [_pos("p", "SPY")])
        assert round(daily, 2) == -215.0
        equity_clean = 2150.88 + daily
        viol, fci, _ = _loss_check(daily, equity_clean, [_pos("p", "SPY")])
        assert any(v.envelope == "loss_daily" for v in viol)  # ~-11% < limit
        assert "p" in fci

    def test_realized_loss_no_open_positions_trips(self):
        """Realized loss after the book emptied → trips, no corroboration touched."""
        daily, unc = equity_state.corroborated_daily_pnl(-200.0, [])
        assert daily == -200.0 and unc == []
        equity_clean = 2150.88 + daily
        viol, _fci, _ = _loss_check(daily, equity_clean, [])
        assert any(v.envelope == "loss_daily" for v in viol)

    def test_dark_crash_excludes_all_no_false_close(self):
        """All positions non-corroborated → unrealized excluded, flagged, daily=
        realized(0) → no force_close (the per-position stop is the backstop)."""
        with patch(_EMC) as m:
            m.return_value = _est(None, complete=False)
            daily, unc = equity_state.corroborated_daily_pnl(0.0, [_pos("a"), _pos("b")])
        assert daily == 0.0 and len(unc) == 2
        viol, fci, _ = _loss_check(daily, 2150.88, [_pos("a"), _pos("b")])
        assert not any(v.envelope == "loss_daily" for v in viol)
        assert fci == []

    def test_true_positive_executable_loss_trips(self):
        """The fix must NOT blind the brake to a REAL executable loss."""
        with patch(_EMC) as m:
            m.return_value = _est(-300.0)
            daily, _ = equity_state.corroborated_daily_pnl(0.0, [_pos("p")])
        assert round(daily, 2) == -300.0
        equity_clean = 2150.88 + daily  # ~1851; -300/1851 ≈ -16%
        viol, fci, _ = _loss_check(daily, equity_clean, [_pos("p")])
        assert any(v.envelope == "loss_daily" for v in viol)
        assert "p" in fci


# ── weekly mirror ───────────────────────────────────────────────────

class TestWeeklyMirror:
    def test_weekly_realized_plus_corroborated_unrealized_trips(self):
        with patch(_EMC) as m:
            m.return_value = _est(-30.0)  # open executable unrealized -30
            unreal, _ = equity_state.corroborated_unrealized([_pos("p", "X")])
        weekly = -400.0 + unreal  # realized_week + shared unrealized = -430
        assert round(weekly, 2) == -430.0
        viol, fci, _ = _loss_check(0.0, 2150.88, [_pos("p", "X")], weekly_pnl=weekly)
        assert any(v.envelope == "loss_weekly" for v in viol)  # -20% < limit
        assert "p" in fci


# ── realized_pnl_since (DB-authoritative realized) ──────────────────

class TestRealizedPnlSince:
    def test_sums_closed_live(self):
        sb = MagicMock()
        (sb.table.return_value.select.return_value.eq.return_value.eq.return_value
         .gte.return_value.in_.return_value.execute.return_value) = MagicMock(
            data=[{"realized_pl": -15.0}, {"realized_pl": -200.0}]
        )
        out = equity_state.realized_pnl_since(sb, "u", ["port-1"], "2026-06-17T00:00:00Z")
        assert round(out, 2) == -215.0

    def test_empty_portfolio_ids_is_zero_not_none(self):
        assert equity_state.realized_pnl_since(MagicMock(), "u", [], "x") == 0.0

    def test_query_error_returns_none_for_fail_safe(self):
        sb = MagicMock()
        sb.table.side_effect = RuntimeError("db down")
        assert equity_state.realized_pnl_since(sb, "u", ["p"], "x") is None


# ── reconcile_realized (H10 cross-check, flag-only) ─────────────────

class TestReconcileRealized:
    def test_divergent_flags(self):
        with patch.object(equity_state, "get_alpaca_daily_pnl", return_value=-285.0), \
             patch.object(equity_state, "broker_unrealized_sum", return_value=-100.0):
            r = equity_state.reconcile_realized("u", 0.0, threshold=25.0)
        # broker-implied realized = -285 - (-100) = -185; |−185 − 0| = 185 > 25
        assert r["divergent"] is True
        assert r["broker_implied_realized"] == -185.0

    def test_incident_case_not_divergent(self):
        # 06-17: equity_delta -285, broker_unrealized -285 → implied 0 == DB 0.
        with patch.object(equity_state, "get_alpaca_daily_pnl", return_value=-285.0), \
             patch.object(equity_state, "broker_unrealized_sum", return_value=-285.0):
            r = equity_state.reconcile_realized("u", 0.0, threshold=25.0)
        assert r["divergent"] is False

    def test_unavailable_inputs_return_none(self):
        with patch.object(equity_state, "get_alpaca_daily_pnl", return_value=None), \
             patch.object(equity_state, "broker_unrealized_sum", return_value=-1.0):
            assert equity_state.reconcile_realized("u", 0.0) is None
        # missing DB realized → None (never reconcile against an unknown)
        assert equity_state.reconcile_realized("u", None) is None
