"""Realized entry/close cost comparison — multi-basis COST CONSUMER #3
(OBSERVE-ONLY, operator-invoked).

Consumers #1 (PR #1258) and #2 (PR #1265) attach the ESTIMATED and EXECUTABLE
cost bases (scanner_estimate, scanner_unified_final, ranker_model,
stage_executable_cross) to ``candidate_terminal_dispositions.detail
->cost_reconciliation`` at the disposition-write seam. At that seam the REALIZED
basis is typed UNAVAILABLE by construction (``no_broker_fill_pre_execution`` —
there is no broker fill before execution). This module is CONSUMER #3: it closes
the loop AFTER the fact by comparing the PERSISTED estimated/executable cost
values against the REALIZED entry and close fills for round-trips that already
happened.

WHY A HISTORICAL SUGGESTION->ORDER->POSITION CLI (not a disposition consumer):
``candidate_terminal_dispositions`` is EMPTY today (the migration is applied but
no cycle has written a natural row yet — first rows land on the next weekday
cycle). A realized comparison that JOINED through that table would have zero
rows. But the realized-vs-persisted-estimate comparison does NOT need the
disposition artifact: the spine ``paper_positions (closed) -> trade_suggestions
-> paper_orders (open + close fills)`` already links historically (verified
read-only 2026-07-18: 86 closed positions, 86/86 with suggestion_id + realized_pl,
80/86 open orders carry a persisted ``requested_price``, 6/86 closes carry the
persisted ``close_fill_gap`` executable stamp). So this consumer reads that spine
directly.

HONESTY CONTRACT (charter — the same H9 both-ends discipline as consumers #1/#2):
  - COMPARE against PERSISTED estimates ONLY; NEVER recompute a decision-time
    value we did not store. The estimates read here are all durable columns:
    ``paper_orders.requested_price`` (the limit we asked at stage),
    ``paper_orders.tcm`` (the stage-time TransactionCostModel estimate),
    ``trade_suggestions.ranking_costs`` (the ranker's round-trip fee estimate),
    and the ``close_fill_gap`` stage stamp (cross = executable full-cross,
    mid = trigger mid). The scanner_estimate / scanner_unified bases are NOT
    persisted historically (they only exist once dispositions populate) and are
    therefore out of scope here — typed absent, never reconstructed.
  - The REALIZED values are the DB rows of record: ``paper_orders.avg_fill_price``
    / ``filled_qty`` (the actual fills) and ``paper_positions.realized_pl`` (the
    authoritative round-trip P&L).
  - REALIZED COMMISSION is PER-ROUTING, not blanket-unavailable (07-18 review
    correction). ``paper_orders.fees_usd`` means TWO different things by routing,
    read read-only from the live data:
      * BROKER-ROUTED fills (``execution_mode`` alpaca_live/alpaca_paper AND
        ``alpaca_order_id`` present AND ``broker_status='filled'``) carry the REAL
        Alpaca commission that ``alpaca_fill_reconciler`` stamped — today $0
        (zero-commission options). Verified: on ALL 42 broker-routed filled
        orders ``fees_usd=0`` and it NEVER equals ``tcm.fees_usd`` (0/42). For
        these rows realized commission is KNOWN (= fees_usd, source
        ``broker_reconciler``) — reporting it UNAVAILABLE would be OVER-abstention,
        the mirror image of H9.
      * INTERNAL / non-broker fills (internal_paper / shadow_blocked /
        submission_failed) carry an estimate-or-ambiguous ``fees_usd`` (it equals
        ``tcm.fees_usd`` on 76/120 internal_paper + 12/12 shadow_blocked) — there
        realized commission is typed UNAVAILABLE, never fabricated.
  - SIGN SAFETY (2026-07-08 close_fill_gap sign-bug class): the broker
    ``avg_fill_price`` sign is UNRELIABLE for direction (verified: sell fills are
    positive 68x and negative 12x in the live data). Entry adverse/favorable
    direction is therefore derived from the reliable ``side`` + the fill
    MAGNITUDE, NEVER the raw signed fill. The close side reuses the frozen
    ``close_fill_gap.broker_fill_to_mark_basis`` (negation) via
    ``cost_basis.extract_realized_close_costs`` — the canonical sign-correct path.
    Fills on F-CREDIT-SIGN-marked rows are already the CORRECTED magnitude (the
    correction ran 2026-07-18 ~14:20Z — 19 orders carry
    ``order_json.f_credit_sign_correction``, census fp b780271c…); the abs()-based
    entry path is immune to the correction either way (magnitude only).
  - COMPARE, NEVER SUM. Estimated, executable and realized are alternative
    MEASUREMENTS of one round trip. Every output is a typed pairwise delta
    (a - b) or a passthrough; no field ever adds two bases together.
  - COHORTS ARE SEPARATE. Live champion (aggressive, real broker fills) vs shadow
    (neutral / conservative, internal synthetic fills — "partly fiction" per
    docs/specs/shadow_fill_realism.md) vs unattributed (no cohort). Shadow
    magnitudes NEVER aggregate into live. Each row also carries a fill-realism
    flag (broker vs internal) from ``fill_source``.
  - ENTRY and EXIT are explicit and never conflated. Units are explicit on every
    number: PRICE fields are per-structure-contract dollars-per-contract;
    USD fields state PER_STRUCTURE_CONTRACT (x100) vs TOTAL (x100 x qty).
  - H9: a value that cannot be honestly priced (missing fill, missing estimate,
    missing stamp) is typed UNAVAILABLE and COUNTED, never scored as zero.

OPERATION (mirrors scripts/analytics/challenger_study.py):
  - This file lives OUTSIDE ``packages/quantum`` so the ``cost_basis`` import-lock
    sweep never sees it, and NO scanner/ranker/gate/executor imports it. It only
    READS the frozen ``cost_basis`` types + ``extract_realized_close_costs``; it
    changes nothing in the live path and feeds no decision.
  - It opens NO database connection and touches NO network. ``--emit-sql`` prints
    the exact READ-ONLY query an operator runs (Supabase MCP / psql);
    ``--rows-json`` consumes the JSON that query returns; ``--out`` writes a dated
    markdown report. There is no live-DB code path to rot.

TCM v2 REALIZED-ACCRUAL EXTENSION (Lane B, observe-only — see the delimited
section below ``build_study``): this module also ACCRUES realized-vs-model
COMMISSION examples from the #1278 stage-stamped ``tcm.tcm_v2_proposal``. For
every eligible entry AND close side of a closed round-trip it emits one typed
example — current-model commission vs proposed-v2 commission vs realized broker
commission, plus the two owner-facing deltas (``current_minus_realized`` /
``v2_minus_realized``) — version-segregated by the stamp's own ``model_version``.
It is a PURE function of the DB payload (idempotent; re-run = same output);
"accrual over time" is the CLI's dated snapshots (``--accrual-json`` + the dated
markdown), NOT a new table. It imports NOTHING from ``tcm_v2_proposal`` — it
reads the already-persisted stamp dict — and feeds no decision. PROMOTE_TCM_V2
stays false: nothing here promotes the model.
"""

from __future__ import annotations

import argparse
import json
import statistics
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

from packages.quantum.analytics.cost_basis import (
    OPTION_MULTIPLIER,
    CostBasisKind,
    CostComponent,
    CostDelta,
    CostSide,
    CostSource,
    CostUnit,
    Provenance,
    extract_realized_close_costs,
)

MODEL_VERSION = "realized-cost-study/consumer3-1.0"

