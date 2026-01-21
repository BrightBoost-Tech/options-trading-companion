"""
Policy-as-Code layer for go-live readiness gates.

This module provides deterministic, pure policy functions that combine
global ops control state and user readiness to make gate decisions.
"""

from packages.quantum.policies.go_live_policy import (
    GateDecision,
    evaluate_go_live_gate,
)

__all__ = [
    "GateDecision",
    "evaluate_go_live_gate",
]
