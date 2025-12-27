from typing import List, Optional, Set, Dict

# Normalized set of known credit strategies
# Includes registry keys and StrategySelector output strings
CREDIT_STRATEGIES = {
    "short_put_credit_spread",
    "short_call_credit_spread",
    "credit_put_spread",
    "credit_call_spread",
    "iron_condor",
    "short_strangle",
    "short_put",
    "short_call",
    "condor"
}

class StrategyPolicy:
    """
    Central policy enforcement for trading strategies.
    Used by StrategySelector, Scanner, and Orchestrator to filter out banned structures.
    """
    def __init__(self, banned_strategies: List[str] = None):
        """
        Initialize with a list of banned strategy strings.
        Special keywords:
        - 'credit_spreads': Bans all vertical credit spreads and iron condors.
        """
        self.banned_strategies = set(s.lower().strip() for s in (banned_strategies or []))

        # Check for broad category bans
        self.ban_all_credit = (
            "credit_spreads" in self.banned_strategies
            or "credit" in self.banned_strategies
        )

    def is_allowed(self, strategy_name: str) -> bool:
        """
        Determines if a specific strategy is allowed under the current policy.
        """
        if not strategy_name:
            return True # No strategy to ban (e.g. unknown)

        s = strategy_name.lower().strip().replace(" ", "_")

        # 1. Direct Ban
        if s in self.banned_strategies:
            return False

        # 2. Category Ban: Credit Spreads
        if self.ban_all_credit:
            if self._is_credit_strategy(s):
                return False

        return True

    def get_rejection_reason(self, strategy_name: str) -> Optional[str]:
        """
        Returns a human-readable rejection reason if banned, else None.
        """
        if self.is_allowed(strategy_name):
            return None

        s = strategy_name.lower().strip().replace(" ", "_")
        if self.ban_all_credit and self._is_credit_strategy(s):
            return f"Strategy '{strategy_name}' is banned (No Credit Spreads Policy)."

        return f"Strategy '{strategy_name}' is explicitly banned by user preference."

    def _is_credit_strategy(self, strategy_key: str) -> bool:
        """
        Helper to detect if a strategy string represents a credit structure.
        """
        # Check allowed list
        if strategy_key in CREDIT_STRATEGIES:
            return True

        # Heuristic checks
        if "credit" in strategy_key:
            return True
        if "short" in strategy_key and "spread" in strategy_key:
            # e.g. short_put_spread is typically a credit spread (selling the spread)
            # But wait, "short put spread" is ambiguous?
            # In this codebase: "SHORT_PUT_CREDIT_SPREAD"
            return True

        # Iron Condor variants
        if "condor" in strategy_key:
            return True

        return False