# Read-only query an operator runs (Supabase MCP / psql) to regenerate the
# --rows-json payload. ONE row per CLOSED position (the realized round-trip grain
# — a suggestion can fan out into one position per cohort, so we key on the
# position, never dedup by suggestion, to keep cohorts separate). Emits the
# REALIZED fills + the PERSISTED estimates side by side; the mapper computes the
# typed deltas offline. STRICTLY READ-ONLY: a single SELECT, no write verbs.
STUDY_SQL = r"""
WITH cp AS (
  SELECT pp.id AS position_id, pp.suggestion_id, pp.symbol, pp.strategy,
         pp.regime, pp.quantity, pp.realized_pl, pp.cohort_id, pp.fill_source,
         pp.close_reason, pp.closed_at
  FROM paper_positions pp
  WHERE pp.status = 'closed'
),
-- OPEN order = the EARLIEST filled order for the position (its fill established
-- the entry). CLOSE order = the LATEST filled order (picked below, and joined
-- only when strictly later than the open, so a single-fill position has no close).
open_o AS (
  SELECT DISTINCT ON (po.position_id)
    po.position_id, po.side, po.avg_fill_price, po.requested_price,
    po.filled_qty, po.fees_usd, po.tcm, po.filled_at,
    po.execution_mode, (po.alpaca_order_id IS NOT NULL) AS has_alpaca_oid,
    po.broker_status
  FROM paper_orders po
  WHERE po.status = 'filled'
  ORDER BY po.position_id, po.filled_at ASC
),
close_o AS (
  SELECT DISTINCT ON (po.position_id)
    po.position_id, po.side, po.avg_fill_price, po.requested_price,
    po.filled_qty, po.fees_usd, po.order_json, po.tcm, po.filled_at,
    po.execution_mode, (po.alpaca_order_id IS NOT NULL) AS has_alpaca_oid,
    po.broker_status
  FROM paper_orders po
  WHERE po.status = 'filled'
  ORDER BY po.position_id, po.filled_at DESC
)
SELECT json_build_object(
  'schema_version', 1,
  'model_version', 'realized-cost-study/consumer3-1.0',
  'generated_at', to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD'),
  'source', 'paper_positions(closed) JOIN trade_suggestions JOIN paper_orders(open+close fills)',
  'win_rule', 'realized_pl > 0 (authoritative DB row of record)',
  'rows', COALESCE(json_agg(row_to_json(x)
            ORDER BY x.cohort_name, x.closed_at, x.record_id), '[]'::json)
)
FROM (
  SELECT
    cp.position_id::text                                   AS record_id,
    cp.suggestion_id::text                                 AS suggestion_id,
    COALESCE(plc.cohort_name, 'unattributed')              AS cohort_name,
    cp.fill_source                                         AS fill_source,
    cp.symbol                                              AS symbol,
    cp.strategy                                            AS strategy,
    COALESCE(cp.regime, 'unknown')                         AS regime,
    cp.quantity                                            AS quantity,
    round(cp.realized_pl, 2)                               AS realized_pl,
    to_char(cp.closed_at AT TIME ZONE 'UTC',
            'YYYY-MM-DD"T"HH24:MI:SS"Z"')                  AS closed_at,
    cp.close_reason                                        AS close_reason,
    -- ENTRY realized fill + PERSISTED estimates (requested limit, TCM stamp)
    oo.side                                                AS entry_side,
    oo.avg_fill_price                                      AS entry_fill_price,
    oo.requested_price                                     AS entry_requested_price,
    oo.filled_qty                                          AS entry_filled_qty,
    -- fees_usd is REAL broker commission on broker-routed rows, estimate on
    -- internal rows — the routing columns below disambiguate (never blanket).
    oo.fees_usd                                            AS entry_fees_usd,
    oo.execution_mode                                      AS entry_execution_mode,
    oo.has_alpaca_oid                                      AS entry_has_alpaca_oid,
    oo.broker_status                                       AS entry_broker_status,
    oo.tcm                                                 AS entry_tcm,
    -- CLOSE realized fill (broker net fill) + PERSISTED executable stamp
    co.side                                                AS close_side,
    co.avg_fill_price                                      AS close_fill_price,
    co.filled_qty                                          AS close_filled_qty,
    co.fees_usd                                            AS close_fees_usd,
    co.execution_mode                                      AS close_execution_mode,
    co.has_alpaca_oid                                      AS close_has_alpaca_oid,
    co.broker_status                                       AS close_broker_status,
    co.order_json                                          AS close_order_json,
    -- CLOSE-order TCM stamp: carries `tcm_v2_proposal` on post-#1278 close
    -- rows (the close-side dual-run record). Absent on pre-#1278 closes ->
    -- the accrual types the v2 side UNAVAILABLE, never zero.
    co.tcm                                                 AS close_tcm,
    -- PERSISTED ranker fee estimate (present only on ranked suggestions)
    ts.ranking_costs                                       AS ranking_costs
  FROM cp
  LEFT JOIN open_o  oo  ON oo.position_id = cp.position_id
  LEFT JOIN close_o co  ON co.position_id = cp.position_id
                       AND co.filled_at > oo.filled_at
  LEFT JOIN trade_suggestions ts ON ts.id = cp.suggestion_id
  LEFT JOIN policy_lab_cohorts plc ON plc.id = cp.cohort_id
) x;
""".strip()


# --- cohort / fill-realism classification -----------------------------------
# Live champion is the aggressive cohort (real capital, real broker fills);
# neutral + conservative are shadow (internal synthetic fills, no real capital).
_SHADOW_COHORTS = frozenset({"neutral", "conservative"})


def classify_cohort(cohort_name: Optional[str]) -> str:
    """live | shadow | unattributed — the P&L-comparability partition. Shadow
    magnitudes NEVER aggregate into live (docs/specs/shadow_fill_realism.md)."""
    name = (cohort_name or "").strip().lower()
    if name == "aggressive":
        return "live"
    if name in _SHADOW_COHORTS:
        return "shadow"
    return "unattributed"


def fill_realism(fill_source: Optional[str]) -> str:
    """broker (a real Alpaca fill) | internal (synthetic / evaluator / unknown).
    Orthogonal to cohort: it flags whether the fill itself is broker-true."""
    src = (fill_source or "").strip().lower()
    if src.startswith("alpaca"):
        return "broker"
    return "internal"


# --- small numeric helpers --------------------------------------------------
def _coerce_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f


def _abs(value: Any) -> Optional[float]:
    f = _coerce_float(value)
    return None if f is None else abs(f)


# --- typed pairwise delta (reuses the public cost_basis.CostDelta) ----------
def _delta(
    name: str,
    a: Optional[CostComponent],
    b: Optional[CostComponent],
    note: str,
) -> CostDelta:
    """a - b as a typed CostDelta; UNAVAILABLE (no fabricated zero) when either
    side is missing or typed-unavailable. Mirrors cost_basis._pair_delta so the
    never-fabricate discipline is identical, but stays a pure COMPARE — the two
    inputs are never summed."""
    if a is None or b is None or not a.available or not b.available:
        reasons = []
        for label, c in (("a", a), ("b", b)):
            if c is None:
                reasons.append(f"{label}=missing")
            elif not c.available:
                reasons.append(f"{label}={c.unavailable_reason}")
        return CostDelta(
            name=name, amount_usd=None, available=False,
            reason=";".join(reasons) or "inputs_unavailable",
            detail={"note": note},
        )
    return CostDelta(
        name=name,
        amount_usd=float(a.amount_usd) - float(b.amount_usd),
        available=True,
        detail={"note": note, "a_usd": a.amount_usd, "b_usd": b.amount_usd},
    )


# --- realized-entry cost components (from persisted columns, sign-safe) ------
_ENTRY_PROV = Provenance(
    model_version="paper_orders.avg_fill_price|requested_price|tcm@persisted",
    source_detail="sign-safe: magnitude x side (never the raw broker fill sign)",
)


def _entry_adverse_slip_usd(
    side: Optional[str],
    fill_mag: Optional[float],
    reference_mag: Optional[float],
) -> Optional[float]:
    """Per-structure-contract ADVERSE slippage in USD: how much WORSE the
    realized fill magnitude was than a reference magnitude, direction derived
    from the reliable ``side`` (never the corrupt fill sign).

      buy  (debit paid):     adverse = (|fill| - |ref|) * 100   (paid more = adverse)
      sell (credit received):adverse = (|ref| - |fill|) * 100   (got less = adverse)

    Positive = adverse (realized worse than the reference); negative = favorable.
    None when any input is missing or the side is unknown (typed UNAVAILABLE)."""
    s = (side or "").strip().lower()
    if fill_mag is None or reference_mag is None or s not in ("buy", "sell"):
        return None
    if s == "buy":
        return (fill_mag - reference_mag) * OPTION_MULTIPLIER
    return (reference_mag - fill_mag) * OPTION_MULTIPLIER


