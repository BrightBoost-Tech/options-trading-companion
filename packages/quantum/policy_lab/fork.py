"""
Pipeline fork — creates cohort-specific suggestions from the shared opportunity set.

After the workflow orchestrator generates scored suggestions for the default
cohort, this module clones them for each additional Policy Lab cohort with
adjusted sizing and filtering per PolicyConfig.
"""

import logging
import math
from datetime import datetime, timezone, date
from typing import Dict, List, Optional, Any

from packages.quantum.policy_lab.config import (
    PolicyConfig,
    load_cohort_configs,
    is_policy_lab_enabled,
)

logger = logging.getLogger(__name__)


def fork_suggestions_for_cohorts(
    user_id: str,
    supabase,
    source_window: str = "midday_entry",
) -> Dict[str, Any]:
    """
    After the orchestrator inserts suggestions for the default cohort,
    create cohort-specific variants for each additional Policy Lab cohort.

    The default cohort's suggestions (cohort_name IS NULL) serve as the
    source. For each other active cohort, we clone qualifying suggestions
    with adjusted quantity and tag them with cohort_name.

    Returns summary of what was created.
    """
    if not is_policy_lab_enabled():
        return {"status": "disabled"}

    configs = load_cohort_configs(user_id, supabase)
    if not configs:
        return {"status": "no_cohorts"}

    # Fetch today's untagged suggestions (the default cohort's output)
    today_str = date.today().isoformat()
    source_res = supabase.table("trade_suggestions") \
        .select("*") \
        .eq("user_id", user_id) \
        .eq("window", source_window) \
        .eq("cycle_date", today_str) \
        .is_("cohort_name", "null") \
        .in_("status", ["pending", "staged"]) \
        .order("risk_adjusted_ev", desc=True) \
        .order("ev", desc=True) \
        .execute()

    source_suggestions = source_res.data or []
    if not source_suggestions:
        logger.info(f"policy_lab_fork: no source suggestions for user={user_id}")
        return {"status": "no_source_suggestions", "created": {}}

    # Tag source suggestions as the aggressive cohort (default)
    for s in source_suggestions:
        try:
            supabase.table("trade_suggestions").update({
                "cohort_name": "aggressive",
            }).eq("id", s["id"]).execute()
        except Exception:
            pass  # Non-critical

    # Get cohort portfolio mapping and cohort IDs
    cohort_portfolios = _get_cohort_portfolios(user_id, supabase)
    cohort_ids = _get_cohort_ids(user_id, supabase)

    created = {}
    for cohort_name, config in configs.items():
        if cohort_name == "aggressive":
            created[cohort_name] = len(source_suggestions)
            continue  # Already tagged above

        portfolio_id = cohort_portfolios.get(cohort_name)
        cohort_id = cohort_ids.get(cohort_name)
        if not portfolio_id:
            logger.warning(f"policy_lab_fork: no portfolio for cohort={cohort_name}")
            continue

        # Get cohort's current portfolio for capital-aware sizing
        port_res = supabase.table("paper_portfolios") \
            .select("cash_balance, net_liq") \
            .eq("id", portfolio_id) \
            .single() \
            .execute()
        portfolio = port_res.data or {}
        deployable = float(portfolio.get("net_liq") or portfolio.get("cash_balance") or 100000)

        # Count existing open positions for this cohort's portfolio
        open_pos_res = supabase.table("paper_positions") \
            .select("id", count="exact") \
            .eq("portfolio_id", portfolio_id) \
            .eq("status", "open") \
            .execute()
        open_count = open_pos_res.count or 0

        # Filter source suggestions by cohort policy
        filtered = _filter_for_cohort(source_suggestions, config, open_count)
        filtered_ids = {s["id"] for s in filtered}

        # Decision logging: log every (cohort, suggestion) decision
        _log_cohort_decisions(
            supabase, user_id, cohort_name, cohort_id,
            source_suggestions, filtered_ids, config, open_count,
        )

        # Clone with adjusted sizing
        cloned = 0
        for s in filtered:
            try:
                clone = _clone_suggestion_for_cohort(
                    s, cohort_name, config, deployable,
                )
                if clone:
                    supabase.table("trade_suggestions").insert(clone).execute()
                    cloned += 1
            except Exception as e:
                logger.warning(
                    f"policy_lab_fork_clone_error: cohort={cohort_name} "
                    f"ticker={s.get('ticker')} error={e}"
                )

        created[cohort_name] = cloned
        logger.info(
            f"policy_lab_fork: cohort={cohort_name} "
            f"source={len(source_suggestions)} filtered={len(filtered)} cloned={cloned}"
        )

    # Log decisions for the aggressive cohort too (all accepted by default)
    aggressive_cohort_id = cohort_ids.get("aggressive")
    if aggressive_cohort_id and source_suggestions:
        all_ids = {s["id"] for s in source_suggestions}
        _log_cohort_decisions(
            supabase, user_id, "aggressive", aggressive_cohort_id,
            source_suggestions, all_ids,
            configs.get("aggressive", PolicyConfig()),
            0,  # aggressive doesn't filter by open positions at fork time
        )

    return {"status": "ok", "created": created}


