from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
import numpy as np
import logging

from packages.quantum.services.market_data_truth_layer import MarketDataTruthLayer
from packages.quantum.services.iv_repository import IVRepository
from packages.quantum.services.iv_point_service import IVPointService
from packages.quantum.services.universe_service import UniverseService
from packages.quantum.analytics.factors import calculate_trend, calculate_iv_rank
from packages.quantum.common_enums import RegimeState

logger = logging.getLogger(__name__)

# Removed local RegimeState definition in favor of common_enums.py

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

    features: Dict[str, float] = field(default_factory=dict)
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self):
        return {
            "as_of_ts": self.as_of_ts,
            "state": self.state.value,
            "risk_score": self.risk_score,
            "risk_scaler": self.risk_scaler,
            "features": self.features,
            "details": self.details
        }

@dataclass
class SymbolRegimeSnapshot:
    symbol: str
    as_of_ts: str
    state: RegimeState
    score: float # 0-100 continuous

    # Components
    iv_rank: Optional[float] = None
    atm_iv_30d: Optional[float] = None
    rv_20d: Optional[float] = None
    iv_rv_spread: Optional[float] = None
    skew_25d: Optional[float] = None
    term_slope: Optional[float] = None

    quality_flags: Dict[str, bool] = field(default_factory=dict)
    features: Dict[str, float] = field(default_factory=dict)

    def to_dict(self):
        return {
            "symbol": self.symbol,
            "as_of_ts": self.as_of_ts,
            "state": self.state.value,
            "score": self.score,
            "features": self.features,
            "quality_flags": self.quality_flags
        }

