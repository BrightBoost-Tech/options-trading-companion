"""P1-C (2026-07-02) — MTM mark-WRITE corroboration.

The last phantom-mark seam: refresh_marks + the monitor's Part-B persist made
raw mid marks DURABLE, and governance (policy-lab drawdown → champion
auto-rollback; go-live checkpoints) read them as facts. Contract under pin:

- ADDITIVE: current_mark / unrealized_pl persist the raw mid byte-identically
  (fast paths and the close-limit read never see a changed field);
- corroborated fields ride alongside, computed from the SAME cycle's
  pre-fetched snapshots (the helper never raises, never fabricates — dark or
  incomplete quotes persist NULLs + an 'uncorroborated' stamp);
- governance prefers corroborated: the 07-01 SOFI evidence fixture (raw
  +196.52 vs corroborated −1,044.48) must no longer produce a phantom
  cohort P&L / max_drawdown input;
- OUTPUT_FRESHNESS watches paper_positions.last_marked_at (NULLS LAST).
"""

from unittest.mock import MagicMock, patch

from packages.quantum.analytics.exit_mark_corroboration import (
    corroborated_mark_fields,
)
from packages.quantum.policy_lab.evaluator import _position_unrealized
from packages.quantum.services.ops_health_service import OUTPUT_FRESHNESS


# Two-leg debit spread, 1 contract: long leg + short leg with live two-sided
# quotes. Executable side: sell long at bid (1.20), buy short at ask (0.40)
# → achievable_close = 0.80/spread.
POS = {
    "id": "p1",
    "quantity": 1,
    "avg_entry_price": 1.00,
    "legs": [
        {"occ_symbol": "O:XYZ260717C00050000", "side": "buy", "quantity": 1},
        {"occ_symbol": "O:XYZ260717C00055000", "side": "sell", "quantity": 1},
    ],
}

FULL_SNAPS = {
    "O:XYZ260717C00050000": {"quote": {"bid": 1.20, "ask": 1.30, "last": 1.25}},
    "O:XYZ260717C00055000": {"quote": {"bid": 0.30, "ask": 0.40, "last": 0.35}},
}

DARK_SNAPS = {
    "O:XYZ260717C00050000": {"quote": {"bid": 1.20, "ask": 1.30, "last": 1.25}},
    "O:XYZ260717C00055000": {"quote": {"bid": None, "ask": None, "last": None}},
}


class TestCorroboratedMarkFields:
    def test_happy_path_computes_from_cached_snapshots(self):
        calls = []

        def snapshot_fn(occs):
            calls.append(list(occs))
            return FULL_SNAPS

        out = corroborated_mark_fields(POS, snapshot_fn=snapshot_fn, raw_mark=1.10)
        assert out["mark_corroborated"] is not None
        assert abs(out["mark_corroborated"] - 0.80) < 1e-9
        assert out["unrealized_pl_corroborated"] is not None
        q = out["mark_quality"]
        assert q["basis"] == "corroborated"
        assert q["quote_complete"] is True
        # divergence normalized by the achievable PRICE (#1034 convention):
        # |1.10 - 0.80| / 0.80 = 0.375
        assert abs(q["divergence_frac"] - 0.375) < 1e-6
        assert "corroborated_at" in q
        assert len(calls) == 1  # exactly one pass over the cached dict

    def test_dark_leg_persists_nulls_never_fabricates(self):
        out = corroborated_mark_fields(
            POS, snapshot_fn=lambda occs: DARK_SNAPS, raw_mark=1.10
        )
        assert out["mark_corroborated"] is None
        assert out["unrealized_pl_corroborated"] is None
        assert out["mark_quality"]["basis"] == "uncorroborated"
        assert "divergence_frac" not in out["mark_quality"]

    def test_snapshot_failure_never_raises(self):
        def boom(occs):
            raise RuntimeError("feed down")

        out = corroborated_mark_fields(POS, snapshot_fn=boom, raw_mark=1.10)
        assert out["mark_corroborated"] is None
        assert out["unrealized_pl_corroborated"] is None
        assert out["mark_quality"]["basis"] == "uncorroborated"
        assert out["mark_quality"]["reason"].startswith("estimate_error:")


