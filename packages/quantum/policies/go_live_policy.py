"""
Go-Live Readiness Gate Policy (Policy-as-Code)

Pure policy functions that evaluate readiness for live trading execution.
No DB access, no HTTP - just deterministic policy logic.

Gate Matrix:
1. paused=True => allowed=False, reason=paused_globally
2. mode=paper => allowed=False, reason=mode_is_paper_only
3. mode=micro_live + paper_ready=False => allowed=False, reason=paper_milestones_incomplete
4. mode=micro_live + paper_ready=True => allowed=True, requires_manual_approval=True, reason=micro_live_restricted
5. mode=live + overall_ready=False => allowed=False, reason=historical_validation_failed
6. mode=live + overall_ready=True => allowed=True, requires_manual_approval=False, reason=fully_authorized
"""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional


@dataclass
class GateDecision:
    """
    Result of evaluating the go-live readiness gate.

    Attributes:
        allowed: Whether live execution is permitted
        requires_manual_approval: If True, auto-live jobs are blocked but manual approval paths work
        reason: Machine-readable reason code for the decision
        context: Additional context for debugging/UI display
    """
    allowed: bool
    requires_manual_approval: bool
    reason: str
    context: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "allowed": self.allowed,
            "requires_manual_approval": self.requires_manual_approval,
            "reason": self.reason,
            "context": self.context,
        }


def evaluate_go_live_gate(
    ops_state: Dict[str, Any],
    user_readiness: Dict[str, Any]
) -> GateDecision:
    """
    Evaluate the go-live readiness gate based on ops state and user readiness.

    This is a pure policy function with no side effects.

    Args:
        ops_state: Dict from get_global_ops_control() containing:
            - mode: "paper" | "micro_live" | "live"
            - paused: bool
            - pause_reason: Optional[str]
        user_readiness: Dict from GoLiveValidationService.get_or_create_state() containing:
            - paper_ready: bool
            - overall_ready: bool

    Returns:
        GateDecision with allowed, requires_manual_approval, reason, and context

    Safety: If ops_state is missing keys, defaults to DENY (paused=True, mode=paper).
    If user_readiness is missing keys, defaults to not ready (False).
    """
    # Extract ops state with safe defaults (fail-safe to DENY)
    paused = ops_state.get("paused", True)  # Default to paused if missing
    pause_reason = ops_state.get("pause_reason")
    mode = ops_state.get("mode", "paper")  # Default to paper mode if missing

    # Extract user readiness with safe defaults (not ready)
    paper_ready = user_readiness.get("paper_ready", False)
    overall_ready = user_readiness.get("overall_ready", False)

    # Build context for debugging/UI
    context = {
        "mode": mode,
        "paused": paused,
        "pause_reason": pause_reason,
        "paper_ready": paper_ready,
        "overall_ready": overall_ready,
    }

    # Gate Matrix Evaluation (ordered by priority)

    # 1. Global pause check (highest priority)
    if paused:
        return GateDecision(
            allowed=False,
            requires_manual_approval=False,
            reason="paused_globally",
            context=context,
        )

    # 2. Paper mode - no live execution allowed
    if mode == "paper":
        return GateDecision(
            allowed=False,
            requires_manual_approval=False,
            reason="mode_is_paper_only",
            context=context,
        )

    # 3. Micro-live mode
    if mode == "micro_live":
        if not paper_ready:
            return GateDecision(
                allowed=False,
                requires_manual_approval=False,
                reason="paper_milestones_incomplete",
                context=context,
            )
        # Paper ready in micro_live mode - allowed but requires manual approval
        return GateDecision(
            allowed=True,
            requires_manual_approval=True,
            reason="micro_live_restricted",
            context=context,
        )

    # 4. Live mode
    if mode == "live":
        if not overall_ready:
            return GateDecision(
                allowed=False,
                requires_manual_approval=False,
                reason="historical_validation_failed",
                context=context,
            )
        # Fully authorized for live trading
        return GateDecision(
            allowed=True,
            requires_manual_approval=False,
            reason="fully_authorized",
            context=context,
        )

    # Unknown mode - fail safe to DENY
    return GateDecision(
        allowed=False,
        requires_manual_approval=False,
        reason="unknown_mode",
        context=context,
    )
