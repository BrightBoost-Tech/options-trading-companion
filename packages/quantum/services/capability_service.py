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
        # Rule: Active if account > $2,000 OR (Portfolio has holdings and we can assume it's funded)
        # We check for a recent portfolio snapshot with valid total value.
        agent_sizing = self._check_agent_sizing(user_id)
        capabilities.append(agent_sizing)

        # 2. Counterfactual Analysis
        # Rule: Active if user has at least one entry in outcomes_log (meaning they are generating data for feedback)
        counterfactual = self._check_counterfactual_analysis(user_id)
        capabilities.append(counterfactual)

        # 3. Advanced Event Guardrails
        # Rule: Active if we have sufficient market data (scanner_universe populated)
        guardrails = self._check_event_guardrails(user_id)
        capabilities.append(guardrails)

        return UserCapabilitiesResponse(capabilities=capabilities)

    def _check_agent_sizing(self, user_id: str) -> CapabilityState:
        """
        Check if account size / sync status supports agent sizing.
        Minimum Account Tier logic: > $2,000 for full auto sizing features.
        """
        try:
            # Check most recent snapshot
            res = self.supabase.table("portfolio_snapshots") \
                .select("holdings, created_at, risk_metrics") \
                .eq("user_id", user_id) \
                .order("created_at", desc=True) \
                .limit(1) \
                .execute()

            data = res.data
            if not data:
                return CapabilityState(
                    capability=UpgradeCapability.AGENT_SIZING,
                    is_active=False,
                    reason="No portfolio synced. Connect brokerage to unlock."
                )

            snapshot = data[0]
            holdings = snapshot.get("holdings", []) or [] # Ensure list
            risk_metrics = snapshot.get("risk_metrics", {}) or {}

            # Account Tier check
            # Handle potential None/Null values safely
            net_liquidity = risk_metrics.get("net_liquidity")
            total_equity = float(net_liquidity) if net_liquidity is not None else 0.0

            # If net_liquidity is missing/zero, try summing holdings
            if total_equity <= 0 and holdings:
                sum_holdings = 0.0
                for h in holdings:
                    qty = h.get("quantity")
                    price = h.get("current_price")
                    # Safe float conversion
                    q_val = float(qty) if qty is not None else 0.0
                    p_val = float(price) if price is not None else 0.0
                    sum_holdings += (q_val * p_val)
                total_equity = sum_holdings

            if total_equity >= 2000.0:
                 return CapabilityState(
                    capability=UpgradeCapability.AGENT_SIZING,
                    is_active=True,
                    reason="Active (Account > $2,000)"
                )
            elif len(holdings) > 0:
                 return CapabilityState(
                    capability=UpgradeCapability.AGENT_SIZING,
                    is_active=False,
                    reason="Account value too low (< $2,000) for agent sizing."
                )
            else:
                 return CapabilityState(
                    capability=UpgradeCapability.AGENT_SIZING,
                    is_active=False,
                    reason="Portfolio empty."
                )

        except Exception as e:
            logger.error(f"Error checking agent sizing capability: {e}")
            return CapabilityState(
                capability=UpgradeCapability.AGENT_SIZING,
                is_active=False,
                reason="Error verifying account status."
            )

    def _check_counterfactual_analysis(self, user_id: str) -> CapabilityState:
        """
        Check if user has outcomes to analyze.
        """
        try:
            # Check learning_feedback_loops or outcomes_log
            res = self.supabase.table("learning_feedback_loops") \
                .select("id", count="exact") \
                .eq("user_id", user_id) \
                .limit(1) \
                .execute()

            count = res.count
            if count is not None and count > 0:
                return CapabilityState(
                    capability=UpgradeCapability.COUNTERFACTUAL_ANALYSIS,
                    is_active=True,
                    reason="Feedback loop active."
                )
            else:
                return CapabilityState(
                    capability=UpgradeCapability.COUNTERFACTUAL_ANALYSIS,
                    is_active=False,
                    reason="No completed trade cycles yet."
                )

        except Exception as e:
            logger.warning(f"Could not check learning_feedback_loops: {e}")
            return CapabilityState(
                capability=UpgradeCapability.COUNTERFACTUAL_ANALYSIS,
                is_active=False,
                reason="Data unavailable."
            )

    def _check_event_guardrails(self, user_id: str) -> CapabilityState:
        """
        Check if market data availability supports advanced guardrails.
        """
        try:
            # Check if scanner universe has data (System Readiness)
            res = self.supabase.table("scanner_universe") \
                .select("ticker") \
                .limit(1) \
                .execute()

            if res.data and len(res.data) > 0:
                return CapabilityState(
                    capability=UpgradeCapability.ADVANCED_EVENT_GUARDRAILS,
                    is_active=True,
                    reason="System ready (Market Data Active)."
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
