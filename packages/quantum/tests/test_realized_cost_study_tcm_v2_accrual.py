"""Tests for the TCM v2 REALIZED-ACCRUAL extension of the realized-cost study
(``scripts/analytics/realized_cost_study.py``, Lane B, observe-only).

The accrual consumes the #1278 stage-stamped ``tcm.tcm_v2_proposal`` and emits,
per eligible entry/close side of a closed round-trip, a typed COMMISSION
example — current-model vs proposed-v2 vs realized broker commission — plus the
two owner-facing deltas. These tests pin, with SYNTHETIC fixtures only (NO live
DB), every case the Lane B charter names:

  * broker zero-commission rows (realized KNOWN $0; the frozen model over-charges)
  * internal synthetic fees (realized UNAVAILABLE → both deltas UNAVAILABLE)
  * qty>1 (commission is quantity-scaled TOTAL; the delta scales)
  * condor leg-count (4-leg stamp surfaces leg_count)
  * missing close stamp (close-side v2 UNAVAILABLE; realized fill-gap still typed)
  * missing v2 stamp (pre-#1278 rows: v2 UNAVAILABLE, never zero; current still real)
  * duplicate-row dedup (idempotence: one example per (record_id, side))
  * model-version drift (a v2 version bump segregates rows into a NEW bucket)
  * cohort separation + JOIN identity (entry↔close share record_id + suggestion_id)
"""

import pytest

from scripts.analytics.realized_cost_study import (
    STUDY_SQL,
    TCM_V2_STAMP_KEY,
    build_accrual_examples,
    build_study,
    build_tcm_v2_accrual,
    render_markdown,
    _dedup_examples,
)


# --- fixtures ---------------------------------------------------------------
def _v2_stamp(*, routing, entry_or_close, leg_count=2, quantity=1,
              proposed_commission_usd=0.0, proposed_available=True,
              proposed_reason=None, current_commission_usd=0.65,
              model_version="tcm_v2_proposal/0.1.0",
              source="broker_zero_commission_options"):
    """A synthetic stamp mirroring services.tcm_v2_proposal.build_proposal's
    persisted shape (only the fields the accrual reads)."""
    comm = {"available": proposed_available, "source": source}
    if proposed_available:
        comm["usd"] = proposed_commission_usd
    else:
        comm["usd"] = None
        comm["reason"] = proposed_reason or "proposed_commission_unavailable"
    return {
        "model_version": model_version,
        "routing": routing,
        "entry_or_close": entry_or_close,
        "leg_count": leg_count,
        "quantity": quantity,
        "source": source,
        "current_model": {
            "commission_usd": {"usd": current_commission_usd, "available": True},
        },
        "proposed_model": {"commission_usd": comm},
        "delta": {"commission_usd": None, "available": False},
    }


