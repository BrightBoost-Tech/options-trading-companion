"""
Calibration Service — compares predicted vs realized outcomes.

Reads from the learning_trade_outcomes_v3 view (which joins
learning_feedback_loops → trade_suggestions) and computes
calibration metrics segmented by strategy, regime, DTE bucket,
and other dimensions.

Feature flag: CALIBRATION_ENABLED (default "1")
Minimum sample: MIN_CALIBRATION_TRADES (default 8)
Staleness TTL: CALIBRATION_MAX_AGE_DAYS (default 10) — a cached adjustments
blob older than this is NOT served (raw predictions are used, the documented
fallback) and a `calibration_stale` risk_alert fires. Kill switch
CALIBRATION_STALENESS_TTL_ENABLED (default ON; explicit 0/false/no/off
disables — empty/unset is ON per the #1038 flag convention).
"""

import logging
import math
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from supabase import Client

logger = logging.getLogger(__name__)

# ⚠ IMPORT-TIME flag (2026-07-09 EOD note): this is evaluated once at module
# import, so a Railway env flip does NOT take effect until the worker RECYCLES
# (tonight's re-enable needed a recycle for exactly this). 2c refactor to a
# call-time read was assessed non-trivial (multiple import sites read this as a
# module constant) and deferred — see the fail-loud logs at the apply/write
# sites which now make a disabled state visible from either side.
CALIBRATION_ENABLED = os.environ.get("CALIBRATION_ENABLED", "1") == "1"
MIN_CALIBRATION_TRADES = int(os.environ.get("MIN_CALIBRATION_TRADES", "8"))

# Maximum age of a served adjustments blob. The 2026-05-15→06-09 incident:
# the daily job silently no-opped for 25 days (insufficient_data below
# MIN_CALIBRATION_TRADES) while get_calibration_adjustments kept serving the
# frozen 05-15 blob — halving LONG_CALL EVs (two recorded edge_below_minimum
# gate flips: F 05-19, AAL 05-22) while LONG_PUT shipped raw. Design cadence
# is daily; 10 days of no writes means the loop is broken, not waiting.
CALIBRATION_MAX_AGE_DAYS = float(os.environ.get("CALIBRATION_MAX_AGE_DAYS", "10"))


def _staleness_ttl_enabled() -> bool:
    """CALIBRATION_STALENESS_TTL_ENABLED — default ON. Empty/unset → ON
    (the empty-string-no-op lesson); only explicit 0/false/no/off disables."""
    raw = os.environ.get("CALIBRATION_STALENESS_TTL_ENABLED", "")
    if not raw.strip():
        return True
    return raw.strip().lower() not in ("0", "false", "no", "off")


def _train_live_only_enabled() -> bool:
    """CALIBRATION_TRAIN_LIVE_ONLY — default ON. When ON, live-applied
    calibration trains ONLY on live (is_paper=false) outcomes, so shadow /
    internal-fill outcomes cannot drive an EV/PoP multiplier applied to live
    entries (the 2026-06-18 LONG_PUT ×1.5 incident: 2 shadow NFLX trades,
    incl. a +662 outlier, outvoted the lone under-performing live trade and
    inverted the live sign). Empty/unset → ON (the empty-string-no-op lesson);
    only explicit 0/false/no/off reverts to the legacy is_paper-blind set.
    Narrowing below MIN_CALIBRATION_TRADES → insufficient_data (raw mode, ×1.0)
    is the designed do-no-harm posture until live volume matures."""
    raw = os.environ.get("CALIBRATION_TRAIN_LIVE_ONLY", "")
    if not raw.strip():
        return True
    return raw.strip().lower() not in ("0", "false", "no", "off")


# Reserved top-level key in the adjustments blob carrying the OVERALL
# (all-segments) multipliers — the fallback for strategy keys with no
# segment coverage. Underscore prefix cannot collide with strategy names.
OVERALL_KEY = "_overall"

