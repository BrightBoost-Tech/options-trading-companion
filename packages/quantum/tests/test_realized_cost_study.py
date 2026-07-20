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

import re
from pathlib import Path

import pytest

from scripts.analytics.realized_cost_study import (
    STUDY_SQL,
    build_row,
    build_study,
    classify_cohort,
    execution_realism,
    economic_evidence_cohort,
    render_markdown,
    _entry_adverse_slip_usd,
)


def _broker_live(study):
    """The single broker-live (real-capital, authoritative) cohort, or None."""
    live = [c for c in study.cohorts if c.economic_evidence_cohort == "broker_live"]
    assert len(live) <= 1, "broker_live must be a single partition"
    return live[0] if live else None


# --- fixtures ---------------------------------------------------------------
def _row(record_id, cohort_name, *, fill_source="alpaca_fill_reconciler",
         symbol="QQQ", strategy="DEBIT", regime="normal", quantity=17,
         realized_pl=-45.0, closed_at="2026-07-15T14:15:06Z", close_reason="target",
         entry_side="buy", entry_fill_price=1.4847, entry_requested_price=1.47,
         entry_tcm=None, close_side="sell", close_fill_price=1.17,
         close_order_json=None, ranking_costs=None, routing="broker",
         entry_fees_usd=None):
    # routing="broker" => real Alpaca LIVE execution ($0 stamped commission);
    # routing="paper"  => real Alpaca PAPER execution (broker-routed, $0 stamped,
    #                     but NOT real capital);
    # routing="internal" => internal_paper (fees_usd estimate-or-ambiguous).
    if routing == "broker":
        exec_mode, has_oid, bstatus = "alpaca_live", True, "filled"
        fees = 0.0 if entry_fees_usd is None else entry_fees_usd
    elif routing == "paper":
        exec_mode, has_oid, bstatus = "alpaca_paper", True, "filled"
        fees = 0.0 if entry_fees_usd is None else entry_fees_usd
    else:
        exec_mode, has_oid, bstatus = "internal_paper", False, None
        fees = 11.05 if entry_fees_usd is None else entry_fees_usd
    return {
        "record_id": record_id, "suggestion_id": f"sug-{record_id}",
        "cohort_name": cohort_name, "fill_source": fill_source, "symbol": symbol,
        "strategy": strategy, "regime": regime, "quantity": quantity,
        "realized_pl": realized_pl, "closed_at": closed_at, "close_reason": close_reason,
        "entry_side": entry_side, "entry_fill_price": entry_fill_price,
        "entry_requested_price": entry_requested_price, "entry_filled_qty": quantity,
        "entry_fees_usd": fees, "entry_execution_mode": exec_mode,
        "entry_has_alpaca_oid": has_oid, "entry_broker_status": bstatus,
        "entry_tcm": entry_tcm,
        "close_side": close_side, "close_fill_price": close_fill_price,
        "close_filled_qty": quantity, "close_fees_usd": fees,
        "close_execution_mode": exec_mode, "close_has_alpaca_oid": has_oid,
        "close_broker_status": bstatus, "close_order_json": close_order_json,
        "ranking_costs": ranking_costs,
    }


# A debit close WITH the close_fill_gap stamp (cross/mid in signed mark basis).
STAMPED_CLOSE_OJ = {"close_fill_gap_cross": -1.10, "close_fill_gap_mid": -1.20}


