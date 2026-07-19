"""Tests for the TCM v2 MULTI-FILL realized-accrual extension (Lane B) of
``scripts/analytics/realized_cost_study.py`` — fill-complete commission
coverage, observe-only.

Consumer #3's #1289 accrual collapsed a position to its earliest-open +
latest-close order, dropping every intermediate fill (its reviewer flagged 18
live positions with >2 filled orders, up to 6). This lane consumes the full
``fill_orders`` inventory (the new STUDY_SQL column) and aggregates commission
over EVERY contributing fill of each side. These tests pin, with SYNTHETIC
fixtures only (NO live DB), every case the Lane B charter names:

  * multi-fill entry (2 fills → summed commission, fill_count=2)
  * multi-close (2 close orders → summed commission)
  * partial-fill quantities summing (side quantity = Σ filled_qty)
  * single-fill regression (inventory-of-one reproduces the collapsed grain)
  * duplicate/replay idempotency (order_id dedup; zero-qty rows dropped;
    payload dedup; pure function of the DB)
  * model-version drift (a version bump segregates buckets; mixed-within-a-side
    marks a `mixed:` version)
  * correction-marker rows (F-CREDIT-SIGN noted, commission NOT re-corrected)
  * missing stamps (pre-#1278 → v2 UNAVAILABLE, never zero)
  * boundary adjudication (first side-flip; leading zero-qty never defines side)
  * H9 no-undercount (a partial/mixed side types the total UNAVAILABLE, counted)

The legacy single-order path (no inventory) is exercised by
test_realized_cost_study_tcm_v2_accrual.py and must stay byte-identical.
"""

import json

import pytest

from scripts.analytics.realized_cost_study import (
    STUDY_SQL,
    build_accrual_examples,
    build_study,
    build_tcm_v2_accrual,
    render_markdown,
    _split_fill_inventory,
    _dedup_examples,
)


# --- fixtures ---------------------------------------------------------------
def _stamp(routing, *, proposed_usd=0.0, available=True, reason=None,
           leg_count=2, model_version="tcm_v2_proposal/0.1.0",
           source="broker_zero_commission_options"):
    """Minimal synthetic ``tcm_v2_proposal`` — only the fields the accrual reads."""
    comm = {"available": available}
    if available:
        comm["usd"] = proposed_usd
    else:
        comm["usd"] = None
        comm["reason"] = reason or "proposed_commission_unavailable"
    return {
        "model_version": model_version,
        "routing": routing,
        "leg_count": leg_count,
        "source": source,
        "proposed_model": {"commission_usd": comm},
    }


def _order(order_id, side, filled_qty, *, avg_fill_price=1.0,
           requested_price=1.0, routing="broker", tcm_fees=0.65,
           v2_proposed=0.0, v2_stamp="auto",
           v2_version="tcm_v2_proposal/0.1.0", leg_count=2,
           order_json=None, filled_at="2026-07-20T14:00:00.000000Z",
           credit_correction=False, has_tcm=True):
    """One filled ``paper_orders`` row as it appears inside the ``fill_orders``
    inventory. routing='broker' → real Alpaca fill ($0 fees, all broker
    signals); routing='internal' → internal_paper (fees estimate-or-ambiguous)."""
    if routing == "broker":
        exec_mode, has_oid, bstatus, fees = "alpaca_live", True, "filled", 0.0
        v2_routing = "broker_alpaca_options"
    else:
        exec_mode, has_oid, bstatus, fees = "internal_paper", False, None, 11.05
        v2_routing = "internal"
    tcm = None
    if has_tcm:
        tcm = {"fees_usd": tcm_fees, "expected_fill_price": avg_fill_price}
        if v2_stamp == "auto":
            tcm["tcm_v2_proposal"] = _stamp(
                v2_routing, proposed_usd=v2_proposed, leg_count=leg_count,
                model_version=v2_version)
        elif v2_stamp is not None:
            tcm["tcm_v2_proposal"] = v2_stamp
    return {
        "order_id": order_id, "side": side, "filled_qty": filled_qty,
        "requested_qty": filled_qty, "avg_fill_price": avg_fill_price,
        "requested_price": requested_price, "fees_usd": fees,
        "execution_mode": exec_mode, "has_alpaca_oid": has_oid,
        "broker_status": bstatus, "tcm": tcm, "order_json": order_json,
        "filled_at": filled_at,
        "has_credit_sign_correction": credit_correction,
    }


