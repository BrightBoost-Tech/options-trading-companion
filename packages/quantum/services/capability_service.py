from typing import List, Optional, Dict, Any
from uuid import UUID
from supabase import Client

from packages.quantum.models import UpgradeCapability, CapabilityState, UserCapabilitiesResponse
from packages.quantum.services.journal_service import JournalService
from packages.quantum.security import get_supabase_user_client
import logging

logger = logging.getLogger(__name__)

class CapabilityResolver:
    """
    Determines which capabilities are active for a user based on deterministic rules:
    - Data availability
    - Account size
    - User actions (e.g. reviewed outcomes)
    """

    def __init__(self, supabase_client: Client):
        self.supabase = supabase_client
        # We can also inject other services if needed, e.g. for account size

    def resolve_capabilities(self, user_id: str) -> UserCapabilitiesResponse:
        capabilities = []

        # 1. Agent Sizing
        # Rule: Active if we have a portfolio snapshot with value > $2,000 (arbitrary threshold for "serious" sizing)
        # or just if we have *any* synced positions to size against.
        agent_sizing = self._check_agent_sizing(user_id)
        capabilities.append(agent_sizing)

        # 2. Counterfactual Feedback
        # Rule: Active if user has at least one entry in outcomes_log (meaning they are generating data for feedback)
        counterfactual = self._check_counterfactual_feedback(user_id)
        capabilities.append(counterfactual)

        # 3. Advanced Event Guardrails
        # Rule: Active if we have sufficient market data (scanner_universe populated)
        guardrails = self._check_event_guardrails(user_id)
        capabilities.append(guardrails)

        return UserCapabilitiesResponse(capabilities=capabilities)

    def _check_agent_sizing(self, user_id: str) -> CapabilityState:
        """
        Check if account size / sync status supports agent sizing.
        """
        try:
            # Check most recent snapshot
            res = self.supabase.table("portfolio_snapshots") \
                .select("holdings, created_at") \
                .eq("user_id", user_id) \
                .order("created_at", desc=True) \
                .limit(1) \
                .execute()

            data = res.data
            if not data:
                return CapabilityState(
                    capability=UpgradeCapability.AGENT_SIZING_ENABLED,
                    is_active=False,
                    reason="No portfolio synced. Connect brokerage to unlock."
                )

            # Simple check: do we have holdings?
            holdings = data[0].get("holdings", [])
            if len(holdings) > 0:
                 return CapabilityState(
                    capability=UpgradeCapability.AGENT_SIZING_ENABLED,
                    is_active=True,
                    reason="Portfolio synced."
                )
            else:
                 return CapabilityState(
                    capability=UpgradeCapability.AGENT_SIZING_ENABLED,
                    is_active=False,
                    reason="Portfolio empty."
                )

        except Exception as e:
            logger.error(f"Error checking agent sizing capability: {e}")
            return CapabilityState(
                capability=UpgradeCapability.AGENT_SIZING_ENABLED,
                is_active=False,
                reason="Error verifying account status."
            )

    def _check_counterfactual_feedback(self, user_id: str) -> CapabilityState:
        """
        Check if user has outcomes to analyze.
        """
        try:
            # Check outcomes_log or similar
            # If table doesn't exist yet in all envs, catch error
            res = self.supabase.table("learning_feedback_loops") \
                .select("id", count="exact") \
                .eq("user_id", user_id) \
                .limit(1) \
                .execute()

            count = res.count
            if count and count > 0:
                return CapabilityState(
                    capability=UpgradeCapability.COUNTERFACTUAL_FEEDBACK,
                    is_active=True,
                    reason="Feedback loop active."
                )
            else:
                return CapabilityState(
                    capability=UpgradeCapability.COUNTERFACTUAL_FEEDBACK,
                    is_active=False,
                    reason="No completed trade cycles yet."
                )

        except Exception as e:
            # Fallback if table issues
            logger.warning(f"Could not check learning_feedback_loops: {e}")
            return CapabilityState(
                capability=UpgradeCapability.COUNTERFACTUAL_FEEDBACK,
                is_active=False,
                reason="Data unavailable."
            )

    def _check_event_guardrails(self, user_id: str) -> CapabilityState:
        """
        Check if market data availability supports advanced guardrails.
        This is a system-wide check usually, but let's scope it.
        """
        try:
            # Check if scanner universe has data
            res = self.supabase.table("scanner_universe") \
                .select("ticker") \
                .limit(1) \
                .execute()

            if res.data and len(res.data) > 0:
                return CapabilityState(
                    capability=UpgradeCapability.ADVANCED_EVENT_GUARDRAILS,
                    is_active=True,
                    reason="Market data active."
                )
            else:
                return CapabilityState(
                    capability=UpgradeCapability.ADVANCED_EVENT_GUARDRAILS,
                    is_active=False,
                    reason="Market scanner offline."
                )
        except Exception as e:
            return CapabilityState(
                capability=UpgradeCapability.ADVANCED_EVENT_GUARDRAILS,
                is_active=False,
                reason="System check failed."
            )
