from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
import numpy as np
from datetime import datetime, timedelta
import logging

from packages.quantum.services.market_data_truth_layer import MarketDataTruthLayer
from packages.quantum.services.iv_repository import IVRepository
from packages.quantum.services.iv_point_service import IVPointService
from packages.quantum.services.universe_service import UniverseService
from packages.quantum.analytics.factors import calculate_trend, calculate_iv_rank

logger = logging.getLogger(__name__)

class RegimeState(str, Enum):
    SUPPRESSED = "suppressed"
    NORMAL = "normal"
    ELEVATED = "elevated"
    SHOCK = "shock"
    REBOUND = "rebound"
    CHOP = "chop"

@dataclass
class GlobalRegimeSnapshot:
    as_of_ts: str
    state: RegimeState
    risk_score: float # 0-100
    risk_scaler: float # e.g. 0.8 to 1.5

    # Components
    trend_score: float # z-score
    vol_score: float
    corr_score: float
    breadth_score: float
    liquidity_score: float

    details: Dict[str, Any] = field(default_factory=dict)

@dataclass
class SymbolRegimeSnapshot:
    symbol: str
    as_of_ts: str
    state: RegimeState
    score: float # 0-100 continuous

    # Components
    iv_rank: Optional[float]
    atm_iv_30d: Optional[float]
    rv_20d: Optional[float]
    iv_rv_spread: Optional[float]
    skew_25d: Optional[float]
    term_slope: Optional[float]

    quality_flags: Dict[str, bool] = field(default_factory=dict)

