"""CLOSE_FILL_GAP sign fix (2026-07-08 audit finding) + false-ager stamp.

The live-fill call site abs()'d the broker's net combo fill against SIGNED
stage-stamped marks, corrupting every CREDIT close's gap_fraction (QQQ
07-07: stored 15.08, true ~1.42 — expected value verified independently:
(-1.64 - -1.98) / (-1.74 - -1.98) = 0.34/0.24 = 1.4167). Debit closes were
coincidentally unaffected (abs == negation-of-negative), which is why SOFI
06-30's 0.23 was correct and the bug hid until the first credit close.
"""

from pathlib import Path

import pytest

from packages.quantum.services.close_fill_gap import (
    broker_fill_to_mark_basis,
    compute_gap_fraction,
)

_QUANTUM = Path(__file__).parent.parent


class TestSignFix:
    def test_qqq_0707_credit_close_pin(self):
        """THE PIN — the live specimen: cross −1.98 / mid −1.74 / broker
        fill +1.64 (debit paid to close the credit condor) → ~1.4167."""
        fill = broker_fill_to_mark_basis(1.64)
        assert fill == -1.64
        gap = compute_gap_fraction(-1.98, -1.74, fill)
        assert gap == pytest.approx(1.4167, abs=1e-3)

    def test_qqq_0707_old_abs_value_is_the_corruption(self):
        """Regression shape: the abs'd fill against signed marks produces
        exactly the corrupt 15.08 the audit found — assert the old path's
        arithmetic so nobody 'simplifies' the negation away."""
        corrupt = compute_gap_fraction(-1.98, -1.74, abs(1.64))
        assert corrupt == pytest.approx(15.083, abs=1e-2)
        assert corrupt != pytest.approx(1.4167, abs=1e-3)

    def test_sofi_0630_debit_close_unchanged(self):
        """Opposite sign (debit structure closes for a CREDIT, broker
        reports negative): −1.36 → +1.36 vs +1.31/+1.525 → ~0.2326 — the
        docstring's historical example must keep its value, proving the fix
        is not credit-only and historical debit rows stay consistent."""
        fill = broker_fill_to_mark_basis(-1.36)
        assert fill == 1.36
        gap = compute_gap_fraction(1.31, 1.525, fill)
        assert gap == pytest.approx(0.2326, abs=1e-3)

    def test_none_and_garbage_safe(self):
        assert broker_fill_to_mark_basis(None) is None
        assert broker_fill_to_mark_basis("garbage") is None
        assert broker_fill_to_mark_basis("2.5") == -2.5


class TestProductionCallPathPins:
    def test_live_fill_site_uses_mark_basis_not_abs(self):
        """The 9a2cef1/#1126 rule: the fix must live at the PRODUCTION call
        site — the reconciler's live-fill emit."""
        src = (_QUANTUM / "brokers" / "alpaca_order_handler.py").read_text(
            encoding="utf-8"
        )
        assert "broker_fill_to_mark_basis" in src
        assert "abs(float(_cfg_fill))" not in src

    def test_monitor_part_b_stamps_last_marked_at(self):
        """False-ager fix: the q15min fresh-mark persist stamps
        last_marked_at alongside the mark it just wrote."""
        src = (
            _QUANTUM / "jobs" / "handlers" / "intraday_risk_monitor.py"
        ).read_text(encoding="utf-8")
        anchor = src.find('"current_mark": pos.get("current_mark")')
        assert anchor != -1
        assert '"last_marked_at"' in src[anchor : anchor + 900]