# Hard floor excluding pre-2026-04-13 outcome rows whose `pnl_realized` values
# are corrupted. Root cause: internal-paper-era and early Alpaca-paper era
# contained bugs (internal-fill reset 2026-04-04, close-order fixes 2026-04-10
# through 2026-04-15 — see CLAUDE.md Bugs Fixed) that produced P&L values
# orders of magnitude off from reality. Diagnostic on 2026-04-16 confirmed
# 34 outlier rows summing to +$95,408 vs Alpaca lifetime -$2,724.
#
# Filter is query-time only; source rows in learning_feedback_loops are
# preserved for lineage. The floor supplements the rolling window_days
# cutoff via `max(window_cutoff, CORRUPTED_PNL_FLOOR)` so calibration
# converges on clean data as the floor ages out of the rolling window.
#
# ⚠ LOCKSTEP (v3 view): learning_performance_summary_v3 (conviction's source
# view, #1043) hardcodes this same floor literal in its WHERE GREATEST(...) wall
# — a Postgres view can't read this env var. If this default changes, update
# that view via CREATE OR REPLACE in the same change (the migration drift-guard
# test pins them equal).
CORRUPTED_PNL_FLOOR = os.environ.get(
    # v5-A3 (2026-06-10): floor raised 04-13 → 04-16. The 04-13..04-16 band
    # contains the duplicate-ingest-era rows (ADBE/AMD ×2 — 76.5% of training
    # dollars were dup-counted) on top of the original pnl-corruption window.
    "CALIBRATION_PNL_FLOOR_DATE", "2026-04-16T00:00:00+00:00"
)

# EV-model epoch (v5-A1, 2026-06-10 ALERT): the debit-spread PoP/EV definition
# changed at this deploy (breakeven interpolation made reachable; previously
# PoP = raw long-leg delta). (prediction, outcome) pairs generated by the OLD
# predictor must not calibrate the NEW one — they measure a different model.
# Outcomes earlier than this epoch are excluded from calibration; the loop
# RELEARNS from post-fix predictions as closes accumulate (raw predictions
# serve in the interim — the documented insufficient-data fallback). Combined
# with the deploy-time blob reset (an empty adjustments row superseding the
# floored pre-fix blob), this prevents the double-correction (~0.48×0.5≈0.24)
# of applying delta-era multipliers to breakeven-era predictions.
# ⚠ LOCKSTEP (v3 view): learning_performance_summary_v3 (conviction's source
# view, #1043) hardcodes this same epoch literal in its WHERE GREATEST(...) wall
# — a Postgres view can't read this env var. If this default changes, update
# that view via CREATE OR REPLACE in the same change (the migration drift-guard
# test pins them equal), or conviction trains on a different epoch than
# calibration.
CALIBRATION_EV_EPOCH = os.environ.get(
    "CALIBRATION_EV_EPOCH", "2026-06-11T00:00:00+00:00"
)

# DTE buckets for segmentation.
# Aligned with post_trade_learning.py (the writer of signal_weight_history) so
# segment keys produced by the learning loop match the keys looked up here at
# suggestions_open. Prior buckets (0-7, 7-14, 14-30, 30-60) never matched the
# learning-side buckets, leaving the calibration feedback loop open-circuit.
DTE_BUCKETS = {
    "0-21":  (0, 22),
    "21-35": (22, 36),
    "35-45": (36, 46),
    "45+":   (46, 9999),
}


