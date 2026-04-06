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

            # Fetch open positions with updated marks
            pos_res = client.table("paper_positions") \
                .select("id, symbol, quantity, unrealized_pl, avg_entry_price, max_credit, nearest_expiry, sector, status") \
                .eq("user_id", user_id) \
                .eq("status", "open") \
                .execute()
            open_positions = pos_res.data or []

            if open_positions:
                # Sum unrealized P&L as daily proxy (marks just refreshed)
                daily_pnl = sum(float(p.get("unrealized_pl") or 0) for p in open_positions)

                # Estimate equity from positions + marks
                from packages.quantum.services.cash_service import CashService
                import asyncio
                cash_svc = CashService(client)
                try:
                    equity = asyncio.get_event_loop().run_until_complete(
                        cash_svc.get_deployable_capital(user_id)
                    )
                except RuntimeError:
                    equity = sum(abs(float(p.get("avg_entry_price") or 0)) * abs(float(p.get("quantity") or 0)) * 100 for p in open_positions)

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