# --- 1. classification (THREE separate axes — V17-4) ------------------------
class TestClassification:
    @pytest.mark.parametrize("name,expected", [
        # POLICY cohort is a STRATEGY identity, never an economic claim: an
        # 'aggressive' policy row is 'aggressive', NOT 'live'.
        ("aggressive", "aggressive"), ("AGGRESSIVE", "aggressive"),
        ("neutral", "shadow"), ("conservative", "shadow"),
        (None, "unattributed"), ("", "unattributed"), ("weird", "unattributed"),
    ])
    def test_policy_cohort(self, name, expected):
        assert classify_cohort(name) == expected

    @pytest.mark.parametrize("mode,expected", [
        # ECONOMIC realism reads execution_mode (the reliable venue), NEVER the
        # noisy fill_source. Only alpaca_live is real capital.
        ("alpaca_live", "alpaca_live"), ("ALPACA_LIVE", "alpaca_live"),
        ("alpaca_paper", "alpaca_paper"),
        ("internal_paper", "internal"), ("shadow_blocked", "internal"),
        ("submission_failed", "internal"), (None, "internal"), ("", "internal"),
    ])
    def test_execution_realism(self, mode, expected):
        assert execution_realism(mode) == expected

    @pytest.mark.parametrize("realism,expected", [
        ("alpaca_live", "broker_live"), ("alpaca_paper", "broker_paper"),
        ("internal", "internal"),
    ])
    def test_economic_evidence_cohort(self, realism, expected):
        assert economic_evidence_cohort(realism) == expected

    def test_aggressive_paper_row_is_not_broker_live(self):
        # THE V17-4 CORE: an aggressive-POLICY row that filled on the paper
        # broker is economic-evidence broker_PAPER, never broker_live.
        r = build_row(_row("a", "aggressive", routing="paper"))
        assert r.policy_cohort == "aggressive"
        assert r.execution_realism == "alpaca_paper"
        assert r.economic_evidence_cohort == "broker_paper"

    def test_aggressive_internal_row_is_not_broker_live(self):
        r = build_row(_row("a", "aggressive", routing="internal"))
        assert r.policy_cohort == "aggressive"
        assert r.execution_realism == "internal"
        assert r.economic_evidence_cohort == "internal"


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
        # No entry_execution_mode → execution_realism 'internal' (never fabricate
        # a broker route from an absent venue), so this aggressive-policy row
        # lands in (aggressive, internal), NOT a broker-live bucket.
        empty = {"record_id": "e", "cohort_name": "aggressive"}
        study = build_study({"rows": [empty]})
        agg = next(c for c in study.cohorts if c.policy_cohort == "aggressive")
        assert agg.execution_realism == "internal"
        assert agg.economic_evidence_cohort == "internal"
        assert agg.n_rows == 1
        # every delta abstained (counted), none scored
        assert agg.entry_vs_requested.n_available == 0
        assert agg.entry_vs_requested.n_unavailable == 1
        assert agg.close_vs_executable_cross.n_available == 0


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


# --- 4b. realized commission PER ROUTING (the 07-18 review repair) ----------
class TestRealizedCommissionPerRouting:
    def test_broker_routed_commission_is_known_zero(self):
        # A real Alpaca fill stamps the true $0 options commission — KNOWN, not
        # blanket-unavailable (that would be over-abstention, the mirror of H9).
        r = build_row(_row("a", "aggressive", routing="broker", entry_fees_usd=0.0))
        c = r.entry_realized_commission
        assert c.available is True and c.amount_usd == 0.0
        assert c.provenance.model_version.endswith("broker_reconciler")

    def test_internal_fill_commission_is_unavailable(self):
        # An internal fill's fees_usd is estimate-or-ambiguous → typed UNAVAILABLE.
        r = build_row(_row("a", "neutral", fill_source="exit_evaluator",
                          routing="internal"))
        c = r.entry_realized_commission
        assert c.available is False
        assert c.unavailable_reason == "internal_fill_commission_not_broker_stamped"

    def test_broker_routing_requires_all_three_signals(self):
        # Missing broker_status (e.g. submission_failed) → not broker-routed.
        row = _row("a", "aggressive", routing="broker")
        row["entry_broker_status"] = "submission_failed"
        assert build_row(row).entry_realized_commission.available is False

    def test_commission_vs_tcm_delta_broker_known_vs_estimate(self):
        # broker $0 realized − TCM $11.05 estimate = −11.05 (the estimate
        # over-charged commission for zero-fee options).
        r = build_row(_row("a", "aggressive", routing="broker", entry_fees_usd=0.0,
                          entry_tcm={"fees_usd": 11.05}))
        d = r.entry_commission_vs_tcm
        assert d.available is True and d.amount_usd == pytest.approx(-11.05)

    def test_commission_vs_tcm_unavailable_on_internal(self):
        r = build_row(_row("a", "neutral", routing="internal",
                          entry_tcm={"fees_usd": 11.05}))
        assert r.entry_commission_vs_tcm.available is False

    def test_cohort_routing_counts(self):
        # CONTRACT CHANGE (V17-4): an internal fill in the aggressive POLICY book
        # no longer shares a cohort with the live fills — it partitions into its
        # OWN (aggressive, internal) bucket, so the broker-live commission counts
        # can never be polluted by an internal row.
        study = build_study({"rows": [
            _row("L1", "aggressive", routing="broker"),
            _row("L2", "aggressive", routing="broker"),
            _row("I1", "aggressive", routing="internal"),
        ]})
        live = _broker_live(study)
        assert live.n_rows == 2
        assert live.entry_commission_broker_known == 2
        assert live.entry_commission_internal_unavailable == 0
        internal = next(
            c for c in study.cohorts
            if c.policy_cohort == "aggressive" and c.execution_realism == "internal")
        assert internal.n_rows == 1
        assert internal.economic_evidence_cohort == "internal"
        assert internal.entry_commission_broker_known == 0
        assert internal.entry_commission_internal_unavailable == 1