def _entry_missing_reason(
    fill_mag: Optional[float], reference_mag: Optional[float],
    side: Optional[str], reference_absent_reason: str,
) -> str:
    if fill_mag is None:
        return "entry_fill_missing"
    if reference_mag is None:
        return reference_absent_reason
    return "entry_side_unknown"


def _entry_delta(
    name: str,
    side: Optional[str],
    fill_mag: Optional[float],
    reference_mag: Optional[float],
    reference_absent_reason: str,
    note: str,
) -> CostDelta:
    """The REALIZED entry adverse-slippage comparison as a typed CostDelta:
    per-structure-contract USD, direction derived from ``side`` + fill MAGNITUDE
    (sign-safe). This IS the realized-fill-vs-estimate difference (COMPARE, never
    SUM). Typed UNAVAILABLE — never a fabricated zero — when any input is
    missing. Detail carries both magnitudes so a reader can see the two sides of
    the comparison, never a summed number."""
    val = _entry_adverse_slip_usd(side, fill_mag, reference_mag)
    if val is None:
        return CostDelta(
            name=name, amount_usd=None, available=False,
            reason=_entry_missing_reason(
                fill_mag, reference_mag, side, reference_absent_reason),
            detail={"note": note},
        )
    return CostDelta(
        name=name, amount_usd=val, available=True,
        detail={
            "note": note,
            "realized_fill_per_contract": fill_mag,
            "reference_per_contract": reference_mag,
            "side": side,
        },
    )


# --- realized commission (PER-ROUTING; never blanket-unavailable) ------------
# A fill is BROKER-ROUTED — its ``fees_usd`` is the REAL Alpaca commission the
# reconciler stamped ($0 for options today) — iff it executed at the broker.
# Verified read-only 2026-07-18: on ALL 42 broker-routed filled orders
# ``fees_usd = 0`` and it NEVER equals ``tcm.fees_usd`` (0/42). Internal /
# non-broker fills carry an estimate-or-ambiguous ``fees_usd`` (it equals
# ``tcm.fees_usd`` on 76/120 internal_paper + 12/12 shadow_blocked) — there the
# realized commission is typed UNAVAILABLE, never fabricated. Reporting the
# broker-known value UNAVAILABLE would be OVER-abstention (the mirror of H9).
_BROKER_EXEC_MODES = frozenset({"alpaca_live", "alpaca_paper"})
_COMMISSION_PROV = Provenance(
    model_version="paper_orders.fees_usd@broker_reconciler",
    source_detail="real Alpaca commission on broker-routed fills; $0 options today",
)


def _broker_routed(
    execution_mode: Any, has_alpaca_oid: Any, broker_status: Any
) -> bool:
    """True only for a genuine broker execution: an alpaca execution_mode AND a
    broker order id AND broker_status='filled'. Excludes internal_paper,
    shadow_blocked, and submission_failed (verified: those never carry a real
    $0-stamped commission)."""
    return (
        str(execution_mode or "").strip().lower() in _BROKER_EXEC_MODES
        and bool(has_alpaca_oid)
        and str(broker_status or "").strip().lower() == "filled"
    )


def _realized_commission_component(
    name: str, side: CostSide, execution_mode: Any, has_alpaca_oid: Any,
    broker_status: Any, fees_usd: Any,
) -> CostComponent:
    """Realized commission for ONE fill, typed PER ROUTING (TOTAL USD).
    Broker-routed → KNOWN (= ``fees_usd``, source broker_reconciler; $0 today).
    Internal / non-broker → typed UNAVAILABLE (fees_usd is estimate-or-ambiguous
    there). Never blanket-unavailable when the real value is known."""
    if not _broker_routed(execution_mode, has_alpaca_oid, broker_status):
        return CostComponent.make_unavailable(
            name, CostSource.REALIZED, side, CostBasisKind.REALIZED,
            CostUnit.TOTAL, "internal_fill_commission_not_broker_stamped",
            provenance=_COMMISSION_PROV,
        )
    fee = _coerce_float(fees_usd)
    if fee is None:
        return CostComponent.make_unavailable(
            name, CostSource.REALIZED, side, CostBasisKind.REALIZED,
            CostUnit.TOTAL, "broker_routed_but_fees_missing",
            provenance=_COMMISSION_PROV,
        )
    return CostComponent(
        name=name, source=CostSource.REALIZED, side=side,
        basis=CostBasisKind.REALIZED, unit=CostUnit.TOTAL,
        amount_usd=abs(fee), provenance=_COMMISSION_PROV,
    )


def _tcm_fees_usd(tcm: Any) -> Optional[float]:
    if isinstance(tcm, Mapping):
        return _coerce_float(tcm.get("fees_usd"))
    return None


def _tcm_commission_component(tcm: Any) -> CostComponent:
    """The persisted TCM commission ESTIMATE as a typed component (entry
    one-way, TOTAL USD) — the b-side for the realized-vs-estimate commission
    delta. Typed UNAVAILABLE when tcm has no fees_usd."""
    fee = _tcm_fees_usd(tcm)
    if fee is None:
        return CostComponent.make_unavailable(
            "tcm_commission_estimate", CostSource.TCM, CostSide.ENTRY,
            CostBasisKind.ESTIMATED, CostUnit.TOTAL,
            "tcm_fees_not_persisted",
            provenance=Provenance(model_version="paper_orders.tcm@persisted"),
        )
    return CostComponent(
        name="tcm_commission_estimate", source=CostSource.TCM,
        side=CostSide.ENTRY, basis=CostBasisKind.ESTIMATED, unit=CostUnit.TOTAL,
        amount_usd=fee, provenance=Provenance(model_version="paper_orders.tcm@persisted"),
    )


# --- per-row typed comparison ------------------------------------------------
@dataclass(frozen=True)
class RowComparison:
    record_id: str
    cohort: str            # live | shadow | unattributed
    fill_realism: str      # broker | internal
    symbol: str
    strategy: str
    regime: str
    quantity: Optional[float]
    realized_pl: Optional[float]
    closed_at: str
    close_reason: Optional[str]
    entry_side: Optional[str]
    close_side: Optional[str]
    has_close: bool
    # typed deltas (COMPARE, never SUM)
    entry_slip_vs_requested: CostDelta        # realized entry fill vs persisted requested limit
    entry_slip_vs_tcm: CostDelta              # realized entry fill vs persisted tcm expected fill
    close_realized_vs_executable_cross: CostDelta  # realized close fill vs persisted executable cross
    close_gap_fraction: Optional[float]       # where fill sits between cross (0) and mid (1)
    # realized commission, typed PER ROUTING (broker-known vs internal-unavailable)
    entry_realized_commission: CostComponent
    close_realized_commission: CostComponent
    entry_commission_vs_tcm: CostDelta        # realized commission vs persisted TCM commission estimate
    # persisted-estimate context (displayed, NEVER added to realized)
    persisted_estimates: Mapping[str, Any]


def _tcm_expected_fill(tcm: Any) -> Optional[float]:
    if isinstance(tcm, Mapping):
        return _abs(tcm.get("expected_fill_price"))
    return None


def _persisted_estimate_context(row: Mapping[str, Any]) -> Dict[str, Any]:
    """Verbatim persisted-estimate values for display — labeled ESTIMATE and
    NEVER summed with the realized numbers. Units stated inline."""
    tcm = row.get("entry_tcm") if isinstance(row.get("entry_tcm"), Mapping) else {}
    rc = row.get("ranking_costs") if isinstance(row.get("ranking_costs"), Mapping) else {}
    ctx: Dict[str, Any] = {
        "entry_requested_price_per_contract": _abs(row.get("entry_requested_price")),
        "entry_fees_usd_note": (
            "paper_orders.fees_usd is the REAL Alpaca commission on broker-routed "
            "fills (the realized commission — see entry_realized_commission), and "
            "an estimate-or-ambiguous value on internal fills; it is disambiguated "
            "PER ROUTING, never treated as a blanket estimate"
        ),
        "tcm_estimate": {
            "expected_fill_price_per_contract": _tcm_expected_fill(tcm),
            "fees_usd_total_estimate": _coerce_float(tcm.get("fees_usd")),
            "expected_slippage_usd_total_estimate": _coerce_float(tcm.get("expected_slippage_usd")),
            "expected_spread_cost_usd_total_estimate": _coerce_float(tcm.get("expected_spread_cost_usd")),
            "used_fallback": bool(tcm.get("used_fallback")) if tcm else None,
        } if tcm else None,
        "ranker_estimate": {
            "expected_fees_total_usd_estimate": _coerce_float(rc.get("expected_fees_total")),
            "leg_count": rc.get("leg_count"),
            "round_trip_sides": rc.get("round_trip_sides"),
        } if rc else None,
    }
    return ctx


