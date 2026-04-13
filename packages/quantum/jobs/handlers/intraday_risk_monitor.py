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
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from packages.quantum.jobs.handlers.utils import get_admin_client
from packages.quantum.jobs.handlers.exceptions import PermanentJobError

logger = logging.getLogger(__name__)

JOB_NAME = "intraday_risk_monitor"
CHICAGO_TZ = ZoneInfo("America/Chicago")

# Force-close enforcement: warn-only until RISK_ENVELOPE_ENFORCE=1
_ENFORCE_FORCE_CLOSE = os.environ.get("RISK_ENVELOPE_ENFORCE", "0") == "1"


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

        # 1. Market hours check
        if not self._is_market_open():
            return {"ok": True, "status": "market_closed", "checks": 0}

        # 2. Get user IDs to monitor
        user_ids = self._get_active_user_ids(payload)
        if not user_ids:
            return {"ok": True, "status": "no_users", "checks": 0}

        all_results = []
        for user_id in user_ids:
            try:
                result = self._check_user(user_id)
                all_results.append(result)
            except Exception as e:
                logger.error(f"[RISK_MONITOR] Error for user {user_id[:8]}: {e}")
                all_results.append({"user_id": user_id[:8], "error": str(e)})

        total_violations = sum(r.get("violations", 0) for r in all_results)
        total_force_closes = sum(r.get("force_closes_submitted", 0) for r in all_results)

        return {
            "ok": True,
            "status": "completed",
            "users_checked": len(user_ids),
            "total_violations": total_violations,
            "total_force_closes": total_force_closes,
            "results": all_results,
        }

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

        # 5a. Position-level exit triggers — ALWAYS execute.
        #      Stop losses and expiration-day exits are safety-critical and must
        #      not be gated behind RISK_ENVELOPE_ENFORCE (which controls only
        #      portfolio-level force-close behavior).
        for pos, reason in exit_triggered:
            success = self._execute_force_close(
                pos, f"intraday_{reason}", user_id
            )
            if success:
                force_closes_submitted += 1

        # 5b. Envelope violations
        for violation in result.violations:
            if violation.severity == "force_close":
                if _ENFORCE_FORCE_CLOSE:
                    # Find positions to close
                    for pos_id in result.force_close_ids:
                        pos = next((p for p in positions if p.get("id") == pos_id), None)
                        if pos:
                            success = self._execute_force_close(
                                pos, violation.message, user_id
                            )
                            if success:
                                force_closes_submitted += 1
                else:
                    # Warn-only mode (pre April 13)
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

            # Multi-leg: compute from all legs (all-or-nothing)
            leg_total = 0.0
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
                leg_qty = float(leg.get("quantity") or pos.get("quantity") or 1)
                action = leg.get("action", "buy")
                side_mult = 1.0 if action == "buy" else -1.0
                leg_total += mid * 100 * abs(leg_qty) * side_mult

            if all_priced:
                qty = abs(float(pos.get("quantity") or 1))
                entry_value = float(pos.get("avg_entry_price") or 0) * qty * 100
                pos["current_mark"] = leg_total / (qty * 100) if qty > 0 else 0
                if float(pos.get("quantity") or 0) < 0:
                    pos["unrealized_pl"] = entry_value - abs(leg_total)
                else:
                    pos["unrealized_pl"] = leg_total - entry_value

        return positions

    # ── Equity estimation ─────────────────────────────────────────────

    def _estimate_equity(self, user_id: str, positions: List[Dict]) -> float:
        """
        Estimate portfolio equity from deployable capital config or position values.
        """
        # Try go_live_progression for capital
        try:
            res = self.supabase.table("go_live_progression") \
                .select("deployable_capital") \
                .eq("user_id", user_id) \
                .limit(1) \
                .execute()
            if res.data and res.data[0].get("deployable_capital"):
                return float(res.data[0]["deployable_capital"])
        except Exception:
            pass

        # Fallback: sum of entry values
        total = sum(
            abs(float(p.get("avg_entry_price") or 0))
            * abs(float(p.get("quantity") or 1))
            * 100
            for p in positions
        )
        return max(total * 2, 500.0)  # Rough 2x estimate, floor $500

    def _compute_weekly_pnl(self, user_id: str, daily_pnl: float) -> float:
        """
        Compute this week's cumulative P&L from EOD snapshots.
        Falls back to daily_pnl if no history available.
        """
        try:
            monday = date.today() - timedelta(days=date.today().weekday())
            res = self.supabase.table("paper_eod_snapshots") \
                .select("unrealized_pl") \
                .gte("snapshot_date", monday.isoformat()) \
                .execute()
            if res.data:
                week_total = sum(float(r.get("unrealized_pl") or 0) for r in res.data)
                return week_total + daily_pnl
        except Exception:
            pass
        return daily_pnl

    # ── Force close ───────────────────────────────────────────────────

    def _execute_force_close(self, position: Dict, reason: str, user_id: str) -> bool:
        """
        Submit close order for a single position.

        Uses the same _close_position path as PaperExitEvaluator — no duplicate logic.
        Returns True if close was submitted, False if skipped or failed.
        """
        pos_id = position.get("id", "unknown")
        symbol = position.get("symbol", "?")

        # Idempotency: check if a close order already exists
        try:
            existing = self.supabase.table("paper_orders") \
                .select("id") \
                .eq("position_id", pos_id) \
                .in_("status", ["submitted", "working", "partial", "pending"]) \
                .execute()
            if existing.data:
                logger.info(
                    f"[RISK_MONITOR] Skipping {symbol} — close order already pending "
                    f"(order_id={existing.data[0]['id'][:8]})"
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
