from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Any
import logging
import numpy as np
from ..models import OptionContract, OptionType

logger = logging.getLogger(__name__)

class IVPointService:
    """
    Manages fetching and processing IV surface points for underlying assets.
    """

    def __init__(self, supabase_client):
        self.supabase = supabase_client

    def get_points(self, symbol: str, lookback_days: int = 30) -> List[Dict]:
        """Fetch IV points history for a symbol"""
        try:
            cutoff = (datetime.now() - timedelta(days=lookback_days)).isoformat()

            res = self.supabase.table('underlying_iv_points') \
                .select('*') \
                .eq('symbol', symbol) \
                .gte('date', cutoff) \
                .order('date', desc=True) \
                .execute()

            return res.data if res.data else []

        except Exception as e:
            logger.error(f"Failed to fetch IV points for {symbol}: {e}")
            return []

    def get_latest_point(self, symbol: str) -> Optional[Dict]:
        """Get most recent IV point"""
        try:
            res = self.supabase.table('underlying_iv_points') \
                .select('*') \
                .eq('symbol', symbol) \
                .order('date', desc=True) \
                .limit(1) \
                .execute()

            return res.data[0] if res.data else None

        except Exception as e:
            logger.error(f"Failed to fetch latest IV point for {symbol}: {e}")
            return None

    def upsert_point(self, point_data: Dict) -> bool:
        """Upsert a single IV point"""
        try:
            self.supabase.table('underlying_iv_points') \
                .upsert(point_data) \
                .execute()
            return True
        except Exception as e:
            logger.error(f"Failed to upsert IV point for {point_data.get('symbol')}: {e}")
            return False

    def compute_iv_stats(self, points: List[Dict]) -> Dict:
        """Calculate statistics from a list of points"""
        if not points:
            return {}

        ivs = [p['atm_iv_30d'] for p in points if p.get('atm_iv_30d')]
        if not ivs:
            return {}

        return {
            'avg_iv_30d': sum(ivs) / len(ivs),
            'min_iv': min(ivs),
            'max_iv': max(ivs),
            'current': ivs[0],
            'points_count': len(ivs)
        }

    # --- IV Surface Helpers ---

    def compute_atm_iv_target_from_chain(self, chain: List[Dict], spot: float, as_of_ts: datetime, target_dte: int = 30) -> Optional[float]:
        """
        Interpolates ATM IV for a specific DTE target from a raw option chain.
        Expects chain to have 'strike', 'expiration', 'implied_volatility', 'type'.
        """
        if not chain or spot <= 0:
            return None

        # 1. Filter for relevant expirations (near term)
        target_date = as_of_ts.date() + timedelta(days=target_dte)

        # Group by expiry
        expiries = {}
        for c in chain:
            # Parse expiry if string
            exp = c.get('expiration')
            if isinstance(exp, str):
                try:
                    exp = datetime.strptime(exp, "%Y-%m-%d").date()
                except ValueError:
                    continue
            elif isinstance(exp, (datetime, date)):
                exp = exp if isinstance(exp, date) else exp.date()
            else:
                continue

            dte = (exp - as_of_ts.date()).days
            if dte < 5 or dte > 120: continue # Focus on liquid near term

            if dte not in expiries: expiries[dte] = []
            expiries[dte].append(c)

        if not expiries:
            return None

        # 2. Find two closest expirations
        sorted_dtes = sorted(expiries.keys())
        # Ideally find one before and one after target_dte
        lower_dte = next((d for d in reversed(sorted_dtes) if d <= target_dte), None)
        upper_dte = next((d for d in sorted_dtes if d >= target_dte), None)

        if not lower_dte and not upper_dte: return None
        if not lower_dte: lower_dte = upper_dte
        if not upper_dte: upper_dte = lower_dte

        # Helper to get ATM IV for a specific expiry
        def get_expiry_atm(dte_chain):
            # Filter for strikes near spot
            # Simple approach: find straddle or closest OTM call/put average
            strikes = sorted(list(set(c['strike'] for c in dte_chain)))
            if not strikes: return None

            # Find closest strike
            closest_strike = min(strikes, key=lambda x: abs(x - spot))

            # Get IVs for closest strike
            ivs = [c.get('implied_volatility') for c in dte_chain
                   if c['strike'] == closest_strike and c.get('implied_volatility') is not None]

            valid_ivs = [iv for iv in ivs if iv > 0]
            if not valid_ivs: return None
            return sum(valid_ivs) / len(valid_ivs)

        iv_lower = get_expiry_atm(expiries[lower_dte])
        iv_upper = get_expiry_atm(expiries[upper_dte])

        if iv_lower is None or iv_upper is None:
            return iv_lower or iv_upper

        # 3. Time Weighted Interpolation
        if lower_dte == upper_dte:
            return iv_lower

        # Linear interpolation by square root of time (variance)? Or just linear time?
        # Standard: Linear in total variance (sigma^2 * t)
        t_target = target_dte / 365.0
        t_lower = lower_dte / 365.0
        t_upper = upper_dte / 365.0

        var_lower = (iv_lower ** 2) * t_lower
        var_upper = (iv_upper ** 2) * t_upper

        weight = (t_target - t_lower) / (t_upper - t_lower)
        var_target = var_lower + weight * (var_upper - var_lower)

        return np.sqrt(var_target / t_target)

    def compute_skew_25d_from_chain(self, chain: List[Dict], spot: float, as_of_ts: datetime, target_dte: int = 30) -> float:
        """
        Computes 25-delta Skew (Put IV - Call IV) / ATM IV.
        Approximates 25-delta using moneyness if delta not available.
        """
        # Approximate 25d strike distance (very rough, assumes BS)
        # 25d put is approx at spot * exp(-0.67 * sigma * sqrt(t))

        atm_iv = self.compute_atm_iv_target_from_chain(chain, spot, as_of_ts, target_dte)
        if not atm_iv: return 0.0

        t = target_dte / 365.0
        sigma = atm_iv

        # Estimate strikes
        # Standard deviation move
        std_dev = sigma * np.sqrt(t)

        # 25 Delta is roughly 0.67 std devs OTM?
        # N(d1) = 0.25 -> d1 approx -0.67
        # Strike approx: K = S * exp(0.67 * sigma * sqrt(t)) ?? No.
        # Let's use simple percentage OTM proxy for now if Greeks missing
        # 25 delta put approx 90-95% moneyness for 30d?
        # Rule of thumb: 1 SD move

        put_strike_target = spot * (1 - 0.7 * std_dev) # Roughly 25d
        call_strike_target = spot * (1 + 0.7 * std_dev) # Roughly 25d

        # Find IVs at these strikes for target expiry
        # We need to interpolate across strikes

        # Re-use expiry filtering logic
        # ... (Simplified: just grab all contracts in 20-40 DTE window)
        relevant_contracts = []
        for c in chain:
            # Parse expiry
            exp = c.get('expiration')
            if isinstance(exp, str):
                try: exp = datetime.strptime(exp, "%Y-%m-%d").date()
                except: continue
            elif isinstance(exp, (datetime, date)):
                exp = exp if isinstance(exp, date) else exp.date()

            dte = (exp - as_of_ts.date()).days
            if 20 <= dte <= 40:
                relevant_contracts.append(c)

        if not relevant_contracts: return 0.0

        # Find closest Put and Call
        put_ivs = [c['implied_volatility'] for c in relevant_contracts
                   if c.get('type') == 'put' and c.get('implied_volatility')]
        put_strikes = [c['strike'] for c in relevant_contracts
                       if c.get('type') == 'put' and c.get('implied_volatility')]

        call_ivs = [c['implied_volatility'] for c in relevant_contracts
                    if c.get('type') == 'call' and c.get('implied_volatility')]
        call_strikes = [c['strike'] for c in relevant_contracts
                        if c.get('type') == 'call' and c.get('implied_volatility')]

        if not put_ivs or not call_ivs: return 0.0

        # Interpolate Put IV
        put_iv = np.interp(put_strike_target, put_strikes, put_ivs)
        call_iv = np.interp(call_strike_target, call_strikes, call_ivs)

        # Skew = (Put IV - Call IV)
        return (put_iv - call_iv)

    def compute_term_slope(self, chain: List[Dict], spot: float, as_of_ts: datetime) -> float:
        """
        Computes term structure slope: (IV_90d - IV_30d) / IV_30d
        """
        iv_30 = self.compute_atm_iv_target_from_chain(chain, spot, as_of_ts, target_dte=30)
        iv_90 = self.compute_atm_iv_target_from_chain(chain, spot, as_of_ts, target_dte=90)

        if iv_30 and iv_90 and iv_30 > 0:
            return (iv_90 - iv_30) / iv_30
        return 0.0