def _row(record_id, cohort_name, *, routing="broker", fill_source=None,
         symbol="QQQ", strategy="DEBIT", regime="normal", quantity=1,
         realized_pl=-45.0, closed_at="2026-07-20T14:15:06Z",
         close_reason="target", suggestion_id=None,
         entry_side="buy", entry_fill_price=1.48, entry_requested_price=1.47,
         entry_tcm_fees=0.65, entry_v2_stamp="auto", entry_v2_leg_count=2,
         entry_v2_proposed=0.0,
         close_present=True, close_side="sell", close_fill_price=1.17,
         close_order_json="auto", close_tcm_fees=0.65, close_v2_stamp="auto",
         close_v2_proposed=0.0, ranking_costs=None):
    """One closed-position DB row (post-STUDY_SQL shape, incl. the new
    ``close_tcm`` column). ``routing='broker'`` => real Alpaca fill ($0 stamped
    fees, all three broker signals present); ``routing='internal'`` =>
    internal_paper (no broker signals, fees estimate-or-ambiguous)."""
    if routing == "broker":
        exec_mode, has_oid, bstatus = "alpaca_live", True, "filled"
        fees = 0.0
        v2_routing = "broker_alpaca_options"
    else:
        exec_mode, has_oid, bstatus = "internal_paper", False, None
        fees = 11.05
        v2_routing = "shadow" if cohort_name in ("neutral", "conservative") else "internal"
    if fill_source is None:
        fill_source = "alpaca_fill_reconciler" if routing == "broker" else "exit_evaluator"

    # Entry TCM (+ optional v2 stamp).
    entry_tcm = {"fees_usd": entry_tcm_fees, "expected_fill_price": 1.46}
    if entry_v2_stamp == "auto":
        entry_tcm[TCM_V2_STAMP_KEY] = _v2_stamp(
            routing=v2_routing, entry_or_close="entry",
            leg_count=entry_v2_leg_count, quantity=quantity,
            proposed_commission_usd=entry_v2_proposed,
            current_commission_usd=entry_tcm_fees,
        )
    elif entry_v2_stamp is not None:
        entry_tcm[TCM_V2_STAMP_KEY] = entry_v2_stamp

    # Close side.
    close_tcm = None
    close_oj = None
    if close_present:
        close_tcm = {"fees_usd": close_tcm_fees}
        if close_v2_stamp == "auto":
            close_tcm[TCM_V2_STAMP_KEY] = _v2_stamp(
                routing=v2_routing, entry_or_close="close",
                leg_count=entry_v2_leg_count, quantity=quantity,
                proposed_commission_usd=close_v2_proposed,
                current_commission_usd=close_tcm_fees,
            )
        elif close_v2_stamp is not None:
            close_tcm[TCM_V2_STAMP_KEY] = close_v2_stamp
        close_oj = ({"close_fill_gap_cross": -1.10, "close_fill_gap_mid": -1.20}
                    if close_order_json == "auto" else close_order_json)

    return {
        "record_id": record_id,
        "suggestion_id": suggestion_id or f"sug-{record_id}",
        "cohort_name": cohort_name, "fill_source": fill_source, "symbol": symbol,
        "strategy": strategy, "regime": regime, "quantity": quantity,
        "realized_pl": realized_pl, "closed_at": closed_at,
        "close_reason": close_reason,
        "entry_side": entry_side, "entry_fill_price": entry_fill_price,
        "entry_requested_price": entry_requested_price, "entry_filled_qty": quantity,
        "entry_fees_usd": fees, "entry_execution_mode": exec_mode,
        "entry_has_alpaca_oid": has_oid, "entry_broker_status": bstatus,
        "entry_tcm": entry_tcm,
        "close_side": close_side if close_present else None,
        "close_fill_price": close_fill_price if close_present else None,
        "close_filled_qty": quantity if close_present else None,
        "close_fees_usd": fees if close_present else None,
        "close_execution_mode": exec_mode if close_present else None,
        "close_has_alpaca_oid": has_oid if close_present else None,
        "close_broker_status": bstatus if close_present else None,
        "close_order_json": close_oj,
        "close_tcm": close_tcm,
        "ranking_costs": ranking_costs,
    }


def _by_side(row):
    exs = {e.side: e for e in build_accrual_examples(row)}
    return exs