def build_row(row: Mapping[str, Any]) -> RowComparison:
    """Map ONE db row to its typed realized-vs-persisted-estimate comparison.
    Pure; never raises on a partial row (missing pieces type UNAVAILABLE)."""
    cohort = classify_cohort(row.get("cohort_name"))
    realism = fill_realism(row.get("fill_source"))
    qty = _coerce_float(row.get("quantity"))

    entry_side = row.get("entry_side")
    entry_fill_mag = _abs(row.get("entry_fill_price"))
    requested_mag = _abs(row.get("entry_requested_price"))
    tcm_fill_mag = _tcm_expected_fill(row.get("entry_tcm"))

    # ENTRY realized adverse slippage vs the two persisted references.
    entry_slip_vs_requested = _entry_delta(
        "entry_realized_fill_vs_requested_limit", entry_side, entry_fill_mag,
        requested_mag, "requested_price_not_persisted",
        note=("per-structure-contract USD; positive = realized entry fill WORSE "
              "than the persisted requested limit (adverse), sign-safe via side"),
    )
    entry_slip_vs_tcm = _entry_delta(
        "entry_realized_fill_vs_tcm_expected", entry_side, entry_fill_mag,
        tcm_fill_mag, "tcm_expected_fill_not_persisted",
        note=("per-structure-contract USD; positive = realized entry fill WORSE "
              "than the persisted TCM expected fill (adverse), sign-safe via side"),
    )

    # CLOSE side: reuse the frozen realized-close extractor (sign-correct via
    # broker_fill_to_mark_basis + the close_fill_gap stamp). Executable cross is
    # typed UNAVAILABLE where the stamp is absent — realized fill still surfaces.
    close_oj = row.get("close_order_json") if isinstance(row.get("close_order_json"), Mapping) else None
    close_fill = row.get("close_fill_price")
    has_close = close_fill is not None
    close_delta: CostDelta
    gap_fraction: Optional[float] = None
    if has_close:
        realized_close = extract_realized_close_costs(
            order_json=close_oj, broker_fill=close_fill, quantity=qty,
        )
        gap_fraction = realized_close.gap_fraction
        fill_c = realized_close.breakdown.component("realized_fill_mark")
        cross_c = realized_close.breakdown.component("stage_cross_mark")
        close_delta = _delta(
            "close_realized_fill_vs_executable_cross",
            fill_c, cross_c,
            note=("signed mark basis, per-structure-contract USD (x100); "
                  "executable cross is the stage full-cross estimate; "
                  "positive = realized close fill cost above the executable estimate"),
        )
    else:
        close_delta = CostDelta(
            name="close_realized_fill_vs_executable_cross",
            amount_usd=None, available=False,
            reason="no_close_fill_order", detail={
                "note": "single-fill position (no distinct close order filled)"},
        )

    # Realized commission, typed PER ROUTING — broker-known ($0 today) vs
    # internal-unavailable. NEVER blanket-unavailable when the broker stamped it.
    entry_commission = _realized_commission_component(
        "entry_realized_commission", CostSide.ENTRY,
        row.get("entry_execution_mode"), row.get("entry_has_alpaca_oid"),
        row.get("entry_broker_status"), row.get("entry_fees_usd"),
    )
    close_commission = _realized_commission_component(
        "close_realized_commission", CostSide.EXIT,
        row.get("close_execution_mode"), row.get("close_has_alpaca_oid"),
        row.get("close_broker_status"), row.get("close_fees_usd"),
    )
    # Realized commission vs the persisted TCM commission ESTIMATE (entry
    # one-way, TOTAL USD): available only when the broker stamped a real value
    # AND the tcm estimate is present. Today broker $0 vs a positive estimate →
    # a negative delta (the model over-charges commission for zero-fee options).
    entry_commission_vs_tcm = _delta(
        "entry_realized_commission_vs_tcm_estimate",
        entry_commission, _tcm_commission_component(row.get("entry_tcm")),
        note=("TOTAL USD, entry one-way; a − b = realized commission − TCM "
              "commission estimate; negative = the estimate over-charged"),
    )

    return RowComparison(
        record_id=str(row.get("record_id")),
        cohort=cohort,
        fill_realism=realism,
        symbol=str(row.get("symbol") or "unknown"),
        strategy=str(row.get("strategy") or "unknown"),
        regime=str(row.get("regime") or "unknown"),
        quantity=qty,
        realized_pl=_coerce_float(row.get("realized_pl")),
        closed_at=str(row.get("closed_at") or ""),
        close_reason=row.get("close_reason"),
        entry_side=entry_side,
        close_side=row.get("close_side"),
        has_close=has_close,
        entry_slip_vs_requested=entry_slip_vs_requested,
        entry_slip_vs_tcm=entry_slip_vs_tcm,
        close_realized_vs_executable_cross=close_delta,
        close_gap_fraction=gap_fraction,
        entry_realized_commission=entry_commission,
        close_realized_commission=close_commission,
        entry_commission_vs_tcm=entry_commission_vs_tcm,
        persisted_estimates=_persisted_estimate_context(row),
    )


# --- cohort aggregation ------------------------------------------------------
@dataclass(frozen=True)
class DeltaStat:
    """Aggregate of ONE typed delta across a cohort's rows. Never mixes bases —
    it summarizes a single a-b comparison; abstentions are counted, not scored."""
    name: str
    n_available: int
    n_unavailable: int
    mean_usd: Optional[float]
    median_usd: Optional[float]
    reasons: Mapping[str, int]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "n_available": self.n_available,
            "n_unavailable": self.n_unavailable,
            "mean_usd": self.mean_usd,
            "median_usd": self.median_usd,
            "abstain_reasons": dict(self.reasons),
        }


def _stat(name: str, deltas: List[CostDelta]) -> DeltaStat:
    vals = [d.amount_usd for d in deltas if d.available and d.amount_usd is not None]
    reasons: Dict[str, int] = {}
    for d in deltas:
        if not d.available:
            reasons[d.reason or "unavailable"] = reasons.get(d.reason or "unavailable", 0) + 1
    return DeltaStat(
        name=name,
        n_available=len(vals),
        n_unavailable=len(deltas) - len(vals),
        mean_usd=(statistics.fmean(vals) if vals else None),
        median_usd=(statistics.median(vals) if vals else None),
        reasons=reasons,
    )


@dataclass(frozen=True)
class CohortReport:
    cohort: str
    n_rows: int
    n_broker_fills: int
    n_internal_fills: int
    realized_pl_sum: Optional[float]
    realized_wins: int
    realized_losses: int
    entry_vs_requested: DeltaStat
    entry_vs_tcm: DeltaStat
    close_vs_executable_cross: DeltaStat
    gap_fraction_n: int
    gap_fraction_mean: Optional[float]
    # realized commission, typed per routing (broker-known vs internal-unavailable)
    entry_commission_broker_known: int
    entry_commission_internal_unavailable: int
    close_commission_broker_known: int
    entry_commission_vs_tcm: DeltaStat


@dataclass(frozen=True)
class StudyReport:
    generated_at: str
    source: str
    model_version: str
    total_rows: int
    cohorts: Tuple[CohortReport, ...]
    # TCM v2 realized-accrual (Lane B, observe-only) — built from the same
    # payload; version-segregated. Defaulted so older callers/tests that
    # construct StudyReport positionally still work.
    tcm_v2_accrual: TcmV2AccrualReport = field(
        default_factory=lambda: TcmV2AccrualReport(total_examples=0, buckets=()))


