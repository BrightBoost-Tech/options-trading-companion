"""
Intraday Risk Monitor Job Handler

Runs every 15 minutes during market hours (9:30 AM - 4:00 PM CT).
Closes the 6-hour monitoring gap between the 8:15 AM and 3:00 PM exit evaluations.

Responsibilities:
- Fetch fresh quotes from Alpaca for all open option positions
- Recompute unrealized P&L per position
- Run check_all_envelopes() with current portfolio state
- FORCE_CLOSE violations: submit exit order immediately via Alpaca
- WARN violations: log to risk_alerts table
- All actions logged to risk_alerts and job_runs

Safety rules:
- Can only CLOSE positions, never OPEN
- Skips if market is closed
- Idempotent: if a close order already exists for a position, skip it
- If Alpaca submission fails, log critical alert and retry next cycle
"""

import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from packages.quantum.jobs.handlers.utils import get_admin_client
from packages.quantum.jobs.handlers.exceptions import PermanentJobError
from packages.quantum.services import equity_state
from packages.quantum.risk.payoff_bounds import (
    evaluate_payoff_bound,
    payoff_bound_alert_fields,
)
from packages.quantum.risk.mark_math import compute_current_value, finalize_mark

logger = logging.getLogger(__name__)

JOB_NAME = "intraday_risk_monitor"
CHICAGO_TZ = ZoneInfo("America/Chicago")

# Force-close enforcement: warn-only until RISK_ENVELOPE_ENFORCE=1
_ENFORCE_FORCE_CLOSE = os.environ.get("RISK_ENVELOPE_ENFORCE", "0") == "1"
# Intraday target_profit capture (default OFF). When on, the 15-min monitor
# also closes positions that hit their per-cohort target_profit — the profit-
# side mirror of the stop_loss it already acts on — closing the multi-hour
# blind window between the twice-daily paper_exit_evaluate runs (F marked +$30
# at 13:15Z, realized +$105 on an intraday spike the system wouldn't recheck
# until ~20:00Z). Enabling is a separate operator decision after tests pass and
# ideally after observing one cycle correctly HOLD a below-target position.
_INTRADAY_TARGET_PROFIT_ENABLED = os.environ.get("INTRADAY_TARGET_PROFIT_ENABLED", "0") == "1"

# Alpaca-authoritative equity + weekly P&L were extracted to
# `packages.quantum.services.equity_state` so that other callers
# (paper_mark_to_market, paper_autopilot_service) can adopt the same
# discipline in follow-up PRs. See its module docstring for rationale and
# the RISK_EQUITY_SOURCE rip-cord.


