"""
Regression tests for two SILENT fail-OPEN loss-protection defects.

(1) policy_lab.config.load_cohort_configs returned the LOOSE DEFAULT_CONFIGS on
    BOTH a legitimate empty seed AND a DB/load FAULT. A fault therefore silently
    WIDENED the live champion's stop (aggressive 0.65 vs live ~0.30, 2.17x) with
    zero signal, indistinguishable from a first-boot empty seed.
    Fix: distinguish fault from empty seed. On a fault, fail SAFE to the
    last-known-good cache (live-tight) or, absent one, TIGHT_FALLBACK
    (stops <= 0.30) — never the loose DEFAULT_CONFIGS — and log [CONFIG_FAULT].
    The legitimate empty-seed baseline is preserved (NO fault log).

(2) paper_exit_evaluator._check_stop_loss returned False ("no stop") when
    max_credit was None/0 — silently disabling the per-position stop.
    Fix: recover an avg_entry_price-derived cost basis (protection preserved,
    no spurious close) or, with no basis at all, fire protectively only on a
    confirmed loss; log [STOP_LOSS_DATA_FAULT]. The healthy (max_credit present)
    path is unchanged.
"""
import logging
from types import SimpleNamespace

import pytest

from packages.quantum.policy_lab import config as cfg
from packages.quantum.services import paper_exit_evaluator as pxe


# ── Minimal fake supabase fluent chain ───────────────────────────────
class _FakeQuery:
    def __init__(self, rows, raise_exc):
        self._rows = rows
        self._raise = raise_exc

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def execute(self):
        if self._raise is not None:
            raise self._raise
        return SimpleNamespace(data=self._rows)


class _FakeSupabase:
    """raise_exc set → .execute() raises, simulating a DB/load FAULT."""

    def __init__(self, rows=None, raise_exc=None):
        self._rows = rows
        self._raise = raise_exc

    def table(self, *a, **k):
        return _FakeQuery(self._rows, self._raise)


@pytest.fixture(autouse=True)
def _reset_cache():
    # The module-level last-known-good cache leaks across tests; isolate it.
    cfg._LAST_KNOWN_GOOD = None
    yield
    cfg._LAST_KNOWN_GOOD = None


# ── (1) config.py — fault vs empty-seed distinction ──────────────────

def test_load_fault_no_cache_uses_tight_fallback(caplog):
    """DB load RAISES, no prior success → TIGHT_FALLBACK (aggressive 0.30),
    NEVER the loose DEFAULT_CONFIGS 0.65, and a loud [CONFIG_FAULT] is logged."""
    supabase = _FakeSupabase(raise_exc=RuntimeError("db down"))
    with caplog.at_level(logging.ERROR, logger="packages.quantum.policy_lab.config"):
        configs = cfg.load_cohort_configs("user-1", supabase)

    assert configs["aggressive"].stop_loss_pct <= 0.30  # tight, fail-SAFE
    assert configs["aggressive"].stop_loss_pct != 0.65  # NOT the loose default
    assert any("[CONFIG_FAULT]" in r.getMessage() for r in caplog.records)


def test_load_fault_after_success_uses_cached_tight_values(caplog):
    """A successful load seeds the cache with live-tight values; a later FAULT
    returns the CACHED tight value (0.20), not the loose DEFAULT_CONFIGS."""
    good = _FakeSupabase(rows=[
        {"cohort_name": "aggressive", "policy_config": {"stop_loss_pct": 0.20}},
    ])
    seeded = cfg.load_cohort_configs("user-1", good)
    assert seeded["aggressive"].stop_loss_pct == 0.20  # sanity: live value loaded

    bad = _FakeSupabase(raise_exc=RuntimeError("db blip"))
    with caplog.at_level(logging.ERROR, logger="packages.quantum.policy_lab.config"):
        configs = cfg.load_cohort_configs("user-1", bad)

    assert configs["aggressive"].stop_loss_pct == 0.20  # cached live-tight, not 0.65
    assert any("[CONFIG_FAULT]" in r.getMessage() for r in caplog.records)


