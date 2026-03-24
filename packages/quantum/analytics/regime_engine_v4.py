"""
Regime Engine V4 — Continuous Multi-Factor Regime State

Replaces discrete state labels (NORMAL, CHOP, SHOCK) with a continuous
regime vector that downstream systems can query without bucketing.

RegimeVector dimensions:
- volatility_regime: 0-1 (0=calm, 1=crisis)
- trend_strength: -1 to 1 (negative=downtrend, positive=uptrend)
- mean_reversion: 0-1 (0=trending, 1=mean-reverting)
- correlation_regime: 0-1 (0=dispersed, 1=correlated)
- liquidity_regime: 0-1 (0=thin, 1=deep)
- event_density: 0-1 (0=quiet, 1=catalyst-heavy)

Runs in parallel with regime_engine_v3 — NOT a replacement.
Feature flag: REGIME_V4_ENABLED (default false)

When disabled, all callers use v3 as before.
"""

import logging
import math
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import numpy as np

from packages.quantum.common_enums import RegimeState

logger = logging.getLogger(__name__)


def is_regime_v4_enabled() -> bool:
    """Check if v4 regime engine is enabled."""
    return os.environ.get("REGIME_V4_ENABLED", "").lower() in ("1", "true")


# ---------------------------------------------------------------------------
# Core data structure
# ---------------------------------------------------------------------------

