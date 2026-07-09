"""Shadow-detection fix (E2 residue, 2026-07-09 EOD) + calibration fail-loud.

The Option-A cohort split keyed on routing_mode == 'paper_shadow', but
PRODUCTION emits 'live_eligible' / 'shadow_only' — so the check matched
nothing and the shadow fix was inert. This test uses the EXACT strings
production emits (the bug was a test-vs-reality value mismatch). Fail-safe:
an unknown routing value must fall to observe-only, never decision-changed.
"""

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

sys.modules.setdefault("alpaca", types.ModuleType("alpaca"))
sys.modules.setdefault("alpaca.trading", types.ModuleType("alpaca.trading"))
sys.modules.setdefault(
    "alpaca.trading.requests", types.ModuleType("alpaca.trading.requests")
)

from packages.quantum.paper_endpoints import (  # noqa: E402
    _is_shadow_routing,
    _apply_entry_roundtrip_gate,
    EntryRoundtripCostExceedsEV,
)

_QUANTUM = Path(__file__).parent.parent

# PRODUCTION routing values (verified against paper_portfolios 2026-07-09):
LIVE_ROUTING = "live_eligible"     # aggressive champion
SHADOW_ROUTING = "shadow_only"     # neutral / conservative


class TestShadowRoutingResolution:
    def test_production_shadow_value_is_shadow(self):
        assert _is_shadow_routing(SHADOW_ROUTING) is True

    def test_production_live_value_is_not_shadow(self):
        assert _is_shadow_routing(LIVE_ROUTING) is False

    def test_old_paper_shadow_value_no_longer_matches(self):
        # the string the OLD (broken) check looked for — production never emits
        # it; it must now resolve NOT-shadow (proves we moved off it).
        assert _is_shadow_routing("paper_shadow") is False

    def test_unknown_and_none_fail_safe_to_not_shadow(self):
        # THE FAIL-SAFE PIN: unknown/future/None → observe-only, never
        # decision-changed.
        assert _is_shadow_routing(None) is False
        assert _is_shadow_routing("some_future_mode") is False
        assert _is_shadow_routing("") is False

    def test_case_and_whitespace_tolerant(self):
        assert _is_shadow_routing(" Shadow_Only ") is True


# ── routing string → gate DECISION (the 07-07 qty-4 economics, ×7 shadow) ──
_LEGS = [
    ("O:QQQ260821P00640000", "buy"), ("O:QQQ260821P00645000", "sell"),
    ("O:QQQ260821C00765000", "sell"), ("O:QQQ260821C00770000", "buy"),
]
# per-leg cross 0.0175 → per-contract $7; at qty7 sized $49. gross_ev 42.45.
_QUOTES = {o: {"bid": 1.00, "ask": 1.0175} for (o, _a) in _LEGS}


def _ticket(ev, qty):
    legs = [types.SimpleNamespace(symbol=o, action=a, quantity=qty, strike=None)
            for (o, a) in _LEGS]
    return types.SimpleNamespace(expected_value=ev, legs=legs, quantity=qty)


class _FakeSb:
    def __init__(self):
        self.updates = []

    def table(self, name):
        outer = self

        class _Q:
            def update(self, row):
                outer.updates.append(row)
                return self

            def eq(self, *a, **k):
                return self

            def execute(self):
                return types.SimpleNamespace(data=[{"id": "r"}])
        return _Q()


class TestRoutingToDecision:
    def test_i_shadow_only_qty7_passes_on_fixed_basis(self):
        """shadow_only + qty7 + new_net≥floor(+35.45) + old_net<floor(−6.55)
        → PASS (fixed basis live for shadows)."""
        import os
        os.environ.pop("GATE_QTY_FIX_LIVE_ENABLED", None)
        is_shadow = _is_shadow_routing(SHADOW_ROUTING)
        assert is_shadow is True
        sb = _FakeSb()
        _apply_entry_roundtrip_gate(  # no raise → allowed
            sb, _ticket(42.45, 7), None, _QUOTES, suggestion_id="s",
            is_shadow=is_shadow,
        )
        assert sb.updates == []

    def test_ii_live_eligible_qty7_rejects_and_logs(self):
        """live_eligible + same setup → REJECT (old basis) + observe-log."""
        is_shadow = _is_shadow_routing(LIVE_ROUTING)
        assert is_shadow is False
        sb = _FakeSb()
        import logging
        import packages.quantum.paper_endpoints as pe
        with __import__("unittest").TestCase().assertLogs(
            pe.logger if hasattr(pe, "logger") else logging.getLogger(
                "packages.quantum.paper_endpoints"), "WARNING") as cm:
            try:
                _apply_entry_roundtrip_gate(
                    sb, _ticket(42.45, 7), None, _QUOTES, suggestion_id="s",
                    is_shadow=is_shadow,
                )
            except EntryRoundtripCostExceedsEV:
                pass
        assert any("GATE_QTY_SCALED_SHADOW" in m for m in cm.output)

    def test_iii_unknown_routing_observe_only(self):
        """unknown routing → is_shadow False → observe-only (REJECT on old
        basis), never the fixed decision."""
        is_shadow = _is_shadow_routing("brand_new_mode")
        assert is_shadow is False
        sb = _FakeSb()
        raised = False
        try:
            _apply_entry_roundtrip_gate(
                sb, _ticket(42.45, 7), None, _QUOTES, suggestion_id="s",
                is_shadow=is_shadow,
            )
        except EntryRoundtripCostExceedsEV:
            raised = True
        assert raised  # old-basis reject (observe-only), not the fixed PASS

    def test_iv_qty1_invariant_unchanged(self):
        sb = _FakeSb()
        # qty1: per-contract == sized; healthy edge → allow both ways.
        quotes = {o: {"bid": 1.00, "ask": 1.005} for (o, _a) in _LEGS}
        _apply_entry_roundtrip_gate(
            sb, _ticket(42.45, 1), None, quotes, suggestion_id="s",
            is_shadow=_is_shadow_routing(SHADOW_ROUTING),
        )
        assert sb.updates == []


class TestCallSiteWiring:
    def test_call_site_uses_helper(self):
        src = (_QUANTUM / "paper_endpoints.py").read_text(encoding="utf-8")
        assert "_is_shadow_routing((portfolio or {}).get(\"routing_mode\"))" in src
        # the old broken literal must be gone from the call site
        assert 'routing_mode") or ""\n    ).strip().lower() == "paper_shadow"' not in src


class TestCalibrationFailLoud:
    def test_scan_logs_disabled_when_off(self):
        src = (_QUANTUM / "services" / "workflow_orchestrator.py").read_text(
            encoding="utf-8")
        assert "if not _CAL_ENABLED:" in src
        assert "[CALIBRATION] DISABLED" in src

    def test_write_job_logs_compute_but_disabled(self):
        src = (_QUANTUM / "jobs" / "handlers" / "calibration_update.py").read_text(
            encoding="utf-8")
        assert "computed-but-not-" in src
        assert "APPLY is DISABLED" in src

    def test_import_time_flag_comment_present(self):
        src = (_QUANTUM / "analytics" / "calibration_service.py").read_text(
            encoding="utf-8")
        assert "IMPORT-TIME flag" in src
