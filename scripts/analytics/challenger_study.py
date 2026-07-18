"""⑤ Offline challenger-vs-baseline study runner (OBSERVE-ONLY, operator-invoked).

Reuses the merged terminal-distribution foundation
(``packages.quantum.analytics.terminal_distribution``, PR #1247) VERBATIM:
its ``records_from_rows`` mapper, its ``evaluate_model`` prequential evaluator,
its ``head_to_head`` joint-set comparator, its frozen baseline adapters and the
lognormal challenger. This runner adds ONLY the offline glue the foundation
docstring anticipates ("an operator ... fetches rows read-only ... and maps
them here"): DB-row -> foundation-row transform (OCC-symbol leg parsing, DTE
derivation, cohort split by ``is_paper``, corrected-P&L pass-through) and a
dated markdown report.

OBSERVE-ONLY / NON-INTERFERENCE (charter, docs/backlog.md ⑤):
- This file lives OUTSIDE ``packages/quantum`` so it is invisible to the
  import-lock sweep, and it is imported by NO scanner/ranker/gate/executor/EV
  module. It only READS foundation code; it changes nothing in the live path.
- It opens NO database connection. ``--emit-sql`` prints the exact read-only
  query an operator runs (e.g. via the Supabase MCP); ``--rows-json`` consumes
  the JSON that query returns. There is no live-DB code path to rot.
- H9: a model that cannot honestly price its inputs ABSTAINS (typed
  Unavailable) and is COUNTED, never scored as a coin flip.

DATA CONTRACT (one row per closed historical outcome, deduped by suggestion):
    record_id, is_paper, strategy (DB vocab), regime, known_at (ISO-8601 as-of),
    realized_pnl (CORRECTED live value), pop_pred, ev_pred (stored production
    predictions, may be null), net_premium (>0), contracts,
    legs [{side|action, symbol (OCC), quantity, +optional iv, greeks{delta,…}}],
    corrected (bool), +optional entry_underlying_spot {value, status, …}.

⑤ FUTURE SCORABILITY (stage-seam capture, PRs #1259 + entry-spot/IV): a row
whose trade was staged AFTER the capture landed carries per-leg ``iv`` +
``greeks.delta`` on its legs and a stage-level ``entry_underlying_spot`` marker
(SQL sources these from the stage-populated ``paper_orders.order_json``). The
mapper below consumes them NATURALLY: the frozen adapter scores once per-leg
delta is present; the lognormal challenger scores once spot AND per-leg IV are
BOTH present. HISTORICAL rows captured none of these → the fields are absent →
the models abstain (missing_delta / missing_spot / missing_iv), COUNTED not
scored. Per H9 nothing is ever backfilled or defaulted: an absent field stays
absent and the model abstains, never a fabricated spot/IV/delta.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from packages.quantum.analytics.terminal_distribution import (
    EvalRecord,
    ModelReport,
    Provenance,
    StrategyEvaluation,
    Unavailable,
    baseline_condor,
    baseline_credit_vertical,
    baseline_debit_vertical,
    challenger_lognormal_evaluate,
    evaluate_model,
    head_to_head,
    params_hash,
    records_from_rows,
)
from packages.quantum.analytics.terminal_distribution.evaluator import HeadToHead

# --- DB strategy vocabulary -> foundation contract strategy -----------------
STRATEGY_MAP: Dict[str, str] = {
    "IRON_CONDOR": "iron_condor",
    "LONG_CALL_DEBIT_SPREAD": "debit_vertical",
    "LONG_PUT_DEBIT_SPREAD": "debit_vertical",
    "CREDIT_CALL_SPREAD": "credit_vertical",
    "CREDIT_PUT_SPREAD": "credit_vertical",
}

# Read-only query an operator runs (Supabase MCP / psql) to regenerate the
# --rows-json payload. Deduped by suggestion (latest close). Emits corrected
# P&L (v3.pnl_realized is already the post-F-CREDIT-SIGN live value).
STUDY_SQL = r"""
WITH ded AS (
  SELECT DISTINCT ON (o.suggestion_id)
    o.suggestion_id, o.is_paper, o.strategy, o.regime,
    o.entry_ts, o.closed_at, o.pnl_realized, o.pop_predicted, o.ev_predicted
  FROM learning_trade_outcomes_v3 o
  WHERE o.suggestion_id IS NOT NULL
  ORDER BY o.suggestion_id, o.closed_at DESC
)
SELECT json_build_object(
  'schema_version', 1,
  'generated_at', to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD'),
  'source', 'learning_trade_outcomes_v3 JOIN trade_suggestions (DISTINCT ON suggestion_id)',
  'win_rule', 'realized_pnl > 0',
  'rows', json_agg(row_to_json(x) ORDER BY x.is_paper, x.strategy, x.known_at, x.record_id)
)
FROM (
  SELECT
    d.suggestion_id::text AS record_id, d.is_paper, d.strategy,
    COALESCE(d.regime,'unknown') AS regime,
    to_char(COALESCE(d.entry_ts, ts.created_at) AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS"Z"') AS known_at,
    round(d.pnl_realized,2)  AS realized_pnl,
    round(d.pop_predicted,6) AS pop_pred,
    round(d.ev_predicted,4)  AS ev_pred,
    round((ts.order_json->>'limit_price')::numeric,4) AS net_premium,
    COALESCE((ts.order_json->>'contracts')::int,1) AS contracts,
    (l.suggestion_id IS NOT NULL) AS corrected,
    -- queue-5: prefer the STAGE-POPULATED legs (per-leg iv + greeks.delta
    -- captured at the stage seam, PRs #1259 + entry-spot/IV); fall back to the
    -- decision-record suggestion legs for any suggestion with no captured order
    -- (older rows -> no iv/delta -> the models abstain, never defaulted). Same
    -- OCC symbols/geometry either way; the mapper reads side|action.
    COALESCE(po.order_json->'legs', ts.order_json->'legs') AS legs,
    -- queue-5: stage-level entry underlying spot (typed marker). NULL for
    -- suggestions staged before the capture; {status:'unavailable_at_stage'}
    -- until an honest same-fetch spot source is wired -- either way the
    -- challenger abstains missing_spot, never on a fabricated value.
    po.order_json->'entry_underlying_spot' AS entry_underlying_spot
  FROM ded d
  JOIN trade_suggestions ts ON ts.id = d.suggestion_id
  LEFT JOIN LATERAL (
    -- latest staged/filled order carrying the stage-populated legs for this
    -- suggestion (observe-only read; DISTINCT-latest is enough for the study).
    SELECT po.order_json
    FROM paper_orders po
    WHERE po.suggestion_id = d.suggestion_id
      AND po.order_json ? 'legs'
    ORDER BY po.staged_at DESC NULLS LAST
    LIMIT 1
  ) po ON true
  LEFT JOIN LATERAL (
    SELECT lfl.suggestion_id FROM learning_feedback_loops lfl
    WHERE lfl.suggestion_id = d.suggestion_id
      AND lfl.details_json ? 'f_credit_sign_correction' LIMIT 1
  ) l ON true
) x;
""".strip()


# --- OCC / geometry helpers -------------------------------------------------
def parse_occ(symbol: str) -> Tuple[str, float, date]:
    """Parse an OCC option symbol (``O:AMD260313P00180000``) into
    (option_type, strike, expiry). Raises ValueError on a malformed symbol —
    the foundation mapper turns that into an explicit skip (never a default)."""
    core = symbol[2:] if symbol.startswith("O:") else symbol
    if len(core) < 15:
        raise ValueError(f"OCC symbol too short: {symbol!r}")
    strike = int(core[-8:]) / 1000.0
    cp = core[-9]
    yymmdd = core[-15:-9]
    if cp not in ("C", "P"):
        raise ValueError(f"OCC option-type not C/P: {symbol!r}")
    option_type = "call" if cp == "C" else "put"
    expiry = datetime.strptime("20" + yymmdd, "%Y%m%d").date()
    return option_type, strike, expiry


def dte_bucket(dte: Optional[float]) -> str:
    if dte is None:
        return "unknown"
    if dte <= 14:
        return "0-14"
    if dte <= 30:
        return "15-30"
    if dte <= 45:
        return "31-45"
    return "46+"


def _geometry_bounds(strategy: str, strikes: List[float], premium: float, contracts: int) -> Tuple[float, float]:
    """Exact defined-risk max_gain / max_loss in per-position dollars. Display
    metadata only (the evaluator scores pop & EV) — computed, never guessed."""
    scale = 100.0 * contracts
    if strategy == "iron_condor":
        s = sorted(strikes)
        min_width = min(s[1] - s[0], s[3] - s[2]) if len(s) == 4 else 0.0
        return premium * scale, max(0.0, (min_width - premium)) * scale
    width = (max(strikes) - min(strikes)) if len(strikes) >= 2 else 0.0
    return max(0.0, (width - premium)) * scale, premium * scale


# --- ⑤ captured stage-seam market inputs (per-leg iv/delta + entry spot) -----
# Consumed NATURALLY when present; absent on historical rows → models abstain.
# H9: never defaulted, never fabricated — an absent/typed-unavailable field maps
# to None and the model abstains, it is never invented.
def _finite(x: Any) -> Optional[float]:
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _leg_iv(leg: Dict[str, Any]) -> Optional[float]:
    """Per-leg captured implied volatility (stage-seam populate). Honoured only
    when the leg's ``iv_status`` is 'populated_at_stage' (or the status key is
    absent, for a plain synthetic/future test shape) AND the value is finite and
    > 0. A typed-unavailable / dark / non-positive IV → None → the challenger
    abstains missing_iv (never a default IV — the dormant ``iv or 0.30``)."""
    if not isinstance(leg, dict):
        return None
    status = leg.get("iv_status")
    if status is not None and status != "populated_at_stage":
        return None
    iv = _finite(leg.get("iv"))
    return iv if (iv is not None and iv > 0) else None


def _leg_delta(leg: Dict[str, Any]) -> Optional[float]:
    """Per-leg captured delta (#1259 greeks populate). RAW per-contract delta as
    the snapshot reported it (call +, put −); the frozen adapter abs()es like
    production. Reads leg['greeks']['delta'] (the populated shape) or a flat
    leg['delta'] (synthetic/future test shape). Dark greeks (greeks=None) → None
    → the frozen adapter abstains missing_delta, never fabricated."""
    if not isinstance(leg, dict):
        return None
    g = leg.get("greeks")
    if isinstance(g, dict) and g.get("delta") is not None:
        return _finite(g.get("delta"))
    if leg.get("delta") is not None:
        return _finite(leg.get("delta"))
    return None


def _entry_spot(raw: Any) -> Optional[float]:
    """Entry underlying spot from the ⑤ stage-level capture. Accepts the typed
    marker {value, status, …} (value honoured ONLY when status is
    'populated_at_stage', or status absent for a plain test shape) or a bare
    number (synthetic/future shape). Typed-unavailable / missing → None → the
    challenger abstains missing_spot, never a fabricated spot (H9)."""
    if raw is None:
        return None
    if isinstance(raw, dict):
        status = raw.get("status")
        if status is not None and status != "populated_at_stage":
            return None
        v = _finite(raw.get("value"))
        return v if (v is not None and v > 0) else None
    v = _finite(raw)
    return v if (v is not None and v > 0) else None


# --- DB row -> foundation row-dict + stored-prediction side map -------------
def to_foundation_row(db_row: Dict[str, Any]) -> Tuple[Dict[str, Any], Tuple[Optional[float], Optional[float], float, float]]:
    """Map ONE db row to the ``records_from_rows`` schema and extract the stored
    production (pop, ev, max_gain, max_loss) for the baseline model. Raises on a
    structurally unmappable row (bad OCC symbol / unknown strategy) so the caller
    can record an explicit skip (H9 — never silently defaulted)."""
    strategy = STRATEGY_MAP.get(db_row["strategy"])
    if strategy is None:
        raise ValueError(f"unmapped strategy {db_row['strategy']!r}")

    legs: List[Dict[str, Any]] = []
    strikes: List[float] = []
    expiries: List[date] = []
    for leg in db_row["legs"]:
        option_type, strike, expiry = parse_occ(leg["symbol"])
        # Suggestion legs use 'side'; stage-populated (paper_orders/positions)
        # legs use 'action' — accept either.
        fleg: Dict[str, Any] = {
            "action": leg.get("side") or leg.get("action"),
            "option_type": option_type,
            "strike": strike,
        }
        # ⑤ captured market inputs flow through ONLY when present (H9): a
        # historical leg omits both and the models abstain, never defaulted.
        iv = _leg_iv(leg)
        if iv is not None:
            fleg["iv"] = iv
        delta = _leg_delta(leg)
        if delta is not None:
            fleg["delta"] = delta
        legs.append(fleg)
        strikes.append(strike)
        expiries.append(expiry)

    known_dt = datetime.strptime(db_row["known_at"][:10], "%Y-%m-%d").date()
    dte_days = float((max(expiries) - known_dt).days) if expiries else None
    contracts = int(db_row.get("contracts") or 1)
    premium = float(db_row["net_premium"])

    foundation_row = {
        "record_id": db_row["record_id"],
        "known_at": db_row["known_at"],
        "strategy": strategy,
        "legs": legs,
        "net_premium": premium,
        "contracts": contracts,
        # ⑤ entry spot from the stage-level capture when present; None on
        # historical rows and on the current typed-unavailable marker (H9) →
        # challenger abstains missing_spot, never a fabricated spot.
        "spot": _entry_spot(db_row.get("entry_underlying_spot")),
        "dte_days": dte_days,
        "risk_free_rate": 0.0,
        "outcome_status": "resolved",
        "realized_win": (float(db_row["realized_pnl"]) > 0.0),
        "realized_pnl": float(db_row["realized_pnl"]),
        "regime": db_row.get("regime") or "unknown",
        "dte_bucket": dte_bucket(dte_days),
    }
    mg, ml = _geometry_bounds(strategy, strikes, premium, contracts)
    pop = db_row.get("pop_pred")
    ev = db_row.get("ev_pred")
    preds = (None if pop is None else float(pop), None if ev is None else float(ev), mg, ml)
    return foundation_row, preds


# --- models (all reuse the foundation) --------------------------------------
def make_production_baseline(pred_map: Dict[str, Tuple[Optional[float], Optional[float], float, float]]):
    """Frozen baseline AS EMITTED: the production pop/ev that
    ``ev_calculator`` actually produced at decision time (stored in
    learning_trade_outcomes_v3). Abstains (H9) when a stored value is missing —
    never invents one."""

    def fn(rec: EvalRecord):
        pop, ev, mg, ml = pred_map.get(rec.record_id, (None, None, 0.0, 0.0))
        if pop is None or ev is None:
            return Unavailable(
                "missing_stored_prediction",
                f"no stored pop/ev for {rec.record_id}",
                "production_baseline_stored",
            )
        return StrategyEvaluation(
            strategy=rec.structure.strategy,
            model="production_baseline_stored",
            pop=pop,
            expected_value=ev,
            basis="raw",
            max_gain=mg,
            max_loss=ml,
            breakevens=(),
            provenance=Provenance(
                source="trade_suggestions",
                version="stored@v3",
                params_hash=params_hash({"record_id": rec.record_id}),
            ),
        )

    return fn


def frozen_adapter_model(rec: EvalRecord):
    """Frozen baseline adapter re-run OFFLINE (production math verbatim). Needs
    per-leg deltas the historical record never stored -> abstains missing_delta."""
    s = rec.structure
    if s.strategy == "iron_condor":
        return baseline_condor(s, rec.dist_inputs, model="strict")
    if s.strategy == "debit_vertical":
        return baseline_debit_vertical(s, rec.dist_inputs)
    if s.strategy == "credit_vertical":
        return baseline_credit_vertical(s, rec.dist_inputs)
    return Unavailable("unsupported_strategy", s.strategy, "frozen_adapter")


def challenger_model(rec: EvalRecord):
    """Lognormal challenger. Needs per-leg IV + entry spot the historical record
    never stored -> abstains (missing_spot first)."""
    return challenger_lognormal_evaluate(rec.structure, rec.dist_inputs)


# --- study assembly ---------------------------------------------------------
@dataclass(frozen=True)
class CohortStudy:
    cohort: str
    is_paper: bool
    n_rows: int
    n_corrected: int
    skipped: Tuple[Tuple[int, str], ...]
    baseline: ModelReport
    adapter: ModelReport
    challenger: ModelReport
    h2h_baseline_challenger: HeadToHead
    h2h_adapter_challenger: HeadToHead


@dataclass(frozen=True)
class StudyReport:
    generated_at: str
    source: str
    census_fingerprint: Optional[str]
    total_rows: int
    cohorts: Tuple[CohortStudy, ...]


def _abstain_hist(report: ModelReport) -> Dict[str, int]:
    return dict(Counter(p.abstain_reason for p in report.predictions if not p.scored and p.abstain_reason))


def build_cohort_study(cohort: str, is_paper: bool, db_rows: List[Dict[str, Any]]) -> CohortStudy:
    foundation_rows: List[Dict[str, Any]] = []
    pred_map: Dict[str, Tuple[Optional[float], Optional[float], float, float]] = {}
    skipped: List[Tuple[int, str]] = []
    n_corrected = 0
    for idx, db_row in enumerate(db_rows):
        if db_row.get("corrected"):
            n_corrected += 1
        try:
            frow, preds = to_foundation_row(db_row)
        except (KeyError, TypeError, ValueError) as exc:
            skipped.append((idx, f"unmappable db row: {exc!r}"))
            continue
        foundation_rows.append(frow)
        pred_map[frow["record_id"]] = preds

    records, map_skips = records_from_rows(foundation_rows)
    skipped.extend(map_skips)

    baseline = evaluate_model(make_production_baseline(pred_map), records, model_label="production_baseline_stored")
    adapter = evaluate_model(frozen_adapter_model, records, model_label="frozen_baseline_adapter")
    challenger = evaluate_model(challenger_model, records, model_label="lognormal_v1_challenger")
    return CohortStudy(
        cohort=cohort,
        is_paper=is_paper,
        n_rows=len(db_rows),
        n_corrected=n_corrected,
        skipped=tuple(skipped),
        baseline=baseline,
        adapter=adapter,
        challenger=challenger,
        h2h_baseline_challenger=head_to_head(baseline, challenger),
        h2h_adapter_challenger=head_to_head(adapter, challenger),
    )


def build_study(payload: Dict[str, Any]) -> StudyReport:
    rows: List[Dict[str, Any]] = payload["rows"]
    live = [r for r in rows if not r.get("is_paper")]
    shadow = [r for r in rows if r.get("is_paper")]
    cohorts = (
        build_cohort_study("live", False, live),
        build_cohort_study("shadow", True, shadow),
    )
    return StudyReport(
        generated_at=payload.get("generated_at", ""),
        source=payload.get("source", ""),
        census_fingerprint=payload.get("census_fingerprint"),
        total_rows=len(rows),
        cohorts=cohorts,
    )


# --- rendering --------------------------------------------------------------
def _fmt(x: Optional[float], nd: int = 4) -> str:
    return "—" if x is None else f"{x:.{nd}f}"


def _model_line(label: str, r: ModelReport) -> str:
    cov = "—" if r.coverage is None else f"{r.coverage*100:.0f}%"
    return (
        f"| {label} | {r.scored}/{r.eligible} ({cov}) | {r.abstained} | "
        f"{_fmt(r.brier)} | {_fmt(r.ev_rmse, 2)} | {_fmt(r.realized_net, 2)} |"
    )


def render_markdown(study: StudyReport) -> str:
    L: List[str] = []
    L.append(f"# ⑤ Offline Challenger-vs-Baseline Study — {study.generated_at}")
    L.append("")
    L.append(f"- Source: {study.source}")
    if study.census_fingerprint:
        L.append(f"- F-CREDIT-SIGN census fingerprint: `{study.census_fingerprint}`")
    L.append(f"- Total closed outcomes studied (deduped by suggestion): **{study.total_rows}**")
    L.append("- Win rule: `realized_pnl > 0`. Metrics on the **both-present** "
             "(stored pop AND ev) scored subset; abstentions counted, never scored 0.5 (H9).")
    L.append("")
    for c in study.cohorts:
        L.append(f"## Cohort: {c.cohort.upper()} (is_paper={str(c.is_paper).lower()})")
        L.append("")
        L.append(f"- Rows: **{c.n_rows}** · F-CREDIT-SIGN-corrected rows in cohort: **{c.n_corrected}** "
                 f"· unmappable skips: {len(c.skipped)}")
        L.append(f"- Censoring: censored(open)={c.baseline.censored} · malformed={c.baseline.malformed} "
                 f"· eligible(resolved+mappable)={c.baseline.eligible}")
        L.append("")
        L.append("| model | scored/eligible (coverage) | abstained | Brier | EV-RMSE ($) | realized net ($) |")
        L.append("|---|---|---|---|---|---|")
        L.append(_model_line("frozen baseline (as-emitted, stored production pop/ev)", c.baseline))
        L.append(_model_line("frozen baseline adapter (offline re-run)", c.adapter))
        L.append(_model_line("lognormal_v1 challenger (offline)", c.challenger))
        L.append("")
        L.append(f"- Adapter abstention reasons: `{_abstain_hist(c.adapter) or '{}'}`")
        L.append(f"- Challenger abstention reasons: `{_abstain_hist(c.challenger) or '{}'}`")
        bl_ab = _abstain_hist(c.baseline)
        if bl_ab:
            L.append(f"- Baseline abstention reasons: `{bl_ab}`")
        h = c.h2h_baseline_challenger
        L.append(f"- Head-to-head (baseline vs challenger) joint scored set: **n_joint={h.n_joint}** "
                 + ("→ charter falsifier UNADJUDICABLE (challenger produced no scored prediction)."
                    if h.n_joint == 0 else
                    f"Brier {_fmt(h.brier_a)} vs {_fmt(h.brier_b)}; EV-RMSE {_fmt(h.ev_rmse_a,2)} vs {_fmt(h.ev_rmse_b,2)}."))
        L.append("")
        # per-segment (baseline scored set only)
        if c.baseline.segments:
            L.append("### Baseline per-segment (strategy · regime · DTE bucket)")
            L.append("")
            L.append("| strategy | regime | DTE | n | Brier | EV-RMSE ($) | realized net ($) |")
            L.append("|---|---|---|---|---|---|---|")
            for key, m in c.baseline.segments:
                L.append(f"| {key.strategy} | {key.regime} | {key.dte_bucket} | {m.n_scored} | "
                         f"{_fmt(m.brier)} | {_fmt(m.ev_rmse,2)} | {_fmt(m.realized_net,2)} |")
            L.append("")
    return "\n".join(L) + "\n"


# --- CLI --------------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="⑤ offline challenger-vs-baseline study (observe-only, read-only)")
    ap.add_argument("--rows-json", help="path to the JSON payload emitted by --emit-sql")
    ap.add_argument("--emit-sql", action="store_true", help="print the read-only SQL to regenerate the payload, then exit")
    ap.add_argument("--out", help="write the markdown report to this path (default: stdout)")
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
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
