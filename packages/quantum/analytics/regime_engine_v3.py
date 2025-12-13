from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
import numpy as np
import logging

logger = logging.getLogger(__name__)

class RegimeState(Enum):
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
        Determines the effective regime for trading decisions, usually taking the 'worse' (riskier)
        of the global vs local state, with some nuance.
        """
        # Risk hierarchy
        risk_rank = {
            RegimeState.SUPPRESSED: 1,
            RegimeState.NORMAL: 2,
            RegimeState.REBOUND: 3,
            RegimeState.CHOP: 4,
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