def _build_cohort(cohort: str, rows: List[RowComparison]) -> CohortReport:
    pls = [r.realized_pl for r in rows if r.realized_pl is not None]
    gaps = [r.close_gap_fraction for r in rows if r.close_gap_fraction is not None]
    return CohortReport(
        cohort=cohort,
        n_rows=len(rows),
        n_broker_fills=sum(1 for r in rows if r.fill_realism == "broker"),
        n_internal_fills=sum(1 for r in rows if r.fill_realism == "internal"),
        realized_pl_sum=(round(sum(pls), 2) if pls else None),
        realized_wins=sum(1 for p in pls if p > 0),
        realized_losses=sum(1 for p in pls if p <= 0),
        entry_vs_requested=_stat(
            "entry_realized_fill_vs_requested_limit",
            [r.entry_slip_vs_requested for r in rows]),
        entry_vs_tcm=_stat(
            "entry_realized_fill_vs_tcm_expected",
            [r.entry_slip_vs_tcm for r in rows]),
        close_vs_executable_cross=_stat(
            "close_realized_fill_vs_executable_cross",
            [r.close_realized_vs_executable_cross for r in rows]),
        gap_fraction_n=len(gaps),
        gap_fraction_mean=(statistics.fmean(gaps) if gaps else None),
        entry_commission_broker_known=sum(
            1 for r in rows if r.entry_realized_commission.available),
        entry_commission_internal_unavailable=sum(
            1 for r in rows if not r.entry_realized_commission.available),
        close_commission_broker_known=sum(
            1 for r in rows if r.close_realized_commission.available),
        entry_commission_vs_tcm=_stat(
            "entry_realized_commission_vs_tcm_estimate",
            [r.entry_commission_vs_tcm for r in rows]),
    )


# Deterministic cohort order in the report.
_COHORT_ORDER = ("live", "shadow", "unattributed")


def build_study(payload: Mapping[str, Any]) -> StudyReport:
    rows = [build_row(r) for r in (payload.get("rows") or [])]
    by_cohort: Dict[str, List[RowComparison]] = {c: [] for c in _COHORT_ORDER}
    for r in rows:
        by_cohort.setdefault(r.cohort, []).append(r)
    cohorts = tuple(
        _build_cohort(c, by_cohort[c])
        for c in _COHORT_ORDER if by_cohort.get(c)
    )
    return StudyReport(
        generated_at=str(payload.get("generated_at", "")),
        source=str(payload.get("source", "")),
        model_version=str(payload.get("model_version", MODEL_VERSION)),
        total_rows=len(rows),
        cohorts=cohorts,
        tcm_v2_accrual=build_tcm_v2_accrual(payload),
    )


# ═══════════════════════════════════════════════════════════════════════════
# TCM v2 REALIZED-ACCRUAL (Lane B, observe-only) — consumer of the #1278
# stage-stamped ``tcm.tcm_v2_proposal``.
#
# WHAT THIS ACCRUES: for every eligible entry AND close side of a closed
# round-trip, one typed COMMISSION example — the ONLY component TCM v2 changes
# (#1273 evidence pin; slippage/spread are carried UNCHANGED and surfaced as
# realized context, never differenced). Each example carries the three
# commission bases side by side:
#   * current_model_cost — the FROZEN TCM commission (paper_orders.tcm.fees_usd).
#   * tcm_v2_cost        — the PROPOSED routing-aware commission, read from the
#                          stamped ``tcm.tcm_v2_proposal`` (post-#1278 rows ONLY;
#                          absent → typed UNAVAILABLE, NEVER a fabricated zero).
#   * realized_commission — the broker-true commission PER ROUTING (#1273): a
#                          real Alpaca fill's ``fees_usd`` ($0 options today) is
#                          KNOWN; an internal/shadow fill is typed UNAVAILABLE.
# and the two typed deltas the owner's promotion packet needs:
#   * current_minus_realized = current model commission − realized commission.
#   * v2_minus_realized      = proposed v2 commission     − realized commission.
# On a broker fill these read (frozen 0.65×qty − 0)=+ and (0 − 0)=0 — the
# accrued evidence that v2 tracks realized where the frozen model over-charges.
#
# IDENTITY / IDEMPOTENCE: entry↔close are two sides of ONE round-trip, joined
# ONLY on the durable spine identity (``paper_positions.id`` = record_id, plus
# suggestion_id) the STUDY_SQL already enforces (open = earliest fill, close =
# latest fill joined only when strictly later). The report is a PURE function of
# the DB payload: a re-run yields byte-identical output, and "accrual over time"
# is the CLI's dated snapshots (``--accrual-json`` / the dated markdown), NOT a
# new table. Examples are deduped by ``{record_id}:{side}`` so a duplicated
# payload row can never double-count.
#
# VERSION SEGREGATION: buckets are keyed on (cohort, v2 model_version). A v2
# version bump changes ``tcm_v2_proposal.model_version``, so post-bump examples
# land in a DIFFERENT bucket and never pool with pre-bump ones.
# ═══════════════════════════════════════════════════════════════════════════

TCM_V2_STAMP_KEY = "tcm_v2_proposal"
_V2_VERSION_UNAVAILABLE = "unavailable_no_v2_stamp"

_CURRENT_MODEL_COMMISSION_PROV = Provenance(
    model_version="paper_orders.tcm.fees_usd@frozen",
    source_detail="frozen TransactionCostModel commission (one-way, leg-blind, qty×0.65)",
)


def _side_enum(side: str) -> CostSide:
    return CostSide.ENTRY if side == "entry" else CostSide.EXIT


def _v2_stamp(tcm: Any) -> Optional[Mapping[str, Any]]:
    """The stamped ``tcm_v2_proposal`` dict, or None (pre-#1278 rows / no tcm)."""
    if isinstance(tcm, Mapping):
        stamp = tcm.get(TCM_V2_STAMP_KEY)
        if isinstance(stamp, Mapping):
            return stamp
    return None


def _current_model_commission_component(tcm: Any, side: str) -> CostComponent:
    """The FROZEN TCM commission (``tcm.fees_usd``) as a typed component
    (TOTAL USD). Typed UNAVAILABLE when tcm carries no fees_usd — never zero."""
    fee = _tcm_fees_usd(tcm)
    cost_side = _side_enum(side)
    if fee is None:
        return CostComponent.make_unavailable(
            "current_model_cost", CostSource.TCM, cost_side,
            CostBasisKind.ESTIMATED, CostUnit.TOTAL,
            "tcm_fees_not_persisted",
            provenance=_CURRENT_MODEL_COMMISSION_PROV,
        )
    return CostComponent(
        name="current_model_cost", source=CostSource.TCM, side=cost_side,
        basis=CostBasisKind.ESTIMATED, unit=CostUnit.TOTAL,
        amount_usd=abs(fee), provenance=_CURRENT_MODEL_COMMISSION_PROV,
    )


