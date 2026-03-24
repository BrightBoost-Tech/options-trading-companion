"""
Forecast adjustments around catalytic events.

Produces EventAdjustment multipliers that modify EV, PoP, and sizing
based on proximity to known events. The policy layer decides whether
to act on these — this module only computes the adjustments.

Adjustment types:
- Pre-earnings: widen confidence intervals, reduce sizing
- Post-earnings: detect IV crush, flag for exit
- Near ex-div: adjust put/call parity
- Opex week: increase gamma sensitivity
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from packages.quantum.events.event_engine import EventSignal
from packages.quantum.events.event_scorer import EventScore

logger = logging.getLogger(__name__)


@dataclass
class EventAdjustment:
    """
    Multipliers to apply to forecasts near events.

    All multipliers default to 1.0 (no change).
    Values < 1.0 reduce; > 1.0 amplify.
    """
    # Core multipliers
    ev_multiplier: float = 1.0            # Scale expected value
    pop_multiplier: float = 1.0           # Scale probability of profit
    sizing_multiplier: float = 1.0        # Scale position size
    confidence_width_multiplier: float = 1.0  # Widen confidence intervals

    # Flags for the policy layer
    require_defined_risk: bool = False     # Force spreads, no naked
    suggest_exit: bool = False             # Post-event IV crush detected
    suppress_new_entry: bool = False       # Too close to event

    # Context
    reason: str = ""
    event_type: str = ""
    days_to_event: int = 999

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ev_multiplier": round(self.ev_multiplier, 3),
            "pop_multiplier": round(self.pop_multiplier, 3),
            "sizing_multiplier": round(self.sizing_multiplier, 3),
            "confidence_width_multiplier": round(self.confidence_width_multiplier, 3),
            "require_defined_risk": self.require_defined_risk,
            "suggest_exit": self.suggest_exit,
            "suppress_new_entry": self.suppress_new_entry,
            "reason": self.reason,
            "event_type": self.event_type,
            "days_to_event": self.days_to_event,
        }


def compute_event_adjustment(
    signal: EventSignal,
    score: EventScore,
    is_credit_strategy: bool = True,
    current_iv: float = 0.0,
    historical_iv: float = 0.0,
) -> EventAdjustment:
    """
    Compute forecast adjustments based on event signal and score.

    Args:
        signal: EventSignal from event engine
        score: EventScore from event scorer
        is_credit_strategy: True for premium selling, False for debit
        current_iv: Current ATM IV
        historical_iv: Typical non-event IV baseline

    Returns:
        EventAdjustment with multipliers for EV, PoP, sizing
    """
    adj = EventAdjustment()

    if not signal.events or not signal.nearest_event:
        return adj

    nearest = signal.nearest_event
    adj.event_type = nearest.event_type
    adj.days_to_event = nearest.days_until

    # --- Pre-Earnings Adjustments ---
    if nearest.event_type == "earnings":
        adj = _adjust_for_earnings(adj, nearest.days_until, is_credit_strategy, score)

    # --- Ex-Dividend Adjustments ---
    elif nearest.event_type == "ex_dividend":
        adj = _adjust_for_ex_div(adj, nearest.days_until, is_credit_strategy)

    # --- Opex Adjustments ---
    elif nearest.event_type == "opex":
        adj = _adjust_for_opex(adj, nearest.days_until, is_credit_strategy)

    # --- Post-Event IV Crush Detection ---
    if current_iv > 0 and historical_iv > 0:
        iv_ratio = current_iv / historical_iv
        if iv_ratio < 0.75 and nearest.days_until <= 0:
            # IV crushed after event — flag for exit on credit strategies
            if is_credit_strategy:
                adj.suggest_exit = True
                adj.reason = f"IV crush detected (IV ratio {iv_ratio:.2f})"

    # --- Biotech Amplifier ---
    if signal.is_biotech:
        adj.sizing_multiplier *= 0.7  # Always reduce sizing for biotech
        adj.confidence_width_multiplier *= 1.3
        if adj.reason:
            adj.reason += " [biotech amplified]"

    return adj


def _adjust_for_earnings(
    adj: EventAdjustment,
    days: int,
    is_credit: bool,
    score: EventScore,
) -> EventAdjustment:
    """Adjustments for upcoming earnings."""
    if days <= 0:
        # Post-earnings: IV has likely crushed
        adj.reason = "Post-earnings (IV crush likely)"
        if is_credit:
            adj.suggest_exit = True
        return adj

    if days <= 1:
        # Earnings imminent — suppress new entries
        adj.suppress_new_entry = True
        adj.sizing_multiplier = 0.0
        adj.require_defined_risk = True
        adj.confidence_width_multiplier = 2.5
        adj.reason = f"Earnings in {days}d — suppress new entries"
        return adj

    if days <= 3:
        # Very close — heavy adjustments
        adj.sizing_multiplier = 0.3
        adj.ev_multiplier = 0.7
        adj.pop_multiplier = 0.8
        adj.confidence_width_multiplier = 2.0
        adj.require_defined_risk = True
        adj.reason = f"Earnings in {days}d — heavy sizing reduction"
        return adj

    if days <= 7:
        # Earnings week — moderate adjustments
        adj.sizing_multiplier = 0.6
        adj.ev_multiplier = 0.85
        adj.confidence_width_multiplier = 1.5
        adj.require_defined_risk = True
        adj.reason = f"Earnings in {days}d — moderate adjustment"
        return adj

    if days <= 14:
        # Approaching — slight adjustment
        adj.sizing_multiplier = 0.85
        adj.confidence_width_multiplier = 1.2
        adj.reason = f"Earnings in {days}d — slight adjustment"
        return adj

    # >14 days: no adjustment
    return adj


def _adjust_for_ex_div(
    adj: EventAdjustment,
    days: int,
    is_credit: bool,
) -> EventAdjustment:
    """
    Adjustments near ex-dividend dates.

    Near ex-div, short calls face early assignment risk.
    Put-call parity shifts by the dividend amount.
    """
    if days <= 2:
        adj.ev_multiplier = 0.9
        adj.require_defined_risk = True
        adj.reason = f"Ex-div in {days}d — assignment risk on short calls"
    elif days <= 7:
        adj.confidence_width_multiplier = 1.1
        adj.reason = f"Ex-div in {days}d — minor adjustment"

    return adj


def _adjust_for_opex(
    adj: EventAdjustment,
    days: int,
    is_credit: bool,
) -> EventAdjustment:
    """
    Adjustments near options expiration.

    Opex brings pin risk and gamma spikes.
    """
    if days <= 2:
        adj.sizing_multiplier = 0.8
        adj.confidence_width_multiplier = 1.3
        adj.reason = f"Opex in {days}d — gamma/pin risk"
    elif days <= 5:
        adj.confidence_width_multiplier = 1.1
        adj.reason = f"Opex in {days}d — minor gamma awareness"

    return adj
