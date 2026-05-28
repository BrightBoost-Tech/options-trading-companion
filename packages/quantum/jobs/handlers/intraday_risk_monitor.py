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

logger = logging.getLogger(__name__)

JOB_NAME = "intraday_risk_monitor"
CHICAGO_TZ = ZoneInfo("America/Chicago")

# Force-close enforcement: warn-only until RISK_ENVELOPE_ENFORCE=1
_ENFORCE_FORCE_CLOSE = os.environ.get("RISK_ENVELOPE_ENFORCE", "0") == "1"

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

        # 3. Compute portfolio metrics for envelope check
        equity = self._estimate_equity(user_id, positions)
        daily_pnl = sum(float(p.get("unrealized_pl") or 0) for p in positions)
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

        # 4. Run envelope check
        config = EnvelopeConfig.from_env()
        result = check_all_envelopes(
            positions=positions,
            equity=equity,
            daily_pnl=daily_pnl,
            weekly_pnl=weekly_pnl,
            config=config,
        )

        # 4b. Check position-level exit conditions (stop loss, expiration)
        #     The envelope check above handles portfolio-level limits.
        #     This catches individual positions that hit their own stop/expiry
        #     between the scheduled 8:15 AM / 3:00 PM exit evaluations.
        from packages.quantum.services.paper_exit_evaluator import (
            evaluate_position_exit,
            EXIT_CONDITIONS,
        )
        exit_triggered = []
        for pos in positions:
            reason = evaluate_position_exit(pos, conditions=EXIT_CONDITIONS)
            if reason and reason in ("stop_loss", "expiration_day"):
                exit_triggered.append((pos, reason))

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
            success = self._execute_force_close(
                pos, f"intraday_{reason}", user_id
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
            port_res = self.supabase.table("paper_portfolios") \
                .select("id") \
                .eq("user_id", user_id) \
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
            if not legs:
                sym = normalize_symbol(pos.get("symbol", ""))
                snap = snapshots.get(sym, {})
                q = snap.get("quote", snap)
                bid = float(q.get("bid") or 0)
                ask = float(q.get("ask") or 0)
                mid = (bid + ask) / 2.0 if bid > 0 and ask > 0 else float(q.get("mid") or 0)
                if mid > 0:
                    qty = abs(float(pos.get("quantity") or 1))
                    current_value = mid * 100 * qty
                    entry_value = float(pos.get("avg_entry_price") or 0) * qty * 100
                    pos["current_mark"] = mid
                    pos["unrealized_pl"] = current_value - entry_value
                continue

            # Multi-leg: compute from all legs (all-or-nothing).
            #
            # Scale-consistency invariant (2026-05-18 BUG-A fix):
            # The stored `legs` JSON persists each leg's `quantity` as the
            # per-spread leg unit (typically 1) — NOT scaled by the number
            # of contracts in the position. `pos.quantity` is the spread
            # contract count (e.g. 4 for a 4-contract debit spread).
            #
            # We therefore compute the PER-SPREAD value from the legs
            # (each leg priced at its declared per-spread quantity), and
            # scale BOTH current_value and entry_value by pos.quantity in
            # the same step. Mixing scales — per-1 leg_total against per-N
            # entry_value — fabricates large losses on any multi-contract
            # position and force-closes it within seconds of opening.
            # Today's CSX 4-contract spread was the forcing example.
            per_spread_value = 0.0  # dollar value of ONE spread (post-fees-ex)
            all_priced = True
            for leg in legs:
                if not isinstance(leg, dict):
                    continue
                sym = normalize_symbol(leg.get("occ_symbol") or leg.get("symbol", ""))
                snap = snapshots.get(sym, {})
                q = snap.get("quote", snap)
                bid = float(q.get("bid") or 0)
                ask = float(q.get("ask") or 0)
                mid = (bid + ask) / 2.0 if bid > 0 and ask > 0 else float(q.get("mid") or 0)
                if mid <= 0:
                    all_priced = False
                    break
                # leg.quantity is the per-spread leg unit. Do NOT mix in
                # pos.quantity here — that's applied once at the end.
                leg_qty = float(leg.get("quantity") or 1)
                action = leg.get("action", "buy")
                side_mult = 1.0 if action == "buy" else -1.0
                per_spread_value += mid * 100 * abs(leg_qty) * side_mult

            if all_priced:
                qty_signed = float(pos.get("quantity") or 0)
                qty_abs = abs(qty_signed)
                per_spread_entry_value = float(pos.get("avg_entry_price") or 0) * 100
                # current_mark is the per-spread mark price ($/spread),
                # independent of pos.quantity. This is what downstream
                # consumers (paper_eod_snapshots, exit evaluator) expect.
                pos["current_mark"] = per_spread_value / 100.0
                # Compute per-spread P&L preserving the pre-fix sign
                # convention for credit (qty<0) vs debit (qty>0)
                # structures, THEN scale by qty_abs in the same step.
                # Pre-fix used qty=1 implicitly (leg_total was per-1 and
                # entry_value was per-N — only matched at qty=1). Both
                # branches keep the same per-spread shape; the only
                # change is that the qty_abs scaling is applied once,
                # consistently, at the end. avg_entry_price stores the
                # ABSOLUTE per-spread net premium for both debit and
                # credit positions, hence the per-spread entry constant
                # is unsigned and the directional sign comes from which
                # branch we take below.
                if qty_signed < 0:
                    # Short / credit: entry_per_spread is credit received
                    # (positive); abs(per_spread_value) is current
                    # liability (positive). PL/spread = entry - liability.
                    per_spread_pl = per_spread_entry_value - abs(per_spread_value)
                else:
                    # Long / debit: per_spread_value is current value
                    # (positive); entry_per_spread is cost paid (positive).
                    # PL/spread = current - entry.
                    per_spread_pl = per_spread_value - per_spread_entry_value
                pos["unrealized_pl"] = per_spread_pl * qty_abs

                # ── Payoff-bound guard (Task 1, 2026-05-28) ───────────────
                # Layered ON TOP of the mark math above — changes no
                # computation. Bounds the just-finalised unrealized_pl to the
                # spread's physical payoff envelope and surfaces impossible
                # marks loudly. Convention-agnostic: the bound is derived from
                # pos.quantity + strikes + avg_entry (reliable), never from
                # legs.quantity (the unreliable field — see #3). The
                # legs.quantity double-count this guard catches (F: +$1,695 vs
                # max-profit +$520) is NOT fixed here; that is #3.
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

    def _execute_force_close(self, position: Dict, reason: str, user_id: str) -> bool:
        """
        Submit close order for a single position.

        Uses the same _close_position path as PaperExitEvaluator — no duplicate logic.
        Returns True if close was submitted, False if skipped or failed.
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
                .select("id, status") \
                .eq("position_id", pos_id) \
                .eq("side", close_side) \
                .in_("status", [
                    "staged", "submitted", "working", "partial", "pending",
                    "needs_manual_review", "filled", "cancelled",
                ]) \
                .execute()
            if existing.data:
                logger.info(
                    f"[RISK_MONITOR] Skipping {symbol} — close order already exists "
                    f"(order_id={existing.data[0]['id'][:8]} "
                    f"status={existing.data[0]['status']})"
                )
                return False
        except Exception as e:
            logger.warning(f"[RISK_MONITOR] Idempotency check failed for {pos_id}: {e}")

        # Use the same close method as PaperExitEvaluator
        try:
            from packages.quantum.services.paper_exit_evaluator import PaperExitEvaluator
            evaluator = PaperExitEvaluator(self.supabase)
            result = evaluator._close_position(
                user_id=user_id,
                position_id=pos_id,
                reason=f"risk_envelope:{reason}",
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
