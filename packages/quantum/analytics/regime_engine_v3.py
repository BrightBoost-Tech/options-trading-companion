from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
import numpy as np
import logging
import concurrent.futures
import math
import os

from packages.quantum.services.market_data_truth_layer import MarketDataTruthLayer
from packages.quantum.services.iv_repository import IVRepository
from packages.quantum.services.iv_point_service import IVPointService
from packages.quantum.services.universe_service import UniverseService
from packages.quantum.analytics.factors import calculate_trend, calculate_iv_rank
from packages.quantum.common_enums import RegimeState

logger = logging.getLogger(__name__)

# V4 Engine Version
ENGINE_VERSION = "v4"

# Liquidity z-score constants
LIQUIDITY_BASELINE_SPREAD = 0.002  # 0.2% median spread = neutral (z=0)
LIQUIDITY_SCALE = 0.001            # 0.1% per z-unit

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
        # V4: Include components dict with z-scores and intermediates for DB persistence
        components = {
            "trend_z": self.trend_score,
            "vol_z": self.vol_score,
            "corr_z": self.corr_score,
            "breadth_z": self.breadth_score,
            "liquidity_z": self.liquidity_score,
        }
        # Add intermediates from details if available
        if self.details:
            if "rv_20d" in self.details:
                components["rv_20d"] = self.details["rv_20d"]
            if "avg_corr" in self.details:
                components["avg_corr"] = self.details["avg_corr"]
            if "breadth_pct" in self.details:
                components["breadth_pct"] = self.details["breadth_pct"]
            if "median_spread_pct" in self.details:
                components["median_spread_pct"] = self.details["median_spread_pct"]

        return {
            "as_of_ts": self.as_of_ts,
            "state": self.state.value,
            "risk_score": self.risk_score,
            "risk_scaler": self.risk_scaler,
            "components": components,
            "details": self.details,
            "engine_version": ENGINE_VERSION,
            # Keep features for backward compatibility
            "features": self.features,
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
        # V4: Include metrics dict with all symbol-level measurements
        metrics = {
            "iv_rank": self.iv_rank,
            "atm_iv_30d": self.atm_iv_30d,
            "rv_20d": self.rv_20d,
            "iv_rv_spread": self.iv_rv_spread,
            "skew_25d": self.skew_25d,
            "term_slope": self.term_slope,
        }
        # Add scoring inputs from features
        if self.features:
            metrics["f_rank"] = self.features.get("iv_rank")
            metrics["f_spread"] = self.features.get("iv_rv_spread")
            metrics["f_skew"] = self.features.get("skew")
            metrics["f_term"] = self.features.get("term")

        return {
            "symbol": self.symbol,
            "as_of_ts": self.as_of_ts,
            "state": self.state.value,
            "score": self.score,
            "metrics": metrics,
            "quality_flags": self.quality_flags,
            "engine_version": ENGINE_VERSION,
            # Keep features for backward compatibility
            "features": self.features,
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

        # Bolt Optimization: Fetch basket data in parallel
        # This reduces global scan latency from ~1.6s to ~0.2s by executing 8 requests concurrently
        def fetch_basket_bars(sym):
            try:
                bars = self.market_data.daily_bars(sym, start_date, as_of_ts)
                return sym, bars
            except Exception as e:
                logger.warning(f"Failed to fetch basket data for {sym}: {e}")
                return sym, None

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(self.BASKET)) as executor:
            future_to_sym = {executor.submit(fetch_basket_bars, sym): sym for sym in self.BASKET}
            for future in concurrent.futures.as_completed(future_to_sym):
                sym, bars = future.result()
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

        # Bolt Optimization: Use sum() / len() for small lists (20x faster than np.mean)
        sma50 = sum(closes[-50:]) / 50.0 if len(closes) >= 50 else closes[-1]
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
        avg_corr = None
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
                avg_corr = float(np.mean(corrs))
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

        breadth_pct = 0.6  # default neutral
        if valid_cnt > 0:
            breadth_pct = above_sma / valid_cnt
            breadth_z = (breadth_pct - 0.6) / 0.2

        # E. Liquidity (V4: real computation from basket quote spreads)
        liquidity_z = 0.0
        median_spread_pct = None
        liquidity_issues = []

        try:
            # Fetch basket quotes for spread calculation
            basket_quotes = self.market_data.snapshot_many(self.BASKET)
            spread_pcts = []

            for sym in self.BASKET:
                snap = basket_quotes.get(sym, {})
                quote = snap.get("quote", {})
                bid = quote.get("bid")
                ask = quote.get("ask")
                mid = quote.get("mid")

                if bid is not None and ask is not None and mid is not None and mid > 0:
                    spread_pct = (ask - bid) / mid
                    if spread_pct >= 0:  # Valid spread
                        spread_pcts.append(spread_pct)
                else:
                    liquidity_issues.append(f"{sym}:missing_quote")

            if spread_pcts:
                # Compute median spread
                sorted_spreads = sorted(spread_pcts)
                n = len(sorted_spreads)
                if n % 2 == 0:
                    median_spread_pct = (sorted_spreads[n//2 - 1] + sorted_spreads[n//2]) / 2.0
                else:
                    median_spread_pct = sorted_spreads[n//2]

                # Liquidity z-score: higher spread = worse liquidity = higher risk
                # Neutral at 0.2% spread, each 0.1% adds 1 z-unit
                liquidity_z = (median_spread_pct - LIQUIDITY_BASELINE_SPREAD) / LIQUIDITY_SCALE
                liquidity_z = np.clip(liquidity_z, -3, 3)
            else:
                liquidity_issues.append("no_valid_spreads")

        except Exception as e:
            logger.warning(f"Failed to compute liquidity: {e}")
            liquidity_issues.append(f"error:{str(e)[:50]}")

        # 3. Aggregation (V4: includes liquidity with small weight)
        w_vol = 0.35      # Reduced from 0.4 to make room for liquidity
        w_trend = 0.30
        w_corr = 0.15     # Reduced from 0.2
        w_breadth = 0.10
        w_liq = 0.10      # New liquidity weight

        # Invert trend/breadth (High trend = Low Risk), liquidity adds to risk
        raw_risk = (w_vol * vol_z) + (w_corr * corr_z) + (w_liq * liquidity_z) - (w_trend * trend_z) - (w_breadth * breadth_z)

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
             # Bolt Optimization: Use sum() / len() for small lists
             sma20 = sum(closes[-20:]) / 20.0 if len(closes) >= 20 else closes[-1]
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

        # Build details dict with all intermediates for V4 DB persistence
        details = {
            "spy_price": price,
            "spy_sma50": sma50,
            "rv_20d": rv_20d,
            "breadth_pct": breadth_pct,
        }
        if avg_corr is not None:
            details["avg_corr"] = avg_corr
        if median_spread_pct is not None:
            details["median_spread_pct"] = median_spread_pct
        if liquidity_issues:
            details["liquidity_issues"] = liquidity_issues

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
            details=details
        )

    def _calculate_realized_volatility(self, closes: List[float]) -> Optional[float]:
        """
        Bolt Optimization: Calculates realized volatility using pure Python.
        This is ~5x faster than numpy for small lists (n~20) due to reduced overhead.
        """
        # Need at least 2 points to calculate returns, and we need 20 returns for RV.
        # So we need 21 price points.
        if len(closes) < 21:
            return None

        # Extract only the last 21 points
        subset = closes[-21:]

        rets = []
        for i in range(20):
            c_prev = subset[i]
            c_curr = subset[i+1]
            if c_prev == 0:
                rets.append(0.0)
            else:
                rets.append((c_curr - c_prev) / c_prev)

        # Standard Deviation of returns
        # ddof=0 for population std (matches np.std default)
        mean = sum(rets) / 20.0
        var = sum((r - mean) ** 2 for r in rets) / 20.0

        # Annualize
        return math.sqrt(var) * 15.874507866387544 # sqrt(252)

    def _adapt_chain_to_raw_schema(self, chain_results: List[Dict]) -> List[Dict]:
        """
        Adapts TruthLayer canonical chain format to raw-ish schema expected by IVPointService.

        TruthLayer format: {contract, underlying, strike, expiry, right, quote, iv, greeks, ...}
        IVPointService format: {details: {expiration_date, strike_price, contract_type}, greeks, implied_volatility}
        """
        adapted = []
        for c in chain_results:
            adapted_contract = {
                "details": {
                    "expiration_date": c.get("expiry"),
                    "strike_price": c.get("strike"),
                    "contract_type": c.get("right"),  # 'call' or 'put'
                },
                "greeks": c.get("greeks", {}),
                "implied_volatility": c.get("iv"),
            }
            # Also copy greeks.iv if available and implied_volatility is missing
            if adapted_contract["implied_volatility"] is None:
                greeks = c.get("greeks", {})
                adapted_contract["implied_volatility"] = greeks.get("iv")

            adapted.append(adapted_contract)
        return adapted

    def compute_symbol_snapshot(
        self,
        symbol: str,
        global_snapshot: GlobalRegimeSnapshot,
        existing_bars: List[Dict] = None,
        iv_context: Dict[str, Any] = None,
        chain_results: Optional[List[Dict]] = None,
        spot: Optional[float] = None
    ) -> SymbolRegimeSnapshot:
        """
        Computes regime state for a single symbol.

        V4 Enhancements:
        - Accepts optional `chain_results` to compute skew_25d and term_slope
        - Falls back to chain fetch if REGIME_V4_FETCH_CHAIN=1 env var is set
        - Accepts optional `existing_bars` and `iv_context` to avoid redundant API calls
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

        # Bolt Optimization: Use pure python implementation for realized volatility
        # to avoid numpy array creation overhead for every symbol scan.
        if bars and len(bars) >= 21:
             # Only extract what we need
             subset_bars = bars[-21:]
             closes = [b['close'] for b in subset_bars]
             rv_20d = self._calculate_realized_volatility(closes)
        else:
            quality_flags["rv_missing"] = True

        # 3. IV-RV Spread
        iv_rv_spread = None
        if atm_iv and rv_20d:
            iv_rv_spread = atm_iv - rv_20d

        # 4. Skew and Term Structure (V4: real computation from chain)
        skew_25d = None
        term_slope = None

        # Get spot price
        if spot is None:
            spot = bars[-1]['close'] if bars else 0

        # V4: Compute skew and term from chain if provided
        if chain_results and spot > 0:
            try:
                # Adapt TruthLayer chain to IVPointService format
                adapted_chain = self._adapt_chain_to_raw_schema(chain_results)

                # Compute skew_25d
                skew_25d = IVPointService.compute_skew_25d_from_chain(
                    adapted_chain, spot, as_of, target_dte=30.0
                )

                # Compute term_slope
                term_slope = IVPointService.compute_term_slope(
                    adapted_chain, spot, as_of
                )
            except Exception as e:
                logger.warning(f"Failed to compute skew/term for {symbol}: {e}")

        # V4: Optional fallback - fetch chain if env var set and no chain provided
        elif spot > 0 and chain_results is None:
            fetch_chain_enabled = os.getenv("REGIME_V4_FETCH_CHAIN", "0").lower() in ("1", "true", "yes")
            if fetch_chain_enabled:
                try:
                    # Fetch chain with 20% strike range for skew/term calculation
                    fetched_chain = self.market_data.option_chain(
                        symbol, strike_range=0.20, spot=spot
                    )
                    if fetched_chain:
                        adapted_chain = self._adapt_chain_to_raw_schema(fetched_chain)
                        skew_25d = IVPointService.compute_skew_25d_from_chain(
                            adapted_chain, spot, as_of, target_dte=30.0
                        )
                        term_slope = IVPointService.compute_term_slope(
                            adapted_chain, spot, as_of
                        )
                except Exception as e:
                    logger.warning(f"Failed to fetch/compute chain for {symbol}: {e}")

        if skew_25d is None: quality_flags["skew_missing"] = True
        if term_slope is None: quality_flags["term_missing"] = True

        # 5. Classification (V4: skew and term now contribute to score)
        f_rank = iv_rank if iv_rank is not None else 50.0
        f_spread = (iv_rv_spread * 100) if iv_rv_spread is not None else 0

        # V4: Scale skew and term to contribute to score
        # skew_25d is typically in range [-0.1, 0.3], scale by 100 for score contribution
        # Positive skew (puts more expensive) indicates fear/risk
        f_skew = (skew_25d * 100) if skew_25d is not None else 0

        # term_slope is IV_90d - IV_30d, typically in range [-0.1, 0.1]
        # Negative slope (backwardation) indicates near-term fear
        f_term = (-term_slope * 100) if term_slope is not None else 0

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