# --- 5. cohort separation ---------------------------------------------------
class TestCohortSeparation:
    def _study(self):
        return build_study({
            "generated_at": "2026-07-18", "source": "synthetic",
            "rows": [
                _row("L1", "aggressive", realized_pl=-45.0),   # alpaca_live
                _row("L2", "aggressive", realized_pl=20.0),    # alpaca_live
                # an aggressive PAPER-broker row with a huge magnitude — must NOT
                # pool into the broker-live headline (V17-4)
                _row("P1", "aggressive", routing="paper", realized_pl=-9999.0),
                # shadow with a huge fictional magnitude + internal fill
                _row("S1", "neutral", fill_source="exit_evaluator", realized_pl=5000.0,
                     routing="internal"),
                _row("U1", None, fill_source=None, realized_pl=3.0, routing="internal"),
            ],
        })

    def test_split_and_no_leak(self):
        study = self._study()
        live = _broker_live(study)
        # broker-live is ONLY the two alpaca_live rows
        assert live.policy_cohort == "aggressive"
        assert live.execution_realism == "alpaca_live"
        assert live.n_rows == 2
        assert live.realized_pl_sum == pytest.approx(-25.0)
        # neither the -9999 paper magnitude nor the 5000 shadow fiction leaks in
        paper = next(c for c in study.cohorts
                     if c.economic_evidence_cohort == "broker_paper")
        assert paper.policy_cohort == "aggressive" and paper.n_rows == 1
        assert paper.realized_pl_sum == pytest.approx(-9999.0)
        shadow = next(c for c in study.cohorts if c.policy_cohort == "shadow")
        assert shadow.realized_pl_sum == pytest.approx(5000.0)
        assert shadow.economic_evidence_cohort == "internal"
        unattr = next(c for c in study.cohorts if c.policy_cohort == "unattributed")
        assert unattr.n_rows == 1 and unattr.realized_pl_sum == pytest.approx(3.0)

    def test_realism_partition_is_homogeneous(self):
        # Every cohort's rows share one execution_realism by construction — so a
        # fill can never be miscounted into another economic bucket.
        study = self._study()
        for c in study.cohorts:
            assert c.economic_evidence_cohort == economic_evidence_cohort(
                c.execution_realism)
        # exactly one real-capital bucket exists
        assert sum(1 for c in study.cohorts
                   if c.economic_evidence_cohort == "broker_live") == 1

    def test_win_loss_counts(self):
        live = _broker_live(self._study())
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
        # The persisted TCM/ranker estimates are surfaced separately and NEVER
        # folded into any realized delta.
        r = build_row(_row("a", "aggressive",
                          entry_tcm={"expected_fill_price": 1.46, "fees_usd": 11.05},
                          ranking_costs={"expected_fees_total": 22.1, "leg_count": 2}))
        ctx = r.persisted_estimates
        # the fees note now describes the PER-ROUTING meaning of fees_usd
        assert "per routing" in ctx["entry_fees_usd_note"].lower()
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
                            _row("S1", "neutral", fill_source="exit_evaluator",
                                 routing="internal")]}
        md = render_markdown(build_study(payload))
        # headings now carry the policy cohort, the execution realism, AND the
        # economic-evidence label — an internal row is never headed "LIVE".
        assert "Cohort: AGGRESSIVE / ALPACA_LIVE" in md
        assert "economic evidence: BROKER_LIVE" in md
        assert "Cohort: SHADOW / INTERNAL" in md
        assert "ENTRY realized fill vs requested limit" in md
        assert "CLOSE realized fill vs executable cross" in md
        assert "ENTRY realized commission vs TCM estimate" in md
        assert "Realized commission routing:" in md
        assert "PER_STRUCTURE_CONTRACT" in md
        assert "COMPARE, never SUM" in md

    def test_only_broker_live_heading_claims_real_capital(self):
        # An aggressive/internal + aggressive/paper row must NOT get a
        # "real capital" / "authoritative" line; only the alpaca_live bucket does.
        payload = {"source": "s", "rows": [
            _row("L1", "aggressive", routing="broker"),
            _row("P1", "aggressive", routing="paper"),
            _row("I1", "aggressive", routing="internal"),
        ]}
        md = render_markdown(build_study(payload))
        # exactly one "AUTHORITATIVE, real capital" label (the broker-live bucket)
        assert md.count("AUTHORITATIVE, real capital") == 1
        assert "NOT real capital (paper broker)" in md
        assert "NOT real capital (internal fills)" in md

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
        assert "entry_fees_usd" in STUDY_SQL and "close_fees_usd" in STUDY_SQL
        # only filled orders are read (cancelled/watchdog rows never enter)
        assert "po.status = 'filled'" in STUDY_SQL
        assert "pp.status = 'closed'" in STUDY_SQL

    def test_broker_routing_columns_present(self):
        # per-routing commission needs the order-level routing signals for BOTH
        # the open and close order.
        for col in ("execution_mode", "alpaca_order_id IS NOT NULL", "broker_status"):
            assert col in STUDY_SQL
        assert "entry_execution_mode" in STUDY_SQL and "close_execution_mode" in STUDY_SQL