def _inv_row(record_id, cohort_name, orders, *, symbol="QQQ", strategy="DEBIT",
             regime="normal", quantity=3, realized_pl=-45.0,
             closed_at="2026-07-20T14:15:06Z", suggestion_id=None,
             fill_source="alpaca_fill_reconciler", ranking_costs=None):
    """A closed-position row carrying a ``fill_orders`` inventory (the new
    multi-fill path). Flattened entry_*/close_* fields are intentionally
    omitted — the inventory is the source of truth for this path."""
    return {
        "record_id": record_id,
        "suggestion_id": suggestion_id or f"sug-{record_id}",
        "cohort_name": cohort_name, "fill_source": fill_source, "symbol": symbol,
        "strategy": strategy, "regime": regime, "quantity": quantity,
        "realized_pl": realized_pl, "closed_at": closed_at,
        "close_reason": "target", "fill_orders": orders,
        "ranking_costs": ranking_costs,
    }


def _by_side(row):
    return {e.side: e for e in build_accrual_examples(row)}


# A credit open (sell to open) then a single buy-to-close — the observed
# credit-structure shape. t0<t1 so the split is deterministic.
def _credit_roundtrip(record_id="p1", cohort="aggressive", routing="broker"):
    return _inv_row(record_id, cohort, [
        _order("o-entry", "sell", 3, filled_at="2026-07-20T13:00:00.000000Z",
               routing=routing),
        _order("o-close", "buy", 3, filled_at="2026-07-20T14:00:00.000000Z",
               routing=routing),
    ])


# --- 1. multi-fill ENTRY (2 fills) ------------------------------------------
class TestMultiFillEntry:
    def test_two_entry_fills_sum_commission(self):
        # buy(entry) x2 @ 0.65 frozen each, v2 0 each, broker realized 0 each;
        # then one sell-to-close so the entry run is exactly the two buys.
        row = _inv_row("p1", "aggressive", [
            _order("e1", "buy", 2, filled_at="2026-07-20T13:00:00.000000Z"),
            _order("e2", "buy", 1, filled_at="2026-07-20T13:05:00.000000Z"),
            _order("c1", "sell", 3, filled_at="2026-07-20T14:00:00.000000Z"),
        ])
        e = _by_side(row)["entry"]
        assert e.fill_count == 2
        assert e.quantity == pytest.approx(3.0)          # 2 + 1 summed
        assert e.current_model_cost.available
        assert e.current_model_cost.amount_usd == pytest.approx(1.30)  # 0.65 x2
        assert e.tcm_v2_cost.available and e.tcm_v2_cost.amount_usd == pytest.approx(0.0)
        assert e.realized_commission.available and e.realized_commission.amount_usd == pytest.approx(0.0)
        # the model over-charges 1.30 vs realized 0; v2 tracks realized (0)
        assert e.current_minus_realized.amount_usd == pytest.approx(1.30)
        assert e.v2_minus_realized.amount_usd == pytest.approx(0.0)

    def test_entry_fill_count_and_multiplier_explicit(self):
        e = _by_side(_credit_roundtrip())["entry"]
        assert e.fill_count == 1
        assert e.multiplier == 100.0
        d = e.as_dict()
        assert d["fill_count"] == 1 and d["multiplier"] == 100.0
        assert d["entry_or_close"] == "entry"