def _v2_proposed_commission_component(
    stamp: Optional[Mapping[str, Any]], side: str
) -> CostComponent:
    """The PROPOSED v2 routing-aware commission, read from the stamped
    ``tcm_v2_proposal.proposed_model.commission_usd`` (TOTAL USD). Post-#1278
    rows ONLY — an absent stamp types UNAVAILABLE (``no_v2_stamp_pre_1278``),
    never a fabricated zero. Broker-routed proposes $0 (available, amount 0.0);
    internal/shadow proposes the labeled synthetic estimate. The stamp's OWN
    ``model_version`` rides provenance so version drift is auditable per row."""
    cost_side = _side_enum(side)
    if stamp is None:
        return CostComponent.make_unavailable(
            "tcm_v2_cost", CostSource.TCM, cost_side,
            CostBasisKind.ESTIMATED, CostUnit.TOTAL,
            "no_v2_stamp_pre_1278",
            provenance=Provenance(model_version=_V2_VERSION_UNAVAILABLE),
        )
    prov = Provenance(
        model_version=str(stamp.get("model_version") or "tcm_v2_proposal/unknown"),
        source_detail=str(stamp.get("source") or "unknown_source"),
    )
    pm = stamp.get("proposed_model")
    comm = pm.get("commission_usd") if isinstance(pm, Mapping) else None
    if not isinstance(comm, Mapping) or not comm.get("available"):
        reason = (
            (comm.get("reason") if isinstance(comm, Mapping) else None)
            or "v2_commission_unavailable"
        )
        return CostComponent.make_unavailable(
            "tcm_v2_cost", CostSource.TCM, cost_side,
            CostBasisKind.ESTIMATED, CostUnit.TOTAL, str(reason),
            provenance=prov,
        )
    usd = _coerce_float(comm.get("usd"))
    if usd is None:
        return CostComponent.make_unavailable(
            "tcm_v2_cost", CostSource.TCM, cost_side,
            CostBasisKind.ESTIMATED, CostUnit.TOTAL,
            "v2_commission_usd_missing", provenance=prov,
        )
    return CostComponent(
        name="tcm_v2_cost", source=CostSource.TCM, side=cost_side,
        basis=CostBasisKind.ESTIMATED, unit=CostUnit.TOTAL,
        amount_usd=abs(usd), provenance=prov,
    )


def _v2_model_version(stamp: Optional[Mapping[str, Any]]) -> str:
    """The stamp's own ``model_version`` (the version-segregation key), or the
    sentinel when no stamp is present (pre-#1278)."""
    if stamp is None:
        return _V2_VERSION_UNAVAILABLE
    return str(stamp.get("model_version") or "tcm_v2_proposal/unknown")


def _accrual_routing(
    stamp: Optional[Mapping[str, Any]], broker_routed: bool, cohort: str
) -> Tuple[str, str]:
    """(routing_label, routing_source). Prefer the stage-stamped routing (the
    v2 proposal's own stage-time prediction). When no stamp exists, DERIVE a
    coarse routing from the REALIZED venue signals — never fabricate a broker
    route for an unrecognized one."""
    if stamp is not None and stamp.get("routing"):
        return str(stamp["routing"]), "stage_stamp"
    if broker_routed:
        return "broker_alpaca_options", "derived_from_realized"
    if cohort == "shadow":
        return "shadow", "derived_from_realized"
    return "internal", "derived_from_realized"


def _realized_fill_gap_component(
    side: str,
    close_order_json: Optional[Mapping[str, Any]],
    close_fill: Any,
    quantity: Optional[float],
) -> Tuple[CostComponent, Optional[float]]:
    """The realized spread/fill-gap carried context (close_fill_gap when
    stamped): the frozen ``extract_realized_close_costs.realized_slippage_vs_mid``
    (TOTAL USD) + gap_fraction. ENTRY side has no close_fill_gap → UNAVAILABLE.
    An unstamped close (no cross/mid) → UNAVAILABLE. Neither model's commission
    is differenced against this — it is the component v2 carries UNCHANGED."""
    if side != "close":
        return (
            CostComponent.make_unavailable(
                "realized_spread_or_fill_gap", CostSource.REALIZED,
                CostSide.ENTRY, CostBasisKind.REALIZED, CostUnit.TOTAL,
                "entry_side_no_close_fill_gap",
            ),
            None,
        )
    if close_fill is None:
        return (
            CostComponent.make_unavailable(
                "realized_spread_or_fill_gap", CostSource.REALIZED,
                CostSide.EXIT, CostBasisKind.REALIZED, CostUnit.TOTAL,
                "no_close_fill_order",
            ),
            None,
        )
    realized = extract_realized_close_costs(
        order_json=close_order_json, broker_fill=close_fill, quantity=quantity,
    )
    slip = realized.breakdown.component("realized_slippage_vs_mid")
    if slip is None:  # pragma: no cover - the extractor always includes it
        slip = CostComponent.make_unavailable(
            "realized_spread_or_fill_gap", CostSource.REALIZED, CostSide.EXIT,
            CostBasisKind.REALIZED, CostUnit.TOTAL, "extractor_missing_slip",
        )
    return slip, realized.gap_fraction


# --- one typed accrual example ----------------------------------------------
@dataclass(frozen=True)
class TcmV2AccrualExample:
    """One eligible entry/close side of a closed round-trip, comparing the
    current-model commission and the proposed v2 commission against the
    realized broker commission. Every money field is a typed CostComponent /
    CostDelta — a missing input is UNAVAILABLE and COUNTED, never scored zero."""
    example_id: str            # f"{record_id}:{side}" — the dedup key
    record_id: str             # paper_positions.id — the round-trip spine
    suggestion_id: str         # durable identity (entry↔close share it)
    cohort: str                # live | shadow | unattributed
    fill_realism: str          # broker | internal
    side: str                  # entry | close
    routing: str               # broker_alpaca_options | shadow | internal | ...
    routing_source: str        # stage_stamp | derived_from_realized
    strategy: str
    leg_count: Optional[int]
    quantity: Optional[float]
    model_version: str         # the v2 stamp version (segregation key) or sentinel
    v2_stamp_present: bool
    known_at: str              # closed_at (round-trip realization time)
    source: str                # tcm_v2_proposal@stage | no_v2_stamp
    current_model_cost: CostComponent          # frozen TCM commission (TOTAL USD)
    tcm_v2_cost: CostComponent                 # proposed v2 commission (TOTAL USD)
    realized_commission: CostComponent         # broker-true, per routing (TOTAL USD)
    realized_spread_or_fill_gap: CostComponent  # carried context (close side)
    close_gap_fraction: Optional[float]
    current_minus_realized: CostDelta          # current − realized commission
    v2_minus_realized: CostDelta               # proposed v2 − realized commission

    def as_dict(self) -> Dict[str, Any]:
        return {
            "example_id": self.example_id,
            "record_id": self.record_id,
            "suggestion_id": self.suggestion_id,
            "cohort": self.cohort,
            "fill_realism": self.fill_realism,
            "side": self.side,
            "routing": self.routing,
            "routing_source": self.routing_source,
            "strategy": self.strategy,
            "leg_count": self.leg_count,
            "quantity": self.quantity,
            "model_version": self.model_version,
            "v2_stamp_present": self.v2_stamp_present,
            "known_at": self.known_at,
            "source": self.source,
            "current_model_cost": self.current_model_cost.as_dict(),
            "tcm_v2_cost": self.tcm_v2_cost.as_dict(),
            "realized_commission": self.realized_commission.as_dict(),
            "realized_spread_or_fill_gap": self.realized_spread_or_fill_gap.as_dict(),
            "close_gap_fraction": self.close_gap_fraction,
            "current_minus_realized": self.current_minus_realized.as_dict(),
            "v2_minus_realized": self.v2_minus_realized.as_dict(),
        }


