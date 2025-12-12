from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
import numpy as np
import logging

logger = logging.getLogger(__name__)

class RegimeState(Enum):
    SUPPRESSED = "suppressed"
    NORMAL = "normal"
    ELEVATED = "elevated"
    SHOCK = "shock"
    REBOUND = "rebound"
    CHOP = "chop"

@dataclass
class GlobalRegimeSnapshot:
    as_of_ts: datetime
    state: RegimeState
    risk_score: float
    risk_scaler: float
    features: Dict[str, float] = field(default_factory=dict)

    def to_dict(self):
        return {
            "as_of_ts": self.as_of_ts.isoformat(),
            "state": self.state.value,
            "risk_score": self.risk_score,
            "risk_scaler": self.risk_scaler,
            "features": self.features
        }

@dataclass
class SymbolRegimeSnapshot:
    symbol: str
    as_of_ts: datetime
    state: RegimeState
    symbol_score: float
    features: Dict[str, float] = field(default_factory=dict)
    quality_flags: Dict[str, bool] = field(default_factory=dict)

    def to_dict(self):
        return {
            "symbol": self.symbol,
            "as_of_ts": self.as_of_ts.isoformat(),
            "state": self.state.value,
            "symbol_score": self.symbol_score,
            "features": self.features,
            "quality_flags": self.quality_flags
        }