# --- 2. multi-CLOSE (2 close orders) ----------------------------------------
class TestMultiClose:
    def test_two_close_orders_sum_commission(self):
        row = _inv_row("p1", "aggressive", [
            _order("e1", "buy", 4, filled_at="2026-07-20T13:00:00.000000Z"),
            _order("c1", "sell", 2, filled_at="2026-07-20T14:00:00.000000Z"),
            _order("c2", "sell", 2, filled_at="2026-07-20T14:05:00.000000Z"),
        ])
        c = _by_side(row)["close"]
        assert c.side == "close"
        assert c.fill_count == 2
        assert c.quantity == pytest.approx(4.0)          # 2 + 2
        assert c.current_model_cost.amount_usd == pytest.approx(1.30)
        assert c.current_minus_realized.amount_usd == pytest.approx(1.30)
        assert c.v2_minus_realized.amount_usd == pytest.approx(0.0)

    def test_close_fill_gap_context_from_last_contributing_close(self):
        # the representative fill-gap comes from the LATEST contributing close.
        stamped_oj = {"close_fill_gap_cross": -1.10, "close_fill_gap_mid": -1.20}
        row = _inv_row("p1", "aggressive", [
            _order("e1", "buy", 3, filled_at="2026-07-20T13:00:00.000000Z"),
            _order("c1", "sell", 1, filled_at="2026-07-20T14:00:00.000000Z"),
            _order("c2", "sell", 2, avg_fill_price=1.17,
                   order_json=stamped_oj, filled_at="2026-07-20T14:05:00.000000Z"),
        ])
        c = _by_side(row)["close"]
        assert c.realized_spread_or_fill_gap.available is True
        assert c.close_gap_fraction == pytest.approx(0.7, abs=1e-6)


# --- 3. partial-fill quantities summing -------------------------------------
class TestPartialFillQuantities:
    def test_side_quantity_is_sum_of_partial_fills(self):
        row = _inv_row("p1", "aggressive", [
            _order("e1", "buy", 2, filled_at="2026-07-20T13:00:00.000000Z"),
            _order("e2", "buy", 3, filled_at="2026-07-20T13:01:00.000000Z"),
            _order("e3", "buy", 1, filled_at="2026-07-20T13:02:00.000000Z"),
            _order("c1", "sell", 6, filled_at="2026-07-20T14:00:00.000000Z"),
        ])
        e = _by_side(row)["entry"]
        assert e.fill_count == 3
        assert e.quantity == pytest.approx(6.0)          # 2 + 3 + 1
        assert e.current_model_cost.amount_usd == pytest.approx(1.95)  # 0.65 x3


# --- 4. single-fill regression (inventory-of-one) ---------------------------
class TestSingleFillInventory:
    def test_single_entry_only_no_close(self):
        row = _inv_row("p1", "aggressive", [
            _order("e1", "buy", 3, filled_at="2026-07-20T13:00:00.000000Z"),
        ])
        exs = _by_side(row)
        assert set(exs) == {"entry"}
        e = exs["entry"]
        assert e.fill_count == 1
        assert e.current_model_cost.amount_usd == pytest.approx(0.65)
        assert e.tcm_v2_cost.amount_usd == pytest.approx(0.0)
        assert e.realized_commission.amount_usd == pytest.approx(0.0)

    def test_inventory_of_one_matches_collapsed_grain(self):
        # a clean 2-order round trip through the inventory path yields the same
        # per-side commissions the collapsed grain would (0.65 vs 0 vs 0).
        e = _by_side(_credit_roundtrip())["entry"]
        c = _by_side(_credit_roundtrip())["close"]
        for x in (e, c):
            assert x.current_model_cost.amount_usd == pytest.approx(0.65)
            assert x.v2_minus_realized.amount_usd == pytest.approx(0.0)
            assert x.fill_count == 1