def _accrual_example_for_side(
    row: Mapping[str, Any], *, side: str, cohort: str, realism: str,
    qty: Optional[float], tcm: Any, exec_mode: Any, has_oid: Any,
    broker_status: Any, fees_usd: Any,
    close_order_json: Optional[Mapping[str, Any]] = None,
    close_fill: Any = None,
) -> TcmV2AccrualExample:
    stamp = _v2_stamp(tcm)
    broker_routed = _broker_routed(exec_mode, has_oid, broker_status)
    routing, routing_source = _accrual_routing(stamp, broker_routed, cohort)

    current_cost = _current_model_commission_component(tcm, side)
    v2_cost = _v2_proposed_commission_component(stamp, side)
    realized_commission = _realized_commission_component(
        "realized_commission", _side_enum(side), exec_mode, has_oid,
        broker_status, fees_usd,
    )
    spread_gap, gap_fraction = _realized_fill_gap_component(
        side, close_order_json, close_fill, qty,
    )

    current_minus_realized = _delta(
        "current_minus_realized", current_cost, realized_commission,
        note=("TOTAL USD commission; current frozen TCM − realized broker "
              "commission; positive = the frozen model over-charges vs realized"),
    )
    v2_minus_realized = _delta(
        "v2_minus_realized", v2_cost, realized_commission,
        note=("TOTAL USD commission; proposed v2 − realized broker commission; "
              "0 on a broker fill = the proposal tracks realized ($0 options)"),
    )

    # leg_count: prefer the stamp's own count, else the ranker estimate.
    leg_count: Optional[int] = None
    if stamp is not None and stamp.get("leg_count") is not None:
        try:
            leg_count = int(stamp["leg_count"])
        except (TypeError, ValueError):
            leg_count = None
    if leg_count is None:
        rc = row.get("ranking_costs")
        if isinstance(rc, Mapping) and rc.get("leg_count") is not None:
            try:
                leg_count = int(rc["leg_count"])
            except (TypeError, ValueError):
                leg_count = None

    record_id = str(row.get("record_id"))
    return TcmV2AccrualExample(
        example_id=f"{record_id}:{side}",
        record_id=record_id,
        suggestion_id=str(row.get("suggestion_id") or ""),
        cohort=cohort,
        fill_realism=realism,
        side=side,
        routing=routing,
        routing_source=routing_source,
        strategy=str(row.get("strategy") or "unknown"),
        leg_count=leg_count,
        quantity=qty,
        model_version=_v2_model_version(stamp),
        v2_stamp_present=stamp is not None,
        known_at=str(row.get("closed_at") or ""),
        source=("tcm_v2_proposal@stage" if stamp is not None else "no_v2_stamp"),
        current_model_cost=current_cost,
        tcm_v2_cost=v2_cost,
        realized_commission=realized_commission,
        realized_spread_or_fill_gap=spread_gap,
        close_gap_fraction=gap_fraction,
        current_minus_realized=current_minus_realized,
        v2_minus_realized=v2_minus_realized,
    )


def build_accrual_examples(row: Mapping[str, Any]) -> List[TcmV2AccrualExample]:
    """Map ONE db row to its entry + close TCM v2 accrual examples. The close
    example exists ONLY when a distinct close order filled (single-fill
    positions yield an entry example only). Pure; never raises on a partial
    row (missing pieces type UNAVAILABLE)."""
    cohort = classify_cohort(row.get("cohort_name"))
    realism = fill_realism(row.get("fill_source"))
    qty = _coerce_float(row.get("quantity"))

    examples: List[TcmV2AccrualExample] = [
        _accrual_example_for_side(
            row, side="entry", cohort=cohort, realism=realism, qty=qty,
            tcm=row.get("entry_tcm"),
            exec_mode=row.get("entry_execution_mode"),
            has_oid=row.get("entry_has_alpaca_oid"),
            broker_status=row.get("entry_broker_status"),
            fees_usd=row.get("entry_fees_usd"),
        )
    ]
    if row.get("close_fill_price") is not None:
        close_oj = (
            row.get("close_order_json")
            if isinstance(row.get("close_order_json"), Mapping) else None
        )
        examples.append(_accrual_example_for_side(
            row, side="close", cohort=cohort, realism=realism, qty=qty,
            tcm=row.get("close_tcm"),
            exec_mode=row.get("close_execution_mode"),
            has_oid=row.get("close_has_alpaca_oid"),
            broker_status=row.get("close_broker_status"),
            fees_usd=row.get("close_fees_usd"),
            close_order_json=close_oj,
            close_fill=row.get("close_fill_price"),
        ))
    return examples


def _dedup_examples(
    examples: List[TcmV2AccrualExample],
) -> List[TcmV2AccrualExample]:
    """Idempotence guard: one example per (record_id, side). A duplicated
    payload row (same position seen twice) can never double-count; first
    occurrence wins (the payload is deterministically ordered upstream)."""
    seen: Dict[str, TcmV2AccrualExample] = {}
    for ex in examples:
        if ex.example_id not in seen:
            seen[ex.example_id] = ex
    return list(seen.values())


# --- version-segregated aggregation -----------------------------------------
@dataclass(frozen=True)
class TcmV2VersionBucket:
    """Accrual tally for ONE (cohort, v2 model_version). A version bump lands
    post-bump examples in a NEW bucket — versions never pool."""
    cohort: str
    model_version: str
    n_examples: int
    n_entry: int
    n_close: int
    v2_stamp_present: int
    v2_stamp_absent: int
    realized_commission_known: int
    realized_commission_unavailable: int
    current_minus_realized: DeltaStat
    v2_minus_realized: DeltaStat

    def as_dict(self) -> Dict[str, Any]:
        return {
            "cohort": self.cohort,
            "model_version": self.model_version,
            "n_examples": self.n_examples,
            "n_entry": self.n_entry,
            "n_close": self.n_close,
            "v2_stamp_present": self.v2_stamp_present,
            "v2_stamp_absent": self.v2_stamp_absent,
            "realized_commission_known": self.realized_commission_known,
            "realized_commission_unavailable": self.realized_commission_unavailable,
            "current_minus_realized": self.current_minus_realized.as_dict(),
            "v2_minus_realized": self.v2_minus_realized.as_dict(),
        }


@dataclass(frozen=True)
class TcmV2AccrualReport:
    total_examples: int
    buckets: Tuple[TcmV2VersionBucket, ...]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "total_examples": self.total_examples,
            "buckets": [b.as_dict() for b in self.buckets],
        }


def _build_v2_bucket(
    cohort: str, model_version: str, examples: List[TcmV2AccrualExample]
) -> TcmV2VersionBucket:
    return TcmV2VersionBucket(
        cohort=cohort,
        model_version=model_version,
        n_examples=len(examples),
        n_entry=sum(1 for e in examples if e.side == "entry"),
        n_close=sum(1 for e in examples if e.side == "close"),
        v2_stamp_present=sum(1 for e in examples if e.v2_stamp_present),
        v2_stamp_absent=sum(1 for e in examples if not e.v2_stamp_present),
        realized_commission_known=sum(
            1 for e in examples if e.realized_commission.available),
        realized_commission_unavailable=sum(
            1 for e in examples if not e.realized_commission.available),
        current_minus_realized=_stat(
            "current_minus_realized",
            [e.current_minus_realized for e in examples]),
        v2_minus_realized=_stat(
            "v2_minus_realized", [e.v2_minus_realized for e in examples]),
    )


def build_tcm_v2_accrual(payload: Mapping[str, Any]) -> TcmV2AccrualReport:
    """Pure function of the DB payload → the version-segregated TCM v2
    realized-accrual report. Deduped by (record_id, side); buckets keyed on
    (cohort, v2 model_version) in deterministic order."""
    examples: List[TcmV2AccrualExample] = []
    for r in (payload.get("rows") or []):
        examples.extend(build_accrual_examples(r))
    examples = _dedup_examples(examples)

    by_key: Dict[Tuple[str, str], List[TcmV2AccrualExample]] = {}
    for ex in examples:
        by_key.setdefault((ex.cohort, ex.model_version), []).append(ex)

    # Deterministic order: cohort precedence, then model_version ascending.
    cohort_rank = {c: i for i, c in enumerate(_COHORT_ORDER)}
    ordered_keys = sorted(
        by_key.keys(),
        key=lambda k: (cohort_rank.get(k[0], len(_COHORT_ORDER)), k[0], k[1]),
    )
    buckets = tuple(
        _build_v2_bucket(cohort, mv, by_key[(cohort, mv)])
        for (cohort, mv) in ordered_keys
    )
    return TcmV2AccrualReport(total_examples=len(examples), buckets=buckets)


# --- rendering ---------------------------------------------------------------
def _fmt(x: Optional[float], nd: int = 2) -> str:
    return "—" if x is None else f"{x:.{nd}f}"


def _delta_row(label: str, s: DeltaStat) -> str:
    return (
        f"| {label} | {s.n_available} | {s.n_unavailable} | "
        f"{_fmt(s.mean_usd)} | {_fmt(s.median_usd)} | "
        f"`{dict(s.reasons) or '{}'}` |"
    )


