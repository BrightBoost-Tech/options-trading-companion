"""
Event impact scoring for options strategies.

Scores how much an upcoming catalyst affects options pricing and
strategy selection. Two composite scores:

- event_risk_score (0-100): higher = more dangerous for premium sellers
- event_opportunity_score (0-100): higher = better for event-aware strategies

Also computes:
- iv_event_premium: current IV vs non-event baseline
- expected_move: straddle-implied move estimate
- days_to_event proximity weighting
"""

import logging
import math
from dataclasses import dataclass
from typing import Any, Dict, Optional

from packages.quantum.events.event_engine import EventSignal, CatalystEvent

logger = logging.getLogger(__name__)


@dataclass
class EventScore:
    """Scored event impact for a symbol."""
    symbol: str

    # Composite scores
    event_risk_score: float = 0.0          # 0-100 (higher = more risk for sellers)
    event_opportunity_score: float = 0.0   # 0-100 (higher = better event play)

    # Components
    days_to_event: int = 999
    event_type: str = ""
    iv_event_premium: float = 0.0          # current_iv - baseline_iv
    expected_move_pct: float = 0.0         # straddle-implied move %
    earnings_surprise_factor: float = 0.0  # historical surprise magnitude

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_risk_score": round(self.event_risk_score, 1),
            "event_opportunity_score": round(self.event_opportunity_score, 1),
            "days_to_event": self.days_to_event,
            "event_type": self.event_type,
            "iv_event_premium": round(self.iv_event_premium, 4),
            "expected_move_pct": round(self.expected_move_pct, 4),
        }


def score_event_impact(
    signal: EventSignal,
    current_iv: float = 0.0,
    historical_iv: float = 0.0,
    atm_straddle_price: float = 0.0,
    spot_price: float = 0.0,
    avg_earnings_move_pct: float = 0.0,
) -> EventScore:
    """
    Score the impact of upcoming events on options pricing.

    Args:
        signal: EventSignal from the event engine
        current_iv: Current ATM implied volatility
        historical_iv: Typical non-event IV for this name (baseline)
        atm_straddle_price: ATM straddle price (for expected move)
        spot_price: Current underlying price
        avg_earnings_move_pct: Historical average earnings move (0-1)

    Returns:
        EventScore with composite risk and opportunity scores
    """
    result = EventScore(symbol=signal.symbol)

    if not signal.events:
        return result

    nearest = signal.nearest_event
    if not nearest:
        return result

    result.days_to_event = nearest.days_until
    result.event_type = nearest.event_type

    # --- IV Event Premium ---
    if current_iv > 0 and historical_iv > 0:
        result.iv_event_premium = current_iv - historical_iv

    # --- Expected Move (straddle-implied) ---
    if atm_straddle_price > 0 and spot_price > 0:
        result.expected_move_pct = atm_straddle_price / spot_price

    # --- Risk Score (for premium sellers) ---
    risk = 0.0

    # Proximity: closer events = higher risk (exponential decay)
    if nearest.days_until <= 0:
        proximity_risk = 0.0  # Event passed — no forward risk
    elif nearest.days_until <= 1:
        proximity_risk = 95.0
    elif nearest.days_until <= 3:
        proximity_risk = 80.0
    elif nearest.days_until <= 7:
        proximity_risk = 50.0
    elif nearest.days_until <= 14:
        proximity_risk = 25.0
    else:
        proximity_risk = 5.0

    # Event type multiplier
    type_multiplier = _event_type_risk_weight(nearest.event_type)

    # IV premium component: higher premium = more risk (market expects move)
    iv_premium_risk = 0.0
    if result.iv_event_premium > 0 and historical_iv > 0:
        # How much IV is elevated as fraction of baseline
        iv_ratio = result.iv_event_premium / historical_iv
        iv_premium_risk = min(30, iv_ratio * 100)

    # Biotech amplifier
    biotech_amp = 1.3 if signal.is_biotech else 1.0

    risk = (proximity_risk * 0.5 + iv_premium_risk * 0.3) * type_multiplier * biotech_amp

    # Multiple events compound risk
    if len(signal.events) > 1:
        risk *= 1.0 + 0.1 * (len(signal.events) - 1)

    result.event_risk_score = min(100.0, max(0.0, risk))

    # --- Opportunity Score (for event-aware strategies) ---
    # High IV premium + known event = good for straddles/strangles or IV crush plays
    opp = 0.0

    # IV premium creates opportunity for vol strategies
    if result.iv_event_premium > 0:
        opp += min(40, result.iv_event_premium / 0.10 * 20)

    # Known earnings date with high confidence = better timing
    if nearest.event_type == "earnings" and nearest.confidence >= 0.8:
        opp += 20.0

    # Optimal timing: 2-5 days before event (enough to capture IV expansion)
    if 2 <= nearest.days_until <= 5:
        opp += 25.0
    elif 1 <= nearest.days_until <= 1:
        opp += 15.0  # Day-of is riskier but still opportunity

    # Historical surprise factor
    if avg_earnings_move_pct > 0:
        result.earnings_surprise_factor = avg_earnings_move_pct
        opp += min(15, avg_earnings_move_pct * 100)

    result.event_opportunity_score = min(100.0, max(0.0, opp))

    return result


def _event_type_risk_weight(event_type: str) -> float:
    """Weight factor by event type (how much it typically moves options)."""
    weights = {
        "earnings": 1.0,        # Highest impact
        "fda_decision": 1.2,    # Even higher for biotech
        "ex_dividend": 0.3,     # Lower impact (predictable)
        "opex": 0.4,            # Pin risk, gamma
        "index_rebalance": 0.2, # Usually small
    }
    return weights.get(event_type, 0.5)