def _filter_for_cohort(
    suggestions: List[Dict],
    config: PolicyConfig,
    open_positions: int,
) -> List[Dict]:
    """Filter source suggestions by cohort's PolicyConfig."""
    available_slots = max(0, config.max_positions_open - open_positions)
    max_new = min(config.max_suggestions_per_day, available_slots)

    filtered = []
    for s in suggestions:
        if len(filtered) >= max_new:
            break
        # Use risk_adjusted_ev when available, fall back to ev
        rank_value = s.get("risk_adjusted_ev")
        if rank_value is None:
            rank_value = float(s.get("ev") or 0)
        else:
            rank_value = float(rank_value)
        if rank_value < config.min_score_threshold:
            continue
        filtered.append(s)

    return filtered


def _clone_suggestion_for_cohort(
    source: Dict,
    cohort_name: str,
    config: PolicyConfig,
    deployable_capital: float,
) -> Optional[Dict]:
    """
    Clone a suggestion with cohort-specific sizing.

    Adjusts contract quantity based on cohort's risk parameters while
    preserving the original suggestion's legs, strategy, and scores.
    """
    order_json = source.get("order_json") or {}
    sizing_meta = source.get("sizing_metadata") or {}

    original_contracts = int(order_json.get("contracts") or 1)
    max_loss = float(sizing_meta.get("max_loss_total") or 0)
    max_loss_per = max_loss / max(original_contracts, 1)

    # Compute cohort-specific contract count
    if max_loss_per > 0:
        budget = deployable_capital * config.budget_cap_pct
        max_risk = deployable_capital * config.max_risk_pct_per_trade * config.risk_multiplier
        effective_risk = min(budget, max_risk)
        contracts = max(1, int(math.floor(effective_risk / max_loss_per)))
    else:
        # Fallback: scale proportionally from aggressive defaults
        scale = config.max_risk_pct_per_trade / 0.05
        contracts = max(1, int(round(original_contracts * scale)))

    # Build cloned order_json with new quantity
    cloned_order = {**order_json, "contracts": contracts}

    # Build cloned sizing_metadata
    cloned_sizing = {
        **sizing_meta,
        "contracts": contracts,
        "cohort_name": cohort_name,
        "original_contracts": original_contracts,
        "policy_max_risk_pct": config.max_risk_pct_per_trade,
    }

    now_iso = datetime.now(timezone.utc).isoformat()

    # Use unique fingerprint to avoid unique constraint violation
    source_fp = source.get("legs_fingerprint") or ""
    cohort_fp = f"{source_fp}_{cohort_name}" if source_fp else cohort_name

    return {
        "user_id": source["user_id"],
        "window": source.get("window"),
        "ticker": source.get("ticker"),
        "symbol": source.get("symbol"),
        "strategy": source.get("strategy"),
        "direction": source.get("direction"),
        "status": "pending",
        "ev": source.get("ev"),
        "risk_adjusted_ev": source.get("risk_adjusted_ev"),
        "order_json": cloned_order,
        "sizing_metadata": cloned_sizing,
        "cohort_name": cohort_name,
        "cycle_date": source.get("cycle_date"),
        "legs_fingerprint": cohort_fp,
        "trace_id": source.get("trace_id"),
        "model_version": source.get("model_version"),
        "features_hash": source.get("features_hash"),
        "regime": source.get("regime"),
        "decision_lineage": source.get("decision_lineage"),
        "lineage_hash": source.get("lineage_hash"),
        "agent_signals": source.get("agent_signals"),
        "agent_summary": source.get("agent_summary"),
        "created_at": now_iso,
    }