# --- 1. broker zero-commission rows -----------------------------------------
class TestBrokerZeroCommission:
    def test_entry_current_over_close_v2_tracks_realized(self):
        # frozen fee 0.65 (qty 1) vs broker realized $0 vs proposed v2 $0.
        e = _by_side(_row("p1", "aggressive", routing="broker",
                          entry_tcm_fees=0.65, entry_v2_proposed=0.0))["entry"]
        assert e.current_model_cost.available and e.current_model_cost.amount_usd == 0.65
        assert e.tcm_v2_cost.available and e.tcm_v2_cost.amount_usd == 0.0
        assert e.realized_commission.available and e.realized_commission.amount_usd == 0.0
        # current OVER-charges; v2 TRACKS realized (the accrued evidence).
        assert e.current_minus_realized.available
        assert e.current_minus_realized.amount_usd == pytest.approx(0.65)
        assert e.v2_minus_realized.available
        assert e.v2_minus_realized.amount_usd == pytest.approx(0.0)

    def test_close_side_also_accrues(self):
        c = _by_side(_row("p1", "aggressive", routing="broker"))["close"]
        assert c.side == "close"
        assert c.current_minus_realized.amount_usd == pytest.approx(0.65)
        assert c.v2_minus_realized.amount_usd == pytest.approx(0.0)

    def test_routing_and_source_from_stamp(self):
        e = _by_side(_row("p1", "aggressive", routing="broker"))["entry"]
        assert e.routing == "broker_alpaca_options"
        assert e.routing_source == "stage_stamp"
        assert e.v2_stamp_present is True
        assert e.source == "tcm_v2_proposal@stage"
        assert e.model_version == "tcm_v2_proposal/0.1.0"


# --- 2. internal synthetic fees ---------------------------------------------
class TestInternalSyntheticFees:
    def test_realized_commission_unavailable_deltas_abstain(self):
        # internal fill: fees_usd is estimate-or-ambiguous → realized UNAVAILABLE,
        # so BOTH deltas abstain (counted, never scored zero — H9).
        e = _by_side(_row("s1", "neutral", routing="internal"))["entry"]
        assert e.realized_commission.available is False
        assert (e.realized_commission.unavailable_reason
                == "internal_fill_commission_not_broker_stamped")
        assert e.current_minus_realized.available is False
        assert e.v2_minus_realized.available is False
        # the model commissions themselves are still typed (present), just not
        # differenced against an absent realized value.
        assert e.current_model_cost.available is True

    def test_internal_v2_proposed_is_synthetic_estimate(self):
        # internal routing proposes the synthetic estimate = the current fee.
        e = _by_side(_row("s1", "neutral", routing="internal",
                          entry_tcm_fees=11.05, entry_v2_proposed=11.05))["entry"]
        assert e.tcm_v2_cost.available and e.tcm_v2_cost.amount_usd == 11.05
        assert e.routing == "shadow"


# --- 3. qty>1 (commission is a quantity-scaled TOTAL) -----------------------
class TestQuantityScaling:
    def test_delta_scales_with_quantity(self):
        # frozen fee 0.65*qty one-way; qty=7 → current 4.55 vs realized $0.
        e = _by_side(_row("p1", "aggressive", routing="broker", quantity=7,
                          entry_tcm_fees=4.55, entry_v2_proposed=0.0))["entry"]
        assert e.quantity == 7
        assert e.current_model_cost.amount_usd == pytest.approx(4.55)
        assert e.current_minus_realized.amount_usd == pytest.approx(4.55)
        assert e.v2_minus_realized.amount_usd == pytest.approx(0.0)


# --- 4. condor leg-count -----------------------------------------------------
class TestCondorLegCount:
    def test_four_leg_stamp_surfaces_leg_count(self):
        e = _by_side(_row("p1", "aggressive", routing="broker",
                          entry_v2_leg_count=4))["entry"]
        assert e.leg_count == 4

    def test_leg_count_falls_back_to_ranker_when_stamp_absent(self):
        # no v2 stamp → leg_count from the ranker estimate.
        e = _by_side(_row("p1", "aggressive", routing="broker",
                          entry_v2_stamp=None, close_v2_stamp=None,
                          ranking_costs={"leg_count": 3}))["entry"]
        assert e.leg_count == 3

    def test_leg_count_unavailable_when_nothing_carries_it(self):
        e = _by_side(_row("p1", "aggressive", routing="broker",
                          entry_v2_stamp=None, close_v2_stamp=None,
                          ranking_costs=None))["entry"]
        assert e.leg_count is None


