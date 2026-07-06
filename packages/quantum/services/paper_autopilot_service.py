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
from packages.quantum.observability.alerts import alert, _get_admin_supabase

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

        # Deterministic sorting: risk_adjusted_ev desc, created_at asc, id asc.
        # M4 item 0b (2026-07-06): the #1126 viability bias is applied HERE —
        # the audit's F1 finding was that the biased sort lived only in
        # rank_suggestions_canonical, which has zero production callers (the
        # 9a2cef1 class: green tests on an orphan function). This is the
        # executor's real candidacy ordering, so the bias must live here.
        # Sort-KEY only: the stored risk_adjusted_ev is untouched (allocator
        # split-skew reads it); positive scores only; flag-off byte-identical.
        from packages.quantum.analytics.canonical_ranker import (
            _viability_bias_enabled,
            _viability_rank_key,
        )
        bias_on = _viability_bias_enabled()

        def sort_key(s):
            score = s.get("risk_adjusted_ev")
            if score is None:
                score = s.get("ev") or 0.0
            try:
                score = float(score)
            except (TypeError, ValueError):
                score = 0.0
            if bias_on and score > 0:
                score = _viability_rank_key(
                    {"risk_adjusted_ev": score, "ticker": s.get("ticker")}
                )
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

        # Entries-only break-glass halt: a DB-level brake (ops_control.
        # entries_paused) that blocks NEW entries here at the entry seam while
        # LEAVING the intraday risk monitor + exit/close jobs running — those
        # never call this path, so loss-protection keeps running. Independent
        # of the global `paused` gate above. Reads DEFENSIVELY and FAILS OPEN
        # (a spurious entries-halt only parks the day), so a read error never
        # blocks entries on its own and never bypasses the global pause.
        try:
            from packages.quantum.ops_endpoints import are_entries_paused
            entries_paused, entries_reason = are_entries_paused()
            if entries_paused:
                logger.info(f"paper_auto_execute_entries_paused: reason={entries_reason}")
                return {
                    "status": "entries_paused",
                    "reason": entries_reason,
                    "executed_count": 0,
                }
        except Exception:
            pass  # Entries-only brake fails OPEN — never block on its own error

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
            alert(
                _get_admin_supabase(),
                alert_type="paper_autopilot_staleness_gate_failed",
                severity="warning",
                message=f"Staleness gate check failed: {type(sg_err).__name__}",
                user_id=user_id,
                metadata={
                    "function_name": "execute_top_suggestions",
                    "error_class": type(sg_err).__name__,
                    "error_message": str(sg_err)[:500],
                    "consequence": "autopilot proceeds without staleness verification — stale data may drive entries",
                },
            )

        # Circuit breaker: block new entries if risk envelope is breached
        try:
            from packages.quantum.risk.risk_envelope import check_all_envelopes, EnvelopeConfig
            cb_positions = self._get_open_positions_for_risk_check(user_id)
            # v5 phantom-mark-safe entry-halt brake (P2#6 — mirrors the #1071
            # force-close fix). The breaker fires on realized (DB-authoritative,
            # trusted, UN-GATED — preserves the v5-A2/06-11 realized protection,
            # incl. on an EMPTY book) + executable-corroborated unrealized
            # (#1034), NEVER the raw broker equity delta / phantom-marked live
            # equity. On 06-17 a phantom broker unrealized of −285 on an
            # incomplete-leg-quote window read ~−13-15% and would have BLOCKED
            # the day's single execution shot on a MARA whose executable close
            # realized −15. Denominator de-phantomed to last_equity + daily_pnl
            # (the same bad mark also depresses live equity, inflating the %).
            # Fail-SAFE: scope or realized query unavailable → legacy broker-true
            # brake (errs protective). NEVER pass realized=0.0 — that silently
            # drops realized protection.
            from packages.quantum.services import equity_state
            _scope_ok = True
            _live_ids: set = set()
            try:
                from packages.quantum.risk.position_scope import (
                    live_routed_portfolio_ids,
                )
                _live_ids = set(live_routed_portfolio_ids(self.client, user_id))
            except Exception as _scope_err:
                logger.warning(
                    f"[CIRCUIT_BREAKER] user={user_id[:8]}: live-routing scope "
                    f"query failed ({type(_scope_err).__name__}); corroborated "
                    f"brake falls back to the legacy broker-true brake this run"
                )
                _scope_ok = False
            _day_start = datetime.now(timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            realized_today = (
                equity_state.realized_pnl_since(
                    self.client, user_id, _live_ids, _day_start.isoformat()
                )
                if _scope_ok
                else None
            )
            if (not _scope_ok) or realized_today is None:
                # Fail SAFE: scope or realized query unavailable — legacy
                # broker-true brake (errs protective).
                logger.warning(
                    f"[CIRCUIT_BREAKER] user={user_id[:8]}: corroborated brake "
                    f"inputs unavailable (scope_ok={_scope_ok}, "
                    f"realized_today={realized_today}) — legacy broker-true "
                    f"brake this run"
                )
                cb_daily_proxy = sum(
                    float(p.get("unrealized_pl") or 0) for p in cb_positions
                )
                cb_daily_pnl = equity_state.tightened_daily_pnl(
                    user_id, cb_daily_proxy, supabase=self.client,
                )
                cb_equity = self._estimate_equity(user_id, cb_positions)
            else:
                # Executable-corroborated unrealized over the OPEN live book;
                # positions whose executable side can't be priced are EXCLUDED +
                # flagged (H9), never priced off a phantom broker mark. Excluding
                # → less negative → less likely to halt (correct: don't halt the
                # day on a value you can't corroborate; #1048 per-position stops
                # + the force-close monitor are the real-loss backstop).
                corroborated_unreal, _uncorroborated = (
                    equity_state.corroborated_unrealized(cb_positions)
                )
                for _u in _uncorroborated:
                    alert(
                        _get_admin_supabase(),
                        alert_type="daily_brake_unrealized_uncorroborated",
                        severity="warning",
                        message=(
                            f"Entry-halt breaker EXCLUDED {_u.get('symbol')} "
                            f"({str(_u.get('position_id'))[:8]}) unrealized: "
                            f"executable side not corroborated "
                            f"({_u.get('reason')}). Realized + the per-position "
                            f"stop still protect it."
                        ),
                        user_id=user_id,
                        metadata={
                            "function_name": "execute_top_suggestions",
                            "position_id": _u.get("position_id"),
                            "symbol": _u.get("symbol"),
                            "reason": _u.get("reason"),
                            "consequence": (
                                "entry-halt breaker excluded this position's "
                                "unrealized from the daily brake; realized and "
                                "the per-position stop still protect it"
                            ),
                        },
                    )
                cb_daily_pnl = realized_today + corroborated_unreal
                # Clean %-denominator: last_equity + daily P&L, NOT the phantom-
                # marked live broker equity (the same bad mark depresses it,
                # inflating the loss %).
                _last_equity = equity_state.get_alpaca_last_equity(
                    user_id, supabase=self.client,
                )
                cb_equity = (
                    (_last_equity + cb_daily_pnl)
                    if _last_equity is not None
                    else None
                )
            if cb_equity is None:
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
            else:
                # Daily P&L was computed above (corroborated + phantom-safe,
                # or the legacy fail-safe). Weekly: broker-true via
                # get_portfolio_history — previously NOT fed here at all
                # (defaulted 0.0), so a losing week never gated entries. Weekly
                # uses portfolio-history equity, not the per-leg last-trade mark
                # class, so it is left broker-true; the corroborated weekly
                # horizon is the 15-min monitor's job (#1071).
                cb_weekly_pnl = equity_state.get_alpaca_weekly_pnl(
                    user_id, supabase=self.client,
                )
                if cb_weekly_pnl is None:
                    logger.warning(
                        f"[CIRCUIT_BREAKER] Alpaca weekly P&L unavailable for "
                        f"user={user_id[:8]} — weekly envelope skipped this "
                        f"run (daily envelope still enforced)."
                    )
                    cb_weekly_pnl = 0.0
                cb_config = EnvelopeConfig.from_env()
                # #1044 utilization gate: at small tier with the gate
                # EXPLICITLY enabled (strict =1), demote the share-of-book
                # concentration_symbol check BLOCK→WARN — the pro-forma
                # utilization cap (per-candidate STAGE gate in
                # _execute_per_cohort) replaces it as the entry-blocking
                # capital control. Sector/expiry/stress severities and all
                # loss envelopes are untouched. Fail SAFE: OBP unreadable →
                # tier unresolved → no demotion; any error in this check →
                # no demotion (legacy stricter BLOCK retained). Wrapped in
                # its own try/except so a fault here can never trip the
                # outer cb_err handler and disable the whole breaker.
                try:
                    from packages.quantum.risk import utilization_gate as ug
                    ug.echo_flag_state()
                    if ug.is_enabled() and ug.tier_is_small(user_id, supabase=self.client):
                        cb_config.symbol_concentration_severity = "warn"
                        logger.warning(
                            "[UTILIZATION_GATE] small tier + gate enabled — "
                            "concentration_symbol demoted to WARN for this run "
                            "(utilization gate enforces per-candidate at stage time)"
                        )
                except Exception as _ug_err:
                    logger.warning(
                        "[UTILIZATION_GATE] demotion check failed — legacy "
                        "concentration BLOCK retained: %s", _ug_err,
                    )
                cb_result = check_all_envelopes(
                    positions=cb_positions,
                    equity=cb_equity,
                    daily_pnl=cb_daily_pnl,
                    weekly_pnl=cb_weekly_pnl,
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
            # #72-H5b SAFETY-CRITICAL: circuit breaker check failure means
            # risk envelope state could not be verified; autopilot proceeds
            # with entries despite a potential breach (daily/weekly loss
            # caps, per-symbol concentration, etc). Alert fires BEFORE the
            # fall-through so operator awareness precedes unsafe entries.
            alert(
                _get_admin_supabase(),
                alert_type="paper_autopilot_circuit_breaker_failed",
                severity="critical",
                message=f"Risk-envelope circuit breaker check failed: {type(cb_err).__name__}",
                user_id=user_id,
                metadata={
                    "function_name": "execute_top_suggestions",
                    "error_class": type(cb_err).__name__,
                    "error_message": str(cb_err)[:500],
                    "consequence": "Circuit breaker state could not be verified; autopilot proceeds with entries despite potential envelope breach. Risk: entries continue when they should be blocked by daily/weekly loss caps or per-symbol concentration limits.",
                    "operator_action_required": "Pause autopilot manually (set PAPER_AUTOPILOT_ENABLED=0 in Railway env) until risk_alerts and position state are reconciled. Verify daily/weekly P&L state, per-symbol exposure, and any active loss-envelope flags before resuming.",
                },
            )
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
            alert(
                _get_admin_supabase(),
                alert_type="paper_autopilot_pre_sweep_failed",
                severity="warning",
                message=f"Pre-execution order sweep failed: {type(sweep_err).__name__}",
                user_id=user_id,
                metadata={
                    "function_name": "execute_top_suggestions",
                    "error_class": type(sweep_err).__name__,
                    "error_message": str(sweep_err)[:500],
                    "consequence": "stale orders not cleaned up before new entries — possible duplicate order conditions",
                },
            )

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
                self._stamp_blocked_reason(
                    sid, "symbol_already_held",
                    f"open position in {ticker} (user-level dedup)",
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
                self._stamp_blocked_reason(
                    sid, "edge_below_minimum_at_stage",
                    f"net_edge=${net_edge:.2f} < ${MIN_EDGE_AFTER_COSTS:.0f}",
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
                self._stamp_blocked_reason(
                    sid, "below_min_score",
                    f"score={score:.4f} < min_score={min_score:.4f}",
                )

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
        # #72-H5b: aggregation list for per-suggestion failures (status
        # update + full execution share this list).
        _per_suggestion_failures = []

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
                    _per_suggestion_failures.append({
                        "suggestion_id": sid,
                        "ticker": ticker,
                        "stage": "status_staged_update",
                        "error_class": type(status_err).__name__,
                        "error_message": str(status_err)[:200],
                    })

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
                _per_suggestion_failures.append({
                    "suggestion_id": sid,
                    "ticker": ticker,
                    "stage": "full_execution",
                    "error_class": type(e).__name__,
                    "error_message": str(e)[:200],
                })

        # #72-H5b: aggregated alert for per-suggestion failures.
        if _per_suggestion_failures:
            _failed_tickers = list({f["ticker"] for f in _per_suggestion_failures if f.get("ticker")})[:20]
            _distinct_error_classes = sorted({f["error_class"] for f in _per_suggestion_failures})
            _stages = sorted({f["stage"] for f in _per_suggestion_failures})
            alert(
                _get_admin_supabase(),
                alert_type="paper_autopilot_per_suggestion_failed",
                severity="warning",
                message=f"{len(_per_suggestion_failures)} per-suggestion failures during autopilot execution",
                user_id=user_id,
                metadata={
                    "function_name": "execute_top_suggestions",
                    "failed_count": len(_per_suggestion_failures),
                    "failed_tickers": _failed_tickers,
                    "distinct_error_classes": _distinct_error_classes,
                    "stages_affected": _stages,
                    "consequence": f"{len(_per_suggestion_failures)} suggestions did not execute as expected this cycle",
                },
            )

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

    def _stamp_blocked_reason(self, suggestion_id, reason: str, detail: str = "") -> None:
        """Stamp blocked_reason/_detail on a suggestion rejected at stage time.

        Closes the 'swept as stale' observability gap (06-10 A3 diagnostic):
        a #1038-rejected or risk-gated suggestion previously left NO trace on
        its row — status stayed pending, the morning sweep relabeled it
        dismissed, and the real cause lived only in logs/job results.
        Fail-soft: a stamp failure never affects the execution loop.
        """
        try:
            self.client.table(TRADE_SUGGESTIONS_TABLE).update({
                "blocked_reason": reason,
                "blocked_detail": str(detail)[:300],
            }).eq("id", suggestion_id).execute()
        except Exception as e:
            logger.warning(
                f"[STAGE_BLOCK] blocked_reason stamp failed for "
                f"{str(suggestion_id)[:8]}: {e}"
            )

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
            EntryQuoteUnpriceable,
        )

        supabase = self.client
        analytics = get_analytics_service()
        configs = load_cohort_configs(user_id, supabase)
        portfolios = _get_cohort_portfolios(user_id, supabase)

        # #1044 utilization gate — pro-forma total-utilization cap on LIVE-
        # routed entries (shadow books don't consume real OBP). Live scope
        # resolved once per run; if resolution fails, ALL cohorts are gated
        # this run (over-gating a shadow book is cheap; missing the live one
        # isn't — fail closed).
        from packages.quantum.risk import utilization_gate as ug
        _ug_on = ug.is_enabled()
        _ug_live_portfolio_ids = None
        if _ug_on:
            try:
                from packages.quantum.risk.position_scope import live_routed_portfolio_ids
                _ug_live_portfolio_ids = set(live_routed_portfolio_ids(supabase, user_id))
            except Exception as _scope_err:
                logger.warning(
                    "[UTILIZATION_GATE] live-routing scope resolution failed — "
                    "gating ALL cohorts this run (fail-closed): %s", _scope_err,
                )
                _ug_live_portfolio_ids = None  # None → gate every cohort

        today_str = datetime.now(timezone.utc).date().isoformat()
        all_executed = []
        all_errors = []
        total_processed = 0
        # #72-H5b: aggregation list for per-cohort per-suggestion failures
        _cohort_per_suggestion_failures = []

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

            # Re-entry cooldown — FILTER gate (before ranking/staging): drop any
            # suggestion whose (cohort, symbol) is benched by a just-stopped
            # cooldown so it never reaches staging. Best-effort: on a query
            # error this passes through and the authoritative STAGE gate below
            # fails closed. cohort_id resolved from the cohort's portfolio.
            from packages.quantum.services import reentry_cooldown as rc
            _cooldown_on = rc.is_enabled()
            cohort_id = rc.resolve_cohort_id(supabase, portfolio_id) if _cooldown_on else None
            if _cooldown_on and suggestions:
                try:
                    _benched = rc.active_symbols(
                        supabase, cohort_id,
                        [s.get("ticker") or s.get("symbol") for s in suggestions],
                    )
                    if _benched:
                        _before = len(suggestions)
                        suggestions = [
                            s for s in suggestions
                            if (s.get("ticker") or s.get("symbol")) not in _benched
                        ]
                        logger.warning(
                            "[REENTRY_COOLDOWN] filter gate excluded %s for "
                            "cohort=%s (%s→%s suggestions)",
                            sorted(_benched), cohort_id, _before, len(suggestions),
                        )
                except rc.CooldownQueryError as _ce:
                    logger.error(
                        "[REENTRY_COOLDOWN] filter-gate query failed for cohort=%s "
                        "(stage gate will fail-closed): %s", cohort_id, _ce,
                    )

            # Deduplicate
            already = self.get_already_executed_suggestion_ids_today(user_id)

            # Symbol-level dedup SCOPED TO THIS COHORT'S PORTFOLIO: a cohort
            # skips a symbol only if IT already holds it.
            #
            # Bug fix (2026-06-01): cohort_held was previously built from
            # get_open_positions(user_id) — the WHOLE account, every cohort
            # portfolio — so whichever cohort processed a symbol first (e.g. a
            # shadow_only cohort) starved every LATER cohort of that symbol,
            # including the live aggressive champion. (BAC 2026-06-01: the
            # conservative/shadow_only cohort filled BAC internally at 16:30,
            # so the aggressive/live champion's pending BAC was skipped
            # "already have open position" and no live entry was placed.)
            # The variable name + the per-cohort loop show the intent was
            # per-cohort dedup; the user-wide fetch was the defect. Scoping by
            # portfolio_id restores cohort independence. Real per-symbol
            # exposure is still bounded INDEPENDENTLY of this count-based dedup
            # by the capital_allocator per-symbol concentration cap
            # (DEFAULT_MAX_SYMBOL_ALLOC_PCT) and the canonical_ranker
            # concentration penalty — removing the cross-cohort block does not
            # remove a real exposure guard.
            cohort_open = self.get_open_positions(user_id)
            cohort_held = {
                p.get("symbol") for p in cohort_open
                if p.get("symbol") and p.get("portfolio_id") == portfolio_id
            }

            for s in suggestions:
                sid = s.get("id")
                if sid in already:
                    print(f"[AUTO_EXEC] SKIP {s.get('ticker')}/{sid[:8]}: already executed today", flush=True)
                    continue
                ticker = s.get("ticker") or s.get("symbol") or "?"
                if ticker in cohort_held:
                    print(f"[AUTO_EXEC] SKIP {ticker}/{sid[:8]}: already have open position", flush=True)
                    # Cohort forks are separate suggestion rows — stamping this
                    # fork never masks another cohort's pending copy (ledger N2:
                    # the 06-10 NFLX forks were swept unprocessed + unstamped).
                    self._stamp_blocked_reason(
                        sid, "symbol_already_held",
                        f"cohort {cohort_name} already holds {ticker}",
                    )
                    continue
                print(f"[AUTO_EXEC] EXECUTING {ticker}/{sid[:8]} cohort={cohort_name}", flush=True)
                try:
                    # Re-entry cooldown — STAGE gate (authoritative; mirrors
                    # #1038's fresh-at-stage check). Re-query just before
                    # staging to catch the rank→stage gap. Runs BEFORE and
                    # INDEPENDENT of any entry-vs-add discrimination — an
                    # add-to-position on a benched symbol MUST be blocked.
                    # FAIL-CLOSED: a query error skips this stage (a skipped
                    # cycle is cheap; a missed lockout isn't).
                    if _cooldown_on:
                        try:
                            if rc.is_active(supabase, cohort_id, ticker):
                                logger.warning(
                                    "[REENTRY_COOLDOWN] STAGE gate BLOCKED "
                                    "%s/%s cohort=%s — active cooldown",
                                    ticker, sid[:8], cohort_id,
                                )
                                raise rc.SymbolCooldownActive(cohort_id, ticker)
                        except rc.CooldownQueryError as _ce:
                            logger.error(
                                "[REENTRY_COOLDOWN] STAGE gate query failed for "
                                "%s cohort=%s — FAIL-CLOSED, skipping stage: %s",
                                ticker, cohort_id, _ce,
                            )
                            raise rc.SymbolCooldownActive(cohort_id, ticker) from _ce

                    # #1044 utilization gate — STAGE gate (pro-forma): block
                    # THIS entry if (committed + candidate)/(committed + OBP)
                    # exceeds the cap. Fresh broker reads inside (positions +
                    # settled OBP); FAIL-CLOSED on any unreadable input; logs
                    # every evaluation with the numbers and the decision.
                    if _ug_on and (
                        _ug_live_portfolio_ids is None
                        or portfolio_id in _ug_live_portfolio_ids
                    ):
                        ug.evaluate_entry(
                            user_id, ticker, ug.candidate_cost_usd(s),
                            supabase=supabase,
                        )

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
                except rc.SymbolCooldownActive as _ca:
                    # Benched by an active re-entry cooldown (or a fail-closed
                    # query error) — an expected, ENFORCED skip, already logged
                    # loudly at the gate. NOT an execution failure; don't
                    # pollute the failure aggregation.
                    self._stamp_blocked_reason(sid, "symbol_cooldown", str(_ca))
                    continue
                except ug.EntryUtilizationBlocked as _ub:
                    # #1044: pro-forma utilization above the cap — an expected,
                    # ENFORCED block (the evaluation line with the numbers was
                    # already logged inside evaluate_entry). Not a failure.
                    logger.warning(
                        "[UTILIZATION_GATE] STAGE gate BLOCKED %s/%s cohort=%s — %s",
                        ticker, sid[:8], cohort_name, _ub,
                    )
                    self._stamp_blocked_reason(sid, "entry_utilization_blocked", str(_ub))
                    continue
                except ug.UtilizationGateError as _ue:
                    # #1044 FAIL-CLOSED: an input the gate needs could not be
                    # read fresh (OBP / broker positions / threshold /
                    # candidate cost). Block this entry loudly; never fall
                    # back to a DB snapshot or wave it through.
                    logger.error(
                        "[UTILIZATION_GATE] input unreadable for %s/%s "
                        "cohort=%s — FAIL-CLOSED, skipping stage: %s",
                        ticker, sid[:8], cohort_name, _ue,
                    )
                    self._stamp_blocked_reason(sid, "utilization_gate_error", str(_ue))
                    continue
                except EntryQuoteUnpriceable as _eq:
                    # #1038 stage-time rejection — preserve the existing error
                    # accounting (these counted as errors-not-executed before)
                    # AND stamp the row so the cause survives the morning
                    # stale-sweep (06-10: 3 XLE forks rejected, rows left
                    # pending/blocked_reason-null — invisible by the next day).
                    logger.error(
                        f"policy_lab_execute_error: cohort={cohort_name} "
                        f"ticker={ticker} error={_eq}"
                    )
                    all_errors.append({
                        "cohort": cohort_name, "suggestion_id": sid, "error": str(_eq),
                    })
                    _cohort_per_suggestion_failures.append({
                        "cohort_name": cohort_name,
                        "suggestion_id": sid,
                        "ticker": ticker,
                        "error_class": "EntryQuoteUnpriceable",
                        "error_message": str(_eq)[:200],
                    })
                    self._stamp_blocked_reason(sid, "entry_quote_unpriceable", str(_eq))
                    continue
                except Exception as e:
                    logger.error(f"policy_lab_execute_error: cohort={cohort_name} ticker={ticker} error={e}")
                    all_errors.append({"cohort": cohort_name, "suggestion_id": sid, "error": str(e)})
                    _cohort_per_suggestion_failures.append({
                        "cohort_name": cohort_name,
                        "suggestion_id": sid,
                        "ticker": ticker,
                        "error_class": type(e).__name__,
                        "error_message": str(e)[:200],
                    })

        # #72-H5b: aggregated alert for cohort per-suggestion failures
        if _cohort_per_suggestion_failures:
            _failed_tickers = list({f["ticker"] for f in _cohort_per_suggestion_failures if f.get("ticker")})[:20]
            _distinct_error_classes = sorted({f["error_class"] for f in _cohort_per_suggestion_failures})
            _cohorts_affected = sorted({f["cohort_name"] for f in _cohort_per_suggestion_failures if f.get("cohort_name")})
            alert(
                _get_admin_supabase(),
                alert_type="paper_autopilot_cohort_per_suggestion_failed",
                severity="warning",
                message=f"{len(_cohort_per_suggestion_failures)} per-cohort suggestion executions failed",
                user_id=user_id,
                metadata={
                    "function_name": "_execute_per_cohort",
                    "failed_count": len(_cohort_per_suggestion_failures),
                    "failed_tickers": _failed_tickers,
                    "distinct_error_classes": _distinct_error_classes,
                    "cohorts_affected": _cohorts_affected,
                    "consequence": f"{len(_cohort_per_suggestion_failures)} cohort-routed suggestions did not execute as expected this cycle",
                },
            )

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
            alert(
                _get_admin_supabase(),
                alert_type="paper_autopilot_cohort_sweep_failed",
                severity="warning",
                message=f"Policy Lab cohort sweep failed: {type(e).__name__}",
                user_id=user_id,
                metadata={
                    "function_name": "_execute_per_cohort",
                    "error_class": type(e).__name__,
                    "error_message": str(e)[:500],
                    "consequence": "Policy Lab sweep skipped — cohort decision logging may be incomplete for this cycle",
                },
            )

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
        """Fetch open LIVE-routed positions for the risk envelope check.

        Scoped to live_eligible portfolios (position_scope.LIVE_ROUTING_MODE):
        this is a LIVE-entry circuit breaker, so shadow_only / paper_shadow
        cohort positions must not contaminate its concentration/stress math. A
        shadow_only BAC position blocking live entries on a flat live book was
        the 2026-06-02 bug (twin of #1011). On a flat live book this returns []
        -> total_risk=0 -> concentration early-returns -> no block, as intended.
        """
        try:
            from packages.quantum.risk.position_scope import LIVE_ROUTING_MODE
            port_res = self.client.table("paper_portfolios") \
                .select("id") \
                .eq("user_id", user_id) \
                .eq("routing_mode", LIVE_ROUTING_MODE) \
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
            alert(
                _get_admin_supabase(),
                alert_type="paper_autopilot_risk_check_positions_fetch_failed",
                severity="warning",
                message=f"Risk-check open positions fetch failed: {type(e).__name__}",
                user_id=user_id,
                metadata={
                    "function_name": "_get_open_positions_for_risk_check",
                    "error_class": type(e).__name__,
                    "error_message": str(e)[:500],
                    "consequence": "risk check proceeds without authoritative position state — concentration/correlation gates may be bypassed",
                },
            )
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
        """Get portfolio_id of the currently-promoted champion cohort,
        or None when no cohort is promoted (caller falls back to the
        default portfolio_id resolution path).

        #62a-D1 (closed 2026-05-18): pre-PR this queried
        `is_champion = True` — a non-existent column on
        `policy_lab_cohorts` — wrapped in a silent `try/except: pass`
        and always returned None. The integration seam between
        `policy_lab_evaluator` (writer of `promoted_at`) and the live
        routing consumer (this site + fork.py:67) was never connected.
        Rewritten to query `promoted_at`. See champion.py for the
        helper used by fork.py; this function intentionally returns
        the portfolio_id rather than the cohort_name because that's
        what the caller (`_stage_order_internal.portfolio_id_arg`)
        needs. See `docs/loud_error_doctrine.md` H12 for the doctrine.
        """
        try:
            res = self.client.table("policy_lab_cohorts") \
                .select("portfolio_id") \
                .eq("user_id", user_id) \
                .eq("is_active", True) \
                .not_.is_("promoted_at", "null") \
                .order("promoted_at", desc=True) \
                .limit(1) \
                .execute()
        except Exception as e:
            # Real network / permission failure. Loud log, defensive
            # None return. Caller treats None as "use default portfolio."
            logger.warning(
                f"_get_champion_portfolio lookup failed for user={user_id}: "
                f"{type(e).__name__}: {str(e)[:200]} — caller will use default portfolio"
            )
            return None

        if res.data and res.data[0].get("portfolio_id"):
            return res.data[0]["portfolio_id"]
        # No cohort promoted — caller falls back to default portfolio.
        # Expected during transition windows; not an alert condition.
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
        except Exception as _budget_err:
            alert(
                _get_admin_supabase(),
                alert_type="paper_autopilot_portfolio_budget_failed",
                severity="warning",
                message=f"Portfolio budget fetch failed (defaulting to $100k): {type(_budget_err).__name__}",
                user_id=user_id,
                metadata={
                    "function_name": "_get_portfolio_budget",
                    "error_class": type(_budget_err).__name__,
                    "error_message": str(_budget_err)[:500],
                    "fallback_budget": 100000,
                    "consequence": "sizing uses $100k default budget instead of authoritative portfolio cash — over-sizing risk",
                },
            )
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
            # #72-H5b: per-call alert (static method, can't aggregate
            # across close-loop without refactoring signature). Bounded
            # by close-loop size (~1-3 calls per cycle typically).
            alert(
                _get_admin_supabase(),
                alert_type="paper_autopilot_occ_resolve_failed",
                severity="warning",
                message=f"OCC symbol resolve failed for position {pos_id}: {type(e).__name__}",
                user_id=position.get("user_id"),
                symbol=underlying,
                metadata={
                    "function_name": "_resolve_occ_symbol",
                    "position_id": pos_id,
                    "underlying": underlying,
                    "error_class": type(e).__name__,
                    "error_message": str(e)[:500],
                    "consequence": "falls back to underlying ticker — quote will be stock NBBO, not options",
                },
            )

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
        # #72-H5b: aggregation list for per-position close failures
        _per_position_close_failures = []

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
                _per_position_close_failures.append({
                    "position_id": pos_id,
                    "symbol": position.get("symbol"),
                    "error_class": type(e).__name__,
                    "error_message": str(e)[:200],
                })

        # #72-H5b: aggregated alert for per-position close failures
        if _per_position_close_failures:
            _failed_symbols = list({f["symbol"] for f in _per_position_close_failures if f.get("symbol")})[:20]
            _distinct_error_classes = sorted({f["error_class"] for f in _per_position_close_failures})
            alert(
                _get_admin_supabase(),
                alert_type="paper_autopilot_per_position_close_failed",
                severity="warning",
                message=f"{len(_per_position_close_failures)} per-position close failures during autopilot",
                user_id=user_id,
                metadata={
                    "function_name": "close_positions",
                    "failed_count": len(_per_position_close_failures),
                    "failed_symbols": _failed_symbols,
                    "distinct_error_classes": _distinct_error_classes,
                    "consequence": f"{len(_per_position_close_failures)} positions failed to close this cycle — may remain open past intended exit",
                },
            )

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
