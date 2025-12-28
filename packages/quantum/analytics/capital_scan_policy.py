from packages.quantum.services.analytics.small_account_compounder import SmallAccountCompounder

class CapitalScanPolicy:
    # Tier-based minimum scan thresholds
    # Micro ($0-$1k): $15 min
    # Small ($1k-$5k): $35 min
    # Standard ($5k+): $100 min
    THRESHOLDS = {
        "micro": 15.0,
        "small": 35.0,
        "standard": 100.0
    }

    # Fallback default
    DEFAULT_THRESHOLD = 100.0

    @staticmethod
    def can_scan(deployable_capital: float) -> tuple[bool, str]:
        """
        Determines if the account has enough capital to run a scan.
        Returns (allowed: bool, reason: str).
        """
        if deployable_capital is None:
            return False, "Deployable capital is None"

        if deployable_capital <= 0:
            return False, f"Deployable capital is zero or negative ({deployable_capital})"

        # Determine tier
        try:
            tier = SmallAccountCompounder.get_tier(deployable_capital)
            tier_name = tier.name.lower()
        except Exception:
            # Fallback if get_tier fails
            # Assume standard to be safe
            tier_name = "standard"

        threshold = CapitalScanPolicy.THRESHOLDS.get(tier_name, CapitalScanPolicy.DEFAULT_THRESHOLD)

        if deployable_capital < threshold:
            return False, f"Insufficient capital ({deployable_capital:.2f}) for {tier_name} tier scan (min: {threshold:.2f})"

        return True, "OK"
