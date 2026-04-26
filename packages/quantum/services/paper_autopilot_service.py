"""
Paper Autopilot Service

Provides automated paper trading execution for Phase-3 streak automation.
- Selects and executes top executable suggestions
- Closes positions based on configurable policy
- Respects pause gate and paper-only mode
- Uses deterministic ordering and deduplication

Runtime Environment Variables:
- PAPER_AUTOPILOT_ENABLED: "1" to enable (default: "0")
- PAPER_AUTOPILOT_MAX_TRADES_PER_DAY: Max trades per day (default: "3")
- PAPER_AUTOPILOT_MIN_SCORE: Minimum score threshold (default: "0.0")
- PAPER_AUTOPILOT_CLOSE_POLICY: "close_all" | "min_one" | "ev_rank" (default: "close_all")
- PAPER_AUTOPILOT_MAX_CLOSES_PER_DAY: Max closes per day (default: "99")
"""

import os
import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone, timedelta

from packages.quantum.table_constants import TRADE_SUGGESTIONS_TABLE

logger = logging.getLogger(__name__)


def _get_config() -> Dict[str, Any]:
    """
    Get autopilot configuration from environment variables.
    Read at runtime to allow dynamic configuration.
    """
    return {
        "enabled": os.environ.get("PAPER_AUTOPILOT_ENABLED", "0") == "1",
        "max_trades_per_day": int(os.environ.get("PAPER_AUTOPILOT_MAX_TRADES_PER_DAY", "3")),
        "min_score": float(os.environ.get("PAPER_AUTOPILOT_MIN_SCORE", "0.0")),
        "close_policy": os.environ.get("PAPER_AUTOPILOT_CLOSE_POLICY", "close_all"),
        "max_closes_per_day": int(os.environ.get("PAPER_AUTOPILOT_MAX_CLOSES_PER_DAY", "99")),
    }


def _compute_today_window() -> Tuple[str, str]:
    """
    Compute UTC today window bounds for deterministic queries.
    Returns (today_start_iso, tomorrow_start_iso).
    """
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_start = today_start + timedelta(days=1)
    return today_start.isoformat(), tomorrow_start.isoformat()