class RegimeEngineV3:
    """
    Computes multi-factor regime states for global market and individual symbols.
    """

    BASKET = ['SPY','QQQ','IWM','TLT','HYG','XLF','XLK','XLE']

    def __init__(self,
                 supabase_client=None, # Allow None for compatibility with some calls, but prefer passing it
                 market_data: MarketDataTruthLayer = None,
                 iv_repository: IVRepository = None,
                 iv_point_service: IVPointService = None):

        self.supabase = supabase_client
        # Allow passing dependencies directly or instantiating them
        self.market_data = market_data or MarketDataTruthLayer()
        self.iv_repo = iv_repository or (IVRepository(supabase_client) if supabase_client else None)
        self.iv_point_service = iv_point_service or (IVPointService(supabase_client) if supabase_client else None)
        self.universe_service = UniverseService(supabase_client) if supabase_client else None

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
        price = closes[-1]

        # Trend Score: Positive if > SMAs, Negative if < SMAs
        trend_val = (price - sma50) / sma50
        trend_z = np.clip(trend_val * 20, -3, 3)

        # B. Volatility (Realized)
        returns = np.diff(closes) / closes[:-1]
        rv_20d = np.std(returns[-20:]) * np.sqrt(252) if len(returns) >= 20 else 0.15

        vol_z = (rv_20d - 0.15) / 0.05
        vol_z = np.clip(vol_z, -3, 3)

        # C. Correlation (Basket)
        corr_z = 0.0
        if len(basket_data) > 3:
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
                corr_z = (avg_corr - 0.5) / 0.2

        # D. Breadth (% > SMA50)
        breadth_z = 0.0
        above_sma = 0
        valid_cnt = 0

        for sym in self.BASKET: # Using basket for breadth proxy
            if sym in basket_data:
                b_closes = [b['close'] for b in basket_data[sym]]
                if len(b_closes) >= 50:
                    b_sma = np.mean(b_closes[-50:])
                    if b_closes[-1] > b_sma:
                        above_sma += 1
                valid_cnt += 1

        if valid_cnt > 0:
            breadth_pct = above_sma / valid_cnt
            breadth_z = (breadth_pct - 0.6) / 0.2

        liquidity_z = 0.0

        # 3. Aggregation
        w_vol = 0.4
        w_trend = 0.3
        w_corr = 0.2
        w_breadth = 0.1

        # Invert trend/breadth (High trend = Low Risk)
        raw_risk = (w_vol * vol_z) + (w_corr * corr_z) - (w_trend * trend_z) - (w_breadth * breadth_z)

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
        if state in [RegimeState.SHOCK, RegimeState.ELEVATED]:
             sma20 = np.mean(closes[-20:]) if len(closes) >= 20 else closes[-1]
             if price > sma20 and price < sma50:
                 state = RegimeState.REBOUND

        # Overlay: Chop?
        if abs(trend_z) < 0.5 and vol_z < 0 and state == RegimeState.NORMAL:
            state = RegimeState.CHOP

        # 5. Risk Scaler
        scaler_map = {
            RegimeState.SUPPRESSED: 1.2,
            RegimeState.NORMAL: 1.0,
            RegimeState.CHOP: 0.9,
            RegimeState.ELEVATED: 0.7,
            RegimeState.REBOUND: 0.8,
            RegimeState.SHOCK: 0.5
        }
        risk_scaler = scaler_map.get(state, 1.0)

        features = {
            "trend_z": trend_z,
            "vol_z": vol_z,
            "corr_z": corr_z,
            "breadth_z": breadth_z,
            "liquidity_z": liquidity_z
        }

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
            features=features,
            details={
                "spy_price": price,
                "spy_sma50": sma50,
                "rv_20d": rv_20d
            }
        )

    def compute_symbol_snapshot(self, symbol: str, global_snapshot: GlobalRegimeSnapshot, existing_bars: List[Dict] = None, iv_context: Dict[str, Any] = None) -> SymbolRegimeSnapshot:
        """
        Computes regime state for a single symbol.
        Accepts optional `existing_bars` and `iv_context` to avoid redundant API calls.
        """
        as_of = datetime.fromisoformat(global_snapshot.as_of_ts)

        # 1. Fetch IV Context (Use prefetched or fetch now)
        if not iv_context:
             iv_context = self.iv_repo.get_iv_context(symbol) if self.iv_repo else {}

        iv_rank = iv_context.get('iv_rank')
        atm_iv = iv_context.get('iv_30d')

        quality_flags = {
            "iv_missing": atm_iv is None,
            "rank_missing": iv_rank is None
        }

        # 2. Fetch Realized Vol
        bars = existing_bars
        if not bars:
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
        skew_25d = None
        term_slope = None

        # Only try if we have spot
        spot = bars[-1]['close'] if bars else 0
        if spot > 0 and self.iv_point_service:
             # Just use point service if available as shortcut
             # Not implementing full chain fetch here to keep it simple
             pass

        if skew_25d is None: quality_flags["skew_missing"] = True
        if term_slope is None: quality_flags["term_missing"] = True

        # 5. Classification
        f_rank = iv_rank if iv_rank is not None else 50.0
        f_spread = (iv_rv_spread * 100) if iv_rv_spread is not None else 0
        f_skew = 0 # Default
        f_term = 0 # Default

        raw_score = (0.5 * f_rank) + (1.0 * f_spread) + (0.5 * f_skew) + (0.5 * f_term)
        score = max(0.0, min(100.0, raw_score))

        state = RegimeState.NORMAL
        if score < 20: state = RegimeState.SUPPRESSED
        elif score < 60: state = RegimeState.NORMAL
        elif score < 80: state = RegimeState.ELEVATED
        else: state = RegimeState.SHOCK

        features = {
            "iv_rank": f_rank,
            "iv_rv_spread": f_spread,
            "skew": f_skew,
            "term": f_term
        }

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
            quality_flags=quality_flags,
            features=features
        )

    def get_effective_regime(self, symbol_snap: SymbolRegimeSnapshot, global_snap: GlobalRegimeSnapshot) -> RegimeState:
        """
        Determines the effective regime for trading decisions.
        """
        risk_rank = {
            RegimeState.SUPPRESSED: 1,
            RegimeState.NORMAL: 2,
            RegimeState.CHOP: 3,
            RegimeState.REBOUND: 4,
            RegimeState.ELEVATED: 5,
            RegimeState.SHOCK: 6
        }

        g_rank = risk_rank.get(global_snap.state, 2)
        s_rank = risk_rank.get(symbol_snap.state, 2)

        if global_snap.state == RegimeState.SHOCK:
            return RegimeState.SHOCK

        if global_snap.state == RegimeState.REBOUND:
            if s_rank == 6: return RegimeState.SHOCK
            return RegimeState.REBOUND

        effective = global_snap.state if g_rank >= s_rank else symbol_snap.state
        return effective

    def map_to_scoring_regime(self, state: RegimeState) -> str:
        """
        Maps 6-state regime to legacy 3-state scoring regime.
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