# --- 5. missing close stamp --------------------------------------------------
class TestMissingCloseStamp:
    def test_close_v2_unavailable_but_current_and_gap_typed(self):
        # close order carries a tcm (current fee) but NO v2 stamp.
        c = _by_side(_row("p1", "aggressive", routing="broker",
                          close_v2_stamp=None))["close"]
        assert c.v2_stamp_present is False
        assert c.tcm_v2_cost.available is False
        assert c.tcm_v2_cost.unavailable_reason == "no_v2_stamp_pre_1278"
        # the current-model commission is still real...
        assert c.current_model_cost.available is True
        # ...and the realized fill-gap (close_fill_gap stamp) is still typed.
        assert c.realized_spread_or_fill_gap.available is True
        assert c.close_gap_fraction == pytest.approx(0.7, abs=1e-6)
        # current−realized computes; v2−realized abstains (no v2 value).
        assert c.current_minus_realized.available is True
        assert c.v2_minus_realized.available is False
        assert c.v2_minus_realized.reason and "no_v2_stamp_pre_1278" in c.v2_minus_realized.reason

    def test_unstamped_close_fill_gap_types_context_unavailable(self):
        # close present but NO close_fill_gap stamp (older order) → the carried
        # realized spread/fill-gap is UNAVAILABLE, never fabricated.
        c = _by_side(_row("p1", "aggressive", routing="broker",
                          close_order_json=None))["close"]
        assert c.realized_spread_or_fill_gap.available is False
        assert c.close_gap_fraction is None

    def test_single_fill_position_has_no_close_example(self):
        exs = _by_side(_row("p1", "aggressive", routing="broker",
                            close_present=False))
        assert set(exs.keys()) == {"entry"}
        # entry side never carries a close_fill_gap.
        assert exs["entry"].realized_spread_or_fill_gap.available is False
        assert (exs["entry"].realized_spread_or_fill_gap.unavailable_reason
                == "entry_side_no_close_fill_gap")


# --- 6. missing v2 stamp (pre-#1278 rows) ------------------------------------
class TestMissingV2Stamp:
    def test_v2_unavailable_never_zero_current_still_real(self):
        e = _by_side(_row("p1", "aggressive", routing="broker",
                          entry_v2_stamp=None, close_v2_stamp=None))["entry"]
        assert e.v2_stamp_present is False
        assert e.model_version == "unavailable_no_v2_stamp"
        assert e.source == "no_v2_stamp"
        # v2 typed UNAVAILABLE (NOT a fabricated 0.0)
        assert e.tcm_v2_cost.available is False
        assert e.tcm_v2_cost.amount_usd is None
        assert e.v2_minus_realized.available is False
        # current-vs-realized still accrues (broker realized known)
        assert e.current_minus_realized.available is True

    def test_routing_derived_from_realized_when_no_stamp(self):
        e = _by_side(_row("p1", "aggressive", routing="broker",
                          entry_v2_stamp=None, close_v2_stamp=None))["entry"]
        assert e.routing == "broker_alpaca_options"
        assert e.routing_source == "derived_from_realized"

    def test_internal_no_stamp_routing_derives_internal(self):
        e = _by_side(_row("u1", None, routing="internal",
                          entry_v2_stamp=None, close_v2_stamp=None))["entry"]
        # unattributed + internal fill → derived 'internal'
        assert e.routing == "internal"
        assert e.routing_source == "derived_from_realized"


# --- 7. duplicate-row dedup (idempotence) ------------------------------------
class TestDuplicateDedup:
    def test_duplicate_payload_row_counts_once(self):
        row = _row("p1", "aggressive", routing="broker")
        # same position appears twice in the payload
        acc = build_tcm_v2_accrual({"rows": [row, dict(row)]})
        # 1 entry + 1 close, NOT doubled
        assert acc.total_examples == 2
        live = [b for b in acc.buckets if b.cohort == "aggressive"][0]
        assert live.n_examples == 2 and live.n_entry == 1 and live.n_close == 1

    def test_dedup_helper_keys_on_record_id_and_side(self):
        row = _row("p1", "aggressive", routing="broker")
        exs = build_accrual_examples(row) + build_accrual_examples(dict(row))
        assert len(exs) == 4
        deduped = _dedup_examples(exs)
        assert len(deduped) == 2
        assert {e.example_id for e in deduped} == {"p1:entry", "p1:close"}

    def test_report_is_pure_function_of_db(self):
        payload = {"rows": [_row("p1", "aggressive", routing="broker"),
                            _row("s1", "neutral", routing="internal")]}
        assert build_tcm_v2_accrual(payload) == build_tcm_v2_accrual(payload)


