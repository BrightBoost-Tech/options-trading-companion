"""Prequential (predictive-sequential) validator for calibration — the FALSIFIER.

Question this answers: does the calibration layer actually IMPROVE out-of-sample
EV/PoP prediction on LIVE closes, or is it noise (or worse)? A backward-looking
"calibration error" computed on the same rows the multipliers were fit on is
circular and always flatters calibration. This runs the honest test instead:

    for each live close k (in closed_at order, k >= warmup):
        fit calibration on the PREFIX closes [0 .. k-1]     (no look-ahead)
        apply that fit to close k's RAW ev_predicted / pop_predicted
        score calibrated-vs-raw error against the realized pnl of close k

Aggregated over all k this yields raw-vs-calibrated EV-RMSE and Brier. THE
FALSIFIER is the headline: `ev_rmse_improvement = raw_rmse - calibrated_rmse`.
If it is <= 0, calibration did NOT reduce out-of-sample EV error → the
"calibration helps" hypothesis is falsified on this sample. Positive = helps.

Non-circularity (as of #1167, 2026-07-11): `ev_predicted` in
learning_trade_outcomes_v3 is `COALESCE(ts.ev_raw, ts.ev)` — the RAW
pre-calibration prediction. So we fit on raw predictions and score calibration's
effect on raw predictions; we never train on calibration's own output. A
pre-#1167 view (ev_predicted = calibrated) would make this circular — the fetch
guards the column defensively but the guarantee lives in the view.

The fit reuses the PRODUCTION math exactly: CalibrationService
.build_adjustments_from_outcomes + apply_calibration (the same functions
suggestions_open calls). `min_trades` is lowered from the production 8 to a
study warm-up so calibration actually fires on the small live sample; this is a
STUDY tool, not a production path — it schedules nothing and changes no live
behavior.
"""
import logging
import math
from typing import Any, Dict, List, Optional

from packages.quantum.analytics.calibration_service import (
    CalibrationService,
    apply_calibration,
)

logger = logging.getLogger(__name__)

DEFAULT_WARMUP = 4  # min prefix closes before scoring begins


def _num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _adjustments_of(fit: Dict[str, Any]) -> Dict[str, Any]:
    """The adjustments blob when the fit converged, else {} (→ raw passthrough)."""
    if fit.get("status") == "ok":
        return fit.get("adjustments") or {}
    return {}


def _fit_is_order_invariant(prefix, service, min_trades) -> bool:
    """Prefix-invariance: the fit must be a function of the SET of prior closes,
    not their order (any order dependence would be a look-ahead / leakage bug).
    Fit the prefix and its reverse; the blobs must match (multipliers are
    round(.,4), so FP summation-order jitter cannot spuriously fail this)."""
    a = _adjustments_of(service.build_adjustments_from_outcomes(prefix, min_trades=min_trades))
    b = _adjustments_of(service.build_adjustments_from_outcomes(
        list(reversed(prefix)), min_trades=min_trades))
    return a == b