class RegimeEngineV3:
    """
    Computes multi-factor regime states for global market and individual symbols.
    """

    # Global basket for proxy calculation if universe is missing
    GLOBAL_BASKET = ['SPY', 'QQQ', 'IWM', 'TLT', 'HYG', 'XLF', 'XLK', 'XLE']

    def __init__(self, market_data_service, iv_repository, iv_point_service):
        self.market_data = market_data_service
        self.iv_repo = iv_repository
        self.iv_point_service = iv_point_service

    def compute_global_snapshot(self, as_of_ts: datetime, universe_symbols: List[str] | None = None) -> GlobalRegimeSnapshot:
        """
        Computes global market regime based on SPY trend, volatility, correlation, and breadth.
        """
        # 1. Fetch SPY Data
        spy_bars = self.market_data.get_historical_prices("SPY", days=100) # Need enough for SMA50 + Slope

        # 2. Compute Core Features
        features = {}

        # Trend Features
        if spy_bars and len(spy_bars) >= 50:
            closes = [b['close'] for b in spy_bars]
            sma20 = np.mean(closes[-20:])
            sma50 = np.mean(closes[-50:])
            features['spy_sma20_dist'] = (closes[-1] / sma20) - 1.0
            features['spy_sma50_dist'] = (closes[-1] / sma50) - 1.0

            # Slope (last 10 days)
            y = closes[-10:]
            x = np.arange(len(y))
            slope = np.polyfit(x, y, 1)[0]
            features['spy_slope_10d'] = slope / closes[-1] # Normalize
        else:
            features['spy_sma20_dist'] = 0.0
            features['spy_sma50_dist'] = 0.0
            features['spy_slope_10d'] = 0.0

        # Volatility Features (Realized)
        if spy_bars and len(spy_bars) >= 60:
            returns = np.diff(np.log([b['close'] for b in spy_bars]))
            features['rv_20d'] = np.std(returns[-20:]) * np.sqrt(252)
            features['rv_60d'] = np.std(returns[-60:]) * np.sqrt(252)
        else:
            features['rv_20d'] = 0.15 # Fallback
            features['rv_60d'] = 0.15

        # Breadth & Correlation
        # Use universe_symbols if provided, else basket
        target_symbols = universe_symbols if universe_symbols else self.GLOBAL_BASKET
        # Limit to max 50 symbols for performance if universe is huge
        if len(target_symbols) > 50:
             # Deterministic sample based on sorting
             target_symbols = sorted(target_symbols)[:50]

        # Breadth (% > SMA50) & Correlation
        breadth_score = 0.5
        avg_corr = 0.0

        # This part requires fetching bars for all target symbols.
        # In a real implementation, this should be optimized/batched.
        # For V3, assuming market_data has a batch fetch or we iterate.
        # Ideally, market_data_service should support batch fetching.
        # Here we will do a simplified best-effort.

        valid_symbols = 0
        above_sma50 = 0
        returns_matrix = []

        for sym in target_symbols:
            # Skip SPY as we already have it
            if sym == 'SPY': continue

            bars = self.market_data.get_historical_prices(sym, days=60)
            if not bars or len(bars) < 50:
                continue

            closes = [b['close'] for b in bars]
            sma50_sym = np.mean(closes[-50:])
            if closes[-1] > sma50_sym:
                above_sma50 += 1
            valid_symbols += 1

            if len(bars) >= 21:
                rets = np.diff(np.log([b['close'] for b in bars[-21:]]))
                returns_matrix.append(rets)

        if valid_symbols > 0:
            breadth_score = above_sma50 / valid_symbols

        if len(returns_matrix) > 2:
            # Pad or truncate to match lengths if necessary, but here we requested same lookback
            # Correlation matrix
            try:
                min_len = min(len(r) for r in returns_matrix)
                trimmed_rets = [r[-min_len:] for r in returns_matrix]
                corr_mat = np.corrcoef(trimmed_rets)
                # Upper triangle average
                avg_corr = np.mean(corr_mat[np.triu_indices(len(corr_mat), k=1)])
            except Exception:
                avg_corr = 0.5 # Fallback

        features['breadth_sma50'] = breadth_score
        features['avg_correlation'] = avg_corr

        # 3. Liquidity Stress (Proxy via VIX or similar if available, else omit)
        # Assuming VIX is in IV repository or passed in.
        # For now, let's omit specialized liquidity stress unless we have VIX data handy.

        # 4. Normalize to Z-Scores / Risk Score
        # Simple rule-based weighting for V3

        # Trend Score: Positive is good (low risk), Negative is bad (high risk)
        trend_signal = (features['spy_sma50_dist'] * 0.5) + (features['spy_slope_10d'] * 50)
        # Vol Score: Low is good, High is bad
        vol_signal = -1 * (features['rv_20d'] - 0.15) * 10
        # Breadth: High is good
        breadth_signal = (breadth_score - 0.5) * 2
        # Correlation: Low is good (diversification), High is bad (contagion)
        corr_signal = -1 * (avg_corr - 0.4) * 2

        # Aggregate Risk Score (Higher = Safer in this logic? No, let's make Higher = Riskier)
        # Let's invert the signals: Higher value = Higher Risk

        risk_score = 0.0
        # Check signs. SMA50_dist < 0 means we are below SMA50 (bearish) -> ADD Risk
        risk_score += (features['spy_sma50_dist'] < 0) * 2.0 # Below SMA50
        risk_score += (features['spy_slope_10d'] < 0) * 1.0 # Negative slope

        # Vol: Higher is riskier
        risk_score += (features['rv_20d'] > 0.20) * 2.0 # High Vol
        risk_score += (features['rv_20d'] > 0.35) * 3.0 # Extreme Vol

        # Breadth: Lower is riskier
        risk_score += (breadth_score < 0.3) * 1.5 # Weak Breadth

        # Correlation: Higher is riskier (panic convergence)
        risk_score += (avg_corr > 0.7) * 1.5 # High Correlation

        features['raw_risk_score'] = risk_score

        # 5. Classify State
        state = RegimeState.NORMAL

        # Simple decision tree
        if risk_score > 6.0:
            state = RegimeState.SHOCK
        elif risk_score > 3.0:
            state = RegimeState.ELEVATED
        elif risk_score < 1.0 and features['rv_20d'] < 0.12:
            state = RegimeState.SUPPRESSED

        # Detect Rebound: Recent shock/elevated but strong short-term slope/breadth
        # E.g. 5d slope is very positive while 20d vol is still high
        if state in [RegimeState.ELEVATED, RegimeState.SHOCK]:
             # Need short term slope
             short_slope = features['spy_slope_10d']
             if short_slope > 0.005: # Strong up move
                 state = RegimeState.REBOUND

        # Detect Chop: Normal/Elevated but flat slope and mean reversion
        if state in [RegimeState.NORMAL, RegimeState.ELEVATED]:
            if abs(features['spy_slope_10d']) < 0.001 and features['rv_20d'] > 0.15:
                state = RegimeState.CHOP

        # 6. Risk Scaler
        scaler_map = {
            RegimeState.SUPPRESSED: 1.2, # Lever up slightly? Or just strict sizing.
            RegimeState.NORMAL: 1.0,
            RegimeState.ELEVATED: 0.8,
            RegimeState.CHOP: 0.7,
            RegimeState.REBOUND: 0.6, # Caution on rebounds
            RegimeState.SHOCK: 0.4    # Defensive
        }
        risk_scaler = scaler_map.get(state, 1.0)

        return GlobalRegimeSnapshot(
            as_of_ts=as_of_ts,
            state=state,
            risk_score=risk_score,
            risk_scaler=risk_scaler,
            features=features
        )

    def compute_symbol_snapshot(self, symbol: str, as_of_ts: datetime, global_snapshot: Optional[GlobalRegimeSnapshot] = None) -> SymbolRegimeSnapshot:
        """
        Computes regime state for a specific symbol using IV surface and realized vol.
        """
        features = {}
        flags = {}

        # 1. Get IV Context (Rank)
        iv_ctx = self.iv_repo.get_iv_context(symbol)
        features['iv_rank'] = iv_ctx.get('iv_rank', 50.0) if iv_ctx else 50.0
        features['atm_iv_30d'] = iv_ctx.get('current_iv', 0.0) if iv_ctx else 0.0

        # 2. Realized Vol (20d)
        bars = self.market_data.get_historical_prices(symbol, days=30)
        if bars and len(bars) >= 21:
            rets = np.diff(np.log([b['close'] for b in bars]))
            rv_20d = np.std(rets[-20:]) * np.sqrt(252)
            features['rv_20d'] = rv_20d
        else:
            features['rv_20d'] = features['atm_iv_30d'] # Fallback
            flags['rv_missing'] = True

        # 3. IV-RV Spread
        if features['atm_iv_30d'] > 0:
            features['iv_rv_spread'] = features['atm_iv_30d'] - features['rv_20d']
        else:
            features['iv_rv_spread'] = 0.0

        # 4. IV Surface Features (Skew, Term)
        # Fetch option chain snapshot if possible, or use pre-computed points
        # For V3, let's assume we use iv_point_service or market_data to get a chain
        # If live, we might want to fetch the chain. If not, use last point.

        # Try to get latest point from service first
        latest_point = self.iv_point_service.get_latest_point(symbol)

        if latest_point:
             # If point is recent (< 24h), use it
             # For now, just use it
             features['skew_25d'] = latest_point.get('skew_25d', 0.0)
             features['term_slope'] = latest_point.get('term_slope', 0.0)
        else:
             # Try to compute from live chain if possible (or mock if dev)
             # This is expensive, so maybe we rely on what's available
             features['skew_25d'] = 0.0
             features['term_slope'] = 0.0
             flags['surface_missing'] = True

        # 5. Classify Symbol State
        # Logic:
        # High IV Rank (>80) -> ELEVATED or SHOCK
        # High IV-RV Spread -> Earnings/Event (ELEVATED)
        # Low IV Rank (<20) -> SUPPRESSED

        sym_score = 0.0
        state = RegimeState.NORMAL

        if features['iv_rank'] > 80:
            state = RegimeState.ELEVATED
            sym_score += 2.0
        elif features['iv_rank'] > 95:
            state = RegimeState.SHOCK
            sym_score += 4.0
        elif features['iv_rank'] < 20:
            state = RegimeState.SUPPRESSED
            sym_score -= 1.0

        # Skew adjustment
        if features['skew_25d'] > 0.05: # High skew (puts expensive)
            sym_score += 1.0

        # 6. Override with Global Context if correlated
        # If global is SHOCK, symbol is likely SHOCK unless beta is negative
        # For now, just return local state, get_effective_regime handles blending

        return SymbolRegimeSnapshot(
            symbol=symbol,
            as_of_ts=as_of_ts,
            state=state,
            symbol_score=sym_score,
            features=features,
            quality_flags=flags
        )

    def get_effective_regime(self, symbol_snap: SymbolRegimeSnapshot, global_snap: GlobalRegimeSnapshot) -> RegimeState:
        """
        Determines the effective regime for trading decisions, usually taking the 'worse' (riskier)
        of the global vs local state, with some nuance.
        """
        # Risk hierarchy
        risk_rank = {
            RegimeState.SUPPRESSED: 1,
            RegimeState.NORMAL: 2,
            RegimeState.REBOUND: 3,
            RegimeState.CHOP: 4,
            RegimeState.ELEVATED: 5,
            RegimeState.SHOCK: 6
        }

        g_rank = risk_rank.get(global_snap.state, 2)
        s_rank = risk_rank.get(symbol_snap.state, 2)

        # If global is SHOCK, it overrides everything to SHOCK or REBOUND
        if global_snap.state == RegimeState.SHOCK:
            return RegimeState.SHOCK

        # If global is CHOP, individual names might still be trending, but caution needed.
        if global_snap.state == RegimeState.CHOP:
             if s_rank >= 5: return symbol_snap.state # Symbol is breaking out/down
             return RegimeState.CHOP

        # Default: Max risk
        if s_rank > g_rank:
            return symbol_snap.state

        return global_snap.state

    def map_to_scoring_regime(self, regime: RegimeState) -> str:
        """
        Maps V3 regime to legacy V2 scoring buckets (normal/high_vol/panic).
        """
        mapping = {
            RegimeState.SUPPRESSED: 'normal',
            RegimeState.NORMAL: 'normal',
            RegimeState.REBOUND: 'high_vol', # Rebounds are volatile
            RegimeState.CHOP: 'normal', # Chop is annoying but usually not panic vol
            RegimeState.ELEVATED: 'high_vol',
            RegimeState.SHOCK: 'panic'
        }
        return mapping.get(regime, 'normal')
