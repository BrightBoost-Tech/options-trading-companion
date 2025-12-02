from typing import Dict, Any, Optional, List
import math

class ScoringEngine:
    """
    Calculates a regime-conditioned raw score for a symbol based on weighted factors.

    The score is linear but weights are dynamic based on:
    - Market Regime (e.g., 'low_vol', 'high_vol', 'panic')
    - Catalyst Window (e.g., 'none', 'pre', 'event', 'post')
    - Liquidity Tier (e.g., 'top', 'mid', 'lower')
    """

    def __init__(
        self,
        weight_matrix: Dict[str, Dict[str, float]],
        catalyst_profiles: Dict[str, Dict[str, float]],
        liquidity_scalar: Dict[str, float],
    ):
        """
        Args:
            weight_matrix: weight_matrix[regime][factor] = base factor weight for that regime.
            catalyst_profiles: catalyst_profiles[catalyst_window][factor] = multiplicative adjustments.
            liquidity_scalar: liquidity_scalar[liquidity_tier] = scalar applied to final raw_score.
        """
        self.weight_matrix = weight_matrix
        self.catalyst_profiles = catalyst_profiles
        self.liquidity_scalar = liquidity_scalar

    def calculate_score(self, symbol_data: Dict[str, Any], regime: str) -> Dict[str, Any]:
        """
        Computes the raw score for a single symbol under a specific regime.

        Args:
            symbol_data: Dictionary containing:
                - "symbol": str
                - "factors": {factor_name: normalized_value} (values typically 0-100 or 0-1)
                - "catalyst_window": str (e.g., 'none', 'pre', 'event', 'post')
                - "liquidity_tier": str (e.g., 'top', 'mid', 'lower')
            regime: The current market regime (e.g., 'normal', 'high_vol').

        Returns:
            Dictionary with:
                 - "symbol": str,
                 - "raw_score": float,
                 - "factor_contribution": {factor: w_f * val_f},
                 - "regime_used": regime,
                 - "catalyst_window": str,
                 - "liquidity_tier": str,
        """
        symbol = symbol_data.get("symbol", "UNKNOWN")
        factors = symbol_data.get("factors", {})
        catalyst_window = symbol_data.get("catalyst_window", "none")
        liquidity_tier = symbol_data.get("liquidity_tier", "mid")

        # 1. Select weights for the regime (fallback to 'normal' or empty dict)
        base_weights = self.weight_matrix.get(regime, self.weight_matrix.get('normal', {}))
        if not base_weights and self.weight_matrix:
            # Fallback to first available if normal missing
            base_weights = next(iter(self.weight_matrix.values()))

        # 2. Apply catalyst multipliers
        # Default multiplier is 1.0 if not specified
        cat_multipliers = self.catalyst_profiles.get(catalyst_window, {})

        adjusted_weights = {}
        total_weight = 0.0

        for factor, weight in base_weights.items():
            multiplier = cat_multipliers.get(factor, 1.0)
            adj_w = weight * multiplier
            if adj_w < 0:
                adj_w = 0 # Ignore negative weights for normalization
            adjusted_weights[factor] = adj_w
            total_weight += adj_w

        # 3. Normalize weights to sum to 1
        final_weights = {}
        if total_weight > 0:
            for f, w in adjusted_weights.items():
                final_weights[f] = w / total_weight
        else:
            final_weights = {f: 0.0 for f in adjusted_weights}

        # 4. Compute linear score = Σ w_f * factor_value_f
        raw_score = 0.0
        factor_contribution = {}

        for factor, weight in final_weights.items():
            val = factors.get(factor, 0.0)
            contribution = weight * val
            factor_contribution[factor] = contribution
            raw_score += contribution

        # 5. Multiply by liquidity_scalar
        liq_scale = self.liquidity_scalar.get(liquidity_tier, 1.0)
        raw_score *= liq_scale

        # Scale factor contributions too so they sum to raw_score
        for f in factor_contribution:
            factor_contribution[f] *= liq_scale

        return {
            "symbol": symbol,
            "raw_score": raw_score,
            "factor_contribution": factor_contribution,
            "regime_used": regime,
            "catalyst_window": catalyst_window,
            "liquidity_tier": liquidity_tier,
        }


class ConvictionTransform:
    """
    Converts raw linear scores into a Conviction Coefficient C_i in [0, 1].

    Implements the "Relativity Trap" fix by anchoring the pivot (mu) against
    an absolute hard floor and blending it with the universe median.
    """

    def __init__(self, regime_profiles: Dict[str, Dict[str, Any]]):
        """
        Args:
            regime_profiles: Dict where key is regime name, value is dict with:
                - k: float (sigmoid steepness)
                - mu: float (nominal pivot score)
                - absolute_hard_floor: float (min score to be viable)
                - mu_dynamic_weight: float [0, 1] (weight of universe median)
                - panic_scale: Optional[float] (0, 1] (scalar for panic regime)
        """
        self.regime_profiles = regime_profiles

    def _sigmoid(self, x: float, k: float) -> float:
        try:
            return 1.0 / (1.0 + math.exp(-k * x))
        except OverflowError:
            return 0.0 if x < 0 else 1.0

    def get_conviction(
        self,
        raw_score: float,
        regime: str,
        universe_median: Optional[float] = None,
    ) -> float:
        """
        Calculates the Conviction Coefficient C_i.

        Args:
            raw_score: The raw score from ScoringEngine (0-100 scale implied).
            regime: The current market regime.
            universe_median: The median raw_score of the universe for this regime.
                             If None, dynamic relativity is disabled (uses nominal mu).

        Returns:
            float: Conviction coefficient in [0.0, 1.0].
        """
        profile = self.regime_profiles.get(regime)
        if not profile:
            # Fallback to default or raise error?
            # Using a safe default implies we might mask config errors,
            # but better than crashing in production if regime name mismatch.
            # Let's try to find a 'normal' profile or create a generic one.
            profile = self.regime_profiles.get('normal', {
                'k': 0.1, 'mu': 50.0, 'absolute_hard_floor': 30.0, 'mu_dynamic_weight': 0.0
            })

        k = profile.get('k', 0.1)
        mu = profile.get('mu', 50.0)
        absolute_hard_floor = profile.get('absolute_hard_floor', 0.0)
        mu_dynamic_weight = profile.get('mu_dynamic_weight', 0.0)
        panic_scale = profile.get('panic_scale', 1.0)

        # 1. Hard Floor Check
        if raw_score < absolute_hard_floor:
            return 0.0

        # 2. Compute effective pivot
        if universe_median is not None:
            blended_mu = (mu_dynamic_weight * universe_median) + ((1.0 - mu_dynamic_weight) * mu)
        else:
            blended_mu = mu

        mu_eff = max(blended_mu, absolute_hard_floor)

        # 3. Sigmoid Transform
        # C_i = 1 / (1 + exp(-k * (raw_score - mu_eff)))
        c_i = self._sigmoid(raw_score - mu_eff, k)

        # 4. Panic Scaling
        if regime == 'panic':
            c_i *= panic_scale

        # 5. Clamp to [0.0, 1.0] (sigmoid is already bounded, panic_scale <= 1)
        return max(0.0, min(1.0, c_i))