# --- 5. duplicate / replay idempotency --------------------------------------
class TestDuplicateAndReplay:
    def test_duplicate_order_id_collapses(self):
        # the SAME order id appears twice in the inventory → counted once.
        dup = _order("e1", "buy", 3, filled_at="2026-07-20T13:00:00.000000Z")
        row = _inv_row("p1", "aggressive", [dup, dict(dup),
                                            _order("c1", "sell", 3,
                                                   filled_at="2026-07-20T14:00:00.000000Z")])
        e = _by_side(row)["entry"]
        assert e.fill_count == 1
        assert e.current_model_cost.amount_usd == pytest.approx(0.65)  # not 1.30

    def test_zero_qty_replay_rows_dropped_but_counted(self):
        # 1 real close + 3 zero-qty replay rows (the observed retry artifact).
        row = _inv_row("p1", "aggressive", [
            _order("e1", "buy", 4, filled_at="2026-07-20T13:00:00.000000Z"),
            _order("c1", "sell", 4, filled_at="2026-07-20T14:00:00.000000Z"),
            _order("c2", "sell", 0, filled_at="2026-07-20T14:01:00.000000Z"),
            _order("c3", "sell", 0, filled_at="2026-07-20T14:02:00.000000Z"),
            _order("c4", "sell", 0, filled_at="2026-07-20T14:03:00.000000Z"),
        ])
        c = _by_side(row)["close"]
        assert c.fill_count == 1                 # only the nonzero fill contributes
        assert c.zero_fill_rows == 3
        assert c.quantity == pytest.approx(4.0)
        assert c.current_model_cost.amount_usd == pytest.approx(0.65)  # not 4x

    def test_payload_duplicate_row_counts_once(self):
        row = _credit_roundtrip()
        acc = build_tcm_v2_accrual({"rows": [row, dict(row)]})
        assert acc.total_examples == 2           # 1 entry + 1 close, not doubled

    def test_pure_function_of_db(self):
        payload = {"rows": [
            _credit_roundtrip("p1"),
            _inv_row("p2", "neutral", [
                _order("x1", "buy", 2, routing="internal",
                       filled_at="2026-07-20T13:00:00.000000Z"),
                _order("x2", "sell", 2, routing="internal",
                       filled_at="2026-07-20T14:00:00.000000Z")]),
        ]}
        assert build_tcm_v2_accrual(payload) == build_tcm_v2_accrual(payload)


# --- 6. model-version drift --------------------------------------------------
class TestVersionDrift:
    def test_version_bump_across_positions_segregates_buckets(self):
        v1 = _credit_roundtrip("p1")
        v2 = _inv_row("p2", "aggressive", [
            _order("e2", "buy", 3, v2_version="tcm_v2_proposal/0.2.0",
                   filled_at="2026-07-20T13:00:00.000000Z"),
            _order("c2", "sell", 3, v2_version="tcm_v2_proposal/0.2.0",
                   filled_at="2026-07-20T14:00:00.000000Z"),
        ])
        acc = build_tcm_v2_accrual({"rows": [v1, v2]})
        live = {b.model_version for b in acc.buckets if b.cohort == "live"}
        assert "tcm_v2_proposal/0.1.0" in live
        assert "tcm_v2_proposal/0.2.0" in live

    def test_mixed_versions_within_a_side_marks_mixed(self):
        # two entry fills stamped with DIFFERENT v2 versions → a `mixed:` key,
        # so the drift is visible, never silently pooled.
        row = _inv_row("p1", "aggressive", [
            _order("e1", "buy", 2, v2_version="tcm_v2_proposal/0.1.0",
                   filled_at="2026-07-20T13:00:00.000000Z"),
            _order("e2", "buy", 1, v2_version="tcm_v2_proposal/0.2.0",
                   filled_at="2026-07-20T13:05:00.000000Z"),
            _order("c1", "sell", 3, filled_at="2026-07-20T14:00:00.000000Z"),
        ])
        e = _by_side(row)["entry"]
        assert e.model_version == "mixed:tcm_v2_proposal/0.1.0+tcm_v2_proposal/0.2.0"
        assert e.v2_stamp_present is True


