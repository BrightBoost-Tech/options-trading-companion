"""Tests for the realized entry/close cost comparison runner — COST CONSUMER #3
(``scripts/analytics/realized_cost_study.py``).

The runner is OBSERVE-ONLY glue over the frozen ``cost_basis`` foundation: it
compares PERSISTED estimated/executable cost values against REALIZED fills for
closed round-trips. These tests pin, with SYNTHETIC fixtures only (NO live DB):

1. cohort / fill-realism classification (live vs shadow vs unattributed;
   broker vs internal).
2. ENTRY adverse-slippage SIGN SAFETY — direction comes from ``side`` + fill
   MAGNITUDE, NEVER the raw broker fill sign (the 2026-07-08 corruption class):
   a sell fill stored POSITIVE and the same fill stored NEGATIVE produce the
   IDENTICAL adverse number.
3. H9 typed-unavailable, COUNTED not scored, when a fill / persisted estimate /
   side is missing — never a fabricated zero.
4. CLOSE reuse of the frozen ``extract_realized_close_costs``: a stamped close
   yields a gap_fraction + executable-cross delta; an unstamped or single-fill
   close types the cross delta UNAVAILABLE while the realized fill still exists.
5. COHORT SEPARATION: shadow magnitudes NEVER aggregate into live; the
   fill-realism flag is independent of the cohort.
6. COMPARE-NEVER-SUM: every cost output is a typed pairwise delta (a − b) or a
   labeled passthrough; no field ever adds two bases together.
7. determinism.
8. render_markdown smoke: cohorts, entry/exit rows, units legend.
9. STUDY_SQL semantics: strictly read-only single SELECT; open = earliest fill,
   close = latest fill joined only when strictly later; cohort/realized_pl
   present; fees_usd labeled an ESTIMATE.
"""

import pytest

from scripts.analytics.realized_cost_study import (
    STUDY_SQL,
    build_row,
    build_study,
    classify_cohort,
    fill_realism,
    render_markdown,
    _entry_adverse_slip_usd,
)


# --- fixtures ---------------------------------------------------------------
def _row(record_id, cohort_name, *, fill_source="alpaca_fill_reconciler",
         symbol="QQQ", strategy="DEBIT", regime="normal", quantity=17,
         realized_pl=-45.0, closed_at="2026-07-15T14:15:06Z", close_reason="target",
         entry_side="buy", entry_fill_price=1.4847, entry_requested_price=1.47,
         entry_tcm=None, close_side="sell", close_fill_price=1.17,
         close_order_json=None, ranking_costs=None):
    return {
        "record_id": record_id, "suggestion_id": f"sug-{record_id}",
        "cohort_name": cohort_name, "fill_source": fill_source, "symbol": symbol,
        "strategy": strategy, "regime": regime, "quantity": quantity,
        "realized_pl": realized_pl, "closed_at": closed_at, "close_reason": close_reason,
        "entry_side": entry_side, "entry_fill_price": entry_fill_price,
        "entry_requested_price": entry_requested_price, "entry_filled_qty": quantity,
        "entry_fees_estimate": 11.05, "entry_tcm": entry_tcm,
        "close_side": close_side, "close_fill_price": close_fill_price,
        "close_filled_qty": quantity, "close_order_json": close_order_json,
        "ranking_costs": ranking_costs,
    }


# A debit close WITH the close_fill_gap stamp (cross/mid in signed mark basis).
STAMPED_CLOSE_OJ = {"close_fill_gap_cross": -1.10, "close_fill_gap_mid": -1.20}


# --- 1. classification ------------------------------------------------------
class TestClassification:
    @pytest.mark.parametrize("name,expected", [
        ("aggressive", "live"), ("AGGRESSIVE", "live"),
        ("neutral", "shadow"), ("conservative", "shadow"),
        (None, "unattributed"), ("", "unattributed"), ("weird", "unattributed"),
    ])
    def test_cohort(self, name, expected):
        assert classify_cohort(name) == expected

    @pytest.mark.parametrize("src,expected", [
        ("alpaca_fill_reconciler", "broker"), ("alpaca", "broker"),
        ("exit_evaluator", "internal"), ("manual_endpoint", "internal"),
        (None, "internal"), ("", "internal"),
    ])
    def test_fill_realism(self, src, expected):
        assert fill_realism(src) == expected