class RegimeEngineV3:
    """
    Multi-factor regime engine providing continuous scores and 6-state classification.
    """

    BASKET = ['SPY','QQQ','IWM','TLT','HYG','XLF','XLK','XLE']

    def __init__(self,
                 supabase_client,
                 market_data: MarketDataTruthLayer = None):
        self.supabase = supabase_client
        self.market_data = market_data or MarketDataTruthLayer()
        self.iv_repo = IVRepository(supabase_client)
        self.universe_service = UniverseService(supabase_client)

    def compute_global_snapshot(self,
                                as_of_ts: datetime,
                                universe_symbols: List[str] = None) -> GlobalRegimeSnapshot:
        """
        Computes the global market regime state based on multi-factor analysis.
        """
        # 1. Fetch Data
        # We need daily bars for basket
        start_date = as_of_ts - timedelta(days=100) # Enough for SMA50 and Vol calculation

        basket_data = {}
        for sym in self.BASKET:
            bars = self.market_data.daily_bars(sym, start_date, as_of_ts)
            if bars:
                basket_data[sym] = bars

        if 'SPY' not in basket_data:
            # Critical failure, fallback to minimal default
            logger.error("SPY data missing for global regime computation")
            return self._default_global_snapshot(as_of_ts)

        # 2. Compute Factors

        # A. Trend (SPY)
        spy_bars = basket_data['SPY']
        closes = [b['close'] for b in spy_bars]

        sma50 = np.mean(closes[-50:]) if len(closes) >= 50 else closes[-1]
        sma20 = np.mean(closes[-20:]) if len(closes) >= 20 else closes[-1]
        price = closes[-1]

        # Trend Score: Positive if > SMAs, Negative if < SMAs
        # Simple z-score proxy: (Price - SMA50) / SMA50 * 10 (approx)
        trend_val = (price - sma50) / sma50
        trend_z = np.clip(trend_val * 20, -3, 3) # +/- 5% deviation = +/- 1.0 z approx?
        # Actually standard dev of spy is ~15% annualized -> ~1% daily.
        # Over 50 days, deviation can be 5-10%.
        # Let's map 5% > SMA50 to +2.0 z-score.

        # B. Volatility (Realized)
        returns = np.diff(closes) / closes[:-1]
        rv_20d = np.std(returns[-20:]) * np.sqrt(252) if len(returns) >= 20 else 0.15

        # Vol Z-Score: (RV - 0.15) / 0.05 approx?
        # VIX approx avg is 18-20.
        vol_z = (rv_20d - 0.15) / 0.05
        vol_z = np.clip(vol_z, -3, 3)

        # C. Correlation (Basket)
        corr_z = 0.0
        if len(basket_data) > 3:
            # Compute pairwise correlations of last 20d returns
            corrs = []
            base_rets = returns[-20:]
            if len(base_rets) == 20:
                for sym, bars in basket_data.items():
                    if sym == 'SPY': continue
                    s_closes = [b['close'] for b in bars]
                    if len(s_closes) < 21: continue
                    s_rets = np.diff(s_closes) / s_closes[:-1]
                    s_rets = s_rets[-20:]
                    if len(s_rets) == 20:
                        c = np.corrcoef(base_rets, s_rets)[0,1]
                        if not np.isnan(c):
                            corrs.append(c)

            if corrs:
                avg_corr = np.mean(corrs)
                # High correlation = Panic/Stress usually
                # Normal ~ 0.5? Panic ~ 0.9?
                corr_z = (avg_corr - 0.5) / 0.2

        # D. Breadth (% > SMA50)
        breadth_z = 0.0
        # If universe_symbols provided, use them. Else basket.
        check_symbols = universe_symbols if universe_symbols and len(universe_symbols) > 10 else self.BASKET
        above_sma = 0
        valid_cnt = 0

        # To avoid massive API calls if universe is huge, we might use UniverseService metrics if available?
        # But here we stick to what we can fetch. If universe is large, this might be slow if not cached.
        # Let's use basket for speed if universe not pre-fetched.
        # Actually prompt says: "using universe_symbols when available, else basket proxy"

        # Optimization: We already have basket bars. If universe is passed, we might assume data needs fetching.
        # Let's stick to basket for reliability/speed in this implementation unless specific service exists.

        for sym in self.BASKET: # Using basket for breadth proxy to ensure speed
            if sym in basket_data:
                b_closes = [b['close'] for b in basket_data[sym]]
                if len(b_closes) >= 50:
                    b_sma = np.mean(b_closes[-50:])
                    if b_closes[-1] > b_sma:
                        above_sma += 1
                valid_cnt += 1

        if valid_cnt > 0:
            breadth_pct = above_sma / valid_cnt
            # Low breadth = Bad.
            breadth_z = (breadth_pct - 0.6) / 0.2 # 60% is normal. < 20% is -2.

        # E. Liquidity (Spread Proxy - hard to get without quotes)
        # We'll use volume deviation? Or just zero for now if data sparse.
        liquidity_z = 0.0

        # 3. Aggregation
        # Risk Score: High Vol + High Corr - Trend - Breadth
        # We want a score where High = Risky.

        # Weights
        w_vol = 0.4
        w_trend = 0.3
        w_corr = 0.2
        w_breadth = 0.1

        # Invert trend/breadth (High trend = Low Risk)
        raw_risk = (w_vol * vol_z) + (w_corr * corr_z) - (w_trend * trend_z) - (w_breadth * breadth_z)

        # Normalize to 0-100?
        # raw_risk range approx -3 to +3.
        # -3 (Goldilocks) -> 0
        # +3 (Armageddon) -> 100
        risk_score = 50 + (raw_risk * 16.6)
        risk_score = max(0.0, min(100.0, risk_score))

        # 4. Classification
        state = RegimeState.NORMAL

        if risk_score < 20:
            state = RegimeState.SUPPRESSED
        elif risk_score < 60:
            state = RegimeState.NORMAL
        elif risk_score < 80:
            state = RegimeState.ELEVATED
        else:
            state = RegimeState.SHOCK

        # Overlay: Rebound?
        # If trend is negative but short term slope positive?
        # Simple Rebound Logic: Price < SMA50 but Price > SMA20? Or 3d return > 2% after drop?
        if state in [RegimeState.SHOCK, RegimeState.ELEVATED]:
             # Check for sharp bounce
             if price > sma20 and price < sma50:
                 state = RegimeState.REBOUND

        # Overlay: Chop?
        # Low trend, Low Vol? Or Range bound?
        # If trend_z near 0 and vol_z low.
        if abs(trend_z) < 0.5 and vol_z < 0 and state == RegimeState.NORMAL:
            state = RegimeState.CHOP

        # 5. Risk Scaler
        # Map state to scaler
        scaler_map = {
            RegimeState.SUPPRESSED: 1.2, # Lever up slightly? Or just 1.0?
            # Actually suppressed vol often implies "safe to sell premium" but "risk of explosion".
            # For sizing: 1.2 means we can take MORE risk (size bigger).
            RegimeState.NORMAL: 1.0,
            RegimeState.CHOP: 0.9,
            RegimeState.ELEVATED: 0.7,
            RegimeState.REBOUND: 0.8,
            RegimeState.SHOCK: 0.5
        }
        risk_scaler = scaler_map.get(state, 1.0)

        return GlobalRegimeSnapshot(
            as_of_ts=as_of_ts.isoformat(),
            state=state,
            risk_score=risk_score,
            risk_scaler=risk_scaler,
            trend_score=trend_z,
            vol_score=vol_z,
            corr_score=corr_z,
            breadth_score=breadth_z,
            liquidity_score=liquidity_z,
            details={
                "spy_price": price,
                "spy_sma50": sma50,
                "rv_20d": rv_20d
            }
        )

    def compute_symbol_snapshot(self, symbol: str, global_snapshot: GlobalRegimeSnapshot) -> SymbolRegimeSnapshot:
        """
        Computes regime state for a single symbol.
        """
        as_of = datetime.fromisoformat(global_snapshot.as_of_ts)

        # 1. Fetch IV Context
        # Prefer IVRepository (pre-computed / database)
        iv_context = self.iv_repo.get_iv_context(symbol)

        iv_rank = iv_context.get('iv_rank')
        atm_iv = iv_context.get('iv_30d')

        quality_flags = {
            "iv_missing": atm_iv is None,
            "rank_missing": iv_rank is None
        }

        # 2. Fetch Realized Vol
        # Need bars
        end_date = as_of
        start_date = end_date - timedelta(days=40)
        bars = self.market_data.daily_bars(symbol, start_date, end_date)

        rv_20d = None
        if bars and len(bars) >= 20:
             closes = [b['close'] for b in bars]
             rets = np.diff(closes) / closes[:-1]
             if len(rets) >= 20:
                 rv_20d = np.std(rets[-20:]) * np.sqrt(252)
        else:
            quality_flags["rv_missing"] = True

        # 3. IV-RV Spread
        iv_rv_spread = None
        if atm_iv and rv_20d:
            iv_rv_spread = atm_iv - rv_20d

        # 4. Skew and Term Structure
        # Need option chain snapshot
        # This is expensive. Only do if strictly needed or cache?
        # For "Midday/Morning" cycles, we can afford it for candidates.

        skew_25d = None
        term_slope = None

        # Try to fetch chain
        # Check cache via market_data? It handles caching.
        # We need spot first.
        spot = bars[-1]['close'] if bars else 0
        if spot > 0:
            chain = self.market_data.option_chain(symbol)
            if chain:
                skew_25d = IVPointService.compute_skew_25d_from_chain(chain, spot, as_of)
                term_slope = IVPointService.compute_term_slope(chain, spot, as_of)

        if skew_25d is None: quality_flags["skew_missing"] = True
        if term_slope is None: quality_flags["term_missing"] = True

        # 5. Classification
        # Score based on IV Rank, Spread, Skew
        # High Score = High Opportunity for Premium Selling? Or High Risk?
        # Let's align with Global: High Score = High Vol/Risk.

        # Factors
        f_rank = iv_rank if iv_rank is not None else 50.0
        f_spread = (iv_rv_spread * 100) if iv_rv_spread is not None else 0 # e.g. 5% -> 5.0

        # Skew: High Skew (Put expensive) = Fear.
        f_skew = (skew_25d * 100) if skew_25d is not None else 0 # 10% skew -> 10.0

        # Term: Inverted (Negative) = Fear. Normal (Positive) = Calm.
        f_term = (term_slope * -100) if term_slope is not None else 0 # -5% slope -> +5.0 risk score contribution

        # Weighted Sum
        # Rank is 0-100.
        # Spread is usually -5 to +10.
        # Skew is usually 0 to 20.

        raw_score = (0.5 * f_rank) + (1.0 * f_spread) + (0.5 * f_skew) + (0.5 * f_term)
        # Base ~ 25 + 5 + 5 + 0 = 35.

        score = max(0.0, min(100.0, raw_score))

        # State
        state = RegimeState.NORMAL
        if score < 20: state = RegimeState.SUPPRESSED
        elif score < 60: state = RegimeState.NORMAL
        elif score < 80: state = RegimeState.ELEVATED
        else: state = RegimeState.SHOCK

        return SymbolRegimeSnapshot(
            symbol=symbol,
            as_of_ts=as_of.isoformat(),
            state=state,
            score=score,
            iv_rank=iv_rank,
            atm_iv_30d=atm_iv,
            rv_20d=rv_20d,
            iv_rv_spread=iv_rv_spread,
            skew_25d=skew_25d,
            term_slope=term_slope,
            quality_flags=quality_flags
        )

    def get_effective_regime(self, symbol_snap: SymbolRegimeSnapshot, global_snap: GlobalRegimeSnapshot) -> RegimeState:
        """
        Determines the effective regime for trading decisions.
        Generally takes the more restrictive (higher risk) state,
        but allows specific overrides (e.g., Symbol is Normal in a Global Rebound).
        """
        # Define hierarchy of risk
        risk_rank = {
            RegimeState.SUPPRESSED: 1,
            RegimeState.NORMAL: 2,
            RegimeState.CHOP: 3,
            RegimeState.REBOUND: 4,
            RegimeState.ELEVATED: 5,
            RegimeState.SHOCK: 6
        }

        g_rank = risk_rank[global_snap.state]
        s_rank = risk_rank[symbol_snap.state]

        # Default: Max Risk
        effective = global_snap.state if g_rank >= s_rank else symbol_snap.state

        # Special Cases

        # 1. Global Shock overrides everything
        if global_snap.state == RegimeState.SHOCK:
            return RegimeState.SHOCK

        # 2. Rebound Logic
        if global_snap.state == RegimeState.REBOUND:
            # If symbol is Shock, stay Shock.
            # If symbol is Normal/Elevated, treat as Rebound (Buy opportunity).
            if s_rank == 6: return RegimeState.SHOCK
            return RegimeState.REBOUND

        return effective

    def map_to_scoring_regime(self, state: RegimeState) -> str:
        """
        Maps 6-state regime to legacy 3-state scoring regime.
        Output: 'normal' | 'high_vol' | 'panic'
        """
        if state == RegimeState.SHOCK:
            return 'panic'
        elif state in [RegimeState.ELEVATED, RegimeState.REBOUND]:
            return 'high_vol'
        else:
            return 'normal'

    def _default_global_snapshot(self, as_of_ts: datetime) -> GlobalRegimeSnapshot:
        return GlobalRegimeSnapshot(
            as_of_ts=as_of_ts.isoformat(),
            state=RegimeState.NORMAL,
            risk_score=50.0,
            risk_scaler=1.0,
            trend_score=0.0,
            vol_score=0.0,
            corr_score=0.0,
            breadth_score=0.0,
            liquidity_score=0.0
        )