def _get_cohort_portfolios(user_id: str, supabase) -> Dict[str, str]:
    """Map cohort_name → portfolio_id from policy_lab_cohorts."""
    try:
        res = supabase.table("policy_lab_cohorts") \
            .select("cohort_name, portfolio_id") \
            .eq("user_id", user_id) \
            .eq("is_active", True) \
            .execute()
        return {r["cohort_name"]: r["portfolio_id"] for r in (res.data or [])}
    except Exception:
        return {}


def _get_cohort_ids(user_id: str, supabase) -> Dict[str, str]:
    """Map cohort_name → cohort id (UUID) from policy_lab_cohorts."""
    try:
        res = supabase.table("policy_lab_cohorts") \
            .select("id, cohort_name") \
            .eq("user_id", user_id) \
            .eq("is_active", True) \
            .execute()
        return {r["cohort_name"]: r["id"] for r in (res.data or [])}
    except Exception:
        return {}


def _build_features_snapshot(suggestion: Dict) -> Dict:
    """Extract a features snapshot from a suggestion for decision logging."""
    return {
        "ev": suggestion.get("ev"),
        "probability_of_profit": suggestion.get("probability_of_profit"),
        "regime": suggestion.get("regime"),
        "model_version": suggestion.get("model_version"),
        "features_hash": suggestion.get("features_hash"),
        "strategy": suggestion.get("strategy"),
        "ticker": suggestion.get("ticker"),
        "window": suggestion.get("window"),
    }


def _build_simulated_fill(suggestion: Dict) -> Dict:
    """Extract simulated fill data from suggestion's TCM estimates."""
    tcm = suggestion.get("tcm") or {}
    order_json = suggestion.get("order_json") or {}
    sizing = suggestion.get("sizing_metadata") or {}
    return {
        "expected_fill_price": tcm.get("expected_fill_price"),
        "expected_slippage": tcm.get("expected_slippage"),
        "spread_width": tcm.get("spread_width"),
        "limit_price": order_json.get("limit_price"),
        "contracts": order_json.get("contracts"),
        "max_loss_total": sizing.get("max_loss_total"),
    }


def _log_cohort_decisions(
    supabase,
    user_id: str,
    cohort_name: str,
    cohort_id: Optional[str],
    all_suggestions: List[Dict],
    accepted_ids: set,
    config: PolicyConfig,
    open_positions: int,
) -> None:
    """
    Log a decision record for every (cohort, suggestion) pair.

    Called once per cohort during fork. Records whether each suggestion
    was accepted or rejected, with reason codes explaining why.
    """
    if not cohort_id:
        logger.debug(f"policy_decision_log_skip: no cohort_id for {cohort_name}")
        return

    available_slots = max(0, config.max_positions_open - open_positions)
    max_new = min(config.max_suggestions_per_day, available_slots)

    rows = []
    accepted_so_far = 0

    for rank, s in enumerate(all_suggestions, start=1):
        sid = s.get("id")
        ev = float(s.get("ev") or 0)

        # Determine decision and reasons
        if sid in accepted_ids:
            decision = "accepted"
            reason_codes = []
            accepted_so_far += 1
        else:
            # Figure out WHY it was rejected
            reason_codes = []
            if ev < config.min_score_threshold:
                reason_codes.append("ev_below_min")
            if accepted_so_far >= max_new:
                if open_positions >= config.max_positions_open:
                    reason_codes.append("max_positions_reached")
                else:
                    reason_codes.append("daily_limit_reached")
            if not reason_codes:
                reason_codes.append("filtered_by_policy")
            decision = "rejected"

        rows.append({
            "cohort_id": cohort_id,
            "suggestion_id": sid,
            "user_id": user_id,
            "decision": decision,
            "rank_at_decision": rank,
            "reason_codes": reason_codes,
            "features_snapshot": _build_features_snapshot(s),
            "simulated_fill": _build_simulated_fill(s),
        })

    if not rows:
        return

    try:
        # Batch upsert — on_conflict handles re-runs on the same day
        supabase.table("policy_decisions").upsert(
            rows, on_conflict="cohort_id,suggestion_id"
        ).execute()
        logger.info(
            f"policy_decision_log: cohort={cohort_name} "
            f"total={len(rows)} accepted={sum(1 for r in rows if r['decision'] == 'accepted')} "
            f"rejected={sum(1 for r in rows if r['decision'] == 'rejected')}"
        )
    except Exception as e:
        logger.error(f"policy_decision_log_error: cohort={cohort_name} error={e}")