# --- 8. model-version drift (segregation) ------------------------------------
class TestModelVersionDrift:
    def test_version_bump_segregates_into_new_bucket(self):
        v1 = _row("p1", "aggressive", routing="broker")  # v0.1.0 default
        # a v2 version bump: same cohort, DIFFERENT model_version
        bumped_entry = _v2_stamp(routing="broker_alpaca_options",
                                 entry_or_close="entry",
                                 model_version="tcm_v2_proposal/0.2.0")
        bumped_close = _v2_stamp(routing="broker_alpaca_options",
                                 entry_or_close="close",
                                 model_version="tcm_v2_proposal/0.2.0")
        v2 = _row("p2", "aggressive", routing="broker",
                  entry_v2_stamp=bumped_entry, close_v2_stamp=bumped_close)
        acc = build_tcm_v2_accrual({"rows": [v1, v2]})
        live_buckets = {b.model_version: b for b in acc.buckets if b.cohort == "aggressive"}
        # TWO distinct live buckets — versions never pool
        assert set(live_buckets.keys()) == {
            "tcm_v2_proposal/0.1.0", "tcm_v2_proposal/0.2.0"}
        assert live_buckets["tcm_v2_proposal/0.1.0"].n_examples == 2
        assert live_buckets["tcm_v2_proposal/0.2.0"].n_examples == 2

    def test_no_stamp_lands_in_sentinel_bucket_separate_from_stamped(self):
        stamped = _row("p1", "aggressive", routing="broker")
        unstamped = _row("p2", "aggressive", routing="broker",
                         entry_v2_stamp=None, close_v2_stamp=None)
        acc = build_tcm_v2_accrual({"rows": [stamped, unstamped]})
        versions = {b.model_version for b in acc.buckets if b.cohort == "aggressive"}
        assert "tcm_v2_proposal/0.1.0" in versions
        assert "unavailable_no_v2_stamp" in versions


# --- 9. cohort separation + JOIN identity ------------------------------------
class TestCohortSeparationAndJoinIdentity:
    def test_shadow_never_pools_into_live(self):
        acc = build_tcm_v2_accrual({"rows": [
            _row("L1", "aggressive", routing="broker"),
            _row("S1", "neutral", routing="internal"),
            _row("U1", None, routing="internal"),
        ]})
        cohorts = {b.cohort for b in acc.buckets}
        assert cohorts == {"aggressive", "shadow", "unattributed"}
        live = [b for b in acc.buckets if b.cohort == "aggressive"]
        # only the aggressive round-trip's 2 examples are in live
        assert sum(b.n_examples for b in live) == 2

    def test_entry_close_share_durable_identity(self):
        # The join proof: entry and close examples of ONE round-trip carry the
        # SAME record_id (position spine) AND suggestion_id — the only identity
        # the accrual joins on.
        exs = _by_side(_row("p1", "aggressive", routing="broker",
                            suggestion_id="sug-XYZ"))
        assert exs["entry"].record_id == exs["close"].record_id == "p1"
        assert exs["entry"].suggestion_id == exs["close"].suggestion_id == "sug-XYZ"
        assert exs["entry"].example_id == "p1:entry"
        assert exs["close"].example_id == "p1:close"