def render_markdown(study: StudyReport) -> str:
    L: List[str] = []
    L.append(f"# Realized Cost Comparison — Consumer #3 — {study.generated_at}")
    L.append("")
    L.append(f"- Source: {study.source}")
    L.append(f"- Model: `{study.model_version}`")
    L.append(f"- Total closed round-trips: **{study.total_rows}**")
    L.append("- OBSERVE-ONLY. Compares PERSISTED estimated/executable bases "
             "against REALIZED fills; **COMPARE, never SUM** — every number is a "
             "typed pairwise delta or a passthrough.")
    L.append("")
    L.append("### Units & sign legend")
    L.append("- PRICE fields are per-structure-contract dollars-per-contract; "
             "USD deltas are **PER_STRUCTURE_CONTRACT** (× multiplier "
             f"{int(OPTION_MULTIPLIER)}); TOTAL would be × qty on top (never mixed).")
    L.append("- ENTRY deltas are sign-SAFE: adverse/favorable direction comes "
             "from the reliable order `side` + fill MAGNITUDE, never the broker "
             "fill sign (the 2026-07-08 sign-corruption class). Positive = "
             "realized fill WORSE than the estimate (adverse).")
    L.append("- CLOSE delta reuses the frozen `close_fill_gap` sign-correct path "
             "(`cost_basis.extract_realized_close_costs`); executable cross is "
             "typed UNAVAILABLE where the stage stamp is absent.")
    L.append("- `realized_pl` is the authoritative DB round-trip P&L "
             "(context, never a cost basis).")
    L.append("- Realized COMMISSION is typed PER ROUTING (not blanket): on "
             "BROKER-routed fills `paper_orders.fees_usd` is the REAL Alpaca "
             "commission (KNOWN, $0 for options today); on INTERNAL fills it is "
             "estimate-or-ambiguous → typed UNAVAILABLE. The commission delta "
             "compares the KNOWN broker value against the persisted TCM estimate "
             "(TOTAL USD, entry one-way).")
    L.append("")
    for c in study.cohorts:
        L.append(f"## Cohort: {c.cohort.upper()}")
        L.append("")
        descriptor = (
            "live champion cohort (real capital)" if c.cohort == "live"
            else "shadow cohort (no real capital; internal synthetic fills are "
                 "partly fiction — docs/specs/shadow_fill_realism.md)"
            if c.cohort == "shadow"
            else "no cohort attribution")
        L.append(f"- {descriptor}")
        L.append(f"- Rows: **{c.n_rows}** · fill provenance: "
                 f"{c.n_broker_fills} broker / {c.n_internal_fills} internal "
                 "(orthogonal to cohort — the actual fill source per row)")
        L.append(f"- Realized P&L (authoritative): sum **{_fmt(c.realized_pl_sum)}** "
                 f"· wins {c.realized_wins} / losses {c.realized_losses}")
        L.append(f"- Close-fill-gap (fill between executable cross=0 and mid=1): "
                 f"n={c.gap_fraction_n}, mean={_fmt(c.gap_fraction_mean, 4)}")
        L.append(f"- Realized commission routing: entry "
                 f"{c.entry_commission_broker_known} broker-KNOWN / "
                 f"{c.entry_commission_internal_unavailable} internal-UNAVAILABLE "
                 f"· close {c.close_commission_broker_known} broker-KNOWN")
        L.append("")
        L.append("| typed delta (a − b) | n avail | n unavail | mean USD | "
                 "median USD | abstain reasons |")
        L.append("|---|---|---|---|---|---|")
        L.append(_delta_row("ENTRY realized fill vs requested limit", c.entry_vs_requested))
        L.append(_delta_row("ENTRY realized fill vs TCM expected fill", c.entry_vs_tcm))
        L.append(_delta_row("ENTRY realized commission vs TCM estimate", c.entry_commission_vs_tcm))
        L.append(_delta_row("CLOSE realized fill vs executable cross", c.close_vs_executable_cross))
        L.append("")
    if not study.cohorts:
        L.append("_No closed round-trips in the payload._")
        L.append("")
    L.extend(_render_tcm_v2_accrual(study.tcm_v2_accrual))
    return "\n".join(L) + "\n"


def _render_tcm_v2_accrual(report: TcmV2AccrualReport) -> List[str]:
    """The TCM v2 realized-accrual section (Lane B, observe-only). One block
    per (cohort, v2 model_version) so versions never pool."""
    L: List[str] = []
    L.append("## TCM v2 Realized-Accrual (observe-only, Lane B)")
    L.append("")
    L.append(f"- Total eligible entry/close examples: **{report.total_examples}**")
    L.append("- Accrues the ONLY component TCM v2 changes — **commission** "
             "(#1273 evidence). `current_model_cost` = the frozen TCM commission; "
             "`tcm_v2_cost` = the stamped `tcm.tcm_v2_proposal` commission "
             "(post-#1278 rows ONLY; absent → typed UNAVAILABLE, never zero); "
             "`realized_commission` = the broker-true `fees_usd` PER ROUTING "
             "($0 options today on a real fill; internal fills UNAVAILABLE).")
    L.append("- `current_minus_realized` / `v2_minus_realized` are TOTAL-USD "
             "commission deltas vs the SAME realized value; on a broker fill "
             "they read (frozen 0.65×qty − 0)=+ and (0 − 0)=0 — the accrued "
             "evidence that v2 tracks realized. Slippage/spread are carried "
             "UNCHANGED (surfaced as realized context), never differenced here.")
    L.append("- Buckets are keyed on (cohort, v2 `model_version`): a version "
             "bump lands post-bump examples in a NEW bucket — versions never "
             "pool. IDEMPOTENT: pure function of the DB; re-run = same output.")
    L.append("")
    if not report.buckets:
        L.append("_No eligible TCM v2 accrual examples in the payload._")
        L.append("")
        return L
    for b in report.buckets:
        L.append(f"### {b.cohort.upper()} · v2 `{b.model_version}`")
        L.append("")
        L.append(f"- Examples: **{b.n_examples}** "
                 f"(entry {b.n_entry} / close {b.n_close}) · "
                 f"v2 stamp present {b.v2_stamp_present} / "
                 f"absent {b.v2_stamp_absent}")
        L.append(f"- Realized commission: {b.realized_commission_known} KNOWN "
                 f"(broker) / {b.realized_commission_unavailable} UNAVAILABLE "
                 "(internal)")
        L.append("")
        L.append("| typed delta (a − b) | n avail | n unavail | mean USD | "
                 "median USD | abstain reasons |")
        L.append("|---|---|---|---|---|---|")
        L.append(_delta_row("current − realized commission", b.current_minus_realized))
        L.append(_delta_row("v2 − realized commission", b.v2_minus_realized))
        L.append("")
    return L


# --- CLI --------------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Consumer #3 realized entry/close cost comparison "
                    "(observe-only, read-only)")
    ap.add_argument("--rows-json", help="path to the JSON payload emitted by --emit-sql")
    ap.add_argument("--emit-sql", action="store_true",
                    help="print the read-only SQL to regenerate the payload, then exit")
    ap.add_argument("--out", help="write the markdown report to this path (default: stdout)")
    ap.add_argument("--accrual-json",
                    help="also write the per-example TCM v2 realized-accrual "
                         "examples (the machine-diffable dated snapshot) to this "
                         "path; deterministic, one object per eligible entry/close")
    args = ap.parse_args(argv)

    if args.emit_sql:
        print(STUDY_SQL)
        return 0
    if not args.rows_json:
        ap.error("--rows-json is required (or use --emit-sql)")

    with open(args.rows_json, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    study = build_study(payload)
    md = render_markdown(study)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(md)
        print(f"wrote {args.out}")
    else:
        print(md)
    if args.accrual_json:
        # Per-example dated snapshot: a PURE re-derivation of the DB payload
        # (deterministic order), so diffing two dated files IS the accrual.
        examples = _dedup_examples([
            ex for r in (payload.get("rows") or [])
            for ex in build_accrual_examples(r)
        ])
        examples.sort(key=lambda e: (e.cohort, e.model_version, e.record_id, e.side))
        snapshot = {
            "generated_at": str(payload.get("generated_at", "")),
            "source": str(payload.get("source", "")),
            "accrual_summary": study.tcm_v2_accrual.as_dict(),
            "examples": [e.as_dict() for e in examples],
        }
        with open(args.accrual_json, "w", encoding="utf-8") as fh:
            json.dump(snapshot, fh, indent=2, sort_keys=True)
        print(f"wrote {args.accrual_json}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