# --- 7. correction-marker rows ----------------------------------------------
class TestCreditSignCorrection:
    def test_correction_marker_noted_not_recorrected(self):
        # an F-CREDIT-SIGN row carries a corrected magnitude; the flag surfaces
        # and commission (abs) is unaffected — nothing is re-corrected.
        row = _inv_row("p1", "aggressive", [
            _order("e1", "buy", 3, avg_fill_price=-1.48, credit_correction=True,
                   filled_at="2026-07-20T13:00:00.000000Z"),
            _order("c1", "sell", 3, filled_at="2026-07-20T14:00:00.000000Z"),
        ])
        e = _by_side(row)["entry"]
        assert e.has_credit_sign_correction is True
        assert e.current_model_cost.amount_usd == pytest.approx(0.65)  # magnitude
        assert e.as_dict()["has_credit_sign_correction"] is True

    def test_no_correction_flag_false(self):
        e = _by_side(_credit_roundtrip())["entry"]
        assert e.has_credit_sign_correction is False


# --- 8. missing v2 stamps (pre-#1278) ---------------------------------------
class TestMissingStamps:
    def test_all_unstamped_side_v2_unavailable_clean(self):
        row = _inv_row("p1", "aggressive", [
            _order("e1", "buy", 2, v2_stamp=None,
                   filled_at="2026-07-20T13:00:00.000000Z"),
            _order("e2", "buy", 1, v2_stamp=None,
                   filled_at="2026-07-20T13:05:00.000000Z"),
            _order("c1", "sell", 3, v2_stamp=None,
                   filled_at="2026-07-20T14:00:00.000000Z"),
        ])
        e = _by_side(row)["entry"]
        assert e.v2_stamp_present is False
        assert e.model_version == "unavailable_no_v2_stamp"
        assert e.tcm_v2_cost.available is False
        assert e.tcm_v2_cost.unavailable_reason == "no_v2_stamp_pre_1278"
        assert e.tcm_v2_cost.amount_usd is None          # never a fabricated 0
        # current is still real; v2 delta abstains, current delta computes
        assert e.current_model_cost.available is True
        assert e.current_model_cost.amount_usd == pytest.approx(1.30)
        assert e.current_minus_realized.available is True
        assert e.v2_minus_realized.available is False

    def test_missing_tcm_on_one_order_types_current_incomplete(self):
        # H9: one entry fill has no tcm → the side current total is UNAVAILABLE
        # (a partial total is never a silent undercount), and counted.
        row = _inv_row("p1", "aggressive", [
            _order("e1", "buy", 2, filled_at="2026-07-20T13:00:00.000000Z"),
            _order("e2", "buy", 1, has_tcm=False,
                   filled_at="2026-07-20T13:05:00.000000Z"),
            _order("c1", "sell", 3, filled_at="2026-07-20T14:00:00.000000Z"),
        ])
        e = _by_side(row)["entry"]
        assert e.current_model_cost.available is False
        assert "incomplete_side" in (e.current_model_cost.unavailable_reason or "")
        assert e.fill_count == 2


# --- 9. per-routing realized commission -------------------------------------
class TestRealizedPerRouting:
    def test_all_broker_side_realized_known_zero(self):
        e = _by_side(_credit_roundtrip(routing="broker"))["entry"]
        assert e.realized_commission.available is True
        assert e.realized_commission.amount_usd == pytest.approx(0.0)

    def test_all_internal_side_realized_unavailable(self):
        e = _by_side(_credit_roundtrip("s1", "neutral", "internal"))["entry"]
        assert e.realized_commission.available is False
        assert e.current_minus_realized.available is False
        assert e.v2_minus_realized.available is False
        # current model estimate is still typed (present)
        assert e.current_model_cost.available is True

    def test_mixed_broker_and_internal_side_realized_unavailable(self):
        # a side with ANY internal fill can't state a broker-true total (H9).
        row = _inv_row("p1", "aggressive", [
            _order("e1", "buy", 2, routing="broker",
                   filled_at="2026-07-20T13:00:00.000000Z"),
            _order("e2", "buy", 1, routing="internal",
                   filled_at="2026-07-20T13:05:00.000000Z"),
            _order("c1", "sell", 3, routing="broker",
                   filled_at="2026-07-20T14:00:00.000000Z"),
        ])
        e = _by_side(row)["entry"]
        assert e.realized_commission.available is False
        assert "incomplete_side" in (e.realized_commission.unavailable_reason or "")
        assert e.current_minus_realized.available is False


