"""Tests for the 2026-06-18 is_paper-blind-calibration fix + the coupled v3
conviction view (P2#1 / #1043).

Context: the first clean post-epoch relearn (06-18 10:00Z) produced a
LONG_PUT_DEBIT_SPREAD ev×1.5/pop×1.5 segment driven by 2 shadow NFLX trades
(incl. a +662 outlier) outvoting the lone live trade — which had UNDER-performed
(+48 vs +95.67 pred → live-only would deflate). is_paper-blind calibration
inverted the live sign and applied the boost to live scoring.

Four pins:
1. Live-only filter — _fetch_outcomes adds .eq("is_paper", False) when
   CALIBRATION_TRAIN_LIVE_ONLY is ON (default); reverts to blind on explicit falsy.
2. Null-pop basis fix — _compute_segment_metrics measures the realized win rate
   over the SAME non-null-pop rows as the predicted average (adding null-pop rows
   must not move pop_realized_rate / pop_calibration_error; win_count stays over all).
3. <MIN-live → raw fallback — compute_calibration_adjustments below
   MIN_CALIBRATION_TRADES returns insufficient_data, and an empty blob makes
   apply_calibration the identity (×1.0).
4. v3 migration drift-guard — the migration .sql carries is_paper=false and an
   epoch/floor literal pinned equal to the calibration_service.py source defaults.
"""
import glob
import os
import re
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from packages.quantum.analytics import calibration_service as cs

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def _new_service():
    # __new__ avoids __init__ deps; the methods under test use only self.client
    # (mocked) or pure args.
    return cs.CalibrationService.__new__(cs.CalibrationService)


def _row(pop, pnl, ev=0.0):
    return {
        "pop_predicted": pop,
        "pnl_realized": pnl,
        "ev_predicted": ev,
        "pnl_predicted": ev,
    }


# ── 1. Live-only filter in _fetch_outcomes ──────────────────────────

class _QueryRecorder:
    """Records .eq() calls on a supabase-style fluent query chain."""
    def __init__(self, rows):
        self._rows = rows
        self.eq_calls = []

    def table(self, *a, **k):
        return self

    def select(self, *a, **k):
        return self

    def gte(self, *a, **k):
        return self

    def eq(self, col, val):
        self.eq_calls.append((col, val))
        return self

    def execute(self):
        return SimpleNamespace(data=self._rows)


def _fetch_eq_calls(flag_value):
    svc = _new_service()
    rec = _QueryRecorder([_row(0.6, 10.0)])
    svc.client = rec
    env = {} if flag_value is None else {"CALIBRATION_TRAIN_LIVE_ONLY": flag_value}
    with patch.dict(os.environ, env, clear=False):
        if flag_value is None:
            os.environ.pop("CALIBRATION_TRAIN_LIVE_ONLY", None)
        svc._fetch_outcomes("u", 30)
    return rec.eq_calls


def test_live_only_filter_on_by_default_unset():
    calls = _fetch_eq_calls(None)  # unset → ON
    assert ("is_paper", False) in calls
    assert ("user_id", "u") in calls  # sanity: base filter still applied


def test_live_only_filter_on_explicit_truthy():
    assert ("is_paper", False) in _fetch_eq_calls("1")


def test_live_only_filter_off_explicit_falsy_reverts_to_blind():
    calls = _fetch_eq_calls("0")
    assert ("is_paper", False) not in calls
    assert ("user_id", "u") in calls  # base filter still applied


# ── 2. Null-pop denominator-basis fix ───────────────────────────────