# --- 10. SQL + render smoke --------------------------------------------------
class TestSqlAndRender:
    def test_study_sql_selects_close_tcm(self):
        # the close-side v2 stamp requires the close order's tcm column.
        assert "close_tcm" in STUDY_SQL
        assert "po.tcm" in STUDY_SQL
        # still strictly read-only
        up = STUDY_SQL.upper()
        for verb in ("INSERT ", "UPDATE ", "DELETE ", "DROP ", "ALTER ",
                     "CREATE ", "TRUNCATE "):
            assert verb not in up

    def test_render_includes_accrual_section(self):
        payload = {"generated_at": "2026-07-20", "source": "synthetic",
                   "rows": [_row("L1", "aggressive", routing="broker"),
                            _row("S1", "neutral", routing="internal")]}
        md = render_markdown(build_study(payload))
        assert "TCM v2 Realized-Accrual" in md
        assert "current − realized commission" in md
        assert "v2 − realized commission" in md
        assert "tcm_v2_proposal/0.1.0" in md

    def test_empty_payload_renders_accrual_placeholder(self):
        md = render_markdown(build_study({"rows": []}))
        assert "No eligible TCM v2 accrual examples" in md

    def test_example_as_dict_is_json_safe(self):
        import json
        e = _by_side(_row("p1", "aggressive", routing="broker"))["entry"]
        d = e.as_dict()
        # round-trips through json (all typed components serialize)
        assert json.loads(json.dumps(d))["current_minus_realized"]["amount_usd"] == pytest.approx(0.65)
        assert d["model_version"] == "tcm_v2_proposal/0.1.0"


# --- 11. legacy-path stamp coverage (V17-3) ---------------------------------
class TestLegacyStampCoverage:
    """The single-order (non-inventory) path also emits the coverage fields:
    contributing_fill_count is 1, and stamp_complete tracks the one stamp."""

    def test_stamped_legacy_side_is_complete(self):
        e = _by_side(_row("p1", "aggressive", routing="broker"))["entry"]
        assert e.contributing_fill_count == 1
        assert e.stamped_fill_count == 1
        assert e.stamp_complete is True

    def test_unstamped_legacy_side_is_incomplete(self):
        e = _by_side(_row("p1", "aggressive", routing="broker",
                          entry_v2_stamp=None, close_v2_stamp=None))["entry"]
        assert e.contributing_fill_count == 1
        assert e.stamped_fill_count == 0
        assert e.stamp_complete is False
        assert e.tcm_v2_cost.available is False


# --- 12. economic-evidence axis (V17-4) -------------------------------------
class TestLegacyEconomicEvidence:
    def test_aggressive_broker_example_is_broker_live(self):
        e = _by_side(_row("p1", "aggressive", routing="broker"))["entry"]
        assert e.cohort == "aggressive"
        assert e.execution_realism == "alpaca_live"
        assert e.economic_evidence_cohort == "broker_live"

    def test_aggressive_internal_example_is_not_broker_live(self):
        e = _by_side(_row("i1", "aggressive", routing="internal"))["entry"]
        assert e.cohort == "aggressive"           # policy unchanged...
        assert e.execution_realism == "internal"  # ...but economics are internal
        assert e.economic_evidence_cohort == "internal"

    def test_internal_example_never_in_a_broker_live_bucket(self):
        acc = build_tcm_v2_accrual({"rows": [
            _row("L1", "aggressive", routing="broker"),
            _row("I1", "aggressive", routing="internal"),
        ]})
        live = [b for b in acc.buckets
                if b.economic_evidence_cohort == "broker_live"]
        # every broker-live example is an alpaca_live fill; the internal row's
        # examples land only in the (aggressive, internal) bucket
        assert all(b.execution_realism == "alpaca_live" for b in live)
        assert sum(b.n_examples for b in live) == 2
        internal = [b for b in acc.buckets
                    if b.cohort == "aggressive"
                    and b.economic_evidence_cohort == "internal"]
        assert sum(b.n_examples for b in internal) == 2