class CalibrationService:
    """Compare predicted EV/PoP against realized outcomes."""

    def __init__(self, supabase: Client):
        self.client = supabase

    def compute_calibration_report(
        self,
        user_id: str,
        window_days: int = 30,
    ) -> Dict[str, Any]:
        """
        Compare predicted vs realized across segments.

        Returns segmented calibration metrics including:
        - overall: aggregate EV and PoP calibration
        - by_strategy: per strategy type
        - by_regime: per market regime
        - by_window: per trading window (morning_limit, midday_entry)
        """
        outcomes = self._fetch_outcomes(user_id, window_days)

        if outcomes is None:
            # Fetch failure is not an empty cohort. Keep the metrics endpoint's
            # truth vocabulary aligned with the live adjustment path so a DB
            # outage can never render as a healthy no-data result.
            return {
                "status": "error",
                "reason": "fetch_failed",
                "window_days": window_days,
            }

        if not outcomes:
            return {
                "status": "no_data",
                "sample_size": 0,
                "window_days": window_days,
            }

        return {
            "status": "ok",
            "window_days": window_days,
            "computed_at": datetime.now(timezone.utc).isoformat(),
            "overall": self._compute_segment_metrics(outcomes),
            "by_strategy": self._group_and_compute(outcomes, "strategy"),
            "by_regime": self._group_and_compute(outcomes, "regime"),
            "by_window": self._group_and_compute(outcomes, "window"),
        }

    def compute_calibration_adjustments(
        self,
        user_id: str,
        window_days: int = 30,
    ) -> Dict[str, Any]:
        """
        Compute EV/PoP multipliers based on historical calibration error.

        Returns nested dict: {strategy: {regime: {dte_bucket: {ev_multiplier, pop_multiplier}}}}

        DTE-segmented calibration allows the system to learn that e.g.
        short-DTE debit spreads have different realized returns than
        long-DTE ones, even in the same regime.

        Falls back gracefully: callers that don't pass dte_bucket to
        apply_calibration() will get the "_all" bucket (aggregate).
        """
        outcomes = self._fetch_outcomes(user_id, window_days)

        if outcomes is None:
            # Fetch FAILED (not a legit-empty result) — surface status=error so
            # calibration_update does NOT clear the served blob to raw on a
            # transient query failure (#1076 point 3: last-good preserved).
            return {"status": "error", "reason": "fetch_failed",
                    "window_days": window_days}

        return self.build_adjustments_from_outcomes(outcomes)

    def build_adjustments_from_outcomes(
        self,
        outcomes: List[Dict[str, Any]],
        min_trades: Optional[int] = None,
    ) -> Dict[str, Any]:
        """PURE fit: an outcomes LIST → the adjustments blob, no DB round-trip.

        Extracted from compute_calibration_adjustments (2026-07-12) so the
        prequential validator can fit calibration on an arbitrary PREFIX of
        closes (1..k-1) to score close k out-of-sample without re-querying.
        Behavior-identical for the production default (min_trades=None →
        MIN_CALIBRATION_TRADES): compute_calibration_adjustments now delegates
        here. `min_trades` is a study knob ONLY — the validator lowers it to
        exercise calibration on the small live sample; production never passes it.
        Uses no self.client — safe to call on a CalibrationService(None)."""
        min_trades = MIN_CALIBRATION_TRADES if min_trades is None else min_trades

        if len(outcomes) < min_trades:
            return {
                "status": "insufficient_data",
                "sample_size": len(outcomes),
                "minimum_required": min_trades,
            }

        adjustments: Dict[str, Dict[str, Dict[str, Any]]] = {}

        # Group by (strategy, regime, dte_bucket)
        groups: Dict[str, List[Dict]] = {}
        for o in outcomes:
            strategy = o.get("strategy") or "unknown"
            regime = o.get("regime") or "unknown"
            dte_bucket = self._classify_dte(o)
            key = f"{strategy}|{regime}|{dte_bucket}"
            groups.setdefault(key, []).append(o)

            # Also accumulate into "_all" bucket for backward compatibility
            all_key = f"{strategy}|{regime}|_all"
            groups.setdefault(all_key, []).append(o)

        for key, group in groups.items():
            if len(group) < max(3, min_trades // 4):
                continue

            strategy, regime, dte_bucket = key.split("|", 2)
            metrics = self._compute_segment_metrics(group)

            ev_mult = self._compute_ev_multiplier(metrics)
            pop_mult = self._compute_pop_multiplier(metrics)

            # Only include non-trivial adjustments (>5% deviation)
            if abs(1.0 - ev_mult) > 0.05 or abs(1.0 - pop_mult) > 0.05:
                adjustments \
                    .setdefault(strategy, {}) \
                    .setdefault(regime, {})[dte_bucket] = {
                        "ev_multiplier": round(ev_mult, 4),
                        "pop_multiplier": round(pop_mult, 4),
                        "sample_size": metrics["sample_size"],
                        "ev_calibration_error": metrics["ev_calibration_error"],
                        "pop_calibration_error": metrics.get("pop_calibration_error"),
                    }

        # Persist the OVERALL (all-segments) multipliers under the reserved
        # top-level key so apply_calibration can fall back to them for a
        # strategy with no segment coverage instead of a SILENT ×1.0 — the
        # silent default let LONG_PUT_DEBIT_SPREAD ship raw EV/PoP for weeks
        # while the frozen blob halved only LONG_CALL (H9 silent-default class).
        overall_metrics = self._compute_segment_metrics(outcomes)
        adjustments[OVERALL_KEY] = {
            "ev_multiplier": round(self._compute_ev_multiplier(overall_metrics), 4),
            "pop_multiplier": round(self._compute_pop_multiplier(overall_metrics), 4),
            "sample_size": overall_metrics["sample_size"],
            "ev_calibration_error": overall_metrics["ev_calibration_error"],
        }

        return {
            "status": "ok",
            "adjustments": adjustments,
            "total_outcomes": len(outcomes),
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def _classify_dte(outcome: Dict[str, Any]) -> str:
        """Classify an outcome into a DTE bucket based on entry DTE.

        Matches post_trade_learning._compute_segment_key bucket boundaries so the
        learning-side writes and calibration-side reads share segment keys.
        """
        details = outcome.get("details_json") or {}
        dte = details.get("dte_at_entry") or outcome.get("dte_at_entry") or outcome.get("days_to_expiry")
        if dte is None:
            return "unknown"
        try:
            dte = int(float(dte))
        except (TypeError, ValueError):
            return "unknown"
        if dte <= 21:
            return "0-21"
        if dte <= 35:
            return "21-35"
        if dte <= 45:
            return "35-45"
        return "45+"

    # ── Data fetching ───────────────────────────────────────────────

    def fetch_eligible_outcomes(
        self,
        user_id: str,
        window_days: int,
        *,
        order_by_closed_at: bool = False,
    ) -> Optional[List[Dict[str, Any]]]:
        """THE shared production cohort-selection/fetch contract (F-A3-4).

        The SINGLE source of the eligible-outcome set for BOTH production
        calibration (via `_fetch_outcomes`) and the prequential validator (via
        `prequential_validator.fetch_live_outcomes`). No consumer may keep a
        second copy of the is_paper / epoch / corrupted-P&L predicate — parity
        is by DELEGATION here, not by re-implementation.

        Applies two floors:
        1. Rolling window cutoff = now - window_days
        2. Hard CORRUPTED_PNL_FLOOR that excludes pre-2026-04-13 rows with
           corrupted pnl_realized values (see module-level constant for full
           rationale). The effective cutoff is max of both plus the EV epoch so
           calibration never regresses onto bad data even if window_days is large.

        The live-only (is_paper=false) predicate is applied when
        CALIBRATION_TRAIN_LIVE_ONLY is ON (default). `is_paper`'s provenance is
        execution-mode-derived (paper_learning_ingest._resolve_is_paper returns
        `execution_mode != 'alpaca_live'` — so is_paper is FALSE iff the closing
        order's execution_mode == 'alpaca_live', and True for internal_paper /
        shadow / missing / any other simulated mode) — so "live" here means
        broker-filled, never a routing-eligibility label (F-A3-4 D2).

        Returns:
          None  — the query FAILED (caller MUST surface an error and MUST NOT
                  treat this as insufficiency: no green-on-vacuum),
          []    — success with ZERO eligible rows (legitimate insufficiency),
          [...] — eligible rows (sorted closed_at ASC when order_by_closed_at,
                  for prequential prefix scoring; unordered otherwise).
        """
        window_cutoff = (
            datetime.now(timezone.utc) - timedelta(days=window_days)
        ).isoformat()
        effective_cutoff = max(
            window_cutoff, CORRUPTED_PNL_FLOOR, CALIBRATION_EV_EPOCH
        )

        try:
            # SQL equivalent:
            #   SELECT ev_predicted, pop_predicted, pnl_realized, ...
            #   FROM learning_trade_outcomes_v3
            #   WHERE user_id = :user_id
            #     AND closed_at >= :effective_cutoff   -- hard floor +
            #                                            rolling window
            #
            # The closed_at floor excludes pre-2026-04-13 rows whose
            # pnl_realized is corrupted by the internal-fill reset
            # (2026-04-04) and close-order bug fixes (2026-04-10,
            # 2026-04-13, 2026-04-15). See CLAUDE.md Bugs Fixed.
            query = (
                self.client.table("learning_trade_outcomes_v3")
                .select(
                    "ev_predicted, pop_predicted, pnl_realized, pnl_predicted, "
                    "pnl_alpha, strategy, regime, window, ticker, closed_at, "
                    "model_version, is_paper"
                )
                .eq("user_id", user_id)
                .gte("closed_at", effective_cutoff)
            )
            # v5 (2026-06-18): when CALIBRATION_TRAIN_LIVE_ONLY is ON (default),
            # live-applied calibration trains on LIVE outcomes only. Shadow /
            # internal-fill outcomes must not drive an EV/PoP multiplier applied
            # to live entries — the 06-18 LONG_PUT ×1.5 incident (2 shadow NFLX,
            # incl. a +662 outlier, outvoted the lone under-performing live trade
            # and inverted the live sign). Explicit falsy reverts to is_paper-
            # blind. Narrowing below MIN_CALIBRATION_TRADES → insufficient_data
            # (raw mode) is the designed do-no-harm fallback.
            if _train_live_only_enabled():
                query = query.eq("is_paper", False)
            result = query.execute()
            rows = result.data or []
            if order_by_closed_at:
                # ISO-8601 closed_at → lexicographic sort == chronological.
                rows = sorted(rows, key=lambda r: r.get("closed_at") or "")
            return rows
        except Exception as e:
            # Return None (NOT []) so the caller distinguishes a query FAILURE
            # from a legitimately-empty result: compute_calibration_adjustments
            # maps None → status=error and the raw-mode blob-clear (#1076) does
            # NOT fire on a transient fetch error (point 3 — last-good preserved).
            # A real empty result still returns [] → insufficient_data.
            logger.error(f"[CALIBRATION] Failed to fetch outcomes: {e}")
            return None

    def _fetch_outcomes(
        self, user_id: str, window_days: int
    ) -> Optional[List[Dict[str, Any]]]:
        """Production calibration's fetch — a thin delegator to the shared
        `fetch_eligible_outcomes` contract. Kept as the internal name the
        calibration report/adjustment paths (and their tests) call; order is
        irrelevant to the aggregate fit so it takes the unordered result."""
        return self.fetch_eligible_outcomes(user_id, window_days)

    # ── Metrics computation ─────────────────────────────────────────

    def _compute_segment_metrics(
        self, outcomes: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Compute calibration metrics for a group of outcomes."""
        n = len(outcomes)
        if n == 0:
            return {"sample_size": 0}

        # EV calibration
        ev_predicted = [float(o.get("ev_predicted") or 0) for o in outcomes]
        pnl_realized = [float(o.get("pnl_realized") or 0) for o in outcomes]

        ev_pred_avg = sum(ev_predicted) / n
        ev_real_avg = sum(pnl_realized) / n
        ev_cal_error = ev_pred_avg - ev_real_avg

        # EV RMSE
        ev_sq_errors = [
            (p - r) ** 2 for p, r in zip(ev_predicted, pnl_realized)
        ]
        ev_rmse = math.sqrt(sum(ev_sq_errors) / n)

        # PoP calibration (predicted probability vs actual win rate).
        # BASIS FIX (2026-06-18): measure the realized win rate over the SAME
        # rows that inform the predicted average — rows with a non-null
        # pop_predicted. Pre-fix used wins/n (ALL rows) against a predicted
        # average computed over only non-null-pop rows — a denominator-basis
        # mismatch. On the 06-18 LONG_PUT segment it read pred 0.6581 (1 non-null
        # row) vs realized 3/3 (incl. 2 null-pop shadow wins) → -0.34 error.
        # win_count/loss_count below stay over ALL rows (the overall win stats).
        pop_rows = [o for o in outcomes if o.get("pop_predicted") is not None]
        pop_predicted_vals = [float(o.get("pop_predicted") or 0) for o in pop_rows]
        wins = sum(1 for o in outcomes if float(o.get("pnl_realized") or 0) > 0)

        pop_pred_avg = (
            sum(pop_predicted_vals) / len(pop_predicted_vals)
            if pop_predicted_vals
            else None
        )
        pop_realized_rate = (
            sum(1 for o in pop_rows if float(o.get("pnl_realized") or 0) > 0)
            / len(pop_rows)
            if pop_rows
            else 0.0
        )
        pop_cal_error = (
            (pop_pred_avg - pop_realized_rate)
            if pop_pred_avg is not None
            else None
        )

        # Win/loss stats
        total_pnl = sum(pnl_realized)
        avg_win = 0.0
        avg_loss = 0.0
        win_pnls = [r for r in pnl_realized if r > 0]
        loss_pnls = [r for r in pnl_realized if r < 0]
        if win_pnls:
            avg_win = sum(win_pnls) / len(win_pnls)
        if loss_pnls:
            avg_loss = sum(loss_pnls) / len(loss_pnls)

        return {
            "sample_size": n,
            "ev_predicted_avg": round(ev_pred_avg, 2),
            "ev_realized_avg": round(ev_real_avg, 2),
            "ev_calibration_error": round(ev_cal_error, 2),
            "ev_rmse": round(ev_rmse, 2),
            "pop_predicted_avg": round(pop_pred_avg, 4) if pop_pred_avg is not None else None,
            "pop_realized_rate": round(pop_realized_rate, 4),
            "pop_calibration_error": round(pop_cal_error, 4) if pop_cal_error is not None else None,
            "total_pnl": round(total_pnl, 2),
            "win_count": wins,
            "loss_count": n - wins,
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
        }

    def _group_and_compute(
        self, outcomes: List[Dict], key: str
    ) -> Dict[str, Dict[str, Any]]:
        """Group outcomes by a field and compute metrics per group."""
        groups: Dict[str, List[Dict]] = {}
        for o in outcomes:
            val = o.get(key) or "unknown"
            groups.setdefault(val, []).append(o)

        return {
            k: self._compute_segment_metrics(v)
            for k, v in groups.items()
            if len(v) >= 3  # minimum for meaningful stats
        }

    # ── Multiplier computation ──────────────────────────────────────

    @staticmethod
    def _compute_ev_multiplier(metrics: Dict[str, Any]) -> float:
        """
        If predicted EV is consistently higher than realized,
        return a multiplier < 1.0 to deflate future predictions.

        Clamped to [0.5, 1.5] to prevent extreme corrections.
        """
        pred = metrics.get("ev_predicted_avg", 0)
        if abs(pred) < 1.0:
            return 1.0  # Too small to calibrate

        realized = metrics.get("ev_realized_avg", 0)
        ratio = realized / pred
        return max(0.5, min(1.5, ratio))

    @staticmethod
    def _compute_pop_multiplier(metrics: Dict[str, Any]) -> float:
        """
        If predicted PoP is consistently higher than realized win rate,
        return a multiplier < 1.0 to deflate future PoP estimates.

        Clamped to [0.5, 1.5].
        """
        pred = metrics.get("pop_predicted_avg")
        if pred is None or pred < 0.05:
            return 1.0

        realized = metrics.get("pop_realized_rate", 0)
        ratio = realized / pred
        return max(0.5, min(1.5, ratio))


# Once-per-process-per-day guard so the staleness alert doesn't spam
# risk_alerts on every suggestion cycle while the blob stays stale.
_STALE_ALERTED_ON: Optional[str] = None


def get_calibration_adjustments(
    user_id: str, supabase: Client
) -> Dict[str, Dict[str, Dict[str, float]]]:
    """
    Convenience function: load cached adjustments from Supabase.

    Returns {} when none are cached OR when the latest blob is older than
    CALIBRATION_MAX_AGE_DAYS (the documented "raw predictions are used
    as-is" fallback) — a stale blob is logged + alerted, never silently
    served. Returns: {strategy: {regime: {ev_multiplier, pop_multiplier}}}
    """
    global _STALE_ALERTED_ON
    try:
        result = (
            supabase.table("calibration_adjustments")
            .select("adjustments, computed_at")
            .eq("user_id", user_id)
            .order("computed_at", desc=True)
            .limit(1)
            .execute()
        )
        if not result.data:
            return {}

        row = result.data[0]
        computed_at_raw = row.get("computed_at")
        if _staleness_ttl_enabled() and computed_at_raw:
            try:
                ts = str(computed_at_raw).replace("Z", "+00:00")
                # Supabase may emit a space separator instead of 'T'
                computed_at = datetime.fromisoformat(ts.replace(" ", "T", 1))
                if computed_at.tzinfo is None:
                    computed_at = computed_at.replace(tzinfo=timezone.utc)
                age_days = (
                    datetime.now(timezone.utc) - computed_at
                ).total_seconds() / 86400.0
            except (TypeError, ValueError):
                age_days = None
            if age_days is not None and age_days > CALIBRATION_MAX_AGE_DAYS:
                logger.warning(
                    "[CALIBRATION] cached adjustments are %.1f days old "
                    "(> %.0f-day TTL, computed_at=%s) — serving NO adjustments "
                    "(raw predictions) instead of a frozen blob.",
                    age_days, CALIBRATION_MAX_AGE_DAYS, computed_at_raw,
                )
                today = datetime.now(timezone.utc).date().isoformat()
                if _STALE_ALERTED_ON != today:
                    _STALE_ALERTED_ON = today
                    try:
                        from packages.quantum.observability.alerts import alert
                        alert(
                            supabase,
                            alert_type="calibration_stale",
                            severity="warning",
                            message=(
                                f"calibration_adjustments is {age_days:.1f} days old "
                                f"(TTL {CALIBRATION_MAX_AGE_DAYS:.0f}d) — raw predictions "
                                f"in use; the daily calibration_update is not writing"
                            ),
                            user_id=user_id,
                            metadata={
                                "computed_at": str(computed_at_raw),
                                "age_days": round(age_days, 1),
                                "max_age_days": CALIBRATION_MAX_AGE_DAYS,
                                "function_name": "get_calibration_adjustments",
                            },
                        )
                    except Exception as alert_err:
                        logger.warning(
                            "[CALIBRATION] stale-alert write failed: %s", alert_err
                        )
                return {}

        return row.get("adjustments") or {}
    except Exception as e:
        # Table may not exist yet (fresh installs) — fall through to empty,
        # but never silently (the prior bare `except: pass` hid real errors).
        logger.warning(
            "[CALIBRATION] get_calibration_adjustments failed (serving no "
            "adjustments): %s: %s", type(e).__name__, e,
        )

    return {}


def apply_calibration(
    ev: float,
    pop: float,
    strategy: str,
    regime: str,
    adjustments: Dict[str, Dict[str, Dict[str, float]]],
    dte_bucket: Optional[str] = None,
) -> tuple:
    """
    Apply calibration multipliers to raw EV and PoP.

    Lookup order:
    1. (strategy, regime, dte_bucket) — most specific
    2. (strategy, regime, "_all") — aggregate for that strategy/regime
    3. "_overall" — the blob's all-segments multiplier (LOGGED fallback;
       closes the silent-×1.0 hole that let an uncovered strategy ship raw
       while covered strategies were halved)
    4. 1.0 — no adjustment (only when the blob carries no overall either)

    Returns (adjusted_ev, adjusted_pop).
    Logs adjustment when applied.
    """
    strat_adj = adjustments.get(strategy, {})
    regime_adj = strat_adj.get(regime, {})

    # New format: regime_adj is {dte_bucket: {ev_multiplier, pop_multiplier}}
    # Old format: regime_adj is {ev_multiplier, pop_multiplier} directly
    # Detect format by checking if ev_multiplier exists at top level (old format)
    if "ev_multiplier" in regime_adj:
        # Old format (backward compatibility with cached rows)
        bucket_adj = regime_adj
    else:
        # New format: try specific DTE bucket, fall back to _all
        bucket_adj = {}
        if dte_bucket:
            bucket_adj = regime_adj.get(dte_bucket, {})
        if not bucket_adj:
            bucket_adj = regime_adj.get("_all", {})

    if not bucket_adj and adjustments:
        overall_adj = adjustments.get(OVERALL_KEY) or {}
        if overall_adj:
            bucket_adj = overall_adj
            logger.info(
                "[CALIBRATION] no segment coverage for %s/%s — using overall "
                "multiplier (ev×%.3f, pop×%.3f, n=%s)",
                strategy, regime,
                overall_adj.get("ev_multiplier", 1.0),
                overall_adj.get("pop_multiplier", 1.0),
                overall_adj.get("sample_size"),
            )

    ev_mult = bucket_adj.get("ev_multiplier", 1.0)
    pop_mult = bucket_adj.get("pop_multiplier", 1.0)

    adj_ev = ev * ev_mult
    # Probability of profit is a probability — it must live in [0, 1]. The
    # calibration multiplier is clamped to [0.5, 1.5], so without an explicit
    # clamp on the output, a raw PoP of 0.7 × 1.5 = 1.05 leaks into downstream
    # EV math as if the trade wins >100% of the time.
    _pre_clamp_pop = pop * pop_mult
    adj_pop = max(0.0, min(1.0, _pre_clamp_pop))
    # BOUNDARY-LOG (2026-07-10): clamp-AND-LOG so the >1.0 overshoot the
    # free-look caught is never silently erased. ATTRIBUTION (corrected): the
    # overshoot originates HERE — the calibration MULTIPLIER (pop × pop_mult),
    # silently clamped since 2026-04-16 — NOT the delta-cushion composition
    # path (ev_calculator's convex-combination PoP is bounded ≤ 1 by
    # construction; raw pre-calibration pop has never exceeded 0.7945). Legs
    # are out of scope at this apply site — strategy/regime/dte only.
    # Queryable marker: grep "[CALIBRATION] POP_CLAMP_ENGAGED". Reopen trigger:
    # frequent engagement → probability-space-aware multiplier/cushion revision.
    # DORMANT-BY-ARITHMETIC in the present regime: pop_mult is floored at 0.5
    # and currently sits at that floor, so pop × 0.5 ≤ 0.5 can never breach 1.0
    # — this log CANNOT fire today. It is insurance for the day the multiplier
    # climbs back above 1.0, NOT dead/broken code. Do not read "never fires" as
    # "broken".
    if _pre_clamp_pop > 1.0 or _pre_clamp_pop < 0.0:
        logger.warning(
            "[CALIBRATION] POP_CLAMP_ENGAGED raw_pop=%.4f pop_mult=%.3f "
            "product=%.4f clamped=%.4f seg=%s/%s/%s — a probability exceeded "
            "[0,1] at the calibration apply site (boundary signal).",
            pop, pop_mult, _pre_clamp_pop, adj_pop,
            strategy, regime, dte_bucket or "_all",
        )

    if ev_mult != 1.0 or pop_mult != 1.0:
        bucket_label = dte_bucket or "_all"
        logger.info(
            f"[CALIBRATION] Adjusted {strategy}/{regime}/{bucket_label}: "
            f"EV {ev:.2f}→{adj_ev:.2f} (×{ev_mult:.3f}), "
            f"PoP {pop:.3f}→{adj_pop:.3f} (×{pop_mult:.3f})"
        )

    return adj_ev, adj_pop