@dataclass
class RegimeVector:
    """
    Continuous multi-factor regime state.

    All dimensions are continuous — no discrete buckets. Downstream systems
    can threshold as needed or use the raw values for continuous adjustment.
    """
    # Primary dimensions
    volatility_regime: float = 0.3     # 0=calm, 1=crisis
    trend_strength: float = 0.0        # -1=strong downtrend, 1=strong uptrend
    mean_reversion: float = 0.5        # 0=trending, 1=mean-reverting
    correlation_regime: float = 0.5    # 0=dispersed, 1=highly correlated
    liquidity_regime: float = 0.7      # 0=thin/illiquid, 1=deep/liquid
    event_density: float = 0.0         # 0=quiet, 1=catalyst-heavy

    # Derived convenience scores
    risk_score: float = 50.0           # 0-100 composite risk
    risk_scaler: float = 1.0           # sizing multiplier

    # Metadata
    as_of_ts: str = ""
    engine_version: str = "v4_continuous"
    data_quality: Dict[str, bool] = field(default_factory=dict)

    @property
    def label(self) -> str:
        """
        Backward-compatible discrete label derived from continuous state.

        Maps the continuous regime vector to legacy RegimeState labels
        so existing code that reads .label continues to work.
        """
        if self.volatility_regime > 0.8:
            return "shock"
        if self.volatility_regime > 0.6:
            if self.trend_strength > 0.2:
                return "rebound"
            return "elevated"
        if self.mean_reversion > 0.7 and abs(self.trend_strength) < 0.2:
            return "chop"
        if self.volatility_regime < 0.2 and abs(self.trend_strength) < 0.3:
            return "suppressed"
        return "normal"

    @property
    def regime_state(self) -> RegimeState:
        """Backward-compatible RegimeState enum."""
        label_to_state = {
            "suppressed": RegimeState.SUPPRESSED,
            "normal": RegimeState.NORMAL,
            "chop": RegimeState.CHOP,
            "elevated": RegimeState.ELEVATED,
            "rebound": RegimeState.REBOUND,
            "shock": RegimeState.SHOCK,
        }
        return label_to_state.get(self.label, RegimeState.NORMAL)

    @property
    def scoring_regime(self) -> str:
        """Map to legacy 3-state scoring regime."""
        if self.volatility_regime > 0.8:
            return "panic"
        if self.volatility_regime > 0.6:
            return "high_vol"
        return "normal"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "volatility_regime": round(self.volatility_regime, 4),
            "trend_strength": round(self.trend_strength, 4),
            "mean_reversion": round(self.mean_reversion, 4),
            "correlation_regime": round(self.correlation_regime, 4),
            "liquidity_regime": round(self.liquidity_regime, 4),
            "event_density": round(self.event_density, 4),
            "risk_score": round(self.risk_score, 2),
            "risk_scaler": round(self.risk_scaler, 3),
            "label": self.label,
            "scoring_regime": self.scoring_regime,
            "as_of_ts": self.as_of_ts,
            "engine_version": self.engine_version,
            "data_quality": self.data_quality,
        }

    def to_feature_dict(self) -> Dict[str, float]:
        """Flat feature dict for suggestion logging / decision context."""
        return {
            "regime_v4_vol": self.volatility_regime,
            "regime_v4_trend": self.trend_strength,
            "regime_v4_mr": self.mean_reversion,
            "regime_v4_corr": self.correlation_regime,
            "regime_v4_liq": self.liquidity_regime,
            "regime_v4_event": self.event_density,
            "regime_v4_risk": self.risk_score,
        }


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class RegimeEngineV4:
    """
    Computes continuous regime vectors from market data.

    Parallel to v3 — does NOT replace it. Use is_regime_v4_enabled()
    to check before calling.
    """

    BASKET = ["SPY", "QQQ", "IWM", "TLT", "HYG", "XLF", "XLK", "XLE"]

    def __init__(self, market_data=None):
        """
        Args:
            market_data: MarketDataTruthLayer instance (optional — degrades gracefully)
        """
        self.market_data = market_data

    def compute(
        self,
        as_of_ts: Optional[datetime] = None,
        surface_metrics: Optional[Dict[str, Any]] = None,
        event_signals: Optional[Dict[str, Any]] = None,
        vix_data: Optional[Dict[str, float]] = None,
    ) -> RegimeVector:
        """
        Compute the continuous regime vector.

        Args:
            as_of_ts: Timestamp (default: now UTC)
            surface_metrics: IV surface metrics from surfaces module
            event_signals: Event density data from events module
            vix_data: VIX data dict with keys: vix, vix_9d, vix_3m

        Returns:
            RegimeVector with all dimensions populated
        """
        if as_of_ts is None:
            as_of_ts = datetime.now(timezone.utc)

        vec = RegimeVector(as_of_ts=as_of_ts.isoformat())
        quality = {}

        # --- 1. Volatility Regime ---
        vec.volatility_regime, quality["vol"] = self._compute_volatility(
            as_of_ts, vix_data
        )

        # --- 2. Trend Strength ---
        vec.trend_strength, quality["trend"] = self._compute_trend(as_of_ts)

        # --- 3. Mean Reversion ---
        vec.mean_reversion, quality["mr"] = self._compute_mean_reversion(as_of_ts)

        # --- 4. Correlation Regime ---
        vec.correlation_regime, quality["corr"] = self._compute_correlation(as_of_ts)

        # --- 5. Liquidity Regime ---
        vec.liquidity_regime, quality["liq"] = self._compute_liquidity()

        # --- 6. Event Density ---
        vec.event_density = self._compute_event_density(event_signals)
        quality["event"] = True  # Always available (defaults to 0)

        # --- Composite Risk Score ---
        vec.risk_score = self._compute_risk_score(vec)
        vec.risk_scaler = self._compute_risk_scaler(vec)
        vec.data_quality = quality

        logger.info(
            f"regime_v4: vol={vec.volatility_regime:.2f} trend={vec.trend_strength:+.2f} "
            f"mr={vec.mean_reversion:.2f} corr={vec.correlation_regime:.2f} "
            f"liq={vec.liquidity_regime:.2f} event={vec.event_density:.2f} "
            f"risk={vec.risk_score:.0f} label={vec.label}"
        )

        return vec

    # ------------------------------------------------------------------
    # Factor computations
    # ------------------------------------------------------------------

    def _compute_volatility(
        self,
        as_of: datetime,
        vix_data: Optional[Dict[str, float]] = None,
    ) -> tuple:
        """
        Volatility regime from VIX + realized vol.

        Maps to 0-1: VIX 12 → 0.1, VIX 20 → 0.4, VIX 30 → 0.7, VIX 50 → 1.0
        """
        vix = None

        # Try VIX data if provided
        if vix_data:
            vix = vix_data.get("vix")

        # Try to fetch SPY realized vol as fallback
        if vix is None and self.market_data:
            try:
                bars = self.market_data.daily_bars(
                    "SPY",
                    as_of - timedelta(days=30),
                    as_of,
                )
                if bars and len(bars) >= 21:
                    closes = [b["close"] for b in bars]
                    rets = np.diff(closes) / closes[:-1]
                    rv = float(np.std(rets[-20:]) * np.sqrt(252))
                    # Convert RV to VIX-equivalent (roughly: VIX ≈ RV * 100)
                    vix = rv * 100
            except Exception as e:
                logger.debug(f"regime_v4_vol_fetch_error: {e}")

        if vix is None:
            return 0.3, False  # Neutral default

        # Sigmoid-like mapping: VIX to 0-1
        # VIX 12 → 0.1, VIX 20 → 0.35, VIX 30 → 0.65, VIX 50 → 0.95
        regime = 1.0 / (1.0 + math.exp(-0.1 * (vix - 25)))
        return _clamp(regime, 0.0, 1.0), True

    def _compute_trend(self, as_of: datetime) -> tuple:
        """
        Trend strength from SPY price vs moving averages.

        -1 = strong downtrend, 0 = flat, +1 = strong uptrend
        """
        if not self.market_data:
            return 0.0, False

        try:
            bars = self.market_data.daily_bars(
                "SPY",
                as_of - timedelta(days=100),
                as_of,
            )
            if not bars or len(bars) < 50:
                return 0.0, False

            closes = [b["close"] for b in bars]
            price = closes[-1]
            sma20 = sum(closes[-20:]) / 20
            sma50 = sum(closes[-50:]) / 50

            # Trend = weighted average of price vs SMAs
            trend_20 = (price - sma20) / sma20  # Short-term
            trend_50 = (price - sma50) / sma50  # Medium-term

            # Combine with short-term bias
            raw = trend_20 * 0.6 + trend_50 * 0.4

            # Scale to [-1, 1] — 5% above/below SMA = ±1
            strength = _clamp(raw / 0.05, -1.0, 1.0)
            return strength, True

        except Exception as e:
            logger.debug(f"regime_v4_trend_error: {e}")
            return 0.0, False

    def _compute_mean_reversion(self, as_of: datetime) -> tuple:
        """
        Mean reversion tendency from price oscillation around SMA.

        0 = strongly trending, 1 = strongly mean-reverting

        Uses variance ratio test: if returns are mean-reverting,
        var(2-day returns) < 2 * var(1-day returns).
        """
        if not self.market_data:
            return 0.5, False

        try:
            bars = self.market_data.daily_bars(
                "SPY",
                as_of - timedelta(days=60),
                as_of,
            )
            if not bars or len(bars) < 40:
                return 0.5, False

            closes = [b["close"] for b in bars]

            # 1-day returns
            rets_1d = [(closes[i] - closes[i-1]) / closes[i-1]
                       for i in range(1, len(closes))]

            # 2-day returns
            rets_2d = [(closes[i] - closes[i-2]) / closes[i-2]
                       for i in range(2, len(closes))]

            if len(rets_1d) < 20 or len(rets_2d) < 20:
                return 0.5, False

            var_1d = _variance(rets_1d[-20:])
            var_2d = _variance(rets_2d[-20:])

            if var_1d <= 0:
                return 0.5, False

            # Variance ratio: VR = var(2d) / (2 * var(1d))
            # VR < 1 → mean-reverting, VR > 1 → trending
            vr = var_2d / (2.0 * var_1d)

            # Map: VR=0.5 → MR=0.9, VR=1.0 → MR=0.5, VR=1.5 → MR=0.1
            mr = _clamp(1.0 - (vr - 0.5), 0.0, 1.0)
            return mr, True

        except Exception as e:
            logger.debug(f"regime_v4_mr_error: {e}")
            return 0.5, False

    def _compute_correlation(self, as_of: datetime) -> tuple:
        """
        Cross-asset correlation from basket.

        0 = dispersed (assets moving independently)
        1 = highly correlated (risk-on/risk-off moves)
        """
        if not self.market_data:
            return 0.5, False

        try:
            corrs = []
            spy_bars = self.market_data.daily_bars(
                "SPY", as_of - timedelta(days=30), as_of
            )
            if not spy_bars or len(spy_bars) < 21:
                return 0.5, False

            spy_closes = [b["close"] for b in spy_bars]
            spy_rets = np.diff(spy_closes) / spy_closes[:-1]
            spy_rets = spy_rets[-20:]

            if len(spy_rets) < 20:
                return 0.5, False

            for sym in ["QQQ", "IWM", "XLF", "XLK", "XLE"]:
                try:
                    bars = self.market_data.daily_bars(
                        sym, as_of - timedelta(days=30), as_of
                    )
                    if not bars or len(bars) < 21:
                        continue
                    closes = [b["close"] for b in bars]
                    rets = np.diff(closes) / closes[:-1]
                    rets = rets[-20:]
                    if len(rets) == 20:
                        c = float(np.corrcoef(spy_rets, rets)[0, 1])
                        if not np.isnan(c):
                            corrs.append(abs(c))
                except Exception:
                    continue

            if not corrs:
                return 0.5, False

            avg_corr = sum(corrs) / len(corrs)
            # Map: avg_corr 0.3 → 0.15, 0.5 → 0.5, 0.8 → 0.85
            regime = _clamp((avg_corr - 0.2) / 0.6, 0.0, 1.0)
            return regime, True

        except Exception as e:
            logger.debug(f"regime_v4_corr_error: {e}")
            return 0.5, False

    def _compute_liquidity(self) -> tuple:
        """
        Liquidity regime from basket bid-ask spreads.

        0 = thin/illiquid, 1 = deep/liquid
        """
        if not self.market_data:
            return 0.7, False  # Assume OK

        try:
            snapshots = self.market_data.snapshot_many(self.BASKET)
            spread_pcts = []

            for sym in self.BASKET:
                snap = snapshots.get(sym, {})
                quote = snap.get("quote", {})
                bid = quote.get("bid")
                ask = quote.get("ask")
                mid = quote.get("mid")

                if bid and ask and mid and mid > 0:
                    spread = (ask - bid) / mid
                    if spread >= 0:
                        spread_pcts.append(spread)

            if not spread_pcts:
                return 0.7, False

            median_spread = sorted(spread_pcts)[len(spread_pcts) // 2]

            # Map: 0.05% spread → 0.95 (very liquid), 0.5% → 0.3, 1% → 0.1
            regime = _clamp(1.0 - (median_spread / 0.005), 0.0, 1.0)
            return regime, True

        except Exception as e:
            logger.debug(f"regime_v4_liq_error: {e}")
            return 0.7, False

    def _compute_event_density(
        self,
        event_signals: Optional[Dict[str, Any]] = None,
    ) -> float:
        """
        Event density from events module.

        0 = quiet period, 1 = many catalysts upcoming
        """
        if not event_signals:
            return 0.0

        # Count symbols with events in next 7 days
        total = len(event_signals)
        if total == 0:
            return 0.0

        with_events = sum(
            1 for sig in event_signals.values()
            if hasattr(sig, "is_earnings_week") and sig.is_earnings_week
        )

        # Also count from dict representation
        if with_events == 0:
            with_events = sum(
                1 for sig in event_signals.values()
                if isinstance(sig, dict) and sig.get("is_earnings_week")
            )

        density = with_events / max(total, 1)
        return _clamp(density, 0.0, 1.0)

    # ------------------------------------------------------------------
    # Composite scores
    # ------------------------------------------------------------------

    def _compute_risk_score(self, vec: RegimeVector) -> float:
        """
        Composite risk score 0-100 from regime vector.

        Weights:
        - Volatility: 35% (highest weight — vol is the primary risk driver)
        - Correlation: 20% (systemic risk indicator)
        - Inverse liquidity: 15% (illiquidity = risk)
        - Inverse trend: 15% (downtrend = risk)
        - Event density: 10%
        - Mean reversion: 5% (choppy = slightly higher risk)
        """
        risk = (
            vec.volatility_regime * 35.0
            + vec.correlation_regime * 20.0
            + (1.0 - vec.liquidity_regime) * 15.0
            + max(0, -vec.trend_strength) * 15.0  # Only downtrend adds risk
            + vec.event_density * 10.0
            + vec.mean_reversion * 5.0
        )
        return _clamp(risk, 0.0, 100.0)

    def _compute_risk_scaler(self, vec: RegimeVector) -> float:
        """
        Sizing scaler from risk score.

        risk 0-20 → 1.2x, 20-50 → 1.0x, 50-70 → 0.7x, 70-100 → 0.5x
        """
        r = vec.risk_score
        if r < 20:
            return 1.2
        if r < 50:
            return 1.0
        if r < 70:
            return 0.7
        return 0.5


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _variance(values: list) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    return sum((x - mean) ** 2 for x in values) / (n - 1)