def run_prequential_validation(
    outcomes: List[Dict[str, Any]],
    *,
    warmup: int = DEFAULT_WARMUP,
    min_trades: Optional[int] = None,
    service: Optional[CalibrationService] = None,
) -> Dict[str, Any]:
    """`outcomes`: live closes as dicts, sorted by closed_at ASCENDING (caller
    sorts). Each needs ev_predicted, pop_predicted, pnl_realized, strategy,
    regime. Returns the prequential report (see module docstring). Zero-row and
    too-short samples return status=insufficient_data, never raise."""
    if min_trades is None:
        min_trades = warmup
    svc = service or CalibrationService(None)  # build_* uses no client

    n_total = len(outcomes or [])
    if n_total <= warmup:
        return {
            "status": "insufficient_data",
            "n_outcomes": n_total,
            "warmup": warmup,
            "reason": f"need > {warmup} closes to score any out-of-sample",
        }

    records: List[Dict[str, Any]] = []
    prefix_invariant = True
    first_invariance_violation = None

    for k in range(warmup, n_total):
        prefix = outcomes[:k]
        target = outcomes[k]

        if prefix_invariant and not _fit_is_order_invariant(prefix, svc, min_trades):
            prefix_invariant = False
            first_invariance_violation = k

        fit = svc.build_adjustments_from_outcomes(prefix, min_trades=min_trades)
        adj = _adjustments_of(fit)

        raw_ev = _num(target.get("ev_predicted"))
        raw_pop_v = target.get("pop_predicted")
        raw_pop = _num(raw_pop_v) if raw_pop_v is not None else None
        strat = target.get("strategy") or "unknown"
        reg = target.get("regime") or "unknown"
        dte_bucket = svc._classify_dte(target)

        cal_ev, cal_pop_raw = apply_calibration(
            raw_ev, (raw_pop if raw_pop is not None else 0.0),
            strat, reg, adj, dte_bucket=dte_bucket)
        cal_pop = cal_pop_raw if raw_pop is not None else None

        pnl = _num(target.get("pnl_realized"))
        win = 1.0 if pnl > 0 else 0.0

        records.append({
            "k": k,
            "ticker": target.get("ticker"),
            "strategy": strat, "regime": reg,
            "fit_status": fit.get("status"),
            "fired": abs(cal_ev - raw_ev) > 1e-9,
            "raw_ev": raw_ev, "cal_ev": cal_ev, "pnl_realized": pnl,
            "raw_ev_err": raw_ev - pnl, "cal_ev_err": cal_ev - pnl,
            "raw_pop": raw_pop, "cal_pop": cal_pop, "win": win,
        })

    n = len(records)
    raw_rmse = math.sqrt(sum(r["raw_ev_err"] ** 2 for r in records) / n)
    cal_rmse = math.sqrt(sum(r["cal_ev_err"] ** 2 for r in records) / n)
    raw_mae = sum(abs(r["raw_ev_err"]) for r in records) / n
    cal_mae = sum(abs(r["cal_ev_err"]) for r in records) / n

    pop_rows = [r for r in records if r["raw_pop"] is not None]
    if pop_rows:
        m = len(pop_rows)
        raw_brier = sum((r["raw_pop"] - r["win"]) ** 2 for r in pop_rows) / m
        cal_brier = sum((r["cal_pop"] - r["win"]) ** 2 for r in pop_rows) / m
    else:
        raw_brier = cal_brier = None

    ev_rmse_improvement = raw_rmse - cal_rmse
    n_fired = sum(1 for r in records if r["fired"])

    # THE FALSIFIER — headline. Positive improvement = calibration reduces
    # out-of-sample EV error. <= 0 = it does not → hypothesis falsified. When
    # calibration never fired (n_fired == 0, raw sample too thin), the verdict
    # is INCONCLUSIVE: raw == calibrated by construction, nothing was tested.
    if n_fired == 0:
        verdict = "INCONCLUSIVE_CALIBRATION_NEVER_FIRED"
    elif ev_rmse_improvement > 0:
        verdict = "CALIBRATION_HELPS"
    else:
        verdict = "FALSIFIED_CALIBRATION_DOES_NOT_HELP"

    return {
        "status": "ok",
        "n_outcomes": n_total,
        "n_scored": n,
        "n_calibration_fired": n_fired,
        "warmup": warmup,
        "min_trades": min_trades,
        "prefix_invariant": prefix_invariant,
        "first_invariance_violation_k": first_invariance_violation,
        "ev_rmse": {"raw": round(raw_rmse, 4), "calibrated": round(cal_rmse, 4),
                    "improvement": round(ev_rmse_improvement, 4)},
        "ev_mae": {"raw": round(raw_mae, 4), "calibrated": round(cal_mae, 4),
                   "improvement": round(raw_mae - cal_mae, 4)},
        "brier": ({"raw": round(raw_brier, 4), "calibrated": round(cal_brier, 4),
                   "improvement": round(raw_brier - cal_brier, 4), "n_pop": len(pop_rows)}
                  if raw_brier is not None else {"raw": None, "n_pop": 0}),
        "falsifier": {
            "verdict": verdict,
            "headline_metric": "ev_rmse_improvement",
            "value": round(ev_rmse_improvement, 4),
            "interpretation": "raw_rmse - calibrated_rmse; >0 = calibration helps out-of-sample",
        },
        "records": records,
    }


# ── On-demand fetch + runner (no scheduler wiring — study tool) ──────────────

def fetch_live_outcomes(client, user_id: str, window_days: int = 120) -> List[Dict[str, Any]]:
    """Live (is_paper=false) closes from learning_trade_outcomes_v3, closed_at
    ASC. `ev_predicted` is COALESCE(ev_raw, ev) at the view (#1167) → RAW; the
    validator's non-circularity rests on that. Returns [] on empty/failure."""
    try:
        res = (
            client.table("learning_trade_outcomes_v3")
            .select("ev_predicted, pop_predicted, pnl_realized, strategy, regime, "
                    "window, ticker, closed_at, is_paper")
            .eq("user_id", user_id)
            .eq("is_paper", False)
            .order("closed_at", desc=False)
            .execute()
        )
        return res.data or []
    except Exception as e:  # noqa: BLE001 - study tool, degrade to empty loudly
        logger.error("[PREQUENTIAL] fetch failed: %s", e)
        return []


def main() -> int:
    """On-demand entrypoint. Prints the FALSIFIER verdict first, then metrics."""
    import json
    import os
    from packages.quantum.observability.alerts import _get_admin_supabase  # lazy

    user_id = os.environ.get("PREQUENTIAL_USER_ID") or os.environ.get("DEFAULT_USER_ID")
    warmup = int(os.environ.get("PREQUENTIAL_WARMUP", str(DEFAULT_WARMUP)))
    if not user_id:
        print("ERROR: set PREQUENTIAL_USER_ID (or DEFAULT_USER_ID)")
        return 2

    client = _get_admin_supabase()
    outcomes = fetch_live_outcomes(client, user_id)
    report = run_prequential_validation(outcomes, warmup=warmup)

    fals = report.get("falsifier", {})
    print("=" * 68)
    print(f"  PREQUENTIAL FALSIFIER: {fals.get('verdict', report.get('status'))}")
    if report.get("status") == "ok":
        print(f"  ev_rmse_improvement = {fals.get('value')} "
              f"(raw {report['ev_rmse']['raw']} → cal {report['ev_rmse']['calibrated']})")
        print(f"  scored={report['n_scored']}  fired={report['n_calibration_fired']}  "
              f"prefix_invariant={report['prefix_invariant']}")
    print("=" * 68)
    trimmed = {k: v for k, v in report.items() if k != "records"}
    print(json.dumps(trimmed, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