# --- 2. entry sign safety ---------------------------------------------------
class TestEntrySignSafety:
    def test_buy_adverse_is_paid_above_reference(self):
        # buy: paid 1.4847 vs requested 1.47 -> adverse +1.47 USD/contract
        assert _entry_adverse_slip_usd("buy", 1.4847, 1.47) == pytest.approx(1.47)

    def test_sell_adverse_is_received_below_reference(self):
        # sell: got 1.3266 vs requested 1.34 -> adverse +1.34 USD/contract
        assert _entry_adverse_slip_usd("sell", 1.3266, 1.34) == pytest.approx(1.34, abs=1e-9)

    def test_sell_favorable_is_negative(self):
        # sell: got MORE than requested -> favorable (negative adverse)
        assert _entry_adverse_slip_usd("sell", 1.40, 1.34) == pytest.approx(-6.0, abs=1e-9)

    def test_raw_broker_sign_is_ignored(self):
        # The runner passes the fill MAGNITUDE; whatever sign the broker stored,
        # the adverse number is identical (the corruption class cannot leak).
        pos = build_row(_row("a", "aggressive", entry_side="sell",
                             entry_fill_price=1.3266, entry_requested_price=1.34,
                             close_fill_price=None, close_side=None))
        neg = build_row(_row("a", "aggressive", entry_side="sell",
                             entry_fill_price=-1.3266, entry_requested_price=1.34,
                             close_fill_price=None, close_side=None))
        assert pos.entry_slip_vs_requested.amount_usd == pytest.approx(
            neg.entry_slip_vs_requested.amount_usd)
        assert pos.entry_slip_vs_requested.amount_usd == pytest.approx(1.34, abs=1e-9)

    def test_negative_requested_is_magnitude_normalized(self):
        # A negative persisted requested_price (seen in live data) is abs()'d.
        r = build_row(_row("a", "aggressive", entry_side="buy",
                          entry_fill_price=1.4847, entry_requested_price=-1.47,
                          close_fill_price=None, close_side=None))
        assert r.entry_slip_vs_requested.amount_usd == pytest.approx(1.47)


# --- 3. H9 typed-unavailable, counted ---------------------------------------
class TestUnavailableCounted:
    def test_missing_requested_types_unavailable(self):
        r = build_row(_row("a", "aggressive", entry_requested_price=None,
                          close_fill_price=None, close_side=None))
        d = r.entry_slip_vs_requested
        assert d.available is False and d.amount_usd is None
        assert d.reason == "requested_price_not_persisted"

    def test_missing_tcm_types_unavailable(self):
        r = build_row(_row("a", "aggressive", entry_tcm=None,
                          close_fill_price=None, close_side=None))
        assert r.entry_slip_vs_tcm.available is False
        assert r.entry_slip_vs_tcm.reason == "tcm_expected_fill_not_persisted"

    def test_missing_fill_types_unavailable(self):
        r = build_row(_row("a", "aggressive", entry_fill_price=None,
                          close_fill_price=None, close_side=None))
        assert r.entry_slip_vs_requested.reason == "entry_fill_missing"

    def test_unknown_side_types_unavailable(self):
        r = build_row(_row("a", "aggressive", entry_side=None,
                          close_fill_price=None, close_side=None))
        assert r.entry_slip_vs_requested.reason == "entry_side_unknown"

    def test_fully_empty_row_is_counted_not_scored(self):
        empty = {"record_id": "e", "cohort_name": "aggressive"}
        study = build_study({"rows": [empty]})
        live = next(c for c in study.cohorts if c.cohort == "live")
        assert live.n_rows == 1
        # every delta abstained (counted), none scored
        assert live.entry_vs_requested.n_available == 0
        assert live.entry_vs_requested.n_unavailable == 1
        assert live.close_vs_executable_cross.n_available == 0


# --- 4. close reuse of the frozen extractor ---------------------------------
class TestCloseReuse:
    def test_stamped_close_yields_gap_and_executable_delta(self):
        # close fill 1.17 -> mark -1.17*100 = -117; cross -1.10*100 = -110;
        # delta = -117 - (-110) = -7. gap = (-1.17 - -1.10)/(-1.20 - -1.10) = 0.7
        r = build_row(_row("a", "aggressive", close_fill_price=1.17,
                          close_order_json=STAMPED_CLOSE_OJ))
        d = r.close_realized_vs_executable_cross
        assert d.available is True
        assert d.amount_usd == pytest.approx(-7.0, abs=1e-6)
        assert r.close_gap_fraction == pytest.approx(0.7, abs=1e-6)

    def test_unstamped_close_types_cross_unavailable_but_row_has_close(self):
        r = build_row(_row("a", "aggressive", close_fill_price=1.17,
                          close_order_json=None))
        assert r.has_close is True
        assert r.close_realized_vs_executable_cross.available is False
        assert r.close_gap_fraction is None

    def test_single_fill_position_has_no_close(self):
        r = build_row(_row("a", "aggressive", close_fill_price=None, close_side=None))
        assert r.has_close is False
        assert r.close_realized_vs_executable_cross.reason == "no_close_fill_order"