# --- 10. boundary adjudication ----------------------------------------------
class TestBoundaryAdjudication:
    def test_credit_open_splits_at_side_flip(self):
        entry, close = _split_fill_inventory([
            _order("s1", "sell", 3, filled_at="2026-07-20T13:00:00.000000Z"),
            _order("b1", "buy", 3, filled_at="2026-07-20T14:00:00.000000Z"),
            _order("b2", "buy", 3, filled_at="2026-07-20T14:05:00.000000Z"),
        ])
        assert [o["order_id"] for o in entry] == ["s1"]
        assert [o["order_id"] for o in close] == ["b1", "b2"]

    def test_debit_open_splits_at_side_flip(self):
        entry, close = _split_fill_inventory([
            _order("b1", "buy", 4, filled_at="2026-07-20T13:00:00.000000Z"),
            _order("s1", "sell", 4, filled_at="2026-07-20T14:00:00.000000Z"),
        ])
        assert [o["order_id"] for o in entry] == ["b1"]
        assert [o["order_id"] for o in close] == ["s1"]

    def test_leading_zero_qty_does_not_define_side(self):
        # a leading zero-qty artifact of the opposite side must not flip the
        # opening side: the first NONZERO fill defines it.
        entry, close = _split_fill_inventory([
            _order("z0", "buy", 0, filled_at="2026-07-20T12:59:00.000000Z"),
            _order("s1", "sell", 3, filled_at="2026-07-20T13:00:00.000000Z"),
            _order("b1", "buy", 3, filled_at="2026-07-20T14:00:00.000000Z"),
        ])
        # opening side = sell (first nonzero); the leading zero buy sorts before
        # it but shares neither the flip nor the qty.
        assert [o["order_id"] for o in entry] == ["z0", "s1"]
        assert [o["order_id"] for o in close] == ["b1"]

    def test_single_side_no_flip_is_entry_only(self):
        entry, close = _split_fill_inventory([
            _order("b1", "buy", 2, filled_at="2026-07-20T13:00:00.000000Z"),
            _order("b2", "buy", 1, filled_at="2026-07-20T13:05:00.000000Z"),
        ])
        assert len(entry) == 2 and close == []

    def test_out_of_order_timestamps_are_sorted(self):
        # inventory given out of order still splits by time (deterministic).
        entry, close = _split_fill_inventory([
            _order("b1", "buy", 3, filled_at="2026-07-20T14:00:00.000000Z"),
            _order("s1", "sell", 3, filled_at="2026-07-20T13:00:00.000000Z"),
        ])
        assert [o["order_id"] for o in entry] == ["s1"]
        assert [o["order_id"] for o in close] == ["b1"]


# --- 11. cohort separation + identity ---------------------------------------
class TestCohortAndIdentity:
    def test_shadow_never_pools_into_live(self):
        acc = build_tcm_v2_accrual({"rows": [
            _credit_roundtrip("L1", "aggressive", "broker"),
            _credit_roundtrip("S1", "neutral", "internal"),
            _credit_roundtrip("U1", None, "internal"),
        ]})
        cohorts = {b.cohort for b in acc.buckets}
        assert cohorts == {"live", "shadow", "unattributed"}
        live = [b for b in acc.buckets if b.cohort == "live"]
        assert sum(b.n_examples for b in live) == 2

    def test_entry_close_share_spine_identity(self):
        exs = _by_side(_credit_roundtrip("p1"))
        assert exs["entry"].record_id == exs["close"].record_id == "p1"
        assert exs["entry"].suggestion_id == exs["close"].suggestion_id == "sug-p1"
        assert exs["entry"].example_id == "p1:entry"
        assert exs["close"].example_id == "p1:close"