def test_empty_seed_returns_baseline_without_fault_marker(caplog):
    """Query SUCCEEDS with zero rows → legit empty-seed baseline (DEFAULT_CONFIGS,
    aggressive 0.65) and NO fault marker — DISTINGUISHABLE from the fault path."""
    supabase = _FakeSupabase(rows=[])
    with caplog.at_level(logging.DEBUG, logger="packages.quantum.policy_lab.config"):
        configs = cfg.load_cohort_configs("user-1", supabase)

    assert configs["aggressive"].stop_loss_pct == 0.65  # legit first-boot baseline
    assert not any("[CONFIG_FAULT]" in r.getMessage() for r in caplog.records)


def test_tight_fallback_stops_never_looser_than_champion():
    """Every TIGHT_FALLBACK cohort stop must be <= the live champion (0.30)."""
    assert cfg.TIGHT_FALLBACK, "TIGHT_FALLBACK must not be empty"
    for name, c in cfg.TIGHT_FALLBACK.items():
        assert c.stop_loss_pct <= 0.30, f"{name} stop {c.stop_loss_pct} > 0.30"


# ── (2) _check_stop_loss — missing/zero max_credit fail-safe ──────────

def _pos(max_credit, upl, qty=1, avg_entry_price=2.0):
    return {
        "id": "p-1",
        "max_credit": max_credit,
        "unrealized_pl": upl,
        "quantity": qty,
        "avg_entry_price": avg_entry_price,
    }


def test_stop_loss_none_max_credit_loss_not_silently_disabled(caplog):
    """max_credit=None + real loss → stop STILL fires via the avg_entry_price
    basis (NOT the old silent False), and logs [STOP_LOSS_DATA_FAULT]."""
    pos = _pos(max_credit=None, upl=-500.0, qty=1, avg_entry_price=2.0)
    with caplog.at_level(logging.ERROR, logger=pxe.__name__):
        fired = pxe._check_stop_loss(pos, sl_pct=0.50)

    # fallback_basis = 2.0*100*1 = 200; threshold = -(200*0.5) = -100; -500 <= -100
    assert fired is True
    assert any("[STOP_LOSS_DATA_FAULT]" in r.getMessage() for r in caplog.records)


def test_stop_loss_zero_max_credit_loss_not_silently_disabled():
    """max_credit=0 behaves like None (the second silent fail-OPEN leak)."""
    pos = _pos(max_credit=0, upl=-500.0, qty=1, avg_entry_price=2.0)
    assert pxe._check_stop_loss(pos, sl_pct=0.50) is True


def test_stop_loss_missing_credit_no_loss_is_not_spurious_close():
    """max_credit=None but the position is in PROFIT → no stop (no spurious
    close). Demonstrates protection is preserved WITHOUT forcing a close."""
    pos = _pos(max_credit=None, upl=+500.0, qty=1, avg_entry_price=2.0)
    assert pxe._check_stop_loss(pos, sl_pct=0.50) is False


def test_stop_loss_no_basis_at_all_fires_only_on_confirmed_loss():
    """No max_credit AND no avg_entry_price: protective fire ONLY on a confirmed
    loss; a flat/up position is not stopped (still no spurious close)."""
    loss = _pos(max_credit=None, upl=-1.0, qty=1, avg_entry_price=0)
    flat = _pos(max_credit=None, upl=0.0, qty=1, avg_entry_price=0)
    assert pxe._check_stop_loss(loss, sl_pct=0.50) is True
    assert pxe._check_stop_loss(flat, sl_pct=0.50) is False


def test_stop_loss_healthy_path_unchanged():
    """max_credit present: healthy formula identical to pre-fix behavior
    (credit position, entry_cost=200, sl_pct=2.0 → threshold -400)."""
    assert pxe._check_stop_loss(_pos(2.00, -450.0, qty=-1), sl_pct=2.0) is True
    assert pxe._check_stop_loss(_pos(2.00, -300.0, qty=-1), sl_pct=2.0) is False
