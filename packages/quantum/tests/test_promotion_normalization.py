"""Gap-3(a) (2026-07-03) — shadow-ledger promotion-time normalization.

Pins: the SOFI twin fixture normalizes per-contract on both sides with the
measured fill-discount on the SHADOW side only; live/champion values are
byte-identical; ledger inputs are never mutated; flag-off is a true
identity; the module is imported by governance (policy_lab.evaluator) and
nothing else; the discount is a measured constant with bounded parsing.
"""

import inspect
import os
from unittest.mock import patch

from packages.quantum.policy_lab import promotion_normalization as pn


CHAMP = "champ-cohort-id"
SHADOW = "shadow-cohort-id"


def _row(cohort_id, trade_date, realized=0.0, unrealized=0.0):
    return {
        "cohort_id": cohort_id, "trade_date": trade_date,
        "realized_pnl": realized, "unrealized_pnl": unrealized,
        "expected_shortfall": 0.0, "avg_winner": 0.0, "avg_loser": 0.0,
        "max_drawdown_pct": -0.05, "trade_count": 1, "win_rate": 0.0,
    }


def _pos(qty, created, closed=None, cohort=SHADOW):
    return {"cohort_id": cohort, "quantity": qty,
            "created_at": created, "closed_at": closed}


class TestSofiTwinFixture:
    """The 07-01 evidence pair: live 1-lot −$40 vs shadow 17-lot −$1,044.48
    (26× raw). Normalized: live −40.00 vs shadow (−1044.48/17)×0.31 ≈ −19.05
    — the comparison is per-contract expected contribution, not raw fiction."""

    def test_normalized_comparison(self, monkeypatch):
        monkeypatch.delenv("SHADOW_PROMOTION_NORMALIZATION_ENABLED", raising=False)
        monkeypatch.delenv("SHADOW_FILL_DISCOUNT", raising=False)
        rows = [
            _row(CHAMP, "2026-06-30", realized=-40.0),
            _row(SHADOW, "2026-07-01", realized=-1044.48),
        ]
        positions = {
            CHAMP: [_pos(1, "2026-06-30T16:30:00+00:00",
                         "2026-06-30T19:45:00+00:00", cohort=CHAMP)],
            SHADOW: [_pos(17, "2026-06-30T16:30:00+00:00",
                          "2026-07-01T13:30:00+00:00")],
        }
        out = pn.normalize_promotion_rows(rows, positions, champion_id=CHAMP)
        champ_out = next(r for r in out if r["cohort_id"] == CHAMP)
        shadow_out = next(r for r in out if r["cohort_id"] == SHADOW)
        # Live side: divisor 1, NO discount → byte-identical.
        assert champ_out["realized_pnl"] == -40.0
        # Shadow side: per-contract then the measured discount.
        assert abs(shadow_out["realized_pnl"] - (-1044.48 / 17 * 0.31)) < 1e-9
        # Percent fields untouched on both sides.
        assert shadow_out["max_drawdown_pct"] == -0.05

    def test_ledger_rows_never_mutated(self, monkeypatch):
        monkeypatch.delenv("SHADOW_PROMOTION_NORMALIZATION_ENABLED", raising=False)
        rows = [_row(SHADOW, "2026-07-01", realized=-1044.48)]
        pn.normalize_promotion_rows(
            rows, {SHADOW: [_pos(17, "2026-06-30", "2026-07-01")]}, CHAMP
        )
        assert rows[0]["realized_pnl"] == -1044.48  # input untouched


class TestDiscountScope:
    def test_discount_applies_to_shadow_only(self, monkeypatch):
        monkeypatch.delenv("SHADOW_PROMOTION_NORMALIZATION_ENABLED", raising=False)
        rows = [
            _row(CHAMP, "2026-07-01", realized=100.0),
            _row(SHADOW, "2026-07-01", realized=100.0),
        ]
        out = pn.normalize_promotion_rows(rows, {}, champion_id=CHAMP)
        champ_out = next(r for r in out if r["cohort_id"] == CHAMP)
        shadow_out = next(r for r in out if r["cohort_id"] == SHADOW)
        assert champ_out["realized_pnl"] == 100.0     # divisor 1, no discount
        assert abs(shadow_out["realized_pnl"] - 31.0) < 1e-9  # ×0.31

    def test_champion_per_contract_still_applies(self, monkeypatch):
        monkeypatch.delenv("SHADOW_PROMOTION_NORMALIZATION_ENABLED", raising=False)
        rows = [_row(CHAMP, "2026-07-01", realized=100.0)]
        out = pn.normalize_promotion_rows(
            rows, {CHAMP: [_pos(5, "2026-07-01", "2026-07-01", cohort=CHAMP)]},
            champion_id=CHAMP,
        )
        assert abs(out[0]["realized_pnl"] - 20.0) < 1e-9  # /5, ×1.0