# --- 10. census-shape no-conflation (V17-4 reproduced) ----------------------
class TestCensusShapeNoConflation:
    """Drives the REPRODUCED live census: the aggressive POLICY book =
    12 alpaca_live + 11 alpaca_paper + 1 internal_paper. 81% of the magnitude is
    paper/internal — the old contract pooled it ALL under a single LIVE headline.
    The broker-live headline must equal ONLY the 12 alpaca_live sum (-$400.00),
    and a huge paper/internal magnitude must not be able to move it."""

    def _census_study(self):
        rows = []
        # 12 alpaca_live rows summing to EXACTLY -400.00
        live_pls = [-50.0] * 8 + [0.0] * 4
        for i, pl in enumerate(live_pls):
            rows.append(_row(f"LV{i}", "aggressive", routing="broker", realized_pl=pl))
        # 11 alpaca_paper rows carrying most of the magnitude (must NOT pool live)
        for i in range(11):
            rows.append(_row(f"PP{i}", "aggressive", routing="paper",
                             realized_pl=-159.13))
        # 1 internal_paper row with a HUGE magnitude — must not move live either
        rows.append(_row("IN0", "aggressive", routing="internal",
                         realized_pl=-1_000_000.0))
        return build_study({"source": "census", "rows": rows})

    def test_broker_live_headline_is_only_the_alpaca_live_sum(self):
        live = _broker_live(self._census_study())
        assert live.n_rows == 12
        assert live.execution_realism == "alpaca_live"
        assert live.economic_evidence_cohort == "broker_live"
        assert live.realized_pl_sum == pytest.approx(-400.00)

    def test_huge_internal_magnitude_cannot_change_broker_live(self):
        study = self._census_study()
        internal = next(
            c for c in study.cohorts
            if c.policy_cohort == "aggressive" and c.execution_realism == "internal")
        assert internal.n_rows == 1
        assert internal.realized_pl_sum == pytest.approx(-1_000_000.0)
        # the broker-live sum is exactly the 12 live rows, untouched
        assert _broker_live(study).realized_pl_sum == pytest.approx(-400.00)

    def test_aggressive_appears_as_three_realism_buckets(self):
        study = self._census_study()
        agg = [c for c in study.cohorts if c.policy_cohort == "aggressive"]
        assert sorted(c.execution_realism for c in agg) == [
            "alpaca_live", "alpaca_paper", "internal"]
        paper = next(c for c in agg if c.execution_realism == "alpaca_paper")
        assert paper.n_rows == 11
        assert paper.economic_evidence_cohort == "broker_paper"


# --- 11. observe-only import lock -------------------------------------------
_STUDY_IMPORT_RE = re.compile(
    r"^\s*(?:"
    r"from\s+[\w\.]*realized_cost_study\s+import"
    r"|import\s+[\w\.]*realized_cost_study"
    r"|from\s+[\w\.]+\s+import\s+[^\n]*realized_cost_study"
    r")",
    re.MULTILINE,
)


class TestObserveOnlyImportLock:
    """The realized-cost study is a read-only analytics CLI. NO production
    module under packages/quantum (scanner / ranker / executor / gate / exit /
    risk / allocator / scoring) may import it — if a future change wires it into
    a decision path this test breaks the build, forcing a deliberate review.
    Tests import it freely."""

    def test_no_live_consumer_imports_the_study(self):
        quantum = Path(__file__).resolve().parents[1]  # packages/quantum
        offenders = []
        for path in sorted(quantum.rglob("*.py")):
            rel = path.relative_to(quantum)
            if "tests" in rel.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if _STUDY_IMPORT_RE.search(text):
                offenders.append(rel.as_posix())
        assert offenders == [], (
            "realized_cost_study is observe-only; no production module may "
            f"import it (offenders: {offenders})")

    def test_import_lock_regex_bites(self):
        # the lock must actually catch the realistic import shapes...
        for line in (
            "from scripts.analytics.realized_cost_study import build_study",
            "import scripts.analytics.realized_cost_study",
            "from scripts.analytics import realized_cost_study",
        ):
            assert _STUDY_IMPORT_RE.search(line), f"pattern missed: {line!r}"
        # ...and not false-positive on an unrelated mention.
        assert _STUDY_IMPORT_RE.search("# realized_cost_study is documented here") is None
