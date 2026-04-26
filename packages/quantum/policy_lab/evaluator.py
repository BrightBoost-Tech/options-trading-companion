"""
Daily cohort evaluator — computes utility scores, compares cohorts, and
checks promotion eligibility using Bayesian posterior probability.

Champion/challenger design:
- One cohort is "default" (promoted_at is not null = champion)
- Other cohorts are challengers
- All three run in paper simultaneously

Promotion rules (ALL must be true):
1. At least MIN_TRADING_DAYS of data
2. At least MIN_TRADE_COUNT closed trades
3. No hard risk breaches (drawdown > HARD_DRAWDOWN_LIMIT)
4. Challenger utility > default utility by UTILITY_MARGIN (15%)
5. Posterior probability challenger is better > POSTERIOR_THRESHOLD (70%)
6. Challenger max drawdown not worse than default
7. Cooldown period since last promotion elapsed
"""

import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Dict, Any, List, Optional
from collections import defaultdict

from packages.quantum.policy_lab.scoring import (
    CohortDailyMetrics,
    CohortScore,
    score_cohort_window,
    posterior_probability_better,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PROMOTION_WINDOW = int(os.environ.get("POLICY_LAB_PROMOTION_WINDOW", "7"))
AUTO_PROMOTE = os.environ.get("POLICY_LAB_AUTOPROMOTE", "").lower() in ("1", "true")

# Promotion gates
MIN_TRADING_DAYS = 3
MIN_TRADE_COUNT = 10
UTILITY_MARGIN = 0.15          # challenger must be 15% better
POSTERIOR_THRESHOLD = 0.70     # P(challenger > default) must exceed this
HARD_DRAWDOWN_LIMIT = -0.20   # -20% max drawdown = hard breach
COOLDOWN_DAYS = 2              # days between promotions
ROLLBACK_HOURS = 24            # rollback window for new champion


# ---------------------------------------------------------------------------
# Daily evaluation (unchanged — computes metrics and upserts)
# ---------------------------------------------------------------------------

def evaluate_cohorts(
    user_id: str,
    eval_date: date,
    supabase,
) -> Dict[str, Any]:
    """
    Compute daily performance metrics for each active cohort and upsert
    into policy_daily_scores. (Legacy policy_lab_daily_results write
    removed 2026-04-26 — schema drift caused PGRST204; zero readers in
    apps/web/. Reader endpoint cleanup tracked as backlog #73.)

    Returns comparison summary dict.
    """
    cohorts_res = supabase.table("policy_lab_cohorts") \
        .select("id, cohort_name, portfolio_id, policy_config") \
        .eq("user_id", user_id) \
        .eq("is_active", True) \
        .execute()
    cohorts = cohorts_res.data or []

    if not cohorts:
        return {"status": "no_cohorts", "results": []}

    eval_date_str = eval_date.isoformat()
    results = []

    for cohort in cohorts:
        cohort_id = cohort["id"]
        portfolio_id = cohort["portfolio_id"]
        cohort_name = cohort["cohort_name"]

        try:
            metrics = _compute_cohort_metrics(
                supabase, portfolio_id, eval_date_str,
            )

            # Upsert into policy_daily_scores with utility
            daily_m = CohortDailyMetrics(
                cohort_id=cohort_id,
                cohort_name=cohort_name,
                trade_date=eval_date_str,
                realized_pnl=metrics["realized_pl"],
                unrealized_pnl=metrics["unrealized_pl"],
                max_drawdown_pct=metrics.get("max_drawdown", 0),
                trade_count=metrics["positions_closed"],
                win_rate=metrics.get("win_rate"),
                avg_winner=metrics.get("avg_winner", 0),
                avg_loser=metrics.get("avg_loser", 0),
            )

            from packages.quantum.policy_lab.scoring import compute_daily_utility
            utility = compute_daily_utility(daily_m)

            scores_row = {
                "cohort_id": cohort_id,
                "trade_date": eval_date_str,
                "utility_score": round(utility, 2),
                "realized_pnl": metrics["realized_pl"],
                "unrealized_pnl": metrics["unrealized_pl"],
                "max_drawdown_pct": metrics.get("max_drawdown", 0),
                "trade_count": metrics["positions_closed"],
                "win_rate": metrics.get("win_rate"),
                "avg_winner": metrics.get("avg_winner"),
                "avg_loser": metrics.get("avg_loser"),
                "symbols_traded": metrics.get("symbols_traded", []),
            }
            try:
                supabase.table("policy_daily_scores") \
                    .upsert(scores_row, on_conflict="cohort_id,trade_date") \
                    .execute()
            except Exception as e:
                logger.warning(f"policy_daily_scores_upsert_error: {e}")

            results.append({
                "cohort_name": cohort_name,
                "cohort_id": cohort_id,
                "utility": round(utility, 2),
                **metrics,
            })

            logger.info(
                f"policy_lab_eval: cohort={cohort_name} date={eval_date_str} "
                f"utility={utility:.2f} realized={metrics['realized_pl']:.2f} "
                f"unrealized={metrics['unrealized_pl']:.2f} "
                f"win_rate={metrics.get('win_rate')}"
            )

        except Exception as e:
            logger.exception(
                "policy_lab_eval_error: cohort=%s",
                cohort_name,
                extra={
                    "cohort_id": str(cohort_id) if cohort_id else None,
                    "user_id": user_id,
                },
            )
            # Surface per-cohort failures via risk_alerts. Without this,
            # errors here were silently swallowed — the pattern that
            # hid the ImportError fixed in PR #807 and the schema drift
            # fixed in this PR.
            try:
                supabase.table("risk_alerts").insert({
                    "user_id": user_id,
                    "alert_type": "policy_lab_eval_cohort_failure",
                    "severity": "warning",
                    "message": f"evaluate_cohorts failed for cohort '{cohort_name}': {type(e).__name__}",
                    "metadata": {
                        "cohort_name": cohort_name,
                        "cohort_id": str(cohort_id) if cohort_id else None,
                        "exception_type": type(e).__name__,
                        "exception_str": str(e)[:500],
                        "function": "evaluate_cohorts",
                        "stage": "per_cohort_processing",
                    },
                }).execute()
            except Exception:
                logger.exception(
                    "policy_lab: failed to write risk_alert for cohort failure",
                    extra={"original_error": str(e)[:200]},
                )
            results.append({"cohort_name": cohort_name, "error": str(e)})

    return {"status": "ok", "eval_date": eval_date_str, "results": results}


def _compute_cohort_metrics(
    supabase,
    portfolio_id: str,
    eval_date_str: str,
) -> Dict[str, Any]:
    """Compute performance metrics for a single cohort portfolio on a given date."""

    # Positions closed today
    closed_res = supabase.table("paper_positions") \
        .select("realized_pl, symbol") \
        .eq("portfolio_id", portfolio_id) \
        .eq("status", "closed") \
        .gte("closed_at", f"{eval_date_str}T00:00:00") \
        .lt("closed_at", f"{eval_date_str}T23:59:59.999") \
        .execute()
    closed = closed_res.data or []

    realized_pls = [float(p.get("realized_pl") or 0) for p in closed]
    realized_pl = sum(realized_pls)
    positions_closed = len(closed)
    wins = [pl for pl in realized_pls if pl > 0]
    losses = [pl for pl in realized_pls if pl < 0]
    win_rate = (len(wins) / positions_closed) if positions_closed > 0 else None
    avg_winner = (sum(wins) / len(wins)) if wins else 0.0
    avg_loser = (sum(losses) / len(losses)) if losses else 0.0
    symbols_traded = list(set(p.get("symbol", "") for p in closed if p.get("symbol")))

    # Open positions (unrealized P&L)
    open_res = supabase.table("paper_positions") \
        .select("unrealized_pl") \
        .eq("portfolio_id", portfolio_id) \
        .eq("status", "open") \
        .neq("quantity", 0) \
        .execute()
    open_positions = open_res.data or []
    unrealized_pl = sum(float(p.get("unrealized_pl") or 0) for p in open_positions)

    # Positions opened today
    opened_res = supabase.table("paper_positions") \
        .select("id", count="exact") \
        .eq("portfolio_id", portfolio_id) \
        .gte("created_at", f"{eval_date_str}T00:00:00") \
        .lt("created_at", f"{eval_date_str}T23:59:59.999") \
        .execute()
    positions_opened = opened_res.count or 0

    # Portfolio capital
    port_res = supabase.table("paper_portfolios") \
        .select("cash_balance, net_liq") \
        .eq("id", portfolio_id) \
        .single() \
        .execute()
    portfolio = port_res.data or {}
    net_liq = float(portfolio.get("net_liq") or portfolio.get("cash_balance") or 100000)
    cash = float(portfolio.get("cash_balance") or 0)
    capital_deployed = max(0, net_liq - cash)

    total_pl = realized_pl + unrealized_pl

    # Max drawdown approximation: worst single-day loss as fraction of net_liq
    max_drawdown = 0.0
    if net_liq > 0 and total_pl < 0:
        max_drawdown = total_pl / net_liq

    return {
        "positions_opened": positions_opened,
        "positions_closed": positions_closed,
        "realized_pl": round(realized_pl, 2),
        "unrealized_pl": round(unrealized_pl, 2),
        "total_pl": round(total_pl, 2),
        "win_rate": round(win_rate, 4) if win_rate is not None else None,
        "avg_winner": round(avg_winner, 2),
        "avg_loser": round(avg_loser, 2),
        "capital_deployed": round(capital_deployed, 2),
        "risk_budget_used": round(capital_deployed / net_liq, 4) if net_liq > 0 else 0,
        "max_drawdown": round(max_drawdown, 4),
        "symbols_traded": symbols_traded,
    }


# ---------------------------------------------------------------------------
# Promotion check (utility-based with Bayesian confidence)
# ---------------------------------------------------------------------------

def check_promotion(
    user_id: str,
    supabase,
) -> Dict[str, Any]:
    """
    Check if any challenger cohort qualifies for promotion over the current
    default using utility-based scoring with Bayesian posterior confidence.

    Returns promotion decision dict with full metrics snapshot.
    """
    cohorts_res = supabase.table("policy_lab_cohorts") \
        .select("id, cohort_name, promoted_at") \
        .eq("user_id", user_id) \
        .eq("is_active", True) \
        .execute()
    cohorts = cohorts_res.data or []

    if len(cohorts) < 2:
        return {"status": "insufficient_cohorts"}

    # Identify current champion (most recently promoted, or first if none)
    champion = None
    challengers = []
    for c in cohorts:
        if c.get("promoted_at"):
            if champion is None or (c["promoted_at"] > champion["promoted_at"]):
                champion = c
        # All are potential challengers initially
    if champion is None:
        # No promoted cohort — pick neutral as default champion
        champion = next((c for c in cohorts if c["cohort_name"] == "neutral"), cohorts[0])

    challengers = [c for c in cohorts if c["id"] != champion["id"]]
    id_to_name = {c["id"]: c["cohort_name"] for c in cohorts}

    # Fetch trailing window of daily scores
    window_start = (date.today() - timedelta(days=PROMOTION_WINDOW)).isoformat()
    cohort_ids = [c["id"] for c in cohorts]

    scores_res = supabase.table("policy_daily_scores") \
        .select("*") \
        .in_("cohort_id", cohort_ids) \
        .gte("trade_date", window_start) \
        .order("trade_date", desc=False) \
        .execute()
    rows = scores_res.data or []

    if not rows:
        return {"status": "no_scores_data"}

    # Group rows by cohort_id
    by_cohort: Dict[str, List[Dict]] = defaultdict(list)
    for r in rows:
        by_cohort[r["cohort_id"]].append(r)

    # Build CohortScore for each
    scored: Dict[str, CohortScore] = {}
    for cid, daily_rows in by_cohort.items():
        metrics = [
            CohortDailyMetrics(
                cohort_id=cid,
                cohort_name=id_to_name.get(cid, "?"),
                trade_date=r["trade_date"],
                realized_pnl=float(r.get("realized_pnl") or 0),
                unrealized_pnl=float(r.get("unrealized_pnl") or 0),
                max_drawdown_pct=float(r.get("max_drawdown_pct") or 0),
                expected_shortfall=float(r.get("expected_shortfall") or 0),
                execution_quality=float(r.get("execution_quality") or 0),
                calibration_quality=float(r.get("calibration_quality") or 0),
                trade_count=int(r.get("trade_count") or 0),
                win_rate=float(r["win_rate"]) if r.get("win_rate") is not None else None,
                avg_winner=float(r.get("avg_winner") or 0),
                avg_loser=float(r.get("avg_loser") or 0),
                regime_at_close=r.get("regime_at_close") or "",
            )
            for r in daily_rows
        ]
        cs = score_cohort_window(metrics)
        if cs:
            scored[cid] = cs

    champion_score = scored.get(champion["id"])
    if not champion_score:
        return {"status": "champion_no_data", "champion": champion["cohort_name"]}

    # Evaluate each challenger
    best_challenger = None
    best_posterior = 0.0
    evaluations = []

    for ch in challengers:
        ch_score = scored.get(ch["id"])
        if not ch_score:
            evaluations.append({
                "cohort": ch["cohort_name"],
                "verdict": "no_data",
            })
            continue

        # Gate 1: Minimum trading days
        if ch_score.trading_days < MIN_TRADING_DAYS:
            evaluations.append({
                "cohort": ch["cohort_name"],
                "verdict": "insufficient_days",
                "trading_days": ch_score.trading_days,
                "required": MIN_TRADING_DAYS,
            })
            continue

        # Gate 2: Minimum trade count
        if ch_score.trade_count < MIN_TRADE_COUNT:
            evaluations.append({
                "cohort": ch["cohort_name"],
                "verdict": "insufficient_trades",
                "trade_count": ch_score.trade_count,
                "required": MIN_TRADE_COUNT,
            })
            continue

        # Gate 3: No hard risk breach
        if ch_score.max_drawdown_pct < HARD_DRAWDOWN_LIMIT:
            evaluations.append({
                "cohort": ch["cohort_name"],
                "verdict": "hard_risk_breach",
                "max_drawdown": ch_score.max_drawdown_pct,
                "limit": HARD_DRAWDOWN_LIMIT,
            })
            continue

        # Gate 4: Utility margin
        if champion_score.utility != 0:
            margin = (ch_score.utility - champion_score.utility) / abs(champion_score.utility)
        else:
            margin = 1.0 if ch_score.utility > 0 else 0.0

        if margin < UTILITY_MARGIN:
            evaluations.append({
                "cohort": ch["cohort_name"],
                "verdict": "insufficient_margin",
                "challenger_utility": ch_score.utility,
                "champion_utility": champion_score.utility,
                "margin": round(margin, 4),
                "required": UTILITY_MARGIN,
            })
            continue

        # Gate 5: Posterior probability
        posterior = posterior_probability_better(
            ch_score.daily_utilities,
            champion_score.daily_utilities,
        )

        if posterior < POSTERIOR_THRESHOLD:
            evaluations.append({
                "cohort": ch["cohort_name"],
                "verdict": "insufficient_confidence",
                "posterior": round(posterior, 4),
                "required": POSTERIOR_THRESHOLD,
                "margin": round(margin, 4),
            })
            continue

        # Gate 6: Drawdown not worse than champion
        if ch_score.max_drawdown_pct < champion_score.max_drawdown_pct:
            evaluations.append({
                "cohort": ch["cohort_name"],
                "verdict": "worse_drawdown",
                "challenger_dd": ch_score.max_drawdown_pct,
                "champion_dd": champion_score.max_drawdown_pct,
            })
            continue

        # All gates passed
        evaluations.append({
            "cohort": ch["cohort_name"],
            "verdict": "eligible",
            "utility": ch_score.utility,
            "margin": round(margin, 4),
            "posterior": round(posterior, 4),
        })

        if posterior > best_posterior:
            best_posterior = posterior
            best_challenger = ch

    # No eligible challenger
    if not best_challenger:
        logger.info(
            f"policy_lab_promotion_check: user={user_id} champion={champion['cohort_name']} "
            f"no_challenger_eligible evaluations={evaluations}"
        )
        return {
            "status": "no_promotion",
            "champion": champion["cohort_name"],
            "evaluations": evaluations,
        }

    winner_name = best_challenger["cohort_name"]
    winner_score = scored[best_challenger["id"]]

    # Check cooldown
    last_promo_res = supabase.table("policy_lab_promotions") \
        .select("created_at") \
        .eq("user_id", user_id) \
        .order("created_at", desc=True) \
        .limit(1) \
        .execute()
    if last_promo_res.data:
        last_promo_time = datetime.fromisoformat(
            last_promo_res.data[0]["created_at"].replace("Z", "+00:00")
        )
        cooldown_until = last_promo_time + timedelta(days=COOLDOWN_DAYS)
        if datetime.now(timezone.utc) < cooldown_until:
            logger.info(
                f"policy_lab_promotion_cooldown: user={user_id} "
                f"winner={winner_name} cooldown_until={cooldown_until.isoformat()}"
            )
            return {
                "status": "cooldown",
                "champion": champion["cohort_name"],
                "eligible_challenger": winner_name,
                "cooldown_until": cooldown_until.isoformat(),
            }

    # Build full metrics snapshot
    metrics_snapshot = {
        "champion": {
            "name": champion["cohort_name"],
            "utility": champion_score.utility,
            "realized_pnl": champion_score.realized_pnl,
            "max_drawdown": champion_score.max_drawdown_pct,
            "trade_count": champion_score.trade_count,
            "trading_days": champion_score.trading_days,
        },
        "challenger": {
            "name": winner_name,
            "utility": winner_score.utility,
            "realized_pnl": winner_score.realized_pnl,
            "max_drawdown": winner_score.max_drawdown_pct,
            "trade_count": winner_score.trade_count,
            "trading_days": winner_score.trading_days,
            "posterior": round(best_posterior, 4),
        },
        "evaluations": evaluations,
        "window_days": PROMOTION_WINDOW,
        "gates": {
            "min_trading_days": MIN_TRADING_DAYS,
            "min_trade_count": MIN_TRADE_COUNT,
            "utility_margin": UTILITY_MARGIN,
            "posterior_threshold": POSTERIOR_THRESHOLD,
            "hard_drawdown_limit": HARD_DRAWDOWN_LIMIT,
        },
    }

    promotion_row = {
        "user_id": user_id,
        "promoted_cohort": winner_name,
        "demoted_cohort": champion["cohort_name"],
        "reason": (
            f"Utility {winner_score.utility:.0f} vs {champion_score.utility:.0f} "
            f"(+{best_posterior:.0%} confidence)"
        ),
        "metrics_snapshot": metrics_snapshot,
        "auto_promoted": AUTO_PROMOTE,
        "confirmed_by": "auto" if AUTO_PROMOTE else None,
    }

    supabase.table("policy_lab_promotions").insert(promotion_row).execute()

    if AUTO_PROMOTE:
        now_iso = datetime.now(timezone.utc).isoformat()
        # Promote challenger
        supabase.table("policy_lab_cohorts") \
            .update({"promoted_at": now_iso}) \
            .eq("id", best_challenger["id"]) \
            .execute()
        # Clear champion's promoted_at (demote to challenger)
        supabase.table("policy_lab_cohorts") \
            .update({"promoted_at": None}) \
            .eq("id", champion["id"]) \
            .execute()

    logger.info(
        f"policy_lab_promotion: user={user_id} "
        f"champion={champion['cohort_name']}→{winner_name} "
        f"utility={winner_score.utility:.0f} vs {champion_score.utility:.0f} "
        f"posterior={best_posterior:.2%} auto={AUTO_PROMOTE}"
    )

    return {
        "status": "promoted" if AUTO_PROMOTE else "recommended",
        "winner": winner_name,
        "demoted": champion["cohort_name"],
        "auto_promoted": AUTO_PROMOTE,
        "posterior": round(best_posterior, 4),
        "metrics_snapshot": metrics_snapshot,
    }


# ---------------------------------------------------------------------------
# Rollback check (runs ~24h after promotion)
# ---------------------------------------------------------------------------

def check_rollback(
    user_id: str,
    supabase,
) -> Dict[str, Any]:
    """
    Check if a recently promoted champion should be rolled back.

    If the new champion breaches hard drawdown or loss limits within
    ROLLBACK_HOURS of promotion, revert to the previous champion.
    """
    cohorts_res = supabase.table("policy_lab_cohorts") \
        .select("id, cohort_name, promoted_at") \
        .eq("user_id", user_id) \
        .eq("is_active", True) \
        .execute()
    cohorts = cohorts_res.data or []

    current_champion = None
    for c in cohorts:
        if c.get("promoted_at"):
            if current_champion is None or c["promoted_at"] > current_champion["promoted_at"]:
                current_champion = c

    if not current_champion or not current_champion.get("promoted_at"):
        return {"status": "no_champion"}

    # Check if within rollback window
    promoted_at = datetime.fromisoformat(
        current_champion["promoted_at"].replace("Z", "+00:00")
    )
    rollback_deadline = promoted_at + timedelta(hours=ROLLBACK_HOURS)

    if datetime.now(timezone.utc) > rollback_deadline:
        return {"status": "past_rollback_window"}

    # Check if champion has breached since promotion
    promoted_date_str = promoted_at.date().isoformat()
    scores_res = supabase.table("policy_daily_scores") \
        .select("utility_score, max_drawdown_pct, realized_pnl") \
        .eq("cohort_id", current_champion["id"]) \
        .gte("trade_date", promoted_date_str) \
        .execute()
    scores = scores_res.data or []

    for s in scores:
        dd = float(s.get("max_drawdown_pct") or 0)
        if dd < HARD_DRAWDOWN_LIMIT:
            # Breach — rollback
            logger.critical(
                f"policy_lab_rollback: user={user_id} "
                f"champion={current_champion['cohort_name']} "
                f"drawdown={dd} limit={HARD_DRAWDOWN_LIMIT} — "
                f"rolling back"
            )

            # Find previous champion from last promotion
            last_promo_res = supabase.table("policy_lab_promotions") \
                .select("demoted_cohort") \
                .eq("user_id", user_id) \
                .order("created_at", desc=True) \
                .limit(1) \
                .execute()

            old_champion_name = None
            if last_promo_res.data:
                old_champion_name = last_promo_res.data[0].get("demoted_cohort")

            if old_champion_name:
                # Re-promote old champion
                now_iso = datetime.now(timezone.utc).isoformat()
                supabase.table("policy_lab_cohorts") \
                    .update({"promoted_at": now_iso}) \
                    .eq("user_id", user_id) \
                    .eq("cohort_name", old_champion_name) \
                    .execute()
                # Demote current
                supabase.table("policy_lab_cohorts") \
                    .update({"promoted_at": None}) \
                    .eq("id", current_champion["id"]) \
                    .execute()

                # Log rollback as promotion
                supabase.table("policy_lab_promotions").insert({
                    "user_id": user_id,
                    "promoted_cohort": old_champion_name,
                    "demoted_cohort": current_champion["cohort_name"],
                    "reason": f"ROLLBACK: drawdown {dd:.2%} breached {HARD_DRAWDOWN_LIMIT:.0%} limit within {ROLLBACK_HOURS}h",
                    "metrics_snapshot": {"trigger": "rollback", "drawdown": dd},
                    "auto_promoted": True,
                    "confirmed_by": "auto_rollback",
                }).execute()

            return {
                "status": "rolled_back",
                "demoted": current_champion["cohort_name"],
                "restored": old_champion_name,
                "trigger_drawdown": dd,
            }

    return {"status": "ok", "champion": current_champion["cohort_name"]}


# ---------------------------------------------------------------------------
# Cohort decision accuracy — reads policy_decisions to measure which
# cohort's accept/reject decisions produce the best outcomes.
# ---------------------------------------------------------------------------

def compute_decision_accuracy(
    supabase,
    user_id: str,
    lookback_days: int = 30,
) -> Dict[str, Any]:
    """
    Compare cohort decision quality using realized outcomes from policy_decisions.

    For each cohort, computes:
      - accepted_win_rate: % of accepted trades that were profitable
      - rejection_accuracy: % of rejected trades that would have lost money
      - sample_size: total decisions with realized outcomes

    Returns dict keyed by cohort_id.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()

    try:
        rows = (
            supabase.table("policy_decisions")
            .select("cohort_id, decision, realized_outcome")
            .eq("user_id", user_id)
            .gte("created_at", cutoff)
            .not_.is_("realized_outcome", "null")
            .limit(500)
            .execute()
        ).data or []
    except Exception as e:
        logger.warning(f"compute_decision_accuracy failed: {e}")
        return {}

    if not rows:
        return {}

    stats: Dict[str, Dict[str, int]] = defaultdict(
        lambda: {"accepted_wins": 0, "accepted_losses": 0,
                 "rejected_wins": 0, "rejected_losses": 0}
    )

    for row in rows:
        cid = row.get("cohort_id")
        if not cid:
            continue
        outcome = row.get("realized_outcome") or {}
        pnl = float(outcome.get("pnl_realized", 0))
        if row["decision"] == "accepted":
            if pnl > 0:
                stats[cid]["accepted_wins"] += 1
            else:
                stats[cid]["accepted_losses"] += 1
        else:
            if pnl > 0:
                stats[cid]["rejected_wins"] += 1
            else:
                stats[cid]["rejected_losses"] += 1

    results = {}
    for cid, s in stats.items():
        total_accepted = s["accepted_wins"] + s["accepted_losses"]
        total_rejected = s["rejected_wins"] + s["rejected_losses"]
        results[cid] = {
            "accepted_win_rate": round(s["accepted_wins"] / total_accepted, 3) if total_accepted else None,
            "rejection_accuracy": round(s["rejected_losses"] / total_rejected, 3) if total_rejected else None,
            "sample_size": total_accepted + total_rejected,
        }

    logger.info(f"[DECISION_ACCURACY] user={user_id[:8]} cohorts={len(results)} lookback={lookback_days}d")
    for cid, r in results.items():
        logger.info(
            f"  cohort={cid[:8]} accepted_wr={r['accepted_win_rate']} "
            f"reject_acc={r['rejection_accuracy']} n={r['sample_size']}"
        )

    return results