def test_pop_basis_excludes_null_pop_rows_from_both_sides():
    svc = _new_service()
    # 3 non-null-pop rows: 2 wins, 1 loss → realized rate over the pop set = 2/3.
    base = [_row(0.6, 100.0), _row(0.6, 100.0), _row(0.6, -50.0)]
    m_base = svc._compute_segment_metrics(base)
    # Add 2 null-pop WINS. Pre-fix (wins/n) would move the realized rate from
    # 2/3 to 4/5; post-fix it must be UNCHANGED (null-pop rows inform neither side).
    m_null = svc._compute_segment_metrics(base + [_row(None, 200.0), _row(None, 300.0)])

    assert m_null["pop_realized_rate"] == m_base["pop_realized_rate"]
    assert m_null["pop_predicted_avg"] == m_base["pop_predicted_avg"]
    assert m_null["pop_calibration_error"] == m_base["pop_calibration_error"]
    # Overall win stats DO count the null-pop wins (measured over all rows).
    assert m_null["win_count"] == m_base["win_count"] + 2
    assert m_null["sample_size"] == 5


def test_pop_basis_all_null_pop_yields_none_not_crash():
    svc = _new_service()
    m = svc._compute_segment_metrics([_row(None, 100.0), _row(None, -10.0)])
    assert m["pop_predicted_avg"] is None
    assert m["pop_calibration_error"] is None
    assert m["sample_size"] == 2  # never raises on all-null pop


# ── 3. Sub-MIN live pool → insufficient_data (raw mode) ─────────────

def test_below_min_live_falls_through_to_raw_and_apply_is_identity():
    svc = _new_service()
    svc.client = MagicMock()
    n = cs.MIN_CALIBRATION_TRADES - 1
    svc._fetch_outcomes = lambda *a, **k: [_row(0.6, 10.0) for _ in range(n)]

    res = svc.compute_calibration_adjustments("u")
    assert res["status"] == "insufficient_data"
    assert res["sample_size"] == n
    assert not res.get("adjustments")  # no segment multipliers produced

    # An empty/insufficient blob must leave EV/PoP untouched downstream.
    ev, pop = cs.apply_calibration(100.0, 0.6, "LONG_PUT_DEBIT_SPREAD", "normal", {})
    assert ev == 100.0 and pop == 0.6


# ── 4. v3 migration drift-guard ─────────────────────────────────────

def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def test_v3_migration_is_paper_false_and_literals_pinned_to_source():
    migs = glob.glob(os.path.join(
        REPO_ROOT, "supabase", "migrations",
        "*learning_performance_summary_v3*.sql",
    ))
    assert len(migs) == 1, f"expected exactly one v3 migration, found: {migs}"
    mig = _read(migs[0])
    src = _read(os.path.join(
        REPO_ROOT, "packages", "quantum", "analytics", "calibration_service.py",
    ))

    # is_paper-blind posture must match calibration's live-only training.
    assert re.search(r"is_paper\s*=\s*false", mig, re.IGNORECASE), \
        "v3 view must filter is_paper = false (match live-only calibration)"

    # Epoch literal in the migration GREATEST wall == CALIBRATION_EV_EPOCH source default.
    mig_epoch = re.search(
        r"'([^']+)'::timestamptz,\s*--\s*=\s*CALIBRATION_EV_EPOCH", mig)
    src_epoch = re.search(r'"CALIBRATION_EV_EPOCH",\s*"([^"]+)"', src)
    assert mig_epoch and src_epoch, "epoch literal/marker missing (migration or source)"
    assert mig_epoch.group(1) == src_epoch.group(1), \
        f"epoch drift: migration {mig_epoch.group(1)} != source {src_epoch.group(1)}"

    # Corruption-floor literal == CORRUPTED_PNL_FLOOR source default.
    mig_floor = re.search(
        r"'([^']+)'::timestamptz\)\s*--\s*=\s*CORRUPTED_PNL_FLOOR", mig)
    src_floor = re.search(r'"CALIBRATION_PNL_FLOOR_DATE",\s*"([^"]+)"', src)
    assert mig_floor and src_floor, "floor literal/marker missing (migration or source)"
    assert mig_floor.group(1) == src_floor.group(1), \
        f"floor drift: migration {mig_floor.group(1)} != source {src_floor.group(1)}"
