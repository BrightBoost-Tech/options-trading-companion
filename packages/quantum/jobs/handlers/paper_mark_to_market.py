"""
Paper Mark-to-Market Job Handler

Refreshes current_mark and unrealized_pl on all open paper positions,
then saves an EOD snapshot for checkpoint evaluation.

Schedule: 3:30 PM CDT (while quotes are still live, before checkpoint).
"""

import logging
from typing import Any, Dict

from packages.quantum.services.paper_mark_to_market_service import PaperMarkToMarketService
from packages.quantum.jobs.handlers.utils import get_admin_client
from packages.quantum.jobs.handlers.exceptions import RetryableJobError, PermanentJobError

logger = logging.getLogger(__name__)

JOB_NAME = "paper_mark_to_market"


def run(payload: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    """
    Refresh marks and save EOD snapshot.

    Payload:
        - user_id: str - Target user UUID (required)
    """
    user_id = payload.get("user_id")

    if not user_id:
        raise PermanentJobError("user_id is required for paper_mark_to_market")

    logger.info(f"[PAPER_MARK_TO_MARKET] Starting for user {user_id}")

    try:
        client = get_admin_client()
        service = PaperMarkToMarketService(client)

        # 1. Refresh marks with live quotes
        mark_result = service.refresh_marks(user_id)
        logger.info(
            f"[PAPER_MARK_TO_MARKET] Marks refreshed: "
            f"{mark_result.get('positions_marked', 0)}/{mark_result.get('total_positions', 0)}"
        )

        # 1b. Run risk envelope check against refreshed marks (WARN-ONLY)
        envelope_violations = []
        try:
            from packages.quantum.risk.risk_envelope import (
                check_all_envelopes,
                EnvelopeConfig,
            )

            # Fetch open LIVE-routed positions with updated marks. Scoped to
            # live_eligible portfolios so the (warn-only) envelope here reflects
            # live-capital exposure, not shadow_only / paper_shadow cohort
            # positions (#1011 twin; consistent with the autopilot circuit
            # breaker + intraday monitor live scoping).
            from packages.quantum.risk.position_scope import live_routed_portfolio_ids
            _live_ids = live_routed_portfolio_ids(client, user_id)
            if _live_ids:
                pos_res = client.table("paper_positions") \
                    .select("id, symbol, quantity, unrealized_pl, avg_entry_price, max_credit, nearest_expiry, sector, status") \
                    .in_("portfolio_id", _live_ids) \
                    .eq("status", "open") \
                    .execute()
                open_positions = pos_res.data or []
            else:
                open_positions = []

            # Equity source — Alpaca-authoritative via the shared
            # equity_state module (PR #780 follow-up). The prior
            # inline approach used an event-loop bridge into
            # CashService that always raised inside RQ worker context,
            # then fell through to a notional-of-open-positions sum.
            # That produced absurdly tight per-symbol envelope limits
            # on small paper portfolios (e.g. AMZN $1,310 notional →
            # $39 per-symbol loss limit at 3%).
            #
            # get_alpaca_equity returns None on Alpaca failure; MUST
            # NOT fabricate a substitute denominator. Matches the
            # contract intraday_risk_monitor has used since 83872db —
            # fabricated equity was the mechanism behind the
            # 2026-04-16 false force-close incident.
            from packages.quantum.services import equity_state
            # v5-A2: fetch equity even on an EMPTY book — realized losses
            # survive force-closes; this (warn-only) check must still see
            # them instead of going silent the moment the book empties.
            equity = equity_state.get_alpaca_equity(user_id, supabase=client)

            if equity is None:
                logger.warning(
                    f"[RISK_ENVELOPE] MTM: Alpaca equity unavailable "
                    f"for user={user_id[:8]} — skipping envelope check. "
                    f"Greeks/concentration/stress envelopes unaffected; "
                    f"loss envelopes will be re-evaluated next cycle."
                )
            else:
                # Daily P&L: open-book unrealized sum (marks just refreshed)
                # tightened by broker equity−last_equity (v5-A2 realized-
                # blind brake — min() so the envelope fires on EITHER).
                daily_pnl_proxy = sum(float(p.get("unrealized_pl") or 0) for p in open_positions)
                daily_pnl = equity_state.tightened_daily_pnl(
                    user_id, daily_pnl_proxy, supabase=client,
                )

                config = EnvelopeConfig.from_env()
                envelope_result = check_all_envelopes(
                    positions=open_positions,
                    equity=equity,
                    daily_pnl=daily_pnl,
                    config=config,
                )

                if envelope_result.violations:
                    for v in envelope_result.violations:
                        logger.warning(
                            f"[RISK_ENVELOPE] MTM {v.severity.upper()}: {v.message} "
                            f"(envelope={v.envelope})"
                        )
                    envelope_violations = [v.to_dict() for v in envelope_result.violations]

                    if envelope_result.force_close_ids:
                        logger.critical(
                            f"[RISK_ENVELOPE] FORCE_CLOSE recommended for "
                            f"{len(envelope_result.force_close_ids)} positions: "
                            f"{envelope_result.force_close_ids} "
                            f"(warn-only mode — no action taken)"
                        )
        except Exception as env_err:
            logger.warning(f"[RISK_ENVELOPE] MTM check failed (non-fatal): {env_err}")

        # 2. Save EOD snapshot
        snapshot_result = service.save_eod_snapshot(user_id)
        logger.info(
            f"[PAPER_MARK_TO_MARKET] Snapshots saved: {snapshot_result.get('snapshots_saved', 0)}"
        )

        return {
            "ok": True,
            "mark_result": mark_result,
            "snapshot_result": snapshot_result,
            "envelope_violations": envelope_violations,
        }

    except Exception as e:
        logger.error(f"[PAPER_MARK_TO_MARKET] Failed for user {user_id}: {e}")
        raise RetryableJobError(f"Paper mark-to-market failed: {e}")
