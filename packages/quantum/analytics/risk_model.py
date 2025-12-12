
import math
import numpy as np
import logging
from typing import List, Dict, Any, Tuple
from packages.quantum.models import SpreadPosition

logger = logging.getLogger(__name__)

class SpreadRiskModel:
    """
    Deliverable 2: Spread/Greeks-aware Optimizer Inputs.
    Computes expected return (mu), covariance (sigma), and collateral
    directly from spread greeks and market factors.
    """

    def __init__(self, investable_assets: List[SpreadPosition], market_context: Dict[str, Any] = None):
        self.assets = investable_assets
        self.market_context = market_context or {}
        # Defaults if market context is missing
        self.base_drift = self.market_context.get('base_drift', 0.05) # 5% annual market drift
        self.risk_free_rate = self.market_context.get('risk_free_rate', 0.04) # 4% risk free
        self.market_vol_change = self.market_context.get('expected_vol_change', 0.0) # Assume stable vol on avg

    def build_mu_sigma(self,
                       underlying_cov: np.ndarray,
                       underlying_tickers: List[str],
                       horizon_days: int = 5) -> Tuple[np.ndarray, np.ndarray, np.ndarray, List[float]]:
        """
        Constructs mu and sigma for the optimizer based on spread components.

        Args:
            underlying_cov: Covariance matrix of underlying asset RETURNS.
            underlying_tickers: List of tickers corresponding to rows/cols of underlying_cov.
            horizon_days: Optimization horizon in days.

        Returns:
            mu: Expected return vector (n,)
            sigma: Covariance matrix (n, n)
            coskew: Coskewness tensor (n, n, n) - currently zeros
            collateral: List of collateral requirement per spread
        """
        n = len(self.assets)
        mu = np.zeros(n)
        sigma = np.zeros((n, n))
        collateral = np.zeros(n)

        # Pre-compute mapping from underlying ticker to index in underlying_cov
        # Be robust to variations in ticker symbols (e.g. SPY vs SPY US)
        u_map = {t: i for i, t in enumerate(underlying_tickers)}

        # 1. Compute per-spread metrics
        spread_deltas = []
        spread_vegas = []

        for i, asset in enumerate(self.assets):
            # Calculate Collateral / Capital Required
            # Logic: Use max loss or explicit margin calculation.
            # SpreadPosition doesn't always have 'max_loss' pre-calc, so we infer or default.
            # Assuming vertical spread: Width * Qty * 100 - Premium?
            # Or use 'net_cost' for debit spreads.

            c_i = self._estimate_collateral(asset)
            collateral[i] = c_i
            if c_i <= 0.01: c_i = 100.0 # Safety div by zero

            # Extract Greeks (scaled to 1 unit of spread)
            # SpreadPosition delta/gamma/etc are total for quantity?
            # Check models.py: "delta: float" usually aggregate.
            # But optimizer works on weights. We need return per dollar of capital.
            # Return_i = PnL_i / Collateral_i

            # Use aggregate greeks from asset
            delta_i = asset.delta
            vega_i = asset.vega
            theta_i = asset.theta

            # Underlying price (needed for Delta exposure in $)
            # S is underlying price. Delta is typically dOpt/dUnderlying.
            # Dollar Delta = Delta * S.
            # But underlying price isn't on SpreadPosition directly, only 'underlying'.
            # We assume we can get S from leg or approximation or just use 1.0 if missing (bad).
            S = 100.0
            if asset.legs:
                # Try to find price from legs
                leg0 = asset.legs[0]
                if isinstance(leg0, dict):
                    S = leg0.get('current_price') or leg0.get('underlying_price') or 100.0
                # If SpreadLeg object
                elif hasattr(leg0, 'current_price'):
                    S = leg0.current_price or 100.0

            # Expected PnL (approx Taylor expansion)
            # E[PnL] = Delta * E[dS] + Vega * E[dVol] + Theta * dt

            # E[dS] = S * (mu_stock * dt)
            dt = horizon_days / 365.0

            # Use market drift (beta * market) or individual stock drift?
            # For V3, let's use a simplified CAPM-like or constant drift if specific drift missing.
            # We assume underlying follows base_drift.
            expected_stock_return = self.base_drift * dt
            E_dS = S * expected_stock_return

            # E[dVol]
            # Mean reversion? For now assume 0 or slight revert.
            E_dVol = self.market_vol_change * dt

            # Theta PnL
            theta_pnl = theta_i * horizon_days # Theta is usually decay per day

            E_PnL = (delta_i * E_dS) + (vega_i * E_dVol) + theta_pnl

            # Normalize to return
            mu[i] = E_PnL / c_i

            # Store scaled sensitivities for Sigma calculation
            # Sensitivity to Underlying Return R_u: (Delta * S) / Collateral
            sens_delta = (delta_i * S) / c_i
            spread_deltas.append(sens_delta)

            # Sensitivity to Vol Return?
            # We lack Vol covariance matrix. We will omit Vega covariance for now
            # and treat Delta covariance as the primary driver.
            # Add idiosyncratic variance diagonal?
            spread_vegas.append(vega_i / c_i)

        # 2. Compute Sigma (Covariance)
        # Sigma_spreads = J @ Sigma_stocks @ J.T
        # Where J is (n_spreads, n_stocks) sensitivity matrix.

        # Construct Jacobian J
        n_stocks = len(underlying_tickers)
        if n_stocks == 0:
            # Fallback identity
            return mu, np.eye(n)*0.05, np.zeros((n,n,n)), collateral

        J = np.zeros((n, n_stocks))

        for i, asset in enumerate(self.assets):
            u_sym = asset.underlying
            if u_sym in u_map:
                idx = u_map[u_sym]
                # J[i, idx] = Sensitivity of Spread i to Return of Stock idx
                J[i, idx] = spread_deltas[i]
            else:
                # Ticker not in covariance matrix (e.g. index vs stock mismatch)
                # Fallback: Treat as independent variance?
                pass

        # Calculate Systematic Covariance
        Sigma_syst = J @ underlying_cov @ J.T

        # Add Idiosyncratic / Unexplained Variance
        # Options have gamma/vega risk not captured by delta-linear correlation.
        # Add a diagonal ridge.
        # Estimate idiosyncratic vol roughly:
        # Vega risk? Gamma risk?
        # Simple heuristic: add 20% of diagonal or min floor.

        diag_ridge = np.diag([0.01 + (0.1 * abs(v)) for v in spread_vegas]) # Vega-based uncertainty?

        # Ensure minimum variance (avoid singular matrix)
        min_var = 1e-4
        np.fill_diagonal(diag_ridge, np.diag(diag_ridge) + min_var)

        sigma = Sigma_syst + diag_ridge

        # Coskew (Mock for now, as requested)
        coskew = np.zeros((n, n, n))

        return mu, sigma, coskew, list(collateral)

    def _estimate_collateral(self, asset: SpreadPosition) -> float:
        """
        Estimates the capital required (denominator for return calc).
        """
        # 1. If explicit value exists (unlikely in current model but good practice)
        # if hasattr(asset, 'margin_req') and asset.margin_req: return asset.margin_req

        # 2. Estimate based on type
        stype = str(asset.spread_type).lower()

        # 2.1 Debit Spreads / Long Calls / Long Puts
        # Capital = Cost Basis (Net Cost)
        if 'debit' in stype or 'long' in stype:
            cost = asset.net_cost
            if cost > 0: return cost
            # Fallback if cost is zero/negative (data error): Use current value
            if asset.current_value > 0: return asset.current_value
            # Fallback: width?
            return 500.0 # $500 default

        # 2.2 Credit Spreads / Iron Condors / Verticals (Short)
        # Capital = Max Loss (Width - Credit) or Margin
        # We need width.
        width = 0.0
        strikes = []
        for leg in asset.legs:
            # Handle dictionary or object leg
            s = leg.get('strike') if isinstance(leg, dict) else getattr(leg, 'strike', 0)
            if s: strikes.append(float(s))

        if len(strikes) >= 2:
            width = max(strikes) - min(strikes)

        if width > 0:
            qty = asset.quantity
            # For IC, width of wider wing. Assuming simplified width calc above is okay for V1.
            # Max Loss = (Width * 100 * Qty) - Premium Received
            # Net Cost for credit spread is usually negative (credit).
            # So Capital = Width*100*Qty + Net_Cost

            # Standard contract size 100
            cap_req = (width * 100 * qty) + asset.net_cost # net_cost is negative for credit
            if cap_req < 0: cap_req = 100.0 # Should be positive
            return cap_req

        # Fallback default
        return 1000.0
