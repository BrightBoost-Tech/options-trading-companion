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
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from packages.quantum.jobs.handlers.utils import get_admin_client
from packages.quantum.jobs.handlers.exceptions import PermanentJobError
from packages.quantum.services import equity_state
from packages.quantum.risk.payoff_bounds import (
    evaluate_payoff_bound,
    payoff_bound_alert_fields,
)
from packages.quantum.risk.mark_math import compute_current_value, finalize_mark, usable_mid

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


def _intraday_cohort_stop_enabled() -> bool:
    """INTRADAY_COHORT_STOP_ENABLED — default ON (empty/unset → ON; only an
    explicit 0/false/no/off disables — the #1038 convention). When on, the
    15-min monitor evaluates STOP-LOSS against the position's COHORT
    conditions (sl 0.15/0.20/0.30) instead of the global default (flat 0.50
    of entry_cost). Audit Area 7 (2026-06-09): cohort configs were loaded
    only inside the target_profit flag gate and used only for TP, so the
    binding cohort stops were checked just 2-3x/day by the scheduled sweeps
    (one of them pre-open at stale marks) — losers rode 94-143h while
    winners exited in 22-72h at <=15-min TP latency; the 06-08 shadow NFLX
    stops closed $211.80 past their configured thresholds at the Monday
    13:00Z sweep. Fail-safe is the legacy default conditions (looser stop —
    fires later, never wrongly). Read at call time for testability."""
    raw = os.environ.get("INTRADAY_COHORT_STOP_ENABLED", "")
    if not raw.strip():
        return True
    return raw.strip().lower() not in ("0", "false", "no", "off")

# Layer-1 exit mark-sanity gate (OBSERVE-ONLY, default OFF). When on, a
# mark-derived exit fire (target_profit / stop_loss) ALSO writes a
# corroboration verdict comparing the triggering mark vs the achievable
# close from live executable leg quotes — WITHOUT changing the exit. Read at
# call time (not pinned here) so the observe module owns the lenient parse;
# this constant is unused for gating and kept only for startup visibility.
# See analytics.exit_mark_corroboration. No enforcement is built (Stage-2).

# The market session, in the MARKET's timezone. Fallback for the broker-clock
# gate (_is_market_open) when the clock API is unavailable. America/New_York,
# 9:30-16:00 — NEVER Chicago numbers (the 2026-06-05 first-hour-blind bug was
# exactly the ET session transcribed as CT). DST-safe: the session is defined
# in ET, so computing in ET needs no offset arithmetic.
EASTERN_TZ = ZoneInfo("America/New_York")


def _mark_is_stale_fallback(pos: Dict[str, Any], now: Optional[datetime] = None) -> bool:
    """True when the position's persisted mark predates the CURRENT session
    open — i.e. the unrealized_pl a mark-derived exit would evaluate is
    yesterday's number (06-12: the values TP/stop consume when the fresh
    recompute fails come straight from the DB row).

    Boundary = today's 9:30 ET open (a pre-open mark — including a 13:15Z
    evaluator-refresh mark — is NOT a session price; the Area-7 finding's
    Monday 13:00Z sweep closed $211.80 past thresholds on exactly that).
    Missing last_marked_at → stale (no provenance = no trust).
    EXIT_STALE_MARK_MAX_AGE_MINUTES overrides with a pure age check."""
    raw = pos.get("last_marked_at")
    if not raw:
        return True
    try:
        ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=ZoneInfo("UTC"))
    except (ValueError, TypeError):
        return True
    now_et = (now or datetime.now(EASTERN_TZ)).astimezone(EASTERN_TZ)
    override = os.environ.get("EXIT_STALE_MARK_MAX_AGE_MINUTES", "").strip()
    if override:
        try:
            max_age = float(override) * 60.0
            return (now_et - ts.astimezone(EASTERN_TZ)).total_seconds() > max_age
        except ValueError:
            pass  # bad override → fall through to the session boundary
    session_open_et = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    return ts.astimezone(EASTERN_TZ) < session_open_et