def _get_utc_date_key() -> str:
    """Get UTC date string for idempotency keys."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class PaperAutopilotService:
    """
    Service for automated paper trading.

    Provides methods for:
    - Selecting executable suggestions
    - Executing top suggestions deterministically
    - Closing positions with configurable policy
    """

    def __init__(self, supabase_client):
        self.client = supabase_client
        self.config = _get_config()

    def is_enabled(self) -> bool:
        """Check if autopilot is enabled via environment."""
        return self.config["enabled"]

    def get_executable_suggestions(
        self,
        user_id: str,
        include_backlog: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Fetch executable (pending) suggestions for a user.

        When CANONICAL_RANKING_ENABLED: recomputes risk_adjusted_ev with
        live position context so ranking reflects current portfolio state.
        Returns list sorted deterministically by (risk_adjusted_ev desc,
        created_at asc, id asc).
        """
        today_start, tomorrow_start = _compute_today_window()

        query = self.client.table(TRADE_SUGGESTIONS_TABLE) \
            .select("*") \
            .eq("user_id", user_id) \
            .eq("status", "pending")

        if not include_backlog:
            query = query \
                .gte("created_at", today_start) \
                .lt("created_at", tomorrow_start)

        result = query.execute()
        suggestions = result.data or []

        # Live recomputation of risk_adjusted_ev with current positions
        from packages.quantum.analytics.canonical_ranker import (
            CANONICAL_RANKING_ENABLED,
            compute_risk_adjusted_ev,
        )
        if CANONICAL_RANKING_ENABLED and suggestions:
            positions = self.get_open_positions(user_id)
            budget = self._get_portfolio_budget(user_id)
            for s in suggestions:
                s["risk_adjusted_ev"] = round(
                    compute_risk_adjusted_ev(s, positions, budget), 6
                )

        # Deterministic sorting: risk_adjusted_ev desc, created_at asc, id asc
        def sort_key(s):
            score = s.get("risk_adjusted_ev")
            if score is None:
                score = s.get("ev") or 0.0
            try:
                score = float(score)
            except (TypeError, ValueError):
                score = 0.0
            created = s.get("created_at") or ""
            sid = s.get("id") or ""
            return (-score, created, sid)

        suggestions.sort(key=sort_key)
        return suggestions

    def get_already_executed_suggestion_ids_today(self, user_id: str) -> set:
        """
        Get suggestion IDs that already have paper orders staged/executed today.
        Used for deduplication to prevent double-execution.
        """
        today_start, tomorrow_start = _compute_today_window()

        # Query paper_orders for today's active orders linked to suggestions.
        # Cancelled orders are excluded so their suggestions can be retried.
        result = self.client.table("paper_orders") \
            .select("suggestion_id") \
            .in_("status", ["staged", "working", "partial", "submitted", "filled"]) \
            .gte("created_at", today_start) \
            .lt("created_at", tomorrow_start) \
            .execute()

        orders = result.data or []
        return {o["suggestion_id"] for o in orders if o.get("suggestion_id")}

    def execute_top_suggestions(
        self,
        user_id: str,
        limit: Optional[int] = None,
        min_score: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Execute top N executable suggestions for a user.

        Args:
            user_id: Target user
            limit: Max suggestions to execute (default from config)
            min_score: Minimum score threshold (default from config)

        Returns:
            Summary dict with executed_count, skipped_count, errors, etc.
        """
        # Ops control: check if trading is paused
        try:
            from packages.quantum.ops_endpoints import is_trading_paused
            paused, reason = is_trading_paused()
            if paused:
                logger.info(f"paper_auto_execute_paused: reason={reason}")
                return {"status": "paused", "reason": reason, "executed_count": 0}
        except Exception:
            pass  # If ops_control unavailable, continue (fail-open)

        # Staleness gate: block new entries if market data is stale
        try:
            from packages.quantum.risk.staleness_gate import check_staleness_gate
            stale = check_staleness_gate()
            if stale.blocked:
                return {
                    "status": "blocked",
                    "reason": f"staleness_gate: {stale.reason}",
                    "age_seconds": stale.age_seconds,
                    "stale_symbols": stale.stale_symbols,
                    "executed_count": 0,
                }
        except Exception as sg_err:
            logger.warning(f"[STALENESS_GATE] Check failed (non-fatal): {sg_err}")

        # Circuit breaker: block new entries if risk envelope is breached
        try:
            from packages.quantum.risk.risk_envelope import check_all_envelopes, EnvelopeConfig
            cb_positions = self._get_open_positions_for_risk_check(user_id)
            cb_equity = (
                self._estimate_equity(user_id, cb_positions)
                if cb_positions else None
            )
            if cb_positions and cb_equity is None:
                # Alpaca unavailable — skip the circuit-breaker check
                # rather than fabricating a denominator. The autopilot
                # run continues; intraday_risk_monitor (15-min cadence)
                # is the authoritative guard and uses the same Alpaca-
                # authoritative equity source.
                logger.warning(
                    f"[CIRCUIT_BREAKER] Alpaca equity unavailable for "
                    f"user={user_id[:8]} — skipping envelope check this "
                    f"autopilot run. Entry-gate not enforced this cycle."
                )
            elif cb_positions:
                cb_daily_pnl = sum(float(p.get("unrealized_pl") or 0) for p in cb_positions)
                cb_config = EnvelopeConfig.from_env()
                cb_result = check_all_envelopes(
                    positions=cb_positions,
                    equity=cb_equity,
                    daily_pnl=cb_daily_pnl,
                    config=cb_config,
                )
                if not cb_result.passed:
                    logger.critical(
                        f"[CIRCUIT_BREAKER] Blocking new entries: "
                        f"{len(cb_result.violations)} envelope violations, "
                        f"sizing_mult={cb_result.sizing_multiplier:.2f}, "
                        f"force_close_ids={cb_result.force_close_ids}"
                    )
                    return {
                        "status": "blocked",
                        "reason": "risk_envelope_breach",
                        "violations": len(cb_result.violations),
                        "force_close_ids": cb_result.force_close_ids,
                        "executed_count": 0,
                    }
        except Exception as cb_err:
            logger.warning(f"[CIRCUIT_BREAKER] Check failed (non-fatal): {cb_err}")

        # Policy Lab: execute per-cohort with cohort-specific filtering
        from packages.quantum.policy_lab.config import is_policy_lab_enabled
        if is_policy_lab_enabled():
            return self._execute_per_cohort(user_id)

        limit = limit or self.config["max_trades_per_day"]
        min_score = min_score if min_score is not None else self.config["min_score"]

        # Sweep FIRST: retry all working/partial orders from prior runs,
        # regardless of whether there are new suggestions to stage.
        from packages.quantum.paper_endpoints import (
            _suggestion_to_ticket,
            _stage_order_internal,
            _process_orders_for_user,
            get_supabase,
            get_analytics_service,
        )
        supabase = self.client
        analytics = get_analytics_service()

        sweep_processed = 0
        from packages.quantum.brokers.execution_router import get_execution_mode as _get_exec_mode, ExecutionMode as _EM
        try:
            if _get_exec_mode() == _EM.INTERNAL_PAPER:
                sweep_result = _process_orders_for_user(supabase, analytics, user_id)
            else:
                sweep_result = {"processed": 0}
            sweep_processed = sweep_result.get("processed", 0)
            if sweep_processed > 0:
                logger.info(
                    f"paper_auto_execute_sweep: user_id={user_id} "
                    f"sweep_processed={sweep_processed} "
                    f"total_orders={sweep_result.get('total_orders', 0)}"
                )
            sweep_errors = sweep_result.get("errors") or []
            if sweep_errors:
                logger.warning(
                    f"paper_auto_execute_sweep_errors: user_id={user_id} "
                    f"errors={sweep_errors}"
                )
        except Exception as sweep_err:
            logger.warning(f"paper_auto_execute_sweep_error: user_id={user_id} error={sweep_err}")

        # Get executable suggestions
        suggestions = self.get_executable_suggestions(user_id, include_backlog=False)

        if not suggestions:
            return {
                "status": "ok",
                "executed_count": 0,
                "skipped_count": 0,
                "reason": "no_candidates",
                "processed_summary": {
                    "total_processed": sweep_processed,
                    "sweep_processed": sweep_processed,
                },
            }

        # Get already executed to dedupe
        already_executed = self.get_already_executed_suggestion_ids_today(user_id)

        # Symbol-level dedup: reject suggestions for symbols with open positions
        open_positions = self.get_open_positions(user_id)
        held_symbols = {
            p.get("symbol") for p in open_positions if p.get("symbol")
        }

        # Min-edge filter: reject suggestions where fees eat the profit
        from packages.quantum.analytics.canonical_ranker import MIN_EDGE_AFTER_COSTS
        edge_filtered_count = 0
        fee_per_contract = 0.65
        symbol_dedup_count = 0

        # Filter by min_score, min_edge, and dedupe
        candidates = []
        deduped_count = 0
        below_min_score_count = 0
        for s in suggestions:
            sid = s.get("id")
            if sid in already_executed:
                deduped_count += 1
                continue

            # Block entries for symbols already held
            ticker = s.get("ticker") or s.get("symbol")
            if ticker and ticker in held_symbols:
                symbol_dedup_count += 1
                logger.info(
                    f"[DEDUP] Rejected {ticker}: already have open position"
                )
                continue

            # Min-edge check (catches legacy suggestions without risk_adjusted_ev)
            sizing = s.get("sizing_metadata") or {}
            contracts = int(sizing.get("contracts") or 1)
            fees = fee_per_contract * contracts * 2
            slippage = float(sizing.get("expected_slippage") or 0)
            net_edge = float(s.get("ev") or 0) - fees - slippage
            if net_edge < MIN_EDGE_AFTER_COSTS:
                edge_filtered_count += 1
                logger.info(
                    f"[FILTER] Rejected {s.get('ticker')}: "
                    f"net_edge=${net_edge:.2f} < ${MIN_EDGE_AFTER_COSTS:.0f}"
                )
                continue

            score = s.get("risk_adjusted_ev")
            if score is None:
                score = s.get("ev") or 0.0
            try:
                score = float(score)
            except (TypeError, ValueError):
                score = 0.0

            if score >= min_score:
                candidates.append(s)
            else:
                below_min_score_count += 1

        if not candidates:
            return {
                "status": "ok",
                "executed_count": 0,
                "skipped_count": len(suggestions),
                "reason": "no_qualifying_candidates",
                "processed_summary": {
                    "total_processed": sweep_processed,
                    "sweep_processed": sweep_processed,
                },
            }

        # Take top N
        to_execute = candidates[:limit]

        logger.info(
            f"paper_auto_execute_start: user_id={user_id} "
            f"suggestions_fetched={len(suggestions)} deduped={deduped_count} "
            f"symbol_dedup={symbol_dedup_count} "
            f"below_min_score={below_min_score_count} edge_filtered={edge_filtered_count} "
            f"candidates={len(candidates)} "
            f"to_execute={len(to_execute)}"
        )

        executed = []
        errors = []

        for suggestion in to_execute:
            sid = suggestion.get("id")
            ticker = suggestion.get("ticker", "unknown")
            logger.info(f"paper_auto_execute_processing: suggestion_id={sid} symbol={ticker}")
            try:
                # Convert to ticket
                ticket = _suggestion_to_ticket(suggestion)

                # Use champion cohort portfolio if available, else default
                champion_portfolio = self._get_champion_portfolio(user_id)

                # Stage order
                order_id = _stage_order_internal(
                    supabase,
                    analytics,
                    user_id,
                    ticket,
                    portfolio_id_arg=champion_portfolio,
                    suggestion_id_override=sid
                )

                # Update suggestion status (non-fatal: proceed even if this fails)
                try:
                    supabase.table(TRADE_SUGGESTIONS_TABLE).update({
                        "status": "staged"
                    }).eq("id", sid).execute()
                except Exception as status_err:
                    logger.warning(
                        f"Failed to update suggestion {sid} status to 'staged', "
                        f"proceeding with order processing: {status_err}"
                    )

                # Process order via internal fill ONLY for internal_paper mode.
                # For Alpaca modes, alpaca_order_sync handles fills.
                from packages.quantum.brokers.execution_router import get_execution_mode, ExecutionMode
                _exec_mode = get_execution_mode()
                if _exec_mode == ExecutionMode.INTERNAL_PAPER:
                    process_result = _process_orders_for_user(supabase, analytics, user_id, target_order_id=order_id)
                else:
                    process_result = {"processed": 0, "note": "alpaca_routed"}

                logger.info(
                    f"paper_auto_execute_order_created: suggestion_id={sid} "
                    f"order_id={order_id} symbol={ticker} mode={_exec_mode.value}"
                )

                executed.append({
                    "suggestion_id": sid,
                    "order_id": order_id,
                    "processed": process_result.get("processed", 0),
                    "processing_errors": process_result.get("errors") or None,
                })

            except Exception as e:
                logger.error(
                    f"paper_auto_execute_error: suggestion_id={sid} "
                    f"symbol={ticker} error={e}"
                )
                errors.append({"suggestion_id": sid, "error": str(e)})

        logger.info(
            f"paper_auto_execute_summary: user_id={user_id} "
            f"orders_created={len(executed)} skipped={len(suggestions) - len(to_execute)} "
            f"errors={len(errors)} sweep_processed={sweep_processed}"
        )

        # Compute processing summary: count orders that had processing errors
        processing_error_count = sum(
            1 for e in executed if e.get("processing_errors")
        )
        total_processed = sum(e.get("processed", 0) for e in executed) + sweep_processed

        # Status: "partial" if staging or processing errors, else "ok"
        has_staging_errors = len(errors) > 0
        has_processing_errors = processing_error_count > 0
        if has_staging_errors or has_processing_errors:
            status = "partial"
        elif executed:
            status = "ok"
        else:
            status = "ok"

        return {
            "status": status,
            "executed_count": len(executed),
            "skipped_count": len(suggestions) - len(to_execute),
            "error_count": len(errors),
            "executed": executed,
            "errors": errors if errors else None,
            "processed_summary": {
                "total_processed": total_processed,
                "processing_error_count": processing_error_count,
                "sweep_processed": sweep_processed,
            },
        }

    def _execute_per_cohort(self, user_id: str) -> Dict[str, Any]:
        """
        Policy Lab path: execute suggestions grouped by cohort.

        Each cohort's suggestions (tagged with cohort_name) are executed
        against the cohort's portfolio using the cohort's PolicyConfig
        for filtering limits.
        """
        from packages.quantum.policy_lab.config import load_cohort_configs
        from packages.quantum.policy_lab.fork import _get_cohort_portfolios
        from packages.quantum.paper_endpoints import (
            _suggestion_to_ticket,
            _stage_order_internal,
            _process_orders_for_user,
            get_analytics_service,
        )

        supabase = self.client
        analytics = get_analytics_service()
        configs = load_cohort_configs(user_id, supabase)
        portfolios = _get_cohort_portfolios(user_id, supabase)

        today_str = datetime.now(timezone.utc).date().isoformat()
        all_executed = []
        all_errors = []
        total_processed = 0

        # Debug: also query ALL pending suggestions regardless of cohort to see what exists
        all_pending_res = supabase.table(TRADE_SUGGESTIONS_TABLE) \
            .select("id, ticker, cohort_name, cycle_date, status, ev") \
            .eq("user_id", user_id) \
            .eq("status", "pending") \
            .execute()
        all_pending = all_pending_res.data or []
        print(
            f"[AUTO_EXEC] All pending suggestions: {len(all_pending)} total, "
            f"cycle_dates={set(s.get('cycle_date') for s in all_pending)}, "
            f"cohorts={set(s.get('cohort_name') for s in all_pending)}, "
            f"today_str={today_str}",
            flush=True,
        )
        for s in all_pending[:10]:
            print(
                f"[AUTO_EXEC]   id={s['id'][:8]} ticker={s.get('ticker')} "
                f"cohort={s.get('cohort_name')} cycle_date={s.get('cycle_date')} "
                f"ev={s.get('ev')}",
                flush=True,
            )

        print(
            f"[AUTO_EXEC] Cohort configs: {list(configs.keys())}, "
            f"portfolios: {list(portfolios.keys())}",
            flush=True,
        )

        for cohort_name, config in configs.items():
            portfolio_id = portfolios.get(cohort_name)
            if not portfolio_id:
                print(f"[AUTO_EXEC] SKIP cohort={cohort_name}: no portfolio", flush=True)
                continue

            # Fetch this cohort's pending suggestions
            res = supabase.table(TRADE_SUGGESTIONS_TABLE) \
                .select("*") \
                .eq("user_id", user_id) \
                .eq("cohort_name", cohort_name) \
                .eq("status", "pending") \
                .eq("cycle_date", today_str) \
                .order("risk_adjusted_ev", desc=True) \
                .order("ev", desc=True) \
                .limit(config.max_suggestions_per_day) \
                .execute()
            suggestions = res.data or []

            print(
                f"[AUTO_EXEC] cohort={cohort_name}: query returned {len(suggestions)} "
                f"(filter: cohort_name={cohort_name}, cycle_date={today_str}, status=pending)",
                flush=True,
            )

            # Deduplicate
            already = self.get_already_executed_suggestion_ids_today(user_id)

            # Symbol-level dedup: reject suggestions for symbols with open positions
            cohort_open = self.get_open_positions(user_id)
            cohort_held = {
                p.get("symbol") for p in cohort_open if p.get("symbol")
            }

            for s in suggestions:
                sid = s.get("id")
                if sid in already:
                    print(f"[AUTO_EXEC] SKIP {s.get('ticker')}/{sid[:8]}: already executed today", flush=True)
                    continue
                ticker = s.get("ticker") or s.get("symbol") or "?"
                if ticker in cohort_held:
                    print(f"[AUTO_EXEC] SKIP {ticker}/{sid[:8]}: already have open position", flush=True)
                    continue
                print(f"[AUTO_EXEC] EXECUTING {ticker}/{sid[:8]} cohort={cohort_name}", flush=True)
                try:
                    ticket = _suggestion_to_ticket(s)
                    order_id = _stage_order_internal(
                        supabase, analytics, user_id, ticket,
                        portfolio_id_arg=portfolio_id,
                        suggestion_id_override=sid,
                    )
                    if not order_id:
                        continue

                    from packages.quantum.brokers.execution_router import get_execution_mode, ExecutionMode
                    _exec_mode = get_execution_mode()
                    if _exec_mode == ExecutionMode.INTERNAL_PAPER:
                        proc = _process_orders_for_user(
                            supabase, analytics, user_id, target_order_id=order_id,
                        )
                    else:
                        proc = {"processed": 0, "note": "alpaca_routed"}
                    all_executed.append({
                        "cohort": cohort_name,
                        "suggestion_id": sid,
                        "order_id": order_id,
                        "processed": proc.get("processed", 0),
                    })
                    total_processed += proc.get("processed", 0)
                except Exception as e:
                    logger.error(f"policy_lab_execute_error: cohort={cohort_name} ticker={ticker} error={e}")
                    all_errors.append({"cohort": cohort_name, "suggestion_id": sid, "error": str(e)})

        # Sweep all working orders across all portfolios (internal_paper only)
        sweep_processed = 0
        try:
            from packages.quantum.brokers.execution_router import get_execution_mode, ExecutionMode
            if get_execution_mode() == ExecutionMode.INTERNAL_PAPER:
                sweep = _process_orders_for_user(supabase, analytics, user_id)
            else:
                sweep = {"processed": 0}
            sweep_processed = sweep.get("processed", 0)
        except Exception as e:
            logger.warning(f"policy_lab_sweep_error: {e}")

        print(
            f"[AUTO_EXEC] SUMMARY: user={user_id[:8]} "
            f"pending_total={len(all_pending)} "
            f"executed={len(all_executed)} errors={len(all_errors)} "
            f"processed={total_processed} sweep={sweep_processed}",
            flush=True,
        )
        logger.info(
            f"policy_lab_execute_summary: user_id={user_id} "
            f"executed={len(all_executed)} errors={len(all_errors)} "
            f"processed={total_processed} sweep={sweep_processed}"
        )

        return {
            "status": "partial" if all_errors else "ok",
            "executed_count": len(all_executed),
            "error_count": len(all_errors),
            "executed": all_executed,
            "errors": all_errors or None,
            "processed_summary": {
                "total_processed": total_processed + sweep_processed,
                "sweep_processed": sweep_processed,
            },
        }

    def get_open_positions(self, user_id: str) -> List[Dict[str, Any]]:
        """
        Get open paper positions for a user.

        Positions are sorted deterministically by (opened_at asc, id asc)
        for consistent close ordering.
        """
        # First get user's portfolios
        port_res = self.client.table("paper_portfolios") \
            .select("id") \
            .eq("user_id", user_id) \
            .execute()

        portfolios = port_res.data or []
        if not portfolios:
            return []

        portfolio_ids = [p["id"] for p in portfolios]

        # Get open positions only (closed positions are preserved for history)
        pos_res = self.client.table("paper_positions") \
            .select("*") \
            .in_("portfolio_id", portfolio_ids) \
            .eq("status", "open") \
            .execute()

        positions = pos_res.data or []

        # Deterministic sort: created_at asc, id asc (oldest first)
        def sort_key(p):
            created = p.get("created_at") or ""
            pid = p.get("id") or ""
            return (created, pid)

        positions.sort(key=sort_key)
        return positions

    def _get_open_positions_for_risk_check(self, user_id: str) -> List[Dict[str, Any]]:
        """Fetch open positions with fields needed for risk envelope check."""
        try:
            port_res = self.client.table("paper_portfolios") \
                .select("id") \
                .eq("user_id", user_id) \
                .execute()
            portfolio_ids = [p["id"] for p in (port_res.data or [])]
            if not portfolio_ids:
                return []

            pos_res = self.client.table("paper_positions") \
                .select("id, symbol, quantity, unrealized_pl, avg_entry_price, max_credit, nearest_expiry, sector, status") \
                .in_("portfolio_id", portfolio_ids) \
                .eq("status", "open") \
                .execute()
            return pos_res.data or []
        except Exception as e:
            logger.warning(f"[CIRCUIT_BREAKER] Failed to fetch positions: {e}")
            return []

    def _estimate_equity(
        self, user_id: str, positions: List[Dict[str, Any]],
    ) -> Optional[float]:
        """Alpaca-authoritative account equity for risk envelope check.

        Returns None when Alpaca is unavailable; callers MUST skip the
        envelope check rather than fabricate a denominator. Using a
        notional-sum fallback (prior behavior) produced absurdly tight
        envelope limits on small paper portfolios — the mechanism behind
        the 2026-04-16 false force-close incident that 83872db originally
        addressed for intraday_risk_monitor. PR #780 extracted the
        Alpaca-authoritative helpers to a shared module; this is the
        corresponding follow-up for paper_autopilot_service.
        """
        from packages.quantum.services import equity_state
        return equity_state.get_alpaca_equity(user_id, supabase=self.client)

    def _get_champion_portfolio(self, user_id: str) -> Optional[str]:
        """Get portfolio_id of the champion cohort, or None for default."""
        try:
            res = self.client.table("policy_lab_cohorts") \
                .select("portfolio_id") \
                .eq("user_id", user_id) \
                .eq("is_champion", True) \
                .eq("is_active", True) \
                .limit(1) \
                .execute()
            if res.data and res.data[0].get("portfolio_id"):
                return res.data[0]["portfolio_id"]
        except Exception:
            pass
        return None

    def _get_portfolio_budget(self, user_id: str) -> float:
        """Get deployable capital (net_liq or cash_balance) for risk-adjusted ranking."""
        try:
            res = self.client.table("paper_portfolios") \
                .select("net_liq, cash_balance") \
                .eq("user_id", user_id) \
                .limit(1) \
                .execute()
            if res.data:
                row = res.data[0]
                return float(row.get("net_liq") or row.get("cash_balance") or 100_000)
        except Exception:
            pass
        return 100_000  # Safe default

    def get_positions_closed_today(self, user_id: str) -> int:
        """
        Count positions closed today (via learning_feedback_loops outcomes).
        Used for deduplication to enforce max_closes_per_day.
        """
        today_start, tomorrow_start = _compute_today_window()

        # Count paper trade outcomes closed today
        result = self.client.table("learning_feedback_loops") \
            .select("id", count="exact") \
            .eq("user_id", user_id) \
            .eq("is_paper", True) \
            .eq("outcome_type", "trade_closed") \
            .gte("created_at", today_start) \
            .lt("created_at", tomorrow_start) \
            .execute()

        return result.count or 0

    @staticmethod
    def _resolve_occ_symbol(position: Dict[str, Any], supabase) -> str:
        """
        Resolve OCC options symbol from position legs or opening order.

        Priority: position.legs → opening order legs → underlying ticker fallback.
        """
        pos_id = position.get("id")
        underlying = position["symbol"]

        # 1. Try position legs (available after Phase 1 / Bug 5 fix)
        pos_legs = position.get("legs") or []
        if pos_legs:
            leg_sym = pos_legs[0].get("symbol", "") if isinstance(pos_legs[0], dict) else ""
            if leg_sym.startswith("O:") or len(leg_sym) > 10:
                return leg_sym

        # 2. Fallback: query opening order's legs
        try:
            open_order = supabase.table("paper_orders") \
                .select("order_json") \
                .eq("position_id", pos_id) \
                .order("created_at", desc=False) \
                .limit(1) \
                .execute()
            if open_order.data:
                legs = open_order.data[0].get("order_json", {}).get("legs", [])
                if legs:
                    leg_sym = legs[0].get("symbol", "")
                    if leg_sym.startswith("O:") or len(leg_sym) > 10:
                        return leg_sym
        except Exception as e:
            logger.warning(f"Failed to resolve OCC symbol for position {pos_id}: {e}")

        logger.warning(
            f"No OCC symbol found for position {pos_id} — "
            f"falling back to underlying ticker {underlying}. "
            f"Quote will be stock NBBO, not options."
        )
        return underlying

    @staticmethod
    def _marginal_ev(position: Dict[str, Any]) -> float:
        """
        Canonical marginal EV for position close ranking.

        Uses risk_adjusted_ev when available (stamped at suggestion
        creation), falls back to unrealized_pl.  Lower = worse position
        = should close first (ascending sort).
        """
        raev = position.get("risk_adjusted_ev")
        if raev is not None:
            return float(raev)
        return float(position.get("unrealized_pl") or 0.0)

    def _select_positions_to_close(
        self,
        positions: List[Dict[str, Any]],
        remaining_quota: int,
        policy: str,
    ) -> List[Dict[str, Any]]:
        """
        Select and rank positions for closing based on policy.

        Policies:
        - "close_all": Close all open positions (ignores quota)
        - "ev_rank": Close worst risk-adjusted EV first, up to quota

        The legacy "min_one" policy (forced close regardless of exit
        conditions) has been removed — positions should only close
        when exit conditions trigger.
        """
        if policy == "close_all":
            return positions

        if policy == "ev_rank":
            ranked = sorted(positions, key=self._marginal_ev)
            return ranked[:remaining_quota]

        # Default: ev_rank (min_one removed)
        ranked = sorted(positions, key=self._marginal_ev)
        return ranked[:remaining_quota]

    def close_positions(
        self,
        user_id: str,
        max_to_close: Optional[int] = None,
        policy: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Close paper positions according to policy.

        Args:
            user_id: Target user
            max_to_close: Maximum positions to close (default from config)
            policy: Close policy - "close_all" | "ev_rank"

        Returns:
            Summary dict with closed_count, skipped_reason, etc.
        """
        max_to_close = max_to_close or self.config["max_closes_per_day"]
        policy = policy or self.config["close_policy"]

        # Check how many already closed today (skip for close_all policy)
        already_closed = self.get_positions_closed_today(user_id)

        if policy != "close_all" and already_closed >= max_to_close:
            return {
                "status": "ok",
                "closed_count": 0,
                "reason": "max_closes_reached",
                "already_closed_today": already_closed,
            }

        remaining_quota = max_to_close - already_closed

        # Get open positions
        positions = self.get_open_positions(user_id)

        if not positions:
            return {
                "status": "ok",
                "closed_count": 0,
                "reason": "no_positions",
            }

        # Select positions to close based on policy
        to_close = self._select_positions_to_close(positions, remaining_quota, policy)

        logger.info(
            f"paper_auto_close_selection: user_id={user_id} policy={policy} "
            f"open_positions={len(positions)} to_close={len(to_close)} "
            f"already_closed_today={already_closed}"
        )

        # Close using internal logic
        from packages.quantum.paper_endpoints import (
            _stage_order_internal,
            _process_orders_for_user,
            get_analytics_service,
        )
        from packages.quantum.models import TradeTicket

        supabase = self.client
        analytics = get_analytics_service()

        # PDT guard: check day-trade budget before closing same-day positions
        from packages.quantum.services.pdt_guard_service import (
            is_pdt_enabled, get_pdt_status, is_same_day_close,
        )
        pdt_on = is_pdt_enabled()
        remaining_day_trades = 999
        if pdt_on:
            pdt_status = get_pdt_status(supabase, user_id)
            remaining_day_trades = pdt_status["day_trades_remaining"]
            logger.info(
                f"paper_auto_close_pdt: user_id={user_id} "
                f"day_trades_remaining={remaining_day_trades}"
            )

        closed = []
        errors = []
        pdt_blocked = 0

        for position in to_close:
            pos_id = position.get("id")
            try:
                # PDT check: skip same-day closes if day-trade limit reached
                if pdt_on and remaining_day_trades <= 0:
                    if is_same_day_close(position):
                        pdt_blocked += 1
                        logger.info(
                            f"paper_auto_close_pdt_blocked: pos={pos_id} "
                            f"symbol={position.get('symbol')} — holding overnight"
                        )
                        continue

                # Resolve OCC symbol from position legs or opening order
                occ_symbol = self._resolve_occ_symbol(position, supabase)

                # Build closing ticket
                qty = float(position["quantity"])
                side = "sell" if qty > 0 else "buy"

                ticket = TradeTicket(
                    symbol=position["symbol"],
                    quantity=abs(qty),
                    order_type="market",
                    strategy_type=position.get("strategy_key", "").split("_")[-1] if position.get("strategy_key") else "custom",
                    source_engine="paper_autopilot",
                    legs=[
                        {"symbol": occ_symbol, "action": side, "quantity": abs(qty)}
                    ]
                )

                # Set source_ref_id if available
                if position.get("suggestion_id"):
                    ticket.source_ref_id = position.get("suggestion_id")

                # Stage closing order
                order_id = _stage_order_internal(
                    supabase,
                    analytics,
                    user_id,
                    ticket,
                    position["portfolio_id"],
                    position_id=pos_id,
                    trace_id_override=position.get("trace_id")
                )

                # Process order via internal fill ONLY for internal_paper mode.
                from packages.quantum.brokers.execution_router import get_execution_mode, ExecutionMode
                _exec_mode = get_execution_mode()
                if _exec_mode == ExecutionMode.INTERNAL_PAPER:
                    process_result = _process_orders_for_user(supabase, analytics, user_id, target_order_id=order_id)
                else:
                    process_result = {"processed": 0, "note": "alpaca_routed"}

                closed.append({
                    "position_id": pos_id,
                    "order_id": order_id,
                    "processed": process_result.get("processed", 0),
                    "processing_errors": process_result.get("errors") or None,
                })

                # Decrement day-trade budget for same-day closes
                if pdt_on and is_same_day_close(position):
                    remaining_day_trades -= 1

            except Exception as e:
                logger.error(f"Failed to close position {pos_id}: {e}")
                errors.append({"position_id": pos_id, "error": str(e)})

        # Compute processing summary
        processing_error_count = sum(
            1 for c in closed if c.get("processing_errors")
        )
        total_processed = sum(c.get("processed", 0) for c in closed)

        # Status: "partial" if staging or processing errors
        has_staging_errors = len(errors) > 0
        has_processing_errors = processing_error_count > 0
        if has_staging_errors or has_processing_errors:
            status = "partial"
        elif closed:
            status = "ok"
        else:
            status = "ok"

        return {
            "status": status,
            "closed_count": len(closed),
            "error_count": len(errors),
            "pdt_blocked": pdt_blocked,
            "closed": closed,
            "errors": errors if errors else None,
            "processed_summary": {
                "total_processed": total_processed,
                "processing_error_count": processing_error_count,
            },
        }