# --- 5. cohort separation ---------------------------------------------------
class TestCohortSeparation:
    def _study(self):
        return build_study({
            "generated_at": "2026-07-18", "source": "synthetic",
            "rows": [
                _row("L1", "aggressive", realized_pl=-45.0),
                _row("L2", "aggressive", realized_pl=20.0),
                # shadow with a huge fictional magnitude + internal fill
                _row("S1", "neutral", fill_source="exit_evaluator", realized_pl=5000.0),
                _row("U1", None, fill_source=None, realized_pl=3.0),
            ],
        })

    def test_split_and_no_leak(self):
        study = self._study()
        live = next(c for c in study.cohorts if c.cohort == "live")
        shadow = next(c for c in study.cohorts if c.cohort == "shadow")
        unattr = next(c for c in study.cohorts if c.cohort == "unattributed")
        assert live.n_rows == 2 and shadow.n_rows == 1 and unattr.n_rows == 1
        # the fictional 5000 shadow magnitude NEVER enters the live sum
        assert live.realized_pl_sum == pytest.approx(-25.0)
        assert shadow.realized_pl_sum == pytest.approx(5000.0)

    def test_fill_realism_flag_independent_of_cohort(self):
        study = self._study()
        live = next(c for c in study.cohorts if c.cohort == "live")
        shadow = next(c for c in study.cohorts if c.cohort == "shadow")
        assert live.n_broker_fills == 2 and live.n_internal_fills == 0
        assert shadow.n_broker_fills == 0 and shadow.n_internal_fills == 1

    def test_win_loss_counts(self):
        live = next(c for c in self._study().cohorts if c.cohort == "live")
        assert live.realized_wins == 1 and live.realized_losses == 1


# --- 6. compare-never-sum ----------------------------------------------------
class TestCompareNeverSum:
    def test_entry_delta_is_a_difference_not_a_sum(self):
        # amount == (fill - requested) magnitude*100 for a buy; the detail carries
        # BOTH sides separately so a reader can never mistake it for a sum.
        r = build_row(_row("a", "aggressive", entry_side="buy",
                          entry_fill_price=1.50, entry_requested_price=1.47,
                          close_fill_price=None, close_side=None))
        d = r.entry_slip_vs_requested
        assert d.amount_usd == pytest.approx((1.50 - 1.47) * 100)
        assert set(("realized_fill_per_contract", "reference_per_contract", "side")) \
            <= set(d.detail.keys())

    def test_persisted_estimates_are_labeled_and_separate(self):
        # The persisted fee ESTIMATE is surfaced separately and explicitly NOT a
        # realized commission — never folded into any realized delta.
        r = build_row(_row("a", "aggressive",
                          entry_tcm={"expected_fill_price": 1.46, "fees_usd": 11.05},
                          ranking_costs={"expected_fees_total": 22.1, "leg_count": 2}))
        ctx = r.persisted_estimates
        assert "not a" in ctx["entry_fees_estimate_usd_note"].lower() \
            or "estimate" in ctx["entry_fees_estimate_usd_note"].lower()
        assert ctx["tcm_estimate"]["fees_usd_total_estimate"] == 11.05
        assert ctx["ranker_estimate"]["expected_fees_total_usd_estimate"] == 22.1


# --- 7. determinism ---------------------------------------------------------
class TestDeterminism:
    def test_identical_inputs_identical_study(self):
        payload = {"generated_at": "2026-07-18", "source": "s",
                   "rows": [_row("a", "aggressive", close_order_json=STAMPED_CLOSE_OJ),
                            _row("b", "neutral", fill_source="exit_evaluator")]}
        assert build_study(payload) == build_study(payload)


# --- 8. render smoke --------------------------------------------------------
class TestRender:
    def test_markdown_has_cohorts_units_and_sides(self):
        payload = {"generated_at": "2026-07-18", "source": "synthetic",
                   "rows": [_row("L1", "aggressive", close_order_json=STAMPED_CLOSE_OJ),
                            _row("S1", "neutral", fill_source="exit_evaluator")]}
        md = render_markdown(build_study(payload))
        assert "Cohort: LIVE" in md and "Cohort: SHADOW" in md
        assert "ENTRY realized fill vs requested limit" in md
        assert "CLOSE realized fill vs executable cross" in md
        assert "PER_STRUCTURE_CONTRACT" in md
        assert "COMPARE, never SUM" in md

    def test_empty_payload_renders_without_crash(self):
        md = render_markdown(build_study({"rows": []}))
        assert "No closed round-trips" in md


# --- 9. STUDY_SQL semantics -------------------------------------------------
class TestStudySql:
    def test_strictly_read_only_single_select(self):
        up = STUDY_SQL.upper()
        for verb in ("INSERT ", "UPDATE ", "DELETE ", "DROP ", "ALTER ",
                     "TRUNCATE ", "CREATE ", "GRANT "):
            assert verb not in up, f"write verb leaked into read-only SQL: {verb!r}"
        assert up.count("SELECT JSON_BUILD_OBJECT") == 1

    def test_open_is_earliest_close_is_latest_and_distinct(self):
        # open = earliest filled; close = latest filled joined only when strictly
        # later than the open (a single-fill position gets no close).
        assert "ORDER BY po.position_id, po.filled_at ASC" in STUDY_SQL
        assert "ORDER BY po.position_id, po.filled_at DESC" in STUDY_SQL
        assert "co.filled_at > oo.filled_at" in STUDY_SQL

    def test_cohort_and_realized_pl_and_estimate_label_present(self):
        assert "policy_lab_cohorts" in STUDY_SQL
        assert "cp.realized_pl" in STUDY_SQL
        assert "fees_usd" in STUDY_SQL and "entry_fees_estimate" in STUDY_SQL
        # only filled orders are read (cancelled/watchdog rows never enter)
        assert "po.status = 'filled'" in STUDY_SQL
        assert "pp.status = 'closed'" in STUDY_SQL