# --- 12. version-bucket fill coverage ---------------------------------------
class TestBucketFillCoverage:
    def test_bucket_counts_multi_fill_and_fills_covered(self):
        # entry filled across 2 orders + 1 close order = 3 fills; the entry
        # example is multi-fill, the close is not.
        row = _inv_row("p1", "aggressive", [
            _order("e1", "buy", 2, filled_at="2026-07-20T13:00:00.000000Z"),
            _order("e2", "buy", 1, filled_at="2026-07-20T13:05:00.000000Z"),
            _order("c1", "sell", 3, filled_at="2026-07-20T14:00:00.000000Z"),
        ])
        acc = build_tcm_v2_accrual({"rows": [row]})
        live = [b for b in acc.buckets if b.cohort == "live"][0]
        assert live.fills_covered == 3           # 2 (entry) + 1 (close)
        assert live.n_multi_fill == 1            # only the entry example
        assert live.as_dict()["fills_covered"] == 3


# --- 13. SQL + render + coexistence -----------------------------------------
class TestSqlRenderCoexist:
    def test_study_sql_emits_fill_inventory_read_only(self):
        assert "fill_orders" in STUDY_SQL
        assert "json_agg" in STUDY_SQL
        up = STUDY_SQL.upper()
        for verb in ("INSERT ", "UPDATE ", "DELETE ", "DROP ", "ALTER ",
                     "CREATE ", "TRUNCATE ", "GRANT "):
            assert verb not in up
        # still a single top-level json_build_object projection
        assert up.count("SELECT JSON_BUILD_OBJECT") == 1

    def test_render_includes_fill_coverage(self):
        payload = {"generated_at": "2026-07-20", "source": "synthetic",
                   "rows": [_inv_row("p1", "aggressive", [
                       _order("e1", "buy", 2, filled_at="2026-07-20T13:00:00.000000Z"),
                       _order("e2", "buy", 1, filled_at="2026-07-20T13:05:00.000000Z"),
                       _order("c1", "sell", 3, filled_at="2026-07-20T14:00:00.000000Z"),
                   ])]}
        md = render_markdown(build_study(payload))
        assert "Fill coverage" in md
        assert "multi-fill" in md

    def test_legacy_and_inventory_rows_coexist(self):
        # a payload with a legacy (flattened, no fill_orders) row AND an
        # inventory row both produce examples through build_study.
        legacy = {
            "record_id": "L", "suggestion_id": "sug-L", "cohort_name": "aggressive",
            "fill_source": "alpaca_fill_reconciler", "symbol": "QQQ",
            "strategy": "DEBIT", "regime": "normal", "quantity": 1,
            "realized_pl": -5.0, "closed_at": "2026-07-20T14:00:00Z",
            "close_reason": "target", "entry_side": "buy", "entry_fill_price": 1.48,
            "entry_requested_price": 1.47, "entry_filled_qty": 1,
            "entry_fees_usd": 0.0, "entry_execution_mode": "alpaca_live",
            "entry_has_alpaca_oid": True, "entry_broker_status": "filled",
            "entry_tcm": {"fees_usd": 0.65, "expected_fill_price": 1.46},
            "close_side": None, "close_fill_price": None,
        }
        acc = build_tcm_v2_accrual({"rows": [legacy, _credit_roundtrip("p1")]})
        ids = {e for b in acc.buckets for e in (b.model_version,)}
        assert acc.total_examples == 3           # legacy entry(1) + rt entry+close(2)

    def test_example_as_dict_json_safe_with_task_aliases(self):
        e = _by_side(_credit_roundtrip())["entry"]
        d = json.loads(json.dumps(e.as_dict()))
        # task-named output fields all present
        for k in ("current_model", "tcm_v2", "realized", "routing", "strategy",
                  "legs", "quantity", "entry_or_close", "fill_count",
                  "current_error", "v2_error", "model_version", "known_at"):
            assert k in d, f"missing task output field {k!r}"
        assert d["current_error"]["amount_usd"] == pytest.approx(0.65)
        assert d["known_at"] == "2026-07-20T14:15:06Z"