def _fallback_is_market_open_et(now: Optional[datetime] = None) -> bool:
    """Correct wall-clock market-hours check in America/New_York (9:30-16:00
    ET, weekdays). Degraded mode only (no holiday/half-day awareness) — the
    primary gate is the Alpaca clock."""
    now_et = (now or datetime.now(EASTERN_TZ)).astimezone(EASTERN_TZ)
    if now_et.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
    return market_open <= now_et <= market_close

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
        # F-A4-1 (2026-07-11): do NOT swallow a fatal into an ok:False RETURN —
        # that is recorded 'succeeded' and is INVISIBLE (a protection cycle that
        # failed green). RAISE so the runner's exception path records it
        # (failed_retryable) and the A4/dashboard readers see it. The next q15
        # cron re-runs the monitor regardless.
        logger.error(f"[RISK_MONITOR] Fatal error: {e}", exc_info=True)
        raise


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
        #     target/expiration exits AND (post audit-Area-7) their own
        #     cohort-resolved stop_loss — before INTRADAY_COHORT_STOP_ENABLED
        #     this comment overclaimed: stops were evaluated at the global
        #     default 0.50, not the cohort values. This scopes the
        #     live-CAPITAL aggregate only; it does not blind any cohort to
        #     its own exits. NOTE: shadow books have no envelope backstop by
        #     design — the cohort stop IS their loss protection.
        _live_ids: set = set()
        _scope_ok = True
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
            _scope_ok = False

        # ── One-beta exposure TRIPWIRE (2026-07-08, meta-audit gap #3) ────
        # ADDITIVE ALARM ONLY — never blocks, closes, or mutates a position.
        # The real bucket-correlation control (B1/B2) is filed; until it
        # ships, nothing mechanical watches concurrent live exposure while
        # the allocator can select ≤4 candidates in one cycle. Fires a
        # critical (immediate-egress + receipt via _log_alert→alert()) at
        # ≥2 open LIVE-routed positions. Fail-isolated: a tripwire bug must
        # never touch the monitor's protective path.
        try:
            self._one_beta_tripwire(user_id, live_positions, _scope_ok)
        except Exception as _trip_err:
            logger.warning(
                f"[RISK_MONITOR] one-beta tripwire failed (non-fatal): {_trip_err}"
            )

        # 3. Compute portfolio metrics for envelope check (LIVE book).
        #     v5 phantom-mark-safe brake (2026-06-17 incident): the daily/weekly
        #     loss brake fires on realized (DB-authoritative, trusted, UN-GATED —
        #     preserves the #1058/06-11 realized protection) + executable-
        #     corroborated unrealized (#1034), NEVER the raw broker equity delta.
        #     On 06-17 a phantom broker unrealized of −285 on an incomplete-leg-
        #     quote window force-closed the live MARA whose executable close
        #     realized −15. Per-position stops (#1048) are unchanged. NOTE: the
        #     other tightened_daily_pnl consumers (MTM / autopilot breaker /
        #     midday) still share the phantom on their GATE paths (block/reduce,
        #     not force-close) — follow-up. get_alpaca_daily_pnl is now only the
        #     H10 cross-check below.
        _now = datetime.now(timezone.utc)
        _day_start = _now.replace(hour=0, minute=0, second=0, microsecond=0)
        _week_start = _day_start - timedelta(days=_day_start.weekday())  # Mon 00:00Z
        realized_today = equity_state.realized_pnl_since(
            self.supabase, user_id, _live_ids, _day_start.isoformat()
        )
        realized_week = equity_state.realized_pnl_since(
            self.supabase, user_id, _live_ids, _week_start.isoformat()
        )
        if (not _scope_ok) or realized_today is None or realized_week is None:
            # Fail SAFE: live-routing scope or the realized query is unavailable
            # this cycle — fall back to the legacy broker-true brake (errs
            # protective) rather than silently dropping realized protection.
            logger.warning(
                f"[RISK_MONITOR] user={user_id[:8]}: corroborated brake inputs "
                f"unavailable (scope_ok={_scope_ok}, realized_today={realized_today}, "
                f"realized_week={realized_week}) — legacy broker-true brake this cycle"
            )
            equity = self._estimate_equity(user_id, live_positions)
            daily_pnl_proxy = sum(float(p.get("unrealized_pl") or 0) for p in live_positions)
            daily_pnl = equity_state.tightened_daily_pnl(
                user_id, daily_pnl_proxy, supabase=self.supabase,
            )
            weekly_pnl = self._compute_weekly_pnl(user_id, daily_pnl)
        else:
            # Executable-corroborated unrealized over the OPEN live book, shared
            # by the daily + weekly horizons. Non-corroborated positions are
            # EXCLUDED + flagged (H9) — never priced off a phantom broker mark.
            corroborated_unreal, _uncorroborated = equity_state.corroborated_unrealized(
                live_positions
            )
            for _u in _uncorroborated:
                self._log_alert(
                    user_id=user_id,
                    alert_type="daily_brake_unrealized_uncorroborated",
                    severity="warning",
                    position_id=_u.get("position_id"),
                    symbol=_u.get("symbol"),
                    message=(
                        f"Daily/weekly brake EXCLUDED {_u.get('symbol')} "
                        f"({str(_u.get('position_id'))[:8]}) unrealized: executable "
                        f"side not corroborated ({_u.get('reason')}). Realized + the "
                        f"per-position stop still protect it."
                    ),
                )
            daily_pnl = realized_today + corroborated_unreal
            weekly_pnl = realized_week + corroborated_unreal
            # Clean %-denominator: last_equity + daily P&L, NOT the phantom-marked
            # live broker equity (the same bad mark depresses it, inflating the %).
            last_equity = equity_state.get_alpaca_last_equity(user_id, supabase=self.supabase)
            equity = (last_equity + daily_pnl) if last_equity is not None else None
            # H10 reconciliation cross-check (flag-only; no force-close effect).
            _recon = equity_state.reconcile_realized(
                user_id, realized_today, supabase=self.supabase
            )
            if _recon and _recon.get("divergent"):
                self._log_alert(
                    user_id=user_id,
                    alert_type="daily_brake_realized_reconcile_divergence",
                    severity="warning",
                    message=(
                        f"Realized reconcile divergence: broker-implied "
                        f"${_recon['broker_implied_realized']} vs DB "
                        f"${_recon['realized_db']} (diff ${_recon['diff']} > "
                        f"${_recon['threshold']}); brake uses DB realized (H10)."
                    ),
                    metadata=_recon,
                )

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

        # Per-position exit-trigger corroboration (#1035/#1036 triggers 2+3):
        # the per-symbol loss force-close (loss_per_symbol) and the cohort stop
        # decide on the EXECUTABLE-corroborated mark, not the raw/mid
        # unrealized_pl that on an incomplete-leg-quote window is a leg-skew
        # phantom (06-17 MARA). Reuses THIS cycle's already-fetched leg quotes
        # (the shared 60s snapshot cache _refresh_marks populated — no extra
        # fetch). Per-position FAIL-SAFE: uncorroborable → raw mark, fire-if-past
        # (NEVER a suppressor), exactly as #1071/#1079. _mark_unpriceable
        # positions keep the existing #1035 skip (check_loss_envelopes + the
        # cohort guards read the preserved flag). live_positions corroborated
        # separately so the scope-failed fallback (live_positions = positions)
        # is preserved.
        _corr_positions = self._corroborate_exit_marks(positions)
        _corr_live_positions = self._corroborate_exit_marks(live_positions)

        # 4. Run envelope check (LIVE book only — see 2b)
        config = EnvelopeConfig.from_env()
        result = check_all_envelopes(
            positions=_corr_live_positions,
            equity=equity,
            daily_pnl=daily_pnl,
            weekly_pnl=weekly_pnl,
            config=config,
        )

        # 4a. loss_per_symbol degraded protection — LOUD, not silent (#1035
        # asymmetric policy extended to the envelope). Positions whose mark was
        # unpriceable this pass were SKIPPED from the per-symbol loss decision
        # (not force-closed on a stale value, not silently coerced to no-breach).
        self._alert_loss_per_symbol_degraded(result, user_id)

        # 4b. Check position-level exit conditions (stop loss, expiration)
        #     The envelope check above handles portfolio-level limits.
        #     This catches individual positions that hit their own stop/expiry
        #     between the scheduled 8:15 AM / 3:00 PM exit evaluations.
        #     Runs over the FULL managed set (not just live) so shadow cohorts
        #     keep their own intraday exits (2b).
        exit_triggered = self._collect_intraday_exit_triggers(_corr_positions, user_id)

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
                # A stop is a stop (06-12): cohort stop_loss closes bench the
                # symbol exactly like per-symbol envelope stops. #1040's
                # writer covered only result.symbol_loss_stops — the 06-12
                # SPY cohort stop closed at 15:30Z and was re-rankable at the
                # 16:00Z scan (manually benched that day; this makes it
                # permanent). target_profit/expiration do NOT bench.
                if reason == "stop_loss":
                    self._write_cohort_stop_cooldown(pos, user_id)

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
                    # Warn-only mode for non-loss envelopes. A9-F1 2026-07-07:
                    # was alert_type="force_close" severity=critical — a
                    # nothing-was-closed row wearing the real force-close's
                    # costume (31% of historical force_close rows). Honest
                    # type + high (visible in every H11 sweep, no false
                    # "position closed" scare).
                    self._log_alert(
                        user_id=user_id,
                        alert_type="envelope_violation_warn_only",
                        severity="high",
                        message=f"[WARN-ONLY] {violation.message} (enforcement disabled)",
                        position_id=None,
                        symbol=None,
                        metadata=violation.to_dict(),
                    )
                    warnings_logged += 1
            elif violation.severity in ("warn", "block"):
                # A9-F2/F7 2026-07-07: was the untyped 'warn' alert type at
                # severity high|medium — a costume plus a severity outside
                # the vocabulary ('medium' is invisible to severity='warning'
                # filters). Envelope name rides in metadata.envelope.
                self._log_alert(
                    user_id=user_id,
                    alert_type="envelope_violation",
                    severity="high" if violation.severity == "block" else "warning",
                    message=violation.message,
                    metadata=violation.to_dict(),
                )
                warnings_logged += 1

        # 5c. Re-entry cooldown WRITER (Option B, intent-based). For each
        # PER-SYMBOL loss-envelope stop this pass (the structured
        # result.symbol_loss_stops — never daily/weekly/concentration), bench
        # (cohort_id, symbol) until next session open so the scanner can't
        # re-rank/re-enter the symbol it just stopped (the 2026-06-08 NFLX
        # whipsaw). Written at the stop DECISION (independent of fill); loud on
        # failure; the stop itself is never rolled back.
        self._write_reentry_cooldowns(result, user_id)

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
        """Return True if the market is open — broker-authoritative.

        HISTORY (2026-06-05 detection-failure diagnostic): this used a
        wall-clock window of 9:30-16:00 in CHICAGO time — the ET session
        transcribed as CT numbers — so the effective window was
        14:30-21:00Z instead of the real 13:30-20:00Z. The monitor was
        BLIND for the first hour of every session (the −$202 NFLX
        excursion happened unseen in that window) and ran a phantom hour
        after the close. Now: Alpaca's get_clock() (which also knows
        holidays and half-days), with a CORRECT America/New_York
        wall-clock fallback — never the old CT numbers — so the monitor
        stays live through clock-API outages (degraded mode loses only
        holiday awareness).
        """
        # Short TTL cache: one clock call per cycle, not per check.
        now_mono = time.monotonic()
        cached = getattr(self, "_clock_cache", None)
        if cached and (now_mono - cached[0]) < 60:
            return cached[1]

        try:
            from packages.quantum.brokers.alpaca_client import get_alpaca_client
            clock = get_alpaca_client().get_market_clock()
            is_open = bool(clock["is_open"])
            logger.info(
                f"[RISK_MONITOR] market-hours gate: Alpaca clock is_open={is_open} "
                f"next_open={clock.get('next_open')} next_close={clock.get('next_close')}"
            )
            self._clock_cache = (now_mono, is_open)
            return is_open
        except Exception as e:
            is_open = _fallback_is_market_open_et()
            logger.warning(
                f"[RISK_MONITOR] market-hours gate: Alpaca clock unavailable "
                f"({type(e).__name__}) — ET wall-clock fallback says "
                f"is_open={is_open} (degraded: no holiday awareness)"
            )
            self._clock_cache = (now_mono, is_open)
            return is_open

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
        # Part-B companion (fresh-mark close fix): positions whose marks were
        # successfully recomputed this cycle — persisted back to the DB below
        # so current_mark is 15-min fresh for ALL consumers (dashboards, the
        # 2026-06-04 DB-vs-broker divergence). The CLOSE fix itself does NOT
        # depend on this persist — _execute_force_close passes the in-memory
        # mark directly (robust to persist failures). Belt-and-suspenders.
        refreshed_positions: List[Dict] = []

        # Update positions with fresh marks
        for pos in positions:
            legs = pos.get("legs") or []

            # Shared mid resolver over the pre-fetched snapshots (used for both
            # the leg-less and multi-leg paths via risk.mark_math).
            def _mid_for(sym: str) -> Optional[float]:
                snap = snapshots.get(normalize_symbol(sym), {})
                q = snap.get("quote", snap)
                # usable_mid (06-12): a degenerately wide quote (the 13:30Z
                # C750 0.76×14.09) returns None → failed leg → all-or-nothing
                # unpriceable, never a fabricated mark.
                return usable_mid(
                    q.get("bid"), q.get("ask"), float(q.get("mid") or 0)
                )

            if not legs:
                mid = _mid_for(pos.get("symbol", ""))
                if mid is not None and mid > 0:
                    qty_signed = float(pos.get("quantity") or 1)
                    current_value = mid * 100 * abs(qty_signed)
                    # #3 unification: single shared full-count finalize (H13).
                    pos["current_mark"], pos["unrealized_pl"] = finalize_mark(
                        qty_signed, pos.get("avg_entry_price"), current_value
                    )
                    pos["_mark_fresh"] = True
                    refreshed_positions.append(pos)
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
            # NEVER FABRICATE (mirrors the #1034 gate fix): pass failed_legs so
            # a leg that can't price makes compute_current_value all-or-nothing
            # None — NOT a partial sum over only the priceable legs. The
            # partial-sum was the 2026-06-08 phantom ROOT: at the open one NFLX
            # leg quoted 0.0, was silently DROPPED, and the surviving leg's
            # value finalized to a fabricated +$325 mark the spread never held
            # (real achievable ~−$36) → target_profit fired on a phantom. The
            # else-branch comment below long CLAIMED an all-or-nothing
            # short-circuit but, without failed_legs, never delivered it (the
            # None path only fired when EVERY leg was unpriceable). Now any one
            # dead leg → None → the unpriceable path.
            _failed_legs: List[str] = []
            current_value = compute_current_value(
                legs, _mid_for, pos.get("quantity"), failed_legs=_failed_legs
            )

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
                pos["_mark_fresh"] = True
                refreshed_positions.append(pos)
            else:
                # Multi-leg recompute short-circuited: at least one leg could
                # not be priced this pass (failed_legs non-empty → all-or-
                # nothing None, post the 2026-06-08 fix above). The position
                # retains its DB-stale unrealized_pl, but we now FLAG it
                # unpriceable so the exit-trigger collection refuses to act on
                # a value it cannot corroborate this pass (target_profit never
                # fires; stop_loss raises a loud degraded-protection alert
                # instead of firing on a stale/fabricated mark). Recorded here +
                # alerted loudly after the loop (mtm_refresh_partial).
                pos["_mark_unpriceable"] = True
                skipped_positions.append({
                    "position_id": pos.get("id"),
                    "symbol": pos.get("symbol"),
                    "leg_count": len([l for l in legs if isinstance(l, dict)]),
                    "failed_legs": list(_failed_legs),
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

        # Part-B companion: persist the fresh marks so DB current_mark is
        # 15-min fresh for every consumer (pre-fix it was only written by the
        # scheduled jobs at 13:15Z/20:00Z/20:30Z → up to ~6.5h stale; the
        # 2026-06-04 DB-vs-broker divergence: DB +$52 vs broker −$34).
        # FAIL-SOFT: a write failure must never break the eval or the close —
        # both use the in-memory marks. Last-writer-wins vs the daily MTM job
        # is correct (freshest wins; single-row update is atomic).
        from packages.quantum.analytics.exit_mark_corroboration import (
            corroborated_mark_fields,
        )

        for pos in refreshed_positions:
            try:
                # P1-C (07-02): persist corroboration alongside the raw mark
                # (ADDITIVE — in-memory marks, envelopes, and exit triggers
                # are untouched; #1079/#1080 already corroborate decisions).
                # snapshot_fn reuses THIS cycle's pre-fetched snapshots —
                # zero extra API calls. Incomplete → NULLs + stamp, never
                # fabricated.
                corro = corroborated_mark_fields(
                    pos,
                    snapshot_fn=lambda occs: snapshots,
                    raw_mark=pos.get("current_mark"),
                )
                self.supabase.table("paper_positions").update({
                    "current_mark": pos.get("current_mark"),
                    "unrealized_pl": pos.get("unrealized_pl"),
                    # False-ager fix (2026-07-08): this path MARKS the
                    # position — stamp the provenance field it was starving.
                    # Pre-fix only the scheduled MTM stamped last_marked_at,
                    # so OUTPUT_FRESHNESS false-aged paper_positions past its
                    # 168h ceiling (7× ops_output_stale highs today) and the
                    # stale-mark exit guard saw q15min marks as provenance-less.
                    "last_marked_at": datetime.now(timezone.utc).isoformat(),
                    **corro,
                }).eq("id", pos.get("id")).execute()
            except Exception as persist_err:
                logger.warning(
                    f"[RISK_MONITOR] fresh-mark persist failed (non-fatal) "
                    f"position={str(pos.get('id'))[:8]}: {persist_err}"
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

    def _write_reentry_cooldowns(self, result, user_id: str) -> int:
        """Bench each per-symbol loss-envelope stop (cohort_id, symbol) until
        next session open — the re-entry cooldown WRITER (Option B, intent at
        the stop decision). Gated on result.symbol_loss_stops (the structured
        per-symbol breaches only). Fail-loud per symbol; never rolls back the
        stop. Returns the number of cooldown rows written."""
        from packages.quantum.services import reentry_cooldown as rc
        if not rc.is_enabled():
            return 0
        stops = getattr(result, "symbol_loss_stops", None) or []
        if not stops:
            return 0
        cooldown_until = rc.compute_cooldown_until()  # fail-closed inside
        written = 0
        for stop in stops:
            try:
                if rc.write_cooldown(
                    self.supabase,
                    cohort_id=stop.get("cohort_id"),
                    symbol=stop.get("symbol"),
                    cooldown_until=cooldown_until,
                    reason=rc.COOLDOWN_REASON,
                    triggering_position_id=stop.get("position_id"),
                    realized_loss=stop.get("realized_loss"),
                ):
                    written += 1
            except Exception as e:  # never let cooldown-writing break the cycle
                logger.critical(
                    "[RISK_MONITOR] reentry cooldown write raised for %s "
                    "(non-fatal; stop unaffected): %s", stop.get("symbol"), e,
                )
        return written

    def _write_cohort_stop_cooldown(self, pos: Dict, user_id: str) -> bool:
        """#1040 extension (06-12): a COHORT stop_loss force-close writes the
        same reentry_cooldowns row as a per-symbol envelope stop — same
        duration convention (next session open via compute_cooldown_until),
        reason 'cohort_stop_force_close'. Fail-loud per symbol; never rolls
        back the stop itself."""
        from packages.quantum.services import reentry_cooldown as rc
        if not rc.is_enabled():
            return False
        try:
            return bool(rc.write_cooldown(
                self.supabase,
                cohort_id=pos.get("cohort_id"),
                symbol=pos.get("symbol"),
                cooldown_until=rc.compute_cooldown_until(),
                reason="cohort_stop_force_close",
                triggering_position_id=pos.get("id"),
                realized_loss=float(pos.get("unrealized_pl") or 0),
            ))
        except Exception as e:  # never let cooldown-writing break the stop
            logger.critical(
                "[RISK_MONITOR] cohort-stop cooldown write raised for %s "
                "(non-fatal; stop unaffected): %s", pos.get("symbol"), e,
            )
            return False

    def _alert_loss_per_symbol_degraded(self, result, user_id: str) -> int:
        """Raise a loud high-severity alert for each position whose per-symbol
        loss could not be evaluated this pass (unpriceable mark). Returns the
        count alerted. Protection resumes next pass when quotes return; Stage-2
        is last-good / conservative / marketable. (#1035 asymmetric policy
        extended to the loss_per_symbol envelope.)"""
        n = 0
        for _deg in (getattr(result, "degraded_per_symbol", None) or []):
            self._log_alert(
                user_id=user_id,
                alert_type="loss_per_symbol_protection_degraded",
                severity="high",
                message=(
                    f"loss_per_symbol protection degraded for "
                    f"{_deg.get('symbol')}: position could not be priced this "
                    f"pass (unmarkable leg quotes) — NOT acting on a stale mark; "
                    f"will retry next pass when quotes return"
                ),
                position_id=_deg.get("position_id"),
                symbol=_deg.get("symbol"),
                metadata={
                    "stale_unrealized_pl": _deg.get("stale_unrealized_pl"),
                    "envelope": "loss_per_symbol",
                    "consequence": (
                        "Per-symbol loss envelope not evaluated this pass "
                        "(mark uncorroborated). Protection resumes next pass. "
                        "Stage-2: last-good / conservative / marketable close."
                    ),
                    "doctrine_ref": "H9 loud-not-silent; never act on a "
                                    "fabricated/uncorroborated mark",
                },
            )
            n += 1
        return n

    def _corroborate_exit_marks(self, positions: List[Dict]) -> List[Dict]:
        """Return ``positions`` with ``unrealized_pl`` replaced by the executable-
        corroborated decision P&L (#1035/#1036) for the per-position exit triggers
        — the per-symbol loss force-close (``loss_per_symbol``) and the cohort
        stop — so they fire on the position's TRUE value, not a raw/mid phantom.

        Reuses THIS cycle's leg quotes: ``corroborated_exit_upl`` reads the shared
        60s snapshot cache that ``_refresh_marks`` already populated this pass, so
        there is NO extra fetch and no added cadence latency. Per-position
        FAIL-SAFE: an uncorroborable position keeps its RAW mark (fire-if-past),
        never suppressed. Non-mutating (``{**p}``); all other fields (greeks,
        sector, ``_mark_unpriceable``, ``portfolio_id``) are preserved unchanged,
        so the existing envelope/cohort guards (incl. the #1035 unpriceable skip)
        and the greeks/concentration/stress checks behave exactly as before. Each
        raw-fallback is logged so the fallback is never silent."""
        if not positions:
            return positions
        from packages.quantum.analytics import exit_mark_corroboration as _emc
        out: List[Dict] = []
        for p in positions:
            # snapshot_fn=None → default truth layer → the shared 60s cache this
            # cycle's _refresh_marks already filled (cache hit, no fetch).
            upl, basis = _emc.corroborated_exit_upl(p)
            if basis != "corroborated":
                logger.info(
                    "[EXIT_CORROBORATE] monitor %s (%s): raw-fallback (%s) — "
                    "loss_per_symbol/cohort-stop on the raw mark upl=%s, "
                    "fire-if-past (never suppressed)",
                    p.get("symbol"), str(p.get("id"))[:8], basis, upl,
                )
            out.append({**p, "unrealized_pl": upl})
        return out

    def _collect_intraday_exit_triggers(self, positions: List[Dict], user_id: str) -> List:
        """Collect position-level intraday exit triggers as (position, reason) pairs.

        - stop_loss (INTRADAY_COHORT_STOP_ENABLED, default ON): evaluated against
          the position's COHORT conditions at monitor cadence — the same
          build_exit_conditions the scheduled evaluator uses (H13: no parallel
          decision logic). Before audit Area 7 the cohort build lived inside the
          target_profit flag gate and only TP consumed it, so stops ran at the
          global default (flat 0.50 of entry_cost) and the binding cohort stops
          (0.15/0.20/0.30) were checked only 2-3x/day by the scheduled sweeps.
          Flag off / load failure → legacy default conditions (a LOOSER stop —
          the fail-safe can only delay a stop to today's behavior, never fire
          a wrong one).
        - expiration_day: date-derived, identical under either condition set.
        - target_profit (flag-gated, _INTRADAY_TARGET_PROFIT_ENABLED): the profit-
          side mirror, cohort-resolved as before. Marks are the post-#3 unified
          full-count values (risk.mark_math).

        Fail-safe: if per-cohort params can't be resolved, target_profit is NOT
        acted on (better to wait for the scheduled run than act on a wrong
        threshold) and stop_loss falls back to the default conditions.
        """
        from packages.quantum.services.paper_exit_evaluator import (
            evaluate_position_exit,
            EXIT_CONDITIONS,
            build_exit_conditions,
            PaperExitEvaluator,
        )

        tp_active = _INTRADAY_TARGET_PROFIT_ENABLED
        cohort_stop_active = _intraday_cohort_stop_enabled()
        cohort_conditions: Dict[str, Any] = {}
        cohort_evaluator = None
        if tp_active or cohort_stop_active:
            try:
                from packages.quantum.policy_lab.config import load_cohort_configs
                cohort_evaluator = PaperExitEvaluator(self.supabase)
                for _cn, _cfg in (load_cohort_configs(user_id, self.supabase) or {}).items():
                    cohort_conditions[_cn] = build_exit_conditions(
                        target_profit_pct=_cfg.target_profit_pct,
                        stop_loss_pct=_cfg.stop_loss_pct,
                        min_dte_to_exit=_cfg.min_dte_to_exit,
                    )
            except Exception as e:
                logger.warning(
                    f"[RISK_MONITOR] intraday cohort-conditions load failed "
                    f"(non-fatal; target_profit not acted on this cycle, "
                    f"stop_loss falls back to default conditions): {e}"
                )
                tp_active = False
                cohort_conditions = {}
                cohort_evaluator = None

        exit_triggered = []
        for pos in positions:
            # ASYMMETRIC fail-closed handling of an unpriceable mark (positions
            # whose legs could not be priced this pass — flagged in
            # _refresh_marks). A mark we can't corroborate must NOT drive a
            # mark-derived exit (the 2026-06-08 phantom lesson):
            #   • target_profit → NEVER fires (you cannot confirm a profit on a
            #     position you cannot price; this kills the opening-transient
            #     phantom at its source).
            #   • stop_loss → does NOT act on the stale/uncorroborated value;
            #     raises a LOUD H9 alert that protection is degraded this pass,
            #     then relies on the next pass when quotes return. Strictly
            #     better than acting on a fabricated mark that could MASK a real
            #     loss behind a phantom profit.
            #   • expiration_day → date-derived, UNAFFECTED (a calendar date is
            #     real regardless of quotes).
            # Stage-2 (NOT decided here): a robust unpriceable-stop policy —
            # last-good mark / conservative bound / marketable protective close
            # — would let stop_loss still protect without a live mark. Do not
            # silently weaken the stop in the meantime; alert and retry.
            # ── Structural mark-validity clamp (06-15) ────────────────────
            # Reject an IMPOSSIBLE composed mark BEFORE any exit condition
            # evaluates, regardless of how it was produced — fresh compute OR
            # a DB-stale fallback. The 13:30Z QQQ phantom (mark −7.305 /
            # implied −$569.50 on a 5-wide / 1.61cr condor, max loss $339)
            # drove a stop the per-leg degenerate-quote rejector did NOT stop,
            # because the −7.305 came from the DB fallback, not the compute
            # path. This composed-structure clamp closes that exact gap. On
            # reject: treat as unpriceable for this cycle (the existing
            # fail-closed posture — TP never fires, stop alerts degraded,
            # NEVER suppresses a real stop), loud [STRUCT_CLAMP] + alert. A
            # real near-max mark (e.g. −$330 < max $339) is NOT rejected.
            try:
                from packages.quantum.risk.mark_validity import (
                    validate_structure_mark,
                )
                _clamp_ok, _clamp_reason, _clamp_detail = validate_structure_mark(pos)
                if not _clamp_ok:
                    pos["_mark_unpriceable"] = True
                    pos["_struct_clamp_rejected"] = True
                    logger.critical(
                        "[STRUCT_CLAMP] %s (%s) impossible mark rejected "
                        "(%s): %s — treated unpriceable this cycle, NOT acted on",
                        pos.get("symbol"), str(pos.get("id"))[:8],
                        _clamp_reason, _clamp_detail,
                    )
                    self._log_alert(
                        user_id=user_id,
                        alert_type="struct_clamp_rejected",
                        severity="high",
                        message=(
                            f"Structural mark clamp rejected impossible mark "
                            f"for {pos.get('symbol')}: {_clamp_reason} "
                            f"(mark={_clamp_detail.get('per_contract_mark')}, "
                            f"wing={_clamp_detail.get('wing_width')}, "
                            f"implied_pl={_clamp_detail.get('implied_pl')}, "
                            f"max_loss=${_clamp_detail.get('max_loss_dollars')})"
                        ),
                        position_id=pos.get("id"),
                        symbol=pos.get("symbol"),
                        metadata={
                            **_clamp_detail,
                            "reason": _clamp_reason,
                            "consequence": (
                                "Mark is structurally impossible; no exit "
                                "evaluated this cycle. Re-evaluates next cycle "
                                "with a sane mark. A REAL stop is never "
                                "suppressed — only impossible marks are."
                            ),
                            "doctrine_ref": "stop-side analogue of #1034 "
                                            "Stage-2; never suppress a real stop",
                        },
                    )
            except Exception as _clamp_err:  # never let the clamp break exits
                logger.warning(
                    f"[STRUCT_CLAMP] validation raised (non-fatal; exit "
                    f"proceeds) for {pos.get('symbol')}: {_clamp_err}"
                )

            unpriceable = bool(pos.get("_mark_unpriceable"))

            # Stale-fallback guard (06-12): a position that did NOT get a
            # fresh mark this pass (no _mark_fresh) and whose persisted mark
            # predates the current session is carrying YESTERDAY's numbers —
            # mark-derived exits must not fire on them. Treated exactly like
            # unpriceable (TP never fires; stop_loss alerts degraded, never
            # acts). Belt to the usable_mid degenerate-quote fix: this
            # covers the refresh-failed-silently / overnight-stale residue.
            if not unpriceable and not pos.get("_mark_fresh"):
                if _mark_is_stale_fallback(pos):
                    logger.warning(
                        f"[RISK_MONITOR] exit-eval STALE-MARK GUARD: "
                        f"{pos.get('symbol')} ({str(pos.get('id'))[:8]}) has no "
                        f"fresh mark this pass and last_marked_at="
                        f"{pos.get('last_marked_at')!r} predates the session "
                        f"open — mark-derived exits skipped this cycle"
                    )
                    self._log_alert(
                        user_id=user_id,
                        alert_type="stale_mark_exit_guard",
                        severity="warning",
                        message=(
                            f"Exit evaluation skipped for {pos.get('symbol')}: "
                            f"only available mark predates the current session "
                            f"(last_marked_at={pos.get('last_marked_at')}). "
                            f"TP/stop not evaluated; expiration unaffected."
                        ),
                        position_id=pos.get("id"),
                        symbol=pos.get("symbol"),
                        metadata={
                            "stale_unrealized_pl": float(pos.get("unrealized_pl") or 0),
                            "last_marked_at": str(pos.get("last_marked_at")),
                            "consequence": (
                                "Stale numbers cannot fire TP/stop this pass. "
                                "If this persists across cycles the quote layer "
                                "is degraded — investigate."
                            ),
                        },
                    )
                    unpriceable = True

            # Resolve this position's cohort conditions ONCE — consumed by
            # both the stop evaluation (when cohort_stop_active) and the
            # target_profit branch below. Resolution failure → default
            # conditions (looser stop = today's behavior; never a misfire).
            conds = EXIT_CONDITIONS
            if cohort_conditions and cohort_evaluator is not None:
                try:
                    _cohort = cohort_evaluator._resolve_position_cohort(pos)
                    conds = cohort_conditions.get(_cohort) or EXIT_CONDITIONS
                except Exception as e:
                    logger.warning(
                        f"[RISK_MONITOR] cohort resolution failed for "
                        f"{pos.get('id')} (default conditions this pass): {e}"
                    )
                    conds = EXIT_CONDITIONS

            stop_conds = conds if cohort_stop_active else EXIT_CONDITIONS
            reason = evaluate_position_exit(pos, conditions=stop_conds)

            if reason == "expiration_day":
                exit_triggered.append((pos, reason))
                continue
            if reason == "stop_loss":
                if unpriceable:
                    self._log_alert(
                        user_id=user_id,
                        alert_type="stop_loss_protection_degraded",
                        severity="high",
                        message=(
                            f"stop_loss protection degraded for "
                            f"{pos.get('symbol')}: position could not be priced "
                            f"this pass (unmarkable leg quotes) — NOT acting on "
                            f"the stale mark; will retry next pass when quotes "
                            f"return"
                        ),
                        position_id=pos.get("id"),
                        symbol=pos.get("symbol"),
                        metadata={
                            "stale_unrealized_pl": float(pos.get("unrealized_pl") or 0),
                            "consequence": (
                                "Per-position stop_loss not evaluated this pass "
                                "(mark uncorroborated). Protection resumes next "
                                "pass when leg quotes return. Stage-2: last-good "
                                "/ conservative / marketable protective close."
                            ),
                            "doctrine_ref": "H9 loud-not-silent; never act on a "
                                            "fabricated/uncorroborated mark",
                        },
                    )
                    continue
                exit_triggered.append((pos, reason))
                continue  # stop/expiry take priority; a position can't also be at +target

            # target_profit — NEVER on an unpriceable mark. Uses the SAME
            # cohort conditions resolved above (one resolution per position).
            if tp_active and not unpriceable:
                try:
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
                .select("id, status, created_at, cancelled_at, order_json") \
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
            # the resting GTC at the broker before submitting. STALE
            # terminal-failed ('cancelled') attempts no longer block either
            # — the close-retry re-arm semantics (see the helper in
            # paper_exit_evaluator).
            from packages.quantum.services.paper_exit_evaluator import (
                filter_blocking_close_orders,
            )
            _blocking = filter_blocking_close_orders(
                existing.data or [],
                supabase=self.supabase,
                position_id=pos_id,
                symbol=symbol,
            )
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

            # Evaluate-fresh / execute-fresh: pass the EXACT in-memory mark
            # this cycle's decision used (_refresh_marks), so the close limit
            # is staged from the same observation that triggered it — NOT the
            # DB current_mark, which is only persisted by the scheduled jobs
            # and can be ~6.5h stale (2026-06-04: BAC detected >=+$255 fresh,
            # closed at the stale $3.03 -> +$192; loss-side a stale limit
            # stages ABOVE a falling market and never fills). GUARD: only a
            # valid finite >0 fresh mark is passed; if this position's
            # refresh degraded (incomplete leg quotes -> mtm_refresh_partial),
            # fall back to the legacy DB read and LOG it — never fabricate,
            # never use a third number. Invariant: the order uses the SAME
            # mark the decision used (fresh when fresh is good).
            import math
            _fresh_mark = position.get("current_mark")
            try:
                _fresh_mark = float(_fresh_mark)
                _mark_ok = math.isfinite(_fresh_mark) and _fresh_mark > 0
            except (TypeError, ValueError):
                _mark_ok = False
            if not _mark_ok:
                logger.warning(
                    f"[RISK_MONITOR] fresh mark unavailable/degraded for "
                    f"{symbol} ({pos_id[:8]}) — close falls back to DB "
                    f"current_mark (mark={position.get('current_mark')!r})"
                )

            # ── Layer-1 exit mark-sanity gate (Stage-2 capable) ───────────
            # For mark-derived fires (target_profit / stop_loss) ONLY, record
            # a corroboration verdict comparing the mark we're about to stage
            # against the achievable close from live executable leg quotes.
            # Stage-1 (observe): writes a row, changes nothing. Stage-2
            # (EXIT_MARK_SANITY_ENFORCE_ENABLED, default OFF): a TARGET_PROFIT
            # fire whose row says would_suppress=true is SUPPRESSED — the row
            # is still written as the evidence trail. stop_loss is NEVER
            # suppressed: compute_corroboration forces would_suppress=False
            # for it, and this branch additionally fires only for
            # target_profit (double asymmetry guard). Fail-safe is preserved:
            # observe_exit_mark forces would_suppress=False on any
            # corroboration error, and any exception here lets the exit
            # proceed unchanged (a gate bug can never stop a protective exit;
            # the 2026-06-08 phantom-mark learning loop).
            _gate_exit_type = None
            if reason == "intraday_target_profit":
                _gate_exit_type = "target_profit"
            elif reason == "intraday_stop_loss":
                _gate_exit_type = "stop_loss"
            if _gate_exit_type is not None:
                try:
                    from packages.quantum.analytics import exit_mark_corroboration as _emc
                    _enforce = _emc.is_enforce_enabled()
                    if _emc.is_observe_enabled() or _enforce:
                        _gate_row = _emc.observe_exit_mark(
                            self.supabase,
                            position=position,
                            exit_type=_gate_exit_type,
                            triggering_mark=_fresh_mark if _mark_ok else position.get("current_mark"),
                            triggering_implied_pl=float(position.get("unrealized_pl") or 0),
                            job_run_id=getattr(self, "job_run_id", None),
                            user_id=user_id,
                        )
                        if (
                            _enforce
                            and _gate_exit_type == "target_profit"
                            and isinstance(_gate_row, dict)
                            and _gate_row.get("would_suppress") is True
                        ):
                            logger.warning(
                                f"[RISK_MONITOR] TARGET_PROFIT SUPPRESSED for "
                                f"{symbol} ({pos_id[:8]}): mark not corroborated "
                                f"on the executable side "
                                f"(reason={_gate_row.get('suppress_reason')}, "
                                f"trigger={_gate_row.get('triggering_mark')}, "
                                f"achievable={_gate_row.get('achievable_close')}, "
                                f"frac={_gate_row.get('divergence_frac')}) — "
                                f"no close staged; re-evaluates next cycle"
                            )
                            self._log_alert(
                                user_id=user_id,
                                alert_type="exit_tp_suppressed_phantom_mark",
                                severity="high",
                                message=(
                                    f"Suppressed target_profit close for {symbol}: "
                                    f"triggering mark "
                                    f"{_gate_row.get('triggering_mark')} not "
                                    f"corroborated (achievable "
                                    f"{_gate_row.get('achievable_close')}, "
                                    f"{_gate_row.get('suppress_reason')})"
                                ),
                                position_id=pos_id,
                                symbol=symbol,
                                metadata={
                                    "suppress_reason": _gate_row.get("suppress_reason"),
                                    "divergence_frac": _gate_row.get("divergence_frac"),
                                    "consequence": (
                                        "No close order staged on the phantom "
                                        "mark. Position re-evaluates next cycle "
                                        "with fresh quotes; a real profit "
                                        "corroborates and proceeds."
                                    ),
                                },
                            )
                            return False
                except Exception as _gate_err:
                    logger.warning(
                        f"[RISK_MONITOR] exit mark-sanity gate failed "
                        f"(non-fatal; exit proceeds): {_gate_err}"
                    )

            result = evaluator._close_position(
                user_id=user_id,
                position_id=pos_id,
                reason=_close_reason_arg,
                exit_price_override=_fresh_mark if _mark_ok else None,
            )

            # CLOSE_QUOTE_VALIDATION (Phase 2): a DEFER means the close was NOT
            # staged (executable side uncorroborated — leg dark) and the position
            # is still OPEN. Treat as not-closed: no "Force-closed" critical (the
            # close gate already emitted close_stage_uncorroborated + any
            # escalation), no force_close count, and — critically — no symbol
            # bench (a deferred stop must not cooldown a position that never
            # closed). The monitor re-evaluates next cycle.
            # P0-A (2026-07-10): a LIVE close that could not confirm a broker
            # fill returns 'unknown_reconciling' — position still OPEN, never
            # internally filled. Treat exactly like a deferred close: NOT closed,
            # no "Force-closed" success critical, no cooldown bench (a close that
            # never completed must not bench the symbol). force_close_failed
            # already fired inside _close_position; the reconciler/operator
            # resolves it. Counting only a COMPLETED close as success fixes the
            # :1428 success-costume (internal-fill fallthrough is now impossible
            # for live).
            _rt_p0a = (result or {}).get("routed_to")
            if _rt_p0a in ("deferred_uncorroborated", "unknown_reconciling"):
                logger.warning(
                    f"[RISK_MONITOR] close NOT completed ({_rt_p0a}) for {symbol} "
                    f"({str(pos_id)[:8]}) reason={reason} — position held OPEN, "
                    f"re-eval next cycle"
                )
                return False

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
            # A9-F1 2026-07-07: was alert_type="force_close" — the FAILED
            # submit shared the successful close's type. Split type; on the
            # immediate-egress allowlist (a position still open on a breached
            # control must reach the operator now, not at the relay poll).
            self._log_alert(
                user_id=user_id,
                alert_type="force_close_failed",
                severity="critical",
                message=f"Force close FAILED for {symbol}: {e} — retrying next cycle",
                position_id=pos_id,
                symbol=symbol,
                metadata={"error": str(e)},
            )
            return False

    # ── One-beta exposure tripwire (meta-audit gap #3, 2026-07-08) ────

    def _one_beta_tripwire(
        self, user_id: str, live_positions: List[Dict], scope_ok: bool
    ) -> None:
        """ALARM — never act — when ≥2 LIVE-routed positions are open while
        the bucket-correlation control (B1/B2) remains unbuilt.

        Simplest-correct version (owner decision 07-08): ANY 2 concurrent
        live positions is the uncontrolled case at this account size —
        per-bucket refinement is B1/B2's job, deliberately not built here.
        Semantics: alarm-on-onset, deduped on the sorted open-position-id
        SET — an unchanged standing pair does NOT re-alarm every q15 cycle;
        a 3rd position (new set) re-alarms. Skips when the live-routing
        scope query failed this cycle (counting shadows would be noise; the
        scope failure already warned loudly and the next clean cycle
        re-evaluates). Flag CONCURRENT_POSITION_ALARM_ENABLED default-ON
        (safety polarity: unset/empty → ON; only explicit falsy disables).
        This method READS risk_alerts and emits via _log_alert — it never
        writes positions, orders, or ops_control.
        """
        raw = (
            os.environ.get("CONCURRENT_POSITION_ALARM_ENABLED") or ""
        ).strip().lower()
        if raw in ("0", "false", "no", "off"):
            return
        if not scope_ok:
            return
        open_live = [
            p for p in live_positions
            if str(p.get("status") or "open").lower() == "open"
        ]
        if len(open_live) < 2:
            return
        position_set = ",".join(sorted(str(p.get("id")) for p in open_live))
        symbols = sorted({str(p.get("symbol")) for p in open_live})
        # Onset dedup: one alarm per distinct open-set (7-day window so an
        # ancient identical set can never suppress a fresh onset).
        try:
            recent = (
                self.supabase.table("risk_alerts")
                .select("id, metadata")
                .eq("alert_type", "concurrent_live_positions_uncontrolled")
                .gte(
                    "created_at",
                    (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(),
                )
                .limit(20)
                .execute()
            )
            for row in (recent.data or []):
                meta = row.get("metadata") or {}
                if isinstance(meta, dict) and meta.get("position_set") == position_set:
                    return  # this exact exposure set already alarmed
        except Exception as dedup_err:
            # Dedup read failure → alarm anyway (fail-toward-alarming; a
            # duplicate alert beats a silent uncontrolled exposure).
            logger.warning(
                f"[RISK_MONITOR] tripwire dedup read failed — alarming anyway: {dedup_err}"
            )
        self._log_alert(
            user_id=user_id,
            alert_type="concurrent_live_positions_uncontrolled",
            severity="critical",
            message=(
                f"{len(open_live)} concurrent LIVE positions open "
                f"({', '.join(symbols)}) with NO bucket-correlation control "
                f"built (B1/B2 filed). Additive alarm only — nothing was "
                f"blocked or closed; operator decides."
            ),
            metadata={
                "position_set": position_set,
                "count": len(open_live),
                "symbols": symbols,
                "consequence": (
                    "Concurrent live exposure is uncontrolled at block level "
                    "until B1/B2 ships; correlated names can stack."
                ),
                "operator_action": (
                    "Review the open set; close/hold is your call. The "
                    "alarm re-fires only if the set changes."
                ),
            },
        )

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
        """Write a risk alert via the canonical observability ``alert()``.

        A9 2026-07-07: was a bare direct insert — no severity-vocabulary
        enforcement, no insert retry (#1100), no immediate egress, no
        egress_owner stamp (today's REAL force_close rode the ≤37-min relay
        because THIS writer wrote it). Delegating to alert() gives every
        monitor alert the retry stack, the allowlisted immediate egress +
        receipt, and the F3 row-lost fail-safe. Severities are normalized
        into the vocabulary first (medium/warn → warning, error → high) so a
        severity='warning' query catches the whole warning class. alert()
        never raises; the outer guard covers the import seam only.
        """
        _SEVERITY_NORMALIZE = {
            "medium": "warning", "warn": "warning", "error": "high",
        }
        severity = _SEVERITY_NORMALIZE.get(severity, severity)
        try:
            from packages.quantum.observability.alerts import alert as _alert
            _alert(
                self.supabase,
                alert_type=alert_type,
                message=message,
                severity=severity,
                metadata=metadata or {},
                user_id=user_id,
                position_id=position_id,
                symbol=symbol,
            )
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