class TestRawFieldsByteIdentical:
    """THE LOAD-BEARING PIN: this change is persistence-ADDITIVE. The raw
    current_mark / unrealized_pl values in both write payloads are computed
    by exactly the same code as before; the corroborated fields only ride
    alongside. Fast loss paths (envelopes/stops/monitor triggers) and the
    close-limit read consume the raw fields or in-memory marks — neither is
    changed by this PR."""

    def test_mtm_service_payload_carries_raw_and_corroborated(self):
        import inspect
        from packages.quantum.services import paper_mark_to_market_service as svc

        src = inspect.getsource(svc.PaperMarkToMarketService.refresh_marks)
        # Raw fields persist exactly as computed by finalize_mark…
        assert '"current_mark": per_contract_mark' in src
        assert '"unrealized_pl": unrealized' in src
        # …with the corroborated fields additive alongside.
        assert "corroborated_mark_fields(" in src

    def test_monitor_part_b_payload_carries_raw_and_corroborated(self):
        import inspect
        from packages.quantum.jobs.handlers import intraday_risk_monitor as mon

        src = inspect.getsource(mon.IntradayRiskMonitor._refresh_marks)
        assert '"current_mark": pos.get("current_mark")' in src
        assert '"unrealized_pl": pos.get("unrealized_pl")' in src
        assert "corroborated_mark_fields(" in src

    def test_exit_evaluator_close_limit_still_reads_raw_current_mark(self):
        # The close-limit seam must keep reading the RAW column — replacing
        # it was rejected precisely because this is a live close path.
        import inspect
        from packages.quantum.services import paper_exit_evaluator as pee

        src = inspect.getsource(pee)
        assert "current_mark" in src
        assert "mark_corroborated" not in src


class TestGovernancePrefersCorroborated:
    def test_sofi_phantom_fixture_champion_rollback_input(self):
        """14d evidence fixture: 07-01 SOFI persisted raw +196.52 thirty
        minutes before the corroborated close realized −1,044.48. The cohort
        unrealized input must read the corroborated side."""
        phantom = {"unrealized_pl": 196.52, "unrealized_pl_corroborated": -1044.48}
        assert _position_unrealized(phantom) == -1044.48

    def test_null_corroboration_falls_back_to_raw(self):
        assert _position_unrealized(
            {"unrealized_pl": -42.0, "unrealized_pl_corroborated": None}
        ) == -42.0
        assert _position_unrealized({"unrealized_pl": None}) == 0.0

    def test_zero_corroborated_is_honored_not_treated_as_missing(self):
        assert _position_unrealized(
            {"unrealized_pl": 50.0, "unrealized_pl_corroborated": 0.0}
        ) == 0.0

    def test_policy_lab_selects_corroborated_column(self):
        import inspect
        from packages.quantum.policy_lab import evaluator

        src = inspect.getsource(evaluator._compute_cohort_metrics)
        assert "unrealized_pl_corroborated" in src

    def test_go_live_prefers_corroborated(self):
        from packages.quantum.services.go_live_validation_service import (
            GoLiveValidationService,
        )

        svc = GoLiveValidationService.__new__(GoLiveValidationService)
        svc.supabase = MagicMock()
        rows = [
            {"unrealized_pl": 196.52, "unrealized_pl_corroborated": -1044.48},
            {"unrealized_pl": -42.0, "unrealized_pl_corroborated": None},
        ]
        (
            svc.supabase.table.return_value
            .select.return_value
            .in_.return_value
            .neq.return_value
            .execute.return_value
        ) = MagicMock(data=rows)
        with patch.object(
            GoLiveValidationService, "_get_paper_portfolio_ids", return_value=["pf1"]
        ):
            total = svc._get_current_unrealized_total("u1")
        assert total == -1044.48 + -42.0


class TestOutputFreshnessRegistry:
    def test_mark_refresh_registered(self):
        entries = {(t, c) for t, c, _ in OUTPUT_FRESHNESS}
        assert ("paper_positions", "last_marked_at") in entries

    def test_generic_query_orders_nulls_last(self):
        import inspect
        from packages.quantum.services import ops_health_service as ohs

        src = inspect.getsource(ohs.get_output_freshness)
        assert "nullsfirst=False" in src
