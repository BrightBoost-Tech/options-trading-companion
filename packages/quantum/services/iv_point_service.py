import numpy as np
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Tuple, Any

class IVPointService:
    """
    Service for calculating 30-day ATM Implied Volatility from option chain snapshots.
    Follows the VIX methodology logic:
    1. Select near-term and next-term expirations bracketing 30 days.
    2. Select ATM strikes for each expiration.
    3. Interpolate variance in time.
    """

    @staticmethod
    def compute_atm_iv_30d_from_chain(
        chain_results: List[Dict],
        spot: float,
        as_of_ts: datetime
    ) -> Dict[str, Any]:
        """
        Orchestrates the calculation of 30-day IV.
        Returns a dictionary suitable for storage in underlying_iv_points.
        """
        if not chain_results or spot <= 0:
            return IVPointService._failure_result("missing_data")

        # 1. Group by expiry
        grouped = IVPointService._group_by_expiry(chain_results)

        # 2. Filter valid expiries (> 1 day, < 365 days)
        valid_expiries = []
        today = as_of_ts.date()
        target_date = today + timedelta(days=30)

        for exp_str, contracts in grouped.items():
            try:
                exp_date = datetime.strptime(exp_str, '%Y-%m-%d').date()
                dte = (exp_date - today).days
                if 2 <= dte <= 365:
                    valid_expiries.append((dte, exp_date, contracts))
            except ValueError:
                continue

        valid_expiries.sort(key=lambda x: x[0]) # Sort by DTE

        if not valid_expiries:
            return IVPointService._failure_result("no_valid_expiries")

        # 3. Find bracketing expiries
        # We need T1 <= 30 <= T2
        # Ideally T1 is closest <= 30, T2 is closest > 30

        term1 = None
        term2 = None

        # Iterate to find the crossover point
        for i in range(len(valid_expiries)):
            dte, _, _ = valid_expiries[i]
            if dte <= 30:
                term1 = valid_expiries[i]
            elif dte > 30:
                term2 = valid_expiries[i]
                break # Found the first one > 30

        # Fallback logic if we don't have perfect brackets
        method = "var_interp_spot_atm"
        quality_penalty = 0

        if term1 and term2:
            pass # Ideal case
        elif term1 and not term2:
            # Only have shorter terms (e.g. 29 days). Extrapolate or just use last.
            # Using nearest for robustness.
            term2 = term1
            method = "nearest_expiry"
            quality_penalty = 20
        elif not term1 and term2:
            # Only have longer terms (e.g. starting 35 days).
            term1 = term2
            method = "nearest_expiry"
            quality_penalty = 20

        # 4. Calculate IV for each term
        # Term structure: (dte, date, contracts)
        iv1, strike1, q1 = IVPointService._compute_atm_iv_for_expiry(term1[2], spot)
        iv2, strike2, q2 = IVPointService._compute_atm_iv_for_expiry(term2[2], spot)

        if iv1 is None or iv2 is None:
             return IVPointService._failure_result("atm_iv_calculation_failed")

        # 5. Interpolate
        # V = sigma^2 * T
        # T is in years = DTE / 365.0 (Standardize to 365 for crypto/stocks usually 252? VIX uses minutes/year)
        # We will use simple calendar days / 365.0 for IV convention matching Polygon usually.

        t1 = term1[0] / 365.0
        t2 = term2[0] / 365.0
        t_target = 30.0 / 365.0

        v1 = (iv1 ** 2) * t1
        v2 = (iv2 ** 2) * t2

        # Linear interpolation of Variance
        # V_30 = V1 + (V2 - V1) * ( (T_target - T1) / (T2 - T1) )

        if term1[0] == term2[0]:
            # Same expiry (fallback case)
            v_target = v1
            # If using same expiry, DTE might not match t_target (30d).
            # If T1 != 30, then V1 = sigma^2 * T1.
            # V_target (30d) would be sigma^2 * T_30?
            # If we assume flat term structure for single expiry:
            # IV_30 = IV_T1.
            # So v_target should actually be iv1^2 * t_target.
            # Current code: v_target = v1 = iv1^2 * t1.
            # iv_30d = sqrt(v1 / t_target) = sqrt(iv1^2 * t1 / t_target) = iv1 * sqrt(t1 / t_target)
            # This scales IV by sqrt(time ratio) which is incorrect for flat term structure assumption.
            # If we assume flat IV, IV_30 = IV1.

            # Correct logic for "nearest_expiry" method:
            # Return IV1 directly.
            iv_30d = iv1
        else:
            slope = (v2 - v1) / (t2 - t1)
            v_target = v1 + slope * (t_target - t1)

            if v_target < 0:
                v_target = 0

            iv_30d = np.sqrt(v_target / t_target)

        return {
            "iv_30d": float(iv_30d),
            "iv_30d_method": method,
            "expiry1": term1[1].strftime('%Y-%m-%d'),
            "expiry2": term2[1].strftime('%Y-%m-%d'),
            "iv1": float(iv1),
            "iv2": float(iv2),
            "strike1": float(strike1),
            "strike2": float(strike2),
            "quality_score": max(0, 100 - quality_penalty - q1 - q2), # 100 is perfect
            "inputs": {
                "t1_dte": term1[0],
                "t2_dte": term2[0],
                "spot": spot
            }
        }

    @staticmethod
    def _compute_atm_iv_for_expiry(contracts: List[Dict], spot: float) -> Tuple[Optional[float], Optional[float], int]:
        """
        Returns (iv, strike, penalty_score)
        Selects strike closest to spot.
        Averages Call and Put IV if available.
        """
        if not contracts:
            return None, None, 100

        # Find ATM strike
        # Filter for valid IVs first?
        # Polygon snapshot keys: 'implied_volatility', 'strike_price', 'contract_type' ('call'/'put')

        # Organize by strike
        by_strike = {}
        for c in contracts:
            details = c.get('details', {})
            strike = details.get('strike_price')
            if strike is None:
                continue

            if strike not in by_strike:
                by_strike[strike] = {'call': None, 'put': None}

            ctype = details.get('contract_type') # 'call' or 'put'

            # Check for IV
            greeks = c.get('greeks') or {}
            iv = c.get('implied_volatility') or greeks.get('iv')

            if iv and iv > 0:
                by_strike[strike][ctype] = iv

        if not by_strike:
            return None, None, 100

        # Find closest strike to spot
        available_strikes = sorted(by_strike.keys())
        closest_strike = min(available_strikes, key=lambda x: abs(x - spot))

        data = by_strike[closest_strike]
        iv_call = data['call']
        iv_put = data['put']

        penalty = 0
        final_iv = None

        if iv_call and iv_put:
            final_iv = (iv_call + iv_put) / 2.0
        elif iv_call:
            final_iv = iv_call
            penalty += 10 # Missing one side
        elif iv_put:
            final_iv = iv_put
            penalty += 10 # Missing one side
        else:
            # Should not happen given logic above, but fallback
            # Try searching neighbors?
            # For this Phase, simplistic fail.
            return None, closest_strike, 100

        # Penalty for distance from spot
        dist_pct = abs(closest_strike - spot) / spot
        if dist_pct > 0.05:
            penalty += int(dist_pct * 100) # 1% off = 1 penalty point

        return final_iv, closest_strike, penalty

    @staticmethod
    def _group_by_expiry(contracts: List[Dict]) -> Dict[str, List[Dict]]:
        grouped = {}
        for c in contracts:
            details = c.get('details', {})
            exp = details.get('expiration_date')
            if exp:
                if exp not in grouped:
                    grouped[exp] = []
                grouped[exp].append(c)
        return grouped

    @staticmethod
    def _failure_result(reason: str) -> Dict[str, Any]:
        return {
            "iv_30d": None,
            "iv_30d_method": "failed",
            "inputs": {"reason": reason}
        }
