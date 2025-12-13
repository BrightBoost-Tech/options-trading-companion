from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Any, Tuple
import logging
import numpy as np
from ..models import OptionContract, OptionType

logger = logging.getLogger(__name__)

class IVPointService:
    """
    Manages fetching and processing IV surface points for underlying assets.
    Service for calculating ATM Implied Volatility and Skew from option chain snapshots.
    Follows VIX methodology logic where applicable.
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

    @staticmethod
    def compute_atm_iv_target_from_chain(
        chain_results: List[Dict],
        spot: float,
        as_of_ts: datetime,
        target_dte: float = 30.0
    ) -> Dict[str, Any]:
        """
        Orchestrates the calculation of interpolated ATM IV for a specific target DTE.
        """
        if not chain_results or spot <= 0:
            return IVPointService._failure_result("missing_data")

        # 1. Group by expiry
        grouped = IVPointService._group_by_expiry(chain_results)

        # 2. Filter valid expiries (> 1 day, < 365 days)
        valid_expiries = []
        today = as_of_ts.date()

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
        term1 = None
        term2 = None

        for i in range(len(valid_expiries)):
            dte, _, _ = valid_expiries[i]
            if dte <= target_dte:
                term1 = valid_expiries[i]
            elif dte > target_dte:
                term2 = valid_expiries[i]
                break

        method = "var_interp_spot_atm"
        quality_penalty = 0

        if term1 and term2:
            pass
        elif term1 and not term2:
            term2 = term1
            method = "nearest_expiry"
            quality_penalty = 20
        elif not term1 and term2:
            term1 = term2
            method = "nearest_expiry"
            quality_penalty = 20

        # 4. Calculate IV for each term
        iv1, strike1, q1 = IVPointService._compute_atm_iv_for_expiry(term1[2], spot)
        iv2, strike2, q2 = IVPointService._compute_atm_iv_for_expiry(term2[2], spot)

        if iv1 is None or iv2 is None:
             return IVPointService._failure_result("atm_iv_calculation_failed")

        # 5. Interpolate
        t1 = term1[0] / 365.0
        t2 = term2[0] / 365.0
        t_target = target_dte / 365.0

        v1 = (iv1 ** 2) * t1
        v2 = (iv2 ** 2) * t2

        if term1[0] == term2[0]:
            iv_target = iv1
        else:
            slope = (v2 - v1) / (t2 - t1)
            v_target = v1 + slope * (t_target - t1)
            if v_target < 0: v_target = 0
            iv_target = np.sqrt(v_target / t_target)

        return {
            "iv": float(iv_target),
            "iv_30d": float(iv_target), # Backwards compat if target is 30
            "iv_method": method,
            "expiry1": term1[1].strftime('%Y-%m-%d'),
            "expiry2": term2[1].strftime('%Y-%m-%d'),
            "iv1": float(iv1),
            "iv2": float(iv2),
            "strike1": float(strike1),
            "strike2": float(strike2),
            "quality_score": max(0, 100 - quality_penalty - q1 - q2),
            "inputs": {
                "t1_dte": term1[0],
                "t2_dte": term2[0],
                "spot": spot,
                "target_dte": target_dte
            }
        }

    @staticmethod
    def compute_skew_25d_from_chain(
        chain_results: List[Dict],
        spot: float,
        as_of_ts: datetime,
        target_dte: float = 30.0
    ) -> Optional[float]:
        """
        Computes 25-delta Skew: (Put IV - Call IV) / ATM IV
        Uses delta if available, otherwise approximates via moneyness.
        Returns None if calculation fails.
        """
        if not chain_results or spot <= 0:
            return None

        # 1. Isolate options near target DTE (e.g. 30 days)
        grouped = IVPointService._group_by_expiry(chain_results)
        today = as_of_ts.date()

        best_diff = 999
        best_contracts = []

        for exp_str, contracts in grouped.items():
            try:
                exp_date = datetime.strptime(exp_str, '%Y-%m-%d').date()
                dte = (exp_date - today).days
                diff = abs(dte - target_dte)
                if diff < best_diff and dte > 2:
                    best_diff = diff
                    best_contracts = contracts
            except:
                continue

        if not best_contracts or best_diff > 15: # Too far from target
            return None

        # 2. Find 25 delta Put and Call
        calls = [c for c in best_contracts if c.get('details', {}).get('contract_type') == 'call']
        puts = [c for c in best_contracts if c.get('details', {}).get('contract_type') == 'put']

        def get_iv_at_delta(options, target_delta):
            candidates = []
            for opt in options:
                greeks = opt.get('greeks') or {}
                d = greeks.get('delta')
                iv = opt.get('implied_volatility') or greeks.get('iv')
                if d is not None and iv is not None:
                    candidates.append((abs(d - target_delta), iv))

            if not candidates:
                return None

            candidates.sort(key=lambda x: x[0])
            if candidates[0][0] < 0.10: # Within 0.10 delta
                return candidates[0][1]
            return None

        call_iv_25 = get_iv_at_delta(calls, 0.25)
        put_iv_25 = get_iv_at_delta(puts, -0.25)

        if call_iv_25 is None or put_iv_25 is None:
            return None

        # Get ATM IV for normalization
        atm_res = IVPointService._compute_atm_iv_for_expiry(best_contracts, spot)
        atm_iv = atm_res[0]

        if not atm_iv or atm_iv == 0:
            return None

        # Skew = (PutIV - CallIV) / ATM IV
        skew = (put_iv_25 - call_iv_25) / atm_iv
        return skew

    @staticmethod
    def compute_term_slope(
        chain_results: List[Dict],
        spot: float,
        as_of_ts: datetime
    ) -> Optional[float]:
        """
        Computes Term Slope: IV_90d - IV_30d
        """
        iv_30 = IVPointService.compute_atm_iv_target_from_chain(chain_results, spot, as_of_ts, target_dte=30.0)
        iv_90 = IVPointService.compute_atm_iv_target_from_chain(chain_results, spot, as_of_ts, target_dte=90.0)

        if iv_30.get('iv') is not None and iv_90.get('iv') is not None:
            return iv_90['iv'] - iv_30['iv']

        return None

    @staticmethod
    def _compute_atm_iv_for_expiry(contracts: List[Dict], spot: float) -> Tuple[Optional[float], Optional[float], int]:
        """
        Computes ATM IV for a specific expiry by finding closest strike to spot.
        """
        if not contracts:
            return None, None, 100

        # Organize by strike
        by_strike = {}
        for c in contracts:
            details = c.get('details', {})
            strike = details.get('strike_price')
            if strike is None:
                continue

            if strike not in by_strike:
                by_strike[strike] = {'call': None, 'put': None}

            ctype = details.get('contract_type')

            greeks = c.get('greeks') or {}
            iv = c.get('implied_volatility') or greeks.get('iv')

            if iv and iv > 0:
                by_strike[strike][ctype] = iv

        if not by_strike:
            return None, None, 100

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
            penalty += 10
        elif iv_put:
            final_iv = iv_put
            penalty += 10
        else:
            return None, closest_strike, 100

        dist_pct = abs(closest_strike - spot) / spot
        if dist_pct > 0.05:
            penalty += int(dist_pct * 100)

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
            "iv": None,
            "iv_30d": None,
            "iv_method": "failed",
            "inputs": {"reason": reason}
        }