class TestFlagPolarity:
    def test_default_on(self, monkeypatch):
        monkeypatch.delenv("SHADOW_PROMOTION_NORMALIZATION_ENABLED", raising=False)
        assert pn.is_enabled() is True

    def test_empty_is_on(self, monkeypatch):
        monkeypatch.setenv("SHADOW_PROMOTION_NORMALIZATION_ENABLED", "  ")
        assert pn.is_enabled() is True

    def test_explicit_falsy_disables(self, monkeypatch):
        for v in ("0", "false", "no", "off", "OFF"):
            monkeypatch.setenv("SHADOW_PROMOTION_NORMALIZATION_ENABLED", v)
            assert pn.is_enabled() is False

    def test_flag_off_is_identity(self, monkeypatch):
        monkeypatch.setenv("SHADOW_PROMOTION_NORMALIZATION_ENABLED", "0")
        rows = [_row(SHADOW, "2026-07-01", realized=-1044.48)]
        out = pn.normalize_promotion_rows(
            rows, {SHADOW: [_pos(17, "2026-06-30", "2026-07-01")]}, CHAMP
        )
        assert out is rows  # the very same list — legacy behavior


class TestMeasuredDiscount:
    def test_default_is_measured_031(self, monkeypatch):
        monkeypatch.delenv("SHADOW_FILL_DISCOUNT", raising=False)
        assert pn.fill_discount() == 0.31

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("SHADOW_FILL_DISCOUNT", "0.5")
        assert pn.fill_discount() == 0.5

    def test_out_of_range_falls_back(self, monkeypatch):
        for v in ("0", "-0.2", "1.5", "banana"):
            monkeypatch.setenv("SHADOW_FILL_DISCOUNT", v)
            assert pn.fill_discount() == 0.31

    def test_one_is_allowed(self, monkeypatch):
        monkeypatch.setenv("SHADOW_FILL_DISCOUNT", "1.0")
        assert pn.fill_discount() == 1.0


class TestDailyContractDivisor:
    def test_open_position_attributes_to_each_open_day(self):
        positions = [_pos(17, "2026-06-30T16:30:00+00:00", "2026-07-01T13:30:00+00:00")]
        assert pn.daily_contract_divisor(positions, "2026-06-30") == 17.0
        assert pn.daily_contract_divisor(positions, "2026-07-01") == 17.0
        assert pn.daily_contract_divisor(positions, "2026-06-29") == 1.0
        assert pn.daily_contract_divisor(positions, "2026-07-02") == 1.0

    def test_still_open_counts_forward(self):
        positions = [_pos(3, "2026-06-30", None)]
        assert pn.daily_contract_divisor(positions, "2026-07-02") == 3.0

    def test_no_positions_floors_at_one(self):
        assert pn.daily_contract_divisor([], "2026-07-01") == 1.0

    def test_bad_dates_and_qty_never_raise(self):
        positions = [{"quantity": None, "created_at": "not-a-date", "closed_at": None}]
        assert pn.daily_contract_divisor(positions, "garbage") == 1.0


class TestGovernanceOnlyPin:
    def test_module_imported_only_by_policy_lab_evaluator(self):
        """The normalization is a GOVERNANCE read-side transform. No trading
        path may import it — pinned by sweeping the package for importers."""
        import pathlib

        pkg = pathlib.Path(pn.__file__).resolve().parents[1]  # packages/quantum
        importers = []
        for py in pkg.rglob("*.py"):
            if "tests" in py.parts or py.name == "promotion_normalization.py":
                continue
            try:
                text = py.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if "promotion_normalization" in text:
                importers.append(str(py.relative_to(pkg)))
        assert importers == [str(pathlib.Path("policy_lab") / "evaluator.py")], (
            f"unexpected importers of promotion_normalization: {importers}"
        )

    def test_check_promotion_normalizes_before_scoring(self):
        from packages.quantum.policy_lab import evaluator

        src = inspect.getsource(evaluator.check_promotion)
        assert "normalize_promotion_rows" in src
        assert src.index("normalize_promotion_rows") < src.index("score_cohort_window")
