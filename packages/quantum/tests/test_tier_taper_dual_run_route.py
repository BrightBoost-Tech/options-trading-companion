"""Route-level DARK dual-run proof for the tier taper.

Two guarantees, both driven through REAL production functions (no
source-string assertions — per CLAUDE.md a wiring test must EXECUTE the
route and assert on OUTPUT):

1. BYTE-IDENTICAL LIVE PATH — the observe-only dual-run cannot perturb the
   production sizing chain. We drive the exact seam ``run_midday_cycle``
   uses (PortfolioAllocator.allocate → attach ``_allocator_allocated_budget``
   → SmallAccountCompounder.calculate_variable_sizing with
   ``allocation_hint``) and assert the sizing output is identical whether or
   not ``tier_taper.observe`` is interleaved, and that ``observe`` mutates
   none of the candidate dicts.

2. PAYLOAD EMITTED ADDITIVELY — ``_build_cycle_metadata`` (the real sink
   function) is byte-identical WITHOUT the taper kwarg (no ``tier_taper``
   key) and carries the well-formed payload WITH it.
"""
import copy

import pytest

from packages.quantum.services.analytics import tier_taper as tt
from packages.quantum.services.analytics.small_account_compounder import (
    SmallAccountCompounder,
)
from packages.quantum.services.portfolio_allocator import PortfolioAllocator
from packages.quantum.services.workflow_orchestrator import (
    _build_cycle_metadata,
)


def _candidates():
    return [
        {"symbol": "SPY", "score": 92, "max_loss": 120.0},
        {"symbol": "QQQ", "score": 84, "max_loss": 95.0},
        {"symbol": "IWM", "score": 77, "max_loss": 80.0},
    ]


def _run_sizing_chain(candidates, equity, regime):
    """Reproduce the run_midday_cycle small-tier sizing seam EXACTLY.

    Mirrors workflow_orchestrator.run_midday_cycle lines ~2854 (allocator)
    and ~3291 (calculate_variable_sizing with allocation_hint). Returns the
    per-candidate risk_budget list — the live sizing OUTPUT to byte-pin.
    """
    tier = SmallAccountCompounder.get_tier(equity)
    allocator = PortfolioAllocator()
    results = allocator.allocate(
        candidates=candidates, total_equity=equity, regime=regime,
        open_positions=[],
    )
    for r in results:
        r.candidate["_allocator_allocated_budget"] = r.allocated_budget

    budgets = []
    for cand in candidates:
        sizing = SmallAccountCompounder.calculate_variable_sizing(
            candidate=cand, capital=equity, tier=tier, regime=regime,
            compounding=False,
            allocation_hint=cand.get("_allocator_allocated_budget"),
        )
        budgets.append(sizing["risk_budget"])
    return budgets


class TestLivePathByteIdentical:
    def test_sizing_identical_with_and_without_observe(self):
        equity, regime = 1500.0, "normal"

        cands_a = _candidates()
        baseline = _run_sizing_chain(cands_a, equity, regime)

        # Same chain, but interleave the DARK observe call the way the
        # wire-in does (before the sizing loop, per-cycle).
        cands_b = _candidates()
        _payload = tt.observe(equity, regime, previous_state=None)
        assert isinstance(_payload, dict)  # the dark computation ran
        with_observe = _run_sizing_chain(cands_b, equity, regime)

        assert baseline == with_observe, (
            "DARK dual-run changed the live sizing output — not byte-identical"
        )

    def test_observe_does_not_mutate_candidates(self):
        cands = _candidates()
        snapshot = copy.deepcopy(cands)
        tt.observe(1500.0, "normal", previous_state=None)
        assert cands == snapshot  # observe takes primitives; no candidate touch

    @pytest.mark.parametrize("equity", [800.0, 999.0, 1001.0, 1500.0])
    def test_byte_pin_across_equities(self, equity):
        # Micro ($800/$999) uses no allocator; small ($1001/$1500) does.
        base = _run_sizing_chain(_candidates(), equity, "normal")
        tt.observe(equity, "normal", previous_state=None)
        again = _run_sizing_chain(_candidates(), equity, "normal")
        assert base == again


class TestPayloadEmittedAdditively:
    def test_metadata_byte_identical_without_taper(self):
        kwargs = dict(
            exit_reason=None, tier="small", regime="normal",
            deployable_capital=1050.0, open_position_count=0,
            available_envelope_dollars=100.0,
        )
        meta = _build_cycle_metadata(**kwargs)
        assert "tier_taper" not in meta  # additive: absent when not supplied

    def test_metadata_carries_payload_when_supplied(self):
        payload = tt.observe(1050.0, "normal", previous_state=None)
        meta = _build_cycle_metadata(
            exit_reason=None, tier="small", regime="normal",
            deployable_capital=1050.0, open_position_count=0,
            available_envelope_dollars=100.0,
            tier_taper=payload,
        )
        assert meta["tier_taper"] is payload
        # Well-formed: owner-required dual-run keys present.
        for k in ("current", "proposed", "difference", "verdict",
                  "engine_version", "previous_tier_state",
                  "hysteresis_decision"):
            assert k in meta["tier_taper"]
        assert meta["tier_taper"]["engine_version"] == tt.ENGINE_VERSION

    def test_none_taper_kwarg_is_still_additive_absent(self):
        # The orchestrator passes tier_taper=None on the fail-path; that must
        # not inject a null key (keeps legacy readers byte-identical).
        meta = _build_cycle_metadata(
            exit_reason="scanner_failed", tier="micro", regime="normal",
            deployable_capital=800.0, open_position_count=0,
            available_envelope_dollars=None, tier_taper=None,
        )
        assert "tier_taper" not in meta


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