def run(payload: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    """
    Main entry point — called by the job runner.

    Returns summary dict for job_runs logging.
    """
    start_time = time.time()

    try:
        monitor = IntradayRiskMonitor()
        result = monitor.execute(payload)
        result["duration_ms"] = int((time.time() - start_time) * 1000)
        return result
    except Exception as e:
        logger.error(f"[RISK_MONITOR] Fatal error: {e}", exc_info=True)
        return {
            "ok": False,
            "error": str(e),
            "duration_ms": int((time.time() - start_time) * 1000),
        }


class IntradayRiskMonitor:
    """Monitors open positions and enforces risk envelope limits intra-day."""

    def __init__(self):
        self.supabase = get_admin_client()

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Run a single monitoring cycle."""
        from packages.quantum.observability.agent_sessions import agent_session

        with agent_session("loss_minimization") as session:
            # 1. Market hours check
            if not self._is_market_open():
                result = {"ok": True, "status": "market_closed", "checks": 0}
                session.summary = result
                return result

            # 2. Get user IDs to monitor
            user_ids = self._get_active_user_ids(payload)
            if not user_ids:
                result = {"ok": True, "status": "no_users", "checks": 0}
                session.summary = result
                return result

            all_results = []
            for user_id in user_ids:
                try:
                    user_result = self._check_user(user_id)
                    all_results.append(user_result)
                except Exception as e:
                    logger.error(f"[RISK_MONITOR] Error for user {user_id[:8]}: {e}")
                    all_results.append({"user_id": user_id[:8], "error": str(e)})

            total_violations = sum(r.get("violations", 0) for r in all_results)
            total_force_closes = sum(r.get("force_closes_submitted", 0) for r in all_results)

            result = {
                "ok": True,
                "status": "completed",
                "users_checked": len(user_ids),
                "total_violations": total_violations,
                "total_force_closes": total_force_closes,
                "results": all_results,
            }
            session.summary = result
            return result

    def _check_user(self, user_id: str) -> Dict[str, Any]:
        """Run full risk check for a single user."""
        from packages.quantum.risk.risk_envelope import (
            check_all_envelopes,
            EnvelopeConfig,
        )
        from packages.quantum.services.market_data_truth_layer import MarketDataTruthLayer
        from packages.quantum.services.cache_key_builder import normalize_symbol

        # 1. Fetch open positions
        positions = self._fetch_open_positions(user_id)
        if not positions:
            return {"user_id": user_id[:8], "positions": 0, "violations": 0}

        # 2. Refresh marks from Alpaca
        positions = self._refresh_marks(positions)

        # 2b. Scope the portfolio-level envelope (concentration / stress / loss)
        #     to the LIVE book. shadow_only / paper_shadow cohort positions are
        #     internal/simulated — not live capital — and must not drive
        #     concentration alerts or loss force-close (the 2026-06-02 phantom
        #     "BAC 100% of risk" 15-min alerts; twin of the #1011 dedup
        #     contamination). Per-position exit triggers (5a, below) still run
        #     over the FULL managed set, so shadow cohorts keep their own
        #     stop/target/expiration exits — this scopes the live-CAPITAL
        #     aggregate only, it does not blind any cohort to its own exits.
        try:
            from packages.quantum.risk.position_scope import live_routed_portfolio_ids
            _live_ids = set(live_routed_portfolio_ids(self.supabase, user_id))
            live_positions = [p for p in positions if p.get("portfolio_id") in _live_ids]
        except Exception as _scope_err:
            logger.warning(
                f"[RISK_MONITOR] user={user_id[:8]}: live-routing scope query failed "
                f"({type(_scope_err).__name__}); envelope falls back to full managed "
                f"set this cycle (per-position exits unaffected)"
            )
            live_positions = positions

        # 3. Compute portfolio metrics for envelope check (LIVE book)
        equity = self._estimate_equity(user_id, live_positions)
        daily_pnl = sum(float(p.get("unrealized_pl") or 0) for p in live_positions)
        weekly_pnl = self._compute_weekly_pnl(user_id, daily_pnl)

        # Alpaca-unavailable fallbacks. Do NOT fabricate equity or weekly P&L
        # from local estimates — that was the 2026-04-16 failure mode
        # (fabricated $8,982 equity + $17K summed-snapshot "weekly loss"
        # triggered force-close at -190% on a ~-1% real week).
        if equity is None:
            logger.warning(
                f"[RISK_MONITOR] user={user_id[:8]}: Alpaca equity unavailable — "
                f"skipping weekly + daily loss envelopes. Greeks, concentration, "
                f"stress, and position-level stop/expiry exits still run."
            )
            # check_loss_envelopes short-circuits at equity <= 0, so passing 0.0
            # cleanly skips both daily and weekly envelopes. Stress also skips.
            equity = 0.0
        if weekly_pnl is None:
            logger.warning(
                f"[RISK_MONITOR] user={user_id[:8]}: Alpaca weekly P&L unavailable — "
                f"skipping weekly envelope only. Daily loss envelope continues "
                f"on local daily_pnl against real Alpaca equity."
            )
            # 0 is benign: 0 / equity = 0, no weekly breach. Daily still runs.
            weekly_pnl = 0.0

        # 4. Run envelope check (LIVE book only — see 2b)
        config = EnvelopeConfig.from_env()
        result = check_all_envelopes(
            positions=live_positions,
            equity=equity,
            daily_pnl=daily_pnl,
            weekly_pnl=weekly_pnl,
            config=config,
        )

        # 4b. Check position-level exit conditions (stop loss, expiration)
        #     The envelope check above handles portfolio-level limits.
        #     This catches individual positions that hit their own stop/expiry
        #     between the scheduled 8:15 AM / 3:00 PM exit evaluations.
        #     Runs over the FULL managed set (not just live) so shadow cohorts
        #     keep their own intraday exits (2b).
        exit_triggered = self._collect_intraday_exit_triggers(positions, user_id)

        # 5. Process violations
        force_closes_submitted = 0
        warnings_logged = 0

        # 2026-05-18 BUG-C fix (FIX 2d): track positions that have been
        # successfully force-closed in THIS cycle. The `positions` list
        # at line 127 is fetched once per cycle and never refreshed —
        # after a successful close, the in-memory state is stale (the
        # DB row's status is now 'closed' but the dict in this list
        # still shows 'open'). Without this set, the 5a and 5b loops
        # below would call _execute_force_close repeatedly on the same
        # position when multiple violations fire against it, staging
        # zero-qty duplicate close orders and raising spurious critical
        # alerts. Today's CSX cycle: stop_loss (5a) + 2 loss-envelope
        # force_closes (5b) → 5 attempts on the same position, 4 of
        # which fired AFTER the position was already closed.
        closed_in_this_cycle: set = set()

        # 5a. Position-level exit triggers — ALWAYS execute.
        #      Stop losses and expiration-day exits are safety-critical and must
        #      not be gated behind RISK_ENVELOPE_ENFORCE (which controls only
        #      portfolio-level force-close behavior).
        for pos, reason in exit_triggered:
            pid = pos.get("id")
            if pid in closed_in_this_cycle:
                continue
            # Attribution: target_profit must record close_reason='target_profit_hit'
            # (the bare reason maps there via _map_close_reason), NOT the
            # 'envelope_force_close' bucket the 'risk_envelope:' prefix maps to.
            # stop_loss/expiration keep their existing risk_envelope: mapping
            # (unchanged) by passing no override.
            _mapped = "target_profit" if reason == "target_profit" else None
            success = self._execute_force_close(
                pos, f"intraday_{reason}", user_id, mapped_close_reason=_mapped
            )
            if success:
                force_closes_submitted += 1
                if pid:
                    closed_in_this_cycle.add(pid)

        # 5b. Envelope violations
        #     Daily/weekly/per-symbol loss limits are safety-critical — always
        #     execute force-close regardless of RISK_ENVELOPE_ENFORCE.
        #     Concentration and stress violations remain gated behind the flag.
        #     This mirrors the pattern established for position-level exits in 5a.
        for violation in result.violations:
            if violation.severity == "force_close":
                is_loss_envelope = violation.envelope.startswith("loss_")
                should_execute = is_loss_envelope or _ENFORCE_FORCE_CLOSE

                if should_execute:
                    # Find positions to close
                    for pos_id in result.force_close_ids:
                        if pos_id in closed_in_this_cycle:
                            continue
                        pos = next((p for p in positions if p.get("id") == pos_id), None)
                        if pos:
                            success = self._execute_force_close(
                                pos, violation.message, user_id
                            )
                            if success:
                                force_closes_submitted += 1
                                closed_in_this_cycle.add(pos_id)
                else:
                    # Warn-only mode for non-loss envelopes
                    self._log_alert(
                        user_id=user_id,
                        alert_type="force_close",
                        severity="critical",
                        message=f"[WARN-ONLY] {violation.message} (enforcement disabled)",
                        position_id=None,
                        symbol=None,
                        metadata=violation.to_dict(),
                    )
                    warnings_logged += 1
            elif violation.severity in ("warn", "block"):
                self._log_alert(
                    user_id=user_id,
                    alert_type="warn",
                    severity="high" if violation.severity == "block" else "medium",
                    message=violation.message,
                    metadata=violation.to_dict(),
                )
                warnings_logged += 1

        logger.info(
            f"[RISK_MONITOR] user={user_id[:8]} positions={len(positions)} "
            f"equity=${equity:.0f} daily_pnl=${daily_pnl:.0f} "
            f"violations={len(result.violations)} "
            f"force_closes={force_closes_submitted} warnings={warnings_logged} "
            f"envelope_passed={result.passed}"
        )

        return {
            "user_id": user_id[:8],
            "positions": len(positions),
            "violations": len(result.violations),
            "force_closes_submitted": force_closes_submitted,
            "warnings_logged": warnings_logged,
            "envelope_passed": result.passed,
            "sizing_multiplier": result.sizing_multiplier,
        }

    # ── Market hours ──────────────────────────────────────────────────

    def _is_market_open(self) -> bool:
        """Return True if current time is within market hours (9:30-4:00 CT, weekdays)."""
        now = datetime.now(CHICAGO_TZ)
        if now.weekday() >= 5:  # Saturday=5, Sunday=6
            return False
        market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
        return market_open <= now <= market_close

    # ── Position fetching ─────────────────────────────────────────────

    def _fetch_open_positions(self, user_id: str) -> List[Dict]:
        """Fetch all open paper positions for a user."""
        try:
            # Paper-shadow isolation (additive, no-op when off): exclude the
            # paper-shadow executor's portfolios so the live monitor never
            # manages its observation positions. Extends the existing
            # shadow_only exclusion precedent (see services/paper_shadow_isolation.py
            # PAPER_SHADOW_ROUTING_MODE). When no paper_shadow portfolios exist
            # (always, pre-Phase-1b), .neq matches all rows → identical result.
            port_res = self.supabase.table("paper_portfolios") \
                .select("id") \
                .eq("user_id", user_id) \
                .neq("routing_mode", "paper_shadow") \
                .execute()

            portfolio_ids = [p["id"] for p in (port_res.data or [])]
            if not portfolio_ids:
                return []

            pos_res = self.supabase.table("paper_positions") \
                .select("*") \
                .in_("portfolio_id", portfolio_ids) \
                .eq("status", "open") \
                .neq("quantity", 0) \
                .execute()

            return pos_res.data or []
        except Exception as e:
            logger.error(f"[RISK_MONITOR] Failed to fetch positions: {e}")
            return []

    # ── Mark refresh ──────────────────────────────────────────────────

    def _refresh_marks(self, positions: List[Dict]) -> List[Dict]:
        """
        Get fresh quotes from Alpaca snapshots for all position symbols.
        Recompute unrealized_pl for each position.
        Reuses the same MarketDataTruthLayer as paper_mark_to_market.
        """
        from packages.quantum.services.market_data_truth_layer import MarketDataTruthLayer
        from packages.quantum.services.cache_key_builder import normalize_symbol

        truth_layer = MarketDataTruthLayer()

        # Collect all leg symbols
        all_symbols = []
        for pos in positions:
            legs = pos.get("legs") or []
            for leg in legs:
                if isinstance(leg, dict):
                    sym = leg.get("occ_symbol") or leg.get("symbol", "")
                    if sym:
                        all_symbols.append(sym)
            if not legs and pos.get("symbol"):
                all_symbols.append(pos["symbol"])

        if not all_symbols:
            return positions

        # Batch fetch — routes options to Alpaca, equities to Polygon
        snapshots = truth_layer.snapshot_many(all_symbols)

        # #2026-05-12 MTM-staleness PR-1: track positions whose in-memory
        # recompute fails (multi-leg with any incomplete leg quote → the
        # all_priced guard below short-circuits). Pre-fix, these silently
        # retained their DB-staleness value and threshold checks operated
        # on it. Tracking the skip set so we can emit a loud alert after
        # the loop. H9 wrapper-drift class.
        skipped_positions: List[Dict] = []

        # Update positions with fresh marks
        for pos in positions:
            legs = pos.get("legs") or []

            # Shared mid resolver over the pre-fetched snapshots (used for both
            # the leg-less and multi-leg paths via risk.mark_math).
            def _mid_for(sym: str) -> float:
                snap = snapshots.get(normalize_symbol(sym), {})
                q = snap.get("quote", snap)
                bid = float(q.get("bid") or 0)
                ask = float(q.get("ask") or 0)
                return (bid + ask) / 2.0 if (bid > 0 and ask > 0) else float(q.get("mid") or 0)

            if not legs:
                mid = _mid_for(pos.get("symbol", ""))
                if mid > 0:
                    qty_signed = float(pos.get("quantity") or 1)
                    current_value = mid * 100 * abs(qty_signed)
                    # #3 unification: single shared full-count finalize (H13).
                    pos["current_mark"], pos["unrealized_pl"] = finalize_mark(
                        qty_signed, pos.get("avg_entry_price"), current_value
                    )
                continue

            # Multi-leg: single shared full-count mark math (H13, #3).
            #
            # Convention (#3, pinned): legs[].quantity == the position contract
            # count (full-count). compute_current_value sums the TOTAL signed
            # value across all contracts; finalize_mark scales unrealized_pl
            # exactly ONCE. The pre-unification code here treated leg.quantity as
            # a per-spread unit (1) and then multiplied per-spread P&L by
            # pos.quantity AGAIN — double-counting (F: +$2,070 vs the correct
            # +$30). Both readers now route through risk.mark_math so they cannot
            # diverge. The CSX 4-contract BUG-A shape is prevented at the fill
            # seam (assertion+coercion) and any per-spread row that still reached
            # here would be caught loudly by the #987 payoff-bound guard below.
            current_value = compute_current_value(legs, _mid_for, pos.get("quantity"))

            if current_value is not None:
                qty_signed = float(pos.get("quantity") or 0)
                pos["current_mark"], pos["unrealized_pl"] = finalize_mark(
                    qty_signed, pos.get("avg_entry_price"), current_value
                )

                # ── Payoff-bound guard (#987, retained) ───────────────────
                # Layered ON TOP of the unified mark math — changes no
                # computation. Convention-agnostic (pos.quantity + strikes +
                # avg_entry, never legs.quantity). With the double-count removed
                # this should now be in-bounds for F (+$30); it remains the loud
                # catch if any future per-spread row slips through.
                _bound = evaluate_payoff_bound(pos, pos["unrealized_pl"])
                if _bound.applicable and not _bound.in_bounds:
                    self._log_alert(
                        user_id=pos.get("user_id") or "",
                        position_id=pos.get("id"),
                        symbol=pos.get("symbol"),
                        **payoff_bound_alert_fields(
                            pos, _bound,
                            "intraday_risk_monitor._refresh_marks",
                        ),
                    )
                    pos["unrealized_pl"] = _bound.clamped_value
            else:
                # #2026-05-12 MTM-staleness PR-1: multi-leg recompute
                # short-circuited due to at least one leg returning
                # mid <= 0. Position retains its DB-stale unrealized_pl
                # for the downstream threshold checks — record the skip
                # so we alert after the loop.
                skipped_positions.append({
                    "position_id": pos.get("id"),
                    "symbol": pos.get("symbol"),
                    "leg_count": len([l for l in legs if isinstance(l, dict)]),
                    "stale_unrealized_pl": float(pos.get("unrealized_pl") or 0),
                })

        # #2026-05-12 MTM-staleness PR-1: loud alert when any position's
        # in-memory recompute failed. Pre-fix, the silent skip left
        # threshold checks operating on DB-stale values (today's CSX:
        # DB=-$8, Alpaca truth=-$196, no force-close fired). Same
        # alert_type as paper_mark_to_market_service.refresh_marks's
        # equivalent fire — queryable together; `source` distinguishes
        # which refresh site fired.
        if skipped_positions:
            self._log_alert(
                user_id=positions[0].get("user_id") if positions else "",
                alert_type="mtm_refresh_partial",
                severity="warning",
                message=(
                    f"intraday_risk_monitor MTM recompute skipped "
                    f"{len(skipped_positions)} of {len(positions)} positions "
                    f"due to incomplete leg quotes"
                ),
                metadata={
                    "source": "intraday_risk_monitor._refresh_marks",
                    "positions_skipped": len(skipped_positions),
                    "total_positions": len(positions),
                    "skipped": skipped_positions[:20],
                    "consequence": (
                        "Skipped positions retain stale DB unrealized_pl. "
                        "Per-symbol / daily / weekly loss thresholds will "
                        "operate on stale values; force-close may not fire "
                        "on positions that have moved against us intraday. "
                        "Resolved by PR-2 (broker-authoritative fallback "
                        "via Alpaca.get_all_positions)."
                    ),
                },
            )

        return positions

    # ── Equity estimation ─────────────────────────────────────────────
    # Delegates to packages.quantum.services.equity_state. Shims are kept
    # here so test doubles can override per-instance without reaching into
    # the shared module.

    def _estimate_equity(self, user_id: str, positions: List[Dict]) -> Optional[float]:
        return equity_state.get_alpaca_equity(
            user_id, supabase=self.supabase, positions=positions,
        )

    def _compute_weekly_pnl(
        self, user_id: str, daily_pnl: float
    ) -> Optional[float]:
        return equity_state.get_alpaca_weekly_pnl(user_id, supabase=self.supabase)

    # ── Force close ───────────────────────────────────────────────────

    def _collect_intraday_exit_triggers(self, positions: List[Dict], user_id: str) -> List:
        """Collect position-level intraday exit triggers as (position, reason) pairs.

        - stop_loss / expiration_day: evaluated on the default EXIT_CONDITIONS via
          the shared evaluate_position_exit — UNCHANGED existing behavior.
        - target_profit (flag-gated, _INTRADAY_TARGET_PROFIT_ENABLED): the profit-
          side mirror. Uses the SAME per-cohort _check_target_profit (inside the
          cohort's build_exit_conditions check) — no parallel decision logic (H13).
          Marks are the post-#3 unified full-count values (risk.mark_math), so the
          threshold is evaluated against correct unrealized_pl (not the old
          double-count). Reuses load_cohort_configs / build_exit_conditions /
          _resolve_position_cohort — the same machinery the scheduled evaluator uses.

        Fail-safe: if per-cohort params can't be resolved, target_profit is NOT
        acted on (better to wait for the scheduled run than act on a wrong
        threshold). stop_loss/expiration are unaffected by that fail-safe.
        """
        from packages.quantum.services.paper_exit_evaluator import (
            evaluate_position_exit,
            EXIT_CONDITIONS,
            build_exit_conditions,
            PaperExitEvaluator,
        )

        tp_active = _INTRADAY_TARGET_PROFIT_ENABLED
        tp_conditions_by_cohort: Dict[str, Any] = {}
        tp_evaluator = None
        if tp_active:
            try:
                from packages.quantum.policy_lab.config import load_cohort_configs
                tp_evaluator = PaperExitEvaluator(self.supabase)
                for _cn, _cfg in (load_cohort_configs(user_id, self.supabase) or {}).items():
                    tp_conditions_by_cohort[_cn] = build_exit_conditions(
                        target_profit_pct=_cfg.target_profit_pct,
                        stop_loss_pct=_cfg.stop_loss_pct,
                        min_dte_to_exit=_cfg.min_dte_to_exit,
                    )
            except Exception as e:
                logger.warning(
                    f"[RISK_MONITOR] intraday target_profit cohort load failed "
                    f"(non-fatal; target_profit not acted on this cycle): {e}"
                )
                tp_active = False

        exit_triggered = []
        for pos in positions:
            reason = evaluate_position_exit(pos, conditions=EXIT_CONDITIONS)
            if reason and reason in ("stop_loss", "expiration_day"):
                exit_triggered.append((pos, reason))
                continue  # stop/expiry take priority; a position can't also be at +target
            if tp_active:
                try:
                    cohort = tp_evaluator._resolve_position_cohort(pos)
                    conds = tp_conditions_by_cohort.get(cohort) or EXIT_CONDITIONS
                    if conds["target_profit"]["check"](pos):
                        exit_triggered.append((pos, "target_profit"))
                except Exception as e:
                    logger.warning(
                        f"[RISK_MONITOR] intraday target_profit check failed for "
                        f"{pos.get('id')} (non-fatal): {e}"
                    )
        return exit_triggered

    def _execute_force_close(
        self, position: Dict, reason: str, user_id: str,
        mapped_close_reason: Optional[str] = None,
    ) -> bool:
        """
        Submit close order for a single position.

        Uses the same _close_position path as PaperExitEvaluator — no duplicate logic.
        Returns True if close was submitted, False if skipped or failed.

        mapped_close_reason: optional bare exit reason (e.g. "target_profit") passed
        straight to _close_position so it maps to the correct close_reason enum
        (target_profit_hit). When None (stop_loss / envelope breaches), the existing
        "risk_envelope:{reason}" form is used (→ envelope_force_close), unchanged.
        """
        pos_id = position.get("id", "unknown")
        symbol = position.get("symbol", "?")

        # Idempotency: check if a close order already exists.
        # Includes needs_manual_review to prevent the order-spam loop where
        # each cycle creates a new order that immediately fails. The deeper
        # guard in _close_position is the true gate, but this avoids the
        # overhead of the routing check + staging attempt.
        #
        # 2026-05-18 BUG-C fix: 'filled' and 'cancelled' MUST be in the
        # filter, AND the lookup must be scoped to the CLOSE side
        # (sell-to-close for long, buy-to-close for short) so the entry
        # order — which shares position_id and ends in status='filled' —
        # does not match. Pre-fix list omitted 'filled', so when the
        # first internal-paper close order filled synchronously, the next
        # iteration of the violation loop punched straight through this
        # guard and staged a duplicate (today's CSX cycle staged 4
        # zero-qty close orders). 'cancelled' is included for the same
        # reason: a close attempt that was reasoned away leaves a
        # terminal trace; treating it as "no close attempted" causes
        # spurious retries.
        position_qty = float(position.get("quantity") or 0)
        close_side = "sell" if position_qty > 0 else "buy"
        try:
            existing = self.supabase.table("paper_orders") \
                .select("id, status, order_json") \
                .eq("position_id", pos_id) \
                .eq("side", close_side) \
                .in_("status", [
                    "staged", "submitted", "working", "partial", "pending",
                    "needs_manual_review", "filled", "cancelled",
                ]) \
                .execute()
            # GTC resting profit-limits must NOT satisfy this guard — a
            # parked gtc_profit_exit order would otherwise permanently
            # disarm stop/envelope force-closes for the position. The
            # force-close proceeds; submit_and_track's pre-cancel removes
            # the resting GTC at the broker before submitting.
            from packages.quantum.services.paper_exit_evaluator import (
                filter_blocking_close_orders,
            )
            _blocking = filter_blocking_close_orders(existing.data or [])
            if _blocking:
                logger.info(
                    f"[RISK_MONITOR] Skipping {symbol} — close order already exists "
                    f"(order_id={_blocking[0]['id'][:8]} "
                    f"status={_blocking[0]['status']})"
                )
                return False
        except Exception as e:
            logger.warning(f"[RISK_MONITOR] Idempotency check failed for {pos_id}: {e}")

        # Use the same close method as PaperExitEvaluator
        try:
            from packages.quantum.services.paper_exit_evaluator import PaperExitEvaluator
            evaluator = PaperExitEvaluator(self.supabase)
            _close_reason_arg = mapped_close_reason if mapped_close_reason else f"risk_envelope:{reason}"
            result = evaluator._close_position(
                user_id=user_id,
                position_id=pos_id,
                reason=_close_reason_arg,
            )

            self._log_alert(
                user_id=user_id,
                alert_type="force_close",
                severity="critical",
                message=f"Force-closed {symbol}: {reason}",
                position_id=pos_id,
                symbol=symbol,
                metadata={
                    "order_id": result.get("order_id"),
                    "routed_to": result.get("routed_to"),
                    "unrealized_pl": float(position.get("unrealized_pl") or 0),
                },
            )

            logger.critical(
                f"[RISK_MONITOR] FORCE CLOSE submitted: {symbol} "
                f"unrealized=${position.get('unrealized_pl', 0):.0f} "
                f"reason={reason} order_id={result.get('order_id', '?')}"
            )
            return True

        except Exception as e:
            logger.error(
                f"[RISK_MONITOR] Force close FAILED for {symbol}: {e}. "
                f"Will retry next cycle."
            )
            self._log_alert(
                user_id=user_id,
                alert_type="force_close",
                severity="critical",
                message=f"Force close FAILED for {symbol}: {e} — retrying next cycle",
                position_id=pos_id,
                symbol=symbol,
                metadata={"error": str(e)},
            )
            return False

    # ── Alert logging ─────────────────────────────────────────────────

    def _log_alert(
        self,
        user_id: str,
        alert_type: str,
        severity: str,
        message: str,
        position_id: Optional[str] = None,
        symbol: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ):
        """Write a risk alert to the risk_alerts table."""
        try:
            self.supabase.table("risk_alerts").insert({
                "user_id": user_id,
                "alert_type": alert_type,
                "severity": severity,
                "position_id": position_id,
                "symbol": symbol,
                "message": message,
                "metadata": metadata or {},
            }).execute()
        except Exception as e:
            logger.error(f"[RISK_MONITOR] Failed to write risk_alert: {e}")

    # ── User discovery ────────────────────────────────────────────────

    def _get_active_user_ids(self, payload: Dict) -> List[str]:
        """Get user IDs to monitor — from payload or all users with open positions."""
        # Explicit user_id in payload
        uid = payload.get("user_id") or os.environ.get("USER_ID") or os.environ.get("TASK_USER_ID")
        if uid:
            return [uid]

        # Discover from open positions
        try:
            from packages.quantum.jobs.handlers.utils import get_active_user_ids
            return get_active_user_ids(self.supabase)
        except Exception:
            return []
